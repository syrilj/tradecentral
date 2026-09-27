<script setup lang="ts">
/**
 * Theta decay + vanna exposure by strike.
 *   · Theta bars  = option-price points/day bleeding out of each strike
 *     (both sides negative for long premium; deeper bar = faster decay)
 *   · Vanna trace = net dealer delta shares per +1 vol point (call +/put −
 *     dealer convention). Positive trace → rising IV lifts dealer delta
 *     (dealers buy dips); negative → rising IV forces dealer selling.
 * Two stacked panes share one strike axis so the decay map and the vol
 * sensitivity map read against the same strikes.
 */
import { computed, ref } from 'vue'
import type { ThetaVannaStrikeRow } from '@/api'
import { linearScale } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'
import { compact, num, signed } from '@/format'

const props = withDefaults(
  defineProps<{
    rows: ThetaVannaStrikeRow[]
    spot?: number | null
    callWall?: number | null
    putWall?: number | null
    gammaFlip?: number | null
    callIvWall?: number | null
    putIvWall?: number | null
  }>(),
  {
    spot: null,
    callWall: null,
    putWall: null,
    gammaFlip: null,
    callIvWall: null,
    putIvWall: null,
  },
)

const hostRef = ref<HTMLDivElement | null>(null)
const { W } = useChartSize(hostRef, {
  minW: 280,
  minH: 240,
  fallbackW: 900,
  fallbackH: 320,
})
const H = computed(() => Math.max(240, W.value * 0.34))

const pad = computed(() => ({
  l: W.value < 480 ? 52 : 64,
  r: W.value < 480 ? 12 : 18,
  t: 22,
  gap: 26,
  b: 26,
}))

const thetaH = computed(() => (H.value - pad.value.t - pad.value.b - pad.value.gap) * 0.62)
const vannaTop = computed(() => pad.value.t + thetaH.value + pad.value.gap)
const vannaH = computed(() => H.value - pad.value.b - vannaTop.value)

const ordered = computed(() =>
  [...props.rows].filter((r) => Number.isFinite(r.strike)).sort((a, b) => a.strike - b.strike),
)

const strikeDomain = computed(() => {
  const strikes = ordered.value.map((r) => r.strike)
  if (!strikes.length) return { lo: 0, hi: 1 }
  const lo = Math.min(...strikes)
  const hi = Math.max(...strikes)
  if (lo === hi) return { lo: lo - 1, hi: hi + 1 }
  const padAmt = (hi - lo) * 0.05
  return { lo: lo - padAmt, hi: hi + padAmt }
})

const xScale = computed(() =>
  linearScale([strikeDomain.value.lo, strikeDomain.value.hi], [pad.value.l, W.value - pad.value.r]),
)

const barWidth = computed(() => {
  const n = ordered.value.length
  if (n <= 1) return 16
  let minDx = Infinity
  for (let i = 1; i < n; i++) {
    const dx = Math.abs(
      xScale.value(ordered.value[i]!.strike) - xScale.value(ordered.value[i - 1]!.strike),
    )
    if (dx > 0 && dx < minDx) minDx = dx
  }
  if (!Number.isFinite(minDx)) return 12
  return Math.max(5, Math.min(22, Math.floor(minDx * 0.72)))
})

/* ---- theta pane: bars below the baseline (decay is a cost) ------------- */
const thetaMax = computed(() =>
  Math.max(1, ...ordered.value.map((r) => Math.abs(r.net_theta_flow))),
)
const thetaBaseY = computed(() => pad.value.t + 14)
const thetaScale = computed(() => linearScale([0, thetaMax.value], [0, thetaH.value - 14]))

/* ---- vanna pane: zero midline, signed trace ---------------------------- */
const vannaMax = computed(() =>
  Math.max(1, ...ordered.value.map((r) => Math.abs(r.net_vanna_flow))),
)
const vannaZeroY = computed(() => vannaTop.value + vannaH.value / 2)
const vannaScale = computed(() =>
  linearScale([-vannaMax.value, vannaMax.value], [vannaTop.value + vannaH.value, vannaTop.value]),
)

const vannaPath = computed(() => {
  const pts = ordered.value.map((r) => ({
    x: xScale.value(r.strike),
    y: vannaScale.value(r.net_vanna_flow),
  }))
  if (!pts.length) return ''
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
})

