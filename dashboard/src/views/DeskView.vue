<script setup lang="ts">
import { computed, inject, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  api,
  type ActivityFlagRow,
  type StatusPayload,
  type Readiness,
  type ScanDepth,
  type ScanJob,
  type Trajectory,
} from '@/api'
import type { Resource } from '@/composables/useResource'
import { num, pctFrac, signedPct, tone, usd, DASH } from '@/format'
import { sparkline } from '@/charts'
import Panel from '@/components/Panel.vue'
import VerdictChip from '@/components/VerdictChip.vue'

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

// Filtering state for dropdowns
const peadFilter = ref<'all' | 'flagged' | 'long' | 'short'>('all')
const signalFilter = ref<'all' | 'entered' | 'actionable' | 'long' | 'short'>('all')

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
const customWatchlist = ref<string[]>(['NVDA', 'TSLA', 'AMD'])
const probeResults = ref<Record<string, Trajectory | null>>({})

let watchlistTimer: number | undefined

onMounted(() => {
  try {
    const saved = localStorage.getItem('edge_custom_watchlist')
    if (saved) {
      const parsed = JSON.parse(saved)
      if (Array.isArray(parsed) && parsed.length > 0) {
        customWatchlist.value = parsed.map((s) => String(s).toUpperCase())
      }
    }
  } catch {
    /* fallback to default */
  }
  void probeWatchlist(true)
  void resumeScanJob()
  // Keep personal watchlist fresh even when the shared status asof is quiet.
  watchlistTimer = window.setInterval(() => void probeWatchlist(true), 60_000)
})

onUnmounted(() => {
  scanPollToken += 1
  if (watchlistTimer !== undefined) clearInterval(watchlistTimer)
})

function saveWatchlist(): void {
  try {
    localStorage.setItem('edge_custom_watchlist', JSON.stringify(customWatchlist.value))
  } catch {
    /* ignore storage errors */
  }
}

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
      customWatchlist.value.push(clean)
      saveWatchlist()
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
    if (asof && asof !== prev) void probeWatchlist(true)
  },
)

