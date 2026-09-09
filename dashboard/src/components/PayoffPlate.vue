<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  payoffColumns,
  structureGreeks,
  type OptionLeg,
} from '@/charts/landing-viz'

/**
 * Lab workbench plate: a real multi-leg payoff figure.
 *
 * Replaces a static "options workbench" raster with a live structure
 * evaluator: preset legs are priced by the same Black-Scholes closed forms
 * the desk uses (landing-viz), so today's value curve, expiry P&L, and the
 * Greeks strip all move together when the visitor drags spot or switches the
 * structure. Structural parameters only — S₀=100, σ=30%, T=45D.
 */
interface StructurePreset {
  key: string
  name: string
  legs: OptionLeg[]
}

const PRESETS: StructurePreset[] = [
  { key: 'call', name: 'Long call 100', legs: [{ kind: 'call', strike: 100, dir: 1 }] },
  {
    key: 'spread',
    name: 'Bull call 100/115',
    legs: [
      { kind: 'call', strike: 100, dir: 1 },
      { kind: 'call', strike: 115, dir: -1 },
    ],
  },
  {
    key: 'fly',
    name: 'Iron fly 90/100/110',
    legs: [
      { kind: 'put', strike: 90, dir: 1 },
      { kind: 'put', strike: 100, dir: -1 },
      { kind: 'call', strike: 100, dir: -1 },
      { kind: 'call', strike: 110, dir: 1 },
    ],
  },
]

const S_REF = 100
const SIGMA = 0.3
const T = 45 / 365
const R = 0.05
const Q = 0
const S_LOW = 70
const S_HIGH = 130
const N = 81

const activeKey = ref<StructurePreset['key']>('spread')
const spot = ref(S_REF)

const preset = computed(() => PRESETS.find((p) => p.key === activeKey.value)!)

const env = computed(() => ({ S: spot.value, T, sigma: SIGMA, r: R, q: Q }))
const greeks = computed(() => structureGreeks(preset.value.legs, env.value))
const cols = computed(() => payoffColumns(preset.value.legs, env.value, S_LOW, S_HIGH, N))

/* ── Chart geometry ───────────────────────────────────────────────────────── */
const VB_W = 560
const VB_H = 240
const PAD = { l: 46, r: 16, t: 24, b: 26 }
const plotW = VB_W - PAD.l - PAD.r
const plotH = VB_H - PAD.t - PAD.b

const xOf = (S: number): number => PAD.l + ((S - S_LOW) / (S_HIGH - S_LOW)) * plotW

const yDomain = computed(() => {
  const all = [...cols.value.today, ...cols.value.expiry, 0]
  const lo = Math.min(...all)
  const hi = Math.max(...all)
  const pad = (hi - lo) * 0.12 || 1
  return { lo: lo - pad, hi: hi + pad }
})
const yOf = computed(
  () => (v: number): number =>
    PAD.t + ((yDomain.value.hi - v) / (yDomain.value.hi - yDomain.value.lo)) * plotH,
)

function toPath(values: number[]): string {
  return values
    .map(
      (v, i) =>
        `${i === 0 ? 'M' : 'L'}${xOf(cols.value.spots[i]!).toFixed(1)},${yOf.value(v).toFixed(1)}`,
    )
    .join('')
}
const todayPath = computed(() => toPath(cols.value.today))
const expiryPath = computed(() => toPath(cols.value.expiry))
const zeroY = computed(() => yOf.value(0))
const spotX = computed(() => xOf(spot.value))
const spotPnl = computed(
  () =>
    cols.value.expiry[Math.round(((spot.value - S_LOW) / (S_HIGH - S_LOW)) * (N - 1))] ?? 0,
)

/* Max profit/loss at expiry across the ladder, for the boundary chips. */
const expiryBounds = computed(() => {
  let lo = Infinity,
    hi = -Infinity
  for (const v of cols.value.expiry) {
    if (v < lo) lo = v
    if (v > hi) hi = v
  }
  return { lo, hi }
})

const premium = computed(() => cols.value.premium)
const debit = computed(() => premium.value >= 0)

/* Leg labels, stacked so two legs sharing a strike (fly wings) don't overlap
   into an unreadable superimposition. */
