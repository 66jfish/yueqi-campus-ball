"""
球局模型（t_game）
====================================================================
与「惰性结算」相关的关键点：
    settle_status —— 球局维度的结算标记，避免同一场球局被重复结算
    settled_at    —— 结算完成时间
    checkin_start_time / checkin_end_time —— 签到窗口，
                    球局结束后由 Service 触发「未签到 -> 缺席」的批量判定，
                    该判定正是惰性结算的第二个触发时机
====================================================================
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, BigInteger, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import FeeType, GameStatus, SettleStatus, SportType
from app.db.base import MYSQL_TABLE_OPTIONS, Base, SoftDeleteMixin, TimestampMixin


class Game(Base, TimestampMixin, SoftDeleteMixin):
    """球局表"""

    __tablename__ = "t_game"
    __table_args__ = (
        Index("idx_game_creator", "creator_id"),
        Index("idx_game_sport_start", "sport_type", "start_time"),
        Index("idx_game_status_start", "status", "start_time"),
        Index("idx_game_settle_status", "settle_status"),
        # 同场地同时段冲突校验的核心索引
        Index("idx_game_venue_time", "venue_name", "start_time"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="球局ID，主键"
    )
    creator_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="发起人用户ID（外键 -> t_user.id）"
    )

    # ---------------- 基本信息 ----------------
    sport_type: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=SportType.BASKETBALL,
        server_default=text("1"),
        comment="运动类型：1-篮球 2-足球 3-羽毛球 4-网球 5-排球 6-乒乓球",
    )
    title: Mapped[str] = mapped_column(String(64), nullable=False, comment="球局标题，如：周五晚东区篮球")
    description: Mapped[str | None] = mapped_column(Text, comment="球局说明（水平要求、备注等）")

    # ---------------- 场地 ----------------
    campus: Mapped[str | None] = mapped_column(String(64), comment="所在校区")
    venue_name: Mapped[str | None] = mapped_column(String(64), comment="场馆/球场名称")
    venue_address: Mapped[str | None] = mapped_column(String(128), comment="详细地址")

    # ---------------- 时间 ----------------
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="开球时间")
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="结束时间")
    signup_deadline: Mapped[datetime | None] = mapped_column(DateTime, comment="报名截止时间")
    checkin_start_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="签到开始时间（一般为开球前30分钟）"
    )
    checkin_end_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="签到截止时间（超过即视为缺席，触发惰性结算）"
    )

    # ---------------- 人数 ----------------
    max_players: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default=text("10"), comment="最大人数（含组织者）"
    )
    min_players: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default=text("2"), comment="最少成局人数"
    )
    current_players: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="当前已报名人数（冗余字段，报名/取消时同步维护，避免列表页count）",
    )

    # ---------------- 费用 & 门槛 ----------------
    fee_type: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=FeeType.FREE,
        server_default=text("0"),
        comment="费用类型：0-免费 1-AA制",
    )
    fee_amount: Mapped[Decimal | None] = mapped_column(
        DECIMAL(10, 2), comment="人均费用（元），fee_type=1 时有效"
    )
    skill_level_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="最低球技要求：0-不限 1-新手 2-初级 3-中级 4-高级 5-大神",
    )
    gender_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="性别限制：0-不限 1-仅男生 2-仅女生",
    )
    min_credit_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="报名最低信誉分要求：0-不限（用于过滤低信誉用户）",
    )

    # ---------------- 状态 & 结算 ----------------
    status: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=GameStatus.DRAFT,
        server_default=text("0"),
        comment="球局状态：0-草稿 1-报名中 2-报名截止 3-进行中 4-已结束 5-已取消",
    )
    settle_status: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=SettleStatus.PENDING,
        server_default=text("0"),
        comment="结算状态（惰性结算用）：0-待结算 1-已结算 2-部分结算",
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, comment="本条球局完成结算的时间")
    cancel_reason: Mapped[str | None] = mapped_column(String(255), comment="取消/流局原因")

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Game id={self.id} title={self.title} status={self.status}>"
