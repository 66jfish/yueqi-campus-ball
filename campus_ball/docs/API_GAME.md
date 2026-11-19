# 球局核心业务 · 接口文档

> 模块：`app/api/v1/game.py` + `app/api/v1/checkin.py` + `app/services/game.py` + `app/services/checkin.py`
> 版本：v1.1 　接口前缀：`/api/v1`
> 在线调试：启动后访问 `http://127.0.0.1:8000/docs`（Swagger UI 可直接试跑）
> 依赖：JWT 鉴权（见 `docs/API_AUTH.md`）、MySQL 表结构（见 `sql/001_schema.sql`）

---

## 一、接口总览

| # | 方法 | 路径 | 说明 | 鉴权 |
| --- | --- | --- | --- | --- |
| ① | POST | `/api/v1/game` | 发起球局（含**同场地同时段冲突**校验） | 需登录 |
| ② | GET | `/api/v1/game` | 球局列表（筛选 + 分页，**sport_type 球类筛选**、**match_score**） | 可选登录 |
| ③ | GET | `/api/v1/game/{game_id}` | 球局详情（含核销统计） | 可选登录 |
| ④ | POST | `/api/v1/game/{game_id}/signup` | 报名加入球局（**用户时间冲突** + **球局未满**校验） | 需登录 |
| ⑤ | POST | `/api/v1/game/{game_id}/exit` | 退出球局（自动候补补位） | 需登录 |
| ⑥ | POST | `/api/v1/checkin/verify` | **签到核销**（发起人给到场用户签到，触发惰性结算） | 需登录·发起人 |
| 附 | GET | `/api/v1/checkin/game/{game_id}` | 核销名单（谁到了、谁没到，含到场统计） | 需登录·发起人 |
| 附 | GET | `/api/v1/game/{game_id}/members` | 报名名单（正式 + 候补） | 可选登录 |
| 附 | POST | `/api/v1/checkin/absent-judgement` | 缺席判定（球局结束后批量惰性结算） | 需登录·发起人 |

统一响应：`{"code": int, "message": str, "data": any}`；`code=0` 为成功。

**小黑屋拦截**：禁赛期内访问以上任何接口，都会在认证中间件层被统一拦截（`403 / 40301`），接口内无需重复判断。

---

## 二、通用约定

### 2.1 枚举值

| 字段 | 取值 |
| --- | --- |
| `sport_type` 球类 | 1-篮球 2-足球 3-羽毛球 4-网球 5-排球 6-乒乓球 |
| `status` 球局状态 | 0-草稿 1-报名中 2-报名截止 3-进行中 4-已结束 5-已取消 |
| `settle_status` 结算状态 | 0-待结算 1-已结算 2-部分结算 |
| `registration.status` 报名状态 | 1-已报名 2-已取消 3-候补中 4-被移出 |
| `checkin_status` 签到状态 | 0-未签到 1-正常签到 2-迟到 3-缺席 4-已请假 |
| `checkin_type` 签到方式 | 1-扫码 2-定位打卡 3-发起人核销/人工补签 |
| `fee_type` 费用类型 | 0-免费 1-AA制 |

### 2.2 关键规则

| 规则 | 说明 | 相关配置 |
| --- | --- | --- |
| 同场地同时段冲突 | 同一 `(campus, venue_name)` 在 `[start, end)` 有重叠的未取消球局 → 拒绝创建 | `GAME_CONFLICT_BUFFER_MINUTES`（默认 0） |
| 用户时间冲突 | 用户在同一时段已「正式报名」其它球局 → 拒绝报名/发起（候补不占用时间） | 同上 |
| 球局未满 | 满员时默认进入候补队列并返回位次；关闭候补则直接拒绝 | `GAME_SIGNUP_ALLOW_WAITLIST`（默认 true） |
| 退出限制 | 开球后禁止退出；可配置开球前 N 分钟内禁止退出 | `GAME_CANCEL_DEADLINE_MINUTES`（默认 0=不限制） |
| 候补补位 | 正式名额退出后，系统自动把候补队列第一位提升为正式名额 | — |
| 核销窗口 | 优先用球局的 `checkin_start_time/checkin_end_time`；未填则自动推算 | `CHECKIN_OPEN_BEFORE_MINUTES=30`、`CHECKIN_LATE_AFTER_MINUTES=15` |
| 迟到判定 | 超过核销截止时间核销 → 记为迟到（-3 分）；窗口内 → 正常（+2 分） | — |
| 逾期核销 | 球局已结算后不可再核销（避免重复结算），需走申诉 | — |
| **match_score** | **AI 匹配分，当前返回静态固定占位值 80.0**；AI 智能匹配模块接入后替换为按用户画像实时计算的值，字段结构不变 | `MATCH_SCORE_PLACEHOLDER` |

