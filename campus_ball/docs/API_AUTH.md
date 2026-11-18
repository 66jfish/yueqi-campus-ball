# 用户认证模块 · 接口文档

> 模块：`app/api/v1/auth.py` + `app/services/auth.py` + `app/core/security.py` + `app/middleware/auth.py`
> 版本：v1.0 　接口前缀：`/api/v1/auth`
> 在线调试：启动后访问 `http://127.0.0.1:8000/docs`（Swagger UI，可直接试跑）

---

## 一、设计要点

| 项 | 方案 |
| --- | --- |
| 密码存储 | **bcrypt**（cost=12，自带随机盐），库里存 `$2b$12$...`；明文不落库、不写日志 |
| 历史密码兼容 | 兼容旧 `pbkdf2_sha256$...` 哈希，**登录成功后自动升级为 bcrypt**，用户无感 |
| 令牌方案 | JWT 双令牌：`access_token`（默认 7 天）+ `refresh_token`（默认 30 天） |
| 令牌载荷 | `sub`(用户ID) / `iat` / `exp` / `jti` / `type`(access\|refresh) / `iss` / `aud` |
| 鉴权位置 | **认证中间件统一前置**（`app/middleware/auth.py`），注册在路由之前 |
| 接口复用 | 需要登录的接口只需声明 `current_user: CurrentUser`，无需再写鉴权代码 |
| 统一拦截 | 认证钩子链：账号状态 → **小黑屋**（后续可任意扩展，见第五节） |
| 响应格式 | 全站统一 `{"code": int, "message": str, "data": any}` |
| 超长密码 | 超过 bcrypt 的 72 字节上限时先做 SHA-256 摘要（不截断、不丢熵） |

### 鉴权流程图

```
客户端请求
   │
   ▼
[CORS 中间件]
   │
   ▼
[AuthMiddleware]  ← 路由前置，所有 /api/v1/* 先经过这里
   ├─ 路径在 PUBLIC 白名单？        → 直接放行（登录/注册/刷新/文档/健康检查）
   ├─ 无 Token？
   │     ├─ OPTIONAL 路径（如球局浏览） → 匿名放行
   │     └─ 其余路径                  → 401 + code=40100
   ├─ 解析 JWT（签名/过期/签发方/受众/类型）
   │     └─ 失败 → 401 + code=40101（过期）/ 40102（非法）
   ├─ 写入 request.state.user_id / token_payload
   ├─ 执行认证钩子链
   │     ├─ account_status_hook → 账号被禁用：401/403 + code=40103
   │     └─ blacklist_hook      → 小黑屋禁赛中：403 + code=40301
   │            （白名单：/api/v1/blacklist/me、/api/v1/user/me*）
   ▼
[接口]  需要登录则声明 current_user: CurrentUser（直接复用上面解析结果，不重复校验）
```

---

## 二、统一响应与错误码

### 成功

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

### 失败

```json
{
  "code": 40102,
  "message": "登录凭证无效，请重新登录",
  "data": null
}
```

| code | HTTP | 含义 | 前端建议动作 |
| --- | --- | --- | --- |
| 0 | 200 | 成功 | 正常处理 |
| 40000 | 400 / 422 | 参数错误（消息内含具体字段） | 表单标红提示 |
| 40100 | 401 | 未登录 / 缺少访问令牌 | 跳转登录页 |
| 40101 | 401 | 令牌已过期 | 先调 `/auth/refresh`，失败再跳登录页 |
| 40102 | 401 | 令牌非法（篡改、签名错误、类型不符） | 清除本地令牌，跳登录页 |
| 40103 | 403 | 账号被管理员禁用 | 提示联系管理员 |
| 40301 | 403 | 小黑屋禁赛中 | 展示解封时间倒计时（`data.ban_end_time`） |
| 40400 | 404 | 资源不存在 | 提示 |
| 40900 | 409 | 冲突（学号已注册等） | 提示 |
| 50000 | 500 | 服务端错误 | 提示稍后重试 |

令牌相关错误响应头统一带 `WWW-Authenticate: Bearer`。

---

## 三、接口详情

