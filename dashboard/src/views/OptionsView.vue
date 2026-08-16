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
import { compact, num, optUsd, pctFrac, shortDate, signed, signedPct, tone, usd } from '@/format'
import Panel from '@/components/Panel.vue'
import GammaExposureMap from '@/components/GammaExposureMap.vue'
import SqueezeScreener from '@/components/SqueezeScreener.vue'
import OptionsFlowContext from '@/components/OptionsFlowContext.vue'
import OptionsConvictionBoard from '@/components/OptionsConvictionBoard.vue'
import OptionsDirectionBrief from '@/components/OptionsDirectionBrief.vue'

import LoadingState from '@/components/LoadingState.vue'
import { buildOptionsDirection } from '@/optionsDirection'
import { activityLeanRead } from '@/optionsTape'
import { loadWatchlist, toggleWatchlistSymbol, watchlistHas } from '@/watchlist'

type NoisePreset = 'strict' | 'balanced' | 'raw'
type TapeView = 'near' | 'all' | 'whales' | 'anomalies' | 'calls' | 'puts' | 'sweeps' | 'blocks' | 'itm' | 'unusual' | 'momentum' | 'moonshot'
type TapeSort = 'near-signed' | 'newest' | 'premium' | 'anomaly'
type PremiumFloor = 0 | 25_000 | 50_000 | 100_000 | 250_000 | 500_000 | 1_000_000

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
/** Match backend default so the list and print counts stay aligned. */
const tapeLimit = ref(500)
/** Default to near-dated signed flow so actionable prints show first.
 *  User can switch to 'all' to see the full tape without DTE restriction. */
const tapeView = ref<TapeView>('near')
/** Sort default: near-term signed first (most actionable), then newest. */
const tapeSort = ref<TapeSort>('near-signed')
/** Upper DTE cutoff for the 'near' view — 0-30d means this calendar month. */
const nearDteMax = ref(30)
const tapeDisplayMode = ref<'table' | 'cards'>('table')
const filterRecoveryNotice = ref<string | null>(null)
const filtersOpen = ref(false)
/** Market-wide unusual board is secondary — underlier analysis comes first. */
const unusualOpen = ref(false)
/** Locked gamma strike for GEX focus. */
const focusStrike = ref<number | null>(null)
/** Prevents feedback loop when History auto-fills dateTo from the response. */
const historyAsOfSyncing = ref(false)
/**
 * Suppresses the filter watcher while a symbol load resets expiry/focus.
 * Without this, first open / ticker change fires a second debounced refresh
 * that can supersede the chain request and leave the map blank.
 */
const symbolLoadSyncing = ref(false)
const PREMIUM_FLOORS: PremiumFloor[] = [0, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]
const book = ref(loadWatchlist())
const onBook = computed(() => watchlistHas(book.value, symbol.value))

function toggleBook(): void {
  book.value = toggleWatchlistSymbol(book.value, symbol.value).symbols
}

const historyFrom = ref('')
const historyTo = ref('')
const historyLoading = ref(false)
const historyError = ref<string | null>(null)
const historyTape = ref<import('@/api').MarketFlowPrint[]>([])
const historyTapeMeta = ref('')

async function loadHistoryTape(): Promise<void> {
  historyLoading.value = true
  historyError.value = null
  try {
    const payload = await api.flowTape({
      symbol: symbol.value,
      from: historyFrom.value || dateFrom.value || undefined,
      to: historyTo.value || dateTo.value || undefined,
      minPremium: minPremium.value,
    })
    historyTape.value = payload.tape ?? []
    historyTapeMeta.value = `${payload.print_count} prints · ${payload.feed_status}`
    if (payload.warnings?.length) historyError.value = payload.warnings.join(' · ')
  } catch (err) {
    historyError.value = err instanceof Error ? err.message : 'History tape unavailable'
    historyTape.value = []
  } finally {
    historyLoading.value = false
  }
}

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
  { intervalMs: 120_000, enabled: () => unusualOpen.value },
)

watch(unusualOpen, (open) => {
  if (open && !unusual.data.value) void unusual.refresh()
})

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
  { intervalMs: 120_000, enabled: () => opportunitiesOpen.value },
)

watch(opportunitiesOpen, (open) => {
  if (open && !opportunities.data.value) void opportunities.refresh()
})

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
 * C/P premium from the returned tape when present so the KPI matches the flow
 * list. Falls back to summary window aggregates only when the tape is empty.
 */
const flowPremSplit = computed(() => {
  const tape = d.value?.flow_tape ?? []
  let call = 0
  let put = 0
  if (tape.length) {
    for (const row of tape) {
      const prem = Number(row.premium)
      if (!Number.isFinite(prem) || prem < 0) continue
      if (row.right === 'call') call += prem
      else if (row.right === 'put') put += prem
    }
  }
  if (call + put <= 0) {
    call = s.value?.call_premium ?? 0
    put = s.value?.put_premium ?? 0
  }
  const ratio = put > 0 ? call / put : null
  return {
    call: call > 0 ? call : null,
    put: put > 0 ? put : null,
    ratio,
  }
})

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
    if (historyAsOfSyncing.value || symbolLoadSyncing.value) return
    refreshDebounced()
  },
)

function cleanTicker(term: string): string {
  return term.trim().toUpperCase().replace(/[^A-Z0-9.-]/g, '').slice(0, 10)
}

/**
 * Load a symbol and refresh options intelligence.
 *
 * Wrong-underlier paint is prevented by `payloadMatches` (data only surfaces
 * when `data.symbol === symbol`). We only blank cached data when the ticker
 * actually changes — a same-symbol reload keeps the last good chain visible
 * so a failed refresh cannot make the map permanently disappear.
 */
