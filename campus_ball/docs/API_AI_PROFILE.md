# AI 信誉画像模块 · 算法说明与接口文档

> 模块：`app/services/ai_profile.py`、`app/api/v1/ai.py`、`app/api/v1/user.py`（个人主页）
> 触发点：`app/services/reputation.py`（签到/核销/缺席）、`app/services/game.py`（主动退出）
> 版本：v1.3 　接口前缀：`/api/v1/ai`
> 数据库变更：`sql/005_migration_v1_3.sql`

---

## 一、模块定位

```
行为事实（数据库可查）        画像算法（双轨）              下游应用
┌────────────────────┐   ┌──────────────────────┐   ┌────────────────────┐
│ 签到 / 迟到 / 请假  │   │ 轨道A：DeepSeek      │   │ 个人主页：分数+标签 │
│ 缺席（放鸽子）      │──▶│ 轨道B：本地加权规则  │──▶│ 球局匹配：match_score│
│ 主动退出 / 临期退出 │   │ （自动降级）         │   │ 运营预警：score_gap │
└────────────────────┘   └──────────────────────┘   └────────────────────┘
        触发：签到 / 缺席 / 退出结算（惰性）
```

两条轨道输出结构完全一致，接口层不区分；响应里用 `source`（`deepseek`/`rule`）与
`degraded`（是否降级）标明来源，前端可据此提示「当前为本地规则评估」。

**核心工程约束**：没有 DeepSeek API Key、调用超时/限流/返回非法，都必须**照常返回画像**，
保证 Demo 与离线环境可完整运行。

---

## 二、本地加权规则算法（降级方案，也是确定性基线）

### 2.1 权重表（`app/core/constants.py::PROFILE_WEIGHTS`）

| 行为 | 权重 | 说明 |
| --- | --- | --- |
| 按时签到（到场） | **+2 / 次** | 到场是基本义务，给予稳定正向激励 |
| 迟到签到 | **-3 / 次** | 影响他人等待 |
| 已请假 | **0** | 提前告知是负责任行为，不惩罚（避免用户硬扛导致缺席） |
| 无故缺席（未签到未请假） | **-10 / 次** | ★放鸽子，大幅扣分，与惰性结算口径完全一致 |
| 主动退出（距开球 > 2h） | **-2 / 次** | ★少量扣分，影响可控 |
| 临近开球退出（≤ 2h） | **-4 / 次** | 组织者来不及补位，扣分略重 |

### 2.2 计算公式

```
画像分 = clamp(
      初始分 100
    + 2  × 按时签到次数
    - 3  × 迟到次数
    - 10 × 无故缺席次数
    - 2  × 主动退出次数
    - 4  × 临近开球退出次数
    + 守约加成（完成 ≥5 场 且 守约率 ≥95% 时 +3）
, 0, 150)
```

派生指标：

| 指标 | 定义 |
| --- | --- |
| 应到场次数 | 按时签到 + 迟到 + 缺席（请假不算，请假是负责任的提前告知） |
| 守约率 | 按时签到 / 应到场 |
| 缺席率 | 缺席 / 应到场 |
| 退出率 | 退出 / 累计报名 |

### 2.3 计算示例（可复算）

某用户：按时签到 3 次、迟到 1 次、缺席 2 次、主动退出 1 次、临期退出 1 次

| 项 | 次数 | 权重 | 小计 |
| --- | --- | --- | --- |
| 按时签到 | 3 | +2 | +6 |
| 迟到签到 | 1 | -3 | -3 |
| 已请假 | 0 | 0 | 0 |
| 无故缺席 | 2 | -10 | **-20** |
| 主动退出 | 1 | -2 | -2 |
| 临近开球退出(≤2h) | 1 | -4 | -4 |
| 守约加成 | — | — | 0（应到场 6 场，守约率 50%） |
| **合计** | | | **100 - 23 = 77** |

`breakdown` 字段会把这张表原样返回，前端可直接展示「分数怎么来的」。

### 2.4 标签与风险等级（规则版自然语言）

优先级：**缺席 > 退出 > 迟到 > 参与度 > 球技**

| 条件 | 标签 |
| --- | --- |
| 缺席 ≥3 次 或 缺席率 ≥30% | 频繁放鸽子 |
| 缺席 ≥1 次 | 有过缺席 |
| 缺席 = 0 | 从未缺席 |
| 临期退出 ≥2 次 | 常临期退局 |
| 主动退出 ≥3 次 或 退出率 ≥40% | 报名波动大 |
| 迟到 ≥2 次 或 迟到率 ≥30% | 习惯性迟到 |
| 到场 ≥10 / ≥3 / <3 次 | 球局常客 / 稳定参与 / 新人球友 |
| 球技 ≥4 级 / 信誉分 ≥120 | 高水平选手 / 信誉金牌 |

