import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Панель собирается в dist/; бэкенд (FastAPI) может отдавать её как статику.
// В режиме разработки /api и /media проксируются на uvicorn (порт 8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/media': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
