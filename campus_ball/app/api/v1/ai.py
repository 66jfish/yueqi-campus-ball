"""
AI 信誉画像接口
====================================================================
路径前缀：/api/v1/ai

    GET  /profile            获取我的信誉画像（脏标记或缓存过期时当场重算，否则返回缓存）
    GET  /explain            查看画像算法说明（权重表、公式、融合与降级策略）— 前端"分数怎么来的"
    POST /profile/refresh    强制重算（忽略缓存与 dirty 标记）
    POST /refresh-dirty      管理端：批量重算「待重算」用户的画像（后台任务的手动补偿）

设计要点：
    1. 双轨：优先 DeepSeek，无 Key / 调用失败自动降级本地加权规则（Demo 可离线跑通）
    2. 惰性触发：签到 / 缺席 / 退出结算后置 dirty=1，后台任务或本次读取时重算
    3. 画像分（score）与操作分（reputation_score）分列：前者用于展示与匹配参考，
       后者由惰性结算维护，用于报名门槛与封禁判定，避免大模型影响业务规则

详细算法说明见 docs/API_AI_PROFILE.md
====================================================================
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, get_current_admin
from app.core.config import settings
from app.core.constants import (
    AI_SCORE_MAX_ADJUST,
    AI_SCORE_WEIGHT,
    PROFILE_LATE_CANCEL_HOURS,
    PROFILE_SCORE_MAX,
    PROFILE_SCORE_MIN,
    PROFILE_WEIGHTS,
    CheckinStatus,
    RegistrationStatus,
)
from app.core.exceptions import NotFoundException
from app.core.response import ApiResponse
from app.models import CheckinRecord, Game, Registration, User
from app.schemas import AIExplainOut, AIProfileOut, AIProfileRefreshRequest
from app.services import ai_profile as ai_service

router = APIRouter(prefix="/ai", tags=["AI信誉画像"])

WEIGHT_DESC = {
    "checked": "按时签到（到场）：+2/次",
    "late": "迟到签到：-3/次",
    "absent": "无故缺席（未签到未请假）：-10/次（大幅扣分）",
    "leave": "已请假：0（提前告知不惩罚）",
    "cancel_early": "主动退出（距开球 > 阈值）：-2/次（少量扣分）",
    "cancel_late": f"临近开球退出（≤{PROFILE_LATE_CANCEL_HOURS}h）：-4/次",
}


# ==================================================================
# 我的画像
# ==================================================================
@router.get(
    "/profile",
    response_model=ApiResponse[AIProfileOut],
    summary="获取我的信誉画像（标签 + 画像分）",
    description=(
        "**惰性触发**：签到 / 缺席 / 退出结算后画像会被标记为「待重算」，\n"
        "本接口在检测到 `dirty=1` 或缓存超过 `AI_PROFILE_CACHE_HOURS` 时会当场重算并返回最新结果，\n"
        "否则直接返回缓存（响应里的 `cached=true`）。\n\n"
        "**双轨算法**：优先 DeepSeek；没有 API Key 或调用失败时自动降级为本地加权规则版，\n"
        "此时 `source=rule`、`degraded=true`，分数由确定性的权重表算出（见 `/ai/explain`）。\n\n"
        "**两个分数**：`score` 是画像分（0-150，用于展示与球局匹配参考）；\n"
        "`reputation_score` 是操作分（惰性结算维护，用于报名门槛与封禁判定）。"
    ),
)
async def get_my_profile(current_user: CurrentUser, db: DbSession, force: bool = Query(False, description="忽略缓存强制重算")):
    """获取我的信誉画像"""
    profile = await _resolve_profile(db, current_user, force=force)
    return ApiResponse.ok(profile, message="画像已更新" if not profile.cached else "返回缓存画像")


@router.post(
    "/profile/refresh",
    response_model=ApiResponse[AIProfileOut],
    summary="强制刷新我的信誉画像",
)
async def refresh_my_profile(
    current_user: CurrentUser, db: DbSession, payload: AIProfileRefreshRequest | None = None
):
    """忽略缓存与 dirty 标记，重新生成画像"""
    profile = await _resolve_profile(db, current_user, force=True)
    return ApiResponse.ok(profile, message="画像已刷新")


# ==================================================================
# 算法说明
# ==================================================================
@router.get(
    "/explain",
    response_model=ApiResponse[AIExplainOut],
    summary="画像算法说明（权重表 / 公式 / 融合与降级策略）",
    description="返回本地加权规则的完整权重表与公式，前端可直接在「分数怎么来的」弹窗中展示。",
)
async def explain_algorithm(current_user: CurrentUser):
    """画像算法说明（公开可查，便于用户理解扣分规则）"""
    return ApiResponse.ok(
        AIExplainOut(
            score_range=[PROFILE_SCORE_MIN, PROFILE_SCORE_MAX],
            base_score=settings.CREDIT_SCORE_INIT,
            weights=PROFILE_WEIGHTS,
            weight_desc=WEIGHT_DESC,
            formula=(
                "画像分 = clamp(初始分100 "
                "+ 2×按时签到次数 - 3×迟到次数 - 10×无故缺席次数 "
                "- 2×主动退出次数 - 4×临近开球退出次数 + 守约加成, 0, 150)"
            ),
            keep_rate_bonus="完成 ≥5 场且守约率 ≥95% 时额外 +3 分",
            fusion={
                "ai_weight": AI_SCORE_WEIGHT,
                "rule_weight": round(1 - AI_SCORE_WEIGHT, 2),
                "max_adjust": AI_SCORE_MAX_ADJUST,
                "description": (
                    "有 DeepSeek 时：最终分 = 0.3×AI建议分 + 0.7×本地加权分，"
                    f"且相对本地基线最多调整 ±{AI_SCORE_MAX_ADJUST} 分（防模型幻觉导致分数跳变）"
                ),
            },
            degrade_policy=(
                "未配置 DEEPSEEK_API_KEY、AI_ENABLED=false 或调用异常（超时/限流/返回非法）时，"
                "自动使用本地加权规则版，接口不报错，Demo 可离线运行"
            ),
            trigger_policy=(
                "惰性触发：签到/核销、缺席判定、主动退出结算后置 dirty=1；"
                f"后台每 {settings.AI_PROFILE_SCAN_INTERVAL_SECONDS} 秒兜底重算，"
                "用户查看画像或个人主页时也会按需重算"
            ),
            match_score_formula={
                "base": 60,
                "reputation": "20 × (画像分/150)",
                "skill": "12 × max(0, 1 - 球技差距/5)",
                "preference": "8 × 该球类历史占比",
                "penalty_full": -5,
                "conflict": "与已报名球局时间冲突时匹配分置 0",
                "desc": "球局列表对登录用户按此公式实时计算 match_score，未登录返回静态基线 80.0",
            },
            source_priority=["deepseek", "rule(本地加权规则降级)"],
        )
    )


# ==================================================================
# 管理端：批量重算待刷新画像
# ==================================================================
@router.post(
    "/refresh-dirty",
    response_model=ApiResponse[dict],
    summary="批量重算「待重算」用户的画像（管理端/运维）",
    description=(
        "扫描 `ai_profile_dirty=1` 的用户并重新生成画像。\n"
        "生产环境由后台任务每 10 分钟自动执行一次，本接口用于手动补偿（例如大模型短暂不可用后补算）。"
    ),
)
async def refresh_dirty(
    db: DbSession,
    admin: User = Depends(get_current_admin),
    limit: int = Query(20, ge=1, le=200, description="单轮最多重算多少个用户"),
):
    result = await ai_service.refresh_dirty_profiles(db, limit=limit)
    return ApiResponse.ok(
        result,
        message=f"扫描 {result['scanned']} 人，重算成功 {result['refreshed']} 人",
    )


@router.get(
    "/stats",
    response_model=ApiResponse[dict],
    summary="画像运行状态（待重算人数 / 来源分布 / 是否启用大模型）",
)
async def profile_stats(current_user: CurrentUser, db: DbSession):
    """运维视角：查看画像模块运行状态"""
    from sqlalchemy import func

    dirty_count = (
        await db.execute(select(func.count()).select_from(User).where(User.ai_profile_dirty == 1))
    ).scalar_one()
    total_with_profile = (
        await db.execute(select(func.count()).select_from(User).where(User.ai_profile.isnot(None)))
    ).scalar_one()
    deepseek_count = (
        await db.execute(
            select(func.count()).select_from(User).where(User.ai_profile_source == "deepseek")
        )
    ).scalar_one()
    rule_count = (
        await db.execute(select(func.count()).select_from(User).where(User.ai_profile_source == "rule"))
    ).scalar_one()

    return ApiResponse.ok(
        {
            "llm_available": ai_service.ai_profile_service.available,
            "llm_model": settings.DEEPSEEK_MODEL if ai_service.ai_profile_service.available else None,
            "enabled": settings.AI_ENABLED,
            "trigger_on_settle": settings.AI_PROFILE_TRIGGER_ON_SETTLE,
            "async_refresh": settings.AI_PROFILE_ASYNC_REFRESH,
            "scan_interval_seconds": settings.AI_PROFILE_SCAN_INTERVAL_SECONDS,
            "cache_hours": settings.AI_PROFILE_CACHE_HOURS,
            "dirty_count": dirty_count,
            "profiled_users": total_with_profile,
            "source_distribution": {"deepseek": deepseek_count, "rule": rule_count},
            "match_score_enabled": settings.AI_MATCH_SCORE_ENABLED,
        }
    )


# ==================================================================
# 内部工具
# ==================================================================
async def _resolve_profile(db: DbSession, user: User, *, force: bool = False) -> AIProfileOut:
    """
    决定「返回缓存」还是「当场重算」：
        force=True                        → 重算
        dirty=1（签到/缺席/退出后标记）    → 重算
        无画像 / 缓存超过 CACHE_HOURS      → 重算
        否则                              → 返回缓存
    """
    cached = user.ai_profile if isinstance(user.ai_profile, dict) else None
    updated_at = user.ai_profile_updated_at

    expired = bool(
        updated_at
        and datetime.now() - updated_at > timedelta(hours=settings.AI_PROFILE_CACHE_HOURS)
    )
    need_rebuild = force or cached is None or bool(user.ai_profile_dirty) or expired

    if force or cached is None:
        trigger = "manual"           # 手动刷新 / 首次生成
    elif expired:
        trigger = "cache_expired"
    else:
        trigger = user.ai_profile_trigger or "dirty"

    if need_rebuild:
        profile_data = await ai_service.generate_profile(db, user.id, trigger=trigger)
        if profile_data is None:
            raise NotFoundException("用户不存在或已注销")
        return _to_out(user.id, profile_data, cached=False, version=(user.ai_profile_version or 1))

    # 返回缓存：把关键字段补齐（老数据可能缺 score/breakdown）
    features = await ai_service.collect_features(db, user.id)
    rule = ai_service.local_weighted_score(features) if features else {"score": 0, "breakdown": []}
    profile_data = dict(cached)
    profile_data.setdefault("score", user.ai_score or rule["score"])
    profile_data.setdefault("rule_score", rule["score"])
    profile_data.setdefault("reputation_score", user.reputation_score)
    profile_data.setdefault("breakdown", rule["breakdown"])
    profile_data.setdefault("score_gap", int(profile_data.get("score") or 0) - user.reputation_score)
    return _to_out(user.id, profile_data, cached=True, version=user.ai_profile_version or 0)


def _to_out(user_id: int, data: dict, *, cached: bool, version: int) -> AIProfileOut:
    """把画像字典转成接口出参（容错：老数据缺字段时用默认值补齐）"""
    generated_at = data.get("generated_at")
    return AIProfileOut(
        user_id=user_id,
        score=int(data.get("score") or 0),
        rule_score=int(data.get("rule_score") or 0),
        ai_score=data.get("ai_score"),
        ai_adjust=int(data.get("ai_adjust") or 0),
        reputation_score=int(data.get("reputation_score") or 0),
        score_gap=int(data.get("score_gap") or 0),
        credit_level=int(data.get("credit_level") or 3),
        credit_level_text=data.get("credit_level_text") or "正常",
        risk_level=data.get("risk_level") or "medium",
        tags=list(data.get("tags") or []),
        summary=data.get("summary") or "",
        suggestions=list(data.get("suggestions") or []),
        source=data.get("source") or "rule",
        degraded=bool(data.get("degraded", True)),
        trigger=data.get("trigger"),
        version=version,
        cached=cached,
        generated_at=generated_at if isinstance(generated_at, datetime) else None,
        features=data.get("features") or {},
        breakdown=list(data.get("breakdown") or []),
    )
