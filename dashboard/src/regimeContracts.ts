/**
 * Shared contracts for the live gamma-regime surface (/regime).
 *
 * This file is the interface seam between four independently-built units:
 *   gammaRegime.ts        — regime state from the GEX profile + live spot
 *   riskNeutralDensity.ts — smile -> Black-Scholes reprice -> Breeden-Litzenberger
 *   gammaTilt.ts          — regime/charm deformation of that density
 *   /api/gamma/regime     — the index + sector breadth strip
 *
 * Nothing here holds logic. Every unit depends on these types and on nothing
 * else of each other's internals, so each can be read, tested, and replaced
 * on its own.
 */

// ---------------------------------------------------------------------------
// Regime state — recomputed every fast tick from a fixed surface + live spot.
// ---------------------------------------------------------------------------

export type GammaRegime = 'short' | 'long' | 'flip' | 'unmeasurable'

export interface RegimeState {
  /**
   * Dealer net gamma interpolated from `gex_price_profile` at live spot, in
   * $M per 1% move. Negative = dealers short gamma (hedging amplifies moves).
   */
  netGammaM: number | null
  /**
   * d(netGamma)/dSpot, a finite difference on the same profile. This is the
   * term that says where the tape is *pulled*: it tells you whether moving up
   * walks deeper into suppression or out into open air.
   */
  gammaSlope: number | null
  /** (spot - zeroGamma) / spot. Signed: negative = below the flip. */
  distanceToFlip: number | null
  /**
   * 'flip' when |distanceToFlip| is inside `flipBandPct` — the regime is not
   * meaningfully established either way and must not be asserted as if it is.
   */
  regime: GammaRegime
  /** Half-width of the neutral band around zero gamma, as a fraction of spot. */
  flipBandPct: number
  spot: number | null
  zeroGamma: number | null
  pinStrike: number | null
  callWall: number | null
  putWall: number | null
  /**
   * Mirrors the payload's `gex_measurable`. False when open interest is absent:
   * GEX would be fake zeros, so every downstream regime claim must be withheld
   * rather than rendered as a confident neutral.
   */
  measurable: boolean
  /**
   * Symbol-relative scale references: the largest |net_gex_m| and |slope|
   * observed across this symbol's own GEX profile.
   *
   * These exist because gamma magnitude is not comparable across instruments.
   * SPX/SPY net gamma runs orders of magnitude above a single name's, so any
   * fixed $M divisor either saturates instantly on an index or never engages
   * on a small cap — and this surface's primary universe is indices and
   * sector ETFs, the exact case a single-name constant gets wrong.
   *
   * Normalizing against the symbol's own profile makes the regime read
   * scale-free. `GammaExposureMap.vue` already scales its bars by
   * `net_gex_m / maxAbs` for the same reason; this is that idea, reused.
   *
   * Null when the profile is too sparse to establish a scale — consumers must
   * then fall back to their own documented constant rather than dividing by
   * zero or assuming a magnitude.
   */
  gammaScaleM: number | null
  slopeScaleM: number | null
}

// ---------------------------------------------------------------------------
// Risk-neutral density — recomputed on chain refetch (~75s), not every tick.
// ---------------------------------------------------------------------------

/** One point of the interpolated volatility smile, in log-moneyness. */
export interface SmilePoint {
  /** ln(strike / spot). */
  logMoneyness: number
  strike: number
  /** Annualized implied volatility, as a decimal (0.24 = 24%). */
  iv: number
}

export interface Smile {
  points: SmilePoint[]
  spot: number
  /** Year fraction to expiry. */
  tYears: number
  riskFreeRate: number
  expiry: string
  /** Calendar days to this expiry, when the payload states it. */
  dte?: number | null
  /**
   * True when the points came from the expiry-blended `iv_surface` rather than
   * one expiry's own smile — a legacy-payload fallback only. A blended smile is
   * not any traded expiry's, so the density built from it is dominated by
   * clipping artifact and no probability read off it should be shown as one.
   */
  blended?: boolean
  /** Strikes that actually carried a usable IV, before interpolation. */
  observedStrikes: number
  /**
   * Half-width, in log-moneyness, of the horizon-scaled window the smile was
   * restricted to, and how many quoted strikes fell outside it.
   *
   * Chains quote far wider than any one horizon can price. On a 1DTE SPY chain
   * sigma*sqrt(T) is ~1.1%, yet the chain quotes strikes 35% out — thirty-odd
   * standard deviations away, where the IVs are bid-ask noise (observed
   * oscillating 0.93 -> 0.61 -> 0.85 -> 0.57 across adjacent strikes). Feeding
   * that to an interpolator puts non-convexity into the repriced call curve,
   * which surfaces as negative density and large `clippedMass`.
   *
   * Dropping those strikes is a judgment about relevance, so it is reported
   * rather than done silently.
   */
  windowHalfWidth: number
  strikesDropped: number
}