function loadSymbol(raw: string, { pushRoute = true } = {}): void {
  const clean = cleanTicker(raw)
  if (!clean) return
  const changed = clean !== symbol.value
  // Same ticker already in flight — do not stack a second request that can
  // clear/supersede the first and leave the chain empty.
  if (!changed && resource.loading.value) return

  symbolLoadSyncing.value = true
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
  void resource.refresh({ clear: changed }).finally(() => {
    // Allow filter mutations after this tick so expiry reset does not queue
    // a second /api/options call behind the symbol load.
    queueMicrotask(() => { symbolLoadSyncing.value = false })
  })
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

// An exact expiry can stop clearing the quality gates after Min OI / spread /
// DTE changes. Falling back to ALL keeps the rest of the chain visible while
// making the recovery explicit instead of rendering an apparently broken
// workspace with a now-invalid select value.
watch(
  () => resource.data.value,
  (payload) => {
    if (!payload || payload.symbol !== symbol.value) return
    if (selectedExpiry.value === 'all' || selectedExpiry.value === 'nearest') return
    if (String(payload.filters?.expiry ?? '') !== selectedExpiry.value) return
    if ((payload.quality?.chain_contracts_raw ?? 0) <= 0) return
    if ((payload.quality?.chain_contracts_included ?? 0) > 0) return
    const failedExpiry = selectedExpiry.value
    selectedExpiry.value = 'all'
    focusStrike.value = null
    filterRecoveryNotice.value = `${shortDate(failedExpiry)} has no contracts that clear the active quality filters. Showing all expiries.`
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
  if (resource.loading.value || symbolLoadSyncing.value) return
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
const leanRead = computed(() => {
  if (s.value?.activity_lean) {
    return activityLeanRead({
      activity_lean: s.value.activity_lean,
      activity_lean_source: s.value.activity_lean_source,
      activity_lean_label: s.value.activity_lean_label,
      decision_authorized: s.value.decision_authorized,
    })
  }
  const call = flowPremSplit.value.call ?? 0
  const put = flowPremSplit.value.put ?? 0
  const total = call + put
  const imb = total > 0 ? (call - put) / total : 0
  const lean = total <= 0 || Math.abs(imb) < 0.15 ? 'neutral' : imb > 0 ? 'bullish' : 'bearish'
  return activityLeanRead({
    activity_lean: lean,
    activity_lean_source: total > 0 && Math.abs(imb) >= 0.15 ? 'call_put_premium' : 'none',
    activity_lean_label: lean.toUpperCase(),
    decision_authorized: false,
  })
})
const expiry = computed(() => d.value?.chain_context)
const historyMeta = computed(() => d.value?.history)
const historyDays = computed(() => historyMeta.value?.available_dates ?? [])
/**
 * True only while a network request is in flight.
 * Previously this also required `payloadMatches`, so a failed first load
 * (or a ticker switch that cleared data) left the UI stuck on "CALCULATING"
 * forever with no chain — even though loading had finished.
 */
const loadingSymbol = computed(() => resource.loading.value)
/** First paint / post-error empty: no matching payload and nothing in flight. */
const chainMissing = computed(() => !payloadMatches.value && !resource.loading.value)

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
  // No payload yet — do not claim measurable (avoids empty chart flash).
  if (!d.value) return false
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
  if (fromSummary != null && Number.isFinite(fromSummary)) return fromSummary
  const pct = side === 'call' ? keyLevels.value?.call_wall_pct : keyLevels.value?.put_wall_pct
  if (pct != null && Number.isFinite(pct)) return pct
  const spot = s.value?.spot
  const wall = side === 'call' ? s.value?.call_wall : s.value?.put_wall
  if (spot == null || spot <= 0 || wall == null || wall <= 0) return null
  const calc = (wall - spot) / spot
  return Number.isFinite(calc) ? calc : null
}

function isItm(row: OptionsTapeRow): boolean {
  const spotPrice = row.underlying_price ?? d.value?.summary?.spot
  if (spotPrice == null || spotPrice <= 0 || row.strike == null || row.strike <= 0) return false
  return row.right === 'call' ? spotPrice > row.strike : spotPrice < row.strike
}

function moneynessInfo(row: OptionsTapeRow): { text: string; cls: 'itm' | 'otm' | 'atm' } | null {
  const spotPrice = row.underlying_price ?? d.value?.summary?.spot
  if (spotPrice == null || spotPrice <= 0 || row.strike == null || row.strike <= 0) return null
  const diffPct = ((spotPrice - row.strike) / row.strike) * 100
  if (!Number.isFinite(diffPct)) return null
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
      return row.trade_class === 'sweep' || row.is_sweep === true || row.anomaly_flags.includes('sweep_burst')
    }
    if (tapeView.value === 'blocks') return row.trade_class === 'block' || row.is_block === true
    if (tapeView.value === 'unusual') return row.is_unusual === true || (row.presets ?? []).includes('unusual')
    if (tapeView.value === 'momentum') return row.is_momentum === true || (row.presets ?? []).includes('momentum')
    if (tapeView.value === 'moonshot') return row.is_moonshot === true || (row.presets ?? []).includes('moonshot')
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
  let calls = 0
  let puts = 0
  let anomalies = 0
  let unusual = 0
  let momentum = 0
  let moonshot = 0
  for (const r of rows) {
    if (r.trade_class === 'sweep' || r.is_sweep === true || r.anomaly_flags.includes('sweep_burst')) sweeps += 1
    if (r.trade_class === 'block' || r.is_block === true) blocks += 1
    if (r.premium >= 100_000) whales += 1
    if (isItm(r)) itm += 1
    if (r.right === 'call') calls += 1
    if (r.right === 'put') puts += 1
    if (r.anomaly_flags.length > 0) anomalies += 1
    if (r.is_unusual || (r.presets ?? []).includes('unusual')) unusual += 1
    if (r.is_momentum || (r.presets ?? []).includes('momentum')) momentum += 1
    if (r.is_moonshot || (r.presets ?? []).includes('moonshot')) moonshot += 1
    if (r.expiry) {
      const dteDays = Math.ceil((new Date(r.expiry).getTime() - now.getTime()) / 86_400_000)
      if (dteDays >= 0 && dteDays <= nearDteMax.value) near += 1
    }
  }
  return { all: rows.length, sweeps, blocks, whales, itm, near, calls, puts, anomalies, unusual, momentum, moonshot }
})

function tapeViewCount(view: TapeView): number {
  const counts = tapeClassCounts.value
  return view === 'all' ? counts.all : counts[view]
}

function tapeViewLabel(view: TapeView): string {
  return {
    near: 'Near-dated',
    all: 'All',
    whales: 'Whales',
    anomalies: 'Flags',
    calls: 'Calls',
    puts: 'Puts',
    sweeps: 'Sweeps',
    blocks: 'Blocks',
    itm: 'ITM',
    unusual: 'Unusual',
    momentum: 'Momentum',
    moonshot: 'Moonshot',
  }[view]
}

function selectTapeView(view: TapeView): void {
  if (view !== 'all' && tapeViewCount(view) === 0) {
    filterRecoveryNotice.value = `${tapeViewLabel(view)} has no matches in the current payload. Showing all qualified prints.`
    tapeView.value = 'all'
    return
  }
  filterRecoveryNotice.value = null
  tapeView.value = view
  if (view === 'near') tapeSort.value = 'near-signed'
}

// A server-side filter refresh can remove every row from the currently active
// local tab. Recover to ALL instead of leaving a blank table that looks like a
// failed request; the notice preserves why the view changed.
watch(
  [() => d.value?.flow_tape, tapeView, nearDteMax],
  () => {
    if (!(d.value?.flow_tape?.length) || tapeView.value === 'all') return
    if (tapeViewCount(tapeView.value) > 0) return
    const emptyView = tapeViewLabel(tapeView.value)
    tapeView.value = 'all'
    filterRecoveryNotice.value = `${emptyView} has no matches after the filter update. Showing all qualified prints.`
  },
)

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
  return { label: 'N/A', cls: 'unsigned', title: 'Unresolved' }
}

function tradeClassLabel(row: OptionsTapeRow): string {
  const raw = (row.trade_class || 'single').toLowerCase()
  if (raw === 'sweep' || row.anomaly_flags.includes('sweep_burst')) {
    // Golden sweep: premium ≥ $500k with sweep classification = institutional conviction
    return row.premium >= 500_000 ? 'GOLDEN SWEEP' : 'SWEEP'
  }
  if (raw === 'block') return 'BLOCK'
  if (raw === 'split') return 'SPLIT'
  if (raw === 'multileg') return 'MULTILEG'
  return 'SINGLE'
}

/** Maps a trade class label to its global token CSS class from tokens.css */
function tradeClassTokenCls(label: string): string {
  if (label === 'GOLDEN SWEEP') return 'flow-badge badge-golden-sweep'
  if (label === 'SWEEP') return 'flow-badge badge-sweep'
  if (label === 'BLOCK') return 'flow-badge badge-block'
  if (label === 'SPLIT') return 'flow-badge badge-split'
  if (label === 'MULTILEG') return 'flow-badge badge-multileg'
  return 'flow-badge badge-standard'
}

/** Returns the whale-indicator tier class for premium size */
function premiumTierCls(premium: number): string {
  if (premium >= 1_000_000) return 'whale-indicator tier-mega-whale'
  if (premium >= 500_000) return 'whale-indicator tier-500k'
  if (premium >= 100_000) return 'whale-indicator tier-100k'
  if (premium >= 25_000) return 'whale-indicator tier-25k'
  return 'whale-indicator tier-std'
}

/** Premium tier label for the indicator */
function premiumTierLabel(premium: number): string {
  if (premium >= 1_000_000) return '$1M+'
  if (premium >= 500_000) return '$500K+'
  if (premium >= 100_000) return '$100K+'
  if (premium >= 25_000) return '$25K+'
  return 'STD'
}

/** Vol/OI ratio tier for the vol-oi-pill */
function volOiRatio(row: OptionsTapeRow): number | null {
  const oi = row.open_interest
  const vol = row.volume ?? row.contracts ?? 0
  if (!oi || oi <= 0 || vol <= 0) return null
  return vol / oi
}

function volOiPillCls(ratio: number | null): string {
  if (ratio == null) return 'vol-oi-pill'
  if (ratio >= 3) return 'vol-oi-pill extreme'
  if (ratio >= 1) return 'vol-oi-pill high'
  return 'vol-oi-pill'
}

