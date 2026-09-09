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
  /** Dealer delta notional carried at this strike ($M), same sign convention
   *  as GEX. 0 on a payload produced before DEX existed. */
  call_dex_m: number
  put_dex_m: number
  net_dex_m: number
}

export interface TopographyState {
  quadrant:
    | 'forward_positive_ramp'
    | 'backward_positive_ramp'
    | 'forward_negative_slide'
    | 'backward_negative_slide'
    | 'transition_zone'
    /** No flip level could be located, so no quadrant is defined. */
    | 'unmeasurable'
  title: string
  description: string
  dealer_hedging_action: string
  expected_market_behavior: string
  gex_above_spot_m: number
  gex_below_spot_m: number
  gex_ratio: number
  call_wall: number | null
  put_wall: number | null
  gamma_flip: number | null
  volatility_trigger: number | null
  absolute_gamma_peak: number | null
}

/**
 * What the snapshot was measured from. Read this before rendering any
 * directional claim: `measurable: false` means the server withheld the read
 * rather than returning a neutral-looking one, and the UI must withhold too.
 */
export interface ChainQuality {
  measurable: boolean
  contracts: number
  strikes: number
  total_open_interest: number
  /** Strike-sides priced off the default IV because no IV was quoted. */
  iv_fallback_contracts: number
  flip_located: boolean
  dealer_convention: 'index' | 'equity'
  reason: string | null
}

/** One point on the gamma map: net dealer GEX ($M) if spot were here. */
export interface GexProfilePoint {
  spot: number
  net_gex_m: number
}

export interface MicrostructureRegimeSnapshot {
  symbol: string
  spot: number
  asof: string
  regime: 'positive_gamma' | 'negative_gamma' | 'neutral_transition' | 'unmeasurable'
  /** Scale-free strength of the regime call in [0, 1]. NOT a probability. */
  regime_strength: number
  /** Per-strike sum at spot: `call_gex_m + put_gex_m` equals this exactly. */
  net_gex_m: number
  call_gex_m: number
  put_gex_m: number
  /** The same quantity read off `gex_profile` at spot — the curve the flip and
   *  the gamma map are drawn from. Reported alongside `net_gex_m`, not instead
   *  of it, so the call/put split stays internally consistent; a material gap
   *  between the two is called out in `notes`. */
  net_gex_profile_m: number | null
  net_vex_m: number
  net_chex_m: number
  /** Aggregate dealer delta notional ($M). Positive means dealers are long
   *  delta and must sell into strength — overhead friction on a rally.
   *  Negative means they are short delta and buy strength, the condition
   *  behind a squeeze. Null (not 0) when the chain was not measurable: a
   *  balanced book is a real zero and must stay distinct from "not measured". */
  net_dex_m: number | null
  call_dex_m: number | null
  put_dex_m: number | null
  /** Null when the spot/IV velocities it needs were not measured. */
  hedging_flow_m: number | null
  zero_dte_charm_drift_m: number
  gamma_flip: number | null
  call_wall: number | null
  put_wall: number | null
  volatility_trigger: number | null
  absolute_gamma_peak: number | null
  quality: ChainQuality
  topography: TopographyState
  strikes: StrikeExposure[]
  /** The gamma map: net dealer GEX revalued across a grid of spots. */
  gex_profile: GexProfilePoint[]
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
  regime: 'positive_gamma' | 'negative_gamma' | 'neutral_transition' | 'gamma_unmeasured'
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
  /** Null when no dealer-gamma series backed this bar -- the engine no longer
   *  substitutes fixed percentages of the bar's own close. */
  call_wall: number | null
  put_wall: number | null
  gamma_flip: number | null
  /** One-bar 1-sigma move in dollars. Every stop and target on the ticket is a
   *  multiple of this, not of `sigma_local` (which is channel width, not risk). */
  risk_unit: number
  risk_unit_basis: 'implied_1bar' | 'atr' | 'close_to_close' | 'none'
  /** |target - entry| / |entry - stop| for the quoted plan. */
  risk_reward: number
  target_1r: number
  target_2r: number
  target_3r: number
  notes: string[]
}

export interface SystematicSignalsPayload {
  symbol: string
  window: string
  n_bars: number
  latest_signal: ExecutionSignal | null
  active_signals_count: number
  signals: ExecutionSignal[]
  /** False when no historical dealer-gamma snapshots backed these signals. */
  gamma_conditioned?: boolean
  basis?: string
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
  /** False when no historical dealer-gamma snapshots existed to condition on,
   *  which is currently always -- this stack stores no chain history. The UI
   *  must say so next to the Sharpe rather than implying the live model's
   *  gamma logic was what produced these numbers. */
  gamma_conditioned?: boolean
  basis?: string
}


/** Execution-side gates from `/api/execution-gate`: the clock, the expiry
 *  policy, today's opening range and the routed contract. Every section
 *  carries its own measurability -- an absent reading is never a permissive
 *  default. */
export interface ExecutionGatePayload {
  symbol: string
  endpoint: string
  asof: string
  spot?: number
  chain_source?: string
  session: {
    phase: string
    may_enter: boolean
    reason: string
    must_be_flat: boolean
    permitted_setups: string[]
    exchange_time: string
  }
  expiry_policy: {
    min_dte: number
    max_dte: number
    zero_dte_permitted: boolean
    rationale: string
  }
  initial_balance: {
    measurable: boolean
    high?: number | null
    low?: number | null
    width?: number | null
    bar_count?: number
    session_date?: string | null
    reason?: string | null
  }
  contract?: {
    measurable: boolean
    strike: number | null
    right: string | null
    expiry: string | null
    delta: number | null
    dte: number | null
    considered: number
    direction: string
    reason: string | null
    warnings: string[]
    spread: {
      measurable: boolean
      ratio_pct: number | null
      cap_pct: number
      passes: boolean
      mid: number | null
      reason: string | null
    } | null
  }
}
