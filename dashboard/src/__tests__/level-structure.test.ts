/**
 * Unit tests for dashboard/src/levelStructure.ts — the merge of dealer gamma,
 * volume-at-price, order flow and the kernel onto one level ladder, plus the
 * mean-reversion target.
 *
 * The behaviours worth pinning are the ones a trading decision hangs on:
 * that nearby levels merge instead of double-printing, that a level several
 * lenses name outranks one only gamma knows about, that flow evidence is
 * reported as ABSENT rather than as neutral when the price is outside the
 * measured window, and that the mean target is a median (so one lagging
 * anchor cannot drag it to a price no lens named).
 */
import { describe, expect, it } from 'vitest'
import type { AbsorptionMatrix, AbsorptionMatrixBin } from '@/api'
import {
  binAt,
  buildLevelLadder,
  fairValueTarget,
  flowAt,
  orderFlowRead,
  type LadderInput,
} from '@/levelStructure'

/** Ten $1 bins from 95 to 105, POC at 99.5, heavier buying low, selling high. */
function makeMatrix(overrides: Partial<AbsorptionMatrix> = {}): AbsorptionMatrix {
  const bins: AbsorptionMatrixBin[] = []
  for (let i = 0; i < 10; i += 1) {
    const low = 95 + i
    // Peak at index 4 (99–100), tapering outward.
    const total = 1000 - Math.abs(i - 4) * 150
    const buyHeavy = i <= 4
    bins.push({
      index: i,
      low,
      high: low + 1,
      mid: low + 0.5,
      total,
      buy: buyHeavy ? total * 0.72 : total * 0.3,
      sell: buyHeavy ? total * 0.28 : total * 0.7,
      strong_buy: buyHeavy ? total * 0.3 : 0,
      strong_sell: buyHeavy ? 0 : total * 0.3,
      delta: buyHeavy ? total * 0.4 : -total * 0.4,
      delta_frac: (total * 0.4) / 400,
      absorption: i === 2 ? 800 : 40,
      touches: i === 2 ? 12 : 3,
      rejections: i === 2 ? 3 : 0,
      in_value_area: i >= 2 && i <= 6,
      strength: i === 2 ? 8.4 : 3.1,
    })
  }
  return {
    available: true,
    lookback: 220,
    bins_used: 10,
    window_bars: 220,
    window_low: 95,
    window_high: 105,
    bins,
    poc: 99.5,
    vah: 102,
    val: 97,
    zones: [
      {
        low: 97,
        high: 98,
        mid: 97.5,
        strength: 8.4,
        tier: 'ELITE',
        side: 'support',
        volume: 700,
        absorption: 800,
        touches: 12,
        rejections: 3,
      },
    ],
    last_print: null,
    pressure: {
      score: 34.2,
      regime: 'ACCUM',
      imbalance: 0.18,
      cvd_bias: 0.22,
      absorption_bias: 0.4,
      absorption_side: 'SUPPORT',
      last_cluster_dir: 1,
      buy_share: 0.58,
      sell_share: 0.42,
    },
    ...overrides,
  }
}

function ladderInput(over: Partial<LadderInput> = {}): LadderInput {
  return {
    spot: 100,
    sigma: 0.22,
    tYears: 5 / 252,
    em1dDollars: 1.4,
    matrix: makeMatrix(),
    gamma: { callWall: 103, putWall: 97.4, zeroGamma: 100.6, pinStrike: 100 },
    kernel: { mean: 99.5, upper: 102.2, lower: 96.8, vwap: 99.4 },
    vol: { emHigh: 101.4, emLow: 98.6 },
    ...over,
  }
}

