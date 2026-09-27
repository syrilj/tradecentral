import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { OptionsSqueeze, SqueezeSetup } from '@/api'
import {
  calculateFeaturedSetup,
  calculateRingOffset,
  formatNearSpotGex,
  calculateTrackWidthPct,
  buildTakeaways,
  buildTheoryIdentity,
  buildSqueezeExplanation,
  formatMillions,
  RING_CIRCUMFERENCE,
  RING_RADIUS,
} from '@/squeezeCalc'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function mockSetup(score: number, overrides: Partial<SqueezeSetup> = {}): SqueezeSetup {
  return {
    side: 'bullish',
    score,
    score_01: score / 100,
    likelihood:
      score >= 75 ? 'imminent' : score >= 55 ? 'likely' : score >= 35 ? 'possible' : 'unlikely',
    factors: [],
    setup_analysis: [],
    for_stronger: [],
    trading_implication: 'Structure test implication',
    spot: 500,
    wall: null,
    wall_pct: null,
    ...overrides,
  }
}

describe('Squeeze Screener Calculation Suite', () => {
  describe('1. Setup Selection & Tie-Breaking with signedScore', () => {
    it('honors explicit primary="bearish" regardless of setup score comparison', () => {
      const bull = mockSetup(80)
      const bear = mockSetup(40)
      const res = calculateFeaturedSetup('bearish', bull, bear, 40)
      expect(res.side).toBe('bearish')
      expect(res.setup).toBe(bear)
    })

    it('honors explicit primary="bullish" regardless of setup score comparison', () => {
      const bull = mockSetup(30)
      const bear = mockSetup(75)
      const res = calculateFeaturedSetup('bullish', bull, bear, -45)
      expect(res.side).toBe('bullish')
      expect(res.setup).toBe(bull)
    })

    it('selects higher score setup when primary is "quiet"', () => {
      const bullHigh = mockSetup(70)
      const bearLow = mockSetup(25)
      expect(calculateFeaturedSetup('quiet', bullHigh, bearLow, 0).side).toBe('bullish')

      const bullLow = mockSetup(20)
      const bearHigh = mockSetup(65)
      expect(calculateFeaturedSetup('quiet', bullLow, bearHigh, 0).side).toBe('bearish')
    })

    it('tie-breaks equal structure scores (bs === rs) using negative signedScore -> bearish', () => {
      const bull = mockSetup(45)
      const bear = mockSetup(45)
      // Negative signed score (-30) indicates put-skew / bearish bias
      const resQuiet = calculateFeaturedSetup('quiet', bull, bear, -30)
      expect(resQuiet.side).toBe('bearish')
      expect(resQuiet.setup).toBe(bear)

      const resTwoWay = calculateFeaturedSetup('two_way', bull, bear, -15)
      expect(resTwoWay.side).toBe('bearish')
      expect(resTwoWay.setup).toBe(bear)
    })

    it('tie-breaks equal structure scores (bs === rs) using positive signedScore -> bullish', () => {
      const bull = mockSetup(50)
      const bear = mockSetup(50)
      const resQuiet = calculateFeaturedSetup('quiet', bull, bear, 25)
      expect(resQuiet.side).toBe('bullish')
      expect(resQuiet.setup).toBe(bull)

      const resTwoWay = calculateFeaturedSetup('two_way', bull, bear, 10)
      expect(resTwoWay.side).toBe('bullish')
      expect(resTwoWay.setup).toBe(bull)
    })

    it('defaults to bullish when structure scores are equal and signedScore is 0 or null', () => {
      const bull = mockSetup(40)
      const bear = mockSetup(40)
      expect(calculateFeaturedSetup('quiet', bull, bear, 0).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bull, bear, null).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bull, bear, undefined).side).toBe('bullish')
    })

    it('handles undefined setups gracefully', () => {
      const resNullBull = calculateFeaturedSetup('quiet', undefined, mockSetup(30), -10)
      expect(resNullBull.side).toBe('bearish')

      const resNullBoth = calculateFeaturedSetup('quiet', undefined, undefined, -5)
      expect(resNullBoth.side).toBe('bearish')

      const resNullBothPos = calculateFeaturedSetup('quiet', undefined, undefined, 5)
      expect(resNullBothPos.side).toBe('bullish')
    })

    it('handles compound primary labels and case-insensitivity cleanly', () => {
      const bull = mockSetup(60)
      const bear = mockSetup(40)
      expect(calculateFeaturedSetup('bearish_squeeze', bull, bear).side).toBe('bearish')
      expect(calculateFeaturedSetup('BEARISH_LEAN', bull, bear).side).toBe('bearish')
      expect(calculateFeaturedSetup('bullish_squeeze', bull, bear).side).toBe('bullish')
      expect(calculateFeaturedSetup('BULLISH', bull, bear).side).toBe('bullish')
    })

    it('falls back to available setup when preferred side setup is missing', () => {
      const bull = mockSetup(65)
      const res = calculateFeaturedSetup('bearish', bull, undefined)
      expect(res.side).toBe('bearish')
      expect(res.setup).toBe(bull)
    })
  })

  describe('2. Radial Ring Offset Math & Geometry Bounds', () => {
    it('calculates exact stroke-dashoffset for standard score ranges', () => {
      const fullOffset = RING_CIRCUMFERENCE
      expect(calculateRingOffset(0)).toBeCloseTo(fullOffset, 2)
      expect(calculateRingOffset(100)).toBeCloseTo(0, 2)
      expect(calculateRingOffset(50)).toBeCloseTo(fullOffset * 0.5, 2)
      expect(calculateRingOffset(25)).toBeCloseTo(fullOffset * 0.75, 2)
      expect(calculateRingOffset(75)).toBeCloseTo(fullOffset * 0.25, 2)
    })

    it('renders ring progress accurately for negative scores using Math.abs', () => {
      const fullOffset = RING_CIRCUMFERENCE
      // Negative scores (e.g. -50 bearish squeeze) should render 50% stroke fill
      expect(calculateRingOffset(-50)).toBeCloseTo(fullOffset * 0.5, 2)
      expect(calculateRingOffset(-75)).toBeCloseTo(fullOffset * 0.25, 2)
      expect(calculateRingOffset(-100)).toBeCloseTo(0, 2)
    })

    it('clamps extreme positive and negative scores strictly to [0, 100]%', () => {
      expect(calculateRingOffset(150)).toBeCloseTo(0, 2)
      expect(calculateRingOffset(999)).toBeCloseTo(0, 2)
      expect(calculateRingOffset(-150)).toBeCloseTo(0, 2)
      expect(calculateRingOffset(-500)).toBeCloseTo(0, 2)
    })

    it('handles null, undefined, and NaN without runtime errors or invalid offsets', () => {
      const fullOffset = RING_CIRCUMFERENCE
      expect(calculateRingOffset(null)).toBeCloseTo(fullOffset, 2)
      expect(calculateRingOffset(undefined)).toBeCloseTo(fullOffset, 2)
      expect(calculateRingOffset(Number.NaN)).toBeCloseTo(fullOffset, 2)
    })

    it('supports custom circumference values', () => {
      const customC = 100
      expect(calculateRingOffset(40, customC)).toBeCloseTo(60, 2)
      expect(calculateRingOffset(-40, customC)).toBeCloseTo(60, 2)
    })

    it('derives RING_CIRCUMFERENCE from RING_RADIUS (2πr) so it can never drift from the SVG radius', () => {
      // Regression: RING_CIRCUMFERENCE was previously a standalone literal
      // (263.89) that had to be kept in sync by hand with RING_RADIUS and the
      // SVG's r="42" attribute. It is now computed, so the two can never
      // silently disagree.
      expect(RING_RADIUS).toBe(42)
      expect(RING_CIRCUMFERENCE).toBeCloseTo(2 * Math.PI * 42, 8)
      expect(RING_CIRCUMFERENCE).toBeCloseTo(263.8938, 3)
    })
  })

  describe('3. Currency Formatting for Near-Spot Net GEX', () => {
    it('formats positive values with leading plus sign and standard dollar unit', () => {
      expect(formatNearSpotGex(12.34)).toBe('+$12.3M')
      expect(formatNearSpotGex(0.48)).toBe('+$0.5M')
      expect(formatNearSpotGex(100)).toBe('+$100.0M')
      expect(formatNearSpotGex(0)).toBe('+$0.0M')
    })

    it('formats negative values as -$X.XM rather than $-X.XM', () => {
      expect(formatNearSpotGex(-5.2)).toBe('-$5.2M')
      expect(formatNearSpotGex(-0.4)).toBe('-$0.4M')
      expect(formatNearSpotGex(-12.34)).toBe('-$12.3M')
      expect(formatNearSpotGex(-99.9)).toBe('-$99.9M')
    })

    it('handles missing or invalid GEX values with fallback em-dash', () => {
      expect(formatNearSpotGex(null)).toBe('—')
      expect(formatNearSpotGex(undefined)).toBe('—')
      expect(formatNearSpotGex(Number.NaN)).toBe('—')
    })
  })

  describe('4. Factor Track Width Percentage Calculations & Clamping', () => {
    it('calculates proper width percentage for positive factor scores', () => {
      expect(calculateTrackWidthPct(50, 100)).toBe(50)
      expect(calculateTrackWidthPct(15, 20)).toBe(75)
      expect(calculateTrackWidthPct(10, 10)).toBe(100)
      expect(calculateTrackWidthPct(0, 50)).toBe(0)
    })

    it('clamps negative scores to 0% to prevent negative CSS widths', () => {
      expect(calculateTrackWidthPct(-10, 100)).toBe(0)
      expect(calculateTrackWidthPct(-50, 50)).toBe(0)
      expect(calculateTrackWidthPct(-0.01, 100)).toBe(0)
    })

    it('clamps overflow scores to 100%', () => {
      expect(calculateTrackWidthPct(120, 100)).toBe(100)
      expect(calculateTrackWidthPct(25, 20)).toBe(100)
    })

    it('handles zero or negative maximums safely', () => {
      expect(calculateTrackWidthPct(10, 0)).toBe(0)
      expect(calculateTrackWidthPct(10, -5)).toBe(0)
      expect(calculateTrackWidthPct(null, 100)).toBe(0)
      expect(calculateTrackWidthPct(10, null)).toBe(0)
      expect(calculateTrackWidthPct(Number.NaN, 100)).toBe(0)
    })
  })

  describe('5. Takeaway Bullet Dot Polarity & Tone', () => {
    it('assigns "pos" dot tone and upward arrow to bullish call wall level', () => {
      const takeaways = buildTakeaways({
        side: 'bullish',
        wallLevel: 580,
        wallPct: 0.025,
        wallLabel: 'Call Wall',
      })
      expect(takeaways.length).toBeGreaterThanOrEqual(1)
      expect(takeaways[0].type).toBe('pos')
      expect(takeaways[0].icon).toBe('↑')
      expect(takeaways[0].line).toContain('Call Wall at $580.00 (+2.5%)')
    })

    it('assigns "neg" dot tone and downward arrow to bearish put wall level', () => {
      const takeaways = buildTakeaways({
        side: 'bearish',
        wallLevel: 550,
        wallPct: -0.03,
        wallLabel: 'Put Wall',
      })
      expect(takeaways.length).toBeGreaterThanOrEqual(1)
      expect(takeaways[0].type).toBe('neg')
      expect(takeaways[0].icon).toBe('↓')
      expect(takeaways[0].line).toContain('Put Wall at $550.00 (-3.0%)')
    })

    it('assigns "warn" dot tone to dampened long-gamma regime notices', () => {
      const takeaways = buildTakeaways({
        side: 'bullish',
        dampened: true,
      })
      const damp = takeaways.find((t) => t.line.includes('Long-gamma regime'))
      expect(damp).toBeDefined()
      expect(damp?.type).toBe('warn')
      expect(damp?.icon).toBe('●')
    })

    it('assigns "info" dot tone to general trading implications', () => {
      const takeaways = buildTakeaways({
        side: 'bullish',
        implication: 'High positive gamma cushions abrupt drawdown.',
      })
      const impl = takeaways.find((t) => t.line.includes('cushions'))
      expect(impl).toBeDefined()
      expect(impl?.type).toBe('info')
      expect(impl?.icon).toBe('●')
    })

    it('correctly maps setup_analysis strings with keyword classification', () => {
      const takeaways = buildTakeaways({
        side: 'bearish',
        analysis: [
          'Downside acceleration below put wall magnet',
          'Zero-gamma volatility amplification zone',
          'Partial structure lean on low volume',
        ],
      })
      expect(takeaways[0].type).toBe('neg')
      expect(takeaways[0].icon).toBe('↓')
      expect(takeaways[1].type).toBe('warn')
      expect(takeaways[1].icon).toBe('●')
      expect(takeaways[2].type).toBe('info')
      expect(takeaways[2].icon).toBe('●')
    })
  })

  describe('6. Component Template & CSS Token Compliance', () => {
    const vueSrc = readFileSync(join(root, 'components/SqueezeScreener.vue'), 'utf8')

    it('colours the verdict by side through call/put tokens, never an amber override', () => {
      expect(vueSrc).toMatch(
        /\.sq\[data-tone='bullish'\]\s*\{\s*--sq-tone:\s*var\(--call-hi\);?\s*\}/,
      )
      expect(vueSrc).toMatch(
        /\.sq\[data-tone='bearish'\]\s*\{\s*--sq-tone:\s*var\(--put-hi\);?\s*\}/,
      )
      expect(vueSrc).toMatch(/\.score-num\s*\{[^}]*color:\s*var\(--sq-tone\)/s)
    })

    it('renders an unmeasured dash — not a fake $0.00 — for a null level', () => {
      // api.ts documents squeeze/GEX/wall fields as "null = unmeasured, NOT zero".
      expect(vueSrc).not.toContain("'$0.00'")
      expect(vueSrc).toContain('lv.price != null ? optUsd(lv.price) : DASH')
    })

    it('draws a meter only for a measured step', () => {
      expect(vueSrc).toContain('<i v-if="st.fill01 != null"')
    })

    it('labels the score as a theory score, not a squeeze probability', () => {
      expect(vueSrc).toContain('THEORY SCORE · NOT A FORECAST')
      expect(vueSrc).toContain('buildSqueezeExplanation')
      expect(vueSrc).not.toContain('PROBABILITY SCORE')
      expect(vueSrc).not.toContain('Imminent')
    })

    it('exposes the identity formula and the two direction legs', () => {
      expect(vueSrc).toContain('identity-formula')
      expect(vueSrc).toContain('dir-legs')
      expect(vueSrc).toContain('ex.dirLegs')
      expect(vueSrc).not.toContain('tanh(40 ×')
    })
  })
})

