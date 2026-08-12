/**
 * Typed client for edge/tools/api_server.py.
 *
 * Every call funnels through `req()` so a dead backend surfaces as a typed
 * error rather than an unhandled rejection. In a trading surface a silently
 * stale panel is worse than a visibly broken one, so callers are expected to
 * render the error, not swallow it.
 */

const BASE = import.meta.env.DEV ? '' : ''

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly endpoint: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { Accept: 'application/json' },
      ...init,
    })
  } catch (e) {
    throw new ApiError(
      `backend unreachable — is api_server.py running on :8787?`,
      0,
      path,
    )
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { error?: string }
      if (body?.error) detail = body.error
    } catch {
      /* non-JSON error body; keep statusText */
    }
    // Vite's proxy returns a bare 500 "Internal Server Error" when nothing is
    // listening on :8787. Surface a more actionable message on a trading desk.
    if (
      (res.status === 500 || res.status === 502 || res.status === 504) &&
      (!detail || detail === 'Internal Server Error' || detail === 'Bad Gateway')
    ) {
      detail = `API ${res.status} on ${path} — is edge/tools/api_server.py running on :8787?`
    }
    throw new ApiError(detail, res.status, path)
  }
  return (await res.json()) as T
}

/* ------------------------------------------------------------------ types */

export type Verdict = 'GO' | 'NO-GO' | 'UNKNOWN' | string

export interface VolReadout {
  VIX: number
  term_slope: number
  tail_risk: number
  date: string
}

export interface DirectionalSignal {
  symbol: string
  [k: string]: unknown
}

export interface PeadCandidate {
  symbol: string
  [k: string]: unknown
}

export interface LeaderboardRow {
  [k: string]: unknown
}

export type ScanDepth = 'quick' | 'deep'

export interface ScanSummary {
  depth: ScanDepth
  elapsed_seconds: number
  pead_universe_symbols: number
  pead_attempted_symbols: number
  pead_evaluated_symbols: number
  pead_qualified_symbols: number
  pead_unavailable_symbols: number
  pead_failed_symbols: number
  pead_confidence_kind: 'ordinal_score' | string
  pead_gate_verdict: Verdict
  directional_model_universe_symbols: number
  directional_attempted_symbols: number
  directional_scored_symbols: number
  directional_failed_symbols: number
  directional_warning_count: number
  signal_overlap_symbols?: number
  signal_agreement_symbols?: number
  signal_conflict_symbols?: number
  activity_market_universe_symbols: number
  activity_local_scanned_symbols: number
  activity_local_flagged_symbols: number
  activity_live_requested_symbols: number
  activity_live_completed_symbols: number
  activity_live_with_prints_symbols: number
  qlib_score_kind?: string
  qlib_source?: string
  qlib_attempted_symbols?: number
  qlib_scored_symbols?: number
  qlib_failed_symbols?: number
  qlib_priority_routed_symbols?: number
  qlib_asof?: string | null
  qlib_quality?: string
}

export type ScanJobState = 'queued' | 'running' | 'completed' | 'failed'

export interface ScanJobResult {
  status: 'ok'
  message: string
  asof?: string
  data: StatusPayload
}

export interface ScanJob {
  id: string
  depth: ScanDepth
  state: ScanJobState
  stage: string
  progress: number
  message: string
  started_at: string | null
  updated_at: string | null
  elapsed_seconds: number
  error: string | null
  result?: ScanJobResult
}

export interface ScanJobPayload {
  status: ScanJobState | 'idle' | 'missing'
  message: string
  job: ScanJob | null
}

export interface ActivityFlagRow {
  symbol: string
  activity_score: number
  score_kind: 'ordinal_activity'
  activity_rank: number
  flags: string[]
  context_side: 'long' | 'short' | 'mixed' | 'neutral' | string
  pead_side?: 'long' | 'short' | null
  pead_horizon?: 'session_open' | string | null
  directional_side?: 'long' | 'short' | null
  directional_horizon?: string | null
  signal_alignment?: 'agree' | 'conflict' | 'pead_only' | 'directional_only' | 'none' | string
  calibrated_probability: number | null
  live: boolean
  live_asof: string | null
  premium: number | null
  print_count: number
  call_print_count: number
  put_print_count: number
  contract_count?: number
  call_premium?: number | null
  put_premium?: number | null
  put_flow_pct?: number | null
  otm_premium?: number | null
  otm_flow_pct?: number | null
  average_otm_pct?: number | null
  sweep_count?: number
  sweep_contracts?: number
  sweep_premium?: number
  sweep_otm_contracts?: number
  sweep_otm_premium?: number
  unusual_contracts?: number
  average_price?: number | null
  average_dte?: number | null
  signed_print_count?: number
  ret_1d: number | null
  volume_vs_20d_median: number | null
  price_impulse: 'up' | 'down' | 'flat' | string
  sources: string[]
  decision_authorized: false
  note: string
  qlib_score?: number | null
  qlib_rank?: number | null
  qlib_score_kind?: string
  qlib_source?: string
  qlib_asof?: string | null
}

export interface ActivityScan {
  schema_version: string
  asof: string
  depth: ScanDepth
  rows: ActivityFlagRow[]
  qlib_scan?: {
    quality?: string
    score_kind?: string
    source?: string
    asof?: string | null
    coverage?: Record<string, number>
    warnings?: string[]
    decision_authorized?: boolean
    top_rows?: Array<Record<string, unknown>>
  }
  coverage: {
    market_universe: number
    local_requested: number
    local_scanned: number
    local_failed: number
    local_flagged: number
    local_asof: string | null
    live_requested: number
    live_completed: number
    live_with_activity: number
    qlib_attempted?: number
    qlib_scored?: number
    qlib_failed?: number
    qlib_priority_routed?: number
  }
  warnings: string[]
  decision_authorized: false
  score_kind: 'ordinal_activity'
  qlib_score_kind?: string
  caveats: string[]
}

/** Market-wide unusual options flow board (`/api/unusual-flow`). */
export interface UnusualFlowRow extends Omit<ActivityFlagRow, 'score_kind'> {
  score_kind: 'ordinal_unusual_flow' | string
  unusual_score?: number
  call_put_imbalance?: number | null
}

export interface UnusualFlowPayload {
  schema_version: string
  asof: string
  generated_at?: string
  rows: UnusualFlowRow[]
  tape?: MarketFlowPrint[]
  summary?: UnusualFlowSummary
  feed_status?: 'live' | 'no_prints' | 'unavailable' | string
  feed_reason?: string | null
  coverage: {
    market_universe: number
    local_scanned: number
    local_flagged: number
    live_requested: number
    live_completed: number
    live_with_activity: number
    unusual_shown: number
    provider_requests?: number
    provider_requests_completed?: number
    provider_prints?: number
    observed_symbols?: number
  }
  warnings: string[]
  notes?: string[]
  min_premium: number
  decision_authorized: false
  score_kind: 'ordinal_unusual_flow' | string
  source_snapshot?: 'market_flow' | string
  cache?: {
    hit?: boolean
    source?: string
    age_seconds?: number
    ttl_seconds?: number
    refresh_hint?: string
  }
  caveats: string[]
}