function volOiLabel(ratio: number | null): string {
  if (ratio == null) return '0.00x'
  if (ratio >= 10) return '>10x'
  return `${ratio.toFixed(1)}x`
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

const signedFlowAvailable = computed(() => Boolean(d.value?.provider?.signed_flow_available))

function formatLag(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '0s'
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

/** Wall-clock age from an ISO stamp (preferred over baked-in age_seconds). */
function ageFromAsOf(asof: string | null | undefined, fallback: number | null | undefined): number | null {
  if (asof) {
    const ms = Date.parse(asof)
    if (Number.isFinite(ms)) return Math.max(0, (Date.now() - ms) / 1000)
  }
  return fallback ?? null
}

/**
 * Live lag indicator for this underlier's options tape — not generic "connected".
 * Distinguishes real trade tape vs chain-volume proxy vs history.
 * Feed age (any provider print) drives LIVE/STALE; qualified-tape lag is secondary
 * so high min-$ filters do not falsely mark a live name as 19h stale.
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
  const freshness = d.value.freshness
  const feedAge = ageFromAsOf(
    freshness?.feed_asof ?? d.value.observed_at,
    freshness?.feed_age_seconds ?? freshness?.age_seconds ?? null,
  )
  const tapeAge = ageFromAsOf(
    freshness?.tape_asof,
    freshness?.tape_age_seconds ?? null,
  )
  // Prefer feed liveness for the lamp; fall back to qualified tape age.
  const age = feedAge ?? tapeAge
  const basis = d.value.provider?.activity_basis
  const printsIn = d.value.quality?.flow_prints_included ?? 0
  const printsRaw = d.value.quality?.flow_prints_raw ?? 0
  const tapeN = d.value.flow_tape?.length ?? 0
  const lag = formatLag(age)
  const tapeLag = formatLag(tapeAge)
  const rejectedBelow = Number(d.value.quality?.flow_rejected?.below_premium ?? 0)
  const expiryRelaxed = d.value.quality?.flow_rejected?.expiry_filter_relaxed === true
  const requestedExpiry = String(d.value.quality?.flow_rejected?.requested_expiry ?? '')

  if (d.value.mode_resolved === 'history' || d.value.mode_resolved === 'history_fallback') {
    return {
      status: 'history' as const,
      lamp: 'history',
      title: d.value.mode_resolved === 'history_fallback' ? 'HIST FALLBACK' : 'HISTORY',
      sub: `Dated chain · ${historyMeta.value?.selected_asof ?? d.value.asof_utc?.slice(0, 10) ?? 'N/A'}`,
      lag,
      detail: `${d.value.quality?.chain_contracts_included ?? 0} contracts kept`,
    }
  }

  if (basis === 'trade_tape' && (tapeN > 0 || printsRaw > 0)) {
    const live = age != null && age <= 120
    const soft = age != null && age <= 600
    const qualifiedStale = tapeAge != null && tapeAge > 600 && (feedAge == null || feedAge <= 120)
    if (tapeN === 0) {
      return {
        status: live ? 'warm' as const : 'stale' as const,
        lamp: live ? 'stale' : 'stale',
        title: live ? 'FEED LIVE · NO QUALIFIED PRINTS' : 'TAPE EMPTY',
        sub: live
          ? `Provider is live (${lag}) but min $ / filters excluded all ${printsRaw} prints`
          : `No qualifying prints · feed lag ${lag}`,
        lag,
        detail: `0 shown · 0/${printsRaw} prints · try RAW or lower Min $`,
      }
    }
    return {
      status: live ? 'live' as const : soft ? 'warm' as const : 'stale' as const,
      lamp: live ? 'live' : soft ? 'stale' : 'stale',
      title: live && expiryRelaxed
        ? 'LIVE TAPE · ALL EXP'
        : live
        ? (qualifiedStale ? 'LIVE FEED · THIN WHALES' : 'LIVE TAPE')
        : soft ? 'TAPE WARM' : 'TAPE STALE',
      sub: expiryRelaxed
        ? `${shortDate(requestedExpiry)} had no qualified prints · GEX stays selected, tape shows all expiries`
        : live
        ? (qualifiedStale
          ? `Feed live · qualified ≥$${compact(minPremium.value)} prints lag ${tapeLag}${rejectedBelow > 0 ? ` · ${rejectedBelow} below min $` : ''}`
          : `Streaming prints for ${d.value.symbol}`)
        : soft
          ? `Last feed lag ${lag} — still usable`
          : `Last observation lag ${lag} — not fresh`,
      lag: live && qualifiedStale ? tapeLag : lag,
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

/** One honest direction read for the whole workspace. Call/put identity is
 * deliberately excluded. The builder accepts signed flow, a fired squeeze,
 * or fresh underlying momentum — and recomputes on every 60s Options poll. */
const directionRead = computed(() => buildOptionsDirection(s.value, tapeHealth.value.status))

const filterSummary = computed(() =>
  `TAPE ≥$${compact(minPremium.value)} · VOL ≥${minVolume.value} · GEX OI ≥${minOpenInterest.value} · SPREAD ≤${num(maxSpreadPct.value * 100, 0)}% · ${minDte.value}–${maxDte.value}D`,
)

function setPremiumFloor(v: PremiumFloor): void {
  minPremium.value = v
  // Align preset chip if it matches a known preset floor.
  if (v === 100_000) preset.value = 'strict'
  else if (v === 25_000) preset.value = 'balanced'
  else if (v === 0) preset.value = 'raw'
  // The shared filter watcher performs one coalesced refresh. Starting an
  // immediate second request here can supersede the first response and make a
  // populated filter result briefly look empty.
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
          <span class="view-label label">OPTIONS FLOW</span>
          <button type="button" class="book-pin label" :class="{ on: onBook }" @click="toggleBook">
            {{ onBook ? '★ BOOK' : '☆ BOOK' }}
          </button>
        </div>
      </div>

      <div class="quick-tickers" role="group" aria-label="Liquid underlier shortcuts">
        <button
          v-for="t in ['SPY', 'QQQ', 'NVDA', 'TSLA', 'AAPL', 'AMD', 'MSFT', 'META']"
          :key="t"
          type="button"
          class="ticker-chip label"
          :class="{ on: symbol === t }"
          @click="loadSymbol(t)"
        >{{ t }}</button>
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
        <RouterLink class="market-flow-link label" :to="{ name: 'insiders', query: { symbol } }">INSIDERS</RouterLink>
        <RouterLink class="market-flow-link label" :to="{ name: 'calculator' }">CALCULATOR</RouterLink>
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
        <span class="qf-lab label">TAPE MIN $</span>
        <button
          v-for="floor in PREMIUM_FLOORS"
          :key="floor"
          type="button"
          class="qf-chip label"
          :class="{ on: minPremium === floor }"
          @click="setPremiumFloor(floor)"
        >{{ floorLabel(floor) }}</button>
        <span class="qf-sep" aria-hidden="true" />
        <span class="qf-lab label">FILTER PRESET</span>
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

    <section v-if="filterRecoveryNotice" class="filter-recovery rise" role="status">
      <span class="label">FILTER RECOVERED</span>
      <p>{{ filterRecoveryNotice }}</p>
      <button type="button" class="label" @click="filterRecoveryNotice = null">DISMISS</button>
    </section>

    <section v-if="filtersOpen" class="filter-deck rise">
      <p class="filter-deck-intro">
        These controls change the displayed tape and GEX map. A preset resets the bundle; the fields below are manual overrides.
      </p>
      <div class="filters">
        <label><span class="label">Tape from</span><input v-model="dateFrom" type="date" /></label>
        <label><span class="label">{{ mode === 'history' ? 'Historical chain day' : 'Tape to' }}</span><input v-model="dateTo" type="date" /></label>
        <label><span class="label">Tape minimum $</span><input v-model.number="minPremium" type="number" min="0" step="5000" /></label>
        <label><span class="label">Minimum contracts</span><input v-model.number="minVolume" type="number" min="0" step="1" /></label>
        <label><span class="label">GEX minimum OI</span><input v-model.number="minOpenInterest" type="number" min="0" step="25" /></label>
        <label><span class="label">Maximum spread %</span><input :value="maxSpreadPct * 100" type="number" min="0.1" max="200" step="1" @input="maxSpreadPct = Number(($event.target as HTMLInputElement).value) / 100" /></label>
        <label><span class="label">Minimum DTE</span><input v-model.number="minDte" type="number" min="0" max="730" /></label>
        <label><span class="label">Maximum DTE</span><input v-model.number="maxDte" type="number" min="0" max="730" /></label>
        <label><span class="label">Tape rows</span>
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
      <button class="label" type="button" @click="void resource.refresh({ clear: !d })">RETRY</button>
    </div>

    <div v-if="loadingSymbol && !d" class="fault-strip loading-strip">
      <span class="label">CALCULATING</span>
      Loading GEX · squeeze · tape for <strong class="fig">{{ symbol }}</strong>…
    </div>
    <div v-else-if="loadingSymbol && d" class="fault-strip loading-strip soft">
      <span class="label">REFRESHING {{ symbol }}</span>
      Recomputing squeeze and structure…
    </div>
    <div v-else-if="chainMissing && !resource.error.value" class="fault-strip">
      <span class="label">NO CHAIN</span>
      No options payload for <strong class="fig">{{ symbol }}</strong> yet.
      <button class="label" type="button" @click="void resource.refresh({ clear: true })">LOAD CHAIN</button>
    </div>

    <OptionsDirectionBrief
      :symbol="symbol"
      :read="directionRead"
    />

    <!-- Dense structure KPI rail -->
    <section class="kpi-rail rise">
      <div class="kpi spot">
        <span class="label">SPOT</span>
        <strong class="fig">{{ optUsd(s?.spot) }}</strong>
        <em class="label">UNDERLYING</em>
      </div>
      <div class="kpi" :class="s?.regime">
        <span class="label">NET GEX</span>
        <strong class="fig" :class="tone(s?.total_gex_m)">{{ s?.total_gex_m == null ? '$0.0M' : `${s.total_gex_m >= 0 ? '+' : ''}$${num(s.total_gex_m, 1)}M` }}</strong>
        <em class="label">{{ (s?.regime ?? 'UNKNOWN').toUpperCase() }} GAMMA</em>
      </div>
      <div class="kpi call">
        <span class="label">CALL WALL</span>
        <strong class="fig call">{{ optUsd(s?.call_wall) }}</strong>
        <em class="label call-tag">{{ wallPct('call') == null ? '+0.0%' : (wallPct('call')! >= 0 ? '+' : '') + pctFrac(wallPct('call'), 1) }}</em>
      </div>
      <div class="kpi put">
        <span class="label">PUT WALL</span>
        <strong class="fig put">{{ optUsd(s?.put_wall) }}</strong>
        <em class="label put-tag">{{ wallPct('put') == null ? '-0.0%' : (wallPct('put')! >= 0 ? '+' : '') + pctFrac(wallPct('put'), 1) }}</em>
      </div>
      <div class="kpi">
        <span class="label">FLIP</span>
        <strong class="fig accent">{{ optUsd(s?.gamma_flip) }}</strong>
        <em class="label">ZERO-GAMMA LEVEL</em>
      </div>
      <div class="kpi">
        <span class="label">IV</span>
        <strong class="fig">{{ p?.atm_iv != null ? pctFrac(p.atm_iv, 1) : '0.0%' }}</strong>
        <em class="label">ATM · {{ p?.horizon_days ?? 0 }}D</em>
      </div>
      <div class="kpi">
        <span class="label">C/P PREM</span>
        <strong class="fig">
          <span class="call">{{ flowPremSplit.call != null ? `$${compact(flowPremSplit.call)}` : '$0' }}</span>
          <span class="dim">/</span>
          <span class="put">{{ flowPremSplit.put != null ? `$${compact(flowPremSplit.put)}` : '$0' }}</span>
        </strong>
        <em class="label">RATIO {{ flowPremSplit.ratio == null ? '1.00x' : num(flowPremSplit.ratio, 2) }}</em>
      </div>
      <div class="kpi" :class="leanRead.lean">
        <span class="label">LEAN</span>
        <strong class="fig">{{ leanRead.label }}</strong>
        <em class="label">ACTIVITY · NOT AUTH</em>
      </div>
      <div class="kpi squeeze-kpi">
        <span class="label">SQUEEZE</span>
        <div class="kpi-squeeze-body">
          <strong class="fig">
            {{ squeeze?.score ?? squeeze?.bullish_setup?.score ?? squeeze?.bearish_setup?.score ?? 0 }}
            <small v-if="squeeze">/100</small>
          </strong>
          <span
            v-if="squeeze?.primary || squeeze?.bullish_setup?.likelihood || squeeze?.bearish_setup?.likelihood"
            class="squeeze-tag label"
          >{{ (squeeze?.primary || squeeze?.bullish_setup?.likelihood || squeeze?.bearish_setup?.likelihood || 'UNLIKELY').toUpperCase().replace(/_/g, '-') }}</span>
        </div>
      </div>
    </section>

    <!-- Dense workbench: Flow context bar + Squeeze + Dominant GEX -->
    <div class="workbench">
      <Panel
        label="FLOW CONVICTION & AGGRESSOR SPREAD"
        flush
        class="cell flow-context-cell flow-context-bar"
      >
        <OptionsFlowContext
          :summary="s"
          :tape="d?.flow_tape ?? []"
          :anomaly-count="d?.anomalies.count ?? 0"
          :signed-flow-available="signedFlowAvailable"
          :tape-status="tapeHealth.status"
          :tape-title="tapeHealth.title"
          :direction="directionRead"
        />
      </Panel>

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
          <div v-else-if="chainMissing" class="unmeasured">
            <p class="unmeasured-head label">CHAIN NOT LOADED</p>
            <p class="unmeasured-body">
              Squeeze needs a matching options payload for {{ symbol }}. Use LOAD CHAIN if this panel stays empty.
            </p>
          </div>
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
              <span class="gex-meta-badge">EXPOSURE {{ !gexMeasurable || s?.total_gex_m == null ? '$0.0M' : `$${num(s.total_gex_m, 1)}M` }}</span>
              <span class="gex-meta-badge">SPOT {{ optUsd(s?.spot) }}</span>
              <span v-if="s?.gamma_flip != null" class="gex-meta-badge flip">FLIP {{ optUsd(s.gamma_flip) }}</span>
              <span v-if="s?.zero_gamma != null" class="gex-meta-badge flip">ZERO-GAMMA {{ optUsd(s.zero_gamma) }}</span>
            </div>
          </template>
          <LoadingState v-if="loadingSymbol && !d" label="Loading GEX" compact />
          <div v-else-if="chainMissing" class="unmeasured">
            <p class="unmeasured-head label">CHAIN NOT LOADED</p>
            <p class="unmeasured-body">
              Waiting for a matching options payload for {{ symbol }}. If this sticks,
              hit LOAD CHAIN above or retry after the feed recovers.
            </p>
          </div>
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
          <div v-else-if="!(d?.gex_by_strike?.length)" class="unmeasured">
            <p class="unmeasured-head label">NO STRIKES IN WINDOW</p>
            <p class="unmeasured-body">
              {{ chainRawCount }} contracts were fetched but none cleared the current
              DTE / OI / spread filters. Widen TUNE (lower Min OI, raise Max DTE) or
              switch expiry to ALL.
            </p>
          </div>
          <template v-else>
            <GammaExposureMap
              :rows="d?.gex_by_strike ?? []"
              :spot="s?.spot ?? 0"
              :call-wall="s?.call_wall ?? null"
              :put-wall="s?.put_wall ?? null"
              :gamma-flip="s?.gamma_flip ?? s?.zero_gamma ?? null"
              :focus-strike="focusStrike"
              @update:focus-strike="focusStrike = $event"
            />
            <div v-if="d?.oi_by_strike?.length" class="oi-by-strike">
              <span class="label">OI by strike</span>
              <span
                v-for="row in d.oi_by_strike.slice(0, 12)"
                :key="row.strike"
                class="oi-strike-chip label"
              >{{ usd(row.strike) }} · <b class="call">C {{ compact(row.call_oi) }}</b> / <b class="put">P {{ compact(row.put_oi) }}</b></span>
            </div>
          </template>
        </Panel>
      </div>
    </div>

    <p class="calc-handoff">
      <span class="label">Spot / strike / DTE / vol calculator lives on its own workspace.</span>
      <RouterLink
        class="market-flow-link label"
        :to="{
          name: 'calculator',
          query: {
            symbol,
            strategy: 'long_call',
            ...(s?.spot != null ? { spot: String(s.spot) } : {}),
            ...(s?.call_wall != null ? { strike: String(s.call_wall) } : {}),
            ...(p?.atm_iv != null ? { vol: String(p.atm_iv) } : {}),
            ...(p?.horizon_days != null ? { dte: String(p.horizon_days) } : {}),
          },
        }"
      >OPEN CALCULATOR</RouterLink>
    </p>

    <Panel
      label="QUALIFIED FLOW TAPE"
      index="03"
      :meta="`${visibleTape.length}/${d?.flow_tape.length ?? 0} PRINTS · ${tapeClassCounts.whales} WHALES · ${tapeClassCounts.sweeps} SWEEPS · ${tapeClassCounts.blocks} BLOCKS`"
      :live="tapeHealth.status === 'live'"
      flush
      class="tape-panel tape-panel-full"
    >
      :meta="`${visibleTape.length}/${d?.flow_tape.length ?? 0} PRINTS · ${tapeClassCounts.whales} WHALES · ${tapeClassCounts.sweeps} SWEEPS · ${tapeClassCounts.blocks} BLOCKS`"
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
            <button type="button" class="label near-tab" :class="{ on: tapeView === 'near' }" :disabled="tapeClassCounts.near === 0" @click="selectTapeView('near')" title="Near-dated flow (this month). Signed prints bubble to top.">
              NEAR<span class="near-count">&nbsp;{{ tapeClassCounts.near }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'all' }" @click="selectTapeView('all')">ALL&nbsp;{{ tapeClassCounts.all }}</button>
            <button type="button" class="label whale-tab" :class="{ on: tapeView === 'whales' }" :disabled="tapeClassCounts.whales === 0" @click="selectTapeView('whales')">
              WHALES<span class="tab-count">{{ tapeClassCounts.whales }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'itm' }" :disabled="tapeClassCounts.itm === 0" @click="selectTapeView('itm')">
              ITM<span class="tab-count">{{ tapeClassCounts.itm }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'unusual' }" :disabled="tapeClassCounts.unusual === 0" @click="selectTapeView('unusual')">
              UNUSUAL<span class="tab-count">{{ tapeClassCounts.unusual }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'sweeps' }" :disabled="tapeClassCounts.sweeps === 0" @click="selectTapeView('sweeps')">
              SWEEPS<span class="tab-count">{{ tapeClassCounts.sweeps }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'momentum' }" :disabled="tapeClassCounts.momentum === 0" @click="selectTapeView('momentum')">
              MOMENTUM<span class="tab-count">{{ tapeClassCounts.momentum }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'moonshot' }" :disabled="tapeClassCounts.moonshot === 0" @click="selectTapeView('moonshot')">
              MOONSHOT<span class="tab-count">{{ tapeClassCounts.moonshot }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'blocks' }" :disabled="tapeClassCounts.blocks === 0" @click="selectTapeView('blocks')">
              BLOCKS<span class="tab-count">{{ tapeClassCounts.blocks }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'anomalies' }" :disabled="tapeClassCounts.anomalies === 0" @click="selectTapeView('anomalies')">
              FLAGS<span class="tab-count">{{ tapeClassCounts.anomalies }}</span>
            </button>
            <button type="button" class="label" :class="{ on: tapeView === 'calls' }" :disabled="tapeClassCounts.calls === 0" @click="selectTapeView('calls')">CALLS&nbsp;{{ tapeClassCounts.calls }}</button>
            <button type="button" class="label" :class="{ on: tapeView === 'puts' }" :disabled="tapeClassCounts.puts === 0" @click="selectTapeView('puts')">PUTS&nbsp;{{ tapeClassCounts.puts }}</button>
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
              isMegaWhale: row.premium >= 500_000,
              isGoldenSweep: tradeClassLabel(row) === 'GOLDEN SWEEP',
              [tapeLean(row).cls]: true,
            }"
          >
            <div class="card-head-row">
              <span class="lean-pill label" :class="tapeLean(row).cls">{{ tapeLean(row).label }}</span>
              <span class="ts-time fig">{{ row.timestamp.slice(11, 19) }}</span>
              <span
                :class="premiumTierCls(row.premium)"
              >{{ premiumTierLabel(row.premium) }}</span>
              <span :class="tradeClassTokenCls(tradeClassLabel(row))" style="margin-left:auto;">{{ tradeClassLabel(row) }}</span>
            </div>

            <div class="card-body-row">
              <div class="strike-box">
                <span class="strike-label label">STRIKE</span>
                <strong class="strike-val fig">{{ optUsd(row.strike) }}</strong>
                <span v-if="moneynessInfo(row)" class="money-tag label" :class="moneynessInfo(row)!.cls">{{ moneynessInfo(row)!.text }}</span>
              </div>
              <div class="prem-box" :class="row.right">
                <span class="prem-label label">PREMIUM</span>
                <strong class="prem-val fig">${{ compact(row.premium || 0) }}</strong>
                <span class="fill-sub label">{{ num(contractsOf(row), 0) }} contracts @ {{ pricePaid(row) == null ? '$0.00' : `$${num(pricePaid(row), 2)}` }}</span>
              </div>
            </div>

            <div class="card-foot-row">
              <span class="class-chip label" :class="tradeClassLabel(row).toLowerCase()">{{ tradeClassLabel(row) }}</span>
              <span class="exp-tag label">{{ row.expiry ? shortDate(row.expiry) : 'N/A' }}</span>
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
              <th class="label flag-col">Tier</th>
              <th class="label">Time</th>
              <th class="label tape-col-group">Lean</th>
              <th class="label">Class</th>
              <th class="label tape-col-group">Expiry</th>
              <th class="label num-col">Strike</th>
              <th class="label num-col tape-col-group stock-head">Spot</th>
              <th class="label num-col tape-col-group">Fill</th>
              <th class="label num-col">Contracts</th>
              <th class="label num-col vol-oi-head">Vol/OI</th>
              <th class="label num-col tape-premium-head">Premium</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in visibleTape"
              :key="`${row.timestamp}-${row.right}-${row.strike}-${row.premium}`"
              :class="{
                anomalous: row.anomaly_flags.length,
                isWhale: row.premium >= 100_000,
                isMegaWhale: row.premium >= 500_000,
                isGoldenSweep: tradeClassLabel(row) === 'GOLDEN SWEEP',
                [tapeLean(row).cls]: true,
              }"
            >
              <td class="flag-col">
                <span
                  :class="premiumTierCls(row.premium)"
                  :title="`Premium tier: ${premiumTierLabel(row.premium)}`"
                >{{ premiumTierLabel(row.premium) }}</span>
              </td>
              <td class="fig dim ts-cell">{{ row.timestamp.slice(11, 19) }}</td>
              <td class="tape-col-group">
                <span class="bias-chip label" :class="tapeLean(row).cls" :title="tapeLean(row).title">
                  {{ tapeLean(row).label }}
                </span>
              </td>
              <td>
                <span :class="tradeClassTokenCls(tradeClassLabel(row))">
                  {{ tradeClassLabel(row) }}
                </span>
              </td>
              <td class="fig dim tape-col-group expiry-cell">{{ row.expiry ? shortDate(row.expiry) : 'N/A' }}</td>
              <td class="fig num-col strike-cell">{{ optUsd(row.strike) }}</td>
              <td class="fig num-col tape-col-group stock-cell">
                <div class="stock-lockup">
                  <span class="stock-val">{{ (row.underlying_price ?? s?.spot) == null ? '$0.00' : optUsd(row.underlying_price ?? s?.spot) }}</span>
                  <span v-if="moneynessInfo(row)" class="moneyness-tag label" :class="moneynessInfo(row)!.cls">{{ moneynessInfo(row)!.text }}</span>
                </div>
              </td>
              <td class="fig num-col tape-col-group" :title="row.premium_estimated ? 'Back-solved from notional' : 'Per-contract fill'">
                {{ pricePaid(row) == null ? '$0.00' : `$${num(pricePaid(row)!, 2)}` }}
              </td>
              <td class="fig num-col">{{ num(contractsOf(row), 0) }}</td>
              <td class="num-col">
                <span :class="volOiPillCls(volOiRatio(row))" :title="row.open_interest != null ? `OI: ${num(row.open_interest, 0)}` : 'OI unavailable'">
                  {{ volOiLabel(volOiRatio(row)) }}
                </span>
              </td>
              <td class="fig num-col premium-cell" :class="[row.right, { 'whale-prem': row.premium >= 100_000 }]">
                ${{ compact(row.premium || 0) }}
                <small v-if="row.premium_estimated" class="est">≈</small>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else-if="d?.flow_tape.length" class="no-tape compact-empty">
        <strong>NO PRINTS MATCH THIS TABLE VIEW</strong>
        <p>The source tape is loaded. Reset the local view to show the qualified prints.</p>
        <button type="button" class="label raw-btn" @click="selectTapeView('all')">SHOW ALL {{ d.flow_tape.length }}</button>
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

    <Panel label="On-demand historical tape" index="05b" class="rise">
      <div class="history-tape-bar">
        <label><span class="label">From</span><input v-model="historyFrom" type="date"></label>
        <label><span class="label">To</span><input v-model="historyTo" type="date"></label>
        <button type="button" class="label raw-btn" :disabled="historyLoading" @click="void loadHistoryTape()">
          {{ historyLoading ? 'LOADING…' : `LOAD ${symbol} TAPE` }}
        </button>
        <span class="label">{{ historyTapeMeta }}</span>
      </div>
      <p v-if="historyError" class="note pad">{{ historyError }}</p>
      <div v-else-if="historyTape.length" class="table-scroll">
        <table class="tape-table">
          <thead>
            <tr>
              <th class="label">Time</th>
              <th class="label">Right</th>
              <th class="label">Tags</th>
              <th class="label num">Premium</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in historyTape.slice(0, 50)" :key="`${row.timestamp}-${row.strike}-${row.premium}`">
              <td class="fig">{{ shortDate(row.timestamp) }}</td>
              <td class="fig">{{ row.right }} {{ row.strike != null ? optUsd(row.strike) : 'N/A' }}</td>
              <td class="label">{{ (row.presets ?? []).join(' · ') || row.trade_class || 'STANDARD' }}</td>
              <td class="fig num">{{ optUsd(row.premium, 0) }}</td>
            </tr>
          </tbody>
        </table>
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
                  {{ row.ret_1d == null ? '+0.0%' : signedPct((row.ret_1d ?? 0) * 100, 1) }}
                </td>
                <td>
                  <span
                    class="side-pill"
                    :class="row.activity_lean === 'bullish' || row.context_side === 'long' ? 'pos'
                      : row.activity_lean === 'bearish' || row.context_side === 'short' ? 'neg'
                        : row.activity_lean === 'mixed' ? 'warn' : 'neutral'"
                    :title="row.activity_lean_source ? `Activity lean · ${row.activity_lean_source}` : 'Activity lean'"
                  >
                    {{ (row.activity_lean_label || row.activity_lean || row.context_side || 'NEUTRAL').toUpperCase() }}
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
          Click a row to load that underlier. Lean is bullish/bearish activity detection (premium + price); signed buy/sell is separate when the feed provides it.
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
                  {{ row.ret_1d == null ? '+0.0%' : signedPct((row.ret_1d ?? 0) * 100, 1) }}
                </td>
                <td class="fig num">{{ pctFrac(row.spread_pct ?? 0, 1) }}</td>
                <td class="fig num">{{ num(row.open_interest ?? 0, 0) }}</td>
                <td class="fig num">{{ row.selected_dte == null ? '0D' : `${row.selected_dte}D` }}</td>
                <td class="fig num" :class="imbalanceTone(row.call_put_imbalance)">
                  {{ row.call_put_imbalance == null ? '+0%' : signedPct((row.call_put_imbalance ?? 0) * 100, 0) }}
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
  gap: var(--s4);
  min-height: calc(100% + (var(--s5) * 2));
  margin: calc(var(--s5) * -1);
  padding: var(--s5) var(--s5) var(--s7);
  min-width: 0;
  background: var(--void);
}

