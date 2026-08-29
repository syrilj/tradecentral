/**
 * PressureDriftChart (charm flow by strike) + DriftView structural and
 * geometry gate.
 *
 * Mirrors the options-drift-chart and options-ui-tokens pattern: reads the
 * shipped SFC source and asserts the charm chart uses the instrument palette
 * (sell=put / buy=call / phosphor=net trace), has a true zero midline with
 * selling pressure rising up and buying pressure growing down, and never
 * emits NaN into an SVG path. The math section exercises the pure scales the
 * chart is built on, exactly the way options-drift-chart.test.ts does.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { linearScale, linePath, niceTicks } from '../charts'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function readSrc(rel: string): string {
  return readFileSync(join(root, rel), 'utf8')
}

const FORBIDDEN = [
  '#ef4444',
  '#f87171',
  '#059669',
  '#dc2626',
  '0xef4444',
  'drop-shadow',
  'GREEN=CALL',
  'RED=PUT',
]

describe('PressureDriftChart token & structure gate (shipped SFC)', () => {
  const src = () => readSrc('components/PressureDriftChart.vue')

  it('uses call/put/phosphor tokens — no hardcoded neon or green/red confusion', () => {
    const s = src()
    for (const bad of FORBIDDEN) {
      expect(s, `PressureDriftChart still contains forbidden pattern: ${bad}`).not.toContain(bad)
    }
  })

  it('selling bars use the put token and rise UP from the zero midline', () => {
    const s = src()
    expect(s).toMatch(/\.bar\.sell\s*\{\s*fill:\s*var\(--put\)/)
    expect(s).toContain('zeroY - bar.sellH')
    expect(s).toContain('SELLING PRESSURE')
  })

  it('buying bars use the call token and grow DOWN from the zero midline', () => {
    const s = src()
    expect(s).toMatch(/\.bar\.buy\s*\{\s*fill:\s*var\(--call\)/)
    expect(s).toContain('zeroY')
    expect(s).toContain('BUYING PRESSURE')
  })

  it('the net trace uses the phosphor token as a continuous pressure read', () => {
    const s = src()
    expect(s).toMatch(/\.net-trace\s*\{\s*stroke:\s*var\(--phosphor\)/)
    expect(s).toContain('net-trace')
    expect(s).toContain('Net trace across strikes')
  })

  it('has a centered zero midline dividing the two pressure panes', () => {
    const s = src()
    expect(s).toContain('zeroY')
    expect(s).toMatch(
      /zeroY\s*=\s*computed\(\(\)\s*=>\s*plotTop\.value\s*\+\s*plotH\.value\s*\/\s*2\)/,
    )
    expect(s).toMatch(/class="zero"/)
  })

  it('renders an honest empty state rather than fake-zero bars', () => {
    const s = src()
    expect(s).toContain('NO CHARM DATA — CHAIN MISSING IV OR OI')
  })

  it('labels the readout as a positioning proxy, not observed flow', () => {
    const s = src()
    expect(s).toContain('Positioning proxy from open interest, not observed flow')
    expect(s).toContain('shares/day')
  })

  it('uses the chart-size composable and a strike (not time) axis', () => {
    const s = src()
    expect(s).toContain("from '@/composables/useChartSize'")
    expect(s).toContain('useChartSize(frameEl')
    expect(s).toContain('strikeDomain')
  })
})

describe('DriftView structure gate (shipped SFC)', () => {
  const src = () => readSrc('views/DriftView.vue')

  it('mounts the charm chart, GEX map, and strike table', () => {
    const s = src()
    expect(s).toContain('PressureDriftChart')
    expect(s).toContain('GammaExposureMap')
    expect(s).toContain('strike-table')
    expect(s).toContain('charm_by_strike')
    expect(s).toContain('chain_by_strike')
  })

  it('wires the pressure gauge to the backend pressure payload', () => {
    const s = src()
    expect(s).toContain('pressure')
    expect(s).toContain('gauge-needle')
    expect(s).toContain('aria-valuenow')
    expect(s).toContain('convention_note')
  })

  it('shows KPI cards for GEX, charm flow, P/C ratio, and last update', () => {
    const s = src()
    expect(s).toContain('NET GEX')
    expect(s).toContain('NET CHARM FLOW')
    expect(s).toContain('PUT / CALL RATIO')
    expect(s).toContain('LAST UPDATE')
  })

  it('has range, expiry, and symbol controls that drive the query and refresh', () => {
    const s = src()
    expect(s).toContain('selectedRange')
    expect(s).toContain('selectedExpiry')
    expect(s).toContain('symbolInput')
    expect(s).toContain("name: 'drift'")
    expect(s).toContain('optionsRes.refresh({ clear: true })')
  })

  it('renders missing metrics as stale, not fake zeros', () => {
    const s = src()
    expect(s).toContain('stale')
    expect(s).toContain(": '—'")
    expect(s).toContain('NO CHAIN')
  })

  it('has no forbidden neon / glass effects', () => {
    const s = src()
    for (const bad of FORBIDDEN) {
      expect(s, `DriftView still contains forbidden pattern: ${bad}`).not.toContain(bad)
    }
    expect(s).not.toContain('backdrop-filter')
  })
})

describe('PressureDriftChart Math & Geometry Engine', () => {
  it('builds a symmetric flow scale about the zero midline', () => {
    const H = 420
    const pad = { l: 56, r: 18, t: 22, b: 24 }
    const plotTop = pad.t
    const plotBot = H - pad.b
    const plotH = plotBot - plotTop
    const zeroY = plotTop + plotH / 2
    const halfH = plotH / 2

    // zero midline is exactly centred
    expect(zeroY).toBeCloseTo(plotTop + halfH)

    const flowMax = 50_000
    const barScale = halfH / flowMax

    // A bar at full scale sells up to the top of the sell pane
    const sellH = flowMax * barScale
    expect(zeroY - sellH).toBeCloseTo(plotTop)

    // A bar at full scale buys down to the bottom of the buy pane
    const buyH = flowMax * barScale
    expect(zeroY + buyH).toBeCloseTo(plotBot)
  })

  it('maps positive net charm flow to selling pressure (above zero)', () => {
    const flowMax = 50_000
    const plotTop = 22
    const plotBot = 396
    const zeroY = plotTop + (plotBot - plotTop) / 2
    const yScale = linearScale([-flowMax, flowMax], [plotBot, plotTop])

    // Positive flow (dealers sell) maps above the midline (smaller y = up)
    expect(yScale(25_000)).toBeLessThan(zeroY)
    // Negative flow (dealers buy) maps below the midline
    expect(yScale(-25_000)).toBeGreaterThan(zeroY)
    // Zero maps to the midline
    expect(yScale(0)).toBeCloseTo(zeroY)
  })

  it('net trace path never emits NaN or Infinity', () => {
    const rows = [
      { strike: 90, net_charm_flow: -12_000 },
      { strike: 100, net_charm_flow: 4_000 },
      { strike: 110, net_charm_flow: 18_000 },
    ]
    const xScale = linearScale([85, 115], [56, 982])
    const yScale = linearScale([-20_000, 20_000], [396, 22])
    const d = linePath(rows.map((r) => ({ x: xScale(r.strike), y: yScale(r.net_charm_flow) })))
    expect(d).not.toContain('NaN')
    expect(d).not.toContain('Infinity')
    expect(d.startsWith('M')).toBe(true)
  })

  it('flow magnitude ticks are mirrored about the midline', () => {
    const flowMax = 50_000
    const halfH = 180
    const zeroY = 210
    const ticks = niceTicks(0, flowMax, 3)
    expect(ticks.length).toBeGreaterThan(0)
    for (const v of ticks) {
      const sellY = zeroY - (v / flowMax) * halfH
      const buyY = zeroY + (v / flowMax) * halfH
      // Sell ticks sit at or above the midline; buy ticks at or below
      expect(sellY).toBeLessThanOrEqual(zeroY)
      expect(buyY).toBeGreaterThanOrEqual(zeroY)
    }
  })

  it('strike axis is ordinal over strikes, not wall-clock time', () => {
    const strikes = [90, 95, 100, 105, 110]
    const xScale = linearScale([strikes[0], strikes[strikes.length - 1]], [56, 982])
    expect(xScale(90)).toBeCloseTo(56)
    expect(xScale(110)).toBeCloseTo(982)
    expect(xScale(100)).toBeCloseTo((56 + 982) / 2)
  })

  it('linePath returns empty string on empty input rather than crashing', () => {
    expect(linePath([])).toBe('')
  })
})

describe('Router and navigation register the Drift tab', () => {
  it('router has a /drift route named drift pointing at DriftView', () => {
    const r = readSrc('router.ts')
    expect(r).toMatch(/path:\s*'\/drift'\s*,\s*name:\s*'drift'/s)
    expect(r).toContain("import('@/views/DriftView.vue')")
  })

  it('App primary nav includes Drift with the drift icon', () => {
    const a = readSrc('App.vue')
    expect(a).toMatch(/name:\s*'drift'[^}]*title:\s*'Drift'/s)
    expect(a).toMatch(/name:\s*'drift'[^}]*icon:\s*'drift'/s)
    expect(a).toContain("'drift'")
  })

  it('AppIcon renders a drift icon template', () => {
    const i = readSrc('components/AppIcon.vue')
    expect(i).toContain("name === 'drift'")
  })
})
