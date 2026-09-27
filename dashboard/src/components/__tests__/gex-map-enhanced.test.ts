import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

function readSrc(rel: string): string {
  return readFileSync(join(root, rel), 'utf8')
}

describe('Enhanced GEX Map Component Verification', () => {
  const gexSrc = readSrc('components/GammaExposureMap.vue')

  it('supports multi-view modes: winning side, dual bars, net profile, and cumulative GEX', () => {
    expect(gexSrc).toContain('viewMode')
    expect(gexSrc).toContain('WINNING SIDE')
    expect(gexSrc).toContain('DUAL BARS')
    expect(gexSrc).toContain('NET PROFILE')
    expect(gexSrc).toContain('CUMULATIVE')
    expect(gexSrc).toContain('cumulativeAreaPath')
    expect(gexSrc).toContain('cumulativeLinePath')
  })

  it('supports display layout formats: GRAPH, SPLIT, and TABLE', () => {
    expect(gexSrc).toContain('layoutMode')
    expect(gexSrc).toContain('GRAPH')
    expect(gexSrc).toContain('SPLIT')
    expect(gexSrc).toContain('TABLE')
    expect(gexSrc).toContain('gex-strike-table')
    expect(gexSrc).toContain('winner-pill')
  })

  it('supports strike range presets: ATM ±6%, NEAR ±12%, WIDE ±25%, ALL', () => {
    expect(gexSrc).toContain('ATM (±6%)')
    expect(gexSrc).toContain('NEAR (±12%)')
    expect(gexSrc).toContain('WIDE (±25%)')
    expect(gexSrc).toContain('ALL STRIKES')
  })

  it('provides analytical overlays: Net Trace & Gamma Regime Zones', () => {
    expect(gexSrc).toContain('NET TRACE')
    expect(gexSrc).toContain('netTracePath')
    expect(gexSrc).toContain('REGIMES')
    expect(gexSrc).toContain('regime-zones')
    expect(gexSrc).toContain('VOLATILITY AMPLIFIED')
    expect(gexSrc).toContain('VOLATILITY DAMPENED')
  })

  it('includes quick structural level jump chips', () => {
    expect(gexSrc).toContain('quick-levels')
    expect(gexSrc).toContain('jumpToLevel')
    expect(gexSrc).toContain('level-chip')
  })

  it('supports keyboard stepping with ArrowLeft / ArrowRight, Enter/Space, and Escape', () => {
    expect(gexSrc).toContain('ArrowLeft')
    expect(gexSrc).toContain('ArrowRight')
    expect(gexSrc).toContain('Escape')
    expect(gexSrc).toContain('@keydown.esc="clearLock"')
  })

  it('maintains strict instrument token compliance', () => {
    expect(gexSrc).not.toContain('#ef4444')
    expect(gexSrc).not.toContain('drop-shadow')
    expect(gexSrc).not.toContain('filter:')
  })

  it('omits level markers when spot or wall strikes are zero or non-positive', async () => {
    const { createSSRApp, h } = await import('vue')
    const { renderToString } = await import('vue/server-renderer')
    const GammaExposureMap = (await import('../GammaExposureMap.vue')).default

    const app = createSSRApp({
      render: () =>
        h(GammaExposureMap, {
          rows: [
            { strike: 100, call_gex_m: 5, put_gex_m: -2, net_gex_m: 3, call_oi: 500, put_oi: 200 },
            { strike: 110, call_gex_m: 8, put_gex_m: -1, net_gex_m: 7, call_oi: 800, put_oi: 100 },
          ],
          spot: 0, // Zero spot
          callWall: null,
          putWall: 0, // Zero put wall
          gammaFlip: -10, // Negative flip
        }),
    })

    const html = await renderToString(app)
    expect(html).not.toContain('SPOT $0')
    expect(html).not.toContain('PUT W $0')
    expect(html).not.toContain('FLIP $-10')
  })
})
