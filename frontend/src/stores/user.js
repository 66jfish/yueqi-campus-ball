/**
 * 用户状态（Pinia）
 * ---------------------------------------------------------------------------
 * 统一持有：token / 当前用户 / AI 画像 / 小黑屋状态
 * 小黑屋状态在登录后与每次进入个人主页时刷新，供全站横幅与拦截提示复用
 */
import { defineStore } from 'pinia'
import { authApi, userApi, aiApi, blacklistApi } from '@/api'

const LEVEL_TEXT = { 1: '黑名单', 2: '观察中', 3: '正常', 4: '优秀', 5: '金牌球友' }
const LEVEL_TYPE = { 1: 'danger', 2: 'warning', 3: 'info', 4: 'success', 5: 'success' }

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('mq_token') || '',
    refreshToken: localStorage.getItem('mq_refresh_token') || '',
    user: JSON.parse(localStorage.getItem('mq_user') || 'null'),
    profile: null,       // AI 画像（含 tags / score / breakdown）
    ban: null,           // 小黑屋状态
    loading: false
  }),

  getters: {
    isLoggedIn: (s) => Boolean(s.token),
    displayName: (s) => s.user?.nickname || '未登录',
    creditScore: (s) => s.user?.reputation_score ?? s.user?.credit_score ?? 100,
    levelText: (s) => LEVEL_TEXT[s.user?.credit_level || 3],
    levelType: (s) => LEVEL_TYPE[s.user?.credit_level || 3],
    isBanned: (s) => Boolean(s.ban?.banned),
    banEndTime: (s) => s.ban?.ban_end_time || null,
    tags: (s) => s.profile?.tags || s.user?.ai_profile?.tags || []
  },

  actions: {
    persist() {
      localStorage.setItem('mq_token', this.token || '')
      localStorage.setItem('mq_refresh_token', this.refreshToken || '')
      localStorage.setItem('mq_user', JSON.stringify(this.user || null))
    },

    async login(account, password) {
      const data = await authApi.login({ account, password })
      this.token = data.token.access_token
      this.refreshToken = data.token.refresh_token
      this.user = data.user
      this.persist()
      await this.loadExtras()
      return data
    },

    async register(payload) {
      return authApi.register(payload)
    },

    async logout() {
      try {
        await authApi.logout()
      } catch (e) {
        /* 登出接口幂等，失败也不影响本地清理 */
      }
      this.token = ''
      this.refreshToken = ''
      this.user = null
      this.profile = null
      this.ban = null
      this.persist()
    },

    async fetchMe() {
      if (!this.token) return null
      this.user = await userApi.me()
      this.persist()
      return this.user
    },

    /** 拉取 AI 画像 + 小黑屋状态（个人主页 & 全局横幅使用） */
    async loadExtras() {
      if (!this.token) return
      const tasks = [
        aiApi.profile().then((p) => (this.profile = p)).catch(() => {}),
        blacklistApi.myStatus().then((b) => (this.ban = b)).catch(() => {})
      ]
      await Promise.all(tasks)
    },

    async refreshProfile() {
      this.profile = await aiApi.refresh()
      return this.profile
    },

    async refreshBan() {
      this.ban = await blacklistApi.myStatus()
      return this.ban
    }
  }
})

export { LEVEL_TEXT, LEVEL_TYPE }
