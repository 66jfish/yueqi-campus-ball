# 端到端（E2E）测试用例

> 覆盖：认证 → 发局 → 报名 → 核销 → 缺席判定 → 自动封禁 → 拦截 → 惰性解封 → AI 画像 → 个人主页
> 两种执行方式：
> 1. **自动化 pytest 套件**（已实际跑通，**110 个用例全部通过**）：`cd campus_ball && pytest -q`
>    用内存 SQLite + 依赖覆盖模拟数据库，不需要 MySQL/TiDB，覆盖每个模块的分支与边界
> 2. **真实 HTTP 端到端脚本**（对着已部署服务跑）：`python campus_ball/scripts/e2e_check.py --base https://<后端域名>/api/v1`
>    会真实写入数据，请只在测试环境执行

---

## 一、用例总览

| # | 用例 | 关键校验点 | 对应接口 | pytest 覆盖 |
| --- | --- | --- | --- | --- |
| E2E-01 | 健康检查与数据库连通 | `code=0`、`database=true` | `GET /health` | ✔ test_smoke |
| E2E-02 | 注册学生账号 | 学号唯一、密码 bcrypt 入库（`$2b$12$`）、初始信誉分 100 | `POST /auth/register` | ✔ test_auth |
| E2E-03 | 登录签发双令牌 | 返回 access/refresh、载荷含 `sub/jti/type/iss/aud` | `POST /auth/login` | ✔ test_auth |
| E2E-04 | 未登录访问受保护接口 | HTTP 401 + `code=40100` | `GET /user/me` | ✔ test_auth |
| E2E-05 | 令牌过期 / 非法 | `40101` / `40102` 区分返回 | 任意受保护接口 | ✔ test_auth |
| E2E-06 | 发起球局 | 报名中状态、发起人占 1 名额、自动补核销窗口 | `POST /game` | ✔ test_game |
| E2E-07 | **同场地同时段冲突** | 409 + 提示含冲突球局名与占用时段 | `POST /game` | ✔ test_game |
| E2E-08 | 发起人时间冲突 | 自己同时段已报名其它球局 → 拒绝发局 | `POST /game` | ✔ test_game |
| E2E-09 | 球局列表筛选分页 | `sport_type` 不传=全部/传值=过滤、`match_score`、分页 pages | `GET /game` | ✔ test_game |
| E2E-10 | 报名加入球局 | 成功后名额 +1、生成待结算签到记录 | `POST /game/{id}/signup` | ✔ test_game |
| E2E-11 | 报名-时间冲突 | 同时段已报名其它球局 → 409 + 冲突球局名 | `POST /game/{id}/signup` | ✔ test_game |
| E2E-12 | 报名-球局已满 | 满员进候补（位次从 1 开始）/ 关闭候补则直接拒绝 | `POST /game/{id}/signup` | ✔ test_game |
| E2E-13 | 退出球局 + 候补补位 | `promoted_user_id` 非空、退出者待结算记录作废 | `POST /game/{id}/exit` | ✔ test_game |
| E2E-14 | **发起人核销签到** | 标记已签到 + **惰性结算 +2** + 记录核销人 | `POST /checkin/verify` | ✔ test_game |
| E2E-15 | 核销幂等 | 重复核销 → `skipped=true`，信誉分不再变化 | `POST /checkin/verify` | ✔ test_game |
| E2E-16 | 核销-迟到判定 | 超过核销截止 → 迟到 `-3` | `POST /checkin/verify` | ✔ test_game |
| E2E-17 | 核销-非发起人 | 403 `40300` 只有发起人可核销 | `POST /checkin/verify` | ✔ test_game |
| E2E-18 | **结束球局→缺席判定** | 未签到未请假 → 缺席 **-10**、球局状态已结束 | `POST /game/{id}/finish` | ✔ test_game / test_blacklist |
| E2E-19 | **缺席自动封禁 3 天** | `ban_end_time = ban_start_time + 3天`、`reason` 落库 | 缺席判定流程 | ✔ test_blacklist |
| E2E-20 | 兜底扫描补判漏判 | 已过结束时间且未结算的球局被自动判定 | `POST /blacklist/scan-absent` | ✔ test_blacklist |
| E2E-21 | **封禁拦截写操作** | 发局/报名 → HTTP 403 + `code=403` + `msg` 含「禁赛…将于…解除」 | `POST /game`、`/signup` | ✔ test_auth / test_blacklist |
| E2E-22 | **封禁不拦查询/签到** | 球局列表/详情/个人主页/我的封禁状态/历史球局签到核销全部放行 | 多个 GET / `POST /checkin/*` | ✔ test_auth / test_blacklist |
| E2E-23 | **惰性解封（不依赖定时任务）** | 把 `ban_end_time` 改到过去 → 立即 `banned=false` 且可正常发局 | `GET /blacklist/me` | ✔ test_blacklist |
| E2E-24 | 连续缺席不叠加（顺延） | 记录数不变、`extend_count=1`、解禁时间顺延 3 天、`original_end` 留痕 | 缺席判定流程 | ✔ test_blacklist |
| E2E-25 | 顺延上限保护 | 累计顺延到 `BAN_MAX_TOTAL_DAYS`(30) 后不再延长（`capped=true`） | 缺席判定流程 | ✔ test_blacklist |
| E2E-26 | 封禁记录永久留存 | `GET /blacklist/records` 可查历史（含已解封），含 `reason` | `GET /blacklist/records` | ✔ test_blacklist |
| E2E-27 | AI 画像-降级链路 | 无 Key → `source=rule`、`degraded=true`、含标签与加权明细 | `GET /ai/profile` | ✔ test_ai_profile |
| E2E-28 | AI 画像-大模型链路（打桩） | `source=deepseek`、融合限幅 `|ai_adjust| ≤ 8` | `GET /ai/profile` | ✔ test_ai_profile |
| E2E-29 | AI 画像-触发时机 | 签到/缺席/退出后 `dirty=1` 且 `trigger` 正确；读取时重算并清标记 | `GET /ai/profile` | ✔ test_ai_profile |
| E2E-30 | 个人主页展示 | 信誉分 + 等级 + 标签 + 加权明细 + 行为统计，且不含学号/手机号 | `GET /user/{id}/profile` | ✔ test_ai_profile |
| E2E-31 | 球局匹配参考分 | 登录用户按画像算分；时间冲突/低于门槛 → 0 并给出 `match_reason` | `GET /game` | ✔ test_ai_profile |
| E2E-32 | 定时任务入口鉴权 | 未配 `CRON_SECRET` → 403；凭证正确 → 返回三项兜底结果 | `GET /system/cron/daily` | ⚠️ 见下方说明 |
| E2E-33 | 运行时信息 | 展示部署形态、惰性策略、Cron 配置、DB 连接方式 | `GET /system/runtime` | ⚠️ 见下方说明 |

