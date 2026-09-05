/**
 * Unit test suite for RegimeStateBadge.vue.
 *
 * Verifies active regime classification pills, directional pull vector badges,
 * scale-free strength tags, primary magnet target pills, and strict zero-spoofing /
 * missing data formatting.
 */
import { describe, it, expect } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import RegimeStateBadge from '../components/RegimeStateBadge.vue'
import type {
  PriceDrawTelemetryPayload,
  MarketRegimeType,
  PriceDrawLevel,
} from '../priceDrawContracts'

const sampleMagnet: PriceDrawLevel = {
  id: 'call_wall_605',
  type: 'call_wall',
  label: 'Call Wall',
  price: 605.0,
  distance_pts: 6.58,
  distance_pct: 1.1,
  pull_score: 88,
  direction: 'above',
  regime_role: 'Overhead Resistance Cap',
  supporting_lenses: ['GAMMA', 'GEX', 'IV'],
  lens_count: 3,
  is_primary_magnet: true,
}

const samplePayload: PriceDrawTelemetryPayload = {
  symbol: 'SPY',
  spot: 598.42,
  asof_utc: '2026-08-29T18:00:00Z',
  regime_state: 'volatility_dampening',
  regime_label: 'Vol Dampening (Long Γ)',
  regime_strength: 0.85,
  dominant_direction: 'bullish_pull',
  primary_magnet: sampleMagnet,
  levels: [sampleMagnet],
  confluence_clusters: [],
  quality: {
    measurable: true,
    open_interest_available: true,
    iv_available: true,
    volume_available: true,
    reason: null,
  },
  warnings: [],
}

async function renderBadge(props: Record<string, unknown> = {}): Promise<string> {
  const app = createSSRApp({
    render: () => h(RegimeStateBadge, props),
  })
  return renderToString(app)
}

describe('RegimeStateBadge — Regime Classification Pills', () => {
  it('renders volatility dampening (long gamma) regime with correct text and class', async () => {
    const html = await renderBadge({
      regimeState: 'volatility_dampening' as MarketRegimeType,
      dominantDirection: 'bullish_pull',
      regimeStrength: 0.92,
      measurable: true,
    })
    expect(html).toContain('VOL DAMPENING · LONG Γ')
    expect(html).toContain('regime-dampening')
    expect(html).toContain('92%')
  })

  it('renders volatility amplification (short gamma) regime', async () => {
    const html = await renderBadge({
      regimeState: 'volatility_amplification' as MarketRegimeType,
      dominantDirection: 'bearish_pull',
      regimeStrength: 0.78,
      measurable: true,
    })
    expect(html).toContain('VOL AMPLIFICATION · SHORT Γ')
    expect(html).toContain('regime-amplification')
    expect(html).toContain('78%')
  })

  it('renders charm decay selling drift regime', async () => {
    const html = await renderBadge({
      regimeState: 'charm_decay_selling' as MarketRegimeType,
      dominantDirection: 'bearish_pull',
      regimeStrength: 0.65,
      measurable: true,
    })
    expect(html).toContain('CHARM DECAY · SELLING DRIFT')
    expect(html).toContain('regime-charm')
  })

  it('renders charm decay buying drift regime', async () => {
    const html = await renderBadge({
      regimeState: 'charm_decay_buying' as MarketRegimeType,
      dominantDirection: 'bullish_pull',
      regimeStrength: 0.61,
      measurable: true,
    })
    expect(html).toContain('CHARM DECAY · BUYING DRIFT')
    expect(html).toContain('regime-charm')
  })

  it('renders vanna vol expansion regime', async () => {
    const html = await renderBadge({
      regimeState: 'vanna_vol_expansion' as MarketRegimeType,
      dominantDirection: 'bearish_pull',
      regimeStrength: 0.88,
      measurable: true,
    })
    expect(html).toContain('VANNA EXPANSION · VOL SHOCK')
    expect(html).toContain('regime-vanna')
  })

  it('renders neutral transition gamma-flip straddle regime', async () => {
    const html = await renderBadge({
      regimeState: 'neutral_transition' as MarketRegimeType,
      dominantDirection: 'neutral_pin',
      regimeStrength: 0.5,
      measurable: true,
    })
    expect(html).toContain('TRANSITION STRADDLE · Γ-FLIP')
    expect(html).toContain('regime-transition')
  })

  it('renders unmeasurable regime cleanly with neutral placeholders', async () => {
    const html = await renderBadge({
      regimeState: 'unmeasurable' as MarketRegimeType,
      measurable: false,
    })
    expect(html).toContain('REGIME UNMEASURED')
    expect(html).toContain('regime-unmeasured')
    expect(html).toContain('vector-unmeasured')
  })
})

