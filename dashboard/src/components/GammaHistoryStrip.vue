<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { GexHistoryPoint } from '@/api'
import { num, optSignedGex, shortDate } from '@/format'

/**
 * Compact multi-day GEX wall / spot / net strip.
 * Width tracks the host via ResizeObserver (no fixed 900 viewBox letterbox).
 * Internal layout scales with the height prop so dense desk defaults (~110)
 * still leave readable price + GEX bands.
 */
const props = withDefaults(
  defineProps<{
    history: GexHistoryPoint[]
    height?: number
  }>(),
  { height: 110 },
)

const hostRef = ref<HTMLDivElement | null>(null)
const measuredWidth = ref(0)
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  const el = hostRef.value
  if (!el) return
  measuredWidth.value = el.getBoundingClientRect().width
  if (typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver((entries) => {
    const width = entries[0]?.contentRect.width
    if (width && width > 0) measuredWidth.value = width
  })
  resizeObserver.observe(el)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})

const W = computed(() => Math.max(240, Math.round(measuredWidth.value) || 640))
const H = computed(() => Math.max(80, Math.round(props.height)))

const left = computed(() => (W.value < 400 ? 40 : 48))
const right = 12
const top = 12
/** Split: ~62% price band, gap, ~28% GEX bars, residual for date labels. */
const priceBottom = computed(() => Math.round(top + (H.value - top - 16) * 0.58))
const gexTop = computed(() => priceBottom.value + 8)
const gexBottom = computed(() => H.value - 14)
const gexMid = computed(() => (gexTop.value + gexBottom.value) / 2)
const gexHalf = computed(() => Math.max(6, (gexBottom.value - gexTop.value) / 2 - 1))

const ordered = computed(() => [...props.history].sort((a, b) => a.t.localeCompare(b.t)))

function x(index: number): number {
  if (ordered.value.length <= 1) return (left.value + W.value - right) / 2
  return left.value + (index / (ordered.value.length - 1)) * (W.value - left.value - right)
}

const priceDomain = computed(() => {
  const values = ordered.value
    .flatMap((point) => [point.spot, point.call_wall, point.put_wall])
    .filter((value): value is number => value != null && Number.isFinite(value))
  if (!values.length) return { lo: 0, hi: 1 }
  let lo = Math.min(...values)
  let hi = Math.max(...values)
  const pad = Math.max((hi - lo) * 0.15, hi * 0.01, 0.01)
  if (lo === hi) [lo, hi] = [lo - pad, hi + pad]
  else [lo, hi] = [lo - pad, hi + pad]
  return { lo, hi }
})

function priceY(value: number): number {
  const { lo, hi } = priceDomain.value
  return priceBottom.value - ((value - lo) / (hi - lo)) * (priceBottom.value - top)
}

function pathFor(key: 'spot' | 'call_wall' | 'put_wall'): string {
  const points = ordered.value
    .map((point, index) => ({ value: point[key], x: x(index) }))
    .filter((point): point is { value: number; x: number } => point.value != null)
  return points
    .map(
      (point, index) =>
        `${index ? 'L' : 'M'}${point.x.toFixed(2)},${priceY(point.value).toFixed(2)}`,
    )
    .join(' ')
}

const spotPath = computed(() => pathFor('spot'))
const callPath = computed(() => pathFor('call_wall'))
const putPath = computed(() => pathFor('put_wall'))
const maxGex = computed(() =>
  Math.max(1e-9, ...ordered.value.map((point) => Math.abs(point.total_gex_m))),
)
const latest = computed(() => ordered.value.at(-1))
const hoverIdx = ref<number | null>(null)
const activePoint = computed(() =>
  hoverIdx.value != null ? ordered.value[hoverIdx.value] : latest.value,
)

const barW = computed(() => {
  const n = Math.max(ordered.value.length, 1)
  const plotW = W.value - left.value - right
  return Math.max(2, Math.min(12, (plotW / n) * 0.55))
})
</script>

