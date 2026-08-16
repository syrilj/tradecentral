<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type StatusPayload } from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import FlowDashboard from '@/components/FlowDashboard.vue'
import FlowSuggestionDrawer from '@/components/FlowSuggestionDrawer.vue'

const FLOW_LIMIT = 80
const BASE_FLOW_FLOOR = 25_000
const FLOW_POLL_MS = 15_000

const router = useRouter()
const route = useRoute()
const sharedStatus = inject<Resource<StatusPayload> | null>('status', null)
const statusPayload = computed(() => sharedStatus?.data.value ?? null)
const minPremium = ref(BASE_FLOW_FLOOR)
const forceNext = ref(false)
const selectedSetup = ref(String(route.query.setup || '').trim().toUpperCase())

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
  selectedSetup.value = symbol
  void router.replace({
    name: 'flow',
    query: { ...route.query, setup: symbol },
  })
}

function closeSetup(): void {
  selectedSetup.value = ''
  const query = { ...route.query }
  delete query.setup
  void router.replace({ name: 'flow', query })
}

watch(() => route.query.setup, (value) => {
  selectedSetup.value = String(value || '').trim().toUpperCase()
})
</script>

<template>
  <div class="flow-view">
    <header class="flow-head ticked rise">
      <div class="flow-title">
        <span class="label eyebrow"><i aria-hidden="true" class="live-dot" /> LIVE OPTIONS FLOW</span>
        <h1>Market-Wide Order Flow</h1>
        <p>
          Real-time institutional order activity across liquid names.
          Sweeps, blocks, and unusual prints. Signed buy/sell when the feed marks it.
        </p>
      </div>
      <div class="scope-stack">
        <span class="scope-chip label live"><i aria-hidden="true" /> LIVE TAPE</span>
        <span class="scope-chip label">SWEEPS &amp; BLOCKS</span>
        <span class="scope-chip label">GOLDEN SWEEPS</span>
        <span class="scope-chip label">WATCHLIST ALERTS</span>
        <span class="scope-chip label">15s POLL</span>
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

    <FlowSuggestionDrawer
      v-if="selectedSetup"
      :symbol="selectedSetup"
      @close="closeSetup"
    />
  </div>
</template>

<style scoped>
.flow-view {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  min-width: 0;
  padding-bottom: var(--s6);
}

.flow-head {
  position: relative;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s6);
  padding: var(--s4) var(--s5);
  border: var(--hair) solid var(--rule);
  border-left: 2px solid var(--phosphor-dim);
}

.flow-title {
  min-width: 0;
}

.eyebrow {
  color: var(--phosphor);
}

h1 {
  margin: var(--s2) 0 0;
  color: var(--ink);
  font: 700 var(--t-display) / 1.15 var(--font-display);
  letter-spacing: var(--track-tight);
}

.flow-title p {
  max-width: 76ch;
  margin-top: var(--s3);
  color: var(--text-secondary);
  font-size: var(--t-body);
  line-height: 1.55;
}

.scope-stack {
  display: flex;
  align-content: flex-start;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: var(--s2);
  max-width: 390px;
  padding-bottom: var(--s1);
}

.scope-chip {
  display: inline-flex;
  align-items: center;
  min-height: var(--density-control-h);
  padding: var(--s1) var(--s2);
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule);
}

.scope-chip.live {
  color: var(--status-live);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.scope-chip.live i {
  display: inline-block;
  width: 5px;
  height: 5px;
  margin-right: 5px;
  border-radius: 50%;
  background: currentColor;
}

.live-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--phosphor);
  margin-right: 6px;
  vertical-align: middle;
  animation: dot-pulse 2s ease-in-out infinite;
}
@keyframes dot-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.scope-chip.warn {
  color: var(--status-stale);
}

@media (max-width: 780px) {
  .flow-head {
    flex-direction: column;
    gap: var(--s3);
    min-height: 0;
    padding: var(--s4);
  }

  h1 {
    font-size: var(--t-display);
  }

  .scope-stack {
    justify-content: flex-start;
    max-width: none;
  }
}
</style>
