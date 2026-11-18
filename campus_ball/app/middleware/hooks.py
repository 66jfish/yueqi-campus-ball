"""
认证拦截钩子中心（小黑屋等统一拦截点）
====================================================================
设计目的
    把一个「拿到 user_id 之后、进入业务接口之前」的统一拦截点抽象成钩子，
    后续新增任何全局拦截规则（小黑屋禁赛、账号封禁、强制改密、异地登录、
    设备指纹、接口限流……）只需要写一个函数 + 注册一次，
    不需要在每个接口里重复写判断，也不需要改中间件本身。

钩子签名
    async def hook(request: Request, user_id: int) -> None
        - 通过：正常返回
        - 拦截：抛 app.core.exceptions.BizException 的子类（如 BannedException）

执行时机
    app/middleware/auth.py 解析出 user_id 之后、call_next 之前，按注册顺序依次执行；
    任意钩子抛异常即中断请求并返回统一错误响应。

测试友好
    钩子里需要数据库会话，取自 SESSION_SCOPE_FACTORY；
    单元测试可用 set_session_scope_factory() 换成测试库会话工厂。
====================================================================
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BannedException, BizException
from app.db.session import async_session_scope
from app.services import blacklist as blacklist_service

logger = logging.getLogger(__name__)

# 钩子函数类型：接收请求与用户ID，拦截时抛业务异常
AuthHook = Callable[[Request, int], Awaitable[None]]


# ==================================================================
# 会话工厂（可替换，便于测试）
# ==================================================================
SESSION_SCOPE_FACTORY: Callable[[], Any] = async_session_scope


def set_session_scope_factory(factory: Callable[[], Any]) -> None:
    """替换钩子使用的数据库会话工厂（单元测试注入内存库时使用）"""
    global SESSION_SCOPE_FACTORY
    SESSION_SCOPE_FACTORY = factory


# ==================================================================
# 钩子注册表
# ==================================================================
_hooks: list[tuple[str, AuthHook]] = []


def register_auth_hook(name: str, hook: AuthHook, *, prepend: bool = False) -> None:
    """
    注册认证拦截钩子

    :param name: 钩子名（便于日志与排查，需唯一）
    :param hook: 钩子函数
    :param prepend: True 时插到最前（先执行）

    示例（后续扩展小黑屋之外的规则）：
        async def device_ban_hook(request: Request, user_id: int) -> None:
            if await is_device_banned(request.headers.get("X-Device-Id")):
                raise ForbiddenException("该设备已被限制")
        register_auth_hook("device_ban", device_ban_hook)
    """
    if any(existing_name == name for existing_name, _ in _hooks):
        logger.warning("认证钩子 %s 已存在，跳过重复注册", name)
        return
    if prepend:
        _hooks.insert(0, (name, hook))
    else:
        _hooks.append((name, hook))
    logger.info("已注册认证拦截钩子：%s（当前共 %d 个）", name, len(_hooks))


def list_auth_hooks() -> list[str]:
    """当前已注册的钩子名列表（/health 或运维接口可展示）"""
    return [name for name, _ in _hooks]


def clear_auth_hooks() -> None:
    """清空钩子（主要供单元测试使用）"""
    _hooks.clear()


async def run_auth_hooks(request: Request, user_id: int) -> None:
    """
    依次执行所有钩子；任一钩子拦截（抛 BizException）即中断。
    钩子内部异常按策略处理：
        BLACKLIST_FAIL_OPEN=True  → 记录日志并放行（保可用性，默认）
        BLACKLIST_FAIL_OPEN=False → 直接拦截（安全优先）
    """
    for name, hook in _hooks:
        try:
            await hook(request, user_id)
        except BizException:
            raise  # 业务拦截：原样抛出，由全局异常处理器输出统一响应
        except Exception as exc:  # noqa: BLE001 - 钩子自身故障不能拖垮整站
            logger.error("认证钩子 %s 执行异常 user_id=%s：%s", name, user_id, exc)
            if not settings.BLACKLIST_FAIL_OPEN:
                raise BizException("认证校验失败，请稍后重试") from exc


# ==================================================================
# 内置钩子 1：小黑屋（禁赛）统一拦截 —— 规则3
# ==================================================================
# 白名单：被封禁用户仍然可以访问的路径前缀（查询类接口一律放行）
#   - 查看自己的封禁状态 / 解禁倒计时
#   - 查看个人主页与信誉分
HOOK_EXEMPT_PREFIXES: tuple[str, ...] = (
    f"{settings.API_V1_PREFIX}/blacklist/me",
    f"{settings.API_V1_PREFIX}/user/me",
)


async def blacklist_hook(request: Request, user_id: int) -> None:
    """
    小黑屋拦截钩子（中间件层，全局兜底）。

    规则3：只拦「写操作中的发局/报名」，查询类接口（GET）全部放行，
          让被封禁用户能看到球局列表与自己的封禁状态/解禁时间。
    规则4：是否仍在封禁期由 get_active_ban() 惰性判定（ban_end_time > NOW()），
          不依赖定时任务。

    拦截清单的判定口径与 get_current_active_user 依赖共用
    blacklist_service.is_ban_blocked_request()，避免两处规则不一致。
    """
    if any(request.url.path.startswith(prefix) for prefix in HOOK_EXEMPT_PREFIXES):
        return

    # 非「被禁动作」直接放行：查询接口、签到/核销、退出球局、请假等都不拦
    if not blacklist_service.is_ban_blocked_request(request.method, request.url.path):
        return

    async with SESSION_SCOPE_FACTORY() as db:  # type: AsyncSession
        ban = await blacklist_service.get_active_ban(db, user_id)
        if ban is None:
            return

    logger.info(
        "小黑屋拦截 user_id=%s %s %s 解禁时间=%s",
        user_id, request.method, request.url.path, ban.ban_end_time,
    )
    raise BannedException(
        message=ban.message(),
        ban_end_time=ban.ban_end_time,
        ban_duration_days=ban.ban_duration_days,
        reason=ban.reason,
        reason_type=ban.reason_type,
        extend_count=ban.extend_count,
    )


# ==================================================================
# 内置钩子 2：账号状态校验（禁用账号统一拦截）
# ==================================================================
async def account_status_hook(request: Request, user_id: int) -> None:
    """
    账号状态钩子：status != 1 的账号直接拦截。
    与 need_password_change / device_ban 等钩子一样，作为「全局规则」统一执行。
    """
    from app.core.constants import UserStatus
    from app.core.exceptions import AccountDisabledException, AuthException
    from app.models import User
    async with SESSION_SCOPE_FACTORY() as db:  # type: AsyncSession
        user = await db.get(User, user_id)

    if user is None or user.is_deleted:
        raise AuthException("账号不存在或已注销")
    if user.status != UserStatus.NORMAL:
        raise AccountDisabledException()


# ==================================================================
# 默认注册（中间件加载时可重复调用 register，函数内部做了去重）
# ==================================================================
def register_default_hooks() -> None:
    """注册脚手架自带的钩子：账号状态 → 小黑屋（顺序即执行顺序）"""
    register_auth_hook("account_status", account_status_hook)
    register_auth_hook("blacklist", blacklist_hook)


__all__ = [
    "AuthHook",
    "register_auth_hook",
    "register_default_hooks",
    "run_auth_hooks",
    "list_auth_hooks",
    "clear_auth_hooks",
    "set_session_scope_factory",
    "blacklist_hook",
    "account_status_hook",
    "HOOK_EXEMPT_PREFIXES",
]
