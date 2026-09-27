<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type SupplyChainPayload, type SupplyChainThemeSummary } from '@/api'
import { useResource } from '@/composables/useResource'
import ThematicBanner from '@/components/ThematicBanner.vue'
import ValueChainGraph from '@/components/ValueChainGraph.vue'
import BeneficiaryTable from '@/components/BeneficiaryTable.vue'
import EvidenceDrawer from '@/components/EvidenceDrawer.vue'
import AppIcon from '@/components/AppIcon.vue'

export interface SuggestionItem {
  symbol: string
  name: string
  sector?: string
  isCurated: boolean
}

export type LoadingStage =
  'idle' | 'resolving' | 'fetching' | 'mapping' | 'rendering' | 'complete' | 'error'

export interface LoadingStageItem {
  id: 'resolving' | 'fetching' | 'mapping' | 'rendering'
  shortLabel: string
  label: string
  pct: number
}

const STAGES: readonly LoadingStageItem[] = [
  { id: 'resolving', shortLabel: 'Taxonomy', label: 'Resolving symbol & sector taxonomy', pct: 20 },
  {
    id: 'fetching',
    shortLabel: 'Discovery',
    label: 'Discovering multi-tier suppliers & customers',
    pct: 50,
  },
  {
    id: 'mapping',
    shortLabel: 'Elasticity',
    label: 'Computing elasticity & CapEx exposure',
    pct: 75,
  },
  {
    id: 'rendering',
    shortLabel: 'Topology',
    label: 'Compiling topology & rendering graph',
    pct: 90,
  },
] as const

