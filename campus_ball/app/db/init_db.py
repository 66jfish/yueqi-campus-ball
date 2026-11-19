"""
建表 / 初始化数据
====================================================================
开发环境：可以用 SQLAlchemy 直接 create_all 快速起表
生产环境：建议执行 sql/001_schema.sql（字段注释更全、可控性更强），
          或接入 Alembic 做版本化迁移。

用法：
    python -m app.db.init_db            # 按 ORM 建表（已存在则跳过）
    python -m app.db.init_db --drop     # 先删后建（仅限开发环境！）
====================================================================
"""

import argparse
import asyncio
import logging

from app.core.config import settings
from app.db.base import Base
from app.db.session import check_database_connection, engine

# 关键：必须 import 所有模型，Base.metadata 才认识全部表
from app.models import (  # noqa: F401
    Blacklist,
    CheckinRecord,
    Game,
    Registration,
    User,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def create_tables(drop_first: bool = False) -> None:
    """创建全部数据表"""
    if drop_first:
        if settings.is_prod:
            raise RuntimeError("生产环境禁止执行 drop_all！")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        logger.warning("已删除全部数据表（开发环境）")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("建表完成，共 %d 张表：%s", len(Base.metadata.tables), list(Base.metadata.tables))


async def main() -> None:
    parser = argparse.ArgumentParser(description="搭子月球 - 数据库初始化")
    parser.add_argument("--drop", action="store_true", help="先删除已有表（仅开发环境）")
    args = parser.parse_args()

    if not await check_database_connection():
        raise SystemExit(
            f"数据库连接失败，请检查 .env 配置：{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
        )

    await create_tables(drop_first=args.drop)


if __name__ == "__main__":
    asyncio.run(main())
