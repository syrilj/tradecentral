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

  it('loads the six source lenses before synthesis with the bounded collector', () => {
    expect(view).toContain('api.options(')
    expect(view).toContain('api.quotes([requestedSymbol])')
    expect(view).toContain('api.marketRegime(')
    expect(view).toContain('regime?.flow.dealerGammaRegime')
    expect(view).toContain('api.vpaAnalyze(')
    expect(view).toContain('api.executionGate(')
    expect(view).toContain('api.kronosEvidence(requestedSymbol)')
    expect(view).toContain('collect(`${requestedSymbol}:forecast`')
    expect(view).toContain('forecast: forecast?.status ?? statusOf(forecastResult)')
    expect(view).toContain('{{ sourceRows.length }} source lenses')
    expect(view).toContain('{{ readyCount }}/4 DECISION LENSES READY')
    expect(view).toContain('LIVE SOURCE LENSES · OPERATOR ACTIVATED')
    expect(view).toContain('sessionOnly: true')
    expect(view).toContain('Promise.allSettled')
  })

  it('anchors the directional verdict to current price and measured structure', () => {
    const component = source('components/DecisionPriceContext.vue')
    const context = source('decisionPriceContext.ts')
    expect(view).toContain(
      'buildDecisionPriceContext({ symbol: requestedSymbol, quote, options, vpa })',
    )
    expect(view).toContain('<DecisionPriceContext')
    expect(component).toContain('PRICE CONTEXT')
    expect(component).toContain('CURRENT PRICE')
    expect(component).toContain('NEXT ABOVE')
    expect(component).toContain('NEXT BELOW')
    expect(component).toContain('These levels show structure, not an entry.')
    expect(context).toContain('VALUE AREA LOW')
    expect(context).toContain('POINT OF CONTROL')
    expect(context).toContain('VALUE AREA HIGH')
    expect(context).toContain('GAMMA FLIP')
    expect(context).toContain('Current price and measured structural levels are unavailable.')
  })

  it('types and flattens the Kronos evidence into the live-decision request', () => {
    expect(api).toContain("schema_version: 'kronos-evidence-v1'")
    expect(api).toContain(
      "export type KronosEvidenceStatus = 'ready' | 'missing' | 'stale' | 'error'",
    )
    expect(api).toContain('kronosEvidence: (symbol: string)')
    expect(api).toContain('/api/kronos/evidence?symbol=${encodeURIComponent(symbol)}')
    expect(view).toContain('forecastEvidence?.forecast.horizon')
    expect(view).toContain('forecastEvidence?.forecast.interval_80')
    expect(view).toContain('forecastEvidence?.research_confidence.score')
    expect(view).toContain('forecastEvidence?.provenance ?? {}')
    expect(view).toContain('source: forecastEvidence?.source ?? null')
    expect(view).toContain('asof_utc: forecastEvidence?.asof_utc ?? null')
    expect(view).toContain('direction: forecastEvidence?.direction ?? null')
    expect(view).toContain('point_pct: forecastEvidence?.forecast.point_pct ?? null')
    expect(view).toContain('confidence_kind: forecastEvidence?.research_confidence.kind ?? null')
    expect(view).toContain('confidence_label: forecastEvidence?.research_confidence.label ?? null')
    expect(view).toContain(
      'selective_actionable: forecastEvidence?.research_confidence.selective_actionable ?? false',
    )
  })

  it('renders forecast provenance, horizon, unavailable state, and research-only safety copy', () => {
    expect(view).toContain('<section class="forecast-card" aria-labelledby="forecast-heading">')
    expect(view).toContain('MODEL FORECAST')
    expect(view).toContain('formatForecastHorizon(forecastEvidence.horizon)')
    expect(view).toContain('PROVENANCE')
    expect(view).toContain('AS OF')
    expect(view).toContain('Forecast unavailable')
    expect(view).toContain('VPA fallback active')
    expect(view).toContain('it is not a Kronos model forecast')
    expect(view).toContain('SCENARIO SUPPORT')
    expect(view).toContain('NOT WIN PROBABILITY')
    expect(view).toContain('forecastEvidence?.conflict_with_action')
    expect(view).toContain('SELECTED FOR RESEARCH')
    expect(view).toContain('MODEL ABSTAINED')
    expect(view).not.toContain("? 'ACTIONABLE' : 'NOT ACTIONABLE'")
    expect(view).toContain('This is ordinal research evidence, not win probability')
    expect(view).not.toContain('forecast-probability')
  })

  it('calls the server-side TypeSafe endpoint and never exposes a credential', () => {
    expect(api).toContain("'/api/typesafe/live-decision'")
    expect(view).toContain('api.typeSafeLiveDecision(state)')
    expect(view).not.toContain('TYPESAFE_API_KEY=')
  })

  it('renders a directional read while labeling confidence honestly', () => {
    expect(view).toContain('BUY')
    expect(view).toContain('SELL')
    expect(view).toContain('STANDBY')
    expect(view).toContain('model certainty · not win probability')
    expect(view).toContain("['buy', 'sell']")
    expect(view).not.toContain('BUY BIAS')
    expect(view).not.toContain('SELL BIAS')
    expect(view).not.toContain("['buy', 'wait', 'sell']")
    expect(view).not.toContain("?? 'wait'")
    expect(api).toContain("LiveDecisionAction = 'buy' | 'sell'")
    expect(api).not.toContain("'buy' | 'sell' | 'wait'")
  })

  it('keeps directional reads separate from the app-owned execution posture', () => {
    expect(view).toContain('decision.risk_assessment?.keep_out')
    expect(view).toContain('EXECUTION POSTURE · STAND DOWN')
    expect(view).toContain('DECISION SUPPORT · NO ORDER AUTHORIZED')
    expect(view).toContain('aria-label="Execution posture"')
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

  it('renders the Decision Brain panel with explicit hysteresis and session locking', () => {
    expect(view).toContain('DECISION BRAIN')
    expect(view).toContain('CONFLUENCE')
    expect(view).toContain('HYSTERESIS ACTIVE')
    expect(view).toContain('SESSION LOCKED')
    expect(view).toContain('previous_decision: previousDecision.value')
    expect(view).toContain('clampedConsensus')
    expect(view).toContain('meterFillStyle')
    expect(view).toContain('meterPointerLeft')
    expect(view).toContain('model-cards-grid')
    expect(view).toContain('model-vote-card')
  })

  it('is discoverable in SearchPalette and promoted to the primary rail', () => {
    const palette = source('components/SearchPalette.vue')
    expect(palette).toContain("name: 'decision'")
    expect(palette).toContain("title: 'Decision'")
    expect(app).toContain("name: 'decision'")
    expect(app).toContain('decisionDestination,')
    const macro = app.match(/const macroTools = \[([\s\S]*?)\] as const/)?.[1] ?? ''
    expect(macro).not.toContain("name: 'decision'")
  })

  it('integrates the sealed last-week backtest as a dense Decision mode', () => {
    const panel = source('components/DecisionBacktestPanel.vue')
    expect(view).toContain('OOS BACKTEST')
    expect(view).toContain('<DecisionBacktestPanel v-if="viewMode === \'backtest\'" />')
    expect(api).toContain('/api/decision-tree/backtest')
    expect(panel).toContain('SEALED OOS · NEXT SESSION · DAILY CART')
    expect(panel).toContain('HOLDOUT COMPARISON')
    expect(panel).toContain('FOCUS TAPE · SPCX')
    expect(panel).toContain('LIVE CAPITAL · BLOCKED')
    expect(panel).toContain('data-density="compact"')
  })
})
