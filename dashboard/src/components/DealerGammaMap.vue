<script setup lang="ts">
/**
 * Dealer gamma map — net dealer GEX revalued across spot, with the per-strike
 * gamma ladder beneath it on the same price axis.
 *
 * WHY THIS EXISTS
 * The server has been computing both of these on every 30s poll and shipping
 * them in the microstructure payload (`gex_profile`, `strikes`), and nothing in
 * the app read either one. Fifty full chain revaluations per poll went into a
 * field no component referenced, so the page named "dealer gamma regime"
 * displayed the regime's *conclusions* — a flip price, a wall price, a verdict
 * sentence — with no way to see the surface they were read off. That is the
 * one view where "trust me" is least acceptable: the flip is a root of this
 * curve, and whether it is a clean single crossing or one of several shallow
 * ones is the difference between a level worth a stop and a coin flip.
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
 * Both lanes share one x (price) axis with the live spot marker, so the curve,
 * the strikes and the structural levels line up vertically and can be read
 * against each other rather than in two separate frames.
 *
 * Everything is withheld when `quality.measurable` is false — see the note in
 * the template. A blank map is a correct map when there is no chain.
 */
import { computed, ref } from 'vue'
import type {
  GexProfilePoint,
  StrikeExposure,
  ChainQuality,
} from '@/microstructureContracts'
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
  }>(),
  { spot: null, zeroGamma: null, callWall: null, putWall: null, pinStrike: null },
)

const hostRef = ref<HTMLDivElement | null>(null)
const { W, H } = useChartSize(hostRef, { minW: 320, minH: 300, fallbackW: 900, fallbackH: 420 })

const measurable = computed(() => props.quality?.measurable !== false && props.profile.length >= 2)

/* ---- layout: two stacked lanes, one shared price axis -------------------- */
const left = 64
const right = 20
const top = 26
const axisH = 22
const laneGap = 14

const innerW = computed(() => Math.max(80, W.value - left - right))
const bodyH = computed(() => Math.max(120, H.value - top - axisH))
const curveH = computed(() => Math.max(70, Math.round((bodyH.value - laneGap) * 0.62)))
const ladderH = computed(() => Math.max(50, bodyH.value - laneGap - curveH.value))
const curveY0 = top
const ladderY0 = computed(() => top + curveH.value + laneGap)

/* ---- price domain -------------------------------------------------------
 * Windowed to the region an operator can act on. The raw profile spans the
 * whole quoted strike ladder (routinely +/-20%), which compresses spot, the
 * flip and both walls into a few pixels. Structural levels always widen the
 * window back out to include themselves — a wall 9% away is more
 * decision-relevant than the strikes either side of spot. */
const WINDOW_PCT = 0.09

const priceDomain = computed<[number, number]>(() => {
  const spot = props.spot
  const xs = props.profile.map((p) => p.spot).filter((v) => Number.isFinite(v))
  if (!xs.length) return [0, 1]
  let lo = Math.min(...xs)
  let hi = Math.max(...xs)
  if (spot && spot > 0) {
    lo = Math.max(lo, spot * (1 - WINDOW_PCT))
    hi = Math.min(hi, spot * (1 + WINDOW_PCT))
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
  const pad = (hi - lo) * 0.04
  return [lo - pad, hi + pad]
})

const xScale = computed(() =>
  linearScale(priceDomain.value, [left, left + innerW.value]),
)

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
  const pad = (hi - lo) * 0.08
  return [lo - pad, hi + pad]
})

const yCurve = computed(() =>
  linearScale(gexDomain.value, [curveY0 + curveH.value, curveY0]),
)

const zeroY = computed(() => yCurve.value(0))

/** Split into a positive-gamma path and a negative-gamma path so each half can
 *  carry its own color. Split points are interpolated at the axis crossing so
 *  the two halves meet exactly on the zero line instead of overlapping a
 *  segment that spans it. */
type Seg = { sign: 1 | -1; d: string }

type Run = { sign: 1 | -1; parts: string[] }