describe('RegimeStateBadge — Directional Pull Vector Pills', () => {
  it('renders bullish pull vector pill', async () => {
    const html = await renderBadge({
      regimeState: 'volatility_dampening',
      dominantDirection: 'bullish_pull',
      measurable: true,
    })
    expect(html).toContain('▲ BULLISH PULL')
    expect(html).toContain('vector-bullish')
  })

  it('renders bearish pull vector pill', async () => {
    const html = await renderBadge({
      regimeState: 'volatility_amplification',
      dominantDirection: 'bearish_pull',
      measurable: true,
    })
    expect(html).toContain('▼ BEARISH PULL')
    expect(html).toContain('vector-bearish')
  })

  it('renders neutral pin vector pill', async () => {
    const html = await renderBadge({
      regimeState: 'neutral_transition',
      dominantDirection: 'neutral_pin',
      measurable: true,
    })
    expect(html).toContain('● NEUTRAL PIN')
    expect(html).toContain('vector-neutral')
  })

  it('renders unmeasured vector as dash when unmeasured', async () => {
    const html = await renderBadge({
      dominantDirection: 'unmeasured',
      measurable: false,
    })
    expect(html).toContain('—')
    expect(html).toContain('vector-unmeasured')
  })
})

describe('RegimeStateBadge — Payload Integration & Props', () => {
  it('renders completely from PriceDrawTelemetryPayload', async () => {
    const html = await renderBadge({
      payload: samplePayload,
      showPrimaryMagnet: true,
    })
    expect(html).toContain('VOL DAMPENING · LONG Γ')
    expect(html).toContain('▲ BULLISH PULL')
    expect(html).toContain('85%')
    expect(html).toContain('Call Wall')
    expect(html).toContain('$605.00')
    expect(html).toContain('+1.10%')
  })

  it('respects compact mode and visibility toggles', async () => {
    const html = await renderBadge({
      payload: samplePayload,
      compact: true,
      showVector: false,
      showStrength: false,
    })
    expect(html).toContain('is-compact')
    expect(html).not.toContain('▲ BULLISH PULL')
    expect(html).not.toContain('85%')
    expect(html).toContain('VOL DAMPENING · LONG Γ')
  })

  it('handles zero-spoofing when payload indicates unmeasurable data', async () => {
    const unmeasuredPayload: PriceDrawTelemetryPayload = {
      symbol: 'XYZ',
      spot: null,
      asof_utc: '2026-08-29T18:00:00Z',
      regime_state: 'unmeasurable',
      regime_label: 'Unmeasured Regime',
      regime_strength: null,
      dominant_direction: 'unmeasured',
      primary_magnet: null,
      levels: [],
      confluence_clusters: [],
      quality: {
        measurable: false,
        open_interest_available: false,
        iv_available: false,
        volume_available: false,
        reason: 'Chain missing',
      },
      warnings: ['Chain missing'],
    }

    const html = await renderBadge({ payload: unmeasuredPayload })
    expect(html).toContain('REGIME UNMEASURED')
    expect(html).toContain('—')
    expect(html).not.toContain('NaN')
    expect(html).not.toContain('undefined')
    expect(html).not.toContain('null')
  })
})
