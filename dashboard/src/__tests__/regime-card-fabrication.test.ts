import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

function readSource(relativeFilePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, '..', relativeFilePath), 'utf-8')
}

/**
 * The Layer-3 regime card renders eleven figures. Ten of them used to be
 * literals typed into `reconciledMarketRegime` in RegimeView.vue, so the card
 * read the same on a symbol with a full chain and on one whose
 * /api/market-regime call had not returned: 72.0% calibrated confidence,
 * a 68/20/12 simplex, 15% hazard, 85% stability, 45-of-50-bar tenure, 85%
 * model consensus over four named agreeing models, 35th vol percentile,
 * H = 0.52, 100% persistence, and `quality.measurable: true` asserting all of
 * it was measured.
 *
 * Every figure on that card now comes from the regime engine or renders an em
 * dash. These assertions pin the literals out.
 */
describe('Layer 3 regime card carries no fabricated figures', () => {
  const src = readSource('views/RegimeView.vue')

  it('does not seed or floor the calibrated confidence score', () => {
    expect(src).not.toContain('raw?.confidence?.score ?? 0.78')
    expect(src).not.toContain('Math.max(raw?.confidence?.score ?? 0.76, 0.72)')
    expect(src).not.toContain('Math.max(raw?.confidence?.score ?? 0.72, 0.7)')
    expect(src).toContain('let confidenceScore: number | null = raw?.confidence?.score ?? null')
  })

  it('withholds confidence and the simplex when the label is locally reconciled', () => {
    expect(src).toContain('const labelIsLocallyReconciled = raw == null || primary !== raw.primary')
    expect(src).toMatch(/labelIsLocallyReconciled\)\s*\{\s*\n\s*confidenceScore = null/)
  })

  it('attaches no hand-written probability simplex to a synthesized label', () => {
    expect(src).not.toMatch(/probs = \{ bullish: [0-9.]+, neutral: [0-9.]+, bearish: [0-9.]+ \}/)
    expect(src).toContain(
      'let probs: SimplexProbabilities | null = raw?.probabilities ? { ...raw.probabilities } : null',
    )
  })

  it('does not invent or clamp CUSUM/BOCPD transition figures', () => {
    expect(src).not.toContain('Math.min(raw?.transition?.changepointProb5d ?? 0.15, 0.28)')
    expect(src).not.toContain('Math.min(raw?.transition?.changepointProb20d ?? 0.25, 0.38)')
    expect(src).not.toContain('Math.max(raw?.transition?.stabilityScore ?? 0.85, 0.78)')
    expect(src).not.toContain('raw?.transition?.mapRunLength ?? 45')
    expect(src).not.toContain('raw?.transition?.expectedRunLength ?? 50')
    expect(src).toContain('changepointProb5d: raw?.transition?.changepointProb5d ?? null')
    expect(src).toContain('stabilityScore: raw?.transition?.stabilityScore ?? null')
  })

  it('does not assert model consensus the pairwise matrix cannot support', () => {
    expect(src).not.toContain('Math.max(raw?.agreement?.agreementScore ?? 0.85, 0.82)')
    expect(src).not.toContain(
      "agreeingModels: ['Trend (Kalman)', 'Gamma Topography', 'Order Flow', 'Market Structure']",
    )
    expect(src).toContain('agreement: raw?.agreement ?? {')
  })

  it('does not hard-code pillar statistics', () => {
    expect(src).not.toContain('volPercentile: 0.35')
    expect(src).not.toContain('hurstExponent: 0.52')
    expect(src).not.toContain('trendPersistence: 1.0')
  })

  it('does not claim full data completeness unconditionally', () => {
    expect(src).not.toMatch(/measurable: true,\s*\n\s*dataCompleteness: 1\.0/)
    expect(src).toContain('raw?.quality?.measurable === true || (pt != null && spot != null)')
  })
})

describe('Regime contracts admit absent measurements', () => {
  const src = readSource('regimeContracts.ts')

  it('types confidence, transition and agreement scores as nullable', () => {
    expect(src).toContain('score: number | null')
    expect(src).toContain('changepointProb5d: number | null')
    expect(src).toContain('stabilityScore: number | null')
    expect(src).toContain('agreementScore: number | null')
  })
})

describe('PrimaryRegimeCard distinguishes uncalibrated from low confidence', () => {
  const src = readSource('components/PrimaryRegimeCard.vue')

  it('labels a missing score UNCALIBRATED rather than LOW', () => {
    expect(src).toContain("return 'UNCALIBRATED'")
    expect(src).toContain('{{ confidenceBandLabel }}')
    expect(src).not.toContain('{{ confidenceBand.toUpperCase() }}')
  })
})

describe('TransitionRiskGauge renders an em dash for absent changepoint stats', () => {
  const src = readSource('components/TransitionRiskGauge.vue')

  it('does not substitute 100% stability or a zero tenure for null', () => {
    expect(src).not.toContain('props.transition?.stabilityScore ?? 1.0')
    expect(src).not.toContain('props.transition?.mapRunLength ?? 0')
    expect(src).toContain('stabilityScore != null')
    expect(src).toContain('mapRunLength != null')
  })
})

describe('The tactical briefing declares itself provisional before the chain lands', () => {
  const src = readSource('views/RegimeView.vue')

  it('flags the price-only read so the later rewrite is expected', () => {
    expect(src).toContain('const provisional = regimeRead.value.side == null')
    expect(src).toContain('provisionalNote')
    expect(src).toContain('Price-only read — dealer gamma pending')
    expect(src).toContain('class="tactical-provisional font-mono"')
  })
})
