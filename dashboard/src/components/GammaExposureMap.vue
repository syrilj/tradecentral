<script setup lang="ts">
/**
 * Net-GEX & Call/Put Strike Profile — InsiderFinance-style glow profile.
 *
 *   · X axis = strike (low → high, left → right)
 *   · Call GEX / Call OI = gradient emerald bar ABOVE zero line (glows)
 *   · Put GEX / Put OI = gradient crimson bar BELOW zero line (glows)
 *   · Net profile = smooth phosphor-white trace line (no per-strike dots)
 *   · Wall bars carry direct value labels at the bar tip
 *   · Structural levels (PUT W / FLIP / SPOT / CALL W) = pinned badges + guides
 *
 * Dual-bar representation ensures neutral strikes (e.g. +$50M Call / -$50M Put)
 * show full gamma battleground instead of disappearing into a 0-height net line.
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { GexStrikeRow } from '@/api'
import { niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'
import { compact, DASH, num } from '@/format'

export type GexViewMode = 'winner' | 'dual' | 'net' | 'cumulative'
export type GexLayoutMode = 'graph' | 'split' | 'table'

interface Bar extends GexStrikeRow {
  net: number
  callVal: number
  putVal: number
  callH: number
  callY: number
  putH: number
  putY: number
  netH: number
  netY: number
  cumNet: number
  cumNetY: number
  winnerSide: 'call' | 'put' | 'flat'
  winnerVal: number
  winnerH: number
  winnerY: number
  winnerPct: number
  dominanceText: string
  cx: number
  thickness: number
  isSpotNear: boolean
  isCallWall: boolean
  isPutWall: boolean
  isFlip: boolean
}

interface Level {
  key: string
  label: string
  value: number
  cls: string
  x: number
  labelX: number
  labelY: number
  /** Content-derived badge width (px). The <rect> background pills around
   *  each level label are sized to their text so long strike labels such as
   *  `CALL W $1234.56` never clip or overlap an adjacent badge. */
  badgeW: number
}

interface WallLabel {
  key: string
  x: number
  y: number
  text: string
  cls: 'call' | 'put'
}

const props = withDefaults(
  defineProps<{
    rows: GexStrikeRow[]
    spot: number
    callWall: number | null
    putWall: number | null
    gammaFlip: number | null
    focusStrike?: number | null
    maxHeight?: number
  }>(),
  { maxHeight: 620, focusStrike: null },
)

const emit = defineEmits<{
  'update:focusStrike': [strike: number | null]
}>()

function lockStrike(strike: number): void {
  emit('update:focusStrike', props.focusStrike === strike ? null : strike)
}

function clearLock(): void {
  emit('update:focusStrike', null)
}

function onBarKeydown(e: KeyboardEvent, strike: number): void {
  if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
    e.preventDefault()
    lockStrike(strike)
  } else if (e.key === 'Escape') {
    e.preventDefault()
    clearLock()
  } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    e.preventDefault()
    const rows = orderedRows.value
    const idx = rows.findIndex((r) => r.strike === strike)
    if (idx === -1) return
    const nextIdx =
      e.key === 'ArrowLeft' ? Math.max(0, idx - 1) : Math.min(rows.length - 1, idx + 1)
    const nextStrike = rows[nextIdx].strike
    hoverStrike.value = nextStrike
    if (props.focusStrike != null) {
      emit('update:focusStrike', nextStrike)
    }
  }
}

watch(
  () => props.rows,
  (rows) => {
    if (props.focusStrike == null) return
    if (!rows.some((r) => r.strike === props.focusStrike)) {
      emit('update:focusStrike', null)
    }
  },
)

const hostRef = ref<HTMLDivElement | null>(null)
const { W: hostW, H: hostH } = useChartSize(hostRef, {
  minW: 200,
  minH: 160,
  fallbackW: 800,
  fallbackH: 340,
})

const left = 52
const right = 16
const top = 48
const bottom = 28
const minCol = 14

const hoverStrike = ref<number | null>(null)
const strikeScope = ref<'atm' | 'near' | 'wide' | 'all'>('near')
const metric = ref<'gex' | 'oi'>('gex')
const viewMode = ref<GexViewMode>('winner')
const layoutMode = ref<GexLayoutMode>('graph')
const showTrace = ref<boolean>(true)
const showRegimes = ref<boolean>(true)
const tableFilter = ref<string>('')
const tableSortKey = ref<'strike' | 'winner' | 'call' | 'put' | 'net' | 'dist'>('strike')
const tableSortDir = ref<'asc' | 'desc'>('asc')

const visible = computed(() => {
  if (!props.rows.length) return []
  if (strikeScope.value === 'all') return props.rows
  let ratio = 0.12
  if (strikeScope.value === 'atm') ratio = 0.06
  else if (strikeScope.value === 'wide') ratio = 0.25
  const filtered = props.rows.filter(
    (r) => r.strike >= props.spot * (1 - ratio) && r.strike <= props.spot * (1 + ratio),
  )
  return filtered.length >= 6 ? filtered : props.rows
})

const orderedRows = computed(() => [...visible.value].sort((a, b) => a.strike - b.strike))
const colCount = computed(() => Math.max(orderedRows.value.length, 1))

const H = computed(() => {
  if (layoutMode.value === 'split') {
    return Math.max(180, Math.min(260, (hostH.value || 340) * 0.55))
  }
  return Math.max(160, hostH.value || 340)
})
const plotInnerH = computed(() => Math.max(80, H.value - top - bottom))
const plotBottom = computed(() => top + plotInnerH.value)
const zeroY = computed(() => top + plotInnerH.value / 2)
const halfPlotH = computed(() => Math.max(1, plotInnerH.value / 2 - 8))

const plotInnerW = computed(() => {
  const minNeed = colCount.value * minCol
  const hostInner = Math.max(120, hostW.value - left - right)
  return Math.max(hostInner, minNeed)
})
const W = computed(() => plotInnerW.value + left + right)
const scrollable = computed(() => W.value > hostW.value + 0.5)
const bandW = computed(() => plotInnerW.value / colCount.value)

function bandCenter(index: number): number {
  return left + bandW.value * (index + 0.5)
}

const maxAbs = computed(() => {
  if (!orderedRows.value.length) return 1e-9
  const vals: number[] = []
  for (const r of orderedRows.value) {
    if (metric.value === 'gex') {
      const c = Number.isFinite(r.call_gex_m) ? Math.abs(r.call_gex_m) : 0
      const p = Number.isFinite(r.put_gex_m) ? Math.abs(r.put_gex_m) : 0
      const n = Number.isFinite(r.net_gex_m) ? Math.abs(r.net_gex_m) : 0
      vals.push(c, p, n)
    } else {
      const coi = Number.isFinite(r.call_oi) ? Math.abs(r.call_oi) : 0
      const poi = Number.isFinite(r.put_oi) ? Math.abs(r.put_oi) : 0
      vals.push(coi, poi, Math.abs(coi - poi))
    }
  }
  return Math.max(1e-9, ...vals)
})

const totalNet = computed(() =>
  orderedRows.value.reduce(
    (s, r) => s + (metric.value === 'gex' ? r.net_gex_m : r.call_oi - r.put_oi),
    0,
  ),
)
const callTotal = computed(() =>
  orderedRows.value.reduce((s, r) => s + (metric.value === 'gex' ? r.call_gex_m : r.call_oi), 0),
)
const putTotal = computed(() =>
  orderedRows.value.reduce((s, r) => s + (metric.value === 'gex' ? r.put_gex_m : r.put_oi), 0),
)

const gexRatio = computed(() => {
  const c = Math.abs(callTotal.value)
  const p = Math.abs(putTotal.value)
  if (p <= 1e-6) return c > 0 ? 'CALL DOM' : 'BALANCED'
  if (c <= 1e-6) return p > 0 ? 'PUT DOM' : 'BALANCED'
  const r = c / p
  if (r >= 1.2) return `${num(r, 1)}x CALL`
  if (r <= 0.83) return `${num(1 / r, 1)}x PUT`
  return 'BALANCED'
})

const maxCumulative = computed(() => {
  if (!orderedRows.value.length) return 1e-9
  let sum = 0
  let peak = 1e-9
  for (const r of orderedRows.value) {
    sum += metric.value === 'gex' ? r.net_gex_m : r.call_oi - r.put_oi
    if (Math.abs(sum) > peak) peak = Math.abs(sum)
  }
  return peak
})

function metricValue(value: number, signed = false): string {
  if (!Number.isFinite(value)) return DASH
  const rounded = Number(value.toFixed(1))
  const sign = rounded > 0 ? (signed ? '+' : '') : rounded < 0 ? '-' : ''
  const abs = Math.abs(rounded === 0 ? 0 : rounded)
  return metric.value === 'gex' ? `${sign}$${num(abs, 1)}M` : `${sign}${compact(abs)}`
}

/** Axis ticks drop the trailing ".0" and use a typographic minus so the
 *  gutter reads "+$20M / 0 / −$20M" instead of "$20.0M / - $20.0M". */
function axisValue(v: number): string {
  if (v === 0) return '0'
  const rounded = Number(v.toFixed(1))
  const abs = Math.abs(rounded)
  const body = Number.isInteger(abs) ? String(abs) : abs.toFixed(1)
  const magnitude = metric.value === 'gex' ? `$${body}M` : compact(Number(body))
  if (rounded > 0) return `+${magnitude}`
  return `−${magnitude}`
}

