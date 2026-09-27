<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type MarketClock, type PlaysDecision, type PlaysJob, type PlaysPayload } from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import LoadingState from '@/components/LoadingState.vue'
import { DASH, age, num, pctFrac, shortDate, signedPct, usd } from '@/format'

/**
 * Plays of the day.
 *
 * This is the operator surface for the daily-plays decision funnel: market
 * map -> routed targets -> model domain -> directional setups -> live
 * option-chain validation -> ENTER/WATCH/ABSTAIN. When the calibrated-model
 * path produces no actionable ticket, the pullback technical-screen engine
 * contributes its own policy-gated, honestly-labelled tickets so the desk
 * has real candidates with exact contracts. Every ticket carries its setup
 * evidence (chart structure + options flow) and quote provenance. Decision
 * support only; never places or routes an order.
 */

const router = useRouter()
const sharedMarketClock = inject<Resource<MarketClock> | null>('marketClock', null)

/** Poll cadence while the tab is visible: fresh enough for intraday use. */
const REFRESH_INTERVAL_MS = 60_000

const accountInput = ref('10000')
const running = ref(false)
const runMsg = ref<string | null>(null)
const runJob = ref<PlaysJob | null>(null)
let pollToken = 0

const feed = useResource<PlaysPayload>(() => api.plays(), { intervalMs: REFRESH_INTERVAL_MS })

const payload = computed(() => feed.data.value)
const available = computed(() => payload.value?.available === true)
const emptyReason = computed(
  () => payload.value?.reason || 'No daily plays run has been persisted yet.',
)

const plays = computed<PlaysDecision[]>(() => (payload.value?.plays ?? []) as PlaysDecision[])
const watchlist = computed<PlaysDecision[]>(
  () => (payload.value?.watchlist ?? []) as PlaysDecision[],
)
const rejections = computed<PlaysDecision[]>(
  () => (payload.value?.rejections ?? []) as PlaysDecision[],
)
const researchBoard = computed(() => payload.value?.research_board ?? [])
const blockers = computed(() => payload.value?.decision_blockers ?? [])
const warnings = computed(() => payload.value?.warnings ?? [])
const advisoryWarnings = computed(() => payload.value?.advisory_evidence_warnings ?? [])
const executionWarnings = computed(() => payload.value?.execution_health_warnings ?? [])

const marketMap = computed(() => payload.value?.market_map ?? {})
const moneyIn = computed(() => (marketMap.value.money_in ?? []) as Array<Record<string, unknown>>)
const moneyOut = computed(() => (marketMap.value.money_out ?? []) as Array<Record<string, unknown>>)
const rotation = computed(() => (marketMap.value.rotation ?? {}) as Record<string, unknown>)
const scanScope = computed(() => payload.value?.scan_scope ?? null)
const flowCoverage = computed(() => {
  const cov = (payload.value?.flow_activity ?? {}) as Record<string, unknown>
  return (cov.coverage ?? {}) as Record<string, unknown>
})

const marketSession = computed(() => sharedMarketClock?.data.value?.market_session ?? null)
const planningMode = computed(() =>
  Boolean(marketSession.value && marketSession.value !== 'regular'),
)

const statusLabel = computed(() => {
  if (!available.value) return 'NO RUN'
  return payload.value?.status === 'COMPLETE' ? 'PLAYS FOUND' : 'NO PLAY'
})

const statusTone = computed(() => {
  if (!available.value) return 'flat'
  return payload.value?.status === 'COMPLETE' ? 'pos' : 'warn'
})

const modeLabel = computed(() => String(payload.value?.mode ?? DASH).toUpperCase())
const sessionLabel = computed(() => String(payload.value?.market_session ?? DASH).toUpperCase())

const funnel = computed(() => {
  const s = scanScope.value
  if (!s) return []
  return [
    { label: 'Sector books', value: s.sector_books_scored, sub: 'scored' },
    { label: 'Routed targets', value: s.targeted_count, sub: 'flow targets' },
    { label: 'Model domain', value: s.model_domain_supported, sub: 'supported symbols' },
    { label: 'Scanned', value: s.successfully_scanned_candidates, sub: 'candidates' },
    {
      label: 'Directional',
      value: s.directional_setups,
      sub:
        sleeveCounts.value.bounce || sleeveCounts.value.breakdown
          ? `${sleeveCounts.value.bounce} bounce · ${sleeveCounts.value.breakdown} brk`
          : 'setups',
    },
    { label: 'Chains', value: s.chain_requests, sub: 'requested' },
    { label: 'Snapshots', value: s.chain_snapshots, sub: 'validated' },
  ]
})

const flowMeta = computed(() => {
  const requested = Number(flowCoverage.value.requested ?? 0)
  const observed = Number(flowCoverage.value.with_activity ?? 0)
  if (!requested) return 'No live flow requested'
  return `${observed}/${requested} names with prints · unsigned tape`
})

function accountValue(): number {
  const parsed = Number(accountInput.value)
  if (!Number.isFinite(parsed) || parsed <= 0) return 10_000
  return Math.max(100, Math.min(100_000_000, parsed))
}

