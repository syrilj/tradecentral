/**
 * DealerGammaMap — the surface the regime page's conclusions are read off.
 *
 * This component did not exist. The server had been shipping `gex_profile`
 * (50 full chain revaluations per poll) and `strikes` in the microstructure
 * payload since the engine landed, and no component in the app referenced
 * either field — so the page asserted a flip price and two wall prices with no
 * way to see the curve behind them. These tests cover the two things that make
 * the map trustworthy rather than decorative: it withholds when there is no
 * chain, and its zero line is where net gamma is actually zero.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import DealerGammaMap from '../components/DealerGammaMap.vue'
import type { ChainQuality, GexProfilePoint, StrikeExposure } from '@/microstructureContracts'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = readFileSync(join(root, 'components', 'DealerGammaMap.vue'), 'utf8')

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

/** A profile that crosses zero once, just below spot. */
function profile(): GexProfilePoint[] {
  const out: GexProfilePoint[] = []
  for (let i = 0; i < 40; i++) {
    const s = 480 + i
    out.push({ spot: s, net_gex_m: (s - 497) * 12 })
  }
  return out
}

function strikes(): StrikeExposure[] {
  return [490, 495, 500, 505, 510].map((k) => ({
    strike: k,
    call_oi: 5000,
    put_oi: 6000,
    call_volume: 100,
    put_volume: 120,
    call_iv: 0.2,
    put_iv: 0.22,
    call_gamma: 0.01,
    put_gamma: 0.01,
    call_gex_m: 40 - Math.abs(k - 500),
    put_gex_m: -(35 - Math.abs(k - 500)),
    net_gex_m: 5,
    call_vex_m: 1,
    put_vex_m: -1,
    net_vex_m: 0,
    call_chex_m: 0.5,
    put_chex_m: -0.4,
    net_chex_m: 0.1,
    speed_m: 0.2,
    zomma_m: 0.1,
    call_dex_m: 0,
    put_dex_m: 0,
    net_dex_m: 0,
  }))
}

async function render(overrides: Record<string, unknown> = {}): Promise<string> {
  const app = createSSRApp({
    render: () =>
      h(DealerGammaMap, {
        profile: profile(),
        strikes: strikes(),
        quality: okQuality,
        spot: 500,
        zeroGamma: 497,
        callWall: 510,
        putWall: 490,
        pinStrike: 500,
        ...overrides,
      }),
  })
  return renderToString(app)
}

describe('DealerGammaMap withholds rather than drawing a flat line', () => {
  it('renders no chart at all when the chain is unmeasurable', async () => {
    const html = await render({
      quality: { ...okQuality, measurable: false, reason: "no option chain available for 'ZZZZ'" },
      profile: [],
      strikes: [],
    })
    expect(html).not.toContain('<svg')
    // The reason travels to the operator; "nothing plotted" without a cause
    // is indistinguishable from a loading state.
    expect(html).toContain('no option chain available')
  })

  it('withholds on a degenerate profile even when quality says measurable', async () => {
    // One point is not a curve. Drawing it as a line through the frame would
    // read as "gamma is flat here", which is a claim, not an absence of one.
    const html = await render({ profile: [{ spot: 500, net_gex_m: 40 }] })
    expect(html).not.toContain('<svg')
  })

  it('draws the curve, the strike ladder and the structural levels when measurable', async () => {
    const html = await render()
    expect(html).toContain('<svg')
    expect(html).toContain('curve-line')
    expect(html).toContain('gex-bar')
    // Flip / walls / pin each get a labelled rule spanning both lanes.
    expect(html).toContain('FLIP')
    expect(html).toContain('CALL W')
    expect(html).toContain('PUT W')
    // Live spot is a rule plus a price pill on the axis, not a text label —
    // assert the marker itself and the price it reports.
    expect(html).toContain('spot-line')
    expect(html).toContain('pill-spot')
  })

  it('ranks the structural levels instead of drawing four equal rules', async () => {
    // The whole point of the ranking: the operator should be able to read
    // "which level first" off the chart rather than sorting it themselves.
    const html = await render()
    expect(html).toContain('Levels by priority')
    // Nearest-and-heaviest wins rank 1. With spot at 500 the flip at 505 is
    // both closer and structurally weightier than either wall.
    const flipRow = html.indexOf('Zero gamma')
    const callRow = html.indexOf('Call wall')
    expect(flipRow).toBeGreaterThan(-1)
    expect(callRow).toBeGreaterThan(-1)
    expect(flipRow).toBeLessThan(callRow)
  })

  it('surfaces the default-IV contract count, so assumed Greeks are visible', async () => {
    const html = await render({ quality: { ...okQuality, iv_fallback_contracts: 12 } })
    expect(html).toContain('12 strike-sides on default IV')
  })

  it('says so when no flip exists rather than leaving the readout blank', async () => {
    const html = await render({ zeroGamma: null })
    expect(html).toContain('none in range')
  })
})

describe('DealerGammaMap source contracts', () => {
  it('forces the y domain to straddle zero', () => {
    // "Which side of zero am I on" is the entire question the curve lane
    // answers; a domain auto-scaled to the data's own min/max would place the
    // zero line at an arbitrary height, or off-frame entirely.
    expect(src).toContain('const lo = Math.min(0, ...ys)')
    expect(src).toContain('const hi = Math.max(0, ...ys)')
  })

  it("scales the ladder against the symbol's own peak, not a fixed $M constant", () => {
    // An index's per-strike gamma runs orders of magnitude above a single
    // name's; a fixed divisor saturates on one and vanishes on the other.
    expect(src).toContain('const ladderScaleM = computed(')
    expect(src).toContain('Math.abs(r.call_gex_m), Math.abs(r.put_gex_m)')
  })

  it('splits the curve at the exact zero crossing so the halves meet on the axis', () => {
    expect(src).toContain('const t = span === 0 ? 0 : (0 - prev.net_gex_m) / span')
  })

  it('lets structural levels widen the window back out to include themselves', () => {
    // A wall 9% away is more decision-relevant than the strikes either side of
    // spot; windowing it off the frame hides the level that matters most.
    const domainBlock = src.slice(src.indexOf('const priceDomain = computed'))
    expect(domainBlock.slice(0, 900)).toContain(
      'for (const v of [props.spot, props.zeroGamma, props.callWall, props.putWall, props.pinStrike])',
    )
  })
})
