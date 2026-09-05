/**
 * One surface, one number per concept.
 *
 * The regime page rendered the same quantity from two independent sources side
 * by side: the ladder, map and briefing read the canonical `regimeRead` while
 * the Greeks and topography cards read the microstructure snapshot directly.
 * The page printed two gamma flips, two spot prices, two "net dealer gamma"
 * figures and three regime verdicts, all at once, with nothing telling the
 * operator which to believe. These tests pin the consistency rules that
 * replaced that.
 */
import { describe, it, expect } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import DealerGammaMap from '../components/DealerGammaMap.vue'
import DealerGreeksFlowCard from '../components/DealerGreeksFlowCard.vue'
import CausalEnvelopeChart from '../components/CausalEnvelopeChart.vue'
import { buildLevelLadder, fairValueTarget } from '../levelStructure'
import type {
  ChainQuality,
  ExecutionSignal,
  GexProfilePoint,
  MicrostructureRegimeSnapshot,
  StateEstimationPoint,
  StrikeExposure,
  TopographyState,
} from '@/microstructureContracts'

const okQuality: ChainQuality = {
  measurable: true,
  contracts: 300,
  strikes: 40,
  total_open_interest: 900_000,
  iv_fallback_contracts: 0,
  flip_located: true,
  dealer_convention: 'index',
  reason: null,
}

/** Net gamma crosses zero just above spot, so spot sits short-gamma but only
 *  barely — the exact configuration that made the map and the briefing
 *  disagree. */
function profile(): GexProfilePoint[] {
  const out: GexProfilePoint[] = []
  for (let i = 0; i < 40; i++) {
    const s = 750 + i
    out.push({ spot: s, net_gex_m: (s - 770.33) * 300 })
  }
  return out
}

function strikes(): StrikeExposure[] {
  return [760, 765, 770, 775].map((k) => ({
    strike: k,
    call_oi: 5000,
    put_oi: 6000,
    call_volume: 100,
    put_volume: 120,
    call_iv: 0.2,
    put_iv: 0.22,
    call_gamma: 0.01,
    put_gamma: 0.01,
    call_gex_m: 40,
    put_gex_m: -35,
    net_gex_m: 5,
    call_vex_m: 1,
    put_vex_m: -1,
    net_vex_m: 0,
    call_chex_m: 0.5,
    put_chex_m: -0.4,
    net_chex_m: 0.1,
    speed_m: 0.2,
    zomma_m: 0.1,
  }))
}

const topography: TopographyState = {
  quadrant: 'forward_negative_slide',
  title: 'Forward Negative Slide',
  description: 'Deep negative GEX below spot.',
  dealer_hedging_action: 'Downward spot motion forces dealer short-selling.',
  expected_market_behavior: 'Directional breakdown cascades.',
  gex_above_spot_m: 304.9,
  gex_below_spot_m: -929.8,
  gex_ratio: 0.33,
  call_wall: 770,
  put_wall: 760,
  gamma_flip: 770.47,
  volatility_trigger: 770,
  absolute_gamma_peak: 769,
}

/** A snapshot whose own level solve sits a few cents off the canonical read —
 *  the real SPY case that printed 770.47 next to 770.33. */
function snapshot(): MicrostructureRegimeSnapshot {
  return {
    symbol: 'SPY',
    spot: 765.72,
    asof: '2026-08-30T17:53:01Z',
    regime: 'negative_gamma',
    regime_strength: 0.4,
    net_gex_m: -624.93,
    call_gex_m: 2416.4,
    put_gex_m: -3041.3,
    net_gex_profile_m: -373.1,
    net_vex_m: 68.98,
    net_chex_m: 205.94,
    hedging_flow_m: null,
    zero_dte_charm_drift_m: 290.38,
    gamma_flip: 770.47,
    call_wall: 770,
    put_wall: 760,
    volatility_trigger: 770,
    absolute_gamma_peak: 769,
    quality: okQuality,
    topography,
    strikes: strikes(),
    gex_profile: profile(),
    notes: [],
  }
}

async function renderMap(overrides: Record<string, unknown> = {}): Promise<string> {
  const app = createSSRApp({
    render: () =>
      h(DealerGammaMap, {
        profile: profile(),
        strikes: strikes(),
        quality: okQuality,
        spot: 769.3,
        zeroGamma: 770.33,
        callWall: 770,
        putWall: 760,
        pinStrike: 760,
        ...overrides,
      }),
  })
  return renderToString(app)
}

async function renderGreeks(overrides: Record<string, unknown> = {}): Promise<string> {
  const app = createSSRApp({
    render: () =>
      h(DealerGreeksFlowCard, {
        snapshot: snapshot(),
        spot: 769.3,
        gammaFlip: 770.33,
        callWall: 770,
        putWall: 760,
        pinStrike: 760,
        netGammaAtSpotM: -373.1,
        ...overrides,
      }),
  })
  return renderToString(app)
}

