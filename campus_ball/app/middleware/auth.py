"""
JWT 认证中间件（统一鉴权前置）
====================================================================
位置：注册在路由之前（Starlette 中间件栈），所有 /api/v1/* 请求先经过这里，
      再到具体接口。业务接口只需声明 `current_user: CurrentUser` 依赖即可复用，
      无需每个接口自己解析 Token。

职责（只做鉴权，不做业务）：
    1. 判断路径是否需要鉴权（公开路径直接放行）
    2. 从 Authorization: Bearer <token> 或 Cookie 中取出 Token
    3. 校验 JWT（签名 / 过期 / 签发方 / 受众 / 类型）
    4. 把结果写入 request.state，供依赖注入与接口直接读取：
           request.state.user_id        当前用户ID
           request.state.token_payload  JWT 载荷（含 jti，便于后续强制下线）
    5. 依次执行「认证拦截钩子」（小黑屋、账号状态等），统一拦截、无需在接口里重复写
    6. 任何失败都返回统一响应 {code, message, data}，并给出准确的错误码

路径策略（三档，全部在下方常量里集中配置）：
    PUBLIC   公开路径：不解析 Token、不执行钩子（登录、注册、健康检查、API 文档）
    OPTIONAL 可选登录：有 Token 就解析并执行钩子，无 Token 放行（球局浏览类接口）
    DEFAULT  其余路径：必须携带有效 Token，否则 401

与依赖注入的分工：
    中间件负责「能不能进来」，deps.get_current_user 负责「取到用户对象」；
    后者会复用 request.state.user_id，不会重复解析 Token。
====================================================================
"""

import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import settings
from app.core.exceptions import AuthException, BizException, TokenInvalidException
from app.core.response import ApiResponse, RespCode
from app.core.security import decode_token, get_token_remaining_seconds
from app.middleware.hooks import list_auth_hooks, run_auth_hooks

logger = logging.getLogger(__name__)

_API = settings.API_V1_PREFIX


