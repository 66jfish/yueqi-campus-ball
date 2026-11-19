/**
 * 内置 Mock 适配器（纯前端演示模式）
 * ---------------------------------------------------------------------------
 * 作用：不启动后端也能完整预览/截图所有页面（VITE_USE_MOCK=true 时启用）。
 * 联调与上线请把 .env 里的 VITE_USE_MOCK 设为 false，走真实接口。
 *
 * 它是一个「axios adapter」，因此拦截层（JWT / 401 / 403 小黑屋弹窗 / Toast）
 * 与真实环境完全一致，可以直接验证交互。
 */

export const USE_MOCK = String(import.meta.env.VITE_USE_MOCK || 'false') === 'true'

/** 演示用可变状态：个人主页上的「模拟解禁 / 模拟禁赛」按钮会改这里 */
export const mockState = {
  banActive: true,
  user: {
    id: 2,
    student_no: '20230001',
    nickname: '球场小王子',
    avatar_url: null,
    campus: '老校区',
    college: '计算机学院',
    grade: '2023',
    gender: 1,
    skill_level: 4,
    reputation_score: 88,
    credit_score: 88,
    credit_level: 3,
    total_game_count: 12,
    absent_count: 2,
    status: 1,
    created_at: '2026-09-01T10:00:00'
  }
}

const LEVEL_TEXT = { 1: '黑名单', 2: '观察中', 3: '正常', 4: '优秀', 5: '金牌球友' }

const SPORTS = {
  1: { name: '篮球', cat: '乌头', color: '#9CC9E3' },
  2: { name: '足球', cat: '豆花', color: '#8EC5A7' },
  3: { name: '羽毛球', cat: '齐刘海', color: '#8EC5A7' },
  4: { name: '网球', cat: '白芷', color: '#DBC48E' },
  5: { name: '排球', cat: '小橘', color: '#ECBFC7' },
  6: { name: '乒乓球', cat: '芝麻', color: '#C6B6E0' }
}

function hoursFromNow(h, m = 0) {
  const d = new Date()
  d.setHours(d.getHours() + h, m, 0, 0)
  return d.toISOString().slice(0, 16)
}

function buildGame(i, sport, opts = {}) {
  const max = opts.max ?? 8
  const cur = opts.cur ?? 5
  return {
    id: 100 + i,
    creator_id: 1,
    creator_nickname: opts.creator || '球场小王子',
    creator_credit_score: 100,
    sport_type: sport,
    title: opts.title || `${SPORTS[sport].name} · ${opts.mode || '野球局'}`,
    description: opts.description || '水平不限，重在参与，请自备球鞋与水。',
    campus: opts.campus || '老校区',
    venue_name: opts.venue || '老校区体育馆 3 号场',
    venue_address: '老校区体育馆一层',
    start_time: opts.start || hoursFromNow(2),
    end_time: opts.end || hoursFromNow(4),
    signup_deadline: opts.deadline || hoursFromNow(1),
    checkin_start_time: hoursFromNow(-1),
    checkin_end_time: hoursFromNow(3),
    max_players: max,
    min_players: 2,
    current_players: cur,
    fee_type: opts.fee ? 1 : 0,
    fee_amount: opts.fee ?? null,
    skill_level_limit: opts.skill ?? 0,
    gender_limit: opts.gender ?? 0,
    min_credit_score: opts.minCredit ?? 0,
    status: opts.status ?? 1,
    settle_status: opts.settle ?? 0,
    created_at: '2026-11-01T10:00:00',
    waitlist_count: opts.waitlist ?? 0,
    slots_left: Math.max(0, max - cur),
    is_full: cur >= max,
    match_score: opts.match ?? 92.0,
    match_reason: opts.reason || '信誉分 88、球技符合要求、常玩该球类',
    my_registration_status: opts.myReg ?? null,
    my_checkin_status: opts.myCheckin ?? null
  }
}