const CURATED_TICKERS: Record<string, { name: string; sector: string }> = {
  NVDA: { name: 'NVIDIA Corporation', sector: 'Semiconductors' },
  AVGO: { name: 'Broadcom Inc.', sector: 'Semiconductors' },
  TSM: { name: 'Taiwan Semiconductor Manufacturing', sector: 'Semiconductors' },
  AMD: { name: 'Advanced Micro Devices', sector: 'Semiconductors' },
  MSFT: { name: 'Microsoft Corporation', sector: 'Software & Cloud' },
  AAPL: { name: 'Apple Inc.', sector: 'Consumer Electronics' },
  AMZN: { name: 'Amazon.com Inc.', sector: 'Cloud & E-Commerce' },
  GOOGL: { name: 'Alphabet Inc.', sector: 'Cloud & AI Services' },
  META: { name: 'Meta Platforms Inc.', sector: 'Social & AI Infrastructure' },
  ARM: { name: 'Arm Holdings plc', sector: 'Semiconductor IP' },
  QCOM: { name: 'Qualcomm Inc.', sector: 'Semiconductors & Wireless' },
  INTC: { name: 'Intel Corporation', sector: 'Semiconductors & Foundry' },
  MU: { name: 'Micron Technology Inc.', sector: 'Memory & Storage' },
  ASML: { name: 'ASML Holding N.V.', sector: 'Semiconductor Equipment' },
  LRCX: { name: 'Lam Research Corp.', sector: 'Semiconductor Equipment' },
  AMAT: { name: 'Applied Materials Inc.', sector: 'Semiconductor Equipment' },
  KLAC: { name: 'KLA Corporation', sector: 'Semiconductor Equipment' },
  MRVL: { name: 'Marvell Technology Inc.', sector: 'Semiconductors' },
  ALAB: { name: 'Astera Labs Inc.', sector: 'PCIe Connectivity' },
  COHR: { name: 'Coherent Corp.', sector: 'Optics & Lasers' },
  LITE: { name: 'Lumentum Holdings', sector: 'Optics & Photonic Components' },
  AAOI: { name: 'Applied Optoelectronics', sector: 'Optical Transceivers' },
  FN: { name: 'Fabrinet', sector: 'Optical Packaging & Manufacturing' },
  VRT: { name: 'Vertiv Holdings Co', sector: 'Liquid Cooling & Power' },
  SMCI: { name: 'Super Micro Computer', sector: 'AI Server Systems' },
  ANET: { name: 'Arista Networks', sector: 'Cloud Networking' },
  CEG: { name: 'Constellation Energy Corp.', sector: 'Nuclear Power' },
  VST: { name: 'Vistra Corp.', sector: 'Power Generation' },
  TLN: { name: 'Talen Energy Corp.', sector: 'Nuclear Power' },
  OKLO: { name: 'Oklo Inc.', sector: 'Advanced Fission' },
  SMR: { name: 'NuScale Power Corp.', sector: 'Small Modular Reactors' },
  CCJ: { name: 'Cameco Corp.', sector: 'Uranium Fuel' },
  LEU: { name: 'Centrus Energy Corp.', sector: 'Enriched Uranium' },
  BWXT: { name: 'BWX Technologies', sector: 'Nuclear Components' },
  ETN: { name: 'Eaton Corporation', sector: 'Electrical Equipment' },
  PWR: { name: 'Quanta Services', sector: 'Grid Infrastructure' },
  GEV: { name: 'GE Vernova Inc.', sector: 'Power Equipment' },
  NEE: { name: 'NextEra Energy', sector: 'Clean Energy & Utilities' },
  UEC: { name: 'Uranium Energy Corp.', sector: 'Uranium Mining' },
  ASTS: { name: 'AST SpaceMobile Inc.', sector: 'Space Direct-to-Cell' },
  RKLB: { name: 'Rocket Lab USA', sector: 'Space Launch & Satellites' },
  LUNR: { name: 'Intuitive Machines', sector: 'Lunar Exploration' },
  RDW: { name: 'Redwire Corporation', sector: 'Space Infrastructure' },
  PL: { name: 'Planet Labs PBC', sector: 'Earth Observation' },
  IRDM: { name: 'Iridium Communications', sector: 'Satellite Communications' },
  GSAT: { name: 'Globalstar Inc.', sector: 'Satellite Services' },
  LMT: { name: 'Lockheed Martin', sector: 'Aerospace & Defense' },
  NOC: { name: 'Northrop Grumman', sector: 'Aerospace & Defense' },
  KTOS: { name: 'Kratos Defense', sector: 'Unmanned Defense Systems' },
  HEI: { name: 'HEICO Corporation', sector: 'Aerospace Components' },
  SNOW: { name: 'Snowflake Inc.', sector: 'Data Cloud' },
  CRWD: { name: 'CrowdStrike Holdings', sector: 'Cybersecurity' },
  PANW: { name: 'Palo Alto Networks', sector: 'Cybersecurity' },
  NET: { name: 'Cloudflare Inc.', sector: 'Edge Cloud & Security' },
  DDOG: { name: 'Datadog Inc.', sector: 'Cloud Observability' },
  NOW: { name: 'ServiceNow Inc.', sector: 'Enterprise AI Workflow' },
  ESTC: { name: 'Elastic N.V.', sector: 'Search & Vector DB' },
  CFLT: { name: 'Confluent Inc.', sector: 'Data Streaming' },
  GTLB: { name: 'GitLab Inc.', sector: 'DevSecOps Platform' },
  WST: { name: 'West Pharmaceutical Services', sector: 'Drug Delivery & Packaging' },
  CTLT: { name: 'Catalent Inc.', sector: 'Biopharma CDMO' },
  STE: { name: 'STERIS plc', sector: 'Sterilization & Surgical' },
  TMO: { name: 'Thermo Fisher Scientific', sector: 'Life Sciences Tools' },
  DHR: { name: 'Danaher Corporation', sector: 'Bioprocess & Diagnostics' },
  VKTX: { name: 'Viking Therapeutics', sector: 'Metabolic & GLP-1' },
  ALT: { name: 'Altimmune Inc.', sector: 'GLP-1 Therapeutics' },
  AMGN: { name: 'Amgen Inc.', sector: 'Biopharmaceuticals' },
  PFE: { name: 'Pfizer Inc.', sector: 'Biopharmaceuticals' },
  AZN: { name: 'AstraZeneca PLC', sector: 'Biopharmaceuticals' },
  SYM: { name: 'Symbotic Inc.', sector: 'Warehouse Automation' },
  ISRG: { name: 'Intuitive Surgical', sector: 'Robotic Surgery' },
  ROK: { name: 'Rockwell Automation', sector: 'Industrial Automation' },
  SERV: { name: 'Serve Robotics', sector: 'Autonomous Delivery' },
  CGNX: { name: 'Cognex Corporation', sector: 'Machine Vision' },
  ZBRA: { name: 'Zebra Technologies', sector: 'Enterprise Asset Tracking' },
  IONQ: { name: 'IonQ Inc.', sector: 'Quantum Computing' },
  RGTI: { name: 'Rigetti Computing', sector: 'Superconducting Quantum' },
  QBTS: { name: 'D-Wave Quantum', sector: 'Quantum Annealing' },
  QUBT: { name: 'Quantum Computing Inc.', sector: 'Photonic Quantum' },
  HON: { name: 'Honeywell International', sector: 'Industrial & Quantum' },
  ARQQ: { name: 'Arqit Quantum', sector: 'Quantum Encryption' },
  TSLA: { name: 'Tesla Inc.', sector: 'Autonomous Vehicles & Robotics' },
  UBER: { name: 'Uber Technologies', sector: 'Mobility & Delivery' },
  T: { name: 'AT&T Inc.', sector: 'Telecommunications' },
}

const route = useRoute()
const router = useRouter()

const currentTheme = ref<string>('ai_datacenter')
const searchSymbol = ref<string>('')
const currentDepth = ref<number>(2)
const currentMode = ref<'dedicated' | 'intertwined'>('dedicated')
const selectedSymbol = ref<string | null>(null)
const drawerOpen = ref<boolean>(false)
const forceNext = ref<boolean>(false)
const lastIngestStatus = ref<string | null>(null)

// Autocomplete State
const showSuggestions = ref<boolean>(false)
const suggestions = ref<SuggestionItem[]>([])
const highlightedIndex = ref<number>(-1)
const searchInputRef = ref<HTMLInputElement | null>(null)

// Progressive Multi-Stage Loading State
const loadingStage = ref<LoadingStage>('idle')
const loadingProgress = ref<number>(0)
const loadingStageLabel = ref<string>('Idle')
const elapsedSeconds = ref<string>('0.0')