describe('gamma map regime badge', () => {
  it('reports the page regime call, not the bare sign of net gamma', async () => {
    // Net gamma at spot is negative here. Classified on sign alone the map said
    // SHORT GAMMA while the briefing, which applies a neutral band around the
    // flip, said the regime was undecided.
    const html = await renderMap({ regime: 'flip' })
    expect(html).toContain('AT THE FLIP')
    expect(html).not.toContain('SHORT GAMMA GAMMA')
    expect(html).toMatch(/AT THE FLIP/)
  })

  it('still reads the sign when no canonical call is supplied', async () => {
    const html = await renderMap({ regime: null })
    expect(html).toContain('SHORT GAMMA')
  })

  it('follows the canonical call when it is a side', async () => {
    const html = await renderMap({ regime: 'long' })
    expect(html).toContain('LONG GAMMA')
  })
})

describe('dealer greeks card', () => {
  it('prints the canonical flip, not the snapshot’s own solve', async () => {
    const html = await renderGreeks()
    expect(html).toContain('770.33')
  })

  it('names the snapshot’s disagreement instead of hiding it', async () => {
    const html = await renderGreeks()
    expect(html).toContain('Chain snapshot solves these differently')
    expect(html).toContain('770.47')
  })

  it('stays silent when the two sources agree', async () => {
    const agreed = snapshot()
    agreed.gamma_flip = 770.33
    agreed.absolute_gamma_peak = 760
    const html = await renderGreeks({ snapshot: agreed })
    expect(html).not.toContain('Chain snapshot solves these differently')
  })

  it('flags the pin when the two pipelines pick different max-|GEX| strikes', async () => {
    // Both pipelines define this level identically -- the strike with the
    // largest |net GEX| -- and returned 760 and 769 for the same chain.
    const html = await renderGreeks()
    expect(html).toContain('gamma peak $769.00')
  })

  it('never prints the withheld note over a populated card', async () => {
    // The divergence and notes paragraphs sit between the metrics row and the
    // withheld note; as a `v-else-if` the latter bound to the wrong branch.
    const html = await renderGreeks()
    expect(html).not.toContain('Dealer Greeks withheld')
  })

  it('still withholds when the chain is unmeasurable', async () => {
    const dead = snapshot()
    dead.quality = { ...okQuality, measurable: false, reason: 'no open interest observed' }
    const html = await renderGreeks({ snapshot: dead })
    expect(html).toContain('Dealer Greeks withheld')
    expect(html).toContain('no open interest observed')
    expect(html).not.toContain('NET GEX · CHAIN TOTAL')
  })

  it('labels the chain total and the at-spot read as different measurements', async () => {
    const html = await renderGreeks()
    expect(html).toContain('NET GEX · CHAIN TOTAL')
    expect(html).toContain('At spot (map curve)')
    expect(html).toContain('-373.10M')
  })

  it('surfaces snapshot notes rather than dropping them', async () => {
    const noted = snapshot()
    noted.notes = ['profile and strike-sum net gamma differ by 40%']
    const html = await renderGreeks({ snapshot: noted })
    expect(html).toContain('differ by 40%')
  })

  it('falls back to the snapshot when no canonical level is supplied', async () => {
    const html = await renderGreeks({ gammaFlip: null })
    expect(html).toContain('770.47')
  })
})

describe('merged levels', () => {
  it('exposes each lens’s own price, not just the cluster centroid', () => {
    // Call wall 770.00 and flip 770.33 merge; the centroid is 770.17, which is
    // neither level. Labelled "Call wall +1" it read as a call wall at 770.17.
    const ladder = buildLevelLadder({
      spot: 769.3,
      sigma: null,
      tYears: null,
      em1dDollars: null,
      matrix: null,
      gamma: { callWall: 770, putWall: 700, zeroGamma: 770.33, pinStrike: null },
      kernel: { mean: null, upper: null, lower: null, vwap: null },
      vol: { emHigh: null, emLow: null },
    })
    const merged = ladder.find((l) => l.members.length > 1)
    expect(merged).toBeDefined()
    const prices = merged!.members.map((m) => m.price).sort((a, b) => a - b)
    expect(prices).toContain(770)
    expect(prices).toContain(770.33)
    expect(merged!.spread).toBeCloseTo(0.33, 5)
  })

  it('reports a zero spread for a level only one lens named', () => {
    const ladder = buildLevelLadder({
      spot: 769.3,
      sigma: null,
      tYears: null,
      em1dDollars: null,
      matrix: null,
      gamma: { callWall: 790, putWall: null, zeroGamma: null, pinStrike: null },
      kernel: { mean: null, upper: null, lower: null, vwap: null },
      vol: { emHigh: null, emLow: null },
    })
    expect(ladder).toHaveLength(1)
    expect(ladder[0].members).toHaveLength(1)
    expect(ladder[0].spread).toBe(0)
    expect(ladder[0].price).toBe(790)
  })
})

