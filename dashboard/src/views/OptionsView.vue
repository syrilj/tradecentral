<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  ApiError,
  type LiveOpportunities,
  type LiveOpportunityRow,
  type OptionsIntelligence,
  type OptionsMode,
  type OptionsRange,
  type OptionsTapeRow,
  type SearchHit,
  type StatusPayload,
  type UnusualFlowPayload,
  type UnusualFlowRow,
} from '@/api'
import { debounce, useResource, type Resource } from '@/composables/useResource'
import { compact, num, pctFrac, shortDate, signed, signedPct, tone, usd, DASH } from '@/format'
import Panel from '@/components/Panel.vue'
import GammaExposureMap from '@/components/GammaExposureMap.vue'
import SqueezeScreener from '@/components/SqueezeScreener.vue'
import ProbabilityDensityChart from '@/components/ProbabilityDensityChart.vue'
import OptionsFlowContext from '@/components/OptionsFlowContext.vue'
import OptionsConvictionBoard from '@/components/OptionsConvictionBoard.vue'
import LoadingState from '@/components/LoadingState.vue'

type NoisePreset = 'strict' | 'balanced' | 'raw'
type TapeView = 'near' | 'all' | 'whales' | 'anomalies' | 'calls' | 'puts' | 'sweeps' | 'blocks' | 'itm'
type TapeSort = 'near-signed' | 'newest' | 'premium' | 'anomaly'
type PremiumFloor = 0 | 25_000 | 50_000 | 100_000 | 250_000

const status = inject<Resource<StatusPayload>>('status')
const route = useRoute()
const router = useRouter()
const initialSymbol = typeof route.query.symbol === 'string' ? route.query.symbol : 'NVDA'
const symbolInput = ref(initialSymbol.toUpperCase())
const symbol = ref(initialSymbol.toUpperCase())
const mode = ref<OptionsMode>('live')
const selectedRange = ref<OptionsRange>('5d')
/** Default to all expiries — InsiderFinance GEX profile convention. */
const selectedExpiry = ref('all')
const preset = ref<NoisePreset>('balanced')
const dateFrom = ref('')
const dateTo = ref('')
/** Balanced defaults: high floors empty the qualified tape on mid-caps. */
const minPremium = ref(25_000)
const minVolume = ref(1)
/** Keep thin OTM walls visible (IF includes low-OI structure). */
const minOpenInterest = ref(50)
const maxSpreadPct = ref(0.25)
const minDte = ref(0)
/** Full chain window for multi-expiry GEX (IF uses all listed expiries). */
const maxDte = ref(365)
const tapeLimit = ref(100)
/** Default to near-dated signed flow so actionable prints show first.
 *  User can switch to 'all' to see the full tape without DTE restriction. */
const tapeView = ref<TapeView>('near')
/** Sort default: near-term signed first (most actionable), then newest. */
const tapeSort = ref<TapeSort>('near-signed')
/** Upper DTE cutoff for the 'near' view — 0-30d means this calendar month. */
const nearDteMax = ref(30)
const tapeDisplayMode = ref<'table' | 'cards'>('table')
const filtersOpen = ref(false)
/** Market-wide unusual board is secondary — underlier analysis comes first. */
const unusualOpen = ref(false)
/** Locked gamma strike for GEX focus. */
const focusStrike = ref<number | null>(null)
/** Prevents feedback loop when History auto-fills dateTo from the response. */
const historyAsOfSyncing = ref(false)
const PREMIUM_FLOORS: PremiumFloor[] = [0, 25_000, 50_000, 100_000, 250_000]

/* Market-style search typeahead */
const searchHits = ref<SearchHit[]>([])
const searching = ref(false)
const searchOpen = ref(false)

const resource = useResource<OptionsIntelligence>(() => api.options({
  symbol: symbol.value,
  mode: mode.value,
  range: selectedRange.value,
  minPremium: minPremium.value,
  minVolume: minVolume.value,
  minOpenInterest: minOpenInterest.value,
  maxSpreadPct: maxSpreadPct.value,
  minDte: minDte.value,
  maxDte: maxDte.value,
  expiry: selectedExpiry.value,
  tapeLimit: tapeLimit.value,
  dateFrom: dateFrom.value || undefined,
  // In history mode, `to` selects which dated chain day to load.
  dateTo: dateTo.value || undefined,
}), { intervalMs: 60_000 })

/**
 * Set true for exactly one refresh so a manual "SCAN LIVE FLOW" click bypasses the
 * backend's short poll cache (tools/api_server.py _UNUSUAL_FLOW_TTL_S). Flipped back to
 * false right after — the passive on-mount fetch and the 120s auto-poll below must
 * keep respecting the server cache, or every poll would hammer the upstream feed.
 */
const unusualForceNext = ref(false)

/** Market-wide unusual flow — independent of the selected underlier. */
const unusual = useResource<UnusualFlowPayload>(
  () => api.unusualFlow({ limit: 40, minPremium: minPremium.value, force: unusualForceNext.value }),
  { intervalMs: 120_000 },
)

/**
 * Manual "SCAN LIVE FLOW" handler — forces one live backend scan, then reverts the
 * flag so the next passive poll/on-mount fetch goes back to cache-respecting.
 */
async function scanLiveFlow(): Promise<void> {
  unusualForceNext.value = true
  try {
    await unusual.refresh()
  } finally {
    unusualForceNext.value = false
  }
}

/**
 * Set true for exactly one refresh so a manual "SCAN LIVE" click bypasses the
 * backend's 90s cache (tools/api_server.py _LIVE_OPPORTUNITIES_TTL_S). Same
 * one-shot-then-revert pattern as unusualForceNext above.
 */
const opportunitiesForceNext = ref(false)

/** Collapsed by default, like the Unusual Flow board above it. */
const opportunitiesOpen = ref(false)

/** Composite board+flow ranking (conviction board squeeze x market-wide
 *  unusual flow, z-blended) — independent of the selected underlier. */
const opportunities = useResource<LiveOpportunities>(
  () => api.liveOpportunities({ limit: 40, force: opportunitiesForceNext.value }),
  { intervalMs: 120_000 },
)

/**
 * Manual "SCAN LIVE" handler — forces one live recombination of the cached
 * board/flow boards, then reverts the flag so passive polling stays cached.
 */
async function scanLiveOpportunities(): Promise<void> {
  opportunitiesForceNext.value = true
  try {
    await opportunities.refresh()
  } finally {
    opportunitiesForceNext.value = false
  }
}

const opportunityRows = computed<LiveOpportunityRow[]>(() => opportunities.data.value?.rows ?? [])

const opportunitiesMeta = computed(() => {
  const data = opportunities.data.value
  const cov = data?.coverage
  if (cov) {
    return `${cov.union_symbols} NAMES · ${cov.gate_pass} TRADABLE · ${cov.gate_fail} NO-TRADE`
  }
  if (data && data.available === false) return 'AWAITING BOARD + FLOW DATA'
  return 'SCAN FOR COMPOSITE RANKING'
})

const SIGNAL_BASIS_LABEL: Record<string, string> = {
  structure_only: 'STRUCTURE',
  flow_only: 'FLOW',
  both: 'BOTH',
}
function signalBasisLabel(basis: string): string {
  return SIGNAL_BASIS_LABEL[basis] ?? basis.replaceAll('_', ' ').toUpperCase()
}

function gateTitle(row: LiveOpportunityRow): string {
  if (row.gate_pass) return 'Passed spread / open interest / DTE thresholds.'
  return row.gate_reasons.length ? row.gate_reasons.join('; ') : 'Failed the tradability gate.'
}

/** Signed call/put lean — options-right identity, not trade direction. */
function imbalanceTone(v: number | null | undefined): 'call' | 'put' | 'flat' {
  if (v == null || !Number.isFinite(v)) return 'flat'
  if (v > 0) return 'call'
  if (v < 0) return 'put'
  return 'flat'
}

/**
 * composite_score is an unbounded z-blend — clamp the METER (not the printed
 * figure) to ±3 so one outlier symbol can't flatten every other bar to a
 * sliver. The exact value is always shown as text alongside it.
 */
const COMPOSITE_METER_CLAMP = 3
function compositeMeterStyle(v: number | null | undefined): { left: string; width: string } {
  if (v == null || !Number.isFinite(v)) return { left: '50%', width: '0%' }
  const clamped = Math.max(-COMPOSITE_METER_CLAMP, Math.min(COMPOSITE_METER_CLAMP, v))
  const half = (Math.abs(clamped) / COMPOSITE_METER_CLAMP) * 50
  return clamped >= 0
    ? { left: '50%', width: `${half}%` }
    : { left: `${50 - half}%`, width: `${half}%` }
}

/** Drives both "BACKFILL OI" buttons (squeeze + gamma unmeasured panels) so a
 *  click on either disables both instead of firing two overlapping fetches. */
const backfilling = ref(false)
const backfillError = ref<string | null>(null)

/**
 * Captures a live OI snapshot for the current symbol (tools/backfill_option_oi.py,
 * run server-side) and refreshes so the unmeasured panels resolve to real
 * squeeze/gamma numbers without a page reload.
 */
async function backfillOi(): Promise<void> {
  if (backfilling.value) return
  backfilling.value = true
  backfillError.value = null
  try {
    await api.backfillOptionOi(symbol.value)
    await resource.refresh()
  } catch (e) {
    backfillError.value = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e)
  } finally {
    backfilling.value = false
  }
}

const refreshDebounced = debounce(() => void resource.refresh(), 240)
watch(
  [mode, selectedRange, selectedExpiry, tapeLimit, dateFrom, dateTo, minPremium, minVolume, minOpenInterest, maxSpreadPct, minDte, maxDte],
  () => {
    if (historyAsOfSyncing.value) return
    refreshDebounced()
  },
)

function cleanTicker(term: string): string {
  return term.trim().toUpperCase().replace(/[^A-Z0-9.-]/g, '').slice(0, 10)
}

/**
 * Load a symbol and ALWAYS refresh options intelligence.
 * Clears prior payload first so the UI cannot paint the previous underlier's
 * squeeze/GEX under the new ticker while the request is in flight.
 */
function loadSymbol(raw: string, { pushRoute = true } = {}): void {
  const clean = cleanTicker(raw)
  if (!clean) return
  const changed = clean !== symbol.value
  symbol.value = clean
  symbolInput.value = clean
  searchOpen.value = false
  if (changed) {
    selectedExpiry.value = 'all'
    focusStrike.value = null
  }
  if (pushRoute) {
    void router.replace({ query: { ...route.query, symbol: clean } })
  }
  // Always clear+fetch — even when reloading the same ticker.
  void resource.refresh({ clear: true })
}

const runSearch = debounce(async (term: string) => {
  const cleaned = cleanTicker(term)
  if (!cleaned) {
    searchHits.value = []
    return
  }
  searching.value = true
  try {
    const raw = await api.search(cleaned, 12)
    let list = raw.filter((h) => (h.kind ?? 'symbol') === 'symbol')
    if (cleaned && !list.some((h) => h.symbol === cleaned)) {
      list = [{
        symbol: cleaned,
        kind: 'symbol',
        tier: 'wide',
        n_bars: 0,
        first_date: '',
        last_date: '',
      }, ...list]
    }
    searchHits.value = list.slice(0, 12)
    searchOpen.value = true
  } catch {
    searchHits.value = cleaned
      ? [{ symbol: cleaned, kind: 'symbol', tier: 'wide', n_bars: 0, first_date: '', last_date: '' }]
      : []
  } finally {
    searching.value = false
  }
}, 140)

watch(symbolInput, (v) => {
  if (v.trim().toUpperCase() === symbol.value) return
  void runSearch(v)
})

watch(
  () => route.query.symbol,
  (value) => {
    if (typeof value !== 'string') return
    const clean = cleanTicker(value)
    if (!clean) return
    // Always load — even when symbol was already set by the form submit —
    // so squeeze recalculates for the active underlier.
    if (clean !== symbol.value) {
      loadSymbol(clean, { pushRoute: false })
    }
  },
)

// History: clear dates so the API auto-picks the last good chain day.
// Live: also clear dates — leftover history `to` was clamping the live tape
// window and rejecting every print as outside_range.
watch(mode, (next, prev) => {
  if (next === prev) return
  if (next === 'history' || next === 'live') {
    dateFrom.value = ''
    dateTo.value = ''
    focusStrike.value = null
  }
})

// After a history response lands, surface the selected chain day in the date control.
watch(
  () => resource.data.value,
  (payload) => {
    if (!payload || mode.value !== 'history') return
    const selected = payload.history?.selected_asof
    if (!selected) return
    if (dateTo.value === selected) return
    historyAsOfSyncing.value = true
    dateTo.value = selected
    // Allow subsequent manual date changes to re-fetch.
    queueMicrotask(() => { historyAsOfSyncing.value = false })
  },
)

function selectSymbol(): void {
  loadSymbol(symbolInput.value)
}

/** Watch symbol itself so any path that mutates it (route, search, board click) forces a load. */
watch(symbol, (next, prev) => {
  if (!next || next === prev) return
  // loadSymbol already refreshes; this catches external mutations only.
  if (resource.data.value?.symbol === next) return
  if (resource.loading.value) return
  void resource.refresh({ clear: true })
})

function setHistoryDay(day: string): void {
  dateTo.value = day
  // dateFrom left empty — single-day chain selection via `to`.
}

