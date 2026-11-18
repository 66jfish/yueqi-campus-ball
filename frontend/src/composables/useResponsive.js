/**
 * 响应式断点（对齐 Element Plus 栅格断点）
 *   xs  <768px   手机：单列 + 底部导航
 *   sm  768-992  平板：双列
 *   md  ≥992px   桌面：多列 + 顶部导航
 */
import { onMounted, onUnmounted, ref } from 'vue'

const BREAKPOINTS = { sm: 768, md: 992, lg: 1200 }

export function useResponsive() {
  const width = ref(typeof window === 'undefined' ? 1280 : window.innerWidth)
  const isMobile = ref(width.value < BREAKPOINTS.sm)
  const isTablet = ref(width.value >= BREAKPOINTS.sm && width.value < BREAKPOINTS.md)
  const isDesktop = ref(width.value >= BREAKPOINTS.md)

  const update = () => {
    width.value = window.innerWidth
    isMobile.value = width.value < BREAKPOINTS.sm
    isTablet.value = width.value >= BREAKPOINTS.sm && width.value < BREAKPOINTS.md
    isDesktop.value = width.value >= BREAKPOINTS.md
  }

  onMounted(() => {
    update()
    window.addEventListener('resize', update, { passive: true })
  })
  onUnmounted(() => window.removeEventListener('resize', update))

  return { width, isMobile, isTablet, isDesktop, BREAKPOINTS }
}

/** Element 栅格 span：手机 24（整行）、平板 12（两列）、桌面 8（三列） */
export const gridCols = { xs: 24, sm: 12, md: 8, lg: 8 }
export const gridGutter = { xs: 12, sm: 14, md: 16 }