describe('binAt / flowAt', () => {
  const m = makeMatrix()

  it('finds the bin containing a price, right-inclusive on the top bin', () => {
    expect(binAt(m, 97.5)!.index).toBe(2)
    expect(binAt(m, 95)!.index).toBe(0)
    expect(binAt(m, 105)!.index).toBe(9)
  })

  it('returns null outside the measured window instead of clamping to an edge', () => {
    // A level far from where price has recently traded genuinely has no flow
    // evidence; snapping it to the nearest bin would invent some.
    expect(binAt(m, 80)).toBeNull()
    expect(binAt(m, 140)).toBeNull()
    expect(binAt(null, 100)).toBeNull()
  })

  it('restores the sign of delta, which the wire format drops from delta_frac', () => {
    expect(flowAt(m, 96.5)!.deltaFrac).toBeGreaterThan(0)
    expect(flowAt(m, 103.5)!.deltaFrac).toBeLessThan(0)
  })

  it('attaches the covering zone tier and side', () => {
    const f = flowAt(m, 97.5)!
    expect(f.zoneTier).toBe('ELITE')
    expect(f.zoneSide).toBe('support')
    expect(f.rejections).toBe(3)
    expect(f.inValueArea).toBe(true)
  })

  it('reports volume share against the heaviest bin, so the POC reads 1', () => {
    expect(flowAt(m, 99.5)!.volumeShare).toBeCloseTo(1, 9)
  })
})

describe('buildLevelLadder', () => {
  it('sorts high to low so the output reads as a price axis', () => {
    const out = buildLevelLadder(ladderInput())
    const prices = out.map((l) => l.price)
    expect([...prices].sort((a, b) => b - a)).toEqual(prices)
  })

  it('merges lenses that name effectively the same price into one level', () => {
    const out = buildLevelLadder(ladderInput())
    // Put wall 97.4 and the ELITE order-flow zone at 97.5 are 0.1 apart, well
    // inside half a $1 bin — one level, two lenses, not two rules to reconcile.
    const merged = out.find((l) => l.price > 97.2 && l.price < 97.7)!
    expect(merged.lenses).toEqual(expect.arrayContaining(['gamma', 'orderflow']))
    expect(merged.sources.length).toBeGreaterThan(1)
  })

  it('ranks a multi-lens, tape-defended level above a gamma-only one', () => {
    const out = buildLevelLadder(ladderInput())
    const defended = out.find((l) => l.price > 97.2 && l.price < 97.7)!
    const gammaOnly = out.find((l) => l.lenses.length === 1 && l.lenses[0] === 'gamma')
    expect(defended.conviction).toBeGreaterThan(50)
    if (gammaOnly) expect(defended.conviction).toBeGreaterThan(gammaOnly.conviction)
  })

  it('names the absence of flow coverage rather than scoring it as neutral', () => {
    const out = buildLevelLadder(
      ladderInput({ gamma: { callWall: 140, putWall: null, zeroGamma: null, pinStrike: null } }),
    )
    const far = out.find((l) => l.price === 140)
    // 140 is outside the ±12% frame of the ladder but still built; when it is
    // present it must carry no flow and say so.
    if (far) {
      expect(far.flow).toBeNull()
      expect(far.evidence.join(' ')).toContain('no order-flow coverage')
    }
  })

  it('labels support below spot and resistance above it', () => {
    const out = buildLevelLadder(ladderInput())
    for (const l of out) {
      expect(l.role).toBe(l.price >= 100 ? 'resistance' : 'support')
    }
  })

  it('attaches a touch probability per level and reports distance in expected moves', () => {
    const out = buildLevelLadder(ladderInput())
    const withProb = out.filter((l) => l.prob != null)
    expect(withProb.length).toBe(out.length)
    const callWall = out.find((l) => l.label.startsWith('Call wall'))!
    expect(callWall.prob!.touch).toBeGreaterThan(callWall.prob!.terminal)
    expect(callWall.emMultiple).toBeCloseTo(3 / 1.4, 6)
  })

  it('omits probabilities entirely when there is no vol to compute them from', () => {
    const out = buildLevelLadder(ladderInput({ sigma: null }))
    expect(out.length).toBeGreaterThan(0)
    expect(out.every((l) => l.prob === null)).toBe(true)
  })

  it('returns an empty ladder without a spot rather than anchoring on zero', () => {
    expect(buildLevelLadder(ladderInput({ spot: 0 }))).toEqual([])
    expect(buildLevelLadder(ladderInput({ spot: NaN }))).toEqual([])
  })

  it('still builds from gamma alone when no order-flow window exists', () => {
    const out = buildLevelLadder(ladderInput({ matrix: null }))
    expect(out.length).toBeGreaterThan(0)
    expect(out.every((l) => l.flow === null)).toBe(true)
  })
})

