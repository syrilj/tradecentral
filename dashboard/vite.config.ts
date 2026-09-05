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
      target: 'es2022',
      cssCodeSplit: true,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes('node_modules')) {
              if (id.includes('three')) {
                return 'vendor-three'
              }
              if (id.includes('gsap')) {
                return 'vendor-gsap'
              }
              if (id.includes('echarts') || id.includes('zrender')) {
                return 'vendor-echarts'
              }
              if (id.includes('@clerk')) {
                return 'vendor-clerk'
              }
              if (id.includes('vue') || id.includes('vue-router')) {
                return 'vendor-vue'
              }
            }
          },
        },
      },
    },
    server: {
      port: 5178,
      proxy: {
        '/api': { target: 'http://localhost:8787', changeOrigin: true },
      },
    },
    test: {
      environment: 'node',
      coverage: {
        provider: 'v8',
        reporter: ['text', 'json-summary'],
        include: ['src/**/*.ts'],
        exclude: ['src/**/*.vue', 'src/**/__tests__/**'],
        thresholds: {
          lines: 60,
          functions: 60,
          statements: 60,
          branches: 50,
        },
      },
    },
  }
})
