"""
认证模块测试（真实跑通，不依赖 MySQL）
====================================================================
用内存 SQLite + 依赖覆盖（dependency_overrides）把认证链路完整跑一遍：
    bcrypt 存储 → 注册 → 登录签发 JWT → 中间件校验 → 钩子拦截（小黑屋/禁用）
若本机有 MySQL，可去掉 SQLite 装配直接连库跑同样逻辑。
====================================================================
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  确保模型全部注册
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_and_rehash,
    verify_password,
)
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.middleware import hooks as hook_module
from app.models import Blacklist, User
from app.services import blacklist as blacklist_service

# ----------------------------------------------------------------------
# SQLite 适配：去掉 MySQL 专有建表参数，并把 BIGINT 主键换成 INTEGER
# （SQLite 只有 INTEGER PRIMARY KEY 才自增；MySQL 下无此问题）
# ----------------------------------------------------------------------
for _table in Base.metadata.tables.values():
    for _key in ("mysql_charset", "mysql_collate", "mysql_engine"):
        _table.kwargs.pop(_key, None)
    for _col in _table.columns:
        if isinstance(_col.type, BigInteger):
            _col.type = Integer()

engine = create_async_engine(
    "sqlite+aiosqlite://",
    poolclass=StaticPool,  # 内存库需共享同一连接
    connect_args={"check_same_thread": False},
)
# autoflush=False 与生产会话（app/db/session.py）保持一致，避免测试掩盖真实行为
TestSessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def _test_session_scope():
    """替换认证钩子使用的会话工厂，让钩子也查测试库"""
    async with TestSessionLocal() as session:
        yield session


async def _override_get_db():
    async with TestSessionLocal() as session:
        yield session


@pytest.fixture(scope="module", autouse=True)
def _prepare_database():
    """建表 + 注入测试库会话"""
    asyncio.run(_create_tables())
    hook_module.set_session_scope_factory(_test_session_scope)
    app.dependency_overrides[get_db] = _override_get_db
    # 小黑屋缓存是进程级的、按 user_id 索引：换测试库必须清空，避免读到上一个库的封禁状态
    blacklist_service.ban_cache.clear()
    yield
    app.dependency_overrides.clear()
    blacklist_service.ban_cache.clear()


async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _register(client, **overrides):
    payload = {
        "student_no": "20230001",
        "nickname": "球场小王子",
        "password": "abc123456",
        "phone": "13800000001",
        "campus": "老校区",
        "skill_level": 3,
    }
    payload.update(overrides)
    return client.post("/api/v1/auth/register", json=payload)


def _login(client, account="20230001", password="abc123456"):
    return client.post("/api/v1/auth/login", json={"account": account, "password": password})


def _set_credit(user_id: int, score: int) -> None:
    """直接改信誉分，用于构造「低信誉」场景"""

    async def _run():
        async with TestSessionLocal() as db:
            user = await db.get(User, user_id)
            user.credit_score = score
            await db.commit()

    asyncio.run(_run())


def _add_ban(user_id: int, days: int = 3, reason: str = "缺席球局"):
    """
    走真实业务路径把用户关进小黑屋：调用 blacklist_service.ban_user()
    （它会写库并主动失效内存缓存，因此封禁后下一个请求立刻生效）
    """
    from app.services import blacklist as blacklist_service

    async def _run():
        async with TestSessionLocal() as db:
            await blacklist_service.ban_user(
                db, user_id=user_id, days=days, reason_type=1, reason=reason, operator_id=0
            )

    asyncio.run(_run())


def _disable_user(user_id: int) -> None:
    async def _run():
        async with TestSessionLocal() as db:
            user = await db.get(User, user_id)
            user.status = 0
            await db.commit()

    asyncio.run(_run())


# ======================================================================
# 一、bcrypt 密码哈希
# ======================================================================
def test_password_uses_bcrypt_format():
    """密码必须是 bcrypt 格式（$2b$ + cost），且可往返校验"""
    hashed = hash_password("abc123456")
    assert hashed.startswith("$2b$12$")
    assert len(hashed) == 60
    assert "abc123456" not in hashed  # 明文绝不出现
    assert verify_password("abc123456", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_bcrypt_salt_is_random():
    """同一密码两次哈希结果不同（随机盐）"""
    assert hash_password("abc123456") != hash_password("abc123456")


def test_verify_and_rehash_upgrades_legacy_pbkdf2():
    """历史 PBKDF2 哈希可登录，并自动升级为 bcrypt"""
    import hashlib

    salt = b"0123456789abcdef"
    legacy = (
        "pbkdf2_sha256$260000$" + salt.hex() + "$"
        + hashlib.pbkdf2_hmac("sha256", b"abc123456", salt, 260000).hex()
    )
    assert verify_password("abc123456", legacy) is True

    passed, new_hash = verify_and_rehash("abc123456", legacy)
    assert passed is True
    assert new_hash is not None and new_hash.startswith("$2b$")
    assert needs_rehash(legacy) is True
    assert needs_rehash(new_hash) is False  # 已是当前 cost，无需再升级


def test_long_password_over_72_bytes():
    """超过 bcrypt 72 字节上限的密码仍能正确校验（先 SHA-256 摘要，不截断）"""
    long_pwd = "球" * 40  # UTF-8 下 120 字节
    hashed = hash_password(long_pwd)
    assert verify_password(long_pwd, hashed) is True
    assert verify_password("球" * 39, hashed) is False


# ======================================================================
# 二、JWT 签发与校验
# ======================================================================
def test_jwt_round_trip_with_claims():
    token = create_access_token(7, extra_claims={"student_no": "20230001"})
    payload = decode_token(token)
    assert payload["sub"] == "7"
    assert payload["type"] == "access"
    assert payload["student_no"] == "20230001"
    assert payload["iss"] == "campus-ball"
    assert payload["jti"]  # 预留强制下线用的唯一ID


def test_refresh_token_type_isolation():
    """refresh 令牌不能用于访问业务接口"""
    from app.core.exceptions import TokenInvalidException

    refresh = create_refresh_token(7)
    with pytest.raises(TokenInvalidException):
        decode_token(refresh, expect_type="access")
    assert decode_token(refresh, expect_type="refresh")["type"] == "refresh"


def test_expired_token_raises_expired():
    from app.core.exceptions import TokenExpiredException

    token = create_access_token(7, expires_minutes=-1)
    with pytest.raises(TokenExpiredException):
        decode_token(token)


def test_tampered_token_raises_invalid():
    from app.core.exceptions import TokenInvalidException

    token = create_access_token(7)
    with pytest.raises(TokenInvalidException):
        decode_token(token + "tampered")


# ======================================================================
# 三、注册接口
# ======================================================================
def test_register_success_and_password_is_bcrypt(client):
    resp = _register(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["student_no"] == "20230001"
    assert body["data"]["credit_score"] == 100
    assert "password" not in body["data"] and "password_hash" not in body["data"]

    async def _check():
        async with TestSessionLocal() as db:
            user = await db.get(User, body["data"]["id"])
            assert user.password_hash.startswith("$2b$12$")  # ★ 库里是 bcrypt
            assert user.password_hash != "abc123456"

    asyncio.run(_check())


def test_register_duplicate_student_no(client):
    _register(client, student_no="20239999", phone="13800009999")
    resp = _register(client, student_no="20239999", phone="13800009998")
    assert resp.status_code == 409
    assert resp.json() == {"code": 40900, "message": "该学号或手机号已注册", "data": None}


def test_register_param_validation_unified_format(client):
    resp = _register(client, password="123")
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 40000
    assert "password" in body["message"]


# ======================================================================
# 四、登录接口
# ======================================================================
def test_login_success_returns_token_pair(client):
    _register(client, student_no="20231001", phone="13800001001")
    resp = _login(client, "20231001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["message"] == "登录成功"
    token = body["data"]["token"]
    assert token["token_type"] == "bearer"
    assert token["expires_in"] == 604800
    assert decode_token(token["access_token"])["sub"]  # 令牌可解析
    assert decode_token(token["refresh_token"], expect_type="refresh")["type"] == "refresh"
    assert body["data"]["user"]["student_no"] == "20231001"


def test_login_by_phone(client):
    _register(client, student_no="20231002", phone="13800001002")
    resp = _login(client, "13800001002")
    assert resp.json()["code"] == 0


def test_login_wrong_password(client):
    _register(client, student_no="20231003", phone="13800001003")
    resp = _login(client, "20231003", "wrong-password")
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000
    assert resp.json()["message"] == "账号或密码错误"


def test_login_nonexistent_account_same_message(client):
    """账号不存在与密码错误返回同一提示，避免账号探测"""
    resp = _login(client, "no-such-user", "abc123456")
    assert resp.json()["message"] == "账号或密码错误"


def test_refresh_token_endpoint(client):
    _register(client, student_no="20231004", phone="13800001004")
    login_body = _login(client, "20231004").json()
    resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_body["data"]["token"]["refresh_token"]},
    )
    assert resp.json()["code"] == 0
    assert decode_token(resp.json()["data"]["access_token"])["sub"]


# ======================================================================
# 五、JWT 中间件（路由前置统一鉴权）
# ======================================================================
def test_protected_endpoint_without_token(client):
    resp = client.get("/api/v1/user/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100  # 统一响应格式
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_protected_endpoint_with_valid_token(client):
    _register(client, student_no="20232001", phone="13800002001")
    access = _login(client, "20232001").json()["data"]["token"]["access_token"]

    resp = client.get("/api/v1/user/me", headers={"Authorization": f"Bearer {access}"})
    assert resp.status_code == 200
    assert resp.json()["data"]["student_no"] == "20232001"


def test_protected_endpoint_with_expired_token(client):
    token = create_access_token(1, expires_minutes=-1)
    resp = client.get("/api/v1/user/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 40101  # 令牌过期


def test_protected_endpoint_with_invalid_token(client):
    resp = client.get("/api/v1/user/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 40102  # 令牌非法


def test_public_path_needs_no_token(client):
    """登录接口本身属于公开路径，不会被中间件拦下"""
    resp = client.post("/api/v1/auth/login", json={"account": "20231001", "password": "abc123456"})
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


def test_optional_path_allows_anonymous(client):
    """球局列表属可选登录路径：匿名可访问（不是 401）"""
    resp = client.get("/api/v1/game")
    assert resp.status_code not in (401, 403)


def test_token_info_endpoint(client):
    _register(client, student_no="20232002", phone="13800002002")
    access = _login(client, "20232002").json()["data"]["token"]["access_token"]
    resp = client.get("/api/v1/auth/token-info", headers={"Authorization": f"Bearer {access}"})
    assert resp.json()["code"] == 0
    data = resp.json()["data"]
    assert data["type"] == "access"
    assert data["expires_in"] > 0
    assert data["need_refresh"] is False


# ======================================================================
# 六、拦截钩子（小黑屋 / 账号状态）
# ======================================================================
def test_blacklist_hook_blocks_write_actions_only(client):
    """
    ★小黑屋规则3：封禁期间只有「发局 / 报名」被拦；
    查询类接口（球局列表、个人主页、我的签到记录）与签到/核销全部放行。
    响应体按产品规则给出：{"code": 403, "msg": "您因放鸽子被禁赛，将于 xxx 解除"}
    """
    _register(client, student_no="20233001", phone="13800003001")
    user_id = _login(client, "20233001").json()["data"]["user"]["id"]
    access = _login(client, "20233001").json()["data"]["token"]["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    # 封禁前：可正常访问
    assert client.get("/api/v1/checkin/my", headers=headers).status_code == 200

    # 关进小黑屋（默认 3 天）
    _add_ban(user_id, days=3, reason="连续缺席")

    # ---------- 1) 被拦截：发起球局 / 报名 ----------
    for method, path, payload in (
        ("POST", "/api/v1/game", _game_payload_for_ban_test()),
        ("POST", "/api/v1/game/1/signup", None),
    ):
        resp = client.request(method, path, headers=headers, json=payload)
        assert resp.status_code == 403, path
        body = resp.json()
        assert body["code"] == 403, path                       # 产品规则：code=403
        assert "您因放鸽子被禁赛" in body["msg"], path           # 产品规则：msg 字段
        assert "解除" in body["msg"], path
        assert body["message"] == body["msg"], path            # 平台统一字段保持同值
        assert body["data"]["banned"] is True, path
        assert body["data"]["ban_end_time"], path
        assert body["data"]["ban_duration_days"] == 3, path

    # ---------- 2) 不被拦截：查询类接口 ----------
    for path in ("/api/v1/checkin/my", "/api/v1/user/me", "/api/v1/game", "/api/v1/blacklist/me"):
        assert client.get(path, headers=headers).status_code == 200, path

    # ---------- 3) 不被拦截：历史遗留球局的签到/核销（规则明确要求） ----------
    checkin_resp = client.post(
        "/api/v1/checkin/checkin",
        headers=headers,
        json={"game_id": 1, "checkin_type": 1},
    )
    assert checkin_resp.status_code != 403, checkin_resp.text


def test_blacklist_hook_exempts_self_status_endpoints(client):
    """被封禁用户仍可查询自己的封禁状态与资料（否则用户不知道为什么被封）"""
    _register(client, student_no="20233002", phone="13800003002")
    user_id = _login(client, "20233002").json()["data"]["user"]["id"]
    access = _login(client, "20233002").json()["data"]["token"]["access_token"]
    headers = {"Authorization": f"Bearer {access}"}
    _add_ban(user_id)

    resp = client.get("/api/v1/blacklist/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["banned"] is True

    resp = client.get("/api/v1/user/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["student_no"] == "20233002"


def _game_payload_for_ban_test() -> dict:
    """构造一个合法的发局请求体（用于验证被封禁用户发起球局时被拦截）"""
    now = datetime.now()
    return {
        "sport_type": 1,
        "title": "封禁期间试着发局",
        "venue_name": "封禁测试场地",
        "campus": "老校区",
        "start_time": (now + timedelta(hours=2)).isoformat(),
        "end_time": (now + timedelta(hours=3)).isoformat(),
        "max_players": 4,
        "min_players": 2,
    }


def test_expired_ban_does_not_block(client):
    """★到期自动解封：封禁已过期则不再拦截"""
    _register(client, student_no="20233003", phone="13800003003")
    user_id = _login(client, "20233003").json()["data"]["user"]["id"]
    access = _login(client, "20233003").json()["data"]["token"]["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    async def _run():
        async with TestSessionLocal() as db:
            start = datetime.now() - timedelta(days=5)  # 5 天前封的，3 天已到期
            db.add(
                Blacklist(
                    user_id=user_id,
                    ban_start_time=start,
                    ban_duration_days=3,
                    ban_end_time=Blacklist.calc_end_time(start, 3),
                    status=1,
                    reason_type=1,
                )
            )
            await db.commit()

    asyncio.run(_run())
    assert client.get("/api/v1/checkin/my", headers=headers).status_code == 200


def test_account_status_hook_blocks_disabled_user(client):
    _register(client, student_no="20233004", phone="13800003004")
    user_id = _login(client, "20233004").json()["data"]["user"]["id"]
    access = _login(client, "20233004").json()["data"]["token"]["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    _disable_user(user_id)
    resp = client.get("/api/v1/checkin/my", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["code"] == 40103  # 账号被禁用


def test_hook_chain_registered(client):
    """启动时钩子链已注册（账号状态 -> 小黑屋）"""
    assert hook_module.list_auth_hooks() == ["account_status", "blacklist"]


# ======================================================================
# 七、登出
# ======================================================================
def test_logout_is_idempotent(client):
    _register(client, student_no="20234001", phone="13800004001")
    access = _login(client, "20234001").json()["data"]["token"]["access_token"]

    resp = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert resp.json()["code"] == 0
    assert resp.json()["data"]["logout"] is True

    # 未登录调用也返回成功
    assert client.post("/api/v1/auth/logout").json()["code"] == 0
