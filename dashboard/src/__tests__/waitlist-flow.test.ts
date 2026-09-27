import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const authSource = readFileSync(join(srcRoot, 'views', 'AuthView.vue'), 'utf8')
const landingSource = readFileSync(join(srcRoot, 'views', 'LandingView.vue'), 'utf8')
const routerSource = readFileSync(join(srcRoot, 'router.ts'), 'utf8')

describe('Clerk waitlist flow', () => {
  it('routes landing access requests to the named waitlist route', () => {
    expect(landingSource).toContain("to=\"{ name: 'waitlist', query: { redirect: '/flow' } }\"")
    expect(landingSource).toContain('Request operator access')
    expect(routerSource).toContain("path: '/waitlist'")
    expect(routerSource).toContain("name: 'waitlist'")
    expect(authSource).toMatch(/mode = computed\(\(\) =>\s*route\.name === 'waitlist'/)
  })

  it('uses Clerk Waitlist when Clerk is ready', () => {
    expect(authSource).toContain("import { SignIn, Waitlist, useAuth, useClerk, useUser } from '@clerk/vue'")
    expect(authSource).toContain('<Waitlist v-else-if="hasClerk" sign-in-url="/auth" />')
    expect(authSource).toContain('const hasClerk = computed(() => !localMode && isLoaded.value && clerk.value != null)')
  })

  it('states that a request was not submitted when Clerk is unavailable', () => {
    expect(authSource).toContain('Waitlist unavailable')
    expect(authSource).toMatch(/no request has been submitted/i)
    expect(authSource).toContain('Waitlist requests require Clerk, which is not configured in local mode.')
    expect(authSource).toContain('role="status"')
  })

  it('has no simulated submission, local ticket, or fake confirmation path', () => {
    expect(authSource).not.toContain('WaitlistForm')
    expect(authSource).not.toContain('createWaitlistSubmission')
    expect(authSource).not.toContain('setTimeout(')
    expect(authSource).not.toContain('localStorage')
    expect(authSource).not.toContain('QUEUED FOR REVIEW')
  })
})