function scanDelay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function trackRunJob(initial: PlaysJob, token: number): Promise<void> {
  let current = initial
  runJob.value = current
  while (token === pollToken && (current.state === 'queued' || current.state === 'running')) {
    await scanDelay(750)
    if (token !== pollToken) return
    const payloadJob = await api.playsStatus(current.id)
    if (!payloadJob.job) throw new Error(payloadJob.message)
    current = payloadJob.job
    runJob.value = current
    runMsg.value = current.message
  }
  if (token !== pollToken) return
  if (current.state === 'completed') {
    runMsg.value = current.message
    await feed.refresh()
  } else if (current.state === 'failed') {
    runMsg.value = current.error || current.message
  }
}

async function runPlays(): Promise<void> {
  const token = ++pollToken
  running.value = true
  runMsg.value = null
  try {
    const payloadJob = await api.playsRun(accountValue())
    if (!payloadJob.job) throw new Error(payloadJob.message)
    runMsg.value = payloadJob.message
    await trackRunJob(payloadJob.job, token)
  } catch (e) {
    runMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (token === pollToken) running.value = false
  }
}

async function refreshLatest(): Promise<void> {
  await feed.refresh()
}

onMounted(() => {
  void feed.refresh()
})

onUnmounted(() => {
  pollToken += 1
})

/* ---- display helpers ---------------------------------------------------- */

function sideWord(value: string | null | undefined): string {
  const side = String(value || '').toLowerCase()
  return side === 'long' ? 'LONG' : side === 'short' ? 'SHORT' : 'NEUTRAL'
}

function sideClass(value: string | null | undefined): string {
  const side = String(value || '').toLowerCase()
  return side === 'long' ? 'pos' : side === 'short' ? 'neg' : 'flat'
}

function confidenceKind(decision: PlaysDecision): string {
  return String(decision.confidence?.confidence_kind ?? 'unavailable').replaceAll('_', ' ')
}

function maxLossLabel(decision: PlaysDecision): string {
  const loss = decision.risk?.max_loss_dollars
  if (loss == null || !Number.isFinite(loss)) return DASH
  return usd(loss, 0)
}

function legLabel(decision: PlaysDecision): string {
  if (!decision.legs?.length) return 'No validated legs'
  return decision.legs
    .map((leg) => `${leg.side.toUpperCase()} ${leg.occ_symbol} @ ≤ ${usd(leg.ask, 2)}`)
    .join(' · ')
}

function reasonList(decision: PlaysDecision): string[] {
  const reasons = decision.confidence?.reasons ?? []
  const failed = decision.confidence?.failed_checks ?? []
  return [...reasons, ...failed].filter((item, index, all) => all.indexOf(item) === index)
}

function openSymbol(symbol: string | undefined): void {
  if (symbol) void router.push({ name: 'market', query: { symbol } })
}

function openOptions(symbol: string | undefined): void {
  if (symbol) void router.push({ name: 'options', query: { symbol } })
}

function rotationLabel(): string {
  const kind = String(rotation.value.kind ?? '')
    .replaceAll('_', ' ')
    .toUpperCase()
  if (!kind) return 'NO DEFINITIVE ROTATION'
  const confidence = rotation.value.confidence
  const conf =
    confidence != null && Number.isFinite(Number(confidence))
      ? ` · ${pctFrac(Number(confidence), 0)}`
      : ''
  return `${kind}${conf}`
}

function mapRowTone(row: Record<string, unknown>): 'pos' | 'neg' | 'flat' {
  const direction = String(row.direction ?? row.flow_direction ?? '')
  if (direction === 'in') return 'pos'
  if (direction === 'out') return 'neg'
  return 'flat'
}

function mapRowScore(row: Record<string, unknown>): string {
  const score = row.flow_score ?? row.rs_1d
  if (score == null || !Number.isFinite(Number(score))) return DASH
  return signedPct(Number(score) * 100, 1)
}

function researchSide(row: Record<string, unknown>): string {
  return sideWord(String(row.side ?? ''))
}

function researchProbability(row: Record<string, unknown>): string {
  const value = row.directional_confidence ?? row.development_calibrated_probability_up
  if (value == null || !Number.isFinite(Number(value))) return DASH
  return pctFrac(Number(value), 1)
}

function researchHorizon(row: Record<string, unknown>): string {
  const horizon = Number(row.horizon_days)
  return Number.isFinite(horizon) && horizon > 0 ? `H${horizon}` : DASH
}

/* ---- scanner-evidence helpers (pullback engine runs) -------------------- */

const isEngineRun = computed(() => payload.value?.engine === 'pullback_flow_engine')

const sleeveCounts = computed(() => {
  const s = scanScope.value
  return {
    bounce: Number(s?.bounce_setups ?? 0),
    breakdown: Number(s?.breakdown_setups ?? 0),
  }
})

interface PlayEvidence {
  setupKind: string
  pullback: number | null
  rsi: number | null
  pcrVolume: number | null
  callWall: number | null
  putWall: number | null
  maxPain: number | null
  target1: number | null
  supportStop: number | null
  targetExpiry: string | null
  atmIv: number | null
}

