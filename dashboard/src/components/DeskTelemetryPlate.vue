<script setup lang="ts">
import { computed } from 'vue'
import { structuralGexProfile } from '@/charts/landing-viz'

/**
 * Hero "workstation" tab: a structural desk telemetry plate.
 *
 * Replaces a static marketing raster with the thing it claimed to show: a
 * GEX-by-strike profile with the flip boundary, wall levels, and the regime
 * ribbon, all computed in-browser from a named parametric model
 * (structuralGexProfile). Figures are structural anatomy — S₀=100, σ=30% —
 * never a quote; live chains appear after operator sign-in.
 */
const S = 100
const SIGMA = 0.3
const FLIP = 88
const CALL_WALL = 110
const PUT_WALL = 92
const N_STRIKES = 25
const RANGE = 0.24

const profile = computed(() =>
  structuralGexProfile({
    S,
    flipK: FLIP,
    callWallK: CALL_WALL,
    putWallK: PUT_WALL,
    nStrikes: N_STRIKES,
    range: RANGE,
  }),
)

const netPositive = computed(() => profile.value.net > 0)
const flipDistPct = computed(() => ((FLIP - S) / S) * 100)
const callWallDistPct = computed(() => ((CALL_WALL - S) / S) * 100)
const putWallDistPct = computed(() => ((PUT_WALL - S) / S) * 100)
/** 1-day implied move: σ·S/√252. */
const dailyMove = computed(() => (SIGMA * S) / Math.sqrt(252))

/* ── Chart geometry ───────────────────────────────────────────────────────── */
const VB_W = 560
const VB_H = 210
const PAD = { l: 14, r: 14, t: 26, b: 22 }
const plotW = VB_W - PAD.l - PAD.r
const plotH = VB_H - PAD.t - PAD.b
const zeroY = PAD.t + plotH / 2

const kLow = S * (1 - RANGE)
const kHigh = S * (1 + RANGE)
const xOf = (K: number): number => PAD.l + ((K - kLow) / (kHigh - kLow)) * plotW

const bars = computed(() => {
  const bw = plotW / N_STRIKES - 3
  return profile.value.points.map((p) => {
    const h = (Math.abs(p.gex) * plotH) / 2
    const x = xOf(p.K) - bw / 2
    return {
      d:
        p.gex >= 0
          ? `M${x.toFixed(1)},${zeroY.toFixed(1)}v${-h.toFixed(1)}h${bw.toFixed(1)}v${h.toFixed(1)}z`
          : `M${x.toFixed(1)},${zeroY.toFixed(1)}v${h.toFixed(1)}h${bw.toFixed(1)}v${-h.toFixed(1)}z`,
      up: p.gex >= 0,
    }
  })
})

const flipX = computed(() => xOf(FLIP))
const spotX = computed(() => xOf(S))
const callWallX = computed(() => xOf(CALL_WALL))
const putWallX = computed(() => xOf(PUT_WALL))

const netLabel = computed(() => (netPositive.value ? 'LONG Γ · DAMPENED' : 'SHORT Γ · AMPLIFYING'))
</script>

