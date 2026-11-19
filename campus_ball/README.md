# 搭子月球 · 后端脚手架（FastAPI + MySQL）

> 技术栈：Python FastAPI + MySQL 8 + SQLAlchemy 2.0（异步）+ JWT（PyJWT）
> 前端配套：Vue3 + Element Plus，响应式（手机 / 平板 / 桌面自适应）
> AI 能力：信誉画像优先 DeepSeek，**未配置 API Key 时自动降级为本地规则版**

---

## 一、目录结构说明

```
campus_ball/
├── app/                                  # 应用主包
│   ├── __init__.py
│   ├── main.py                           # ★ 入口：生命周期、中间件、路由、异常、/health
│   │
│   ├── core/                             # 核心基础设施（与业务无关，可整体复用）
│   │   ├── config.py                     # ★ 全局配置：MySQL / JWT / bcrypt / 信誉规则 / AI / CORS
│   │   ├── constants.py                  # 枚举 + 信誉分规则表（CREDIT_RULES）+ 分数→等级映射
│   │   ├── security.py                   # ★ 密码哈希（bcrypt，兼容历史 PBKDF2）+ JWT 签发/校验
│   │   ├── response.py                   # 统一响应体 {code, message, data} + 错误码表
│   │   └── exceptions.py                 # 业务异常 + 全局异常处理器
│   │
│   ├── db/                               # 数据访问基础设施
│   │   ├── base.py                       # Declarative Base + 时间戳/逻辑删除 Mixin
│   │   ├── session.py                    # ★ 数据库连接模块：异步 Engine / Session / get_db
│   │   └── init_db.py                    # 建表脚本（开发环境 python -m app.db.init_db）
│   │
│   ├── models/                           # ORM 模型（5 张核心表）
│   │   ├── user.py                       # t_user          用户表（信誉分、AI画像）
│   │   ├── game.py                       # t_game          球局表（签到窗口、结算标记）
│   │   ├── registration.py               # t_registration  报名表（含候补队列）
│   │   ├── checkin.py                    # t_checkin_record 签到记录表（惰性结算账本）
│   │   └── blacklist.py                  # t_blacklist     失信小黑屋表（到期自动解封）
│   │
│   ├── schemas/                          # Pydantic 出入参模型（与 models 解耦，不暴露密码哈希）
│   │   ├── auth.py  user.py  game.py  checkin.py  blacklist.py  ai.py
│   │
│   ├── services/                         # 业务逻辑层（接口只做参数校验 + 调服务）
│   │   ├── auth.py                       # ★ 认证：注册 / 登录 / 刷新令牌 / 登出（bcrypt）
│   │   ├── user.py                       # 用户资料查询与维护
│   │   ├── game.py                       # ★ 球局：发起（场地/时间冲突校验）/ 列表 / 详情 / 报名 / 退出 / 候补补位
│   │   ├── checkin.py                    # ★ 核销：发起人核销到场用户 / 核销名单（触发惰性结算）
│   │   ├── reputation.py                 # ★ 信誉分惰性结算（签到/核销、缺席判定两个触发时机）
│   │   ├── blacklist.py                  # ★ 小黑屋：封禁 / 查询 / 到期自动解封 + 结果缓存
│   │   └── ai_profile.py                 # ★ AI 信誉画像：DeepSeek 优先 + 本地规则降级
│   │
│   ├── api/
│   │   ├── deps.py                       # 依赖注入：get_db / get_current_user(复用中间件) / get_current_admin
│   │   └── v1/
│   │       ├── __init__.py               # api_router 汇总（新增模块只改这里）
│   │       ├── auth.py                   # /api/v1/auth      注册、登录、刷新、登出、令牌信息
│   │       ├── user.py                   # /api/v1/user      资料、信誉分、信誉流水
│   │       ├── game.py                   # /api/v1/game      球局、报名、候补
│   │       ├── checkin.py                # /api/v1/checkin   签到、请假、缺席判定
│   │       ├── blacklist.py              # /api/v1/blacklist 小黑屋查询/封禁/解封
│   │       └── ai.py                     # /api/v1/ai        信誉画像（带缓存）
│   │
│   └── middleware/
│       ├── auth.py                       # ★ JWT 认证中间件（路由前置：解析令牌 + 执行钩子链）
│       └── hooks.py                      # ★ 认证拦截钩子链：账号状态 → 小黑屋 → 可任意扩展
│
├── docs/
│   ├── API_AUTH.md                       # ★ 认证模块接口文档（参数表 + 请求/返回示例 + 前端对接）
│   ├── API_GAME.md                       # ★ 球局核心业务接口文档（6 个接口 + 异常提示 + 调用链路）
│   ├── API_BLACKLIST.md                  # ★ 小黑屋失信惩罚模块（规则说明 + 连续缺席处理逻辑 + 接口）
│   └── API_AI_PROFILE.md                 # ★ AI 信誉画像（加权算法说明 + 融合策略 + 接口 + 匹配分）
│
├── sql/
│   ├── 001_schema.sql                    # ★ 完整建表 SQL（每字段带注释）
│   ├── 002_init_data.sql                 # 可选：演示数据（账号密码均为 123456，bcrypt 哈希）
│   ├── 003_migration_v1_1.sql            # 增量迁移：核销人字段 + 场地时间索引
│   ├── 004_migration_v1_2.sql            # 增量迁移：reputation_score 更名 + 顺延字段
│   └── 005_migration_v1_3.sql            # 增量迁移：AI 画像字段（ai_score/dirty/version）
│
├── tests/
│   ├── test_smoke.py                     # 冒烟测试（路由/文档/工具函数）
│   ├── test_auth.py                      # ★ 认证模块测试（bcrypt、JWT、中间件、钩子拦截）
│   ├── test_game.py                      # ★ 球局核心业务测试（冲突校验、报名退出、核销结算）
│   ├── test_blacklist.py                 # ★ 小黑屋惩罚测试（缺席判定、封禁、顺延、惰性解封）
│   └── test_ai_profile.py                # ★ AI 画像测试（加权算法、降级、融合限幅、匹配分）
│
├── requirements.txt
├── .env.example                          # 环境变量样例，复制为 .env 使用
└── .gitignore
```

