<script setup>
/**
 * 热局卡片（设计稿核心部件）
 * 结构：球类·模式 / 状态标签 → 时间·地点·距离 → 人均费用·人数·水平
 *      → 人数进度条（绿=人少、蓝=正常、橙=快满） → 「加入球局」按钮
 * 状态标签规则（设计稿标注）：
 *   还差 N 人（未满）｜女生友好（gender_limit=2）｜今晚（今天 18:00 后开球）
 *   信誉金牌（创建者信誉分 ≥120）｜已满（可候补）
 */
import { computed } from 'vue'
import CatIcon from './CatIcon.vue'

const props = defineProps({
  game: { type: Object, required: true },
  /** 是否展示真实「加入球局」按钮（我的球局列表里用底部操作位代替） */
  showJoin: { type: Boolean, default: true },
  /** 按钮 loading（防重复提交） */
  joining: { type: Boolean, default: false }
})
const emit = defineEmits(['join', 'open'])

const SPORT = {
  1: { name: '篮球', cat: '乌云' },
  2: { name: '足球', cat: '芝麻' },
  3: { name: '羽毛球', cat: '白芷' },
  4: { name: '网球', cat: '豆花' },
  5: { name: '排球', cat: '橘子' },
  6: { name: '乒乓球', cat: '团子' }
}

const sport = computed(() => SPORT[props.game.sport_type] || { name: '运动', cat: '校猫' })

/** 标题已含球类名时不再重复前缀（避免出现「羽毛球·羽毛球·双打」） */
const displayTitle = computed(() => {
  const title = props.game.title || ''
  return title.includes(sport.value.name) ? title : `${sport.value.name} · ${title}`
})

