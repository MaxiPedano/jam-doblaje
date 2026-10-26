import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: process.env.BASE_PATH || '/',
  optimizeDeps: { entries: ['index.html'] },
  server: {
    watch: { ignored: ['**/.venv/**', '**/backend/**'] },
    proxy: { '/api': { target: process.env.STUDIO_API_TARGET || 'http://127.0.0.1:8765', changeOrigin: true, timeout: 660000, proxyTimeout: 660000 } },
  },
  preview: { proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true } } },
})
