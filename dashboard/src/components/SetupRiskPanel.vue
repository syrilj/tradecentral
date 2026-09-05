<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { LiveOpportunityPlaybook } from '@/api'
import { DASH, num, usd } from '@/format'
import { sizeDefinedRisk } from '@/riskSizing'

const props = defineProps<{
  risk: LiveOpportunityPlaybook['risk'] | null | undefined
  setupStatus: string | null | undefined
  referenceDebit?: number | null
  referenceLabel?: string | null
}>()

const STORAGE_KEY = 'tradecentral.setup-risk.v1'
const accountEquity = ref(100_000)
const selectedRiskPct = ref(0.5)
const openRiskDollars = ref(0)
const netDebit = ref<number | null>(null)
const spreadWidth = ref<number | null>(null)

watch(
  () => props.referenceDebit,
  (value) => {
    const debit = Number(value)
    netDebit.value = Number.isFinite(debit) && debit > 0 ? debit : null
  },
  { immediate: true },
)

const maxRiskPct = computed(() => Number(props.risk?.max_account_risk_pct ?? 0.005))
const maxHeatPct = computed(() => Number(props.risk?.max_portfolio_heat_pct ?? 0.02))
const mode = computed(() => String(props.setupStatus || '').toLowerCase())
const entryEligible = computed(() => mode.value === 'candidate')
const sizingEnabled = computed(() => ['candidate', 'research_only', 'plan'].includes(mode.value))

const sizing = computed(() =>
  sizeDefinedRisk({
    accountEquity: accountEquity.value,
    riskPct: selectedRiskPct.value / 100,
    maxRiskPct: maxRiskPct.value,
    portfolioHeatPct: maxHeatPct.value,
    openRiskDollars: openRiskDollars.value,
    netDebit: netDebit.value,
    spreadWidth: spreadWidth.value,
    eligible: sizingEnabled.value,
  }),
)

const stateCopy = computed(() => {
  if (sizing.value.state === 'blocked') return 'SETUP NOT ENTRY-ELIGIBLE'
  if (sizing.value.state === 'quote_required')
    return entryEligible.value ? 'ENTER LIVE NET DEBIT' : 'ENTER DEBIT TO PLAN'
  if (sizing.value.state === 'no_capacity') return 'NO RISK CAPACITY'
  const count = `${sizing.value.contracts} CONTRACT${sizing.value.contracts === 1 ? '' : 'S'}`
  return entryEligible.value ? `${count} MAX` : `PLAN ${count}`
})

function inputNumber(event: Event): number | null {
  const value = Number((event.target as HTMLInputElement).value)
  return Number.isFinite(value) && value >= 0 ? value : null
}

onMounted(() => {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as Record<string, unknown>
    if (Number(saved.accountEquity) > 0) accountEquity.value = Number(saved.accountEquity)
    if (Number(saved.selectedRiskPct) > 0) selectedRiskPct.value = Number(saved.selectedRiskPct)
    if (Number(saved.openRiskDollars) >= 0) openRiskDollars.value = Number(saved.openRiskDollars)
  } catch {
    // A malformed browser preference must never prevent risk controls rendering.
  }
})

watch([accountEquity, selectedRiskPct, openRiskDollars], () => {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        accountEquity: accountEquity.value,
        selectedRiskPct: selectedRiskPct.value,
        openRiskDollars: openRiskDollars.value,
      }),
    )
  } catch {
    // Storage can be unavailable in hardened/private browser contexts.
  }
})
</script>