export interface UnusualFlowSummary {
  total_premium: number
  call_premium: number
  put_premium: number
  unclassified_premium: number
  put_flow_pct: number | null
  call_flow_pct: number | null
  total_contracts: number
  unusual_contracts: number | null
  sweep_contracts: number
  sweep_premium: number
  tape_print_count: number
  visible_tape_print_count?: number
  signed_print_count: number
  signed_print_pct: number | null
  tape_detail_available: boolean
  premium_basis: 'provider_contract_tape' | 'provider_symbol_aggregate' | string
  scope?: string
  qualified_symbol_count?: number
  visible_symbol_count?: number
}

export interface MarketFlowPrint extends OptionsTapeRow {
  symbol: string | null
  dte?: number | null
  otm_pct?: number | null
  open_interest?: number | null
  implied_volatility?: number | null
}

/** Genetic algorithm evolution lab (`/api/ga`). Research-only. */
export interface GaRunSummary {
  run_id: string
  created_at?: string | null
  n_generations?: number | null
  population_size?: number | null
  best_fitness?: number | null
  alive_final?: number | null
  n_elites?: number | null
  confirmation_passes?: number | null
  confirmation_total?: number | null
  n_symbols?: number | null
  decision_authorized?: boolean
  path?: string
}

export interface GaGenes {
  signal_family: string
  lookback: number
  entry_z: number
  exit_z: number
  horizon_days: number
  top_k: number
  long_short: string
  vol_window: number
  dollar_volume_min_rank: number
}

export interface GaGenome {
  id: string
  generation: number
  genes: GaGenes
  parent_ids?: string[]
  fitness?: number | null
  metrics?: Record<string, number | string | null>
  alive?: boolean
  death_reason?: string | null
}

export interface GaHistoryPoint {
  generation: number
  best_fitness: number
  mean_fitness: number
  median_fitness: number
  alive_count: number
  best_genome_id: string
  best_genes: GaGenes
}

export interface GaConfirmationRow {
  id: string
  fitness_in_sample?: number | null
  fitness_confirmation?: number | null
  alive_confirmation?: boolean
  death_reason?: string | null
  genes?: GaGenes
  metrics_in_sample?: Record<string, number | string | null>
  metrics_confirmation?: Record<string, number | string | null>
  passes_confirmation?: boolean
}

export interface GaRunDetail {
  schema_version?: string
  run_id: string
  created_at?: string
  decision_authorized?: boolean
  protocol?: Record<string, unknown>
  config?: Record<string, unknown>
  fitness_config?: Record<string, unknown>
  symbols?: string[]
  history?: GaHistoryPoint[]
  elites?: GaGenome[]
  confirmation?: GaConfirmationRow[]
  notes?: string[]
}

export interface GaPayload {
  schema_version: string
  runs_dir: string
  latest_run_id: string | null
  selected_run_id: string | null
  runs: GaRunSummary[]
  detail: GaRunDetail | null
  error: string | null
  decision_authorized: false
  notes: string[]
}

export interface StatusPayload {
  asof: string
  broad_universe_count: number
  market_universe_count: number
  searchable_symbol_count: number
  scan_summary: ScanSummary
  pead_candidates: PeadCandidate[]
  directional_signals: DirectionalSignal[]
  signal_reconciliation?: {
    schema_version: string
    counts: {
      pead_flags: number
      directional_forecasts: number
      overlap: number
      agreements: number
      conflicts: number
      pead_only: number
      directional_only: number
    }
    rows: Array<{
      symbol: string
      relation: 'agree' | 'conflict' | string
      pead_side: string
      pead_strength: number | null
      directional_side: string
      directional_probability: number | null
      directional_state: string | null
      directional_horizon: string | null
    }>
    decision_rule: string
    semantics: { pead: string; directional: string }
  }
  activity_scan: ActivityScan
  sector_flow: Record<string, unknown>
  latest_vol: VolReadout
  pead_metrics: Record<string, number | string | Record<string, boolean>>
  gcp_resources: Record<string, unknown>
  leaderboard: LeaderboardRow[]
}

export interface SearchHit {
  symbol: string
  kind?: 'symbol' | 'track'
  name?: string
  category?: string
  description?: string
  tier: 'wide' | 'core' | 'live'
  n_bars: number
  first_date: string
  last_date: string
}

export interface TrajectoryBar {
  d: string
  o: number
  h: number
  l: number
  c: number
  v: number
  ret: number
  cum: number
  dd: number
}

export interface TrajectoryStats {
  last_price: number
  chg_1d_pct: number
  chg_5d_pct: number
  chg_1m_pct: number
  chg_3m_pct: number
  chg_ytd_pct: number
  chg_window_pct: number
  ann_return_pct: number
  ann_vol_pct: number
  sharpe: number | null
  max_drawdown_pct: number
  calmar: number | null
  atr_20: number
  atr_pct: number
  adv_20_usd: number
  best_day_pct: number
  worst_day_pct: number
  pct_days_up: number
}

export interface QlibContext {
  symbol?: string
  qlib_score: number | null
  qlib_rank: number | null
  score_kind?: string
  source?: string
  asof?: string | null
  quality?: 'ok' | 'missing' | 'skipped' | string
  decision_authorized?: boolean
  features?: Record<string, number | null> | null
  warnings?: string[]
}

export interface Trajectory {
  symbol: string
  window: string
  n_bars: number
  first_date: string
  last_date: string
  source: string
  series: TrajectoryBar[]
  stats: TrajectoryStats
  factors: Record<string, number | null>
  /** Cross-sectional qlib research score shared with deep scan (ordinal only). */
  qlib?: QlibContext
  qlib_score?: number | null
  qlib_rank?: number | null
  qlib_score_kind?: string
  qlib_source?: string
  qlib_asof?: string | null
  qlib_quality?: string
}

export interface CompareStat extends Partial<TrajectoryStats> {
  /** Last observed market bar; never the request timestamp. */
  asof?: string | null
  age_days?: number | null
  quality?: 'current' | 'stale' | 'missing' | string
  source?: string | null
  change_basis?: 'last_two_observed_closes' | string
}

export interface ComparePayload {
  window: string
  asof?: string | null
  oldest_asof?: string | null
  generated_at?: string | null
  series: Record<string, { d: string; cum: number }[]>
  stats: Record<string, CompareStat>
  correlation: Record<string, Record<string, number>>
}

export interface Gate {
  id: string
  name: string
  verdict: Verdict
  source_file: string
  metrics: Record<string, number | string | null>
  checks: Record<string, boolean>
  updated: string | null
}

export interface Readiness {
  asof: string
  cleared_for_live: boolean
  blocking_reasons: string[]
  shadow: {
    n_sessions: number
    required: number
    latest_decision: unknown
    reliability: Record<string, unknown> | null
  }
  gates_summary: { go: number; no_go: number; unknown: number }
}

export interface Health {
  ok: boolean
  ts: string
  symbols_indexed: number
  uptime_s: number
}

