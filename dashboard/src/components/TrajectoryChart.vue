<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TrajectoryBar } from '@/api'
import { linearScale, niceTicks, dateTicks, ema, linePath, areaPath } from '@/charts'
import { num, signedPct, shortDate } from '@/format'

/**
 * The financial trajectory: price trace over a drawdown underlay.
 * In price mode, also overlays session-style VWAP and EMA 9/21 — the levels
 * discretionary and systematic desks pin execution against.
 */
interface TrajectoryLevel {
  label: string
  price: number
  tone?: 'pos' | 'neg' | 'accent' | 'flat'
}

const CANDLE_CAP = 260

function aggregateBars(series: TrajectoryBar[], cap: number): TrajectoryBar[] {
  if (series.length <= cap) return series
  const step = Math.ceil(series.length / cap)
  const out: TrajectoryBar[] = []
  for (let i = 0; i < series.length; i += step) {
    const chunk = series.slice(i, Math.min(series.length, i + step))
    const first = chunk[0]
    const last = chunk[chunk.length - 1]
    let h = first.h
    let l = first.l
    let vol = 0
    for (const b of chunk) {
      if (Number.isFinite(b.h) && b.h > h) h = b.h
      if (Number.isFinite(b.l) && b.l > 0 && b.l < l) l = b.l
      vol += Math.max(0, b.v || 0)
    }
    out.push({ ...last, o: first.o, h, l, v: vol })
  }
  return out
}

const props = withDefaults(
  defineProps<{
    series: TrajectoryBar[]
    symbol: string
    /** Draw the cumulative-growth curve instead of raw price. */
    mode?: 'price' | 'growth'
    /** OHLC candles (price mode) vs close line. */
    renderAs?: 'candles' | 'line'
    height?: number
    showVwap?: boolean
    showEma?: boolean
    /** Horizontal reference prices (bear / mark / base / bull). */
    levels?: TrajectoryLevel[]
  }>(),
  { mode: 'price', renderAs: 'candles', height: 340, showVwap: true, showEma: true, levels: () => [] },
)

const W = 1000
const PAD = { t: 14, r: 62, b: 22, l: 10 }
const DD_H = 74 // underwater pane
const GAP = 16

const priceH = computed(() => Math.max(120, props.height - DD_H - GAP - PAD.t - PAD.b))
const totalH = computed(() => PAD.t + priceH.value + GAP + DD_H + PAD.b)

const wantCandles = computed(
  () => props.mode === 'price' && props.renderAs === 'candles' && props.series.length > 0,
)

/** Long windows aggregate OHLC so the pane does not paint 1k+ SVG candles. */
const plotSeries = computed(() =>
  wantCandles.value ? aggregateBars(props.series, CANDLE_CAP) : props.series,
)

const values = computed(() =>
  props.mode === 'growth' ? plotSeries.value.map((b) => b.cum) : plotSeries.value.map((b) => b.c),
)

/** Cumulative VWAP from typical price (H+L+C)/3 · volume — daily bars proxy. */
const vwapSeries = computed(() => {
  if (props.mode !== 'price' || !props.showVwap || !plotSeries.value.length) return null as number[] | null
  let pv = 0
  let vol = 0
  return plotSeries.value.map((b) => {
    const typical = (b.h + b.l + b.c) / 3
    const v = Math.max(0, b.v || 0)
    pv += typical * v
    vol += v
    return vol > 0 ? pv / vol : b.c
  })
})

const ema9 = computed(() => {
  if (props.mode !== 'price' || !props.showEma) return null as number[] | null
  const closes = plotSeries.value.map((b) => b.c)
  return closes.length ? ema(closes, 9) : null
})
const ema21 = computed(() => {
  if (props.mode !== 'price' || !props.showEma) return null as number[] | null
  const closes = plotSeries.value.map((b) => b.c)
  return closes.length ? ema(closes, 21) : null
})

const x = computed(() =>
  linearScale([0, Math.max(1, plotSeries.value.length - 1)], [PAD.l, W - PAD.r]),
)

const useCandles = computed(() => wantCandles.value)

const yDomain = computed(() => {
  const v: number[] = []
  if (useCandles.value) {
    for (const b of plotSeries.value) {
      if (b.h > 0 && b.l > 0) v.push(b.h, b.l, b.o, b.c)
    }
  } else {
    for (const val of values.value) {
      if (Number.isFinite(val)) v.push(val)
    }
  }
  if (props.mode === 'price') {
    if (vwapSeries.value) {
      for (const val of vwapSeries.value) if (Number.isFinite(val) && val > 0) v.push(val)
    }
    if (ema9.value) {
      for (const val of ema9.value) if (Number.isFinite(val) && val > 0) v.push(val)
    }
    if (ema21.value) {
      for (const val of ema21.value) if (Number.isFinite(val) && val > 0) v.push(val)
    }
    for (const level of props.levels) {
      if (Number.isFinite(level.price) && level.price > 0) v.push(level.price)
    }
  }
  if (!v.length) return [0, 1] as [number, number]
  const minVal = Math.min(...v)
  const maxVal = Math.max(...v)
  const span = Math.max(0.001, maxVal - minVal)
  const pad = span * 0.035
  const lo = Math.max(0, minVal - pad)
  const hi = maxVal + pad
  return [lo, hi] as [number, number]
})