### 3.1 用户注册

`POST /api/v1/auth/register`　无需认证

**请求参数（JSON Body）**

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| student_no | string | 是 | 3-32 位 | 学号，全站唯一 |
| nickname | string | 是 | 1-32 位 | 昵称 |
| password | string | 是 | 6-64 位 | 密码，**bcrypt 加密存储** |
| real_name | string | 否 | ≤32 | 真实姓名 |
| phone | string | 否 | ≤20 | 手机号（唯一，可作登录账号） |
| campus | string | 否 | ≤64 | 校区 |
| college | string | 否 | ≤64 | 学院 |
| grade | string | 否 | ≤16 | 年级 |
| gender | int | 否 | 0/1/2 | 0-未知 1-男 2-女，默认 0 |
| skill_level | int | 否 | 1-5 | 球技水平，默认 1 |

**请求示例**

```json
{
  "student_no": "20230001",
  "nickname": "球场小王子",
  "password": "abc123456",
  "real_name": "张三",
  "phone": "13800000001",
  "campus": "东校区",
  "college": "计算机学院",
  "grade": "2023",
  "gender": 1,
  "skill_level": 3
}
```

**成功响应 200**

```json
{
  "code": 0,
  "message": "注册成功",
  "data": {
    "id": 1,
    "student_no": "20230001",
    "nickname": "球场小王子",
    "avatar_url": null,
    "campus": "东校区",
    "college": "计算机学院",
    "gender": 1,
    "skill_level": 3,
    "credit_score": 100,
    "credit_level": 3,
    "created_at": "2026-11-18T10:00:00"
  }
}
```

**失败响应**

```json
// 409 学号/手机号重复
{ "code": 40900, "message": "该学号或手机号已注册", "data": null }

// 422 参数不合法
{
  "code": 40000,
  "message": "参数错误：password String should have at least 6 characters",
  "data": [ { "loc": ["body", "password"], "msg": "String should have at least 6 characters" } ]
}
```

---

### 3.2 用户登录（JWT 签发）

`POST /api/v1/auth/login`　无需认证

**请求参数**

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| account | string | 是 | 3-64 位 | 学号 **或** 手机号 |
| password | string | 是 | 6-64 位 | 密码 |

**请求示例**

```json
{ "account": "20230001", "password": "abc123456" }
```

**成功响应 200**

```json
{
  "code": 0,
  "message": "登录成功",
  "data": {
    "token": {
      "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwidHlwZSI6ImFjY2Vzcy...",
      "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwidHlwZSI6InJlZnJlc2gi...",
      "token_type": "bearer",
      "expires_in": 604800
    },
    "user": {
      "id": 1,
      "student_no": "20230001",
      "nickname": "球场小王子",
      "avatar_url": null,
      "campus": "东校区",
      "college": "计算机学院",
      "gender": 1,
      "skill_level": 3,
      "credit_score": 100,
      "credit_level": 3,
      "created_at": "2026-11-18T10:00:00"
    }
  }
}
```

**失败响应**

```json
// 400 账号或密码错误（不区分「账号不存在」与「密码错误」，防账号探测）
{ "code": 40000, "message": "账号或密码错误", "data": null }

// 403 账号被禁用
{ "code": 40103, "message": "账号已被禁用，请联系管理员", "data": null }
```

**JWT 载荷示例（解码后）**

```json
{
  "sub": "1",
  "iat": 1763431200,
  "exp": 1764036000,
  "jti": "a1b2c3d4e5f60718",
  "type": "access",
  "iss": "campus-ball",
  "aud": "campus-ball-client",
  "student_no": "20230001",
  "nickname": "球场小王子",
  "credit_level": 3
}
```

**后续请求携带方式（三种任选其一）**

```
Authorization: Bearer <access_token>     ← 推荐
Cookie: access_token=<access_token>
X-Access-Token: <access_token>           ← 小程序/第三方客户端
```

---

### 3.3 刷新访问令牌

`POST /api/v1/auth/refresh`　无需认证（但需携带**有效**的 refresh_token）

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| refresh_token | string | 是 | 登录返回的 refresh_token |

