<script setup lang="ts">
import { computed, ref } from 'vue'
import { num } from '@/format'
import { linearScale, niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'

export interface TimeSeriesPoint {
  time: string
  netGammaM: number
  price: number
  volumeDelta?: number
}

const props = withDefaults(
  defineProps<{
    symbol?: string
    points?: TimeSeriesPoint[]
    liveSpot?: number | null
  }>(),
  {
    symbol: 'SPY',
    // No default spot. `525.16` is a plausible index level and was used to
    // seed a fabricated series below; a missing spot must read as missing.
    liveSpot: null,
    points: () => [],
  },
)

const hostRef = ref<HTMLDivElement | null>(null)
const { W } = useChartSize(hostRef, { minW: 340, minH: 260, fallbackW: 800, fallbackH: 280 })
const H = 280

const pad = {
  l: 44,
  r: 44,
  t: 20,
  b: 30,
}

const innerW = computed(() => Math.max(100, W.value - pad.l - pad.r))
const innerH = H - pad.t - pad.b

// Only real points are ever plotted.
//
// This computed used to SYNTHESISE a full intraday series when the caller had
// none: fifteen hardcoded clock times, a hand-drawn gamma arc, a price walk of
// `baseSpot + sin(i * 0.8)` seeded from a default 525 spot, and a volume-delta
// bar series of `sin(i * 1.5)`. The result was a complete, plausible,
// entirely fictional chart that a trader could not distinguish from a real
// session -- and it rendered even when the caller correctly supplied an empty
// array, which meant an honest empty upstream was silently overwritten with
// invented data here. See docs/audits/2026-09-01-vwap-orderflow-evaluation.md
// for the wider pattern.
const seriesData = computed<TimeSeriesPoint[]>(() => props.points ?? [])

// Two points are the minimum that can draw a line or a scale; below that every
// downstream computed (`priceMin`/`priceMax`/`timeDomain`) would reduce over an
// empty array and yield +/-Infinity.
const hasData = computed(() => seriesData.value.length >= 2)

const gammaExtent = computed(() => {
  const data = seriesData.value
  if (!data.length) return 100
  let maxAbs = 0
  for (const d of data) {
    if (Number.isFinite(d.netGammaM)) {
      maxAbs = Math.max(maxAbs, Math.abs(d.netGammaM))
    }
  }
  return maxAbs > 0 ? maxAbs * 1.15 : 100
})

const maxGamma = computed(() => gammaExtent.value)
const minGamma = computed(() => -gammaExtent.value)

const priceMin = computed(() => {
  const ps = seriesData.value.map((d) => d.price)
  return Math.min(...ps) * 0.995
})
const priceMax = computed(() => {
  const ps = seriesData.value.map((d) => d.price)
  return Math.max(...ps) * 1.005
})

// The x axis spaces points by index and labels them with the raw time string:
// the upstream history can be daily dates ("2026-08-29") or intraday clock
// strings ("14:35"), so a clock-minute axis cannot be assumed.
const xScale = computed(() => {
  const n = seriesData.value.length
  return (idx: number) => (n <= 1 ? pad.l : pad.l + (idx / (n - 1)) * innerW.value)
})

const timeTicks = computed(() => {
  const n = seriesData.value.length
  if (n < 2) return []
  const maxTicks = 6
  const step = Math.max(1, Math.ceil((n - 1) / (maxTicks - 1)))
  const ticks: { label: string; x: number }[] = []
  for (let i = 0; i < n; i += step)
    ticks.push({ label: seriesData.value[i].time, x: xScale.value(i) })
  if (ticks[ticks.length - 1].x !== xScale.value(n - 1)) {
    ticks.push({ label: seriesData.value[n - 1].time, x: xScale.value(n - 1) })
  }
  return ticks
})

const yGammaScale = computed(() =>
  linearScale([minGamma.value, maxGamma.value], [pad.t + innerH * 0.75, pad.t]),
)

const zeroY = computed(() => yGammaScale.value(0))

const yPriceScale = computed(() =>
  linearScale([priceMin.value, priceMax.value], [pad.t + innerH * 0.75, pad.t]),
)

// Generate Positive & Negative Area Paths
const posAreaPath = computed(() => {
  const data = seriesData.value
  if (data.length < 2) return ''
  const z = zeroY.value

  const pts = data.map((d, i) => {
    const y = d.netGammaM >= 0 ? yGammaScale.value(d.netGammaM) : z
    return { x: xScale.value(i), y }
  })

  const firstX = xScale.value(0)
  const lastX = xScale.value(data.length - 1)
  const line = pts
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(' ')
  return `${line} L ${lastX.toFixed(1)} ${z.toFixed(1)} L ${firstX.toFixed(1)} ${z.toFixed(1)} Z`
})

const negAreaPath = computed(() => {
  const data = seriesData.value
  if (data.length < 2) return ''
  const z = zeroY.value

  const pts = data.map((d, i) => {
    const y = d.netGammaM < 0 ? yGammaScale.value(d.netGammaM) : z
    return { x: xScale.value(i), y }
  })

  const firstX = xScale.value(0)
  const lastX = xScale.value(data.length - 1)
  const line = pts
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(' ')
  return `${line} L ${lastX.toFixed(1)} ${z.toFixed(1)} L ${firstX.toFixed(1)} ${z.toFixed(1)} Z`
})

const priceLinePath = computed(() => {
  const data = seriesData.value
  if (data.length < 2) return ''
  return data
    .map(
      (d, i) =>
        `${i === 0 ? 'M' : 'L'} ${xScale.value(i).toFixed(1)} ${yPriceScale.value(d.price).toFixed(1)}`,
    )
    .join(' ')
})

// "Now" is the most recent observation, i.e. the last plotted point. A
// hardcoded index crashed the render whenever the history was shorter.
const nowX = computed(() => xScale.value(seriesData.value.length - 1))

const leftYTicks = computed(() => {
  const max = gammaExtent.value
  return niceTicks(-max, max, 5)
})
const rightYTicks = computed(() => niceTicks(priceMin.value, priceMax.value, 5))

function formatGammaTick(v: number): string {
  if (v === 0) return '$0'
  const sign = v > 0 ? '+' : '-'
  const abs = Math.abs(v)
  if (abs >= 1000) {
    return `${sign}$${(abs / 1000).toFixed(1)}B`
  }
  return `${sign}$${abs.toFixed(0)}M`
}
</script>

<template>
  <div class="net-gamma-spot-card">
    <div class="card-header">
      <div class="title-group">
        <span class="card-title font-mono font-bold">NET GAMMA &amp; SPOT PRICE</span>
        <div class="view-mode-pill font-mono">
          <span class="text-ink-dim">Show:</span>
          <span class="mode-text">Net Gamma</span>
        </div>
      </div>

      <div class="legend-group">
        <span class="leg-item font-mono"><i class="leg-line call"></i> Net Gamma</span>
        <span class="leg-item font-mono"><i class="leg-line put"></i> Net Gamma (Negative)</span>
        <span class="leg-item font-mono"><i class="leg-line price"></i> {{ symbol }} Price</span>
        <span class="leg-item font-mono"><i class="leg-line zero"></i> Zero Line</span>
      </div>
    </div>

    <!-- Chart Frame -->
    <div ref="hostRef" class="chart-frame">
      <div v-if="!hasData" class="chart-empty font-mono">
        <span class="empty-dash">&mdash;</span>
        <span class="empty-text">No net-gamma history for {{ symbol }}</span>
      </div>
      <svg
        v-else
        class="timeseries-svg"
        role="img"
        :aria-label="`Net dealer gamma against spot price over time.`"
        :viewBox="`0 0 ${W} ${H}`"
        preserveAspectRatio="none"
      >
        <title>{{ `Net dealer gamma against spot price over time.` }}</title>
        <defs>
          <linearGradient id="ng-pos-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="var(--call)" stop-opacity="0.5" />
            <stop offset="100%" stop-color="var(--call)" stop-opacity="0.05" />
          </linearGradient>
          <linearGradient id="ng-neg-grad" x1="0" y1="1" x2="0" y2="0">
            <stop offset="0%" stop-color="var(--put)" stop-opacity="0.5" />
            <stop offset="100%" stop-color="var(--put)" stop-opacity="0.05" />
          </linearGradient>
        </defs>

        <!-- Zero Horizontal Line -->
        <line
          :x1="pad.l"
          :x2="pad.l + innerW"
          :y1="zeroY"
          :y2="zeroY"
          stroke="var(--rule-hi)"
          stroke-width="1.5"
          stroke-dasharray="3 3"
        />

        <!-- Positive Gamma Filled Area -->
        <path :d="posAreaPath" fill="url(#ng-pos-grad)" />

        <!-- Negative Gamma Filled Area -->
        <path :d="negAreaPath" fill="url(#ng-neg-grad)" />

        <!-- SPY Price Trace -->
        <path
          :d="priceLinePath"
          fill="none"
          stroke="var(--ink)"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />

        <!-- Volume / Delta Bars at bottom -->
        <g v-for="(d, i) in seriesData" :key="`vol-${i}`">
          <rect
            :x="xScale(i) - 2"
            :y="pad.t + innerH - Math.min(24, Math.abs(d.volumeDelta ?? 10) * 0.4)"
            width="4"
            :height="Math.min(24, Math.abs(d.volumeDelta ?? 10) * 0.4)"
            :fill="(d.volumeDelta ?? 0) >= 0 ? 'var(--call)' : 'var(--put)'"
            opacity="0.75"
          />
        </g>

        <!-- Vertical 'Now' Marker -->
        <line
          :x1="nowX"
          :x2="nowX"
          :y1="pad.t"
          :y2="pad.t + innerH"
          stroke="var(--phosphor)"
          stroke-width="1.5"
          stroke-dasharray="3 3"
        />
        <text :x="nowX" :y="pad.t - 4" text-anchor="middle" class="now-tag font-mono font-bold">
          Now
        </text>

        <!-- Left Y-Axis (Gamma) -->
        <g v-for="v in leftYTicks" :key="`g-${v}`">
          <text
            :x="pad.l - 6"
            :y="yGammaScale(v) + 3"
            text-anchor="end"
            class="axis-tick font-mono"
          >
            {{ formatGammaTick(v) }}
          </text>
        </g>

        <!-- Right Y-Axis (Price $) -->
        <g v-for="p in rightYTicks" :key="`p-${p}`">
          <text
            :x="pad.l + innerW + 6"
            :y="yPriceScale(p) + 3"
            text-anchor="start"
            class="axis-tick font-mono"
          >
            ${{ num(p, 0) }}
          </text>
        </g>

        <!-- Bottom X-Axis (Time) -->
        <g v-for="(t, ti) in timeTicks" :key="`x-${ti}`">
          <text :x="t.x" :y="pad.t + innerH + 16" text-anchor="middle" class="axis-tick font-mono">
            {{ t.label }}
          </text>
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.net-gamma-spot-card {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: 0.875rem 1rem;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 0.5rem;
  box-sizing: border-box;
  overflow: hidden;
  min-width: 0;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.title-group {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.card-title {
  font-size: 0.8125rem;
  letter-spacing: 0.05em;
  color: var(--ink);
}

.view-mode-pill {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: var(--t-micro);
  background: var(--panel-hi);
  padding: 0.125rem 0.375rem;
  border-radius: var(--r-xs);
}

.mode-text {
  color: var(--ink-soft);
  font-weight: 600;
}

.legend-group {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  flex-wrap: wrap;
}

.leg-item {
  font-size: var(--t-nano);
  color: var(--ink-dim);
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.leg-line {
  width: 10px;
  height: 2px;
  display: inline-block;
}

.leg-line.call {
  background: var(--call);
}

.leg-line.put {
  background: var(--put);
}

.leg-line.price {
  background: var(--ink);
}

.leg-line.zero {
  background: var(--rule-hi);
}

.chart-frame {
  width: 100%;
  height: 260px;
  position: relative;
}

/* Honest empty state: an em dash for the missing number, per the repo
   convention that an unavailable value is never rendered as a plausible one. */
.chart-empty {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--ink-dim);
  font-size: 12px;
  text-align: center;
}

.chart-empty .empty-dash {
  font-size: 22px;
  line-height: 1;
  opacity: 0.55;
}

.timeseries-svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}

.axis-tick {
  font-size: var(--t-nano);
  fill: var(--ink-faint);
}

.now-tag {
  font-size: var(--t-nano);
  fill: var(--phosphor);
}
</style>
