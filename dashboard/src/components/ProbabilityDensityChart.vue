<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import type { OptionsProbability } from '@/api'
import { useChartSize } from '@/composables/useChartSize'
import { num, pctFrac, usd } from '@/format'

// Three.js is only needed after an operator explicitly opens the measured 3D
// surface. Keeping it out of the default Options route removes the heaviest
// dependency from the initial workspace download.
const RiskNeutral3DModel = defineAsyncComponent(() => import('@/components/RiskNeutral3DModel.vue'))

/**
 * 2D risk-neutral lognormal PDF of terminal price f(S_T).
 * Includes interactive Target Price & Risk-Neutral Probability Calculator.
 */
const props = withDefaults(
  defineProps<{
    probability?: OptionsProbability | null
    spot: number
    callWall?: number | null
    putWall?: number | null
    focusPrice?: number | null
    height?: number
    dte?: number | null
    vol?: number | null
    breakevens?: number[]
    strikes?: Array<{ strike: number; right: 'call' | 'put'; quantity?: number }>
    pop?: number | null
    strategyLabel?: string
  }>(),
  {
    probability: null,
    height: 260,
    callWall: null,
    putWall: null,
    focusPrice: null,
    dte: null,
    vol: null,
    breakevens: () => [],
    strikes: () => [],
    pop: null,
    strategyLabel: undefined,
  },
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

const targetPrice = ref<number | null>(null)
watch(
  () => props.spot,
  (s) => {
    if (s && targetPrice.value == null) {
      targetPrice.value = Math.round(s * 1.05 * 100) / 100
    }
  },
  { immediate: true },
)

const activeTargetPrice = computed(
  () => targetPrice.value ?? (props.spot ? Math.round(props.spot * 1.05 * 100) / 100 : 0),
)

const model = computed(() => {
  const p = props.probability
  const spotVal = Number(props.spot)
  const dteVal = p?.horizon_days ?? (props.dte != null && props.dte > 0 ? props.dte : 30)
  const ivVal =
    p?.atm_iv ??
    (props.vol != null && props.vol > 0 ? (props.vol > 2 ? props.vol / 100 : props.vol) : 0.3)

  if (!spotVal || spotVal <= 0 || !ivVal || ivVal <= 0 || !dteVal || dteVal <= 0) return null
  const T = Math.max(dteVal, 1) / 365
  const sigma = ivVal * Math.sqrt(T)
  if (!(sigma > 0)) return null
  const mu = Math.log(spotVal) - 0.5 * ivVal * ivVal * T
  const sigma2 = 2 * sigma
  let low = Math.max(0.01, (p?.expected_low ?? spotVal * (1 - sigma)) * 0.85)
  let high = (p?.expected_high ?? spotVal * (1 + sigma)) * 1.15
  if (props.focusPrice != null && props.focusPrice > 0) {
    low = Math.min(low, props.focusPrice * 0.96)
    high = Math.max(high, props.focusPrice * 1.04)
  }
  if (props.breakevens && props.breakevens.length) {
    for (const be of props.breakevens) {
      if (be > 0) {
        low = Math.min(low, be * 0.95)
        high = Math.max(high, be * 1.05)
      }
    }
  }
  return {
    mu,
    sigma,
    sigma2,
    T,
    iv: ivVal,
    low,
    high,
    horizon: dteVal,
    expectedMove: p?.expected_move ?? spotVal * sigma,
    expectedLow: p?.expected_low ?? spotVal - spotVal * sigma,
    expectedHigh: p?.expected_high ?? spotVal + spotVal * sigma,
  }
})

function cdfNormal(x: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const d = 0.3989423 * Math.exp((-x * x) / 2)
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
  return x >= 0 ? 1 - p : p
}

function density(x: number, mu: number, sigma: number): number {
  if (x <= 0 || sigma <= 0) return 0
  const z = (Math.log(x) - mu) / sigma
  return (1 / (x * sigma * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * z * z)
}

const targetCalc = computed(() => {
  const m = model.value
  const s = props.spot
  const tp = activeTargetPrice.value
  if (!m || !s || tp <= 0) return null

  const chgPct = ((tp - s) / s) * 100
  const zScore = (Math.log(tp / s) - (m.mu - Math.log(s))) / m.sigma
  const d2 = (Math.log(s / tp) - 0.5 * m.sigma * m.sigma) / m.sigma
  const probAbove = cdfNormal(d2)
  const probBelow = 1 - probAbove

  let probBetweenWalls: number | null = null
  if (props.putWall && props.callWall && props.putWall < props.callWall) {
    const d2Put = (Math.log(s / props.putWall) - 0.5 * m.sigma * m.sigma) / m.sigma
    const d2Call = (Math.log(s / props.callWall) - 0.5 * m.sigma * m.sigma) / m.sigma
    probBetweenWalls = Math.max(0, cdfNormal(d2Put) - cdfNormal(d2Call))
  }

  return {
    tp,
    chgPct,
    zScore,
    probAbove,
    probBelow,
    probBetweenWalls,
  }
})

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
  const baseBottom = (H.value - pad.value.b).toFixed(2)
  const area = `${line} L${pts[pts.length - 1].x.toFixed(2)},${baseBottom} L${pts[0].x.toFixed(2)},${baseBottom} Z`

  // Split into lower tail (put wash below spot) and upper tail (call wash above spot)
  const spotPrice = props.spot || (m.low + m.high) / 2
  const spotU = (spotPrice - m.low) / (m.high - m.low)
  const spotX = pad.value.l + Math.max(0, Math.min(1, spotU)) * plotW
  const spotDens = density(spotPrice, m.mu, m.sigma)
  const spotY = H.value - pad.value.b - (spotDens / maxD) * plotH

  // Lower tail (prices <= spot)
  const lowerPts = pts.filter((p) => p.price <= spotPrice)
  const lowerSegments = lowerPts.map(
    (p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(2)},${p.y.toFixed(2)}`,
  )
  lowerSegments.push(`L${spotX.toFixed(2)},${spotY.toFixed(2)}`)
  const putArea = `${lowerSegments.join(' ')} L${spotX.toFixed(2)},${baseBottom} L${pts[0].x.toFixed(2)},${baseBottom} Z`

  // Upper tail (prices >= spot)
  const upperPts = pts.filter((p) => p.price >= spotPrice)
  const upperSegments = [`M${spotX.toFixed(2)},${spotY.toFixed(2)}`]
  upperPts.forEach((p) => upperSegments.push(`L${p.x.toFixed(2)},${p.y.toFixed(2)}`))
  const callArea = `${upperSegments.join(' ')} L${pts[pts.length - 1].x.toFixed(2)},${baseBottom} L${spotX.toFixed(2)},${baseBottom} Z`

  return { pts, line, area, putArea, callArea, maxD, m, plotH, plotW, spotX, spotY }
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

const oneSigmaBounds = computed(() => {
  const c = curve.value
  if (!c) return null
  const xLo = xOfPrice(c.m.expectedLow)
  const xHi = xOfPrice(c.m.expectedHigh)
  if (xLo == null || xHi == null) return null
  return { xLo, xHi, expectedLow: c.m.expectedLow, expectedHigh: c.m.expectedHigh }
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
  if (props.breakevens && props.breakevens.length) {
    props.breakevens.forEach((be, i) => {
      add(`be-${i}`, be, 'BE', 'focus')
    })
  }
  if (props.strikes && props.strikes.length) {
    props.strikes.forEach((stk, i) => {
      add(`strike-${i}`, stk.strike, stk.right === 'call' ? 'CALL K' : 'PUT K', stk.right)
    })
  }
  if (activeTargetPrice.value > 0 && activeTargetPrice.value !== props.spot) {
    add('target', activeTargetPrice.value, 'TARGET', 'target')
  }
  const sorted = [...items].sort((a, b) => a.x - b.x)
  const MIN_GAP = 54
  let prevX = -Infinity
  let lane = 0
  return sorted.map((item) => {
    if (item.x - prevX < MIN_GAP) lane = (lane + 1) % 3
    else lane = 0
    prevX = item.x
    return {
      ...item,
      labelY: pad.value.t - 8 - lane * 10,
    }
  })
})

function setQuickTarget(deltaPct: number): void {
  if (!props.spot) return
  targetPrice.value = Math.round(props.spot * (1 + deltaPct / 100) * 100) / 100
}

function setTargetToLevel(price: number | null | undefined): void {
  if (price != null && price > 0) {
    targetPrice.value = Math.round(price * 100) / 100
  }
}

const activeProbability = computed<OptionsProbability | null>(() => {
  if (props.probability?.available && props.probability.atm_iv && props.probability.horizon_days) {
    return props.probability
  }
  const m = model.value
  if (!m || !props.spot) return null
  return {
    available: true,
    method: 'black_scholes_lognormal',
    atm_iv: m.iv,
    horizon_days: m.horizon,
    expected_move: m.expectedMove,
    expected_low: m.expectedLow,
    expected_high: m.expectedHigh,
    prob_above_call_wall: null,
    prob_below_put_wall: null,
    prob_between_walls: null,
  }
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

function probeDetails(
  pt: { price: number; dens: number; x: number; y: number },
  source: 'lock' | 'hover',
) {
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

const viewMode = ref<'2d' | '3d'>('2d')
// A 3D surface must be based on the same measured inputs as the 2D density.
// Do not let an unavailable chain turn into a plausible-looking model.
const canRender3d = computed(() => model.value !== null)

watch(canRender3d, (available) => {
  if (!available && viewMode.value === '3d') viewMode.value = '2d'
})
</script>

<template>
  <div class="pdf-chart">
    <div class="head">
      <div class="mode-toggle mini-segment">
        <button
          type="button"
          class="label"
          :class="{ on: viewMode === '2d' }"
          @click="viewMode = '2d'"
        >
          2D DEN
        </button>
        <button
          type="button"
          class="label"
          :class="{ on: viewMode === '3d' }"
          :disabled="!canRender3d"
          :title="
            canRender3d
              ? 'Inspect the measured 3D risk-neutral surface'
              : 'Need ATM IV + expiry for a 3D model'
          "
          @click="viewMode = '3d'"
        >
          3D MODEL
        </button>
      </div>

      <div v-if="model" class="facts">
        <span class="label model-tag">{{
          viewMode === '3d' ? '3D SURFACE MODEL' : '2D PDF f(S_T)'
        }}</span>
        <span class="label"
          >IV <b class="fig">{{ pctFrac(model.iv, 1) }}</b></span
        >
        <span class="label">{{ model.horizon }}D</span>
        <span class="label"
          >±1σ <b class="fig">{{ usd(model.expectedMove) }}</b></span
        >
        <span class="label put">{{ usd(model.expectedLow) }}</span>
        <span class="label">→</span>
        <span class="label call">{{ usd(model.expectedHigh) }}</span>
      </div>
      <div v-if="focus && viewMode === '2d'" class="probe-inline" :class="focus.source">
        <span class="label">{{ focus.source === 'lock' ? 'LOCK' : 'PROBE' }}</span>
        <b class="fig">{{ usd(focus.price) }}</b>
        <span class="call">P(S&gt;) {{ pctFrac(focus.probAbove, 0) }}</span>
        <span class="put">P(S&lt;) {{ pctFrac(focus.probBelow, 0) }}</span>
      </div>
      <span v-else-if="viewMode === '2d'" class="idle label">Hover curve · lock a GEX strike</span>
    </div>

    <!-- 3D Surface Model view -->
    <RiskNeutral3DModel
      v-if="viewMode === '3d' && canRender3d"
      :probability="activeProbability"
      :spot="spot"
      :call-wall="callWall"
      :put-wall="putWall"
      :focus-price="focusPrice"
      :height="Math.max(260, height)"
    />

    <!-- 2D Canvas SVG View -->
    <div v-else ref="hostRef" class="canvas" :style="{ height: `${H}px` }">
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
        <!-- 1σ Expected Move Shaded Band -->
        <rect
          v-if="oneSigmaBand"
          class="sigma-band"
          :x="oneSigmaBand.x"
          :y="pad.t"
          :width="oneSigmaBand.width"
          :height="H - pad.t - pad.b"
        />

        <!-- 1σ Expected Move Boundary Lines -->
        <g v-if="oneSigmaBounds" class="sigma-bounds">
          <line
            :x1="oneSigmaBounds.xLo"
            :x2="oneSigmaBounds.xLo"
            :y1="pad.t"
            :y2="H - pad.b"
            class="sigma-bound low"
          />
          <line
            :x1="oneSigmaBounds.xHi"
            :x2="oneSigmaBounds.xHi"
            :y1="pad.t"
            :y2="H - pad.b"
            class="sigma-bound high"
          />
          <text :x="oneSigmaBounds.xLo" :y="pad.t - 4" text-anchor="middle" class="sigma-label low">
            -1σ {{ num(oneSigmaBounds.expectedLow, 0) }}
          </text>
          <text
            :x="oneSigmaBounds.xHi"
            :y="pad.t - 4"
            text-anchor="middle"
            class="sigma-label high"
          >
            +1σ {{ num(oneSigmaBounds.expectedHigh, 0) }}
          </text>
        </g>

        <!-- Base Axes -->
        <line class="baseline" :x1="pad.l" :x2="W - pad.r" :y1="H - pad.b" :y2="H - pad.b" />
        <line class="baseline" :x1="pad.l" :x2="pad.l" :y1="pad.t" :y2="H - pad.b" />
        <text class="axis-cap" :x="(pad.l + W - pad.r) / 2" :y="H - 4" text-anchor="middle">
          TERMINAL PRICE $
        </text>
        <text
          class="axis-cap y-cap"
          :x="12"
          :y="(pad.t + H - pad.b) / 2"
          text-anchor="middle"
          :transform="`rotate(-90 12 ${(pad.t + H - pad.b) / 2})`"
        >
          REL DENSITY
        </text>

        <!-- 2D Lognormal Tails: Crimson Lower Tail, Emerald Upper Tail -->
        <path class="area put-tail" :d="curve.putArea" fill="var(--put-wash)" />
        <path class="area call-tail" :d="curve.callArea" fill="var(--call-wash)" />
        <path class="curve" :d="curve.line" />

        <!-- Strike Level Markers -->
        <g v-for="m in markers" :key="m.key" class="marker" :class="m.cls">
          <line :x1="m.x" :x2="m.x" :y1="pad.t" :y2="H - pad.b" />
          <text :x="m.x" :y="m.labelY" text-anchor="middle">{{ m.label }}</text>
        </g>

        <!-- Interactive Probe / Cursor Crosshair -->
        <g v-if="focus" class="probe">
          <line :x1="focus.x" :x2="focus.x" :y1="focus.y" :y2="H - pad.b" class="probe-line" />
          <circle :cx="focus.x" :cy="focus.y" r="4.5" class="probe-dot" />
          <g
            class="probe-tooltip"
            :transform="`translate(${focus.x}, ${Math.max(pad.t + 16, focus.y - 12)})`"
          >
            <rect :x="-44" :y="-16" width="88" height="18" rx="2" class="probe-tip-bg" />
            <text text-anchor="middle" y="-3.5" class="probe-tip-text">
              {{ usd(focus.price) }} · {{ pctFrac(focus.probAbove, 0) }} P(&gt;)
            </text>
          </g>
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

    <!-- Integrated Risk-Neutral Target & Probability Calculator -->
    <div v-if="model" class="calc-panel">
      <div class="calc-head">
        <span class="calc-title label">TARGET PRICE & RISK CALCULATOR</span>
        <span class="calc-sub label"
          >{{ model.horizon }}D HORIZON · IV {{ pctFrac(model.iv, 1) }}</span
        >
      </div>
      <div class="calc-body">
        <div class="calc-inputs">
          <div class="input-row">
            <label class="label" for="target-price-val">TARGET $</label>
            <input
              id="target-price-val"
              type="number"
              :value="activeTargetPrice"
              :min="Math.round(spot * 0.5)"
              :max="Math.round(spot * 1.5)"
              step="1"
              class="target-num-input"
              @input="targetPrice = Number(($event.target as HTMLInputElement).value)"
            />
          </div>
          <input
            type="range"
            :value="activeTargetPrice"
            :min="Math.round(spot * 0.8)"
            :max="Math.round(spot * 1.2)"
            step="0.5"
            class="target-slider"
            @input="targetPrice = Number(($event.target as HTMLInputElement).value)"
          />
          <div class="target-chips">
            <button type="button" class="chip-btn" @click="setQuickTarget(-10)">-10%</button>
            <button type="button" class="chip-btn" @click="setQuickTarget(-5)">-5%</button>
            <button type="button" class="chip-btn" @click="setTargetToLevel(model.expectedLow)">
              -1σ
            </button>
            <button type="button" class="chip-btn" @click="setTargetToLevel(model.expectedHigh)">
              +1σ
            </button>
            <button type="button" class="chip-btn" @click="setQuickTarget(5)">+5%</button>
            <button type="button" class="chip-btn" @click="setQuickTarget(10)">+10%</button>
            <button
              v-if="putWall"
              type="button"
              class="chip-btn put"
              @click="setTargetToLevel(putWall)"
            >
              PUT WALL
            </button>
            <button
              v-if="callWall"
              type="button"
              class="chip-btn call"
              @click="setTargetToLevel(callWall)"
            >
              CALL WALL
            </button>
            <button
              v-for="(be, idx) in breakevens"
              :key="`be-chip-${idx}`"
              type="button"
              class="chip-btn accent"
              @click="setTargetToLevel(be)"
            >
              BE {{ num(be, 0) }}
            </button>
          </div>
        </div>
        <div v-if="targetCalc" class="calc-metrics">
          <div class="calc-tile">
            <span class="label">TARGET RETURN</span>
            <strong class="fig" :class="targetCalc.chgPct >= 0 ? 'call' : 'put'">
              {{ targetCalc.chgPct >= 0 ? '+' : '' }}{{ num(targetCalc.chgPct, 1) }}%
            </strong>
          </div>
          <div class="calc-tile">
            <span class="label">PROB EXPIRE ABOVE</span>
            <strong class="fig call">{{ pctFrac(targetCalc.probAbove, 1) }}</strong>
          </div>
          <div class="calc-tile">
            <span class="label">PROB EXPIRE BELOW</span>
            <strong class="fig put">{{ pctFrac(targetCalc.probBelow, 1) }}</strong>
          </div>
          <div class="calc-tile">
            <span class="label">Z-SCORE (DIST)</span>
            <strong class="fig"
              >{{ targetCalc.zScore >= 0 ? '+' : '' }}{{ num(targetCalc.zScore, 2) }}σ</strong
            >
          </div>
          <div v-if="targetCalc.probBetweenWalls != null" class="calc-tile">
            <span class="label">PROB INSIDE WALLS</span>
            <strong class="fig accent">{{ pctFrac(targetCalc.probBetweenWalls, 1) }}</strong>
          </div>
          <div v-if="pop != null" class="calc-tile">
            <span class="label">STRATEGY POP</span>
            <strong class="fig" :class="pop >= 0.5 ? 'call' : 'put'">{{ pctFrac(pop, 1) }}</strong>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Surface glass token: var(--glass-surface-hi) */
.pdf-chart {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s2) var(--s3) var(--s3);
}
.head {
  display: flex;
  align-items: center;
  gap: 6px 12px;
  min-height: 28px;
  flex: 0 0 auto;
  flex-wrap: wrap;
}
.facts {
  display: flex;
  align-items: center;
  gap: 6px 12px;
  flex-wrap: wrap;
  min-width: 0;
}
.facts b {
  color: var(--ink);
  margin-left: 3px;
}
.model-tag {
  color: var(--phosphor);
  font-weight: 700;
}
.facts .put,
.probe-inline .put {
  color: var(--put-hi);
}
.facts .call,
.probe-inline .call {
  color: var(--call-hi);
}
.probe-inline {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  padding: 4px 10px;
  min-height: 26px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-hi);
  font: 10px var(--font-display);
  letter-spacing: 0.05em;
  color: var(--ink-dim);
}
.probe-inline.lock {
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.probe-inline b {
  color: var(--ink);
}
.idle {
  margin-left: auto;
  color: var(--ink-dim);
  font-size: 10px;
}
.canvas {
  position: relative;
  width: 100%;
  min-width: 0;
  overflow: hidden;
  background: var(--void);
  border: var(--hair) solid var(--rule-hi);
}
.svg {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}
.sigma-band {
  fill: var(--void-lift);
  opacity: 0.65;
}
.sigma-bound {
  stroke: var(--rule-hi);
  stroke-width: 1px;
  stroke-dasharray: 3 3;
  vector-effect: non-scaling-stroke;
  opacity: 0.85;
}
.sigma-label {
  fill: var(--ink-faint);
  font: 700 var(--t-nano) var(--font-display);
  letter-spacing: 0.04em;
  paint-order: stroke;
  stroke: var(--void);
  stroke-width: 3px;
}
.sigma-label.low {
  fill: var(--put-hi);
}
.sigma-label.high {
  fill: var(--call-hi);
}

.curve {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 2px;
  vector-effect: non-scaling-stroke;
}
.area.put-tail {
  fill: var(--put-wash);
  opacity: 0.85;
  transition: opacity 0.15s ease;
}
.area.call-tail {
  fill: var(--call-wash);
  opacity: 0.85;
  transition: opacity 0.15s ease;
}
.baseline {
  stroke: var(--rule-hi);
  stroke-width: 1px;
  vector-effect: non-scaling-stroke;
}
.marker line {
  stroke-width: 1.25px;
  stroke-dasharray: 4 3;
  vector-effect: non-scaling-stroke;
  transition: stroke 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}
.marker.put line {
  stroke: var(--put-hi);
}
.marker.call line {
  stroke: var(--call-hi);
}
.marker.spot line {
  stroke: var(--ink);
  stroke-dasharray: none;
  stroke-width: 1.5px;
}
.marker.focus line {
  stroke: var(--phosphor);
  stroke-dasharray: none;
  stroke-width: 1.5px;
}
.marker.target line {
  stroke: var(--warn);
  stroke-dasharray: 2 2;
  stroke-width: 1.5px;
}
.marker text {
  fill: var(--ink-soft);
  font: 700 10px var(--font-display);
  letter-spacing: 0.04em;
  paint-order: stroke;
  stroke: var(--void);
  stroke-width: 3px;
  transition: fill 0.15s ease;
}
.marker.put text {
  fill: var(--put-hi);
}
.marker.call text {
  fill: var(--call-hi);
}
.marker.spot text {
  fill: var(--ink);
}
.marker.focus text {
  fill: var(--phosphor);
}
.marker.target text {
  fill: var(--warn);
}
.probe {
  transition:
    transform 0.15s cubic-bezier(0.16, 1, 0.3, 1),
    opacity 0.15s ease;
}
.probe-line {
  stroke: var(--phosphor);
  stroke-width: 1.25px;
  stroke-dasharray: 2 3;
  vector-effect: non-scaling-stroke;
}
.probe-dot {
  fill: var(--phosphor);
  stroke: var(--void);
  stroke-width: 1.5px;
}
.probe-tip-bg {
  fill: var(--panel-raise);
  stroke: var(--phosphor-dim);
  stroke-width: 1px;
}
.probe-tip-text {
  fill: var(--phosphor);
  font: 700 var(--t-nano) var(--font-data);
}
.x-axis line {
  stroke: var(--rule-hi);
  vector-effect: non-scaling-stroke;
}
.x-axis text {
  fill: var(--ink-dim);
  font: 600 10px var(--font-data);
}
.empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--ink-dim);
  margin: 0;
}

/* Calculator */
.calc-panel {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-hi);
}
.calc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: var(--s2);
  border-bottom: var(--hair) solid var(--rule);
  flex-wrap: wrap;
}
.calc-title {
  color: var(--phosphor);
  font-weight: 700;
  letter-spacing: 0.08em;
}
.calc-sub {
  color: var(--ink-dim);
}
.calc-body {
  display: flex;
  align-items: stretch;
  gap: var(--s4);
  flex-wrap: wrap;
}
.calc-inputs {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  flex: 0 0 200px;
  min-width: 0;
}
.input-row {
  display: flex;
  align-items: center;
  gap: var(--s2);
}
.input-row .label {
  color: var(--ink-dim);
  font: 700 10px var(--font-display);
}
.target-num-input {
  width: 96px;
  padding: 4px 8px;
  font: 700 13px var(--font-data);
  color: var(--ink);
  background: var(--void);
  border: var(--hair) solid var(--rule-hi);
}
.target-slider {
  width: 100%;
  accent-color: var(--phosphor);
  cursor: pointer;
  height: 18px;
}
.target-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}
.chip-btn {
  padding: 2px 6px;
  font: 700 var(--t-nano) var(--font-display);
  letter-spacing: 0.04em;
  color: var(--ink-dim);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  cursor: pointer;
  transition: all 0.1s ease;
}
.chip-btn:hover {
  color: var(--ink);
  border-color: var(--rule-hi);
}
.chip-btn.call {
  color: var(--call-hi);
  border-color: var(--call-dim);
}
.chip-btn.put {
  color: var(--put-hi);
  border-color: var(--put-dim);
}
.chip-btn.accent {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}
.calc-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: var(--s2);
  flex: 1 1 auto;
  min-width: 0;
}
.calc-tile {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  background: var(--panel);
  border: var(--hair) solid var(--rule);
}
.calc-tile .label {
  color: var(--ink-dim);
  font: 700 var(--t-nano) var(--font-display);
  letter-spacing: 0.06em;
}
.calc-tile .fig {
  font: 700 0.9375rem var(--font-data);
  color: var(--ink);
}
.calc-tile .fig.call {
  color: var(--call-hi);
}
.calc-tile .fig.put {
  color: var(--put-hi);
}
.calc-tile .fig.accent {
  color: var(--phosphor);
}

.mode-toggle.mini-segment,
.pdf-chart :deep(.mini-segment) {
  display: flex;
  min-height: 26px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void);
  overflow: hidden;
}
.pdf-chart .mode-toggle button {
  padding: 0 10px;
  color: var(--ink-dim);
  border-right: var(--hair) solid var(--rule);
  font: 600 10px var(--font-display);
  letter-spacing: 0.05em;
  min-height: 26px;
  cursor: pointer;
  background: transparent;
}
.pdf-chart .mode-toggle button:last-child {
  border-right: 0;
}
.pdf-chart .mode-toggle button.on {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  box-shadow: inset 0 -2px var(--phosphor);
}
.pdf-chart .mode-toggle button:disabled {
  cursor: not-allowed;
  color: var(--ink-faint);
  background: var(--panel);
}
</style>
