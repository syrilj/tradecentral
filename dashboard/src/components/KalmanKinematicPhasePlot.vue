<script setup lang="ts">
import { computed, ref } from 'vue'
import type { StateEstimationPoint } from '@/microstructureContracts'
import { num, optSigned } from '@/format'

const props = withDefaults(
  defineProps<{
    points: StateEstimationPoint[]
    breakoutZ?: number
    exhaustionZ?: number
    hoverIndex?: number | null
  }>(),
  {
    breakoutZ: 1.6,
    exhaustionZ: 0.4,
    hoverIndex: null,
  },
)

const emit = defineEmits<{
  'update:hoverIndex': [index: number | null]
}>()

const breakoutThresh = computed(() => props.breakoutZ ?? 1.6)
const exhaustionThresh = computed(() => props.exhaustionZ ?? 0.4)

// Synced / Local Hover Tracking
const localHoverIndex = ref<number | null>(null)
const activeHoverIndex = computed(() => props.hoverIndex ?? localHoverIndex.value)

const latestPoint = computed(() => {
  if (activeHoverIndex.value != null && props.points[activeHoverIndex.value]) {
    return props.points[activeHoverIndex.value]
  }
  if (!props.points || props.points.length === 0) return null
  return props.points[props.points.length - 1]
})

// Robust Velocity Z-Score Extent for Sub-Chart
const velocityExtent = computed(() => {
  if (!props.points || props.points.length === 0) return { min: -2.5, max: 2.5 }
  let maxAbs = 0.5
  for (const pt of props.points) {
    if (Number.isFinite(pt.kalman_zscore) && Math.abs(pt.kalman_zscore) > maxAbs) {
      maxAbs = Math.abs(pt.kalman_zscore)
    }
  }
  // Cap at 4.5 sigma so extreme anomalies do not compress the tradeable momentum oscillations
  const bound = Math.min(5.0, Math.max(breakoutThresh.value * 1.4, maxAbs * 1.05))
  return { min: -bound, max: bound }
})

const width = 1200
const height = 190
const pad = { top: 18, right: 120, bottom: 28, left: 70 }
const innerW = width - pad.left - pad.right
const innerH = height - pad.top - pad.bottom

function scaleX(idx: number): number {
  const n = props.points.length
  if (n <= 1) return pad.left
  const clamped = Math.max(0, Math.min(n - 1, idx))
  return pad.left + (clamped / (n - 1)) * innerW
}

function scaleZ(z: number): number {
  const { min, max } = velocityExtent.value
  const clampedZ = Math.max(min, Math.min(max, z))
  const norm = (clampedZ - min) / (max - min)
  return pad.top + (1 - norm) * innerH
}

const zeroY = computed(() => scaleZ(0.0))
const posBreakoutY = computed(() => scaleZ(breakoutThresh.value))
const negBreakoutY = computed(() => scaleZ(-breakoutThresh.value))
const posExhaustY = computed(() => scaleZ(exhaustionThresh.value))
const negExhaustY = computed(() => scaleZ(-exhaustionThresh.value))

const velocityPath = computed(() => {
  if (!props.points || props.points.length === 0) return ''
  return props.points
    .map(
      (pt, i) =>
        `${i === 0 ? 'M' : 'L'} ${scaleX(i).toFixed(1)} ${scaleZ(pt.kalman_zscore).toFixed(1)}`,
    )
    .join(' ')
})

function formatDateLabel(isoStr: string): string {
  try {
    const d = new Date(isoStr)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
  } catch {
    return isoStr.slice(5, 10)
  }
}

// X-Axis Date Ticks matching main chart
const xTicks = computed(() => {
  const n = props.points.length
  if (n === 0) return []
  const count = Math.min(8, n)
  const ticks = []
  for (let i = 0; i < count; i++) {
    const idx = Math.floor((i / (count - 1)) * (n - 1))
    const pt = props.points[idx]
    ticks.push({
      label: formatDateLabel(pt.t),
      rawTime: pt.t,
      x: scaleX(idx),
    })
  }
  return ticks
})

function onSvgMouseMove(evt: MouseEvent): void {
  const svg = evt.currentTarget as SVGSVGElement
  const rect = svg.getBoundingClientRect()
  const mouseX = evt.clientX - rect.left
  const svgX = (mouseX / rect.width) * width

  const n = props.points.length
  if (n <= 1) return

  const relX = Math.max(0, Math.min(innerW, svgX - pad.left))
  const idx = Math.round((relX / innerW) * (n - 1))
  const finalIdx = Math.max(0, Math.min(n - 1, idx))
  localHoverIndex.value = finalIdx
  emit('update:hoverIndex', finalIdx)
}

