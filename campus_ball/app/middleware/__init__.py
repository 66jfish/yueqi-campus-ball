"""
中间件包
====================================================================
    auth.py   —— JWT 认证中间件（统一鉴权 + 统一拦截钩子，注册在路由前置）
    hooks.py  —— 认证拦截钩子中心（小黑屋 / 账号状态 / 后续可扩展规则）
====================================================================
"""

from app.middleware.auth import AuthMiddleware, log_registered_hooks
from app.middleware.hooks import (
    blacklist_hook,
    list_auth_hooks,
    register_auth_hook,
    register_default_hooks,
    run_auth_hooks,
    set_session_scope_factory,
)

__all__ = [
    "AuthMiddleware",
    "log_registered_hooks",
    "register_auth_hook",
    "register_default_hooks",
    "run_auth_hooks",
    "list_auth_hooks",
    "set_session_scope_factory",
    "blacklist_hook",
]
