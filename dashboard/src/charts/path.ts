/**
 * SVG path-string builders. Every function takes already-scaled pixel
 * coordinates (run your data through a `Scale` from `./scale` first) and
 * returns a plain `d` attribute string — no DOM, no SVG namespace calls.
 *
 * Every function returns `""` on empty input rather than throwing, so a
 * chart with no data yet renders an empty `<path>` instead of crashing the
 * component that calls this. Coordinates are rounded to 2dp to keep the
 * generated markup small.
 */

import { linearScale } from './scale'

/** A single plotted point in pixel space. */
export interface Pt {
  x: number
  y: number
}

/**
 * Straight-segment polyline through `pts`: `"M x,y L x,y L x,y..."`.
 * Bad input: `[]` returns `""`.
 */
export function linePath(pts: Pt[]): string {
  if (pts.length === 0) return ''
  let d = `M${r2(pts[0].x)},${r2(pts[0].y)}`
  for (let i = 1; i < pts.length; i++) {
    d += `L${r2(pts[i].x)},${r2(pts[i].y)}`
  }
  return d
}

/**
 * Smoothed curve through `pts` using a uniform Catmull-Rom spline
 * converted to cubic Bezier segments (endpoints clamped by duplicating the
 * nearest real point, so the curve doesn't overshoot past the first/last
 * sample).
 *
 * `tension` is clamped to `[0, 1]`: `0` degenerates to straight segments
 * (control points collapse onto the endpoints), `0.5` (the default)
 * reproduces the textbook Catmull-Rom-to-Bezier conversion (control point
 * offset = neighbor delta / 6), and `1` doubles that offset for a looser
 * curve.
 *
 * Bad input: `[]` returns `""`; 1 point returns a bare `"M x,y"`; 2 points
 * falls back to `linePath` (a spline needs at least 3 points to curve).
 */
export function smoothPath(pts: Pt[], tension = 0.5): string {
  if (pts.length === 0) return ''
  if (pts.length === 1) return `M${r2(pts[0].x)},${r2(pts[0].y)}`
  if (pts.length === 2) return linePath(pts)

  const k = clamp(tension, 0, 1) / 3
  let d = `M${r2(pts[0].x)},${r2(pts[0].y)}`

  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] ?? p2

    const cp1x = p1.x + (p2.x - p0.x) * k
    const cp1y = p1.y + (p2.y - p0.y) * k
    const cp2x = p2.x - (p3.x - p1.x) * k
    const cp2y = p2.y - (p3.y - p1.y) * k

    d += `C${r2(cp1x)},${r2(cp1y)} ${r2(cp2x)},${r2(cp2y)} ${r2(p2.x)},${r2(p2.y)}`
  }

  return d
}

/**
 * Closed fill shape under a line: traces `pts` left to right, then drops
 * straight down/up to `baselineY` and closes back to the start.
 * Bad input: `[]` returns `""`.
 */
export function areaPath(pts: Pt[], baselineY: number): string {
  if (pts.length === 0) return ''
  const first = pts[0]
  const last = pts[pts.length - 1]

  let d = `M${r2(first.x)},${r2(baselineY)}L${r2(first.x)},${r2(first.y)}`
  for (let i = 1; i < pts.length; i++) {
    d += `L${r2(pts[i].x)},${r2(pts[i].y)}`
  }
  d += `L${r2(last.x)},${r2(baselineY)}Z`
  return d
}

/**
 * Step-after line: from each point, a horizontal segment at the current y
 * extends to the next point's x, then a vertical segment meets its y.
 * Bad input: `[]` returns `""`.
 */
export function stepPath(pts: Pt[]): string {
  if (pts.length === 0) return ''
  let d = `M${r2(pts[0].x)},${r2(pts[0].y)}`
  for (let i = 1; i < pts.length; i++) {
    const prev = pts[i - 1]
    const curr = pts[i]
    d += `L${r2(curr.x)},${r2(prev.y)}L${r2(curr.x)},${r2(curr.y)}`
  }
  return d
}

/** One OHLC bar, already in pixel space (x = center, h/l/o/c = pixel y). */
export interface CandleBar {
  x: number
  o: number
  h: number
  l: number
  c: number
}

