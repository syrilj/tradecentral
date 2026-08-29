<script setup lang="ts">
/**
 * Live dealer-gamma regime surface — the main graph on /regime.
 *
 * Price is the ONE vertical axis, shared by every layer, so distribution
 * mass reads directly against structure instead of living in two
 * incomparable charts:
 *
 *   · left lane  — horizontal GEX bars per strike (call right / put left of
 *     a shared zero line), from `gexByStrike`.
 *   · right lane — the tilted density curve (the asserted regime model,
 *     coloured by regime) with the UNTILTED risk-neutral density always
 *     plotted alongside it as a quieter audit line. The tilt is a model,
 *     not a fact; the untilted curve is never optional decoration.
 *   · full-width rules — zero-gamma flip, call wall, put wall, pin strike,
 *     each labelled, plus live spot as a distinct marker that moves on the
 *     fast clock without touching the GEX bars or density curves.
 *
 * When `state.measurable` is false (no open interest), the GEX lane
 * withholds its bars rather than drawing zeros — see the empty-lane note.
 */
import { computed, ref } from 'vue'
import type { GexStrikeRow } from '@/api'
import type { DensityGrid, GammaRegime, RegimeState } from '@/regimeContracts'
import { linearScale, niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'
import { DASH, num, optGex } from '@/format'

const props = withDefaults(
  defineProps<{
    symbol?: string
    gexByStrike: GexStrikeRow[]
    tiltedGrid: DensityGrid | null
    untiltedGrid: DensityGrid | null
    state: RegimeState
    /** False when the density mass had to be clipped so heavily that the
     *  curves are artifacts, not a distribution (the ATM put/call step on a
     *  very short expiry). The rail already withholds the probabilities in
     *  that case; the lane must withhold the curves too rather than draw
     *  confident-looking scribble. */
    densityReliable?: boolean
    focusStrike?: number | null
  }>(),
  { symbol: '', densityReliable: true, focusStrike: null },
)

const emit = defineEmits<{
  'update:focusStrike': [strike: number | null]
}>()

const hostRef = ref<HTMLDivElement | null>(null)
const { W, H } = useChartSize(hostRef, { minW: 320, minH: 320, fallbackW: 760, fallbackH: 440 })

/* ---- layout -------------------------------------------------------------
 * Two lanes sharing one price (Y) axis: GEX bars on the left, density
 * curves on the right. `left` reserves room for price labels; `right`
 * reserves room for structural-level badges. */
const left = 60
const right = 108
const top = 40
const bottom = 26
const laneGap = 20

const innerW = computed(() => Math.max(80, W.value - left - right))
const innerH = computed(() => Math.max(80, H.value - top - bottom))
const gexLaneW = computed(() => Math.max(40, (innerW.value - laneGap) * 0.42))
const densityLaneW = computed(() => Math.max(40, innerW.value - laneGap - gexLaneW.value))
const gexX0 = left
const gexX1 = computed(() => gexX0 + gexLaneW.value)
const densityX0 = computed(() => gexX1.value + laneGap)
const zeroX = computed(() => gexX0 + gexLaneW.value / 2)
const halfGexW = computed(() => Math.max(2, gexLaneW.value / 2 - 3))

/* ---- windowed strikes: near the money is the readable region ----------
 * Observed live on SPY: the density grids span +/-30-50% (smile
 * extrapolation across the whole quoted chain) while every structural level
 * sits within 0.3% of spot. Taking the domain as the union of ALL grid
 * strikes compressed the tradeable region — flip, both walls, pin, spot and
 * every meaningful GEX bar — into a ~2px band in the middle of a 600-1200
 * axis. Everything on this chart is windowed to the SAME near-money band so
 * the axis serves the region the operator can actually act on; levels
 * outside the band still stretch the domain to include them. */
const RANGE_PCT = 0.07

function windowBySpot<T extends number>(strikes: T[], spot: number | null, minKeep: number): T[] {
  if (!spot || spot <= 0 || strikes.length <= minKeep) return strikes
  for (const pct of [RANGE_PCT, 0.15]) {
    const windowed = strikes.filter((s) => s >= spot * (1 - pct) && s <= spot * (1 + pct))
    if (windowed.length >= minKeep) return windowed
  }
  return strikes
}

const visibleRows = computed<GexStrikeRow[]>(() => {
  const rows = props.gexByStrike.filter((r) => Number.isFinite(r.strike))
  const kept = windowBySpot(
    rows.map((r) => r.strike),
    props.state.spot,
    6,
  )
  if (kept.length === rows.length) return rows
  const keep = new Set(kept)
  return rows.filter((r) => keep.has(r.strike))
})

/** Subset a density grid to [lo, hi]. A curve drawn outside the frame would
 *  also pollute the domain; clipping first keeps the axis honest. */
function clipGrid(grid: DensityGrid | null, lo: number, hi: number): DensityGrid | null {
  if (!grid) return null
  const strikes: number[] = []
  const density: number[] = []
  for (let i = 0; i < grid.strikes.length; i++) {
    const s = grid.strikes[i]
    if (s >= lo && s <= hi) {
      strikes.push(s)
      density.push(grid.density[i])
    }
  }
  if (strikes.length < 2) return null
  return { ...grid, strikes, density }
}

/* ---- shared price domain ------------------------------------------------
 * Union of windowed strikes, the windowed grids, spot, and every structural
 * level, padded a little so nothing sits flush on the frame. */
const priceDomain = computed<[number, number]>(() => {
  const values: number[] = []
  for (const r of visibleRows.value) values.push(r.strike)
  const { spot, zeroGamma, callWall, putWall, pinStrike } = props.state
  // Levels always join the domain even when outside the strike window — a
  // wall 12% away is far more decision-relevant than the strikes near spot.
  for (const v of [spot, zeroGamma, callWall, putWall, pinStrike]) {
    if (v != null && Number.isFinite(v)) values.push(v)
  }
  const finite = values.filter((v) => Number.isFinite(v))
  if (!finite.length) return [0, 1]
  let lo = Math.min(...finite)
  let hi = Math.max(...finite)
  if (lo === hi) {
    lo -= Math.max(1, Math.abs(lo) * 0.05)
    hi += Math.max(1, Math.abs(hi) * 0.05)
  }
  const pad = (hi - lo) * 0.06
  return [lo - pad, hi + pad]
})

/** Both grids, clipped to the SAME domain the axis displays. */
const visibleTiltedGrid = computed(() =>
  clipGrid(props.tiltedGrid, priceDomain.value[0], priceDomain.value[1]),
)
const visibleUntiltedGrid = computed(() =>
  clipGrid(props.untiltedGrid, priceDomain.value[0], priceDomain.value[1]),
)

const priceScale = computed(() => linearScale(priceDomain.value, [top + innerH.value, top]))
const priceTicks = computed(() =>
  niceTicks(priceDomain.value[0], priceDomain.value[1], H.value < 260 ? 4 : 6),
)

/* ---- GEX lane ------------------------------------------------------------
 * Square-root width scale, not linear. Observed live on SPY: the call wall
 * strike carried ~$3.2B of gamma against a ~$0.5M median across the window
 * — a linear scale keyed to that max leaves 93% of visible bars under 2px,
 * which is how this chart read as an empty frame. Sqrt keeps the ordering
 * exact and the ordering is what the lane is for; the wall still reads as
 * full-width, but the rungs around it now show their ladder. */
const gexMaxAbs = computed(() => {
  const vals = visibleRows.value.flatMap((r) => [
    Math.abs(r.call_gex_m || 0),
    Math.abs(r.put_gex_m || 0),
  ])
  return Math.max(1e-9, ...vals)
})
const gexScale = computed(() => (v: number) => {
  const t = Math.min(1, Math.max(0, v / gexMaxAbs.value))
  return Math.sqrt(t) * halfGexW.value
})

const gexBarThickness = computed(() => {
  const n = visibleRows.value.length || 1
  const raw = (innerH.value / n) * 0.7
  return Math.max(2, Math.min(9, raw))
})

interface GexBar {
  strike: number
  y: number
  callW: number
  putW: number
  callVal: number
  putVal: number
  netVal: number
}

const gexBars = computed<GexBar[]>(() =>
  visibleRows.value.map((r) => ({
    strike: r.strike,
    y: priceScale.value(r.strike),
    callW: gexScale.value(Math.max(0, r.call_gex_m || 0)),
    putW: gexScale.value(Math.max(0, Math.abs(r.put_gex_m || 0))),
    callVal: r.call_gex_m,
    putVal: r.put_gex_m,
    netVal: r.net_gex_m,
  })),
)

/* ---- density lane ---------------------------------------------------- */
const densityMax = computed(() => {
  const vals: number[] = []
  if (visibleTiltedGrid.value) vals.push(...visibleTiltedGrid.value.density)
  if (visibleUntiltedGrid.value) vals.push(...visibleUntiltedGrid.value.density)
  return Math.max(1e-12, ...vals, 0)
})
const densityScale = computed(() => linearScale([0, densityMax.value], [0, densityLaneW.value - 6]))

function densityPath(grid: DensityGrid | null): string {
  if (!grid || grid.strikes.length < 2) return ''
  const pts = grid.strikes.map((strike, i) => ({
    x: densityX0.value + densityScale.value(Math.max(0, grid.density[i])),
    y: priceScale.value(strike),
  }))
  let d = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`
  for (let i = 1; i < pts.length; i++) d += ` L ${pts[i].x.toFixed(1)} ${pts[i].y.toFixed(1)}`
  return d
}

/** Closed area under the tilted curve, baseline = the lane's left edge
 *  (the curve is a function of Y here, so the baseline is vertical, not
 *  horizontal — this is hand-built rather than forced through the
 *  Y-baseline `areaPath` helper, which assumes the opposite orientation). */
function densityAreaPath(grid: DensityGrid | null): string {
  if (!grid || grid.strikes.length < 2) return ''
  const pts = grid.strikes.map((strike, i) => ({
    x: densityX0.value + densityScale.value(Math.max(0, grid.density[i])),
    y: priceScale.value(strike),
  }))
  const line = pts
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(' ')
  const last = pts[pts.length - 1]
  const first = pts[0]
  return `${line} L ${densityX0.value.toFixed(1)} ${last.y.toFixed(1)} L ${densityX0.value.toFixed(1)} ${first.y.toFixed(1)} Z`
}

const tiltedPath = computed(() =>
  props.densityReliable ? densityPath(visibleTiltedGrid.value) : '',
)
const tiltedAreaPath = computed(() =>
  props.densityReliable ? densityAreaPath(visibleTiltedGrid.value) : '',
)
const untiltedPath = computed(() =>
  props.densityReliable ? densityPath(visibleUntiltedGrid.value) : '',
)

/** The tilted curve is the one asserted claim in the stack — colour it by
 *  the regime it asserts. Neutral ink when there is nothing to assert. */
const regimeTone = computed<string>(() => {
  const r: GammaRegime = props.state.regime
  if (r === 'short') return 'var(--short)'
  if (r === 'long') return 'var(--long)'
  return 'var(--ink-dim)'
})
const regimeWash = computed<string>(() => {
  const r: GammaRegime = props.state.regime
  if (r === 'short') return 'var(--short-wash)'
  if (r === 'long') return 'var(--long-wash)'
  return 'var(--panel-wash)'
})

/* ---- structural levels: full-width labelled rules ---------------------- */
interface LevelLine {
  key: string
  label: string
  /** Compact form for the badge, which has ~98px. `label` stays the full name
   *  and is what the accessible table and aria-label read out. */
  shortLabel: string
  value: number
  y: number
  colorVar: string
  dash: string
}

const levels = computed<LevelLine[]>(() => {
  const s = props.state
  const out: LevelLine[] = []
  const push = (
    key: string,
    label: string,
    shortLabel: string,
    value: number | null,
    colorVar: string,
    dash: string,
  ) => {
    if (value == null || !Number.isFinite(value)) return
    out.push({ key, label, shortLabel, value, y: priceScale.value(value), colorVar, dash: dash })
  }
  push('flip', 'ZERO-GAMMA FLIP', 'FLIP', s.zeroGamma, 'var(--warn)', '5 3')
  push('call', 'CALL WALL', 'CALL W', s.callWall, 'var(--call)', '5 3')
  push('put', 'PUT WALL', 'PUT W', s.putWall, 'var(--put)', '5 3')
  push('pin', 'PIN STRIKE', 'PIN', s.pinStrike, 'var(--ink-soft)', '2 3')
  return out
})

const spotY = computed(() => {
  const s = props.state.spot
  if (s == null || !Number.isFinite(s)) return null
  return priceScale.value(s)
})

/**
 * Vertical de-collision for the right-rail badges.
 *
 * Every badge — spot and each structural level — is drawn at the same x, so
 * two prices that are close in value overlap into unreadable text. That is not
 * an edge case here: spot sits near the flip almost by definition, which is
 * exactly when the reading matters most.
 *
 * Only the LABEL moves; each rule line stays on its true price. Spot is
 * pinned to its exact y because it is the live anchor the eye tracks, and
 * levels are pushed away from it — outward in both directions — so the
 * displacement always reads as "this label belongs slightly off its line"
 * rather than shifting the one marker that must not lie.
 */
const BADGE_MIN_GAP = 19

const badgeLayout = computed<Map<string, number>>(() => {
  const placed = new Map<string, number>()
  const entries = levels.value.map((l) => ({ key: l.key, y: l.y }))
  const anchor = spotY.value

  if (anchor == null) {
    // No live anchor: a plain top-down greedy spread is enough.
    let prev = -Infinity
    for (const e of [...entries].sort((a, b) => a.y - b.y)) {
      const y = Math.max(e.y, prev + BADGE_MIN_GAP)
      placed.set(e.key, y)
      prev = y
    }
    return placed
  }

  placed.set('spot', anchor)

  // Above the anchor: nearest first, each pushed further up as needed.
  let ceiling = anchor
  for (const e of entries.filter((e) => e.y < anchor).sort((a, b) => b.y - a.y)) {
    const y = Math.min(e.y, ceiling - BADGE_MIN_GAP)
    placed.set(e.key, y)
    ceiling = y
  }

  // Below the anchor: mirror image.
  let floor = anchor
  for (const e of entries.filter((e) => e.y >= anchor).sort((a, b) => a.y - b.y)) {
    const y = Math.max(e.y, floor + BADGE_MIN_GAP)
    placed.set(e.key, y)
    floor = y
  }

  return placed
})

function badgeY(key: string, fallback: number): number {
  return badgeLayout.value.get(key) ?? fallback
}

/* ---- keyboard-focusable strike selection -------------------------------- */
const hoverStrike = ref<number | null>(null)

function selectStrike(strike: number): void {
  emit('update:focusStrike', props.focusStrike === strike ? null : strike)
}

function clearSelection(): void {
  emit('update:focusStrike', null)
}

function onBarKeydown(e: KeyboardEvent, strike: number): void {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    selectStrike(strike)
  } else if (e.key === 'Escape') {
    e.preventDefault()
    clearSelection()
  } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
    e.preventDefault()
    const rows = gexBars.value
    const idx = rows.findIndex((r) => r.strike === strike)
    if (idx === -1) return
    // Screen-down means a lower price (y grows downward); ArrowDown moves
    // to the next-lower strike so the key direction matches what moves.
    const nextIdx =
      e.key === 'ArrowDown' ? Math.min(rows.length - 1, idx + 1) : Math.max(0, idx - 1)
    hoverStrike.value = rows[nextIdx].strike
    if (props.focusStrike != null) emit('update:focusStrike', rows[nextIdx].strike)
  }
}

/* ---- accessibility summary ---------------------------------------------- */
const regimeWord: Record<GammaRegime, string> = {
  short: 'short gamma',
  long: 'long gamma',
  flip: 'straddling the gamma flip',
  unmeasurable: 'not measurable — no open interest',
}

const chartAriaLabel = computed(() => {
  const sym = props.symbol ? `${props.symbol} ` : ''
  const s = props.state
  if (s.regime === 'unmeasurable' || !s.measurable) {
    return `${sym}dealer-gamma regime surface: not measurable, no open interest observed.`
  }
  const spotTxt = s.spot != null ? `spot ${num(s.spot, 2)}` : 'spot unknown'
  const distTxt =
    s.distanceToFlip != null
      ? `${s.distanceToFlip >= 0 ? 'above' : 'below'} the zero-gamma flip by ${num(Math.abs(s.distanceToFlip) * 100, 1)} percent`
      : ''
  const wallsTxt =
    s.callWall != null && s.putWall != null
      ? `Call wall ${num(s.callWall, 2)}, put wall ${num(s.putWall, 2)}.`
      : ''
  return `${sym}dealer-gamma regime: ${regimeWord[s.regime]}. ${spotTxt}${distTxt ? ', ' + distTxt : ''}. ${wallsTxt}`.trim()
})
</script>

<template>
  <div ref="hostRef" class="regime-surface" @keydown.esc="clearSelection">
    <svg :viewBox="`0 0 ${W} ${H}`" :width="W" :height="H" role="img" :aria-label="chartAriaLabel">
      <title>{{ chartAriaLabel }}</title>

      <!-- price gridlines + axis -->
      <g class="grid">
        <line
          v-for="t in priceTicks"
          :key="`grid-${t}`"
          :x1="left"
          :x2="left + innerW"
          :y1="priceScale(t)"
          :y2="priceScale(t)"
          class="gridline"
        />
        <text
          v-for="t in priceTicks"
          :key="`ax-${t}`"
          :x="left - 8"
          :y="priceScale(t) + 3.5"
          text-anchor="end"
          class="axis-label fig"
        >
          {{ num(t, 2) }}
        </text>
      </g>

      <!-- lane frames -->
      <rect :x="gexX0" :y="top" :width="gexLaneW" :height="innerH" class="lane-frame" />
      <rect :x="densityX0" :y="top" :width="densityLaneW" :height="innerH" class="lane-frame" />
      <!-- Captions are left-anchored inside lanes only ~42% / 58% of the plot wide,
           so the full descriptions overran into one another. The lane names stay;
           the qualifiers they lose are already carried by the legend below and by
           the chart aria-label, where they do not compete for horizontal space. -->
      <text :x="gexX0" :y="top - 12" class="lane-cap">GEX BY STRIKE ($M)</text>
      <text :x="densityX0" :y="top - 12" class="lane-cap">DENSITY · TILTED + RAW</text>

      <!-- GEX lane -->
      <g v-if="state.measurable && gexBars.length" clip-path="none">
        <line :x1="zeroX" :x2="zeroX" :y1="top" :y2="top + innerH" class="zero-line" />
        <g
          v-for="bar in gexBars"
          :key="bar.strike"
          class="gex-bar-group"
          tabindex="0"
          role="button"
          :aria-pressed="focusStrike === bar.strike"
          :aria-label="`Strike ${num(bar.strike, 2)}. Call GEX ${optGex(bar.callVal)}. Put GEX ${optGex(bar.putVal)}. Net ${optGex(bar.netVal)}.`"
          @click="selectStrike(bar.strike)"
          @keydown="onBarKeydown($event, bar.strike)"
          @mouseenter="hoverStrike = bar.strike"
          @mouseleave="hoverStrike = null"
        >
          <rect
            class="hit"
            :x="gexX0"
            :y="bar.y - Math.max(gexBarThickness, 12) / 2"
            :width="gexLaneW"
            :height="Math.max(gexBarThickness, 12)"
          />
          <rect
            v-if="bar.callW > 0"
            class="call-bar"
            :class="{ active: focusStrike === bar.strike || hoverStrike === bar.strike }"
            :x="zeroX"
            :y="bar.y - gexBarThickness / 2"
            :width="bar.callW"
            :height="gexBarThickness"
          />
          <rect
            v-if="bar.putW > 0"
            class="put-bar"
            :class="{ active: focusStrike === bar.strike || hoverStrike === bar.strike }"
            :x="zeroX - bar.putW"
            :y="bar.y - gexBarThickness / 2"
            :width="bar.putW"
            :height="gexBarThickness"
          />
        </g>
      </g>
      <g v-else-if="!state.measurable">
        <text
          :x="gexX0 + gexLaneW / 2"
          :y="top + innerH / 2"
          text-anchor="middle"
          class="empty-note"
        >
          GEX NOT MEASURABLE
        </text>
        <text
          :x="gexX0 + gexLaneW / 2"
          :y="top + innerH / 2 + 16"
          text-anchor="middle"
          class="empty-note-sub"
        >
          no open interest observed
        </text>
      </g>
      <g v-else>
        <text
          :x="gexX0 + gexLaneW / 2"
          :y="top + innerH / 2"
          text-anchor="middle"
          class="empty-note"
        >
          NO STRIKES IN RANGE
        </text>
      </g>

      <!-- density lane -->
      <g v-if="untiltedPath">
        <path :d="untiltedPath" class="untilted-line" />
      </g>
      <g v-if="tiltedPath">
        <path :d="tiltedAreaPath" class="tilted-area" :fill="regimeWash" />
        <path :d="tiltedPath" class="tilted-line" :stroke="regimeTone" />
      </g>
      <g v-else-if="!densityReliable">
        <!-- The rail withholds the probabilities for the same reason; drawing
             the curves anyway would be asserting the broken shape visually. -->
        <text
          :x="densityX0 + densityLaneW / 2"
          :y="top + innerH / 2 - 8"
          text-anchor="middle"
          class="empty-note"
        >
          DENSITY WITHHELD
        </text>
        <text
          :x="densityX0 + densityLaneW / 2"
          :y="top + innerH / 2 + 10"
          text-anchor="middle"
          class="empty-note-sub"
        >
          noisy smile at the money
        </text>
      </g>
      <g v-else-if="!untiltedPath">
        <text
          :x="densityX0 + densityLaneW / 2"
          :y="top + innerH / 2"
          text-anchor="middle"
          class="empty-note"
        >
          NO DENSITY AVAILABLE
        </text>
      </g>

      <!-- structural level rules, full width -->
      <g v-for="lvl in levels" :key="lvl.key" class="level-line">
        <line
          :x1="left"
          :x2="left + innerW"
          :y1="lvl.y"
          :y2="lvl.y"
          :stroke="lvl.colorVar"
          :stroke-dasharray="lvl.dash"
        />
        <!-- Leader: the badge may sit off its line after de-collision, so a
             hairline ties the label back to the price it actually marks. -->
        <line
          v-if="Math.abs(badgeY(lvl.key, lvl.y) - lvl.y) > 1"
          :x1="left + innerW"
          :x2="left + innerW + 4"
          :y1="lvl.y"
          :y2="badgeY(lvl.key, lvl.y)"
          :stroke="lvl.colorVar"
          class="badge-leader"
        />
        <rect
          :x="left + innerW + 4"
          :y="badgeY(lvl.key, lvl.y) - 8"
          width="98"
          height="16"
          rx="2"
          class="level-badge-bg"
        />
        <text
          :x="left + innerW + 8"
          :y="badgeY(lvl.key, lvl.y) + 3.5"
          class="level-badge-text fig"
          :fill="lvl.colorVar"
        >
          {{ lvl.shortLabel }} {{ num(lvl.value, 2) }}
        </text>
      </g>

      <!-- live spot marker — moves on the fast clock, independent of the
           GEX bars and density curves which only change on the slow one -->
      <g v-if="spotY != null" class="spot-marker">
        <line :x1="left" :x2="left + innerW" :y1="spotY" :y2="spotY" class="spot-line" />
        <rect
          :x="left + innerW + 4"
          :y="spotY - 9"
          width="98"
          height="18"
          rx="2"
          class="spot-badge-bg"
        />
        <text :x="left + innerW + 8" :y="spotY + 4" class="spot-badge-text fig">
          SPOT {{ num(state.spot, 2) }}
        </text>
      </g>
    </svg>

    <!-- Accessible data-table alternative to the SVG -->
    <table class="visually-hidden">
      <caption>
        {{
          chartAriaLabel
        }}
      </caption>
      <thead>
        <tr>
          <th scope="col">Strike</th>
          <th scope="col">Call GEX ($M)</th>
          <th scope="col">Put GEX ($M)</th>
          <th scope="col">Net GEX ($M)</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in visibleRows" :key="row.strike">
          <td>{{ num(row.strike, 2) }}</td>
          <td>{{ optGex(row.call_gex_m) }}</td>
          <td>{{ optGex(row.put_gex_m) }}</td>
          <td>{{ optGex(row.net_gex_m) }}</td>
        </tr>
      </tbody>
      <tfoot>
        <tr>
          <td>Zero-gamma flip</td>
          <td colspan="3">{{ state.zeroGamma != null ? num(state.zeroGamma, 2) : DASH }}</td>
        </tr>
        <tr>
          <td>Call wall</td>
          <td colspan="3">{{ state.callWall != null ? num(state.callWall, 2) : DASH }}</td>
        </tr>
        <tr>
          <td>Put wall</td>
          <td colspan="3">{{ state.putWall != null ? num(state.putWall, 2) : DASH }}</td>
        </tr>
        <tr>
          <td>Pin strike</td>
          <td colspan="3">{{ state.pinStrike != null ? num(state.pinStrike, 2) : DASH }}</td>
        </tr>
        <tr>
          <td>Live spot</td>
          <td colspan="3">{{ state.spot != null ? num(state.spot, 2) : DASH }}</td>
        </tr>
      </tfoot>
    </table>
  </div>
</template>

<style scoped>
.regime-surface {
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 320px;
  display: flex;
  flex-direction: column;
}

svg {
  display: block;
  width: 100%;
  height: 100%;
  background: var(--surface-base);
}

.gridline {
  stroke: var(--rule);
  stroke-width: 1;
  opacity: 0.5;
}

.axis-label {
  fill: var(--ink-faint);
  font-size: var(--t-micro);
}

.lane-frame {
  fill: none;
  stroke: var(--rule-hi);
  stroke-width: 1;
}

.badge-leader {
  stroke-width: 1;
  opacity: 0.55;
}

.lane-cap {
  fill: var(--ink-dim);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.06em;
}

.zero-line {
  stroke: var(--rule-hi);
  stroke-width: 1;
}

.gex-bar-group {
  cursor: pointer;
}

.gex-bar-group .hit {
  fill: transparent;
}

.gex-bar-group:hover .call-bar,
.gex-bar-group:hover .put-bar,
.call-bar.active,
.put-bar.active {
  opacity: 1;
}

.call-bar {
  fill: var(--call);
  opacity: 0.82;
}

.put-bar {
  fill: var(--put);
  opacity: 0.82;
}

.empty-note {
  fill: var(--ink-dim);
  font-family: var(--font-display);
  font-size: var(--t-small);
  font-weight: 700;
  letter-spacing: 0.06em;
}

.empty-note-sub {
  fill: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: 0.04em;
}

.untilted-line {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1.25;
  stroke-dasharray: 3 3;
}

.tilted-area {
  stroke: none;
}

.tilted-line {
  fill: none;
  stroke-width: 2;
}

.level-line line {
  stroke-width: 1;
}

.level-badge-bg {
  fill: var(--panel);
  stroke: var(--rule);
  stroke-width: 1;
}

.level-badge-text {
  font-size: var(--t-micro);
  letter-spacing: 0.02em;
}

.spot-line {
  stroke: var(--phosphor);
  stroke-width: 1.75;
}

.spot-badge-bg {
  fill: var(--phosphor-wash);
  stroke: var(--phosphor);
  stroke-width: 1;
}

.spot-badge-text {
  fill: var(--phosphor);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.02em;
}

/* Standard visually-hidden pattern: present to assistive tech, invisible
   and non-disruptive to sighted layout. */
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (prefers-reduced-motion: reduce) {
  .regime-surface * {
    transition: none !important;
  }
}
</style>
