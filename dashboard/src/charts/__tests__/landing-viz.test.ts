import { describe, expect, it } from 'vitest'
import {
  bsCall,
  bsThetaDay,
  greekCurves,
  icDecayModel,
  legExpiryValue,
  payoffColumns,
  structuralGexProfile,
  structureGreeks,
  type GreekKind,
} from '../landing-viz'

/**
 * The landing-page model lab plots these curves inside a fixed viewBox whose
 * x axis is the strike range mapped onto [0, 100]. A regression here is
 * invisible in unit-free maths but renders the lab as an empty plot, so the
 * axis contract is pinned explicitly.
 */
const KINDS: GreekKind[] = ['value', 'delta', 'gamma', 'vega', 'theta']

const S = 100
const T = 30 / 365
const SIGMA = 0.3
const R = 0.05
const Q = 0
const K_LOW = 60
const K_HIGH = 140
const N = 121

describe('greekCurves', () => {
  it.each(KINDS)('maps the %s curve onto the full [0, 100] strike axis', (kind) => {
    const { call, put } = greekCurves(kind, S, T, SIGMA, R, Q, K_LOW, K_HIGH, N)

    for (const series of [call, put]) {
      expect(series).toHaveLength(N)
      expect(series[0]!.x).toBeCloseTo(0)
      expect(series[series.length - 1]!.x).toBeCloseTo(100)
      for (const p of series) {
        expect(p.x).toBeGreaterThanOrEqual(0)
        expect(p.x).toBeLessThanOrEqual(100)
        expect(Number.isFinite(p.y)).toBe(true)
        expect(Math.abs(p.y)).toBeLessThanOrEqual(1 + 1e-9)
      }
    }
  })

  it('spaces strikes evenly and keeps x monotonically increasing', () => {
    const { call, strikes } = greekCurves('value', S, T, SIGMA, R, Q, K_LOW, K_HIGH, N)

    expect(strikes[0]).toBeCloseTo(K_LOW)
    expect(strikes[strikes.length - 1]).toBeCloseTo(K_HIGH)
    for (let i = 1; i < call.length; i++) {
      expect(call[i]!.x).toBeGreaterThan(call[i - 1]!.x)
    }
    // Midpoint strike lands at the midpoint of the axis.
    expect(call[(N - 1) / 2]!.x).toBeCloseTo(50)
  })

  it('normalises call and put against one shared scale so at least one curve peaks at ±1', () => {
    const { call, put } = greekCurves('value', S, T, SIGMA, R, Q, K_LOW, K_HIGH, N)
    const peak = Math.max(...[...call, ...put].map((p) => Math.abs(p.y)))
    expect(peak).toBeCloseTo(1)
  })

  it.each(KINDS)(
    'uses the FULL band for %s: a point at +1 and a point at the bottom edge',
    (kind) => {
      // A symmetric maxAbs scale left non-negative Greeks (value/gamma/vega)
      // floating in the top half and theta in the bottom half, rendering half
      // the plot as dead space. Domain normalisation pins both band edges.
      const { call, put } = greekCurves(kind, S, T, SIGMA, R, Q, K_LOW, K_HIGH, N)
      const ys = [...call, ...put].map((p) => p.y)
      expect(Math.max(...ys)).toBeCloseTo(1)
      // All kinds touch -1 exactly except value, whose domain floor is 0 (for
      // the payoff boundary) while the cheapest option still costs ~$0.27.
      if (kind === 'value') expect(Math.min(...ys)).toBeLessThanOrEqual(-0.9)
      else expect(Math.min(...ys)).toBeCloseTo(-1)
    },
  )

  it('reports its domain, and the value domain reaches 0 for the payoff boundary', () => {
    const { domain } = greekCurves('value', S, T, SIGMA, R, Q, K_LOW, K_HIGH, N)
    expect(domain.lo).toBe(0)
    // Domain top is the deep-ITM call value at K=60 (~$40.2): the ATM $3.63
    // value sits mid-band instead of hugging the frame edge.
    expect(domain.hi).toBeGreaterThan(30)
  })
})

