"""
小黑屋接口：状态查询 / 封禁记录查询 / 手动封禁 / 解封 / 兜底扫描
====================================================================
路径前缀：/api/v1/blacklist

    GET  /me               我的封禁状态（白名单：被封禁也能查，含解禁时间与倒计时）
    GET  /records          封禁记录分页查询（本人=自己的历史；管理员=全部，支持筛选）
    GET  /                 管理端封禁记录列表（简版，等价于 /records，保留兼容）
    POST /ban              管理端手动封禁（默认 3 天；已在封禁中默认顺延）
    POST /release          管理端手动解封
    POST /release-expired  手动触发一次「到期解封」留痕批处理（拦截本身不依赖它）
    POST /scan-absent      手动触发一次「缺席判定兜底扫描」（漏判补偿）

规则要点：
    规则3 查询类接口不拦截 —— 因此 GET /me、GET /records 均在中间件白名单内
    规则4 自动解封为惰性判断（ban_end_time > NOW()），不依赖定时任务
====================================================================
"""

import math
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession, get_current_admin
from app.core.config import settings
from app.core.constants import BanReasonType
from app.core.response import ApiResponse
from app.models import User
from app.schemas import (
    AbsentScanResultOut,
    BanCreateRequest,
    BanRecordPageOut,
    BanReleaseRequest,
    BlacklistOut,
    MyBanStatusOut,
    VerifyRosterOut,
)
from app.services import blacklist as blacklist_service
from app.services import checkin as checkin_service

router = APIRouter(prefix="/blacklist", tags=["小黑屋"])

# 封禁期间被禁止的动作说明（与 services/blacklist.py::BAN_BLOCKED_PATTERNS 对应）
BLOCKED_ACTION_TEXT = ["发起球局（POST /api/v1/game）", "报名加入球局（POST /api/v1/game/{id}/signup）"]

REASON_TYPE_TEXT = {
    BanReasonType.ABSENT: "缺席未到（放鸽子）",
    BanReasonType.LATE_ACCUMULATED: "多次迟到累计",
    BanReasonType.LOW_CREDIT: "信誉分过低",
    BanReasonType.MANUAL: "管理员人工封禁",
}


# ==================================================================
# 我的封禁状态（白名单接口）
# ==================================================================
@router.get(
    "/me",
    response_model=ApiResponse[MyBanStatusOut],
    summary="我的封禁状态（含解禁时间与历史记录）",
    description=(
        "被封禁状态说明：\n"
        "- 封禁期间**只拦截发起球局与报名**，查询类接口、签到/核销、退出球局均可正常使用\n"
        "- 是否仍在封禁期由 `ban_end_time > 当前时间` 惰性判定，到期即自动解封，无需等待定时任务\n"
        "- `history` 返回全部历史封禁记录（永久留存，含 reason），可用于申诉与信誉画像"
    ),
)
async def my_ban_status(current_user: CurrentUser, db: DbSession):
    """查询自己的禁赛状态（白名单：即便被封禁也能访问）"""
    ban = await blacklist_service.get_active_ban(db, current_user.id, use_cache=False)
    records, total = await blacklist_service.list_bans(
        db, user_id=current_user.id, page=1, page_size=20
    )

    return ApiResponse.ok(
        MyBanStatusOut(
            banned=ban is not None,
            ban_end_time=ban.ban_end_time if ban else None,
            remaining_hours=ban.remaining_hours() if ban else None,
            ban_start_time=ban.ban_start_time if ban else None,
            ban_duration_days=ban.ban_duration_days if ban else None,
            ban_extend_count=ban.extend_count if ban else 0,
            reason=ban.reason if ban else None,
            reason_type=ban.reason_type if ban else None,
            blocked_actions=BLOCKED_ACTION_TEXT if ban else [],
            message=ban.message() if ban else "您当前没有封禁记录，可正常参与球局",
            history=[BlacklistOut.model_validate(item) for item in records],
            total_ban_count=total,
        )
    )


