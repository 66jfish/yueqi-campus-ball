"""
签到 / 核销 / 缺席判定接口  ★惰性结算的三个入口★
====================================================================
路径前缀：/api/v1/checkin
    1. POST /verify              ⑥ 发起人核销到场用户（批量）→ 触发惰性结算
    2. GET  /game/{game_id}      核销名单（发起人视图：谁到了、谁没到）
    3. POST /checkin             本人扫码/定位签到 → 触发惰性结算
    4. POST /leave               请假（不扣分，避免被判缺席）
    5. POST /absent-judgement    球局结束后判定缺席 → 批量惰性结算 + 自动封禁
    6. GET  /my                  我的签到记录（含待结算标记）

惰性结算说明：
    信誉分不实时计算；只有「核销/签到」与「判定缺席」两个时机触发结算，
    结算依据是 t_checkin_record.settled 标记（0-待结算 / 1-已结算）。

详细文档：docs/API_GAME.md 第四、五节
====================================================================
"""

from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.constants import CheckinStatus, CheckinType, GameStatus, SettleStatus
from app.core.exceptions import ConflictException
from app.core.response import ApiResponse
from app.models import CheckinRecord
from app.schemas import (
    AbsentJudgementOut,
    AbsentJudgementRequest,
    CheckinRecordOut,
    CheckinRequest,
    CheckinSettleOut,
    LeaveRequest,
    VerifyCheckinItemOut,
    VerifyCheckinRequest,
    VerifyCheckinResultOut,
    VerifyRosterOut,
)
from app.services import checkin as checkin_service
from app.services import game as game_service
from app.services import reputation as reputation_service

router = APIRouter(prefix="/checkin", tags=["签到与核销"])


# ==================================================================
# ⑥ 发起人核销到场用户（本次核心接口）
# ==================================================================
@router.post(
    "/verify",
    response_model=ApiResponse[VerifyCheckinResultOut],
    summary="⑥ 签到核销（发起人给到场用户签到）",
    description=(
        "球局发起人为到场用户核销签到，**逐人返回结果并即时触发惰性结算**。\n\n"
        "**规则**：\n"
        "- 仅球局发起人可核销（非发起人返回 `40300 只有球局发起人可以执行该操作`）\n"
        "- 核销窗口：球局自身 `checkin_start_time`~`checkin_end_time`，未配置则按「开球前30分钟开放 / 开球后15分钟截止」\n"
        "- 窗口内核销 → 正常签到（信誉分 +2）；超过截止 → 迟到（-3）\n"
        "- 未开放时核销 → `40900 核销尚未开放，xx:xx 起可核销`\n"
        "- 已核销 / 已请假 → 跳过并说明原因（幂等，不会重复加分）\n"
        "- 球局已完成结算 → `40900 该球局已完成结算，无法再核销`\n"
        "- 未报名/已退出的用户 → 该条失败并说明原因，不影响其他人生效\n"
        "- 结算后信誉分低于阈值 → 自动进小黑屋，结果里 `banned=true`"
    ),
    responses={
        200: {
            "description": "核销完成（含部分失败，逐条看 items）",
            "content": {
                "application/json": {
                    "example": {
                        "code": 0,
                        "message": "核销完成：成功 2 人",
                        "data": {
                            "game_id": 101,
                            "verified_count": 2,
                            "skipped_count": 0,
                            "failed_count": 1,
                            "checkin_open_at": "2026-11-20T18:30:00",
                            "checkin_close_at": "2026-11-20T19:15:00",
                            "items": [
                                {
                                    "user_id": 2,
                                    "nickname": "羽毛球爱好者",
                                    "ok": True,
                                    "skipped": False,
                                    "reason": None,
                                    "checkin_status": 1,
                                    "checkin_status_text": "已签到",
                                    "credit_before": 92,
                                    "credit_delta": 2,
                                    "credit_after": 94,
                                    "banned": False,
                                    "ban_end_time": None,
                                },
                                {
                                    "user_id": 9,
                                    "nickname": None,
                                    "ok": False,
                                    "skipped": False,
                                    "reason": "该用户未报名此球局或已退出，无法核销",
                                    "checkin_status": None,
                                    "credit_delta": None,
                                },
                            ],
                        },
                    }
                }
            },
        },
        403: {
            "description": "非发起人 / 处于小黑屋（封禁期间禁止发局与报名）",
            "content": {
                "application/json": {
                    "examples": {
                        "非发起人": {
                            "value": {"code": 40300, "message": "只有球局发起人可以执行该操作", "data": None}
                        },
                        "小黑屋": {
                            "value": {
                                "code": 403,
                                "msg": "您因放鸽子被禁赛，将于 2026-11-21 20:00 解除",
                                "message": "您因放鸽子被禁赛，将于 2026-11-21 20:00 解除",
                                "data": {
                                    "banned": True,
                                    "ban_end_time": "2026-11-21T20:00:00",
                                    "ban_duration_days": 3,
                                    "ban_extend_count": 0,
                                    "reason": "缺席球局（未签到且未请假），球局ID=100",
                                    "reason_type": 1,
                                },
                            }
                        },
                    }
                }
            },
        },
        409: {
            "description": "核销不可用",
            "content": {
                "application/json": {
                    "examples": {
                        "未开放": {"value": {"code": 40900, "message": "核销尚未开放，11-20 18:30 起可核销（开球前 30 分钟）", "data": None}},
                        "已结算": {"value": {"code": 40900, "message": "该球局已完成结算，无法再核销；如需更正请联系管理员申诉", "data": None}},
                        "已取消": {"value": {"code": 40900, "message": "该球局已取消，无法核销签到", "data": None}},
                    }
                }
            },
        },
    },
)
async def verify_checkin(payload: VerifyCheckinRequest, current_user: CurrentUser, db: DbSession):
    """发起人核销：标记到场状态 + 触发惰性结算"""
    game = await game_service.get_game(db, payload.game_id)
    # 仅发起人可核销
    game_service.assert_is_creator(game, current_user)

    result = await checkin_service.verify_checkin(
        db,
        game=game,
        operator=current_user,
        user_ids=payload.user_ids,
        verify_all=payload.verify_all,
        as_late=payload.as_late,
        remark=payload.remark,
    )

    data = VerifyCheckinResultOut(
        game_id=result.game_id,
        verified_count=result.verified_count,
        skipped_count=result.skipped_count,
        failed_count=result.failed_count,
        checkin_open_at=result.checkin_window[0] if result.checkin_window else None,
        checkin_close_at=result.checkin_window[1] if result.checkin_window else None,
        items=[VerifyCheckinItemOut(**item.to_dict()) for item in result.items],
    )

    # 汇总提示：让发起人一眼看到结果
    parts = [f"成功 {result.verified_count} 人"]
    if result.skipped_count:
        parts.append(f"跳过 {result.skipped_count} 人")
    if result.failed_count:
        parts.append(f"失败 {result.failed_count} 人")
    return ApiResponse.ok(data, message="核销完成：" + "，".join(parts))