风险等级：`high`（缺席≥3 或信誉分 < 60）、`medium`（缺席≥1 或退出≥3 或信誉分 < 90）、其余 `low`。

---

## 三、DeepSeek 轨道（首选）

### 3.1 输入

把 `ProfileFeatures.to_dict()` 序列化为 JSON 作为 user message，包含：信誉分、球技、
按时签到/迟到/请假/缺席次数、累计报名、提前退出、临期退出、发起球局数、守约率/缺席率/迟到率/退出率。

### 3.2 输出约束（系统提示词）

```
score: 0-150 整数信誉分建议（100 为初始分；按时签到加分，无故缺席大幅扣分，主动退出小幅扣分）
risk_level: low / medium / high
tags: 3-5 个中文短标签
summary: 60 字以内中文总结
suggestions: 2-3 条中文建议
```

调用参数：`response_format={"type":"json_object"}`（强制 JSON）、`temperature=0.3`、`max_tokens=600`、
超时 `DEEPSEEK_TIMEOUT`（默认 15s）。

### 3.3 容错

任何异常（无 Key、超时、限流、HTTP 非 200、JSON 解析失败、字段缺失）都被捕获 → 自动走本地加权规则版，
仅记录 `warning` 日志，接口始终返回 `code=0`。

---

## 四、融合策略（两个分数怎么合成一个）

```
最终画像分 = 0.3 × AI建议分 + 0.7 × 本地加权分
约束：|最终画像分 - 本地加权分| ≤ 8 分（AI_SCORE_MAX_ADJUST）
```

**为什么要限幅，而不是直接采用大模型的分数？**

1. **业务规则必须稳定**：报名门槛、封禁阈值都依赖信誉分。如果模型偶发返回 150，
   用户会瞬间越过门槛；返回 0 又会被误封——这是不可接受的业务风险。
2. **本地加权分可审计**：它是「次数 × 权重」的确定性计算，任何用户都能被复算、解释、申诉。
   大模型是黑盒，不适合做最终裁决。
3. **发挥各自长处**：大模型擅长把行为特征**标签化 / 自然语言总结**，这部分直接采用；
   定分交给确定性算法，AI 只做**有限微调**。
4. **可对比**：响应同时返回 `rule_score`、`ai_score`、`ai_adjust`，运营可观察模型与规则的偏差，
   为后续调参提供数据。

降级时 `ai_score=null`、`ai_adjust=0`、`score=rule_score`，`source=rule`、`degraded=true`。

---

## 五、两个分数的分工（重要设计说明）

| 分数 | 字段 | 维护方式 | 用途 |
| --- | --- | --- | --- |
| **操作分** | `t_user.reputation_score` | 惰性结算（签到/核销 +2、迟到 -3、缺席 -10） | 报名门槛、封禁阈值、信誉等级 |
| **画像分** | `t_user.ai_score` + 画像 JSON 的 `score` | 本模块（规则/AI 融合） | 个人主页展示、球局匹配参考、运营预警 |

- 操作分是**业务事实**：只由「签到/缺席」这类确定事件驱动，绝不交给大模型；
- 画像分是**综合评估**：包含退出等更丰富的行为，用于展示与匹配排序；
- 响应里的 `score_gap = 画像分 - 操作分`，差异过大时可用于运营预警（例如模型或数据异常）。

---

## 六、惰性触发链路

```
签到 / 发起人核销 / 缺席判定 / 主动退出
        │  （全部经由 settle_user_pending 或 exit_game）
        ▼
① 同一事务内置 ai_profile_dirty = 1（记 trigger，如 checkin / absent / exit）
        │
        ├─▶ ② 立刻异步重算（asyncio 独立任务 + 独立会话，不阻塞接口响应；失败无妨）
        │
        ├─▶ ③ 后台循环每 AI_PROFILE_SCAN_INTERVAL_SECONDS(默认 600s) 扫 dirty=1 兜底重算
        │
        └─▶ ④ 用户打开画像接口 / 个人主页时，若 dirty=1 或缓存超期 → 当场重算（保证展示最新）
```

**三次机会保证最终一致**：即使异步任务与后台循环都没跑，用户查看时也会补算；
即使重算失败，`dirty` 标记仍在（不会丢失）。

实测（测试断言）：核销签到后 `dirty=1, trigger=checkin`，读取画像后 `dirty=0`、`version+1`、
`features.checked_count=1`、`score` 上升。

---

## 七、下游应用：球局匹配参考分（match_score）

球局列表对**登录用户**按画像实时计算（未登录返回静态基线 80.0）：

