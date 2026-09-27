import { describe, expect, it } from 'vitest'
import {
  buildLadder,
  humaniseError,
  prettyReason,
  rankLevels,
  readCall,
  pullMass,
  readTargets,
  sortWorries,
} from '@/briefRead'

/* Shaped from a real /api/adaptive-signal?symbol=NVDA response. */
const SIGNAL = {
  side: 'neutral',
  composite_score: 0.007,
  agreement_band: 'thin',
  stream_scores: { fundamental: 0.0573, sector: -0.1796, sentiment: 0.0972, technical: 0.0647 },
  weights: {
    base: { fundamental: 0.2, sector: 0.25, sentiment: 0.15, technical: 0.4 },
    adapted: { fundamental: 0.2, sector: 0.25, sentiment: 0.15, technical: 0.4 },
    adaptation_mode: 'regime_map_only',
    contributions: {
      fundamental: 0.01146,
      sector: -0.0449,
      sentiment: 0.01458,
      technical: 0.02588,
    },
  },
  reasons: ['technical:above_ma20', 'sector:sector_flow_out'],
}

const HIT_RATES = { events_scored: 1, min_events: 5, stream_performance: {} }

describe('readCall', () => {
  it('reports the stack’s side and score rather than deriving its own', () => {
    const call = readCall(SIGNAL, HIT_RATES)!
    expect(call.side).toBe('neutral')
    expect(call.score).toBe(0.007)
    expect(call.band).toBe('thin')
  })

  it('orders streams by what they actually moved, not by weight', () => {
    /* Sector carries less weight than technical but contributed nearly twice
       as much, so it must lead. Ordering by weight would put technical first
       and misrepresent what produced the number. */
    const call = readCall(SIGNAL, HIT_RATES)!
    expect(call.streams.map((s) => s.name)).toEqual([
      'sector',
      'technical',
      'sentiment',
      'fundamental',
    ])
  })

  it('flags regime_map_only weights as not performance-tilted, and says why', () => {
    const call = readCall(SIGNAL, HIT_RATES)!
    expect(call.performanceTilted).toBe(false)
    expect(call.weightNote).toContain('1 of 5')
  })

  it('reports a genuine performance tilt when the stack applied one', () => {
    const call = readCall(
      { ...SIGNAL, weights: { ...SIGNAL.weights, adaptation_mode: 'performance_tilt' } },
      { events_scored: 60, min_events: 5, stream_performance: { technical: 0.58 } },
    )!
    expect(call.performanceTilted).toBe(true)
    expect(call.weightNote).toContain('60 scored events')
  })

  it('falls back to base weights when no adapted set is present', () => {
    const call = readCall(
      { ...SIGNAL, weights: { base: { technical: 1 }, adaptation_mode: 'regime_map_only' } },
      HIT_RATES,
    )!
    expect(call.streams).toHaveLength(1)
    expect(call.streams[0].weight).toBe(1)
  })

  it('derives a contribution when the payload omits one', () => {
    const call = readCall(
      {
        stream_scores: { technical: 0.5 },
        weights: { adapted: { technical: 0.4 }, adaptation_mode: 'regime_map_only' },
      },
      HIT_RATES,
    )!
    expect(call.streams[0].contribution).toBeCloseTo(0.2)
  })

  it('returns null rather than a neutral-looking zero when nothing loaded', () => {
    expect(readCall(null)).toBeNull()
    expect(readCall(undefined)).toBeNull()
  })
})

describe('humaniseError', () => {
  it('never leaks the endpoint or the timeout budget to a reader', () => {
    const raw = 'API request timed out after 30s: /api/supply-chain?symbol=INFQ&depth=2'
    const out = humaniseError(raw, 'Supply chain')!
    expect(out).not.toContain('/api/')
    expect(out).not.toContain('30s')
    expect(out).toContain('Supply chain')
  })

  it('distinguishes the failure kinds a reader can act on', () => {
    expect(humaniseError('404 Not Found', 'Options')).toContain('No options data exists')
    expect(humaniseError('Failed to fetch', 'Flow')).toContain('Could not reach')
    expect(humaniseError('503 Service Unavailable', 'Flow')).toContain('returned an error')
  })

  it('passes through nothing when there is no error', () => {
    expect(humaniseError(null, 'Flow')).toBeNull()
  })
})

