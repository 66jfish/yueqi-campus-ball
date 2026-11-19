"""
球局核心业务测试（真实跑通，不依赖 MySQL）
====================================================================
覆盖：
    ① 发起球局：成功 / 时间非法 / ★同场地同时段冲突 / 同场地不同时段 / 不同场地 / ★发起人时间冲突
    ② 球局列表：sport_type 筛选（不传返回全部）/ 校区 / 关键词 / 场地模糊 / 分页 / 只看未满 / match_score
    ③ 球局详情：聚合信息 + 核销统计 + is_creator + 匿名可读
    ④ 报名：成功 / 重复 / ★用户时间冲突 / ★满员进候补 / 关闭候补后拒绝 / 信誉分门槛 / 已截止
    ⑤ 退出：★候补自动补位 / 未报名 / 已开始 / 开球前截止
    ⑥ 核销：★非发起人拒绝 / ★核销触发惰性结算 / 幂等 / 迟到 / 窗口未开放 / 已结算拒绝 /
            一键核销 + 名单 / 与缺席判定联动
====================================================================
"""

import asyncio
import itertools
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.constants import (
    MATCH_SCORE_PLACEHOLDER,
    CheckinStatus,
    GameStatus,
    RegistrationStatus,
    SettleStatus,
)
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.middleware import hooks as hook_module
from app.models import CheckinRecord, Game, Registration, User
from app.services import ai_profile as ai_service
from app.services import blacklist as blacklist_service

# ----------------------------------------------------------------------
# SQLite 装配：去掉 MySQL 专有建表参数，BIGINT 主键换 INTEGER（SQLite 才自增）
# ----------------------------------------------------------------------
for _table in Base.metadata.tables.values():
    for _key in ("mysql_charset", "mysql_collate", "mysql_engine"):
        _table.kwargs.pop(_key, None)
    for _col in _table.columns:
        if isinstance(_col.type, BigInteger):
            _col.type = Integer()

engine = create_async_engine(
    "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
)
# autoflush=False 与生产会话（app/db/session.py）保持一致
TestSessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def _test_session_scope():
    async with TestSessionLocal() as session:
        yield session


async def _override_get_db():
    async with TestSessionLocal() as session:
        yield session


@pytest.fixture(scope="module", autouse=True)
def _prepare_database():
    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    hook_module.set_session_scope_factory(_test_session_scope)
    ai_service.set_session_scope_factory(_test_session_scope)  # 画像后台任务也连测试库
    app.dependency_overrides[get_db] = _override_get_db
    # 小黑屋缓存是进程级的、按 user_id 索引：换测试库必须清空（否则上一个测试文件的封禁状态会串号）
    blacklist_service.ban_cache.clear()
    yield
    app.dependency_overrides.clear()
    blacklist_service.ban_cache.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ======================================================================
# 测试工具
# ======================================================================
# 每个用例默认使用独立场地，避免「同场地同时段」互相干扰；
# 需要验证场地冲突的用例会显式传相同的 venue_name。
_venue_seq = itertools.count(1)


def _unique_venue() -> str:
    return f"老校区体育馆{next(_venue_seq)}号场"


def _signup_user(client, student_no: str, nickname: str, credit: int | None = None) -> dict:
    """注册 + 登录，返回 {user_id, headers}"""
    client.post(
        "/api/v1/auth/register",
        json={
            "student_no": student_no,
            "nickname": nickname,
            "password": "abc123456",
            "phone": f"138{student_no[-6:]}",
            "campus": "老校区",
            "skill_level": 3,
        },
    )
    body = client.post("/api/v1/auth/login", json={"account": student_no, "password": "abc123456"}).json()
    assert body["code"] == 0, body
    token = body["data"]["token"]["access_token"]
    user_id = body["data"]["user"]["id"]

    if credit is not None:
        _update_user(user_id, credit_score=credit)

    return {"user_id": user_id, "headers": {"Authorization": f"Bearer {token}"}}


def _game_payload(**overrides) -> dict:
    """默认：现在 +1 小时开球、核销窗口已开放、2 小时后结束、独立场地"""
    now = datetime.now()
    payload = {
        "sport_type": 1,
        "title": "周五晚东区篮球局",
        "description": "水平不限",
        "campus": "老校区",
        "venue_name": _unique_venue(),
        "start_time": (now + timedelta(hours=1)).isoformat(),
        "end_time": (now + timedelta(hours=3)).isoformat(),
        "signup_deadline": (now + timedelta(minutes=30)).isoformat(),
        "checkin_start_time": (now - timedelta(minutes=5)).isoformat(),
        "checkin_end_time": (now + timedelta(hours=2)).isoformat(),
        "max_players": 3,
        "min_players": 2,
    }
    payload.update(overrides)
    return payload


def _create_game(client, headers, expect_ok: bool = True, **overrides) -> dict | None:
    resp = client.post("/api/v1/game", json=_game_payload(**overrides), headers=headers)
    if expect_ok:
        assert resp.status_code == 200, resp.text
        assert resp.json()["code"] == 0, resp.json()
        return resp.json()["data"]
    return resp.json()


def _update_user(user_id: int, **fields):
    async def _op(db):
        user = await db.get(User, user_id)
        for key, value in fields.items():
            setattr(user, key, value)

    _run_db(_op)


def _update_game(game_id: int, **fields):
    async def _op(db):
        game = await db.get(Game, game_id)
        for key, value in fields.items():
            setattr(game, key, value)

    _run_db(_op)