describe('7. Theory identity — fuel × flow × momentum, not a coin-flip forecast', () => {
  function squeeze(over: Partial<OptionsSqueeze> = {}): OptionsSqueeze {
    return {
      bullish: 0.12,
      bearish: 0.04,
      score: 8.1,
      label: 'quiet',
      primary: 'quiet',
      drivers: ['short_premium_dealer_gamma'],
      negative_fuel: 0.64,
      theory: {
        squeeze_risk: 0.021,
        fuel_ui: 0.64,
        bullish_ui: 12,
        bearish_ui: 4,
        adv_m: 850,
        adv_available: true,
        measurable: true,
        directional_flow_imbalance: 0.4,
        momentum: 0.018,
        momentum_fresh: true,
        short_premium_gex_m: { total_gex_m: -12, atm_share: 0.31, weighted_dte: 7 },
      },
      components: {
        theory_liquidity_ratio: 0.014,
        theory_atm_share: 0.31,
        theory_weighted_dte: 7,
        theory_conviction_bull: 0.34,
        theory_conviction_bear: 0.06,
        theory_directional_flow_imbalance: 0.4,
        theory_momentum: 0.018,
        theory_momentum_fresh: true,
      },
      ...over,
    }
  }

  it('unpacks every term in the shipped identity', () => {
    const id = buildTheoryIdentity(squeeze())
    expect(id.formula).toContain('tanh(25·SR)')
    expect(id.fuelScale).toBe(25)
    expect(id.fuelUi).toBeCloseTo(0.64, 4)
    expect(id.atmShare).toBeCloseTo(0.31, 4)
    expect(id.flowImbalance).toBeCloseTo(0.4, 4)
    expect(id.momentum).toBeCloseTo(0.018, 4)
    expect(id.terms.map((t) => t.id)).toEqual([
      'liquidity',
      'atm',
      'urgency',
      'fuel',
      'flow',
      'mom',
      'bull',
      'bear',
    ])
    expect(id.terms.find((t) => t.id === 'mom')?.display).toBe('1.80%')
  })

  it('uses payload fuel_scale in the formula and defaults to 25', () => {
    expect(buildTheoryIdentity(squeeze()).formula).toContain('tanh(25·SR)')
    const legacy = buildTheoryIdentity(squeeze({ theory: { ...squeeze().theory, fuel_scale: 40 } }))
    expect(legacy.fuelScale).toBe(40)
    expect(legacy.formula).toContain('tanh(40·SR)')
    expect(legacy.terms.find((t) => t.id === 'fuel')?.label).toBe('FUEL tanh(40·SR)')
  })

  it('uses shipped front-book urgency instead of recomputing from full-book DTE', () => {
    const id = buildTheoryIdentity(
      squeeze({
        theory: {
          ...squeeze().theory,
          urgency: 0.78,
          urgency_dte: 5,
          urgency_dte_basis: 'front40',
          front40_weighted_dte: 5,
        },
        components: {
          ...(squeeze().components ?? {}),
          theory_weighted_dte: 110,
        },
      }),
    )
    expect(id.weightedDte).toBeCloseTo(5, 4)
    expect(id.fullBookDte).toBeCloseTo(110, 4)
    expect(id.urgency).toBeCloseTo(0.78, 4)
    expect(id.urgencyDteBasis).toBe('front40')
    expect(id.terms.find((t) => t.id === 'urgency')?.detail).toContain('110')
  })

  it('does not call a quiet book a squeeze, and stale momentum is not a side', () => {
    expect(buildTheoryIdentity(squeeze()).state).toBe('fuel_only')
    expect(buildTheoryIdentity(squeeze({ score: 42, primary: 'bullish' })).state).toBe('bull_lean')
    expect(buildTheoryIdentity(squeeze({ score: -44, primary: 'bearish' })).state).toBe('bear_lean')
    const stale = buildTheoryIdentity(
      squeeze({
        theory: {
          squeeze_risk: 0.02,
          fuel_ui: 0.5,
          bullish_ui: 10,
          bearish_ui: 2,
          measurable: true,
          momentum: 0.08,
          momentum_fresh: false,
        },
      }),
    )
    expect(stale.terms.find((t) => t.id === 'mom')?.display).toBe('STALE')
    expect(stale.terms.find((t) => t.id === 'mom')?.tone).toBe('warn')
  })

  it('marks long-gamma dampening and missing payload as unmeasured, never imminent', () => {
    expect(buildTheoryIdentity(null).state).toBe('unmeasured')
    expect(buildTheoryIdentity(squeeze({ long_gamma_dampened: true })).state).toBe('dampened')
    expect(buildTheoryIdentity(squeeze({ long_gamma_dampened: true })).stateLabel).not.toMatch(
      /IMMINENT|LIKELY/,
    )
  })
})