const GAMES = [
  buildGame(1, 3, { title: '羽毛球 · 双打', mode: '双打', venue: '新校区新校区风雨操场', cur: 2, max: 4, fee: 8, gender: 2, match: 96, reason: '常玩该球类、女生友好', start: hoursFromNow(1) }),
  buildGame(2, 1, { title: '篮球 · 半场 3v3', mode: '半场3v3', venue: '老校区篮球场2号', cur: 5, max: 6, skill: 3, match: 90, reason: '球技符合要求', start: hoursFromNow(3) }),
  buildGame(3, 5, { title: '排球 · 沙滩排球', mode: '沙滩排球', venue: '新校区沙排场', cur: 6, max: 8, fee: 5, match: 84, start: hoursFromNow(5) }),
  buildGame(4, 4, { title: '网球 · 单打约练', mode: '单打', venue: '新校区网球场1号', cur: 1, max: 2, fee: 12, skill: 4, match: 78, start: hoursFromNow(26) }),
  buildGame(5, 2, { title: '足球 · 五人制', mode: '五人制', venue: '新校区人工草场', cur: 8, max: 10, fee: 10, match: 86, start: hoursFromNow(28) }),
  buildGame(6, 6, { title: '乒乓球 · 休闲对练', mode: '对练', venue: '体育馆乒乓室', cur: 2, max: 4, match: 95, start: hoursFromNow(30) }),
  buildGame(7, 3, { title: '羽毛球 · 新手场', mode: '新手场', venue: '新校区新校区风雨操场', cur: 4, max: 4, skill: 1, match: 88, isFull: true, start: hoursFromNow(52) }),
  buildGame(8, 1, { title: '篮球 · 全场 5v5', mode: '全场5v5', venue: '老校区篮球场1号', cur: 7, max: 10, skill: 3, minCredit: 80, match: 82, start: hoursFromNow(54) })
]

/* ------------------------------------------------------------------ 画像 */
const PROFILE = {
  user_id: 2,
  score: 93,
  rule_score: 88,
  ai_score: 105,
  ai_adjust: 5,
  reputation_score: 88,
  score_gap: 5,
  credit_level: 3,
  credit_level_text: '正常',
  risk_level: 'medium',
  tags: ['有过缺席', '稳定参与', '高水平选手'],
  summary: '累计到场 9 次、迟到 1 次、缺席 2 次、退出 1 次，守约率 75%。',
  suggestions: [
    '报名后请按时到场；确实来不了请提前请假，避免扣除信誉分并被禁赛。',
    '尽量不要在开球前 2 小时内退出，便于组织者补位。'
  ],
  source: 'rule',
  degraded: true,
  trigger: 'absent',
  version: 4,
  cached: false,
  generated_at: new Date().toISOString(),
  features: {
    checked_count: 9, late_count: 1, leave_count: 1, absent_count: 2,
    signup_total: 14, cancel_early_count: 1, cancel_late_count: 0,
    keep_rate: 0.75, absent_rate: 0.167, late_rate: 0.083, cancel_rate: 0.071
  },
  breakdown: [
    { item: '按时签到', count: 9, weight: 2, subtotal: 18 },
    { item: '迟到签到', count: 1, weight: -3, subtotal: -3 },
    { item: '已请假', count: 1, weight: 0, subtotal: 0 },
    { item: '无故缺席', count: 2, weight: -10, subtotal: -20 },
    { item: '主动退出', count: 1, weight: -2, subtotal: -2 },
    { item: '临近开球退出(≤2h)', count: 0, weight: -4, subtotal: 0 }
  ]
}

function banPayload() {
  const end = new Date(Date.now() + 46 * 3600 * 1000) // 剩余 46 小时
  return {
    banned: true,
    ban_end_time: end.toISOString(),
    remaining_hours: 46,
    ban_start_time: new Date(Date.now() - 26 * 3600 * 1000).toISOString(),
    ban_duration_days: 3,
    ban_extend_count: 0,
    reason: '缺席球局（未签到且未请假），球局ID=101',
    reason_type: 1,
    blocked_actions: ['发起球局（POST /api/v1/game）', '报名加入球局（POST /api/v1/game/{id}/signup）'],
    message: '您因放鸽子被禁赛，将于 ' + end.toLocaleString('zh-CN', { hour12: false }).slice(0, 16) + ' 解除',
    history: [
      {
        id: 1,
        user_id: 2,
        ban_start_time: new Date(Date.now() - 26 * 3600 * 1000).toISOString(),
        ban_duration_days: 3,
        ban_end_time: end.toISOString(),
        status: 1,
        reason_type: 1,
        reason: '缺席球局（未签到且未请假），球局ID=101',
        trigger_game_id: 101,
        credit_score_at_ban: 88,
        ban_extend_count: 0,
        ban_original_end_time: null,
        ban_last_extend_at: null,
        is_active: true,
        created_at: new Date(Date.now() - 26 * 3600 * 1000).toISOString()
      }
    ],
    total_ban_count: 1
  }
}

