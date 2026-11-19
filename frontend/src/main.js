import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import 'element-plus/dist/index.css'      // Element 基础样式
import '@/styles/theme.scss'              // ★ 主题定制（覆盖主色/圆角/阴影/组件样式）
import '@/styles/app.scss'                // 全局视觉语言（卡片/标签/字体层级）

import App from './App.vue'
import router from './router'

const app = createApp(App)

// 全量注册 Element 图标（页面里直接 <el-icon><Search /></el-icon>）
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

document.title = import.meta.env.VITE_APP_TITLE || '搭子月球'

app.mount('#app')
