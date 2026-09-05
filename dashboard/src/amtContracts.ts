/**
 * TypeScript contracts for the Auction Market Theory (AMT) workspace.
 *
 * Shape mirrors the backend engine at `research/amt_engine.py`, served at
 * GET /api/amt/analyze, /api/amt/health, /api/amt/playbook. The Python side
 * is wired in parallel by another agent — this file is the wire contract
 * between the two. Every nullable backend field is typed `| null` here;
 * a mistyped field silently discards real data rather than rendering it, so
 * treat a mismatch against the documented response shape as a bug, not a
 * cosmetic detail.
 */

/** Proof of which timeframe actually served the read, and why it differs
 * from what was requested (a coarser series substituted for a thin one). */
export interface AmtBarsMeta {
  timeframe_requested: string
  timeframe_normalized: string
  timeframe_served: string
  timeframe_label: string | null
  downgraded: boolean
  downgrade_reason: string | null
  bar_count: number
  first_bar: string | null
  last_bar: string | null
  source: string | null
  /** Set when the served timeframe was resampled up from a finer one. */
  resampled_from: string | null
  available?: boolean
}

/** `available: false` — nothing else on the payload is meaningful. Render
 * `reason` and stop; do not fall back to a previous symbol's numbers. */
export interface AmtAnalyzeFailure {
  available: false
  reason: string
  symbol: string | null
  timeframe: string
  bars_meta?: AmtBarsMeta
}

/** One horizontal bin of the volume/TPO profile. */
export interface AmtProfileBin {
  lo: number | null
  hi: number | null
  volume: number | null
  tpo: number
  in_value: boolean
  is_poc: boolean
}

export interface AmtCompositeProfile {
  basis: 'volume' | 'tpo' | string
  bin_width: number | null
  low: number | null
  high: number | null
  poc: number | null
  vah: number | null
  val: number | null
  va_width: number | null
  va_volume_share: number | null
  skew: number | null
  shape: 'p' | 'b' | 'd' | 'double_distribution' | string
  hvn: number[]
  lvn: number[]
  excess_high: boolean
  excess_low: boolean
  single_prints_top: number
  single_prints_bottom: number
  poor_high: boolean
  poor_low: boolean
  bars_at_high: number
  bars_at_low: number
  bar_count: number
  bins: AmtProfileBin[]
}

/** Same shape as `composite`, minus the drawable bins — a longer-lookback
 * context profile used for reference, not painted as a histogram. */
export type AmtContextProfile = Omit<AmtCompositeProfile, 'bins'>

export interface AmtBalanceWindow {
  start: string | null
  end: string | null
  sessions: number
  bars: number
  bar_index_start: number
  truncated: boolean
  reason: string | null
}

export interface AmtSession {
  start: string
  end: string
  bar_count: number
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  poc: number | null
  vah: number | null
  val: number | null
  shape: string
  rotation_factor: number
  overlap_prev: number | null
  poc_shift_atr: number | null
}

export interface AmtRegimeComponents {
  va_overlap: number | null
  containment: number | null
  chop_index: number | null
  efficiency: number | null
  rotation: number | null
}

export interface AmtRegimeWeights {
  va_overlap: number
  containment: number
  chop_index: number
  efficiency: number
  rotation: number
}

export interface AmtRegimeRaw {
  chop_index: number | null
  efficiency_ratio: number | null
  rotation_factor: number
  rotation_factor_max: number
  closes_inside_value: number
  recent_bars: number
  sessions_compared: number
}

/** BALANCE => fade the edges. IMBALANCE => do not fade. TRANSITION is the
 * honest middle read; UNKNOWN means the engine could not score it. */
export interface AmtRegime {
  label: 'BALANCE' | 'TRANSITION' | 'IMBALANCE' | 'UNKNOWN' | string
  score: number | null
  components: AmtRegimeComponents
  weights: AmtRegimeWeights
  raw: AmtRegimeRaw
}