def _get_user(user_id: int) -> dict:
    async def _op(db):
        user = await db.get(User, user_id)
        return {"credit_score": user.credit_score, "absent_count": user.absent_count}

    return _read(_op)


def _get_checkin(game_id: int, user_id: int) -> dict | None:
    async def _op(db):
        record = (
            await db.execute(
                select(CheckinRecord).where(
                    CheckinRecord.game_id == game_id, CheckinRecord.user_id == user_id
                )
            )
        ).scalars().first()
        if not record:
            return None
        return {
            "checkin_status": record.checkin_status,
            "checkin_type": record.checkin_type,
            "checkin_operator_id": record.checkin_operator_id,
            "credit_delta": record.credit_delta,
            "settled": record.settled,
            "remark": record.remark,
        }

    return _read(_op)


def _get_registration(game_id: int, user_id: int) -> dict | None:
    async def _op(db):
        reg = (
            await db.execute(
                select(Registration).where(
                    Registration.game_id == game_id, Registration.user_id == user_id
                )
            )
        ).scalars().first()
        if not reg:
            return None
        return {
            "status": reg.status,
            "is_waitlist": reg.is_waitlist,
            "waitlist_order": reg.waitlist_order,
        }

    return _read(_op)


def _run_db(op):
    async def _run():
        async with TestSessionLocal() as db:
            await op(db)
            await db.commit()

    asyncio.run(_run())


def _read(op):
    async def _run():
        async with TestSessionLocal() as db:
            return await op(db)

    return asyncio.run(_run())


# ======================================================================
# ① 发起球局
# ======================================================================
def test_create_game_success(client):
    """发起成功：报名中、发起人占 1 个名额、自动补核销窗口"""
    host = _signup_user(client, "31000001", "发起人")
    game = _create_game(client, host["headers"])
    assert game["status"] == GameStatus.SIGNING
    assert game["current_players"] == 1
    assert game["creator_id"] == host["user_id"]
    assert game["slots_left"] == 2
    assert game["is_full"] is False
    assert game["creator_nickname"] == "发起人"
    assert game["checkin_start_time"] and game["checkin_end_time"]  # 自动补全
    # 发起人自动报名 + 预生成待结算签到记录
    assert _get_registration(game["id"], host["user_id"])["status"] == RegistrationStatus.SIGNED
    assert _get_checkin(game["id"], host["user_id"])["settled"] == 0


def test_create_game_invalid_time(client):
    """结束时间早于开始时间 → 参数错误（统一响应体，可安全序列化）"""
    host = _signup_user(client, "31000002", "发起人2")
    now = datetime.now()
    body = _create_game(
        client, host["headers"], expect_ok=False,
        start_time=(now + timedelta(hours=3)).isoformat(),
        end_time=(now + timedelta(hours=1)).isoformat(),
        checkin_start_time=(now - timedelta(minutes=5)).isoformat(),
    )
    assert body["code"] == 40000
    assert "结束时间" in body["message"]


def test_create_game_venue_conflict(client):
    """★同场地同时段冲突：同一场地时间重叠 → 40900（换个人发起，避免命中「发起人时间冲突」）"""
    host = _signup_user(client, "31000003", "场地管理员")
    other = _signup_user(client, "31000004", "另一位组织者")
    first = _create_game(client, host["headers"], title="第一场")

    now = datetime.now()
    body = _create_game(
        client, other["headers"], expect_ok=False,
        title="第二场撞场地",
        venue_name=first["venue_name"],                      # 同一场地
        start_time=(now + timedelta(hours=2)).isoformat(),    # 与第一场 19:00~21:00 重叠
        end_time=(now + timedelta(hours=4)).isoformat(),
        signup_deadline=(now + timedelta(minutes=30)).isoformat(),
        checkin_start_time=(now - timedelta(minutes=5)).isoformat(),
        checkin_end_time=(now + timedelta(hours=3)).isoformat(),
    )
    assert body["code"] == 40900
    assert "场地冲突" in body["message"]
    assert "第一场" in body["message"]                       # 提示带上冲突球局，便于用户处理
    assert first["venue_name"] in body["message"]


def test_create_game_same_venue_different_time_ok(client):
    """同场地但时间不重叠 → 允许"""
    host = _signup_user(client, "31000005", "时间管理大师")
    venue = _unique_venue()
    now = datetime.now()
    first = _create_game(client, host["headers"], title="早场", venue_name=venue,
                         start_time=(now + timedelta(hours=1)).isoformat(),
                         end_time=(now + timedelta(hours=2)).isoformat(),
                         signup_deadline=(now + timedelta(minutes=30)).isoformat(),
                         checkin_start_time=(now - timedelta(minutes=5)).isoformat(),
                         checkin_end_time=(now + timedelta(hours=1)).isoformat())
    second = _create_game(client, host["headers"], title="晚场", venue_name=venue,
                          start_time=(now + timedelta(hours=2)).isoformat(),
                          end_time=(now + timedelta(hours=3)).isoformat(),
                          signup_deadline=(now + timedelta(minutes=30)).isoformat(),
                          checkin_start_time=(now + timedelta(minutes=60)).isoformat(),
                          checkin_end_time=(now + timedelta(hours=2)).isoformat())
    assert first["id"] != second["id"]
    assert first["venue_name"] == second["venue_name"]


