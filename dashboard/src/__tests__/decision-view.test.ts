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

  it('renders buy or sell with model confidence, not a withheld action', () => {
    expect(view).toContain('BUY')
    expect(view).toContain('SELL')
    expect(view).toContain('STANDBY')
    expect(view).toContain('confident this is the next action')
    expect(view).toContain("['buy', 'sell']")
    expect(view).not.toContain('BUY BIAS')
    expect(view).not.toContain('SELL BIAS')
    expect(view).not.toContain("['buy', 'wait', 'sell']")
    expect(view).not.toContain("?? 'wait'")
    expect(api).toContain("LiveDecisionAction = 'buy' | 'sell'")
    expect(api).not.toContain("'buy' | 'sell' | 'wait'")
  })

  it('surfaces issues as a risk assessment beside policy blockers', () => {
    expect(view).toContain('RISK ASSESSMENT')
    expect(view).toContain('risk_assessment')
    expect(view).toContain('POLICY BLOCKERS')
    expect(view).toContain('SOURCE TAPE')
    expect(view).toContain('No order routing')
    expect(view).toContain('confidence is model certainty, not win probability')
    expect(view).toContain('issues surface as risk')
  })

  it('overlays VPA next direction and claim-support on the source tape', () => {
    expect(view).toContain('vpa_judgment')
    expect(view).toContain('VPA next')
    expect(view).toContain('claim_support')
    expect(api).toContain('vpa_judgment')
    expect(api).toContain('risk_assessment')
  })

  it('renders the Decision Brain panel with multi-model confluence and jitter shield', () => {
    expect(view).toContain('DECISION BRAIN')
    expect(view).toContain('CONFLUENCE')
    expect(view).toContain('STABILIZED · JITTER SHIELD ACTIVE')
    expect(view).toContain('clampedConsensus')
    expect(view).toContain('meterFillStyle')
    expect(view).toContain('meterPointerLeft')
    expect(view).toContain('model-cards-grid')
    expect(view).toContain('model-vote-card')
  })

  it('is discoverable in SearchPalette command launcher and macro tools', () => {
    const palette = source('components/SearchPalette.vue')
    expect(palette).toContain("name: 'decision'")
    expect(palette).toContain("title: 'Decision'")
    expect(app).toContain("name: 'decision'")
    expect(app).toContain("idx: 'G3'")
  })
})
