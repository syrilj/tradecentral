/**
 * Pure numeric statistics over `number[]` series — no I/O, no DOM, no
 * charting concerns. This is financial code: every function documents its
 * annualization convention and its degrees-of-freedom (ddof) choice
 * explicitly, because a silently-wrong Sharpe ratio is worse than a
 * thrown error.
 *
 * Convention: functions that return a single aggregate number (`maxDrawdown`,
 * `annVol`, `annReturn`, `sharpe`, `correlation`, `quantile`) return `NaN` —
 * never throw — when there isn't enough data to answer. Functions that
 * return one output per input sample (`rollingMean`, `rollingStd`) use
 * `null` per-element instead, since their return type already carries that
 * union. Sample standard deviation (ddof = 1, dividing by `n - 1`) is used
 * everywhere a "sample std" is called for below: `rollingStd`, `annVol`,
 * and `correlation`.
 */

/**
 * Period-over-period percent change. `out[0]` is always `0` by
 * definition (there is no prior period to compare it to).
 * Bad input: `[]` returns `[]`. A `0` in `v` produces `Infinity`/`NaN` at
 * that index (division by zero), matching plain JS division — it never
 * throws.
 */
export function pctChange(v: number[]): number[] {
  if (v.length === 0) return []
  const out: number[] = [0]
  for (let i = 1; i < v.length; i++) {
    out.push((v[i] - v[i - 1]) / v[i - 1])
  }
  return out
}

/**
 * Growth-of-1.0 curve: the running product of `(1 + r)` for each return
 * `r`. `cumulative(pctChange(prices))` reconstructs `prices[i] / prices[0]`
 * at every index (telescoping product), which is the standard way to
 * rebase a price series to compare it against another instrument.
 * Bad input: `[]` returns `[]`.
 */
export function cumulative(returns: number[]): number[] {
  const out: number[] = []
  let acc = 1
  for (const r of returns) {
    acc *= 1 + r
    out.push(acc)
  }
  return out
}

/**
 * Fractional drawdown from the running peak of a growth curve `cum`, as a
 * **negative** number (`0` at a new high, `-0.2` means 20% below the peak
 * so far). Feed it the output of `cumulative`.
 * Bad input: `[]` returns `[]`. If the running peak is ever exactly `0`
 * (a complete wipeout), that index returns `NaN` rather than dividing by
 * zero.
 */
export function drawdown(cum: number[]): number[] {
  if (cum.length === 0) return []
  const out: number[] = []
  let peak = cum[0]
  for (const v of cum) {
    if (v > peak) peak = v
    out.push(peak === 0 ? NaN : v / peak - 1)
  }
  return out
}

/**
 * The worst (most negative) drawdown reached by a growth curve `cum`, e.g.
 * `maxDrawdown([1, 1.5, 0.75, 1.2]) === -0.5` (peak of 1.5, trough of
 * 0.75). Same sign convention as `drawdown`: `0` or negative, never
 * positive.
 * Bad input: `[]` returns `NaN`. Any index where the running peak is `0`
 * is skipped (a `NaN` comparison is always `false`, so it can't corrupt
 * the running max); if every point is skipped this way, returns `0`.
 */
export function maxDrawdown(cum: number[]): number {
  if (cum.length === 0) return NaN
  let peak = cum[0]
  let worst = 0
  for (const v of cum) {
    if (v > peak) peak = v
    const dd = peak === 0 ? NaN : v / peak - 1
    if (dd < worst) worst = dd
  }
  return worst
}

/**
 * Simple moving average over a trailing window of `w` samples.
 * Bad input: non-finite windows never occur (width is floored); `w <= 0`
 * or `w > v.length` returns an all-`null` array of `v`'s length. The first
 * `w - 1` entries are always `null` (not enough history yet).
 */
export function rollingMean(v: number[], w: number): (number | null)[] {
  const n = v.length
  const out: (number | null)[] = new Array(n).fill(null)
  const win = Math.floor(w)
  if (win <= 0 || win > n) return out

  let sum = 0
  for (let i = 0; i < n; i++) {
    sum += v[i]
    if (i >= win) sum -= v[i - win]
    if (i >= win - 1) out[i] = sum / win
  }
  return out
}

