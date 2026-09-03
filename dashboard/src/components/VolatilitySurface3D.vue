<script setup lang="ts">
import { computed, ref } from 'vue'
import { num } from '@/format'
import { useChartSize } from '@/composables/useChartSize'

const props = withDefaults(
  defineProps<{
    symbol?: string
    spot?: number | null
    horizonLabel?: string
  }>(),
  {
    symbol: 'SPY',
    spot: null,
    horizonLabel: '30D',
  },
)

const hasValidSpot = computed(() => props.spot != null && props.spot > 0)

const hostRef = ref<HTMLDivElement | null>(null)
const { W, H } = useChartSize(hostRef, { minW: 280, minH: 210, fallbackW: 380, fallbackH: 230 })
const pad = { l: 44, r: 56, t: 16, b: 32 }

const dragging = ref(false)
// Turntable yaw over the strike/expiry plane. Held in the (-1.1, -0.1) band so
// the strike axis always stays front-right and the expiry axis back-left.
const yaw = ref(-0.62)
const dragPrev = { x: 0 }

const K_STEPS = 21
const T_STEPS = 13
const DTE_MAX = 45

interface SurfaceNode {
  u: number
  v: number
  iv: number
}

function ivAt(strike: number, dte: number): number {
  const s = props.spot && props.spot > 0 ? props.spot : 100
  const moneyness = Math.log(strike / s)
  // Smooth put smirk + downward term structure. Kept continuous across spot —
  // the call/put break in the raw chain would put a step in the smile.
  const baseIv = 0.14 + (1 - dte / DTE_MAX) * 0.05
  const skew = -0.15 * moneyness + 0.35 * moneyness * moneyness
  return Math.max(0.08, baseIv + skew)
}

const grid = computed<SurfaceNode[][]>(() => {
  if (!hasValidSpot.value) return []
  const s = props.spot!
  const nodes: SurfaceNode[][] = []
  for (let d = 0; d < T_STEPS; d++) {
    const dte = 1 + (d / (T_STEPS - 1)) * (DTE_MAX - 1)
    const row: SurfaceNode[] = []
    for (let k = 0; k < K_STEPS; k++) {
      const strike = s * 0.9 + (k / (K_STEPS - 1)) * (s * 0.2)
      row.push({ u: k / (K_STEPS - 1), v: d / (T_STEPS - 1), iv: ivAt(strike, dte) })
    }
    nodes.push(row)
  }
  return nodes
})

const ivBounds = computed(() => {
  let lo = Infinity
  let hi = -Infinity
  for (const row of grid.value) {
    for (const node of row) {
      lo = Math.min(lo, node.iv)
      hi = Math.max(hi, node.iv)
    }
  }
  return { lo, hi }
})

// Quantised bands instead of a smooth gradient: flat fills only on data marks.
const BANDS = 6

function band(iv: number): number {
  const { lo, hi } = ivBounds.value
  const t = Math.min(1, Math.max(0, (iv - lo) / Math.max(1e-9, hi - lo)))
  return Math.min(BANDS - 1, Math.floor(t * BANDS))
}

// ---- projection ------------------------------------------------------------
// Normalised axes (u = strike, v = expiry, w = IV) are rotated by yaw, depth is
// flattened by a fixed pitch, and IV lifts the surface straight up. The unit
// cube corners are then fitted to the plot rect so every rotation stays framed.
const PITCH = 0.46

function projNorm(u: number, v: number, w: number) {
  const c = Math.cos(yaw.value)
  const s = Math.sin(yaw.value)
  const x = u - 0.5
  const z = v - 0.5
  return {
    px: x * c - z * s,
    py: (x * s + z * c) * PITCH - w,
    depth: x * s + z * c,
  }
}