export interface MarketClock {
  asof_utc: string
  exchange: 'XNYS' | string
  market_session: 'premarket' | 'regular' | 'after_hours' | 'closed' | 'replay'
  is_trading_day: boolean
  is_early_close: boolean
  regular_open_utc: string | null
  regular_close_utc: string | null
  next_regular_open_utc: string | null
  next_transition_utc: string | null
  next_transition:
    | 'premarket_opens'
    | 'regular_opens'
    | 'regular_closes'
    | 'after_hours_closes'
    | null
  calendar_source: string
  warning: string | null
}

export type OptionsMode = 'live' | 'history'
export type OptionsRange = '1d' | '5d' | '1m' | '3m'

export interface OptionsQuery {
  symbol: string
  mode?: OptionsMode
  range?: OptionsRange
  minPremium?: number
  minVolume?: number
  minOpenInterest?: number
  maxSpreadPct?: number
  minDte?: number
  maxDte?: number
  expiry?: 'nearest' | 'all' | string
  tapeLimit?: number
  dateFrom?: string
  dateTo?: string
}

export interface OptionsPricePoint {
  t: string
  close: number
}

export interface OptionsFlowPoint {
  t: string
  call_premium: number
  put_premium: number
  signed_net_premium: number | null
  signed_premium_observations: number
  print_count: number
  unresolved_premium: number
  activity_imbalance: number | null
  anomaly_count: number
  anomaly_premium: number
}

export interface OptionsTapeRow {
  timestamp: string
  right: 'call' | 'put'
  premium: number
  volume: number
  /** Contract count (= volume on options tape). */
  contracts?: number
  /** OCC contract multiplier when the provider supplies it; never assumed. */
  contract_multiplier?: number | null
  /** Per-contract fill price when known or back-solved from premium. */
  price?: number | null
  price_estimated?: boolean
  strike: number | null
  /** Underlying stock price when trade occurred or session spot. */
  underlying_price?: number | null
  expiry: string | null
  dte?: number | null
  otm_pct?: number | null
  open_interest?: number | null
  implied_volatility?: number | null
  aggressor: 'buy' | 'sell' | null
  /** BUY / SELL / NO SIDE — always set for display. */
  aggressor_label?: string
  signed_premium: number | null
  /** Directional lean when aggressor or vendor sentiment is known. */
  bias?: 'bullish' | 'bearish' | null
  bias_source?: 'aggressor' | 'vendor_sentiment' | 'none' | string
  /** Contract identity: call | put (always present). */
  activity_side?: 'call' | 'put' | string
  /** sweep | block | single (vendor tag or size/cluster heuristic). */
  trade_class?: 'sweep' | 'block' | 'single' | string
  trade_class_source?: 'vendor' | 'size_heuristic' | 'burst_heuristic' | 'unclassified' | string
  /** BULL / BEAR when signed; CALL / PUT activity when not. */
  edge_label?: string
  premium_estimated: boolean
  anomaly_flags: ('premium_outlier' | 'volume_outlier' | 'repeat_cluster' | 'sweep_burst' | string)[]
  anomaly_score: number
  premium_percentile: number
}

export interface OptionsExpiryContext {
  selection: string
  selected_expiry: string | null
  selected_dte: number | null
  snapshot_dte: number | null
  selection_asof: string
  available_expiries: { expiry: string; dte: number; snapshot_dte: number; contracts: number }[]
}

export interface GexHistoryPoint {
  t: string
  observed_at: string
  spot: number
  expiry: string | null
  contracts: number
  total_gex_m: number
  regime: 'positive' | 'negative' | 'neutral'
  gamma_flip: number | null
  call_wall: number | null
  put_wall: number | null
  pin_strike: number | null
}

export interface GexStrikeRow {
  strike: number
  call_gex_m: number
  put_gex_m: number
  net_gex_m: number
  call_oi: number
  put_oi: number
}

export interface OptionsProbability {
  available: boolean
  method: string
  expiry?: string
  horizon_days?: number
  atm_iv?: number
  expected_move?: number
  expected_low?: number
  expected_high?: number
  prob_above_call_wall?: number | null
  prob_below_put_wall?: number | null
  prob_between_walls?: number | null
}

export interface OptionsHistoryMeta {
  available_dates: string[]
  selected_asof: string | null
  last_good_asof: string | null
  auto_selected: boolean
}

export interface SqueezeFactor {
  id: string
  label: string
  score: number
  max: number
  detail: string
}

export interface SqueezeSetup {
  side: 'bullish' | 'bearish' | string
  score: number
  score_01: number
  likelihood: 'unlikely' | 'possible' | 'likely' | 'imminent' | string
  factors: SqueezeFactor[]
  setup_analysis: string[]
  for_stronger: string[]
  trading_implication: string
  spot: number
  wall: number | null
  wall_pct: number | null
}

export interface OptionsSignal {
  kind: 'volatility' | 'support' | 'resistance' | 'regime_flip' | string
  strength: 'STRONG' | 'MODERATE' | 'WEAK' | string
  title: string
  detail: string
  level: number | null
  level_pct: number | null
}

export interface OptionsSqueeze {
  bullish: number
  bearish: number
  /** Signed gex_core score in [-100, 100]. Positive = bullish squeeze. */
  score?: number
  label: string
  primary?: 'quiet' | 'two_way' | 'bullish' | 'bearish' | string
  drivers: string[]
  method?: string
  components?: Record<string, number>
  scored_components?: Record<string, number>
  long_gamma_dampened?: boolean
  negative_fuel?: number
  key_levels?: {
    spot: number
    call_wall: number | null
    call_wall_pct: number | null
    put_wall: number | null
    put_wall_pct: number | null
    gamma_flip: number | null
    gamma_flip_pct: number | null
    pin_strike: number | null
    near_spot_net_gex_m?: number
  }
  signals?: OptionsSignal[]
  bullish_setup?: SqueezeSetup
  bearish_setup?: SqueezeSetup
}

/** Why a symbol earned an expensive chain request. Ordinal unless noted. */
export type BoardSelectionBasis =
  | 'pead_ordinal'
  | 'live_options_flow'
  | 'activity_ordinal'
  | 'directional_model'

export interface OptionsBoardRow {
  symbol: string
  rank: number
  selection_basis: BoardSelectionBasis | string
  selection_basis_note: string
  selection_score: number | null
  /** `calibrated_probability` only for the frozen-domain model tier. */
  score_kind: 'ordinal_score' | 'ordinal_activity' | 'calibrated_probability' | string
  context_side: string | null
  sources: string[]
  decision_authorized: false
  available: boolean
  error?: string
  spot?: number | null
  squeeze_score?: number | null
  squeeze_label?: string | null
  squeeze_primary?: string | null
  structure_score?: number | null
  long_gamma_dampened?: boolean
  net_gex_m?: number | null
  gex_regime?: string | null
  call_wall?: number | null
  call_wall_pct?: number | null
  put_wall?: number | null
  put_wall_pct?: number | null
  gamma_flip?: number | null
  pin_strike?: number | null
  call_premium?: number | null
  put_premium?: number | null
  activity_imbalance?: number | null
  expected_move?: number | null
  atm_iv?: number | null
  selected_expiry?: string | null
  selected_dte?: number | null
  contracts_included?: number | null
  chain_source?: string | null
  activity_basis?: string | null
  mode_resolved?: string | null
  observed_at?: string | null
  age_seconds?: number | null
  open_interest_source?: string | null
  /**
   * False when open interest was never observed. All structural fields
   * (squeeze, GEX, walls) are null in that case — unmeasured, NOT zero.
   */
  gex_measurable?: boolean
  /** Last local price bar. Compared against the chain clock. */
  price_asof?: string | null
  clock_skew_days?: number | null
  /** True when a live chain is being scored against stale price bars. */
  clock_mismatch?: boolean
  warnings: string[]
}

