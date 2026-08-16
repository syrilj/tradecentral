<script setup lang="ts">
import { computed, inject, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  WINDOWS,
  type SearchHit,
  type Trajectory,
  type ComparePayload,
  type TrajWindow,
  type StatusPayload,
  type FinancialsPayload,
  type StatementTable,
  type CompanyProfilePayload,
  type InsidersIntelligencePayload,
  type GovernmentPayload,
  type OwnershipPayload,
  type SentimentPayload,
} from '@/api'
import type { Resource } from '@/composables/useResource'
import { debounce, useResource } from '@/composables/useResource'
import { num, pct, pctFrac, signedPct, compact, usd, tone, shortDate, DASH } from '@/format'
import {
  formatBigUsd,
  formatPerShare,
  formatStatementCell,
  formatPeriodHeader,
  formatSourceLabel,
  getDerivedRatio,
  getGrowthTone,
} from '@/financialsDisplay'
import { presentSecFilings } from '@/insiderDisplay'
import { sparkline } from '@/charts'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import TrajectoryChart from '@/components/TrajectoryChart.vue'
import LoadingState from '@/components/LoadingState.vue'
import { loadWatchlist, toggleWatchlistSymbol, watchlistHas } from '@/watchlist'
import { tickerCompanyName, tickerIdentity } from '@/tickerIdentity'
import {
  filterSortInstitutions,
  formatHolderChange,
  formatInstitutionsKpi,
  formatInstitutionsPanelMeta,
  holderChangeTone,
  holderPctBarWidth,
  institutionPageCount,
  paginateHolders,
  reportedInstitutionCount,
  tableMaxPctOut,
  type InstitutionSortField,
} from '@/ownershipDisplay'

const status = inject<Resource<StatusPayload>>('status')
const route = useRoute()
const router = useRouter()

// -- Symbols & Search State ----------------------------------------------------
const q = ref('')
const hits = ref<SearchHit[]>([])
const searching = ref(false)

const symbol = ref<string>(((route.query.symbol as string) || 'ASTS').toUpperCase())
const book = ref(loadWatchlist())
const onBook = computed(() => watchlistHas(book.value, symbol.value))

function toggleBook(): void {
  book.value = toggleWatchlistSymbol(book.value, symbol.value).symbols
}

// Active Tab navigation
export type MarketTab =
  | 'overview'
  | 'financials'
  | 'forecast'
  | 'insiders'
  | 'institutions'
  | 'government'
  | 'compensation'
  | 'ownership'
  | 'news'
  | 'compare'

const activeTab = ref<MarketTab>(((route.query.tab as MarketTab) || 'overview'))

// Watch route queries
watch(
  () => route.query.tab,
  (t) => {
    if (t && typeof t === 'string') {
      activeTab.value = t as MarketTab
    }
  },
  { immediate: true },
)

function setTab(tab: MarketTab): void {
  activeTab.value = tab
  void router.replace({
    query: { ...route.query, symbol: symbol.value, tab },
  })
}

// Chart controls
const win = ref<TrajWindow>('1y')
const mode = ref<'price' | 'growth'>('price')
const chartStyle = ref<'candles' | 'line'>('candles')

// Financials controls
const finPeriod = ref<'quarterly' | 'annual'>('quarterly')
const finStatement = ref<'income' | 'balance' | 'cash' | 'breakdown' | 'ratios'>('income')
const finViewMode = ref<'table' | 'charts'>('table')

// Insiders controls
const insiderTypeFilter = ref<'all' | 'buy' | 'sell'>('all')
const insiderSearchQuery = ref('')

// Core trajectory & compare resources
const traj = ref<Trajectory | null>(null)
const trajErr = ref<string | null>(null)
const trajBusy = ref(false)

const basket = ref<string[]>([])
const cmp = ref<ComparePayload | null>(null)
const cmpErr = ref<string | null>(null)

// Rich Stock Intelligence Resources
const financialsRes = useResource<FinancialsPayload>(
  () => api.financials(symbol.value, finPeriod.value),
  { intervalMs: 0 },
)

const profileRes = useResource<CompanyProfilePayload>(
  () => api.companyProfile(symbol.value),
  { intervalMs: 0 },
)

const insidersRes = useResource<InsidersIntelligencePayload>(
  () => api.insiders(symbol.value),
  { intervalMs: 0 },
)

const governmentRes = useResource<GovernmentPayload>(
  () => api.government(symbol.value),
  { intervalMs: 0 },
)

const ownershipRes = useResource<OwnershipPayload>(
  () => api.ownership(symbol.value),
  { intervalMs: 0 },
)

const sentimentRes = useResource<SentimentPayload>(
  () => api.sentiment(symbol.value),
  { intervalMs: 0 },
)

const isGlobalLoading = computed(
  () => trajBusy.value || profileRes.loading.value,
)

function reloadAllSymbolData(): void {
  traj.value = null
  trajBusy.value = true
  trajErr.value = null
  void loadTrajectory()
  void financialsRes.refresh({ clear: true })
  void profileRes.refresh({ clear: true })
  void insidersRes.refresh({ clear: true })
  void governmentRes.refresh({ clear: true })
  void ownershipRes.refresh({ clear: true })
  void sentimentRes.refresh({ clear: true })
}

// Watch symbol and route changes
watch(
  () => route.query.symbol,
  (newSym) => {
    if (newSym && typeof newSym === 'string') {
      const s = cleanTicker(newSym)
      if (s && s !== symbol.value) {
        symbol.value = s
        q.value = s
        const rest = basket.value.filter((b) => b !== s && b !== 'SPY')
        basket.value = [...new Set(s === 'SPY' ? ['SPY', 'QQQ', ...rest] : [s, 'SPY', ...rest])].slice(0, 8)
        void loadCompare()
        reloadAllSymbolData()
      }
    }
  },
  { immediate: true },
)

watch(finPeriod, () => void financialsRes.refresh({ clear: true }))

function cleanTicker(term: string): string {
  return term.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, '').slice(0, 10)
}

const runSearch = debounce(async (term: string) => {
  searching.value = true
  try {
    const cleaned = cleanTicker(term)
    const raw = await api.search(cleaned, 18)
    let list = raw.filter((h) => (h.kind ?? 'symbol') === 'symbol')
    if (cleaned && !list.some((h) => h.symbol === cleaned)) {
      list = [
        {
          symbol: cleaned,
          kind: 'symbol',
          tier: 'wide',
          n_bars: 0,
          first_date: '',
          last_date: '',
        } as SearchHit,
        ...list,
      ]
    }
    hits.value = list
  } catch {
    hits.value = []
  } finally {
    searching.value = false
  }
}, 140)

watch(q, (v) => runSearch(v))

async function loadTrajectory(): Promise<void> {
  const reqSym = symbol.value
  trajBusy.value = true
  trajErr.value = null
  try {
    const res = await api.trajectory(reqSym, win.value)
    if (reqSym === symbol.value) {
      traj.value = res
    }
  } catch (e) {
    if (reqSym === symbol.value) {
      trajErr.value = e instanceof Error ? e.message : String(e)
      traj.value = null
    }
  } finally {
    if (reqSym === symbol.value) {
      trajBusy.value = false
    }
  }
}

async function loadCompare(): Promise<void> {
  if (basket.value.length < 2) {
    cmp.value = null
    cmpErr.value = null
    return
  }
  try {
    cmp.value = await api.compare(basket.value, win.value)
    cmpErr.value = null
  } catch (e) {
    cmpErr.value = e instanceof Error ? e.message : String(e)
    cmp.value = null
  }
}

function select(sym: string): void {
  const s = cleanTicker(sym)
  if (!s) return
  const changed = s !== symbol.value
  symbol.value = s
  q.value = s
  const rest = basket.value.filter((b) => b !== s && b !== 'SPY')
  const next = s === 'SPY' ? ['SPY', 'QQQ', ...rest] : [s, 'SPY', ...rest]
  basket.value = [...new Set(next)].slice(0, 8)
  void loadCompare()
  void router.replace({ query: { ...route.query, symbol: s, tab: activeTab.value } })
  if (changed) reloadAllSymbolData()
  else void loadTrajectory()
}

function onSearchKey(e: KeyboardEvent): void {
  if (e.key === 'Enter') {
    e.preventDefault()
    const typed = cleanTicker(q.value)
    if (typed) select(typed)
  }
  if (e.key === 'ArrowDown' && hits.value.length) {
    e.preventDefault()
    const idx = Math.max(0, hits.value.findIndex((h) => h.symbol === symbol.value))
    const next = hits.value[Math.min(hits.value.length - 1, idx + 1)]
    if (next) select(next.symbol)
  }
  if (e.key === 'ArrowUp' && hits.value.length) {
    e.preventDefault()
    const idx = Math.max(0, hits.value.findIndex((h) => h.symbol === symbol.value))
    const prev = hits.value[Math.max(0, idx - 1)]
    if (prev) select(prev.symbol)
  }
}

function toggleBasket(sym: string): void {
  const clean = cleanTicker(sym)
  if (!clean) return
  const i = basket.value.indexOf(clean)
  if (i >= 0) basket.value.splice(i, 1)
  else if (basket.value.length < 8) basket.value.push(clean)
  void loadCompare()
}

watch([symbol, win], () => void loadTrajectory())
watch(win, () => void loadCompare())

let trajTimer: number | undefined

onMounted(() => {
  reloadAllSymbolData()
  if (symbol.value && symbol.value !== 'SPY') {
    basket.value = [symbol.value, 'SPY']
  } else {
    basket.value = ['SPY', 'QQQ']
  }
  void loadCompare()
  runSearch(symbol.value || '')
  trajTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return
    void loadTrajectory()
    void loadCompare()
  }, 30_000)
})

onUnmounted(() => {
  if (trajTimer !== undefined) clearInterval(trajTimer)
})

const s = computed(() => traj.value?.stats)
const profile = computed(() => profileRes.data.value)
const companyName = computed(() => {
  const fromProfile = profile.value?.about?.name
  const fromHit = hits.value.find((h) => h.symbol === symbol.value)?.name
  return tickerCompanyName(symbol.value, fromProfile || fromHit)
})
const identity = computed(() => tickerIdentity(symbol.value, companyName.value))
const searchOpen = computed(() => Boolean(q.value.trim()) && (hits.value.length > 0 || searching.value))
const finData = computed(() => financialsRes.data.value)
const insData = computed(() => insidersRes.data.value)
const govData = computed(() => governmentRes.data.value)
const ownData = computed(() => ownershipRes.data.value)

function observedAgeDays(value: string | null | undefined): number | null {
  if (!value) return null
  const stamp = Date.parse(value.length <= 10 ? `${value}T00:00:00Z` : value)
  if (!Number.isFinite(stamp)) return null
  return Math.max(0, Math.floor((Date.now() - stamp) / 86_400_000))
}

const dataAudit = computed(() => {
  if (!traj.value) return null
  const lastDate = traj.value.last_asof || traj.value.last_date
  const firstDate = traj.value.first_date
  const nBars = traj.value.n_bars
  const source = traj.value.last_source || traj.value.source
  const advUsd = s.value?.adv_20_usd
  const ageDays = observedAgeDays(lastDate)
  const isLive = traj.value.quality === 'live'
  const isFresh = isLive || (ageDays != null && ageDays <= 3)
  return {
    lastDate,
    firstDate,
    barDate: traj.value.last_date,
    nBars,
    source,
    advUsd,
    isFresh,
    isLive,
    ageDays,
  }
})

const signalBranch = computed(() => {
  const sym = symbol.value?.toUpperCase()
  if (!sym) return null

  const dSignals = (status?.data?.value?.directional_signals ?? []) as any[]
  const peadCandidates = (status?.data?.value?.pead_candidates ?? []) as any[]

  const sig = dSignals.find((s) => s.symbol?.toUpperCase() === sym)
  const pead = peadCandidates.find((p) => p.symbol?.toUpperCase() === sym)

  if (sig) {
    const prob = sig.probability
    return {
      type: 'Directional Signal',
      side: (sig.side || 'LONG').toUpperCase(),
      prob: typeof prob === 'number' && Number.isFinite(prob) ? prob : null,
      state: sig.state || 'WATCH',
      horizon: sig.horizon || '5d',
      momentum: sig.momentum ?? 0,
      model: sig.model || 'XS3 LightGBM',
    }
  }

  if (pead) {
    const prob = pead.model?.probability
    return {
      type: 'PEAD Gap Setup',
      side: (pead.side || 'LONG').toUpperCase(),
      prob: typeof prob === 'number' && Number.isFinite(prob) ? prob : null,
      state: pead.model?.state || 'FLAG',
      horizon: `${pead.model?.horizon_days ?? 20}d`,
      model: pead.model?.id || 'PEAD Catalyst',
    }
  }

  return null
})

// Forecast Analyst Revisions Filters
const forecastActionFilter = ref<'all' | 'upgrade' | 'initiate' | 'maintain' | 'downgrade'>('all')
const forecastSearchQuery = ref('')

function matchRevisionFilter(action: string | undefined, filter: string): boolean {
  if (filter === 'all') return true
  const act = (action || '').toLowerCase().trim()
  if (filter === 'upgrade') {
    return act.includes('upgrade') || act.includes('outperform') || act.includes('buy') || act === 'up'
  }
  if (filter === 'initiate') {
    return act.includes('initiat') || act.includes('coverage') || act === 'init'
  }
  if (filter === 'maintain') {
    return act.includes('maintain') || act.includes('reiterat') || act.includes('hold') || act.includes('neutral') || act === 'main' || act === 'reit'
  }
  if (filter === 'downgrade') {
    return act.includes('downgrade') || act.includes('underperform') || act.includes('sell') || act === 'down'
  }
  return true
}

const revisionsCounts = computed(() => {
  const list = profile.value?.forecast?.upgrades_downgrades || []
  return {
    all: list.length,
    upgrade: list.filter((r) => matchRevisionFilter(r.action, 'upgrade')).length,
    initiate: list.filter((r) => matchRevisionFilter(r.action, 'initiate')).length,
    maintain: list.filter((r) => matchRevisionFilter(r.action, 'maintain')).length,
    downgrade: list.filter((r) => matchRevisionFilter(r.action, 'downgrade')).length,
  }
})

const filteredRevisions = computed(() => {
  const list = profile.value?.forecast?.upgrades_downgrades || []
  return list.filter((rev) => {
    if (!matchRevisionFilter(rev.action, forecastActionFilter.value)) return false

    if (forecastSearchQuery.value) {
      const qLower = forecastSearchQuery.value.toLowerCase().trim()
      const matchFirm = (rev.firm || '').toLowerCase().includes(qLower)
      const matchGrade = (rev.current || '').toLowerCase().includes(qLower) || (rev.to_grade || '').toLowerCase().includes(qLower) || (rev.previous || '').toLowerCase().includes(qLower)
      const matchAct = (rev.action || '').toLowerCase().includes(qLower)
      if (!matchFirm && !matchGrade && !matchAct) return false
    }
    return true
  })
})

// Institutions & Ownership State
const institutionSearchQuery = ref('')
const institutionSortField = ref<InstitutionSortField>('shares')
const institutionSortAsc = ref(false)

function setInstitutionSort(field: InstitutionSortField): void {
  if (institutionSortField.value === field) {
    // Same column: toggle direction
    institutionSortAsc.value = !institutionSortAsc.value
  } else {
    // New column: default to descending
    institutionSortField.value = field
    institutionSortAsc.value = false
  }
}
const institutionPage = ref(1)
const institutionPageSize = ref<number | 'all'>('all')

const filteredInstitutions = computed(() =>
  filterSortInstitutions(
    ownData.value?.top_institutions || [],
    institutionSearchQuery.value,
    institutionSortField.value,
    institutionSortAsc.value,
  ),
)

const totalInstitutionPages = computed(() =>
  institutionPageCount(filteredInstitutions.value.length, institutionPageSize.value),
)

const paginatedInstitutions = computed(() =>
  paginateHolders(filteredInstitutions.value, institutionPage.value, institutionPageSize.value),
)

const institutionsReported = computed(() => reportedInstitutionCount(ownData.value))

const institutionsPanelMeta = computed(() =>
  formatInstitutionsPanelMeta({
    filtered: filteredInstitutions.value.length,
    listed: ownData.value?.top_institutions?.length || 0,
    reported: institutionsReported.value,
    searching: Boolean(institutionSearchQuery.value.trim()),
  }),
)

const ownershipInstitutionsMeta = computed(() =>
  formatInstitutionsPanelMeta({
    filtered: ownData.value?.top_institutions?.length || 0,
    listed: ownData.value?.top_institutions?.length || 0,
    reported: institutionsReported.value,
    searching: false,
  }),
)

const institutionPctScale = computed(() => tableMaxPctOut(filteredInstitutions.value))
const ownershipInstitutionPctScale = computed(() => tableMaxPctOut(ownData.value?.top_institutions || []))
const fundPctScale = computed(() => tableMaxPctOut(ownData.value?.top_funds || []))

const institutionKpis = computed(() => {
  const list = ownData.value?.top_institutions || []
  const totalVal = list.reduce((acc, cur) => acc + (cur.value || 0), 0)
  const top5SumPct = list.slice(0, 5).reduce((acc, cur) => acc + (cur.pct_out || 0), 0)
  return {
    totalValueUsd: totalVal,
    top5Pct: Number(top5SumPct.toFixed(1)),
    countLabel: formatInstitutionsKpi(list.length, institutionsReported.value),
    // Use live data from breakdown; never fall back to a hardcoded value
    reportedInstPct: ownData.value?.breakdown?.institutional_pct ?? null,
  }
})

// Maximum absolute quarterly net volume — used to scale insider bar heights relative to dataset
const insMaxQuarterlyVol = computed(() => {
  const bars = insData.value?.quarterly_net
  if (!bars?.length) return 1
  return Math.max(1, ...bars.map((q: { net_volume: number }) => Math.abs(q.net_volume)))
})

// SEC Filings from Sentiment Payload
const secRows = computed(() => presentSecFilings(sentimentRes.data.value?.symbol_filings))

// Filtered Insiders Transactions
const filteredTransactions = computed(() => {
  const list = insData.value?.transactions || []
  return list.filter((tx) => {
    if (insiderTypeFilter.value === 'buy' && tx.transaction_type !== 'Purchase') return false
    if (insiderTypeFilter.value === 'sell' && tx.transaction_type !== 'Sale') return false
    if (insiderSearchQuery.value) {
      const qLower = insiderSearchQuery.value.toLowerCase()
      return (
        tx.insider_name.toLowerCase().includes(qLower) ||
        tx.relationship.toLowerCase().includes(qLower)
      )
    }
    return true
  })
})

