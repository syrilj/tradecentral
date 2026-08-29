import { describe, expect, it } from 'vitest'
import type { OptionsBoardRow, SqueezeSetup } from '@/api'
import { calculateFeaturedSetup } from '@/squeezeCalc'
import {
  computePressureScore,
  type ConvictionSortKey,
  type ConvictionSortDir,
} from '@/components/OptionsConvictionBoard.vue'

// ============================================================================
// Fixture Generators
// ============================================================================

function mockSetup(
  side: 'bullish' | 'bearish',
  score: number,
  overrides: Partial<SqueezeSetup> = {},
): SqueezeSetup {
  return {
    side,
    score,
    score_01: score / 100,
    likelihood:
      score >= 75 ? 'imminent' : score >= 55 ? 'likely' : score >= 35 ? 'possible' : 'unlikely',
    factors: [
      {
        id: 'proximity',
        label: 'Wall Proximity',
        score: Math.round(score * 0.4),
        max: 40,
        detail: 'Proximity metric',
      },
      {
        id: 'concentration',
        label: 'Gamma Concentration',
        score: Math.round(score * 0.3),
        max: 30,
        detail: 'Concentration metric',
      },
      {
        id: 'flow',
        label: 'Flow Momentum',
        score: Math.round(score * 0.3),
        max: 30,
        detail: 'Flow metric',
      },
    ],
    setup_analysis: [`${side === 'bullish' ? 'Upside' : 'Downside'} structure test`],
    for_stronger: ['Requires sustained delta flow'],
    trading_implication: `${side === 'bullish' ? 'Call' : 'Put'} wall magnet effect`,
    spot: 100,
    wall: side === 'bullish' ? 115 : 98,
    wall_pct: side === 'bullish' ? 0.15 : -0.02,
    ...overrides,
  }
}

function mockRow(
  rank: number,
  symbol: string,
  overrides: Partial<OptionsBoardRow> = {},
): OptionsBoardRow {
  return {
    symbol,
    rank,
    selection_basis: 'live_options_flow',
    selection_basis_note: 'Unusual signed order flow print',
    selection_score: 0.85,
    score_kind: 'ordinal_score',
    context_side: 'bullish',
    sources: ['tape', 'chain'],
    decision_authorized: false,
    available: true,
    spot: 100,
    squeeze_score: null,
    squeeze_label: null,
    squeeze_primary: 'quiet',
    structure_score: null,
    long_gamma_dampened: false,
    net_gex_m: null,
    gex_regime: 'pos_gamma',
    call_wall: 115,
    put_wall: 98,
    gamma_flip: 95,
    pin_strike: 100,
    call_premium: 250_000,
    put_premium: 50_000,
    activity_imbalance: null,
    expected_move: 5.5,
    atm_iv: 0.35,
    warnings: [],
    ...overrides,
  }
}

/**
 * Replicates the sorting algorithm from OptionsConvictionBoard.vue line 179-192
 */
function sortBoardRows(
  list: OptionsBoardRow[],
  sortKey: ConvictionSortKey,
  sortDir: ConvictionSortDir,
): OptionsBoardRow[] {
  return [...list].sort((a, b) => {
    const k = sortKey
    const dir = sortDir === 'asc' ? 1 : -1
    const va = a[k]
    const vb = b[k]
    if (va === vb) return a.rank - b.rank
    if (va === null || va === undefined) return 1
    if (vb === null || vb === undefined) return -1
    if (typeof va === 'string' && typeof vb === 'string') {
      return dir * va.localeCompare(vb)
    }
    return dir * ((va as number) - (vb as number))
  })
}