const curveSegments = computed<Seg[]>(() => {
  const pts = visibleProfile.value
  if (pts.length < 2) return []
  const x = xScale.value
  const y = yCurve.value
  const z = zeroY.value
  const segs: Seg[] = []
  const runs: Run[] = []

  for (let i = 0; i < pts.length; i++) {
    const p = pts[i]
    const sign: 1 | -1 = p.net_gex_m >= 0 ? 1 : -1
    const cur = runs.length ? runs[runs.length - 1] : null

    if (cur === null) {
      runs.push({ sign, parts: [`M ${x(p.spot).toFixed(2)} ${y(p.net_gex_m).toFixed(2)}`] })
      continue
    }
    if (cur.sign === sign) {
      cur.parts.push(`L ${x(p.spot).toFixed(2)} ${y(p.net_gex_m).toFixed(2)}`)
      continue
    }
    // Crossing: interpolate the exact zero point so both halves terminate on
    // the zero line rather than sharing a segment that spans it.
    const prev = pts[i - 1]
    const span = p.net_gex_m - prev.net_gex_m
    const t = span === 0 ? 0 : (0 - prev.net_gex_m) / span
    const crossX = x(prev.spot + t * (p.spot - prev.spot))
    cur.parts.push(`L ${crossX.toFixed(2)} ${z.toFixed(2)}`)
    runs.push({
      sign,
      parts: [
        `M ${crossX.toFixed(2)} ${z.toFixed(2)}`,
        `L ${x(p.spot).toFixed(2)} ${y(p.net_gex_m).toFixed(2)}`,
      ],
    })
  }

  for (const run of runs) {
    if (run.parts.length > 1) segs.push({ sign: run.sign, d: run.parts.join(' ') })
  }
  return segs
})

/** Filled area under each half, for reading sign at a glance rather than by
 *  tracing the line against the axis. */
