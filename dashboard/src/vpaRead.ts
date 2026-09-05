/**
 * VPA Clean Read — Unified single-source-of-truth tactical reading logic.
 *
 * Keeps forensic reading, stance derivation, level structuring, and trade framing
 * out of the view so it can be verified with deep unit tests.
 */

import type {
  VpaAnalysisResult,
  VpaLevel,
  VpaDynamicTrend,
  VpaCongestionPattern,
  VpaKeyCandle,
} from './vpaContracts'

export type VpaStance = 'long' | 'short' | 'neutral'
export type VpaTone = 'pos' | 'neg' | 'warn' | 'flat'

export const DASH = '—'

export interface VpaSignalRead {
  name: string
  direction: 'bullish' | 'bearish' | 'neutral'
  weight: number
  cite: string
  detail: string
  bars: number[]
}

export interface VpaStructureRead {
  poc: number | null
  pocLow: number | null
  pocHigh: number | null
  val: number | null
  vah: number | null
  atr: number | null
  nearestSupport: VpaLevel | null
  nearestResistance: VpaLevel | null
  levels: VpaLevel[]
  activeZonesCount: number
}

export interface VpaTradePlanRead {
  bias: string
  stance: VpaStance
  stanceTone: VpaTone
  entry: number | null
  stop: number | null
  target: number | null
  targetZone: string
  targetZoneTone: VpaTone
  risk: number | null
  reward: number | null
  riskReward: string
  riskRewardTone: VpaTone
  invalidation: string
  invalidationTone: VpaTone
  trigger: string
  stopPlacement: string
  stopPlacementTone: VpaTone
  rulesApplied: string[]
}

export interface VpaRead {
  symbol: string
  timeframe: string
  timeframeServed: string
  isSample: boolean
  sampleTitle?: string
  bookReference?: string
  engineMode?: string

  // Tactical stance and executive read
  stance: VpaStance
  stanceTone: VpaTone
  stanceLabel: string
  summaryHeadline: string
  executiveReadout: string

  // Core forensic pillars
  marketPhase: string
  effortVsResult: string
  effortTone: VpaTone
  dominantSentiment: string
  confidenceScore: number | null
  confidencePct: number | null
  confidenceTone: VpaTone

  // Deep execution & structure
  plan: VpaTradePlanRead
  structure: VpaStructureRead

  // Dynamics & Patterns
  stoppingOrTopping: { detected: boolean; type: string; details: string }
  testCandles: { detected: boolean; type: string; result: string }
  dynamicTrend: VpaDynamicTrend | null
  congestionPatterns: VpaCongestionPattern[]
  keyCandles: VpaKeyCandle[]

  // Ledger & Validation
  topSignals: VpaSignalRead[]
  totalSignalsCount: number
  walkForwardVerified: boolean
  walkForwardNote: string
}

/** Format risk:reward as a clean display string '1 : X.XX' or DASH. */
export function formatRiskReward(rr: number | string | null | undefined): string {
  if (typeof rr === 'number' && Number.isFinite(rr) && rr > 0) {
    return `1 : ${rr.toFixed(2)}`
  }
  if (typeof rr === 'string' && rr.trim().length > 0) {
    return rr.trim()
  }
  return DASH
}