function removeWatchlistSymbol(sym: string): void {
  const idx = customWatchlist.value.indexOf(sym)
  if (idx >= 0) {
    customWatchlist.value.splice(idx, 1)
    delete probeResults.value[sym]
    saveWatchlist()
  }
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
const reconciledBySymbol = computed(() => new Map(
  (reconciliation.value?.rows ?? []).map((row) => [row.symbol.toUpperCase(), row]),
))

watch(
  () => scan.value?.depth,
  (depth) => {
    if (depth === 'quick' || depth === 'deep') scanDepth.value = depth
  },
  { immediate: true },
)

/* Filtering + confidence ranking */
const peadFlagged = computed(() => pead.value.filter((p) => p.setup_ok || p.model?.state === 'FLAG').length)
const sigEntered = computed(() => signals.value.filter((s) => s.state === 'ENTER').length)
const sigHighConf = computed(() =>
  signals.value.filter((s) => hasHighConfidence(s.probability, s.state)).length,
)
const sigActionable = computed(() =>
  signals.value.filter((s) => hasActionableEdge(s.probability)).length,
)
const maxCalibratedEdge = computed(() => {
  let max = 0
  for (const s of signals.value) {
    if (typeof s.probability === 'number' && Number.isFinite(s.probability) && s.probability > max) {
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
const peadGateVerdict = computed(() => String(scan.value?.pead_gate_verdict ?? 'UNKNOWN').toUpperCase())
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
    detail: maxCalibratedEdge.value != null
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
const deepScopeCount = computed(() =>
  scan.value?.activity_market_universe_symbols ?? d.value?.market_universe_count ?? d.value?.searchable_symbol_count ?? 576,
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
  String(scanJob.value?.stage || 'starting').replaceAll('_', ' ').toUpperCase(),
)

function confidenceBand(value: number | null | undefined): 'HIGH' | 'MODERATE' | 'LOW' | 'UNAVAILABLE' {
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
  const ap = typeof a.probability === 'number' && Number.isFinite(a.probability) ? a.probability : -1
  const bp = typeof b.probability === 'number' && Number.isFinite(b.probability) ? b.probability : -1
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
  return signals.value.find((s) => s.symbol?.toUpperCase() === sym.toUpperCase()) ?? null
}

function peadFor(sym: string): PeadRow | null {
  return pead.value.find((row) => row.symbol?.toUpperCase() === sym.toUpperCase()) ?? null
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

const watchSparks = computed(() => {
  const out: Record<string, string> = {}
  for (const [sym, traj] of Object.entries(probeResults.value)) {
    const closes = traj?.series?.map((b) => b.c) ?? []
    if (closes.length > 2) {
      out[sym] = sparkline(closes.slice(-40), 88, 22, 2).d
    }
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
    <header class="arena-head">
      <div class="arena-title">
        <span class="label arena-kicker">Desk / Arena</span>
        <h1>Execution arena</h1>
        <p>Capital posture, ranked market activity, and the names worth opening for deeper work.</p>
      </div>

      <div class="arena-context" aria-label="Desk scope and shortcuts">
        <span class="scope-chip">SESSION BOARD</span>
        <span class="scope-chip" :class="scan?.depth === 'deep' ? 'live' : 'proxy'">
          {{ scan?.depth === 'deep' ? 'MARKET-WIDE SCAN' : 'LOCAL SCAN' }}
        </span>
        <span class="scope-chip" :class="r?.cleared_for_live ? 'live' : 'held'">
          {{ r?.cleared_for_live ? 'CAPITAL CLEARED' : 'PAPER MODE' }}
        </span>
        <RouterLink :to="{ name: 'flow' }" class="arena-flow-link label">OPEN MARKET FLOW</RouterLink>
      </div>
    </header>

    <!-- ── 00 Summary KPI Deck ─────────────────────────────────────────── -->
    <div class="desk-summary">
      <div class="kpi-card" :class="r?.cleared_for_live ? 'armed' : 'held'">
        <span class="label kpi-label">Capital Status</span>
        <div class="kpi-val-row">
          <span class="kpi-val">{{ r?.cleared_for_live ? 'ARMED' : 'HELD' }}</span>
          <span class="kpi-badge" :class="r?.cleared_for_live ? 'armed' : 'held'">
            {{ r?.cleared_for_live ? 'LIVE READY' : 'PAPER TRADING' }}
          </span>
        </div>
        <span class="kpi-sub">
          {{ r?.blocking_reasons?.length ? `${r.blocking_reasons.length} blocker(s) active` : '0 blockers recorded' }}
        </span>
      </div>

      <div class="kpi-card" :class="confidencePosture.tone">
        <span class="label kpi-label">Confidence Posture</span>
        <div class="kpi-val-row">
          <span class="kpi-val fig" :class="sigHighConf > 0 ? 'pos' : ''">{{ confidencePosture.label }}</span>
          <span class="kpi-badge" :class="sigHighConf > 0 ? 'enter' : 'held'">
            {{ sigEntered }} ENTER · {{ sigHighConf }} HIGH
          </span>
        </div>
        <span class="kpi-sub" :title="confidencePosture.detail">
          {{ confidencePosture.detail }}
        </span>
      </div>

      <div class="kpi-card">
        <span class="label kpi-label">Activity Flags</span>
        <div class="kpi-val-row">
          <span class="kpi-val fig">{{ activity.length }}</span>
          <span class="kpi-badge flat">{{ scan?.depth?.toUpperCase() ?? 'SCAN' }}</span>
        </div>
        <span class="kpi-sub">
          {{ liveActivityCount }} live flow · {{ pead.length }} PEAD ordinal
        </span>
      </div>

      <button class="kpi-card clickable" type="button" aria-label="Open Sectors for top sector flow" @click="navTo('sectors')">
        <span class="label kpi-label">Top Sector Flow</span>
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

      <button class="kpi-card clickable" type="button" aria-label="Open Gates for the top alpha strategy" @click="navTo('gates')">
        <span class="label kpi-label">Top Alpha Strategy</span>
        <div class="kpi-val-row">
          <span class="kpi-val strat-name">{{ topStrategy ? topStrategy.strategy : '—' }}</span>
          <VerdictChip v-if="topStrategy" :verdict="topStrategy.verdict" size="sm" />
        </div>
        <span class="kpi-sub">
          Net {{ topStrategy?.net_return ?? '—' }} · Sharpe {{ topStrategy?.sharpe ?? '—' }}
        </span>
      </button>
    </div>

    <!-- High-confidence queue — empty is an explicit, honest state -->
    <section class="confidence-queue w-full" aria-label="High confidence directional queue">
      <div class="confidence-queue-head">
        <div>
          <span class="label">High-confidence queue</span>
          <strong>Calibrated p ≥ {{ pctFrac(ENTER_EDGE, 0) }} or ENTER state</strong>
          <p class="label queue-note">
            PEAD ordinal flags never appear here. Moderate watches ({{ pctFrac(ACTIONABLE_EDGE, 0) }}–{{ pctFrac(ENTER_EDGE, 0) }}) stay in Directional Signals only.
          </p>
        </div>
        <div class="confidence-queue-stats">
          <span class="fig">{{ highConfidenceQueue.length }}</span>
          <span class="label">NAMES</span>
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
          <span class="fig pos">{{ pctFrac(s.probability, 1) }}</span>
          <span class="state label enter">{{ s.state }}</span>
          <span class="label dim">{{ (s.horizon ?? '').replace(' Days', 'd') }}</span>
        </button>
      </div>
      <p v-else class="note pad confidence-empty">
        <template v-if="signals.length === 0">
          No directional scores loaded — run a scan.
        </template>
        <template v-else>
          No high-confidence authorizations this session.
          Max calibrated edge
          <strong class="fig">{{ maxCalibratedEdge != null ? pctFrac(maxCalibratedEdge, 1) : DASH }}</strong>
          · ENTER bar <strong class="fig">{{ pctFrac(ENTER_EDGE, 0) }}</strong>
          · {{ sigActionable }} moderate watch(es) only.
        </template>
      </p>
    </section>

    <section class="scan-console" aria-label="Market scan depth">
      <div class="scan-console-head">
        <div class="scan-title-block">
          <span class="label scan-kicker">Scan scope</span>
          <strong class="scan-title">{{ selectedScanTitle }}</strong>
          <span class="last-scan label">LAST COMPLETE · {{ scan?.depth?.toUpperCase() ?? 'NONE' }}</span>
        </div>

        <div class="scan-readouts" aria-label="Latest scan coverage">
          <div class="scan-readout">
            <span class="label">Market activity</span>
            <span class="fig">
              {{ scan?.activity_local_scanned_symbols ?? 0 }}<i>/{{ scan?.activity_market_universe_symbols ?? d?.market_universe_count ?? '—' }}</i>
            </span>
            <small>daily bars ranked</small>
          </div>
          <div class="scan-readout">
            <span class="label">Live LSE flow</span>
            <span class="fig">
              {{ scan?.activity_live_completed_symbols ?? 0 }}<i>/{{ scan?.activity_live_requested_symbols ?? 0 }}</i>
            </span>
            <small>{{ scan?.activity_live_with_prints_symbols ?? 0 }} names with prints</small>
          </div>
          <div class="scan-readout">
            <span class="label">Calibrated model</span>
            <span class="fig">
              {{ scan?.directional_scored_symbols ?? signals.length }}<i>/{{ scan?.directional_model_universe_symbols ?? '—' }}</i>
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
            {{ scanning ? `${scanJob?.progress ?? 0}% · ${selectedScanLabel}` : `RUN ${scanDepth.toUpperCase()} SCAN` }}
          </button>
        </div>
      </div>
      <div v-if="scanning && scanJob" class="scan-progress" role="status" aria-live="polite">
        <div class="scan-progress-copy">
          <span class="label">{{ scanJob.depth.toUpperCase() }} PASS · {{ scanStageLabel }}</span>
          <strong>{{ scanJob.message }}</strong>
          <small class="fig">{{ num(scanJob.elapsed_seconds, 1) }}s elapsed · the desk remains available</small>
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
        <span v-else class="label">Selected scope is executing as a background job; leaving this view will not cancel it.</span>
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
          {{ livePassLabel }}
          <span>ORDINAL · NOT PROBABILITY</span>
        </div>
      </template>

      <div class="table-container activity-table">
        <table v-if="activity.length" class="grid">
          <thead>
            <tr>
              <th class="label">Rank / Symbol</th>
              <th class="label num">Activity</th>
              <th class="label num">Qlib XS</th>
              <th class="label">Observed Flags</th>
              <th class="label num">Live Flow</th>
              <th class="label num">Price / Volume</th>
              <th class="label">Direction Context</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in activity" :key="row.symbol" @click="open(row.symbol)">
              <td>
                <span class="rank-idx fig">{{ String(row.activity_rank).padStart(2, '0') }}</span>
                <span class="fig sym">{{ row.symbol }}</span>
              </td>
              <td class="num">
                <div class="activity-score">
                  <span class="fig">{{ num(row.activity_score, 1) }}</span>
                  <i aria-hidden="true"><b :style="{ width: `${row.activity_score}%` }" /></i>
                  <small class="label">ORDINAL</small>
                </div>
              </td>
              <td class="num fig">
                <div
                  v-if="row.qlib_rank != null"
                  class="qlib-cell"
                  :title="`Ordinal qlib cross-sectional rank · ${row.qlib_source ?? 'research source'} · ${row.qlib_asof ?? 'as-of unavailable'}`"
                >
                  <strong>#{{ row.qlib_rank }}</strong>
                  <small class="dim">XS {{ row.qlib_score != null ? num(row.qlib_score, 2) : DASH }} · RSCH</small>
                </div>
                <span v-else class="dim">—</span>
              </td>
              <td>
                <div class="flag-stack">
                  <span v-for="flag in row.flags.slice(0, 3)" :key="flag" :class="{ live: flag.includes('LIVE') || flag.includes('$1M') }">
                    {{ flag }}
                  </span>
                </div>
              </td>
              <td class="fig num">
                <template v-if="row.live">
                  <strong class="live-value">{{ row.premium == null ? DASH : usd(row.premium) }}</strong>
                  <small class="flow-count">{{ row.print_count }} prints · C{{ row.call_print_count }}/P{{ row.put_print_count }}</small>
                </template>
                <span v-else class="dim">LOCAL ONLY</span>
              </td>
              <td class="fig num">
                <span :class="tone((row.ret_1d ?? 0) * 100)">{{ signedPct((row.ret_1d ?? 0) * 100, 1) }}</span>
                <small class="flow-count">{{ row.volume_vs_20d_median == null ? DASH : `${num(row.volume_vs_20d_median, 1)}× vol` }}</small>
              </td>
              <td>
                <div class="signal-context">
                  <span v-if="row.pead_side" class="context-source label">GAP {{ sideWord(row.pead_side) }}</span>
                  <span v-if="row.directional_side" class="context-source label">5D {{ sideWord(row.directional_side) }}</span>
                  <span
                    class="alignment-chip label"
                    :class="row.signal_alignment || 'none'"
                  >
                    {{ row.signal_alignment === 'agree' ? 'AGREE'
                      : row.signal_alignment === 'conflict' ? 'CONFLICT'
                        : row.signal_alignment === 'pead_only' ? 'EVENT ONLY'
                          : row.signal_alignment === 'directional_only' ? 'MODEL ONLY' : 'NO VIEW' }}
                  </span>
                  <small v-if="row.calibrated_probability != null && hasActionableEdge(row.calibrated_probability)" class="context-edge">
                    model {{ pctFrac(row.calibrated_probability, 1) }}
                  </small>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">
          No activity rows are available. Run Deep to scan the full catalog and request live LSE flow.
        </p>
      </div>
      <p class="note tiny pad confidence-footnote">
        Activity score ranks observed price, volume, gaps, and live premium. It is not win probability; unsigned call/put flow never supplies trade direction.
      </p>
    </Panel>

    <section class="signal-contract w-full" aria-label="PEAD and directional signal reconciliation">
      <div class="signal-contract-copy">
        <span class="label">Signal contract</span>
        <strong>OPENING GAP EVENT ≠ 5-DAY FORECAST</strong>
        <p>
          PEAD records what happened at the open. Directional estimates the next multi-session move inside a smaller frozen model domain.
          Only the same symbol can agree or conflict; different symbols are non-overlap, not disagreement.
        </p>
      </div>
      <div class="reconciliation-stats" aria-label="Signal overlap counts">
        <div><span class="label">Overlap</span><strong class="fig">{{ reconciliation?.counts.overlap ?? 0 }}</strong></div>
        <div class="agree"><span class="label">Agree</span><strong class="fig">{{ reconciliation?.counts.agreements ?? 0 }}</strong></div>
        <div class="conflict"><span class="label">Conflict</span><strong class="fig">{{ reconciliation?.counts.conflicts ?? 0 }}</strong></div>
        <div><span class="label">Separate names</span><strong class="fig">{{ (reconciliation?.counts.pead_only ?? pead.length) + (reconciliation?.counts.directional_only ?? signals.length) }}</strong></div>
      </div>
      <div v-if="reconciliation?.counts.conflicts" class="conflict-strip label">
        NO UNIFIED THESIS:
        <span v-for="row in reconciliation.rows.filter((item) => item.relation === 'conflict')" :key="row.symbol">
          {{ row.symbol }} · GAP {{ sideWord(row.pead_side) }} / 5D {{ sideWord(row.directional_side) }}
        </span>
      </div>
    </section>

    <!-- ── 02 PEAD gap/volume flags ─────────────────────────────────────── -->
    <Panel
      label="PEAD Gap / Volume Flags"
      index="02"
      :meta="peadMeta"
      :delay="60"
      flush
      class="w-half"
    >
      <template #action>
        <div class="action-bar">
          <div class="select-wrap">
            <select v-model="peadFilter" class="filter-select label">
              <option value="all">ALL FLAGS ({{ pead.length }})</option>
              <option value="flagged">SETUP OK ({{ peadFlagged }})</option>
              <option value="long">UP-GAP FLAGS</option>
              <option value="short">DOWN-GAP FLAGS</option>
            </select>
          </div>
        </div>
      </template>

      <div class="table-container">
        <table v-if="filteredPead.length" class="grid">
          <thead>
            <tr>
              <th class="label">Symbol</th>
              <th class="label">Side</th>
              <th class="label num">Strength</th>
              <th class="label num">Gap / ATR</th>
              <th class="label num">Volume</th>
              <th class="label">5D Forecast</th>
              <th class="label">State</th>
              <th class="label">Options</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(c, i) in filteredPead" :key="i" @click="open(c.symbol)">
              <td class="fig sym">{{ c.symbol }}</td>
              <td>
                <span class="side-pill" :class="c.side === 'long' ? 'pos' : 'neg'">
                  {{ (c.side ?? DASH).toUpperCase() }}
                </span>
              </td>
              <td class="fig num" :class="tone(c.evidence?.pead_score)">{{ num(Math.abs(c.evidence?.pead_score ?? 0), 2) }}</td>
              <td class="fig num" :class="tone(c.evidence?.gap_std)">{{ num(c.evidence?.gap_std, 2) }}</td>
              <td class="fig num">{{ num(c.evidence?.vol_surge, 2) }}×</td>
              <td>
                <span
                  v-if="signalFor(c.symbol)"
                  class="alignment-chip label"
                  :class="relationFor(c.symbol)"
                >
                  {{ relationFor(c.symbol) === 'agree' ? `AGREES ${sideWord(signalFor(c.symbol)?.side)}` : `CONFLICT ${sideWord(signalFor(c.symbol)?.side)}` }}
                </span>
                <span v-else class="coverage-chip label">NO 5D MODEL ROW</span>
              </td>
              <td>
                <span class="state label watch">
                  {{ c.model?.state ?? DASH }}
                </span>
              </td>
              <td>
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
          {{ pead.length === 0 ? 'No gap/volume flags cleared the ordinal threshold this session.' : 'No flags match the selected filter.' }}
        </p>
      </div>
      <p class="note tiny pad confidence-footnote">
        PEAD gate <strong>{{ peadGateVerdict }}</strong>.
        Strength is ordinal (not probability) and cannot authorize an entry or be read as confidence.
      </p>
    </Panel>

    <!-- ── 03 Directional Signals ──────────────────────────────────────── -->
    <Panel
      label="Directional Signals"
      index="03"
      :meta="signalMeta"
      :delay="120"
      flush
      class="w-half"
    >
      <template #action>
        <div class="action-bar">
          <div class="select-wrap">
            <select v-model="signalFilter" class="filter-select label">
              <option value="all">ALL (ranked by edge) · {{ signals.length }}</option>
              <option value="entered">ENTER ONLY · {{ sigEntered }}</option>
              <option value="actionable">≥{{ pctFrac(ACTIONABLE_EDGE, 0) }} WATCH · {{ sigActionable }}</option>
              <option value="long">LONG</option>
              <option value="short">SHORT</option>
            </select>
          </div>
        </div>
      </template>

      <div class="table-container">
        <table v-if="filteredSignals.length" class="grid">
          <thead>
            <tr>
              <th class="label">Symbol</th>
              <th class="label">Side</th>
              <th class="label num">Edge</th>
              <th class="label num">Momentum</th>
              <th class="label num">Hz</th>
              <th class="label">Gap Event</th>
              <th class="label">State</th>
              <th class="label">Options</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in filteredSignals"
              :key="s.symbol + s.horizon"
              :class="{ 'row-high': hasHighConfidence(s.probability, s.state) }"
              @click="open(s.symbol)"
            >
              <td class="fig sym">{{ s.symbol }}</td>
              <td>
                <span class="side-pill" :class="s.side === 'LONG' || s.side === 'long' ? 'pos' : 'neg'">
                  {{ (s.side ?? DASH).toUpperCase() }}
                </span>
              </td>
              <td
                class="fig num"
                :title="edgeTitle(s.probability, s.state)"
              >
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
                        :class="hasHighConfidence(s.probability, s.state) ? 'pos' : hasActionableEdge(s.probability) ? 'mod' : 'flat'"
                        :style="{ width: `${Math.min(100, Math.max(0, (s.probability ?? 0) * 100))}%` }"
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
              <td class="fig num mom-cell" :class="tone(s.momentum)" :title="`Model momentum score ${num(s.momentum, 3)}`">
                <div class="mom-wrap">
                  <span class="mom-bar" aria-hidden="true"><i :style="{ width: `${momentumBarPct(s.momentum)}%` }" /></span>
                  <span>{{ num(s.momentum, 2) }}</span>
                </div>
              </td>
              <td class="fig num dim">{{ (s.horizon ?? '').replace(' Days', 'd') }}</td>
              <td>
                <span
                  v-if="peadFor(s.symbol)"
                  class="alignment-chip label"
                  :class="relationFor(s.symbol)"
                >
                  {{ relationFor(s.symbol) === 'agree' ? `AGREES ${sideWord(peadFor(s.symbol)?.side)}` : `CONFLICT ${sideWord(peadFor(s.symbol)?.side)}` }}
                </span>
                <span v-else class="coverage-chip label">NO GAP EVENT</span>
              </td>
              <td>
                <span class="state label" :class="s.state === 'ENTER' ? 'enter' : 'watch'">{{ s.state }}</span>
              </td>
              <td>
                <button
                  class="chain-btn label"
                  type="button"
                  title="Fetch this name's option chain and gamma structure"
                  @click.stop="openOptions(s.symbol)"
                >
                  CHAIN
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">
          {{ signals.length === 0 ? 'No directional signals emitted — run Quick or Deep scan.' : 'No directional signals match the selected filter.' }}
        </p>
      </div>
      <p class="note tiny pad confidence-footnote">
        Ranked by ENTER then calibrated probability.
        HIGH ≥ {{ pctFrac(ENTER_EDGE, 0) }} · MODERATE ≥ {{ pctFrac(ACTIONABLE_EDGE, 0) }} · below that is WEAK.
        Confidence kind must be calibrated_probability — ordinal PEAD is excluded.
      </p>
    </Panel>

    <!-- ── 04 Custom Stock Watchlist & Ad-Hoc Signal Probe ─────────────── -->
    <Panel
      label="Custom Watchlist"
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
            @keyup.enter="probeSymbol(customTickerInput)"
          />
          <button class="act label" :disabled="probing || !customTickerInput.trim()" @click="probeSymbol(customTickerInput)">
            {{ probing ? 'PROBING…' : '+ ADD' }}
          </button>
          <button class="act label" :disabled="probing" title="Force refresh all watchlist rows" @click="probeWatchlist(true)">
            REFRESH
          </button>
        </div>
      </template>

      <p v-if="probeErr" class="err pad">{{ probeErr }}</p>

      <div class="table-container">
        <table v-if="customWatchlist.length" class="grid">
          <thead>
            <tr>
              <th class="label">Symbol</th>
              <th class="label">Spark</th>
              <th class="label num">Last</th>
              <th class="label num">1D</th>
              <th class="label num">5D</th>
              <th class="label num">Edge</th>
              <th class="label num">Mom</th>
              <th class="label num">Sharpe</th>
              <th class="label">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="sym in customWatchlist" :key="sym" @click="open(sym)">
              <td class="fig sym">{{ sym }}</td>
              <td class="spark-cell">
                <svg v-if="watchSparks[sym]" viewBox="0 0 88 22" class="spark" aria-hidden="true">
                  <path :d="watchSparks[sym]" fill="none" stroke="currentColor" stroke-width="1.4" />
                </svg>
                <span v-else class="dim">—</span>
              </td>
              <td class="fig num price-cell">{{ usd(watchPrice(sym)) }}</td>
              <td class="fig num" :class="tone(probeResults[sym]?.stats?.chg_1d_pct)">
                {{ signedPct(probeResults[sym]?.stats?.chg_1d_pct) }}
              </td>
              <td class="fig num" :class="tone(probeResults[sym]?.stats?.chg_5d_pct)">
                {{ signedPct(probeResults[sym]?.stats?.chg_5d_pct) }}
              </td>
              <td
                class="fig num"
                :title="edgeTitle(signalFor(sym)?.probability, signalFor(sym)?.state)"
              >
                <template v-if="signalFor(sym)?.probability != null">
                  <span
                    :class="hasHighConfidence(signalFor(sym)?.probability, signalFor(sym)?.state)
                      ? 'pos'
                      : hasActionableEdge(signalFor(sym)?.probability) ? '' : 'dim'"
                  >
                    {{ pctFrac(signalFor(sym)!.probability, 1) }}
                    <small
                      v-if="signalFor(sym)?.state"
                      class="label"
                      :class="signalFor(sym)?.state === 'ENTER' ? 'enter' : 'watch'"
                    >{{ signalFor(sym)?.state }}</small>
                  </span>
                </template>
                <span v-else class="dim">—</span>
              </td>
              <td class="fig num" :class="tone(signalFor(sym)?.momentum ?? probeResults[sym]?.stats?.chg_5d_pct)">
                {{ signalFor(sym)?.momentum != null ? num(signalFor(sym)!.momentum, 2) : signedPct(probeResults[sym]?.stats?.chg_5d_pct) }}
              </td>
              <td class="fig num">{{ probeResults[sym]?.stats?.sharpe == null ? DASH : num(probeResults[sym]?.stats?.sharpe, 2) }}</td>
              <td>
                <button class="remove-btn label" title="Remove ticker from personal watchlist" @click.stop="removeWatchlistSymbol(sym)">
                  REMOVE
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">No custom tickers pinned yet. Type a ticker above to probe and pin.</p>
      </div>
      <p class="note tiny pad-x">
        Saved in this browser. Rows re-probe every 60s. Edge/Mom fill when the name is on the directional board; otherwise 5D return stands in for momentum.
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
}
.w-full { grid-column: 1 / -1; }
.w-half { grid-column: span 2; }

/* ---- high-confidence queue --------------------------------------------- */
.confidence-queue {
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel);
  min-width: 0;
}
.confidence-queue-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s4);
  padding: var(--s3) var(--s4);
  border-bottom: var(--hair) solid var(--rule);
}
.confidence-queue-head .label { color: var(--phosphor-dim); letter-spacing: 0.06em; }
.confidence-queue-head strong {
  display: block;
  margin-top: 2px;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: var(--t-small);
}
.queue-note { margin-top: 4px; color: var(--ink-dim); max-width: 72ch; line-height: 1.4; }
.confidence-queue-stats {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
}
.confidence-queue-stats .fig {
  font-size: 1.35rem;
  font-weight: 800;
  color: var(--phosphor);
  line-height: 1;
}
.confidence-queue-rows {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--s2);
  padding: var(--s3);
}
.hc-row {
  display: grid;
  grid-template-columns: 5ch auto 1fr auto auto;
  align-items: center;
  gap: var(--s2);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid color-mix(in srgb, var(--long) 35%, var(--rule));
  background: color-mix(in srgb, var(--long) 8%, var(--panel));
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.hc-row:hover { border-color: var(--long); background: color-mix(in srgb, var(--long) 14%, var(--panel)); }
.confidence-empty { color: var(--ink-dim); line-height: 1.45; }
.row-high td { background: color-mix(in srgb, var(--long) 6%, transparent); }
.prob-cell.high .confidence-value { color: var(--long); font-weight: 700; }

/* ---- workspace identity ------------------------------------------------- */
.arena-head {
  grid-column: 1 / -1;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s5);
  padding: var(--s2) 0 var(--s1);
  border-bottom: var(--hair) solid var(--border-subtle);
}
.arena-title { min-width: 0; }
.arena-kicker { color: var(--phosphor-dim); font-size: var(--t-micro); }
.arena-title h1 {
  margin: 3px 0 4px;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: clamp(1.45rem, 2vw, 2rem);
  letter-spacing: -0.035em;
  line-height: 1;
}
.arena-title p { max-width: 620px; color: var(--text-secondary); font-size: var(--t-small); }
.arena-context { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: var(--s2); }
.scope-chip {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 2px 7px;
  border: var(--hair) solid var(--border-strong);
  color: var(--text-secondary);
  background: var(--surface-raised);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  white-space: nowrap;
}
.scope-chip.live { color: var(--phosphor); border-color: var(--phosphor-dim); background: var(--phosphor-wash); }
.scope-chip.proxy { color: var(--warn); }
.scope-chip.held { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, var(--border-strong)); }
.arena-flow-link {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 4px 8px;
  border: var(--hair) solid var(--phosphor-dim);
  color: var(--phosphor);
  background: var(--phosphor-wash);
  font-size: var(--t-micro);
  text-decoration: none;
  white-space: nowrap;
}
.arena-flow-link:hover { color: var(--surface-canvas); background: var(--phosphor); }

/* ---- 00 Summary KPI Deck ------------------------------------------------ */
.desk-summary {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--s3);
}

.kpi-card {
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--radius-sm, 4px);
  padding: var(--s3) var(--s4);
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  overflow: hidden;
  transition: border-color var(--dur-fast), background var(--dur-fast);
}
.kpi-card:hover {
  border-color: var(--rule-hi);
  background: var(--panel-hi);
}
.kpi-card.clickable { cursor: pointer; }
button.kpi-card {
  width: 100%;
  appearance: none;
  text-align: left;
  font: inherit;
}
.kpi-card:focus-visible, .arena-flow-link:focus-visible { outline: 2px solid var(--action-focus); outline-offset: 2px; }
.kpi-card.armed { border-color: var(--long); }
.kpi-card.held { border-color: color-mix(in srgb, var(--warn) 35%, transparent); }

.kpi-label {
  font-size: 10px;
  color: var(--ink-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
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
  overflow: hidden;
}

.kpi-val {
  font-family: var(--font-mono);
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1.1;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kpi-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  text-transform: uppercase;
  flex-shrink: 0;
  white-space: nowrap;
}
.kpi-badge.armed, .kpi-badge.pos { color: var(--long); background: var(--long-wash); }
.kpi-badge.held, .kpi-badge.neg { color: var(--short); background: var(--short-wash); }
.kpi-badge.enter { color: var(--phosphor); background: var(--phosphor-wash); }
.kpi-badge.flat { color: var(--ink-dim); background: var(--rule); }

.kpi-sub { font-size: 11px; color: var(--ink-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fl-truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.strat-name { font-size: 0.95rem; min-width: 0; flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ---- Scan console -------------------------------------------------------- */
.scan-console {
  grid-column: 1 / -1;
  position: relative;
  overflow: hidden;
  border: var(--hair) solid var(--rule-hi);
  border-left: 3px solid var(--phosphor-dim);
  background:
    repeating-linear-gradient(90deg, transparent 0 79px, var(--grid) 80px),
    var(--void-lift);
}
.scan-console::before,
.scan-console::after {
  content: '';
  position: absolute;
  width: var(--tick);
  height: var(--tick);
  pointer-events: none;
}
.scan-console::before { inset: -1px auto auto -1px; border-top: 2px solid var(--phosphor); border-left: 2px solid var(--phosphor); }
.scan-console::after { inset: auto -1px -1px auto; border-right: 2px solid var(--phosphor); border-bottom: 2px solid var(--phosphor); }

.scan-console-head {
  display: grid;
  grid-template-columns: minmax(140px, 0.7fr) minmax(0, 1fr) auto;
  align-items: stretch;
  min-width: 0;
}
.scan-console-head > * { min-width: 0; }
.scan-title-block {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--s1);
  padding: var(--s4) var(--s5);
  border-right: var(--hair) solid var(--rule);
}
.scan-kicker { color: var(--phosphor-dim); font-size: var(--t-micro); }
.scan-title {
  font-family: var(--font-display);
  color: var(--ink);
  font-size: var(--t-body);
  letter-spacing: 0.02em;
}
.last-scan { color: var(--ink-ghost); font-size: 8px; }
.scan-readouts { display: grid; grid-template-columns: repeat(4, minmax(105px, 1fr)); }
.scan-readout {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  padding: var(--s3) var(--s4);
  border-right: var(--hair) solid var(--rule-faint);
}
.scan-readout > .label { color: var(--ink-dim); font-size: 9px; }
.scan-readout > .fig { color: var(--ink); font-size: var(--t-lead); font-weight: 700; }
.scan-readout > .fig i { color: var(--ink-ghost); font-size: var(--t-small); font-style: normal; }
.scan-readout > small { color: var(--ink-ghost); font-size: 9px; }

.scan-controls {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: var(--s3) var(--s4);
}
.depth-switch { display: flex; border: var(--hair) solid var(--rule-hi); }
.depth-option {
  min-width: 78px;
  padding: 7px 10px;
  color: var(--ink-dim);
  background: var(--panel);
  border-right: var(--hair) solid var(--rule-hi);
  font-size: 9px;
}
.depth-option:last-child { border-right: 0; }
.depth-option span { color: var(--ink-ghost); margin-left: var(--s1); }
.depth-option:hover:not(:disabled) { color: var(--ink); background: var(--panel-hi); }
.depth-option.on { color: var(--void); background: var(--phosphor); }
.depth-option.on span { color: rgba(8, 9, 12, 0.62); }
.scan-run {
  display: flex;
  align-items: center;
  gap: var(--s2);
  min-width: 154px;
  justify-content: center;
  padding: 8px 12px;
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  font-size: 9px;
  font-weight: 800;
}
.scan-run:hover:not(:disabled) { color: var(--void); background: var(--phosphor); }
.scan-run:disabled, .depth-option:disabled { cursor: progress; opacity: 0.68; }
.scan-pulse { width: 6px; height: 6px; background: currentColor; }
.scan-run:disabled .scan-pulse { animation: scan-blink 720ms steps(2, end) infinite; }
@keyframes scan-blink { 50% { opacity: 0.2; } }

.scan-progress {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, 0.45fr);
  align-items: center;
  gap: var(--s5);
  padding: var(--s3) var(--s5);
  border-top: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.scan-progress-copy { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: baseline; gap: var(--s3); min-width: 0; }
.scan-progress-copy > .label { color: var(--phosphor); font-size: 9px; white-space: nowrap; }
.scan-progress-copy > strong { overflow: hidden; color: var(--ink); font-size: var(--t-small); font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.scan-progress-copy > small { color: var(--ink-dim); font-size: 9px; white-space: nowrap; }
.scan-progress-track { height: 4px; overflow: hidden; border: var(--hair) solid var(--rule-hi); background: var(--void); }
.scan-progress-track > i { display: block; height: 100%; background: var(--phosphor); transition: width var(--dur-standard) ease; }

.scan-explain {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s4);
  min-height: 30px;
  padding: var(--s2) var(--s5);
  color: var(--ink-dim);
  border-top: var(--hair) solid var(--rule);
  background: rgba(8, 9, 12, 0.46);
  font-size: 9px;
}
.scan-explain .scan-msg { padding: 0; color: var(--phosphor-dim); }
.scan-flow-link {
  flex: 0 0 auto;
  min-height: 24px;
  padding: 3px 7px;
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  text-decoration: none;
}
.scan-flow-link:hover { color: var(--void); background: var(--phosphor); }
.confidence-note { color: var(--warn); text-align: right; }

/* ---- 01 Interlock -------------------------------------------------------- */
.interlock { display: flex; align-items: flex-start; gap: var(--s6); flex-wrap: wrap; }
.verdict-block { display: flex; flex-direction: column; gap: 4px; padding-right: var(--s5); }

.verdict-pill { display: flex; align-items: center; gap: var(--s3); }
.big-verdict {
  font-family: var(--font-display);
  font-size: 2.25rem;
  font-weight: 800;
  line-height: 0.95;
  letter-spacing: -0.04em;
}
.held .big-verdict { color: var(--warn); }
.armed .big-verdict { color: var(--phosphor); }

.lamp-dot { width: 10px; height: 10px; border-radius: 50%; }
.armed .lamp-dot { background: var(--phosphor); }
.held .lamp-dot { background: var(--warn); }

.vsub { color: var(--ink-dim); font-size: var(--t-small); }
.gauge-set { display: flex; gap: var(--s5); flex-wrap: wrap; }

.shadow-meter-wrap { margin: var(--s4) 0 var(--s3); }
.shadow-bar { position: relative; height: 6px; background: var(--rule); border-radius: 3px; overflow: hidden; }
.shadow-bar i {
  display: block;
  height: 100%;
  background: var(--phosphor);
  transition: width var(--dur-slow) var(--ease-out);
}

.shadow-meter-labels { display: flex; justify-content: space-between; font-size: 10px; color: var(--ink-dim); margin-top: 4px; }
.blocks-wrap { margin-top: var(--s3); border-top: var(--hair) solid var(--rule-faint); padding-top: var(--s3); }
.blocks-header { display: flex; justify-content: space-between; align-items: center; color: var(--ink-dim); font-size: var(--t-tiny); font-weight: 700; margin-bottom: var(--s2); }

.toggle-btn { background: transparent; border: none; color: var(--phosphor); font-size: var(--t-tiny); cursor: pointer; padding: 0; }
.toggle-btn:hover { text-decoration: underline; }

.blocks { list-style: none; display: flex; flex-direction: column; gap: var(--s1); }
.block {
  display: grid;
  grid-template-columns: 2.5ch 1fr;
  gap: var(--s3);
  align-items: baseline;
  padding: var(--s2) 0;
  border-bottom: var(--hair) solid var(--rule-faint);
}
.b-idx { font-size: var(--t-micro); color: var(--warn); font-weight: 700; }
.b-txt { font-size: var(--t-small); color: var(--ink); line-height: 1.4; }

/* ---- Filter Controls & Action Slot -------------------------------------- */
.action-bar { display: flex; align-items: center; gap: var(--s3); }

.select-wrap {
  position: relative;
}

.filter-select {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  color: var(--phosphor);
  font-size: 11px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 3px;
  cursor: pointer;
  outline: none;
}
.filter-select option {
  background: var(--panel);
  color: var(--ink);
}

/* ---- Probe Input Bar ----------------------------------------------------- */
.probe-input-bar {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
}

.probe-input {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink);
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 3px;
  width: 200px;
}

.remove-btn {
  background: transparent;
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 2px;
  cursor: pointer;
}
.remove-btn:hover {
  color: var(--short);
  border-color: var(--short);
}

/* ---- Scrollable Signal Tables ------------------------------------------- */
.table-container {
  max-height: 480px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.grid { width: 100%; border-collapse: collapse; font-size: var(--t-small); }
.grid th {
  text-align: left;
  padding: var(--s3) var(--s4);
  color: var(--ink-dim);
  border-bottom: var(--hair) solid var(--rule);
  position: sticky;
  top: 0;
  background: var(--panel-hi);
  font-weight: 700;
  z-index: 1;
}
.grid td { padding: var(--s2) var(--s4); border-bottom: var(--hair) solid var(--rule-faint); color: var(--ink); vertical-align: middle; }
.grid tbody tr { cursor: pointer; transition: background var(--dur-fast); }
.grid tbody tr:hover { background: var(--panel-raise); }

.num { text-align: right; }
.sym { color: var(--phosphor); font-weight: 700; }
.side-pill { display: inline-block; font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 2px; }
.side-pill.pos { color: var(--long); background: var(--long-wash); }
.side-pill.neg { color: var(--short); background: var(--short-wash); }
.side-pill.neutral { color: var(--ink-dim); background: var(--rule); }

/* ---- Live activity tape ------------------------------------------------- */
.activity-panel { border-color: color-mix(in srgb, var(--phosphor) 30%, var(--rule)); }
.activity-table { max-height: 520px; }
.activity-legend { display: flex; align-items: center; gap: var(--s2); color: var(--ink-dim); font-size: 9px; }
.activity-legend > span:last-child { color: var(--warn); border-left: var(--hair) solid var(--rule); padding-left: var(--s2); }
.live-dot { width: 6px; height: 6px; background: var(--ink-ghost); box-shadow: none; }
.live-dot.on { background: var(--phosphor); }
.rank-idx { display: inline-block; width: 3ch; margin-right: var(--s2); color: var(--ink-ghost); }
.activity-score { display: grid; grid-template-columns: 4ch 70px; justify-content: end; align-items: center; gap: 2px var(--s2); }
.activity-score > i { display: block; height: 3px; overflow: hidden; background: var(--rule); }
.activity-score > i b { display: block; height: 100%; background: var(--warn); }
.activity-score > small { grid-column: 1 / -1; text-align: right; color: var(--ink-ghost); font-size: 8px; }
.qlib-cell { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; white-space: nowrap; }
.qlib-cell > strong { color: var(--ink); }
.qlib-cell > small { color: var(--ink-ghost); font-family: var(--font-ui); font-size: 8px; letter-spacing: 0.04em; }
.flag-stack { display: flex; flex-wrap: wrap; gap: 3px; max-width: 300px; }
.flag-stack span { padding: 1px 5px; color: var(--ink-dim); background: var(--rule); font-size: 9px; font-weight: 700; letter-spacing: 0.03em; }
.flag-stack span.live { color: var(--phosphor); background: var(--phosphor-wash); }
.live-value { display: block; color: var(--phosphor); }
.flow-count, .context-edge { display: block; margin-top: 2px; color: var(--ink-dim); font-family: var(--font-ui); font-size: 9px; white-space: nowrap; }
.context-edge { color: var(--warn); }
.signal-context { display: flex; align-items: center; flex-wrap: wrap; gap: 3px; max-width: 210px; }
.context-source, .coverage-chip { padding: 1px 5px; border: var(--hair) solid var(--rule-hi); color: var(--ink-dim); background: var(--panel-raise); font-size: 8px; white-space: nowrap; }
.alignment-chip { display: inline-flex; min-height: 19px; align-items: center; padding: 1px 5px; border: var(--hair) solid var(--rule-hi); color: var(--ink-dim); white-space: nowrap; }
.alignment-chip.agree { color: var(--long); border-color: color-mix(in srgb, var(--long) 60%, var(--rule)); background: var(--long-wash); }
.alignment-chip.conflict { color: var(--short); border-color: color-mix(in srgb, var(--short) 60%, var(--rule)); background: var(--short-wash); }
.alignment-chip.pead_only, .alignment-chip.directional_only { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 55%, var(--rule)); }

/* PEAD is a session event; Directional is a 5D model. Keep that contract
   visible between the two panels so adjacent tables cannot read as two votes. */
.signal-contract { display: grid; grid-template-columns: minmax(300px, 1fr) auto; gap: var(--s3) var(--s5); padding: var(--s4); border: var(--hair) solid var(--rule-hi); border-left: 3px solid var(--warn); background: var(--panel); }
.signal-contract-copy > span { color: var(--warn); }
.signal-contract-copy > strong { display: block; margin-top: 3px; color: var(--ink); font-family: var(--font-display); font-size: var(--t-small); letter-spacing: .03em; }
.signal-contract-copy > p { max-width: 85ch; margin-top: 5px; color: var(--ink-dim); font-size: var(--t-small); line-height: 1.45; }
.reconciliation-stats { display: grid; grid-template-columns: repeat(4, minmax(72px, 1fr)); border: var(--hair) solid var(--rule); }
.reconciliation-stats > div { display: flex; flex-direction: column; justify-content: center; min-width: 78px; padding: var(--s2) var(--s3); border-right: var(--hair) solid var(--rule); }
.reconciliation-stats > div:last-child { border-right: 0; }
.reconciliation-stats span { color: var(--ink-ghost); font-size: 8px; }
.reconciliation-stats strong { margin-top: 2px; color: var(--ink); font-size: var(--t-body); }
.reconciliation-stats .agree strong { color: var(--long); }
.reconciliation-stats .conflict strong { color: var(--short); }
.conflict-strip { grid-column: 1 / -1; display: flex; align-items: center; flex-wrap: wrap; gap: var(--s2); padding-top: var(--s3); border-top: var(--hair) solid var(--rule); color: var(--short); }
.conflict-strip span { padding: 2px 6px; border: var(--hair) solid color-mix(in srgb, var(--short) 55%, var(--rule)); background: var(--short-wash); }

.prob-cell { display: flex; align-items: center; justify-content: flex-end; gap: var(--s3); }
.prob-bar-wrap { width: 48px; height: 4px; background: var(--rule); border-radius: 2px; overflow: hidden; }
.prob-bar { height: 100%; border-radius: 2px; }
.prob-bar.pos { background: var(--phosphor); }
.prob-bar.mod { background: var(--warn); }
.prob-bar.flat { background: var(--ink-dim); opacity: 0.55; }
.prob-cell.weak { opacity: 0.72; }
.confidence-value { display: flex; flex-direction: column; align-items: flex-end; line-height: 1.05; }
.confidence-value small { font-family: var(--font-ui); font-size: 8px; letter-spacing: 0.08em; }
.confidence-high { color: var(--long); }
.confidence-moderate { color: var(--warn); }
.confidence-low, .confidence-unavailable { color: var(--ink-ghost); }
.confidence-footnote { border-top: var(--hair) solid var(--rule-faint); margin-top: 0 !important; }

.mom-wrap { display: flex; align-items: center; justify-content: flex-end; gap: 6px; }
.mom-bar {
  width: 36px;
  height: 3px;
  background: var(--rule);
  overflow: hidden;
  border-radius: 1px;
}
.mom-bar i { display: block; height: 100%; background: currentColor; opacity: 0.85; }
.spark-cell { width: 96px; color: var(--phosphor-dim); }
.spark { width: 88px; height: 22px; display: block; }
.spark path { vector-effect: non-scaling-stroke; }

.dim { color: var(--ink-dim); }
.pos { color: var(--long); }
.neg { color: var(--short); }
.state { padding: 2px 7px; border: var(--hair) solid currentColor; border-radius: 2px; font-weight: 600; }
.state.enter { color: var(--phosphor); background: var(--phosphor-wash); }
.state.watch { color: var(--ink-dim); border-color: var(--rule-hi); }

/* Routes a flagged name into the options engine — the chain fetch the scan
   itself never performs. Quiet by default so it reads as an action, not a
   signal. */
.chain-btn {
  padding: 2px 7px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: 2px;
  background: transparent;
  color: var(--ink-faint);
  cursor: pointer;
}

.chain-btn:hover,
.chain-btn:focus-visible {
  color: var(--call-hi);
  border-color: var(--call);
}

.act {
  padding: 3px 10px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink);
  font-weight: 600;
}
.act:hover:not(:disabled) { color: var(--phosphor); border-color: var(--phosphor); background: var(--phosphor-wash); }
.act:disabled { color: var(--ink-dim); cursor: progress; }

.scan-msg { padding: var(--s2) var(--s4); color: var(--phosphor-dim); }
.note { color: var(--ink-dim); font-size: var(--t-small); }
.note.pad { padding: var(--s5) var(--s4); }
.note.pad-x { padding: var(--s3) var(--s4) var(--s4); }
.note.tiny { font-size: 11px; margin-top: var(--s3); }
.err { color: var(--short); font-size: var(--t-small); }
.err.pad { padding: var(--s3) var(--s4); }

@media (max-width: 1400px) {
  .desk-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .desk { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .scan-console-head { grid-template-columns: 180px 1fr; }
  .scan-controls { grid-column: 1 / -1; border-top: var(--hair) solid var(--rule); justify-content: flex-end; }
}
@media (max-width: 768px) {
  .arena-head { align-items: flex-start; flex-direction: column; gap: var(--s3); padding-bottom: var(--s3); }
  .arena-context { justify-content: flex-start; }
  .arena-flow-link { min-height: 44px; }
  .desk-summary { grid-template-columns: 1fr; }
  .desk { grid-template-columns: 1fr; }
  .w-half { grid-column: span 1; }
  .action-bar { flex-direction: column; align-items: flex-start; }
  .scan-console-head { display: flex; flex-direction: column; }
  .scan-title-block { border-right: 0; border-bottom: var(--hair) solid var(--rule); }
  .scan-readouts { grid-template-columns: repeat(2, 1fr); }
  .scan-controls { flex-wrap: wrap; justify-content: stretch; }
  .depth-switch, .scan-run { flex: 1 1 100%; }
  .depth-option { flex: 1; }
  .scan-progress { grid-template-columns: 1fr; gap: var(--s3); }
  .scan-progress-copy { grid-template-columns: 1fr auto; }
  .scan-progress-copy > strong { grid-column: 1 / -1; grid-row: 2; white-space: normal; }
  .scan-explain { align-items: flex-start; flex-direction: column; }
  .signal-contract { grid-template-columns: 1fr; }
  .reconciliation-stats { grid-template-columns: repeat(2, 1fr); }
  .reconciliation-stats > div:nth-child(2) { border-right: 0; }
  .reconciliation-stats > div:nth-child(-n + 2) { border-bottom: var(--hair) solid var(--rule); }
  .confidence-note { text-align: left; }
}
</style>
