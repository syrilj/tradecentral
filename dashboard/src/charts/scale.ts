/**
 * Numeric and index-based scales for mapping data domains onto pixel ranges.
 *
 * No dependency on the DOM or on any charting library — every function here
 * is pure arithmetic. Degenerate input (an empty series, a zero-width
 * domain) is guarded explicitly so a scale never emits NaN/Infinity into an
 * SVG `d` or `transform` attribute, which would silently blank out a chart.
 */

/** A callable linear map with its domain/range attached, plus the inverse map. */
export interface Scale {
  (v: number): number
  domain: [number, number]
  range: [number, number]
  invert(px: number): number
}

/**
 * Builds a linear scale from `domain` to `range`. Works with reversed
 * domains/ranges (e.g. a y-axis where price increases upward but pixels
 * increase downward).
 *
 * Bad input: if `domain[0] === domain[1]` (or `range[0] === range[1]` for
 * `invert`), the scale is degenerate and cannot pick a slope — it returns
 * the midpoint of the range (resp. domain) for every input instead of
 * dividing by zero.
 */
export function linearScale(domain: [number, number], range: [number, number]): Scale {
  const [d0, d1] = domain
  const [r0, r1] = range
  const dSpan = d1 - d0
  const rSpan = r1 - r0

  const scale = ((v: number): number => {
    if (dSpan === 0) return (r0 + r1) / 2
    return r0 + ((v - d0) / dSpan) * rSpan
  }) as Scale

  scale.domain = domain
  scale.range = range
  scale.invert = (px: number): number => {
    if (rSpan === 0) return (d0 + d1) / 2
    return d0 + ((px - r0) / rSpan) * dSpan
  }

  return scale
}

/**
 * "Nice" 1-2-5 step-spaced tick values covering `[min, max]`, clamped to
 * stay inside that range (endpoints included when they line up with a
 * step). `count` is a target tick count, not a guarantee.
 *
 * Bad input: non-finite `min`/`max` returns `[]`. A degenerate domain
 * (`min === max`) returns the single value `[min]` rather than dividing by
 * a zero span.
 */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return []
  if (min === max) return [min]

  const lo = Math.min(min, max)
  const hi = Math.max(min, max)
  const n = Math.max(1, Math.floor(count))
  const step = niceStep((hi - lo) / n)

  const startIndex = Math.ceil(lo / step)
  const endIndex = Math.floor(hi / step)
  const maxTicks = 1000 // defensive cap against a pathological step

  const ticks: number[] = []
  for (let i = startIndex; i <= endIndex && ticks.length < maxTicks; i++) {
    ticks.push(roundTo(i * step, 6))
  }
  return ticks
}

/**
 * Pads `[min, max]` by a fraction of its span (default 5%) and rounds the
 * padded bounds outward to the nearest 1-2-5 step, so an axis built on the
 * result tends to land its ticks on the edges instead of just inside them.
 *
 * Bad input: non-finite `min`/`max` returns `[0, 1]`. A degenerate domain
 * (`min === max`) expands around the value by 10% (or by `[-1, 1]` around
 * zero) instead of returning a zero-width domain.
 */
export function niceDomain(min: number, max: number, pad = 0.05): [number, number] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1]

  const lo = Math.min(min, max)
  const hi = Math.max(min, max)

  if (lo === hi) {
    const delta = lo === 0 ? 1 : Math.abs(lo) * 0.1
    return [roundTo(lo - delta, 6), roundTo(hi + delta, 6)]
  }

  const span = hi - lo
  const paddedLo = lo - span * pad
  const paddedHi = hi + span * pad
  const step = niceStep((paddedHi - paddedLo) / 5)

  return [
    roundTo(Math.floor(paddedLo / step) * step, 6),
    roundTo(Math.ceil(paddedHi / step) * step, 6),
  ]
}

/**
 * Index-based ("ordinal") scale over a series of bar dates. The domain is
 * `[0, dates.length - 1]` — bar *position*, not wall-clock time — because
 * markets have gaps (weekends, holidays) that a true time scale would
 * render as visually misleading blank space. `invert` returns a
 * (possibly fractional) bar index; round it to snap to a bar.
 *
 * Bad input: `dates.length <= 1` produces a degenerate `[0, 0]` domain,
 * which `linearScale` already guards to the range midpoint.
 */
export function timeScale(dates: string[], range: [number, number]): Scale {
  const lastIndex = Math.max(dates.length - 1, 0)
  return linearScale([0, lastIndex], range)
}

/** Granularity chosen for `dateTicks` labels based on the span of the series. */
type DateGranularity = 'day' | 'month' | 'year'

/**
 * Picks up to `count` evenly-spaced bar indices and labels them, choosing
 * day/month/year granularity from the span between the first and last
 * date so a 2-week chart reads "Jan 15" while a 5-year chart reads "2024".
 *
 * Bad input: `dates.length === 0` returns `[]`. Unparseable date strings
 * fall back to the raw string as the label rather than throwing.
 */
export function dateTicks(dates: string[], count = 6): { i: number; label: string }[] {
  const n = dates.length
  if (n === 0) return []
  if (n === 1) return [{ i: 0, label: formatDateLabel(dates[0], 'day') }]

  const first = new Date(dates[0])
  const last = new Date(dates[n - 1])
  const spanDays = Math.abs(last.getTime() - first.getTime()) / 86_400_000

  let granularity: DateGranularity
  if (spanDays <= 60) granularity = 'day'
  else if (spanDays <= 730) granularity = 'month'
  else granularity = 'year'

  const tickCount = Math.max(1, Math.min(Math.floor(count), n))
  const indices = new Set<number>()
  if (tickCount === 1) {
    indices.add(0)
  } else {
    for (let k = 0; k < tickCount; k++) {
      indices.add(Math.round((k * (n - 1)) / (tickCount - 1)))
    }
  }

  return Array.from(indices)
    .sort((a, b) => a - b)
    .map((i) => ({ i, label: formatDateLabel(dates[i], granularity) }))
}

/* ------------------------------------------------------------------ internal */

const MONTH_ABBR = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

/** Formats a date string at the given granularity, using UTC fields so a
 * plain "YYYY-MM-DD" string never shifts a day under a negative UTC offset. */
function formatDateLabel(iso: string, granularity: DateGranularity): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso

  const year = d.getUTCFullYear()
  if (granularity === 'year') return String(year)

  const month = MONTH_ABBR[d.getUTCMonth()]
  if (granularity === 'month') return `${month} ${year}`

  return `${month} ${d.getUTCDate()}`
}

/** Rounds a raw step to the nearest 1-2-5 * 10^n "nice" number. */
function niceStep(rawStep: number): number {
  const absStep = Math.abs(rawStep) || 1
  const exponent = Math.floor(Math.log10(absStep))
  const magnitude = Math.pow(10, exponent)
  const residual = absStep / magnitude

  let niceFraction: number
  if (residual <= 1) niceFraction = 1
  else if (residual <= 2) niceFraction = 2
  else if (residual <= 5) niceFraction = 5
  else niceFraction = 10

  return niceFraction * magnitude
}

/** Rounds to `decimals` places and normalizes `-0` to `0`. */
function roundTo(value: number, decimals: number): number {
  const factor = Math.pow(10, decimals)
  const rounded = Math.round(value * factor) / factor
  return rounded === 0 ? 0 : rounded
}
