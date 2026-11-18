"""
签到核销服务（发起人核销到场用户）
====================================================================
★ 核销是「惰性结算」的触发时机 A：
    发起人核销 → 写入签到记录（到场状态）→ 立即结算该用户本场记录 → 信誉分变动
    之后球局结束时的缺席判定只会处理「未签到且未请假」的人，两者数据同源。

关键规则：
    1. 只有球局发起人可以核销（接口层已用 assert_is_creator 校验，服务层再兜一次）
    2. 核销窗口：球局自身的 checkin_start_time/checkin_end_time，
       未配置则按配置推算（开球前 30 分钟开放 / 开球后 15 分钟截止）
    3. 超过截止时间核销 → 记为「迟到」（-3 分）；窗口内 → 「正常签到」（+2 分）
    4. 幂等：已核销/已请假的用户会被跳过并给出原因，不重复加分
    5. 已结算的球局不允许再核销（避免同一球局重复结算，需更正走申诉）
    6. 逐条返回结果（成功/跳过/失败 + 原因），前端可精确提示每个人
====================================================================
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import CheckinStatus, CheckinType, GameStatus, RegistrationStatus, SettleStatus
from app.core.exceptions import ConflictException
from app.models import CheckinRecord, Game, Registration, User
from app.services import reputation as reputation_service
from app.services.game import effective_checkin_window, get_roster

logger = logging.getLogger(__name__)

# 签到状态中文文案
CHECKIN_STATUS_TEXT = {
    CheckinStatus.NOT_CHECKED: "未签到",
    CheckinStatus.CHECKED: "已签到",
    CheckinStatus.LATE: "迟到",
    CheckinStatus.ABSENT: "缺席",
    CheckinStatus.LEAVE: "已请假",
}


@dataclass
class VerifyItem:
    """单个用户的核销结果"""

    user_id: int
    nickname: str | None = None
    ok: bool = False              # 本次是否成功核销
    skipped: bool = False         # 是否因「已核销/已请假」被跳过
    reason: str | None = None     # 失败/跳过的原因（可直接展示给发起人）
    checkin_status: int | None = None
    checkin_status_text: str | None = None
    credit_before: int | None = None
    credit_delta: int | None = None
    credit_after: int | None = None
    banned: bool = False          # 本次结算后是否触发小黑屋
    ban_end_time: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "nickname": self.nickname,
            "ok": self.ok,
            "skipped": self.skipped,
            "reason": self.reason,
            "checkin_status": self.checkin_status,
            "checkin_status_text": self.checkin_status_text,
            "credit_before": self.credit_before,
            "credit_delta": self.credit_delta,
            "credit_after": self.credit_after,
            "banned": self.banned,
            "ban_end_time": self.ban_end_time.isoformat() if self.ban_end_time else None,
        }


@dataclass
class VerifyResult:
    """批量核销结果"""

    game_id: int
    verified_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    items: list[VerifyItem] = field(default_factory=list)
    checkin_window: tuple[datetime, datetime] | None = None

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "verified_count": self.verified_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "checkin_open_at": self.checkin_window[0].isoformat() if self.checkin_window else None,
            "checkin_close_at": self.checkin_window[1].isoformat() if self.checkin_window else None,
            "items": [item.to_dict() for item in self.items],
        }


# ==================================================================
# 核销前置校验
# ==================================================================
def assert_verifiable(game: Game, now: datetime | None = None) -> tuple[datetime, datetime]:
    """
    校验球局当前是否允许核销，返回核销窗口 (open_at, close_at)。
    抛 ConflictException 时 message 就是可直接展示给发起人的提示。
    """
    now = now or datetime.now()

    if game.status == GameStatus.CANCELED:
        raise ConflictException("该球局已取消，无法核销签到")
    if game.settle_status != SettleStatus.PENDING:
        raise ConflictException("该球局已完成结算，无法再核销；如需更正请联系管理员申诉")

    open_at, close_at = effective_checkin_window(game)
    if now < open_at:
        raise ConflictException(f"核销尚未开放，{open_at:%m-%d %H:%M} 起可核销（开球前 {int((game.start_time - open_at).total_seconds() // 60)} 分钟）")
    return open_at, close_at


def judge_checkin_status(now: datetime, close_at: datetime, as_late: bool | None = None) -> int:
    """
    判定本次核销应记为「正常签到」还是「迟到」：
        - 发起人显式指定 as_late 时以其为准（人工补签场景）
        - 否则超过核销截止时间即为迟到
    """
    if as_late is not None:
        return CheckinStatus.LATE if as_late else CheckinStatus.CHECKED
    return CheckinStatus.LATE if now > close_at else CheckinStatus.CHECKED


# ==================================================================
# 核销主流程
# ==================================================================
async def verify_checkin(
    db: AsyncSession,
    *,
    game: Game,
    operator: User,
    user_ids: list[int] | None = None,
    verify_all: bool = False,
    as_late: bool | None = None,
    remark: str | None = None,
    commit: bool = True,
) -> VerifyResult:
    """
    发起人为到场用户核销签到。

    :param user_ids: 指定要核销的用户ID列表
    :param verify_all: True 表示核销该球局所有「已报名但未核销」的用户
    :param as_late: 显式指定记为迟到（None=按核销时间自动判定）
    :param remark: 备注（写入签到记录，便于事后追溯）
    """
    now = datetime.now()
    open_at, close_at = assert_verifiable(game, now)

    # 1) 组织核销对象
    formal_pairs = await _formal_registrations(db, game.id)
    pending = {reg.user_id: (reg, user) for reg, user in formal_pairs}

    if verify_all:
        targets = list(pending.keys())
    else:
        # 去重且保持传入顺序
        targets = list(dict.fromkeys(user_ids or []))
    if not targets:
        raise ConflictException("没有需要核销的用户")

    # 2) 批量取签到记录
    records = (
        await db.execute(
            select(CheckinRecord).where(
                CheckinRecord.game_id == game.id, CheckinRecord.user_id.in_(targets)
            )
        )
    ).scalars().all()
    record_map = {r.user_id: r for r in records}

    result = VerifyResult(game_id=game.id, checkin_window=(open_at, close_at))

    # 3) 逐个核销
    for user_id in targets:
        pair = pending.get(user_id)
        if pair is None:
            result.failed_count += 1
            result.items.append(
                VerifyItem(user_id=user_id, ok=False, reason="该用户未报名此球局或已退出，无法核销")
            )
            continue

        _reg, target_user = pair
        record = record_map.get(user_id)

        skip_reason = _skip_reason(record)
        if skip_reason:
            result.skipped_count += 1
            result.items.append(
                VerifyItem(
                    user_id=user_id,
                    nickname=target_user.nickname,
                    ok=False,
                    skipped=True,
                    reason=skip_reason,
                    checkin_status=record.checkin_status if record else None,
                    checkin_status_text=CHECKIN_STATUS_TEXT.get(
                        CheckinStatus(record.checkin_status) if record else CheckinStatus.NOT_CHECKED
                    ),
                    credit_delta=record.credit_delta if record else 0,
                )
            )
            continue

        # 3.1 标记到场状态
        checkin_status = judge_checkin_status(now, close_at, as_late)
        if record is None:  # 兜底：历史数据可能缺少签到记录
            record = CheckinRecord(game_id=game.id, user_id=user_id, settled=0)
            db.add(record)

        record.checkin_status = checkin_status
        record.checkin_type = CheckinType.MANUAL          # 3-发起人核销
        record.checkin_time = now
        record.checkin_operator_id = operator.id          # 记录是谁核销的，便于追溯
        if remark:
            record.remark = remark
        await db.flush()

        # 3.2 ★触发惰性结算（只结算本球局该用户的待结算记录）
        #     结算内部会把该用户的 AI 画像标记为待重算（trigger=checkin）
        settle = await reputation_service.settle_user_pending(
            db, user_id=user_id, game_id=game.id, profile_trigger="checkin", commit=False
        )

        item = VerifyItem(
            user_id=user_id,
            nickname=target_user.nickname,
            ok=True,
            checkin_status=checkin_status,
            checkin_status_text=CHECKIN_STATUS_TEXT.get(CheckinStatus(checkin_status)),
            credit_before=settle.credit_before if settle else target_user.credit_score,
            credit_delta=settle.credit_delta if settle else 0,
            credit_after=settle.credit_after if settle else target_user.credit_score,
            banned=settle.banned if settle else False,
            ban_end_time=settle.ban_end_time if settle else None,
        )
        result.verified_count += 1
        result.items.append(item)

    # 4) 全部核销完成且无未到场者时，可顺手把「报名截止」推进为「进行中」
    if game.status == GameStatus.SIGNUP_CLOSED:
        game.status = GameStatus.PLAYING

    if commit:
        await db.commit()

    logger.info(
        "球局 %s 核销完成：成功 %d / 跳过 %d / 失败 %d（操作人 %s）",
        game.id, result.verified_count, result.skipped_count, result.failed_count, operator.id,
    )
    return result


async def _formal_registrations(
    db: AsyncSession, game_id: int
) -> list[tuple[Registration, User]]:
    """该球局的正式报名者（状态=SIGNED）及其用户信息"""
    stmt = (
        select(Registration, User)
        .join(User, User.id == Registration.user_id)
        .where(
            Registration.game_id == game_id,
            Registration.status == RegistrationStatus.SIGNED,
        )
    )
    return [(reg, user) for reg, user in (await db.execute(stmt)).all()]


def _skip_reason(record: CheckinRecord | None) -> str | None:
    """判断某条签到记录是否应跳过核销，返回原因"""
    if record is None:
        return None
    if record.settled == 1 and record.checkin_status in (CheckinStatus.CHECKED, CheckinStatus.LATE):
        return "该用户已核销过，无需重复核销"
    if record.checkin_status == CheckinStatus.LEAVE:
        return "该用户已请假，无需核销"
    if record.checkin_status == CheckinStatus.ABSENT:
        return "该用户已被判定为缺席，如需更正请联系管理员"
    if record.settled == 1:
        return "该签到记录已结算，无法重复核销"
    return None


# ==================================================================
# 核销名单（发起人视图）
# ==================================================================
async def get_verify_roster(db: AsyncSession, game: Game, operator: User) -> dict:
    """
    核销名单：正式报名者 + 签到状态 + 到场统计。
    仅发起人可查看全体名单（含他人信誉分），普通用户请用球局详情里的 my_checkin_status。
    """
    from app.services.game import assert_is_creator  # 局部导入避免循环引用

    assert_is_creator(game, operator)
    roster = await get_roster(db, game)
    open_at, close_at = effective_checkin_window(game)

    return {
        "game_id": game.id,
        "title": game.title,
        "status": game.status,
        "settle_status": game.settle_status,
        "start_time": game.start_time.isoformat(),
        "checkin_open_at": open_at.isoformat(),
        "checkin_close_at": close_at.isoformat(),
        "checkin_open": datetime.now() >= open_at and game.settle_status == SettleStatus.PENDING,
        "signed_count": roster.signed_count,
        "checked_count": roster.checked_count,
        "late_count": roster.late_count,
        "absent_count": roster.absent_count,
        "not_checked_count": roster.not_checked_count,
        "waitlist_count": roster.waitlist_count,
        "members": [
            {
                "user_id": item.user_id,
                "nickname": item.nickname,
                "avatar_url": item.avatar_url,
                "credit_score": item.credit_score,
                "registration_status": item.registration.status,
                "is_waitlist": item.registration.is_waitlist,
                "checkin_status": item.checkin_status,
                "checkin_status_text": CHECKIN_STATUS_TEXT.get(
                    CheckinStatus(item.checkin_status) if item.checkin_status is not None else CheckinStatus.NOT_CHECKED
                ),
                "checkin_time": item.checkin_time.isoformat() if item.checkin_time else None,
                "credit_delta": item.credit_delta,
                "settled": item.settled,
            }
            for item in roster.items
        ],
    }


def status_text(status: int | None) -> str:
    """签到状态文案（供其它模块复用）"""
    if status is None:
        return CHECKIN_STATUS_TEXT[CheckinStatus.NOT_CHECKED]
    return CHECKIN_STATUS_TEXT.get(CheckinStatus(status), "未知")


# ==================================================================
# 规则1：球局「已结束」触发缺席判定 + 定时兜底扫描
# ==================================================================
async def finalize_game(
    db: AsyncSession,
    game: Game,
    *,
    operator_id: int = 0,
    commit: bool = True,
) -> dict:
    """
    结束球局并触发缺席判定（幂等：已结算的球局会直接返回）。

    调用场景：
        1) 发起人主动「结束球局」→ POST /api/v1/game/{id}/finish
        2) 定时兜底扫描发现「已过结束时间但未结算」→ scan_overdue_games()

    判定口径（规则1）：已报名 + 未签到 + 未请假 → 记为缺席
                      已核销/已签到/已请假的人不会被判缺席
    """
    game.status = GameStatus.FINISHED
    result = await reputation_service.settle_on_absent_judgement(
        db, game_id=game.id, operator_id=operator_id, auto_prune=True, commit=False
    )
    if commit:
        await db.commit()
    logger.info("球局 %s 已结束并完成缺席判定：缺席 %s 人", game.id, result.get("absent_count"))
    return result


def _overdue_condition(now: datetime):
    """兜底扫描条件：已过结束时间（可含宽限）且仍未结算"""
    deadline = now - timedelta(minutes=settings.ABSENT_SCAN_GRACE_MINUTES)
    return (Game.end_time < deadline,)


async def scan_overdue_games(
    db: AsyncSession,
    *,
    limit: int | None = None,
    now: datetime | None = None,
) -> dict:
    """
    定时兜底扫描（默认每小时一次，见 app/main.py）：防止球局忘记关闭导致漏判。

    扫描对象：is_deleted=0 且 settle_status=待结算，且已过结束时间的球局
              （包含「报名中/报名截止/进行中」——发起人忘了点结束也算）
    处理方式：逐个结束球局并执行缺席判定（缺席 → 扣 10 分 → 自动进小黑屋 3 天）

    :return: {"scanned": n, "finalized": [...], "absent_total": n}
    """
    now = now or datetime.now()
    batch = limit or settings.ABSENT_SCAN_BATCH_SIZE

    stmt = (
        select(Game)
        .where(
            Game.is_deleted == 0,
            Game.settle_status == SettleStatus.PENDING,
            Game.status.in_(
                [
                    int(GameStatus.SIGNING),
                    int(GameStatus.SIGNUP_CLOSED),
                    int(GameStatus.PLAYING),
                ]
            ),
            *_overdue_condition(now),
        )
        .order_by(Game.end_time.asc())
        .limit(batch)
    )
    games = list((await db.execute(stmt)).scalars().all())

    finalized: list[dict] = []
    absent_total = 0
    for game in games:
        try:
            result = await finalize_game(db, game, operator_id=0, commit=False)
            absent_total += result.get("absent_count", 0)
            finalized.append(
                {
                    "game_id": game.id,
                    "title": game.title,
                    "end_time": game.end_time.isoformat(),
                    "absent_count": result.get("absent_count", 0),
                    "settled_users": len(result.get("settled_users", [])),
                }
            )
        except Exception as exc:  # noqa: BLE001 - 单个球局失败不能阻断整轮扫描
            logger.error("兜底判定失败 game_id=%s：%s", game.id, exc)
            await db.rollback()

    if finalized:
        await db.commit()
        logger.warning("兜底扫描完成：处理 %d 场球局，缺席 %d 人次", len(finalized), absent_total)
    return {"scanned": len(games), "finalized": finalized, "absent_total": absent_total}