def test_create_game_different_venue_ok(client):
    """同时段但不同场地、不同发起人 → 允许"""
    host = _signup_user(client, "31000006", "场馆A管理员")
    host2 = _signup_user(client, "31000007", "场馆B管理员")
    first = _create_game(client, host["headers"], title="3号场")
    second = _create_game(client, host2["headers"], title="4号场", venue_name=_unique_venue())
    assert first["venue_name"] != second["venue_name"]


def test_create_game_creator_time_conflict(client):
    """★发起人同一时段已报名别的球局 → 拒绝发起"""
    host = _signup_user(client, "31000008", "发起人A")
    host2 = _signup_user(client, "31000009", "发起人B")

    game = _create_game(client, host["headers"], title="主赛")
    assert client.post(f"/api/v1/game/{game['id']}/signup", headers=host2["headers"], json={"skill_level": 3}).json()["code"] == 0

    now = datetime.now()
    body = _create_game(client, host2["headers"], expect_ok=False, title="冲突发起",
                        start_time=(now + timedelta(hours=2)).isoformat(),
                        end_time=(now + timedelta(hours=4)).isoformat(),
                        signup_deadline=(now + timedelta(minutes=30)).isoformat(),
                        checkin_start_time=(now - timedelta(minutes=5)).isoformat(),
                        checkin_end_time=(now + timedelta(hours=4)).isoformat())
    assert body["code"] == 40900
    assert "时间冲突" in body["message"]


# ======================================================================
# ② 球局列表
# ======================================================================
def test_list_games_sport_type_filter(client):
    """★sport_type：不传返回全部球类，传值按球类过滤"""
    host = _signup_user(client, "31000010", "球类筛选发起人")
    now = datetime.now()
    _create_game(client, host["headers"], title="筛选测试-篮球", venue_name="筛选-场地1", sport_type=1)
    _create_game(client, host["headers"], title="筛选测试-足球", venue_name="筛选-场地2", sport_type=2,
                 start_time=(now + timedelta(hours=5)).isoformat(),
                 end_time=(now + timedelta(hours=7)).isoformat(),
                 checkin_start_time=(now + timedelta(hours=4)).isoformat(),
                 checkin_end_time=(now + timedelta(hours=6)).isoformat())
    _create_game(client, host["headers"], title="筛选测试-羽毛球", venue_name="筛选-场地3", sport_type=3,
                 start_time=(now + timedelta(hours=9)).isoformat(),
                 end_time=(now + timedelta(hours=11)).isoformat(),
                 checkin_start_time=(now + timedelta(hours=8)).isoformat(),
                 checkin_end_time=(now + timedelta(hours=10)).isoformat())

    # 不传 sport_type → 返回全部球类（至少包含本用例 3 场）
    body = client.get("/api/v1/game", params={"venue_name": "筛选-场地"}).json()
    assert body["code"] == 0
    assert body["data"]["total"] == 3
    assert {item["sport_type"] for item in body["data"]["list"]} == {1, 2, 3}

    # 传 sport_type=2 → 只返回足球
    body = client.get("/api/v1/game", params={"sport_type": 2, "venue_name": "筛选-场地"}).json()
    assert body["data"]["total"] == 1
    assert body["data"]["list"][0]["title"] == "筛选测试-足球"
    assert body["data"]["list"][0]["sport_type"] == 2

    # 传 sport_type=1 → 只返回篮球
    body = client.get("/api/v1/game", params={"sport_type": 1, "venue_name": "筛选-场地"}).json()
    assert body["data"]["total"] == 1
    assert body["data"]["list"][0]["sport_type"] == 1

    # 非法的球类值 → 参数错误
    assert client.get("/api/v1/game", params={"sport_type": 9}).status_code == 422


def test_list_games_match_score_is_static(client):
    """★match_score 当前返回静态固定占位值"""
    host = _signup_user(client, "31000011", "匹配分发起人")
    game = _create_game(client, host["headers"], title="匹配分测试", venue_name="匹配分场地")

    listed = client.get("/api/v1/game", params={"keyword": "匹配分测试"}).json()["data"]["list"][0]
    assert listed["match_score"] == MATCH_SCORE_PLACEHOLDER == 80.0

    # 详情同样返回该占位值；且不同球局之间保持一致（固定值）
    host2 = _signup_user(client, "31000012", "匹配分发起人2")
    game2 = _create_game(client, host2["headers"], title="匹配分测试2", venue_name="匹配分场地2")
    listed2 = client.get("/api/v1/game", params={"keyword": "匹配分测试2"}).json()["data"]["list"][0]
    assert listed2["match_score"] == listed["match_score"]

    detail = client.get(f"/api/v1/game/{game['id']}").json()["data"]
    assert detail["match_score"] == MATCH_SCORE_PLACEHOLDER
    assert game["match_score"] == game2["match_score"] == 80.0


