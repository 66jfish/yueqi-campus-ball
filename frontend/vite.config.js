import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    host: true,
    // 开发环境如需直连后端又不想配 CORS，可打开代理，并把 VITE_API_BASE_URL 设为 /api/v1
    // proxy: {
    //   '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true }
    // }
  },
  build: {
    outDir: 'dist',       // ★ npm run build 产物目录：frontend/dist
    assetsDir: 'assets',
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          vue: ['vue', 'vue-router', 'pinia'],
          element: ['element-plus', '@element-plus/icons-vue']
        }
      }
    }
  }
})