// Compare calculations
const cmpSparks = computed(() => {
  const out: Record<string, string> = {}
  if (!cmp.value) return out
  for (const [sym, rows] of Object.entries(cmp.value.series)) {
    if (rows && rows.length > 0) {
      out[sym] = sparkline(rows.map((r) => r.cum), 120, 22, 2).d
    }
  }
  return out
})

const cmpSyms = computed(() => (cmp.value ? Object.keys(cmp.value.series) : []))

// corrStyle: positive correlation → warm (short/red) signals co-movement risk;
// negative correlation → cool (long/green) signals hedging/diversification benefit.
// This is intentional trading-desk convention: correlated = risk (red), anti-corr = hedge (green).
function corrStyle(r: number): Record<string, string> {
  if (!Number.isFinite(r)) return {}
  const p = Math.min(1, Math.abs(r)) * 55
  const hue = r >= 0 ? 'short' : 'long'
  return { background: `color-mix(in srgb, var(--${hue}) ${p.toFixed(1)}%, transparent)` }
}

const factorRows = computed(() => {
  const f = traj.value?.factors ?? {}
  return [
    {
      k: 'rev1',
      label: '1D Reversal',
      desc: 'Short-term 1-day return reversal (-1 × ret1)',
      v: f.rev1,
      formatted: f.rev1 == null ? DASH : signedPct(f.rev1 * 100, 2),
      barPct: Math.min(100, Math.abs(Number(f.rev1 ?? 0)) * 500),
      toneClass: tone(f.rev1),
    },
    {
      k: 'rev5',
      label: '5D Reversal',
      desc: 'Weekly 5-day return reversal (-1 × ret5)',
      v: f.rev5,
      formatted: f.rev5 == null ? DASH : signedPct(f.rev5 * 100, 2),
      barPct: Math.min(100, Math.abs(Number(f.rev5 ?? 0)) * 200),
      toneClass: tone(f.rev5),
    },
    {
      k: 'mom12_1',
      label: '12-1M Momentum',
      desc: '12-month momentum (excl. recent month)',
      v: f.mom12_1,
      formatted: f.mom12_1 == null ? DASH : signedPct(f.mom12_1 * 100, 2),
      barPct: Math.min(100, Math.abs(Number(f.mom12_1 ?? 0)) * 100),
      toneClass: tone(f.mom12_1),
    },
    {
      k: 'lowvol',
      label: 'Low Volatility',
      desc: '20-day return volatility suppression',
      v: f.lowvol,
      formatted: f.lowvol == null ? DASH : num(f.lowvol, 4),
      barPct: Math.min(100, Math.abs(Number(f.lowvol ?? 0)) * 2000),
      toneClass: tone(f.lowvol),
    },
    {
      k: 'liq',
      label: 'Liquidity Index',
      desc: '20-day log dollar volume scale',
      v: f.liq,
      formatted: f.liq == null ? DASH : `${num(f.liq, 2)} log$`,
      sub: f.adv20_usd ? compact(f.adv20_usd) : undefined,
      barPct: Math.min(100, Math.max(0, (Number(f.liq ?? 0) / 12) * 100)),
      toneClass: 'pos',
    },
  ]
})

// Financial Statement Visual Chart Series Computations
const finChartData = computed(() => {
  if (!finData.value || !finData.value.periods?.length) return null
  const periodsDesc = finData.value.periods
  const periodsAsc = [...periodsDesc].reverse()
  const ascIndices = periodsAsc.map((p) => periodsDesc.indexOf(p))
  const formattedPeriods = periodsAsc.map((p) => formatPeriodHeader(p, finPeriod.value === 'quarterly'))

  const getRowValues = (table?: StatementTable, pattern?: RegExp) => {
    if (!table?.rows?.length) return periodsAsc.map(() => null)
    const row = pattern ? table.rows.find((r) => pattern.test(r.key || r.label) && !r.is_header) : table.rows[0]
    if (!row?.values) return periodsAsc.map(() => null)
    return ascIndices.map((idx) => (row.values[idx] != null && Number.isFinite(row.values[idx]) ? row.values[idx] : null))
  }

  const revVals = getRowValues(finData.value.income_statement, /revenue|sales/i)
  const gpVals = getRowValues(finData.value.income_statement, /gross[ _]?profit/i)
  const opVals = getRowValues(finData.value.income_statement, /operating[ _]?(income|profit)/i)
  const niVals = getRowValues(finData.value.income_statement, /net[ _]?income/i)

  const assetVals = getRowValues(finData.value.balance_sheet, /total[ _]?assets/i)
  const liabVals = getRowValues(finData.value.balance_sheet, /total[ _]?(liab|liabilities)/i)
  const eqVals = getRowValues(finData.value.balance_sheet, /equity|stockholder/i)

  const ocfVals = getRowValues(finData.value.cash_flow, /operating[ _]?cash|cash.*operating/i)
  const fcfVals = getRowValues(finData.value.cash_flow, /free[ _]?cash/i)
  const capexVals = getRowValues(finData.value.cash_flow, /capital[ _]?expenditure|capex/i)

  const findMax = (arrays: (number | null)[][]) => {
    let max = 0
    for (const arr of arrays) {
      for (const v of arr) {
        if (v != null && Number.isFinite(v) && Math.abs(v) > max) {
          max = Math.abs(v)
        }
      }
    }
    return max || 1
  }

  return {
    periods: periodsAsc,
    formattedPeriods,
    income: {
      revenue: revVals,
      grossProfit: gpVals,
      operatingIncome: opVals,
      netIncome: niVals,
      maxVal: findMax([revVals, gpVals, opVals, niVals]),
    },
    balance: {
      assets: assetVals,
      liabilities: liabVals,
      equity: eqVals,
      maxVal: findMax([assetVals, liabVals, eqVals]),
    },
    cashFlow: {
      operatingCashFlow: ocfVals,
      freeCashFlow: fcfVals,
      capex: capexVals,
      maxVal: findMax([ocfVals, fcfVals, capexVals]),
    },
  }
})
</script>

