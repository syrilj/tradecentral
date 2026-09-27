<script setup lang="ts">
import { computed, ref } from 'vue'
import type { GexStrikeRow } from '@/api'
import { num, optSigned, DASH } from '@/format'
import { linearScale, niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'

const props = withDefaults(
  defineProps<{
    rows: GexStrikeRow[]
    spot?: number | null
    totalGexM?: number | null
    gammaFlip?: number | null
    callWall?: number | null
    putWall?: number | null
  }>(),
  {
    spot: null,
    totalGexM: null,
    gammaFlip: null,
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
// This component used to synthesise an eleven-strike dealer-gamma ladder
// around spot whenever `rows` was empty, shaping it with
// `140 * Math.exp(-dist * 18)` and manufacturing per-strike open interest from
// that number. It defaulted spot to 525, so it drew an index-like strike
// ladder for any symbol. Dealer gamma exposure is computed from a real option
// chain; a symbol with no chain has no gamma profile, and that must render as
// absent rather than as a smooth, authoritative-looking curve.
// See docs/audits/2026-09-01-vwap-orderflow-evaluation.md.

const effectiveSpot = computed(() => {
  if (props.spot != null && props.spot > 0) return props.spot
  if (props.rows.length > 0) {
    const sorted = [...props.rows].map((r) => r.strike).sort((a, b) => a - b)
    return sorted[Math.floor(sorted.length / 2)]
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
  const step = Math.max(1, Math.floor(rows.length / 6))
  const set = new Set<number>()
  set.add(rows[0].strike)
  set.add(rows[rows.length - 1].strike)
  for (let i = step; i < rows.length - 1; i += step) set.add(rows[i].strike)
  // Nearest strike to spot
  const s = effectiveSpot.value
  if (s != null) {
    let nearest = rows[0].strike
    let minD = Math.abs(nearest - s)
    for (const r of rows) {
      const d = Math.abs(r.strike - s)
      if (d < minD) {
        minD = d
        nearest = r.strike
      }
    }
    set.add(nearest)
  }
  return set
})

const maxAbsGex = computed(() => {
  let m = 1
  for (const r of visibleRows.value) {
    m = Math.max(m, Math.abs(r.call_gex_m ?? 0), Math.abs(r.put_gex_m ?? 0))
  }
  return m * 1.1
})

const xScale = computed(() =>
  linearScale([-maxAbsGex.value, maxAbsGex.value], [pad.l, pad.l + innerW.value]),
)

const zeroX = computed(() => xScale.value(0))

const yScale = computed(() => {
  const n = visibleRows.value.length
  return (idx: number) => pad.t + (idx / Math.max(1, n - 1)) * innerH
})

const rowHeight = computed(() => {
  const n = visibleRows.value.length
  if (n <= 1) return 8
  return Math.max(3, Math.min(14, (innerH / n) * 0.65))
})

// Spot line Y (continuous interpolation between top & bottom strikes)
const spotY = computed(() => {
  const s = effectiveSpot.value
  if (s == null || !visibleRows.value.length) return null
  const topStrike = visibleRows.value[0].strike
  const btmStrike = visibleRows.value[visibleRows.value.length - 1].strike
  if (s < btmStrike || s > topStrike) return null
  const span = topStrike - btmStrike || 1
  return pad.t + ((topStrike - s) / span) * innerH
})

const hoveredStrike = ref<number | null>(null)

const subtitle = computed(() => {
  if (props.gammaFlip != null && props.putWall != null) {
    return `GEX flips positive above $${num(props.gammaFlip, 0)} and turns strongly negative below $${num(props.putWall, 0)}.`
  }
  if (props.gammaFlip != null) {
    return `GEX zero-flip located at $${num(props.gammaFlip, 0)}.`
  }
  return 'Gamma flip level unmeasured across quoted strike range.'
})

const tickCount = computed(() => Math.max(3, Math.min(5, Math.floor(innerW.value / 72))))

const xTicks = computed(() => {
  const max = maxAbsGex.value
  return niceTicks(-max, max, tickCount.value).map((v) => ({
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
  <div class="strike-gex-card">
    <div class="card-header">
      <div class="title-group">
        <span class="card-title font-mono font-bold">
          GAMMA EXPOSURE
          <span
            class="total-pill font-mono font-semibold"
            :class="(totalGexM ?? 0) >= 0 ? 'text-call-hi' : 'text-put-hi'"
          >
            (Total: {{ totalGexM != null ? `${optSigned(totalGexM, 1)}M` : DASH }})
          </span>
        </span>
      </div>
      <div class="legend-group">
        <span class="leg-item font-mono"><i class="leg-dot put"></i> Negative Gamma</span>
        <span class="leg-item font-mono"><i class="leg-dot call"></i> Positive Gamma</span>
        <span class="leg-item font-mono"><i class="leg-line spot"></i> Spot Price</span>
      </div>
    </div>

    <!-- Chart Frame -->
    <div ref="hostRef" class="chart-frame">
      <div v-if="!hasRows" class="chart-empty font-mono">
        <span class="empty-dash">&mdash;</span>
        <span class="empty-text">No dealer-gamma chain data</span>
      </div>
      <svg
        v-else
        class="gex-svg"
        role="img"
        :aria-label="`Dealer gamma exposure by strike. ${subtitle}`"
        :viewBox="`0 0 ${W} ${H}`"
        preserveAspectRatio="none"
      >
        <title>{{ `Dealer gamma exposure by strike. ${subtitle}` }}</title>
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

          <!-- Net GEX Bar -->
          <rect
            v-if="row.net_gex_m >= 0"
            :x="zeroX"
            :y="yScale(idx) - rowHeight / 2"
            :width="Math.max(1, xScale(row.net_gex_m) - zeroX)"
            :height="rowHeight"
            fill="var(--call)"
            rx="1.5"
            class="bar-call"
            @mouseenter="hoveredStrike = row.strike"
            @mouseleave="hoveredStrike = null"
          />
          <rect
            v-else
            :x="xScale(row.net_gex_m)"
            :y="yScale(idx) - rowHeight / 2"
            :width="Math.max(1, zeroX - xScale(row.net_gex_m))"
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
      <span class="sub-caption font-mono text-ink-dim">{{ subtitle }}</span>
    </div>
  </div>
</template>

<style scoped>
.strike-gex-card {
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
}

.card-title {
  font-size: 0.8125rem;
  letter-spacing: 0.05em;
  color: var(--ink);
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.total-pill {
  font-size: 0.75rem;
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

.gex-svg {
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