function onSvgMouseLeave(): void {
  localHoverIndex.value = null
  emit('update:hoverIndex', null)
}
</script>

<template>
  <div class="kalman-phase-card">
    <div class="card-header">
      <div>
        <span class="eyebrow">2-STATE KINEMATIC KALMAN FILTER</span>
        <h3 class="card-title">Instantaneous Latent Velocity &amp; Momentum States</h3>
      </div>
      <div v-if="latestPoint" class="state-badges">
        <span v-if="latestPoint.breakout" class="badge breakout">
          KINEMATIC ACCELERATION (|z| &gt; {{ breakoutThresh }})
        </span>
        <span v-else-if="latestPoint.exhaustion" class="badge exhaustion">
          MOMENTUM EXHAUSTION (|z| &le; {{ exhaustionThresh }})
        </span>
        <span v-else class="badge neutral"> STABLE TRAJECTORY </span>
      </div>
    </div>

    <!-- Live Readouts Strip -->
    <div v-if="latestPoint" class="readouts-row">
      <div class="stat-box">
        <span class="stat-label">LATENT EQUILIBRIUM PRICE (p*)</span>
        <span class="stat-val font-mono">${{ num(latestPoint.kalman_price, 2) }}</span>
      </div>
      <div class="stat-box">
        <span class="stat-label">INSTANTANEOUS VELOCITY (v = dp/dt)</span>
        <span
          class="stat-val font-mono font-semibold"
          :class="{
            'text-emerald': latestPoint.kalman_velocity > 0,
            'text-rose': latestPoint.kalman_velocity < 0,
          }"
        >
          {{ optSigned(latestPoint.kalman_velocity, 4) }}
        </span>
      </div>
      <div class="stat-box">
        <span class="stat-label">STANDARDIZED Z-SCORE (z_v)</span>
        <span
          class="stat-val font-mono font-bold"
          :class="{
            'text-emerald': latestPoint.kalman_zscore > 0,
            'text-rose': latestPoint.kalman_zscore < 0,
          }"
        >
          {{ optSigned(latestPoint.kalman_zscore, 2) }}&sigma;
        </span>
      </div>
      <div class="stat-box">
        <span class="stat-label">ADAPTIVE PROCESS NOISE (Q)</span>
        <span class="stat-val font-mono text-call-hi">{{
          latestPoint.kalman_q.toExponential(2)
        }}</span>
      </div>
    </div>

    <!-- Velocity Time Series SVG Chart -->
    <div class="chart-wrapper">
      <svg role="img" aria-label="Kalman kinematic phase plot: velocity against price level."
        :viewBox="`0 0 ${width} ${height}`"
        class="velocity-svg"
        preserveAspectRatio="xMidYMid meet"
        @mousemove="onSvgMouseMove"
        @mouseleave="onSvgMouseLeave"
      >
        <!-- Neutral Zero Line -->
        <line
          :x1="pad.left"
          :y1="zeroY"
          :x2="width - pad.right"
          :y2="zeroY"
          stroke="var(--rule-hi)"
          stroke-width="1.2"
        />

        <!-- Breakout Acceleration Zone Shading (+ / -) -->
        <rect
          :x="pad.left"
          :y="pad.top"
          :width="innerW"
          :height="Math.max(0, posBreakoutY - pad.top)"
          fill="var(--call-wash)"
          opacity="0.5"
        />
        <rect
          :x="pad.left"
          :y="negBreakoutY"
          :width="innerW"
          :height="Math.max(0, height - pad.bottom - negBreakoutY)"
          fill="var(--put-wash)"
          opacity="0.5"
        />

        <!-- Momentum Exhaustion Shaded Band (+ / - epsilon) -->
        <rect
          :x="pad.left"
          :y="posExhaustY"
          :width="innerW"
          :height="Math.abs(negExhaustY - posExhaustY)"
          fill="var(--warn-wash)"
          stroke="var(--warn)"
          stroke-dasharray="2 2"
          opacity="0.8"
        />

        <!-- Breakout Threshold Lines (+ / - theta) -->
        <line
          :x1="pad.left"
          :y1="posBreakoutY"
          :x2="width - pad.right"
          :y2="posBreakoutY"
          stroke="var(--call)"
          stroke-dasharray="4 3"
          stroke-width="1.2"
          opacity="0.85"
        />
        <line
          :x1="pad.left"
          :y1="negBreakoutY"
          :x2="width - pad.right"
          :y2="negBreakoutY"
          stroke="var(--put)"
          stroke-dasharray="4 3"
          stroke-width="1.2"
          opacity="0.85"
        />

        <!-- Velocity Z-Score Line -->
        <path :d="velocityPath" fill="none" stroke="var(--phosphor)" stroke-width="2.2" />

        <!-- Synchronized Hover Crosshair -->
        <g v-if="activeHoverIndex != null && points[activeHoverIndex]" class="hover-crosshair">
          <line
            :x1="scaleX(activeHoverIndex)"
            :y1="pad.top"
            :x2="scaleX(activeHoverIndex)"
            :y2="height - pad.bottom"
            stroke="var(--ink-dim)"
            stroke-width="1"
            stroke-dasharray="3 3"
          />
          <circle
            :cx="scaleX(activeHoverIndex)"
            :cy="scaleZ(points[activeHoverIndex].kalman_zscore)"
            r="4.5"
            fill="var(--phosphor)"
            stroke="var(--void)"
            stroke-width="2"
          />
        </g>

        <!-- Threshold & Level Labels -->
        <text
          :x="width - pad.right + 6"
          :y="posBreakoutY + 4"
          fill="var(--call)"
          font-size="10"
          font-family="monospace"
          font-weight="700"
        >
          +{{ breakoutThresh }}&sigma; BREAK
        </text>
        <text
          :x="width - pad.right + 6"
          :y="posExhaustY + 4"
          fill="var(--warn)"
          font-size="9"
          font-family="monospace"
        >
          +{{ exhaustionThresh }}&sigma; EXHAUST
        </text>
        <text
          :x="width - pad.right + 6"
          :y="zeroY + 4"
          fill="var(--ink-dim)"
          font-size="10"
          font-family="monospace"
        >
          0.0 LEVEL
        </text>
        <text
          :x="width - pad.right + 6"
          :y="negExhaustY + 4"
          fill="var(--warn)"
          font-size="9"
          font-family="monospace"
        >
          -{{ exhaustionThresh }}&sigma; EXHAUST
        </text>
        <text
          :x="width - pad.right + 6"
          :y="negBreakoutY + 4"
          fill="var(--put)"
          font-size="10"
          font-family="monospace"
          font-weight="700"
        >
          -{{ breakoutThresh }}&sigma; BREAK
        </text>

        <!-- X-Axis Date Labels -->
        <g class="x-axis-labels">
          <text
            v-for="tick in xTicks"
            :key="tick.rawTime"
            :x="tick.x"
            :y="height - 8"
            text-anchor="middle"
            fill="var(--ink-dim)"
            font-size="10"
            font-family="monospace"
          >
            {{ tick.label }}
          </text>
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.kalman-phase-card {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  width: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.eyebrow {
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
  color: var(--ink-faint);
  font-family: var(--font-mono, monospace);
}

.card-title {
  margin: 0.25rem 0 0;
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--ink);
}

.badge {
  font-size: var(--t-micro);
  font-weight: 700;
  padding: 0.25rem 0.5rem;
  border-radius: var(--r-sm);
  font-family: var(--font-mono, monospace);
}

.badge.breakout {
  background: var(--call-wash);
  color: var(--call-hi);
  border: 1px solid var(--call-dim);
}

.badge.exhaustion {
  background: var(--warn-wash);
  color: var(--warn);
  border: 1px solid var(--warn);
}

.badge.neutral {
  background: var(--panel-hi);
  color: var(--ink-dim);
}

.readouts-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.75rem;
}

.stat-box {
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  border-radius: var(--r-sm);
  padding: 0.625rem 0.875rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.stat-label {
  font-size: var(--t-nano);
  color: var(--ink-faint);
  font-family: var(--font-mono, monospace);
}

.stat-val {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--ink);
}

.text-emerald {
  color: var(--long);
}

.text-rose {
  color: var(--short);
}

.text-call-hi {
  color: var(--call-hi);
}

.chart-wrapper {
  width: 100%;
}

.velocity-svg {
  width: 100%;
  height: auto;
  display: block;
  background: var(--void-lift);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  cursor: crosshair;
}
</style>
