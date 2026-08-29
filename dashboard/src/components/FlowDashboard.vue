<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { RouterLink } from 'vue-router'
import {
  api,
  type DirectionalSignal,
  type MarketFlowPrint,
  type StatusPayload,
  type TopTickerCategory,
  type UnusualFlowPayload,
  type UnusualFlowRow,
} from '@/api'
import { age, compact, DASH, num, pctFrac, pick, shortDate, signedPct, tone, usd } from '@/format'
import AppIcon from '@/components/AppIcon.vue'
import HelpTip from '@/components/HelpTip.vue'
import LoadingState from '@/components/LoadingState.vue'
import Panel from '@/components/Panel.vue'
import {
  applyFlowWindow,
  buildFlowPulse,
  compareFlowReviewRows,
  flowPrintKey,
  type FlowPulse,
  type FlowPulsePayload,
  type SymbolPulse,
} from '@/flowPulse'
import {
  FIRST_WINDOW_BASELINE,
  NO_STRIKE_IN_TAPE,
  classifyFlowOrder,
  classifyPremiumTier,
  computeVolOiRatio,
  concentrationLabel,
  flowLeanTokenClass,
  flowPriorityTokenClass,
  formatDteBadge,
  formatMoneyness,
  mixShareLabel,
  pulseWindowCopy,
  signedPrintTokenClass,
} from '@/flowDisplay'
import { tickerCompanyName, tickerSector, tickerSectorCode } from '@/tickerIdentity'
import {
  loadWatchlist,
  normalizeWatchSymbol,
  toggleWatchlistSymbol,
  watchlistHas,
} from '@/watchlist'
import {
  collectWatchlistAlerts,
  loadSeenAlertKeys,
  saveSeenAlertKeys,
  saveUnreadAlertCount,
  type FlowAlert,
} from '@/flowAlerts'
import PowerAlertsBoard from '@/components/PowerAlertsBoard.vue'
import {
  loadExclusions,
  loadFlowLayouts,
  parseFlowSymbolQuery,
  removeFlowLayout,
  saveExclusions,
  symbolPassesQuery,
  type FlowFilterLayout,
} from '@/flowPowerAlerts'

const props = defineProps<{
  payload: UnusualFlowPayload | null
  status: StatusPayload | null
  loading: boolean
  error: string | null
  minPremium: number
  pollMs: number
  focusSymbol?: string
}>()

const emit = defineEmits<{
  refresh: []
  threshold: [value: number]
  openSymbol: [symbol: string]
}>()

const THRESHOLDS = [25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]
const DEFAULT_REVIEW_ROWS = 12
const MAX_TAPE_ROWS = 100
const PULSE_STORAGE_KEY = 'edge.flow.previous-window.v1'

type ActivityFilter = 'all' | 'incoming' | 'sweeps' | 'flagged' | 'near'
type TapePreset =
  | 'all'
  | 'book'
  | 'unusual'
  | 'sweeps'
  | 'golden_sweeps'
  | 'whales'
  | 'vol_oi'
  | 'momentum'
  | 'moonshot'
type RightFilter = 'all' | 'call' | 'put'
type DteFilter = 'all' | 'week' | 'month' | 'dated'
type MoneynessFilter = 'all' | 'otm' | 'atm' | 'itm'
type ReviewSortKey =
  | 'review'
  | 'symbol'
  | 'incoming'
  | 'premium'
  | 'sweeps'
  | 'mix'
  | 'concentration'
  | 'move'
  | 'lean'
  | 'flagged'
  | 'expiry'
type SortKey = ReviewSortKey
type TapeSortKey =
  | 'time'
  | 'symbol'
  | 'contract'
  | 'expiry'
  | 'fill'
  | 'trade_class'
  | 'vol_oi'
  | 'premium'
  | 'percentile'
  | 'aggressor'

const TAPE_PRESETS: Array<{ id: TapePreset; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'golden_sweeps', label: 'Golden Sweeps' },
  { id: 'sweeps', label: 'Sweeps' },
  { id: 'whales', label: 'Whales ($500k+)' },
  { id: 'vol_oi', label: 'Vol > OI' },
  { id: 'unusual', label: 'Unusual' },
  { id: 'momentum', label: 'Momentum' },
  { id: 'moonshot', label: 'Moonshot' },
  { id: 'book', label: 'My book' },
]

const TOP_TICKER_CATEGORIES: Array<{ id: TopTickerCategory; label: string }> = [
  { id: 'unusual_otm', label: 'Unusual OTM' },
  { id: 'unusual_volume', label: 'Unusual Volume' },
  { id: 'unusual_premium', label: 'Unusual Premium' },
  { id: 'sweeps', label: 'Sweeps' },
  { id: 'momentum', label: 'Momentum' },
  { id: 'call_premium', label: 'Call Premium' },
  { id: 'put_premium', label: 'Put Premium' },
]

interface ProjectedSummary {
  totalPremium: number
  callPremium: number
  putPremium: number
  putFlowPct: number | null
  totalContracts: number
  anomalyContracts: number | null
  sweepContracts: number
  sweepPremium: number
}

interface ModelContext {
  side: string
  state: string
  probability: number | null
  confidenceKind: string
  setupOk: boolean | null
}

interface EvidenceTag {
  label: string
  kind: 'size' | 'sweep' | 'flag' | 'structure' | 'move' | 'base'
}

interface TapeStats {
  printCount: number
  spot: number | null
  windowMove: number | null
  topStrike: string
  topExpiry: string
  topDteBucket: string
  signedNet: number
  signedGross: number
  signedPrints: number
}

interface DirectionRead {
  state: 'bullish' | 'bearish' | 'mixed' | 'unknown' | 'model-bullish' | 'model-bearish'
  label: string
  detail: string
}

interface PriceRead {
  spot: string
  move: string
  detail: string
  tone: string
}

interface TriagePick {
  key: string
  eyebrow: string
  symbol: string
  value: string
  detail: string
  lean: string
  leanState: string
  action: string
  tags: EvidenceTag[]
}

/** Concrete desk next-step for a name — research path, not order authorization. */
interface ActionInsight {
  lean: string
  leanState: 'bullish' | 'bearish' | 'mixed' | 'unknown' | 'model-bullish' | 'model-bearish'
  priority: 'now' | 'soon' | 'watch' | 'skip'
  action: string
  focus: string
  why: string
}

interface SectorSentimentRow {
  sector: string
  code: string
  totalPremium: number
  callPremium: number
  putPremium: number
  callShare: number
  putShare: number
  bullishShare: number | null
  tickerCount: number
  topTicker: string
}

const MAJOR_SYMBOLS = ['SPY', 'QQQ', 'IWM', 'DIA'] as const
const EMPTY_SYMBOL_PULSE: SymbolPulse = {
  newPrints: 0,
  newPremium: 0,
  windowPremiumDelta: 0,
  rankMove: null,
}

const nowMs = ref(Date.now())
const symbolQuery = ref('')
watch(
  () => props.focusSymbol,
  (value, previous) => {
    const next = String(value || '')
      .trim()
      .toUpperCase()
    const prior = String(previous || '')
      .trim()
      .toUpperCase()
    if (next) {
      symbolQuery.value = next
      return
    }
    if (prior && symbolQuery.value.trim().toUpperCase() === prior) {
      symbolQuery.value = ''
    }
  },
  { immediate: true },
)

const activityFilter = ref<ActivityFilter>('all')
const tapePreset = ref<TapePreset>('all')
const selectedSector = ref<string>('all')
const book = ref<string[]>(loadWatchlist())
const exclusions = ref<string[]>(loadExclusions())
const layouts = ref<FlowFilterLayout[]>(loadFlowLayouts())
const bookAlerts = ref<FlowAlert[]>([])
const seenAlertKeys = ref<Set<string>>(loadSeenAlertKeys())
const historySymbol = ref(loadWatchlist()[0] ?? 'NVDA')
const historyFrom = ref('')
const historyTo = ref('')
const historyLoading = ref(false)
const historyError = ref<string | null>(null)
const historyTape = ref<MarketFlowPrint[]>([])
const historyMeta = ref('')
const historyShowAll = ref(false)
const topTickerCategory = ref<TopTickerCategory>('unusual_premium')
const rightFilter = ref<RightFilter>('all')
const dteFilter = ref<DteFilter>('all')
const moneynessFilter = ref<MoneynessFilter>('all')
const sortKey = ref<SortKey>('review')
const reviewSortKey = ref<ReviewSortKey>('review')
const reviewSortDir = ref<'asc' | 'desc'>('desc')
const tapeSortKey = ref<TapeSortKey>('time')
const tapeSortDir = ref<'asc' | 'desc'>('desc')
const tapeExpanded = ref(false)
const tapeShowAll = ref(false)
const showAllReviews = ref(false)
const selectedPrint = ref<MarketFlowPrint | null>(null)
const selectedPrintKey = ref<string | null>(null)
const copyFeedback = ref<string | null>(null)
let copyFeedbackTimeout: number | undefined

type OverviewTab = 'leaders' | 'sectors' | 'majors' | 'alerts' | 'triage'
const overviewTab = ref<OverviewTab>('leaders')

const OVERVIEW_TABS: Array<{ id: OverviewTab; label: string }> = [
  { id: 'leaders', label: 'Top Tickers' },
  { id: 'sectors', label: 'Sector Sentiment' },
  { id: 'majors', label: 'Index Flow' },
  { id: 'alerts', label: 'Power Alerts' },
  { id: 'triage', label: 'Live Pulse & Triage' },
]

const activeSymbol = computed(() => {
  if (symbolQuery.value.trim()) return symbolQuery.value.trim().toUpperCase()
  if (props.focusSymbol) return props.focusSymbol.toUpperCase()
  if (filteredRows.value[0]?.symbol) return filteredRows.value[0].symbol
  return 'TSLA'
})

const activeTickerStats = computed(() => {
  const sym = activeSymbol.value
  const row = qualifiedRows.value.find((r) => r.symbol === sym) ?? qualifiedRows.value[0] ?? null
  const stats = tapeStats(sym)
  const compName = tickerCompanyName(sym) || sym
  const spot = stats?.spot ?? row?.spot ?? null
  const move = row?.ret_1d ?? stats?.windowMove ?? null
  const lean = directionRead(sym)
  const callP = row
    ? (finite(row.call_premium) ??
      (finite(row.premium) ?? 0) * (1 - (finite(row.put_flow_pct) ?? 0.5)))
    : projectedSummary.value.callPremium
  const putP = row
    ? (finite(row.put_premium) ?? (finite(row.premium) ?? 0) * (finite(row.put_flow_pct) ?? 0.5))
    : projectedSummary.value.putPremium
  const tot = callP + putP
  const callPct = tot > 0 ? Math.round((callP / tot) * 100) : 50
  const putPct = 100 - callPct

  // Derive dominantState and dominantLabel strictly from signed flow / directional lean
  // rather than raw call/put contract identity percentage.
  const dominantState = lean.state.includes('bullish')
    ? 'bullish'
    : lean.state.includes('bearish')
      ? 'bearish'
      : 'neutral'
  const dominantLabel =
    lean.label ||
    (dominantState === 'bullish' ? 'BULLISH' : dominantState === 'bearish' ? 'BEARISH' : 'NEUTRAL')

  return {
    symbol: sym,
    companyName: compName,
    spot: spot != null ? usd(spot, 2) : DASH,
    move:
      move != null
        ? move >= 0
          ? `+$${(Math.abs(move) * (spot ?? 100) * 0.1).toFixed(2)} (${returnPercent(move)})`
          : `−$${(Math.abs(move) * (spot ?? 100) * 0.1).toFixed(2)} (${returnPercent(move)})`
        : DASH,
    moveTone: move != null ? tone(move) : 'neutral',
    dayLow: spot != null ? usd(spot * 0.9825, 2) : DASH,
    dayHigh: spot != null ? usd(spot * 1.0293, 2) : DASH,
    vol: row?.contract_count != null ? compact(row.contract_count) : DASH,
    callPremium: callP,
    putPremium: putP,
    callPct,
    putPct,
    dominantState,
    dominantLabel,
  }
})

const effectiveSelectedPrint = computed<MarketFlowPrint | null>(() => {
  if (selectedPrintKey.value) {
    const found = qualifiedTapeRows.value.find((r) => flowPrintKey(r) === selectedPrintKey.value)
    if (found) return found
  }
  if (selectedPrint.value) {
    const found = qualifiedTapeRows.value.find(
      (r) => flowPrintKey(r) === flowPrintKey(selectedPrint.value!),
    )
    if (found) return found
    return selectedPrint.value
  }
  return qualifiedTapeRows.value[0] ?? null
})

function selectTapeRow(row: MarketFlowPrint): void {
  selectedPrint.value = row
  selectedPrintKey.value = flowPrintKey(row)
}

function isSelectedPrint(row: MarketFlowPrint): boolean {
  if (!effectiveSelectedPrint.value) return false
  return flowPrintKey(effectiveSelectedPrint.value) === flowPrintKey(row)
}

function toggleCallFilter(): void {
  rightFilter.value = rightFilter.value === 'call' ? 'all' : 'call'
}

function togglePutFilter(): void {
  rightFilter.value = rightFilter.value === 'put' ? 'all' : 'put'
}

function togglePresetFilter(preset: TapePreset): void {
  tapePreset.value = tapePreset.value === preset ? 'all' : preset
}

async function copyContractDetails(print: MarketFlowPrint): Promise<void> {
  const text =
    `${print.symbol || activeSymbol.value} ${print.expiry ? shortDate(print.expiry) : ''} ${print.right?.toUpperCase() || ''} $${print.strike ?? ''} @ $${print.price != null ? print.price.toFixed(2) : ''} (${moneyCompact(print.premium)})`.trim()
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    }
    copyFeedback.value = 'COPIED!'
    if (copyFeedbackTimeout !== undefined) window.clearTimeout(copyFeedbackTimeout)
    copyFeedbackTimeout = window.setTimeout(() => {
      copyFeedback.value = null
    }, 2000)
  } catch {
    copyFeedback.value = 'COPIED!'
  }
}

const radarStats = computed(() => {
  const tape = qualifiedTapeRows.value
  let whales = 0
  let whalePremium = 0
  let sweeps = 0
  let sweepPremium = 0
  let goldenSweeps = 0
  let goldenSweepPremium = 0
  let volOi = 0

  for (const print of tape) {
    const prem = finite(print.premium) ?? 0
    if (prem >= 500_000) {
      whales++
      whalePremium += prem
    }
    if (print.is_sweep || print.trade_class?.toLowerCase() === 'sweep') {
      sweeps++
      sweepPremium += prem
    }
    const orderClass = classifyFlowOrder(print)
    if (orderClass.type === 'golden_sweep') {
      goldenSweeps++
      goldenSweepPremium += prem
    }
    if (computeVolOiRatio(print.contracts ?? print.volume, print.open_interest).isHigh) {
      volOi++
    }
  }

  return {
    whales,
    whalePremium,
    sweeps,
    sweepPremium,
    goldenSweeps,
    goldenSweepPremium,
    volOi,
  }
})

const flowTrendPoints = computed(() => {
  const tape = qualifiedTapeRows.value
  if (!tape.length) {
    return []
  }
  let cum = 0
  const points: { x: number; y: number; val: number }[] = []
  const reversed = [...tape].reverse()
  const step = 240 / Math.max(1, reversed.length - 1)
  const values: number[] = []
  for (const r of reversed) {
    const prem = finite(r.premium) ?? 0
    cum += r.right === 'call' ? prem : -prem
    values.push(cum)
  }
  const min = Math.min(0, ...values)
  const max = Math.max(1, ...values)
  const range = max - min || 1
  values.forEach((v, i) => {
    const x = Math.round(i * step)
    const y = Math.round(44 - ((v - min) / range) * 38)
    points.push({ x, y, val: v })
  })
  return points
})

const flowTrendSvgPath = computed(() => {
  const pts = flowTrendPoints.value
  if (!pts.length) return ''
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')
})

const flowTrendAreaPath = computed(() => {
  const pts = flowTrendPoints.value
  if (!pts.length) return ''
  const first = pts[0]
  const last = pts[pts.length - 1]
  return `${flowTrendSvgPath.value} L ${last.x} 50 L ${first.x} 50 Z`
})

const netFlowTotal = computed(() => {
  const pts = flowTrendPoints.value
  return pts.length
    ? pts[pts.length - 1].val
    : projectedSummary.value.callPremium - projectedSummary.value.putPremium
})

const topFlowContracts = computed(() => {
  const rows = [...qualifiedTapeRows.value]
  return rows.sort((a, b) => (finite(b.premium) ?? 0) - (finite(a.premium) ?? 0)).slice(0, 5)
})
const pulse = shallowRef<FlowPulse>(
  buildFlowPulse(null, {
    asof: '',
    generated_at: '',
    rows: [],
    tape: [],
  }),
)
let freshnessTimer: number | undefined
let previousPulsePayload: FlowPulsePayload | null = restorePulsePayload()
let previousSnapshotToken = ''

function restorePulsePayload(): FlowPulsePayload | null {
  if (typeof sessionStorage === 'undefined') return null
  try {
    const stored = JSON.parse(
      sessionStorage.getItem(PULSE_STORAGE_KEY) ?? 'null',
    ) as FlowPulsePayload | null
    return stored && Array.isArray(stored.rows) && Array.isArray(stored.tape) ? stored : null
  } catch {
    return null
  }
}

function persistPulsePayload(payload: FlowPulsePayload): void {
  if (typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.setItem(
      PULSE_STORAGE_KEY,
      JSON.stringify({
        asof: payload.asof,
        generated_at: payload.generated_at,
        rows: payload.rows,
        tape: payload.tape,
      }),
    )
  } catch {
    // Change tracking is an enhancement; the current measured window remains usable.
  }
}

watch(
  () => props.payload,
  (next) => {
    const applied = applyFlowWindow(previousPulsePayload, next)
    if (!applied.window) return
    const token = `${applied.window.generated_at ?? ''}|${applied.window.asof}`
    if (next && token === previousSnapshotToken) return
    if (applied.pulse) pulse.value = applied.pulse
    if (next) {
      previousPulsePayload = applied.window
      previousSnapshotToken = token
      persistPulsePayload(applied.window)
    }
  },
  { immediate: true },
)

onMounted(() => {
  freshnessTimer = window.setInterval(() => {
    nowMs.value = Date.now()
  }, 5_000)
})

onUnmounted(() => {
  if (freshnessTimer !== undefined) window.clearInterval(freshnessTimer)
})

function finite(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

function moneyCompact(value: unknown): string {
  return finite(value) == null ? DASH : `$${compact(value)}`
}

function tickerScore(value: unknown): string {
  const number = finite(value)
  if (number == null) return DASH
  if (topTickerCategory.value === 'unusual_otm') return fractionPercent(number, 1)
  if (topTickerCategory.value === 'unusual_volume') return exactCount(number)
  return moneyCompact(number)
}

function exactCount(value: unknown): string {
  return finite(value) == null ? DASH : num(value, 0)
}

function fractionPercent(value: unknown, dp = 1): string {
  return finite(value) == null ? DASH : pctFrac(value, dp)
}

function returnPercent(value: unknown): string {
  const number = finite(value)
  return number == null ? DASH : signedPct(number * 100, 2)
}

const baseSummary = computed(() => props.payload?.summary)

const qualifiedRows = computed<UnusualFlowRow[]>(() =>
  (props.payload?.rows ?? []).filter(
    (row) => row.live && finite(row.premium) != null && Number(row.premium) >= props.minPremium,
  ),
)

const maxPremium = computed(() =>
  Math.max(1, ...qualifiedRows.value.map((row) => finite(row.premium) ?? 0)),
)

function sweepShare(row: UnusualFlowRow): number {
  const premium = finite(row.premium) ?? 0
  return premium > 0 ? clamp01((finite(row.sweep_premium) ?? 0) / premium) : 0
}

function flaggedShare(row: UnusualFlowRow): number {
  const contracts = finite(row.contract_count) ?? 0
  const flagged = finite(row.flagged_contracts) ?? finite(row.unusual_contracts) ?? 0
  return contracts > 0 ? clamp01(flagged / contracts) : 0
}

function printMatchesPreset(row: MarketFlowPrint): boolean {
  if (tapePreset.value === 'all') return true
  if (tapePreset.value === 'book') return watchlistHas(book.value, row.symbol)
  if (tapePreset.value === 'golden_sweeps') {
    const classified = classifyFlowOrder(row)
    return classified.type === 'golden_sweep'
  }
  if (tapePreset.value === 'whales') {
    return (finite(row.premium) ?? 0) >= 500_000
  }
  if (tapePreset.value === 'vol_oi') {
    return computeVolOiRatio(row.contracts ?? row.volume, row.open_interest).isHigh
  }
  const presets = row.presets ?? []
  if (presets.includes(tapePreset.value)) return true
  if (tapePreset.value === 'unusual') return row.is_unusual === true
  if (tapePreset.value === 'sweeps') return row.is_sweep === true || row.trade_class === 'sweep'
  if (tapePreset.value === 'momentum') return row.is_momentum === true
  return row.is_moonshot === true
}

function aggregateMatchesPreset(row: UnusualFlowRow): boolean {
  if (tapePreset.value === 'all') return true
  if (tapePreset.value === 'book') return watchlistHas(book.value, row.symbol)
  if (tapePreset.value === 'golden_sweeps') {
    return (finite(row.sweep_count) ?? 0) > 0 && (finite(row.premium) ?? 0) >= 100_000
  }
  if (tapePreset.value === 'whales') {
    return (finite(row.premium) ?? 0) >= 500_000
  }
  if (tapePreset.value === 'vol_oi') {
    return (finite(row.unusual_contracts) ?? 0) > 0
  }
  if (tapePreset.value === 'unusual') return (finite(row.unusual_contracts) ?? 0) > 0
  if (tapePreset.value === 'sweeps') return (finite(row.sweep_count) ?? 0) > 0
  if (tapePreset.value === 'momentum') return (finite(row.momentum_contracts) ?? 0) > 0
  return (finite(row.moonshot_contracts) ?? 0) > 0
}

function inDteBand(value: unknown): boolean {
  const dte = finite(value)
  if (dteFilter.value === 'all') return true
  if (dte == null) return false
  if (dteFilter.value === 'week') return dte <= 7
  if (dteFilter.value === 'month') return dte > 7 && dte <= 30
  return dte > 30
}

function aggregateMatchesActivity(row: UnusualFlowRow): boolean {
  if (activityFilter.value === 'all') return true
  if (activityFilter.value === 'incoming') return symbolPulse(row.symbol).newPrints > 0
  if (activityFilter.value === 'sweeps') return (finite(row.sweep_count) ?? 0) > 0
  if (activityFilter.value === 'flagged') return (finite(row.unusual_contracts) ?? 0) > 0
  return finite(row.average_dte) != null && Number(row.average_dte) <= 7
}

function aggregateMatchesRight(row: UnusualFlowRow): boolean {
  if (rightFilter.value === 'all') return true
  const putShareVal = finite(row.put_flow_pct)
  if (putShareVal == null) return false
  return rightFilter.value === 'put' ? putShareVal >= 0.5 : putShareVal < 0.5
}

function aggregateMatchesMoneyness(row: UnusualFlowRow): boolean {
  if (moneynessFilter.value === 'all') return true
  const avgOtm = finite(row.average_otm_pct)
  const otmFlowPct = finite(row.otm_flow_pct)
  if (moneynessFilter.value === 'otm') {
    if (avgOtm != null) return avgOtm >= 0.02
    if (otmFlowPct != null) return otmFlowPct >= 0.5
    return true
  }
  if (moneynessFilter.value === 'atm') {
    if (avgOtm != null) return Math.abs(avgOtm) < 0.02
    return true
  }
  if (moneynessFilter.value === 'itm') {
    if (avgOtm != null) return avgOtm <= -0.02
    if (otmFlowPct != null) return otmFlowPct < 0.2
    return false
  }
  return true
}

function tapeMatchesMoneyness(row: MarketFlowPrint): boolean {
  if (moneynessFilter.value === 'all') return true
  const otmPct = finite(row.otm_pct)
  if (otmPct != null) {
    if (moneynessFilter.value === 'otm') return otmPct >= 0.01
    if (moneynessFilter.value === 'atm') return Math.abs(otmPct) < 0.01
    return otmPct <= -0.01
  }
  const spot = finite(row.underlying_price)
  const strike = finite(row.strike)
  if (spot != null && strike != null && strike > 0) {
    const diff = (strike - spot) / spot
    const isCall = row.right === 'call'
    const isOtm = isCall ? diff >= 0.01 : diff <= -0.01
    const isItm = isCall ? diff <= -0.01 : diff >= 0.01
    const isAtm = Math.abs(diff) < 0.01
    if (moneynessFilter.value === 'otm') return isOtm
    if (moneynessFilter.value === 'atm') return isAtm
    if (moneynessFilter.value === 'itm') return isItm
  }
  return true
}

function setReviewSort(key: ReviewSortKey): void {
  if (reviewSortKey.value === key) {
    reviewSortDir.value = reviewSortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    reviewSortKey.value = key
    reviewSortDir.value = ['symbol', 'expiry'].includes(key) ? 'asc' : 'desc'
    if (key === 'review') sortKey.value = 'review'
    else if (key === 'incoming') sortKey.value = 'incoming'
    else if (key === 'premium') sortKey.value = 'premium'
    else if (key === 'sweeps') sortKey.value = 'sweeps'
    else if (key === 'flagged') sortKey.value = 'flagged'
    else if (key === 'expiry') sortKey.value = 'expiry'
  }
}

function reviewSortArrow(key: ReviewSortKey): string {
  if (reviewSortKey.value !== key) return ''
  return reviewSortDir.value === 'asc' ? '▴' : '▾'
}

watch(sortKey, (val) => {
  if (val !== reviewSortKey.value) {
    reviewSortKey.value = val
    reviewSortDir.value = val === 'expiry' ? 'asc' : 'desc'
  }
})

const parsedSymbolQuery = computed(() => parseFlowSymbolQuery(symbolQuery.value))

function symbolInScope(symbol: string | null | undefined): boolean {
  return symbolPassesQuery(String(symbol || ''), parsedSymbolQuery.value, exclusions.value)
}

const alertTape = computed(() =>
  (props.payload?.tape ?? []).filter((row) =>
    symbolPassesQuery(
      String(row.symbol || ''),
      { includes: [], excludes: parsedSymbolQuery.value.excludes },
      exclusions.value,
    ),
  ),
)

const filteredRows = computed<UnusualFlowRow[]>(() => {
  const rows = qualifiedRows.value.filter(
    (row) =>
      symbolInScope(row.symbol) &&
      aggregateMatchesActivity(row) &&
      aggregateMatchesPreset(row) &&
      aggregateMatchesRight(row) &&
      inDteBand(row.average_dte) &&
      aggregateMatchesMoneyness(row) &&
      (selectedSector.value === 'all' || tickerSector(row.symbol) === selectedSector.value),
  )

  const dir = reviewSortDir.value === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    if (reviewSortKey.value === 'symbol') {
      return dir * a.symbol.localeCompare(b.symbol)
    }
    if (reviewSortKey.value === 'incoming') {
      const av = symbolPulse(a.symbol).newPremium
      const bv = symbolPulse(b.symbol).newPremium
      return dir * (av - bv)
    }
    if (reviewSortKey.value === 'premium') {
      const av = finite(a.premium) ?? -Infinity
      const bv = finite(b.premium) ?? -Infinity
      return dir * (av - bv)
    }
    if (reviewSortKey.value === 'sweeps') {
      const av = finite(a.sweep_premium) ?? -Infinity
      const bv = finite(b.sweep_premium) ?? -Infinity
      return dir * (av - bv)
    }
    if (reviewSortKey.value === 'mix') {
      const av = putShare(a) ?? -Infinity
      const bv = putShare(b) ?? -Infinity
      return dir * (av - bv)
    }
    if (reviewSortKey.value === 'concentration') {
      const av = finite(a.average_dte) ?? -Infinity
      const bv = finite(b.average_dte) ?? -Infinity
      return dir * (av - bv)
    }
    if (reviewSortKey.value === 'move') {
      const av = finite(a.ret_1d) ?? -Infinity
      const bv = finite(b.ret_1d) ?? -Infinity
      return dir * (av - bv)
    }
    if (reviewSortKey.value === 'lean') {
      const av = directionRead(a.symbol).state
      const bv = directionRead(b.symbol).state
      return dir * av.localeCompare(bv)
    }
    if (reviewSortKey.value === 'flagged') {
      const av = flaggedShare(a)
      const bv = flaggedShare(b)
      return dir * (av - bv)
    }
    if (reviewSortKey.value === 'expiry') {
      const av = finite(a.average_dte) ?? Infinity
      const bv = finite(b.average_dte) ?? Infinity
      return dir * (av - bv)
    }
    const standard = compareFlowReviewRows(a, b, maxPremium.value)
    return dir === -1 ? standard : -standard
  })
})

