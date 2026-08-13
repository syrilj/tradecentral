<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import type {
  DirectionalSignal,
  MarketFlowPrint,
  StatusPayload,
  UnusualFlowPayload,
  UnusualFlowRow,
} from '@/api'
import { age, compact, DASH, num, pctFrac, pick, shortDate, signedPct, tone, usd } from '@/format'
import AppIcon from '@/components/AppIcon.vue'
import LoadingState from '@/components/LoadingState.vue'
import Panel from '@/components/Panel.vue'
import {
  buildFlowPulse,
  compareFlowReviewRows,
  flowPrintKey,
  type FlowPulse,
  type FlowPulsePayload,
  type SymbolPulse,
} from '@/flowPulse'

const props = defineProps<{
  payload: UnusualFlowPayload | null
  status: StatusPayload | null
  loading: boolean
  error: string | null
  minPremium: number
  pollMs: number
}>()

const emit = defineEmits<{
  refresh: []
  threshold: [value: number]
  openSymbol: [symbol: string]
}>()

const THRESHOLDS = [25_000, 50_000, 100_000, 250_000]
const DEFAULT_REVIEW_ROWS = 12
const MAX_TAPE_ROWS = 100
const PULSE_STORAGE_KEY = 'edge.flow.previous-window.v1'

type ActivityFilter = 'all' | 'incoming' | 'sweeps' | 'flagged' | 'near'
type RightFilter = 'all' | 'call' | 'put'
type DteFilter = 'all' | 'week' | 'month' | 'dated'
type SortKey = 'review' | 'incoming' | 'premium' | 'sweeps' | 'flagged' | 'expiry'

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

const MAJOR_SYMBOLS = ['SPY', 'QQQ', 'IWM', 'DIA'] as const
const EMPTY_SYMBOL_PULSE: SymbolPulse = {
  newPrints: 0,
  newPremium: 0,
  windowPremiumDelta: 0,
  rankMove: null,
}

const nowMs = ref(Date.now())
const symbolQuery = ref('')
const activityFilter = ref<ActivityFilter>('all')
const rightFilter = ref<RightFilter>('all')
const dteFilter = ref<DteFilter>('all')
const sortKey = ref<SortKey>('review')
const tapeExpanded = ref(false)
const showAllReviews = ref(false)
const pulse = shallowRef<FlowPulse>(buildFlowPulse(null, {
  asof: '',
  generated_at: '',
  rows: [],
  tape: [],
}))
let freshnessTimer: number | undefined
let previousPulsePayload: FlowPulsePayload | null = restorePulsePayload()
let previousSnapshotToken = ''

function restorePulsePayload(): FlowPulsePayload | null {
  if (typeof sessionStorage === 'undefined') return null
  try {
    const stored = JSON.parse(sessionStorage.getItem(PULSE_STORAGE_KEY) ?? 'null') as FlowPulsePayload | null
    return stored && Array.isArray(stored.rows) && Array.isArray(stored.tape) ? stored : null
  } catch {
    return null
  }
}

function persistPulsePayload(payload: FlowPulsePayload): void {
  if (typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.setItem(PULSE_STORAGE_KEY, JSON.stringify({
      asof: payload.asof,
      generated_at: payload.generated_at,
      rows: payload.rows,
      tape: payload.tape,
    }))
  } catch {
    // Change tracking is an enhancement; the current measured window remains usable.
  }
}

watch(() => props.payload, (next) => {
  if (!next) return
  const token = `${next.generated_at ?? ''}|${next.asof}`
  if (token === previousSnapshotToken) return
  pulse.value = buildFlowPulse(previousPulsePayload, next)
  previousPulsePayload = next
  previousSnapshotToken = token
  persistPulsePayload(next)
}, { immediate: true })

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
  (props.payload?.rows ?? []).filter((row) =>
    row.live && finite(row.premium) != null && Number(row.premium) >= props.minPremium,
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
  return contracts > 0 ? clamp01((finite(row.unusual_contracts) ?? 0) / contracts) : 0
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
  const putShare = finite(row.put_flow_pct)
  if (putShare == null) return false
  return rightFilter.value === 'put' ? putShare >= 0.5 : putShare < 0.5
}

const filteredRows = computed<UnusualFlowRow[]>(() => {
  const query = symbolQuery.value.trim().toUpperCase()
  const rows = qualifiedRows.value.filter((row) =>
    (!query || row.symbol.toUpperCase().includes(query))
      && aggregateMatchesActivity(row)
      && aggregateMatchesRight(row)
      && inDteBand(row.average_dte),
  )

  return [...rows].sort((a, b) => {
    if (sortKey.value === 'incoming') return symbolPulse(b.symbol).newPremium - symbolPulse(a.symbol).newPremium
    if (sortKey.value === 'premium') return (finite(b.premium) ?? 0) - (finite(a.premium) ?? 0)
    if (sortKey.value === 'sweeps') return (finite(b.sweep_premium) ?? 0) - (finite(a.sweep_premium) ?? 0)
    if (sortKey.value === 'flagged') return flaggedShare(b) - flaggedShare(a)
    if (sortKey.value === 'expiry') return (finite(a.average_dte) ?? Infinity) - (finite(b.average_dte) ?? Infinity)
    return compareFlowReviewRows(a, b, maxPremium.value)
  })
})

const reviewRows = computed(() => showAllReviews.value
  ? filteredRows.value
  : filteredRows.value.slice(0, DEFAULT_REVIEW_ROWS),
)
const filteredSymbols = computed(() => new Set(filteredRows.value.map((row) => row.symbol)))
const reviewRankBySymbol = computed(() => new Map(
  [...qualifiedRows.value]
    .sort((a, b) => compareFlowReviewRows(a, b, maxPremium.value))
    .map((row, index) => [row.symbol, index + 1]),
))

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

const qualifiedTapeRows = computed<MarketFlowPrint[]>(() =>
  (props.payload?.tape ?? []).filter((row) =>
    row.symbol != null
      && filteredSymbols.value.has(row.symbol)
      && (rightFilter.value === 'all' || row.right === rightFilter.value)
      && inDteBand(row.dte)
      && tapeMatchesActivity(row),
  ),
)

const tapeRows = computed(() => qualifiedTapeRows.value.slice(0, MAX_TAPE_ROWS))

