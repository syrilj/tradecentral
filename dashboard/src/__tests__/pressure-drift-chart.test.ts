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

  it('keeps tape pressure as separate evidence with source context', () => {
    const s = src()
    expect(s).toContain('dealerRead.evidence.pressureVerdict')
    expect(s).toContain('dealerRead.evidence.pressureActionable')
    expect(s).toContain('Tape pressure is reported separately')
    expect(s).toContain('dealer-evidence-details')
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

describe('PressureDriftChart missing-data detection (shipped SFC)', () => {
  const src = () => readSrc('components/PressureDriftChart.vue')

  it('distinguishes a whole-chain zero-flow outage from a genuinely balanced chain', () => {
    const s = src()
    // hasSignal/noData must exist and must look at call/put/net flow, not
    // just row count, or an all-zero chain (every strike passed the finite
    // filter but every value is exactly 0) silently renders a blank axis
    // instead of the explicit no-data message.
    expect(s).toContain('hasSignal')
    expect(s).toMatch(
      /const noData = computed\(\(\) => ordered\.value\.length === 0 \|\| !hasSignal\.value\)/,
    )
    expect(s).toContain('hasFlow(r.net_charm_flow)')
    expect(s).toContain('hasFlow(r.call_charm_flow)')
    expect(s).toContain('hasFlow(r.put_charm_flow)')
  })

  it('gates the empty-state text on noData, not on bars.length', () => {
    const s = src()
    expect(s).toMatch(/<text v-if="noData" class="empty"/)
    expect(s).not.toContain('v-if="!bars.length"')
  })

  it('suppresses the net-trace flat line and hover probe when noData', () => {
    const s = src()
    expect(s).toMatch(
      /const netPath = computed\(\(\) =>\s*noData\.value\s*\?\s*''\s*:\s*linePath\(/,
    )
    expect(s).toMatch(/if \(!el \|\| n === 0 \|\| noData\.value\)/)
  })

  it('never prints a fake "0" for the sh/d totals when data is missing', () => {
    const s = src()
    expect(s).toContain('totalSellDisplay')
    expect(s).toContain('totalBuyDisplay')
    expect(s).toContain('netTotalDisplay')
    expect(s).toMatch(/import \{ compact, num, DASH \} from '@\/format'/)
  })

  it('the aria-label reflects the no-data state instead of always claiming pressure panes', () => {
    const s = src()
    expect(s).toContain('no usable data, chain missing IV or OI')
  })
})

describe('PressureDriftChart Math & Geometry Engine — missing/degenerate data regressions', () => {
  /**
   * Mirrors the exact computed pipeline in PressureDriftChart.vue
   * (ordered → hasSignal/noData → strikeDomain → xScale/flowMax/yScale →
   * bars → netPath) using the same `charts.ts` primitives the component
   * imports, so these tests exercise the real arithmetic without needing a
   * DOM-mounted SFC (this suite has no @vue/test-utils / jsdom dependency —
   * see the source-gate tests above and elsewhere in this file for the
   * established pattern).
   */
  interface Row {
    strike: number
    call_charm_flow: number
    put_charm_flow: number
    net_charm_flow: number
    call_oi: number
    put_oi: number
  }

  function hasFlow(v: number): boolean {
    return Number.isFinite(v) && v !== 0
  }

  function computeChartState(rows: Partial<Row>[]) {
    const W = 1120
    const pad = { l: 64, r: 24, t: 26, b: 28 }
    const H = 440
    const plotTop = pad.t
    const plotBot = H - pad.b
    const halfH = (plotBot - plotTop) / 2
    const zeroY = plotTop + halfH

    const ordered = rows
      .filter(
        (r): r is Row => Number.isFinite(r.strike) && Number.isFinite(r.net_charm_flow as number),
      )
      .sort((a, b) => a.strike - b.strike)

    const hasSignal = ordered.some(
      (r) => hasFlow(r.net_charm_flow) || hasFlow(r.call_charm_flow) || hasFlow(r.put_charm_flow),
    )
    const noData = ordered.length === 0 || !hasSignal

    const strikes = ordered.map((r) => r.strike)
    const strikeDomain = !strikes.length
      ? { lo: 0, hi: 1 }
      : (() => {
          const lo = Math.min(...strikes)
          const hi = Math.max(...strikes)
          if (lo === hi) return { lo: lo - 1, hi: hi + 1 }
          const padAmt = (hi - lo) * 0.05
          return { lo: lo - padAmt, hi: hi + padAmt }
        })()

    const xScale = linearScale([strikeDomain.lo, strikeDomain.hi], [pad.l, W - pad.r])

    let flowMax = 1
    for (const r of ordered) flowMax = Math.max(flowMax, Math.abs(r.net_charm_flow))

    const yScale = linearScale([-flowMax, flowMax], [plotBot, plotTop])

    const bars = ordered.map((r) => {
      const net = r.net_charm_flow
      const sell = Math.max(0, net)
      const buy = Math.max(0, -net)
      return {
        strike: r.strike,
        x: xScale(r.strike),
        net,
        sellH: Math.max(sell > 0 ? 2 : 0, sell * (halfH / flowMax)),
        buyH: Math.max(buy > 0 ? 2 : 0, buy * (halfH / flowMax)),
      }
    })

    const netPath = noData
      ? ''
      : linePath(ordered.map((r) => ({ x: xScale(r.strike), y: yScale(r.net_charm_flow) })))

    return { ordered, noData, strikeDomain, xScale, yScale, bars, netPath, zeroY, flowMax }
  }

  function assertAllFinite(bars: { x: number; net: number; sellH: number; buyH: number }[]) {
    for (const b of bars) {
      expect(Number.isFinite(b.x)).toBe(true)
      expect(Number.isFinite(b.sellH)).toBe(true)
      expect(Number.isFinite(b.buyH)).toBe(true)
    }
  }

  it('all-zero rows: every strike present but every flow value is exactly 0 (whole chain missing IV/OI) triggers noData', () => {
    const rows: Row[] = Array.from({ length: 40 }, (_, i) => ({
      strike: 90 + i,
      call_charm_flow: 0,
      put_charm_flow: 0,
      net_charm_flow: 0,
      call_oi: 0,
      put_oi: 0,
    }))
    const state = computeChartState(rows)

    expect(state.ordered.length).toBe(40) // rows pass the finite filter — 0 is finite
    expect(state.noData).toBe(true) // but the explicit no-data state must still fire
    expect(state.netPath).toBe('') // no misleading flat line at the zero midline
    expect(Number.isFinite(state.flowMax)).toBe(true)
    expect(state.flowMax).toBeGreaterThan(0) // degenerate-domain guard: never 0
    assertAllFinite(state.bars)
    for (const b of state.bars) {
      expect(b.sellH).toBe(0)
      expect(b.buyH).toBe(0)
    }
  })

  it('empty rows: zero-length payload triggers noData with a finite (non-degenerate) domain', () => {
    const state = computeChartState([])

    expect(state.ordered.length).toBe(0)
    expect(state.noData).toBe(true)
    expect(state.netPath).toBe('')
    expect(state.strikeDomain).toEqual({ lo: 0, hi: 1 })
    expect(Number.isFinite(state.xScale(0.5))).toBe(true)
    expect(state.bars).toEqual([])
  })

  it('single row: strikeDomain widens around the lone strike instead of collapsing to a zero-width domain', () => {
    const rows: Row[] = [
      {
        strike: 100,
        call_charm_flow: 5000,
        put_charm_flow: -1200,
        net_charm_flow: 3800,
        call_oi: 50,
        put_oi: 20,
      },
    ]
    const state = computeChartState(rows)

    expect(state.noData).toBe(false) // real, non-zero signal present
    expect(state.strikeDomain).toEqual({ lo: 99, hi: 101 }) // ±1 padding, not lo === hi
    expect(Number.isFinite(state.xScale(100))).toBe(true)
    expect(state.xScale.domain[0]).not.toBe(state.xScale.domain[1])
    assertAllFinite(state.bars)
    expect(state.netPath).not.toContain('NaN')
    expect(state.netPath).not.toContain('Infinity')
    expect(state.netPath.startsWith('M')).toBe(true)
  })

  it('all-identical strikes: a repeated single strike value never divides by a zero-width domain', () => {
    const rows: Row[] = [
      {
        strike: 100,
        call_charm_flow: 1000,
        put_charm_flow: 0,
        net_charm_flow: 1000,
        call_oi: 10,
        put_oi: 0,
      },
      {
        strike: 100,
        call_charm_flow: 0,
        put_charm_flow: -500,
        net_charm_flow: -500,
        call_oi: 0,
        put_oi: 5,
      },
      {
        strike: 100,
        call_charm_flow: 200,
        put_charm_flow: -200,
        net_charm_flow: 0,
        call_oi: 2,
        put_oi: 2,
      },
    ]
    const state = computeChartState(rows)

    expect(state.noData).toBe(false)
    expect(state.strikeDomain).toEqual({ lo: 99, hi: 101 }) // lo === hi guard still applies with >1 row
    assertAllFinite(state.bars)
    expect(state.bars.every((b) => Number.isFinite(b.x))).toBe(true)
    // All three bars land on the same x — collapsing domain, not a crash.
    const xs = new Set(state.bars.map((b) => b.x))
    expect(xs.size).toBe(1)
    expect(state.netPath).not.toContain('NaN')
    expect(state.netPath).not.toContain('Infinity')
  })

  it('NaN/null values in the payload are filtered out before they can reach a scale or path', () => {
    const rows = [
      {
        strike: NaN,
        call_charm_flow: 100,
        put_charm_flow: 0,
        net_charm_flow: 100,
        call_oi: 1,
        put_oi: 0,
      },
      {
        strike: 95,
        call_charm_flow: NaN,
        put_charm_flow: NaN,
        net_charm_flow: null as unknown as number,
        call_oi: 1,
        put_oi: 1,
      },
      {
        strike: 100,
        call_charm_flow: 2500,
        put_charm_flow: -900,
        net_charm_flow: 1600,
        call_oi: 30,
        put_oi: 12,
      },
      {
        strike: undefined as unknown as number,
        call_charm_flow: 50,
        put_charm_flow: 0,
        net_charm_flow: 50,
        call_oi: 1,
        put_oi: 0,
      },
    ]
    const state = computeChartState(rows)

    // Only the one fully-finite row survives the filter.
    expect(state.ordered.length).toBe(1)
    expect(state.ordered[0].strike).toBe(100)
    expect(state.noData).toBe(false)
    assertAllFinite(state.bars)
    expect(state.netPath).not.toContain('NaN')
    expect(state.netPath).not.toContain('Infinity')
  })

  it('NaN in call/put flow does not masquerade as signal when net flow is legitimately 0', () => {
    // Corrupted call/put cells (NaN) alongside a clean net=0 must NOT be
    // read as "real signal" — hasFlow requires Number.isFinite, so a NaN
    // never counts, and an otherwise all-zero chain still reports noData.
    const rows: Row[] = [
      {
        strike: 90,
        call_charm_flow: NaN,
        put_charm_flow: 0,
        net_charm_flow: 0,
        call_oi: 0,
        put_oi: 0,
      },
      {
        strike: 95,
        call_charm_flow: 0,
        put_charm_flow: NaN,
        net_charm_flow: 0,
        call_oi: 0,
        put_oi: 0,
      },
    ]
    const state = computeChartState(rows)
    expect(state.ordered.length).toBe(2)
    expect(state.noData).toBe(true)
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

describe('DriftView Strike Table, Directional Strategies & Flow Diagram Enhancements', () => {
  const src = () => readSrc('views/DriftView.vue')

  it('strike table uses separate border-collapse for bulletproof sticky positioning', () => {
    const s = src()
    expect(s).toContain('border-collapse: separate')
    expect(s).toContain('border-spacing: 0')
    expect(s).toContain('header-group th')
    expect(s).toContain('header-cols th')
  })

  it('provides sortable columns and CSV export on the strike table', () => {
    const s = src()
    expect(s).toContain('toggleSort')
    expect(s).toContain('exportCsv')
    expect(s).toContain('EXPORT CSV')
  })

  it('provides quick ticker chips and nearest strike filter modes', () => {
    const s = src()
    expect(s).toContain('QUICK TICKERS')
    expect(s).toContain('selectQuickSymbol')
    expect(s).toContain('NEAREST (±10)')
    expect(s).toContain('NEAR SPOT (±10%)')
    expect(s).toContain('HIGH CHARM')
    expect(s).toContain('WALLS &amp; FLIP')
  })

  it('labels Charm as modeled positioning instead of an execution signal', () => {
    const s = src()
    expect(s).toContain('Structural estimate, not observed tape buying or selling')
    expect(s).toContain('does not establish a directional trade')
    expect(s).not.toContain('Directional Execution:')
  })

  it('shows data freshness and model limitations beside the structural read', () => {
    const s = src()
    expect(s).toContain('dealerRead.evidence.freshness')
    expect(s).toContain('Feed age')
    expect(s).toContain('Evidence and model limits')
  })

  it('shows the chain evidence and names missing model inputs', () => {
    const s = src()
    expect(s).toContain('PressureDriftChart')
    expect(s).toContain('charmAllSkipped')
    expect(s).toContain('contracts excluded')
    expect(s).toContain('Those strikes are absent from the chart, not')
  })

  it('provides location and watch context without execution triggers', () => {
    const s = src()
    expect(s).toContain('dealerRead.position')
    expect(s).toContain('dealerRead.watch')
    expect(s).toContain('Walls describe option positioning levels')
    expect(s).not.toContain('IF / THEN LEVEL WATCH &amp; EXECUTION TRIGGERS')
  })

  it('includes major liquid ETF quick chips in the command bar', () => {
    const s = src()
    expect(s).toContain('SPY')
    expect(s).toContain('QQQ')
    expect(s).toContain('IWM')
    expect(s).toContain('DIA')
    expect(s).toContain('XLF')
    expect(s).toContain('XLE')
  })
})