function setPreset(value: NoisePreset): void {
  preset.value = value
  const values = {
    // Tape is the sensitive path: high premium floors empty the qualified tape.
    strict: { premium: 100_000, volume: 25, oi: 200, spread: 0.10, min: 0, max: 90 },
    balanced: { premium: 25_000, volume: 1, oi: 50, spread: 0.25, min: 0, max: 365 },
    raw: { premium: 0, volume: 0, oi: 0, spread: 2, min: 0, max: 730 },
  }[value]
  minPremium.value = values.premium
  minVolume.value = values.volume
  minOpenInterest.value = values.oi
  maxSpreadPct.value = values.spread
  minDte.value = values.min
  maxDte.value = values.max
  // The filter watcher coalesces these mutations into one request.
}

function clearDateFilters(): void {
  dateFrom.value = ''
  dateTo.value = ''
  // The filter watcher refreshes once after both fields settle.
}

/** Only trust payload when it matches the symbol currently selected — prevents
 *  showing previous name's squeeze/GEX while a new load is in flight. */
const payloadMatches = computed(() =>
  Boolean(resource.data.value && resource.data.value.symbol === symbol.value),
)
const d = computed(() => (payloadMatches.value ? resource.data.value : null))
const s = computed(() => d.value?.summary)
const p = computed(() => d.value?.probability)
const expiry = computed(() => d.value?.chain_context)
const historyMeta = computed(() => d.value?.history)
const historyDays = computed(() => historyMeta.value?.available_dates ?? [])
const loadingSymbol = computed(() => resource.loading.value || !payloadMatches.value)

const unusualRows = computed<UnusualFlowRow[]>(() => unusual.data.value?.rows ?? [])
const unusualLiveCount = computed(() => unusualRows.value.filter((r) => r.live).length)
const deskActivityFallback = computed(() => {
  const rows = (status?.data.value?.activity_scan?.rows ?? []) as UnusualFlowRow[]
  return rows.filter((r) => r.live || (r.premium != null && r.premium > 0)).slice(0, 24)
})
const flowBoard = computed(() =>
  unusualRows.value.length ? unusualRows.value : deskActivityFallback.value,
)
const flowBoardMeta = computed(() => {
  const cov = unusual.data.value?.coverage
  if (cov) {
    return `${flowBoard.value.length} NAMES · ${unusualLiveCount.value} LIVE · ${cov.live_completed}/${cov.live_requested} CHECKED`
  }
  if (deskActivityFallback.value.length) {
    return `${deskActivityFallback.value.length} FROM DESK SCAN · RUN UNUSUAL FLOW FOR FULL MARKET`
  }
  return 'SCAN MARKET FOR LIVE TAPE'
})

const squeeze = computed(() => (payloadMatches.value ? s.value?.squeeze : null))

/**
 * False when the chain carried no open interest. Every gamma figure depends on
 * OI, so without it GEX collapses to 0, the min_oi filter drops the whole chain,
 * and the squeeze renders "0/100 UNLIKELY" — all artifacts of a missing input,
 * not observations. Render an explicit unmeasured state instead of those zeros.
 */
const gexMeasurable = computed(() => {
  const q = d.value?.quality as { gex_measurable?: boolean } | undefined
  if (!d.value) return true
  if (q?.gex_measurable !== undefined) return q.gex_measurable
  return (s.value?.call_oi ?? 0) + (s.value?.put_oi ?? 0) > 0
})

/** Contracts fetched but discarded by the filters — the "why is it empty" number. */
const chainRawCount = computed(
  () => (d.value?.quality as { chain_contracts_raw?: number } | undefined)?.chain_contracts_raw ?? 0,
)
const keyLevels = computed(() => squeeze.value?.key_levels)
const wallPct = (side: 'call' | 'put') => {
  // Prefer summary (directional walls from _gex_map); fall back to squeeze levels.
  const fromSummary = side === 'call' ? s.value?.call_wall_pct : s.value?.put_wall_pct
  if (fromSummary != null) return fromSummary
  const pct = side === 'call' ? keyLevels.value?.call_wall_pct : keyLevels.value?.put_wall_pct
  return pct == null ? null : pct
}

/** Notes collapsed by default — open when there are operational warnings. */
const notesOpen = ref(false)
const dataNotes = computed(() => {
  const warns = d.value?.warnings ?? []
  const caveats = (d.value?.caveats ?? []).slice(0, 3)
  return warns.length ? warns : caveats
})
watch(
  () => d.value?.warnings?.length ?? 0,
  (n) => { if (n > 0) notesOpen.value = true },
)

function isItm(row: OptionsTapeRow): boolean {
  const spotPrice = row.underlying_price ?? d.value?.summary?.spot
  if (spotPrice == null || row.strike == null) return false
  return row.right === 'call' ? spotPrice > row.strike : spotPrice < row.strike
}

function moneynessInfo(row: OptionsTapeRow): { text: string; cls: 'itm' | 'otm' | 'atm' } | null {
  const spotPrice = row.underlying_price ?? d.value?.summary?.spot
  if (spotPrice == null || row.strike == null || row.strike <= 0) return null
  const diffPct = ((spotPrice - row.strike) / row.strike) * 100
  const isCall = row.right === 'call'
  const inTheMoney = isCall ? diffPct > 0.1 : diffPct < -0.1
  const atTheMoney = Math.abs(diffPct) <= 0.1

  if (atTheMoney) return { text: 'ATM', cls: 'atm' }
  const dist = Math.abs(diffPct).toFixed(1)
  if (inTheMoney) {
    return { text: `+${dist}% ITM`, cls: 'itm' }
  }
  return { text: `${dist}% OTM`, cls: 'otm' }
}

const visibleTape = computed<OptionsTapeRow[]>(() => {
  const allRows = d.value?.flow_tape ?? []
  const now = new Date()

  /** True when the row's expiry falls within nearDteMax days from today. */
  function isNear(row: OptionsTapeRow): boolean {
    if (!row.expiry) return false
    const expDate = new Date(row.expiry)
    const dteDays = Math.ceil((expDate.getTime() - now.getTime()) / 86_400_000)
    return dteDays >= 0 && dteDays <= nearDteMax.value
  }

  /** True when the row has an explicit buy/sell side (signed flow). */
  function isSigned(row: OptionsTapeRow): boolean {
    return row.aggressor === 'buy' || row.aggressor === 'sell'
      || row.aggressor_label === 'BUY' || row.aggressor_label === 'SELL'
      || row.bias === 'bullish' || row.bias === 'bearish'
      || row.signed_premium != null
  }

  const rows = [...allRows].filter((row) => {
    if (tapeView.value === 'near') return isNear(row)
    if (tapeView.value === 'whales') return row.premium >= 100_000
    if (tapeView.value === 'itm') return isItm(row)
    if (tapeView.value === 'anomalies') return row.anomaly_flags.length > 0
    if (tapeView.value === 'calls') return row.right === 'call'
    if (tapeView.value === 'puts') return row.right === 'put'
    if (tapeView.value === 'sweeps') {
      return row.trade_class === 'sweep' || row.anomaly_flags.includes('sweep_burst')
    }
    if (tapeView.value === 'blocks') return row.trade_class === 'block'
    return true
  })

  if (tapeSort.value === 'premium') return rows.sort((a, b) => b.premium - a.premium)
  if (tapeSort.value === 'anomaly') return rows.sort((a, b) => b.anomaly_score - a.anomaly_score || b.premium - a.premium)
  if (tapeSort.value === 'near-signed') {
    // Tier 1: near-dated AND signed → sort by expiry asc, then premium desc
    // Tier 2: near-dated unsigned
    // Tier 3: far-dated (all tab only) → newest
    return rows.sort((a, b) => {
      const aNear = isNear(a) ? 0 : 1
      const bNear = isNear(b) ? 0 : 1
      if (aNear !== bNear) return aNear - bNear
      const aSigned = isSigned(a) ? 0 : 1
      const bSigned = isSigned(b) ? 0 : 1
      if (aSigned !== bSigned) return aSigned - bSigned
      // Both near+signed: soonest expiry first, then premium desc
      const aExp = a.expiry ?? ''
      const bExp = b.expiry ?? ''
      if (aExp !== bExp) return aExp.localeCompare(bExp)
      return b.premium - a.premium
    })
  }
  return rows.sort((a, b) => b.timestamp.localeCompare(a.timestamp))
})

const tapeClassCounts = computed(() => {
  const rows = d.value?.flow_tape ?? []
  const now = new Date()
  let sweeps = 0
  let blocks = 0
  let whales = 0
  let itm = 0
  let near = 0
  for (const r of rows) {
    if (r.trade_class === 'sweep' || r.anomaly_flags.includes('sweep_burst')) sweeps += 1
    if (r.trade_class === 'block') blocks += 1
    if (r.premium >= 100_000) whales += 1
    if (isItm(r)) itm += 1
    if (r.expiry) {
      const dteDays = Math.ceil((new Date(r.expiry).getTime() - now.getTime()) / 86_400_000)
      if (dteDays >= 0 && dteDays <= nearDteMax.value) near += 1
    }
  }
  return { sweeps, blocks, whales, itm, near }
})

function anomalyLabel(flag: string): string {
  return {
    premium_outlier: 'PRM',
    volume_outlier: 'VOL',
    repeat_cluster: 'CLU',
    sweep_burst: 'SWP',
  }[flag] ?? flag.replaceAll('_', ' ').toUpperCase().slice(0, 4)
}

/**
 * Lean chip: signed BULL/BEAR when aggressor/vendor says so;
 * otherwise CALL/PUT activity identity so the column is never empty/broken.
 */
function tapeLean(row: OptionsTapeRow): { label: string; cls: string; title: string } {
  if (row.bias === 'bullish' || row.edge_label === 'BULL') {
    return {
      label: 'BULL',
      cls: 'bull',
      title: row.bias_source === 'vendor_sentiment'
        ? 'Vendor sentiment lean'
        : 'Bought call or sold put (aggressor-signed)',
    }
  }
  if (row.bias === 'bearish' || row.edge_label === 'BEAR') {
    return {
      label: 'BEAR',
      cls: 'bear',
      title: row.bias_source === 'vendor_sentiment'
        ? 'Vendor sentiment lean'
        : 'Bought put or sold call (aggressor-signed)',
    }
  }
  if (row.right === 'call' || row.activity_side === 'call' || row.edge_label === 'CALL') {
    return { label: 'CALL', cls: 'call', title: 'Call print — activity only, no buy/sell side from feed' }
  }
  if (row.right === 'put' || row.activity_side === 'put' || row.edge_label === 'PUT') {
    return { label: 'PUT', cls: 'put', title: 'Put print — activity only, no buy/sell side from feed' }
  }
  return { label: '—', cls: 'unsigned', title: 'Unresolved' }
}

function tradeClassLabel(row: OptionsTapeRow): string {
  const raw = (row.trade_class || 'single').toLowerCase()
  if (raw === 'sweep' || row.anomaly_flags.includes('sweep_burst')) return 'SWEEP'
  if (raw === 'block') return 'BLOCK'
  return 'SINGLE'
}

function contractsOf(row: OptionsTapeRow): number {
  return row.contracts ?? row.volume ?? 0
}

function pricePaid(row: OptionsTapeRow): number | null {
  if (row.price != null && Number.isFinite(row.price)) return row.price
  const n = contractsOf(row)
  if (n > 0 && row.premium > 0) return row.premium / (n * 100)
  return null
}

function aggressorLabel(row: OptionsTapeRow): { label: string; cls: string } {
  if (row.aggressor === 'buy' || row.aggressor_label === 'BUY') return { label: 'BUY', cls: 'buy' }
  if (row.aggressor === 'sell' || row.aggressor_label === 'SELL') return { label: 'SELL', cls: 'sell' }
  return { label: row.aggressor_label || 'NO SIDE', cls: 'unknown' }
}

const signedFlowAvailable = computed(() => Boolean(d.value?.provider?.signed_flow_available))

