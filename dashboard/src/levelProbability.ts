/**
 * How likely is price to REACH a level — not to close beyond it.
 *
 * The /regime page had exactly two probabilities: P(settle above the call
 * wall) and P(settle below the put wall), both terminal, both withheld the
 * moment the risk-neutral density graded unusable. Neither answers the
 * question an operator actually asks of a level ladder, which is "does it get
 * there at all, and how soon". Terminal probability systematically understates
 * that: SPY can tag the call wall at 11:00 and settle back inside it, and the
 * terminal number scores that day as a miss.
 *
 * So this module computes FIRST-PASSAGE (touch) probability, which is the
 * right statistic for a level: P(the running max/min crosses the barrier at
 * any point before the horizon). Under GBM it has a closed form via the
 * reflection principle, so there is no simulation and no sampling error.
 *
 * Log price X_t = ln(S_t / S_0) is Brownian with drift mu = r - sigma^2/2 and
 * diffusion sigma. For a barrier b = ln(L / S_0):
 *
 *   b > 0 (level above spot):
 *     P(max X >= b) = N((mu T - b) / (sigma sqrt T))
 *                     + exp(2 mu b / sigma^2) N((-b - mu T) / (sigma sqrt T))
 *   b < 0 (level below spot):
 *     P(min X <= b) = N((b - mu T) / (sigma sqrt T))
 *                     + exp(2 mu b / sigma^2) N((b + mu T) / (sigma sqrt T))
 *
 * With zero drift both collapse to 2 N(-|b| / (sigma sqrt T)) — the textbook
 * reflection result, and a useful sanity check on the implementation.
 *
 * TERMINAL probability is kept alongside, because the pair is informative:
 * a level with a high touch probability and a low terminal one is a level the
 * market visits and rejects, which is precisely what "resistance" means.
 */
import { normalCdf } from '@/regimeSignals'

/** Ceiling on the exp() term. 2*mu*b/sigma^2 overflows to Infinity for a very
 *  far barrier under a tiny sigma, and Infinity * 0 is NaN — a silent hole in
 *  the ladder. The companion N() is ~0 there, so clamping loses nothing real. */
const EXP_CLAMP = 700

export interface LevelProbability {
  /** P(price trades at or through the level at any point before the horizon). */
  touch: number
  /** P(price is beyond the level AT the horizon). Always <= touch. */
  terminal: number
  /** touch - terminal: the mass that visits and comes back. High = rejection. */
  rejection: number
  /** 'up' when the level sits above spot, 'down' when below. */
  direction: 'up' | 'down'
}

export interface LevelProbabilityInput {
  spot: number
  level: number
  /** Annualized implied vol as a decimal (0.24 = 24%). */
  sigma: number
  /** Year fraction to the horizon. A 0DTE read passes remainingSession / 252. */
  tYears: number
  /** Risk-free rate as a decimal. Defaults to 0: over an intraday horizon the
   *  drift term is noise next to sigma, and assuming a rate the caller did not
   *  supply would quietly tilt every level. */
  rate?: number
}

function clamp01(x: number): number {
  if (!Number.isFinite(x)) return 0
  return x < 0 ? 0 : x > 1 ? 1 : x
}

/**
 * First-passage and terminal probability for one level.
 *
 * Returns null — never a fabricated 50% — when any input makes the question
 * meaningless: no spot, no vol, no time. A level exactly at spot is already
 * touched, so it returns touch = 1 rather than dividing by a zero barrier.
 */