const timeText = computed(() => {
  const g = props.game
  if (!g.start_time) return '时间待定'
  const d = new Date(String(g.start_time).replace(' ', 'T'))
  const end = g.end_time ? new Date(String(g.end_time).replace(' ', 'T')) : null
  const pad = (n) => String(n).padStart(2, '0')
  const day = `${d.getMonth() + 1}月${d.getDate()}日`
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}${end ? '~' + pad(end.getHours()) + ':' + pad(end.getMinutes()) : ''}`
  return `${day} ${hm}`
})

const feeText = computed(() =>
  props.game.fee_type === 1 && props.game.fee_amount ? `人均 ¥${props.game.fee_amount}` : '免费'
)

const skillText = computed(() => {
  const map = { 0: '不限水平', 1: '新手友好', 2: '初级', 3: '中级', 4: '高级', 5: '大神局' }
  return map[props.game.skill_level_limit || 0]
})

const progress = computed(() => {
  const cur = props.game.current_players || 0
  const max = props.game.max_players || 1
  return Math.min(100, Math.round((cur / max) * 100))
})

/** 进度条颜色：<50% 绿、<80% 蓝、≥80% 橙（设计稿中三条进度条颜色不同） */
const barColor = computed(() => {
  if (progress.value >= 80) return 'var(--c-primary)'
  if (progress.value >= 50) return 'var(--c-blue)'
  return 'var(--c-green)'
})

const slotsLeft = computed(() =>
  props.game.slots_left != null
    ? props.game.slots_left
    : Math.max(0, (props.game.max_players || 0) - (props.game.current_players || 0))
)

const isTonight = computed(() => {
  if (!props.game.start_time) return false
  const d = new Date(String(props.game.start_time).replace(' ', 'T'))
  const now = new Date()
  return d.toDateString() === now.toDateString() && d.getHours() >= 17
})

const tags = computed(() => {
  const list = []
  const g = props.game
  if (g.my_registration_status === 1) list.push({ text: '已报名', type: 'workflow' })
  else if (g.is_full || slotsLeft.value <= 0) list.push({ text: '已满·可候补', type: 'muted' })
  else if (slotsLeft.value <= 2) list.push({ text: `还差 ${slotsLeft.value} 人`, type: 'primary' })
  if (g.gender_limit === 2) list.push({ text: '女生友好', type: 'pink' })
  if (isTonight.value) list.push({ text: '今晚', type: 'warn' })
  if ((g.creator_credit_score || 0) >= 120) list.push({ text: '信誉金牌', type: 'green' })
  if (g.fee_type === 1) list.push({ text: 'AA 制', type: 'blue' })
  return list.slice(0, 4)
})

const matchScore = computed(() => {
  const s = props.game.match_score
  return typeof s === 'number' ? s : null
})
</script>

<template>
  <article class="gcard card card--tap" @click="emit('open', game)">
    <header class="gcard__head">
      <div class="gcard__sport">
        <CatIcon :size="26" color="#49413B" :fill="'#FBF1E5'" />
        <div class="gcard__sporttext">
          <span class="gcard__title">{{ displayTitle }}</span>
          <span class="t-caption">{{ sport.cat }} 值日 · {{ game.venue_name || '场地待定' }}</span>
        </div>
      </div>
      <div v-if="matchScore !== null" class="gcard__match" :title="game.match_reason">
        <b>{{ matchScore }}</b>
        <span>匹配</span>
      </div>
    </header>

    <div class="gcard__tags">
      <span
        v-for="t in tags"
        :key="t.text"
        class="pill"
        :class="{
          'pill--primary': t.type === 'primary',
          'pill--green': t.type === 'green',
          'pill--blue': t.type === 'blue',
          'pill--pink': t.type === 'pink',
          'pill--warn': t.type === 'warn',
          'pill--ghost': t.type === 'workflow',
          'pill--danger': t.type === 'muted'
        }"
        >{{ t.text }}</span
      >
    </div>

    <ul class="gcard__meta">
      <li><el-icon><Clock /></el-icon>{{ timeText }}</li>
      <li><el-icon><LocationInformation /></el-icon>{{ game.campus }} · {{ game.venue_name }}</li>
    </ul>

    <div class="gcard__stats">
      <span class="gcard__fee">{{ feeText }}</span>
      <span class="dot-sep">{{ game.current_players }}/{{ game.max_players }} 人</span>
      <span class="dot-sep">{{ skillText }}</span>
    </div>

    <div class="gcard__bar">
      <div class="gcard__bar-track">
        <div class="gcard__bar-fill" :style="{ width: progress + '%', background: barColor }" />
      </div>
      <span class="t-caption">{{ progress }}%</span>
    </div>

    <footer class="gcard__foot">
      <span class="t-meta">发起人 {{ game.creator_nickname || '同学' }}</span>
      <button
        v-if="showJoin"
        class="btn-soft btn-soft--primary"
        :disabled="joining"
        @click.stop="emit('join', game)"
      >
        <el-icon v-if="joining" class="is-loading"><Loading /></el-icon>
        {{ joining ? '提交中' : game.my_registration_status === 1 ? '已报名' : slotsLeft <= 0 ? '候补' : '加入球局' }}
      </button>
      <span v-else class="gcard__more">查看详情 <el-icon><ArrowRight /></el-icon></span>
    </footer>
  </article>
</template>

<style scoped lang="scss">
.gcard {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
}
.gcard__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-3);
}
.gcard__sport {
  display: flex;
  gap: 10px;
  min-width: 0;
}
.gcard__sporttext {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.gcard__title {
  font-size: 15px;
  font-weight: 700;
  color: var(--c-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.gcard__match {
  flex: none;
  width: 44px;
  height: 44px;
  border-radius: var(--r-md);
  background: var(--c-primary-tint);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  line-height: 1.05;
}
.gcard__match b {
  font-size: 15px;
  color: var(--c-primary-dark);
}
.gcard__match span {
  font-size: 10px;
  color: var(--c-text-muted);
}
.gcard__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.gcard__meta {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.gcard__meta li {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--c-text-sub);
}
.gcard__meta .el-icon {
  color: var(--c-primary);
}
.gcard__stats {
  font-size: 12.5px;
  color: var(--c-text-sub);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}
.gcard__fee {
  font-weight: 700;
  color: var(--c-primary-dark);
}
.gcard__bar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.gcard__bar-track {
  flex: 1;
  height: 7px;
  border-radius: var(--r-pill);
  background: var(--c-line-soft);
  overflow: hidden;
}
.gcard__bar-fill {
  height: 100%;
  border-radius: var(--r-pill);
  transition: width 0.3s ease;
}
.gcard__foot {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  padding-top: 10px;
  border-top: 1px dashed var(--c-line-soft);
}
.gcard__more {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12.5px;
  color: var(--c-primary-dark);
  font-weight: 600;
}
</style>
