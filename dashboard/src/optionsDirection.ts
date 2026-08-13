import type { OptionsSqueeze } from '@/api'

export type OptionsDirectionState = 'bullish' | 'bearish' | 'mixed' | 'neutral' | 'unavailable'
export type OptionsDirectionConfidence = 'high' | 'medium' | 'low' | 'wait'

export interface OptionsActivityShift {
  signed_imbalance?: number | null
  shifted?: boolean | null
  last_shift_kind?: string | null
  n?: number | null
  confidence_band?: string | null
}

export interface OptionsDirectionSummary {
  activity_imbalance?: number | null
  signed_flow_imbalance?: number | null
  signed_flow_confidence?: number | null
  signed_flow_confidence_band?: string | null
  gamma_flip?: number | null
  call_wall?: number | null
  put_wall?: number | null
  squeeze?: OptionsSqueeze | null
  activity_shift?: OptionsActivityShift | null
}

export interface OptionsDirectionRead {
  state: OptionsDirectionState
  confidence: OptionsDirectionConfidence
  headline: string
  subhead: string
  basis: string
  score: number | null
  signedFlow: number | null
  signedConfidence: number | null
  momentum: number | null
  momentumFresh: boolean
  activity: 'call' | 'put' | 'balanced' | 'unavailable'
  activityLabel: string
  callPct: number | null
  putPct: number | null
  drivers: string[]
  confirmationTitle: string
  confirmation: string
  stale: boolean
  tapeStale: boolean
  activityShifted: boolean
}

const DRIVER_LABELS: Record<string, string> = {
  short_premium_dealer_gamma: 'short dealer gamma',
  negative_charting_near_gex: 'negative near-spot GEX',
  long_gamma_dampens: 'long-gamma dampening',
  signed_bullish_flow: 'signed bullish flow',
  signed_bearish_flow: 'signed bearish flow',
  up_momentum: 'upside momentum',
  down_momentum: 'downside momentum',
  call_wall_proximity: 'near the call wall',
  put_wall_proximity: 'near the put wall',
  atm_gamma_concentration: 'ATM gamma concentration',
  short_dated_urgency: 'short-dated urgency',
  near_gamma_flip: 'near the gamma flip',
}