### 2.3 异常响应约定

| code | HTTP | 含义 | 典型场景 |
| --- | --- | --- | --- |
| 0 | 200 | 成功 | — |
| 40000 | 400/422 | 参数错误 | 结束时间早于开球时间、page_size 超限、sport_type 非法 |
| 40100 | 401 | 未登录 | 未带 Token 调用报名/退出/核销 |
| 40101 / 40102 / 40103 | 401/403 | 令牌过期 / 非法 / 账号禁用 | — |
| 40300 | 403 | 无权限 | 非发起人调用核销、查看核销名单 |
| 40301 | 403 | 小黑屋禁赛中 | 禁赛用户报名、核销、发起球局 |
| 40400 | 404 | 资源不存在 | 球局 ID 不存在 |
| 40900 | 409 | 业务冲突 | 场地冲突、时间冲突、满员、重复报名、已截止、不可退出、核销未开放 |

所有 409 的 `message` 都写成**可直接展示给用户的中文提示**，并尽量带上关键信息（冲突球局名、时间、当前分数、开放时间等）。

---

## 三、① 发起球局

`POST /api/v1/game`　需登录

### 请求参数（JSON Body）

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| sport_type | int | 否 | 1-6 | 球类，默认 1（篮球） |
| title | string | 是 | 2-64 | 球局标题 |
| description | string | 否 | ≤500 | 描述（水平要求、装备要求等） |
| campus | string | 否 | ≤64 | 校区（与场地名共同用于冲突校验） |
| venue_name | string | 否 | ≤64 | 场地名称（**填了才做同时段冲突校验**） |
| venue_address | string | 否 | ≤128 | 详细地址 |
| start_time | datetime | 是 | 不早于当前时间 1 小时 | 开球时间 |
| end_time | datetime | 是 | 晚于 start_time | 结束时间 |
| signup_deadline | datetime | 否 | 不晚于 start_time | 报名截止 |
| checkin_start_time | datetime | 否 | 不晚于 start_time | 核销开放时间，缺省=开球前 30 分钟 |
| checkin_end_time | datetime | 否 | — | 核销截止，缺省=开球后 15 分钟（超过记迟到） |
| max_players | int | 否 | 2-50 | 最大人数（含发起人），默认 10 |
| min_players | int | 否 | 2-50 | 最少成局人数，默认 2 |
| fee_type | int | 否 | 0/1 | 0-免费 1-AA制 |
| fee_amount | decimal | 否 | ≥0 | 人均费用 |
| skill_level_limit | int | 否 | 0-5 | 最低球技要求，0=不限 |
| gender_limit | int | 否 | 0/1/2 | 0-不限 1-仅男生 2-仅女生 |
| min_credit_score | int | 否 | ≥0 | 报名最低信誉分，0=不限 |

### 请求示例

```json
{
  "sport_type": 1,
  "title": "周五晚东区篮球局",
  "description": "水平不限，重在参与，请自备球鞋",
  "campus": "老校区",
  "venue_name": "老校区体育馆 3 号场",
  "venue_address": "老校区体育馆一层",
  "start_time": "2026-11-20T19:00:00",
  "end_time": "2026-11-20T21:00:00",
  "signup_deadline": "2026-11-20T17:00:00",
  "max_players": 10,
  "min_players": 4,
  "fee_type": 0
}
```

### 成功响应 200（发起人自动占 1 个名额）

```json
{
  "code": 0,
  "message": "球局创建成功",
  "data": {
    "id": 101,
    "creator_id": 1,
    "sport_type": 1,
    "title": "周五晚东区篮球局",
    "campus": "老校区",
    "venue_name": "老校区体育馆 3 号场",
    "start_time": "2026-11-20T19:00:00",
    "end_time": "2026-11-20T21:00:00",
    "checkin_start_time": "2026-11-20T18:30:00",
    "checkin_end_time": "2026-11-20T19:15:00",
    "max_players": 10,
    "current_players": 1,
    "slots_left": 9,
    "is_full": false,
    "status": 1,
    "settle_status": 0,
    "match_score": 80.0,
    "creator_nickname": "球场小王子",
    "waitlist_count": 0,
    "my_registration_status": 1,
    "my_checkin_status": 0
  }
}
```

