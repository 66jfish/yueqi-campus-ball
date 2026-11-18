"""
球局 / 报名 出入参模型
====================================================================
GameOut 在球局表字段之外，额外带上前端列表/详情页需要的聚合信息：
    creator_nickname / waitlist_count / slots_left / my_registration_status / my_checkin_status
====================================================================
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.constants import MATCH_SCORE_PLACEHOLDER


class GameCreateRequest(BaseModel):
    """发起球局请求"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "sport_type": 1,
                    "title": "周五晚东区篮球局",
                    "description": "水平不限，重在参与，请自备球鞋",
                    "campus": "东校区",
                    "venue_name": "东区体育馆3号场",
                    "venue_address": "东区体育馆一楼",
                    "start_time": "2026-11-20T19:00:00",
                    "end_time": "2026-11-20T21:00:00",
                    "signup_deadline": "2026-11-20T17:00:00",
                    "max_players": 10,
                    "min_players": 4,
                    "fee_type": 0,
                    "skill_level_limit": 0,
                    "gender_limit": 0,
                    "min_credit_score": 0,
                }
            ]
        }
    )

    sport_type: int = Field(1, ge=1, le=6, description="运动类型：1-篮球 2-足球 3-羽毛球 4-网球 5-排球 6-乒乓球")
    title: str = Field(..., min_length=2, max_length=64, description="球局标题", examples=["周五晚东区篮球局"])
    description: str | None = Field(None, max_length=500, description="球局描述（水平要求、装备要求等）")

    campus: str | None = Field(None, max_length=64, description="校区（与场地名一起用于同场地冲突校验）")
    venue_name: str | None = Field(None, max_length=64, description="场地名称（必填才做同时段冲突校验）")
    venue_address: str | None = Field(None, max_length=128, description="详细地址")

    start_time: datetime = Field(..., description="开球时间")
    end_time: datetime = Field(..., description="结束时间（必须晚于开球时间）")
    signup_deadline: datetime | None = Field(None, description="报名截止时间，不填则不限制")
    checkin_start_time: datetime | None = Field(None, description="核销开放时间，不填默认开球前30分钟")
    checkin_end_time: datetime | None = Field(None, description="核销截止时间，不填默认开球后15分钟（超过记迟到）")

    max_players: int = Field(10, ge=2, le=50, description="最大人数（含发起人）")
    min_players: int = Field(2, ge=2, le=50, description="最少成局人数")

    fee_type: int = Field(0, ge=0, le=1, description="费用类型：0-免费 1-AA制")
    fee_amount: Decimal | None = Field(None, ge=0, description="人均费用（元），fee_type=1 时有效")
    skill_level_limit: int = Field(0, ge=0, le=5, description="最低球技要求：0-不限")
    gender_limit: int = Field(0, ge=0, le=2, description="性别限制：0-不限 1-仅男生 2-仅女生")
    min_credit_score: int = Field(0, ge=0, description="报名最低信誉分：0-不限")

    @model_validator(mode="after")
    def check_time_range(self) -> "GameCreateRequest":
        """时间合法性：结束晚于开始；核销窗口在合理范围内"""
        if self.end_time <= self.start_time:
            raise ValueError("结束时间必须晚于开球时间")
        if self.signup_deadline and self.signup_deadline > self.start_time:
            raise ValueError("报名截止时间不能晚于开球时间")
        if self.checkin_start_time and self.checkin_start_time > self.start_time:
            raise ValueError("核销开放时间不能晚于开球时间")
        if self.max_players < self.min_players:
            raise ValueError("最大人数不能小于最少成局人数")
        return self


