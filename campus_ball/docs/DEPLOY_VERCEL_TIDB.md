# 部署文档：Vercel（前后端双项目）+ TiDB Cloud Serverless

> 目标架构：
> ```
> GitHub 仓库（monorepo：campus_ball/ 后端 + frontend/ 前端）
>        │  push 触发自动部署
>        ├──▶ Vercel 项目 A：后端 Serverless（FastAPI + Mangum）→ 提供 /api/v1/*
>        └──▶ Vercel 项目 B：前端静态站点（Vue3 + Vite）→ 用户访问入口
>                        │
>                        └──▶ TiDB Cloud Serverless（MySQL 兼容，强制 TLS）
> ```

---

## 一、项目结构（monorepo 两个目录）

```
仓库根/
├── campus_ball/          # 后端（Vercel 项目 A 的 Root Directory）
│   ├── api/index.py      # ★ Serverless 入口（Mangum 包装 FastAPI）
│   ├── vercel.json       # ★ 构建配置 + Cron 定时任务
│   ├── requirements.txt  # 依赖（Vercel Python 从 Root Directory 读取）
│   ├── app/              # 业务代码
│   ├── sql/              # MySQL 版建表脚本
│   ├── sql/tidb/         # ★ TiDB 专用版建表脚本（已按 TiDB 限制改写）
│   ├── tests/            # pytest 测试（110 个）
│   └── docs/             # 接口文档（/docs 在线可看）
└── frontend/             # 前端（Vercel 项目 B 的 Root Directory）
    ├── vercel.json
    ├── .env.production   # ★ 只需改 VITE_API_BASE_URL
    └── src/…
```

---

## 二、Step 1：TiDB Cloud Serverless 建库

1. 登录 <https://tidbcloud.com> → **Create Cluster** → 选 **Serverless** → 区域选离用户最近的（如 AWS 东京 / 新加坡）
2. 创建后进入 **Clusters → Connect**，记录：
   - `Host`：形如 `gateway01.ap-northeast-1.prod.aws.tidbcloud.com`
   - `Port`：`4000`
   - `User`：形如 `3xxxxxx.root`
   - `Password`：点 **Generate Password** 生成
3. 在 **SQL Editor** 中执行建表脚本（**必须用 TiDB 版**）：

```sql
-- 方式一：控制台 SQL Editor，按顺序粘贴执行
--   1) campus_ball/sql/tidb/001_schema.sql     建 5 张表
--   2) campus_ball/sql/tidb/002_init_data.sql  演示数据（3 个账号，密码均为 123456）
--   3) 如果是从旧库升级，再依次执行 003/004/005

-- 方式二：本地 mysql 客户端
mysql --host <Host> --port 4000 --user <User> -p --ssl-mode=REQUIRED \
      -e "CREATE DATABASE IF NOT EXISTS campus_ball DEFAULT CHARACTER SET utf8mb4;"
mysql --host <Host> --port 4000 --user <User> -p --ssl-mode=REQUIRED campus_ball \
      < campus_ball/sql/tidb/001_schema.sql
mysql --host <Host> --port 4000 --user <User> -p --ssl-mode=REQUIRED campus_ball \
      < campus_ball/sql/tidb/002_init_data.sql
```

> **为什么需要 TiDB 专用 SQL**（与 `sql/*.sql` 的 MySQL 版的差异，均为 TiDB 语法限制）：
>
> | # | MySQL 版写法 | TiDB 的行为 | TiDB 版的处理 |
> | --- | --- | --- | --- |
> | 1 | 一条 `ALTER TABLE` 里 `ADD COLUMN a, ADD COLUMN b, ADD COLUMN c` | ❌ 报 `Unsupported multi schema change` | 拆成多条 `ALTER TABLE`，一条只做一个操作 |
> | 2 | `ADD COLUMN ... AFTER col` | ⚠️ 位置子句支持有限 | 去掉 `AFTER`（不影响业务语义） |
> | 3 | `RENAME INDEX a TO b` | ⚠️ 支持有限 | 改为 `DROP INDEX` + `ADD INDEX` |
> | 4 | `CREATE DATABASE` / `USE` | ⚠️ Serverless 无库级权限 | 去掉，数据库在控制台创建、连接串指定库名 |
> | 5 | `DELIMITER $$ ... CREATE PROCEDURE` | ❌ 客户端不支持 `DELIMITER` | 去掉存储过程（改用应用层幂等） |
>
> 校验方式见第七节（`tmp/tidb_check2.py` 的规则 + sqlglot MySQL 方言解析）。

