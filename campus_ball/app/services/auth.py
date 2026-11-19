"""
认证服务：注册 / 登录 / 刷新令牌 / 登出
====================================================================
密码存储：bcrypt（app/core/security.py）
    - 注册：hash_password() 生成 $2b$12$... 哈希入库，明文永不落库、不写日志
    - 登录：verify_and_rehash() 校验；若发现是历史 PBKDF2 哈希或 cost 偏低，
            校验通过后自动改写为最新 bcrypt 哈希（用户无感升级）
令牌：access + refresh 双令牌，载荷内含 jti，为后续 Redis 强制下线预留
====================================================================
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import UserStatus, map_credit_level
from app.core.exceptions import (
    AccountDisabledException,
    AuthException,
    ConflictException,
    ParamException,
    TokenInvalidException,
)
from app.core.security import (
    TOKEN_TYPE_REFRESH,
    create_token_pair,
    decode_token,
    get_token_remaining_seconds,
    hash_password,
    verify_and_rehash,
)
from app.models import User
from app.schemas import RegisterRequest

logger = logging.getLogger(__name__)


# ==================================================================
# 返回结构
# ==================================================================
@dataclass
class LoginResult:
    """登录成功结果"""

    user: User
    token: dict[str, Any]
    password_upgraded: bool = False  # 是否顺带把历史密码哈希升级为 bcrypt


# ==================================================================
# 注册
# ==================================================================
async def register(db: AsyncSession, payload: RegisterRequest) -> User:
    """
    用户注册
    1. 学号 / 手机号唯一性校验
    2. bcrypt 加密存储密码
    3. 初始化信誉分与信誉等级（惰性结算的起点）
    """
    # ★唯一性校验：phone 为 None 时绝不能参与比较
    #   原因：SQLAlchemy 会把 `User.phone == None` 编译成 `phone IS NULL`，
    #   于是「任何没填手机号的存量用户」都会被误判成冲突，导致新学号注册直接 409。
    #   因此只在客户端真正提供了手机号时才校验手机号。
    conditions = [User.student_no == payload.student_no]
    if payload.phone:
        conditions.append(User.phone == payload.phone)
    exists_stmt = select(User.id).where(or_(*conditions), User.is_deleted == 0)
    if (await db.execute(exists_stmt)).first():
        raise ConflictException("该学号或手机号已注册")

    user = User(
        student_no=payload.student_no,
        nickname=payload.nickname,
        real_name=payload.real_name,
        password_hash=hash_password(payload.password),  # ★ bcrypt 加密存储
        phone=payload.phone or None,
        campus=payload.campus,
        college=payload.college,
        grade=payload.grade,
        gender=payload.gender,
        credit_score=settings.CREDIT_SCORE_INIT,
        credit_level=int(map_credit_level(settings.CREDIT_SCORE_INIT)),
        status=UserStatus.NORMAL,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("新用户注册成功：id=%s student_no=%s", user.id, user.student_no)
    return user


# ==================================================================
# 登录
# ==================================================================
async def get_user_by_account(db: AsyncSession, account: str) -> User | None:
    """按学号或手机号查用户（登录用）"""
    stmt = select(User).where(
        or_(User.student_no == account, User.phone == account),
        User.is_deleted == 0,
    )
    return (await db.execute(stmt)).scalars().first()


async def login(db: AsyncSession, account: str, password: str) -> LoginResult:
    """
    账号密码登录

    安全细节：
        - 账号不存在与密码错误返回同一提示，避免账号探测
        - 账号被禁用单独提示（否则用户无法理解为什么密码正确却登录失败）
        - 登录成功后记录 last_login_at，并尽量静默升级历史密码哈希
    """
    user = await get_user_by_account(db, account)
    if not user:
        logger.info("登录失败（账号不存在）：%s", account)
        raise ParamException("账号或密码错误")

    passed, new_hash = verify_and_rehash(password, user.password_hash)
    if not passed:
        logger.info("登录失败（密码错误）：user_id=%s", user.id)
        raise ParamException("账号或密码错误")

    if user.status != UserStatus.NORMAL:
        raise AccountDisabledException()

    # 历史 PBKDF2 哈希 → 自动升级为 bcrypt（用户无感知）
    password_upgraded = new_hash is not None
    if password_upgraded:
        user.password_hash = new_hash

    user.last_login_at = datetime.now()
    await db.commit()
    await db.refresh(user)

    token = create_token_pair(
        user.id,
        extra_claims={
            "student_no": user.student_no,
            "nickname": user.nickname,
            "credit_level": user.credit_level,
        },
    )
    logger.info("登录成功：user_id=%s（密码哈希升级=%s）", user.id, password_upgraded)
    return LoginResult(user=user, token=token, password_upgraded=password_upgraded)


# ==================================================================
# 刷新令牌
# ==================================================================
async def refresh(db: AsyncSession, refresh_token: str) -> LoginResult:
    """
    用 refresh_token 换取新的 access_token（refresh_token 也一并轮换）
    注意：必须校验 type=refresh，防止拿 access_token 当 refresh_token 用
    """
    payload = decode_token(refresh_token, expect_type=TOKEN_TYPE_REFRESH)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenInvalidException("刷新令牌缺少用户标识") from exc

    user = await db.get(User, user_id)
    if user is None or user.is_deleted:
        raise AuthException("账号不存在或已注销")
    if user.status != UserStatus.NORMAL:
        raise AccountDisabledException()

    token = create_token_pair(
        user.id,
        extra_claims={"student_no": user.student_no, "nickname": user.nickname},
    )
    return LoginResult(user=user, token=token)


# ==================================================================
# 登出（预留：接入 Redis 后按 jti 拉黑）
# ==================================================================
async def logout(user_id: int | None, jti: str | None = None, exp: int | None = None) -> None:
    """
    登出。
    当前实现：客户端丢弃 Token 即可（JWT 无状态）。
    后续接入 Redis 时，在此把 jti 写入黑名单，TTL = 令牌剩余有效期，
    即可实现「登出后旧 Token 立即失效 / 管理员强制下线」。
    """
    if jti and exp:
        ttl = max(0, int(exp - datetime.now(timezone.utc).timestamp()))
        logger.info("登出：user_id=%s jti=%s（剩余 %s 秒，待接入 Redis 黑名单）", user_id, jti, ttl)
    else:
        logger.info("登出：user_id=%s", user_id)


def describe_token(payload: dict[str, Any]) -> dict[str, Any]:
    """返回令牌的元信息（调试用）"""
    return {
        "user_id": payload.get("sub"),
        "jti": payload.get("jti"),
        "type": payload.get("type"),
        "expires_in": get_token_remaining_seconds(payload),
        "expires_at": (
            datetime.fromtimestamp(payload["exp"], tz=timezone.utc).astimezone().isoformat()
            if payload.get("exp")
            else None
        ),
        "expire_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        "refresh_expire_days": round(settings.REFRESH_TOKEN_EXPIRE_MINUTES / 60 / 24, 1),
    }


# 便于外部构造「令牌即将过期」提示
TOKEN_REFRESH_THRESHOLD_SECONDS = 30 * 60


def should_refresh(payload: dict[str, Any]) -> bool:
    """剩余有效期是否已低于续期阈值（前端可在每次请求后据此决定是否静默续期）"""
    return get_token_remaining_seconds(payload) < TOKEN_REFRESH_THRESHOLD_SECONDS


def token_expire_at_minutes() -> timedelta:
    """访问令牌有效期（timedelta 形式，便于测试与展示）"""
    return timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
