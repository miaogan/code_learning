/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// 开发期：前端 :5173 通过代理访问后端 :8000，因此 src/api/client.ts 默认用同源相对路径。
// 生产/独立部署：设置 VITE_API_BASE（仅此一个前端可配项，绝不出现密钥）。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        /**
         * vendor 单独成块（r151 性能收尾）：框架代码几乎不随业务变化，
         * 拆出去后每次发版用户只需重下业务代码，vendor 长期命中缓存。
         *
         * 教程正文**不拆**：实测它被 Learn/Tutorial/Search 多个懒加载页共享，
         * Rollup 会把它提升为入口依赖——拆出来只是多一个请求（跨境 RTT 上更慢），
         * 并没有延后加载（实测登录页 0.6s → 2.2s 的回退已回退）。
         */
        manualChunks(id: string) {
          if (id.includes('node_modules')) return 'vendor'
          return undefined
        },
      },
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
