"""
用户服务：资料查询与维护
====================================================================
说明：
    「注册 / 登录 / 令牌」相关逻辑已归入 app/services/auth.py（认证模块专属），
    本文件只保留与用户资料、信誉相关的读写能力。
====================================================================
"""

import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models import User

logger = logging.getLogger(__name__)


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    """按主键查用户（自动过滤已逻辑删除）"""
    user = await db.get(User, user_id)
    if user and user.is_deleted:
        return None
    return user


async def get_user_by_account(db: AsyncSession, account: str) -> User | None:
    """按学号或手机号查用户"""
    stmt = select(User).where(
        or_(User.student_no == account, User.phone == account),
        User.is_deleted == 0,
    )
    return (await db.execute(stmt)).scalars().first()


async def update_profile(db: AsyncSession, user: User, **fields) -> User:
    """更新个人资料（只更新传入的非空字段）"""
    allowed = {"nickname", "avatar_url", "campus", "college", "grade", "skill_level"}
    for key, value in fields.items():
        if key in allowed and value is not None:
            setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user


async def get_required_user(db: AsyncSession, user_id: int) -> User:
    """取用户，不存在则抛 404"""
    user = await get_user_by_id(db, user_id)
    if not user:
        raise NotFoundException("用户不存在")
    return user
