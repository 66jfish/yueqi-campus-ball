"""
失信小黑屋服务
====================================================================
规则实现对照表：
    规则2  缺席即封禁，时长固定 3 天（ban_end_time = ban_start_time + 3天）
           → apply_ban()
    规则3  封禁期间拦截写操作（发局/报名）；查询接口放行
           → is_ban_blocked_request()（供中间件与依赖复用，单一事实来源）
    规则4  自动解封用惰性判断：查询时 ban_end_time < NOW() 即视为已解封，不依赖定时任务
           → get_active_ban() / is_active()
           记录永久留存（含 reason），作为信誉画像扣分依据
    规则6  连续缺席不叠加封禁：已在封禁中 → 不新建记录，只顺延
           → _extend_ban()（详见下方「连续缺席处理逻辑」）

连续缺席处理逻辑（规则6 的落地方案）
--------------------------------------------------------------------
    情形A：用户当前【无】生效封禁
        → 新建一条记录：ban_start_time=now, ban_duration_days=3, ban_end_time=now+3天
    情形B：用户当前【已有】生效封禁（ban_end_time > now）
        → 不新建记录（避免多条并存导致语义混乱、拦截判断出现歧义），只做三件事：
            1) 顺延解禁时间：ban_end_time = max(当前 ban_end_time, now) + 3天
            2) 首次顺延时把「原本的解禁时间」存进 ban_original_end_time（留痕）
            3) ban_extend_count += 1，ban_last_extend_at = now
    为什么从 ban_end_time 顺延而不是 from now：
        符合「先服完当前惩罚，再加罚」的直觉；若从 now 起算，
        连续缺席反而会让解禁时间提前（越蹲越短），与惩罚意图相反。
    为什么设上限（BAN_MAX_TOTAL_DAYS，默认30天）：
        防止无限顺延形成事实上的永久封禁，校园场景应以教育改正为主；
        达到上限后仍照常扣分、照常留痕，只是不再延长封禁。
    为什么用同一条记录而不是每次新建：
        规则4 要求记录永久留存且能还原最初窗口，
        ban_original_end_time 保留了最初的 3 天区间，
        t_checkin_record 里每次缺席的明细也永久保留，审计信息不丢失。
====================================================================
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import BanReasonType, BanStatus, ReleaseType
from app.core.response import build_ban_message
from app.models import Blacklist

logger = logging.getLogger(__name__)


# ==================================================================
# 规则3：封禁期间被拦截的动作用户
#   设计原则：用「明确黑名单」而不是「拦截所有写操作」。
#   理由：若拦掉所有 POST，用户将无法签到/核销（规则要求历史遗留球局仍可签到）、
#        也无法退出已报名的球局（会被迫占用名额并进一步被判缺席），惩罚会失控。
#   如需更严格（拦掉全部非 GET 请求），把 .env 的 BAN_BLOCK_ALL_WRITES 设为 true。
# ==================================================================
BAN_BLOCKED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("POST", re.compile(r"^/api/v1/game$")),                 # 发起球局
    ("POST", re.compile(r"^/api/v1/game/\d+/signup$")),      # 报名加入球局（含候补）
)


def is_ban_blocked_request(method: str, path: str) -> bool:
    """
    判断某次请求是否属于「封禁期间禁止的动作」。
    中间件钩子与 get_current_active_user 依赖都调用这里，保证两处口径一致。
    """
    method = (method or "").upper()

    # 查询类（GET/HEAD/OPTIONS）一律放行：被封禁用户要能看到球局列表与自己的封禁状态
    if method in ("GET", "HEAD", "OPTIONS"):
        return False

    if settings.BAN_BLOCK_ALL_WRITES:
        return True  # 严格模式：拦掉一切非查询请求

    return any(m == method and pattern.match(path) for m, pattern in BAN_BLOCKED_PATTERNS)


# ==================================================================
# 当前生效的封禁信息（轻量值对象）
# ==================================================================
@dataclass(slots=True)
class ActiveBan:
    """当前生效的封禁信息（ban_end_time 为解禁时间）"""

    user_id: int
    ban_end_time: datetime
    ban_duration_days: int | None = None
    ban_start_time: datetime | None = None
    ban_id: int | None = None
    reason: str | None = None
    reason_type: int | None = None
    extend_count: int = 0
    from_cache: bool = False  # 命中缓存时字段可能不全

    def message(self) -> str:
        """规则3 指定的拦截文案"""
        return build_ban_message(self.ban_end_time, self.reason_type)

    def to_dict(self) -> dict:
        return {
            "ban_id": self.ban_id,
            "ban_start_time": self.ban_start_time.isoformat() if self.ban_start_time else None,
            "ban_end_time": self.ban_end_time.isoformat() if self.ban_end_time else None,
            "ban_duration_days": self.ban_duration_days,
            "ban_extend_count": self.extend_count,
            "reason": self.reason,
            "reason_type": self.reason_type,
            "remaining_hours": self.remaining_hours(),
        }

    def remaining_hours(self) -> float:
        delta = self.ban_end_time - datetime.now()
        return round(max(delta.total_seconds(), 0) / 3600, 1)


@dataclass
class BanApplyResult:
    """封禁应用结果"""

    ban: Blacklist
    created: bool          # True=新建记录；False=顺延已有记录（规则6）
    extended_days: int = 0
    capped: bool = False   # 是否因达到总时长上限而未继续顺延
    message: str = ""


# ==================================================================
# 轻量内存缓存（进程级、按 user_id 索引）
# ==================================================================
class _BanCache:
    """
    key = user_id, value = (过期时间戳, ActiveBan 或 None)
    缓存完整封禁信息，保证「命中缓存」与「回源查询」返回一致。

    注意：缓存是进程级的，单元测试在同一进程内切换测试库时必须 ban_cache.clear()；
    多实例部署时各进程独立，如需强一致请把本类换成 Redis 实现（对外接口不变）。
    """

    def __init__(self, ttl: int) -> None:
        self.ttl = ttl
        self._store: dict[int, tuple[float, ActiveBan | None]] = {}

    def get(self, user_id: int) -> tuple[bool, ActiveBan | None]:
        item = self._store.get(user_id)
        if not item:
            return False, None
        expire_at, ban = item
        if expire_at < time.time():
            self._store.pop(user_id, None)
            return False, None
        return True, ban

    def set(self, user_id: int, ban: ActiveBan | None) -> None:
        self._store[user_id] = (time.time() + self.ttl, ban)

    def invalidate(self, user_id: int) -> None:
        """封禁/顺延/解封后必须调用，否则会读到旧状态"""
        self._store.pop(user_id, None)

    def clear(self) -> None:
        self._store.clear()


ban_cache = _BanCache(ttl=settings.BLACKLIST_CACHE_TTL)


# ==================================================================
# 查询（规则4：惰性判定自动解封）
# ==================================================================
async def get_active_ban(
    db: AsyncSession, user_id: int, use_cache: bool = True
) -> ActiveBan | None:
    """
    查询用户当前生效的封禁。

    惰性解封：条件写死 `ban_end_time > NOW()`，
    一旦过期就查不到，等价于「已自动解封」——不依赖任何定时任务。
    """
    if use_cache:
        hit, cached = ban_cache.get(user_id)
        if hit:
            if cached is None:
                return None
            cached.from_cache = True
            return cached

    stmt = (
        select(Blacklist)
        .where(
            Blacklist.user_id == user_id,
            Blacklist.ban_end_time > datetime.now(),  # ★ 惰性解封：过期即失效
        )
        .order_by(Blacklist.ban_end_time.desc())
        .limit(1)
    )
    ban = (await db.execute(stmt)).scalars().first()

    if not ban:
        if use_cache:
            ban_cache.set(user_id, None)
        return None

    active = ActiveBan(
        user_id=ban.user_id,
        ban_end_time=ban.ban_end_time,
        ban_duration_days=ban.ban_duration_days,
        ban_start_time=ban.ban_start_time,
        ban_id=ban.id,
        reason=ban.reason,
        reason_type=ban.reason_type,
        extend_count=ban.ban_extend_count or 0,
    )
    if use_cache:
        ban_cache.set(user_id, active)
    return active


async def get_active_ban_row(db: AsyncSession, user_id: int) -> Blacklist | None:
    """
    查询生效中的封禁【记录行】（不走缓存，用于顺延等写操作）。
    加 FOR UPDATE 行锁，避免并发缺席判定同时顺延导致相互覆盖。
    """
    stmt = (
        select(Blacklist)
        .where(
            Blacklist.user_id == user_id,
            Blacklist.ban_end_time > datetime.now(),
        )
        .order_by(Blacklist.ban_end_time.desc())
        .limit(1)
        .with_for_update()
    )
    return (await db.execute(stmt)).scalars().first()


async def is_banned(db: AsyncSession, user_id: int) -> bool:
    """是否处于禁赛期（业务层快速判断）"""
    return await get_active_ban(db, user_id) is not None


async def list_bans(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    only_active: bool = False,
    reason_type: int | None = None,
    include_released: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Blacklist], int]:
    """
    分页查询封禁记录（管理端 / 个人封禁历史）。
    记录永久留存，因此 include_released=True 时能查到历史（含已解封）。
    """
    from sqlalchemy import func

    conditions = []
    if user_id is not None:
        conditions.append(Blacklist.user_id == user_id)
    if only_active:
        conditions.append(Blacklist.ban_end_time > datetime.now())
    if reason_type is not None:
        conditions.append(Blacklist.reason_type == reason_type)
    if not include_released:
        conditions.append(Blacklist.released_at.is_(None))

    total = (
        await db.execute(select(func.count()).select_from(Blacklist).where(*conditions))
    ).scalar_one()

    stmt = (
        select(Blacklist)
        .where(*conditions)
        .order_by(Blacklist.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.execute(stmt)).scalars().all()), total


# ==================================================================
# 封禁写入（规则2 + 规则6）
# ==================================================================
async def apply_ban(
    db: AsyncSession,
    *,
    user_id: int,
    reason_type: int = BanReasonType.ABSENT,
    reason: str | None = None,
    days: int | None = None,
    trigger_game_id: int | None = None,
    credit_score_at_ban: int | None = None,
    operator_id: int = 0,
    allow_extend: bool | None = None,
    commit: bool = True,
) -> BanApplyResult:
    """
    给用户应用一次封禁惩罚。

    :param days:     封禁天数，默认取配置（3 天）
    :param allow_extend: 是否允许「封禁中顺延」（规则6）。None=读配置 BAN_EXTEND_ON_REPEAT
    :return: BanApplyResult（created=True 新建 / False 顺延）
    """
    duration_days = days if days is not None else settings.BAN_DEFAULT_DAYS
    extend_allowed = (
        allow_extend if allow_extend is not None else settings.BAN_EXTEND_ON_REPEAT
    )
    now = datetime.now()

    existing = await get_active_ban_row(db, user_id)

    # ---------- 规则6：已在封禁中 → 顺延，不新建 ----------
    if existing is not None and extend_allowed:
        result = await _extend_ban(
            db, ban=existing, days=duration_days, reason=reason,
            reason_type=reason_type, trigger_game_id=trigger_game_id,
            credit_score_at_ban=credit_score_at_ban, now=now,
        )
        if commit:
            await db.commit()
        ban_cache.invalidate(user_id)
        return result

    # ---------- 规则2：新建封禁，end_time = start_time + N天 ----------
    ban = Blacklist(
        user_id=user_id,
        ban_start_time=now,
        ban_duration_days=duration_days,
        ban_end_time=Blacklist.calc_end_time(now, duration_days),
        status=BanStatus.BANNED,
        reason_type=reason_type,
        reason=reason,
        trigger_game_id=trigger_game_id,
        credit_score_at_ban=credit_score_at_ban,
        operator_id=operator_id,
        ban_extend_count=0,
    )
    db.add(ban)
    # 先 flush 拿到自增ID：缺席判定等流程用 commit=False 调用，
    # 若不 flush，返回给前端的封禁明细里 ban_id 会是 null
    await db.flush()
    if commit:
        await db.commit()
        await db.refresh(ban)

    ban_cache.invalidate(user_id)
    logger.warning(
        "用户 %s 被关进小黑屋：%s 天（%s ~ %s），原因类型=%s，原因=%s",
        user_id, duration_days, ban.ban_start_time, ban.ban_end_time, reason_type, reason,
    )
    return BanApplyResult(
        ban=ban,
        created=True,
        message=build_ban_message(ban.ban_end_time, reason_type),
    )


async def _extend_ban(
    db: AsyncSession,
    *,
    ban: Blacklist,
    days: int,
    reason: str | None,
    reason_type: int,
    trigger_game_id: int | None,
    credit_score_at_ban: int | None,
    now: datetime,
) -> BanApplyResult:
    """
    规则6 的核心：顺延已有封禁记录（不新建）。
        ban_end_time = max(当前 ban_end_time, now) + days
    并受 BAN_MAX_TOTAL_DAYS 上限约束。
    """
    base_end = max(ban.ban_end_time, now)
    new_end = base_end + timedelta(days=days)

    # 首次顺延：把最初的解禁时间留痕
    if ban.ban_original_end_time is None:
        ban.ban_original_end_time = ban.ban_end_time

    capped = False
    max_end = ban.ban_start_time + timedelta(days=settings.BAN_MAX_TOTAL_DAYS)
    if new_end > max_end:
        new_end = max_end
        capped = True

    ban.ban_end_time = new_end
    ban.ban_duration_days = (ban.ban_duration_days or days) + days
    ban.ban_extend_count = (ban.ban_extend_count or 0) + 1
    ban.ban_last_extend_at = now
    ban.status = BanStatus.BANNED
    ban.released_at = None
    ban.release_type = None
    # 记录最近一次触发原因，便于事后追溯；历史明细在 t_checkin_record 中永久保留
    ban.reason = f"{ban.reason or '缺席球局'}；封禁期内再次缺席，已顺延 {days} 天"[:255]
    ban.reason_type = reason_type
    ban.credit_score_at_ban = credit_score_at_ban or ban.credit_score_at_ban
    if trigger_game_id:
        ban.trigger_game_id = trigger_game_id

    await db.flush()
    logger.warning(
        "用户 %s 封禁期内再次缺席：封禁顺延 %s 天至 %s（第 %s 次顺延，上限=%s 天%s）",
        ban.user_id, days, new_end, ban.ban_extend_count,
        settings.BAN_MAX_TOTAL_DAYS, "，已达上限" if capped else "",
    )
    return BanApplyResult(
        ban=ban,
        created=False,
        extended_days=days,
        capped=capped,
        message=f"您因放鸽子被禁赛，将于 {new_end:%Y-%m-%d %H:%M} 解除",
    )


# 兼容旧调用名：手动封禁（管理员）
async def ban_user(db: AsyncSession, **kwargs) -> Blacklist:
    """
    管理员手动封禁（对外保持返回 Blacklist 的旧签名）。
    若用户已在封禁中且允许顺延，则顺延原记录而不是新建。传 force_new=True 可强制新建。
    """
    force_new = kwargs.pop("force_new", False)
    if force_new:
        kwargs["allow_extend"] = False
    result = await apply_ban(db, **kwargs)
    return result.ban


async def ban_for_absent(
    db: AsyncSession,
    *,
    user_id: int,
    trigger_game_id: int | None = None,
    credit_score_at_ban: int | None = None,
    operator_id: int = 0,
    reason: str | None = None,
    commit: bool = True,
) -> BanApplyResult:
    """规则2：缺席触发的封禁（固定 3 天；已在封禁中则按规则6 顺延）"""
    return await apply_ban(
        db,
        user_id=user_id,
        reason_type=BanReasonType.ABSENT,
        reason=reason or f"缺席球局（未签到且未请假），球局ID={trigger_game_id}",
        trigger_game_id=trigger_game_id,
        credit_score_at_ban=credit_score_at_ban,
        operator_id=operator_id,
        commit=commit,
    )


async def ban_for_low_credit(
    db: AsyncSession,
    *,
    user_id: int,
    credit_score: int,
    trigger_game_id: int | None = None,
    operator_id: int = 0,
    commit: bool = True,
) -> BanApplyResult:
    """信誉分过低触发的封禁（同样遵守规则6 顺延）"""
    return await apply_ban(
        db,
        user_id=user_id,
        reason_type=BanReasonType.LOW_CREDIT,
        reason=f"信誉分 {credit_score} 低于阈值 {settings.CREDIT_BAN_THRESHOLD}",
        trigger_game_id=trigger_game_id,
        credit_score_at_ban=credit_score,
        operator_id=operator_id,
        commit=commit,
    )


# ==================================================================
# 解封（惰性判定为主，这里只做「留痕」与人工解封）
# ==================================================================
async def release_expired_bans(db: AsyncSession, limit: int = 500) -> int:
    """
    把已到期记录标记为「已解封」（仅留痕，不参与拦截判断）。
    拦截判断始终走 get_active_ban() 的惰性条件，所以本任务即使不跑也不会误封。
    """
    now = datetime.now()

    stmt = select(Blacklist.id, Blacklist.user_id).where(
        Blacklist.status == BanStatus.BANNED,
        Blacklist.ban_end_time <= now,
    ).limit(limit)
    rows = (await db.execute(stmt)).all()
    if not rows:
        return 0

    ban_ids = [row[0] for row in rows]
    user_ids = {row[1] for row in rows}

    await db.execute(
        update(Blacklist)
        .where(Blacklist.id.in_(ban_ids))
        .values(status=BanStatus.RELEASED, released_at=now, release_type=ReleaseType.AUTO)
    )
    await db.commit()
    for user_id in user_ids:
        ban_cache.invalidate(user_id)

    logger.info("自动解封 %d 条到期记录（留痕），涉及用户：%s", len(ban_ids), sorted(user_ids))
    return len(ban_ids)


async def release_ban(
    db: AsyncSession,
    *,
    ban_id: int,
    release_type: int = ReleaseType.MANUAL,
    operator_id: int | None = None,
    remark: str | None = None,
) -> bool:
    """人工解封（管理员 / 申诉）：把解禁时间提前到现在"""
    ban = await db.get(Blacklist, ban_id)
    if not ban or ban.ban_end_time <= datetime.now():
        return False  # 已到期，无需解封

    now = datetime.now()
    ban.ban_end_time = now
    ban.status = BanStatus.RELEASED
    ban.released_at = now
    ban.release_type = release_type
    ban.operator_id = operator_id
    if remark:
        ban.remark = remark

    await db.commit()
    ban_cache.invalidate(ban.user_id)
    logger.info("小黑屋记录 %s（用户 %s）已解封，方式=%s", ban_id, ban.user_id, release_type)
    return True


async def count_bans(db: AsyncSession, *, user_id: int, only_active: bool = False) -> int:
    """统计封禁次数（信誉画像输入特征：累计被封次数）"""
    from sqlalchemy import func

    conditions = [Blacklist.user_id == user_id]
    if only_active:
        conditions.append(Blacklist.ban_end_time > datetime.now())
    return (
        await db.execute(select(func.count()).select_from(Blacklist).where(*conditions))
    ).scalar_one()