function evidenceOf(play: PlaysDecision): PlayEvidence {
  const ev = play.evidence ?? {}
  const read = (key: string): number | null => {
    const v = ev[key]
    return typeof v === 'number' && Number.isFinite(v) ? v : null
  }
  return {
    setupKind: String(ev.setup_kind ?? '—'),
    pullback: read('pullback_20d_pct'),
    rsi: read('rsi_14'),
    pcrVolume: read('pcr_volume'),
    callWall: read('call_wall'),
    putWall: read('put_wall'),
    maxPain: read('max_pain'),
    target1: read('target_1'),
    supportStop: read('support_stop'),
    targetExpiry: typeof ev.target_expiry === 'string' ? ev.target_expiry : null,
    atmIv: read('atm_iv'),
  }
}

function strategyLabel(strategy: string): string {
  if (strategy === 'long_call') return 'LONG CALL · BOUNCE'
  if (strategy === 'long_put') return 'LONG PUT · BREAKDOWN'
  return strategy.replaceAll('_', ' ').toUpperCase()
}

function legGreeksLabel(play: PlaysDecision): string {
  const leg = play.legs[0]
  if (!leg) return DASH
  const parts: string[] = []
  if (leg.delta != null) parts.push(`Δ ${num(leg.delta, 2)}`)
  if (leg.theta != null) parts.push(`θ ${num(leg.theta, 2)}/d`)
  if (leg.charm != null) parts.push(`charm ${leg.charm.toFixed(4)}/d`)
  return parts.length ? parts.join(' · ') : DASH
}

function legQuoteAgeLabel(play: PlaysDecision): string {
  const leg = play.legs[0]
  if (!leg?.quote_asof_utc) return 'no capture stamp'
  return `${age(leg.quote_asof_utc)} old`
}

function chainFreshnessLabel(play: PlaysDecision): string {
  const f = play.freshness ?? {}
  const chainDate = typeof f.chain_date === 'string' ? f.chain_date.replace('date=', '') : null
  if (!chainDate) return 'no chain'
  const stale = f.chain_snapshot_stale === true
  return stale ? `chain ${shortDate(chainDate)} · STALE` : `chain ${shortDate(chainDate)}`
}

/** True when the run's tickets came from the technical-screen engine. */
function isEngineTicket(play: PlaysDecision): boolean {
  const p = play.provenance ?? {}
  return String(p.engine ?? '').includes('Pullback')
}
</script>

