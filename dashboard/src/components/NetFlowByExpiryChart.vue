<script setup lang="ts">
import { computed, ref } from 'vue'
import { num, optSigned } from '@/format'
import { linearScale, niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'

export interface ExpiryFlowRow {
  expiry: string
  dte: number | null
  call_premium?: number
  put_premium?: number
  net_flow?: number
  bullish_flow_m?: number
  bearish_flow_m?: number
}

const props = withDefaults(
  defineProps<{
    rows?: ExpiryFlowRow[]
  }>(),
  {
    // No demo expiries — an absent flow read renders an empty chart, not
    // invented numbers.
    rows: () => [],
  },
)

const hostRef = ref<HTMLDivElement | null>(null)
const { W } = useChartSize(hostRef, { minW: 280, minH: 220, fallbackW: 400, fallbackH: 240 })
const H = 240

// Long enough for a full ISO date + DTE on the left and a signed 7-char
// net-flow readout on the right without clipping either edge.
const pad = {
  l: 112,
  r: 96,
  t: 20,
  b: 28,
}

const innerW = computed(() => Math.max(100, W.value - pad.l - pad.r))
const innerH = H - pad.t - pad.b

const displayRows = computed(() => {
  return props.rows.slice(0, 6)
})

function rowBullish(r: ExpiryFlowRow): number {
  return r.bullish_flow_m ?? (r.call_premium ? r.call_premium / 1e6 : 0)
}

function rowBearish(r: ExpiryFlowRow): number {
  return r.bearish_flow_m ?? (r.put_premium ? r.put_premium / 1e6 : 0)
}

function rowNetFlow(r: ExpiryFlowRow): number {
  if (r.net_flow != null && Number.isFinite(r.net_flow)) return r.net_flow
  return rowBullish(r) - rowBearish(r)
}

const maxFlowM = computed(() => {
  let peak = 1
  for (const r of displayRows.value) {
    const b = rowBullish(r)
    const br = rowBearish(r)
    const net = Math.abs(rowNetFlow(r))
    peak = Math.max(peak, b, br, net)
  }
  return peak * 1.15
})

const xScale = computed(() =>
  linearScale([-maxFlowM.value, maxFlowM.value], [pad.l, pad.l + innerW.value]),
)

const zeroX = computed(() => xScale.value(0))

const yScale = computed(() => {
  const n = displayRows.value.length
  // A single expiry still gets a full-height, vertically centred row so the
  // bars read as bars instead of a squashed sliver pinned to the top edge.
  if (n <= 1) return () => pad.t + innerH / 2
  return (idx: number) => pad.t + (idx / (n - 1)) * innerH
})

const rowHeight = computed(() => {
  const n = displayRows.value.length
  if (n <= 1) return 20
  return Math.max(6, Math.min(18, (innerH / n) * 0.55))
})

// Net curve spline path
const netCurvePath = computed(() => {
  const pts = displayRows.value.map((r, idx) => {
    const net = rowNetFlow(r)
    return {
      x: xScale.value(net),
      y: yScale.value(idx),
    }
  })
  if (pts.length < 2) return ''
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
})

const xTicks = computed(() => {
  const max = maxFlowM.value
  return niceTicks(-max, max, 5).map((v) => ({
    val: v,
    x: xScale.value(v),
  }))
})

const chartCaption = computed(() => {
  if (!displayRows.value.length) return 'No expiry flow data'
  let totalNet = 0
  let nearTermNet = 0
  let datedNet = 0
  for (const r of displayRows.value) {
    const net = rowNetFlow(r)
    totalNet += net
    const dte = r.dte ?? 0
    if (dte <= 7) nearTermNet += net
    else datedNet += net
  }
  if (Math.abs(totalNet) < 0.05) {
    return 'Balanced net flow across visible expiries.'
  }
  const side = totalNet > 0 ? 'Bullish' : 'Bearish'
  if (
    Math.abs(nearTermNet) > Math.abs(datedNet) &&
    ((nearTermNet > 0 && totalNet > 0) || (nearTermNet < 0 && totalNet < 0))
  ) {
    return `${side} flow concentrated in near-term expiries.`
  }
  if (
    Math.abs(datedNet) > Math.abs(nearTermNet) &&
    ((datedNet > 0 && totalNet > 0) || (datedNet < 0 && totalNet < 0))
  ) {
    return `${side} flow concentrated in dated expiries.`
  }
  return `${side} net flow across visible expiries.`
})
</script>

<template>
  <div class="net-flow-expiry-card">
    <div class="card-header">
      <div class="title-group">
        <span class="card-title font-mono font-bold">NET FLOW BY EXPIRY</span>
      </div>
      <div class="legend-group">
        <span class="leg-item font-mono"><i class="leg-dot call"></i> Bullish Flow</span>
        <span class="leg-item font-mono"><i class="leg-dot put"></i> Bearish Flow</span>
        <span class="leg-item font-mono"><i class="leg-line purple"></i> Net Flow</span>
      </div>
    </div>

    <!-- Chart Frame -->
    <div ref="hostRef" class="chart-frame">
      <div v-if="!displayRows.length" class="chart-empty font-mono">
        <span class="empty-dash">&mdash;</span>
        <span class="empty-text">No expiry flow data</span>
      </div>
      <svg
        v-else
        class="flow-svg"
        role="img"
        :aria-label="`Net options flow by expiry.`"
        :viewBox="`0 0 ${W} ${H}`"
        preserveAspectRatio="none"
      >
        <title>{{ `Net options flow by expiry.` }}</title>
        <!-- Zero baseline -->
        <line
          :x1="zeroX"
          :x2="zeroX"
          :y1="pad.t"
          :y2="pad.t + innerH"
          stroke="var(--rule-hi)"
          stroke-width="1.5"
        />

        <!-- Diverging Bars for each Expiry -->
        <g v-for="(row, idx) in displayRows" :key="row.expiry">
          <!-- Expiry Y-axis label -->
          <text
            :x="pad.l - 8"
            :y="yScale(idx) + rowHeight / 2 - 1"
            text-anchor="end"
            class="expiry-axis font-mono"
          >
            {{ row.expiry }}
            <tspan class="dte-sub font-mono text-ink-dim">
              ({{ row.dte != null ? `${row.dte}D` : '' }})
            </tspan>
          </text>

          <!-- Bullish Flow (Right) -->
          <rect
            :x="zeroX"
            :y="yScale(idx) - rowHeight / 2"
            :width="Math.max(0, xScale(rowBullish(row)) - zeroX)"
            :height="rowHeight"
            fill="var(--call)"
            rx="1.5"
            opacity="0.85"
          />

          <!-- Bearish Flow (Left) -->
          <rect
            :x="xScale(-rowBearish(row))"
            :y="yScale(idx) - rowHeight / 2"
            :width="Math.max(0, zeroX - xScale(-rowBearish(row)))"
            :height="rowHeight"
            fill="var(--put)"
            rx="1.5"
            opacity="0.85"
          />

          <!-- Net Flow Value Label: anchored inside the right margin so the
               full signed readout never clips at the card edge. -->
          <text
            :x="pad.l + innerW + 8"
            :y="yScale(idx) + 3.5"
            text-anchor="start"
            class="net-label font-mono font-bold"
            :class="rowNetFlow(row) >= 0 ? 'text-call-hi' : 'text-put-hi'"
          >
            {{ optSigned(rowNetFlow(row), 1) }}M
          </text>
        </g>

        <!-- Net Flow Overlay Line -->
        <path
          v-if="netCurvePath"
          :d="netCurvePath"
          fill="none"
          stroke="var(--phosphor)"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />

        <!-- Net Flow Points -->
        <g v-for="(row, idx) in displayRows" :key="`pt-${row.expiry}`">
          <circle
            :cx="xScale(rowNetFlow(row))"
            :cy="yScale(idx)"
            r="3.5"
            fill="var(--phosphor)"
            stroke="var(--panel)"
            stroke-width="1.5"
          />
        </g>

        <!-- Bottom X-axis ticks -->
        <g v-for="t in xTicks" :key="t.val">
          <line
            :x1="t.x"
            :x2="t.x"
            :y1="pad.t + innerH"
            :y2="pad.t + innerH + 4"
            stroke="var(--rule)"
          />
          <text
            :x="t.x"
            :y="pad.t + innerH + 16"
            text-anchor="middle"
            class="x-axis-tick font-mono"
          >
            {{ t.val === 0 ? '0' : `${t.val > 0 ? '+' : ''}$${num(Math.abs(t.val), 0)}M` }}
          </text>
        </g>
      </svg>
    </div>

    <!-- Subtitle caption -->
    <div class="card-footer">
      <span class="sub-caption font-mono text-ink-dim">{{ chartCaption }}</span>
    </div>
  </div>
</template>

<style scoped>
.net-flow-expiry-card {
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
  height: 100%;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.card-title {
  font-size: 0.8125rem;
  letter-spacing: 0.05em;
  color: var(--ink);
}

.legend-group {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.leg-item {
  font-size: var(--t-nano);
  color: var(--ink-dim);
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.leg-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}

.leg-dot.call {
  background: var(--call);
}

.leg-dot.put {
  background: var(--put);
}

.leg-line.purple {
  width: 10px;
  height: 2px;
  background: var(--phosphor);
  display: inline-block;
}

.chart-frame {
  width: 100%;
  height: 240px;
  position: relative;
}

.chart-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 160px;
  gap: var(--s2);
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.empty-dash {
  font-size: var(--t-display);
  line-height: 1;
}

.flow-svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}

.expiry-axis {
  font-size: var(--t-micro);
  fill: var(--ink);
}

.dte-sub {
  font-size: var(--t-nano);
  fill: var(--ink-dim);
}

.net-label {
  font-size: var(--t-micro);
  fill: var(--ink);
}

.x-axis-tick {
  font-size: var(--t-nano);
  fill: var(--ink-faint);
}

.card-footer {
  padding-top: 0.25rem;
  border-top: 1px solid var(--rule-faint);
}

.sub-caption {
  font-size: var(--t-micro);
}
</style>
