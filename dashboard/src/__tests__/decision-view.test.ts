import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const source = (path: string): string => readFileSync(join(root, path), 'utf8')

describe('TypeSafe live decision surface', () => {
  const view = source('views/DecisionView.vue')
  const api = source('api.ts')
  const router = source('router.ts')
  const app = source('App.vue')

  it('is registered as a primary operator destination', () => {
    expect(router).toMatch(/path:\s*['"]\/decision['"]/)
    expect(router).toMatch(/name:\s*['"]decision['"]/)
    expect(app).toMatch(/name:\s*['"]decision['"]/)
    expect(app).toContain("title: 'Decision'")
  })

  it('loads the five independent source lenses before synthesis', () => {
    expect(view).toContain('api.options(')
    expect(view).toContain('api.marketRegime(')
    expect(view).toContain('regime?.flow.dealerGammaRegime')
    expect(view).toContain('api.vpaAnalyze(')
    expect(view).toContain('api.executionGate(')
    expect(view).toContain('sessionOnly: true')
    expect(view).toContain('Promise.allSettled')
  })

  it('calls the server-side TypeSafe endpoint and never exposes a credential', () => {
    expect(api).toContain("'/api/typesafe/live-decision'")
    expect(view).toContain('api.typeSafeLiveDecision(state)')
    expect(view).not.toContain('TYPESAFE_API_KEY=')
  })

  it('renders action, uncertainty, sources, and policy boundaries', () => {
    expect(view).toContain('BUY BIAS')
    expect(view).toContain('SELL BIAS')
    expect(view).toContain('WAIT')
    expect(view).toContain('Action probability distribution')
    expect(view).toContain('SOURCE TAPE')
    expect(view).toContain('POLICY BLOCKERS')
    expect(view).toContain('No order routing')
  })
})