# ==================================================================
# 核销名单（发起人视图）
# ==================================================================
@router.get(
    "/game/{game_id}",
    response_model=ApiResponse[VerifyRosterOut],
    summary="核销名单（发起人查看谁到了、谁没到）",
    description=(
        "返回正式报名者的签到状态与到场统计，供发起人在核销页一键勾选核销。\n"
        "仅发起人可查看全体名单（含他人信誉分）。"
    ),
    responses={403: {"description": "非发起人", "content": {"application/json": {"example": {"code": 40300, "message": "只有球局发起人可以执行该操作", "data": None}}}}},
)
async def verify_roster(game_id: int, current_user: CurrentUser, db: DbSession):
    """核销名单 + 到场统计"""
    game = await game_service.get_game(db, game_id)
    data = await checkin_service.get_verify_roster(db, game, current_user)
    return ApiResponse.ok(data)


# ==================================================================
# 本人签到（扫码 / 定位打卡）
# ==================================================================
@router.post(
    "/checkin",
    response_model=ApiResponse[CheckinSettleOut],
    summary="本人签到（扫码/定位打卡，触发惰性结算）",
    description="球友自行扫码或定位打卡；超过球局核销截止时间记为迟到。签到后立即结算并返回信誉分变动。",
)
async def do_checkin(payload: CheckinRequest, current_user: CurrentUser, db: DbSession):
    """本人签到 → 触发惰性结算"""
    game = await game_service.get_game(db, payload.game_id)
    if game.status in (GameStatus.CANCELED, GameStatus.FINISHED):
        raise ConflictException("该球局已结束或已取消，无法签到")

    open_at, close_at = checkin_service.effective_checkin_window(game)
    now = datetime.now()
    if now < open_at:
        raise ConflictException(f"签到尚未开放，{open_at:%m-%d %H:%M} 起可签到")
    status = CheckinStatus.LATE if now > close_at else CheckinStatus.CHECKED

    result = await reputation_service.settle_on_checkin(
        db,
        game_id=payload.game_id,
        user_id=current_user.id,
        checkin_status=status,
        checkin_type=payload.checkin_type or CheckinType.QR_CODE,
        location_lat=payload.location_lat,
        location_lng=payload.location_lng,
        remark=payload.remark,
    )

    message = "签到成功" if status == CheckinStatus.CHECKED else "签到成功（迟到）"
    data = CheckinSettleOut(
        success=True,
        message=message,
        user_id=current_user.id,
        credit_before=result.credit_before if result else current_user.credit_score,
        credit_delta=result.credit_delta if result else 0,
        credit_after=result.credit_after if result else current_user.credit_score,
        credit_level=result.credit_level if result else current_user.credit_level,
        settled_record_count=result.settled_record_count if result else 0,
        banned=result.banned if result else False,
        ban_end_time=result.ban_end_time if result else None,
    )
    return ApiResponse.ok(data, message=message)