/**
 * Sample standard deviation (ddof = 1, divides by `w - 1`) over a trailing
 * window of `w` samples.
 * Bad input: `w < 2` (ddof = 1 needs at least 2 points) or `w > v.length`
 * returns an all-`null` array of `v`'s length. The first `w - 1` entries
 * are always `null`.
 */
export function rollingStd(v: number[], w: number): (number | null)[] {
  const n = v.length
  const out: (number | null)[] = new Array(n).fill(null)
  const win = Math.floor(w)
  if (win < 2 || win > n) return out

  for (let i = win - 1; i < n; i++) {
    let sum = 0
    for (let j = i - win + 1; j <= i; j++) sum += v[j]
    const mean = sum / win

    let sumSq = 0
    for (let j = i - win + 1; j <= i; j++) sumSq += (v[j] - mean) ** 2
    out[i] = Math.sqrt(sumSq / (win - 1))
  }
  return out
}

/**
 * Exponential moving average with smoothing factor `alpha = 2 / (span + 1)`
 * (the standard "span" parameterization, matching e.g. pandas' `.ewm(span=)`).
 * The series is seeded with `v[0]` rather than a burn-in window, so the
 * output has the same length as the input from the first sample onward.
 * Bad input: `[]` returns `[]`. `span < 1` is floored to `1`, which makes
 * `alpha = 1` (no smoothing — the output equals the input).
 */
export function ema(v: number[], span: number): number[] {
  const n = v.length
  if (n === 0) return []

  const alpha = 2 / (Math.max(span, 1) + 1)
  const out: number[] = new Array(n)
  out[0] = v[0]
  for (let i = 1; i < n; i++) {
    out[i] = alpha * v[i] + (1 - alpha) * out[i - 1]
  }
  return out
}

/**
 * Annualized volatility: sample standard deviation (ddof = 1) of `returns`
 * scaled by `sqrt(periods)`. `periods` is the number of return periods per
 * year — 252 (trading days) by default; use 52 for weekly returns, 12 for
 * monthly.
 * Bad input: fewer than 2 returns can't form a sample std (ddof = 1 needs
 * `n - 1 >= 1`) — returns `NaN`.
 */
export function annVol(returns: number[], periods = 252): number {
  const n = returns.length
  if (n < 2) return NaN

  const mean = returns.reduce((a, b) => a + b, 0) / n
  const sumSq = returns.reduce((a, b) => a + (b - mean) ** 2, 0)
  const sampleStd = Math.sqrt(sumSq / (n - 1))
  return sampleStd * Math.sqrt(periods)
}

/**
 * Annualized (geometric) return: compounds `returns` into a growth
 * factor, then raises it to `periods / returns.length` and subtracts 1.
 * `periods` defaults to 252 (trading days/year); use 52 or 12 for weekly
 * or monthly returns.
 * Bad input: `[]` returns `NaN`. If the compounded growth factor is `<= 0`
 * (a -100%-or-worse period occurred, e.g. `r <= -1` somewhere), a
 * fractional power of a non-positive base is not a real number, so this
 * returns a floor of `-1` (-100%) instead of `NaN`.
 */
export function annReturn(returns: number[], periods = 252): number {
  const n = returns.length
  if (n === 0) return NaN

  let growth = 1
  for (const r of returns) growth *= 1 + r
  if (growth <= 0) return -1

  return Math.pow(growth, periods / n) - 1
}

/**
 * Annualized Sharpe ratio: mean excess return over sample-std (ddof = 1)
 * of excess return, scaled by `sqrt(periods)`. `rf` is an **annual**
 * risk-free rate (e.g. `0.05` for 5%); it is converted to a per-period
 * rate via `rf / periods` before being subtracted from each return.
 * `periods` defaults to 252 (trading days/year).
 * Bad input: fewer than 2 returns, or a return series with zero variance
 * (e.g. all identical values, so the std of excess returns is `0`),
 * returns `NaN` rather than dividing by zero — a Sharpe ratio is only
 * meaningful when there is dispersion to divide by.
 */