export function levelProbability(input: LevelProbabilityInput): LevelProbability | null {
  const { spot, level, sigma, tYears } = input
  const rate = input.rate ?? 0
  if (!Number.isFinite(spot) || spot <= 0) return null
  if (!Number.isFinite(level) || level <= 0) return null
  if (!Number.isFinite(sigma) || sigma <= 0) return null
  if (!Number.isFinite(tYears) || tYears <= 0) return null

  const b = Math.log(level / spot)
  const direction: 'up' | 'down' = b >= 0 ? 'up' : 'down'

  // Standing on the level. Touched by definition; terminal is the coin flip of
  // which side it settles, which the formulae below also give in the limit.
  if (b === 0) return { touch: 1, terminal: 0.5, rejection: 0.5, direction }

  const vol = sigma * Math.sqrt(tYears)
  const mu = rate - 0.5 * sigma * sigma
  const drift = mu * tYears
  const expArg = Math.min(EXP_CLAMP, Math.max(-EXP_CLAMP, (2 * mu * b) / (sigma * sigma)))
  const reflect = Math.exp(expArg)

  let touch: number
  let terminal: number
  if (b > 0) {
    terminal = normalCdf((drift - b) / vol)
    touch = terminal + reflect * normalCdf((-b - drift) / vol)
  } else {
    terminal = normalCdf((b - drift) / vol)
    touch = terminal + reflect * normalCdf((b + drift) / vol)
  }

  touch = clamp01(touch)
  terminal = clamp01(terminal)
  // Touch can only be understated relative to terminal by float noise; a
  // terminal beyond its own touch is not a thing the process can do.
  if (terminal > touch) terminal = touch
  return { touch, terminal, rejection: touch - terminal, direction }
}

/**
 * Year fraction for an intraday horizon expressed as a fraction of the
 * remaining session, on a 252-day trading year.
 *
 * Calendar time is the wrong clock for a 0DTE level: two hours of an RTH
 * session carries far more variance than two hours of a weekend, and the ATM
 * IV the caller passes is quoted on trading time.
 */
export function sessionYears(sessionFractionRemaining: number): number {
  if (!Number.isFinite(sessionFractionRemaining) || sessionFractionRemaining <= 0) return 0
  return Math.min(1, sessionFractionRemaining) / 252
}

/** Year fraction for a whole-day horizon count, on the same trading clock. */
export function tradingDayYears(days: number): number {
  if (!Number.isFinite(days) || days <= 0) return 0
  return days / 252
}

export interface HorizonSpec {
  key: string
  /** Shown verbatim beside the number — a probability without its horizon is
   *  unreadable, so no caller is allowed to omit one. */
  label: string
  tYears: number
}

/**
 * The same level priced across several horizons.
 *
 * A wall 1.2% away is a near-certainty over a month and a coin flip by the
 * close; showing one number invites the operator to read it as the other.
 */
export function levelProbabilityByHorizon(
  spot: number,
  level: number,
  sigma: number,
  horizons: HorizonSpec[],
  rate = 0,
): Array<{ horizon: HorizonSpec; prob: LevelProbability | null }> {
  return horizons.map((horizon) => ({
    horizon,
    prob: levelProbability({ spot, level, sigma, tYears: horizon.tYears, rate }),
  }))
}

/**
 * Expected time to first touch, in the same units as `tYears`, conditional on
 * touching at all.
 *
 * Derived by bisection on the horizon at which touch probability reaches half
 * the supplied horizon's probability — the MEDIAN time to touch among paths
 * that touch. The mean is infinite for a driftless barrier, so it is not a
 * usable readout; the median is finite and is what "usually gets there by"
 * means to an operator. Null when the level is effectively unreachable inside
 * the horizon (touch < 1%), because a median over ~no paths is not a number.
 */
export function medianTimeToTouch(input: LevelProbabilityInput): number | null {
  const full = levelProbability(input)
  if (!full || full.touch < 0.01) return null
  const target = full.touch / 2
  let lo = 0
  let hi = input.tYears
  for (let i = 0; i < 60; i += 1) {
    const mid = (lo + hi) / 2
    const p = levelProbability({ ...input, tYears: mid })
    if (p == null) return null
    if (p.touch < target) lo = mid
    else hi = mid
  }
  return (lo + hi) / 2
}
