<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TrajectoryBar } from '@/api'
import { linearScale, niceTicks, niceDomain, dateTicks } from '@/charts'
import { linePath, areaPath } from '@/charts'
import { num, signedPct, shortDate } from '@/format'

/**
 * The financial trajectory: price trace over a drawdown underlay.
 *
 * Two stacked panes share one x-axis — price on top, underwater curve below.
 * Showing drawdown *beneath* the price rather than as a separate tab is the
 * whole point: a trace that only goes up hides the path it took, and the path
 * is what a position actually has to survive.
 */
const props = withDefaults(
  defineProps<{
    series: TrajectoryBar[]
    symbol: string
    /** Draw the cumulative-growth curve instead of raw price. */
    mode?: 'price' | 'growth'
    height?: number
  }>(),
  { mode: 'price', height: 340 },
)

const W = 1000
const PAD = { t: 14, r: 62, b: 22, l: 10 }
const DD_H = 74 // underwater pane
const GAP = 16

const priceH = computed(() => Math.max(120, props.height - DD_H - GAP - PAD.t - PAD.b))
const totalH = computed(() => PAD.t + priceH.value + GAP + DD_H + PAD.b)

const values = computed(() =>
  props.mode === 'growth' ? props.series.map((b) => b.cum) : props.series.map((b) => b.c),
)

const x = computed(() =>
  linearScale([0, Math.max(1, props.series.length - 1)], [PAD.l, W - PAD.r]),
)

const yDomain = computed(() => {
  const v = values.value
  if (!v.length) return [0, 1] as [number, number]
  return niceDomain(Math.min(...v), Math.max(...v), 0.06)
})

const y = computed(() =>
  linearScale(yDomain.value, [PAD.t + priceH.value, PAD.t]),
)

const ddTop = computed(() => PAD.t + priceH.value + GAP)
const ddMin = computed(() => Math.min(-0.01, ...props.series.map((b) => b.dd)))
const yDd = computed(() => linearScale([ddMin.value, 0], [ddTop.value + DD_H, ddTop.value]))

const pts = computed(() =>
  values.value.map((v, i) => ({ x: x.value(i), y: y.value(v) })),
)
const ddPts = computed(() =>
  props.series.map((b, i) => ({ x: x.value(i), y: yDd.value(b.dd) })),
)

const trace = computed(() => linePath(pts.value))
const fill = computed(() => areaPath(pts.value, PAD.t + priceH.value))
const ddTrace = computed(() => areaPath(ddPts.value, ddTop.value))

const yTicks = computed(() => niceTicks(yDomain.value[0], yDomain.value[1], 5))
const xTicks = computed(() => dateTicks(props.series.map((b) => b.d), 6))

/* The trace is up if it finished above where it started. Colouring the whole
   line by net direction (rather than per-segment) keeps it readable at 1000+
   points where per-segment colouring turns to mush. */
const up = computed(() => {
  const v = values.value
  return v.length > 1 ? v[v.length - 1] >= v[0] : true
})
const stroke = computed(() => (up.value ? 'var(--long)' : 'var(--short)'))

/* ---- crosshair ---------------------------------------------------------- */
const hover = ref<number | null>(null)
const svg = ref<SVGSVGElement | null>(null)

function onMove(e: MouseEvent): void {
  const el = svg.value
  if (!el || !props.series.length) return
  const box = el.getBoundingClientRect()
  const px = ((e.clientX - box.left) / box.width) * W
  const i = Math.round(x.value.invert(px))
  hover.value = Math.max(0, Math.min(props.series.length - 1, i))
}

const cur = computed(() => (hover.value === null ? null : props.series[hover.value] ?? null))
const curX = computed(() => (hover.value === null ? 0 : x.value(hover.value)))
const curY = computed(() =>
  hover.value === null ? 0 : y.value(values.value[hover.value] ?? 0),
)
/* Flip the readout to the left half once the cursor passes centre so it never
   runs off the plot. */
const flip = computed(() => curX.value > W * 0.62)
</script>

