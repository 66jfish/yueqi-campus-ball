"""
FastAPI 应用入口
====================================================================
启动：
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
接口文档：
    Swagger UI  http://127.0.0.1:8000/docs
    ReDoc       http://127.0.0.1:8000/redoc
    认证模块详细文档  docs/API_AUTH.md

本文件负责组装：
    1. 日志
    2. 生命周期：启动自检 + 注册认证钩子 + 小黑屋到期自动解封后台任务 + 关闭连接池
    3. 中间件（★注意顺序）：
         CORS（最外层） → AuthMiddleware（JWT 鉴权 + 小黑屋等统一拦截） → 路由
    4. 路由：/api/v1/*
    5. 全局异常处理 + 统一响应
    6. /health 健康检查
====================================================================
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.response import ApiResponse
from app.db.session import async_session_scope, check_database_connection, dispose_engine
from app.middleware import AuthMiddleware, list_auth_hooks, register_default_hooks
from app.services import ai_profile as ai_profile_service
from app.services import blacklist as blacklist_service
from app.services import checkin as checkin_service

# ------------------------------------------------------------------
# 日志：开发环境打印 SQL 与 DEBUG 日志，生产环境收敛到 INFO
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("app")

# 小黑屋到期自动解封的检查间隔（秒）
AUTO_RELEASE_INTERVAL_SECONDS = 300


# ==================================================================
# 后台任务：缺席判定兜底扫描（规则1）+ 小黑屋到期解封留痕（规则4）
# ==================================================================
async def _absent_scan_loop(interval: int | None = None) -> None:
    """
    每小时兜底扫描一次：把「已过结束时间但未结算」的球局结束掉并完成缺席判定，
    防止发起人忘记点「结束球局」导致漏判（漏判则漏罚，规则1 要求兜底）。

    幂等：已结算的球局会被 settle_status 过滤掉，重复扫描不会重复扣分。
    """
    interval = interval or settings.ABSENT_SCAN_INTERVAL_SECONDS
    while True:
        await asyncio.sleep(interval)
        try:
            async with async_session_scope() as db:
                result = await checkin_service.scan_overdue_games(db)
            if result["scanned"]:
                logger.warning(
                    "缺席兜底扫描：处理 %d 场球局，判定缺席 %d 人次",
                    result["scanned"], result["absent_total"],
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 后台任务不能因为一次异常就退出
            logger.error("缺席兜底扫描执行失败：%s", exc)


async def _ai_profile_loop(interval: int | None = None) -> None:
    """
    定时重算「待重算」用户的 AI 信誉画像（兜底，保证最终一致）。

    触发链：签到/核销、缺席判定、主动退出 → 置 ai_profile_dirty=1
            → ①（可选）结算后立即异步重算  ②本循环兜底  ③用户查看画像/主页时按需重算
    即使大模型短暂不可用，也会降级为本地加权规则版，不影响业务。
    """
    interval = interval or settings.AI_PROFILE_SCAN_INTERVAL_SECONDS
    while True:
        await asyncio.sleep(interval)
        try:
            async with async_session_scope() as db:
                result = await ai_profile_service.refresh_dirty_profiles(db)
            if result["scanned"]:
                logger.info(
                    "AI 画像兜底重算：扫描 %d 人，成功 %d 人",
                    result["scanned"], result["refreshed"],
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 后台任务不能因为一次异常就退出
            logger.error("AI 画像兜底重算执行失败：%s", exc)


async def _release_loop(interval: int = 300) -> None:
    """
    定时把已到期的封禁记录标记为「已解封」（仅留痕）。

    注意：拦截判断是惰性的（ban_end_time > NOW()），即使本任务没跑，
    到期用户也不会被误封 —— 本任务只是让 status 字段好看、便于统计。
    """
    while True:
        await asyncio.sleep(interval)
        try:
            async with async_session_scope() as db:
                await blacklist_service.release_expired_bans(db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("自动解封任务执行失败：%s", exc)


# ==================================================================
# 生命周期
# ==================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动 / 关闭钩子"""
    logger.info("=" * 60)
    logger.info("%s 启动中（环境：%s）", settings.PROJECT_NAME, settings.ENV)
    logger.info("接口前缀：%s，文档地址：/docs", settings.API_V1_PREFIX)

    # 注册认证拦截钩子（账号状态 → 小黑屋）；后续新增钩子只需再 register 一次
    register_default_hooks()
    logger.info("认证拦截钩子链：%s", " -> ".join(list_auth_hooks()) or "（无）")
    logger.info("认证中间件：%s", "已启用" if settings.AUTH_ENABLED else "已关闭")

    if await check_database_connection():
        logger.info("MySQL 连接正常：%s:%s/%s", settings.DB_HOST, settings.DB_PORT, settings.DB_NAME)
    else:
        # 不阻断启动：方便前端联调、跑单测、生成文档
        logger.warning("MySQL 连接失败，请检查 .env；服务仍会启动，但数据库接口不可用")

    logger.info("AI 信誉画像：%s", "DeepSeek 已启用" if settings.ai_available else "未配置 API Key，走本地规则版")
    logger.info("小黑屋默认禁赛时长：%s 天", settings.BAN_DEFAULT_DAYS)
    logger.info("密码哈希：bcrypt（cost=%s）", settings.BCRYPT_ROUNDS)

    # 启动后台任务：仅在「常驻进程」形态下才有意义（Serverless 每次调用是独立容器，
    # asyncio 循环无法常驻，因此 Serverless 改用惰性判断 + Vercel Cron，详见 app/api/v1/system.py）
    tasks = []
    if settings.SERVERLESS_MODE:
        logger.info("部署形态：Serverless（已关闭进程内定时任务）")
        logger.info("兜底策略：小黑屋惰性解封 + 球局读取时就地补判缺席 + 画像按需重算")
        logger.info("定时兜底：Vercel Cron 每日调用 /api/v1/system/cron/daily（需配置 CRON_SECRET）")
    else:
        tasks.append(asyncio.create_task(_release_loop()))
        if settings.ABSENT_SCAN_ENABLED:
            tasks.append(asyncio.create_task(_absent_scan_loop()))
            logger.info("缺席判定兜底扫描：每 %s 秒执行一次", settings.ABSENT_SCAN_INTERVAL_SECONDS)
        else:
            logger.info("缺席判定兜底扫描：已关闭（ABSENT_SCAN_ENABLED=false）")
        tasks.append(asyncio.create_task(_ai_profile_loop()))
        logger.info(
            "AI 画像：%s；兜底重算每 %s 秒一次",
            "DeepSeek 已启用" if ai_profile_service.ai_profile_service.available else "未配置 API Key，走本地加权规则版",
            settings.AI_PROFILE_SCAN_INTERVAL_SECONDS,
        )
    logger.info("=" * 60)

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await dispose_engine()
        logger.info("%s 已关闭", settings.PROJECT_NAME)


