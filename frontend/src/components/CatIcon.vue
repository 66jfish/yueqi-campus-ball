<script setup>
/**
 * 手绘风猫头图标（纯 SVG，无外部图片依赖）
 * 设计稿中的手绘猫元素用简笔线条还原，可与任意主题色搭配
 */
const props = defineProps({
  size: { type: Number, default: 32 },
  color: { type: String, default: '#49413B' },
  fill: { type: String, default: 'none' },
  whiskers: { type: Boolean, default: true }
})
</script>

<template>
  <svg
    :width="props.size"
    :height="props.size"
    viewBox="0 0 48 48"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <!-- 耳朵 -->
    <path
      d="M12 17 L10 7 L19.5 12.5"
      :stroke="props.color"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      :fill="props.fill"
    />
    <path
      d="M36 17 L38 7 L28.5 12.5"
      :stroke="props.color"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      :fill="props.fill"
    />
    <!-- 脸 -->
    <path
      d="M24 41c8.3 0 14-6.2 14-14.5S32.3 14 24 14 10 18.2 10 26.5 15.7 41 24 41Z"
      :stroke="props.color"
      stroke-width="2"
      stroke-linejoin="round"
      :fill="props.fill"
    />
    <!-- 眼睛 -->
    <circle cx="19" cy="26" r="1.7" :fill="props.color" />
    <circle cx="29" cy="26" r="1.7" :fill="props.color" />
    <!-- 鼻子 -->
    <path d="M24 31.5l-1.8 1.6h3.6L24 31.5Z" :fill="props.color" />
    <!-- 胡须 -->
    <template v-if="props.whiskers">
      <path d="M7.5 27h5M7.5 31h5" :stroke="props.color" stroke-width="1.4" stroke-linecap="round" />
      <path d="M35.5 27h5M35.5 31h5" :stroke="props.color" stroke-width="1.4" stroke-linecap="round" />
    </template>
  </svg>
</template>
