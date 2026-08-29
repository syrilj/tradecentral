<script setup lang="ts">
import { computed } from 'vue'
import type { MicrostructureRegimeSnapshot } from '@/microstructureContracts'
import { num, optSigned, DASH } from '@/format'

const props = defineProps<{
  snapshot: MicrostructureRegimeSnapshot | null
}>()

/**
 * An unmeasurable snapshot carries zeros in every Greek, because there was
 * nothing to measure. Rendered through this card those zeros become
 * "NET GEX +0.00M · Net Market Inflow (Dealers absorb supply)" — a confident
 * balanced read of a chain that does not exist. So the card keys off
 * `quality.measurable`, not merely off the snapshot being non-null.
 */
const snap = computed(() => {
  const s = props.snapshot
  return s && s.quality?.measurable !== false ? s : null
})

const isNetGexPositive = computed(() => (snap.value?.net_gex_m ?? 0) >= 0)
const isNetVexPositive = computed(() => (snap.value?.net_vex_m ?? 0) >= 0)
const isNetChexPositive = computed(() => (snap.value?.net_chex_m ?? 0) >= 0)

/** Null-aware: a withheld hedging flow gets neither tone nor a direction
 *  sentence. `?? 0` would have painted "positive" onto an absent number. */
const hedgingFlowSign = computed<1 | -1 | null>(() => {
  const v = snap.value?.hedging_flow_m
  if (v == null || !Number.isFinite(v)) return null
  return v >= 0 ? 1 : -1
})

const spot = computed(() => snap.value?.spot ?? null)

function distToLevel(lvl: number | null): string {
  if (!spot.value || !lvl || lvl <= 0) return DASH
  const diff = ((lvl - spot.value) / spot.value) * 100
  return optSigned(diff, 1) + '%'
}

/** Level with its currency symbol, or a bare dash — never "$—". */
function level(v: number | null | undefined): string {
  return v != null && Number.isFinite(v) ? `$${num(v, 2)}` : DASH
}

// Visual meter calculations
const callGexRatio = computed(() => {
  if (!snap.value) return 50
  const call = Math.max(0, snap.value.call_gex_m)
  const put = Math.max(0, Math.abs(snap.value.put_gex_m))
  const total = call + put
  if (total <= 0) return 50
  return Math.round((call / total) * 100)
})
</script>