export interface OptionsBoard {
  schema_version: string
  asof_utc: string
  scan_asof: string | null
  depth: string
  limit: number
  require_live_flow: boolean
  rows: OptionsBoardRow[]
  coverage: {
    /** Symbols the scan offered before the top-N slice — the search width. */
    candidates_considered: number
    requested: number
    chain_fetched: number
    chain_failed: number
    squeeze_scored: number
    /** scored names x 2 sides. This board is a search, not a discovery. */
    tests_run: number
    clock_mismatched: number
  }
  selection_basis_notes: Record<string, string>
  decision_authorized: false
  score_kind: string
  warnings: string[]
  caveats: string[]
  cache?: {
    hit: boolean
    age_seconds: number
    ttl_seconds: number
    refresh_hint: string
  }
}

/** Why a row's signal came from — which upstream board(s) had this symbol. */
export type LiveOpportunitySignalBasis = 'structure_only' | 'flow_only' | 'both' | string

export interface LiveOpportunityConfidence {
  kind: 'calibrated_probability' | 'unavailable' | string
  probability: number | null
  band: 'HIGH' | 'MODERATE' | 'LOW' | 'UNCALIBRATED' | string
  source: string | null
  is_high: boolean
  setup_ok: boolean | null
  state: string | null
  calibration_version: string | null
  model: string | null
  reason: string | null
}

export interface LiveOpportunityFreshness {
  pass: boolean
  status: 'FRESH' | 'STALE_OR_PROXY' | string
  max_age_seconds: number
  chain_live: boolean
  chain_age_seconds: number | null
  flow_required: boolean
  flow_live: boolean | null
  flow_age_seconds: number | null
  reasons: string[]
}

export interface LiveOpportunityCosts {
  method: 'quoted_spread_only' | string
  observed_spread_pct: number | null
  one_way_half_spread_pct: number | null
  one_way_half_spread_bps: number | null
  round_trip_spread_pct: number | null
  spread_gate_max_pct: number
  spread_gate_pass: boolean
  market_impact: number | null
  commission: number | null
  complete: boolean
  note: string
}

export interface LiveOpportunityPlaybook {
  status: 'candidate' | 'research_only' | 'blocked' | string
  direction: 'long' | 'short' | 'watch' | string
  direction_source: string
  structure: string
  structure_label: string
  expiry: string | null
  trigger: number | null
  target: number | null
  invalidation: number | null
  levels: {
    spot: number | null
    call_wall: number | null
    put_wall: number | null
    gamma_flip: number | null
    expected_move: number | null
  }
  legs: Array<{ action: string; instruction: string }>
  risk: {
    max_account_risk_pct: number
    max_portfolio_heat_pct: number
    max_loss: string
    sizing_formula: string
    entry_order: string
    exit_rule: string
    quote_cost: LiveOpportunityCosts
  }
  blockers: string[]
  warnings: string[]
}

export interface LiveOpportunityRow {
  symbol: string
  signal_basis: LiveOpportunitySignalBasis
  /** Ordinal z-blend of board squeeze + flow unusual scores. Can be negative. */
  composite_score: number | null
  board_squeeze_score: number | null
  board_squeeze_z: number | null
  flow_unusual_score: number | null
  flow_unusual_z: number | null
  gate_pass: boolean
  /** Populated when gate_pass is false, e.g. ["spread 42% > max 25%"]. */
  gate_reasons: string[]
  spread_pct: number | null
  open_interest: number | null
  selected_dte: number | null
  call_put_imbalance: number | null
  ret_1d: number | null
  premium: number | null
  confidence: LiveOpportunityConfidence
  highlighted: boolean
  live_ready: boolean
  freshness: LiveOpportunityFreshness
  costs: LiveOpportunityCosts
  barriers: {
    spot: number | null
    call_wall: number | null
    put_wall: number | null
    gamma_flip: number | null
    expected_move: number | null
  }
  playbook: LiveOpportunityPlaybook
}

export interface LiveOpportunitiesCoverage {
  board_symbols: number
  flow_symbols: number
  union_symbols: number
  gate_pass: number
  gate_fail: number
  high_confidence: number
  live_ready: number
  uncalibrated: number
  stale_or_proxy: number
}

/**
 * Live opportunities (`/api/options/opportunities`): the conviction board's
 * structural squeeze score and market-wide unusual flow, z-blended per symbol
 * into one ordinal composite ranking. Rows are pre-sorted gate_pass first
 * (desc composite_score), then gate_fail — both groups render, never filter
 * gate_fail client-side, that's a deliberate honesty choice upstream.
 * `available: false` is the normal pre-data state — render `reason` as an
 * empty state, not an error.
 */
export interface LiveOpportunities {
  schema_version?: string
  asof_utc?: string
  available: boolean
  reason?: string
  decision_authorized?: false
  /** Always 'ordinal_composite' when available — never a probability. */
  score_kind?: 'ordinal_composite' | string
  method?: string
  filters?: Record<string, unknown>
  rows?: LiveOpportunityRow[]
  coverage?: LiveOpportunitiesCoverage
  warnings?: string[]
  caveats?: string[]
  sources?: {
    board?: { cache?: { hit?: boolean; age_seconds?: number; ttl_seconds?: number }; asof_utc?: string | null; scan_asof?: string | null }
    flow?: { cache?: { hit?: boolean; age_seconds?: number; ttl_seconds?: number }; asof?: string | null }
    scan_depth?: string
  }
}