describe('fair value', () => {
  const base = {
    spot: 769.3,
    valueAreaLow: null,
    valueAreaHigh: null,
    halfLifeBars: 8,
    em1dDollars: 3.25,
  }

  it('flags anchors that disagree by more than two expected moves', () => {
    // The observed SPY case: a year-long volume POC at 680, VWAP at 748 and the
    // kernel mean at 768 produced a confident "pull DOWN to 748.33".
    const fv = fairValueTarget({ ...base, poc: 680.76, vwap: 748.33, kernelMean: 768.17 })
    expect(fv).not.toBeNull()
    expect(fv!.dispersed).toBe(true)
    expect(fv!.zone.low).toBeCloseTo(680.76, 5)
    expect(fv!.zone.high).toBeCloseTo(768.17, 5)
  })

  it('keeps a point target when the anchors actually agree', () => {
    const fv = fairValueTarget({ ...base, poc: 768.0, vwap: 768.4, kernelMean: 768.2 })
    expect(fv!.dispersed).toBe(false)
    expect(fv!.target).toBeCloseTo(768.2, 5)
  })

  it('falls back to a percentage spread when no expected move is measurable', () => {
    const fv = fairValueTarget({
      ...base,
      em1dDollars: null,
      poc: 680.76,
      vwap: 748.33,
      kernelMean: 768.17,
    })
    expect(fv!.dispersed).toBe(true)
  })
})

describe('causal envelope chart', () => {
  function points(n: number): StateEstimationPoint[] {
    return Array.from({ length: n }, (_, i) => ({
      t: `2026-0${1 + Math.floor(i / 30)}-${String((i % 28) + 1).padStart(2, '0')}`,
      price: 700 + i,
      nw_mean: 700 + i,
      nw_upper: 710 + i,
      nw_lower: 690 + i,
      nw_sigma: 5,
      nw_bandwidth: 20,
      ou_half_life: 8,
      kalman_price: 700 + i,
      kalman_velocity: 0.7,
      kalman_zscore: 0.4,
      kalman_q: 2e-6,
      innovation_var: 1,
      exhaustion: false,
      breakout: false,
    }))
  }

  function signal(barIndex: number): ExecutionSignal {
    return {
      bar_index: barIndex,
      timestamp: '2026-03-30T00:00:00Z',
      symbol: 'SPY',
      action: 'ENTER_SHORT',
      direction: 'short',
      price: 630.35,
      regime: 'negative_gamma',
      topography_quadrant: 'forward_negative_slide',
      setup_name: 'Kinematic_LowerBreak_Cascade',
      conviction: 0.82,
      suggested_size_pct: 2,
      entry_price: 630.35,
      stop_loss: 652.37,
      take_profit: 586.3,
      invalidation_anchor: 'kernel',
      kalman_velocity: -0.5,
      kalman_zscore: -1.8,
      kernel_mean: 640,
      upper_envelope: 660,
      lower_envelope: 620,
      anchored_vwap: 645,
      call_wall: null,
      put_wall: null,
      gamma_flip: null,
      notes: [],
    }
  }

  async function renderChart(sigBar: number): Promise<string> {
    const app = createSSRApp({
      render: () =>
        h(CausalEnvelopeChart, {
          points: points(120),
          signals: [signal(sigBar)],
          callWall: 770,
          putWall: 760,
          gammaFlip: 770.33,
          liveSpot: 769.3,
        }),
    })
    return renderToString(app)
  }

  it('does not project a stale setup’s target and stop', async () => {
    // A 2026-03-30 short's $586 target was being drawn across a chart trading
    // at $766, indistinguishable from a live plan.
    const html = await renderChart(20)
    expect(html).not.toContain('TARGET')
    expect(html).not.toContain('STOP')
    expect(html).toContain('is stale')
  })

  it('projects a setup that is still current', async () => {
    const html = await renderChart(118)
    expect(html).toContain('TARGET')
    expect(html).toContain('STOP')
    expect(html).not.toContain('is stale')
  })

  it('names the bar close as a bar close and shows live spot beside it', async () => {
    // The HUD's price is a bar close off a series that can be days behind the
    // tape; printed as "SPOT PRICE" it read as a second, contradictory quote.
    const html = await renderChart(118)
    expect(html).toContain('BAR CLOSE')
    expect(html).toContain('LIVE SPOT')
    expect(html).not.toContain('SPOT PRICE')
  })

  it('omits the live-spot tile when the quote matches the last bar', async () => {
    const pts = points(120)
    const app = createSSRApp({
      render: () =>
        h(CausalEnvelopeChart, {
          points: pts,
          signals: [],
          liveSpot: pts[pts.length - 1].price,
        }),
    })
    const html = await renderToString(app)
    expect(html).toContain('BAR CLOSE')
    expect(html).not.toContain('LIVE SPOT')
  })
})