@router.post(
    "/leave",
    response_model=ApiResponse[CheckinSettleOut],
    summary="请假（不扣分）",
    description="请假不扣信誉分，但会写入签到记录，避免球局结束后被判定为缺席。",
)
async def do_leave(payload: LeaveRequest, current_user: CurrentUser, db: DbSession):
    """请假"""
    game = await game_service.get_game(db, payload.game_id)
    if game.settle_status != SettleStatus.PENDING:
        raise ConflictException("该球局已完成结算，无法再请假")
    if game.status == GameStatus.CANCELED:
        raise ConflictException("该球局已取消")

    result = await reputation_service.settle_on_checkin(
        db,
        game_id=payload.game_id,
        user_id=current_user.id,
        checkin_status=CheckinStatus.LEAVE,
        remark=payload.remark,
    )
    data = CheckinSettleOut(
        success=True,
        message="已提交请假",
        user_id=current_user.id,
        credit_delta=result.credit_delta if result else 0,
        settled_record_count=result.settled_record_count if result else 0,
    )
    return ApiResponse.ok(data, message="已提交请假")


@router.post(
    "/absent-judgement",
    response_model=ApiResponse[AbsentJudgementOut],
    summary="缺席判定（发起人，批量惰性结算）",
    description=(
        "球局结束后调用：把「未签到且未请假」的报名者标记为缺席（-10 分），"
        "批量触发惰性结算；结算后信誉分低于阈值的自动进小黑屋（默认3天）。\n"
        "核销过的用户不会被判缺席 —— 核销与缺席判定同源，互为校验。"
    ),
)
async def judge_absent(payload: AbsentJudgementRequest, current_user: CurrentUser, db: DbSession):
    """缺席判定"""
    game = await game_service.get_game(db, payload.game_id)
    game_service.assert_is_creator(game, current_user)

    result = await reputation_service.settle_on_absent_judgement(
        db,
        game_id=payload.game_id,
        operator_id=current_user.id,
        auto_prune=payload.auto_prune,
    )
    return ApiResponse.ok(
        AbsentJudgementOut(
            game_id=result["game_id"],
            absent_count=result["absent_count"],
            settled_users=result["settled_users"],
            message=result.get("message", "判定完成"),
        ),
        message="缺席判定完成",
    )


@router.get("/my", response_model=ApiResponse[list[CheckinRecordOut]], summary="我的签到记录")
async def my_checkin_records(current_user: CurrentUser, db: DbSession, limit: int = 20):
    """我的签到记录；settled=0 表示该条记录仍待结算（分数尚未折算）"""
    stmt = (
        select(CheckinRecord)
        .where(CheckinRecord.user_id == current_user.id)
        .order_by(CheckinRecord.id.desc())
        .limit(limit)
    )
    records = list((await db.execute(stmt)).scalars().all())
    return ApiResponse.ok(
        [
            CheckinRecordOut(
                id=r.id,
                game_id=r.game_id,
                user_id=r.user_id,
                checkin_status=r.checkin_status,
                checkin_type=r.checkin_type,
                checkin_time=r.checkin_time,
                credit_delta=r.credit_delta,
                settled=r.settled,
                settled_at=r.settled_at,
            )
            for r in records
        ]
    )