const projectedSummary = computed<ProjectedSummary>(() => {
  const rows = qualifiedRows.value
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

const providerFreshness = computed(() => {
  void nowMs.value
  return age(props.payload?.asof)
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
  return props.payload?.feed_status === 'live' ? 'live' : props.payload?.feed_status ?? 'unknown'
})

const feedStatusLabel = computed(() => {
  if (!props.payload) return 'WAITING'
  if (providerFreshnessState.value === 'stale') return 'STALE SAMPLE'
  if (providerFreshnessState.value === 'live') return 'LIVE SAMPLE'
  return String(props.payload.feed_status ?? 'unknown').replaceAll('_', ' ').toUpperCase()
})

const feedWindowLabel = computed(() => {
  const coverage = props.payload?.coverage
  const prints = coverage?.provider_prints ?? props.payload?.summary?.tape_print_count ?? 0
  const symbols = coverage?.observed_symbols ?? props.payload?.rows.length ?? 0
  return `${compact(prints)} PRINTS · ${compact(symbols)} SYMBOLS`
})

const contractMismatch = computed(() =>
  !!props.payload && props.payload.source_snapshot !== 'market_flow',
)

const hasMeasuredFlow = computed(() =>
  qualifiedRows.value.length > 0 || (props.payload?.tape?.length ?? 0) > 0,
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
      const inferredSigned = row.bias === 'bullish' ? premium : row.bias === 'bearish' ? -premium : null
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
    const windowMove = firstSpot != null && lastSpot != null && firstSpot !== 0
      ? (lastSpot / firstSpot) - 1
      : null

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
  return calibrated
    && context.setupOk === true
    && actionableState
    && (side === 'long' || side === 'short')
    && context.probability >= 0.55
}

function directionRead(symbol: string): DirectionRead {
  const stats = tapeStats(symbol)
  const context = signalBySymbol.value.get(symbol) ?? null
  const hasSignedFlow = !!stats && stats.signedPrints > 0 && stats.signedGross > 0
  const modelStrong = strongModelContext(context)
  const modelBullish = context?.side.toLowerCase() === 'long'
  const boardRow = (props.payload?.rows ?? []).find((row) => row.symbol === symbol) ?? null

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
    const putShare = finite(boardRow.put_flow_pct)
    const imb = finite(boardRow.call_put_imbalance)
    const callHeavy = (imb != null && imb >= 0.15) || (putShare != null && putShare <= 0.42)
    const putHeavy = (imb != null && imb <= -0.15) || (putShare != null && putShare >= 0.58)
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
      detail: fallbackMove == null ? 'Tape spot · no return series' : 'Move within latest provider sample',
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
      label: flaggedShare(row) > 0 ? `Flagged ${fractionPercent(flaggedShare(row), 0)}` : 'Flagged prints',
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
  const dteZone = stats?.topDteBucket && stats.topDteBucket !== 'Unavailable'
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
  } else if (incoming || nearExpiry || sweeps || direction.state.includes('bullish') || direction.state.includes('bearish')) {
    priority = incoming || nearExpiry ? 'now' : 'soon'
  } else if (direction.state === 'mixed' || direction.state === 'unknown') {
    priority = 'watch'
  }

  let action: string
  if (priority === 'skip') {
    action = 'Refresh feed before chain work — provider sample is stale'
  } else if (direction.state === 'mixed') {
    action = 'Open chain · reconcile conflicting lean vs model before size'
  } else if (direction.state.includes('bullish')) {
    action = nearExpiry
      ? 'Open chain · map near-dated call strikes + upside walls'
      : 'Open chain · confirm call side liquidity and call wall'
  } else if (direction.state.includes('bearish')) {
    action = nearExpiry
      ? 'Open chain · map near-dated put strikes + downside walls'
      : 'Open chain · confirm put side liquidity and put wall'
  } else if (incoming) {
    action = 'Open chain · new prints just landed; read structure first'
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

const rankMoveCount = computed(() =>
  [...pulse.value.bySymbol.values()].filter((row) => row.rankMove != null && row.rankMove !== 0).length,
)

const topIncoming = computed(() =>
  [...pulse.value.bySymbol.entries()]
    .filter(([, row]) => row.newPremium > 0)
    .sort((a, b) => b[1].newPremium - a[1].newPremium)[0] ?? null,
)

const pulseState = computed(() => {
  if (pulse.value.baseline) return { label: 'BASELINE SET', state: 'baseline' }
  if (pulse.value.newPrintCount > 0) return { label: `${pulse.value.newPrintCount} NEW PRINTS`, state: 'active' }
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
    const rank = insight.priority === 'now' ? 3 : insight.priority === 'soon' ? 2 : insight.priority === 'watch' ? 1 : 0
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
  const bySweep = [...filteredRows.value]
    .sort((a, b) => (finite(b.sweep_premium) ?? 0) - (finite(a.sweep_premium) ?? 0))[0]
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

const activeFilterCount = computed(() =>
  Number(symbolQuery.value.trim().length > 0)
    + Number(activityFilter.value !== 'all')
    + Number(rightFilter.value !== 'all')
    + Number(dteFilter.value !== 'all')
    + Number(sortKey.value !== 'review'),
)

const reviewMeta = computed(() =>
  `SHOWING ${reviewRows.value.length} OF ${filteredRows.value.length} · ≥ $${compact(props.minPremium)}`,
)

const tapeMeta = computed(() => {
  if (baseSummary.value?.tape_detail_available === false) return 'DETAIL UNAVAILABLE · AGGREGATE SNAPSHOT'
  return `${tapeRows.value.length}/${qualifiedTapeRows.value.length} MATCHING PRINTS · MAX ${MAX_TAPE_ROWS}`
})

function clearFilters(): void {
  symbolQuery.value = ''
  activityFilter.value = 'all'
  rightFilter.value = 'all'
  dteFilter.value = 'all'
  sortKey.value = 'review'
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
  return fractionPercent(putShare(row), 0)
}

function callShareLabel(row: UnusualFlowRow): string {
  return fractionPercent(callShare(row), 0)
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
  if (symbol) emit('openSymbol', symbol)
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
  return String(props.payload?.asof ?? new Date().toISOString()).slice(0, 10).replaceAll(/[^0-9-]/g, '')
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
      evidenceFor(row).map((tag) => tag.label).join(' | '),
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
</script>

<template>
  <section class="flow-dashboard" aria-label="Live options flow review workspace">
    <header class="control-rail ticked rise">
      <div class="control-identity">
        <span class="feed-mark" :class="{ active: providerFreshnessState === 'live' && !loading }" aria-hidden="true">
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
          {{ contractMismatch
            ? 'BACKEND UPDATE REQUIRED'
            : `${feedStatusLabel} · ${feedWindowLabel}` }}
        </span>
        <span>{{ payload ? `PROVIDER ${providerFreshness} · SNAPSHOT ${snapshotFreshness}` : 'NO SNAPSHOT' }}</span>
      </div>

      <button class="refresh-button label" type="button" :disabled="loading" @click="emit('refresh')">
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
        <p>Restart the local API, then refresh this feed. Obsolete Deep-scan data is not substituted here.</p>
      </div>
      <button type="button" class="empty-action label" :disabled="loading" @click="emit('refresh')">
        {{ loading ? 'CHECKING' : 'CHECK AGAIN' }}
      </button>
    </div>

    <div v-else-if="!payload" class="no-snapshot ticked">
      <AppIcon name="flow" :size="24" />
      <strong>No flow snapshot is available.</strong>
      <p>Pull the provider feed to build a review queue from measured ticker aggregates.</p>
      <button type="button" class="empty-action label" @click="emit('refresh')">PULL FLOW DATA</button>
    </div>

    <div v-else-if="!hasMeasuredFlow" class="feed-recovery empty-feed ticked" role="status">
      <span class="recovery-mark label">0×</span>
      <div>
        <span class="label">No measured prints in the latest provider sample</span>
        <strong>The provider returned no contracts above ${{ compact(minPremium) }}.</strong>
        <p>{{ payload.feed_reason || payload.warnings?.[0] || 'Try a lower threshold or request a fresh market-wide provider sample.' }}</p>
      </div>
      <button type="button" class="empty-action label" :disabled="loading" @click="emit('refresh')">
        {{ loading ? 'PULLING' : 'REFRESH FEED' }}
      </button>
    </div>

    <template v-else>
      <section class="live-pulse rise" :class="`brief-${workspaceBrief.tone}`" aria-labelledby="live-pulse-title">
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
          v-for="(pick, index) in triagePicks"
          :key="pick.key"
          type="button"
          class="triage-pick"
          :class="pick.leanState"
          :aria-label="`Open ${pick.symbol} options — ${pick.eyebrow}`"
          @click="openSymbol(pick.symbol)"
        >
          <span class="triage-index fig">0{{ index + 1 }}</span>
          <span class="label">{{ pick.eyebrow }}</span>
          <span class="triage-symbol-line">
            <strong class="fig">{{ pick.symbol }}</strong>
            <b class="fig">{{ pick.value }}</b>
          </span>
          <span class="triage-lean label" :class="pick.leanState">{{ pick.lean }}</span>
          <small class="triage-action">{{ pick.detail }}</small>
          <small class="triage-focus">Focus: {{ pick.action }}</small>
          <span class="triage-tags">
            <span v-for="tag in pick.tags" :key="tag.label" class="label" :class="tag.kind">{{ tag.label }}</span>
          </span>
          <span class="triage-open label">OPEN CHAIN →</span>
        </button>
      </section>

      <section class="filter-shelf rise" aria-label="Flow review filters">
        <div class="filter-intro">
          <span class="label">Review queue filters</span>
          <strong>Narrow the evidence</strong>
          <small>Calls and puts are contract identity; flags are current-tape heuristics, not trade instructions.</small>
        </div>

        <label class="search-filter">
          <span class="label">Ticker</span>
          <span class="input-shell">
            <AppIcon name="search" :size="14" />
            <input v-model="symbolQuery" type="search" placeholder="Search symbol" autocomplete="off">
          </span>
        </label>

        <fieldset class="seg-filter activity-filter">
          <legend class="label">Show</legend>
          <div>
            <button type="button" :class="{ active: activityFilter === 'all' }" @click="activityFilter = 'all'">All</button>
            <button type="button" :class="{ active: activityFilter === 'incoming' }" @click="activityFilter = 'incoming'">New</button>
            <button type="button" :class="{ active: activityFilter === 'sweeps' }" @click="activityFilter = 'sweeps'">Sweeps</button>
            <button type="button" title="Premium, volume, repeat, or sweep heuristics in the current tape" :class="{ active: activityFilter === 'flagged' }" @click="activityFilter = 'flagged'">Flags</button>
            <button type="button" :class="{ active: activityFilter === 'near' }" @click="activityFilter = 'near'">≤7D</button>
          </div>
          <small>Flags mark unusual prints for inspection; they do not establish direction.</small>
        </fieldset>

        <fieldset class="seg-filter">
          <legend class="label">Contract mix</legend>
          <div>
            <button type="button" :class="{ active: rightFilter === 'all' }" @click="rightFilter = 'all'">Any</button>
            <button type="button" :class="{ active: rightFilter === 'call' }" @click="rightFilter = 'call'">Call-led</button>
            <button type="button" :class="{ active: rightFilter === 'put' }" @click="rightFilter = 'put'">Put-led</button>
          </div>
          <small>Filters premium mix only. Buy/sell direction needs provider-signed flow.</small>
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

        <button type="button" class="reset-filter label" :disabled="activeFilterCount === 0" @click="clearFilters">
          RESET <span v-if="activeFilterCount">({{ activeFilterCount }})</span>
        </button>
      </section>

      <section class="majors-section rise" aria-labelledby="majors-title">
        <header class="majors-head">
          <div>
            <span class="label section-kicker">Index flow first</span>
            <h2 id="majors-title">Where the major tape is concentrated</h2>
          </div>
          <p>
            <strong class="label">{{ directionPolicy }}</strong><br>
            Activity lean is descriptive; signed buy/sell and ENTER-state models upgrade evidence. Open chain only to confirm walls and liquidity.
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
                <button type="button" class="major-symbol fig" @click="openSymbol(major.symbol)">{{ major.symbol }}</button>
                <span v-if="symbolPulse(major.symbol).newPrints > 0" class="new-badge label">NEW</span>
                <span class="major-rank fig">REVIEW #{{ reviewRank(major.symbol) }}</span>
                <span class="rank-move fig" :class="rankMoveClass(major.symbol)">{{ rankMoveLabel(major.symbol) }}</span>
              </header>

              <div class="major-premium">
                <div>
                  <span class="label">Sample premium</span>
                  <strong class="fig">{{ moneyCompact(major.row.premium) }}</strong>
                </div>
                <div>
                  <span class="label">{{ pulse.baseline ? 'Tracking state' : 'New this refresh' }}</span>
                  <strong class="fig">{{ pulse.baseline ? 'STARTS NOW' : moneyCompact(symbolPulse(major.symbol).newPremium) }}</strong>
                </div>
              </div>

              <div class="major-direction" :class="directionRead(major.symbol).state">
                <span class="direction-arrow" aria-hidden="true">
                  {{ directionRead(major.symbol).state.includes('bullish') ? '↑' : directionRead(major.symbol).state.includes('bearish') ? '↓' : directionRead(major.symbol).state === 'mixed' ? '↕' : '·' }}
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
                  <dd class="fig">{{ tapeStats(major.symbol)?.topStrike ?? 'Unavailable' }}</dd>
                </div>
                <div>
                  <dt class="label">DTE zone</dt>
                  <dd class="fig">{{ tapeStats(major.symbol)?.topDteBucket ?? 'Unavailable' }}</dd>
                </div>
                <div>
                  <dt class="label">Spot</dt>
                  <dd class="fig">{{ priceRead(major.row).spot }}</dd>
                  <small :class="priceRead(major.row).tone">{{ priceRead(major.row).move }}</small>
                </div>
              </dl>
              <p class="major-action label" :class="actionInsight(major.row).leanState">
                <span>{{ actionInsight(major.row).priority.toUpperCase() }}</span>
                {{ actionInsight(major.row).action }}
              </p>
              <button type="button" class="major-open label" @click="openSymbol(major.symbol)">
                OPEN {{ major.symbol }} CHAIN <span aria-hidden="true">→</span>
              </button>
            </template>
            <template v-else>
              <header class="major-symbol-line">
                <strong class="major-symbol fig">{{ major.symbol }}</strong>
              </header>
              <div class="major-absent">
                <strong>Not in the latest provider sample</strong>
                <p>No qualifying {{ major.symbol }} aggregate cleared ${{ compact(minPremium) }}.</p>
              </div>
              <button type="button" class="major-open label" @click="openSymbol(major.symbol)">
                OPEN {{ major.symbol }} CHAIN <span aria-hidden="true">→</span>
              </button>
            </template>
          </article>
        </div>
      </section>

      <section class="snapshot-strip rise" aria-label="Current threshold snapshot">
        <article>
          <span class="label">Premium in latest sample</span>
          <strong class="fig">{{ moneyCompact(projectedSummary.totalPremium) }}</strong>
          <small>{{ qualifiedRows.length }} tickers above threshold</small>
        </article>
        <article>
          <span class="label">Contracts in scope</span>
          <strong class="fig">{{ compact(projectedSummary.totalContracts) }}</strong>
          <small>{{ exactCount(projectedSummary.anomalyContracts) }} contracts with current-tape flags</small>
        </article>
        <article>
          <span class="label">Sweep-class premium</span>
          <strong class="fig">{{ moneyCompact(projectedSummary.sweepPremium) }}</strong>
          <small>{{ exactCount(projectedSummary.sweepContracts) }} contracts</small>
        </article>
        <article class="freshness-stat">
          <span class="label">Provider age</span>
          <strong class="fig">{{ providerFreshness }}</strong>
          <small>{{ payload.asof ? `As of ${payload.asof}` : 'Timestamp unavailable' }}</small>
          <span class="fresh-state label" :class="providerFreshnessState">{{ providerFreshnessState.toUpperCase() }}</span>
        </article>
      </section>

      <Panel label="What deserves review" index="01" :meta="reviewMeta" flush live>
        <template #action>
          <button type="button" class="panel-action label" :disabled="!reviewRows.length" @click="downloadAggregateCsv">
            EXPORT CSV
          </button>
        </template>

        <div v-if="reviewRows.length" class="table-scroll review-scroll">
          <table class="grid review-table">
            <thead>
              <tr>
                <th class="label">Review</th>
                <th class="label">Desk next step</th>
                <th class="label num">Sample / change</th>
                <th class="label">Call / put mix</th>
                <th class="label">Concentration</th>
                <th class="label">Underlying</th>
                <th class="label">Activity lean</th>
                <th><span class="sr-only">Open symbol</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in reviewRows" :key="row.symbol" :class="{ incoming: symbolPulse(row.symbol).newPrints > 0 }">
                <td class="review-symbol">
                  <span class="row-rank fig">{{ String(index + 1).padStart(2, '0') }}</span>
                  <button type="button" class="symbol-button fig" @click="openSymbol(row.symbol)">
                    {{ row.symbol }}
                  </button>
                  <span v-if="!pulse.baseline" class="table-rank-move fig" :class="rankMoveClass(row.symbol)">{{ rankMoveLabel(row.symbol) }}</span>
                </td>
                <td class="reason-cell action-cell" :class="actionInsight(row).leanState">
                  <span class="priority-chip label" :class="actionInsight(row).priority">{{ actionInsight(row).priority.toUpperCase() }}</span>
                  <strong>{{ actionInsight(row).action }}</strong>
                  <small>Focus {{ actionInsight(row).focus }} · {{ actionInsight(row).why }}</small>
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
                  <small v-if="pulse.baseline" class="fig">latest sample · {{ exactCount(row.contract_count) }} contracts</small>
                  <small v-else-if="symbolPulse(row.symbol).newPrints > 0" class="fig incoming-copy">
                    +{{ moneyCompact(symbolPulse(row.symbol).newPremium) }} · {{ symbolPulse(row.symbol).newPrints }} new vs prior sample
                  </small>
                  <small v-else class="fig">{{ signedMoneyCompact(symbolPulse(row.symbol).windowPremiumDelta) }} vs prior sample</small>
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
                  <strong>{{ tapeStats(row.symbol)?.topStrike ?? (row.average_dte == null ? DASH : `${num(row.average_dte, 1)}D avg`) }}</strong>
                  <small>{{ tapeStats(row.symbol)?.topDteBucket ?? `${fractionPercent(row.average_otm_pct)} avg OTM` }}</small>
                </td>
                <td class="price-cell">
                  <strong class="fig">{{ priceRead(row).spot }}</strong>
                  <small :class="priceRead(row).tone">{{ priceRead(row).move }} · {{ priceRead(row).detail }}</small>
                </td>
                <td class="direction-cell" :class="directionRead(row.symbol).state">
                  <span class="direction-chip label">{{ directionRead(row.symbol).label }}</span>
                  <small>{{ directionRead(row.symbol).detail }}</small>
                </td>
                <td class="open-cell">
                  <button type="button" class="row-open label" :aria-label="`Review ${row.symbol} options`" @click="openSymbol(row.symbol)">
                    OPEN <span aria-hidden="true">→</span>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="filteredRows.length > DEFAULT_REVIEW_ROWS" class="queue-footer">
          <span class="label">
            {{ showAllReviews
              ? `ALL ${filteredRows.length} MATCHES VISIBLE`
              : `TOP ${DEFAULT_REVIEW_ROWS} SHOWN · ${filteredRows.length - DEFAULT_REVIEW_ROWS} LOWER-PRIORITY MATCHES COLLAPSED` }}
          </span>
          <button type="button" class="panel-action label" @click="showAllReviews = !showAllReviews">
            {{ showAllReviews ? 'COLLAPSE TO TOP 12' : `SHOW ALL ${filteredRows.length}` }}
          </button>
        </div>
        <div v-if="!reviewRows.length" class="no-filter-results">
          <strong>No ticker matches this filter combination.</strong>
          <p>The source data is still present; only this local view is empty.</p>
          <button type="button" class="empty-action label" @click="clearFilters">RESET FILTERS</button>
        </div>
      </Panel>

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
          <span class="drawer-action label">{{ tapeExpanded ? 'HIDE' : 'SHOW TAPE' }} <i aria-hidden="true">⌄</i></span>
        </button>

        <div v-if="tapeExpanded" id="flow-raw-tape" class="drawer-body">
          <div class="tape-toolbar">
            <p>
              Filters above also apply here. <strong>C/P feeds the activity lean; signed buy/sell is separate.</strong>
              Aggressor is shown only when the provider supplies it.
            </p>
            <button type="button" class="panel-action label" :disabled="!tapeRows.length" @click="downloadTapeCsv">
              EXPORT TAPE CSV
            </button>
          </div>

          <div v-if="tapeRows.length" class="table-scroll tape-scroll">
            <table class="grid tape-table">
              <thead>
                <tr>
                  <th class="label">Time UTC</th>
                  <th class="label">Symbol</th>
                  <th class="label">Contract</th>
                  <th class="label">Expiry / distance</th>
                  <th class="label num">Fill × contracts</th>
                  <th class="label">Class</th>
                  <th class="label num">Premium</th>
                  <th class="label">Sample percentile</th>
                  <th class="label">Aggressor</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(row, index) in tapeRows"
                  :key="`${row.timestamp}-${row.symbol}-${row.expiry}-${row.strike}-${index}`"
                  :class="{ incoming: isNewPrint(row) }"
                >
                  <td class="fig" :title="row.timestamp">{{ tapeTime(row.timestamp) }}</td>
                  <td>
                    <button v-if="row.symbol" type="button" class="symbol-button fig" @click="openSymbol(row.symbol)">
                      {{ row.symbol }}
                    </button>
                    <span v-else>{{ DASH }}</span>
                    <span v-if="isNewPrint(row)" class="new-badge label">NEW</span>
                  </td>
                  <td class="contract-cell">
                    <span class="right-chip label" :class="row.right">{{ row.right.toUpperCase() }}</span>
                    <span class="fig">{{ usd(row.strike, 2) }}</span>
                  </td>
                  <td class="expiry-cell fig" :title="row.expiry ?? undefined">
                    <strong>{{ shortDate(row.expiry) }}</strong>
                    <small>{{ row.dte == null ? DASH : `${num(row.dte, 0)}D` }} · {{ fractionPercent(row.otm_pct) }} OTM</small>
                  </td>
                  <td class="execution-cell num fig">
                    <strong>{{ usd(row.price, 2) }}</strong>
                    <small>× {{ exactCount(row.contracts ?? row.volume) }}</small>
                  </td>
                  <td>
                    <span class="class-chip label" :class="{ heuristic: heuristicClass(row) }" :title="tradeClassTitle(row)">
                      {{ row.trade_class?.toUpperCase() ?? 'UNCLASSIFIED' }}<sup v-if="heuristicClass(row)">H</sup>
                    </span>
                  </td>
                  <td class="fig num tape-premium">{{ moneyCompact(row.premium) }}</td>
                  <td>
                    <div class="heat-cell" :class="heatClass(row.premium_percentile)">
                      <span class="heat-track" aria-hidden="true"><i :style="{ width: heatWidth(row.premium_percentile) }" /></span>
                      <span class="fig">{{ fractionPercent(row.premium_percentile, 0) }}</span>
                    </div>
                  </td>
                  <td><span class="aggressor label">{{ aggressorLabel(row) }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="tape-unavailable">
            <AppIcon name="density" :size="22" />
            <div>
              <strong>{{ baseSummary?.tape_detail_available === false ? 'Contract detail is unavailable for this snapshot.' : 'No raw prints match the active filters.' }}</strong>
              <p>{{ baseSummary?.tape_detail_available === false ? 'Ticker aggregates remain valid; individual contracts were not supplied.' : 'Reset filters or choose another activity slice.' }}</p>
            </div>
          </div>
        </div>
      </section>

      <section class="method-strip" aria-label="Flow interpretation rules">
        <article>
          <span class="label">Ranking</span>
          <p>Review priority recomputes after every fresh {{ pollSeconds }}s poll. “New” and sample changes compare overlapping provider samples; a negative change can mean old prints rolled out.</p>
        </article>
        <article>
          <span class="label">Direction gate</span>
          <p>Activity lean (bullish/bearish) uses premium mix + price impulse; signed trade direction requires provider buy/sell. Models appear only when calibrated, setup-qualified, ENTER-state, and ≥55%.</p>
        </article>
        <article>
          <span class="label">Actionable insights</span>
          <p>Desk next steps tell you what to open and what to check (strike, DTE, walls). They are research triage — not order authorization. {{ providerBasis }} · LATEST PROVIDER SAMPLE · ≥ ${{ compact(minPremium) }}.</p>
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

/* ── 01 Control Rail ─────────────────────────────────────────────────────── */
.control-rail {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
  gap: var(--s4);
  min-height: 60px;
  padding: var(--s3) var(--s5);
  border: var(--hair) solid var(--border-strong);
  border-left: 3px solid var(--phosphor);
  background-color: var(--surface-raised);
  flex-wrap: wrap;
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
  font-size: 9px;
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
  border-radius: 2px;
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
  font-size: 10px;
  font-weight: 700;
  color: var(--ink-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.thresholds {
  display: flex;
  border: var(--hair) solid var(--border-strong);
  border-radius: 2px;
  overflow: hidden;
}

.thresholds button {
  min-height: 32px;
  padding: 4px 12px;
  color: var(--text-secondary);
  border: 0;
  border-right: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  font-weight: 700;
  transition: all var(--dur-fast) var(--ease-out);
}
.thresholds button:last-child { border-right: 0; }

.thresholds button:hover:not(.active) {
  color: var(--text-primary);
  background: var(--surface-overlay);
}

.thresholds button.active {
  color: var(--void);
  background: var(--phosphor);
  font-weight: 800;
}

.control-status {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-left: auto;
  color: var(--text-tertiary);
  text-align: right;
  font-size: 10px;
}

.control-status span:first-child {
  color: var(--status-live);
  font-weight: 700;
}

.refresh-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-width: 116px;
  min-height: 34px;
  padding: 6px 14px;
  color: var(--void);
  border: var(--hair) solid var(--phosphor);
  background: var(--phosphor);
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 10px;
  letter-spacing: var(--track-label);
  border-radius: 2px;
  transition: all var(--dur-fast) ease;
}

.refresh-button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--phosphor) 85%, #fff);
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
.stale-copy { color: inherit; font-weight: 700; }

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
  border-radius: 2px;
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
  font-size: 10px;
  font-weight: 750;
  cursor: pointer;
  border-radius: 2px;
}
.empty-action:hover {
  color: var(--void);
  background: var(--phosphor);
}

.section-kicker { color: var(--phosphor); font-size: 10px; font-weight: 700; letter-spacing: 0.08em; }

/* ── Live Pulse Banner ───────────────────────────────────────────────────── */
.live-pulse {
  display: grid;
  grid-template-columns: minmax(360px, 1.4fr) repeat(3, minmax(190px, 1fr));
  min-width: 0;
  border: var(--hair) solid var(--border-strong);
  border-left: 3px solid var(--phosphor);
  background: var(--surface-raised);
}

.live-pulse.brief-stale { border-left-color: var(--warn); }
.brief-stale .section-kicker { color: var(--warn); }

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
  font-size: 9px;
  font-weight: 700;
}

.pulse-cadence span:first-child { color: var(--phosphor); }
.pulse-cadence i { display: inline-block; width: 6px; height: 6px; margin-right: 5px; background: currentColor; border-radius: 50%; }

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
  transition: all var(--dur-fast) var(--ease-out);
}

.triage-pick:hover {
  background: var(--surface-overlay);
  border-color: var(--rule-hi);
}

.triage-index {
  position: absolute;
  top: var(--s3);
  right: var(--s4);
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 750;
}

.triage-pick > .label { padding-right: 26px; color: var(--text-tertiary); font-size: 10px; font-weight: 700; }
.triage-symbol-line { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s2); margin-top: var(--s2); }
.triage-symbol-line strong { color: var(--phosphor); font-size: var(--t-fig); font-weight: 750; }
.triage-symbol-line b { color: var(--text-primary); font-size: var(--t-small); font-weight: 750; }

.triage-lean {
  display: inline-flex;
  margin-top: 7px;
  padding: 1px 7px;
  width: fit-content;
  border-radius: 2px;
  font-weight: 800;
  letter-spacing: 0.05em;
  font-size: 9px;
  border: var(--hair) solid currentColor;
}
.triage-lean.bullish,
.triage-lean.model-bullish {
  color: #52c78f;
  border-color: #52c78f;
  background: rgba(82, 199, 143, 0.14);
}
.triage-lean.bearish,
.triage-lean.model-bearish {
  color: #f06d7b;
  border-color: #f06d7b;
  background: rgba(240, 109, 123, 0.14);
}
.triage-lean.mixed {
  color: #e5b048;
  border-color: #e5b048;
  background: rgba(229, 176, 72, 0.14);
}

.triage-action {
  margin-top: 6px;
  color: var(--text-primary);
  font-size: 11px;
  font-weight: 650;
  line-height: 1.35;
}
.triage-focus {
  margin-top: var(--s1);
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.4;
}
.triage-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 7px; }
.triage-tags span {
  padding: 1px 5px;
  color: var(--text-secondary);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  font-size: 9px;
  font-weight: 700;
  border-radius: 2px;
}
.triage-tags .sweep,
.triage-tags .flag { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 55%, var(--border-strong)); }
.triage-tags .size { color: var(--phosphor); border-color: var(--phosphor-dim); }

.triage-open {
  margin-top: auto;
  padding-top: var(--s3);
  color: var(--phosphor);
  border-top: var(--hair) solid var(--border-subtle);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.05em;
}
.triage-pick.bullish,
.triage-pick.model-bullish { border-top-color: #52c78f; }
.triage-pick.bearish,
.triage-pick.model-bearish { border-top-color: #f06d7b; }
.triage-pick.mixed { border-top-color: #e5b048; }

/* ── Filter Shelf ────────────────────────────────────────────────────────── */
.filter-shelf {
  display: grid;
  grid-template-columns: minmax(132px, 0.65fr) minmax(150px, 0.8fr) auto auto minmax(120px, 0.6fr) minmax(150px, 0.7fr) auto;
  align-items: end;
  gap: var(--s3);
  padding: var(--s4);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-raised);
}

.filter-intro {
  display: flex;
  flex-direction: column;
  align-self: center;
  gap: 3px;
  min-width: 0;
}
.filter-intro .label { font-size: 10px; font-weight: 700; color: var(--ink-dim); }
.filter-intro strong { color: var(--text-primary); font: 700 var(--t-small) var(--font-display); }
.filter-intro small { color: var(--text-tertiary); font-size: 9px; line-height: 1.35; }

.search-filter,
.select-filter {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.search-filter > .label,
.select-filter > .label,
.seg-filter legend {
  font-size: 10px;
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
  border-radius: 2px;
}
.input-shell:focus-within {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}
.input-shell input {
  width: 100%;
  min-width: 0;
  outline: none;
  color: var(--text-primary);
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  text-transform: uppercase;
}
.input-shell input::placeholder { color: var(--text-tertiary); text-transform: none; }

.seg-filter { min-width: 0; border: 0; }
.seg-filter > div { display: flex; border: var(--hair) solid var(--border-strong); border-radius: 2px; overflow: hidden; }
.seg-filter > small { display: block; max-width: 28ch; margin-top: 4px; color: var(--text-tertiary); font-size: 9px; line-height: 1.3; }
.seg-filter button {
  min-height: 32px;
  padding: 3px 10px;
  color: var(--text-secondary);
  border: 0;
  border-right: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  font-weight: 700;
  transition: all var(--dur-fast) ease;
}
.seg-filter button:last-child { border-right: 0; }
.seg-filter button:hover:not(.active) { color: var(--text-primary); background: var(--surface-overlay); }
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
  border-radius: 2px;
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
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.06em;
  border-radius: 2px;
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
  min-height: 286px;
  padding: var(--s4);
  border-right: var(--hair) solid var(--border-subtle);
  background: var(--surface-raised);
  transition: background var(--dur-fast) var(--ease-out);
}
.major-card:last-child { border-right: 0; }
.major-card.incoming { background: var(--phosphor-wash); }
.major-card.absent { color: var(--text-tertiary); background: var(--surface-base); }

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
button.major-symbol:hover { color: var(--ink); }
.major-rank { margin-left: auto; color: var(--text-tertiary); font-size: var(--t-micro); font-weight: 700; }

.rank-move,
.table-rank-move {
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  font-weight: 700;
}
.rank-move.up,
.table-rank-move.up { color: var(--long); }
.rank-move.down,
.table-rank-move.down { color: var(--short); }

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
  border-radius: 2px;
}

.major-premium {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s3);
  margin-top: var(--s2);
  padding-bottom: var(--s2);
  border-bottom: var(--hair) solid var(--border-subtle);
}
.major-premium div { min-width: 0; }
.major-premium strong { display: block; overflow: hidden; margin-top: 2px; color: var(--text-primary); font-size: var(--t-small); font-weight: 750; text-overflow: ellipsis; }

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
  border-radius: 2px;
}
.direction-arrow {
  font: 800 var(--t-fig) / 1 var(--font-data);
  text-align: center;
}
.major-direction strong { display: block; color: inherit; font-size: 11px; font-weight: 800; }
.major-direction small { display: block; margin-top: 1px; color: var(--text-tertiary); font-size: var(--t-micro); }
.major-direction.bullish { color: #52c78f; border-color: #52c78f; background: rgba(82, 199, 143, 0.14); }
.major-direction.bearish { color: #f06d7b; border-color: #f06d7b; background: rgba(240, 109, 123, 0.14); }
.major-direction.mixed { color: #e5b048; border-color: #e5b048; background: rgba(229, 176, 72, 0.14); }
.major-direction.model-bullish { color: #52c78f; border-color: color-mix(in srgb, #52c78f 45%, var(--border-strong)); }
.major-direction.model-bearish { color: #f06d7b; border-color: color-mix(in srgb, #f06d7b 45%, var(--border-strong)); }

.major-identity { margin-top: var(--s2); }
.major-identity small { display: block; margin-top: 4px; color: var(--text-tertiary); font-size: var(--t-micro); }

.call-text { color: var(--call-hi); font-weight: 750; }
.put-text { color: var(--put-hi); font-weight: 750; }
.identity-labels { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s2); font-size: 10px; }

.identity-bar {
  display: flex;
  width: 100%;
  height: 6px;
  overflow: hidden;
  background: var(--border-subtle);
  border-radius: 1px;
}
.call-segment { display: block; background: var(--call); }
.put-segment { display: block; background: var(--put); }
.identity-note {
  display: block;
  margin-top: 4px;
  color: var(--text-tertiary);
  font: 700 8px var(--font-display);
  letter-spacing: .05em;
}

.major-concentration {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s2);
  margin-top: var(--s3);
}
.major-concentration div { min-width: 0; }
.major-concentration dd { overflow: hidden; margin-top: 2px; color: var(--text-primary); font-size: var(--t-tiny); font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.major-concentration small { display: block; margin-top: 1px; font-size: 9px; }

.major-action {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: var(--s3);
  padding: var(--s2) var(--s3);
  color: var(--text-secondary);
  border: var(--hair) solid var(--border-subtle);
  background: var(--surface-base);
  font-size: var(--t-micro);
  line-height: 1.35;
  border-radius: 2px;
}
.major-action > span {
  color: var(--phosphor);
  font-weight: 800;
  letter-spacing: 0.05em;
}
.major-action.bullish > span,
.major-action.model-bullish > span { color: #52c78f; }
.major-action.bearish > span,
.major-action.model-bearish > span { color: #f06d7b; }
.major-action.mixed > span { color: #e5b048; }

.major-open {
  width: 100%;
  margin-top: auto;
  min-height: 32px;
  padding: var(--s2) var(--s3);
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.05em;
  border-radius: 2px;
  cursor: pointer;
  transition: all var(--dur-fast) ease;
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
.major-absent strong { color: var(--text-secondary); }
.major-absent p { margin-top: 4px; font-size: var(--t-small); }

/* ── Snapshot Strip ──────────────────────────────────────────────────────── */
.snapshot-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-raised);
}

.snapshot-strip article {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  padding: var(--s4) var(--s5);
  border-right: var(--hair) solid var(--border-subtle);
}
.snapshot-strip article:last-child { border-right: 0; }
.snapshot-strip strong {
  color: var(--text-primary);
  font-size: 1.35rem;
  font-weight: 800;
  line-height: 1.1;
}
.snapshot-strip small {
  overflow: hidden;
  color: var(--text-tertiary);
  font-size: var(--t-micro);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fresh-state {
  position: absolute;
  top: var(--s2);
  right: var(--s2);
  padding: 1px 5px;
  color: var(--text-tertiary);
  border: var(--hair) solid var(--border-strong);
  font-size: 9px;
  font-weight: 800;
  border-radius: 2px;
}
.fresh-state.live { color: var(--status-live); border-color: var(--phosphor-dim); background: var(--phosphor-wash); }
.fresh-state.stale { color: var(--warn); border-color: var(--warn); background: var(--warn-wash); }
.fresh-state.unavailable { color: var(--short); border-color: var(--short); }

.freshness-stat > .label:first-child { padding-right: 58px; }

/* ── Review Table (Panel 01) ─────────────────────────────────────────────── */
.table-scroll {
  min-width: 0;
  overflow: auto;
}
.review-scroll { max-height: 620px; }
.tape-scroll { max-height: 610px; }

.review-table {
  min-width: 1120px;
  font-size: var(--t-tiny);
  border-collapse: collapse;
}

.review-table th {
  padding: var(--s3) var(--s4);
  color: var(--ink-dim);
  background: var(--surface-overlay);
  border-bottom: var(--hair) solid var(--border-strong);
  position: sticky;
  top: 0;
  z-index: 1;
  font-weight: 750;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.review-table td {
  padding: var(--s3) var(--s4);
  border-bottom: var(--hair) solid var(--border-subtle);
  vertical-align: middle;
}
.review-table tbody tr:hover { background: var(--surface-overlay); }
.review-table tbody tr.incoming,
.tape-table tbody tr.incoming { background: var(--phosphor-wash); }

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
  color: var(--phosphor);
  font-weight: 750;
  font-size: 13px;
  cursor: pointer;
}
.symbol-button:hover { color: var(--ink); }

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
.price-cell strong { display: block; color: var(--text-primary); font-size: var(--t-small); }
.price-cell small { display: block; max-width: 21ch; margin-top: 3px; color: var(--text-tertiary); font-size: var(--t-micro); line-height: 1.35; white-space: normal; }
.price-cell small.pos { color: var(--long); }
.price-cell small.neg { color: var(--short); }

.priority-chip {
  display: inline-flex;
  margin-bottom: 3px;
  padding: 1px 6px;
  border: var(--hair) solid currentColor;
  border-radius: 2px;
  font-weight: 800;
  letter-spacing: 0.05em;
  font-size: 9px;
}
.priority-chip.now {
  color: #52c78f;
  border-color: #52c78f;
  background: rgba(82, 199, 143, 0.14);
}
.priority-chip.soon {
  color: #e5b048;
  border-color: #e5b048;
  background: rgba(229, 176, 72, 0.14);
}
.priority-chip.watch { color: var(--text-secondary); border-color: var(--border-strong); }
.priority-chip.skip { color: var(--text-tertiary); opacity: 0.85; border-color: var(--border-subtle); }

.tag-line { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 5px; }
.tag-line .evidence-tag { min-height: 18px; padding: 1px 5px; font-size: var(--t-micro); font-weight: 700; border-radius: 2px; }

.direction-cell { min-width: 180px; }
.direction-chip {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 1px 7px;
  border-radius: 2px;
  font-weight: 800;
  letter-spacing: 0.04em;
  font-size: 10px;
  border: var(--hair) solid currentColor;
}
.direction-cell.bullish .direction-chip { color: #52c78f; border-color: #52c78f; background: rgba(82, 199, 143, 0.14); }
.direction-cell.bearish .direction-chip { color: #f06d7b; border-color: #f06d7b; background: rgba(240, 109, 123, 0.14); }
.direction-cell.mixed .direction-chip { color: #e5b048; border-color: #e5b048; background: rgba(229, 176, 72, 0.14); }
.direction-cell.model-bullish .direction-chip { color: #52c78f; border-color: color-mix(in srgb, #52c78f 45%, var(--border-strong)); }
.direction-cell.model-bearish .direction-chip { color: #f06d7b; border-color: color-mix(in srgb, #f06d7b 45%, var(--border-strong)); }

.row-open {
  min-height: 26px;
  padding: 3px 8px;
  color: var(--call-hi);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  font-size: 10px;
  font-weight: 750;
  border-radius: 2px;
  cursor: pointer;
  transition: all var(--dur-fast) ease;
}
.row-open:hover {
  color: var(--void);
  background: var(--call-hi);
  border-color: var(--call-hi);
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
  font-size: 10px;
  font-weight: 750;
  letter-spacing: var(--track-label);
  color: var(--text-secondary);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  border-radius: 2px;
  cursor: pointer;
}
.panel-action:hover:not(:disabled) {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

/* ── Raw Tape Table (Panel 02) ───────────────────────────────────────────── */
.evidence-drawer {
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-raised);
}
.evidence-drawer.open { border-color: var(--rule-hi); }

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
.drawer-toggle:hover { background: var(--surface-overlay); }
.drawer-index { color: var(--phosphor); font-size: var(--t-micro); font-weight: 800; }
.drawer-copy strong { color: var(--text-primary); font: 700 var(--t-small) var(--font-display); }
.drawer-copy small { margin-top: 2px; color: var(--text-tertiary); font-size: var(--t-micro); }
.drawer-action { color: var(--phosphor); font-weight: 750; font-size: 10px; }

.tape-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s4);
  padding: var(--s3) var(--s4);
  background: var(--surface-base);
  border-bottom: var(--hair) solid var(--border-subtle);
}

.tape-table {
  min-width: 1080px;
  font-size: var(--t-tiny);
  border-collapse: collapse;
}
.tape-table th {
  padding: var(--s2) var(--s3);
  color: var(--ink-dim);
  background: var(--surface-overlay);
  border-bottom: var(--hair) solid var(--border-strong);
  font-weight: 750;
  font-size: 10px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.tape-table td {
  padding: var(--s2) var(--s3);
  border-bottom: var(--hair) solid var(--border-subtle);
  vertical-align: middle;
}
.tape-table tbody tr:hover { background: var(--surface-overlay); }

.right-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 20px;
  padding: 1px 6px;
  border-radius: 2px;
  font-weight: 800;
  font-size: 10px;
}
.right-chip.call { color: var(--call-hi); border: var(--hair) solid var(--call); background: var(--call-wash); }
.right-chip.put { color: var(--put-hi); border: var(--hair) solid var(--put); background: var(--put-wash); }

.class-chip {
  display: inline-flex;
  align-items: center;
  min-height: 19px;
  padding: 1px 5px;
  color: var(--text-secondary);
  border: var(--hair) solid var(--border-strong);
  background: var(--surface-base);
  font-size: 9px;
  font-weight: 750;
  border-radius: 2px;
}
.class-chip.heuristic { color: var(--warn); border-color: var(--warn); background: var(--warn-wash); }

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
.heat-track i { display: block; height: 100%; background: var(--text-tertiary); }
.heat-cell.warm .heat-track i { background: var(--warn); }
.heat-cell.hot .heat-track i { background: var(--phosphor); }

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
.method-strip article:last-child { border-right: 0; }
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
  .live-pulse { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .pulse-copy { grid-column: 1 / -1; border-bottom: var(--hair) solid var(--border-subtle); }
  .pulse-stat:first-of-type { border-left: 0; }
  .major-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .major-card:nth-child(2) { border-right: 0; }
  .major-card:nth-child(n + 3) { border-top: var(--hair) solid var(--border-subtle); }
  .filter-shelf { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .select-filter { min-width: 140px; }
  .reset-filter { align-self: end; }
}

@media (max-width: 1100px) {
  .control-rail {
    display: grid;
    grid-template-columns: minmax(250px, 1fr) auto;
  }
  .threshold-control { justify-content: flex-end; }
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
  .live-pulse { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pulse-stat:nth-of-type(odd) { border-left: 0; }
  .pulse-stat:nth-of-type(n + 3) { border-top: var(--hair) solid var(--border-subtle); }
  .majors-head { align-items: flex-start; flex-direction: column; gap: var(--s2); }
  .majors-head p { text-align: left; }
  .snapshot-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .snapshot-strip article:nth-child(2) { border-right: 0; }
  .snapshot-strip article:nth-child(n + 3) { border-top: var(--hair) solid var(--border-subtle); }
  .filter-shelf { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .seg-filter > div { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); }
  .seg-filter:not(.activity-filter) > div { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .seg-filter button { border-right: 0; }
  .seg-filter button:last-child { border-right: var(--hair) solid var(--border-strong); }
  .drawer-toggle { grid-template-columns: 28px minmax(0, 1fr) auto; }
  .drawer-note { display: none; }
  .method-strip { grid-template-columns: minmax(0, 1fr); }
  .method-strip article { border-right: 0; border-bottom: var(--hair) solid var(--border-subtle); }
  .method-strip article:last-child { border-bottom: 0; }
}

@media (max-width: 620px) {
  .control-rail { grid-template-columns: minmax(0, 1fr); }
  .control-identity,
  .threshold-control { width: 100%; }
  .threshold-control { align-items: flex-start; flex-direction: column; gap: var(--s2); }
  .thresholds { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); width: 100%; }
  .control-status,
  .refresh-button { grid-column: 1; grid-row: auto; }
  .refresh-button { width: 100%; margin-left: 0; }
  .live-pulse { grid-template-columns: minmax(0, 1fr); }
  .pulse-copy { grid-column: auto; }
  .triage-pick { min-height: 142px; border-top: var(--hair) solid var(--border-subtle); border-left: 0; }
  .pulse-stat,
  .pulse-stat:nth-of-type(odd) { border-left: 0; border-top: var(--hair) solid var(--border-subtle); }
  .major-grid { grid-template-columns: minmax(0, 1fr); }
  .major-card,
  .major-card:nth-child(2) { min-height: 244px; border-right: 0; border-top: var(--hair) solid var(--border-subtle); }
  .major-card:first-child { border-top: 0; }
  .snapshot-strip { grid-template-columns: minmax(0, 1fr); }
  .snapshot-strip article { border-right: 0; border-top: var(--hair) solid var(--border-subtle); }
  .snapshot-strip article:first-child { border-top: 0; }
  .filter-shelf { grid-template-columns: minmax(0, 1fr); }
  .queue-footer { align-items: flex-start; flex-direction: column; }
  .drawer-toggle { grid-template-columns: 24px minmax(0, 1fr); }
  .drawer-action { grid-column: 2; }
  .tape-toolbar { align-items: flex-start; flex-direction: column; }
}

@media (prefers-reduced-motion: reduce) {
  .drawer-action i,
  .thresholds button,
  .refresh-button,
  .panel-action,
  .row-open { transition: none; }
}
</style>