/* ------------------------------------------------------------------ 适配器 */
function ok(config, data) {
  return { data, status: 200, statusText: 'OK', headers: {}, config }
}
function httpError(config, status, body) {
  const err = new Error(body.message || 'request failed')
  err.isAxiosError = true
  err.config = config
  err.response = { data: body, status, statusText: 'Error', headers: {}, config }
  return err
}

const ROSTER = {
  game_id: 101,
  title: '羽毛球 · 双打',
  status: 3,
  settle_status: 0,
  start_time: hoursFromNow(1),
  checkin_open_at: hoursFromNow(-1),
  checkin_close_at: hoursFromNow(3),
  checkin_open: true,
  signed_count: 4,
  checked_count: 1,
  late_count: 0,
  absent_count: 0,
  not_checked_count: 3,
  waitlist_count: 1,
  members: [
    { user_id: 2, nickname: '球场小王子', avatar_url: null, credit_score: 88, skill_level: 4, skill_level_text: '高级', registration_status: 1, is_waitlist: 0, checkin_status: 1, checkin_status_text: '已签到', checkin_time: hoursFromNow(0), credit_delta: 2, settled: 1 },
    { user_id: 3, nickname: '齐刘海的粉丝', avatar_url: null, credit_score: 102, skill_level: 3, skill_level_text: '中级', registration_status: 1, is_waitlist: 0, checkin_status: 0, checkin_status_text: '未签到', checkin_time: null, credit_delta: 0, settled: 0 },
    { user_id: 4, nickname: '羽毛球爱好者', avatar_url: null, credit_score: 95, skill_level: 2, skill_level_text: '初级', registration_status: 1, is_waitlist: 0, checkin_status: 0, checkin_status_text: '未签到', checkin_time: null, credit_delta: 0, settled: 0 },
    { user_id: 5, nickname: '迟到侠', avatar_url: null, credit_score: 76, skill_level: 1, skill_level_text: '新手', registration_status: 1, is_waitlist: 0, checkin_status: 0, checkin_status_text: '未签到', checkin_time: null, credit_delta: 0, settled: 0 }
  ]
}