function strikeLabel(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return DASH
  return num(value, Number.isInteger(value) ? 0 : 2)
}

function distanceLabel(strike: number): string {
  if (!props.spot || props.spot <= 0) return ''
  const diff = strike - props.spot
  const pct = (diff / props.spot) * 100
  const rounded = Number(pct.toFixed(1))
  const sign = diff >= 0 ? '+' : ''
  const side = diff > 0 ? 'OTM' : diff < 0 ? 'ITM' : 'ATM'
  return `${sign}$${num(Math.abs(diff), 2)} (${sign}${num(rounded === 0 ? 0 : rounded, 1)}% ${side})`
}

const bars = computed<Bar[]>(() => {
  let runningCum = 0
  const cumDenominator = maxCumulative.value || 1e-9

  return orderedRows.value.map((row, index) => {
    const isGex = metric.value === 'gex'
    const callVal = isGex ? row.call_gex_m : row.call_oi
    const putVal = isGex ? Math.abs(row.put_gex_m) : row.put_oi
    const net = isGex ? row.net_gex_m : row.call_oi - row.put_oi

    runningCum += net
    const cumNet = runningCum

    const callH = Math.max(callVal > 0 ? 2 : 0, (callVal / maxAbs.value) * halfPlotH.value)
    const putH = Math.max(putVal > 0 ? 2 : 0, (putVal / maxAbs.value) * halfPlotH.value)

    const isCallWinner = callVal > putVal
    const isPutWinner = putVal > callVal
    const winnerSide: 'call' | 'put' | 'flat' = isCallWinner ? 'call' : isPutWinner ? 'put' : 'flat'
    const winnerVal = isCallWinner ? callVal : isPutWinner ? putVal : callVal
    const winnerH = Math.max(winnerVal > 0 ? 2 : 0, (winnerVal / maxAbs.value) * halfPlotH.value)
    const winnerY = isCallWinner ? zeroY.value - winnerH : zeroY.value

    const sumVal = callVal + putVal
    const winnerPct =
      sumVal > 0 ? Math.round(((isCallWinner ? callVal : putVal) / sumVal) * 100) : 50
    const dominanceText = isCallWinner
      ? `${winnerPct}% CALL`
      : isPutWinner
        ? `${winnerPct}% PUT`
        : 'TIED'

    const callY = zeroY.value - callH
    const putY = zeroY.value
    const netY = zeroY.value - (net / maxAbs.value) * halfPlotH.value
    const netH = Math.max(2, (Math.abs(net) / maxAbs.value) * halfPlotH.value)
    const cumNetY = zeroY.value - (cumNet / cumDenominator) * halfPlotH.value

    // ≤ 24px thick per mark spec — never fill the slot; the leftover is air.
    const thickness = Math.max(4, Math.min(bandW.value * 0.64, 24))
    const cx = bandCenter(index)

    const isSpotNear =
      Math.abs(row.strike - props.spot) <= (bandW.value > 0 ? props.spot * 0.01 : 0.5)
    const isCallWall = props.callWall != null && Math.abs(row.strike - props.callWall) < 0.01
    const isPutWall = props.putWall != null && Math.abs(row.strike - props.putWall) < 0.01
    const isFlip = props.gammaFlip != null && Math.abs(row.strike - props.gammaFlip) < 0.01

    return {
      ...row,
      net,
      callVal,
      putVal,
      callH,
      callY,
      putH,
      putY,
      netH,
      netY,
      cumNet,
      cumNetY,
      winnerSide,
      winnerVal,
      winnerH,
      winnerY,
      winnerPct,
      dominanceText,
      cx,
      thickness,
      isSpotNear,
      isCallWall,
      isPutWall,
      isFlip,
    }
  })
})

/** Direct labels on the two bars that matter most — the walls. Value rides the
 *  bar tip so the extremes are readable without hover. */
const wallLabels = computed<WallLabel[]>(() => {
  const out: WallLabel[] = []
  if (viewMode.value === 'cumulative' || layoutMode.value === 'table' || !bars.value.length)
    return out
  const cw =
    props.callWall != null
      ? bars.value.find((b) => Math.abs(b.strike - (props.callWall as number)) < 0.01)
      : undefined
  const pw =
    props.putWall != null
      ? bars.value.find((b) => Math.abs(b.strike - (props.putWall as number)) < 0.01)
      : undefined
  if (cw && cw.callH > 16) {
    const yPos =
      viewMode.value === 'winner' && cw.winnerSide === 'put'
        ? cw.winnerY + cw.winnerH + 16
        : cw.callY - 8
    out.push({ key: 'call', x: cw.cx, y: yPos, text: metricValue(cw.callVal, true), cls: 'call' })
  }
  if (pw && pw.putH > 16) {
    const yPos =
      viewMode.value === 'winner' && pw.winnerSide === 'call'
        ? pw.winnerY - 8
        : pw.putY + pw.putH + 16
    out.push({ key: 'put', x: pw.cx, y: yPos, text: metricValue(pw.putVal), cls: 'put' })
  }
  return out
})

function setTableSort(key: 'strike' | 'winner' | 'call' | 'put' | 'net' | 'dist'): void {
  if (tableSortKey.value === key) {
    tableSortDir.value = tableSortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    tableSortKey.value = key
    tableSortDir.value = key === 'strike' ? 'asc' : 'desc'
  }
}

const filteredTableRows = computed(() => {
  let list = bars.value
  if (tableFilter.value.trim()) {
    const q = tableFilter.value.trim().toLowerCase()
    list = list.filter((b) => {
      return (
        String(b.strike).includes(q) ||
        b.winnerSide.includes(q) ||
        b.dominanceText.toLowerCase().includes(q) ||
        (b.isCallWall && 'call wall'.includes(q)) ||
        (b.isPutWall && 'put wall'.includes(q)) ||
        (b.isFlip && 'flip'.includes(q)) ||
        (b.isSpotNear && 'spot atm'.includes(q))
      )
    })
  }
  return [...list].sort((a, b) => {
    let diff = 0
    if (tableSortKey.value === 'strike') diff = a.strike - b.strike
    else if (tableSortKey.value === 'winner') diff = a.winnerPct - b.winnerPct
    else if (tableSortKey.value === 'call') diff = a.callVal - b.callVal
    else if (tableSortKey.value === 'put') diff = a.putVal - b.putVal
    else if (tableSortKey.value === 'net') diff = a.net - b.net
    else if (tableSortKey.value === 'dist')
      diff = Math.abs(a.strike - props.spot) - Math.abs(b.strike - props.spot)
    return tableSortDir.value === 'asc' ? diff : -diff
  })
})

const focusBar = computed(() => {
  if (!bars.value.length) return null
  const target = hoverStrike.value ?? props.focusStrike ?? props.spot
  return bars.value.reduce((best, row) =>
    Math.abs(row.strike - target) < Math.abs(best.strike - target) ? row : best,
  )
})

function xOfPrice(price: number): number | null {
  const rows = orderedRows.value
  if (!rows.length) return null
  if (price <= rows[0].strike) return bandCenter(0)
  const lastIndex = rows.length - 1
  if (price >= rows[lastIndex].strike) return bandCenter(lastIndex)
  for (let i = 0; i < lastIndex; i++) {
    const lo = rows[i]
    const hi = rows[i + 1]
    if (price >= lo.strike && price <= hi.strike) {
      const span = hi.strike - lo.strike
      const t = span > 1e-9 ? (price - lo.strike) / span : 0
      return bandCenter(i + t)
    }
  }
  return null
}

const lockX = computed(() => (props.focusStrike != null ? xOfPrice(props.focusStrike) : null))
const flipX = computed(() => (props.gammaFlip != null ? xOfPrice(props.gammaFlip) : null))

/**
 * Estimate the rendered pixel width of a level badge label.
 *
 * The badge text is `{{ label }} ${{ strikeLabel(value) }}` rendered in
 * `font: 700 var(--t-micro) var(--font-display)` (11px Geist display, weight
 * 700, 0.04em tracking). Rather than ship a canvas measurer, we approximate
 * the advance width with a per-character average: digits and capitals in a
 * condensed technical face advance ~0.62em, narrow glyphs (space, '.', '$',
 * '-', 'W') ~0.4em. This is deliberately a little generous so the pill never
 * under-sizes and clips a long label such as `CALL W $1234.56`.
 *
 * `--t-micro` is 11px; at 0.04em tracking each char adds ~0.44px. We fold the
 * tracking into the per-glyph em factor and add horizontal pill padding
 * (6px each side) plus a 2px safety margin.
 */
function levelBadgeWidth(label: string, value: number): number {
  const text = `${label} $${strikeLabel(value)}`
  // COUPLING: `em` MUST match the badge font-size token `--t-micro`
  // (tokens.css: --t-micro: 0.6875rem = 11px at the default 16px root).
  // The badge <text> is styled `font: 700 var(--t-micro) var(--font-display)`.
  // If --t-micro changes, update this pixel value to keep the width estimate
  // in sync (or derive it from a shared constant exporting the rem→px ratio).
  const em = 11 // == --t-micro (0.6875rem * 16px)
  const padX = 12 // 6px pill padding each side
  const safety = 2
  let width = 0
  for (const ch of text) {
    const narrow = ' .$/-WI'
    const factor = narrow.includes(ch) ? 0.42 : 0.64
    width += factor * em
  }
  return Math.ceil(width + padX + safety)
}

