"""
认证接口：注册 / 登录 / 刷新令牌 / 登出 / 令牌信息
====================================================================
路径前缀：/api/v1/auth
统一响应：{"code": 0, "message": "ok", "data": {...}}
错误码：40000 参数错误 / 40100 未登录 / 40101 令牌过期 / 40102 令牌非法
        / 40103 账号禁用 / 403 禁赛中（小黑屋，配合 msg 字段）/ 40900 学号已注册

详细文档（含请求参数表与返回示例）：docs/API_AUTH.md
====================================================================
"""

from fastapi import APIRouter, Request

from app.api.deps import CurrentUser, DbSession, OptionalUser
from app.core.config import settings
from app.core.response import ApiResponse
from app.core.security import decode_token, get_token_remaining_seconds
from app.schemas import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RegisterRequest,
    TokenInfoOut,
    TokenResponse,
    UserInfoOut,
)
from app.services import auth as auth_service
from app.services.auth import TOKEN_REFRESH_THRESHOLD_SECONDS

router = APIRouter(prefix="/auth", tags=["认证"])


# ==================================================================
# 注册
# ==================================================================
@router.post(
    "/register",
    response_model=ApiResponse[UserInfoOut],
    summary="用户注册",
    description="学号唯一；密码使用 bcrypt 加密存储（$2b$12$...），明文不落库；注册即初始化信誉分。",
    responses={
        200: {
            "description": "注册成功",
            "content": {
                "application/json": {
                    "example": {
                        "code": 0,
                        "message": "注册成功",
                        "data": {
                            "id": 1,
                            "student_no": "20230001",
                            "nickname": "球场小王子",
                            "avatar_url": None,
                            "campus": "老校区",
                            "college": "计算机学院",
                            "gender": 1,
                            "skill_level": 3,
                            "credit_score": 100,
                            "credit_level": 3,
                            "created_at": "2026-11-18T10:00:00",
                        },
                    }
                }
            },
        },
        409: {
            "description": "学号或手机号已注册",
            "content": {
                "application/json": {
                    "example": {"code": 40900, "message": "该学号或手机号已注册", "data": None}
                }
            },
        },
    },
)
async def register(payload: RegisterRequest, db: DbSession):
    """注册成功后不直接发令牌，前端跳登录（也可按需改为自动登录）"""
    user = await auth_service.register(db, payload)
    return ApiResponse.ok(UserInfoOut.model_validate(user), message="注册成功")


# ==================================================================
# 登录
# ==================================================================
@router.post(
    "/login",
    response_model=ApiResponse[LoginResponse],
    summary="用户登录（JWT 签发）",
    description=(
        "支持学号或手机号登录，返回 access_token（7 天）与 refresh_token（30 天）。\n\n"
        "后续请求在请求头携带：`Authorization: Bearer <access_token>`。\n"
        "若数据库中是历史 PBKDF2 哈希，登录成功后会自动升级为 bcrypt（用户无感）。"
    ),
    responses={
        200: {
            "description": "登录成功",
            "content": {
                "application/json": {
                    "example": {
                        "code": 0,
                        "message": "登录成功",
                        "data": {
                            "token": {
                                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.xxx",
                                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.yyy",
                                "token_type": "bearer",
                                "expires_in": 604800,
                            },
                            "user": {
                                "id": 1,
                                "student_no": "20230001",
                                "nickname": "球场小王子",
                                "credit_score": 100,
                                "credit_level": 3,
                            },
                        },
                    }
                }
            },
        },
        400: {
            "description": "账号或密码错误",
            "content": {
                "application/json": {
                    "example": {"code": 40000, "message": "账号或密码错误", "data": None}
                }
            },
        },
    },
)
async def login(payload: LoginRequest, db: DbSession):
    """登录：校验 bcrypt 密码 → 签发双令牌 → 更新最近登录时间"""
    result = await auth_service.login(db, payload.account, payload.password)
    data = LoginResponse(
        token=TokenResponse(**result.token),
        user=UserInfoOut.model_validate(result.user),
    )
    message = "登录成功" if not result.password_upgraded else "登录成功（密码哈希已升级）"
    return ApiResponse.ok(data, message=message)


# ==================================================================
# 刷新令牌
# ==================================================================
@router.post(
    "/refresh",
    response_model=ApiResponse[TokenResponse],
    summary="刷新访问令牌",
    description="用 refresh_token 换取新的令牌对（refresh_token 同时轮换）。令牌过期后前端应先走此接口，失败再跳登录页。",
    responses={
        401: {
            "description": "刷新令牌过期或非法",
            "content": {
                "application/json": {
                    "example": {"code": 40101, "message": "登录已过期，请重新登录", "data": None}
                }
            },
        }
    },
)
async def refresh_token(payload: RefreshRequest, db: DbSession):
    result = await auth_service.refresh(db, payload.refresh_token)
    return ApiResponse.ok(TokenResponse(**result.token), message="刷新成功")


# ==================================================================
# 登出
# ==================================================================
@router.post(
    "/logout",
    response_model=ApiResponse[dict],
    summary="退出登录",
    description=(
        "当前为无状态实现：客户端丢弃本地令牌即可。\n"
        "接口已记录 jti 与剩余有效期，后续接入 Redis 后可在此把 jti 写入黑名单，实现立即失效与强制下线。"
    ),
)
async def logout(request: Request, current_user: OptionalUser):
    """登出：登录状态下记录 jti；未登录调用也返回成功（幂等）"""
    payload = getattr(request.state, "token_payload", None) or {}
    await auth_service.logout(
        user_id=current_user.id if current_user else None,
        jti=payload.get("jti"),
        exp=payload.get("exp"),
    )
    return ApiResponse.ok(
        {
            "logout": True,
            "user_id": current_user.id if current_user else None,
            "note": "请前端清除本地保存的 access_token / refresh_token",
        },
        message="已退出登录",
    )


# ==================================================================
# 令牌信息（前端据此决定是否静默续期）
# ==================================================================
@router.get(
    "/token-info",
    response_model=ApiResponse[TokenInfoOut],
    summary="查看当前令牌信息",
    description="返回令牌剩余有效秒数；need_refresh=true 时建议前端调用 /auth/refresh 静默续期。",
)
async def token_info(request: Request, current_user: CurrentUser):
    """查看当前令牌状态（需登录）"""
    payload = getattr(request.state, "token_payload", None)

    if not payload:
        # 中间件未解析（如直接单测调用）时兜底：从请求头自行解析
        auth_header = request.headers.get(settings.AUTH_HEADER_NAME, "")
        token = auth_header[len(settings.AUTH_TOKEN_PREFIX) + 1 :].strip() if auth_header else ""
        payload = decode_token(token) if token else {}

    remaining = get_token_remaining_seconds(payload)
    return ApiResponse.ok(
        TokenInfoOut(
            user_id=str(current_user.id),
            jti=payload.get("jti"),
            type=payload.get("type", "access"),
            expires_in=remaining,
            expires_at=auth_service.describe_token(payload).get("expires_at"),
            need_refresh=remaining < TOKEN_REFRESH_THRESHOLD_SECONDS,
        )
    )