<template>
  <div class="greeks-flow-card">
    <div class="card-header">
      <div>
        <span class="eyebrow">DEALER GREEKS &amp; SECOND-ORDER FLOWS</span>
        <h3 class="card-title">Instantaneous Hedging Differential</h3>
      </div>
      <div v-if="snap" class="formula-badge">
        F<sub>hedge</sub> = GEX&middot;&Delta;S + VEX&middot;&Delta;&sigma; + CHEX
      </div>
    </div>

    <!-- 4-Metric Grid with Visual Balance Meters.
         Gated on the whole row, not on each value: dashing the numbers out
         while leaving the tone classes and state pills ("VOL DAMPEN",
         "IV Collapse -> Dealer Buying Flow") still asserts a dealer posture
         that was never measured. The pills come from `x ?? 0 >= 0`, so an
         absent reading paints as positive. -->
    <div v-if="snap" class="metrics-row">
      <!-- 1. Net GEX -->
      <div class="greek-box" :class="{ positive: isNetGexPositive, negative: !isNetGexPositive }">
        <div class="box-top">
          <span class="greek-label">NET GEX (1% MOVE)</span>
          <span class="state-pill" :class="isNetGexPositive ? 'pos' : 'neg'">
            {{ isNetGexPositive ? 'VOL DAMPEN' : 'VOL ACCEL' }}
          </span>
        </div>
        <div class="greek-val font-mono">
          {{ snap ? optSigned(snap.net_gex_m, 2) : DASH }}M
        </div>
        <!-- Visual Call vs Put Ratio Bar -->
        <div class="ratio-bar-wrap">
          <div class="ratio-bar">
            <div class="ratio-fill call" :style="{ width: `${callGexRatio}%` }"></div>
            <div class="ratio-fill put" :style="{ width: `${100 - callGexRatio}%` }"></div>
          </div>
        </div>
        <div class="greek-sub">
          Calls: +${{ snap ? num(snap.call_gex_m, 1) : DASH }}M | Puts: -${{
            snap ? num(Math.abs(snap.put_gex_m), 1) : DASH
          }}M
        </div>
      </div>

      <!-- 2. Net VEX -->
      <div class="greek-box" :class="{ positive: isNetVexPositive, negative: !isNetVexPositive }">
        <div class="box-top">
          <span class="greek-label">NET VANNA (VEX)</span>
          <span class="state-pill" :class="isNetVexPositive ? 'pos' : 'neg'">
            {{ isNetVexPositive ? 'VOL EXPANSION BID' : 'IV SPIKE SQUEEZE' }}
          </span>
        </div>
        <div class="greek-val font-mono">
          {{ snap ? optSigned(snap.net_vex_m, 2) : DASH }}M
        </div>
        <div class="greek-sub">
          {{
            isNetVexPositive
              ? 'IV Collapse -> Dealer Buying Flow'
              : 'IV Spike -> Forced Dealer Liquidation'
          }}
        </div>
      </div>

      <!-- 3. Net CHEX / 0DTE Charm -->
      <div class="greek-box" :class="{ positive: isNetChexPositive, negative: !isNetChexPositive }">
        <div class="box-top">
          <span class="greek-label">NET CHARM (CHEX)</span>
          <span class="state-pill" :class="isNetChexPositive ? 'pos' : 'neg'">
            {{ isNetChexPositive ? 'TIME-DECAY LIFT' : 'TIME-DECAY DRAG' }}
          </span>
        </div>
        <div class="greek-val font-mono">
          {{ snap ? optSigned(snap.net_chex_m, 2) : DASH }}M/d
        </div>
        <div class="greek-sub">
          0DTE Charm Drift: +${{ snap ? num(snap.zero_dte_charm_drift_m, 2) : DASH }}M/day
        </div>
      </div>

      <!-- 4. Total Hedging Flow F_hedge -->
      <div
        class="greek-box total-flow"
        :class="{
          positive: hedgingFlowSign === 1,
          negative: hedgingFlowSign === -1,
        }"
      >
        <div class="box-top">
          <span class="greek-label">TOTAL HEDGING FLOW (F<sub>hedge</sub>)</span>
          <span
            v-if="hedgingFlowSign !== null"
            class="state-pill"
            :class="hedgingFlowSign === 1 ? 'pos' : 'neg'"
          >
            {{ hedgingFlowSign === 1 ? 'SUPPORTIVE' : 'EXTRACTION' }}
          </span>
        </div>
        <div class="greek-val font-mono font-bold">
          <template v-if="hedgingFlowSign !== null"
            >{{ optSigned(snap?.hedging_flow_m, 2) }}M</template
          >
          <template v-else>{{ DASH }}</template>
        </div>
        <!-- F_hedge is a flow RATE: it needs a measured spot and IV velocity,
             not an assumed one. Withheld means withheld — no direction
             sentence, no tone, no pill. -->
        <div class="greek-sub">
          {{
            hedgingFlowSign === null
              ? 'Not measured — needs a live spot and IV velocity, which this feed does not yet carry.'
              : hedgingFlowSign === 1
                ? 'Net Market Inflow (Dealers absorb supply)'
                : 'Net Liquidity Extraction (Selling into drop)'
          }}
        </div>
      </div>
    </div>

    <!-- Structural Boundaries Strip with Distance Percentages -->
    <!-- Levels print through `level()`, which emits a bare dash rather than
         "$—" when one could not be measured. -->
    <div v-if="snap" class="boundaries-strip">
      <div class="bound-item">
        <span class="b-label">PUT WALL (SUPPORT)</span>
        <div class="b-val-row">
          <span class="b-val font-mono text-put-hi">{{ level(snap.put_wall) }}</span>
          <span class="b-dist font-mono">({{ distToLevel(snap.put_wall) }})</span>
        </div>
      </div>
      <div class="bound-item">
        <span class="b-label">GAMMA FLIP (S*)</span>
        <div class="b-val-row">
          <span class="b-val font-mono text-warn">{{ level(snap.gamma_flip) }}</span>
          <span class="b-dist font-mono">
            ({{ snap.gamma_flip != null ? distToLevel(snap.gamma_flip) : 'none in range' }})
          </span>
        </div>
      </div>
      <div class="bound-item">
        <span class="b-label">CALL WALL (RESISTANCE)</span>
        <div class="b-val-row">
          <span class="b-val font-mono text-call-hi">{{ level(snap.call_wall) }}</span>
          <span class="b-dist font-mono">({{ distToLevel(snap.call_wall) }})</span>
        </div>
      </div>
      <div class="bound-item">
        <span class="b-label">ABSOLUTE GAMMA PEAK</span>
        <div class="b-val-row">
          <span class="b-val font-mono text-phosphor">{{ level(snap.absolute_gamma_peak) }}</span>
          <span class="b-dist font-mono">({{ distToLevel(snap.absolute_gamma_peak) }})</span>
        </div>
      </div>
    </div>

    <!-- Withheld, and why. Zeros in every Greek box would read as a balanced
         market rather than an absent one. -->
    <p v-else-if="snapshot" class="withheld-note">
      Dealer Greeks withheld — {{ snapshot.quality?.reason ?? 'no measurable option chain' }}.
    </p>
  </div>
