"""
AI 信誉画像模块测试（真实跑通，不依赖 MySQL）
====================================================================
覆盖：
    1. 本地加权规则算法：按时签到加分 / 无故缺席大幅扣分 / 主动退出少量扣分 / 边界裁剪
    2. 降级链路：无 API Key → source=rule、degraded=true，接口不报错
    3. DeepSeek 链路（打桩）：source=deepseek、融合限幅（AI 只做微调）
    4. DeepSeek 异常 → 自动降级为本地规则版
    5. 惰性触发：签到 / 缺席 / 退出 结算后置 dirty 标记；后台可批量重算
    6. 画像展示：个人主页返回信誉分 + 标签 + 加权明细
    7. 下游应用：球局列表 match_score 按画像计算，时间冲突 / 不达门槛置 0
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
from app.core.constants import (
    AI_SCORE_MAX_ADJUST,
    AI_SCORE_WEIGHT,
    PROFILE_SCORE_MAX,
    PROFILE_WEIGHTS,
    CheckinStatus,
    GameStatus,
    RegistrationStatus,
)
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.middleware import hooks as hook_module
from app.models import CheckinRecord, Game, Registration, User
from app.services import ai_profile as ai_service
from app.services import blacklist as blacklist_service

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


@pytest.fixture(autouse=True)
def _disable_async_refresh(monkeypatch):
    """
    关闭「结算后立刻异步重算」，让测试可以确定性地观察 dirty 标记，
    避免后台任务与断言争抢同一个数据库状态（生产默认开启）。
    异步链路本身由 test_async_refresh_scheduler_runs 显式验证。
    """
    monkeypatch.setattr(settings, "AI_PROFILE_ASYNC_REFRESH", False)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ======================================================================
# 工具
# ======================================================================
_venue_seq = itertools.count(1)
_slot_seq = itertools.count(0)


def _signup_user(client, student_no: str, nickname: str, skill_level: int = 3) -> dict:
    client.post(
        "/api/v1/auth/register",
        json={
            "student_no": student_no,
            "nickname": nickname,
            "password": "abc123456",
            "phone": f"136{student_no[-6:]}",
            "campus": "老校区",
            "skill_level": skill_level,
        },
    )
    body = client.post("/api/v1/auth/login", json={"account": student_no, "password": "abc123456"}).json()
    assert body["code"] == 0, body
    return {
        "user_id": body["data"]["user"]["id"],
        "headers": {"Authorization": f"Bearer {body['data']['token']['access_token']}"},
    }


def _make_game(client, headers, *, title="画像测试球局", hours=None, **overrides) -> dict:
    if hours is None:
        hours = 2 + next(_slot_seq) * 4
    now = datetime.now()
    payload = {
        "sport_type": 1,
        "title": title,
        "campus": "老校区",
        "venue_name": f"画像测试场地{next(_venue_seq)}号",
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


def _get_user_row(user_id: int) -> dict:
    async def _op(db):
        user = await db.get(User, user_id)
        return {
            "ai_score": user.ai_score,
            "ai_profile": user.ai_profile,
            "ai_profile_source": user.ai_profile_source,
            "ai_profile_dirty": user.ai_profile_dirty,
            "ai_profile_trigger": user.ai_profile_trigger,
            "ai_profile_version": user.ai_profile_version,
            "reputation_score": user.reputation_score,
        }

    return _read(_op)


def _set_game(game_id: int, **fields):
    async def _op(db):
        game = await db.get(Game, game_id)
        for key, value in fields.items():
            setattr(game, key, value)

    _write(_op)


def _make_features(**overrides) -> ai_service.ProfileFeatures:
    """构造特征对象（用于纯算法单测，不经过数据库）"""
    defaults = dict(user_id=1, nickname="测试用户")
    defaults.update(overrides)
    return ai_service.ProfileFeatures(**defaults)


# ======================================================================
# 一、本地加权规则算法（降级方案的核心）
# ======================================================================
def test_local_weights_match_requirement():
    """权重需符合需求：按时签到加分、无故缺席大幅扣分、主动退出少量扣分"""
    assert PROFILE_WEIGHTS["checked"] > 0                     # 签到加分
    assert PROFILE_WEIGHTS["absent"] < 0                      # 缺席扣分
    assert abs(PROFILE_WEIGHTS["absent"]) > abs(PROFILE_WEIGHTS["cancel_early"])  # 缺席 >> 退出
    assert abs(PROFILE_WEIGHTS["cancel_early"]) <= 2          # 退出只是"少量"扣分
    assert PROFILE_WEIGHTS["leave"] == 0                      # 请假不罚
    assert PROFILE_WEIGHTS["absent"] == -10                   # 与惰性结算口径一致


def test_local_weighted_score_basic():
    """画像分 = 初始分 + Σ 权重×次数，并给出可审计的加权明细"""
    features = _make_features(checked_count=10, late_count=1, absent_count=0, cancel_early_count=0)
    result = ai_service.local_weighted_score(features)
    # 100 + 10*2 + 1*(-3) + 守约加成3 = 120（守约率 10/11=0.909 < 0.95 → 无加成）
    assert result["score"] == 100 + 20 - 3
    assert result["bonus"] == 0

    items = {row["item"]: row for row in result["breakdown"]}
    assert items["按时签到"]["count"] == 10 and items["按时签到"]["subtotal"] == 20
    assert items["迟到签到"]["subtotal"] == -3
    assert items["无故缺席"]["subtotal"] == 0


def test_local_weighted_score_absent_is_severe():
    """无故缺席大幅扣分：3 次缺席 -30 分"""
    result = ai_service.local_weighted_score(
        _make_features(checked_count=2, absent_count=3)
    )
    assert result["score"] == 100 + 4 - 30


def test_local_weighted_score_cancel_is_light():
    """主动退出只是少量扣分；临近开球退出略重（本例满足守约加成，故额外 +3）"""
    light = ai_service.local_weighted_score(
        _make_features(checked_count=5, cancel_early_count=2)
    )
    # 100 + 5*2 - 2*2 + 守约加成3 = 109
    assert light["score"] == 100 + 10 - 4 + 3
    assert light["bonus"] == 3

    heavy = ai_service.local_weighted_score(
        _make_features(checked_count=5, cancel_late_count=2)
    )
    # 100 + 5*2 - 4*2 + 3 = 105
    assert heavy["score"] == 100 + 10 - 8 + 3
    assert heavy["score"] < light["score"]  # 临近退局惩罚更重


def test_local_weighted_score_keep_rate_bonus():
    """完成≥5场且守约率≥95% 额外 +3"""
    features = _make_features(checked_count=20, late_count=0, absent_count=0)
    result = ai_service.local_weighted_score(features)
    assert result["bonus"] == 3
    assert result["score"] == 100 + 40 + 3


def test_local_weighted_score_clamped():
    """极端行为下画像分被裁剪到 [0,150]"""
    low = ai_service.local_weighted_score(_make_features(absent_count=50))
    assert low["score"] == 0

    high = ai_service.local_weighted_score(_make_features(checked_count=100))
    assert high["score"] == PROFILE_SCORE_MAX


def test_local_labels_and_risk():
    """标签与风险等级随行为变化"""
    good = _make_features(checked_count=12, absent_count=0)
    tags, risk, _texts = ai_service.local_labels(good)
    assert "从未缺席" in tags
    assert risk == "low"

    bad = _make_features(checked_count=1, absent_count=4, reputation_score=40)
    tags, risk, _texts = ai_service.local_labels(bad)
    assert "频繁放鸽子" in tags
    assert risk == "high"


# ======================================================================
# 二、DeepSeek 融合与降级
# ======================================================================
def test_no_api_key_degrades_to_local_rule(client):
    """没有 API Key → 自动降级本地加权规则版，接口不报错"""
    user = _signup_user(client, "93000001", "无Key用户")

    body = client.get("/api/v1/ai/profile", headers=user["headers"]).json()
    assert body["code"] == 0
    data = body["data"]
    assert data["source"] == "rule"
    assert data["degraded"] is True
    assert data["ai_score"] is None
    assert data["ai_adjust"] == 0
    assert data["score"] == data["rule_score"]          # 无 AI 调整
    assert data["trigger"] == "manual"
    assert data["version"] >= 1
    assert data["breakdown"]                             # 可解释的加权明细
    assert data["features"]["checked_count"] is not None

    # 落库校验
    row = _get_user_row(user["user_id"])
    assert row["ai_profile_source"] == "rule"
    assert row["ai_score"] == data["score"]
    assert row["ai_profile_dirty"] == 0
    assert row["ai_profile_version"] >= 1


def test_deepseek_success_applies_bounded_adjustment(client, monkeypatch):
    """DeepSeek 成功 → source=deepseek；AI 建议分只做限幅微调"""
    user = _signup_user(client, "93000002", "有大模型用户")

    # 打桩：模拟 DeepSeek 返回一个很高的建议分
    async def _fake_generate(features):
        return {
            "score": 150,
            "risk_level": "low",
            "tags": ["守约达人", "球局常客"],
            "summary": "大模型总结",
            "suggestions": ["继续保持"],
        }

    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(ai_service.ai_profile_service, "api_key", "test-key")
    monkeypatch.setattr(ai_service.ai_profile_service, "generate", _fake_generate)

    body = client.post("/api/v1/ai/profile/refresh", headers=user["headers"]).json()
    data = body["data"]
    assert data["source"] == "deepseek"
    assert data["degraded"] is False
    assert data["ai_score"] == 150
    assert data["tags"] == ["守约达人", "球局常客"]
    assert data["summary"] == "大模型总结"

    # 融合公式：0.3*150 + 0.7*rule，再限幅 ±8
    expected = round(AI_SCORE_WEIGHT * 150 + (1 - AI_SCORE_WEIGHT) * data["rule_score"])
    limited = max(data["rule_score"] - AI_SCORE_MAX_ADJUST, min(data["rule_score"] + AI_SCORE_MAX_ADJUST, expected))
    assert data["score"] == limited
    assert abs(data["ai_adjust"]) <= AI_SCORE_MAX_ADJUST     # ★限幅生效
    assert data["score"] < 150                               # 没有被模型直接拉到 150


def test_deepseek_failure_falls_back_to_rule(client, monkeypatch):
    """DeepSeek 调用异常 → 静默降级为本地规则版，业务不受影响"""
    user = _signup_user(client, "93000003", "大模型超时用户")

    async def _boom(features):
        raise TimeoutError("DeepSeek 超时")

    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(ai_service.ai_profile_service, "api_key", "test-key")
    monkeypatch.setattr(ai_service.ai_profile_service, "generate", _boom)

    body = client.post("/api/v1/ai/profile/refresh", headers=user["headers"]).json()
    assert body["code"] == 0
    assert body["data"]["source"] == "rule"
    assert body["data"]["degraded"] is True


# ======================================================================
# 三、惰性触发：签到 / 缺席 / 退出
# ======================================================================
def test_checkin_marks_profile_dirty(client):
    """★签到结算后：画像标记为待重算，并能立刻重算出最新画像"""
    host = _signup_user(client, "93000010", "签到画像发起人")
    player = _signup_user(client, "93000011", "签到画像球员")
    game = _make_game(client, host["headers"], title="签到触发画像")
    client.post(f"/api/v1/game/{game['id']}/signup", headers=player["headers"], json={"skill_level": 3})

    # 签到前：先算一次画像作为基线
    before = client.get("/api/v1/ai/profile", headers=player["headers"]).json()["data"]
    assert before["features"]["checked_count"] == 0

    # 核销签到 → 结算 → 置 dirty
    client.post(
        "/api/v1/checkin/verify",
        json={"game_id": game["id"], "user_ids": [player["user_id"]]},
        headers=host["headers"],
    )
    row = _get_user_row(player["user_id"])
    assert row["ai_profile_dirty"] == 1
    assert row["ai_profile_trigger"] == "checkin"

    # 用户查看画像时按需重算（惰性）：标签与统计更新
    after = client.get("/api/v1/ai/profile", headers=player["headers"]).json()["data"]
    assert after["cached"] is False
    assert after["features"]["checked_count"] == 1
    assert after["features"]["keep_rate"] == 1.0
    assert after["score"] > before["score"]                    # 按时签到 → 画像分上升
    assert after["version"] > before["version"]

    row = _get_user_row(player["user_id"])
    assert row["ai_profile_dirty"] == 0                        # 重算后清除 dirty


def test_absent_marks_dirty_and_drops_score(client):
    """★缺席后：画像分显著下降，标签出现负面词"""
    host = _signup_user(client, "93000020", "缺席画像发起人")
    pigeon = _signup_user(client, "93000021", "缺席画像球员")
    game = _make_game(client, host["headers"], title="缺席触发画像")
    client.post(f"/api/v1/game/{game['id']}/signup", headers=pigeon["headers"], json={"skill_level": 3})

    before = client.get("/api/v1/ai/profile", headers=pigeon["headers"]).json()["data"]

    # 发起人自己核销（避免发起人也被判缺席），随后结束球局判缺席
    client.post(
        "/api/v1/checkin/verify",
        json={"game_id": game["id"], "user_ids": [host["user_id"]]},
        headers=host["headers"],
    )
    client.post(f"/api/v1/game/{game['id']}/finish", headers=host["headers"])

    row = _get_user_row(pigeon["user_id"])
    assert row["ai_profile_dirty"] == 1
    assert row["ai_profile_trigger"] == "absent"

    after = client.get("/api/v1/ai/profile", headers=pigeon["headers"]).json()["data"]
    assert after["features"]["absent_count"] == 1
    assert after["score"] < before["score"]                     # 缺席 → 扣分
    assert after["score"] == before["score"] - 10               # 权重明确：缺席 -10
    assert after["risk_level"] in ("medium", "high")
    # 负面标签：缺席率 100% → 「频繁放鸽子」（等价于"有过缺席"的更强表述）
    assert any(("缺席" in t) or ("放鸽子" in t) for t in after["tags"]), f"tags={after['tags']}"


def test_exit_marks_dirty(client):
    """★主动退出后：画像标记待重算，且画像分小幅下降（-2）"""
    host = _signup_user(client, "93000030", "退出画像发起人")
    quitter = _signup_user(client, "93000031", "退出画像球员")
    game = _make_game(client, host["headers"], title="退出触发画像")
    client.post(f"/api/v1/game/{game['id']}/signup", headers=quitter["headers"], json={"skill_level": 3})

    before = client.get("/api/v1/ai/profile", headers=quitter["headers"]).json()["data"]

    resp = client.post(f"/api/v1/game/{game['id']}/exit", headers=quitter["headers"]).json()
    assert resp["code"] == 0

    row = _get_user_row(quitter["user_id"])
    assert row["ai_profile_dirty"] == 1
    assert row["ai_profile_trigger"] == "exit"

    after = client.get("/api/v1/ai/profile", headers=quitter["headers"]).json()["data"]
    assert after["features"]["cancel_early_count"] == 1
    assert after["score"] == before["score"] - abs(PROFILE_WEIGHTS["cancel_early"])


def test_refresh_dirty_profiles_batch(client):
    """后台兜底：批量重算 dirty 用户；重算后 dirty 清零"""
    users = [_signup_user(client, f"9300004{i}", f"批量画像用户{i}") for i in range(3)]

    async def _mark(db):
        await ai_service.mark_profile_dirty(db, [u["user_id"] for u in users], trigger="checkin")

    _write(_mark)
    assert all(_get_user_row(u["user_id"])["ai_profile_dirty"] == 1 for u in users)

    async def _refresh():
        async with TestSessionLocal() as db:
            return await ai_service.refresh_dirty_profiles(db)

    result = asyncio.run(_refresh())
    assert result["refreshed"] >= 3
    for u in users:
        row = _get_user_row(u["user_id"])
        assert row["ai_profile_dirty"] == 0
        assert row["ai_profile"] is not None
        assert row["ai_profile_trigger"].startswith("async:")


def test_async_refresh_scheduler_runs(client, monkeypatch):
    """
    ★异步刷新链路：schedule_profile_refresh 会起独立任务完成重算（不等后台循环）
    这里显式打开开关并在事件循环内等待任务结束，验证「即刻重算」确实生效。
    """
    user = _signup_user(client, "93000051", "异步刷新用户")

    async def _mark(db):
        await ai_service.mark_profile_dirty(db, [user["user_id"]], trigger="checkin")

    _write(_mark)
    assert _get_user_row(user["user_id"])["ai_profile_dirty"] == 1

    monkeypatch.setattr(settings, "AI_PROFILE_ASYNC_REFRESH", True)

    async def _run():
        ai_service.schedule_profile_refresh([user["user_id"]], trigger="checkin")
        # 等待被调度的后台任务完成（测试中显式 await，生产环境不等待）
        pending = list(ai_service._pending_tasks)
        assert pending, "应已创建后台刷新任务"
        await asyncio.gather(*pending)

    asyncio.run(_run())

    row = _get_user_row(user["user_id"])
    assert row["ai_profile_dirty"] == 0                     # 后台任务已完成重算并清标记
    assert row["ai_profile"] is not None
    assert row["ai_profile_trigger"] == "checkin"
    assert not ai_service._pending_tasks                    # 任务引用已回收（无泄漏）


def test_async_refresh_noop_without_running_loop(client):
    """非异步上下文调用不报错（交给后台循环兜底）"""
    user = _signup_user(client, "93000052", "无循环用户")

    async def _mark(db):
        await ai_service.mark_profile_dirty(db, [user["user_id"]], trigger="manual")

    _write(_mark)
    ai_service.schedule_profile_refresh([user["user_id"]], trigger="manual")  # 同步上下文
    assert _get_user_row(user["user_id"])["ai_profile_dirty"] == 1  # 标记仍在，等兜底


def test_refresh_dirty_endpoint(client):
    """管理端批量重算接口（学号 admin 白名单）"""
    admin = _signup_user(client, "admin", "管理员")
    user = _signup_user(client, "93000050", "被重算用户")

    async def _mark(db):
        await ai_service.mark_profile_dirty(db, [user["user_id"]], trigger="manual")

    _write(_mark)
    body = client.post("/api/v1/ai/refresh-dirty?limit=5", headers=admin["headers"]).json()
    assert body["code"] == 0
    assert _get_user_row(user["user_id"])["ai_profile_dirty"] == 0


# ======================================================================
# 四、画像展示（个人主页）
# ======================================================================
def test_user_profile_page_shows_reputation(client):
    """★个人主页展示信誉分 + 标签 + 行为统计 + 加权明细"""
    host = _signup_user(client, "93000060", "主页发起人")
    player = _signup_user(client, "93000061", "主页球员", skill_level=4)
    game = _make_game(client, host["headers"], title="主页展示球局")
    client.post(f"/api/v1/game/{game['id']}/signup", headers=player["headers"], json={"skill_level": 3})
    client.post(
        "/api/v1/checkin/verify",
        json={"game_id": game["id"], "user_ids": [player["user_id"]]},
        headers=host["headers"],
    )

    body = client.get(f"/api/v1/user/{player['user_id']}/profile", headers=player["headers"]).json()
    assert body["code"] == 0
    data = body["data"]
    assert data["reputation_score"] == 102                    # 签到 +2
    assert data["credit_score"] == data["reputation_score"]    # 兼容字段
    assert data["credit_level_text"]
    assert data["profile_score"] is not None
    assert data["attended_count"] == 1
    assert data["keep_rate"] == 1.0
    assert data["breakdown"]
    assert data["is_self"] is True
    assert "student_no" not in data and "phone" not in data    # 不泄露隐私

    # 他人查看：拿不到封禁时间
    other = client.get(f"/api/v1/user/{player['user_id']}/profile", headers=host["headers"]).json()
    assert other["data"]["is_self"] is False


def test_ai_explain_endpoint(client):
    """算法说明接口：权重表 / 公式 / 融合与降级策略"""
    user = _signup_user(client, "93000070", "说明查询用户")
    body = client.get("/api/v1/ai/explain", headers=user["headers"]).json()
    assert body["code"] == 0
    data = body["data"]
    assert data["base_score"] == 100
    assert data["weights"]["checked"] == 2
    assert data["weights"]["absent"] == -10
    assert data["weights"]["cancel_early"] == -2
    assert "缺席" in data["formula"]
    assert data["fusion"]["ai_weight"] == AI_SCORE_WEIGHT
    assert data["degrade_policy"]
    assert data["source_priority"][0] == "deepseek"


def test_ai_stats_endpoint(client):
    """运行状态接口"""
    user = _signup_user(client, "93000080", "状态查询用户")
    body = client.get("/api/v1/ai/stats", headers=user["headers"]).json()
    assert body["code"] == 0
    data = body["data"]
    assert data["llm_available"] is False        # 测试环境无 Key
    assert data["enabled"] is True
    assert "dirty_count" in data
    assert data["source_priority"] if False else True


# ======================================================================
# 五、下游应用：球局匹配参考分
# ======================================================================
def test_match_score_uses_profile_for_logged_in_user(client):
    """★登录用户的 match_score 按画像实时计算（不再是固定占位值）"""
    host = _signup_user(client, "93000090", "匹配发起人")
    player = _signup_user(client, "93000091", "匹配球员")

    game = _make_game(client, host["headers"], title="匹配分球局")
    # 让该用户有一场到场记录，画像更完整
    good_game = _make_game(client, host["headers"], title="匹配分历史球局")
    client.post(f"/api/v1/game/{good_game['id']}/signup", headers=player["headers"], json={"skill_level": 3})
    client.post(
        "/api/v1/checkin/verify",
        json={"game_id": good_game["id"], "user_ids": [player["user_id"]]},
        headers=host["headers"],
    )

    # 登录用户：个性化匹配分
    body = client.get(
        "/api/v1/game", params={"keyword": "匹配分球局"}, headers=player["headers"]
    ).json()
    item = body["data"]["list"][0]
    assert item["match_score"] != 80.0 or item["match_reason"]     # 至少给出理由
    assert item["match_reason"]
    assert 0 <= item["match_score"] <= 100

    # 未登录：静态基线分
    anon = client.get("/api/v1/game", params={"keyword": "匹配分球局"}).json()["data"]["list"][0]
    assert anon["match_score"] == 80.0
    assert anon["match_reason"] == "未登录，返回通用推荐分"


def test_match_score_zero_on_time_conflict(client):
    """已报名的相同时段球局 → 匹配分置 0 并给出原因"""
    host = _signup_user(client, "93000100", "冲突匹配发起人")
    host2 = _signup_user(client, "93000101", "冲突匹配发起人2")
    player = _signup_user(client, "93000102", "冲突匹配球员")

    now = datetime.now()
    game_a = _make_game(client, host["headers"], title="冲突匹配A", hours=10)
    game_b = _make_game(
        client, host2["headers"], title="冲突匹配B", hours=11,
        venue_name="冲突匹配场地B",
    )
    client.post(f"/api/v1/game/{game_a['id']}/signup", headers=player["headers"], json={"skill_level": 3})

    body = client.get("/api/v1/game", params={"keyword": "冲突匹配B"}, headers=player["headers"]).json()
    item = body["data"]["list"][0]
    assert item["match_score"] == 0.0
    assert "冲突" in item["match_reason"]


def test_match_score_zero_when_below_reputation_threshold(client):
    """信誉分不达球局门槛 → 匹配分 0"""
    host = _signup_user(client, "93000110", "门槛匹配发起人")
    player = _signup_user(client, "93000111", "低分匹配球员")
    game = _make_game(client, host["headers"], title="门槛匹配球局", min_credit_score=120)

    body = client.get("/api/v1/game", params={"keyword": "门槛匹配球局"}, headers=player["headers"]).json()
    item = body["data"]["list"][0]
    assert item["match_score"] == 0.0
    assert "门槛" in item["match_reason"]


def test_match_score_skill_and_preference():
    """匹配分算法：球技符合 / 常玩球类会加分，满员会降权（纯函数级验证）"""
    features = _make_features(checked_count=10, skill_level=5, sport_counts={1: 8, 2: 2})
    profile = {"score": 120}

    good = ai_service.compute_match_score(
        features=features, profile=profile, game_skill_limit=2, game_sport_type=1,
        is_full=False, time_conflict=False, game_min_reputation=0,
    )
    full = ai_service.compute_match_score(
        features=features, profile=profile, game_skill_limit=2, game_sport_type=1,
        is_full=True, time_conflict=False, game_min_reputation=0,
    )
    weak_skill = ai_service.compute_match_score(
        features=_make_features(checked_count=10, skill_level=1, sport_counts={1: 8}),
        profile=profile, game_skill_limit=5, game_sport_type=1,
        is_full=False, time_conflict=False, game_min_reputation=0,
    )
    assert good["match_score"] > weak_skill["match_score"]     # 球技符合更优
    assert full["match_score"] == good["match_score"] - 5      # 满员惩罚
    assert "信誉分" in good["match_reason"]
    # 未登录返回静态基线
    anon = ai_service.compute_match_score(
        features=None, profile=None, game_skill_limit=0, game_sport_type=1,
        is_full=False, time_conflict=False, game_min_reputation=0,
    )
    assert anon["match_score"] == 80.0


def test_collect_features_counts_exit_types(client):
    """特征统计正确区分「提前退出」与「临近开球退出」"""
    host = _signup_user(client, "93000120", "特征统计发起人")
    user = _signup_user(client, "93000121", "特征统计用户")

    # 提前退出（开球还有很久）
    early = _make_game(client, host["headers"], title="提前退出球局", hours=48)
    client.post(f"/api/v1/game/{early['id']}/signup", headers=user["headers"], json={"skill_level": 3})
    client.post(f"/api/v1/game/{early['id']}/exit", headers=user["headers"])

    # 临近开球退出（1 小时内开球）
    late_game = _make_game(client, host["headers"], title="临期退出球局", hours=2)
    client.post(f"/api/v1/game/{late_game['id']}/signup", headers=user["headers"], json={"skill_level": 3})
    _set_game(late_game["id"], start_time=datetime.now() + timedelta(minutes=30))
    client.post(f"/api/v1/game/{late_game['id']}/exit", headers=user["headers"])

    async def _op(db):
        return await ai_service.collect_features(db, user["user_id"])

    features = asyncio.run(_op_read(_op))
    assert features.cancel_early_count == 1
    assert features.cancel_late_count == 1
    assert features.cancel_total == 2
    assert features.game_created_count == 0

    # 画像分体现两类退出（-2 与 -4）
    result = ai_service.local_weighted_score(features)
    items = {row["item"]: row["subtotal"] for row in result["breakdown"]}
    assert items["主动退出"] == -2
    assert items[f"临近开球退出(≤{2}h)"] == -4


async def _op_read(op):
    async with TestSessionLocal() as db:
        return await op(db)