### 失败响应

```json
// 409 场地冲突（同场地同时段已被占用）
{
  "code": 40900,
  "message": "场地冲突：老校区体育馆 3 号场 在 11-20 19:00~21:00 已被「周五晚东区篮球局」占用，请更换场地或调整时间",
  "data": null
}

// 409 时间冲突（发起人自己同时段已报名别的球局）
{
  "code": 40900,
  "message": "时间冲突：您在同一时段已加入「羽毛球双打」（11-20 19:30~21:00），无法再发起球局",
  "data": null
}

// 400 时间非法
{ "code": 40000, "message": "参数错误：结束时间必须晚于开球时间", "data": [...] }
```

---

## 四、② 球局列表（筛选 + 分页）

`GET /api/v1/game`　可选登录（登录后会额外返回「我的报名/签到状态」）

### 请求参数（Query）

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| **sport_type** | int | 否 | — | **球类筛选：不传 → 返回全部球类；传值（1-6）→ 按球类过滤** |
| campus | string | 否 | — | 校区精确筛选 |
| venue_name | string | 否 | — | 场地名称（模糊匹配） |
| status | int | 否 | — | 球局状态筛选 |
| keyword | string | 否 | — | 关键词（匹配标题/描述） |
| start_date | datetime | 否 | — | 开球时间下界（含） |
| end_date | datetime | 否 | — | 开球时间上界（含） |
| creator_id | int | 否 | — | 按发起人筛选 |
| only_available | bool | 否 | false | 只看「报名中且未满」 |
| sort_desc | bool | 否 | false | false=按开球时间升序（默认），true=降序 |
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 10 | 每页条数，最大 50 |

### 请求示例

```
# 不传 sport_type：返回全部球类
GET /api/v1/game?page=1&page_size=10

# 只看足球（sport_type=2），且只看还有名额的
GET /api/v1/game?sport_type=2&only_available=true
```

### 成功响应 200

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "list": [
      {
        "id": 101,
        "creator_id": 1,
        "creator_nickname": "球场小王子",
        "sport_type": 1,
        "title": "周五晚东区篮球局",
        "campus": "老校区",
        "venue_name": "老校区体育馆 3 号场",
        "start_time": "2026-11-20T19:00:00",
        "end_time": "2026-11-20T21:00:00",
        "max_players": 10,
        "min_players": 4,
        "current_players": 3,
        "slots_left": 7,
        "is_full": false,
        "waitlist_count": 0,
        "match_score": 80.0,
        "status": 1,
        "my_registration_status": null,
        "my_checkin_status": null
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 10,
    "pages": 1
  }
}
```

> **match_score 说明**：当前固定返回 `80.0`（`app/core/constants.py::MATCH_SCORE_PLACEHOLDER`）。
> 前端可先按该字段排序占位；AI 智能匹配模块接入后改为按用户画像实时计算，**字段名与结构不变**。

---

## 五、③ 球局详情

`GET /api/v1/game/{game_id}`　可选登录

### 路径参数

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| game_id | int | 球局ID |

### 成功响应 200

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "id": 101,
    "title": "周五晚东区篮球局",
    "creator_id": 1,
    "creator_nickname": "球场小王子",
    "creator_credit_score": 100,
    "sport_type": 1,
    "campus": "老校区",
    "venue_name": "老校区体育馆 3 号场",
    "venue_address": "老校区体育馆一层",
    "start_time": "2026-11-20T19:00:00",
    "end_time": "2026-11-20T21:00:00",
    "checkin_start_time": "2026-11-20T18:30:00",
    "checkin_end_time": "2026-11-20T19:15:00",
    "max_players": 10,
    "current_players": 3,
    "slots_left": 7,
    "is_full": false,
    "waitlist_count": 1,
    "match_score": 80.0,
    "status": 1,
    "settle_status": 0,
    "checked_count": 0,
    "late_count": 0,
    "absent_count": 0,
    "not_checked_count": 3,
    "is_creator": false,
    "my_registration_status": 1,
    "my_checkin_status": 0
  }
}
```

