"""
v1 版本路由汇总
====================================================================
main.py 只需要：
    from app.api.v1 import api_router
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
后续新增模块（如消息通知、AI 智能匹配）：
    1. 新建 app/api/v1/xxx.py
    2. 在此处 include_router
====================================================================
"""

from fastapi import APIRouter

from app.api.v1 import ai, auth, blacklist, checkin, game, system, user

api_router = APIRouter()

api_router.include_router(auth.router)        # /auth   注册、登录、刷新
api_router.include_router(user.router)        # /user   个人资料、信誉分
api_router.include_router(game.router)        # /game   球局、报名
api_router.include_router(checkin.router)     # /checkin 签到、缺席判定（惰性结算触发点）
api_router.include_router(blacklist.router)   # /blacklist 小黑屋
api_router.include_router(ai.router)          # /ai     AI 信誉画像
api_router.include_router(system.router)      # /system 运行时信息与定时任务入口