function formatLag(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

/**
 * Live lag indicator for this underlier's options tape — not generic "connected".
 * Distinguishes real trade tape vs chain-volume proxy vs history.
 */
const tapeHealth = computed(() => {
  if (loadingSymbol.value && !d.value) {
    return {
      status: 'loading' as const,
      lamp: 'pending',
      title: 'LOADING',
      sub: `Pulling ${symbol.value} chain + tape…`,
      lag: null as string | null,
      detail: '',
    }
  }
  if (!d.value) {
    return {
      status: 'idle' as const,
      lamp: 'pending',
      title: 'NO DATA',
      sub: 'Load a ticker',
      lag: null as string | null,
      detail: '',
    }
  }
  const age = d.value.freshness?.age_seconds ?? null
  const basis = d.value.provider?.activity_basis
  const printsIn = d.value.quality?.flow_prints_included ?? 0
  const printsRaw = d.value.quality?.flow_prints_raw ?? 0
  const tapeN = d.value.flow_tape?.length ?? 0
  const lag = formatLag(age)

  if (d.value.mode_resolved === 'history' || d.value.mode_resolved === 'history_fallback') {
    return {
      status: 'history' as const,
      lamp: 'history',
      title: d.value.mode_resolved === 'history_fallback' ? 'HIST FALLBACK' : 'HISTORY',
      sub: `Dated chain · ${historyMeta.value?.selected_asof ?? d.value.asof_utc?.slice(0, 10) ?? '—'}`,
      lag,
      detail: `${d.value.quality?.chain_contracts_included ?? 0} contracts kept`,
    }
  }

  if (basis === 'trade_tape' && tapeN > 0) {
    const live = age != null && age <= 90
    const soft = age != null && age <= 300
    return {
      status: live ? 'live' as const : soft ? 'warm' as const : 'stale' as const,
      lamp: live ? 'live' : soft ? 'stale' : 'stale',
      title: live ? 'LIVE TAPE' : soft ? 'TAPE WARM' : 'TAPE STALE',
      sub: live
        ? `Streaming prints for ${d.value.symbol}`
        : soft
          ? `Last print lag ${lag} — still usable`
          : `Last observation lag ${lag} — not fresh`,
      lag,
      detail: `${tapeN} shown · ${printsIn}/${printsRaw} prints · ${signedFlowAvailable.value ? 'side on' : 'no side'}`,
    }
  }

  if (basis === 'chain_activity_proxy') {
    return {
      status: 'proxy' as const,
      lamp: 'stale',
      title: 'NO LIVE TAPE',
      sub: `Chain volume proxy only — not trade prints for ${d.value.symbol}`,
      lag,
      detail: `${printsRaw} raw · filter rejected or feed empty`,
    }
  }

  return {
    status: 'missing' as const,
    lamp: 'pending',
    title: 'TAPE OFF',
    sub: age != null ? `Lag ${lag} · no qualified prints` : 'No trade tape available',
    lag,
    detail: basis ?? 'unavailable',
  }
})

const filterSummary = computed(() =>
  `≥$${compact(minPremium.value)} · vol≥${minVolume.value} · OI≥${minOpenInterest.value} · spr≤${num(maxSpreadPct.value * 100, 0)}% · ${minDte.value}–${maxDte.value}d`,
)

function setPremiumFloor(v: PremiumFloor): void {
  minPremium.value = v
  // Align preset chip if it matches a known preset floor.
  if (v === 100_000) preset.value = 'strict'
  else if (v === 25_000) preset.value = 'balanced'
  else if (v === 0) preset.value = 'raw'
  void resource.refresh()
}

function rangeHint(range: OptionsRange): string {
  return {
    '1d': 'Last session — 15m premium buckets',
    '5d': 'Five sessions — hourly buckets',
    '1m': '≈31 days — daily buckets',
    '3m': '≈93 days — daily buckets',
  }[range]
}

function presetHint(value: NoisePreset): string {
  return {
    strict: 'Large prints only: $100k+, vol 25+, OI 200+, max 10% spread, 0–90 DTE',
    balanced: 'Default: $25k+, vol 1+, OI 50+, max 25% spread, 0–365 DTE',
    raw: 'Minimal filters: any premium/volume, max 200% spread, 0–730 DTE',
  }[value]
}

function floorLabel(v: PremiumFloor): string {
  if (v === 0) return 'ANY'
  if (v >= 1_000_000) return `$${v / 1_000_000}M`
  return `$${v / 1000}k`
}

/* The Options workspace is intentionally underlier-scoped. Whole-market
   discovery now lives at /flow; the retired scanner branch stays in this file
   temporarily so the existing fetch/cache work is preserved while its pieces
   are reused by FlowView. */
const optionsTab = ref<'analysis' | 'scanners'>('analysis')

</script>

<template>
  <div class="options-view">
    <!-- Command strip: ticker identity, symbol input, mode, range, expiry, tune -->
    <section class="command ticked rise">
      <div class="identity">
        <div class="symbol-lockup">
          <span class="active-symbol fig">{{ symbol }}</span>
          <span class="view-label label">OPTIONS INTELLIGENCE</span>
        </div>
      </div>

      <form class="symbol-form" @submit.prevent="selectSymbol">
        <div class="symbol-entry">
          <input
            id="option-symbol"
            v-model="symbolInput"
            maxlength="10"
            autocomplete="off"
            spellcheck="false"
            placeholder="TICKER"
            aria-label="Underlying symbol"
            @focus="searchOpen = searchHits.length > 0"
            @keydown.escape="searchOpen = false"
          />
          <button class="load-btn label" type="submit" :disabled="loadingSymbol">
            {{ loadingSymbol ? '…' : 'LOAD' }}
          </button>
        </div>
        <ul v-if="searchOpen && searchHits.length" class="search-hits" role="listbox">
          <li
            v-for="hit in searchHits"
            :key="hit.symbol"
            role="option"
            class="label"
            :class="{ on: hit.symbol === symbol }"
            @mousedown.prevent="loadSymbol(hit.symbol)"
          >
            <span class="fig">{{ hit.symbol }}</span>
            <span class="tier">{{ hit.tier }}</span>
            <span class="bars">{{ hit.n_bars ? `${hit.n_bars} bars` : 'enter' }}</span>
          </li>
        </ul>
      </form>

      <div class="segment mode-seg">
        <button class="seg label" :class="{ on: mode === 'live' }" @click="mode = 'live'">LIVE</button>
        <button class="seg label" :class="{ on: mode === 'history' }" @click="mode = 'history'">HIST</button>
      </div>

      <div class="segment range-seg">
        <button
          v-for="item in (['1d','5d','1m','3m'] as OptionsRange[])"
          :key="item"
          class="seg label"
          :class="{ on: selectedRange === item }"
          @click="selectedRange = item"
          :title="rangeHint(item)"
        >{{ item.toUpperCase() }}</button>
      </div>

      <select v-model="selectedExpiry" class="expiry-select label" aria-label="Options expiry">
        <option value="nearest">NEAREST</option>
        <option value="all">ALL EXP</option>
        <option
          v-for="item in expiry?.available_expiries ?? []"
          :key="item.expiry"
          :value="item.expiry"
        >{{ shortDate(item.expiry) }} · {{ item.dte }}D</option>
      </select>

      <div class="command-right">
        <span class="scope-chip label">{{ mode === 'live' ? 'LIVE / DELAYED' : 'HISTORICAL' }}</span>
        <RouterLink class="market-flow-link label" :to="{ name: 'flow' }">MARKET FLOW</RouterLink>
        <button class="tune label" type="button" :class="{ on: filtersOpen }" @click="filtersOpen = !filtersOpen">
          TUNE {{ filtersOpen ? '▴' : '▾' }}
        </button>
      </div>
    </section>

    <!-- ===== UNDERLIER ANALYSIS ========================================== -->
    <template v-if="optionsTab === 'analysis'">
    <section class="live-filter-bar rise" :class="tapeHealth.status">
      <div class="live-badge" :class="tapeHealth.lamp" :title="tapeHealth.sub">
        <span class="live-pulse" :class="tapeHealth.lamp" aria-hidden="true" />
        <div class="live-text">
          <strong class="label live-title">{{ tapeHealth.title }}</strong>
          <span class="live-sub">{{ tapeHealth.sub }}</span>
        </div>
        <div v-if="tapeHealth.lag" class="live-lag">
          <span class="label">LAG</span>
          <strong class="fig">{{ tapeHealth.lag }}</strong>
        </div>
      </div>
      <div class="live-meta label" v-if="tapeHealth.detail">{{ tapeHealth.detail }}</div>

      <div class="quick-filters">
        <span class="qf-lab label">MIN PREM</span>
        <button
          v-for="floor in PREMIUM_FLOORS"
          :key="floor"
          type="button"
          class="qf-chip label"
          :class="{ on: minPremium === floor }"
          @click="setPremiumFloor(floor)"
        >{{ floorLabel(floor) }}</button>
        <span class="qf-sep" aria-hidden="true" />
        <span class="qf-lab label">NOISE</span>
        <button
          v-for="item in (['strict','balanced','raw'] as NoisePreset[])"
          :key="`qf-${item}`"
          type="button"
          class="qf-chip label"
          :class="{ on: preset === item }"
          :title="presetHint(item)"
          @click="setPreset(item)"
        >{{ item.slice(0, 3).toUpperCase() }}</button>
      </div>
    </section>

    <section v-if="filtersOpen" class="filter-deck rise">
      <div class="filters">
        <label><span class="label">From</span><input v-model="dateFrom" type="date" /></label>
        <label><span class="label">{{ mode === 'history' ? 'Chain day' : 'To' }}</span><input v-model="dateTo" type="date" /></label>
        <label><span class="label">Min $</span><input v-model.number="minPremium" type="number" min="0" step="5000" /></label>
        <label><span class="label">Min vol</span><input v-model.number="minVolume" type="number" min="0" step="1" /></label>
        <label><span class="label">Min OI</span><input v-model.number="minOpenInterest" type="number" min="0" step="25" /></label>
        <label><span class="label">Max spr%</span><input :value="maxSpreadPct * 100" type="number" min="0.1" max="200" step="1" @input="maxSpreadPct = Number(($event.target as HTMLInputElement).value) / 100" /></label>
        <label><span class="label">Min DTE</span><input v-model.number="minDte" type="number" min="0" max="730" /></label>
        <label><span class="label">Max DTE</span><input v-model.number="maxDte" type="number" min="0" max="730" /></label>
        <label><span class="label">Tape n</span>
          <select v-model.number="tapeLimit" class="label">
            <option :value="50">50</option>
            <option :value="100">100</option>
            <option :value="250">250</option>
            <option :value="500">500</option>
          </select>
        </label>
      </div>
      <div class="filter-foot">
        <span class="filter-summary label">{{ filterSummary }}</span>
        <button type="button" class="label raw-btn inline" @click="setPreset('raw')">OPEN RAW</button>
        <button type="button" class="label raw-btn inline" @click="clearDateFilters">CLEAR DATES</button>
      </div>
    </section>

    <section v-if="mode === 'history' && historyDays.length" class="history-day-bar rise">
      <span class="label">History chain day</span>
      <select
        class="history-day-select label"
        :value="historyMeta?.selected_asof ?? dateTo"
        aria-label="Select historical chain day"
        @change="setHistoryDay(($event.target as HTMLSelectElement).value)"
      >
        <option
          v-for="day in [...historyDays].reverse()"
          :key="day"
          :value="day"
        >{{ shortDate(day) }}{{ day === historyMeta?.last_good_asof ? ' · LAST GOOD' : '' }}</option>
      </select>
      <span class="label history-day-meta">
        {{ historyDays.length }} DATED SNAPSHOT{{ historyDays.length === 1 ? '' : 'S' }}
        · GEX / walls / density use this day only
      </span>
      <button
        v-if="historyMeta?.last_good_asof && dateTo !== historyMeta.last_good_asof"
        type="button"
        class="label jump-last-good"
        @click="setHistoryDay(historyMeta.last_good_asof)"
      >JUMP TO LAST GOOD</button>
    </section>

    <div v-if="resource.error.value" class="fault-strip">
      <span class="label">FEED ERROR</span>
      {{ resource.error.value }}
      <button class="label" type="button" @click="void resource.refresh({ clear: true })">RETRY</button>
    </div>

    <div v-if="loadingSymbol && !d" class="fault-strip loading-strip">
      <span class="label">CALCULATING</span>
      Loading GEX · squeeze · tape for <strong class="fig">{{ symbol }}</strong>…
    </div>
    <div v-else-if="loadingSymbol && d" class="fault-strip loading-strip soft">
      <span class="label">REFRESHING {{ symbol }}</span>
      Recomputing squeeze and structure…
    </div>

    <section v-if="dataNotes.length" class="data-notes" :class="{ open: notesOpen }">
      <button class="notes-toggle label" type="button" @click="notesOpen = !notesOpen">
        <span class="notes-dot" aria-hidden="true" />
        {{ dataNotes.length }} DATA NOTE{{ dataNotes.length === 1 ? '' : 'S' }}
        <span class="notes-chev">{{ notesOpen ? '▴' : '▾' }}</span>
      </button>
      <ul v-if="notesOpen">
        <li v-for="(note, i) in dataNotes" :key="i">{{ note }}</li>
      </ul>
      <span v-else class="notes-preview label">{{ dataNotes[0] }}</span>
    </section>

    <!-- Dense structure KPI rail -->
    <section class="kpi-rail rise">
      <div class="kpi spot">
        <span class="label">SPOT</span>
        <strong class="fig">{{ usd(s?.spot) }}</strong>
        <em class="label">UNDERLYING</em>
      </div>
      <div class="kpi" :class="s?.regime">
        <span class="label">NET GEX</span>
        <strong class="fig" :class="tone(s?.total_gex_m)">{{ s?.total_gex_m == null ? DASH : `${s.total_gex_m >= 0 ? '+' : ''}$${num(s.total_gex_m, 1)}M` }}</strong>
        <em class="label">{{ (s?.regime ?? 'UNKNOWN').toUpperCase() }} GAMMA</em>
      </div>
      <div class="kpi call">
        <span class="label">CALL WALL</span>
        <strong class="fig call">{{ usd(s?.call_wall) }}</strong>
        <em class="label call-tag">{{ wallPct('call') == null ? DASH : (wallPct('call')! >= 0 ? '+' : '') + pctFrac(wallPct('call'), 1) }}</em>
      </div>
      <div class="kpi put">
        <span class="label">PUT WALL</span>
        <strong class="fig put">{{ usd(s?.put_wall) }}</strong>
        <em class="label put-tag">{{ wallPct('put') == null ? DASH : (wallPct('put')! >= 0 ? '+' : '') + pctFrac(wallPct('put'), 1) }}</em>
      </div>
      <div class="kpi">
        <span class="label">FLIP</span>
        <strong class="fig accent">{{ usd(s?.gamma_flip) }}</strong>
        <em class="label">ZERO-GAMMA LEVEL</em>
      </div>
      <div class="kpi">
        <span class="label">IV</span>
        <strong class="fig">{{ p?.atm_iv != null ? pctFrac(p.atm_iv, 1) : DASH }}</strong>
        <em class="label">ATM · {{ p?.horizon_days ?? DASH }}D</em>
      </div>
      <div class="kpi">
        <span class="label">C/P PREM</span>
        <strong class="fig">
          <span class="call">{{ s?.call_premium != null ? `$${compact(s.call_premium)}` : DASH }}</span>
          <span class="dim">/</span>
          <span class="put">{{ s?.put_premium != null ? `$${compact(s.put_premium)}` : DASH }}</span>
        </strong>
        <em class="label">RATIO {{ s?.call_put_ratio == null ? DASH : num(s.call_put_ratio, 2) }}</em>
      </div>
      <div class="kpi squeeze-kpi">
        <span class="label">SQUEEZE</span>
        <div class="kpi-squeeze-body">
          <strong class="fig">
            {{ squeeze?.score ?? squeeze?.bullish_setup?.score ?? squeeze?.bearish_setup?.score ?? DASH }}
            <small v-if="squeeze">/100</small>
          </strong>
          <span
            v-if="squeeze?.primary || squeeze?.bullish_setup?.likelihood || squeeze?.bearish_setup?.likelihood"
            class="squeeze-tag label"
          >{{ (squeeze?.primary || squeeze?.bullish_setup?.likelihood || squeeze?.bearish_setup?.likelihood || '').toUpperCase().replace(/_/g, '-') }}</span>
        </div>
      </div>
    </section>

    <!-- Dense workbench: setup, dominant GEX canvas, and flow context. -->
    <div class="workbench">
      <div class="workbench-top">
        <Panel
          label="SQUEEZE SETUP"
          index="01"
          flush
          class="cell screener-cell"
        >
          <template #action>
            <span class="long-it-btn label" title="Setup attention only — not an order">
              SETUP WATCH <span class="info-icon">INFO</span>
            </span>
          </template>
          <LoadingState v-if="loadingSymbol && !squeeze" label="Calculating" compact />
          <div v-else-if="!gexMeasurable" class="unmeasured">
            <p class="unmeasured-head label">SQUEEZE UNMEASURED</p>
            <p class="unmeasured-body">
              No open-interest source for {{ symbol }}.
              {{ chainRawCount }} contracts were fetched, but dealer gamma cannot be
              computed without OI — so this is <b>not</b> a quiet market, it is an
              absent measurement. A score of 0 here would be an artifact.
            </p>
            <div class="unmeasured-actions">
              <button
                type="button"
                class="label scan-btn"
                :disabled="backfilling"
                @click="void backfillOi()"
              >{{ backfilling ? 'BACKFILLING…' : `BACKFILL ${symbol} OI` }}</button>
              <span v-if="backfillError" class="unmeasured-fix warn">{{ backfillError }}</span>
              <span v-else class="unmeasured-fix label">
                Fetches a dated chain snapshot live (tools/backfill_option_oi.py)
              </span>
            </div>
          </div>
          <SqueezeScreener v-else :squeeze="squeeze" :spot="s?.spot" />
        </Panel>

        <Panel
          label="NET GAMMA BY STRIKE"
          index="02"
          flush
          class="cell gex-cell-panel gex-full"
        >
          <template #action>
            <div class="panel-action-group">
              <span class="gex-meta-badge">EXPOSURE {{ !gexMeasurable || s?.total_gex_m == null ? DASH : `$${num(s.total_gex_m, 1)}M` }}</span>
              <span class="gex-meta-badge">SPOT {{ usd(s?.spot) }}</span>
              <span v-if="s?.gamma_flip != null" class="gex-meta-badge flip">FLIP {{ usd(s.gamma_flip) }}</span>
            </div>
          </template>
          <LoadingState v-if="loadingSymbol && !d" label="Loading GEX" compact />
          <div v-else-if="!gexMeasurable" class="unmeasured">
            <p class="unmeasured-head label">GAMMA UNMEASURED</p>
            <p class="unmeasured-body">
              {{ symbol }} has no open interest on this chain, so every strike fails the
              OI filter and the map has nothing to draw. The $0.0M readouts above are the
              absence of an input, not a flat gamma profile.
            </p>
            <div class="unmeasured-actions">
              <button
                type="button"
                class="label scan-btn"
                :disabled="backfilling"
                @click="void backfillOi()"
              >{{ backfilling ? 'BACKFILLING…' : `BACKFILL ${symbol} OI` }}</button>
              <span v-if="backfillError" class="unmeasured-fix warn">{{ backfillError }}</span>
              <span v-else class="unmeasured-fix label">
                Or set the OI filter to 0 in TUNE to inspect raw quotes without gamma.
              </span>
            </div>
          </div>
          <template v-else>
            <GammaExposureMap
              :rows="d?.gex_by_strike ?? []"
              :spot="s?.spot ?? 0"
              :call-wall="s?.call_wall ?? null"
              :put-wall="s?.put_wall ?? null"
              :gamma-flip="s?.gamma_flip ?? null"
              :focus-strike="focusStrike"
              @update:focus-strike="focusStrike = $event"
            />
          </template>
        </Panel>

        <Panel
          label="FLOW SENTIMENT"
          index="03"
          flush
          class="cell flow-context-cell"
        >
          <OptionsFlowContext
            :summary="s"
            :tape="d?.flow_tape ?? []"
            :anomaly-count="d?.anomalies.count ?? 0"
            :signed-flow-available="signedFlowAvailable"
            :tape-status="tapeHealth.status"
            :tape-title="tapeHealth.title"
          />
        </Panel>
      </div>
    </div>

    <!-- Panel 04: Risk-Neutral Probability & Target Calculator -->
    <Panel
      label="RISK-NEUTRAL PROBABILITY"
      index="04"
      flush
      class="prob-calc-panel rise"
    >
      <template #action>
        <div class="panel-action-group" v-if="p">
          <span class="gex-meta-badge" v-if="p.atm_iv">IV {{ pctFrac(p.atm_iv, 1) }}</span>
          <span class="gex-meta-badge" v-if="p.horizon_days">{{ p.horizon_days }}D HORIZON</span>
          <span class="gex-meta-badge" v-if="p.expected_move">±1σ {{ usd(p.expected_move) }}</span>
        </div>
      </template>
      <LoadingState v-if="loadingSymbol && !p" label="Calculating Probability" compact />
      <ProbabilityDensityChart
        v-else
        :probability="p"
        :spot="s?.spot ?? 0"
        :call-wall="s?.call_wall ?? null"
        :put-wall="s?.put_wall ?? null"
        :focus-price="focusStrike"
        :height="180"
      />
    </Panel>

    <Panel
      label="Qualified Flow Tape"
      index="05"
      :meta="`${visibleTape.length}/${d?.flow_tape.length ?? 0} · ${tapeClassCounts.whales} WHALES · ${tapeClassCounts.sweeps} SWP · ${tapeClassCounts.blocks} BLK`"
      :live="tapeHealth.status === 'live'"
      flush
      class="tape-panel tape-panel-full"
    >
      <template #action>
        <div class="mini-segment tape-display-seg">
          <button type="button" class="label" :class="{ on: tapeDisplayMode === 'table' }" @click="tapeDisplayMode = 'table'">TABLE</button>
          <button type="button" class="label" :class="{ on: tapeDisplayMode === 'cards' }" @click="tapeDisplayMode = 'cards'">CARDS</button>
        </div>
      </template>

      <div v-if="d?.flow_tape.length" class="tape-toolbar">
        <!-- Row 1: view tabs on left, sort/status controls on right -->
        <div class="tape-toolbar-main">
          <div class="tape-tabs">
            <button type="button" class="label near-tab" :class="{ on: tapeView === 'near' }" @click="tapeView = 'near'; tapeSort = 'near-signed'" title="Near-dated flow (this month). Signed prints bubble to top.">
              NEAR<span v-if="tapeClassCounts.near" class="near-count">&nbsp;{{ tapeClassCounts.near }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'all' }" @click="tapeView = 'all'">ALL</button>
            <button type="button" class="label whale-tab" :class="{ on: tapeView === 'whales' }" @click="tapeView = 'whales'">
              WHALES<span v-if="tapeClassCounts.whales" class="tab-count">{{ tapeClassCounts.whales }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'itm' }" @click="tapeView = 'itm'">
              ITM<span v-if="tapeClassCounts.itm" class="tab-count">{{ tapeClassCounts.itm }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'sweeps' }" @click="tapeView = 'sweeps'">
              SWEEPS<span v-if="tapeClassCounts.sweeps" class="tab-count">{{ tapeClassCounts.sweeps }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'blocks' }" @click="tapeView = 'blocks'">
              BLOCKS<span v-if="tapeClassCounts.blocks" class="tab-count">{{ tapeClassCounts.blocks }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'anomalies' }" @click="tapeView = 'anomalies'">
              FLAGS<span v-if="d?.anomalies.count" class="tab-count">{{ d.anomalies.count }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'calls' }" @click="tapeView = 'calls'">CALLS</button>
            <button type="button" class="label" :class="{ on: tapeView === 'puts' }" @click="tapeView = 'puts'">PUTS</button>
          </div>
          <div class="tape-toolbar-right">
            <div v-if="tapeView === 'near'" class="near-window-control">
              <span class="label qf-lab">DTE ≤</span>
              <button v-for="d_ in [7, 14, 30]" :key="d_" type="button" class="label near-dte-chip" :class="{ on: nearDteMax === d_ }" @click="nearDteMax = d_">{{ d_ }}d</button>
            </div>
            <label class="sort-control">
              <span class="label">SORT</span>
              <select v-model="tapeSort" class="label">
                <option value="near-signed">NEAR SIGNED</option>
                <option value="newest">NEWEST</option>
                <option value="premium">PREMIUM</option>
                <option value="anomaly">ANOMALY</option>
              </select>
            </label>
            <span class="anomaly-method" :title="d?.anomalies.method">
              <i :class="tapeHealth.lamp" />
              {{ signedFlowAvailable ? 'SIGNED' : 'UNSIGNED' }}
            </span>
          </div>
        </div>
      </div>

      <!-- CARDS MODE: Visual Stalker Stream -->
      <div v-if="visibleTape.length && tapeDisplayMode === 'cards'" class="tape-cards-container">
        <div class="tape-cards-grid">
          <div
            v-for="row in visibleTape"
            :key="`card-${row.timestamp}-${row.right}-${row.strike}-${row.premium}`"
            class="tape-stalker-card"
            :class="{
              anomalous: row.anomaly_flags.length,
              isWhale: row.premium >= 100_000,
              isMegaWhale: row.premium >= 250_000,
              [tapeLean(row).cls]: true,
            }"
          >
            <div class="card-head-row">
              <span class="type-pill label" :class="row.right">{{ row.right === 'call' ? 'CALL' : 'PUT' }}</span>
              <span class="lean-pill label" :class="tapeLean(row).cls">{{ tapeLean(row).label }}</span>
              <span class="ts-time fig">{{ row.timestamp.slice(11, 19) }}</span>
              <span v-if="row.premium >= 250_000" class="flag-chip mega-whale-chip label">MEGA</span>
              <span v-else-if="row.premium >= 100_000" class="flag-chip whale-chip label">WHALE</span>
            </div>

            <div class="card-body-row">
              <div class="strike-box">
                <span class="strike-label label">STRIKE</span>
                <strong class="strike-val fig">${{ usd(row.strike) }}</strong>
                <span v-if="moneynessInfo(row)" class="money-tag label" :class="moneynessInfo(row)!.cls">{{ moneynessInfo(row)!.text }}</span>
              </div>
              <div class="prem-box" :class="row.right">
                <span class="prem-label label">PREMIUM</span>
                <strong class="prem-val fig">${{ compact(row.premium) }}</strong>
                <span class="fill-sub label">{{ num(contractsOf(row), 0) }} ct @ {{ pricePaid(row) == null ? '—' : `$${num(pricePaid(row), 2)}` }}</span>
              </div>
            </div>

            <div class="card-foot-row">
              <span class="class-chip label" :class="tradeClassLabel(row).toLowerCase()">{{ tradeClassLabel(row) }}</span>
              <span class="exp-tag label">{{ row.expiry ? shortDate(row.expiry) : '—' }}</span>
              <span class="agg label" :class="aggressorLabel(row).cls">{{ aggressorLabel(row).label }}</span>
              <span v-for="flag in row.anomaly_flags" :key="flag" class="flag-chip label" :class="flag">{{ anomalyLabel(flag) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- TABLE MODE -->
      <div v-else-if="visibleTape.length" class="table-scroll table-scroll-tall">
        <table class="tape-table">
          <thead>
            <tr>
              <th class="label flag-col">Flag</th>
              <th class="label">Time</th>
              <th class="label tape-col-group">Lean</th>
              <th class="label">Side</th>
              <th class="label">Class</th>
              <th class="label tape-col-group">Expiry</th>
              <th class="label num-col">Strike</th>
              <th class="label num-col tape-col-group stock-head">Stock Price</th>
              <th class="label num-col tape-col-group">Paid $</th>
              <th class="label num-col">Ct</th>
              <th class="label num-col tape-premium-head">Premium</th>
              <th class="label tape-col-group">Aggressor</th>
              <th class="label num-col">Notional edge</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in visibleTape"
              :key="`${row.timestamp}-${row.right}-${row.strike}-${row.premium}`"
              :class="{
                anomalous: row.anomaly_flags.length,
                isWhale: row.premium >= 100_000,
                isMegaWhale: row.premium >= 250_000,
                [tapeLean(row).cls]: true,
              }"
            >
              <td class="flag-col">
                <span v-if="row.premium >= 250_000" class="flag-chip label mega-whale-chip" title="Mega Whale trade ≥ $250,000">MEGA</span>
                <span v-else-if="row.premium >= 100_000" class="flag-chip label whale-chip" title="Whale trade ≥ $100,000">WHALE</span>
                <span v-else-if="!row.anomaly_flags.length" class="no-flag label">—</span>
                <span v-for="flag in row.anomaly_flags" :key="flag" class="flag-chip label" :class="flag">{{ anomalyLabel(flag) }}</span>
              </td>
              <td class="fig dim">{{ row.timestamp.slice(5, 16).replace('T', ' ') }}</td>
              <td class="tape-col-group">
                <span class="bias-chip label" :class="tapeLean(row).cls" :title="tapeLean(row).title">
                  {{ tapeLean(row).label }}
                </span>
              </td>
              <td>
                <span class="type-chip label" :class="row.right">{{ row.right === 'call' ? 'CALL' : 'PUT' }}</span>
              </td>
              <td>
                <span class="class-chip label" :class="tradeClassLabel(row).toLowerCase()">{{ tradeClassLabel(row) }}</span>
              </td>
              <td class="fig dim tape-col-group">{{ row.expiry ? shortDate(row.expiry) : '—' }}</td>
              <td class="fig num-col strike-cell">{{ usd(row.strike) }}</td>
              <td class="fig num-col tape-col-group stock-cell">
                <div class="stock-lockup">
                  <span class="stock-val">{{ (row.underlying_price ?? s?.spot) == null ? DASH : usd(row.underlying_price ?? s?.spot) }}</span>
                  <span v-if="moneynessInfo(row)" class="moneyness-tag label" :class="moneynessInfo(row)!.cls">{{ moneynessInfo(row)!.text }}</span>
                </div>
              </td>
              <td class="fig num-col tape-col-group" :title="row.premium_estimated ? 'Back-solved from notional' : 'Per-contract fill'">
                {{ pricePaid(row) == null ? DASH : num(pricePaid(row), 2) }}
              </td>
              <td class="fig num-col">{{ num(contractsOf(row), 0) }}</td>
              <td class="fig num-col premium-cell" :class="[row.right, { 'whale-prem': row.premium >= 100_000 }]">
                ${{ compact(row.premium) }}
                <small v-if="row.premium_estimated" class="est">≈</small>
              </td>
              <td class="tape-col-group">
                <span class="agg label" :class="aggressorLabel(row).cls" :title="aggressorLabel(row).cls === 'unknown' ? 'LSE does not report buy/sell on this print' : ''">
                  {{ aggressorLabel(row).label }}
                </span>
              </td>
              <td class="fig num-col">
                <span
                  class="edge-chip label"
                  :class="row.signed_premium != null ? (row.signed_premium >= 0 ? 'bull' : 'bear') : 'unsigned'"
                  :title="row.signed_premium == null
                    ? 'No buy/sell from feed — premium is unsigned notional only'
                    : `Signed $${compact(row.signed_premium)}`"
                >
                  <template v-if="row.signed_premium != null">
                    {{ row.signed_premium > 0 ? '+' : '−' }}${{ compact(Math.abs(row.signed_premium)) }}
                  </template>
                  <template v-else>${{ compact(row.premium) }} · unsig</template>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else-if="d?.flow_tape.length" class="no-tape compact-empty">
        <strong>NO PRINTS MATCH THIS TABLE VIEW</strong>
        <p>The source tape is loaded; change the Calls / Puts / Anomalies filter above.</p>
      </div>
      <div v-else class="no-tape">
        <strong>NO QUALIFIED TRADE TAPE</strong>
        <p v-if="d?.provider.activity_basis === 'chain_activity_proxy'">
          No prints cleared the noise filter — activity overlay is using chain volume × price (unsigned proxy), not a trade tape.
        </p>
        <p v-else>
          No prints cleared the current time and noise filters.
        </p>
        <p class="reject-hint label" v-if="d?.quality?.flow_rejected">
          Rejected:
          <template v-for="(n, k) in d.quality.flow_rejected" :key="k">
            <span v-if="typeof n === 'number' && n > 0"> {{ k }}={{ n }}</span>
          </template>
          · raw {{ d.quality.flow_prints_raw ?? 0 }}
          <template v-if="Number(d.quality.flow_rejected.outside_range || 0) > 0">
            · time window issue — live ignores From/To; clear dates or widen range
          </template>
          <template v-else>
            · try <b>RAW</b> noise filter or lower min premium
          </template>
        </p>
        <p class="reject-hint label" v-if="d?.quality?.flow_rejected?.print_ts_min">
          Prints span {{ d.quality.flow_rejected.print_ts_min }} → {{ d.quality.flow_rejected.print_ts_max }}
          · window {{ d.quality.flow_rejected.window_lower }} → {{ d.quality.flow_rejected.window_upper }}
          <template v-if="d.quality.flow_rejected.window_relaxed"> · auto-expanded</template>
        </p>
        <div class="tape-actions">
          <button type="button" class="label raw-btn" @click="setPreset('raw')">SWITCH TO RAW FILTERS</button>
          <button
            v-if="dateFrom || dateTo || Number(d?.quality?.flow_rejected?.outside_range || 0) > 0"
            type="button"
            class="label raw-btn"
            @click="clearDateFilters"
          >
            CLEAR DATE FILTERS
          </button>
        </div>
      </div>
    </Panel>

    </template><!-- /FLOW TAB -->

    <!-- Legacy market scanners are intentionally not reachable here: FlowView
         owns this global surface. Retain this branch while its shared fetching
         code remains available for migration and backward compatibility. -->
    <template v-else-if="false">

    <!-- Market-wide board is secondary — underlier workbench comes first -->
    <section class="unusual-secondary rise">
      <header class="unusual-head">
        <button
          type="button"
          class="unusual-toggle label"
          :aria-expanded="unusualOpen"
          @click="unusualOpen = !unusualOpen"
        >
          <span class="idx fig">05</span>
          <span>Unusual Flow · Market</span>
          <span class="unusual-meta">{{ flowBoardMeta }}</span>
          <span class="notes-chev">{{ unusualOpen ? '▴' : '▾' }}</span>
        </button>
        <div class="unusual-actions">
          <button
            type="button"
            class="label scan-btn"
            :disabled="unusual.loading.value"
            @click="unusualOpen = true; void scanLiveFlow()"
          >{{ unusual.loading.value ? 'SCANNING…' : 'SCAN LIVE FLOW' }}</button>
          <span class="label cov" v-if="unusual.data.value?.asof">
            AS OF {{ shortDate(unusual.data.value?.asof) }}
          </span>
        </div>
      </header>

      <div v-if="unusualOpen" class="unusual-body">
        <p v-if="unusual.error.value" class="note pad">{{ unusual.error.value }}</p>
        <div v-else class="table-container unusual-table">
          <table v-if="flowBoard.length" class="grid">
            <thead>
              <tr>
                <th class="label">Rank / Symbol</th>
                <th class="label num">Unusual</th>
                <th class="label">Flags</th>
                <th class="label num">Live Premium</th>
                <th class="label num">C / P Prints</th>
                <th class="label num">Price</th>
                <th class="label">Lean</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in flowBoard"
                :key="row.symbol"
                :class="{ active: row.symbol === symbol }"
                @click="loadSymbol(row.symbol)"
              >
                <td>
                  <span class="rank-idx fig">{{ String(row.activity_rank).padStart(2, '0') }}</span>
                  <span class="fig sym">{{ row.symbol }}</span>
                </td>
                <td class="num">
                  <div class="activity-score">
                    <span class="fig">{{ num(row.unusual_score ?? row.activity_score, 1) }}</span>
                    <i aria-hidden="true"><b :style="{ width: `${Math.min(100, row.unusual_score ?? row.activity_score)}%` }" /></i>
                  </div>
                </td>
                <td>
                  <div class="flag-stack">
                    <span
                      v-for="flag in row.flags.slice(0, 3)"
                      :key="flag"
                      :class="{ live: flag.includes('LIVE') || flag.includes('$') }"
                    >{{ flag }}</span>
                  </div>
                </td>
                <td class="fig num">
                  <template v-if="row.live && row.premium != null">
                    <strong class="live-value">{{ usd(row.premium) }}</strong>
                    <small class="flow-count">{{ row.print_count }} alerts</small>
                  </template>
                  <span v-else class="dim">NO LIVE TAPE</span>
                </td>
                <td class="fig num">
                  <span class="call">C{{ row.call_print_count }}</span>
                  <span class="sep">/</span>
                  <span class="put">P{{ row.put_print_count }}</span>
                </td>
                <td class="fig num" :class="tone((row.ret_1d ?? 0) * 100)">
                  {{ row.ret_1d == null ? DASH : signedPct((row.ret_1d ?? 0) * 100, 1) }}
                </td>
                <td>
                  <span class="side-pill" :class="row.context_side === 'long' ? 'pos' : row.context_side === 'short' ? 'neg' : 'neutral'">
                    {{ (row.context_side || 'neutral').toUpperCase() }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="note pad">
            No unusual flow rows yet.
            <button type="button" class="label scan-btn inline" @click="void scanLiveFlow()">SCAN LIVE FLOW</button>
            across liquid names + hottest local activity.
          </p>
        </div>
        <p class="note tiny pad">
          Click a row to load that underlier. C/P counts are identity only — not bought/sold direction.
        </p>
      </div>
    </section>

    <!-- Scan conviction board at page bottom for market-wide candidate exploration -->
    <OptionsConvictionBoard @select="loadSymbol" />

    <!-- Composite board+flow ranking — new bottom of page -->
    <section class="unusual-secondary rise">
      <header class="unusual-head">
        <button
          type="button"
          class="unusual-toggle label"
          :aria-expanded="opportunitiesOpen"
          @click="opportunitiesOpen = !opportunitiesOpen"
        >
          <span class="idx fig">06</span>
          <span>Live Opportunities</span>
          <span class="unusual-meta">{{ opportunitiesMeta }}</span>
          <span class="notes-chev">{{ opportunitiesOpen ? '▴' : '▾' }}</span>
        </button>
        <div class="unusual-actions">
          <button
            type="button"
            class="label scan-btn"
            :disabled="opportunities.loading.value"
            @click="opportunitiesOpen = true; void scanLiveOpportunities()"
          >{{ opportunities.loading.value ? 'SCANNING…' : 'SCAN LIVE' }}</button>
          <span class="label cov" v-if="opportunities.data.value?.asof_utc">
            AS OF {{ shortDate(opportunities.data.value?.asof_utc) }}
          </span>
        </div>
      </header>

      <div v-if="opportunitiesOpen" class="unusual-body">
        <p v-if="opportunities.error.value" class="note pad">{{ opportunities.error.value }}</p>
        <p
          v-else-if="opportunities.data.value?.available === false"
          class="note pad"
        >{{ opportunities.data.value?.reason || 'No live opportunities yet.' }}</p>
        <div v-else class="opportunities-table">
          <table v-if="opportunityRows.length" class="grid">
            <thead>
              <tr>
                <th class="label">Rank / Symbol</th>
                <th class="label num">Composite</th>
                <th class="label">Gate</th>
                <th class="label">Signal</th>
                <th class="label num">Ret 1D</th>
                <th class="label num">Spread</th>
                <th class="label num">OI</th>
                <th class="label num">DTE</th>
                <th class="label num">C/P Imb</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, idx) in opportunityRows"
                :key="row.symbol"
                :class="{ active: row.symbol === symbol, 'gate-fail': !row.gate_pass }"
                @click="loadSymbol(row.symbol)"
              >
                <td>
                  <span class="rank-idx fig">{{ String(idx + 1).padStart(2, '0') }}</span>
                  <span class="fig sym">{{ row.symbol }}</span>
                </td>
                <td class="num">
                  <div class="composite-meter">
                    <span class="fig" :class="tone(row.composite_score)">{{ signed(row.composite_score, 2) }}</span>
                    <i class="meter-track" aria-hidden="true">
                      <b class="meter-zero" />
                      <b class="meter-fill" :class="tone(row.composite_score)" :style="compositeMeterStyle(row.composite_score)" />
                    </i>
                  </div>
                </td>
                <td>
                  <span
                    class="gate-chip label"
                    :class="row.gate_pass ? 'pass' : 'fail'"
                    :title="gateTitle(row)"
                  >{{ row.gate_pass ? 'TRADABLE' : 'NO-TRADE' }}</span>
                </td>
                <td>
                  <span class="basis label" :class="row.signal_basis">{{ signalBasisLabel(row.signal_basis) }}</span>
                </td>
                <td class="fig num" :class="tone((row.ret_1d ?? 0) * 100)">
                  {{ row.ret_1d == null ? DASH : signedPct((row.ret_1d ?? 0) * 100, 1) }}
                </td>
                <td class="fig num">{{ pctFrac(row.spread_pct, 1) }}</td>
                <td class="fig num">{{ num(row.open_interest, 0) }}</td>
                <td class="fig num">{{ row.selected_dte == null ? DASH : `${row.selected_dte}D` }}</td>
                <td class="fig num" :class="imbalanceTone(row.call_put_imbalance)">
                  {{ row.call_put_imbalance == null ? DASH : signedPct((row.call_put_imbalance ?? 0) * 100, 0) }}
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="note pad">
            No opportunities yet.
            <button type="button" class="label scan-btn inline" @click="void scanLiveOpportunities()">SCAN LIVE</button>
            to recombine the latest conviction board + unusual flow boards.
          </p>
        </div>
        <p class="note tiny pad" v-if="opportunityRows.length">
          Click a row to load that underlier. NO-TRADE rows failed the gate on measured chain fields — shown, not hidden. Hover a gate chip for the reason.
        </p>
      </div>
    </section>

    </template><!-- /SCANNERS TAB -->

    <details v-if="d?.caveats?.length" class="methodology">
      <summary class="label">MODEL BOUNDARIES · {{ d.caveats.length }} notes</summary>
      <ol>
        <li v-for="note in d.caveats" :key="note">{{ note }}</li>
      </ol>
    </details>
  </div>
</template>

<style scoped>
.options-view {
  /* Options is a primary workspace, so it inherits the shell's shared
     semantic palette. Call/put colors retain their meaning across routes. */
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  min-height: calc(100% + (var(--s5) * 2));
  margin: calc(var(--s5) * -1);
  padding: var(--s4) var(--s4) var(--s6);
  min-width: 0;
  background: var(--void);
}

.options-view :deep(.panel) {
  border: 1px solid var(--rule);
  border-radius: 0;
  padding: 0;
  overflow: hidden;
  background: var(--panel);
}
.options-view :deep(.panel:hover) { border-color: var(--rule-hi); }
.options-view :deep(.panel > .head) {
  min-height: 36px;
  padding: 7px 11px;
  border-bottom: 1px solid var(--rule);
  background: var(--void-lift);
}
.options-view :deep(.panel > .head .idx) { color: var(--phosphor); }

/* ---- view tabs ----------------------------------------------------------- */
.view-tabs {
  display: flex;
  border-bottom: var(--hair) solid var(--rule);
  background: var(--void-lift);
  flex: 0 0 auto;
}
.view-tab {
  padding: 5px 14px;
  border: none;
  border-right: var(--hair) solid var(--rule);
  background: transparent;
  color: var(--ink-dim);
  cursor: pointer;
  font-weight: 700;
  letter-spacing: 0.06em;
  font-size: var(--t-micro);
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.view-tab:hover { color: var(--ink); background: var(--panel-hi); }
.view-tab.on {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border-bottom: 2px solid var(--phosphor);
}
.market-flow-link {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 5px 11px;
  color: var(--call-hi);
  border: 1px solid color-mix(in srgb, var(--call) 42%, var(--rule));
  border-radius: 4px;
  background: var(--call-wash);
  text-decoration: none;
}
.market-flow-link:hover { color: var(--phosphor); background: var(--phosphor-wash); text-decoration: none; }
.options-scope {
  margin: calc(var(--s2) * -1) 0 0;
  padding: 0 var(--s2);
  color: var(--ink-ghost);
  white-space: normal;
}

.command {
  display: flex;
  align-items: center;
  gap: 8px 10px;
  flex-wrap: wrap;
  min-height: 58px;
  padding: 8px 10px;
  border: 1px solid var(--rule-hi);
  border-radius: 6px;
  background: linear-gradient(180deg, #0a2537, #071b29);
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.35);
}
.identity {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  margin-right: 4px;
}
.symbol-lockup { display: flex; align-items: baseline; gap: 6px; line-height: 1; }
.active-symbol { font-size: 1.75rem; font-weight: 700; letter-spacing: -.055em; color: var(--ink); }
.slash { font: 300 1rem var(--font-display); color: var(--rule-hi); }
.view-name { font: 700 0.85rem var(--font-display); letter-spacing: .1em; color: var(--ink-dim); }
.observed { color: var(--ink-ghost); font-size: 9px; white-space: nowrap; }
.symbol-form { position: relative; flex: 0 1 140px; min-width: 110px; }
.mode-seg, .range-seg { flex: 0 0 auto; }
.history-day-bar {
  display: flex;
  align-items: center;
  gap: var(--s3);
  min-height: 32px;
  padding: 2px var(--s3);
  border: var(--hair) solid var(--rule);
  border-left: 3px solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  flex-wrap: wrap;
}
.history-day-select {
  min-height: 30px;
  min-width: 160px;
  padding: 0 28px 0 var(--s3);
  color: var(--ink);
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-hi);
}
.history-day-meta { color: var(--ink-dim); }
.jump-last-good {
  margin-left: auto;
  padding: 4px 10px;
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.jump-last-good:hover { color: var(--void); background: var(--phosphor); }
.focus-note { color: var(--phosphor); font-weight: 650; }
.symbol-entry {
  display: flex;
  height: 32px;
  border: 1px solid var(--rule-hi);
  border-radius: 4px;
  overflow: hidden;
  background: var(--void-lift);
}
.symbol-entry input {
  min-width: 0;
  width: 100%;
  padding: 0 8px;
  font: 600 0.95rem var(--font-data);
  letter-spacing: .06em;
  text-transform: uppercase;
}
.load-btn {
  min-width: 48px;
  padding: 0 8px;
  color: var(--phosphor);
  border-left: var(--hair) solid var(--rule);
  font-size: 10px;
}
.load-btn:disabled { opacity: 0.5; }
.search-hits {
  position: absolute;
  top: calc(100% + 2px);
  left: 0;
  right: 0;
  z-index: 40;
  margin: 0;
  padding: 0;
  list-style: none;
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-raise);
  max-height: 220px;
  overflow: auto;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.35);
}
.search-hits li {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: var(--s2);
  align-items: center;
  padding: 8px 10px;
  cursor: pointer;
  border-bottom: var(--hair) solid var(--rule);
  color: var(--ink-dim);
}
.search-hits li:hover,
.search-hits li.on { background: var(--phosphor-wash); color: var(--ink); }
.search-hits .tier { color: var(--ink-ghost); font-size: 9px; }
.search-hits .bars { color: var(--ink-faint); font-size: 9px; }

