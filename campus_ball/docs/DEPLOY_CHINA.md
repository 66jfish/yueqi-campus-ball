# 国内可访问部署方案（因 `*.vercel.app` 被阻断而制定）

## 一、为什么必须换

实测（2026-11-18，本机国内网络）：

| 检测 | 结果 |
| --- | --- |
| `nslookup yueqi-campus-ball-api.vercel.app` | 解析到 `2a03:2880:f127:83:face:b00c:0:25de`（Facebook IPv6 段，典型 DNS 污染）+ `74.86.3.208` |
| TCP 443 → `*.vercel.app` | ❌ 不可达 |
| TCP 443 → `api.vercel.com` | ✅ 通（说明不是本地网络故障） |
| TCP 443 → `baidu.com` | ✅ 通 |

结论：Vercel 部署本身是成功的（项目 READY、域名 verified），但**默认的 `*.vercel.app` 域名在国内无法访问**，
因此前端页面、后端 `/docs`、以及页面里的 API 请求在国内都不可用。需要换到国内可达的托管。

---

## 二、三条落地路线对比

| 路线 | 前端 | 后端 | 数据库 | 国内可用 | 成本 | 域名/备案 |
| --- | --- | --- | --- | --- | --- | --- |
| **A 轻量应用服务器（推荐，最可控）** | Nginx 托管 `dist` | Docker 容器（本仓库已带 Dockerfile） | Docker MySQL 8（compose 里已配） | ✅ 稳定 | 新用户首年约 ¥50~90/年起的活动机型 | IP+端口可直接访问；绑自有域名**需备案** |
| **B 微信云托管** | 云托管静态托管 | 云托管容器（同一份 Dockerfile） | 云托管自带 MySQL | ✅ 稳定 | 有免费额度，按量计费 | 平台分配默认域名，**无需自备域名/备案**；开通需**微信小程序或公众号**账号（个人可免费注册小程序） |
| **C 腾讯云 EdgeOne Pages + 函数** | EdgeOne Pages（免费额度） | 腾讯云函数 SCF（容器镜像） | 腾讯云 MySQL 免费试用 | ✅ 稳定 | 有免费额度 | 使用自定义域名**需备案** |

> **推荐顺序**：A（你能拿到服务器就行，最省心）→ B（想免备案且有小程序/公众号账号）→ C（想全托管、有备案域名）
> 三条路线**后端代码完全一致**（都用同一份 Dockerfile + 同一套环境变量），只是部署方式不同。

---

## 三、路线 A：轻量应用服务器（逐步操作）

### 3.1 购买与初始化

1. <https://cloud.tencent.com> → 登录（微信扫码）→ 完成**实名认证**
2. 搜 **轻量应用服务器 Lighthouse** → 选 **2核2G** 或 **2核4G**，镜像选 **Ubuntu 22.04**（或 Docker 应用镜像）→ 地域选**广州/上海**
3. 购买后在「防火墙」里放行端口：**22（SSH）、80（HTTP）、8000（后端 API 测试用）**

### 3.2 部署（服务器上执行）

```bash
# 1) 装 Docker（Ubuntu）
curl -fsSL https://get.docker.com | bash -s docker --mirror Aliyun && systemctl enable --now docker

# 2) 拉代码（你已推送到 GitHub，服务器可直接 clone）
git clone https://github.com/66jfish/yueqi-campus-ball.git
cd yueqi-campus-ball/campus_ball

# 3) 配置后端环境变量（常驻模式，注意与 Vercel 版的差异）
cat > .env <<'EOF'
SERVERLESS_MODE=false
ENV=prod
DEBUG=false
DB_USER=yueqi
DB_PASSWORD=换成你的强密码
MYSQL_ROOT_PASSWORD=换一个更强的root密码
JWT_SECRET_KEY=粘贴 python -c "import secrets;print(secrets.token_urlsafe(48))" 的结果
CRON_SECRET=粘贴随机串
CORS_ORIGINS=http://你的服务器IP,http://localhost:5173
AI_ENABLED=true
# DEEPSEEK_API_KEY=            # 留空即自动降级为本地加权规则版
EOF

# 4) 一键起 MySQL + 后端（首次启动自动建表 + 写入演示数据）
docker compose up -d --build

# 5) 自检
docker compose ps
curl http://127.0.0.1:8000/health          # 期望 "database": true
curl http://127.0.0.1:8000/api/v1/system/runtime
```

浏览器打开 `http://<服务器IP>:8000/docs` → **这就是后端接口文档链接（国内可直连）**

### 3.3 前端构建与托管

```bash
# 本地（或服务器）：构建前端，把后端地址指向服务器
cd frontend
echo "VITE_API_BASE_URL=http://<服务器IP>:8000/api/v1" > .env.production
echo "VITE_USE_MOCK=false" >> .env.production
npm install && npm run build        # 产物在 frontend/dist
```

把 `dist/` 上传到服务器，用 Nginx 托管：

