/**
 * The two regime cards must withhold, not zero.
 *
 * `unmeasurable_regime_snapshot` on the server sets every Greek to 0.0 because
 * there was nothing to measure. Passed straight into these cards, those zeros
 * rendered as a complete, confident readout: "NET GEX +0.00M · Net Market
 * Inflow (Dealers absorb supply)" beside "$—" structural levels. An operator
 * glancing at that sees a balanced market, not an absent one — which is the
 * single most expensive confusion this surface can cause, and the reason the
 * server started shipping `quality.measurable` at all.
 *
 * A card that reads `snapshot != null` is not enough; it has to read
 * `quality.measurable`.
 */
import { describe, it, expect } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import DealerGreeksFlowCard from '../components/DealerGreeksFlowCard.vue'
import MicrostructureTopographyCard from '../components/MicrostructureTopographyCard.vue'
import type { MicrostructureRegimeSnapshot, TopographyState } from '@/microstructureContracts'

const measurableTopo: TopographyState = {
  quadrant: 'forward_positive_ramp',
  title: 'Forward Positive Ramp',
  description: 'Large positive GEX stacked overhead above spot price.',
  dealer_hedging_action: 'Dealers sell aggressively into upward price progress.',
  expected_market_behavior: 'Mean-reverting grind.',
  gex_above_spot_m: 120,
  gex_below_spot_m: 45,
  gex_ratio: 2.66,
  call_wall: 510,
  put_wall: 490,
  gamma_flip: 497,
  volatility_trigger: 505,
  absolute_gamma_peak: 500,
}

const unmeasurableTopo: TopographyState = {
  quadrant: 'unmeasurable',
  title: 'Not measurable',
  description: 'No dealer gamma surface could be measured: no option chain available.',
  dealer_hedging_action: 'Unknown — no position data to infer hedging from.',
  expected_market_behavior: 'No claim.',
  gex_above_spot_m: 0,
  gex_below_spot_m: 0,
  gex_ratio: 0,
  call_wall: null,
  put_wall: null,
  gamma_flip: null,
  volatility_trigger: null,
  absolute_gamma_peak: null,
}

function snapshot(over: Partial<MicrostructureRegimeSnapshot> = {}): MicrostructureRegimeSnapshot {
  return {
    symbol: 'SPY',
    spot: 500,
    asof: '2026-08-28T16:00:00Z',
    regime: 'positive_gamma',
    regime_strength: 0.6,
    net_gex_m: 160,
    call_gex_m: 220,
    put_gex_m: -60,
    net_gex_profile_m: 158,
    net_vex_m: -12,
    net_chex_m: 5,
    hedging_flow_m: 8,
    zero_dte_charm_drift_m: 3,
    gamma_flip: 497,
    call_wall: 510,
    put_wall: 490,
    volatility_trigger: 505,
    absolute_gamma_peak: 500,
    quality: {
      measurable: true,
      contracts: 400,
      strikes: 60,
      total_open_interest: 900_000,
      iv_fallback_contracts: 0,
      flip_located: true,
      dealer_convention: 'index',
      reason: null,
    },
    topography: measurableTopo,
    strikes: [],
    gex_profile: [
      { spot: 490, net_gex_m: -20 },
      { spot: 510, net_gex_m: 200 },
    ],
    notes: [],
    ...over,
  }
}

/** What the server actually sends when there is no chain. */
function withheldSnapshot(): MicrostructureRegimeSnapshot {
  return snapshot({
    regime: 'unmeasurable',
    regime_strength: 0,
    net_gex_m: 0,
    call_gex_m: 0,
    put_gex_m: 0,
    net_gex_profile_m: null,
    net_vex_m: 0,
    net_chex_m: 0,
    hedging_flow_m: null,
    zero_dte_charm_drift_m: 0,
    gamma_flip: null,
    call_wall: null,
    put_wall: null,
    volatility_trigger: null,
    absolute_gamma_peak: null,
    quality: {
      measurable: false,
      contracts: 0,
      strikes: 0,
      total_open_interest: 0,
      iv_fallback_contracts: 0,
      flip_located: false,
      dealer_convention: 'index',
      reason: "no option chain available for 'SPY'",
    },
    topography: unmeasurableTopo,
    gex_profile: [],
  })
}

/**
 * SSR emits the template's own HTML comments into the output, and those
 * comments quote the very strings these tests assert are absent (the source
 * comment explaining why a level must not render as "$—" contains "$—").
 * Strip them so the assertions read rendered content only.
 */
function visible(html: string): string {
  return html.replace(/<!--[\s\S]*?-->/g, '')
}

async function renderGreeks(snap: MicrostructureRegimeSnapshot | null): Promise<string> {
  return visible(
    await renderToString(
      createSSRApp({ render: () => h(DealerGreeksFlowCard, { snapshot: snap }) }),
    ),
  )
}

async function renderTopo(topo: TopographyState | null): Promise<string> {
  return visible(
    await renderToString(
      createSSRApp({
        render: () => h(MicrostructureTopographyCard, { topography: topo, spot: 500 }),
      }),
    ),
  )
}

describe('DealerGreeksFlowCard', () => {
  it('renders the readout when the chain is measurable', async () => {
    const html = await renderGreeks(snapshot())
    expect(html).toContain('SUPPORTIVE')
    expect(html).toContain('Dealers absorb supply')
  })

  it('withholds every Greek when the chain is unmeasurable, and says why', async () => {
    const html = await renderGreeks(withheldSnapshot())
    // The reason reaches the operator...
    expect(html).toContain('no option chain available')
    // ...and none of the confident readouts do.
    expect(html).not.toContain('Dealers absorb supply')
    expect(html).not.toContain('Net Liquidity Extraction')
    expect(html).not.toContain('SUPPORTIVE')
    // Structural levels must never render as "$—".
    expect(html).not.toContain('$—')
  })

  it('withholds the hedging flow direction when the velocity was not measured', async () => {
    // hedging_flow_m is a flow RATE. Null means the spot/IV velocity behind it
    // was never measured — `?? 0` used to paint that as SUPPORTIVE.
    const html = await renderGreeks(snapshot({ hedging_flow_m: null }))
    expect(html).toContain('Not measured')
    expect(html).not.toContain('Dealers absorb supply')
    expect(html).not.toContain('Net Liquidity Extraction')
    // The rest of the card still reads normally — one absent field does not
    // withhold the fields that were measured.
    expect(html).toContain('220')
  })

  it('prints a bare dash, not "$—", for a flip that does not exist', async () => {
    const html = await renderGreeks(snapshot({ gamma_flip: null }))
    expect(html).not.toContain('$—')
    expect(html).toContain('none in range')
  })
})

describe('MicrostructureTopographyCard', () => {
  it('highlights the quadrant when one is defined', async () => {
    const html = await renderTopo(measurableTopo)
    expect(html).toContain('FORWARD POSITIVE RAMP')
    expect(html).toContain('Dealers sell aggressively')
  })

  it('highlights nothing and states the reason when no flip located the quadrant', async () => {
    const html = await renderTopo(unmeasurableTopo)
    expect(html).toContain('No dealer gamma surface could be measured')
    // No quadrant badge, no zeroed metrics strip presented as measurements.
    expect(html).not.toContain('UNMEASURABLE')
    expect(html).not.toContain('GEX Overhead Ratio')
    expect(html).not.toContain('$—')
  })
})
