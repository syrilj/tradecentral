import { fileURLToPath } from 'node:url'
import { loadEnv } from 'vite'

const repoDir = fileURLToPath(new URL('../..', import.meta.url))
const env = loadEnv('preview', repoDir, '')
const errors = []
if (env.VITE_EDGE_AUTH_MODE !== 'clerk') {
  errors.push('VITE_EDGE_AUTH_MODE must be clerk for a preview build')
}
if (!String(env.VITE_CLERK_PUBLISHABLE_KEY ?? '').startsWith('pk_test_')) {
  errors.push('Preview builds must use a Clerk development publishable key')
}
if (env.VITE_CONVEX_URL !== 'https://exciting-jaguar-590.convex.cloud') {
  errors.push('Preview build must use the owner-scoped TradeCentral Convex development deployment')
}
if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(env.VITE_EDGE_ALLOWED_EMAILS ?? '').trim())) {
  errors.push('VITE_EDGE_ALLOWED_EMAILS must contain one operator email for the preview')
}
if (errors.length) {
  for (const error of errors) process.stderr.write(`Preview build blocked: ${error}\n`)
  process.exit(1)
}