// Resilient Error State (decoupled from !payload)
const dismissedError = ref<string | null>(null)
const activeError = computed(() => {
  const err = chainResource.error.value
  if (!err) return null
  if (dismissedError.value === err) return null
  return err
})

let debounceTimer: ReturnType<typeof setTimeout> | null = null
let stageTimer1: ReturnType<typeof setTimeout> | null = null
let stageTimer2: ReturnType<typeof setTimeout> | null = null
let stageTimer3: ReturnType<typeof setTimeout> | null = null
let elapsedInterval: ReturnType<typeof setInterval> | null = null
let completeDismissTimer: ReturnType<typeof setTimeout> | null = null

function clearAllTimers() {
  if (stageTimer1) {
    clearTimeout(stageTimer1)
    stageTimer1 = null
  }
  if (stageTimer2) {
    clearTimeout(stageTimer2)
    stageTimer2 = null
  }
  if (stageTimer3) {
    clearTimeout(stageTimer3)
    stageTimer3 = null
  }
  if (elapsedInterval) {
    clearInterval(elapsedInterval)
    elapsedInterval = null
  }
  if (completeDismissTimer) {
    clearTimeout(completeDismissTimer)
    completeDismissTimer = null
  }
  if (debounceTimer) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
}

function startLoadingStages(targetSymbol?: string) {
  clearAllTimers()
  dismissedError.value = null
  const sym = targetSymbol || searchSymbol.value.trim().toUpperCase()
  loadingStage.value = 'resolving'
  loadingProgress.value = 20
  loadingStageLabel.value = sym
    ? `Resolving ${sym} & sector taxonomy`
    : 'Resolving symbol & sector taxonomy'

  const startTime = Date.now()
  elapsedSeconds.value = '0.0'
  elapsedInterval = setInterval(() => {
    elapsedSeconds.value = ((Date.now() - startTime) / 1000).toFixed(1)
  }, 100)

  stageTimer1 = setTimeout(() => {
    if (loadingStage.value === 'resolving') {
      loadingStage.value = 'fetching'
      loadingProgress.value = 50
      loadingStageLabel.value = 'Discovering multi-tier suppliers & customers'
    }
  }, 120)

  stageTimer2 = setTimeout(() => {
    if (loadingStage.value === 'fetching') {
      loadingStage.value = 'mapping'
      loadingProgress.value = 75
      loadingStageLabel.value = 'Computing elasticity & CapEx exposure'
    }
  }, 280)

  stageTimer3 = setTimeout(() => {
    if (loadingStage.value === 'mapping') {
      loadingStage.value = 'rendering'
      loadingProgress.value = 90
      loadingStageLabel.value = 'Compiling topology & rendering graph'
    }
  }, 450)
}

function completeLoadingStages(targetSymbol?: string) {
  clearAllTimers()
  const sym = targetSymbol || searchSymbol.value.trim().toUpperCase()
  loadingStage.value = 'complete'
  loadingProgress.value = 100
  loadingStageLabel.value = sym ? `Computed ${sym} value chain` : 'Computed value chain'
  lastIngestStatus.value = loadingStageLabel.value

  completeDismissTimer = setTimeout(() => {
    if (loadingStage.value === 'complete') {
      loadingStage.value = 'idle'
    }
    lastIngestStatus.value = null
  }, 4000)
}

function failLoadingStages(errorMsg: string) {
  clearAllTimers()
  loadingStage.value = 'error'
  loadingProgress.value = 100
  loadingStageLabel.value = `Error: ${errorMsg}`
}

function stageIndex(stage: LoadingStage): number {
  switch (stage) {
    case 'resolving':
      return 0
    case 'fetching':
      return 1
    case 'mapping':
      return 2
    case 'rendering':
      return 3
    case 'complete':
      return 4
    default:
      return -1
  }
}

function isStageCompleted(id: 'resolving' | 'fetching' | 'mapping' | 'rendering'): boolean {
  if (loadingStage.value === 'complete') return true
  const currentIdx = stageIndex(loadingStage.value)
  const targetIdx = stageIndex(id)
  return currentIdx > targetIdx
}

function isStagePending(id: 'resolving' | 'fetching' | 'mapping' | 'rendering'): boolean {
  if (loadingStage.value === 'complete') return false
  const currentIdx = stageIndex(loadingStage.value)
  const targetIdx = stageIndex(id)
  return currentIdx < targetIdx
}

const stageBadgeText = computed(() => {
  switch (loadingStage.value) {
    case 'resolving':
      return 'STAGE 1/4: RESOLVING'
    case 'fetching':
      return 'STAGE 2/4: DISCOVERING'
    case 'mapping':
      return 'STAGE 3/4: ELASTICITY'
    case 'rendering':
      return 'STAGE 4/4: RENDERING'
    case 'complete':
      return 'COMPLETE'
    case 'error':
      return 'FAILED'
    default:
      return 'READY'
  }
})