const curveAreas = computed(() =>
  curveSegments.value.map((seg) => {
    // Reconstruct the baseline return path from the segment's own endpoints.
    const coords = [...seg.d.matchAll(/[ML] (-?[\d.]+) (-?[\d.]+)/g)]
    if (coords.length < 2) return { sign: seg.sign, d: '' }
    const firstX = coords[0][1]
    const lastX = coords[coords.length - 1][1]
    const z = zeroY.value.toFixed(2)
    return { sign: seg.sign, d: `${seg.d} L ${lastX} ${z} L ${firstX} ${z} Z` }
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
  return Math.max(1.5, Math.min(14, (innerW.value / n) * 0.7))
})

type Bar = { x: number; y: number; h: number; side: 'call' | 'put'; row: StrikeExposure }

const bars = computed<Bar[]>(() => {
  const x = xScale.value
  const half = ladderH.value / 2
  const scale = ladderScaleM.value
  const out: Bar[] = []
  for (const r of visibleStrikes.value) {
    const cx = x(r.strike)
    const callH = (Math.abs(r.call_gex_m) / scale) * half
    const putH = (Math.abs(r.put_gex_m) / scale) * half
    if (callH >= 0.5) {
      out.push({ x: cx, y: ladderMidY.value - callH, h: callH, side: 'call', row: r })
    }
    if (putH >= 0.5) {
      out.push({ x: cx, y: ladderMidY.value, h: putH, side: 'put', row: r })
    }
  }
  return out
})

/* ---- structural level rules --------------------------------------------- */
type Level = { key: string; label: string; price: number; x: number; tone: string; dash: string }

const levels = computed<Level[]>(() => {
  const x = xScale.value
  const [lo, hi] = priceDomain.value
  const out: Level[] = []
  const push = (key: string, label: string, price: number | null, tone: string, dash: string) => {
    if (price == null || !Number.isFinite(price) || price < lo || price > hi) return
    out.push({ key, label, price, x: x(price), tone, dash })
  }
  push('flip', 'FLIP', props.zeroGamma, 'warn', '5 3')
  push('call', 'CALL W', props.callWall, 'call', '5 3')
  push('put', 'PUT W', props.putWall, 'put', '5 3')
  push('pin', 'PIN', props.pinStrike, 'soft', '2 3')
  return out
})

const spotX = computed(() => {
  const s = props.spot
  const [lo, hi] = priceDomain.value
  if (s == null || !Number.isFinite(s) || s < lo || s > hi) return null
  return xScale.value(s)
})

const xTicks = computed(() => {
  const [lo, hi] = priceDomain.value
  return niceTicks(lo, hi, 6)
    .filter((t) => t >= lo && t <= hi)
    .map((t) => ({ v: t, x: xScale.value(t) }))
})

const yTicks = computed(() => {
  const [lo, hi] = gexDomain.value
  return niceTicks(lo, hi, 4)
    .filter((t) => t >= lo && t <= hi)
    .map((t) => ({ v: t, y: yCurve.value(t) }))
})

/* ---- hover readout ------------------------------------------------------ */
const hoverX = ref<number | null>(null)

const hovered = computed(() => {
  if (hoverX.value == null || !visibleProfile.value.length) return null
  const price = xScale.value.invert(hoverX.value)
  let best = visibleProfile.value[0]
  for (const p of visibleProfile.value) {
    if (Math.abs(p.spot - price) < Math.abs(best.spot - price)) best = p
  }
  const strike = visibleStrikes.value.length
    ? visibleStrikes.value.reduce((a, b) =>
        Math.abs(b.strike - price) < Math.abs(a.strike - price) ? b : a,
      )
    : null
  return { point: best, strike, x: xScale.value(best.spot) }
})

function onMove(e: MouseEvent) {
  const host = hostRef.value
  if (!host) return
  const box = host.getBoundingClientRect()
  const px = e.clientX - box.left
  hoverX.value = px >= left && px <= left + innerW.value ? px : null
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
</script>

<template>
  <div ref="hostRef" class="gamma-map" @mousemove="onMove" @mouseleave="hoverX = null">
    <!-- No chain, no map. Rendering an empty grid with axes would read as
         "flat gamma" rather than "nothing measured", which is the exact
         confusion this whole surface was rebuilt to remove. -->
    <p v-if="!measurable" class="withheld label wraps" role="status">
      No dealer gamma surface to map —
      {{ quality?.reason ?? 'waiting for the first chain read' }}. Nothing is plotted rather
      than plotting a flat line that would read as balanced gamma.
    </p>

    <svg
      v-else
      class="map-svg"
      :viewBox="`0 0 ${W} ${H}`"
      role="img"
      aria-label="Net dealer gamma exposure across spot price, with per-strike gamma ladder"
    >
      <!-- curve lane ---------------------------------------------------- -->
      <g class="grid-lines">
        <line
          v-for="t in yTicks"
          :key="`gy-${t.v}`"
          :x1="left"
          :x2="left + innerW"
          :y1="t.y"
          :y2="t.y"
        />
      </g>
      <text
        v-for="t in yTicks"
        :key="`gyl-${t.v}`"
        class="axis-label"
        :x="left - 6"
        :y="t.y + 3"
        text-anchor="end"
      >
        {{ optGex(t.v) }}
      </text>

      <path
        v-for="(a, i) in curveAreas"
        :key="`area-${i}`"
        :class="['curve-area', a.sign > 0 ? 'is-long' : 'is-short']"
        :d="a.d"
      />
      <path
        v-for="(seg, i) in curveSegments"
        :key="`seg-${i}`"
        :class="['curve-line', seg.sign > 0 ? 'is-long' : 'is-short']"
        :d="seg.d"
      />
      <line class="zero-line" :x1="left" :x2="left + innerW" :y1="zeroY" :y2="zeroY" />
      <text class="lane-title" :x="left" :y="curveY0 - 10">
        NET DEALER GAMMA ($M / 1% MOVE) BY SPOT
      </text>

      <!-- ladder lane --------------------------------------------------- -->
      <line
        class="ladder-axis"
        :x1="left"
        :x2="left + innerW"
        :y1="ladderMidY"
        :y2="ladderMidY"
      />
      <rect
        v-for="(b, i) in bars"
        :key="`bar-${i}`"
        :class="['gex-bar', b.side === 'call' ? 'is-call' : 'is-put']"
        :x="b.x - barW / 2"
        :y="b.y"
        :width="barW"
        :height="Math.max(0.6, b.h)"
      />
      <text class="lane-title" :x="left" :y="ladderY0 - 4">
        GAMMA BY STRIKE — CALLS UP / PUTS DOWN
      </text>

      <!-- structural levels span both lanes so they can be read against
           the curve's shape and the strike concentrations at once -->
      <g v-for="lv in levels" :key="lv.key">
        <line
          :class="['level-line', `tone-${lv.tone}`]"
          :x1="lv.x"
          :x2="lv.x"
          :y1="curveY0"
          :y2="ladderY0 + ladderH"
          :stroke-dasharray="lv.dash"
        />
        <text :class="['level-label', `tone-${lv.tone}`]" :x="lv.x + 4" :y="curveY0 + 10">
          {{ lv.label }}
        </text>
      </g>

      <!-- live spot: solid, and the only marker on the fast clock -->
      <line
        v-if="spotX != null"
        class="spot-line"
        :x1="spotX"
        :x2="spotX"
        :y1="curveY0"
        :y2="ladderY0 + ladderH"
      />
      <text v-if="spotX != null" class="spot-label" :x="spotX + 4" :y="ladderY0 + ladderH - 4">
        SPOT
      </text>

      <!-- hover -->
      <line
        v-if="hovered"
        class="hover-line"
        :x1="hovered.x"
        :x2="hovered.x"
        :y1="curveY0"
        :y2="ladderY0 + ladderH"
      />

      <!-- price axis ---------------------------------------------------- -->
      <line
        class="axis-rule"
        :x1="left"
        :x2="left + innerW"
        :y1="ladderY0 + ladderH"
        :y2="ladderY0 + ladderH"
      />
      <text
        v-for="t in xTicks"
        :key="`xt-${t.v}`"
        class="axis-label"
        :x="t.x"
        :y="ladderY0 + ladderH + 14"
        text-anchor="middle"
      >
        {{ num(t.v, 0) }}
      </text>
    </svg>

    <!-- readout: the numbers the map is evidence for, plus the hover probe -->
    <div v-if="measurable" class="map-readout font-mono">
      <span class="ro">
        <em>net γ at spot</em>
        <b :class="netAtSpot == null ? '' : netAtSpot < 0 ? 'neg' : 'pos'">
          {{ netAtSpot != null ? optGex(netAtSpot) : DASH }}
        </b>
      </span>
      <span class="ro">
        <em>flip</em><b>{{ zeroGamma != null ? num(zeroGamma, 2) : 'none in range' }}</b>
      </span>
      <span v-if="hovered" class="ro">
        <em>at {{ num(hovered.point.spot, 2) }}</em>
        <b>{{ optGex(hovered.point.net_gex_m) }}</b>
      </span>
      <span v-if="hovered?.strike" class="ro">
        <em>K {{ num(hovered.strike.strike, 2) }} OI</em>
        <b>{{ hovered.strike.call_oi }}c / {{ hovered.strike.put_oi }}p</b>
      </span>
      <span v-if="quality && quality.iv_fallback_contracts > 0" class="ro warn-note">
        <em>{{ quality.iv_fallback_contracts }} strike-sides on default IV</em>
      </span>
    </div>
  </div>
</template>

<style scoped>
.gamma-map {
  position: relative;
  width: 100%;
  min-height: 300px;
  background: var(--surface-base);
}

.map-svg {
  display: block;
  width: 100%;
  height: 100%;
}

.withheld {
  padding: var(--s4);
  color: var(--ink-dim);
  max-width: 60ch;
}

.grid-lines line {
  stroke: var(--grid);
  stroke-width: 1;
}

.axis-rule,
.ladder-axis {
  stroke: var(--rule);
  stroke-width: 1;
}

.axis-label {
  fill: var(--ink-faint);
  font-family: var(--font-mono);
  font-size: var(--t-micro);
}

.lane-title {
  fill: var(--ink-dim);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
}

.zero-line {
  stroke: var(--rule-hi);
  stroke-width: 1;
}

.curve-line {
  fill: none;
  stroke-width: 1.75;
}
.curve-line.is-long {
  stroke: var(--long);
}
.curve-line.is-short {
  stroke: var(--short);
}

.curve-area {
  stroke: none;
}
.curve-area.is-long {
  fill: var(--long-wash);
}
.curve-area.is-short {
  fill: var(--short-wash);
}

.gex-bar.is-call {
  fill: var(--call);
}
.gex-bar.is-put {
  fill: var(--put);
}

.level-line {
  stroke-width: 1;
}
.level-line.tone-warn {
  stroke: var(--warn);
}
.level-line.tone-call {
  stroke: var(--call);
}
.level-line.tone-put {
  stroke: var(--put);
}
.level-line.tone-soft {
  stroke: var(--ink-soft);
}

.level-label {
  font-family: var(--font-display);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
}
.level-label.tone-warn {
  fill: var(--warn);
}
.level-label.tone-call {
  fill: var(--call);
}
.level-label.tone-put {
  fill: var(--put);
}
.level-label.tone-soft {
  fill: var(--ink-soft);
}

.spot-line {
  stroke: var(--phosphor);
  stroke-width: 1.5;
}

.spot-label {
  fill: var(--phosphor);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
}

.hover-line {
  stroke: var(--ink-ghost);
  stroke-width: 1;
}

.map-readout {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s4);
  padding: var(--s2) var(--s3);
  border-top: var(--hair) solid var(--rule);
  font-size: var(--t-micro);
}

.ro {
  display: inline-flex;
  gap: var(--s2);
  align-items: baseline;
}

.ro em {
  color: var(--ink-faint);
  font-style: normal;
  letter-spacing: var(--track-label);
}

.ro b {
  color: var(--ink);
  font-weight: 500;
}

.ro b.pos {
  color: var(--long);
}

.ro b.neg {
  color: var(--short);
}

.warn-note em {
  color: var(--warn);
}
</style>