export interface OptionsIntelligence {
  schema_version: string
  symbol: string
  mode_requested: OptionsMode
  mode_resolved: 'live' | 'history' | 'history_fallback' | 'unavailable'
  asof_utc: string
  observed_at: string | null
  freshness: { age_seconds: number | null }
  filters: Record<string, number | string | null>
  chain_context: OptionsExpiryContext
  history?: OptionsHistoryMeta
  provider: {
    chain: string
    flow: string
    open_interest: string
    activity_basis: 'trade_tape' | 'chain_activity_proxy' | 'unavailable'
    signed_flow_available: boolean
  }
  summary: {
    spot: number
    call_premium: number
    put_premium: number
    call_put_ratio: number | null
    activity_imbalance: number | null
    signed_net_premium: number | null
    unresolved_premium: number
    total_gex_m: number
    call_gex_m?: number
    put_gex_m?: number
    abs_gex_m?: number
    call_oi?: number
    put_oi?: number
    regime: 'positive' | 'negative' | 'neutral'
    gamma_flip: number | null
    gamma_flip_pct?: number | null
    call_wall: number | null
    call_wall_pct?: number | null
    put_wall: number | null
    put_wall_pct?: number | null
    pin_strike: number | null
    squeeze?: OptionsSqueeze
  }
  quality: {
    chain_contracts_raw: number
    chain_contracts_included: number
    chain_rejected: Record<string, number>
    flow_prints_raw: number
    flow_prints_included: number
    flow_rejected: Record<string, number>
    gamma_source: Record<string, number>
    anomaly_sample_size: number
  }
  price_series: OptionsPricePoint[]
  flow_series: OptionsFlowPoint[]
  flow_tape: OptionsTapeRow[]
  gex_by_strike: GexStrikeRow[]
  gex_by_expiry?: Array<{
    expiry: string
    dte: number | null
    call_gex_m: number
    put_gex_m: number
    net_gex_m: number
    abs_gex_m: number
    call_oi: number
    put_oi: number
    contracts: number
  }>
  gex_price_profile?: Array<{ spot: number; net_gex_m: number }>
  gex_history: GexHistoryPoint[]
  anomalies: { count: number; method: string }
  probability: OptionsProbability
  warnings: string[]
  caveats: string[]
}

export type SourceQuality = 'ok' | 'stale' | 'degraded' | 'missing' | string

export interface CotMarket {
  id: string
  label: string
  cftc_market?: string
  proxy?: string
  asof?: string
  quality?: SourceQuality
  noncomm_net?: number | null
  comm_net?: number | null
  open_interest?: number | null
  noncomm_net_pct_oi?: number | null
  noncomm_net_z_1y?: number | null
  noncomm_net_pctile_1y?: number | null
  bias?: string
  history_weeks?: number
  source?: string
  lag_note?: string
}

export interface SecFilingsPayload {
  symbol: string
  name?: string
  cik?: number | null
  quality: SourceQuality
  asof?: string | null
  source?: string
  lag_note?: string
  counts_90d?: Record<string, number>
  filings?: {
    form: string
    filed: string
    description?: string
    accession?: string
    url?: string | null
  }[]
  edgar_company_url?: string
  error?: string
}

export interface SentimentPayload {
  generated_at: string
  disclaimer: string
  composite: {
    score: number | null
    label: string
    inputs: { name: string; value: number | null }[]
    quality: SourceQuality
  }
  vol: Record<string, unknown>
  cot: {
    quality: SourceQuality
    asof?: string | null
    source?: string
    lag_note?: string
    markets?: CotMarket[]
    errors?: string[]
  }
  finra_short: Record<string, unknown>
  options: Record<string, unknown>
  sector_flow_pointer?: Record<string, unknown>
  accuracy?: Record<string, unknown>
  symbol_filings?: SecFilingsPayload
}

export interface AnomaliesPayload {
  generated_at: string
  disclaimer: string
  price_volume: {
    quality: SourceQuality
    asof?: string | null
    source?: string
    lag_note?: string
    rows?: Record<string, unknown>[]
    n_scanned?: number
    n_flagged?: number
  }
  finra_short_extremes: Record<string, unknown>
  options_extremes: Record<string, unknown>
  sec_activity: Record<string, unknown>
  unified: Record<string, unknown>[]
  accuracy?: Record<string, unknown>
  symbol_focus?: Record<string, unknown>
}

/* ---------------------------------------------------------------- graph ----
   Repo knowledge graph (`/api/graph`), built by edge/tools/graphify_index.py.
   `available: false` is the normal state before anything has been indexed —
   it carries a `reason` and is rendered as an empty state, never as an error.
   Topology only: no coordinates. The client owns layout, so the same graph
   draws identically on every load. */

export interface GraphStats {
  n_nodes: number
  n_edges: number
  n_communities: number
  truncated: boolean
}

export interface GraphCommunity {
  id: string
  label: string
  size: number
  color_index: number
}

export interface GraphNode {
  id: string
  label: string
  community: string
  degree: number
  kind: string
  path: string | null
}

export interface GraphEdge {
  source: string
  target: string
  weight: number
  kind: string
}

export interface GraphPayload {
  available: boolean
  reason: string | null
  generated_at: string | null
  stats: GraphStats | null
  communities: GraphCommunity[]
  nodes: GraphNode[]
  edges: GraphEdge[]
}

/* --------------------------------------------------------- factor research -
   Factor diagnostics (`/api/factors`) from edge/research/factor_diagnostics.py.
   These answer the question the repo's own README raises: the cross-sectional
   Rank IC is real but small, so WHERE does it live — in the extreme quantiles
   (cheap to hold) or spread evenly (eaten by turnover)? */

export interface IcDecayRow {
  horizon: number
  mean_ic: number | null
  ic_std: number | null
  ic_t_stat: number | null
  ic_ir: number | null
  n_periods: number
  pct_positive: number | null
}

export interface QuantileRow {
  quantile: number
  mean_return: number | null
  std_return: number | null
  sharpe: number | null
  n_obs: number
  mean_count: number | null
}

export interface QuantileTurnoverRow {
  quantile: number
  mean_turnover: number | null
  median_turnover: number | null
  n_periods: number
}

export interface FactorTearsheet {
  available: boolean
  reason: string | null
  generated_at: string | null
  source: string | null
  n_dates: number
  n_symbols: number
  execution_lag: number
  monotonicity: number | null
  ic_decay: IcDecayRow[]
  quantiles: QuantileRow[]
  quantile_turnover: QuantileTurnoverRow[]
}

export type TrajWindow = '1m' | '3m' | '6m' | '1y' | '3y' | '5y' | 'max'

export const WINDOWS: TrajWindow[] = ['1m', '3m', '6m', '1y', '3y', '5y', 'max']

/** Regime-aware multi-stream live blend — ordinal only, never trade-authorized. */
export interface AdaptiveStreamBlock {
  score: number | null
  quality: string
  components?: Record<string, number | string | null>
  reasons?: string[]
  [k: string]: unknown
}

export interface AdaptiveSignalRow {
  schema_version: string
  score_kind: 'ordinal_adaptive_blend' | string
  decision_authorized: boolean
  live_capital_authorized: boolean
  promotion_authorized?: boolean
  symbol: string
  asof: string | null
  state: string
  side: 'long' | 'short' | 'neutral' | string
  composite_score: number | null
  agreement_band: 'thin' | 'moderate' | 'strong' | 'conflicted' | string
  regime: {
    volatility_regime?: string | null
    trend_regime?: string | null
    bear_market?: boolean | null
    quality?: string
    [k: string]: unknown
  }
  streams: Record<string, AdaptiveStreamBlock>
  stream_scores: Record<string, number | null>
  weights: {
    base: Record<string, number>
    adapted: Record<string, number>
    adaptation_mode: string
    contributions?: Record<string, number>
  }
  present_streams: string[]
  reasons: string[]
  attention_rank?: number
  bar_freq?: string
  bars_per_session?: number
  n_bars?: number
  stream_performance_used?: Record<string, number | null>
  caveat?: string
}