---

## 三、Step 2：推到 GitHub

```bash
cd <仓库根>                       # 内含 campus_ball/ 与 frontend/
git init
git add .
git commit -m "feat: 搭子月球 搭子月球（FastAPI + TiDB + Vue3）"
git branch -M main
git remote add origin https://github.com/<你的账号>/<仓库名>.git
git push -u origin main
```

> ⚠️ `.env`、`node_modules/`、`dist/`、`__pycache__/` 已在 `.gitignore` 中，不会被提交（里面有数据库密码与 JWT 密钥）。
> 若仓库根目录不在 `campus_ball` 与 `frontend` 的上层，请自行调整下面两个项目的 **Root Directory**。

---

## 四、Step 3：Vercel 项目 A（后端）

1. Vercel 控制台 → **Add New… → Project** → 选中刚推的仓库
2. **Configure Project** 页面按下面填写：

| 配置项 | 值 |
| --- | --- |
| **Root Directory** | `campus_ball`（点 Edit 选择） |
| Framework Preset | Other |
| Build Command | 留空（`vercel.json` 里用 `@vercel/python` 构建） |
| Output Directory | 留空 |
| Install Command | 留空（自动 `pip install -r requirements.txt`） |

3. 这个项目**不需要额外构建命令**：`vercel.json` 已声明
   `builds: [{ "src": "api/index.py", "use": "@vercel/python" }]`，
   所有路径都转发到 `api/index.py`（里面的 `handler = Mangum(app)` 处理 ASGI 请求）。
4. **环境变量**（见第六节清单）→ **Deploy**
5. 部署完成得到后端域名，如 `https://maoqiu-api.vercel.app`：
   - 接口文档：`https://maoqiu-api.vercel.app/docs`（Swagger）
   - 备用文档：`https://maoqiu-api.vercel.app/redoc`
   - 健康检查：`https://maoqiu-api.vercel.app/health`
   - 运行时信息：`https://maoqiu-api.vercel.app/api/v1/system/runtime`

---

## 五、Step 4：Vercel 项目 B（前端）

1. **Add New… → Project** → 同一个仓库 → Root Directory 选 `frontend`
2. Framework Preset：**Vite**（自动识别）→ Build Command `npm run build` → Output Directory `dist`
3. **环境变量**（只需 4 个，见第六节）→ **Deploy**
4. 得到前端域名，如 `https://maoqiu.vercel.app`

### ★ 关键一步：把前端域名加进后端 CORS

后端 Vercel 项目 → Settings → Environment Variables → 修改 `CORS_ORIGINS`：

```
CORS_ORIGINS=https://maoqiu.vercel.app,http://localhost:5173
```

改完 **Redeploy 后端**。否则浏览器会拦掉跨域请求（报 CORS policy 错误）。
后端 `main.py` 已把 `settings.cors_origin_list` 直接喂给 `CORSMiddleware`（支持逗号分隔多域名）。

---

## 六、环境变量清单（含 Vercel 后台填写位置）

**填写位置**：Vercel 控制台 → 选中项目 → **Settings → Environment Variables → Add New**
（每个变量都勾选 **Production** 与 **Preview**，改完必须 **Redeploy** 才生效）

### 6.1 后端项目（campus_ball）— 必填

