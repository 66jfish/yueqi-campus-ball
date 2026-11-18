/**
 * 接口清单（与后端 docs/ 一一对应）
 * 统一从这里调用，页面里不出现裸 URL
 */
import request from './request'

/* =============================== 认证 =============================== */
export const authApi = {
  register: (data) => request.post('/auth/register', data),
  login: (data) => request.post('/auth/login', data),
  refresh: (refreshToken) => request.post('/auth/refresh', { refresh_token: refreshToken }),
  logout: () => request.post('/auth/logout'),
  tokenInfo: () => request.get('/auth/token-info')
}

/* =============================== 用户 =============================== */
export const userApi = {
  me: () => request.get('/user/me'),
  updateMe: (data) => request.put('/user/me', data),
  credit: () => request.get('/user/me/credit'),
  creditHistory: (limit = 20) => request.get('/user/me/credit/history', { params: { limit } }),
  profilePage: (userId) => request.get(`/user/${userId}/profile`)
}

/* =============================== 球局 =============================== */
export const gameApi = {
  create: (data) => request.post('/game', data),
  list: (params) => request.get('/game', { params }),
  detail: (id) => request.get(`/game/${id}`),
  signup: (id) => request.post(`/game/${id}/signup`),
  exit: (id, reason) => request.post(`/game/${id}/exit`, null, { params: reason ? { reason } : {} }),
  finish: (id) => request.post(`/game/${id}/finish`),
  members: (id, onlyFormal = false) => request.get(`/game/${id}/members`, { params: { only_formal: onlyFormal } })
}

/* =============================== 签到 / 核销 =============================== */
export const checkinApi = {
  /** 本人签到（扫码/定位打卡） */
  checkin: (data) => request.post('/checkin/checkin', data),
  leave: (data) => request.post('/checkin/leave', data),
  /** 发起人核销到场用户 */
  verify: (data) => request.post('/checkin/verify', data),
  /** 核销名单 */
  roster: (gameId) => request.get(`/checkin/game/${gameId}`),
  absentJudgement: (gameId) => request.post('/checkin/absent-judgement', { game_id: gameId, auto_prune: true }),
  myRecords: (limit = 20) => request.get('/checkin/my', { params: { limit } })
}

/* =============================== 小黑屋 =============================== */
export const blacklistApi = {
  myStatus: () => request.get('/blacklist/me'),
  records: (params) => request.get('/blacklist/records', { params }),
  config: () => request.get('/blacklist/config')
}

/* =============================== AI 信誉画像 =============================== */
export const aiApi = {
  profile: (force = false) => request.get('/ai/profile', { params: force ? { force: true } : {} }),
  refresh: () => request.post('/ai/profile/refresh', { force: true }),
  explain: () => request.get('/ai/explain'),
  stats: () => request.get('/ai/stats')
}