# ==================================================================
# 应用工厂
# ==================================================================
def create_app() -> FastAPI:
    """创建 FastAPI 实例（工厂模式，方便测试时按需构造）"""
    application = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=(
            "搭子月球后端接口：用户认证（bcrypt + JWT）、约球、报名、签到、"
            "失信小黑屋、AI 信誉画像。\n\n"
            "**鉴权方式**：先调用 `/api/v1/auth/login` 获取 `access_token`，"
            "再点击右上角 Authorize 填入令牌（或请求头 `Authorization: Bearer <token>`）。"
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ---------------- 中间件（★注册顺序即执行顺序的逆序） ----------------
    # Starlette 中「后注册的中间件在更外层」：
    #   1) 先注册 AuthMiddleware（内层）：JWT 鉴权 + 小黑屋/账号状态统一拦截
    #   2) 再注册 CORSMiddleware（外层）：保证被 401/403 拦截的响应也带 CORS 头，
    #      前端才能读到 code=40101（令牌过期）/ code=403（小黑屋）这样的业务错误码
    application.add_middleware(AuthMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,   # 前端 Vue3 开发地址，见 .env
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # ---------------- 全局异常处理 ----------------
    register_exception_handlers(application)

    # ---------------- 路由 ----------------
    application.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # ---------------- 健康检查 ----------------
    @application.get("/health", response_model=ApiResponse[dict], tags=["系统"], summary="健康检查")
    async def health():
        """探活用；database=false 表示数据库暂时不可用"""
        db_ok = await check_database_connection()
        return ApiResponse.ok(
            {
                "status": "ok" if db_ok else "degraded",
                "env": settings.ENV,
                "version": settings.VERSION,
                "database": db_ok,
                "ai_available": settings.ai_available,
                "auth_enabled": settings.AUTH_ENABLED,
                "auth_hooks": list_auth_hooks(),
                "password_scheme": f"bcrypt(cost={settings.BCRYPT_ROUNDS})",
            }
        )

    return application


app = create_app()


if __name__ == "__main__":  # pragma: no cover - 本地调试入口
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