const strikeLabels = computed(() => {
  const byStrike = new Map<number, string[]>()
  for (const leg of preset.value.legs) {
    const glyph = `${leg.dir > 0 ? '+' : '−'}${leg.kind === 'call' ? 'C' : 'P'}`
    const bucket = byStrike.get(leg.strike) ?? []
    bucket.push(glyph)
    byStrike.set(leg.strike, bucket)
  }
  return [...byStrike.entries()].flatMap(([strike, glyphs], idx) =>
    glyphs.map((g, row) => ({
      strike,
      row,
      text: `${g} ${strike}`,
      key: `${idx}-${row}`,
    })),
  )
})

const fmt$ = (v: number, digits = 2): string =>
  `${v < 0 ? '−' : ''}$${Math.abs(v).toFixed(digits)}`
const fmtSigned = (v: number, digits = 3): string =>
  `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(digits)}`
</script>

<template>
  <div
    class="payoff-plate"
    role="group"
    aria-label="Interactive Black-Scholes payoff workbench. Switch between a long call, a bull call spread, and an iron butterfly; drag the spot slider to move the Greeks."
  >
    <div class="pp-toolbar">
      <div class="structure-tabs" role="tablist" aria-label="Structure preset">
        <button
          v-for="p in PRESETS"
          :key="p.key"
          type="button"
          role="tab"
          :aria-selected="activeKey === p.key"
          class="s-tab"
          :class="{ active: activeKey === p.key }"
          @click="activeKey = p.key"
        >
          {{ p.name }}
        </button>
      </div>
      <span class="pp-params">T {{ Math.round(T * 365) }}D · σ {{ (SIGMA * 100).toFixed(0) }}%</span>
    </div>

    <div class="chart-zone">
      <svg :viewBox="`0 0 ${VB_W} ${VB_H}`" aria-hidden="true">
        <!-- zero line -->
        <line :x1="PAD.l" :y1="zeroY" :x2="VB_W - PAD.r" :y2="zeroY" class="zero" />
        <text :x="PAD.l - 6" :y="zeroY + 3" text-anchor="end" class="y-label">$0</text>

        <!-- expiry-domain labels -->
        <text :x="PAD.l - 6" :y="yOf(expiryBounds.hi) + 3" text-anchor="end" class="y-label">
          {{ fmt$(expiryBounds.hi, 0) }}
        </text>
        <text :x="PAD.l - 6" :y="yOf(expiryBounds.lo) + 3" text-anchor="end" class="y-label">
          {{ fmt$(expiryBounds.lo, 0) }}
        </text>

        <!-- legs' strike markers -->
        <line
          v-for="leg in preset.legs"
          :key="`${leg.kind}-${leg.strike}`"
          :x1="xOf(leg.strike)"
          :y1="PAD.t"
          :x2="xOf(leg.strike)"
          :y2="PAD.t + plotH"
          :class="leg.dir > 0 ? 'strike long' : 'strike short'"
        />
        <text
          v-for="sl in strikeLabels"
          :key="`t-${sl.strike}-${sl.text}`"
          :x="xOf(sl.strike)"
          :y="PAD.t - sl.row * 9 - 4"
          text-anchor="middle"
          class="strike-label"
        >
          {{ sl.text }}
        </text>

        <!-- expiry P&L (kinked, dashed) + today's value (solid) -->
        <path :d="expiryPath" class="curve expiry" />
        <path :d="todayPath" class="curve today" />

        <!-- current spot marker -->
        <line :x1="spotX" :y1="PAD.t" :x2="spotX" :y2="PAD.t + plotH" class="spot-rule" />
        <circle :cx="spotX" :cy="yOf(spotPnl)" r="3.4" class="spot-dot" />

        <text :x="xOf(S_LOW)" :y="VB_H - 8" class="x-label">${{ S_LOW }}</text>
        <text :x="xOf(S_HIGH)" :y="VB_H - 8" text-anchor="end" class="x-label">${{ S_HIGH }}</text>
        <text :x="spotX" :y="VB_H - 8" text-anchor="middle" class="x-label spot">
          S {{ spot.toFixed(0) }}
        </text>
      </svg>
    </div>

    <div class="greeks-strip" aria-label="Structure Greeks at current spot">
      <div class="g-cell">
        <span class="g-label">Net premium</span>
        <strong class="g-val" :class="debit ? 'put-t' : 'call-t'"
          >{{ fmt$(premium) }} {{ debit ? 'DEBIT' : 'CREDIT' }}</strong
        >
      </div>
      <div class="g-cell">
        <span class="g-label">Δ delta</span>
        <strong class="g-val">{{ fmtSigned(greeks.delta) }}</strong>
      </div>
      <div class="g-cell">
        <span class="g-label">Γ gamma</span>
        <strong class="g-val">{{ fmtSigned(greeks.gamma, 4) }}</strong>
      </div>
      <div class="g-cell">
        <span class="g-label">ν vega /pt</span>
        <strong class="g-val">{{ fmtSigned(greeks.vega) }}</strong>
      </div>
      <div class="g-cell">
        <span class="g-label">Θ theta /day</span>
        <strong class="g-val">{{ fmtSigned(greeks.thetaDay) }}</strong>
      </div>
      <div class="g-cell bounds">
        <span class="g-label">Expiry bounds</span>
        <strong class="g-val"
          >{{ fmt$(expiryBounds.lo, 0) }} … {{ fmt$(expiryBounds.hi, 0) }}</strong
        >
      </div>
    </div>

    <div class="spot-slider">
      <span class="sl-label">Spot S₀</span>
      <input v-model.number="spot" type="range" :min="S_LOW" :max="S_HIGH" step="0.5" />
      <code class="sl-val">${{ spot.toFixed(2) }}</code>
    </div>
  </div>
