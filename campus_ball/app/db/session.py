"""
数据库连接模块（核心）
====================================================================
职责：
    1. 创建全局唯一的异步 Engine（连接池复用，随进程生命周期）
    2. 提供 AsyncSession 工厂 AsyncSessionLocal
    3. 提供 FastAPI 依赖 get_db（每个请求一个 Session，出异常自动回滚）
    4. 提供服务层/脚本用的会话上下文 async_session_scope
    5. 提供健康检查与优雅关闭

使用方式：
    # API 层（依赖注入）
    async def api(db: AsyncSession = Depends(get_db)): ...

    # Service / 后台任务
    async with async_session_scope() as db:
        ...

注意：
    - Engine 采用「惰性连接」：import 本模块不会真的去连 MySQL，
      因此本地没有数据库时也能正常启动、跑单元测试、生成 OpenAPI 文档。
    - 池参数统一来自 settings，方便不同环境用 .env 调整。
====================================================================
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings

logger = logging.getLogger(__name__)


# ==================================================================
# 1. 异步 Engine
# ==================================================================
def _create_engine() -> AsyncEngine:
    """
    按配置创建异步引擎（模块级只执行一次，同一 Serverless 容器内复用）。

    两种形态：
        常驻服务（uvicorn / 容器）：用连接池，pool_pre_ping 剔除失效连接
        Serverless（Vercel）：用 NullPool（每请求新建/归还），避免容器冻结后连接失效；
                              TiDB Cloud 强制 TLS，按 DB_REQUIRE_SSL 注入 SSL 上下文
    """
    connect_args: dict = {}
    if settings.DB_REQUIRE_SSL:
        # TiDB Cloud Serverless 要求 TLS 连接
        import ssl as _ssl

        if settings.DB_SSL_CA:
            connect_args["ssl"] = _ssl.create_default_context(cafile=settings.DB_SSL_CA)
        else:
            ctx = _ssl.create_default_context()
            ctx.check_hostname = False       # TiDB Cloud 网关域名与证书 CN 可能不一致
            ctx.verify_mode = _ssl.CERT_NONE
            connect_args["ssl"] = ctx

    use_null_pool = settings.DB_USE_NULL_POOL or settings.SERVERLESS_MODE
    pool_kwargs: dict = (
        {"poolclass": NullPool}
        if use_null_pool
        else {
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
            "pool_recycle": settings.DB_POOL_RECYCLE,  # 小于 MySQL wait_timeout，避免连接失效
            "pool_timeout": settings.DB_POOL_TIMEOUT,
            "pool_use_lifo": True,                     # 后进先出，降低空闲连接被服务端掐断的概率
        }
    )

    return create_async_engine(
        settings.sqlalchemy_database_uri,
        echo=settings.DB_ECHO,                 # True 时打印 SQL，排查慢查询用
        echo_pool=False,
        pool_pre_ping=not use_null_pool,       # NullPool 无需 pre_ping（每次都是新连接）
        connect_args=connect_args,
        future=True,
        **pool_kwargs,
    )


engine: AsyncEngine = _create_engine()

# ==================================================================
# 2. 会话工厂
#     expire_on_commit=False：commit 后对象属性仍可读，避免接口序列化时触发
#                             额外查询（配合 Pydantic 序列化很方便）
# ==================================================================
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# ==================================================================
# 3. FastAPI 依赖：每请求一个会话
# ==================================================================
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    请求级数据库会话依赖
    - 正常结束：由业务代码自行 commit（事务边界更清晰）
    - 抛异常：自动 rollback，保证不会留下半截事务
    """
    session = AsyncSessionLocal()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ==================================================================
# 4. 非请求场景会话上下文（定时任务 / 中间件 / 脚本）
# ==================================================================
@asynccontextmanager
async def async_session_scope() -> AsyncGenerator[AsyncSession, None]:
    """
    独立会话上下文，适用于：
        - 黑名单中间件（不走 Depends 的场景）
        - 小黑屋「到期自动解封」后台任务
        - 惰性结算批处理脚本
    用法：
        async with async_session_scope() as db:
            ...
    """
    session = AsyncSessionLocal()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ==================================================================
# 5. 健康检查 / 生命周期
# ==================================================================
async def check_database_connection() -> bool:
    """简单探活：SELECT 1，供 /health 接口与启动自检使用"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - 探活失败原因只记录不抛出
        logger.error("数据库连接失败：%s", exc)
        return False


async def dispose_engine() -> None:
    """优雅关闭连接池（应用 shutdown 时调用）"""
    await engine.dispose()
    logger.info("数据库连接池已释放")
