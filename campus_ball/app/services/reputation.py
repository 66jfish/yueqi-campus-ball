"""
信誉分「惰性结算」服务 ★核心模块★
====================================================================
一、什么是惰性结算
    信誉分平时不做任何实时计算，只在两个时机被触发更新：
        触发时机 A：签到（正常签到 / 迟到签到）
        触发时机 B：判定缺席（球局结束后未签到且未请假）
    其余任何时候读取信誉分，都是直接读 t_user.credit_score 这一列。

二、怎么保证不重复结算
    t_checkin_record.settled 就是「账本标记」：
        settled=0 → 这条记录还没折算成分数
        settled=1 → 已折算，并记录 settled_at
    结算时按 (user_id, settled=0) 捞出所有待结算记录，一次性汇总，
    然后统一置 1。即使接口被重复调用，第二次也捞不到记录，天然幂等。

三、并发安全
    结算前对 t_user 行加 FOR UPDATE 悲观锁，
    避免「签到」和「缺席判定」同时结算造成分数覆盖丢失。

四、结算后附加动作
    若结算后信誉分低于阈值 → 自动调用失信小黑屋服务封禁（默认 3 天）。
====================================================================
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import (
    CREDIT_RULES,
    BanReasonType,
    CheckinStatus,
    GameStatus,
    RegistrationStatus,
    SettleStatus,
    map_credit_level,
)
from app.models import Blacklist, CheckinRecord, Game, Registration, User
from app.services import ai_profile as ai_profile_service
from app.services import blacklist as blacklist_service

logger = logging.getLogger(__name__)

# 会产生信誉分变动的签到状态（也是「待结算」的判定范围）
SETTLEABLE_STATUSES = (
    CheckinStatus.CHECKED,
    CheckinStatus.LATE,
    CheckinStatus.ABSENT,
    CheckinStatus.LEAVE,
)


@dataclass
class SettleResult:
    """一次结算的结果，直接返回给前端展示「本次信誉分变动」"""

    user_id: int
    credit_before: int
    credit_delta: int
    credit_after: int
    credit_level: int
    settled_record_count: int
    banned: bool = False
    ban_extended: bool = False  # True=封禁期内顺延（规则6），False=新建封禁
    ban_end_time: datetime | None = None
    details: list[dict] = field(default_factory=list)  # 每条记录的明细

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "credit_before": self.credit_before,
            "credit_delta": self.credit_delta,
            "credit_after": self.credit_after,
            "credit_level": self.credit_level,
            "settled_record_count": self.settled_record_count,
            "banned": self.banned,
            "ban_extended": self.ban_extended,
            "ban_end_time": self.ban_end_time.isoformat() if self.ban_end_time else None,
            "details": self.details,
        }


# ==================================================================
# 内部工具
# ==================================================================
def _clamp(score: int) -> int:
    """把信誉分限制在 [MIN, MAX] 区间内"""
    return max(settings.CREDIT_SCORE_MIN, min(settings.CREDIT_SCORE_MAX, score))


# ==================================================================
# 触发时机 A：签到
# ==================================================================
async def settle_on_checkin(
    db: AsyncSession,
    *,
    game_id: int,
    user_id: int,
    checkin_status: int = CheckinStatus.CHECKED,
    registration_id: int | None = None,
    checkin_type: int | None = None,
    location_lat: float | None = None,
    location_lng: float | None = None,
    remark: str | None = None,
    commit: bool = True,
) -> SettleResult:
    """
    签到入口：写入/更新签到记录，并立即触发一次惰性结算。

    :param checkin_status: CheckinStatus.CHECKED(正常) 或 CheckinStatus.LATE(迟到)
    :return: 本次结算结果（含信誉分变动，供前端弹「信誉分 +2」提示）
    """
    if checkin_status not in (CheckinStatus.CHECKED, CheckinStatus.LATE, CheckinStatus.LEAVE):
        raise ValueError("签到状态只能是 正常签到/迟到/请假")

    # 1) 找记录，没有就创建（报名时也可以预生成一条 settled=0 的记录）
    stmt = select(CheckinRecord).where(
        CheckinRecord.game_id == game_id, CheckinRecord.user_id == user_id
    )
    record = (await db.execute(stmt)).scalars().first()

    if record is None:
        record = CheckinRecord(
            game_id=game_id,
            user_id=user_id,
            registration_id=registration_id,
        )
        db.add(record)
    elif record.settled == 1:
        # 已结算过的不再重复签到（防止刷分）
        raise ValueError("该球局已完成结算，无法再次签到")

    record.checkin_status = checkin_status
    record.checkin_type = checkin_type
    record.checkin_time = datetime.now()
    record.location_lat = location_lat
    record.location_lng = location_lng
    if remark:
        record.remark = remark

    await db.flush()  # 拿到 record.id，同时把改动压入当前事务

    # 2) 触发惰性结算（settle_user_pending 内部会置 AI 画像待重算标记）
    return await settle_user_pending(db, user_id=user_id, profile_trigger="checkin", commit=commit)


# ==================================================================
# 触发时机 B：判定缺席（球局结束后的批量处理）
# ==================================================================
async def settle_on_absent_judgement(
    db: AsyncSession,
    *,
    game_id: int,
    operator_id: int = 0,
    auto_prune: bool = True,
    commit: bool = True,
) -> dict:
    """
    球局结束后判定缺席并结算。

    :param auto_prune: 是否自动把「未签到且未请假」的报名者标记为缺席
    :param operator_id: 判定人；系统自动判定填 0
    :return: {"game_id":..., "absent_count":..., "settled_users": [...]}
    """
    game = await db.get(Game, game_id)
    if game is None:
        raise ValueError(f"球局 {game_id} 不存在")

    if game.settle_status == SettleStatus.SETTLED:
        return {"game_id": game_id, "absent_count": 0, "settled_users": [], "message": "该球局已结算"}

    now = datetime.now()
    absent_count = 0
    db_affected_user_ids: list[int] = []  # 用于结算后触发 AI 画像重算

    # 1) 拉出所有仍有效的报名记录
    reg_stmt = select(Registration).where(
        Registration.game_id == game_id,
        Registration.status == RegistrationStatus.SIGNED,
    )
    registrations = list((await db.execute(reg_stmt)).scalars().all())

    affected_user_ids: list[int] = []

    for reg in registrations:
        # 取（或补建）签到记录
        rec_stmt = select(CheckinRecord).where(
            CheckinRecord.game_id == game_id, CheckinRecord.user_id == reg.user_id
        )
        record = (await db.execute(rec_stmt)).scalars().first()

        if record is None:
            record = CheckinRecord(
                game_id=game_id,
                user_id=reg.user_id,
                registration_id=reg.id,
                checkin_status=CheckinStatus.NOT_CHECKED,
            )
            db.add(record)
            await db.flush()

        # 已请假的不算缺席
        if record.checkin_status == CheckinStatus.LEAVE:
            affected_user_ids.append(reg.user_id)
            continue

        # 未签到 -> 判缺席
        if record.checkin_status == CheckinStatus.NOT_CHECKED and auto_prune:
            record.checkin_status = CheckinStatus.ABSENT
            record.absence_confirmed_by = operator_id
            record.absence_confirmed_at = now
            absent_count += 1

        affected_user_ids.append(reg.user_id)

    # 2) 逐个用户结算（去重，避免一个用户被结算两次）
    #    注意：必须先把上面标记的「缺席」状态 flush 到数据库，
    #    否则（autoflush=False 的生产会话）结算查不到这些记录，会静默不结算。
    await db.flush()
    settled_users: list[dict] = []

    for user_id in dict.fromkeys(affected_user_ids):
        result = await settle_user_pending(
            db,
            user_id=user_id,
            game_id=game_id,
            apply_low_credit_ban=False,  # 封禁决策在下面统一做（缺席优先，规则2/6）
            profile_trigger=None,        # 画像标记在循环后统一按 "absent" 打（见下方第4步）
            commit=False,
        )
        if result is None:
            continue

        entry = result.to_dict()
        is_absent = any(int(d["checkin_status"]) == int(CheckinStatus.ABSENT) for d in result.details)
        ban_info = await _apply_ban_decision(
            db,
            result=result,
            is_absent=is_absent,
            game_id=game_id,
            operator_id=operator_id,
        )
        if ban_info is not None:
            # _apply_ban_decision 内部已回填 result.banned / ban_extended / ban_end_time
            entry.update(
                banned=result.banned,
                ban_extended=result.ban_extended,
                ban_end_time=ban_info["ban_end_time"],
                ban=ban_info,
            )
        settled_users.append(entry)
        db_affected_user_ids.append(user_id)

    # 3) 更新球局结算状态：状态推进为「已结束」（规则1：已结束即完成缺席判定）
    game.settle_status = SettleStatus.SETTLED
    game.settled_at = now
    if game.status != GameStatus.CANCELED:
        game.status = GameStatus.FINISHED

    # 4) ★缺席触发的 AI 画像重算：同一事务内置脏标记（保证后台兜底一定扫得到）
    await ai_profile_service.mark_profile_dirty(
        db, db_affected_user_ids, trigger="absent", commit=False
    )

    if commit:
        await db.commit()

    # 5) 尽量立刻异步重算（失败无妨，dirty 标记已落库，由后台循环兜底）
    ai_profile_service.schedule_profile_refresh(db_affected_user_ids, trigger="absent")

    logger.info(
        "球局 %s 缺席判定完成：缺席 %d 人，结算 %d 人",
        game_id, absent_count, len(settled_users),
    )
    return {
        "game_id": game_id,
        "absent_count": absent_count,
        "settled_users": settled_users,
    }


async def _apply_ban_decision(
    db: AsyncSession,
    *,
    result: SettleResult,
    is_absent: bool,
    game_id: int | None,
    operator_id: int = 0,
) -> dict | None:
    """
    一次结算最多触发一条封禁决策，避免重复惩罚：
        1) 本次有缺席记录 → 按规则2 封禁 3 天（若已在封禁中则按规则6 顺延）
        2) 否则若信誉分低于阈值 → 按低信誉规则封禁
        3) 都不满足 → 不封禁
    """
    if is_absent and settings.BAN_ON_ABSENT:
        applied = await blacklist_service.ban_for_absent(
            db,
            user_id=result.user_id,
            trigger_game_id=game_id,
            credit_score_at_ban=result.credit_after,
            operator_id=operator_id,
            commit=False,
        )
    elif result.credit_after < settings.CREDIT_BAN_THRESHOLD:
        applied = await blacklist_service.ban_for_low_credit(
            db,
            user_id=result.user_id,
            credit_score=result.credit_after,
            trigger_game_id=game_id,
            operator_id=operator_id,
            commit=False,
        )
    else:
        return None

    ban = applied.ban
    result.banned = True
    result.ban_extended = not applied.created
    result.ban_end_time = ban.ban_end_time
    return {
        "created": applied.created,
        "extended_days": applied.extended_days,
        "capped": applied.capped,
        "extend_count": ban.ban_extend_count or 0,
        "ban_id": ban.id,
        "ban_start_time": ban.ban_start_time.isoformat() if ban.ban_start_time else None,
        "ban_end_time": ban.ban_end_time.isoformat() if ban.ban_end_time else None,
        "reason": ban.reason,
        "message": applied.message,
    }


# ==================================================================
# 惰性结算核心：把某用户的待结算记录一次性折算成信誉分
# ==================================================================
async def settle_user_pending(
    db: AsyncSession,
    *,
    user_id: int,
    game_id: int | None = None,
    apply_low_credit_ban: bool = True,
    profile_trigger: str | None = "checkin",
    commit: bool = True,
) -> SettleResult | None:
    """
    结算某用户所有 settled=0 的签到记录。

    :param game_id: 仅结算指定球局的记录；None 表示结算全部待结算记录
    :param apply_low_credit_ban: 信誉分过低时是否在此处触发封禁。
           缺席判定流程会传 False，因为它自己按「缺席优先」的规则统一决策封禁，
           避免同一次结算里既触发了低信誉封禁、又触发了缺席封禁（重复惩罚）。
    :param profile_trigger: ★AI 画像重算的触发原因；所有结算路径都经过本函数，
           因此把「置画像待重算标记」放在这里，保证签到/核销/缺席都能触发，且只需写一处。
           传 None 表示不触发（例如纯脚本补算场景）。
    :return: 结算结果；若没有待结算记录则返回 None（惰性：不做任何写操作）
    """
    # 0) 先把调用方在当前事务里改动的签到状态刷入数据库再查。
    #    生产会话是 autoflush=False（见 app/db/session.py），
    #    若不显式 flush，像「缺席判定」这种「先改状态、再结算」的流程会读不到刚改的记录，
    #    结果就是结算被静默跳过（信誉分不更新），排查起来非常隐蔽。
    await db.flush()

    # 1) 捞待结算记录
    stmt = select(CheckinRecord).where(
        CheckinRecord.user_id == user_id,
        CheckinRecord.settled == 0,
        CheckinRecord.checkin_status.in_([int(s) for s in SETTLEABLE_STATUSES]),
    )
    if game_id is not None:
        stmt = stmt.where(CheckinRecord.game_id == game_id)

    records = list((await db.execute(stmt)).scalars().all())
    if not records:
        return None  # 没有待结算内容 → 什么都不做，这就是「惰性」

    # 2) 对用户行加锁，防止并发结算相互覆盖
    user_stmt = select(User).where(User.id == user_id).with_for_update()
    user = (await db.execute(user_stmt)).scalars().first()
    if user is None:
        raise ValueError(f"用户 {user_id} 不存在")

    # 3) 汇总分值变动
    credit_before = user.credit_score
    total_delta = 0
    attended = 0     # 实际到场场次（正常签到/迟到）
    absent_num = 0   # 缺席次数
    details: list[dict] = []

    for record in records:
        delta = CREDIT_RULES.get(record.checkin_status, 0)
        total_delta += delta
        record.credit_delta = delta
        record.settled = 1
        record.settled_at = datetime.now()

        if record.checkin_status in (CheckinStatus.CHECKED, CheckinStatus.LATE):
            attended += 1
        elif record.checkin_status == CheckinStatus.ABSENT:
            absent_num += 1

        details.append(
            {
                "checkin_record_id": record.id,
                "game_id": record.game_id,
                "checkin_status": record.checkin_status,
                "credit_delta": delta,
            }
        )

    # 4) 更新用户信誉分与统计（t_user.reputation_score：缺席 -10 分在此落库）
    credit_after = _clamp(credit_before + total_delta)
    user.reputation_score = credit_after
    user.credit_level = int(map_credit_level(credit_after))
    user.credit_settled_at = datetime.now()
    user.total_game_count = (user.total_game_count or 0) + attended
    user.absent_count = (user.absent_count or 0) + absent_num

    await db.flush()

    result = SettleResult(
        user_id=user_id,
        credit_before=credit_before,
        credit_delta=credit_after - credit_before,  # 触发上下限后按实际变动返回
        credit_after=credit_after,
        credit_level=user.credit_level,
        settled_record_count=len(records),
        details=details,
    )
    # 5) 信誉分过低 → 自动进小黑屋（默认 3 天）；已在封禁中则按规则6 顺延
    if apply_low_credit_ban and credit_after < settings.CREDIT_BAN_THRESHOLD:
        ban_result = await blacklist_service.ban_for_low_credit(
            db,
            user_id=user_id,
            credit_score=credit_after,
            trigger_game_id=game_id,
            operator_id=0,
            commit=False,
        )
        result.banned = True
        result.ban_extended = not ban_result.created
        result.ban_end_time = ban_result.ban.ban_end_time

    # 6) ★结算完成 → 标记 AI 信誉画像待重算（同一事务，保证一定被后台兜底到）
    if profile_trigger:
        await ai_profile_service.mark_profile_dirty(
            db, [user_id], trigger=profile_trigger, commit=False
        )

    if commit:
        await db.commit()
        if profile_trigger:
            # 尽量立刻异步重算（不阻塞接口；失败由后台循环兜底）
            ai_profile_service.schedule_profile_refresh([user_id], trigger=profile_trigger)

    logger.info(
        "惰性结算：用户 %s 结算 %d 条记录，信誉分 %s -> %s",
        user_id, len(records), credit_before, credit_after,
    )
    return result


# ==================================================================
# 辅助查询
# ==================================================================
async def get_pending_record_count(db: AsyncSession, user_id: int) -> int:
    """
    查询用户当前有多少条「待结算」记录。
    注意：这是查询而不是结算，用于前端显示「有 2 条记录待结算」，不改变分数。
    """
    stmt = select(CheckinRecord.id).where(
        CheckinRecord.user_id == user_id,
        CheckinRecord.settled == 0,
        CheckinRecord.checkin_status.in_([int(s) for s in SETTLEABLE_STATUSES]),
    )
    return len(list((await db.execute(stmt)).scalars().all()))


async def get_credit_history(db: AsyncSession, user_id: int, limit: int = 20) -> list[dict]:
    """查询信誉分流水（来自已结算的签到记录，无需额外的流水表）"""
    stmt = (
        select(CheckinRecord)
        .where(
            CheckinRecord.user_id == user_id,
            CheckinRecord.settled == 1,
        )
        .order_by(CheckinRecord.settled_at.desc())
        .limit(limit)
    )
    records = list((await db.execute(stmt)).scalars().all())
    return [
        {
            "checkin_record_id": r.id,
            "game_id": r.game_id,
            "checkin_status": r.checkin_status,
            "credit_delta": r.credit_delta,
            "settled_at": r.settled_at.isoformat() if r.settled_at else None,
        }
        for r in records
    ]