describe('bsThetaDay', () => {
  const AT_ATM = { S: 100, K: 100, T: 30 / 365, sigma: 0.3, r: 0.05, q: 0 }

  it('keeps both ATM legs negative and the call the deeper decay at r>0, q=0', () => {
    const call = bsThetaDay(AT_ATM, 'call')
    const put = bsThetaDay(AT_ATM, 'put')
    expect(call).toBeLessThan(0)
    expect(put).toBeLessThan(0)
    // ATM: call −0.064/d, put −0.050/d — the put is shallower.
    expect(call).toBeCloseTo(-0.064, 3)
    expect(put).toBeCloseTo(-0.05, 3)
  })

  it('satisfies the carry identity theta_put − theta_call = rK·e^{−rT}/365 at q=0', () => {
    // Hull: the legs differ only by the strike-carry term. A sign slip on
    // either rK term (which once handed deep-ITM calls positive theta)
    // breaks this identity immediately.
    const deepItmCall = bsThetaDay({ ...AT_ATM, K: 60 }, 'call')
    expect(deepItmCall).toBeLessThan(0)
    for (const K of [60, 80, 100, 120, 140]) {
      const call = bsThetaDay({ ...AT_ATM, K }, 'call')
      const put = bsThetaDay({ ...AT_ATM, K }, 'put')
      expect(put - call).toBeCloseTo((0.05 * K * Math.exp(-0.05 * AT_ATM.T)) / 365, 6)
    }
  })
})

/* ── Multi-leg structures (PayoffPlate) ───────────────────────────────────── */

describe('structureGreeks / payoffColumns', () => {
  const ENV = { S: 100, T: 45 / 365, sigma: 0.3, r: 0.05, q: 0 }
  const LONG_CALL = [{ kind: 'call' as const, strike: 100, dir: 1 as const }]
  const BULL_CALL = [
    { kind: 'call' as const, strike: 100, dir: 1 as const },
    { kind: 'call' as const, strike: 115, dir: -1 as const },
  ]
  const IRON_FLY = [
    { kind: 'put' as const, strike: 90, dir: 1 as const },
    { kind: 'put' as const, strike: 100, dir: -1 as const },
    { kind: 'call' as const, strike: 100, dir: -1 as const },
    { kind: 'call' as const, strike: 110, dir: 1 as const },
  ]

  it('a one-leg structure is exactly the single-contract Greeks', () => {
    const g = structureGreeks(LONG_CALL, ENV)
    expect(g.value).toBeCloseTo(bsCall({ ...ENV, K: 100 }), 8)
    expect(g.delta).toBeCloseTo(Math.exp(-ENV.q * ENV.T) * 0.5443, 3) // ATM call Δ ≈ 0.54
    expect(g.gamma).toBeGreaterThan(0)
    expect(g.thetaDay).toBeLessThan(0)
  })

  it('flipping the direction negates every Greek', () => {
    const long = structureGreeks(LONG_CALL, ENV)
    const short = structureGreeks([{ ...LONG_CALL[0]!, dir: -1 as const }], ENV)
    for (const k of ['value', 'delta', 'gamma', 'vega', 'thetaDay'] as const) {
      expect(short[k]).toBeCloseTo(-long[k], 10)
    }
  })

  it('caps a bull call spread at width − debit, in both value and expiry P&L', () => {
    const g = structureGreeks(BULL_CALL, ENV)
    const debit = g.value
    expect(debit).toBeGreaterThan(0)
    expect(debit).toBeLessThan(15) // cheaper than the spread width
    const cols = payoffColumns(BULL_CALL, ENV, 70, 130, 81)
    expect(Math.max(...cols.expiry)).toBeCloseTo(15 - debit, 2)
    expect(Math.min(...cols.expiry)).toBeCloseTo(-debit, 2)
    // Deep ITM: today's value approaches the expiry cap from below.
    expect(cols.today[cols.today.length - 1]!).toBeLessThanOrEqual(15 - debit + 0.05)
  })

  it('peaks the iron fly at the short strikes — short the body means net credit', () => {
    const g = structureGreeks(IRON_FLY, ENV)
    expect(g.value).toBeLessThan(0) // short the straddle, collect the credit
    // Near delta-neutral, not exactly: the call/put carry asymmetry at r=5%
    // leaves a small residual on the short straddle.
    expect(Math.abs(g.delta)).toBeLessThan(0.12)
    expect(g.gamma).toBeLessThan(0) // short the ATM straddle
    expect(g.thetaDay).toBeGreaterThan(0) // short premium collects decay
    const leg100P = legExpiryValue({ kind: 'put', strike: 100, dir: -1 }, 100)
    expect(leg100P).toBeCloseTo(0, 8)
  })

  it('keeps the premium consistent between greeks and columns', () => {
    const g = structureGreeks(BULL_CALL, ENV)
    const cols = payoffColumns(BULL_CALL, ENV, 70, 130, 81)
    expect(cols.premium).toBeCloseTo(g.value, 10)
  })
})