.loading-strip { border-color: var(--phosphor-dim); color: var(--ink-soft); background: var(--phosphor-wash); }
.loading-strip.soft { opacity: 0.9; }
.loading-strip strong { color: var(--phosphor); margin-left: 4px; }

.unusual-secondary {
  border: var(--hair) solid var(--rule);
  background: var(--panel);
}
.unusual-head {
  display: flex;
  align-items: center;
  gap: var(--s2);
  min-height: 34px;
  padding: 0 var(--s2) 0 0;
  border-bottom: var(--hair) solid var(--rule-faint);
  flex-wrap: wrap;
}
.unusual-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
  flex: 1 1 auto;
  min-width: 0;
  min-height: 34px;
  padding: 0 var(--s3);
  color: var(--ink-soft);
  text-align: left;
  font-weight: 700;
  letter-spacing: 0.06em;
}
.unusual-toggle:hover { color: var(--ink); background: var(--panel-hi); }
.unusual-toggle .idx { color: var(--phosphor); font-size: var(--t-micro); }
.unusual-meta {
  color: var(--ink-ghost);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.unusual-body { border-top: var(--hair) solid var(--rule); }
.unusual-actions { display: flex; align-items: center; gap: var(--s3); flex: 0 0 auto; margin-left: auto; padding-right: var(--s2); }
.scan-btn {
  padding: 5px 10px;
  border: var(--hair) solid var(--phosphor-dim);
  color: var(--phosphor);
  background: var(--phosphor-wash);
  letter-spacing: 0.08em;
  cursor: pointer;
}
.scan-btn:hover { border-color: var(--phosphor); }
.scan-btn:disabled { opacity: 0.5; cursor: wait; }
.scan-btn.inline { margin-left: 8px; vertical-align: middle; }
.unusual-table { max-height: 260px; overflow: auto; }
.unusual-table table { width: 100%; border-collapse: collapse; }
.unusual-table th,
.unusual-table td { padding: 5px 8px; border-bottom: var(--hair) solid var(--rule); text-align: left; }
.unusual-table th.num,
.unusual-table td.num { text-align: right; }
.unusual-table tbody tr { cursor: pointer; }
.unusual-table tbody tr:hover { background: var(--panel-hi); }
.unusual-table tbody tr.active { background: var(--phosphor-wash); box-shadow: inset 2px 0 0 var(--phosphor); }
.rank-idx { color: var(--ink-ghost); margin-right: 8px; font-size: 10px; }
.sym { letter-spacing: 0.04em; }
.flag-stack { display: flex; flex-wrap: wrap; gap: 4px; }
.flag-stack span {
  padding: 2px 6px;
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  font-size: 9px;
  letter-spacing: 0.06em;
}
.flag-stack span.live { color: var(--phosphor); border-color: color-mix(in srgb, var(--phosphor) 45%, var(--rule)); }
.activity-score { display: grid; grid-template-columns: 4ch 56px; justify-content: end; align-items: center; gap: 4px; }
.activity-score > i { display: block; height: 3px; overflow: hidden; background: var(--rule); }
.activity-score > i b { display: block; height: 100%; background: var(--phosphor); }
.live-value { color: var(--phosphor); }
.flow-count { display: block; color: var(--ink-ghost); font-size: 9px; }
.sep { color: var(--ink-ghost); margin: 0 2px; }
.side-pill {
  display: inline-block;
  padding: 2px 7px;
  border: var(--hair) solid var(--rule);
  font-size: 9px;
  letter-spacing: 0.08em;
}
.side-pill.pos { color: var(--call); border-color: color-mix(in srgb, var(--call) 40%, var(--rule)); }
.side-pill.neg { color: var(--put); border-color: color-mix(in srgb, var(--put) 40%, var(--rule)); }
.side-pill.neutral { color: var(--ink-ghost); }

/* ---- Live Opportunities: composite board+flow ranking ------------------ */
.opportunities-table { max-height: 260px; overflow: auto; }
.opportunities-table table { width: 100%; border-collapse: collapse; }
.opportunities-table th,
.opportunities-table td { padding: 5px 8px; border-bottom: var(--hair) solid var(--rule); text-align: left; }
.opportunities-table th.num,
.opportunities-table td.num { text-align: right; }
.opportunities-table tbody tr { cursor: pointer; }
.opportunities-table tbody tr:hover { background: var(--panel-hi); }
.opportunities-table tbody tr.active { background: var(--phosphor-wash); box-shadow: inset 2px 0 0 var(--phosphor); }
/* Shown, not hidden: NO-TRADE rows mute to ink-faint, but the gate chip,
   basis tag, composite meter and ret_1d keep their own explicit colours
   (later, higher-specificity rules), so the reasons stay legible. */
.opportunities-table tbody tr.gate-fail { color: var(--ink-faint); }
.gate-chip {
  display: inline-block;
  padding: 2px 7px;
  border: var(--hair) solid var(--rule);
  font-size: 9px;
  letter-spacing: 0.06em;
}
.gate-chip.pass { color: var(--long); border-color: color-mix(in srgb, var(--long) 45%, var(--rule)); background: var(--long-wash); }
.gate-chip.fail { color: var(--short); border-color: color-mix(in srgb, var(--short) 45%, var(--rule)); background: var(--short-wash); }
.basis {
  display: inline-block;
  padding: 2px 7px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
  font-size: 9px;
  letter-spacing: 0.06em;
}
.basis.both { border-color: var(--phosphor-dim); color: var(--phosphor); }
.basis.structure_only { border-color: color-mix(in srgb, var(--call) 40%, var(--rule)); color: var(--call-hi); }
.basis.flow_only { border-color: color-mix(in srgb, var(--put) 40%, var(--rule)); color: var(--put-hi); }
/* Signed meter: composite_score is a z-blend and can be negative, so the
   fill grows from a centre zero-line instead of a 0-100 left edge. */
.composite-meter { display: grid; grid-template-columns: 6ch 56px; justify-content: end; align-items: center; gap: 4px; }
.composite-meter .meter-track { position: relative; display: block; height: 3px; background: var(--rule); }
.composite-meter .meter-zero { position: absolute; left: 50%; top: -2px; bottom: -2px; width: var(--hair); background: var(--rule-hi); }
.composite-meter .meter-fill { position: absolute; top: 0; bottom: 0; }
.composite-meter .meter-fill.pos { background: var(--long); }
.composite-meter .meter-fill.neg { background: var(--short); }
.composite-meter .meter-fill.flat { background: var(--ink-ghost); }
.note.tiny { font-size: 11px; color: var(--ink-faint); }
.note.pad { padding: var(--s3) var(--s4); }
.cov { color: var(--ink-ghost); }
.segment { display: flex; border: 1px solid var(--rule-hi); border-radius: 4px; height: 32px; overflow: hidden; background: var(--void-lift); }
.seg { padding: 0 9px; color: var(--ink-faint); border-right: var(--hair) solid var(--rule); font-size: 10px; }
.seg:last-child { border-right: 0; }
.seg:hover { color: var(--ink); background: var(--panel-hi); }
.seg.on { color: #022015; background: var(--phosphor); font-weight: 800; }
.expiry-select {
  height: 32px;
  min-width: 120px;
  max-width: 180px;
  padding: 0 22px 0 8px;
  color: var(--ink);
  border: 1px solid var(--rule-hi);
  border-radius: 4px;
  background: var(--panel-hi);
  font-size: 10px;
}
/* ---- live lag badge + quick filters (always visible) ------------------- */
.live-filter-bar {
  display: flex;
  align-items: center;
  gap: 6px 10px;
  flex-wrap: wrap;
  min-height: 34px;
  padding: 3px 8px;
  border: 1px solid var(--rule-hi);
  border-radius: 6px;
  background: linear-gradient(90deg, rgba(8, 29, 43, 0.98), rgba(5, 23, 36, 0.98));
  overflow: hidden;
}
.live-filter-bar.live {
  border-left: 3px solid var(--phosphor);
  background: var(--phosphor-wash);
}
.live-filter-bar.warm,
.live-filter-bar.stale {
  border-left: 3px solid var(--warn);
  background: var(--warn-wash);
}
.live-filter-bar.proxy,
.live-filter-bar.missing {
  border-left: 3px solid var(--ink-ghost);
}
.live-filter-bar.history {
  border-left: 3px solid var(--ink-dim);
}
.live-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 0 1 auto;
}
.live-pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: 0 0 auto;
  background: var(--ink-ghost);
  border: var(--hair) solid var(--rule-hi);
}
/* Solid lamp only — no expanding neon ring */
.live-pulse.live {
  background: var(--phosphor);
  border-color: var(--phosphor-dim);
}
.live-pulse.stale {
  background: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 70%, var(--rule));
}
.live-pulse.history {
  background: var(--ink-dim);
  border-color: var(--rule-hi);
}
.live-pulse.pending {
  background: transparent;
  border-color: var(--ink-ghost);
}
.live-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.live-title {
  letter-spacing: 0.08em;
  font-weight: 800;
  color: var(--ink);
}
.live-badge.live .live-title { color: var(--phosphor); }
.live-badge.stale .live-title { color: var(--warn); }
.live-sub {
  font-size: 10px;
  color: var(--ink-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: min(42vw, 360px);
}
.live-lag {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0;
  padding: 2px 8px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  min-width: 52px;
}
.live-lag .label { color: var(--ink-faint); font-size: 8px; }
.live-lag .fig { font-size: 12px; color: var(--ink); font-weight: 700; }
.live-meta {
  color: var(--ink-ghost);
  font-size: 10px;
  flex: 0 1 auto;
  min-width: 0;
}
.quick-filters {
  display: flex;
  align-items: center;
  gap: 3px;
  flex-wrap: wrap;
  margin-left: auto;
}
.qf-lab {
  color: var(--ink-faint);
  font-size: 9px;
  margin-right: 2px;
  letter-spacing: 0.06em;
}
.qf-chip {
  min-height: 24px;
  padding: 0 7px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
  background: var(--void-lift);
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
}
.qf-chip:hover { color: var(--ink); border-color: var(--rule); }
.qf-chip.on {
  color: var(--void);
  background: var(--phosphor);
  border-color: var(--phosphor);
}
.qf-sep {
  width: 1px;
  height: 18px;
  background: var(--rule-hi);
  margin: 0 4px;
}

.filter-deck {
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
  padding: 6px 8px 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.filter-summary { color: var(--ink-dim); font-size: 10px; }
.filter-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.raw-btn.inline {
  margin-top: 0;
  padding: 3px 8px;
  font-size: 9px;
}
.tune {
  color: var(--phosphor);
  padding: 0 11px;
  height: 32px;
  border: 1px solid var(--phosphor-dim);
  border-radius: 4px;
  background: var(--phosphor-wash);
  font-size: 10px;
}
.tune.on { background: var(--phosphor-wash); }
.filters {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 1px;
  background: var(--rule);
  border: var(--hair) solid var(--rule);
}
.filters label {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 6px 8px;
  background: var(--panel);
  min-width: 0;
}
.filters input,
.filters select {
  width: 100%;
  min-height: 24px;
  padding: 2px 0;
  border-bottom: var(--hair) solid var(--rule-hi);
  font-family: var(--font-data);
  font-size: 12px;
  background: transparent;
  color: var(--ink);
}

.fault-strip { display: flex; align-items: center; gap: var(--s2); min-height: 28px; padding: 4px var(--s3); font-size: var(--t-small); color: var(--short); background: var(--short-wash); border-left: 2px solid var(--short); }
.fault-strip .label { color: inherit; }
.fault-strip button { margin-left: auto; color: inherit; }

.data-notes {
  display: flex;
  align-items: center;
  gap: var(--s2);
  min-height: 28px;
  padding: 4px var(--s3);
  border: 1px solid var(--rule);
  border-radius: 6px;
  background: rgba(8, 28, 42, 0.94);
  color: var(--ink-dim);
  font-size: var(--t-tiny);
}
.data-notes.open { flex-wrap: wrap; align-items: flex-start; }
.notes-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-soft);
  font-weight: 700;
  flex: 0 0 auto;
}
.notes-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warn);
}
.notes-chev { color: var(--ink-ghost); }
.notes-preview {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-ghost);
}
.data-notes ul {
  list-style: none;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 4px 0 0;
  padding: 0;
  color: var(--ink-dim);
}
.data-notes li { padding-left: 12px; border-left: 2px solid var(--rule-hi); line-height: 1.4; }