describe('prettyReason', () => {
  it('unpacks the stream:token form the payload uses', () => {
    expect(prettyReason('technical:above_ma20')).toBe('technical · above ma20')
    expect(prettyReason('elevated_tail_risk')).toBe('elevated tail risk')
  })
})

describe('rankLevels', () => {
  const raw = [
    { kind: 'put_wall' as const, label: 'Put wall', price: 190 },
    { kind: 'call_wall' as const, label: 'Call wall', price: 230 },
    { kind: 'gamma_flip' as const, label: 'Gamma flip', price: 213.62 },
  ]

  it('orders by absolute distance from spot, so the nearest level leads', () => {
    expect(rankLevels(217.55, raw).map((l) => l.kind)).toEqual([
      'gamma_flip',
      'call_wall',
      'put_wall',
    ])
  })

  it('signs the distance and labels the side', () => {
    const [flip] = rankLevels(217.55, raw)
    expect(flip.distPct).toBeCloseTo(((213.62 - 217.55) / 217.55) * 100)
    expect(flip.side).toBe('below')
  })

  it('drops levels the payload did not locate instead of drawing them at zero', () => {
    const out = rankLevels(100, [
      { kind: 'call_wall', label: 'Call wall', price: null },
      { kind: 'put_wall', label: 'Put wall', price: 0 },
      { kind: 'pin', label: 'Pin', price: 105 },
    ])
    expect(out.map((l) => l.kind)).toEqual(['pin'])
  })

  it('returns nothing without a spot to measure against', () => {
    expect(rankLevels(null, raw)).toEqual([])
    expect(rankLevels(0, raw)).toEqual([])
  })
})

describe('sortWorries', () => {
  it('puts high severity first and keeps insertion order inside a tier', () => {
    const out = sortWorries([
      { severity: 'low', title: 'l', detail: '' },
      { severity: 'high', title: 'h1', detail: '' },
      { severity: 'medium', title: 'm', detail: '' },
      { severity: 'high', title: 'h2', detail: '' },
    ])
    expect(out.map((w) => w.title)).toEqual(['h1', 'h2', 'm', 'l'])
  })
})

/* Shaped from a real /api/price-attractors?symbol=NVDA response. */
const ATTRACTORS = {
  spot: 217.55,
  regime_label: 'Positive Gamma',
  regime_strength: 0.8207,
  dominant_direction: 'bullish_pull',
  primary_magnet: {
    id: 'call_wall',
    label: 'Call Wall',
    price: 220,
    pull_score: 62.9,
    distance_pct: 1.1262,
    regime_role: 'Overhead Resistance Cap',
    lens_count: 1,
    supporting_lenses: ['GAMMA'],
    direction: 'above',
    is_primary_magnet: true,
  },
  levels: [
    {
      id: 'poc',
      label: 'Volume POC',
      price: 225,
      pull_score: 43.9,
      distance_pct: 3.42,
      direction: 'above',
    },
    {
      id: 'call_wall',
      label: 'Call Wall',
      price: 220,
      pull_score: 62.9,
      distance_pct: 1.13,
      direction: 'above',
    },
    {
      id: 'kin',
      label: 'Kinematic Attractor',
      price: 218.97,
      pull_score: 57,
      distance_pct: 0.65,
      direction: 'above',
    },
    {
      id: 'pin',
      label: 'Max Pain Pin',
      price: 195,
      pull_score: 26.1,
      distance_pct: -10.37,
      direction: 'below',
    },
  ],
  confluence_clusters: [
    { level: 219.485, distance_pct: 0.8895, lens_count: 2, supporting_lenses: ['GAMMA', 'KALMAN'] },
  ],
  quality: { measurable: true, reason: null },
}

