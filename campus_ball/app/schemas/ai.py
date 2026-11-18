"""
AI 信誉画像 出入参模型
====================================================================
画像输出包含三类信息：
    1. 分数：score（画像分）、rule_score（本地加权基线）、ai_score（大模型建议分）、
             reputation_score（操作分，惰性结算维护）、score_gap（两者差异）
    2. 标签与文案：tags / risk_level / summary / suggestions
    3. 可解释性：breakdown（每一项行为的次数×权重=小计）、features（行为特征明细）
====================================================================
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AIProfileOut(BaseModel):
    """信誉画像输出"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_id": 2,
                    "score": 82,
                    "rule_score": 82,
                    "ai_score": None,
                    "ai_adjust": 0,
                    "reputation_score": 82,
                    "score_gap": 0,
                    "credit_level": 2,
                    "credit_level_text": "观察中",
                    "risk_level": "medium",
                    "tags": ["有过缺席", "稳定参与"],
                    "summary": "累计到场 3 次、迟到 1 次、缺席 2 次、退出 1 次，守约率 50%",
                    "suggestions": ["报名后请按时到场；确实来不了请提前请假，避免扣除信誉分并被禁赛。"],
                    "source": "rule",
                    "degraded": True,
                    "trigger": "absent",
                    "version": 2,
                    "cached": False,
                    "generated_at": "2026-11-18T19:00:00",
                }
            ]
        }
    )

    user_id: int = Field(..., description="用户ID")
    score: int = Field(..., description="★AI 画像评估分（0-150，融合后的最终分）")
    rule_score: int = Field(..., description="本地加权规则基线分（确定性、可复算）")
    ai_score: int | None = Field(None, description="DeepSeek 建议分；未调用大模型时为 null")
    ai_adjust: int = Field(0, description="AI 相对基线的调整量（已限幅 ±8 分）")
    reputation_score: int = Field(..., description="操作分（惰性结算维护，用于报名门槛/封禁判定）")
    score_gap: int = Field(0, description="画像分 - 操作分，差异过大可用于运营预警")
    credit_level: int = Field(..., description="信誉等级：1-黑名单 2-观察 3-正常 4-优秀 5-金牌")
    credit_level_text: str = Field(..., description="信誉等级文案")
    risk_level: str = Field(..., description="风险等级：low / medium / high")
    tags: list[str] = Field(default_factory=list, description="信誉标签（个人主页展示）")
    summary: str = Field("", description="一句话总结")
    suggestions: list[str] = Field(default_factory=list, description="改进建议")
    source: str = Field("rule", description="画像来源：deepseek（大模型）/ rule（本地加权规则降级）")
    degraded: bool = Field(True, description="是否降级（true=本地加权规则版，未使用大模型）")
    trigger: str | None = Field(None, description="本次重算触发原因：checkin/absent/exit/manual/cache_expired")
    version: int = Field(0, description="画像版本号，每次重算 +1")
    cached: bool = Field(False, description="是否直接返回了库中缓存（未重新计算）")
    generated_at: datetime | None = Field(None, description="画像生成时间")
    features: dict[str, Any] = Field(default_factory=dict, description="行为特征明细（签到/迟到/缺席/退出等）")
    breakdown: list[dict] = Field(default_factory=list, description="本地加权明细：项/次数/权重/小计")


class AIProfileRefreshRequest(BaseModel):
    """强制刷新画像"""

    force: bool = Field(True, description="是否强制重新生成（忽略缓存与 dirty 标记）")


class AIExplainOut(BaseModel):
    """
    算法说明（可直接给前端「分数怎么来的」弹窗使用）
    """

    score_range: list[int] = Field(..., description="画像分区间 [min, max]")
    base_score: int = Field(..., description="初始分（新用户分）")
    weights: dict[str, int] = Field(..., description="本地加权规则权重表")
    weight_desc: dict[str, str] = Field(..., description="权重含义说明")
    formula: str = Field(..., description="画像分计算公式（文字版）")
    keep_rate_bonus: str = Field(..., description="守约加成规则")
    fusion: dict[str, Any] = Field(..., description="DeepSeek 与本地规则的融合参数")
    degrade_policy: str = Field(..., description="降级策略说明")
    trigger_policy: str = Field(..., description="触发时机说明")
    match_score_formula: dict[str, Any] = Field(..., description="球局匹配分构成")
    source_priority: list[str] = Field(..., description="画像来源优先级")
