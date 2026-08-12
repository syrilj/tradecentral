<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type StatusPayload } from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import FlowDashboard from '@/components/FlowDashboard.vue'

const FLOW_LIMIT = 80
const BASE_FLOW_FLOOR = 25_000
const FLOW_POLL_MS = 15_000

const router = useRouter()
const sharedStatus = inject<Resource<StatusPayload> | null>('status', null)
const statusPayload = computed(() => sharedStatus?.data.value ?? null)
const minPremium = ref(BASE_FLOW_FLOOR)
const forceNext = ref(false)

const unusual = useResource(
  () => api.unusualFlow({
    limit: FLOW_LIMIT,
    minPremium: BASE_FLOW_FLOOR,
    force: forceNext.value,
  }),
  { intervalMs: FLOW_POLL_MS },
)

function setPremium(value: number): void {
  minPremium.value = value
}

async function refreshFlow(): Promise<void> {
  forceNext.value = true
  try {
    await unusual.refresh()
  } finally {
    forceNext.value = false
  }
}

function openSymbol(symbol: string): void {
  void router.push({ name: 'options', query: { symbol } })
}
</script>

<template>
  <div class="flow-view">
    <header class="flow-head ticked rise">
      <div class="flow-title">
        <span class="label eyebrow">Market-wide options activity</span>
        <h1>Options flow</h1>
        <p>
          Track what entered since the prior provider window, read SPY/QQQ/IWM/DIA concentration first,
          then use the market queue for the rest. Direction is withheld whenever the evidence is unsigned.
        </p>
      </div>
      <div class="scope-stack">
        <span class="scope-chip label live"><i aria-hidden="true" /> MARKET-WIDE TAPE</span>
        <span class="scope-chip label">UP TO 500 PRINTS</span>
        <span class="scope-chip label">POLL 15S</span>
        <span class="scope-chip label warn">ACTIVITY · NOT DIRECTION</span>
      </div>
    </header>

    <FlowDashboard
      :payload="unusual.data.value"
      :status="statusPayload"
      :loading="unusual.loading.value"
      :error="unusual.error.value"
      :min-premium="minPremium"
      :poll-ms="FLOW_POLL_MS"
      @refresh="void refreshFlow()"
      @threshold="setPremium"
      @open-symbol="openSymbol"
    />
  </div>
</template>

<style scoped>
.flow-view {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  min-width: 0;
  padding-bottom: var(--s5);
}

.flow-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s5);
  padding: var(--s4) var(--s5);
  border: var(--hair) solid var(--border-strong);
}

.flow-title {
  min-width: 0;
}

.eyebrow {
  color: var(--phosphor);
}

h1 {
  margin: 4px 0 0;
  color: var(--text-primary);
  font: 700 clamp(1.55rem, 3vw, 2.4rem) / 1 var(--font-display);
  letter-spacing: -0.04em;
}

.flow-title p {
  max-width: 78ch;
  margin-top: var(--s2);
  color: var(--text-secondary);
  font-size: var(--t-small);
}

.scope-stack {
  display: flex;
  align-content: flex-start;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 6px;
  max-width: 360px;
}

.scope-chip {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 2px 5px;
  color: var(--text-secondary);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-overlay);
}

.scope-chip.live {
  color: var(--status-live);
  border-color: var(--phosphor-dim);
}

.scope-chip.live i {
  width: 5px;
  height: 5px;
  margin-right: 5px;
  background: currentColor;
}

.scope-chip.warn {
  color: var(--status-stale);
}

@media (max-width: 780px) {
  .flow-head {
    flex-direction: column;
    gap: var(--s3);
    padding: var(--s4);
  }

  h1 {
    font-size: var(--t-fig);
  }

  .scope-stack {
    justify-content: flex-start;
    max-width: none;
  }
}
</style>