// Sync with route query
watch(
  () => route.query,
  (query) => {
    let shouldRefresh = false
    if (typeof query.theme === 'string' && query.theme && query.theme !== currentTheme.value) {
      currentTheme.value = query.theme
      shouldRefresh = true
    }
    if (
      typeof query.mode === 'string' &&
      (query.mode === 'dedicated' || query.mode === 'intertwined') &&
      query.mode !== currentMode.value
    ) {
      currentMode.value = query.mode
      shouldRefresh = true
    }
    if (typeof query.symbol === 'string' && query.symbol.trim()) {
      const sym = query.symbol.trim().toUpperCase()
      if (sym !== searchSymbol.value) {
        searchSymbol.value = sym
        selectedSymbol.value = sym
        shouldRefresh = true
      }
    } else if (searchSymbol.value && !query.symbol) {
      searchSymbol.value = ''
      selectedSymbol.value = null
      shouldRefresh = true
    }
    if (shouldRefresh) {
      startLoadingStages(searchSymbol.value)
      void chainResource.refresh().then(() => {
        if (chainResource.error.value) {
          failLoadingStages(chainResource.error.value)
        } else {
          completeLoadingStages(searchSymbol.value)
        }
      })
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
    const sym = searchSymbol.value ? searchSymbol.value.trim().toUpperCase() : undefined
    return api.supplyChain({
      theme: sym && currentMode.value === 'dedicated' ? undefined : currentTheme.value,
      symbol: sym,
      depth: currentDepth.value,
      mode: currentMode.value,
      force,
    })
  },
  { intervalMs: 180_000 },
)

const payload = computed(() => chainResource.data.value)
const nodes = computed(() => payload.value?.nodes ?? [])
const edges = computed(() => payload.value?.edges ?? [])
const summary = computed(() => payload.value?.thematic_summary ?? null)
const bridges = computed(() => payload.value?.thematic_bridges ?? [])

// Auto-sync currentTheme if backend auto-routes to symbol native theme
watch(
  () => payload.value?.query?.theme,
  (newTheme) => {
    if (newTheme && newTheme !== currentTheme.value) {
      currentTheme.value = newTheme
    }
  },
)

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

function computeCuratedMatches(query: string): SuggestionItem[] {
  const upper = query.toUpperCase()
  const results: SuggestionItem[] = []
  for (const [sym, info] of Object.entries(CURATED_TICKERS)) {
    if (sym.startsWith(upper) || sym.includes(upper) || info.name.toUpperCase().includes(upper)) {
      results.push({
        symbol: sym,
        name: info.name,
        sector: info.sector,
        isCurated: true,
      })
    }
  }
  results.sort((a, b) => {
    const aStart = a.symbol.startsWith(upper) ? 0 : 1
    const bStart = b.symbol.startsWith(upper) ? 0 : 1
    if (aStart !== bStart) return aStart - bStart
    return a.symbol.localeCompare(b.symbol)
  })
  return results
}

function onSearchInput() {
  const query = searchSymbol.value.trim()
  if (!query) {
    suggestions.value = []
    showSuggestions.value = false
    highlightedIndex.value = -1
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
    return
  }

  showSuggestions.value = true
  highlightedIndex.value = -1

  const curated = computeCuratedMatches(query).slice(0, 8)
  suggestions.value = curated

  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(async () => {
    try {
      const hits = await api.search(query, 10)
      const searchItems: SuggestionItem[] = (hits || []).map((h) => {
        const sym = h.symbol.toUpperCase()
        const curatedInfo = CURATED_TICKERS[sym]
        return {
          symbol: sym,
          name: h.name || curatedInfo?.name || sym,
          sector: h.category || curatedInfo?.sector || 'US Equity',
          isCurated: Boolean(curatedInfo),
        }
      })

      const seen = new Set<string>()
      const merged: SuggestionItem[] = []
      for (const item of [...curated, ...searchItems]) {
        if (!seen.has(item.symbol)) {
          seen.add(item.symbol)
          merged.push(item)
        }
      }
      suggestions.value = merged.slice(0, 8)
    } catch {
      suggestions.value = curated
    }
  }, 150)
}

function onSearchKeydown(e: KeyboardEvent) {
  if (!showSuggestions.value || suggestions.value.length === 0) {
    if (e.key === 'ArrowDown' && searchSymbol.value.trim()) {
      onSearchInput()
    }
    return
  }

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (highlightedIndex.value < suggestions.value.length - 1) {
      highlightedIndex.value++
    } else {
      highlightedIndex.value = 0
    }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (highlightedIndex.value > 0) {
      highlightedIndex.value--
    } else {
      highlightedIndex.value = suggestions.value.length - 1
    }
  } else if (e.key === 'Enter') {
    if (highlightedIndex.value >= 0 && highlightedIndex.value < suggestions.value.length) {
      e.preventDefault()
      selectSuggestion(suggestions.value[highlightedIndex.value])
    }
  } else if (e.key === 'Escape') {
    e.preventDefault()
    showSuggestions.value = false
    highlightedIndex.value = -1
  }
}

function onSearchFocus() {
  if (searchSymbol.value.trim()) {
    onSearchInput()
  }
}

function onSearchBlur() {
  setTimeout(() => {
    showSuggestions.value = false
    highlightedIndex.value = -1
  }, 200)
}

function selectSuggestion(item: SuggestionItem) {
  searchSymbol.value = item.symbol
  showSuggestions.value = false
  highlightedIndex.value = -1
  focusStock(item.symbol)
}