/* ── Walk-forward IC decay model (IcDecayPlate) ────────────────────────────── */

describe('icDecayModel', () => {
  const MODEL = icDecayModel({
    ic1d: 0.004,
    icSdDaily: 0.085,
    periods1d: 491,
    shape: [1.0, 1.18, 1.6, 1.28, 0.05, -0.25],
  })

  it('derives every row cell from the stated formulas — no painted numbers', () => {
    for (const [i, row] of MODEL.rows.entries()) {
      const shape = [1.0, 1.18, 1.6, 1.28, 0.05, -0.25][i]!
      expect(row.meanIc).toBeCloseTo(0.004 * shape, 10)
      expect(row.periods).toBe(491 - row.days)
      const se = 0.085 / Math.sqrt(row.periods)
      expect(row.nwT).toBeCloseTo(row.meanIc / se, 8)
      expect(row.icIr).toBeCloseTo(row.nwT * Math.sqrt(252 / row.days), 8)
      expect(row.pctPositive).toBeGreaterThanOrEqual(0)
      expect(row.pctPositive).toBeLessThanOrEqual(1)
    }
  })

  it('peaks at the modelled 3D crest and decays through half-peak between 5D and 10D', () => {
    expect(MODEL.peakDays).toBe(3)
    expect(MODEL.halfLifeDays).toBeGreaterThan(5)
    expect(MODEL.halfLifeDays).toBeLessThan(10)
  })

  it('counts sign persistence strictly — the flipped 20D horizon does not count', () => {
    expect(MODEL.signPersistence).toBeCloseTo(5 / 6, 8)
  })
})

/* ── Structural GEX profile (DeskTelemetryPlate) ───────────────────────────── */

describe('structuralGexProfile', () => {
  const PROFILE = structuralGexProfile({
    S: 100,
    flipK: 88,
    callWallK: 110,
    putWallK: 92,
    nStrikes: 25,
    range: 0.24,
  })

  it('normalises gex to ±1', () => {
    const abs = PROFILE.points.map((p) => Math.abs(p.gex))
    expect(Math.max(...abs)).toBeCloseTo(1, 10)
    for (const a of abs) {
      expect(a).toBeLessThanOrEqual(1 + 1e-9)
    }
  })

  it('puts the call wall on the positive side and the put wall on the negative side', () => {
    const atK = (target: number) =>
      PROFILE.points.reduce((best, p) =>
        Math.abs(p.K - target) < Math.abs(best.K - target) ? p : best,
      )
    expect(atK(110).gex).toBeGreaterThan(0.5)
    expect(atK(92).gex).toBeLessThan(0)
    // Call wall dominates in this parametrisation → net long gamma.
    expect(PROFILE.net).toBeGreaterThan(0)
  })

  it('the ambient field signs on the flip: far-left bar negative, far-right positive', () => {
    // K=76 (far below the 88 flip) rides the put-side ambient; K=124 (far
    // above) rides the call-side. The put wall itself sits above the flip —
    // the flip marks the ambient sign change, not the wall placement.
    expect(PROFILE.points[0]!.gex).toBeLessThan(0)
    expect(PROFILE.points[PROFILE.points.length - 1]!.gex).toBeGreaterThan(0)
  })
})
