import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Supply Chain & Thematic Beneficiaries Workspace', () => {
  const chainView = source('views/ChainView.vue')
  const banner = source('components/ThematicBanner.vue')
  const graph = source('components/ValueChainGraph.vue')
  const table = source('components/BeneficiaryTable.vue')
  const drawer = source('components/EvidenceDrawer.vue')
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')

  it('registers /chain route and primary navigation tab', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/chain['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]chain['"]/)
    expect(appSrc).toMatch(/name:\s*['"]chain['"]/)
    expect(appSrc).toMatch(/title:\s*['"]Chain['"]/)
  })

  it('ChainView connects components and API resources', () => {
    expect(chainView).toContain('ThematicBanner')
    expect(chainView).toContain('ValueChainGraph')
    expect(chainView).toContain('BeneficiaryTable')
    expect(chainView).toContain('EvidenceDrawer')
    expect(chainView).toMatch(/api\.supplyChain/)
    expect(chainView).toMatch(/api\.supplyChainThemes/)
    expect(chainView).toContain('mode-toggle-group')
    expect(chainView).toContain('Dedicated Chain')
    expect(chainView).toContain('Thematic Intertwine')
    expect(chainView).toContain('thematic-bridges-strip')
  })

  it('ThematicBanner displays narrative and timeline', () => {
    expect(banner).toContain('CAPEX & DEMAND CASCADE')
    expect(banner).toContain('Upcoming Catalyst Milestones')
    expect(banner).toContain('select-theme')
    expect(banner).toContain('select-ticker')
  })

  it('ValueChainGraph implements multi-tier deterministic SVG layout', () => {
    expect(graph).toContain('Tier 2: Materials & Metrology')
    expect(graph).toContain('Tier 1: Optics, Memory, Cooling')
    expect(graph).toContain('Core Driver & Infrastructure')
    expect(graph).toContain('Downstream Cloud & Enterprise')
    expect(graph).toContain('chain-edge')
    expect(graph).toContain('node-card')
    expect(graph).toContain('arrow-supply')
    expect(graph).toContain('arrow-demand')
    expect(graph).toContain('relationship-legend')
    expect(graph).toContain('floating-edge-pill')
  })

  it('BeneficiaryTable provides filtering and elasticity ranking', () => {
    expect(table).toContain('ELASTICITY SCORE')
    expect(table).toContain('CAPEX SENS.')
    expect(table).toContain('REV CONC. %')
    expect(table).toContain('FWD P/E')
    expect(table).toContain('CITATIONS')
    expect(table).toContain('Optics & Lasers')
    expect(table).toContain('Liquid Cooling')
  })

  it('EvidenceDrawer displays verbatim transcript quotes and SEC citations', () => {
    expect(drawer).toContain('VERBATIM TRANSCRIPT & FILING CITATIONS')
    expect(drawer).toContain('ELASTICITY SCORE')
    expect(drawer).toContain('CAPEX SENSITIVITY')
    expect(drawer).toContain('quote-body')
  })
})