<template>
  <div class="plays-view">
    <header class="page-head ticked rise">
      <div class="title-block">
        <span class="label eyebrow">Daily decision-support funnel</span>
        <h1>Plays of the Day</h1>
        <p>
          The full pipeline: sector rotation routes the scan, the frozen model domain scores
          directional setups, and live option-chain validation gates every ticket. When the
          calibrated-model path has no actionable ticket, the technical-screen engine contributes
          chart-plus-flow candidates with exact contracts from the latest chain snapshots. Every
          ticket shows its evidence, quote age, and failure reasons. Fail-closed: a NO PLAY result
          is the honest outcome, not an empty screen.
        </p>
      </div>
      <div class="scope-stack">
        <span class="scope-chip label" :class="{ planning: planningMode }">
          {{ planningMode ? 'MARKET CLOSED · PLANNING' : 'LIVE ENTRY MONITOR' }}
        </span>
        <span class="scope-chip label">SHADOW ONLY · NO ORDERS</span>
        <span class="scope-chip label" :class="{ live: available }">
          {{ available ? `RUN ${payload?.run_id?.slice(0, 15)}` : 'NO RUN PERSISTED' }}
        </span>
        <span v-if="isEngineRun" class="scope-chip engine label">
          ENGINE · {{ String(payload?.engine ?? '').toUpperCase() }} v{{
            payload?.engine_version ?? '?'
          }}
          · 60s AUTO-REFRESH
        </span>
      </div>
    </header>

    <!-- ── Run console ─────────────────────────────────────────────────── -->
    <section class="run-console ticked w-full" aria-label="Daily plays run controls">
      <div class="run-console-head">
        <div class="run-title-block">
          <span class="label run-kicker">Run Operations</span>
          <strong class="run-title">Daily Plays Pipeline</strong>
          <span class="label last-run">
            LAST RUN · {{ available ? `${sessionLabel} · ${modeLabel}` : 'NONE' }}
          </span>
        </div>
        <div class="run-controls">
          <label class="account-field label">
            <span>ACCOUNT</span>
            <input
              v-model="accountInput"
              type="number"
              min="100"
              max="100000000"
              step="1000"
              class="account-input"
              aria-label="Account value in dollars"
            />
          </label>
          <button class="run-btn label" :disabled="running" @click="runPlays">
            <span class="run-pulse" aria-hidden="true" />
            {{
              running
                ? `${runJob?.progress ?? 0}% · ${runJob?.stage?.replaceAll('_', ' ').toUpperCase() ?? 'RUNNING'}`
                : 'RUN PLAYS'
            }}
          </button>
          <button class="refresh-btn label" :disabled="feed.loading.value" @click="refreshLatest">
            {{ feed.loading.value ? 'LOADING…' : 'REFRESH LATEST' }}
          </button>
        </div>
      </div>
      <div v-if="running && runJob" class="run-progress" role="status" aria-live="polite">
        <div class="run-progress-copy">
          <span class="label">{{ runJob.stage.replaceAll('_', ' ').toUpperCase() }}</span>
          <strong>{{ runJob.message }}</strong>
          <small class="fig"
            >{{ num(runJob.elapsed_seconds, 1) }}s elapsed · the desk remains available</small
          >
        </div>
        <div
          class="run-progress-track"
          role="progressbar"
          aria-label="Plays run completion"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-valuenow="runJob.progress"
        >
          <i :style="{ width: `${runJob.progress}%` }" />
        </div>
      </div>
      <div class="run-explain" aria-live="polite">
        <span v-if="runMsg && !running" class="run-msg label">{{ runMsg }}</span>
        <span v-else-if="!running" class="label">
          Runs the full pipeline live (sector flow, model domain, option-chain validation) as a
          background job. It never places or routes an order.
        </span>
        <span v-else class="label"
          >The run is executing in the background; leaving this view will not cancel it.</span
        >
      </div>
    </section>

    <LoadingState v-if="feed.loading.value && !payload" label="Loading latest daily plays run…" />
    <p v-else-if="feed.error.value" class="state err label">{{ feed.error.value }}</p>

    <template v-else-if="available">
      <!-- ── Summary KPI deck ───────────────────────────────────────────── -->
      <section class="summary-deck" aria-label="Daily plays summary">
        <div class="kpi-card ticked" :class="statusTone">
          <span class="label kpi-label">Run status</span>
          <span class="kpi-val fig">{{ statusLabel }}</span>
          <span class="kpi-sub"
            >{{ sessionLabel }} · {{ modeLabel }} · asof {{ shortDate(payload?.asof_utc) }}</span
          >
        </div>
        <div class="kpi-card ticked" :class="plays.length ? 'pos' : 'flat'">
          <span class="label kpi-label">Actionable tickets</span>
          <span class="kpi-val fig">{{ plays.length }}</span>
          <span class="kpi-sub">ENTER only · exact contract + quote</span>
        </div>
        <div class="kpi-card ticked">
          <span class="label kpi-label">Watchlist</span>
          <span class="kpi-val fig">{{ watchlist.length }}</span>
          <span class="kpi-sub">plausible setup · not execution-valid</span>
        </div>
        <div class="kpi-card ticked">
          <span class="label kpi-label">Rejections</span>
          <span class="kpi-val fig">{{ rejections.length }}</span>
          <span class="kpi-sub">failed a model, quote, or risk gate</span>
        </div>
        <div class="kpi-card ticked">
          <span class="label kpi-label">Research board</span>
          <span class="kpi-val fig">{{ researchBoard.length }}</span>
          <span class="kpi-sub">sealed holdout · not plays</span>
        </div>
      </section>

      <!-- ── Market map ────────────────────────────────────────────────── -->
      <Panel
        label="Market Map"
        index="01"
        :meta="`${rotationLabel()} · ${String(marketMap.source ?? 'source unavailable')}`"
        class="w-full"
      >
        <div class="map-grid">
          <div class="map-col">
            <span class="label map-head pos">MONEY IN</span>
            <div v-if="moneyIn.length" class="map-rows">
              <div v-for="row in moneyIn.slice(0, 6)" :key="String(row.etf)" class="map-row">
                <span class="fig sym">{{ row.etf }}</span>
                <span class="label name">{{ row.name }}</span>
                <span class="fig score" :class="mapRowTone(row)">{{ mapRowScore(row) }}</span>
                <span v-if="row.definitive" class="definitive label">DEFINITIVE</span>
              </div>
            </div>
            <p v-else class="note">No inflow books measured.</p>
          </div>
          <div class="map-col">
            <span class="label map-head neg">MONEY OUT</span>
            <div v-if="moneyOut.length" class="map-rows">
              <div v-for="row in moneyOut.slice(0, 6)" :key="String(row.etf)" class="map-row">
                <span class="fig sym">{{ row.etf }}</span>
                <span class="label name">{{ row.name }}</span>
                <span class="fig score" :class="mapRowTone(row)">{{ mapRowScore(row) }}</span>
                <span v-if="row.definitive" class="definitive label">DEFINITIVE</span>
              </div>
            </div>
            <p v-else class="note">No outflow books measured.</p>
          </div>
        </div>
        <p class="note tiny pad">
          Relative strength is a proxy for money flow, not dark-pool or institutional order-flow
          data. Rotation routes the scan; it never manufactures a probability or bypasses an
          execution gate.
        </p>
      </Panel>

      <!-- ── Scan funnel ───────────────────────────────────────────────── -->
      <Panel label="Scan Funnel" index="02" :meta="flowMeta" class="w-full">
        <div class="funnel">
          <div v-for="(step, i) in funnel" :key="step.label" class="funnel-step">
            <span class="funnel-idx fig">{{ String(i + 1).padStart(2, '0') }}</span>
            <span class="label funnel-label">{{ step.label }}</span>
            <span class="fig funnel-value">{{
              step.value == null ? DASH : num(step.value, 0)
            }}</span>
            <span class="label funnel-sub">{{ step.sub }}</span>
          </div>
        </div>
        <p class="note tiny pad">
          Chain request/snapshot counts are not recoverable from the persisted ledger and stay
          unmeasured. The funnel distinguishes "no setup" from "setup found but no executable
          quote".
        </p>
      </Panel>

      <!-- ── Actionable plays ──────────────────────────────────────────── -->
      <Panel
        label="Validated Actionable Plays"
        index="03"
        :meta="`${plays.length} ENTER ticket(s)`"
        :live="plays.length > 0"
        class="w-full"
      >
        <div v-if="plays.length" class="plays-list">
          <article v-for="play in plays" :key="play.play_id" class="play-card">
            <div class="play-head">
              <span class="fig sym-lg">{{ play.symbol }}</span>
              <span class="side-pill" :class="sideClass(play.side)">{{ sideWord(play.side) }}</span>
              <span class="strategy label">{{ strategyLabel(play.strategy) }}</span>
              <span class="state label enter">ENTER</span>
              <span class="rank label">RANK {{ play.rank }}</span>
            </div>
            <div class="play-readouts">
              <Readout
                label="Contract"
                :value="play.legs[0]?.occ_symbol ?? DASH"
                :sub="`${legQuoteAgeLabel(play)} · ${legGreeksLabel(play)}`"
                tone="flat"
              />
              <Readout
                label="Max loss"
                :value="maxLossLabel(play)"
                sub="defined risk"
                tone="flat"
              />
              <Readout
                label="Reward / Risk"
                :value="
                  play.risk?.reward_risk_reference != null
                    ? `${num(play.risk.reward_risk_reference, 2)}x`
                    : DASH
                "
                sub="structure targets"
                :tone="(play.risk?.reward_risk_reference ?? 0) >= 1.5 ? 'pos' : 'flat'"
              />
              <Readout
                label="Chain"
                :value="chainFreshnessLabel(play)"
                :sub="
                  evidenceOf(play).targetExpiry
                    ? `expiry ${shortDate(evidenceOf(play).targetExpiry)}`
                    : 'expiry unmeasured'
                "
                tone="flat"
              />
            </div>
            <div v-if="isEngineTicket(play)" class="levels-row">
              <div class="level-cell">
                <span class="label level-key">SPOT</span>
                <span class="fig">{{ usd(play.entry?.underlying_reference, 2) }}</span>
              </div>
              <div class="level-cell">
                <span class="label level-key">TARGET 1</span>
                <span class="fig pos">{{ usd(evidenceOf(play).target1, 2) }}</span>
              </div>
              <div class="level-cell">
                <span class="label level-key">STOP</span>
                <span class="fig neg">{{ usd(evidenceOf(play).supportStop, 2) }}</span>
              </div>
              <div class="level-cell">
                <span class="label level-key">CALL WALL</span>
                <span class="fig">{{
                  evidenceOf(play).callWall != null ? usd(evidenceOf(play).callWall, 2) : DASH
                }}</span>
              </div>
              <div class="level-cell">
                <span class="label level-key">PUT WALL</span>
                <span class="fig">{{
                  evidenceOf(play).putWall != null ? usd(evidenceOf(play).putWall, 2) : DASH
                }}</span>
              </div>
              <div class="level-cell">
                <span class="label level-key">MAX PAIN</span>
                <span class="fig">{{
                  evidenceOf(play).maxPain != null ? usd(evidenceOf(play).maxPain, 2) : DASH
                }}</span>
              </div>
              <div class="level-cell">
                <span class="label level-key">PCR VOL</span>
                <span
                  class="fig"
                  :class="
                    (evidenceOf(play).pcrVolume ?? 1) < 0.65
                      ? 'pos'
                      : (evidenceOf(play).pcrVolume ?? 1) > 1.0
                        ? 'neg'
                        : ''
                  "
                >
                  {{
                    evidenceOf(play).pcrVolume != null ? num(evidenceOf(play).pcrVolume, 2) : DASH
                  }}
                </span>
              </div>
            </div>
            <div class="legs">
              <span class="label legs-label">TICKET</span>
              <span class="fig legs-value">{{ legLabel(play) }}</span>
            </div>
            <div v-if="play.thesis?.length" class="thesis">
              <span class="label">THESIS</span>
              <p>{{ play.thesis.join(' · ') }}</p>
            </div>
            <div v-if="play.invalidation?.length" class="invalidation">
              <span class="label">INVALIDATION</span>
              <p>{{ play.invalidation.join(' · ') }}</p>
            </div>
            <div class="play-actions">
              <button class="qlink label" type="button" @click="openSymbol(play.symbol)">
                MARKET
              </button>
              <button class="qlink label" type="button" @click="openOptions(play.symbol)">
                OPTIONS
              </button>
            </div>
          </article>
        </div>
        <div v-else class="empty-state">
          <strong>No live-validated actionable plays today.</strong>
          <p>
            The pipeline is fail-closed: an ENTER requires a promoted, calibrated fixed-horizon
            probability plus a fresh, executable option quote that passes every liquidity, spread,
            DTE, and risk gate. Review the watchlist, rejections, and blockers below.
          </p>
        </div>
      </Panel>

      <!-- ── Watchlist ─────────────────────────────────────────────────── -->
      <Panel
        label="Watchlist"
        index="04"
        :meta="`${watchlist.length} plausible setup(s) · not execution-valid`"
        class="w-full"
      >
        <div v-if="watchlist.length" class="table-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label col-sym">Symbol</th>
                <th class="label col-side">Side</th>
                <th class="label col-strategy">Setup</th>
                <th class="label num col-rr">R/R</th>
                <th class="label col-kind">Confidence kind</th>
                <th class="label col-grade">Grade</th>
                <th class="label col-reasons">Why not ENTER</th>
                <th class="label col-chain">Options</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in watchlist"
                :key="row.play_id"
                class="decision-row"
                @click="openSymbol(row.symbol)"
              >
                <td class="fig sym col-sym">{{ row.symbol }}</td>
                <td class="col-side">
                  <span class="side-pill" :class="sideClass(row.side)">{{
                    sideWord(row.side)
                  }}</span>
                </td>
                <td class="label col-strategy">{{ strategyLabel(row.strategy) }}</td>
                <td class="fig num col-rr">
                  {{
                    row.risk?.reward_risk_reference != null
                      ? `${num(row.risk.reward_risk_reference, 2)}x`
                      : DASH
                  }}
                </td>
                <td class="label col-kind">{{ confidenceKind(row) }}</td>
                <td class="fig col-grade">{{ row.confidence?.evidence_grade ?? DASH }}</td>
                <td class="label col-reasons">
                  {{ reasonList(row).slice(0, 3).join(' · ') || DASH }}
                </td>
                <td class="col-chain">
                  <button
                    class="chain-btn label"
                    type="button"
                    @click.stop="openOptions(row.symbol)"
                  >
                    CHAIN
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="note pad">No watch candidates this run.</p>
      </Panel>

      <!-- ── Rejections ────────────────────────────────────────────────── -->
      <Panel
        label="Rejections"
        index="05"
        :meta="`${rejections.length} abstained candidate(s)`"
        class="w-full"
      >
        <div v-if="rejections.length" class="table-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label col-sym">Symbol</th>
                <th class="label col-side">Side</th>
                <th class="label col-strategy">Strategy</th>
                <th class="label col-grade">Grade</th>
                <th class="label col-reasons">Failed checks</th>
                <th class="label col-chain">Options</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rejections"
                :key="row.play_id"
                class="decision-row"
                @click="openSymbol(row.symbol)"
              >
                <td class="fig sym col-sym">{{ row.symbol }}</td>
                <td class="col-side">
                  <span class="side-pill" :class="sideClass(row.side)">{{
                    sideWord(row.side)
                  }}</span>
                </td>
                <td class="label col-strategy">{{ row.strategy.replaceAll('_', ' ') }}</td>
                <td class="fig col-grade">{{ row.confidence?.evidence_grade ?? DASH }}</td>
                <td class="label col-reasons">
                  {{ reasonList(row).slice(0, 4).join(' · ') || DASH }}
                </td>
                <td class="col-chain">
                  <button
                    class="chain-btn label"
                    type="button"
                    @click.stop="openOptions(row.symbol)"
                  >
                    CHAIN
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="note pad">No rejected candidates this run.</p>
      </Panel>

      <!-- ── Research board ────────────────────────────────────────────── -->
      <Panel
        label="Research Board"
        index="06"
        :meta="`${researchBoard.length} sealed holdout row(s) · not plays`"
        class="w-full"
      >
        <div v-if="researchBoard.length" class="table-container">
          <table class="grid">
            <thead>
              <tr>
                <th class="label col-sym">Symbol</th>
                <th class="label col-side">Side</th>
                <th class="label num col-hz">Horizon</th>
                <th class="label num col-edge">Dev-calibrated</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, i) in researchBoard"
                :key="`${String(row.symbol)}-${i}`"
                class="decision-row"
                @click="openSymbol(String(row.symbol))"
              >
                <td class="row-select-cell fig sym col-sym">
                  <button
                    type="button"
                    class="row-select-btn"
                    @click.stop="openSymbol(String(row.symbol))"
                  >
                    <span class="sr-only">Select row</span></button
                  >{{ row.symbol }}
                </td>
                <td class="col-side">
                  <span class="side-pill" :class="sideClass(String(row.side))">{{
                    researchSide(row)
                  }}</span>
                </td>
                <td class="fig num col-hz">{{ researchHorizon(row) }}</td>
                <td class="fig num col-edge">{{ researchProbability(row) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="note pad">No sealed research rows this run.</p>
        <p class="note tiny pad">
          These rows are source-owned context only. They are excluded from the decision ledger and
          cannot be acted on until the terminal holdout clears.
        </p>
      </Panel>

      <!-- ── Blockers & warnings ───────────────────────────────────────── -->
      <Panel
        label="Decision Blockers & Warnings"
        index="07"
        :meta="`${blockers.length} blocker(s) · ${warnings.length} warning(s)`"
        class="w-full"
      >
        <div class="blocker-grid">
          <div class="blocker-col">
            <span class="label blocker-head">DECISION BLOCKERS</span>
            <ul v-if="blockers.length" class="blocker-list">
              <li v-for="item in blockers" :key="item" class="label">{{ item }}</li>
            </ul>
            <p v-else class="note">No blockers recorded.</p>
          </div>
          <div class="blocker-col">
            <span class="label blocker-head">EXECUTION HEALTH</span>
            <ul v-if="executionWarnings.length" class="blocker-list">
              <li v-for="item in executionWarnings" :key="item" class="label">{{ item }}</li>
            </ul>
            <p v-else class="note">No execution-health warnings.</p>
          </div>
          <div class="blocker-col">
            <span class="label blocker-head">ADVISORY EVIDENCE</span>
            <ul v-if="advisoryWarnings.length" class="blocker-list">
              <li v-for="item in advisoryWarnings" :key="item" class="label">{{ item }}</li>
            </ul>
            <p v-else class="note">No advisory evidence warnings.</p>
          </div>
        </div>
        <p class="note tiny pad">
          Advisory evidence (Kronos, flow, sector routing, research challengers) can route the scan
          but never modifies confidence or promotion eligibility.
        </p>
      </Panel>
    </template>

    <p v-else class="state label">{{ emptyReason }}</p>
  </div>
</template>

<style scoped>
.plays-view {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  min-width: 0;
  padding-bottom: var(--s6);
}

.page-head {
  display: flex;
  justify-content: space-between;
  gap: var(--s4);
  align-items: flex-start;
  padding: var(--s3) var(--s4);
  border: var(--hair) solid var(--rule);
  border-left: 1px solid var(--phosphor-dim);
  border-radius: var(--r-md);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  background: var(--panel);
}

.title-block h1 {
  margin: 4px 0 8px;
  font-family: var(--font-display);
  font-size: var(--t-display);
  font-weight: 700;
  letter-spacing: var(--track-tight);
}

.title-block p {
  max-width: 76ch;
  margin: 0;
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.5;
}

.eyebrow {
  color: var(--phosphor);
}

.scope-stack {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
  justify-content: flex-end;
  max-width: 420px;
}

.scope-chip {
  padding: 3px 8px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  color: var(--ink-dim);
}

.scope-chip.live {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.scope-chip.planning {
  color: var(--call-hi);
  border-color: var(--call);
  background: var(--call-wash);
}

.scope-chip.engine {
  color: var(--ink-dim);
  border-color: var(--rule-hi);
  background: var(--void-lift);
}

/* Run console */
.run-console {
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  background: var(--panel);
  overflow: hidden;
}

.run-console-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s4);
  padding: var(--s3);
  border-bottom: var(--hair) solid var(--rule-faint);
}

.run-title-block {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.run-kicker {
  color: var(--ink-faint);
}
.run-title {
  font-family: var(--font-data);
  font-size: var(--t-small);
  letter-spacing: 0.04em;
}
.last-run {
  color: var(--ink-faint);
}

.run-controls {
  display: flex;
  align-items: flex-end;
  gap: var(--s2);
}

.account-field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  color: var(--ink-faint);
}

.account-input {
  width: 120px;
  height: 28px;
  padding: 0 var(--s2);
  color: var(--ink);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-size: var(--t-small);
}

.run-btn,
.refresh-btn {
  height: 28px;
  padding: 0 var(--s3);
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-weight: 600;
  cursor: pointer;
}

.run-btn {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
}

.refresh-btn {
  color: var(--ink-dim);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-hi);
}

