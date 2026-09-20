<script setup lang="ts">
import { computed, inject, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  api,
  type ActivityFlagRow,
  type QuoteMark,
  type StatusPayload,
  type Readiness,
  type ScanDepth,
  type ScanJob,
  type Trajectory,
} from '@/api'
import type { Resource } from '@/composables/useResource'
import { num, pctFrac, signedPct, tone, usd, DASH } from '@/format'
import { sparkline } from '@/charts'
import { loadWatchlist, toggleWatchlistSymbol } from '@/watchlist'
import Panel from '@/components/Panel.vue'
import VerdictChip from '@/components/VerdictChip.vue'
import RegimeStateBadge from '@/components/RegimeStateBadge.vue'
import {
  isRegimeMeasurable,
  formatDistancePercent,
  type PriceDrawTelemetryPayload,
  type PriceDrawLevel,
} from '@/priceDrawContracts'

/**
 * The Desk View.
 *
 * Provides a high-density, command-center dashboard for live-capital interlocks,
 * PEAD pre-market setups, directional trading signals, and custom ticker probing.
 */
const status = inject<Resource<StatusPayload>>('status')!
const readiness = inject<Resource<Readiness>>('readiness')!
const router = useRouter()

const scanning = ref(false)
const scanDepth = ref<ScanDepth>('quick')
const scanMsg = ref<string | null>(null)
const scanJob = ref<ScanJob | null>(null)
let scanPollToken = 0

// Filtering state for dropdowns & views
const peadFilter = ref<'all' | 'flagged' | 'long' | 'short'>('all')
const signalFilter = ref<'all' | 'entered' | 'actionable' | 'long' | 'short'>('all')
const dualViewMode = ref<'split' | 'pead' | 'directional'>('split')

/**
 * Confidence contract (must match tools/render_dashboard.py):
 *  - ENTER authorization only when calibrated p ≥ 0.65
 *  - 0.55–0.65 is WATCH / near coin-flip — never sold as high confidence
 *  - PEAD is ordinal (gate-driven) and cannot authorize entries
 */
const ENTER_EDGE = 0.65
const ACTIONABLE_EDGE = 0.55

// Custom Watchlist & Ad-hoc probe
const customTickerInput = ref('')
const probing = ref(false)
const probeErr = ref<string | null>(null)
const customWatchlist = ref<string[]>(loadWatchlist())
const probeResults = ref<Record<string, Trajectory | null>>({})
const liveMarks = ref<Record<string, QuoteMark>>({})
const regimeTelemetryMap = ref<Record<string, PriceDrawTelemetryPayload>>({})

let watchlistTimer: number | undefined
let marksTimer: number | undefined
let appliedScanAsof = ''

function onVisibilityChange(): void {
  if (document.visibilityState === 'visible') {
    void refreshBoardMarks()
  }
}

onMounted(() => {
  customWatchlist.value = loadWatchlist()
  document.addEventListener('visibilitychange', onVisibilityChange)
  void probeWatchlist(true)
  void resumeScanJob()
  void refreshBoardMarks()
  // Keep personal watchlist fresh even when the shared status asof is quiet.
  watchlistTimer = window.setInterval(() => void probeWatchlist(true), 60_000)
  marksTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible') void refreshBoardMarks()
  }, 20_000)
})

onUnmounted(() => {
  document.removeEventListener('visibilitychange', onVisibilityChange)
  scanPollToken += 1
  if (watchlistTimer !== undefined) clearInterval(watchlistTimer)
  if (marksTimer !== undefined) clearInterval(marksTimer)
})

async function probeSymbol(sym: string): Promise<void> {
  const clean = sym.trim().toUpperCase()
  if (!clean) return
  probing.value = true
  probeErr.value = null
  try {
    // The watchlist renders price/stats only. Skip the full-market qlib panel;
    // Desk signals already carry the calibrated/ordinal model context used here.
    const t = await api.trajectory(clean, '1m', { includeQlib: false })
    probeResults.value[clean] = t
    if (!customWatchlist.value.includes(clean)) {
      customWatchlist.value = toggleWatchlistSymbol(customWatchlist.value, clean).symbols
    }
    customTickerInput.value = ''
  } catch (e) {
    probeErr.value = e instanceof Error ? e.message : String(e)
  } finally {
    probing.value = false
  }
}

async function probeWatchlist(force = false): Promise<void> {
  const targets = customWatchlist.value.filter((sym) => force || !probeResults.value[sym])
  if (!targets.length) return
  await Promise.all(
    targets.map(async (sym) => {
      try {
        probeResults.value[sym] = await api.trajectory(sym, '1m', { includeQlib: false })
      } catch {
        /* keep prior bar if present; retry on next refresh */
      }
    }),
  )
}

// When the shared status feed recovers after a backend outage, re-probe the
// watchlist so rows do not stay stuck on "—" until a full page reload.
watch(
  () => status.data.value?.asof,
  (asof, prev) => {
    if (asof && asof !== prev && (!appliedScanAsof || asof >= appliedScanAsof)) {
      void probeWatchlist(true)
      void refreshBoardMarks()
    }
  },
)

function removeWatchlistSymbol(sym: string): void {
  customWatchlist.value = toggleWatchlistSymbol(customWatchlist.value, sym).symbols
  delete probeResults.value[sym]
}

/** Prefer stats.last_price; fall back to last bar close so rows never go blank when series exists. */
function watchPrice(sym: string): number | null {
  const t = probeResults.value[sym]
  if (!t) return null
  const fromStats = t.stats?.last_price
  if (fromStats != null && Number.isFinite(fromStats)) return fromStats
  const last = t.series?.at(-1)?.c
  return last != null && Number.isFinite(last) ? last : null
}

function scanDelay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function applyCompletedScan(job: ScanJob): void {
  const result = job.result
  if (!result) return
  status.data.value = result.data
  status.error.value = null
  status.fetchedAt.value = new Date().toISOString()
  scanMsg.value = result.message
  appliedScanAsof = result.data?.asof || result.asof || ''
  void refreshBoardMarks()
}

function boardSymbols(): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  const push = (value: string | undefined) => {
    const sym = String(value || '')
      .trim()
      .toUpperCase()
    if (!sym || seen.has(sym)) return
    seen.add(sym)
    out.push(sym)
  }
  for (const row of pead.value) push(row.symbol)
  for (const row of signals.value) push(row.symbol)
  for (const row of customWatchlist.value) push(row)
  return out.slice(0, 40)
}

async function refreshBoardMarks(): Promise<void> {
  const symbols = boardSymbols()
  if (!symbols.length) return
  try {
    const payload = await api.quotes(symbols)
    const next: Record<string, QuoteMark> = { ...liveMarks.value }
    for (const row of payload.rows) {
      if (row.symbol) next[row.symbol.toUpperCase()] = row
    }
    liveMarks.value = next
  } catch {
    /* keep last marks; the next tick retries */
  }

  // Fetch price attractors / regime telemetry for board and activity symbols
  const allSymbols = new Set<string>(symbols)
  for (const row of activity.value) {
    if (row.symbol) allSymbols.add(row.symbol.toUpperCase())
  }

  try {
    await Promise.allSettled(
      Array.from(allSymbols).map(async (sym) => {
        try {
          const data = await api.priceAttractors(sym)
          if (data) {
            regimeTelemetryMap.value[sym.toUpperCase()] = data
          }
        } catch {
          /* keep last or unmeasured */
        }
      }),
    )
  } catch {
    /* keep last marks */
  }
}

function regimeFor(sym: string | undefined): PriceDrawTelemetryPayload | null {
  if (!sym) return null
  return regimeTelemetryMap.value[sym.toUpperCase()] ?? null
}

function primaryMagnetFor(sym: string | undefined): PriceDrawLevel | null {
  return regimeFor(sym)?.primary_magnet ?? null
}

function markFor(sym: string): QuoteMark | null {
  return liveMarks.value[sym.toUpperCase()] ?? null
}

function markLast(sym: string): number | null {
  const last = markFor(sym)?.last
  return last != null && Number.isFinite(last) ? last : watchPrice(sym)
}

function markChg(sym: string): number | null {
  const live = markFor(sym)?.chg_1d_pct
  if (live != null && Number.isFinite(live)) return live
  const traj = probeResults.value[sym]?.stats?.chg_1d_pct
  return traj != null && Number.isFinite(traj) ? traj : null
}

async function trackScanJob(initial: ScanJob, token: number): Promise<void> {
  let current = initial
  scanJob.value = current
  scanDepth.value = current.depth
  while (token === scanPollToken && (current.state === 'queued' || current.state === 'running')) {
    await scanDelay(750)
    if (token !== scanPollToken) return
    const payload = await api.scanStatus(current.id)
    if (!payload.job) throw new Error(payload.message)
    current = payload.job
    scanJob.value = current
    scanMsg.value = current.message
  }
  if (token !== scanPollToken) return
  if (current.state === 'completed') {
    applyCompletedScan(current)
  } else if (current.state === 'failed') {
    scanMsg.value = current.error || current.message
  }
}

async function resumeScanJob(): Promise<void> {
  let token = scanPollToken
  try {
    const payload = await api.scanStatus()
    if (!payload.job || !['queued', 'running'].includes(payload.job.state)) return
    token = ++scanPollToken
    scanning.value = true
    scanMsg.value = payload.job.message
    await trackScanJob(payload.job, token)
  } catch {
    // Resume is opportunistic; the normal status feed remains usable.
  } finally {
    if (token === scanPollToken) scanning.value = false
  }
}

async function runScan(): Promise<void> {
  const token = ++scanPollToken
  scanning.value = true
  scanMsg.value = null
  try {
    const payload = await api.triggerScan(scanDepth.value)
    if (!payload.job) throw new Error(payload.message)
    scanMsg.value = payload.message
    await trackScanJob(payload.job, token)
  } catch (e) {
    scanMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (token === scanPollToken) scanning.value = false
  }
}

const r = computed(() => readiness.data.value)
const d = computed(() => status.data.value)

/* ---- typed narrowings --------------------------------------------------- */

interface PeadRow {
  symbol: string
  side: string
  setup_ok: boolean
  model: {
    probability: number | null
    raw_score: number
    confidence_kind: string
    state: string
    horizon_days: number
    entry_threshold: number | null
    id: string
    promotion_authorized: boolean
  }
  evidence: {
    pead_score: number
    gap_std: number
    vol_surge: number
  }
}
interface SignalRow {
  symbol: string
  side: string
  model: string
  horizon: string
  probability: number | null
  confidence_kind: string
  calibration_version: string | null
  setup_ok: boolean
  state: string
  reasons: string[]
  momentum: number
}
interface BoardRow {
  gate_file: string
  strategy: string
  features: string
  rank_ic: string
  net_return: string
  sharpe: string
  verdict: string
  validation_status: string
}

const pead = computed(() => (d.value?.pead_candidates ?? []) as unknown as PeadRow[])
const signals = computed(() => (d.value?.directional_signals ?? []) as unknown as SignalRow[])
const activity = computed(() => (d.value?.activity_scan?.rows ?? []) as ActivityFlagRow[])
const activityCoverage = computed(() => d.value?.activity_scan?.coverage)
const board = computed(() => (d.value?.leaderboard ?? []) as unknown as BoardRow[])
const sectors = computed(() => (d.value?.sector_flow as any)?.sectors_ranked ?? [])
const scan = computed(() => d.value?.scan_summary)
const reconciliation = computed(() => d.value?.signal_reconciliation)
const reconciledBySymbol = computed(
  () => new Map((reconciliation.value?.rows ?? []).map((row) => [row.symbol.toUpperCase(), row])),
)
// prettier-ignore
const signalsBySymbol = computed(() => new Map(signals.value.map((s) => [s.symbol?.toUpperCase() ?? '', s])))
// prettier-ignore
const peadBySymbol = computed(() => new Map(pead.value.map((p) => [p.symbol?.toUpperCase() ?? '', p])))

watch(
  () => scan.value?.depth,
  (depth) => {
    if (depth === 'quick' || depth === 'deep') scanDepth.value = depth
  },
  { immediate: true },
)

watch(
  () => [pead.value.length, signals.value.length, customWatchlist.value.join(',')],
  () => {
    void refreshBoardMarks()
  },
)