.options-view :deep(.panel) {
  border-radius: 0;
  padding: var(--s1);
}
.options-view :deep(.panel > .head) {
  min-height: 38px;
  padding: var(--s1) var(--s2);
  border-bottom: var(--hair) solid var(--rule);
}
.options-view :deep(.panel > .head .idx) { color: var(--phosphor); }

/* ---- view tabs ----------------------------------------------------------- */
.market-flow-link {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: var(--s2) var(--s3);
  color: var(--call-hi);
  border: var(--hair) solid color-mix(in srgb, var(--call) 42%, var(--rule));
  background: var(--call-wash);
  text-decoration: none;
}
.market-flow-link:hover { color: var(--phosphor); background: var(--phosphor-wash); text-decoration: none; }

.command {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s2) var(--s3);
  min-height: 56px;
  padding: var(--s2) var(--s4);
  border: var(--hair) solid var(--rule);
  border-left: 2px solid var(--phosphor-dim);
  background-color: var(--panel);
}
.identity {
  display: flex;
  align-items: center;
  min-width: 0;
}
.quick-tickers {
  display: flex;
  align-items: center;
  gap: 3px;
  flex-wrap: wrap;
}
.ticker-chip {
  padding: 3px 7px;
  min-height: 26px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  color: var(--ink-dim);
  font: 700 9.5px var(--font-data);
  letter-spacing: 0.04em;
  cursor: pointer;
  border-radius: var(--r-xs, 2px);
  transition: color 0.12s ease, background 0.12s ease, border-color 0.12s ease;
}
.ticker-chip:hover {
  color: var(--ink);
  background: var(--panel-hi);
  border-color: var(--rule);
}
.ticker-chip.on {
  color: var(--void);
  background: var(--phosphor);
  border-color: var(--phosphor);
}
.command-right {
  display: flex;
  align-items: center;
  gap: var(--s2);
  margin-left: auto;
  flex-wrap: wrap;
}
.symbol-lockup {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px var(--s3);
  line-height: 1;
}
.book-pin {
  justify-self: start;
  min-height: 22px;
  padding: 0 7px;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule-hi);
  background: transparent;
  cursor: pointer;
}
.book-pin.on { color: var(--phosphor); border-color: var(--phosphor-dim); }
.history-tape-bar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s3);
  align-items: end;
  padding: var(--s3);
}
.active-symbol { font-size: var(--t-fig); font-weight: 600; letter-spacing: var(--track-tight); color: var(--ink); }
.slash { font: 300 1rem var(--font-display); color: var(--rule-hi); }
.view-name { font: 700 0.85rem var(--font-display); letter-spacing: .1em; color: var(--ink-dim); }
.observed { color: var(--ink-ghost); font-size: var(--t-micro); white-space: nowrap; }
.symbol-form { position: relative; flex: 0 1 120px; min-width: 110px; }
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
.symbol-entry {
  display: flex;
  height: 34px;
  border: var(--hair) solid var(--rule-hi);
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
  min-width: 52px;
  padding: 0 8px;
  color: var(--void);
  border-left: var(--hair) solid var(--phosphor);
  background: var(--phosphor);
  font-size: var(--t-micro);
  font-weight: 800;
}
.load-btn:hover:not(:disabled) { background: var(--phosphor-dim); }
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
.search-hits .tier { color: var(--ink-ghost); font-size: var(--t-micro); }
.search-hits .bars { color: var(--ink-faint); font-size: var(--t-micro); }

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
  padding: var(--s2) var(--s3);
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
.unusual-table td { padding: var(--s2) var(--s4); border-bottom: var(--hair) solid var(--rule-faint); text-align: left; }
.unusual-table th.num,
.unusual-table td.num { text-align: right; }
.unusual-table tbody tr { cursor: pointer; }
.unusual-table tbody tr:hover { background: var(--panel-hi); }
.unusual-table tbody tr.active { background: var(--phosphor-wash); box-shadow: inset 2px 0 0 var(--phosphor); }
.rank-idx { color: var(--ink-ghost); margin-right: 8px; font-size: var(--t-micro); }
.sym { letter-spacing: 0.04em; }
.flag-stack { display: flex; flex-wrap: wrap; gap: 4px; }
.flag-stack span {
  padding: 2px 6px;
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
}
.flag-stack span.live { color: var(--phosphor); border-color: color-mix(in srgb, var(--phosphor) 45%, var(--rule)); }
.activity-score { display: grid; grid-template-columns: 4ch 56px; justify-content: end; align-items: center; gap: 4px; }
.activity-score > i { display: block; height: 3px; overflow: hidden; background: var(--rule); }
.activity-score > i b { display: block; height: 100%; background: var(--phosphor); }
.live-value { color: var(--phosphor); }
.flow-count { display: block; color: var(--ink-ghost); font-size: var(--t-micro); }
.sep { color: var(--ink-ghost); margin: 0 2px; }
.side-pill {
  display: inline-block;
  padding: 2px 7px;
  border: var(--hair) solid var(--rule);
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
}
.side-pill.pos { color: var(--long); border-color: color-mix(in srgb, var(--long) 40%, var(--rule)); }
.side-pill.neg { color: var(--short); border-color: color-mix(in srgb, var(--short) 40%, var(--rule)); }
.side-pill.warn { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, var(--rule)); }
.side-pill.neutral { color: var(--ink-ghost); }

