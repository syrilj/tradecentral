<script setup lang="ts">
/**
 * Dealer gamma map — net dealer GEX revalued across spot, with the per-strike
 * gamma ladder beneath it on the same price axis.
 *
 * WHY THIS EXISTS
 * The server has been computing both of these on every 30s poll and shipping
 * them in the microstructure payload (`gex_profile`, `strikes`). The page named
 * "dealer gamma regime" used to display the regime's *conclusions* — a flip
 * price, a wall price, a verdict sentence — with no way to see the surface they
 * were read off. That is the one view where "trust me" is least acceptable: the
 * flip is a root of this curve, and whether it is a clean single crossing or one
 * of several shallow ones is the difference between a level worth a stop and a
 * coin flip.
 *
 * WHAT THE TWO LANES SHOW
 *   · curve (top) — net dealer gamma ($M per 1% move) if spot were at each
 *     price on the x-axis. Where it crosses zero is the flip. Its SLOPE at
 *     live spot is what actually matters intraday: steep means the hedging
 *     regime changes fast for a small move, flat means it is stable.
 *   · ladder (bottom) — call gamma up, put gamma down, per strike, so the
 *     concentrations that produce the curve's shape are visible as the
 *     open interest they actually are.
 *
 * READING ORDER
 * The levels are ranked, not just drawn. A chart that plots the flip, both
 * walls and the pin as four equal dashed lines makes the operator do the
 * arithmetic of "which one do I care about first" in their head every time they
 * look at it. `rankedLevels` scores each by structural weight over distance
 * from spot; the chart renders rank 1 at full strength and mutes the rest, and
 * the same ranking is spelled out as a list underneath.
 *
 * Everything is withheld when `quality.measurable` is false — see the note in
 * the template. A blank map is a correct map when there is no chain.
 */