**请求示例**

```json
{ "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." }
```

**成功响应 200**（refresh_token 一并轮换）

```json
{
  "code": 0,
  "message": "刷新成功",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.new",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.newrefresh",
    "token_type": "bearer",
    "expires_in": 604800
  }
}
```

**失败响应**

```json
// 401 refresh_token 过期
{ "code": 40101, "message": "登录已过期，请重新登录", "data": null }

// 401 把 access_token 当 refresh_token 用（type 校验拦截）
{ "code": 40102, "message": "登录凭证类型不正确", "data": null }
```

---

### 3.4 退出登录

`POST /api/v1/auth/logout`　登录可选（未登录调用也返回成功，幂等）

**请求参数**：无（令牌从请求头读取）

**成功响应 200**

```json
{
  "code": 0,
  "message": "已退出登录",
  "data": {
    "logout": true,
    "user_id": 1,
    "note": "请前端清除本地保存的 access_token / refresh_token"
  }
}
```

> 当前为无状态实现（客户端丢弃令牌即可）。接口已记录 `jti` 与剩余有效期，
> 后续接入 Redis 后可把 `jti` 写入黑名单，实现「登出即失效」与「管理员强制下线」。

---

### 3.5 查看当前令牌信息

`GET /api/v1/auth/token-info`　**需要认证**

**请求参数**：无

**成功响应 200**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "user_id": "1",
    "jti": "a1b2c3d4e5f60718",
    "type": "access",
    "expires_in": 604230,
    "expires_at": "2026-11-25T10:00:00+08:00",
    "need_refresh": false
  }
}
```

> `need_refresh=true` 表示剩余有效期不足 30 分钟，前端可静默调用 `/auth/refresh` 续期。

---

### 3.6 使用令牌访问业务接口（复用示例）

```bash
# 1) 登录拿令牌
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"account":"20230001","password":"abc123456"}'

# 2) 带令牌访问需要登录的接口（无需任何额外鉴权代码）
curl http://127.0.0.1:8000/api/v1/user/me \
  -H "Authorization: Bearer <access_token>"