const levels = computed<Level[]>(() => {
  const raw: { key: string; label: string; value: number | null; cls: string }[] = [
    {
      key: 'put',
      label: 'PUT W',
      value:
        props.putWall != null && Number.isFinite(props.putWall) && props.putWall > 0
          ? props.putWall
          : null,
      cls: 'put',
    },
    {
      key: 'flip',
      label: 'FLIP',
      value:
        props.gammaFlip != null && Number.isFinite(props.gammaFlip) && props.gammaFlip > 0
          ? props.gammaFlip
          : null,
      cls: 'flip',
    },
    {
      key: 'spot',
      label: 'SPOT',
      value:
        props.spot != null && Number.isFinite(props.spot) && props.spot > 0 ? props.spot : null,
      cls: 'spot',
    },
    {
      key: 'call',
      label: 'CALL W',
      value:
        props.callWall != null && Number.isFinite(props.callWall) && props.callWall > 0
          ? props.callWall
          : null,
      cls: 'call',
    },
  ]
  const placed = raw
    .map((level) => ({ ...level, x: level.value != null ? xOfPrice(level.value) : null }))
    .filter(
      (level): level is { key: string; label: string; value: number; cls: string; x: number } =>
        level.x != null,
    )
    .sort((a, b) => a.x - b.x)

  if (!placed.length) return []

  // Content-derived badge widths — the pill sizes to its text so long strike
  // labels (e.g. `CALL W $1234.56`) never clip. Collision separation is driven
  // by these widths, not a fixed constant that ignores label length.
  const badgeW = placed.map((l) => levelBadgeWidth(l.label, l.value))
  const halfW = badgeW.map((w) => w / 2)
  // Minimum center-to-center gap between two adjacent badges = the sum of their
  // half-widths plus a 4px breathing gutter, so neighbours never overlap.
  const gapBetween = (i: number, j: number) => halfW[i] + halfW[j] + 4

  // Boundaries keep the full badge inside the plot interior — each edge
  // respects the widest badge so no pill clips at the left/right frame.
  const maxHalf = Math.max(...halfW)
  const minBoundary = left + maxHalf
  const maxBoundary = left + plotInnerW.value - maxHalf

  // 1. Initial clamp to plot interior
  const xs = placed.map((l) => Math.max(minBoundary, Math.min(maxBoundary, l.x)))

  // 2. Forward pass (push right) — width-aware separation
  for (let i = 1; i < xs.length; i++) {
    const need = gapBetween(i - 1, i)
    if (xs[i] < xs[i - 1] + need) {
      xs[i] = xs[i - 1] + need
    }
  }

  // 3. Backward pass (pull left if rightmost exceeds maxBoundary)
  if (xs[xs.length - 1] > maxBoundary) {
    xs[xs.length - 1] = maxBoundary
    for (let i = xs.length - 2; i >= 0; i--) {
      const need = gapBetween(i, i + 1)
      if (xs[i] > xs[i + 1] - need) {
        xs[i] = xs[i + 1] - need
      }
    }
  }

  // 4. Clamp check at left boundary
  if (xs[0] < minBoundary) {
    xs[0] = minBoundary
    for (let i = 1; i < xs.length; i++) {
      const need = gapBetween(i - 1, i)
      if (xs[i] < xs[i - 1] + need) {
        xs[i] = xs[i - 1] + need
      }
    }
  }

  // 5. Detect remaining congestion for vertical tier staggering
  const hasRemainingOverlap = xs.some((x, i) => i > 0 && x - xs[i - 1] < gapBetween(i - 1, i) - 2)
  const isWidthConstrained = maxBoundary - minBoundary < placed.length * (maxHalf * 2 + 4)

  return placed.map((level, i) => {
    const labelX = Math.max(minBoundary, Math.min(maxBoundary, xs[i]))
    // Position labels cleanly in dedicated banner lane [24 .. 38]
    const labelY = hasRemainingOverlap || isWidthConstrained ? (i % 2 === 0 ? 24 : 36) : 30

    return {
      ...level,
      labelX,
      labelY,
      badgeW: badgeW[i],
    }
  })
})

/** Catmull-Rom → cubic Bézier smoothing. The net profile reads as a single
 *  swept line (InsiderFinance convention), not a zigzag between bar tops. */
function smoothPath(pts: { x: number; y: number }[]): string {
  if (pts.length < 2) return ''
  let d = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[Math.min(pts.length - 1, i + 2)]
    const c1x = p1.x + (p2.x - p0.x) / 6
    const c1y = p1.y + (p2.y - p0.y) / 6
    const c2x = p2.x - (p3.x - p1.x) / 6
    const c2y = p2.y - (p3.y - p1.y) / 6
    d += ` C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`
  }
  return d
}

const netTracePath = computed(() => {
  if (bars.value.length <= 1) return ''
  return smoothPath(bars.value.map((b) => ({ x: b.cx, y: b.netY })))
})

const cumulativeAreaPath = computed(() => {
  if (bars.value.length <= 1) return ''
  const first = bars.value[0]
  const last = bars.value[bars.value.length - 1]
  const line = bars.value
    .map((b, i) => `${i === 0 ? 'M' : 'L'} ${b.cx.toFixed(1)} ${b.cumNetY.toFixed(1)}`)
    .join(' ')
  return `${line} L ${last.cx.toFixed(1)} ${zeroY.value.toFixed(1)} L ${first.cx.toFixed(1)} ${zeroY.value.toFixed(1)} Z`
})

const cumulativeLinePath = computed(() => {
  if (bars.value.length <= 1) return ''
  return smoothPath(bars.value.map((b) => ({ x: b.cx, y: b.cumNetY })))
})

const tickCount = computed(() => (H.value < 220 ? 3 : 5))

const yTicks = computed(() => {
  if (!orderedRows.value.length) return []
  const maxVal = viewMode.value === 'cumulative' ? maxCumulative.value : maxAbs.value
  return niceTicks(-maxVal, maxVal, tickCount.value).map((value) => ({
    value,
    y: zeroY.value - (value / maxVal) * halfPlotH.value,
  }))
})

const strikeTicks = computed(() => {
  const rows = orderedRows.value
  const n = rows.length
  if (!n) return [] as { x: number; label: string; strike: number; isSpot: boolean }[]
  const maxLabels = Math.min(n, Math.max(4, Math.floor(plotInnerW.value / 56)))
  const indices = new Set<number>()
  if (maxLabels <= 1) indices.add(0)
  else {
    for (let k = 0; k < maxLabels; k++) {
      indices.add(Math.round((k * (n - 1)) / (maxLabels - 1)))
    }
  }
  let nearest = 0
  let best = Infinity
  rows.forEach((r, i) => {
    const d = Math.abs(r.strike - props.spot)
    if (d < best) {
      best = d
      nearest = i
    }
  })
  indices.add(nearest)
  return Array.from(indices)
    .sort((a, b) => a - b)
    .map((i) => ({
      x: bandCenter(i),
      label: strikeLabel(rows[i].strike),
      strike: rows[i].strike,
      isSpot: i === nearest,
    }))
})

function barAriaLabel(bar: Bar): string {
  const callText =
    metric.value === 'gex'
      ? `call GEX ${metricValue(bar.call_gex_m)}`
      : `call OI ${compact(bar.call_oi)}`
  const putText =
    metric.value === 'gex'
      ? `put GEX ${metricValue(Math.abs(bar.put_gex_m))}`
      : `put OI ${compact(bar.put_oi)}`
  const netText = `net ${metricValue(bar.net, true)}`
  return `Strike $${strikeLabel(bar.strike)}. ${callText}, ${putText}, ${netText}.`
}

function jumpToLevel(strike: number | null): void {
  if (strike == null || !Number.isFinite(strike)) return
  const closest = orderedRows.value.reduce(
    (best, row) => (Math.abs(row.strike - strike) < Math.abs(best.strike - strike) ? row : best),
    orderedRows.value[0],
  )
  if (closest) {
    lockStrike(closest.strike)
    scrollToStrike(closest.strike)
  }
}

function scrollToStrike(strike: number): void {
  if (!hostRef.value || !scrollable.value) return
  const targetX = xOfPrice(strike)
  if (targetX != null) {
    const containerW = hostRef.value.clientWidth
    hostRef.value.scrollTo({
      left: Math.max(0, targetX - containerW / 2),
      behavior: 'smooth',
    })
  }
}

function centerOnSpot(): void {
  if (props.spot > 0) {
    scrollToStrike(props.focusStrike ?? props.spot)
  }
}

onMounted(() => {
  nextTick(() => {
    centerOnSpot()
  })
})

watch(
  () => [props.spot, props.rows, strikeScope.value],
  () => {
    nextTick(() => {
      centerOnSpot()
    })
  },
)
</script>

