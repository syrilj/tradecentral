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
  padding: 4px 9px 4px 7px;
  border: var(--hair) solid currentColor;
  color: var(--unknown);
  letter-spacing: 0.08em;
  line-height: 1;
  font-weight: 700;
  border-radius: 2px;
}

.s-sm { padding: 3px 7px 3px 6px; font-size: var(--t-tiny); }

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
.running .dot { animation: pulse-lamp 1.4s var(--ease-in-out) infinite; }
.unknown { color: var(--unknown); }
</style>