| 变量名 | 示例 | 说明 |
| --- | --- | --- |
| `SERVERLESS_MODE` | `true` | 关闭进程内定时任务、启用 NullPool |
| `DB_HOST` | `gateway01.ap-northeast-1.prod.aws.tidbcloud.com` | TiDB Cloud 控制台 → Connect |
| `DB_PORT` | `4000` | TiDB Cloud 固定 4000 |
| `DB_USER` | `3xxxxxx.root` | 控制台 Connect 里复制 |
| `DB_PASSWORD` | `xxxxxxxx` | 控制台 Generate Password |
| `DB_NAME` | `campus_ball` | 控制台创建的库名 |
| `DB_REQUIRE_SSL` | `true` | TiDB Cloud 强制 TLS |
| `DB_USE_NULL_POOL` | `true` | Serverless 建议开 |
| **`JWT_SECRET_KEY`** | 48 位随机串 | 生成：`python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| **`CORS_ORIGINS`** | `https://maoqiu.vercel.app` | ★ 前端域名，逗号分隔 |
| **`CRON_SECRET`** | 32 位随机串 | 定时任务凭证（Vercel Cron 自动以 Bearer 发送） |

### 6.2 后端项目 — 选填

| 变量名 | 默认 | 说明 |
| --- | --- | --- |
| `ENV` | `prod` | 环境标识（影响错误响应是否暴露堆栈） |
| `DEBUG` | `false` | 生产务必 false |
| `DEEPSEEK_API_KEY` | 空 | 留空 → AI 画像自动降级本地加权规则版，功能不受影响 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `AI_ENABLED` | `true` | 画像模块总开关 |
| `BCRYPT_ROUNDS` | `12` | 密码哈希强度 |
| `BAN_DEFAULT_DAYS` | `3` | 禁赛天数 |
| `CREDIT_BAN_THRESHOLD` | `60` | 信誉分封禁阈值 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` | Access Token 有效期（7 天） |
| `BLACKLIST_CACHE_TTL` | `60` | 小黑屋缓存秒数 |

### 6.3 前端项目（frontend）— 必填

| 变量名 | 示例 | 说明 |
| --- | --- | --- |
| **`VITE_API_BASE_URL`** | `https://maoqiu-api.vercel.app/api/v1` | ★ 必须带 `/api/v1`，结尾不加 `/` |
| **`VITE_USE_MOCK`** | `false` | 生产必须 false（true 会走内置假数据） |

### 6.4 前端项目 — 选填

| 变量名 | 默认 | 说明 |
| --- | --- | --- |
| `VITE_API_TIMEOUT` | `15000` | 请求超时（毫秒） |
| `VITE_APP_TITLE` | `搭子月球 · 搭子月球` | 浏览器标题 |

> ⚠️ **不要把 `JWT_SECRET_KEY`、DB 密码放到前端项目**——Vite 会把 `VITE_*` 变量打进 JS 产物，等于公开密钥。
> ⚠️ Vite 变量是**构建期注入**，改完必须 Redeploy，且需清一次浏览器缓存。

---

## 七、定时任务与惰性判断（对应需求第 3 条）

### 7.1 结论：Vercel 上「每小时」配不了，改为「惰性为主 + 每日 Cron 兜底」

| 事实 | 说明 |
| --- | --- |
| Vercel Hobby（免费） | Cron Job **每个项目 1 个任务，最小频率为每天一次**（`0 3 * * *`） |
| Vercel Pro | 支持 `0 * * * *`（每小时），本项目只需把 `vercel.json` 的 schedule 改掉即可 |
| Serverless 进程内 asyncio 循环 | ❌ 不生效（函数执行完容器就冻结），因此 `SERVERLESS_MODE=true` 时框架会**关闭**它们 |

**因此本项目采用「惰性判断为主」的三处设计**（正确性完全不依赖定时任务）：

