import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 后端默认地址；可用环境变量覆盖，避免改代码。
const BACKEND_ORIGIN = process.env.VITE_BACKEND_ORIGIN || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 显式绑定 IPv4：Node 会把 localhost 解析成 ::1，只监听 IPv6 时
    // 浏览器直接打开 http://127.0.0.1:5173 会连不上。
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      // 前端统一请求 /api/**，由 dev server 转发到 FastAPI，规避跨域问题。
      '/api': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
      },
    },
  },
  build: {
    target: 'es2020',
    outDir: 'dist',
  },
})
