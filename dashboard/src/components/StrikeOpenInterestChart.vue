<script setup lang="ts">
import { computed, ref } from 'vue'
import { num, compact } from '@/format'
import { linearScale, niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'

export interface StrikeOiPoint {
  strike: number
  call_oi: number
  put_oi: number
  total_oi?: number
}

const props = withDefaults(
  defineProps<{
    rows: StrikeOiPoint[]
    spot?: number | null
    expiryLabel?: string | null
    callWall?: number | null
    putWall?: number | null
  }>(),
  {
    spot: null,
    // No default expiry. `'May 17 Exp'` labelled every chart with a fixed
    // fake date whenever the real expiry was unknown, including on charts
    // built from real open interest for a different expiry entirely.
    expiryLabel: null,
    callWall: null,
    putWall: null,
  },
)

const hostRef = ref<HTMLDivElement | null>(null)
const { W } = useChartSize(hostRef, { minW: 280, minH: 220, fallbackW: 400, fallbackH: 240 })
const H = 240

const pad = {
  l: 36,
  r: 44,
  t: 20,
  b: 28,
}

const innerW = computed(() => Math.max(100, W.value - pad.l - pad.r))
const innerH = H - pad.t - pad.b

// There is deliberately no fallback row generator.
//
// This component used to synthesise an eleven-strike ladder around spot
// whenever `rows` was empty, with open interest drawn from
// `Math.round(18000 + Math.random() * 12000)`. Because it used `Math.random()`
// the fabricated contract counts changed on every render, and because it
// defaulted spot to 525 it drew an index-like strike ladder for any symbol.
// A caller that correctly passed an empty array -- meaning "we have no open
// interest for this symbol" -- had that honest empty silently replaced with
// invented position data. See docs/audits/2026-09-01-vwap-orderflow-evaluation.md.

const effectiveSpot = computed(() => {
  if (props.spot != null) return props.spot
  if (props.rows.length > 0) {
    return props.rows[Math.floor(props.rows.length / 2)].strike
  }
  return null
})

const hasRows = computed(() => props.rows.length > 0 && effectiveSpot.value != null)

// Filter strikes near spot
const visibleRows = computed(() => {
  const s = effectiveSpot.value
  if (!props.rows.length || s == null) return []
  const filtered = props.rows.filter((r) => r.strike >= s * 0.94 && r.strike <= s * 1.06)
  const list = filtered.length >= 6 ? filtered : props.rows
  return [...list].sort((a, b) => b.strike - a.strike) // top is highest strike
})

// Sparse strike labels (~6-8): round-number steps, always both extremes + the spot strike
const labeledStrikes = computed(() => {
  const rows = visibleRows.value
  if (rows.length <= 8) return new Set(rows.map((r) => r.strike))
  const min = rows[rows.length - 1].strike
  const max = rows[0].strike
  const span = max - min
  let step = 100
  for (const cand of [1, 2, 5, 10, 20, 25, 50, 100]) {
    if (span / cand <= 8) {
      step = cand
      break
    }
  }
  const set = new Set<number>([min, max])
  for (let k = Math.ceil(min / step) * step; k <= max; k += step) set.add(k)
  if (effectiveSpot.value != null) {
    let nearest = rows[0]
    for (const r of rows) {
      if (Math.abs(r.strike - effectiveSpot.value) < Math.abs(nearest.strike - effectiveSpot.value))
        nearest = r
    }
    set.add(nearest.strike)
  }
  return set
})

const maxOi = computed(() => {
  const vals = visibleRows.value.flatMap((r) => [r.call_oi ?? 0, r.put_oi ?? 0])
  return Math.max(100, ...vals)
})

const xScale = computed(() =>
  linearScale([-maxOi.value, maxOi.value], [pad.l, pad.l + innerW.value]),
)

const zeroX = computed(() => xScale.value(0))

const yScale = computed(() => {
  const n = visibleRows.value.length
  return (idx: number) => pad.t + (idx / Math.max(1, n - 1)) * innerH
})

const rowHeight = computed(() => {
  const n = visibleRows.value.length
  if (n <= 1) return 12
  return Math.max(4, Math.min(14, (innerH / n) * 0.7))
})

const spotY = computed(() => {
  const s = effectiveSpot.value
  if (s == null || visibleRows.value.length < 2) return null
  const rows = visibleRows.value
  const topStrike = rows[0].strike
  const btmStrike = rows[rows.length - 1].strike
  if (s < btmStrike || s > topStrike) return null
  const span = topStrike - btmStrike || 1
  return pad.t + ((topStrike - s) / span) * innerH
})

const hoveredStrike = ref<number | null>(null)

const subtitle = computed(() => {
  // Only state where the concentration is when both walls are actually known.
  // The previous defaults ('525C' / '520P') asserted a specific, invented
  // concentration for any symbol whose walls had not been computed -- and this
  // string is also the chart's aria-label, so a screen reader was read a
  // fabricated fact as though it were the measurement.
  if (props.callWall == null || props.putWall == null) {
    return 'Open interest by strike. Call and put wall concentration not available.'
  }
  return `Highest OI concentration at ${num(props.callWall, 0)} and ${num(props.putWall, 0)}.`
})

const tickCount = computed(() => Math.max(3, Math.min(5, Math.floor(innerW.value / 72))))

const xTicks = computed(() => {
  const max = maxOi.value
  return niceTicks(0, max, tickCount.value).map((v) => ({
    val: v,
    x: xScale.value(v),
  }))
})

// Keep the spot label inside the viewBox on narrow cards
const spotLabelX = computed(() => {
  const s = effectiveSpot.value
  const label = s != null ? `$${num(s, 2)}` : ''
  return Math.min(pad.l + innerW.value + 4, W.value - label.length * 4.3)
})
</script>

<template>
  <div class="strike-oi-card">
    <div class="card-header">
      <div class="title-group">
        <span class="card-title font-mono font-bold">
          OPEN INTEREST BY STRIKE
          <span v-if="expiryLabel" class="expiry-pill font-mono font-normal text-ink-dim">
            ({{ expiryLabel }})
          </span>
        </span>
      </div>
      <div class="legend-group">
        <span class="leg-item font-mono"><i class="leg-dot put"></i> Puts OI</span>
        <span class="leg-item font-mono"><i class="leg-dot call"></i> Calls OI</span>
        <span class="leg-item font-mono"><i class="leg-line spot"></i> Spot Price</span>
      </div>
    </div>

    <!-- Chart Frame -->
    <div ref="hostRef" class="chart-frame">
      <div v-if="!hasRows" class="chart-empty font-mono">
        <span class="empty-dash">&mdash;</span>
        <span class="empty-text">No open-interest data</span>
      </div>
      <svg
        v-else
        class="oi-svg"
        role="img"
        :aria-label="`Open interest by strike. ${subtitle}`"
        :viewBox="`0 0 ${W} ${H}`"
        preserveAspectRatio="none"
      >
        <title>{{ `Open interest by strike. ${subtitle}` }}</title>
        <!-- Zero baseline -->
        <line
          :x1="zeroX"
          :x2="zeroX"
          :y1="pad.t"
          :y2="pad.t + innerH"
          stroke="var(--rule-hi)"
          stroke-width="1.5"
        />

        <!-- Horizontal grid / bars -->
        <g v-for="(row, idx) in visibleRows" :key="row.strike">
          <!-- Strike Y-axis label -->
          <text
            v-if="labeledStrikes.has(row.strike)"
            :x="pad.l - 6"
            :y="yScale(idx) + rowHeight / 2 - 1"
            text-anchor="end"
            class="strike-axis font-mono"
            :class="{ 'text-phosphor font-bold': Math.abs(row.strike - (spot ?? 0)) < 2.5 }"
          >
            {{ num(row.strike, 0) }}
          </text>

          <!-- Calls OI Bar (Right) -->
          <rect
            :x="zeroX"
            :y="yScale(idx) - rowHeight / 2"
            :width="Math.max(0, xScale(row.call_oi) - zeroX)"
            :height="rowHeight"
            fill="var(--call)"
            rx="1.5"
            class="bar-call"
            @mouseenter="hoveredStrike = row.strike"
            @mouseleave="hoveredStrike = null"
          />

          <!-- Puts OI Bar (Left) -->
          <rect
            :x="xScale(-row.put_oi)"
            :y="yScale(idx) - rowHeight / 2"
            :width="Math.max(0, zeroX - xScale(-row.put_oi))"
            :height="rowHeight"
            fill="var(--put)"
            rx="1.5"
            class="bar-put"
            @mouseenter="hoveredStrike = row.strike"
            @mouseleave="hoveredStrike = null"
          />
        </g>

        <!-- Horizontal Spot Price Line -->
        <g v-if="spotY != null">
          <line
            :x1="pad.l"
            :x2="pad.l + innerW"
            :y1="spotY"
            :y2="spotY"
            stroke="var(--phosphor)"
            stroke-width="1.5"
            stroke-dasharray="4 3"
          />
          <!-- Spot label on right -->
          <text
            :x="spotLabelX"
            :y="spotY + 3.5"
            text-anchor="start"
            class="spot-badge font-mono font-bold"
          >
            {{ spot != null ? `$${num(spot, 2)}` : '' }}
          </text>
        </g>

        <!-- Bottom X-axis ticks (Calls side) -->
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
            {{ compact(t.val) }}
          </text>
        </g>
      </svg>
    </div>

    <!-- Subtitle caption -->
    <div class="card-footer">
      <span class="sub-caption font-mono text-ink-dim">{{ subtitle }}</span>
    </div>
  </div>
</template>

<style scoped>
.strike-oi-card {
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
  gap: 0.5rem;
  flex-wrap: wrap;
  min-width: 0;
}

.title-group {
  min-width: 0;
}

.card-title {
  font-size: 0.8125rem;
  letter-spacing: 0.05em;
  color: var(--ink);
  display: flex;
  align-items: center;
  gap: 0.375rem;
  flex-wrap: wrap;
}

.expiry-pill {
  font-size: 0.75rem;
  white-space: normal;
  overflow-wrap: anywhere;
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

.leg-line.spot {
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

.oi-svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}

.strike-axis {
  font-size: var(--t-nano);
  fill: var(--ink-dim);
}

.x-axis-tick {
  font-size: var(--t-nano);
  fill: var(--ink-faint);
}

.spot-badge {
  font-size: var(--t-micro);
  fill: var(--phosphor);
}

.bar-call {
  transition: opacity var(--dur-fast) ease;
}

.bar-call:hover {
  fill: var(--call-hi);
}

.bar-put {
  transition: opacity var(--dur-fast) ease;
}

.bar-put:hover {
  fill: var(--put-hi);
}

.card-footer {
  padding-top: 0.25rem;
  border-top: 1px solid var(--rule-faint);
}

.sub-caption {
  font-size: var(--t-micro);
}
</style>
