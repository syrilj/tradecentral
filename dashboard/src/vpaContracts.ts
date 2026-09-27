/**
 * TypeScript contracts for the volume-price analysis view.
 *
 * Shape is fixed by `docs/VPA_REBUILD_CONTRACT.md` §4. Everything added by the
 * rebuild is OPTIONAL on the wire: the backend lands in parallel, so the view
 * must render honestly (empty states, em dashes) while fields are still absent.
 * Never substitute a plausible constant for a missing number.
 */

export interface VpaBar {
  d: string
  o: number
  h: number
  l: number
  c: number
  v: number
  /** Forming bar, excluded from scoring. Chart-only. */
  live?: boolean
}

export interface VpaKeyCandle {
  candle_type: string
  spread: string
  volume: string
  verdict: 'VALIDATION' | 'ANOMALY' | string
  interpretation: string
}

export interface VpaStoppingTopping {
  detected: boolean
  type: string
  details: string
}

export interface VpaTestCandles {
  detected: boolean
  type: string
  result: string
}

export interface VpaSupportResistance {
  floor_support: string
  ceiling_resistance: string
  pivot_highs: string
  pivot_lows: string
  /** How the pivots were found and clustered, e.g. "3-bar fractal pivots at 0.55x ATR". */
  method?: string
}

export interface VpaForensicBreakdown {
  wyckoff_phase: string
  key_candles: VpaKeyCandle[]
  stopping_or_topping: VpaStoppingTopping
  test_candles: VpaTestCandles
  support_resistance: VpaSupportResistance
  volume_at_price: string
}

export interface VpaPrimaryScenario {
  likely_move: string
  direction: 'BULLISH' | 'BEARISH' | 'SIDEWAYS' | string
  probability_pct: number | null
  target_zone: string
  expected_horizon: string
  rationale: string
}

export interface VpaAlternativeScenario {
  thesis: string
  probability_pct: number | null
  speculative_read: string
  invalidation_trigger: string
  risk_warning: string
}

export interface VpaTradeExecutionGuide {
  bias: 'LONG' | 'SHORT' | 'NEUTRAL / WAIT' | string
  entry_trigger: string
  stop_loss_placement: string
  /**
   * Contract §5: null when entry/stop/target are not all derivable. Render `—`,
   * never a placeholder. The engine emits the bare reward multiple as a number
   * (`2.12`); older/vision responses sent a pre-formatted string, so both are
   * accepted and the view does the formatting.
   */
  risk_reward_ratio: number | string | null
  /** The numeric levels the ratio was computed from. Null together with it. */
  entry_price?: number | null
  stop_price?: number | null
  target_price?: number | null
  /** Why `risk_reward_ratio` is null — printed instead of the ratio, never in place of one. */
  risk_reward_unavailable_reason?: string | null
  rules_applied: string[]
}

/* ------------------------------------------------------------------ §4 additions */

/**
 * Proof that the timeframe control actually took effect (defect D1).
 * `timeframe_served` may differ from `timeframe_requested`; when it does,
 * `downgraded` is true and `downgrade_reason` explains why.
 */
export interface VpaBarsMeta {
  timeframe_requested?: string
  timeframe_served?: string
  downgraded?: boolean
  downgrade_reason?: string | null
  bar_count?: number
  first_bar?: string | null
  last_bar?: string | null
  source?: string | null
  /** Set when the served timeframe was resampled up from a finer one. */
  resampled_from?: string | null
  native?: boolean
  lookback_requested?: number
  /**
   * Timestamp of the in-progress bar that was excluded from scoring.
   * The candle itself is in `live_bar` so the chart can still paint it.
   */
  incomplete_bar_dropped?: string | null
  /** Forming candle, wire shape `{d,o,h,l,c,v,live:true}`. Never scored. */
  live_bar?: VpaBar | null
  /**
   * True when serving this request fetched from the provider and changed the
   * parquet on disk — the searched symbol was missing or stale and healed
   * itself. False (or stale `last_bar` + this false) means the provider has
   * not published the newest session yet.
   */
  refreshed_on_demand?: boolean
}