/* Filtering + confidence ranking */
const marketRegimeBreadth = computed(() => {
  let dampening = 0
  let amplification = 0
  let other = 0
  let unmeasured = 0
  let bullishPulls = 0
  let bearishPulls = 0

  const symbols = boardSymbols()
  for (const sym of symbols) {
    const tel = regimeTelemetryMap.value[sym.toUpperCase()]
    if (!tel || !tel.quality?.measurable || tel.regime_state === 'unmeasurable') {
      unmeasured++
      continue
    }
    if (tel.regime_state === 'volatility_dampening') {
      dampening++
    } else if (tel.regime_state === 'volatility_amplification') {
      amplification++
    } else {
      other++
    }

    if (tel.dominant_direction === 'bullish_pull') {
      bullishPulls++
    } else if (tel.dominant_direction === 'bearish_pull') {
      bearishPulls++
    }
  }

  const measured = dampening + amplification + other
  const dominantBias =
    bullishPulls > bearishPulls
      ? 'BULL PULL'
      : bearishPulls > bullishPulls
        ? 'BEAR PULL'
        : 'PIN / FLAT'

  return {
    dampening,
    amplification,
    other,
    unmeasured,
    measured,
    dominantBias,
    total: symbols.length,
  }
})

const peadFlagged = computed(
  () => pead.value.filter((p) => p.setup_ok || p.model?.state === 'FLAG').length,
)
const sigEntered = computed(() => signals.value.filter((s) => s.state === 'ENTER').length)
const sigHighConf = computed(
  () => signals.value.filter((s) => hasHighConfidence(s.probability, s.state)).length,
)
const sigActionable = computed(
  () => signals.value.filter((s) => hasActionableEdge(s.probability)).length,
)
const maxCalibratedEdge = computed(() => {
  let max = 0
  for (const s of signals.value) {
    if (
      typeof s.probability === 'number' &&
      Number.isFinite(s.probability) &&
      s.probability > max
    ) {
      max = s.probability
    }
  }
  return max > 0 ? max : null
})
/** Ranked high-confidence names only — empty is an honest desk state. */
const highConfidenceQueue = computed(() =>
  signals.value
    .filter((s) => hasHighConfidence(s.probability, s.state))
    .slice()
    .sort(compareSignals),
)
const rankedSignals = computed(() => signals.value.slice().sort(compareSignals))
const rankedPead = computed(() => pead.value.slice().sort(comparePead))
const liveActivityCount = computed(() => activity.value.filter((row) => row.live).length)
const peadGateVerdict = computed(() =>
  String(scan.value?.pead_gate_verdict ?? 'UNKNOWN').toUpperCase(),
)
const peadMeta = computed(() => {
  const summary = scan.value
  return summary
    ? `${pead.value.length} ordinal flags / ${summary.pead_attempted_symbols} examined · gate ${summary.pead_gate_verdict}`
    : `${pead.value.length} ordinal flags · no calibrated probability`
})
const signalMeta = computed(() => {
  const summary = scan.value
  const entered = sigEntered.value
  const high = sigHighConf.value
  const scored = summary?.directional_scored_symbols ?? signals.value.length
  const domain = summary?.directional_model_universe_symbols ?? '—'
  return `${entered} ENTER · ${high} high-conf · ${scored}/${domain} scored · bar ${pctFrac(ENTER_EDGE, 0)}`
})
const confidencePosture = computed(() => {
  if (sigEntered.value > 0 || sigHighConf.value > 0) {
    return {
      label: 'HIGH CONFIDENCE',
      tone: 'armed' as const,
      detail: `${Math.max(sigEntered.value, sigHighConf.value)} name(s) at/above ENTER bar ${pctFrac(ENTER_EDGE, 0)}`,
    }
  }
  if (sigActionable.value > 0) {
    return {
      label: 'WATCH ONLY',
      tone: 'held' as const,
      detail: `${sigActionable.value} moderate (≥${pctFrac(ACTIONABLE_EDGE, 0)}); max ${maxCalibratedEdge.value != null ? pctFrac(maxCalibratedEdge.value, 1) : DASH} — below ENTER`,
    }
  }
  return {
    label: 'NO EDGE',
    tone: 'held' as const,
    detail:
      maxCalibratedEdge.value != null
        ? `Max calibrated ${pctFrac(maxCalibratedEdge.value, 1)} · nothing clears ${pctFrac(ACTIONABLE_EDGE, 0)} watch floor`
        : 'No calibrated directional probabilities this session',
  }
})
const activityMeta = computed(() => {
  const coverage = activityCoverage.value
  if (!coverage) return 'Awaiting activity scan'
  const live = coverage.live_requested
    ? `${coverage.live_completed}/${coverage.live_requested} live checked · ${coverage.live_with_activity} with prints`
    : 'live flow runs in Deep mode'
  return `${coverage.local_scanned}/${coverage.market_universe} locally ranked · ${live}`
})
const livePassLabel = computed(() => {
  const coverage = activityCoverage.value
  if (!coverage?.live_requested) return 'DEEP REQUIRED FOR LIVE FLOW'
  if (coverage.live_completed === 0) return 'LSE PASS UNAVAILABLE · OPEN FLOW TO RETRY'
  if (coverage.live_completed >= coverage.live_requested) return 'LSE PASS COMPLETE'
  return `LSE PARTIAL ${coverage.live_completed}/${coverage.live_requested}`
})
const selectedScanLabel = computed(() =>
  scanDepth.value === 'deep'
    ? `${scan.value?.activity_market_universe_symbols ?? d.value?.searchable_symbol_count ?? 576} + ${scan.value?.activity_live_requested_symbols || 100} LIVE`
    : `${Math.min(scan.value?.activity_market_universe_symbols ?? 175, 175)} LOCAL`,
)
const quickScopeCount = computed(() => Math.min(d.value?.broad_universe_count ?? 175, 175))
const deepScopeCount = computed(
  () =>
    scan.value?.activity_market_universe_symbols ??
    d.value?.market_universe_count ??
    d.value?.searchable_symbol_count ??
    576,
)
const selectedScanTitle = computed(() =>
  scanDepth.value === 'deep' ? 'MARKET-WIDE + LIVE FLOW' : 'FAST LOCAL ACTIVITY',
)
const selectedScanDetail = computed(() =>
  scanDepth.value === 'deep'
    ? `Full ${deepScopeCount.value}-name activity + qlib cross-section, the complete calibrated model domain, and up to 100 bounded LSE flow checks.`
    : `${quickScopeCount.value} local activity names and 25 priority names from the calibrated model domain; no live-provider fan-out.`,
)
const scanStageLabel = computed(() =>
  String(scanJob.value?.stage || 'starting')
    .replaceAll('_', ' ')
    .toUpperCase(),
)

function confidenceBand(
  value: number | null | undefined,
): 'HIGH' | 'MODERATE' | 'LOW' | 'UNAVAILABLE' {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'UNAVAILABLE'
  if (value >= ENTER_EDGE) return 'HIGH'
  if (value >= ACTIONABLE_EDGE) return 'MODERATE'
  return 'LOW'
}

/** Meets ENTER bar (p ≥ 0.65) or explicit ENTER state. */
function hasHighConfidence(value: number | null | undefined, state?: string): boolean {
  if (state === 'ENTER') return true
  if (value === null || value === undefined || !Number.isFinite(value)) return false
  return value >= ENTER_EDGE
}

/** Watch-tier edge (p ≥ 0.55). Not authorization. */
function hasActionableEdge(value: number | null | undefined): boolean {
  if (value === null || value === undefined || !Number.isFinite(value)) return false
  return value >= ACTIONABLE_EDGE
}

function edgeTitle(value: number | null | undefined, state?: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return 'No calibrated probability — use momentum + state only. Not authorization.'
  }
  if (hasHighConfidence(value, state)) {
    return `${pctFrac(value, 1)} HIGH — meets ENTER bar (≥${pctFrac(ENTER_EDGE, 0)})`
  }
  if (hasActionableEdge(value)) {
    return `${pctFrac(value, 1)} MODERATE — above ${pctFrac(ACTIONABLE_EDGE, 0)} watch floor; below ENTER ${pctFrac(ENTER_EDGE, 0)}`
  }
  return `${pctFrac(value, 1)} LOW — near coin-flip; not authorization edge`
}

function compareSignals(a: SignalRow, b: SignalRow): number {
  const aEnter = a.state === 'ENTER' ? 1 : 0
  const bEnter = b.state === 'ENTER' ? 1 : 0
  if (aEnter !== bEnter) return bEnter - aEnter
  const ap =
    typeof a.probability === 'number' && Number.isFinite(a.probability) ? a.probability : -1
  const bp =
    typeof b.probability === 'number' && Number.isFinite(b.probability) ? b.probability : -1
  if (bp !== ap) return bp - ap
  return Math.abs(b.momentum ?? 0) - Math.abs(a.momentum ?? 0)
}

function comparePead(a: PeadRow, b: PeadRow): number {
  return Math.abs(b.evidence?.pead_score ?? 0) - Math.abs(a.evidence?.pead_score ?? 0)
}

function momentumBarPct(value: number | null | undefined): number {
  if (value == null || !Number.isFinite(value)) return 0
  // Raw model score ~0–2 typical; map to bar width.
  return Math.min(100, Math.max(0, Math.abs(value) * 50))
}

/** Join desk signals onto a watchlist symbol for edge / momentum chips. */
function signalFor(sym: string): SignalRow | null {
  if (!sym) return null
  return signalsBySymbol.value.get(sym.toUpperCase()) ?? null
}

function peadFor(sym: string): PeadRow | null {
  if (!sym) return null
  return peadBySymbol.value.get(sym.toUpperCase()) ?? null
}

function relationFor(sym: string): 'agree' | 'conflict' | 'none' {
  const relation = reconciledBySymbol.value.get(sym.toUpperCase())?.relation
  if (relation === 'agree' || relation === 'conflict') return relation
  const peadSide = peadFor(sym)?.side?.toLowerCase()
  const directionalSide = signalFor(sym)?.side?.toLowerCase()
  if (!peadSide || !directionalSide) return 'none'
  return peadSide === directionalSide ? 'agree' : 'conflict'
}

function sideWord(value: string | null | undefined): string {
  const side = String(value || '').toLowerCase()
  return side === 'long' ? 'UP' : side === 'short' ? 'DOWN' : 'NONE'
}

/** Activity lean chip — bullish/bearish when detectable, else neutral/mixed. */
function activityLean(row: ActivityFlagRow): { label: string; cls: string; title: string } {
  const lean = String(row.activity_lean || '').toLowerCase()
  const source = String(row.activity_lean_source || 'none').replaceAll('_', ' ')
  if (lean === 'bullish') {
    return {
      label: row.activity_lean_label || 'BULLISH',
      cls: 'bullish',
      title: `Activity lean · ${source}`,
    }
  }
  if (lean === 'bearish') {
    return {
      label: row.activity_lean_label || 'BEARISH',
      cls: 'bearish',
      title: `Activity lean · ${source}`,
    }
  }
  if (lean === 'mixed') {
    return { label: 'MIXED', cls: 'mixed', title: `Activity lean · ${source}` }
  }
  // Fallback from price impulse when backend lean is missing on older payloads.
  const impulse = String(row.price_impulse || '').toLowerCase()
  if (impulse === 'up' || (row.ret_1d != null && row.ret_1d > 0)) {
    return { label: 'BULLISH', cls: 'bullish', title: 'Activity lean · price impulse' }
  }
  if (impulse === 'down' || (row.ret_1d != null && row.ret_1d < 0)) {
    return { label: 'BEARISH', cls: 'bearish', title: 'Activity lean · price impulse' }
  }
  return { label: 'NEUTRAL', cls: 'neutral', title: 'No clear bullish/bearish activity lean' }
}

const sparkCache = new Map<string, { key: string; path: string }>()

const watchSparks = computed(() => {
  const out: Record<string, string> = {}
  for (const [sym, traj] of Object.entries(probeResults.value)) {
    const series = traj?.series
    if (!series || series.length <= 2) continue

    const lastBar = series[series.length - 1]
    const cacheKey = `${series.length}_${lastBar?.d}_${lastBar?.c}`
    const cached = sparkCache.get(sym)
    if (cached && cached.key === cacheKey) {
      out[sym] = cached.path
      continue
    }

    const closes = series.map((b) => b.c)
    const path = sparkline(closes.slice(-40), 88, 22, 2).d
    sparkCache.set(sym, { key: cacheKey, path })
    out[sym] = path
  }
  return out
})

const filteredPead = computed(() => {
  return rankedPead.value.filter((p) => {
    if (peadFilter.value === 'flagged') return p.setup_ok || p.model?.state === 'FLAG'
    if (peadFilter.value === 'long') return p.side?.toLowerCase() === 'long'
    if (peadFilter.value === 'short') return p.side?.toLowerCase() === 'short'
    return true
  })
})

