<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type SupplyChainPayload, type SupplyChainThemeSummary } from '@/api'
import { useResource } from '@/composables/useResource'
import ThematicBanner from '@/components/ThematicBanner.vue'
import ValueChainGraph from '@/components/ValueChainGraph.vue'
import BeneficiaryTable from '@/components/BeneficiaryTable.vue'
import EvidenceDrawer from '@/components/EvidenceDrawer.vue'
import AppIcon from '@/components/AppIcon.vue'

const route = useRoute()
const router = useRouter()

const currentTheme = ref<string>('ai_datacenter')
const searchSymbol = ref<string>('')
const currentDepth = ref<number>(2)
const selectedSymbol = ref<string | null>(null)
const drawerOpen = ref<boolean>(false)
const forceNext = ref<boolean>(false)
const lastIngestStatus = ref<string | null>(null)

// Sync with route query
watch(
  () => route.query,
  (query) => {
    if (typeof query.theme === 'string' && query.theme) {
      currentTheme.value = query.theme
    }
    if (typeof query.symbol === 'string' && query.symbol) {
      searchSymbol.value = query.symbol.toUpperCase()
      selectedSymbol.value = query.symbol.toUpperCase()
    }
  },
  { immediate: true },
)

const themesResource = useResource<{ themes: SupplyChainThemeSummary[] }>(
  () => api.supplyChainThemes(),
  { intervalMs: 300_000 },
)

const themes = computed(() => themesResource.data.value?.themes ?? [])

const chainResource = useResource<SupplyChainPayload>(
  () => {
    const force = forceNext.value
    forceNext.value = false
    return api.supplyChain({
      theme: currentTheme.value,
      symbol: searchSymbol.value || undefined,
      depth: currentDepth.value,
      force,
    })
  },
  { intervalMs: 180_000 },
)

const payload = computed(() => chainResource.data.value)
const nodes = computed(() => payload.value?.nodes ?? [])
const edges = computed(() => payload.value?.edges ?? [])
const summary = computed(() => payload.value?.thematic_summary ?? null)

const selectedNode = computed(() => {
  if (!selectedSymbol.value) return null
  return nodes.value.find((n) => n.symbol === selectedSymbol.value) ?? null
})

const quickBeneficiaries = [
  'ASTS',
  'RKLB',
  'LUNR',
  'RDW',
  'LMT',
  'NOC',
  'KTOS',
  'HEI',
  'PL',
  'IRDM',
  'GSAT',
  'SATL',
  'BKSY',
  'AAOI',
  'LITE',
  'COHR',
  'MU',
  'VRT',
  'CEG',
  'VST',
  'TLN',
  'OKLO',
  'SMR',
  'CCJ',
  'LEU',
  'BWXT',
  'ETN',
  'PWR',
  'GEV',
  'NEE',
  'UEC',
  'ALAB',
  'FN',
  'MRVL',
  'ANET',
  'SMCI',
  'AVGO',
  'TSM',
  'LRCX',
  'CAMT',
  'FORM',
  'ONTO',
  'ACLS',
  'ENTG',
  'TER',
  'COHU',
  'SNOW',
  'CRWD',
  'PANW',
  'NET',
  'DDOG',
  'NOW',
  'ESTC',
  'CFLT',
  'GTLB',
  'WST',
  'CTLT',
  'STE',
  'TMO',
  'DHR',
  'VKTX',
  'ALT',
  'AMGN',
  'PFE',
  'AZN',
  'SYM',
  'ISRG',
  'ROK',
  'SERV',
  'CGNX',
  'ZBRA',
  'IONQ',
  'RGTI',
  'QBTS',
  'QUBT',
  'HON',
  'ARQQ',
]

function onSelectTheme(themeId: string) {
  currentTheme.value = themeId
  searchSymbol.value = ''
  selectedSymbol.value = null
  drawerOpen.value = false
  void router.replace({ query: { theme: themeId } })
  void chainResource.refresh()
}

function onSelectTicker(symbol: string) {
  selectedSymbol.value = symbol
  drawerOpen.value = true
}

function onInspectEvidence(symbol: string) {
  selectedSymbol.value = symbol
  drawerOpen.value = true
}

