import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 开发契约保持不变：
//   端口 5666，`/api` 代理到后端（默认 8000，可用 VITE_API_TARGET 覆盖），并把 `/api` 前缀重写为 `/api/v1`。
// 后端路由全部挂载在 /api/v1 之下（见 app/main.py），因此前端统一以 `/api` 为基准书写路径。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5666,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '/api/v1'),
      },
    },
  },
})