def test_list_games_filters_and_pagination(client):
    """列表：校区/关键词/场地模糊 + 分页 + 只看未满 + 我的报名状态"""
    host = _signup_user(client, "31000013", "列表发起人")
    now = datetime.now()
    _create_game(client, host["headers"], title="分页测试-篮球A", venue_name="分页-场地A")
    _create_game(client, host["headers"], title="分页测试-足球B", venue_name="分页-场地B", sport_type=2,
                 start_time=(now + timedelta(hours=5)).isoformat(),
                 end_time=(now + timedelta(hours=7)).isoformat(),
                 checkin_start_time=(now + timedelta(hours=4)).isoformat(),
                 checkin_end_time=(now + timedelta(hours=6)).isoformat())
    _create_game(client, host["headers"], title="分页测试-羽毛球C", venue_name="分页-场地C", sport_type=3,
                 campus="新校区",
                 start_time=(now + timedelta(hours=9)).isoformat(),
                 end_time=(now + timedelta(hours=11)).isoformat(),
                 checkin_start_time=(now + timedelta(hours=8)).isoformat(),
                 checkin_end_time=(now + timedelta(hours=10)).isoformat())

    # 按校区筛选
    body = client.get("/api/v1/game", params={"campus": "新校区"}).json()
    assert body["data"]["total"] == 1
    assert body["data"]["list"][0]["campus"] == "新校区"

    # 关键词
    body = client.get("/api/v1/game", params={"keyword": "羽毛球C"}).json()
    assert body["data"]["total"] == 1

    # 场地模糊匹配
    body = client.get("/api/v1/game", params={"venue_name": "分页-场地"}).json()
    assert body["data"]["total"] == 3

    # 分页 + 默认按开球时间升序
    body = client.get("/api/v1/game", params={"keyword": "分页测试", "page": 1, "page_size": 2}).json()
    assert body["data"]["total"] == 3
    assert len(body["data"]["list"]) == 2
    assert body["data"]["pages"] == 2
    assert body["data"]["list"][0]["start_time"] <= body["data"]["list"][1]["start_time"]

    # 降序
    body = client.get(
        "/api/v1/game", params={"keyword": "分页测试", "sort_desc": True, "page_size": 3}
    ).json()
    assert body["data"]["list"][0]["start_time"] >= body["data"]["list"][-1]["start_time"]

    # 只看未满 + 未登录时 my_registration_status 为 null
    player = _signup_user(client, "31000014", "列表玩家")
    body = client.get(
        "/api/v1/game", params={"keyword": "分页测试", "only_available": True}, headers=player["headers"]
    ).json()
    assert body["data"]["total"] == 3
    assert all(item["my_registration_status"] is None for item in body["data"]["list"])

    # 报名后能看到自己的报名状态
    target = body["data"]["list"][0]
    client.post(f"/api/v1/game/{target['id']}/signup", headers=player["headers"], json={"skill_level": 3})
    body = client.get("/api/v1/game", params={"keyword": target["title"]}, headers=player["headers"]).json()
    assert body["data"]["list"][0]["my_registration_status"] == RegistrationStatus.SIGNED


def test_list_games_only_available_excludes_full(client):
    """只看未满：已满球局被排除"""
    host = _signup_user(client, "31000015", "满员列表发起人")
    player = _signup_user(client, "31000016", "满员列表玩家")
    game = _create_game(client, host["headers"], title="未满过滤测试", max_players=2)
    client.post(f"/api/v1/game/{game['id']}/signup", headers=player["headers"], json={"skill_level": 3})  # 2/2 已满

    body = client.get("/api/v1/game", params={"keyword": "未满过滤测试", "only_available": True}).json()
    assert body["data"]["total"] == 0

    body = client.get("/api/v1/game", params={"keyword": "未满过滤测试"}).json()
    assert body["data"]["total"] == 1
    assert body["data"]["list"][0]["is_full"] is True


def test_list_games_invalid_page_size(client):
    """超过最大每页条数 → 参数错误"""
    resp = client.get("/api/v1/game", params={"page_size": 999})
    assert resp.status_code == 422
    assert resp.json()["code"] == 40000


# ======================================================================
# ③ 球局详情
# ======================================================================
def test_game_detail(client):
    """详情：聚合信息 + 核销统计 + is_creator + 匿名可读"""
    host = _signup_user(client, "31000020", "详情发起人")
    player = _signup_user(client, "31000021", "详情玩家")
    game = _create_game(client, host["headers"], title="详情场", venue_name="详情场地")
    client.post(f"/api/v1/game/{game['id']}/signup", headers=player["headers"], json={"skill_level": 3})

    body = client.get(f"/api/v1/game/{game['id']}", headers=host["headers"]).json()
    assert body["code"] == 0
    data = body["data"]
    assert data["current_players"] == 2
    assert data["slots_left"] == 1
    assert data["is_creator"] is True
    assert data["not_checked_count"] == 2      # 两人都还没核销
    assert data["checked_count"] == 0
    assert data["my_registration_status"] == RegistrationStatus.SIGNED
    assert data["match_score"] == MATCH_SCORE_PLACEHOLDER

    # 匿名访问详情也能看到（可选登录）
    anon = client.get(f"/api/v1/game/{game['id']}").json()
    assert anon["code"] == 0
    assert anon["data"]["is_creator"] is False
    assert anon["data"]["my_registration_status"] is None

    # 不存在的球局
    assert client.get("/api/v1/game/999999").json()["code"] == 40400


