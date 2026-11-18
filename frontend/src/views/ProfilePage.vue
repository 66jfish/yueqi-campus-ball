<script setup>
/**
 * 个人主页（信誉分 / 信誉标签 / 小黑屋状态与解禁时间）
 * - 顶部：封禁横幅（红/橙警示条 + 倒计时，来自 BanBanner）
 * - 信誉分大卡：操作分 + 等级 + 画像分 + AI 来源提示 + 标签
 * - 加权明细：折叠展示「分数怎么来的」（次数×权重=小计）
 * - 行为统计：到场/迟到/缺席/退出/守约率
 * - 封禁历史（永久留存）与解禁时间
 * - 退出登录
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { userApi, blacklistApi, aiApi } from '@/api'
import { useUserStore, LEVEL_TEXT, LEVEL_TYPE } from '@/stores/user'
import { useCountdown } from '@/composables/useCountdown'
import { mockState, USE_MOCK } from '@/mock'
import BanBanner from '@/components/BanBanner.vue'
import CatIcon from '@/components/CatIcon.vue'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const targetId = computed(() => (route.params.id ? Number(route.params.id) : store.user?.id))
const isSelf = computed(() => !route.params.id || Number(route.params.id) === store.user?.id)

const page = ref(null)
const loading = ref(true)
const refreshing = ref(false)
const showDetail = ref(false)

const ban = computed(() => (isSelf.value ? store.ban : page.value?.banned ? { banned: true } : null))
const banEndTime = computed(() => page.value?.ban_end_time || store.ban?.ban_end_time)
const { text: banCountdown } = useCountdown(banEndTime)

const tags = computed(() => page.value?.tags || [])
const breakdown = computed(() => page.value?.breakdown || [])
const score = computed(() => page.value?.reputation_score ?? store.creditScore)
const profileScore = computed(() => page.value?.profile_score)
const levelText = computed(() => page.value?.credit_level_text || LEVEL_TEXT[page.value?.credit_level || 3])
const levelType = computed(() => LEVEL_TYPE[page.value?.credit_level || 3])

/** 分数环形进度（设计稿同款柔和视觉） */
const ringStyle = computed(() => {
  const pct = Math.min(100, Math.round(((score.value || 0) / 150) * 100))
  return {
    background: `conic-gradient(var(--c-primary) ${pct}%, #eee7db ${pct}% 100%)`
  }
})

