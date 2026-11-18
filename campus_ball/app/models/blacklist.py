"""
失信小黑屋模型（t_blacklist）
====================================================================
设计要点（对应需求「存储封禁起始时间、封禁时长，支持到期自动解封」）：
    1. ban_start_time      —— 封禁开始时间
    2. ban_duration_days   —— 封禁时长（天），校园规则默认 3 天
    3. ban_end_time        —— 解封时间 = 起始时间 + 时长，由服务层落库并加索引，
                              这样「是否还在禁赛」只需一个条件：
                                  status = 1 AND ban_end_time > NOW()
                              过期的记录天然不再命中，等于「自动解封」。
    4. 后台任务 release_expired_bans() 定时把到期记录 status 置 0（留痕），
       即使定时任务挂了，业务查询也不会误判为禁赛中（双保险，不依赖任务可用性）。
    5. 采用「新记录」而不是「改旧记录」的方式追加封禁，保留完整失信历史。
====================================================================
"""

from datetime import datetime, timedelta

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import BanReasonType, BanStatus, ReleaseType
from app.db.base import MYSQL_TABLE_OPTIONS, Base, TimestampMixin


class Blacklist(Base, TimestampMixin):
    """失信小黑屋表（禁赛记录）"""

    __tablename__ = "t_blacklist"
    __table_args__ = (
        # 中间件校验时的核心索引：命中「该用户 + 封禁中 + 未到期」
        Index("idx_ban_user_status_end", "user_id", "status", "ban_end_time"),
        Index("idx_ban_end_time", "ban_end_time"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="小黑屋记录ID，主键"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="被禁赛用户ID（外键 -> t_user.id）"
    )

    # ---------------- 封禁时间 ----------------
    ban_start_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="封禁开始时间"
    )
    ban_duration_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default=text("3"),
        comment="封禁时长（天），校园规则默认3天",
    )
    ban_end_time: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        comment="解封时间=封禁开始时间+封禁时长（服务层落库）；到期即自动解封",
    )

    # ---------------- 状态 ----------------
    status: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=BanStatus.BANNED,
        server_default=text("1"),
        comment="封禁状态：0-已解封 1-封禁中（查询侧以 ban_end_time 惰性判定，本字段仅用于留痕）",
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime, comment="实际解封时间")

    # ---------------- 顺延（连续缺席不叠加封禁） ----------------
    ban_extend_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="顺延次数：封禁期内再次缺席时累加（不新建记录，避免叠加封禁）",
    )
    ban_original_end_time: Mapped[datetime | None] = mapped_column(
        DateTime,
        comment="首次解禁时间（顺延前的初始值，仅首次顺延时写入，用于还原最初的3天窗口）",
    )
    ban_last_extend_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="最近一次顺延时间"
    )
    release_type: Mapped[int | None] = mapped_column(
        Integer, comment="解封方式：1-到期自动解封 2-管理员手动解封 3-申诉通过"
    )

    # ---------------- 原因追溯 ----------------
    reason_type: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=BanReasonType.ABSENT,
        server_default=text("1"),
        comment="封禁原因类型：1-缺席未到 2-多次迟到累计 3-信誉分过低 4-管理员人工封禁",
    )
    reason: Mapped[str | None] = mapped_column(String(255), comment="封禁详细原因说明")
    trigger_game_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="触发封禁的球局ID（可空，人工封禁时为空）"
    )
    credit_score_at_ban: Mapped[int | None] = mapped_column(
        Integer, comment="封禁时的信誉分快照（用于申诉复核）"
    )
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="操作人用户ID；系统自动封禁填0"
    )
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")

    # ==================================================================
    # 辅助方法
    # ==================================================================
    @staticmethod
    def calc_end_time(start_time: datetime, duration_days: int) -> datetime:
        """
        计算解封时间。
        统一在这里计算，避免服务层各处写法不一致导致「禁赛3天」变成71小时之类的偏差。
        """
        return start_time + timedelta(days=duration_days)

    @property
    def is_active(self) -> bool:
        """
        当前是否仍处于封禁中（规则4：只看解禁时间，惰性判定，不依赖 status 字段与定时任务）
        """
        return self.ban_end_time > datetime.now()

    @property
    def remaining_hours(self) -> float:
        """剩余小时数（前端倒计时用）"""
        delta = self.ban_end_time - datetime.now()
        return round(max(delta.total_seconds(), 0) / 3600, 1)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (
            f"<Blacklist id={self.id} user={self.user_id} "
            f"status={self.status} end={self.ban_end_time:%Y-%m-%d %H:%M}>"
        )
