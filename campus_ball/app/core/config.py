"""
全局配置模块
====================================================================
职责：
    1. 集中管理所有可变配置（数据库 / JWT / 业务规则 / AI 参数 / CORS）
    2. 支持从 .env 文件或系统环境变量读取，环境变量优先级高于 .env
    3. 对外只暴露一个单例 `settings`，其它模块统一：
           from app.core.config import settings

扩展方式：
    - 新增 JWT 相关：直接在「JWT」分区加字段
    - 新增 AI 信誉画像：直接在「AI」分区加字段
    - 新增业务开关：直接在「业务规则」分区加字段
    不需要改动任何其它文件。
====================================================================
"""

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """项目配置项（字段名 = 环境变量名，大小写不敏感）"""

    # 允许从 .env / .env.local 读取；extra="ignore" 保证老 .env 多出的键不会报错
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # 基础信息
    # ------------------------------------------------------------------
    PROJECT_NAME: str = "搭子月球"
    ENV: str = "dev"                                  # dev / test / prod
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"                    # 所有业务接口统一前缀
    VERSION: str = "0.1.0"

    # ------------------------------------------------------------------
    # MySQL 数据库连接
    # ------------------------------------------------------------------
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "campus_ball"
    DB_CHARSET: str = "utf8mb4"
    DB_ECHO: bool = False                             # 是否打印 SQL（调试用）

    # 连接池参数：校园场景并发不高，默认值足够
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 3600                       # 小于 MySQL wait_timeout，避免连接失效
    DB_POOL_TIMEOUT: int = 30

    # ------------------------------------------------------------------
    # 密码哈希（bcrypt）
    # ------------------------------------------------------------------
    BCRYPT_ROUNDS: int = 12  # bcrypt cost，越高越安全、登录越慢（12 约 250ms，移动端可接受）

    # ------------------------------------------------------------------
    # JWT 登录鉴权（auth 中间件 / 依赖注入统一读取这里）
    # ------------------------------------------------------------------
    AUTH_ENABLED: bool = True                         # 认证中间件总开关（单测时可关）
    AUTH_HEADER_NAME: str = "Authorization"           # 取 Token 的请求头
    AUTH_TOKEN_PREFIX: str = "Bearer"                 # 请求头前缀：Bearer <token>
    AUTH_COOKIE_NAME: str = "access_token"            # 兼容前端把 Token 放 Cookie 的场景
    AUTH_OPTIONAL_IGNORE_INVALID: bool = True         # 可选登录接口上「带了坏 Token」是否放行
    JWT_SECRET_KEY: str = "dev-only-secret-please-change-me-in-production-0123456789"
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "campus-ball"                   # 签发方（留空则不校验）
    JWT_AUDIENCE: str = "campus-ball-client"          # 受众（留空则不校验）
    JWT_LEEWAY_SECONDS: int = 30                      # 允许的时钟偏差
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7    # Access Token 7 天
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30  # Refresh Token 30 天

    # ------------------------------------------------------------------
    # 业务规则：信誉分 / 小黑屋
    # ------------------------------------------------------------------
    CREDIT_SCORE_INIT: int = 100                      # 新用户初始信誉分（落库字段 reputation_score）
    CREDIT_SCORE_MIN: int = 0                         # 信誉分下限
    CREDIT_SCORE_MAX: int = 150                       # 信誉分上限
    CREDIT_BAN_THRESHOLD: int = 60                    # 低于该值自动进小黑屋
    BAN_DEFAULT_DAYS: int = 3                         # 默认禁赛天数（校园规则：3 天）
    BAN_ON_ABSENT: bool = True                        # ★缺席即封禁（规则2）
    BAN_EXTEND_ON_REPEAT: bool = True                 # ★封禁中再次缺席：顺延而非新建（规则6）
    BAN_MAX_TOTAL_DAYS: int = 30                      # 顺延后总封禁时长上限（天），防止无限顺延
    BAN_BLOCK_ALL_WRITES: bool = False                # False=仅拦「发局/报名」；True=拦所有非查询请求
    BLACKLIST_FAIL_OPEN: bool = True                  # 认证拦截钩子（含小黑屋）查库异常时是否放行
    BLACKLIST_CACHE_TTL: int = 60                     # 小黑屋结果本地缓存秒数，减少查库

    # ------------------------------------------------------------------
    # 缺席判定兜底扫描（防止球局忘记关闭导致漏判）
    # ------------------------------------------------------------------
    ABSENT_SCAN_ENABLED: bool = True                  # 是否启用定时兜底扫描
    ABSENT_SCAN_INTERVAL_SECONDS: int = 3600          # 扫描间隔（秒），默认每小时
    ABSENT_SCAN_BATCH_SIZE: int = 50                  # 单轮最多处理多少个球局
    ABSENT_SCAN_GRACE_MINUTES: int = 0                # 结束时间后宽限多少分钟才判定（0=到点即判）

    # ------------------------------------------------------------------
    # 球局业务规则（冲突校验 / 候补 / 退出 / 核销窗口）
    # ------------------------------------------------------------------
    GAME_SIGNUP_ALLOW_WAITLIST: bool = True   # 满员后是否允许进入候补队列；False 则直接提示「已满」
    GAME_CONFLICT_BUFFER_MINUTES: int = 0     # 时间冲突判定的缓冲分钟数（0=严格按 [start,end) 重叠判断）
    GAME_CANCEL_DEADLINE_MINUTES: int = 0     # 开球前 N 分钟内禁止退出球局；0=不限制
    GAME_MAX_PAGE_SIZE: int = 50              # 列表接口每页最大条数
    CHECKIN_OPEN_BEFORE_MINUTES: int = 30     # 球局未配置签到窗口时，默认开球前 30 分钟开放核销
    CHECKIN_LATE_AFTER_MINUTES: int = 15      # 球局未配置签到截止时，默认开球后 15 分钟内到场算正常

    # ------------------------------------------------------------------
    # AI 信誉画像（DeepSeek 优先，缺 Key 自动降级本地加权规则版）
    # ------------------------------------------------------------------
    AI_ENABLED: bool = True
    DEEPSEEK_API_KEY: str = ""                        # 留空 => 自动走本地加权规则版
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_TIMEOUT: int = 15                        # 秒

    # --- 画像生成时机与缓存 ---
    AI_PROFILE_TRIGGER_ON_SETTLE: bool = True         # 签到/缺席/退出结算后是否触发重算（惰性 + 后台）
    AI_PROFILE_CACHE_HOURS: int = 24                  # 画像缓存有效期（小时），超期则重新生成
    AI_PROFILE_SCAN_INTERVAL_SECONDS: int = 600       # 后台刷新「待重算」用户画像的间隔（秒）
    AI_PROFILE_SCAN_BATCH_SIZE: int = 20              # 单轮最多重算多少个用户
    AI_PROFILE_ASYNC_REFRESH: bool = True             # 结算后是否用后台任务立即刷新（False 则等后台循环）
    AI_MATCH_SCORE_ENABLED: bool = True               # 球局列表 match_score 是否按画像计算（False 则用固定占位值）

    # ------------------------------------------------------------------
    # 部署形态（Serverless / 容器）
    # ------------------------------------------------------------------
    SERVERLESS_MODE: bool = False                     # true=跑在 Vercel 等 Serverless 上（关闭常驻定时任务）
    CRON_SECRET: str = ""                             # 定时任务调用凭证（Vercel Cron 会用 Bearer 发送）

    # ------------------------------------------------------------------
    # MySQL / TiDB 连接
    # ------------------------------------------------------------------
    DB_REQUIRE_SSL: bool = False                      # TiDB Cloud 必须为 true（强制 TLS）
    DB_SSL_CA: str = ""                               # 可选：CA 证书绝对路径（不填则用系统根证书）
    DB_USE_NULL_POOL: bool = False                    # Serverless 建议 true（每请求新建/归还连接）

    # ------------------------------------------------------------------
    # 跨域（前端 Vue3 + Element Plus 开发服务器 / Vercel 域名）
    # ------------------------------------------------------------------
    CORS_ORIGINS: str = "*"                           # 多个用英文逗号分隔

    # ==================================================================
    # 派生属性
    # ==================================================================
    @property
    def sqlalchemy_database_uri(self) -> str:
        """异步连接串（FastAPI 运行时使用，驱动 aiomysql）"""
        password = quote_plus(self.DB_PASSWORD)  # 密码含 @ / # 等特殊字符时需转义
        return (
            f"mysql+aiomysql://{self.DB_USER}:{password}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset={self.DB_CHARSET}"
        )

    @property
    def sqlalchemy_sync_database_uri(self) -> str:
        """同步连接串（Alembic 迁移、离线脚本、建表用，驱动 pymysql）"""
        password = quote_plus(self.DB_PASSWORD)
        return (
            f"mysql+pymysql://{self.DB_USER}:{password}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset={self.DB_CHARSET}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的字符串转成列表，供 CORSMiddleware 使用"""
        raw = (self.CORS_ORIGINS or "").strip()
        if not raw or raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def ai_available(self) -> bool:
        """是否具备调用 DeepSeek 的条件；False 时 AI 服务自动降级为本地规则版"""
        return self.AI_ENABLED and bool(self.DEEPSEEK_API_KEY.strip())

    @property
    def is_prod(self) -> bool:
        return self.ENV.lower() in ("prod", "production")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例获取配置（lru_cache 保证进程内只解析一次 .env）"""
    return Settings()


# 全局配置对象：业务代码统一使用它
settings: Settings = get_settings()
