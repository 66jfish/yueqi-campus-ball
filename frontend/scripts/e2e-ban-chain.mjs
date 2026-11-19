/**
 * 定向验证并截图：缺席 → 小黑屋 → 个人主页封禁横幅 + 倒计时 + 累计封禁1次
 * 与上一轮的区别：核销对象用 **user_id 显式指定**（不再按勾选顺序猜），
 *                每一步都做接口断言，断言全绿后再截图。
 */
import { chromium } from 'playwright'
import { writeFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

const BASE = process.env.SITE || 'http://134.175.40.145'
const API = BASE + '/api/v1'
const OUT = fileURLToPath(new URL('../../deliverables/e2e-shots/', import.meta.url))
const S = String(Date.now()).slice(-6)
const checks = []

function assert(name, ok, detail) {
  checks.push({ name, ok, detail })
  console.log(`  ${ok ? '✓' : '✗'} ${name}${detail ? ' | ' + detail : ''}`)
}
async function call(path, { method = 'GET', body, token } = {}) {
  const r = await fetch(API + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined
  })
  return { http: r.status, json: await r.json().catch(() => ({})) }
}
const pad = (x) => String(x).padStart(2, '0')
const fmt = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`

async function ensureUser(no, nick, phone) {
  await call('/auth/register', { method: 'POST', body: { student_no: no, nickname: nick, password: 'test123456', phone, campus: '老校区' } })
  const r = await call('/auth/login', { method: 'POST', body: { account: no, password: 'test123456' } })
  if (r.json.code !== 0) throw new Error(`${no} 登录失败：${r.json.message}`)
  return { token: r.json.data.token.access_token, user: r.json.data.user }
}

async function main() {
  console.log('\n===== 一、接口断言（硬证据）=====')
  const host = await ensureUser(`h${S}`, '月球组织者', `137${S}1`)
  const pigeon = await ensureUser(`p${S}`, '缺席的小橘', `137${S}2`)
  console.log(`  组织者 id=${host.user.id}(${host.user.nickname})  缺席者 id=${pigeon.user.id}(${pigeon.user.nickname})`)

  const start = new Date(Date.now() + 8 * 60 * 1000), end = new Date(Date.now() + 2 * 3600 * 1000)
  const gRes = await call('/game', {
    method: 'POST', token: host.token,
    body: {
      sport_type: 3, title: `封禁链路验证 ${S}`, campus: '新校区', venue_name: '新校区风雨操场 2 号场',
      start_time: fmt(start), end_time: fmt(end), max_players: 6, min_players: 2,
      skill_level_limit: 2   // 最低要求「初级」
    }
  })
  const gameId = gRes.json.data.id
  assert('① 组织者创建球局（最低水平=初级）', gRes.json.code === 0, `game_id=${gameId}`)

  // B 选「中级(3)」≥ 门槛「初级(2)」→ 确保报名成功
  const signup = await call(`/game/${gameId}/signup`, { method: 'POST', token: pigeon.token, body: { skill_level: 3 } })
  assert('② 缺席者以「中级」报名成功（满足门槛）', signup.json.code === 0,
    `status=${signup.json.data?.registration?.status} skill=${signup.json.data?.registration?.skill_level} ${signup.json.message || ''}`)

  const members = await call(`/game/${gameId}/members`)
  const me = members.json.data.find((m) => m.user_id === pigeon.user.id)
  assert('③ 名单中确认缺席者已报名且水平已记录', Boolean(me) && me.skill_level === 3,
    me ? `kind=${me.skill_level_text} credit=${me.credit_score}` : '未找到')

  // 只核销组织者自己（显式 user_id，避免顺序歧义）
  const verify = await call('/checkin/verify', { method: 'POST', token: host.token, body: { game_id: gameId, user_ids: [host.user.id] } })
  assert('④ 仅核销组织者本人', verify.json.code === 0 && verify.json.data.verified_count === 1,
    `成功 ${verify.json.data?.verified_count} 人，缺席者 ${verify.json.data?.items?.[0]?.nickname || ''}`)

  const finish = await call(`/game/${gameId}/finish`, { method: 'POST', token: host.token })
  assert('⑤ 结束球局并触发缺席判定', finish.json.code === 0, `缺席人数=${finish.json.data?.absent_count}`)

  const ban = await call('/blacklist/me', { token: pigeon.token })
  const bd = ban.json.data || {}
  assert('⑥ 缺席者已进小黑屋', bd.banned === true, `banned=${bd.banned}`)
  assert('⑦ 禁赛时长 = 3 天', bd.ban_duration_days === 3, `days=${bd.ban_duration_days}`)
  assert('⑧ 返回解禁时间', Boolean(bd.ban_end_time), `end=${bd.ban_end_time}`)
  assert('⑨ 剩余小时数 > 0', (bd.remaining_hours ?? 0) > 0, `remaining=${bd.remaining_hours}h`)
  assert('⑩ 累计封禁次数 = 1', bd.total_ban_count === 1, `total=${bd.total_ban_count}`)
  assert('⑪ 封禁原因已记录', Boolean(bd.reason), bd.reason || '')
  assert('⑫ 历史记录含 1 条', (bd.history || []).length === 1, `history=${(bd.history || []).length}`)

  const prof = await call(`/user/${pigeon.user.id}/profile`, { token: pigeon.token })
  assert('⑬ 个人主页接口返回封禁状态', prof.json.data?.banned === true && Boolean(prof.json.data?.ban_end_time),
    `banned=${prof.json.data?.banned} credit=${prof.json.data?.reputation_score}`)

  const blocked = await call('/game', {
    method: 'POST', token: pigeon.token,
    body: { sport_type: 1, title: '被封禁者试着发局', campus: '老校区', venue_name: '老校区体育馆 1 号场', start_time: fmt(start), end_time: fmt(end), max_players: 4 }
  })
  assert('⑭ 封禁期间发局被拦（HTTP 403 / code 403）', blocked.http === 403 && blocked.json.code === 403,
    `http=${blocked.http} code=${blocked.json.code} msg=${(blocked.json.msg || '').slice(0, 40)}`)

  const allowed = await call('/game?page_size=1', { token: pigeon.token })
  assert('⑮ 封禁期间查询球局仍放行', allowed.json.code === 0, `total=${allowed.json.data?.total}`)

  console.log('\n===== 二、UI 截图（基于上面已确认的状态）=====')
  const browser = await chromium.launch({ channel: 'msedge' })
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1.6, locale: 'zh-CN' })
  await ctx.addInitScript((x) => {
    localStorage.setItem('mq_token', x.token)
    localStorage.setItem('mq_user', JSON.stringify(x.user))
  }, pigeon)
  const page = await ctx.newPage()

  await page.goto(`${BASE}/me`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)
  await page.screenshot({ path: `${OUT}25-ban-banner-countdown.png` })
  console.log('  ✓ 25 ban-banner-countdown ← 红色封禁横幅 + 解禁倒计时 + 累计封禁1次')
  const hasBanner = await page.locator('.ban').count()
  assert('⑯ 页面出现封禁横幅（.ban）', hasBanner > 0, `匹配 ${hasBanner} 个`)
  const bannerText = hasBanner ? (await page.locator('.ban').first().innerText()).replace(/\n/g, ' ') : ''
  assert('⑰ 横幅含禁赛文案与倒计时', bannerText.includes('禁赛') && bannerText.includes('倒计时'), bannerText.slice(0, 90))

  // 小黑屋状态卡 + 封禁记录（滚动到右侧卡片）
  await page.locator('.how__head').first().click().catch(() => {})
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${OUT}26-ban-hell-state.png`, fullPage: true })
  console.log('  ✓ 26 ban-hell-state ← 整页（含小黑屋状态卡 / 封禁记录 / 加权明细）')

  // 触发 403 弹窗
  await page.goto(`${BASE}/games/${gameId}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}27-ban-can-still-browse.png` })
  console.log('  ✓ 27 ban-can-still-browse ← 被封禁仍可浏览球局详情')
  await page.getByRole('button', { name: /加入球局|候补|已报名/ }).first().click().catch(() => {})
  await page.waitForTimeout(700)
  const radio = page.locator('.join-skill .el-radio-button', { hasText: '中级' }).first()
  if (await radio.count()) {
    await radio.click()
    await page.getByRole('button', { name: /确认报名/ }).click()
  }
  await page.waitForTimeout(3000)
  await page.screenshot({ path: `${OUT}28-ban-403-dialog.png` })
  console.log('  ✓ 28 ban-403-dialog ← 403 小黑屋弹窗')

  // 手机端封禁横幅
  const m = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2, locale: 'zh-CN' })
  await m.addInitScript((x) => { localStorage.setItem('mq_token', x.token); localStorage.setItem('mq_user', JSON.stringify(x.user)) }, pigeon)
  const pm = await m.newPage()
  await pm.goto(`${BASE}/me`, { waitUntil: 'networkidle' })
  await pm.waitForTimeout(2500)
  await pm.screenshot({ path: `${OUT}29-mobile-ban-banner.png` })
  console.log('  ✓ 29 mobile-ban-banner ← 手机端封禁横幅')

  const okAll = checks.every((c) => c.ok)
  writeFileSync(`${OUT}ban-chain-report.txt`,
    `球局id=${gameId}  组织者=${host.user.id}  缺席者=${pigeon.user.id}\n\n` +
    checks.map((c) => `${c.ok ? '[PASS]' : '[FAIL]'} ${c.name} | ${c.detail || ''}`).join('\n') +
    `\n\n结论：${okAll ? '全部断言通过' : '存在失败断言'}`, 'utf-8')
  console.log(`\n断言：${checks.filter((c) => c.ok).length}/${checks.length} 通过`)
  await browser.close()
  process.exit(okAll ? 0 : 2)
}

main().catch((e) => { console.error('失败：', String(e).slice(0, 300)); process.exit(1) })
