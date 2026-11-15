/**
 * /live — one options decision. The four reads, the chart stance, and a
 * profile the pointer can drag. A missing chain stays blank.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import type { GammaStrikeRow } from '@/gammaResistance'
import { liveOptionsPath, priceGeometry, profileRows, stanceWord } from '@/liveOptions'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('/live registration', () => {
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')
  const apiSrc = source('api.ts')
  const iconSrc = source('components/AppIcon.vue')
  const paletteSrc = source('components/SearchPalette.vue')
  const viewSrc = source('views/LiveOptionsView.vue')

  it('registers /live on its own view and keeps the other screens', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/live['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]live-options['"]/)
    expect(routerSrc).toContain("import('@/views/LiveOptionsView.vue')")
    for (const path of ['/options', '/vanna', '/chain', '/calculator', '/drift', '/gamma']) {
      expect(routerSrc).toContain(`path: '${path}'`)
    }
  })

  it('adds one primary destination', () => {
    const primary = appSrc.match(/const primaryNav = \[\s*([\s\S]*?)\] as const/)?.[1] ?? ''
    expect(primary).toContain("name: 'live-options'")
    expect(primary).toContain("title: 'Live'")
    expect(primary).toContain("hint: 'One options decision'")
    expect(primary).toContain("icon: 'live'")
    expect(iconSrc).toContain("name === 'live'")
    expect(paletteSrc).toContain("{ name: 'live-options', title: 'Live'")
    expect([...appSrc.matchAll(/name:\s*'live-options'/g)]).toHaveLength(1)
  })

  it('fetches /api/live-options and does not authorize an order', () => {
    expect(apiSrc).toContain('liveOptions:')
    expect(apiSrc).toContain('liveOptionsPath(symbol, maxDte)')
    expect(liveOptionsPath('spy', 30)).toBe('/api/live-options?symbol=SPY&max_dte=30')
    expect(viewSrc).toContain('This read does not route an order.')
    expect(viewSrc).not.toContain('placeOrder')
    expect(viewSrc).not.toContain('routeOrder')
  })

  it('shows the four reads, the stance, the profile, and a blank chain', () => {
    expect(viewSrc).toContain('data-testid="live-symbol"')
    expect(viewSrc).toContain('data-testid="live-error"')
    expect(viewSrc).toContain('data-testid="live-empty"')
    expect(viewSrc).toContain('data-testid="live-stance"')
    expect(viewSrc).toContain('data-testid="live-profile"')
    expect(viewSrc).toContain('data-testid="live-chart-missing"')
    expect(viewSrc).toContain('GammaExposureMap')
    expect(viewSrc).toContain('Missing inputs stay blank')
    expect(viewSrc).not.toContain('ValueChainGraph')
    expect(viewSrc).not.toContain('PressureDriftChart')
    expect(viewSrc).not.toContain('VannaView')
  })
})

describe('panel drawing', () => {
  it('names the three stances and leaves a missing stance blank', () => {
    expect(stanceWord('agrees')).toBe('Agrees')
    expect(stanceWord('opposite')).toBe('Opposite')
    expect(stanceWord('stretched')).toBe('Stretched')
    expect(stanceWord(null)).toBe('—')
  })

  it('drops a strike with a missing greek instead of drawing zero', () => {
    const rows: GammaStrikeRow[] = [
      {
        strike: 100,
        call_gex_m: 1.2,
        put_gex_m: -0.4,
        net_gex_m: 0.8,
        abs_gex_m: 1.6,
        call_oi: 10,
        put_oi: 4,
      },
      {
        strike: 105,
        call_gex_m: Number.NaN,
        put_gex_m: -1,
        net_gex_m: -1,
        abs_gex_m: 1,
        call_oi: 1,
        put_oi: 1,
      },
    ]
    expect(profileRows(rows)).toEqual([
      {
        strike: 100,
        call_gex_m: 1.2,
        put_gex_m: -0.4,
        net_gex_m: 0.8,
        call_oi: 10,
        put_oi: 4,
      },
    ])
  })

  it('draws a rising close higher on the right and skips a one-point chart', () => {
    expect(priceGeometry([10], [11], 640, 88)).toBeNull()
    const geometry = priceGeometry([100, 101, 102, 104], [103], 640, 88)
    expect(geometry).not.toBeNull()
    const points = geometry?.line.match(/[\d.]+ [\d.]+/g) ?? []
    expect(points.length).toBe(4)
    const firstY = Number(points[0]?.split(' ')[1])
    const lastY = Number(points[3]?.split(' ')[1])
    expect(Number.isNaN(firstY)).toBe(false)
    expect(Number.isNaN(lastY)).toBe(false)
    expect(lastY).toBeLessThan(firstY)
  })
})