const filteredSignals = computed(() => {
  return rankedSignals.value.filter((s) => {
    if (signalFilter.value === 'entered') return s.state === 'ENTER'
    if (signalFilter.value === 'actionable') return hasActionableEdge(s.probability)
    if (signalFilter.value === 'long') return s.side?.toLowerCase() === 'long'
    if (signalFilter.value === 'short') return s.side?.toLowerCase() === 'short'
    return true
  })
})

/* Top summary stats */
const topSector = computed(() => {
  if (!sectors.value.length) return null
  return [...sectors.value].sort((a: any, b: any) => b.flow_score - a.flow_score)[0]
})

const topStrategy = computed(() => {
  if (!board.value.length) return null
  return board.value.find((b) => b.verdict === 'GO') ?? board.value[0]
})

function open(sym: string | undefined): void {
  if (sym) void router.push({ name: 'market', query: { symbol: sym } })
}

/** Route a candidate into the options engine — the chain fetch the scan itself
 *  never performs. Previously there was no path from a flag to its structure. */
function openOptions(sym: string | undefined): void {
  if (sym) void router.push({ name: 'options', query: { symbol: sym } })
}

function navTo(name: string): void {
  void router.push({ name })
}
</script>

<template>
  <div class="desk">
    <!-- ── Header & Session Posture ────────────────────────────────────── -->
    <header class="arena-head">
      <div class="arena-title">
        <div class="arena-kicker-row">
          <span class="label arena-kicker">Desk · Execution Arena</span>
          <span class="session-indicator" :class="r?.cleared_for_live ? 'live' : 'research'">
            <i class="session-dot" aria-hidden="true" />
            {{ r?.cleared_for_live ? 'LIVE BOOK CLEARED' : 'RESEARCH BOOK' }}
          </span>
        </div>
        <h1>Execution Arena</h1>
        <p class="arena-desc">
          Session posture, live marks, ranked activity, and the names worth opening next.
        </p>
      </div>

      <div class="arena-context" aria-label="Desk scope and shortcuts">
        <span class="scope-chip session-chip">
          <span class="scope-tag">SCOPE</span> SESSION BOARD
        </span>
        <span class="scope-chip" :class="scan?.depth === 'deep' ? 'live' : 'proxy'">
          <span class="scope-tag">SCAN</span> {{ scan?.depth === 'deep' ? 'MARKET-WIDE' : 'LOCAL' }}
        </span>
        <span class="scope-chip" :class="r?.cleared_for_live ? 'live' : 'held'">
          <span class="scope-tag">CAPITAL</span> {{ r?.cleared_for_live ? 'CLEARED' : 'HELD' }}
        </span>
        <RouterLink :to="{ name: 'flow' }" class="arena-flow-link label">
          <span>MARKET FLOW</span>
          <span class="flow-arrow" aria-hidden="true">→</span>
        </RouterLink>
      </div>
    </header>

    <!-- ── 00 Summary KPI Deck (3 Structured Zones) ───────────────────── -->
    <section class="desk-summary" aria-label="Desk session overview metrics">
      <!-- Zone 1: Session Posture & Capital Status -->
      <!-- 01 Capital Status Card -->
      <div class="kpi-card ticked kpi-posture-card" :class="r?.cleared_for_live ? 'armed' : 'held'">
        <div class="kpi-head-row">
          <span class="label kpi-label">Capital Status</span>
          <span class="kpi-badge" :class="r?.cleared_for_live ? 'armed' : 'held'">
            {{ r?.cleared_for_live ? 'LIVE READY' : 'STANDBY' }}
          </span>
        </div>
        <div class="kpi-val-row">
          <span class="kpi-val fig" :class="r?.cleared_for_live ? 'pos' : 'warn-text'">
            {{ r?.cleared_for_live ? 'ARMED' : 'HELD' }}
          </span>
        </div>
        <span class="kpi-sub">
          {{
            r?.blocking_reasons?.length
              ? `${r.blocking_reasons.length} blocker(s) active`
              : '0 blockers recorded'
          }}
        </span>
      </div>

      <!-- 02 Confidence Posture Card -->
      <div class="kpi-card ticked kpi-posture-card" :class="confidencePosture.tone">
        <div class="kpi-head-row">
          <span class="label kpi-label">Confidence Posture</span>
          <span class="kpi-badge" :class="sigHighConf > 0 ? 'enter' : 'held'">
            {{ sigEntered }} ENTER · {{ sigHighConf }} HIGH
          </span>
        </div>
        <div class="kpi-val-row">
          <span
            class="kpi-val fig"
            :class="sigHighConf > 0 ? 'pos' : sigActionable > 0 ? 'warn-text' : ''"
          >
            {{ confidencePosture.label }}
          </span>
        </div>
        <span class="kpi-sub" :title="confidencePosture.detail">
          {{ confidencePosture.detail }}
        </span>
      </div>

      <!-- Zone 2: Market Breadth & Flow -->
      <!-- 03 Activity Flags Card -->
      <div class="kpi-card ticked kpi-breadth-card">
        <div class="kpi-head-row">
          <span class="label kpi-label">Activity Flags</span>
          <span class="kpi-badge flat">{{ scan?.depth?.toUpperCase() ?? 'SCAN' }}</span>
        </div>
        <div class="kpi-val-row">
          <span class="kpi-val fig">{{ activity.length }}</span>
          <span class="kpi-sub-count label">{{ liveActivityCount }} LIVE</span>
        </div>
        <span class="kpi-sub">
          {{ liveActivityCount }} live flow · {{ pead.length }} PEAD ordinal
        </span>
      </div>

      <!-- 04 Regime & Magnet Breadth Card -->
      <button
        class="kpi-card ticked kpi-breadth-card kpi-regime-card"
        type="button"
        aria-label="Open Live Stack for market regime telemetry"
        @click="navTo('livestack')"
      >
        <div class="kpi-head-row">
          <span class="label kpi-label">Regime & Magnet Breadth</span>
          <span
            class="kpi-badge"
            :class="
              marketRegimeBreadth.dampening >= marketRegimeBreadth.amplification
                ? 'pos'
                : 'warn-text'
            "
          >
            {{
              marketRegimeBreadth.dampening >= marketRegimeBreadth.amplification
                ? 'LONG Γ'
                : 'SHORT Γ'
            }}
          </span>
        </div>
        <div class="kpi-val-row">
          <span class="kpi-val fig"
            >{{ marketRegimeBreadth.dampening }}:{{ marketRegimeBreadth.amplification }}</span
          >
          <span class="kpi-sub-count label">DAMP/AMP</span>
        </div>
        <span class="kpi-sub">
          {{ marketRegimeBreadth.dampening }} Dampening ·
          {{ marketRegimeBreadth.amplification }} Amplification ({{
            marketRegimeBreadth.dominantBias
          }})
        </span>
      </button>

      <!-- Zone 3: Macro & Strategy Navigation -->
      <!-- 04 Top Sector Flow (Interactive Navigation Button) -->
      <button
        class="kpi-card ticked kpi-nav-card"
        type="button"
        aria-label="Open Sectors for top sector flow"
        @click="navTo('sectors')"
      >
        <div class="kpi-head-row">
          <span class="label kpi-label">Top Sector Flow</span>
          <span class="kpi-nav-badge">OPEN →</span>
        </div>
        <div class="kpi-val-row">
          <span class="kpi-val sym">{{ topSector ? topSector.etf : '—' }}</span>
          <span class="kpi-badge" :class="tone(topSector?.flow_score ?? 0)">
            {{ topSector ? signedPct(topSector.flow_score * 100, 1) : '—' }}
          </span>
        </div>
        <span class="kpi-sub fl-truncate">
          {{ topSector ? topSector.name : 'Sectors tab' }}
        </span>
      </button>

      <!-- 05 Top Alpha Strategy (Interactive Navigation Button) -->
      <button
        class="kpi-card ticked kpi-nav-card"
        type="button"
        aria-label="Open Gates for the top alpha strategy"
        @click="navTo('gates')"
      >
        <div class="kpi-head-row">
          <span class="label kpi-label">Top Alpha Strategy</span>
          <span class="kpi-nav-badge">OPEN →</span>
        </div>
        <div class="kpi-val-row">
          <span class="kpi-val strat-name">{{ topStrategy ? topStrategy.strategy : '—' }}</span>
          <VerdictChip v-if="topStrategy" :verdict="topStrategy.verdict" size="sm" />
        </div>
        <span class="kpi-sub">
          Net {{ topStrategy?.net_return ?? '—' }} · Sharpe {{ topStrategy?.sharpe ?? '—' }}
        </span>
      </button>
    </section>

    <!-- ── High-Confidence Authorization Queue ─────────────────────────── -->
    <section
      class="confidence-queue ticked w-full"
      :class="{ 'has-items': highConfidenceQueue.length > 0 }"
      aria-label="High confidence directional queue"
    >
      <div class="confidence-queue-head">
        <div class="confidence-queue-title">
          <div class="queue-kicker-row">
            <span class="label queue-kicker">Authorization Queue</span>
            <span class="queue-edge-pill label">ENTER BAR ≥ {{ pctFrac(ENTER_EDGE, 0) }}</span>
          </div>
          <strong>High-Confidence Directional Signals</strong>
          <p class="queue-note">
            Calibrated model domain only. PEAD ordinal flags never appear here. Moderate watches ({{
              pctFrac(ACTIONABLE_EDGE, 0)
            }}–{{ pctFrac(ENTER_EDGE, 0) }}) stay in Directional Signals.
          </p>
        </div>
        <div class="confidence-queue-stats">
          <span class="fig count-fig" :class="highConfidenceQueue.length > 0 ? 'pos' : 'dim'">{{
            highConfidenceQueue.length
          }}</span>
          <span class="label count-label">AUTHORIZED</span>
        </div>
      </div>
      <div v-if="highConfidenceQueue.length" class="confidence-queue-rows">
        <button
          v-for="s in highConfidenceQueue"
          :key="`hc-${s.symbol}`"
          type="button"
          class="hc-row"
          @click="open(s.symbol)"
        >
          <span class="fig sym">{{ s.symbol }}</span>
          <span class="side-pill" :class="s.side === 'LONG' || s.side === 'long' ? 'pos' : 'neg'">
            {{ (s.side ?? DASH).toUpperCase() }}
          </span>
          <span class="fig pos prob-fig">{{ pctFrac(s.probability, 1) }}</span>
          <span class="state label enter">{{ s.state }}</span>
          <span class="label dim horizon-label">{{ (s.horizon ?? '').replace(' Days', 'd') }}</span>
        </button>
      </div>
      <div v-else class="confidence-empty">
        <div class="empty-icon-box">
          <span class="empty-indicator">—</span>
        </div>
        <div class="empty-copy">
          <template v-if="signals.length === 0">
            <strong>No directional scores loaded.</strong>
            <p>Run a Quick or Deep scan to evaluate the serving universe.</p>
          </template>
          <template v-else>
            <strong>No high-confidence authorizations this session.</strong>
            <p>
              Max calibrated edge:
              <strong class="fig">{{
                maxCalibratedEdge != null ? pctFrac(maxCalibratedEdge, 1) : DASH
              }}</strong>
              · ENTER threshold: <strong class="fig">{{ pctFrac(ENTER_EDGE, 0) }}</strong> ·
              {{ sigActionable }} moderate watch names remain under observation.
            </p>
          </template>
        </div>
      </div>
    </section>

    <!-- ── Scan Operations Console ─────────────────────────────────────── -->
    <section class="scan-console ticked w-full" aria-label="Market scan depth and controls">
      <div class="scan-console-head">
        <div class="scan-title-block">
          <span class="label scan-kicker">Scan Operations</span>
          <strong class="scan-title">{{ selectedScanTitle }}</strong>
          <span class="last-scan label"
            >LAST COMPLETE · {{ scan?.depth?.toUpperCase() ?? 'NONE' }}</span
          >
        </div>

        <div class="scan-readouts" aria-label="Latest scan coverage">
          <div class="scan-readout">
            <span class="label">Market activity</span>
            <span class="fig">
              {{ scan?.activity_local_scanned_symbols ?? 0
              }}<i
                >/{{ scan?.activity_market_universe_symbols ?? d?.market_universe_count ?? '—' }}</i
              >
            </span>
            <small>daily bars ranked</small>
          </div>
          <div class="scan-readout">
            <span class="label">Live LSE flow</span>
            <span class="fig">
              {{ scan?.activity_live_completed_symbols ?? 0
              }}<i>/{{ scan?.activity_live_requested_symbols ?? 0 }}</i>
            </span>
            <small>{{ scan?.activity_live_with_prints_symbols ?? 0 }} names with prints</small>
          </div>
          <div class="scan-readout">
            <span class="label">Calibrated model</span>
            <span class="fig">
              {{ scan?.directional_scored_symbols ?? signals.length
              }}<i>/{{ scan?.directional_model_universe_symbols ?? '—' }}</i>
            </span>
            <small>frozen serving domain</small>
          </div>
          <div class="scan-readout">
            <span class="label">Runtime</span>
            <span class="fig">{{ scan ? `${num(scan.elapsed_seconds, 1)}s` : '—' }}</span>
            <small>last completed pass</small>
          </div>
        </div>

        <div class="scan-controls">
          <div class="depth-switch" role="group" aria-label="Scan depth">
            <button
              class="depth-option label"
              :class="{ on: scanDepth === 'quick' }"
              :aria-pressed="scanDepth === 'quick'"
              :disabled="scanning"
              @click="scanDepth = 'quick'"
            >
              QUICK <span>{{ quickScopeCount }} LOCAL</span>
            </button>
            <button
              class="depth-option label"
              :class="{ on: scanDepth === 'deep' }"
              :aria-pressed="scanDepth === 'deep'"
              :disabled="scanning"
              @click="scanDepth = 'deep'"
            >
              DEEP <span>{{ deepScopeCount }} + LIVE</span>
            </button>
          </div>
          <button class="scan-run label" :disabled="scanning" @click="runScan">
            <span class="scan-pulse" aria-hidden="true" />
            {{
              scanning
                ? `${scanJob?.progress ?? 0}% · ${selectedScanLabel}`
                : `RUN ${scanDepth.toUpperCase()} SCAN`
            }}
          </button>
        </div>
      </div>
      <div v-if="scanning && scanJob" class="scan-progress" role="status" aria-live="polite">
        <div class="scan-progress-copy">
          <span class="label">{{ scanJob.depth.toUpperCase() }} PASS · {{ scanStageLabel }}</span>
          <strong>{{ scanJob.message }}</strong>
          <small class="fig"
            >{{ num(scanJob.elapsed_seconds, 1) }}s elapsed · the desk remains available</small
          >
        </div>
        <div
          class="scan-progress-track"
          role="progressbar"
          aria-label="Scan completion"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-valuenow="scanJob.progress"
        >
          <i :style="{ width: `${scanJob.progress}%` }" />
        </div>
      </div>
      <div class="scan-explain" aria-live="polite">
        <span v-if="scanMsg && !scanning" class="scan-msg label">{{ scanMsg }}</span>
        <span v-else-if="!scanning" class="label">{{ selectedScanDetail }}</span>
        <span v-else class="label"
          >Selected scope is executing as a background job; leaving this view will not cancel
          it.</span
        >
        <RouterLink
          v-if="!scanning && scan?.depth === 'deep'"
          :to="{ name: 'flow' }"
          class="scan-flow-link label"
        >
          OPEN DEEP FLOW →
        </RouterLink>
      </div>
    </section>

    <!-- ── 01 Market-wide activity flags ───────────────────────────────── -->
    <Panel
      label="Live Activity Flags"
      index="01"
      :meta="activityMeta"
      :delay="40"
      flush
      class="w-full activity-panel"
    >
      <template #action>
        <div class="activity-legend label">
          <span class="live-dot" :class="{ on: liveActivityCount > 0 }" aria-hidden="true" />
          <span class="pass-label">{{ livePassLabel }}</span>
          <span class="ordinal-note">ORDINAL · NOT PROBABILITY</span>
        </div>
      </template>

      <div class="table-container activity-table">
        <table v-if="activity.length" class="grid">
          <thead>
            <tr>
              <th class="label col-rank">Rank / Symbol</th>
              <th class="label col-lean">Lean</th>
              <th class="label num col-act">Activity Score</th>
              <th class="label num col-qlib">Qlib XS Rank</th>
              <th class="label col-regime">Regime / Magnet</th>
              <th class="label col-flags">Observed Flags</th>
              <th class="label num col-flow">Live Flow</th>
              <th class="label num col-price">Price / Vol</th>
              <th class="label col-dir">Direction Context</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in activity"
              :key="row.symbol"
              class="activity-row"
              @click="open(row.symbol)"
            >
              <td class="row-select-cell col-rank">
                <button type="button" class="row-select-btn" @click.stop="open(row.symbol)">
                  <span class="sr-only">Select row</span>
                </button>
                <span class="rank-idx fig">{{ String(row.activity_rank).padStart(2, '0') }}</span>
                <span class="fig sym">{{ row.symbol }}</span>
              </td>
              <td class="col-lean">
                <span
                  class="lean-chip label"
                  :class="activityLean(row).cls"
                  :title="activityLean(row).title"
                  >{{ activityLean(row).label }}</span
                >
              </td>
              <td class="num col-act">
                <div class="activity-score">
                  <span class="fig score-val">{{ num(row.activity_score, 1) }}</span>
                  <div class="activity-bar-wrap" aria-hidden="true">
                    <b :style="{ width: `${row.activity_score}%` }" />
                  </div>
                  <small class="label ordinal-tag">ORDINAL</small>
                </div>
              </td>
              <td class="num fig col-qlib">
                <div
                  v-if="row.qlib_rank != null"
                  class="qlib-cell"
                  :title="`Ordinal qlib cross-sectional rank · ${row.qlib_source ?? 'research source'} · ${row.qlib_asof ?? 'as-of unavailable'}`"
                >
                  <strong class="qlib-rank-text">#{{ row.qlib_rank }}</strong>
                  <small class="dim"
                    >XS {{ row.qlib_score != null ? num(row.qlib_score, 2) : DASH }} · RSCH</small
                  >
                </div>
                <span v-else class="dim">—</span>
              </td>
              <td class="col-regime">
                <div
                  v-if="
                    regimeFor(row.symbol) && isRegimeMeasurable(regimeFor(row.symbol)!.regime_state)
                  "
                  class="regime-cell"
                >
                  <RegimeStateBadge
                    :payload="regimeFor(row.symbol)"
                    :compact="true"
                    :show-strength="false"
                    :show-vector="false"
                  />
                  <div
                    v-if="primaryMagnetFor(row.symbol)"
                    class="magnet-sub label"
                    :title="primaryMagnetFor(row.symbol)!.regime_role"
                  >
                    ★ {{ primaryMagnetFor(row.symbol)!.label }}
                    {{ usd(primaryMagnetFor(row.symbol)!.price) }}
                    <span class="mono-dist"
                      >({{
                        formatDistancePercent(primaryMagnetFor(row.symbol)!.distance_pct)
                      }})</span
                    >
                  </div>
                </div>
                <span v-else class="dim">—</span>
              </td>
              <td class="col-flags">
                <div class="flag-stack">
                  <span
                    v-for="flag in row.flags.slice(0, 3)"
                    :key="flag"
                    class="flag-pill"
                    :class="{ live: flag.includes('LIVE') || flag.includes('$1M') }"
                  >
                    {{ flag }}
                  </span>
                </div>
              </td>
              <td class="fig num col-flow">
                <template v-if="row.live">
                  <strong class="live-value">{{
                    row.premium == null ? DASH : usd(row.premium)
                  }}</strong>
                  <small class="flow-count"
                    >{{ row.print_count }} prints · C{{ row.call_print_count }}/P{{
                      row.put_print_count
                    }}</small
                  >
                </template>
                <span v-else class="dim local-tag">LOCAL ONLY</span>
              </td>
              <td class="fig num col-price">
                <span class="price-ret" :class="tone((row.ret_1d ?? 0) * 100)">{{
                  signedPct((row.ret_1d ?? 0) * 100, 1)
                }}</span>
                <small class="flow-count">{{
                  row.volume_vs_20d_median == null
                    ? DASH
                    : `${num(row.volume_vs_20d_median, 1)}× vol`
                }}</small>
              </td>
              <td class="col-dir">
                <div class="signal-context">
                  <div class="signal-context-top">
                    <span v-if="row.pead_side" class="context-source label"
                      >GAP {{ sideWord(row.pead_side) }}</span
                    >
                    <span v-if="row.directional_side" class="context-source label"
                      >5D {{ sideWord(row.directional_side) }}</span
                    >
                  </div>
                  <div class="signal-context-bottom">
                    <span class="alignment-chip label" :class="row.signal_alignment || 'none'">
                      {{
                        row.signal_alignment === 'agree'
                          ? 'AGREE'
                          : row.signal_alignment === 'conflict'
                            ? 'CONFLICT'
                            : row.signal_alignment === 'pead_only'
                              ? 'EVENT ONLY'
                              : row.signal_alignment === 'directional_only'
                                ? 'MODEL ONLY'
                                : 'NO VIEW'
                      }}
                    </span>
                    <small
                      v-if="
                        row.calibrated_probability != null &&
                        hasActionableEdge(row.calibrated_probability)
                      "
                      class="context-edge"
                    >
                      model {{ pctFrac(row.calibrated_probability, 1) }}
                    </small>
                  </div>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">
          No activity rows are available. Run Deep to scan the full catalog and request live LSE
          flow.
        </p>
      </div>
      <p class="note tiny pad confidence-footnote">
        Activity score ranks observed price, volume, gaps, and live premium. It is not win
        probability; unsigned call/put flow never supplies trade direction.
      </p>
    </Panel>

    <!-- ── Signal Contract Reconciliation Bridge ────────────────────────── -->
    <section class="signal-contract w-full" aria-label="PEAD and directional signal reconciliation">
      <div class="signal-contract-copy">
        <div class="contract-kicker-row">
          <span class="label contract-kicker">Signal Reconciliation</span>
          <span class="contract-rule-badge label">EVENT ≠ 5D FORECAST</span>
        </div>
        <strong>Model Separation Contract</strong>
        <p>
          PEAD records what happened at the market open. Directional estimates the next
          multi-session move inside a smaller frozen model domain. Only the same symbol can agree or
          conflict; different symbols are non-overlap, not disagreement.
        </p>
      </div>
      <div class="reconciliation-stats" aria-label="Signal overlap counts">
        <div class="stat-box">
          <span class="label">OVERLAP</span
          ><strong class="fig">{{ reconciliation?.counts.overlap ?? 0 }}</strong>
        </div>
        <div class="stat-box agree">
          <span class="label">AGREE</span
          ><strong class="fig pos">{{ reconciliation?.counts.agreements ?? 0 }}</strong>
        </div>
        <div class="stat-box conflict">
          <span class="label">CONFLICT</span
          ><strong class="fig neg">{{ reconciliation?.counts.conflicts ?? 0 }}</strong>
        </div>
        <div class="stat-box">
          <span class="label">SEPARATE</span
          ><strong class="fig">{{
            (reconciliation?.counts.pead_only ?? pead.length) +
            (reconciliation?.counts.directional_only ?? signals.length)
          }}</strong>
        </div>
      </div>
      <div v-if="reconciliation?.counts.conflicts" class="conflict-strip label">
        <span class="conflict-head">NO UNIFIED THESIS:</span>
        <span
          v-for="row in reconciliation.rows.filter((item) => item.relation === 'conflict')"
          :key="row.symbol"
          class="conflict-item"
        >
          {{ row.symbol }} · GAP {{ sideWord(row.pead_side) }} / 5D
          {{ sideWord(row.directional_side) }}
        </span>
      </div>
    </section>

    <!-- ── Dual Model Signals Section Controls ─────────────────────────── -->
    <div class="model-views-header w-full">
      <div class="model-views-kicker">
        <span class="label section-kicker">Trading Signals & Setup Models</span>
        <h2>Model Domains</h2>
      </div>
      <div class="view-mode-tabs" role="tablist" aria-label="Signal layout mode">
        <button
          class="view-tab label"
          :class="{ active: dualViewMode === 'split' }"
          type="button"
          @click="dualViewMode = 'split'"
        >
          SPLIT VIEW ({{ pead.length + signals.length }})
        </button>
        <button
          class="view-tab label"
          :class="{ active: dualViewMode === 'pead' }"
          type="button"
          @click="dualViewMode = 'pead'"
        >
          PEAD GAP FLAGS ({{ pead.length }})
        </button>
        <button
          class="view-tab label"
          :class="{ active: dualViewMode === 'directional' }"
          type="button"
          @click="dualViewMode = 'directional'"
        >
          DIRECTIONAL 5D ({{ signals.length }})
        </button>
      </div>
    </div>

    <!-- ── 02 PEAD gap/volume flags ─────────────────────────────────────── -->
    <Panel
      v-if="dualViewMode === 'split' || dualViewMode === 'pead'"
      label="PEAD Gap / Volume Flags"
      index="02"
      :meta="peadMeta"
      :delay="60"
      flush
      :class="dualViewMode === 'pead' ? 'w-full' : 'w-half'"
    >
      <template #action>
        <div class="action-bar">
          <div class="select-wrap">
            <select
              v-model="peadFilter"
              class="filter-select label"
              aria-label="Filter PEAD gap setups"
            >
              <option value="all">ALL FLAGS ({{ pead.length }})</option>
              <option value="flagged">SETUP OK ({{ peadFlagged }})</option>
              <option value="long">UP-GAP FLAGS</option>
              <option value="short">DOWN-GAP FLAGS</option>
            </select>
          </div>
        </div>
      </template>

      <div class="table-container">
        <table
          v-if="filteredPead.length"
          class="grid table-pead"
          :class="{ 'is-split': dualViewMode === 'split' }"
        >
          <thead>
            <tr>
              <th class="label col-sym">Symbol</th>
              <th class="label num col-last">Last</th>
              <th class="label num col-chg">1D</th>
              <th class="label col-side">Side</th>
              <th class="label num col-score">Strength</th>
              <th v-if="dualViewMode !== 'split'" class="label num col-gap">Gap / ATR</th>
              <th v-if="dualViewMode !== 'split'" class="label num col-vol">Volume</th>
              <th class="label col-5d">5D Forecast</th>
              <th class="label col-state">State</th>
              <th class="label col-chain">Options</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in filteredPead" :key="c.symbol" class="pead-row" @click="open(c.symbol)">
              <td class="fig sym col-sym">{{ c.symbol }}</td>
              <td class="fig num col-last" :title="markFor(c.symbol)?.source || 'awaiting mark'">
                {{ usd(markLast(c.symbol)) }}
              </td>
              <td class="fig num col-chg" :class="tone(markChg(c.symbol))">
                {{ signedPct(markChg(c.symbol)) }}
              </td>
              <td class="col-side">
                <span class="side-pill" :class="c.side === 'long' ? 'pos' : 'neg'">
                  {{ (c.side ?? DASH).toUpperCase() }}
                </span>
              </td>
              <td class="fig num col-score" :class="tone(c.evidence?.pead_score)">
                {{ num(Math.abs(c.evidence?.pead_score ?? 0), 2) }}
              </td>
              <td
                v-if="dualViewMode !== 'split'"
                class="fig num col-gap"
                :class="tone(c.evidence?.gap_std)"
              >
                {{ num(c.evidence?.gap_std, 2) }}
              </td>
              <td v-if="dualViewMode !== 'split'" class="fig num col-vol">
                {{ num(c.evidence?.vol_surge, 2) }}×
              </td>
              <td class="col-5d">
                <span
                  v-if="signalFor(c.symbol)"
                  class="alignment-chip label"
                  :class="relationFor(c.symbol)"
                >
                  {{
                    relationFor(c.symbol) === 'agree'
                      ? `AGREES ${sideWord(signalFor(c.symbol)?.side)}`
                      : `CONFLICT ${sideWord(signalFor(c.symbol)?.side)}`
                  }}
                </span>
                <span v-else class="coverage-chip label">NO 5D MODEL ROW</span>
              </td>
              <td class="col-state">
                <span class="state label watch">
                  {{ c.model?.state ?? DASH }}
                </span>
              </td>
              <td class="col-chain">
                <button
                  class="chain-btn label"
                  type="button"
                  title="Fetch this name's option chain and gamma structure"
                  @click.stop="openOptions(c.symbol)"
                >
                  CHAIN
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">
          {{
            pead.length === 0
              ? 'No gap/volume flags cleared the ordinal threshold this session.'
              : 'No flags match the selected filter.'
          }}
        </p>
      </div>
      <p class="note tiny pad confidence-footnote">
        PEAD gate <strong>{{ peadGateVerdict }}</strong
        >. Strength is ordinal (not probability) and cannot authorize an entry or be read as
        confidence.
      </p>
    </Panel>

    <!-- ── 03 Directional Signals ──────────────────────────────────────── -->
    <Panel
      v-if="dualViewMode === 'split' || dualViewMode === 'directional'"
      label="Directional Signals"
      index="03"
      :meta="signalMeta"
      :delay="120"
      flush
      :class="dualViewMode === 'directional' ? 'w-full' : 'w-half'"
    >
      <template #action>
        <div class="action-bar">
          <div class="select-wrap">
            <select
              v-model="signalFilter"
              class="filter-select label"
              aria-label="Filter directional signals"
            >
              <option value="all">ALL (ranked by edge) · {{ signals.length }}</option>
              <option value="entered">ENTER ONLY · {{ sigEntered }}</option>
              <option value="actionable">
                ≥{{ pctFrac(ACTIONABLE_EDGE, 0) }} WATCH · {{ sigActionable }}
              </option>
              <option value="long">LONG</option>
              <option value="short">SHORT</option>
            </select>
          </div>
        </div>
      </template>

      <div class="table-container">
        <table
          v-if="filteredSignals.length"
          class="grid table-directional"
          :class="{ 'is-split': dualViewMode === 'split' }"
        >
          <thead>
            <tr>
              <th class="label col-sym">Symbol</th>
              <th class="label num col-last">Last</th>
              <th class="label num col-chg">1D</th>
              <th class="label col-side">Side</th>
              <th class="label num col-edge">Edge</th>
              <th class="label col-regime">Regime / Magnet</th>
              <th class="label num col-mom">Momentum</th>
              <th v-if="dualViewMode !== 'split'" class="label num col-hz">Hz</th>
              <th class="label col-gap-event">Gap Event</th>
              <th class="label col-state">State</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in filteredSignals"
              :key="s.symbol"
              class="directional-row"
              :class="{ 'row-high': hasHighConfidence(s.probability, s.state) }"
              @click="open(s.symbol)"
            >
              <td class="fig sym col-sym">{{ s.symbol }}</td>
              <td class="fig num col-last" :title="markFor(s.symbol)?.source || 'awaiting mark'">
                {{ usd(markLast(s.symbol)) }}
              </td>
              <td class="fig num col-chg" :class="tone(markChg(s.symbol))">
                {{ signedPct(markChg(s.symbol)) }}
              </td>
              <td class="col-side">
                <span
                  class="side-pill"
                  :class="s.side === 'LONG' || s.side === 'long' ? 'pos' : 'neg'"
                >
                  {{ (s.side ?? DASH).toUpperCase() }}
                </span>
              </td>
              <td class="fig num col-edge" :title="edgeTitle(s.probability, s.state)">
                <template v-if="s.probability != null && Number.isFinite(s.probability)">
                  <div
                    class="prob-cell"
                    :class="{
                      weak: !hasActionableEdge(s.probability),
                      high: hasHighConfidence(s.probability, s.state),
                    }"
                  >
                    <div class="prob-bar-wrap" aria-hidden="true">
                      <div
                        class="prob-bar"
                        :class="
                          hasHighConfidence(s.probability, s.state)
                            ? 'pos'
                            : hasActionableEdge(s.probability)
                              ? 'mod'
                              : 'flat'
                        "
                        :style="{
                          width: `${Math.min(100, Math.max(0, (s.probability ?? 0) * 100))}%`,
                        }"
                      />
                    </div>
                    <span class="confidence-value">
                      {{ pctFrac(s.probability, 1) }}
                      <small :class="`confidence-${confidenceBand(s.probability).toLowerCase()}`">
                        {{ confidenceBand(s.probability) }}
                      </small>
                    </span>
                  </div>
                </template>
                <span v-else class="dim" title="Uncalibrated — not an edge readout">—</span>
              </td>
              <td class="col-regime">
                <div
                  v-if="
                    regimeFor(s.symbol) && isRegimeMeasurable(regimeFor(s.symbol)!.regime_state)
                  "
                  class="regime-cell"
                >
                  <RegimeStateBadge
                    :payload="regimeFor(s.symbol)"
                    :compact="true"
                    :show-strength="false"
                    :show-vector="false"
                  />
                  <div
                    v-if="primaryMagnetFor(s.symbol)"
                    class="magnet-sub label"
                    :title="primaryMagnetFor(s.symbol)!.regime_role"
                  >
                    ★ {{ primaryMagnetFor(s.symbol)!.label }}
                    {{ usd(primaryMagnetFor(s.symbol)!.price) }}
                    <span class="mono-dist"
                      >({{ formatDistancePercent(primaryMagnetFor(s.symbol)!.distance_pct) }})</span
                    >
                  </div>
                </div>
                <span v-else class="dim">—</span>
              </td>
              <td
                class="fig num mom-cell col-mom"
                :class="tone(s.momentum)"
                :title="`Model momentum score ${num(s.momentum, 3)}`"
              >
                <div class="mom-wrap">
                  <span class="mom-bar" aria-hidden="true"
                    ><i :style="{ width: `${momentumBarPct(s.momentum)}%` }"
                  /></span>
                  <span>{{ num(s.momentum, 2) }}</span>
                </div>
              </td>
              <td v-if="dualViewMode !== 'split'" class="fig num dim col-hz">
                {{ (s.horizon ?? '').replace(' Days', 'd') }}
              </td>
              <td class="col-gap-event">
                <span
                  v-if="peadFor(s.symbol)"
                  class="alignment-chip label"
                  :class="relationFor(s.symbol)"
                >
                  {{
                    relationFor(s.symbol) === 'agree'
                      ? `AGREES ${sideWord(peadFor(s.symbol)?.side)}`
                      : `CONFLICT ${sideWord(peadFor(s.symbol)?.side)}`
                  }}
                </span>
                <span v-else class="coverage-chip label">NO GAP EVENT</span>
              </td>
              <td class="col-state">
                <div class="state-cell">
                  <span class="state label" :class="s.state === 'ENTER' ? 'enter' : 'watch'">{{
                    s.state
                  }}</span>
                  <button
                    class="chain-btn label"
                    type="button"
                    title="Fetch this name's option chain and gamma structure"
                    @click.stop="openOptions(s.symbol)"
                  >
                    CHAIN
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">
          {{
            signals.length === 0
              ? 'No directional signals emitted — run Quick or Deep scan.'
              : 'No directional signals match the selected filter.'
          }}
        </p>
      </div>
      <p class="note tiny pad confidence-footnote">
        Ranked by ENTER then calibrated probability. HIGH ≥ {{ pctFrac(ENTER_EDGE, 0) }} · MODERATE
        ≥ {{ pctFrac(ACTIONABLE_EDGE, 0) }} · below that is WEAK. Confidence kind must be
        calibrated_probability — ordinal PEAD is excluded.
      </p>
    </Panel>

    <!-- ── 04 Custom Stock Watchlist & Ad-Hoc Signal Probe ─────────────── -->
    <Panel
      label="Personal Watchlist & Probe Console"
      index="04"
      :meta="`${customWatchlist.length} pinned · auto-refresh 60s`"
      class="w-full"
      flush
    >
      <template #action>
        <div class="probe-input-bar">
          <input
            v-model="customTickerInput"
            type="text"
            placeholder="Add ticker e.g. TSLA, ASTS"
            class="probe-input label"
            aria-label="Add ticker to watchlist"
            @keyup.enter="probeSymbol(customTickerInput)"
          />
          <button
            class="act label act-primary"
            :disabled="probing || !customTickerInput.trim()"
            @click="probeSymbol(customTickerInput)"
          >
            {{ probing ? 'PROBING…' : '+ ADD TICKER' }}
          </button>
          <button
            class="act label act-secondary"
            :disabled="probing"
            title="Force refresh all watchlist rows"
            @click="probeWatchlist(true)"
          >
            REFRESH ALL
          </button>
        </div>
      </template>

      <p v-if="probeErr" class="err pad">{{ probeErr }}</p>

      <div class="table-container">
        <table v-if="customWatchlist.length" class="grid table-watchlist">
          <thead>
            <tr>
              <th class="label col-sym">Symbol</th>
              <th class="label col-spark">30-Day Trend</th>
              <th class="label num col-price">Last Price</th>
              <th class="label num col-ret1">1D Chg</th>
              <th class="label num col-ret5">5D Chg</th>
              <th class="label num col-edge">Model Edge</th>
              <th class="label col-regime">Regime / Magnet</th>
              <th class="label num col-mom">Momentum</th>
              <th class="label col-act">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="sym in customWatchlist" :key="sym" class="watchlist-row" @click="open(sym)">
              <td class="fig sym col-sym">{{ sym }}</td>
              <td class="spark-cell col-spark">
                <svg v-if="watchSparks[sym]" viewBox="0 0 88 22" class="spark" aria-hidden="true">
                  <path
                    :d="watchSparks[sym]"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.6"
                  />
                </svg>
                <span v-else class="dim">—</span>
              </td>
              <td class="fig num price-cell col-price">{{ usd(markLast(sym)) }}</td>
              <td class="fig num col-ret1" :class="tone(markChg(sym))">
                {{ signedPct(markChg(sym)) }}
              </td>
              <td class="fig num col-ret5" :class="tone(probeResults[sym]?.stats?.chg_5d_pct)">
                {{ signedPct(probeResults[sym]?.stats?.chg_5d_pct) }}
              </td>
              <td
                class="fig num col-edge"
                :title="edgeTitle(signalFor(sym)?.probability, signalFor(sym)?.state)"
              >
                <template v-if="signalFor(sym)?.probability != null">
                  <span
                    class="edge-pill-wrap"
                    :class="
                      hasHighConfidence(signalFor(sym)?.probability, signalFor(sym)?.state)
                        ? 'pos'
                        : hasActionableEdge(signalFor(sym)?.probability)
                          ? 'mod'
                          : 'dim'
                    "
                  >
                    {{ pctFrac(signalFor(sym)!.probability, 1) }}
                    <small
                      v-if="signalFor(sym)?.state"
                      class="label state-mini"
                      :class="signalFor(sym)?.state === 'ENTER' ? 'enter' : 'watch'"
                      >{{ signalFor(sym)?.state }}</small
                    >
                  </span>
                </template>
                <span v-else class="dim">—</span>
              </td>
              <td class="col-regime">
                <div
                  v-if="regimeFor(sym) && isRegimeMeasurable(regimeFor(sym)!.regime_state)"
                  class="regime-cell"
                >
                  <RegimeStateBadge
                    :payload="regimeFor(sym)"
                    :compact="true"
                    :show-strength="false"
                    :show-vector="false"
                  />
                  <div
                    v-if="primaryMagnetFor(sym)"
                    class="magnet-sub label"
                    :title="primaryMagnetFor(sym)!.regime_role"
                  >
                    ★ {{ primaryMagnetFor(sym)!.label }} {{ usd(primaryMagnetFor(sym)!.price) }}
                    <span class="mono-dist"
                      >({{ formatDistancePercent(primaryMagnetFor(sym)!.distance_pct) }})</span
                    >
                  </div>
                </div>
                <span v-else class="dim">—</span>
              </td>
              <td
                class="fig num col-mom"
                :class="tone(signalFor(sym)?.momentum ?? probeResults[sym]?.stats?.chg_5d_pct)"
              >
                {{
                  signalFor(sym)?.momentum != null
                    ? num(signalFor(sym)!.momentum, 2)
                    : signedPct(probeResults[sym]?.stats?.chg_5d_pct)
                }}
              </td>
              <td class="col-act">
                <div class="watch-actions">
                  <button
                    class="chain-btn label"
                    type="button"
                    title="Open options chain"
                    @click.stop="openOptions(sym)"
                  >
                    CHAIN
                  </button>
                  <button
                    class="remove-btn label"
                    title="Remove ticker from personal watchlist"
                    @click.stop="removeWatchlistSymbol(sym)"
                  >
                    REMOVE
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">
          No custom tickers pinned yet. Type a ticker above to probe and pin.
        </p>
      </div>
      <p class="note tiny pad-x">
        Saved in this browser. Rows re-probe every 60s. Edge/Mom fill when the name is on the
        directional board; otherwise 5D return stands in for momentum.
      </p>
    </Panel>
  </div>
