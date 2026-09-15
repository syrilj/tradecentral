import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Vol Trend tab (volatility-targeted trend)', () => {
  const view = source('views/VolTrendView.vue')
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')
  const apiSrc = source('api.ts')
  const iconSrc = source('components/AppIcon.vue')

  it('registers the /voltrend route, primary navigation entry and icon', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/voltrend['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]voltrend['"]/)
    expect(appSrc).toMatch(/name:\s*['"]voltrend['"]/)
    expect(appSrc).toMatch(/title:\s*['"]Vol Trend['"]/)
    expect(appSrc).toMatch(/hint:\s*['"]Volatility-targeted trend['"]/)
    expect(iconSrc).toContain("name === 'voltrend'")
  })

  it('types the /api/vol-target-trend payload and passes every sizing parameter', () => {
    expect(apiSrc).toContain('export interface VolTargetTrendPayload')
    expect(apiSrc).toContain('export interface VolTargetParams')
    expect(apiSrc).toContain('export interface VolTargetTrade')
    expect(apiSrc).toContain('export interface VolTargetSeriesPoint')
    expect(apiSrc).toContain('export interface VolTargetStats')
    expect(apiSrc).toContain('/api/vol-target-trend?')
    for (const param of [
      'window',
      'target_vol',
      'lev_cap',
      'fast_days',
      'slow_days',
      'vol_days',
      'capital',
      'bars',
    ]) {
      expect(apiSrc).toContain(`q.set('${param}'`)
    }
  })

  it('renders all 3 distinct panes: price with EMAs, annualised vol vs target, and leverage sizing vs cap', () => {
    expect(view).toContain('priceChart')
    expect(view).toContain('volChart')
    expect(view).toContain('leverageChart')
    expect(view).toContain('Fast EMA')
    expect(view).toContain('Slow EMA')
    expect(view).toContain('Annualised realised volatility')
    expect(view).toContain('Dynamic entry leverage')
  })

  it('surfaces the payload caveat and in-sample reconstruction notice', () => {
    expect(view).toContain('d.caveat')
    expect(view).toContain('RECONSTRUCTED ROUND TRIPS')
    expect(view).toContain('no costs')
  })

  it('flags a position that was still open when the data ran out', () => {
    expect(view).toContain('forced_exit')
    expect(view).toContain('open at end of data')
    expect(view).toContain('forced-chip')
  })

  it('prevents cross-ticker contamination via payloadMatches guard', () => {
    expect(view).toContain('payloadMatches')
    expect(view).toMatch(/detail\.data\.value\.symbol === symbol\.value/)
  })

  it('renders trade table with sizing leverage and risk-targeted notional', () => {
    expect(view).toContain('Entry Px')
    expect(view).toContain('Exit Px')
    expect(view).toContain('Size (Qty)')
    expect(view).toContain('Notional')
    expect(view).toContain('Leverage')
    expect(view).toContain('Return')
    expect(view).toContain('P&L ($)')
  })

  it('provides persistent tracked stocks keeper board with real-time BUY / SELL signals', () => {
    expect(view).toContain('MY TRACKED STOCKS & SIGNALS')
    expect(view).toContain('addTrackedSymbol')
    expect(view).toContain('removeTrackedSymbol')
    expect(view).toContain('TRACKED_STORAGE_KEY')
    expect(view).toContain('QUICK_PRESETS')
    expect(view).toContain('Current Signal')
    expect(view).toContain('Signal Return')
    expect(apiSrc).toContain('volTargetSignals')
    expect(apiSrc).toContain('VolTargetSignalsPayload')
    expect(apiSrc).toContain('VolTargetSignalItem')
  })

  it('renders the Decision Blueprint hero card with definitive BUY / SELL recommendations', () => {
    expect(view).toContain('blueprint-card')
    expect(view).toContain('BUY / LONG SIGNAL')
    expect(view).toContain('SELL / CASH EXIT')
    expect(view).toContain('Order Action')
    expect(view).toContain('Recommended Size')
    expect(view).toContain('Target Leverage')
    expect(view).toContain('toggleTrackCurrent')
  })
})

