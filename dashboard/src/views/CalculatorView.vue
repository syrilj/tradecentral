<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import OptionsCalculator from '@/components/OptionsCalculator.vue'

const route = useRoute()

function numQuery(name: string): number | null {
  const raw = route.query[name]
  const value = Number(Array.isArray(raw) ? raw[0] : raw)
  return Number.isFinite(value) ? value : null
}

const symbol = computed(() =>
  String(route.query.symbol || '')
    .trim()
    .toUpperCase(),
)
const strategy = computed(() => String(route.query.strategy || route.query.right || 'long_call'))
const spot = computed(() => numQuery('spot'))
const strike = computed(() => numQuery('strike'))
const dte = computed(() => numQuery('dte'))
const vol = computed(() => numQuery('vol'))
const premium = computed(() => numQuery('premium'))
const fromSetup = computed(() => Boolean(symbol.value || strike.value || premium.value))
</script>

<template>
  <div class="calc-view">
    <header class="ticked rise">
      <span class="label">Options toolkit</span>
      <h1>Portfolio calculator</h1>
      <p>
        The book lives here, not on the Options tape. Each contract is a row. Setups open this page
        with the exact contract prefilled. Closed-form P/L and Greeks. No live order path.
      </p>
      <p v-if="fromSetup" class="from-setup label">
        Prefill from {{ symbol || 'setup' }} · {{ strategy.replaceAll('_', ' ') }}
      </p>
    </header>
    <OptionsCalculator
      :key="`${symbol}-${strategy}-${spot}-${strike}-${dte}-${vol}-${premium}`"
      :symbol="symbol || null"
      :default-strategy="strategy"
      :default-spot="spot"
      :default-strike="strike"
      :default-dte="dte"
      :default-vol="vol"
      :default-premium="premium"
    />
  </div>
</template>

<style scoped>
/* Surface glass token: var(--glass-surface-hi) */
.calc-view {
  display: grid;
  gap: var(--s5);
}
.calc-view header {
  padding: var(--s5);
  border: var(--hair) solid var(--rule);
  background: var(--panel);
}
.calc-view h1 {
  margin-top: 6px;
  color: var(--ink);
  font: 700 var(--t-display) / 1.15 var(--font-display);
}
.calc-view p {
  max-width: 72ch;
  margin-top: 8px;
  color: var(--ink-dim);
  font-size: var(--t-small);
}
.from-setup {
  color: var(--phosphor);
}
</style>