<template>
  <div class="gex-map" @keydown.esc="clearLock">
    <!-- Top toolbar: metric switch, range scope, view mode, layout mode, overlays & legend -->
    <div class="map-controls">
      <div class="control-group">
        <div class="mini-segment" role="group" aria-label="Metric selection">
          <button
            type="button"
            class="label"
            :class="{ on: metric === 'gex' }"
            title="Display Dollar Gamma Exposure ($M per 1% move)"
            @click="metric = 'gex'"
          >
            CALL & PUT GEX
          </button>
          <button
            type="button"
            class="label"
            :class="{ on: metric === 'oi' }"
            title="Display Open Interest in Contracts"
            @click="metric = 'oi'"
          >
            CALL & PUT OI
          </button>
        </div>
      </div>

      <div class="control-group">
        <div class="mini-segment" role="group" aria-label="Strike range preset">
          <button
            type="button"
            class="label"
            :class="{ on: strikeScope === 'atm' }"
            @click="strikeScope = 'atm'"
          >
            ATM (±6%)
          </button>
          <button
            type="button"
            class="label"
            :class="{ on: strikeScope === 'near' }"
            @click="strikeScope = 'near'"
          >
            NEAR (±12%)
          </button>
          <button
            type="button"
            class="label"
            :class="{ on: strikeScope === 'wide' }"
            @click="strikeScope = 'wide'"
          >
            WIDE (±25%)
          </button>
          <button
            type="button"
            class="label"
            :class="{ on: strikeScope === 'all' }"
            @click="strikeScope = 'all'"
          >
            ALL STRIKES
          </button>
        </div>
      </div>

      <div class="control-group">
        <div class="mini-segment" role="group" aria-label="View format">
          <button
            type="button"
            class="label"
            :class="{ on: viewMode === 'winner' }"
            title="Show Winning Side per Strike (Calls Above in Green / Puts Below in Red)"
            @click="viewMode = 'winner'"
          >
            WINNING SIDE
          </button>
          <button
            type="button"
            class="label"
            :class="{ on: viewMode === 'dual' }"
            title="Dual Call / Put Bars"
            @click="viewMode = 'dual'"
          >
            DUAL BARS
          </button>
          <button
            type="button"
            class="label"
            :class="{ on: viewMode === 'net' }"
            title="Single Net Exposure Bar per Strike"
            @click="viewMode = 'net'"
          >
            NET PROFILE
          </button>
          <button
            type="button"
            class="label"
            :class="{ on: viewMode === 'cumulative' }"
            title="Cumulative Hedge Requirement across Strikes"
            @click="viewMode = 'cumulative'"
          >
            CUMULATIVE
          </button>
        </div>
      </div>

      <div class="control-group">
        <div class="mini-segment layout-seg" role="group" aria-label="Display layout">
          <button
            type="button"
            class="label"
            :class="{ on: layoutMode === 'graph' }"
            title="Graph View"
            @click="layoutMode = 'graph'"
          >
            GRAPH
          </button>
          <button
            type="button"
            class="label"
            :class="{ on: layoutMode === 'split' }"
            title="Split Graph + Table View"
            @click="layoutMode = 'split'"
          >
            SPLIT
          </button>
          <button
            type="button"
            class="label"
            :class="{ on: layoutMode === 'table' }"
            title="Strike Matrix Table View"
            @click="layoutMode = 'table'"
          >
            TABLE
          </button>
        </div>
      </div>

      <div v-if="layoutMode !== 'table'" class="control-group toggles">
        <button
          type="button"
          class="pill-toggle label"
          :class="{ active: showTrace }"
          title="Toggle Net Profile Trace Line"
          @click="showTrace = !showTrace"
        >
          NET TRACE
        </button>
        <button
          v-if="gammaFlip != null"
          type="button"
          class="pill-toggle label"
          :class="{ active: showRegimes }"
          title="Toggle Positive vs Negative Gamma Regime Zones"
          @click="showRegimes = !showRegimes"
        >
          REGIMES
        </button>
      </div>

      <div
        v-if="
          (putWall != null && putWall > 0) ||
          (gammaFlip != null && gammaFlip > 0) ||
          (spot != null && spot > 0) ||
          (callWall != null && callWall > 0)
        "
        class="quick-levels"
      >
        <span class="label quick-title">JUMP:</span>
        <button
          v-if="putWall != null && putWall > 0"
          type="button"
          class="level-chip put label"
          title="Jump to Put Wall"
          @click="jumpToLevel(putWall)"
        >
          PUT W ${{ strikeLabel(putWall) }}
        </button>
        <button
          v-if="gammaFlip != null && gammaFlip > 0"
          type="button"
          class="level-chip flip label"
          title="Jump to Gamma Flip"
          @click="jumpToLevel(gammaFlip)"
        >
          FLIP ${{ strikeLabel(gammaFlip) }}
        </button>
        <button
          v-if="spot != null && spot > 0"
          type="button"
          class="level-chip spot label"
          title="Jump to Spot"
          @click="jumpToLevel(spot)"
        >
          SPOT ${{ strikeLabel(spot) }}
        </button>
        <button
          v-if="callWall != null && callWall > 0"
          type="button"
          class="level-chip call label"
          title="Jump to Call Wall"
          @click="jumpToLevel(callWall)"
        >
          CALL W ${{ strikeLabel(callWall) }}
        </button>
      </div>

      <span class="coverage label">
        {{ bars.length < rows.length ? `IN VIEW ${bars.length}/${rows.length}` : 'FULL CHAIN' }} ·
        <span class="call-leg"><i class="leg-dot call" />CALL</span> ·
        <span class="put-leg"><i class="leg-dot put" />PUT</span> ·
        <span class="net-leg"><i class="leg-dot net" />NET</span>
      </span>
    </div>

    <!-- Aggregate HUD bar + Interactive Strike Inspector -->
    <div class="exposure-head">
      <div
        v-if="!((hoverStrike != null || focusStrike != null) && focusBar)"
        class="exposure-totals"
      >
        <div class="exposure-total call">
          <span class="label">{{ metric === 'gex' ? 'CALL GEX' : 'CALL OI' }}</span>
          <strong class="fig">{{ metricValue(callTotal, true) }}</strong>
        </div>
        <div class="exposure-total put">
          <span class="label">{{ metric === 'gex' ? 'PUT GEX' : 'PUT OI' }}</span>
          <strong class="fig">{{ metricValue(putTotal) }}</strong>
        </div>
        <div class="exposure-total net" :class="totalNet >= 0 ? 'positive' : 'negative'">
          <span class="label">NET ({{ gexRatio }})</span>
          <strong class="fig">{{ metricValue(totalNet, true) }}</strong>
        </div>
      </div>

      <div v-else-if="focusBar" class="strike-focus" :class="{ locked: focusStrike != null }">
        <div class="focus-strike">
          <span class="label">
            {{ hoverStrike != null ? 'INSPECTING' : 'LOCKED STRIKE' }}
          </span>
          <strong class="fig">${{ strikeLabel(focusBar.strike) }}</strong>
          <small class="dist-tag">{{ distanceLabel(focusBar.strike) }}</small>
        </div>
        <div class="focus-metric winner" :class="focusBar.winnerSide">
          <span class="label">WINNING BIAS</span>
          <strong class="fig">{{ focusBar.dominanceText }}</strong>
          <small>{{
            focusBar.winnerSide === 'call'
              ? 'Call Dominance'
              : focusBar.winnerSide === 'put'
                ? 'Put Dominance'
                : 'Balanced'
          }}</small>
        </div>
        <div class="focus-metric call">
          <span class="label">CALL {{ metric === 'gex' ? 'GEX' : 'OI' }}</span>
          <strong class="fig">{{ metricValue(focusBar.callVal) }}</strong>
          <small>OI {{ compact(focusBar.call_oi) }}</small>
        </div>
        <div class="focus-metric put">
          <span class="label">PUT {{ metric === 'gex' ? 'GEX' : 'OI' }}</span>
          <strong class="fig">{{ metricValue(focusBar.putVal) }}</strong>
          <small>OI {{ compact(focusBar.put_oi) }}</small>
        </div>
        <div class="focus-metric net" :class="focusBar.net >= 0 ? 'positive' : 'negative'">
          <span class="label">NET {{ metric === 'gex' ? 'GEX' : 'OI' }}</span>
          <strong class="fig">{{ metricValue(focusBar.net, true) }}</strong>
          <small>
            <template v-if="focusBar.isCallWall">★ CALL WALL</template>
            <template v-else-if="focusBar.isPutWall">★ PUT WALL</template>
            <template v-else-if="focusBar.isFlip">◆ GAMMA FLIP</template>
            <template v-else-if="focusBar.isSpotNear">● ATM</template>
            <template v-else>click bar to lock</template>
          </small>
        </div>
        <button
          v-if="focusStrike != null"
          type="button"
          class="clear-lock label"
          title="Clear locked strike (Esc)"
          @click="clearLock"
        >
          CLEAR
        </button>
      </div>
    </div>

    <!-- Main Chart Area with SVG Viewbox (Rendered in GRAPH and SPLIT modes) -->
    <div
      v-if="layoutMode !== 'table'"
      ref="hostRef"
      class="plot-scroll"
      :class="{ scrollable, 'split-view': layoutMode === 'split' }"
    >
      <svg
        :viewBox="`0 0 ${W} ${H}`"
        :width="scrollable ? W : '100%'"
        :height="H"
        :style="{
          height: '100%',
          width: scrollable ? `${W}px` : '100%',
          minWidth: scrollable ? `${W}px` : '100%',
          display: 'block',
        }"
        role="img"
        aria-label="Call and Put gamma exposure by strike. Calls up, Puts down, Net as a smooth trace line."
      >
        <title>
          Call vs Put GEX by strike. Winning side indicated by Call UP in emerald green or Put DOWN
          in crimson red.
        </title>

        <defs>
          <!-- Plot frame clip path to guarantee zero bar overflow -->
          <clipPath id="gex-plot-clip">
            <rect :x="left" :y="top" :width="plotInnerW" :height="plotInnerH" rx="1" ry="1" />
          </clipPath>

          <!-- Bar gradients: bright at the data tip, settling into the baseline -->
          <linearGradient id="gex-call-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="var(--call-hi)" />
            <stop offset="0.55" stop-color="var(--call)" />
            <stop offset="1" stop-color="var(--call-dim)" />
          </linearGradient>
          <linearGradient id="gex-put-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="var(--put-dim)" />
            <stop offset="0.45" stop-color="var(--put)" />
            <stop offset="1" stop-color="var(--put-hi)" />
          </linearGradient>
        </defs>

        <!-- Base Plot Background Frame -->
        <rect class="plot-frame" :x="left" :y="top" :width="plotInnerW" :height="plotInnerH" />

        <!-- Optional Gamma Regime Zones Background Shading -->
        <g
          v-if="showRegimes && flipX != null && rows.length"
          class="regime-zones"
          clip-path="url(#gex-plot-clip)"
          aria-hidden="true"
        >
          <!-- Negative Gamma Zone (Below Flip) -->
          <rect
            v-if="flipX > left"
            class="regime-zone neg"
            :x="left"
            :y="top"
            :width="Math.min(flipX - left, plotInnerW)"
            :height="plotInnerH"
          />
          <!-- Positive Gamma Zone (Above Flip) -->
          <rect
            v-if="flipX < left + plotInnerW"
            class="regime-zone pos"
            :x="Math.max(flipX, left)"
            :y="top"
            :width="Math.max(0, left + plotInnerW - Math.max(flipX, left))"
            :height="plotInnerH"
          />
          <text v-if="flipX > left + 110" :x="left + 8" :y="top + 14" class="regime-label neg halo">
            SHORT GAMMA · VOLATILITY AMPLIFIED
          </text>
          <text
            v-if="flipX < left + plotInnerW - 110"
            :x="left + plotInnerW - 8"
            :y="top + 14"
            text-anchor="end"
            class="regime-label pos halo"
          >
            LONG GAMMA · VOLATILITY DAMPENED
          </text>
        </g>

        <!-- Y Grid Lines (hairline, recessive) + vertical strike guides -->
        <g v-if="rows.length" class="grid" clip-path="url(#gex-plot-clip)">
          <line
            v-for="tick in yTicks"
            :key="`grid-${tick.value}`"
            :x1="left"
            :x2="left + plotInnerW"
            :y1="tick.y"
            :y2="tick.y"
            :class="{ zero: tick.value === 0 }"
          />
          <line
            v-for="tick in strikeTicks"
            :key="`vgrid-${tick.strike}`"
            :x1="tick.x"
            :x2="tick.x"
            :y1="top"
            :y2="plotBottom"
            class="vgrid"
          />
        </g>

        <!-- Zero Axis — the one allowed-to-be-loud gridline -->
        <g v-if="rows.length" class="zero-baseline-group">
          <line :x1="left" :x2="left + plotInnerW" :y1="zeroY" :y2="zeroY" class="zero-baseline" />
        </g>

        <!-- Structural Level Guides & Top Labels (Rendered cleanly above the bar peaks) -->
        <g v-for="level in levels" :key="level.key" class="level" :class="level.cls">
          <!-- Guide line inside plot frame -->
          <line :x1="level.x" :x2="level.x" :y1="top" :y2="plotBottom" />
          <!-- Straight leader from badge down to its guide -->
          <line
            :x1="level.labelX"
            :y1="level.labelY + 8"
            :x2="level.x"
            :y2="top - 2"
            class="level-connector"
          />
          <!-- Badge background pill — width is derived from the label text
               (level.badgeW) so long strike labels never clip or overlap -->
          <rect
            :x="level.labelX - level.badgeW / 2"
            :y="level.labelY - 11"
            :width="level.badgeW"
            height="18"
            rx="9"
            class="level-badge-bg"
          />
          <text :x="level.labelX" :y="level.labelY + 2" text-anchor="middle">
            {{ level.label }} ${{ strikeLabel(level.value) }}
          </text>
        </g>

        <!-- Hover / Focus Column Guide Beam -->
        <g v-if="focusBar" class="focus-beam" clip-path="url(#gex-plot-clip)" aria-hidden="true">
          <rect
            :x="focusBar.cx - bandW / 2"
            :y="top"
            :width="bandW"
            :height="plotInnerH"
            class="beam-rect"
          />
        </g>

        <!-- Focus Lock Marker Line -->
        <g v-if="focusStrike != null && lockX != null" class="level focus-lock">
          <line :x1="lockX!" :x2="lockX!" :y1="top" :y2="plotBottom" />
        </g>

        <!-- Cumulative Area / Line (when in cumulative viewMode) -->
        <g
          v-if="viewMode === 'cumulative' && rows.length"
          class="cumulative-group"
          clip-path="url(#gex-plot-clip)"
        >
          <path class="cum-area" :d="cumulativeAreaPath" />
          <path class="cum-line" :d="cumulativeLinePath" />
        </g>

        <!-- STRIKE DATA BARS & INTERACTIVE TARGETS (Clipped safely inside plot frame) -->
        <g v-if="rows.length" class="bars" clip-path="url(#gex-plot-clip)">
          <g
            v-for="bar in bars"
            :key="bar.strike"
            class="strike-bar"
            :class="{
              active: focusBar?.strike === bar.strike,
              locked: focusStrike === bar.strike,
              'put-dominant': bar.putVal > bar.callVal * 1.15,
              'call-dominant': bar.callVal > bar.putVal * 1.15,
            }"
            tabindex="0"
            role="button"
            :aria-pressed="focusStrike === bar.strike"
            :aria-label="barAriaLabel(bar)"
            @mouseenter="hoverStrike = bar.strike"
            @mouseleave="hoverStrike = null"
            @focus="hoverStrike = bar.strike"
            @blur="hoverStrike = null"
            @click="lockStrike(bar.strike)"
            @keydown="onBarKeydown($event, bar.strike)"
          >
            <!-- Full column mouse hit area -->
            <rect
              class="hit"
              :x="bar.cx - bandW / 2"
              :y="top"
              :width="bandW"
              :height="plotInnerH"
            />

            <!-- WINNING SIDE MODE: Call Above (Emerald), Put Below (Crimson) -->
            <template v-if="viewMode === 'winner'">
              <rect
                v-if="bar.winnerH > 0 && bar.winnerSide === 'call'"
                class="call-bar winner-bar"
                :x="bar.cx - bar.thickness / 2"
                :y="bar.winnerY"
                :width="bar.thickness"
                :height="bar.winnerH"
                rx="2"
                ry="2"
              >
                <title>
                  ${{ strikeLabel(bar.strike) }} Call Dominant ({{ bar.dominanceText }})
                  {{ metricValue(bar.callVal) }}
                </title>
              </rect>
              <rect
                v-else-if="bar.winnerH > 0 && bar.winnerSide === 'put'"
                class="put-bar winner-bar"
                :x="bar.cx - bar.thickness / 2"
                :y="bar.winnerY"
                :width="bar.thickness"
                :height="bar.winnerH"
                rx="2"
                ry="2"
              >
                <title>
                  ${{ strikeLabel(bar.strike) }} Put Dominant ({{ bar.dominanceText }})
                  {{ metricValue(bar.putVal) }}
                </title>
              </rect>
            </template>

            <!-- DUAL BARS MODE: Call UP / Put DOWN -->
            <template v-else-if="viewMode === 'dual'">
              <!-- Call Bar (gradient emerald, grows UP from zeroY) -->
              <rect
                v-if="bar.callH > 0"
                class="call-bar"
                :x="bar.cx - bar.thickness / 2"
                :y="bar.callY"
                :width="bar.thickness"
                :height="bar.callH"
                rx="2"
                ry="2"
              >
                <title>${{ strikeLabel(bar.strike) }} Call {{ metricValue(bar.callVal) }}</title>
              </rect>

              <!-- Put Bar (gradient crimson, grows DOWN from zeroY) -->
              <rect
                v-if="bar.putH > 0"
                class="put-bar"
                :x="bar.cx - bar.thickness / 2"
                :y="bar.putY"
                :width="bar.thickness"
                :height="bar.putH"
                rx="2"
                ry="2"
              >
                <title>${{ strikeLabel(bar.strike) }} Put {{ metricValue(bar.putVal) }}</title>
              </rect>
            </template>

            <!-- NET PROFILE MODE: Single Net Bar per Strike -->
            <template v-else-if="viewMode === 'net'">
              <rect
                v-if="bar.netH > 0"
                :class="bar.net >= 0 ? 'call-bar' : 'put-bar'"
                :x="bar.cx - bar.thickness / 2"
                :y="bar.net >= 0 ? zeroY - bar.netH : zeroY"
                :width="bar.thickness"
                :height="bar.netH"
                rx="2"
                ry="2"
              >
                <title>${{ strikeLabel(bar.strike) }} Net {{ metricValue(bar.net, true) }}</title>
              </rect>
            </template>
          </g>
        </g>

        <!-- Wall bars carry direct value labels at the bar tip -->
        <g v-if="wallLabels.length" class="wall-labels" aria-hidden="true">
          <text
            v-for="wl in wallLabels"
            :key="wl.key"
            :x="wl.x"
            :y="wl.y"
            text-anchor="middle"
            class="wall-label halo"
            :class="wl.cls"
          >
            {{ wl.text }}
          </text>
        </g>

        <!-- Continuous Net Trace — smooth swept line, single hover crosshair dot -->
        <g
          v-if="showTrace && viewMode !== 'cumulative' && rows.length"
          class="net-trace-group"
          clip-path="url(#gex-plot-clip)"
          aria-hidden="true"
        >
          <path class="net-trace-path" :d="netTracePath" />
        </g>
        <circle
          v-if="
            showTrace &&
            viewMode !== 'cumulative' &&
            focusBar &&
            (hoverStrike != null || focusStrike != null)
          "
          class="net-trace-dot"
          :cx="focusBar.cx"
          :cy="focusBar.netY"
          r="4.5"
          aria-hidden="true"
        />

        <!-- Y Axis Numbers & Metric Header -->
        <g v-if="rows.length" class="y-axis">
          <text
            v-for="tick in yTicks"
            :key="`yt-${tick.value}`"
            :x="left - 8"
            :y="tick.y + 3.5"
            text-anchor="end"
          >
            {{ axisValue(tick.value) }}
          </text>
        </g>
        <text v-if="rows.length" class="axis-cap" :x="left" :y="14">
          {{
            viewMode === 'cumulative'
              ? metric === 'gex'
                ? 'CUMULATIVE NET GEX $M'
                : 'CUMULATIVE NET OI'
              : viewMode === 'winner'
                ? metric === 'gex'
                  ? 'WINNER GEX $M · CALL UP / PUT DN'
                  : 'WINNER OI · CALL UP / PUT DN'
                : metric === 'gex'
                  ? 'GEX $M · CALL UP / PUT DN'
                  : 'OI · CALL UP / PUT DN'
          }}
        </text>

        <!-- X Axis Strikes & Tick Marks -->
        <g v-if="rows.length" class="x-axis">
          <template v-for="tick in strikeTicks" :key="`st-${tick.strike}`">
            <rect
              v-if="tick.isSpot"
              :x="tick.x - 24"
              :y="plotBottom + 7"
              width="48"
              height="16"
              rx="8"
              class="spot-pill"
            />
            <line
              :x1="tick.x"
              :x2="tick.x"
              :y1="plotBottom"
              :y2="plotBottom + 5"
              :class="{ 'spot-tick': tick.isSpot }"
            />
            <text
              :x="tick.x"
              :y="plotBottom + 19"
              text-anchor="middle"
              :class="{ 'spot-label': tick.isSpot }"
            >
              ${{ tick.label }}
            </text>
          </template>
        </g>

        <!-- Empty State Viewfinder -->
        <g v-if="!rows.length" class="empty-group">
          <rect :x="W / 2 - 140" :y="H / 2 - 24" width="280" height="48" class="empty-frame" />
          <text :x="W / 2" :y="H / 2 + 4" text-anchor="middle" class="empty">
            NO QUALIFYING GAMMA OBSERVATIONS
          </text>
        </g>
      </svg>
    </div>

    <!-- Options Strike Matrix Table (Rendered in SPLIT and TABLE modes) -->
    <div
      v-if="layoutMode !== 'graph'"
      class="gex-table-wrap"
      :class="{ 'full-view': layoutMode === 'table' }"
    >
      <div class="gex-table-toolbar">
        <div class="gex-table-search">
          <input
            v-model="tableFilter"
            type="text"
            placeholder="Filter strikes / tags (call, put, wall, flip)..."
            class="gex-table-input label"
            aria-label="Filter strike matrix"
          />
          <button
            v-if="tableFilter"
            type="button"
            class="clear-input label"
            @click="tableFilter = ''"
          >
            ×
          </button>
        </div>
        <span class="table-count label"> {{ filteredTableRows.length }} STRIKES </span>
      </div>
      <div class="gex-table-scroll">
        <table class="gex-strike-table" role="table" aria-label="Options strike matrix">
          <thead>
            <tr>
              <th :class="{ active: tableSortKey === 'strike' }" @click="setTableSort('strike')">
                STRIKE
                <span class="sort-arr">{{
                  tableSortKey === 'strike' ? (tableSortDir === 'asc' ? '▲' : '▼') : ''
                }}</span>
              </th>
              <th :class="{ active: tableSortKey === 'winner' }" @click="setTableSort('winner')">
                WINNER / BIAS
                <span class="sort-arr">{{
                  tableSortKey === 'winner' ? (tableSortDir === 'asc' ? '▲' : '▼') : ''
                }}</span>
              </th>
              <th
                class="num-col"
                :class="{ active: tableSortKey === 'call' }"
                @click="setTableSort('call')"
              >
                CALL {{ metric.toUpperCase() }}
                <span class="sort-arr">{{
                  tableSortKey === 'call' ? (tableSortDir === 'asc' ? '▲' : '▼') : ''
                }}</span>
              </th>
              <th
                class="num-col"
                :class="{ active: tableSortKey === 'put' }"
                @click="setTableSort('put')"
              >
                PUT {{ metric.toUpperCase() }}
                <span class="sort-arr">{{
                  tableSortKey === 'put' ? (tableSortDir === 'asc' ? '▲' : '▼') : ''
                }}</span>
              </th>
              <th
                class="num-col"
                :class="{ active: tableSortKey === 'net' }"
                @click="setTableSort('net')"
              >
                NET {{ metric.toUpperCase() }}
                <span class="sort-arr">{{
                  tableSortKey === 'net' ? (tableSortDir === 'asc' ? '▲' : '▼') : ''
                }}</span>
              </th>
              <th
                class="num-col"
                :class="{ active: tableSortKey === 'dist' }"
                @click="setTableSort('dist')"
              >
                SPOT DISTANCE
                <span class="sort-arr">{{
                  tableSortKey === 'dist' ? (tableSortDir === 'asc' ? '▲' : '▼') : ''
                }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="bar in filteredTableRows"
              :key="`row-${bar.strike}`"
              :class="{
                'active-row': focusBar?.strike === bar.strike,
                'locked-row': focusStrike === bar.strike,
                'spot-row': bar.isSpotNear,
              }"
              tabindex="0"
              role="row"
              @mouseenter="hoverStrike = bar.strike"
              @mouseleave="hoverStrike = null"
              @click="lockStrike(bar.strike)"
              @keydown.enter.prevent="lockStrike(bar.strike)"
              @keydown.space.prevent="lockStrike(bar.strike)"
            >
              <td class="strike-cell">
                <span class="strike-val">${{ strikeLabel(bar.strike) }}</span>
                <span v-if="bar.isSpotNear" class="tag-badge spot">SPOT</span>
                <span v-if="bar.isCallWall" class="tag-badge call">CALL W</span>
                <span v-if="bar.isPutWall" class="tag-badge put">PUT W</span>
                <span v-if="bar.isFlip" class="tag-badge flip">FLIP</span>
              </td>
              <td>
                <span class="winner-pill" :class="bar.winnerSide">
                  <i class="winner-dot" />
                  {{ bar.dominanceText }}
                </span>
              </td>
              <td class="num-col call-num">
                {{ metricValue(bar.callVal) }}
                <small class="sub-num">OI {{ compact(bar.call_oi) }}</small>
              </td>
              <td class="num-col put-num">
                {{ metricValue(bar.putVal) }}
                <small class="sub-num">OI {{ compact(bar.put_oi) }}</small>
              </td>
              <td class="num-col net-num" :class="bar.net >= 0 ? 'positive' : 'negative'">
                <span class="net-val">{{ metricValue(bar.net, true) }}</span>
                <div class="net-micro-meter">
                  <i
                    :class="bar.net >= 0 ? 'meter-pos' : 'meter-neg'"
                    :style="{
                      width: `${Math.min(100, (Math.abs(bar.net) / (maxAbs || 1)) * 100)}%`,
                    }"
                  />
                </div>
              </td>
              <td class="num-col dist-num">
                {{ distanceLabel(bar.strike) }}
              </td>
            </tr>
            <tr v-if="!filteredTableRows.length">
              <td colspan="6" class="no-rows">No strikes match the filter.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Surface glass token: var(--glass-surface-hi) */