class AuthMiddleware(BaseHTTPMiddleware):
    """JWT 认证中间件：统一鉴权 + 统一拦截钩子"""

    # ---------------- 1) 公开路径：不鉴权、不查小黑屋 ----------------
    PUBLIC_PATHS: frozenset[str] = frozenset(
        {
            "/",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/health",
        }
    )
    PUBLIC_PREFIXES: tuple[str, ...] = (
        f"{_API}/auth/login",     # 登录
        f"{_API}/auth/register",  # 注册
        f"{_API}/auth/refresh",   # 刷新令牌（用 refresh_token 换新令牌）
        f"{_API}/system",         # 运行时信息 + 定时任务入口（接口内用 CRON_SECRET 自行鉴权）
    )

    # ---------------- 2) 可选登录：匿名可读，登录后享有个性化与钩子校验 ----------------
    OPTIONAL_PREFIXES: tuple[str, ...] = (
        f"{_API}/game",     # 球局列表 / 详情（游客可浏览，报名等写操作由接口依赖强制登录）
        f"{_API}/auth/logout",
    )

    # ---------------- 3) 其余路径：必须登录 ----------------

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 预检请求直接放行，交给 CORS 中间件处理
        if request.method == "OPTIONS":
            return await call_next(request)

        if not settings.AUTH_ENABLED:
            return await call_next(request)

        path = request.url.path

        # 1) 公开路径
        if path in self.PUBLIC_PATHS or self._match(path, self.PUBLIC_PREFIXES):
            return await call_next(request)

        is_optional = self._match(path, self.OPTIONAL_PREFIXES)
        token = self._extract_token(request)

        # 2) 无 Token
        if not token:
            if is_optional:
                return await call_next(request)  # 可选登录路径：匿名放行
            return self._error(
                RespCode.UNAUTHORIZED,
                status.HTTP_401_UNAUTHORIZED,
                "未登录或缺少访问令牌，请先登录",
            )

        # 3) 解析 Token
        try:
            payload = decode_token(token)  # 内部会区分「过期」与「非法」
            user_id = int(payload["sub"])
        except BizException as exc:
            if is_optional and settings.AUTH_OPTIONAL_IGNORE_INVALID:
                # 可选登录路径不因坏 Token 报错，按匿名处理
                logger.info("可选登录路径忽略无效 Token：%s", path)
                return await call_next(request)
            return self._error(exc.code, exc.http_status, exc.message)
        except (KeyError, TypeError, ValueError):
            if is_optional and settings.AUTH_OPTIONAL_IGNORE_INVALID:
                return await call_next(request)
            return self._error(
                RespCode.TOKEN_INVALID, status.HTTP_401_UNAUTHORIZED, "登录凭证无效，请重新登录"
            )

        # 4) 写入 request.state，供依赖注入与接口复用
        request.state.user_id = user_id
        request.state.token_payload = payload
        request.state.token_remaining_seconds = get_token_remaining_seconds(payload)

        # 5) 统一拦截钩子：小黑屋 / 账号状态 / 后续扩展的任意全局规则
        try:
            await run_auth_hooks(request, user_id)
        except BizException as exc:
            # 小黑屋响应按产品规则额外输出 msg 字段
            extra = {"msg": exc.message} if getattr(exc, "with_msg_alias", False) else None
            return self._error(exc.code, exc.http_status, exc.message, exc.data, extra=extra)
        except Exception as exc:  # noqa: BLE001 - 钩子框架级异常
            logger.exception("认证钩子执行失败 user_id=%s", user_id)
            if not settings.BLACKLIST_FAIL_OPEN:
                return self._error(
                    RespCode.SERVER_ERROR, status.HTTP_500_INTERNAL_SERVER_ERROR, "认证校验失败，请稍后重试"
                )

        return await call_next(request)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _match(path: str, prefixes: tuple[str, ...]) -> bool:
        """前缀匹配"""
        return any(path.startswith(prefix) for prefix in prefixes)

    @staticmethod
    def _extract_token(request: Request) -> str | None:
        """
        取 Token，优先级：
            1. Authorization: Bearer <token>
            2. Cookie（前端把 Token 放 Cookie 时）
            3. X-Access-Token 自定义头（方便小程序 / 第三方客户端）
        """
        prefix = settings.AUTH_TOKEN_PREFIX.strip()
        header_value = request.headers.get(settings.AUTH_HEADER_NAME) or request.headers.get(
            settings.AUTH_HEADER_NAME.title()
        )
        if header_value:
            if prefix and header_value.lower().startswith(prefix.lower() + " "):
                return header_value[len(prefix) + 1 :].strip()
            return header_value.strip()  # 容错：客户端直接放裸 Token

        cookie_token = request.cookies.get(settings.AUTH_COOKIE_NAME)
        if cookie_token:
            return cookie_token.strip()

        custom = request.headers.get("X-Access-Token")
        return custom.strip() if custom else None

    @staticmethod
    def _error(
        code: int, http_status: int, message: str, data=None, extra: dict | None = None
    ) -> JSONResponse:
        """
        统一的错误响应（与接口层格式完全一致，前端只有一套解析逻辑）。
        extra 用于追加产品规则要求的额外字段（如小黑屋的 msg）。
        """
        body = ApiResponse(code=code, message=message, data=data).model_dump()
        if extra:
            body.update(extra)
        return JSONResponse(
            status_code=http_status,
            content=body,
            headers={"WWW-Authenticate": "Bearer"} if http_status == 401 else None,
        )


def log_registered_hooks() -> None:
    """启动日志：打印已注册的认证钩子（排查「为什么被拦」时很有用）"""
    logger.info("认证拦截钩子：%s", " -> ".join(list_auth_hooks()) or "（无）")


__all__ = ["AuthMiddleware", "log_registered_hooks", "AuthException", "TokenInvalidException"]