<template>
  <div
    class="desk-plate"
    role="img"
    aria-label="Structural dealer gamma telemetry: KPI strip with spot, net gamma, walls and flip; a gamma-by-strike histogram with the flip boundary marked; and the regime ribbon. All figures are model anatomy, not live quotes."
  >
    <div class="kpis">
      <div class="kpi">
        <span class="k-label">Spot</span>
        <strong class="k-val">$100.00</strong>
        <span class="k-sub">MODEL S₀</span>
      </div>
      <div class="kpi">
        <span class="k-label">Net GEX</span>
        <strong class="k-val" :class="netPositive ? 'pos' : 'neg'">{{
          netPositive ? 'LONG Γ' : 'SHORT Γ'
        }}</strong>
        <span class="k-sub" :class="netPositive ? 'pos' : 'neg'">{{
          netPositive ? 'NET POSITIVE' : 'NET NEGATIVE'
        }}</span>
      </div>
      <div class="kpi">
        <span class="k-label">Call wall</span>
        <strong class="k-val pos">${{ CALL_WALL }}</strong>
        <span class="k-sub pos">+{{ callWallDistPct.toFixed(1) }}%</span>
      </div>
      <div class="kpi">
        <span class="k-label">Put wall</span>
        <strong class="k-val neg">${{ PUT_WALL }}</strong>
        <span class="k-sub neg">{{ putWallDistPct.toFixed(1) }}%</span>
      </div>
      <div class="kpi">
        <span class="k-label">0-Γ flip</span>
        <strong class="k-val flip">${{ FLIP }}</strong>
        <span class="k-sub flip">{{ flipDistPct.toFixed(1) }}%</span>
      </div>
      <div class="kpi">
        <span class="k-label">1D move</span>
        <strong class="k-val">±${{ dailyMove.toFixed(2) }}</strong>
        <span class="k-sub">σ·√¹⁄₂₅₂</span>
      </div>
    </div>

    <div class="gex-zone">
      <div class="zone-head">
        <span class="z-title">GAMMA BY STRIKE</span>
        <span class="z-meta">STRUCTURAL · 25 STRIKES ±{{ (RANGE * 100).toFixed(0) }}%</span>
      </div>
      <svg :viewBox="`0 0 ${VB_W} ${VB_H}`" aria-hidden="true">
        <!-- amplification zone left of the flip -->
        <rect :x="PAD.l" :y="PAD.t" :width="flipX - PAD.l" :height="plotH" class="zone amplify" />
        <text :x="PAD.l + 8" :y="PAD.t + 13" class="zone-label">AMPLIFY · SHORT Γ</text>
        <text :x="VB_W - PAD.r - 8" :y="PAD.t + 13" class="zone-label damp" text-anchor="end">
          DAMP · LONG Γ
        </text>

        <!-- bars -->
        <path
          v-for="(bar, i) in bars"
          :key="i"
          :d="bar.d"
          :class="bar.up ? 'bar call' : 'bar put'"
        />

        <!-- zero line -->
        <line :x1="PAD.l" :y1="zeroY" :x2="VB_W - PAD.r" :y2="zeroY" class="zero" />

        <!-- level markers: flip · put wall · spot · call wall -->
        <line :x1="flipX" :y1="PAD.t" :x2="flipX" :y2="PAD.t + plotH" class="mk mk-flip" />
        <line :x1="putWallX" :y1="PAD.t" :x2="putWallX" :y2="PAD.t + plotH" class="mk mk-put" />
        <line :x1="spotX" :y1="PAD.t" :x2="spotX" :y2="PAD.t + plotH" class="mk mk-spot" />
        <line :x1="callWallX" :y1="PAD.t" :x2="callWallX" :y2="PAD.t + plotH" class="mk mk-call" />

        <text :x="flipX" :y="PAD.t + plotH + 15" class="mk-label flip" text-anchor="middle">
          FLIP ${{ FLIP }}
        </text>
        <text :x="spotX" :y="PAD.t + plotH + 15" class="mk-label spot" text-anchor="middle">
          SPOT
        </text>
        <text :x="putWallX" :y="PAD.t - 6" class="mk-label put" text-anchor="middle">
          PUT W ${{ PUT_WALL }}
        </text>
        <text :x="callWallX" :y="PAD.t - 6" class="mk-label call" text-anchor="middle">
          CALL W ${{ CALL_WALL }}
        </text>

        <text :x="PAD.l" :y="VB_H - 4" class="axis-label">${{ kLow.toFixed(0) }}</text>
        <text :x="VB_W - PAD.r" :y="VB_H - 4" class="axis-label end" text-anchor="end">
          ${{ kHigh.toFixed(0) }}
        </text>
      </svg>
    </div>

    <div class="regime-ribbon">
      <span class="rr-dot" aria-hidden="true" />
      <strong>{{ netLabel }}</strong>
      <span class="rr-note"
        >Spot above flip — hedging leans against the move, moves mean-revert.</span
      >
      <code class="rr-math">Γ(K) = Σ OI·φ(d₁)/(Sσ√T)</code>
    </div>
  </div>