function onSelectTheme(themeId: string) {
  currentTheme.value = themeId
  searchSymbol.value = ''
  selectedSymbol.value = null
  drawerOpen.value = false
  showSuggestions.value = false
  highlightedIndex.value = -1
  dismissedError.value = null
  startLoadingStages()
  void router.replace({ query: { theme: themeId } })
  void chainResource.refresh().then(() => {
    if (chainResource.error.value) {
      failLoadingStages(chainResource.error.value)
    } else {
      completeLoadingStages()
    }
  })
}

function onSelectTicker(symbol: string) {
  selectedSymbol.value = symbol
  drawerOpen.value = true
}

function onInspectEvidence(symbol: string) {
  selectedSymbol.value = symbol
  drawerOpen.value = true
}

function clearSearch() {
  searchSymbol.value = ''
  selectedSymbol.value = null
  drawerOpen.value = false
  showSuggestions.value = false
  highlightedIndex.value = -1
  dismissedError.value = null
  const newQuery = { ...route.query }
  delete newQuery.symbol
  startLoadingStages()
  void router.replace({ query: newQuery })
  void chainResource.refresh().then(() => {
    if (chainResource.error.value) {
      failLoadingStages(chainResource.error.value)
    } else {
      completeLoadingStages()
    }
  })
}

function focusStock(sym: string) {
  if (!sym || !sym.trim()) return
  const clean = sym.trim().toUpperCase()
  searchSymbol.value = clean
  selectedSymbol.value = clean
  currentMode.value = 'dedicated'
  drawerOpen.value = false
  showSuggestions.value = false
  highlightedIndex.value = -1
  dismissedError.value = null
  startLoadingStages(clean)
  void router.replace({ query: { symbol: clean, mode: 'dedicated' } })
  void chainResource.refresh().then(() => {
    if (chainResource.error.value) {
      failLoadingStages(chainResource.error.value)
    } else {
      completeLoadingStages(clean)
    }
  })
}

function triggerSearch() {
  if (!searchSymbol.value.trim()) return
  focusStock(searchSymbol.value)
}

function triggerRefresh() {
  forceNext.value = true
  dismissedError.value = null
  startLoadingStages(searchSymbol.value)
  void chainResource.refresh().then(() => {
    if (chainResource.error.value) {
      failLoadingStages(chainResource.error.value)
    } else {
      completeLoadingStages(searchSymbol.value)
    }
  })
}

function retryFetch() {
  dismissedError.value = null
  triggerRefresh()
}

function dismissError() {
  dismissedError.value = chainResource.error.value
}

function toggleDepth() {
  currentDepth.value = currentDepth.value === 1 ? 2 : 1
  startLoadingStages(searchSymbol.value)
  void chainResource.refresh().then(() => {
    if (chainResource.error.value) {
      failLoadingStages(chainResource.error.value)
    } else {
      completeLoadingStages(searchSymbol.value)
    }
  })
}

function setMode(mode: 'dedicated' | 'intertwined') {
  currentMode.value = mode
  startLoadingStages(searchSymbol.value)
  void router.replace({ query: { ...route.query, mode } })
  void chainResource.refresh().then(() => {
    if (chainResource.error.value) {
      failLoadingStages(chainResource.error.value)
    } else {
      completeLoadingStages(searchSymbol.value)
    }
  })
}

function selectBridgeTheme(themeId: string) {
  currentTheme.value = themeId
  currentMode.value = 'intertwined'
  startLoadingStages(searchSymbol.value)
  void router.replace({ query: { ...route.query, theme: themeId, mode: 'intertwined' } })
  void chainResource.refresh().then(() => {
    if (chainResource.error.value) {
      failLoadingStages(chainResource.error.value)
    } else {
      completeLoadingStages(searchSymbol.value)
    }
  })
}

function focusQuickTicker(sym: string) {
  focusStock(sym)
}