export function sharpe(returns: number[], rf = 0, periods = 252): number {
  const n = returns.length
  if (n < 2) return NaN

  const rfPerPeriod = rf / periods
  const excess = returns.map((r) => r - rfPerPeriod)
  const meanExcess = excess.reduce((a, b) => a + b, 0) / n
  const sumSq = excess.reduce((a, b) => a + (b - meanExcess) ** 2, 0)
  const std = Math.sqrt(sumSq / (n - 1))
  if (std === 0) return NaN

  return (meanExcess / std) * Math.sqrt(periods)
}

/**
 * Pearson correlation coefficient between `a` and `b`, computed from
 * sample covariance and sample variances (ddof = 1 throughout — the ratio
 * is ddof-invariant, but the intermediate sums are computed the sample way
 * for consistency with the rest of this module). Series of unequal length
 * are truncated to the shorter one, aligned from index 0.
 * Bad input: fewer than 2 overlapping points, or either series having
 * zero variance (constant), returns `NaN` — correlation against a
 * constant is mathematically undefined, not zero.
 */
export function correlation(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length)
  if (n < 2) return NaN

  let sa = 0
  let sb = 0
  for (let i = 0; i < n; i++) {
    sa += a[i]
    sb += b[i]
  }
  const meanA = sa / n
  const meanB = sb / n

  let cov = 0
  let varA = 0
  let varB = 0
  for (let i = 0; i < n; i++) {
    const da = a[i] - meanA
    const db = b[i] - meanB
    cov += da * db
    varA += da * da
    varB += db * db
  }
  cov /= n - 1
  varA /= n - 1
  varB /= n - 1

  const stdA = Math.sqrt(varA)
  const stdB = Math.sqrt(varB)
  if (stdA === 0 || stdB === 0) return NaN

  return cov / (stdA * stdB)
}

/**
 * The `q`-quantile (`q` in `[0, 1]`) of `v` using linear interpolation
 * between the two nearest ranks (the common "R-7" / NumPy-default method).
 * `q` is clamped into `[0, 1]` rather than extrapolating out of range.
 * Bad input: `[]` or a non-finite `q` returns `NaN`.
 */
export function quantile(v: number[], q: number): number {
  if (v.length === 0 || !Number.isFinite(q)) return NaN

  const sorted = [...v].sort((x, y) => x - y)
  const n = sorted.length
  if (n === 1) return sorted[0]

  const qq = clamp(q, 0, 1)
  const pos = qq * (n - 1)
  const lo = Math.floor(pos)
  const hi = Math.ceil(pos)
  if (lo === hi) return sorted[lo]

  const frac = pos - lo
  return sorted[lo] + (sorted[hi] - sorted[lo]) * frac
}

/**
 * Standard score of each sample: `(x - mean) / populationStd`. Uses the
 * **population** standard deviation (ddof = 0), matching the common
 * default for z-score normalization (e.g. `scipy.stats.zscore`'s default)
 * rather than the ddof = 1 convention used elsewhere in this module —
 * intentional, since z-scoring is normalizing the sample itself rather
 * than estimating a population parameter from it.
 * Bad input: `[]` returns `[]`. A constant series has zero spread to
 * normalize by; rather than returning `NaN` for every point (every value
 * genuinely equals the mean, so "0 standard deviations away" is exact,
 * not invented), this returns an all-`0` array.
 */
export function zscore(v: number[]): number[] {
  const n = v.length
  if (n === 0) return []

  const mean = v.reduce((a, b) => a + b, 0) / n
  const variance = v.reduce((a, b) => a + (b - mean) ** 2, 0) / n
  const std = Math.sqrt(variance)
  if (std === 0) return v.map(() => 0)

  return v.map((x) => (x - mean) / std)
}

/**
 * Rebases `values` so the first element equals `base` (default `1`),
 * scaling every other element by the same factor — e.g. turn a raw price
 * series into "growth of $1" or "growth of 100" for overlaying instruments
 * with different price levels on one chart.
 * Bad input: `[]` returns `[]`. If `values[0] === 0` there is no ratio to
 * rebase by, so every element returns `NaN` rather than `Infinity`.
 */
export function normalizeTo(values: number[], base = 1): number[] {
  if (values.length === 0) return []

  const first = values[0]
  if (first === 0) return values.map(() => NaN)

  return values.map((v) => (v / first) * base)
}

/* ------------------------------------------------------------------ internal */

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v))
}
