<script setup>
/**
 * 我的球局：我发起的 / 我报名的
 * 数据来源：/game?creator_id=自己 与 /game?keyword= 全量后按 my_registration_status 过滤
 * （后端列表已返回 my_registration_status，无需额外接口）
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { gameApi } from '@/api'
import { useUserStore } from '@/stores/user'
import { useResponsive, gridCols, gridGutter } from '@/composables/useResponsive'
import GameCard from '@/components/GameCard.vue'
import BanBanner from '@/components/BanBanner.vue'

const router = useRouter()
const store = useUserStore()
const { isMobile } = useResponsive()

const tab = ref('joined') // joined | created
const loading = ref(false)
const joined = ref([])
const created = ref([])

async function load() {
  if (!store.user?.id) await store.fetchMe()
  loading.value = true
  try {
    const [all, mine] = await Promise.all([
      gameApi.list({ page: 1, page_size: 50 }),
      gameApi.list({ page: 1, page_size: 50, creator_id: store.user.id })
    ])
    joined.value = (all.list || []).filter((g) => g.my_registration_status === 1 || g.my_registration_status === 3)
    created.value = mine.list || []
  } finally {
    loading.value = false
  }
}

const list = computed(() => (tab.value === 'joined' ? joined.value : created.value))

function open(g) {
  router.push({ name: 'game-detail', params: { id: g.id } })
}

onMounted(async () => {
  await store.loadExtras()
  await load()
})
</script>

<template>
  <div class="page">
    <div class="section-head">
      <h2 class="t-section">我的球局</h2>
      <span class="section-head__more" @click="router.push({ name: 'game-create' })">+ 发起新球局</span>
    </div>

    <BanBanner v-if="store.isBanned" :ban="store.ban" compact class="mb" />

    <div class="mytabs">
      <button :class="{ 'is-active': tab === 'joined' }" @click="tab = 'joined'">
        我报名的 <b>{{ joined.length }}</b>
      </button>
      <button :class="{ 'is-active': tab === 'created' }" @click="tab = 'created'">
        我发起的 <b>{{ created.length }}</b>
      </button>
    </div>

    <el-skeleton v-if="loading" :rows="5" animated />
    <el-row v-else :gutter="gridGutter">
      <el-col v-for="g in list" :key="g.id" :xs="24" :sm="12" :md="8" class="col-gap">
        <GameCard :game="g" :show-join="false" @open="open" />
      </el-col>
    </el-row>

    <el-empty
      v-if="!loading && !list.length"
      :description="tab === 'joined' ? '还没报名任何球局，去广场看看' : '还没发起过球局'"
      class="placeholder-box"
    >
      <el-button type="primary" round @click="router.push({ name: 'home' })">去球局广场</el-button>
    </el-empty>
  </div>
</template>

<style scoped lang="scss">
.mytabs {
  display: flex;
  gap: 6px;
  background: var(--c-primary-tint);
  border-radius: var(--r-pill);
  padding: 4px;
  margin-bottom: var(--sp-4);
  max-width: 420px;
}
.mytabs button {
  flex: 1;
  border: none;
  background: transparent;
  height: 40px;
  border-radius: var(--r-pill);
  font-size: 14px;
  font-weight: 700;
  color: var(--c-text-sub);
  cursor: pointer;
  transition: all 0.16s ease;
}
.mytabs button.is-active {
  background: var(--c-primary);
  color: #fff;
  box-shadow: var(--sh-primary);
}
.mytabs b {
  font-weight: 800;
}
.col-gap {
  margin-bottom: 14px;
}
.mb {
  margin-bottom: var(--sp-4);
}
</style>
