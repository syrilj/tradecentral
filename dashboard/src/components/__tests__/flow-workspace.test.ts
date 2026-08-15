import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Standalone Flow workspace contract', () => {
  const flow = source('views/FlowView.vue')
  const dashboard = source('components/FlowDashboard.vue')

  it('contains only the new market-wide Flow workspace', () => {
    expect(flow).toContain('MARKET-WIDE TAPE')
    expect(flow).toContain('MY BOOK')
    expect(flow).toContain('UNUSUAL / SWEEP ALERTS')
    expect(flow).toContain('ON-DEMAND HISTORY')
    expect(flow).toContain('UP TO 500 PRINTS')
    expect(flow).not.toContain('FlowStateView')
    expect(flow).not.toContain('OptionsConvictionBoard')
    expect(flow).not.toContain('Opportunities')
    expect(flow).not.toContain('Barrier Sleeve')
    expect(flow).not.toContain('route.query.tab')
  })

  it('polls one standalone market feed and forces only explicit refreshes', () => {
    expect(flow).toMatch(/api\.unusualFlow/)
    expect(flow).toMatch(/FLOW_POLL_MS = 15_000/)
    expect(flow).toMatch(/intervalMs: FLOW_POLL_MS/)
    expect(flow).toMatch(/forceNext\.value = true/)
    expect(flow).toMatch(/minPremium: BASE_FLOW_FLOOR/)
  })

  it('does not expose legacy routed-symbol or Deep-scan coverage', () => {
    expect(dashboard).toContain('MARKET-WIDE FLOW')
    expect(dashboard).toContain('LATEST PROVIDER SAMPLE')
    expect(dashboard).not.toContain('Partial provider coverage')
    expect(dashboard).not.toContain('routed symbols returned valid provider responses')
    expect(dashboard).not.toContain('DEEP SCAN SNAPSHOT')
  })

  it('projects thresholds locally and bounds the contract tape', () => {
    expect(dashboard).toMatch(/Number\(row\.premium\) >= props\.minPremium/)
    expect(dashboard).toMatch(/const MAX_TAPE_ROWS = 100/)
    expect(dashboard).toMatch(/qualifiedTapeRows\.value\.slice\(0, MAX_TAPE_ROWS\)/)
  })

  it('states the premium-share formula and labels bullish/bearish activity lean', () => {
    expect(dashboard).toMatch(/putPremium \/ classifiedPremium/)
    expect(dashboard).toContain('Activity lean (bullish/bearish)')
    expect(dashboard).toContain('BULLISH ACTIVITY')
    expect(dashboard).toContain('signed trade direction requires provider buy/sell')
    expect(dashboard).not.toContain('Dark pool flow')
    expect(dashboard).not.toContain('NO ATS SOURCE')
  })

  it('separates provider-observation freshness from scan age', () => {
    expect(dashboard).toMatch(/return age\(props\.payload\?\.asof\)/)
    expect(dashboard).toMatch(/return age\(props\.payload\?\.generated_at\)/)
    expect(dashboard).toContain('Provider age')
  })

  it('blocks legacy payloads and collapses empty data into one recovery state', () => {
    expect(dashboard).toMatch(/source_snapshot !== 'market_flow'/)
    expect(dashboard).toContain('Legacy Flow response blocked')
    expect(dashboard).toContain('No measured prints in the latest provider sample')
    expect(dashboard).toMatch(/v-else-if="!hasMeasuredFlow"/)
  })

  it('makes an honest operator brief and measured review queue primary while keeping raw prints optional', () => {
    expect(dashboard).toContain('What deserves review')
    expect(dashboard).toContain('Stale provider sample')
    expect(dashboard).toContain('Context only — refresh before using this tape intraday')
    expect(dashboard).toContain('triagePicks')
    expect(dashboard).toContain('VIEW LIVE SETUP →')
    expect(dashboard).toMatch(/compareFlowReviewRows/)
    expect(dashboard).toMatch(/buildFlowPulse/)
    expect(dashboard).toMatch(/tapeExpanded = ref\(false\)/)
    expect(dashboard).toContain('Raw contract prints')
    expect(dashboard).not.toContain('Smart market insight / ticker')
  })

  it('surfaces actionable desk next steps from lean, concentration, and freshness', () => {
    expect(dashboard).toContain('Actionable desk brief')
    expect(dashboard).toMatch(/function actionInsight/)
    expect(dashboard).toContain('Desk next step')
    expect(dashboard).toContain('Build setup · map near-dated call strikes + upside walls')
    expect(dashboard).toContain('Build setup · map near-dated put strikes + downside walls')
    expect(dashboard).toContain('Refresh feed before chain work — provider sample is stale')
    expect(dashboard).toContain('Focus:')
    expect(dashboard).toContain('Actionable insights')
    expect(dashboard).toContain('research triage — not order authorization')
  })

  it('surfaces InsiderFinance options presets and Top Tickers without dark-pool copy', () => {
    expect(dashboard).toContain('Unusual')
    expect(dashboard).toContain('Sweeps')
    expect(dashboard).toContain('Momentum')
    expect(dashboard).toContain('Moonshot')
    expect(dashboard).toContain('My book')
    expect(dashboard).toContain('Watchlist hits on this tape')
    expect(dashboard).toContain('Book alerts')
    expect(dashboard).toContain('Watching')
    expect(dashboard).toContain('On-demand historical tape')
    expect(dashboard).toContain('On-demand history')
    expect(dashboard).toContain('LOAD HISTORY')
    expect(dashboard).toContain('api.flowTape')
    expect(dashboard).toContain('Top Tickers')
    expect(dashboard).toContain('Unusual OTM')
    expect(dashboard).toContain('Unusual Volume')
    expect(dashboard).toContain('Unusual Premium')
    expect(dashboard).toContain('Call Premium')
    expect(dashboard).toContain('Put Premium')
    expect(dashboard).toContain("tapePreset = ref<TapePreset>('all')")
    expect(dashboard).not.toContain('Dark pool')
    expect(dashboard).not.toContain('ATS')
    expect(dashboard).not.toContain('NO ATS SOURCE')
  })

  it('supports local symbol, activity, right, expiry, and ordering filters', () => {
    expect(dashboard).toMatch(/symbolQuery = ref/)
    expect(dashboard).toMatch(/activityFilter = ref/)
    expect(dashboard).toMatch(/rightFilter = ref/)
    expect(dashboard).toMatch(/dteFilter = ref/)
    expect(dashboard).toMatch(/sortKey = ref/)
    expect(dashboard).toContain('Contract mix')
    expect(dashboard).toContain("activityFilter = 'incoming'")
    expect(dashboard).toContain('New premium')
    expect(dashboard).toContain('Average expiry')
    expect(dashboard).toContain('RESET FILTERS')
    expect(dashboard.indexOf('Flow review filters')).toBeLessThan(dashboard.indexOf('Where the major tape is concentrated'))
  })

  it('persists the prior provider window and collapses the default queue to its strongest rows', () => {
    expect(dashboard).toContain("edge.flow.previous-window.v1")
    expect(dashboard).toMatch(/sessionStorage\.setItem/)
    expect(dashboard).toMatch(/const DEFAULT_REVIEW_ROWS = 12/)
    expect(dashboard).toContain('LOWER-PRIORITY MATCHES COLLAPSED')
    expect(dashboard).toContain('SHOW ALL')
    expect(dashboard).toContain('pulseWindowCopy')
    expect(dashboard).toContain('FIRST_WINDOW_BASELINE')
    expect(dashboard).not.toContain('prior sample')
    expect(dashboard).toContain('flowLeanTokenClass')
    expect(dashboard).toContain('signedPrintTokenClass')
    expect(dashboard).toContain('applyFlowWindow')
    expect(dashboard).toContain('var(--long)')
    expect(dashboard).toContain('var(--short)')
    expect(dashboard).not.toContain('#52c78f')
    expect(dashboard).not.toContain('#f06d7b')
  })

  it('does not present an old provider observation as a live window', () => {
    expect(dashboard).toContain("return 'STALE SAMPLE'")
    expect(dashboard).toContain("providerFreshnessState === 'live'")
    expect(dashboard).toContain('UNSIGNED TAPE')
  })

  it('explains why rows surface and links each row to symbol research', () => {
    expect(dashboard).toMatch(/function evidenceFor/)
    expect(dashboard).toMatch(/function primaryReadout/)
    expect(dashboard).toContain('Top premium')
    expect(dashboard).toContain('Sweep-heavy')
    expect(dashboard).toContain('Flagged ${fractionPercent(flaggedShare(row), 0)}')
    expect(dashboard).toMatch(/@click="openSymbol\(row\.symbol\)"/)
  })

  it('opens a symbol-specific live setup from Flow before chain navigation', () => {
    const drawer = source('components/FlowSuggestionDrawer.vue')
    expect(flow).toContain('FlowSuggestionDrawer')
    expect(flow).toContain('@open-symbol="openSymbol"')
    expect(flow).toContain(':symbol="selectedSetup"')
    expect(flow).toContain("query: { ...route.query, setup: symbol }")
    expect(drawer).toContain('api.flowSuggestions({ symbol: props.symbol')
    expect(drawer).toContain('POLL_MS = 15_000')
    expect(drawer).toContain('SetupRiskPanel')
    expect(drawer).toContain('OPEN LIVE CHAIN →')
    expect(drawer).toContain('CLOSED · PLANNING')
    expect(drawer).toContain('Why live entry is not ready')
    expect(drawer).toContain('Specific contract plan')
    expect(drawer).toContain('Contract quote & risk map')
    expect(drawer).toContain('Take-profit reference')
    expect(drawer).toContain(':reference-debit="suggestion.contract_plan?.sizing_debit"')
    expect(drawer).toContain('QUOTE REQUIRED')
    expect(drawer).toContain('UNSIGNED {{ suggestion.bias_right.toUpperCase() }} BIAS · PAPER CANDIDATE · SIZING LOCKED')
  })

  it('puts major-index concentration and honest direction evidence ahead of the general queue', () => {
    expect(dashboard).toMatch(/MAJOR_SYMBOLS = \['SPY', 'QQQ', 'IWM', 'DIA'\]/)
    expect(dashboard).toContain('Where the major tape is concentrated')
    expect(dashboard).toContain('Strike')
    expect(dashboard).toContain('DTE zone')
    expect(dashboard).toContain('REVIEW #{{ reviewRank(major.symbol) }}')
    expect(dashboard).toContain('BULLISH ACTIVITY')
    expect(dashboard).toContain('BEARISH ACTIVITY')
    expect(dashboard).toContain('BULLISH SIGNED FLOW')
    expect(dashboard).toContain('BEARISH SIGNED FLOW')
    expect(dashboard).toContain('NEUTRAL ACTIVITY')
    expect(dashboard).not.toContain('Explicit model context')
  })

  it('uses tape spot when the daily return context is missing', () => {
    expect(dashboard).toMatch(/function priceRead/)
    expect(dashboard).toContain('Tape spot · no return series')
    expect(dashboard).toContain('No underlying price in this provider sample')
  })
})
