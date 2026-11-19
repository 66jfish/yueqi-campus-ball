<script setup>
/**
 * 球类选择区（设计稿：2x2 网格卡片，含手绘猫头 + 球类名 + 代言猫名与局数）
 * 选中项使用浅绿色边框高亮（设计稿标注）
 * 桌面端 4 列、平板 3 列、手机 2 列（el-col 断点）
 */
import { computed } from 'vue'
import CatIcon from './CatIcon.vue'

const props = defineProps({
  games: { type: Array, default: () => [] },
  modelValue: { type: Number, default: 0 } // 0 = 全部
})
const emit = defineEmits(['update:modelValue'])

const SPORTS = [
  { type: 3, name: '羽毛球', cat: '齐刘海', tint: '#E4F2EA' },
  { type: 5, name: '排球', cat: '小橘', tint: '#FBEAEE' },
  { type: 4, name: '网球', cat: '白芷', tint: '#F6EFDC' },
  { type: 1, name: '篮球', cat: '乌头', tint: '#E6F2F8' },
  { type: 2, name: '足球', cat: '豆花', tint: '#EAF3EE' },
  { type: 6, name: '乒乓球', cat: '芝麻', tint: '#F0EBF8' }
]

/** 每个球类当前进行中的局数（来自列表接口的真实数据） */
const counts = computed(() => {
  const map = {}
  props.games.forEach((g) => {
    map[g.sport_type] = (map[g.sport_type] || 0) + 1
  })
  return map
})

function pick(type) {
  emit('update:modelValue', props.modelValue === type ? 0 : type)
}
</script>

<template>
  <section class="sport">
    <div class="sport__grid">
      <button
        v-for="s in SPORTS"
        :key="s.type"
        class="sport__card"
        :class="{ 'is-active': modelValue === s.type }"
        @click="pick(s.type)"
      >
        <span class="sport__icon" :style="{ background: s.tint }">
          <CatIcon :size="26" color="#49413B" />
        </span>
        <span class="sport__name">{{ s.name }}</span>
        <span class="sport__cat">{{ s.cat }} · {{ counts[s.type] || 0 }} 个局</span>
      </button>
    </div>
  </section>
</template>

<style scoped lang="scss">
.sport__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr)); /* 手机：设计稿 2x2 */
  gap: 10px;
}
@media (min-width: 768px) {
  .sport__grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (min-width: 992px) {
  .sport__grid {
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 12px;
  }
}
.sport__card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  padding: 12px 6px;
  background: var(--c-surface);
  border: 1.5px solid var(--c-line-soft);
  border-radius: var(--r-lg);
  box-shadow: var(--sh-1);
  cursor: pointer;
  transition: all 0.18s ease;
  min-width: 0; /* 允许网格子项收缩，避免文字把卡片撑破 */
  overflow: hidden;
}
.sport__card:hover {
  transform: translateY(-2px);
  box-shadow: var(--sh-2);
}
/* 设计稿：选中项浅绿色边框高亮 */
.sport__card.is-active {
  border-color: var(--c-green);
  background: #fbfefc;
  box-shadow: 0 6px 16px rgba(142, 197, 167, 0.24);
}
.sport__icon {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.sport__name {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--c-text);
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sport__cat {
  font-size: 10.5px;
  color: var(--c-text-muted);
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: -0.2px;
}
</style>