```
match_score = clamp(
      60                                 基础分
    + 20 × (画像分 / 150)                信誉匹配
    + 12 × max(0, 1 - 球技差距 / 5)      球技匹配（用户球技 vs 球局门槛）
    + 8  × 该球类历史占比                 球类偏好
    - 5  × (满员 ? 1 : 0)                满员降权
, 0, 100)
特例：与已报名球局时间冲突 → 0（理由：时间冲突）
      画像分 < 球局信誉门槛   → 0（理由：信誉分低于门槛）
```

响应同时返回 `match_reason`（如「信誉分 102、球技符合要求、常玩该球类」），前端可直接展示推荐理由。

---

## 八、接口文档

### 8.1 获取我的信誉画像 `GET /api/v1/ai/profile`

**请求参数**

| 参数 | 位置 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| force | query | bool | false | true=忽略缓存与 dirty 标记，强制重算 |

**响应示例（降级为本地加权规则版）**

```json
{
  "code": 0,
  "message": "画像已更新",
  "data": {
    "user_id": 2,
    "score": 77,
    "rule_score": 77,
    "ai_score": null,
    "ai_adjust": 0,
    "reputation_score": 77,
    "score_gap": 0,
    "credit_level": 2,
    "credit_level_text": "观察中",
    "risk_level": "medium",
    "tags": ["有过缺席", "稳定参与"],
    "summary": "累计到场 3 次、迟到 1 次、缺席 2 次、退出 1 次，守约率 50%",
    "suggestions": [
      "报名后请按时到场；确实来不了请提前请假，避免扣除信誉分并被禁赛。",
      "尽量不要在开球前 2 小时内退出，便于组织者补位。"
    ],
    "source": "rule",
    "degraded": true,
    "trigger": "absent",
    "version": 3,
    "cached": false,
    "generated_at": "2026-11-18T19:20:00",
    "features": {
      "checked_count": 3, "late_count": 1, "leave_count": 0, "absent_count": 2,
      "signup_total": 7, "cancel_early_count": 1, "cancel_late_count": 1,
      "keep_rate": 0.5, "absent_rate": 0.333, "late_rate": 0.167, "cancel_rate": 0.286
    },
    "breakdown": [
      { "item": "按时签到", "count": 3, "weight": 2, "subtotal": 6 },
      { "item": "迟到签到", "count": 1, "weight": -3, "subtotal": -3 },
      { "item": "已请假", "count": 0, "weight": 0, "subtotal": 0 },
      { "item": "无故缺席", "count": 2, "weight": -10, "subtotal": -20 },
      { "item": "主动退出", "count": 1, "weight": -2, "subtotal": -2 },
      { "item": "临近开球退出(≤2h)", "count": 1, "weight": -4, "subtotal": -4 }
    ]
  }
}
```

**响应示例（DeepSeek 可用时）**

```json
{
  "code": 0,
  "message": "画像已刷新",
  "data": {
    "score": 83,
    "rule_score": 77,
    "ai_score": 96,
    "ai_adjust": 6,
    "source": "deepseek",
    "degraded": false,
    "tags": ["守约意识提升中", "出勤波动", "夜场偏好"],
    "summary": "该用户近期出勤改善明显，但仍有两次缺席记录，建议保持稳定参与。",
    "suggestions": ["保持连续到场 5 场以上可显著提升信誉等级。"]
  }
}
```

> 融合计算：`0.3×96 + 0.7×77 = 82.7 → round = 83`，相对基线 `+6`（未超 ±8 限幅）；
> 若模型返回 150，则 `0.3×150 + 0.7×77 = 98.9`，基线调整 `+21.9` 会被限幅到 `+8`，
> 最终 `85` —— 这就是「AI 只做微调」的实际效果。

### 8.2 算法说明 `GET /api/v1/ai/explain`

返回权重表、公式、守约加成、融合参数、降级策略、匹配分构成、来源优先级。
前端可直接用于「分数怎么来的」弹窗，也便于向用户解释扣分规则。

### 8.3 强制刷新 `POST /api/v1/ai/profile/refresh`

请求体可选 `{"force": true}`；忽略缓存与 dirty 标记，重新生成画像。

### 8.4 批量重算 `POST /api/v1/ai/refresh-dirty`（管理员）

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| limit | query | 20 | 单轮最多重算多少个用户（≤200） |

响应：`{"scanned": 3, "refreshed": 3, "failed": []}`。
生产环境由后台任务每 10 分钟自动执行，本接口用于手动补偿。

### 8.5 运行状态 `GET /api/v1/ai/stats`

