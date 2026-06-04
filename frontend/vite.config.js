import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const allowedHosts = (process.env.MIROFISH_ALLOWED_HOSTS || 'mirofish.pdurlej.com')
  .split(',')
  .map((host) => host.trim())
  .filter(Boolean)

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    allowedHosts,
    port: 3000,
    open: true,
    proxy: {
      '/api': {
        target: 'http://localhost:5001',
        changeOrigin: true,
        secure: false
      }
    }
  }
})
