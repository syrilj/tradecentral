<script setup lang="ts">
import { computed, inject, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  api,
  type ActivityFlagRow,
  type StatusPayload,
  type Readiness,
  type ScanDepth,
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

// Filtering state for dropdowns
const peadFilter = ref<'all' | 'entered' | 'long' | 'short'>('all')
const signalFilter = ref<'all' | 'entered' | 'long' | 'short'>('all')

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
  // Keep personal watchlist fresh even when the shared status asof is quiet.
  watchlistTimer = window.setInterval(() => void probeWatchlist(true), 60_000)
})

onUnmounted(() => {
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
    const t = await api.trajectory(clean, '1m')
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
  for (const sym of customWatchlist.value) {
    try {
      if (force || !probeResults.value[sym]) {
        probeResults.value[sym] = await api.trajectory(sym, '1m')
      }
    } catch {
      /* ignore individual ticker probe error; retry on next refresh */
    }
  }
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

async function runScan(): Promise<void> {
  scanning.value = true
  scanMsg.value = null
  try {
    const result = await api.triggerScan(scanDepth.value)
    status.data.value = result.data
    status.error.value = null
    status.fetchedAt.value = new Date().toISOString()
    scanMsg.value = result.message
  } catch (e) {
    scanMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    scanning.value = false
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

watch(
  () => scan.value?.depth,
  (depth) => {
    if (depth === 'quick' || depth === 'deep') scanDepth.value = depth
  },
  { immediate: true },
)

/* Filtering computed properties */
const peadEntered = computed(() => pead.value.filter((p) => p.model?.state === 'ENTER').length)
const sigEntered = computed(() => signals.value.filter((s) => s.state === 'ENTER').length)
const liveActivityCount = computed(() => activity.value.filter((row) => row.live).length)
const peadMeta = computed(() => {
  const summary = scan.value
  return summary
    ? `${pead.value.length} ordinal flags / ${summary.pead_attempted_symbols} examined · gate ${summary.pead_gate_verdict}`
    : `${pead.value.length} ordinal flags · no calibrated probability`
})
const signalMeta = computed(() => {
  const summary = scan.value
  return summary
    ? `${sigEntered.value} entered · ${summary.directional_scored_symbols} scored / ${summary.directional_model_universe_symbols} modeled`
    : `${sigEntered.value} entered · ${signals.value.length} scored`
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
  if (coverage.live_completed >= coverage.live_requested) return 'LSE PASS COMPLETE'
  return `LSE PARTIAL ${coverage.live_completed}/${coverage.live_requested}`
})
const selectedScanLabel = computed(() =>
  scanDepth.value === 'deep'
    ? `${scan.value?.activity_market_universe_symbols ?? d.value?.searchable_symbol_count ?? 576} + ${scan.value?.activity_live_requested_symbols || 100} LIVE`
    : `${Math.min(scan.value?.activity_market_universe_symbols ?? 175, 175)} LOCAL`,
)

function confidenceBand(value: number | null | undefined): 'HIGH' | 'MODERATE' | 'LOW' | 'UNAVAILABLE' {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'UNAVAILABLE'
  if (value >= 0.65) return 'HIGH'
  if (value >= 0.55) return 'MODERATE'
  return 'LOW'
}

/** True edge for authorization chrome; weak probs still render dim for context. */
function hasActionableEdge(value: number | null | undefined): boolean {
  if (value === null || value === undefined || !Number.isFinite(value)) return false
  return value >= 0.55
}

function edgeTitle(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return 'No calibrated probability — use momentum + state only.'
  }
  if (!hasActionableEdge(value)) {
    return `${pctFrac(value, 1)} calibrated — near coin-flip; not authorization edge`
  }
  return `${confidenceBand(value)} calibrated edge`
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
  return pead.value.filter((p) => {
    if (peadFilter.value === 'entered') return p.model?.state === 'ENTER'
    if (peadFilter.value === 'long') return p.side?.toLowerCase() === 'long'
    if (peadFilter.value === 'short') return p.side?.toLowerCase() === 'short'
    return true
  })
})

const filteredSignals = computed(() => {
  return signals.value.filter((s) => {
    if (signalFilter.value === 'entered') return s.state === 'ENTER'
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

      <div class="kpi-card">
        <span class="label kpi-label">Authorized Entries</span>
        <div class="kpi-val-row">
          <span class="kpi-val fig pos">{{ sigEntered }}</span>
          <span class="kpi-badge enter">ENTER SIGNAL</span>
        </div>
        <span class="kpi-sub">
          PEAD excluded · {{ sigEntered }} calibrated directional
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

      <div class="kpi-card clickable" @click="navTo('sectors')">
        <span class="label kpi-label">Top Sector Flow ➔</span>
        <div class="kpi-val-row">
          <span class="kpi-val sym">{{ topSector ? topSector.etf : '—' }}</span>
          <span class="kpi-badge" :class="tone(topSector?.flow_score ?? 0)">
            {{ topSector ? signedPct(topSector.flow_score * 100, 1) : '—' }}
          </span>
        </div>
        <span class="kpi-sub fl-truncate">
          {{ topSector ? topSector.name : 'Sectors tab' }}
        </span>
      </div>

      <div class="kpi-card clickable" @click="navTo('gates')">
        <span class="label kpi-label">Top Alpha Strategy ➔</span>
        <div class="kpi-val-row">
          <span class="kpi-val strat-name">{{ topStrategy ? topStrategy.strategy : '—' }}</span>
          <VerdictChip v-if="topStrategy" :verdict="topStrategy.verdict" size="sm" />
        </div>
        <span class="kpi-sub">
          Net {{ topStrategy?.net_return ?? '—' }} · Sharpe {{ topStrategy?.sharpe ?? '—' }}
        </span>
      </div>
    </div>

    <section class="scan-console" aria-label="Market scan depth">
      <div class="scan-console-head">
        <div class="scan-title-block">
          <span class="label scan-kicker">Scan scope</span>
          <strong class="scan-title">
            {{ scan?.depth === 'deep' ? 'MARKET-WIDE + LIVE FLOW' : 'FAST LOCAL ACTIVITY' }}
          </strong>
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
              QUICK <span>25</span>
            </button>
            <button
              class="depth-option label"
              :class="{ on: scanDepth === 'deep' }"
              :aria-pressed="scanDepth === 'deep'"
              :disabled="scanning"
              @click="scanDepth = 'deep'"
            >
              DEEP <span>{{ scan?.activity_market_universe_symbols ?? d?.searchable_symbol_count ?? 576 }}</span>
            </button>
          </div>
          <button class="scan-run label" :disabled="scanning" @click="runScan">
            <span class="scan-pulse" aria-hidden="true" />
            {{ scanning ? `SCANNING ${selectedScanLabel}…` : `RUN ${scanDepth.toUpperCase()} SCAN` }}
          </button>
        </div>
      </div>
      <div class="scan-explain">
        <span v-if="scanMsg" class="scan-msg label">{{ scanMsg }}</span>
        <span v-else class="label">
          Quick ranks 175 local names. Deep ranks the full {{ scan?.activity_market_universe_symbols ?? d?.searchable_symbol_count ?? 576 }}-name catalog,
          checks the top 100 against live LSE flow, and keeps confidence separate.
        </span>
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
                <template v-if="row.qlib_rank != null">
                  <strong>#{{ row.qlib_rank }}</strong>
                  <small class="dim">{{ row.qlib_score != null ? num(row.qlib_score, 2) : DASH }} · research</small>
                </template>
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
                <span v-else class="dim">NO PRINTS</span>
              </td>
              <td class="fig num">
                <span :class="tone((row.ret_1d ?? 0) * 100)">{{ signedPct((row.ret_1d ?? 0) * 100, 1) }}</span>
                <small class="flow-count">{{ row.volume_vs_20d_median == null ? DASH : `${num(row.volume_vs_20d_median, 1)}× vol` }}</small>
              </td>
              <td>
                <span class="side-pill" :class="row.context_side === 'long' ? 'pos' : row.context_side === 'short' ? 'neg' : 'neutral'">
                  {{ row.context_side.toUpperCase() }}
                </span>
                <small v-if="row.calibrated_probability != null && hasActionableEdge(row.calibrated_probability)" class="context-edge">
                  model {{ pctFrac(row.calibrated_probability, 1) }}
                </small>
                <small v-else class="context-edge dim">not authorized</small>
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
              <option value="entered">AUTHORIZED ONLY ({{ peadEntered }})</option>
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
      <p class="note tiny pad confidence-footnote">PEAD gate is NO-GO. Strength is ordinal and cannot authorize an entry or be read as confidence.</p>
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
              <option value="all">ALL SIGNALS ({{ signals.length }})</option>
              <option value="entered">ENTER ONLY ({{ sigEntered }})</option>
              <option value="long">LONG SIGNALS</option>
              <option value="short">SHORT SIGNALS</option>
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
              <th class="label">State</th>
              <th class="label">Options</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(s, i) in filteredSignals" :key="i" @click="open(s.symbol)">
              <td class="fig sym">{{ s.symbol }}</td>
              <td>
                <span class="side-pill" :class="s.side === 'LONG' || s.side === 'long' ? 'pos' : 'neg'">
                  {{ (s.side ?? DASH).toUpperCase() }}
                </span>
              </td>
              <td
                class="fig num"
                :title="edgeTitle(s.probability)"
              >
                <template v-if="s.probability != null && Number.isFinite(s.probability)">
                  <div class="prob-cell" :class="{ weak: !hasActionableEdge(s.probability) }">
                    <div class="prob-bar-wrap" aria-hidden="true">
                      <div
                        class="prob-bar"
                        :class="s.state === 'ENTER' ? 'pos' : hasActionableEdge(s.probability) ? 'mod' : 'flat'"
                        :style="{ width: `${Math.min(100, Math.max(0, (s.probability ?? 0) * 100))}%` }"
                      />
                    </div>
                    <span class="confidence-value">
                      {{ pctFrac(s.probability, 1) }}
                      <small :class="`confidence-${confidenceBand(s.probability).toLowerCase()}`">
                        {{ hasActionableEdge(s.probability) ? confidenceBand(s.probability) : 'WEAK' }}
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
          {{ signals.length === 0 ? 'No directional signals emitted.' : 'No directional signals match the selected filter.' }}
        </p>
      </div>
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
              <td class="fig num" :title="edgeTitle(signalFor(sym)?.probability)">
                <template v-if="signalFor(sym)?.probability != null">
                  <span :class="hasActionableEdge(signalFor(sym)?.probability) ? 'pos' : 'dim'">
                    {{ pctFrac(signalFor(sym)!.probability, 1) }}
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
.kpi-card.armed { border-color: rgba(34, 197, 94, 0.3); }
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
.kpi-badge.armed, .kpi-badge.pos { color: var(--long); background: rgba(34, 197, 94, 0.12); }
.kpi-badge.held, .kpi-badge.neg { color: var(--short); background: rgba(239, 68, 68, 0.12); }
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
  background:
    linear-gradient(90deg, var(--phosphor-wash), transparent 24%),
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
.side-pill.pos { color: var(--long); background: rgba(34, 197, 94, 0.12); }
.side-pill.neg { color: var(--short); background: rgba(239, 68, 68, 0.12); }
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
.flag-stack { display: flex; flex-wrap: wrap; gap: 3px; max-width: 300px; }
.flag-stack span { padding: 1px 5px; color: var(--ink-dim); background: var(--rule); font-size: 9px; font-weight: 700; letter-spacing: 0.03em; }
.flag-stack span.live { color: var(--phosphor); background: var(--phosphor-wash); }
.live-value { display: block; color: var(--phosphor); }
.flow-count, .context-edge { display: block; margin-top: 2px; color: var(--ink-dim); font-family: var(--font-ui); font-size: 9px; white-space: nowrap; }
.context-edge { color: var(--warn); }

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
  .scan-explain { align-items: flex-start; flex-direction: column; }
  .confidence-note { text-align: left; }
}
</style>
