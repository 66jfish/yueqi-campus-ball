# 搭子月球 · 搭子月球前端

Vue3 + Vite + Element Plus + Pinia + axios，响应式适配手机 / 平板 / 电脑，对接后端全部接口。

---

## 一、快速开始

```bash
cd frontend
npm install          # 依赖安装（约 1 分钟）
npm run dev          # 启动开发服务器 → http://localhost:5173
npm run build        # 生产构建 → 产物在 frontend/dist
npm run preview      # 本地预览构建产物 → http://localhost:4173
```

> **开箱即用**：`.env.development` 里 `VITE_USE_MOCK=true`，不启后端也能跑通全部页面（内置 mock 适配器）。
> 联调时把它改成 `false`，并把 `VITE_API_BASE_URL` 指向后端即可。

### 截图预览（脚本自动生成，非示意图）

```bash
npm run dev                       # 先起服务
node scripts/screenshot.mjs       # 用本机 Edge 渲染并截图 → frontend/screenshots/
```

`screenshots/` 下每个页面各两份：`desktop-*.png`（1440×1000）、`mobile-*.png`（390×844 手机视口）：

| 页面 | 桌面 | 手机 |
| --- | --- | --- |
| 球局广场（首页） | `desktop-home.png` | `mobile-home.png` |
| 球局广场 · 热局列表 | `desktop-home-list.png` | `mobile-home-list.png` |
| 登录 / 注册 | `desktop-login.png` | `mobile-login.png` |
| 发起球局 | `desktop-create.png` | `mobile-create.png` |
| 球局详情 | `desktop-detail.png` | `mobile-detail.png` |
| 我的球局 | `desktop-my-games.png` | `mobile-my-games.png` |
| 签到核销 | `desktop-verify.png` | `mobile-verify.png` |
| 个人主页（含封禁横幅） | `desktop-profile.png` | `mobile-profile.png` |

---

## 二、页面清单与路由

| 路由 | 页面 | 说明 |
| --- | --- | --- |
| `/` | 球局广场 | 设计稿首页复刻：品牌区 + 立即约球 + 2×2 球类网格 + 附近热局卡片列表 |
| `/login` | 登录 / 注册 | 单页切换，表单校验 + loading |
| `/create` | 发起球局 | 完整表单（时间/人数/门槛校验），冲突提示 |
| `/games/:id` | 球局详情 | 信息 + 报名/退出 + 发起人（结束球局、去核销）+ 成员墙 |
| `/my` | 我的球局 | 我报名的 / 我发起的 两个 Tab |
| `/verify/:id` | 签到核销 | 名单 + 勾选核销 + 一键核销 + 逐条结果 + 结束球局判缺席 |
| `/me`、`/u/:id` | 个人主页 | 信誉分环、标签、加权明细、参与统计、**小黑屋状态与解禁倒计时** |

---

## 三、设计稿还原说明

### 从设计稿提取的色值（像素级取样，非估算）

| 用途 | 色值 | 来源 |
| --- | --- | --- |
| 页面背景（暖米色） | `#F9F4E9` | 设计稿占比 34% 主色 |
| 主色（暖橙 / 陶土橙） | `#DB9A64` | 「立即约球」按钮与状态标签 |
| 主色深（hover / 强调文字） | `#C9873F` | 按钮按下态推导 |
| 辅助绿（选中卡边框、进度条） | `#8EC5A7` | 球类卡选中态边框 |
| 辅助蓝（进度条） | `#9CC9E3` | 第二条进度条 |
| 辅助粉（女生友好标签） | `#ECBFC7` | 标签底色 |
| 主文字（深棕灰） | `#49413B` | 标题与正文 |
| 次要文字 | `#69625A` / `#9A9188` | 副标题、辅助信息 |
| 描边 | `#EAE3D6` | 卡片边框 |

### 已实现的标注 / 交互

