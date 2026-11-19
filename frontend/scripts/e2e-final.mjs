/**
 * 搭子月球 · 真实环境全流程截图（http://134.175.40.145）
 * 覆盖：首页 → 注册(无球技水平项) → 校区三项 → 发局(校外自由输入+最低水平) → 报名(水平必填)
 *      → 核销(+2) → 结束球局 → 缺席(-10) → 小黑屋 403 → 个人主页(封禁横幅/常打项目/自评水平)
 */
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

const BASE = process.env.SITE || 'http://134.175.40.145'
const API = BASE + '/api/v1'
const OUT = fileURLToPath(new URL('../../deliverables/e2e-shots/', import.meta.url))
mkdirSync(OUT, { recursive: true })

const S = String(Date.now()).slice(-6)
const C = { no: `c${S}`, nick: '月球发起人', pwd: 'test123456', phone: `138${S}1` }
const A = { no: `a${S}`, nick: '到场的小齐刘海', pwd: 'test123456', phone: `138${S}2` }
const B = { no: `b${S}`, nick: '放鸽子的小橘', pwd: 'test123456', phone: `138${S}3` }

const log = []
let n = 0
async function shot(page, name, note = '') {
  n += 1
  await page.screenshot({ path: `${OUT}${String(n).padStart(2, '0')}-${name}.png` })
  log.push(`${String(n).padStart(2, '0')} ${name} ${note}`)
  console.log(`  ✓ ${String(n).padStart(2, '0')} ${name} ${note}`)
}
const pad = (x) => String(x).padStart(2, '0')
const fmt = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:00`

async function apiRegister(u) {
  const r = await fetch(`${API}/auth/register`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ student_no: u.no, nickname: u.nick, password: u.pwd, phone: u.phone, campus: '老校区' })
  })
  const j = await r.json()
  if (j.code !== 0 && !String(j.message).includes('已注册')) throw new Error(`${u.no} 注册失败：${j.message}`)
  return j.data
}
async function apiLogin(u) {
  const r = await fetch(`${API}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account: u.no, password: u.pwd })
  })
  const j = await r.json()
  if (j.code !== 0) throw new Error(`${u.no} 登录失败：${j.message}`)
  return { token: j.data.token.access_token, user: j.data.user }
}
async function ctxAs(browser, s) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1.5, locale: 'zh-CN' })
  await ctx.addInitScript((x) => {
    localStorage.setItem('mq_token', x.token)
    localStorage.setItem('mq_user', JSON.stringify(x.user))
  }, s)
  return ctx
}
async function api(path, body, token, method = 'POST') {
  const r = await fetch(API + path, {
    method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined
  })
  return r.json()
}