<template>
  <figure class="chart">
    <svg
      ref="svg"
      class="svg"
      :viewBox="`0 0 ${W} ${totalH}`"
      preserveAspectRatio="none"
      role="img"
      :aria-label="`${symbol} ${mode} trajectory, ${series.length} bars`"
      @mousemove="onMove"
      @mouseleave="hover = null"
    >
      <defs>
        <linearGradient :id="`g-${symbol}`" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="stroke" stop-opacity="0.20" />
          <stop offset="100%" :stop-color="stroke" stop-opacity="0" />
        </linearGradient>
      </defs>

      <!-- horizontal graticule -->
      <g class="grid">
        <line
          v-for="t in yTicks"
          :key="`h${t}`"
          :x1="PAD.l"
          :x2="W - PAD.r"
          :y1="y(t)"
          :y2="y(t)"
        />
      </g>

      <!-- price pane -->
      <path :d="fill" :fill="`url(#g-${symbol})`" />
      <path :d="trace" class="trace" :stroke="stroke" />

      <!-- y labels, right gutter -->
      <g class="ylab">
        <text v-for="t in yTicks" :key="`y${t}`" :x="W - PAD.r + 8" :y="y(t) + 3">
          {{ mode === 'growth' ? `${num(t, 2)}×` : num(t, 2) }}
        </text>
      </g>

      <!-- underwater pane -->
      <line class="zero" :x1="PAD.l" :x2="W - PAD.r" :y1="ddTop" :y2="ddTop" />
      <path :d="ddTrace" class="dd" />
      <text class="pane-lab" :x="PAD.l + 2" :y="ddTop + 11">DRAWDOWN</text>
      <text class="pane-lab dim" :x="W - PAD.r + 8" :y="ddTop + DD_H">
        {{ num(ddMin * 100, 1) }}%
      </text>

      <!-- x labels -->
      <g class="xlab">
        <text v-for="t in xTicks" :key="`x${t.i}`" :x="x(t.i)" :y="totalH - 6">
          {{ t.label }}
        </text>
      </g>

      <!-- crosshair -->
      <g v-if="cur" class="cross">
        <line :x1="curX" :x2="curX" :y1="PAD.t" :y2="ddTop + DD_H" />
        <circle :cx="curX" :cy="curY" r="3" :fill="stroke" />
        <circle :cx="curX" :cy="yDd(cur.dd)" r="2" class="dd-dot" />
      </g>
    </svg>

    <!-- readout floats over the plot; text, not a tooltip chrome box -->
    <figcaption v-if="cur" class="readout" :class="{ flip }">
      <span class="r-date label">{{ shortDate(cur.d) }}</span>
      <span class="r-px fig">{{ mode === 'growth' ? `${num(cur.cum, 3)}×` : num(cur.c, 2) }}</span>
      <span class="r-chg fig" :class="cur.ret >= 0 ? 'pos' : 'neg'">
        {{ signedPct(cur.ret * 100, 2) }}
      </span>
      <span class="r-dd fig neg">{{ num(cur.dd * 100, 1) }}% dd</span>
    </figcaption>
  </figure>
</template>

<style scoped>
.chart { position: relative; width: 100%; }

.svg { display: block; width: 100%; height: auto; overflow: visible; }

.grid line {
  stroke: var(--rule-faint);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.trace {
  fill: none;
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.dd {
  fill: var(--short);
  fill-opacity: 0.24;
  stroke: var(--short);
  stroke-width: 1;
  stroke-opacity: 0.55;
  vector-effect: non-scaling-stroke;
}

.zero {
  stroke: var(--rule-hi);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

text {
  font-family: var(--font-data);
  font-size: 9px;
  fill: var(--ink-faint);
}

.ylab text { text-anchor: start; }
.xlab text { text-anchor: middle; fill: var(--ink-ghost); }

.pane-lab {
  font-family: var(--font-display);
  font-size: 7px;
  letter-spacing: 0.14em;
  fill: var(--ink-ghost);
}
.pane-lab.dim { fill: var(--short); opacity: 0.7; }

.cross line {
  stroke: var(--phosphor);
  stroke-width: 1;
  stroke-dasharray: 2 3;
  vector-effect: non-scaling-stroke;
  opacity: 0.75;
}
.dd-dot { fill: var(--short); }

.readout {
  position: absolute;
  top: 0;
  right: 66px;
  display: flex;
  align-items: baseline;
  gap: var(--s3);
  padding: 3px 0;
  pointer-events: none;
  background: linear-gradient(to right, transparent, var(--panel) 12%);
}
.readout.flip { right: auto; left: 8px; background: linear-gradient(to left, transparent, var(--panel) 12%); }

.r-date { color: var(--ink-ghost); }
.r-px { font-size: var(--t-body); color: var(--ink); font-weight: 500; }
.r-chg, .r-dd { font-size: var(--t-tiny); }
.r-dd { opacity: 0.8; }
</style>