/* ---- compact KPI rail ------------------------------------------------- */
.kpi-rail {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 8px;
  background: transparent;
  border: 0;
  overflow: visible;
}
.kpi .dim { color: var(--ink-ghost); margin: 0 2px; }
.kpi {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  min-width: 0;
  min-height: 78px;
  padding: 10px 11px;
  border: 1px solid var(--rule);
  border-radius: 6px;
  background: linear-gradient(145deg, rgba(12, 39, 56, 0.98), rgba(6, 25, 38, 0.98));
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.14);
}
.kpi .label { color: var(--ink-faint); font-size: 9px; letter-spacing: 0.08em; line-height: 1.2; font-weight: 700; }
.kpi strong {
  font-size: 1.08rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--ink);
  line-height: 1.15;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.kpi em {
  font-style: normal;
  color: var(--ink-faint);
  font-size: 8px;
  line-height: 1.15;
}
.kpi.spot { border-color: color-mix(in srgb, var(--phosphor) 36%, var(--rule)); background: linear-gradient(145deg, rgba(18, 64, 70, 0.82), rgba(6, 27, 40, 0.98)); }
.kpi.spot strong { font-size: 1.28rem; color: var(--ink); font-weight: 750; }
.kpi.positive { border-color: color-mix(in srgb, var(--long) 32%, var(--rule)); }
.kpi.negative { border-color: color-mix(in srgb, var(--short) 32%, var(--rule)); }
.kpi.call strong, .kpi .call { color: var(--call); }
.kpi.put strong, .kpi .put { color: var(--put); }
.kpi .accent { color: var(--phosphor); }
.call-tag { color: var(--call); font-weight: 600; margin-left: 4px; }
.put-tag { color: var(--put); font-weight: 600; margin-left: 4px; }
.kpi-squeeze-body {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.squeeze-tag {
  padding: 1px 5px;
  border: var(--hair) solid color-mix(in srgb, var(--warn) 55%, var(--rule));
  background: var(--warn-wash);
  color: var(--warn);
  font-size: 8px;
  font-weight: 700;
}

/* ---- workbench: squeeze (narrower) + GEX map (dominant width) ----------- */
.workbench {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.workbench-top {
  display: grid;
  grid-template-columns: minmax(260px, 300px) minmax(500px, 1fr) minmax(250px, 290px);
  grid-auto-rows: clamp(430px, 46vh, 500px);
  gap: 8px;
  min-width: 0;
  align-items: stretch;
}
@media (max-width: 1180px) {
  .workbench-top { grid-template-columns: 1fr; }
}

.workbench .cell {
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
}
.workbench .gex-full { width: 100%; }
.workbench .flow-context-cell :deep(.body) { overflow: hidden; }
.workbench :deep(.panel) {
  height: 100%;
  min-height: 0;
}
.workbench :deep(.body) {
  padding: 0;
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}
.workbench :deep(.head) {
  padding: 6px 12px;
  min-height: 32px;
}
.gex-meta-badge.flip { color: var(--warn); }

.view-label {
  font-size: 9px;
  color: var(--phosphor-dim);
  font-weight: 700;
  letter-spacing: 0.12em;
  margin-left: 6px;
  white-space: nowrap;
}

.command-right {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}
.scope-chip {
  padding: 6px 9px;
  color: var(--phosphor);
  border: 1px solid color-mix(in srgb, var(--phosphor) 38%, var(--rule));
  border-radius: 4px;
  background: var(--phosphor-wash);
}

.long-it-btn {
  padding: 2px 8px;
  border: var(--hair) solid color-mix(in srgb, var(--call) 50%, var(--rule));
  background: color-mix(in srgb, var(--call) 12%, transparent);
  color: var(--call);
  font-size: 10px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 4px;
}
.long-it-btn .info-icon {
  font-size: 9px;
  opacity: 0.8;
}

.panel-action-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  max-width: min(70vw, 640px);
  justify-content: flex-end;
}

.chart-legend-pill {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.04em;
  padding: 1px 4px;
}
.chart-legend-pill.price { color: var(--ink-dim); }
.chart-legend-pill.call { color: var(--call); }
.chart-legend-pill.put { color: var(--put); }
.chart-legend-pill.flip { color: var(--warn); }
.chart-legend-pill.spot { color: var(--ink); }

.range-select, .density-days-select {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink);
  font-size: 9px;
  padding: 1px 4px;
  font-weight: 700;
}