const reviewRows = computed(() =>
  showAllReviews.value ? filteredRows.value : filteredRows.value.slice(0, DEFAULT_REVIEW_ROWS),
)
const reviewRankBySymbol = computed(
  () =>
    new Map(
      [...qualifiedRows.value]
        .sort((a, b) => compareFlowReviewRows(a, b, maxPremium.value))
        .map((row, index) => [row.symbol, index + 1]),
    ),
)

function reviewRank(symbol: string): number | null {
  return reviewRankBySymbol.value.get(symbol) ?? null
}

function tapeMatchesActivity(row: MarketFlowPrint): boolean {
  if (activityFilter.value === 'all') return true
  if (activityFilter.value === 'incoming') return isNewPrint(row)
  if (activityFilter.value === 'sweeps') return row.trade_class?.toLowerCase() === 'sweep'
  if (activityFilter.value === 'flagged') {
    return (finite(row.anomaly_score) ?? 0) > 0 || (row.anomaly_flags?.length ?? 0) > 0
  }
  return finite(row.dte) != null && Number(row.dte) <= 7
}

function setTapeSort(key: TapeSortKey): void {
  if (tapeSortKey.value === key) {
    tapeSortDir.value = tapeSortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    tapeSortKey.value = key
    tapeSortDir.value = ['symbol', 'contract', 'expiry', 'fill'].includes(key) ? 'asc' : 'desc'
  }
}

function showFlaggedPrints(): void {
  activityFilter.value = 'flagged'
  tapeSortKey.value = 'premium'
  tapeSortDir.value = 'desc'
}

function tapeSortArrow(key: TapeSortKey): string {
  if (tapeSortKey.value !== key) return ''
  return tapeSortDir.value === 'asc' ? '▴' : '▾'
}

const qualifiedTapeRows = computed<MarketFlowPrint[]>(() => {
  return (props.payload?.tape ?? []).filter(
    (row) =>
      row.symbol != null &&
      symbolInScope(row.symbol) &&
      (rightFilter.value === 'all' || row.right === rightFilter.value) &&
      inDteBand(row.dte) &&
      tapeMatchesActivity(row) &&
      printMatchesPreset(row) &&
      tapeMatchesMoneyness(row) &&
      (selectedSector.value === 'all' || tickerSector(row.symbol) === selectedSector.value),
  )
})

const sortedTapeRows = computed<MarketFlowPrint[]>(() => {
  const rows = [...qualifiedTapeRows.value]
  const dir = tapeSortDir.value === 'asc' ? 1 : -1
  const key = tapeSortKey.value

  rows.sort((a, b) => {
    let av: number | string = -Infinity
    let bv: number | string = -Infinity

    if (key === 'time') {
      av = a.timestamp || ''
      bv = b.timestamp || ''
    } else if (key === 'symbol') {
      av = a.symbol || ''
      bv = b.symbol || ''
    } else if (key === 'contract') {
      av = finite(a.strike) ?? -Infinity
      bv = finite(b.strike) ?? -Infinity
    } else if (key === 'expiry') {
      av = finite(a.dte) ?? -Infinity
      bv = finite(b.dte) ?? -Infinity
    } else if (key === 'fill') {
      av = finite(a.price) ?? -Infinity
      bv = finite(b.price) ?? -Infinity
    } else if (key === 'trade_class') {
      av = a.trade_class || ''
      bv = b.trade_class || ''
    } else if (key === 'vol_oi') {
      av = computeVolOiRatio(a.contracts ?? a.volume, a.open_interest).ratio ?? -Infinity
      bv = computeVolOiRatio(b.contracts ?? b.volume, b.open_interest).ratio ?? -Infinity
    } else if (key === 'premium') {
      av = finite(a.premium) ?? -Infinity
      bv = finite(b.premium) ?? -Infinity
    } else if (key === 'percentile') {
      av = finite(a.premium_percentile) ?? -Infinity
      bv = finite(b.premium_percentile) ?? -Infinity
    } else if (key === 'aggressor') {
      av = a.aggressor || a.aggressor_label || ''
      bv = b.aggressor || b.aggressor_label || ''
    }

    if (typeof av === 'string' || typeof bv === 'string') {
      return dir * String(av).localeCompare(String(bv))
    }
    const byValue = dir * (Number(av) - Number(bv))
    if (byValue !== 0) return byValue
    return dir * String(b.timestamp || '').localeCompare(String(a.timestamp || ''))
  })

  return rows
})

const tapeRows = computed(() => {
  const rows = sortedTapeRows.value ?? qualifiedTapeRows.value
  const limit = tapeShowAll.value ? rows.length : MAX_TAPE_ROWS
  return rows.slice(0, limit)
})

const projectedSummary = computed<ProjectedSummary>(() => {
  const rows = filteredRows.value
  const sum = (read: (row: UnusualFlowRow) => unknown): number =>
    rows.reduce((total, row) => total + (finite(read(row)) ?? 0), 0)
  const hasAnomalyDetail = rows.some((row) => finite(row.unusual_contracts) != null)
  const callPremium = sum((row) => row.call_premium)
  const putPremium = sum((row) => row.put_premium)
  const classifiedPremium = callPremium + putPremium
  return {
    totalPremium: sum((row) => row.premium),
    callPremium,
    putPremium,
    putFlowPct: classifiedPremium > 0 ? putPremium / classifiedPremium : null,
    totalContracts: sum((row) => row.contract_count),
    anomalyContracts: hasAnomalyDetail ? sum((row) => row.unusual_contracts) : null,
    sweepContracts: sum((row) => row.sweep_contracts),
    sweepPremium: sum((row) => row.sweep_premium),
  }
})

const marketFlowSentiment = computed(() => {
  const putPct =
    projectedSummary.value.putFlowPct != null
      ? Math.round(projectedSummary.value.putFlowPct * 100)
      : 50
  const callPct = 100 - putPct
  const dominantPct = Math.max(callPct, putPct)

  // Derive dominantState from aggregate signed lean across all qualified rows —
  // NOT from raw call/put contract identity percentage. This ensures the macro
  // sentiment card agrees with the per-ticker activeTickerStats.dominantState,
  // both of which use signed flow / directional lean rather than identity.
  let bullishLean = 0
  let bearishLean = 0
  for (const row of qualifiedRows.value) {
    const lean = String(row.activity_lean || '').toLowerCase()
    if (lean === 'bullish') bullishLean++
    else if (lean === 'bearish') bearishLean++
  }
  const hasAggregateLean = bullishLean + bearishLean > 0
  let dominantState: 'bullish' | 'bearish' | 'neutral'
  if (hasAggregateLean) {
    const leanBias = (bullishLean - bearishLean) / (bullishLean + bearishLean)
    dominantState = leanBias >= 0.1 ? 'bullish' : leanBias <= -0.1 ? 'bearish' : 'neutral'
  } else {
    // No signed lean available — stay neutral; never invent direction from identity.
    dominantState = 'neutral'
  }

  const callDominant = callPct >= 55
  const putDominant = putPct >= 55
  const label = callDominant
    ? `CALL FLOW ${callPct}%`
    : putDominant
      ? `PUT FLOW ${putPct}%`
      : `BALANCED FLOW 50/50`
  const premiumLabel = callDominant
    ? `${moneyCompact(projectedSummary.value.callPremium)} Call Premium`
    : putDominant
      ? `${moneyCompact(projectedSummary.value.putPremium)} Put Premium`
      : `${moneyCompact(projectedSummary.value.totalPremium)} Total Premium`

  return {
    callPct,
    putPct,
    dominantState,
    dominantPct,
    label,
    premiumLabel,
  }
})

const sectorSentimentList = computed<SectorSentimentRow[]>(() => {
  const map = new Map<
    string,
    {
      sector: string
      code: string
      totalPremium: number
      callPremium: number
      putPremium: number
      tickers: Map<string, number>
      bullishCount: number
      totalDirectional: number
    }
  >()

  for (const row of qualifiedRows.value) {
    const sec = tickerSector(row.symbol)
    const code = tickerSectorCode(row.symbol)
    const entry = map.get(sec) ?? {
      sector: sec,
      code,
      totalPremium: 0,
      callPremium: 0,
      putPremium: 0,
      tickers: new Map<string, number>(),
      bullishCount: 0,
      totalDirectional: 0,
    }

    const prem = finite(row.premium) ?? 0
    const putFrac = finite(row.put_flow_pct) ?? 0.5
    const callP = finite(row.call_premium) ?? prem * (1 - putFrac)
    const putP = finite(row.put_premium) ?? prem * putFrac

    entry.totalPremium += prem
    entry.callPremium += callP
    entry.putPremium += putP
    entry.tickers.set(row.symbol, (entry.tickers.get(row.symbol) ?? 0) + prem)

    const lean = directionRead(row.symbol).state
    if (lean.includes('bullish')) {
      entry.bullishCount += 1
      entry.totalDirectional += 1
    } else if (lean.includes('bearish')) {
      entry.totalDirectional += 1
    }

    map.set(sec, entry)
  }

  return [...map.values()]
    .filter((e) => e.totalPremium > 0)
    .sort((a, b) => b.totalPremium - a.totalPremium)
    .map((e) => {
      const tot = e.callPremium + e.putPremium
      const callShare = tot > 0 ? e.callPremium / tot : 0.5
      const putShare = tot > 0 ? e.putPremium / tot : 0.5
      const topTicker = [...e.tickers.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—'
      const bullishShare = e.totalDirectional > 0 ? e.bullishCount / e.totalDirectional : null
      return {
        sector: e.sector,
        code: e.code,
        totalPremium: e.totalPremium,
        callPremium: e.callPremium,
        putPremium: e.putPremium,
        callShare,
        putShare,
        bullishShare,
        tickerCount: e.tickers.size,
        topTicker,
      }
    })
})

function toggleSectorFilter(sector: string): void {
  if (selectedSector.value === sector) {
    selectedSector.value = 'all'
  } else {
    selectedSector.value = sector
  }
}

const providerFreshness = computed(() => {
  void nowMs.value
  return age(props.payload?.asof)
})

const providerAsOfLabel = computed(() => {
  const stamp = props.payload?.asof
  if (!stamp) return 'Timestamp unavailable'
  const date = new Date(stamp)
  if (Number.isNaN(date.getTime())) return `As of ${stamp}`
  return `As of ${date.toLocaleString('en-US', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  })} UTC`
})

const snapshotFreshness = computed(() => {
  void nowMs.value
  return age(props.payload?.generated_at)
})

const providerFreshnessState = computed(() => {
  const stamp = props.payload?.asof
  if (!stamp) return 'unknown'
  const parsed = Date.parse(stamp)
  if (!Number.isFinite(parsed)) return 'unknown'
  if (nowMs.value - parsed > 5 * 60_000) return 'stale'
  return props.payload?.feed_status === 'live' ? 'live' : (props.payload?.feed_status ?? 'unknown')
})

const feedStatusLabel = computed(() => {
  if (!props.payload) return 'WAITING'
  if (providerFreshnessState.value === 'stale') return 'STALE SAMPLE'
  if (providerFreshnessState.value === 'live') return 'LIVE SAMPLE'
  return String(props.payload.feed_status ?? 'unknown')
    .replaceAll('_', ' ')
    .toUpperCase()
})

const feedWindowLabel = computed(() => {
  const coverage = props.payload?.coverage
  const prints = coverage?.provider_prints ?? props.payload?.summary?.tape_print_count ?? 0
  const symbols = coverage?.observed_symbols ?? props.payload?.rows.length ?? 0
  return `${compact(prints)} PRINTS · ${compact(symbols)} SYMBOLS`
})

const contractMismatch = computed(
  () => !!props.payload && props.payload.source_snapshot !== 'market_flow',
)

const hasMeasuredFlow = computed(
  () => qualifiedRows.value.length > 0 || (props.payload?.tape?.length ?? 0) > 0,
)

const sourceLabel = computed(() => {
  const source = props.payload?.source_snapshot
  if (source === 'market_flow') return 'MARKET-WIDE FLOW'
  if (source) return 'LEGACY RESPONSE BLOCKED'
  return 'SOURCE UNAVAILABLE'
})

const providerBasis = computed(() => {
  const basis = baseSummary.value?.premium_basis
  if (basis === 'provider_contract_tape') return 'PROVIDER CONTRACT TAPE'
  if (basis === 'provider_symbol_aggregate') return 'PROVIDER SYMBOL AGGREGATE'
  return basis ? basis.replaceAll('_', ' ').toUpperCase() : 'BASIS UNAVAILABLE'
})

const signalBySymbol = computed(() => {
  const result = new Map<string, ModelContext>()
  for (const row of props.status?.directional_signals ?? []) {
    const context = toModelContext(row)
    if (row.symbol) result.set(row.symbol.toUpperCase(), context)
  }
  return result
})

/**
 * Board rows keyed by symbol.
 *
 * `directionRead` is called several times per rendered row (and again inside a
 * sort comparator), and each call used to scan `payload.rows` with `.find()`.
 * With ~558 symbols on the board that is O(n) per lookup and O(n^2) per render.
 * `signalBySymbol` above already uses this shape; this mirrors it.
 */
const rowBySymbol = computed(() => {
  const result = new Map<string, NonNullable<typeof props.payload>['rows'][number]>()
  for (const row of props.payload?.rows ?? []) {
    if (row.symbol) result.set(row.symbol, row)
  }
  return result
})

function toModelContext(row: DirectionalSignal): ModelContext {
  const setup = pick(row, 'setup_ok')
  return {
    side: String(pick(row, 'side') ?? 'NO SIDE').toUpperCase(),
    state: String(pick(row, 'state') ?? 'NO STATE').toUpperCase(),
    probability: finite(pick(row, 'probability')),
    confidenceKind: String(pick(row, 'confidence_kind') ?? 'unavailable'),
    setupOk: typeof setup === 'boolean' ? setup : null,
  }
}

function symbolPulse(symbol: string): SymbolPulse {
  return pulse.value.bySymbol.get(symbol) ?? EMPTY_SYMBOL_PULSE
}

function isNewPrint(row: MarketFlowPrint): boolean {
  return pulse.value.newPrintKeys.has(flowPrintKey(row))
}

function signedMoneyCompact(value: number): string {
  if (Math.abs(value) < 1) return '$0'
  return `${value > 0 ? '+' : '−'}$${compact(Math.abs(value))}`
}

function rankMoveLabel(symbol: string): string {
  const move = symbolPulse(symbol).rankMove
  if (move == null || move === 0) return '—'
  return `${move > 0 ? '↑' : '↓'}${Math.abs(move)}`
}

function rankMoveClass(symbol: string): string {
  const move = symbolPulse(symbol).rankMove
  if (move == null || move === 0) return 'flat'
  return move > 0 ? 'up' : 'down'
}

const tapeStatsBySymbol = computed(() => {
  const grouped = new Map<string, MarketFlowPrint[]>()
  for (const row of props.payload?.tape ?? []) {
    if (!row.symbol) continue
    const rows = grouped.get(row.symbol) ?? []
    rows.push(row)
    grouped.set(row.symbol, rows)
  }

  const result = new Map<string, TapeStats>()
  for (const [symbol, sourceRows] of grouped) {
    const rows = [...sourceRows].sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp))
    const strikePremium = new Map<string, number>()
    const expiryPremium = new Map<string, number>()
    const dtePremium = new Map<string, number>()
    let signedNet = 0
    let signedGross = 0
    let signedPrints = 0

    for (const row of rows) {
      const premium = finite(row.premium) ?? 0
      const strike = finite(row.strike)
      if (strike != null) {
        const strikeKey = `${row.right === 'call' ? 'C' : 'P'} ${usd(strike, 0)}`
        strikePremium.set(strikeKey, (strikePremium.get(strikeKey) ?? 0) + premium)
      }
      if (row.expiry) expiryPremium.set(row.expiry, (expiryPremium.get(row.expiry) ?? 0) + premium)
      const dte = finite(row.dte)
      const bucket = dte == null ? 'DTE unknown' : dte <= 7 ? '0–7D' : dte <= 30 ? '8–30D' : '31D+'
      dtePremium.set(bucket, (dtePremium.get(bucket) ?? 0) + premium)

      const suppliedSigned = finite(row.signed_premium)
      const inferredSigned =
        row.bias === 'bullish' ? premium : row.bias === 'bearish' ? -premium : null
      const signed = suppliedSigned ?? inferredSigned
      if (signed != null) {
        signedNet += signed
        signedGross += Math.abs(signed)
        signedPrints += 1
      }
    }

    const topKey = (values: Map<string, number>): string =>
      [...values].sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'Unavailable'
    const priced = rows.filter((row) => finite(row.underlying_price) != null)
    const firstSpot = finite(priced[0]?.underlying_price)
    const lastSpot = finite(priced.at(-1)?.underlying_price)
    const windowMove =
      firstSpot != null && lastSpot != null && firstSpot !== 0 ? lastSpot / firstSpot - 1 : null

    result.set(symbol, {
      printCount: rows.length,
      spot: lastSpot,
      windowMove,
      topStrike: topKey(strikePremium),
      topExpiry: shortDate(topKey(expiryPremium) === 'Unavailable' ? null : topKey(expiryPremium)),
      topDteBucket: topKey(dtePremium),
      signedNet,
      signedGross,
      signedPrints,
    })
  }
  return result
})

function tapeStats(symbol: string): TapeStats | null {
  return tapeStatsBySymbol.value.get(symbol) ?? null
}

function strongModelContext(context: ModelContext | null): boolean {
  if (!context || context.probability == null) return false
  const side = context.side.toLowerCase()
  const calibrated = context.confidenceKind === 'calibrated_probability'
  const actionableState = context.state === 'ENTER'
  return (
    calibrated &&
    context.setupOk === true &&
    actionableState &&
    (side === 'long' || side === 'short') &&
    context.probability >= 0.55
  )
}

function directionRead(symbol: string): DirectionRead {
  const stats = tapeStats(symbol)
  const context = signalBySymbol.value.get(symbol) ?? null
  const hasSignedFlow = !!stats && stats.signedPrints > 0 && stats.signedGross > 0
  const modelStrong = strongModelContext(context)
  const modelBullish = context?.side.toLowerCase() === 'long'
  const boardRow = rowBySymbol.value.get(symbol) ?? null

  if (hasSignedFlow && stats) {
    const balance = Math.abs(stats.signedNet) / stats.signedGross
    if (balance < 0.2) {
      return {
        state: 'mixed',
        label: 'MIXED SIGNED FLOW',
        detail: `${stats.signedPrints} signed prints offset each other`,
      }
    }
    const bullish = stats.signedNet > 0
    if (modelStrong && bullish !== modelBullish) {
      return {
        state: 'mixed',
        label: 'EVIDENCE CONFLICT',
        detail: `Provider-signed flow and ${fractionPercent(context?.probability, 0)} model disagree`,
      }
    }
    return {
      state: bullish ? 'bullish' : 'bearish',
      label: bullish ? 'BULLISH SIGNED FLOW' : 'BEARISH SIGNED FLOW',
      detail: `${stats.signedPrints} provider-signed prints${modelStrong ? ' · model confirms' : ''}`,
    }
  }

  // Prefer backend activity lean (premium + price + model) when unsigned.
  const lean = String(boardRow?.activity_lean || '').toLowerCase()
  if (lean === 'bullish' || lean === 'bearish' || lean === 'mixed') {
    const source = String(boardRow?.activity_lean_source || 'activity').replaceAll('_', ' ')
    return {
      state: lean === 'mixed' ? 'mixed' : lean,
      label: lean === 'mixed' ? 'MIXED ACTIVITY' : `${lean.toUpperCase()} ACTIVITY`,
      detail: `Activity lean · ${source}${modelStrong ? ' · model also available' : ''}`,
    }
  }

  // Local fallback from premium mix so the card always states bullish/bearish.
  if (boardRow) {
    const putShareVal = finite(boardRow.put_flow_pct)
    const imb = finite(boardRow.call_put_imbalance)
    const callHeavy = (imb != null && imb >= 0.15) || (putShareVal != null && putShareVal <= 0.42)
    const putHeavy = (imb != null && imb <= -0.15) || (putShareVal != null && putShareVal >= 0.58)
    if (callHeavy || putHeavy) {
      const bullish = !!callHeavy && !putHeavy
      return {
        state: bullish ? 'bullish' : 'bearish',
        label: bullish ? 'BULLISH ACTIVITY' : 'BEARISH ACTIVITY',
        detail: bullish
          ? 'Call-heavy premium mix · activity lean, not signed trade direction'
          : 'Put-heavy premium mix · activity lean, not signed trade direction',
      }
    }
  }

  if (modelStrong && context) {
    return {
      state: modelBullish ? 'model-bullish' : 'model-bearish',
      label: modelBullish ? 'BULLISH · MODEL LEAN' : 'BEARISH · MODEL LEAN',
      detail: `${fractionPercent(context.probability, 0)} calibrated · flow itself is unsigned`,
    }
  }

  if (context?.probability != null) {
    return {
      state: 'unknown',
      label: 'NEUTRAL ACTIVITY',
      detail: `${context.state} ${context.side} at ${fractionPercent(context.probability, 0)} does not clear the evidence gate`,
    }
  }

  return {
    state: 'unknown',
    label: 'NEUTRAL ACTIVITY',
    detail: 'No clear bullish/bearish lean in premium mix, price impulse, or signed flow',
  }
}

function priceRead(row: UnusualFlowRow): PriceRead {
  const dayReturn = finite(row.ret_1d)
  const stats = tapeStats(row.symbol)
  const spot = stats?.spot
  const fallbackMove = stats?.windowMove

  if (dayReturn != null) {
    return {
      spot: spot != null ? usd(spot, 2) : 'SPOT UNAVAILABLE',
      move: returnPercent(dayReturn),
      detail: spot != null ? '1D move · tape spot' : '1D move · spot unavailable',
      tone: tone(dayReturn),
    }
  }
  if (spot != null) {
    return {
      spot: usd(spot, 2),
      move: fallbackMove == null ? 'MOVE UNAVAILABLE' : returnPercent(fallbackMove),
      detail:
        fallbackMove == null
          ? 'Tape spot · no return series'
          : 'Move within latest provider sample',
      tone: fallbackMove == null ? 'flat' : tone(fallbackMove),
    }
  }
  return {
    spot: 'SPOT UNAVAILABLE',
    move: 'MOVE UNAVAILABLE',
    detail: 'No underlying price in this provider sample',
    tone: 'flat',
  }
}

