import { describe, expect, it } from 'vitest'
import type {
  MicrostructureRegimeSnapshot,
  TopographyState,
  ExecutionSignal,
} from '@/microstructureContracts'

describe('Microstructure Regime Dynamics contracts', () => {
  it('correctly validates a positive gamma microstructure regime snapshot', () => {
    const topo: TopographyState = {
      quadrant: 'forward_positive_ramp',
      title: 'Forward Positive Ramp',
      description: 'Large positive GEX stacked overhead',
      dealer_hedging_action: 'Dealers sell aggressively into rallies',
      expected_market_behavior: 'Mean-reverting grind',
      gex_above_spot_m: 120.5,
      gex_below_spot_m: 45.2,
      gex_ratio: 2.66,
      call_wall: 510,
      put_wall: 490,
      gamma_flip: 495,
      volatility_trigger: 505,
      absolute_gamma_peak: 500,
    }

    const snapshot: MicrostructureRegimeSnapshot = {
      symbol: 'SPY',
      spot: 502.5,
      asof: '2026-08-28T16:00:00Z',
      regime: 'positive_gamma',
      regime_confidence: 0.92,
      net_gex_m: 165.7,
      call_gex_m: 220.3,
      put_gex_m: -54.6,
      net_vex_m: -12.4,
      net_chex_m: 4.8,
      hedging_flow_m: 8.2,
      zero_dte_charm_drift_m: 3.5,
      gamma_flip: 495,
      call_wall: 510,
      put_wall: 490,
      volatility_trigger: 505,
      absolute_gamma_peak: 500,
      topography: topo,
      strikes: [],
      synthetic_gex_profile: [
        { spot: 490, net_gex_m: -10 },
        { spot: 500, net_gex_m: 165.7 },
      ],
      notes: ['Gamma flip at $495'],
    }

    expect(snapshot.symbol).toBe('SPY')
    expect(snapshot.regime).toBe('positive_gamma')
    expect(snapshot.spot).toBeGreaterThan(snapshot.gamma_flip)
    expect(snapshot.topography.quadrant).toBe('forward_positive_ramp')
    expect(snapshot.net_gex_m).toBeGreaterThan(0)
  })

  it('correctly models negative gamma breakout signal execution properties', () => {
    const signal: ExecutionSignal = {
      bar_index: 45,
      timestamp: '2026-08-28T14:30:00Z',
      symbol: 'SPY',
      action: 'ENTER_SHORT',
      direction: 'short',
      price: 488.5,
      regime: 'negative_gamma',
      topography_quadrant: 'forward_negative_slide',
      setup_name: 'NegGEX_PutWall_Cascade',
      conviction: 0.88,
      suggested_size_pct: 8.8,
      entry_price: 488.5,
      stop_loss: 492.0,
      take_profit: 480.0,
      invalidation_anchor: 'Spot re-crossing Gamma Flip $495',
      kalman_velocity: -0.25,
      kalman_zscore: -2.1,
      kernel_mean: 491.0,
      upper_envelope: 496.0,
      lower_envelope: 486.0,
      anchored_vwap: 492.5,
      call_wall: 510,
      put_wall: 490,
      gamma_flip: 495,
      notes: ['Negative GEX breakdown cascade'],
    }

    expect(signal.action).toBe('ENTER_SHORT')
    expect(signal.direction).toBe('short')
    expect(signal.kalman_zscore).toBeLessThan(-1.6)
    expect(signal.stop_loss).toBeGreaterThan(signal.entry_price)
    expect(signal.take_profit).toBeLessThan(signal.entry_price)
  })
})
