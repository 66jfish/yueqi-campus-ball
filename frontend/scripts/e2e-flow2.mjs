/**
 * 全流程第二阶段：报名(必填水平) → 核销(+2) → 结束球局 → 缺席 → 小黑屋拦截 → 个人主页
 * 认证方式：先用 API 登录拿 token，再注入 localStorage（比驱动登录表单稳）
 */
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

const BASE = process.env.SITE || 'http://134.175.40.145'
const API = BASE + '/api/v1'
const OUT = fileURLToPath(new URL('../../deliverables/e2e-shots/', import.meta.url))
mkdirSync(OUT, { recursive: true })

const STAMP = process.env.STAMP || String(Date.now()).slice(-7)
const C = { no: `C${STAMP}`, nick: '月球发起人', pwd: 'test123456' }
const A = { no: `A${STAMP}`, nick: '到场的小齐刘海', pwd: 'test123456' }
const B = { no: `B${STAMP}`, nick: '放鸽子的小橘', pwd: 'test123456' }

const log = []
let n = 100
async function shot(page, name, note = '') {
  n += 1
  const file = `${OUT}${String(n).padStart(3, '0')}-${name}.png`
  await page.screenshot({ path: file })
  log.push(`${n} ${name} ${note}`)
  console.log(`  ✓ ${n} ${name} ${note}`)
}

