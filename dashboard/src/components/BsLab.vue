<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import {
  bsCall,
  bsPutPrice,
  bsD1,
  bsGamma,
  bsVega,
  bsThetaDay,
  greekCurves,
  normCdf,
  type GreekKind,
} from '@/charts/landing-viz'

/**
 * Interactive Black-Scholes workbench for the public landing page.
 *
 * Sliders drive the actual closed-form formulas: option value, delta, gamma,
 * vega, or per-day theta across the strike axis, with an ATM marker the
 * operator can drag. The readouts recompute live from the same inputs.
 *
 * Structural anatomy only — S is a unitless model spot, never a quote.
 * Live per-symbol chains appear after operator sign-in.
 */

gsap.registerPlugin(ScrollTrigger)

/* ── model state (structural parameters) ──────────────────────────────────── */
const sigma = ref(0.3) // implied vol, 5%–80%
const days = ref(30) // calendar days to expiry, 2–180
const strike = ref(100) // selected K, set by slider or chart drag

const S = 100 // model spot — fixed so moneyness stays readable
const r = 0.05 // risk-free carry (structural constant)
const q = 0 // dividend yield (structural constant)

const T = computed(() => Math.max(days.value, 1) / 365)
const sigT = computed(() => sigma.value * Math.sqrt(T.value))

/* ── Greek selection ──────────────────────────────────────────────────────── */
interface GreekDef {
  id: GreekKind
  label: string
  formula: string
}
const GREEKS: GreekDef[] = [
  { id: 'value', label: 'VALUE', formula: 'V_call = e^(−rT)·[S·Φ(d₁) − K·Φ(d₂)]' },
  { id: 'delta', label: 'DELTA Δ', formula: 'Δ_call = e^(−qT)·Φ(d₁)' },
  { id: 'gamma', label: 'GAMMA Γ', formula: 'Γ = φ(d₁)/(S·σ·√T)' },
  { id: 'vega', label: 'VEGA ν', formula: 'ν = S·φ(d₁)·√T/100' },
  { id: 'theta', label: 'THETA Θ', formula: 'Θ_day = ∂V/∂t ÷ 365' },
]
const greekIndex = ref(0)
const activeGreek = computed(() => GREEKS[greekIndex.value]!)

/* ── geometry over the strike axis (normalised to a fixed viewBox) ────────── */
const K_LOW = 60
const K_HIGH = 140
const N_PTS = 121

const VB_W = 640
const VB_H = 300
const M = { l: 16, r: 16, t: 28, b: 32 }
const plotW = VB_W - M.l - M.r
const plotH = VB_H - M.t - M.b
const midY = M.t + plotH / 2

const curves = computed(() =>
  greekCurves(activeGreek.value.id, S, T.value, sigma.value, r, q, K_LOW, K_HIGH, N_PTS),
)

