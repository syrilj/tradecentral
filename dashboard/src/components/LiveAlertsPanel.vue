<script setup lang="ts">
/**
 * Supported alert kinds:
 * - 'gex_flip': GEX Flip
 * - 'large_flow': Large Flow
 * - 'support_break': Support Break
 * - 'wall_pin': Wall Pin
 * - 'vol_trigger': Volatility Trigger
 */
export interface RegimeAlert {
  id: string
  type: 'gex_flip' | 'large_flow' | 'support_break' | 'wall_pin' | 'vol_trigger'
  title: string
  desc: string
  time: string
  tone: 'bullish' | 'bearish' | 'warn'
}

withDefaults(
  defineProps<{
    symbol?: string
    alerts?: RegimeAlert[]
  }>(),
  {
    symbol: 'SPY',
    alerts: () => [],
  },
)

const emit = defineEmits<{
  'view-all': []
}>()
</script>

<template>
  <div class="live-alerts-panel">
    <div class="card-header">
      <span class="card-eyebrow font-mono">ALERTS</span>
    </div>

    <div class="alerts-stack">
      <div v-if="!alerts || alerts.length === 0" class="empty-alerts font-mono text-ink-dim">
        No active regime alerts for {{ symbol }}
      </div>
      <div v-for="alert in alerts" :key="alert.id" class="alert-item" :class="`tone-${alert.tone}`">
        <div class="alert-top">
          <div class="alert-title-wrap">
            <span class="alert-status-dot"></span>
            <span class="alert-title font-mono font-bold">{{ alert.title }}</span>
          </div>
          <span class="alert-time font-mono text-ink-dim">{{ alert.time }}</span>
        </div>
        <p class="alert-desc">{{ alert.desc }}</p>
      </div>
    </div>

    <div class="card-footer">
      <button type="button" class="view-all-btn" @click="emit('view-all')">
        View All Alerts
      </button>
    </div>
  </div>
</template>

<style scoped>
.live-alerts-panel {
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
  font-family: var(--font-display);
  font-size: 0.75rem;
  letter-spacing: 0.06em;
  color: var(--ink-dim);
  font-weight: 700;
}

.alerts-stack {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.empty-alerts {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 90px;
  font-family: var(--font-ui);
  font-size: 0.8125rem;
  text-align: center;
  padding: 1rem;
}

.alert-item {
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  border-radius: var(--r-sm);
  padding: 0.625rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.alert-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.alert-title-wrap {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.alert-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}

.alert-item.tone-bullish .alert-status-dot {
  background: var(--call-hi);
}

.alert-item.tone-bearish .alert-status-dot {
  background: var(--put-hi);
}

.alert-item.tone-warn .alert-status-dot {
  background: var(--warn);
}

.alert-title {
  font-family: var(--font-ui);
  font-size: 0.8125rem;
  font-weight: 700;
  color: var(--ink);
}

.alert-time {
  font-family: var(--font-data);
  font-size: 0.75rem;
}

.alert-desc {
  font-family: var(--font-ui);
  font-size: 0.8125rem;
  color: var(--ink-soft);
  margin: 0;
  line-height: 1.45;
}

.card-footer {
  display: flex;
  justify-content: center;
  padding-top: 0.375rem;
  border-top: 1px solid var(--rule-faint);
}

.view-all-btn {
  background: transparent;
  border: none;
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  padding: 0.15rem 0.35rem;
  transition: color var(--dur-fast) ease;
}

.view-all-btn:hover {
  color: var(--phosphor);
}
</style>
