import { createRouter, createWebHistory } from 'vue-router'

/** 需要登录的路由 meta.requiresAuth = true */
const routes = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/Home.vue'),
    meta: { title: '球局广场', nav: 'home', navIcon: 'HomeFilled', navText: '首页' }
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录 / 注册', hideNav: true }
  },
  {
    path: '/games/:id',
    name: 'game-detail',
    component: () => import('@/views/GameDetail.vue'),
    meta: { title: '球局详情' }
  },
  {
    path: '/create',
    name: 'game-create',
    component: () => import('@/views/GameCreate.vue'),
    meta: { title: '发起球局', requiresAuth: true, nav: 'create', navIcon: 'AddCircle', navText: '发局' }
  },
  {
    path: '/my',
    name: 'my-games',
    component: () => import('@/views/MyGames.vue'),
    meta: { title: '我的球局', requiresAuth: true, nav: 'my', navIcon: 'Flag', navText: '我的球局' }
  },
  {
    path: '/verify/:id',
    name: 'checkin-verify',
    component: () => import('@/views/CheckinVerify.vue'),
    meta: { title: '签到核销', requiresAuth: true }
  },
  {
    path: '/me',
    name: 'profile',
    component: () => import('@/views/ProfilePage.vue'),
    meta: { title: '个人主页', requiresAuth: true, nav: 'me', navIcon: 'User', navText: '我的' }
  },
  {
    path: '/u/:id',
    name: 'user-profile',
    component: () => import('@/views/ProfilePage.vue'),
    meta: { title: '个人主页' }
  },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

/** 全局登录守卫：未登录访问受限页面 → 跳登录页并记住来源 */
router.beforeEach((to) => {
  const token = localStorage.getItem('mq_token')
  if (to.meta.requiresAuth && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.title) {
    document.title = `${to.meta.title} · ${import.meta.env.VITE_APP_TITLE || '搭子月球'}`
  }
  return true
})

export default router

/** 手机底部导航项（设计稿：底部固定 3-4 个入口） */
export const bottomNavItems = routes
  .filter((r) => r.meta?.nav)
  .map((r) => ({ name: r.name, text: r.meta.navText, icon: r.meta.navIcon, key: r.meta.nav }))
