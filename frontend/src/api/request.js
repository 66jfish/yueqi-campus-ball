/**
 * axios 封装（全局唯一出口）
 * ---------------------------------------------------------------------------
 * 1. baseURL 来自 VITE_API_BASE_URL —— 部署后后端地址变化只改 .env 一处
 * 2. 自动携带 JWT（Authorization: Bearer <token>）
 * 3. 401 → 清除登录态并跳转登录页（带 redirect）
 * 4. 403 小黑屋 → 弹窗提示「您因放鸽子被禁赛，将于 xx 时间解除」并展示解禁时间
 * 5. 其它错误 → 统一 Toast 展示后端返回的 message
 * 6. 业务成功时直接返回 data，失败时 reject 一个带 code/data 的 Error
 */
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import router from '@/router'
import { USE_MOCK, mockAdapter } from '@/mock'

const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: Number(import.meta.env.VITE_API_TIMEOUT || 15000),
  headers: { 'Content-Type': 'application/json' }
})

// 纯前端演示模式：不连后端，由内置 mock 适配器返回数据
if (USE_MOCK) {
  service.defaults.adapter = mockAdapter
}

/* ---------------------------------------------------------------- 请求拦截 */
service.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('mq_token')
    if (token) config.headers.Authorization = `Bearer ${token}`
    return config
  },
  (error) => Promise.reject(error)
)

/* ---------------------------------------------------------------- 工具函数 */
export function formatDateTime(value) {
  if (!value) return '未知'
  const d = new Date(String(value).replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return String(value)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 把后端错误包成可判断的对象 */
function bizError(code, message, data) {
  const err = new Error(message || '请求失败')
  err.code = code
  err.data = data
  err.isBizError = true
  return err
}

let banDialogShowing = false

/** 小黑屋弹窗：展示后端返回的原文 + 明确的解禁时间（同一时间只弹一次） */
function showBanDialog(message, data = {}) {
  if (banDialogShowing) return
  banDialogShowing = true
  const endText = formatDateTime(data.ban_end_time)
  ElMessageBox.alert(
    `<div style="line-height:1.9">
       <p style="margin:0 0 8px">${message || '您因放鸽子被禁赛'}</p>
       <p style="margin:0;font-size:13px;color:#69625A">
         解禁时间：<b style="color:#c9873f">${endText}</b>
       </p>
       <p style="margin:4px 0 0;font-size:12.5px;color:#9a9188">
         禁赛期间仅可浏览、签到与核销，不能发起球局与报名
       </p>
     </div>`,
    '禁赛提示',
    {
      dangerouslyUseHTMLString: true,
      confirmButtonText: '我知道了',
      type: 'warning',
      customClass: 'ban-dialog'
    }
  )
    .catch(() => {})
    .finally(() => {
      banDialogShowing = false
    })
}

/** 401 统一处理：清登录态 → 跳登录页 */
function handleUnauthorized() {
  localStorage.removeItem('mq_token')
  localStorage.removeItem('mq_refresh_token')
  localStorage.removeItem('mq_user')
  const current = router.currentRoute.value
  if (current.name !== 'login') {
    router.replace({ name: 'login', query: { redirect: current.fullPath } })
  }
}

/* ---------------------------------------------------------------- 响应拦截 */
service.interceptors.response.use(
  (resp) => {
    const body = resp.data
    // 后端统一响应体 { code, message, data }
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) return body.data
      const msg = body.msg || body.message || '请求失败'
      if (body.code === 403 && body.data?.banned) {
        showBanDialog(msg, body.data)
        return Promise.reject(bizError(403, msg, body.data))
      }
      if ([40100, 40101, 40102].includes(body.code)) {
        handleUnauthorized()
      }
      ElMessage.error(msg)
      return Promise.reject(bizError(body.code, msg, body.data))
    }
    return body
  },
  (error) => {
    const resp = error.response
    const body = resp?.data || {}
    const msg = body.msg || body.message || error.message || '网络异常，请稍后重试'

    if (resp?.status === 401) {
      handleUnauthorized()
      ElMessage.error(msg)
      return Promise.reject(bizError(401, msg, body.data))
    }
    // ★ 小黑屋：HTTP 403 且业务码 403（后端按产品规则返回 code=403 + msg）
    if (resp?.status === 403 && (body.code === 403 || body.data?.banned)) {
      showBanDialog(msg, body.data)
      return Promise.reject(bizError(403, msg, body.data))
    }
    if (body.code === 40103) {
      ElMessage.error(msg)
      handleUnauthorized()
      return Promise.reject(bizError(40103, msg, body.data))
    }
    ElMessage.error(msg)
    return Promise.reject(bizError(body.code ?? resp?.status, msg, body.data))
  }
)

export default service