</template>

<style scoped>
.desk {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s4);
  align-items: start;
  padding-bottom: var(--s6);
}
.w-full {
  grid-column: 1 / -1;
}
.w-half {
  grid-column: span 2;
}

/* ── Workspace Identity Header ───────────────────────────────────────────── */
.arena-head {
  grid-column: 1 / -1;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s5);
  padding: var(--s3) 0 var(--s2);
  border-bottom: var(--hair) solid var(--rule-hi);
}
.arena-title {
  min-width: 0;
}
.arena-kicker-row {
  display: flex;
  align-items: center;
  gap: var(--s3);
  margin-bottom: 4px;
}
.arena-kicker {
  color: var(--phosphor);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.08em;
}
.session-indicator {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
  padding: var(--s1) var(--s2);
  border-radius: var(--r-sm);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.05em;
}
.session-indicator.live {
  color: var(--long);
  background: var(--long-wash);
  border: var(--hair) solid color-mix(in srgb, var(--long) 50%, var(--rule));
}
.session-indicator.research {
  color: var(--warn);
  background: var(--warn-wash);
  border: var(--hair) solid color-mix(in srgb, var(--warn) 50%, var(--rule));
}
.session-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.arena-title h1 {
  margin: var(--s1) 0;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: var(--t-display);
  letter-spacing: var(--track-display);
  line-height: 1.15;
  font-weight: 600;
}
.arena-desc {
  max-width: 680px;
  color: var(--text-secondary);
  font-size: var(--t-small);
  line-height: 1.4;
}
.arena-context {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: var(--s2);
}
.scope-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
  min-height: var(--density-control-h);
  padding: var(--s1) var(--s2);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
  color: var(--ink);
  background: var(--panel);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  white-space: nowrap;
}
.scope-tag {
  color: var(--ink-faint);
  font-weight: 600;
}
.scope-chip.session-chip {
  border-color: var(--rule-hi);
  background: var(--panel-hi);
}
.scope-chip.live {
  color: var(--phosphor);
  border-color: color-mix(in srgb, var(--phosphor) 60%, var(--rule));
  background: var(--phosphor-wash);
}
.scope-chip.proxy {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 50%, var(--rule));
}
.scope-chip.held {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 50%, var(--rule));
  background: var(--warn-wash);
}
.arena-flow-link {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
  min-height: var(--density-control-h);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--phosphor);
  border-radius: var(--r-sm);
  color: var(--void);
  background: var(--phosphor);
  font-size: var(--t-micro);
  font-weight: 600;
  text-decoration: none;
  white-space: nowrap;
  transition: background var(--dur-fast) var(--ease-out);
}
.arena-flow-link:hover {
  background: var(--phosphor-dim);
}
.flow-arrow {
  font-family: var(--font-data);
}

