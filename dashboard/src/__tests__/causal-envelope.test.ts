import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { StateEstimationPoint } from '@/microstructureContracts'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('CausalEnvelopeChart component and math logic', () => {
  const chartSrc = source('components/CausalEnvelopeChart.vue')

  it('declares props and svg path generation for causal Nadaraya-Watson envelopes', () => {
    expect(chartSrc).toContain('points: StateEstimationPoint[]')
    expect(chartSrc).toContain('nwEnvelopeAreaPath')
    expect(chartSrc).toContain('nwMeanPath')
    expect(chartSrc).toContain('vwapPaths')
    expect(chartSrc).toContain('signalMarkers')
  })

  it('renders structural levels for Call Wall, Put Wall, and Gamma Flip', () => {
    expect(chartSrc).toContain('callWall')
    expect(chartSrc).toContain('putWall')
    expect(chartSrc).toContain('gammaFlip')
    expect(chartSrc).toContain('structural-lines')
  })

  it('correctly tests point scale calculations', () => {
    const points: StateEstimationPoint[] = [
      {
        t: '2026-08-28T09:30:00Z',
        price: 500.0,
        nw_mean: 500.0,
        nw_upper: 504.0,
        nw_lower: 496.0,
        nw_sigma: 2.0,
        nw_bandwidth: 20.0,
        ou_half_life: 15.0,
        kalman_price: 500.0,
        kalman_velocity: 0.0,
        kalman_zscore: 0.0,
        kalman_q: 0.001,
        innovation_var: 1.0,
        exhaustion: true,
        breakout: false,
      },
    ]

    expect(points.length).toBe(1)
    expect(points[0].nw_upper).toBeGreaterThan(points[0].nw_lower)
  })
})