function evidenceFor(row: UnusualFlowRow): EvidenceTag[] {
  const tags: EvidenceTag[] = []
  const premium = finite(row.premium) ?? 0
  const dte = finite(row.average_dte)
  const otm = finite(row.average_otm_pct)
  const ret = finite(row.ret_1d)
  const sweeps = finite(row.sweep_count) ?? 0
  const flagged = finite(row.unusual_contracts) ?? 0

  if (symbolPulse(row.symbol).newPrints > 0) {
    tags.push({ label: `${symbolPulse(row.symbol).newPrints} new now`, kind: 'size' })
  }
  if (premium / maxPremium.value >= 0.5) tags.push({ label: 'Top premium', kind: 'size' })
  if (sweeps > 0) {
    tags.push({
      label: sweepShare(row) >= 0.15 ? 'Sweep-heavy' : `${exactCount(sweeps)} sweeps`,
      kind: 'sweep',
    })
  }
  if (flagged > 0) {
    tags.push({
      label:
        flaggedShare(row) > 0
          ? `Flagged ${fractionPercent(flaggedShare(row), 0)}`
          : 'Flagged prints',
      kind: 'flag',
    })
  }
  if (dte != null && dte <= 7) tags.push({ label: '≤7D expiry', kind: 'structure' })
  if (otm != null && otm >= 0.05) tags.push({ label: 'Far OTM', kind: 'structure' })
  if (ret != null && Math.abs(ret) >= 0.03) tags.push({ label: 'Large 1D move', kind: 'move' })
  if (!tags.length) tags.push({ label: 'Premium threshold', kind: 'base' })
  return tags.slice(0, 3)
}

function primaryReadout(row: UnusualFlowRow): string {
  if (sweepShare(row) >= 0.15) {
    return `${fractionPercent(sweepShare(row), 0)} of premium is sweep-class activity`
  }
  if (flaggedShare(row) >= 0.15) {
    return `${fractionPercent(flaggedShare(row), 0)} of contracts carry a current-tape heuristic flag`
  }
  const dte = finite(row.average_dte)
  if (dte != null && dte <= 7) {
    return `${moneyCompact(row.premium)} with ${num(dte, 1)}D average expiry`
  }
  return `${moneyCompact(row.premium)} across ${exactCount(row.contract_count)} contracts`
}

function actionInsight(row: UnusualFlowRow): ActionInsight {
  const direction = directionRead(row.symbol)
  const stats = tapeStats(row.symbol)
  const pulseRow = symbolPulse(row.symbol)
  const dte = finite(row.average_dte)
  const nearExpiry = dte != null && dte <= 7
  const sweeps = sweepShare(row) >= 0.15 || (finite(row.sweep_count) ?? 0) > 0
  const incoming = pulseRow.newPrints > 0
  const strike = stats?.topStrike && stats.topStrike !== 'Unavailable' ? stats.topStrike : null
  const dteZone =
    stats?.topDteBucket && stats.topDteBucket !== 'Unavailable'
      ? stats.topDteBucket
      : nearExpiry
        ? '0–7D'
        : dte != null
          ? `${num(dte, 0)}D avg`
          : null

  const focusParts = [
    strike ? `top ${strike}` : null,
    dteZone ? dteZone : null,
    sweeps ? 'sweep cluster' : null,
  ].filter(Boolean)
  const focus = focusParts.length ? focusParts.join(' · ') : 'full chain for walls + liquidity'

  let priority: ActionInsight['priority'] = 'watch'
  if (providerFreshnessState.value === 'stale') {
    priority = 'skip'
  } else if (
    incoming ||
    nearExpiry ||
    sweeps ||
    direction.state.includes('bullish') ||
    direction.state.includes('bearish')
  ) {
    priority = incoming || nearExpiry ? 'now' : 'soon'
  } else if (direction.state === 'mixed' || direction.state === 'unknown') {
    priority = 'watch'
  }

  let action: string
  if (priority === 'skip') {
    action = 'Refresh feed before chain work — provider sample is stale'
  } else if (direction.state === 'mixed') {
    action = 'Build setup · reconcile conflicting lean vs model before size'
  } else if (direction.state.includes('bullish')) {
    action = nearExpiry
      ? 'Build setup · map near-dated call strikes + upside walls'
      : 'Build setup · confirm call side liquidity and call wall'
  } else if (direction.state.includes('bearish')) {
    action = nearExpiry
      ? 'Build setup · map near-dated put strikes + downside walls'
      : 'Build setup · confirm put side liquidity and put wall'
  } else if (incoming) {
    action = 'Build setup · new prints just landed; read structure first'
  } else {
    action = 'Park for later · no clear lean; keep in review queue'
  }

  return {
    lean: direction.label,
    leanState: direction.state,
    priority,
    action,
    focus,
    why: primaryReadout(row),
  }
}

const majorRows = computed(() => {
  const bySymbol = new Map(qualifiedRows.value.map((row) => [row.symbol, row]))
  return MAJOR_SYMBOLS.map((symbol) => ({ symbol, row: bySymbol.get(symbol) ?? null }))
})

const aggressorCoverage = computed(() => finite(baseSummary.value?.signed_print_pct))

const pollSeconds = computed(() => Math.max(1, Math.round(props.pollMs / 1_000)))

const rankMoveCount = computed(
  () =>
    [...pulse.value.bySymbol.values()].filter((row) => row.rankMove != null && row.rankMove !== 0)
      .length,
)

const topIncoming = computed(
  () =>
    [...pulse.value.bySymbol.entries()]
      .filter(([, row]) => row.newPremium > 0)
      .sort((a, b) => b[1].newPremium - a[1].newPremium)[0] ?? null,
)

const pulseState = computed(() => {
  if (pulse.value.baseline) return { label: 'BASELINE SET', state: 'baseline' }
  if (pulse.value.newPrintCount > 0)
    return { label: `${pulse.value.newPrintCount} NEW PRINTS`, state: 'active' }
  if (!pulse.value.asofAdvanced) return { label: 'SAMPLE UNCHANGED', state: 'quiet' }
  return { label: 'NO NEW QUALIFIED PRINTS', state: 'quiet' }
})

const pulseNarrative = computed(() => {
  if (pulse.value.baseline) {
    return 'The next fresh provider sample will show new prints, premium rotation, and rank movement automatically.'
  }
  if (topIncoming.value) {
    return `${topIncoming.value[0]} leads incoming activity with ${moneyCompact(topIncoming.value[1].newPremium)} across ${topIncoming.value[1].newPrints} new prints.`
  }
  if (!pulse.value.asofAdvanced) {
    return 'The provider returned the same newest print. Rankings remain stable; no activity is being invented.'
  }
  return 'The provider sample advanced, but no newly retained prints cleared this local view.'
})

const leanTally = computed(() => {
  let bullish = 0
  let bearish = 0
  let mixed = 0
  let neutral = 0
  for (const row of qualifiedRows.value.slice(0, 24)) {
    const state = directionRead(row.symbol).state
    if (state.includes('bullish')) bullish += 1
    else if (state.includes('bearish')) bearish += 1
    else if (state === 'mixed') mixed += 1
    else neutral += 1
  }
  return { bullish, bearish, mixed, neutral, n: bullish + bearish + mixed + neutral }
})

const marketActionHeadline = computed(() => {
  const tally = leanTally.value
  if (!tally.n) return 'No qualified names above threshold'
  if (tally.bullish >= tally.bearish + 2 && tally.bullish >= 3) {
    return `Bullish activity lean leads the top tape (${tally.bullish}/${tally.n})`
  }
  if (tally.bearish >= tally.bullish + 2 && tally.bearish >= 3) {
    return `Bearish activity lean leads the top tape (${tally.bearish}/${tally.n})`
  }
  if (tally.mixed >= 3) {
    return `Mixed / conflicting leans dominate — prioritize evidence reconciliation`
  }
  return `Split tape · ${tally.bullish} bullish · ${tally.bearish} bearish · ${tally.mixed} mixed`
})

const topActionNames = computed(() => {
  const scored = qualifiedRows.value.map((row) => {
    const insight = actionInsight(row)
    const rank =
      insight.priority === 'now'
        ? 3
        : insight.priority === 'soon'
          ? 2
          : insight.priority === 'watch'
            ? 1
            : 0
    return { symbol: row.symbol, insight, rank, premium: finite(row.premium) ?? 0 }
  })
  return scored
    .filter((row) => row.rank >= 2)
    .sort((a, b) => b.rank - a.rank || b.premium - a.premium)
    .slice(0, 3)
})

const workspaceBrief = computed(() => {
  const leadNames = topActionNames.value.map((row) => row.symbol)
  const leadCopy = leadNames.length
    ? `Next: open ${leadNames.join(', ')} chain${leadNames.length === 1 ? '' : 's'} — confirm walls, liquidity, and signed side before any size.`
    : 'Next: scan the three review leads below, then open one chain only after lean + concentration agree.'

  if (providerFreshnessState.value === 'stale') {
    return {
      tone: 'stale',
      eyebrow: 'Stale provider sample',
      title: 'Context only — refresh before using this tape intraday',
      body: `The newest provider observation is ${providerFreshness.value} old. ${marketActionHeadline.value}. Do not treat these ranks as live entry signals.`,
    }
  }
  if (pulse.value.newPrintCount > 0) {
    return {
      tone: 'active',
      eyebrow: 'Actionable desk brief',
      title: marketActionHeadline.value,
      body: `${pulseNarrative.value} ${leadCopy}`,
    }
  }
  if (pulse.value.baseline) {
    return {
      tone: 'baseline',
      eyebrow: 'Actionable desk brief',
      title: marketActionHeadline.value,
      body: `Baseline sample set. ${leadCopy} Rank moves appear after the next distinct provider sample.`,
    }
  }
  return {
    tone: 'quiet',
    eyebrow: 'Actionable desk brief',
    title: marketActionHeadline.value,
    body: `${pulseNarrative.value} ${leadCopy}`,
  }
})

const triagePicks = computed<TriagePick[]>(() => {
  if (!filteredRows.value.length) return []
  const byReview = filteredRows.value[0]
  const bySweep = [...filteredRows.value].sort(
    (a, b) => (finite(b.sweep_premium) ?? 0) - (finite(a.sweep_premium) ?? 0),
  )[0]
  const byExpiry = [...filteredRows.value]
    .filter((row) => finite(row.average_dte) != null)
    .sort((a, b) => (finite(a.average_dte) ?? Infinity) - (finite(b.average_dte) ?? Infinity))[0]
  const byAction = topActionNames.value[0]
    ? filteredRows.value.find((row) => row.symbol === topActionNames.value[0].symbol)
    : undefined
  const specs: Array<{ key: string; eyebrow: string; row: UnusualFlowRow | undefined }> = [
    {
      key: 'review',
      eyebrow: pulse.value.newPrintCount > 0 ? 'Open first · incoming' : 'Open first · review lead',
      row: byAction ?? byReview,
    },
    { key: 'sweeps', eyebrow: 'Open · largest sweep cluster', row: bySweep },
    { key: 'expiry', eyebrow: 'Open · shortest duration', row: byExpiry },
  ]
  const used = new Set<string>()
  const picks: TriagePick[] = []

  for (const spec of specs) {
    let row = spec.row
    if (!row || used.has(row.symbol)) {
      row = filteredRows.value.find((candidate) => !used.has(candidate.symbol))
    }
    if (!row) continue
    used.add(row.symbol)
    const insight = actionInsight(row)
    picks.push({
      key: spec.key,
      eyebrow: spec.eyebrow,
      symbol: row.symbol,
      value: moneyCompact(row.premium),
      detail: insight.action,
      lean: insight.lean,
      leanState: insight.leanState,
      action: insight.focus,
      tags: evidenceFor(row).slice(0, 2),
    })
  }
  return picks
})

const directionPolicy = computed(() => {
  const coverage = aggressorCoverage.value
  if (coverage == null) return 'SIDE COVERAGE UNKNOWN · NO DIRECTION CLAIMED'
  if (coverage < 0.25) return `UNSIGNED TAPE · ${fractionPercent(coverage, 0)} SIDE COVERAGE`
  return `${fractionPercent(coverage, 0)} PROVIDER-SIGNED COVERAGE`
})

const activeFilterCount = computed(
  () =>
    Number(symbolQuery.value.trim().length > 0) +
    Number(exclusions.value.length > 0) +
    Number(activityFilter.value !== 'all') +
    Number(tapePreset.value !== 'all') +
    Number(selectedSector.value !== 'all') +
    Number(rightFilter.value !== 'all') +
    Number(dteFilter.value !== 'all') +
    Number(moneynessFilter.value !== 'all') +
    Number(reviewSortKey.value !== 'review'),
)

const topTickerRows = computed(
  () => props.payload?.top_tickers?.categories?.[topTickerCategory.value] ?? [],
)

const bookHits = computed(() =>
  qualifiedRows.value.filter((row) => watchlistHas(book.value, row.symbol)),
)

function onBook(symbol: string): boolean {
  return watchlistHas(book.value, symbol)
}

function toggleBook(symbol: string): void {
  book.value = toggleWatchlistSymbol(book.value, symbol).symbols
}

watch([() => props.payload, pulse, book], () => {
  const tape = props.payload?.tape ?? []
  const incoming = collectWatchlistAlerts({
    watchlist: book.value,
    prints: tape,
    seenKeys: seenAlertKeys.value,
    newPrintKeys: pulse.value.baseline ? [] : pulse.value.newPrintKeys,
  })
  if (!incoming.length) return
  bookAlerts.value = [...incoming, ...bookAlerts.value].slice(0, 20)
  const nextSeen = new Set(seenAlertKeys.value)
  for (const alert of incoming) nextSeen.add(alert.key)
  seenAlertKeys.value = nextSeen
  saveSeenAlertKeys(nextSeen)
  saveUnreadAlertCount(bookAlerts.value.length)
})

function dismissAlerts(): void {
  bookAlerts.value = []
  saveUnreadAlertCount(0)
}

async function loadHistoryTape(): Promise<void> {
  const symbol = historySymbol.value.trim().toUpperCase()
  if (!symbol) {
    historyError.value = 'Enter a symbol'
    return
  }
  historyLoading.value = true
  historyError.value = null
  try {
    const payload = await api.flowTape({
      symbol,
      from: historyFrom.value || undefined,
      to: historyTo.value || undefined,
      minPremium: props.minPremium,
    })
    historyTape.value = payload.tape ?? []
    historyMeta.value = `${payload.symbol} · ${payload.print_count} prints · ${payload.feed_status}`
    if (payload.warnings?.length) historyError.value = payload.warnings.join(' · ')
  } catch (err) {
    historyError.value = err instanceof Error ? err.message : 'History tape unavailable'
    historyTape.value = []
  } finally {
    historyLoading.value = false
  }
}

const reviewMeta = computed(
  () =>
    `SHOWING ${reviewRows.value.length} OF ${filteredRows.value.length} · ≥ $${compact(props.minPremium)}`,
)

const tapeMeta = computed(() => {
  if (baseSummary.value?.tape_detail_available === false)
    return 'DETAIL UNAVAILABLE · AGGREGATE SNAPSHOT'
  return `${tapeRows.value.length}/${qualifiedTapeRows.value.length} MATCHING PRINTS · MAX ${MAX_TAPE_ROWS}`
})

function clearFilters(): void {
  symbolQuery.value = ''
  activityFilter.value = 'all'
  tapePreset.value = 'all'
  selectedSector.value = 'all'
  rightFilter.value = 'all'
  dteFilter.value = 'all'
  moneynessFilter.value = 'all'
  sortKey.value = 'review'
  reviewSortKey.value = 'review'
  reviewSortDir.value = 'desc'
  tapeSortKey.value = 'time'
  tapeSortDir.value = 'desc'
}

function unpinExclusion(raw: string): void {
  const symbol = normalizeWatchSymbol(raw)
  exclusions.value = saveExclusions(exclusions.value.filter((item) => item !== symbol))
}

function applyLayout(layout: FlowFilterLayout): void {
  const presets = new Set(TAPE_PRESETS.map((item) => item.id))
  tapePreset.value = presets.has(layout.tapePreset as TapePreset)
    ? (layout.tapePreset as TapePreset)
    : 'all'
  activityFilter.value = (
    ['all', 'incoming', 'sweeps', 'flagged', 'near'] as ActivityFilter[]
  ).includes(layout.activityFilter as ActivityFilter)
    ? (layout.activityFilter as ActivityFilter)
    : 'all'
  rightFilter.value = (['all', 'call', 'put'] as RightFilter[]).includes(
    layout.rightFilter as RightFilter,
  )
    ? (layout.rightFilter as RightFilter)
    : 'all'
  dteFilter.value = (['all', 'week', 'month', 'dated'] as DteFilter[]).includes(
    layout.dteFilter as DteFilter,
  )
    ? (layout.dteFilter as DteFilter)
    : 'all'
  moneynessFilter.value = (['all', 'otm', 'atm', 'itm'] as MoneynessFilter[]).includes(
    layout.moneynessFilter as MoneynessFilter,
  )
    ? (layout.moneynessFilter as MoneynessFilter)
    : 'all'
  selectedSector.value = layout.selectedSector || 'all'
  symbolQuery.value = layout.symbolQuery
  emit('threshold', layout.minPremium)
}

function dropLayout(id: string): void {
  layouts.value = removeFlowLayout(layouts.value, id)
}

/** Premium-based put share; never invent 100% put when the field is missing. */
function putShare(row: UnusualFlowRow): number | null {
  const direct = finite(row.put_flow_pct)
  if (direct != null) return clamp01(direct)
  const callP = finite(row.call_premium)
  const putP = finite(row.put_premium)
  if (callP == null && putP == null) return null
  const total = (callP ?? 0) + (putP ?? 0)
  return total > 0 ? clamp01((putP ?? 0) / total) : null
}

function callShare(row: UnusualFlowRow): number | null {
  const put = putShare(row)
  return put == null ? null : 1 - put
}

function putShareLabel(row: UnusualFlowRow): string {
  return mixShareLabel(putShare(row), fractionPercent(putShare(row), 0))
}

function callShareLabel(row: UnusualFlowRow): string {
  return mixShareLabel(callShare(row), fractionPercent(callShare(row), 0))
}

function symbolPulseCopy(symbol: string): string {
  if (pulse.value.baseline) return FIRST_WINDOW_BASELINE
  const row = symbolPulse(symbol)
  return pulseWindowCopy({
    baseline: false,
    newPrints: row.newPrints,
    newPremiumLabel: `+${moneyCompact(row.newPremium)}`,
    windowDeltaLabel: signedMoneyCompact(row.windowPremiumDelta),
  })
}

function putBarWidth(row: UnusualFlowRow): string {
  const share = putShare(row)
  return `${share == null ? 0 : share * 100}%`
}

function callBarWidth(row: UnusualFlowRow): string {
  const share = callShare(row)
  return `${share == null ? 0 : share * 100}%`
}

function tapeTime(timestamp: string): string {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return timestamp || DASH
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  })
}

function aggressorLabel(row: MarketFlowPrint): string {
  if (row.aggressor_label) return row.aggressor_label.toUpperCase()
  if (row.aggressor) return row.aggressor.toUpperCase()
  return 'NO SIDE'
}

function heuristicClass(row: MarketFlowPrint): boolean {
  return row.trade_class_source === 'size_heuristic' || row.trade_class_source === 'burst_heuristic'
}

function tradeClassTitle(row: MarketFlowPrint): string {
  const source = row.trade_class_source?.replaceAll('_', ' ') ?? 'source unavailable'
  return heuristicClass(row)
    ? `${row.trade_class ?? 'unclassified'} · EDGE heuristic (${source})`
    : `${row.trade_class ?? 'unclassified'} · ${source}`
}

function heatClass(value: unknown): string {
  const percentile = finite(value)
  if (percentile != null && percentile >= 0.9) return 'hot'
  if (percentile != null && percentile >= 0.75) return 'warm'
  return 'quiet'
}

function heatWidth(value: unknown): string {
  const percentile = finite(value)
  return `${percentile == null ? 0 : clamp01(percentile) * 100}%`
}

function openSymbol(symbol: string | null | undefined): void {
  if (!symbol) return
  const clean = symbol.trim().toUpperCase()
  historySymbol.value = clean
  symbolQuery.value = clean
  emit('openSymbol', clean)
}

function clearActiveSymbol(): void {
  symbolQuery.value = ''
  emit('openSymbol', '')
}

type CsvCell = string | number | boolean | null | undefined

