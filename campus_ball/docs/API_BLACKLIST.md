# 小黑屋失信惩罚模块 · 接口文档与规则说明

> 模块：`app/services/blacklist.py`、`app/services/checkin.py`（缺席判定）、
> `app/api/deps.py::get_current_active_user`（拦截依赖）、`app/middleware/hooks.py`（全局兜底）
> 版本：v1.2 　接口前缀：`/api/v1/blacklist`
> 数据库变更：`sql/004_migration_v1_2.sql`

---

## 一、规则实现对照

| # | 规则 | 落地实现 | 位置 |
| --- | --- | --- | --- |
| 1 | 球局「已结束」触发缺席判定（已报名+未签到+未请假=缺席）；并有**每小时兜底扫描** | `finalize_game()` / `scan_overdue_games()`；`POST /game/{id}/finish`；后台任务每小时执行 | `services/checkin.py`、`main.py` |
| 2 | 缺席用户自动进小黑屋，时长固定 3 天（`end_time = start_time + 3天`） | `ban_for_absent()` → `apply_ban()` | `services/blacklist.py` |
| 3 | 封禁期间拦截**写操作（发局/报名）**，返回 `{"code":403,"msg":"您因放鸽子被禁赛，将于 {解禁时间} 解除"}`；查询类接口不拦截 | `is_ban_blocked_request()` + `get_current_active_user` 依赖 + 中间件钩子 | `services/blacklist.py`、`api/deps.py`、`middleware/hooks.py` |
| 4 | 自动解封用**惰性判断**（`end_time < now` 即视为解封，不依赖定时任务）；记录永久留存含 `reason` | `get_active_ban()` 查询条件 `ban_end_time > NOW()`；`list_bans()` 永久可查 | `services/blacklist.py` |
| 5 | 用户表同步维护 `reputation_score`，缺席 **-10 分** | `CREDIT_RULES[ABSENT] = -10`，结算时写 `t_user.reputation_score` | `core/constants.py`、`services/reputation.py` |
| 6 | 连续缺席**不叠加封禁** | 封禁期内再次缺席 → 不新建记录，**顺延**原记录（见第二节） | `apply_ban()` / `_extend_ban()` |

### 缺席判定口径

```
已报名（registration.status = 已报名）
   ├─ 已核销 / 已签到 → 到场，+2（迟到 -3），不会被判缺席
   ├─ 已请假         → 0 分，不会被判缺席
   └─ 未签到 + 未请假 → ★缺席：-10 分 + 自动进小黑屋 3 天
```

### 兜底扫描（防止漏判）

- 触发条件：`已过结束时间` + `settle_status = 待结算`，状态为「报名中/报名截止/进行中」都算
  （即发起人忘了点「结束球局」也会被处理）
- 执行频率：`ABSENT_SCAN_INTERVAL_SECONDS`（默认 3600 秒 = 每小时）
- 幂等：已结算的球局被 `settle_status` 过滤，不会重复扣分/重复封禁
- 可手动补偿：`POST /api/v1/blacklist/scan-absent`（管理端）

---

## 二、规则6：连续缺席的处理逻辑（设计说明）

### 问题

用户第一次缺席被封 3 天；在他**仍在封禁期内**时又缺席了第二场球局。
如果每次缺席都新建一条封禁记录，会出现多条记录并存 → 拦截判断要取最大值、
解禁时间含义混乱、封禁次数统计失真。

### 方案

| 情形 | 处理 | 记录变化 |
| --- | --- | --- |
| A. 当前**无**生效封禁 | **新建**一条记录 | `ban_start_time=now`、`ban_duration_days=3`、`ban_end_time=start+3天` |
| B. 当前**已有**生效封禁 | **不新建**，只顺延原记录 | `ban_end_time = max(原ban_end_time, now) + 3天`；首次顺延时把原解禁时间存入 `ban_original_end_time`；`ban_extend_count += 1`；`ban_last_extend_at = now` |
| C. 原封禁**已过期**后再缺席 | 视同情形 A，**新建**记录 | 历史记录全部永久留存，可追溯 |

无论 A/B，**扣分与失信次数都照常累计**（`reputation_score -10`、`absent_count += 1`）——
封禁是惩罚，扣分是信用记录，两者独立。

### 为什么这样设计