export type VpaLevelKind = 'support' | 'resistance' | string

/** A numeric, drawable support/resistance zone (defect D5). */
export interface VpaLevel {
  price: number
  low?: number
  high?: number
  kind: VpaLevelKind
  /** 0..1 — drives band opacity on the canvas. */
  strength?: number
  touches?: number
  source?: string
  /** What the zone was born as. `origins` lists every role it has held. */
  origin?: VpaLevelKind
  origins?: VpaLevelKind[]
  /** A ceiling closed through on rising volume can later act as support. */
  role_reversed?: boolean
  last_touch_bar?: number
}

export interface VpaVapBin {
  low: number
  high: number
  volume: number
  /** 0..1 share of `total_volume` — drives the profile bar length. */
  pct_of_total?: number
}

/** Range-distributed volume-at-price (defect D6), not close-binned. */
export interface VpaVolumeAtPrice {
  poc?: number | null
  /** The POC is a bin, not a line: these are its edges. */
  poc_low?: number | null
  poc_high?: number | null
  value_area_low?: number | null
  value_area_high?: number | null
  /** 0..1 — the share of volume the value area actually captured. */
  value_area_pct?: number | null
  total_volume?: number | null
  bin_size?: number | null
  method?: string | null
  book_ref?: string | null
  bins?: VpaVapBin[]
}

export type VpaEvidenceDirection = 'bullish' | 'bearish' | 'neutral' | string

/** One signed line of the ledger behind every number the page prints (defect D4). */
export interface VpaEvidenceItem {
  signal: string
  direction: VpaEvidenceDirection
  weight: number
  /** 0-based indices into the scored bar series. */
  bars?: number[]
  /** Short dates for those indices, same order. */
  bar_dates?: string[]
  book_ref?: string
  detail?: string
}

/** How the headline percentage was formed — shown next to the percentage itself. */
export interface VpaProbabilityBasis {
  bull_score?: number
  bear_score?: number
  method?: string
  /** Clamp applied to the logistic, e.g. [35, 80]. */
  band?: number[]
  /** The pre-clamp figure, and whether the clamp actually bit. */
  raw_probability_pct?: number
  clamped?: boolean
  evidence_count?: number
  note?: string
}

/** D2/D3 honesty: the snapshot button must never appear to work and do nothing. */
export interface VpaVisionStatus {
  available: boolean
  /**
   * Always false. The quantitative path reads exact OHLCV bars and is the more
   * precise of the two, so a missing vision model is a reduced-reach condition,
   * not a broken feature.
   */
  required?: boolean
  primary_path?: string
  reason?: string | null
  image_received?: boolean
  image_used?: boolean
  model?: string | null
}

/**
 * Dynamic trend line fitted through the recent pivots. Null when there is
 * no pivot structure to fit; `direction: 'none'` when the pivots are two-sided,
 * in which case the slope fields are absent rather than zero.
 */
export interface VpaDynamicTrend {
  direction: 'bullish' | 'bearish' | 'none' | string
  detail: string
  pivot_count?: number
  pivot_bars?: number[]
  slope_per_bar?: number
  /** Slope normalised by ATR so it compares across instruments. */
  slope_atr_per_bar?: number
  book_ref?: string
}

/** Congestion geometry (pennant, triangle, triple top or bottom) built from pivot pairs. */
export interface VpaCongestionPattern {
  pattern: string
  direction: 'bullish' | 'bearish' | 'neutral' | string
  bars: number[]
  /** The breakout level the pattern resolves against. */
  level?: number
  detail: string
  book_ref?: string
}

/**
 * The arithmetic behind `confidence_score`. Shown so the number is auditable
 * rather than asserted — every component is a 0..1 multiplier except the two
 * raw counts.
 */
export interface VpaConfidenceBasis {
  confidence_score?: number
  components?: {
    coverage?: number
    agreement?: number
    recency?: number
    evidence_density?: number
    downgrade_penalty?: number
    method_ceiling?: number
    bar_count?: number
    data_age_days?: number
  }
  method?: string
}