- **球类选择区**：2×2 网格（手机）→ 6 列（桌面），选中项**浅绿色边框高亮**，卡片含手绘猫头 + 球类名 + 代言猫名与局数
- **热局卡片**：球类·模式 → 状态标签（**还差 N 人 / 女生友好 / 今晚 / 信誉金牌 / AA 制**）→ 时间地点 → 人均费用·人数·水平 → **人数进度条（<50% 绿、<80% 蓝、≥80% 橙）** → 「加入球局」按钮
- **按钮风格**：主按钮橙色实心圆角 + 柔和投影；次按钮浅米色底深灰字；均有 `:active` 缩放与 loading 态
- **底部导航**：手机固定底部 4 入口（首页 / 发局 / 我的球局 / 我的），当前项橙色高亮
- **字体层级**：`.t-hero`(26/800) → `.t-section`(17/700) → `.t-card-title`(16/700) → `.t-body`(13.5) → `.t-meta`(12.5) → `.t-caption`(11.5)

### Element Plus 主题定制方式

用**官方 CSS 变量**覆盖（`src/styles/theme.scss`），覆盖主色/成功/警告/危险、文字色、圆角体系、控件高度、
阴影，并做组件级定制（按钮圆角与投影、输入框描边、卡片圆角、Tag 胶囊化、Dialog/Drawer 大圆角）。

> 未采用 `@forward element-plus/theme-chalk` 编译期方案，原因：需要 sass 与 Element 源码强耦合、
> 易受 sass 版本升级影响；CSS 变量方案覆盖范围相同（Element Plus 2.x 全面支持），且零编译风险。

### 设计稿未覆盖页面的风格推导

签到核销页、个人主页、表单页沿用同一套语言：**暖米背景 + 白色大圆角卡片 + 橙色主操作 + 胶囊标签 + 猫头图标**；
警示场景（封禁）用红/橙渐变横幅 + 倒计时，灰阶信息用 `.t-caption`，保证全站一致。

---

## 四、技术要求落地

### 1. 接口地址统一配置

```bash
frontend/.env.development   → VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
frontend/.env.production    → VITE_API_BASE_URL=https://your-backend-domain.com/api/v1
```

**后端地址变化只改一处**（`.env.*` 里的 `VITE_API_BASE_URL`，或 Vercel 环境变量），页面里不出现任何硬编码 URL。

### 2. axios 封装（`src/api/request.js`）

| 能力 | 实现 |
| --- | --- |
| 自动带 JWT | 请求拦截器读 `localStorage.mq_token` → `Authorization: Bearer <token>` |
| 401 统一跳登录 | 清 token → `router.replace({name:'login', query:{redirect: 当前路径}})` |
| 403 小黑屋弹窗 | 命中 `code===403 && data.banned` 时弹「您因放鸽子被禁赛，将于 xx 时间解除」+ **解禁时间** + 期间限制说明 |
| 其他错误 | `ElMessage.error(后端 message)` 统一 Toast |
| 业务码 | `code===0` 直接 resolve `data`；否则 reject 带 `code/data` 的 Error；`40900`（场地/时间冲突）在表单页额外弹窗提示 |

### 3. 表单校验与防重复

- 时间：日期选择器 `disabled-date` 禁用今天之前 + 提交前二次校验「开球时间不能早于当前时间」/「结束时间必须晚于开球时间」
- 人数：`max_players` 2-50 且不小于最少成局人数；`min_players` 必填
- 必填：球类 / 标题 / 场地 / 开球时间 / 结束时间；标题 2-64 字
- 防重复：所有提交按钮绑定 `:loading`（登录、注册、发局、报名、退出、核销、结束球局）

### 4. 小黑屋视觉处理

`components/BanBanner.vue`：红色渐变警示条（剩余 >6h）／橙色渐变（≤6h 即将解禁），
展示**封禁原因 + 解禁时间 + 秒级倒计时**（`useCountdown`）+ 期间可做/不可做说明；
个人主页右侧另有「小黑屋状态」卡；球局广场顶部显示细条提示；全局 403 时弹窗。

---

## 五、npm run build 产物目录 & Vercel 部署

### 构建产物目录

```
frontend/dist/           ← ★ npm run build 的产物目录（vite.config.js: build.outDir = 'dist'）
├── index.html
└── assets/              # 按类型分包：index(应用) / vue / element / 各页面懒加载 chunk
```

构建结果（实测）：`✓ built in 7.51s`；`element` 分包约 1.05 MB（gzip 345 kB），`vue` 117 kB，应用入口 90 kB。

### 部署到 Vercel