onBeforeUnmount(() => {
  clearAllTimers()
})
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
        <!-- View Mode Switcher -->
        <div class="mode-toggle-group">
          <button
            type="button"
            class="mode-toggle-btn"
            :class="{ active: currentMode === 'dedicated' }"
            title="Dedicated Company Multi-Tier Chain"
            @click="setMode('dedicated')"
          >
            Dedicated Chain
          </button>
          <button
            type="button"
            class="mode-toggle-btn"
            :class="{ active: currentMode === 'intertwined' }"
            title="Intertwined Macro Thematic Frontier"
            @click="setMode('intertwined')"
          >
            Thematic Intertwine
          </button>
        </div>

        <!-- Symbol Search with Autocomplete Dropdown -->
        <div class="search-container">
          <form class="search-form" @submit.prevent="triggerSearch">
            <div class="search-input-wrap">
              <input
                ref="searchInputRef"
                v-model="searchSymbol"
                type="text"
                role="combobox"
                aria-autocomplete="list"
                :aria-expanded="showSuggestions && suggestions.length > 0"
                aria-controls="suggestions-list"
                :aria-activedescendant="
                  highlightedIndex >= 0 ? `suggestion-opt-${highlightedIndex}` : undefined
                "
                aria-label="Search equity symbol"
                placeholder="Type Any Stock (AAPL, AMD, COHR, UBER)..."
                class="sym-search-input"
                autocomplete="off"
                spellcheck="false"
                @input="onSearchInput"
                @keydown="onSearchKeydown"
                @focus="onSearchFocus"
                @blur="onSearchBlur"
              />
              <button
                v-if="searchSymbol"
                type="button"
                class="clear-btn"
                aria-label="Clear symbol search"
                title="Clear symbol search"
                @click="clearSearch"
              >
                ×
              </button>
            </div>
            <button type="submit" class="search-btn">Compute Chain</button>
            <button
              v-if="searchSymbol"
              type="button"
              class="reset-btn"
              title="Reset to all themes"
              @click="clearSearch"
            >
              Reset
            </button>
          </form>

          <!-- Autocomplete Suggestions Dropdown -->
          <ul
            v-if="showSuggestions && suggestions.length > 0"
            id="suggestions-list"
            class="suggestions-dropdown"
            role="listbox"
            aria-label="Symbol suggestions"
          >
            <li
              v-for="(item, idx) in suggestions"
              :id="`suggestion-opt-${idx}`"
              :key="item.symbol"
              role="option"
              :aria-selected="highlightedIndex === idx"
              class="suggestion-item"
              :class="{ highlighted: highlightedIndex === idx }"
              @mouseenter="highlightedIndex = idx"
              @mousedown.prevent="selectSuggestion(item)"
            >
              <div class="sugg-left">
                <span class="sugg-symbol">{{ item.symbol }}</span>
                <span class="sugg-name">{{ item.name }}</span>
                <span v-if="item.sector" class="sugg-sector">{{ item.sector }}</span>
              </div>
              <div class="sugg-right">
                <span
                  class="sugg-badge"
                  :class="item.isCurated ? 'badge-curated' : 'badge-discovery'"
                >
                  {{ item.isCurated ? 'Curated Ecosystem Leader' : 'Algorithmic Discovery' }}
                </span>
              </div>
            </li>
          </ul>
        </div>

        <!-- Depth Toggle -->
        <button
          type="button"
          class="depth-btn"
          title="Toggle Multi-Tier vs Direct Supplier Hops"
          @click="toggleDepth"
        >
          Depth: Tier {{ currentDepth }}
        </button>

        <!-- Live Refresh / Recompute -->
        <button
          type="button"
          class="refresh-btn"
          :disabled="chainResource.loading.value"
          title="Recompute value chain metrics and sensitivity"
          @click="triggerRefresh"
        >
          <span v-if="chainResource.loading.value">⟳ Recomputing...</span>
          <span v-else>⟳ Recompute</span>
        </button>
      </div>
    </header>

    <!-- Multi-Stage Progressive Loading Stepper Banner -->
    <div
      v-if="loadingStage !== 'idle'"
      class="loading-stepper-panel"
      data-test="loading-stepper"
      role="status"
      aria-live="polite"
    >
      <div class="stepper-header">
        <div class="stepper-stage-info">
          <span class="stepper-stage-badge" :class="`stage-${loadingStage}`">
            <span v-if="loadingStage === 'complete'" class="badge-icon">✓</span>
            <span v-else-if="loadingStage === 'error'" class="badge-icon">✕</span>
            <span v-else class="stage-spinner" aria-hidden="true" />
            <span class="badge-text">{{ stageBadgeText }}</span>
          </span>
          <span class="stepper-label" data-test="stepper-label">{{ loadingStageLabel }}</span>
        </div>
        <div class="stepper-telemetry">
          <span v-if="elapsedSeconds" class="telemetry-elapsed">{{ elapsedSeconds }}s elapsed</span>
          <span class="telemetry-pct">{{ loadingProgress }}%</span>
        </div>
      </div>

      <!-- Stepper Track / Progress Bar -->
      <div class="stepper-track-wrap">
        <div
          class="stepper-progress-bar"
          :class="`bar-${loadingStage}`"
          :style="{ width: `${loadingProgress}%` }"
        />
      </div>

      <!-- 4 Stages Readout -->
      <div class="stepper-steps-grid">
        <div
          v-for="(s, idx) in STAGES"
          :key="s.id"
          class="step-item"
          :class="{
            active: loadingStage === s.id,
            completed: isStageCompleted(s.id),
            pending: isStagePending(s.id),
          }"
        >
          <span class="step-num">{{ idx + 1 }}</span>
          <span class="step-title">{{ s.shortLabel }}</span>
        </div>
      </div>
    </div>

    <!-- Resilient Dismissible Error Banner (decoupled from !payload) -->
    <div v-if="activeError" class="error-banner" data-test="error-banner" role="alert">
      <div class="error-msg-wrap">
        <span class="error-icon" aria-hidden="true">⚠</span>
        <div class="error-text-block">
          <span class="error-title">Resolution & Fetch Error</span>
          <span class="error-detail">{{ activeError }}</span>
        </div>
      </div>
      <div class="error-actions">
        <button
          type="button"
          class="error-retry-btn"
          data-test="retry-btn"
          title="Retry value chain computation"
          @click="retryFetch"
        >
          ⟳ Retry
        </button>
        <button
          type="button"
          class="error-dismiss-btn"
          data-test="dismiss-btn"
          title="Dismiss error notification"
          @click="dismissError"
        >
          ✕ Dismiss
        </button>
      </div>
    </div>

    <!-- Thematic Frontier Bridges Strip -->
    <div v-if="bridges.length" class="thematic-bridges-strip">
      <span class="bridge-label">INTERTWINED THEMATIC FRONTIERS:</span>
      <div class="bridge-chips">
        <button
          v-for="b in bridges"
          :key="b.id"
          type="button"
          class="bridge-chip"
          :title="`Intertwine into ${b.theme_name}`"
          @click="selectBridgeTheme(b.id)"
        >
          <span class="bridge-name">⚡ {{ b.theme_name }}</span>
          <span v-if="b.role" class="bridge-role">({{ b.role }})</span>
        </button>
      </div>
    </div>

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
        <span class="section-hint"
          >Click any supplier or customer node to trace connections and inspect citations</span
        >
      </div>
      <ValueChainGraph
        :nodes="nodes"
        :edges="edges"
        :selected-symbol="selectedSymbol"
        @select-node="onSelectTicker"
        @focus-node="focusStock"
      />
    </section>

    <!-- Ranked Beneficiary Matrix & Growth Forecast -->
    <section class="section-matrix">
      <div class="section-header">
        <span class="section-badge">BENEFICIARY ELASTICITY & REVENUE PROPAGATION</span>
        <span class="section-hint"
          >Ranked by CapEx flow-through sensitivity, operating leverage, and options flow
          momentum</span
        >
      </div>
      <BeneficiaryTable
        :nodes="nodes"
        :selected-symbol="selectedSymbol"
        @select-ticker="onSelectTicker"
        @inspect-evidence="onInspectEvidence"
        @focus-ticker="focusStock"
      />
    </section>

    <!-- Slide-Out Evidence & Citations Drawer -->
    <EvidenceDrawer
      :node="selectedNode"
      :open="drawerOpen"
      :edges="payload?.edges || []"
      :focal-node="payload?.focal_entity || null"
      @close="drawerOpen = false"
      @focus-chain="focusStock"
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
  background: var(--glass-surface, var(--panel));
  border: 1px solid var(--glass-border-subtle, var(--rule));
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
  flex-wrap: wrap;
}

