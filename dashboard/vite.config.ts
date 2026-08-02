import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Built output lands in edge/runs/dashboard_dist/, which api_server.py serves
// as the SPA root. Keeping the build inside runs/ means the dashboard ships
// with the artifacts it renders.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    outDir: '../runs/dashboard_dist',
    emptyOutDir: true,
    // A trading desk should not be waiting on a 12-file waterfall.
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5178,
    // `npm run dev` proxies to the live Python API so the frontend can be
    // iterated on without rebuilding.
    proxy: {
      '/api': { target: 'http://localhost:8787', changeOrigin: true },
    },
  },
})
