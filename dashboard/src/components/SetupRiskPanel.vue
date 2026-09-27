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

const riskPresets = computed(() => {
  const ceiling = maxRiskPct.value * 100
  const candidateList = [0.25, 0.5, 0.75, 1.0, 2.0]
  const list = candidateList.filter((p) => p <= ceiling)
  if (!list.includes(ceiling) && ceiling > 0) {
    list.push(ceiling)
  }
  return list.sort((a, b) => a - b).slice(0, 4)
})

function setRiskPreset(pct: number): void {
  selectedRiskPct.value = pct
}

const isCustomDebit = computed(() => {
  if (props.referenceDebit == null || netDebit.value == null) return false
  return Math.abs(netDebit.value - props.referenceDebit) > 0.001
})

function resetToReferenceDebit(): void {
  if (props.referenceDebit != null) {
    netDebit.value = props.referenceDebit
  }
}

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

const heatPercent = computed(() => {
  if (sizing.value.portfolioRiskBudget <= 0) return 0
  const pct = Math.round(
    (sizing.value.remainingPortfolioHeat / sizing.value.portfolioRiskBudget) * 100,
  )
  return Math.max(0, Math.min(100, pct))
})

const lossPerContract = computed(() => {
  if (sizing.value.contracts > 0 && sizing.value.maxLoss > 0) {
    return sizing.value.maxLoss / sizing.value.contracts
  }
  if (spreadWidth.value != null && spreadWidth.value > 0) {
    return spreadWidth.value * 100
  }
  if (netDebit.value != null && netDebit.value > 0) {
    return netDebit.value * 100
  }
  return null
})

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
      <div class="risk-head-title">
        <span class="label eyebrow">Defined-risk sizing</span>
        <h3 id="risk-title">Risk before contracts</h3>
      </div>
      <span class="risk-state label" :class="sizing.state">{{ stateCopy }}</span>
    </header>

    <div class="risk-inputs">
      <label class="input-cell">
        <span class="label">Account equity</span>
        <span class="input-shell fig">
          <i>$</i>
          <input
            v-model.number="accountEquity"
            type="number"
            min="0"
            step="1000"
            aria-label="Account equity in dollars"
          />
        </span>
      </label>

      <label class="input-cell risk-pct-cell">
        <div class="risk-pct-head">
          <span class="label">Risk / trade</span>
          <span class="policy-cap-note label">Max {{ num(maxRiskPct * 100, 1) }}%</span>
        </div>
        <span class="input-shell fig">
          <input
            v-model.number="selectedRiskPct"
            type="number"
            min="0"
            :max="maxRiskPct * 100"
            step="0.1"
            aria-label="Target risk percentage per trade"
          />
          <i>%</i>
        </span>
        <div v-if="riskPresets.length > 1" class="quick-risk-presets">
          <button
            v-for="preset in riskPresets"
            :key="preset"
            type="button"
            class="preset-btn label"
            :class="{ active: Math.abs(selectedRiskPct - preset) < 0.01 }"
            @click="setRiskPreset(preset)"
          >
            {{ preset }}%
          </button>
        </div>
      </label>

      <label class="input-cell">
        <span class="label">Open portfolio risk</span>
        <span class="input-shell fig">
          <i>$</i>
          <input
            v-model.number="openRiskDollars"
            type="number"
            min="0"
            step="100"
            aria-label="Open portfolio risk in dollars"
          />
        </span>
      </label>

      <label class="input-cell quote-input">
        <div class="input-label-row">
          <span class="label">Debit / premium</span>
          <button
            v-if="isCustomDebit && props.referenceDebit != null"
            type="button"
            class="revert-btn label"
            title="Reset to contract midpoint"
            @click="resetToReferenceDebit()"
          >
            RESET
          </button>
        </div>
        <span class="input-shell fig">
          <i>$</i>
          <input
            :value="netDebit ?? ''"
            type="number"
            min="0"
            step="0.01"
            placeholder="Required"
            aria-label="Option net debit or premium per share"
            @input="netDebit = inputNumber($event)"
          />
        </span>
        <small v-if="referenceLabel" class="ref-label">{{ referenceLabel }}</small>
      </label>

      <label class="input-cell">
        <span class="label">Spread width</span>
        <span class="input-shell fig">
          <i>$</i>
          <input
            :value="spreadWidth ?? ''"
            type="number"
            min="0"
            step="0.5"
            placeholder="Optional"
            aria-label="Optional spread width in dollars"
            @input="spreadWidth = inputNumber($event)"
          />
        </span>
      </label>
    </div>

    <!-- Portfolio Heat Capacity Gauge -->
    <div class="heat-gauge-strip">
      <div class="heat-meta">
        <span class="label">Portfolio heat capacity</span>
        <span class="heat-readout fig">
          {{ usd(sizing.remainingPortfolioHeat, 0) }} / {{ usd(sizing.portfolioRiskBudget, 0) }}
          <span class="heat-pct label">({{ heatPercent }}% available)</span>
        </span>
      </div>
      <div class="risk-meter" aria-label="Portfolio heat remaining">
        <span
          :style="{ width: `${heatPercent}%` }"
          :class="{ tight: heatPercent <= 20, warning: heatPercent <= 10 }"
        />
      </div>
    </div>

    <!-- Math transparency breakdown -->
    <div v-if="lossPerContract && sizing.effectiveBudget > 0" class="sizing-formula label">
      <span
        >Budget <strong>{{ usd(sizing.effectiveBudget, 0) }}</strong></span
      >
      <span class="op">&divide;</span>
      <span
        >Max loss / 1 <strong>${{ num(lossPerContract, 0) }}</strong></span
      >
      <span class="op">=</span>
      <span class="result" :class="{ positive: sizing.contracts > 0 }">
        <strong>{{ sizing.contracts }}</strong>
        {{ sizing.contracts === 1 ? 'Contract' : 'Contracts' }}
      </span>
    </div>

    <dl class="risk-output">
      <div class="output-tile">
        <dt class="label">Effective budget</dt>
        <dd class="fig">{{ usd(sizing.effectiveBudget, 0) }}</dd>
        <small class="tile-sub">Min(Trade cap, Heat)</small>
      </div>
      <div class="output-tile contracts">
        <dt class="label">Max contracts</dt>
        <dd class="fig">{{ sizing.contracts }}</dd>
        <small class="tile-sub">{{ sizing.contracts > 0 ? 'Permitted size' : 'Locked' }}</small>
      </div>
      <div class="output-tile">
        <dt class="label">Maximum loss</dt>
        <dd class="fig">{{ usd(sizing.maxLoss, 0) }}</dd>
        <small class="tile-sub">Defined exit risk</small>
      </div>
      <div class="output-tile">
        <dt class="label">Max reward / risk</dt>
        <dd class="fig">
          {{ sizing.rewardRisk == null ? DASH : `${num(sizing.rewardRisk, 2)}×` }}
        </dd>
        <small class="tile-sub">Payoff multiple</small>
      </div>
    </dl>

    <div class="risk-footer">
      <p class="risk-policy">
        Per-trade cap {{ num(maxRiskPct * 100, 1) }}% · portfolio heat cap
        {{ num(maxHeatPct * 100, 1) }}%.
        {{ risk?.entry_order || 'Use a bounded limit order.' }}
      </p>
      <p class="risk-warning" :class="{ planning: sizingEnabled && !entryEligible }">
        <template v-if="entryEligible">
          Sizing stays at zero until a live net debit is entered.
        </template>
        <template v-else-if="sizingEnabled">
          Planning size only: freshness or confidence has not cleared the live-entry gate.
        </template>
        <template v-else-if="mode === 'paper_candidate'">
          Sizing stays at zero. Paper candidate: a delayed quote cannot unlock live size.
        </template>
        <template v-else> Sizing stays at zero because this row has no directional plan. </template>
        This calculator does not authorize execution.
      </p>
    </div>
  </section>