1. **不新建记录** → 拦截判断只需问「有没有生效记录」，永远不存在多条并存的歧义；
   同时 `t_checkin_record` 里保留了每一次缺席的时间、球局、分值，审计信息不丢。
2. **从 `ban_end_time` 顺延而不是从 `now` 顺延** →
   符合「先服完当前惩罚再加罚」的直觉；若从 `now` 起算，连续缺席反而会让解禁时间**提前**（越蹲越短），
   与惩罚意图相反。例如：11-18 封到 11-21，11-19 再缺席 → 顺延到 11-24（而不是 11-22）。
3. **首次解禁时间留痕**（`ban_original_end_time`）→ 规则4 要求记录永久留存且可还原最初的 3 天窗口，
   顺延是可审计的（原始窗口 + 顺延次数 + 最近顺延时间）。
4. **设总时长上限** `BAN_MAX_TOTAL_DAYS`（默认 30 天）→
   防止无限顺延变成事实上的永久封禁，校园场景应以教育改正为主；
   触顶后仍照常扣分、照常留痕，只是不再延长封禁（`capped=true` 会体现在响应里）。

### 示例（实测数据）

```
第 1 次缺席  11-18 18:00 → 封至 11-21 18:00   extend_count=0  original_end=null
第 2 次缺席  11-18 18:05 → 封至 11-24 18:00   extend_count=1  original_end=11-21 18:00  （同一条记录）
```

---

## 三、封禁期间的拦截范围（规则3）

| 请求 | 是否拦截 | 说明 |
| --- | --- | --- |
| `POST /api/v1/game` 发起球局 | ❌ **拦截 403** | 占用新球局资源 |
| `POST /api/v1/game/{id}/signup` 报名 | ❌ **拦截 403** | 占用名额 |
| `GET /api/v1/game`、`/game/{id}`、`/game/{id}/members` | ✅ 放行 | 查询类，看球局不受限 |
| `GET /api/v1/user/me`、`/user/me/credit`、`/user/me/credit/history` | ✅ 放行 | 看个人主页含信誉分 |
| `GET /api/v1/blacklist/me`、`/blacklist/records`、`/blacklist/config` | ✅ 放行 | **被封禁用户能看到自己的封禁状态与解禁时间** |
| `POST /api/v1/checkin/checkin`（本人签到） | ✅ 放行 | 规则要求：历史遗留球局仍可签到 |
| `POST /api/v1/checkin/verify`（发起人核销） | ✅ 放行 | 履行既有球局的组织义务 |
| `POST /api/v1/checkin/leave`（请假） | ✅ 放行 | 避免因无法请假而再次缺席 |
| `POST /api/v1/game/{id}/exit`（退出球局） | ✅ 放行 | 否则用户被困在名额里，会持续被判缺席 |

> 为什么用「明确黑名单」而不是「拦截所有写操作」：
> 若拦掉全部非 GET 请求，用户既不能签到也不能退出，惩罚会滚雪球式失控，
> 与规则3 中「历史遗留球局仍可签到」的要求直接冲突。
> 需要更严格时把 `.env` 的 `BAN_BLOCK_ALL_WRITES` 设为 `true` 即可（拦截全部非查询请求）。

### 拦截响应（实测）

```json
HTTP/1.1 403 Forbidden
{
  "code": 403,
  "msg": "您因放鸽子被禁赛，将于 2026-11-21 18:15 解除",
  "message": "您因放鸽子被禁赛，将于 2026-11-21 18:15 解除",
  "data": {
    "banned": true,
    "ban_end_time": "2026-11-21T18:15:57",
    "ban_duration_days": 3,
    "ban_extend_count": 0,
    "reason": "缺席球局（未签到且未请假），球局ID=11",
    "reason_type": 1
  }
}
```

- `code = 403`、`msg` 字段按产品规则输出；
- 同时保留平台统一的 `message` 字段（与 `msg` 同值），既有前端解析逻辑无需改动；
- 原因类型非「缺席」时文案为「您已被禁赛，将于 {解禁时间} 解除」。

---

