import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Hosts the dev server answers to. Production serves the built SPA from
// Gunicorn, so this only matters when reaching `npm run dev` through a
// hostname — set MIROFISH_ALLOWED_HOSTS (comma-separated) for that.
const allowedHosts = (process.env.MIROFISH_ALLOWED_HOSTS || 'localhost')
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