### 分层与依赖方向

```
api (路由/参数校验)  →  services (业务规则)  →  models (ORM)  →  MySQL
        ↓                    ↓
     schemas (出入参)      core / db (基础设施)
```
- **api** 不写业务规则，只做参数校验与响应包装
- **services** 承载全部业务规则（惰性结算、封禁、AI 调用），可被定时任务直接复用
- **core/** 与 **db/** 不含业务语义，前端换框架、业务换模块都不受影响

---

## 二、快速开始

```bash
# 1) 安装依赖
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 2) 准备数据库（推荐直接跑 SQL，字段注释最全）
mysql -uroot -p < sql/001_schema.sql
mysql -uroot -p campus_ball < sql/002_init_data.sql   # 可选：演示数据

# 3) 配置环境变量
copy .env.example .env            # macOS/Linux: cp .env.example .env
# 修改 DB_PASSWORD、JWT_SECRET_KEY；（可选）填入 DEEPSEEK_API_KEY

# 4) 启动
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# 文档：http://127.0.0.1:8000/docs    健康检查：/health
```

> 说明：**不填 `DEEPSEEK_API_KEY` 也能完整运行**，AI 画像会自动走本地规则版
> （响应里 `source="rule"`、`degraded=true`，前端可据此提示“本地规则评估”）。

---

## 三、两个关键设计

### 1. 信誉分「惰性结算」（不实时计算）

| 项目 | 说明 |
| --- | --- |
| 事实来源 | `t_user.credit_score`，平时只读，**不实时计算** |
| 触发时机 A | 签到（正常签到 / 迟到）→ `POST /api/v1/checkin/checkin` |
| 触发时机 B | 判定缺席（球局结束后未签到且未请假）→ `POST /api/v1/checkin/absent-judgement` |
| 账本 | `t_checkin_record.settled`：0=待结算、1=已结算（记录 `credit_delta`、`settled_at`） |
| 幂等 | 结算时只捞 `settled=0` 的记录，处理完置 1，重复调用不会重复扣分 |
| 并发 | 结算前对 `t_user` 行 `SELECT ... FOR UPDATE`，避免签到与缺席判定同时结算丢更新 |
| 分值规则 | `app/core/constants.py::CREDIT_RULES`：签到 +2、迟到 -3、缺席 -10、请假 0 |
| 附加动作 | 结算后信誉分低于阈值（默认 60）→ 自动进小黑屋（默认 3 天） |

流程：`签到/缺席判定 → 捞出 settled=0 记录 → 汇总 delta → 更新 credit_score/credit_level → 记录置 settled=1 → 触发封禁判定`

### 2. 小黑屋「禁赛 3 天 + 到期自动解封」

- 表字段：`ban_start_time`（起始）+ `ban_duration_days`（时长，默认 3）+ `ban_end_time`（到期时间）
- **判定是否禁赛只需一句**：`status = 1 AND ban_end_time > NOW()`
  → 过期记录天然不命中，等于自动解封，**不依赖定时任务可用性**
- 后台任务（`app/main.py` 的 lifespan，默认 5 分钟一轮）把到期记录置为 `status=0 / release_type=1`，保留解封痕迹
- **黑名单中间件**（`app/middleware/blacklist.py`）对 `/game`、`/checkin`、`/registration` 路径统一拦截，
  禁赛中直接返回 `403` + `code=40301` + 解封时间，业务接口不会被执行
- 查询结果带 60 秒内存缓存，避免每个请求都查库；数据库异常默认放行（`BLACKLIST_FAIL_OPEN=true`，可按需改为 false）

---

## 四、接口清单（v1）

### 认证与用户

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | 注册（学号唯一，bcrypt 存储，初始信誉分 100） |
| POST | `/api/v1/auth/login` | 登录，返回 access/refresh token |
| POST | `/api/v1/auth/refresh` | 刷新访问令牌（refresh_token 轮换） |
| POST | `/api/v1/auth/logout` | 退出登录（幂等，已预留 jti 黑名单） |
| GET | `/api/v1/auth/token-info` | 查看当前令牌剩余有效期（决定是否静默续期） |
| GET | `/api/v1/user/me` | 当前用户信息 |
| PUT | `/api/v1/user/me` | 更新个人资料 |
| GET | `/api/v1/user/me/credit` | 信誉分状态（含待结算条数、是否禁赛） |
| GET | `/api/v1/user/me/credit/history` | 信誉分流水（已结算记录） |

### 球局核心业务（详细见 [docs/API_GAME.md](docs/API_GAME.md)）

| # | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| ① | POST | `/api/v1/game` | 发起球局（★同场地同时段冲突 + 发起人时间冲突校验） |
| ② | GET | `/api/v1/game` | 球局列表（筛选 + 分页；★`sport_type` 不传=全部球类；★`match_score` 静态占位值 80.0） |
| ③ | GET | `/api/v1/game/{game_id}` | 球局详情（含核销统计与「我的报名/签到状态」） |
| ④ | POST | `/api/v1/game/{game_id}/signup` | 报名（★用户时间冲突 + 球局未满，满员转候补） |
| ⑤ | POST | `/api/v1/game/{game_id}/exit` | 退出球局（★自动候补补位） |
| ⑥ | POST | `/api/v1/checkin/verify` | **签到核销**（发起人给到场用户签到，★触发惰性结算） |
| ⑦ | POST | `/api/v1/game/{game_id}/finish` | **结束球局**（★触发缺席判定：未签到未请假 → -10 分 + 封禁 3 天） |
| — | GET | `/api/v1/checkin/game/{game_id}` | 核销名单（谁到了、谁没到 + 到场统计，仅发起人） |
| — | GET | `/api/v1/game/{game_id}/members` | 报名名单（正式 + 候补） |
| — | POST | `/api/v1/checkin/absent-judgement` | 缺席判定（与结束球局等价的手动入口） |

### 小黑屋失信惩罚（详细见 [docs/API_BLACKLIST.md](docs/API_BLACKLIST.md)）

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/v1/blacklist/me` | 登录 | **我的封禁状态**（被封禁也能查：解禁时间、倒计时、禁止动作、历史记录） |
| GET | `/api/v1/blacklist/records` | 登录 | **封禁记录查询**（分页；本人=自己，管理员=全部并可筛选） |
| GET | `/api/v1/blacklist` | 管理员 | 封禁记录列表（管理端简版） |
| POST | `/api/v1/blacklist/ban` | 管理员 | 手动封禁（默认 3 天；已在封禁中默认**顺延**） |
| POST | `/api/v1/blacklist/release` | 管理员 | 手动解封 |
| POST | `/api/v1/blacklist/release-expired` | 管理员 | 到期解封**留痕**批处理 |
| POST | `/api/v1/blacklist/scan-absent` | 管理员 | 手动触发缺席判定**兜底扫描** |
| GET | `/api/v1/blacklist/config` | 登录 | 查看当前生效的惩罚规则参数 |

### 签到、小黑屋、AI

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/checkin/checkin` | 本人扫码/定位签到 → 触发惰性结算 |
| POST | `/api/v1/checkin/leave` | 请假（不扣分，避免被判缺席） |
| GET | `/api/v1/checkin/my` | 我的签到记录（含待结算标记） |
| GET | `/api/v1/blacklist/me` | 我的封禁状态（白名单，禁赛也能查） |
| GET | `/api/v1/blacklist` | 封禁记录列表（管理端） |
| POST | `/api/v1/blacklist/ban` | 手动封禁 |
| POST | `/api/v1/blacklist/release` | 手动解封 |
| POST | `/api/v1/blacklist/release-expired` | 手动触发到期自动解封 |
| GET | `/api/v1/ai/profile` | 获取信誉画像（24 小时缓存） |
| POST | `/api/v1/ai/profile/refresh` | 强制刷新画像 |

统一响应格式：

```json
{ "code": 0, "message": "ok", "data": {} }
```
`code` 约定：0 成功 / 40000 参数错误 / 40100 未登录 / **40101 令牌过期** / **40102 令牌非法** /
**40103 账号禁用** / 40300 无权限 / **40301 禁赛中** / 40900 状态冲突 / 50000 服务端错误。

---

## 三点五、用户认证模块（bcrypt + JWT 中间件 + 拦截钩子）

| 项 | 实现 |
| --- | --- |
| 密码存储 | **bcrypt**（cost=12，随机盐），库里 `$2b$12$...`；兼容历史 PBKDF2 并在登录后自动升级 |
| 令牌 | JWT 双令牌：access（7 天）+ refresh（30 天），载荷含 `sub/iat/exp/jti/type/iss/aud` |
| 鉴权位置 | **`AuthMiddleware` 路由前置**，三档策略：公开 / 可选登录 / 必须登录（改一处即全局生效） |
| 接口复用 | 需要登录的接口只写 `current_user: CurrentUser`，中间件已解析好，接口不重复解 Token |
| 统一拦截 | 认证钩子链 `账号状态 → 小黑屋`，业务接口零改动；扩展只需 `register_auth_hook()` |
| 详细文档 | [`docs/API_AUTH.md`](docs/API_AUTH.md)（请求参数表、成功/失败返回示例、前端 axios 拦截示例） |

```python
# 新增一个需要登录的接口：只加一个依赖，鉴权与小黑屋拦截自动生效
@router.get("/my-orders")
async def my_orders(current_user: CurrentUser, db: DbSession):
    return ApiResponse.ok(...)
```

```python
# 扩展一个全局拦截规则（例如强制改密），注册一次即对所有接口生效
async def need_password_change_hook(request: Request, user_id: int) -> None:
    if await is_password_expired(user_id):
        raise BizException("密码已过期，请先修改密码", code=40302)

register_auth_hook("password_expire", need_password_change_hook)
```

---

## 四点半、球局核心业务（发起 / 列表 / 详情 / 报名 / 退出 / 核销）

### 关键校验（全部在服务层，异常提示可直接展示给用户）

| 校验 | 位置 | 提示示例 |
| --- | --- | --- |
| ★同场地同时段冲突 | `services/game.py::check_venue_conflict` | 场地冲突：东区体育馆3号场 在 11-20 19:00~21:00 已被「周五晚东区篮球局」占用，请更换场地或调整时间 |
| ★用户时间冲突（报名/发起） | `check_user_time_conflict` | 时间冲突：您在 11-20 19:00~21:00 已加入「周五晚东区篮球局」，无法再报名同时段的球局 |
| ★球局未满 | `sign_up` | 满员进候补：球局已满，您已进入候补队列（第 1 位）／关闭候补：球局已满（10/10），请关注后续空位 |
| 门槛（信誉分/球技/性别） | `sign_up` | 该球局要求信誉分不低于 80，您当前 55 分，暂无法报名 |
| 退出限制 | `exit_game` | 球局已开始，无法退出；确需退出请联系发起人 ／ 距开球不足 120 分钟，已无法退出（截止 11-20 17:00） |
| 核销前置 | `services/checkin.py::assert_verifiable` | 核销尚未开放，11-20 18:30 起可核销（开球前 30 分钟） ／ 该球局已完成结算，无法再核销 |

### 核销如何驱动惰性结算（★核心链路）

```
发起人核销（POST /checkin/verify，可批量/一键）
  → 写签到记录：checkin_status(1正常/2迟到) + checkin_time + checkin_operator_id（谁核销的）
  → settle_user_pending(user_id, game_id)   # 惰性结算
       · 捞 settled=0 的签到记录 → 汇总 +2 / -3
       · 更新 t_user：credit_score / credit_level / total_game_count / absent_count
       · 记录置 settled=1 并写 credit_delta（信誉流水可查）
       · 分数 < 60 → 自动进小黑屋 3 天（返回 banned + ban_end_time）
  → 球局结束后 absent-judgement 只处理「未签到且未请假」者 → 已核销者不会被判缺席
```

核销数据同时为 AI 信誉画像（`/api/v1/ai/profile` 的 `total_game_count`/`absent_count`）提供输入。

### 球局相关配置（`.env`）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `GAME_SIGNUP_ALLOW_WAITLIST` | true | 满员后是否进入候补队列；false 则直接拒绝 |
| `GAME_CONFLICT_BUFFER_MINUTES` | 0 | 时间冲突判定缓冲（分钟），>0 时要求两场之间留出间隔 |
| `GAME_CANCEL_DEADLINE_MINUTES` | 0 | 开球前 N 分钟内禁止退出；0=不限制 |
| `GAME_MAX_PAGE_SIZE` | 50 | 列表每页最大条数 |
| `CHECKIN_OPEN_BEFORE_MINUTES` | 30 | 未配置核销窗口时，默认开球前 30 分钟开放核销 |
| `CHECKIN_LATE_AFTER_MINUTES` | 15 | 未配置核销截止时，默认开球后 15 分钟内到场算正常（超过记迟到 -3） |

### match_score（AI 匹配分）

`match_score` 目前返回**静态固定占位值 80.0**（`app/core/constants.py::MATCH_SCORE_PLACEHOLDER`），
前端可先用于排序/展示；AI 智能匹配模块接入后只需替换 `services/game.py` 中 `GameRow.match_score` 的赋值，
**接口字段与结构不变**。

### 数据库增量

v1.0 → v1.1 新增 `t_checkin_record.checkin_operator_id`（核销人）与 `t_game.idx_game_venue_time`（场地+时间索引）：

```bash
mysql -uroot -p campus_ball < sql/003_migration_v1_1.sql
```

---

## 五、小黑屋失信惩罚模块（六条规则的落地）

| 规则 | 实现 | 入口 |
| --- | --- | --- |
| ① 缺席判定（已报名+未签到+未请假）+ **每小时兜底扫描** | `finalize_game()` / `scan_overdue_games()` | `POST /game/{id}/finish`、`POST /blacklist/scan-absent`、后台任务 |
| ② 缺席即封禁，时长固定 3 天（`end = start + 3天`） | `apply_ban()` | 缺席判定自动触发 |
| ③ 封禁期间只拦**发局/报名**，返回 `{"code":403,"msg":"您因放鸽子被禁赛，将于 x 解除"}`；查询类放行 | `is_ban_blocked_request()` + `get_current_active_user` + 中间件钩子 | — |
| ④ **惰性解封**（`ban_end_time > NOW()` 即视为封禁中，不依赖定时任务）；记录永久留存含 `reason` | `get_active_ban()` / `list_bans()` | `GET /blacklist/me`、`/blacklist/records` |
| ⑤ 用户表 `reputation_score` 同步扣分（缺席 **-10**） | `CREDIT_RULES[ABSENT] = -10` | 惰性结算时落库 |
| ⑥ **连续缺席不叠加**：封禁期内再次缺席 → 不新建记录，**顺延**原记录 | `_extend_ban()` | 见下方规则说明 |

### 规则⑥ 连续缺席处理逻辑（设计说明）

| 情形 | 处理 |
| --- | --- |
| 当前**无**生效封禁 | 新建记录：`ban_start_time=now`、`3 天`、`ban_end_time = start + 3天` |
| 当前**已有**生效封禁 | **不新建**，只顺延：`ban_end_time = max(原 ban_end_time, now) + 3天`；首次顺延写入 `ban_original_end_time`；`ban_extend_count += 1` |
| 原封禁**已过期**后再缺席 | 视同新建（历史记录永久保留，可追溯） |

- **扣分与失信次数始终照常累计**（`-10` / `absent_count++`），封禁与信用记录相互独立；
- **从 `ban_end_time` 顺延而非从 `now` 顺延**：符合「先服完当前惩罚再加罚」的直觉，否则连续缺席会让解禁时间**提前**（越蹲越短）；
- **设总时长上限** `BAN_MAX_TOTAL_DAYS`（默认 30 天）防止无限顺延变成事实永久封禁，触顶后 `capped=true`；
- 实测：第 1 次缺席封至 11-21，封禁期内再次缺席 → 同一条记录顺延至 11-24（`extend_count=1`，`ban_original_end_time=11-21`）。

### 拦截范围（为什么不是「拦所有写操作」）

| 拦截（403） | 放行 |
| --- | --- |
| `POST /game`（发起球局）、`POST /game/{id}/signup`（报名） | 全部查询接口、`/blacklist/me`、`/user/me`、**签到/核销/请假/退出球局** |

若拦掉所有非查询请求，用户既不能签到也不能退出，会被反复判缺席导致惩罚滚雪球，
且与「历史遗留球局仍可签到」的要求冲突。需要更严格时把 `BAN_BLOCK_ALL_WRITES=true`。

### 双层防护与配置

```
中间件钩子 blacklist_hook（全局兜底，任何路径都不会漏）
        +
接口依赖 get_current_active_user / RequireActiveUser（接口契约，显式声明）
        两者共用 is_ban_blocked_request() 的拦截口径，规则永远一致
```

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BAN_DEFAULT_DAYS` | 3 | 封禁时长（天） |
| `BAN_ON_ABSENT` | true | 缺席是否直接封禁 |
| `BAN_EXTEND_ON_REPEAT` | true | 封禁期内再次缺席是否顺延（false 则新建） |
| `BAN_MAX_TOTAL_DAYS` | 30 | 顺延后总时长上限 |
| `BAN_BLOCK_ALL_WRITES` | false | 严格模式：拦全部非查询请求 |
| `ABSENT_SCAN_ENABLED` | true | 兜底扫描开关 |
| `ABSENT_SCAN_INTERVAL_SECONDS` | 3600 | 扫描间隔（秒） |

数据库增量：`mysql -uroot -p campus_ball < sql/004_migration_v1_2.sql`
（`credit_score` → `reputation_score`，ORM 用 synonym 保留兼容别名，接口同时返回两个字段）

---

## 六、AI 信誉画像模块（详细见 [docs/API_AI_PROFILE.md](docs/API_AI_PROFILE.md)）

### 双轨算法

| 轨道 | 触发条件 | 输出 |
| --- | --- | --- |
| A：DeepSeek | 配置了 `DEEPSEEK_API_KEY` 且 `AI_ENABLED=true` | 标签 / 风险等级 / 总结 / 建议 / AI 建议分 |
| B：本地加权规则（降级） | 无 Key、调用失败、返回非法 —— 全自动切换 | 同一结构（`source=rule`、`degraded=true`） |

### 本地加权规则（权重表，确定性可复算）

```
画像分 = clamp(初始分100 + 2×按时签到 - 3×迟到 - 10×无故缺席 - 2×主动退出 - 4×临期退出 + 守约加成, 0, 150)
```
- 按时签到 **+2**（加分）／无故缺席 **-10**（大幅扣分）／主动退出 **-2**（少量扣分，与惰性结算口径一致）
- 临近开球（≤2h）退出 **-4**；请假 **0**（提前告知不惩罚）
- 守约加成：完成 ≥5 场且守约率 ≥95% → **+3**
- 响应返回 `breakdown`（项/次数/权重/小计），前端可直接展示「分数怎么来的」

### 融合与两个分数的分工

```
最终画像分 = 0.3 × AI建议分 + 0.7 × 本地加权分   且 |调整| ≤ 8 分（限幅，防模型幻觉）
```

| 分数 | 字段 | 用途 |
| --- | --- | --- |
| 操作分 | `t_user.reputation_score` | 报名门槛、封禁阈值（只由签到/缺席事件驱动的确定性结算） |
| 画像分 | `t_user.ai_score` | 个人主页展示、球局匹配参考、`score_gap` 运营预警 |

### 惰性触发（签到 / 缺席 / 退出）

```
签到·核销·缺席·退出 → 同一事务置 dirty=1（记 trigger）
   → ① 立即异步重算（不阻塞响应）② 后台每 600s 兜底 ③ 用户查看画像/主页时按需重算
```

### 下游应用

| 场景 | 说明 |
| --- | --- |
| 个人主页 | `GET /api/v1/user/{user_id}/profile`：信誉分 + 等级 + 标签 + 行为统计 + 加权明细 |
| 球局匹配 | `match_score`（0-100）= 60 + 20×信誉归一 + 12×球技匹配 + 8×球类偏好 - 5×满员；时间冲突或低于门槛 → 0，并给出 `match_reason` |
| 画像接口 | `GET /api/v1/ai/profile`（查看）、`/ai/explain`（算法说明）、`/ai/stats`（运行状态）、`POST /ai/refresh-dirty`（管理端批量补算） |

数据库增量：`mysql -uroot -p campus_ball < sql/005_migration_v1_3.sql`

---

## 七、后续扩展指引

| 扩展点 | 改动位置 |
| --- | --- |
| 新增业务模块（通知、智能匹配） | 新建 `app/api/v1/xxx.py` + `app/services/xxx.py`，在 `app/api/v1/__init__.py` 注册 |
| JWT 增加角色/权限 | `app/core/security.py` 的 `extra_claims` + `app/api/deps.py::get_current_admin`（可换为 RBAC 表） |
| 新增全局拦截规则 | `app/middleware/hooks.py` 写个 `async def hook(request, user_id)` 再 `register_auth_hook()` 注册 |
| 新增公开接口（免登录） | 把路径加入 `app/middleware/auth.py::PUBLIC_PREFIXES`，不用改接口代码 |
| 强制下线（踢人） | `security` 已生成 `jti`，接入 Redis 后按 jti 拉黑即可（`services/auth.logout` 已预留位置） |
| 替换密码算法 | 只改 `app/core/security.py`：`hash_password/verify_password/needs_rehash` 三个函数；旧哈希靠 `needs_rehash` 平滑升级 |
| 替换 AI 服务商 | 只改 `app/services/ai_profile.py`，返回值结构保持不变 |
| 加信誉分流水表 | 目前复用 `t_checkin_record`；如需更细粒度审计可新增 `t_credit_log` |
| 接入 Alembic 迁移 | `alembic init` 后用 `app.db.base.Base.metadata` 作为 target_metadata，同步串用 `sqlalchemy_sync_database_uri` |
| 定时任务（缺席自动判定） | 参考 `app/main.py::_auto_release_loop`，扩展为「扫已结束未结算球局 → 自动判定缺席」 |
| AI 智能匹配（替换 match_score） | 改 `services/game.py::GameRow.match_score` 赋值 + 复用 `services/ai_profile.py` 的 DeepSeek 调用；接口结构不变 |

> 类型说明：生产建表 SQL 对小型枚举字段使用 `TINYINT/SMALLINT` 以节省空间；
> ORM 中以 `Integer` 声明（跨库通用），读写不受影响，以数据库实际列定义为准。