.gex-meta-badge {
  font-size: 9px;
  color: var(--ink-dim);
  font-family: var(--font-data);
  margin-left: 6px;
}

.gex-aux {
  flex: 0 0 auto;
  border-top: var(--hair) solid var(--rule);
  background: var(--void-lift);
}
.gex-aux > summary {
  cursor: pointer;
  padding: 3px 6px;
  color: var(--ink-faint);
  list-style: none;
}
.gex-aux > summary::-webkit-details-marker { display: none; }
.gex-aux[open] > summary {
  border-bottom: var(--hair) solid var(--rule);
  color: var(--ink-dim);
}

.expiry-gex.compact {
  margin: 0;
  padding: 4px 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 72px;
  overflow: auto;
}
.expiry-gex-row {
  display: grid;
  grid-template-columns: 48px 28px 1fr 52px;
  align-items: center;
  gap: 4px;
  min-height: 14px;
}
.expiry-gex-row .exp { color: var(--ink-dim); font-size: 9px; }
.expiry-gex-row .dte { color: var(--ink-ghost); text-align: right; font-size: 9px; }
.expiry-gex-row .bar-track {
  height: 4px;
  background: var(--rule);
  overflow: hidden;
}
.expiry-gex-row .bar-track i {
  display: block;
  height: 100%;
  min-width: 2px;
}
.expiry-gex-row .bar-track i.pos { background: var(--call); }
.expiry-gex-row .bar-track i.neg { background: var(--put); }
.expiry-gex-row .fig { text-align: right; font-size: 10px; color: var(--ink-soft); }
.empty-note { color: var(--ink-dim); padding: 10px 6px; font-size: 12px; }