describe('Milestone 2 Challenger 2: Empirical Challenge Suite', () => {
  // ==========================================================================
  // Challenge 1: computePressureScore Boundary & Tone Mapping Stress Test
  // ==========================================================================
  describe('Challenge 1: computePressureScore Tone Mapping & Extreme Inputs', () => {
    it('exhaustively validates squeeze score threshold boundaries [-0.5, +0.5]', () => {
      // Exactly at 0.5 -> tone should be 'neutral' (requires signed > 0.5 for 'pos')
      expect(computePressureScore(mockRow(1, 'A', { squeeze_score: 0.5 })).tone).toBe('neutral')
      // Just above 0.5 -> 'pos'
      expect(computePressureScore(mockRow(1, 'A', { squeeze_score: 0.50001 })).tone).toBe('pos')
      expect(computePressureScore(mockRow(1, 'A', { squeeze_score: 0.50001 })).label).toBe('+0.5')

      // Exactly at -0.5 -> tone should be 'neutral' (requires signed < -0.5 for 'neg')
      expect(computePressureScore(mockRow(1, 'A', { squeeze_score: -0.5 })).tone).toBe('neutral')
      // Just below -0.5 -> 'neg'
      expect(computePressureScore(mockRow(1, 'A', { squeeze_score: -0.50001 })).tone).toBe('neg')
      expect(computePressureScore(mockRow(1, 'A', { squeeze_score: -0.50001 })).label).toBe('-0.5')

      // Zero & negative zero
      expect(computePressureScore(mockRow(1, 'A', { squeeze_score: 0 })).tone).toBe('neutral')
      expect(computePressureScore(mockRow(1, 'A', { squeeze_score: -0 })).tone).toBe('neutral')
    })

    it('clamps squeeze scores strictly to [-100, 100]', () => {
      const posExtreme = computePressureScore(mockRow(1, 'A', { squeeze_score: 9999 }))
      expect(posExtreme.score).toBe(100)
      expect(posExtreme.signed).toBe(100)
      expect(posExtreme.tone).toBe('pos')
      expect(posExtreme.label).toBe('+100.0')

      const negExtreme = computePressureScore(mockRow(1, 'A', { squeeze_score: -9999 }))
      expect(negExtreme.score).toBe(100)
      expect(negExtreme.signed).toBe(-100)
      expect(negExtreme.tone).toBe('neg')
      expect(negExtreme.label).toBe('-100.0')
    })

    it('validates premium dampener dynamics for live_options_flow', () => {
      // Test table of premium totals and expected dampening
      const testCases = [
        { call: 50_000, put: 50_000, expectedDampener: 1.0 }, // 100k -> 1.0
        { call: 200_000, put: 300_000, expectedDampener: 1.0 }, // 500k -> clamped to 1.0
        { call: 50_000, put: 0, expectedDampener: 0.5 }, // 50k -> 0.50
        { call: 10_000, put: 0, expectedDampener: 0.15 }, // 10k -> floor 0.15
        { call: 0, put: 0, expectedDampener: 1.0 }, // 0 total prem -> fallback to rawSigned (dampener 1.0)
      ]

      for (const tc of testCases) {
        const row = mockRow(1, 'TEST', {
          selection_basis: 'live_options_flow',
          squeeze_score: 40.0,
          call_premium: tc.call,
          put_premium: tc.put,
        })
        const res = computePressureScore(row)
        const expectedSigned = 40.0 * tc.expectedDampener
        expect(res.signed).toBeCloseTo(expectedSigned, 4)
      }
    })

    it('ignores premium dampener when selection_basis is NOT live_options_flow', () => {
      // When basis is pead_ordinal, small premium should NOT dampen squeeze score
      const row = mockRow(1, 'TEST', {
        selection_basis: 'pead_ordinal',
        squeeze_score: 40.0,
        call_premium: 5_000,
        put_premium: 0,
      })
      const res = computePressureScore(row)
      expect(res.signed).toBe(40.0)
      expect(res.score).toBe(40.0)
      expect(res.tone).toBe('pos')
    })

    it('empirically verifies invariant: Net GEX alone NEVER produces pos or neg tone', () => {
      const gexValues = [-1000, -100, -50.5, -1, -0.001, 0, 0.001, 1, 50.5, 100, 1000]

      for (const gex of gexValues) {
        const row = mockRow(1, 'GEX_TEST', {
          squeeze_score: null,
          activity_imbalance: null,
          net_gex_m: gex,
        })
        const res = computePressureScore(row)
        expect(res.tone).toBe('neutral')
        expect(res.signed).toBe(gex)
        expect(res.score).toBe(Math.min(100, Math.abs(gex) * 10))
        if (gex > 0) {
          expect(res.label).toBe(`+${gex.toFixed(1)}M`)
        } else {
          expect(res.label).toBe(`${gex.toFixed(1)}M`)
        }
      }
    })

    it('empirically verifies invariant: unsigned activity_imbalance NEVER synthesizes pos or neg tone', () => {
      const imbalances = [-1.0, -0.8, -0.5, 0, 0.5, 0.8, 1.0]

      for (const imb of imbalances) {
        const row = mockRow(1, 'ACT_TEST', {
          squeeze_score: null,
          activity_imbalance: imb,
          net_gex_m: null,
          selection_score: null,
        })
        const res = computePressureScore(row)
        expect(res.tone).toBe('neutral')
        expect(res.score).toBe(0)
        expect(res.signed).toBe(0)
        expect(res.label).toBe('0.0')
      }
    })

    it('robustly handles non-finite numbers (NaN, Infinity, -Infinity) gracefully', () => {
      const nanSqueeze = mockRow(1, 'A', {
        squeeze_score: NaN,
        net_gex_m: null,
        selection_score: null,
      })
      expect(computePressureScore(nanSqueeze)).toEqual({
        score: 0,
        signed: 0,
        tone: 'neutral',
        label: '0.0',
      })

      const infSqueeze = mockRow(1, 'A', {
        squeeze_score: Infinity,
        net_gex_m: null,
        selection_score: null,
      })
      expect(computePressureScore(infSqueeze)).toEqual({
        score: 0,
        signed: 0,
        tone: 'neutral',
        label: '0.0',
      })

      const nanGex = mockRow(1, 'A', { squeeze_score: null, net_gex_m: NaN, selection_score: null })
      expect(computePressureScore(nanGex)).toEqual({
        score: 0,
        signed: 0,
        tone: 'neutral',
        label: '0.0',
      })

      const nanScore = mockRow(1, 'A', {
        squeeze_score: null,
        net_gex_m: null,
        selection_score: NaN,
      })
      expect(computePressureScore(nanScore)).toEqual({
        score: 0,
        signed: 0,
        tone: 'neutral',
        label: '0.0',
      })
    })
  })

  // ==========================================================================
  // Challenge 2: Conviction Board Sorting Stability Under Missing/Partial Data
  // ==========================================================================
  describe('Challenge 2: Conviction Board Sorting Stability & Determinism', () => {
    const testKeys: ConvictionSortKey[] = [
      'rank',
      'symbol',
      'selection_basis',
      'selection_score',
      'spot',
      'squeeze_score',
      'net_gex_m',
      'put_wall',
      'call_wall',
      'expected_move',
      'atm_iv',
    ]

    it('verifies deterministic rank tie-breaking for equal values across all sort keys', () => {
      const rows: OptionsBoardRow[] = [
        mockRow(3, 'TSLA', { selection_score: 50, spot: 200, squeeze_score: 10, net_gex_m: 5 }),
        mockRow(1, 'AAPL', { selection_score: 50, spot: 200, squeeze_score: 10, net_gex_m: 5 }),
        mockRow(2, 'NVDA', { selection_score: 50, spot: 200, squeeze_score: 10, net_gex_m: 5 }),
      ]

      for (const key of testKeys) {
        if (key === 'rank' || key === 'symbol') continue
        const sortedAsc = sortBoardRows(rows, key, 'asc')
        const sortedDesc = sortBoardRows(rows, key, 'desc')

        // When values are equal (va === vb), tie-breaker is a.rank - b.rank
        expect(sortedAsc.map((r) => r.rank)).toEqual([1, 2, 3])
        expect(sortedDesc.map((r) => r.rank)).toEqual([1, 2, 3])
      }
    })

    it('sinks null and undefined entries to the bottom regardless of sort direction', () => {
      const rows: OptionsBoardRow[] = [
        mockRow(1, 'AAPL', { squeeze_score: null }),
        mockRow(2, 'NVDA', { squeeze_score: 50 }),
        mockRow(3, 'MSFT', { squeeze_score: undefined }),
        mockRow(4, 'AMZN', { squeeze_score: 20 }),
        mockRow(5, 'GOOG', { squeeze_score: -10 }),
      ]

      // Ascending sort on squeeze_score
      const sortedAsc = sortBoardRows(rows, 'squeeze_score', 'asc')
      // Measured values sorted ascending: -10, 20, 50. Null/undefined at the bottom.
      expect(sortedAsc.slice(0, 3).map((r) => r.symbol)).toEqual(['GOOG', 'AMZN', 'NVDA'])
      expect(sortedAsc.slice(3).map((r) => r.symbol)).toEqual(['AAPL', 'MSFT'])

      // Descending sort on squeeze_score
      const sortedDesc = sortBoardRows(rows, 'squeeze_score', 'desc')
      // Measured values sorted descending: 50, 20, -10. Null/undefined at the bottom.
      expect(sortedDesc.slice(0, 3).map((r) => r.symbol)).toEqual(['NVDA', 'AMZN', 'GOOG'])
      expect(sortedDesc.slice(3).map((r) => r.symbol)).toEqual(['AAPL', 'MSFT'])
    })

    it('verifies stable string sorting on symbol and selection_basis', () => {
      const rows: OptionsBoardRow[] = [
        mockRow(1, 'TSLA', { selection_basis: 'pead_ordinal' }),
        mockRow(2, 'AAPL', { selection_basis: 'live_options_flow' }),
        mockRow(3, 'MSFT', { selection_basis: 'directional_model' }),
      ]

      const bySymAsc = sortBoardRows(rows, 'symbol', 'asc')
      expect(bySymAsc.map((r) => r.symbol)).toEqual(['AAPL', 'MSFT', 'TSLA'])

      const bySymDesc = sortBoardRows(rows, 'symbol', 'desc')
      expect(bySymDesc.map((r) => r.symbol)).toEqual(['TSLA', 'MSFT', 'AAPL'])

      const byBasisAsc = sortBoardRows(rows, 'selection_basis', 'asc')
      expect(byBasisAsc.map((r) => r.selection_basis)).toEqual([
        'directional_model',
        'live_options_flow',
        'pead_ordinal',
      ])
    })

    it('fuzz tests sorting stability with 200 randomized rows containing mixed nulls and duplicates', () => {
      const randomRows: OptionsBoardRow[] = Array.from({ length: 200 }, (_, i) => {
        const randNull = (val: number) => (Math.random() < 0.3 ? null : val)
        return mockRow(i + 1, `SYM_${(i % 20).toString().padStart(2, '0')}`, {
          spot: randNull(100 + (i % 10) * 5),
          squeeze_score: randNull(-50 + (i % 7) * 15),
          net_gex_m: randNull(-100 + (i % 5) * 40),
          call_wall: randNull(110 + (i % 4) * 10),
          put_wall: randNull(90 - (i % 4) * 10),
          expected_move: randNull(2 + (i % 3)),
          atm_iv: randNull(0.2 + (i % 5) * 0.1),
        })
      })

      for (const key of testKeys) {
        for (const dir of ['asc', 'desc'] as const) {
          const pass1 = sortBoardRows(randomRows, key, dir)
          const pass2 = sortBoardRows(randomRows, key, dir)

          // 1. Invariant: Sort is completely deterministic
          expect(pass1.map((r) => r.rank)).toEqual(pass2.map((r) => r.rank))

          // 2. Invariant: Preserves length and all items
          expect(pass1.length).toBe(200)
          const rankSet = new Set(pass1.map((r) => r.rank))
          expect(rankSet.size).toBe(200)

          // 3. Invariant: Nulls/undefined are strictly partitioned at the end
          let foundNull = false
          for (const row of pass1) {
            const val = row[key]
            if (val === null || val === undefined) {
              foundNull = true
            } else if (foundNull) {
              // A non-null was found after a null -> sorting failed total partition!
              throw new Error(
                `Non-null found after null in key ${key} dir ${dir}: rank ${row.rank}`,
              )
            }
          }
        }
      }
    })
  })

  // ==========================================================================
  // Challenge 3: Squeeze Direction Alignment & Tie-Breaking Hierarchy
  // ==========================================================================
  describe('Challenge 3: calculateFeaturedSetup Precedence & Fallbacks', () => {
    it('strictly tests the 3-tier hierarchy: primary > signedScore > wall structure', () => {
      const bull = mockSetup('bullish', 20)
      const bear = mockSetup('bearish', 80)

      // Tier 1: Explicit primary overrides both signedScore and wall scores
      expect(calculateFeaturedSetup('bullish', bull, bear, -99).side).toBe('bullish')
      expect(calculateFeaturedSetup('bearish', bull, bear, +99).side).toBe('bearish')
      expect(calculateFeaturedSetup('BULL_TREND', bull, bear, -50).side).toBe('bullish')
      expect(calculateFeaturedSetup('BEAR_BREAK', bull, bear, +50).side).toBe('bearish')

      // Tier 2: Non-directional primary obeys signedScore regardless of wall scores
      expect(calculateFeaturedSetup('quiet', bull, bear, +0.01).side).toBe('bullish')
      expect(calculateFeaturedSetup('two_way', bull, bear, -0.01).side).toBe('bearish')
      expect(calculateFeaturedSetup('', bull, bear, +10).side).toBe('bullish')
      expect(calculateFeaturedSetup(undefined, bull, bear, -10).side).toBe('bearish')

      // Tier 3: Zero or unmeasured signedScore falls back to structure score (rs vs bs)
      expect(calculateFeaturedSetup('quiet', bull, bear, 0).side).toBe('bearish') // bear.score (80) > bull.score (20)
      expect(calculateFeaturedSetup('quiet', bull, bear, null).side).toBe('bearish')
      expect(calculateFeaturedSetup('quiet', bull, bear, undefined).side).toBe('bearish')
      expect(calculateFeaturedSetup('quiet', bull, bear, NaN).side).toBe('bearish')

      // Tier 3 tie-break: Equal structure scores default to bullish
      const equalBull = mockSetup('bullish', 50)
      const equalBear = mockSetup('bearish', 50)
      expect(calculateFeaturedSetup('quiet', equalBull, equalBear, 0).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', equalBull, equalBear, null).side).toBe('bullish')
    })
  })
})