.mode-toggle-group {
  display: flex;
  background: var(--void);
  border: 1px solid var(--rule);
  padding: 2px;
  gap: 2px;
}

.mode-toggle-btn {
  background: transparent;
  border: none;
  color: var(--ink-dim);
  font-size: 0.72rem;
  padding: 0.25rem 0.6rem;
  cursor: pointer;
  font-family: var(--font-mono, monospace);
  transition: all 0.15s ease;
}

.mode-toggle-btn:hover {
  color: var(--ink);
}

.mode-toggle-btn.active {
  background: var(--phosphor-wash);
  color: var(--phosphor);
  font-weight: 700;
  border: 1px solid var(--phosphor-dim);
}

.search-container {
  position: relative;
  display: inline-flex;
}

.search-form {
  display: flex;
  align-items: center;
}

.search-input-wrap {
  position: relative;
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
  width: 250px;
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

.clear-btn {
  background: var(--void);
  border: 1px solid var(--rule);
  border-left: none;
  border-right: none;
  color: var(--ink-dim);
  padding: 0.35rem 0.5rem;
  font-size: 0.85rem;
  cursor: pointer;
  line-height: 1;
}

.clear-btn:hover {
  color: var(--ink);
}

.reset-btn {
  background: var(--void-lift);
  border: 1px solid var(--rule);
  border-left: none;
  color: var(--ink-dim);
  padding: 0.35rem 0.65rem;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.reset-btn:hover {
  background: var(--panel-raise);
  color: var(--ink);
  border-color: var(--rule-hi);
}

.suggestions-dropdown {
  position: absolute;
  top: calc(100% + 2px);
  left: 0;
  width: 440px;
  max-width: 90vw;
  background: var(--panel);
  border: 1px solid var(--rule-hi);
  list-style: none;
  margin: 0;
  padding: 0;
  z-index: 50;
  max-height: 320px;
  overflow-y: auto;
}

.suggestion-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.45rem 0.65rem;
  border-bottom: 1px solid var(--rule);
  cursor: pointer;
  transition: background 0.12s ease;
}

.suggestion-item:last-child {
  border-bottom: none;
}

.suggestion-item:hover,
.suggestion-item.highlighted {
  background: var(--panel-raise);
}

.suggestion-item:focus-visible {
  outline: 2px solid var(--accent, var(--phosphor));
  outline-offset: -1px;
}

.sugg-left {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  flex: 1;
}

.sugg-symbol {
  font-family: var(--font-mono, monospace);
  font-weight: 700;
  color: var(--phosphor);
  font-size: 0.8rem;
}

.sugg-name {
  color: var(--ink);
  font-size: 0.72rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sugg-sector {
  color: var(--ink-faint);
  font-size: 0.65rem;
  white-space: nowrap;
}

.sugg-right {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.sugg-badge {
  font-family: var(--font-mono, monospace);
  font-size: var(--t-nano);
  padding: 0.1rem 0.35rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.sugg-badge.badge-curated {
  background: var(--phosphor-wash);
  color: var(--phosphor);
  border: 1px solid var(--phosphor-dim);
}

.sugg-badge.badge-discovery {
  background: var(--void-lift);
  color: var(--ink-dim);
  border: 1px solid var(--rule);
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

/* Progressive Loading Stepper */
.loading-stepper-panel {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  padding: 0.65rem 1rem;
  background: var(--glass-surface, var(--panel));
  border: 1px solid var(--glass-border-subtle, var(--rule));
}

.stepper-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.stepper-stage-info {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.stepper-stage-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.65rem;
  font-weight: 700;
  padding: 0.15rem 0.45rem;
  border: 1px solid var(--rule);
  background: var(--void-lift);
}

.stepper-stage-badge.stage-resolving {
  color: var(--call-hi);
  border-color: var(--call);
  background: var(--call-wash);
}

.stepper-stage-badge.stage-fetching {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.stepper-stage-badge.stage-mapping {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}

.stepper-stage-badge.stage-rendering {
  color: var(--call-hi);
  border-color: var(--call);
  background: var(--call-wash);
}

.stepper-stage-badge.stage-complete {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.stepper-stage-badge.stage-error {
  color: var(--short);
  border-color: var(--short);
  background: var(--short-wash);
}

.stage-spinner {
  display: inline-block;
  width: 8px;
  height: 8px;
  border: 1.5px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.badge-icon {
  font-weight: 900;
  font-size: 0.7rem;
}

.badge-text {
  letter-spacing: 0.04em;
}

.stepper-label {
  font-family: var(--font-mono, monospace);
  font-size: 0.72rem;
  color: var(--ink);
}

.stepper-telemetry {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.68rem;
  color: var(--ink-dim);
}

.stepper-track-wrap {
  width: 100%;
  height: 3px;
  background: var(--void);
  border: 1px solid var(--rule);
  overflow: hidden;
}

.stepper-progress-bar {
  height: 100%;
  background: var(--phosphor);
  transition: width 0.25s ease-out;
}

.stepper-progress-bar.bar-error {
  background: var(--short);
}

.stepper-steps-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.5rem;
  margin-top: 0.15rem;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.65rem;
  color: var(--ink-dim);
  padding: 0.2rem 0.45rem;
  background: var(--void-lift);
  border: 1px solid var(--rule);
}

.step-item.completed {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

.step-item.active {
  color: var(--ink);
  font-weight: 700;
  border-color: var(--rule-hi);
  background: var(--panel-raise);
}

.step-num {
  width: 14px;
  height: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--void);
  font-size: var(--t-nano);
  font-weight: 700;
}

.step-item.completed .step-num {
  background: var(--phosphor-wash);
  color: var(--phosphor);
}

.step-item.active .step-num {
  background: var(--phosphor);
  color: var(--void);
}

/* Resilient Error Banner */
.error-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.65rem 1rem;
  background: var(--short-wash);
  border: 1px solid var(--short);
  color: var(--short);
  font-size: 0.75rem;
}

.error-msg-wrap {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.error-icon {
  font-size: 1.1rem;
  line-height: 1;
}

.error-text-block {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.error-title {
  font-family: var(--font-mono, monospace);
  font-weight: 700;
  font-size: 0.72rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.error-detail {
  color: var(--ink);
  font-size: 0.72rem;
}

.error-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.error-retry-btn {
  background: var(--short);
  color: var(--void);
  border: none;
  padding: 0.25rem 0.65rem;
  font-size: 0.7rem;
  font-family: var(--font-mono, monospace);
  font-weight: 700;
  cursor: pointer;
  transition: opacity 0.15s ease;
}

.error-retry-btn:hover {
  opacity: 0.85;
}

.error-retry-btn:focus-visible,
.error-dismiss-btn:focus-visible {
  outline: 2px solid var(--accent, var(--phosphor));
  outline-offset: 1px;
}

.error-dismiss-btn {
  background: transparent;
  border: 1px solid var(--short);
  color: var(--short);
  padding: 0.25rem 0.65rem;
  font-size: 0.7rem;
  font-family: var(--font-mono, monospace);
  cursor: pointer;
  transition: all 0.15s ease;
}

.error-dismiss-btn:hover {
  background: var(--short-wash);
  color: var(--ink);
}

.thematic-bridges-strip {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  flex-wrap: wrap;
  padding: 0.45rem 0.85rem;
  background: color-mix(in srgb, var(--cat-1) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--cat-1) 30%, var(--rule));
  font-size: 0.68rem;
}

.bridge-label {
  color: var(--cat-1);
  font-weight: 700;
  letter-spacing: 0.05em;
  font-family: var(--font-mono, monospace);
}

.bridge-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.bridge-chip {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.65rem;
  padding: 0.2rem 0.5rem;
  background: var(--panel);
  border: 1px solid color-mix(in srgb, var(--cat-1) 40%, var(--rule));
  color: var(--ink);
  cursor: pointer;
  transition: all 0.15s ease;
}

.bridge-chip:hover {
  background: color-mix(in srgb, var(--cat-1) 25%, transparent);
  border-color: var(--cat-1);
}

.bridge-name {
  font-weight: 600;
}

.bridge-role {
  color: var(--ink-faint);
  font-size: var(--t-nano);
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
</style>