export async function mockAdapter(config) {
  await new Promise((r) => setTimeout(r, 160)) // 模拟网络延迟，便于观察 loading 态
  const url = (config.url || '').replace(/^https?:\/\/[^/]+/, '')
  const method = (config.method || 'get').toLowerCase()
  const params = config.params || {}
  const body = (() => {
    try {
      return config.data ? JSON.parse(config.data) : {}
    } catch {
      return {}
    }
  })()

  /* ---- 认证 ---- */
  if (url.endsWith('/auth/login') && method === 'post') {
    if (body.password === 'wrong') {
      return Promise.reject(httpError(config, 400, { code: 40000, message: '账号或密码错误', data: null }))
    }
    return ok(config, {
      code: 0,
      message: '登录成功',
      data: {
        token: {
          access_token: 'mock.jwt.token',
          refresh_token: 'mock.refresh.token',
          token_type: 'bearer',
          expires_in: 604800
        },
        user: mockState.user
      }
    })
  }
  if (url.endsWith('/auth/register') && method === 'post') {
    return ok(config, { code: 0, message: '注册成功', data: mockState.user })
  }
  if (url.endsWith('/auth/logout')) {
    return ok(config, { code: 0, message: '已退出登录', data: { logout: true, user_id: 2 } })
  }
  if (url.endsWith('/auth/token-info')) {
    return ok(config, { code: 0, message: 'ok', data: { user_id: '2', jti: 'mock', type: 'access', expires_in: 604230, need_refresh: false } })
  }

  /* ---- 用户 ---- */
  if (url.endsWith('/user/me') && method === 'get') {
    return ok(config, { code: 0, message: 'ok', data: { ...mockState.user, ai_profile: PROFILE, ai_score: PROFILE.score, ai_profile_source: 'rule', ai_profile_dirty: 0 } })
  }
  if (url.endsWith('/user/me/credit')) {
    return ok(config, { code: 0, message: 'ok', data: { reputation_score: 88, credit_score: 88, credit_level: 3, pending_settle_count: 0, banned: mockState.banActive, ban_end_time: mockState.banActive ? banPayload().ban_end_time : null, ban_extend_count: 0 } })
  }
  if (url.includes('/user/me/credit/history')) {
    return ok(config, {
      code: 0,
      message: 'ok',
      data: [
        { checkin_record_id: 31, game_id: 101, checkin_status: 1, credit_delta: 2, settled_at: hoursFromNow(-2) },
        { checkin_record_id: 28, game_id: 96, checkin_status: 3, credit_delta: -10, settled_at: hoursFromNow(-30) },
        { checkin_record_id: 24, game_id: 90, checkin_status: 2, credit_delta: -3, settled_at: hoursFromNow(-72) }
      ]
    })
  }
  const profilePageMatch = url.match(/\/user\/(\d+)\/profile$/)
  if (profilePageMatch) {
    const isSelf = profilePageMatch[1] === '2'
    return ok(config, {
      code: 0,
      message: 'ok',
      data: {
        user_id: Number(profilePageMatch[1]),
        nickname: isSelf ? mockState.user.nickname : '白芷的粉丝',
        avatar_url: null,
        campus: '老校区',
        college: '计算机学院',
        gender: isSelf ? 1 : 2,
        skill_level: 4,
        reputation_score: 88,
        credit_score: 88,
        credit_level: 3,
        credit_level_text: LEVEL_TEXT[3],
        profile_score: PROFILE.score,
        tags: PROFILE.tags,
        summary: PROFILE.summary,
        profile_source: 'rule',
        profile_degraded: true,
        breakdown: PROFILE.breakdown,
        attended_count: 9,
        late_count: 1,
        absent_count: 2,
        favorite_sports: [
          { sport_type: 3, name: '羽毛球', count: 7, ratio: 0.58 },
          { sport_type: 1, name: '篮球', count: 3, ratio: 0.25 },
          { sport_type: 5, name: '排球', count: 2, ratio: 0.17 }
        ],
        latest_skill_level: 3,
        latest_skill_level_text: '中级',
        latest_skill_sport: '羽毛球',
        cancel_count: 1,
        keep_rate: 0.75,
        joined_game_count: 12,
        created_game_count: 3,
        banned: isSelf ? mockState.banActive : false,
        ban_end_time: isSelf && mockState.banActive ? banPayload().ban_end_time : null,
        registered_at: '2026-09-01T10:00:00',
        is_self: isSelf
      }
    })
  }

  /* ---- AI 画像 ---- */
  if (url.includes('/ai/profile')) {
    return ok(config, { code: 0, message: '画像已更新', data: PROFILE })
  }
  if (url.includes('/ai/explain')) {
    return ok(config, {
      code: 0,
      message: 'ok',
      data: {
        score_range: [0, 150],
        base_score: 100,
        weights: { checked: 2, late: -3, absent: -10, leave: 0, cancel_early: -2, cancel_late: -4 },
        weight_desc: {
          checked: '按时签到（到场）：+2/次',
          late: '迟到签到：-3/次',
          absent: '无故缺席（未签到未请假）：-10/次（大幅扣分）',
          leave: '已请假：0（提前告知不惩罚）',
          cancel_early: '主动退出（距开球 > 阈值）：-2/次（少量扣分）',
          cancel_late: '临近开球退出（≤2h）：-4/次'
        },
        formula: '画像分 = clamp(初始分100 + 2×按时签到 - 3×迟到 - 10×无故缺席 - 2×主动退出 - 4×临期退出 + 守约加成, 0, 150)',
        keep_rate_bonus: '完成 ≥5 场且守约率 ≥95% 时额外 +3 分',
        fusion: { ai_weight: 0.3, rule_weight: 0.7, max_adjust: 8, description: '最终分 = 0.3×AI建议分 + 0.7×本地加权分，且调整幅度 ≤ ±8' },
        degrade_policy: '未配置 DEEPSEEK_API_KEY 或调用异常时自动使用本地加权规则版',
        trigger_policy: '签到/缺席/退出结算后置 dirty，后台每 600s 兜底重算',
        match_score_formula: { base: 60, reputation: '20×(画像分/150)', skill: '12×max(0,1-差距/5)', preference: '8×球类占比', penalty_full: -5, conflict: '冲突置 0' },
        source_priority: ['deepseek', 'rule(本地加权规则降级)']
      }
    })
  }
  if (url.includes('/ai/stats')) {
    return ok(config, { code: 0, message: 'ok', data: { llm_available: false, enabled: true, dirty_count: 0, profiled_users: 3, source_distribution: { deepseek: 0, rule: 3 }, match_score_enabled: true } })
  }

  /* ---- 小黑屋 ---- */
  if (url.includes('/blacklist/me')) {
    return ok(config, {
      code: 0,
      message: 'ok',
      data: mockState.banActive ? banPayload() : { banned: false, ban_end_time: null, remaining_hours: null, blocked_actions: [], message: '您当前没有封禁记录，可正常参与球局', history: [], total_ban_count: 1 }
    })
  }
  if (url.includes('/blacklist/records')) {
    return ok(config, { code: 0, message: 'ok', data: { items: banPayload().history, total: 1, page: 1, page_size: 20, pages: 1 } })
  }
  if (url.includes('/blacklist/config')) {
    return ok(config, { code: 0, message: 'ok', data: { ban_days: 3, ban_on_absent: true, extend_on_repeat: true, max_total_days: 30, block_all_writes: false, absent_deduct_score: 10, lazy_release: true } })
  }

  /* ---- 球局 ---- */
  if (url.endsWith('/game') && method === 'post') {
    if (mockState.banActive) {
      const p = banPayload()
      return Promise.reject(httpError(config, 403, { code: 403, msg: p.message, message: p.message, data: { banned: true, ban_end_time: p.ban_end_time, ban_duration_days: 3, ban_extend_count: 0, reason: p.reason, reason_type: 1 } }))
    }
    return ok(config, { code: 0, message: '球局创建成功', data: { ...GAMES[0], id: 200, title: body.title || '新球局', current_players: 1, slots_left: (body.max_players || 8) - 1, max_players: body.max_players || 8 } })
  }
  if (url.endsWith('/game') && method === 'get') {
    let list = [...GAMES]
    if (params.sport_type) list = list.filter((g) => g.sport_type === Number(params.sport_type))
    if (params.campus) list = list.filter((g) => g.campus === params.campus)
    if (params.keyword) list = list.filter((g) => g.title.includes(params.keyword))
    if (params.status) list = list.filter((g) => g.status === Number(params.status))
    if (params.only_available) list = list.filter((g) => !g.is_full && g.status === 1)
    const page = Number(params.page || 1)
    const size = Number(params.page_size || 10)
    const total = list.length
    const items = list.slice((page - 1) * size, page * size)
    return ok(config, { code: 0, message: 'ok', data: { list: items, total, page, page_size: size, pages: Math.ceil(total / size) } })
  }
  const detailMatch = url.match(/\/game\/(\d+)$/)
  if (detailMatch && method === 'get') {
    const g = GAMES.find((x) => x.id === Number(detailMatch[1])) || GAMES[0]
    return ok(config, { code: 0, message: 'ok', data: { ...g, checked_count: 1, late_count: 0, absent_count: 0, not_checked_count: 3, is_creator: g.creator_id === 2 } })
  }
  const signupMatch = url.match(/\/game\/(\d+)\/signup$/)
  if (signupMatch && method === 'post') {
    if (mockState.banActive) {
      const p = banPayload()
      return Promise.reject(httpError(config, 403, { code: 403, msg: p.message, message: p.message, data: { banned: true, ban_end_time: p.ban_end_time, ban_duration_days: 3, ban_extend_count: 0, reason: p.reason, reason_type: 1 } }))
    }
    const g = GAMES.find((x) => x.id === Number(signupMatch[1])) || GAMES[0]
    const SKILL_TEXT = { 1: '新手', 2: '初级', 3: '中级', 4: '高级', 5: '大神' }
    if (!body.skill_level) {
      return Promise.reject(httpError(config, 400, { code: 40000, message: '请先选择你在该球类的水平（新手/初级/中级/高级/大神）后再报名', data: null }))
    }
    if (g.skill_level_limit && body.skill_level < g.skill_level_limit) {
      return Promise.reject(httpError(config, 409, { code: 40900, message: `该球局最低水平要求为「${SKILL_TEXT[g.skill_level_limit]}」，您自评「${SKILL_TEXT[body.skill_level]}」，暂不达标，无法报名`, data: null }))
    }
    return ok(config, { code: 0, message: '报名成功（' + (g.current_players + 1) + '/' + g.max_players + '）', data: { registration: { id: 9, game_id: g.id, user_id: 2, status: 1, is_waitlist: 0, waitlist_order: 0, signup_time: new Date().toISOString(), credit_snapshot: 88, skill_level: body.skill_level, skill_level_text: SKILL_TEXT[body.skill_level] }, is_waitlist: false, current_players: g.current_players + 1, message: '报名成功' } })
  }
  const exitMatch = url.match(/\/game\/(\d+)\/exit$/)
  if (exitMatch && method === 'post') {
    return ok(config, { code: 0, message: '已退出球局，已自动通知候补球友补位', data: { registration: { id: 9, game_id: Number(exitMatch[1]), user_id: 2, status: 2, is_waitlist: 0, waitlist_order: 0 }, promoted_user_id: 7, current_players: 4, message: '已退出球局，已自动通知候补球友补位' } })
  }
  const finishMatch = url.match(/\/game\/(\d+)\/finish$/)
  if (finishMatch && method === 'post') {
    return ok(config, { code: 0, message: '球局已结束，判定缺席 2 人', data: { game_id: Number(finishMatch[1]), status: 4, absent_count: 2, settled_users: [] } })
  }
  const membersMatch = url.match(/\/game\/(\d+)\/members$/)
  if (membersMatch) {
    return ok(config, {
      code: 0,
      message: 'ok',
      data: ROSTER.members.map((m) => ({ user_id: m.user_id, nickname: m.nickname, avatar_url: null, status: m.registration_status, is_waitlist: m.is_waitlist, waitlist_order: m.is_waitlist ? 1 : 0, signup_time: hoursFromNow(-20), credit_score: m.credit_score }))
    })
  }

  /* ---- 签到 / 核销 ---- */
  const rosterMatch = url.match(/\/checkin\/game\/(\d+)$/)
  if (rosterMatch) return ok(config, { code: 0, message: 'ok', data: { ...ROSTER, game_id: Number(rosterMatch[1]) } })
  if (url.includes('/checkin/verify')) {
    const ids = body.user_ids || [3, 4]
    const items = ids.map((uid, i) => {
      const member = ROSTER.members.find((m) => m.user_id === uid)
      return {
        user_id: uid,
        nickname: member?.nickname || `用户${uid}`,
        ok: true,
        skipped: false,
        reason: null,
        checkin_status: 1,
        checkin_status_text: '已签到',
        credit_before: member?.credit_score ?? 90,
        credit_delta: 2,
        credit_after: (member?.credit_score ?? 90) + 2,
        banned: false,
        ban_end_time: null
      }
    })
    return ok(config, { code: 0, message: `核销完成：成功 ${items.length} 人`, data: { game_id: body.game_id || 101, verified_count: items.length, skipped_count: 0, failed_count: 0, checkin_open_at: hoursFromNow(-1), checkin_close_at: hoursFromNow(3), items } })
  }
  if (url.includes('/checkin/checkin')) {
    return ok(config, { code: 0, message: '签到成功', data: { success: true, message: '签到成功', user_id: 2, credit_before: 88, credit_delta: 2, credit_after: 90, credit_level: 3, settled_record_count: 1, banned: false, ban_end_time: null } })
  }
  if (url.includes('/checkin/leave')) {
    return ok(config, { code: 0, message: '已提交请假', data: { success: true, message: '已提交请假', user_id: 2, credit_delta: 0, settled_record_count: 1 } })
  }
  if (url.includes('/checkin/absent-judgement')) {
    return ok(config, { code: 0, message: '缺席判定完成', data: { game_id: body.game_id || 101, absent_count: 1, settled_users: [], message: '判定完成' } })
  }
  if (url.includes('/checkin/my')) {
    return ok(config, {
      code: 0,
      message: 'ok',
      data: [
        { id: 31, game_id: 101, user_id: 2, checkin_status: 1, checkin_type: 1, checkin_time: hoursFromNow(-1), credit_delta: 2, settled: 1, settled_at: hoursFromNow(-1) },
        { id: 28, game_id: 96, user_id: 2, checkin_status: 3, checkin_type: null, checkin_time: null, credit_delta: -10, settled: 1, settled_at: hoursFromNow(-30) },
        { id: 33, game_id: 105, user_id: 2, checkin_status: 0, checkin_type: null, checkin_time: null, credit_delta: 0, settled: 0, settled_at: null }
      ]
    })
  }

  // 未覆盖的接口：返回空成功，避免演示时页面报错
  return ok(config, { code: 0, message: 'ok（mock 未实现该接口）', data: {} })
}

export { SPORTS, GAMES, PROFILE }
