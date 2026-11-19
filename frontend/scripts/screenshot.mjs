/**
 * 页面截图脚本（真实渲染，不是示意图）
 * ---------------------------------------------------------------------------
 * 使用本机已安装的 Edge（channel: 'msedge'），无需下载浏览器内核。
 * 用法：node scripts/screenshot.mjs         （需先启动 dev server 于 5173 端口）
 * 产出：frontend/screenshots/{desktop,mobile}-{page}.png
 *
 * 为什么用脚本而不是手工截：一次跑出「桌面 + 手机」两套断点，便于核对响应式效果。
 */
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

const BASE = process.env.SHOT_BASE || 'http://127.0.0.1:5173'
const OUT = fileURLToPath(new URL('../screenshots/', import.meta.url))
mkdirSync(OUT, { recursive: true })

const DESKTOP = { width: 1440, height: 1000 }
const MOBILE = { width: 390, height: 844 } // iPhone 14 逻辑分辨率

/** 演示用登录态（mock 模式下任意 token 都能通过路由守卫） */
const AUTH_STATE = {
  mq_token: 'mock.jwt.token',
  mq_refresh_token: 'mock.refresh.token',
  mq_user: JSON.stringify({
    id: 2,
    student_no: '20230001',
    nickname: '球场小王子',
    campus: '老校区',
    college: '计算机学院',
    skill_level: 4,
    reputation_score: 88,
    credit_score: 88,
    credit_level: 3
  })
}

const PAGES = [
  { name: 'home', path: '/', wait: '.hero' },
  // 手机首屏看不到热局卡片，额外截一张滚动到列表的图（验证卡片样式）
  { name: 'home-list', path: '/', wait: '.filters', scrollTo: '.filters' },
  { name: 'login', path: '/login', wait: '.auth__card' },
  { name: 'create', path: '/create', wait: 'form' },
  { name: 'detail', path: '/games/101', wait: '.detail' },
  { name: 'my-games', path: '/my', wait: '.mytabs' },
  { name: 'verify', path: '/verify/101', wait: '.verify__ops' },
  { name: 'profile', path: '/me', wait: '.score' }
]

const browser = await chromium.launch({ channel: 'msedge' })

for (const [label, viewport] of [
  ['desktop', DESKTOP],
  ['mobile', MOBILE]
]) {
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 2,
    locale: 'zh-CN',
    isMobile: label === 'mobile',
    hasTouch: label === 'mobile'
  })
  await context.addInitScript((state) => {
    for (const [k, v] of Object.entries(state)) localStorage.setItem(k, v)
  }, AUTH_STATE)

  const page = await context.newPage()
  for (const p of PAGES) {
    await page.goto(BASE + p.path, { waitUntil: 'networkidle' })
    try {
      await page.waitForSelector(p.wait, { timeout: 8000 })
    } catch {
      console.warn(`  ! ${p.name} 等待选择器超时：${p.wait}`)
    }
    if (p.scrollTo) {
      // 等 mock 数据回来后再滚动，保证目标区块已渲染
      await page.waitForSelector('.gcard', { timeout: 8000 }).catch(() => {})
      await page.evaluate((sel) => {
        document.querySelector(sel)?.scrollIntoView({ block: 'start' })
      }, p.scrollTo)
      // 去掉固定底部导航对视线的遮挡：截图时隐藏它
      await page.addStyleTag({ content: '.bottomnav{visibility:hidden}' })
    }
    await page.waitForTimeout(700) // 等 mock 延迟与过渡动画结束
    const file = `${OUT}${label}-${p.name}.png`
    await page.screenshot({ path: file, fullPage: label === 'desktop' && !p.scrollTo })
    console.log(`  ✓ ${label}/${p.name} -> ${file}`)
  }
  await context.close()
}

await browser.close()
console.log('截图完成')
