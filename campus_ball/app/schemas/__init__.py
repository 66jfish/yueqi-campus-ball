"""Pydantic 出入参模型包：统一导出，接口层 `from app.schemas import XxxOut`"""

from app.schemas.ai import AIExplainOut, AIProfileOut, AIProfileRefreshRequest
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RegisterRequest,
    TokenInfoOut,
    TokenResponse,
    UserInfoOut,
)
from app.schemas.blacklist import (
    AbsentScanResultOut,
    BanCreateRequest,
    BanRecordPageOut,
    BanReleaseRequest,
    BlacklistOut,
    MyBanStatusOut,
)
from app.schemas.checkin import (
    AbsentJudgementOut,
    AbsentJudgementRequest,
    CheckinRecordOut,
    CheckinRequest,
    CheckinSettleOut,
    LeaveRequest,
    RosterMemberCheckinOut,
    VerifyCheckinItemOut,
    VerifyCheckinRequest,
    VerifyCheckinResultOut,
    VerifyRosterOut,
)
from app.schemas.game import (
    ExitGameResult,
    GameCreateRequest,
    GameDetailOut,
    GameListItem,
    GameOut,
    GamePageOut,
    RegistrationOut,
    RosterMemberOut,
    SignupResult,
)
from app.schemas.user import (
    CreditHistoryItem,
    CreditStatusOut,
    UpdateUserRequest,
    UserBrief,
    UserOut,
    UserProfilePageOut,
)

__all__ = [
    # auth
    "RegisterRequest", "LoginRequest", "TokenResponse", "RefreshRequest",
    "LoginResponse", "UserInfoOut", "TokenInfoOut",
    # user
    "UserOut", "UserBrief", "CreditStatusOut", "CreditHistoryItem", "UpdateUserRequest",
    "UserProfilePageOut",
    # game
    "GameCreateRequest", "GameOut", "GameListItem", "GameDetailOut", "GamePageOut",
    "RegistrationOut", "SignupResult", "ExitGameResult", "RosterMemberOut",
    # checkin
    "CheckinRequest", "LeaveRequest", "CheckinSettleOut",
    "AbsentJudgementRequest", "AbsentJudgementOut", "CheckinRecordOut",
    "VerifyCheckinRequest", "VerifyCheckinItemOut", "VerifyCheckinResultOut",
    "VerifyRosterOut", "RosterMemberCheckinOut",
    # blacklist
    "BanCreateRequest", "BanReleaseRequest", "BlacklistOut", "MyBanStatusOut",
    "BanRecordPageOut", "AbsentScanResultOut",
    # ai
    "AIProfileOut", "AIProfileRefreshRequest", "AIExplainOut",
]