# ======================================================================
# ④ 报名加入球局
# ======================================================================
def test_signup_success_and_duplicate(client):
    host = _signup_user(client, "31000030", "报名发起人")
    player = _signup_user(client, "31000031", "报名玩家")
    game = _create_game(client, host["headers"], title="报名场", venue_name="报名场地")

    body = client.post(f"/api/v1/game/{game['id']}/signup", headers=player["headers"], json={"skill_level": 3}).json()
    assert body["code"] == 0
    assert body["data"]["is_waitlist"] is False
    assert body["data"]["current_players"] == 2
    assert "报名成功" in body["message"]
    assert _get_checkin(game["id"], player["user_id"])["settled"] == 0

    # 重复报名
    body = client.post(f"/api/v1/game/{game['id']}/signup", headers=player["headers"], json={"skill_level": 3}).json()
    assert body["code"] == 40900
    assert "已报名" in body["message"]


def test_signup_time_conflict(client):
    """★用户时间冲突：同时段已报名其它球局 → 拒绝（提示带上冲突球局）"""
    host = _signup_user(client, "31000040", "冲突发起人")
    host2 = _signup_user(client, "31000041", "冲突发起人2")
    player = _signup_user(client, "31000042", "冲突玩家")
    now = datetime.now()

    game_a = _create_game(client, host["headers"], title="场次甲", venue_name="冲突场地甲")
    game_b = _create_game(client, host2["headers"], title="场次乙", venue_name="冲突场地乙",
                          start_time=(now + timedelta(hours=2)).isoformat(),
                          end_time=(now + timedelta(hours=4)).isoformat(),
                          signup_deadline=(now + timedelta(minutes=30)).isoformat(),
                          checkin_start_time=(now - timedelta(minutes=5)).isoformat(),
                          checkin_end_time=(now + timedelta(hours=3)).isoformat())

    assert client.post(f"/api/v1/game/{game_a['id']}/signup", headers=player["headers"], json={"skill_level": 3}).json()["code"] == 0
    body = client.post(f"/api/v1/game/{game_b['id']}/signup", headers=player["headers"], json={"skill_level": 3}).json()
    assert body["code"] == 40900
    assert "时间冲突" in body["message"]
    assert "场次甲" in body["message"]


def test_signup_full_goes_waitlist(client):
    """★球局已满：默认进入候补队列（位置从 1 开始）"""
    host = _signup_user(client, "31000050", "满员发起人")
    p1 = _signup_user(client, "31000051", "玩家1")
    p2 = _signup_user(client, "31000052", "玩家2")
    p3 = _signup_user(client, "31000053", "玩家3")
    game = _create_game(client, host["headers"], title="满员场", max_players=3)  # 发起人占1

    r1 = client.post(f"/api/v1/game/{game['id']}/signup", headers=p1["headers"], json={"skill_level": 3}).json()
    r2 = client.post(f"/api/v1/game/{game['id']}/signup", headers=p2["headers"], json={"skill_level": 3}).json()
    assert r1["data"]["current_players"] == 2
    assert r2["data"]["current_players"] == 3

    body = client.post(f"/api/v1/game/{game['id']}/signup", headers=p3["headers"], json={"skill_level": 3}).json()
    assert body["code"] == 0
    assert body["data"]["is_waitlist"] is True
    assert body["data"]["registration"]["waitlist_order"] == 1
    assert "候补" in body["message"]

    # 候补者重复报名提示候补位次
    again = client.post(f"/api/v1/game/{game['id']}/signup", headers=p3["headers"], json={"skill_level": 3}).json()
    assert again["code"] == 40900
    assert "候补" in again["message"]


