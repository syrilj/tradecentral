<script setup lang="ts">
import { computed, ref } from 'vue'
import type { OptionsProbability } from '@/api'
import { useChartSize } from '@/composables/useChartSize'
import { num, pctFrac, usd } from '@/format'

/**
 * 2D risk-neutral lognormal PDF of terminal price f(S_T).
 * Not a 3D surface — x = price, y = density (relative scale).
 * Width tracks the host; height is an explicit prop.
 */
const props = withDefaults(
  defineProps<{
    probability: OptionsProbability | null | undefined
    spot: number
    callWall?: number | null
    putWall?: number | null
    focusPrice?: number | null
    height?: number
  }>(),
  { height: 260, callWall: null, putWall: null, focusPrice: null },
)

const hostRef = ref<HTMLDivElement | null>(null)
const hoverX = ref<number | null>(null)
const { W } = useChartSize(hostRef, {
  minW: 240,
  minH: 80,
  fallbackW: 640,
  fallbackH: props.height,
})
const H = computed(() => Math.max(160, Math.round(props.height)))

/** Left pad leaves room for a density axis label; top for wall tags. */
const pad = computed(() => ({
  l: W.value < 420 ? 28 : 36,
  r: W.value < 420 ? 10 : 14,
  t: 28,
  b: 28,
}))

const model = computed(() => {
  const p = props.probability
  if (!p?.available || !props.spot || !p.atm_iv || !p.horizon_days) return null
  const T = Math.max(p.horizon_days, 1) / 365
  const sigma = p.atm_iv * Math.sqrt(T)
  if (!(sigma > 0)) return null
  const mu = Math.log(props.spot) - 0.5 * p.atm_iv * p.atm_iv * T
  const sigma2 = 2 * sigma
  let low = Math.max(0.01, (p.expected_low ?? props.spot * 0.85) * 0.85)
  let high = (p.expected_high ?? props.spot * 1.15) * 1.15
  if (props.focusPrice != null && props.focusPrice > 0) {
    low = Math.min(low, props.focusPrice * 0.96)
    high = Math.max(high, props.focusPrice * 1.04)
  }
  return {
    mu,
    sigma,
    sigma2,
    T,
    iv: p.atm_iv,
    low,
    high,
    horizon: p.horizon_days,
    expectedMove: p.expected_move ?? props.spot * sigma,
    expectedLow: p.expected_low ?? props.spot - props.spot * sigma,
    expectedHigh: p.expected_high ?? props.spot + props.spot * sigma,
  }
})

function cdfNormal(x: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const d = 0.3989423 * Math.exp(-x * x / 2)
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
  return x >= 0 ? 1 - p : p
}