function triggerSearch() {
  if (!searchSymbol.value.trim()) return
  const sym = searchSymbol.value.trim().toUpperCase()
  selectedSymbol.value = sym
  drawerOpen.value = true
  lastIngestStatus.value = `Ingesting ${sym}...`
  void router.replace({ query: { ...route.query, symbol: sym } })
  void chainResource.refresh().then(() => {
    lastIngestStatus.value = `Loaded ${sym}`
    setTimeout(() => {
      lastIngestStatus.value = null
    }, 4000)
  })
}

function triggerRefresh() {
  forceNext.value = true
  lastIngestStatus.value = 'Re-scanning live SEC filings & transcripts...'
  void chainResource.refresh().then(() => {
    lastIngestStatus.value = 'Live Ingest Complete'
    setTimeout(() => {
      lastIngestStatus.value = null
    }, 4000)
  })
}

function toggleDepth() {
  currentDepth.value = currentDepth.value === 1 ? 2 : 1
  void chainResource.refresh()
}

function focusQuickTicker(sym: string) {
  searchSymbol.value = sym
  triggerSearch()
}
</script>

<template>
  <div class="chain-view" data-test="chain-view">
    <!-- Header Control Bar -->
    <header class="chain-ctrl-bar">
      <div class="ctrl-left">
        <div class="brand-title">
          <AppIcon name="chain" :size="18" />
          <span class="title-text">SUPPLY CHAIN & VALUE ECOSYSTEMS</span>
        </div>
        <div class="node-count-badge">
          {{ nodes.length }} Active Entities · {{ edges.length }} Supply Links
        </div>
      </div>

      <div class="ctrl-right">
        <!-- Search -->
        <form class="search-form" @submit.prevent="triggerSearch">
          <input
            v-model="searchSymbol"
            type="text"
            placeholder="Focus Ticker (e.g. NVDA, AAOI, MU, SMR)..."
            class="sym-search-input"
          />
          <button type="submit" class="search-btn">Focus</button>
        </form>

        <!-- Depth Toggle -->
        <button
          type="button"
          class="depth-btn"
          @click="toggleDepth"
          title="Toggle Multi-Tier vs Direct Supplier Hops"
        >
          Depth: Tier {{ currentDepth }}
        </button>

        <!-- Live Refresh -->
        <button
          type="button"
          class="refresh-btn"
          :disabled="chainResource.loading.value"
          @click="triggerRefresh"
          title="Live Ingest & Rescore Transcripts"
        >
          <span v-if="chainResource.loading.value">⟳ Ingesting...</span>
          <span v-else>⟳ Live Ingest</span>
        </button>
      </div>
    </header>

    <!-- Quick Catalyst / Focus Chips -->
    <div class="quick-focus-strip">
      <span class="strip-label">FOCUS CANDIDATES:</span>
      <div class="quick-chips">
        <button
          v-for="sym in quickBeneficiaries"
          :key="sym"
          type="button"
          class="quick-chip"
          :class="{ active: selectedSymbol === sym }"
          @click="focusQuickTicker(sym)"
        >
          {{ sym }}
        </button>
      </div>
      <span v-if="lastIngestStatus" class="live-status-pill">
        {{ lastIngestStatus }}
      </span>
    </div>

    <div v-if="chainResource.error.value && !payload" class="error-banner">
      {{ chainResource.error.value }}
    </div>

    <!-- Thematic Narrative & Catalyst Strip -->
    <ThematicBanner
      :summary="summary"
      :themes="themes"
      :current-theme-id="currentTheme"
      @select-theme="onSelectTheme"
      @select-ticker="onSelectTicker"
    />

    <!-- Value Chain Interactive Canvas -->
    <section class="section-canvas">
      <div class="section-header">
        <span class="section-badge">VALUE CHAIN TOPOLOGY</span>
        <span class="section-hint">Click any supplier or customer node to trace connections and inspect citations</span>
      </div>
      <ValueChainGraph
        :nodes="nodes"
        :edges="edges"
        :selected-symbol="selectedSymbol"
        @select-node="onSelectTicker"
      />
    </section>

    <!-- Ranked Beneficiary Matrix & Growth Forecast -->
    <section class="section-matrix">
      <div class="section-header">
        <span class="section-badge">BENEFICIARY ELASTICITY & REVENUE PROPAGATION</span>
        <span class="section-hint">Ranked by CapEx flow-through sensitivity, operating leverage, and options flow momentum</span>
      </div>
      <BeneficiaryTable
        :nodes="nodes"
        :selected-symbol="selectedSymbol"
        @select-ticker="onSelectTicker"
        @inspect-evidence="onInspectEvidence"
      />
    </section>

    <!-- Slide-Out Evidence & Citations Drawer -->
    <EvidenceDrawer
      :node="selectedNode"
      :open="drawerOpen"
      @close="drawerOpen = false"
    />
  </div>
