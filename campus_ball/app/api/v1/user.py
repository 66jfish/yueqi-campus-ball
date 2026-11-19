"""
用户接口：个人资料 + 信誉分（惰性结算视角）
====================================================================
路径前缀：/api/v1/user
关键点：
    GET /me/credit  —— 只读库里的信誉分，不触发任何计算；
                      同时告诉前端「还有几条记录待结算」，
                      让惰性结算对用户是可解释、可预期的。
====================================================================
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, OptionalUser
from app.core.constants import CreditLevel, RegistrationStatus, skill_text
from app.models import Game, Registration
from sqlalchemy import select
from app.core.exceptions import NotFoundException
from app.core.response import ApiResponse
from app.schemas import (
    CreditHistoryItem,
    CreditStatusOut,
    UpdateUserRequest,
    UserOut,
    UserProfilePageOut,
)
from app.services import ai_profile as ai_profile_service
from app.services import blacklist as blacklist_service
from app.services import reputation as reputation_service
from app.services import user as user_service

router = APIRouter(prefix="/user", tags=["用户"])

# 球类文案（常打项目展示用）
SPORT_NAME = {1: "篮球", 2: "足球", 3: "羽毛球", 4: "网球", 5: "排球", 6: "乒乓球"}

# 信誉等级文案（个人主页展示用）
_LEVEL_TEXT = {
    CreditLevel.BLACKLIST: "黑名单",
    CreditLevel.WATCH: "观察中",
    CreditLevel.NORMAL: "正常",
    CreditLevel.GOOD: "优秀",
    CreditLevel.GOLD: "金牌球友",
}


@router.get("/me", response_model=ApiResponse[UserOut], summary="获取当前登录用户信息")
async def get_me(current_user: CurrentUser):
    return ApiResponse.ok(UserOut.model_validate(current_user))


@router.put("/me", response_model=ApiResponse[UserOut], summary="更新个人资料")
async def update_me(payload: UpdateUserRequest, current_user: CurrentUser, db: DbSession):
    user = await user_service.update_profile(db, current_user, **payload.model_dump())
    return ApiResponse.ok(UserOut.model_validate(user), message="资料已更新")


@router.get(
    "/{user_id}/profile",
    response_model=ApiResponse[UserProfilePageOut],
    summary="用户个人主页（信誉分 + AI 画像 + 行为统计）",
    description=(
        "个人主页展示接口：\n"
        "- 信誉分与等级（`reputation_score` / `credit_level` / `credit_level_text`）\n"
        "- AI 画像：画像分 `profile_score`、信誉标签 `tags`、画像总结、加权明细 `breakdown`\n"
        "- 行为统计：到场/迟到/缺席/退出次数、守约率\n"
        "- 封禁状态：他人只能看到「是否在封禁中」，解禁时间仅本人可见\n\n"
        "不返回手机号、邮箱、学号等隐私字段。"
    ),
)
async def get_user_profile_page(user_id: int, db: DbSession, current_user: OptionalUser):
    """用户个人主页（含信誉分与 AI 画像）"""
    user = await user_service.get_user_by_id(db, user_id)
    if user is None or user.is_deleted:
        raise NotFoundException("用户不存在")

    is_self = bool(current_user and current_user.id == user_id)
    features = await ai_profile_service.collect_features(db, user_id)
    rule = (
        ai_profile_service.local_weighted_score(features)
        if features
        else {"score": user.reputation_score, "breakdown": []}
    )
    profile = user.ai_profile if isinstance(user.ai_profile, dict) else {}
    ban = await blacklist_service.get_active_ban(db, user_id)

    # 常打项目：按参与次数倒序（来自行为特征里的球类分布）
    sport_counts = dict(features.sport_counts) if features else {}
    total_sport = sum(sport_counts.values()) or 1
    favorite_sports = [
        {
            "sport_type": st,
            "name": SPORT_NAME.get(st, "其他"),
            "count": cnt,
            "ratio": round(cnt / total_sport, 2),
        }
        for st, cnt in sorted(sport_counts.items(), key=lambda x: -x[1])[:4]
    ]

    # 最近一次报名时自评的水平（含球类）
    latest_reg = (
        await db.execute(
            select(Registration, Game.sport_type)
            .join(Game, Game.id == Registration.game_id)
            .where(Registration.user_id == user_id, Registration.status == RegistrationStatus.SIGNED)
            .order_by(Registration.signup_time.desc())
            .limit(1)
        )
    ).first()
    latest_skill_level = latest_reg[0].skill_level if latest_reg else None
    latest_skill_sport = SPORT_NAME.get(latest_reg[1], None) if latest_reg else None

    return ApiResponse.ok(
        UserProfilePageOut(
            user_id=user.id,
            nickname=user.nickname,
            avatar_url=user.avatar_url,
            campus=user.campus,
            college=user.college,
            gender=user.gender,
            skill_level=user.skill_level,
            reputation_score=user.reputation_score,
            credit_score=user.reputation_score,
            credit_level=user.credit_level,
            credit_level_text=_LEVEL_TEXT.get(user.credit_level, "正常"),
            profile_score=user.ai_score or profile.get("score") or rule["score"],
            tags=list(profile.get("tags") or []),
            summary=profile.get("summary"),
            profile_source=user.ai_profile_source or profile.get("source"),
            profile_degraded=bool(profile.get("degraded", True)),
            breakdown=list(profile.get("breakdown") or rule["breakdown"]),
            favorite_sports=favorite_sports,
            latest_skill_level=latest_skill_level,
            latest_skill_level_text=skill_text(latest_skill_level) if latest_skill_level else None,
            latest_skill_sport=latest_skill_sport,
            attended_count=features.checked_count if features else 0,
            late_count=features.late_count if features else 0,
            absent_count=user.absent_count,
            cancel_count=features.cancel_total if features else 0,
            keep_rate=features.keep_rate if features else 1.0,
            joined_game_count=user.total_game_count,
            created_game_count=features.game_created_count if features else 0,
            banned=ban is not None,
            ban_end_time=ban.ban_end_time if (ban and is_self) else None,
            registered_at=user.created_at,
            is_self=is_self,
        )
    )


@router.get("/me/credit", response_model=ApiResponse[CreditStatusOut], summary="查询信誉分状态")
async def get_my_credit(current_user: CurrentUser, db: DbSession):
    """
    信誉状态查询（不触发结算）。
    真正改变信誉分的只有两个动作：签到、判定缺席。
    """
    pending = await reputation_service.get_pending_record_count(db, current_user.id)
    ban = await blacklist_service.get_active_ban(db, current_user.id)

    return ApiResponse.ok(
        CreditStatusOut(
            reputation_score=current_user.reputation_score,
            credit_score=current_user.reputation_score,  # 兼容字段
            credit_level=current_user.credit_level,
            pending_settle_count=pending,
            banned=ban is not None,
            ban_end_time=ban.ban_end_time if ban else None,
            ban_extend_count=ban.extend_count if ban else 0,
            credit_settled_at=current_user.credit_settled_at,
        )
    )


@router.get(
    "/me/credit/history",
    response_model=ApiResponse[list[CreditHistoryItem]],
    summary="信誉分流水（已结算记录）",
)
async def get_my_credit_history(current_user: CurrentUser, db: DbSession, limit: int = 20):
    """直接复用签到记录表作为流水，无需额外维护流水表"""
    records = await reputation_service.get_credit_history(db, current_user.id, limit=limit)
    return ApiResponse.ok(records)
