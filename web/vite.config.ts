import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发态：前端 5173，接口与 SSE 反向代理到后端 8787。
// 生产态：pnpm build 产物 web/dist 由 FastAPI 同源托管。
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
