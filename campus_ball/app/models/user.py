"""
用户模型（t_user）
====================================================================
与「惰性结算」相关的关键点：
    credit_score       —— 信誉分实际存库字段，平时只读不实时计算
    credit_settled_at  —— 最近一次结算水位线，便于排查「分数为什么没变」
    credit_level       —— 结算时顺手刷新的等级，方便列表页排序/标签展示
    absent_count       —— 失信次数，AI 信誉画像的重要输入特征
====================================================================
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.core.constants import CreditLevel, Gender, SkillLevel, UserStatus
from app.db.base import MYSQL_TABLE_OPTIONS, Base, SoftDeleteMixin, TimestampMixin


class User(Base, TimestampMixin, SoftDeleteMixin):
    """用户表"""

    __tablename__ = "t_user"
    __table_args__ = (
        Index("uk_user_student_no", "student_no", unique=True),
        Index("uk_user_phone", "phone", unique=True),
        Index("idx_user_reputation_score", "reputation_score"),
        Index("idx_user_status", "status"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="用户ID，主键"
    )

    # ---------------- 账号 / 身份 ----------------
    student_no: Mapped[str] = mapped_column(String(32), nullable=False, comment="学号，校内唯一标识")
    nickname: Mapped[str] = mapped_column(String(32), nullable=False, comment="昵称")
    real_name: Mapped[str | None] = mapped_column(String(32), comment="真实姓名（实名认证用）")
    password_hash: Mapped[str] = mapped_column(
        String(160), nullable=False, comment="密码哈希（PBKDF2，禁止明文存储）"
    )
    phone: Mapped[str | None] = mapped_column(String(20), comment="手机号（登录/通知）")
    email: Mapped[str | None] = mapped_column(String(64), comment="邮箱")
    avatar_url: Mapped[str | None] = mapped_column(String(255), comment="头像URL")

    # ---------------- 校内属性 ----------------
    campus: Mapped[str | None] = mapped_column(String(64), comment="校区，如：东校区")
    college: Mapped[str | None] = mapped_column(String(64), comment="学院")
    grade: Mapped[str | None] = mapped_column(String(16), comment="年级，如：2023")
    gender: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=Gender.UNKNOWN,
        server_default=text("0"),
        comment="性别：0-未知 1-男 2-女",
    )

    # ---------------- 信誉体系（惰性结算） ----------------
    reputation_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        server_default=text("100"),
        comment="信誉分（初始100；惰性结算：签到时+2/-3，缺席时-10，不实时计算）",
    )
    # 兼容别名：历史代码里的 user.credit_score / User.credit_score 依然可用
    # （synonym 在 ORM 属性与查询语句两个层面都生效，无需改动既有业务代码）
    credit_score = synonym("reputation_score")

    credit_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=CreditLevel.NORMAL,
        server_default=text("3"),
        comment="信誉等级：1-黑名单 2-观察 3-正常 4-优秀 5-金牌（结算时按分数刷新）",
    )
    credit_settled_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="信誉分最近一次结算时间（惰性结算水位线）"
    )
    total_game_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="累计参与球局数（结算时累加）",
    )
    absent_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="累计缺席/迟到次数（失信次数，AI画像输入特征）",
    )

    # ---------------- 球技 & AI 画像 ----------------
    skill_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=SkillLevel.NEWBIE,
        server_default=text("1"),
        comment="球技水平：1-新手 2-初级 3-中级 4-高级 5-大神",
    )
    ai_profile: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="AI信誉画像结果（含画像分/标签/风险等级/明细；DeepSeek输出或本地加权规则版）"
    )
    ai_score: Mapped[int | None] = mapped_column(
        Integer, comment="AI画像评估分（0-150，画像算法输出；供个人主页展示与球局匹配参考）"
    )
    ai_profile_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="AI信誉画像最近生成时间"
    )
    ai_profile_source: Mapped[str | None] = mapped_column(
        String(16), comment="画像来源：deepseek（大模型）/ rule（本地加权规则降级）"
    )
    ai_profile_dirty: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="待重算标记：1=签到/缺席/退出结算后需要重算画像（后台任务或读取时惰性重算）",
    )
    ai_profile_trigger: Mapped[str | None] = mapped_column(
        String(32), comment="最近一次触发重算的原因：checkin/absent/exit/manual/cache_expired"
    )
    ai_profile_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="画像版本号：每次重算 +1，便于缓存与审计",
    )

    # ---------------- 状态 ----------------
    status: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=UserStatus.NORMAL,
        server_default=text("1"),
        comment="账号状态：0-禁用 1-正常",
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, comment="最近登录时间")

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<User id={self.id} student_no={self.student_no} credit={self.credit_score}>"