</template>

<style scoped>
/* The desk plate keeps the desk's own dark scheme inside the page's paper
   chrome — the same token family as the navy evidence band (band-dark), so
   the two dark surfaces on the page read as one system. */
.desk-plate {
  --dp-bg: var(--panel);
  --dp-panel: var(--panel-hi);
  --dp-rule: rgba(250, 250, 244, 0.12);
  --dp-ink: var(--ink);
  --dp-dim: var(--ink-soft);
  --dp-faint: var(--ink-faint);
  --dp-call: var(--long);
  --dp-put: var(--no-go);
  --dp-flip: var(--warn);
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--dp-bg);
  color: var(--dp-ink);
  font-family: var(--font-data);
}

.kpis {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  border-bottom: var(--hair) solid var(--dp-rule);
}
.kpi {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-left: var(--hair) solid var(--dp-rule);
  min-width: 0;
}
.kpi:first-child {
  border-left: 0;
}
.k-label {
  font-size: var(--t-nano);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--dp-faint);
}
.k-val {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.02em;
  white-space: nowrap;
}
.k-sub {
  font-size: var(--t-nano);
  letter-spacing: 0.06em;
  color: var(--dp-faint);
}
.pos {
  color: var(--dp-call);
}
.neg {
  color: var(--dp-put);
}
.flip {
  color: var(--dp-flip);
}

.gex-zone {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 10px 12px 4px;
  min-height: 0;
}
.zone-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 4px;
}
.z-title {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--dp-dim);
}
.z-meta {
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  color: var(--dp-faint);
}
svg {
  display: block;
  width: 100%;
  height: 100%;
  flex: 1;
}
.zone.amplify {
  fill: rgba(255, 122, 112, 0.05);
}
.zone-label {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.1em;
  fill: var(--dp-put);
  opacity: 0.85;
}
.zone-label.damp {
  fill: var(--dp-call);
}
.bar.call {
  fill: var(--dp-call);
  opacity: 0.85;
}
.bar.put {
  fill: var(--dp-put);
  opacity: 0.85;
}
.zero {
  stroke: var(--dp-rule);
  stroke-width: 1;
}
.mk {
  stroke-width: 1;
}
.mk-flip {
  stroke: var(--dp-flip);
  stroke-dasharray: 3 3;
}
.mk-spot {
  stroke: var(--dp-ink);
}
.mk-call {
  stroke: var(--dp-call);
  stroke-dasharray: 2 2;
  opacity: 0.7;
}
.mk-put {
  stroke: var(--dp-put);
  stroke-dasharray: 2 2;
  opacity: 0.7;
}
.mk-label {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.06em;
}
.mk-label.flip {
  fill: var(--dp-flip);
}
.mk-label.spot {
  fill: var(--dp-ink);
}
.mk-label.call {
  fill: var(--dp-call);
}
.mk-label.put {
  fill: var(--dp-put);
}
.axis-label {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  fill: var(--dp-faint);
}

.regime-ribbon {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-top: var(--hair) solid var(--dp-rule);
  background: var(--dp-panel);
  font-size: 10px;
  letter-spacing: 0.08em;
}
.rr-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--dp-call);
  flex: none;
}
.regime-ribbon strong {
  color: var(--dp-call);
  font-weight: 700;
  white-space: nowrap;
}
.rr-note {
  color: var(--dp-faint);
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rr-math {
  margin-left: auto;
  font-size: var(--t-nano);
  color: var(--dp-faint);
  white-space: nowrap;
}

@media (max-width: 700px) {
  .kpis {
    grid-template-columns: repeat(3, 1fr);
  }
  .kpi:nth-child(4) {
    border-left: 0;
  }
  .kpi:nth-child(n + 4) {
    border-top: var(--hair) solid var(--dp-rule);
  }
  .rr-note {
    display: none;
  }
}
</style>
