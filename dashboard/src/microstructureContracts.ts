/**
 * TypeScript contract interfaces for Microstructure Regime Dynamics,
 * State-Space Filtering, Causal Envelopes, and Systematic Execution.
 */

export interface StrikeExposure {
  strike: number
  call_oi: number
  put_oi: number
  call_volume: number
  put_volume: number
  call_iv: number | null
  put_iv: number | null
  call_gamma: number
  put_gamma: number
  call_gex_m: number
  put_gex_m: number
  net_gex_m: number
  call_vex_m: number
  put_vex_m: number
  net_vex_m: number
  call_chex_m: number
  put_chex_m: number
  net_chex_m: number
  speed_m: number
  zomma_m: number
}

export interface TopographyState {
  quadrant:
    | 'forward_positive_ramp'
    | 'backward_positive_ramp'
    | 'forward_negative_slide'
    | 'backward_negative_slide'
    | 'transition_zone'
  title: string
  description: string
  dealer_hedging_action: string
  expected_market_behavior: string
  gex_above_spot_m: number
  gex_below_spot_m: number
  gex_ratio: number
  call_wall: number
  put_wall: number
  gamma_flip: number
  volatility_trigger: number
  absolute_gamma_peak: number
}

export interface SyntheticGexPoint {
  spot: number
  net_gex_m: number
}

export interface MicrostructureRegimeSnapshot {
  symbol: string
  spot: number
  asof: string
  regime: 'positive_gamma' | 'negative_gamma' | 'neutral_transition'
  regime_confidence: number
  net_gex_m: number
  call_gex_m: number
  put_gex_m: number
  net_vex_m: number
  net_chex_m: number
  hedging_flow_m: number
  zero_dte_charm_drift_m: number
  gamma_flip: number
  call_wall: number
  put_wall: number
  volatility_trigger: number
  absolute_gamma_peak: number
  topography: TopographyState
  strikes: StrikeExposure[]
  synthetic_gex_profile: SyntheticGexPoint[]
  notes: string[]
}

export interface StateEstimationPoint {
  t: string
  price: number
  nw_mean: number
  nw_upper: number
  nw_lower: number
  nw_sigma: number
  nw_bandwidth: number
  ou_half_life: number
  kalman_price: number
  kalman_velocity: number
  kalman_zscore: number
  kalman_q: number
  innovation_var: number
  exhaustion: boolean
  breakout: boolean
}

export interface StateEstimationPayload {
  symbol: string
  window: string
  n_bars: number
  params: {
    h: number
    alpha: number
    q: number
    sigma_r: number
  }
  points: StateEstimationPoint[]
  generated_at: string
}

export interface AnchoredVwapPoint {
  t: string
  vwap: number
  upper_1sd: number
  lower_1sd: number
  upper_2sd: number
  lower_2sd: number
}

export interface AnchoredVwapSeries {
  anchor_name: string
  anchor_index: number
  series: AnchoredVwapPoint[]
}

export interface AnchoredVwapPayload {
  symbol: string
  window: string
  n_bars: number
  anchors: AnchoredVwapSeries[]
  generated_at: string
}

export interface ExecutionSignal {
  bar_index: number
  timestamp: string
  symbol: string
  action: 'ENTER_LONG' | 'ENTER_SHORT' | 'EXIT_LONG' | 'EXIT_SHORT' | 'HOLD' | 'NONE'
  direction: 'long' | 'short' | 'flat'
  price: number
  regime: 'positive_gamma' | 'negative_gamma' | 'neutral_transition'
  topography_quadrant: string
  setup_name: string
  conviction: number
  suggested_size_pct: number
  entry_price: number
  stop_loss: number
  take_profit: number
  invalidation_anchor: string
  kalman_velocity: number
  kalman_zscore: number
  kernel_mean: number
  upper_envelope: number
  lower_envelope: number
  anchored_vwap: number
  call_wall: number
  put_wall: number
  gamma_flip: number
  notes: string[]
}

export interface SystematicSignalsPayload {
  symbol: string
  window: string
  n_bars: number
  latest_signal: ExecutionSignal | null
  active_signals_count: number
  signals: ExecutionSignal[]
  generated_at: string
}

export interface SimulatedTrade {
  trade_id: number
  symbol: string
  direction: 'long' | 'short'
  regime: string
  setup_name: string
  entry_bar: number
  entry_time: string
  entry_price: number
  exit_bar: number | null
  exit_time: string | null
  exit_price: number | null
  exit_reason: string | null
  shares: number
  gross_pnl: number
  net_pnl: number
  return_pct: number
  holding_bars: number
  slippage_cost: number
  transaction_cost: number
  gamma_pnl_attribution: number
  delta_hedge_cost: number
}

export interface RegimeMetrics {
  regime_name: string
  n_trades: number
  win_rate: number
  profit_factor: number
  total_net_pnl: number
  avg_return_pct: number
  sharpe_ratio: number
}

export interface BacktestTearsheet {
  symbol: string
  n_bars: number
  start_date: string
  end_date: string
  initial_capital: number
  ending_capital: number
  total_net_pnl: number
  total_return_pct: number
  cagr_pct: number
  sharpe_ratio: number
  sortino_ratio: number
  calmar_ratio: number
  max_drawdown_pct: number
  max_drawdown_dollar: number
  win_rate: number
  profit_factor: number
  expectancy_per_trade: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  avg_win_dollar: number
  avg_loss_dollar: number
  win_loss_ratio: number
  avg_holding_bars: number
  total_slippage: number
  total_commissions: number
  total_gamma_pnl: number
  total_hedging_pnl: number
  daily_turnover_pct: number
  equity_curve: Array<{ bar: number; timestamp: string; equity: number; spot: number }>
  drawdown_curve: Array<{
    bar: number
    timestamp: string
    drawdown_pct: number
    drawdown_dollar: number
  }>
  trades: SimulatedTrade[]
  regime_breakdown: Record<string, RegimeMetrics>
}