.run-btn:disabled,
.refresh-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.run-pulse {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 6px;
  border-radius: 50%;
  background: currentColor;
  vertical-align: middle;
}

.run-progress {
  padding: var(--s3);
  border-bottom: var(--hair) solid var(--rule-faint);
}

.run-progress-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-bottom: var(--s2);
}

.run-progress-copy strong {
  font-family: var(--font-data);
  font-size: var(--t-small);
}
.run-progress-copy small {
  color: var(--ink-faint);
}

.run-progress-track {
  height: 4px;
  background: var(--void-lift);
  border-radius: var(--r-xs);
  overflow: hidden;
}

.run-progress-track i {
  display: block;
  height: 100%;
  background: var(--phosphor);
}

.run-explain {
  padding: var(--s2) var(--s3);
  color: var(--ink-faint);
}

.run-msg {
  color: var(--ink-dim);
}

/* Summary deck */
.summary-deck {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--s3);
}

.kpi-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--s3);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  background: var(--panel);
}

.kpi-label {
  color: var(--ink-faint);
}
.kpi-val {
  font-size: var(--t-fig);
  font-weight: 500;
}
.kpi-sub {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  line-height: 1.4;
}

.kpi-card.pos .kpi-val {
  color: var(--long);
}
.kpi-card.neg .kpi-val {
  color: var(--short);
}
.kpi-card.warn .kpi-val {
  color: var(--warn);
}
.kpi-card.flat .kpi-val {
  color: var(--ink-dim);
}

