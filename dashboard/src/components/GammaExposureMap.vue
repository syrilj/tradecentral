<script setup lang="ts">
/**
 * Net-GEX strike profile — vertical bars across the wide desk.
 *
 *   · X axis = strike (low → high, left → right)
 *   · Y axis = net GEX $M (put/negative below zero · call/positive above)
 *
 * Vertical bars use full panel width better than horizontal rows when the
 * GEX panel sits wide next to the squeeze board.
 */
import { computed, ref, watch } from 'vue'
import type { GexStrikeRow } from '@/api'
import { niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'
import { compact, DASH, num } from '@/format'

interface Bar extends GexStrikeRow {
  net: number
  positive: boolean
  index: number
  /** Column center x */
  cx: number
  /** Bar top y */
  y: number
  /** Bar height in px */
  h: number
  /** Bar width in px */
  thickness: number
}

interface Level {
  key: string
  label: string
  value: number
  cls: string
  x: number
  labelX: number
}

const props = withDefaults(defineProps<{
  rows: GexStrikeRow[]
  spot: number
  callWall: number | null
  putWall: number | null
  gammaFlip: number | null
  focusStrike?: number | null
  /** Plot viewport height (bars grow into this). */
  maxHeight?: number
}>(), { maxHeight: 380, focusStrike: null })

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
  if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return
  e.preventDefault()
  lockStrike(strike)
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
const { W: hostW } = useChartSize(hostRef, {
  minW: 240,
  minH: 80,
  fallbackW: 900,
  fallbackH: 280,
})

const left = 48
const right = 10
const top = 18
const bottom = 36
/** Minimum column width so strike labels stay readable. */
const minCol = 14

const hoverStrike = ref<number | null>(null)
const strikeScope = ref<'near' | 'all'>('near')
const metric = ref<'gex' | 'oi'>('gex')

const visible = computed(() => {
  if (!props.rows.length) return []
  if (strikeScope.value === 'all') return props.rows
  const near = props.rows.filter((r) => r.strike >= props.spot * 0.88 && r.strike <= props.spot * 1.12)
  return near.length >= 8 ? near : props.rows
})

/** Ascending strike — low left, high right (price-axis convention). */
const orderedRows = computed(() => [...visible.value].sort((a, b) => a.strike - b.strike))
const colCount = computed(() => Math.max(orderedRows.value.length, 1))

const H = computed(() => Math.max(200, Math.round(props.maxHeight)))
const plotInnerH = computed(() => Math.max(80, H.value - top - bottom))
const plotBottom = computed(() => top + plotInnerH.value)
const zeroY = computed(() => top + plotInnerH.value / 2)
const halfPlotH = computed(() => Math.max(1, plotInnerH.value / 2 - 4))

/** Content width: at least host width; grow for dense chains so we can scroll X. */
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

const netOf = (row: GexStrikeRow): number =>
  metric.value === 'gex' ? row.net_gex_m : row.call_oi - row.put_oi

const maxAbs = computed(() =>
  Math.max(1e-9, ...orderedRows.value.map((r) => Math.abs(netOf(r)))),
)

const totalNet = computed(() => orderedRows.value.reduce((s, r) => s + netOf(r), 0))
const callTotal = computed(() =>
  orderedRows.value.reduce((s, r) => s + (metric.value === 'gex' ? r.call_gex_m : r.call_oi), 0),
)
const putTotal = computed(() =>
  orderedRows.value.reduce((s, r) => s + (metric.value === 'gex' ? r.put_gex_m : r.put_oi), 0),
)

function metricValue(value: number, signed = false): string {
  if (!Number.isFinite(value)) return DASH
  const sign = value > 0 ? (signed ? '+' : '') : value < 0 ? '-' : ''
  const abs = Math.abs(value)
  return metric.value === 'gex' ? `${sign}$${num(abs, 1)}M` : `${sign}${compact(abs)}`
}

function strikeLabel(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return DASH
  return num(value, Number.isInteger(value) ? 0 : 2)
}

const showBarValues = computed(() => bandW.value >= 22)

const bars = computed<Bar[]>(() =>
  orderedRows.value.map((row, index) => {
    const net = netOf(row)
    const positive = net >= 0
    const rawH = (Math.abs(net) / maxAbs.value) * halfPlotH.value
    const h = net === 0 ? 0 : Math.max(rawH, 2)
    const thickness = Math.max(4, Math.min(bandW.value * 0.72, 28))
    const cx = bandCenter(index)
    // Positive grows up from zero; negative grows down.
    const y = positive ? zeroY.value - h : zeroY.value
    return {
      ...row,
      net,
      positive,
      index,
      cx,
      y,
      h,
      thickness,
    }
  }),
)

const focusBar = computed(() => {
  if (!bars.value.length) return null
  const target = hoverStrike.value ?? props.focusStrike ?? props.spot
  return bars.value.reduce((best, row) =>
    Math.abs(row.strike - target) < Math.abs(best.strike - target) ? row : best,
  )
})

/** Map a price onto strike-band x (interpolate between bracketing strikes). */
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

const levels = computed<Level[]>(() => {
  const raw: { key: string; label: string; value: number | null; cls: string }[] = [
    { key: 'put', label: 'PUT', value: props.putWall, cls: 'put' },
    { key: 'flip', label: 'FLIP', value: props.gammaFlip, cls: 'flip' },
    { key: 'spot', label: 'SPOT', value: props.spot, cls: 'spot' },
    { key: 'call', label: 'CALL', value: props.callWall, cls: 'call' },
  ]
  const placed = raw
    .map((level) => ({ ...level, x: level.value != null ? xOfPrice(level.value) : null }))
    .filter((level): level is { key: string; label: string; value: number; cls: string; x: number } => level.x != null)
    .sort((a, b) => a.x - b.x)

  let lastLabelX = -Infinity
  const minGap = 36
  return placed.map((level) => {
    const desired = level.x
    const labelX = desired > lastLabelX + minGap ? desired : lastLabelX + minGap
    lastLabelX = labelX
    return { ...level, labelX }
  })
})

const tickCount = computed(() => (H.value < 220 ? 3 : 5))

const yTicks = computed(() => {
  if (!orderedRows.value.length) return []
  return niceTicks(-maxAbs.value, maxAbs.value, tickCount.value).map((value) => ({
    value,
    y: zeroY.value - (value / maxAbs.value) * halfPlotH.value,
  }))
})

/** Sparse strike labels on x-axis (avoid stampede). */
const strikeTicks = computed(() => {
  const rows = orderedRows.value
  const n = rows.length
  if (!n) return [] as { x: number; label: string; strike: number }[]
  const maxLabels = Math.min(n, Math.max(4, Math.floor(plotInnerW.value / 48)))
  const indices = new Set<number>()
  if (maxLabels <= 1) indices.add(0)
  else {
    for (let k = 0; k < maxLabels; k++) {
      indices.add(Math.round((k * (n - 1)) / (maxLabels - 1)))
    }
  }
  // Always include nearest-to-spot strike.
  let nearest = 0
  let best = Infinity
  rows.forEach((r, i) => {
    const d = Math.abs(r.strike - props.spot)
    if (d < best) { best = d; nearest = i }
  })
  indices.add(nearest)
  return Array.from(indices)
    .sort((a, b) => a - b)
    .map((i) => ({ x: bandCenter(i), label: strikeLabel(rows[i].strike), strike: rows[i].strike }))
})

function barAriaLabel(bar: Bar): string {
  const callText = metric.value === 'gex' ? `call ${metricValue(bar.call_gex_m)}` : `call OI ${compact(bar.call_oi)}`
  const putText = metric.value === 'gex' ? `put ${metricValue(bar.put_gex_m)}` : `put OI ${compact(bar.put_oi)}`
  const state = props.focusStrike === bar.strike
    ? 'Locked. Activate to release.'
    : 'Activate to lock focus.'
  return `Strike ${strikeLabel(bar.strike)}. Net ${metricValue(bar.net, true)}. ${callText}, ${putText}. ${state}`
}
</script>

<template>
  <div class="gex-map">
    <div class="map-controls">
      <div class="control-group">
        <div class="mini-segment">
          <button class="label" :class="{ on: metric === 'gex' }" @click="metric = 'gex'">NET GEX</button>
          <button class="label" :class="{ on: metric === 'oi' }" @click="metric = 'oi'">NET OI</button>
        </div>
      </div>
      <div class="control-group">
        <div class="mini-segment">
          <button class="label" :class="{ on: strikeScope === 'near' }" @click="strikeScope = 'near'">NEAR</button>
          <button class="label" :class="{ on: strikeScope === 'all' }" @click="strikeScope = 'all'">ALL</button>
        </div>
      </div>
      <span class="coverage label">
        {{ bars.length }}/{{ rows.length }}
        · +UP / −DN
        · click→lock
        {{ scrollable ? ' · SCROLL →' : '' }}
      </span>
    </div>

    <div class="exposure-head">
      <div class="exposure-total call">
        <span class="label">{{ metric === 'gex' ? 'CALL' : 'C OI' }}</span>
        <strong class="fig">{{ metricValue(callTotal, true) }}</strong>
      </div>
      <div class="exposure-total put">
        <span class="label">{{ metric === 'gex' ? 'PUT' : 'P OI' }}</span>
        <strong class="fig">{{ metricValue(putTotal) }}</strong>
      </div>
      <div class="exposure-total net" :class="totalNet >= 0 ? 'positive' : 'negative'">
        <span class="label">NET</span>
        <strong class="fig">{{ metricValue(totalNet, true) }}</strong>
      </div>
      <div v-if="focusBar" class="strike-focus">
        <span class="label">
          {{
            hoverStrike != null ? 'HOVER'
              : focusStrike != null ? 'LOCKED'
                : 'SPOT'
          }}
        </span>
        <strong class="fig">${{ strikeLabel(focusBar.strike) }}</strong>
        <span class="focus-split">
          <b :class="focusBar.positive ? 'pos' : 'neg'">
            {{ metricValue(focusBar.net, true) }}
          </b>
          <b class="dim">C {{ metric === 'gex' ? metricValue(focusBar.call_gex_m) : compact(focusBar.call_oi) }}</b>
          <b class="dim">P {{ metric === 'gex' ? metricValue(focusBar.put_gex_m) : compact(focusBar.put_oi) }}</b>
          <button
            v-if="focusStrike != null"
            type="button"
            class="clear-lock label"
            @click="clearLock"
          >CLR</button>
        </span>
      </div>
    </div>

    <div
      ref="hostRef"
      class="plot-scroll"
      :class="{ scrollable }"
      :style="{ height: `${H}px` }"
    >
      <svg
        :viewBox="`0 0 ${W} ${H}`"
        :style="{ height: `${H}px`, width: `${W}px`, minWidth: '100%' }"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Net gamma exposure by strike as vertical bars. Strikes low to high left to right; net GEX up and down from zero."
      >
        <title>Net GEX by strike — vertical bars. Up = positive/call-side; down = negative/put-side.</title>

        <rect
          class="plot-frame"
          :x="left"
          :y="top"
          :width="plotInnerW"
          :height="plotInnerH"
        />

        <g v-if="rows.length" class="grid">
          <line
            v-for="tick in yTicks"
            :key="`grid-${tick.value}`"
            :x1="left"
            :x2="left + plotInnerW"
            :y1="tick.y"
            :y2="tick.y"
            :class="{ zero: tick.value === 0 }"
          />
        </g>

        <!-- wall / flip / spot vertical guides -->
        <g v-for="level in levels" :key="level.key" class="level" :class="level.cls">
          <line :x1="level.x" :x2="level.x" :y1="top" :y2="plotBottom" />
          <text :x="level.labelX" :y="top + 11" text-anchor="middle">{{ level.label }} {{ strikeLabel(level.value) }}</text>
        </g>

        <g v-if="focusStrike != null && lockX != null" class="level focus-lock">
          <line :x1="lockX!" :x2="lockX!" :y1="top" :y2="plotBottom" />
        </g>

        <g v-if="rows.length" class="bars">
          <g
            v-for="bar in bars"
            :key="bar.strike"
            class="strike-bar"
            :class="{
              pos: bar.positive,
              neg: !bar.positive,
              active: focusBar?.strike === bar.strike,
              locked: focusStrike === bar.strike,
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
            <rect
              class="hit"
              :x="bar.cx - bandW / 2"
              :y="top"
              :width="bandW"
              :height="plotInnerH"
            />
            <rect
              class="net-bar"
              :x="bar.cx - bar.thickness / 2"
              :y="bar.y"
              :width="bar.thickness"
              :height="bar.h"
            >
              <title>${{ strikeLabel(bar.strike) }} net {{ metricValue(bar.net, true) }} · C {{ metric === 'gex' ? metricValue(bar.call_gex_m) : compact(bar.call_oi) }} / P {{ metric === 'gex' ? metricValue(bar.put_gex_m) : compact(bar.put_oi) }}</title>
            </rect>
            <text
              v-if="showBarValues && bar.h > 14"
              class="bar-value"
              :class="bar.positive ? 'pos' : 'neg'"
              :x="bar.cx"
              :y="bar.positive ? bar.y - 3 : bar.y + bar.h + 11"
              text-anchor="middle"
            >{{ metricValue(bar.net, true) }}</text>
          </g>
        </g>

        <!-- Y axis (GEX $) -->
        <g v-if="rows.length" class="y-axis">
          <text
            v-for="tick in yTicks"
            :key="`yt-${tick.value}`"
            :x="left - 6"
            :y="tick.y + 3"
            text-anchor="end"
          >{{ tick.value === 0 ? '0' : metricValue(tick.value, true) }}</text>
        </g>
        <text v-if="rows.length" class="axis-cap" :x="left" :y="top - 6">{{ metric === 'gex' ? 'NET GEX $M' : 'NET OI' }} · +UP / −DN</text>

        <!-- X axis (strikes) -->
        <g v-if="rows.length" class="x-axis">
          <template v-for="tick in strikeTicks" :key="`st-${tick.strike}`">
            <line :x1="tick.x" :x2="tick.x" :y1="plotBottom" :y2="plotBottom + 4" />
            <text :x="tick.x" :y="H - 8" text-anchor="middle">{{ tick.label }}</text>
          </template>
        </g>

        <text v-if="!rows.length" :x="W / 2" :y="H / 2" text-anchor="middle" class="empty">NO QUALIFYING GAMMA OBSERVATIONS</text>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.gex-map {
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.map-controls {
  display: flex;
  align-items: center;
  gap: 4px 6px;
  margin: 0;
  min-height: 22px;
  flex: 0 0 auto;
  flex-wrap: wrap;
  padding: 2px 4px 0;
}
.control-group { display: flex; align-items: center; gap: 4px; }
.mini-segment { display: flex; min-height: 22px; border: var(--hair) solid var(--rule-hi); }
.mini-segment button {
  padding: 0 7px;
  color: var(--ink-faint);
  border-right: var(--hair) solid var(--rule);
  font-size: 10px;
  min-height: 22px;
  cursor: pointer;
}
.mini-segment button:last-child { border-right: 0; }
.mini-segment button:hover { color: var(--ink); background: var(--panel-hi); }
.mini-segment button.on { color: var(--ink); background: var(--panel-raise); box-shadow: inset 0 -2px var(--phosphor); }
.coverage { margin-left: auto; color: var(--ink-faint); font-size: 10px; }

.exposure-head {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)) minmax(0, 1.5fr);
  gap: 1px;
  margin: 0;
  flex: 0 0 auto;
  background: var(--rule);
  border: var(--hair) solid var(--rule);
}
.exposure-total, .strike-focus {
  min-width: 0;
  min-height: 24px;
  padding: 2px 6px;
  background: var(--panel-hi);
}
.exposure-total {
  display: flex;
  flex-direction: row;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
  position: relative;
}
.exposure-total::after {
  content: '';
  position: absolute;
  inset: auto 0 0;
  height: 2px;
  background: currentColor;
}
.exposure-total .label { color: inherit; font-size: 9px; flex: 0 0 auto; }
.exposure-total strong {
  font-size: 0.8125rem;
  font-weight: 650;
  line-height: 1.15;
  color: inherit;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: right;
}
.exposure-total.call { color: var(--call); }
.exposure-total.put { color: var(--put); }
.exposure-total.net { color: var(--phosphor); }
.exposure-total.net.negative { color: var(--short); }
.strike-focus {
  display: grid;
  grid-template-columns: auto 1fr;
  align-content: center;
  column-gap: 6px;
  row-gap: 1px;
}
.strike-focus > strong {
  grid-row: 1 / 3;
  grid-column: 1;
  align-self: center;
  font-size: 0.9375rem;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
}
.strike-focus > .label { grid-column: 2; color: var(--phosphor); font-size: 9px; }
.focus-split { grid-column: 2; display: flex; flex-wrap: wrap; gap: 2px 6px; font: 10px var(--font-data); }
.focus-split b { font-weight: 650; white-space: nowrap; color: var(--ink); }
.focus-split .pos { color: var(--long); }
.focus-split .neg { color: var(--short); }
.focus-split .dim { color: var(--ink-dim); font-weight: 500; }

