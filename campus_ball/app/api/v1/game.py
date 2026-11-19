"""
球局接口：发起 / 列表 / 详情 / 报名 / 退出 / 名单
====================================================================
路径前缀：/api/v1/game
鉴权：本组路径为「可选登录」——列表与详情匿名可读，
      发起 / 报名 / 退出等写操作由 CurrentUser 依赖强制登录；
      处于小黑屋的用户在中间件钩子层就被 403 拦截（接口内无需重复判断）。

统一响应：{"code": 0, "message": "ok", "data": {...}}
详细文档（参数表 + 返回示例 + 异常码）：docs/API_GAME.md
====================================================================
"""

import math
from datetime import datetime

from fastapi import APIRouter, Query

from app.api.deps import CurrentActiveUser, CurrentUser, DbSession, OptionalUser
from app.core.config import settings
from app.core.constants import skill_text
from app.core.response import ApiResponse
from app.schemas import (
    ExitGameResult,
    GameCreateRequest,
    GameDetailOut,
    GameListItem,
    GameOut,
    GamePageOut,
    RegistrationOut,
    RosterMemberOut,
    SignupRequest,
    SignupResult,
)
from app.services import checkin as checkin_service
from app.services import game as game_service

router = APIRouter(prefix="/game", tags=["球局"])


# ==================================================================
# 1. 发起球局
# ==================================================================
@router.post(
    "",
    response_model=ApiResponse[GameOut],
    summary="① 发起球局",
    description=(
        "创建球局，创建后状态为「报名中」，发起人自动占 1 个名额。\n\n"
        "**冲突校验**：\n"
        "- 同一（校区, 场地）在同一时段已有未取消球局 → `40900 场地冲突`\n"
        "- 发起人同一时段已报名其它球局 → `40900 时间冲突`\n"
        "- 未填核销窗口时，自动按「开球前30分钟开放 / 开球后15分钟截止」推算"
    ),
    responses={
        409: {
            "description": "场地冲突 / 时间冲突",
            "content": {
                "application/json": {
                    "examples": {
                        "场地冲突": {
                            "value": {
                                "code": 40900,
                                "message": "场地冲突：老校区体育馆 3 号场 在 11-20 19:00~21:00 已被「周五晚东区篮球局」占用，请更换场地或调整时间",
                                "data": None,
                            }
                        },
                        "时间冲突": {
                            "value": {
                                "code": 40900,
                                "message": "时间冲突：您在同一时段已加入「羽毛球双打」（11-20 19:30~21:00），无法再发起球局",
                                "data": None,
                            }
                        },
                    }
                }
            },
        }
    },
)
async def create_game(payload: GameCreateRequest, current_user: CurrentActiveUser, db: DbSession):
    """
    发起球局：场地冲突 → 发起人时间冲突 → 落库。

    鉴权使用 CurrentActiveUser：小黑屋封禁期间调用会被拦截，返回
        {"code": 403, "msg": "您因放鸽子被禁赛，将于 2026-11-21 20:00 解除"}
    """
    game = await game_service.create_game(db, current_user, payload)
    row = await game_service.get_game_row(db, game, current_user.id)
    return ApiResponse.ok(_to_game_out(row), message="球局创建成功")


