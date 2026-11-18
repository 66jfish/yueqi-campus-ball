"""
签到记录模型（t_checkin_record）
====================================================================
★ 惰性结算的「账本」表 ★
    settled = 0 表示这条签到/缺席记录还没有折算成信誉分，
    下次有人触发结算（签到动作、或者球局结束后的缺席判定）时，
    才会把这些未结算记录一次性汇总、更新到 t_user.credit_score，并置 settled = 1。
    好处：分数不是每条记录实时算的，而是「用的时候才算」，
         高并发签到场景下不产生行锁竞争，也天然支持补算/重算。

    credit_delta —— 结算时写入的本次分值变动，便于前端展示「+2 / -10」流水
====================================================================
"""

from datetime import datetime

from decimal import Decimal

from sqlalchemy import DECIMAL, BigInteger, DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import CheckinStatus, CheckinType
from app.db.base import MYSQL_TABLE_OPTIONS, Base, TimestampMixin


class CheckinRecord(Base, TimestampMixin):
    """签到记录表"""

    __tablename__ = "t_checkin_record"
    __table_args__ = (
        Index("uk_checkin_game_user", "game_id", "user_id", unique=True),
        # 惰性结算的核心索引：按 (settled, checkin_status) 快速捞出待结算记录
        Index("idx_checkin_settle", "settled", "checkin_status"),
        Index("idx_checkin_user_status", "user_id", "checkin_status"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="签到记录ID，主键"
    )
    game_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="球局ID（外键 -> t_game.id）"
    )
    registration_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="关联报名记录ID（外键 -> t_registration.id）"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="用户ID（外键 -> t_user.id）"
    )

    # ---------------- 签到状态 ----------------
    checkin_status: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=CheckinStatus.NOT_CHECKED,
        server_default=text("0"),
        comment="签到状态：0-未签到 1-正常签到 2-迟到 3-缺席 4-已请假",
    )
    checkin_type: Mapped[int | None] = mapped_column(
        Integer, comment="签到方式：1-扫码 2-定位打卡 3-发起人核销/人工补签"
    )
    checkin_time: Mapped[datetime | None] = mapped_column(DateTime, comment="实际签到时间")
    checkin_operator_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="核销/补签操作人用户ID（发起人核销时记录发起人ID；本人签到为空）"
    )

    # ---------------- 定位（防代签） ----------------
    location_lat: Mapped[Decimal | None] = mapped_column(
        DECIMAL(10, 7), comment="签到纬度（校验是否在球场附近）"
    )
    location_lng: Mapped[Decimal | None] = mapped_column(
        DECIMAL(10, 7), comment="签到经度（校验是否在球场附近）"
    )

    # ---------------- 缺席判定 ----------------
    absence_confirmed_by: Mapped[int | None] = mapped_column(
        BigInteger, comment="缺席判定人用户ID（组织者或系统，系统判定填0）"
    )
    absence_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="缺席判定时间（惰性结算的第二触发点）"
    )

    # ---------------- 惰性结算字段 ----------------
    credit_delta: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="本次记录产生的信誉分变动（结算时写入，如 +2 / -10）",
    )
    settled: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="惰性结算标记：0-待结算 1-已结算（只有签到/缺席判定时才置1）",
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, comment="该记录被结算的时间")

    remark: Mapped[str | None] = mapped_column(String(255), comment="备注（请假原因、人工补签说明）")

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<CheckinRecord id={self.id} game={self.game_id} user={self.user_id} status={self.checkin_status}>"