</template>

<style scoped>
.chain-view {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  padding: 1.25rem;
  background: var(--void);
  min-height: 100vh;
  position: relative;
  font-family: var(--font-sans, system-ui, sans-serif);
}

.chain-ctrl-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  background: var(--panel);
  border: 1px solid var(--rule);
  padding: 0.65rem 1rem;
}

.ctrl-left {
  display: flex;
  align-items: center;
  gap: 0.85rem;
}

.brand-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--ink);
  font-weight: 700;
  font-size: 0.88rem;
  letter-spacing: 0.04em;
}

.title-text {
  font-family: var(--font-mono, monospace);
}

.node-count-badge {
  font-size: 0.68rem;
  font-family: var(--font-mono, monospace);
  padding: 0.15rem 0.45rem;
  background: var(--void-lift);
  color: var(--ink-soft);
  border: 1px solid var(--rule);
}

.ctrl-right {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.search-form {
  display: flex;
  align-items: center;
}

.sym-search-input {
  background: var(--void);
  border: 1px solid var(--rule);
  border-right: none;
  color: var(--ink);
  padding: 0.35rem 0.65rem;
  font-size: 0.75rem;
  font-family: var(--font-mono, monospace);
  width: 230px;
}

.sym-search-input:focus {
  outline: none;
  border-color: var(--phosphor);
}

.search-btn {
  background: var(--panel-raise);
  border: 1px solid var(--rule);
  color: var(--ink);
  padding: 0.35rem 0.65rem;
  font-size: 0.75rem;
  cursor: pointer;
}

.search-btn:hover {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
  color: var(--phosphor);
}

.depth-btn,
.refresh-btn {
  background: var(--void-lift);
  border: 1px solid var(--rule);
  color: var(--ink-dim);
  font-size: 0.75rem;
  padding: 0.35rem 0.65rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.depth-btn:hover,
.refresh-btn:hover {
  background: var(--panel-raise);
  color: var(--ink);
  border-color: var(--rule-hi);
}

.quick-focus-strip {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  flex-wrap: wrap;
  padding: 0.45rem 0.85rem;
  background: var(--void-lift);
  border: 1px solid var(--rule);
  font-size: 0.68rem;
}

.strip-label {
  color: var(--ink-faint);
  font-weight: 600;
  letter-spacing: 0.05em;
}

.quick-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}

.quick-chip {
  font-family: var(--font-mono, monospace);
  font-size: 0.65rem;
  padding: 0.15rem 0.4rem;
  background: var(--panel);
  border: 1px solid var(--rule);
  color: var(--ink-dim);
  cursor: pointer;
  transition: all 0.12s ease;
}

.quick-chip:hover {
  background: var(--panel-raise);
  color: var(--ink);
  border-color: var(--rule-hi);
}

.quick-chip.active {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
  color: var(--phosphor);
  font-weight: 700;
}

.live-status-pill {
  margin-left: auto;
  font-family: var(--font-mono, monospace);
  font-size: 0.65rem;
  color: var(--phosphor);
  background: var(--phosphor-wash);
  padding: 0.15rem 0.45rem;
  border: 1px solid var(--phosphor-dim);
}

.section-canvas,
.section-matrix {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-badge {
  font-family: var(--font-mono, monospace);
  font-size: 0.68rem;
  letter-spacing: 0.06em;
  color: var(--phosphor);
  font-weight: 600;
}

.section-hint {
  font-size: 0.7rem;
  color: var(--ink-faint);
}

.error-banner {
  background: var(--short-wash);
  border: 1px solid var(--short);
  color: var(--short);
  padding: 0.75rem 1rem;
  font-size: 0.8rem;
}
</style>