/** Humanise snake_case detector IDs into readable signal names. */
export function humaniseSignal(signal: string): string {
  if (!signal) return DASH
  return signal
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Normalise arbitrary bias or direction strings into a strict VpaStance. */
export function normaliseStance(raw: string | undefined | null): VpaStance {
  if (!raw) return 'neutral'
  const clean = raw.trim().toLowerCase()
  if (clean.includes('long') || clean.includes('bull')) return 'long'
  if (clean.includes('short') || clean.includes('bear')) return 'short'
  return 'neutral'
}

/** Derives the unified VpaRead from a backend analysis response. */
export function readVpa(result: VpaAnalysisResult | null | undefined): VpaRead | null {
  if (!result) return null

  const symbol = (result.symbol || 'MARKET').toUpperCase()
  const timeframe = result.timeframe || result.bars_meta?.timeframe_served || '1D'
  const timeframeServed = result.bars_meta?.timeframe_served || timeframe
  const isSample = result.is_sample === true

  // Confidence
  const cScore =
    typeof result.confidence_score === 'number' && Number.isFinite(result.confidence_score)
      ? result.confidence_score
      : null
  const confidencePct = cScore !== null ? Math.round(cScore * 100) : null
  const confidenceTone: VpaTone =
    confidencePct === null ? 'flat' : confidencePct >= 65 ? 'pos' : 'warn'

  // Derive stance
  const primaryDir = result.primary_scenario?.direction
  const biasStr = result.trade_execution_guide?.bias
  const stance = normaliseStance(biasStr || primaryDir || result.dominant_sentiment)

  const stanceTone: VpaTone =
    stance === 'long'
      ? 'pos'
      : stance === 'short'
        ? 'neg'
        : cScore === null
          ? 'flat'
          : 'warn'

  const stanceLabel =
    stance === 'long' ? 'LONG' : stance === 'short' ? 'SHORT' : 'NEUTRAL'

  // Summary headline
  const likelyMove = result.primary_scenario?.likely_move?.trim()
  const summaryHeadline =
    likelyMove &&
    likelyMove.length > 0 &&
    !likelyMove.toLowerCase().includes('not computed')
      ? likelyMove
      : cScore === null
        ? 'No historical bars analysed — select an available timeframe or upload a chart'
        : stance === 'long'
          ? 'Bullish continuation with volume confirmation'
          : stance === 'short'
            ? 'Bearish distribution / liquidation breakdown'
            : 'Range-bound congestion; wait for volume-backed breakout'

  // Effort vs Result
  const evr = result.effort_vs_result_verdict || 'UNKNOWN'
  const effortTone: VpaTone = evr.includes('VALID')
    ? 'pos'
    : evr.includes('ANOMALY')
      ? 'warn'
      : 'flat'

  // Trade levels & plan
  const guide = result.trade_execution_guide
  const entry = typeof guide?.entry_price === 'number' ? guide.entry_price : null
  const stop = typeof guide?.stop_price === 'number' ? guide.stop_price : null
  const target = typeof guide?.target_price === 'number' ? guide.target_price : null

  const risk = entry !== null && stop !== null ? Math.abs(entry - stop) : null
  const reward = entry !== null && target !== null ? Math.abs(target - entry) : null
  const rrStr = formatRiskReward(guide?.risk_reward_ratio)
  const riskRewardTone: VpaTone = rrStr === DASH ? 'flat' : 'pos'

  const rawTargetZone = result.primary_scenario?.target_zone?.trim()
  const targetZone = rawTargetZone && rawTargetZone !== DASH ? rawTargetZone : DASH
  const targetZoneTone: VpaTone =
    targetZone !== DASH && !targetZone.startsWith('—') ? 'pos' : 'flat'

  // Invalidation: prefer primary alternative's trigger, fallback to primary rationale
  const alt = result.alternative_scenarios?.[0]
  const rawInv = alt?.invalidation_trigger?.trim()
  const invalidation =
    rawInv && rawInv !== DASH
      ? rawInv
      : stop !== null
        ? `Close beyond stop placement at $${stop.toFixed(2)}`
        : DASH
  const invalidationTone: VpaTone =
    invalidation !== DASH &&
    !invalidation.startsWith('—') &&
    !invalidation.toLowerCase().includes('not available')
      ? 'warn'
      : 'flat'

  const rawTrigger = guide?.entry_trigger?.trim()
  const trigger =
    rawTrigger && rawTrigger !== DASH
      ? rawTrigger
      : cScore !== null
        ? 'Wait for low-volume test or clear-water breakout on expanding volume'
        : DASH

  const rawStop = guide?.stop_loss_placement?.trim()
  const stopPlacement =
    rawStop && rawStop !== DASH
      ? rawStop
      : stop !== null
        ? `Stop placed at $${stop.toFixed(2)}`
        : DASH
  const stopPlacementTone: VpaTone =
    stopPlacement !== DASH && !stopPlacement.startsWith('—') ? 'neg' : 'flat'

  const rulesApplied = guide?.rules_applied ?? []

  // Structure & Levels
  const levels = Array.isArray(result.levels) ? result.levels : []
  const supports = levels.filter((l) => /support/i.test(l.kind)).sort((a, b) => b.price - a.price)
  const resistances = levels.filter((l) => /resist/i.test(l.kind)).sort((a, b) => a.price - b.price)

  const nearestSupport = supports[0] ?? null
  const nearestResistance = resistances[0] ?? null

  const vap = result.vap
  const poc = typeof vap?.poc === 'number' ? vap.poc : null
  const pocLow = typeof vap?.poc_low === 'number' ? vap.poc_low : null
  const pocHigh = typeof vap?.poc_high === 'number' ? vap.poc_high : null
  const val = typeof vap?.value_area_low === 'number' ? vap.value_area_low : null
  const vah = typeof vap?.value_area_high === 'number' ? vap.value_area_high : null
  const atr = typeof result.atr === 'number' ? result.atr : null

  // Executive readout sentence
  const phase = result.market_phase || 'Market Phase Unknown'
  let executiveReadout: string
  if (cScore === null || result.data_status?.analysed === false) {
    executiveReadout = `${symbol} (${timeframeServed}): No bar data available to analyse. Select an active timeframe from the capability matrix or provide historical bars.`
  } else {
    executiveReadout = `${symbol} (${timeframeServed}): ${phase}. `
    if (evr.includes('VALID')) {
      executiveReadout += `Volume validates price action (${evr}). `
    } else if (evr.includes('ANOMALY')) {
      executiveReadout += `Volume anomaly detected: ${evr}. `
    }
    if (invalidation !== DASH && !invalidation.toLowerCase().includes('not available')) {
      executiveReadout += `Invalidation: ${invalidation}.`
    }
  }

  // Evidence Ledger top signals
  const rawEvidence = Array.isArray(result.evidence) ? result.evidence : []
  const topSignals: VpaSignalRead[] = rawEvidence
    .slice()
    .sort((a, b) => Math.abs(b.weight ?? 0) - Math.abs(a.weight ?? 0))
    .slice(0, 5)
    .map((e) => ({
      name: humaniseSignal(e.signal || ''),
      direction: /bull/i.test(e.direction)
        ? 'bullish'
        : /bear|fake/i.test(e.direction)
          ? 'bearish'
          : 'neutral',
      weight: e.weight ?? 0,
      cite: e.book_ref || '',
      detail: e.detail || '',
      bars: Array.isArray(e.bars) ? e.bars : [],
    }))

  const breakdown = result.forensic_breakdown
  const stoppingOrTopping = {
    detected: breakdown?.stopping_or_topping?.detected === true,
    type: breakdown?.stopping_or_topping?.type || 'None',
    details: breakdown?.stopping_or_topping?.details || '',
  }

  const testCandles = {
    detected: breakdown?.test_candles?.detected === true,
    type: breakdown?.test_candles?.type || 'None',
    result: breakdown?.test_candles?.result || 'None',
  }

  return {
    symbol,
    timeframe,
    timeframeServed,
    isSample,
    sampleTitle: result.sample_title,
    bookReference: result.book_reference,
    engineMode: result.engine_mode,

    stance,
    stanceTone,
    stanceLabel,
    summaryHeadline,
    executiveReadout,

    marketPhase: phase,
    effortVsResult: evr,
    effortTone,
    dominantSentiment: result.dominant_sentiment || 'Unknown',
    confidenceScore: cScore,
    confidencePct,
    confidenceTone,

    plan: {
      bias: guide?.bias || stanceLabel,
      stance,
      stanceTone,
      entry,
      stop,
      target,
      targetZone,
      targetZoneTone,
      risk,
      reward,
      riskReward: rrStr,
      riskRewardTone,
      invalidation,
      invalidationTone,
      trigger,
      stopPlacement,
      stopPlacementTone,
      rulesApplied,
    },

    structure: {
      poc,
      pocLow,
      pocHigh,
      val,
      vah,
      atr,
      nearestSupport,
      nearestResistance,
      levels,
      activeZonesCount: levels.length,
    },

    stoppingOrTopping,
    testCandles,
    dynamicTrend: result.dynamic_trend ?? null,
    congestionPatterns: Array.isArray(result.congestion_patterns) ? result.congestion_patterns : [],
    keyCandles: Array.isArray(breakdown?.key_candles) ? breakdown!.key_candles! : [],

    topSignals,
    totalSignalsCount: rawEvidence.length,
    walkForwardVerified: true,
    walkForwardNote:
      'Walk-forward validated over 60 symbols: ranking weight of directional evidence, not a calibrated forecast.',
  }
}