### 失败响应

```json
{ "code": 40400, "message": "球局不存在或已删除", "data": null }
```

---

## 六、④ 报名加入球局

`POST /api/v1/game/{game_id}/signup`　需登录

### 请求参数

无 Body；`game_id` 走路径参数。

### 校验顺序（异常提示按此顺序返回）

1. 球局是否可报名（草稿/已取消/已结束都不可报名）
2. 报名是否已截止
3. 是否重复报名（含候补）
4. 门槛：信誉分 / 球技 / 性别
5. **用户时间冲突**（同一时段已正式报名其它球局）
6. **球局是否已满**（满员 → 进候补 或 直接拒绝）

### 成功响应 200

```json
// 正常报名
{
  "code": 0,
  "message": "报名成功（4/10）",
  "data": {
    "registration": {
      "id": 88,
      "game_id": 101,
      "user_id": 2,
      "status": 1,
      "is_waitlist": 0,
      "waitlist_order": 0,
      "signup_time": "2026-11-18T10:00:00",
      "credit_snapshot": 100
    },
    "is_waitlist": false,
    "current_players": 4
  }
}

// 满员进候补
{
  "code": 0,
  "message": "球局已满，您已进入候补队列（第 1 位）",
  "data": {
    "registration": { "status": 3, "is_waitlist": 1, "waitlist_order": 1 },
    "is_waitlist": true,
    "current_players": 10
  }
}
```

### 失败响应（全部为 409 + 可直接展示的中文提示）

```json
{ "code": 40900, "message": "时间冲突：您在 11-20 19:00~21:00 已加入「周五晚东区篮球局」，无法再报名同时段的球局", "data": null }
{ "code": 40900, "message": "球局已满（10/10），请关注后续空位", "data": null }
{ "code": 40900, "message": "您已报名该球局，无需重复报名", "data": null }
{ "code": 40900, "message": "您已在该球局的候补队列中（第 1 位）", "data": null }
{ "code": 40900, "message": "报名已于 11-20 17:00 截止", "data": null }
{ "code": 40900, "message": "该球局要求信誉分不低于 80，您当前 55 分，暂无法报名", "data": null }
{ "code": 40900, "message": "该球局要求球技水平不低于 3 级，您当前 1 级", "data": null }
{ "code": 40900, "message": "该球局仅限女生，您不符合报名条件", "data": null }
{ "code": 40900, "message": "球局已开始，无法报名", "data": null }
{ "code": 40900, "message": "该球局当前状态为「已结束」，不可报名", "data": null }
```

---

## 七、⑤ 退出球局

`POST /api/v1/game/{game_id}/exit`　需登录

### 请求参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| game_id | path | int | 是 | 球局ID |
| reason | query | string | 否 | 退出原因，≤255 |

### 成功响应 200（退出正式名额后自动补位）

```json
{
  "code": 0,
  "message": "已退出球局，已自动通知候补球友补位",
  "data": {
    "registration": {
      "id": 88, "game_id": 101, "user_id": 2,
      "status": 2, "is_waitlist": 0, "waitlist_order": 0,
      "signup_time": "2026-11-18T10:00:00"
    },
    "promoted_user_id": 7,
    "current_players": 9
  }
}
```

> 退出后本人**待结算的签到记录会被作废**，因此不会被误判缺席、不会扣分；
> 补位者会获得一条新的待结算签到记录，可正常参与核销与缺席判定。

### 失败响应

```json
{ "code": 40900, "message": "您尚未报名该球局，无需退出", "data": null }
{ "code": 40900, "message": "球局已开始，无法退出；确需退出请联系发起人", "data": null }
{ "code": 40900, "message": "距开球不足 120 分钟，已无法退出（截止 11-20 17:00）", "data": null }
{ "code": 40900, "message": "该球局已取消，无需退出", "data": null }
```

---

## 八、⑥ 签到核销（发起人给到场用户签到）

`POST /api/v1/checkin/verify`　需登录，**仅球局发起人**

### 请求参数（JSON Body）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| game_id | int | 是 | 球局ID |
| user_ids | int[] | 二选一 | 要核销的用户ID列表 |
| verify_all | bool | 二选一 | true=一键核销该球局所有「已报名但未核销」的用户 |
| as_late | bool\|null | 否 | true-强制记为迟到(false=正常)；null(默认)-按核销时间自动判定 |
| remark | string | 否 | 备注，写入签到记录便于追溯 |