<template>
  <div class="market-cockpit">
    <!-- ── Header & Search Bar ────────────────────────────────────────────── -->
    <header class="ticker-masthead">
      <div class="masthead-main">
        <div class="ticker-brand">
          <div class="ticker-badge">
            <span class="ticker-badge-sym fig">{{ symbol }}</span>
          </div>
          <div class="ticker-info">
            <div class="ticker-title-row">
              <h1 class="company-name lab">{{ identity.label }}</h1>
              <span v-if="profile?.about?.sector" class="ticker-meta-dot">·</span>
              <span v-if="profile?.about?.sector" class="ticker-sec-tag label">{{ profile.about.sector }}</span>
              <span v-if="profile?.about?.industry" class="ticker-ind-tag label dim">/ {{ profile.about.industry }}</span>
            </div>
            <div class="ticker-sub-row">
              <span class="ticker-exchange label">USD · Real Time Mark</span>
              <span v-if="profile?.about?.market_cap" class="ticker-mcap label dim">
                MCAP: <strong class="fig">{{ formatBigUsd(profile.about.market_cap) }}</strong>
              </span>
              <span v-if="profile?.about?.employees" class="ticker-emp label dim">
                EMP: <strong class="fig">{{ profile.about.employees.toLocaleString() }}</strong>
              </span>
            </div>
          </div>
        </div>

        <div class="ticker-price-block">
          <div v-if="trajBusy && !traj" class="price-hero-loading">
            <span class="loading-pulse-badge label">SYNCING {{ symbol }}…</span>
          </div>
          <div v-else class="price-hero">
            <strong class="last-price fig" :class="tone(s?.last_price)">
              {{ usd(s?.last_price) }}
            </strong>
            <div class="price-changes">
              <span class="chg-val fig" :class="tone(s?.chg_1d_pct)">
                {{ signedPct(s?.chg_1d_pct) }}
              </span>
              <span class="chg-sub label dim">1D</span>
            </div>
          </div>
          <div class="ticker-actions">
            <button type="button" class="btn-action pin-btn label" :class="{ on: onBook }" @click="toggleBook">
              {{ onBook ? 'PINNED' : 'PIN TO BOOK' }}
            </button>
            <RouterLink :to="{ name: 'options', query: { symbol } }" class="btn-action label">
              OPTIONS DRIFT
            </RouterLink>
            <RouterLink :to="{ name: 'flow', query: { setup: symbol } }" class="btn-action label">
              FLOW TAPE
            </RouterLink>
            <RouterLink :to="{ name: 'suggest', query: { symbol } }" class="btn-action label">
              SETUPS
            </RouterLink>
            <button
              type="button"
              class="btn-action label"
              :class="{ on: activeTab === 'insiders' }"
              @click="setTab('insiders')"
            >
              INSIDERS
            </button>
          </div>
        </div>

        <div class="ticker-search-strip">
          <div class="search-input-wrap">
            <span class="search-glyph">⌕</span>
            <input
              v-model="q"
              class="search-input"
              type="text"
              placeholder="Ticker"
              spellcheck="false"
              autocomplete="off"
              aria-label="Symbol search"
              @keydown="onSearchKey"
            />
            <span v-if="searching || isGlobalLoading" class="search-busy label">···</span>
          </div>
          <div v-if="searchOpen" class="search-dropdown-menu">
            <button
              v-for="h in hits.slice(0, 8)"
              :key="h.symbol"
              type="button"
              class="search-drop-item"
              :class="{ on: h.symbol === symbol }"
              @click="select(h.symbol)"
            >
              <strong class="drop-sym fig">{{ h.symbol }}</strong>
              <span class="drop-tier label dim">
                {{ tickerCompanyName(h.symbol, h.name) || (h.n_bars ? `${h.n_bars} bars` : 'live / uncached') }}
              </span>
            </button>
          </div>
        </div>
      </div>

      <!-- Real-Time Syncing Loading Indicator Strip -->
      <div v-if="isGlobalLoading" class="ticker-sync-strip label">
        <span class="sync-dot fresh" />
        <span class="sync-text">SYNCHRONIZING REAL-TIME QUOTES & INTELLIGENCE FOR <strong class="fig">{{ symbol }}</strong>…</span>
      </div>

      <!-- ── Zero-Emoji Institutional Primary Tab Navigation ──────────────── -->
      <nav class="cockpit-tabs-nav" role="tablist" aria-label="Stock Analysis Tabs">
        <button
          v-for="tabItem in [
            { id: 'overview', index: '01', label: 'Overview' },
            { id: 'financials', index: '02', label: 'Financials' },
            { id: 'forecast', index: '03', label: 'Forecast' },
            { id: 'insiders', index: '04', label: 'Insiders' },
            { id: 'institutions', index: '05', label: 'Institutions' },
            { id: 'government', index: '06', label: 'Government' },
            { id: 'compensation', index: '07', label: 'Compensation' },
            { id: 'ownership', index: '08', label: 'Ownership' },
            { id: 'news', index: '09', label: 'News & Filings' },
            { id: 'compare', index: '10', label: 'Compare' },
          ] as const"
          :key="tabItem.id"
          type="button"
          class="cockpit-tab-btn label"
          :class="{ active: activeTab === tabItem.id }"
          role="tab"
          :aria-selected="activeTab === tabItem.id"
          @click="setTab(tabItem.id)"
        >
          <span class="tab-index fig">{{ tabItem.index }}</span>
          <span class="tab-label">{{ tabItem.label }}</span>
        </button>
      </nav>
    </header>

    <!-- ===================================================================== -->
    <!-- TAB 1: OVERVIEW                                                       -->
    <!-- ===================================================================== -->
    <section v-if="activeTab === 'overview'" class="tab-content overview-layout">
      <!-- Trajectory Chart & Stats Strip -->
      <Panel :label="`${identity.label} trajectory`" index="01" :meta="traj ? `${traj.n_bars} bars · ${formatSourceLabel(traj.source)}` : ''" class="overview-chart-panel">
        <template #action>
          <div class="switches">
            <button type="button" class="mkt-refresh-btn label" :disabled="trajBusy" @click="loadTrajectory">
              <span class="refresh-icon" :class="{ spinning: trajBusy }">↻</span>
              {{ trajBusy ? 'REFRESHING…' : 'REFRESH MARK' }}
            </button>
            <div class="seg">
              <button
                v-for="m in (['price', 'growth'] as const)"
                :key="m"
                class="seg-b label"
                :class="{ on: mode === m }"
                @click="mode = m"
              >
                {{ m }}
              </button>
            </div>
            <div v-if="mode === 'price'" class="seg">
              <button class="seg-b label" :class="{ on: chartStyle === 'candles' }" @click="chartStyle = 'candles'">candles</button>
              <button class="seg-b label" :class="{ on: chartStyle === 'line' }" @click="chartStyle = 'line'">line</button>
            </div>
            <div class="seg">
              <button
                v-for="w in WINDOWS"
                :key="w"
                class="seg-b label"
                :class="{ on: win === w }"
                @click="win = w"
              >
                {{ w }}
              </button>
            </div>
          </div>
        </template>

        <!-- Audit Strip -->
        <div v-if="dataAudit" class="data-audit-strip label">
          <span class="audit-item status-pill" :class="dataAudit.isFresh ? 'fresh' : 'stale'">
            <b class="audit-dot" :class="dataAudit.isFresh ? 'fresh' : 'stale'" />
            {{ dataAudit.isLive ? 'LIVE MARK' : dataAudit.isFresh ? 'DATA AS OF' : 'STALE AS OF' }}
            {{ shortDate(dataAudit.lastDate) }}
          </span>
          <span class="audit-item dim">{{ dataAudit.nBars }} bars ({{ shortDate(dataAudit.firstDate) }} → {{ shortDate(dataAudit.barDate) }})</span>
          <span class="audit-item source-badge">{{ formatSourceLabel(dataAudit.source) }}</span>
          <span v-if="dataAudit.advUsd" class="audit-item dim">ADV: {{ compact(dataAudit.advUsd) }}</span>
        </div>

        <p v-if="trajErr" class="err">{{ trajErr }}</p>
        <LoadingState v-else-if="trajBusy && !traj" label="Loading trace…" />

        <template v-else-if="traj">
          <div class="overview-readouts">
            <Readout label="1D" :value="signedPct(s?.chg_1d_pct)" :tone="tone(s?.chg_1d_pct)" size="sm" />
            <Readout label="5D" :value="signedPct(s?.chg_5d_pct)" :tone="tone(s?.chg_5d_pct)" size="sm" />
            <Readout label="1M" :value="signedPct(s?.chg_1m_pct)" :tone="tone(s?.chg_1m_pct)" size="sm" />
            <Readout label="3M" :value="signedPct(s?.chg_3m_pct)" :tone="tone(s?.chg_3m_pct)" size="sm" />
            <Readout label="YTD" :value="signedPct(s?.chg_ytd_pct)" :tone="tone(s?.chg_ytd_pct)" size="sm" />
            <Readout label="Window" :value="signedPct(s?.chg_window_pct)" :tone="tone(s?.chg_window_pct)" size="sm" />
          </div>

          <TrajectoryChart
            :series="traj.series"
            :symbol="traj.symbol"
            :mode="mode"
            :render-as="mode === 'price' ? chartStyle : 'line'"
            :height="400"
          />

          <div class="stats-grid">
            <Readout label="Ann. return" :value="pct(s?.ann_return_pct)" :tone="tone(s?.ann_return_pct)" size="sm" />
            <Readout label="Ann. vol" :value="pct(s?.ann_vol_pct)" size="sm" />
            <Readout label="Sharpe" :value="s?.sharpe == null ? DASH : num(s.sharpe, 2)" :tone="tone(s?.sharpe)" size="sm" />
            <Readout label="Max DD" :value="pct(s?.max_drawdown_pct)" tone="neg" size="sm" />
            <Readout label="Calmar" :value="s?.calmar == null ? DASH : num(s.calmar, 2)" size="sm" />
            <Readout label="ATR 20" :value="s?.atr_20 != null ? num(s.atr_20) : DASH" :sub="s?.atr_pct != null ? pct(s.atr_pct, 1) : undefined" size="sm" />
            <Readout label="ADV 20" :value="compact(s?.adv_20_usd)" sub="usd" size="sm" />
            <Readout label="Best day" :value="signedPct(s?.best_day_pct)" tone="pos" size="sm" />
            <Readout label="Worst day" :value="signedPct(s?.worst_day_pct)" tone="neg" size="sm" />
            <Readout label="Days up" :value="s?.pct_days_up != null ? pct(s.pct_days_up, 1) : DASH" size="sm" />
          </div>
        </template>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">PRICE TRAJECTORY</span>
          <h3 class="unavail-title lab">Price Data Unavailable for {{ symbol }}</h3>
          <p class="unavail-desc">Historical bar data and trajectory could not be loaded from public market feeds.</p>
          <div class="unavail-meta label dim">
            <span>Upstream Feed: <strong>yfinance / Exchange Bars</strong></span>
          </div>
        </div>
      </Panel>

      <!-- Smart Score & Quick Intelligence Grid -->
      <div class="overview-sidebar">
        <!-- Smart Score Card -->
        <Panel label="Stock Smart Score" index="02" :meta="profile?.smart_score?.rating || DASH">
          <LoadingState v-if="profileRes.loading.value && !profile?.smart_score" label="Evaluating quantitative smart score…" />
          <div v-else-if="profile?.smart_score" class="smart-score-card">
            <div class="score-dial">
              <div
                class="score-circle"
                :class="{
                  pos: (profile.smart_score.score ?? 0) >= 8,
                  mid: (profile.smart_score.score ?? 0) >= 5 && (profile.smart_score.score ?? 0) < 8,
                  neg: (profile.smart_score.score ?? 0) < 5,
                }"
              >
                <span class="score-num fig">{{ profile.smart_score.score != null ? profile.smart_score.score : DASH }}</span>
                <span v-if="profile.smart_score.score != null" class="score-max label dim">/ 10</span>
              </div>
              <div class="score-desc">
                <strong
                  class="score-rating lab"
                  :class="(profile.smart_score.score ?? 0) >= 8 ? 'pos' : ((profile.smart_score.score ?? 0) <= 4 ? 'neg' : 'flat')"
                >
                  {{ profile.smart_score.rating || DASH }}
                </strong>
                <p class="score-note label dim">Quantitative 5-pillar synthesis: analyst consensus, fundamentals, momentum, insider, and institutional accumulation.</p>
              </div>
            </div>
            <div v-if="profile.smart_score.components" class="score-breakdown">
              <div v-for="(val, k) in profile.smart_score.components" :key="k" class="score-bar-row">
                <span class="score-bar-lbl label">{{ String(k).replace(/_/g, ' ') }}</span>
                <div class="score-bar-track">
                  <div
                    class="score-bar-fill"
                    :class="{ pos: val >= 8, mid: val >= 5 && val < 8, neg: val < 5 }"
                    :style="{ width: `${Math.min(100, Math.max(10, val * 10))}%` }"
                  />
                </div>
                <span class="score-bar-val fig" :class="{ pos: val >= 8, neg: val < 5 }">{{ val }}</span>
              </div>
            </div>
          </div>
          <div v-else class="unavail-meta label dim">
            <span>Score synthesis details unavailable for {{ symbol }}.</span>
          </div>
        </Panel>

        <!-- Signal Branch -->
        <Panel v-if="signalBranch" label="Desk Signal" index="03" :meta="signalBranch.model">
          <div class="signal-branch-card">
            <div class="sig-title-row">
              <span class="label sig-type">{{ signalBranch.type }}</span>
              <span class="sig-side-badge" :class="signalBranch.side.includes('LONG') ? 'pos' : 'neg'">
                {{ signalBranch.side }}
              </span>
              <span class="state label" :class="signalBranch.state === 'ENTER' ? 'enter' : 'watch'">
                {{ signalBranch.state }}
              </span>
            </div>
            <div class="sig-metrics">
              <Readout
                label="Edge"
                :value="signalBranch.prob != null ? pctFrac(signalBranch.prob, 1) : DASH"
                :tone="signalBranch.prob != null && signalBranch.prob >= 0.55 ? 'pos' : 'flat'"
                size="sm"
              />
              <Readout label="Horizon" :value="signalBranch.horizon || DASH" size="sm" />
              <Readout v-if="signalBranch.momentum !== undefined" label="Momentum" :value="signedPct(signalBranch.momentum, 2)" :tone="tone(signalBranch.momentum)" size="sm" />
            </div>
          </div>
        </Panel>
      </div>

      <!-- Quick Intelligence Cards Grid -->
      <div class="overview-cards-grid">
        <!-- Card: Financials Snapshot -->
        <div class="quick-card card-financials" @click="setTab('financials')">
          <div class="card-head">
            <span class="card-title lab">Financials</span>
            <span class="card-link label">VIEW STATEMENT →</span>
          </div>
          <div class="card-body">
            <div class="card-kpi-row">
              <span class="kpi-l label">TTM Revenue</span>
              <strong class="kpi-v fig">{{ formatBigUsd(finData?.income_statement?.rows?.[0]?.values?.[0] || (finData?.ratios?.market_cap ? (finData?.ratios?.enterprise_value ? finData.ratios.enterprise_value * 0.25 : null) : null)) }}</strong>
            </div>
            <div class="card-kpi-row">
              <span class="kpi-l label">Gross Margin</span>
              <strong class="kpi-v fig" :class="getGrowthTone(finData?.ratios?.gross_margin ?? getDerivedRatio(finData?.ratios as Record<string, number|null|undefined>, finData?.income_statement?.rows, 'gross_margin'))">
                {{ (finData?.ratios?.gross_margin ?? getDerivedRatio(finData?.ratios as Record<string, number|null|undefined>, finData?.income_statement?.rows, 'gross_margin')) != null ? `${finData?.ratios?.gross_margin ?? getDerivedRatio(finData?.ratios as Record<string, number|null|undefined>, finData?.income_statement?.rows, 'gross_margin')}%` : DASH }}
              </strong>
            </div>
            <div class="card-kpi-row">
              <span class="kpi-l label">Net Margin</span>
              <strong class="kpi-v fig" :class="getGrowthTone(finData?.ratios?.net_margin ?? getDerivedRatio(finData?.ratios as Record<string, number|null|undefined>, finData?.income_statement?.rows, 'net_margin'))">
                {{ (finData?.ratios?.net_margin ?? getDerivedRatio(finData?.ratios as Record<string, number|null|undefined>, finData?.income_statement?.rows, 'net_margin')) != null ? `${finData?.ratios?.net_margin ?? getDerivedRatio(finData?.ratios as Record<string, number|null|undefined>, finData?.income_statement?.rows, 'net_margin')}%` : DASH }}
              </strong>
            </div>
          </div>
        </div>

        <!-- Card: Insider Trading Snapshot -->
        <div class="quick-card card-insiders" @click="setTab('insiders')">
          <div class="card-head">
            <span class="card-title lab">Insider Trading</span>
            <span class="card-link label">OPEN TAPE →</span>
          </div>
          <div class="card-body">
            <div class="card-kpi-row">
              <span class="kpi-l label">90D Net Volume</span>
              <strong class="kpi-v fig" :class="getGrowthTone(insData?.summary?.net_volume_usd)">
                {{ formatBigUsd(insData?.summary?.net_volume_usd) }}
              </strong>
            </div>
            <div class="card-kpi-row">
              <span class="kpi-l label">Form 4 Trades</span>
              <strong class="kpi-v fig">{{ insData?.summary?.total_transactions != null ? `${insData.summary.total_transactions} filings` : DASH }}</strong>
            </div>
            <div class="card-kpi-row">
              <span class="kpi-l label">Buy vs Sell Mix</span>
              <strong v-if="insData?.summary" class="kpi-v fig pos">
                {{ insData.summary.buy_count }} BUY <span class="dim">/ {{ insData.summary.sell_count }} SELL</span>
              </strong>
              <strong v-else class="kpi-v fig dim">—</strong>
            </div>
          </div>
        </div>

        <!-- Card: Forecast Snapshot -->
        <div class="quick-card card-forecast" @click="setTab('forecast')">
          <div class="card-head">
            <span class="card-title lab">Analyst Forecast</span>
            <span class="card-link label">PRICE TARGETS →</span>
          </div>
          <div class="card-body">
            <div class="card-kpi-row">
              <span class="kpi-l label">Consensus</span>
              <strong class="kpi-v lab pos">{{ profile?.forecast?.consensus_rating || DASH }}</strong>
            </div>
            <div class="card-kpi-row">
              <span class="kpi-l label">Median Target</span>
              <strong class="kpi-v fig">{{ usd(profile?.forecast?.target_price_median) }}</strong>
            </div>
            <div class="card-kpi-row">
              <span class="kpi-l label">Implied Upside</span>
              <strong class="kpi-v fig" :class="getGrowthTone(profile?.forecast?.upside_pct)">
                {{ profile?.forecast?.upside_pct != null ? `+${profile.forecast.upside_pct}%` : DASH }}
              </strong>
            </div>
          </div>
        </div>

        <!-- Card: Government & Congress -->
        <div class="quick-card card-gov" @click="setTab('government')">
          <div class="card-head">
            <span class="card-title lab">Government & Lobbying</span>
            <span class="card-link label">DISCLOSURES →</span>
          </div>
          <div class="card-body">
            <div class="card-kpi-row">
              <span class="kpi-l label">Congress Trades</span>
              <strong class="kpi-v fig">{{ govData?.congress ? `${govData.congress.length} disclosures` : DASH }}</strong>
            </div>
            <div class="card-kpi-row">
              <span class="kpi-l label">Quarterly Lobbying</span>
              <strong class="kpi-v fig">{{ formatBigUsd(govData?.lobbying?.estimated_quarterly_spend) }}</strong>
            </div>
            <div class="card-kpi-row">
              <span class="kpi-l label">Federal Contracts</span>
              <strong class="kpi-v fig">{{ govData?.contracts ? `${govData.contracts.length} awards` : DASH }}</strong>
            </div>
          </div>
        </div>
      </div>

      <!-- Bulls Say vs Bears Say -->
      <Panel label="Bull Case vs Bear Case" index="04" meta="Analytical Thesis" class="overview-full-span">
        <div v-if="profile?.bull_bear?.bulls_say?.length || profile?.bull_bear?.bears_say?.length" class="bull-bear-grid">
          <div class="bull-box">
            <div class="thesis-header pos">
              <span class="thesis-icon">▲</span>
              <strong class="lab">BULLS SAY</strong>
            </div>
            <ul class="thesis-list">
              <li v-for="(pt, idx) in profile?.bull_bear?.bulls_say || []" :key="idx" class="thesis-item">
                <span class="dot pos">•</span>
                <p class="thesis-text">{{ pt }}</p>
              </li>
            </ul>
          </div>
          <div class="bear-box">
            <div class="thesis-header neg">
              <span class="thesis-icon">▼</span>
              <strong class="lab">BEARS SAY</strong>
            </div>
            <ul class="thesis-list">
              <li v-for="(pt, idx) in profile?.bull_bear?.bears_say || []" :key="idx" class="thesis-item">
                <span class="dot neg">•</span>
                <p class="thesis-text">{{ pt }}</p>
              </li>
            </ul>
          </div>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">THESIS SYNTHESIS</span>
          <h3 class="unavail-title lab">Bull / Bear Thesis Analysis Pending</h3>
          <p class="unavail-desc">Independent quantitative bull and bear thesis points are being synthesized for {{ symbol }}.</p>
          <div class="unavail-meta label dim">
            <span>Upstream Source: <strong>Financial Consensus & SEC Disclosures</strong></span>
          </div>
        </div>
      </Panel>

      <!-- About the Company -->
      <Panel :label="`About ${symbol}`" index="05" :meta="profile?.about?.sector || DASH" class="overview-full-span">
        <div class="about-card">
          <p class="about-desc">{{ profile?.about?.description || 'Company description unavailable from public filings.' }}</p>
          <div class="about-stats-row">
            <div class="about-stat-item">
              <span class="stat-lbl label">Headquarters</span>
              <strong class="stat-val fig">{{ profile?.about?.address || [profile?.about?.city, profile?.about?.state, profile?.about?.country].filter(Boolean).join(', ') || DASH }}</strong>
            </div>
            <div class="about-stat-item">
              <span class="stat-lbl label">Market Cap</span>
              <strong class="stat-val fig">{{ formatBigUsd(profile?.about?.market_cap) }}</strong>
            </div>
            <div class="about-stat-item">
              <span class="stat-lbl label">Full-Time Employees</span>
              <strong class="stat-val fig">{{ profile?.about?.employees != null ? profile.about.employees.toLocaleString() : DASH }}</strong>
            </div>
            <div class="about-stat-item">
              <span class="stat-lbl label">Website</span>
              <a v-if="profile?.about?.website" :href="profile.about.website" target="_blank" rel="noopener" class="stat-link label">
                {{ profile.about.website.replace('https://', '').replace('http://', '') }}
              </a>
              <span v-else class="dim">—</span>
            </div>
          </div>
        </div>
      </Panel>
    </section>

    <!-- ===================================================================== -->
    <!-- TAB 2: FINANCIALS                                                     -->
    <!-- ===================================================================== -->
    <section v-else-if="activeTab === 'financials'" class="tab-content financials-layout">
      <!-- Sub-tab toolbar -->
      <div class="financials-toolbar">
        <div class="fin-statement-selector">
          <button
            v-for="s in [
              { id: 'income', label: 'Income Statement' },
              { id: 'balance', label: 'Balance Sheet' },
              { id: 'cash', label: 'Cash Flow' },
              { id: 'breakdown', label: 'Revenue Breakdown' },
              { id: 'ratios', label: 'Valuation & Ratios' },
            ] as const"
            :key="s.id"
            type="button"
            class="fin-btn label"
            :class="{ on: finStatement === s.id }"
            @click="finStatement = s.id"
          >
            {{ s.label }}
          </button>
        </div>

        <div class="fin-controls-right">
          <div class="seg">
            <button class="seg-b label" :class="{ on: finPeriod === 'quarterly' }" @click="finPeriod = 'quarterly'">Quarterly</button>
            <button class="seg-b label" :class="{ on: finPeriod === 'annual' }" @click="finPeriod = 'annual'">Annual</button>
          </div>
          <div class="seg">
            <button class="seg-b label" :class="{ on: finViewMode === 'table' }" @click="finViewMode = 'table'">Table</button>
            <button class="seg-b label" :class="{ on: finViewMode === 'charts' }" @click="finViewMode = 'charts'">Charts</button>
          </div>
        </div>
      </div>

      <LoadingState v-if="financialsRes.loading.value && !finData" label="Loading financial filings…" />
      <p v-else-if="financialsRes.error.value" class="err">{{ financialsRes.error.value }}</p>

      <template v-else-if="finData">
        <!-- ---------------- TABLE VIEW MODE ---------------- -->
        <template v-if="finViewMode === 'table'">
          <!-- 1. Income Statement Table -->
          <Panel
            v-if="finStatement === 'income'"
            :label="`${symbol} Income Statement`"
            index="F1"
            :meta="`${finPeriod.toUpperCase()} · ${finData.periods?.length || 0} PERIODS`"
          >
            <div v-if="finData.income_statement?.rows?.length" class="table-scroll-container">
              <table class="financial-statement-grid">
                <thead>
                  <tr>
                    <th class="label col-metric">Line Item</th>
                    <th v-for="p in finData.periods" :key="p" class="label col-period">
                      {{ formatPeriodHeader(p, finPeriod === 'quarterly') }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in finData.income_statement.rows"
                    :key="row.key"
                    :class="{
                      'row-header': row.is_header,
                      'row-bold': row.is_bold,
                      'row-total': row.is_total,
                      [`indent-${row.indent || 0}`]: true,
                    }"
                  >
                    <td class="cell-label lab">{{ row.label }}</td>
                    <td
                      v-for="(val, idx) in row.values"
                      :key="idx"
                      class="cell-val fig"
                      :class="row.format === 'pct' ? getGrowthTone(val) : ''"
                    >
                      {{ formatStatementCell(val, row.format) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="institutional-unavailable-container">
              <span class="unavail-eyebrow label dim">INCOME STATEMENT</span>
              <h3 class="unavail-title lab">Income Statement Data Unavailable for {{ symbol }}</h3>
              <p class="unavail-desc">Standardized Income Statement filings could not be parsed for {{ symbol }} ({{ finPeriod }}).</p>
              <div class="unavail-meta label dim">
                <span>Upstream Feed: <strong>SEC EDGAR 10-K / 10-Q & yfinance</strong></span>
              </div>
            </div>
          </Panel>

          <!-- 2. Balance Sheet Table -->
          <Panel
            v-else-if="finStatement === 'balance'"
            :label="`${symbol} Balance Sheet`"
            index="F2"
            :meta="`${finPeriod.toUpperCase()} · ${finData.periods?.length || 0} PERIODS`"
          >
            <div v-if="finData.balance_sheet?.rows?.length" class="table-scroll-container">
              <table class="financial-statement-grid">
                <thead>
                  <tr>
                    <th class="label col-metric">Line Item</th>
                    <th v-for="p in finData.periods" :key="p" class="label col-period">
                      {{ formatPeriodHeader(p, finPeriod === 'quarterly') }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in finData.balance_sheet.rows"
                    :key="row.key"
                    :class="{
                      'row-header': row.is_header,
                      'row-bold': row.is_bold,
                      'row-total': row.is_total,
                      [`indent-${row.indent || 0}`]: true,
                    }"
                  >
                    <td class="cell-label lab">{{ row.label }}</td>
                    <td v-for="(val, idx) in row.values" :key="idx" class="cell-val fig">
                      {{ formatStatementCell(val, row.format) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="institutional-unavailable-container">
              <span class="unavail-eyebrow label dim">BALANCE SHEET</span>
              <h3 class="unavail-title lab">Balance Sheet Data Unavailable for {{ symbol }}</h3>
              <p class="unavail-desc">Balance Sheet filings could not be retrieved for {{ symbol }} ({{ finPeriod }}).</p>
              <div class="unavail-meta label dim">
                <span>Upstream Feed: <strong>SEC EDGAR 10-K / 10-Q & yfinance</strong></span>
              </div>
            </div>
          </Panel>

          <!-- 3. Cash Flow Table -->
          <Panel
            v-else-if="finStatement === 'cash'"
            :label="`${symbol} Cash Flow Statement`"
            index="F3"
            :meta="`${finPeriod.toUpperCase()} · ${finData.periods?.length || 0} PERIODS`"
          >
            <div v-if="finData.cash_flow?.rows?.length" class="table-scroll-container">
              <table class="financial-statement-grid">
                <thead>
                  <tr>
                    <th class="label col-metric">Line Item</th>
                    <th v-for="p in finData.periods" :key="p" class="label col-period">
                      {{ formatPeriodHeader(p, finPeriod === 'quarterly') }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in finData.cash_flow.rows"
                    :key="row.key"
                    :class="{
                      'row-header': row.is_header,
                      'row-bold': row.is_bold,
                      'row-total': row.is_total,
                      [`indent-${row.indent || 0}`]: true,
                    }"
                  >
                    <td class="cell-label lab">{{ row.label }}</td>
                    <td v-for="(val, idx) in row.values" :key="idx" class="cell-val fig">
                      {{ formatStatementCell(val, row.format) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="institutional-unavailable-container">
              <span class="unavail-eyebrow label dim">CASH FLOW</span>
              <h3 class="unavail-title lab">Cash Flow Statement Data Unavailable for {{ symbol }}</h3>
              <p class="unavail-desc">Cash Flow filings could not be parsed for {{ symbol }} ({{ finPeriod }}).</p>
              <div class="unavail-meta label dim">
                <span>Upstream Feed: <strong>SEC EDGAR 10-K / 10-Q & yfinance</strong></span>
              </div>
            </div>
          </Panel>

          <!-- 4. Revenue Breakdown -->
          <div v-else-if="finStatement === 'breakdown'" class="breakdown-grid">
            <Panel label="Revenue by Business Segment" index="F4a" meta="Segment Allocation">
              <div v-if="finData.revenue_breakdown?.by_segment?.length" class="breakdown-list">
                <div v-for="seg in finData.revenue_breakdown.by_segment" :key="seg.segment" class="breakdown-item">
                  <div class="breakdown-item-top">
                    <span class="seg-name lab">{{ seg.segment }}</span>
                    <strong class="seg-val fig">{{ formatBigUsd(seg.revenue) }}</strong>
                  </div>
                  <div class="breakdown-progress-track">
                    <div class="breakdown-progress-fill" :style="{ width: `${seg.pct || 0}%` }" />
                  </div>
                  <div class="breakdown-item-sub">
                    <span class="label dim">{{ seg.pct != null ? `${seg.pct}%` : DASH }} of total</span>
                    <span v-if="seg.growth_yoy" class="label pos">+{{ seg.growth_yoy }}% YoY Growth</span>
                  </div>
                </div>
              </div>
              <div v-else class="institutional-unavailable-container">
                <span class="unavail-eyebrow label dim">SEGMENT DISCLOSURES</span>
                <h3 class="unavail-title lab">Segment Breakdown Unavailable</h3>
                <p class="unavail-desc">Segment disclosures are not available for {{ symbol }}.</p>
                <div class="unavail-meta label dim">
                  <span>Source: <strong>SEC Form 10-K Notes</strong></span>
                </div>
              </div>
            </Panel>

            <Panel label="Revenue by Geography" index="F4b" meta="Geographic Allocation">
              <div v-if="finData.revenue_breakdown?.by_geography?.length" class="breakdown-list">
                <div v-for="geo in finData.revenue_breakdown.by_geography" :key="geo.region" class="breakdown-item">
                  <div class="breakdown-item-top">
                    <span class="seg-name lab">{{ geo.region }}</span>
                    <strong class="seg-val fig">{{ formatBigUsd(geo.revenue) }}</strong>
                  </div>
                  <div class="breakdown-progress-track">
                    <div class="breakdown-progress-fill" :style="{ width: `${geo.pct || 0}%` }" />
                  </div>
                  <div class="breakdown-item-sub">
                    <span class="label dim">{{ geo.pct != null ? `${geo.pct}%` : DASH }} of total</span>
                  </div>
                </div>
              </div>
              <div v-else class="institutional-unavailable-container">
                <span class="unavail-eyebrow label dim">GEOGRAPHY DISCLOSURES</span>
                <h3 class="unavail-title lab">Geographic Breakdown Unavailable</h3>
                <p class="unavail-desc">Geographical revenue reporting is not provided for {{ symbol }}.</p>
                <div class="unavail-meta label dim">
                  <span>Source: <strong>SEC Form 10-K Notes</strong></span>
                </div>
              </div>
            </Panel>
          </div>

          <!-- 5. Valuation Ratios & Health -->
          <Panel v-else-if="finStatement === 'ratios'" label="Valuation & Financial Health Multiples" index="F5" meta="Multiples">
            <div class="ratios-multiples-grid">
              <div class="ratio-card">
                <span class="ratio-label label">Trailing P/E</span>
                <strong class="ratio-value fig">{{ finData.ratios?.pe_trailing != null ? `${finData.ratios.pe_trailing}x` : DASH }}</strong>
                <span class="ratio-desc label dim">Market Cap / Net Income</span>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Forward P/E</span>
                <strong class="ratio-value fig">{{ finData.ratios?.pe_forward != null ? `${finData.ratios.pe_forward}x` : DASH }}</strong>
                <span class="ratio-desc label dim">12M Forward Earnings</span>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Price to Sales (P/S)</span>
                <strong class="ratio-value fig">{{ finData.ratios?.ps_trailing != null ? `${finData.ratios.ps_trailing}x` : DASH }}</strong>
                <span class="ratio-desc label dim">Market Cap / TTM Revenue</span>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Price to Book (P/B)</span>
                <strong class="ratio-value fig">{{ finData.ratios?.pb_trailing != null ? `${finData.ratios.pb_trailing}x` : DASH }}</strong>
                <span class="ratio-desc label dim">Market Cap / Equity</span>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">EV / EBITDA</span>
                <strong class="ratio-value fig">{{ finData.ratios?.ev_ebitda != null ? `${finData.ratios.ev_ebitda}x` : DASH }}</strong>
                <span class="ratio-desc label dim">Enterprise Val / EBITDA</span>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">EV / Revenue</span>
                <strong class="ratio-value fig">{{ finData.ratios?.ev_revenue != null ? `${finData.ratios.ev_revenue}x` : DASH }}</strong>
                <span class="ratio-desc label dim">Enterprise Val / Sales</span>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Debt to Equity</span>
                <strong class="ratio-value fig">{{ finData.ratios?.debt_to_equity != null ? finData.ratios.debt_to_equity : DASH }}</strong>
                <span class="ratio-desc label dim">Total Debt / Total Equity</span>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Current Ratio</span>
                <strong class="ratio-value fig">{{ finData.ratios?.current_ratio != null ? finData.ratios.current_ratio : DASH }}</strong>
                <span class="ratio-desc label dim">Current Assets / Liabilities</span>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Return on Equity (ROE)</span>
                <strong class="ratio-value fig" :class="getGrowthTone(finData.ratios?.roe)">{{ finData.ratios?.roe != null ? `${finData.ratios.roe}%` : DASH }}</strong>
                <span class="ratio-desc label dim">Net Income / Equity</span>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Return on Assets (ROA)</span>
                <strong class="ratio-value fig" :class="getGrowthTone(finData.ratios?.roa)">{{ finData.ratios?.roa != null ? `${finData.ratios.roa}%` : DASH }}</strong>
                <span class="ratio-desc label dim">Net Income / Total Assets</span>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">YoY Revenue Growth</span>
                <strong class="ratio-value fig" :class="getGrowthTone(finData.ratios?.revenue_growth_yoy)">{{ finData.ratios?.revenue_growth_yoy != null ? `+${finData.ratios.revenue_growth_yoy}%` : DASH }}</strong>
                <span class="ratio-desc label dim">Annualized Topline Change</span>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Free Cash Flow</span>
                <strong class="ratio-value fig" :class="getGrowthTone(finData.ratios?.free_cash_flow)">{{ formatBigUsd(finData.ratios?.free_cash_flow) }}</strong>
                <span class="ratio-desc label dim">Operating Cash - CapEx</span>
              </div>
            </div>
          </Panel>
        </template>

        <!-- ---------------- CHARTS VIEW MODE ---------------- -->
        <template v-else-if="finViewMode === 'charts'">
          <!-- 1. Income Statement Charts -->
          <Panel
            v-if="finStatement === 'income'"
            :label="`${symbol} Revenue & Profitability Trajectory`"
            index="F1"
            :meta="`${finPeriod.toUpperCase()} · ${finData.periods?.length || 0} PERIODS`"
          >
            <div v-if="finChartData" class="fin-chart-card">
              <div class="fin-chart-legend">
                <span class="chart-leg-item"><i class="leg-swatch rev" /> Revenue</span>
                <span class="chart-leg-item"><i class="leg-swatch gross" /> Gross Profit</span>
                <span class="chart-leg-item"><i class="leg-swatch op" /> Operating Income</span>
                <span class="chart-leg-item"><i class="leg-swatch net" /> Net Income</span>
              </div>
              <div class="fin-bars-timeline">
                <div v-for="(p, idx) in finChartData.periods" :key="p" class="fin-timeline-col">
                  <div class="fin-col-bars">
                    <div
                      v-if="finChartData.income.revenue[idx] != null"
                      class="fin-bar rev"
                      :style="{ height: `${Math.max(4, (Math.abs(finChartData.income.revenue[idx]!) / finChartData.income.maxVal) * 100)}%` }"
                      :title="`Revenue: ${formatBigUsd(finChartData.income.revenue[idx])}`"
                    />
                    <div
                      v-if="finChartData.income.grossProfit[idx] != null"
                      class="fin-bar gross"
                      :style="{ height: `${Math.max(4, (Math.abs(finChartData.income.grossProfit[idx]!) / finChartData.income.maxVal) * 100)}%` }"
                      :title="`Gross Profit: ${formatBigUsd(finChartData.income.grossProfit[idx])}`"
                    />
                    <div
                      v-if="finChartData.income.operatingIncome[idx] != null"
                      class="fin-bar op"
                      :class="finChartData.income.operatingIncome[idx]! >= 0 ? 'pos' : 'neg'"
                      :style="{ height: `${Math.max(4, (Math.abs(finChartData.income.operatingIncome[idx]!) / finChartData.income.maxVal) * 100)}%` }"
                      :title="`Operating Income: ${formatBigUsd(finChartData.income.operatingIncome[idx])}`"
                    />
                    <div
                      v-if="finChartData.income.netIncome[idx] != null"
                      class="fin-bar net"
                      :class="finChartData.income.netIncome[idx]! >= 0 ? 'pos' : 'neg'"
                      :style="{ height: `${Math.max(4, (Math.abs(finChartData.income.netIncome[idx]!) / finChartData.income.maxVal) * 100)}%` }"
                      :title="`Net Income: ${formatBigUsd(finChartData.income.netIncome[idx])}`"
                    />
                  </div>
                  <span class="fin-col-lbl label">{{ finChartData.formattedPeriods[idx] }}</span>
                  <span class="fin-col-val fig">{{ formatBigUsd(finChartData.income.revenue[idx]) }}</span>
                </div>
              </div>
            </div>
            <div v-else class="institutional-unavailable-container">
              <span class="unavail-eyebrow label dim">STATEMENT VISUALIZATION</span>
              <h3 class="unavail-title lab">Income Statement Chart Data Unavailable</h3>
              <p class="unavail-desc">Multi-period chart metrics could not be rendered for {{ symbol }}.</p>
              <div class="unavail-meta label dim">
                <span>Upstream Source: <strong>SEC EDGAR & yfinance</strong></span>
              </div>
            </div>
          </Panel>

          <!-- 2. Balance Sheet Charts -->
          <Panel
            v-else-if="finStatement === 'balance'"
            :label="`${symbol} Capital Structure & Solvency Trajectory`"
            index="F2"
            :meta="`${finPeriod.toUpperCase()} · ${finData.periods?.length || 0} PERIODS`"
          >
            <div v-if="finChartData" class="fin-chart-card">
              <div class="fin-chart-legend">
                <span class="chart-leg-item"><i class="leg-swatch assets" /> Total Assets</span>
                <span class="chart-leg-item"><i class="leg-swatch liab" /> Total Liabilities</span>
                <span class="chart-leg-item"><i class="leg-swatch equity" /> Stockholders Equity</span>
              </div>
              <div class="fin-bars-timeline">
                <div v-for="(p, idx) in finChartData.periods" :key="p" class="fin-timeline-col">
                  <div class="fin-col-bars">
                    <div
                      v-if="finChartData.balance.assets[idx] != null"
                      class="fin-bar assets"
                      :style="{ height: `${Math.max(4, (Math.abs(finChartData.balance.assets[idx]!) / finChartData.balance.maxVal) * 100)}%` }"
                      :title="`Assets: ${formatBigUsd(finChartData.balance.assets[idx])}`"
                    />
                    <div
                      v-if="finChartData.balance.liabilities[idx] != null"
                      class="fin-bar liab"
                      :style="{ height: `${Math.max(4, (Math.abs(finChartData.balance.liabilities[idx]!) / finChartData.balance.maxVal) * 100)}%` }"
                      :title="`Liabilities: ${formatBigUsd(finChartData.balance.liabilities[idx])}`"
                    />
                    <div
                      v-if="finChartData.balance.equity[idx] != null"
                      class="fin-bar equity"
                      :style="{ height: `${Math.max(4, (Math.abs(finChartData.balance.equity[idx]!) / finChartData.balance.maxVal) * 100)}%` }"
                      :title="`Equity: ${formatBigUsd(finChartData.balance.equity[idx])}`"
                    />
                  </div>
                  <span class="fin-col-lbl label">{{ finChartData.formattedPeriods[idx] }}</span>
                  <span class="fin-col-val fig">{{ formatBigUsd(finChartData.balance.assets[idx]) }}</span>
                </div>
              </div>
            </div>
            <div v-else class="institutional-unavailable-container">
              <span class="unavail-eyebrow label dim">STATEMENT VISUALIZATION</span>
              <h3 class="unavail-title lab">Balance Sheet Chart Data Unavailable</h3>
              <p class="unavail-desc">Balance Sheet chart metrics could not be rendered for {{ symbol }}.</p>
              <div class="unavail-meta label dim">
                <span>Upstream Source: <strong>SEC EDGAR & yfinance</strong></span>
              </div>
            </div>
          </Panel>

          <!-- 3. Cash Flow Charts -->
          <Panel
            v-else-if="finStatement === 'cash'"
            :label="`${symbol} Cash Flow & Capital Allocation Trajectory`"
            index="F3"
            :meta="`${finPeriod.toUpperCase()} · ${finData.periods?.length || 0} PERIODS`"
          >
            <div v-if="finChartData" class="fin-chart-card">
              <div class="fin-chart-legend">
                <span class="chart-leg-item"><i class="leg-swatch ocf" /> Operating Cash Flow</span>
                <span class="chart-leg-item"><i class="leg-swatch fcf" /> Free Cash Flow</span>
                <span class="chart-leg-item"><i class="leg-swatch capex" /> Capital Expenditures</span>
              </div>
              <div class="fin-bars-timeline">
                <div v-for="(p, idx) in finChartData.periods" :key="p" class="fin-timeline-col">
                  <div class="fin-col-bars">
                    <div
                      v-if="finChartData.cashFlow.operatingCashFlow[idx] != null"
                      class="fin-bar ocf"
                      :style="{ height: `${Math.max(4, (Math.abs(finChartData.cashFlow.operatingCashFlow[idx]!) / finChartData.cashFlow.maxVal) * 100)}%` }"
                      :title="`OCF: ${formatBigUsd(finChartData.cashFlow.operatingCashFlow[idx])}`"
                    />
                    <div
                      v-if="finChartData.cashFlow.freeCashFlow[idx] != null"
                      class="fin-bar fcf"
                      :class="finChartData.cashFlow.freeCashFlow[idx]! >= 0 ? 'pos' : 'neg'"
                      :style="{ height: `${Math.max(4, (Math.abs(finChartData.cashFlow.freeCashFlow[idx]!) / finChartData.cashFlow.maxVal) * 100)}%` }"
                      :title="`FCF: ${formatBigUsd(finChartData.cashFlow.freeCashFlow[idx])}`"
                    />
                    <div
                      v-if="finChartData.cashFlow.capex[idx] != null"
                      class="fin-bar capex"
                      :style="{ height: `${Math.max(4, (Math.abs(finChartData.cashFlow.capex[idx]!) / finChartData.cashFlow.maxVal) * 100)}%` }"
                      :title="`CapEx: ${formatBigUsd(finChartData.cashFlow.capex[idx])}`"
                    />
                  </div>
                  <span class="fin-col-lbl label">{{ finChartData.formattedPeriods[idx] }}</span>
                  <span class="fin-col-val fig">{{ formatBigUsd(finChartData.cashFlow.operatingCashFlow[idx]) }}</span>
                </div>
              </div>
            </div>
            <div v-else class="institutional-unavailable-container">
              <span class="unavail-eyebrow label dim">STATEMENT VISUALIZATION</span>
              <h3 class="unavail-title lab">Cash Flow Chart Data Unavailable</h3>
              <p class="unavail-desc">Cash Flow chart metrics could not be rendered for {{ symbol }}.</p>
              <div class="unavail-meta label dim">
                <span>Upstream Source: <strong>SEC EDGAR & yfinance</strong></span>
              </div>
            </div>
          </Panel>

          <!-- 4. Revenue Breakdown Charts -->
          <div v-else-if="finStatement === 'breakdown'" class="breakdown-grid">
            <Panel label="Revenue by Business Segment" index="F4a" meta="Segment Allocation">
              <div v-if="finData.revenue_breakdown?.by_segment?.length" class="breakdown-list">
                <div v-for="seg in finData.revenue_breakdown.by_segment" :key="seg.segment" class="breakdown-item">
                  <div class="breakdown-item-top">
                    <span class="seg-name lab">{{ seg.segment }}</span>
                    <strong class="seg-val fig">{{ formatBigUsd(seg.revenue) }}</strong>
                  </div>
                  <div class="breakdown-progress-track">
                    <div class="breakdown-progress-fill" :style="{ width: `${seg.pct || 0}%` }" />
                  </div>
                  <div class="breakdown-item-sub">
                    <span class="label dim">{{ seg.pct != null ? `${seg.pct}%` : DASH }} of total</span>
                    <span v-if="seg.growth_yoy" class="label pos">+{{ seg.growth_yoy }}% YoY Growth</span>
                  </div>
                </div>
              </div>
              <div v-else class="institutional-unavailable-container">
                <span class="unavail-eyebrow label dim">SEGMENT DISCLOSURES</span>
                <h3 class="unavail-title lab">Segment Breakdown Unavailable</h3>
                <p class="unavail-desc">Segment disclosures are not available for {{ symbol }}.</p>
                <div class="unavail-meta label dim">
                  <span>Source: <strong>SEC Form 10-K Notes</strong></span>
                </div>
              </div>
            </Panel>

            <Panel label="Revenue by Geography" index="F4b" meta="Geographic Allocation">
              <div v-if="finData.revenue_breakdown?.by_geography?.length" class="breakdown-list">
                <div v-for="geo in finData.revenue_breakdown.by_geography" :key="geo.region" class="breakdown-item">
                  <div class="breakdown-item-top">
                    <span class="seg-name lab">{{ geo.region }}</span>
                    <strong class="seg-val fig">{{ formatBigUsd(geo.revenue) }}</strong>
                  </div>
                  <div class="breakdown-progress-track">
                    <div class="breakdown-progress-fill" :style="{ width: `${geo.pct || 0}%` }" />
                  </div>
                  <div class="breakdown-item-sub">
                    <span class="label dim">{{ geo.pct != null ? `${geo.pct}%` : DASH }} of total</span>
                  </div>
                </div>
              </div>
              <div v-else class="institutional-unavailable-container">
                <span class="unavail-eyebrow label dim">GEOGRAPHY DISCLOSURES</span>
                <h3 class="unavail-title lab">Geographic Breakdown Unavailable</h3>
                <p class="unavail-desc">Geographical revenue reporting is not provided for {{ symbol }}.</p>
                <div class="unavail-meta label dim">
                  <span>Source: <strong>SEC Form 10-K Notes</strong></span>
                </div>
              </div>
            </Panel>
          </div>

          <!-- 5. Valuation Ratios & Health -->
          <Panel v-else-if="finStatement === 'ratios'" label="Valuation & Financial Health Multiples" index="F5" meta="Multiples">
            <div class="ratios-multiples-grid">
              <div class="ratio-card">
                <span class="ratio-label label">Trailing P/E</span>
                <strong class="ratio-value fig">{{ finData.ratios?.pe_trailing != null ? `${finData.ratios.pe_trailing}x` : DASH }}</strong>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Forward P/E</span>
                <strong class="ratio-value fig">{{ finData.ratios?.pe_forward != null ? `${finData.ratios.pe_forward}x` : DASH }}</strong>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Price to Sales (P/S)</span>
                <strong class="ratio-value fig">{{ finData.ratios?.ps_trailing != null ? `${finData.ratios.ps_trailing}x` : DASH }}</strong>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Price to Book (P/B)</span>
                <strong class="ratio-value fig">{{ finData.ratios?.pb_trailing != null ? `${finData.ratios.pb_trailing}x` : DASH }}</strong>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">EV / EBITDA</span>
                <strong class="ratio-value fig">{{ finData.ratios?.ev_ebitda != null ? `${finData.ratios.ev_ebitda}x` : DASH }}</strong>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">EV / Revenue</span>
                <strong class="ratio-value fig">{{ finData.ratios?.ev_revenue != null ? `${finData.ratios.ev_revenue}x` : DASH }}</strong>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Debt to Equity</span>
                <strong class="ratio-value fig">{{ finData.ratios?.debt_to_equity != null ? finData.ratios.debt_to_equity : DASH }}</strong>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Current Ratio</span>
                <strong class="ratio-value fig">{{ finData.ratios?.current_ratio != null ? finData.ratios.current_ratio : DASH }}</strong>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Return on Equity (ROE)</span>
                <strong class="ratio-value fig" :class="getGrowthTone(finData.ratios?.roe)">{{ finData.ratios?.roe != null ? `${finData.ratios.roe}%` : DASH }}</strong>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Return on Assets (ROA)</span>
                <strong class="ratio-value fig" :class="getGrowthTone(finData.ratios?.roa)">{{ finData.ratios?.roa != null ? `${finData.ratios.roa}%` : DASH }}</strong>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">YoY Revenue Growth</span>
                <strong class="ratio-value fig" :class="getGrowthTone(finData.ratios?.revenue_growth_yoy)">{{ finData.ratios?.revenue_growth_yoy != null ? `+${finData.ratios.revenue_growth_yoy}%` : DASH }}</strong>
              </div>
              <div class="ratio-card">
                <span class="ratio-label label">Free Cash Flow</span>
                <strong class="ratio-value fig">{{ formatBigUsd(finData.ratios?.free_cash_flow) }}</strong>
              </div>
            </div>
          </Panel>
        </template>
      </template>

      <div v-else class="institutional-unavailable-container">
        <span class="unavail-eyebrow label dim">FINANCIAL DATA FEED</span>
        <h3 class="unavail-title lab">Financial Statements Unavailable for {{ symbol }}</h3>
        <p class="unavail-desc">Multi-period SEC EDGAR filings and financial ratio computations could not be loaded for {{ symbol }}.</p>
        <div class="unavail-meta label dim">
          <span>Upstream Source: <strong>SEC EDGAR Direct & yfinance</strong></span>
        </div>
      </div>
    </section>

    <!-- ===================================================================== -->
    <!-- TAB 3: FORECAST                                                       -->
    <!-- ===================================================================== -->
    <section v-else-if="activeTab === 'forecast'" class="tab-content forecast-layout">
      <div class="forecast-top-grid">
        <!-- Ratings Breakdown -->
        <Panel label="Analyst Ratings Consensus" index="T1" :meta="profile?.forecast?.consensus_rating || DASH">
          <div v-if="profile?.forecast" class="forecast-rating-box">
            <div class="rating-consensus-hero">
              <strong class="consensus-badge lab pos">{{ profile.forecast.consensus_rating || DASH }}</strong>
              <span class="consensus-sub label dim">
                {{ profile.forecast.recommendation_mean != null ? `Score: ${profile.forecast.recommendation_mean} / 5.0 (1.0 = Max Conviction)` : 'Score: —' }}
              </span>
            </div>
            <div v-if="profile.forecast.recommendations" class="rec-distribution-bars">
              <div class="rec-bar-item">
                <span class="rec-lbl label pos">Strong Buy</span>
                <span class="rec-count fig">{{ profile.forecast.recommendations.strong_buy ?? 0 }}</span>
              </div>
              <div class="rec-bar-item">
                <span class="rec-lbl label pos">Buy</span>
                <span class="rec-count fig">{{ profile.forecast.recommendations.buy ?? 0 }}</span>
              </div>
              <div class="rec-bar-item">
                <span class="rec-lbl label">Hold</span>
                <span class="rec-count fig">{{ profile.forecast.recommendations.hold ?? 0 }}</span>
              </div>
              <div class="rec-bar-item">
                <span class="rec-lbl label neg">Underperform</span>
                <span class="rec-count fig">{{ profile.forecast.recommendations.underperform ?? 0 }}</span>
              </div>
              <div class="rec-bar-item">
                <span class="rec-lbl label neg">Sell</span>
                <span class="rec-count fig">{{ profile.forecast.recommendations.sell ?? 0 }}</span>
              </div>
            </div>
          </div>
          <div v-else class="institutional-unavailable-container">
            <span class="unavail-eyebrow label dim">CONSENSUS RATINGS</span>
            <h3 class="unavail-title lab">Analyst Ratings Unavailable for {{ symbol }}</h3>
            <p class="unavail-desc">Wall Street analyst consensus coverage is currently not available for this symbol.</p>
            <div class="unavail-meta label dim">
              <span>Source: <strong>Wall Street Consensus Aggregators</strong></span>
            </div>
          </div>
        </Panel>

        <!-- Price Target Meter -->
        <Panel label="12-Month Price Targets" index="T2" :meta="profile?.forecast?.target_price_median != null ? `MEDIAN ${usd(profile.forecast.target_price_median)}` : DASH">
          <div v-if="profile?.forecast?.target_price_median != null" class="price-target-meter-card">
            <div class="pt-values-row">
              <div class="pt-val-item">
                <span class="pt-lbl label dim">Lowest Target</span>
                <strong class="pt-num fig">{{ usd(profile.forecast.target_price_low) }}</strong>
              </div>
              <div class="pt-val-item highlight">
                <span class="pt-lbl label pos">Median Target</span>
                <strong class="pt-num fig pos">{{ usd(profile.forecast.target_price_median) }}</strong>
                <span v-if="profile.forecast.upside_pct != null" class="pt-upside label pos">+{{ profile.forecast.upside_pct }}% Upside</span>
                <span v-else class="pt-upside label dim">—</span>
              </div>
              <div class="pt-val-item">
                <span class="pt-lbl label dim">Highest Target</span>
                <strong class="pt-num fig">{{ usd(profile.forecast.target_price_high) }}</strong>
              </div>
            </div>
            <div class="pt-gauge-track">
              <div
                class="pt-gauge-range"
                :style="(() => {
                  const lo = profile.forecast.target_price_low ?? 0
                  const hi = profile.forecast.target_price_high ?? 0
                  const median = profile.forecast.target_price_median ?? 0
                  const cur = s?.last_price ?? median
                  const min = Math.min(lo, cur) * 0.97
                  const max = Math.max(hi, cur) * 1.03
                  const span = max - min || 1
                  const leftPct = ((lo - min) / span) * 100
                  const widthPct = ((hi - lo) / span) * 100
                  return { left: `${leftPct.toFixed(1)}%`, width: `${Math.max(4, widthPct).toFixed(1)}%` }
                })()"
              />
              <div
                class="pt-gauge-current-marker"
                :style="(() => {
                  const lo = profile.forecast.target_price_low ?? 0
                  const hi = profile.forecast.target_price_high ?? 0
                  const median = profile.forecast.target_price_median ?? 0
                  const cur = s?.last_price ?? median
                  const min = Math.min(lo, cur) * 0.97
                  const max = Math.max(hi, cur) * 1.03
                  const span = max - min || 1
                  return { left: `${(((cur - min) / span) * 100).toFixed(1)}%` }
                })()"
                title="Current Price"
              />
            </div>
            <div class="pt-caption-row label dim">
              <span>Low Range</span>
              <span>Current Mark: {{ usd(s?.last_price) }}</span>
              <span>High Range</span>
            </div>
          </div>
          <div v-else class="institutional-unavailable-container">
            <span class="unavail-eyebrow label dim">PRICE TARGETS</span>
            <h3 class="unavail-title lab">Price Target Disclosures Unavailable</h3>
            <p class="unavail-desc">12-month forward price target models are not reported for {{ symbol }}.</p>
            <div class="unavail-meta label dim">
              <span>Source: <strong>Consensus Equity Research</strong></span>
            </div>
          </div>
        </Panel>
      </div>

      <!-- Upgrades / Downgrades History -->
      <Panel
        label="Wall Street Analyst Ratings & Revisions"
        index="T3"
        :meta="`${filteredRevisions.length} of ${revisionsCounts.all} Actions`"
      >
        <div class="insider-table-filters">
          <div class="seg">
            <button class="seg-b label" :class="{ on: forecastActionFilter === 'all' }" @click="forecastActionFilter = 'all'">
              All ({{ revisionsCounts.all }})
            </button>
            <button class="seg-b label" :class="{ on: forecastActionFilter === 'upgrade' }" @click="forecastActionFilter = 'upgrade'">
              Upgrades ({{ revisionsCounts.upgrade }})
            </button>
            <button class="seg-b label" :class="{ on: forecastActionFilter === 'initiate' }" @click="forecastActionFilter = 'initiate'">
              Initiations ({{ revisionsCounts.initiate }})
            </button>
            <button class="seg-b label" :class="{ on: forecastActionFilter === 'maintain' }" @click="forecastActionFilter = 'maintain'">
              Maintains ({{ revisionsCounts.maintain }})
            </button>
            <button class="seg-b label" :class="{ on: forecastActionFilter === 'downgrade' }" @click="forecastActionFilter = 'downgrade'">
              Downgrades ({{ revisionsCounts.downgrade }})
            </button>
          </div>
          <input
            v-model="forecastSearchQuery"
            class="filter-search-input"
            placeholder="Search firm, grade, or action..."
          />
        </div>

        <div v-if="filteredRevisions.length" class="table-scroll-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label">Date</th>
                <th class="label">Research Firm</th>
                <th class="label">Action</th>
                <th class="label">Current Grade</th>
                <th class="label">Prior Grade</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(rev, idx) in filteredRevisions" :key="idx">
                <td class="dim fig">{{ rev.date || DASH }}</td>
                <td class="lab bold">{{ rev.firm || DASH }}</td>
                <td>
                  <span
                    class="kind label"
                    :class="
                      rev.action?.toLowerCase().includes('upgrade') || rev.action?.toLowerCase().includes('initiat') || rev.action?.toLowerCase() === 'up'
                        ? 'pos'
                        : (rev.action?.toLowerCase().includes('downgrade') || rev.action?.toLowerCase() === 'down' ? 'neg' : 'dim')
                    "
                  >
                    {{ rev.action || DASH }}
                  </span>
                </td>
                <td class="fig" :class="/buy|outperform|overweight|positive/i.test(rev.current || rev.to_grade || '') ? 'pos' : (/sell|underperform|underweight/i.test(rev.current || rev.to_grade || '') ? 'neg' : 'dim')">
                  {{ rev.current || rev.to_grade || DASH }}
                </td>
                <td class="dim fig">{{ rev.previous || rev.from_grade || DASH }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">REVISIONS TAPE</span>
          <h3 class="unavail-title lab">No Analyst Ratings Match Criteria</h3>
          <p class="unavail-desc">No rating upgrades or downgrades match the selected filter for {{ symbol }}.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>Wall Street Equity Research Coverage Ledger</strong></span>
          </div>
        </div>
      </Panel>
    </section>

    <!-- ===================================================================== -->
    <!-- TAB 4: INSIDERS                                                       -->
    <!-- ===================================================================== -->
    <section v-else-if="activeTab === 'insiders'" class="tab-content insiders-layout">
      <!-- KPIs Strip -->
      <div class="insider-kpis-strip">
        <div class="kpi-card">
          <span class="kpi-lbl label">90D Net Volume</span>
          <strong class="kpi-val fig" :class="getGrowthTone(insData?.summary?.net_volume_usd)">
            {{ formatBigUsd(insData?.summary?.net_volume_usd) }}
          </strong>
        </div>
        <div class="kpi-card">
          <span class="kpi-lbl label">Total Purchases ($)</span>
          <strong class="kpi-val fig pos">{{ formatBigUsd(insData?.summary?.buy_volume_usd) }}</strong>
        </div>
        <div class="kpi-card">
          <span class="kpi-lbl label">Total Sales ($)</span>
          <strong class="kpi-val fig neg">{{ formatBigUsd(insData?.summary?.sell_volume_usd) }}</strong>
        </div>
        <div class="kpi-card">
          <span class="kpi-lbl label">Form 4 Filings</span>
          <strong class="kpi-val fig">{{ insData?.summary?.total_transactions != null ? insData.summary.total_transactions : DASH }}</strong>
        </div>
      </div>

      <!-- Quarterly Net Insider Trading Graph -->
      <Panel label="Quarterly Net Insider Volume" index="I1" meta="SEC Form 4 Open Market Activity">
        <div v-if="insData?.quarterly_net?.length" class="quarterly-insiders-chart">
          <div v-for="q in insData.quarterly_net" :key="q.quarter" class="q-bar-column">
            <div class="q-bar-wrapper">
              <div
                class="q-bar"
                :class="q.net_volume >= 0 ? 'pos' : 'neg'"
                :style="{
                  height: `${Math.min(100, Math.max(12, (Math.abs(q.net_volume) / insMaxQuarterlyVol) * 100))}%`,
                }"
              />
            </div>
            <span class="q-label label">{{ q.quarter }}</span>
            <span class="q-val fig" :class="q.net_volume >= 0 ? 'pos' : 'neg'">
              {{ formatBigUsd(q.net_volume) }}
            </span>
          </div>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">QUARTERLY SENTIMENT</span>
          <h3 class="unavail-title lab">Quarterly Net Insider Data Unavailable</h3>
          <p class="unavail-desc">Historical quarterly net insider volume breakdown is not available for {{ symbol }}.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>SEC Form 4 Archives</strong></span>
          </div>
        </div>
      </Panel>

      <!-- Insider Trades Table with Filters -->
      <Panel label="SEC Form 4 Insider Trades Tape" index="I2" :meta="`${filteredTransactions.length} Transactions`">
        <div class="insider-table-filters">
          <div class="seg">
            <button class="seg-b label" :class="{ on: insiderTypeFilter === 'all' }" @click="insiderTypeFilter = 'all'">All</button>
            <button class="seg-b label" :class="{ on: insiderTypeFilter === 'buy' }" @click="insiderTypeFilter = 'buy'">Buys Only</button>
            <button class="seg-b label" :class="{ on: insiderTypeFilter === 'sell' }" @click="insiderTypeFilter = 'sell'">Sales Only</button>
          </div>
          <input
            v-model="insiderSearchQuery"
            class="filter-search-input"
            placeholder="Filter by name or role..."
          />
        </div>

        <div v-if="filteredTransactions.length" class="table-scroll-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label">Date</th>
                <th class="label">Insider</th>
                <th class="label">Role</th>
                <th class="label">Type</th>
                <th class="label">Shares</th>
                <th class="label">Price</th>
                <th class="label">Total Value</th>
                <th class="label">Shares Held</th>
                <th class="label">SEC Doc</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(tx, idx) in filteredTransactions" :key="idx">
                <td class="dim fig">{{ tx.date || DASH }}</td>
                <td class="lab bold">{{ tx.insider_name || DASH }}</td>
                <td class="dim">{{ tx.relationship || DASH }}</td>
                <td>
                  <span class="kind label" :class="tx.transaction_type === 'Purchase' ? 'pos' : 'neg'">
                    {{ tx.transaction_type ? tx.transaction_type.toUpperCase() : DASH }}
                  </span>
                </td>
                <td class="fig">{{ tx.shares != null ? tx.shares.toLocaleString() : DASH }}</td>
                <td class="fig">{{ formatPerShare(tx.price) }}</td>
                <td class="fig" :class="tx.transaction_type === 'Purchase' ? 'pos' : 'neg'">
                  {{ formatBigUsd(tx.value) }}
                </td>
                <td class="fig dim">{{ tx.shares_held_after != null ? tx.shares_held_after.toLocaleString() : DASH }}</td>
                <td>
                  <a
                    :href="tx.sec_form_url || `https://www.sec.gov/edgar/search/#/q=${encodeURIComponent(symbol)}&forms=4`"
                    target="_blank"
                    rel="noopener"
                    class="label link"
                  >
                    Form 4 ↗
                  </a>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">FORM 4 TAPE</span>
          <h3 class="unavail-title lab">No Insider Transactions Recorded</h3>
          <p class="unavail-desc">No Form 4 open market insider transactions match the selected criteria for {{ symbol }}.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>SEC EDGAR Direct XML / Form 4 Feed</strong></span>
          </div>
        </div>
      </Panel>

      <!-- Strategy Backtest Card -->
      <Panel label="Quantitative Insider Purchases Strategy" index="I3" meta="Hypothetical Systematic Model">
        <div v-if="insData?.strategy" class="strategy-backtest-card">
          <div class="strat-hero">
            <div>
              <h3 class="strat-title lab">{{ insData.strategy.name || 'Insider Purchases Strategy' }}</h3>
              <p class="strat-desc label dim">{{ insData.strategy.description || 'Systematic replication of multi-officer Form 4 cluster purchases.' }}</p>
            </div>
            <div class="strat-cagr">
              <span class="label dim">CAGR</span>
              <strong class="cagr-fig fig pos">{{ insData.strategy.cagr != null ? signedPct(insData.strategy.cagr) : DASH }}</strong>
            </div>
          </div>
          <div class="strat-metrics-grid">
            <Readout label="30D Return" :value="signedPct(insData.strategy.return_30d)" :tone="tone(insData.strategy.return_30d)" size="sm" />
            <Readout label="1Y Return" :value="signedPct(insData.strategy.return_1y)" :tone="tone(insData.strategy.return_1y)" size="sm" />
            <Readout label="Max Drawdown" :value="pct(insData.strategy.max_drawdown)" tone="neg" size="sm" />
            <Readout label="Sharpe" :value="insData.strategy.sharpe != null ? num(insData.strategy.sharpe, 2) : DASH" tone="pos" size="sm" />
            <Readout label="Win Rate" :value="insData.strategy.win_rate != null ? pct(insData.strategy.win_rate, 1) : DASH" tone="pos" size="sm" />
            <Readout label="Alpha" :value="signedPct(insData.strategy.alpha)" tone="pos" size="sm" />
            <Readout label="Beta" :value="insData.strategy.beta != null ? num(insData.strategy.beta, 2) : DASH" size="sm" />
            <Readout label="Total Trades" :value="insData.strategy.total_trades != null ? String(insData.strategy.total_trades) : DASH" size="sm" />
          </div>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">BACKTEST MATRIX</span>
          <h3 class="unavail-title lab">Insider Model Backtest Unavailable</h3>
          <p class="unavail-desc">Quantitative backtest metrics are not available for this symbol configuration.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>Systematic Signal Engine</strong></span>
          </div>
        </div>
      </Panel>
    </section>

    <!-- ===================================================================== -->
    <!-- TAB 5: INSTITUTIONS                                                   -->
    <!-- ===================================================================== -->
    <section v-else-if="activeTab === 'institutions'" class="tab-content institutions-layout">
      <!-- Institutional KPIs Strip -->
      <div v-if="ownData?.top_institutions?.length" class="insider-kpis-strip">
        <div class="kpi-card">
          <span class="kpi-lbl label">Total Institutional Value</span>
          <strong class="kpi-val fig pos">{{ formatBigUsd(institutionKpis.totalValueUsd) }}</strong>
        </div>
        <div class="kpi-card">
          <span class="kpi-lbl label">Institutional Ownership</span>
          <strong class="kpi-val fig">{{ institutionKpis.reportedInstPct != null ? `${institutionKpis.reportedInstPct}%` : DASH }}</strong>
        </div>
        <div class="kpi-card">
          <span class="kpi-lbl label">Top 5 Concentration</span>
          <strong class="kpi-val fig">{{ institutionKpis.top5Pct }}%</strong>
        </div>
        <div class="kpi-card">
          <span class="kpi-lbl label">Reporting 13F Holders</span>
          <strong class="kpi-val fig">{{ institutionKpis.countLabel }}</strong>
        </div>
      </div>

      <!-- 13F Top Institutional Holders with Search & Pagination -->
      <Panel
        label="Top Institutional Owners (13F Filings)"
        index="O1"
        :meta="institutionsPanelMeta"
      >
        <div class="institutions-toolbar">
          <div class="table-search-box">
            <span class="search-icon">⌕</span>
            <input
              v-model="institutionSearchQuery"
              class="filter-search-input"
              placeholder="Search institution name (e.g. Vanguard, BlackRock, Citadel)..."
              @input="institutionPage = 1"
            />
          </div>
          <div class="toolbar-controls">
            <div class="seg">
              <span class="seg-label label dim">Per Page:</span>
              <button
                v-for="size in ([10, 25, 50, 'all'] as const)"
                :key="size"
                class="seg-b label"
                :class="{ on: institutionPageSize === size }"
                @click="institutionPageSize = size; institutionPage = 1"
              >
                {{ size === 'all' ? 'All' : size }}
              </button>
            </div>
          </div>
        </div>

        <div v-if="paginatedInstitutions.length" class="table-scroll-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label sortable" @click="setInstitutionSort('holder')">
                  Institution <span class="sort-arr">{{ institutionSortField === 'holder' ? (institutionSortAsc ? '↑' : '↓') : '↕' }}</span>
                </th>
                <th class="label sortable" @click="setInstitutionSort('shares')">
                  Shares Held <span class="sort-arr">{{ institutionSortField === 'shares' ? (institutionSortAsc ? '↑' : '↓') : '↕' }}</span>
                </th>
                <th class="label sortable" @click="setInstitutionSort('change')">
                  Last Quarter <span class="sort-arr">{{ institutionSortField === 'change' ? (institutionSortAsc ? '↑' : '↓') : '↕' }}</span>
                </th>
                <th class="label sortable" @click="setInstitutionSort('pct_out')">
                  % Outstanding <span class="sort-arr">{{ institutionSortField === 'pct_out' ? (institutionSortAsc ? '↑' : '↓') : '↕' }}</span>
                </th>
                <th class="label sortable" @click="setInstitutionSort('value')">
                  Market Value <span class="sort-arr">{{ institutionSortField === 'value' ? (institutionSortAsc ? '↑' : '↓') : '↕' }}</span>
                </th>
                <th class="label sortable" @click="setInstitutionSort('date')">
                  Reported Date <span class="sort-arr">{{ institutionSortField === 'date' ? (institutionSortAsc ? '↑' : '↓') : '↕' }}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(inst, idx) in paginatedInstitutions" :key="idx">
                <td class="lab bold">
                  <div class="inst-name-cell">
                    <span class="inst-rank fig dim">#{{ (institutionPageSize === 'all' ? 0 : (institutionPage - 1) * Number(institutionPageSize)) + idx + 1 }}</span>
                    <span>{{ inst.holder }}</span>
                  </div>
                </td>
                <td class="fig">{{ inst.shares != null ? inst.shares.toLocaleString() : DASH }}</td>
                <td class="fig" :class="holderChangeTone(inst)">{{ formatHolderChange(inst) }}</td>
                <td class="fig">
                  <div class="pct-cell">
                    <span>{{ inst.pct_out != null ? `${inst.pct_out}%` : DASH }}</span>
                    <div class="pct-bar-track">
                      <div class="pct-bar-fill" :style="{ width: `${holderPctBarWidth(inst.pct_out, institutionPctScale) * 100}%` }" />
                    </div>
                  </div>
                </td>
                <td class="fig pos">{{ formatBigUsd(inst.value) }}</td>
                <td class="dim fig">{{ inst.date_reported || DASH }}</td>
              </tr>
            </tbody>
          </table>

          <!-- Pagination Bar -->
          <div v-if="institutionPageSize !== 'all' && totalInstitutionPages > 1" class="pagination-bar">
            <span class="page-info label dim">
              Showing {{ (institutionPage - 1) * Number(institutionPageSize) + 1 }}–{{ Math.min(filteredInstitutions.length, institutionPage * Number(institutionPageSize)) }} of {{ filteredInstitutions.length }}
            </span>
            <div class="page-nav-btns">
              <button
                type="button"
                class="seg-b label"
                :disabled="institutionPage <= 1"
                @click="institutionPage = Math.max(1, institutionPage - 1)"
              >
                ← Prev
              </button>
              <span class="page-indicator fig">{{ institutionPage }} / {{ totalInstitutionPages }}</span>
              <button
                type="button"
                class="seg-b label"
                :disabled="institutionPage >= totalInstitutionPages"
                @click="institutionPage = Math.min(totalInstitutionPages, institutionPage + 1)"
              >
                Next →
              </button>
            </div>
          </div>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">13F HOLDINGS</span>
          <h3 class="unavail-title lab">No Institutional Records Match Criteria</h3>
          <p class="unavail-desc">No 13F institutional holdings matched the search filter for {{ symbol }}.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>SEC EDGAR Form 13F-HR Feeds</strong></span>
          </div>
        </div>
      </Panel>

      <!-- Top Mutual Fund & ETF Holders -->
      <Panel label="Top Mutual Fund & ETF Holders" index="O2" :meta="`${ownData?.top_funds?.length || 0} Funds`">
        <div v-if="ownData?.top_funds?.length" class="table-scroll-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label">Fund / ETF Name</th>
                <th class="label">Shares Held</th>
                <th class="label">Last Quarter</th>
                <th class="label">% Outstanding</th>
                <th class="label">Market Value</th>
                <th class="label">Reported Date</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(fund, idx) in ownData.top_funds" :key="idx">
                <td class="lab bold">{{ fund.holder }}</td>
                <td class="fig">{{ fund.shares != null ? fund.shares.toLocaleString() : DASH }}</td>
                <td class="fig" :class="holderChangeTone(fund)">{{ formatHolderChange(fund) }}</td>
                <td class="fig">
                  <div class="pct-cell">
                    <span>{{ fund.pct_out != null ? `${fund.pct_out}%` : DASH }}</span>
                    <div class="pct-bar-track">
                      <div class="pct-bar-fill" :style="{ width: `${holderPctBarWidth(fund.pct_out, fundPctScale) * 100}%` }" />
                    </div>
                  </div>
                </td>
                <td class="fig pos">{{ formatBigUsd(fund.value) }}</td>
                <td class="dim fig">{{ fund.date_reported || DASH }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">MUTUAL FUND HOLDINGS</span>
          <h3 class="unavail-title lab">Mutual Fund Holdings Unavailable</h3>
          <p class="unavail-desc">Registered fund portfolio holdings are not reported for {{ symbol }}.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>SEC EDGAR N-PORT Disclosures</strong></span>
          </div>
        </div>
      </Panel>
    </section>

    <!-- ===================================================================== -->
    <!-- TAB 6: GOVERNMENT                                                     -->
    <!-- ===================================================================== -->
    <section v-else-if="activeTab === 'government'" class="tab-content government-layout">
      <!-- Congressional Trades -->
      <Panel label="Congressional Trading Activity" index="G1" :meta="`${govData?.congress?.length || 0} Disclosures`">
        <div v-if="govData?.congress?.length" class="table-scroll-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label">Politician</th>
                <th class="label">Party & Chamber</th>
                <th class="label">Transaction Date</th>
                <th class="label">Filing Date</th>
                <th class="label">Type</th>
                <th class="label">Amount Range</th>
                <th class="label">Source</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(c, idx) in govData.congress" :key="idx">
                <td class="lab bold">{{ c.politician_name }}</td>
                <td>
                  <span class="kind label" :class="c.party === 'Democrat' ? 'dem' : 'rep'">
                    {{ c.party || DASH }} · {{ c.chamber || DASH }} ({{ c.state || DASH }})
                  </span>
                </td>
                <td class="dim fig">{{ c.transaction_date || DASH }}</td>
                <td class="dim fig">{{ c.filing_date || DASH }}</td>
                <td>
                  <span class="kind label" :class="c.type === 'Purchase' ? 'pos' : 'neg'">
                    {{ c.type ? c.type.toUpperCase() : DASH }}
                  </span>
                </td>
                <td class="fig bold">{{ c.amount_range || DASH }}</td>
                <td>
                  <a v-if="c.source_url" :href="c.source_url" target="_blank" rel="noopener" class="label link">STOCK Act</a>
                  <span v-else class="dim">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">STOCK ACT DISCLOSURES</span>
          <h3 class="unavail-title lab">No Congressional Trades Disclosed for {{ symbol }}</h3>
          <p class="unavail-desc">No U.S. House or Senate financial disclosures found for this symbol.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>House & Senate Financial Disclosures (STOCK Act)</strong></span>
          </div>
        </div>
      </Panel>

      <!-- Corporate Lobbying -->
      <Panel label="Corporate Lobbying Disclosures" index="G2" :meta="govData?.lobbying?.total_spend_annual != null ? `Annual Spend: ${formatBigUsd(govData.lobbying.total_spend_annual)}` : DASH">
        <div v-if="govData?.lobbying?.filings?.length" class="table-scroll-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label">Date</th>
                <th class="label">Amount</th>
                <th class="label">Issue Area</th>
                <th class="label">Specific Policy Description</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(lob, idx) in govData.lobbying.filings" :key="idx">
                <td class="dim fig">{{ lob.date || DASH }}</td>
                <td class="fig bold">{{ formatBigUsd(lob.amount) }}</td>
                <td class="lab pos">{{ lob.issue || DASH }}</td>
                <td class="dim">{{ lob.description || DASH }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">LOBBYING DISCLOSURES</span>
          <h3 class="unavail-title lab">No Corporate Lobbying Filings for {{ symbol }}</h3>
          <p class="unavail-desc">No Lobbying Disclosure Act (LDA) filings on record with the Senate Office of Public Records.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>Senate LDA Database</strong></span>
          </div>
        </div>
      </Panel>

      <!-- Federal Government Contracts -->
      <Panel label="Federal Government Contracts & Grants" index="G3" :meta="`${govData?.contracts?.length || 0} Awards`">
        <div v-if="govData?.contracts?.length" class="table-scroll-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label">Agency</th>
                <th class="label">Award Date</th>
                <th class="label">Contract Value</th>
                <th class="label">Award Type</th>
                <th class="label">Description</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(con, idx) in govData.contracts" :key="idx">
                <td class="lab bold">{{ con.agency || DASH }}</td>
                <td class="dim fig">{{ con.date || DASH }}</td>
                <td class="fig pos bold">{{ formatBigUsd(con.amount) }}</td>
                <td class="label">{{ con.contract_type || DASH }}</td>
                <td class="dim">{{ con.description || DASH }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">FEDERAL CONTRACTS</span>
          <h3 class="unavail-title lab">No Federal Contract Awards for {{ symbol }}</h3>
          <p class="unavail-desc">No prime agency awards or federal contract obligations recorded in the current fiscal window.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>USASpending.gov Open API</strong></span>
          </div>
        </div>
      </Panel>

      <!-- U.S. Patent Grants -->
      <Panel label="U.S. Patent Grants" index="G4" :meta="`${govData?.patents?.length || 0} Patents`">
        <div v-if="govData?.patents?.length" class="table-scroll-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label">Patent #</th>
                <th class="label">Title</th>
                <th class="label">Grant Date</th>
                <th class="label">Abstract</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(pat, idx) in govData.patents" :key="idx">
                <td class="fig bold">{{ pat.patent_number || DASH }}</td>
                <td class="lab bold">{{ pat.title || DASH }}</td>
                <td class="dim fig">{{ pat.grant_date || DASH }}</td>
                <td class="dim">{{ pat.abstract || DASH }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">USPTO PATENTS</span>
          <h3 class="unavail-title lab">No USPTO Patent Grants Found for {{ symbol }}</h3>
          <p class="unavail-desc">No patent grants found assigned to the corporate entity in the USPTO open database.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>USPTO PatentsView Database</strong></span>
          </div>
        </div>
      </Panel>
    </section>

    <!-- ===================================================================== -->
    <!-- TAB 7: COMPENSATION                                                   -->
    <!-- ===================================================================== -->
    <section v-else-if="activeTab === 'compensation'" class="tab-content compensation-layout">
      <!-- Executive Compensation Overview -->
      <Panel label="Executive Compensation Summary" index="C1" meta="SEC DEF 14A Proxy Filings">
        <div class="comp-summary-strip">
          <div class="comp-summary-card">
            <span class="label dim">Highest Paid Executive</span>
            <strong class="comp-stat-val lab">{{ profile?.compensation?.highest_paid_name || DASH }}</strong>
            <span class="comp-stat-sub fig pos">{{ profile?.compensation?.highest_paid_total != null ? `${formatBigUsd(profile.compensation.highest_paid_total)} / Year` : DASH }}</span>
          </div>
          <div class="comp-summary-card">
            <span class="label dim">Median Employee Pay</span>
            <strong class="comp-stat-val fig">{{ formatBigUsd(profile?.compensation?.median_employee_pay) }}</strong>
            <span class="comp-stat-sub label dim">Annual Estimated Compensation</span>
          </div>
          <div class="comp-summary-card">
            <span class="label dim">CEO Pay Ratio</span>
            <strong class="comp-stat-val fig">{{ profile?.compensation?.ceo_pay_ratio != null ? `${profile.compensation.ceo_pay_ratio} : 1` : DASH }}</strong>
            <span class="comp-stat-sub label dim">Ratio to Median Employee</span>
          </div>
        </div>

        <div v-if="profile?.compensation?.rows?.length" class="table-scroll-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label">Executive Name</th>
                <th class="label">Role / Title</th>
                <th class="label">Base Salary</th>
                <th class="label">Bonus</th>
                <th class="label">Stock Awards</th>
                <th class="label">Total Compensation</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(exec, idx) in profile.compensation.rows" :key="idx">
                <td class="lab bold">{{ exec.name }}</td>
                <td class="dim">{{ exec.role || DASH }}</td>
                <td class="fig">{{ formatBigUsd(exec.salary) }}</td>
                <td class="fig">{{ formatBigUsd(exec.bonus) }}</td>
                <td class="fig">{{ formatBigUsd(exec.stock_awards) }}</td>
                <td class="fig pos bold">{{ formatBigUsd(exec.total_compensation) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">PROXY DISCLOSURES</span>
          <h3 class="unavail-title lab">Executive Officer Disclosures Unavailable</h3>
          <p class="unavail-desc">Detailed executive officer compensation data could not be parsed from DEF 14A proxy statements for {{ symbol }}.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>SEC EDGAR DEF 14A Disclosures</strong></span>
          </div>
        </div>
      </Panel>
    </section>

    <!-- ===================================================================== -->
    <!-- TAB 8: OWNERSHIP                                                      -->
    <!-- ===================================================================== -->
    <section v-else-if="activeTab === 'ownership'" class="tab-content ownership-layout">
      <!-- Ownership Structure Breakdown -->
      <Panel label="Ownership Structure & Float Distribution" index="W1" meta="Shareholder Registry">
        <div v-if="ownData?.breakdown" class="ownership-distribution-card">
          <div class="ownership-bars-row">
            <div
              v-if="ownData.breakdown.institutional_pct"
              class="own-bar-seg inst"
              :style="{ width: `${ownData.breakdown.institutional_pct}%` }"
            >
              <span class="bar-lbl label">Institutions {{ ownData.breakdown.institutional_pct }}%</span>
            </div>
            <div
              v-if="ownData.breakdown.insider_pct"
              class="own-bar-seg insider"
              :style="{ width: `${ownData.breakdown.insider_pct}%` }"
            >
              <span class="bar-lbl label">Insiders {{ ownData.breakdown.insider_pct }}%</span>
            </div>
            <div
              v-if="ownData.breakdown.retail_float_pct"
              class="own-bar-seg retail"
              :style="{ width: `${ownData.breakdown.retail_float_pct}%` }"
            >
              <span class="bar-lbl label">Retail Float {{ ownData.breakdown.retail_float_pct }}%</span>
            </div>
          </div>

          <div class="ownership-stats-grid">
            <Readout label="Institutional Ownership" :value="ownData.breakdown.institutional_pct != null ? `${ownData.breakdown.institutional_pct}%` : DASH" size="sm" />
            <Readout label="Insider Ownership" :value="ownData.breakdown.insider_pct != null ? `${ownData.breakdown.insider_pct}%` : DASH" size="sm" />
            <Readout label="Retail / Public Float" :value="ownData.breakdown.retail_float_pct != null ? `${ownData.breakdown.retail_float_pct}%` : DASH" size="sm" />
            <Readout label="Shares Outstanding" :value="compact(ownData.breakdown.shares_outstanding)" size="sm" />
            <Readout label="Float Shares" :value="compact(ownData.breakdown.float_shares)" size="sm" />
            <Readout label="Short % of Float" :value="ownData.short_interest?.short_pct_of_float != null ? `${ownData.short_interest.short_pct_of_float}%` : DASH" size="sm" />
            <Readout label="Days to Cover" :value="ownData.short_interest?.days_to_cover != null ? `${ownData.short_interest.days_to_cover}d` : DASH" size="sm" />
            <Readout label="Prior Month Short" :value="ownData.short_interest?.shares_short_prior_month != null ? compact(ownData.short_interest.shares_short_prior_month) : DASH" size="sm" />
          </div>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">SHAREHOLDER REGISTRY</span>
          <h3 class="unavail-title lab">Ownership Structure Breakdown Unavailable</h3>
          <p class="unavail-desc">Float distribution between institutional, insider, and public retail holders is not available for {{ symbol }}.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>13F Filings & Exchange Float Registry</strong></span>
          </div>
        </div>
      </Panel>

      <!-- Institutional Owners in Ownership Tab -->
      <Panel label="Top Institutional Owners (13F Filings)" index="W2" :meta="ownershipInstitutionsMeta">
        <div v-if="ownData?.top_institutions?.length" class="table-scroll-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label">Institution</th>
                <th class="label">Shares Held</th>
                <th class="label">Last Quarter</th>
                <th class="label">% Outstanding</th>
                <th class="label">Market Value</th>
                <th class="label">Reported Date</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(inst, idx) in ownData.top_institutions" :key="idx">
                <td class="lab bold">{{ inst.holder }}</td>
                <td class="fig">{{ inst.shares != null ? inst.shares.toLocaleString() : DASH }}</td>
                <td class="fig" :class="holderChangeTone(inst)">{{ formatHolderChange(inst) }}</td>
                <td class="fig">
                  <div class="pct-cell">
                    <span>{{ inst.pct_out != null ? `${inst.pct_out}%` : DASH }}</span>
                    <div class="pct-bar-track">
                      <div class="pct-bar-fill" :style="{ width: `${holderPctBarWidth(inst.pct_out, ownershipInstitutionPctScale) * 100}%` }" />
                    </div>
                  </div>
                </td>
                <td class="fig pos">{{ formatBigUsd(inst.value) }}</td>
                <td class="dim fig">{{ inst.date_reported || DASH }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">13F HOLDINGS</span>
          <h3 class="unavail-title lab">Institutional Ownership Disclosures Unavailable</h3>
          <p class="unavail-desc">13F institutional holding records could not be retrieved for {{ symbol }}.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>SEC EDGAR Form 13F-HR Feeds</strong></span>
          </div>
        </div>
      </Panel>

      <!-- Top Mutual Fund & ETF Holders in Ownership Tab -->
      <Panel label="Top Mutual Fund & ETF Holders" index="W3" :meta="`${ownData?.top_funds?.length || 0} Funds`">
        <div v-if="ownData?.top_funds?.length" class="table-scroll-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label">Fund / ETF Name</th>
                <th class="label">Shares Held</th>
                <th class="label">Last Quarter</th>
                <th class="label">% Outstanding</th>
                <th class="label">Market Value</th>
                <th class="label">Reported Date</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(fund, idx) in ownData.top_funds" :key="idx">
                <td class="lab bold">{{ fund.holder }}</td>
                <td class="fig">{{ fund.shares != null ? fund.shares.toLocaleString() : DASH }}</td>
                <td class="fig" :class="holderChangeTone(fund)">{{ formatHolderChange(fund) }}</td>
                <td class="fig">
                  <div class="pct-cell">
                    <span>{{ fund.pct_out != null ? `${fund.pct_out}%` : DASH }}</span>
                    <div class="pct-bar-track">
                      <div class="pct-bar-fill" :style="{ width: `${holderPctBarWidth(fund.pct_out, fundPctScale) * 100}%` }" />
                    </div>
                  </div>
                </td>
                <td class="fig pos">{{ formatBigUsd(fund.value) }}</td>
                <td class="dim fig">{{ fund.date_reported || DASH }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">MUTUAL FUND HOLDINGS</span>
          <h3 class="unavail-title lab">Mutual Fund Holdings Unavailable</h3>
          <p class="unavail-desc">Registered fund portfolio holdings are not reported for {{ symbol }}.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>SEC EDGAR N-PORT Disclosures</strong></span>
          </div>
        </div>
      </Panel>
    </section>

    <!-- ===================================================================== -->
    <!-- TAB 9: NEWS & SEC FILINGS                                             -->
    <!-- ===================================================================== -->
    <section v-else-if="activeTab === 'news'" class="tab-content news-layout">
      <Panel label="SEC EDGAR Official Filings" index="N1" :meta="`${secRows.length} Filings`">
        <LoadingState v-if="sentimentRes.loading.value && !secRows.length" label="Loading EDGAR Filings…" />
        <div v-else-if="!secRows.length" class="institutional-unavailable-container">
          <span class="unavail-eyebrow label dim">EDGAR SUBMISSIONS</span>
          <h3 class="unavail-title lab">No SEC Filings in Recent Window</h3>
          <p class="unavail-desc">No watched SEC EDGAR regulatory filings (10-K, 10-Q, 8-K) were recorded for {{ symbol }} in the observation window.</p>
          <div class="unavail-meta label dim">
            <span>Source: <strong>SEC EDGAR Direct Submissions Feed</strong></span>
          </div>
        </div>
        <div v-else class="table-scroll-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label">Kind</th>
                <th class="label">Form</th>
                <th class="label">Filing Date</th>
                <th class="label">Description</th>
                <th class="label">EDGAR Doc</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in secRows" :key="`${row.form}-${row.filed}-${i}`">
                <td><span class="kind label" :class="`kind-${row.kind ?? 'unknown'}`">{{ row.kind ? row.kind.toUpperCase() : DASH }}</span></td>
                <td class="fig bold">{{ row.form || DASH }}</td>
                <td class="dim fig">{{ row.filed || DASH }}</td>
                <td class="dim">{{ row.description || DASH }}</td>
                <td>
                  <a v-if="row.url" :href="row.url" target="_blank" rel="noopener" class="label link">Open SEC Filing</a>
                  <span v-else class="dim">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>
    </section>

    <!-- ===================================================================== -->
    <!-- TAB 10: COMPARE                                                       -->
    <!-- ===================================================================== -->
    <section v-else-if="activeTab === 'compare'" class="tab-content compare-layout">
      <!-- Basket Toolbar -->
      <div class="compare-toolbar">
        <div class="basket-chips-row">
          <span class="label dim">Active Basket ({{ basket.length }}/8):</span>
          <span
            v-for="sym in basket"
            :key="sym"
            class="basket-chip"
            :class="{ active: sym === symbol }"
          >
            <strong class="chip-sym fig" @click="select(sym)">{{ sym }}</strong>
            <button type="button" class="chip-rm label" title="Remove" @click.stop="toggleBasket(sym)">×</button>
          </span>
        </div>
        <div class="basket-add-row">
          <span class="label dim">Quick Add:</span>
          <button
            v-for="bench in ['SPY', 'QQQ', 'IWM', 'DIA', 'AAPL', 'NVDA'].filter((b) => !basket.includes(b))"
            :key="bench"
            type="button"
            class="btn-action label"
            @click="toggleBasket(bench)"
          >
            + {{ bench }}
          </button>
        </div>
      </div>

      <div class="compare-grid">
        <Panel label="Factor Loadings" index="C1" :meta="symbol">
          <ul class="facs">
            <li v-for="f in factorRows" :key="f.k" class="fac">
              <div class="f-top">
                <span class="label f-lab" :title="f.desc">{{ f.label }}</span>
                <div class="f-val-wrap">
                  <span class="fig f-val" :class="f.toneClass">{{ f.formatted }}</span>
                  <span v-if="f.sub" class="f-sub label">{{ f.sub }}</span>
                </div>
              </div>
              <span class="f-bar" aria-hidden="true">
                <i
                  :style="{
                    width: `${f.barPct}%`,
                    background: f.k === 'liq' ? 'var(--phosphor)' : (Number(f.v ?? 0) >= 0 ? 'var(--long)' : 'var(--short)'),
                  }"
                />
              </span>
            </li>
          </ul>
        </Panel>

        <Panel label="Multi-Symbol Basket Performance & Correlation" index="C2" :meta="`${basket.length} Symbols · ${win.toUpperCase()}`">
          <div v-if="basket.length < 2" class="compare-empty-container">
            <span class="unavail-eyebrow label dim">COMPARATIVE ANALYSIS</span>
            <h3 class="unavail-title lab">Select at Least 2 Tickers to Compare</h3>
            <p class="unavail-desc">Select at least 2 tickers to display comparative metrics, correlation matrix, and normalized price trajectories.</p>
            <div class="compare-quick-actions">
              <button v-if="symbol && !basket.includes(symbol)" type="button" class="btn-action label" @click="toggleBasket(symbol)">
                + ADD {{ symbol }}
              </button>
              <button v-if="!basket.includes('SPY')" type="button" class="btn-action label" @click="toggleBasket('SPY')">
                + ADD SPY
              </button>
              <button v-if="!basket.includes('QQQ')" type="button" class="btn-action label" @click="toggleBasket('QQQ')">
                + ADD QQQ
              </button>
            </div>
          </div>
          <p v-else-if="cmpErr" class="err">{{ cmpErr }}</p>
          <LoadingState v-else-if="!cmp" label="Loading compare…" />
          <template v-else-if="cmp">
            <div class="compare-perf-table">
              <div class="leg-head label">
                <span>Symbol</span><span>Trajectory</span><span>Window Ret</span><span>Sharpe</span><span>Max DD</span><span />
              </div>
              <ul class="legend">
                <li v-for="sym in cmpSyms" :key="sym" class="leg">
                  <button type="button" class="leg-sym fig" @click="select(sym)">{{ sym }}</button>
                  <svg class="spark" viewBox="0 0 120 22" preserveAspectRatio="none" aria-hidden="true">
                    <path
                      v-if="cmpSparks[sym]"
                      :d="cmpSparks[sym]"
                      fill="none"
                      stroke-width="1.25"
                      vector-effect="non-scaling-stroke"
                      :stroke="(cmp.stats[sym]?.chg_window_pct ?? 0) >= 0 ? 'var(--long)' : 'var(--short)'"
                    />
                  </svg>
                  <span class="fig leg-ret" :class="tone(cmp.stats[sym]?.chg_window_pct)">
                    {{ signedPct(cmp.stats[sym]?.chg_window_pct, 1) }}
                  </span>
                  <span class="fig leg-sh">{{ cmp.stats[sym]?.sharpe == null ? DASH : num(cmp.stats[sym]?.sharpe, 2) }}</span>
                  <span class="fig leg-dd neg">{{ pct(cmp.stats[sym]?.max_drawdown_pct, 0) }}</span>
                  <button type="button" class="leg-x label" title="Remove" @click="toggleBasket(sym)">×</button>
                </li>
              </ul>
            </div>

            <div class="corr-section">
              <h3 class="sub-lab label">Pearson Return Correlation Matrix</h3>
              <div class="corr-table-wrap">
                <div class="corr" :style="{ '--n': cmpSyms.length }">
                  <span class="corr-corner" />
                  <span v-for="c in cmpSyms" :key="`ch${c}`" class="label corr-h">{{ c }}</span>
                  <template v-for="r in cmpSyms" :key="`row${r}`">
                    <span class="label corr-h-row">{{ r }}</span>
                    <span
                      v-for="c in cmpSyms"
                      :key="`${r}-${c}`"
                      class="fig corr-c"
                      :style="corrStyle(cmp.correlation[r]?.[c] ?? NaN)"
                    >
                      {{ num(cmp.correlation[r]?.[c], 2) }}
                    </span>
                  </template>
                </div>
              </div>
            </div>
          </template>
        </Panel>
      </div>
    </section>
  </div>
</template>

<style scoped>
.market-cockpit {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  min-width: 0;
}

/* ---- Masthead & Header -------------------------------------------------- */
.ticker-masthead {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.masthead-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s4);
}
.ticker-search-strip {
  position: relative;
  flex: 1 1 220px;
  min-width: 180px;
  max-width: 320px;
}

.ticker-brand {
  display: flex;
  align-items: center;
  gap: var(--s3);
}

.ticker-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 6px 12px;
  background: var(--void);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
}

.ticker-badge-sym {
  font-size: var(--t-h3, 20px);
  font-weight: 700;
  color: var(--phosphor);
  letter-spacing: 0.05em;
}

.ticker-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ticker-title-row {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.company-name {
  margin: 0;
  font-size: var(--t-base, 16px);
  font-weight: 600;
  color: var(--ink);
}

.ticker-meta-dot {
  color: var(--ink-dim);
}

.ticker-sec-tag {
  color: var(--ink-soft);
  font-size: var(--t-tiny, 11px);
}

.ticker-ind-tag {
  font-size: var(--t-tiny, 11px);
}

.ticker-sub-row {
  display: flex;
  align-items: center;
  gap: var(--s3);
  font-size: var(--t-tiny, 11px);
}

.ticker-price-block {
  display: flex;
  align-items: center;
  gap: var(--s5);
  flex-wrap: wrap;
}

.price-hero-loading {
  display: flex;
  align-items: center;
  height: 36px;
}

.loading-pulse-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  background: var(--void);
  border: var(--hair) solid var(--rule-hi);
  color: var(--phosphor);
  border-radius: var(--r-sm);
  font-size: var(--t-micro, 10px);
  letter-spacing: var(--track-label);
  animation: pulse-sync 1.5s ease-in-out infinite;
}

@keyframes pulse-sync {
  0%, 100% { opacity: 0.6; }
  50% { opacity: 1; }
}

.price-hero {
  display: flex;
  align-items: baseline;
  gap: var(--s3);
}

.last-price {
  font-size: var(--t-h2, 26px);
  font-weight: 700;
  letter-spacing: -0.02em;
}

.price-changes {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.chg-val {
  font-size: var(--t-small, 14px);
  font-weight: 600;
}

.ticker-actions {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.btn-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  color: var(--ink-soft);
  font-size: var(--t-tiny, 11px);
  text-decoration: none;
  cursor: pointer;
  border-radius: var(--r-sm);
  transition: border-color var(--dur-fast), color var(--dur-fast);
}

.btn-action:hover {
  border-color: var(--rule-hi);
  color: var(--ink);
}

.btn-action.on, .pin-btn.on {
  border-color: var(--phosphor);
  color: var(--phosphor);
}

/* Search input */
.search-input-wrap {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: 6px 12px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.search-glyph {
  color: var(--ink-dim);
  font-size: 14px;
}

.search-busy {
  color: var(--phosphor);
  font-size: 12px;
  animation: pulse-sync 1s ease-in-out infinite;
}

.search-input {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--ink);
  font-family: inherit;
  font-size: var(--t-small, 13px);
  outline: none;
}

.search-dropdown-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
  z-index: 50;
  display: flex;
  flex-direction: column;
}

.search-drop-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: transparent;
  border: none;
  border-bottom: var(--hair) solid var(--rule);
  color: var(--ink);
  cursor: pointer;
  text-align: left;
}

.search-drop-item:hover {
  background: var(--void);
}

/* Sync Strip */
.ticker-sync-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--void);
  border-radius: var(--r-sm);
  border: var(--hair) solid var(--rule-faint);
  font-size: var(--t-micro, 10px);
  color: var(--ink-soft);
  letter-spacing: var(--track-label);
}

.sync-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--phosphor);
  /* no glow — desk system forbids box-shadow: 0 0 */
  animation: pulse-sync 1s ease-in-out infinite;
}

.sync-text strong {
  color: var(--phosphor);
}

/* Cockpit Tabs Navigation */
.cockpit-tabs-nav {
  display: flex;
  align-items: center;
  gap: 2px;
  overflow-x: auto;
  border-top: var(--hair) solid var(--rule);
  padding-top: var(--s2);
}

.cockpit-tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--ink-dim);
  cursor: pointer;
  white-space: nowrap;
  font-size: var(--t-small, 13px);
  font-weight: 500;
  transition: color var(--dur-fast), border-color var(--dur-fast);
}

