/**
 * Types for GET /api/liquidity/analyze and GET /api/liquidity/thresholds.
 *
 * Binding spec: docs/LIQUIDITY_TAB_CONTRACT.md §2. Every key below is spelled
 * exactly as the backend JSON (snake_case). A renamed field silently drops a
 * real number on the floor, so do not "tidy" these names.
 *
 * Stop pools are inferred from OHLCV price structure. Nothing here is an
 * observed order: there is no order-book, NBBO or tick data in this repo.
 */

export type LiquidityTimeframe = '1m' | '5m' | '15m' | '1h'
export type LiquidityRange = 'session' | '2d' | '5d' | '10d'

export type LiquidityBasis = 'inferred_from_structure'
export type LiquidityPoolSide = 'buy_stops' | 'sell_stops'
export type LiquidityPoolStatus = 'resting' | 'swept_reclaimed' | 'swept_accepted'
export type LiquiditySweepOutcome = 'reclaimed' | 'accepted' | 'pending'
export type LiquidityDirection = 'long' | 'short' | 'neutral'
export type LiquidityConfidenceBasis = 'counted_history' | 'structure_only'
export type LiquidityStopMethod = 'beyond_pool' | 'atr_fallback'
export type LiquidityProfileNode = 'hvn' | 'lvn' | 'normal'

/** Known pool source tags (§3 step 3). Left open: the engine may add more. */
export type LiquidityPoolSource =
  | 'swing_high'
  | 'swing_low'
  | 'equal_highs'
  | 'equal_lows'
  | 'prior_session_high'
  | 'prior_session_low'
  | 'opening_range_high'
  | 'opening_range_low'
  | 'value_area_high'
  | 'value_area_low'
  | 'round_number'
  | (string & {})

export interface LiquidityPrice {
  last: number | null
  ts: string | null
  /** "lse_candles" | "yahoo" | "disk_1h" */
  source: string | null
  stale_seconds: number | null
}

export interface LiquidityAtr {
  value: number | null
  period: number
}

export interface LiquidityProfileBin {
  price_lo: number
  price_hi: number
  price_mid: number
  volume: number
  share: number
  node: LiquidityProfileNode
}

export interface LiquidityProfile {
  range_start: string | null
  range_end: string | null
  bars_used: number
  method: 'bar_range_distribution' | (string & {})
  bin_size: number | null
  poc: number | null
  vah: number | null
  val: number | null
  bins: LiquidityProfileBin[]
  hvns: number[]
  lvns: number[]
}

export interface LiquidityDistance {
  abs: number | null
  atr: number | null
  pct: number | null
}

export interface LiquidityScoreComponents {
  confluence: number
  touches: number
  freshness: number
  proximity: number
  thin_path: number
}

export interface LiquidityPool {
  id: string
  /** buy_stops sit above price (short stops + breakout buys); sell_stops below. */
  side: LiquidityPoolSide
  level: number
  zone_lo: number
  zone_hi: number
  sources: LiquidityPoolSource[]
  touches: number
  first_seen: string | null
  last_tested: string | null
  untested_bars: number | null
  distance: LiquidityDistance
  thin_liquidity_between: boolean
  score: number
  score_components: LiquidityScoreComponents
  status: LiquidityPoolStatus
}

export interface LiquiditySweepForward {
  bars: number
  ret_atr: number | null
}

export interface LiquiditySweep {
  ts: string
  pool_id: string
  side: LiquidityPoolSide
  level: number
  extreme: number
  pierce_atr: number | null
  bars_to_reclaim: number | null
  volume_ratio: number | null
  outcome: LiquiditySweepOutcome
  /** null when not enough bars have closed after the sweep. */
  forward: LiquiditySweepForward | null
}

/**
 * Counted base rate. §2 says "null + reason if n < min_samples". The UI
 * accepts both shapes: the whole object null (reason on the watch row), or the
 * object present with `p_touch: null`, its `n` and a `reason`. A rate is only
 * ever rendered when both `p_touch` and `n` are non-null.
 */
export interface LiquidityBaseRate {
  p_touch: number | null
  within_bars: number | null
  n: number | null
  reason?: string | null
}

export interface LiquiditySweepWatch {
  pool_id: string
  side: LiquidityPoolSide
  distance_atr: number | null
  drivers: string[]
  base_rate: LiquidityBaseRate | null
  /** Why base_rate is null, when the engine nulls the whole object. */
  base_rate_reason?: string | null
  reason?: string | null
}

export interface LiquidityEvidence {
  signal: string
  direction: LiquidityDirection
  weight: number
  detail: string
}

export interface LiquidityBias {
  direction: LiquidityDirection
  confidence_basis: LiquidityConfidenceBasis
  evidence: LiquidityEvidence[]
  summary: string
}

export interface LiquidityStop {
  naive: number | null
  suggested: number | null
  beyond_pool_id: string | null
  risk_atr: number | null
  rationale: string
  method: LiquidityStopMethod
}

export interface LiquidityStops {
  long: LiquidityStop | null
  short: LiquidityStop | null
}

export interface LiquidityFollowThrough {
  rate: number | null
  n: number | null
  horizon_bars: number | null
  reason?: string | null
}

export interface LiquidityCalibration {
  source: 'symbol_history' | 'study_file' | null
  /** null + reason when n < min_samples (same two shapes as LiquidityBaseRate). */
  sweep_reclaim_follow_through: LiquidityFollowThrough | null
  sweep_reclaim_follow_through_reason?: string | null
  reason?: string | null
  notes: string | null
}

export interface LiquidityBar {
  ts: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number | null
}

/** Tunables echoed by the engine (LIQUIDITY_THRESHOLDS). */
export interface LiquidityThresholds {
  min_samples?: number
  eq_tol_atr?: number
  merge_atr?: number
  buffer_atr?: number
  max_pool_atr?: number
  min_pierce_atr?: number
  reclaim_bars?: number
  forward_bars?: number
  watch_atr?: number
  bias_recency_bars?: number
  bias_min_edge?: number
  stop_buffer_atr?: number
  max_stop_atr?: number
  [k: string]: unknown
}

export interface LiquidityAnalyzeSuccess {
  available: true
  reason: null
  symbol: string
  timeframe: LiquidityTimeframe | (string & {})
  generated_at: string
  basis: LiquidityBasis
  price: LiquidityPrice
  atr: LiquidityAtr
  profile: LiquidityProfile
  pools: LiquidityPool[]
  sweeps: LiquiditySweep[]
  sweep_watch: LiquiditySweepWatch[]
  bias: LiquidityBias
  stops: LiquidityStops
  calibration: LiquidityCalibration
  bars: LiquidityBar[]
  thresholds: LiquidityThresholds
}

/** Provider failure / empty bars: HTTP 200 with available:false and a reason. */
export interface LiquidityAnalyzeFailure {
  available: false
  reason: string | null
  symbol?: string
  timeframe?: string
  generated_at?: string
}

export type LiquidityAnalysisResult = LiquidityAnalyzeSuccess | LiquidityAnalyzeFailure

export interface LiquidityThresholdsPayload {
  thresholds: LiquidityThresholds
}

/** A true fixed-range profile: when both are present they override `range`. */
export interface LiquidityAnchors {
  anchor_start: string
  anchor_end: string
}
