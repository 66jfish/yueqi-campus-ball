"""
系统 / 运维接口（含 Vercel Cron 定时任务入口）
====================================================================
路径前缀：/api/v1/system

设计说明（对应需求「定时任务能配就配，不能配就去掉并说明」）：
    Vercel Serverless 无法常驻进程内的 asyncio 循环（老版本 app/main.py 里的
    _release_loop / _absent_scan_loop / _ai_profile_loop 在 Serverless 上根本不执行），
    因此本模块改为：

    ① 惰性判断为主（不依赖任何定时任务）
        · 小黑屋是否仍在封禁：查询时用 ban_end_time > NOW() 判定，到期自动失效
        · 球局漏判缺席：读取球局详情/列表时就地补判（services/game.py::maybe_finalize_overdue）
        · AI 画像：读取画像/个人主页时按 dirty 标记按需重算

    ② 定时任务作为「兜底加速」（能配就配）
        · Vercel Cron：Hobby 套餐只支持「每天一次」，因此配 1 条每日任务，
          一次性完成「漏判扫描 + 到期解封留痕 + 画像批量重算」三件事
        · Pro 套餐可把频率改成每小时：schedule 改为 "0 * * * *"
        · 不配 Cron 也不影响正确性：所有状态都有惰性判断兜底，只是「被动等待访问」触发

    ③ 手工触发：同样的接口带 token 用 curl 调一次即可（部署后排查用）
====================================================================
"""

import logging

from fastapi import APIRouter, Header, Query

from app.api.deps import DbSession
from app.core.config import settings
from app.core.exceptions import ForbiddenException
from app.core.response import ApiResponse
from app.services import ai_profile as ai_profile_service
from app.services import blacklist as blacklist_service
from app.services import checkin as checkin_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["系统与定时任务"])


def _assert_cron_token(token: str | None, authorization: str | None) -> None:
    """
    校验定时任务凭证：
        Vercel Cron 在配置了 CRON_SECRET 环境变量时会自动带上 `Authorization: Bearer <CRON_SECRET>`；
        同时兼容 `?token=xxx` 手工调用。未配置 CRON_SECRET 时一律拒绝（安全默认）。
    """
    if not settings.CRON_SECRET:
        raise ForbiddenException("未配置 CRON_SECRET，定时任务接口已禁用")

    if token and token == settings.CRON_SECRET:
        return
    if authorization and authorization.lower().startswith("bearer "):
        if authorization[7:].strip() == settings.CRON_SECRET:
            return
    raise ForbiddenException("定时任务凭证无效")


@router.get(
    "/cron/daily",
    response_model=ApiResponse[dict],
    summary="每日定时任务（Vercel Cron 调用）：漏判扫描 + 到期解封留痕 + 画像重算",
    description=(
        "由 vercel.json 的 crons 配置每天 03:00 触发（Hobby 套餐限制为每天一次）。\n"
        "三件事一次完成：\n"
        "1. `缺席判定兜底扫描`：把「已过结束时间但未结算」的球局结束掉并判定缺席\n"
        "2. `到期解封留痕`：把过期封禁记录标记为已解封（拦截本身是惰性判断，不依赖它）\n"
        "3. `AI 画像批量重算`：把 dirty=1 的用户画像重算（大模型不可用时自动降级本地规则）\n\n"
        "鉴权：`Authorization: Bearer <CRON_SECRET>`（Vercel Cron 自动携带）或 `?token=<CRON_SECRET>`"
    ),
)
async def cron_daily(
    db: DbSession,
    token: str | None = Query(None, description="定时任务凭证（与 CRON_SECRET 一致）"),
    authorization: str | None = Header(None),
):
    """每日兜底任务"""
    _assert_cron_token(token, authorization)

    absent = await checkin_service.scan_overdue_games(db)
    released = await blacklist_service.release_expired_bans(db)
    profiles = await ai_profile_service.refresh_dirty_profiles(db)

    logger.warning(
        "每日定时任务完成：漏判扫描 %s 场（缺席 %s 人次）｜解封留痕 %s 条｜画像重算 %s 人",
        absent["scanned"], absent["absent_total"], released, profiles["refreshed"],
    )
    return ApiResponse.ok(
        {
            "absent_scan": absent,
            "released_bans": released,
            "profile_refreshed": profiles,
            "note": "小黑屋拦截为惰性判断（ban_end_time > NOW()），本任务仅做留痕与兜底加速",
        },
        message="每日兜底任务完成",
    )


@router.get(
    "/runtime",
    response_model=ApiResponse[dict],
    summary="运行时信息（部署形态 / 惰性策略 / 定时任务配置）",
)
async def runtime_info(db: DbSession):
    """
    部署后排查用：一眼看清当前是 Serverless 还是常驻、定时任务有没有配、
    惰性判断是否生效（不需要登录，仅暴露非敏感信息）。
    """
    import sys

    return ApiResponse.ok(
        {
            "serverless_mode": settings.SERVERLESS_MODE,
            "python": sys.version.split()[0],
            "env": settings.ENV,
            "lazy_strategies": {
                "ban_release": "查询时 ban_end_time > NOW() 即视为封禁中，到期自动失效（不依赖定时任务）",
                "absent_judgement": "读取球局时若已过结束时间且未结算，就地补判缺席",
                "ai_profile": "读取画像/个人主页时按 ai_profile_dirty 标记按需重算",
            },
            "cron": {
                "enabled": bool(settings.CRON_SECRET),
                "endpoint": "/api/v1/system/cron/daily",
                "schedule_in_vercel": "0 3 * * *（Hobby 仅支持每天一次；Pro 可改 0 * * * * 每小时）",
            },
            "db": {
                "host_configured": bool(settings.DB_HOST),
                "database": settings.DB_NAME,
                "require_ssl": settings.DB_REQUIRE_SSL,
                "pool": "NullPool（Serverless）" if (settings.DB_USE_NULL_POOL or settings.SERVERLESS_MODE) else "QueuePool（常驻）",
            },
            "ai": {
                "llm_available": ai_profile_service.ai_profile_service.available,
                "model": settings.DEEPSEEK_MODEL if ai_profile_service.ai_profile_service.available else None,
            },
        }
    )