</template>

<style scoped>
/* Cream instrument on the lab paper — inherits the landing page token remap. */
.payoff-plate {
  display: flex;
  flex-direction: column;
  background: var(--tc-cream);
  color: var(--ink);
  font-family: var(--font-data);
}

.pp-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: var(--hair) solid var(--rule);
}
.structure-tabs {
  display: inline-flex;
  gap: 4px;
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  border-radius: 6px;
  padding: 2px;
}
.s-tab {
  padding: 5px 11px;
  border: none;
  border-radius: 4px;
  background: transparent;
  font-family: var(--font-data);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--ink-faint);
  cursor: pointer;
  transition: all var(--dur) var(--ease-out);
  white-space: nowrap;
}
.s-tab:hover {
  color: var(--ink);
}
.s-tab.active {
  color: var(--ink);
  background: var(--tc-cream);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
.pp-params {
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
  white-space: nowrap;
}

.chart-zone {
  padding: 12px 14px 4px;
  border-bottom: var(--hair) solid var(--rule);
}
svg {
  display: block;
  width: 100%;
  height: auto;
}
.zero {
  stroke: var(--ink-ghost);
  stroke-width: 1;
  stroke-dasharray: 4 3;
}
.y-label,
.x-label {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  fill: var(--ink-faint);
  letter-spacing: 0.04em;
}
.x-label.spot {
  fill: var(--ink);
  font-weight: 700;
}
.strike {
  stroke-width: 1;
  stroke-dasharray: 2 3;
}
.strike.long {
  stroke: var(--call);
}
.strike.short {
  stroke: var(--put);
}
.strike-label {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.04em;
  fill: var(--ink-faint);
}
.curve {
  fill: none;
}
.curve.expiry {
  stroke: var(--ink);
  stroke-width: 1.4;
  stroke-dasharray: 5 3;
}
.curve.today {
  stroke: var(--phosphor);
  stroke-width: 2;
}
.spot-rule {
  stroke: var(--ink);
  stroke-width: 1;
}
.spot-dot {
  fill: var(--phosphor);
  stroke: var(--tc-cream);
  stroke-width: 1.4;
}

.greeks-strip {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  border-bottom: var(--hair) solid var(--rule);
}
.g-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 14px;
  border-left: var(--hair) solid var(--rule);
  min-width: 0;
}
.g-cell:first-child {
  border-left: 0;
}
.g-label {
  font-size: var(--t-nano);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-faint);
}
.g-val {
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}
.g-val.put-t {
  color: var(--put);
}
.g-val.call-t {
  color: var(--call);
}
.g-cell.bounds .g-val {
  font-size: 11px;
}

.spot-slider {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
}
.sl-label {
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-faint);
  white-space: nowrap;
}
input[type='range'] {
  flex: 1;
  accent-color: var(--phosphor);
  cursor: pointer;
}
.sl-val {
  font-size: 11px;
  font-weight: 700;
  color: var(--ink);
}

@media (max-width: 700px) {
  .greeks-strip {
    grid-template-columns: repeat(3, 1fr);
  }
  .g-cell:nth-child(4) {
    border-left: 0;
  }
  .g-cell:nth-child(n + 4) {
    border-top: var(--hair) solid var(--rule);
  }
  .structure-tabs {
    overflow-x: auto;
  }
}
</style>
