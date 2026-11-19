<script setup>
/**
 * 球局广场（首页）—— 复刻设计稿
 *   ① 顶部品牌区由 AppLayout 统一承载（品牌名 + 标语 + 右侧圆形猫头）
 *   ② 核心行动区：主标题「在月球，找到你的约球搭子
约一场不掉线的球」+ 橙色「立即约球」按钮
 *   ③ 球类选择区：2x2 网格（手机）/ 6 列（桌面）
 *   ④ 附近热局：卡片列表（手机单列、平板两列、桌面三列）+「全部 >」入口
 *   ⑤ 筛选：球类 / 校区 / 只看可报名
 */
defineOptions({ name: 'HomeView' }) // 供 App.vue keep-alive 缓存

import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { gameApi } from '@/api'
import { useUserStore } from '@/stores/user'
import { useResponsive, gridCols, gridGutter } from '@/composables/useResponsive'
import GameCard from '@/components/GameCard.vue'
import SportGrid from '@/components/SportGrid.vue'
import BanBanner from '@/components/BanBanner.vue'

const router = useRouter()
const store = useUserStore()
const { isMobile } = useResponsive()

const loading = ref(false)
const joiningId = ref(null)
const games = ref([])
const total = ref(0)

const filters = ref({ sport_type: 0, campus: '', only_available: true, page: 1, page_size: 9 })
const campuses = ['老校区', '新校区', '校外']

const heroTitle = '在月球，找到你的约球搭子\n约一场不掉线的球'

async function load() {
  loading.value = true
  try {
    const params = {
      page: filters.value.page,
      page_size: filters.value.page_size,
      only_available: filters.value.only_available || undefined,
      campus: filters.value.campus || undefined,
      sport_type: filters.value.sport_type || undefined
    }
    const data = await gameApi.list(params)
    games.value = data.list || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

/** 加入球局：按钮 loading 防重复提交；失败由统一拦截器提示（含小黑屋弹窗） */
async function join(game) {
  if (!store.isLoggedIn) {
    router.push({ name: 'login', query: { redirect: '/' } })
    return
  }
  if (game.my_registration_status === 1) {
    router.push({ name: 'game-detail', params: { id: game.id } })
    return
  }
  joiningId.value = game.id
  try {
    const res = await gameApi.signup(game.id)
    ElMessage.success(res.message || '报名成功')
    await load()
  } catch (e) {
    /* 统一拦截器已提示 */
  } finally {
    joiningId.value = null
  }
}

function open(game) {
  router.push({ name: 'game-detail', params: { id: game.id } })
}

function goCreate() {
  router.push({ name: store.isLoggedIn ? 'game-create' : 'login', query: { redirect: '/create' } })
}

/** 球类徽标数量（球类网格需要全部球局的分布，故单独取一份不带筛选的数据） */
const sportSource = ref([])
async function loadSportSource() {
  const data = await gameApi.list({ page: 1, page_size: 50 })
  sportSource.value = data.list || []
}

function pickSport(type) {
  filters.value.sport_type = type
  load()
}

onMounted(async () => {
  await Promise.all([load(), loadSportSource()])
  if (store.isLoggedIn) store.loadExtras()
})

const shownCount = computed(() => games.value.length)
</script>

<template>
  <div class="page">
    <!-- ② 核心行动区 -->
    <section class="hero">
      <div class="hero__text">
        <h1 class="t-hero">{{ heroTitle }}</h1>
        <p class="hero__sub">本周月球值日 · 齐刘海｜在月球，找到你的约球搭子</p>
        <div class="hero__actions">
          <el-button type="primary" size="large" round @click="goCreate">
            <el-icon><Plus /></el-icon>&nbsp;立即约球
          </el-button>
          <el-button text @click="router.push({ name: 'my-games' })">查看我的球局</el-button>
        </div>
      </div>
      <div class="hero__art" aria-hidden="true">
        <span class="hero__blob" />
        <span class="hero__badge">月球监督 · 不掉线</span>
      </div>
    </section>

    <!-- 封禁提示（细条，不打断浏览） -->
    <BanBanner v-if="store.isBanned" :ban="store.ban" compact class="mt-block" />

    <!-- ③ 球类选择区 -->
    <div class="section-head">
      <h2 class="t-section">选个球类</h2>
      <span class="section-head__more" @click="pickSport(0)">全部球类 ></span>
    </div>
    <SportGrid
      :games="sportSource"
      :model-value="filters.sport_type"
      @update:model-value="pickSport"
    />

    <!-- ⑤ 筛选 -->
    <div class="section-head">
      <h2 class="t-section">附近热局</h2>
      <span class="section-head__more" @click="load">全部 {{ total }} ></span>
    </div>
    <div class="filters">
      <el-radio-group v-model="filters.campus" size="small" @change="load">
        <el-radio-button :value="''">全部校区</el-radio-button>
        <el-radio-button v-for="c in campuses" :key="c" :value="c">{{ c }}</el-radio-button>
      </el-radio-group>
      <el-checkbox v-model="filters.only_available" size="small" @change="load">只看可报名</el-checkbox>
    </div>

    <!-- ④ 热局列表：手机单列 / 平板两列 / 桌面三列 -->
    <el-skeleton v-if="loading" :rows="6" animated class="mt-block" />
    <el-row v-else :gutter="gridGutter" class="mt-block">
      <el-col v-for="g in games" :key="g.id" :xs="24" :sm="12" :md="8" class="col-gap">
        <GameCard :game="g" :joining="joiningId === g.id" @join="join" @open="open" />
      </el-col>
    </el-row>

    <el-empty
      v-if="!loading && !shownCount"
      description="这个筛选下还没有球局，换个条件或自己发起一个吧"
      class="placeholder-box"
    />

    <div v-if="total > games.length" class="more">
      <el-button round text @click="filters.page += 1; load()">加载更多</el-button>
    </div>
  </div>
</template>

<style scoped lang="scss">
/* 核心行动区 */
.hero {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  padding: var(--sp-5);
  border-radius: var(--r-xl);
  background: linear-gradient(135deg, #fdf6ec 0%, #f9ecdc 60%, #f6e3cf 100%);
  border: 1px solid #f3e2cd;
  box-shadow: var(--sh-2);
  overflow: hidden;
}
.hero__text {
  min-width: 0;
}
.t-hero {
  white-space: pre-line;
  margin: 0 0 8px;
}
.hero__sub {
  margin: 0 0 16px;
  font-size: 12.5px;
  color: var(--c-text-sub);
}
.hero__actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.hero__art {
  position: relative;
  flex: none;
  width: 120px;
  height: 90px;
}
.hero__blob {
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 60% 40%, rgba(219, 154, 100, 0.55), rgba(219, 154, 100, 0));
  border-radius: 50%;
  filter: blur(2px);
}
.hero__badge {
  position: absolute;
  bottom: 6px;
  right: 0;
  background: #fff;
  border-radius: var(--r-pill);
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 700;
  color: var(--c-primary-dark);
  box-shadow: var(--sh-2);
}
@media (max-width: 767px) {
  .hero {
    flex-direction: column;
    align-items: flex-start;
  }
  .hero__art {
    display: none;
  }
}

/* 筛选条 */
.filters {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  flex-wrap: wrap;
}
.mt-block {
  margin-top: var(--sp-4);
}
.col-gap {
  margin-bottom: 14px;
}
.more {
  text-align: center;
  margin-top: var(--sp-4);
}
</style>