async function apiRegister(u) {
  const r = await fetch(`${API}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ student_no: u.no, nickname: u.nick, password: u.pwd, campus: '老校区' })
  })
  const j = await r.json()
  if (j.code !== 0 && !String(j.message).includes('已注册')) {
    throw new Error(`${u.no} 注册失败: ${j.message}`)
  }
}

async function apiLogin(u) {
  const r = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account: u.no, password: u.pwd })
  })
  const j = await r.json()
  if (j.code !== 0) throw new Error(`${u.no} 登录失败: ${j.message}`)
  return { token: j.data.token.access_token, user: j.data.user }
}

async function ctxAs(browser, session) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 980 }, deviceScaleFactor: 1.5, locale: 'zh-CN' })
  await ctx.addInitScript((s) => {
    localStorage.setItem('mq_token', s.token)
    localStorage.setItem('mq_user', JSON.stringify(s.user))
  }, session)
  return ctx
}

async function main() {
  const browser = await chromium.launch({ channel: 'msedge' })
  await apiRegister(C); await apiRegister(A); await apiRegister(B)
  const sC = await apiLogin(C), sA = await apiLogin(A), sB = await apiLogin(B)
  console.log(`  账号就绪：C=${sC.user.id} A=${sA.user.id} B=${sB.user.id}`)

  // ---- 用 API 建局（环节少、稳定；表单截图阶段一已拍）----
  const pad = (x) => String(x).padStart(2, '0')
  const fmt = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`
  const start = new Date(Date.now() + 8 * 60 * 1000)
  const end = new Date(Date.now() + 2 * 3600 * 1000)
  const gRes = await fetch(`${API}/game`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${sC.token}` },
    body: JSON.stringify({
      sport_type: 3, title: `月球羽毛球双打 ${STAMP}`, description: 'E2E 全流程验证用球局',
      campus: '新校区', venue_name: '新校区风雨操场 1 号场', venue_address: '风雨操场一层',
      start_time: fmt(start), end_time: fmt(end), max_players: 6, min_players: 2, skill_level_limit: 2
    })
  })
  const g = (await gRes.json()).data
  console.log(`  球局已创建：id=${g.id}（最低水平要求=初级，校区=新校区）`)

  // ---- A / B 报名（UI：必填水平弹窗）----
  let ctxA = await ctxAs(browser, sA)
  let pA = await ctxA.newPage()
  try {
    await pA.goto(`${BASE}/games/${g.id}`, { waitUntil: 'networkidle' })
    await pA.waitForTimeout(1200)
    if (n === 100) await shot(pA, 'game-detail', '← 球局详情（新校区 + 最低水平要求）')
    await pA.getByRole('button', { name: /加入球局/ }).first().click()
    await pA.waitForTimeout(700)
    await shot(pA, 'signup-dialog-required-skill', '← 报名弹窗：水平必填（不选不能提交）')
    // 先试「不选直接确认」应被拦
    await pA.getByRole('button', { name: /确认报名/ }).click()
    await pA.waitForTimeout(800)
    await shot(pA, 'signup-blocked-no-skill', '← 未选水平 → 提示后不放行')
    await pA.locator('.join-skill .el-radio-button', { hasText: '高级' }).first().click()
    await pA.getByRole('button', { name: /确认报名/ }).click()
    await pA.waitForTimeout(2500)
    await shot(pA, 'signup-A-success', '← A 报名成功（自评高级，满足最低要求）')
  } catch (e) {
    await shot(pA, 'error-A', '← ' + String(e).slice(0, 80))
  }

  let ctxB = await ctxAs(browser, sB)
  let pB = await ctxB.newPage()
  try {
    await pB.goto(`${BASE}/games/${g.id}`, { waitUntil: 'networkidle' })
    await pB.waitForTimeout(900)
    await pB.getByRole('button', { name: /加入球局/ }).first().click()
    await pB.waitForTimeout(600)
    await pB.locator('.join-skill .el-radio-button', { hasText: '初级' }).first().click()
    await pB.getByRole('button', { name: /确认报名/ }).click()
    await pB.waitForTimeout(2500)
    await shot(pB, 'signup-B-success', '← B 报名成功（自评初级）')
  } catch (e) {
    await shot(pB, 'error-B', '← ' + String(e).slice(0, 80))
  }

  // ---- C 核销：只勾选 C 和 A，B 留作缺席 ----
  const ctxC = await ctxAs(browser, sC)
  const pC = await ctxC.newPage()
  try {
    await pC.goto(`${BASE}/verify/${g.id}`, { waitUntil: 'networkidle' })
    await pC.waitForTimeout(1500)
    await shot(pC, 'verify-roster', '← 核销名单：每人显示水平 + 信誉分')
    const boxes = pC.locator('.verify__row .el-checkbox')
    await boxes.nth(0).click(); await boxes.nth(1).click()
    await pC.waitForTimeout(300)
    await shot(pC, 'verify-selected', '← 勾选发起人 + A（B 故意不核销）')
    await pC.getByRole('button', { name: /核销勾选/ }).click()
    await pC.waitForTimeout(3000)
    await shot(pC, 'verify-result', '← 核销结果：信誉分 +2（惰性结算）')
  } catch (e) {
    await shot(pC, 'error-verify', '← ' + String(e).slice(0, 80))
  }

  // ---- C 结束球局 → 缺席判定 ----
  try {
    await pC.goto(`${BASE}/games/${g.id}`, { waitUntil: 'networkidle' })
    await pC.waitForTimeout(1000)
    await pC.getByRole('button', { name: /结束球局/ }).first().click()
    await pC.waitForTimeout(800)
    await shot(pC, 'finish-confirm', '← 结束球局二次确认（提示缺席将扣 10 分）')
    await pC.getByRole('button', { name: /确认结束/ }).click()
    await pC.waitForTimeout(3000)
    await shot(pC, 'finish-done', '← 球局结束，B 被判缺席 -10 分')
  } catch (e) {
    await shot(pC, 'error-finish', '← ' + String(e).slice(0, 80))
  }

  // ---- B 被小黑屋拦截：发局 403 弹窗 ----
  try {
    await pB.goto(`${BASE}/create`, { waitUntil: 'networkidle' })
    await pB.waitForTimeout(800)
    await shot(pB, 'ban-before-submit', '← B 进入发局页（可浏览，提交才会被拦）')
    await pB.locator('input[placeholder*="球局标题"]').fill('B 试着发局')
    await pB.locator('.el-form .el-select').first().click()
    await pB.waitForTimeout(250)
    await pB.locator('.el-select-dropdown__item', { hasText: '老校区' }).first().click()
    await pB.locator('input[placeholder*="校内场地名称"]').fill('老校区体育馆 1 号场')
    const d = pB.locator('.el-date-editor input')
    await d.nth(0).click(); await d.nth(0).fill(fmt(start)); await d.nth(0).press('Enter')
    await d.nth(1).click(); await d.nth(1).fill(fmt(end)); await d.nth(1).press('Enter')
    await pB.getByRole('button', { name: /发布球局/ }).click()
    await pB.waitForTimeout(3000)
    await shot(pB, 'ban-403-dialog', '← 403 小黑屋弹窗：禁赛文案 + 解禁时间')
  } catch (e) {
    await shot(pB, 'error-ban', '← ' + String(e).slice(0, 80))
  }

  // ---- B 个人主页：封禁横幅 + 倒计时 + 常打项目 ----
  try {
    await pB.goto(`${BASE}/me`, { waitUntil: 'networkidle' })
    await pB.waitForTimeout(2000)
    await shot(pB, 'profile-B-banned', '← 个人主页：红色禁赛横幅 + 解禁倒计时')
    await pB.locator('.how__head').first().click()
    await pB.waitForTimeout(600)
    await shot(pB, 'profile-B-breakdown', '← 信誉分怎么来的（加权明细）')
  } catch (e) {
    await shot(pB, 'error-profileB', '← ' + String(e).slice(0, 80))
  }

  // ---- A 个人主页：信誉 +2 与常打项目/自评水平 ----
  try {
    await pA.goto(`${BASE}/me`, { waitUntil: 'networkidle' })
    await pA.waitForTimeout(2000)
    await shot(pA, 'profile-A-credit', '← A 个人主页：签到 +2、常打项目、最近自评水平')
  } catch (e) {
    await shot(pA, 'error-profileA', '← ' + String(e).slice(0, 80))
  }

  // ---- 手机端首页（响应式） ----
  const mctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2, locale: 'zh-CN' })
  await mctx.addInitScript((s) => { localStorage.setItem('mq_token', s.token); localStorage.setItem('mq_user', JSON.stringify(s.user)) }, sA)
  const pm = await mctx.newPage()
  await pm.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await pm.waitForTimeout(1500)
  await shot(pm, 'mobile-home', '← 手机端首页（2 列球类 + 底部导航）')

  writeFileSync(`${OUT}step-log-phase2.txt`, log.join('\n'), 'utf-8')
  console.log(`\n阶段二完成，球局 id=${g.id}，截图目录：${OUT}`)
  await browser.close()
}

main().catch((e) => {
  console.error('阶段二整体失败：', String(e).slice(0, 300))
  process.exit(1)
})