describe('readTargets', () => {
  it('ranks destinations by the stack’s pull score, strongest first', () => {
    /* The payload does not arrive sorted. Ordering is the answer to "where
       does it make sense to go", so it must not depend on array order. */
    const t = readTargets(ATTRACTORS)!
    expect(t.levels.map((l) => l.price)).toEqual([220, 218.97, 225, 195])
  })

  it('surfaces the primary magnet and its pull as the headline destination', () => {
    const t = readTargets(ATTRACTORS)!
    expect(t.primary?.price).toBe(220)
    expect(t.primary?.pull).toBeCloseTo(62.9)
    expect(t.pullLabel).toBe('Pulling up')
  })

  it('reports only clusters where two or more lenses actually agree', () => {
    const t = readTargets(ATTRACTORS)!
    expect(t.confluence?.price).toBeCloseTo(219.485)
    expect(t.confluence?.lenses).toEqual(['GAMMA', 'KALMAN'])

    const single = readTargets({
      ...ATTRACTORS,
      confluence_clusters: [{ level: 219, lens_count: 1, supporting_lenses: ['GAMMA'] }],
    })!
    expect(single.confluence).toBeNull()
  })

  it('withholds every target when the chain was not measurable', () => {
    const t = readTargets({
      ...ATTRACTORS,
      quality: { measurable: false, reason: 'No open interest on this chain.' },
    })!
    expect(t.levels).toEqual([])
    expect(t.primary).toBeNull()
    expect(t.reason).toBe('No open interest on this chain.')
  })

  it('drops levels with no usable price rather than plotting them at zero', () => {
    const t = readTargets({
      ...ATTRACTORS,
      levels: [
        { label: 'Broken', price: 0 },
        { label: 'Fine', price: 100, pull_score: 5 },
      ],
    })!
    expect(t.levels.map((l) => l.label)).toEqual(['Fine'])
  })

  it('returns null when the lens has not loaded', () => {
    expect(readTargets(null)).toBeNull()
  })
})

describe('buildLadder', () => {
  const levels = [
    {
      kind: 'put_wall' as const,
      label: 'Put wall',
      price: 400,
      distPct: -14.1,
      meaning: '',
      side: 'below' as const,
    },
    {
      kind: 'pin' as const,
      label: 'Pin strike',
      price: 400,
      distPct: -14.1,
      meaning: '',
      side: 'below' as const,
    },
    {
      kind: 'vol_trigger' as const,
      label: 'Vol trigger',
      price: 400,
      distPct: -14.1,
      meaning: '',
      side: 'below' as const,
    },
    {
      kind: 'gamma_flip' as const,
      label: 'Gamma flip',
      price: 476.91,
      distPct: 2.5,
      meaning: '',
      side: 'above' as const,
    },
  ]
  const targets = [
    {
      id: 'poc',
      label: 'Volume POC',
      price: 400,
      pull: 30,
      distancePct: -14.1,
      role: '',
      lensCount: 1,
      lenses: ['VOLUME'],
      side: 'below' as const,
      isPrimary: false,
    },
    {
      id: 'kin',
      label: 'Kinematic Attractor',
      price: 477.19,
      pull: 46,
      distancePct: 2.5,
      role: '',
      lensCount: 1,
      lenses: ['KALMAN'],
      side: 'above' as const,
      isPrimary: true,
    },
  ]

  it('collapses one price carrying many roles into a single rung', () => {
    /* AMD printed 400.00 four times across two cards — put wall, pin, vol
       trigger and volume POC are all the same price. */
    const { rungs } = buildLadder(465.46, levels, targets)
    const at400 = rungs.filter((r) => Math.abs(r.price - 400) < 1)
    expect(at400).toHaveLength(1)
    /* "Put Wall" from the attractor and "Put wall" from the level list are
       the same role in different case, and must not both appear. */
    expect(at400[0].roles).toEqual(['Volume POC', 'Put wall', 'Pin strike', 'Vol trigger'])
  })

  it('merges near-identical prices from different lenses onto one rung', () => {
    /* 476.91 and 477.19 are 0.06% apart — the same shelf, not two. */
    const { rungs } = buildLadder(465.46, levels, targets)
    const near477 = rungs.filter((r) => r.price > 470)
    expect(near477).toHaveLength(1)
    expect(near477[0].pull).toBe(46)
  })

  it('keeps the strongest pull when several land on one rung', () => {
    const { rungs } = buildLadder(
      100,
      [],
      [
        {
          id: 'a',
          label: 'A',
          price: 110,
          pull: 20,
          distancePct: 10,
          role: '',
          lensCount: 1,
          lenses: [],
          side: 'above',
          isPrimary: false,
        },
        {
          id: 'b',
          label: 'B',
          price: 110,
          pull: 70,
          distancePct: 10,
          role: '',
          lensCount: 1,
          lenses: [],
          side: 'above',
          isPrimary: false,
        },
      ],
    )
    expect(rungs[0].pull).toBe(70)
  })

  it('sorts high price to low, so the ladder reads like a price axis', () => {
    const { rungs } = buildLadder(465.46, levels, targets)
    const prices = rungs.map((r) => r.price)
    expect(prices).toEqual([...prices].sort((a, b) => b - a))
  })

  it('signs distance from spot to the level, one convention throughout', () => {
    const { rungs } = buildLadder(465.46, levels, targets)
    const above = rungs.find((r) => r.price > 470)!
    expect(above.distPct).toBeGreaterThan(0)
    expect(above.side).toBe('above')
  })

  it('returns nothing without a spot to measure against', () => {
    expect(buildLadder(null, levels, targets)).toEqual({ rungs: [], dropped: 0 })
  })
})

