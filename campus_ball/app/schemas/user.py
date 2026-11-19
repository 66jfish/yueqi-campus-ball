"""用户相关出入参模型"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    """用户详情（对外输出，绝不包含 password_hash）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    student_no: str = Field(..., description="学号")
    nickname: str = Field(..., description="昵称")
    avatar_url: str | None = Field(None, description="头像URL")
    campus: str | None = Field(None, description="校区")
    college: str | None = Field(None, description="学院")
    grade: str | None = Field(None, description="年级")
    gender: int = Field(0, description="性别：0-未知 1-男 2-女")
    skill_level: int = Field(1, description="球技水平：1-新手 ... 5-大神")

    # 信誉体系（惰性结算结果）
    reputation_score: int = Field(100, description="信誉分（口径：正常签到+2、迟到-3、缺席-10）")
    credit_score: int = Field(100, description="信誉分兼容字段（与 reputation_score 同值，老前端可继续使用）")
    credit_level: int = Field(3, description="信誉等级：1-黑名单 2-观察 3-正常 4-优秀 5-金牌")
    credit_settled_at: datetime | None = Field(None, description="最近一次结算时间")
    total_game_count: int = Field(0, description="累计参与球局数")
    absent_count: int = Field(0, description="累计缺席次数")

    ai_profile: dict[str, Any] | None = Field(None, description="AI信誉画像（缓存结果，含画像分/标签/加权明细）")
    ai_score: int | None = Field(None, description="AI 画像评估分（0-150，个人主页展示）")
    ai_profile_source: str | None = Field(None, description="画像来源：deepseek / rule（本地加权规则降级）")
    ai_profile_dirty: int = Field(0, description="待重算标记：1=签到/缺席/退出后待重算")
    ai_profile_updated_at: datetime | None = Field(None, description="AI画像更新时间")

    status: int = Field(1, description="账号状态：0-禁用 1-正常")
    last_login_at: datetime | None = Field(None, description="最近登录时间")
    created_at: datetime | None = Field(None, description="注册时间")


class UserProfilePageOut(BaseModel):
    """
    用户个人主页（信誉分与画像展示）
    对外只暴露展示必需字段：不含手机号、邮箱、学号等隐私信息。
    """

    user_id: int = Field(..., description="用户ID")
    nickname: str = Field(..., description="昵称")
    avatar_url: str | None = Field(None, description="头像")
    campus: str | None = Field(None, description="校区")
    college: str | None = Field(None, description="学院")
    gender: int = Field(0, description="性别：0-未知 1-男 2-女")
    skill_level: int = Field(1, description="球技水平：1-新手 … 5-大神")

    # ---- 信誉分（个人主页核心展示） ----
    reputation_score: int = Field(..., description="★信誉分（操作分，惰性结算维护，用于报名门槛）")
    credit_score: int = Field(..., description="信誉分兼容字段（与 reputation_score 同值）")
    credit_level: int = Field(..., description="信誉等级：1-黑名单 2-观察 3-正常 4-优秀 5-金牌")
    credit_level_text: str = Field(..., description="信誉等级文案")

    # ---- AI 画像 ----
    profile_score: int | None = Field(None, description="AI 画像评估分（0-150）")
    tags: list[str] = Field(default_factory=list, description="信誉标签")
    summary: str | None = Field(None, description="画像总结")
    profile_source: str | None = Field(None, description="画像来源：deepseek / rule")
    profile_degraded: bool = Field(True, description="是否本地加权规则版（未使用大模型）")
    breakdown: list[dict] = Field(default_factory=list, description="画像加权明细（分数怎么来的）")

    # ---- 常打项目 & 最近自评水平 ----
    favorite_sports: list[dict] = Field(
        default_factory=list, description="常打项目（按参与次数倒序）：[{sport_type, name, count, ratio}]"
    )
    latest_skill_level: int | None = Field(None, description="最近一次报名自评的水平（该球类）")
    latest_skill_level_text: str | None = Field(None, description="最近自评水平文案")
    latest_skill_sport: str | None = Field(None, description="最近自评水平对应的球类")

    # ---- 行为统计 ----
    attended_count: int = Field(0, description="累计到场（正常签到）次数")
    late_count: int = Field(0, description="累计迟到次数")
    absent_count: int = Field(0, description="累计缺席次数")
    cancel_count: int = Field(0, description="累计主动退出次数")
    keep_rate: float = Field(1.0, description="守约率（按时到场 / 应到场）")
    joined_game_count: int = Field(0, description="累计参与球局场次")
    created_game_count: int = Field(0, description="累计发起球局场次")

    # ---- 小黑屋状态（本人可见全量，他人仅看是否在封禁中） ----
    banned: bool = Field(False, description="当前是否处于禁赛期")
    ban_end_time: datetime | None = Field(None, description="解禁时间（仅本人可见具体时间）")

    registered_at: datetime | None = Field(None, description="注册时间")
    is_self: bool = Field(False, description="是否查看的是自己的主页")


class UserBrief(BaseModel):
    """用户简要信息（球局列表里展示组织者/参与者）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    avatar_url: str | None = None
    reputation_score: int = 100
    credit_score: int = 100  # 兼容字段
    skill_level: int = 1


class CreditStatusOut(BaseModel):
    """用户信誉状态（惰性结算视角）"""

    reputation_score: int = Field(..., description="当前信誉分（直接读库，不做实时计算）")
    credit_score: int = Field(..., description="信誉分兼容字段（与 reputation_score 同值）")
    credit_level: int = Field(..., description="信誉等级")
    pending_settle_count: int = Field(0, description="还有多少条记录待结算")
    banned: bool = Field(False, description="是否处于禁赛期（惰性判定：ban_end_time > now）")
    ban_end_time: datetime | None = Field(None, description="解禁时间")
    ban_extend_count: int = Field(0, description="封禁顺延次数（连续缺席时累加）")
    credit_settled_at: datetime | None = Field(None, description="最近结算时间")


class CreditHistoryItem(BaseModel):
    """信誉分流水项（来自已结算的签到记录）"""

    checkin_record_id: int
    game_id: int
    checkin_status: int = Field(..., description="1-正常签到 2-迟到 3-缺席 4-已请假")
    credit_delta: int = Field(..., description="本次分值变动，如 +2 / -10")
    settled_at: datetime | None = Field(None, description="结算时间")


class UpdateUserRequest(BaseModel):
    """更新个人资料（可扩展）"""

    nickname: str | None = Field(None, min_length=1, max_length=32)
    avatar_url: str | None = Field(None, max_length=255)
    campus: str | None = Field(None, max_length=64)
    college: str | None = Field(None, max_length=64)
    grade: str | None = Field(None, max_length=16)
    skill_level: int | None = Field(None, ge=1, le=5)