/* ── 00 Summary KPI Deck (3 Structured Zones) ────────────────────────────── */
.desk-summary {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--s3);
}

.kpi-card {
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  background: var(--panel);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  padding: var(--s3) var(--s4);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: var(--s2);
  min-height: 104px;
  min-width: 0;
  transition:
    border-color var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out);
}
.kpi-card:hover {
  border-color: var(--rule-hi);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.45);
}
.kpi-card:focus-visible,
.arena-flow-link:focus-visible {
  outline: var(--hair) solid var(--phosphor);
  outline-offset: 2px;
}
.kpi-card.armed {
  border-left: 1px solid var(--long);
}
.kpi-card.held {
  border-left: 1px solid var(--warn);
}
.kpi-breadth-card {
  border-left: 1px solid var(--phosphor-dim);
}
.kpi-regime-card {
  border-left: 1px solid var(--cat-2);
  cursor: pointer;
  text-align: left;
}
.kpi-regime-card:hover {
  border-color: var(--rule-hi);
  border-left-color: var(--cat-2);
}

/* Macro/Strategy Navigation Cards */
.kpi-nav-card {
  width: 100%;
  appearance: none;
  text-align: left;
  font: inherit;
  cursor: pointer;
  border-left: 1px solid var(--call);
}
.kpi-nav-card:hover {
  border-color: var(--rule-hi);
  border-left-color: var(--call-hi);
}
.kpi-nav-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 6px;
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--call-hi);
  background: var(--call-wash);
  border: var(--hair) solid var(--call);
  transition: all var(--dur-fast) ease;
}
.kpi-nav-card:hover .kpi-nav-badge {
  color: var(--void);
  background: var(--call-hi);
  border-color: var(--call-hi);
}

