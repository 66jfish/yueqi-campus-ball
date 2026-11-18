<script setup>
/**
 * 球局详情页
 * - 基本信息 + 状态标签 + 人数进度 + 匹配分与推荐理由
 * - 操作：加入球局 / 退出（loading 防重复）| 发起人：去核销 / 结束球局
 * - 成员头像墙（正式 + 候补）
 * - 场地/时间冲突等错误由统一拦截器 Toast 展示后端原文
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { gameApi } from '@/api'
import { useUserStore } from '@/stores/user'
import CatIcon from '@/components/CatIcon.vue'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const gameId = route.params.id
const game = ref(null)
const members = ref([])
const loading = ref(true)
const acting = ref(false)

const SPORT_NAME = { 1: '篮球', 2: '足球', 3: '羽毛球', 4: '网球', 5: '排球', 6: '乒乓球' }
const STATUS_TEXT = { 0: '草稿', 1: '报名中', 2: '报名截止', 3: '进行中', 4: '已结束', 5: '已取消' }

const isCreator = computed(() => Boolean(game.value && game.value.is_creator))
const progress = computed(() => {
  if (!game.value) return 0
  return Math.min(100, Math.round(((game.value.current_players || 0) / (game.value.max_players || 1)) * 100))
})
const slotsLeft = computed(() =>
  game.value ? game.value.slots_left ?? Math.max(0, game.value.max_players - game.value.current_players) : 0
)
const myStatus = computed(() => game.value?.my_registration_status)
const canJoin = computed(() => game.value?.status === 1 && slotsLeft.value > 0 && myStatus.value !== 1)
const canExit = computed(() => myStatus.value === 1 || myStatus.value === 3)
const canVerify = computed(
  () => isCreator.value && game.value?.settle_status === 0 && !['已结束', '已取消'].includes(STATUS_TEXT[game.value?.status])
)

function fmt(v) {
  if (!v) return '待定'
  const d = new Date(String(v).replace(' ', 'T'))
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}月${d.getDate()}日 ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function load() {
  loading.value = true
  try {
    game.value = await gameApi.detail(gameId)
    members.value = await gameApi.members(gameId)
  } finally {
    loading.value = false
  }
}

async function join() {
  if (!store.isLoggedIn) {
    router.push({ name: 'login', query: { redirect: route.fullPath } })
    return
  }
  acting.value = true
  try {
    const res = await gameApi.signup(gameId)
    ElMessage.success(res.message || '报名成功')
    await load()
  } catch (e) {
    /* 统一提示 */
  } finally {
    acting.value = false
  }
}

async function exit() {
  try {
    await ElMessageBox.confirm(
      '退出后名额会让给候补同学；距开球 2 小时内退出会记入画像（-4 分），确定退出吗？',
      '退出球局',
      { confirmButtonText: '确认退出', cancelButtonText: '再想想', type: 'warning' }
    )
  } catch {
    return
  }
  acting.value = true
  try {
    const res = await gameApi.exit(gameId, '用户主动退出')
    ElMessage.success(res.message || '已退出球局')
    await load()
  } catch (e) {
    /* 统一提示 */
  } finally {
    acting.value = false
  }
}

