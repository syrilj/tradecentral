<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '@/api'
import { debounce } from '@/composables/useResource'
import { DASH, num, usd } from '@/format'

type Strategy = 'long_call' | 'long_put' | 'long_straddle'

const props = defineProps<{
  defaultStrategy?: Strategy | string | null
  defaultSpot?: number | null
  defaultStrike?: number | null
  defaultDte?: number | null
  defaultVol?: number | null
  defaultPremium?: number | null
  symbol?: string | null
}>()

function asStrategy(value: unknown): Strategy {
  const raw = String(value || '').toLowerCase()
  if (raw === 'long_put' || raw === 'put') return 'long_put'
  if (raw === 'long_straddle' || raw === 'straddle') return 'long_straddle'
  return 'long_call'
}

const strategy = ref<Strategy>(asStrategy(props.defaultStrategy))
const spot = ref(props.defaultSpot && props.defaultSpot > 0 ? props.defaultSpot : 100)
const strike = ref(props.defaultStrike && props.defaultStrike > 0 ? props.defaultStrike : 105)
const dte = ref(props.defaultDte != null && props.defaultDte >= 0 ? props.defaultDte : 30)
const volPct = ref(props.defaultVol && props.defaultVol > 0 ? props.defaultVol * 100 : 30)
const premium = ref(props.defaultPremium != null && props.defaultPremium >= 0 ? props.defaultPremium : 5)
const error = ref<string | null>(null)
const loading = ref(false)
const result = ref<{
  greeks: { delta: number; gamma: number; theta: number; vega: number; theo: number }
  pnl_at_expiry: Array<{ spot: number; pnl: number }>
} | null>(null)

watch(() => props.defaultStrategy, (value) => {
  if (value) strategy.value = asStrategy(value)
})
watch(() => props.defaultSpot, (value) => {
  if (value && value > 0) spot.value = value
})
watch(() => props.defaultStrike, (value) => {
  if (value && value > 0) strike.value = value
})
watch(() => props.defaultDte, (value) => {
  if (value != null && value >= 0) dte.value = value
})
watch(() => props.defaultVol, (value) => {
  if (value && value > 0) volPct.value = value * 100
})
watch(() => props.defaultPremium, (value) => {
  if (value != null && value >= 0) premium.value = value
})

const strategyLabel = computed(() => ({
  long_call: 'Long Call',
  long_put: 'Long Put',
  long_straddle: 'Long Straddle',
}[strategy.value]))