.tape-panel-full { min-height: 280px; width: 100%; }
.prob-calc-panel {
  min-height: 250px;
  margin-top: 0;
}
.prob-calc-panel :deep(.body) {
  padding: 0;
}
.prob-calc-panel :deep(.head) {
  padding: 6px 12px;
  min-height: 32px;
}
.table-scroll-tall { max-height: min(52vh, 520px) !important; }
.tape-toolbar {
  display: flex;
  flex-direction: column;
  min-height: 28px;
  border-block: var(--hair) solid var(--rule);
  background: var(--void-lift);
}
/* Main row: tabs flush left, right controls flush right */
.tape-toolbar-main {
  display: flex;
  align-items: stretch;
  min-height: 28px;
}
.tape-toolbar-right {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: 0 var(--s2);
  margin-left: auto;
  flex-shrink: 0;
}
.tape-tabs {
  display: flex;
  align-self: stretch;
  overflow-x: auto;
  /* Hide scrollbar but keep scrollable — avoids layout jump on narrow panes */
  scrollbar-width: none;
}
.tape-tabs::-webkit-scrollbar { display: none; }
.tape-tabs button {
  padding: 0 10px;
  color: var(--ink-faint);
  border-right: var(--hair) solid var(--rule);
  white-space: nowrap;
  flex-shrink: 0;
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.tape-tabs button:first-child { border-left: var(--hair) solid var(--rule); }
.tape-tabs button:hover:not(.on) { color: var(--ink-soft); background: var(--panel-hi); }
.tape-tabs button.on { color: var(--ink); background: var(--panel-hi); font-weight: 700; box-shadow: inset 0 -2px var(--phosphor); }
/* Tab count badge */
.tab-count {
  display: inline-block;
  margin-left: 4px;
  padding: 0 4px;
  background: var(--panel-raise);
  color: var(--ink-ghost);
  font-size: 9px;
  font-weight: 700;
  vertical-align: middle;
}
/* NEAR tab: slightly more prominent than the generic tabs — it's the actionable default */
.tape-tabs .near-tab { color: var(--call-hi, var(--call)); font-weight: 700; }
.tape-tabs .near-tab:hover:not(.on) { color: var(--call); background: var(--call-wash); }
.tape-tabs .near-tab.on { color: var(--call-hi, var(--call)); background: var(--call-wash); box-shadow: inset 0 -2px var(--call); }
.near-count {
  display: inline-block;
  margin-left: 3px;
  color: var(--call-hi, var(--call));
  font-weight: 700;
}
.near-window-control {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 0 6px;
  border-left: var(--hair) solid var(--rule-hi);
}
.near-dte-chip {
  min-height: 20px;
  padding: 0 6px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-faint);
  background: transparent;
  font-size: 9px;
  font-weight: 700;
  cursor: pointer;
  letter-spacing: 0.05em;
}
.near-dte-chip:hover { color: var(--call-hi, var(--call)); border-color: var(--call); }
.near-dte-chip.on {
  color: var(--call-hi, var(--call));
  border-color: color-mix(in srgb, var(--call) 60%, var(--rule));
  background: var(--call-wash);
}
.sort-control { display: flex; align-items: center; gap: var(--s2); }
.sort-control select { min-height: 22px; padding: 0 18px 0 6px; color: var(--ink); border: var(--hair) solid var(--rule-hi); background: var(--panel); font-size: 10px; }
.anomaly-method { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-dim); font: 9px var(--font-display); letter-spacing: .06em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px; }
.anomaly-method i { width: 7px; height: 7px; border-radius: 50%; background: var(--ink-ghost); flex: 0 0 auto; }
.anomaly-method i.live { background: var(--phosphor); }
.anomaly-method i.stale { background: var(--warn); }
.anomaly-method i.history { background: var(--ink-dim); }
.table-scroll { overflow: auto; max-height: 420px; }
table { width: 100%; border-collapse: collapse; font-size: var(--t-tiny); }
th, td { padding: 3px 8px; border-bottom: var(--hair) solid var(--rule); text-align: left; white-space: nowrap; }
th { position: sticky; top: 0; background: var(--panel); z-index: 1; color: var(--ink-dim); }
td.fig, th.num-col, td.num-col { font-size: var(--t-small); }
.flag-col { min-width: 80px; }
/* One consistent anomaly-flag treatment. The abbreviation (PRM/VOL/CLU/SWP)
   already carries the sub-type, so color stays a single "flagged" signal
   instead of four competing hues — and never phosphor, which means
   live-now everywhere else on this page. */
