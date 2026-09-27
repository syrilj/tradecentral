/** Landing-page visual contract: authored/computed proof, not generated banners. */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const testDir = dirname(fileURLToPath(import.meta.url))
const dashboardRoot = join(testDir, '..', '..')
const landingViewPath = join(dashboardRoot, 'src', 'views', 'LandingView.vue')

describe('Landing Page Visual Contract', () => {
  it('does not ship generated dashboard banners or image-only showcases', () => {
    const src = readFileSync(landingViewPath, 'utf8')
    for (const name of [
      'hero-workstation',
      'flow-gex-showcase',
      'regime-magnets',
      'research-governance',
      'options-workbench',
    ]) {
      expect(src).not.toContain(name)
    }
    expect(src).not.toContain('ticker-tape')
  })

  it('keeps product proof in authored interactive visuals', () => {
    const src = readFileSync(landingViewPath, 'utf8')
    expect(src).toContain('GexFlowVisual')
    expect(src).toContain('McLiveHero')
  })

  it('keeps the hero and flow proof interactive without image toggles', () => {
    const src = readFileSync(landingViewPath, 'utf8')
    expect(src).toContain('heroViewMode')
    expect(src).toContain("heroViewMode === 'mc'")
    expect(src).toContain("heroViewMode === 'workstation'")
    expect(src).toContain('GexFlowVisual')
  })

  it('keeps the public navigation focused on the buyer journey', () => {
    const src = readFileSync(landingViewPath, 'utf8')
    expect(src).toContain('href="#product"')
    expect(src).toContain('href="#flow"')
    expect(src).toContain('href="#method"')
    expect(src).not.toContain('href="#workstation"')
    expect(src).not.toContain('href="#regimes"')
  })

  it('preserves all strict product and copyright safety boundaries', () => {
    const src = readFileSync(landingViewPath, 'utf8')
    // No forbidden claim terms
    expect(src).not.toContain('actionable insight')
    expect(src).not.toContain('INSTITUTIONAL-GRADE')
    expect(src).not.toContain('Smart Money')
    expect(src).not.toContain('guaranteed returns')
    // No prohibited third-party broker or exchange logos
    expect(src.toLowerCase()).not.toContain('robinhood')
    expect(src.toLowerCase()).not.toContain('interactive brokers')
    expect(src.toLowerCase()).not.toContain('bloomberg')
    expect(src.toLowerCase()).not.toContain('tradingview')
  })
})