const plottedLevels = computed(() => {
  if (props.mode !== 'price') return [] as Array<TrajectoryLevel & { y: number }>
  return props.levels
    .filter((level) => Number.isFinite(level.price) && level.price > 0)
    .map((level) => ({ ...level, y: y.value(level.price) }))
})

/** Candle geometry — body + wick for each bar. */
const candles = computed(() => {
  if (!useCandles.value) return [] as {
    x: number
    mid: number
    bodyTop: number
    bodyBot: number
    high: number
    low: number
    up: boolean
    w: number
  }[]
  const n = plotSeries.value.length
  const slot = Math.max(1, (W - PAD.l - PAD.r) / Math.max(1, n))
  const bodyW = Math.max(1.5, Math.min(10, slot * 0.68))
  return plotSeries.value.map((b, i) => {
    const cx = x.value(i)
    const o = y.value(b.o)
    const c = y.value(b.c)
    return {
      x: cx - bodyW / 2,
      mid: cx,
      bodyTop: Math.min(o, c),
      bodyBot: Math.max(o, c),
      high: y.value(b.h),
      low: y.value(b.l),
      up: b.c >= b.o,
      w: bodyW,
    }
  })
})

const y = computed(() =>
  linearScale(yDomain.value, [PAD.t + priceH.value, PAD.t]),
)

const ddTop = computed(() => PAD.t + priceH.value + GAP)
const ddMin = computed(() => Math.min(-0.01, ...plotSeries.value.map((b) => b.dd)))
const yDd = computed(() => linearScale([ddMin.value, 0], [ddTop.value + DD_H, ddTop.value]))

const pts = computed(() =>
  values.value.map((v, i) => ({ x: x.value(i), y: y.value(v) })),
)
const ddPts = computed(() =>
  plotSeries.value.map((b, i) => ({ x: x.value(i), y: yDd.value(b.dd) })),
)

const trace = computed(() => linePath(pts.value))
const fill = computed(() => areaPath(pts.value, PAD.t + priceH.value))
const ddTrace = computed(() => areaPath(ddPts.value, ddTop.value))

const vwapPath = computed(() => {
  if (!vwapSeries.value) return ''
  return linePath(vwapSeries.value.map((v, i) => ({ x: x.value(i), y: y.value(v) })))
})
const ema9Path = computed(() => {
  if (!ema9.value) return ''
  return linePath(ema9.value.map((v, i) => ({ x: x.value(i), y: y.value(v) })))
})
const ema21Path = computed(() => {
  if (!ema21.value) return ''
  return linePath(ema21.value.map((v, i) => ({ x: x.value(i), y: y.value(v) })))
})

const lastOverlays = computed(() => {
  if (props.mode !== 'price' || !plotSeries.value.length) return null
  const i = plotSeries.value.length - 1
  return {
    px: plotSeries.value[i].c,
    vwap: vwapSeries.value?.[i] ?? null,
    e9: ema9.value?.[i] ?? null,
    e21: ema21.value?.[i] ?? null,
  }
})

const yTicks = computed(() => niceTicks(yDomain.value[0], yDomain.value[1], 5))
const xTicks = computed(() => dateTicks(plotSeries.value.map((b) => b.d), 6))

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
  if (!el || !plotSeries.value.length) return
  const box = el.getBoundingClientRect()
  const px = ((e.clientX - box.left) / box.width) * W
  const i = Math.round(x.value.invert(px))
  hover.value = Math.max(0, Math.min(plotSeries.value.length - 1, i))
}