/* Market map */
.map-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s4);
}

.map-col {
  min-width: 0;
}

.map-head {
  display: block;
  margin-bottom: var(--s2);
  font-weight: 700;
  letter-spacing: 0.06em;
}

.map-head.pos {
  color: var(--long);
}
.map-head.neg {
  color: var(--short);
}

.map-rows {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
}

.map-row {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr) 90px auto;
  align-items: center;
  gap: var(--s2);
  padding: var(--s1) var(--s2);
  border: var(--hair) solid var(--rule-faint);
  border-radius: var(--r-xs);
  background: var(--void-lift);
}

.map-row .sym {
  font-weight: 700;
}
.map-row .name {
  color: var(--ink-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.map-row .score {
  text-align: right;
}
.map-row .score.pos {
  color: var(--long);
}
.map-row .score.neg {
  color: var(--short);
}
.definitive {
  color: var(--phosphor);
  font-size: var(--t-micro);
}

/* Funnel */
.funnel {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: var(--s2);
}

.funnel-step {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: var(--s2);
  border: var(--hair) solid var(--rule-faint);
  border-radius: var(--r-xs);
  background: var(--void-lift);
}

.funnel-idx {
  color: var(--phosphor);
  font-size: var(--t-micro);
}
.funnel-label {
  color: var(--ink-faint);
}
.funnel-value {
  font-size: var(--t-fig);
  font-weight: 500;
}
.funnel-sub {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

/* Plays */
.plays-list {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.play-card {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s3);
  border: var(--hair) solid var(--phosphor-dim);
  border-radius: var(--r-md);
  background: var(--phosphor-wash);
}

.play-head {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.sym-lg {
  font-size: var(--t-fig);
  font-weight: 600;
}
.strategy {
  color: var(--ink-dim);
}
.state.enter {
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  padding: 2px 7px;
  border-radius: var(--r-xs);
}
.rank {
  color: var(--ink-faint);
  margin-left: auto;
}

.play-readouts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s3);
}

/* Structure levels row (engine tickets) */
.levels-row {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: var(--s2);
}

.level-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--s2);
  border: var(--hair) solid var(--rule-faint);
  border-radius: var(--r-xs);
  background: var(--void-lift);
}