### 请求示例

```json
// 勾选核销
{ "game_id": 101, "user_ids": [2, 3], "remark": "现场核销" }

// 一键核销全部未核销者
{ "game_id": 101, "verify_all": true }
```

### 成功响应 200（逐人返回结果 + 信誉分变动）

```json
{
  "code": 0,
  "message": "核销完成：成功 2 人，失败 1 人",
  "data": {
    "game_id": 101,
    "verified_count": 2,
    "skipped_count": 0,
    "failed_count": 1,
    "checkin_open_at": "2026-11-20T18:30:00",
    "checkin_close_at": "2026-11-20T19:15:00",
    "items": [
      {
        "user_id": 2,
        "nickname": "羽毛球爱好者",
        "ok": true,
        "skipped": false,
        "reason": null,
        "checkin_status": 1,
        "checkin_status_text": "已签到",
        "credit_before": 100,
        "credit_delta": 2,
        "credit_after": 102,
        "banned": false,
        "ban_end_time": null
      },
      {
        "user_id": 9,
        "nickname": null,
        "ok": false,
        "skipped": false,
        "reason": "该用户未报名此球局或已退出，无法核销",
        "checkin_status": null,
        "credit_delta": null
      }
    ]
  }
}
```

### 失败 / 跳过说明

| 情况 | HTTP | code | 提示 |
| --- | --- | --- | --- |
| 非发起人 | 403 | 40300 | 只有球局发起人可以执行该操作 |
| 小黑屋禁赛中 | 403 | 40301 | 您已被限制参与球局（禁赛 3 天），预计 xx 解封 |
| 窗口未开放 | 409 | 40900 | 核销尚未开放，11-20 18:30 起可核销（开球前 30 分钟） |
| 已结算 | 409 | 40900 | 该球局已完成结算，无法再核销；如需更正请联系管理员申诉 |
| 已取消 | 409 | 40900 | 该球局已取消，无法核销签到 |
| 参数缺失/重复 | 422 | 40000 | 请传入 user_ids 或设置 verify_all=true / user_ids 中存在重复用户 |
| 该用户已核销 | 200 | 0 | 该条 `skipped=true`，reason=该用户已核销过，无需重复核销 |
| 该用户已请假 | 200 | 0 | 该条 `skipped=true`，reason=该用户已请假，无需核销 |
| 该用户未报名 | 200 | 0 | 该条 `ok=false`，reason=该用户未报名此球局或已退出，无法核销 |

### 核销与惰性结算的关系

```
发起人核销
   ├─ 写入签到记录：checkin_status=1/2（到场状态）、checkin_time、checkin_operator_id（谁核销的）
   └─ 触发惰性结算 settle_user_pending(user_id, game_id)
         ├─ 捞出该用户本球局 settled=0 的签到记录
         ├─ 汇总分值：正常签到 +2 / 迟到 -3
         ├─ 更新 t_user.credit_score / credit_level / total_game_count / absent_count
         ├─ 记录置 settled=1，写入 credit_delta（流水可查）
         └─ 信誉分 < 阈值(60) → 自动进小黑屋 3 天（返回 banned=true + ban_end_time）
```

**幂等性**：已 `settled=1` 的记录不会被二次结算，重复点击核销不会重复加分。
**与缺席判定同源**：球局结束后调用 `/api/v1/checkin/absent-judgement` 时，只处理「未签到且未请假」的人，
因此核销过的人不会被判缺席 —— 核销数据同时为信誉画像（`GET /api/v1/ai/profile`）提供输入。

---

## 九、核销名单（发起人视图）