import { computed, ref } from 'vue'
import type { GexProfilePoint, StrikeExposure, ChainQuality } from '@/microstructureContracts'
import type { GammaRegime } from '@/regimeContracts'
import { linearScale, niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'
import { DASH, num, optGex } from '@/format'

const props = withDefaults(
  defineProps<{
    profile: GexProfilePoint[]
    strikes: StrikeExposure[]
    quality: ChainQuality | null
    /** Live spot from the fast clock, so the marker moves between chain refreshes. */
    spot?: number | null
    zeroGamma?: number | null
    callWall?: number | null
    putWall?: number | null
    pinStrike?: number | null
    /**
     * The page's canonical regime call. The map used to classify on the bare
     * sign of net gamma at spot, which contradicted the briefing whenever spot
     * sat inside the neutral band around the flip — the map read "SHORT GAMMA"
     * while the verdict above it read "undecided", off the same two numbers.
     * The sign is still the fallback when no canonical call is supplied.
     */
    regime?: GammaRegime | null
  }>(),
  {
    spot: null,
    zeroGamma: null,
    callWall: null,
    putWall: null,
    pinStrike: null,
    regime: null,
  },
)

const hostRef = ref<HTMLDivElement | null>(null)
/* The frame owns its height in CSS. When the svg was left to size the host,
 * the measured H fed the viewBox and the viewBox fed the height straight back
 * — the box inflated on every observer tick (it was 46,000px tall in the
 * browser). The svg is now pinned inside a fixed frame and cannot drive it. */
const { W, H } = useChartSize(hostRef, { minW: 320, minH: 260, fallbackW: 960, fallbackH: 400 })

const measurable = computed(() => props.quality?.measurable !== false && props.profile.length >= 2)

/* Series toggles are declared before the layout block because the lane
 * geometry below depends on whether the ladder lane is drawn at all. */
const showLadder = ref(true)
const showLevels = ref(true)

/* ---- layout -------------------------------------------------------------
 * Value axis on the right, price axis along the bottom, both lanes sharing the
 * price axis. Lane captions live in HTML chrome above the frame rather than as
 * <text> inside the plot, where they used to collide with the axis labels. */
const padL = 14
const padR = 66
const axisH = 24
const laneGap = 28
/** Height of one row in the level-tag lane above the plot. */
const TAG_H = 16

const innerW = computed(() => Math.max(80, W.value - padL - padR))
/* The top pad is whatever the packed tag lane needs. Tags used to be drawn
 * inside the plot at a fixed y, so two levels a few ticks apart printed on top
 * of each other and neither was readable. */
const padT = computed(() => 8 + (showLevels.value ? tagRows.value : 0) * TAG_H)
const bodyH = computed(() => Math.max(140, H.value - padT.value - axisH))
const curveH = computed(() =>
  showLadder.value ? Math.max(90, Math.round((bodyH.value - laneGap) * 0.62)) : bodyH.value,
)
const ladderH = computed(() =>
  showLadder.value ? Math.max(48, bodyH.value - laneGap - curveH.value) : 0,
)
const curveY0 = computed(() => padT.value)
const curveY1 = computed(() => curveY0.value + curveH.value)
const ladderY0 = computed(() => curveY1.value + laneGap)
const ladderY1 = computed(() => ladderY0.value + ladderH.value)
/** Bottom of whatever is actually drawn — the price axis sits here. */
const plotB = computed(() => (showLadder.value ? ladderY1.value : curveY1.value))
const plotR = computed(() => padL + innerW.value)

/* ---- price window -------------------------------------------------------
 * The raw profile spans the whole quoted strike ladder (routinely +/-20%),
 * which compresses spot, the flip and both walls into a few pixels. The window
 * is operator-selectable, and structural levels always widen it back out to
 * include themselves — a wall 9% away is more decision-relevant than the
 * strikes either side of spot. */
const WINDOWS = [
  { key: '2', label: '±2%', pct: 0.02 },
  { key: '4', label: '±4%', pct: 0.04 },
  { key: '7', label: '±7%', pct: 0.07 },
  { key: 'full', label: 'FULL', pct: null },
] as const

type WindowKey = (typeof WINDOWS)[number]['key']

const windowKey = ref<WindowKey>('4')
const windowPct = computed(() => WINDOWS.find((w) => w.key === windowKey.value)?.pct ?? null)

const priceDomain = computed<[number, number]>(() => {
  const spot = props.spot
  const xs = props.profile.map((p) => p.spot).filter((v) => Number.isFinite(v))
  if (!xs.length) return [0, 1]
  let lo = Math.min(...xs)
  let hi = Math.max(...xs)
  const pct = windowPct.value
  if (pct != null && spot && spot > 0) {
    lo = Math.max(lo, spot * (1 - pct))
    hi = Math.min(hi, spot * (1 + pct))
  }
  for (const v of [props.spot, props.zeroGamma, props.callWall, props.putWall, props.pinStrike]) {
    if (v != null && Number.isFinite(v) && v > 0) {
      lo = Math.min(lo, v)
      hi = Math.max(hi, v)
    }
  }
  if (!(hi > lo)) {
    const mid = lo || 1
    return [mid * 0.98, mid * 1.02]
  }
  const pad = (hi - lo) * 0.035
  return [lo - pad, hi + pad]
})

const xScale = computed(() => linearScale(priceDomain.value, [padL, plotR.value]))

/** Profile points inside the visible window, so the curve is not drawn (and
 *  its extent not measured) outside the frame. */
const visibleProfile = computed<GexProfilePoint[]>(() => {
  const [lo, hi] = priceDomain.value
  return props.profile.filter((p) => p.spot >= lo && p.spot <= hi && Number.isFinite(p.net_gex_m))
})

const visibleStrikes = computed<StrikeExposure[]>(() => {
  const [lo, hi] = priceDomain.value
  return props.strikes.filter((r) => r.strike >= lo && r.strike <= hi)
})

/* ---- curve lane ---------------------------------------------------------
 * The zero line must sit where net gamma is actually zero, so the y domain is
 * forced to straddle it. A curve auto-scaled to its own min/max would put the
 * zero line at an arbitrary height, and "which side of zero am I on" is the
 * entire question this lane answers. */
const gexDomain = computed<[number, number]>(() => {
  const ys = visibleProfile.value.map((p) => p.net_gex_m)
  if (!ys.length) return [-1, 1]
  const lo = Math.min(0, ...ys)
  const hi = Math.max(0, ...ys)
  if (lo === hi) return [-1, 1]
  const pad = (hi - lo) * 0.1
  return [lo - pad, hi + pad]
})

/* One unit for the whole rail. `optGex` switches between M and B per value, so
 * a single axis could print "$0.0M" next to "-$4.0B" and silently change scale
 * between two adjacent ticks. The axis picks its unit once, from the domain. */
const axisUnit = computed<'M' | 'B'>(() => {
  const [lo, hi] = gexDomain.value
  return Math.max(Math.abs(lo), Math.abs(hi)) >= 1000 ? 'B' : 'M'
})

function axisGex(v: number, dp?: number): string {
  const unit = axisUnit.value
  const scaled = unit === 'B' ? v / 1000 : v
  const places = dp ?? (unit === 'B' ? 1 : 0)
  return `${scaled < 0 ? '-$' : '$'}${Math.abs(scaled).toFixed(places)}${unit}`
}

const yCurve = computed(() => linearScale(gexDomain.value, [curveY1.value, curveY0.value]))
const zeroY = computed(() => yCurve.value(0))

/** Split into a positive-gamma path and a negative-gamma path so each half can
 *  carry its own color. Split points are interpolated at the axis crossing so
 *  the two halves meet exactly on the zero line instead of overlapping a
 *  segment that spans it. */
type Seg = { sign: 1 | -1; d: string; x0: number; x1: number }

const curveSegments = computed<Seg[]>(() => {
  const pts = visibleProfile.value
  if (pts.length < 2) return []
  const x = xScale.value
  const y = yCurve.value
  const z = zeroY.value
  const runs: { sign: 1 | -1; parts: string[]; x0: number; x1: number }[] = []

  for (let i = 0; i < pts.length; i++) {
    const p = pts[i]
    const sign: 1 | -1 = p.net_gex_m >= 0 ? 1 : -1
    const px = x(p.spot)
    const cur = runs.length ? runs[runs.length - 1] : null

    if (cur === null) {
      runs.push({
        sign,
        parts: [`M ${px.toFixed(2)} ${y(p.net_gex_m).toFixed(2)}`],
        x0: px,
        x1: px,
      })
      continue
    }
    if (cur.sign === sign) {
      cur.parts.push(`L ${px.toFixed(2)} ${y(p.net_gex_m).toFixed(2)}`)
      cur.x1 = px
      continue
    }
    // Crossing: interpolate the exact zero point so both halves terminate on
    // the zero line rather than sharing a segment that spans it.
    const prev = pts[i - 1]
    const span = p.net_gex_m - prev.net_gex_m
    const t = span === 0 ? 0 : (0 - prev.net_gex_m) / span
    const crossX = x(prev.spot + t * (p.spot - prev.spot))
    cur.parts.push(`L ${crossX.toFixed(2)} ${z.toFixed(2)}`)
    cur.x1 = crossX
    runs.push({
      sign,
      parts: [
        `M ${crossX.toFixed(2)} ${z.toFixed(2)}`,
        `L ${px.toFixed(2)} ${y(p.net_gex_m).toFixed(2)}`,
      ],
      x0: crossX,
      x1: px,
    })
  }

  return runs
    .filter((r) => r.parts.length > 1)
    .map((r) => ({ sign: r.sign, d: r.parts.join(' '), x0: r.x0, x1: r.x1 }))
})

/** Filled area under each half, for reading sign at a glance rather than by
 *  tracing the line against the axis. */
const curveAreas = computed(() =>
  curveSegments.value.map((seg) => {
    const z = zeroY.value.toFixed(2)
    return {
      sign: seg.sign,
      d: `${seg.d} L ${seg.x1.toFixed(2)} ${z} L ${seg.x0.toFixed(2)} ${z} Z`,
    }
  }),
)

/* ---- ladder lane --------------------------------------------------------
 * Bars are scaled against the largest single-strike |gamma| in view, so the
 * ladder shows this symbol's own distribution rather than being squashed by a
 * fixed $M constant that only fits one order of magnitude. */
const ladderScaleM = computed(() => {
  let max = 0
  for (const r of visibleStrikes.value) {
    max = Math.max(max, Math.abs(r.call_gex_m), Math.abs(r.put_gex_m))
  }
  return max > 0 ? max : 1
})

const ladderMidY = computed(() => ladderY0.value + ladderH.value / 2)

const barW = computed(() => {
  const n = visibleStrikes.value.length
  if (n < 2) return 8
  return Math.max(1.5, Math.min(13, (innerW.value / n) * 0.66))
})

type Bar = { x: number; y: number; h: number; side: 'call' | 'put'; strike: number }

const bars = computed<Bar[]>(() => {
  if (!showLadder.value) return []
  const x = xScale.value
  const half = ladderH.value / 2
  const scale = ladderScaleM.value
  const out: Bar[] = []
  for (const r of visibleStrikes.value) {
    const cx = x(r.strike)
    const callH = (Math.abs(r.call_gex_m) / scale) * half
    const putH = (Math.abs(r.put_gex_m) / scale) * half
    if (callH >= 0.5) {
      out.push({ x: cx, y: ladderMidY.value - callH, h: callH, side: 'call', strike: r.strike })
    }
    if (putH >= 0.5) {
      out.push({ x: cx, y: ladderMidY.value, h: putH, side: 'put', strike: r.strike })
    }
  }
  return out
})

/* ---- structural levels, ranked -------------------------------------------
 * "Which level matters first" is the question the operator actually has, and
 * four identical dashed lines refuse to answer it. Score = structural weight
 * over distance from spot, so a wall 0.3% away outranks a flip 4% away while a
 * flip and a wall at equal distance still do not tie. */
type Tone = 'flip' | 'call' | 'put' | 'pin'

type Level = {
  key: string
  label: string
  full: string
  price: number
  x: number
  tone: Tone
  distPct: number | null
  above: boolean
  score: number
  rank: number
  meaning: string
}

const LEVEL_WEIGHT: Record<Tone, number> = { flip: 1, call: 0.82, put: 0.82, pin: 0.55 }

const rankedLevels = computed<Level[]>(() => {
  const x = xScale.value
  const [lo, hi] = priceDomain.value
  const spot = props.spot
  const raw: Omit<Level, 'rank'>[] = []

  const push = (
    key: string,
    label: string,
    full: string,
    price: number | null | undefined,
    tone: Tone,
    meaning: string,
  ) => {
    if (price == null || !Number.isFinite(price) || price < lo || price > hi) return
    const distPct = spot && spot > 0 ? (price - spot) / spot : null
    const mag = distPct == null ? 0.01 : Math.max(0.0008, Math.abs(distPct))
    raw.push({
      key,
      label,
      full,
      price,
      x: x(price),
      tone,
      distPct,
      above: distPct == null ? false : distPct >= 0,
      score: LEVEL_WEIGHT[tone] / mag,
      meaning,
    })
  }

  push(
    'flip',
    'FLIP',
    'Zero gamma',
    props.zeroGamma,
    'flip',
    'hedging flips sign — the vol regime changes here',
  )
  push(
    'call',
    'CALL WALL',
    'Call wall',
    props.callWall,
    'call',
    'dealer supply builds — upside drag',
  )
  push(
    'put',
    'PUT WALL',
    'Put wall',
    props.putWall,
    'put',
    'dealer demand builds — downside cushion',
  )
  push(
    'pin',
    'PIN',
    'Pin strike',
    props.pinStrike,
    'pin',
    'largest gamma concentration — magnet into the close',
  )

  return raw.sort((a, b) => b.score - a.score).map((lv, i) => ({ ...lv, rank: i + 1 }))
})

/** Pixel width of a level tag, from its label length. */
function tagW(label: string): number {
  return label.length * 6.1 + 22
}

/* Tag packing: rank order first, so rank 1 always lands on the row closest to
 * the plot, then greedily into the lowest row it fits without touching a tag
 * already placed there. */
type TaggedLevel = { lv: Level; row: number; w: number }

const taggedLevels = computed<TaggedLevel[]>(() => {
  const rows: { s: number; e: number }[][] = []
  const out: TaggedLevel[] = []
  for (const lv of rankedLevels.value) {
    const w = tagW(lv.label)
    const s = lv.x + 3
    const e = s + w + 5
    let row = 0
    while (rows[row]?.some((iv) => s < iv.e && e > iv.s)) row++
    ;(rows[row] ??= []).push({ s, e })
    out.push({ lv, row, w })
  }
  return out
})

const tagRows = computed(() =>
  taggedLevels.value.length ? Math.max(...taggedLevels.value.map((t) => t.row + 1)) : 0,
)

/** Row 0 sits directly on top of the plot; each further row stacks above it. */
function tagY(row: number): number {
  return curveY0.value - (row + 1) * TAG_H + 1
}

const spotX = computed(() => {
  const s = props.spot
  const [lo, hi] = priceDomain.value
  if (s == null || !Number.isFinite(s) || s < lo || s > hi) return null
  return xScale.value(s)
})

const xTicks = computed(() => {
  const [lo, hi] = priceDomain.value
  const count = innerW.value > 720 ? 8 : innerW.value > 460 ? 6 : 4
  return niceTicks(lo, hi, count)
    .filter((t) => t >= lo && t <= hi)
    .map((t) => ({ v: t, x: xScale.value(t) }))
})

const yTicks = computed(() => {
  const [lo, hi] = gexDomain.value
  return niceTicks(lo, hi, 5)
    .filter((t) => t >= lo && t <= hi)
    .map((t) => ({ v: t, y: yCurve.value(t) }))
})

/* ---- crosshair ----------------------------------------------------------
 * Snapped to the nearest profile sample on x so the readout is a real measured
 * point, free on y so the value pill reads the axis the pointer is actually
 * over — the convention every trading chart uses. */
const cursor = ref<{ x: number; y: number } | null>(null)

const hovered = computed(() => {
  const c = cursor.value
  if (!c || !visibleProfile.value.length) return null
  const price = xScale.value.invert(c.x)
  let best = visibleProfile.value[0]
  for (const p of visibleProfile.value) {
    if (Math.abs(p.spot - price) < Math.abs(best.spot - price)) best = p
  }
  const strike = visibleStrikes.value.length
    ? visibleStrikes.value.reduce((a, b) =>
        Math.abs(b.strike - price) < Math.abs(a.strike - price) ? b : a,
      )
    : null
  const distPct = props.spot && props.spot > 0 ? (best.spot - props.spot) / props.spot : null
  return {
    point: best,
    strike,
    x: xScale.value(best.spot),
    y: yCurve.value(best.net_gex_m),
    distPct,
  }
})

/* Hovering a row in the priority list lights that level up on the chart. The
 * ranking and the rule are the same fact; without the link the operator has to
 * find "rank 3" among four dashed lines by eye. */
const focusKey = ref<string | null>(null)

/** Value under the pointer on the curve axis — the pill on the right rail. */
const cursorValue = computed(() => {
  const c = cursor.value
  if (!c || c.y < curveY0.value || c.y > curveY1.value) return null
  return yCurve.value.invert(c.y)
})

/** The tooltip flips to the left of the crosshair past mid-frame so it never
 *  runs off the right rail. */
const tipStyle = computed(() => {
  const h = hovered.value
  if (!h) return {}
  const flip = h.x > padL + innerW.value * 0.6
  return {
    left: `${((flip ? h.x - 14 : h.x + 14) / Math.max(1, W.value)) * 100}%`,
    top: `${padT.value + 6}px`,
    transform: flip ? 'translateX(-100%)' : 'none',
  }
})

function onMove(e: MouseEvent) {
  const host = hostRef.value
  if (!host) return
  const box = host.getBoundingClientRect()
  const sx = W.value / Math.max(1, box.width)
  const sy = H.value / Math.max(1, box.height)
  const px = (e.clientX - box.left) * sx
  const py = (e.clientY - box.top) * sy
  cursor.value =
    px >= padL && px <= plotR.value && py >= curveY0.value && py <= plotB.value
      ? { x: px, y: py }
      : null
}

/** Net gamma at live spot, read off the same curve the chart draws — the
 *  headline this map is the evidence for. */
const netAtSpot = computed<number | null>(() => {
  const s = props.spot
  const pts = props.profile
  if (s == null || pts.length < 2) return null
  const sorted = [...pts].sort((a, b) => a.spot - b.spot)
  if (s <= sorted[0].spot) return sorted[0].net_gex_m
  if (s >= sorted[sorted.length - 1].spot) return sorted[sorted.length - 1].net_gex_m
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i].spot >= s) {
      const a = sorted[i - 1]
      const b = sorted[i]
      const dx = b.spot - a.spot
      if (dx === 0) return a.net_gex_m
      return a.net_gex_m + ((s - a.spot) / dx) * (b.net_gex_m - a.net_gex_m)
    }
  }
  return null
})