.level-key {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}
.level-cell .fig {
  font-size: var(--t-small);
}

.legs {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: var(--s2);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  background: var(--void-lift);
}

.legs-label {
  color: var(--ink-faint);
}
.legs-value {
  color: var(--ink);
  font-size: var(--t-small);
  word-break: break-all;
}

.thesis,
.invalidation {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.thesis .label {
  color: var(--long);
}
.invalidation .label {
  color: var(--short);
}
.thesis p,
.invalidation p {
  margin: 0;
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.5;
}

.play-actions {
  display: flex;
  gap: var(--s2);
}

.qlink {
  padding: 3px 8px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  color: var(--ink-dim);
  background: var(--void-lift);
  cursor: pointer;
  font-family: var(--font-data);
}

.qlink:hover {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

.empty-state {
  padding: var(--s4);
  border: var(--hair) solid var(--warn);
  border-radius: var(--r-md);
  background: var(--warn-wash);
}

.empty-state strong {
  color: var(--warn);
}
.empty-state p {
  margin: var(--s2) 0 0;
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.5;
}

/* Tables */
.table-container {
  overflow: auto;
  max-height: 560px;
}

.grid {
  width: 100%;
  border-collapse: collapse;
}

.grid th,
.grid td {
  padding: 7px 10px;
  border-bottom: var(--hair) solid var(--rule-faint);
  text-align: left;
  font-size: var(--t-small);
}

.grid th.num,
.grid td.num {
  text-align: right;
}

.grid tbody tr {
  cursor: pointer;
}
.grid tbody tr:hover {
  background: var(--panel-hi);
}

.sym {
  font-weight: 700;
}

.side-pill {
  display: inline-block;
  padding: 1px 7px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-size: var(--t-micro);
}

.side-pill.pos {
  color: var(--long);
  border-color: var(--long);
  background: var(--long-wash);
}
.side-pill.neg {
  color: var(--short);
  border-color: var(--short);
  background: var(--short-wash);
}
.side-pill.flat {
  color: var(--ink-faint);
}

.chain-btn {
  padding: 2px 7px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  color: var(--ink-dim);
  background: var(--void-lift);
  cursor: pointer;
  font-family: var(--font-data);
}

.chain-btn:hover {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

/* Blockers */
.blocker-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s4);
}

.blocker-col {
  min-width: 0;
}

.blocker-head {
  display: block;
  margin-bottom: var(--s2);
  color: var(--ink-faint);
  font-weight: 700;
  letter-spacing: 0.06em;
}

.blocker-list {
  margin: 0;
  padding-left: 1.1em;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.6;
}
/* Each blocker is a full sentence; .label would otherwise clip it to one line. */
.blocker-list li {
  overflow: visible;
  text-overflow: clip;
  white-space: normal;
}
/* Failed-check lists are joined sentences — wrap them inside the table cell. */
.col-reasons {
  overflow: visible;
  text-overflow: clip;
  white-space: normal;
  line-height: 1.4;
}

.note {
  margin: 0;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
}
.note.pad {
  padding: var(--s3);
}
.note.tiny.pad {
  padding: var(--s2) var(--s3);
  color: var(--ink-faint);
}

.state {
  padding: var(--s4);
  color: var(--ink-dim);
}
.state.err {
  color: var(--short);
}

@media (max-width: 1100px) {
  .summary-deck {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .funnel {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
  .play-readouts {
    grid-template-columns: 1fr 1fr;
  }
  .levels-row {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 780px) {
  .page-head {
    flex-direction: column;
  }
  .scope-stack {
    justify-content: flex-start;
    max-width: none;
  }
  .run-console-head {
    flex-direction: column;
    align-items: stretch;
  }
  .run-controls {
    flex-wrap: wrap;
  }
  .map-grid {
    grid-template-columns: 1fr;
  }
  .blocker-grid {
    grid-template-columns: 1fr;
  }
  .summary-deck {
    grid-template-columns: 1fr 1fr;
  }
  .funnel {
    grid-template-columns: 1fr 1fr;
  }
  .levels-row {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