async function finish() {
  try {
    await ElMessageBox.confirm(
      '结束后立刻执行缺席判定：已报名 + 未签到 + 未请假的同学会被记缺席（-10 分）并自动禁赛 3 天。',
      '结束球局',
      { confirmButtonText: '确认结束', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  acting.value = true
  try {
    const res = await gameApi.finish(gameId)
    ElMessage.success(res.message || '球局已结束')
    await load()
  } finally {
    acting.value = false
  }
}

onMounted(() => {
  load()
  if (store.isLoggedIn) store.loadExtras()
})
</script>

<template>
  <div class="page">
    <el-skeleton v-if="loading" :rows="8" animated />

    <template v-else-if="game">
      <el-row :gutter="16">
        <el-col :xs="24" :md="15">
          <!-- 主信息卡 -->
          <div class="card detail">
            <div class="detail__head">
              <div class="detail__sport">
                <CatIcon :size="40" color="#DB9A63" fill="#FBF1E5" />
                <div>
                  <h1 class="t-section">{{ game.title }}</h1>
                  <p class="t-caption">
                    {{ SPORT_NAME[game.sport_type] }} · {{ game.campus }} · {{ game.venue_name }}
                  </p>
                </div>
              </div>
              <div class="detail__match">
                <b>{{ game.match_score }}</b>
                <span>匹配分</span>
              </div>
            </div>

            <div class="detail__tags">
              <span class="pill pill--green">{{ STATUS_TEXT[game.status] }}</span>
              <span v-if="slotsLeft > 0" class="pill pill--primary">还差 {{ slotsLeft }} 人</span>
              <span v-else class="pill pill--danger">已满 · 可候补</span>
              <span v-if="game.gender_limit === 2" class="pill pill--pink">女生友好</span>
              <span v-if="game.fee_type === 1" class="pill pill--blue">人均 ¥{{ game.fee_amount }}</span>
              <span v-if="game.min_credit_score" class="pill pill--warn">信誉分 ≥{{ game.min_credit_score }}</span>
            </div>

            <el-descriptions :column="1" border class="detail__desc">
              <el-descriptions-item label="开球时间">{{ fmt(game.start_time) }} ~ {{ fmt(game.end_time) }}</el-descriptions-item>
              <el-descriptions-item label="报名截止">{{ fmt(game.signup_deadline) }}</el-descriptions-item>
              <el-descriptions-item label="核销窗口">
                {{ fmt(game.checkin_start_time) }} ~ {{ fmt(game.checkin_end_time) }}
              </el-descriptions-item>
              <el-descriptions-item label="场地">{{ game.campus }} · {{ game.venue_name }}（{{ game.venue_address || '未填' }}）</el-descriptions-item>
              <el-descriptions-item label="人数">
                {{ game.current_players }}/{{ game.max_players }}
                <span v-if="game.waitlist_count">（候补 {{ game.waitlist_count }} 人）</span>
              </el-descriptions-item>
              <el-descriptions-item label="已到场">{{ game.checked_count || 0 }} 人 · 未核销 {{ game.not_checked_count || 0 }} 人</el-descriptions-item>
            </el-descriptions>

            <p v-if="game.description" class="detail__desc-text">{{ game.description }}</p>

            <div class="detail__bar">
              <div class="detail__bar-track">
                <div class="detail__bar-fill" :style="{ width: progress + '%' }" />
              </div>
              <span class="t-caption">{{ progress }}%</span>
            </div>

            <div class="detail__actions">
              <el-button v-if="canJoin" type="primary" size="large" round :loading="acting" @click="join">
                加入球局
              </el-button>
              <el-button v-else-if="canExit" size="large" round :loading="acting" @click="exit">退出球局</el-button>
              <el-button v-else type="primary" size="large" round disabled>已结束/不可报名</el-button>
              <el-button v-if="isCreator && canVerify" size="large" round :loading="acting" @click="finish">
                结束球局并判缺席
              </el-button>
            </div>

            <p v-if="game.match_reason" class="detail__reason">
              <el-icon><MagicStick /></el-icon> 推荐理由：{{ game.match_reason }}
            </p>
          </div>
        </el-col>

        <el-col :xs="24" :md="9">
          <!-- 发起人 + 成员 -->
          <div class="card side">
            <h3 class="t-card-title">发起人</h3>
            <div class="side__creator">
              <CatIcon :size="30" color="#49413B" />
              <div>
                <p class="side__name">{{ game.creator_nickname || '同学' }}</p>
                <p class="t-caption">信誉分 {{ game.creator_credit_score ?? '—' }}</p>
              </div>
            </div>

            <div class="section-head">
              <h3 class="t-card-title">已报名 {{ members.filter((m) => m.status === 1).length }} 人</h3>
              <RouterLink v-if="isCreator" :to="{ name: 'checkin-verify', params: { id: game.id } }">
                <span class="section-head__more">去核销 ></span>
              </RouterLink>
            </div>
            <ul class="side__members">
              <li v-for="m in members" :key="m.user_id">
                <span class="side__avatar"><CatIcon :size="20" color="#69625A" /></span>
                <span class="side__member-name">{{ m.nickname }}</span>
                <span class="t-caption">信誉 {{ m.credit_score }}</span>
                <span v-if="m.is_waitlist" class="pill pill--ghost">候补</span>
              </li>
            </ul>
            <el-empty v-if="!members.length" description="还没有人报名" :image-size="60" />
          </div>
        </el-col>
      </el-row>
    </template>

    <el-empty v-else description="球局不存在或已删除" />
  </div>
</template>

<style scoped lang="scss">
.detail {
  padding: var(--sp-5);
}
.detail__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-3);
}
.detail__sport {
  display: flex;
  gap: 12px;
  align-items: center;
  min-width: 0;
}
.detail__sport h1 {
  margin: 0;
}
.detail__match {
  flex: none;
  text-align: center;
  background: var(--c-primary-tint);
  border-radius: var(--r-md);
  padding: 8px 12px;
}
.detail__match b {
  display: block;
  font-size: 20px;
  color: var(--c-primary-dark);
}
.detail__match span {
  font-size: 10.5px;
  color: var(--c-text-muted);
}
.detail__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: var(--sp-3) 0;
}
.detail__desc {
  margin-bottom: var(--sp-3);
}
.detail__desc-text {
  font-size: 13px;
  color: var(--c-text-sub);
  background: var(--c-bg-soft);
  border-radius: var(--r-md);
  padding: 10px 12px;
}
.detail__bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: var(--sp-3) 0;
}
.detail__bar-track {
  flex: 1;
  height: 8px;
  border-radius: var(--r-pill);
  background: var(--c-line-soft);
  overflow: hidden;
}
.detail__bar-fill {
  height: 100%;
  background: var(--c-primary);
  border-radius: var(--r-pill);
}
.detail__actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: var(--sp-3);
}
.detail__reason {
  margin: var(--sp-3) 0 0;
  font-size: 12.5px;
  color: var(--c-primary-dark);
  display: flex;
  align-items: center;
  gap: 6px;
}
.side {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.side__creator {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  background: var(--c-bg-soft);
  border-radius: var(--r-md);
}
.side__name {
  margin: 0;
  font-weight: 700;
}
.side__members {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.side__members li {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.side__avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--c-bg-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
.side__member-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