const regimeWord = computed(() => {
  switch (props.regime) {
    case 'short':
      return 'SHORT GAMMA'
    case 'long':
      return 'LONG GAMMA'
    case 'flip':
      return 'AT THE FLIP'
    case 'unmeasurable':
      return DASH
  }
  const v = netAtSpot.value
  if (v == null) return DASH
  return v < 0 ? 'SHORT GAMMA' : 'LONG GAMMA'
})

/** Tone follows the regime call, not the raw sign, so a reading inside the
 *  neutral band is not painted bearish by a marginally negative number. */
const regimeTone = computed(() => {
  if (props.regime === 'flip') return 'flip'
  if (props.regime === 'long') return 'pos'
  if (props.regime === 'short') return 'neg'
  if (props.regime === 'unmeasurable') return ''
  const v = netAtSpot.value
  if (v == null) return ''
  return v < 0 ? 'neg' : 'pos'
})

function signedPctLabel(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return DASH
  const p = v * 100
  return `${p >= 0 ? '+' : ''}${p.toFixed(2)}%`
}
</script>

<template>
  <div class="gamma-map">
    <!-- No chain, no map. Rendering an empty grid with axes would read as
         "flat gamma" rather than "nothing measured", which is the exact
         confusion this whole surface was rebuilt to remove. -->
    <p v-if="!measurable" class="withheld label wraps" role="status">
      No dealer gamma surface to map:
      {{ quality?.reason ?? 'waiting for the first chain read' }}. Nothing is plotted rather than
      plotting a flat line that would read as balanced gamma.
    </p>

    <template v-else>
      <!-- chart toolbar ------------------------------------------------- -->
      <div class="tv-toolbar">
        <div class="tb-series">
          <span class="tb-title">NET DEALER γ · ${{ axisUnit }} / 1% MOVE</span>
          <span class="tb-key"><i class="sw sw-long" />long γ</span>
          <span class="tb-key"><i class="sw sw-short" />short γ</span>
          <span class="tb-key"><i class="sw sw-spot" />spot</span>
        </div>
        <div class="tb-controls">
          <div class="seg" role="group" aria-label="Price window">
            <button
              v-for="w in WINDOWS"
              :key="w.key"
              type="button"
              class="seg-btn"
              :class="{ on: windowKey === w.key }"
              :aria-pressed="windowKey === w.key"
              @click="windowKey = w.key"
            >
              {{ w.label }}
            </button>
          </div>
          <button
            type="button"
            class="toggle"
            :class="{ on: showLadder }"
            :aria-pressed="showLadder"
            @click="showLadder = !showLadder"
          >
            LADDER
          </button>
          <button
            type="button"
            class="toggle"
            :class="{ on: showLevels }"
            :aria-pressed="showLevels"
            @click="showLevels = !showLevels"
          >
            LEVELS
          </button>
        </div>
      </div>

      <!-- plot ----------------------------------------------------------- -->
      <div
        ref="hostRef"
        class="tv-frame"
        :class="{ 'no-ladder': !showLadder }"
        @pointermove="onMove"
        @mousemove="onMove"
        @pointerleave="cursor = null"
        @mouseleave="cursor = null"
      >
        <svg
          class="map-svg"
          :viewBox="`0 0 ${W} ${H}`"
          preserveAspectRatio="none"
          role="img"
          aria-label="Net dealer gamma exposure across spot price, with per-strike gamma ladder"
        >
          <defs>
            <linearGradient id="dgm-long" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="var(--call)" stop-opacity="0.36" />
              <stop offset="100%" stop-color="var(--call)" stop-opacity="0.02" />
            </linearGradient>
            <linearGradient id="dgm-short" x1="0" y1="1" x2="0" y2="0">
              <stop offset="0%" stop-color="var(--put)" stop-opacity="0.36" />
              <stop offset="100%" stop-color="var(--put)" stop-opacity="0.02" />
            </linearGradient>
            <clipPath id="dgm-curve-clip">
              <rect :x="padL" :y="curveY0 - 2" :width="innerW" :height="curveH + 4" />
            </clipPath>
          </defs>

          <!-- grid -->
          <g class="grid">
            <line
              v-for="t in yTicks"
              :key="`gy-${t.v}`"
              :x1="padL"
              :x2="plotR"
              :y1="t.y"
              :y2="t.y"
            />
            <line
              v-for="t in xTicks"
              :key="`gx-${t.v}`"
              :x1="t.x"
              :x2="t.x"
              :y1="curveY0"
              :y2="plotB"
            />
          </g>

          <!-- curve lane -->
          <g clip-path="url(#dgm-curve-clip)">
            <path
              v-for="(a, i) in curveAreas"
              :key="`area-${i}`"
              class="curve-area"
              :fill="a.sign > 0 ? 'url(#dgm-long)' : 'url(#dgm-short)'"
              :d="a.d"
            />
            <path
              v-for="(seg, i) in curveSegments"
              :key="`seg-${i}`"
              :class="['curve-line', seg.sign > 0 ? 'is-long' : 'is-short']"
              :d="seg.d"
            />
          </g>
          <line class="zero-line" :x1="padL" :x2="plotR" :y1="zeroY" :y2="zeroY" />

          <!-- ladder lane -->
          <g v-if="showLadder">
            <line class="ladder-axis" :x1="padL" :x2="plotR" :y1="ladderMidY" :y2="ladderMidY" />
            <rect
              v-for="(b, i) in bars"
              :key="`bar-${i}`"
              :class="[
                'gex-bar',
                b.side === 'call' ? 'is-call' : 'is-put',
                hovered && hovered.strike && hovered.strike.strike === b.strike ? 'is-hot' : '',
              ]"
              :x="b.x - barW / 2"
              :y="b.y"
              :width="barW"
              :height="Math.max(0.6, b.h)"
            />
          </g>

          <!-- structural levels, ranked: rank 1 reads first --------------- -->
          <g v-if="showLevels">
            <g
              v-for="t in taggedLevels"
              :key="t.lv.key"
              :class="[
                'level',
                `tone-${t.lv.tone}`,
                `rank-${t.lv.rank}`,
                focusKey === t.lv.key ? 'is-focus' : '',
                focusKey && focusKey !== t.lv.key ? 'is-muted' : '',
              ]"
            >
              <line
                class="level-line"
                :x1="t.lv.x"
                :x2="t.lv.x"
                :y1="tagY(t.row) + 15"
                :y2="plotB"
              />
              <g :transform="`translate(${t.lv.x}, ${tagY(t.row)})`">
                <rect class="level-tag" x="3" y="0" :width="t.w" height="15" rx="2" />
                <text class="level-rank" x="10" y="11">{{ t.lv.rank }}</text>
                <text class="level-tag-text" x="19" y="11">{{ t.lv.label }}</text>
              </g>
            </g>
          </g>

          <!-- live spot: solid, and the only marker on the fast clock -->
          <g v-if="spotX != null">
            <line class="spot-line" :x1="spotX" :x2="spotX" :y1="curveY0" :y2="plotB" />
            <circle
              v-if="netAtSpot != null"
              class="spot-dot"
              :cx="spotX"
              :cy="yCurve(netAtSpot)"
              r="3.5"
            />
          </g>

          <!-- crosshair -->
          <g v-if="hovered && cursor" class="crosshair">
            <line :x1="hovered.x" :x2="hovered.x" :y1="curveY0" :y2="plotB" />
            <line v-if="cursorValue != null" :x1="padL" :x2="plotR" :y1="cursor.y" :y2="cursor.y" />
            <circle class="probe" :cx="hovered.x" :cy="hovered.y" r="3" />
          </g>

          <!-- right value rail -->
          <line class="rail" :x1="plotR" :x2="plotR" :y1="curveY0" :y2="plotB" />
          <text
            v-for="t in yTicks"
            :key="`yl-${t.v}`"
            class="axis-label"
            :x="plotR + 7"
            :y="t.y + 3.5"
            text-anchor="start"
          >
            {{ axisGex(t.v) }}
          </text>
          <g v-if="cursorValue != null && cursor" class="pill pill-y">
            <rect :x="plotR + 2" :y="cursor.y - 8" :width="padR - 8" height="16" rx="2" />
            <text :x="plotR + 7" :y="cursor.y + 3.5">{{ axisGex(cursorValue, 1) }}</text>
          </g>

          <!-- price axis -->
          <line class="axis-rule" :x1="padL" :x2="plotR" :y1="plotB" :y2="plotB" />
          <text
            v-for="t in xTicks"
            :key="`xt-${t.v}`"
            class="axis-label"
            :x="t.x"
            :y="plotB + 15"
            text-anchor="middle"
          >
            {{ num(t.v, 0) }}
          </text>
          <g v-if="spotX != null" class="pill pill-spot">
            <rect :x="spotX - 27" :y="plotB + 3" width="54" height="16" rx="2" />
            <text :x="spotX" :y="plotB + 14.5" text-anchor="middle">{{ num(spot, 2) }}</text>
          </g>
          <g v-if="hovered" class="pill pill-x">
            <rect :x="hovered.x - 27" :y="plotB + 3" width="54" height="16" rx="2" />
            <text :x="hovered.x" :y="plotB + 14.5" text-anchor="middle">
              {{ num(hovered.point.spot, 2) }}
            </text>
          </g>
        </svg>

        <!-- the ladder caption sits in chrome, not in the plot, so it can never
             collide with the axis labels the way the old <text> one did -->
        <span v-if="showLadder" class="lane-cap cap-ladder">γ BY STRIKE · CALLS ↑ / PUTS ↓</span>

        <!-- crosshair tooltip -->
        <div v-if="hovered" class="tv-tip font-mono" :style="tipStyle">
          <div class="tip-head">{{ num(hovered.point.spot, 2) }}</div>
          <div class="tip-row">
            <span>net γ</span>
            <b :class="hovered.point.net_gex_m < 0 ? 'neg' : 'pos'">
              {{ optGex(hovered.point.net_gex_m) }}
            </b>
          </div>
          <div class="tip-row">
            <span>from spot</span><b>{{ signedPctLabel(hovered.distPct) }}</b>
          </div>
          <template v-if="hovered.strike">
            <div class="tip-sep" />
            <div class="tip-row">
              <span>K {{ num(hovered.strike.strike, 2) }}</span>
              <b>{{ hovered.strike.call_oi }}c / {{ hovered.strike.put_oi }}p</b>
            </div>
            <div class="tip-row">
              <span>call γ</span><b class="pos">{{ optGex(hovered.strike.call_gex_m) }}</b>
            </div>
            <div class="tip-row">
              <span>put γ</span><b class="neg">{{ optGex(hovered.strike.put_gex_m) }}</b>
            </div>
          </template>
        </div>
      </div>

      <!-- level priority: the ranking the chart draws, spelled out -------- -->
      <div v-if="rankedLevels.length" class="prio">
        <span class="prio-cap label">Levels by priority</span>
        <ol class="prio-list">
          <li
            v-for="lv in rankedLevels"
            :key="lv.key"
            :class="['prio-item', `tone-${lv.tone}`, { on: focusKey === lv.key }]"
            @mouseenter="focusKey = lv.key"
            @mouseleave="focusKey = null"
          >
            <span class="prio-rank">{{ lv.rank }}</span>
            <span class="prio-name">{{ lv.full }}</span>
            <span class="prio-px font-mono">{{ num(lv.price, 2) }}</span>
            <span class="prio-dist font-mono" :class="lv.above ? 'up' : 'dn'">
              {{ lv.above ? '▲' : '▼' }} {{ signedPctLabel(lv.distPct) }}
            </span>
            <span class="prio-why">{{ lv.meaning }}</span>
          </li>
        </ol>
      </div>

      <!-- readout: the numbers the map is evidence for -->
      <div class="map-readout font-mono">
        <span class="ro">
          <em>regime</em>
          <b :class="regimeTone">{{ regimeWord }}</b>
        </span>
        <span class="ro">
          <em>net γ at spot</em>
          <b :class="netAtSpot == null ? '' : netAtSpot < 0 ? 'neg' : 'pos'">
            {{ netAtSpot != null ? optGex(netAtSpot) : DASH }}
          </b>
        </span>
        <span class="ro">
          <em>flip</em><b>{{ zeroGamma != null ? num(zeroGamma, 2) : 'none in range' }}</b>
        </span>
        <span class="ro">
          <em>strikes in view</em><b>{{ visibleStrikes.length }}</b>
        </span>
        <span v-if="quality && quality.iv_fallback_contracts > 0" class="ro warn-note">
          <em>{{ quality.iv_fallback_contracts }} strike-sides on default IV</em>
        </span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.gamma-map {
  position: relative;
  width: 100%;
  background: var(--surface-base);
}