<template>
  <section class="risk-panel" aria-labelledby="risk-title">
    <header class="risk-head">
      <div>
        <span class="label">Defined-risk sizing</span>
        <h3 id="risk-title">Risk before contracts</h3>
      </div>
      <span class="risk-state label" :class="sizing.state">{{ stateCopy }}</span>
    </header>

    <div class="risk-inputs">
      <label>
        <span class="label">Account equity</span>
        <span class="input-shell fig"
          ><i>$</i><input v-model.number="accountEquity" type="number" min="0" step="1000"
        /></span>
      </label>
      <label>
        <span class="label">Risk / trade</span>
        <span class="input-shell fig"
          ><input
            v-model.number="selectedRiskPct"
            type="number"
            min="0"
            :max="maxRiskPct * 100"
            step="0.1"
          /><i>%</i></span
        >
      </label>
      <label>
        <span class="label">Open portfolio risk</span>
        <span class="input-shell fig"
          ><i>$</i><input v-model.number="openRiskDollars" type="number" min="0" step="100"
        /></span>
      </label>
      <label class="quote-input">
        <span class="label">Debit / premium</span>
        <span class="input-shell fig"
          ><i>$</i
          ><input
            :value="netDebit ?? ''"
            type="number"
            min="0"
            step="0.01"
            placeholder="Required"
            @input="netDebit = inputNumber($event)"
        /></span>
        <small v-if="referenceLabel">{{ referenceLabel }}</small>
      </label>
      <label>
        <span class="label">Spread width</span>
        <span class="input-shell fig"
          ><i>$</i
          ><input
            :value="spreadWidth ?? ''"
            type="number"
            min="0"
            step="0.5"
            placeholder="Optional"
            @input="spreadWidth = inputNumber($event)"
        /></span>
      </label>
    </div>

    <div class="risk-meter" aria-label="Portfolio heat remaining">
      <span
        :style="{
          width: `${Math.min(100, sizing.portfolioRiskBudget > 0 ? (sizing.remainingPortfolioHeat / sizing.portfolioRiskBudget) * 100 : 0)}%`,
        }"
      />
    </div>

    <dl class="risk-output">
      <div>
        <dt class="label">Effective budget</dt>
        <dd class="fig">{{ usd(sizing.effectiveBudget, 0) }}</dd>
      </div>
      <div class="contracts">
        <dt class="label">Max contracts</dt>
        <dd class="fig">{{ sizing.contracts }}</dd>
      </div>
      <div>
        <dt class="label">Maximum loss</dt>
        <dd class="fig">{{ usd(sizing.maxLoss, 0) }}</dd>
      </div>
      <div>
        <dt class="label">Max reward / risk</dt>
        <dd class="fig">
          {{ sizing.rewardRisk == null ? DASH : `${num(sizing.rewardRisk, 2)}×` }}
        </dd>
      </div>
    </dl>

    <p class="risk-policy">
      Per-trade cap {{ num(maxRiskPct * 100, 1) }}% · portfolio heat cap
      {{ num(maxHeatPct * 100, 1) }}%.
      {{ risk?.entry_order || 'Use a bounded limit order.' }}
    </p>
    <p class="risk-warning" :class="{ planning: sizingEnabled && !entryEligible }">
      <template v-if="entryEligible"
        >Sizing stays at zero until a live net debit is entered.</template
      >
      <template v-else-if="sizingEnabled"
        >Planning size only: freshness or confidence has not cleared the live-entry gate.</template
      >
      <template v-else>Sizing stays at zero because this row has no directional plan.</template>
      This calculator does not authorize execution.
    </p>
  </section>
</template>

<style scoped>
.risk-panel {
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-md);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  background: var(--panel);
  overflow: hidden;
}

.risk-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s3);
  background: var(--panel-hi);
  border-bottom: var(--hair) solid var(--rule);
}

.risk-head h3 {
  margin-top: 3px;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: var(--t-small);
  font-weight: 600;
}

.risk-state {
  padding: 3px 7px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
}
.risk-state.ready {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.risk-state.blocked {
  color: var(--short);
  border-color: var(--short);
  background: var(--short-wash);
}
.risk-state.quote_required,
.risk-state.no_capacity {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}

.risk-inputs {
  display: grid;
  grid-template-columns: repeat(5, minmax(90px, 1fr));
  gap: var(--hair);
  background: var(--rule);
}

.risk-inputs label {
  min-width: 0;
  padding: var(--s2) var(--s3);
  background: var(--void-lift);
}

.risk-inputs label > .label {
  display: block;
  margin-bottom: 5px;
  color: var(--ink-faint);
}
.risk-inputs small {
  display: block;
  margin-top: 3px;
  color: var(--call-hi);
  font-size: var(--t-micro);
  line-height: 1.25;
}
.quote-input {
  box-shadow: inset 0 2px 0 var(--phosphor-dim);
}

.input-shell {
  display: flex;
  align-items: center;
  gap: 3px;
  color: var(--ink);
}
.input-shell i {
  color: var(--ink-faint);
  font-style: normal;
}
.input-shell input {
  width: 100%;
  min-width: 0;
}
.input-shell input::placeholder {
  color: var(--ink-faint);
}

.risk-meter {
  height: 3px;
  background: var(--rule-faint);
}
.risk-meter span {
  display: block;
  height: 100%;
  background: var(--phosphor-dim);
  transition: width var(--dur) var(--ease-out);
}

.risk-output {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  margin: 0;
}
.risk-output > div {
  padding: var(--s3);
  border-right: var(--hair) solid var(--rule);
}
.risk-output > div:last-child {
  border-right: 0;
}
.risk-output dt {
  color: var(--ink-faint);
}
.risk-output dd {
  margin-top: 4px;
  color: var(--ink-soft);
  font-size: var(--t-lead);
}
.risk-output .contracts dd {
  color: var(--phosphor);
  font-size: var(--t-fig);
}

.risk-policy,
.risk-warning {
  margin: 0;
  padding: 0 var(--s3) var(--s2);
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.45;
}
.risk-warning {
  padding-bottom: var(--s3);
  color: var(--warn);
}
.risk-warning.planning {
  color: var(--call-hi);
}

@media (max-width: 840px) {
  .risk-inputs {
    grid-template-columns: 1fr 1fr;
  }
  .risk-output {
    grid-template-columns: 1fr 1fr;
  }
  .risk-output > div:nth-child(2) {
    border-right: 0;
  }
  .risk-output > div:nth-child(-n + 2) {
    border-bottom: var(--hair) solid var(--rule);
  }
}
</style>