# ==================================================================
# 2. 球局列表
# ==================================================================
@router.get(
    "",
    response_model=ApiResponse[GamePageOut],
    summary="② 球局列表（筛选 + 分页）",
    description=(
        "支持运动类型、校区、场地、状态、关键词、时间区间、发起人、只看未满等筛选。\n\n"
        "- `sport_type` **不传 → 返回全部球类**；传值（1-6）→ 按球类过滤\n"
        "- `match_score` 为 **AI 匹配分，当前返回静态固定占位值 80.0**，"
        "AI 智能匹配模块接入后替换为按用户画像实时计算的值，字段结构不变\n"
        "- 登录后还会返回 `my_registration_status` / `my_checkin_status`，便于前端标记「已报名」"
    ),
)
async def list_games(
    db: DbSession,
    current_user: OptionalUser,
    sport_type: int | None = Query(
        None,
        ge=1,
        le=6,
        description="球类筛选：1-篮球 2-足球 3-羽毛球 4-网球 5-排球 6-乒乓球；**不传则返回全部球类**",
    ),
    campus: str | None = Query(None, max_length=64, description="校区"),
    venue_name: str | None = Query(None, max_length=64, description="场地名称（模糊匹配）"),
    status: int | None = Query(None, ge=0, le=5, description="球局状态：1-报名中 2-报名截止 3-进行中 4-已结束 5-已取消"),
    keyword: str | None = Query(None, max_length=64, description="关键词（匹配标题/描述）"),
    start_date: datetime | None = Query(None, description="开球时间下界（含），如 2026-11-20T00:00:00"),
    end_date: datetime | None = Query(None, description="开球时间上界（含）"),
    creator_id: int | None = Query(None, description="按发起人筛选"),
    only_available: bool = Query(False, description="只看报名中且未满的球局"),
    sort_desc: bool = Query(False, description="false=按开球时间升序（默认） true=降序"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(
        10, ge=1, le=settings.GAME_MAX_PAGE_SIZE, description=f"每页条数，最大 {settings.GAME_MAX_PAGE_SIZE}"
    ),
):
    """球局列表：默认按开球时间升序"""
    rows, total = await game_service.list_games(
        db,
        sport_type=sport_type,
        campus=campus,
        venue_name=venue_name,
        status=status,
        keyword=keyword,
        start_date=start_date,
        end_date=end_date,
        creator_id=creator_id,
        only_available=only_available,
        sort_desc=sort_desc,
        page=page,
        page_size=page_size,
        current_user_id=current_user.id if current_user else None,
        with_match_score=settings.AI_MATCH_SCORE_ENABLED,
    )
    data = GamePageOut(
        items=[GameListItem.model_validate(_to_game_out(row)) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if page_size else 0,
    )
    return ApiResponse.ok(data)


# ==================================================================
# 3. 球局详情
# ==================================================================
@router.get(
    "/{game_id}",
    response_model=ApiResponse[GameDetailOut],
    summary="③ 球局详情",
    description="返回球局全部信息 + 发起人信息 + 名额情况 + 核销统计 + 当前用户在该球局的状态。",
    responses={404: {"description": "球局不存在", "content": {"application/json": {"example": {"code": 40400, "message": "球局不存在或已删除", "data": None}}}}},
)
async def get_game_detail(game_id: int, db: DbSession, current_user: OptionalUser):
    """球局详情"""
    game = await game_service.get_game(db, game_id)
    row = await game_service.get_game_row(db, game, current_user.id if current_user else None)

    base = _to_game_out(row)
    roster = await game_service.get_roster(db, game)

    detail = GameDetailOut(
        **base.model_dump(),
        checked_count=roster.checked_count,
        late_count=roster.late_count,
        absent_count=roster.absent_count,
        not_checked_count=roster.not_checked_count,
        is_creator=bool(current_user and game.creator_id == current_user.id),
    )
    return ApiResponse.ok(detail)


# ==================================================================
# 4. 报名加入球局
# ==================================================================
@router.post(
    "/{game_id}/signup",
    response_model=ApiResponse[SignupResult],
    summary="④ 报名加入球局",
    description=(
        "**校验顺序**（异常提示按此顺序返回，前端可直接展示）：\n"
        "1. 球局状态是否可报名 → 2. 报名是否已截止 → 3. 是否重复报名\n"
        "4. 信誉分/球技/性别门槛 → 5. **用户时间冲突**（同时段已报名其它球局）→ 6. **球局是否已满**"
    ),
    responses={
        409: {
            "description": "各种冲突",
            "content": {
                "application/json": {
                    "examples": {
                        "时间冲突": {
                            "value": {
                                "code": 40900,
                                "message": "时间冲突：您在 11-20 19:00~21:00 已加入「周五晚东区篮球局」，无法再报名同时段的球局",
                                "data": None,
                            }
                        },
                        "已满": {
                            "value": {
                                "code": 40900,
                                "message": "球局已满（10/10），请关注后续空位",
                                "data": None,
                            }
                        },
                        "重复报名": {
                            "value": {"code": 40900, "message": "您已报名该球局，无需重复报名", "data": None}
                        },
                        "报名截止": {
                            "value": {"code": 40900, "message": "报名已于 11-20 17:00 截止", "data": None}
                        },
                        "信誉分不足": {
                            "value": {
                                "code": 40900,
                                "message": "该球局要求信誉分不低于 80，您当前 55 分，暂无法报名",
                                "data": None,
                            }
                        },
                    }
                }
            },
        }
    },
)
async def sign_up(game_id: int, payload: SignupRequest, current_user: CurrentActiveUser, db: DbSession):
    """
    报名加入球局：★必须提交该球类的自评水平（skill_level），否则 40000 拒绝。
    其余校验：球局可报名 → 未截止 → 未重复 → 门槛（信誉分/水平/性别）→ 时间冲突 → 名额。
    鉴权使用 CurrentActiveUser：小黑屋封禁期间调用会被拦截（返回 code=403 与 msg）。
    """
    result = await game_service.sign_up(db, game_id, current_user, skill_level=payload.skill_level)
    return ApiResponse.ok(result, message=result.message)


# ==================================================================
# 5. 退出球局
# ==================================================================
@router.post(
    "/{game_id}/exit",
    response_model=ApiResponse[ExitGameResult],
    summary="⑤ 退出球局",
    description=(
        "退出（取消报名）球局。\n"
        "- 开球后不可退出；开球前 N 分钟内是否可退出由 `GAME_CANCEL_DEADLINE_MINUTES` 控制\n"
        "- 退出正式名额后，系统自动从候补队列补位一人，并在返回里给出 `promoted_user_id`\n"
        "- 退出后本人待结算的签到记录会被作废，不会被误判缺席"
    ),
    responses={
        409: {
            "description": "不可退出",
            "content": {
                "application/json": {
                    "examples": {
                        "已开始": {"value": {"code": 40900, "message": "球局已开始，无法退出；确需退出请联系发起人", "data": None}},
                        "未报名": {"value": {"code": 40900, "message": "您尚未报名该球局，无需退出", "data": None}},
                        "临近开球": {"value": {"code": 40900, "message": "距开球不足 120 分钟，已无法退出（截止 11-20 17:00）", "data": None}},
                    }
                }
            },
        }
    },
)
async def exit_game(
    game_id: int,
    current_user: CurrentUser,
    db: DbSession,
    reason: str | None = Query(None, max_length=255, description="退出原因（可选）"),
):
    """退出球局（自动候补补位）"""
    result = await game_service.exit_game(db, game_id, current_user, reason)
    return ApiResponse.ok(
        ExitGameResult(
            registration=RegistrationOut.model_validate(result.registration),
            promoted_user_id=result.promoted_user_id,
            current_players=result.current_players,
            message=result.message,
        ),
        message=result.message,
    )


@router.post(
    "/{game_id}/cancel",
    response_model=ApiResponse[ExitGameResult],
    summary="⑤-别名 取消报名（等价于退出球局）",
    description="兼容旧调用；新前端请使用 `POST /game/{game_id}/exit`。",
    include_in_schema=False,
)
async def cancel_signup(game_id: int, current_user: CurrentUser, db: DbSession, reason: str | None = None):
    """兼容旧接口：等价于退出球局"""
    result = await game_service.exit_game(db, game_id, current_user, reason)
    return ApiResponse.ok(
        ExitGameResult(
            registration=RegistrationOut.model_validate(result.registration),
            promoted_user_id=result.promoted_user_id,
            current_players=result.current_players,
            message=result.message,
        ),
        message=result.message,
    )


# ==================================================================
# 结束球局（规则1：状态变为「已结束」即触发缺席判定）
# ==================================================================
@router.post(
    "/{game_id}/finish",
    response_model=ApiResponse[dict],
    summary="结束球局（发起人，触发缺席判定与封禁）",
    description=(
        "把球局状态推进为「已结束」并立即执行缺席判定：\n"
        "**已报名 + 未签到 + 未请假 → 记为缺席**：信誉分 -10，并自动进小黑屋封禁 3 天。\n\n"
        "- 已核销/已签到/已请假的用户不会被判缺席\n"
        "- 幂等：已结算的球局重复调用不会重复判定\n"
        "- 若发起人忘记结束球局，后台有**每小时兜底扫描**自动完成（见 `/api/v1/blacklist/scan-absent`）"
    ),
)
async def finish_game(game_id: int, current_user: CurrentUser, db: DbSession):
    """结束球局并触发缺席判定"""
    game = await game_service.get_game(db, game_id)
    game_service.assert_is_creator(game, current_user)

    result = await checkin_service.finalize_game(db, game, operator_id=current_user.id)
    return ApiResponse.ok(
        {
            "game_id": game_id,
            "status": game.status,
            "absent_count": result.get("absent_count", 0),
            "settled_users": result.get("settled_users", []),
            "message": result.get("message", "球局已结束，缺席判定完成"),
        },
        message=f"球局已结束，判定缺席 {result.get('absent_count', 0)} 人",
    )


# ==================================================================
# 名单（列表页/详情页展示用）
# ==================================================================
@router.get(
    "/{game_id}/members",
    response_model=ApiResponse[list[RosterMemberOut]],
    summary="球局报名名单（正式 + 候补）",
    description="按「正式报名 → 候补顺序」返回成员，含昵称、头像与信誉分，便于前端渲染头像墙。",
)
async def list_members(game_id: int, db: DbSession, only_formal: bool = Query(False, description="只看正式名额")):
    """报名名单"""
    game = await game_service.get_game(db, game_id)
    pairs = await game_service.list_registrations(db, game.id, only_formal=only_formal)
    return ApiResponse.ok(
        [
            RosterMemberOut(
                user_id=user.id,
                nickname=user.nickname,
                avatar_url=user.avatar_url,
                status=reg.status,
                is_waitlist=reg.is_waitlist,
                waitlist_order=reg.waitlist_order,
                signup_time=reg.signup_time,
                credit_score=user.credit_score,
                skill_level=reg.skill_level,
                skill_level_text=skill_text(reg.skill_level),
            )
            for reg, user in pairs
        ]
    )


# ==================================================================
# 内部工具
# ==================================================================
def _to_game_out(row: game_service.GameRow) -> GameOut:
    """把服务层聚合行转成接口出参（补全聚合字段）"""
    game = row.game
    out = GameOut.model_validate(game)
    slots_left = max(0, game.max_players - game.current_players)
    out.creator_nickname = row.creator_nickname
    out.creator_credit_score = row.creator_credit_score
    out.waitlist_count = row.waitlist_count
    out.match_score = row.match_score          # 按用户画像实时计算（未登录=静态基线分）
    out.match_reason = row.match_reason
    out.slots_left = slots_left
    out.is_full = slots_left <= 0
    out.my_registration_status = row.my_registration_status
    out.my_checkin_status = row.my_checkin_status
    return out
