import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const authSource = readFileSync(join(root, 'auth.ts'), 'utf8')
const viewSource = readFileSync(join(root, 'views', 'AuthView.vue'), 'utf8')
const mockSource = readFileSync(join(root, 'components', 'FlowWorkspaceMockup.vue'), 'utf8')
const appSource = readFileSync(join(root, 'App.vue'), 'utf8')
const mainSource = readFileSync(join(root, 'main.ts'), 'utf8')

describe('Clerk operator access contract', () => {
  it('uses Clerk for the operator session instead of a local passphrase lock', () => {
    expect(mainSource).toContain('clerkPlugin')
    expect(mainSource).toContain("signInUrl: '/auth'")
    expect(viewSource).toContain('SignIn')
    expect(viewSource).toContain('from \'@clerk/vue\'')
    expect(authSource).not.toContain('PBKDF2')
    expect(viewSource).not.toContain('createOperatorCredential')
  })

  it('places Clerk on the right of the landing-to-flow close', () => {
    expect(viewSource).toContain('auth-shell')
    expect(viewSource).toContain('minmax(390px, 460px)')
    expect(viewSource).toContain('Unlock the instrument')
    expect(viewSource).toContain("safeRedirect(route.query.redirect, '/flow')")
    expect(appSource).toContain("name: 'auth'")
    expect(appSource).toContain('query: { redirect: route.fullPath }')
  })

  it('offers a direct sidebar sign-out action in addition to the account menu', () => {
    expect(appSource).toContain('const clerk = useClerk()')
    expect(appSource).toContain('async function signOut')
    expect(appSource).toContain('await clerk.value?.signOut()')
    expect(appSource).toContain("'SIGN OUT'")
  })

  it('keeps an honest workstation boundary', () => {
    expect(viewSource).toContain('The research API')
    expect(viewSource).toContain('still binds to 127.0.0.1')
    expect(viewSource).not.toContain('network authentication')
    expect(viewSource).not.toContain('guaranteed returns')
  })

  it('uses a structural Flow mockup with no invented quotes', () => {
    expect(viewSource).toContain('FlowWorkspaceMockup')
    expect(mockSource).toContain('SPY')
    expect(mockSource).toContain('QQQ')
    expect(mockSource).toContain('IWM')
    expect(mockSource).toContain('DIA')
    expect(mockSource).toContain('no invented')
    expect(mockSource).toContain('Window premium')
    expect(mockSource).toContain('—')
    expect(mockSource).not.toContain('5,321.41')
    expect(mockSource).not.toContain('guaranteed')
  })
})