const view = computed(() => {
  let minX = Infinity
  let maxX = -Infinity
  let minY = Infinity
  let maxY = -Infinity
  for (const u of [0, 1]) {
    for (const v of [0, 1]) {
      for (const w of [0, 1]) {
        const p = projNorm(u, v, w)
        minX = Math.min(minX, p.px)
        maxX = Math.max(maxX, p.px)
        minY = Math.min(minY, p.py)
        maxY = Math.max(maxY, p.py)
      }
    }
  }
  const sx = (W.value - pad.l - pad.r) / Math.max(1e-9, maxX - minX)
  const sy = (H.value - pad.t - pad.b) / Math.max(1e-9, maxY - minY)
  const k = Math.min(sx, sy)
  const ox = pad.l + (W.value - pad.l - pad.r - (maxX - minX) * k) / 2 - minX * k
  const oy = pad.t + (H.value - pad.t - pad.b - (maxY - minY) * k) / 2 - minY * k
  return { k, ox, oy }
})

function toXY(u: number, v: number, w: number) {
  const p = projNorm(u, v, w)
  return {
    x: view.value.ox + p.px * view.value.k,
    y: view.value.oy + p.py * view.value.k,
  }
}

// Surface facets, painted back-to-front so nearer rows overlap correctly.
interface Facet {
  key: string
  pts: string
  band: number
  depth: number
}

const normIv = computed(() => (iv: number) => {
  const { lo, hi } = ivBounds.value
  return (iv - lo) / Math.max(1e-9, hi - lo)
})

const facets = computed<Facet[]>(() => {
  const out: Facet[] = []
  const lift = normIv.value
  for (let d = 0; d < T_STEPS - 1; d++) {
    for (let k = 0; k < K_STEPS - 1; k++) {
      const a = grid.value[d][k]
      const b = grid.value[d][k + 1]
      const c = grid.value[d + 1][k + 1]
      const e = grid.value[d + 1][k]
      const p1 = toXY(a.u, a.v, lift(a.iv))
      const p2 = toXY(b.u, b.v, lift(b.iv))
      const p3 = toXY(c.u, c.v, lift(c.iv))
      const p4 = toXY(e.u, e.v, lift(e.iv))
      out.push({
        key: `${d}-${k}`,
        pts: `${p1.x.toFixed(1)},${p1.y.toFixed(1)} ${p2.x.toFixed(1)},${p2.y.toFixed(1)} ${p3.x.toFixed(1)},${p3.y.toFixed(1)} ${p4.x.toFixed(1)},${p4.y.toFixed(1)}`,
        band: band((a.iv + b.iv + c.iv + e.iv) / 4),
        depth: (projNorm(a.u, a.v, 0).depth + projNorm(c.u, c.v, 0).depth) / 2,
      })
    }
  }
  return out.sort((m, n) => n.depth - m.depth)
})

// Floor grid: the base plane the surface is measured off of.
const floorLines = computed(() => {
  const lines: Array<{ d: string }> = []
  for (let k = 0; k < K_STEPS; k += 2) {
    const u = k / (K_STEPS - 1)
    const p1 = toXY(u, 0, 0)
    const p2 = toXY(u, 1, 0)
    lines.push({ d: `M ${p1.x.toFixed(1)} ${p1.y.toFixed(1)} L ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}` })
  }
  for (let d = 0; d < T_STEPS; d += 2) {
    const v = d / (T_STEPS - 1)
    const p1 = toXY(0, v, 0)
    const p2 = toXY(1, v, 0)
    lines.push({ d: `M ${p1.x.toFixed(1)} ${p1.y.toFixed(1)} L ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}` })
  }
  return lines
})

// With yaw held negative the strike axis reads on the front edge (v = 1) and
// the expiry axis on the left edge (u = 0).
const strikeTicks = computed(() => {
  const s = props.spot ?? 100
  return [0, 0.5, 1].map((u) => {
    const strike = s * 0.9 + u * (s * 0.2)
    return { ...toXY(u, 1, 0), label: num(strike, 0) }
  })
})