function finite(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function side(value: number | null, threshold: number): 'bullish' | 'bearish' | null {
  if (value == null || Math.abs(value) < threshold) return null
  return value > 0 ? 'bullish' : 'bearish'
}

function money(value: number | null | undefined): string | null {
  const parsed = finite(value)
  if (parsed == null) return null
  return `$${parsed.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

function activityRead(imbalance: number | null): Pick<
  OptionsDirectionRead,
  'activity' | 'activityLabel' | 'callPct' | 'putPct'
> {
  if (imbalance == null) {
    return {
      activity: 'unavailable',
      activityLabel: 'NO ACTIVITY MIX',
      callPct: null,
      putPct: null,
    }
  }

  const callPct = Math.round(Math.max(0, Math.min(1, (imbalance + 1) / 2)) * 100)
  const putPct = 100 - callPct
  if (callPct >= 58) {
    return { activity: 'call', activityLabel: 'CALL-HEAVY ACTIVITY', callPct, putPct }
  }
  if (putPct >= 58) {
    return { activity: 'put', activityLabel: 'PUT-HEAVY ACTIVITY', callPct, putPct }
  }
  return { activity: 'balanced', activityLabel: 'BALANCED ACTIVITY', callPct, putPct }
}

/**
 * Build the one direction read used across the Options workspace.
 *
 * Contract right (call/put) is deliberately excluded from direction. The side
 * can only come from the backend's squeeze model, whose directional terms are
 * explicitly signed flow and fresh underlying momentum. When those terms
 * disagree, the honest result is mixed even if one narrowly wins the score.
 */
export function buildOptionsDirection(
  summary: OptionsDirectionSummary | null | undefined,
  tapeStatus = 'missing',
): OptionsDirectionRead {
  const stale = ['stale', 'warm', 'history', 'proxy', 'missing'].includes(tapeStatus)
  if (!summary) {
    return {
      state: 'unavailable',
      confidence: 'wait',
      headline: 'AWAITING DATA',
      subhead: 'Load a measured options chain to build the underlier read.',
      basis: 'NO MEASURED INPUTS',
      score: null,
      signedFlow: null,
      signedConfidence: null,
      momentum: null,
      momentumFresh: false,
      activity: 'unavailable',
      activityLabel: 'NO ACTIVITY MIX',
      callPct: null,
      putPct: null,
      drivers: [],
      confirmationTitle: 'LOAD A MEASURED CHAIN',
      confirmation: 'Direction stays blank until signed flow or fresh momentum reaches the squeeze model.',
      stale,
      tapeStale: stale,
      activityShifted: false,
    }
  }

  const squeeze = summary.squeeze ?? null
  const theory = squeeze?.theory
  const score = finite(squeeze?.score)
  const rawSignedFlow = finite(summary.signed_flow_imbalance)
  const rawSignedConfidence = finite(summary.signed_flow_confidence)
  // Some older payloads serialize an absent signed sample as 0/0. Treat that
  // as missing evidence, not a measured neutral observation.
  const hasSignedSample = rawSignedFlow != null && (rawSignedConfidence == null || rawSignedConfidence > 0)
  const signedFlow = hasSignedSample ? rawSignedFlow : null
  const signedConfidence = hasSignedSample ? rawSignedConfidence : null
  const momentumFresh = theory?.momentum_fresh !== false
  const momentum = momentumFresh ? finite(theory?.momentum) : null
  const flowSide = side(signedFlow, 0.05)
  const momentumSide = side(momentum, 0.005)
  const conflict = flowSide != null && momentumSide != null && flowSide !== momentumSide
  const primary = squeeze?.primary
  const tapeStale = stale
  // Tape lag is not the same as a dead directional input. Fresh momentum can
  // still lean the underlier after the options feed goes quiet after hours.
  const inputsStale = (signedFlow == null) && !momentumFresh

  let state: OptionsDirectionState = 'neutral'
  if (conflict || primary === 'two_way') state = 'mixed'
  else if ((primary === 'bullish' || primary === 'bearish') && score != null && Math.abs(score) >= 20) {
    state = primary
  } else if (flowSide != null) {
    state = flowSide
  } else if (momentumSide != null) {
    state = momentumSide
  }

  const aligned = flowSide != null && momentumSide != null && flowSide === momentumSide
  let basis = 'NO SIGNED DIRECTION'
  if (aligned) basis = 'SIGNED FLOW + MOMENTUM'
  else if (flowSide != null && momentumSide != null) basis = 'CONFLICTING FLOW + MOMENTUM'
  else if (flowSide != null) basis = 'SIGNED FLOW'
  else if (momentumSide != null) basis = 'PRICE MOMENTUM'
  else if (state === 'bullish' || state === 'bearish') basis = 'GAMMA SQUEEZE MODEL'

  let headline = 'NO DIRECTION'
  let subhead = 'No qualified directional edge yet — keep this name on watch.'
  if (state === 'bullish') {
    headline = 'BULLISH'
    subhead = basis === 'PRICE MOMENTUM'
      ? 'Fresh price momentum is leading. Tape has no buy/sell side — this is not a signed squeeze.'
      : 'Upside squeeze conditions are leading for the underlier.'
  } else if (state === 'bearish') {
    headline = 'BEARISH'
    subhead = basis === 'PRICE MOMENTUM'
      ? 'Fresh price momentum is leading. Tape has no buy/sell side — this is not a signed squeeze.'
      : 'Downside squeeze conditions are leading for the underlier.'
  } else if (state === 'mixed') {
    headline = 'MIXED / WAIT'
    subhead = conflict
      ? 'Signed flow and price momentum disagree — there is no clean side.'
      : 'Two-way squeeze pressure is elevated without a clean side.'
  }

  let confidence: OptionsDirectionConfidence = state === 'neutral' || state === 'mixed' ? 'wait' : 'low'
  if (state === 'bullish' || state === 'bearish') {
    let points = 0
    const magnitude = Math.abs(score ?? 0)
    if (magnitude >= 60) points += 2
    else if (magnitude >= 35) points += 1
    if ((signedConfidence ?? 0) >= 0.75) points += 2
    else if ((signedConfidence ?? 0) >= 0.375) points += 1
    if (momentumSide != null) points += 1
    if (aligned) points += 1
    if (tapeStale) points -= 1
    // Momentum-only, or tape-only without a squeeze fire, cannot be high.
    if (signedFlow == null) points = Math.min(points, 2)
    confidence = points >= 4 ? 'high' : points >= 2 ? 'medium' : 'low'
    if (signedFlow == null && confidence === 'high') confidence = 'medium'
  }

  const activity = activityRead(finite(summary.activity_imbalance))
  const activityShifted = Boolean(summary.activity_shift?.shifted)
  const drivers = (squeeze?.drivers ?? [])
    .map((driver) => DRIVER_LABELS[driver] ?? driver.replaceAll('_', ' '))
    .slice(0, 4)
  if (activityShifted) drivers.unshift('activity shift on tape')

  const flip = money(summary.gamma_flip)
  const callWall = money(summary.call_wall)
  const putWall = money(summary.put_wall)
  let confirmationTitle = 'WAIT FOR DIRECTIONAL EVIDENCE'
  let confirmation = 'Calls versus puts describe contract activity, not intent. Wait for signed side or fresh momentum before assigning direction.'

  if (state === 'bullish' || state === 'bearish') {
    const upside = state === 'bullish'
    confirmationTitle = upside ? 'CONFIRM THE UPSIDE CASE' : 'CONFIRM THE DOWNSIDE CASE'
    if (basis === 'PRICE MOMENTUM') {
      confirmation = [
        `Direction is from fresh price momentum (${momentum != null ? `${(momentum * 100).toFixed(1)}%` : 'measured'}).`,
        'The tape has no buy/sell side, so this is not a signed-flow squeeze.',
        'Call/put mix is contract identity, not intent.',
        upside
          ? (callWall ? `The ${callWall} call wall is the first upside structure test.` : null)
          : (putWall ? `The ${putWall} put wall is the first downside structure test.` : null),
      ].filter(Boolean).join(' ')
    } else {
      confirmation = [
        'Look for signed flow and momentum to remain aligned.',
        flip ? `Use the ${flip} gamma flip as the nearest regime checkpoint.` : null,
        upside
          ? (callWall ? `The ${callWall} call wall is the first upside structure test.` : null)
          : (putWall ? `The ${putWall} put wall is the first downside structure test.` : null),
      ].filter(Boolean).join(' ')
    }
  } else if (state === 'mixed') {
    confirmationTitle = 'RESOLVE THE CONFLICT'
    confirmation = 'Wait for signed flow and fresh momentum to agree. Until then, use the walls as scenario boundaries rather than a directional call.'
  }

  return {
    state,
    confidence,
    headline,
    subhead,
    basis,
    score,
    signedFlow,
    signedConfidence,
    momentum,
    momentumFresh,
    ...activity,
    drivers,
    confirmationTitle,
    confirmation,
    stale: inputsStale,
    tapeStale,
    activityShifted,
  }
}
