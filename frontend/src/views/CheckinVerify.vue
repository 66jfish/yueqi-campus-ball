<script setup>
/**
 * 签到核销页（发起人给到场用户签到）
 * - 名单来自 /checkin/game/{id}：未签到 / 已签到 / 迟到 / 缺席 一目了然
 * - 支持勾选批量核销 与「一键全部核销」
 * - 核销结果逐条展示：成功（含信誉分变动 +2/-3）、跳过（已核销/已请假）、失败（未报名）
 * - 结束球局 → 触发缺席判定（未签到未请假者 -10 分 + 自动禁赛 3 天）
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { checkinApi, gameApi } from '@/api'
import CatIcon from '@/components/CatIcon.vue'

const route = useRoute()
const router = useRouter()
const gameId = route.params.id

const roster = ref(null)
const selected = ref([])
const loading = ref(true)
const verifying = ref(false)
const finishing = ref(false)
const results = ref([])

const STATUS_STYLE = {
  0: { text: '未签到', cls: 'pill--ghost' },
  1: { text: '已签到', cls: 'pill--green' },
  2: { text: '迟到', cls: 'pill--warn' },
  3: { text: '缺席', cls: 'pill--danger' },
  4: { text: '已请假', cls: 'pill--blue' }
}

const members = computed(() => roster.value?.members || [])
const pendingMembers = computed(() => members.value.filter((m) => m.checkin_status === 0 || m.checkin_status === null))
const checkedCount = computed(() => members.value.filter((m) => [1, 2].includes(m.checkin_status)).length)

async function load() {
  loading.value = true
  try {
    roster.value = await checkinApi.roster(gameId)
    selected.value = pendingMembers.value.map((m) => m.user_id)
  } finally {
    loading.value = false
  }
}

function fmt(v) {
  if (!v) return '—'
  const d = new Date(String(v).replace(' ', 'T'))
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

async function verifyAll() {
  if (!pendingMembers.value.length) {
    ElMessage.info('没有待核销的同学')
    return
  }
  verifying.value = true
  try {
    const res = await checkinApi.verify({ game_id: Number(gameId), verify_all: true })
    results.value = res.items || []
    ElMessage.success(res.message || '核销完成')
    await load()
  } finally {
    verifying.value = false
  }
}

async function verifySelected() {
  if (!selected.value.length) {
    ElMessage.warning('请先勾选要核销的同学')
    return
  }
  verifying.value = true
  try {
    const res = await checkinApi.verify({ game_id: Number(gameId), user_ids: selected.value })
    results.value = res.items || []
    ElMessage.success(res.message || '核销完成')
    await load()
  } finally {
    verifying.value = false
  }
}

async function finish() {
  try {
    await ElMessageBox.confirm(
      '结束后立刻执行缺席判定：未签到且未请假的同学会被记缺席（-10 分）并自动禁赛 3 天。确定吗？',
      '结束球局',
      { confirmButtonText: '确认结束', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  finishing.value = true
  try {
    const res = await gameApi.finish(gameId)
    ElMessage.success(res.message || '球局已结束')
    await load()
  } finally {
    finishing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="section-head">
      <h2 class="t-section">签到核销</h2>
      <span class="section-head__more" @click="router.back()">返回</span>
    </div>

    <el-skeleton v-if="loading" :rows="6" animated />

    <template v-else-if="roster">
      <!-- 概览 -->
      <div class="card verify__head">
        <div class="verify__title">
          <CatIcon :size="34" color="#DB9A64" fill="#FBF1E5" />
          <div>
            <h3 class="t-card-title">{{ roster.title }}</h3>
            <p class="t-caption">
              核销窗口 {{ fmt(roster.checkin_open_at) }} ~ {{ fmt(roster.checkin_close_at) }}
              <span v-if="roster.checkin_open" class="pill pill--green" style="margin-left: 6px">核销中</span>
              <span v-else class="pill pill--ghost" style="margin-left: 6px">未开放</span>
            </p>
          </div>
        </div>
        <div class="verify__stats">
          <div><b>{{ roster.signed_count }}</b><span>报名</span></div>
          <div><b class="is-green">{{ checkedCount }}</b><span>已到场</span></div>
          <div><b class="is-orange">{{ roster.not_checked_count }}</b><span>未核销</span></div>
          <div><b class="is-red">{{ roster.absent_count }}</b><span>缺席</span></div>
        </div>
      </div>

      <!-- 操作条 -->
      <div class="verify__ops">
        <el-button type="primary" round :loading="verifying" @click="verifyAll">
          <el-icon><Select /></el-icon>&nbsp;一键核销全部未到（{{ pendingMembers.length }}）
        </el-button>
        <el-button round :loading="verifying" @click="verifySelected">核销勾选（{{ selected.length }}）</el-button>
        <el-button round :loading="finishing" @click="finish">结束球局并判缺席</el-button>
      </div>

      <!-- 名单 -->
      <el-checkbox-group v-model="selected" class="verify__list">
        <label v-for="m in members" :key="m.user_id" class="verify__row card card--flat">
          <el-checkbox :value="m.user_id" :disabled="[1, 2, 4].includes(m.checkin_status)" />
          <span class="verify__avatar"><CatIcon :size="22" color="#69625A" /></span>
          <span class="verify__name">{{ m.nickname }}</span>
          <span class="pill pill--ghost">{{ m.skill_level_text || '未填写水平' }}</span>
          <span class="t-caption">信誉 {{ m.credit_score }}</span>
          <span class="pill" :class="STATUS_STYLE[m.checkin_status ?? 0].cls">
            {{ m.checkin_status_text }}
          </span>
          <span class="t-caption verify__time">{{ fmt(m.checkin_time) }}</span>
          <span v-if="m.credit_delta" class="t-caption" :class="m.credit_delta > 0 ? 'is-green' : 'is-red'">
            {{ m.credit_delta > 0 ? '+' : '' }}{{ m.credit_delta }}
          </span>
        </label>
      </el-checkbox-group>

      <!-- 核销结果（逐条） -->
      <div v-if="results.length" class="card verify__result">
        <h3 class="t-card-title">本次核销结果</h3>
        <ul>
          <li v-for="r in results" :key="r.user_id">
            <span class="pill" :class="r.ok ? 'pill--green' : r.skipped ? 'pill--warn' : 'pill--danger'">
              {{ r.ok ? '成功' : r.skipped ? '跳过' : '失败' }}
            </span>
            <b>{{ r.nickname || '用户' + r.user_id }}</b>
            <span v-if="r.ok" class="t-body">
              {{ r.checkin_status_text }}
              <span :class="r.credit_delta > 0 ? 'is-green' : 'is-red'">
                （信誉 {{ r.credit_delta > 0 ? '+' : '' }}{{ r.credit_delta }} → {{ r.credit_after }}）
              </span>
              <span v-if="r.banned" class="pill pill--danger">已进小黑屋</span>
            </span>
            <span v-else class="t-body">{{ r.reason }}</span>
          </li>
        </ul>
      </div>
    </template>

    <el-empty v-else description="没有权限或球局不存在" />
  </div>
</template>

<style scoped lang="scss">
.verify__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  flex-wrap: wrap;
}
.verify__title {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.verify__title h3 {
  margin: 0;
}
.verify__stats {
  display: flex;
  gap: var(--sp-4);
}
.verify__stats div {
  text-align: center;
}
.verify__stats b {
  display: block;
  font-size: 19px;
  color: var(--c-text);
}
.verify__stats span {
  font-size: 11px;
  color: var(--c-text-muted);
}
.is-green {
  color: #3f7a5c;
}
.is-orange {
  color: var(--c-primary-dark);
}
.is-red {
  color: var(--c-danger);
}
.verify__ops {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin: var(--sp-4) 0;
}
.verify__list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.verify__row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: var(--c-surface);
  cursor: pointer;
}
.verify__avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--c-bg-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
.verify__name {
  flex: 1;
  min-width: 0;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.verify__time {
  width: 48px;
  text-align: right;
}
.verify__result {
  margin-top: var(--sp-4);
}
.verify__result ul {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.verify__result li {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
}
</style>