async function main() {
  const browser = await chromium.launch({ channel: 'msedge' })

  // ---------- ① 首页 + UI 注册（截图用真实表单）----------
  const pub = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1.5, locale: 'zh-CN' })
  const p0 = await pub.newPage()
  await p0.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await p0.waitForTimeout(1500)
  await shot(p0, 'home', '← 首页：校区筛选(老校区/新校区/校外) + 新猫名')

  await p0.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await p0.getByRole('button', { name: '注册' }).first().click()
  await p0.waitForTimeout(400)
  await shot(p0, 'register-form', '← 注册表单：已无「球技水平」项')
  await p0.locator('input[placeholder="校内唯一"]').fill(C.no)
  await p0.locator('input[placeholder="球局里展示的名字"]').fill(C.nick)
  await p0.locator('input[placeholder="6-64 位"]').fill(C.pwd)
  await p0.locator('input[placeholder="再次输入"]').fill(C.pwd)
  await p0.locator('input[placeholder="可作为登录账号"]').fill(C.phone)
  await p0.locator('.el-form-item:has-text("校区") .el-select').first().click()
  await p0.waitForTimeout(350)
  await shot(p0, 'campus-options', '← 校区仅三项：老校区 / 新校区 / 校外')
  await p0.locator('.el-select-dropdown__item', { hasText: '老校区' }).first().click()
  await p0.getByRole('button', { name: /注册并登录/ }).click()
  await p0.waitForTimeout(3000)
  await shot(p0, 'register-success', '← 注册成功并自动登录')
  await pub.close()

  // ---------- 账号准备（API，保证后续步骤稳定）----------
  // 账号准备：用独立学号走 API 注册（避免与上面 UI 表单账号混淆），保证后续步骤稳定
  const sC = await (async () => { const u = { ...C, no: C.no + 'c' }; await apiRegister(u); return apiLogin(u) })()
  const sA = await (async () => { const u = { ...A, no: A.no + 'a' }; await apiRegister(u); return apiLogin(u) })()
  const sB = await (async () => { const u = { ...B, no: B.no + 'b' }; await apiRegister(u); return apiLogin(u) })()
  console.log(`  账号：C=${sC.user.id} A=${sA.user.id} B=${sB.user.id}`)

  // ---------- ② 发局（UI：校外 + 自由输入 + 最低水平）----------
  const ctxC = await ctxAs(browser, sC)
  const pC = await ctxC.newPage()
  const start = new Date(Date.now() + 8 * 60 * 1000)
  const end = new Date(Date.now() + 2 * 3600 * 1000)
  let gameId = null
  try {
    await pC.goto(`${BASE}/create`, { waitUntil: 'networkidle' })
    await pC.waitForTimeout(900)
    await pC.locator('input[placeholder*="球局标题"]').fill(`月球羽毛球双打 ${S}`)
    await pC.locator('.el-form-item:has-text("校区") .el-select').first().click()
    await pC.waitForTimeout(300)
    await pC.locator('.el-select-dropdown__item', { hasText: '校外' }).first().click()
    await pC.waitForTimeout(300)
    await pC.locator('input[placeholder*="校外球馆名称"]').fill('月球体育中心 2 号羽毛球馆')
    await shot(pC, 'create-offcampus', '← 选「校外」→ 场地变为自由输入')
    const dt = pC.locator('.el-date-editor input')
    await dt.nth(0).click(); await dt.nth(0).fill(fmt(start)); await dt.nth(0).press('Enter')
    await pC.waitForTimeout(250)
    await dt.nth(1).click(); await dt.nth(1).fill(fmt(end)); await dt.nth(1).press('Enter')
    await pC.waitForTimeout(250)
    await pC.locator('.el-form-item:has-text("最低水平要求") .el-select').first().click()
    await pC.waitForTimeout(350)
    await shot(pC, 'create-min-skill-options', '← 最低水平要求：不限/初级/中级/高级/大神')
    await pC.locator('.el-select-dropdown__item', { hasText: '初级' }).first().click()
    await pC.getByRole('button', { name: /发布球局/ }).click()
    await pC.waitForTimeout(3500)
    await shot(pC, 'create-result', '← 发布结果（创办人自动占 1 席）')
    gameId = Number(pC.url().split('/').pop())
    console.log('  球局 id =', gameId)
  } catch (e) {
    await shot(pC, 'error-create', '← ' + String(e).slice(0, 70))
  }

  // 兜底：UI 发局失败则用 API 建局，保证后续流程能跑
  if (!gameId || Number.isNaN(gameId)) {
    const g = await api('/game', {
      sport_type: 3, title: `月球羽毛球双打 ${S}`, campus: '新校区', venue_name: '新校区风雨操场 1 号场',
      start_time: fmt(start).replace(' ', 'T'), end_time: fmt(end).replace(' ', 'T'),
      max_players: 6, min_players: 2, skill_level_limit: 2
    }, sC.token)
    gameId = g.data.id
    console.log('  （UI 发局失败，已用 API 建局）id =', gameId)
  }

  // ---------- ③ 报名：水平必填 ----------
  const ctxA = await ctxAs(browser, sA)
  const pA = await ctxA.newPage()
  try {
    await pA.goto(`${BASE}/games/${gameId}`, { waitUntil: 'networkidle' })
    await pA.waitForTimeout(1500)
    await shot(pA, 'game-detail', '← 球局详情（校外场地 + 最低水平要求）')
    await pA.getByRole('button', { name: /加入球局/ }).first().click()
    await pA.waitForTimeout(700)
    await shot(pA, 'signup-dialog-required', '← 报名弹窗：水平必填')
    await pA.getByRole('button', { name: /确认报名/ }).click()
    await pA.waitForTimeout(1000)
    await shot(pA, 'signup-blocked-no-skill', '← 未选水平 → 被拒（不填不能报名）')
    await pA.locator('.join-skill .el-radio-button', { hasText: '高级' }).first().click()
    await pA.waitForTimeout(200)
    await pA.getByRole('button', { name: /确认报名/ }).click()
    await pA.waitForTimeout(2500)
    await shot(pA, 'signup-A-success', '← A 报名成功（自评高级，满足最低「初级」）')
  } catch (e) {
    await shot(pA, 'error-signupA', '← ' + String(e).slice(0, 70))
  }

  const ctxB = await ctxAs(browser, sB)
  const pB = await ctxB.newPage()
  try {
    await pB.goto(`${BASE}/games/${gameId}`, { waitUntil: 'networkidle' })
    await pB.waitForTimeout(900)
    await pB.getByRole('button', { name: /加入球局/ }).first().click()
    await pB.waitForTimeout(600)
    await pB.locator('.join-skill .el-radio-button', { hasText: '初级' }).first().click()
    await pB.getByRole('button', { name: /确认报名/ }).click()
    await pB.waitForTimeout(2500)
    await shot(pB, 'signup-B-success', '← B 报名成功（自评初级）')
  } catch (e) {
    await shot(pB, 'error-signupB', '← ' + String(e).slice(0, 70))
  }

  // ---------- ④ 核销（只核销 C 与 A，B 留作缺席）----------
  try {
    await pC.goto(`${BASE}/verify/${gameId}`, { waitUntil: 'networkidle' })
    await pC.waitForTimeout(1800)
    await shot(pC, 'verify-roster', '← 核销名单：每人显示水平 + 信誉分')
    const boxes = pC.locator('.verify__row .el-checkbox')
    await boxes.nth(0).click(); await boxes.nth(1).click()
    await pC.waitForTimeout(300)
    await shot(pC, 'verify-selected', '← 勾选发起人 + A（B 故意不核销）')
    await pC.getByRole('button', { name: /核销勾选/ }).click()
    await pC.waitForTimeout(3500)
    await shot(pC, 'verify-result', '← 核销结果：信誉分 +2（惰性结算）')
  } catch (e) {
    await shot(pC, 'error-verify', '← ' + String(e).slice(0, 70))
  }

  // ---------- ⑤ 结束球局 → 缺席判定 ----------
  try {
    await pC.goto(`${BASE}/games/${gameId}`, { waitUntil: 'networkidle' })
    await pC.waitForTimeout(1200)
    await pC.getByRole('button', { name: /结束球局/ }).first().click()
    await pC.waitForTimeout(900)
    await shot(pC, 'finish-confirm', '← 二次确认：缺席将扣 10 分并禁赛')
    await pC.getByRole('button', { name: /确认结束/ }).click()
    await pC.waitForTimeout(3500)
    await shot(pC, 'finish-done', '← 球局结束，B 被判缺席 -10 分')
  } catch (e) {
    await shot(pC, 'error-finish', '← ' + String(e).slice(0, 70))
  }

  // ---------- ⑥ B 被小黑屋拦截 ----------
  try {
    await pB.goto(`${BASE}/games/${gameId}`, { waitUntil: 'networkidle' })
    await pB.waitForTimeout(1000)
    await shot(pB, 'ban-detail-visible', '← 被封禁用户仍可浏览球局（查询不被拦）')
    const joinBtn = pB.getByRole('button', { name: /加入球局|候补|已报名/ }).first()
    await joinBtn.click().catch(() => {})
    await pB.waitForTimeout(600)
    const radio = pB.locator('.join-skill .el-radio-button', { hasText: '中级' }).first()
    if (await radio.count()) { await radio.click(); await pB.getByRole('button', { name: /确认报名/ }).click() }
    await pB.waitForTimeout(3000)
    await shot(pB, 'ban-403-dialog', '← 403 小黑屋弹窗：禁赛文案 + 解禁时间')
  } catch (e) {
    await shot(pB, 'error-ban', '← ' + String(e).slice(0, 70))
  }

  // ---------- ⑦ 个人主页 ----------
  try {
    await pB.goto(`${BASE}/me`, { waitUntil: 'networkidle' })
    await pB.waitForTimeout(2500)
    await shot(pB, 'profile-B-banned-banner', '← B 个人主页：红色禁赛横幅 + 解禁倒计时')
    await pB.locator('.how__head').first().click()
    await pB.waitForTimeout(800)
    await shot(pB, 'profile-B-breakdown', '← 信誉分怎么来的 + 常打项目')
  } catch (e) {
    await shot(pB, 'error-profileB', '← ' + String(e).slice(0, 70))
  }
  try {
    await pA.goto(`${BASE}/me`, { waitUntil: 'networkidle' })
    await pA.waitForTimeout(2500)
    await shot(pA, 'profile-A-credit', '← A：签到 +2 后的信誉分 + 最近自评水平')
  } catch (e) {
    await shot(pA, 'error-profileA', '← ' + String(e).slice(0, 70))
  }

  // ---------- ⑧ 手机端 ----------
  const mctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2, locale: 'zh-CN' })
  await mctx.addInitScript((x) => { localStorage.setItem('mq_token', x.token); localStorage.setItem('mq_user', JSON.stringify(x.user)) }, sA)
  const pm = await mctx.newPage()
  await pm.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await pm.waitForTimeout(1800)
  await shot(pm, 'mobile-home', '← 手机端首页（2 列球类 + 底部导航）')

  writeFileSync(`${OUT}step-log-final.txt`, `球局id=${gameId}\n账号 C/A/B = ${C.no}/${A.no}/${B.no}\n\n` + log.join('\n'), 'utf-8')
  console.log(`\n完成：${log.length} 张截图 → ${OUT}`)
  await browser.close()
}

main().catch((e) => { console.error('整体失败：', String(e).slice(0, 300)); process.exit(1) })
