"""
模型包
====================================================================
在这里统一导出所有 ORM 模型：
    1. 业务代码可以 `from app.models import User, Game`
    2. app/db/init_db.py 导入本包后，Base.metadata 就能识别全部表
新增模型时记得在此登记。
====================================================================
"""

from app.models.blacklist import Blacklist
from app.models.checkin import CheckinRecord
from app.models.game import Game
from app.models.registration import Registration
from app.models.user import User

__all__ = [
    "User",
    "Game",
    "Registration",
    "CheckinRecord",
    "Blacklist",
]