.gex-map {
  width: 100%;
  max-width: 100%;
  height: 100%;
  max-height: 100%;
  box-sizing: border-box;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  gap: 6px;
  background: var(--panel);
  padding: 6px 10px 8px;
}

.map-controls {
  display: flex;
  align-items: center;
  gap: 6px 8px;
  margin: 0;
  flex: 0 0 auto;
  flex-wrap: wrap;
  min-width: 0;
  max-width: 100%;
}

.control-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.mini-segment {
  display: inline-flex;
  align-items: center;
  padding: 2px;
  min-height: 26px;
  border: var(--hair) solid var(--glass-border);
  background: var(--glass-base);
  border-radius: var(--r-sm);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.25);
}

.mini-segment button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 8px;
  color: var(--ink-dim);
  border: none;
  font: 600 var(--t-micro) var(--font-display);
  letter-spacing: 0.04em;
  min-height: 22px;
  cursor: pointer;
  background: transparent;
  border-radius: var(--r-xs);
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out);
}

.mini-segment button:hover {
  color: var(--ink);
  background: var(--glass-surface-hi);
}

.mini-segment button.on {
  color: var(--void);
  background: var(--phosphor);
  font-weight: 750;
  box-shadow: var(--glass-specular);
}

.pill-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 9px;
  min-height: 26px;
  color: var(--ink-dim);
  border: var(--hair) solid var(--glass-border);
  background: var(--glass-base);
  border-radius: 9999px;
  font: 600 var(--t-micro) var(--font-display);
  letter-spacing: 0.05em;
  cursor: pointer;
  box-shadow: var(--glass-specular-subtle);
  transition: all var(--dur-fast) var(--ease-out);
}