def test_signup_full_rejected_when_waitlist_disabled(client, monkeypatch):
    """关闭候补后，满员直接拒绝"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "GAME_SIGNUP_ALLOW_WAITLIST", False)

    host = _signup_user(client, "31000060", "满员发起人2")
    p1 = _signup_user(client, "31000061", "玩家4")
    p2 = _signup_user(client, "31000062", "玩家5")
    game = _create_game(client, host["headers"], title="满员拒绝场", max_players=2)

    assert client.post(f"/api/v1/game/{game['id']}/signup", headers=p1["headers"], json={"skill_level": 3}).json()["code"] == 0
    body = client.post(f"/api/v1/game/{game['id']}/signup", headers=p2["headers"], json={"skill_level": 3}).json()
    assert body["code"] == 40900
    assert "已满" in body["message"]


def test_signup_min_credit_limit(client):
    """信誉分门槛：不足则拒绝，提示带上当前分数"""
    host = _signup_user(client, "31000070", "门槛发起人")
    poor = _signup_user(client, "31000071", "低信誉玩家", credit=50)
    game = _create_game(client, host["headers"], title="门槛场", min_credit_score=80)

    body = client.post(f"/api/v1/game/{game['id']}/signup", headers=poor["headers"], json={"skill_level": 3}).json()
    assert body["code"] == 40900
    assert "信誉分" in body["message"] and "50" in body["message"]


def test_signup_after_deadline(client):
    """报名已截止"""
    host = _signup_user(client, "31000080", "截止发起人")
    player = _signup_user(client, "31000081", "迟到玩家")
    game = _create_game(client, host["headers"], title="截止场")
    _update_game(game["id"], signup_deadline=datetime.now() - timedelta(minutes=1))

    body = client.post(f"/api/v1/game/{game['id']}/signup", headers=player["headers"], json={"skill_level": 3}).json()
    assert body["code"] == 40900
    assert "截止" in body["message"]


# ======================================================================
# ⑤ 退出球局
# ======================================================================
def test_exit_game_promotes_waitlist(client):
    """★退出后自动从候补补位"""
    host = _signup_user(client, "31000090", "退出发起人")
    p1 = _signup_user(client, "31000091", "正式玩家")
    p2 = _signup_user(client, "31000092", "候补玩家")
    game = _create_game(client, host["headers"], title="退出场", max_players=2)  # 发起人 + 1

    assert client.post(f"/api/v1/game/{game['id']}/signup", headers=p1["headers"], json={"skill_level": 3}).json()["code"] == 0
    assert client.post(f"/api/v1/game/{game['id']}/signup", headers=p2["headers"], json={"skill_level": 3}).json()["data"]["is_waitlist"] is True

    body = client.post(f"/api/v1/game/{game['id']}/exit?reason=临时有事", headers=p1["headers"]).json()
    assert body["code"] == 0
    assert body["data"]["promoted_user_id"] == p2["user_id"]
    assert body["data"]["current_players"] == 2
    assert "补位" in body["message"]

    assert _get_registration(game["id"], p1["user_id"])["status"] == RegistrationStatus.CANCELED
    assert _get_registration(game["id"], p2["user_id"])["status"] == RegistrationStatus.SIGNED
    # 补位者获得待结算签到记录
    assert _get_checkin(game["id"], p2["user_id"])["settled"] == 0
    # 退出者本人待结算记录被作废，不会被判缺席
    assert _get_checkin(game["id"], p1["user_id"]) is None


def test_exit_game_not_registered(client):
    host = _signup_user(client, "31000093", "发起人X")
    other = _signup_user(client, "31000094", "路人Y")
    game = _create_game(client, host["headers"], title="退出校验场")

    body = client.post(f"/api/v1/game/{game['id']}/exit", headers=other["headers"]).json()
    assert body["code"] == 40900
    assert "尚未报名" in body["message"]


def test_exit_game_after_start_rejected(client):
    host = _signup_user(client, "31000095", "发起人Z")
    game = _create_game(client, host["headers"], title="已开球场")
    _update_game(game["id"], start_time=datetime.now() - timedelta(minutes=10))

    body = client.post(f"/api/v1/game/{game['id']}/exit", headers=host["headers"]).json()
    assert body["code"] == 40900
    assert "已开始" in body["message"]


def test_exit_game_deadline_rejected(client, monkeypatch):
    """开球前 N 分钟内禁止退出（GAME_CANCEL_DEADLINE_MINUTES）"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "GAME_CANCEL_DEADLINE_MINUTES", 120)

    host = _signup_user(client, "31000096", "发起人W")
    game = _create_game(client, host["headers"], title="临期退出场")  # 1 小时后开球 < 120 分钟
    body = client.post(f"/api/v1/game/{game['id']}/exit", headers=host["headers"]).json()
    assert body["code"] == 40900
    assert "距开球不足" in body["message"]


# ======================================================================
# ⑥ 签到核销（发起人核销 + 惰性结算）
# ======================================================================
def test_verify_requires_creator(client):
    """非发起人不能核销"""
    host = _signup_user(client, "31100001", "核销发起人")
    player = _signup_user(client, "31100002", "普通玩家")
    game = _create_game(client, host["headers"], title="权限校验场")
    client.post(f"/api/v1/game/{game['id']}/signup", headers=player["headers"], json={"skill_level": 3})

    body = client.post(
        "/api/v1/checkin/verify",
        json={"game_id": game["id"], "user_ids": [player["user_id"]]},
        headers=player["headers"],
    ).json()
    assert body["code"] == 40300
    assert "发起人" in body["message"]


def test_verify_success_triggers_lazy_settlement(client):
    """★核销成功 → 标记到场 + 立即惰性结算（正常签到 +2），并记录核销人"""
    host = _signup_user(client, "31100010", "核销发起人2")
    p1 = _signup_user(client, "31100011", "到场玩家1")
    p2 = _signup_user(client, "31100012", "到场玩家2")
    game = _create_game(client, host["headers"], title="核销成功场", max_players=5)
    for p in (p1, p2):
        client.post(f"/api/v1/game/{game['id']}/signup", headers=p["headers"], json={"skill_level": 3})

    before = _get_user(p1["user_id"])["credit_score"]

    body = client.post(
        "/api/v1/checkin/verify",
        json={"game_id": game["id"], "user_ids": [p1["user_id"], p2["user_id"]], "remark": "现场核销"},
        headers=host["headers"],
    ).json()
    assert body["code"] == 0
    assert "成功 2 人" in body["message"]
    data = body["data"]
    assert data["verified_count"] == 2 and data["skipped_count"] == 0 and data["failed_count"] == 0

    item = data["items"][0]
    assert item["ok"] is True
    assert item["checkin_status"] == CheckinStatus.CHECKED
    assert item["checkin_status_text"] == "已签到"
    assert item["credit_delta"] == 2                      # 正常签到 +2
    assert item["credit_before"] == before
    assert item["credit_after"] == before + 2

    # 数据库侧：签到记录已结算 + 记录了核销人
    record = _get_checkin(game["id"], p1["user_id"])
    assert record["checkin_status"] == CheckinStatus.CHECKED
    assert record["settled"] == 1
    assert record["credit_delta"] == 2
    assert record["checkin_operator_id"] == host["user_id"]   # 谁核销的
    assert record["remark"] == "现场核销"

    # 用户信誉分真的变了
    assert _get_user(p1["user_id"])["credit_score"] == before + 2