.tab-index {
  font-size: 11px;
  color: var(--ink-dim);
  letter-spacing: 0.04em;
}

.cockpit-tab-btn:hover {
  color: var(--ink);
}

.cockpit-tab-btn.active {
  color: var(--phosphor);
  border-bottom-color: var(--phosphor);
  font-weight: 600;
}

.cockpit-tab-btn.active .tab-index {
  color: var(--phosphor);
}

/* ---- Layouts ------------------------------------------------------------ */
.tab-content {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.overview-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--s4);
}

.overview-chart-panel {
  grid-column: 1;
  min-width: 0;
}

.overview-sidebar {
  grid-column: 1;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--s4);
}

.overview-cards-grid {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--s4);
}

.overview-full-span {
  grid-column: 1 / -1;
}

/* Quick Cards */
.quick-card {
  padding: var(--s4);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  transition: border-color var(--dur-fast), background var(--dur-fast);
}

.quick-card:hover {
  border-color: var(--rule-hi);
  background: var(--panel-hi);
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-title {
  font-size: var(--t-small, 13px);
  font-weight: 600;
  color: var(--ink);
}

.card-link {
  font-size: var(--t-tiny, 10px);
  color: var(--phosphor);
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.card-kpi-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

/* Smart Score */
.smart-score-card {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.score-dial {
  display: flex;
  align-items: center;
  gap: var(--s4);
}

.score-circle {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 2px;
  width: 64px;
  height: 64px;
  background: var(--void);
  border: 2px solid var(--rule-hi);
  border-radius: 50%;
  padding-top: 14px;
  flex-shrink: 0;
  transition: all var(--dur-fast);
}

.score-circle.pos {
  border-color: var(--phosphor);
  /* no glow — desk system forbids box-shadow: 0 0 */
}

.score-circle.mid {
  border-color: var(--warn);
}

.score-circle.neg {
  border-color: var(--short);
}

.score-num {
  font-size: var(--t-fig);
  font-weight: 700;
  color: var(--ink);
}

.score-circle.pos .score-num { color: var(--phosphor); }
.score-circle.mid .score-num { color: var(--warn); }
.score-circle.neg .score-num { color: var(--short); }

.score-max {
  font-size: 10px;
}

.score-breakdown {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.score-bar-row {
  display: grid;
  grid-template-columns: 120px 1fr 24px;
  align-items: center;
  gap: var(--s2);
  font-size: var(--t-tiny, 11px);
}

.score-bar-track {
  height: 4px;
  background: var(--void);
  border-radius: 2px;
  overflow: hidden;
}

.score-bar-fill {
  height: 100%;
  border-radius: 2px;
  background: var(--rule-hi);
  transition: width var(--dur-fast);
}

.score-bar-fill.pos { background: var(--phosphor); }
.score-bar-fill.mid { background: var(--warn); }
.score-bar-fill.neg { background: var(--short); }

/* Bull Bear Grid */
.bull-bear-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s4);
}

.bull-box, .bear-box {
  padding: var(--s4);
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.thesis-header {
  display: flex;
  align-items: center;
  gap: var(--s2);
  font-size: var(--t-small, 13px);
  font-weight: 700;
}

.thesis-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.thesis-item {
  display: flex;
  align-items: flex-start;
  gap: var(--s2);
}

.thesis-text {
  margin: 0;
  font-size: var(--t-small, 13px);
  line-height: 1.45;
  color: var(--ink-soft);
}

/* About Card */
.about-card {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.about-desc {
  margin: 0;
  font-size: var(--t-small, 13px);
  line-height: 1.6;
  color: var(--ink-soft);
}

.about-stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--s4);
  padding-top: var(--s3);
  border-top: var(--hair) solid var(--rule);
}

/* ---- Financials Toolbar & Grid ------------------------------------------- */
.financials-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.fin-statement-selector {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.fin-btn {
  padding: 6px 12px;
  background: transparent;
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  cursor: pointer;
  border-radius: var(--r-sm);
  font-size: var(--t-small, 12px);
  transition: all var(--dur-fast);
}

.fin-btn:hover {
  color: var(--ink);
  border-color: var(--rule-hi);
}

.fin-btn.on {
  background: var(--void);
  color: var(--phosphor);
  border-color: var(--phosphor);
  font-weight: 600;
}

.fin-controls-right {
  display: flex;
  align-items: center;
  gap: var(--s3);
}

.financial-statement-grid {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-small, 13px);
  font-variant-numeric: tabular-nums;
  font-feature-settings: 'tnum' 1;
}

.financial-statement-grid th, .financial-statement-grid td {
  padding: 8px 12px;
  border-bottom: var(--hair) solid var(--rule);
  text-align: right;
}

.financial-statement-grid th:first-child, .financial-statement-grid td:first-child {
  text-align: left;
}

.col-metric {
  width: 320px;
}

.row-header {
  background: var(--void);
  font-weight: 700;
  color: var(--ink);
}

.row-bold {
  font-weight: 600;
  color: var(--ink);
}

.row-total {
  background: var(--void);
  border-top: var(--hair) solid var(--rule-hi);
  border-bottom: 2px solid var(--rule-hi);
  font-weight: 700;
  color: var(--phosphor);
}

.indent-1 .cell-label {
  padding-left: 28px;
  color: var(--ink-soft);
}

.ratios-multiples-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--s4);
}