interface Marker {
  value: number
  label: string
  cls: string
}
function markers(): Marker[] {
  const out: Marker[] = []
  if (props.putWall != null) out.push({ value: props.putWall, label: 'PUT W', cls: 'put' })
  if (props.putIvWall != null && props.putIvWall !== props.putWall)
    out.push({ value: props.putIvWall, label: 'IV W', cls: 'put-dim' })
  if (props.gammaFlip != null) out.push({ value: props.gammaFlip, label: 'FLIP', cls: 'warn' })
  if (props.callIvWall != null && props.callIvWall !== props.callWall)
    out.push({ value: props.callIvWall, label: 'IV W', cls: 'call-dim' })
  if (props.callWall != null) out.push({ value: props.callWall, label: 'CALL W', cls: 'call' })
  return out
}
const levelMarkers = computed(markers)

const spotX = computed(() => {
  const s = props.spot
  if (s == null || s < strikeDomain.value.lo || s > strikeDomain.value.hi) return null
  return xScale.value(s)
})

const hoverIdx = ref<number | null>(null)
const hoverRow = computed(() =>
  hoverIdx.value == null ? null : (ordered.value[hoverIdx.value] ?? null),
)

interface Bar {
  x: number
  h: number
  y: number
  vannaY: number
  row: ThetaVannaStrikeRow
}
const bars = computed<Bar[]>(() =>
  ordered.value.map((row) => {
    const h = Math.max(2, thetaScale.value(Math.abs(row.net_theta_flow)))
    return {
      x: xScale.value(row.strike),
      h,
      y: thetaBaseY.value + (thetaH.value - 14) - h,
      vannaY: vannaScale.value(row.net_vanna_flow),
      row,
    }
  }),
)
</script>

<template>
  <div class="tv-wrap">
    <div ref="hostRef" class="host">
      <svg
        :width="W"
        :height="H"
        :viewBox="`0 0 ${W} ${H}`"
        role="img"
        aria-label="Theta decay and vanna exposure by strike"
      >
        <!-- pane labels -->
        <text :x="pad.l - 6" :y="thetaBaseY + 4" text-anchor="end" class="pane-label fig">
          θ/day
        </text>
        <text :x="pad.l - 6" :y="vannaZeroY + 3" text-anchor="end" class="pane-label fig">
          Δ/vol
        </text>

        <!-- theta baseline -->
        <line
          :x1="pad.l"
          :x2="W - pad.r"
          :y1="thetaBaseY"
          :y2="thetaBaseY"
          stroke="var(--rule)"
          stroke-width="1"
        />

        <!-- theta bars (decay bleeds downward) -->
        <g
          v-for="(bar, i) in bars"
          :key="`tb${bar.row.strike}`"
          @mouseenter="hoverIdx = i"
          @mouseleave="hoverIdx = null"
        >
          <rect
            :x="bar.x - barWidth / 2"
            :y="thetaBaseY"
            :width="barWidth"
            :height="bar.h"
            class="theta-bar"
            :class="{ dim: hoverIdx != null && hoverIdx !== i }"
            fill="var(--warn)"
            fill-opacity="0.55"
          />
          <rect
            :x="bar.x - barWidth / 2"
            :y="bar.vannaY - 1"
            :width="barWidth"
            :height="2"
            fill="var(--cat-1)"
            fill-opacity="0.8"
            :class="{ dim: hoverIdx != null && hoverIdx !== i }"
          />
        </g>

        <!-- vanna zero line + trace -->
        <line
          :x1="pad.l"
          :x2="W - pad.r"
          :y1="vannaZeroY"
          :y2="vannaZeroY"
          stroke="var(--rule)"
          stroke-width="1"
        />
        <path :d="vannaPath" fill="none" stroke="var(--cat-1)" stroke-width="1.5" />

        <!-- strike axis -->
        <g v-for="row in ordered" :key="`x${row.strike}`">
          <text :x="xScale(row.strike)" :y="H - pad.b + 16" text-anchor="middle" class="axis fig">
            {{ num(row.strike, 0) }}
          </text>
        </g>

        <!-- structural level markers -->
        <g v-for="m in levelMarkers" :key="m.label + m.value">
          <line
            v-if="m.value >= strikeDomain.lo && m.value <= strikeDomain.hi"
            :x1="xScale(m.value)"
            :x2="xScale(m.value)"
            :y1="pad.t"
            :y2="H - pad.b"
            :class="['level-rule', m.cls]"
            stroke-dasharray="3 4"
          />
          <text
            v-if="m.value >= strikeDomain.lo && m.value <= strikeDomain.hi"
            :x="xScale(m.value) + 3"
            :y="pad.t + (m.cls === 'put' || m.cls === 'put-dim' ? 8 : H - pad.b - 4)"
            :class="['axis', 'fig', m.cls]"
          >
            {{ m.label }} {{ num(m.value, 0) }}
          </text>
        </g>

        <!-- spot rule -->
        <g v-if="spotX != null">
          <line
            :x1="spotX"
            :x2="spotX"
            :y1="pad.t"
            :y2="H - pad.b"
            stroke="var(--phosphor)"
            stroke-width="1.5"
          />
          <text
            :x="spotX + (spotX > W / 2 ? -6 : 6)"
            :text-anchor="spotX > W / 2 ? 'end' : 'start'"
            :y="pad.t + 8"
            class="axis fig spot-label"
          >
            SPOT
          </text>
        </g>
      </svg>
    </div>

    <div class="legend mono">
      <span class="legend-item"><span class="swatch theta" />θ DECAY (pts/day)</span>
      <span class="legend-item"><span class="swatch vanna" />VANNA (Δ shares / +1 vol pt)</span>
    </div>

    <div v-if="hoverRow" class="readout mono fig">
      <span class="strike">{{ num(hoverRow.strike, 0) }}</span>
      <span>θ {{ compact(hoverRow.net_theta_flow) }}/day</span>
      <span>vanna {{ signed(hoverRow.net_vanna_flow) }}</span>
      <span>call OI {{ compact(hoverRow.call_oi) }} · put OI {{ compact(hoverRow.put_oi) }}</span>
    </div>
    <p v-else class="method-note">
      Deeper amber bar = faster premium decay at that strike. Vanna trace above zero: rising IV adds
      dealer delta (supportive); below zero: rising IV forces dealer selling (pressuring).
    </p>
  </div>