def test_verify_is_idempotent_and_reports_reasons(client):
    """幂等：重复核销被跳过并给出原因；未报名用户核销失败但不影响他人"""
    host = _signup_user(client, "31100020", "核销发起人3")
    player = _signup_user(client, "31100021", "玩家A")
    outsider = _signup_user(client, "31100022", "路人B")
    game = _create_game(client, host["headers"], title="幂等核销场", max_players=4)
    client.post(f"/api/v1/game/{game['id']}/signup", headers=player["headers"], json={"skill_level": 3})

    # 第一次核销：1 成功 + 1 失败（未报名）
    body = client.post("/api/v1/checkin/verify",
                       json={"game_id": game["id"], "user_ids": [player["user_id"], outsider["user_id"]]},
                       headers=host["headers"]).json()
    assert body["data"]["verified_count"] == 1
    assert body["data"]["failed_count"] == 1
    failed = [i for i in body["data"]["items"] if not i["ok"]][0]
    assert failed["user_id"] == outsider["user_id"]
    assert "未报名" in failed["reason"]

    # 再次核销同一人 → 跳过，且信誉分不再变化
    credit_after_first = _get_user(player["user_id"])["credit_score"]
    body = client.post("/api/v1/checkin/verify",
                       json={"game_id": game["id"], "user_ids": [player["user_id"]]},
                       headers=host["headers"]).json()
    assert body["data"]["skipped_count"] == 1
    assert body["data"]["verified_count"] == 0
    assert "已核销" in body["data"]["items"][0]["reason"]
    assert _get_user(player["user_id"])["credit_score"] == credit_after_first


def test_verify_late_status(client):
    """超过核销截止时间核销 → 记为迟到（-3 分）"""
    host = _signup_user(client, "31100030", "核销发起人4")
    latecomer = _signup_user(client, "31100031", "迟到玩家")
    game = _create_game(client, host["headers"], title="迟到核销场", max_players=4)
    client.post(f"/api/v1/game/{game['id']}/signup", headers=latecomer["headers"], json={"skill_level": 3})

    # 把核销截止时间拨到过去 → 现在核销即为迟到
    _update_game(game["id"], checkin_end_time=datetime.now() - timedelta(minutes=10))
    before = _get_user(latecomer["user_id"])["credit_score"]

    body = client.post("/api/v1/checkin/verify",
                       json={"game_id": game["id"], "user_ids": [latecomer["user_id"]]},
                       headers=host["headers"]).json()
    item = body["data"]["items"][0]
    assert item["checkin_status"] == CheckinStatus.LATE
    assert item["checkin_status_text"] == "迟到"
    assert item["credit_delta"] == -3
    assert item["credit_after"] == before - 3


def test_verify_as_late_override(client):
    """发起人可显式指定记为迟到（人工补签场景）"""
    host = _signup_user(client, "31100032", "核销发起人4b")
    player = _signup_user(client, "31100033", "补签玩家")
    game = _create_game(client, host["headers"], title="指定迟到场", max_players=4)
    client.post(f"/api/v1/game/{game['id']}/signup", headers=player["headers"], json={"skill_level": 3})

    body = client.post("/api/v1/checkin/verify",
                       json={"game_id": game["id"], "user_ids": [player["user_id"]], "as_late": True},
                       headers=host["headers"]).json()
    item = body["data"]["items"][0]
    assert item["checkin_status"] == CheckinStatus.LATE
    assert item["credit_delta"] == -3


def test_verify_before_window_rejected(client):
    """核销窗口未开放 → 明确提示开放时间"""
    host = _signup_user(client, "31100040", "核销发起人5")
    game = _create_game(client, host["headers"], title="未开放场")
    _update_game(
        game["id"],
        start_time=datetime.now() + timedelta(hours=5),
        checkin_start_time=datetime.now() + timedelta(hours=4),
        checkin_end_time=datetime.now() + timedelta(hours=6),
    )

    body = client.post("/api/v1/checkin/verify",
                       json={"game_id": game["id"], "user_ids": [host["user_id"]]},
                       headers=host["headers"]).json()
    assert body["code"] == 40900
    assert "核销尚未开放" in body["message"]


def test_verify_after_settle_rejected(client):
    """球局已结算 → 不能核销"""
    host = _signup_user(client, "31100050", "核销发起人6")
    game = _create_game(client, host["headers"], title="已结算场")
    _update_game(game["id"], settle_status=SettleStatus.SETTLED)

    body = client.post("/api/v1/checkin/verify",
                       json={"game_id": game["id"], "user_ids": [host["user_id"]]},
                       headers=host["headers"]).json()
    assert body["code"] == 40900
    assert "已完成结算" in body["message"]


def test_verify_all_and_roster(client):
    """一键核销 + 核销名单统计（仅发起人可见）"""
    host = _signup_user(client, "31100060", "核销发起人7")
    p1 = _signup_user(client, "31100061", "玩家C")
    p2 = _signup_user(client, "31100062", "玩家D")
    game = _create_game(client, host["headers"], title="一键核销场", max_players=5)
    for p in (p1, p2):
        client.post(f"/api/v1/game/{game['id']}/signup", headers=p["headers"], json={"skill_level": 3})

    # 核销前名单
    roster = client.get(f"/api/v1/checkin/game/{game['id']}", headers=host["headers"]).json()
    assert roster["code"] == 0
    assert roster["data"]["signed_count"] == 3
    assert roster["data"]["not_checked_count"] == 3
    assert roster["data"]["checkin_open"] is True
    assert all(m["checkin_status_text"] == "未签到" for m in roster["data"]["members"])

    # 一键核销全部未核销者
    body = client.post("/api/v1/checkin/verify",
                       json={"game_id": game["id"], "verify_all": True},
                       headers=host["headers"]).json()
    assert body["data"]["verified_count"] == 3

    roster = client.get(f"/api/v1/checkin/game/{game['id']}", headers=host["headers"]).json()
    assert roster["data"]["checked_count"] == 3
    assert roster["data"]["not_checked_count"] == 0

    # 非发起人看不到核销名单
    denied = client.get(f"/api/v1/checkin/game/{game['id']}", headers=p1["headers"]).json()
    assert denied["code"] == 40300


