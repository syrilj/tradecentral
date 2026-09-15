<script setup lang="ts">
import { computed } from 'vue'
import { DASH } from '@/format'
import { flowMixStats } from '@/flowDisplay'

const props = withDefaults(
  defineProps<{
    totalPremiumM?: number | null
    bullishPremiumM?: number | null
    bearishPremiumM?: number | null
    netFlowM?: number | null
  }>(),
  {
    totalPremiumM: null,
    bullishPremiumM: null,
    bearishPremiumM: null,
    netFlowM: null,
  },
)

const mix = computed(() => flowMixStats(props))
const hasFlow = computed(() => mix.value.hasMix)

const bullishPct = computed(() => mix.value.bullishPct)

const radius = 28
const circumference = 2 * Math.PI * radius
const bullishDasharray = computed(() => {
  const arcLength = ((bullishPct.value ?? 0) / 100) * circumference
  return `${arcLength.toFixed(1)} ${circumference.toFixed(1)}`
})

const donutStroke = computed(() => (hasFlow.value ? 'var(--call)' : 'var(--rule-hi)'))
</script>

<template>
  <div class="flow-summary-card">
    <div class="card-header">
      <div>
        <span class="card-eyebrow font-display font-semibold">FLOW SUMMARY (TODAY)</span>
        <p class="card-subtitle">Measured option premium split by directional side.</p>
      </div>
      <span class="card-period font-mono">TODAY</span>
    </div>

    <div class="summary-body">
      <div class="stat-col">
        <span class="stat-label font-ui">Total premium</span>
        <span class="stat-val font-mono font-bold">{{ mix.totalPremium }}</span>
        <span class="stat-helper">Calls + puts</span>
      </div>

      <div class="donut-wrap">
        <svg class="donut-svg" viewBox="0 0 70 70" role="img" aria-label="Flow mix">
          <circle
            cx="35"
            cy="35"
            :r="radius"
            fill="none"
            :stroke="hasFlow ? 'var(--put)' : 'var(--rule)'"
            stroke-width="7"
          />
          <circle
            cx="35"
            cy="35"
            :r="radius"
            fill="none"
            :stroke="donutStroke"
            stroke-width="7"
            :stroke-dasharray="hasFlow ? bullishDasharray : `${circumference} 0`"
            stroke-dashoffset="0"
            transform="rotate(-90 35 35)"
            stroke-linecap="round"
          />
          <text x="35" y="38" text-anchor="middle" class="donut-label font-mono font-bold">
            {{ hasFlow ? `${bullishPct}%` : DASH }}
          </text>
        </svg>
      </div>

      <ul class="flow-legend">
        <li class="legend-row">
          <span class="swatch swatch-bull" aria-hidden="true"></span>
          <span class="stat-label font-ui">Bullish</span>
          <span class="stat-val font-mono font-bold text-call-hi">{{ mix.bullishLabel }}</span>
        </li>
        <li class="legend-row">
          <span class="swatch swatch-bear" aria-hidden="true"></span>
          <span class="stat-label font-ui">Bearish</span>
          <span class="stat-val font-mono font-bold text-put-hi">{{ mix.bearishLabel }}</span>
        </li>
        <li class="legend-row">
          <span class="swatch swatch-net" aria-hidden="true"></span>
          <span class="stat-label font-ui">Net Flow</span>
          <span
            class="stat-val font-mono font-bold"
            :class="mix.netFlow === DASH ? '' : 'text-ink'"
          >
            {{ mix.netFlow }}
          </span>
        </li>
      </ul>
    </div>

    <p class="summary-read" :class="{ 'is-muted': !hasFlow }">
      {{ hasFlow ? `${mix.bullishLabel} of measured premium is bullish; ${mix.bearishLabel} is bearish.` : 'Directional mix is not measurable in this window.' }}
    </p>
  </div>
</template>

<style scoped>
.flow-summary-card {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: 1rem 1.125rem;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 0.5rem;
  box-sizing: border-box;
  overflow: hidden;
  min-width: 0;
  height: 100%;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-subtitle {
  margin: 0.25rem 0 0;
  color: var(--ink-faint);
  font-size: var(--t-micro);
  line-height: 1.35;
}

.card-period {
  align-self: flex-start;
  color: var(--phosphor);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
}

.card-eyebrow {
  font-family: var(--font-display);
  font-size: 0.75rem;
  letter-spacing: 0.06em;
  color: var(--ink-dim);
  font-weight: 700;
  white-space: nowrap;
}

.summary-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 68px minmax(132px, 1fr);
  align-items: center;
  gap: 1rem;
  margin: 0.5rem 0;
  min-width: 0;
}

.stat-col {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-width: 0;
}

.stat-label {
  font-family: var(--font-ui);
  font-size: 0.75rem;
  color: var(--ink-dim);
  white-space: nowrap;
}

.stat-val {
  font-family: var(--font-data);
  font-size: 0.875rem;
  color: var(--ink);
  white-space: nowrap;
}

.stat-helper {
  color: var(--ink-faint);
  font-size: var(--t-nano);
}

.donut-wrap {
  width: 68px;
  height: 68px;
  flex-shrink: 0;
}

.donut-svg {
  width: 100%;
  height: 100%;
}

.donut-label {
  fill: var(--ink);
  font-family: var(--font-data);
  font-size: 0.75rem;
}

.flow-legend {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
  flex: 1;
}

.legend-row {
  display: grid;
  grid-template-columns: 8px auto 1fr;
  align-items: center;
  gap: 0.375rem;
  min-width: 0;
}

.legend-row .stat-val {
  justify-self: end;
  /* Allow the value to wrap rather than silently clipping signed premium
     strings like "+$312.6M" when the card is in a narrow grid column. */
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
  text-align: right;
}

.summary-read {
  margin: 0;
  padding-top: 0.625rem;
  border-top: 1px solid var(--rule-faint);
  color: var(--ink-soft);
  font-size: var(--t-micro);
  line-height: 1.45;
}

.summary-read.is-muted {
  color: var(--ink-faint);
}

@media (max-width: 520px) {
  .summary-body {
    grid-template-columns: minmax(0, 1fr) 64px;
  }

  .flow-legend {
    grid-column: 1 / -1;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.5rem;
  }

  .legend-row .stat-val {
    justify-self: start;
  }
}

.swatch {
  width: 8px;
  height: 8px;
  border-radius: var(--r-xs);
  flex-shrink: 0;
}

.swatch-bull {
  background: var(--call);
}

.swatch-bear {
  background: var(--put);
}

.swatch-net {
  background: var(--panel-raise);
  border: 1px solid var(--rule-hi);
}
</style>
