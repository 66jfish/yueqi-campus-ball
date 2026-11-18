"""签到 / 缺席判定相关出入参模型"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CheckinRequest(BaseModel):
    """签到请求"""

    game_id: int = Field(..., description="球局ID")
    checkin_type: int = Field(1, ge=1, le=3, description="签到方式：1-扫码 2-定位打卡 3-人工补签")
    location_lat: float | None = Field(None, ge=-90, le=90, description="纬度（定位打卡时必填）")
    location_lng: float | None = Field(None, ge=-180, le=180, description="经度（定位打卡时必填）")
    remark: str | None = Field(None, max_length=255, description="备注")


class LeaveRequest(BaseModel):
    """请假请求（请假不扣分，但会写入签到记录，避免被判缺席）"""

    game_id: int = Field(..., description="球局ID")
    remark: str | None = Field(None, max_length=255, description="请假原因")


class CheckinSettleOut(BaseModel):
    """
    签到/缺席判定的返回：包含本次惰性结算结果。
    前端可直接用 credit_delta 弹「信誉分 +2」的提示，用 banned 提示进入小黑屋。
    """

    success: bool = True
    message: str = "操作成功"
    user_id: int | None = None
    credit_before: int | None = Field(None, description="变动前信誉分")
    credit_delta: int | None = Field(None, description="本次变动值（惰性结算得出）")
    credit_after: int | None = Field(None, description="变动后信誉分")
    credit_level: int | None = Field(None, description="变动后信誉等级")
    settled_record_count: int = Field(0, description="本次结算的记录条数")
    banned: bool = Field(False, description="本次结算后是否被关进小黑屋")
    ban_end_time: datetime | None = Field(None, description="解封时间")


class AbsentJudgementRequest(BaseModel):
    """缺席判定请求（球局结束后由组织者触发，或由定时任务自动触发）"""

    game_id: int = Field(..., description="球局ID")
    auto_prune: bool = Field(True, description="是否自动把「未签到且未请假」的报名者判为缺席")


class AbsentJudgementOut(BaseModel):
    """缺席判定结果"""

    game_id: int
    absent_count: int = Field(0, description="本次判定为缺席的人数")
    settled_users: list[dict] = Field(default_factory=list, description="被结算的用户及其信誉分变动")
    message: str = "判定完成"


class CheckinRecordOut(BaseModel):
    """签到记录输出"""

    id: int
    game_id: int
    user_id: int
    checkin_status: int = Field(..., description="0-未签到 1-正常签到 2-迟到 3-缺席 4-已请假")
    checkin_type: int | None = None
    checkin_time: datetime | None = None
    credit_delta: int = Field(0, description="本次记录折算的信誉分变动")
    settled: int = Field(0, description="0-待结算 1-已结算")
    settled_at: datetime | None = None


# ==================================================================
# 发起人核销签到
# ==================================================================
class VerifyCheckinRequest(BaseModel):
    """
    发起人核销请求（给到场用户签到）。
    user_ids 与 verify_all 二选一：
        - user_ids：核销指定用户
        - verify_all=true：一键核销该球局所有「已报名但未核销」的用户
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"game_id": 101, "user_ids": [2, 3], "remark": "现场核销"},
                {"game_id": 101, "verify_all": True},
            ]
        }
    )

    game_id: int = Field(..., description="球局ID")
    user_ids: list[int] | None = Field(None, description="要核销的用户ID列表（与 verify_all 二选一）")
    verify_all: bool = Field(False, description="是否一键核销全部未核销的报名者")
    as_late: bool | None = Field(
        None, description="显式指定记为迟到：true-迟到(扣3分) false-正常(加2分) null-按核销时间自动判定"
    )
    remark: str | None = Field(None, max_length=255, description="备注（写入签到记录，便于追溯）")

    @model_validator(mode="after")
    def check_target(self) -> "VerifyCheckinRequest":
        if self.verify_all:
            return self
        if not self.user_ids:
            raise ValueError("请传入 user_ids 或设置 verify_all=true")
        if len(set(self.user_ids)) != len(self.user_ids):
            raise ValueError("user_ids 中存在重复用户")
        return self


class VerifyCheckinItemOut(BaseModel):
    """单个用户的核销结果"""

    user_id: int
    nickname: str | None = Field(None, description="昵称")
    ok: bool = Field(False, description="本次是否核销成功")
    skipped: bool = Field(False, description="是否因已核销/已请假被跳过")
    reason: str | None = Field(None, description="失败或跳过的原因，可直接展示")
    checkin_status: int | None = Field(None, description="核销后签到状态：1-正常签到 2-迟到")
    checkin_status_text: str | None = Field(None, description="签到状态文案")
    credit_before: int | None = Field(None, description="结算前信誉分")
    credit_delta: int | None = Field(None, description="本次信誉分变动（惰性结算结果，正常+2/迟到-3）")
    credit_after: int | None = Field(None, description="结算后信誉分")
    banned: bool = Field(False, description="本次结算后是否被关进小黑屋")
    ban_end_time: datetime | None = Field(None, description="解封时间")


class VerifyCheckinResultOut(BaseModel):
    """批量核销结果"""

    game_id: int
    verified_count: int = Field(0, description="核销成功人数")
    skipped_count: int = Field(0, description="跳过人数（已核销/已请假）")
    failed_count: int = Field(0, description="失败人数（未报名此球局等）")
    checkin_open_at: datetime | None = Field(None, description="本次核销开放的起始时间")
    checkin_close_at: datetime | None = Field(None, description="核销截止时间（超过记迟到）")
    items: list[VerifyCheckinItemOut] = Field(default_factory=list, description="逐人结果")


class RosterMemberCheckinOut(BaseModel):
    """核销名单成员"""

    user_id: int
    nickname: str | None = None
    avatar_url: str | None = None
    credit_score: int | None = Field(None, description="信誉分")
    registration_status: int = Field(..., description="报名状态：1-已报名 3-候补中")
    is_waitlist: int = Field(0, description="0-正式 1-候补")
    checkin_status: int | None = Field(None, description="0-未签到 1-正常签到 2-迟到 3-缺席 4-已请假")
    checkin_status_text: str | None = Field(None, description="签到状态文案")
    checkin_time: datetime | None = Field(None, description="核销时间")
    credit_delta: int = Field(0, description="该场信誉分变动")
    settled: int = Field(0, description="0-待结算 1-已结算")


class VerifyRosterOut(BaseModel):
    """核销名单（发起人视图）"""

    game_id: int
    title: str = Field(..., description="球局标题")
    status: int = Field(..., description="球局状态")
    settle_status: int = Field(0, description="结算状态：0-待结算 1-已结算")
    start_time: datetime = Field(..., description="开球时间")
    checkin_open_at: datetime = Field(..., description="核销开放时间")
    checkin_close_at: datetime = Field(..., description="核销截止时间")
    checkin_open: bool = Field(False, description="当前是否在可核销窗口内")
    signed_count: int = Field(0, description="正式报名人数")
    checked_count: int = Field(0, description="正常签到人数")
    late_count: int = Field(0, description="迟到人数")
    absent_count: int = Field(0, description="缺席人数")
    not_checked_count: int = Field(0, description="未核销人数")
    waitlist_count: int = Field(0, description="候补人数")
    members: list[RosterMemberCheckinOut] = Field(default_factory=list, description="成员明细")
