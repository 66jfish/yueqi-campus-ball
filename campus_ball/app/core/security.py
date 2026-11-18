"""
安全模块：密码哈希（bcrypt）+ JWT 签发/校验
====================================================================
一、密码哈希
    1. 首选 bcrypt：自带随机盐、cost 可调（默认 12 轮），抗 GPU 爆破，
       存储格式形如 $2b$12$xxxxxxxxxxxxxxxxxxxxxx，固定 60 字符
    2. 兼容历史 PBKDF2 哈希（pbkdf2_sha256$迭代$盐$哈希）：
       老用户仍可正常登录，登录成功后会由 auth 服务自动升级为 bcrypt
    3. bcrypt 只取密码前 72 字节：超长密码先做 SHA-256 摘要再交给 bcrypt，
       不截断、不丢失熵；该规则固定写在代码里，校验时使用同一规则
    4. 校验使用 bcrypt.checkpw（内部为常数时间比较），避免时序攻击

二、JWT
    payload 结构：
        sub  : 用户ID（字符串，JWT 规范要求）
        iat  : 签发时间   exp: 过期时间   jti: 令牌唯一ID（预留强制下线）
        type : access | refresh（防止用 refresh 令牌直接访问业务接口）
        iss  : 签发方     aud: 受众（均可在 .env 配置，留空则不校验）
    校验时统一验证：签名、过期时间（含时钟容差 leeway）、签发方、受众

三、本文件只有纯函数，不访问数据库，便于单元测试与复用
====================================================================
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import AuthException, TokenExpiredException, TokenInvalidException

logger = logging.getLogger(__name__)

# ---------------------------- 常量 ----------------------------
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

_LEGACY_PBKDF2_PREFIX = "pbkdf2_sha256"
_BCRYPT_MAX_BYTES = 72  # bcrypt 算法本身的输入上限


# ==================================================================
# 一、密码哈希
# ==================================================================
def _prepare_password(raw_password: str) -> bytes:
    """
    把明文密码转换成 bcrypt 可接受的字节串。
    超过 72 字节时先做 SHA-256 摘要（32 字节），而不是直接截断，
    这样长密码的全部字符都会影响哈希结果。
    """
    raw = raw_password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raw = hashlib.sha256(raw).digest()
    return raw


def hash_password(raw_password: str, rounds: int | None = None) -> str:
    """
    生成 bcrypt 密码哈希
    :param rounds: bcrypt cost（默认读配置 BCRYPT_ROUNDS=12）
    :return: 形如 $2b$12$.... 的 60 字符哈希串
    """
    cost = rounds or settings.BCRYPT_ROUNDS
    salt = bcrypt.gensalt(rounds=cost)
    hashed = bcrypt.hashpw(_prepare_password(raw_password), salt)
    return hashed.decode("utf-8")


def _verify_legacy_pbkdf2(raw_password: str, password_hash: str) -> bool:
    """校验历史 PBKDF2 哈希（仅为平滑迁移保留，新数据一律 bcrypt）"""
    try:
        algorithm, iterations, salt_hex, digest_hex = password_hash.split("$")
        if algorithm != _LEGACY_PBKDF2_PREFIX:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", raw_password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


def verify_password(raw_password: str, password_hash: str) -> bool:
    """
    校验明文密码与数据库中的哈希是否匹配（自动识别 bcrypt / 历史 PBKDF2）
    """
    if not password_hash:
        return False

    # 历史数据：PBKDF2
    if password_hash.startswith(_LEGACY_PBKDF2_PREFIX):
        return _verify_legacy_pbkdf2(raw_password, password_hash)

    # 当前方案：bcrypt
    try:
        return bcrypt.checkpw(_prepare_password(raw_password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # 哈希串损坏或格式非法，一律判定失败
        return False


def needs_rehash(password_hash: str) -> bool:
    """
    是否需要重新哈希（用于登录时自动升级）：
        - 历史 PBKDF2 哈希
        - bcrypt cost 低于当前配置
    """
    if not password_hash:
        return False
    if password_hash.startswith(_LEGACY_PBKDF2_PREFIX):
        return True
    if password_hash.startswith("$2"):
        try:
            current_cost = int(password_hash.split("$")[2])
        except (IndexError, ValueError):
            return True
        return current_cost < settings.BCRYPT_ROUNDS
    return True


def verify_and_rehash(raw_password: str, password_hash: str) -> tuple[bool, str | None]:
    """
    校验密码，并在需要时返回新的哈希（供登录成功后静默升级）
    :return: (是否通过, 新哈希或 None)
    """
    if not verify_password(raw_password, password_hash):
        return False, None
    if needs_rehash(password_hash):
        return True, hash_password(raw_password)
    return True, None


# ==================================================================
# 二、JWT
# ==================================================================
def _base_payload(subject: int | str, token_type: str, expires_minutes: int) -> dict[str, Any]:
    """构造 JWT 公共载荷"""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
        "jti": secrets.token_hex(8),  # 预留：写入 Redis 即可实现强制下线
        "type": token_type,
    }
    if settings.JWT_ISSUER:
        payload["iss"] = settings.JWT_ISSUER
    if settings.JWT_AUDIENCE:
        payload["aud"] = settings.JWT_AUDIENCE
    return payload


def create_access_token(
    subject: int | str,
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    签发 Access Token（业务接口鉴权用）
    :param subject: 用户ID
    :param extra_claims: 附加信息，如 {"student_no": "20230001", "role": "admin"}
    """
    payload = _base_payload(
        subject, TOKEN_TYPE_ACCESS, expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: int | str, expires_minutes: int | None = None) -> str:
    """签发 Refresh Token（仅用于换取新的 Access Token）"""
    payload = _base_payload(
        subject, TOKEN_TYPE_REFRESH, expires_minutes or settings.REFRESH_TOKEN_EXPIRE_MINUTES
    )
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_token_pair(subject: int | str, extra_claims: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    一次性签发 access + refresh，返回给接口层包装成统一响应
    """
    return {
        "access_token": create_access_token(subject, extra_claims=extra_claims),
        "refresh_token": create_refresh_token(subject),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


def decode_token(token: str, expect_type: str | None = TOKEN_TYPE_ACCESS) -> dict[str, Any]:
    """
    解析并校验 Token（签名 / 过期 / 签发方 / 受众 / 类型）
    :raises TokenExpiredException: 已过期
    :raises TokenInvalidException: 非法或类型不符
    """
    options = {"require": ["exp", "iat", "sub"]}
    kwargs: dict[str, Any] = {
        "algorithms": [settings.JWT_ALGORITHM],
        "options": options,
        "leeway": settings.JWT_LEEWAY_SECONDS,  # 容忍客户端与服务端之间的时钟偏差
    }
    if settings.JWT_ISSUER:
        kwargs["issuer"] = settings.JWT_ISSUER
    if settings.JWT_AUDIENCE:
        kwargs["audience"] = settings.JWT_AUDIENCE

    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, **kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredException("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        logger.info("Token 校验失败：%s", exc)
        raise TokenInvalidException("登录凭证无效，请重新登录") from exc

    if expect_type and payload.get("type") != expect_type:
        raise TokenInvalidException("登录凭证类型不正确")
    return payload


def get_user_id_from_token(token: str, expect_type: str | None = TOKEN_TYPE_ACCESS) -> int:
    """从 Token 中解析出用户ID（int）；失败抛认证异常"""
    payload = decode_token(token, expect_type=expect_type)
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenInvalidException("登录凭证缺少用户标识") from exc


def get_token_remaining_seconds(payload: dict[str, Any]) -> int:
    """剩余有效秒数（供前端做续期提醒、供后续 Redis 黑名单设置 TTL）"""
    exp = payload.get("exp")
    if not exp:
        return 0
    return max(0, int(exp - datetime.now(timezone.utc).timestamp()))


__all__ = [
    "TOKEN_TYPE_ACCESS",
    "TOKEN_TYPE_REFRESH",
    "hash_password",
    "verify_password",
    "needs_rehash",
    "verify_and_rehash",
    "create_access_token",
    "create_refresh_token",
    "create_token_pair",
    "decode_token",
    "get_user_id_from_token",
    "get_token_remaining_seconds",
    "AuthException",
]
