<script setup lang="ts">
import { computed } from 'vue'

/**
 * Renders a pre-registered gate verdict with human-readable status labels.
 */
const props = withDefaults(
  defineProps<{ verdict: string; size?: 'sm' | 'md' }>(),
  { size: 'md' },
)

const kind = computed(() => {
  const v = (props.verdict ?? '').toUpperCase().replace(/[\s_]/g, '-')
  if (v === 'GO') return 'go'
  if (v === 'NO-GO' || v === 'NOGO' || v === 'FAIL') return 'no-go'
  if (v.includes('RUN') || v.includes('PEND')) return 'running'
  return 'unknown'
})

const labelText = computed(() => {
  const v = (props.verdict ?? '').toUpperCase().trim()
  if (v === 'GO') return 'GO: CLEARED'
  if (v === 'NO-GO' || v === 'NOGO') return 'HELD (RISK LIMIT)'
  if (v === 'FAIL') return 'REJECTED: HIGH RISK'
  return v || 'UNEVALUATED'
})

const tooltipText = computed(() => {
  if (kind.value === 'go') return 'Pre-registered backtest passed all turnover, drawdown, and IC gates.'
  if (kind.value === 'no-go') return 'Gate evaluation failed turnover or drawdown risk thresholds.'
  return 'Gate status pending or unevaluated.'
})
</script>

<template>
  <span class="chip label" :class="[kind, `s-${size}`]" :title="tooltipText">
    <i class="dot" aria-hidden="true" />
    {{ labelText }}
  </span>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border: var(--hair) solid currentColor;
  color: var(--unknown);
  letter-spacing: 0.05em;
  line-height: 1;
  font-weight: 600;
  border-radius: var(--r-sm);
  backdrop-filter: var(--glass-blur-sm);
  -webkit-backdrop-filter: var(--glass-blur-sm);
  box-shadow: var(--glass-specular-subtle);
}

.s-sm { padding: 2px 6px; font-size: var(--t-micro); }

.dot {
  width: 5px;
  height: 5px;
  background: currentColor;
  border-radius: 50%;
  flex: 0 0 auto;
}

.go { color: var(--go); background: var(--long-wash); }
.no-go { color: var(--no-go); background: var(--short-wash); }
.running { color: var(--running); background: var(--warn-wash); }
.running .dot { animation: pulse-lamp var(--dur-pulse-fast) var(--ease-in-out) infinite; }
.unknown { color: var(--unknown); background: rgba(255, 255, 255, 0.02); }
</style>