.pill-toggle:hover {
  color: var(--ink);
  border-color: var(--glass-border-hi);
  background: var(--glass-surface-hi);
}

.pill-toggle.active {
  color: var(--void);
  background: var(--phosphor);
  border-color: var(--phosphor);
  box-shadow: var(--glass-specular);
}

.quick-levels {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--glass-base);
  padding: 2px 6px;
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-sm);
  flex-wrap: wrap;
}

.quick-title {
  color: var(--ink-faint);
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.06em;
}

.level-chip {
  position: relative;
  /* .label clips overflow; the chip needs it visible so the hit target below
     is not cut back to the painted size. */
  overflow: visible;
  padding: 2px 8px;
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.03em;
  cursor: pointer;
  border: var(--hair) solid var(--glass-border);
  border-radius: 9999px;
  background: var(--void-lift);
  box-shadow: var(--glass-specular-subtle);
  transition:
    transform 0.15s cubic-bezier(0.16, 1, 0.3, 1),
    opacity 0.15s ease,
    background 0.15s ease;
  white-space: nowrap;
}

.level-chip:hover {
  background: var(--panel-hi);
  border-color: var(--glass-border-hi);
  transform: translateY(-0.5px);
}

.level-chip.put {
  color: var(--put-hi);
  border-color: var(--put);
  background: var(--put-wash);
}
.level-chip.call {
  color: var(--call-hi);
  border-color: var(--call);
  background: var(--call-wash);
}
.level-chip.flip {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}
.level-chip.spot {
  color: var(--ink);
  border-color: var(--ink-dim);
  background: var(--void-lift);
}
/* Painted size stays compact for desk density; this restores a 28px pointer
   target underneath without touching layout. */
