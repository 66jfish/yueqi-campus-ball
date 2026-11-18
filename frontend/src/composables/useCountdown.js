/**
 * 解禁倒计时（小黑屋横幅 / 个人主页使用）
 * 返回 { text, expired, days/hours/minutes/seconds }
 */
import { computed, onUnmounted, ref } from 'vue'

export function useCountdown(endTimeRef) {
  const remain = ref(0)
  let timer = null

  const tick = () => {
    const end = endTimeRef.value ? new Date(String(endTimeRef.value).replace(' ', 'T')).getTime() : 0
    remain.value = Math.max(0, end - Date.now())
    if (remain.value === 0 && timer) {
      clearInterval(timer)
      timer = null
    }
  }

  tick()
  timer = setInterval(tick, 1000)
  onUnmounted(() => timer && clearInterval(timer))

  const parts = computed(() => {
    const s = Math.floor(remain.value / 1000)
    return {
      days: Math.floor(s / 86400),
      hours: Math.floor((s % 86400) / 3600),
      minutes: Math.floor((s % 3600) / 60),
      seconds: s % 60
    }
  })

  const text = computed(() => {
    const { days, hours, minutes, seconds } = parts.value
    if (remain.value <= 0) return '已解禁'
    if (days > 0) return `${days} 天 ${hours} 小时 ${minutes} 分`
    if (hours > 0) return `${hours} 小时 ${minutes} 分 ${seconds} 秒`
    return `${minutes} 分 ${seconds} 秒`
  })

  return { remain, parts, text, expired: computed(() => remain.value <= 0) }
}
