"""
业务常量与枚举
====================================================================
把「状态码 / 角色 / 信誉分规则」等魔法数字集中在这里，
ORM 模型、Service、API 层统一引用，避免各写一份导致对不上。
====================================================================
"""

from enum import IntEnum


# ==================================================================
# 通用
# ==================================================================
class DeleteFlag(IntEnum):
    """逻辑删除标记"""

    NO = 0   # 未删除
    YES = 1  # 已删除


class Gender(IntEnum):
    """性别"""

    UNKNOWN = 0
    MALE = 1
    FEMALE = 2


# ==================================================================
# 用户
# ==================================================================
class UserStatus(IntEnum):
    """账号状态"""

    DISABLED = 0  # 禁用（管理员操作）
    NORMAL = 1    # 正常


class CreditLevel(IntEnum):
    """
    信誉等级（由信誉分区间映射，惰性结算时一并刷新）
    1 黑名单 / 2 观察 / 3 正常 / 4 优秀 / 5 金牌
    """

    BLACKLIST = 1
    WATCH = 2
    NORMAL = 3
    GOOD = 4
    GOLD = 5


class SkillLevel(IntEnum):
    """球技水平（自评 + AI 画像可校准）"""

    NEWBIE = 1     # 新手
    PRIMARY = 2    # 初级
    INTERMEDIATE = 3  # 中级
    ADVANCED = 4   # 高级
    MASTER = 5     # 大神


# ==================================================================
# 球局
# ==================================================================
class SportType(IntEnum):
    """运动类型"""

    BASKETBALL = 1  # 篮球
    FOOTBALL = 2    # 足球
    BADMINTON = 3   # 羽毛球
    TENNIS = 4      # 网球
    VOLLEYBALL = 5  # 排球
    PINGPONG = 6    # 乒乓球


class GameStatus(IntEnum):
    """球局状态流转：草稿 -> 报名中 -> 报名截止 -> 进行中 -> 已结束 / 已取消"""

    DRAFT = 0        # 草稿
    SIGNING = 1      # 报名中
    SIGNUP_CLOSED = 2  # 报名截止（等待开始）
    PLAYING = 3      # 进行中
    FINISHED = 4     # 已结束（可触发缺席判定）
    CANCELED = 5     # 已取消


class SettleStatus(IntEnum):
    """球局结算状态：用于惰性结算，避免重复结算"""

    PENDING = 0   # 待结算
    SETTLED = 1   # 已结算
    PARTIAL = 2   # 部分结算（有人未判定完成）


class FeeType(IntEnum):
    """费用类型"""

    FREE = 0  # 免费
    AA = 1    # AA 制


# ==================================================================
# AI 智能匹配分（match_score）
# ==================================================================
# 当前球局列表返回的 match_score 为「静态固定占位值」：
#   - 前端可先按该字段排序/展示，不必等 AI 匹配模块上线
#   - AI 智能匹配模块接入后，改为按 (用户画像, 球局特征) 实时计算，
#     只需替换 app/services/game.py 里 GameRow.match_score 的赋值，接口结构不变
MATCH_SCORE_PLACEHOLDER: float = 80.0


# ==================================================================
# 报名
# ==================================================================
class RegistrationStatus(IntEnum):
    """报名状态"""

    SIGNED = 1    # 已报名（占用名额）
    CANCELED = 2  # 已取消
    WAITLIST = 3  # 候补中
    KICKED = 4    # 被组织者移出


# ==================================================================
# 签到 / 缺席
# ==================================================================
class CheckinStatus(IntEnum):
    """签到状态"""

    NOT_CHECKED = 0  # 未签到（球局未结束时为正常态）
    CHECKED = 1      # 正常签到
    LATE = 2         # 迟到签到
    ABSENT = 3       # 缺席（球局结束后仍未签到且未请假）
    LEAVE = 4        # 已请假（不扣分）


class CheckinType(IntEnum):
    """签到方式"""

    QR_CODE = 1   # 扫码
    LOCATION = 2  # 定位打卡
    MANUAL = 3    # 组织者人工补签


# ==================================================================
# 小黑屋 / 失信
# ==================================================================
class BanStatus(IntEnum):
    """封禁状态"""

    RELEASED = 0  # 已解封
    BANNED = 1    # 封禁中


class BanReasonType(IntEnum):
    """封禁原因类型"""

    ABSENT = 1            # 缺席未到
    LATE_ACCUMULATED = 2  # 多次迟到累计
    LOW_CREDIT = 3        # 信誉分过低
    MANUAL = 4            # 管理员人工封禁


class ReleaseType(IntEnum):
    """解封方式"""

    AUTO = 1     # 到期自动解封
    MANUAL = 2   # 管理员手动解封
    APPEAL = 3   # 申诉通过


# ==================================================================
# 信誉分规则 —— 惰性结算的核心规则表
#   key  : CheckinStatus 值
#   value: 触发结算时对信誉分的增减
# 说明：只有「签到」和「判定缺席」两个时机才会读这张表，
#       平时不会为了展示分数而实时计算。
# ==================================================================
CREDIT_RULES: dict[int, int] = {
    CheckinStatus.CHECKED: +2,   # 正常签到：+2
    CheckinStatus.LATE: -3,      # 迟到签到：-3
    CheckinStatus.ABSENT: -10,   # 缺席：-10
    CheckinStatus.LEAVE: 0,      # 已请假：不奖不罚
    CheckinStatus.NOT_CHECKED: 0,  # 未结算态，变动为 0
}