.level-chip::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: max(100%, 28px);
  height: max(100%, 28px);
  transform: translate(-50%, -50%);
}

.coverage {
  margin-left: auto;
  color: var(--ink-dim);
  font: 500 var(--t-micro) var(--font-data);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.coverage .call-leg,
.coverage .put-leg,
.coverage .net-leg {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-weight: 700;
}

.coverage .call-leg {
  color: var(--call-hi);
}
.coverage .put-leg {
  color: var(--put-hi);
}
.coverage .net-leg {
  color: var(--ink-soft);
}

.leg-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: 0 0 auto;
}

.leg-dot.call {
  background: var(--call);
}
.leg-dot.put {
  background: var(--put);
}
.leg-dot.net {
  background: var(--ink-soft);
}

.exposure-head {
  display: flex;
  min-height: 36px;
  max-height: 38px;
  background: var(--void-lift);
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-md);
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  box-shadow: var(--glass-shadow-sm), var(--glass-specular-subtle);
}

.exposure-totals {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  width: 100%;
  min-width: 0;
  background: var(--rule);
}

.exposure-total {
  min-width: 0;
  min-height: 34px;
  padding: 3px 10px;
  background: var(--void-lift);
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  position: relative;
  overflow: hidden;
}

.exposure-total::after {
  content: '';
  position: absolute;
  inset: auto 0 0;
  height: 2px;
  background: currentColor;
}