describe('8. Squeeze explanation — the board shows its arithmetic', () => {
  /** Shape of the live SPY payload on 2026-09-14 after the flow-vote fix. */
  function spy(over: Partial<OptionsSqueeze> = {}): OptionsSqueeze {
    return {
      bullish: 0,
      bearish: 0.5179,
      score: -51.8,
      label: 'bearish_squeeze',
      primary: 'bearish',
      drivers: ['short_premium_dealer_gamma', 'down_momentum'],
      long_gamma_dampened: false,
      negative_fuel: 0.9772,
      theory: {
        squeeze_risk: 0.05578,
        fuel_ui: 0.9772,
        bullish_ui: 0,
        bearish_ui: 51.8,
        adv_m: 26342.1,
        adv_available: true,
        measurable: true,
        directional_flow_imbalance: null,
        flow_measured: false,
        flow_weight: 0,
        momentum: -0.0159,
        momentum_fresh: true,
        mom_ref: 0.03,
        mom_up_gate: 0,
        mom_dn_gate: 0.53,
        conviction_bull: 0,
        conviction_bear: 0.53,
        liquidity_ratio: 0.05737,
        urgency: 1,
        fuel_scale: 40,
        lean_threshold: 20,
        squeeze_threshold: 40,
        short_premium_gex_m: { total_gex_m: -1511.2, atm_share: 0.9723, weighted_dte: 0 },
      },
      components: {
        theory_liquidity_ratio: 0.05737,
        theory_atm_share: 0.9723,
        theory_weighted_dte: 0,
      },
      key_levels: {
        spot: 760.88,
        call_wall: 765,
        call_wall_pct: 0.0054,
        put_wall: 760,
        put_wall_pct: -0.0012,
        gamma_flip: 766.96,
        gamma_flip_pct: 0.008,
        pin_strike: 760,
      },
      ...over,
    }
  }

  it('reads a verdict, side and marker straight from the signed score', () => {
    const ex = buildSqueezeExplanation(spy(), 760.88)
    expect(ex.measurable).toBe(true)
    expect(ex.verdict).toBe('BEAR SQUEEZE')
    expect(ex.side).toBe('bearish')
    expect(ex.scoreDisplay).toBe('−52')
    expect(ex.markerPct).toBeCloseTo(24.1, 2)
  })

  it('walks fuel × direction = score with the payload numbers', () => {
    const ex = buildSqueezeExplanation(spy(), 760.88)
    const [fuel, dir, score] = ex.steps
    expect(fuel.value).toBe('98%')
    expect(fuel.lines.join(' ')).toContain('$1.51B')
    expect(fuel.lines.join(' ')).toContain('5.7% of the $26.34B traded per day')
    expect(fuel.lines.join(' ')).toContain('mostly expiring today')
    expect(dir.value).toBe('BEAR 53%')
    expect(dir.lines[0]).toContain("doesn't vote")
    expect(dir.lines[1]).toContain('−1.59%')
    expect(score.value).toBe('−52')
    expect(score.lines.join(' ')).toContain('Bear leg: 98% fuel × 53% = 51.8')
    expect(ex.fuelScale).toBe(40)
    expect(ex.formula).toContain('tanh(40·SR)')
    expect(ex.dirLegs.find((l) => l.id === 'flow')?.votes).toBe(false)
    expect(ex.dirLegs.find((l) => l.id === 'mom')?.votes).toBe(true)
    expect(ex.dirLegs.find((l) => l.id === 'mom')?.display).toContain('−1.59%')
  })

  it('marks the put wall as the trigger on a bearish read and orders levels by price', () => {
    const ex = buildSqueezeExplanation(spy(), 760.88)
    expect(ex.levels.map((l) => l.id)).toEqual(['gamma_flip', 'call_wall', 'spot', 'put_wall'])
    expect(ex.levels.find((l) => l.trigger)?.id).toBe('put_wall')
    expect(ex.levels.find((l) => l.id === 'gamma_flip')?.note).toContain('amplify')
  })

  it('says what would change the read, derived from fuel and the flip', () => {
    const ex = buildSqueezeExplanation(
      spy({ score: -26, bearish: 0.26, label: 'bearish_lean' }),
      760.88,
    )
    expect(ex.verdict).toBe('BEAR LEAN')
    const watch = ex.watch.join(' ')
    // squeeze at 40 needs conviction 40/97.72 → 41% of the 3% cap ≈ 1.2%
    expect(watch).toContain('±1.2% would lift it to a squeeze')
    expect(watch).toContain('Reclaiming the flip at $766.96')
    expect(watch).toContain('expires today')
  })

  it('never calls a squeeze without fuel, and caps the reachable score', () => {
    const ex = buildSqueezeExplanation(
      spy({
        score: -7.4,
        label: 'quiet',
        primary: 'quiet',
        theory: { ...spy().theory, fuel_ui: 0.148, bearish_ui: 7.4, conviction_bear: 0.5 },
      }),
      760.88,
    )
    expect(ex.verdict).toBe('NO FUEL')
    expect(ex.watch[0]).toContain('caps the score at ±15')
  })

  it('reports long gamma as dampened and a missing payload as unmeasured, with no numbers', () => {
    expect(buildSqueezeExplanation(spy({ long_gamma_dampened: true }), 760.88).verdict).toBe(
      'DAMPENED',
    )
    const none = buildSqueezeExplanation(null, null)
    expect(none.verdict).toBe('UNMEASURED')
    expect(none.scoreDisplay).toBe('—')
    expect(none.markerPct).toBeNull()
    expect(none.steps.every((s) => s.fill01 == null)).toBe(true)
    expect(none.levels).toEqual([])
  })

  it('keeps flow as a vote when the tape is signed', () => {
    const ex = buildSqueezeExplanation(
      spy({
        theory: {
          ...spy().theory,
          directional_flow_imbalance: -0.4,
          flow_measured: true,
          flow_weight: 0.5,
        },
      }),
      760.88,
    )
    expect(ex.steps[1].lines[0]).toContain('Signed flow -0.4')
    expect(ex.watch.join(' ')).not.toContain('second vote')
  })

  it('treats an out-of-range legacy fuel as unmeasured instead of printing >100%', () => {
    const ex = buildSqueezeExplanation(
      spy({ negative_fuel: 14.5, theory: { ...spy().theory, fuel_ui: undefined } }),
      760.88,
    )
    expect(ex.steps[0].value).toBe('—')
    expect(ex.steps[0].fill01).toBeNull()
  })

  it('lets the readout label win over the two-way leg test', () => {
    const ex = buildSqueezeExplanation(
      spy({
        label: 'bearish_lean',
        score: -26,
        theory: { ...spy().theory, bullish_ui: 12, bearish_ui: 38 },
      }),
      760.88,
    )
    expect(ex.verdict).toBe('BEAR LEAN')
  })

  it('formats $M figures compactly without inventing a zero', () => {
    expect(formatMillions(1511.2)).toBe('$1.51B')
    expect(formatMillions(115.14)).toBe('$115M')
    expect(formatMillions(-12.44)).toBe('−$12.4M')
    expect(formatMillions(null)).toBe('—')
  })
})