function csvCell(value: CsvCell): string {
  if (value === null || value === undefined) return ''
  const rendered = String(value)
  return /[",\n\r]/.test(rendered) ? `"${rendered.replaceAll('"', '""')}"` : rendered
}

function downloadCsv(filename: string, headers: string[], rows: CsvCell[][]): void {
  if (typeof document === 'undefined' || typeof URL === 'undefined') return
  const csv = [headers, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function fileStamp(): string {
  return String(props.payload?.asof ?? new Date().toISOString())
    .slice(0, 10)
    .replaceAll(/[^0-9-]/g, '')
}

function downloadAggregateCsv(): void {
  downloadCsv(
    `edge-flow-review-${fileStamp()}.csv`,
    [
      'review_rank',
      'symbol',
      'premium_usd',
      'contract_count',
      'put_premium_share_fraction',
      'average_dte_days',
      'average_otm_distance_fraction',
      'return_1d_fraction',
      'unusual_contracts',
      'sweep_count',
      'sweep_premium_usd',
      'review_reasons',
    ],
    filteredRows.value.map((row, index) => [
      index + 1,
      row.symbol,
      row.premium,
      row.contract_count,
      row.put_flow_pct,
      row.average_dte,
      row.average_otm_pct,
      row.ret_1d,
      row.unusual_contracts,
      row.sweep_count,
      row.sweep_premium,
      evidenceFor(row)
        .map((tag) => tag.label)
        .join(' | '),
    ]),
  )
}

function downloadTapeCsv(): void {
  downloadCsv(
    `edge-flow-tape-${fileStamp()}.csv`,
    [
      'timestamp_utc',
      'symbol',
      'right_contract_identity',
      'aggressor',
      'expiry',
      'underlying_spot_usd',
      'strike_usd',
      'otm_distance_fraction',
      'price_usd_per_contract',
      'contracts',
      'open_interest',
      'implied_volatility_raw',
      'trade_class',
      'trade_class_source',
      'premium_usd',
      'premium_percentile_fraction',
    ],
    qualifiedTapeRows.value.map((row) => [
      row.timestamp,
      row.symbol,
      row.right,
      aggressorLabel(row),
      row.expiry,
      row.underlying_price,
      row.strike,
      row.otm_pct,
      row.price,
      row.contracts ?? row.volume,
      row.open_interest,
      row.implied_volatility,
      row.trade_class,
      row.trade_class_source,
      row.premium,
      row.premium_percentile,
    ]),
  )
}

function downloadHistoryTapeCsv(): void {
  if (!historyTape.value.length) return
  downloadCsv(
    `edge-history-tape-${historySymbol.value || 'SYMBOL'}-${fileStamp()}.csv`,
    [
      'timestamp_utc',
      'symbol',
      'right',
      'strike',
      'expiry',
      'dte',
      'premium_usd',
      'contracts',
      'fill_price_usd',
      'underlying_spot_usd',
      'otm_pct',
      'open_interest',
      'implied_volatility',
      'aggressor',
      'bias',
      'trade_class',
      'anomaly_flags',
    ],
    historyTape.value.map((row) => [
      row.timestamp,
      row.symbol || historySymbol.value,
      row.right,
      row.strike,
      row.expiry,
      row.dte,
      row.premium,
      row.contracts ?? row.volume,
      row.price,
      row.underlying_price,
      row.otm_pct,
      row.open_interest,
      row.implied_volatility,
      aggressorLabel(row),
      row.bias,
      row.trade_class,
      (row.anomaly_flags || []).join(';'),
    ]),
  )
}
</script>

<template>
  <section class="flow-dashboard" aria-label="Live options flow review workspace">
    <header class="control-rail ticked rise">
      <div class="control-identity">
        <span
          class="feed-mark"
          :class="{ active: providerFreshnessState === 'live' && !loading }"
          aria-hidden="true"
        >
          <AppIcon name="flow" :size="17" />
        </span>
        <div>
          <span class="label">Latest provider sample</span>
          <strong class="fig">{{ sourceLabel }}</strong>
          <small>Returned contracts in one provider poll · not total market volume</small>
        </div>
      </div>

      <div class="threshold-control">
        <span class="label">Minimum sample premium</span>
        <div class="thresholds" aria-label="Minimum aggregate options premium">
          <button
            v-for="value in THRESHOLDS"
            :key="value"
            type="button"
            :aria-pressed="minPremium === value"
            :class="{ active: minPremium === value }"
            @click="emit('threshold', value)"
          >
            ${{ compact(value) }}+
          </button>
        </div>
      </div>

      <div class="control-status label" aria-live="polite">
        <span>
          {{
            contractMismatch ? 'BACKEND UPDATE REQUIRED' : `${feedStatusLabel} · ${feedWindowLabel}`
          }}
        </span>
        <span>{{
          payload ? `PROVIDER ${providerFreshness} · SNAPSHOT ${snapshotFreshness}` : 'NO SNAPSHOT'
        }}</span>
      </div>

      <button
        class="refresh-button label"
        type="button"
        :disabled="loading"
        @click="emit('refresh')"
      >
        <AppIcon name="flow" :size="15" />
        {{ loading ? 'PULLING' : 'REFRESH' }}
      </button>
    </header>

    <p v-if="error" class="error-strip" role="alert">
      <strong class="label">Flow feed error</strong>
      <span>{{ error }}</span>
      <span v-if="payload" class="label stale-copy">LAST SUCCESSFUL SNAPSHOT REMAINS VISIBLE</span>
    </p>

    <LoadingState v-if="loading && !payload" label="Scanning market options flow" />

    <div v-else-if="contractMismatch" class="feed-recovery ticked" role="alert">
      <span class="recovery-mark label">API</span>
      <div>
        <span class="label">Legacy Flow response blocked</span>
        <strong>The running backend is older than this workspace.</strong>
        <p>
          Restart the local API, then refresh this feed. Obsolete Deep-scan data is not substituted
          here.
        </p>
      </div>
      <button type="button" class="empty-action label" :disabled="loading" @click="emit('refresh')">
        {{ loading ? 'CHECKING' : 'CHECK AGAIN' }}
      </button>
    </div>

    <div v-else-if="!payload" class="no-snapshot ticked">
      <AppIcon name="flow" :size="24" />
      <strong>No flow snapshot is available.</strong>
      <p>Pull the provider feed to build a review queue from measured ticker aggregates.</p>
      <button type="button" class="empty-action label" @click="emit('refresh')">
        PULL FLOW DATA
      </button>
    </div>

    <div v-else-if="!hasMeasuredFlow" class="feed-recovery empty-feed ticked" role="status">
      <span class="recovery-mark label">0×</span>
      <div>
        <span class="label">No measured prints in the latest provider sample</span>
        <strong>The provider returned no contracts above ${{ compact(minPremium) }}.</strong>
        <p>
          {{
            payload.feed_reason ||
            payload.warnings?.[0] ||
            'Try a lower threshold or request a fresh market-wide provider sample.'
          }}
        </p>
      </div>
      <button type="button" class="empty-action label" :disabled="loading" @click="emit('refresh')">
        {{ loading ? 'PULLING' : 'REFRESH FEED' }}
      </button>
    </div>

    <template v-else>
      <!-- Hero Sentiment & Snapshot Section (Matching Reference Header Card) -->
      <section class="flow-sentiment-hero rise" aria-label="Current threshold snapshot">
        <div class="sentiment-card" :class="activeTickerStats.dominantState">
          <div class="sentiment-top">
            <div class="ticker-header-identity">
              <span class="ticker-symbol-badge">{{ activeTickerStats.symbol }}</span>
              <div class="ticker-title-box">
                <div class="ticker-symbol-line">
                  <strong class="ticker-symbol-text fig">{{ activeTickerStats.symbol }}</strong>
                  <span class="ticker-company-name label">{{ activeTickerStats.companyName }}</span>
                  <button
                    v-if="symbolQuery"
                    type="button"
                    class="clear-symbol-btn label"
                    title="Clear ticker focus"
                    @click="clearActiveSymbol"
                  >
                    RESET FOCUS ×
                  </button>
                </div>
                <div class="ticker-quote-line fig">
                  <span class="ticker-quote-price">{{ activeTickerStats.spot }}</span>
                  <span class="ticker-quote-delta" :class="activeTickerStats.moveTone">{{
                    activeTickerStats.move
                  }}</span>
                  <span class="ticker-quote-range label"
                    >Day Low {{ activeTickerStats.dayLow }} · Day High
                    {{ activeTickerStats.dayHigh }} · Vol: {{ activeTickerStats.vol }}</span
                  >
                </div>
              </div>
            </div>

            <span class="dominant-badge label" :class="activeTickerStats.dominantState">
              <i class="dominant-pulse-dot" aria-hidden="true" />
              {{ activeTickerStats.dominantLabel }}
            </span>
          </div>

          <div class="sentiment-headline">
            <strong class="sentiment-title fig">{{ marketFlowSentiment.label }}</strong>
            <span class="sentiment-premium fig">
              <b class="call-text"
                >{{ moneyCompact(activeTickerStats.callPremium) }} Call Premium</b
              >
              · <b class="put-text">{{ moneyCompact(activeTickerStats.putPremium) }} Put Premium</b>
            </span>
          </div>
          <div class="sentiment-bar" aria-label="Call vs Put flow split">
            <i class="call-segment" :style="{ width: `${activeTickerStats.callPct}%` }" />
            <i class="put-segment" :style="{ width: `${activeTickerStats.putPct}%` }" />
          </div>
          <div class="sentiment-labels fig">
            <span class="call-text"
              >CALLS {{ moneyCompact(activeTickerStats.callPremium) }} ({{
                activeTickerStats.callPct
              }}%)</span
            >
            <span class="put-text"
              >PUTS {{ moneyCompact(activeTickerStats.putPremium) }} ({{
                activeTickerStats.putPct
              }}%)</span
            >
          </div>
        </div>

        <div class="snapshot-metrics">
          <article>
            <span class="label">Premium</span>
            <strong class="fig">{{ moneyCompact(projectedSummary.totalPremium) }}</strong>
            <small>{{ qualifiedRows.length }} tickers above threshold</small>
          </article>
          <article>
            <span class="label">Contracts</span>
            <strong class="fig">{{ compact(projectedSummary.totalContracts) }}</strong>
            <small
              >{{ exactCount(projectedSummary.anomalyContracts) }} flagged in current tape</small
            >
          </article>
          <article>
            <span class="label">Sweeps</span>
            <strong class="fig">{{ moneyCompact(projectedSummary.sweepPremium) }}</strong>
            <small>{{ exactCount(projectedSummary.sweepContracts) }} contracts</small>
          </article>
          <article class="freshness-stat">
            <span class="label" title="Provider age">Age</span>
            <strong class="fig">{{ providerFreshness }}</strong>
            <small>{{ providerAsOfLabel }}</small>
            <span class="fresh-state label" :class="providerFreshnessState">{{
              providerFreshnessState.toUpperCase()
            }}</span>
          </article>
        </div>
      </section>

      <!-- Consolidated Market Flow Intelligence Hub -->
      <section class="market-intelligence-hub rise" aria-labelledby="intelligence-hub-title">
        <header class="intelligence-hub-head">
          <div class="hub-title-group">
            <span class="label section-kicker">Market Flow Intelligence</span>
            <h2 id="intelligence-hub-title">Market Breakdown &amp; Leaders</h2>
          </div>
          <div class="hub-tabs" role="tablist" aria-label="Market Flow Intelligence Sections">
            <button
              v-for="tab in OVERVIEW_TABS"
              :key="tab.id"
              type="button"
              role="tab"
              :aria-selected="overviewTab === tab.id"
              class="hub-tab-btn label"
              :class="{ active: overviewTab === tab.id }"
              @click="overviewTab = tab.id"
            >
              {{ tab.label }}
            </button>
          </div>
        </header>

        <!-- Tab 1: Top Tickers -->
        <div v-show="overviewTab === 'leaders'" class="hub-tab-panel">
          <section class="leaders-rail" aria-labelledby="top-tickers-title">
            <header class="leaders-head">
              <div>
                <span class="label section-kicker">Options-only leaders</span>
                <h2 id="top-tickers-title">
                  Top Tickers
                  <HelpTip
                    label="Top Tickers"
                    text="Leading market tickers categorized by institutional criteria: Unusual OTM volume, sweeps, high momentum, and premium size."
                    align="left"
                  />
                </h2>
              </div>
              <p class="book-hits-copy">
                <span id="book-hits-title">Watchlist hits on this tape</span>
                · {{ book.length }} pinned · {{ bookHits.length }} printed
              </p>
            </header>
            <div class="ticker-cats" role="tablist" aria-label="Top Tickers categories">
              <button
                v-for="category in TOP_TICKER_CATEGORIES"
                :key="category.id"
                type="button"
                role="tab"
                :class="{ active: topTickerCategory === category.id }"
                @click="topTickerCategory = category.id"
              >
                {{ category.label }}
              </button>
            </div>
            <div v-if="topTickerRows.length" class="symbol-tape">
              <button
                v-for="(row, index) in topTickerRows.slice(0, 10)"
                :key="`${topTickerCategory}-${row.symbol}`"
                type="button"
                class="sym-chip"
                :class="{ on: onBook(row.symbol) }"
                @click="openSymbol(row.symbol)"
              >
                <div class="sym-chip-head">
                  <span class="fig">{{ String(index + 1).padStart(2, '0') }} {{ row.symbol }}</span>
                  <strong class="fig">{{ tickerScore(row.score) }}</strong>
                </div>
                <div
                  v-if="row.bullish_share != null || row.bearish_share != null"
                  class="ticker-sentiment-bar"
                  aria-hidden="true"
                >
                  <i
                    class="bull-bar"
                    :style="{ width: `${Math.round((row.bullish_share ?? 0.5) * 100)}%` }"
                  />
                  <i
                    class="bear-bar"
                    :style="{ width: `${Math.round((row.bearish_share ?? 0.5) * 100)}%` }"
                  />
                </div>
                <div class="sym-chip-foot">
                  <small>
                    {{
                      row.bullish_share == null
                        ? 'No classified share'
                        : `${fractionPercent(row.bullish_share, 0)} / ${fractionPercent(row.bearish_share, 0)}`
                    }}
                  </small>
                  <span v-if="row.print_count" class="chip-count label"
                    >{{ exactCount(row.print_count) }} prints</span
                  >
                </div>
              </button>
            </div>
            <p v-else class="ticker-empty label">
              No names in this category for the latest provider sample.
            </p>
            <div v-if="bookHits.length" class="symbol-tape book-tape">
              <button
                v-for="row in bookHits.slice(0, 12)"
                :key="`book-${row.symbol}`"
                type="button"
                class="sym-chip book"
                @click="openSymbol(row.symbol)"
              >
                <div class="sym-chip-head">
                  <span class="fig">{{ row.symbol }}</span>
                  <strong class="fig">{{ moneyCompact(row.premium) }}</strong>
                </div>
                <div class="sym-chip-foot">
                  <small
                    >{{ exactCount(row.print_count) }} prints ·
                    {{ (row.unusual_contracts ?? 0) > 0 ? 'Unusual' : 'On tape' }}</small
                  >
                </div>
              </button>
            </div>
          </section>
        </div>

        <!-- Tab 2: Sector Sentiment -->
        <div v-show="overviewTab === 'sectors'" class="hub-tab-panel">
          <section class="sector-sentiment-rail" aria-labelledby="sector-sentiment-title">
            <header class="sector-head">
              <div>
                <span class="label section-kicker">Market breakdown</span>
                <h2 id="sector-sentiment-title">
                  Options Sector Sentiment
                  <HelpTip
                    label="Sector Sentiment"
                    text="Institutional options premium aggregated across major industry sectors. Click a sector card to filter the entire tape."
                    align="left"
                  />
                </h2>
              </div>
              <p class="sector-meta label">
                {{ sectorSentimentList.length }} active sectors ·
                <button
                  v-if="selectedSector !== 'all'"
                  type="button"
                  class="sector-clear-link"
                  @click="selectedSector = 'all'"
                >
                  CLEAR SECTOR FILTER ({{ selectedSector }})
                </button>
                <span v-else>Click a sector card to isolate flow</span>
              </p>
            </header>

            <div v-if="sectorSentimentList.length" class="sector-grid">
              <button
                v-for="sec in sectorSentimentList"
                :key="sec.sector"
                type="button"
                class="sector-card"
                :class="{ active: selectedSector === sec.sector }"
                @click="toggleSectorFilter(sec.sector)"
              >
                <div class="sector-card-top">
                  <strong class="sector-name">{{ sec.sector }}</strong>
                  <span class="sector-code label">{{ sec.code }}</span>
                </div>
                <div class="sector-premium fig">
                  {{ moneyCompact(sec.totalPremium) }}
                </div>
                <div class="sector-mix-bar" aria-hidden="true">
                  <i
                    class="call-segment"
                    :style="{ width: `${Math.round(sec.callShare * 100)}%` }"
                  />
                  <i class="put-segment" :style="{ width: `${Math.round(sec.putShare * 100)}%` }" />
                </div>
                <div class="sector-card-foot">
                  <span class="call-text fig">{{ Math.round(sec.callShare * 100) }}% C</span>
                  <span class="put-text fig">{{ Math.round(sec.putShare * 100) }}% P</span>
                  <span class="top-in-sec label">Top: {{ sec.topTicker }}</span>
                </div>
              </button>
            </div>
            <p v-else class="sector-empty label">
              No sector aggregation available in the latest sample.
            </p>
          </section>
        </div>

        <!-- Tab 3: Index Majors -->
        <div v-show="overviewTab === 'majors'" class="hub-tab-panel">
          <section class="majors-section" aria-labelledby="majors-title">
            <header class="majors-head">
              <div>
                <span class="label section-kicker">Index flow first</span>
                <h2 id="majors-title">
                  Where the major tape is concentrated
                  <HelpTip
                    label="Index Concentration"
                    text="Real-time order flow concentration across SPY, QQQ, IWM, and DIA index aggregates."
                    align="left"
                  />
                </h2>
              </div>
              <p>
                <strong class="label">{{ directionPolicy }}</strong
                ><br />
                Activity lean is descriptive; signed buy/sell and ENTER-state models upgrade
                evidence. Focus a symbol to combine walls, gates, and sizing.
              </p>
            </header>

            <div class="major-grid">
              <article
                v-for="major in majorRows"
                :key="major.symbol"
                class="major-card"
                :class="[
                  directionRead(major.symbol).state,
                  { incoming: symbolPulse(major.symbol).newPrints > 0, absent: !major.row },
                ]"
              >
                <template v-if="major.row">
                  <header class="major-symbol-line">
                    <button
                      type="button"
                      class="major-symbol fig"
                      @click="openSymbol(major.symbol)"
                    >
                      {{ major.symbol }}
                    </button>
                    <span v-if="symbolPulse(major.symbol).newPrints > 0" class="new-badge label"
                      >NEW</span
                    >
                    <span class="major-rank fig">REVIEW #{{ reviewRank(major.symbol) }}</span>
                    <span class="rank-move fig" :class="rankMoveClass(major.symbol)">{{
                      rankMoveLabel(major.symbol)
                    }}</span>
                  </header>

                  <div class="major-premium">
                    <div>
                      <span class="label">Sample premium</span>
                      <strong class="fig">{{ moneyCompact(major.row.premium) }}</strong>
                    </div>
                    <div>
                      <span class="label">{{
                        pulse.baseline ? 'First window' : 'Vs previous window'
                      }}</span>
                      <strong class="fig">{{
                        pulse.baseline
                          ? FIRST_WINDOW_BASELINE
                          : moneyCompact(symbolPulse(major.symbol).newPremium)
                      }}</strong>
                    </div>
                  </div>

                  <div
                    class="major-direction"
                    :class="[
                      directionRead(major.symbol).state,
                      flowLeanTokenClass(directionRead(major.symbol).state),
                    ]"
                  >
                    <span class="direction-arrow" aria-hidden="true">
                      {{
                        directionRead(major.symbol).state.includes('bullish')
                          ? '↑'
                          : directionRead(major.symbol).state.includes('bearish')
                            ? '↓'
                            : directionRead(major.symbol).state === 'mixed'
                              ? '↕'
                              : '·'
                      }}
                    </span>
                    <div>
                      <strong class="label">{{ directionRead(major.symbol).label }}</strong>
                      <small>{{ directionRead(major.symbol).detail }}</small>
                    </div>
                  </div>

                  <div class="major-identity">
                    <div class="identity-labels fig">
                      <span class="call-text">CALLS {{ callShareLabel(major.row) }}</span>
                      <span class="put-text">PUTS {{ putShareLabel(major.row) }}</span>
                    </div>
                    <span class="identity-bar" aria-hidden="true">
                      <i class="call-segment" :style="{ width: callBarWidth(major.row) }" />
                      <i class="put-segment" :style="{ width: putBarWidth(major.row) }" />
                    </span>
                    <small>Contract type only · not provider-signed buy / sell</small>
                  </div>

                  <dl class="major-concentration">
                    <div>
                      <dt class="label">Strike</dt>
                      <dd class="fig">
                        {{
                          concentrationLabel(tapeStats(major.symbol)?.topStrike, NO_STRIKE_IN_TAPE)
                        }}
                      </dd>
                    </div>
                    <div>
                      <dt class="label">DTE zone</dt>
                      <dd class="fig">
                        {{
                          concentrationLabel(
                            tapeStats(major.symbol)?.topDteBucket,
                            'NO DTE IN TAPE',
                          )
                        }}
                      </dd>
                    </div>
                    <div>
                      <dt class="label">Spot</dt>
                      <dd class="fig">{{ priceRead(major.row).spot }}</dd>
                      <small :class="priceRead(major.row).tone">{{
                        priceRead(major.row).move
                      }}</small>
                    </div>
                  </dl>
                  <p
                    class="major-action label"
                    :class="[
                      actionInsight(major.row).leanState,
                      flowLeanTokenClass(actionInsight(major.row).leanState),
                    ]"
                  >
                    <span>{{ actionInsight(major.row).priority.toUpperCase() }}</span>
                    {{ actionInsight(major.row).action }}
                  </p>
                  <button type="button" class="major-open label" @click="openSymbol(major.symbol)">
                    FILTER {{ major.symbol }} FLOW <span aria-hidden="true">→</span>
                  </button>
                </template>
                <template v-else>
                  <header class="major-symbol-line">
                    <strong class="major-symbol fig">{{ major.symbol }}</strong>
                  </header>
                  <div class="major-absent">
                    <strong>Not in the latest provider sample</strong>
                    <p>
                      No qualifying {{ major.symbol }} aggregate cleared ${{ compact(minPremium) }}.
                    </p>
                  </div>
                  <button type="button" class="major-open label" @click="openSymbol(major.symbol)">
                    FILTER {{ major.symbol }} FLOW <span aria-hidden="true">→</span>
                  </button>
                </template>
              </article>
            </div>
          </section>
        </div>

        <!-- Tab 4: Power Alerts -->
        <div v-show="overviewTab === 'alerts'" class="hub-tab-panel">
          <PowerAlertsBoard
            :prints="alertTape"
            :rows="payload.rows ?? []"
            :book="book"
            :asof="payload.asof"
            @open-symbol="openSymbol"
          />
        </div>

        <!-- Tab 5: Live Pulse & Triage -->
        <div v-show="overviewTab === 'triage'" class="hub-tab-panel">
          <section
            class="live-pulse"
            :class="`brief-${workspaceBrief.tone}`"
            aria-labelledby="live-pulse-title"
          >
            <div class="pulse-copy" :class="workspaceBrief.tone">
              <span class="section-kicker label">{{ workspaceBrief.eyebrow }}</span>
              <h2 id="live-pulse-title">{{ workspaceBrief.title }}</h2>
              <p>{{ workspaceBrief.body }}</p>
              <div class="pulse-cadence label">
                <span><i aria-hidden="true" /> {{ pulseState.label }}</span>
                <span>AUTO POLL {{ pollSeconds }}S</span>
                <span>SERVER CACHE {{ payload.cache?.ttl_seconds ?? '—' }}S</span>
                <span>{{ rankMoveCount }} RANK MOVES</span>
              </div>
            </div>

            <button
              v-for="(triagePick, index) in triagePicks"
              :key="triagePick.key"
              type="button"
              class="triage-pick"
              :class="[triagePick.leanState, flowLeanTokenClass(triagePick.leanState)]"
              :aria-label="`Inspect ${triagePick.symbol} live options flow — ${triagePick.eyebrow}`"
              @click="openSymbol(triagePick.symbol)"
            >
              <span class="triage-index fig">0{{ index + 1 }}</span>
              <span class="label">{{ triagePick.eyebrow }}</span>
              <span class="triage-symbol-line">
                <strong class="fig">{{ triagePick.symbol }}</strong>
                <b class="fig">{{ triagePick.value }}</b>
              </span>
              <span
                class="triage-lean label"
                :class="[triagePick.leanState, flowLeanTokenClass(triagePick.leanState)]"
                >{{ triagePick.lean }}</span
              >
              <small class="triage-action">{{ triagePick.detail }}</small>
              <small class="triage-focus">Focus: {{ triagePick.action }}</small>
              <span class="triage-tags">
                <span
                  v-for="tag in triagePick.tags"
                  :key="tag.label"
                  class="label"
                  :class="tag.kind"
                  >{{ tag.label }}</span
                >
              </span>
              <span class="triage-open label">VIEW LIVE SETUP →</span>
            </button>
          </section>
        </div>
      </section>

      <!-- Book alerts banner / tray (Matching Section Ordering for contract tests) -->
      <section
        class="alert-tray rise"
        :class="{ empty: !bookAlerts.length, armed: bookAlerts.length > 0 }"
        role="status"
      >
        <header>
          <span class="label">Book alerts</span>
          <strong v-if="bookAlerts.length">
            {{ bookAlerts.length }} Unusual / Sweep print{{ bookAlerts.length === 1 ? '' : 's' }} on
            pinned names
          </strong>
          <strong v-else>Watching {{ book.join(', ') || 'no names' }} for Unusual and Sweep</strong>
        </header>
        <ul v-if="bookAlerts.length">
          <li v-for="alert in bookAlerts.slice(0, 6)" :key="alert.key">
            <button type="button" class="fig" @click="openSymbol(alert.symbol)">
              {{ alert.symbol }}
            </button>
            <span class="label">{{ alert.kind.toUpperCase() }}</span>
            <span class="fig">{{ moneyCompact(alert.premium) }}</span>
            <small
              >{{ alert.right }} {{ alert.strike ?? '—' }} · {{ shortDate(alert.timestamp) }}</small
            >
          </li>
        </ul>
        <button v-if="bookAlerts.length" type="button" class="label" @click="dismissAlerts">
          CLEAR
        </button>
      </section>

      <!-- 2-Column Institutional Options Flow Workspace (Matching Reference Layout) -->
      <div class="flow-institutional-grid">
        <!-- Left Main Area: Filters, Tape Table, Evidence, and Review Queue (72% width) -->
        <main class="flow-main-column">
          <!-- Flow Review Filters (Quick Filter Rail) -->
          <section class="filter-shelf rise" aria-label="Flow review filters">
            <div class="filter-tier-primary">
              <div class="filter-search-group">
                <label class="search-filter">
                  <span class="label">Ticker</span>
                  <span class="input-shell">
                    <AppIcon name="search" :size="14" />
                    <input
                      v-model="symbolQuery"
                      type="search"
                      placeholder="NVDA or -SPY to hide"
                      autocomplete="off"
                    />
                    <button
                      v-if="symbolQuery"
                      type="button"
                      class="clear-input-btn label"
                      @click="symbolQuery = ''"
                    >
                      ×
                    </button>
                  </span>
                </label>
              </div>

              <fieldset class="seg-filter preset-filter">
                <legend class="label">
                  Tape presets
                  <HelpTip
                    label="Tape Presets"
                    text="Quick filters for institutional flow: Golden Sweeps ($100k+ sweeps), Sweeps, Whales ($500k+), Vol > OI opening activity, Unusual, Momentum, Moonshot, and My Book."
                    align="left"
                  />
                </legend>
                <div>
                  <button
                    v-for="preset in TAPE_PRESETS"
                    :key="preset.id"
                    type="button"
                    :class="{ active: tapePreset === preset.id }"
                    @click="tapePreset = preset.id"
                  >
                    {{ preset.label }}
                  </button>
                </div>
              </fieldset>

              <button
                type="button"
                class="reset-filter label"
                :disabled="activeFilterCount === 0"
                @click="clearFilters"
              >
                RESET FILTERS <span v-if="activeFilterCount">({{ activeFilterCount }})</span>
              </button>
            </div>

            <!-- Compact Layouts & Exclusions Tray -->
            <div v-if="layouts.length || exclusions.length" class="filter-meta-tray">
              <div v-if="layouts.length" class="tray-group">
                <span class="label">Saved layouts:</span>
                <button
                  v-for="layout in layouts"
                  :key="layout.id"
                  type="button"
                  class="layout-chip label"
                  :title="`Restore layout ${layout.name} (Press Delete to remove)`"
                  @click="applyLayout(layout)"
                  @keydown.delete.prevent="dropLayout(layout.id)"
                >
                  {{ layout.name }} ×
                </button>
              </div>
              <div v-if="exclusions.length" class="tray-group">
                <span class="label">Pinned exclusions:</span>
                <button
                  v-for="symbol in exclusions"
                  :key="symbol"
                  type="button"
                  class="exclusion-chip label"
                  :title="`Show ${symbol} again`"
                  @click="unpinExclusion(symbol)"
                >
                  −{{ symbol }} ×
                </button>
              </div>
            </div>

            <div class="filter-tier-secondary">
              <fieldset class="seg-filter activity-filter">
                <legend class="label">
                  Show
                  <HelpTip
                    label="Activity Heuristics"
                    text="Flags mark unusual prints, repeat orders, or large sizes for inspection. They do not establish direction."
                    align="left"
                  />
                </legend>
                <div>
                  <button
                    type="button"
                    :class="{ active: activityFilter === 'all' }"
                    @click="activityFilter = 'all'"
                  >
                    All
                  </button>
                  <button
                    type="button"
                    :class="{ active: activityFilter === 'incoming' }"
                    @click="activityFilter = 'incoming'"
                  >
                    New
                  </button>
                  <button
                    type="button"
                    title="Largest flagged prints first, newest on ties — premium, volume, repeat, or sweep heuristics in the current tape"
                    :class="{ active: activityFilter === 'flagged' }"
                    @click="showFlaggedPrints"
                  >
                    Flags
                  </button>
                </div>
              </fieldset>

              <fieldset class="seg-filter">
                <legend class="label">
                  Contract mix
                  <HelpTip
                    label="Contract Mix"
                    text="Filters premium mix only (Calls vs Puts). Buy/sell aggressor direction requires provider-signed flow."
                    align="left"
                  />
                </legend>
                <div>
                  <button
                    type="button"
                    :class="{ active: rightFilter === 'all' }"
                    @click="rightFilter = 'all'"
                  >
                    Any
                  </button>
                  <button
                    type="button"
                    :class="{ active: rightFilter === 'call' }"
                    @click="rightFilter = 'call'"
                  >
                    Call-led
                  </button>
                  <button
                    type="button"
                    :class="{ active: rightFilter === 'put' }"
                    @click="rightFilter = 'put'"
                  >
                    Put-led
                  </button>
                </div>
              </fieldset>

              <fieldset class="seg-filter moneyness-filter">
                <legend class="label">
                  Moneyness
                  <HelpTip
                    label="Moneyness Filter"
                    text="OTM is ≥2% out of the money; ATM is within ±2%; ITM is ≥2% in the money."
                    align="left"
                  />
                </legend>
                <div>
                  <button
                    type="button"
                    :class="{ active: moneynessFilter === 'all' }"
                    @click="moneynessFilter = 'all'"
                  >
                    All
                  </button>
                  <button
                    type="button"
                    :class="{ active: moneynessFilter === 'otm' }"
                    @click="moneynessFilter = 'otm'"
                  >
                    OTM
                  </button>
                  <button
                    type="button"
                    :class="{ active: moneynessFilter === 'atm' }"
                    @click="moneynessFilter = 'atm'"
                  >
                    ATM
                  </button>
                  <button
                    type="button"
                    :class="{ active: moneynessFilter === 'itm' }"
                    @click="moneynessFilter = 'itm'"
                  >
                    ITM
                  </button>
                </div>
              </fieldset>

              <label class="select-filter">
                <span class="label">Average expiry</span>
                <select v-model="dteFilter">
                  <option value="all">Any DTE</option>
                  <option value="week">0–7 days</option>
                  <option value="month">8–30 days</option>
                  <option value="dated">31+ days</option>
                </select>
              </label>

              <label class="select-filter">
                <span class="label">Order by</span>
                <select v-model="sortKey">
                  <option value="review">Review priority</option>
                  <option value="incoming">New premium</option>
                  <option value="premium">Premium</option>
                  <option value="sweeps">Sweep premium</option>
                  <option value="flagged">Flagged share</option>
                  <option value="expiry">Nearest expiry</option>
                </select>
              </label>
            </div>
          </section>

          <!-- Realtime Option Flow Live Table (Institutional Centerpiece) -->
          <section class="realtime-tape-card rise" aria-label="Realtime Option Flow">
            <header class="realtime-tape-header">
              <div class="realtime-title-line">
                <i class="live-pulse-dot" aria-hidden="true" />
                <h2>{{ activeSymbol }} Realtime Option Flow</h2>
                <span class="live-tag label">STREAMING</span>
              </div>
              <div class="tape-quick-actions">
                <span class="tape-count-badge label">{{ tapeRows.length }} PRINTS</span>
                <button
                  type="button"
                  class="panel-action label"
                  :disabled="!tapeRows.length"
                  @click="downloadTapeCsv"
                >
                  EXPORT CSV
                </button>
                <button
                  type="button"
                  class="panel-action label"
                  @click="tapeShowAll = !tapeShowAll"
                >
                  {{ tapeShowAll ? 'COLLAPSE TAPE' : `SHOW ALL ${qualifiedTapeRows.length}` }}
                </button>
              </div>
            </header>

            <div v-if="tapeRows.length" class="table-scroll tape-scroll">
              <table class="grid tape-table tape-live">
                <caption class="sr-only">
                  Live options-flow prints. Select a row to inspect its contract and open the
                  underlying options chain.
                </caption>
                <colgroup>
                  <col class="tape-col-time" />
                  <col class="tape-col-symbol" />
                  <col class="tape-col-contract" />
                  <col class="tape-col-expiry" />
                  <col class="tape-col-fill" />
                  <col class="tape-col-class" />
                  <col class="tape-col-vol-oi" />
                  <col class="tape-col-premium" />
                  <col class="tape-col-percentile" />
                  <col class="tape-col-aggressor" />
                </colgroup>
                <thead>
                  <tr>
                    <th
                      class="sortable th-time"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        tapeSortKey === 'time'
                          ? tapeSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setTapeSort('time')"
                      @keydown.enter="setTapeSort('time')"
                    >
                      <span class="th-content">
                        <span>Time UTC</span>
                        <span class="sort-indicator">{{ tapeSortArrow('time') }}</span>
                      </span>
                    </th>
                    <th
                      class="sortable th-symbol"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        tapeSortKey === 'symbol'
                          ? tapeSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setTapeSort('symbol')"
                      @keydown.enter="setTapeSort('symbol')"
                    >
                      <span class="th-content">
                        <span>Symbol</span>
                        <span class="sort-indicator">{{ tapeSortArrow('symbol') }}</span>
                      </span>
                    </th>
                    <th
                      class="sortable th-contract"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        tapeSortKey === 'contract'
                          ? tapeSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setTapeSort('contract')"
                      @keydown.enter="setTapeSort('contract')"
                    >
                      <span class="th-content">
                        <span>Contract</span>
                        <span class="sort-indicator">{{ tapeSortArrow('contract') }}</span>
                      </span>
                    </th>
                    <th
                      class="sortable th-expiry"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        tapeSortKey === 'expiry'
                          ? tapeSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setTapeSort('expiry')"
                      @keydown.enter="setTapeSort('expiry')"
                    >
                      <span class="th-content">
                        <span>Expiry / distance</span>
                        <span class="sort-indicator">{{ tapeSortArrow('expiry') }}</span>
                      </span>
                    </th>
                    <th
                      class="num sortable th-fill"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        tapeSortKey === 'fill'
                          ? tapeSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setTapeSort('fill')"
                      @keydown.enter="setTapeSort('fill')"
                    >
                      <span class="th-content">
                        <span>Fill × contracts</span>
                        <span class="sort-indicator">{{ tapeSortArrow('fill') }}</span>
                      </span>
                    </th>
                    <th
                      class="sortable th-class"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        tapeSortKey === 'trade_class'
                          ? tapeSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setTapeSort('trade_class')"
                      @keydown.enter="setTapeSort('trade_class')"
                    >
                      <span class="th-content">
                        <span>Class</span>
                        <HelpTip
                          label="Execution Class"
                          text="Order classification: Sweeps (multi-exchange aggressive market orders), Golden Sweeps ($1M+ sweeps), Blocks (large single negotiated prints), Splits, and Multileg orders."
                          align="left"
                        />
                        <span class="sort-indicator">{{ tapeSortArrow('trade_class') }}</span>
                      </span>
                    </th>
                    <th
                      class="num sortable th-vol-oi"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        tapeSortKey === 'vol_oi'
                          ? tapeSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setTapeSort('vol_oi')"
                      @keydown.enter="setTapeSort('vol_oi')"
                    >
                      <span class="th-content">
                        <span>Vol / OI</span>
                        <HelpTip
                          label="Vol / OI Ratio"
                          text="Volume to Open Interest ratio: >1.0 indicates new opening position activity rather than closing existing contracts."
                          align="center"
                        />
                        <span class="sort-indicator">{{ tapeSortArrow('vol_oi') }}</span>
                      </span>
                    </th>
                    <th
                      class="num sortable th-prem"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        tapeSortKey === 'premium'
                          ? tapeSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setTapeSort('premium')"
                      @keydown.enter="setTapeSort('premium')"
                    >
                      <span class="th-content">
                        <span>Premium</span>
                        <span class="sort-indicator">{{ tapeSortArrow('premium') }}</span>
                      </span>
                    </th>
                    <th
                      class="sortable th-percentile"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        tapeSortKey === 'percentile'
                          ? tapeSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setTapeSort('percentile')"
                      @keydown.enter="setTapeSort('percentile')"
                    >
                      <span class="th-content">
                        <span>Sample %ile</span>
                        <HelpTip
                          label="Sample Percentile"
                          text="Relative premium percentile of this print compared to all prints in the current provider sample."
                          align="center"
                        />
                        <span class="sort-indicator">{{ tapeSortArrow('percentile') }}</span>
                      </span>
                    </th>
                    <th
                      class="sortable th-aggressor"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        tapeSortKey === 'aggressor'
                          ? tapeSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setTapeSort('aggressor')"
                      @keydown.enter="setTapeSort('aggressor')"
                    >
                      <span class="th-content">
                        <span>Aggressor</span>
                        <HelpTip
                          label="Aggressor Side"
                          text="Side taking liquidity: Ask (buyer aggressive), Bid (seller aggressive), Midpoint (neutral), or Multi-exchange."
                          align="right"
                        />
                        <span class="sort-indicator">{{ tapeSortArrow('aggressor') }}</span>
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(row, index) in tapeRows"
                    :key="`${row.timestamp}-${row.symbol}-${row.expiry}-${row.strike}-${index}`"
                    :class="{ incoming: isNewPrint(row), selected: isSelectedPrint(row) }"
                    role="button"
                    tabindex="0"
                    :aria-label="`Inspect ${row.symbol || 'unknown'} ${row.right || 'option'} ${row.strike ?? ''} option print`"
                    :aria-pressed="isSelectedPrint(row)"
                    @click="selectTapeRow(row)"
                    @keydown.enter="selectTapeRow(row)"
                    @keydown.space.prevent="selectTapeRow(row)"
                  >
                    <td class="fig" :title="row.timestamp">
                      <span class="time-readout">{{ tapeTime(row.timestamp) }}</span>
                      <span v-if="isNewPrint(row)" class="new-badge label">NEW</span>
                    </td>
                    <td class="symbol-cell">
                      <div class="symbol-cell-content">
                        <button
                          v-if="row.symbol"
                          type="button"
                          class="symbol-button fig"
                          :title="tickerCompanyName(row.symbol) || undefined"
                          @click.stop="openSymbol(row.symbol)"
                        >
                          {{ row.symbol }}
                        </button>
                        <span v-else>{{ DASH }}</span>
                        <small
                          v-if="row.underlying_price != null"
                          class="tape-spot-label fig"
                          :class="
                            row.underlying_price && row.strike
                              ? tone(
                                  row.right === 'call'
                                    ? row.underlying_price - row.strike
                                    : row.strike - row.underlying_price,
                                )
                              : ''
                          "
                        >
                          {{ usd(row.underlying_price, 2) }}
                        </small>
                      </div>
                    </td>
                    <td class="contract-cell">
                      <span class="right-chip label" :class="row.right">{{
                        row.right.toUpperCase()
                      }}</span>
                      <strong class="strike-val fig">{{ usd(row.strike, 2) }}</strong>
                    </td>
                    <td class="expiry-cell fig" :title="row.expiry ?? undefined">
                      <div class="expiry-cell-content">
                        <div class="expiry-primary">
                          <strong>{{ shortDate(row.expiry) }}</strong>
                          <span class="dte-pill label" :class="formatDteBadge(row.dte).className">{{
                            formatDteBadge(row.dte).label
                          }}</span>
                        </div>
                        <span
                          class="moneyness-tag label"
                          :class="formatMoneyness(row.otm_pct).className"
                        >
                          {{ formatMoneyness(row.otm_pct).label }}
                        </span>
                      </div>
                    </td>
                    <td class="execution-cell num fig">
                      <strong>{{ usd(row.price, 2) }}</strong>
                      <small>× {{ exactCount(row.contracts ?? row.volume) }}</small>
                    </td>
                    <td>
                      <span
                        class="flow-badge label"
                        :class="classifyFlowOrder(row).className"
                        :title="`${classifyFlowOrder(row).description} · ${tradeClassTitle(row)}`"
                      >
                        <i
                          v-if="classifyFlowOrder(row).type === 'golden_sweep'"
                          class="badge-pip"
                          aria-hidden="true"
                        />
                        {{ classifyFlowOrder(row).label }}
                      </span>
                    </td>
                    <td class="vol-oi-cell num">
                      <span
                        class="vol-oi-pill label"
                        :class="{
                          'vol-oi-high': computeVolOiRatio(
                            row.contracts ?? row.volume,
                            row.open_interest,
                          ).isHigh,
                          'vol-oi-extreme': computeVolOiRatio(
                            row.contracts ?? row.volume,
                            row.open_interest,
                          ).isExtreme,
                        }"
                        :title="
                          computeVolOiRatio(row.contracts ?? row.volume, row.open_interest).isHigh
                            ? 'Unusual Volume > Open Interest (Opening Activity)'
                            : 'Volume to Open Interest ratio'
                        "
                      >
                        <span
                          v-if="
                            computeVolOiRatio(row.contracts ?? row.volume, row.open_interest).isHigh
                          "
                          class="hot-pip"
                          aria-hidden="true"
                          >•</span
                        >
                        {{
                          computeVolOiRatio(row.contracts ?? row.volume, row.open_interest)
                            .formatted
                        }}
                      </span>
                    </td>
                    <td
                      class="fig num tape-premium"
                      :class="classifyPremiumTier(row.premium).className"
                    >
                      <div class="premium-meter-wrap">
                        <span
                          class="premium-fill-meter"
                          :style="{ width: heatWidth(row.premium_percentile) }"
                        />
                        <span
                          v-if="classifyPremiumTier(row.premium).isWhale"
                          class="whale-indicator label"
                          :class="classifyPremiumTier(row.premium).className"
                        >
                          {{ classifyPremiumTier(row.premium).label }}
                        </span>
                        <span class="premium-val-text">{{ moneyCompact(row.premium) }}</span>
                      </div>
                    </td>
                    <td>
                      <div class="heat-cell" :class="heatClass(row.premium_percentile)">
                        <span class="heat-track" aria-hidden="true"
                          ><i :style="{ width: heatWidth(row.premium_percentile) }"
                        /></span>
                        <span class="fig">{{ fractionPercent(row.premium_percentile, 0) }}</span>
                      </div>
                    </td>
                    <td>
                      <span
                        class="aggressor label"
                        :class="signedPrintTokenClass(row.aggressor ?? row.aggressor_label)"
                        >{{ aggressorLabel(row) }}</span
                      >
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="tape-unavailable">
              <AppIcon name="density" :size="22" />
              <div>
                <strong>{{
                  baseSummary?.tape_detail_available === false
                    ? 'Contract detail is unavailable for this snapshot.'
                    : 'No raw prints match the active filters.'
                }}</strong>
                <p>
                  {{
                    baseSummary?.tape_detail_available === false
                      ? 'Ticker aggregates remain valid; individual contracts were not supplied.'
                      : 'Reset filters or choose another activity slice.'
                  }}
                </p>
              </div>
            </div>
          </section>

          <!-- Raw Contract Prints (Evidence Drawer / On-demand history) -->
          <section class="evidence-drawer rise" :class="{ open: tapeExpanded }">
            <button
              type="button"
              class="drawer-toggle"
              :aria-expanded="tapeExpanded"
              aria-controls="flow-raw-tape"
              @click="tapeExpanded = !tapeExpanded"
            >
              <span class="drawer-index fig">02</span>
              <span class="drawer-copy">
                <strong>Raw contract prints</strong>
                <small>Evidence layer · {{ tapeMeta }}</small>
              </span>
              <span class="drawer-note">Open when you need fill-level detail</span>
              <span class="drawer-action label"
                >{{ tapeExpanded ? 'HIDE' : 'SHOW TAPE' }} <i aria-hidden="true">⌄</i></span
              >
            </button>

            <div v-if="tapeExpanded" id="flow-raw-tape" class="drawer-body">
              <div class="tape-toolbar">
                <p>
                  Filters above also apply here.
                  <strong>C/P feeds the activity lean; signed buy/sell is separate.</strong>
                  Aggressor is shown only when the provider supplies it.
                </p>
                <div class="tape-actions">
                  <button
                    type="button"
                    class="panel-action label"
                    :disabled="!tapeRows.length"
                    @click="downloadTapeCsv"
                  >
                    EXPORT TAPE CSV
                  </button>
                  <button
                    type="button"
                    class="panel-action label"
                    @click="tapeShowAll = !tapeShowAll"
                  >
                    {{ tapeShowAll ? 'COLLAPSE TAPE' : `SHOW ALL ${qualifiedTapeRows.length}` }}
                  </button>
                </div>
              </div>
              <div class="history-tape-bar">
                <span class="label">On-demand history</span>
                <span class="sr-only">On-demand historical tape</span>
                <input
                  v-model="historySymbol"
                  type="text"
                  maxlength="10"
                  placeholder="SYMBOL"
                  aria-label="History symbol"
                />
                <input v-model="historyFrom" type="date" aria-label="History from" />
                <input v-model="historyTo" type="date" aria-label="History to" />
                <button
                  type="button"
                  class="panel-action label"
                  :disabled="historyLoading"
                  @click="void loadHistoryTape()"
                >
                  {{ historyLoading ? 'LOADING…' : 'LOAD HISTORY' }}
                </button>
                <button
                  v-if="historyTape.length"
                  type="button"
                  class="panel-action label"
                  title="Export historical tape to CSV"
                  @click="downloadHistoryTapeCsv"
                >
                  EXPORT CSV
                </button>
                <button
                  v-if="historyTape.length > 40"
                  type="button"
                  class="panel-action label"
                  @click="historyShowAll = !historyShowAll"
                >
                  {{ historyShowAll ? 'SHOW FIRST 40' : `SHOW ALL ${historyTape.length}` }}
                </button>
                <small v-if="historyMeta">{{ historyMeta }}</small>
                <small v-if="historyError">{{ historyError }}</small>
              </div>
              <div v-if="historyTape.length" class="table-scroll tape-scroll">
                <table class="grid tape-table">
                  <thead>
                    <tr>
                      <th class="label">Time UTC</th>
                      <th class="label">Symbol</th>
                      <th class="label">Right</th>
                      <th class="label num">Strike</th>
                      <th class="label">Expiry</th>
                      <th class="label">Class</th>
                      <th class="label num">Price</th>
                      <th class="label num">Contracts</th>
                      <th class="label num">Premium</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="row in historyShowAll ? historyTape : historyTape.slice(0, 40)"
                      :key="flowPrintKey(row)"
                    >
                      <td class="fig">{{ shortDate(row.timestamp) }}</td>
                      <td class="fig bold">{{ row.symbol || historySymbol }}</td>
                      <td class="fig">
                        <span class="bias-chip label" :class="row.right">{{
                          row.right?.toUpperCase()
                        }}</span>
                      </td>
                      <td class="fig num">{{ row.strike != null ? `$${row.strike}` : '—' }}</td>
                      <td class="fig">{{ row.expiry ? shortDate(row.expiry) : '—' }}</td>
                      <td class="label">
                        {{ (row.presets ?? []).join(' · ') || row.trade_class || '—' }}
                      </td>
                      <td class="fig num">
                        {{ row.price != null ? `$${row.price.toFixed(2)}` : '—' }}
                      </td>
                      <td class="fig num">{{ num(row.contracts ?? row.volume, 0) }}</td>
                      <td
                        class="fig num"
                        :class="[row.right, { 'whale-prem': (row.premium ?? 0) >= 100_000 }]"
                      >
                        {{ moneyCompact(row.premium) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <!-- What deserves review (Panel 01) -->
          <Panel label="What deserves review" index="01" :meta="reviewMeta" flush live>
            <template #action>
              <button
                type="button"
                class="panel-action label"
                :disabled="!reviewRows.length"
                @click="downloadAggregateCsv"
              >
                EXPORT CSV
              </button>
            </template>

            <div v-if="reviewRows.length" class="table-scroll review-scroll">
              <table class="grid review-table">
                <thead>
                  <tr>
                    <th
                      class="label sortable"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        reviewSortKey === 'symbol'
                          ? reviewSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setReviewSort('symbol')"
                      @keydown.enter="setReviewSort('symbol')"
                    >
                      Review <span class="sort-indicator">{{ reviewSortArrow('symbol') }}</span>
                    </th>
                    <th
                      class="label sortable"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        reviewSortKey === 'review'
                          ? reviewSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setReviewSort('review')"
                      @keydown.enter="setReviewSort('review')"
                    >
                      Desk next step
                      <HelpTip
                        label="Desk Next Step"
                        text="Actionable research next step derived from flow concentration, momentum, and options wall positioning."
                        align="left"
                      />
                      <span class="sort-indicator">{{ reviewSortArrow('review') }}</span>
                    </th>
                    <th
                      class="label num sortable"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        reviewSortKey === 'premium'
                          ? reviewSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : reviewSortKey === 'incoming'
                            ? reviewSortDir === 'asc'
                              ? 'ascending'
                              : 'descending'
                            : 'none'
                      "
                      @click="setReviewSort('premium')"
                      @keydown.enter="setReviewSort('premium')"
                    >
                      Sample / change
                      <span class="sort-indicator">{{
                        reviewSortArrow('premium') || reviewSortArrow('incoming')
                      }}</span>
                    </th>
                    <th
                      class="label sortable"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        reviewSortKey === 'mix'
                          ? reviewSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setReviewSort('mix')"
                      @keydown.enter="setReviewSort('mix')"
                    >
                      Call / put mix
                      <HelpTip
                        label="Contract Mix"
                        text="Distribution of call vs put premium for this symbol in the sample. Identity only — not buy/sell direction."
                        align="center"
                      />
                      <span class="sort-indicator">{{ reviewSortArrow('mix') }}</span>
                    </th>
                    <th
                      class="label sortable"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        reviewSortKey === 'concentration'
                          ? reviewSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setReviewSort('concentration')"
                      @keydown.enter="setReviewSort('concentration')"
                    >
                      Concentration
                      <HelpTip
                        label="Flow Concentration"
                        text="Top strike and DTE expiration zone where institutional order volume is clustered."
                        align="center"
                      />
                      <span class="sort-indicator">{{ reviewSortArrow('concentration') }}</span>
                    </th>
                    <th
                      class="label sortable"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        reviewSortKey === 'move'
                          ? reviewSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setReviewSort('move')"
                      @keydown.enter="setReviewSort('move')"
                    >
                      Underlying <span class="sort-indicator">{{ reviewSortArrow('move') }}</span>
                    </th>
                    <th
                      class="label sortable"
                      role="columnheader"
                      tabindex="0"
                      :aria-sort="
                        reviewSortKey === 'lean'
                          ? reviewSortDir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      "
                      @click="setReviewSort('lean')"
                      @keydown.enter="setReviewSort('lean')"
                    >
                      Activity lean
                      <HelpTip
                        label="Activity Lean"
                        text="Descriptive directional bias derived from premium mix and price impulse. Signed flow confirmation required for higher confidence."
                        align="right"
                      />
                      <span class="sort-indicator">{{ reviewSortArrow('lean') }}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(row, index) in reviewRows"
                    :key="row.symbol"
                    :class="{ incoming: symbolPulse(row.symbol).newPrints > 0 }"
                  >
                    <td class="review-symbol">
                      <span class="row-rank fig">{{ String(index + 1).padStart(2, '0') }}</span>
                      <button
                        type="button"
                        class="symbol-button fig"
                        :title="tickerCompanyName(row.symbol) || undefined"
                        @click="openSymbol(row.symbol)"
                      >
                        {{ row.symbol }}
                      </button>
                      <button
                        type="button"
                        class="book-pin label"
                        :class="{ on: onBook(row.symbol) }"
                        :aria-label="
                          onBook(row.symbol)
                            ? `Remove ${row.symbol} from book`
                            : `Pin ${row.symbol} to book`
                        "
                        @click="toggleBook(row.symbol)"
                      >
                        {{ onBook(row.symbol) ? 'PINNED' : 'PIN' }}
                      </button>
                      <span
                        v-if="!pulse.baseline"
                        class="table-rank-move fig"
                        :class="rankMoveClass(row.symbol)"
                        >{{ rankMoveLabel(row.symbol) }}</span
                      >
                    </td>
                    <td
                      class="reason-cell action-cell"
                      :class="[
                        actionInsight(row).leanState,
                        flowLeanTokenClass(actionInsight(row).leanState),
                      ]"
                    >
                      <span
                        class="priority-chip label"
                        :class="[
                          actionInsight(row).priority,
                          flowPriorityTokenClass(actionInsight(row).priority),
                        ]"
                        >{{ actionInsight(row).priority.toUpperCase() }}</span
                      >
                      <strong>{{ actionInsight(row).action }}</strong>
                      <small
                        >Focus {{ actionInsight(row).focus }} · {{ actionInsight(row).why }}</small
                      >
                      <span class="tag-line">
                        <span
                          v-for="tag in evidenceFor(row)"
                          :key="tag.label"
                          class="evidence-tag label"
                          :class="tag.kind"
                        >
                          {{ tag.label }}
                        </span>
                      </span>
                    </td>
                    <td class="activity-cell num">
                      <strong class="fig">{{ moneyCompact(row.premium) }}</strong>
                      <small
                        class="fig"
                        :class="{
                          'incoming-copy': !pulse.baseline && symbolPulse(row.symbol).newPrints > 0,
                        }"
                      >
                        {{
                          pulse.baseline
                            ? `${FIRST_WINDOW_BASELINE} · ${exactCount(row.contract_count)} contracts`
                            : symbolPulseCopy(row.symbol)
                        }}
                      </small>
                    </td>
                    <td class="identity-cell">
                      <div class="identity-labels fig">
                        <span class="call-text">CALLS {{ callShareLabel(row) }}</span>
                        <span class="put-text">PUTS {{ putShareLabel(row) }}</span>
                      </div>
                      <span class="identity-bar" aria-hidden="true">
                        <i class="call-segment" :style="{ width: callBarWidth(row) }" />
                        <i class="put-segment" :style="{ width: putBarWidth(row) }" />
                      </span>
                      <small class="identity-note">CONTRACT TYPE · NOT BUY / SELL</small>
                    </td>
                    <td class="structure-cell fig">
                      <strong>{{
                        concentrationLabel(
                          tapeStats(row.symbol)?.topStrike,
                          row.average_dte == null
                            ? NO_STRIKE_IN_TAPE
                            : `${num(row.average_dte, 1)}D avg`,
                        )
                      }}</strong>
                      <small>{{
                        tapeStats(row.symbol)?.topDteBucket ??
                        `${fractionPercent(row.average_otm_pct)} avg OTM`
                      }}</small>
                    </td>
                    <td class="price-cell">
                      <strong class="fig">{{ priceRead(row).spot }}</strong>
                      <small :class="priceRead(row).tone"
                        >{{ priceRead(row).move }} · {{ priceRead(row).detail }}</small
                      >
                    </td>
                    <td
                      class="direction-cell"
                      :class="[
                        directionRead(row.symbol).state,
                        flowLeanTokenClass(directionRead(row.symbol).state),
                      ]"
                    >
                      <span class="direction-chip label">{{
                        directionRead(row.symbol).label
                      }}</span>
                      <small>{{ directionRead(row.symbol).detail }}</small>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="filteredRows.length > DEFAULT_REVIEW_ROWS" class="queue-footer">
              <span class="label">
                {{
                  showAllReviews
                    ? `ALL ${filteredRows.length} MATCHES VISIBLE`
                    : `TOP ${DEFAULT_REVIEW_ROWS} SHOWN · ${filteredRows.length - DEFAULT_REVIEW_ROWS} LOWER-PRIORITY MATCHES COLLAPSED`
                }}
              </span>
              <button
                type="button"
                class="panel-action label"
                @click="showAllReviews = !showAllReviews"
              >
                {{ showAllReviews ? 'COLLAPSE TO TOP 12' : `SHOW ALL ${filteredRows.length}` }}
              </button>
            </div>
            <div v-if="!reviewRows.length" class="no-filter-results">
              <strong>No ticker matches this filter combination.</strong>
              <p>The source data is still present; only this local view is empty.</p>
              <button type="button" class="empty-action label" @click="clearFilters">
                RESET FILTERS
              </button>
            </div>
          </Panel>
        </main>

        <!-- Right Column: Realtime Flow Analytics Sidebar (28% width) -->
        <aside class="flow-sidebar-column">
          <!-- Card 1: Flow Trend Sparkline & Cumulative Delta -->
          <div class="sidebar-card trend-card rise">
            <div class="sidebar-card-head">
              <span class="label section-kicker">Realtime Flow Analytics</span>
              <h3 class="sidebar-card-title">{{ activeSymbol }} Flow Trend</h3>
            </div>
            <div class="trend-readout-row">
              <div>
                <span class="label">Cumulative Net Flow</span>
                <strong class="fig net-flow-val" :class="netFlowTotal >= 0 ? 'pos' : 'neg'">
                  {{ netFlowTotal >= 0 ? '+' : '−' }}${{ compact(Math.abs(netFlowTotal)) }}
                </strong>
              </div>
              <button
                type="button"
                class="trend-badge-btn label"
                :class="[
                  netFlowTotal >= 0 ? 'bullish' : 'bearish',
                  { active: rightFilter !== 'all' },
                ]"
                :title="
                  netFlowTotal >= 0 ? 'Click to filter Call flow' : 'Click to filter Put flow'
                "
                @click="netFlowTotal >= 0 ? toggleCallFilter() : togglePutFilter()"
              >
                {{ netFlowTotal >= 0 ? 'CALL DOMINANT' : 'PUT DOMINANT' }}
                <span v-if="rightFilter !== 'all'" class="filter-on-tag">FILTERED</span>
              </button>
            </div>
            <!-- Trend SVG Chart -->
            <div class="trend-chart-box" :title="`Cumulative flow: ${moneyCompact(netFlowTotal)}`">
              <svg viewBox="0 0 240 54" class="trend-svg" preserveAspectRatio="none">
                <path :d="flowTrendAreaPath" class="trend-area" />
                <path
                  :d="flowTrendSvgPath"
                  class="trend-line"
                  stroke-width="2"
                  stroke-linecap="round"
                />
              </svg>
            </div>
          </div>

          <!-- Card 2: Call vs Put Premium & Volume Ratio Breakdown -->
          <div class="sidebar-card distribution-card rise">
            <div class="sidebar-card-head">
              <div class="dist-head-row">
                <div>
                  <span class="label section-kicker">Volume &amp; Premium Distribution</span>
                  <h3 class="sidebar-card-title">Flow Ratio</h3>
                </div>
                <span v-if="rightFilter !== 'all'" class="filter-pill label">
                  {{ rightFilter.toUpperCase() }} ONLY
                </span>
              </div>
            </div>
            <div class="distribution-meters">
              <div class="dist-row">
                <div class="dist-labels fig">
                  <button
                    type="button"
                    class="dist-label-btn call-text"
                    :class="{ active: rightFilter === 'call' }"
                    title="Filter Call-led flow"
                    @click="toggleCallFilter"
                  >
                    Calls {{ activeTickerStats.callPct }}%
                  </button>
                  <button
                    type="button"
                    class="dist-label-btn put-text"
                    :class="{ active: rightFilter === 'put' }"
                    title="Filter Put-led flow"
                    @click="togglePutFilter"
                  >
                    Puts {{ activeTickerStats.putPct }}%
                  </button>
                </div>
                <div class="dist-track interactive" title="Click green for Calls, red for Puts">
                  <i
                    class="call-segment clickable"
                    :class="{ dimmed: rightFilter === 'put' }"
                    :style="{ width: `${activeTickerStats.callPct}%` }"
                    @click="toggleCallFilter"
                  />
                  <i
                    class="put-segment clickable"
                    :class="{ dimmed: rightFilter === 'call' }"
                    :style="{ width: `${activeTickerStats.putPct}%` }"
                    @click="togglePutFilter"
                  />
                </div>
              </div>
              <div class="dist-legend-grid">
                <button
                  type="button"
                  class="dist-stat-btn call"
                  :class="{ active: rightFilter === 'call' }"
                  title="Click to toggle Call filter"
                  @click="toggleCallFilter"
                >
                  <span class="label">Total Call Premium</span>
                  <strong class="fig">{{ moneyCompact(activeTickerStats.callPremium) }}</strong>
                </button>
                <button
                  type="button"
                  class="dist-stat-btn put"
                  :class="{ active: rightFilter === 'put' }"
                  title="Click to toggle Put filter"
                  @click="togglePutFilter"
                >
                  <span class="label">Total Put Premium</span>
                  <strong class="fig">{{ moneyCompact(activeTickerStats.putPremium) }}</strong>
                </button>
              </div>
            </div>
          </div>

          <!-- Card 3: Top Flow Contracts / Active Strikes -->
          <div class="sidebar-card top-contracts-card rise">
            <div class="sidebar-card-head">
              <span class="label section-kicker">Largest Orders</span>
              <h3 class="sidebar-card-title">Top Active Strikes</h3>
            </div>
            <div v-if="topFlowContracts.length" class="top-contracts-list">
              <button
                v-for="contract in topFlowContracts"
                :key="flowPrintKey(contract)"
                type="button"
                class="contract-row-btn"
                :class="{ active: isSelectedPrint(contract) }"
                @click="selectTapeRow(contract)"
              >
                <div class="contract-left">
                  <span class="right-chip label" :class="contract.right">{{
                    contract.right?.toUpperCase()
                  }}</span>
                  <strong class="contract-strike fig">{{ usd(contract.strike, 0) }}</strong>
                  <small class="contract-exp label">{{ shortDate(contract.expiry) }}</small>
                </div>
                <div class="contract-right">
                  <strong class="contract-prem fig">{{ moneyCompact(contract.premium) }}</strong>
                  <span class="contract-type label" :class="classifyFlowOrder(contract).className">
                    {{ classifyFlowOrder(contract).label }}
                  </span>
                </div>
              </button>
            </div>
            <div v-else class="empty-top-contracts">
              <small class="label">No orders matching current filter</small>
            </div>
          </div>

          <!-- Card 4: Institutional Blocks & Lit Pool Radar -->
          <div class="sidebar-card institutional-alert-card rise">
            <div class="alert-card-badge-line">
              <span class="institutional-badge label">INSTITUTIONAL RADAR</span>
              <span v-if="tapePreset !== 'all'" class="radar-live-pill label">FILTERED</span>
            </div>
            <h3 class="alert-card-heading">Institutional Flow &amp; Lit Pool Radar</h3>
            <p class="alert-card-description">
              Live real-time detection of high-conviction institutional prints, sweep bursts, and
              whale orders.
            </p>
            <div class="radar-action-grid">
              <button
                type="button"
                class="radar-grid-btn"
                :class="{ active: tapePreset === 'whales' }"
                @click="togglePresetFilter('whales')"
              >
                <div class="radar-btn-meta">
                  <span class="radar-btn-title">Whales ($500k+)</span>
                  <span class="radar-btn-count fig"
                    >{{ radarStats.whales }} prints ·
                    {{ moneyCompact(radarStats.whalePremium) }}</span
                  >
                </div>
                <span class="radar-btn-action label">{{
                  tapePreset === 'whales' ? 'ACTIVE' : 'FILTER'
                }}</span>
              </button>
              <button
                type="button"
                class="radar-grid-btn"
                :class="{ active: tapePreset === 'sweeps' }"
                @click="togglePresetFilter('sweeps')"
              >
                <div class="radar-btn-meta">
                  <span class="radar-btn-title">Sweeps</span>
                  <span class="radar-btn-count fig"
                    >{{ radarStats.sweeps }} prints ·
                    {{ moneyCompact(radarStats.sweepPremium) }}</span
                  >
                </div>
                <span class="radar-btn-action label">{{
                  tapePreset === 'sweeps' ? 'ACTIVE' : 'FILTER'
                }}</span>
              </button>
              <button
                type="button"
                class="radar-grid-btn"
                :class="{ active: tapePreset === 'golden_sweeps' }"
                @click="togglePresetFilter('golden_sweeps')"
              >
                <div class="radar-btn-meta">
                  <span class="radar-btn-title">Golden Sweeps</span>
                  <span class="radar-btn-count fig"
                    >{{ radarStats.goldenSweeps }} prints ·
                    {{ moneyCompact(radarStats.goldenSweepPremium) }}</span
                  >
                </div>
                <span class="radar-btn-action label">{{
                  tapePreset === 'golden_sweeps' ? 'ACTIVE' : 'FILTER'
                }}</span>
              </button>
              <button
                type="button"
                class="radar-grid-btn"
                :class="{ active: tapePreset === 'vol_oi' }"
                @click="togglePresetFilter('vol_oi')"
              >
                <div class="radar-btn-meta">
                  <span class="radar-btn-title">Vol &gt; OI (Opening)</span>
                  <span class="radar-btn-count fig">{{ radarStats.volOi }} prints</span>
                </div>
                <span class="radar-btn-action label">{{
                  tapePreset === 'vol_oi' ? 'ACTIVE' : 'FILTER'
                }}</span>
              </button>
            </div>
          </div>

          <!-- Card 5: Selected Print Contract Anatomy Inspector -->
          <div v-if="effectiveSelectedPrint" class="sidebar-card inspector-card rise">
            <div class="sidebar-card-head">
              <div class="inspector-title-row">
                <div>
                  <span class="label section-kicker">Contract Anatomy</span>
                  <h3 class="sidebar-card-title">
                    {{ effectiveSelectedPrint.symbol || activeSymbol }} Contract Details
                  </h3>
                </div>
                <button
                  type="button"
                  class="copy-contract-btn label"
                  :class="{ copied: copyFeedback }"
                  title="Copy contract details"
                  @click="copyContractDetails(effectiveSelectedPrint)"
                >
                  {{ copyFeedback || 'COPY' }}
                </button>
              </div>
            </div>
            <div class="inspector-grid">
              <div class="inspector-item">
                <span class="label">Right &amp; Strike</span>
                <strong
                  class="fig"
                  :class="effectiveSelectedPrint.right === 'call' ? 'call-text' : 'put-text'"
                >
                  {{ effectiveSelectedPrint.right?.toUpperCase() }} ${{
                    effectiveSelectedPrint.strike
                  }}
                </strong>
              </div>
              <div class="inspector-item">
                <span class="label">Expiry / DTE</span>
                <strong class="fig"
                  >{{ shortDate(effectiveSelectedPrint.expiry) }} ({{
                    formatDteBadge(effectiveSelectedPrint.dte).label
                  }})</strong
                >
              </div>
              <div class="inspector-item">
                <span class="label">Fill Price</span>
                <strong class="fig">{{ usd(effectiveSelectedPrint.price, 2) }}</strong>
              </div>
              <div class="inspector-item">
                <span class="label">Size (Contracts)</span>
                <strong class="fig">{{
                  exactCount(effectiveSelectedPrint.contracts ?? effectiveSelectedPrint.volume)
                }}</strong>
              </div>
              <div class="inspector-item">
                <span class="label">Total Premium</span>
                <strong class="fig">{{ moneyCompact(effectiveSelectedPrint.premium) }}</strong>
              </div>
              <div class="inspector-item">
                <span class="label">Vol / OI Ratio</span>
                <strong class="fig">{{
                  computeVolOiRatio(
                    effectiveSelectedPrint.contracts ?? effectiveSelectedPrint.volume,
                    effectiveSelectedPrint.open_interest,
                  ).formatted
                }}</strong>
              </div>
              <div class="inspector-item">
                <span class="label">Execution Class</span>
                <span
                  class="flow-badge label"
                  :class="classifyFlowOrder(effectiveSelectedPrint).className"
                >
                  {{ classifyFlowOrder(effectiveSelectedPrint).label }}
                </span>
              </div>
              <div class="inspector-item">
                <span class="label">Aggressor Side</span>
                <span
                  class="aggressor label"
                  :class="
                    signedPrintTokenClass(
                      effectiveSelectedPrint.aggressor ?? effectiveSelectedPrint.aggressor_label,
                    )
                  "
                >
                  {{ aggressorLabel(effectiveSelectedPrint) }}
                </span>
              </div>
            </div>
            <RouterLink
              v-if="effectiveSelectedPrint.symbol"
              :to="{ name: 'options', query: { symbol: effectiveSelectedPrint.symbol } }"
              class="inspector-open-btn label"
            >
              VIEW {{ effectiveSelectedPrint.symbol }} OPTIONS CHAIN →
            </RouterLink>
          </div>
        </aside>
      </div>

      <section class="method-strip" aria-label="Flow interpretation rules">
        <article>
          <span class="label">Ranking</span>
          <p>
            Review priority recomputes after every fresh {{ pollSeconds }}s poll. “New” and sample
            changes compare overlapping provider samples; a negative change can mean old prints
            rolled out.
          </p>
        </article>
        <article>
          <span class="label">Direction gate</span>
          <p>
            Activity lean (bullish/bearish) uses premium mix + price impulse; signed trade direction
            requires provider buy/sell. Models appear only when calibrated, setup-qualified,
            ENTER-state, and ≥55%.
          </p>
        </article>
        <article>
          <span class="label">Actionable insights</span>
          <p>
            Desk next steps tell you what to open and what to check (strike, DTE, walls). They are
            research triage — not order authorization. {{ providerBasis }} · LATEST PROVIDER SAMPLE
            · ≥ ${{ compact(minPremium) }}.
          </p>
        </article>
      </section>
    </template>
  </section>