> ⚠️ E2E-32/33 为本轮新增（Serverless 适配），已在 `GET /openapi.json` 中确认路由注册成功，
> 但**尚未补充独立 pytest 用例**，也**未在真实 Vercel 环境验证**（需部署后才能跑）。

---

## 二、核心闭环用例（详细步骤）

### E2E-18 ~ E2E-23：缺席惩罚闭环

**前置**：账号 A（发起人）、B（到场）、C（放鸽子），B、C 均报名同一球局。

| 步骤 | 操作 | 期望结果 |
| --- | --- | --- |
| 1 | A 核销 B 的签到 | `code=0`，B 的 `checkin_status=1`，`credit_delta=+2`，记录 `checkin_operator_id=A` |
| 2 | A 结束球局（`POST /game/{id}/finish`） | `absent_count≥1`（只有 C），球局 `status=已结束`、`settle_status=已结算` |
| 3 | 查 C 的 `reputation_score` | `100 - 10 = 90`，`absent_count=1` |
| 4 | 查 C 的 `GET /blacklist/me` | `banned=true`、`ban_duration_days=3`、`ban_end_time = ban_start_time + 3天`、`reason` 非空 |
| 5 | C 尝试发局 / 报名 | HTTP **403**，body `{"code":403,"msg":"您因放鸽子被禁赛，将于 xxx 解除", ...}` |
| 6 | C 查询球局列表 / 个人主页 / 封禁状态 / 历史球局签到 | 全部 **200**（查询与签到不拦） |
| 7 | 把 C 的 `ban_end_time` 改成 1 小时前（仅测试环境直接改库） | 立即 `banned=false`，发局恢复 200 —— **证明不依赖任何定时任务** |
| 8 | 让 C 在封禁期内再缺席一次 | 小黑屋**记录数仍为 1**、`ban_extend_count=1`、解禁时间**顺延 3 天**、`ban_original_end_time` 记录首次解禁时间、信誉分继续 -10 |

### E2E-27 ~ E2E-31：AI 画像闭环

| 步骤 | 操作 | 期望结果 |
| --- | --- | --- |
| 1 | 未配 `DEEPSEEK_API_KEY` 时调 `GET /ai/profile` | `code=0`；`source=rule`、`degraded=true`、`ai_score=null`、`score=rule_score` |
| 2 | 核销签到后查库 `t_user.ai_profile_dirty` | `=1`，`ai_profile_trigger='checkin'` |
| 3 | 再调 `GET /ai/profile` | 就地重算：`features.checked_count` 增加、`score` 上升、`version+1`、`dirty` 清零 |
| 4 | 缺席判定后重复第 2~3 步 | `trigger='absent'`，`score` 下降 10 |
| 5 | 主动退出后重复第 2~3 步 | `trigger='exit'`，`score` 下降 2 |
| 6 | 给 `DEEPSEEK_API_KEY` 并把模型返回值打桩为 150 | `source=deepseek`、`ai_adjust` 被限幅到 `+8`、`score` 不会跳到 150 |
| 7 | 调 `GET /user/{id}/profile` | 返回信誉分/等级/标签/加权明细/行为统计；**不含学号、手机号、邮箱** |

---

## 三、执行记录（本机实测）

```bash
# 1) 自动化套件（本次实际执行）
cd campus_ball
python -m pytest -q
# → 110 passed（认证 32 + 球局 30 + 小黑屋 15 + AI 画像 25 + 冒烟 8）

# 2) 真实 HTTP 端到端（需先部署或用本地 MySQL/TiDB 起服务）
python campus_ball/scripts/e2e_check.py --base https://<后端域名>/api/v1
# → 输出每项 ✓/✗ 与通过率，失败项会打印响应体
```

**执行状态说明（如实标注）**：

| 项目 | 状态 |
| --- | --- |
| pytest 110 个用例 | ✅ 已执行通过（SQLite 内存库 + 依赖覆盖） |
| 真实 MySQL/TiDB 上的 DDL 执行 | ❌ 未执行（本机无 MySQL/TiDB 实例）；已用「sqlglot MySQL 方言解析 + TiDB 限制规则」静态校验，产出 `sql/tidb/*.sql` |
| 真实 DeepSeek 调用 | ❌ 未执行（无 API Key）；成功/失败两条分支用打桩验证 |
| `scripts/e2e_check.py` 对真实服务 | ❌ 未执行（没有可连的数据库）；脚本已就绪，部署后可直接跑 |
| Vercel Cron 实际触发 | ❌ 未执行（无 Vercel 账号）；配置与鉴权逻辑已实现 |
