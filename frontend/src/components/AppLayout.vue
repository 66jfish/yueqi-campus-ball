<script setup>
/**
 * 全局布局
 *   手机（<768px）  ：顶部品牌栏 + 单列内容 + 底部导航（fixed）
 *   平板（768-992） ：顶部品牌栏 + 内容（栅格两列）
 *   桌面（≥992px）  ：顶部品牌栏 + 内容（栅格多列）+ 顶部导航项
 * 底部导航与顶部导航项来自 router 的 meta.nav 配置，新增页面只改路由即可。
 */
import { computed } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { bottomNavItems } from '@/router'
import { useResponsive } from '@/composables/useResponsive'
import { useUserStore } from '@/stores/user'
import CatIcon from './CatIcon.vue'

const route = useRoute()
const router = useRouter()
const store = useUserStore()
const { isMobile } = useResponsive()

const navItems = computed(() => bottomNavItems)
const currentNav = computed(() => route.meta?.nav)
const showNav = computed(() => !route.meta?.hideNav)

function go(name) {
  router.push({ name })
}
</script>

<template>
  <div class="shell">
    <!-- ============ 顶部品牌栏（设计稿：左品牌+标语，右圆形猫头） ============ -->
    <header class="topbar">
      <div class="topbar__inner">
        <RouterLink to="/" class="brand">
          <CatIcon :size="30" color="#DB9A64" />
          <span class="brand__text">
            <span class="brand__name">搭子月球</span>
            <span class="brand__slogan">在月球，找到你的约球搭子</span>
          </span>
        </RouterLink>

        <!-- 桌面端导航 -->
        <nav v-if="!isMobile && showNav" class="topnav">
          <button
            v-for="item in navItems"
            :key="item.name"
            class="topnav__item"
            :class="{ 'is-active': currentNav === item.key }"
            @click="go(item.name)"
          >
            {{ item.text }}
          </button>
        </nav>

        <div class="topbar__right">
          <template v-if="store.isLoggedIn">
            <RouterLink to="/me" class="avatar" :title="store.displayName">
              <CatIcon :size="24" color="#49413B" />
            </RouterLink>
          </template>
          <el-button v-else size="small" type="primary" round @click="go('login')">登录</el-button>
        </div>
      </div>
    </header>

    <!-- ============ 内容区 ============ -->
    <main class="content">
      <slot />
    </main>

    <!-- ============ 手机底部导航（设计稿：fixed 底部 4 入口） ============ -->
    <nav v-if="isMobile && showNav" class="bottomnav safe-bottom">
      <button
        v-for="item in navItems"
        :key="item.name"
        class="bottomnav__item"
        :class="{ 'is-active': currentNav === item.key }"
        @click="go(item.name)"
      >
        <el-icon :size="20"><component :is="item.icon" /></el-icon>
        <span>{{ item.text }}</span>
      </button>
    </nav>
  </div>
</template>

<style scoped lang="scss">
.shell {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

/* ---------------- 顶部品牌栏 ---------------- */
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  background: rgba(249, 244, 233, 0.92);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--c-line-soft);
}
.topbar__inner {
  max-width: var(--page-max);
  margin: 0 auto;
  height: var(--top-h);
  padding: 0 var(--sp-4);
  display: flex;
  align-items: center;
  gap: var(--sp-4);
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--c-text);
}
.brand__text {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
}
.brand__name {
  font-size: 17px;
  font-weight: 800;
  letter-spacing: 0.5px;
}
.brand__slogan {
  font-size: 11px;
  color: var(--c-text-muted);
}
.topnav {
  display: flex;
  gap: var(--sp-1);
  margin-left: auto;
}
.topnav__item {
  border: none;
  background: transparent;
  padding: 8px 14px;
  border-radius: var(--r-pill);
  font-size: 14px;
  font-weight: 600;
  color: var(--c-text-sub);
  cursor: pointer;
  transition: all 0.16s ease;
}
.topnav__item:hover {
  background: var(--c-primary-tint);
  color: var(--c-text);
}
.topnav__item.is-active {
  background: var(--c-primary);
  color: #fff;
  box-shadow: var(--sh-primary);
}
.topbar__right {
  margin-left: auto;
  display: flex;
  align-items: center;
}
.topnav + .topbar__right {
  margin-left: var(--sp-3);
}
.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--c-primary-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1.5px solid #fff;
  box-shadow: var(--sh-1);
}

/* ---------------- 内容 ---------------- */
.content {
  flex: 1;
  min-width: 0;
}

/* ---------------- 手机底部导航 ---------------- */
.bottomnav {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 30;
  height: var(--nav-h);
  display: flex;
  align-items: center;
  justify-content: space-around;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(12px);
  border-top: 1px solid var(--c-line-soft);
  box-shadow: 0 -6px 18px rgba(73, 65, 59, 0.05);
}
.bottomnav__item {
  flex: 1;
  border: none;
  background: transparent;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  color: var(--c-text-muted);
  cursor: pointer;
  padding: 6px 0;
  transition: color 0.16s ease, transform 0.16s ease;
}
.bottomnav__item.is-active {
  color: var(--c-primary-dark);
  font-weight: 700;
  transform: translateY(-1px);
}
</style>