function fmt(v) {
  if (!v) return '—'
  const d = new Date(String(v).replace(' ', 'T'))
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function load() {
  loading.value = true
  try {
    if (isSelf.value) {
      await store.fetchMe()
      await store.loadExtras()
      page.value = await userApi.profilePage(store.user.id)
    } else {
      page.value = await userApi.profilePage(targetId.value)
    }
  } finally {
    loading.value = false
  }
}

async function refreshProfile() {
  refreshing.value = true
  try {
    await store.refreshProfile()
    page.value = await userApi.profilePage(store.user.id)
    ElMessage.success('画像已刷新')
  } finally {
    refreshing.value = false
  }
}

/** 演示用：切换 mock 里的封禁状态，便于查看横幅两种配色 */
async function toggleBan() {
  mockState.banActive = !mockState.banActive
  await store.refreshBan()
  page.value = await userApi.profilePage(store.user.id)
}

async function logout() {
  await store.logout()
  ElMessage.success('已退出登录')
  router.push({ name: 'home' })
}

onMounted(load)
</script>

<template>
  <div class="page">
    <el-skeleton v-if="loading" :rows="8" animated />

    <template v-else-if="page">
      <!-- ★ 小黑屋封禁横幅（红/橙警示条 + 倒计时） -->
      <BanBanner v-if="isSelf && store.ban?.banned" :ban="store.ban" class="mb" />

      <el-row :gutter="16">
        <el-col :xs="24" :md="15">
          <!-- 信誉分主卡 -->
          <div class="card score">
            <div class="score__left">
              <div class="score__ring" :style="ringStyle">
                <div class="score__ring-inner">
                  <b>{{ score }}</b>
                  <span>信誉分</span>
                </div>
              </div>
              <div class="score__info">
                <h1 class="t-section">{{ page.nickname }}</h1>
                <p class="t-caption">
                  {{ page.campus || '—' }} · {{ page.college || '—' }} · 球技 {{ page.skill_level }} 级
                </p>
                <div class="score__tags">
                  <span class="pill" :class="`pill--${levelType === 'success' ? 'green' : levelType === 'warning' ? 'warn' : levelType === 'danger' ? 'danger' : 'blue'}`">
                    {{ levelText }}
                  </span>
                  <span v-for="t in tags" :key="t" class="pill pill--ghost">{{ t }}</span>
                </div>
              </div>
            </div>

            <div class="score__right">
              <div class="score__metric">
                <b>{{ profileScore ?? '—' }}</b>
                <span>AI 画像分</span>
              </div>
              <div class="score__metric">
                <b>{{ Math.round((page.keep_rate ?? 1) * 100) }}%</b>
                <span>守约率</span>
              </div>
              <el-button
                v-if="isSelf"
                size="small"
                round
                :loading="refreshing"
                @click="refreshProfile"
              >
                刷新画像
              </el-button>
            </div>
          </div>

          <!-- 加权明细：分数怎么来的 -->
          <div class="card how">
            <div class="how__head" @click="showDetail = !showDetail">
              <h3 class="t-card-title">
                <el-icon><MagicStick /></el-icon> 信誉分怎么来的
              </h3>
              <el-icon><component :is="showDetail ? 'ArrowUp' : 'ArrowDown'" /></el-icon>
            </div>
            <p class="t-caption how__formula">
              画像分 = 初始分 100 + 2×按时签到 - 3×迟到 - 10×无故缺席 - 2×主动退出 - 4×临期退出 + 守约加成
            </p>

            <el-collapse-transition>
              <el-table v-show="showDetail" :data="breakdown" size="small" class="how__table">
                <el-table-column prop="item" label="行为项" min-width="150" />
                <el-table-column prop="count" label="次数" width="70" align="center" />
                <el-table-column prop="weight" label="权重" width="70" align="center" />
                <el-table-column label="小计" width="80" align="center">
                  <template #default="{ row }">
                    <span :class="row.subtotal > 0 ? 'is-green' : row.subtotal < 0 ? 'is-red' : ''">
                      {{ row.subtotal > 0 ? '+' : '' }}{{ row.subtotal }}
                    </span>
                  </template>
                </el-table-column>
              </el-table>
            </el-collapse-transition>

            <p v-if="page.summary" class="t-body how__summary">{{ page.summary }}</p>
            <p v-if="page.profile_degraded" class="t-caption how__degraded">
              当前为本地加权规则评估（未启用大模型），接入 DeepSeek 后标签与总结由 AI 生成
            </p>
          </div>

          <!-- 封禁历史 -->
          <div v-if="isSelf && store.ban?.history?.length" class="card history">
            <h3 class="t-card-title">封禁记录（永久留存）</h3>
            <ul>
              <li v-for="h in store.ban.history" :key="h.id">
                <span class="pill" :class="h.is_active ? 'pill--danger' : 'pill--ghost'">
                  {{ h.is_active ? '封禁中' : '已解禁' }}
                </span>
                <div>
                  <p class="history__reason">{{ h.reason || '缺席球局' }}</p>
                  <p class="t-caption">
                    {{ fmt(h.ban_start_time) }} ~ {{ fmt(h.ban_end_time) }} · {{ h.ban_duration_days }} 天
                    <span v-if="h.ban_extend_count">· 顺延 {{ h.ban_extend_count }} 次</span>
                  </p>
                </div>
              </li>
            </ul>
          </div>
        </el-col>

        <el-col :xs="24" :md="9">
          <!-- 行为统计 -->
          <div class="card stats">
            <h3 class="t-card-title">参与记录</h3>
            <div class="stats__grid">
              <div><b class="is-green">{{ page.attended_count }}</b><span>按时到场</span></div>
              <div><b class="is-orange">{{ page.late_count }}</b><span>迟到</span></div>
              <div><b class="is-red">{{ page.absent_count }}</b><span>缺席</span></div>
              <div><b>{{ page.cancel_count }}</b><span>主动退出</span></div>
              <div><b>{{ page.joined_game_count }}</b><span>参与球局</span></div>
              <div><b>{{ page.created_game_count }}</b><span>发起球局</span></div>
            </div>
          </div>

          <!-- 小黑屋状态 -->
          <div v-if="isSelf" class="card banbox">
            <h3 class="t-card-title">小黑屋状态</h3>
            <template v-if="store.ban?.banned">
              <p class="banbox__state is-red">封禁中</p>
              <p class="t-body">解禁时间：<b>{{ fmt(store.ban.ban_end_time) }}</b></p>
              <p class="t-body">剩余：<b class="is-red">{{ banCountdown }}</b></p>
              <p class="t-caption">封禁期间可浏览/签到，不能发起球局与报名</p>
            </template>
            <template v-else>
              <p class="banbox__state is-green">状态良好</p>
              <p class="t-caption">累计封禁 {{ store.ban?.total_ban_count || 0 }} 次，无生效中的处罚</p>
            </template>
            <el-button v-if="USE_MOCK" size="small" text @click="toggleBan">
              （演示）{{ mockState.banActive ? '模拟解禁' : '模拟禁赛' }}
            </el-button>
          </div>

          <div class="card actions">
            <el-button round style="width: 100%" @click="router.push({ name: 'my-games' })">我的球局</el-button>
            <el-button round style="width: 100%; margin: 8px 0 0" @click="router.push({ name: 'game-create' })">
              发起球局
            </el-button>
            <el-button v-if="isSelf" round text style="width: 100%; margin-top: 8px" @click="logout">
              退出登录
            </el-button>
          </div>
        </el-col>
      </el-row>
    </template>

    <el-empty v-else description="用户不存在" />
  </div>
</template>

<style scoped lang="scss">
.mb {
  margin-bottom: var(--sp-4);
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

/* 信誉分主卡 */
.score {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  flex-wrap: wrap;
}
.score__left {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  min-width: 0;
}
.score__ring {
  width: 104px;
  height: 104px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
.score__ring-inner {
  width: 82px;
  height: 82px;
  border-radius: 50%;
  background: var(--c-surface);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 0 0 1px var(--c-line-soft);
}
.score__ring-inner b {
  font-size: 26px;
  line-height: 1;
  color: var(--c-text);
}
.score__ring-inner span {
  font-size: 10.5px;
  color: var(--c-text-muted);
  margin-top: 3px;
}
.score__info h1 {
  margin: 0 0 2px;
}
.score__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.score__right {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
}
.score__metric {
  text-align: center;
}
.score__metric b {
  display: block;
  font-size: 20px;
  color: var(--c-primary-dark);
}
.score__metric span {
  font-size: 11px;
  color: var(--c-text-muted);
}

/* 加权明细 */
.how {
  margin-top: var(--sp-4);
}
.how__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
}
.how__head h3 {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
}
.how__formula {
  margin: 8px 0 0;
  line-height: 1.7;
}
.how__table {
  margin-top: 10px;
}
.how__summary {
  margin: 10px 0 0;
}
.how__degraded {
  margin: 6px 0 0;
  color: var(--c-primary-dark);
}

/* 封禁历史 */
.history {
  margin-top: var(--sp-4);
}
.history ul {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.history li {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--c-line-soft);
}
.history li:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.history__reason {
  margin: 0;
  font-size: 13px;
  color: var(--c-text);
}

/* 统计 */
.stats__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 10px;
}
.stats__grid div {
  text-align: center;
  background: var(--c-bg-soft);
  border-radius: var(--r-md);
  padding: 10px 4px;
}
.stats__grid b {
  display: block;
  font-size: 18px;
}
.stats__grid span {
  font-size: 11px;
  color: var(--c-text-muted);
}

/* 小黑屋状态 */
.banbox {
  margin-top: var(--sp-4);
}
.banbox__state {
  font-size: 16px;
  font-weight: 800;
  margin: 6px 0;
}
.banbox p {
  margin: 4px 0;
}

.actions {
  margin-top: var(--sp-4);
}
</style>