.withheld {
  padding: var(--s4);
  color: var(--ink-dim);
  max-width: 60ch;
}

/* ---- toolbar ------------------------------------------------------------ */
.tv-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  flex-wrap: wrap;
  padding: var(--s2) var(--s3);
  border-bottom: 1px solid var(--rule-faint);
}

.tb-series {
  display: flex;
  align-items: center;
  gap: var(--s3);
}

.tb-title {
  font-family: var(--font-data);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: var(--ink-soft);
  padding-right: var(--s1);
}

.tb-key {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-data);
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-faint);
}

.sw {
  width: 12px;
  height: 2px;
  border-radius: 1px;
}
.sw-long {
  background: var(--call-hi);
}
.sw-short {
  background: var(--put-hi);
}
.sw-spot {
  background: var(--phosphor);
}

.tb-controls {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.seg {
  display: inline-flex;
  border: 1px solid var(--rule);
  border-radius: 3px;
  overflow: hidden;
}

.seg-btn,
.toggle {
  font-family: var(--font-data);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
  background: transparent;
  border: 0;
  padding: 4px 9px;
  cursor: pointer;
  transition:
    color 0.12s ease,
    background 0.12s ease;
}

.seg-btn + .seg-btn {
  border-left: 1px solid var(--rule);
}

.seg-btn:hover,
.toggle:hover {
  color: var(--ink-soft);
  background: rgba(255, 255, 255, 0.04);
}

.seg-btn.on {
  color: var(--void);
  background: var(--phosphor);
}

.toggle {
  border: 1px solid var(--rule);
  border-radius: 3px;
}

.toggle.on {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

/* ---- plot frame ---------------------------------------------------------
 * The frame owns its height. The svg is pinned inside it and stretched with
 * preserveAspectRatio="none", so the viewBox can never feed back into layout. */
.tv-frame {
  position: relative;
  width: 100%;
  height: clamp(340px, 42vh, 470px);
  background: var(--void);
  cursor: crosshair;
  touch-action: none;
  overflow: hidden;
}

.tv-frame.no-ladder {
  height: clamp(250px, 30vh, 340px);
}

.map-svg {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
}

.lane-cap {
  position: absolute;
  right: 74px;
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--ink-faint);
  pointer-events: none;
}

.cap-ladder {
  bottom: 30px;
}

/* ---- plot marks --------------------------------------------------------- */
.grid line {
  stroke: var(--wash-line);
  stroke-width: 1;
  shape-rendering: crispEdges;
}

.curve-line {
  fill: none;
  stroke-width: 1.75;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.curve-line.is-long {
  stroke: var(--call-hi);
}
.curve-line.is-short {
  stroke: var(--put-hi);
}

.zero-line {
  stroke: rgba(255, 255, 255, 0.32);
  stroke-width: 1;
  stroke-dasharray: 3 3;
  shape-rendering: crispEdges;
}

.ladder-axis,
.axis-rule,
.rail {
  stroke: var(--rule);
  stroke-width: 1;
  shape-rendering: crispEdges;
}

.gex-bar {
  transition: opacity 0.1s ease;
}
.gex-bar.is-call {
  fill: var(--call);
  opacity: 0.6;
}
.gex-bar.is-put {
  fill: var(--put);
  opacity: 0.6;
}
.gex-bar.is-hot {
  opacity: 1;
}

.axis-label {
  font-family: var(--font-data);
  font-size: 10px;
  fill: var(--ink-faint);
  letter-spacing: 0.02em;
}

/* ---- levels: rank drives visual weight ---------------------------------- */
.level-line {
  stroke-width: 1;
  stroke-dasharray: 4 4;
}

.level-tag {
  stroke-width: 1;
}

.level-rank,
.level-tag-text {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 800;
  letter-spacing: 0.07em;
}

.level .level-tag-text {
  fill: var(--ink);
}

.tone-flip .level-line,
.tone-flip .level-tag {
  stroke: var(--warn);
}
.tone-flip .level-tag {
  fill: color-mix(in srgb, var(--warn) 20%, var(--void));
}
.tone-flip .level-rank {
  fill: var(--warn);
}

.tone-call .level-line,
.tone-call .level-tag {
  stroke: var(--call);
}
.tone-call .level-tag {
  fill: color-mix(in srgb, var(--call) 20%, var(--void));
}
.tone-call .level-rank {
  fill: var(--call-hi);
}

.tone-put .level-line,
.tone-put .level-tag {
  stroke: var(--put);
}
.tone-put .level-tag {
  fill: color-mix(in srgb, var(--put) 20%, var(--void));
}
.tone-put .level-rank {
  fill: var(--put-hi);
}

.tone-pin .level-line,
.tone-pin .level-tag {
  stroke: var(--ink-ghost);
}
.tone-pin .level-tag {
  fill: var(--wash-3);
}
.tone-pin .level-rank {
  fill: var(--ink-dim);
}

/* Rank 1 reads first; each step down loses weight. This is the whole point of
   ranking them — an equal-weight chart makes the operator do the sort. */
.level.rank-1 {
  opacity: 1;
}
.level.rank-1 .level-line {
  stroke-width: 1.5;
  stroke-dasharray: 6 3;
}
.level.rank-2 {
  opacity: 0.76;
}
.level.rank-3 {
  opacity: 0.54;
}
.level.rank-4 {
  opacity: 0.4;
}

.level {
  transition: opacity 0.12s ease;
}

.level.is-focus {
  opacity: 1;
}

.level.is-focus .level-line {
  stroke-width: 2;
  stroke-dasharray: none;
}

.level.is-muted {
  opacity: 0.18;
}

.spot-line {
  stroke: var(--phosphor);
  stroke-width: 1.25;
  shape-rendering: crispEdges;
}

.spot-dot {
  fill: var(--phosphor);
  stroke: var(--void);
  stroke-width: 1.5;
}

.crosshair line {
  stroke: rgba(255, 255, 255, 0.28);
  stroke-width: 1;
  stroke-dasharray: 2 3;
  shape-rendering: crispEdges;
}

.crosshair .probe {
  fill: var(--ink);
  stroke: var(--void);
  stroke-width: 1.5;
  stroke-dasharray: none;
}

.pill rect {
  fill: var(--panel-raise);
  stroke: var(--rule-hi);
  stroke-width: 1;
}

.pill text {
  font-family: var(--font-data);
  font-size: 10px;
  font-weight: 700;
  fill: var(--ink);
}

.pill-spot rect {
  fill: var(--phosphor);
  stroke: none;
}
.pill-spot text {
  fill: var(--void);
}

/* ---- tooltip ------------------------------------------------------------ */
.tv-tip {
  position: absolute;
  top: 30px; /* overridden inline so the tip always clears the tag lane */
  min-width: 150px;
  padding: 7px 9px;
  background: var(--glass-overlay);
  backdrop-filter: var(--glass-blur-sm);
  border: 1px solid var(--glass-border);
  border-radius: 4px;
  box-shadow: var(--glass-shadow-md);
  pointer-events: none;
  font-size: 10.5px;
  z-index: 2;
}

.tip-head {
  font-weight: 800;
  font-size: 12px;
  color: var(--ink);
  margin-bottom: 4px;
}

.tip-row {
  display: flex;
  justify-content: space-between;
  gap: var(--s3);
  line-height: 1.55;
}

.tip-row span {
  color: var(--ink-faint);
}

.tip-row b {
  color: var(--ink-soft);
  font-weight: 700;
}

.tip-sep {
  height: 1px;
  background: var(--rule);
  margin: 5px 0;
}

.pos {
  color: var(--call-hi);
}
.neg {
  color: var(--put-hi);
}
/* Inside the neutral band the regime has no side, so it gets neither
   colour — a marginally negative reading must not render as bearish. */
.flip {
  color: var(--warn, var(--ink-dim));
}

/* ---- priority ladder ---------------------------------------------------- */
.prio {
  border-top: 1px solid var(--rule-faint);
  padding: var(--s3);
}

.prio-cap {
  display: block;
  color: var(--ink-faint);
  margin-bottom: var(--s2);
}

.prio-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}

.prio-item {
  display: grid;
  grid-template-columns: 18px minmax(80px, auto) 70px 82px 1fr;
  align-items: center;
  gap: var(--s2);
  padding: 5px var(--s2);
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.018);
  border-left: 2px solid var(--rule-hi);
  font-size: 11px;
  cursor: default;
  transition: background 0.12s ease;
}

