import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Volume Price Analysis (VPA) Workspace & Ingestion Engine', () => {
  const view = source('views/VpaView.vue')
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')
  const apiSrc = source('api.ts')
  const contractsSrc = source('vpaContracts.ts')

  it('registers /vpa route and navigation tab in workspace shell', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/vpa['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]vpa['"]/)
    expect(routerSrc).toContain('Volume Price Analysis')
    expect(appSrc).toContain("name: 'vpa'")
    expect(appSrc).toContain("title: 'VPA'")
  })

  it('exposes typed VPA API endpoints on the client', () => {
    expect(apiSrc).toContain('vpaAnalyze:')
    expect(apiSrc).toContain('vpaCodex:')
    expect(apiSrc).toContain('vpaSamples:')
    expect(apiSrc).toContain('vpaHealth:')
    expect(apiSrc).toContain('/api/vpa/analyze')
    expect(apiSrc).toContain('/api/vpa/codex')
    expect(apiSrc).toContain('/api/vpa/samples')
    expect(apiSrc).toContain('/api/vpa/health')
  })

  it('declares comprehensive VPA contracts with invalidation and risk management', () => {
    expect(contractsSrc).toContain('export interface VpaKeyCandle')
    expect(contractsSrc).toContain('export interface VpaForensicBreakdown')
    expect(contractsSrc).toContain('export interface VpaPrimaryScenario')
    expect(contractsSrc).toContain('export interface VpaAlternativeScenario')
    expect(contractsSrc).toContain('export interface VpaTradeExecutionGuide')
    expect(contractsSrc).toContain('invalidation_trigger: string')
    expect(contractsSrc).toContain('stop_loss_placement: string')
  })

  it('supports global clipboard paste and dropzone chart screenshot ingestion', () => {
    expect(view).toContain('handleGlobalPaste')
    expect(view).toContain('onDrop')
    expect(view).toContain('Paste Chart Screenshot (⌘V / Ctrl+V)')
    expect(view).toContain('Run VPA Forensic Scan')
  })

  it('renders Wyckoff campaigns, candle forensic evaluation, and effort vs result', () => {
    expect(view).toContain('Wyckoff Campaign Context')
    expect(view).toContain('Candle-by-Candle Forensic Evaluation')
    expect(view).toContain('Stopping / Topping Dynamics')
    expect(view).toContain('Low-Volume Tests (Supply / Demand)')
    expect(view).toContain("Support &amp; Resistance (The 'House' Model) &amp; VAP")
    expect(view).toContain('Effort vs. Result')
  })

  it('surfaces primary move forecasts and speculative alternative reads with invalidation triggers', () => {
    expect(view).toContain('Primary Read')
    expect(view).toContain('Speculative Alternative Reads &amp; Invalidation')
    expect(view).toContain('Exact Invalidation Trigger:')
    expect(view).toContain('Caution: Market Reading is Discretionary')
  })

  it('includes the volume-price rules drawer', () => {
    expect(view).toContain('Volume-price rules')
    expect(view).toContain('Three Universal Laws (Wyckoff)')
    expect(view).toContain('Core Operating Principles')
    expect(view).toContain('Premier Candlestick Taxonomies')
  })
})

/* -------------------------------------------------------------------------
   Rebuild contract (docs/VPA_REBUILD_CONTRACT.md) §4 + §7.
   These guard the defects the rebuild exists to fix — D1 (dead timeframe),
   D2/D3 (snapshot that does nothing), D4 (constant probabilities),
   D5/D6 (undrawable support/resistance), D8 (canned cases dressed as engine
   output). Each assertion fails against the pre-rebuild view.
   ---------------------------------------------------------------------- */