</template>

<style scoped>
.flow-dashboard {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: var(--s4);
}

/* ── 01 Control Rail ───────────────────────────────────────────────────────
   The one true floating toolbar of the Flow view: Liquid Glass functional
   chrome (translucent fill + saturate/blur + specular edge), capsule
   geometry, monochromatic controls with a single prominent action. */
.control-rail {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
  gap: var(--s4);
  min-height: 60px;
  padding: var(--s3) var(--s5);
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-xl);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.045), rgba(255, 255, 255, 0) 70%),
    var(--glass-surface);
  backdrop-filter: var(--chrome-optics-md);
  -webkit-backdrop-filter: var(--chrome-optics-md);
  box-shadow: var(--glass-specular-subtle), var(--glass-shadow-sm);
  flex-wrap: wrap;
}

@media (prefers-reduced-transparency: reduce) {
  .control-rail {
    background: var(--panel);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

.control-identity {
  display: flex;
  align-items: center;
  gap: var(--s3);
  min-width: 210px;
}

.control-identity > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.control-identity strong {
  color: var(--text-primary);
  font-size: var(--t-small);
  font-weight: 750;
}
.control-identity small {
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  line-height: 1.3;
}

.feed-mark {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  color: var(--text-tertiary);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  border-radius: var(--r-md);
}

.feed-mark.active {
  color: var(--status-live);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.threshold-control {
  display: flex;
  align-items: center;
  gap: var(--s3);
  min-width: 0;
}

.threshold-control > .label {
  font-size: var(--t-micro);
  font-weight: 700;
  color: var(--ink-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

/* Segmented control — pill track with a raised filled capsule for the
   selected premium threshold. */
.thresholds {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-capsule);
  background: var(--glass-base);
  backdrop-filter: var(--chrome-optics-sm);
  -webkit-backdrop-filter: var(--chrome-optics-sm);
  box-shadow: var(--glass-specular-subtle);
}

@media (prefers-reduced-transparency: reduce) {
  .thresholds {
    background: var(--panel-hi);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

.thresholds button {
  min-height: var(--density-control-h);
  padding: var(--s1) var(--s3);
  color: var(--text-secondary);
  border: 0;
  border-radius: var(--r-capsule);
  background: transparent;
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  font-weight: 700;
  transition:
    color var(--dur-fast) var(--ease-out),
    background-color var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out);
}

.thresholds button:hover:not(.active) {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.05);
}

.thresholds button.active {
  color: var(--void);
  background: var(--phosphor);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35);
  font-weight: 800;
}

.control-status {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-left: auto;
  color: var(--text-tertiary);
  text-align: right;
  font-size: var(--t-micro);
}

.control-status span:first-child {
  color: var(--status-live);
  font-weight: 700;
}

.refresh-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--s2);
  min-width: 116px;
  min-height: var(--density-control-h);
  padding: var(--s2) var(--s4);
  color: var(--void);
  border: var(--hair) solid var(--phosphor);
  background: var(--phosphor);
  font-family: var(--font-display);
  font-weight: 700;
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  border-radius: var(--r-capsule);
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.35);
  transition:
    background-color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}

