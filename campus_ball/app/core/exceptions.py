"""
自定义异常 + 全局异常处理器
====================================================================
业务代码直接 `raise BizException(...)` 即可，
响应格式统一走 app.core.response，前端无需区分错误来源。
====================================================================
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.response import BAN_MESSAGE_TEMPLATE, RespCode, fail

logger = logging.getLogger(__name__)


# ==================================================================
# 异常定义
# ==================================================================
class BizException(Exception):
    """业务异常基类：code 走 RespCode，http_status 控制 HTTP 状态码"""

    code: int = RespCode.SERVER_ERROR
    http_status: int = status.HTTP_200_OK  # 业务错误默认仍返回 200，便于前端统一处理
    with_msg_alias: bool = False  # True 时响应体额外输出 msg 字段（小黑屋按产品规则需要）

    def __init__(self, message: str, code: int | None = None, data=None):
        self.message = message
        self.code = code if code is not None else self.code
        self.data = data
        super().__init__(message)


class ParamException(BizException):
    """参数错误"""

    code = RespCode.PARAM_ERROR
    http_status = status.HTTP_400_BAD_REQUEST


class AuthException(BizException):
    """未登录 / 缺少 Token"""

    code = RespCode.UNAUTHORIZED
    http_status = status.HTTP_401_UNAUTHORIZED


class TokenExpiredException(BizException):
    """Token 已过期：前端收到该码应跳转登录（或先尝试用 refresh_token 续期）"""

    code = RespCode.TOKEN_EXPIRED
    http_status = status.HTTP_401_UNAUTHORIZED

    def __init__(self, message: str = "登录已过期，请重新登录"):
        super().__init__(message)


class TokenInvalidException(BizException):
    """Token 非法：签名错误、被篡改、类型不符等"""

    code = RespCode.TOKEN_INVALID
    http_status = status.HTTP_401_UNAUTHORIZED

    def __init__(self, message: str = "登录凭证无效，请重新登录"):
        super().__init__(message)


class AccountDisabledException(BizException):
    """账号被禁用（管理员操作），与「小黑屋禁赛」区分开"""

    code = RespCode.ACCOUNT_DISABLED
    http_status = status.HTTP_403_FORBIDDEN

    def __init__(self, message: str = "账号已被禁用，请联系管理员"):
        super().__init__(message)


class PermissionException(BizException):
    """无权限（例如非组织者修改球局）"""

    code = RespCode.FORBIDDEN
    http_status = status.HTTP_403_FORBIDDEN


class ForbiddenException(PermissionException):
    """
    无权限（语义更明确的写法）：资源存在，但当前用户无权操作，
    例如「只有球局发起人可以核销签到」。
    继承自 PermissionException，因此 `except PermissionException` 同样能捕获。
    """

    def __init__(self, message: str = "无权限执行该操作"):
        super().__init__(message)


class BannedException(BizException):
    """
    小黑屋异常：用户处于禁赛期。

    响应体（规则3 指定）：
        {"code": 403, "msg": "您因放鸽子被禁赛，将于 2026-11-21 20:00 解除",
         "message": "同上（平台统一字段，兼容既有前端）",
         "data": {"ban_end_time": ..., "ban_duration_days": 3, "reason": ..., "ban_extend_count": 0}}
    """

    code = RespCode.BANNED
    http_status = status.HTTP_403_FORBIDDEN
    with_msg_alias = True  # 让全局异常处理器额外输出 msg 字段

    def __init__(
        self,
        message: str = BAN_MESSAGE_TEMPLATE.format(end="未知"),
        ban_end_time=None,
        ban_duration_days: int | None = None,
        reason: str | None = None,
        reason_type: int | None = None,
        extend_count: int = 0,
    ):
        super().__init__(
            message,
            data={
                "banned": True,
                "ban_end_time": ban_end_time.isoformat() if ban_end_time else None,
                "ban_duration_days": ban_duration_days,
                "ban_extend_count": extend_count,
                "reason": reason,
                "reason_type": reason_type,
            },
        )


class NotFoundException(BizException):
    """资源不存在"""

    code = RespCode.NOT_FOUND
    http_status = status.HTTP_404_NOT_FOUND


class ConflictException(BizException):
    """状态冲突：重复报名 / 重复签到 / 名额已满等"""

    code = RespCode.CONFLICT
    http_status = status.HTTP_409_CONFLICT


# ==================================================================
# 全局异常处理器注册
# ==================================================================
def register_exception_handlers(app: FastAPI) -> None:
    """把所有异常处理器挂到 FastAPI 实例上（在 main.py 调用）"""

    @app.exception_handler(BizException)
    async def biz_exception_handler(request: Request, exc: BizException):
        """业务异常：转为统一响应体（小黑屋额外带 msg 字段）"""
        logger.warning("[业务异常] %s %s -> %s", request.method, request.url.path, exc.message)
        body = fail(code=exc.code, message=exc.message, data=exc.data)
        if exc.with_msg_alias:
            body["msg"] = exc.message
        return JSONResponse(status_code=exc.http_status, content=body)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """
        Pydantic 参数校验失败：提取第一条错误，前端好展示。
        注意：exc.errors() 的 ctx 里可能带 ValueError 等不可 JSON 序列化的对象
        （model_validator 抛错时就会出现），必须只挑 JSON 安全的字段返回，
        否则响应构造阶段会抛 "Object of type ValueError is not JSON serializable"。
        """
        errors = exc.errors()
        safe_errors = [
            {
                "loc": [str(x) for x in item.get("loc", [])],
                "msg": str(item.get("msg", "")),
                "type": str(item.get("type", "")),
            }
            for item in errors
        ]
        first = safe_errors[0] if safe_errors else {}
        loc = ".".join(x for x in first.get("loc", []) if x != "body")
        message = f"参数错误：{loc} {first.get('msg', '')}".strip()
        logger.info("[参数校验失败] %s %s -> %s", request.method, request.url.path, message)
        return JSONResponse(
            status_code=422,  # 参数校验失败（直接写数字，避免不同 Starlette 版本的常量改名告警）
            content=fail(code=RespCode.PARAM_ERROR, message=message, data=safe_errors),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """HTTP 异常（404 / 405 等）"""
        return JSONResponse(
            status_code=exc.status_code,
            content=fail(code=exc.status_code * 100, message=str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """兜底：未捕获异常打日志，生产环境不暴露堆栈"""
        logger.exception("[未处理异常] %s %s", request.method, request.url.path)
        message = f"服务器内部错误：{exc}" if settings.DEBUG else "服务器内部错误，请稍后重试"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=fail(code=RespCode.SERVER_ERROR, message=message),
        )
