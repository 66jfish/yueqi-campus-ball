"""
报名模型（t_registration）
====================================================================
一人一局只能有一条报名记录（唯一索引 uk_reg_game_user），
取消报名走状态流转（status=2）而不是物理删除，便于失信追溯。
====================================================================
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import RegistrationStatus, SkillLevel
from app.db.base import MYSQL_TABLE_OPTIONS, Base, TimestampMixin


class Registration(Base, TimestampMixin):
    """报名表"""

    __tablename__ = "t_registration"
    __table_args__ = (
        Index("uk_reg_game_user", "game_id", "user_id", unique=True),
        Index("idx_reg_game_status", "game_id", "status"),
        Index("idx_reg_user_status", "user_id", "status"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="报名记录ID，主键"
    )
    game_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="球局ID（外键 -> t_game.id）"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="报名用户ID（外键 -> t_user.id）"
    )

    status: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=RegistrationStatus.SIGNED,
        server_default=text("1"),
        comment="报名状态：1-已报名 2-已取消 3-候补中 4-被移出",
    )
    is_waitlist: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="是否候补：0-正式名额 1-候补队列（名额满时进入）",
    )
    waitlist_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="候补顺序号，越小越先补位",
    )

    signup_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), comment="报名时间"
    )
    cancel_time: Mapped[datetime | None] = mapped_column(DateTime, comment="取消报名时间")
    cancel_reason: Mapped[str | None] = mapped_column(String(255), comment="取消原因")

    credit_snapshot: Mapped[int | None] = mapped_column(
        Integer, comment="报名时的信誉分快照（AI画像/事后追责参考）"
    )
    skill_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=SkillLevel.NEWBIE,
        server_default=text("1"),
        comment="报名时自评的该球类水平（必填）：1-新手 2-初级 3-中级 4-高级 5-大神",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Registration id={self.id} game={self.game_id} user={self.user_id}>"