function toPath(pts: { x: number; y: number }[]): string {
  const xOf = (v: number): number => M.l + (v / 100) * plotW
  const yOf = (v: number): number => midY - v * (plotH / 2)
  return pts
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${xOf(p.x).toFixed(1)},${yOf(p.y).toFixed(1)}`)
    .join('')
}

const callPath = computed(() => toPath(curves.value.call))
const putPath = computed(() => toPath(curves.value.put))

/* ── domain-aware helpers: raw value -> plot y, using the curves' own range ── */
function plotYOfRaw(v: number): number {
  const { lo, hi } = curves.value.domain
  const span = hi - lo || 1
  return midY - ((2 * (v - lo)) / span - 1) * (plotH / 2)
}

/** Zero line only exists when the plotted range actually crosses zero. */
const zeroY = computed((): number | null => {
  const { lo, hi } = curves.value.domain
  return lo <= 0 && hi >= 0 ? plotYOfRaw(0) : null
})

/* ── marker dots pinned on both curves at the selected strike ─────────────── */
const strikeIdx = computed(() =>
  Math.min(Math.max(Math.round(((strike.value - K_LOW) / (K_HIGH - K_LOW)) * (N_PTS - 1)), 0), N_PTS - 1),
)
const callDotY = computed(() => midY - (curves.value.call[strikeIdx.value]?.y ?? 0) * (plotH / 2))
const putDotY = computed(() => midY - (curves.value.put[strikeIdx.value]?.y ?? 0) * (plotH / 2))

/* ── intrinsic payoff boundary (value tab): the expiry limit of both curves ── */
const boundaryPath = computed((): { call: string; put: string } | null => {
  if (activeGreek.value.id !== 'value') return null
  const toBoundary = (intrinsic: (K: number) => number): string =>
    curves.value.strikes
      .map(
        (K, i) =>
          `${i === 0 ? 'M' : 'L'}${(M.l + ((K - K_LOW) / (K_HIGH - K_LOW)) * plotW).toFixed(1)},${plotYOfRaw(intrinsic(K)).toFixed(1)}`,
      )
      .join('')
  return {
    call: toBoundary((K) => Math.max(S - K, 0)),
    put: toBoundary((K) => Math.max(K - S, 0)),
  }
})
const boundaryNote = computed(() => {
  if (!boundaryPath.value) return null
  return { x: tickX(S) - 8, y: plotYOfRaw(0) - 8 }
})

/* ── ATM marker position on the shared axis ───────────────────────────────── */
const atmX = computed(() => M.l + ((strike.value - K_LOW) / (K_HIGH - K_LOW)) * plotW)

/* ── static grid geometry ─────────────────────────────────────────────────── */
const gridH = [0, 1, 2, 3, 4].map((i) => M.t + (plotH * i) / 4)
const gridW = [0, 1, 2, 3, 4].map((i) => M.l + (plotW * i) / 4)
const strikeTicks = [70, 80, 90, 100, 110, 120, 130]
const tickX = (K: number): number => M.l + ((K - K_LOW) / (K_HIGH - K_LOW)) * plotW

/* ── ATM readouts — all live from the same closed forms ───────────────────── */
const d1Atm = computed(() => bsD1({ S, K: strike.value, T: T.value, sigma: sigma.value, r, q }))
const disc = computed(() => Math.exp(-q * T.value))
const callDelta = computed(() => disc.value * normCdf(d1Atm.value))
const putDelta = computed(() => -disc.value * normCdf(-d1Atm.value))

const callReadout = computed((): string => {
  switch (activeGreek.value.id) {
    case 'value':
      return `$${bsCall({ S, K: strike.value, T: T.value, sigma: sigma.value, r, q }).toFixed(2)}`
    case 'delta':
      return `+${callDelta.value.toFixed(3)}`
    case 'gamma':
      return bsGamma({ S, K: strike.value, T: T.value, sigma: sigma.value, r, q }).toFixed(4)
    case 'vega':
      return bsVega({ S, K: strike.value, T: T.value, sigma: sigma.value, r, q }).toFixed(3)
    case 'theta':
      return `${bsThetaDay({ S, K: strike.value, T: T.value, sigma: sigma.value, r, q }, 'call').toFixed(3)}/d`
    default:
      return '—'
  }
})
const putReadout = computed((): string => {
  switch (activeGreek.value.id) {
    case 'value':
      return `$${bsPutPrice({ S, K: strike.value, T: T.value, sigma: sigma.value, r, q }).toFixed(2)}`
    case 'delta':
      return putDelta.value.toFixed(3)
    case 'gamma':
      return bsGamma({ S, K: strike.value, T: T.value, sigma: sigma.value, r, q }).toFixed(4)
    case 'vega':
      return bsVega({ S, K: strike.value, T: T.value, sigma: sigma.value, r, q }).toFixed(3)
    case 'theta':
      return `${bsThetaDay({ S, K: strike.value, T: T.value, sigma: sigma.value, r, q }, 'put').toFixed(3)}/d`
    default:
      return '—'
  }
})

/* ── pointer interaction: click/drag anywhere on the plot sets the strike ──── */
const svgRef = ref<SVGSVGElement | null>(null)
let dragging = false

function strikeFromEvent(e: PointerEvent): void {
  const svg = svgRef.value
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  const frac = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1)
  const vbFrac = (frac * VB_W - M.l) / plotW
  strike.value = Math.round(K_LOW + Math.min(Math.max(vbFrac, 0), 1) * (K_HIGH - K_LOW))
}
function onDown(e: PointerEvent): void {
  dragging = true
  ;(e.currentTarget as Element).setPointerCapture?.(e.pointerId)
  strikeFromEvent(e)
}
function onMove(e: PointerEvent): void {
  if (dragging) strikeFromEvent(e)
}
function onUp(): void {
  dragging = false
}

/* ── entrance reveal ──────────────────────────────────────────────────────── */
let ctx: gsap.Context | undefined
onMounted(() => {
  ctx = gsap.context(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    gsap.from('.bs-lab .lab-reveal', {
      opacity: 0,
      y: 18,
      stagger: 0.08,
      duration: 0.55,
      ease: 'power2.out',
      scrollTrigger: {
        trigger: '.bs-lab',
        start: 'top 78%',
        toggleActions: 'play none none none',
      },
    })
    document.querySelectorAll<SVGPathElement>('.bs-curve').forEach((p) => {
      const len = p.getTotalLength()
      gsap.fromTo(
        p,
        { strokeDasharray: len, strokeDashoffset: len },
        {
          strokeDashoffset: 0,
          duration: 1.1,
          ease: 'power2.inOut',
          // Clear the dash inline styles afterwards: the path `d` is reactive
          // (sliders rebuild it), and a stale dasharray tuned to the intro
          // length would show gaps on longer redrawn curves.
          onComplete: () => gsap.set(p, { clearProps: 'strokeDasharray,strokeDashoffset' }),
          scrollTrigger: {
            trigger: '.bs-lab',
            start: 'top 72%',
            toggleActions: 'play none none none',
          },
        },
      )
    })
  })
})
onBeforeUnmount(() => ctx?.revert())
</script>

<template>
  <figure
    class="bs-lab"
    aria-label="Interactive Black-Scholes model. Adjust volatility and expiry; click the chart to move the strike."
  >
    <span class="frame-beam" aria-hidden="true" />

    <figcaption class="lab-head">
      <div class="lab-title lab-reveal">
        <span class="fig-label">BLACK–SCHOLES WORKBENCH</span>
        <span class="fig-state">STRUCTURAL MODEL · DRAG TO EXPLORE</span>
      </div>

      <div class="controls lab-reveal">
        <label class="control">
          <span class="ctl-name">Implied vol σ</span>
          <input v-model.number="sigma" type="range" min="0.05" max="0.8" step="0.01" />
          <output class="ctl-val">{{ (sigma * 100).toFixed(0) }}%</output>
        </label>
        <label class="control">
          <span class="ctl-name">Expiry T</span>
          <input v-model.number="days" type="range" min="2" max="180" step="1" />
          <output class="ctl-val">{{ days }}d</output>
        </label>
      </div>

      <div class="greek-tabs lab-reveal" role="tablist" aria-label="Choose the plotted quantity">
        <button
          v-for="(g, i) in GREEKS"
          :key="g.id"
          role="tab"
          :aria-selected="i === greekIndex"
          :class="{ on: i === greekIndex }"
          @click="greekIndex = i"
        >
          {{ g.label }}
        </button>
      </div>
    </figcaption>

    <div class="plot-stage lab-reveal">
      <svg
        ref="svgRef"
        role="img"
        aria-label="Black-Scholes option values across the strike axis, with the selected strike marked on both legs and the expiry payoff boundary shown."
        :viewBox="`0 0 ${VB_W} ${VB_H}`"
        preserveAspectRatio="xMidYMid meet"
        @pointerdown="onDown"
        @pointermove="onMove"
        @pointerup="onUp"
        @pointercancel="onUp"
      >
        <!-- measurement grid -->
        <g class="grid">
          <line v-for="(y, i) in gridH" :key="`h${i}`" x1="16" :y1="y" :x2="VB_W - 16" :y2="y" />
          <line v-for="(x, i) in gridW" :key="`w${i}`" :x1="x" y1="28" :x2="x" :y2="VB_H - 32" />
        </g>
        <!-- zero line, only when the plotted range crosses zero -->
        <line v-if="zeroY !== null" class="zero-line" x1="16" :y1="zeroY" :x2="VB_W - 16" :y2="zeroY" />

        <!-- intrinsic payoff boundary: the expiry limit the smooth curves sit above -->
        <g v-if="boundaryPath" class="boundary">
          <path :d="boundaryPath.put" />
          <path :d="boundaryPath.call" />
          <text
            v-if="boundaryNote"
            class="plot-note"
            :x="boundaryNote.x"
            :y="boundaryNote.y"
            text-anchor="end"
          >
            payoff boundary at expiry
          </text>
        </g>

        <!-- curves -->
        <path class="bs-curve put" :d="putPath" />
        <path class="bs-curve call" :d="callPath" />

        <!-- draggable strike marker, dots pinned on both curves -->
        <g class="atm-marker">
          <line :x1="atmX" y1="22" :x2="atmX" :y2="VB_H - 30" />
          <circle class="mk call" :cx="atmX" :cy="callDotY" r="3" />
          <circle class="mk put" :cx="atmX" :cy="putDotY" r="3" />
        </g>

        <!-- strike axis ticks -->
        <g class="ticks">
          <text v-for="K in strikeTicks" :key="K" :x="tickX(K)" :y="VB_H - 14" text-anchor="middle">
            {{ K }}
          </text>
          <text :x="tickX(K_HIGH)" :y="VB_H - 14" text-anchor="end" class="dim">strike K →</text>
        </g>
      </svg>

      <p class="plot-hint">Click or drag inside the plot · K = ${{ strike }}</p>
    </div>

    <div class="lab-footer lab-reveal">
      <dl class="readouts">
        <div class="ro">
          <dt>Call</dt>
          <dd class="call-ink">{{ callReadout }}</dd>
        </div>
        <div class="ro">
          <dt>Put</dt>
          <dd class="put-ink">{{ putReadout }}</dd>
        </div>
        <div class="ro wide">
          <dt>{{ activeGreek.label }} identity</dt>
          <dd class="formula">{{ activeGreek.formula }}</dd>
        </div>
      </dl>
      <strong>d₁ = {{ d1Atm.toFixed(3) }} · σ√T = {{ sigT.toFixed(3) }} · r = 5%</strong>
    </div>
  </figure>
</template>

<style scoped>
.bs-lab {
  position: relative;
  margin: 0;
  padding: 18px 20px 16px;
  overflow: hidden;
  color: var(--ink);
  border: var(--hair) solid var(--rule-hi);
  border-top: 2px solid var(--phosphor);
  background:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px), var(--panel);
  background-size: 28px 28px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
}

.lab-head {
  display: grid;
  gap: 14px;
  padding-bottom: 12px;
  border-bottom: var(--hair) solid var(--rule);
}
.lab-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.fig-label {
  color: var(--ink);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}
.fig-state {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 650;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}

/* ── controls ── */
.controls {
  display: flex;
  flex-wrap: wrap;
  gap: 18px 28px;
}
.control {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 220px;
  flex: 1 1 220px;
}
.ctl-name {
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  white-space: nowrap;
}
.ctl-val {
  min-width: 38px;
  text-align: right;
  color: var(--phosphor);
  font-family: var(--font-data);
  font-size: 11px;
  font-weight: 700;
}
input[type='range'] {
  flex: 1 1 auto;
  appearance: none;
  height: 3px;
  background: var(--rule-hi);
  border-radius: 1px;
  outline-offset: 4px;
  cursor: ew-resize;
}
input[type='range']::-webkit-slider-thumb {
  appearance: none;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: var(--phosphor);
  border: 2px solid var(--void);
  cursor: grab;
}
input[type='range']::-moz-range-thumb {
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: var(--phosphor);
  border: 2px solid var(--void);
  cursor: grab;
}

/* ── greek tabs ── */
.greek-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.greek-tabs button {
  padding: 6px 12px;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out);
}
.greek-tabs button:hover {
  color: var(--ink);
  border-color: var(--rule-hi);
}
.greek-tabs button.on {
  color: var(--void);
  background: var(--phosphor);
  border-color: transparent;
  font-weight: 800;
}

/* ── plot ── */
.plot-stage {
  margin-top: 12px;
}
.plot-stage svg {
  display: block;
  width: 100%;
  height: auto;
  cursor: crosshair;
  touch-action: none;
}
.grid line {
  stroke: var(--rule-faint);
  stroke-width: 1;
}
.zero-line {
  stroke: var(--rule-hi);
  stroke-width: 1;
  stroke-dasharray: 4 4;
}
.plot-note {
  fill: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.06em;
}
.bs-curve {
  fill: none;
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}
.bs-curve.call {
  stroke: var(--call);
}
.bs-curve.put {
  stroke: var(--put);
  opacity: 0.85;
}
.boundary path {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1;
  stroke-dasharray: 2 4;
  vector-effect: non-scaling-stroke;
}
.boundary .plot-note {
  letter-spacing: 0.05em;
}
.atm-marker line {
  stroke: var(--ink-soft);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}
.atm-marker .mk {
  stroke: var(--void);
  stroke-width: 1.5;
}
.atm-marker .mk.call {
  fill: var(--call);
}
.atm-marker .mk.put {
  fill: var(--put);
}
.ticks text {
  fill: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.04em;
}
.ticks .dim {
  fill: var(--ink-faint);
}
.plot-hint {
  margin: 6px 0 0;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.07em;
  text-transform: uppercase;
}

/* ── footer readouts ── */
.lab-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: var(--hair) solid var(--rule);
}
.readouts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 26px;
  margin: 0;
}
.ro dt {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.ro dd {
  margin: 2px 0 0;
  font-family: var(--font-data);
  font-size: 17px;
  font-weight: 650;
  letter-spacing: -0.01em;
}
.call-ink {
  color: var(--call);
}
.put-ink {
  color: var(--put);
}
.ro.wide dd {
  color: var(--ink-soft);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.lab-footer > strong {
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 600;
  letter-spacing: 0.05em;
  white-space: nowrap;
}

@media (max-width: 720px) {
  .bs-lab {
    padding: 14px;
  }
  .control {
    min-width: 100%;
  }
  .lab-footer {
    flex-direction: column;
    align-items: flex-start;
  }
}

@media (prefers-reduced-motion: reduce) {
  .frame-beam {
    animation: none !important;
    opacity: 0.4;
  }
}
</style>
