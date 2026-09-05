/**
 * Unit test suite for PriceDrawLadder.vue.
 *
 * Verifies visual gauge rail rendering, ranked attraction targets matrix,
 * signed distance and pull score formatting, supporting lens chips,
 * interactive level selection, and zero-spoofing / unmeasured handling.
 */
import { describe, it, expect } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import PriceDrawLadder from '../components/PriceDrawLadder.vue'
import type { PriceDrawTelemetryPayload, PriceDrawLevel } from '../priceDrawContracts'

const sampleLevels: PriceDrawLevel[] = [
  {
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
  },
  {
    id: 'kinematic_drift_601',
    type: 'kinematic_drift',
    label: 'Kinematic Drift',
    price: 601.2,
    distance_pts: 2.78,
    distance_pct: 0.46,
    pull_score: 64,
    direction: 'above',
    regime_role: 'Kinematic Attractor',
    supporting_lenses: ['KALMAN', 'NW'],
    lens_count: 2,
    is_primary_magnet: false,
  },
  {
    id: 'gamma_flip_595',
    type: 'gamma_flip',
    label: 'Gamma Flip',
    price: 595.0,
    distance_pts: -3.42,
    distance_pct: -0.57,
    pull_score: 72,
    direction: 'below',
    regime_role: 'Regime Transition Pivot',
    supporting_lenses: ['GAMMA', 'FLIP'],
    lens_count: 2,
    is_primary_magnet: false,
  },
  {
    id: 'max_pain_590',
    type: 'max_pain_pin',
    label: 'Max Pain Pin',
    price: 590.0,
    distance_pts: -8.42,
    distance_pct: -1.41,
    pull_score: 55,
    direction: 'below',
    regime_role: 'Expiry Pin',
    supporting_lenses: ['OI', 'CHARM'],
    lens_count: 2,
    is_primary_magnet: false,
  },
  {
    id: 'put_wall_585',
    type: 'put_wall',
    label: 'Put Wall',
    price: 585.0,
    distance_pts: -13.42,
    distance_pct: -2.24,
    pull_score: 81,
    direction: 'below',
    regime_role: 'Downside Support Floor',
    supporting_lenses: ['GAMMA', 'GEX'],
    lens_count: 2,
    is_primary_magnet: false,
  },
]