.exposure-total .label {
  color: var(--ink-dim);
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.05em;
  flex: 0 0 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.exposure-total strong {
  font: 700 0.875rem var(--font-data);
  line-height: 1.15;
  color: inherit;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: right;
}

.exposure-total.call {
  color: var(--call-hi);
}
.exposure-total.put {
  color: var(--put-hi);
}
.exposure-total.net {
  color: var(--phosphor);
}
.exposure-total.net.negative {
  color: var(--put-hi);
}

.strike-focus {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 12px;
  background: var(--void-lift);
  padding: 2px 10px;
  min-width: 0;
  min-height: 34px;
  overflow: hidden;
}

.focus-strike,
.focus-metric {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 1px;
  overflow: hidden;
}

.focus-strike > .label,
.focus-metric > .label {
  color: var(--phosphor);
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.06em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.focus-strike > strong {
  font: 700 0.875rem var(--font-data);
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dist-tag {
  color: var(--ink-dim);
  font: 500 var(--t-micro) var(--font-data);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.focus-metric strong {
  overflow: hidden;
  font: 700 var(--t-micro) var(--font-data);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.focus-metric small {
  color: var(--ink-faint);
  font: 500 var(--t-micro) var(--font-data);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.focus-metric.call strong {
  color: var(--call-hi);
}
.focus-metric.put strong {
  color: var(--put-hi);
}
.focus-metric.net.positive strong {
  color: var(--call-hi);
}
.focus-metric.net.negative strong {
  color: var(--put-hi);
}

.plot-scroll {
  position: relative;
  overflow-x: auto;
  overflow-y: hidden;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs, 2px);
  flex: 1 1 0;
  min-height: 0;
  background: var(--void);
}

.plot-scroll::-webkit-scrollbar {
  height: 6px;
}
.plot-scroll::-webkit-scrollbar-track {
  background: var(--void);
}
.plot-scroll::-webkit-scrollbar-thumb {
  background: var(--rule-hi);
  border-radius: 3px;
}
.plot-scroll::-webkit-scrollbar-thumb:hover {
  background: var(--rule);
}

svg {
  display: block;
  background: var(--void);
}

.plot-frame {
  fill: var(--void-lift);
  stroke: var(--rule-hi);
  stroke-width: 1;
}

.regime-zone.neg {
  fill: color-mix(in srgb, var(--put) 3%, transparent);
}

.regime-zone.pos {
  fill: color-mix(in srgb, var(--call) 3%, transparent);
}

.regime-label {
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.1em;
  pointer-events: none;
  opacity: 0.7;
}

.regime-label.neg {
  fill: var(--put-hi);
}

.regime-label.pos {
  fill: var(--call-hi);
}

/* Halo keeps floating plot text legible when it crosses a bar. */
.halo {
  paint-order: stroke;
  stroke: var(--void);
  stroke-width: 3.5px;
  stroke-linejoin: round;
}

.grid line {
  stroke: var(--rule);
  stroke-width: 1px;
  opacity: 0.55;
  vector-effect: non-scaling-stroke;
}

.grid line.vgrid {
  opacity: 0.22;
}

.grid line.zero {
  stroke: none;
  opacity: 0;
}

.zero-baseline {
  stroke: var(--rule-hi);
  stroke-width: 1px;
  opacity: 1;
  vector-effect: non-scaling-stroke;
}

.y-axis text,
.x-axis text {
  fill: var(--ink-dim);
  font: 600 var(--t-micro) var(--font-data);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

.y-axis text {
  fill: var(--ink-soft);
}

.x-axis text.spot-label {
  fill: var(--ink);
  font-weight: 700;
}

.spot-pill {
  fill: var(--phosphor-wash);
  stroke: var(--phosphor-dim);
  stroke-width: 1px;
}

.x-axis line {
  stroke: var(--rule-hi);
  vector-effect: non-scaling-stroke;
}

.x-axis line.spot-tick {
  stroke: var(--phosphor);
  stroke-width: 1.5px;
}

.axis-cap {
  fill: var(--ink-dim);
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.08em;
}

.strike-bar {
  cursor: pointer;
}

.strike-bar:focus-visible {
  outline: var(--hair) solid var(--phosphor);
  outline-offset: 2px;
}

.strike-bar:focus-visible .hit,
.strike-bar:focus .hit {
  stroke: var(--phosphor);
  stroke-width: 1;
}

.strike-bar .hit {
  fill: transparent;
  pointer-events: all;
}

.focus-beam .beam-rect {
  fill: var(--phosphor-wash);
  stroke: none;
  pointer-events: none;
}

/* Flat token fills for calls and puts matching instrument design rules */
.strike-bar .call-bar,
.strike-bar .put-bar {
  vector-effect: non-scaling-stroke;
  stroke: none;
  opacity: 0.96;
  transition: opacity 0.12s ease;
}

.strike-bar .call-bar {
  fill: var(--call);
}

.strike-bar .put-bar {
  fill: var(--put);
}

.strike-bar .net-dot {
  fill: var(--ink);
}

.strike-bar.call-dominant .call-bar {
  opacity: 1;
  fill: var(--call-hi);
}

.strike-bar.put-dominant .put-bar {
  opacity: 1;
  fill: var(--put-hi);
}

.strike-bar:hover .call-bar,
.strike-bar.active .call-bar,
.strike-bar:hover .put-bar,
.strike-bar.active .put-bar {
  opacity: 1;
}

.strike-bar.locked .call-bar {
  opacity: 1;
  fill: var(--call-hi);
}

.strike-bar.locked .put-bar {
  opacity: 1;
  fill: var(--put-hi);
}

/* Direct value labels on the wall bars — text wears text ink, never series hue */
.wall-label {
  font: 700 var(--t-micro) var(--font-data);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
  fill: var(--ink);
  pointer-events: none;
}

.net-trace-path {
  fill: none;
  stroke: var(--ink-soft);
  stroke-width: 1.75;
  stroke-linejoin: round;
  stroke-linecap: round;
  opacity: 0.9;
  pointer-events: none;
  vector-effect: non-scaling-stroke;
}

/* Single crosshair dot that rides the trace on hover — 2px surface ring so it
   stays legible where it crosses bars or the trace itself */
.net-trace-dot {
  fill: var(--ink);
  stroke: var(--void);
  stroke-width: 2px;
  pointer-events: none;
}

.cumulative-group .cum-area {
  fill: var(--phosphor-wash);
  opacity: 0.55;
  pointer-events: none;
}

.cumulative-group .cum-line {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1.75;
  stroke-linejoin: round;
  stroke-linecap: round;
  pointer-events: none;
  vector-effect: non-scaling-stroke;
}

.focus-lock line {
  stroke: var(--phosphor);
  stroke-width: 1.5;
  stroke-dasharray: 3 3;
  vector-effect: non-scaling-stroke;
}

.clear-lock {
  margin-left: 2px;
  padding: 2px 6px;
  min-height: 20px;
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  cursor: pointer;
  font: 700 var(--t-micro) var(--font-display);
}

.clear-lock:hover {
  color: var(--void);
  background: var(--phosphor);
}

.level line {
  stroke-width: 1.25px;
  stroke-dasharray: 4 4;
  vector-effect: non-scaling-stroke;
  opacity: 0.85;
  transition:
    stroke 0.12s ease,
    opacity 0.12s ease;
}

.level.call line {
  stroke: var(--call-hi);
}
.level.put line {
  stroke: var(--put-hi);
}
.level.spot line {
  stroke: var(--ink);
  stroke-dasharray: none;
  stroke-width: 1.5px;
  opacity: 0.9;
}
.level.flip line {
  stroke: var(--warn);
}

.level-connector {
  stroke-width: 1px;
  stroke-dasharray: 2 2;
  opacity: 0.7;
  pointer-events: none;
  vector-effect: non-scaling-stroke;
}
line.level-connector {
  fill: none;
}
.level.call .level-connector {
  stroke: var(--call-hi);
}
.level.put .level-connector {
  stroke: var(--put-hi);
}
.level.spot .level-connector {
  stroke: var(--ink-dim);
}
.level.flip .level-connector {
  stroke: var(--warn);
}

.level-badge-bg {
  fill: var(--void-lift);
  stroke: var(--rule-hi);
  stroke-width: 1px;
}
.level.call .level-badge-bg {
  fill: var(--call-wash);
  stroke: var(--call);
}
.level.put .level-badge-bg {
  fill: var(--put-wash);
  stroke: var(--put);
}
.level.spot .level-badge-bg {
  fill: var(--void-lift);
  stroke: var(--ink-dim);
}
.level.flip .level-badge-bg {
  fill: var(--warn-wash);
  stroke: var(--warn);
}

.level text {
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.04em;
  pointer-events: none;
}

.level.call text {
  fill: var(--call-hi);
}
.level.put text {
  fill: var(--put-hi);
}
.level.spot text {
  fill: var(--ink);
}
.level.flip text {
  fill: var(--warn);
}

.empty-frame {
  fill: var(--void);
  stroke: var(--rule-hi);
  stroke-width: 1;
}

.empty {
  fill: var(--ink-dim);
  font: 600 var(--t-micro) var(--font-display);
  letter-spacing: 0.08em;
}

/* =========================================================================
   OPTIONS STRIKE MATRIX TABLE (GRAPH TABLE)
   ========================================================================= */
.gex-table-wrap {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs, 2px);
  background: var(--void);
  overflow: hidden;
}

.gex-table-wrap.full-view {
  flex: 1 1 auto;
  height: 100%;
}

.gex-table-wrap:not(.full-view) {
  flex: 1 1 200px;
  max-height: 48%;
}

.gex-table-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  background: var(--void-lift);
  border-bottom: var(--hair) solid var(--rule);
  gap: 8px;
}

.gex-table-search {
  position: relative;
  display: flex;
  align-items: center;
  flex: 1 1 260px;
  max-width: 320px;
}

.gex-table-input {
  width: 100%;
  min-height: 22px;
  padding: 2px 22px 2px 6px;
  border: var(--hair) solid var(--glass-border);
  background: var(--glass-base);
  border-radius: var(--r-xs);
  color: var(--ink);
  font: 500 var(--t-micro) var(--font-data);
  outline: none;
}

.gex-table-input:focus {
  border-color: var(--phosphor);
}

.clear-input {
  position: absolute;
  right: 4px;
  background: transparent;
  border: none;
  color: var(--ink-dim);
  cursor: pointer;
  font: 700 var(--t-micro) var(--font-display);
  padding: 0 4px;
}

.table-count {
  color: var(--ink-dim);
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.05em;
}

.gex-table-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: auto;
}

.gex-table-scroll::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.gex-table-scroll::-webkit-scrollbar-track {
  background: var(--void);
}
.gex-table-scroll::-webkit-scrollbar-thumb {
  background: var(--rule-hi);
  border-radius: 3px;
}

.gex-strike-table {
  width: 100%;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
  text-align: left;
}

.gex-strike-table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--panel-hi);
  padding: 5px 8px;
  color: var(--ink-dim);
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.04em;
  border-bottom: var(--hair) solid var(--rule-hi);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}

.gex-strike-table thead th:hover {
  color: var(--ink);
  background: var(--panel-raise);
}

.gex-strike-table thead th.active {
  color: var(--phosphor);
}

.sort-arr {
  font-size: var(--t-micro);
  margin-left: 2px;
}

.gex-strike-table tbody tr {
  border-bottom: var(--hair) solid var(--rule-faint);
  cursor: pointer;
  transition: background var(--dur-fast) ease;
}

.gex-strike-table tbody tr:hover {
  background: var(--glass-surface-hi);
}

.gex-strike-table tbody tr.active-row {
  background: var(--phosphor-wash);
}

.gex-strike-table tbody tr.locked-row {
  background: var(--phosphor-wash);
  outline: 1px solid var(--phosphor-dim);
}

.gex-strike-table tbody td {
  padding: 4px 8px;
  font: 500 var(--t-micro) var(--font-data);
  color: var(--ink);
  white-space: nowrap;
}

.strike-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.strike-val {
  font-weight: 700;
}

.tag-badge {
  padding: 1px 4px;
  border-radius: 3px;
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.03em;
}

.tag-badge.spot {
  background: var(--void-lift);
  border: var(--hair) solid var(--ink-dim);
  color: var(--ink);
}
.tag-badge.call {
  background: var(--call-wash);
  border: var(--hair) solid var(--call);
  color: var(--call-hi);
}
.tag-badge.put {
  background: var(--put-wash);
  border: var(--hair) solid var(--put);
  color: var(--put-hi);
}
.tag-badge.flip {
  background: var(--warn-wash);
  border: var(--hair) solid var(--warn);
  color: var(--warn);
}

.winner-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border-radius: 9999px;
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.03em;
}

.winner-pill.call {
  background: var(--call-wash);
  border: var(--hair) solid var(--call);
  color: var(--call-hi);
}

.winner-pill.put {
  background: var(--put-wash);
  border: var(--hair) solid var(--put);
  color: var(--put-hi);
}

.winner-pill.flat {
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
}

.winner-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.num-col {
  text-align: right;
}

.sub-num {
  display: block;
  font-size: var(--t-micro);
  color: var(--ink-faint);
}

.call-num {
  color: var(--call-hi);
}

.put-num {
  color: var(--put-hi);
}

.net-num {
  position: relative;
}

.net-num.positive .net-val {
  color: var(--call-hi);
}
.net-num.negative .net-val {
  color: var(--put-hi);
}

.net-micro-meter {
  width: 100%;
  height: 2px;
  background: var(--rule-faint);
  margin-top: 2px;
  position: relative;
  overflow: hidden;
}

.meter-pos {
  display: block;
  height: 100%;
  background: var(--call);
}

.meter-neg {
  display: block;
  height: 100%;
  background: var(--put);
  margin-left: auto;
}

.dist-num {
  color: var(--ink-dim);
}

.no-rows {
  text-align: center;
  padding: 16px;
  color: var(--ink-dim);
  font: 500 var(--t-micro) var(--font-display);
}

@media (max-width: 900px) {
  .coverage {
    width: 100%;
    margin-left: 0;
  }
  .exposure-totals {
    flex: 1 1 100%;
  }
  .strike-focus {
    flex: 1 1 100%;
  }
}

@media (max-width: 620px) {
  .strike-focus {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .clear-lock {
    justify-self: start;
  }
}
</style>
