/**
 * Rule of 16 Expected Move & Volatility Boundary Calculations.
 *
 * The Rule of 16 states:
 *   1-Day Expected Move (EM_1d) = Spot * (IV / 16)
 *   Since sqrt(252) ≈ 15.87 ≈ 16 trading days in a standard year.
 *
 * Horizons:
 *   - 1-Day:   Spot * (IV / 16)
 *   - 1-Week:  Spot * (IV / 16) * sqrt(5) ≈ Spot * (IV / 7.155)
 *   - 1-Month: Spot * (IV / sqrt(12)) ≈ Spot * (IV / 3.464)
 */

export interface ExpectedMoveMetrics {
  spot: number
  ivAnnualPct: number
  em1dDollars: number
  em1dPct: number
  em1dLow: number
  em1dHigh: number
  em1wDollars: number
  em1wPct: number
  em1wLow: number
  em1wHigh: number
  em1mDollars: number
  em1mPct: number
  em1mLow: number
  em1mHigh: number
  vixRef?: number | null
  /** Which volatility actually produced these numbers. The panel used to label
   *  the corridor "(VIX / 16)" unconditionally while feeding it the symbol's
   *  own ATM IV, so a name at 88% IV printed a 5.5% daily band under a caption
   *  claiming it came from a 15.7 VIX -- a 5.6x discrepancy between the label
   *  and the arithmetic. */
  ivBasis: 'atm_iv' | 'vix_proxy'
  /** Ready-to-render caption for the basis, e.g. "ATM IV 88.0% / 16". */
  ivBasisLabel: string
  /** Institutional skew-calibrated asymmetric bounds & multi-tier cones */
  em1dUpDollars?: number
  em1dDownDollars?: number
  em1dMedianLow?: number
  em1dMedianHigh?: number
  em1dTail95Low?: number
  em1dTail95High?: number
  method?: 'rule_of_16' | 'calibrated_calendar'
}

/**
 * Institutional Calibrated Expected Move calculation.
 * Accounts for 365 calendar days option quoting convention and skew asymmetry.
 */
export function computeCalibratedExpectedMove(
  spot: number | null | undefined,
  ivOrVix: number | null | undefined,
  vixRef?: number | null,
  options?: {
    putIvPct?: number | null
    callIvPct?: number | null
    straddlePrice?: number | null
    useCalendarDays?: boolean
  },
): ExpectedMoveMetrics | null {
  if (!spot || spot <= 0) return null

  let rawIv = Number(ivOrVix)
  if (!Number.isFinite(rawIv) || rawIv <= 0) {
    if (vixRef && Number.isFinite(vixRef) && vixRef > 0) {
      rawIv = vixRef
    } else {
      return null
    }
  }

  const usedVixFallback = !Number.isFinite(Number(ivOrVix)) || Number(ivOrVix) <= 0
  const ivDec = rawIv > 1.5 ? rawIv / 100.0 : rawIv
  const ivAnnualPct = ivDec * 100.0
  const ivBasis: 'atm_iv' | 'vix_proxy' = usedVixFallback ? 'vix_proxy' : 'atm_iv'
  const useCalendar = options?.useCalendarDays ?? true
  const daysInYear = useCalendar ? 365.0 : 252.0
  const denom1d = Math.sqrt(daysInYear) // 19.10 for calendar, 15.87 for trading
  const ivBasisLabel = usedVixFallback
    ? `VIX ${ivAnnualPct.toFixed(1)} (1/√${Math.round(daysInYear)})`
    : `ATM IV ${ivAnnualPct.toFixed(1)}% (1/√${Math.round(daysInYear)})`

  // 1-Day Move with calendar-day scaling
  const em1dDollars = spot * (ivDec / denom1d)
  const em1dPct = (ivDec / denom1d) * 100.0

  // Skew-aware bounds if put/call IV provided
  let em1dUpDollars = em1dDollars
  let em1dDownDollars = em1dDollars
  if (options?.callIvPct && options.callIvPct > 0) {
    const cIvDec = options.callIvPct > 1.5 ? options.callIvPct / 100.0 : options.callIvPct
    em1dUpDollars = spot * (cIvDec / denom1d)
  }
  if (options?.putIvPct && options.putIvPct > 0) {
    const pIvDec = options.putIvPct > 1.5 ? options.putIvPct / 100.0 : options.putIvPct
    em1dDownDollars = spot * (pIvDec / denom1d)
  }

  const em1dLow = Math.max(0, spot - em1dDownDollars)
  const em1dHigh = spot + em1dUpDollars

  // 1-Week Move (7 calendar days or 5 trading days)
  const weekDays = useCalendar ? 7.0 : 5.0
  const weekFactor = Math.sqrt(weekDays / daysInYear)
  const em1wDollars = spot * (ivDec * weekFactor)
  const em1wPct = ivDec * weekFactor * 100.0
  const em1wLow = Math.max(0, spot - em1wDollars)
  const em1wHigh = spot + em1wDollars

  // 1-Month Move (30 calendar days or 21 trading days)
  const monthDays = useCalendar ? 30.4375 : 21.0
  const monthFactor = Math.sqrt(monthDays / daysInYear)
  const em1mDollars = spot * (ivDec * monthFactor)
  const em1mPct = ivDec * monthFactor * 100.0
  const em1mLow = Math.max(0, spot - em1mDollars)
  const em1mHigh = spot + em1mDollars

  // Multi-tier cones
  const em1dMedianLow = Math.max(0, spot - 0.6745 * em1dDownDollars)
  const em1dMedianHigh = spot + 0.6745 * em1dUpDollars
  const em1dTail95Low = Math.max(0, spot - 2.0 * em1dDownDollars)
  const em1dTail95High = spot + 2.0 * em1dUpDollars

  return {
    spot,
    ivAnnualPct,
    em1dDollars,
    em1dPct,
    em1dLow,
    em1dHigh,
    em1wDollars,
    em1wPct,
    em1wLow,
    em1wHigh,
    em1mDollars,
    em1mPct,
    em1mLow,
    em1mHigh,
    vixRef,
    ivBasis,
    ivBasisLabel,
    em1dUpDollars,
    em1dDownDollars,
    em1dMedianLow,
    em1dMedianHigh,
    em1dTail95Low,
    em1dTail95High,
    method: 'calibrated_calendar',
  }
}