const samplePayload: PriceDrawTelemetryPayload = {
  symbol: 'SPY',
  spot: 598.42,
  asof_utc: '2026-08-29T18:00:00Z',
  regime_state: 'volatility_dampening',
  regime_label: 'Vol Dampening (Long Γ)',
  regime_strength: 0.85,
  dominant_direction: 'bullish_pull',
  primary_magnet: sampleLevels[0],
  levels: sampleLevels,
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

async function renderLadder(props: Record<string, unknown> = {}): Promise<string> {
  const app = createSSRApp({
    render: () => h(PriceDrawLadder, props),
  })
  return renderToString(app)
}

describe('PriceDrawLadder — Visual Gauge Rail', () => {
  it('renders spot level with price and active marker on the rail', async () => {
    const html = await renderLadder({
      payload: samplePayload,
      spot: 598.42,
      levels: sampleLevels,
    })
    expect(html).toContain('SPOT $598.42')
    expect(html).toContain('spot-marker')
    expect(html).toContain('spot-line')
    expect(html).toContain('ACTIVE')
  })

  it('renders all structural target markers on the gauge rail', async () => {
    const html = await renderLadder({
      payload: samplePayload,
    })
    expect(html).toContain('Call Wall')
    expect(html).toContain('$605.00')
    expect(html).toContain('Put Wall')
    expect(html).toContain('$585.00')
    expect(html).toContain('Gamma Flip')
    expect(html).toContain('$595.00')
    expect(html).toContain('Max Pain Pin')
    expect(html).toContain('$590.00')
    expect(html).toContain('Kinematic Drift')
    expect(html).toContain('$601.20')
  })

  it('highlights primary magnet with star indicator on the gauge', async () => {
    const html = await renderLadder({
      payload: samplePayload,
    })
    expect(html).toContain('★')
    expect(html).toContain('is-primary')
  })
})

describe('PriceDrawLadder — Ranked Attraction Targets Table', () => {
  it('renders table headers for level, type, dist, pull score, regime role, and lenses', async () => {
    const html = await renderLadder({ payload: samplePayload })
    expect(html).toContain('LEVEL')
    expect(html).toContain('TYPE')
    expect(html).toContain('DIST (PTS / %)')
    expect(html).toContain('PULL SCORE')
    expect(html).toContain('REGIME ROLE')
    expect(html).toContain('SUPPORTING LENSES')
  })

  it('ranks primary magnet first regardless of numerical sort', async () => {
    const html = await renderLadder({ payload: samplePayload })
    // The first row in table body should be Call Wall (primary magnet)
    const tbodyIdx = html.indexOf('<tbody')
    const firstRow = html.slice(tbodyIdx, html.indexOf('</tr>', tbodyIdx))
    expect(firstRow).toContain('Call Wall')
    expect(firstRow).toContain('★')
  })

  it('formats signed distance points and percentages correctly', async () => {
    const html = await renderLadder({ payload: samplePayload })
    // Above spot
    expect(html).toContain('+6.58 (+1.10%)')
    expect(html).toContain('+2.78 (+0.46%)')
    // Below spot
    expect(html).toContain('-3.42 (-0.57%)')
    expect(html).toContain('-8.42 (-1.41%)')
    expect(html).toContain('-13.42 (-2.24%)')
  })

  it('renders pull score meter bars and percentages', async () => {
    const html = await renderLadder({ payload: samplePayload })
    expect(html).toContain('88%')
    expect(html).toContain('72%')
    expect(html).toContain('81%')
    expect(html).toContain('pull-bar-fill')
  })

  it('renders multi-lens badge chips with domain-specific classes', async () => {
    const html = await renderLadder({ payload: samplePayload })
    expect(html).toContain('GAMMA')
    expect(html).toContain('KALMAN')
    expect(html).toContain('CHARM')
    expect(html).toContain('lens-gamma')
    expect(html).toContain('lens-kalman')
    expect(html).toContain('lens-charm')
  })

  it('renders regime role descriptions accurately', async () => {
    const html = await renderLadder({ payload: samplePayload })
    expect(html).toContain('Overhead Resistance Cap')
    expect(html).toContain('Regime Transition Pivot')
    expect(html).toContain('Downside Support Floor')
    expect(html).toContain('Expiry Pin')
  })
})

describe('PriceDrawLadder — Zero-Spoofing & Unmeasured Handling', () => {
  it('renders clean unmeasured state when payload is unmeasurable', async () => {
    const unmeasuredPayload: PriceDrawTelemetryPayload = {
      symbol: 'ABC',
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
        reason: 'Option chain missing for ticker ABC',
      },
      warnings: ['Option chain missing for ticker ABC'],
    }

    const html = await renderLadder({ payload: unmeasuredPayload })
    expect(html).toContain('REGIME UNMEASURED · NO ACTIVE PRICE MAGNETS')
    expect(html).toContain('Option chain missing for ticker ABC')
    expect(html).not.toContain('<table')
    expect(html).not.toContain('$0.00')
    expect(html).not.toContain('NaN')
  })

  it('handles null distance or pull score fields with explicit dashes (—)', async () => {
    const sparseLevel: PriceDrawLevel = {
      id: 'sparse_100',
      type: 'confluence_zone',
      label: 'Confluence Zone',
      price: 100.0,
      distance_pts: null,
      distance_pct: null,
      pull_score: null,
      direction: 'at_spot',
      regime_role: '',
      supporting_lenses: ['VOLUME'],
      lens_count: 1,
      is_primary_magnet: false,
    }

    const html = await renderLadder({
      spot: 100.0,
      levels: [sparseLevel],
      quality: {
        measurable: true,
        open_interest_available: true,
        iv_available: true,
        volume_available: true,
        reason: null,
      },
    })
    expect(html).toContain('Confluence Zone')
    expect(html).toContain('—')
    expect(html).not.toContain('NaN%')
    expect(html).not.toContain('null')
  })
})

describe('PriceDrawLadder — Selected Level & Compact Prop', () => {
  it('marks selected level with is-selected class', async () => {
    const html = await renderLadder({
      payload: samplePayload,
      selectedLevelId: 'gamma_flip_595',
    })
    expect(html).toContain('is-selected')
  })

  it('supports compact prop styling', async () => {
    const html = await renderLadder({
      payload: samplePayload,
      compact: true,
    })
    expect(html).toContain('is-compact')
  })
})