class GameOut(BaseModel):
    """球局信息（列表/详情通用）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    creator_id: int = Field(..., description="发起人用户ID")
    sport_type: int = Field(..., description="运动类型：1-篮球 2-足球 3-羽毛球 4-网球 5-排球 6-乒乓球")
    title: str = Field(..., description="球局标题")
    description: str | None = Field(None, description="球局描述")
    campus: str | None = Field(None, description="校区")
    venue_name: str | None = Field(None, description="场地名称")
    venue_address: str | None = Field(None, description="详细地址")
    start_time: datetime = Field(..., description="开球时间")
    end_time: datetime = Field(..., description="结束时间")
    signup_deadline: datetime | None = Field(None, description="报名截止时间")
    checkin_start_time: datetime | None = Field(None, description="核销开放时间")
    checkin_end_time: datetime | None = Field(None, description="核销截止时间（超过记迟到）")
    max_players: int = Field(..., description="最大人数")
    min_players: int = Field(..., description="最少成局人数")
    current_players: int = Field(..., description="当前正式报名人数")
    fee_type: int = Field(0, description="费用类型：0-免费 1-AA制")
    fee_amount: Decimal | None = Field(None, description="人均费用（元）")
    skill_level_limit: int = Field(0, description="最低球技要求：0-不限")
    gender_limit: int = Field(0, description="性别限制：0-不限 1-仅男生 2-仅女生")
    min_credit_score: int = Field(0, description="报名最低信誉分：0-不限")
    status: int = Field(..., description="球局状态：0-草稿 1-报名中 2-报名截止 3-进行中 4-已结束 5-已取消")
    settle_status: int = Field(0, description="结算状态：0-待结算 1-已结算 2-部分结算")
    created_at: datetime | None = Field(None, description="创建时间")

    # ---- 聚合字段（由服务层补全，不属于球局表） ----
    creator_nickname: str | None = Field(None, description="发起人昵称")
    creator_credit_score: int | None = Field(None, description="发起人信誉分")
    waitlist_count: int = Field(0, description="候补人数")
    slots_left: int = Field(0, description="剩余名额（max_players - current_players，最小为0）")
    is_full: bool = Field(False, description="是否已满员")
    match_score: float = Field(
        MATCH_SCORE_PLACEHOLDER,
        description=(
            "AI 匹配分（0-100）。登录后按用户画像实时计算（信誉分 + 球技 + 球类偏好 + 满员/时间冲突惩罚）；"
            "未登录返回静态基线分 80.0"
        ),
    )
    match_reason: str | None = Field(None, description="匹配分说明（如：信誉分 102、球技符合要求）")
    my_registration_status: int | None = Field(
        None, description="当前用户报名状态：1-已报名 2-已取消 3-候补中 4-被移出；未报名为 null"
    )
    my_checkin_status: int | None = Field(
        None, description="当前用户签到状态：0-未签到 1-正常签到 2-迟到 3-缺席 4-已请假；无记录为 null"
    )


class GameListItem(GameOut):
    """球局列表项（与 GameOut 一致，预留扩展）"""


class GameDetailOut(GameOut):
    """球局详情（额外带核销统计）"""

    checked_count: int = Field(0, description="已到场人数（正常签到+迟到）")
    late_count: int = Field(0, description="迟到人数")
    absent_count: int = Field(0, description="缺席人数")
    not_checked_count: int = Field(0, description="尚未核销人数")
    is_creator: bool = Field(False, description="当前用户是否为本场发起人")


class GamePageOut(BaseModel):
    """
    球局分页结果。

    注意：字段名用 items 而不是 list —— 在类体内定义名为 list 的字段会遮蔽内置 list，
    导致后续 `list[Xxx]` 注解求值失败（FieldInfo object is not subscriptable）。
    对外 JSON 仍保持 "list" 键（alias），与既有前端契约一致。
    """

    model_config = ConfigDict(populate_by_name=True)

    items: list[GameListItem] = Field(
        default_factory=list,
        alias="list",
        description="当前页数据",
    )
    total: int = Field(0, description="总条数")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(10, description="每页条数")
    pages: int = Field(0, description="总页数")


class RegistrationOut(BaseModel):
    """报名记录输出"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    user_id: int
    status: int = Field(1, description="1-已报名 2-已取消 3-候补中 4-被移出")
    is_waitlist: int = Field(0, description="0-正式名额 1-候补")
    waitlist_order: int = Field(0, description="候补顺序号")
    signup_time: datetime | None = None
    credit_snapshot: int | None = None


class SignupResult(BaseModel):
    """报名结果"""

    registration: RegistrationOut
    is_waitlist: bool = Field(False, description="是否进入候补队列")
    current_players: int = Field(0, description="当前正式报名人数")
    message: str = Field("报名成功", description="提示信息，可直接展示")


class ExitGameResult(BaseModel):
    """退出球局结果"""

    registration: RegistrationOut
    promoted_user_id: int | None = Field(None, description="被候补补位上来的用户ID（无候补为 null）")
    current_players: int = Field(0, description="退出后当前正式人数")
    message: str = Field("已退出球局", description="提示信息")


class RosterMemberOut(BaseModel):
    """报名名单成员"""

    user_id: int
    nickname: str | None = None
    avatar_url: str | None = None
    status: int = Field(..., description="报名状态：1-已报名 3-候补中")
    is_waitlist: int = 0
    waitlist_order: int = 0
    signup_time: datetime | None = None
    credit_score: int | None = None
