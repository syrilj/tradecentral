import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Kalman tab (constant-velocity trend)', () => {
  const view = source('views/KalmanView.vue')
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')
  const apiSrc = source('api.ts')
  const iconSrc = source('components/AppIcon.vue')

  it('registers the /kalman route, research-group nav entry and icon', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/kalman['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]kalman['"]/)
    expect(appSrc).toMatch(/name:\s*['"]kalman['"]/)
    expect(appSrc).toMatch(/title:\s*['"]Kalman['"]/)
    expect(iconSrc).toContain("name === 'kalman'")
  })

  it('types the /api/kalman-trend payload and passes every filter parameter', () => {
    expect(apiSrc).toContain('export interface KalmanTrendPayload')
    expect(apiSrc).toContain('export interface KalmanParams')
    expect(apiSrc).toContain('export interface KalmanTrade')
    expect(apiSrc).toContain('/api/kalman-trend?')
    for (const param of ['window', 'q', 'entry_z', 'exit_z', 'noise_days', 'allow_short', 'bars']) {
      expect(apiSrc).toContain(`q.set('${param}'`)
    }
  })

  it('renders the velocity and the velocity-over-noise panes, not just price', () => {
    expect(view).toContain('Filtered velocity')
    expect(view).toContain('Slope / noise')
    expect(view).toContain('scoreChart')
    expect(view).toContain('slopeChart')
  })

  it('shows the traded thresholds on the score pane without clipping the tails', () => {
    expect(view).toContain('thr entry')
    expect(view).toContain('thr exit')
    // asinh keeps entry_z readable when the score runs into the hundreds; a
    // linear domain would collapse the thresholds onto the zero line.
    expect(view).toContain('Math.asinh')
    expect(view).toContain('asinh axis')
    expect(view).not.toContain('clipped at')
  })

  it('surfaces the payload caveat rather than presenting the run as a track record', () => {
    expect(view).toContain('d.caveat')
    expect(view).toContain('no costs')
    expect(view).toContain('Reconstructed round trips')
  })

  it('flags a position that was still open when the data ran out', () => {
    expect(view).toContain('forced_exit')
    expect(view).toContain('still on at last bar')
  })

  it('never paints the previous symbol under a new ticker', () => {
    expect(view).toContain('payloadMatches')
    expect(view).toMatch(/detail\.data\.value\.symbol === symbol\.value/)
  })
})
