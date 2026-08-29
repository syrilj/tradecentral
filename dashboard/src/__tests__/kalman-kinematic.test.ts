import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { StateEstimationPoint } from '@/microstructureContracts'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('KalmanKinematicPhasePlot component and math logic', () => {
  const plotSrc = source('components/KalmanKinematicPhasePlot.vue')

  it('declares props and svg path generation for 2-state kinematic Kalman velocity', () => {
    expect(plotSrc).toContain('points: StateEstimationPoint[]')
    expect(plotSrc).toContain('breakoutZ')
    expect(plotSrc).toContain('exhaustionZ')
    expect(plotSrc).toContain('velocityPath')
    expect(plotSrc).toContain('velocity-svg')
  })

  it('declares momentum exhaustion and kinematic acceleration state badges', () => {
    expect(plotSrc).toContain('KINEMATIC ACCELERATION')
    expect(plotSrc).toContain('MOMENTUM EXHAUSTION')
    expect(plotSrc).toContain('STABLE TRAJECTORY')
    expect(plotSrc).toContain('LATENT EQUILIBRIUM PRICE')
    expect(plotSrc).toContain('INSTANTANEOUS VELOCITY')
  })

  it('correctly handles state points', () => {
    const pt: StateEstimationPoint = {
      t: '2026-08-28T09:30:00Z',
      price: 500.0,
      nw_mean: 500.0,
      nw_upper: 504.0,
      nw_lower: 496.0,
      nw_sigma: 2.0,
      nw_bandwidth: 20.0,
      ou_half_life: 15.0,
      kalman_price: 500.0,
      kalman_velocity: 0.25,
      kalman_zscore: 2.1,
      kalman_q: 0.001,
      innovation_var: 1.0,
      exhaustion: false,
      breakout: true,
    }

    expect(pt.breakout).toBe(true)
    expect(pt.kalman_zscore).toBeGreaterThan(1.6)
  })
})