```bash
# 服务器上
sudo apt install -y nginx
sudo mkdir -p /var/www/yueqi && sudo cp -r dist/* /var/www/yueqi/
sudo tee /etc/nginx/sites-available/yueqi <<'EOF'
server {
    listen 80;
    server_name _;
    root /var/www/yueqi;
    index index.html;
    location / { try_files $uri $uri/ /index.html; }   # SPA 路由（刷新不 404）
}
EOF
sudo ln -sf /etc/nginx/sites-available/yueqi /etc/nginx/sites-enabled/yueqi
sudo rm -f /etc/nginx/sites-enabled/default && sudo nginx -t && sudo systemctl reload nginx
```

→ 打开 `http://<服务器IP>` 即为**前端公网链接（国内可直连）**

### 3.4 想用域名 + HTTPS（可选）

1. 买域名（如 `yueqi.example.com`）→ 解析 A 记录到服务器 IP
2. **国内服务器绑域名需 ICP 备案**（腾讯云控制台可提交，约 3~20 个工作日）；不备案则只能用 IP 访问
3. 备案通过后：`sudo apt install -y certbot python3-certbot-nginx && sudo certbot --nginx -d yueqi.example.com`

---

## 四、路线 B：微信云托管（免备案、国内可达）

> 前提：有**微信小程序或公众号**账号（个人可免费注册小程序，5 分钟）

1. <https://cloud.weixin.qq.com> → 微信扫码登录 → 选择你的小程序/公众号 → 开通云托管
2. **新建服务** `yueqi-api` → 部署方式选「**本地代码 / 代码包上传**」→ 上传 `campus_ball` 目录（内含 Dockerfile，平台会自动识别）→ 端口填 **8000**
3. 服务设置 → **环境变量**：与路线 A 的 `.env` 一致（`SERVERLESS_MODE=false`、`DB_*`、`JWT_SECRET_KEY`、`CORS_ORIGINS`）
4. **数据库**：云托管控制台 → 数据库 → 新建 MySQL → 建库 `campus_ball` → 把连接信息填进上面的 `DB_*`
   - 初始化建表：在云托管「数据库 → SQL 执行」里依次执行 `sql/tidb/001_schema.sql`、`sql/tidb/002_init_data.sql`
5. 部署完成后平台会给出**默认 HTTPS 域名（国内可直连）** → 即后端文档链接：`https://<默认域名>/docs`
6. 前端：`VITE_API_BASE_URL=https://<默认域名>/api/v1` → `npm run build` → 用云托管的**静态网站托管**上传 `dist`

---

## 五、环境变量清单（常驻模式，与 Vercel 版的差异）

| 变量 | 常驻（服务器 / 云托管） | Vercel Serverless 版 | 说明 |
| --- | --- | --- | --- |
| `SERVERLESS_MODE` | **`false`** | `true` | 决定是否启用连接池与进程内定时任务 |
| `DB_REQUIRE_SSL` | `false`（容器内网）／云托管 MySQL 按需 | `true` | TiDB Cloud 强制 TLS；自建 MySQL 一般不需要 |
| `DB_USE_NULL_POOL` | `false` | `true` | Serverless 用 NullPool，常驻用连接池 |
| `DB_HOST` / `DB_PORT` | `mysql` / `3306`（compose 内网） | 云库地址 / 4000 | — |
| `JWT_SECRET_KEY` | 必填 | 必填 | 48 位随机 |
| `CRON_SECRET` | 可选 | 必填（Vercel Cron） | 常驻模式下定时任务在进程内跑，可不配 |
| `CORS_ORIGINS` | 前端实际域名/IP | 前端 Vercel 域名 | 逗号分隔多来源 |
| `DEEPSEEK_API_KEY` | 可选 | 可选 | 留空自动降级本地加权规则版 |

---

## 六、建表 SQL 执行顺序（国内 MySQL）

| 场景 | 执行文件 | 说明 |
| --- | --- | --- |
| **全新库** | 只执行 `sql/tidb/001_schema.sql` + `sql/tidb/002_init_data.sql` | 001 已含全部最新字段与索引；002 写入 3 个演示账号 |
| 从 v1.0 老库升级 | 再依次执行 `003` → `004` → `005` | 这三个是增量迁移，**新库执行会报 Duplicate column** |
| 用 docker compose | 无需手动执行 | 首次启动自动按顺序灌入 001、002 |

> `sql/tidb/*.sql` 同时兼容 MySQL 8（去掉了 `CREATE DATABASE`/`USE`，库名由连接串或 `MYSQL_DATABASE` 指定；
> 迁移语句已按「一条 ALTER 一个操作」拆开）——国内 MySQL 与 TiDB 都能直接跑。

---

## 七、部署后自检

```bash
curl http://<地址>/health                      # database: true
curl http://<地址>/api/v1/system/runtime       # serverless_mode: false、pool: QueuePool
curl -X POST http://<地址>/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"account":"20230001","password":"123456"}'   # 演示账号，应返回双令牌
python campus_ball/scripts/e2e_check.py --base http://<地址>/api/v1   # 33 项端到端
```