export function computeRuleOf16ExpectedMove(
  spot: number | null | undefined,
  ivOrVix: number | null | undefined,
  vixRef?: number | null,
): ExpectedMoveMetrics | null {
  if (!spot || spot <= 0) return null

  // If IV is passed as a fraction (e.g. 0.22) vs percentage (22.0)
  let rawIv = Number(ivOrVix)
  if (!Number.isFinite(rawIv) || rawIv <= 0) {
    if (vixRef && Number.isFinite(vixRef) && vixRef > 0) {
      rawIv = vixRef
    } else {
      return null
    }
  }

  const usedVixFallback = !Number.isFinite(Number(ivOrVix)) || Number(ivOrVix) <= 0
  const ivDec = rawIv > 1.5 ? rawIv / 100.0 : rawIv
  const ivAnnualPct = ivDec * 100.0
  const ivBasis: 'atm_iv' | 'vix_proxy' = usedVixFallback ? 'vix_proxy' : 'atm_iv'
  const ivBasisLabel = usedVixFallback
    ? `VIX ${ivAnnualPct.toFixed(1)} / 16`
    : `ATM IV ${ivAnnualPct.toFixed(1)}% / 16`

  // 1-Day Move (Rule of 16)
  const em1dDollars = spot * (ivDec / 16.0)
  const em1dPct = (ivDec / 16.0) * 100.0
  const em1dLow = Math.max(0, spot - em1dDollars)
  const em1dHigh = spot + em1dDollars

  // 1-Week Move (5 trading days: sqrt(5/252) ≈ 1/7.10)
  const sqrt5Factor = Math.sqrt(5.0) / 15.8745 // ≈ 0.1408
  const em1wDollars = spot * (ivDec * sqrt5Factor)
  const em1wPct = ivDec * sqrt5Factor * 100.0
  const em1wLow = Math.max(0, spot - em1wDollars)
  const em1wHigh = spot + em1wDollars

  // 1-Month Move (21 trading days / sqrt(12))
  const sqrtMonthFactor = 1.0 / Math.sqrt(12.0) // ≈ 0.2887
  const em1mDollars = spot * (ivDec * sqrtMonthFactor)
  const em1mPct = ivDec * sqrtMonthFactor * 100.0
  const em1mLow = Math.max(0, spot - em1mDollars)
  const em1mHigh = spot + em1mDollars

  return {
    spot,
    ivAnnualPct,
    em1dDollars,
    em1dPct,
    em1dLow,
    em1dHigh,
    em1wDollars,
    em1wPct,
    em1wLow,
    em1wHigh,
    em1mDollars,
    em1mPct,
    em1mLow,
    em1mHigh,
    vixRef,
    ivBasis,
    ivBasisLabel,
  }
}

export interface ExcursionAssessment {
  ratio: number
  status: 'within_normal' | 'expansion' | 'abnormal_breakout'
  label: string
  colorVar: string
}

export function assessMoveExcursion(
  dayChangeDollars: number,
  em1dDollars: number,
): ExcursionAssessment {
  if (!em1dDollars || em1dDollars <= 0) {
    return {
      ratio: 0,
      status: 'within_normal',
      label: 'Normal Implied Range',
      colorVar: 'var(--ink-dim)',
    }
  }

  const ratio = Math.abs(dayChangeDollars) / em1dDollars

  if (ratio <= 0.8) {
    return {
      ratio,
      status: 'within_normal',
      label: `${(ratio * 100).toFixed(0)}% of 1D EM · Consolidation within 1σ`,
      colorVar: 'var(--ink-dim)',
    }
  } else if (ratio <= 1.2) {
    return {
      ratio,
      status: 'expansion',
      label: `${(ratio * 100).toFixed(0)}% of 1D EM · Testing 1σ Boundary`,
      colorVar: 'var(--warn)',
    }
  } else {
    return {
      ratio,
      status: 'abnormal_breakout',
      label: `${ratio.toFixed(2)}x 1D EM · Abnormal Volatility Breakout (>1σ)`,
      colorVar: 'var(--call-hi)',
    }
  }
}

export interface WallSpatialStatus {
  callWallInside1d: boolean
  putWallInside1d: boolean
  callWallDistEmRatio: number | null
  putWallDistEmRatio: number | null
}

export function assessWallAlignment(
  callWall: number | null | undefined,
  putWall: number | null | undefined,
  spot: number,
  em1dDollars: number,
): WallSpatialStatus {
  const result: WallSpatialStatus = {
    callWallInside1d: false,
    putWallInside1d: false,
    callWallDistEmRatio: null,
    putWallDistEmRatio: null,
  }

  if (!em1dDollars || em1dDollars <= 0 || !spot || spot <= 0) return result

  if (callWall && callWall > spot) {
    const dist = callWall - spot
    result.callWallDistEmRatio = dist / em1dDollars
    result.callWallInside1d = callWall <= spot + em1dDollars
  }

  if (putWall && putWall < spot) {
    const dist = spot - putWall
    result.putWallDistEmRatio = dist / em1dDollars
    result.putWallInside1d = putWall >= spot - em1dDollars
  }

  return result
}