.ratio-card {
  padding: var(--s3);
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ratio-value {
  font-size: var(--t-display);
}

/* Revenue Breakdown */
.breakdown-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s4);
}

.breakdown-list {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.breakdown-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--s3);
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.breakdown-item-top, .breakdown-item-sub {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.breakdown-progress-track {
  height: 6px;
  background: var(--panel);
  border-radius: 3px;
  overflow: hidden;
}

.breakdown-progress-fill {
  height: 100%;
  background: var(--phosphor);
}

/* Financials Chart Mode Styles */
.fin-chart-card {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  padding: var(--s4);
  background: var(--void);
  border-radius: var(--r-sm);
}

.fin-chart-legend {
  display: flex;
  align-items: center;
  gap: var(--s4);
  flex-wrap: wrap;
  font-size: var(--t-tiny, 11px);
}

.chart-leg-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-soft);
}

.leg-swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}

.leg-swatch.rev { background: var(--phosphor); }
.leg-swatch.gross { background: #5b95b5; }
.leg-swatch.op { background: #c1955e; }
.leg-swatch.net { background: var(--long); }
.leg-swatch.assets { background: var(--phosphor); }
.leg-swatch.liab { background: var(--short); }
.leg-swatch.equity { background: #5b95b5; }
.leg-swatch.ocf { background: var(--phosphor); }
.leg-swatch.fcf { background: var(--long); }
.leg-swatch.capex { background: #c1955e; }

.fin-bars-timeline {
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
  height: 220px;
  padding-top: var(--s3);
  border-bottom: var(--hair) solid var(--rule);
  gap: var(--s3);
}

.fin-timeline-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  height: 100%;
  max-width: 120px;
}

.fin-col-bars {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 4px;
}

.fin-bar {
  flex: 1;
  max-width: 18px;
  border-radius: 2px 2px 0 0;
  transition: height var(--dur-fast);
}

.fin-bar.rev { background: var(--phosphor); }
.fin-bar.gross { background: #5b95b5; }
.fin-bar.op { background: #c1955e; }
.fin-bar.net { background: var(--long); }
.fin-bar.op.neg, .fin-bar.net.neg { background: var(--short); }
.fin-bar.assets { background: var(--phosphor); }
.fin-bar.liab { background: var(--short); }
.fin-bar.equity { background: #5b95b5; }
.fin-bar.ocf { background: var(--phosphor); }
.fin-bar.fcf { background: var(--long); }
.fin-bar.fcf.neg { background: var(--short); }
.fin-bar.capex { background: #c1955e; }

.fin-col-lbl {
  font-size: var(--t-tiny, 11px);
  color: var(--ink);
}

.fin-col-val {
  font-size: var(--t-micro, 10px);
  color: var(--ink-dim);
}

/* Forecast Meter */
.forecast-top-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s4);
}

.price-target-meter-card {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  padding: var(--s3);
  background: var(--void);
  border-radius: var(--r-sm);
}

.pt-values-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.pt-val-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pt-val-item.highlight {
  align-items: center;
}

.pt-num {
  font-size: var(--t-display);
}

.pt-gauge-track {
  position: relative;
  height: 8px;
  background: var(--panel);
  border-radius: 4px;
}

.pt-gauge-range {
  position: absolute;
  height: 100%;
  background: var(--phosphor-wash, rgba(169, 196, 108, 0.15));
  border-left: 2px solid var(--phosphor);
  border-right: 2px solid var(--phosphor);
}

.pt-gauge-current-marker {
  position: absolute;
  top: -4px;
  width: 4px;
  height: 16px;
  background: var(--ink);
  border-radius: 2px;
}

.pt-caption-row {
  display: flex;
  justify-content: space-between;
  font-size: var(--t-tiny, 11px);
}

.rec-distribution-bars {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--s2);
  margin-top: var(--s3);
}

.rec-bar-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 8px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

/* Insiders layout */
.insider-kpis-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--s4);
}

.kpi-card {
  padding: var(--s3);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.quarterly-insiders-chart {
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
  height: 140px;
  padding: var(--s3);
  background: var(--void);
  border-radius: var(--r-sm);
}

.q-bar-column {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  height: 100%;
}

.q-bar-wrapper {
  flex: 1;
  display: flex;
  align-items: flex-end;
  width: 24px;
}

.q-bar {
  width: 100%;
  border-radius: 2px 2px 0 0;
}

.insider-table-filters {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--s3);
  margin-bottom: var(--s3);
}

.filter-search-input {
  padding: 6px 12px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  color: var(--ink);
  font-family: inherit;
  font-size: var(--t-small, 12px);
  border-radius: var(--r-sm);
}

.strategy-backtest-card {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.strat-hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.strat-metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--s3);
}

/* Compensation strip */
.comp-summary-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--s4);
  margin-bottom: var(--s4);
}