## 四、接口清单

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/v1/blacklist/me` | 登录 | **我的封禁状态**（被封禁也能查：解禁时间、倒计时、禁止动作、历史记录） |
| GET | `/api/v1/blacklist/records` | 登录 | **封禁记录查询**（分页；本人=自己的记录；管理员=全部并可筛选） |
| GET | `/api/v1/blacklist` | 管理员 | 封禁记录列表（管理端简版，等价于 `/records`） |
| POST | `/api/v1/blacklist/ban` | 管理员 | 手动封禁（默认 3 天；已在封禁中默认顺延） |
| POST | `/api/v1/blacklist/release` | 管理员 | 手动解封（解禁时间提前到当前时间） |
| POST | `/api/v1/blacklist/release-expired` | 管理员 | 到期解封**留痕**批处理（拦截本身不依赖它） |
| POST | `/api/v1/blacklist/scan-absent` | 管理员 | 手动触发缺席判定兜底扫描 |
| GET | `/api/v1/blacklist/config` | 登录 | 查看当前生效的惩罚规则参数 |
| POST | `/api/v1/game/{game_id}/finish` | 登录·发起人 | **结束球局并触发缺席判定**（规则1 的主动入口） |

### 4.1 我的封禁状态 `GET /api/v1/blacklist/me`

**请求参数**：无

**响应示例（封禁中）**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "banned": true,
    "ban_end_time": "2026-11-21T18:15:57",
    "remaining_hours": 71.8,
    "ban_start_time": "2026-11-18T18:15:57",
    "ban_duration_days": 3,
    "ban_extend_count": 0,
    "reason": "缺席球局（未签到且未请假），球局ID=11",
    "reason_type": 1,
    "blocked_actions": [
      "发起球局（POST /api/v1/game）",
      "报名加入球局（POST /api/v1/game/{id}/signup）"
    ],
    "message": "您因放鸽子被禁赛，将于 2026-11-21 18:15 解除",
    "history": [
      {
        "id": 1,
        "user_id": 2,
        "ban_start_time": "2026-11-18T18:15:57",
        "ban_duration_days": 3,
        "ban_end_time": "2026-11-21T18:15:57",
        "status": 1,
        "reason_type": 1,
        "reason": "缺席球局（未签到且未请假），球局ID=11",
        "trigger_game_id": 11,
        "credit_score_at_ban": 90,
        "ban_extend_count": 0,
        "ban_original_end_time": null,
        "ban_last_extend_at": null,
        "is_active": true,
        "created_at": "2026-11-18T18:15:57"
      }
    ],
    "total_ban_count": 1
  }
}
```

**响应示例（未封禁）**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "banned": false,
    "ban_end_time": null,
    "remaining_hours": null,
    "ban_extend_count": 0,
    "blocked_actions": [],
    "message": "您当前没有封禁记录，可正常参与球局",
    "history": []
  }
}
```

### 4.2 封禁记录查询 `GET /api/v1/blacklist/records`

**请求参数（Query）**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| user_id | int | — | 按用户筛选，**仅管理员生效**；普通用户传了也会被忽略（防止越权） |
| only_active | bool | false | 只看仍在封禁期的记录（惰性判定 `ban_end_time > now`） |
| reason_type | int | — | 1-缺席未到 2-多次迟到累计 3-信誉分过低 4-管理员人工封禁 |
| include_released | bool | true | 是否包含已解封的历史记录（默认包含，体现「记录永久留存」） |
| page | int | 1 | 页码 |
| page_size | int | 20 | 每页条数，最大 100 |

**响应示例**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {
        "id": 2,
        "user_id": 2,
        "ban_start_time": "2026-11-18T18:15:57",
        "ban_duration_days": 6,
        "ban_end_time": "2026-11-24T18:15:57",
        "status": 1,
        "reason_type": 1,
        "reason": "缺席球局（未签到且未请假），球局ID=11；封禁期内再次缺席，已顺延 3 天",
        "trigger_game_id": 12,
        "credit_score_at_ban": 80,
        "ban_extend_count": 1,
        "ban_original_end_time": "2026-11-21T18:15:57",
        "ban_last_extend_at": "2026-11-18T18:20:10",
        "is_active": true
      },
      {
        "id": 1,
        "user_id": 2,
        "ban_start_time": "2026-11-01T10:00:00",
        "ban_duration_days": 3,
        "ban_end_time": "2026-11-04T10:00:00",
        "status": 0,
        "reason_type": 1,
        "reason": "缺席球局（未签到且未请假），球局ID=5",
        "released_at": "2026-11-04T10:00:00",
        "release_type": 1,
        "is_active": false
      }
    ],
    "total": 2,
    "page": 1,
    "page_size": 20,
    "pages": 1
  }
}
```