</template>

<style scoped>
.risk-panel {
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-1);
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

.risk-head-title h3 {
  margin: 3px 0 0;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: var(--t-body);
  font-weight: 600;
  letter-spacing: var(--track-tight);
}

.risk-head .eyebrow {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
}

.risk-state {
  padding: 4px 9px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: var(--track-label);
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

.input-cell {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-width: 0;
  padding: var(--s2) var(--s3);
  background: var(--void-lift);
  transition: background var(--dur-fast) var(--ease-out);
}

.input-cell:focus-within {
  background: var(--panel-hi);
}

.input-cell > .label {
  display: block;
  margin-bottom: 5px;
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.risk-pct-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s1);
  margin-bottom: 5px;
}

.risk-pct-head .label {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.policy-cap-note {
  color: var(--ink-faint);
  font-size: var(--t-nano);
}

.quick-risk-presets {
  display: flex;
  gap: 3px;
  margin-top: 5px;
}

.preset-btn {
  padding: 1px 4px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  background: var(--panel);
  color: var(--ink-dim);
  font-size: var(--t-nano);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.preset-btn:hover {
  color: var(--ink);
  border-color: var(--rule-hi);
}

.preset-btn.active {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
  font-weight: 600;
}

.input-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 5px;
}

.input-label-row .label {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.revert-btn {
  padding: 1px 5px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  background: transparent;
  color: var(--phosphor);
  font-size: var(--t-nano);
  cursor: pointer;
}

.revert-btn:hover {
  background: var(--phosphor-wash);
}

.quote-input {
  box-shadow: inset 0 2px 0 var(--phosphor-dim);
}

.ref-label {
  display: block;
  margin-top: 4px;
  color: var(--call-hi);
  font-size: var(--t-nano);
  line-height: 1.25;
}

.input-shell {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 6px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  background: var(--panel);
  color: var(--ink);
  transition: border-color var(--dur-fast) var(--ease-out);
}

.input-cell:focus-within .input-shell {
  border-color: var(--phosphor);
  outline: var(--focus-ring);
  outline-offset: -1px;
}

.input-shell i {
  color: var(--ink-dim);
  font-style: normal;
  font-size: var(--t-small);
}

.input-shell input {
  width: 100%;
  min-width: 0;
  border: none;
  padding: 0;
  background: transparent;
  color: var(--ink);
  font-family: var(--font-data);
  font-size: var(--t-body);
  font-variant-numeric: tabular-nums;
  outline: none;
}

.input-shell input::placeholder {
  color: var(--ink-faint);
}

.heat-gauge-strip {
  padding: var(--s2) var(--s3);
  background: var(--panel-hi);
  border-top: var(--hair) solid var(--rule);
  border-bottom: var(--hair) solid var(--rule);
}

.heat-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.heat-meta .label {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.heat-readout {
  color: var(--ink-soft);
  font-size: var(--t-tiny);
  font-variant-numeric: tabular-nums;
}

.heat-pct {
  color: var(--ink-dim);
  margin-left: var(--s1);
}

.risk-meter {
  position: relative;
  height: 5px;
  border-radius: var(--r-xs);
  background: var(--rule);
  overflow: hidden;
}

.risk-meter span {
  display: block;
  height: 100%;
  background: var(--phosphor);
  border-radius: var(--r-xs);
  transition: width var(--dur) var(--ease-out);
}

.risk-meter span.tight {
  background: var(--warn);
}

.risk-meter span.warning {
  background: var(--short);
}

.sizing-formula {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s2);
  padding: var(--s2) var(--s3);
  background: var(--void-lift);
  border-bottom: var(--hair) solid var(--rule-faint);
  color: var(--ink-dim);
  font-size: var(--t-micro);
}

.sizing-formula strong {
  color: var(--ink);
}

.sizing-formula .op {
  color: var(--ink-faint);
}

.sizing-formula .result {
  color: var(--ink-soft);
}

.sizing-formula .result.positive strong {
  color: var(--phosphor);
}

.risk-output {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  margin: 0;
  background: var(--panel);
}

.output-tile {
  padding: var(--s3);
  border-right: var(--hair) solid var(--rule);
  display: flex;
  flex-direction: column;
}

.output-tile:last-child {
  border-right: 0;
}

.output-tile dt {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.output-tile dd {
  margin: 4px 0 2px;
  color: var(--ink);
  font-size: var(--t-lead);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.output-tile.contracts dd {
  color: var(--phosphor);
  font-size: var(--t-fig);
}

.tile-sub {
  color: var(--ink-faint);
  font-size: var(--t-nano);
}

.risk-footer {
  padding: var(--s2) var(--s3) var(--s3);
  background: var(--void-lift);
  border-top: var(--hair) solid var(--rule-faint);
}

.risk-policy {
  margin: 0 0 4px;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.45;
}

.risk-warning {
  margin: 0;
  color: var(--warn);
  font-size: var(--t-tiny);
  line-height: 1.45;
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
  .output-tile:nth-child(2) {
    border-right: 0;
  }
  .output-tile:nth-child(-n + 2) {
    border-bottom: var(--hair) solid var(--rule);
  }
}
</style>
