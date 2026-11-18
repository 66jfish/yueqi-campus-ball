"""
小黑屋 / 封禁相关出入参模型
====================================================================
字段命名与产品规则对齐：
    ban_start_time      封禁开始时间
    ban_duration_days   封禁时长（天，规则2：固定 3 天）
    ban_end_time        解禁时间（= start + 时长；顺延后为新的解禁时间）
    ban_extend_count    顺延次数（规则6：封禁期内再次缺席累加，不新建记录）
    ban_original_end_time 首次解禁时间（顺延前的初始值，永久留痕）
====================================================================
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BanCreateRequest(BaseModel):
    """管理员手动封禁（默认 3 天，可指定时长）"""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"user_id": 3, "days": 3, "reason_type": 4, "reason": "多次放鸽子"}]}
    )

    user_id: int = Field(..., description="被禁赛用户ID")
    days: int | None = Field(None, ge=1, le=365, description="禁赛天数，不填则用系统默认 3 天")
    reason_type: int = Field(
        4, ge=1, le=4, description="原因类型：1-缺席未到 2-多次迟到累计 3-信誉分过低 4-管理员人工封禁"
    )
    reason: str | None = Field(None, max_length=255, description="封禁原因说明")
    trigger_game_id: int | None = Field(None, description="关联球局ID（可空）")
    force_new: bool = Field(
        False, description="用户已在封禁中时：false=顺延原记录（默认，规则6），true=强制新建一条记录"
    )


class BanReleaseRequest(BaseModel):
    """解封请求"""

    ban_id: int = Field(..., description="小黑屋记录ID")
    release_type: int = Field(2, ge=1, le=3, description="解封方式：1-自动 2-人工 3-申诉")
    remark: str | None = Field(None, max_length=255, description="解封说明")


class BlacklistOut(BaseModel):
    """小黑屋记录（永久留存，含 reason，可作为信誉画像扣分依据）"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="封禁记录ID")
    user_id: int = Field(..., description="被禁赛用户ID")
    ban_start_time: datetime = Field(..., description="封禁开始时间")
    ban_duration_days: int = Field(..., description="封禁时长（天），规则2 固定 3 天")
    ban_end_time: datetime = Field(..., description="解禁时间（= 开始时间 + 时长；顺延后为新的解禁时间）")
    status: int = Field(..., description="0-已解封 1-封禁中（仅留痕，拦截以 ban_end_time 惰性判定）")
    reason_type: int = Field(..., description="1-缺席未到 2-多次迟到累计 3-信誉分过低 4-管理员人工封禁")
    reason: str | None = Field(None, description="封禁原因（永久留存，供信誉画像与申诉使用）")
    trigger_game_id: int | None = Field(None, description="触发封禁的球局ID")
    credit_score_at_ban: int | None = Field(None, description="封禁时的信誉分快照")
    released_at: datetime | None = Field(None, description="实际解封时间")
    release_type: int | None = Field(None, description="解封方式：1-到期自动 2-人工 3-申诉")
    ban_extend_count: int = Field(0, description="顺延次数（封禁期内再次缺席累加）")
    ban_original_end_time: datetime | None = Field(None, description="首次解禁时间（顺延前，留痕）")
    ban_last_extend_at: datetime | None = Field(None, description="最近一次顺延时间")
    is_active: bool = Field(
        False, description="当前是否仍生效（惰性判定：ban_end_time > now；无需定时任务）"
    )
    operator_id: int | None = Field(None, description="操作人ID（系统自动封禁为 0）")
    remark: str | None = Field(None, description="备注")
    created_at: datetime | None = Field(None, description="创建时间")


class MyBanStatusOut(BaseModel):
    """当前用户自己的封禁状态（白名单接口，被封禁也能查）"""

    banned: bool = Field(False, description="是否处于禁赛期")
    ban_end_time: datetime | None = Field(None, description="解禁时间")
    remaining_hours: float | None = Field(None, description="剩余小时数（前端可做倒计时）")
    ban_start_time: datetime | None = Field(None, description="封禁开始时间")
    ban_duration_days: int | None = Field(None, description="封禁时长（天）")
    ban_extend_count: int = Field(0, description="顺延次数（连续缺席时累加）")
    reason: str | None = Field(None, description="封禁原因")
    reason_type: int | None = Field(None, description="原因类型：1-缺席 2-迟到累计 3-信誉分过低 4-人工")
    blocked_actions: list[str] = Field(
        default_factory=list, description="封禁期间被禁止的动作说明（发局/报名），其余接口可正常使用"
    )
    message: str | None = Field(None, description="可直接展示的提示文案")
    history: list[BlacklistOut] = Field(default_factory=list, description="历史封禁记录（永久留存）")
    total_ban_count: int = Field(0, description="累计封禁次数（AI 信誉画像输入特征）")


class BanRecordPageOut(BaseModel):
    """封禁记录分页查询结果"""

    items: list[BlacklistOut] = Field(default_factory=list, description="封禁记录列表")
    total: int = Field(0, description="总条数（含已解封的历史记录）")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(20, description="每页条数")
    pages: int = Field(0, description="总页数")


class AbsentScanResultOut(BaseModel):
    """缺席兜底扫描结果"""

    scanned: int = Field(0, description="本轮扫描到的过期球局数")
    absent_total: int = Field(0, description="判定缺席总人次（每人 -10 分并封禁 3 天）")
    finalized: list[dict] = Field(default_factory=list, description="已结束并完成判定的球局明细")