# ==================================================================
# 封禁记录查询（分页 + 筛选）
# ==================================================================
@router.get(
    "/records",
    response_model=ApiResponse[BanRecordPageOut],
    summary="封禁记录查询（分页，永久留存）",
    description=(
        "查询封禁记录：\n"
        "- 普通用户只返回自己的记录（`user_id` 参数会被忽略，防止越权查看他人）\n"
        "- 管理员（学号白名单）可查全部，并支持 `user_id` / `only_active` / `reason_type` 筛选\n"
        "- `only_active=true` 只返回当前仍在封禁期的记录；默认返回含已解封的全部历史"
    ),
)
async def query_ban_records(
    current_user: CurrentUser,
    db: DbSession,
    user_id: int | None = Query(None, description="按用户ID筛选（仅管理员可用）"),
    only_active: bool = Query(False, description="只看当前仍在封禁期的记录"),
    reason_type: int | None = Query(None, ge=1, le=4, description="按封禁原因筛选"),
    include_released: bool = Query(True, description="是否包含已解封的历史记录"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
):
    """封禁记录分页查询"""
    is_admin = current_user.student_no in {"admin"}  # TODO: 迁移到 RBAC
    target_user_id = user_id if (is_admin and user_id) else current_user.id

    records, total = await blacklist_service.list_bans(
        db,
        user_id=target_user_id,
        only_active=only_active,
        reason_type=reason_type,
        include_released=include_released,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.ok(
        BanRecordPageOut(
            items=[BlacklistOut.model_validate(r) for r in records],
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if page_size else 0,
        )
    )


@router.get("", response_model=ApiResponse[BanRecordPageOut], summary="封禁记录列表（管理端）")
async def list_bans_admin(
    db: DbSession,
    admin: User = Depends(get_current_admin),
    user_id: int | None = Query(None, description="按用户ID筛选"),
    only_active: bool = Query(False, description="只看封禁中（惰性判定）"),
    reason_type: int | None = Query(None, ge=1, le=4, description="按原因筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """管理端封禁记录列表（等价于 /records 的管理员视角）"""
    records, total = await blacklist_service.list_bans(
        db, user_id=user_id, only_active=only_active, reason_type=reason_type,
        page=page, page_size=page_size,
    )
    return ApiResponse.ok(
        BanRecordPageOut(
            items=[BlacklistOut.model_validate(r) for r in records],
            total=total, page=page, page_size=page_size,
            pages=math.ceil(total / page_size) if page_size else 0,
        )
    )


# ==================================================================
# 管理端：封禁 / 解封 / 兜底扫描
# ==================================================================
@router.post(
    "/ban",
    response_model=ApiResponse[dict],
    summary="手动封禁（管理端，默认 3 天）",
    description=(
        "把用户关进小黑屋。\n"
        "- 用户**已在封禁中**时：默认按规则6 **顺延**原记录（不新建，避免叠加封禁）；"
        "如需强制新建一条记录请传 `force_new=true`\n"
        "- 封禁时长固定按 `days`（默认 `BAN_DEFAULT_DAYS=3`），`ban_end_time = ban_start_time + 时长`"
    ),
)
async def create_ban(
    payload: BanCreateRequest, db: DbSession, admin: User = Depends(get_current_admin)
):
    """手动封禁"""
    applied = await blacklist_service.apply_ban(
        db,
        user_id=payload.user_id,
        reason_type=payload.reason_type,
        reason=payload.reason,
        days=payload.days,
        trigger_game_id=payload.trigger_game_id,
        operator_id=admin.id,
        allow_extend=not payload.force_new,
    )
    return ApiResponse.ok(
        {
            "ban": BlacklistOut.model_validate(applied.ban).model_dump(),
            "created": applied.created,
            "extended_days": applied.extended_days,
            "capped": applied.capped,
            "message": applied.message,
        },
        message="已加入小黑屋" if applied.created else f"用户已在封禁中，已顺延 {applied.extended_days} 天",
    )


@router.post("/release", response_model=ApiResponse[dict], summary="手动解封（管理端）")
async def release_ban(
    payload: BanReleaseRequest, db: DbSession, admin: User = Depends(get_current_admin)
):
    """手动解封：把解禁时间提前到当前时间"""
    ok = await blacklist_service.release_ban(
        db,
        ban_id=payload.ban_id,
        release_type=payload.release_type,
        operator_id=admin.id,
        remark=payload.remark,
    )
    if not ok:
        return ApiResponse.fail(code=40400, message="记录不存在或已自动解封（解禁时间已过）")
    return ApiResponse.ok({"ban_id": payload.ban_id, "released": True}, message="已解封")


@router.post(
    "/release-expired",
    response_model=ApiResponse[dict],
    summary="触发到期解封留痕（管理端/运维）",
    description="把已到期记录标记为「已解封」仅用于留痕；拦截判断始终是惰性判定，不依赖本任务。",
)
async def release_expired(db: DbSession, admin: User = Depends(get_current_admin)):
    count = await blacklist_service.release_expired_bans(db)
    return ApiResponse.ok({"released_count": count}, message=f"本次标记解封 {count} 条记录")


@router.post(
    "/scan-absent",
    response_model=ApiResponse[AbsentScanResultOut],
    summary="缺席判定兜底扫描（管理端/运维，漏判补偿）",
    description=(
        "扫描「已过结束时间但仍未结算」的球局，逐个结束并执行缺席判定：\n"
        "已报名 + 未签到 + 未请假 → 缺席（-10 分）→ 自动进小黑屋 3 天。\n"
        "生产环境由后台定时任务每小时自动执行一次，此接口用于手动补偿。"
    ),
)
async def scan_absent(db: DbSession, admin: User = Depends(get_current_admin)):
    result = await checkin_service.scan_overdue_games(db)
    return ApiResponse.ok(
        AbsentScanResultOut(**result),
        message=f"扫描 {result['scanned']} 场，判定缺席 {result['absent_total']} 人次",
    )


@router.get(
    "/config",
    response_model=ApiResponse[dict],
    summary="查看当前小黑屋规则配置（便于前端展示与排查）",
)
async def ban_config(current_user: CurrentUser):
    """返回当前生效的封禁规则参数"""
    return ApiResponse.ok(
        {
            "ban_days": settings.BAN_DEFAULT_DAYS,
            "ban_on_absent": settings.BAN_ON_ABSENT,
            "extend_on_repeat": settings.BAN_EXTEND_ON_REPEAT,
            "max_total_days": settings.BAN_MAX_TOTAL_DAYS,
            "block_all_writes": settings.BAN_BLOCK_ALL_WRITES,
            "blocked_actions": BLOCKED_ACTION_TEXT,
            "absent_deduct_score": 10,
            "lazy_release": True,
            "lazy_release_rule": "ban_end_time > NOW() 即视为封禁中，到期自动解封，不依赖定时任务",
            "scan_interval_seconds": settings.ABSENT_SCAN_INTERVAL_SECONDS,
            "reason_type_text": {str(k): v for k, v in REASON_TYPE_TEXT.items()},
            "now": datetime.now().isoformat(),
        }
    )
