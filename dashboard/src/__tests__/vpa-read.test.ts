import { describe, it, expect } from 'vitest'
import {
  readVpa,
  formatRiskReward,
  humaniseSignal,
  normaliseStance,
  buildRiskLadder,
  DASH,
} from '@/vpaRead'
import type { VpaAnalysisResult } from '@/vpaContracts'

describe('vpaRead tactical reading logic', () => {
  it('returns null for null or undefined input', () => {
    expect(readVpa(null)).toBeNull()
    expect(readVpa(undefined)).toBeNull()
  })

  it('correctly normalises arbitrary bias strings into strict stances', () => {
    expect(normaliseStance('LONG')).toBe('long')
    expect(normaliseStance('Strongly Bullish')).toBe('long')
    expect(normaliseStance('SHORT')).toBe('short')
    expect(normaliseStance('Bearish Rejection')).toBe('short')
    expect(normaliseStance('NEUTRAL / WAIT')).toBe('neutral')
    expect(normaliseStance('SIDEWAYS')).toBe('neutral')
    expect(normaliseStance('')).toBe('neutral')
    expect(normaliseStance(null)).toBe('neutral')
  })

  it('formats risk-reward numbers and strings honestly', () => {
    expect(formatRiskReward(2.456)).toBe('1 : 2.46')
    expect(formatRiskReward('1 : 3.0')).toBe('1 : 3.0')
    expect(formatRiskReward(null)).toBe(DASH)
    expect(formatRiskReward(undefined)).toBe(DASH)
    expect(formatRiskReward(0)).toBe(DASH)
  })

  it('humanises snake_case signal identifiers into clean display labels', () => {
    expect(humaniseSignal('stopping_volume')).toBe('Stopping Volume')
    expect(humaniseSignal('low_volume_test')).toBe('Low Volume Test')
    expect(humaniseSignal('effort_vs_result')).toBe('Effort Vs Result')
    expect(humaniseSignal('')).toBe(DASH)
  })

  const mockBullishPayload: VpaAnalysisResult = {
    symbol: 'NVDA',
    timeframe: '1h',
    market_phase: 'Markup Phase (Demand in Control)',
    dominant_sentiment: 'Strongly Bullish',
    confidence_score: 0.82,
    effort_vs_result_verdict: 'VALIDATION (Effort = Result)',
    forensic_breakdown: {
      wyckoff_phase: 'NVDA at $128.50 on 1h bars. Demand in control.',
      key_candles: [
        {
          candle_type: 'Hammer Candle (09-04 10:30)',
          spread: 'Wide (3.20)',
          volume: 'Ultra High (2.4x)',
          verdict: 'VALIDATION',
          interpretation: 'Demand overwhelmed selling.',
        },
      ],
      stopping_or_topping: {
        detected: true,
        type: 'Stopping Volume',
        details: 'High volume lower wick rejected lower prices.',
      },
      test_candles: {
        detected: true,
        type: 'Low Volume Supply Test',
        result: 'Successful',
      },
      support_resistance: {
        floor_support: '$124.00 band',
        ceiling_resistance: '$135.00 band',
        pivot_highs: '$135.00',
        pivot_lows: '$124.00',
        method: 'fractal pivots',
      },
      volume_at_price: '$126.00 POC',
    },
    primary_scenario: {
      likely_move: 'Bullish continuation toward $135.00',
      direction: 'BULLISH',
      probability_pct: 78,
      target_zone: '$135.00',
      expected_horizon: '4 to 8 bars',
      rationale: 'Volume validates markup.',
    },
    alternative_scenarios: [
      {
        thesis: 'Fakeout Reversal',
        probability_pct: 22,
        speculative_read: 'Failure to hold above breakout.',
        invalidation_trigger: 'Candle close below $124.00 on high volume',
        risk_warning: 'Exit if support fails.',
      },
    ],
    trade_execution_guide: {
      bias: 'LONG',
      entry_trigger: 'Enter on pullback test of $126.50',
      stop_loss_placement: 'Stop below $124.00 support',
      risk_reward_ratio: 2.5,
      entry_price: 126.5,
      stop_price: 124.0,
      target_price: 132.75,
      rules_applied: ['Wyckoff Law of Effort vs Result', 'rule.breakout'],
    },
    levels: [
      {
        price: 124.0,
        low: 123.5,
        high: 124.5,
        kind: 'support',
        strength: 0.85,
        touches: 4,
        source: 'pivot_cluster',
        role_reversed: false,
      },
      {
        price: 135.0,
        low: 134.2,
        high: 135.8,
        kind: 'resistance',
        strength: 0.75,
        touches: 3,
        source: 'pivot_cluster',
        role_reversed: false,
      },
    ],
    vap: {
      poc: 126.0,
      poc_low: 125.5,
      poc_high: 126.5,
      value_area_low: 124.0,
      value_area_high: 130.0,
      value_area_pct: 0.71,
      total_volume: 54000000,
    },
    evidence: [
      {
        signal: 'stopping_volume',
        direction: 'bullish',
        weight: 0.25,
        bars: [12, 13],
        book_ref: 'rule.stopping-volume',
        detail: 'Ultra-high volume absorption at support.',
      },
      {
        signal: 'supply_test',
        direction: 'bullish',
        weight: 0.18,
        bars: [15],
        book_ref: 'rule.supply-demand-test',
        detail: 'Low volume test confirms supply exhaustion.',
      },
    ],
    dynamic_trend: {
      direction: 'bullish',
      detail: 'Upward dynamic trend line through higher pivot lows.',
      pivot_count: 3,
      slope_per_bar: 0.35,
    },
    congestion_patterns: [],
    atr: 2.15,
  }

  it('derives a complete, cohesive tactical read from a bullish response', () => {
    const read = readVpa(mockBullishPayload)!
    expect(read).not.toBeNull()
    expect(read.symbol).toBe('NVDA')
    expect(read.timeframe).toBe('1h')
    expect(read.stance).toBe('long')
    expect(read.stanceLabel).toBe('LONG')
    expect(read.stanceTone).toBe('pos')
    expect(read.summaryHeadline).toBe('Bullish continuation toward $135.00')

    // Pillars
    expect(read.marketPhase).toBe('Markup Phase (Demand in Control)')
    expect(read.effortVsResult).toContain('VALIDATION')
    expect(read.effortTone).toBe('pos')
    expect(read.confidencePct).toBe(82)
    expect(read.confidenceTone).toBe('pos')

    // Trade plan
    expect(read.plan.entry).toBe(126.5)
    expect(read.plan.stop).toBe(124.0)
    expect(read.plan.target).toBe(132.75)
    expect(read.plan.risk).toBe(2.5)
    expect(read.plan.reward).toBe(6.25)
    expect(read.plan.riskReward).toBe('1 : 2.50')
    expect(read.plan.riskRewardTone).toBe('pos')
    expect(read.plan.invalidation).toBe('Candle close below $124.00 on high volume')

    // Structure
    expect(read.structure.poc).toBe(126.0)
    expect(read.structure.val).toBe(124.0)
    expect(read.structure.vah).toBe(130.0)
    expect(read.structure.atr).toBe(2.15)
    expect(read.structure.nearestSupport?.price).toBe(124.0)
    expect(read.structure.nearestResistance?.price).toBe(135.0)

    // Dynamics
    expect(read.stoppingOrTopping.detected).toBe(true)
    expect(read.testCandles.detected).toBe(true)
    expect(read.dynamicTrend?.direction).toBe('bullish')

    // Executive readout
    expect(read.executiveReadout).toContain('NVDA')
    expect(read.executiveReadout).toContain('Markup Phase')
    expect(read.executiveReadout).toContain(
      'Invalidation: Candle close below $124.00 on high volume',
    )

    // Top signals
    expect(read.topSignals).toHaveLength(2)
    expect(read.topSignals[0].name).toBe('Stopping Volume')
    expect(read.topSignals[0].direction).toBe('bullish')
  })

  it('handles missing or incomplete fields without throwing or generating fake numbers', () => {
    const minimal: VpaAnalysisResult = {
      symbol: 'SPY',
      timeframe: 'Daily',
      market_phase: 'Congestion',
      dominant_sentiment: 'Neutral',
      confidence_score: null,
      effort_vs_result_verdict: 'UNKNOWN',
      forensic_breakdown: {
        wyckoff_phase: 'Unclear',
        key_candles: [],
        stopping_or_topping: { detected: false, type: 'None', details: '' },
        test_candles: { detected: false, type: 'None', result: 'None' },
        support_resistance: {
          floor_support: '—',
          ceiling_resistance: '—',
          pivot_highs: '—',
          pivot_lows: '—',
        },
        volume_at_price: '—',
      },
      primary_scenario: {
        likely_move: 'Sideways drift',
        direction: 'SIDEWAYS',
        probability_pct: 50,
        target_zone: '—',
        expected_horizon: '—',
        rationale: '—',
      },
      alternative_scenarios: [],
      trade_execution_guide: {
        bias: 'NEUTRAL',
        entry_trigger: '',
        stop_loss_placement: '',
        risk_reward_ratio: null,
        rules_applied: [],
      },
    }

    const read = readVpa(minimal)!
    expect(read).not.toBeNull()
    expect(read.stance).toBe('neutral')
    expect(read.stanceLabel).toBe('NEUTRAL')
    expect(read.confidencePct).toBeNull()
    expect(read.confidenceTone).toBe('flat')
    expect(read.plan.entry).toBeNull()
    expect(read.plan.stop).toBeNull()
    expect(read.plan.target).toBeNull()
    expect(read.plan.riskReward).toBe(DASH)
    expect(read.structure.poc).toBeNull()
    expect(read.structure.nearestSupport).toBeNull()
    expect(read.structure.nearestResistance).toBeNull()
  })

  it('properly stamps reference textbook cases', () => {
    const sample: VpaAnalysisResult = {
      symbol: 'HON',
      timeframe: 'Daily',
      is_sample: true,
      sample_title: 'Stored reference case',
      book_reference: 'stored-reference',
      market_phase: 'Accumulation',
      dominant_sentiment: 'Bullish',
      confidence_score: 0.92,
      effort_vs_result_verdict: 'VALIDATION',
      forensic_breakdown: {
        wyckoff_phase: 'Accumulation complete',
        key_candles: [],
        stopping_or_topping: { detected: true, type: 'Stopping Volume', details: '' },
        test_candles: { detected: false, type: 'None', result: 'None' },
        support_resistance: {
          floor_support: '—',
          ceiling_resistance: '—',
          pivot_highs: '—',
          pivot_lows: '—',
        },
        volume_at_price: '—',
      },
      primary_scenario: {
        likely_move: 'Markup',
        direction: 'BULLISH',
        probability_pct: 82,
        target_zone: '—',
        expected_horizon: '—',
        rationale: '—',
      },
      alternative_scenarios: [],
      trade_execution_guide: {
        bias: 'LONG',
        entry_trigger: '',
        stop_loss_placement: '',
        risk_reward_ratio: '1 : 3.2',
        rules_applied: [],
      },
    }

    const read = readVpa(sample)!
    expect(read.isSample).toBe(true)
    expect(read.sampleTitle).toBe('Stored reference case')
    expect(read.bookReference).toBe('stored-reference')
  })

  it('handles zero-bar engine fallback response cleanly with honest tones and messaging', () => {
    const noData: VpaAnalysisResult = {
      symbol: 'AAPL',
      timeframe: '15m',
      market_phase: 'Unknown — no bars analysed',
      dominant_sentiment: 'Unknown',
      confidence_score: null,
      effort_vs_result_verdict: 'UNKNOWN',
      data_status: { analysed: false, reason: 'no bars available' },
      bars: [],
      forensic_breakdown: {
        wyckoff_phase: 'No bars loaded for AAPL: no bars available.',
        key_candles: [],
        stopping_or_topping: { detected: false, type: 'None', details: 'Not evaluated' },
        test_candles: { detected: false, type: 'None', result: 'None' },
        support_resistance: {
          floor_support: '—',
          ceiling_resistance: '—',
          pivot_highs: '—',
          pivot_lows: '—',
        },
        volume_at_price: '—',
      },
      primary_scenario: {
        likely_move: 'Not computed — no bars',
        direction: 'UNKNOWN',
        probability_pct: null,
        target_zone: '—',
        expected_horizon: '—',
        rationale: 'no bars available',
      },
      alternative_scenarios: [
        {
          thesis: 'Not computed — no bars',
          probability_pct: null,
          speculative_read: 'no bars available',
          invalidation_trigger: 'Not available without bars to analyse.',
          risk_warning: 'No analysis was produced; do not trade from this response.',
        },
      ],
      trade_execution_guide: {
        bias: 'NO READ',
        entry_trigger: '—',
        stop_loss_placement: '—',
        risk_reward_ratio: null,
        rules_applied: [],
      },
    }

    const read = readVpa(noData)!
    expect(read).not.toBeNull()
    expect(read.stance).toBe('neutral')
    expect(read.stanceTone).toBe('flat')
    expect(read.summaryHeadline).toContain('No historical bars analysed')
    expect(read.executiveReadout).toContain('No bar data available to analyse')
    expect(read.confidencePct).toBeNull()
    expect(read.confidenceTone).toBe('flat')
    expect(read.plan.trigger).toBe(DASH)
    expect(read.plan.stopPlacement).toBe(DASH)
    expect(read.plan.stopPlacementTone).toBe('flat')
    expect(read.plan.targetZone).toBe(DASH)
    expect(read.plan.targetZoneTone).toBe('flat')
    expect(read.plan.invalidation).toBe('Not available without bars to analyse.')
    expect(read.plan.invalidationTone).toBe('flat')
  })
})