describe('VPA contracts: §4 response additions', () => {
  const contractsSrc = source('vpaContracts.ts')
  const apiSrc = source('api.ts')

  it('types every new §4 block', () => {
    for (const iface of [
      'VpaBarsMeta',
      'VpaLevel',
      'VpaVapBin',
      'VpaVolumeAtPrice',
      'VpaEvidenceItem',
      'VpaProbabilityBasis',
      'VpaVisionStatus',
      'VpaTimeframeOption',
      'VpaHealthPayload',
    ]) {
      expect(contractsSrc).toContain(`export interface ${iface}`)
    }
  })

  it('hangs the new blocks off the analysis result as optional fields', () => {
    for (const field of [
      'bars_meta?: VpaBarsMeta',
      'levels?: VpaLevel[]',
      'vap?: VpaVolumeAtPrice',
      'evidence?: VpaEvidenceItem[]',
      'probability_basis?: VpaProbabilityBasis',
      'vision_status?: VpaVisionStatus',
    ]) {
      expect(contractsSrc).toContain(field)
    }
  })

  it('keeps every pre-existing field so nothing breaks while the backend lands', () => {
    for (const field of [
      'market_phase: string',
      'dominant_sentiment: string',
      'confidence_score: number',
      'effort_vs_result_verdict:',
      'forensic_breakdown: VpaForensicBreakdown',
      'primary_scenario: VpaPrimaryScenario',
      'alternative_scenarios: VpaAlternativeScenario[]',
      'trade_execution_guide: VpaTradeExecutionGuide',
      'is_sample?: boolean',
      'sample_title?: string',
      'book_reference?: string',
    ]) {
      expect(contractsSrc).toContain(field)
    }
  })

  it('lets risk_reward_ratio be null rather than a fabricated string (§5)', () => {
    // The engine emits the bare reward multiple as a number; typing it string-only
    // made the view discard every computed ratio and print "not derivable" over it.
    expect(contractsSrc).toContain('risk_reward_ratio: number | string | null')
  })

  it('models bars_meta downgrade reporting and level role reversal', () => {
    expect(contractsSrc).toContain('timeframe_requested?: string')
    expect(contractsSrc).toContain('timeframe_served?: string')
    expect(contractsSrc).toContain('downgraded?: boolean')
    expect(contractsSrc).toContain('downgrade_reason?: string | null')
    expect(contractsSrc).toContain('role_reversed?: boolean')
  })

  it('exports the new types through the api barrel', () => {
    for (const t of [
      'VpaBarsMeta',
      'VpaLevel',
      'VpaVolumeAtPrice',
      'VpaEvidenceItem',
      'VpaProbabilityBasis',
      'VpaVisionStatus',
      'VpaTimeframeOption',
      'VpaHealthPayload',
    ]) {
      expect(apiSrc).toContain(`  ${t},`)
    }
  })
})