| 场景 | 惰性实现 | 代码位置 |
| --- | --- | --- |
| 小黑屋是否仍在封禁 | 查询条件写死 `ban_end_time > NOW()`，**过期即自动失效**；不读 `status` 字段 | `services/blacklist.py::get_active_ban` |
| 球局漏判缺席 | 读取球局详情/列表时，若「已过结束时间且未结算」→ **就地补判缺席**（幂等） | `services/game.py::maybe_finalize_overdue` |
| AI 画像重算 | 读取画像/个人主页时按 `ai_profile_dirty` 标记**按需重算**；大模型不可用自动降级 | `api/v1/ai.py::_resolve_profile` |

**定时任务（兜底加速，能配就配）**：`vercel.json` 已配 1 条每日任务，
一次完成「漏判扫描 + 到期解封留痕 + 画像批量重算」：

```json
"crons": [{ "path": "/api/v1/system/cron/daily", "schedule": "0 3 * * *" }]
```

- 鉴权：配好 `CRON_SECRET` 后，Vercel Cron 会自动带 `Authorization: Bearer <CRON_SECRET>`；
  未配置则接口一律拒绝（安全默认）
- 手工触发：`curl -H "Authorization: Bearer $CRON_SECRET" https://<后端域名>/api/v1/system/cron/daily`
- **即使把 Cron 整段删掉也不影响正确性**：只是「被动等用户访问」触发惰性判断

---

## 八、部署后自检清单

```bash
# 1. 健康检查（含数据库连通性）
curl https://<后端域名>/health
# 期望：{"code":0,"data":{"status":"ok","database":true,...}}

# 2. 运行时信息（确认 Serverless 形态与惰性策略生效）
curl https://<后端域名>/api/v1/system/runtime

# 3. 接口文档可访问
open https://<后端域名>/docs

# 4. 用演示账号登录（拿到 token 后调一个需登录接口）
curl -X POST https://<后端域名>/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"account":"20230001","password":"123456"}'

# 5. 跨域自检：在浏览器控制台执行（应无 CORS 报错）
fetch('https://<后端域名>/api/v1/game?page_size=1').then(r => r.json()).then(console.log)

# 6. 定时任务手工触发
curl -H "Authorization: Bearer $CRON_SECRET" https://<后端域名>/api/v1/system/cron/daily
```

前端自检：打开前端域名 → 首页应显示球局列表（若为空，说明库里还没有数据或 CORS 未配好）。

---

## 九、常见问题

| 现象 | 原因与处理 |
| --- | --- |
| `/health` 返回 `database:false` | 环境变量没填对：`DB_HOST/USER/PASSWORD/NAME`；TiDB 必须 `DB_REQUIRE_SSL=true` |
| 前端报 CORS policy | 后端 `CORS_ORIGINS` 没加前端域名，改完要 **Redeploy 后端** |
| 前端请求 404 | `VITE_API_BASE_URL` 少了 `/api/v1` 或结尾多了 `/` |
| 前端数据是假的 | `VITE_USE_MOCK` 还是 `true` |
| 登录 401 / token 无效 | 后端 `JWT_SECRET_KEY` 被改过（换密钥会让旧 token 全失效），重新登录即可 |
| 建表报 `Unsupported multi schema change` | 用了 `sql/*.sql`（MySQL 版），改用 `sql/tidb/*.sql` |
| 建表报 permission denied (CREATE DATABASE) | TiDB Serverless 无库级权限：在控制台建库，SQL 里只跑建表语句（用 tidb 版） |
| 冷启动慢（首次 2-3 秒） | Serverless 正常现象；已通过「引擎模块级复用 + NullPool」降到最低 |
| Cron 任务没跑 | Hobby 只支持每天一次；确认 `CRON_SECRET` 已配，Vercel → 项目 → Cron Jobs 可看执行记录 |
| 死循环式重复登录 | 401 时前端会跳登录页；若后端一直返回 40100，检查前端是否把 token 存到了 `mq_token` |