describe('buildRiskLadder keeps clustered trade levels readable', () => {
  it('merges last into entry when they print as the same price', () => {
    const ladder = buildRiskLadder({
      entry: 217.3,
      stop: 222.31,
      target: 215.0,
      last: 217.301,
    })
    expect(ladder).not.toBeNull()
    expect(ladder!.direction).toBe('short')
    expect(ladder!.rungs.map((r) => r.label)).toEqual(['STOP', 'ENTRY · LAST', 'TARGET'])
    expect(ladder!.rungs.map((r) => r.price.toFixed(2))).toEqual(['222.31', '217.30', '215.00'])
    expect(ladder!.rungs[1]?.isEntry).toBe(true)
    expect(ladder!.risk).toBeCloseTo(5.01, 2)
    expect(ladder!.reward).toBeCloseTo(2.3, 2)
  })

  it('keeps a distinct last as its own rung instead of overlapping the entry', () => {
    const ladder = buildRiskLadder({
      entry: 217.3,
      stop: 222.31,
      target: 215.0,
      last: 218.1,
    })
    expect(ladder!.rungs.map((r) => r.label)).toEqual(['STOP', 'LAST', 'ENTRY', 'TARGET'])
  })

  it('sorts high price to low and paints risk/reward on the connectors', () => {
    const ladder = buildRiskLadder({
      entry: 126.5,
      stop: 124.0,
      target: 132.75,
    })
    expect(ladder!.direction).toBe('long')
    expect(ladder!.rungs.map((r) => r.label)).toEqual(['TARGET', 'ENTRY', 'STOP'])
    expect(ladder!.rungs[0]?.segBelow).toBe('reward')
    expect(ladder!.rungs[1]?.segBelow).toBe('risk')
    expect(ladder!.rungs[2]?.segBelow).toBeNull()
  })

  it('returns null when the triplet is not measurable', () => {
    expect(buildRiskLadder({ entry: Number.NaN, stop: 1, target: 2 })).toBeNull()
    expect(buildRiskLadder({ entry: 1, stop: Number.POSITIVE_INFINITY, target: 2 })).toBeNull()
  })
})