.prio-item.on {
  background: rgba(255, 255, 255, 0.06);
}

.prio-item.tone-flip {
  border-left-color: var(--warn);
}
.prio-item.tone-call {
  border-left-color: var(--call);
}
.prio-item.tone-put {
  border-left-color: var(--put);
}
.prio-item.tone-pin {
  border-left-color: var(--ink-faint);
}

.prio-rank {
  font-family: var(--font-data);
  font-size: 10px;
  font-weight: 800;
  color: var(--ink-faint);
  text-align: center;
}

.prio-name {
  font-family: var(--font-data);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--ink-soft);
}

.prio-px {
  color: var(--ink);
  font-weight: 700;
}

.prio-dist {
  font-size: 10.5px;
}
.prio-dist.up {
  color: var(--call-hi);
}
.prio-dist.dn {
  color: var(--put-hi);
}

.prio-why {
  color: var(--ink-faint);
  font-size: 10.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---- readout ------------------------------------------------------------ */
.map-readout {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s4);
  padding: var(--s2) var(--s3);
  border-top: 1px solid var(--rule-faint);
  font-size: 11px;
}

.ro {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
}

.ro em {
  font-style: normal;
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--ink-faint);
}

.ro b {
  color: var(--ink);
  font-weight: 700;
}

.warn-note em {
  color: var(--warn);
}

@media (max-width: 760px) {
  .prio-item {
    grid-template-columns: 16px 1fr 64px 72px;
  }
  .prio-why {
    display: none;
  }
  .lane-cap {
    display: none;
  }
}
</style>