`GET /api/v1/checkin/game/{game_id}`　需登录，**仅发起人**（否则 `40300`）

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "game_id": 101,
    "title": "周五晚东区篮球局",
    "status": 3,
    "settle_status": 0,
    "start_time": "2026-11-20T19:00:00",
    "checkin_open_at": "2026-11-20T18:30:00",
    "checkin_close_at": "2026-11-20T19:15:00",
    "checkin_open": true,
    "signed_count": 3,
    "checked_count": 1,
    "late_count": 1,
    "absent_count": 0,
    "not_checked_count": 1,
    "waitlist_count": 1,
    "members": [
      {
        "user_id": 2,
        "nickname": "羽毛球爱好者",
        "avatar_url": null,
        "credit_score": 102,
        "registration_status": 1,
        "is_waitlist": 0,
        "checkin_status": 1,
        "checkin_status_text": "已签到",
        "checkin_time": "2026-11-20T18:45:00",
        "credit_delta": 2,
        "settled": 1
      },
      {
        "user_id": 3,
        "nickname": "王五",
        "credit_score": 55,
        "registration_status": 1,
        "is_waitlist": 0,
        "checkin_status": 0,
        "checkin_status_text": "未签到",
        "checkin_time": null,
        "credit_delta": 0,
        "settled": 0
      }
    ]
  }
}
```

> 普通用户请在球局详情里看自己的 `my_checkin_status`（名单含他人信誉分，仅发起人可见）。

---

## 十、完整调用链路示例（curl）

```bash
# 1) 登录拿令牌
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"account":"20230001","password":"abc123456"}' | python -c "import sys,json;print(json.load(sys.stdin)['data']['token']['access_token'])")

# 2) 发起球局
curl -X POST http://127.0.0.1:8000/api/v1/game -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sport_type":1,"title":"周五晚东区篮球局","campus":"老校区","venue_name":"老校区体育馆 3 号场",
       "start_time":"2026-11-20T19:00:00","end_time":"2026-11-20T21:00:00","max_players":10}'

# 3) 列表：不传 sport_type 返回全部；只看足球
curl "http://127.0.0.1:8000/api/v1/game?page=1&page_size=10"
curl "http://127.0.0.1:8000/api/v1/game?sport_type=2&only_available=true"

# 4) 详情
curl http://127.0.0.1:8000/api/v1/game/101

# 5) 报名
curl -X POST http://127.0.0.1:8000/api/v1/game/101/signup -H "Authorization: Bearer $TOKEN"

# 6) 退出
curl -X POST "http://127.0.0.1:8000/api/v1/game/101/exit?reason=临时有事" -H "Authorization: Bearer $TOKEN"

# 7) 发起人核销（给 2、3 号用户签到，触发惰性结算）
curl -X POST http://127.0.0.1:8000/api/v1/checkin/verify -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"game_id":101,"user_ids":[2,3],"remark":"现场核销"}'

# 8) 核销名单
curl http://127.0.0.1:8000/api/v1/checkin/game/101 -H "Authorization: Bearer $TOKEN"

# 9) 球局结束后判定缺席（只处理未签到者）
curl -X POST http://127.0.0.1:8000/api/v1/checkin/absent-judgement -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"game_id":101,"auto_prune":true}'
```

---

## 十一、数据库变更（v1.0 → v1.1）

| 变更 | 位置 | 说明 | 迁移脚本 |
| --- | --- | --- | --- |
| 新增 `checkin_operator_id` | `t_checkin_record` | 记录核销/补签操作人，便于追溯「谁给谁签的到」 | `sql/003_migration_v1_1.sql` |
| 新增 `idx_game_venue_time` | `t_game` | `(venue_name, start_time)` 联合索引，支撑同场地同时段冲突校验 | 同上 |

```bash
mysql -uroot -p campus_ball < sql/003_migration_v1_1.sql
```

---

## 十二、前端响应式对接建议（Vue3 + Element Plus）

| 场景 | 手机（<768px） | 平板（768-992px） | 桌面（>992px） |
| --- | --- | --- | --- |
| 球局列表 | `el-card` 单列 + 底部固定「发起球局」按钮 | 双列卡片 | 三列卡片 + 左侧筛选栏 |
| 筛选栏（sport_type 等） | 顶部折叠 `el-collapse` | 顶部横向 `el-radio-group` | 左侧 `el-form` 常驻 |
| 核销页 | 成员列表 + 大号「核销」按钮，支持全部核销 | 双列 | 表格 + 批量勾选核销 |

```js
// 报名的统一错误提示：后端 message 已是完整中文提示，直接展示即可
const res = await api.post(`/game/${gameId}/signup`)
if (res.code === 40900) ElMessage.warning(res.message)   // 时间冲突 / 已满 / 已截止 …
if (res.code === 40301) ElMessage.error(res.message)     // 小黑屋，可展示解封倒计时
```