/**
 * Builds candlestick geometry as three separate path strings so the caller
 * can style up/down bodies differently and stroke the wicks once: all
 * bullish bodies (`c >= o`) concatenated into `up`, bearish bodies into
 * `down`, and every high-low wick into `wicks`. Each body is a closed
 * rectangle `halfWidth` either side of `x`.
 *
 * Bad input: `[]` returns `{ up: "", down: "", wicks: "" }`.
 */
export function candlePath(
  bars: CandleBar[],
  halfWidth: number,
): { up: string; down: string; wicks: string } {
  if (bars.length === 0) return { up: '', down: '', wicks: '' }

  const hw = Math.abs(halfWidth)
  let up = ''
  let down = ''
  let wicks = ''

  for (const bar of bars) {
    const { x, o, h, l, c } = bar
    const top = r2(Math.max(o, c))
    const bottom = r2(Math.min(o, c))
    const left = r2(x - hw)
    const right = r2(x + hw)
    const rect = `M${left},${top}L${right},${top}L${right},${bottom}L${left},${bottom}Z`

    if (c >= o) up += rect
    else down += rect

    wicks += `M${r2(x)},${r2(h)}L${r2(x)},${r2(l)}`
  }

  return { up, down, wicks }
}

/**
 * Closed ribbon between two series (e.g. a Bollinger band or a confidence
 * interval): traces `upper` left to right, then `lower` right to left, and
 * closes. `upper` and `lower` don't need matching lengths.
 * Bad input: either array empty returns `""`.
 */
export function bandPath(upper: Pt[], lower: Pt[]): string {
  if (upper.length === 0 || lower.length === 0) return ''

  let d = `M${r2(upper[0].x)},${r2(upper[0].y)}`
  for (let i = 1; i < upper.length; i++) {
    d += `L${r2(upper[i].x)},${r2(upper[i].y)}`
  }
  for (let i = lower.length - 1; i >= 0; i--) {
    d += `L${r2(lower[i].x)},${r2(lower[i].y)}`
  }
  d += 'Z'
  return d
}

/**
 * Self-contained line + fill for a compact sparkline: lays `values` out
 * evenly across `w` (inset by `pad` on both sides) and scales them to `h`
 * (inset by `pad` top and bottom), and also returns the pixel position of
 * the last, min, and max samples so a caller can drop marker dots on them
 * without recomputing the scale.
 *
 * Bad input: `[]` returns `d`/`area` as `""` and `last`/`min`/`max` as
 * `{ x: 0, y: 0 }`. A flat series (`min === max`) is handled by
 * `linearScale`'s own degenerate-domain guard, so the line renders at the
 * vertical midpoint instead of NaN.
 */
export function sparkline(
  values: number[],
  w: number,
  h: number,
  pad = 2,
): { d: string; area: string; last: Pt; min: Pt; max: Pt } {
  const zero: Pt = { x: 0, y: 0 }
  if (values.length === 0) {
    return { d: '', area: '', last: zero, min: zero, max: zero }
  }

  const innerW = Math.max(w - pad * 2, 0)
  const innerH = Math.max(h - pad * 2, 0)

  let minV = values[0]
  let maxV = values[0]
  let minIdx = 0
  let maxIdx = 0
  for (let i = 1; i < values.length; i++) {
    if (values[i] < minV) {
      minV = values[i]
      minIdx = i
    }
    if (values[i] > maxV) {
      maxV = values[i]
      maxIdx = i
    }
  }

  const n = values.length
  const xScale = linearScale([0, Math.max(n - 1, 0)], [pad, pad + innerW])
  const yScale = linearScale([minV, maxV], [pad + innerH, pad])
  const pts: Pt[] = values.map((v, i) => ({ x: xScale(i), y: yScale(v) }))

  const last = pts[n - 1]
  const min = pts[minIdx]
  const max = pts[maxIdx]

  return {
    d: linePath(pts),
    area: areaPath(pts, pad + innerH),
    last: { x: r2(last.x), y: r2(last.y) },
    min: { x: r2(min.x), y: r2(min.y) },
    max: { x: r2(max.x), y: r2(max.y) },
  }
}

/* ------------------------------------------------------------------ internal */

/** Rounds a coordinate to 2dp and normalizes `-0` to `0`. */
function r2(n: number): number {
  const rounded = Math.round(n * 100) / 100
  return rounded === 0 ? 0 : rounded
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v))
}