/**
 * A probability density over price, sampled on a uniform strike grid.
 * `density` integrates to 1 across `strikes` by construction.
 */
export interface DensityGrid {
  strikes: number[]
  density: number[]
  spot: number
  tYears: number
  /**
   * How the grid was produced. 'risk-neutral' is derived purely from market
   * prices and is arbitrage-free; 'tilted' carries an asserted model on top.
   */
  kind: 'risk-neutral' | 'tilted'
}

export interface RiskNeutralResult {
  grid: DensityGrid | null
  /**
   * Negative-density mass clipped before renormalization, as a fraction of
   * total. Large values mean the smile is noisy or the chain is too sparse to
   * support a density — surface it, never hide it.
   */
  clippedMass: number
  /** Populated when a density could not be built; `grid` is then null. */
  unavailableReason: string | null
}

// ---------------------------------------------------------------------------
// Tilt — the one asserted model in the stack. Constants are displayed, never
// hidden, and the untilted density stays plotted alongside for audit.
// ---------------------------------------------------------------------------

export interface TiltParams {
  /**
   * Multiplier on the whole smile before repricing. > 1 widens (short gamma:
   * hedging feeds realized vol above implied), < 1 narrows (long gamma).
   */
  volScale: number
  /**
   * Esscher exponential-tilt coefficient in log-moneyness: w(K) ∝ exp(theta *
   * ln(K/spot)). Positive leans the distribution up. A measure change, so the
   * result stays a valid normalized density.
   */
  theta: number
  /** Charm-driven pull toward `pinStrike`, weighted by session remaining. */
  pinPull: number
  /** Tunables, surfaced in the UI so the numbers can be audited. */
  constants: { lambda: number; kappa: number }
}

export interface RegimeProbabilities {
  /** Integrals over the tilted density. Null when the regime is unmeasurable. */
  probAboveCallWall: number | null
  probBelowPutWall: number | null
  probBetweenWalls: number | null
  /** Highest-density price — "where it is trying to go". */
  modalTarget: number | null
  expectedMove: number | null
  /** Central interval covering 68% of the tilted mass. */
  band68: { low: number; high: number } | null
}

// ---------------------------------------------------------------------------
// Breadth — GET /api/gamma/regime?universe=core
// ---------------------------------------------------------------------------

export interface RegimeSymbolRow {
  symbol: string
  kind: 'index' | 'sector'
  label: string
  spot: number | null
  netGammaM: number | null
  zeroGamma: number | null
  regime: GammaRegime
  distanceToFlip: number | null
  /** From /api/kalman-trend. Null when the trend read is unavailable. */
  trend: 'up' | 'down' | 'flat' | null
  measurable: boolean
  /** Non-fatal, per-symbol: one dead chain must not blank the whole strip. */
  note: string | null
}

export interface RegimeBreadthPayload {
  asof: string
  universe: string
  rows: RegimeSymbolRow[]
  /**
   * The actual signal in this strip: an index pinned long-gamma while a heavy
   * sector runs short-gamma means the index is held while its weight is free.
   */
  divergence: {
    indexRegime: GammaRegime
    shortGammaSectors: string[]
    note: string
  } | null
  warnings: string[]
  cache: { hit: boolean; age_seconds: number; ttl_seconds: number } | null
}

// ---------------------------------------------------------------------------
// Multi-Dimensional Unified Market Regime Contracts (R2, R3, R4, R5)
// Conforms to Layer 3 deterministic reconciliation output from desk_regime_fusion.py.
// ---------------------------------------------------------------------------

export type PrimaryRegimeType =
  | 'bull_trend'
  | 'bear_trend'
  | 'compression_range'
  | 'mean_reverting'
  | 'vol_expansion_breakout'
  | 'uncertain_transitional'
  | 'unmeasurable'

export type ConfidenceBand = 'high' | 'moderate' | 'low'