.comp-summary-card {
  padding: var(--s4);
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* Ownership */
.ownership-distribution-card {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.ownership-bars-row {
  display: flex;
  height: 28px;
  border-radius: var(--r-sm);
  overflow: hidden;
}

.own-bar-seg {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
}

.own-bar-seg.inst { background: var(--phosphor); color: var(--void); }
.own-bar-seg.insider { background: var(--rule-hi); color: var(--ink); }
.own-bar-seg.retail { background: var(--panel-raise); color: var(--ink-soft); }

.ownership-stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--s4);
}

/* Standardized Institutional Unavailable Container */
.institutional-unavailable-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--s5) var(--s4);
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  gap: var(--s2);
}

.unavail-eyebrow {
  letter-spacing: var(--track-label);
  font-size: var(--t-micro, 10px);
  color: var(--ink-dim);
}

.unavail-title {
  margin: 0;
  font-size: var(--t-base, 15px);
  font-weight: 600;
  color: var(--ink);
}

.unavail-desc {
  margin: 0;
  max-width: 480px;
  font-size: var(--t-small, 13px);
  line-height: 1.5;
  color: var(--ink-soft);
}

.unavail-meta {
  display: flex;
  align-items: center;
  gap: var(--s2);
  margin-top: var(--s2);
  font-size: var(--t-tiny, 11px);
}