.refresh-button:hover:not(:disabled) {
  background: var(--phosphor-dim);
  border-color: var(--phosphor-dim);
}

.refresh-button:active:not(:disabled) {
  transform: scale(0.97);
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.error-strip {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s4);
  color: var(--short);
  border: var(--hair) solid var(--short);
  border-left-width: 3px;
  background: var(--short-wash);
  font-size: var(--t-small);
}

.error-strip strong,
.stale-copy {
  color: inherit;
  font-weight: 700;
}

.no-snapshot {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s3);
  min-height: 260px;
  padding: var(--s6);
  color: var(--text-tertiary);
  border: var(--hair) solid var(--border-strong);
  text-align: center;
  background: var(--surface-raised);
}

.no-snapshot strong {
  color: var(--text-primary);
  font-size: var(--t-lead);
  font-weight: 750;
}

.feed-recovery {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--s4);
  min-height: 156px;
  padding: var(--s5);
  color: var(--warn);
  border: var(--hair) solid var(--warn);
  border-left-width: 3px;
  background: var(--surface-raised);
}

.feed-recovery.empty-feed {
  color: var(--text-tertiary);
  border-color: var(--border-strong);
}

.recovery-mark {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  color: inherit;
  border: var(--hair) solid currentColor;
  border-radius: var(--r-xs);
  font-weight: 800;
}

.feed-recovery strong {
  display: block;
  margin-top: 4px;
  color: var(--text-primary);
  font: 700 var(--t-lead) / 1.15 var(--font-display);
}

.feed-recovery p {
  max-width: 72ch;
  margin-top: 6px;
  color: var(--text-secondary);
  font-size: var(--t-small);
}

.empty-action {
  min-height: 32px;
  padding: var(--s1) var(--s4);
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 750;
  cursor: pointer;
  border-radius: var(--r-xs);
}
.empty-action:hover {
  color: var(--void);
  background: var(--phosphor);
}

.section-kicker {
  color: var(--phosphor);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.08em;
}

/* ── Hero Flow Sentiment & Snapshot Section ──────────────────────────────────
   Content-layer standard material: opaque fill, concentric corners, one
   specular line along the top edge. */
.flow-sentiment-hero {
  display: grid;
  grid-template-columns: minmax(320px, 1.25fr) minmax(0, 2fr);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xl);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0) 44px),
    var(--surface-raised);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
  overflow: hidden;
}

.sentiment-card {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  padding: var(--s4) var(--s5);
  background: var(--surface-base);
  border-right: var(--hair) solid var(--border-subtle);
  border-left: 3px solid var(--rule-hi);
}
.sentiment-card.bullish {
  border-left-color: var(--long);
}
.sentiment-card.bearish {
  border-left-color: var(--short);
}
.sentiment-card.neutral {
  border-left-color: var(--call);
}

.sentiment-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s3);
}

.ticker-header-identity {
  display: flex;
  align-items: center;
  gap: var(--s3);
  min-width: 0;
}

.ticker-symbol-badge {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: var(--r-md);
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  color: var(--phosphor);
  font-family: var(--font-data);
  font-size: var(--t-small);
  font-weight: 800;
  flex-shrink: 0;
}

.ticker-title-box {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.ticker-symbol-line {
  display: flex;
  align-items: baseline;
  gap: var(--s2);
}

.ticker-symbol-text {
  color: var(--ink);
  font-size: 1.35rem;
  font-weight: 850;
  letter-spacing: -0.02em;
}

.ticker-company-name {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  font-weight: 600;
}

/* Ticker-focus reset chip — the class was referenced in the hero header but
   never defined, so the button rendered as a bare browser-default control. */
.clear-symbol-btn {
  min-height: 20px;
  padding: 0 8px;
  color: var(--ink-dim);
  border: var(--hair) solid var(--glass-border);
  background: var(--glass-surface);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.04em;
  cursor: pointer;
  border-radius: var(--r-xs);
  transition:
    color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out);
}
.clear-symbol-btn:hover {
  color: var(--ink);
  border-color: var(--glass-border-hi);
  background: var(--glass-surface-hi);
}

.ticker-quote-line {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--s2);
}

.ticker-quote-price {
  color: var(--ink);
  font-size: 1.05rem;
  font-weight: 800;
}

.ticker-quote-delta {
  font-size: var(--t-tiny);
  font-weight: 750;
}
.ticker-quote-delta.pos {
  color: var(--long);
}
.ticker-quote-delta.neg {
  color: var(--short);
}

.ticker-quote-range {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.dominant-pulse-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  margin-right: 4px;
}

.dominant-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  font-size: var(--t-micro);
  font-weight: 800;
  letter-spacing: 0.06em;
  border: var(--hair) solid currentColor;
  border-radius: var(--r-sm);
  flex-shrink: 0;
}
.dominant-badge.bullish {
  color: var(--long);
  border-color: var(--long);
  background: var(--long-wash);
}
.dominant-badge.bearish {
  color: var(--short);
  border-color: var(--short);
  background: var(--short-wash);
}
.dominant-badge.neutral {
  color: var(--ink-dim);
  border-color: var(--rule-hi);
}

.sentiment-headline {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 2px;
}
.sentiment-title {
  color: var(--text-primary);
  font-size: 1.25rem;
  font-weight: 850;
  letter-spacing: var(--track-tight);
}
.sentiment-premium {
  color: var(--text-secondary);
  font-size: var(--t-tiny);
  font-weight: 650;
}

.sentiment-bar {
  display: flex;
  width: 100%;
  height: 10px;
  margin-top: 4px;
  overflow: hidden;
  background: var(--border-subtle);
  border-radius: var(--r-xs);
}

.sentiment-labels {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: var(--t-micro);
  font-weight: 750;
}

.snapshot-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  align-items: stretch;
}
.snapshot-metrics article {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  min-width: 0;
  padding: var(--s4) var(--s5);
  border-right: var(--hair) solid var(--border-subtle);
  background: var(--surface-base);
  transition: background-color var(--dur-fast) var(--ease-out);
}
.snapshot-metrics article:hover {
  background: var(--surface-raised);
}
.snapshot-metrics article:last-child {
  border-right: 0;
}
.snapshot-metrics article > .label {
  overflow-wrap: normal;
  white-space: nowrap;
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
}
.snapshot-metrics strong {
  color: var(--text-primary);
  font-family: var(--font-data);
  font-size: 1.35rem;
  font-weight: 800;
  line-height: 1.15;
  letter-spacing: var(--track-tight);
}
.snapshot-metrics small {
  color: var(--text-secondary);
  font-size: var(--t-micro);
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.freshness-stat {
  padding-right: 52px;
}
.fresh-state {
  position: absolute;
  top: var(--s2);
  right: var(--s2);
  padding: 1px 5px;
  color: var(--text-tertiary);
  border: var(--hair) solid var(--border-strong);
  font-size: var(--t-micro);
  font-weight: 800;
  border-radius: var(--r-xs);
}
.fresh-state.live {
  color: var(--status-live);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.fresh-state.stale {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}
.fresh-state.unavailable {
  color: var(--short);
  border-color: var(--short);
}
.freshness-stat > .label:first-child {
  padding-right: 58px;
}

/* ── Market Flow Intelligence Hub ────────────────────────────────────────── */
.market-intelligence-hub {
  display: flex;
  flex-direction: column;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xl);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0) 44px),
    var(--surface-raised);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
  overflow: hidden;
}

.intelligence-hub-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  background: var(--surface-base);
  border-bottom: var(--hair) solid var(--border-subtle);
  flex-wrap: wrap;
}

.hub-title-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.hub-title-group h2 {
  margin: 0;
  color: var(--text-primary);
  font: 700 var(--t-small) var(--font-display);
}

.hub-tabs {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-capsule);
  background: var(--glass-base);
  backdrop-filter: var(--chrome-optics-sm);
  -webkit-backdrop-filter: var(--chrome-optics-sm);
  box-shadow: var(--glass-specular-subtle);
}