async function run(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    result.value = await api.optionsCalculator({
      strategy: strategy.value,
      spot: spot.value,
      strike: strike.value,
      dte: dte.value,
      vol: volPct.value / 100,
      premium: premium.value,
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Calculator unavailable'
  } finally {
    loading.value = false
  }
}

const refresh = debounce(run, 250)
watch([strategy, spot, strike, dte, volPct, premium], () => { void refresh() }, { immediate: true })

const samplePnl = computed(() => {
  const series = result.value?.pnl_at_expiry ?? []
  if (!series.length) return []
  const picks = [0, Math.floor(series.length * 0.25), Math.floor(series.length * 0.5), Math.floor(series.length * 0.75), series.length - 1]
  return [...new Set(picks)].map((index) => series[index])
})
</script>

<template>
  <section class="calc" aria-labelledby="calc-title">
    <header>
      <div>
        <span class="label">Closed-form P/L</span>
        <h3 id="calc-title">Options profit calculator</h3>
      </div>
      <span class="label">{{ symbol ? `${symbol} · ` : '' }}{{ strategyLabel }} · no order path</span>
    </header>

    <div class="calc-controls">
      <fieldset>
        <legend class="label">Strategy</legend>
        <div>
          <button type="button" :class="{ on: strategy === 'long_call' }" @click="strategy = 'long_call'">Long Call</button>
          <button type="button" :class="{ on: strategy === 'long_put' }" @click="strategy = 'long_put'">Long Put</button>
          <button type="button" :class="{ on: strategy === 'long_straddle' }" @click="strategy = 'long_straddle'">Long Straddle</button>
        </div>
      </fieldset>
      <label><span class="label">Spot</span><input v-model.number="spot" type="number" min="0.01" step="0.5"></label>
      <label><span class="label">Strike</span><input v-model.number="strike" type="number" min="0.01" step="0.5"></label>
      <label><span class="label">Expiry DTE</span><input v-model.number="dte" type="number" min="0" max="730" step="1"></label>
      <label><span class="label">Vol %</span><input v-model.number="volPct" type="number" min="1" max="300" step="0.5"></label>
      <label><span class="label">Premium</span><input v-model.number="premium" type="number" min="0" step="0.05"></label>
    </div>

    <p v-if="error" class="calc-error">{{ error }}</p>
    <dl v-else class="greeks">
      <div><dt class="label">Delta</dt><dd class="fig">{{ result ? num(result.greeks.delta, 3) : DASH }}</dd></div>
      <div><dt class="label">Gamma</dt><dd class="fig">{{ result ? num(result.greeks.gamma, 4) : DASH }}</dd></div>
      <div><dt class="label">Theta</dt><dd class="fig">{{ result ? usd(result.greeks.theta, 2) : DASH }}</dd></div>
      <div><dt class="label">Vega</dt><dd class="fig">{{ result ? usd(result.greeks.vega, 2) : DASH }}</dd></div>
      <div><dt class="label">Theo</dt><dd class="fig">{{ result ? usd(result.greeks.theo, 2) : DASH }}</dd></div>
      <div><dt class="label">Status</dt><dd class="fig">{{ loading ? '…' : 'READY' }}</dd></div>
    </dl>

    <table v-if="samplePnl.length" class="pnl-table">
      <thead>
        <tr>
          <th class="label">Underlying</th>
          <th class="label num">P/L at expiry</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="point in samplePnl" :key="point.spot">
          <td class="fig">{{ usd(point.spot) }}</td>
          <td class="fig num" :class="point.pnl >= 0 ? 'pos' : 'neg'">{{ usd(point.pnl, 0) }}</td>
        </tr>
      </tbody>
    </table>
    <p class="calc-note">Multi-leg P/L is the sum of the same function on each leg. Diagnostic only — not an order ticket.</p>
  </section>
</template>

<style scoped>
.calc { padding: var(--s4); }
.calc header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s3);
  margin-bottom: var(--s4);
}
.calc h3 {
  margin-top: 3px;
  color: var(--ink);
  font: 700 var(--t-small) / 1.2 var(--font-display);
}
.calc-controls {
  display: grid;
  grid-template-columns: minmax(180px, 1.4fr) repeat(5, minmax(90px, 1fr));
  gap: var(--s3);
}
.calc-controls fieldset { border: 0; padding: 0; }
.calc-controls fieldset > div { display: flex; flex-wrap: wrap; gap: 4px; }
.calc-controls button {
  min-height: 28px;
  padding: 0 8px;
  color: var(--text-secondary);
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel);
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 750;
  cursor: pointer;
}
.calc-controls button.on { color: var(--void); border-color: var(--phosphor); background: var(--phosphor); }
.calc-controls label { display: flex; flex-direction: column; gap: 4px; }
.calc-controls input {
  min-height: 28px;
  padding: 0 8px;
  color: var(--ink);
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  font-family: var(--font-data);
}
.greeks {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--s3);
  margin-top: var(--s4);
}
.greeks dd { margin-top: 2px; color: var(--ink); }
.pnl-table { width: 100%; margin-top: var(--s4); border-collapse: collapse; }
.pnl-table th, .pnl-table td { padding: 5px 0; border-bottom: var(--hair) solid var(--rule); }
.pnl-table .num { text-align: right; }
.pos { color: var(--long); }
.neg { color: var(--short); }
.calc-note, .calc-error { margin-top: var(--s3); color: var(--text-tertiary); font-size: var(--t-micro); }
.calc-error { color: var(--warn); }
@media (max-width: 900px) {
  .calc-controls, .greeks { grid-template-columns: 1fr 1fr; }
}
</style>