const expiryTicks = computed(() => {
  return [0, 0.5, 1].map((v) => {
    const dte = 1 + v * (DTE_MAX - 1)
    return { ...toXY(0, v, 0), label: `${Math.round(dte)}D` }
  })
})

const spotMark = computed(() => {
  const s = props.spot ?? 100
  // The strike range is 0.9s..1.1s, so spot always sits at the mid strike.
  const u = (s - s * 0.9) / (s * 0.2)
  return { axis: toXY(u, 1, 0), inner: toXY(u, 0.9, 0) }
})

const strikeAxisMid = computed(() => {
  const a = toXY(0, 1, 0)
  const b = toXY(1, 1, 0)
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
})

const expiryAxisMid = computed(() => {
  const a = toXY(0, 0, 0)
  const b = toXY(0, 1, 0)
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
})

const ivLegend = computed(() => {
  const { lo, hi } = ivBounds.value
  const y0 = pad.t + 16
  const step = 16
  return {
    x: W.value - pad.r + 14,
    y0,
    step,
    lo,
    hi,
    top: `${(hi * 100).toFixed(0)}%`,
    bottom: `${(lo * 100).toFixed(0)}%`,
  }
})

function onPointerDown(e: PointerEvent) {
  dragging.value = true
  dragPrev.x = e.clientX
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  yaw.value = Math.min(-0.1, Math.max(-1.1, yaw.value + (e.clientX - dragPrev.x) * 0.006))
  dragPrev.x = e.clientX
}

function onPointerUp() {
  dragging.value = false
}
</script>

<template>
  <div class="vol-surface-card">
    <div class="card-header">
      <div class="title-group">
        <span class="card-title font-display font-bold">VOLATILITY SURFACE</span>
      </div>
      <div class="controls-group">
        <span class="ticker-badge font-mono">{{ symbol }}</span>
        <span class="horizon-badge">{{ horizonLabel }}</span>
      </div>
    </div>

    <!-- Surface Frame -->
    <div
      ref="hostRef"
      class="canvas-container"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointerleave="onPointerUp"
    >
      <div v-if="!hasValidSpot" class="chart-empty font-mono">
        <span class="empty-dash">&mdash;</span>
        <span class="empty-text">No spot price available for 3D vol surface</span>
      </div>
      <svg
        v-else
        class="surface-svg"
        role="img"
        :aria-label="`Implied volatility surface across strike and expiry.`"
        :viewBox="`0 0 ${W} ${H}`"
      >
        <title>{{ `Implied volatility surface across strike and expiry.` }}</title>
        <!-- Floor grid -->
        <path
          v-for="(line, i) in floorLines"
          :key="`fl-${i}`"
          :d="line.d"
          fill="none"
          class="floor-line"
          stroke-width="1"
        />

        <!-- Surface facets -->
        <polygon
          v-for="f in facets"
          :key="f.key"
          :points="f.pts"
          :class="`iv-q${f.band}`"
          class="facet"
          stroke-width="0.5"
        />

        <!-- Axes -->
        <text
          :x="strikeAxisMid.x"
          :y="strikeAxisMid.y + 26"
          text-anchor="middle"
          class="axis-title font-mono"
        >
          STRIKE
        </text>
        <text
          :x="expiryAxisMid.x - 14"
          :y="expiryAxisMid.y - 6"
          text-anchor="middle"
          class="axis-title font-mono"
        >
          DTE
        </text>

        <g v-for="(t, i) in strikeTicks" :key="`kt-${i}`">
          <text :x="t.x" :y="t.y + 11" text-anchor="middle" class="axis-tick font-mono">
            {{ t.label }}
          </text>
        </g>
        <g v-for="(t, i) in expiryTicks" :key="`dt-${i}`">
          <text :x="t.x - 8" :y="t.y + 3" text-anchor="end" class="axis-tick font-mono">
            {{ t.label }}
          </text>
        </g>

        <!-- Spot reference on the strike axis -->
        <line
          :x1="spotMark.axis.x"
          :y1="spotMark.axis.y"
          :x2="spotMark.inner.x"
          :y2="spotMark.inner.y"
          stroke="var(--phosphor)"
          stroke-width="1.5"
        />
        <text
          :x="spotMark.axis.x"
          :y="spotMark.axis.y + 24"
          text-anchor="middle"
          class="spot-label font-mono font-bold"
        >
          SPOT {{ num(spot ?? 0, 0) }}
        </text>

        <!-- IV legend -->
        <text :x="ivLegend.x + 4" :y="ivLegend.y0 - 12" class="axis-title font-mono">IV</text>
        <text
          :x="ivLegend.x - 4"
          :y="ivLegend.y0 - 2"
          text-anchor="end"
          class="axis-tick font-mono"
        >
          {{ ivLegend.top }}
        </text>
        <rect
          v-for="b in BANDS"
          :key="`lg-${b}`"
          :x="ivLegend.x"
          :y="ivLegend.y0 + (BANDS - b) * ivLegend.step"
          width="8"
          :height="ivLegend.step"
          :class="`iv-q${b - 1}`"
        />
        <text
          :x="ivLegend.x - 4"
          :y="ivLegend.y0 + BANDS * ivLegend.step"
          text-anchor="end"
          class="axis-tick font-mono"
        >
          {{ ivLegend.bottom }}
        </text>
      </svg>
    </div>

    <!-- Subtitle caption -->
    <div class="card-footer">
      <span class="sub-caption font-mono text-ink-dim">
        Smirk showing higher IV demand in puts.
      </span>
    </div>
  </div>
