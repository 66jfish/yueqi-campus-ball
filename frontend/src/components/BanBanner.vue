<script setup>
/**
 * 小黑屋封禁横幅（红/橙警示条 + 解禁倒计时）
 * 设计推导（设计稿未覆盖，沿用同一套视觉语言：大圆角、柔和配色、明确层级）
 *   红色 = 正在封禁中；橙色 = 即将解禁（<6 小时）
 * 展示：封禁原因、解禁时间、倒计时、封禁期间可做/不可做的说明
 */
import { computed } from 'vue'
import { useCountdown } from '@/composables/useCountdown'

const props = defineProps({
  /** /blacklist/me 返回对象；banned=true 时展示 */
  ban: { type: Object, default: null },
  /** compact=true 时用于页面顶部细条提示（球局广场） */
  compact: { type: Boolean, default: false }
})

const endTime = computed(() => props.ban?.ban_end_time || null)
const { text, expired, parts } = useCountdown(endTime)

const nearRelease = computed(() => (props.ban?.remaining_hours ?? 99) <= 6 || parts.value.days === 0)

function fmt(v) {
  if (!v) return '未知'
  const d = new Date(String(v).replace(' ', 'T'))
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
</script>

<template>
  <div v-if="ban?.banned" class="ban" :class="{ 'ban--orange': nearRelease, 'ban--compact': compact }">
    <div class="ban__icon">
      <el-icon :size="compact ? 16 : 22"><WarningFilled /></el-icon>
    </div>

    <div class="ban__body">
      <p class="ban__title">
        您因放鸽子被禁赛<span v-if="!compact">，将于 {{ fmt(ban.ban_end_time) }} 解除</span>
      </p>
      <p v-if="!compact" class="ban__desc">{{ ban.reason || '缺席球局（未签到且未请假）' }}</p>

      <div class="ban__count">
        <span class="ban__count-label">{{ expired ? '已解禁' : '解禁倒计时' }}</span>
        <b class="ban__count-value">{{ text }}</b>
      </div>

      <p v-if="!compact" class="ban__note">
        禁赛期间可浏览球局、签到核销、退出球局；<b>不能发起球局与报名</b>。
      </p>
    </div>

    <div v-if="!compact && ban.remaining_hours != null" class="ban__right">
      <span class="t-caption">剩余</span>
      <b>{{ Math.ceil(ban.remaining_hours) }}h</b>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ban {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
  padding: var(--sp-4);
  border-radius: var(--r-lg);
  background: linear-gradient(135deg, #fbe6e1 0%, #f9dcd6 100%);
  border: 1px solid #f0c3ba;
  box-shadow: 0 6px 18px rgba(217, 99, 79, 0.14);
  color: #8d3a2a;
}
/* 即将解禁 → 橙色警示 */
.ban--orange {
  background: linear-gradient(135deg, #fdf1dc 0%, #fbe6c6 100%);
  border-color: #eccf9c;
  box-shadow: 0 6px 18px rgba(224, 163, 60, 0.16);
  color: #8a5c10;
}
.ban--compact {
  padding: 8px 12px;
  align-items: center;
  border-radius: var(--r-pill);
}
.ban__icon {
  flex: none;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  color: inherit;
}
.ban--compact .ban__icon {
  width: 24px;
  height: 24px;
}
.ban__body {
  flex: 1;
  min-width: 0;
}
.ban__title {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  color: inherit;
}
.ban--compact .ban__title {
  font-size: 13px;
  font-weight: 600;
}
.ban__desc {
  margin: 4px 0 0;
  font-size: 12.5px;
  opacity: 0.85;
}
.ban__count {
  margin-top: 8px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(255, 255, 255, 0.7);
  border-radius: var(--r-pill);
  padding: 4px 12px;
}
.ban__count-label {
  font-size: 11.5px;
  opacity: 0.8;
}
.ban__count-value {
  font-size: 14px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.4px;
}
.ban__note {
  margin: 8px 0 0;
  font-size: 12px;
  opacity: 0.85;
  line-height: 1.7;
}
.ban__right {
  flex: none;
  text-align: center;
  display: flex;
  flex-direction: column;
  opacity: 0.9;
}
.ban__right b {
  font-size: 18px;
}
</style>
