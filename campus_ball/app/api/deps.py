"""
API 依赖注入（认证相关）
====================================================================
与 JWT 认证中间件的分工：
    中间件（app/middleware/auth.py）—— 决定「请求能不能进来」，并写入 request.state.user_id
    本文件                          —— 决定「接口拿到哪个用户对象」

因此：
    - 需要登录的接口，直接声明 `current_user: CurrentUser` 即可复用，无需重复解析 Token
    - 中间件已完成解析时，这里直接复用 request.state.user_id（不重复解 Token）
    - 即使中间件被关闭（AUTH_ENABLED=false）或单测直接调用接口，
      本文件也能自行解析 Token，保证接口自身的健壮性
====================================================================
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import UserStatus
from app.core.exceptions import (
    AccountDisabledException,
    AuthException,
    BannedException,
    PermissionException,
)
from app.core.security import get_user_id_from_token
from app.db.session import get_db
from app.models import User
from app.services import blacklist as blacklist_service

# auto_error=False：没带 Token 时不由 FastAPI 直接抛错，交由我们返回统一格式
_bearer_scheme = HTTPBearer(auto_error=False, description="登录后获得的 JWT Access Token")


def _extract_token_from_request(
    request: Request, credentials: HTTPAuthorizationCredentials | None
) -> str | None:
    """从请求中取 Token：Authorization 头 > Cookie > 自定义头"""
    if credentials and credentials.credentials:
        return credentials.credentials
    cookie_token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    custom = request.headers.get("X-Access-Token")
    return custom.strip() if custom else None


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    获取当前登录用户（需登录接口统一使用）

    解析顺序：
        1. 中间件已解析好 → 直接用 request.state.user_id
        2. 否则自行解析 Token（兼容中间件关闭 / 单测场景）
    校验顺序：Token 有效 → 用户存在且未注销 → 账号状态正常
    """
    user_id = getattr(request.state, "user_id", None)

    if user_id is None:
        token = _extract_token_from_request(request, credentials)
        if not token:
            raise AuthException("未登录或缺少访问令牌，请先登录")
        user_id = get_user_id_from_token(token)

    user = await db.get(User, user_id)
    if user is None or user.is_deleted:
        raise AuthException("账号不存在或已注销")
    if user.status != UserStatus.NORMAL:
        raise AccountDisabledException()
    return user


async def get_optional_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """
    可选登录：登录了返回 User，未登录返回 None（球局列表等匿名可读接口用）
    注意：Token 非法时在此静默返回 None，与中间件对「可选登录路径」的策略保持一致。
    """
    user_id = getattr(request.state, "user_id", None)

    if user_id is None:
        token = _extract_token_from_request(request, credentials)
        if not token:
            return None
        try:
            user_id = get_user_id_from_token(token)
        except AuthException:
            return None

    user = await db.get(User, user_id)
    if user is None or user.is_deleted or user.status != UserStatus.NORMAL:
        return None
    return user


async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    管理员依赖（管理端接口使用）。
    脚手架阶段用「学号在白名单」简化判断，后续可替换为 t_user.role + RBAC 表。
    """
    admin_student_nos = {"admin"}  # TODO: 迁移到配置或数据库
    if current_user.student_no not in admin_student_nos:
        raise PermissionException("需要管理员权限")
    return current_user


# ==================================================================
# ★ 小黑屋独立依赖（规则3/规则4）
# ==================================================================
async def get_current_active_user(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    要求：已登录 + 未处于小黑屋封禁期。用于「发起球局 / 报名」等写操作接口。

    设计说明（为什么不每个接口自己写判断）：
        1. 复用现有 JWT 认证中间件的结果 —— current_user 已由中间件解析并写入
           request.state.user_id，本依赖不重复解析 Token；
        2. 拦截口径与中间件钩子共用 blacklist_service.is_ban_blocked_request()，
           两处规则永远一致；
        3. 接口侧只需声明 `current_user: CurrentActiveUser`，不必写任何判断。

    与中间件钩子的分工：
        中间件钩子 = 全局兜底（任何路径都不会漏）；
        本依赖     = 接口契约（显式声明「这个接口需要未被封禁的用户」），
                     即便 AUTH_ENABLED=false 或新增接口忘记配置，也能拦住。
    """
    # 查询类请求放行（例如接口自身允许 GET），非被禁动作也放行
    if not blacklist_service.is_ban_blocked_request(request.method, request.url.path):
        return current_user

    ban = await blacklist_service.get_active_ban(db, current_user.id)
    if ban is not None:
        raise BannedException(
            message=ban.message(),
            ban_end_time=ban.ban_end_time,
            ban_duration_days=ban.ban_duration_days,
            reason=ban.reason,
            reason_type=ban.reason_type,
            extend_count=ban.extend_count,
        )
    return current_user


async def require_active_user(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    强制版依赖：无论请求方法/路径，只要处于封禁期就拒绝。
    适合明确「只服务正常用户」的接口（例如将来路径调整后仍要拦截），
    比 get_current_active_user 更严格，不留 match 规则的余地。
    """
    ban = await blacklist_service.get_active_ban(db, current_user.id)
    if ban is not None:
        raise BannedException(
            message=ban.message(),
            ban_end_time=ban.ban_end_time,
            ban_duration_days=ban.ban_duration_days,
            reason=ban.reason,
            reason_type=ban.reason_type,
            extend_count=ban.extend_count,
        )
    return current_user


# 常用类型别名，接口签名更简洁
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_current_user)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
CurrentActiveUser = Annotated[User, Depends(get_current_active_user)]
RequireActiveUser = Annotated[User, Depends(require_active_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]

__all__ = [
    "get_db",
    "get_current_user",
    "get_optional_current_user",
    "get_current_admin",
    "CurrentUser",
    "OptionalUser",
    "CurrentAdmin",
    "DbSession",
]
