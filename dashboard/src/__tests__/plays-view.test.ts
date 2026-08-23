import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Plays of the Day workspace', () => {
  const view = source('views/PlaysView.vue')
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')
  const apiSrc = source('api.ts')

  it('registers /plays route and primary navigation tab', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/plays['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]plays['"]/)
    expect(appSrc).toMatch(/name:\s*['"]plays['"]/)
    expect(appSrc).toMatch(/title:\s*['"]Plays['"]/)
  })

  it('exposes the read-only latest run and the on-demand background job', () => {
    expect(apiSrc).toContain("plays: () => req<PlaysPayload>('/api/plays')")
    expect(apiSrc).toContain('/api/plays/run')
    expect(apiSrc).toContain('/api/plays/status')
  })

  it('renders the full decision funnel, not just ENTER tickets', () => {
    expect(view).toContain('Market Map')
    expect(view).toContain('Scan Funnel')
    expect(view).toContain('Validated Actionable Plays')
    expect(view).toContain('Watchlist')
    expect(view).toContain('Rejections')
    expect(view).toContain('Research Board')
    expect(view).toContain('Decision Blockers & Warnings')
  })

  it('surfaces scanner evidence on engine tickets', () => {
    expect(view).toContain('strategyLabel')
    expect(view).toContain('Reward / Risk')
    expect(view).toContain('chainFreshnessLabel')
    expect(view).toContain('legGreeksLabel')
    expect(view).toContain('CALL WALL')
    expect(view).toContain('PUT WALL')
    expect(view).toContain('MAX PAIN')
    expect(view).toContain('PCR VOL')
    expect(apiSrc).toContain('bounce_setups')
    expect(apiSrc).toContain('breakdown_setups')
    expect(apiSrc).toContain("engine?: string | null")
  })

  it('polls for fresh plays while the desk is open', () => {
    expect(view).toMatch(/REFRESH_INTERVAL_MS = \d{2,}_000/)
    expect(view).toMatch(/intervalMs: REFRESH_INTERVAL_MS/)
  })

  it('keeps the fail-closed NO PLAY state visible and honest', () => {
    expect(view).toContain('No live-validated actionable plays today.')
    expect(view).toContain('The pipeline is fail-closed')
    expect(view).toContain('NO PLAY')
  })

  it('never authorizes orders', () => {
    expect(view).toContain('SHADOW ONLY · NO ORDERS')
    expect(view).toContain('It never places or routes an order.')
  })
})
