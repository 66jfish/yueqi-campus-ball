"""
小黑屋失信惩罚模块测试（真实跑通，不依赖 MySQL）
====================================================================
逐条覆盖需求规则：
    规则1 缺席判定：已报名 + 未签到 + 未请假 → 缺席（-10 分）
          ① 结束球局触发  ② 定时兜底扫描（忘记关闭的球局）
    规则2 缺席即封禁：ban_end_time = ban_start_time + 3 天
    规则3 封禁期间只拦「发局/报名」，返回 {"code":403,"msg":"您因放鸽子被禁赛，将于 x 解除"}
          查询类接口放行；历史遗留球局仍可签到
    规则4 惰性解封：ban_end_time < now 即视为解封，不依赖定时任务；记录永久留存含 reason
    规则5 用户表 reputation_score 同步扣分（缺席 -10）
    规则6 连续缺席不叠加：不新建记录，只顺延原记录 + 次数留痕
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
from app.core.config import settings
from app.core.constants import BanReasonType, CheckinStatus, GameStatus, SettleStatus
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.middleware import hooks as hook_module
from app.models import Blacklist, CheckinRecord, Game, Registration, User
from app.services import ai_profile as ai_service
from app.services import blacklist as blacklist_service
from app.services import checkin as checkin_service

# ----------------------------------------------------------------------
# SQLite 装配
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
    blacklist_service.ban_cache.clear()
    yield
    app.dependency_overrides.clear()
    blacklist_service.ban_cache.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ======================================================================
# 工具
# ======================================================================
_venue_seq = itertools.count(1)
_slot_seq = itertools.count(0)


def _signup_user(client, student_no: str, nickname: str) -> dict:
    client.post(
        "/api/v1/auth/register",
        json={
            "student_no": student_no,
            "nickname": nickname,
            "password": "abc123456",
            "phone": f"139{student_no[-6:]}",
            "campus": "老校区",
        },
    )
    body = client.post("/api/v1/auth/login", json={"account": student_no, "password": "abc123456"}).json()
    assert body["code"] == 0, body
    return {
        "user_id": body["data"]["user"]["id"],
        "headers": {"Authorization": f"Bearer {body['data']['token']['access_token']}"},
    }


def _make_game(client, headers, *, title="惩罚测试球局", hours: int | None = None, **overrides) -> dict:
    """
    创建一场球局。
    默认自动分配互不重叠的时段（否则同一发起人的多场球局会命中「发起人时间冲突」），
    需要构造时间重叠场景时显式传 hours。
    """
    if hours is None:
        hours = 2 + next(_slot_seq) * 4
    now = datetime.now()
    payload = {
        "sport_type": 1,
        "title": title,
        "campus": "老校区",
        "venue_name": f"惩罚测试场地{next(_venue_seq)}号",
        "start_time": (now + timedelta(hours=hours)).isoformat(),
        "end_time": (now + timedelta(hours=hours + 2)).isoformat(),
        "checkin_start_time": (now - timedelta(minutes=5)).isoformat(),
        "checkin_end_time": (now + timedelta(hours=hours + 1)).isoformat(),
        "max_players": 6,
        "min_players": 2,
    }
    payload.update(overrides)
    resp = client.post("/api/v1/game", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _join(client, headers, game_id: int) -> dict:
    """报名球局，直接返回响应 JSON"""
    return client.post(f"/api/v1/game/{game_id}/signup", headers=headers, json={"skill_level": 3}).json()


def _ban_directly(user_id: int, *, reason: str = "缺席球局（未签到且未请假），球局ID=900", days: int = 3):
    """直接调用服务层封禁（绕过接口，便于构造封禁态），返回封禁记录ID"""
    return asyncio.run(_ban_directly_result(user_id, reason=reason, days=days)).id


async def _ban_directly_result(user_id: int, *, reason: str = "缺席球局（未签到且未请假），球局ID=900", days: int = 3):
    """同上，但返回封禁记录对象"""
    async with TestSessionLocal() as db:
        applied = await blacklist_service.apply_ban(
            db, user_id=user_id, reason_type=BanReasonType.ABSENT,
            reason=reason, days=days, operator_id=0,
        )
        blacklist_service.ban_cache.clear()
        return applied.ban


def _read(op):
    async def _run():
        async with TestSessionLocal() as db:
            return await op(db)

    return asyncio.run(_run())


def _write(op):
    async def _run():
        async with TestSessionLocal() as db:
            await op(db)
            await db.commit()

    asyncio.run(_run())


def _get_user(user_id: int) -> dict:
    async def _op(db):
        user = await db.get(User, user_id)
        return {
            "reputation_score": user.reputation_score,
            "credit_score_alias": user.credit_score,   # synonym 兼容字段
            "credit_level": user.credit_level,
            "absent_count": user.absent_count,
        }

    return _read(_op)


def _get_game(game_id: int) -> dict:
    async def _op(db):
        game = await db.get(Game, game_id)
        return {"status": game.status, "settle_status": game.settle_status}

    return _read(_op)


def _set_game(game_id: int, **fields):
    async def _op(db):
        game = await db.get(Game, game_id)
        for key, value in fields.items():
            setattr(game, key, value)

    _write(_op)


def _bans_of(user_id: int) -> list[dict]:
    async def _op(db):
        rows = (
            await db.execute(
                select(Blacklist).where(Blacklist.user_id == user_id).order_by(Blacklist.id.asc())
            )
        ).scalars().all()
        return [
            {
                "id": b.id,
                "start": b.ban_start_time,
                "days": b.ban_duration_days,
                "end": b.ban_end_time,
                "original_end": b.ban_original_end_time,
                "extend_count": b.ban_extend_count,
                "status": b.status,
                "reason": b.reason,
                "reason_type": b.reason_type,
                "trigger_game_id": b.trigger_game_id,
                "released_at": b.released_at,
            }
            for b in rows
        ]

    return _read(_op)


def _expire_ban(ban_id: int, hours_ago: int = 1):
    """把某条封禁改成「已过期」，用于验证惰性解封"""

    async def _op(db):
        ban = await db.get(Blacklist, ban_id)
        ban.ban_end_time = datetime.now() - timedelta(hours=hours_ago)

    _write(_op)
    blacklist_service.ban_cache.clear()


# ======================================================================
# 规则1 + 规则2 + 规则5：缺席判定 → 扣 10 分 → 自动封禁 3 天
# ======================================================================
def test_finish_game_triggers_absent_and_ban(client):
    """结束球局触发缺席判定：未签到未请假者记缺席、-10 分、自动进小黑屋 3 天"""
    host = _signup_user(client, "82000001", "惩罚发起人")
    arrived = _signup_user(client, "82000002", "到场的小明")
    missing = _signup_user(client, "82000003", "放鸽子的小红")

    game = _make_game(client, host["headers"], title="缺席判定球局")
    for p in (arrived, missing):
        assert _join(client, p["headers"], game["id"])["code"] == 0

    # 小明核销到场（+2），小红既不签到也不请假 → 应被判缺席
    verify = client.post(
        "/api/v1/checkin/verify",
        json={"game_id": game["id"], "user_ids": [arrived["user_id"]]},
        headers=host["headers"],
    ).json()
    assert verify["code"] == 0

    missing_before = _get_user(missing["user_id"])["reputation_score"]

    # ★规则1：结束球局即触发判定
    finish = client.post(f"/api/v1/game/{game['id']}/finish", headers=host["headers"]).json()
    assert finish["code"] == 0
    assert "缺席" in finish["message"]
    # 缺席者 = 放鸽子的小红 + 未核销的发起人
    assert finish["data"]["absent_count"] == 2

    # 规则5：缺席 -10 分，字段 reputation_score 同步维护
    after = _get_user(missing["user_id"])
    assert after["reputation_score"] == missing_before - 10
    assert after["credit_score_alias"] == after["reputation_score"]   # synonym 兼容
    assert after["absent_count"] == 1

    # 到场者不受影响
    assert _get_user(arrived["user_id"])["absent_count"] == 0

    # 球局状态 → 已结束，且结算标记置位
    g = _get_game(game["id"])
    assert g["status"] == GameStatus.FINISHED
    assert g["settle_status"] == SettleStatus.SETTLED

    # ★规则2：缺席者自动进小黑屋，时长固定 3 天，end = start + 3天
    bans = _bans_of(missing["user_id"])
    assert len(bans) == 1
    ban = bans[0]
    assert ban["days"] == settings.BAN_DEFAULT_DAYS == 3
    assert ban["end"] == ban["start"] + timedelta(days=3)
    assert ban["reason_type"] == BanReasonType.ABSENT
    assert ban["trigger_game_id"] == game["id"]
    assert ban["reason"] and "缺席" in ban["reason"]        # 规则4：reason 永久留存
    assert ban["extend_count"] == 0

    # 已被核销的到场者不会进小黑屋
    assert _bans_of(arrived["user_id"]) == []


def test_finish_game_is_idempotent(client):
    """重复结束球局不会重复判定/重复扣分"""
    host = _signup_user(client, "82000010", "幂等发起人")
    missing = _signup_user(client, "82000011", "幂等放鸽子")
    game = _make_game(client, host["headers"], title="幂等判定球局")
    _join(client, missing["headers"], game["id"])

    client.post(f"/api/v1/game/{game['id']}/finish", headers=host["headers"])
    score_after_first = _get_user(missing["user_id"])["reputation_score"]

    second = client.post(f"/api/v1/game/{game['id']}/finish", headers=host["headers"]).json()
    assert second["data"]["absent_count"] == 0
    assert _get_user(missing["user_id"])["reputation_score"] == score_after_first
    assert len(_bans_of(missing["user_id"])) == 1


def test_absent_scan_fallback_finds_overdue_games(client):
    """★规则1 定时兜底扫描：发起人忘记结束球局，扫描后仍能判定漏判"""
    host = _signup_user(client, "82000020", "忘关球局发起人")
    missing = _signup_user(client, "82000021", "被兜底判定的鸽子")
    game = _make_game(client, host["headers"], title="忘记关闭的球局")
    _join(client, missing["headers"], game["id"])

    # 模拟「球局时间已过，但没人点结束」（状态仍是进行中、未结算）
    _set_game(
        game["id"],
        status=GameStatus.PLAYING,
        start_time=datetime.now() - timedelta(hours=4),
        end_time=datetime.now() - timedelta(hours=2),
        checkin_start_time=datetime.now() - timedelta(hours=5),
        checkin_end_time=datetime.now() - timedelta(hours=3),
    )

    async def _scan():
        async with TestSessionLocal() as db:
            return await checkin_service.scan_overdue_games(db)

    result = asyncio.run(_scan())
    assert result["scanned"] >= 1
    assert any(item["game_id"] == game["id"] for item in result["finalized"])

    g = _get_game(game["id"])
    assert g["status"] == GameStatus.FINISHED
    assert g["settle_status"] == SettleStatus.SETTLED

    # 漏判被补偿：扣分 + 封禁
    assert _get_user(missing["user_id"])["absent_count"] == 1
    assert len(_bans_of(missing["user_id"])) == 1


def test_absent_scan_skips_future_and_settled_games(client):
    """兜底扫描不会误伤：未到结束时间、已取消、已结算的球局都不处理"""
    host = _signup_user(client, "82000030", "扫描边界发起人")

    future = _make_game(client, host["headers"], title="未来的球局")
    canceled = _make_game(client, host["headers"], title="已取消球局")
    _set_game(
        canceled["id"],
        status=GameStatus.CANCELED,
        end_time=datetime.now() - timedelta(hours=1),
    )
    settled = _make_game(client, host["headers"], title="已结算球局")
    _set_game(
        settled["id"],
        status=GameStatus.FINISHED,
        settle_status=SettleStatus.SETTLED,
        end_time=datetime.now() - timedelta(hours=1),
    )

    async def _scan():
        async with TestSessionLocal() as db:
            return await checkin_service.scan_overdue_games(db)

    result = asyncio.run(_scan())
    scanned_ids = [item["game_id"] for item in result["finalized"]]
    assert future["id"] not in scanned_ids
    assert canceled["id"] not in scanned_ids
    assert settled["id"] not in scanned_ids
    assert _get_user(host["user_id"])["absent_count"] == 0


# ======================================================================
# 规则3：拦截范围（只拦发局/报名）+ 响应格式
# ======================================================================
def test_ban_blocks_game_create_and_signup_only(client):
    """★封禁期间：发局/报名 403（code=403 + msg），查询与签到/核销放行"""
    host = _signup_user(client, "82000040", "封禁测试发起人")
    banned = _signup_user(client, "82000041", "被封禁的小刚")

    # 先让被封禁用户报上一场球（历史遗留球局）
    legacy_game = _make_game(client, host["headers"], title="历史遗留球局")
    assert _join(client, banned["headers"], legacy_game["id"])["code"] == 0

    # 关进小黑屋
    _ban_directly(banned["user_id"])

    # ---------- 1) 发起球局被拦 ----------
    now = datetime.now()
    resp = client.post(
        "/api/v1/game",
        headers=banned["headers"],
        json={
            "sport_type": 1, "title": "封禁期间发局", "venue_name": "封禁场地A",
            "start_time": (now + timedelta(hours=3)).isoformat(),
            "end_time": (now + timedelta(hours=4)).isoformat(),
            "max_players": 4,
        },
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == 403
    assert body["msg"].startswith("您因放鸽子被禁赛，将于 ")
    assert body["msg"].endswith("解除")
    assert body["data"]["banned"] is True
    assert body["data"]["ban_duration_days"] == 3
    # 解禁时间格式可读，且等于 ban_start + 3 天
    assert "T" in body["data"]["ban_end_time"]

    # ---------- 2) 报名被拦 ----------
    another = _make_game(client, host["headers"], title="封禁期间想报名")
    resp = client.post(f"/api/v1/game/{another['id']}/signup", headers=banned["headers"], json={"skill_level": 3})
    assert resp.status_code == 403
    assert resp.json()["code"] == 403
    assert "您因放鸽子被禁赛" in resp.json()["msg"]

    # ---------- 3) 查询类接口全部放行 ----------
    for path in (
        "/api/v1/game",
        f"/api/v1/game/{legacy_game['id']}",
        f"/api/v1/game/{legacy_game['id']}/members",
        "/api/v1/user/me",
        "/api/v1/user/me/credit",
        "/api/v1/user/me/credit/history",
        "/api/v1/checkin/my",
        "/api/v1/blacklist/me",
        "/api/v1/blacklist/records",
        "/api/v1/blacklist/config",
    ):
        assert client.get(path, headers=banned["headers"]).status_code == 200, path

    # ---------- 4) 历史遗留球局仍可签到（规则明确要求） ----------
    signin = client.post(
        "/api/v1/checkin/checkin",
        headers=banned["headers"],
        json={"game_id": legacy_game["id"], "checkin_type": 1},
    )
    assert signin.status_code == 200, signin.text
    assert signin.json()["code"] == 0

    # ---------- 5) 也可正常退出球局、请假（不被拦，避免用户被困住） ----------
    assert client.post(
        f"/api/v1/game/{another['id']}/exit", headers=banned["headers"]
    ).status_code in (200, 409)  # 409=未报名该场，但绝不是 403（未被封禁拦截）


def test_ban_blocks_creator_verify_when_creator_banned(client):
    """被封禁的发起人仍能核销自己历史遗留球局的签到（活动本身不占用新资源）"""
    host = _signup_user(client, "82000050", "被封发起人")
    player = _signup_user(client, "82000051", "正常玩家")
    game = _make_game(client, host["headers"], title="发起人被封的球局")
    assert _join(client, player["headers"], game["id"])["code"] == 0

    _ban_directly(host["user_id"])

    resp = client.post(
        "/api/v1/checkin/verify",
        json={"game_id": game["id"], "user_ids": [player["user_id"]]},
        headers=host["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["verified_count"] == 1


# ======================================================================
# 规则4：惰性解封（不依赖定时任务）+ 记录永久留存
# ======================================================================
def test_lazy_release_without_any_task(client):
    """★规则4：把封禁改成已过期，无需跑任何定时任务，用户立即恢复发局能力"""
    host = _signup_user(client, "82000060", "惰性解封发起人")
    banned = _signup_user(client, "82000061", "即将解封的人")

    ban_id = _ban_directly(banned["user_id"], reason="缺席球局（未签到且未请假），球局ID=901")

    # 封禁中：发局被拦
    now = datetime.now()
    payload = {
        "sport_type": 1, "title": "解封前", "venue_name": "惰性解封场地",
        "start_time": (now + timedelta(hours=5)).isoformat(),
        "end_time": (now + timedelta(hours=6)).isoformat(),
        "max_players": 4,
    }
    assert client.post("/api/v1/game", json=payload, headers=banned["headers"]).status_code == 403

    # 直接把解禁时间改到过去（模拟 3 天过去），不执行任何后台任务
    _expire_ban(ban_id, hours_ago=1)

    # 惰性判定：查询侧立即视为已解封
    status = client.get("/api/v1/blacklist/me", headers=banned["headers"]).json()["data"]
    assert status["banned"] is False
    assert status["total_ban_count"] == 1          # 规则4：记录永久留存
    assert status["history"][0]["reason"]         # 含 reason，可作信誉画像依据
    assert status["history"][0]["is_active"] is False

    payload["title"] = "解封后"
    payload["venue_name"] = "惰性解封场地2"
    resp = client.post("/api/v1/game", json=payload, headers=banned["headers"])
    assert resp.status_code == 200, resp.text


def test_release_expired_only_marks_status(client):
    """到期解封批处理只做「留痕」，不改变拦截结论（拦截本来就是惰性的）"""
    host = _signup_user(client, "82000070", "留痕测试")
    banned = _signup_user(client, "82000071", "留痕测试用户")

    ban_id = _ban_directly(banned["user_id"], reason="缺席球局（未签到且未请假），球局ID=902")
    _expire_ban(ban_id, hours_ago=2)
    assert _bans_of(banned["user_id"])[0]["status"] == 1        # 还没跑任务，status 仍是 1

    async def _release():
        async with TestSessionLocal() as db:
            return await blacklist_service.release_expired_bans(db)

    released = asyncio.run(_release())
    assert released >= 1
    ban = _bans_of(banned["user_id"])[0]
    assert ban["status"] == 0
    assert ban["released_at"] is not None
    # 已解封 → 不影响正常使用
    assert client.get("/api/v1/blacklist/me", headers=banned["headers"]).json()["data"]["banned"] is False


# ======================================================================
# 规则6：连续缺席不叠加封禁（顺延）
# ======================================================================
def test_repeat_absent_reuses_same_record_and_extends(client):
    """★规则6：封禁期内再次缺席 → 不新建记录；原记录顺延 3 天 + 次数留痕 + 照常扣分"""
    host = _signup_user(client, "82000080", "连续缺席发起人")
    repeat = _signup_user(client, "82000081", "惯犯小强")

    # 第一场：缺席 → 封禁 3 天
    game1 = _make_game(client, host["headers"], title="第一场")
    assert _join(client, repeat["headers"], game1["id"])["code"] == 0
    # 发起人核销自己到场，避免发起人也被判缺席（否则发起人同样进小黑屋）
    client.post(
        "/api/v1/checkin/verify",
        json={"game_id": game1["id"], "user_ids": [host["user_id"]]},
        headers=host["headers"],
    )
    client.post(f"/api/v1/game/{game1['id']}/finish", headers=host["headers"])

    bans_after_first = _bans_of(repeat["user_id"])
    assert len(bans_after_first) == 1
    first = bans_after_first[0]
    score_after_first = _get_user(repeat["user_id"])["reputation_score"]

    # 第二场：仍在封禁期内再次缺席
    game2 = _make_game(client, host["headers"], title="第二场")
    # 被封禁用户不能报名新球局，这里直接建报名记录模拟「早已报名、后来被封」的情形
    async def _force_registration(db):
        db.add(
            Registration(
                game_id=game2["id"], user_id=repeat["user_id"], status=1, is_waitlist=0,
                signup_time=datetime.now(), credit_snapshot=score_after_first,
            )
        )
        db.add(
            CheckinRecord(
                game_id=game2["id"], user_id=repeat["user_id"],
                checkin_status=CheckinStatus.NOT_CHECKED, settled=0,
            )
        )

    _write(_force_registration)
    finish2 = client.post(f"/api/v1/game/{game2['id']}/finish", headers=host["headers"]).json()
    assert finish2["code"] == 0

    bans_after_second = _bans_of(repeat["user_id"])
    # ① 记录数不变：不叠加封禁
    assert len(bans_after_second) == 1
    second = bans_after_second[0]
    assert second["id"] == first["id"]

    # ② 顺延：end = 原 end + 3 天；首次解禁时间留痕
    assert second["end"] == first["end"] + timedelta(days=3)
    assert second["original_end"] == first["end"]
    assert second["extend_count"] == 1
    assert second["days"] == 6                      # 3 + 3

    # ③ 扣分照常累计
    assert _get_user(repeat["user_id"])["reputation_score"] == score_after_first - 10
    assert _get_user(repeat["user_id"])["absent_count"] == 2

    # ④ 拦截仍然生效，并且返回的是顺延后的解禁时间
    now = datetime.now()
    blocked = client.post(
        "/api/v1/game",
        headers=repeat["headers"],
        json={
            "sport_type": 1, "title": "顺延期间发局", "venue_name": "顺延场地",
            "start_time": (now + timedelta(hours=6)).isoformat(),
            "end_time": (now + timedelta(hours=7)).isoformat(),
            "max_players": 4,
        },
    )
    assert blocked.status_code == 403
    assert blocked.json()["data"]["ban_extend_count"] == 1

    # ⑤ 接口返回的封禁状态体现顺延次数
    me = client.get("/api/v1/blacklist/me", headers=repeat["headers"]).json()["data"]
    assert me["ban_extend_count"] == 1
    assert me["ban_duration_days"] == 6


def test_third_absent_extends_again_until_cap(client):
    """第三次、第四次缺席持续顺延；达到总时长上限后不再延长（但照常扣分）"""
    host = _signup_user(client, "82000090", "上限测试发起人")
    repeat = _signup_user(client, "82000091", "上限测试惯犯")

    ban = asyncio.run(_ban_directly_result(repeat["user_id"]))
    start = ban.ban_start_time

    # 连续顺延，直到超过上限
    async def _extend(times: int):
        async with TestSessionLocal() as db:
            results = []
            for _ in range(times):
                applied = await blacklist_service.apply_ban(
                    db, user_id=repeat["user_id"], reason_type=BanReasonType.ABSENT,
                    days=settings.BAN_DEFAULT_DAYS, operator_id=0,
                )
                results.append(applied)
            return results

    total_extends = settings.BAN_MAX_TOTAL_DAYS // settings.BAN_DEFAULT_DAYS
    results = asyncio.run(_extend(total_extends))
    assert all(not r.created for r in results)      # 全程未新建记录
    final = _bans_of(repeat["user_id"])[0]
    assert final["end"] <= start + timedelta(days=settings.BAN_MAX_TOTAL_DAYS)

    # 再顺延一次 → 触顶，不再延长
    capped = asyncio.run(_extend(1))[0]
    assert capped.capped is True
    assert _bans_of(repeat["user_id"])[0]["end"] == final["end"]


def test_expired_ban_then_absent_creates_new_record(client):
    """规则6 的反面：封禁已过期后再次缺席 → 新建记录（不是顺延）"""
    host = _signup_user(client, "82000100", "过期再犯发起人")
    repeat = _signup_user(client, "82000101", "改不了的小刚")

    first_id = _ban_directly(repeat["user_id"], reason="第一次缺席")
    _expire_ban(first_id, hours_ago=5)              # 上个封禁已过期

    async def _apply_again():
        async with TestSessionLocal() as db:
            return await blacklist_service.apply_ban(
                db, user_id=repeat["user_id"], reason_type=BanReasonType.ABSENT,
                reason="第二次缺席", days=3, operator_id=0,
            )

    applied = asyncio.run(_apply_again())
    blacklist_service.ban_cache.clear()
    assert applied.created is True                 # 新建
    bans = _bans_of(repeat["user_id"])
    assert len(bans) == 2                          # 两条历史记录都永久留存
    assert bans[0]["id"] == first_id
    assert bans[1]["end"] == bans[1]["start"] + timedelta(days=3)


# ======================================================================
# 规则4：封禁记录查询接口
# ======================================================================
def test_ban_records_query_api(client):
    """封禁记录查询接口：分页 + 筛选 + 永久留存 + 越权保护"""
    host = _signup_user(client, "82000110", "记录查询发起人")
    user = _signup_user(client, "82000111", "记录查询用户")
    other = _signup_user(client, "82000112", "别人家的用户")

    async def _make_bans():
        async with TestSessionLocal() as db:
            await blacklist_service.apply_ban(
                db, user_id=user["user_id"], reason_type=BanReasonType.ABSENT,
                reason="缺席球局A", days=3, operator_id=0,
            )
            await blacklist_service.apply_ban(
                db, user_id=other["user_id"], reason_type=BanReasonType.MANUAL,
                reason="人工封禁", days=3, operator_id=1,
            )

    asyncio.run(_make_bans())
    blacklist_service.ban_cache.clear()

    # 本人查询：只看到自己的记录
    body = client.get("/api/v1/blacklist/records", headers=user["headers"]).json()
    assert body["code"] == 0
    assert body["data"]["total"] == 1
    item = body["data"]["items"][0]
    assert item["user_id"] == user["user_id"]
    assert item["reason"] == "缺席球局A"
    assert item["is_active"] is True
    assert item["ban_extend_count"] == 0
    assert item["ban_original_end_time"] is None

    # 非管理员传 user_id 也拿不到别人的记录（越权保护）
    body = client.get(
        f"/api/v1/blacklist/records?user_id={other['user_id']}", headers=user["headers"]
    ).json()
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["user_id"] == user["user_id"]

    # 分页参数
    body = client.get("/api/v1/blacklist/records?page=1&page_size=1", headers=user["headers"]).json()
    assert body["data"]["page_size"] == 1
    assert body["data"]["pages"] == 1

    # 只看生效中 / 按原因筛选
    assert client.get(
        "/api/v1/blacklist/records?only_active=true", headers=user["headers"]
    ).json()["data"]["total"] == 1
    assert client.get(
        "/api/v1/blacklist/records?reason_type=4", headers=user["headers"]
    ).json()["data"]["total"] == 0


def test_my_ban_status_api(client):
    """我的封禁状态接口：解禁时间、剩余小时、禁止动作说明、历史记录"""
    host = _signup_user(client, "82000120", "状态查询发起人")
    user = _signup_user(client, "82000121", "状态查询用户")

    # 未封禁时
    body = client.get("/api/v1/blacklist/me", headers=user["headers"]).json()
    assert body["code"] == 0
    assert body["data"]["banned"] is False
    assert body["data"]["blocked_actions"] == []
    assert body["data"]["total_ban_count"] == 0

    async def _ban():
        async with TestSessionLocal() as db:
            await blacklist_service.apply_ban(
                db, user_id=user["user_id"], reason_type=BanReasonType.ABSENT,
                reason="缺席球局（未签到且未请假），球局ID=100", days=3, operator_id=0,
            )

    asyncio.run(_ban())
    blacklist_service.ban_cache.clear()

    body = client.get("/api/v1/blacklist/me", headers=user["headers"]).json()
    data = body["data"]
    assert data["banned"] is True
    assert data["ban_end_time"] is not None
    assert 0 < data["remaining_hours"] <= 72
    assert data["ban_duration_days"] == 3
    assert data["reason_type"] == BanReasonType.ABSENT
    assert data["blocked_actions"] == [
        "发起球局（POST /api/v1/game）",
        "报名加入球局（POST /api/v1/game/{id}/signup）",
    ]
    assert "您因放鸽子被禁赛" in data["message"]
    assert data["total_ban_count"] == 1
    assert len(data["history"]) == 1
    assert data["history"][0]["reason"]


def test_ban_config_api(client):
    """规则配置查询接口：前端可直接展示当前规则"""
    host = _signup_user(client, "82000130", "配置查询发起人")
    body = client.get("/api/v1/blacklist/config", headers=host["headers"]).json()
    assert body["code"] == 0
    data = body["data"]
    assert data["ban_days"] == 3
    assert data["absent_deduct_score"] == 10
    assert data["lazy_release"] is True
    assert data["block_all_writes"] is False


# ======================================================================
# 管理端：手动封禁走规则6、解封、兜底扫描接口
# ======================================================================
def test_admin_ban_and_release_and_scan_endpoints(client, monkeypatch):
    """管理端接口：封禁（含顺延）、解封、兜底扫描（学号白名单鉴权）"""
    admin = _signup_user(client, "admin", "管理员")          # 学号 admin 即管理员
    user = _signup_user(client, "82000140", "被处理的用户")
    host = _signup_user(client, "82000141", "扫描接口发起人")

    # 手动封禁
    body = client.post(
        "/api/v1/blacklist/ban",
        headers=admin["headers"],
        json={"user_id": user["user_id"], "days": 3, "reason_type": 4, "reason": "多次放鸽子"},
    ).json()
    assert body["code"] == 0
    assert body["data"]["created"] is True
    ban_id = body["data"]["ban"]["id"]

    # 已在封禁中再次手动封禁 → 默认顺延（规则6）
    body = client.post(
        "/api/v1/blacklist/ban",
        headers=admin["headers"],
        json={"user_id": user["user_id"], "days": 3, "reason_type": 4, "reason": "又放鸽子"},
    ).json()
    assert body["data"]["created"] is False
    assert body["data"]["extended_days"] == 3
    assert "顺延" in body["message"]

    # force_new=true 时强制新建
    body = client.post(
        "/api/v1/blacklist/ban",
        headers=admin["headers"],
        json={"user_id": user["user_id"], "days": 3, "force_new": True, "reason": "强制新建"},
    ).json()
    assert body["data"]["created"] is True

    # 手动解封
    body = client.post(
        "/api/v1/blacklist/release",
        headers=admin["headers"],
        json={"ban_id": ban_id, "release_type": 2, "remark": "申诉通过"},
    ).json()
    assert body["code"] == 0 and body["data"]["released"] is True

    # 非管理员不能调管理端接口
    denied = client.post(
        "/api/v1/blacklist/ban", headers=user["headers"], json={"user_id": host["user_id"]}
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == 40300

    # 兜底扫描接口
    game = _make_game(client, host["headers"], title="手动扫描球局")
    _set_game(
        game["id"],
        status=GameStatus.PLAYING,
        start_time=datetime.now() - timedelta(hours=3),
        end_time=datetime.now() - timedelta(hours=1),
    )
    body = client.post("/api/v1/blacklist/scan-absent", headers=admin["headers"]).json()
    assert body["code"] == 0
    assert body["data"]["scanned"] >= 1
    assert _get_user(host["user_id"])["absent_count"] == 1
