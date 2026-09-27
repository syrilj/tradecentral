/**
 * Vanna tab (delta–vol coupling · FOMC) — registration + contract gate.
 *
 * Mirrors the pressure-drift-chart / macro-view pattern: pure helpers are
 * exercised against the exact /api/vanna payload contract, and the shipped
 * SFC source is gated on the properties that matter — honest empty state,
 * pivot marker, phase badge — plus token hygiene (no hardcoded palette).
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  vannaDirectionCopy,
  vannaDirectionLabel,
  vannaDominantExpiry,
  vannaPhaseLabel,
  vannaPhaseTone,
  type VannaPayload,
} from '@/api'
import { linearScale, niceTicks } from '@/charts'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

/** The exact backend contract, FOMC-week shape (2 days out, pivot present). */
function fixture(): VannaPayload {
  return {
    symbol: 'SPY',
    asof: '2026-09-14T14:30:00Z',
    spot: 662.4,
    vanna_summary: {
      net_vanna_flow: 12_400_000,
      call_vanna_flow: 31_200_000,
      put_vanna_flow: -18_800_000,
      direction: 'iv_up_supportive',
      source: 'black_scholes_vanna',
      contracts_skipped: 3,
    },
    by_strike: [
      {
        strike: 640,
        call_vanna_flow: 2_100_000,
        put_vanna_flow: -5_400_000,
        net_vanna_flow: -3_300_000,
      },
      {
        strike: 650,
        call_vanna_flow: 4_800_000,
        put_vanna_flow: -4_100_000,
        net_vanna_flow: 700_000,
      },
      {
        strike: 660,
        call_vanna_flow: 9_600_000,
        put_vanna_flow: -2_200_000,
        net_vanna_flow: 7_400_000,
      },
      {
        strike: 670,
        call_vanna_flow: 8_300_000,
        put_vanna_flow: -1_100_000,
        net_vanna_flow: 7_200_000,
      },
      {
        strike: 680,
        call_vanna_flow: 6_400_000,
        put_vanna_flow: -900_000,
        net_vanna_flow: 5_500_000,
      },
    ],
    by_expiry: [
      {
        expiry: '2026-09-18',
        dte: 4,
        call_vanna_flow: 18_900_000,
        put_vanna_flow: -9_600_000,
        net_vanna_flow: 9_300_000,
      },
      {
        expiry: '2026-09-25',
        dte: 11,
        call_vanna_flow: 7_200_000,
        put_vanna_flow: -4_900_000,
        net_vanna_flow: 2_300_000,
      },
      {
        expiry: '2026-10-16',
        dte: 32,
        call_vanna_flow: 5_100_000,
        put_vanna_flow: -4_300_000,
        net_vanna_flow: 800_000,
      },
    ],
    vanna_pivot: 648.5,
    event_context: {
      next_fomc: '2026-09-16',
      days_to_fomc: 2,
      is_fomc_day: false,
      is_fomc_week: true,
      last_fomc: '2026-07-29',
      days_since_fomc: 47,
      phase: 'pre_fomc',
      note: 'FOMC in 2d — front-expiry vanna load peaks into the announcement.',
    },
  }
}