</template>

<style scoped>
.tv-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  min-width: 0;
}

.host {
  width: 100%;
  overflow: hidden;
}

.theta-bar,
circle {
  transition: opacity var(--dur-fast) var(--ease-out);
}

.dim {
  opacity: 0.35;
}

.pane-label,
.axis {
  fill: var(--ink-faint);
  font-size: var(--t-micro);
  font-family: var(--font-data);
}

.fig {
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
}

.level-rule.put {
  stroke: var(--put);
  opacity: 0.6;
}

.level-rule.put-dim {
  stroke: var(--put);
  opacity: 0.3;
}

.level-rule.call {
  stroke: var(--call);
  opacity: 0.6;
}

.level-rule.call-dim {
  stroke: var(--call);
  opacity: 0.3;
}

.level-rule.warn {
  stroke: var(--warn);
  opacity: 0.5;
}

.axis.put,
.axis.put-dim {
  fill: var(--put-dim);
}

.axis.call,
.axis.call-dim {
  fill: var(--call-dim);
}

.axis.warn {
  fill: var(--warn);
}

.spot-label {
  fill: var(--phosphor);
}

.legend {
  display: flex;
  gap: var(--s3);
  flex-wrap: wrap;
  font-size: var(--t-micro);
  color: var(--ink-soft);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  letter-spacing: 0.05em;
}

.swatch {
  width: 12px;
  height: 8px;
  display: inline-block;
  border-radius: 1px;
}

.swatch.theta {
  background: color-mix(in srgb, var(--warn) 55%, transparent);
}

.swatch.vanna {
  background: var(--cat-1);
  height: 2px;
}

.readout {
  display: flex;
  gap: var(--s3);
  flex-wrap: wrap;
  color: var(--ink-soft);
  font-size: var(--t-micro);
}

.readout .strike {
  color: var(--ink);
  font-weight: 600;
}

.method-note {
  margin: 0;
  color: var(--ink-faint);
  font-size: var(--t-micro);
  line-height: 1.5;
}
</style>