.plot-scroll {
  overflow-x: auto;
  overflow-y: hidden;
  width: 100%;
  min-width: 0;
  border: var(--hair) solid var(--rule);
  flex: 0 0 auto;
  background: var(--void-lift);
}
svg { display: block; background: var(--void-lift); overflow: visible; }
.plot-frame {
  fill: var(--panel);
  stroke: var(--rule-hi);
  stroke-width: 1;
}
.grid line { stroke: var(--rule-hi); stroke-width: 1; opacity: .5; vector-effect: non-scaling-stroke; }
.grid line.zero { stroke: var(--ink-dim); stroke-width: 1.5; opacity: .85; }
.y-axis text, .x-axis text {
  fill: var(--ink-dim);
  font: 600 10px var(--font-data);
  letter-spacing: .02em;
}
.x-axis line { stroke: var(--rule-hi); vector-effect: non-scaling-stroke; }
.axis-cap {
  fill: var(--ink-dim);
  font: 600 10px var(--font-display);
  letter-spacing: .08em;
}

.strike-bar { cursor: pointer; }
.strike-bar .hit { fill: transparent; pointer-events: all; }
.strike-bar .bar-value {
  font: 600 9px var(--font-data);
  letter-spacing: 0.01em;
  pointer-events: none;
  paint-order: stroke;
  stroke: var(--void);
  stroke-width: 2.5px;
}
.strike-bar .bar-value.pos { fill: var(--long); }
.strike-bar .bar-value.neg { fill: var(--short); }
.strike-bar .net-bar {
  vector-effect: non-scaling-stroke;
  stroke-width: 0.5;
  opacity: .92;
  transition: opacity var(--dur-fast) var(--ease-out), stroke-width var(--dur-fast) var(--ease-out);
}
.strike-bar.pos .net-bar { fill: var(--long); stroke: var(--long); }
.strike-bar.neg .net-bar { fill: var(--short); stroke: var(--short); }
.strike-bar:hover .net-bar,
.strike-bar.active .net-bar {
  opacity: 1;
  stroke-width: 1;
}
.strike-bar.locked .net-bar {
  opacity: 1;
  stroke-width: 1.75;
  stroke: var(--phosphor);
}
.strike-bar:focus-visible .net-bar { stroke-width: 1.5; }