export interface StreamHitRates {
  schema_version?: string
  score_kind?: string
  decision_authorized?: boolean
  lookback_events?: number
  min_events?: number
  events_considered?: number
  events_scored?: number
  events_skipped?: number
  stream_counts?: Record<string, number>
  stream_performance?: Record<string, number>
  asof?: string | null
  sources?: string[]
  caveat?: string
  error?: string
  quality?: string
}

export interface AdaptiveSignalPayload {
  mode: 'symbol' | 'board' | string
  symbol: string | null
  asof: string | null
  board: {
    schema_version?: string
    score_kind?: string
    decision_authorized?: boolean
    quality?: string
    asof?: string | null
    rows: AdaptiveSignalRow[]
    coverage?: Record<string, number>
    regime_histogram?: Record<string, number>
    caveat?: string
  } | null
  signal: AdaptiveSignalRow | null
  stream_hit_rates?: StreamHitRates | null
  decision_authorized: boolean
  live_capital_authorized: boolean
}

/* ----------------------------------------------------------- changepoints -
   Bayesian Online Changepoint Detection (`/api/changepoints`), implementing
   Adams & MacKay 2007 (arXiv:0710.3742) §2-3 over daily returns:
   zero-mean Gaussian observation model, Gamma(a, b) prior on the precision,
   constant hazard H = 1/lambda_gap. The endpoint serves two shapes — a
   cross-section (payload A, all symbols, offline artifact) and a per-symbol
   detail (payload B, computed on demand) carrying the run-length posterior
   matrix behind the paper's Figure 3. This is a diagnostic surface:
   break_prob says the return-generating variance just changed, not that
   anything is tradable — only the repo's own gate modules authorise that.

   AMENDMENT 1 (BOCPD_CONTRACT.md): P(r_t = 0 | x_1:t) is constant under a
   constant hazard (identically H = 1/lambda_gap, ~0.004 for lambda_gap=250)
   and carries zero information — it is not exposed. The detection statistic
   is `break_prob = P(r_t <= 5 | x_1:t)`, the posterior probability that a
   changepoint occurred within the last 5 bars (plus `break_prob_20` at a
   20-bar lookback). The paper's Fig. 3 signal is the collapse of the
   run-length ridge, which these fields summarise without the caller having
   to read the matrix. */

export interface ChangepointModel {
  observation: string
  hazard: string
  lambda_gap: number
  prior: { a: number; b: number }
  truncation_mass: number
  reference: string
}

export interface ChangepointThresholds {
  break: number
  settling: number
}

export type ChangepointRegime = 'BREAK' | 'SETTLING' | 'STABLE' | string

export interface ChangepointRow {
  symbol: string
  n_bars: number
  last_date: string
  /** P(r_t <= 5 | x_1:t) — probability a break occurred in the last 5 bars. */
  break_prob: number
  /** P(r_t <= 20 | x_1:t) — same statistic at a 20-bar lookback. */
  break_prob_20: number
  /** argmax_r P(r_t | x_1:t). */
  map_run_length: number
  /** Sum_r r * P(r_t | x_1:t). */
  expected_run_length: number
  last_break_date: string | null
  days_since_break: number | null
  /** sd of the marginal predictive (eq. 1) with the undefined-variance r=0
   *  run masked out, daily fraction. */
  predictive_vol: number
  /** Posterior mass retained after masking r=0 out of predictive_vol's
   *  mixture (~0.996 typical); null if not reported. */
  predictive_vol_defined_mass: number | null
  /** realized 20-bar sd of returns, daily fraction. */
  trailing_vol_20d: number
  vol_ratio: number | null
  last_return: number
  regime: ChangepointRegime
}

export interface ChangepointsPayload {
  available: boolean
  reason: string | null
  generated_at: string
  source: string
  asof: string
  model: ChangepointModel
  thresholds: ChangepointThresholds
  n_symbols: number
  lookback_days: number
  symbols: ChangepointRow[]
  /** Symbols the artifact attempted but could not score (optional — older
   *  artifacts may omit these). */
  n_skipped?: number
  skipped?: { symbol: string; reason: string }[]
}

export interface ChangepointSeriesPoint {
  d: string
  ret: number
  /** P(r_t <= 5 | x_1:t) — see ChangepointRow.break_prob. */
  break_prob: number
  map_run: number
  pred_vol: number
  pred_mean: number
}

/** The paper's Figure-3-bottom run-length posterior heatmap. */
export interface ChangepointRunlength {
  /** Downsampled dates, length n_cols (<= 260). */
  dates: string[]
  /** Downsampled run-length row labels, length n_rows (<= 130). */
  run_values: number[]
  n_rows: number
  n_cols: number
  /** Colour-scale floor for the clipped log10 probabilities. */
  log_floor: number
  /**
   * Row-major, rows = run lengths: matrix[i][j] is log10 P(run_values[i] |
   * x_1:dates[j]), clipped to [log_floor, 0]. null where the run length
   * exceeds bars elapsed (structurally impossible) or falls below the floor.
   */
  matrix: (number | null)[][]
}

export interface ChangepointBreak {
  date: string
  break_prob: number
  ret: number
  pred_vol_before: number
  pred_vol_after: number
}

export interface ChangepointDetail {
  available: boolean
  reason: string | null
  symbol: string
  window: string
  n_bars: number
  first_date: string
  last_date: string
  generated_at: string
  model: ChangepointModel
  thresholds: ChangepointThresholds
  series: ChangepointSeriesPoint[]
  runlength: ChangepointRunlength
  breaks: ChangepointBreak[]
  /** The exact per-symbol row from payload A, for this symbol. */
  stats: ChangepointRow | null
}

/* ---------------------------------------------------------------- endpoints */

export interface MomentumCandidate {
  symbol: string
  price: number
  gap_pct: number | null
  day_change_pct: number | null
  rvol: number | null
  float_shares: number | null
  float_badge: 'optimal' | 'qualifies' | 'no' | 'unknown'
  gap_sweet_spot: boolean
  price_qualifies: boolean
  gap_qualifies: boolean
  rvol_qualifies: boolean
  pillars_met: number
}

export interface MomentumScanPayload {
  asof: string
  universe_size: number
  expected_universe_size: number
  float_coverage_pct: number
  candidates: MomentumCandidate[]
  all_candidates?: MomentumCandidate[]
}

/* ------------------------------------------------------------- flow-state -
   Latent market-state estimator for forced-flow events (`/api/flow-state`),
   built offline by tools/build_flow_state.py from daily-bar proxies only —
   there is no order-book depth/trades/quotes anywhere in this repo, so every
   "flow", "impact", or "liquidity" figure here is a descriptive proxy, not a
   causal identification. tier 0 = states/events only; tier 1 = a Phase-2
   matched-control study has been run and its own T1 criterion passed
   (bootstrap CI excludes 0 AND deflated permutation p < 0.01). `models` is
   always null and decision_authorized always false until a Phase-3
   development gate (not built yet) records a pass and raises tier to >= 2 —
   the Model/EV panel renders permanently locked below that. */

export type FlowStateName =
  | 'NORMAL' | 'PRESSURE' | 'SHOCK' | 'TEST' | 'CASCADE' | 'ABSORB' | 'EXHAUSTION' | 'FADE'

