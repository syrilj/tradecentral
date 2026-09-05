<script setup lang="ts">
import { computed } from 'vue'
import { optSigned, DASH } from '@/format'
import type { GammaRegime } from '@/regimeContracts'

const props = withDefaults(
  defineProps<{
    regime?: GammaRegime | null
    dealerBias?: string | null
    crowdPositioning?: string | null
    smartMoneyFlow?: string | null
    netDeltaM?: number | null
  }>(),
  {
    regime: null,
    dealerBias: null,
    crowdPositioning: null,
    smartMoneyFlow: null,
    netDeltaM: null,
  },
)

const dealerPositioning = computed(() => {
  if (props.regime === 'long') return 'Long Gamma'
  if (props.regime === 'short') return 'Short Gamma'
  if (props.regime === 'flip') return 'Neutral / Flip'
  return 'Unmeasured'
})

const resolvedDealerBias = computed(() => {
  if (props.dealerBias) return props.dealerBias
  if (props.regime === 'short') return 'Slightly Bearish'
  if (props.regime === 'long') return 'Moderately Bullish'
  if (props.regime === 'flip') return 'Neutral'
  return 'Unmeasured'
})
</script>

<template>
  <div class="positioning-summary-card">
    <div class="card-header">
      <span class="card-eyebrow font-mono">POSITIONING SUMMARY</span>
    </div>

    <div class="positioning-rows">
      <!-- Dealer Positioning -->
      <div class="pos-row">
        <span class="pos-label font-mono">Dealer Positioning</span>
        <span
          class="pos-pill font-mono font-bold"
          :class="regime === 'long' ? 'pill-bullish' : regime === 'short' ? 'pill-bearish' : 'pill-neutral'"
        >
          {{ dealerPositioning }}
        </span>
      </div>

      <!-- Dealer Bias -->
      <div class="pos-row">
        <span class="pos-label font-mono">Dealer Bias</span>
        <span
          class="pos-pill font-mono font-bold"
          :class="regime === 'long' ? 'pill-bullish' : regime === 'short' ? 'pill-warn' : 'pill-neutral'"
        >
          {{ resolvedDealerBias }}
        </span>
      </div>

      <!-- Crowd Positioning -->
      <div class="pos-row">
        <span class="pos-label font-mono">Crowd Positioning</span>
        <span
          class="pos-pill font-mono font-bold"
          :class="crowdPositioning ? (crowdPositioning.toLowerCase().includes('bull') ? 'pill-bullish' : 'pill-bearish') : 'pill-neutral'"
        >
          {{ crowdPositioning ?? DASH }}
        </span>
      </div>

      <!-- Smart Money Flow -->
      <div class="pos-row">
        <span class="pos-label font-mono">Smart Money Flow</span>
        <span
          class="pos-pill font-mono font-bold"
          :class="smartMoneyFlow ? (smartMoneyFlow.toLowerCase().includes('bull') ? 'pill-bullish' : 'pill-bearish') : 'pill-neutral'"
        >
          {{ smartMoneyFlow ?? DASH }}
        </span>
      </div>

      <!-- Net Delta -->
      <div class="pos-row">
        <span class="pos-label font-mono">Net Delta (All Exp)</span>
        <span
          class="delta-val font-mono font-bold"
          :class="netDeltaM == null ? 'text-ink-dim' : netDeltaM >= 0 ? 'text-call-hi' : 'text-put-hi'"
        >
          {{ netDeltaM != null ? `${optSigned(netDeltaM, 1)}M` : DASH }}
        </span>
      </div>
    </div>

    <!-- Card Footer -->
    <div class="card-footer">
      <span class="sub-caption font-mono text-ink-dim">
        Data aggregated across all expirations.
      </span>
    </div>
  </div>
</template>

<style scoped>
.positioning-summary-card {
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
}

.card-eyebrow {
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
  color: var(--ink-dim);
  font-weight: 700;
}

.positioning-rows {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

/* Value gets its own column so a long bias sentence wraps without pushing
   leftwards into the label. Labels and values never share a baseline. */
.pos-row {
  display: grid;
  grid-template-columns: minmax(0, auto) minmax(0, 1fr);
  align-items: center;
  gap: var(--s3);
  padding: 0.25rem 0;
  border-bottom: 1px solid var(--rule-faint);
}

.pos-row:last-child {
  border-bottom: none;
}

.pos-row > :last-child {
  justify-self: end;
  text-align: right;
}

.pos-label {
  font-size: 0.75rem;
  color: var(--ink-dim);
  white-space: nowrap;
}

.pos-pill {
  font-size: var(--t-micro);
  padding: 0.15rem 0.5rem;
  border-radius: var(--r-xs);
  white-space: normal;
  line-height: 1.35;
  max-width: 100%;
  /* Clamp long dealer_hedging_action sentences to 2 lines so they don't
     push the card height or get invisibly clipped by overflow:hidden. */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.pill-bullish {
  background: var(--call-wash);
  color: var(--call-hi);
  border: 1px solid var(--call-dim);
}

.pill-bearish {
  background: var(--put-wash);
  color: var(--put-hi);
  border: 1px solid var(--put-dim);
}

.pill-warn {
  background: var(--warn-wash);
  color: var(--warn);
  border: 1px solid var(--warn);
}

.pill-neutral {
  background: var(--panel-hi);
  color: var(--ink-soft);
  border: 1px solid var(--rule-hi);
}

.delta-val {
  font-size: 0.875rem;
}

.card-footer {
  padding-top: 0.25rem;
  border-top: 1px solid var(--rule-faint);
}

.sub-caption {
  font-size: var(--t-micro);
}
</style>