describe('Vanna tab registration', () => {
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')
  const apiSrc = source('api.ts')
  const iconSrc = source('components/AppIcon.vue')

  it('registers a dedicated /vanna route backed by VannaView', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/vanna['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]vanna['"]/)
    expect(routerSrc).toContain("import('@/views/VannaView.vue')")
    expect(routerSrc).toMatch(/title:\s*['"]Vanna['"]/)
  })

  it('nav registry contains vanna as a tab with the FOMC hint and an existing glyph', () => {
    const primary = appSrc.match(/const primaryNav = \[\s*([\s\S]*?)\] as const/)?.[1] ?? ''
    expect(primary).toContain("name: 'vanna'")
    expect(primary).toContain("title: 'Vanna'")
    expect(primary).toContain("hint: 'Delta–vol coupling · FOMC'")
    expect(primary).toContain('tab: true')
    const icon = primary.match(/name: 'vanna'[\s\S]*?icon: '([a-z-]+)'/)?.[1]
    expect(icon).toBeTruthy()
    expect(iconSrc).toContain(`name === '${icon}'`)
    // Vanna appears exactly once across every nav block (no duplicate destinations).
    expect([...appSrc.matchAll(/name:\s*'vanna'/g)]).toHaveLength(1)
  })

  it('adds one typed fetch to the api client', () => {
    expect(apiSrc).toMatch(/vanna:\s*\(symbol: string\)/)
    expect(apiSrc).toContain(
      '`/api/vanna?symbol=${encodeURIComponent(symbol.trim().toUpperCase())}`',
    )
    expect(apiSrc).toContain('export interface VannaPayload')
    expect(apiSrc).toContain('export interface VannaEventContext')
  })
})

describe('Vanna view-model helpers against the contract fixture', () => {
  const v = fixture()

  it('phase badge reads PRE-FOMC 2D and the hot tone drives the accent border', () => {
    expect(vannaPhaseLabel(v.event_context)).toBe('PRE-FOMC 2D')
    expect(vannaPhaseTone(v.event_context)).toBe('hot')
  })

  it('phase badge covers fomc_today / post_fomc / baseline and null context', () => {
    const ctx = v.event_context!
    expect(vannaPhaseLabel({ ...ctx, phase: 'fomc_today', is_fomc_day: true })).toBe('FOMC TODAY')
    expect(vannaPhaseLabel({ ...ctx, phase: 'post_fomc' })).toBe('POST-FOMC')
    expect(vannaPhaseLabel({ ...ctx, phase: 'baseline' })).toBe('BASELINE')
    expect(vannaPhaseLabel(null)).toBe('—')
    expect(vannaPhaseTone({ ...ctx, phase: 'baseline' })).toBe('cool')
  })

  it('net-flow direction chip and its one-line mechanic are derived, not fabricated', () => {
    expect(vannaDirectionLabel(v.vanna_summary.direction)).toBe('IV-UP SUPPORTIVE')
    expect(vannaDirectionLabel('iv_up_pressuring')).toBe('IV-UP PRESSURING')
    expect(vannaDirectionLabel('neutral')).toBe('NEUTRAL')
    expect(vannaDirectionCopy(v.vanna_summary.direction)).toContain('vol crush')
    expect(vannaDirectionCopy('iv_up_pressuring')).toContain('vol-spiral')
    expect(vannaDirectionCopy('neutral')).toContain('cancel')
  })

  it('dominant expiry is the front-week load (largest |net vanna|)', () => {
    const dom = vannaDominantExpiry(v.by_expiry)
    expect(dom?.expiry).toBe('2026-09-18')
    expect(dom?.dte).toBe(4)
    expect(vannaDominantExpiry([])).toBeNull()
  })
})

describe('Vanna strike chart geometry (pure scales the SFC uses)', () => {
  it('symmetric domain keeps the zero midline true and monotone', () => {
    const m = 9_600_000
    const y = linearScale([-m, m], [250, 26])
    expect(y(0)).toBeCloseTo(138, 1)
    expect(y(m)).toBeLessThan(y(0))
    expect(y(-m)).toBeGreaterThan(y(0))
    const ticks = niceTicks(-m, m, 5)
    expect(ticks).toContain(0)
    expect(Math.min(...ticks)).toBeLessThan(0)
    expect(Math.max(...ticks)).toBeGreaterThan(0)
  })
})

describe('VannaView shipped source gates', () => {
  const view = source('views/VannaView.vue')

  it('renders the fixture fields: net flow, phase badge, pivot marker, skipped count', () => {
    expect(view).toContain('summary?.net_vanna_flow')
    expect(view).toContain('vannaPhaseLabel')
    expect(view).toContain('data-testid="vanna-pivot-marker"')
    expect(view).toContain('contracts_skipped')
    expect(view).toContain('v-if="skipped > 0"')
    expect(view).toContain('vannaDominantExpiry')
    expect(view).toContain('event.note')
  })

  it('renders an explicit chain-unavailable state and never placeholder numbers', () => {
    expect(view).toContain('chain unavailable')
    expect(view).toContain('unavailableReason')
    expect(view).not.toMatch(/not derivable/i)
    // No invented demo bars: no literal strike/flow figures in the SFC source.
    expect(view).not.toMatch(/\b(660|12\.4M|31\.2M)\b/)
  })

  it('uses instrument tokens only — no hardcoded palette, gradients, or glow', () => {
    expect(view).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
    expect(view).not.toContain('linear-gradient')
    expect(view).not.toContain('radial-gradient')
    expect(view).not.toContain('box-shadow')
    expect(view).not.toContain('text-shadow')
    expect(view).not.toContain('drop-shadow')
    expect(view).toContain('var(--call)')
    expect(view).toContain('var(--put)')
    expect(view).toContain('var(--warn)')
  })

  it('respects the 10px type floor and 28px hit floor', () => {
    expect(view).not.toMatch(/font-size:\s*(?:[0-9](?:\.\d+)?px)\b/)
    expect(view).toContain('var(--t-nano)')
    expect(view).toContain('var(--density-control-h)')
  })
})