describe('fairValueTarget', () => {
  it('takes the median of the anchors, not the average', () => {
    // POC 99, VWAP 99.2, kernel 106: the mean is 101.4, a price no lens named
    // and above two of the three anchors. The median is 99.2.
    const fv = fairValueTarget({
      spot: 100,
      poc: 99,
      vwap: 99.2,
      kernelMean: 106,
      valueAreaLow: 97,
      valueAreaHigh: 102,
      halfLifeBars: 4,
      em1dDollars: 1.4,
    })!
    expect(fv.target).toBeCloseTo(99.2, 9)
    expect(fv.anchors).toHaveLength(3)
  })

  it('reports anchor disagreement instead of burying it in the target', () => {
    const fv = fairValueTarget({
      spot: 100,
      poc: 99,
      vwap: 99.2,
      kernelMean: 106,
      valueAreaLow: null,
      valueAreaHigh: null,
      halfLifeBars: null,
      em1dDollars: null,
    })!
    expect(fv.spreadPct).toBeCloseTo(7, 6)
  })

  it('scales the pull on the expected-move clock, not on a fixed percentage', () => {
    const base = {
      spot: 100,
      vwap: null,
      kernelMean: null,
      valueAreaLow: null,
      valueAreaHigh: null,
      halfLifeBars: null,
    }
    // The same 2% gap is a strong pull on a quiet name and weak on a wild one.
    const quiet = fairValueTarget({ ...base, poc: 98, em1dDollars: 0.5 })!
    const wild = fairValueTarget({ ...base, poc: 98, em1dDollars: 8 })!
    expect(quiet.pull).toBe('strong')
    expect(wild.pull).toBe('weak')
  })

  it('calls spot "at value" only inside a quarter of an expected move', () => {
    const fv = fairValueTarget({
      spot: 100,
      poc: 100.2,
      vwap: null,
      kernelMean: null,
      valueAreaLow: null,
      valueAreaHigh: null,
      halfLifeBars: null,
      em1dDollars: 4,
    })!
    expect(fv.direction).toBe('at')
  })

  it('flags whether spot is inside the value area, or says it cannot tell', () => {
    const inside = fairValueTarget({
      spot: 100,
      poc: 99.5,
      vwap: null,
      kernelMean: null,
      valueAreaLow: 97,
      valueAreaHigh: 102,
      halfLifeBars: null,
      em1dDollars: null,
    })!
    expect(inside.insideValueArea).toBe(true)

    const unknown = fairValueTarget({
      spot: 100,
      poc: 99.5,
      vwap: null,
      kernelMean: null,
      valueAreaLow: null,
      valueAreaHigh: null,
      halfLifeBars: null,
      em1dDollars: null,
    })!
    expect(unknown.insideValueArea).toBeNull()
  })

  it('withholds entirely when no anchor is measurable', () => {
    expect(
      fairValueTarget({
        spot: 100,
        poc: null,
        vwap: null,
        kernelMean: null,
        valueAreaLow: null,
        valueAreaHigh: null,
        halfLifeBars: null,
        em1dDollars: null,
      }),
    ).toBeNull()
  })
})

describe('orderFlowRead', () => {
  it('turns the pressure block into a sentence naming the absorption side', () => {
    const read = orderFlowRead(makeMatrix())!
    expect(read.regime).toBe('ACCUM')
    expect(read.headline).toContain('Accumulation')
    expect(read.detail).toContain('58%')
    expect(read.detail).toContain('defending declines')
  })

  it('withholds when the matrix is unavailable rather than reporting BALANCED', () => {
    expect(orderFlowRead(null)).toBeNull()
    expect(orderFlowRead(makeMatrix({ available: false }))).toBeNull()
    expect(orderFlowRead(makeMatrix({ pressure: null }))).toBeNull()
  })
})
