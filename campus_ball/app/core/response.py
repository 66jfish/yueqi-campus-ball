"""
统一响应体
====================================================================
前端（Vue3 + Element Plus）统一按 { code, message, data } 解析，
code=0 表示成功，非 0 为业务错误码，便于前端统一做 message 提示。
====================================================================
"""

from enum import IntEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class RespCode(IntEnum):
    """业务响应码（HTTP 状态码另外表达）"""

    SUCCESS = 0            # 成功
    PARAM_ERROR = 40000    # 参数校验失败
    UNAUTHORIZED = 40100   # 未登录 / 缺少 Token
    TOKEN_EXPIRED = 40101  # Token 已过期
    TOKEN_INVALID = 40102  # Token 非法 / 类型不符 / 签名错误
    ACCOUNT_DISABLED = 40103  # 账号被禁用
    FORBIDDEN = 40300      # 无权限
    BANNED = 403           # 小黑屋禁赛中（按产品规则使用 403，配合 msg 字段返回）
    NOT_FOUND = 40400      # 资源不存在
    CONFLICT = 40900       # 状态冲突（重复报名、重复签到等）
    AI_DEGRADED = 50010    # AI 服务降级（已返回本地规则版结果）
    SERVER_ERROR = 50000   # 服务器内部错误


# 小黑屋拦截文案模板（产品指定）：{end} = 解禁时间
BAN_MESSAGE_TEMPLATE = "您因放鸽子被禁赛，将于 {end} 解除"
# 非缺席原因封禁（如信誉分过低、管理员封禁）使用的文案
BAN_MESSAGE_GENERIC_TEMPLATE = "您已被禁赛，将于 {end} 解除"


class ApiResponse(BaseModel, Generic[T]):
    """
    统一响应模型
    示例：{"code": 0, "message": "ok", "data": {...}}
    """

    code: int = Field(default=RespCode.SUCCESS, description="业务状态码，0 表示成功")
    message: str = Field(default="ok", description="提示信息")
    data: T | None = Field(default=None, description="业务数据")

    @classmethod
    def ok(cls, data: Any = None, message: str = "ok") -> "ApiResponse":
        """成功响应"""
        return cls(code=RespCode.SUCCESS, message=message, data=data)

    @classmethod
    def fail(cls, code: int, message: str, data: Any = None) -> "ApiResponse":
        """失败响应（一般不直接调用，交给全局异常处理器）"""
        return cls(code=code, message=message, data=data)


# ------------------------------------------------------------------
# 便捷函数：在返回值类型标注较麻烦的接口里直接使用
# ------------------------------------------------------------------
def success(data: Any = None, message: str = "ok") -> dict:
    """成功响应字典"""
    return {"code": RespCode.SUCCESS, "message": message, "data": data}


def fail(code: int = RespCode.SERVER_ERROR, message: str = "error", data: Any = None) -> dict:
    """失败响应字典"""
    return {"code": code, "message": message, "data": data}


def banned_body(message: str, data: Any = None) -> dict:
    """
    小黑屋拦截响应体（按产品规则给出 code=403 与 msg 字段）。

    同时保留平台统一的 message 字段，避免既有前端解析逻辑失效：
        {"code": 403, "msg": "...", "message": "...", "data": {...}}
    """
    return {
        "code": int(RespCode.BANNED),
        "msg": message,
        "message": message,
        "data": data,
    }


def build_ban_message(end_time, reason_type=None, template: str | None = None) -> str:
    """
    生成封禁提示文案。
        缺席类封禁 → 「您因放鸽子被禁赛，将于 2026-11-21 20:00 解除」（产品指定文案）
        其它原因   → 「您已被禁赛，将于 ... 解除」
    """
    from app.core.constants import BanReasonType  # 局部导入，避免 constants <-> response 循环引用

    end_text = end_time.strftime("%Y-%m-%d %H:%M") if end_time else "未知"
    if template:
        return template.format(end=end_text)
    if reason_type == BanReasonType.ABSENT:
        return BAN_MESSAGE_TEMPLATE.format(end=end_text)
    return BAN_MESSAGE_GENERIC_TEMPLATE.format(end=end_text)