### 4.3 结束球局 `POST /api/v1/game/{game_id}/finish`

**鉴权**：登录 + 必须是该球局发起人（否则 `40300`）

**响应示例**

```json
{
  "code": 0,
  "message": "球局已结束，判定缺席 2 人",
  "data": {
    "game_id": 11,
    "status": 4,
    "absent_count": 2,
    "settled_users": [
      {
        "user_id": 2,
        "credit_before": 100,
        "credit_delta": -10,
        "credit_after": 90,
        "credit_level": 3,
        "settled_record_count": 1,
        "banned": true,
        "ban_extended": false,
        "ban_end_time": "2026-11-21T18:15:57",
        "details": [{ "checkin_record_id": 31, "game_id": 11, "checkin_status": 3, "credit_delta": -10 }],
        "ban": {
          "created": true,
          "extended_days": 0,
          "capped": false,
          "extend_count": 0,
          "ban_id": 1,
          "ban_start_time": "2026-11-18T18:15:57",
          "ban_end_time": "2026-11-21T18:15:57",
          "reason": "缺席球局（未签到且未请假），球局ID=11",
          "message": "您因放鸽子被禁赛，将于 2026-11-21 18:15 解除"
        }
      }
    ]
  }
}
```

> `ban.created=false` 表示本次是**顺延**（规则6）；`ban.extended_days` 为顺延天数。

### 4.4 手动封禁 `POST /api/v1/blacklist/ban`（管理员）

```json
// 请求
{ "user_id": 3, "days": 3, "reason_type": 4, "reason": "多次放鸽子" }

// 响应（首次封禁）
{
  "code": 0, "message": "已加入小黑屋",
  "data": { "ban": { "...": "..." }, "created": true, "extended_days": 0, "capped": false,
            "message": "您因放鸽子被禁赛，将于 2026-11-21 18:15 解除" }
}

// 响应（已在封禁中 → 顺延）
{ "code": 0, "message": "用户已在封禁中，已顺延 3 天",
  "data": { "created": false, "extended_days": 3, "capped": false } }
```

### 4.5 其它接口

```json
// 手动解封 POST /api/v1/blacklist/release
{ "ban_id": 1, "release_type": 2, "remark": "申诉通过" }
→ { "code": 0, "message": "已解封", "data": { "ban_id": 1, "released": true } }

// 到期解封留痕 POST /api/v1/blacklist/release-expired
→ { "code": 0, "message": "本次标记解封 1 条记录", "data": { "released_count": 1 } }

// 兜底扫描 POST /api/v1/blacklist/scan-absent
→ { "code": 0, "message": "扫描 1 场，判定缺席 2 人次",
    "data": { "scanned": 1, "absent_total": 2,
              "finalized": [{ "game_id": 11, "title": "忘记关闭的球局",
                              "end_time": "2026-11-18T16:00:00", "absent_count": 2, "settled_users": 2 }] } }

// 规则查询 GET /api/v1/blacklist/config
→ { "code": 0, "data": { "ban_days": 3, "absent_deduct_score": 10, "lazy_release": true,
                         "lazy_release_rule": "ban_end_time > NOW() 即视为封禁中……",
                         "extend_on_repeat": true, "max_total_days": 30, "block_all_writes": false,
                         "blocked_actions": ["发起球局（POST /api/v1/game）", "报名加入球局（POST /api/v1/game/{id}/signup）"] } }
```

---

## 五、代码集成方式（不重复写判断）

### 5.1 独立依赖 `get_current_active_user`

```python
# app/api/deps.py
CurrentActiveUser = Annotated[User, Depends(get_current_active_user)]

# 接口侧：只改依赖声明，不写任何拦截代码
@router.post("", response_model=ApiResponse[GameOut], summary="① 发起球局")
async def create_game(payload: GameCreateRequest, current_user: CurrentActiveUser, db: DbSession):
    ...
```