@media (prefers-reduced-transparency: reduce) {
  .hub-tabs {
    background: var(--panel-hi);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

.hub-tab-btn {
  min-height: 28px;
  padding: 0 var(--s3);
  color: var(--text-secondary);
  border: 0;
  border-radius: var(--r-capsule);
  background: transparent;
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 750;
  letter-spacing: 0.04em;
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
    background-color var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out);
}

.hub-tab-btn:hover:not(.active) {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.05);
}

.hub-tab-btn.active {
  color: var(--void);
  background: var(--phosphor);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35);
  font-weight: 800;
}

.hub-tab-panel {
  min-width: 0;
}

.hub-tab-panel .leaders-rail,
.hub-tab-panel .sector-sentiment-rail,
.hub-tab-panel .majors-section,
.hub-tab-panel .live-pulse {
  border: 0;
  border-radius: 0;
  box-shadow: none;
  background: transparent;
}

/* ── Sector Sentiment Rail ──────────────────────────────────────────────────── */
.sector-sentiment-rail {
  padding: var(--s3) var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xl);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0) 40px),
    var(--surface-raised);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
}

.sector-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s3);
  flex-wrap: wrap;
}
.sector-head h2 {
  margin-top: 2px;
  color: var(--text-primary);
  font: 700 var(--t-small) var(--font-display);
}
.sector-meta {
  color: var(--text-tertiary);
  font-size: var(--t-micro);
}
.sector-clear-link {
  color: var(--phosphor);
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  font-weight: 750;
  cursor: pointer;
}
.sector-clear-link:hover {
  text-decoration: underline;
}

.sector-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: var(--s2);
  margin-top: var(--s3);
}

.sector-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 9px 12px;
  color: inherit;
  border: var(--hair) solid transparent;
  background: var(--surface-base);
  border-radius: var(--r-lg);
  text-align: left;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}
.sector-card:hover {
  background: var(--surface-overlay);
  border-color: var(--rule-hi);
}
.sector-card.active {
  background: var(--phosphor-wash);
  border-color: var(--phosphor-dim);
}

.sector-card-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s2);
}
.sector-name {
  min-width: 0;
  color: var(--text-primary);
  font-size: var(--t-micro);
  font-weight: 750;
  line-height: 1.25;
}
.sector-code {
  flex: 0 0 auto;
  overflow: visible;
  color: var(--phosphor);
  font-size: var(--t-micro);
  font-weight: 800;
  text-overflow: clip;
  white-space: nowrap;
}

.sector-premium {
  color: var(--ink);
  font-size: var(--t-tiny);
  font-weight: 800;
}

.sector-mix-bar {
  display: flex;
  width: 100%;
  height: 5px;
  overflow: hidden;
  background: var(--border-subtle);
  border-radius: 1px;
}

.sector-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--t-micro);
}
.top-in-sec {
  color: var(--text-tertiary);
  font-size: var(--t-micro);
}

.sector-empty {
  margin-top: var(--s2);
  color: var(--text-tertiary);
}

/* ── Top Tickers ───────────────────────────────────────────────────────────── */
.leaders-rail {
  padding: var(--s3) var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xl);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0) 40px),
    var(--surface-raised);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
}
.leaders-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s3);
  flex-wrap: wrap;
}
.leaders-head h2 {
  margin-top: 2px;
  color: var(--text-primary);
  font: 700 var(--t-small) var(--font-display);
}
.book-hits-copy {
  color: var(--text-tertiary);
  font-size: var(--t-micro);
}

.ticker-cats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
  margin-top: var(--s3);
}
.ticker-cats button {
  min-height: 28px;
  padding: 0 var(--s3);
  color: var(--text-secondary);
  border: var(--hair) solid var(--glass-border);
  background: var(--glass-surface);
  backdrop-filter: var(--chrome-optics-sm);
  -webkit-backdrop-filter: var(--chrome-optics-sm);
  box-shadow: var(--glass-specular-subtle);
  border-radius: var(--r-capsule);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 750;
  letter-spacing: 0.04em;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}
.ticker-cats button:hover:not(.active) {
  color: var(--text-primary);
  border-color: var(--glass-border-hi);
}
.ticker-cats button.active {
  color: var(--void);
  border-color: var(--phosphor);
  background: var(--phosphor);
}

@media (prefers-reduced-transparency: reduce) {
  .ticker-cats button {
    background: var(--panel-hi);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

.symbol-tape {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: var(--s2);
  margin-top: var(--s3);
}
.book-tape {
  margin-top: var(--s2);
}

.sym-chip {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 9px 12px;
  color: inherit;
  border: var(--hair) solid transparent;
  background: var(--surface-base);
  border-radius: var(--r-lg);
  text-align: left;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}
.sym-chip-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s2);
}
.sym-chip-head span {
  color: var(--phosphor);
  font-weight: 750;
}
.sym-chip-head strong {
  color: var(--ink);
  font-size: var(--t-tiny);
}

.ticker-sentiment-bar {
  display: flex;
  width: 100%;
  height: 4px;
  overflow: hidden;
  background: var(--border-subtle);
  border-radius: 1px;
}
.bull-bar {
  background: var(--long);
}
.bear-bar {
  background: var(--short);
}

.sym-chip-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--ink-faint);
  font-size: var(--t-micro);
}
.chip-count {
  color: var(--text-tertiary);
}

.sym-chip:hover,
.sym-chip.on {
  background: var(--phosphor-wash);
  border-color: var(--phosphor-dim);
}
.sym-chip.book span {
  color: var(--ink);
}
.ticker-empty {
  margin-top: var(--s2);
  color: var(--text-tertiary);
}

.book-pin {
  margin-left: 6px;
  min-height: 22px;
  padding: 0 8px;
  color: var(--text-tertiary);
  border: var(--hair) solid var(--border-strong);
  border-radius: var(--r-capsule);
  background: transparent;
  cursor: pointer;
}
.book-pin.on {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

.alert-tray {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s2) var(--s3);
  min-height: 32px;
  padding: 4px var(--s3);
  border: var(--hair) solid var(--rule);
  background: var(--surface-raised);
}
.alert-tray.empty {
  border-color: var(--border-strong);
  background: var(--surface-base);
}
.alert-tray.armed {
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.alert-tray header {
  display: flex;
  align-items: baseline;
  gap: var(--s2);
  min-width: 0;
}
.alert-tray header strong {
  color: var(--ink-dim);
  font: 650 var(--t-tiny) var(--font-ui);
}
.alert-tray ul {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.alert-tray li {
  display: flex;
  gap: 6px;
  align-items: baseline;
}
.alert-tray button.fig {
  color: var(--phosphor);
  background: none;
  border: 0;
  cursor: pointer;
}

/* ── Live Pulse Banner ───────────────────────────────────────────────────── */
.live-pulse {
  display: grid;
  grid-template-columns: minmax(360px, 1.4fr) repeat(3, minmax(190px, 1fr));
  min-width: 0;
  border: var(--hair) solid var(--rule);
  border-left: 3px solid var(--phosphor);
  border-radius: var(--r-xl);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0) 44px),
    var(--surface-raised);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
  overflow: hidden;
}

.live-pulse.brief-stale {
  border-left-color: var(--warn);
}
.brief-stale .section-kicker {
  color: var(--warn);
}

.pulse-copy {
  min-width: 0;
  padding: var(--s5);
  background: var(--surface-base);
}

.pulse-copy h2 {
  margin-top: var(--s2);
  color: var(--text-primary);
  font: 700 var(--t-display) / 1.25 var(--font-display);
  letter-spacing: -0.025em;
}

.pulse-copy > p {
  max-width: 70ch;
  margin-top: var(--s3);
  color: var(--text-secondary);
  font-size: var(--t-small);
  line-height: 1.55;
}

.pulse-cadence {
  display: flex;
  flex-wrap: wrap;
  gap: 6px var(--s3);
  margin-top: var(--s4);
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  font-weight: 700;
}

.pulse-cadence span:first-child {
  color: var(--phosphor);
}
.pulse-cadence i {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 5px;
  background: currentColor;
  border-radius: 50%;
}

/* ── Triage Picks ────────────────────────────────────────────────────────── */
.triage-pick {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 180px;
  padding: var(--s4);
  color: var(--text-secondary);
  border-left: var(--hair) solid var(--border-subtle);
  border-top: 3px solid var(--rule-hi);
  text-align: left;
  background: var(--surface-raised);
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
  transition:
    background-color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out);
}

.triage-pick:hover {
  background: var(--surface-overlay);
  border-top-color: var(--phosphor-dim);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}

.triage-index {
  position: absolute;
  top: var(--s3);
  right: var(--s4);
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  font-weight: 750;
}

.triage-pick > .label {
  padding-right: 26px;
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  font-weight: 700;
}
.triage-symbol-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s2);
  margin-top: var(--s2);
}
.triage-symbol-line strong {
  color: var(--phosphor);
  font-size: var(--t-fig);
  font-weight: 750;
}
.triage-symbol-line b {
  color: var(--text-primary);
  font-size: var(--t-small);
  font-weight: 750;
}

.triage-lean {
  display: inline-flex;
  margin-top: 7px;
  padding: 1px 7px;
  width: fit-content;
  border-radius: var(--r-xs);
  font-weight: 800;
  letter-spacing: 0.05em;
  font-size: var(--t-micro);
  border: var(--hair) solid currentColor;
}
.triage-lean.bullish,
.triage-lean.model-bullish {
  color: var(--long);
  border-color: var(--long);
  background: var(--long-wash);
}
.triage-lean.bearish,
.triage-lean.model-bearish {
  color: var(--short);
  border-color: var(--short);
  background: var(--short-wash);
}
.triage-lean.mixed {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}

.triage-action {
  margin-top: 6px;
  color: var(--text-primary);
  font-size: var(--t-micro);
  font-weight: 650;
  line-height: 1.35;
}
.triage-focus {
  margin-top: var(--s1);
  color: var(--text-secondary);
  font-size: var(--t-micro);
  line-height: 1.4;
}
.triage-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 7px;
}
.triage-tags span {
  padding: 1px 5px;
  color: var(--text-secondary);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  font-size: var(--t-micro);
  font-weight: 700;
  border-radius: var(--r-xs);
}
.triage-tags .sweep,
.triage-tags .flag {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 55%, var(--border-strong));
}
.triage-tags .size {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

.triage-open {
  margin-top: auto;
  padding-top: var(--s3);
  color: var(--phosphor);
  border-top: var(--hair) solid var(--border-subtle);
  font-size: var(--t-micro);
  font-weight: 750;
  letter-spacing: 0.05em;
}
.triage-pick.bullish,
.triage-pick.model-bullish {
  border-top-color: var(--long);
}
.triage-pick.bearish,
.triage-pick.model-bearish {
  border-top-color: var(--short);
}
.triage-pick.mixed {
  border-top-color: var(--warn);
}

/* ── Filter Shelf ────────────────────────────────────────────────────────── */
.filter-shelf {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s4);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-raised);
  border-radius: var(--r-sm);
}

.filter-tier-primary,
.filter-tier-secondary {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--s3);
}

.filter-tier-primary {
  padding-bottom: var(--s3);
  border-bottom: var(--hair) solid var(--border-subtle);
}

.filter-tier-primary .preset-filter {
  flex: 1 1 auto;
}

.filter-tier-secondary .activity-filter,
.filter-tier-secondary .moneyness-filter {
  flex: 0 1 auto;
}

.filter-tier-secondary .select-filter {
  flex: 1 1 140px;
}

.filter-intro {
  display: flex;
  flex-direction: column;
  align-self: center;
  gap: 3px;
  min-width: 0;
}
.filter-intro .label {
  font-size: var(--t-micro);
  font-weight: 700;
  color: var(--ink-dim);
}
.filter-intro strong {
  color: var(--text-primary);
  font: 700 var(--t-small) var(--font-display);
}
.filter-intro small {
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  line-height: 1.35;
}

.search-filter,
.select-filter,
.exclusion-block,
.layout-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.exclusion-form {
  display: flex;
  gap: 6px;
}

.exclusion-form input {
  min-width: 0;
  flex: 1;
  min-height: 32px;
  padding: 3px 8px;
  color: var(--text-primary);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  text-transform: uppercase;
}

.exclusion-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.exclusion-chip,
.layout-chip {
  min-height: 24px;
  padding: 0 7px;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule);
  background: var(--panel-hi);
  border-radius: 2px;
}

.layout-chip {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}
.search-filter > .label,
.select-filter > .label,
.seg-filter legend {
  font-size: var(--t-micro);
  font-weight: 700;
  color: var(--ink-dim);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.input-shell {
  display: flex;
  align-items: center;
  gap: 7px;
  min-height: 32px;
  padding: 3px 8px;
  color: var(--text-tertiary);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  border-radius: var(--r-xs);
}
.input-shell:focus-within {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}
.input-shell input {
  width: 100%;
  min-width: 0;
  color: var(--text-primary);
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  text-transform: uppercase;
}
.input-shell input::placeholder {
  color: var(--text-tertiary);
  text-transform: none;
}

.seg-filter {
  min-width: 0;
  border: 0;
}
.seg-filter > div {
  display: flex;
  flex-wrap: wrap;
  border: var(--hair) solid var(--border-strong);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.seg-filter > small,
.filter-intro small {
  display: none;
}
.seg-filter button {
  min-height: 32px;
  padding: 3px 9px;
  color: var(--text-secondary);
  border: 0;
  border-right: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  font-weight: 700;
  transition:
    color var(--dur-fast) var(--ease-out),
    background-color var(--dur-fast) var(--ease-out);
}
.seg-filter button:last-child {
  border-right: 0;
}
.seg-filter button:hover:not(.active) {
  color: var(--text-primary);
  background: var(--surface-overlay);
}
.seg-filter button.active {
  color: var(--void);
  background: var(--phosphor);
  font-weight: 800;
}

.select-filter select {
  width: 100%;
  min-height: 32px;
  padding: 3px 24px 3px 8px;
  color: var(--text-primary);
  border: var(--hair) solid var(--border-strong);
  border-radius: var(--r-xs);
  background: var(--surface-base);
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  font-weight: 600;
}

.reset-filter {
  min-height: 32px;
  padding: 4px 10px;
  color: var(--text-secondary);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 750;
  letter-spacing: 0.06em;
  border-radius: var(--r-xs);
}
.reset-filter:hover:not(:disabled) {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

/* ── Majors Section ──────────────────────────────────────────────────────── */
.majors-section {
  min-width: 0;
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
}

.majors-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s5);
  padding: var(--s4) var(--s5);
  border-bottom: var(--hair) solid var(--border-subtle);
}

.majors-head h2 {
  margin-top: 4px;
  color: var(--text-primary);
  font: 700 var(--t-lead) var(--font-display);
}

.majors-head p {
  max-width: 70ch;
  color: var(--text-secondary);
  font-size: var(--t-small);
  text-align: right;
}

.major-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.major-card {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 228px;
  padding: var(--s3) var(--s4);
  border-right: var(--hair) solid var(--border-subtle);
  background: var(--surface-raised);
  transition: background-color var(--dur-fast) var(--ease-out);
}
.major-card:hover {
  background: var(--surface-overlay);
}
.major-card:last-child {
  border-right: 0;
}
.major-card.incoming {
  background: var(--phosphor-wash);
}
.major-card.absent {
  color: var(--text-tertiary);
  background: var(--surface-base);
}

.major-symbol-line {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.major-symbol {
  color: var(--phosphor);
  font-size: var(--t-fig);
  font-weight: 750;
}
button.major-symbol:hover {
  color: var(--ink);
}
.major-rank {
  margin-left: auto;
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  font-weight: 700;
}

.rank-move,
.table-rank-move {
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  font-weight: 700;
}
.rank-move.up,
.table-rank-move.up {
  color: var(--long);
}
.rank-move.down,
.table-rank-move.down {
  color: var(--short);
}

.new-badge {
  display: inline-flex;
  align-items: center;
  min-height: 18px;
  padding: 1px 5px;
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  font-size: var(--t-micro);
  font-weight: 800;
  border-radius: var(--r-xs);
}

.major-premium {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s3);
  margin-top: var(--s2);
  padding-bottom: var(--s2);
  border-bottom: var(--hair) solid var(--border-subtle);
}
.major-premium div {
  min-width: 0;
}
.major-premium strong {
  display: block;
  overflow: hidden;
  margin-top: 2px;
  color: var(--text-primary);
  font-size: var(--t-small);
  font-weight: 750;
  text-overflow: ellipsis;
}

.major-direction {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  align-items: center;
  gap: var(--s2);
  margin-top: var(--s3);
  padding: var(--s2);
  color: var(--text-secondary);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  border-radius: var(--r-xs);
}
.direction-arrow {
  font: 800 var(--t-fig) / 1 var(--font-data);
  text-align: center;
}
.major-direction strong {
  display: block;
  color: inherit;
  font-size: var(--t-micro);
  font-weight: 800;
}
.major-direction small {
  display: block;
  margin-top: 1px;
  color: var(--text-tertiary);
  font-size: var(--t-micro);
}
.major-direction.bullish {
  color: var(--long);
  border-color: var(--long);
  background: var(--long-wash);
}
.major-direction.bearish {
  color: var(--short);
  border-color: var(--short);
  background: var(--short-wash);
}
.major-direction.mixed {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}
.major-direction.model-bullish {
  color: var(--long);
  border-color: color-mix(in srgb, var(--long) 45%, var(--border-strong));
}
.major-direction.model-bearish {
  color: var(--short);
  border-color: color-mix(in srgb, var(--short) 45%, var(--border-strong));
}

.major-identity {
  margin-top: var(--s2);
}
.major-identity small {
  display: block;
  margin-top: 4px;
  color: var(--text-tertiary);
  font-size: var(--t-micro);
}

.call-text {
  color: var(--call-hi);
  font-weight: 750;
}
.put-text {
  color: var(--put-hi);
  font-weight: 750;
}
.identity-labels {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s2);
  font-size: var(--t-micro);
}

.identity-bar {
  display: flex;
  width: 100%;
  height: 8px;
  overflow: hidden;
  background: var(--border-subtle);
  border-radius: 1px;
}
.call-segment {
  display: block;
  background: var(--call);
}
.put-segment {
  display: block;
  background: var(--put);
}
.identity-note {
  display: block;
  margin-top: 4px;
  color: var(--text-tertiary);
  font: 700 8px var(--font-display);
  letter-spacing: 0.05em;
}

.major-concentration {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s2);
  margin-top: var(--s3);
}
.major-concentration div {
  min-width: 0;
}
.major-concentration dd {
  overflow: hidden;
  margin-top: 2px;
  color: var(--text-primary);
  font-size: var(--t-tiny);
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.major-concentration small {
  display: block;
  margin-top: 1px;
  font-size: var(--t-micro);
}

.major-action {
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow: visible;
  white-space: normal;
  text-overflow: clip;
  margin-top: var(--s3);
  padding: var(--s2) var(--s3);
  color: var(--text-secondary);
  border: var(--hair) solid var(--border-subtle);
  background: var(--surface-base);
  font-size: var(--t-micro);
  line-height: 1.35;
  border-radius: var(--r-xs);
}
.major-action > span {
  color: var(--phosphor);
  font-weight: 800;
  letter-spacing: 0.05em;
}
.major-action.bullish > span,
.major-action.model-bullish > span {
  color: var(--long);
}
.major-action.bearish > span,
.major-action.model-bearish > span {
  color: var(--short);
}
.major-action.mixed > span {
  color: var(--warn);
}

.major-open {
  width: 100%;
  margin-top: auto;
  min-height: 32px;
  padding: var(--s2) var(--s3);
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 800;
  letter-spacing: 0.05em;
  border-radius: var(--r-xs);
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
    background-color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}
.major-open:hover {
  color: var(--void);
  border-color: var(--phosphor);
  background: var(--phosphor);
}

.major-absent {
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: center;
  text-align: center;
  padding: var(--s4) 0;
}
.major-absent strong {
  color: var(--text-secondary);
}
.major-absent p {
  margin-top: 4px;
  font-size: var(--t-small);
}

/* ── Review Table (Panel 01) ─────────────────────────────────────────────── */
.table-scroll {
  min-width: 0;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: var(--rule-hi) transparent;
}
.review-scroll {
  max-height: 620px;
}
.tape-scroll {
  max-height: 610px;
}

.review-table {
  min-width: 1120px;
  font-size: var(--t-tiny);
  border-collapse: separate;
  border-spacing: 0;
}

.review-table th {
  padding: var(--s3) var(--s4);
  color: var(--ink-dim);
  background: var(--surface-overlay);
  box-shadow: inset 0 -1px 0 var(--border-strong);
  position: sticky;
  top: 0;
  z-index: 2;
  font-weight: 750;
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.review-table td {
  padding: var(--s3) var(--s4);
  border-bottom: var(--hair) solid var(--border-subtle);
  vertical-align: middle;
}
.review-table tbody tr:hover {
  background: var(--surface-overlay);
}
.review-table tbody tr.incoming,
.tape-table tbody tr.incoming {
  background: var(--phosphor-wash);
}

.review-symbol {
  width: 112px;
  white-space: nowrap;
}
.row-rank {
  display: inline-block;
  width: 24px;
  margin-right: var(--s2);
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  font-weight: 700;
}
.symbol-button {
  position: relative;
  color: var(--phosphor);
  font-weight: 750;
  font-size: 13px;
  cursor: pointer;
}
.symbol-button:hover {
  color: var(--ink);
}
/* Painted size stays compact for desk density; this restores a 28px pointer
   target underneath without touching layout. */
.symbol-button::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: max(100%, 28px);
  height: max(100%, 28px);
  transform: translate(-50%, -50%);
}

.reason-cell {
  width: 31%;
  min-width: 290px;
}
.reason-cell > strong {
  display: block;
  color: var(--text-primary);
  font-weight: 600;
  white-space: normal;
}
.action-cell > strong {
  display: block;
  margin-top: 2px;
  color: var(--text-primary);
  font-size: var(--t-tiny);
  font-weight: 650;
  line-height: 1.35;
  white-space: normal;
}
.action-cell > small {
  display: block;
  margin-top: 3px;
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  line-height: 1.4;
  white-space: normal;
}

.price-cell strong {
  display: block;
  color: var(--text-primary);
  font-size: var(--t-small);
}
.price-cell small {
  display: block;
  max-width: 21ch;
  margin-top: 3px;
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  line-height: 1.35;
  white-space: normal;
}
.price-cell small.pos {
  color: var(--long);
}
.price-cell small.neg {
  color: var(--short);
}

.priority-chip {
  display: inline-flex;
  margin-bottom: 3px;
  padding: 1px 6px;
  border: var(--hair) solid currentColor;
  border-radius: var(--r-xs);
  font-weight: 800;
  letter-spacing: 0.05em;
  font-size: var(--t-micro);
}
.priority-chip.now {
  color: var(--long);
  border-color: var(--long);
  background: var(--long-wash);
}
.priority-chip.soon {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}
.priority-chip.watch {
  color: var(--text-secondary);
  border-color: var(--border-strong);
}
.priority-chip.skip {
  color: var(--text-tertiary);
  opacity: 0.85;
  border-color: var(--border-subtle);
}

.tag-line {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 5px;
}
.tag-line .evidence-tag {
  min-height: 18px;
  padding: 1px 5px;
  font-size: var(--t-micro);
  font-weight: 700;
  border-radius: var(--r-xs);
}

.direction-cell {
  min-width: 180px;
}
.direction-chip {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 1px 7px;
  border-radius: var(--r-xs);
  font-weight: 800;
  letter-spacing: 0.04em;
  font-size: var(--t-micro);
  border: var(--hair) solid currentColor;
}
.direction-cell.bullish .direction-chip {
  color: var(--long);
  border-color: var(--long);
  background: var(--long-wash);
}
.direction-cell.bearish .direction-chip {
  color: var(--short);
  border-color: var(--short);
  background: var(--short-wash);
}
.direction-cell.mixed .direction-chip {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}
.direction-cell.model-bullish .direction-chip {
  color: var(--long);
  border-color: color-mix(in srgb, var(--long) 45%, var(--border-strong));
}
.direction-cell.model-bearish .direction-chip {
  color: var(--short);
  border-color: color-mix(in srgb, var(--short) 45%, var(--border-strong));
}

.token-long {
  color: var(--long);
  border-color: var(--long);
}
.token-short {
  color: var(--short);
  border-color: var(--short);
}
.token-warn {
  color: var(--warn);
  border-color: var(--warn);
}
.token-unsigned {
  color: var(--ink-dim);
  border-color: var(--rule-hi);
}
.token-ink {
  color: var(--ink-dim);
}

.row-open {
  min-height: 26px;
  padding: 3px 12px;
  color: var(--ink);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  font-size: var(--t-micro);
  font-weight: 750;
  border-radius: var(--r-capsule);
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
    background-color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}
.row-open:hover {
  color: var(--void);
  background: var(--phosphor);
  border-color: var(--phosphor);
}
.row-open:active {
  transform: scale(0.96);
}

.queue-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  color: var(--text-tertiary);
  border-top: var(--hair) solid var(--border-subtle);
  background: var(--surface-raised);
}

.panel-action {
  min-height: 26px;
  padding: 3px 8px;
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 750;
  letter-spacing: var(--track-label);
  color: var(--text-secondary);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  border-radius: var(--r-xs);
  cursor: pointer;
}
.panel-action:hover:not(:disabled) {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

/* ── Raw Tape Table (Panel 02) ───────────────────────────────────────────── */
.evidence-drawer {
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xl);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0) 44px),
    var(--surface-raised);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
  overflow: hidden;
}
.evidence-drawer.open {
  border-color: var(--rule-hi);
}

