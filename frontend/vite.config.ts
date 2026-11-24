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
         * 手工分块（r151 性能收尾）：教程正文 358KB 源码被 Learn/Tutorial/Search 等
         * 多个懒加载页共享，Rollup 默认会把它提升进入口 chunk——导致登录页也要付这笔钱。
         * 拆成独立 chunk 后入口只剩框架与壳；正文 chunk 只在进入学习类页面时拉取，
         * 且内容不变时长期命中浏览器缓存（文件名带 content hash）。
         */
        manualChunks(id: string) {
          if (id.includes('/src/content/tutorials/')) return 'tutorial-content'
          if (id.includes('/src/content/')) return 'content'
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