它复用了 JWT 认证中间件已经解析好的 `request.state.user_id`（不重复解析 Token），
并且与中间件钩子共用同一份拦截口径 `blacklist_service.is_ban_blocked_request()`。

### 5.2 双层防护

| 层 | 位置 | 作用 |
| --- | --- | --- |
| 中间件钩子 | `app/middleware/hooks.py::blacklist_hook` | **全局兜底**：任何路径都不会漏（新增接口无需配置） |
| 接口依赖 | `get_current_active_user` | **接口契约**：显式声明「本接口需要未被封禁的用户」，即使关闭中间件也拦得住 |

另提供更严格的 `RequireActiveUser`（无论方法/路径都校验封禁），供将来需要时使用。

### 5.3 定时任务

`app/main.py` 的 lifespan 启动两个后台任务：

| 任务 | 间隔 | 作用 |
| --- | --- | --- |
| `_absent_scan_loop` | `ABSENT_SCAN_INTERVAL_SECONDS`（3600s） | 漏判兜底（规则1） |
| `_release_loop` | 300s | 到期解封**留痕**（拦截本身是惰性的，规则4） |

---

## 六、配置项（`.env`）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BAN_DEFAULT_DAYS` | 3 | 封禁时长（天），规则2 固定 3 天 |
| `BAN_ON_ABSENT` | true | 缺席是否直接封禁 |
| `BAN_EXTEND_ON_REPEAT` | true | 封禁期内再次缺席是否顺延（规则6）；false 则新建记录 |
| `BAN_MAX_TOTAL_DAYS` | 30 | 顺延后总时长上限 |
| `BAN_BLOCK_ALL_WRITES` | false | true=拦截所有非查询请求（更严格） |
| `BLACKLIST_CACHE_TTL` | 60 | 封禁状态缓存秒数（写封禁/顺延/解封时主动失效） |
| `BLACKLIST_FAIL_OPEN` | true | 钩子查库异常时是否放行（安全优先改 false） |
| `ABSENT_SCAN_ENABLED` | true | 是否启用兜底扫描 |
| `ABSENT_SCAN_INTERVAL_SECONDS` | 3600 | 扫描间隔（秒） |
| `ABSENT_SCAN_BATCH_SIZE` | 50 | 单轮最多处理球局数 |
| `ABSENT_SCAN_GRACE_MINUTES` | 0 | 结束时间后宽限分钟数才判定 |

---

## 七、数据库变更（v1.1 → v1.2）

```bash
mysql -uroot -p campus_ball < sql/004_migration_v1_2.sql
```

| 变更 | 表 | 说明 |
| --- | --- | --- |
| `credit_score` → `reputation_score` | `t_user` | 信誉分字段更名（缺席 -10）。ORM 侧用 `synonym("reputation_score")` 保留 `credit_score` 兼容别名，接口同时返回两个字段，老前端不受影响 |
| `ban_extend_count` | `t_blacklist` | 顺延次数（规则6） |
| `ban_original_end_time` | `t_blacklist` | 首次解禁时间（顺延前留痕） |
| `ban_last_extend_at` | `t_blacklist` | 最近一次顺延时间 |
| 索引重命名 | `t_user` | `idx_user_credit_score` → `idx_user_reputation_score` |

---

## 八、前端对接建议（Vue3 + Element Plus）

```js
// 拦截提示：后端 message/msg 已是完整中文文案，直接展示
axios.interceptors.response.use(null, (error) => {
  const { code, msg, message, data } = error.response?.data || {}
  if (code === 403 && data?.banned) {
    ElMessageBox.alert(msg, '禁赛提示', {
      confirmButtonText: '我知道了',
      type: 'warning'
    })
    // 个人中心展示倒计时
    startCountdown(data.ban_end_time)
  }
  return Promise.reject(error)
})
```

**个人中心展示**：调用 `GET /api/v1/blacklist/me`，用 `banned` / `ban_end_time` / `remaining_hours` /
`blocked_actions`（提示用户封禁期间只能浏览和签到，不能发局报名）/ `history`（历史记录）渲染。

**响应式建议**：封禁提示卡片在手机端用 `el-alert`（全宽、字号 14px），桌面端用 `el-card` 悬浮在页面顶部；
倒计时数字用等宽字体，`<768px` 时改为「xx 小时后解禁」的短文案避免折行。
