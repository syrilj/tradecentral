<script setup lang="ts">
import { computed } from 'vue'
import { bsCall, bsPutPrice, greekCurves } from '@/charts/landing-viz'

/**
 * Bento-card preview of the model lab.
 *
 * The curves and the two readouts come from the same closed-form engine that
 * powers the interactive workbench further down the page — this card computes
 * them on mount rather than shipping a picture of them, so the claim it makes
 * ("a real Black-Scholes workbench") is the claim it demonstrates.
 *
 * Structural parameters only: S is a unitless model spot, never a quote.
 */
const S = 100
const R = 0.05
const Q = 0
const SIGMA = 0.3
const T = 30 / 365
const K_LOW = 60
const K_HIGH = 140
const N = 81

const VB_W = 260
const VB_H = 92
const PAD = { l: 8, r: 8, t: 10, b: 20 }
const plotW = VB_W - PAD.l - PAD.r
const plotH = VB_H - PAD.t - PAD.b
const midY = PAD.t + plotH / 2

const curves = computed(() => greekCurves('delta', S, T, SIGMA, R, Q, K_LOW, K_HIGH, N))

function toPath(pts: { x: number; y: number }[]): string {
  return pts
    .map(
      (p, i) =>
        `${i === 0 ? 'M' : 'L'}${(PAD.l + (p.x / 100) * plotW).toFixed(1)},${(
          midY -
          p.y * (plotH / 2)
        ).toFixed(1)}`,
    )
    .join('')
}

const callPath = computed(() => toPath(curves.value.call))
const putPath = computed(() => toPath(curves.value.put))
const atmX = computed(() => PAD.l + ((S - K_LOW) / (K_HIGH - K_LOW)) * plotW)

const callValue = computed(() => bsCall({ S, K: S, T, sigma: SIGMA, r: R, q: Q }).toFixed(2))
const putValue = computed(() => bsPutPrice({ S, K: S, T, sigma: SIGMA, r: R, q: Q }).toFixed(2))
</script>

<template>
  <figure
    class="lab-plate"
    aria-label="Call and put delta computed across the strike range by the same Black-Scholes engine as the interactive workbench, with the at-the-money values shown beneath."
  >
    <figcaption>
      <span>Δ ACROSS K</span>
      <i aria-hidden="true" />
      <span class="params">σ 30% · 30D</span>
    </figcaption>

    <svg :viewBox="`0 0 ${VB_W} ${VB_H}`" aria-hidden="true">
      <path class="axis" :d="`M${PAD.l} ${midY}H${VB_W - PAD.r}`" />
      <path class="atm" :d="`M${atmX} ${PAD.t}V${PAD.t + plotH}`" />
      <path class="curve put" :d="putPath" />
      <path class="curve call" :d="callPath" />
      <circle class="knot" :cx="atmX" :cy="midY" r="2.6" />
      <text class="tick" :x="PAD.l" :y="VB_H - 6">K 60</text>
      <text class="tick atm-tick" :x="atmX - 8" :y="VB_H - 6">ATM</text>
      <text class="tick end" :x="VB_W - PAD.r" :y="VB_H - 6">140</text>
    </svg>

    <div class="readouts">
      <span class="ro"
        ><i class="sw call" />CALL <strong>${{ callValue }}</strong></span
      >
      <span class="ro"
        ><i class="sw put" />PUT <strong>${{ putValue }}</strong></span
      >
      <span class="ro live">computed in-browser</span>
    </div>
  </figure>
</template>

<style scoped>
.lab-plate {
  margin: 0;
  padding: 9px 10px 8px;
  border: var(--hair) solid var(--rule);
  border-top: 2px solid var(--tc-yellow);
  background:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px), var(--panel);
  background-size: 22px 22px;
}
figcaption {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 7px;
  border-bottom: var(--hair) solid var(--rule);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.09em;
  color: var(--ink-faint);
}
figcaption i {
  flex: 1;
  height: 1px;
  background: var(--rule);
}
.params {
  color: var(--ink-faint);
}
svg {
  display: block;
  width: 100%;
  height: auto;
  margin-top: 4px;
  overflow: visible;
}
.axis {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1;
}
.atm {
  fill: none;
  stroke: var(--ink-ghost);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}
.curve {
  fill: none;
  stroke-width: 1.8;
  vector-effect: non-scaling-stroke;
}
.curve.call {
  stroke: var(--call);
}
.curve.put {
  stroke: var(--put);
}
.knot {
  fill: var(--void);
  stroke: var(--ink);
  stroke-width: 1.4;
}
.tick {
  fill: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.06em;
}
.tick.end {
  text-anchor: end;
}
.tick.atm-tick {
  fill: var(--ink-faint);
}
.readouts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  padding-top: 7px;
  border-top: var(--hair) solid var(--rule);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.06em;
  color: var(--ink-faint);
}
.ro {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.ro strong {
  color: var(--ink);
  font-weight: 700;
}
.ro.live {
  margin-left: auto;
  color: var(--ink-faint);
  text-transform: uppercase;
}
.sw {
  width: 8px;
  height: 8px;
}
.sw.call {
  background: var(--call);
}
.sw.put {
  background: var(--put);
}
</style>