1. **导入仓库**，Root Directory 设为 `frontend`（若仓库根就是 frontend 则留空）
2. Framework Preset 选 **Vite**（`vercel.json` 已声明，可自动识别）
   - Build Command：`npm run build`
   - Output Directory：`dist`
3. **配置环境变量**（Project → Settings → Environment Variables，Production / Preview 都建议加）：

| 变量名 | 必填 | 示例 / 说明 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | ✅ **必需** | `https://api.example.com/api/v1`（**必须带 `/api/v1`，结尾不要加 `/`**） |
| `VITE_USE_MOCK` | ✅ 建议 | 生产填 `false`（填 `true` 会走内置假数据、不请求后端） |
| `VITE_API_TIMEOUT` | 可选 | `15000`（毫秒） |
| `VITE_APP_TITLE` | 可选 | `搭子月球 · 搭子月球` |

> ⚠️ Vite 只把 `VITE_` 前缀的变量注入前端。**不要**把数据库密码、JWT 密钥等敏感信息放进前端环境变量，
> 它们会被打进 JS 产物里（`JWT_SECRET_KEY` 只配在后端）。
>
> 环境变量改动后需要 **Redeploy** 才生效（构建期注入）。

4. **SPA 路由**：`vercel.json` 已配置 `rewrites: /(.*) → /index.html`，避免刷新 `/my`、`/games/101` 出现 404
5. **后端跨域**：在后端 `.env` 把 `CORS_ORIGINS` 加上 Vercel 域名（如 `https://your-app.vercel.app`）
6. 静态资源已配置长缓存（`/assets/*` immutable），`index.html` 不缓存，发版无需手动清 CDN

---

## 六、目录结构

```
frontend/
├── .env.development / .env.production    # ★ 接口地址等环境变量（部署只改这里）
├── vercel.json                           # Vercel 构建配置 + SPA 重写
├── vite.config.js                        # 别名 / 分包 / 产物目录 dist
├── scripts/screenshot.mjs                # 截图脚本（Playwright + 本机 Edge）
├── screenshots/                          # 各页面截图（桌面 + 手机）
└── src/
    ├── main.js                           # Element 全量注册 + 主题样式引入
    ├── App.vue                           # 布局壳 + 路由出口（首页 keep-alive）
    ├── styles/
    │   ├── theme.scss                    # ★ 设计令牌 + Element 主题定制
    │   └── app.scss                      # 卡片/标签/字体层级/通用类
    ├── router/index.js                   # 路由 + 登录守卫 + 底部导航项
    ├── stores/user.js                    # token / 用户 / 画像 / 小黑屋状态
    ├── api/
    │   ├── request.js                    # ★ axios 封装（JWT/401/403/Toast）
    │   └── index.js                      # 全部接口按模块归类
    ├── mock/index.js                     # 内置 mock 适配器（演示模式）
    ├── composables/
    │   ├── useResponsive.js              # 断点（<768 / 768-992 / ≥992）
    │   └── useCountdown.js               # 解禁倒计时
    ├── components/
    │   ├── AppLayout.vue                 # 顶部品牌栏 + 桌面导航 + 手机底部导航
    │   ├── GameCard.vue                  # ★ 热局卡片（设计稿核心部件）
    │   ├── SportGrid.vue                 # ★ 2×2 球类选择（选中绿边框）
    │   ├── BanBanner.vue                 # ★ 小黑屋红/橙警示条 + 倒计时
    │   └── CatIcon.vue                   # 手绘猫头 SVG（无图片依赖）
    └── views/                            # 7 个页面
        Home.vue / Login.vue / GameCreate.vue / GameDetail.vue /
        MyGames.vue / CheckinVerify.vue / ProfilePage.vue
```

---

## 七、响应式断点（对齐 Element 栅格）

| 断点 | 宽度 | 布局 |
| --- | --- | --- |
| xs | <768px | **单列 + 底部固定导航**；球类 2 列；隐藏顶部导航项 |
| sm | 768-992px | 两列；球类 3 列；顶部导航出现 |
| md | ≥992px | 多列（列表 3 列、详情 5:3）；球类 6 列；侧栏 sticky；底部导航隐藏 |

实现方式：`el-row/el-col` 的 `:xs/:sm/:md` 属性 + `useResponsive()`（matchMedia 断点，用于控制导航形态与展示密度）。