export interface FlowStateRow {
  symbol: string
  current_state: FlowStateName | string
  days_in_state: number
  flow_z: number | null
  persistence_5d: number | null
  amihud_z: number | null
  cs_spread: number | null
  /** Rolling OLS slope of returns on flow_z (descriptive impact proxy). */
  impact_beta?: number | null
  /** Trailing robust z of impact_beta; only positive values feed the sleeve. */
  impact_beta_z?: number | null
  /**
   * Barrier-conditioned continuation sleeve:
   * |flow_z| × max(impact_beta_z,0) × persistence × exp(−d/τ).
   * Ranking feature for continuation research — not a bottom/fade call.
   */
  continuation_score?: number | null
  /** sign(flow_z): +1 buy pressure, −1 sell pressure. */
  continuation_direction?: number | null
  /** Smooth barrier kernel exp(−d/τ) in [0,1]. */
  barrier_proximity?: number | null
  /** Distance to nearest structural barrier in ATR units. */
  dist_to_barrier_atr?: number | null
  air_pocket_up: number | null
  air_pocket_down: number | null
  next_support: number | null
  next_resistance: number | null
  /** ORDINAL rank across this run's symbols (1 = most stressed) — never a probability. */
  stress_rank: number
}

export interface FlowStateTimelinePoint {
  date: string
  state: FlowStateName | string
}

export interface FlowStateEvent {
  symbol: string
  t0: string
  direction: number
  state_path: string[]
  outcome: 'DOWN_FIRST' | 'UP_FIRST' | 'NEITHER' | 'AMBIGUOUS' | null
  time_to_hit: number | null
  mfe: number | null
  mae: number | null
}

export interface BarrierFieldNode {
  price: number | null
  mass: number | null
}

export interface BarrierField {
  grid: number[]
  density: number[]
  price: number | null
  nodes: BarrierFieldNode[]
  /** Today's live options-chain snapshot only, when populated — null otherwise. */
  strikes_overlay: number[] | null
}

export interface ImpactCurve {
  lags: number[]
  mean_cum_ret: (number | null)[]
  ci_lo: (number | null)[]
  ci_hi: (number | null)[]
}

export interface PhenomenonResult {
  tested: boolean
  effect: number | null
  nw_t: number | null
  boot_ci: [number | null, number | null] | null
  perm_p: number | null
  n_events: number
  n_controls: number
  grid: Record<string, unknown>[]
  prereg_id: string | null
  passed: boolean
}

export interface GateResult {
  evaluated: boolean
  passed: boolean
  checks: Record<string, unknown>
  ledger_id: string | null
}

export interface FlowStatePayload {
  available: boolean
  reason: string | null
  as_of: string | null
  tier: 0 | 1 | 2
  decision_authorized: boolean
  caveats: string[]
  states: FlowStateRow[]
  timelines: Record<string, FlowStateTimelinePoint[]>
  events: FlowStateEvent[]
  barrier_fields: Record<string, BarrierField>
  impact_curve: ImpactCurve
  phenomenon: PhenomenonResult
  gate: GateResult
  models: null
  producing_script: string
}