.kpi-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
  min-width: 0;
}
.kpi-label {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  color: var(--ink-dim);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kpi-val-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
  min-width: 0;
  margin: 1px 0;
}

.kpi-val {
  font-family: var(--font-data);
  font-size: var(--t-fig);
  font-weight: 500;
  line-height: 1.1;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.warn-text {
  color: var(--warn);
}

.kpi-badge {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  padding: var(--s1) var(--s2);
  border-radius: var(--r-xs);
  text-transform: uppercase;
  flex-shrink: 0;
  white-space: nowrap;
  letter-spacing: 0.04em;
  border: var(--hair) solid currentColor;
}
.kpi-badge.armed,
.kpi-badge.pos {
  color: var(--long);
  background: var(--long-wash);
}
.kpi-badge.held,
.kpi-badge.neg {
  color: var(--short);
  background: var(--short-wash);
}
.kpi-badge.enter {
  color: var(--phosphor);
  background: var(--phosphor-wash);
}
.kpi-badge.flat {
  color: var(--ink-soft);
  background: var(--rule);
  border-color: var(--rule-hi);
}

.kpi-sub {
  font-size: var(--t-tiny);
  color: var(--ink-soft);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.3;
}
.kpi-sub-count {
  color: var(--phosphor-dim);
  font-size: var(--t-micro);
  font-weight: 600;
}
.fl-truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.strat-name {
  font-size: var(--t-lead);
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── High-Confidence Authorization Queue ─────────────────────────────────── */
.confidence-queue {
  border: var(--hair) solid var(--rule);
  border-left: 1px solid var(--phosphor);
  border-radius: var(--r-md);
  background: var(--panel);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  overflow: hidden;
  min-width: 0;
  transition: border-color var(--dur-fast) var(--ease-out);
}
.confidence-queue.has-items {
  border-left-color: var(--long);
}
.confidence-queue-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s4);
  padding: var(--s3) var(--s4);
  background: var(--panel-hi);
  border-bottom: var(--hair) solid var(--rule);
}
.queue-kicker-row {
  display: flex;
  align-items: center;
  gap: var(--s3);
  margin-bottom: 2px;
}
.queue-kicker {
  color: var(--phosphor);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.06em;
}
.queue-edge-pill {
  color: var(--ink-soft);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  padding: var(--s1) var(--s2);
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-hi);
  border-radius: var(--r-xs);
}
.confidence-queue-title strong {
  display: block;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: var(--t-display);
  letter-spacing: var(--track-display);
  font-weight: 600;
}
.queue-note {
  margin-top: var(--s1);
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  max-width: 80ch;
  line-height: 1.4;
}
.confidence-queue-stats {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  flex-shrink: 0;
}
.count-fig {
  font-size: var(--t-fig);
  font-weight: 500;
  line-height: 1;
}
.count-label {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  letter-spacing: 0.08em;
}
.confidence-queue-rows {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: var(--s2);
  padding: var(--s3) var(--s4);
}
.hc-row {
  display: grid;
  grid-template-columns: 5ch auto 1fr auto auto;
  align-items: center;
  gap: var(--s2);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid color-mix(in srgb, var(--long) 50%, var(--rule));
  background: color-mix(in srgb, var(--long) 10%, var(--panel));
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: all var(--dur-fast) ease;
}
.hc-row:hover {
  border-color: var(--long);
  background: color-mix(in srgb, var(--long) 18%, var(--panel));
}
.prob-fig {
  font-size: var(--t-lead);
  font-weight: 800;
}
.horizon-label {
  font-size: var(--t-micro);
}

.confidence-empty {
  display: flex;
  align-items: center;
  gap: var(--s4);
  padding: var(--s4);
  color: var(--ink-soft);
}
.empty-icon-box {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  flex-shrink: 0;
}
.empty-indicator {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-lead);
}
.empty-copy strong {
  display: block;
  color: var(--ink);
  font-size: var(--t-small);
  margin-bottom: 2px;
}
.empty-copy p {
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.4;
}

/* ── Scan Console ────────────────────────────────────────────────────────── */
.scan-console {
  position: relative;
  border: var(--hair) solid var(--rule);
  border-left: var(--hair) solid var(--phosphor);
}

