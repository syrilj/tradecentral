import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Live Stack tab (stacked-signals surface)', () => {
  const view = source('views/LiveStackView.vue')
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')
  const apiSrc = source('api.ts')
  const iconSrc = source('components/AppIcon.vue')

  it('registers the /livestack route and a Tools overflow entry', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/livestack['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]livestack['"]/)
    expect(appSrc).toMatch(/name:\s*['"]livestack['"]/)
    expect(appSrc).toMatch(/title:\s*['"]Live Stack['"]/)
    expect(iconSrc).toContain("name === 'stack'")
  })

  it('types the stacked_signals payload block', () => {
    expect(apiSrc).toContain('export interface StackedSignals')
    expect(apiSrc).toContain('ThetaVannaStrikeRow')
    expect(apiSrc).toContain('IvSurfaceSummary')
    expect(apiSrc).toContain('VolumeProfileBin')
    expect(apiSrc).toContain('ConfluenceCluster')
    expect(apiSrc).toMatch(/stacked_signals\?:\s*StackedSignals/)
  })

  it('stacks every lens on one page', () => {
    expect(view).toContain('WHAT THE DATA SAYS')
    expect(view).toContain('GammaExposureMap')
    expect(view).toContain('ThetaVannaChart')
    expect(view).toContain('IvSurfaceChart')
    expect(view).toContain('VolumeProfileChart')
    expect(view).toContain('LEVEL CONFLUENCE')
    expect(view).toContain('PRESSURE GAUGE')
  })

  it('polls live while the tab is open', () => {
    expect(view).toMatch(/REFRESH_MS = \d{2,}_000/)
    expect(view).toMatch(/intervalMs: REFRESH_MS/)
  })

  it('renders missing lenses as explicit unmeasured states, never fake zeros', () => {
    expect(view).toContain('No open-interest snapshot behind these numbers')
    expect(view).toContain('No usable IV quotes on this chain.')
    expect(view).toContain('Needs ≥5 priced sessions with volume')
    expect(view).toContain('No dated IV + open interest — theta/vanna unmeasured for this chain.')
  })

  it('keeps confluence descriptive and decision support only', () => {
    expect(view).toContain('confluence zones are descriptive geometry, not probabilities')
    expect(view).toContain('DECISION SUPPORT ONLY')
    // A level must be named by ≥2 lenses before it makes the ladder.
    expect(view).toMatch(/lens_count >= 2/)
  })
})
