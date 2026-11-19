/** 补齐「发局表单」截图：校外自由输入 + 最低水平要求选项 */
import { chromium } from 'playwright'
import { fileURLToPath, URL } from 'node:url'

const BASE = process.env.SITE || 'http://134.175.40.145'
const API = BASE + '/api/v1'
const OUT = fileURLToPath(new URL('../../deliverables/e2e-shots/', import.meta.url))
const S = String(Date.now()).slice(-6)
const pad = (x) => String(x).padStart(2, '0')
const fmt = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:00`

const no = `g${S}`
await fetch(`${API}/auth/register`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ student_no: no, nickname: '发局表单验证', password: 'test123456', phone: `137${S}`, campus: '老校区' })
})
const login = await (await fetch(`${API}/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ account: no, password: 'test123456' })
})).json()
const s = { token: login.data.token.access_token, user: login.data.user }

const browser = await chromium.launch({ channel: 'msedge' })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1.5, locale: 'zh-CN' })
await ctx.addInitScript((x) => {
  localStorage.setItem('mq_token', x.token)
  localStorage.setItem('mq_user', JSON.stringify(x.user))
}, s)
const page = await ctx.newPage()
await page.goto(`${BASE}/create`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)

const start = new Date(Date.now() + 10 * 60 * 1000)
const end = new Date(Date.now() + 2.5 * 3600 * 1000)
await page.locator('.el-form-item:has-text("球局标题") input').first().fill(`月球羽毛球双打 ${S}`)
// 选「校外」→ 场地自由输入
await page.locator('.el-form-item:has-text("校区") .el-select').first().click()
await page.waitForTimeout(300)
await page.locator('.el-select-dropdown__item', { hasText: '校外' }).first().click()
await page.waitForTimeout(300)
await page.locator('input[placeholder*="校外球馆名称"]').fill('月球体育中心 2 号羽毛球馆')
const dt = page.locator('.el-date-editor input')
await dt.nth(0).click(); await dt.nth(0).fill(fmt(start)); await dt.nth(0).press('Enter')
await page.waitForTimeout(250)
await dt.nth(1).click(); await dt.nth(1).fill(fmt(end)); await dt.nth(1).press('Enter')
await page.waitForTimeout(250)
await page.screenshot({ path: `${OUT}22-create-offcampus-freevenue.png` })
console.log('  ✓ 22 create-offcampus-freevenue ← 选「校外」→ 场地为自由输入')
// 最低水平要求下拉
await page.locator('.el-form-item:has-text("最低水平要求") .el-select').first().click()
await page.waitForTimeout(400)
await page.screenshot({ path: `${OUT}23-create-min-skill-options.png` })
console.log('  ✓ 23 create-min-skill-options ← 不限/初级/中级/高级/大神')
await page.locator('.el-select-dropdown__item', { hasText: '中级' }).first().click()
await page.waitForTimeout(300)
await page.screenshot({ path: `${OUT}24-create-filled.png` })
console.log('  ✓ 24 create-filled ← 表单填写完成（校外场地 + 中级要求）')
await browser.close()