.focus-lock line { stroke: var(--phosphor); stroke-width: 2; stroke-dasharray: 3 3; vector-effect: non-scaling-stroke; }
.clear-lock {
  margin-left: 2px;
  padding: 1px 5px;
  min-height: 18px;
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  cursor: pointer;
}
.clear-lock:hover { color: var(--void); background: var(--phosphor); }

.level line { stroke-width: 1.35; stroke-dasharray: 4 4; vector-effect: non-scaling-stroke; opacity: 0.9; }
.level.call line { stroke: var(--call-hi); }
.level.put line { stroke: var(--put-hi); }
.level.spot line { stroke: var(--ink); stroke-dasharray: none; stroke-width: 1.6; opacity: 0.7; }
.level.flip line { stroke: var(--warn); }
.level text {
  font-size: 9px;
  font-weight: 700;
  paint-order: stroke;
  stroke: var(--void);
  stroke-width: 3px;
  stroke-linejoin: round;
  letter-spacing: 0.04em;
}
.level.call text { fill: var(--call-hi); }
.level.put text { fill: var(--put-hi); }
.level.spot text { fill: var(--ink); }
.level.flip text { fill: var(--warn); }
.empty { fill: var(--ink); font: 12px var(--font-display); letter-spacing: .1em; }

@media (max-width: 900px) {
  .coverage { width: 100%; margin-left: 0; }
  .exposure-head { grid-template-columns: repeat(3, 1fr); }
  .strike-focus { grid-column: 1 / -1; }
}
</style>
