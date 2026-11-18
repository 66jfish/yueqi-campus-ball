"""
ORM 基类
====================================================================
提供：
    Base            —— 所有模型的声明式基类（SQLAlchemy 2.0 风格）
    TimestampMixin  —— created_at / updated_at 通用时间字段
说明：
    alembic 后续接入时，直接 `target_metadata = Base.metadata`
====================================================================
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""

    # 说明：SQLAlchemy 中子类的 __table_args__ 会「整体覆盖」父类的定义，
    # 因此各模型需要把 MYSQL_TABLE_OPTIONS 放在自己 __table_args__ 元组的最后一位。
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


# 统一的 MySQL 表选项：在字段注释、索引之外，保证字符集与存储引擎一致
MYSQL_TABLE_OPTIONS: dict[str, str] = {
    "mysql_charset": "utf8mb4",           # 支持 emoji / 生僻字
    "mysql_collate": "utf8mb4_unicode_ci",
    "mysql_engine": "InnoDB",             # 事务 + 行锁，惰性结算依赖 FOR UPDATE
}


class TimestampMixin:
    """创建/更新时间 Mixin，业务表基本都需要"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )


class SoftDeleteMixin:
    """逻辑删除 Mixin：按 is_deleted=0 过滤，避免物理删除导致数据无法追溯"""

    is_deleted: Mapped[int] = mapped_column(
        default=0,
        server_default="0",
        nullable=False,
        comment="逻辑删除标记：0-未删除 1-已删除",
    )