.scan-console-head {
  display: grid;
  grid-template-columns: minmax(170px, 0.75fr) minmax(0, 1.25fr) auto;
  align-items: stretch;
  min-width: 0;
}
.scan-console-head > * {
  min-width: 0;
}
.scan-title-block {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--s1);
  padding: var(--s4) var(--s5);
  border-right: var(--hair) solid var(--rule);
  background: var(--panel);
}
.scan-kicker {
  color: var(--phosphor);
  font-size: var(--t-micro);
  font-weight: 700;
}
.scan-title {
  font-family: var(--font-display);
  color: var(--ink);
  font-size: var(--t-display);
  font-weight: 700;
  letter-spacing: var(--track-tight);
}
.last-scan {
  overflow: visible;
  color: var(--ink-faint);
  font-size: var(--t-micro);
  font-weight: 600;
  line-height: 1.3;
  text-overflow: clip;
  white-space: normal;
}

.scan-readouts {
  display: grid;
  grid-template-columns: repeat(4, minmax(110px, 1fr));
  background: var(--panel);
}
.scan-readout {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  padding: var(--s3) var(--s4);
  border-right: var(--hair) solid var(--rule);
}
.scan-readout > .label {
  color: var(--ink-dim);
  font-size: var(--t-micro);
  font-weight: 700;
}
.scan-readout > .fig {
  color: var(--ink);
  font-size: var(--t-fig);
  font-weight: 500;
}
.scan-readout > .fig i {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  font-style: normal;
  font-weight: 500;
}
.scan-readout > small {
  color: var(--ink-soft);
  font-size: var(--t-micro);
}

.scan-controls {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s3) var(--s5);
  background: var(--panel-hi);
}
.depth-switch {
  display: flex;
  border: var(--hair) solid var(--rule-hi);
}
.depth-option {
  min-width: 88px;
  min-height: var(--density-control-h);
  padding: var(--s2) var(--s3);
  color: var(--ink-soft);
  background: var(--panel);
  border-right: var(--hair) solid var(--rule-hi);
  font-size: var(--t-micro);
  font-weight: 750;
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out);
}
.depth-option:last-child {
  border-right: 0;
}
.depth-option span {
  color: var(--ink-faint);
  margin-left: var(--s1);
  font-weight: 600;
}
.depth-option:hover:not(:disabled) {
  color: var(--ink);
  background: var(--panel-raise);
}
.depth-option.on {
  color: var(--void);
  background: var(--phosphor);
}
.depth-option.on span {
  color: color-mix(in srgb, var(--void) 70%, transparent);
}

.scan-run {
  display: flex;
  align-items: center;
  gap: var(--s2);
  min-width: 170px;
  min-height: var(--density-control-h);
  justify-content: center;
  padding: var(--s2) var(--s3);
  color: var(--void);
  border: var(--hair) solid var(--phosphor);
  border-radius: 2px;
  background: var(--phosphor);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: var(--track-label);
  transition: background var(--dur-fast) var(--ease-out);
}
.scan-run:hover:not(:disabled) {
  background: var(--phosphor-dim);
}
.scan-run:disabled,
.depth-option:disabled {
  cursor: progress;
  opacity: 0.7;
}
.scan-pulse {
  width: 7px;
  height: 7px;
  background: currentColor;
  border-radius: 1px;
}
.scan-run:disabled .scan-pulse {
  animation: scan-blink 720ms steps(2, end) infinite;
}
@keyframes scan-blink {
  50% {
    opacity: 0.2;
  }
}

.scan-progress {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(200px, 0.45fr);
  align-items: center;
  gap: var(--s5);
  padding: var(--s3) var(--s5);
  border-top: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.scan-progress-copy {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: baseline;
  gap: var(--s3);
  min-width: 0;
}
.scan-progress-copy > .label {
  color: var(--phosphor);
  font-size: var(--t-micro);
  font-weight: 700;
  white-space: nowrap;
}
.scan-progress-copy > strong {
  overflow: hidden;
  color: var(--ink);
  font-size: var(--t-small);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.scan-progress-copy > small {
  color: var(--ink-soft);
  font-size: var(--t-micro);
  white-space: nowrap;
}
.scan-progress-track {
  height: 5px;
  overflow: hidden;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void);
}
.scan-progress-track > i {
  display: block;
  height: 100%;
  background: var(--phosphor);
}

.scan-explain {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s4);
  min-height: 32px;
  padding: var(--s2) var(--s5);
  color: var(--ink-soft);
  border-top: var(--hair) solid var(--rule);
  background: var(--void-lift);
  font-size: var(--t-micro);
}
.scan-explain .scan-msg {
  padding: 0;
  color: var(--phosphor);
  font-weight: 600;
}
.scan-flow-link {
  flex: 0 0 auto;
  min-height: 24px;
  padding: 3px 8px;
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  text-decoration: none;
  font-weight: 700;
  font-size: var(--t-micro);
}
.scan-flow-link:hover {
  color: var(--void);
  background: var(--phosphor);
}

/* ── Panel 01: Live Activity Flags ───────────────────────────────────────── */
.activity-panel {
  border-color: var(--rule-hi);
}
.activity-table {
  max-height: 520px;
}
.activity-legend {
  display: flex;
  align-items: center;
  gap: var(--s3);
  color: var(--ink-soft);
  font-size: var(--t-micro);
  font-weight: 600;
}
.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-ghost);
}
.live-dot.on {
  background: var(--phosphor);
}
.pass-label {
  color: var(--ink);
}
.ordinal-note {
  color: var(--warn);
  border-left: var(--hair) solid var(--rule-hi);
  padding-left: var(--s3);
}

.rank-idx {
  display: inline-block;
  width: 3ch;
  margin-right: var(--s2);
  color: var(--ink-faint);
  font-weight: 700;
}
.activity-row:hover {
  background: var(--panel-raise);
}

/* Lean Chips - High Contrast Tokenized */
.lean-chip {
  display: inline-flex;
  min-height: 22px;
  align-items: center;
  padding: 1px 8px;
  border-radius: 2px;
  font-weight: 800;
  letter-spacing: 0.05em;
  font-size: var(--t-micro);
  white-space: nowrap;
}
.lean-chip.bullish {
  color: var(--long);
  border: var(--hair) solid var(--long);
  background: var(--long-wash);
}
.lean-chip.bearish {
  color: var(--short);
  border: var(--hair) solid var(--short);
  background: var(--short-wash);
}
.lean-chip.mixed {
  color: var(--warn);
  border: var(--hair) solid var(--warn);
  background: var(--warn-wash);
}
.lean-chip.neutral {
  color: var(--ink-soft);
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-hi);
}

/* Activity Meter */
.activity-score {
  display: grid;
  grid-template-columns: 4ch 64px;
  justify-content: end;
  align-items: center;
  gap: 2px var(--s2);
}
.score-val {
  font-weight: 750;
  color: var(--ink);
}
.activity-bar-wrap {
  display: block;
  height: 4px;
  overflow: hidden;
  background: var(--rule);
  border-radius: 1px;
}
.activity-bar-wrap b {
  display: block;
  height: 100%;
  background: var(--warn);
}
.ordinal-tag {
  grid-column: 1 / -1;
  text-align: right;
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
}

/* Qlib Cell */
.qlib-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
  white-space: nowrap;
}
.qlib-rank-text {
  color: var(--ink);
  font-weight: 750;
}

/* Flags */
.flag-stack {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-width: 280px;
}
.flag-pill {
  padding: 1px 6px;
  color: var(--ink-soft);
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  border-radius: 2px;
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.03em;
}
.flag-pill.live {
  color: var(--phosphor);
  border-color: color-mix(in srgb, var(--phosphor) 60%, var(--rule));
  background: var(--phosphor-wash);
}

.live-value {
  display: block;
  color: var(--phosphor);
  font-weight: 800;
  font-size: var(--t-small);
}
.flow-count {
  display: block;
  margin-top: 2px;
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: var(--t-micro);
  white-space: nowrap;
}
.local-tag {
  font-size: var(--t-micro);
  font-weight: 600;
}
.price-ret {
  font-weight: 750;
  font-size: var(--t-small);
}

/* Signal Context (Structured 2-Line Direction Cell) */
.signal-context {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 130px;
  max-width: 220px;
}
.signal-context-top,
.signal-context-bottom {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.context-source,
.coverage-chip {
  padding: 2px 6px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-soft);
  background: var(--panel-hi);
  font-size: var(--t-micro);
  font-weight: 700;
  border-radius: 2px;
  white-space: nowrap;
}
.alignment-chip {
  display: inline-flex;
  min-height: 20px;
  align-items: center;
  padding: 1px 6px;
  border-radius: 2px;
  font-size: var(--t-micro);
  font-weight: 800;
  letter-spacing: 0.04em;
  white-space: nowrap;
  border: var(--hair) solid currentColor;
}
.alignment-chip.agree {
  color: var(--long);
  border-color: var(--long);
  background: var(--long-wash);
}
.alignment-chip.conflict {
  color: var(--short);
  border-color: var(--short);
  background: var(--short-wash);
}
.alignment-chip.pead_only,
.alignment-chip.directional_only {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}
.context-edge {
  color: var(--warn);
  font-size: var(--t-micro);
  font-weight: 700;
}

/* ── Signal Contract Reconciliation ──────────────────────────────────────── */
.signal-contract {
  display: grid;
  grid-template-columns: minmax(300px, 1fr) auto;
  gap: var(--s4) var(--s5);
  padding: var(--s4) var(--s5);
  border: var(--hair) solid var(--rule-hi);
  border-left: 1px solid var(--warn);
  background: var(--panel);
}
.contract-kicker-row {
  display: flex;
  align-items: center;
  gap: var(--s3);
  margin-bottom: 2px;
}
.contract-kicker {
  color: var(--warn);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.08em;
}
.contract-rule-badge {
  color: var(--ink-soft);
  font-size: var(--t-micro);
  padding: 1px 6px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-hi);
  border-radius: 2px;
}
.signal-contract-copy > strong {
  display: block;
  margin-top: 2px;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: var(--t-display);
  letter-spacing: 0.02em;
}
.signal-contract-copy > p {
  max-width: 85ch;
  margin-top: 4px;
  color: var(--ink-soft);
  font-size: var(--t-tiny);
  line-height: 1.45;
}
.reconciliation-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(80px, 1fr));
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-hi);
}
.stat-box {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  min-width: 80px;
  padding: var(--s3) var(--s3);
  border-right: var(--hair) solid var(--rule-hi);
}
.stat-box:last-child {
  border-right: 0;
}
.stat-box .label {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  font-weight: 700;
  margin-bottom: 2px;
}
.stat-box strong {
  font-size: var(--t-fig);
  font-weight: 500;
}
.stat-box.agree strong {
  color: var(--long);
}
.stat-box.conflict strong {
  color: var(--short);
}

.conflict-strip {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s2);
  padding-top: var(--s3);
  border-top: var(--hair) solid var(--rule);
  color: var(--short);
}
.conflict-head {
  font-weight: 750;
  font-size: var(--t-micro);
}
.conflict-item {
  padding: 2px 8px;
  border: var(--hair) solid color-mix(in srgb, var(--short) 60%, var(--rule));
  background: var(--short-wash);
  border-radius: 2px;
  font-size: var(--t-micro);
  font-weight: 700;
}

/* ── Model Views Controls ────────────────────────────────────────────────── */
.model-views-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s4);
  padding: var(--s2) 0 var(--s1);
  margin-top: var(--s2);
  border-bottom: var(--hair) solid var(--rule-hi);
}
.section-kicker {
  color: var(--phosphor-dim);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.08em;
}
.model-views-kicker h2 {
  font-family: var(--font-display);
  font-size: var(--t-display);
  color: var(--ink);
  font-weight: 700;
  margin-top: 1px;
}
.view-mode-tabs {
  display: flex;
  border: var(--hair) solid var(--rule-hi);
  border-radius: 2px;
  overflow: hidden;
}
.view-tab {
  padding: var(--s2) var(--s3);
  font-size: var(--t-micro);
  font-weight: 750;
  color: var(--ink-soft);
  background: var(--panel);
  border-right: var(--hair) solid var(--rule-hi);
  transition: all var(--dur-fast) ease;
}
.view-tab:last-child {
  border-right: 0;
}
.view-tab:hover {
  color: var(--ink);
  background: var(--panel-hi);
}
.view-tab.active {
  color: var(--void);
  background: var(--phosphor);
}

/* ── Filter Controls & Action Bar ────────────────────────────────────────── */
.action-bar {
  display: flex;
  align-items: center;
  gap: var(--s3);
}
.select-wrap {
  position: relative;
}
.filter-select {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  color: var(--phosphor);
  font-size: var(--t-micro);
  font-weight: 750;
  padding: var(--s2) var(--s3);
  border-radius: 2px;
  cursor: pointer;
  transition: border-color var(--dur-fast);
}
.filter-select:hover,
.filter-select:focus-visible {
  border-color: var(--phosphor);
}
.filter-select option {
  background: var(--panel);
  color: var(--ink);
}

