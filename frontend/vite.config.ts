import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 前端作为后端服务的「入口层」（M-11），开发期通过代理访问本地服务。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8756',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})