# ==================================================================
# 校区选项（全站统一为三个：老校区 / 新校区 / 校外）
#   选「校外」时场地为自由输入（球馆名或地址）
# ==================================================================
CAMPUS_LAO = "老校区"
CAMPUS_XIN = "新校区"
CAMPUS_OFF = "校外"
CAMPUS_OPTIONS: tuple[str, ...] = (CAMPUS_LAO, CAMPUS_XIN, CAMPUS_OFF)
# 校外场地：不校验是否在校内场馆列表中，由用户自填
CAMPUS_FREE_VENUE = CAMPUS_OFF

# 球技水平文案（1-5 与 SkillLevel 对应）
SKILL_LEVEL_TEXT: dict[int, str] = {
    0: "不限",
    1: "新手",
    2: "初级",
    3: "中级",
    4: "高级",
    5: "大神",
}


def skill_text(level: int | None) -> str:
    """水平数值 → 文案（用于接口返回，前端直接展示）"""
    return SKILL_LEVEL_TEXT.get(int(level or 0), "未知")


# 信誉分 -> 信誉等级 的映射阈值（从高到低匹配）
# 注意：区间必须让「初始分 100」落在 NORMAL(3)，与数据库默认值 credit_level=3 保持一致，
#      否则新用户会出现「库里是 3、结算后变 4」的跳变。
CREDIT_LEVEL_THRESHOLDS: list[tuple[int, CreditLevel]] = [
    (120, CreditLevel.GOLD),      # >= 120 金牌
    (110, CreditLevel.GOOD),      # >= 110 优秀
    (90, CreditLevel.NORMAL),     # >= 90  正常（初始分 100 落在这里）
    (60, CreditLevel.WATCH),      # >= 60  观察
    (0, CreditLevel.BLACKLIST),   # < 60   黑名单
]


def map_credit_level(credit_score: int) -> CreditLevel:
    """根据信誉分映射信誉等级（惰性结算时调用）"""
    for threshold, level in CREDIT_LEVEL_THRESHOLDS:
        if credit_score >= threshold:
            return level
    return CreditLevel.BLACKLIST


# ==================================================================
# AI 信誉画像：本地加权规则权重表（降级方案的核心算法）
# ==================================================================
# 设计原则：
#   1. 每个权重都对应一种「可观测的行为事实」，不做主观加权
#   2. 无故缺席（放鸽子）权重最重，主动退出权重最轻（符合产品规则）
#   3. 该算法完全确定性、可复算、可审计，不依赖大模型
# 画像分计算公式见 app/services/ai_profile.py::local_weighted_score
PROFILE_WEIGHTS: dict[str, int] = {
    "checked": +2,        # 按时签到（到场）：加分
    "late": -3,           # 迟到签到：小幅扣分
    "absent": -10,        # 无故缺席（未签到未请假）：大幅扣分
    "leave": 0,           # 已请假：不奖不罚（请假是负责任的行为）
    "cancel_early": -2,   # 主动退出（距开球 > 提前退出阈值）：少量扣分
    "cancel_late": -4,    # 临近开球才退出（≤ 阈值小时）：占用名额影响成局，扣分略重
}

# 退出行为的「临近开球」判定阈值（小时）：开球前 N 小时内退出算 cancel_late
PROFILE_LATE_CANCEL_HOURS: int = 2
# 请假不计分的说明：请假仍需提前操作，但不惩罚（避免用户硬扛着不请假导致缺席）

# 画像分区间（与 t_user.reputation_score 使用同一上下限口径）
PROFILE_SCORE_MIN: int = 0
PROFILE_SCORE_MAX: int = 150

# ==================================================================
# AI 信誉画像：DeepSeek 结果与本地规则结果的融合参数
# ==================================================================
# 融合策略：以本地加权分为确定性基线，AI 建议分只做有限调整
#   最终分 = AI_WEIGHT * ai_score + (1 - AI_WEIGHT) * rule_score
#   并限制 |最终分 - rule_score| <= AI_SCORE_MAX_ADJUST（防模型幻觉导致分数剧烈跳变）
AI_SCORE_WEIGHT: float = 0.3      # AI 建议分权重（仅在有 API Key 且调用成功时生效）
AI_SCORE_MAX_ADJUST: int = 8      # 相对本地基线的最大调整幅度（分）

# ==================================================================
# 球局匹配参考分（match_score）：画像分的第一个下游应用
# ==================================================================
MATCH_SCORE_BASE: float = 60.0          # 基础分
MATCH_SCORE_WEIGHT_REPUTATION: float = 20.0   # 信誉分归一化后最多贡献 20 分
MATCH_SCORE_WEIGHT_SKILL: float = 12.0        # 球技匹配最多贡献 12 分
MATCH_SCORE_WEIGHT_PREFERENCE: float = 8.0    # 球类偏好最多贡献 8 分
MATCH_SCORE_PENALTY_FULL: float = 5.0         # 满员惩罚
MATCH_SCORE_MAX: float = 100.0