/* ── Tables & Grid Data ──────────────────────────────────────────────────── */
.table-container {
  max-height: 480px;
  overflow-y: auto;
  overflow-x: auto;
  scrollbar-width: thin;
}

.grid {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-small);
}
.grid th {
  text-align: left;
  padding: var(--s3) var(--s4);
  color: var(--ink-dim);
  border-bottom: var(--hair) solid var(--rule-hi);
  position: sticky;
  top: 0;
  background: var(--panel-hi);
  font-weight: 750;
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  z-index: 1;
  white-space: nowrap;
}
.grid td {
  padding: var(--s2) var(--s4);
  border-bottom: var(--hair) solid var(--rule-faint);
  color: var(--ink);
  vertical-align: middle;
}
.grid tbody tr {
  cursor: pointer;
  transition: background var(--dur-fast);
}
.grid tbody tr:hover {
  background: var(--panel-hi);
}

.num {
  text-align: right;
}
.sym {
  color: var(--phosphor);
  font-weight: 750;
  font-size: var(--t-small);
}

/* Split View Column Condensation (.w-half) */
.w-half .table-pead th,
.w-half .table-pead td,
.w-half .table-directional th,
.w-half .table-directional td {
  padding: var(--s2) var(--s2);
}
.w-half .col-sym {
  min-width: 54px;
}
.w-half .col-last,
.w-half .col-chg {
  min-width: 48px;
  font-size: var(--t-tiny);
}
.w-half .col-side {
  min-width: 42px;
  padding-left: 2px;
  padding-right: 2px;
}
.w-half .col-score {
  min-width: 46px;
  font-size: var(--t-tiny);
}
.w-half .col-5d,
.w-half .col-gap-event {
  max-width: 110px;
  overflow: hidden;
}
.w-half .col-state {
  min-width: 48px;
}
.w-half .col-chain {
  width: 44px;
  padding-left: 2px;
  padding-right: 2px;
}
.w-half .chain-btn {
  padding: var(--s1) var(--s2);
  font-size: var(--t-micro);
}
.w-half .side-pill {
  min-width: 36px;
  font-size: var(--t-micro);
  padding: var(--s1) var(--s2);
}
.w-half .prob-cell {
  gap: var(--s1);
}
.w-half .prob-bar-wrap {
  width: 32px;
  height: 4px;
}
.w-half .mom-wrap {
  gap: 4px;
}
.w-half .mom-bar {
  width: 22px;
  height: 3px;
}
.w-half .alignment-chip {
  font-size: var(--t-micro);
  padding: var(--s1) var(--s2);
}
.w-half .coverage-chip {
  font-size: var(--t-micro);
  padding: var(--s1) var(--s2);
}

/* Side Pills */
.side-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 48px;
  font-size: var(--t-micro);
  font-weight: 800;
  letter-spacing: 0.05em;
  padding: 2px 6px;
  border-radius: 2px;
  text-align: center;
}
.side-pill.pos {
  color: var(--long);
  border: var(--hair) solid var(--long);
  background: var(--long-wash);
}
.side-pill.neg {
  color: var(--short);
  border: var(--hair) solid var(--short);
  background: var(--short-wash);
}
.side-pill.neutral {
  color: var(--ink-soft);
  border: var(--hair) solid var(--rule-hi);
  background: var(--rule);
}

/* Directional Edge Gauges */
.prob-cell {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--s3);
}
.prob-bar-wrap {
  width: 50px;
  height: 5px;
  background: var(--rule);
  border-radius: 1px;
  overflow: hidden;
}
.prob-bar {
  height: 100%;
  border-radius: 1px;
}
.prob-bar.pos {
  background: var(--phosphor);
}
.prob-bar.mod {
  background: var(--warn);
}
.prob-bar.flat {
  background: var(--ink-ghost);
  opacity: 0.6;
}
.prob-cell.weak {
  opacity: 0.75;
}
.confidence-value {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  line-height: 1.1;
  font-weight: 750;
}
.confidence-value small {
  font-family: var(--font-ui);
  font-size: var(--t-micro);
  font-weight: 800;
  letter-spacing: 0.08em;
}
.confidence-high {
  color: var(--long);
}
.confidence-moderate {
  color: var(--warn);
}
.confidence-low,
.confidence-unavailable {
  color: var(--ink-faint);
}
.row-high td {
  background: color-mix(in srgb, var(--long) 7%, transparent);
}

/* Momentum Cells */
.mom-wrap {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}
.mom-bar {
  width: 36px;
  height: 4px;
  background: var(--rule);
  overflow: hidden;
  border-radius: 1px;
}
.mom-bar i {
  display: block;
  height: 100%;
  background: currentColor;
  opacity: 0.85;
}

/* Status Badges */
.state {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border: var(--hair) solid currentColor;
  border-radius: 2px;
  font-weight: 750;
  font-size: var(--t-micro);
  letter-spacing: 0.04em;
}
.state.enter {
  color: var(--phosphor);
  background: var(--phosphor-wash);
}
.state.watch {
  color: var(--ink-soft);
  border-color: var(--rule-hi);
  background: var(--panel-hi);
}

/* Action Buttons */
.chain-btn {
  padding: var(--s1) var(--s2);
  border: var(--hair) solid var(--rule-hi);
  border-radius: 2px;
  background: var(--panel-hi);
  color: var(--call-hi);
  font-weight: 750;
  font-size: var(--t-micro);
  cursor: pointer;
  transition: all var(--dur-fast) ease;
}
.chain-btn:hover,
.chain-btn:focus-visible {
  color: var(--void);
  background: var(--call-hi);
  border-color: var(--call-hi);
}

/* ── Panel 04: Personal Watchlist ────────────────────────────────────────── */
.probe-input-bar {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}
.probe-input {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink);
  font-size: var(--t-micro);
  font-weight: 600;
  padding: var(--s2) var(--s3);
  border-radius: 2px;
  width: 220px;
  transition: border-color var(--dur-fast);
}
.probe-input:focus {
  border-color: var(--phosphor);
}
.act {
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--rule-hi);
  border-radius: 2px;
  font-size: var(--t-micro);
  font-weight: 750;
  cursor: pointer;
  transition: all var(--dur-fast) ease;
}
.act-primary {
  color: var(--void);
  background: var(--phosphor);
  border-color: var(--phosphor);
}
.act-primary:hover:not(:disabled) {
  background: var(--phosphor-dim);
}
.act-secondary {
  color: var(--ink);
  background: transparent;
}
.act-secondary:hover:not(:disabled) {
  border-color: var(--rule-hi);
  background: var(--panel-hi);
}
.act:disabled {
  opacity: 0.6;
  cursor: progress;
}

.table-watchlist {
  width: 100%;
  table-layout: fixed;
  border-collapse: separate;
  border-spacing: 0;
}
.table-watchlist th,
.table-watchlist td {
  box-sizing: border-box;
  vertical-align: middle;
  border-bottom: var(--hair) solid var(--rule-faint);
}
.table-watchlist th {
  border-bottom: var(--hair) solid var(--rule-hi);
}
.table-watchlist tbody tr:last-child td {
  border-bottom: var(--hair) solid var(--rule);
}
.table-watchlist .col-sym {
  width: 9%;
}
.table-watchlist .col-spark {
  width: 13%;
}
.table-watchlist .col-price {
  width: 10%;
}
.table-watchlist .col-ret1,
.table-watchlist .col-ret5 {
  width: 8%;
}
.table-watchlist .col-edge {
  width: 11%;
}
.table-watchlist .col-regime {
  width: 18%;
}
.table-watchlist .col-mom {
  width: 8%;
}
.table-watchlist .col-act {
  width: 15%;
}

.col-regime {
  min-width: 145px;
}
.regime-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.magnet-sub {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  color: var(--phosphor-dim);
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mono-dist {
  font-family: var(--font-data);
  color: var(--ink-dim);
}
.state-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
}
.table-watchlist .spark-cell {
  width: 16%;
  color: var(--phosphor);
  vertical-align: middle;
}
.table-watchlist .spark {
  width: 88px;
  height: 22px;
  display: block;
  margin: 0;
}
.spark-cell {
  width: 96px;
  color: var(--phosphor);
}
.spark {
  width: 88px;
  height: 22px;
  display: block;
}
.spark path {
  vector-effect: non-scaling-stroke;
}

.edge-pill-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 750;
}
.edge-pill-wrap.pos {
  color: var(--long);
}
.edge-pill-wrap.mod {
  color: var(--warn);
}
.state-mini {
  font-size: var(--t-micro);
  padding: var(--s1) var(--s2);
  border: var(--hair) solid currentColor;
  border-radius: 1px;
}
.watch-actions {
  display: flex;
  align-items: center;
  gap: var(--s2);
}
.remove-btn {
  background: transparent;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-faint);
  font-size: var(--t-micro);
  font-weight: 750;
  padding: var(--s1) var(--s2);
  border-radius: 2px;
  cursor: pointer;
  transition: all var(--dur-fast) ease;
}
.remove-btn:hover {
  color: var(--short);
  border-color: var(--short);
  background: var(--short-wash);
}

/* ── Shared Utilities & Responsive Breakpoints ───────────────────────────── */
.dim {
  color: var(--ink-faint);
}
.pos {
  color: var(--long);
}
.neg {
  color: var(--short);
}
.confidence-footnote {
  border-top: var(--hair) solid var(--rule);
  margin-top: 0 !important;
}
.note {
  color: var(--ink-soft);
  font-size: var(--t-small);
}
.note.pad {
  padding: var(--s5) var(--s4);
}
.note.pad-x {
  padding: var(--s3) var(--s4) var(--s4);
}
.note.tiny {
  font-size: var(--t-micro);
  margin-top: var(--s3);
}
.err {
  color: var(--short);
  font-size: var(--t-small);
}
.err.pad {
  padding: var(--s3) var(--s4);
}

@media (max-width: 1400px) {
  .desk-summary {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .kpi-nav-card:nth-child(4) {
    grid-column: span 1;
  }
  .kpi-nav-card:nth-child(5) {
    grid-column: span 1;
  }
  .desk {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .scan-console-head {
    grid-template-columns: 180px 1fr;
  }
  .scan-controls {
    grid-column: 1 / -1;
    border-top: var(--hair) solid var(--rule);
    justify-content: flex-end;
  }
}
@media (max-width: 1100px) {
  .w-half {
    grid-column: span 4;
  }
  .desk-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .kpi-breadth-card {
    grid-column: 1 / -1;
  }
  .kpi-nav-card:nth-child(5) {
    grid-column: span 1;
  }
  .reconciliation-stats {
    grid-template-columns: repeat(2, 1fr);
  }
  .stat-box:nth-child(2) {
    border-right: 0;
  }
  .stat-box:nth-child(-n + 2) {
    border-bottom: var(--hair) solid var(--rule-hi);
  }
}
@media (max-width: 768px) {
  .arena-head {
    align-items: flex-start;
    flex-direction: column;
    gap: var(--s3);
    padding-bottom: var(--s3);
  }
  .arena-context {
    justify-content: flex-start;
  }
  .arena-flow-link {
    min-height: 40px;
  }
  .desk-summary {
    grid-template-columns: 1fr;
  }
  .desk {
    grid-template-columns: 1fr;
  }
  .w-half {
    grid-column: span 1;
  }
  .action-bar {
    flex-direction: column;
    align-items: flex-start;
  }
  .scan-console-head {
    display: flex;
    flex-direction: column;
  }
  .scan-title-block {
    border-right: 0;
    border-bottom: var(--hair) solid var(--rule);
  }
  .scan-readouts {
    grid-template-columns: repeat(2, 1fr);
  }
  .scan-controls {
    flex-wrap: wrap;
    justify-content: stretch;
  }
  .depth-switch,
  .scan-run {
    flex: 1 1 100%;
  }
  .depth-option {
    flex: 1;
  }
  .scan-progress {
    grid-template-columns: 1fr;
    gap: var(--s3);
  }
  .scan-progress-copy {
    grid-template-columns: 1fr auto;
  }
  .scan-progress-copy > strong {
    grid-column: 1 / -1;
    grid-row: 2;
    white-space: normal;
  }
  .scan-explain {
    align-items: flex-start;
    flex-direction: column;
  }
  .signal-contract {
    grid-template-columns: 1fr;
  }
  .model-views-header {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--s2);
  }
  .view-mode-tabs {
    width: 100%;
  }
  .view-tab {
    flex: 1;
    text-align: center;
  }
}
</style>
