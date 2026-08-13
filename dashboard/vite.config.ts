import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

const repoDir = fileURLToPath(new URL('..', import.meta.url))

// Built output lands in edge/runs/dashboard_dist/, which api_server.py serves
// as the SPA root. Keeping the build inside runs/ means the dashboard ships
// with the artifacts it renders.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repoDir, '')
  return {
    plugins: [vue()],
    envDir: repoDir,
    define: {
      'import.meta.env.VITE_EDGE_ALLOWED_EMAILS': JSON.stringify(
        env.VITE_EDGE_ALLOWED_EMAILS || env.EDGE_ALLOWED_EMAILS || '',
      ),
    },
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    build: {
      outDir: '../runs/dashboard_dist',
      emptyOutDir: true,
      chunkSizeWarningLimit: 900,
    },
    server: {
      port: 5178,
      proxy: {
        '/api': { target: 'http://localhost:8787', changeOrigin: true },
      },
    },
  }
})
