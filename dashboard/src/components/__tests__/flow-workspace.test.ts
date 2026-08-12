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
    expect(dashboard).toContain('MARKET-WIDE WINDOW')
    expect(dashboard).not.toContain('Partial provider coverage')
    expect(dashboard).not.toContain('routed symbols returned valid provider responses')
    expect(dashboard).not.toContain('DEEP SCAN SNAPSHOT')
  })

  it('projects thresholds locally and bounds the contract tape', () => {
    expect(dashboard).toMatch(/Number\(row\.premium\) >= props\.minPremium/)
    expect(dashboard).toMatch(/const MAX_TAPE_ROWS = 100/)
    expect(dashboard).toMatch(/qualifiedTapeRows\.value\.slice\(0, MAX_TAPE_ROWS\)/)
  })

  it('states the premium-share formula and never infers direction from call/put identity', () => {
    expect(dashboard).toMatch(/putPremium \/ classifiedPremium/)
    expect(dashboard).toContain('PUT / (CALL + PUT)')
    expect(dashboard).toContain('C/P is contract identity, not market direction.')
    expect(dashboard).toContain('no bullish or bearish intent is inferred from call/put alone')
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
    expect(dashboard).toContain('No measured prints in the current window')
    expect(dashboard).toMatch(/v-else-if="!hasMeasuredFlow"/)
  })

  it('makes an honest operator brief and measured review queue primary while keeping raw prints optional', () => {
    expect(dashboard).toContain('What deserves review')
    expect(dashboard).toContain('Archived provider window')
    expect(dashboard).toContain('Context only — refresh before using this tape intraday')
    expect(dashboard).toContain('triagePicks')
    expect(dashboard).toContain('OPEN CHAIN →')
    expect(dashboard).toMatch(/compareFlowReviewRows/)
    expect(dashboard).toMatch(/buildFlowPulse/)
    expect(dashboard).toMatch(/tapeExpanded = ref\(false\)/)
    expect(dashboard).toContain('Raw contract prints')
    expect(dashboard).not.toContain('Smart market insight / ticker')
  })

  it('supports local symbol, activity, right, expiry, and ordering filters', () => {
    expect(dashboard).toMatch(/symbolQuery = ref/)
    expect(dashboard).toMatch(/activityFilter = ref/)
    expect(dashboard).toMatch(/rightFilter = ref/)
    expect(dashboard).toMatch(/dteFilter = ref/)
    expect(dashboard).toMatch(/sortKey = ref/)
    expect(dashboard).toContain('Dominant right')
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
  })

  it('does not present an old provider observation as a live window', () => {
    expect(dashboard).toContain("return 'STALE WINDOW'")
    expect(dashboard).toContain("providerFreshnessState === 'live'")
    expect(dashboard).toContain('UNSIGNED TAPE')
  })

  it('explains why rows surface and links each row to symbol research', () => {
    expect(dashboard).toMatch(/function evidenceFor/)
    expect(dashboard).toMatch(/function primaryReadout/)
    expect(dashboard).toContain('Top premium')
    expect(dashboard).toContain('Sweep-heavy')
    expect(dashboard).toContain('High flagged share')
    expect(dashboard).toMatch(/@click="openSymbol\(row\.symbol\)"/)
  })

  it('puts major-index concentration and honest direction evidence ahead of the general queue', () => {
    expect(dashboard).toMatch(/MAJOR_SYMBOLS = \['SPY', 'QQQ', 'IWM', 'DIA'\]/)
    expect(dashboard).toContain('Where the major tape is concentrated')
    expect(dashboard).toContain('Strike')
    expect(dashboard).toContain('DTE zone')
    expect(dashboard).toContain('REVIEW #{{ reviewRank(major.symbol) }}')
    expect(dashboard).toContain('DIRECTION NOT READABLE')
    expect(dashboard).toContain('BULLISH SIGNED FLOW')
    expect(dashboard).toContain('BEARISH SIGNED FLOW')
    expect(dashboard).toContain('does not clear the evidence gate')
    expect(dashboard).not.toContain('Explicit model context')
  })

  it('uses tape spot when the daily return context is missing', () => {
    expect(dashboard).toMatch(/function priceRead/)
    expect(dashboard).toContain('Tape spot · return feed unavailable')
    expect(dashboard).toContain('No underlying price in this snapshot')
  })
})
