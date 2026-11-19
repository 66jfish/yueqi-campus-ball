"""
认证模块出入参模型
====================================================================
所有模型都带 json_schema_extra 示例，直接体现在 /docs 的「Example Value」区域，
前端对接时可一键试跑。
====================================================================
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    """注册请求"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "student_no": "20230001",
                    "nickname": "球场小王子",
                    "password": "abc123456",
                    "real_name": "张三",
                    "phone": "13800000001",
                    "campus": "老校区",
                    "college": "计算机学院",
                    "grade": "2023",
                    "gender": 1,
                    "skill_level": 3,
                }
            ]
        }
    )

    student_no: str = Field(..., min_length=3, max_length=32, description="学号，校内唯一", examples=["20230001"])
    nickname: str = Field(..., min_length=1, max_length=32, description="昵称", examples=["球场小王子"])
    password: str = Field(..., min_length=6, max_length=64, description="密码，6-64 位（bcrypt 加密存储）", examples=["abc123456"])
    real_name: str | None = Field(None, max_length=32, description="真实姓名（可选）")
    phone: str | None = Field(None, max_length=20, description="手机号（可选，可与学号一起作为登录账号）")
    campus: str | None = Field(None, max_length=64, description="校区")
    college: str | None = Field(None, max_length=64, description="学院")
    grade: str | None = Field(None, max_length=16, description="年级")
    gender: int = Field(0, ge=0, le=2, description="性别：0-未知 1-男 2-女")
    # 注：球技水平不在注册时采集，改为「报名某球局时按该球类自评」（见 SignupRequest）


class LoginRequest(BaseModel):
    """登录请求（学号或手机号均可）"""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"account": "20230001", "password": "abc123456"}]}
    )

    account: str = Field(..., min_length=3, max_length=64, description="学号或手机号", examples=["20230001"])
    password: str = Field(..., min_length=6, max_length=64, description="密码", examples=["abc123456"])


class RefreshRequest(BaseModel):
    """刷新令牌请求"""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."}]}
    )

    refresh_token: str = Field(..., description="登录时返回的 refresh_token")


class TokenResponse(BaseModel):
    """令牌对（access + refresh）"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.xxx",
                    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.yyy",
                    "token_type": "bearer",
                    "expires_in": 604800,
                }
            ]
        }
    )

    access_token: str = Field(..., description="访问令牌，放入请求头 Authorization: Bearer <token>")
    refresh_token: str = Field(..., description="刷新令牌，仅用于 /auth/refresh 换取新令牌")
    token_type: str = Field("bearer", description="令牌类型，固定 bearer")
    expires_in: int = Field(..., description="访问令牌有效期（秒），默认 604800（7 天）")


class UserInfoOut(BaseModel):
    """登录/注册返回的用户概要（不含任何敏感字段）"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="用户ID")
    student_no: str = Field(..., description="学号")
    nickname: str = Field(..., description="昵称")
    avatar_url: str | None = Field(None, description="头像URL")
    campus: str | None = Field(None, description="校区")
    college: str | None = Field(None, description="学院")
    gender: int = Field(0, description="性别：0-未知 1-男 2-女")
    skill_level: int = Field(1, description="球技水平：1-新手 ... 5-大神")
    credit_score: int = Field(100, description="信誉分")
    credit_level: int = Field(3, description="信誉等级：1-黑名单 2-观察 3-正常 4-优秀 5-金牌")
    created_at: datetime | None = Field(None, description="注册时间")


class LoginResponse(BaseModel):
    """登录响应体"""

    token: TokenResponse = Field(..., description="令牌对")
    user: UserInfoOut = Field(..., description="用户概要信息")


class TokenInfoOut(BaseModel):
    """当前令牌信息（前端用于判断是否该续期）"""

    user_id: str = Field(..., description="令牌所属用户ID")
    jti: str | None = Field(None, description="令牌唯一ID（后续可据此强制下线）")
    type: str = Field("access", description="令牌类型：access / refresh")
    expires_in: int = Field(..., description="剩余有效秒数")
    expires_at: str | None = Field(None, description="过期时间（本地时区 ISO 格式）")
    need_refresh: bool = Field(False, description="剩余时间是否已低于续期阈值（30 分钟）")