/** Provenance of the detection thresholds: book-derived or provisional defaults. */
export interface VpaThresholdsStatus {
  spec_present?: boolean
  spec_path?: string | null
  thresholds_source?: string | null
  provisional?: boolean
  note?: string | null
}

export type VpaEngineMode =
  | 'quantitative_ohlcv_vpa'
  | 'vision_multimodal'
  | 'vision+quant'
  | 'canonical_codex_reference'
  | 'offline_heuristic'
  | string

export interface VpaAnalysisResult {
  symbol?: string
  timeframe?: string
  asset_class?: string
  market_phase: string
  dominant_sentiment: string
  confidence_score: number | null
  effort_vs_result_verdict: 'VALIDATION' | 'ANOMALY' | 'MIXED' | string
  forensic_breakdown: VpaForensicBreakdown
  primary_scenario: VpaPrimaryScenario
  alternative_scenarios: VpaAlternativeScenario[]
  trade_execution_guide: VpaTradeExecutionGuide
  is_sample?: boolean
  sample_title?: string
  book_reference?: string
  description?: string
  engine_mode?: VpaEngineMode
  warning?: string
  notice?: string

  /* §4 additions — optional until worker B's backend lands. */
  bars?: VpaBar[]
  bars_meta?: VpaBarsMeta
  levels?: VpaLevel[]
  vap?: VpaVolumeAtPrice
  evidence?: VpaEvidenceItem[]
  probability_basis?: VpaProbabilityBasis
  vision_status?: VpaVisionStatus
  dynamic_trend?: VpaDynamicTrend | null
  congestion_patterns?: VpaCongestionPattern[]
  confidence_basis?: VpaConfidenceBasis
  thresholds_status?: VpaThresholdsStatus
  /** Average true range over the served bars, in price units. */
  atr?: number
  data_status?: { analysed: boolean; reason?: string }
  deterministic?: boolean
  reproducible?: boolean
}

export interface VpaAnalyzeRequest {
  image_base64?: string
  mime_type?: string
  symbol?: string
  timeframe?: string
  lookback?: number
  asset_class?: string
  notes?: string
  sample_id?: string
  ohlcv_series?: Array<{
    d?: string
    date?: string
    o?: number
    open?: number
    h?: number
    high?: number
    l?: number
    low?: number
    c?: number
    close?: number
    v?: number
    volume?: number
  }>
}

export interface VpaSampleMeta {
  id: string
  symbol: string
  timeframe: string
  asset_class: string
  title: string
  book_reference: string
  description: string
}

/* ------------------------------------------------------------- /api/vpa/health */

/**
 * One row of the timeframe support matrix. `available: false` rows MUST render
 * disabled with `reason` shown — never silently substituted for daily.
 */
export interface VpaTimeframeOption {
  value: string
  label: string
  available: boolean
  symbols?: number
  reason?: string | null
}

export interface VpaHealthPayload {
  /** Echoed when the probe was scoped to a symbol; availability is per symbol. */
  symbol?: string | null
  vision: {
    available: boolean
    /** Vision is an optional enrichment, never a prerequisite for a read. */
    required?: boolean
    primary_path?: string
    reason?: string | null
    model?: string | null
  }
  timeframes: VpaTimeframeOption[]
  data_sources?: Record<string, number>
}

export interface VpaCodexPayload {
  title: string
  author: string
  laws: Array<{
    id: string
    name: string
    origin: string
    principle: string
    vpa_application: string
  }>
  principles: Array<{
    number: number
    name: string
    summary: string
  }>
  candle_taxonomy: Array<{
    name: string
    category: string
    sentiment: string
    structure: string
    volume_scenarios: Record<string, string>
  }>
  campaign_phases: Array<{
    phase: string
    actor: string
    objective: string
    price_action: string
    volume_profile: string
  }>
  multi_timeframe: {
    framework: string
    structure: Record<string, string>
    golden_rule: string
  }
  support_resistance: {
    house_analogy: string
    role_reversal: string
    breakout_validation: Record<string, string>
    stop_loss_guidance: string
  }
}