<template>
  <div class="history-strip">
    <div class="history-head">
      <div class="titles">
        <span class="label title">GEX history</span>
        <span class="label sub">
          chain snapshots · walls + spot + net
          {{ latest?.expiry ? `· exp ${shortDate(latest.expiry)}` : '· all exp' }}
        </span>
      </div>
      <div class="history-facts">
        <span class="label"
          >N <b class="fig">{{ ordered.length }}</b></span
        >
        <span class="label"
          >NET
          <b class="fig" :class="activePoint && activePoint.total_gex_m >= 0 ? 'call' : 'put'">{{
            activePoint ? optSignedGex(activePoint.total_gex_m, 1) : '—'
          }}</b></span
        >
        <span class="label"
          >AS OF <b class="fig">{{ shortDate(activePoint?.t) }}</b></span
        >
        <span v-if="hoverIdx != null && activePoint" class="history-probe label">
          SPOT ${{ num(activePoint.spot) }} · CW ${{ num(activePoint.call_wall) }} · PW ${{
            num(activePoint.put_wall)
          }}
        </span>
      </div>
      <div class="history-key label">
        <span class="call"><i />Call</span>
        <span class="put"><i />Put</span>
        <span class="spot"><i />Spot</span>
        <span class="net"><i />Net</span>
      </div>
    </div>

    <div ref="hostRef" class="canvas" :style="{ height: `${H}px` }">
      <svg
        :viewBox="`0 0 ${W} ${H}`"
        class="svg"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Historical gamma walls, spot, and net gamma by captured snapshot"
      >
        <g class="grid">
          <line :x1="left" :x2="W - right" :y1="top" :y2="top" />
          <line :x1="left" :x2="W - right" :y1="priceBottom" :y2="priceBottom" />
          <line :x1="left" :x2="W - right" :y1="gexMid" :y2="gexMid" />
          <text :x="left - 6" :y="top + 4" text-anchor="end">{{ num(priceDomain.hi, 0) }}</text>
          <text :x="left - 6" :y="priceBottom + 4" text-anchor="end">
            {{ num(priceDomain.lo, 0) }}
          </text>
          <text :x="left - 6" :y="gexMid + 3" text-anchor="end">GEX</text>
        </g>

        <g class="gex-bars">
          <rect
            v-for="(point, index) in ordered"
            :key="`gex-${point.t}`"
            :x="x(index) - barW / 2"
            :y="
              point.total_gex_m >= 0
                ? gexMid - (Math.abs(point.total_gex_m) / maxGex) * gexHalf
                : gexMid
            "
            :width="barW"
            :height="Math.max(1.5, (Math.abs(point.total_gex_m) / maxGex) * gexHalf)"
            :class="[
              point.total_gex_m >= 0 ? 'positive' : 'negative',
              { active: hoverIdx === index },
            ]"
            @mouseenter="hoverIdx = index"
            @mouseleave="hoverIdx = null"
          >
            <title>
              {{ shortDate(point.t) }} · net GEX {{ optSignedGex(point.total_gex_m, 2) }} · spot ${{
                num(point.spot)
              }}
            </title>
          </rect>
        </g>

        <path v-if="callPath" class="trace call" :d="callPath" />
        <path v-if="putPath" class="trace put" :d="putPath" />
        <path v-if="spotPath" class="trace spot" :d="spotPath" />

        <g class="points">
          <g v-for="(point, index) in ordered" :key="point.t">
            <circle
              :cx="x(index)"
              :cy="priceY(point.spot)"
              r="8"
              class="hit"
              @mouseenter="hoverIdx = index"
              @mouseleave="hoverIdx = null"
            >
              <title>
                {{ shortDate(point.t) }} · spot ${{ num(point.spot) }} · call wall
                {{ num(point.call_wall) }} · put wall {{ num(point.put_wall) }}
              </title>
            </circle>
            <circle
              :cx="x(index)"
              :cy="priceY(point.spot)"
              r="2.5"
              class="dot"
              :class="{ active: hoverIdx === index }"
            />
            <text
              v-if="index === 0 || index === ordered.length - 1"
              :x="x(index)"
              :y="H - 2"
              text-anchor="middle"
            >
              {{ shortDate(point.t) }}
            </text>
          </g>
        </g>

        <text v-if="!ordered.length" :x="W / 2" :y="H / 2" text-anchor="middle" class="empty">
          NO CHAIN SNAPSHOTS
        </text>
        <text
          v-else-if="ordered.length === 1"
          :x="W / 2"
          :y="priceBottom / 2 + top / 2"
          text-anchor="middle"
          class="single"
        >
          1 DAY · NEED 2+ SNAPSHOTS
        </text>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.history-strip {
  margin: 6px 0 0;
  padding-top: 6px;
  border-top: var(--hair) solid var(--rule);
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s1);
}
.history-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px 10px;
  min-height: 24px;
  flex-wrap: wrap;
}
.titles {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
}
.title {
  color: var(--ink);
  white-space: nowrap;
}
.sub {
  color: var(--ink-faint);
  font-size: 10px;
}
.history-facts {
  display: flex;
  gap: 6px 12px;
  align-items: center;
  flex-wrap: wrap;
}
.history-facts b {
  margin-left: 3px;
  color: var(--ink);
}
.history-facts .call {
  color: var(--call-hi);
}
.history-facts .put {
  color: var(--put-hi);
}
.history-probe {
  padding: 1px 6px;
  background: var(--panel-raise);
  border: var(--hair) solid var(--rule-hi);
  color: var(--phosphor);
  font: 700 9px var(--font-data);
  transition:
    transform 0.15s cubic-bezier(0.16, 1, 0.3, 1),
    opacity 0.15s ease;
}
.canvas {
  position: relative;
  width: 100%;
  min-width: 0;
  overflow: visible;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
}
.svg {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}
.grid line {
  stroke: var(--rule);
  stroke-width: 1px;
  vector-effect: non-scaling-stroke;
}
.grid text,
.points text {
  fill: var(--ink-dim);
  font: 600 10px var(--font-data);
}
.trace {
  fill: none;
  stroke-width: 1.6;
  vector-effect: non-scaling-stroke;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.trace.call {
  stroke: var(--call-hi);
}
.trace.put {
  stroke: var(--put-hi);
}
.trace.spot {
  stroke: var(--ink);
}
.points .hit {
  fill: transparent;
  stroke: none;
  pointer-events: all;
  cursor: crosshair;
}
.points .dot {
  fill: var(--ink-soft);
  pointer-events: none;
  transition:
    transform 0.15s cubic-bezier(0.16, 1, 0.3, 1),
    fill 0.15s ease;
}
.points .dot.active {
  fill: var(--phosphor);
  transform: scale(1.5);
}

/* High-contrast emerald/crimson GEX strip bars */
.gex-bars rect {
  vector-effect: non-scaling-stroke;
  stroke-width: 1px;
  transition:
    opacity 0.15s cubic-bezier(0.16, 1, 0.3, 1),
    stroke-width 0.15s ease,
    fill 0.15s ease;
  cursor: crosshair;
}
.gex-bars rect.positive {
  fill: var(--call);
  stroke: var(--call-hi);
  opacity: 0.92;
}
.gex-bars rect.negative {
  fill: var(--put);
  stroke: var(--put-hi);
  opacity: 0.92;
}
.gex-bars rect:hover,
.gex-bars rect.active {
  opacity: 1;
  stroke-width: 1.5px;
}
.gex-bars rect.positive:hover,
.gex-bars rect.positive.active {
  fill: var(--call-hi);
}
.gex-bars rect.negative:hover,
.gex-bars rect.negative.active {
  fill: var(--put-hi);
}

.empty,
.single {
  fill: var(--ink-dim);
  font: 10px var(--font-display);
  letter-spacing: 0.08em;
}
.single {
  fill: var(--warn);
}
.history-key {
  display: flex;
  gap: 8px;
  align-items: center;
  color: var(--ink-faint);
  font-size: 10px;
  margin-left: auto;
}
.history-key span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.history-key i {
  display: inline-block;
  width: 10px;
  height: 2px;
  background: currentColor;
}
.history-key .call {
  color: var(--call-hi);
}
.history-key .put {
  color: var(--put-hi);
}
.history-key .spot {
  color: var(--ink);
}
.history-key .net {
  color: var(--call-hi);
}
.history-key .net i {
  height: 8px;
  width: 6px;
}
@media (max-width: 760px) {
  .history-head {
    align-items: flex-start;
  }
  .history-key {
    margin-left: 0;
    width: 100%;
  }
}
</style>