/* ---- Overview Chart Panel Controls & Strips --------------------------- */
.switches {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.mkt-refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  font-size: var(--t-micro, 10px);
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: all var(--dur-fast);
}

.mkt-refresh-btn:hover:not(:disabled) {
  color: var(--phosphor);
  border-color: var(--phosphor);
}

.refresh-icon {
  display: inline-block;
  font-size: 12px;
  line-height: 1;
}

.refresh-icon.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  100% { transform: rotate(360deg); }
}

.seg {
  display: inline-flex;
  align-items: center;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  padding: 1px;
  gap: 1px;
}

.seg-b {
  padding: 3px 8px;
  font-size: var(--t-micro, 10px);
  color: var(--ink-dim);
  background: transparent;
  border: none;
  border-radius: calc(var(--r-sm) - 1px);
  cursor: pointer;
  transition: all var(--dur-fast);
  text-transform: uppercase;
}

.seg-b:hover {
  color: var(--ink);
}

.seg-b.on {
  background: var(--panel-raise);
  color: var(--phosphor);
  font-weight: 600;
}

.data-audit-strip {
  display: flex;
  align-items: center;
  gap: var(--s4);
  padding: 8px var(--s4);
  background: var(--void);
  border-bottom: var(--hair) solid var(--rule-faint);
  flex-wrap: wrap;
  font-size: var(--t-tiny, 11px);
}