</template>

<style scoped>
.withheld-note {
  padding: var(--s3);
  border-top: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.5;
}

.greeks-flow-card {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--radius-sm, 4px);
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.eyebrow {
  font-size: 0.6875rem;
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

.formula-badge {
  font-size: 0.6875rem;
  font-family: var(--font-mono, monospace);
  color: var(--ink-dim);
  background: var(--panel-hi);
  padding: 0.25rem 0.5rem;
  border-radius: var(--radius-sm, 4px);
  border: 1px solid var(--rule-faint);
}

.metrics-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0.75rem;
}

.greek-box {
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  border-radius: var(--radius-sm, 4px);
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.box-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.state-pill {
  font-size: 0.5625rem;
  font-weight: 700;
  font-family: var(--font-mono, monospace);
  padding: 0.1rem 0.35rem;
  border-radius: 2px;
}

.state-pill.pos {
  background: var(--call-wash);
  color: var(--call-hi);
  border: 1px solid var(--call-dim);
}

.state-pill.neg {
  background: var(--put-wash);
  color: var(--put-hi);
  border: 1px solid var(--put-dim);
}

.greek-box.positive {
  border-left: 3px solid var(--long);
}

.greek-box.negative {
  border-left: 3px solid var(--short);
}

.greek-box.total-flow {
  background: var(--panel-raise);
}

.greek-label {
  font-size: 0.625rem;
  color: var(--ink-faint);
  font-family: var(--font-mono, monospace);
}

.greek-val {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--ink);
}

.greek-box.positive .greek-val {
  color: var(--call-hi);
}

.greek-box.negative .greek-val {
  color: var(--put-hi);
}

.ratio-bar-wrap {
  width: 100%;
  margin: 0.125rem 0;
}

.ratio-bar {
  display: flex;
  height: 4px;
  width: 100%;
  border-radius: 2px;
  overflow: hidden;
  background: var(--void);
}

.ratio-fill.call {
  background: var(--call);
}

.ratio-fill.put {
  background: var(--put);
}

.greek-sub {
  font-size: 0.6875rem;
  color: var(--ink-dim);
  line-height: 1.3;
}

.boundaries-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.75rem;
  padding: 0.75rem;
  background: var(--void-lift);
  border: 1px solid var(--rule-faint);
  border-radius: var(--radius-sm, 4px);
}

.bound-item {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.b-label {
  font-size: 0.625rem;
  color: var(--ink-faint);
  font-family: var(--font-mono, monospace);
}

.b-val-row {
  display: flex;
  align-items: baseline;
  gap: 0.375rem;
}

.b-val {
  font-size: 0.9375rem;
  font-weight: 700;
}

.b-dist {
  font-size: 0.6875rem;
  color: var(--ink-faint);
}

.text-call-hi {
  color: var(--call-hi);
}

.text-put-hi {
  color: var(--put-hi);
}

.text-warn {
  color: var(--warn);
}

.text-phosphor {
  color: var(--phosphor);
}
</style>
