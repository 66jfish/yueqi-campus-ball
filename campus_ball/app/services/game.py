"""
球局服务：发起 / 列表 / 详情 / 报名 / 退出 / 名单
====================================================================
核心业务规则（全部在服务层实现，接口层只做参数校验）：

1) 发起球局
   - 时间合法性：结束必须晚于开始
   - ★同场地同时段冲突校验：同一(校区, 场地)在 [start, end) 有重叠的未取消球局 → 拒绝
   - ★发起人自身时间冲突校验：发起人同一时段已报名别的球局 → 拒绝
   - 自动补默认签到窗口（未填时按配置推算），供后续核销使用

2) 球局列表
   - 支持运动类型 / 校区 / 状态 / 关键词 / 日期区间 / 只看未满 等筛选 + 分页
   - 批量取发起人昵称、候补人数、当前用户报名状态，避免 N+1

3) 报名
   - 球局状态、报名截止、重复报名、门槛（信誉分/球技/性别）
   - ★用户时间冲突校验：同一时段已正式报名其它球局 → 拒绝
   - ★球局未满校验：满员后按配置进入候补队列或直接拒绝

4) 退出球局
   - 开球后禁止退出；可配置「开球前 N 分钟内禁止退出」
   - 退出正式名额后自动从候补队列补位（补位者同样生成待结算签到记录）

5) 签到核销
   - 见 app/services/checkin.py（发起人核销 → 触发惰性结算）
====================================================================
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import (
    MATCH_SCORE_PLACEHOLDER,
    CheckinStatus,
    FeeType,
    GameStatus,
    RegistrationStatus,
    SettleStatus,
    SportType,
)
from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException, ParamException
from app.models import CheckinRecord, Game, Registration, User
from app.core.constants import skill_text
from app.schemas import GameCreateRequest, SignupResult
from app.services import ai_profile as ai_profile_service

logger = logging.getLogger(__name__)

# 不参与「场地/时间冲突」判定的球局状态：已取消的球局不占场地
CONFLICT_EXCLUDED_STATUSES = (GameStatus.CANCELED,)


# ==================================================================
# 出参结构
# ==================================================================
@dataclass
class GameRow:
    """列表/详情用的聚合行（球局 + 关联信息，避免接口层再查库）"""

    game: Game
    creator_nickname: str | None = None
    creator_credit_score: int | None = None
    waitlist_count: int = 0
    # AI 匹配分：按用户画像实时计算（未登录时为静态基线分）
    match_score: float = MATCH_SCORE_PLACEHOLDER
    match_reason: str | None = None
    my_registration_status: int | None = None  # 当前登录用户在该球局的报名状态（未报名为 None）
    my_checkin_status: int | None = None


@dataclass
class ExitResult:
    """退出球局结果"""

    registration: Registration
    promoted_user_id: int | None = None  # 被候补补位上来的用户ID
    current_players: int = 0
    message: str = "已退出球局"


@dataclass
class RosterItem:
    """核销名单中的一行"""

    registration: Registration
    user_id: int
    nickname: str = ""
    avatar_url: str | None = None
    credit_score: int = 100
    checkin_status: int | None = None
    checkin_time: datetime | None = None
    credit_delta: int = 0
    settled: int = 0


@dataclass
class RosterResult:
    """球局核销名单（含到场统计）"""

    game: Game
    items: list[RosterItem] = field(default_factory=list)
    signed_count: int = 0
    checked_count: int = 0
    late_count: int = 0
    absent_count: int = 0
    not_checked_count: int = 0
    waitlist_count: int = 0


# ==================================================================
# 内部工具
# ==================================================================
def _overlap_condition(start_time: datetime, end_time: datetime, buffer_minutes: int = 0):
    """
    生成「时间段重叠」的 SQL 条件（左闭右开）：
        已有.start < 新.end   且  已有.end > 新.start

    缓冲（buffer_minutes）的算法放在 Python 侧完成，不写成 SQL 的列运算：
        已有.start < 新.end + 缓冲   ⇔   已有.start < (新.end + 缓冲)
        已有.end + 缓冲 > 新.start   ⇔   已有.end > (新.start - 缓冲)
    这样既能保证「两场之间至少留出 N 分钟」，也避免了不同数据库
    对「日期列 + 时间间隔」支持不一致的问题（MySQL 需 DATE_ADD，SQLite 无原生支持）。
    """
    buffer = timedelta(minutes=buffer_minutes)
    return (Game.start_time < end_time + buffer, Game.end_time > start_time - buffer)


async def check_venue_conflict(
    db: AsyncSession,
    *,
    venue_name: str | None,
    campus: str | None,
    start_time: datetime,
    end_time: datetime,
    exclude_game_id: int | None = None,
) -> Game | None:
    """
    ★同场地同时段冲突校验
    返回冲突的球局（存在冲突）或 None（无冲突）。
    场地名为空时不做校验（例如只是「操场见」这类非固定场地）。
    """
    if not venue_name:
        return None

    conditions = [
        Game.is_deleted == 0,
        Game.venue_name == venue_name,
        Game.status.notin_([int(s) for s in CONFLICT_EXCLUDED_STATUSES]),
        *_overlap_condition(start_time, end_time, settings.GAME_CONFLICT_BUFFER_MINUTES),
    ]
    # 校区做 NULL 安全比较
    if campus is None:
        conditions.append(Game.campus.is_(None))
    else:
        conditions.append(Game.campus == campus)
    if exclude_game_id:
        conditions.append(Game.id != exclude_game_id)

    stmt = select(Game).where(*conditions).order_by(Game.start_time.asc()).limit(1)
    return (await db.execute(stmt)).scalars().first()


async def check_user_time_conflict(
    db: AsyncSession,
    *,
    user_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_game_id: int | None = None,
    include_waitlist: bool = False,
) -> tuple[Game | None, Registration | None]:
    """
    ★用户时间冲突校验：该用户在 [start, end) 是否已有其它球局安排。
    默认只统计「正式报名」（候补不占用时间），可用 include_waitlist=True 一并统计。

    :return: (冲突球局, 对应报名记录)，无冲突返回 (None, None)
    """
    statuses = [RegistrationStatus.SIGNED]
    if include_waitlist:
        statuses.append(RegistrationStatus.WAITLIST)

    conditions = [
        Registration.user_id == user_id,
        Registration.status.in_([int(s) for s in statuses]),
        Game.is_deleted == 0,
        Game.status.notin_([int(s) for s in CONFLICT_EXCLUDED_STATUSES]),
        *_overlap_condition(start_time, end_time, settings.GAME_CONFLICT_BUFFER_MINUTES),
    ]
    if exclude_game_id:
        conditions.append(Game.id != exclude_game_id)

    stmt = (
        select(Game, Registration)
        .join(Game, Game.id == Registration.game_id)
        .where(*conditions)
        .order_by(Game.start_time.asc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if not row:
        return None, None
    return row[0], row[1]


def default_checkin_window(start_time: datetime) -> tuple[datetime, datetime]:
    """
    未配置签到窗口时按配置推算：
        开放时间 = 开球前 CHECKIN_OPEN_BEFORE_MINUTES 分钟
        截止时间 = 开球后 CHECKIN_LATE_AFTER_MINUTES 分钟（超过即为迟到）
    """
    return (
        start_time - timedelta(minutes=settings.CHECKIN_OPEN_BEFORE_MINUTES),
        start_time + timedelta(minutes=settings.CHECKIN_LATE_AFTER_MINUTES),
    )


def effective_checkin_window(game: Game) -> tuple[datetime, datetime]:
    """球局实际的核销窗口（优先用球局自身配置，否则按默认规则推算）"""
    open_at, close_at = default_checkin_window(game.start_time)
    return game.checkin_start_time or open_at, game.checkin_end_time or close_at


def _format_range(game: Game) -> str:
    """把球局时间格式化成易于阅读的提示文案"""
    return f"{game.start_time:%m-%d %H:%M}~{game.end_time:%H:%M}"


# ==================================================================
# 1. 发起球局
# ==================================================================
async def create_game(db: AsyncSession, creator: User, payload: GameCreateRequest) -> Game:
    """
    发起球局。
    校验顺序：时间合法性 → 场地冲突 → 发起人时间冲突 → 落库（自动补签到窗口）
    """
    if payload.end_time <= payload.start_time:
        raise ParamException("结束时间必须晚于开球时间")

    now = datetime.now()
    if payload.start_time < now - timedelta(hours=1):
        raise ParamException("开球时间不能早于当前时间")

    # ★同场地同时段冲突
    conflict = await check_venue_conflict(
        db,
        venue_name=payload.venue_name,
        campus=payload.campus,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )
    if conflict is not None:
        raise ConflictException(
            f"场地冲突：{conflict.venue_name} 在 {_format_range(conflict)} 已被「{conflict.title}」占用，"
            f"请更换场地或调整时间"
        )

    # ★发起人自身时间冲突（同时报了别的球局）
    my_conflict, _ = await check_user_time_conflict(
        db, user_id=creator.id, start_time=payload.start_time, end_time=payload.end_time
    )
    if my_conflict is not None:
        raise ConflictException(
            f"时间冲突：您在同一时段已加入「{my_conflict.title}」（{_format_range(my_conflict)}），"
            f"无法再发起球局"
        )

    data = payload.model_dump(exclude_none=True)

    # 自动补默认签到窗口，保证核销有据可依
    open_at, close_at = default_checkin_window(payload.start_time)
    data.setdefault("checkin_start_time", open_at)
    data.setdefault("checkin_end_time", close_at)

    game = Game(
        creator_id=creator.id,
        **data,
        status=GameStatus.SIGNING,
        settle_status=SettleStatus.PENDING,
        current_players=0,
    )
    db.add(game)
    await db.flush()

    # 发起人自动占一个名额（发起人默认参加），并预生成待结算签到记录
    db.add(
        Registration(
            game_id=game.id,
            user_id=creator.id,
            status=RegistrationStatus.SIGNED,
            is_waitlist=0,
            signup_time=now,
            credit_snapshot=creator.credit_score,
        )
    )
    db.add(
        CheckinRecord(
            game_id=game.id,
            user_id=creator.id,
            checkin_status=CheckinStatus.NOT_CHECKED,
            settled=0,
        )
    )
    game.current_players = 1

    await db.commit()
    await db.refresh(game)
    logger.info("用户 %s 发起球局 %s：%s @%s", creator.id, game.id, game.title, game.venue_name)
    return game


# ==================================================================
# 2. 球局列表 / 3. 球局详情
# ==================================================================
async def list_games(
    db: AsyncSession,
    *,
    sport_type: int | None = None,
    campus: str | None = None,
    venue_name: str | None = None,
    status: int | None = None,
    keyword: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    creator_id: int | None = None,
    only_available: bool = False,
    sort_desc: bool = False,
    page: int = 1,
    page_size: int = 10,
    current_user_id: int | None = None,
    with_match_score: bool = True,
) -> tuple[list[GameRow], int]:
    """
    球局列表（筛选 + 分页）。

    :param current_user_id: 登录用户ID，用于返回「我的报名状态」与个性化 match_score
    :param with_match_score: 是否按用户画像计算 match_score（未登录时自动退化为静态基线分）
    :return: (当前页数据, 总条数)
    """
    conditions = [Game.is_deleted == 0]
    if sport_type is not None:
        conditions.append(Game.sport_type == sport_type)
    if campus:
        conditions.append(Game.campus == campus)
    if venue_name:
        conditions.append(Game.venue_name.like(f"%{venue_name}%"))
    if status is not None:
        conditions.append(Game.status == status)
    if keyword:
        conditions.append(
            or_(Game.title.like(f"%{keyword}%"), Game.description.like(f"%{keyword}%"))
        )
    if start_date is not None:
        conditions.append(Game.start_time >= start_date)
    if end_date is not None:
        conditions.append(Game.start_time <= end_date)
    if creator_id is not None:
        conditions.append(Game.creator_id == creator_id)
    if only_available:
        # 只看还有名额的：报名中的球局 + 未满
        conditions.append(Game.status == GameStatus.SIGNING)
        conditions.append(Game.current_players < Game.max_players)

    total = (await db.execute(select(func.count()).select_from(Game).where(*conditions))).scalar_one()

    order = Game.start_time.desc() if sort_desc else Game.start_time.asc()
    stmt = select(Game).where(*conditions).order_by(order).offset((page - 1) * page_size).limit(page_size)
    games = list((await db.execute(stmt)).scalars().all())
    if not games:
        return [], total

    game_ids = [g.id for g in games]
    creator_ids = {g.creator_id for g in games}

    # 批量取发起人昵称与信誉分（避免 N+1）
    creator_rows = (
        await db.execute(
            select(User.id, User.nickname, User.credit_score).where(
                User.id.in_(creator_ids), User.is_deleted == 0
            )
        )
    ).all()
    creator_map = {uid: (nickname, credit) for uid, nickname, credit in creator_rows}

    # 批量取候补人数
    waitlist_rows = (
        await db.execute(
            select(Registration.game_id, func.count())
            .where(
                Registration.game_id.in_(game_ids),
                Registration.status == RegistrationStatus.WAITLIST,
            )
            .group_by(Registration.game_id)
        )
    ).all()
    waitlist_map = {gid: cnt for gid, cnt in waitlist_rows}

    # 批量取当前用户在这些球局的报名与签到状态
    my_reg_map: dict[int, int] = {}
    my_checkin_map: dict[int, int] = {}
    my_busy_ranges: list[tuple[int, datetime, datetime]] = []
    if current_user_id:
        reg_rows = (
            await db.execute(
                select(Registration.game_id, Registration.status).where(
                    Registration.game_id.in_(game_ids),
                    Registration.user_id == current_user_id,
                )
            )
        ).all()
        my_reg_map = {gid: status for gid, status in reg_rows}
        checkin_rows = (
            await db.execute(
                select(CheckinRecord.game_id, CheckinRecord.checkin_status).where(
                    CheckinRecord.game_id.in_(game_ids),
                    CheckinRecord.user_id == current_user_id,
                )
            )
        ).all()
        my_checkin_map = {gid: st for gid, st in checkin_rows}

    # ---------- AI 画像驱动的 match_score ----------
    match_context = None
    if with_match_score and current_user_id:
        from app.services import ai_profile as ai_profile_service  # 局部导入避免循环引用

        match_context = await ai_profile_service.build_match_context(db, current_user_id)
        # 我已在其它球局的忙碌时段（用于「时间冲突」降权提示）
        busy_rows = (
            await db.execute(
                select(Game.id, Game.start_time, Game.end_time)
                .join(Registration, Registration.game_id == Game.id)
                .where(
                    Registration.user_id == current_user_id,
                    Registration.status == RegistrationStatus.SIGNED,
                    Game.is_deleted == 0,
                    Game.status.notin_([int(s) for s in CONFLICT_EXCLUDED_STATUSES]),
                )
            )
        ).all()
        my_busy_ranges = [(gid, st, et) for gid, st, et in busy_rows]

    rows = []
    for game in games:
        nickname, credit = creator_map.get(game.creator_id, (None, None))
        row = GameRow(
            game=game,
            creator_nickname=nickname,
            creator_credit_score=credit,
            waitlist_count=waitlist_map.get(game.id, 0),
            my_registration_status=my_reg_map.get(game.id),
            my_checkin_status=my_checkin_map.get(game.id),
        )
        if match_context is not None:
            from app.services import ai_profile as ai_profile_service

            features, profile = match_context
            conflict = any(
                gid != game.id and st < game.end_time and et > game.start_time
                for gid, st, et in my_busy_ranges
            )
            result = ai_profile_service.compute_match_score(
                features=features,
                profile=profile,
                game_skill_limit=game.skill_level_limit or 0,
                game_sport_type=game.sport_type,
                is_full=(game.current_players >= game.max_players),
                time_conflict=conflict,
                game_min_reputation=game.min_credit_score or 0,
            )
            row.match_score = result["match_score"]
            row.match_reason = result["match_reason"]
        elif current_user_id is None:
            # 未登录：返回静态基线分，并说明原因（避免出现 null 让前端困惑）
            row.match_reason = "未登录，返回通用推荐分"
        rows.append(row)
    return rows, total


async def maybe_finalize_overdue(db: AsyncSession, game: Game) -> bool:
    """
    ★惰性兜底：读取球局时，若「已过结束时间但仍未结算」，就地完成缺席判定。

    为什么需要它：
        Vercel Serverless 无法常驻定时任务，若只靠 Cron，最坏情况下漏判要等到
        第二天 03:00 才补上（期间被放鸽子的球局信誉分未更新）。
        把判定挂在「读取球局」这个高频动作上，等于「有人看就自动结算」，
        与小黑屋的惰性解封思路一致 —— 正确性不依赖任何后台任务。

    幂等：settle_status 会挡住重复判定；异常只记录日志，绝不影响读取接口。
    """
    if game.settle_status != SettleStatus.PENDING or game.status == GameStatus.CANCELED:
        return False
    grace = timedelta(minutes=settings.ABSENT_SCAN_GRACE_MINUTES)
    if game.end_time + grace > datetime.now():
        return False

    from app.services import checkin as checkin_service  # 局部导入，避免与 checkin 模块循环引用

    try:
        await checkin_service.finalize_game(db, game, operator_id=0)
        logger.info("惰性补判缺席：球局 %s（结束于 %s）已就地结算", game.id, game.end_time)
        return True
    except Exception as exc:  # noqa: BLE001 - 兜底逻辑不能影响正常读取
        logger.warning("惰性补判缺席失败 game_id=%s：%s", game.id, exc)
        await db.rollback()
        return False


async def get_game(db: AsyncSession, game_id: int) -> Game:
    """按ID取球局（不存在抛 404）"""
    game = await db.get(Game, game_id)
    if not game or game.is_deleted:
        raise NotFoundException("球局不存在或已删除")
    return game


async def get_game_row(db: AsyncSession, game: Game, current_user_id: int | None = None) -> GameRow:
    """组装球局详情所需的关联信息（读取前先做一次惰性补判，见 maybe_finalize_overdue）"""
    await maybe_finalize_overdue(db, game)

    creator = await db.get(User, game.creator_id)
    waitlist_count = (
        await db.execute(
            select(func.count())
            .select_from(Registration)
            .where(Registration.game_id == game.id, Registration.status == RegistrationStatus.WAITLIST)
        )
    ).scalar_one()

    my_status = None
    my_checkin = None
    if current_user_id:
        reg = (
            await db.execute(
                select(Registration).where(
                    Registration.game_id == game.id, Registration.user_id == current_user_id
                )
            )
        ).scalars().first()
        my_status = reg.status if reg else None
        record = (
            await db.execute(
                select(CheckinRecord).where(
                    CheckinRecord.game_id == game.id, CheckinRecord.user_id == current_user_id
                )
            )
        ).scalars().first()
        my_checkin = record.checkin_status if record else None

    return GameRow(
        game=game,
        creator_nickname=creator.nickname if creator else None,
        creator_credit_score=creator.credit_score if creator else None,
        waitlist_count=waitlist_count,
        my_registration_status=my_status,
        my_checkin_status=my_checkin,
    )


# ==================================================================
# 4. 报名加入球局
# ==================================================================
async def sign_up(
    db: AsyncSession, game_id: int, user: User, skill_level: int | None = None
) -> SignupResult:
    """
    报名加入球局。
    校验顺序（异常提示按此顺序给出，前端可直接展示）：
        ★水平必填 → 球局可报名 → 未截止 → 未重复报名 → 门槛（信誉分/球技/性别）
        → ★时间冲突 → ★名额
    :param skill_level: ★该球类自评水平（1-5，必填）
    """
    if skill_level is None:
        raise ParamException("请先选择你在该球类的水平（新手/初级/中级/高级/大神）后再报名")
    game = await get_game(db, game_id)
    now = datetime.now()

    # 1) 球局状态
    if game.status == GameStatus.CANCELED:
        raise ConflictException("该球局已取消，无法报名")
    if game.status != GameStatus.SIGNING:
        raise ConflictException(f"该球局当前状态为「{_status_text(game.status)}」，不可报名")

    # 2) 报名截止
    if game.signup_deadline and now > game.signup_deadline:
        raise ConflictException(f"报名已于 {game.signup_deadline:%m-%d %H:%M} 截止")
    if now >= game.start_time:
        raise ConflictException("球局已开始，无法报名")

    # 3) 重复报名
    existing = (
        await db.execute(
            select(Registration).where(
                Registration.game_id == game_id, Registration.user_id == user.id
            )
        )
    ).scalars().first()
    if existing and existing.status in (RegistrationStatus.SIGNED, RegistrationStatus.WAITLIST):
        if existing.status == RegistrationStatus.WAITLIST:
            raise ConflictException(f"您已在该球局的候补队列中（第 {existing.waitlist_order} 位）")
        raise ConflictException("您已报名该球局，无需重复报名")

    # 4) 门槛校验
    if game.min_credit_score and user.credit_score < game.min_credit_score:
        raise ConflictException(
            f"该球局要求信誉分不低于 {game.min_credit_score}，您当前 {user.credit_score} 分，暂无法报名"
        )
    # ★按「报名时自评的水平」校验球局门槛（不再依赖注册时的水平）
    if game.skill_level_limit and int(skill_level) < game.skill_level_limit:
        raise ConflictException(
            f"该球局最低水平要求为「{skill_text(game.skill_level_limit)}」，"
            f"您自评「{skill_text(skill_level)}」，暂不达标，无法报名"
        )
    if game.gender_limit and user.gender != game.gender_limit:
        limit_text = "仅限男生" if game.gender_limit == 1 else "仅限女生"
        raise ConflictException(f"该球局{limit_text}，您不符合报名条件")

    # 5) ★用户时间冲突
    conflict_game, _ = await check_user_time_conflict(
        db,
        user_id=user.id,
        start_time=game.start_time,
        end_time=game.end_time,
        exclude_game_id=game.id,
    )
    if conflict_game is not None:
        raise ConflictException(
            f"时间冲突：您在 {_format_range(conflict_game)} 已加入「{conflict_game.title}」，"
            f"无法再报名同时段的球局"
        )

    # 6) ★名额校验（满员 → 候补 或 直接拒绝）
    slots_left = game.max_players - game.current_players
    is_waitlist = slots_left <= 0
    if is_waitlist and not settings.GAME_SIGNUP_ALLOW_WAITLIST:
        raise ConflictException(f"球局已满（{game.current_players}/{game.max_players}），请关注后续空位")

    if existing is None:
        existing = Registration(game_id=game_id, user_id=user.id)
        db.add(existing)

    if is_waitlist:
        # 候补位次必须在改动本条记录之前算，并排除自己，
        # 否则结果会依赖 session 的 autoflush 行为（生产 autoflush=False、测试默认 True 会算出不同名次）
        wait_count = (
            await db.execute(
                select(func.count())
                .select_from(Registration)
                .where(
                    Registration.game_id == game_id,
                    Registration.status == RegistrationStatus.WAITLIST,
                    Registration.user_id != user.id,
                )
            )
        ).scalar_one()
        existing.waitlist_order = wait_count + 1

    existing.status = RegistrationStatus.WAITLIST if is_waitlist else RegistrationStatus.SIGNED
    existing.is_waitlist = 1 if is_waitlist else 0
    existing.signup_time = now
    existing.cancel_time = None
    existing.cancel_reason = None
    existing.credit_snapshot = user.credit_score
    existing.skill_level = int(skill_level)  # ★记录本次报名自评的水平

    if not is_waitlist:
        existing.waitlist_order = 0
        game.current_players += 1
        await _ensure_checkin_record(db, game.id, user.id, existing.id)

    await db.commit()
    await db.refresh(existing)

    message = (
        f"球局已满，您已进入候补队列（第 {existing.waitlist_order} 位）"
        if is_waitlist
        else f"报名成功（{game.current_players}/{game.max_players}）"
    )
    return SignupResult(
        registration=existing,
        is_waitlist=is_waitlist,
        current_players=game.current_players,
        message=message,
    )


# ==================================================================
# 5. 退出球局
# ==================================================================
async def exit_game(
    db: AsyncSession, game_id: int, user: User, reason: str | None = None
) -> ExitResult:
    """
    退出球局（取消报名）。
    - 开球后不可退出；开球前 N 分钟内是否可退出由 GAME_CANCEL_DEADLINE_MINUTES 控制
    - 退出正式名额后自动从候补队列补位一位，并返回补位者ID
    """
    game = await get_game(db, game_id)
    now = datetime.now()

    registration = (
        await db.execute(
            select(Registration).where(
                Registration.game_id == game_id, Registration.user_id == user.id
            )
        )
    ).scalars().first()
    if not registration or registration.status not in (
        RegistrationStatus.SIGNED,
        RegistrationStatus.WAITLIST,
    ):
        raise ConflictException("您尚未报名该球局，无需退出")

    if game.status == GameStatus.CANCELED:
        raise ConflictException("该球局已取消，无需退出")
    if now >= game.start_time:
        raise ConflictException("球局已开始，无法退出；确需退出请联系发起人")
    if settings.GAME_CANCEL_DEADLINE_MINUTES > 0:
        deadline = game.start_time - timedelta(minutes=settings.GAME_CANCEL_DEADLINE_MINUTES)
        if now > deadline:
            raise ConflictException(
                f"距开球不足 {settings.GAME_CANCEL_DEADLINE_MINUTES} 分钟，已无法退出（截止 {deadline:%m-%d %H:%M}）"
            )

    was_formal = registration.status == RegistrationStatus.SIGNED
    registration.status = RegistrationStatus.CANCELED
    registration.cancel_time = now
    registration.cancel_reason = reason

    promoted_user_id = None
    if was_formal:
        game.current_players = max(0, game.current_players - 1)
        # 退出后作废本人待结算的签到记录，避免后续被误判缺席
        await _void_checkin_record(db, game.id, user.id)
        promoted_user_id = await _promote_from_waitlist(db, game)

    # ★退出球局触发的 AI 信誉画像重算：先置脏标记（同一事务），再尝试立刻异步重算
    await ai_profile_service.mark_profile_dirty(db, [user.id], trigger="exit", commit=False)
    await db.commit()
    await db.refresh(registration)
    ai_profile_service.schedule_profile_refresh([user.id], trigger="exit")

    message = "已退出球局"
    if promoted_user_id:
        message += "，已自动通知候补球友补位"
    return ExitResult(
        registration=registration,
        promoted_user_id=promoted_user_id,
        current_players=game.current_players,
        message=message,
    )


async def _promote_from_waitlist(db: AsyncSession, game: Game) -> int | None:
    """从候补队列补位一人（顺序号最小者优先），返回补位用户ID"""
    candidate = (
        await db.execute(
            select(Registration)
            .where(
                Registration.game_id == game.id,
                Registration.status == RegistrationStatus.WAITLIST,
            )
            .order_by(Registration.waitlist_order.asc(), Registration.signup_time.asc())
            .limit(1)
        )
    ).scalars().first()
    if not candidate:
        return None

    candidate.status = RegistrationStatus.SIGNED
    candidate.is_waitlist = 0
    candidate.waitlist_order = 0
    game.current_players += 1
    await _ensure_checkin_record(db, game.id, candidate.user_id, candidate.id)
    logger.info("候补补位：球局 %s，用户 %s", game.id, candidate.user_id)
    return candidate.user_id


async def _ensure_checkin_record(
    db: AsyncSession, game_id: int, user_id: int, registration_id: int | None = None
) -> CheckinRecord:
    """保证「正式报名者」都有一条待结算的签到记录（缺席判定依赖它）"""
    record = (
        await db.execute(
            select(CheckinRecord).where(
                CheckinRecord.game_id == game_id, CheckinRecord.user_id == user_id
            )
        )
    ).scalars().first()
    if record:
        return record

    record = CheckinRecord(
        game_id=game_id,
        user_id=user_id,
        registration_id=registration_id,
        checkin_status=CheckinStatus.NOT_CHECKED,
        settled=0,
    )
    db.add(record)
    return record


async def _void_checkin_record(db: AsyncSession, game_id: int, user_id: int) -> None:
    """
    退出球局时处理签到记录：
        - 尚未结算：直接物理删除（该用户不再参与本场，不应产生缺席记录）
        - 已结算：保留（已折算过信誉分，不能抹掉流水）
    """
    record = (
        await db.execute(
            select(CheckinRecord).where(
                CheckinRecord.game_id == game_id, CheckinRecord.user_id == user_id
            )
        )
    ).scalars().first()
    if record and record.settled == 0:
        await db.delete(record)


# ==================================================================
# 6. 名单 / 权限
# ==================================================================
async def list_registrations(
    db: AsyncSession, game_id: int, *, only_formal: bool = False
) -> list[tuple[Registration, User]]:
    """球局报名名单（含候补），返回 (报名记录, 用户) 便于直接组装展示信息"""
    conditions = [Registration.game_id == game_id]
    if only_formal:
        conditions.append(Registration.status == RegistrationStatus.SIGNED)

    stmt = (
        select(Registration, User)
        .join(User, User.id == Registration.user_id)
        .where(*conditions)
        .order_by(Registration.status.asc(), Registration.waitlist_order.asc(), Registration.signup_time.asc())
    )
    return [(reg, user) for reg, user in (await db.execute(stmt)).all()]


async def get_roster(db: AsyncSession, game: Game) -> RosterResult:
    """
    核销名单：正式报名者 + 各自签到状态，并统计到场/迟到/缺席/未核销人数。
    发起人在核销页、用户在场次详情页都会用到。
    """
    pairs = await list_registrations(db, game.id, only_formal=True)
    user_ids = [user.id for _, user in pairs]
    record_map: dict[int, CheckinRecord] = {}
    if user_ids:
        records = (
            await db.execute(
                select(CheckinRecord).where(
                    CheckinRecord.game_id == game.id, CheckinRecord.user_id.in_(user_ids)
                )
            )
        ).scalars().all()
        record_map = {r.user_id: r for r in records}

    result = RosterResult(game=game, signed_count=len(pairs))
    for reg, user in pairs:
        record = record_map.get(user.id)
        status = record.checkin_status if record else None

        if status == CheckinStatus.CHECKED:
            result.checked_count += 1
        elif status == CheckinStatus.LATE:
            result.late_count += 1
        elif status == CheckinStatus.ABSENT:
            result.absent_count += 1
        elif status in (CheckinStatus.NOT_CHECKED, None):
            result.not_checked_count += 1

        result.items.append(
            RosterItem(
                registration=reg,
                user_id=user.id,
                nickname=user.nickname,
                avatar_url=user.avatar_url,
                credit_score=user.credit_score,
                checkin_status=status,
                checkin_time=record.checkin_time if record else None,
                credit_delta=record.credit_delta if record else 0,
                settled=record.settled if record else 0,
            )
        )

    result.waitlist_count = (
        await db.execute(
            select(func.count())
            .select_from(Registration)
            .where(Registration.game_id == game.id, Registration.status == RegistrationStatus.WAITLIST)
        )
    ).scalar_one()
    return result


def assert_is_creator(game: Game, user: User) -> None:
    """校验是否为球局发起人（核销、缺席判定等管理动作仅发起人可执行）"""
    if game.creator_id != user.id:
        raise ForbiddenException("只有球局发起人可以执行该操作")


def _status_text(status: int) -> str:
    """球局状态中文文案（用于异常提示，前端可直接展示）"""
    return {
        GameStatus.DRAFT: "草稿",
        GameStatus.SIGNING: "报名中",
        GameStatus.SIGNUP_CLOSED: "报名截止",
        GameStatus.PLAYING: "进行中",
        GameStatus.FINISHED: "已结束",
        GameStatus.CANCELED: "已取消",
    }.get(GameStatus(status), "未知")
