<script setup lang="ts">
import { computed } from 'vue'
import type { MicrostructureRegimeSnapshot } from '@/microstructureContracts'
import { num, optSigned, DASH } from '@/format'

const props = withDefaults(
  defineProps<{
    snapshot: MicrostructureRegimeSnapshot | null
    spot?: number | null
    netGammaM?: number | null
  }>(),
  {
    spot: null,
    netGammaM: null,
  },
)

const snap = computed(() => {
  const s = props.snapshot
  return s && s.quality?.measurable !== false ? s : null
})

const netPressureM = computed<number | null>(() => {
  if (snap.value?.hedging_flow_m != null) return snap.value.hedging_flow_m
  if (props.netGammaM != null) return props.netGammaM * -0.45
  return null
})

const callHedgingM = computed<number | null>(() => {
  if (snap.value?.call_gex_m != null) return snap.value.call_gex_m * 0.25
  return null
})

const putHedgingM = computed<number | null>(() => {
  if (snap.value?.put_gex_m != null) return Math.abs(snap.value.put_gex_m) * 0.28
  return null
})

const hedgingImpactPrice = computed<number | null>(() => {
  if (netPressureM.value == null || props.spot == null) return null
  const flow = netPressureM.value
  return (flow / 1000) * (props.spot * 0.001)
})

const hedgingImpactIv = computed<number | null>(() => {
  if (snap.value?.net_vex_m == null) return null
  const vex = snap.value.net_vex_m
  return (vex / 100) * 0.1
})
</script>

<template>
  <div class="instant-hedging-card">
    <div class="card-header">
      <span class="card-eyebrow font-mono">INSTANTANEOUS HEDGING</span>
    </div>

    <div class="metrics-stack">
      <!-- Net Hedging Pressure -->
      <div class="metric-row">
        <div class="m-left">
          <span class="m-label font-mono">Net Hedging Pressure</span>
        </div>
        <span
          class="m-val font-mono font-bold"
          :class="netPressureM == null ? 'text-ink-dim' : netPressureM >= 0 ? 'text-call-hi' : 'text-put-hi'"
        >
          {{ netPressureM != null ? `${optSigned(netPressureM, 1)}M` : DASH }}
        </span>
      </div>

      <!-- Call Hedging -->
      <div class="metric-row">
        <div class="m-left">
          <span class="m-label font-mono">Call Hedging</span>
        </div>
        <span
          class="m-val font-mono font-bold"
          :class="callHedgingM != null ? 'text-call-hi' : 'text-ink-dim'"
        >
          {{ callHedgingM != null ? `+${num(callHedgingM, 1)}M` : DASH }}
        </span>
      </div>

      <!-- Put Hedging -->
      <div class="metric-row">
        <div class="m-left">
          <span class="m-label font-mono">Put Hedging</span>
        </div>
        <span
          class="m-val font-mono font-bold"
          :class="putHedgingM != null ? 'text-put-hi' : 'text-ink-dim'"
        >
          {{ putHedgingM != null ? `+${num(putHedgingM, 1)}M` : DASH }}
        </span>
      </div>

      <!-- Hedging Impact (Price) -->
      <div class="metric-row">
        <span class="m-label font-mono">Hedging Impact (Price)</span>
        <span
          class="m-val font-mono font-bold"
          :class="hedgingImpactPrice == null ? 'text-ink-dim' : hedgingImpactPrice >= 0 ? 'text-call-hi' : 'text-put-hi'"
        >
          {{ hedgingImpactPrice != null ? `${optSigned(hedgingImpactPrice, 2)}` : DASH }}
        </span>
      </div>

      <!-- Hedging Impact (IV) -->
      <div class="metric-row">
        <span class="m-label font-mono">Hedging Impact (IV)</span>
        <span
          class="m-val font-mono font-bold"
          :class="hedgingImpactIv == null ? 'text-ink-dim' : hedgingImpactIv >= 0 ? 'text-call-hi' : 'text-put-hi'"
        >
          {{ hedgingImpactIv != null ? `${optSigned(hedgingImpactIv, 2)}%` : DASH }}
        </span>
      </div>
    </div>

    <div class="card-footer">
      <span class="sub-caption font-mono text-ink-dim">
        Differential dealers' dynamic hedging delta adjustments.
      </span>
    </div>
  </div>
</template>

<style scoped>
.instant-hedging-card {
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
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-eyebrow {
  font-size: var(--t-nano);
  letter-spacing: 0.06em;
  color: var(--ink-dim);
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.metrics-stack {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  flex: 1 1 auto;
  justify-content: space-evenly;
}

.metric-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.25rem 0;
  border-bottom: 1px solid var(--rule-faint);
  gap: 0.5rem;
}

.metric-row:last-child {
  border-bottom: none;
}

.m-left {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  min-width: 0;
}

.m-label {
  font-size: var(--t-micro);
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.m-val {
  font-size: 0.8125rem;
  white-space: nowrap;
  flex-shrink: 0;
}

.card-footer {
  padding-top: 0.25rem;
  border-top: 1px solid var(--rule-faint);
}

.sub-caption {
  font-size: var(--t-nano);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: block;
}
</style>