.audit-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-soft);
}

.audit-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}

.audit-dot.fresh {
  background: var(--long);
  /* no glow — desk system forbids box-shadow: 0 0 */
}

.audit-dot.stale {
  background: var(--warn);
}

.source-badge {
  padding: 1px 6px;
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  font-size: 9px;
  color: var(--ink-dim);
  letter-spacing: 0.06em;
}

.overview-readouts {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  background: var(--panel-hi);
  border-bottom: var(--hair) solid var(--rule-faint);
}

@media (max-width: 900px) {
  .overview-readouts {
    grid-template-columns: repeat(3, 1fr);
  }
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  background: var(--void);
  border-top: var(--hair) solid var(--rule-faint);
}

/* Signal Branch */
.signal-branch-card {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s3);
  background: var(--void);
  border-radius: var(--r-sm);
}

.sig-title-row {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.sig-type {
  font-size: var(--t-micro, 10px);
  color: var(--ink-dim);
}

.sig-side-badge {
  padding: 2px 6px;
  border-radius: var(--r-xs);
  font-size: var(--t-micro, 10px);
  font-weight: 700;
  letter-spacing: 0.04em;
}

.sig-side-badge.pos { background: rgba(34, 197, 94, 0.15); color: var(--long); }
.sig-side-badge.neg { background: rgba(239, 68, 68, 0.15); color: var(--short); }

.state {
  padding: 1px 5px;
  border-radius: var(--r-xs);
  font-size: 9px;
}

.state.enter { background: var(--phosphor-wash); color: var(--phosphor); }
.state.watch { background: var(--panel); color: var(--ink-dim); }

.sig-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
  gap: var(--s2);
}

/* Compare Layout & Toolbar */
.compare-layout {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.compare-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.basket-chips-row {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.basket-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  font-size: var(--t-small, 12px);
  transition: all var(--dur-fast);
}

.basket-chip.active {
  border-color: var(--phosphor);
}

.chip-sym {
  cursor: pointer;
  color: var(--ink);
}

.basket-chip.active .chip-sym {
  color: var(--phosphor);
}

.chip-rm {
  background: none;
  border: none;
  color: var(--ink-dim);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0 2px;
}

.chip-rm:hover {
  color: var(--short);
}

.basket-add-row {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.compare-grid {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: var(--s4);
}

@media (max-width: 1000px) {
  .compare-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

/* Factor Loadings */
.facs {
  list-style: none;
  padding: var(--s3);
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  background: var(--void);
  border-radius: var(--r-sm);
}

.fac {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.f-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.f-lab {
  font-size: var(--t-tiny, 11px);
  color: var(--ink-dim);
}

.f-val-wrap {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.f-val {
  font-size: var(--t-small, 13px);
  font-weight: 600;
}

.f-sub {
  font-size: 10px;
  color: var(--ink-dim);
}

.f-bar {
  display: block;
  width: 100%;
  height: 4px;
  background: var(--panel);
  border-radius: 2px;
  overflow: hidden;
}

.f-bar i {
  display: block;
  height: 100%;
  border-radius: 2px;
  transition: width var(--dur-fast);
}

/* Compare Performance Table & Correlation Matrix */
.compare-perf-table {
  display: flex;
  flex-direction: column;
  border-bottom: var(--hair) solid var(--rule);
}

.leg-head {
  display: grid;
  grid-template-columns: 70px 130px 90px 80px 80px 36px;
  gap: var(--s2);
  padding: var(--s2) var(--s3);
  font-size: var(--t-micro, 10px);
  color: var(--ink-dim);
  text-transform: uppercase;
  letter-spacing: var(--track-label);
  background: var(--panel-hi);
  border-bottom: var(--hair) solid var(--rule-faint);
}

.legend {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
}

.leg {
  display: grid;
  grid-template-columns: 70px 130px 90px 80px 80px 36px;
  align-items: center;
  gap: var(--s2);
  padding: 8px var(--s3);
  border-bottom: var(--hair) solid var(--rule-faint);
  transition: background var(--dur-fast);
}

.leg:hover {
  background: var(--void);
}

.leg-sym {
  font-weight: 700;
  color: var(--phosphor);
  background: var(--void);
  padding: 3px 8px;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
  cursor: pointer;
  text-align: center;
  font-size: var(--t-small, 12px);
}

.spark {
  width: 120px;
  height: 22px;
  display: block;
}

.leg-ret, .leg-sh, .leg-dd {
  font-size: var(--t-small, 13px);
  font-variant-numeric: tabular-nums;
}

.leg-x {
  width: 24px;
  height: 24px;
  border-radius: var(--r-xs);
  background: var(--void);
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  line-height: 1;
  transition: all var(--dur-fast);
}

.leg-x:hover {
  color: var(--short);
  border-color: var(--short);
}

/* Correlation Section */
.corr-section {
  padding: var(--s4) var(--s3);
}

.sub-lab {
  margin: 0 0 var(--s3);
  font-size: var(--t-micro, 10px);
  color: var(--ink-dim);
  text-transform: uppercase;
  letter-spacing: var(--track-label);
}

.corr-table-wrap {
  overflow-x: auto;
  width: 100%;
}

.corr {
  display: grid;
  grid-template-columns: 60px repeat(var(--n), minmax(50px, 1fr));
  gap: 2px;
  align-items: center;
  background: var(--void);
  padding: var(--s2);
  border-radius: var(--r-sm);
  border: var(--hair) solid var(--rule-faint);
}

.corr-corner {
  background: transparent;
}

.corr-h {
  text-align: center;
  font-size: 11px;
  font-weight: 700;
  color: var(--phosphor);
  padding: 4px;
  letter-spacing: 0.04em;
}

.corr-h-row {
  font-size: 11px;
  font-weight: 700;
  color: var(--phosphor);
  padding: 4px 6px;
  letter-spacing: 0.04em;
}

.corr-c {
  text-align: center;
  font-size: 12px;
  font-family: var(--font-data);
  padding: 8px 4px;
  border-radius: var(--r-xs);
  font-variant-numeric: tabular-nums;
  border: var(--hair) solid var(--rule-faint);
}

/* Compare Empty State Container */
.compare-empty-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--s5) var(--s4);
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  gap: var(--s3);
}

.compare-quick-actions {
  display: flex;
  align-items: center;
  gap: var(--s2);
  margin-top: var(--s2);
}

/* Common Table Utilities */
.table-scroll-container {
  overflow-x: auto;
  width: 100%;
}

.link {
  color: var(--phosphor);
  text-decoration: underline;
}

.kind.dem { background: rgba(59, 130, 246, 0.2); color: #60a5fa; }
.kind.rep { background: rgba(239, 68, 68, 0.2); color: #f87171; }

/* SEC EDGAR filing kind color-coding */
.kind-annual { color: var(--phosphor); }
.kind-quarterly { color: var(--ink-dim); }
.kind-event { color: var(--call); }
.kind-unknown { color: var(--ink-ghost); }

/* Institutions Toolbar, Sorting & Pagination */
.institutions-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  background: var(--void);
  border-bottom: var(--hair) solid var(--rule-faint);
  flex-wrap: wrap;
}

.table-search-box {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex: 1;
  min-width: 240px;
}

.search-icon {
  color: var(--ink-dim);
  font-size: 14px;
}

.toolbar-controls {
  display: flex;
  align-items: center;
  gap: var(--s3);
}

.seg-label {
  font-size: var(--t-micro, 10px);
  padding: 0 4px;
}

th.sortable {
  cursor: pointer;
  user-select: none;
  transition: color var(--dur-fast);
}

th.sortable:hover {
  color: var(--phosphor);
}

.sort-arr {
  font-size: 10px;
  margin-left: 2px;
  color: var(--ink-dim);
}

.inst-name-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.inst-rank {
  font-size: 10px;
  color: var(--ink-dim);
  min-width: 24px;
}

.pct-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pct-bar-track {
  width: 120px;
  height: 6px;
  background: var(--void);
  border-radius: 1px;
  overflow: hidden;
  flex: 0 0 120px;
}

.pct-bar-fill {
  height: 100%;
  background: var(--phosphor);
}

.pagination-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--s3) var(--s4);
  background: var(--void);
  border-top: var(--hair) solid var(--rule-faint);
  flex-wrap: wrap;
  gap: var(--s2);
}

.page-nav-btns {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
}

.page-indicator {
  font-size: var(--t-tiny, 11px);
  color: var(--ink-soft);
  padding: 0 var(--s2);
}

.ratio-desc {
  font-size: 9px;
  color: var(--ink-dim);
  letter-spacing: 0.02em;
}

/* Quick Card Top Accents */
.quick-card.card-financials {
  border-top: 2px solid rgba(169, 196, 108, 0.6);
}

.quick-card.card-insiders {
  border-top: 2px solid rgba(245, 158, 11, 0.6);
}

.quick-card.card-forecast {
  border-top: 2px solid rgba(56, 189, 248, 0.6);
}

.quick-card.card-gov {
  border-top: 2px solid rgba(167, 139, 250, 0.6);
}
</style>
