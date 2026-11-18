"""
AI 信誉画像服务（惰性触发：签到 / 缺席 / 退出 时重算）
====================================================================
一、双轨算法
    轨道A（首选）：DeepSeek 大模型
        输入用户历史行为特征 → 输出标签、风险等级、总结、建议、AI 建议分
    轨道B（降级）：本地加权规则版
        完全确定性、不依赖网络与大模型，Demo/离线环境可正常运行
    两条轨道返回结构完全一致，接口层无需区分；响应里用 source/degraded 标明来源。

二、融合策略（关键设计）
    最终画像分 = AI_WEIGHT * AI建议分 + (1 - AI_WEIGHT) * 本地加权分
    且限制 |最终分 - 本地加权分| <= AI_SCORE_MAX_ADJUST（默认 8 分）
      理由：
        1) 本地加权分是确定性基线 —— 可复算、可审计、可解释，不会因模型波动而乱跳；
        2) 大模型擅长「标签化 + 自然语言总结」，但直接定分容易出现幻觉与不一致；
        3) 限幅保证「AI 只做微调」，即使模型返回离谱分数也不会破坏业务规则
           （报名门槛、封禁阈值都依赖信誉分，必须稳定）。
    t_user.reputation_score（操作分）仍由惰性结算维护，AI 分写 t_user.ai_score（画像分），
    两者分别用于「业务门槛」与「个人主页展示 + 球局匹配参考」，互不干扰。

三、惰性触发（与信誉分结算绑定）
    签到 / 核销 / 缺席判定 / 退出球局 → mark_profile_dirty() 置 dirty=1
        → ① 如开启 AI_PROFILE_ASYNC_REFRESH，立刻用后台任务异步重算（不阻塞接口响应）
        → ② 后台循环每 AI_PROFILE_SCAN_INTERVAL_SECONDS 扫一遍 dirty=1 的用户兜底重算
        → ③ 用户打开个人主页 / 调用画像接口时，若 dirty=1 或缓存过期，当场重算（保证展示最新）
    三次机会保证「最终一致」，同时接口响应始终很快。

四、下游应用
    compute_match_score()：把画像分作为球局匹配分（match_score）的输入之一，
    球局列表对登录用户按画像实时计算（未登录返回静态基线分）。
====================================================================
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import (
    AI_SCORE_MAX_ADJUST,
    AI_SCORE_WEIGHT,
    CREDIT_LEVEL_THRESHOLDS,
    MATCH_SCORE_BASE,
    MATCH_SCORE_MAX,
    MATCH_SCORE_PENALTY_FULL,
    MATCH_SCORE_PLACEHOLDER,
    MATCH_SCORE_WEIGHT_PREFERENCE,
    MATCH_SCORE_WEIGHT_REPUTATION,
    MATCH_SCORE_WEIGHT_SKILL,
    PROFILE_LATE_CANCEL_HOURS,
    PROFILE_SCORE_MAX,
    PROFILE_SCORE_MIN,
    PROFILE_WEIGHTS,
    CheckinStatus,
    CreditLevel,
    GameStatus,
    RegistrationStatus,
    map_credit_level,
)
from app.models import CheckinRecord, Game, Registration, User
from app.db.session import async_session_scope

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 后台刷新任务使用的会话工厂（默认生产库；单元测试可替换为测试库）
# 与 app/middleware/hooks.py 的做法保持一致，便于测试注入
# ------------------------------------------------------------------
SESSION_SCOPE_FACTORY = async_session_scope
_pending_tasks: set[Any] = set()


def set_session_scope_factory(factory: Any) -> None:
    """替换后台画像任务使用的数据库会话工厂（单元测试注入内存库时使用）"""
    global SESSION_SCOPE_FACTORY
    SESSION_SCOPE_FACTORY = factory

_LEVEL_TEXT = {
    CreditLevel.BLACKLIST: "黑名单",
    CreditLevel.WATCH: "观察中",
    CreditLevel.NORMAL: "正常",
    CreditLevel.GOOD: "优秀",
    CreditLevel.GOLD: "金牌球友",
}

# DeepSeek 系统提示词：约束输出 JSON，降低解析成本
_SYSTEM_PROMPT = (
    "你是校园运动平台的信誉画像分析助手。根据用户的历史行为特征（签到/迟到/缺席/请假/退出等），"
    "输出 JSON，不要输出任何多余文字。字段要求：\n"
    "  score: 0-150 的整数信誉分建议（100 为初始分，按时签到应加分，无故缺席应大幅扣分，主动退出应小幅扣分）\n"
    "  risk_level: low / medium / high\n"
    "  tags: 3-5 个中文短标签（例如：守约达人、习惯性迟到、频繁放鸽子、球局常客）\n"
    "  summary: 60 字以内的中文总结\n"
    "  suggestions: 2-3 条中文改进建议"
)


# ==================================================================
# 一、行为特征（画像算法的唯一输入）
# ==================================================================
@dataclass
class ProfileFeatures:
    """用户历史行为特征（全部来自数据库可查事实，可复算）"""

    user_id: int
    nickname: str = ""
    reputation_score: int = 100          # 当前操作分（惰性结算维护）
    credit_level: int = 3
    skill_level: int = 1
    # --- 签到类 ---
    checked_count: int = 0               # 按时签到（到场）
    late_count: int = 0                  # 迟到
    leave_count: int = 0                 # 请假
    absent_count: int = 0                # 无故缺席（未签到未请假）
    # --- 报名/退出类 ---
    signup_total: int = 0                # 累计报名（正式名额）
    cancel_early_count: int = 0          # 主动退出（距开球 > 阈值）
    cancel_late_count: int = 0           # 临近开球退出（≤ 阈值）
    game_created_count: int = 0          # 发起球局场次
    # --- 球类偏好（匹配分用） ---
    sport_counts: dict[int, int] = field(default_factory=dict)

    # ---------------- 派生指标 ----------------
    @property
    def settled_total(self) -> int:
        """已完成判定的场次（签到+迟到+缺席+请假）"""
        return self.checked_count + self.late_count + self.leave_count + self.absent_count

    @property
    def expected_total(self) -> int:
        """应到场场次（不含请假：请假是负责任的提前告知）"""
        return self.checked_count + self.late_count + self.absent_count

    @property
    def keep_rate(self) -> float:
        """守约率：应到场里按时到达的比例"""
        return round(self.checked_count / self.expected_total, 3) if self.expected_total else 1.0

    @property
    def absent_rate(self) -> float:
        return round(self.absent_count / self.expected_total, 3) if self.expected_total else 0.0

    @property
    def late_rate(self) -> float:
        return round(self.late_count / self.expected_total, 3) if self.expected_total else 0.0

    @property
    def cancel_total(self) -> int:
        return self.cancel_early_count + self.cancel_late_count

    @property
    def cancel_rate(self) -> float:
        return round(self.cancel_total / self.signup_total, 3) if self.signup_total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "nickname": self.nickname,
            "reputation_score": self.reputation_score,
            "skill_level": self.skill_level,
            "checked_count": self.checked_count,
            "late_count": self.late_count,
            "leave_count": self.leave_count,
            "absent_count": self.absent_count,
            "signup_total": self.signup_total,
            "cancel_early_count": self.cancel_early_count,
            "cancel_late_count": self.cancel_late_count,
            "game_created_count": self.game_created_count,
            "settled_total": self.settled_total,
            "keep_rate": self.keep_rate,
            "absent_rate": self.absent_rate,
            "late_rate": self.late_rate,
            "cancel_rate": self.cancel_rate,
        }


async def collect_features(db: AsyncSession, user_id: int) -> ProfileFeatures | None:
    """
    汇总画像所需的全部行为事实（一次查询搞定，避免多次往返）：
        签到记录聚合 + 报名/退出聚合 + 发起球局数 + 球类偏好
    """
    user = await db.get(User, user_id)
    if user is None or user.is_deleted:
        return None

    # 1) 签到类统计
    checkin_rows = (
        await db.execute(
            select(
                func.sum(case((CheckinRecord.checkin_status == int(CheckinStatus.CHECKED), 1), else_=0)),
                func.sum(case((CheckinRecord.checkin_status == int(CheckinStatus.LATE), 1), else_=0)),
                func.sum(case((CheckinRecord.checkin_status == int(CheckinStatus.LEAVE), 1), else_=0)),
                func.sum(case((CheckinRecord.checkin_status == int(CheckinStatus.ABSENT), 1), else_=0)),
            ).where(CheckinRecord.user_id == user_id)
        )
    ).first()
    checked = int(checkin_rows[0] or 0)
    late = int(checkin_rows[1] or 0)
    leave = int(checkin_rows[2] or 0)
    absent = int(checkin_rows[3] or 0)

    # 2) 报名 / 退出统计（区分「提前退出」与「临近开球才退出」）
    late_cancel_threshold = timedelta(hours=PROFILE_LATE_CANCEL_HOURS)
    reg_rows = (
        await db.execute(
            select(
                Registration.status,
                Registration.signup_time,
                Registration.cancel_time,
                Game.start_time,
            )
            .join(Game, Game.id == Registration.game_id)
            .where(Registration.user_id == user_id, Game.is_deleted == 0)
        )
    ).all()

    signup_total = 0
    cancel_early = 0
    cancel_late = 0
    for status, _signup_time, cancel_time, start_time in reg_rows:
        if status in (RegistrationStatus.SIGNED, RegistrationStatus.WAITLIST, RegistrationStatus.CANCELED):
            signup_total += 1
        if status == RegistrationStatus.CANCELED and cancel_time and start_time:
            if start_time - cancel_time <= late_cancel_threshold:
                cancel_late += 1
            else:
                cancel_early += 1

    # 3) 发起球局数
    created = (
        await db.execute(
            select(func.count())
            .select_from(Game)
            .where(Game.creator_id == user_id, Game.is_deleted == 0)
        )
    ).scalar_one()

    # 4) 球类偏好（用于匹配分：常玩的球类匹配度更高）
    sport_rows = (
        await db.execute(
            select(Game.sport_type, func.count())
            .join(Registration, Registration.game_id == Game.id)
            .where(
                Registration.user_id == user_id,
                Registration.status.in_(
                    [int(RegistrationStatus.SIGNED), int(RegistrationStatus.CANCELED)]
                ),
                Game.is_deleted == 0,
            )
            .group_by(Game.sport_type)
        )
    ).all()

    return ProfileFeatures(
        user_id=user_id,
        nickname=user.nickname,
        reputation_score=user.reputation_score,
        credit_level=user.credit_level,
        skill_level=user.skill_level,
        checked_count=checked,
        late_count=late,
        leave_count=leave,
        absent_count=absent,
        signup_total=signup_total,
        cancel_early_count=cancel_early,
        cancel_late_count=cancel_late,
        game_created_count=created,
        sport_counts={int(sport): int(cnt) for sport, cnt in sport_rows},
    )


# ==================================================================
# 二、轨道B：本地加权规则版（降级方案，确定性算法）
# ==================================================================
def _clamp(value: float, low: int = PROFILE_SCORE_MIN, high: int = PROFILE_SCORE_MAX) -> int:
    return int(max(low, min(high, round(value))))


def local_weighted_score(features: ProfileFeatures) -> dict[str, Any]:
    """
    本地加权规则算法（画像分 = 初始分 + Σ 权重×次数，再裁剪到 [0,150]）

        初始分 BASE = 100（与系统 CREDIT_SCORE_INIT 一致）
        + 按时签到      × (+2)     到场是基本义务，给予稳定正向激励
        + 迟到          × (-3)     影响他人等待，小幅扣分
        + 已请假        × ( 0)     提前告知是负责任行为，不惩罚
        + 无故缺席      × (-10)    ★放鸽子，大幅扣分
        + 主动退出      × (-2)     ★少量扣分（提前足够时间退出，影响可控）
        + 临近开球退出  × (-4)     ★略重（≤2 小时才退出，组织者来不及补位）

    另加「守约加成」：完成 ≥5 场且守约率 ≥95% 时额外 +3（鼓励长期稳定参与）。

    :return: {"score": int, "breakdown": [...], "bonus": int}
    """
    w = PROFILE_WEIGHTS
    items = [
        ("按时签到", features.checked_count, w["checked"]),
        ("迟到签到", features.late_count, w["late"]),
        ("已请假", features.leave_count, w["leave"]),
        ("无故缺席", features.absent_count, w["absent"]),
        ("主动退出", features.cancel_early_count, w["cancel_early"]),
        (f"临近开球退出(≤{PROFILE_LATE_CANCEL_HOURS}h)", features.cancel_late_count, w["cancel_late"]),
    ]

    breakdown: list[dict[str, Any]] = []
    consumed = 0
    for label, count, weight in items:
        subtotal = count * weight
        consumed += subtotal
        breakdown.append(
            {"item": label, "count": count, "weight": weight, "subtotal": subtotal}
        )

    base_bonus = 3 if (features.settled_total >= 5 and features.keep_rate >= 0.95) else 0
    if base_bonus:
        breakdown.append(
            {"item": "守约加成（完成≥5场且守约率≥95%）", "count": 1, "weight": base_bonus, "subtotal": base_bonus}
        )

    raw = settings.CREDIT_SCORE_INIT + consumed + base_bonus
    return {
        "score": _clamp(raw),
        "raw_score": raw,
        "breakdown": breakdown,
        "bonus": base_bonus,
    }


def local_labels(features: ProfileFeatures) -> tuple[list[str], str, list[str]]:
    """
    本地标签 / 风险等级 / 建议（规则版画像的自然语言部分）
    标签优先级：缺席 > 退出 > 迟到 > 参与度 > 球技
    """
    tags: list[str] = []
    suggestions: list[str] = []

    if features.absent_count >= 3 or features.absent_rate >= 0.3:
        tags.append("频繁放鸽子")
    elif features.absent_count >= 1:
        tags.append("有过缺席")
    else:
        tags.append("从未缺席")

    if features.cancel_late_count >= 2:
        tags.append("常临期退局")
    if features.cancel_early_count >= 3 or features.cancel_rate >= 0.4:
        tags.append("报名波动大")
    if features.late_count >= 2 or features.late_rate >= 0.3:
        tags.append("习惯性迟到")
    if features.checked_count >= 10:
        tags.append("球局常客")
    elif features.checked_count >= 3:
        tags.append("稳定参与")
    else:
        tags.append("新人球友")
    if features.skill_level >= 4:
        tags.append("高水平选手")
    if features.reputation_score >= 120:
        tags.append("信誉金牌")

    if features.absent_count >= 3 or features.reputation_score < settings.CREDIT_BAN_THRESHOLD:
        risk_level = "high"
    elif features.absent_count >= 1 or features.cancel_total >= 3 or features.reputation_score < 90:
        risk_level = "medium"
    else:
        risk_level = "low"

    if features.absent_count:
        suggestions.append("报名后请按时到场；确实来不了请提前请假，避免扣除信誉分并被禁赛。")
    if features.cancel_late_count:
        suggestions.append(f"尽量不要在开球前 {PROFILE_LATE_CANCEL_HOURS} 小时内退出，便于组织者补位。")
    if features.late_count >= 2:
        suggestions.append("建议提前 10 分钟到达场地，减少迟到带来的信誉损失。")
    if features.settled_total < 3:
        suggestions.append("多参与球局可以提升画像准确度，也更容易被组织者接纳。")
    if features.checked_count >= 10 and not features.absent_count:
        suggestions.append("长期守约表现优秀，可优先报名热门时段球局。")
    if not suggestions:
        suggestions.append("保持当前良好的参与记录，信誉分会持续累积提升。")

    summary = (
        f"{features.nickname or '该用户'}：累计到场 {features.checked_count} 次、"
        f"迟到 {features.late_count} 次、缺席 {features.absent_count} 次、"
        f"退出 {features.cancel_total} 次（其中临期退出 {features.cancel_late_count} 次），"
        f"守约率 {features.keep_rate * 100:.0f}%。"
    )
    return tags[:5], risk_level, suggestions[:3] + [summary]


# ==================================================================
# 三、轨道A：DeepSeek
# ==================================================================
class AIProfileService:
    """DeepSeek 调用封装：失败/无 Key 一律降级，不向上抛错"""

    def __init__(self) -> None:
        self.api_key = settings.DEEPSEEK_API_KEY.strip()
        self.base_url = settings.DEEPSEEK_BASE_URL.rstrip("/")
        self.model = settings.DEEPSEEK_MODEL
        self.timeout = settings.DEEPSEEK_TIMEOUT

    @property
    def available(self) -> bool:
        return settings.AI_ENABLED and bool(self.api_key)

    async def generate(self, features: ProfileFeatures) -> dict[str, Any]:
        """
        调用 DeepSeek 生成画像（标签/风险等级/总结/建议/AI建议分）
        :raises Exception: 调用失败由上层捕获并降级
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(features.to_dict(), ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
            "max_tokens": 600,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        parsed = json.loads(data["choices"][0]["message"]["content"])
        return {
            "score": parsed.get("score"),
            "risk_level": parsed.get("risk_level", "medium"),
            "tags": parsed.get("tags", []),
            "summary": parsed.get("summary", ""),
            "suggestions": parsed.get("suggestions", []),
        }


ai_profile_service = AIProfileService()


# ==================================================================
# 四、生成 + 融合 + 落库
# ==================================================================
def fuse_score(rule_score: int, ai_score: Any) -> tuple[int, int]:
    """
    融合本地加权分与 AI 建议分
    :return: (最终画像分, 相对基线的调整量)
    """
    if not isinstance(ai_score, (int, float)):
        return rule_score, 0

    blended = AI_SCORE_WEIGHT * float(ai_score) + (1 - AI_SCORE_WEIGHT) * rule_score
    delta = blended - rule_score
    # 限幅：AI 只能微调，防止模型幻觉把分数拉爆
    delta = max(-AI_SCORE_MAX_ADJUST, min(AI_SCORE_MAX_ADJUST, delta))
    final = _clamp(rule_score + delta)
    return final, final - rule_score


async def generate_profile(
    db: AsyncSession,
    user_id: int,
    *,
    trigger: str = "manual",
    commit: bool = True,
) -> dict[str, Any] | None:
    """
    生成并落库用户画像（惰性结算的画像侧入口）

    :param trigger: 触发原因，用于审计：checkin / absent / exit / manual / cache_expired
    :return: 画像结果字典；用户不存在返回 None
    """
    features = await collect_features(db, user_id)
    if features is None:
        return None

    rule_result = local_weighted_score(features)
    local_tags, local_risk, local_texts = local_labels(features)
    local_summary = local_texts[-1]

    source = "rule"
    degraded = True
    ai_raw: dict[str, Any] | None = None

    # ---------- 轨道A：DeepSeek ----------
    if ai_profile_service.available:
        try:
            ai_raw = await ai_profile_service.generate(features)
            source = "deepseek"
            degraded = False
        except Exception as exc:  # noqa: BLE001 - 外部服务失败必须降级
            logger.warning("DeepSeek 画像生成失败，降级为本地加权规则版：user_id=%s err=%s", user_id, exc)

    # ---------- 融合 ----------
    rule_score = rule_result["score"]
    if ai_raw is not None:
        final_score, adjust = fuse_score(rule_score, ai_raw.get("score"))
        tags = [t for t in (ai_raw.get("tags") or []) if t][:5] or local_tags
        risk_level = ai_raw.get("risk_level") or local_risk
        summary = ai_raw.get("summary") or local_summary
        suggestions = [s for s in (ai_raw.get("suggestions") or []) if s][:3]
    else:
        final_score, adjust = rule_score, 0
        tags, risk_level, summary = local_tags, local_risk, local_summary
        suggestions = local_texts[:-1]

    level = map_credit_level(final_score)
    profile = {
        "score": final_score,                       # AI 画像评估分（本模块输出）
        "rule_score": rule_score,                   # 本地加权基线（可审计）
        "ai_score": ai_raw.get("score") if ai_raw else None,   # 大模型建议分（未调用为 null）
        "ai_adjust": adjust,                        # AI 相对基线的调整量（已限幅）
        "reputation_score": features.reputation_score,          # 当前操作分（惰性结算维护）
        "score_gap": final_score - features.reputation_score,   # 画像分与操作分差异（运营预警用）
        "credit_level": int(level),
        "credit_level_text": _LEVEL_TEXT.get(level, "正常"),
        "risk_level": risk_level,
        "tags": tags,
        "summary": summary,
        "suggestions": suggestions,
        "source": source,
        "degraded": degraded,                       # true=本地加权规则版
        "trigger": trigger,
        "features": features.to_dict(),
        "breakdown": rule_result["breakdown"],      # 加权明细（前端可展示"分数怎么来的"）
        "generated_at": datetime.now().isoformat(),
    }

    user = await db.get(User, user_id)
    user.ai_profile = profile
    user.ai_score = final_score
    user.ai_profile_source = source
    user.ai_profile_updated_at = datetime.now()
    user.ai_profile_dirty = 0
    user.ai_profile_trigger = trigger
    user.ai_profile_version = (user.ai_profile_version or 0) + 1

    if commit:
        await db.commit()

    logger.info(
        "画像重算完成：user_id=%s trigger=%s source=%s 画像分=%s（基线 %s，AI调整 %+d，操作分 %s）",
        user_id, trigger, source, final_score, rule_score, adjust, features.reputation_score,
    )
    return profile


# ==================================================================
# 五、惰性触发：脏标记 + 后台刷新
# ==================================================================
async def mark_profile_dirty(
    db: AsyncSession,
    user_ids: list[int],
    *,
    trigger: str,
    commit: bool = False,
) -> int:
    """
    把用户标记为「画像待重算」（签到 / 缺席 / 退出结算后调用）。
    只置标记、不做重算，保证业务接口响应不被大模型调用拖慢；
    真正的重算由「后台循环」或「用户查看画像时」完成。

    :return: 被标记的用户数
    """
    ids = list(dict.fromkeys(uid for uid in user_ids if uid))
    if not ids:
        return 0

    users = list((await db.execute(select(User).where(User.id.in_(ids)))).scalars().all())
    for user in users:
        user.ai_profile_dirty = 1
        user.ai_profile_trigger = trigger
    if commit:
        await db.commit()
    logger.info("标记画像待重算：%d 个用户（trigger=%s）", len(users), trigger)
    return len(users)


async def refresh_dirty_profiles(db: AsyncSession, limit: int | None = None) -> dict[str, Any]:
    """
    后台批量重算「待重算」用户的画像（兜底，保证最终一致）。
    单用户失败不影响其它用户。
    """
    batch = limit or settings.AI_PROFILE_SCAN_BATCH_SIZE
    stmt = (
        select(User.id, User.ai_profile_trigger)
        .where(User.ai_profile_dirty == 1, User.is_deleted == 0)
        .order_by(User.updated_at.asc())
        .limit(batch)
    )
    rows = (await db.execute(stmt)).all()

    done: list[int] = []
    failed: list[int] = []
    for user_id, trigger in rows:
        try:
            await generate_profile(db, user_id, trigger=f"async:{trigger or 'dirty'}", commit=False)
            done.append(user_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("后台重算画像失败 user_id=%s：%s", user_id, exc)
            await db.rollback()
            failed.append(user_id)

    if done:
        await db.commit()
    return {"scanned": len(rows), "refreshed": len(done), "failed": failed}


def schedule_profile_refresh(user_ids: list[int], trigger: str) -> None:
    """
    结算后「立刻异步」重算画像（不阻塞接口响应）。

    设计取舍与健壮性处理：
        - 用 asyncio.create_task 起独立任务、独立会话，避免污染请求事务；
        - 任务内部完全吞掉异常 —— 画像失败绝不能影响签到/缺席判定的结果；
        - 强引用保存任务并在结束时回收，异常通过 done_callback 记录而不是抛给事件循环
          （否则事件循环关闭时会出现 "Task exception was never retrieved" 之类的噪声错误）；
        - 若进程在任务完成前退出，dirty 标记仍在，后台循环会补算（最终一致）。
    """
    if not settings.AI_PROFILE_TRIGGER_ON_SETTLE or not settings.AI_PROFILE_ASYNC_REFRESH:
        return
    ids = [uid for uid in dict.fromkeys(user_ids) if uid]
    if not ids:
        return

    async def _worker() -> None:
        try:
            async with SESSION_SCOPE_FACTORY() as db:
                await mark_profile_dirty(db, ids, trigger=trigger, commit=True)
                for user_id in ids:
                    try:
                        await generate_profile(db, user_id, trigger=trigger, commit=False)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("异步重算画像失败 user_id=%s：%s", user_id, exc)
                        await db.rollback()
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("画像异步刷新任务失败（不影响主流程）：%s", exc)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 非异步上下文（例如脚本里直接调用服务层）：跳过，交给后台循环兜底
        logger.debug("当前无运行中的事件循环，跳过画像异步刷新")
        return

    task = loop.create_task(_worker())
    _pending_tasks.add(task)
    task.add_done_callback(_on_task_done)


def _on_task_done(task: "asyncio.Task[None]") -> None:
    """后台任务收尾：回收引用 + 记录异常（绝不把异常抛回事件循环）"""
    _pending_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:  # pragma: no cover - 兜底日志
        logger.warning("画像异步刷新任务异常（不影响主流程）：%s", exc)


# ==================================================================
# 六、下游应用：球局匹配参考分
# ==================================================================
def compute_match_score(
    *,
    features: ProfileFeatures | None,
    profile: dict[str, Any] | None,
    game_skill_limit: int,
    game_sport_type: int,
    is_full: bool,
    time_conflict: bool = False,
    game_min_reputation: int = 0,
) -> dict[str, Any]:
    """
    球局匹配分（画像分的下游应用，0-100）：

        基础分 BASE(60)
        + 信誉匹配：20 × (画像分 / 150)                     信誉越好越容易被推荐
        + 球技匹配：12 × max(0, 1 - 差值/5)                 与球局门槛的差距每级扣 20%
        + 球类偏好：8 × (该球类历史占比)                     常玩的球类匹配度更高
        - 满员惩罚：5                                       已满的球局降权
        - 时间冲突：直接置 0（并给出 reason，前端可提示不可报名）
        - 信誉分不达门槛：直接置 0

    未登录（features/profile 均为 None）→ 返回静态基线分，保证匿名浏览可用。
    """
    if features is None or profile is None:
        return {"match_score": MATCH_SCORE_PLACEHOLDER, "match_reason": "未登录，返回通用推荐分"}

    if time_conflict:
        return {"match_score": 0.0, "match_reason": "时间冲突：该时段您已报名其它球局"}

    score_value = int(profile.get("score") or features.reputation_score)
    if game_min_reputation and score_value < game_min_reputation:
        return {
            "match_score": 0.0,
            "match_reason": f"您的信誉分 {score_value} 低于该球局门槛 {game_min_reputation}",
        }

    score = MATCH_SCORE_BASE
    score += MATCH_SCORE_WEIGHT_REPUTATION * (score_value / PROFILE_SCORE_MAX)

    skill_gap = max(0, game_skill_limit - features.skill_level)
    score += MATCH_SCORE_WEIGHT_SKILL * max(0.0, 1 - skill_gap / 5)

    total_sport = sum(features.sport_counts.values())
    if total_sport:
        ratio = features.sport_counts.get(game_sport_type, 0) / total_sport
        score += MATCH_SCORE_WEIGHT_PREFERENCE * ratio

    if is_full:
        score -= MATCH_SCORE_PENALTY_FULL

    score = round(max(0.0, min(MATCH_SCORE_MAX, score)), 1)

    reasons = [f"信誉分 {score_value}"]
    if game_skill_limit and features.skill_level >= game_skill_limit:
        reasons.append("球技符合要求")
    if total_sport and features.sport_counts.get(game_sport_type):
        reasons.append("常玩该球类")
    if is_full:
        reasons.append("已满员（可候补）")
    return {"match_score": score, "match_reason": "、".join(reasons)}


async def build_match_context(db: AsyncSession, user_id: int) -> tuple[ProfileFeatures | None, dict | None]:
    """
    取用户的画像上下文（特征 + 画像 JSON），用于球局列表计算 match_score。
    画像缺失时用历史特征现场算一次基线（不落库，保证列表接口够快）。
    """
    features = await collect_features(db, user_id)
    if features is None:
        return None, None

    user = await db.get(User, user_id)
    profile = user.ai_profile if isinstance(user.ai_profile, dict) else None
    if profile is None or profile.get("score") is None:
        rule = local_weighted_score(features)
        tags, risk, texts = local_labels(features)
        profile = {
            "score": rule["score"],
            "tags": tags,
            "risk_level": risk,
            "summary": texts[-1],
            "source": "rule",
            "degraded": True,
            "breakdown": rule["breakdown"],
        }
    return features, profile