/* ---- Live Opportunities: composite board+flow ranking ------------------ */
.opportunities-table { max-height: 260px; overflow: auto; }
.opportunities-table table { width: 100%; border-collapse: collapse; }
.opportunities-table th,
.opportunities-table td { padding: var(--s2) var(--s4); border-bottom: var(--hair) solid var(--rule-faint); text-align: left; }
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
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
}
.gate-chip.pass { color: var(--long); border-color: color-mix(in srgb, var(--long) 45%, var(--rule)); background: var(--long-wash); }
.gate-chip.fail { color: var(--short); border-color: color-mix(in srgb, var(--short) 45%, var(--rule)); background: var(--short-wash); }
.basis {
  display: inline-block;
  padding: 2px 7px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
  font-size: var(--t-micro);
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
.note.tiny { font-size: var(--t-micro); color: var(--ink-faint); }
.note.pad { padding: var(--s3) var(--s4); }
.cov { color: var(--ink-ghost); }
.segment { display: flex; border: 1px solid var(--rule-hi); height: 34px; overflow: hidden; background: var(--void-lift); }
.seg { padding: 0 var(--s2); color: var(--ink-faint); border-right: var(--hair) solid var(--rule); font-size: var(--t-micro); }
.seg:last-child { border-right: 0; }
.seg:hover { color: var(--ink); background: var(--panel-hi); }
.seg.on { color: var(--void); background: var(--phosphor); font-weight: 800; }
.expiry-select {
  height: 34px;
  min-width: 120px;
  max-width: 160px;
  padding: 0 22px 0 8px;
  color: var(--ink);
  border: 1px solid var(--rule-hi);
  background: var(--panel-hi);
  font-size: var(--t-micro);
}
.expiry-select:hover { border-color: var(--rule); }
.seg:focus-visible,
.expiry-select:focus-visible,
.symbol-entry:focus-within {
  outline: var(--hair) solid var(--phosphor);
  outline-offset: 2px;
}
/* ---- live lag badge + quick filters (always visible) ------------------- */
.live-filter-bar {
  display: flex;
  align-items: center;
  gap: var(--s2) var(--s3);
  flex-wrap: wrap;
  min-height: 46px;
  padding: var(--s2) var(--s3);
  border: 1px solid var(--rule-hi);
  background: var(--panel);
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
.filter-recovery {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--warn);
  border-left-width: 3px;
  background: var(--warn-wash);
}
.filter-recovery > span { flex: 0 0 auto; color: var(--warn); }
.filter-recovery p { flex: 1 1 auto; margin: 0; color: var(--ink-dim); font-size: var(--t-tiny); }
.filter-recovery button { padding: 3px 7px; color: var(--warn); border: var(--hair) solid var(--warn); }
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
  font-size: var(--t-micro);
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
.live-lag .label { color: var(--ink-faint); font-size: var(--t-micro); }
.live-lag .fig { font-size: var(--t-tiny); color: var(--ink); font-weight: 700; }
.live-meta {
  color: var(--ink-ghost);
  font-size: var(--t-micro);
  flex: 1 1 120px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.quick-filters {
  display: flex;
  align-items: center;
  gap: 3px;
  flex: 0 0 auto;
  flex-wrap: nowrap;
  margin-left: auto;
}
.qf-lab {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  margin-right: 2px;
  letter-spacing: 0.06em;
}
.qf-chip {
  min-height: 28px;
  padding: 0 var(--s2);
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
  background: var(--void-lift);
  font-size: var(--t-micro);
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
  padding: var(--s3);
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}
.filter-deck-intro {
  max-width: 88ch;
  margin: 0;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.45;
}
.filter-summary { color: var(--ink-dim); font-size: var(--t-micro); }
.filter-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.raw-btn.inline {
  margin-top: 0;
  padding: var(--s1) var(--s2);
  font-size: var(--t-micro);
}
.tune {
  color: var(--phosphor);
  padding: 0 var(--s3);
  height: 34px;
  border: 1px solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  font-size: var(--t-micro);
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
  font-size: var(--t-tiny);
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
  background: var(--panel);
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
/* ---- compact KPI rail ------------------------------------------------- */
.kpi-rail {
  display: grid;
  grid-template-columns: repeat(9, minmax(0, 1fr));
  gap: 1px;
  padding: 1px;
  background: var(--rule);
  border: 1px solid var(--rule-hi);
  border-radius: var(--r-md);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.45);
  overflow: hidden;
}
@media (max-width: 1380px) {
  .kpi-rail {
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }
}
@media (max-width: 860px) {
  .kpi-rail {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 580px) {
  .kpi-rail {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.kpi .dim { color: var(--ink-ghost); margin: 0 2px; }
.kpi {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  min-width: 0;
  min-height: 76px;
  padding: 8px 12px;
  border: 0;
  background: var(--panel);
  overflow: hidden;
}
.kpi .label {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.07em;
  line-height: 1.2;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.kpi strong {
  font-size: 1.0rem;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--ink);
  line-height: 1.15;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-variant-numeric: tabular-nums;
}
.kpi em {
  font-style: normal;
  color: var(--ink-faint);
  font-size: var(--t-micro);
  line-height: 1.15;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* SPOT is the anchor — larger and slightly bolder */
.kpi.spot { box-shadow: inset 3px 0 var(--phosphor); background: var(--phosphor-wash); }
.kpi.spot strong { font-size: 1.2rem; color: var(--ink); font-weight: 700; letter-spacing: -0.03em; }
.kpi.positive { border-color: color-mix(in srgb, var(--long) 32%, var(--rule)); }
.kpi.negative { border-color: color-mix(in srgb, var(--short) 32%, var(--rule)); }
.kpi.bullish { box-shadow: inset 3px 0 var(--long); }
.kpi.bearish { box-shadow: inset 3px 0 var(--short); }
.kpi.call strong, .kpi .call { color: var(--call-hi, var(--call)); }
.kpi.put strong, .kpi .put { color: var(--put-hi, var(--put)); }
.kpi .accent { color: var(--phosphor); }
.call-tag { color: var(--call-hi, var(--call)); font-weight: 600; margin-left: 2px; }
.put-tag { color: var(--put-hi, var(--put)); font-weight: 600; margin-left: 2px; }
.kpi-squeeze-body {
  display: flex;
  align-items: baseline;
  gap: 4px;
  overflow: hidden;
}
.squeeze-tag {
  padding: 1px 4px;
  border: var(--hair) solid color-mix(in srgb, var(--warn) 55%, var(--rule));
  background: var(--warn-wash);
  color: var(--warn);
  font-family: var(--font-data);
  font-size: 9px;
  font-weight: 600;
  border-radius: var(--r-xs);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 80px;
}

/* ---- workbench: flow bar, then squeeze + dominant GEX ------------------- */
.calc-handoff {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  background: var(--panel);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
}
.workbench {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.workbench-top {
  display: grid;
  grid-template-columns: minmax(240px, 280px) minmax(0, 1fr);
  grid-template-rows: minmax(560px, 62vh);
  gap: 8px;
  min-width: 0;
  align-items: stretch;
}
@media (max-width: 1180px) {
  .workbench-top {
    grid-template-columns: 1fr;
    grid-template-rows: auto minmax(520px, 58vh);
  }
}

.workbench .cell {
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.workbench-top .cell { height: 100%; }
.workbench .gex-full { width: 100%; min-height: 560px; }
.workbench .gex-full :deep(.body) { overflow: hidden; }
.workbench .flow-context-cell {
  flex: 0 0 auto;
  height: auto;
}
.workbench .flow-context-cell :deep(.body) { overflow: hidden; }
.workbench .flow-context-bar :deep(.panel) { height: auto; }
.workbench-top :deep(.panel) {
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
.workbench .flow-context-bar :deep(.body) {
  overflow: hidden;
  flex: 0 0 auto;
}
.workbench :deep(.head) {
  padding: var(--s2) var(--s3);
  min-height: 32px;
}
.gex-meta-badge.flip { color: var(--warn); }
.oi-by-strike {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
  padding: var(--s3);
  border-top: var(--hair) solid var(--rule);
}
.oi-by-strike > .label:first-child { color: var(--phosphor); }
.oi-by-strike .oi-strike-chip {
  padding: 1px 6px;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
}
.oi-by-strike .call { color: var(--call-hi); font-weight: 700; }
.oi-by-strike .put { color: var(--put-hi); font-weight: 700; }

.view-label {
  font-size: var(--t-micro);
  color: var(--phosphor-dim);
  font-weight: 700;
  letter-spacing: 0.12em;
  margin-left: 0;
  white-space: nowrap;
}

.command-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 6px;
  justify-self: end;
}
.scope-chip {
  padding: var(--s2) var(--s3);
  color: var(--phosphor);
  border: 1px solid color-mix(in srgb, var(--phosphor) 38%, var(--rule));
  background: var(--phosphor-wash);
}

.long-it-btn {
  padding: 2px 8px;
  border: var(--hair) solid color-mix(in srgb, var(--call) 50%, var(--rule));
  background: color-mix(in srgb, var(--call) 12%, transparent);
  color: var(--call);
  font-size: var(--t-micro);
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 4px;
}
.long-it-btn .info-icon {
  font-size: var(--t-micro);
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

.gex-meta-badge {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  font-family: var(--font-data);
  margin-left: 6px;
}

.tape-panel-full { min-height: 280px; width: 100%; }
.prob-calc-panel {
  min-height: 250px;
  margin-top: 0;
}
.prob-calc-panel :deep(.body) {
  padding: 0;
}
.prob-calc-panel :deep(.head) {
  padding: var(--s2) var(--s3);
  min-height: 32px;
}
.table-scroll-tall { max-height: min(52vh, 520px) !important; }
.tape-toolbar {
  display: flex;
  flex-direction: column;
  min-height: 36px;
  border-block: var(--hair) solid var(--rule);
  background: var(--void-lift);
}
/* Main row: tabs flush left, right controls flush right */
.tape-toolbar-main {
  display: flex;
  align-items: stretch;
  min-height: 36px;
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
.tape-tabs button:disabled { color: var(--ink-ghost); opacity: 0.45; cursor: not-allowed; background: transparent; }
.tape-tabs button:focus-visible {
  outline: var(--hair) solid var(--phosphor);
  outline-offset: -2px;
}
/* Tab count badge */
.tab-count {
  display: inline-block;
  margin-left: 4px;
  padding: 0 4px;
  background: var(--panel-raise);
  color: var(--ink-ghost);
  font-size: var(--t-micro);
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
  min-height: 26px;
  padding: 0 6px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-faint);
  background: transparent;
  font-size: var(--t-micro);
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
.sort-control select { min-height: 26px; padding: 0 18px 0 6px; color: var(--ink); border: var(--hair) solid var(--rule-hi); background: var(--panel); font-size: var(--t-micro); }
.sort-control select:hover { border-color: var(--rule); }
.anomaly-method { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-dim); font: var(--t-micro) var(--font-display); letter-spacing: .06em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px; }
.anomaly-method i { width: 7px; height: 7px; border-radius: 50%; background: var(--ink-ghost); flex: 0 0 auto; }
.anomaly-method i.live { background: var(--phosphor); }
.anomaly-method i.stale { background: var(--warn); }
.anomaly-method i.history { background: var(--ink-dim); }
.table-scroll { overflow: auto; max-height: 420px; }
table { width: 100%; border-collapse: collapse; font-size: var(--t-tiny); }
th, td { padding: var(--s2) var(--s3); border-bottom: var(--hair) solid var(--rule); text-align: left; white-space: nowrap; }
th { position: sticky; top: 0; background: var(--panel-hi); z-index: 1; color: var(--ink-dim); }
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
/* Legacy flag-chip sizes stay (anomaly flags) */
.no-flag { color: var(--ink-ghost); }
/* Vol/OI head column */
.vol-oi-head { color: var(--ink-dim); }
/* Timestamp column: trimmed to time only, tighter */
.ts-cell { font-size: var(--t-micro); letter-spacing: 0.03em; }
/* Expiry cell: compact mono */
.expiry-cell { font-size: var(--t-micro); letter-spacing: 0.02em; }
/* Type chip: abbreviated C/P takes less space */
.type-chip { min-width: 24px; }
/* Golden sweep rows: left amber rule + subtle gold wash */
tr.isGoldenSweep {
  background: var(--badge-golden-wash);
  box-shadow: inset 4px 0 0 var(--badge-golden);
}
tr.isGoldenSweep td { color: var(--ink); }
.tape-stalker-card.isGoldenSweep {
  border-left: 3px solid var(--badge-golden);
  background: color-mix(in srgb, var(--badge-golden) 8%, var(--panel));
}
/* Anomalous rows: left rule only, no gradient wash */
tr.anomalous { box-shadow: inset 3px 0 0 var(--warn); }
/* Whale row thresholds — $100k and $500k+ (previously $250k) */
/* Whale rows: progressively heavier left rule, flat background */
tr.isWhale {
  background: var(--warn-wash);
  box-shadow: inset 3px 0 0 var(--warn);
}
tr.isMegaWhale {
  background: color-mix(in srgb, var(--warn) 16%, var(--panel));
  box-shadow: inset 5px 0 0 var(--warn);
}
tr.anomalous td, tr.isWhale td, tr.isMegaWhale td { color: var(--ink); }
.num-col { text-align: right; }
.dim { color: var(--ink-dim); }
.tape-table th { font-size: var(--t-micro); letter-spacing: 0.06em; border-bottom: var(--hair) solid var(--rule-hi); }
.tape-table td { padding: var(--s2) var(--s3); font-size: var(--t-tiny); }
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
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.05em;
}
.type-chip.call { color: var(--call-hi, var(--call)); border-color: color-mix(in srgb, var(--call) 45%, var(--rule)); background: var(--call-wash); }
.type-chip.put { color: var(--put-hi, var(--put)); border-color: color-mix(in srgb, var(--put) 45%, var(--rule)); background: var(--put-wash); }
td.call { color: var(--call-hi, var(--call)); }
td.put { color: var(--put-hi, var(--put)); }
.agg.buy { color: var(--long); background: var(--long-wash); border-color: color-mix(in srgb, var(--long) 40%, var(--rule)); font-weight: 800; }
.agg.sell { color: var(--short); background: var(--short-wash); border-color: color-mix(in srgb, var(--short) 40%, var(--rule)); font-weight: 800; }
.agg.unknown { color: var(--ink-faint); font-size: var(--t-micro); }
.bias-chip.bull, .edge-chip.bull { color: var(--long); border-color: color-mix(in srgb, var(--long) 50%, var(--rule)); background: var(--long-wash); }
.bias-chip.bear, .edge-chip.bear { color: var(--short); border-color: color-mix(in srgb, var(--short) 50%, var(--rule)); background: var(--short-wash); }
.bias-chip.call { color: var(--call-hi, var(--call)); border-color: color-mix(in srgb, var(--call) 40%, var(--rule)); background: var(--call-wash); }
.bias-chip.put { color: var(--put-hi, var(--put)); border-color: color-mix(in srgb, var(--put) 40%, var(--rule)); background: var(--put-wash); }
.bias-chip.unsigned, .edge-chip.unsigned { color: var(--ink-ghost); background: var(--panel-hi); border-color: var(--rule); }
/* Trade class is a classification, not a live/selection state — phosphor is
   reserved for that, so SWEEP reads via weight + a raised neutral fill
   instead of borrowing the page's one accent color. BLOCK keeps the warn
   "large print" cue it already had. */
.class-chip.sweep { color: var(--ink); border-color: var(--ink-faint); background: var(--panel-raise); font-weight: 800; }
.class-chip.block { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 55%, var(--rule)); background: var(--warn-wash); font-weight: 800; }
.class-chip.single { color: var(--ink-dim); background: transparent; }
.est { color: var(--ink-faint); margin-left: 2px; font-size: var(--t-micro); }
.whale-indicator {
  display: inline-block;
  padding: 1px 6px;
  border-radius: var(--r-xs);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.05em;
  line-height: 1.2;
}
.tier-100k {
  color: var(--warn);
  background: var(--warn-wash);
  border: var(--hair) solid color-mix(in srgb, var(--warn) 50%, var(--rule));
}
.tier-500k {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.14);
  border: var(--hair) solid color-mix(in srgb, #f59e0b 60%, var(--rule));
}
.tier-mega-whale {
  color: #fbbf24;
  background: rgba(251, 191, 36, 0.18);
  border: var(--hair) solid color-mix(in srgb, #fbbf24 70%, var(--rule));
  font-weight: 800;
}
.no-tape { min-height: 180px; display: grid; place-content: center; justify-items: center; gap: var(--s2); color: var(--ink-dim); text-align: center; padding: var(--s4); }
.no-tape strong { font: 650 var(--t-small) var(--font-display); letter-spacing: .08em; color: var(--ink); }
.no-tape p { max-width: 54ch; font-size: var(--t-small); }
.reject-hint { max-width: 60ch; color: var(--ink-faint); line-height: 1.5; }
.reject-hint b { color: var(--warn); }
.raw-btn {
  margin-top: var(--s1);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--phosphor-dim);
  color: var(--phosphor);
  background: var(--phosphor-wash);
  letter-spacing: 0.08em;
  cursor: pointer;
}
.raw-btn:hover { border-color: var(--phosphor); }
.tape-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
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
  font-size: var(--t-micro);
  line-height: 1.35;
}

@media (max-width: 1100px) {
  .command {
    grid-template-columns: auto minmax(120px, 1fr) auto auto;
  }
  .expiry-select { grid-column: 1 / 2; }
  .command-right { grid-column: 2 / -1; }
  .kpi-rail { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .tape-toolbar { flex-wrap: wrap; padding-block: 6px; }
  .anomaly-method { width: 100%; margin-left: 0; max-width: none; }
  .unusual-meta { display: none; }
  .live-sub { max-width: 50vw; }
  .quick-filters { margin-left: 0; width: 100%; flex-wrap: wrap; }
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

@media (max-width: 560px) {
  .command-right {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
    margin-left: 0;
  }
  .command-right .scope-chip { grid-column: 1 / -1; }
  .market-flow-link,
  .tune { width: 100%; justify-content: center; }
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
  font-size: var(--t-micro);
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
  padding: var(--s3);
  background: var(--void);
  max-height: min(60vh, 560px);
  overflow-y: auto;
}
.tape-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 1px;
  background: var(--rule);
  border: var(--hair) solid var(--rule);
}
.tape-stalker-card {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  padding: var(--s3);
  background: var(--panel);
  border: 0;
  transition: background var(--dur-fast) var(--ease-out);
}
.tape-stalker-card.bull {
  border-left: 3px solid var(--long);
  background: var(--panel);
}
.tape-stalker-card.bear {
  border-left: 3px solid var(--short);
  background: var(--panel);
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
.lean-pill.bull { color: var(--long); }
.lean-pill.bear { color: var(--short); }
.ts-time { font: 500 10px var(--font-data); color: var(--ink-dim); margin-left: auto; }
.card-body-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 0;
  border-top: var(--hair) solid var(--rule-faint);
  border-bottom: var(--hair) solid var(--rule-faint);
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