```

未带令牌访问的响应：

```json
{ "code": 40100, "message": "未登录或缺少访问令牌，请先登录", "data": null }
```

被小黑屋拦截的响应（403）：

```json
{
  "code": 40301,
  "message": "您已被限制参与球局（禁赛 3 天），预计 2026-11-21 20:00 解封",
  "data": {
    "ban_end_time": "2026-11-21T20:00:00",
    "ban_duration_days": 3,
    "reason": "信誉分 52 低于阈值 60"
  }
}
```

---

## 四、路径鉴权策略（三档）

在 `app/middleware/auth.py` 顶部集中配置，改一处即全局生效：

| 档位 | 配置项 | 当前包含 | 行为 |
| --- | --- | --- | --- |
| 公开 | `PUBLIC_PATHS` / `PUBLIC_PREFIXES` | `/`、`/docs`、`/redoc`、`/openapi.json`、`/health`、`/api/v1/auth/login`、`/register`、`/refresh` | 不解析令牌、不执行钩子 |
| 可选登录 | `OPTIONAL_PREFIXES` | `/api/v1/game`（球局浏览）、`/api/v1/auth/logout` | 有令牌则解析并执行钩子；无令牌匿名放行 |
| 必须登录 | 其余全部 | `/api/v1/user/*`、`/api/v1/checkin/*`、`/api/v1/ai/*`、`/api/v1/blacklist/*` | 缺令牌 → 401 |

> 新增公开接口时，**只需把路径加进 `PUBLIC_PREFIXES`**，不用在每个接口里写鉴权开关。

---

## 五、小黑屋拦截钩子（统一拦截，不重复写）

### 5.1 为什么用钩子

后续必然还有别的全局规则（账号封禁、强制改密、异地登录、设备封禁、接口限流……
如果每个接口都写一遍判断，漏一处就是漏洞。因此把它们统一收敛到
`app/middleware/hooks.py` 的钩子链中，在认证中间件里执行。

### 5.2 内置钩子

| 钩子 | 作用 | 拦截时返回 |
| --- | --- | --- |
| `account_status` | 账号不存在/已注销/被禁用 | 40100 / 40103 |
| `blacklist` | **小黑屋禁赛中统一拦截** | 403 + code=40301（含解封时间） |

小黑屋判定条件（查询侧自动忽略到期记录，即到期自动解封）：

```sql
SELECT * FROM t_blacklist
WHERE user_id = ? AND status = 1 AND ban_end_time > NOW()
ORDER BY ban_end_time DESC LIMIT 1;
```

白名单（被禁赛仍可访问）：`/api/v1/blacklist/me`、`/api/v1/user/me*`
——保证用户能看到「自己为什么被封、什么时候解封」。

> **缓存与生效时机**：钩子查询结果带 60 秒内存缓存（`BLACKLIST_CACHE_TTL`）以降载。
> `ban_user()` / `release_ban()` / `release_expired_bans()` 写库时会主动失效缓存，
> 因此走服务层封禁后**下一个请求立即生效**；封禁信息（时长、原因）也会一并缓存，
> 保证「命中缓存」与「回源查询」两种情况下接口返回内容完全一致。
> 多进程/多实例部署时各进程缓存独立，若需要强一致请把 `_BanCache` 换成 Redis（接口不变）。

### 5.3 新增一个钩子（三行）

```python
# app/middleware/hooks.py
from app.core.exceptions import BizException

async def need_password_change_hook(request: Request, user_id: int) -> None:
    async with SESSION_SCOPE_FACTORY() as db:
        if await is_password_expired(db, user_id):
            raise BizException("密码已过期，请先修改密码", code=40302)

register_auth_hook("password_expire", need_password_change_hook)   # 注册即生效
```

钩子的执行顺序 = 注册顺序；任一步骤抛异常都会立即中断请求并返回统一响应。
钩子内部异常默认放行（`BLACKLIST_FAIL_OPEN=true`），若安全优先可改为 `false`。

---

## 六、前端对接建议（Vue3 + Element Plus）

```js
// axios 统一拦截：自动带令牌 + 统一错误处理
axios.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

axios.interceptors.response.use(
  (resp) => {
    const { code, message, data } = resp.data
    if (code === 0) return data
    ElMessage.error(message)
    return Promise.reject(new Error(message))
  },
  async (error) => {
    const { code, message, data } = error.response?.data || {}
    if (code === 40101) {                      // 令牌过期 → 静默续期
      try {
        const t = await refreshToken()
        error.config.headers.Authorization = `Bearer ${t.access_token}`
        return axios.request(error.config)
      } catch { /* 续期失败 → 跳登录页 */ }
    }
    if (code === 40301) ElMessage.warning(`${message}`)   // 小黑屋：展示解封倒计时
    else if (code !== 0) ElMessage.error(message)
    return Promise.reject(error)
  }
)
```

**响应式适配建议**：登录/注册页用 `el-form` + `:label-position="isMobile ? 'top' : 'right'"`，
容器宽度 `min(420px, 92vw)`；Element Plus 断点：`<768px` 手机、`768~992px` 平板、`>992px` 桌面。

---

## 七、配置项（`.env`）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BCRYPT_ROUNDS` | 12 | bcrypt cost，越高越安全、登录越慢 |
| `JWT_SECRET_KEY` | dev 占位值 | **生产必须替换**：`python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `JWT_ALGORITHM` | HS256 | 签名算法 |
| `JWT_ISSUER` / `JWT_AUDIENCE` | campus-ball / campus-ball-client | 签发方与受众（留空则不校验） |
| `JWT_LEEWAY_SECONDS` | 30 | 允许的时钟偏差 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 10080 | 访问令牌有效期（7 天） |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | 43200 | 刷新令牌有效期（30 天） |
| `AUTH_ENABLED` | true | 认证中间件总开关（单测可关） |
| `AUTH_OPTIONAL_IGNORE_INVALID` | true | 可选登录路径上「坏令牌」是否按匿名放行 |
| `BLACKLIST_FAIL_OPEN` | true | 钩子查库异常时是否放行（安全优先改 false） |