```json
{
  "llm_available": false,
  "llm_model": null,
  "enabled": true,
  "trigger_on_settle": true,
  "async_refresh": true,
  "scan_interval_seconds": 600,
  "cache_hours": 24,
  "dirty_count": 0,
  "profiled_users": 12,
  "source_distribution": { "deepseek": 9, "rule": 3 },
  "match_score_enabled": true
}
```

### 8.6 用户个人主页 `GET /api/v1/user/{user_id}/profile`

信誉分展示入口（不返回手机号、邮箱、学号等隐私字段）。

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "user_id": 2,
    "nickname": "球场小王子",
    "avatar_url": null,
    "campus": "老校区",
    "college": "计算机学院",
    "gender": 1,
    "skill_level": 4,
    "reputation_score": 102,
    "credit_score": 102,
    "credit_level": 3,
    "credit_level_text": "正常",
    "profile_score": 108,
    "tags": ["从未缺席", "稳定参与", "高水平选手"],
    "summary": "累计到场 5 次、迟到 0 次、缺席 0 次，守约率 100%。",
    "profile_source": "rule",
    "profile_degraded": true,
    "breakdown": [{ "item": "按时签到", "count": 5, "weight": 2, "subtotal": 10 }],
    "attended_count": 5,
    "late_count": 0,
    "absent_count": 0,
    "cancel_count": 0,
    "keep_rate": 1.0,
    "joined_game_count": 5,
    "created_game_count": 1,
    "banned": false,
    "ban_end_time": null,
    "registered_at": "2026-11-18T10:00:00",
    "is_self": false
  }
}
```

> `ban_end_time` 仅本人可见（`is_self=true`），保护隐私。

---

## 九、配置项（`.env`）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `AI_ENABLED` | true | 画像模块总开关 |
| `DEEPSEEK_API_KEY` | 空 | 留空 → 直接走本地加权规则版 |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` / `DEEPSEEK_TIMEOUT` | 官方地址 / `deepseek-chat` / 15s | 大模型参数 |
| `AI_PROFILE_TRIGGER_ON_SETTLE` | true | 结算后是否触发画像重算 |
| `AI_PROFILE_ASYNC_REFRESH` | true | 是否结算后立刻异步重算（false 则等后台循环） |
| `AI_PROFILE_CACHE_HOURS` | 24 | 画像缓存有效期 |
| `AI_PROFILE_SCAN_INTERVAL_SECONDS` | 600 | 后台兜底重算间隔 |
| `AI_PROFILE_SCAN_BATCH_SIZE` | 20 | 单轮最多重算用户数 |
| `AI_MATCH_SCORE_ENABLED` | true | 球局匹配分是否按画像计算 |

---

## 十、数据库变更（v1.2 → v1.3）

```bash
mysql -uroot -p campus_ball < sql/005_migration_v1_3.sql
```

| 字段 | 说明 |
| --- | --- |
| `t_user.ai_score` | 画像评估分（0-150），个人主页展示 + 匹配参考 |
| `t_user.ai_profile_source` | 画像来源：`deepseek` / `rule` |
| `t_user.ai_profile_dirty` | 待重算标记（+ 索引 `idx_user_ai_profile_dirty`） |
| `t_user.ai_profile_trigger` | 最近一次重算原因 |
| `t_user.ai_profile_version` | 画像版本号（每次重算 +1，便于缓存与审计） |

---

## 十一、前端展示建议（Vue3 + Element Plus）

```vue
<!-- 个人主页：信誉分卡片（手机端单列 / 桌面端与标签并排） -->
<el-card class="reputation-card">
  <div class="score">{{ profile.reputation_score }}</div>
  <el-tag :type="levelType(profile.credit_level)">{{ profile.credit_level_text }}</el-tag>
  <el-tag v-for="t in profile.tags" :key="t" :type="t.includes('鸽子') || t.includes('缺席') ? 'danger' : 'success'">
    {{ t }}
  </el-tag>
  <el-collapse v-if="!isMobile">
    <el-collapse-item title="分数怎么来的">
      <el-table :data="profile.breakdown">
        <el-table-column prop="item" label="行为" />
        <el-table-column prop="count" label="次数" width="70" />
        <el-table-column prop="weight" label="权重" width="70" />
        <el-table-column prop="subtotal" label="小计" width="80" />
      </el-table>
    </el-collapse-item>
  </el-collapse>
  <el-alert v-if="profile.profile_degraded" type="info" :closable="false"
            title="当前为本地加权规则评估（未启用大模型）" />
</el-card>
```

**响应式建议**：`<768px` 时信誉分卡片改为横向紧凑布局（分数 32px、标签换行）；
`768~992px` 两列；`>992px` 分数 + 标签 + 加权明细表格三栏。球局列表在手机端把
`match_score` 显示为「推荐指数」星级（`Math.round(match_score/20)` 星），点击展示 `match_reason`。