.flag-chip {
  display: inline-block;
  margin: 1px 4px 2px 0;
  padding: 2px 6px;
  color: var(--void);
  background: var(--warn);
  border: var(--hair) solid var(--warn);
  font-size: var(--t-micro);
  font-weight: 800;
  letter-spacing: .04em;
}
/* Mega-whale: same warn fill, heavier weight — no glow, no gradient */
.flag-chip.mega-whale-chip {
  background: var(--warn);
  color: var(--void);
  border-color: var(--warn);
  font-weight: 800;
}
/* Whale: dimmed wash so it reads below mega */
.flag-chip.whale-chip {
  background: var(--warn-wash);
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 55%, var(--rule));
  font-weight: 700;
}
.no-flag { color: var(--ink-ghost); }
/* Anomalous rows: left rule only, no gradient wash */
tr.anomalous { box-shadow: inset 3px 0 0 var(--warn); }
/* Whale rows: progressively heavier left rule, flat background */
tr.isWhale {
  background: var(--warn-wash);
  box-shadow: inset 3px 0 0 var(--warn);
}
tr.isMegaWhale {
  background: color-mix(in srgb, var(--warn) 14%, var(--panel));
  box-shadow: inset 4px 0 0 var(--warn);
}
tr.anomalous td, tr.isWhale td, tr.isMegaWhale td { color: var(--ink); }
.num-col { text-align: right; }
.dim { color: var(--ink-dim); }
.tape-table th { font-size: 9px; letter-spacing: 0.06em; border-bottom: var(--hair) solid var(--rule-hi); }
.tape-table td { padding: 5px 8px; font-size: var(--t-tiny); }
/* Row states: hover lifts the surface; anomalous rows keep their warn wash
   underneath so the flag cue never gets washed out by the hover state. */
.tape-table tbody tr { transition: background var(--dur-fast) var(--ease-out); }
.tape-table tbody tr:hover { background: var(--panel-hi); }
.tape-table tbody tr.anomalous:hover {
  background: color-mix(in srgb, var(--warn) 14%, var(--panel-hi));
}
/* Quiet column-group dividers — Lean/Side/Class, Expiry/Strike, the
   economics group, then Aggressor/edge — so the eye can chunk the row
   instead of parsing twelve flat columns in one pass. */
.tape-table th.tape-col-group,
.tape-table td.tape-col-group {
  border-left: var(--hair) solid var(--rule-faint);
}
.tape-premium-head { color: var(--ink-soft); }
/* Premium is the number this table exists to show — it gets the only
   large, bold figure in the row; everything else recedes around it. */
.premium-cell {
  font-size: var(--t-body);
  font-weight: 700;
  letter-spacing: var(--track-tight);
}
.premium-cell .est { font-size: var(--t-micro); font-weight: 600; margin-left: 1px; }
.type-chip, .agg, .bias-chip, .class-chip, .edge-chip {
  display: inline-block;
  min-width: 46px;
  padding: 2px 6px;
  text-align: center;
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-hi);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.05em;
}
.type-chip.call { color: var(--call); border-color: color-mix(in srgb, var(--call) 45%, var(--rule)); background: var(--call-wash); }
.type-chip.put { color: var(--put); border-color: color-mix(in srgb, var(--put) 45%, var(--rule)); background: var(--put-wash); }
td.call { color: var(--call); }
td.put { color: var(--put); }
.agg.buy { color: var(--long); background: var(--long-wash); border-color: color-mix(in srgb, var(--long) 40%, var(--rule)); font-weight: 800; }
.agg.sell { color: var(--short); background: var(--short-wash); border-color: color-mix(in srgb, var(--short) 40%, var(--rule)); font-weight: 800; }
.agg.unknown { color: var(--ink-faint); font-size: 9px; }
.bias-chip.bull, .edge-chip.bull { color: var(--call); border-color: color-mix(in srgb, var(--call) 50%, var(--rule)); background: var(--call-wash); }
.bias-chip.bear, .edge-chip.bear { color: var(--put); border-color: color-mix(in srgb, var(--put) 50%, var(--rule)); background: var(--put-wash); }
.bias-chip.call { color: var(--call); border-color: color-mix(in srgb, var(--call) 40%, var(--rule)); background: var(--call-wash); }
.bias-chip.put { color: var(--put); border-color: color-mix(in srgb, var(--put) 40%, var(--rule)); background: var(--put-wash); }
.bias-chip.unsigned, .edge-chip.unsigned { color: var(--ink-ghost); background: var(--panel-hi); border-color: var(--rule); }
/* Trade class is a classification, not a live/selection state — phosphor is
   reserved for that, so SWEEP reads via weight + a raised neutral fill
   instead of borrowing the page's one accent color. BLOCK keeps the warn
   "large print" cue it already had. */
.class-chip.sweep { color: var(--ink); border-color: var(--ink-faint); background: var(--panel-raise); font-weight: 800; }
.class-chip.block { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 55%, var(--rule)); background: var(--warn-wash); font-weight: 800; }
.class-chip.single { color: var(--ink-dim); background: transparent; }
.est { color: var(--ink-faint); margin-left: 2px; font-size: 9px; }
/* Notes always scannable — denser strip for power-user desk */
.data-notes {
  min-height: 32px;
  border-left: 3px solid var(--warn);
  background: color-mix(in srgb, var(--warn) 6%, var(--panel));
}
.data-notes.open ul {
  max-height: 120px;
  overflow: auto;
}
.no-tape { min-height: 180px; display: grid; place-content: center; justify-items: center; gap: var(--s2); color: var(--ink-dim); text-align: center; padding: var(--s4); }
.no-tape strong { font: 650 var(--t-small) var(--font-display); letter-spacing: .08em; color: var(--ink); }
.no-tape p { max-width: 54ch; font-size: var(--t-small); }
.reject-hint { max-width: 60ch; color: var(--ink-faint); line-height: 1.5; }
.reject-hint b { color: var(--warn); }
.raw-btn {
  margin-top: var(--s1);
  padding: 6px 12px;
  border: var(--hair) solid var(--phosphor-dim);
  color: var(--phosphor);
  background: var(--phosphor-wash);
  letter-spacing: 0.08em;
  cursor: pointer;
}
.raw-btn:hover { border-color: var(--phosphor); }
.tape-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.tape-glyph { font: 2.25rem var(--font-display); color: var(--rule-hi); line-height: 1; }
.compact-empty { min-height: 140px; }

.methodology {
  border: var(--hair) solid var(--rule);
  background: var(--panel);
  color: var(--ink-faint);
}
.methodology > summary {
  cursor: pointer;
  padding: 6px var(--s3);
  list-style: none;
  letter-spacing: 0.06em;
}
.methodology > summary::-webkit-details-marker { display: none; }
.methodology[open] > summary {
  border-bottom: var(--hair) solid var(--rule);
  color: var(--ink-dim);
}
.methodology ol {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 2px var(--s4);
  padding: 6px var(--s3) 8px var(--s5);
  margin: 0;
  font-size: 10px;
  line-height: 1.35;
}

@media (max-width: 1100px) {
  .kpi-rail { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .tape-toolbar { flex-wrap: wrap; padding-block: 6px; }
  .anomaly-method { width: 100%; margin-left: 0; max-width: none; }
  .unusual-meta { display: none; }
  .live-sub { max-width: 50vw; }
  .quick-filters { margin-left: 0; width: 100%; }
}

@media (max-width: 840px) {
  .kpi-rail { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .methodology ol { grid-template-columns: 1fr; }
  .tape-tabs { overflow-x: auto; width: 100%; }
  .sort-control { width: 100%; }
  .unusual-head { flex-direction: column; align-items: stretch; }
  .unusual-actions { margin-left: 0; padding: 0 8px 8px; }
  .tune { margin-left: 0; }
}
/* Absent-measurement state. Deliberately reads as a warning, not an empty
   state: "no data" and "a calm market" must never look alike. */
.unmeasured {
  padding: 1.25rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  border: var(--hair) solid var(--phosphor-dim);
  border-left: 3px solid var(--phosphor);
  background: var(--panel-raise);
}

.unmeasured-head {
  color: var(--phosphor);
  font: 700 11px var(--font-display);
  letter-spacing: 0.08em;
}

.unmeasured-body {
  margin: 0;
  font-size: var(--t-small);
  line-height: 1.6;
  color: var(--ink-soft);
  white-space: normal;
}

.unmeasured-body b {
  color: var(--ink);
}

.unmeasured-fix {
  color: var(--ink-faint);
  white-space: normal;
  line-height: 1.5;
}
.unmeasured-fix.warn { color: var(--warn); }
.unmeasured-actions {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

/* Stock Price column & Moneyness tags */
.stock-head { color: var(--phosphor); }
.stock-cell { text-align: right; }
.stock-lockup {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
  line-height: 1.1;
}
.stock-val {
  font-family: var(--font-data);
  font-weight: 600;
  color: var(--ink);
}
.moneyness-tag {
  font-size: 8.5px;
  font-weight: 700;
  padding: 1px 4px;
  letter-spacing: 0.05em;
  line-height: 1;
}
.moneyness-tag.itm {
  color: var(--long);
  background: var(--long-wash);
  border: var(--hair) solid color-mix(in srgb, var(--long) 30%, var(--rule));
}
.moneyness-tag.otm {
  color: var(--ink-ghost);
  background: transparent;
}
.moneyness-tag.atm {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
}


/* Whale tab highlight — tokens only, no !important */
.whale-tab.on {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 55%, var(--rule));
  background: var(--warn-wash);
  box-shadow: inset 0 -2px var(--warn);
}
/* Whale row hover: lift without overriding the left-rule cue */
tr.isWhale:hover {
  background: color-mix(in srgb, var(--warn) 10%, var(--panel-hi));
}
tr.isMegaWhale:hover {
  background: color-mix(in srgb, var(--warn) 18%, var(--panel-hi));
}
/* Premium cell on whale rows — weight emphasis, no glow */
.whale-prem { font-weight: 700; }
.strike-cell { font-weight: 600; }

/* Tape Stalker Cards View */
.tape-cards-container {
  padding: 10px;
  background: var(--void);
  max-height: min(60vh, 560px);
  overflow-y: auto;
}
.tape-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.tape-stalker-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  transition: background var(--dur-fast) var(--ease-out);
}
.tape-stalker-card.bull {
  border-left: 3px solid var(--call);
  background: var(--call-wash);
}
.tape-stalker-card.bear {
  border-left: 3px solid var(--put);
  background: var(--put-wash);
}
.tape-stalker-card.isWhale {
  border-color: color-mix(in srgb, var(--warn) 55%, var(--rule));
}
.tape-stalker-card.isMegaWhale {
  border-color: var(--warn);
  border-width: 1px 1px 1px 3px;
}
.card-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
}
.type-pill {
  font: 800 10px var(--font-display);
  padding: 1px 6px;
}
.type-pill.call { color: var(--call-hi, var(--call)); background: var(--call-wash); border: var(--hair) solid color-mix(in srgb, var(--call) 40%, var(--rule)); }
.type-pill.put { color: var(--put-hi, var(--put)); background: var(--put-wash); border: var(--hair) solid color-mix(in srgb, var(--put) 40%, var(--rule)); }
.lean-pill {
  font: 700 9px var(--font-display);
  padding: 1px 5px;
}
.lean-pill.bull { color: var(--call-hi, var(--call)); }
.lean-pill.bear { color: var(--put-hi, var(--put)); }
.ts-time { font: 500 10px var(--font-data); color: var(--ink-dim); margin-left: auto; }
.card-body-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 0;
  border-y: 1px solid var(--rule-faint);
}
.strike-box, .prem-box {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.strike-box .strike-label, .prem-box .prem-label {
  font: 700 8px var(--font-display);
  color: var(--ink-dim);
}
.strike-box .strike-val {
  font: 700 15px var(--font-data);
  color: var(--ink);
}
.prem-box { align-items: flex-end; }
.prem-box .prem-val {
  font: 700 15px var(--font-data);
}
.prem-box.call .prem-val { color: var(--call-hi, var(--call)); }
.prem-box.put .prem-val { color: var(--put-hi, var(--put)); }
.fill-sub { font: 500 9px var(--font-data); color: var(--ink-faint); }
.card-foot-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.exp-tag { font: 500 9px var(--font-data); color: var(--ink-dim); }
</style>