describe('9. Direction honesty — measured / partial / degraded', () => {
  /** A real NVDA-style degraded payload: tape unsigned, momentum 5 days stale. */
  function nvda(over: Partial<OptionsSqueeze> = {}): OptionsSqueeze {
    return {
      bullish: 0,
      bearish: 0,
      score: 0,
      label: 'quiet',
      primary: 'quiet',
      drivers: ['short_premium_dealer_gamma'],
      long_gamma_dampened: false,
      negative_fuel: 0.05,
      theory: {
        squeeze_risk: 0.0013,
        fuel_ui: 0.05,
        bullish_ui: 0,
        bearish_ui: 0,
        adv_m: 9400,
        adv_available: true,
        measurable: true,
        directional_flow_imbalance: null,
        flow_measured: false,
        flow_weight: 0,
        momentum: 0.011,
        momentum_fresh: false,
        momentum_price_age_days: 5,
        short_premium_gex_m: { total_gex_m: -1.1, atm_share: 0.3, weighted_dte: 3 },
      },
      key_levels: {
        spot: 177.4,
        call_wall: 185,
        call_wall_pct: 0.043,
        put_wall: 170,
        put_wall_pct: -0.042,
        gamma_flip: 180.2,
        gamma_flip_pct: 0.016,
        pin_strike: 175,
      },
      ...over,
    }
  }

  it('suppresses the score when neither direction leg votes — never a numeric 0', () => {
    const ex = buildSqueezeExplanation(nvda(), 177.4)
    expect(ex.dirStatus).toBe('degraded')
    expect(ex.verdict).toBe('DIRECTION UNMEASURED')
    expect(ex.tone).toBe('unmeasured')
    expect(ex.score).toBeNull()
    expect(ex.scoreDisplay).toBe('—')
    expect(ex.markerPct).toBeNull()
    expect(ex.side).toBe('neutral')
    expect(ex.summary).toContain('suppressed, not a zero')
    expect(ex.dirChip?.text).toBe('DIRECTION UNMEASURED · SCORE SUPPRESSED')
  })

  it('keeps structural sections alive in the degraded state', () => {
    const ex = buildSqueezeExplanation(nvda(), 177.4)
    const [fuel, dir, score] = ex.steps
    expect(fuel.value).not.toBe('—')
    expect(fuel.fill01).not.toBeNull()
    expect(dir.value).toBe('—')
    expect(dir.fill01).toBeNull()
    expect(dir.tone).toBe('warn')
    expect(score.value).toBe('—')
    expect(score.fill01).toBeNull()
    expect(score.lines.join(' ')).not.toMatch(/Bull leg|Bull − bear/)
    expect(dir.lines.join(' ')).toContain('5 calendar days old')
    expect(ex.levels.length).toBeGreaterThanOrEqual(3)
    expect(ex.watch.join(' ')).toContain('restore the momentum vote')
    expect(ex.watch.join(' ')).toContain('direction vote')
  })

  it('shows the voting leg in the partial state and names the other UNMEASURED', () => {
    // Same payload shape as the live SPY read: momentum fresh, tape unsigned.
    const wMom = buildSqueezeExplanation(
      nvda({ theory: { ...nvda().theory, momentum_fresh: true } }),
      177.4,
    )
    expect(wMom.dirStatus).toBe('partial')
    expect(wMom.dirChip?.text).toBe('DIRECTION PARTIAL · SIGNED FLOW UNMEASURED')
    expect(wMom.scoreDisplay).not.toBe('—')
    expect(wMom.steps[1].lines.join(' ')).toContain('UNMEASURED')
    expect(wMom.steps[1].lines.join(' ')).toContain("doesn't vote")
  })

  it('reports full measurement with no chip when both legs vote', () => {
    const both = buildSqueezeExplanation(
      nvda({
        score: 12.4,
        bullish: 0.124,
        theory: {
          ...nvda().theory,
          directional_flow_imbalance: 0.3,
          flow_measured: true,
          flow_weight: 0.5,
          momentum_fresh: true,
        },
      }),
      177.4,
    )
    expect(both.dirStatus).toBe('measured')
    expect(both.dirChip).toBeNull()
    expect(both.markerPct).not.toBeNull()
  })

  it('a measured flat zero conviction still renders as a real NONE, not an em-dash', () => {
    const flat = buildSqueezeExplanation(
      nvda({
        score: 0,
        theory: {
          ...nvda().theory,
          directional_flow_imbalance: 0.01,
          flow_measured: true,
          flow_weight: 0.5,
          momentum: 0.001,
          momentum_fresh: true,
          momentum_price_age_days: 0,
          conviction_bull: 0,
          conviction_bear: 0,
        },
      }),
      177.4,
    )
    expect(flat.dirStatus).toBe('measured')
    expect(flat.steps[1].value).toBe('NONE')
  })
})