describe('pullMass', () => {
  it('splits total pull either side of spot', () => {
    /* AMD read "pulling down" on downside mass while its single strongest
       magnet sat above spot. Both facts are real; the split shows why. */
    const { above, below } = pullMass([
      {
        id: 'a',
        label: 'A',
        price: 477,
        pull: 46,
        distancePct: 2.5,
        role: '',
        lensCount: 1,
        lenses: [],
        side: 'above',
        isPrimary: true,
      },
      {
        id: 'b',
        label: 'B',
        price: 420,
        pull: 30,
        distancePct: -9.8,
        role: '',
        lensCount: 1,
        lenses: [],
        side: 'below',
        isPrimary: false,
      },
      {
        id: 'c',
        label: 'C',
        price: 400,
        pull: 28,
        distancePct: -14.1,
        role: '',
        lensCount: 1,
        lenses: [],
        side: 'below',
        isPrimary: false,
      },
    ])
    expect(above).toBe(46)
    expect(below).toBe(58)
  })

  it('is zero either side when nothing scored', () => {
    expect(pullMass([])).toEqual({ above: 0, below: 0 })
  })
})

describe('buildLadder distance guard', () => {
  it('drops a degenerate solve instead of plotting it, and counts it', () => {
    /* AMD's attractor endpoint returned a "Zero-Gamma Flip" at 5.00 against a
       465 spot. On a shared scale that one rung flattens every real level. */
    const { rungs, dropped } = buildLadder(
      465.46,
      [],
      [
        {
          id: 'z',
          label: 'Zero-Gamma Flip',
          price: 5,
          pull: 10,
          distancePct: -98.9,
          role: '',
          lensCount: 1,
          lenses: [],
          side: 'below',
          isPrimary: false,
        },
        {
          id: 'k',
          label: 'Kinematic',
          price: 477,
          pull: 46,
          distancePct: 2.5,
          role: '',
          lensCount: 1,
          lenses: [],
          side: 'above',
          isPrimary: true,
        },
      ],
    )
    expect(rungs.map((r) => r.price)).toEqual([477])
    expect(dropped).toBe(1)
  })

  it('dedupes roles that differ only in case', () => {
    const { rungs } = buildLadder(
      100,
      [
        {
          kind: 'put_wall',
          label: 'Put wall',
          price: 90,
          distPct: -10,
          meaning: '',
          side: 'below',
        },
      ],
      [
        {
          id: 'pw',
          label: 'Put Wall',
          price: 90,
          pull: 20,
          distancePct: -10,
          role: '',
          lensCount: 1,
          lenses: [],
          side: 'below',
          isPrimary: false,
        },
      ],
    )
    expect(rungs[0].roles).toEqual(['Put Wall'])
  })
})