describe('VPA timeframe control is real and honest (defect D1)', () => {
  const view = source('views/VpaView.vue')

  it('builds the dropdown from /api/vpa/health, not a hardcoded array', () => {
    // Scoped to the symbol: availability is per ticker, not global.
    expect(view).toContain('api.vpaHealth(symbolInput.value)')
    expect(view).toContain('health.value?.timeframes')
    expect(view).toContain('v-for="tf in timeframeOptions"')
    // The old eight-entry literal must be gone.
    expect(view).not.toContain("{ value: '15m', label: '15 Minutes' }")
    expect(view).not.toContain("{ value: 'Daily', label: 'Daily (1D)' }")
  })

  it('renders unavailable timeframes disabled with their reason instead of substituting', () => {
    expect(view).toContain(':disabled="!tf.available"')
    expect(view).toContain('tf.reason')
    expect(view).toContain('unavailableTimeframes')
  })

  it('locks the selector when the capability report is unreachable', () => {
    expect(view).toContain(':disabled="!capabilityKnown"')
    expect(view).toContain('Timeframe capability report unavailable')
  })

  it('re-runs the analysis when timeframe or asset class changes', () => {
    expect(view).toMatch(/watch\(\s*\[timeframeInput,\s*assetClassInput\]/)
    expect(view).toContain('fetchEquityDataAndAnalyze(symbolInput.value)')
  })

  it('names requested vs served timeframe when the engine downgrades', () => {
    expect(view).toContain('Timeframe downgraded')
    expect(view).toContain('barsMeta?.timeframe_requested')
    expect(view).toContain('barsMeta?.timeframe_served')
    expect(view).toContain('downgrade_reason')
  })

  it('surfaces bars_meta as the proof the control did something', () => {
    expect(view).toContain('Bars Served To The Engine')
    expect(view).toContain('barsMeta.bar_count')
    expect(view).toContain('barsMeta.first_bar')
    expect(view).toContain('barsMeta.last_bar')
    expect(view).toContain('barsMeta.source')
  })
})

describe('VPA snapshot-to-vision never appears to work and do nothing (D2/D3)', () => {
  const view = source('views/VpaView.vue')

  it('drives the button off vision_status / health capability', () => {
    expect(view).toContain('vision_status')
    expect(view).toContain('visionAvailable')
    expect(view).toContain('snapBlockedReason')
    expect(view).toContain(':disabled="snapDisabled"')
  })

  it('refuses to post when the capability is absent', () => {
    expect(view).toMatch(
      /async function snapCanvasToVision[\s\S]{0,160}if \(snapDisabled\.value\) return/,
    )
  })

  it('states the blocking reason in plain text next to the control', () => {
    expect(view).toContain('Vision Not Configured')
    expect(view).toContain('class="snap-reason"')
  })

  it('frames vision as optional rather than as a broken feature', () => {
    // Vision only extends reach to charts we hold no bars for; for a local
    // symbol the exact-OHLCV read is strictly more precise. That framing is
    // the API's own receipt, rendered once via snapBlockedReason — not a
    // second, duplicated static paragraph.
    expect(view).toContain('class="snap-reason"')
    expect(view).toContain('{{ snapBlockedReason }}')
    expect(view).not.toContain('class="snap-note"')
    expect(view).not.toContain('Screenshots will not be read.')
  })

  it('reports an image that was received but not used', () => {
    expect(view).toContain('image_received')
    expect(view).toContain('image_used')
    expect(view).toContain('Snapshot discarded')
  })
})

describe('VPA support & resistance is numeric and drawn (D5/D6)', () => {
  const view = source('views/VpaView.vue')

  it('consumes levels[] and vap rather than only prose strings', () => {
    expect(view).toContain('analysisResult.value?.levels')
    expect(view).toContain('analysisResult.value?.vap')
    expect(view).toContain('orderedLevels')
  })

  it('paints support/resistance bands, POC, value area and role-reversal markers', () => {
    expect(view).toContain('Support / resistance bands')
    expect(view).toContain('Value area shading')
    expect(view).toContain('Point of control')
    expect(view).toContain('l.role_reversed')
    expect(view).toContain('Volume-at-price profile')
    expect(view).toContain('candlePath')
  })

  it('weights band opacity by strength and prints the touch count', () => {
    expect(view).toContain('strength * 0.1')
    expect(view).toContain('`×${l.touches}`')
  })

  it('keeps a readable, interactive level list that highlights on the chart', () => {
    expect(view).toContain('levels-table')
    expect(view).toContain('@mouseenter="hoveredLevelKey = levelKey(l, idx)"')
    expect(view).toContain('watch(hoveredLevelKey')
    expect(view).toContain('levelBands')
  })

  it('says so plainly when the engine reports no levels', () => {
    expect(view).toContain('No numeric levels in this response')
  })
})

describe('VPA probabilities carry their evidence (defect D4)', () => {
  const view = source('views/VpaView.vue')

  it('renders the evidence ledger with weights, bars and book citations', () => {
    expect(view).toContain('Evidence Ledger')
    expect(view).toContain('ev.signal')
    expect(view).toContain('ev.direction')
    expect(view).toContain('ev.weight')
    expect(view).toContain('ev.bars')
    expect(view).toContain('ev.book_ref')
    expect(view).toContain('ev.detail')
  })

  it('shows probability_basis beside the percentage, caveat included', () => {
    expect(view).toContain('probabilityBasis.bull_score')
    expect(view).toContain('probabilityBasis.bear_score')
    expect(view).toContain('probabilityBasis.band')
    expect(view).toContain('not a calibrated forecast')
  })

  it('flags a percentage that arrives with no basis', () => {
    expect(view).toContain('class="basis-missing"')
    expect(view).toContain('Read it as an unsupported claim')
  })

  it('renders an em dash rather than a placeholder for missing figures', () => {
    expect(view).toContain("const DASH = '—'")
    expect(view).toContain('riskReward === DASH')
    // The old view invented a confidence of 0.8 when the field was absent.
    expect(view).not.toContain('confidence_score || 0.8')
    expect(view).toContain('confidencePct === null ? DASH')
  })

  it('never hardcodes the pre-rebuild constants in the view', () => {
    expect(view).not.toContain('1 : 3.1')
    expect(view).not.toMatch(/probability_pct:\s*74/)
    expect(view).not.toMatch(/confidence_score:\s*0\.86/)
  })
})

describe('VPA does not ship third-party published chart commentaries (defect D8)', () => {
  const view = source('views/VpaView.vue')

  it('states that third-party published reads are not included', () => {
    expect(view).toContain('Reference library')
    expect(view).toContain('reference-item')
    expect(view).toContain('Third-party published chart commentaries are not included')
    expect(view).not.toContain('Coulling')
  })

  it('shows the book citation prominently on each case', () => {
    expect(view).toContain('sample.book_reference')
    expect(view).toContain('ri-cite')
    expect(view).toContain('prov-cite')
  })

  it('marks the whole result panel when a reference case is loaded', () => {
    expect(view).toContain('isReferenceCase')
    expect(view).toContain("'is-reference': isReferenceCase")
  })

  it('does not let a canned case hijack the live timeframe controls', () => {
    expect(view).not.toContain('if (res.timeframe) timeframeInput.value = res.timeframe')
  })
})

describe('VPA typography follows the desk token ladder', () => {
  const view = source('views/VpaView.vue')

  it('uses the shared type scale rather than ad-hoc rem values', () => {
    for (const t of ['--t-micro', '--t-tiny', '--t-small', '--t-body', '--t-fig', '--t-display']) {
      expect(view).toContain(`var(${t})`)
    }
  })

  it('sets tabular figures for numeric columns', () => {
    expect(view).toContain("font-feature-settings: 'tnum', 'zero'")
    expect(view).toContain('font-variant-numeric: tabular-nums')
    expect(view).toContain('.vpa-table td.num')
  })

  it('drops the utility-class soup the view used for headings', () => {
    expect(view).not.toContain('class="font-bold text-ink"')
    expect(view).not.toContain('text-[10px]')
    expect(view).not.toContain('text-[11px]')
  })

  it('constrains prose measure so long rationales stay readable', () => {
    expect(view).toMatch(/max-width:\s*\d+ch/)
  })
})

describe('VPA renders every signal the engine computes, not a subset', () => {
  const view = source('views/VpaView.vue')
  const contractsSrc = source('vpaContracts.ts')
  const apiSrc = source('api.ts')

  it('types the four signal blocks the view used to drop on the floor', () => {
    for (const iface of [
      'VpaDynamicTrend',
      'VpaCongestionPattern',
      'VpaConfidenceBasis',
      'VpaThresholdsStatus',
    ]) {
      expect(contractsSrc).toContain(`export interface ${iface}`)
      expect(apiSrc).toContain(iface)
    }
    for (const field of [
      'dynamic_trend?: VpaDynamicTrend | null',
      'congestion_patterns?: VpaCongestionPattern[]',
      'confidence_basis?: VpaConfidenceBasis',
      'thresholds_status?: VpaThresholdsStatus',
    ]) {
      expect(contractsSrc).toContain(field)
    }
  })

  it('renders the Ch.8 dynamic trend line with its slope, pivots and citation', () => {
    expect(view).toContain('Dynamic trend line')
    expect(view).toContain('dynamicTrend')
    expect(view).toContain('slope_atr_per_bar')
    expect(view).toContain('slope_per_bar')
    expect(view).toContain('pivot_bars')
    // `direction: 'none'` is a real read (two-sided pivots), not an empty state.
    expect(view).toContain("dynamicTrend!.direction === 'none'")
  })

  it('renders Ch.11 congestion patterns as a list with level and book reference', () => {
    expect(view).toContain('Congestion patterns')
    expect(view).toContain('congestionPatterns')
    expect(view).toContain('congestion-row')
    expect(view).toMatch(/No pennant, flag or triangle/)
  })

  it('decomposes the confidence headline instead of asserting it', () => {
    expect(view).toContain('confidenceBasis')
    expect(view).toContain('confidenceComponents')
    for (const key of [
      'coverage',
      'agreement',
      'recency',
      'evidence_density',
      'downgrade_penalty',
      'method_ceiling',
    ]) {
      expect(view).toContain(key)
    }
    expect(view).toContain('confidence_basis')
    // No basis is an honesty condition, not a blank panel.
    expect(view).toMatch(/unaudited/)
  })

  it('states whether the thresholds are book-derived or provisional defaults', () => {
    expect(view).toContain('thresholdsStatus')
    expect(view).toContain('provisional')
    expect(view).toContain('Book-derived')
  })

  it('surfaces the VAP precision fields rather than rounding them away', () => {
    for (const field of ['poc_low', 'poc_high', 'value_area_pct', 'bin_size', 'total_volume']) {
      expect(view).toContain(field)
    }
    expect(view).toContain('atr')
  })

  it('says why the risk:reward is missing instead of only that it is', () => {
    expect(view).toContain('risk_reward_unavailable_reason')
    expect(contractsSrc).toContain('risk_reward_unavailable_reason?: string | null')
  })

  it('names the finer timeframe a resampled bar set came from', () => {
    expect(view).toContain('barsMeta.resampled_from')
    expect(contractsSrc).toContain('resampled_from?: string | null')
  })
})

describe('VPA risk:reward survives the wire format (regression)', () => {
  const view = source('views/VpaView.vue')
  const contractsSrc = source('vpaContracts.ts')

  it('formats a numeric reward multiple instead of dropping it', () => {
    // Regression: `typeof rr === 'string'` alone rejected the engine's 2.12 and
    // rendered an em dash captioned "not derivable" — over a derived figure.
    expect(view).toContain("typeof rr === 'number'")
    expect(view).toMatch(/1 : \$\{rr\.toFixed\(2\)\}/)
    expect(view).toContain("typeof rr === 'string'")
  })

  it('shows the entry, stop and target the ratio was computed from', () => {
    for (const field of ['entry_price', 'stop_price', 'target_price']) {
      expect(view).toContain(field)
      expect(contractsSrc).toContain(`${field}?: number | null`)
    }
    expect(view).toContain('hasTradeLevels')
    expect(view).toContain('tradeRiskPerUnit')
    expect(view).toContain('tradeRewardPerUnit')
  })

  it('draws a rank-based price staff instead of overlapping labels on a linear rail', () => {
    expect(view).toContain('buildRiskLadder')
    expect(view).toContain('class="risk-ladder"')
    expect(view).toContain('rl-rung')
    expect(view).not.toContain('risk-mark')
    expect(view).not.toContain('riskScale')
    expect(view).not.toContain('stopPct')
  })
})

describe('VPA level provenance is informative, not a constant', () => {
  const view = source('views/VpaView.vue')
  const contractsSrc = source('vpaContracts.ts')

  it('shows what a zone has actually been rather than "pivot_cluster" on every row', () => {
    // The Origin column rendered l.source, which is the same literal for every
    // level. origins[] carries the Ch.7 house story: a band that has been both.
    expect(view).toContain('levelOriginLabel')
    expect(view).toContain("origins.length > 1) return 'floor & ceiling'")
    expect(contractsSrc).toContain('origins?: VpaLevelKind[]')
  })

  it('ages each level so a stale band reads as stale', () => {
    expect(view).toContain('levelBarsSinceTouch')
    expect(view).toContain('last_touch_bar')
    expect(view).toContain('bars ago')
  })

  it('keeps the pivot lists and the derivation the engine reports', () => {
    expect(view).toContain('support_resistance.pivot_highs')
    expect(view).toContain('support_resistance.pivot_lows')
    expect(view).toContain('srMethod')
    expect(contractsSrc).toContain('method?: string')
  })
})

describe('VPA scan button proves it ran (deterministic engine)', () => {
  const view = source('views/VpaView.vue')

  it('stamps a receipt because an identical re-scan changes nothing on screen', () => {
    // The engine returns a byte-identical read in ~30ms for the same inputs, so
    // the spinner never paints and no figure moves — without a receipt the
    // button is indistinguishable from a broken one.
    expect(view).toContain('lastScanAt')
    expect(view).toContain('lastScanChanged')
    expect(view).toContain('scan-receipt')
    expect(view).toContain('read unchanged')
    expect(view).toContain('read updated')
  })

  it('routes every analyse path through applyResult so the receipt cannot go stale', () => {
    expect(view).toContain('function applyResult')
    // Stamping only the button's own path left the receipt claiming "unchanged"
    // after a timeframe switch had in fact changed the read.
    const direct = view.match(/analysisResult\.value = res/g) ?? []
    expect(direct.length).toBe(2) // one inside applyResult, one in loadSample
    expect(view).toContain('applyResult(res)')
  })

  it('does not stamp a live-scan receipt over a canned textbook case', () => {
    expect(view).toMatch(/lastScanAt\.value = null/)
  })
})