export interface ConfidenceComponents {
  qData?: number
  qBars?: number
  qChain?: number
  qFreshness?: number
  aModels?: number
  dBoundary?: number
  dFlip?: number
  dTrend?: number
  sPersistence?: number
  tenureBars?: number
  whipsawPenalty?: number
  tRisk?: number
  hazardMultiplier?: number
  compositeConfidence?: number
}

export interface CalibratedConfidence {
  /** Strictly in [0.0, 1.0], or null when nothing has calibrated a score.
   *  Null is not "low confidence" -- it is "no confidence was computed", and
   *  the UI must render it as an em dash, never as a default figure. */
  score: number | null
  band: ConfidenceBand
  penaltyFactors: string[]
  components?: ConfidenceComponents
}

export interface SimplexProbabilities {
  bullish: number
  bearish: number
  neutral: number
}

export type TrendState = 'strong_up' | 'up' | 'flat' | 'down' | 'strong_down' | 'unmeasured'

export interface TrendContext {
  state: TrendState
  slope: number | null
  kalmanVelocity: number | null
  kalmanZScore: number | null
  trendPersistence: number | null
  measured: boolean
}

export type VolatilityStateType = 'compression' | 'normal' | 'elevated' | 'shock' | 'unmeasured'

export interface VolatilityContext {
  state: VolatilityStateType
  realizedVolPct: number | null
  impliedVolPct: number | null
  volPercentile: number | null
  parkinsonVolPct: number | null
  ivHvRatio: number | null
  measured: boolean
}

export type MarketStructureType = 'trending' | 'mean_reverting' | 'range_bound' | 'unmeasured'

export interface StructureContext {
  state: MarketStructureType
  ouHalfLifeBars: number | null
  hurstExponent: number | null
  breakoutZScore: number | null
  exhaustionZScore: number | null
  measured: boolean
}

export type FlowStateType = 'accumulation' | 'distribution' | 'churn' | 'balanced' | 'unmeasured'

export interface FlowContext {
  state: FlowStateType
  dealerGammaRegime: GammaRegime // 'short' | 'long' | 'flip' | 'unmeasurable'
  netGexM: number | null
  netVexM: number | null
  netCharmDriftM: number | null
  orderFlowDeltaM: number | null
  hedgingPressureDirection: 'supportive' | 'pressuring' | 'neutral' | string
  measured: boolean
}

export type TransitionRiskLevel = 'low' | 'moderate' | 'high' | 'critical'

export interface TransitionRisk {
  level: TransitionRiskLevel
  changepointProb5d: number | null
  changepointProb20d: number | null
  mapRunLength: number | null
  expectedRunLength: number | null
  stabilityScore: number | null
  measured: boolean
}

export type TransitionState = TransitionRisk

export type AgreementBand = 'high' | 'moderate' | 'low' | 'conflict'

export interface PairwiseConflictDetail {
  conflictCode: string
  modelA: string
  modelB: string
  correlation: number
  severity: 'HIGH' | 'CRITICAL' | 'MEDIUM' | string
  explanation: string
}

export type PairwiseConflict = PairwiseConflictDetail

export interface ModelAgreement {
  band: AgreementBand
  agreementScore: number | null
  agreeingModels: string[]
  conflictingModels: string[]
  divergenceSummary: string | null
  pairwiseMatrix?: Record<string, Record<string, number>> | null
  conflicts?: PairwiseConflictDetail[]
}

export type ModelAgreementState = ModelAgreement

export interface DynamicExplanation {
  headline: string
  summary: string
  leadingDrivers: string[]
  riskFactors: string[]
  uncertaintySources: string[]
}

export type DynamicExplanationState = DynamicExplanation

export interface RegimeStructuralLevels {
  callWall: number | null
  putWall: number | null
  gammaFlip: number | null
  sessionVwap: number | null
}

export interface RegimeQuality {
  measurable: boolean
  missingLenses: string[]
  reason: string | null
  dataCompleteness?: number
}

export interface MarketRegimePayload {
  symbol: string
  asof_utc: string
  spot: number | null
  primary: PrimaryRegimeType
  primaryLabel: string
  confidence: CalibratedConfidence
  probabilities?: SimplexProbabilities | null
  trend: TrendContext
  volatility: VolatilityContext
  structure: StructureContext
  flow: FlowContext
  transition: TransitionRisk
  agreement: ModelAgreement
  explanation: DynamicExplanation
  levels: RegimeStructuralLevels
  quality: RegimeQuality
  cache?: { hit: boolean; age_seconds: number; ttl_seconds: number }
}