function density(x: number, mu: number, sigma: number): number {
  if (x <= 0 || sigma <= 0) return 0
  const z = (Math.log(x) - mu) / sigma
  return (1 / (x * sigma * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * z * z)
}

const curve = computed(() => {
  const m = model.value
  if (!m) return null
  const n = 180
  const dens: number[] = []
  let maxD = 1e-12
  for (let i = 0; i < n; i++) {
    const price = m.low + (i / (n - 1)) * (m.high - m.low)
    const d = density(price, m.mu, m.sigma)
    dens.push(d)
    if (d > maxD) maxD = d
  }
  const plotH = H.value - pad.value.t - pad.value.b
  const plotW = W.value - pad.value.l - pad.value.r
  const pts: { price: number; dens: number; x: number; y: number }[] = []
  for (let i = 0; i < n; i++) {
    const price = m.low + (i / (n - 1)) * (m.high - m.low)
    const u = i / (n - 1)
    pts.push({
      price,
      dens: dens[i],
      x: pad.value.l + u * plotW,
      y: H.value - pad.value.b - (dens[i] / maxD) * plotH,
    })
  }
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ')
  const area = `${line} L${pts[pts.length - 1].x.toFixed(2)},${(H.value - pad.value.b).toFixed(2)} L${pts[0].x.toFixed(2)},${(H.value - pad.value.b).toFixed(2)} Z`
  return { pts, line, area, maxD, m, plotH, plotW }
})

function xOfPrice(price: number): number | null {
  const c = curve.value
  if (!c) return null
  const u = (price - c.m.low) / (c.m.high - c.m.low)
  if (u < -0.02 || u > 1.02) return null
  return pad.value.l + Math.max(0, Math.min(1, u)) * c.plotW
}

const oneSigmaBand = computed(() => {
  const c = curve.value
  if (!c) return null
  const xLo = xOfPrice(c.m.expectedLow)
  const xHi = xOfPrice(c.m.expectedHigh)
  if (xLo == null || xHi == null) return null
  return { x: Math.min(xLo, xHi), width: Math.abs(xHi - xLo) }
})

const markers = computed(() => {
  const items: { key: string; x: number; label: string; cls: string; price: number }[] = []
  const add = (key: string, price: number | null | undefined, label: string, cls: string) => {
    if (price == null || price <= 0) return
    const x = xOfPrice(price)
    if (x == null) return
    items.push({ key, x, label: `${label} ${num(price, 0)}`, cls, price })
  }
  add('put', props.putWall, 'PUT', 'put')
  add('spot', props.spot, 'SPOT', 'spot')
  add('call', props.callWall, 'CALL', 'call')
  add('focus', props.focusPrice, 'FOCUS', 'focus')
  const sorted = [...items].sort((a, b) => a.x - b.x)
  // Labels sit under the top edge (inside pad.t band) so they never clip;
  // stagger Y when neighbours are tight.
  const MIN_GAP = 54
  let prevX = -Infinity
  let lane = 0
  return sorted.map((item) => {
    if (item.x - prevX < MIN_GAP) lane = 1 - lane
    else lane = 0
    prevX = item.x
    return {
      ...item,
      labelY: pad.value.t - 8 - lane * 12,
    }
  })
})

const xTicks = computed(() => {
  const c = curve.value
  if (!c) return []
  const n = W.value < 480 ? 4 : 5
  return Array.from({ length: n }, (_, i) => {
    const price = c.m.low + (i / (n - 1)) * (c.m.high - c.m.low)
    return { price, x: pad.value.l + (i / (n - 1)) * c.plotW }
  })
})

function onMove(e: MouseEvent): void {
  const svg = e.currentTarget as SVGSVGElement
  const box = svg.getBoundingClientRect()
  if (box.width <= 0) return
  hoverX.value = ((e.clientX - box.left) / box.width) * W.value
}

function probeDetails(pt: { price: number; dens: number; x: number; y: number }, source: 'lock' | 'hover') {
  const c = curve.value
  if (!c) return null
  const d2 = (Math.log(props.spot / pt.price) - 0.5 * c.m.sigma * c.m.sigma) / c.m.sigma
  const probAbove = cdfNormal(d2)
  return { ...pt, rel: pt.dens / c.maxD, probAbove, probBelow: 1 - probAbove, source }
}

function probeAtPrice(price: number) {
  const c = curve.value
  if (!c) return null
  let best = c.pts[0]
  let bestDist = Infinity
  for (const pt of c.pts) {
    const d = Math.abs(pt.price - price)
    if (d < bestDist) {
      bestDist = d
      best = pt
    }
  }
  return probeDetails(best, 'lock')
}

const focus = computed(() => {
  const c = curve.value
  if (!c) return null
  if (hoverX.value != null) {
    let best = c.pts[0]
    let bestDist = Infinity
    for (const pt of c.pts) {
      const d = Math.abs(pt.x - hoverX.value)
      if (d < bestDist) {
        bestDist = d
        best = pt
      }
    }
    return probeDetails(best, 'hover')
  }
  if (props.focusPrice != null && props.focusPrice > 0) return probeAtPrice(props.focusPrice)
  return null
})
</script>

<template>
  <div class="pdf-chart">
    <div class="head">
      <div class="facts" v-if="model">
        <span class="label model-tag">2D PDF f(S<sub>T</sub>)</span>
        <span class="label">IV <b class="fig">{{ pctFrac(model.iv, 1) }}</b></span>
        <span class="label">{{ model.horizon }}D</span>
        <span class="label">±1σ <b class="fig">{{ usd(model.expectedMove) }}</b></span>
        <span class="label put">{{ usd(model.expectedLow) }}</span>
        <span class="label">→</span>
        <span class="label call">{{ usd(model.expectedHigh) }}</span>
      </div>
      <div v-if="focus" class="probe-inline" :class="focus.source">
        <span class="label">{{ focus.source === 'lock' ? 'LOCK' : 'PROBE' }}</span>
        <b class="fig">{{ usd(focus.price) }}</b>
        <span class="call">P(S&gt;) {{ pctFrac(focus.probAbove, 0) }}</span>
        <span class="put">P(S&lt;) {{ pctFrac(focus.probBelow, 0) }}</span>
      </div>
      <span v-else class="idle label">Hover curve · lock a GEX strike</span>
    </div>

    <div ref="hostRef" class="canvas" :style="{ height: `${H}px` }">
      <svg
        v-if="curve"
        :viewBox="`0 0 ${W} ${H}`"
        class="svg"
        role="img"
        aria-label="Two-dimensional probability density of terminal price. X is price, Y is relative density."
        preserveAspectRatio="xMidYMid meet"
        @mousemove="onMove"
        @mouseleave="hoverX = null"
      >
        <rect
          v-if="oneSigmaBand"
          class="sigma-band"
          :x="oneSigmaBand.x"
          :y="pad.t"
          :width="oneSigmaBand.width"
          :height="H - pad.t - pad.b"
          fill="var(--rule)"
          opacity="0.55"
        />

        <!-- Axes: price → , density ↑ (plain 2D, not a 3D projection) -->
        <line class="baseline" :x1="pad.l" :x2="W - pad.r" :y1="H - pad.b" :y2="H - pad.b" />
        <line class="baseline" :x1="pad.l" :x2="pad.l" :y1="pad.t" :y2="H - pad.b" />
        <text class="axis-cap" :x="(pad.l + W - pad.r) / 2" :y="H - 4" text-anchor="middle">TERMINAL PRICE $</text>
        <text
          class="axis-cap y-cap"
          :x="12"
          :y="(pad.t + H - pad.b) / 2"
          text-anchor="middle"
          :transform="`rotate(-90 12 ${(pad.t + H - pad.b) / 2})`"
        >REL DENSITY</text>

        <!-- Flat wash under the curve — instrument rule: no fake 3D gradient -->
        <path class="area" :d="curve.area" fill="var(--phosphor-wash)" />
        <path class="curve" :d="curve.line" />

        <g v-for="m in markers" :key="m.key" class="marker" :class="m.cls">
          <line :x1="m.x" :x2="m.x" :y1="pad.t" :y2="H - pad.b" />
          <text :x="m.x" :y="m.labelY" text-anchor="middle">{{ m.label }}</text>
        </g>

        <g v-if="focus" class="probe">
          <line :x1="focus.x" :x2="focus.x" :y1="focus.y" :y2="H - pad.b" />
          <circle :cx="focus.x" :cy="focus.y" r="4.5" />
          <text
            class="probe-price"
            :x="focus.x"
            :y="Math.max(pad.t + 12, focus.y - 10)"
            text-anchor="middle"
          >{{ usd(focus.price) }}</text>
        </g>

        <g class="x-axis">
          <template v-for="tick in xTicks" :key="tick.x">
            <line :x1="tick.x" :x2="tick.x" :y1="H - pad.b" :y2="H - pad.b + 4" />
            <text :x="tick.x" :y="H - 14" text-anchor="middle">{{ num(tick.price, 0) }}</text>
          </template>
        </g>
      </svg>
      <p v-else class="empty label">Need ATM IV + expiry for a 2D density</p>
    </div>
  </div>
</template>

<style scoped>
.pdf-chart {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.head {
  display: flex;
  align-items: center;
  gap: 4px 8px;
  min-height: 22px;
  flex: 0 0 auto;
  flex-wrap: wrap;
  padding: 2px 4px 0;
}
.facts { display: flex; align-items: center; gap: 4px 8px; flex-wrap: wrap; min-width: 0; }
.facts b { color: var(--ink); margin-left: 3px; }
.model-tag { color: var(--phosphor); font-weight: 700; }
.facts .put, .probe-inline .put { color: var(--put); }
.facts .call, .probe-inline .call { color: var(--call); }
.probe-inline {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
  padding: 1px 6px;
  min-height: 20px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-hi);
  font: 10px var(--font-display);
  letter-spacing: 0.05em;
  color: var(--ink-dim);
}
.probe-inline.lock { border-color: var(--phosphor-dim); background: var(--phosphor-wash); }
.probe-inline b { color: var(--ink); }
.idle { margin-left: auto; color: var(--ink-faint); font-size: 10px; }
.canvas {
  position: relative;
  width: 100%;
  min-width: 0;
  overflow: hidden;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
}
.svg { display: block; width: 100%; height: 100%; overflow: visible; }
.axis-cap {
  fill: var(--ink-faint);
  font: 600 9px var(--font-display);
  letter-spacing: 0.08em;
}
.curve {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}
.area { opacity: 1; }
.baseline { stroke: var(--rule-hi); stroke-width: 1; vector-effect: non-scaling-stroke; }
.marker line { stroke-width: 1.2; stroke-dasharray: 4 3; vector-effect: non-scaling-stroke; }
.marker.put line { stroke: var(--put); }
.marker.call line { stroke: var(--call); }
.marker.spot line { stroke: var(--ink); stroke-dasharray: none; stroke-width: 1.5; }
.marker.focus line { stroke: var(--phosphor); stroke-dasharray: none; stroke-width: 1.6; }
.marker text {
  fill: var(--ink-soft);
  font: 700 10px var(--font-display);
  letter-spacing: 0.04em;
  paint-order: stroke;
  stroke: var(--void);
  stroke-width: 3px;
}
.marker.put text { fill: var(--put-hi); }
.marker.call text { fill: var(--call-hi); }
.marker.spot text { fill: var(--ink); }
.marker.focus text { fill: var(--phosphor); }
.probe line { stroke: var(--phosphor); stroke-width: 1.2; stroke-dasharray: 2 3; vector-effect: non-scaling-stroke; }
.probe circle { fill: var(--phosphor); stroke: var(--void); stroke-width: 1.5; }
.probe-price {
  fill: var(--phosphor);
  font: 700 10px var(--font-data);
  paint-order: stroke;
  stroke: var(--void);
  stroke-width: 3px;
}
.x-axis line { stroke: var(--ink-faint); vector-effect: non-scaling-stroke; }
.x-axis text {
  fill: var(--ink-dim);
  font: 600 10px var(--font-data);
}
.empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--ink-ghost);
  margin: 0;
}
</style>