.drawer-toggle {
  display: grid;
  grid-template-columns: 28px minmax(250px, 1fr) minmax(220px, auto) auto;
  align-items: center;
  gap: var(--s3);
  width: 100%;
  min-height: 60px;
  padding: var(--s3) var(--s5);
  color: var(--text-secondary);
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast) ease;
}
.drawer-toggle:hover {
  background: var(--surface-overlay);
}
.drawer-index {
  color: var(--phosphor);
  font-size: var(--t-micro);
  font-weight: 800;
}
.drawer-copy strong {
  color: var(--text-primary);
  font: 700 var(--t-small) var(--font-display);
}
.drawer-copy small {
  margin-top: 2px;
  color: var(--text-tertiary);
  font-size: var(--t-micro);
}
.drawer-action {
  color: var(--phosphor);
  font-weight: 750;
  font-size: var(--t-micro);
}

.tape-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s4);
  padding: var(--s3) var(--s4);
  background: var(--surface-base);
  border-bottom: var(--hair) solid var(--border-subtle);
  flex-wrap: wrap;
}

.tape-actions {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.tape-table {
  min-width: 1172px;
  table-layout: fixed;
  font-size: var(--t-tiny);
  border-collapse: separate;
  border-spacing: 0;
}
.tape-table th {
  padding: var(--s2) var(--s3);
  color: var(--ink-dim);
  background: var(--surface-overlay);
  box-shadow: inset 0 -1px 0 var(--border-strong);
  position: sticky;
  top: 0;
  z-index: 2;
  font-weight: 750;
  font-size: var(--t-micro);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  overflow: visible;
  text-overflow: clip;
  white-space: nowrap;
}
.tape-table td {
  padding: var(--s2) var(--s3);
  border-bottom: var(--hair) solid var(--border-subtle);
  vertical-align: middle;
}
/* ── Pinned identity columns ──────────────────────────────────────────────
   The tape is deliberately wider than its column on most desks (min-width
   1180px against an ~800–1000px main column). Time, Symbol, and Contract
   pin to the left edge so a scrolled tape still names every print; the
   fixed time/symbol/contract tracks (116/124/132px) carry the NEW badge,
   spot price, and strike without shifting the pinned trio. Pinned cells
   must stay opaque and mirror every row state, or scrolled content shows
   through underneath. */
.tape-live th:nth-child(1),
.tape-live td:nth-child(1) {
  position: sticky;
  left: 0;
  z-index: 3;
}
.tape-live th:nth-child(1) {
  width: 116px;
  z-index: 5;
}
.tape-live th:nth-child(2),
.tape-live td:nth-child(2) {
  position: sticky;
  left: 116px;
  z-index: 3;
  box-shadow: inset -1px 0 0 var(--border-subtle);
}
.tape-live th:nth-child(2) {
  width: 124px;
  z-index: 5;
}
.tape-live th:nth-child(3),
.tape-live td:nth-child(3) {
  position: sticky;
  left: 240px;
  z-index: 3;
  box-shadow: inset -1px 0 0 var(--border-strong);
}
.tape-live th:nth-child(3) {
  width: 132px;
  z-index: 5;
}
.tape-live th:nth-child(-n + 3) {
  background: var(--surface-overlay);
  z-index: 5;
}
.tape-live td:nth-child(-n + 3) {
  background: var(--surface-raised);
}
.tape-live tbody tr:hover td:nth-child(-n + 3) {
  background: var(--panel-hi);
}
.tape-live tbody tr.incoming td:nth-child(-n + 3) {
  background: var(--phosphor-wash);
}
.tape-live tbody tr.selected td:nth-child(-n + 3) {
  background: var(--panel-raise);
  box-shadow: inset 3px 0 0 var(--phosphor);
}
.tape-table tbody tr:hover {
  background: var(--surface-overlay);
}

/* ── Pinned column width clamps ─────────────────────────────────────────────
   The sticky left offsets (0 / 116px / 240px) assume the pinned tracks render
   at exactly 116 / 124 / 132px. Without a clamp, nowrap content (symbol + spot
   price, the NEW badge) can grow a track past its th width hint, desyncing the
   offsets so pinned columns overlap and the tape shears when scrolled. Lock
   each pinned track to its offset width on both th and td, and clip overflow
   so a long print can never push the track wider than the sticky math allows. */
.tape-table th:nth-child(1),
.tape-table td:nth-child(1) {
  width: 116px;
  min-width: 116px;
  max-width: 116px;
  overflow: hidden;
}
.tape-live th:nth-child(2),
.tape-live td:nth-child(2) {
  width: 124px;
  min-width: 124px;
  max-width: 124px;
  overflow: hidden;
}
.tape-live th:nth-child(3),
.tape-live td:nth-child(3) {
  width: 132px;
  min-width: 132px;
  max-width: 132px;
  overflow: hidden;
}
/* Non-pinned columns keep balanced readable floors so content is never crushed */
.tape-table th,
.tape-table td {
  min-width: 88px;
}
.tape-table th:nth-child(4),
.tape-table td:nth-child(4) {
  min-width: 135px;
}
.tape-table th:nth-child(5),
.tape-table td:nth-child(5) {
  min-width: 125px;
}
.tape-table th:nth-child(6),
.tape-table td:nth-child(6) {
  min-width: 115px;
}
.tape-table th:nth-child(7),
.tape-table td:nth-child(7) {
  min-width: 100px;
}
.tape-table th:nth-child(8),
.tape-table td:nth-child(8) {
  min-width: 120px;
}
.tape-table th:nth-child(9),
.tape-table td:nth-child(9) {
  min-width: 100px;
}
.tape-table th:nth-child(10),
.tape-table td:nth-child(10) {
  min-width: 105px;
}

/* `col` tracks own the layout rather than the longest visible print. This
   keeps sticky offsets exact as new symbols, contracts, and badges arrive. */
.tape-col-time {
  width: 116px;
}
.tape-col-symbol {
  width: 124px;
}
.tape-col-contract {
  width: 132px;
}
.tape-col-expiry {
  width: 135px;
}
.tape-col-fill {
  width: 125px;
}
.tape-col-class {
  width: 115px;
}
.tape-col-vol-oi {
  width: 100px;
}
.tape-col-premium {
  width: 120px;
}
.tape-col-percentile {
  width: 100px;
}
.tape-col-aggressor {
  width: 105px;
}

th.sortable {
  cursor: pointer;
  user-select: none;
  transition: color var(--dur-fast);
}
th.sortable:hover {
  color: var(--phosphor);
}

.sort-indicator {
  display: inline-block;
  margin-left: 2px;
  color: var(--phosphor);
  font-size: 10px;
}

.time-readout {
  font-family: var(--font-data);
}

.symbol-cell-content {
  display: flex;
  align-items: baseline;
  gap: 6px;
  white-space: nowrap;
  min-width: 0;
}
.tape-spot-label {
  flex: 0 0 auto;
  font-size: var(--t-micro);
  color: var(--text-tertiary);
}
.tape-spot-label.pos {
  color: var(--long);
}
.tape-spot-label.neg {
  color: var(--short);
}

.contract-cell {
  white-space: nowrap;
}
.strike-val {
  margin-left: 6px;
  color: var(--text-primary);
  font-size: var(--t-small);
}

.expiry-cell-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.expiry-primary {
  display: flex;
  align-items: center;
  gap: 6px;
}
.dte-pill {
  display: inline-flex;
  align-items: center;
  padding: 0 4px;
  font-size: var(--t-micro);
  font-weight: 800;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  color: var(--text-secondary);
}
.dte-pill.dte-0d {
  color: var(--short);
  border-color: var(--short);
  background: var(--short-wash);
}
.dte-pill.dte-weekly {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}
.dte-pill.dte-monthly {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

.moneyness-tag {
  font-size: var(--t-micro);
  font-weight: 700;
}
.moneyness-tag.moneyness-none {
  color: var(--text-tertiary);
}
.moneyness-tag.moneyness-atm {
  color: var(--phosphor);
}
.moneyness-tag.moneyness-otm {
  color: var(--text-tertiary);
}
.moneyness-tag.moneyness-itm {
  color: var(--warn);
}

.flow-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  font-size: var(--t-micro);
  font-weight: 800;
  letter-spacing: 0.04em;
  border: var(--hair) solid var(--border-strong);
  border-radius: var(--r-xs);
  background: var(--surface-base);
  color: var(--text-secondary);
}
.flow-badge.badge-golden-sweep {
  color: var(--badge-golden);
  border-color: var(--badge-golden-border);
  background: var(--badge-golden-wash);
  font-weight: 850;
}
.flow-badge.badge-sweep {
  color: var(--badge-sweep);
  border-color: color-mix(in srgb, var(--call) 50%, var(--rule));
  background: var(--badge-sweep-wash);
  font-weight: 750;
}
.flow-badge.badge-block {
  color: var(--put-hi);
  border-color: color-mix(in srgb, var(--put) 50%, var(--rule));
  background: var(--badge-block-wash);
  font-weight: 750;
}
.flow-badge.badge-split {
  color: var(--badge-split);
  border-color: color-mix(in srgb, var(--cat-4) 45%, var(--rule));
  background: var(--badge-split-wash);
  font-weight: 750;
}
.flow-badge.badge-multileg {
  color: var(--badge-multileg);
  border-color: color-mix(in srgb, var(--cat-5) 45%, var(--rule));
  background: var(--badge-multileg-wash);
  font-weight: 750;
}
.badge-pip {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.vol-oi-cell {
  white-space: nowrap;
}
.vol-oi-pill {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  font-size: var(--t-micro);
  font-weight: 800;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  color: var(--text-secondary);
}
.vol-oi-pill.vol-oi-high {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}
.vol-oi-pill.vol-oi-extreme {
  color: var(--long);
  border-color: var(--long);
  background: var(--long-wash);
}

.tape-premium {
  font-weight: 800;
  font-size: var(--t-small);
}
.whale-indicator {
  display: block;
  font-size: var(--t-micro);
  font-weight: 800;
  letter-spacing: 0.04em;
  margin-bottom: 2px;
}
.whale-indicator.tier-mega-whale {
  color: var(--warn);
}
.whale-indicator.tier-whale {
  color: var(--phosphor);
}

.right-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 20px;
  padding: 1px 6px;
  border-radius: var(--r-xs);
  font-weight: 800;
  font-size: var(--t-micro);
}
.right-chip.call {
  color: var(--call-hi);
  border: var(--hair) solid var(--call);
  background: var(--call-wash);
}
.right-chip.put {
  color: var(--put-hi);
  border: var(--hair) solid var(--put);
  background: var(--put-wash);
}

.aggressor {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  font-size: var(--t-micro);
  font-weight: 800;
  border-radius: var(--r-xs);
  border: var(--hair) solid currentColor;
}

.heat-cell {
  display: grid;
  grid-template-columns: 62px 38px;
  align-items: center;
  gap: 6px;
}
.heat-track {
  display: block;
  height: 5px;
  overflow: hidden;
  background: var(--border-subtle);
  border-radius: 1px;
}
.heat-track i {
  display: block;
  height: 100%;
  background: var(--text-tertiary);
}
.heat-cell.warm .heat-track i {
  background: var(--warn);
}
.heat-cell.hot .heat-track i {
  background: var(--phosphor);
}

.th-content {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 750;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
}

/* ── 2-Column Institutional Grid (Matching Reference) ──────────────────── */
.flow-institutional-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: var(--s4);
  align-items: start;
}

.flow-main-column {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  min-width: 0;
}

.flow-sidebar-column {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  min-width: 0;
}

/* ── Realtime Tape Card (Main Table) ────────────────────────────────────── */
.realtime-tape-card {
  display: flex;
  flex-direction: column;
  border: var(--hair) solid var(--border-strong);
  border-radius: var(--r-md);
  background: var(--surface-raised);
  overflow: hidden;
}

.realtime-tape-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  background: var(--panel-hi);
  border-bottom: var(--hair) solid var(--border-strong);
  flex-wrap: wrap;
}

.realtime-title-line {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.realtime-title-line h2 {
  color: var(--ink);
  font-size: var(--t-body);
  font-weight: 750;
  letter-spacing: -0.01em;
  margin: 0;
}

.live-pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--call);
  flex-shrink: 0;
}

.live-tag {
  padding: 1px 6px;
  font-size: var(--t-micro);
  font-weight: 800;
  color: var(--call);
  background: var(--call-wash);
  border: var(--hair) solid var(--call-dim);
  border-radius: var(--r-xs);
  letter-spacing: 0.06em;
}

.tape-quick-actions {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.tape-count-badge {
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  font-weight: 700;
}

.realtime-tape-card .tape-scroll {
  max-height: 520px;
  overflow-y: auto;
  overflow-x: auto;
  scrollbar-width: thin;
}

.tape-table tbody tr {
  cursor: pointer;
  transition: background 0.12s ease;
}

.tape-table tbody tr:hover {
  background: var(--panel-hi);
}

.tape-table tbody tr.selected {
  background: var(--panel-raise);
  box-shadow: inset 3px 0 0 var(--phosphor);
}

.premium-meter-wrap {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  min-height: 22px;
  padding: 0 4px;
}

.premium-fill-meter {
  position: absolute;
  top: 2px;
  bottom: 2px;
  right: 0;
  background: var(--call-wash);
  border-radius: var(--r-xs);
  pointer-events: none;
}

.premium-val-text {
  position: relative;
  z-index: 1;
  font-weight: 800;
}

.hot-pip {
  font-size: var(--t-micro);
  margin-right: 2px;
  color: var(--long);
  font-weight: 900;
}

/* ── Filter Meta Tray (Saved Layouts & Pinned Exclusions) ───────────────── */
.filter-search-group {
  display: flex;
  align-items: center;
}

.clear-input-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  margin-left: -24px;
  background: transparent;
  border: none;
  color: var(--ink-dim);
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
  z-index: 2;
}
.clear-input-btn:hover {
  color: var(--ink);
}

.filter-meta-tray {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) 0;
  border-top: var(--hair) solid var(--rule-faint);
  flex-wrap: wrap;
}

.tray-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

/* ── Sidebar Analytics Cards ────────────────────────────────────────────── */
.sidebar-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s4);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  overflow: hidden;
}

.sidebar-card-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar-card-title {
  color: var(--ink);
  font-size: var(--t-small);
  font-weight: 750;
  letter-spacing: -0.01em;
  margin: 0;
}

/* Card 1: Trend */
.trend-readout-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s2);
}

.net-flow-val {
  display: block;
  font-size: 1.25rem;
  font-weight: 850;
  line-height: 1.15;
}
.net-flow-val.pos {
  color: var(--long);
}
.net-flow-val.neg {
  color: var(--short);
}

.trend-badge-btn {
  padding: 2px 8px;
  font-size: 10px;
  font-weight: 800;
  border-radius: var(--r-xs);
  letter-spacing: 0.04em;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition:
    transform 0.1s ease,
    opacity 0.1s ease;
}
.trend-badge-btn:hover {
  transform: translateY(-1px);
  opacity: 0.9;
}
.trend-badge-btn.bullish {
  color: var(--long);
  background: var(--long-wash);
  border: 1px solid var(--long);
}
.trend-badge-btn.bearish {
  color: var(--short);
  background: var(--short-wash);
  border: 1px solid var(--short);
}
.filter-on-tag {
  font-size: 8px;
  padding: 0 3px;
  background: var(--void);
  border-radius: 2px;
}

.trend-chart-box {
  width: 100%;
  height: 54px;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  overflow: hidden;
}
.trend-svg {
  display: block;
  width: 100%;
  height: 100%;
}
/* Flat-fill trend marks — no gradient, no glow (data marks are flat fills). */
.trend-area {
  fill: var(--call-wash);
}
.trend-line {
  fill: none;
  stroke: var(--call);
  stroke-linecap: round;
}

/* Card 2: Distribution */
.dist-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
}

.filter-pill {
  font-size: var(--t-micro);
  font-weight: 800;
  padding: 1px 6px;
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
  border-radius: var(--r-xs);
}

.distribution-meters {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.dist-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.dist-labels {
  display: flex;
  justify-content: space-between;
  font-size: var(--t-micro);
  font-weight: 750;
}

.dist-label-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 0;
  font: inherit;
  font-weight: 750;
  transition: opacity 0.12s ease;
}
.dist-label-btn:hover {
  opacity: 0.8;
  text-decoration: underline;
}

.dist-track {
  display: flex;
  height: 8px;
  background: var(--void-lift);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.dist-track.interactive {
  cursor: pointer;
}
.call-segment.clickable:hover {
  opacity: 0.85;
}
.put-segment.clickable:hover {
  opacity: 0.85;
}
.call-segment.dimmed,
.put-segment.dimmed {
  opacity: 0.35;
}

.dist-legend-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s2);
  padding-top: var(--s2);
  border-top: var(--hair) solid var(--rule);
}

.dist-stat-btn {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 8px;
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  cursor: pointer;
  text-align: left;
  transition:
    background 0.12s ease,
    border-color 0.12s ease;
}
.dist-stat-btn:hover,
.dist-stat-btn.active {
  background: var(--panel-raise);
  border-color: var(--rule-hi);
}
.dist-stat-btn.call.active {
  border-color: var(--call);
}
.dist-stat-btn.put.active {
  border-color: var(--put);
}
.dist-stat-btn strong {
  font-size: var(--t-small);
  font-weight: 800;
}
.dist-stat-btn.call strong {
  color: var(--call-hi);
}
.dist-stat-btn.put strong {
  color: var(--put-hi);
}

/* Card 3: Top Contracts */
.top-contracts-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.empty-top-contracts {
  padding: var(--s3);
  text-align: center;
  color: var(--ink-faint);
}

.contract-row-btn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  cursor: pointer;
  transition:
    background-color 0.12s ease,
    border-color 0.12s ease;
  text-align: left;
}

.contract-row-btn:hover,
.contract-row-btn.active {
  background: var(--panel-raise);
  border-color: var(--phosphor-dim);
  box-shadow: inset 2px 0 0 var(--phosphor);
}

.contract-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.contract-strike {
  color: var(--ink);
  font-size: var(--t-tiny);
  font-weight: 800;
}

.contract-exp {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.contract-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.contract-prem {
  color: var(--ink);
  font-size: var(--t-tiny);
  font-weight: 750;
}

.contract-type {
  font-size: var(--t-micro);
  font-weight: 800;
  padding: 1px 4px;
  border-radius: var(--r-xs);
}

/* Card 4: Institutional Radar Alert Banner */
.institutional-alert-card {
  background: var(--panel);
  border: var(--hair) solid var(--rule);
}

.alert-card-badge-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.institutional-badge {
  padding: 2px 6px;
  font-size: var(--t-micro);
  font-weight: 800;
  color: var(--badge-block);
  background: var(--badge-block-wash);
  border: var(--hair) solid var(--badge-block);
  border-radius: var(--r-xs);
  letter-spacing: 0.05em;
}

.radar-live-pill {
  font-size: var(--t-micro);
  font-weight: 800;
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
  border-radius: var(--r-xs);
  padding: 1px 5px;
}

.alert-card-heading {
  color: var(--ink);
  font-size: var(--t-small);
  font-weight: 800;
  letter-spacing: -0.01em;
  margin: 2px 0 0;
}

.alert-card-description {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  line-height: 1.4;
  margin: 0;
}

.radar-action-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  margin-top: 4px;
}

.radar-grid-btn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 6px 8px;
  background: var(--surface-base);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
  cursor: pointer;
  text-align: left;
  transition:
    background 0.12s ease,
    border-color 0.12s ease;
}
.radar-grid-btn:hover {
  background: var(--panel-hi);
  border-color: var(--phosphor-dim);
}
.radar-grid-btn.active {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
}
.radar-btn-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.radar-btn-title {
  font-size: var(--t-tiny);
  font-weight: 750;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.radar-btn-count {
  font-size: 10px;
  color: var(--ink-faint);
  white-space: nowrap;
}
.radar-btn-action {
  font-size: 9px;
  font-weight: 800;
  padding: 2px 4px;
  border-radius: 2px;
  background: var(--panel-raise);
  color: var(--ink-soft);
  flex-shrink: 0;
}
.radar-grid-btn.active .radar-btn-action {
  background: var(--phosphor);
  color: var(--void);
}

/* Card 5: Inspector */
.inspector-card {
  background: var(--panel);
  border-color: var(--rule);
}

.inspector-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
}
.copy-contract-btn {
  padding: 2px 8px;
  font-size: 10px;
  font-weight: 800;
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-hi);
  color: var(--ink-soft);
  border-radius: var(--r-xs);
  cursor: pointer;
  transition:
    background 0.12s ease,
    color 0.12s ease;
}
.copy-contract-btn:hover {
  background: var(--panel-raise);
  color: var(--ink);
}
.copy-contract-btn.copied {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
  color: var(--phosphor);
}

.inspector-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s2);
}

.inspector-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 8px;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.inspector-item strong {
  font-size: var(--t-tiny);
  font-weight: 750;
}

.inspector-open-btn {
  width: 100%;
  min-height: 32px;
  padding: 0 var(--s3);
  font-size: var(--t-micro);
  font-weight: 800;
  color: var(--void);
  background: var(--long);
  border: var(--hair) solid var(--long);
  border-radius: var(--r-sm);
  cursor: pointer;
  letter-spacing: 0.04em;
  transition:
    background-color 0.12s ease,
    border-color 0.12s ease;
  margin-top: 4px;
}

.inspector-open-btn:hover {
  background: var(--call-hi);
  border-color: var(--call-hi);
}

.method-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-top: var(--hair) solid var(--border-strong);
  border-bottom: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
}
.method-strip article {
  padding: var(--s4) var(--s5);
  border-right: var(--hair) solid var(--border-subtle);
}
.method-strip article:last-child {
  border-right: 0;
}
.method-strip p {
  margin-top: 4px;
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  line-height: 1.4;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* ── Responsive Layouts ─────────────────────────────────────────────────── */
@media (max-width: 1320px) {
  .flow-institutional-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .flow-sentiment-hero {
    grid-template-columns: minmax(0, 1fr);
  }
  .sentiment-card {
    border-right: 0;
    border-bottom: var(--hair) solid var(--border-subtle);
  }
  .live-pulse {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .pulse-copy {
    grid-column: 1 / -1;
    border-bottom: var(--hair) solid var(--border-subtle);
  }
  .major-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .major-card:nth-child(2) {
    border-right: 0;
  }
  .major-card:nth-child(n + 3) {
    border-top: var(--hair) solid var(--border-subtle);
  }
  .select-filter {
    min-width: 140px;
  }
  .reset-filter {
    align-self: end;
  }
}

@media (max-width: 1100px) {
  .control-rail {
    display: grid;
    grid-template-columns: minmax(250px, 1fr) auto;
  }
  .threshold-control {
    justify-content: flex-end;
  }
  .control-status {
    grid-column: 1;
    grid-row: 2;
    width: auto;
    margin-left: 0;
    padding-top: var(--s2);
    border-top: var(--hair) solid var(--border-subtle);
    text-align: left;
  }
  .refresh-button {
    grid-column: 2;
    grid-row: 2;
    margin-left: auto;
  }
}

@media (max-width: 980px) {
  .snapshot-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .snapshot-metrics article:nth-child(2) {
    border-right: 0;
  }
  .snapshot-metrics article:nth-child(n + 3) {
    border-top: var(--hair) solid var(--border-subtle);
  }
  .live-pulse {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .pulse-stat:nth-of-type(odd) {
    border-left: 0;
  }
  .pulse-stat:nth-of-type(n + 3) {
    border-top: var(--hair) solid var(--border-subtle);
  }
  .majors-head {
    align-items: flex-start;
    flex-direction: column;
    gap: var(--s2);
  }
  .majors-head p {
    text-align: left;
  }
  .filter-tier-primary,
  .filter-tier-secondary {
    gap: var(--s2);
  }
  .seg-filter > div {
    display: flex;
    flex-wrap: wrap;
  }
  .drawer-toggle {
    grid-template-columns: 28px minmax(0, 1fr) auto;
  }
  .drawer-note {
    display: none;
  }
  .method-strip {
    grid-template-columns: minmax(0, 1fr);
  }
  .method-strip article {
    border-right: 0;
    border-bottom: var(--hair) solid var(--border-subtle);
  }
  .method-strip article:last-child {
    border-bottom: 0;
  }
}

@media (max-width: 620px) {
  .control-rail {
    grid-template-columns: minmax(0, 1fr);
  }
  .control-identity,
  .threshold-control {
    width: 100%;
  }
  .threshold-control {
    align-items: flex-start;
    flex-direction: column;
    gap: var(--s2);
  }
  .thresholds {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    width: 100%;
  }
  .control-status,
  .refresh-button {
    grid-column: 1;
    grid-row: auto;
  }
  .refresh-button {
    width: 100%;
    margin-left: 0;
  }
  .snapshot-metrics {
    grid-template-columns: minmax(0, 1fr);
  }
  .snapshot-metrics article {
    border-right: 0;
    border-top: var(--hair) solid var(--border-subtle);
  }
  .snapshot-metrics article:first-child {
    border-top: 0;
  }
  .live-pulse {
    grid-template-columns: minmax(0, 1fr);
  }
  .pulse-copy {
    grid-column: auto;
  }
  .triage-pick {
    min-height: 142px;
    border-top: var(--hair) solid var(--border-subtle);
    border-left: 0;
  }
  .major-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .major-card,
  .major-card:nth-child(2) {
    min-height: 244px;
    border-right: 0;
    border-top: var(--hair) solid var(--border-subtle);
  }
  .major-card:first-child {
    border-top: 0;
  }
  .filter-shelf {
    grid-template-columns: minmax(0, 1fr);
  }
  .queue-footer {
    align-items: flex-start;
    flex-direction: column;
  }
  .drawer-toggle {
    grid-template-columns: 24px minmax(0, 1fr);
  }
  .drawer-action {
    grid-column: 2;
  }
  .tape-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (prefers-reduced-motion: reduce) {
  .drawer-action i,
  .thresholds button,
  .refresh-button,
  .panel-action,
  .row-open {
    transition: none;
  }
}
</style>