const cur = computed(() => (hover.value === null ? null : plotSeries.value[hover.value] ?? null))
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
      :aria-label="`${symbol} ${mode} trajectory, ${plotSeries.length} bars`"
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

      <!-- price pane: candles (live daily OHLC) or line -->
      <template v-if="useCandles">
        <g class="candles">
          <g v-for="(c, i) in candles" :key="i" class="candle" :class="c.up ? 'up' : 'dn'">
            <line :x1="c.mid" :x2="c.mid" :y1="c.high" :y2="c.low" class="wick" />
            <rect
              :x="c.x"
              :y="c.bodyTop"
              :width="c.w"
              :height="Math.max(1, c.bodyBot - c.bodyTop)"
              class="body"
            />
          </g>
        </g>
        <path v-if="ema21Path" class="overlay ema21" :d="ema21Path" />
        <path v-if="ema9Path" class="overlay ema9" :d="ema9Path" />
        <path v-if="vwapPath" class="overlay vwap" :d="vwapPath" />
      </template>
      <template v-else>
        <path :d="fill" :fill="`url(#g-${symbol})`" />
        <path v-if="ema21Path" class="overlay ema21" :d="ema21Path" />
        <path v-if="ema9Path" class="overlay ema9" :d="ema9Path" />
        <path v-if="vwapPath" class="overlay vwap" :d="vwapPath" />
        <path :d="trace" class="trace" :stroke="stroke" />
      </template>

      <!-- case / mark reference levels — scale includes prices below the live print -->
      <g v-if="plottedLevels.length" class="levels">
        <g v-for="lv in plottedLevels" :key="lv.label" class="level" :class="lv.tone || 'flat'">
          <line :x1="PAD.l" :x2="W - PAD.r" :y1="lv.y" :y2="lv.y" />
          <text :x="W - PAD.r + 8" :y="lv.y + 3">{{ lv.label }}</text>
        </g>
      </g>

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
      <template v-if="mode === 'price' && hover !== null">
        <span v-if="vwapSeries" class="r-ov fig vwap-c">VWAP {{ num(vwapSeries[hover], 2) }}</span>
        <span v-if="ema9" class="r-ov fig ema9-c">E9 {{ num(ema9[hover], 2) }}</span>
        <span v-if="ema21" class="r-ov fig ema21-c">E21 {{ num(ema21[hover], 2) }}</span>
      </template>
    </figcaption>

    <div v-if="mode === 'price' && lastOverlays" class="legend label">
      <span class="leg-px">PRICE {{ num(lastOverlays.px, 2) }}</span>
      <span v-if="lastOverlays.vwap != null" class="vwap-c">VWAP {{ num(lastOverlays.vwap, 2) }}</span>
      <span v-if="lastOverlays.e9 != null" class="ema9-c">EMA9 {{ num(lastOverlays.e9, 2) }}</span>
      <span v-if="lastOverlays.e21 != null" class="ema21-c">EMA21 {{ num(lastOverlays.e21, 2) }}</span>
      <span v-for="lv in plottedLevels" :key="`leg-${lv.label}`" class="leg-lv" :class="lv.tone || 'flat'">
        {{ lv.label }} {{ num(lv.price, 2) }}
      </span>
    </div>
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

.candle .wick {
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.candle .body {
  stroke-width: 0;
  vector-effect: non-scaling-stroke;
}
.candle.up .wick { stroke: var(--long); }
.candle.up .body { fill: var(--long); }
.candle.dn .wick { stroke: var(--short); }
.candle.dn .body { fill: var(--short); }

.overlay {
  fill: none;
  stroke-width: 1.15;
  vector-effect: non-scaling-stroke;
  stroke-linejoin: round;
  opacity: 0.92;
}
/* Series hues stay on-token: warn / call / put. No rainbow chart defaults. */
.overlay.vwap { stroke: var(--warn); stroke-dasharray: 5 3; }
.overlay.ema9 { stroke: var(--call-hi); }
.overlay.ema21 { stroke: var(--put); opacity: 0.85; }

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s3);
  padding: 6px 2px 0;
  color: var(--ink-faint);
}
.leg-px { color: var(--ink-dim); }
.vwap-c { color: var(--warn); }
.ema9-c { color: var(--call-hi); }
.ema21-c { color: var(--put); }
.leg-lv.neg { color: var(--short); }
.leg-lv.pos { color: var(--long); }
.leg-lv.accent { color: var(--phosphor); }
.leg-lv.flat { color: var(--ink-dim); }

.level line {
  stroke-width: 1;
  stroke-dasharray: 4 3;
  vector-effect: non-scaling-stroke;
  opacity: 0.85;
}
.level text {
  font-size: 8px;
  letter-spacing: 0.08em;
}
.level.neg line, .level.neg text { stroke: var(--short); fill: var(--short); }
.level.pos line, .level.pos text { stroke: var(--long); fill: var(--long); }
.level.accent line, .level.accent text { stroke: var(--phosphor); fill: var(--phosphor); }
.level.flat line, .level.flat text { stroke: var(--ink-dim); fill: var(--ink-dim); }
.r-ov { font-size: 10px; }

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
  user-select: none;
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
  background: var(--panel);
}
.readout.flip { right: auto; left: 8px; background: var(--panel); }

.r-date { color: var(--ink-ghost); }
.r-px { font-size: var(--t-body); color: var(--ink); font-weight: 500; }
.r-chg, .r-dd { font-size: var(--t-tiny); }
.r-dd { opacity: 0.8; }
</style>
