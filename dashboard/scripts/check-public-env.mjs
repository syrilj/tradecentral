import { fileURLToPath } from 'node:url'
import { loadEnv } from 'vite'

const repoDir = fileURLToPath(new URL('../..', import.meta.url))
const env = loadEnv('production', repoDir, '')
const errors = []

if (env.VITE_EDGE_AUTH_MODE !== 'clerk') {
  errors.push('VITE_EDGE_AUTH_MODE must be clerk for a public build')
}
if (!String(env.VITE_CLERK_PUBLISHABLE_KEY ?? '').startsWith('pk_live_')) {
  errors.push('VITE_CLERK_PUBLISHABLE_KEY must be a Clerk production key')
}
if (!/^https:\/\/[^/]+\.convex\.cloud$/.test(String(env.VITE_CONVEX_URL ?? ''))) {
  errors.push('VITE_CONVEX_URL must be a production Convex deployment URL')
}

const emailList = String(env.VITE_EDGE_ALLOWED_EMAILS ?? '').trim().toLowerCase()
if (!/^[^@\s,]+@[^@\s,]+\.[^@\s,]+$/.test(emailList)) {
  errors.push('VITE_EDGE_ALLOWED_EMAILS must contain exactly one operator email')
}

if (errors.length) {
  for (const error of errors) process.stderr.write(`Public build blocked: ${error}\n`)
  process.exit(1)
}