export type AmtZone =
  | 'ABOVE_VALUE'
  | 'VAH_EDGE'
  | 'INSIDE_UPPER'
  | 'POC'
  | 'INSIDE_LOWER'
  | 'VAL_EDGE'
  | 'BELOW_VALUE'
  | string

export interface AmtLocation {
  close: number | null
  date: string | null
  zone: AmtZone
  edge_tolerance: number | null
  dist_to_poc_atr: number | null
  dist_to_vah_atr: number | null
  dist_to_val_atr: number | null
  closes_above_value: number
  closes_below_value: number
  acceptance: 'none' | 'above' | 'below' | string
  failed_auction: 'none' | 'look_above_fail' | 'look_below_fail' | string
  failed_auction_extreme: number | null
}

export interface AmtActivity {
  bars: number
  initiative_buying: number
  initiative_selling: number
  responsive_buying: number
  responsive_selling: number
  delta_proxy: number | null
  dominant: 'initiative' | 'responsive' | 'mixed' | string
}

/** The empirical, measured-on-this-symbol replacement for the folkloric
 * "80% rule". Rates are null (never a fabricated percentage) when the
 * sample of attempts is too small — see `note`. */
export interface AmtRotationStats {
  sessions: number
  sessions_in_balance: number
  val_attempts: number
  val_rotations: number
  val_rotation_rate: number | null
  vah_attempts: number
  vah_rotations: number
  vah_rotation_rate: number | null
  range_breaks_up: number
  range_breaks_down: number
  min_attempts_for_rate: number
  note: string
}

export type AmtEvidenceDirection = 'balance' | 'imbalance' | 'bullish' | 'bearish' | string

/** One signed line of the ledger behind the regime verdict and the lean. */
export interface AmtEvidenceItem {
  signal: string
  direction: AmtEvidenceDirection
  weight: number | null
  detail: string
}

export interface AmtDirectionalLean {
  label: 'bullish' | 'bearish' | 'neutral' | string
  bullish_weight: number | null
  bearish_weight: number | null
}

export interface AmtTradePlan {
  bias: 'LONG' | 'SHORT' | 'NEUTRAL / WAIT' | string
  setup: string
  entry: number | null
  stop: number | null
  target_1: number | null
  target_2: number | null
  risk_reward: number | null
  /** Why `risk_reward` is null — printed instead of the ratio, never in
   * place of a fabricated one. */
  risk_reward_unavailable_reason: string | null
  risk_per_unit: number | null
  invalidation: string
  rules_applied: string[]
}

export interface AmtPlaybookRule {
  rule: string
  detail: string
}

export interface AmtBar {
  date: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number | null
}

export interface AmtAnalyzeSuccess {
  available: true
  symbol: string
  timeframe: string
  as_of: string | null
  atr: number | null
  composite: AmtCompositeProfile
  context_profile: AmtContextProfile
  balance_window: AmtBalanceWindow
  sessions: AmtSession[]
  session_bars: number
  regime: AmtRegime
  location: AmtLocation
  activity: AmtActivity
  rotation_stats: AmtRotationStats
  evidence: AmtEvidenceItem[]
  directional_lean: AmtDirectionalLean
  trade_plan: AmtTradePlan
  narrative: string
  playbook: AmtPlaybookRule[]
  thresholds: Record<string, unknown>
  bars_meta: AmtBarsMeta
  bars: AmtBar[]
}

export type AmtAnalysisResult = AmtAnalyzeFailure | AmtAnalyzeSuccess

/* ------------------------------------------------------------- /api/amt/health */

/** One row of the timeframe support matrix. `available: false` rows MUST
 * render disabled with `reason` shown — never silently substituted. */
export interface AmtTimeframeOption {
  value: string
  label: string
  available: boolean
  symbols: number
  source?: string
  native?: boolean
  reason?: string | null
  fallback?: string
}

export interface AmtHealthPayload {
  symbol: string | null
  timeframes: AmtTimeframeOption[]
  data_sources: Record<string, number>
}

/* ----------------------------------------------------------- /api/amt/playbook */

export interface AmtPlaybookPayload {
  playbook: AmtPlaybookRule[]
  thresholds: Record<string, unknown>
}