</template>

<style scoped>
.vol-surface-card {
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
  font-family: var(--font-display);
  font-size: 0.875rem;
  letter-spacing: 0.04em;
  color: var(--ink);
}

.controls-group {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: var(--t-tiny);
}

.ticker-badge,
.horizon-badge {
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  padding: 0.15rem 0.45rem;
  border-radius: var(--r-xs);
  color: var(--ink-soft);
  font-size: 0.75rem;
}

.canvas-container {
  width: 100%;
  height: 220px;
  cursor: grab;
  position: relative;
  touch-action: none;
}

.canvas-container:active {
  cursor: grabbing;
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

.surface-svg {
  width: 100%;
  height: 100%;
  display: block;
  overflow: visible;
}

.floor-line {
  stroke: var(--rule);
}

.facet {
  stroke: var(--panel);
}

/* IV ramp, quantised: dim ink at low IV rising to the one accent at high. */
.iv-q0 {
  fill: color-mix(in srgb, var(--phosphor) 8%, var(--ink-ghost));
}

.iv-q1 {
  fill: color-mix(in srgb, var(--phosphor) 24%, var(--ink-ghost));
}

.iv-q2 {
  fill: color-mix(in srgb, var(--phosphor) 42%, var(--ink-ghost));
}

.iv-q3 {
  fill: color-mix(in srgb, var(--phosphor) 60%, var(--ink-ghost));
}

.iv-q4 {
  fill: color-mix(in srgb, var(--phosphor) 80%, var(--ink-ghost));
}

.iv-q5 {
  fill: var(--phosphor);
}

.axis-title {
  font-family: var(--font-ui);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  fill: var(--ink-dim);
}

.axis-tick {
  font-family: var(--font-data);
  font-size: 0.75rem;
  fill: var(--ink-dim);
  font-variant-numeric: tabular-nums;
}

.spot-label {
  font-family: var(--font-ui);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  fill: var(--phosphor);
}

.card-footer {
  padding-top: 0.375rem;
  border-top: 1px solid var(--rule-faint);
}

.sub-caption {
  font-family: var(--font-ui);
  font-size: 0.8125rem;
  color: var(--ink-soft);
}
</style>