export const api = {
  health: () => req<Health>('/api/health'),
  status: () => req<StatusPayload>('/api/status'),
  leaderboard: () => req<{ asof: string; leaderboard: LeaderboardRow[] }>('/api/leaderboard'),
  gcp: () => req<Record<string, unknown>>('/api/gcp'),
  gates: () => req<{ gates: Gate[] }>('/api/gates'),
  momentumScan: () => req<MomentumScanPayload>('/api/momentum-scan'),
  readiness: () => req<Readiness>('/api/readiness'),
  marketClock: () => req<MarketClock>('/api/market-clock'),

  sentiment: (symbol?: string) =>
    req<SentimentPayload>(
      symbol
        ? `/api/sentiment?symbol=${encodeURIComponent(symbol)}`
        : '/api/sentiment',
    ),

  anomalies: (opts?: { limit?: number; symbol?: string }) => {
    const q = new URLSearchParams()
    if (opts?.limit) q.set('limit', String(opts.limit))
    if (opts?.symbol) q.set('symbol', opts.symbol)
    const qs = q.toString()
    return req<AnomaliesPayload>(`/api/anomalies${qs ? `?${qs}` : ''}`)
  },

  search: (q: string, limit = 25) =>
    req<{ results: SearchHit[] } | SearchHit[]>(
      `/api/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ).then(normalizeSearch),

  trajectory: (symbol: string, window: TrajWindow = '1y') =>
    req<Trajectory>(
      `/api/trajectory?symbol=${encodeURIComponent(symbol)}&window=${window}`,
    ),

  compare: (symbols: string[], window: TrajWindow = '1y') =>
    req<ComparePayload>(
      `/api/compare?symbols=${encodeURIComponent(symbols.join(','))}&window=${window}`,
    ),

  options: (query: OptionsQuery) => {
    const params = new URLSearchParams({
      symbol: query.symbol,
      mode: query.mode ?? 'live',
      range: query.range ?? '5d',
    })
    const optional: [string, number | string | undefined][] = [
      ['min_premium', query.minPremium],
      ['min_volume', query.minVolume],
      ['min_oi', query.minOpenInterest],
      ['max_spread', query.maxSpreadPct],
      ['min_dte', query.minDte],
      ['max_dte', query.maxDte],
      ['expiry', query.expiry],
      ['tape_limit', query.tapeLimit],
      ['from', query.dateFrom],
      ['to', query.dateTo],
    ]
    for (const [key, value] of optional) {
      if (value !== undefined && value !== '') params.set(key, String(value))
    }
    return req<OptionsIntelligence>(`/api/options?${params.toString()}`)
  },

  /**
   * Triggers a live OI capture for one symbol (`/api/options/backfill_oi`) so
   * a symbol with no cached open-interest snapshot can resolve out of the
   * "unmeasured" state without a manual `tools/backfill_option_oi.py` run.
   * Takes several seconds (live yfinance fetch) — callers should show a
   * loading state and refresh `options()`/`optionsBoard()` on success.
   */
  backfillOptionOi: (symbol: string, opts?: { maxDte?: number }) => {
    const q = new URLSearchParams({ symbol })
    if (opts?.maxDte != null) q.set('max_dte', String(opts.maxDte))
    return req<{
      status: 'ok'
      symbol: string
      asof: string
      contracts: number
      with_oi: number
    }>(`/api/options/backfill_oi?${q.toString()}`, { method: 'POST' })
  },

  /**
   * Conviction board (`/api/options/board`): pulls live option chains for the
   * top-ranked names the active scan produced, so structure is visible for the
   * candidates the desk actually surfaced instead of only for a hand-typed
   * ticker. Selection is ordinal — see `selection_basis` on every row.
   *
   * Pass `force` to bypass the 5-minute server cache and refetch chains live.
   */
  optionsBoard: (opts?: {
    limit?: number
    depth?: 'quick' | 'deep'
    requireLiveFlow?: boolean
    force?: boolean
  }) => {
    const q = new URLSearchParams()
    if (opts?.limit != null) q.set('limit', String(opts.limit))
    if (opts?.depth) q.set('depth', opts.depth)
    if (opts?.requireLiveFlow) q.set('require_live_flow', '1')
    if (opts?.force) q.set('force', '1')
    const qs = q.toString()
    return req<OptionsBoard>(`/api/options/board${qs ? `?${qs}` : ''}`)
  },

  /** Standalone market-wide options-flow window (one live LSE request). */
  unusualFlow: (opts?: { limit?: number; minPremium?: number; force?: boolean }) => {
    const q = new URLSearchParams()
    if (opts?.limit != null) q.set('limit', String(opts.limit))
    if (opts?.minPremium != null) q.set('min_premium', String(opts.minPremium))
    if (opts?.force) q.set('force', '1')
    const qs = q.toString()
    return req<UnusualFlowPayload>(`/api/unusual-flow${qs ? `?${qs}` : ''}`)
  },

  /**
   * Live opportunities (`/api/options/opportunities`): composite board+flow
   * ranking, z-blended per symbol. Ordinal only — see `caveats`.
   *
   * Pass `force` to bypass the server cache and recompute now.
   */
  liveOpportunities: (opts?: { limit?: number; force?: boolean }) => {
    const q = new URLSearchParams()
    if (opts?.limit != null) q.set('limit', String(opts.limit))
    if (opts?.force) q.set('force', '1')
    const qs = q.toString()
    return req<LiveOpportunities>(`/api/options/opportunities${qs ? `?${qs}` : ''}`)
  },

  /** Genetic evolution lab (research-only artifacts under runs/ga/). */
  ga: (runId?: string) =>
    req<GaPayload>(
      runId ? `/api/ga?run_id=${encodeURIComponent(runId)}` : '/api/ga',
    ),

  /** Repo knowledge graph. `maxNodes` caps what the browser has to lay out. */
  graph: (maxNodes = 400) => req<GraphPayload>(`/api/graph?max_nodes=${maxNodes}`),

  /** Factor diagnostics — IC decay, quantile spread, turnover by quantile. */
  factors: () => req<FactorTearsheet>('/api/factors'),

  /** BOCPD cross-section — every symbol's run-length posterior summary. */
  changepoints: () => req<ChangepointsPayload>('/api/changepoints'),

  /** BOCPD single-symbol detail — series, run-length matrix, breaks. */
  changepointDetail: (symbol: string, window: TrajWindow = '1y') =>
    req<ChangepointDetail>(
      `/api/changepoints?symbol=${encodeURIComponent(symbol)}&window=${window}`,
    ),

  /** Latent flow-state cross-section — offline artifact, tier-gated panels. */
  flowState: () => req<FlowStatePayload>('/api/flow-state'),

  /** Live multi-stream adaptive blend (regime weights + optional online soft reweight). */
  adaptiveSignal: (opts?: { symbol?: string; limit?: number }) => {
    const q = new URLSearchParams()
    if (opts?.symbol) q.set('symbol', opts.symbol)
    if (opts?.limit != null) q.set('limit', String(opts.limit))
    const qs = q.toString()
    return req<AdaptiveSignalPayload>(`/api/adaptive-signal${qs ? `?${qs}` : ''}`)
  },

  /** Fintel key presence probe — never returns the secret. */
  fintelStatus: () => req<FintelStatusPayload>('/api/fintel/status'),

  /** Polled Fintel market boards (squeeze / SI / calendars). */
  fintelStream: (opts?: { squeezeLimit?: number; shortInterestLimit?: number; force?: boolean }) => {
    const q = new URLSearchParams()
    if (opts?.squeezeLimit != null) q.set('squeeze_limit', String(opts.squeezeLimit))
    if (opts?.shortInterestLimit != null) q.set('short_interest_limit', String(opts.shortInterestLimit))
    if (opts?.force) q.set('force', '1')
    const qs = q.toString()
    return req<FintelStreamPayload>(`/api/fintel/stream${qs ? `?${qs}` : ''}`)
  },

  /** Per-symbol Fintel intel bundle for analysis. Default depth=core (quota-light). */
  fintelIntel: (
    symbol: string,
    opts?: { country?: string; force?: boolean; depth?: 'core' | 'full' },
  ) => {
    const q = new URLSearchParams({ symbol, depth: opts?.depth ?? 'core' })
    if (opts?.country) q.set('country', opts.country)
    if (opts?.force) q.set('force', '1')
    return req<FintelIntelPayload>(`/api/fintel/intel?${q.toString()}`)
  },

  fintelSearch: (q: string, opts?: { limit?: number; country?: string }) => {
    const params = new URLSearchParams({ q })
    if (opts?.limit != null) params.set('limit', String(opts.limit))
    if (opts?.country) params.set('country', opts.country)
    return req<FintelSearchPayload>(`/api/fintel/search?${params.toString()}`)
  },

  analyze: (symbol: string) =>
    req<Record<string, unknown>>(`/api/analyze?symbol=${encodeURIComponent(symbol)}`),

  triggerScan: (depth: ScanDepth = 'quick') =>
    req<ScanJobPayload>(
      `/api/trigger_scan?depth=${depth}`,
      { method: 'POST' },
    ),

  scanStatus: (jobId?: string) =>
    req<ScanJobPayload>(
      `/api/scan_status${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ''}`,
    ),
}

/* ---------------------------------------------------------------- fintel ----
   Proxied Fintel Public Data API. Key lives only in edge/.env as FINTEL_API_KEY
   and is sent server-side as X-API-KEY. Never trade-authorized. */

export interface FintelStatusPayload {
  provider: string
  base_url: string
  configured: boolean
  auth_header: string
  env_var: string
  key_setup_url: string
  docs_url: string
  decision_authorized: boolean
  live_capital_authorized: boolean
  hint: string
}

export interface FintelStreamPayload {
  available: boolean
  configured?: boolean
  provider?: string
  generated_at?: string
  boards?: Record<string, unknown>
  errors?: Record<string, string>
  error?: string
  error_kind?: 'auth' | 'quota' | string
  quota_exceeded?: boolean
  poll_hint_seconds?: number
  caveat?: string
  decision_authorized?: boolean
  live_capital_authorized?: boolean
}

export interface FintelAnalysis {
  headline: string
  notes: string[]
  metrics: Record<string, number | string | null | undefined>
  attention_score: number
}

export interface FintelIntelPayload {
  available: boolean
  configured?: boolean
  provider?: string
  symbol?: string
  country?: string
  depth?: string
  generated_at?: string
  blocks?: Record<string, unknown>
  errors?: Record<string, string>
  analysis?: FintelAnalysis
  error?: string
  error_kind?: 'auth' | 'quota' | string
  quota_exceeded?: boolean
  hint?: string
  caveat?: string
  decision_authorized?: boolean
  live_capital_authorized?: boolean
}

export interface FintelSearchPayload {
  available: boolean
  configured?: boolean
  query?: string
  results: Record<string, unknown>[]
  error?: string
  generated_at?: string
}

/** The server may return a bare array or a wrapped object; accept both. */
function normalizeSearch(r: { results: SearchHit[] } | SearchHit[]): SearchHit[] {
  return Array.isArray(r) ? r : (r.results ?? [])
}
