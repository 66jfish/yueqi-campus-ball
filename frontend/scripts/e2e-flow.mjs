/**
 * 真实环境全流程截图（Playwright + 本机 Edge）
 * 目标：http://134.175.40.145
 * 流程：首页 → 注册 → 登录 → 发局(含校外/最低水平) → 报名(必填水平) → 核销 → 结束球局
 *      → 缺席者被拦(小黑屋弹窗) → 个人主页(封禁横幅/常打项目/自评水平)
 * 每步一张截图，单步失败不影响后续；输出 step-log。
 */
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

const BASE = process.env.SITE || 'http://134.175.40.145'
const OUT = fileURLToPath(new URL('../../deliverables/e2e-shots/', import.meta.url))
mkdirSync(OUT, { recursive: true })

const stamp = Date.now().toString().slice(-6)
const C = { no: `C${stamp}`, nick: '月球发起人', pwd: 'test123456' }
const A = { no: `A${stamp}`, nick: '到场的小齐刘海', pwd: 'test123456' }
const B = { no: `B${stamp}`, nick: '放鸽子的小橘', pwd: 'test123456' }

const log = []
let n = 0
async function shot(page, name, note = '') {
  n += 1
  const file = `${OUT}${String(n).padStart(2, '0')}-${name}.png`
  await page.screenshot({ path: file })
  log.push(`${String(n).padStart(2, '0')} ${name} ${note}`)
  console.log(`  ✓ ${String(n).padStart(2, '0')} ${name} ${note}`)
  return file
}

async function register(page, u, campus = '老校区') {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: '注册' }).first().click()
  await page.waitForTimeout(300)
  await shot(page, `register-form-${u.no}`, '← 注册表单（已无「球技水平」项）')
  await page.locator('.el-form input').nth(0).fill(u.no)
  await page.locator('.el-form input').nth(1).fill(u.nick)
  await page.locator('.el-form input[type=password]').nth(0).fill(u.pwd)
  await page.locator('.el-form input[type=password]').nth(1).fill(u.pwd)
  // 校区选择（默认老校区，这里显式打开看选项）
  await page.locator('.el-form .el-select').first().click()
  await page.waitForTimeout(300)
  await shot(page, `campus-options-${u.no}`, '← 校区三项：老校区/新校区/校外')
  await page.locator('.el-select-dropdown__item', { hasText: campus }).first().click()
  await shot(page, `register-filled-${u.no}`, '← 填写完成')
  await page.getByRole('button', { name: /注册并登录/ }).click()
  await page.waitForTimeout(2500)
  return page
}

async function login(page, u) {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.locator('input').first().fill(u.no)
  await page.locator('input[type=password]').first().fill(u.pwd)
  await page.getByRole('button', { name: /^登录/ }).first().click()
  await page.waitForTimeout(2500)
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
}

async function createGame(page) {
  await page.goto(`${BASE}/create`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  const now = new Date(Date.now() + 5 * 60 * 1000)
  const end = new Date(Date.now() + 2 * 3600 * 1000)
  const pad = (x) => String(x).padStart(2, '0')
  const fmt = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:00`

  await page.locator('input[placeholder*="球局标题"]').fill(`月球羽毛球双打 ${stamp}`)
  // 校区 → 校外（验证自由输入）
  await page.locator('.el-form .el-select').first().click()
  await page.waitForTimeout(250)
  await page.locator('.el-select-dropdown__item', { hasText: '校外' }).first().click()
  await page.waitForTimeout(200)
  await page.locator('input[placeholder*="校外球馆名称"]').fill('月球体育中心 2 号羽毛球馆')
  await shot(page, 'create-offcampus-freevenue', '← 选「校外」→ 场地为自由输入')

  // 时间：开球 = now+5min（保证核销窗口已开放）
  const dts = page.locator('.el-date-editor input')
  await dts.nth(0).click(); await dts.nth(0).fill(fmt(now)); await dts.nth(0).press('Enter')
  await page.waitForTimeout(300)
  await dts.nth(1).click(); await dts.nth(1).fill(fmt(end)); await dts.nth(1).press('Enter')
  await page.waitForTimeout(300)
  // 最低水平要求 = 初级(2)
  await page.locator('.el-form .el-select').last().click()
  await page.waitForTimeout(250)
  await page.locator('.el-select-dropdown__item', { hasText: '初级' }).first().click()
  await shot(page, 'create-min-skill', '← 最低水平要求：不限/初级/中级/高级/大神')
  await page.getByRole('button', { name: /发布球局/ }).click()
  await page.waitForTimeout(3000)
  await shot(page, 'create-result', '← 发布结果')
  return page.url()
}

async function main() {
  const browser = await chromium.launch({ channel: 'msedge' })
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 980 }, deviceScaleFactor: 1.5, locale: 'zh-CN'
  })
  const page = await ctx.newPage()
  page.on('dialog', (d) => d.accept())

  try {
    // ① 首页
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await shot(page, 'home', '← 首页（新校区筛选 + 新猫名「齐刘海」）')

    // ② 注册三个账号
    for (const u of [C, A, B]) await register(page, u)
    await shot(page, 'register-done', '← 注册后已自动登录')

    // ③ 发局（用发起人账号，校外 + 最低水平）
    await login(page, C)
    const createUrl = await createGame(page)

    // ④ 球局详情 + 报名（A 必填水平）
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1200)
    await shot(page, 'home-with-game', '← 首页出现刚发的球局')
    await page.getByRole('button', { name: /加入球局/ }).first().click()
    await page.waitForTimeout(600)
    await shot(page, 'signup-skill-dialog', '← 报名弹窗：水平必填')
    await page.locator('.join-skill .el-radio-button', { hasText: '高级' }).first().click()
    await page.getByRole('button', { name: /确认报名/ }).click()
    await page.waitForTimeout(2500)
    await shot(page, 'signup-success', '← 报名成功（已记录自评水平）')
  } catch (e) {
    await shot(page, 'error-1', '← 步骤异常：' + String(e).slice(0, 60))
  }

  writeFileSync(`${OUT}step-log.txt`, log.join('\n'), 'utf-8')
  console.log('\n阶段一完成，产出：', OUT)
  await ctx.close()
  await browser.close()
}

main()