def test_verify_request_validation(client):
    """user_ids 与 verify_all 二选一；user_ids 不允许重复"""
    host = _signup_user(client, "31100070", "核销发起人8")
    game = _create_game(client, host["headers"], title="参数校验场")

    resp = client.post("/api/v1/checkin/verify", json={"game_id": game["id"]}, headers=host["headers"])
    assert resp.status_code == 422
    assert resp.json()["code"] == 40000
    assert "user_ids" in resp.json()["message"]

    resp = client.post("/api/v1/checkin/verify",
                       json={"game_id": game["id"], "user_ids": [1, 1]}, headers=host["headers"])
    assert resp.status_code == 422
    assert "重复" in resp.json()["message"]


def test_verified_user_not_marked_absent(client):
    """★核销与缺席判定联动：已核销者不被判缺席，未核销者才扣分"""
    host = _signup_user(client, "31100080", "联动发起人")
    arrived = _signup_user(client, "31100081", "到场者")
    missing = _signup_user(client, "31100082", "放鸽子")
    game = _create_game(client, host["headers"], title="联动场", max_players=5)
    for p in (arrived, missing):
        client.post(f"/api/v1/game/{game['id']}/signup", headers=p["headers"], json={"skill_level": 3})

    # 只核销 arrived
    client.post("/api/v1/checkin/verify",
                json={"game_id": game["id"], "user_ids": [arrived["user_id"]]},
                headers=host["headers"])
    arrived_credit = _get_user(arrived["user_id"])["credit_score"]   # 已 +2

    # 球局结束并判定缺席（发起人本人也未核销，所以缺席 2 人）
    _update_game(game["id"], status=GameStatus.PLAYING, end_time=datetime.now() - timedelta(minutes=5))
    body = client.post("/api/v1/checkin/absent-judgement",
                       json={"game_id": game["id"], "auto_prune": True},
                       headers=host["headers"]).json()
    assert body["code"] == 0
    assert body["data"]["absent_count"] == 2       # 未核销的：发起人 + 放鸽子

    # 到场者分数不变；放鸽子者 -10 且计入失信次数
    assert _get_user(arrived["user_id"])["credit_score"] == arrived_credit
    assert _get_user(missing["user_id"])["absent_count"] == 1
    assert _get_user(missing["user_id"])["credit_score"] == 90

    # 球局已结算 → 再核销被拒
    re_verify = client.post("/api/v1/checkin/verify",
                            json={"game_id": game["id"], "user_ids": [missing["user_id"]]},
                            headers=host["headers"]).json()
    assert re_verify["code"] == 40900
    assert "已完成结算" in re_verify["message"]


def test_verify_triggers_ban_when_credit_too_low(client):
    """核销结算后信誉分低于阈值 → 自动进小黑屋（结果里 banned=true）"""
    from app.core.config import settings

    host = _signup_user(client, "31100090", "低分发起人")
    low = _signup_user(client, "31100091", "临界玩家", credit=settings.CREDIT_BAN_THRESHOLD - 1)
    game = _create_game(client, host["headers"], title="触发封禁场", max_players=4)
    client.post(f"/api/v1/game/{game['id']}/signup", headers=low["headers"], json={"skill_level": 3})

    # 让核销记为迟到（-3）→ 分数跌破阈值
    body = client.post("/api/v1/checkin/verify",
                       json={"game_id": game["id"], "user_ids": [low["user_id"]], "as_late": True},
                       headers=host["headers"]).json()
    item = body["data"]["items"][0]
    assert item["banned"] is True
    assert item["ban_end_time"] is not None
    assert item["credit_after"] == settings.CREDIT_BAN_THRESHOLD - 1 - 3


def test_game_members_list(client):
    """报名名单：正式 + 候补"""
    host = _signup_user(client, "31100100", "名单发起人")
    p1 = _signup_user(client, "31100101", "名单玩家1")
    p2 = _signup_user(client, "31100102", "名单玩家2")
    game = _create_game(client, host["headers"], title="名单场", max_players=2)
    client.post(f"/api/v1/game/{game['id']}/signup", headers=p1["headers"], json={"skill_level": 3})
    client.post(f"/api/v1/game/{game['id']}/signup", headers=p2["headers"], json={"skill_level": 3})  # 候补

    body = client.get(f"/api/v1/game/{game['id']}/members").json()
    assert body["code"] == 0
    assert len(body["data"]) == 3                       # 发起人 + 正式 + 候补
    assert body["data"][-1]["is_waitlist"] == 1
    assert body["data"][-1]["nickname"] == "名单玩家2"

    body = client.get(f"/api/v1/game/{game['id']}/members", params={"only_formal": True}).json()
    assert len(body["data"]) == 2
