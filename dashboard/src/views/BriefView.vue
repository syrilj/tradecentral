<script setup lang="ts">
/**
 * The Brief — the day's best setups first, then one name read in depth.
 *
 * The top section is cross-sectional: `/api/plays` is the stack's own
 * decision funnel (market map → routed targets → directional setups → live
 * chain validation), ranked ENTER-first, refreshed while the tab is open, and
 * runnable from here when no run is persisted. It answers "what do I play
 * right now" with the exact contract, its levels and its invalidation.
 *
 * Below that, the single-name read: every card answers one question and links
 * to the tab that owns the detail, so this page stays a summary rather than a
 * taller copy of the workstation. Clicking a setup loads its symbol here.
 *
 * The direction call comes from `/api/adaptive-signal` — the stack's own
 * multi-stream blend, under weights it derives. This page does not invent a
 * score. Dealer gamma sits in its own card because it describes range, not
 * direction, and folding it into a direction blend was the specific error
 * that made an earlier version read "leans bullish +1.00" on a name the
 * calibrated blend called neutral at +0.007.
 */
import { computed, inject, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type AdaptiveSignalPayload,
  type MarketFlowPrint,
  type OptionsIntelligence,
  type PlaysDecision,
  type PlaysJob,
  type PlaysPayload,
  type StatusPayload,
  type SupplyChainPayload,
} from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import { compact, num, signed, usd, shortDate, age, DASH } from '@/format'
import {
  humaniseError,
  prettyReason,
  rankLevels,
  readCall,
  buildLadder,
  pullMass,
  readTargets,
  sortWorries,
  type WorryItem,
} from '@/briefRead'
import type { MicrostructureRegimeSnapshot } from '@/microstructureContracts'
import PriceLadder from '@/components/PriceLadder.vue'
import LoadingState from '@/components/LoadingState.vue'

const route = useRoute()
const router = useRouter()
const sharedStatus = inject<Resource<StatusPayload> | null>('status', null)

function querySymbol(): string {
  const raw = route.query.symbol
  const value = Array.isArray(raw) ? raw[0] : raw
  return String(value || 'SPY')
    .trim()
    .toUpperCase()
}

const symbol = ref(querySymbol())
const symbolInput = ref(symbol.value)

/* ── symbol validation ───────────────────────────────────────────────────
   The heavy lenses are six requests, several of which take tens of seconds
   before timing out. Resolving the ticker first means a typo reports "not
   recognised" in a moment instead of six staggered failures. */
const symbolStatus = ref<'ok' | 'checking' | 'unknown'>('ok')
const resolvedName = ref<string | null>(null)

async function resolveSymbol(candidate: string): Promise<boolean> {
  symbolStatus.value = 'checking'
  try {
    const hits = await api.search(candidate, 8)
    const match = hits.find((h) => h.symbol.toUpperCase() === candidate)
    if (match) {
      resolvedName.value = match.name ?? null
      symbolStatus.value = 'ok'
      return true
    }
    resolvedName.value = null
    symbolStatus.value = 'unknown'
    return false
  } catch {
    /* Search itself is down. Do not block the read on a validator outage —
       let the lenses try and report their own failures. */
    symbolStatus.value = 'ok'
    return true
  }
}

async function commitSymbol(): Promise<void> {
  const clean = symbolInput.value
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
  if (!clean || clean === symbol.value) return
  const known = await resolveSymbol(clean)
  if (!known) return
  symbol.value = clean
  void router.replace({ query: { ...route.query, symbol: clean } })
}

watch(
  () => route.query.symbol,
  () => {
    const next = querySymbol()
    if (next !== symbol.value) {
      symbol.value = next
      symbolInput.value = next
      void resolveSymbol(next)
    }
  },
)

void resolveSymbol(symbol.value)

/* ── resources ─────────────────────────────────────────────────────────── */
const quotesRes = useResource(() => api.quotes([symbol.value]), { intervalMs: 10_000 })
const callRes = useResource<AdaptiveSignalPayload>(
  () => api.adaptiveSignal({ symbol: symbol.value }),
  { intervalMs: 60_000 },
)
const microRes = useResource<MicrostructureRegimeSnapshot>(
  () => api.microstructureRegime(symbol.value),
  { intervalMs: 30_000 },
)
const optionsRes = useResource<OptionsIntelligence>(
  () => api.options({ symbol: symbol.value, mode: 'live', range: '5d' }),
  { intervalMs: 30_000 },
)
const targetRes = useResource(() => api.priceAttractors(symbol.value), { intervalMs: 30_000 })
const flowRes = useResource(() => api.unusualFlow({ limit: 300 }), { intervalMs: 30_000 })
const chainRes = useResource<SupplyChainPayload>(
  () => api.supplyChain({ symbol: symbol.value, depth: 2 }),
  { intervalMs: 0 },
)

/* ── today's top setups (cross-sectional) ─────────────────────────────────
   `/api/plays` is the decision funnel the Plays tab operates. Here it is
   the ranked answer to "what do I play right now": ENTER tickets first, then
   the watchlist, each with its exact contract, levels and invalidation. */
const playsRes = useResource<PlaysPayload>(() => api.plays(), { intervalMs: 60_000 })

const playsPayload = computed(() => playsRes.data.value)
const playsAvailable = computed(() => playsPayload.value?.available === true)
const playsLoading = computed(() => playsRes.loading.value && !playsPayload.value)

const playsMeta = computed(() => {
  const p = playsPayload.value
  if (!p?.available) return null
  const parts: string[] = []
  if (p.asof_utc) parts.push(`asof ${shortDate(p.asof_utc)}`)
  if (p.market_session) parts.push(String(p.market_session).toUpperCase())
  return parts.join(' · ')
})

interface SetupCard {
  id: string
  symbol: string
  side: string
  sideWord: string
  sideClass: string
  strategy: string
  state: string
  stateClass: string
  rank: number
  contract: string
  quoteAge: string
  entry: string
  target1: string
  stop: string
  maxLoss: string
  rr: string
  thesis: string
  invalidation: string
}

function readNumber(evidence: Record<string, unknown>, key: string): number | null {
  const v = evidence?.[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function money(v: number | null, dp = 2): string {
  return v == null ? DASH : usd(v, dp)
}

function contractLabel(play: PlaysDecision): string {
  const legs = play.legs ?? []
  if (!legs.length) return 'No validated contract'
  return legs
    .map((leg) => {
      const right = String(leg.right ?? '').toUpperCase()
      const expiry = leg.expiry ? shortDate(leg.expiry) : DASH
      const cap = leg.ask != null ? `@ ≤ ${usd(leg.ask, 2)}` : ''
      return `${String(leg.side).toUpperCase()} ${right} ${num(leg.strike, 2)} ${expiry} ${cap}`.trim()
    })
    .join(' + ')
}

function setupOf(play: PlaysDecision): SetupCard {
  const side = String(play.side ?? '').toLowerCase()
  const state = String(play.state ?? '').toUpperCase()
  const ev = (play.evidence ?? {}) as Record<string, unknown>
  const rr = play.risk?.reward_risk_reference
  return {
    id: String(play.play_id ?? `${play.symbol}-${play.rank}`),
    symbol: String(play.symbol ?? DASH),
    side,
    sideWord: side === 'long' ? 'LONG' : side === 'short' ? 'SHORT' : 'FLAT',
    sideClass: side === 'long' ? 'pos' : side === 'short' ? 'neg' : 'flat',
    strategy: String(play.strategy ?? '').replaceAll('_', ' ').toUpperCase(),
    state,
    stateClass: state === 'ENTER' ? 'enter' : state === 'WATCH' ? 'watch' : 'flat',
    rank: Number(play.rank ?? 0),
    contract: contractLabel(play),
    quoteAge: play.legs?.[0]?.quote_asof_utc ? `${age(play.legs[0].quote_asof_utc)} old` : '',
    entry: money(play.entry?.underlying_reference ?? null),
    target1: money(readNumber(ev, 'target_1')),
    stop: money(readNumber(ev, 'support_stop')),
    maxLoss:
      play.risk?.max_loss_dollars != null && Number.isFinite(play.risk.max_loss_dollars)
        ? usd(play.risk.max_loss_dollars, 0)
        : DASH,
    rr: rr != null && Number.isFinite(rr) ? `${num(rr, 2)}x` : DASH,
    thesis: (play.thesis ?? [])[0] ?? '',
    invalidation: (play.invalidation ?? [])[0] ?? '',
  }
}

/** ENTER tickets first in funnel rank, then the watchlist behind them. */
const setups = computed<SetupCard[]>(() => {
  const p = playsPayload.value
  if (!p?.available) return []
  return [...(p.plays ?? []), ...(p.watchlist ?? [])].map(setupOf)
})

const enterCount = computed(() => (playsPayload.value?.plays ?? []).length)

/* ── running the funnel from here ────────────────────────────────────────
   A live run is a background job (it can take minutes); the same tracker as
   the Plays tab, compacted. Leaving the page does not cancel the run. */
const runRunning = ref(false)
const runMsg = ref<string | null>(null)
const runJob = ref<PlaysJob | null>(null)
let pollToken = 0

function scanDelay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function trackRunJob(initial: PlaysJob, token: number): Promise<void> {
  let current = initial
  runJob.value = current
  while (token === pollToken && (current.state === 'queued' || current.state === 'running')) {
    await scanDelay(1000)
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
    await playsRes.refresh()
  } else if (current.state === 'failed') {
    runMsg.value = current.error || current.message
  }
}

async function runTodayScan(): Promise<void> {
  const token = ++pollToken
  runRunning.value = true
  runMsg.value = null
  try {
    const payloadJob = await api.playsRun()
    if (!payloadJob.job) throw new Error(payloadJob.message)
    runMsg.value = payloadJob.message
    await trackRunJob(payloadJob.job, token)
  } catch (e) {
    runMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (token === pollToken) runRunning.value = false
  }
}

onUnmounted(() => {
  pollToken += 1
})

watch(symbol, () => {
  void quotesRes.refresh({ clear: true })
  void callRes.refresh({ clear: true })
  void microRes.refresh({ clear: true })
  void optionsRes.refresh({ clear: true })
  void targetRes.refresh({ clear: true })
  void chainRes.refresh({ clear: true })
})

function refreshAll(): void {
  void quotesRes.refresh()
  void callRes.refresh()
  void microRes.refresh()
  void optionsRes.refresh()
  void targetRes.refresh()
  void flowRes.refresh()
  void chainRes.refresh()
  void playsRes.refresh()
}

/* ── base reads ────────────────────────────────────────────────────────── */
const micro = computed(() => microRes.data.value)
const options = computed(() => optionsRes.data.value)
const chain = computed(() => chainRes.data.value)
const quote = computed(() => quotesRes.data.value?.rows?.[0] ?? null)
const summary = computed(() => options.value?.summary ?? null)
const probability = computed(() => options.value?.probability ?? null)
const measurable = computed(() => micro.value?.quality?.measurable ?? false)

const spot = computed<number | null>(
  () => quote.value?.last ?? micro.value?.spot ?? summary.value?.spot ?? null,
)

const targets = computed(() => readTargets(targetRes.data.value))

const mass = computed(() => pullMass(targets.value?.levels ?? []))

/**
 * The aggregate direction and the nearest magnet can genuinely disagree —
 * AMD read "pulling down" on downside mass while its strongest single magnet
 * sat 2.5% above spot. Both are true; the card labels them separately rather
 * than printing them adjacent as if one statement.
 */
const massLabel = computed(() => {
  const { above, below } = mass.value
  const total = above + below
  if (total <= 0) return null
  const upShare = above / total
  return {
    upShare,
    text:
      upShare > 0.6
        ? `${(upShare * 100).toFixed(0)}% of pull sits above spot`
        : upShare < 0.4
          ? `${((1 - upShare) * 100).toFixed(0)}% of pull sits below spot`
          : 'Pull is balanced either side of spot',
  }
})

const call = computed(() =>
  readCall(callRes.data.value?.signal, callRes.data.value?.stream_hit_rates),
)

const sideLabel = computed(() => {
  switch (call.value?.side) {
    case 'long':
      return 'LONG'
    case 'short':
      return 'SHORT'
    default:
      return 'NEUTRAL'
  }
})

/** Widest contribution in the set, so the bars share one scale. */
const maxContribution = computed(() =>
  Math.max(...(call.value?.streams ?? []).map((s) => Math.abs(s.contribution)), 0.0001),
)

/** Signed distance from spot TO the level — the one convention on this page. */
const distanceToFlipPct = computed<number | null>(() => {
  const s = spot.value
  const flip = micro.value?.gamma_flip
  if (typeof s !== 'number' || typeof flip !== 'number' || s <= 0) return null
  return ((flip - s) / s) * 100
})

/* ── range (dealer positioning) ────────────────────────────────────────── */
/** Spot marker position on the flip ruler: 0 = 2%+ below flip, 50 = at flip,
 *  100 = 2%+ above. Clamped so the marker never leaves the rail. */
const flipRuler = computed(() => {
  const s = spot.value
  const f = micro.value?.gamma_flip
  if (typeof s !== 'number' || typeof f !== 'number' || s <= 0) return null
  const d = ((f - s) / s) * 100
  const pos = 50 - Math.max(-2, Math.min(2, d)) * 25
  return { d, pos }
})

const rangeRead = computed(() => {
  const m = micro.value
  if (!m || !measurable.value) return null
  const cs = options.value?.charm_summary ?? null
  return {
    regime: m.regime,
    title:
      m.regime === 'positive_gamma'
        ? 'Range compressed'
        : m.regime === 'negative_gamma'
          ? 'Range amplified'
          : 'Range unstable',
    body:
      m.regime === 'positive_gamma'
        ? 'Dealers are long gamma: they buy weakness and sell strength, so moves get absorbed.'
        : m.regime === 'negative_gamma'
          ? 'Dealers are short gamma: they sell weakness and buy strength, so moves get bigger.'
          : 'Dealer gamma is balanced or neutral: flow does not reliably pin or accelerate spot.',
    netGex: m.net_gex_m,
    charm: cs,
  }
})

/* ── levels ────────────────────────────────────────────────────────────── */
const watchLevels = computed(() =>
  rankLevels(spot.value, [
    { kind: 'gamma_flip', label: 'Gamma flip', price: micro.value?.gamma_flip },
    { kind: 'call_wall', label: 'Call wall', price: micro.value?.call_wall },
    { kind: 'put_wall', label: 'Put wall', price: micro.value?.put_wall },
    { kind: 'pin', label: 'Pin strike', price: summary.value?.pin_strike },
    { kind: 'vol_trigger', label: 'Vol trigger', price: micro.value?.volatility_trigger },
    { kind: 'peak', label: 'Gamma peak', price: micro.value?.absolute_gamma_peak },
  ]),
)

const ladder = computed(() =>
  buildLadder(spot.value, watchLevels.value, targets.value?.levels ?? []),
)

const horizonLabel = computed<string | null>(() => {
  const p = probability.value
  if (!p?.available) return null
  if (typeof p.horizon_days === 'number') return `${p.horizon_days}D`
  return p.expiry ?? null
})

/* ── flow ──────────────────────────────────────────────────────────────── */
const flowRow = computed(
  () => (flowRes.data.value?.rows ?? []).find((r) => r.symbol === symbol.value) ?? null,
)

const flowPrints = computed(() =>
  (flowRes.data.value?.tape ?? []).filter((p) => p.symbol === symbol.value).slice(0, 5),
)

function printTime(ts: string | null | undefined): string {
  const s = String(ts ?? '')
  return s.slice(11, 16) || '—'
}

function printWhy(p: MarketFlowPrint): string {
  if (p.trade_class && p.trade_class !== 'single') return p.trade_class
  if (p.why?.length) return p.why[0]
  if (p.anomaly_flags?.length) return String(p.anomaly_flags[0]).replace(/_/g, ' ')
  return p.aggressor_label?.toLowerCase() ?? '—'
}

/* ── chain ─────────────────────────────────────────────────────────────── */
const chainPicks = computed(() => {
  const nodes = chain.value?.nodes ?? []
  /* One company can hold two roles in the same chain — GOOGL is both a
     horizontal enabler and a downstream customer of NVDA — and the payload
     carries a node per role. Keep the strongest reading once. */
  const best = new Map<string, (typeof nodes)[number]>()
  for (const n of nodes) {
    if (n.symbol === symbol.value) continue
    const score = n.metrics.elasticity_score
    if (score == null) continue // unscored nodes are not ranked
    const prev = best.get(n.symbol)
    const prevScore = prev?.metrics.elasticity_score
    if (!prev || prevScore == null || score > prevScore) best.set(n.symbol, n)
  }
  return [...best.values()]
    .sort((a, b) => (b.metrics.elasticity_score ?? 0) - (a.metrics.elasticity_score ?? 0))
    .slice(0, 6)
})

const chainMessage = computed(() =>
  chainRes.loading.value && !chain.value
    ? 'Mapping the chain…'
    : (humaniseError(chainRes.error.value, 'Supply chain') ??
      (chainPicks.value.length ? null : 'No supply chain is mapped for this symbol.')),
)

/* ── worries ───────────────────────────────────────────────────────────── */
const worries = computed<WorryItem[]>(() => {
  const out: WorryItem[] = []
  const m = micro.value
  const sum = summary.value
  const c = call.value

  if (c && !c.performanceTilted) {
    out.push({
      severity: 'medium',
      title: 'The call is not performance-calibrated',
      detail: c.weightNote,
    })
  }

  if (c && (c.band === 'thin' || c.band === 'conflicted')) {
    out.push({
      severity: 'medium',
      title: `Stream agreement is ${c.band}`,
      detail:
        c.band === 'conflicted'
          ? 'The streams point in different directions; the composite is an average over a real disagreement.'
          : 'The streams barely move the composite. This is close to no signal at all.',
    })
  }

  const t = targets.value
  if (t && c && t.direction !== 'neutral' && c.side !== 'neutral') {
    const pullUp = t.direction === 'bullish_pull'
    if (pullUp !== (c.side === 'long')) {
      out.push({
        severity: 'medium',
        title: 'Pull and lean point opposite ways',
        detail: `Attractors pull ${pullUp ? 'up' : 'down'} while the blend leans ${c.side}. One of them is early.`,
      })
    }
  }

  const dist = distanceToFlipPct.value
  if (dist !== null && Math.abs(dist) < 0.5) {
    out.push({
      severity: 'high',
      title: `Sitting on the gamma flip (${signed(dist, 2)}%)`,
      detail: 'Dealer hedging changes sign here; the range read can invert on a tiny move.',
    })
  }

  if (m?.regime === 'negative_gamma') {
    out.push({
      severity: 'high',
      title: 'Negative gamma amplifies moves',
      detail: 'Hedging is pro-cyclical. Expect wider range and faster tails than ±EM implies.',
    })
  }

  if (!measurable.value && !microRes.loading.value) {
    out.push({
      severity: 'high',
      title: 'Dealer gamma is unmeasurable',
      detail:
        m?.quality?.reason ?? 'The chain did not support a gamma read, so levels are withheld.',
    })
  }

  if (sum && sum.signed_net_premium == null) {
    out.push({
      severity: 'medium',
      title: 'Flow direction is not signed',
      detail: 'Prints carry no side, so no bullish or bearish read can be taken from flow.',
    })
  }

  const feedAge = feedAgeSeconds.value
  if (typeof feedAge === 'number' && feedAge > 300) {
    out.push({
      severity: 'medium',
      title: `Options data is ${describeAge(feedAge)} old`,
      detail: 'Every chain-derived figure here describes a stale book.',
    })
  }

  const lenses: Array<[string, Resource<unknown>]> = [
    ['The call', callRes],
    ['Dealer positioning', microRes],
    ['Options', optionsRes],
    ['Price targets', targetRes],
    ['Flow', flowRes],
  ]
  for (const [lens, res] of lenses) {
    const msg = humaniseError(res.error.value, lens)
    if (msg) out.push({ severity: 'high', title: `${lens} unavailable`, detail: msg })
  }

  return sortWorries(out).slice(0, 4)
})

/** Scale the unit to the gap: "44 hours" beats "2641 minutes". */
function describeAge(seconds: number): string {
  const mins = Math.round(seconds / 60)
  if (mins < 90) return `${mins} minute${mins === 1 ? '' : 's'}`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `${hours} hour${hours === 1 ? '' : 's'}`
  const days = Math.round(hours / 24)
  return `${days} day${days === 1 ? '' : 's'}`
}

/* Freshness for the reader, without naming a single endpoint. */
const anyLoading = computed(
  () =>
    callRes.loading.value ||
    microRes.loading.value ||
    optionsRes.loading.value ||
    targetRes.loading.value ||
    flowRes.loading.value,
)

const feedAgeSeconds = computed(() => options.value?.freshness?.feed_age_seconds ?? null)

const staleFeed = computed(() => {
  const a = feedAgeSeconds.value
  return typeof a === 'number' && a > 300
})

const freshnessLabel = computed(() =>
  anyLoading.value
    ? 'UPDATING'
    : staleFeed.value
      ? `STALE ${describeAge(feedAgeSeconds.value ?? 0).toUpperCase()}`
      : 'LIVE',
)

const marketAsof = computed(() => sharedStatus?.data.value?.asof ?? null)

/* ── drill-down ────────────────────────────────────────────────────────── */
function drill(name: string): void {
  void router.push({ name, query: { symbol: symbol.value } })
}

function openSymbol(sym: string): void {
  symbolInput.value = sym
  void commitSymbol()
}
</script>

<template>
  <div class="brief">
    <!-- ── header ──────────────────────────────────────────────────────── -->
    <header class="head">
      <div class="ident">
        <h1>{{ symbol }}</h1>
        <span class="spot fig">{{ spot === null ? '—' : num(spot, 2) }}</span>
        <span
          v-if="quote?.chg_1d_pct != null"
          :class="['chg', 'fig', quote.chg_1d_pct >= 0 ? 'pos' : 'neg']"
          >{{ signed(quote.chg_1d_pct, 2) }}%</span
        >
        <span v-if="resolvedName" class="coname">{{ resolvedName }}</span>
      </div>

      <form class="controls" @submit.prevent="commitSymbol">
        <label class="sr-only" for="brief-symbol">Underlier</label>
        <input
          id="brief-symbol"
          v-model="symbolInput"
          class="sym-input"
          :class="{ bad: symbolStatus === 'unknown' }"
          spellcheck="false"
          autocomplete="off"
          placeholder="SPY"
        />
        <button type="submit" class="btn">Read</button>
        <button type="button" class="btn ghost" @click="refreshAll">Refresh</button>
        <span class="freshness label" :class="{ 'is-stale': staleFeed && !anyLoading }">
          <i
            aria-hidden="true"
            :class="['dot', anyLoading ? 'busy' : staleFeed ? 'stale' : 'live']"
          />
          {{ freshnessLabel }}
        </span>
      </form>
    </header>

    <p v-if="symbolStatus === 'unknown'" class="notice" role="alert">
      <strong>{{ symbolInput.toUpperCase() }}</strong> isn’t a symbol this desk covers. Check the
      ticker, or search for it from the Market tab.
    </p>

    <!-- ── today's top setups ────────────────────────────────────────────── -->
    <section class="setups" aria-label="Today's top setups">
      <header class="setups-head">
        <div class="setups-title-block">
          <h2 class="setups-title">Top setups right now</h2>
          <p class="setups-sub">
            The funnel's own ranking, live: ENTER first, then the watchlist. Click a name to read
            it in depth below.
          </p>
        </div>
        <div class="setups-controls">
          <span v-if="playsMeta" class="label setups-meta">{{ playsMeta }}</span>
          <button
            type="button"
            class="btn"
            :disabled="runRunning"
            @click="runTodayScan"
          >
            {{ runRunning ? `${runJob?.progress ?? 0}% · SCANNING` : 'RUN SCAN' }}
          </button>
          <button
            type="button"
            class="btn ghost"
            :disabled="playsRes.loading.value"
            @click="playsRes.refresh()"
          >
            {{ playsRes.loading.value ? 'UPDATING…' : 'UPDATE' }}
          </button>
          <button type="button" class="btn ghost" @click="drill('plays')">ALL PLAYS →</button>
        </div>
      </header>

      <div v-if="runRunning && runJob" class="run-progress" role="status" aria-live="polite">
        <span class="label">{{ runJob.stage.replaceAll('_', ' ').toUpperCase() }}</span>
        <strong>{{ runJob.message }}</strong>
        <span
          class="run-progress-track"
          role="progressbar"
          aria-label="Scan run completion"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-valuenow="runJob.progress"
        >
          <i :style="{ width: `${runJob.progress}%` }" />
        </span>
      </div>
      <p v-else-if="runMsg && !playsAvailable" class="run-msg label" aria-live="polite">
        {{ runMsg }}
      </p>

      <LoadingState v-if="playsLoading" label="Reading today's run…" />
      <p v-else-if="playsRes.error.value && !playsAvailable" class="empty">
        {{ humaniseError(playsRes.error.value, 'The setups funnel') }}
      </p>

      <ul v-else-if="setups.length" class="setup-list">
        <li v-for="s in setups" :key="s.id" :class="['setup', s.stateClass]">
          <button type="button" class="setup-main" @click="openSymbol(s.symbol)">
            <span class="setup-rank fig">{{ s.rank || '—' }}</span>
            <span class="setup-sym fig">{{ s.symbol }}</span>
            <span :class="['setup-side', 'label', s.sideClass]">{{ s.sideWord }}</span>
            <span class="setup-strategy label">{{ s.strategy }}</span>
            <span :class="['setup-state', 'label', s.stateClass]">{{ s.state }}</span>
            <span v-if="s.quoteAge" class="setup-age label">{{ s.quoteAge }}</span>
          </button>
          <div class="setup-body">
            <p class="setup-contract fig">{{ s.contract }}</p>
            <dl class="setup-levels">
              <div>
                <dt class="label">SPOT REF</dt>
                <dd class="fig">{{ s.entry }}</dd>
              </div>
              <div>
                <dt class="label">TARGET 1</dt>
                <dd class="fig pos">{{ s.target1 }}</dd>
              </div>
              <div>
                <dt class="label">STOP / SUPPORT</dt>
                <dd class="fig neg">{{ s.stop }}</dd>
              </div>
              <div>
                <dt class="label">MAX LOSS</dt>
                <dd class="fig">{{ s.maxLoss }}</dd>
              </div>
              <div>
                <dt class="label">R / R</dt>
                <dd class="fig">{{ s.rr }}</dd>
              </div>
            </dl>
            <p v-if="s.thesis" class="setup-why">
              <span class="label">THESIS</span> {{ s.thesis }}
            </p>
            <p v-if="s.invalidation" class="setup-why inv">
              <span class="label">INVALIDATION</span> {{ s.invalidation }}
            </p>
          </div>
        </li>
      </ul>

      <div v-else-if="playsAvailable" class="setup-empty">
        <strong>No setup cleared the gates in the latest run.</strong>
        <p>
          The funnel is fail-closed: an ENTER needs a validated contract, fresh quotes and a
          liquidity-grade chain. {{ enterCount }} actionable, watch the funnel on the Plays tab.
        </p>
        <button type="button" class="btn" :disabled="runRunning" @click="runTodayScan">
          {{ runRunning ? `${runJob?.progress ?? 0}% · SCANNING` : 'RUN A FRESH SCAN' }}
        </button>
      </div>

      <div v-else class="setup-empty">
        <strong>No run persisted yet.</strong>
        <p>
          {{
            playsPayload?.reason ??
            'Run the decision funnel to rank today’s setups live: it takes a few minutes in the background.'
          }}
        </p>
        <button type="button" class="btn" :disabled="runRunning" @click="runTodayScan">
          {{ runRunning ? `${runJob?.progress ?? 0}% · SCANNING` : 'RUN TODAY’S SCAN' }}
        </button>
      </div>
    </section>

    <!-- ── row 1: the call + range ─────────────────────────────────────── -->
    <div class="name-head" aria-label="Single-name read">
      <h2 class="name-title">One name, in depth</h2>
      <span class="label">{{ symbol }} · live read, self-refreshing</span>
    </div>
    <div class="row row-top">
      <section :class="['card', 'call-card', call?.side ?? 'neutral']">
        <header class="card-head">
          <h2 class="card-title">Which way it leans</h2>
          <span class="card-src label">ADAPTIVE BLEND</span>
        </header>

        <template v-if="call">
          <div class="call-figure">
            <strong class="side">{{ sideLabel }}</strong>
            <span class="composite fig">{{ signed(call.score, 3) }}</span>
            <span :class="['band', 'label', call.band]">{{ call.band }} agreement</span>
          </div>

          <ul class="streams">
            <li v-for="s in call.streams" :key="s.name" class="stream">
              <span class="st-name">{{ s.name }}</span>
              <span class="st-bar" aria-hidden="true">
                <i
                  :class="['st-fill', s.contribution >= 0 ? 'up' : 'down']"
                  :style="{
                    width: `${Math.min(50, (Math.abs(s.contribution) / maxContribution) * 50)}%`,
                    [s.contribution >= 0 ? 'insetInlineStart' : 'insetInlineEnd']: '50%',
                  }"
                />
              </span>
              <span :class="['st-val', 'fig', s.contribution >= 0 ? 'pos' : 'neg']">{{
                signed(s.contribution, 3)
              }}</span>
              <span class="st-w label">{{ (s.weight * 100).toFixed(0) }}%</span>
            </li>
          </ul>

          <div class="reasons">
            <span v-for="r in call.reasons.slice(0, 3)" :key="r" class="reason label">{{
              prettyReason(r)
            }}</span>
          </div>

          <p class="caveat">{{ call.weightNote }} Ordinal: not a probability, not an order.</p>
        </template>
        <p v-else class="empty">
          {{ humaniseError(callRes.error.value, 'The call') ?? 'Reading the blend…' }}
        </p>
      </section>

      <section
        :class="['card', 'range-card', rangeRead?.regime ?? 'none']"
        role="link"
        tabindex="0"
        @click="drill('regime')"
        @keyup.enter="drill('regime')"
      >
        <header class="card-head">
          <h2 class="card-title">Dealer force &amp; range</h2>
          <span class="card-src label">REGIME →</span>
        </header>

        <template v-if="rangeRead">
          <strong class="range-title">{{ rangeRead.title }}</strong>
          <p class="range-body">{{ rangeRead.body }}</p>
          <div
            v-if="flipRuler && spot !== null && micro?.gamma_flip != null"
            class="flip-ruler"
            role="img"
            :aria-label="`Spot ${num(spot, 2)} is ${Math.abs(flipRuler.d).toFixed(2)}% ${
              flipRuler.d > 0 ? 'below' : 'above'
            } the gamma flip at ${num(micro.gamma_flip, 2)}`"
          >
            <div class="flip-ruler-track">
              <span class="flip-ruler-tick" />
              <span class="flip-ruler-marker" :style="{ left: `${flipRuler.pos}%` }" />
            </div>
            <p class="flip-ruler-read label">
              GAMMA FLIP {{ num(micro.gamma_flip, 2) }}
              <span class="fig">
                · SPOT {{ Math.abs(flipRuler.d).toFixed(2) }}%
                {{ flipRuler.d > 0 ? 'BELOW' : 'ABOVE' }}
              </span>
            </p>
          </div>
          <dl class="mini-figs">
            <div>
              <dt class="label">NET GEX</dt>
              <dd class="fig">{{ `${signed(rangeRead.netGex, 1)}M` }}</dd>
            </div>
            <div>
              <dt class="label">TO FLIP</dt>
              <dd class="fig">
                {{ distanceToFlipPct === null ? '—' : `${signed(distanceToFlipPct, 2)}%` }}
              </dd>
            </div>
            <div>
              <dt class="label">CHARM</dt>
              <dd class="fig">
                {{
                  rangeRead.charm
                    ? `${compact(Math.abs(rangeRead.charm.net_charm_flow), 1)} ${rangeRead.charm.pressure}`
                    : '—'
                }}
              </dd>
            </div>
          </dl>
        </template>
        <p v-else class="empty">
          {{
            humaniseError(microRes.error.value, 'Dealer positioning') ??
            micro?.quality?.reason ??
            'Reading the chain…'
          }}
        </p>
      </section>
    </div>

    <!-- ── row 2: levels + move + flow ─────────────────────────────────── -->
    <div class="row row-mid">
      <section
        class="card ladder-card"
        role="link"
        tabindex="0"
        @click="drill('options')"
        @keyup.enter="drill('options')"
      >
        <header class="card-head">
          <h2 class="card-title">The ladder</h2>
          <span class="card-src label">OPTIONS →</span>
        </header>
        <PriceLadder
          :spot="spot"
          :rungs="ladder.rungs"
          :expected-low="probability?.expected_low ?? null"
          :expected-high="probability?.expected_high ?? null"
          :horizon-label="horizonLabel"
          :unmeasurable-reason="
            measurable ? null : (micro?.quality?.reason ?? 'Chain not measurable')
          "
        />
      </section>

      <section
        :class="['card', 'target-card', targets?.direction ?? 'neutral']"
        role="link"
        tabindex="0"
        @click="drill('regime')"
        @keyup.enter="drill('regime')"
      >
        <header class="card-head">
          <h2 class="card-title">Where it's pulling</h2>
          <span class="card-src label">ATTRACTORS →</span>
        </header>

        <template v-if="targets?.primary">
          <div class="target-lead">
            <span class="pull-label label">Nearest magnet</span>
            <strong class="target-price fig">{{ num(targets.primary.price, 2) }}</strong>
            <span
              :class="['target-dist', 'fig', targets.primary.side === 'above' ? 'pos' : 'neg']"
              >{{
                targets.primary.distancePct === null
                  ? ''
                  : signed(targets.primary.distancePct, 1) + '%'
              }}</span
            >
          </div>
          <p class="target-why">
            {{ targets.primary.label }} · {{ targets.primary.role }} · pull
            {{ num(targets.primary.pull, 0) }}/100
          </p>
          <p v-if="massLabel" :class="['mass', targets.direction]">
            <span class="label">NET PULL</span> {{ massLabel.text }}
          </p>
          <p v-if="targets.confluence" class="confluence">
            <b>{{ num(targets.confluence.price, 2) }}</b> —
            {{ targets.confluence.lenses.join(' + ') }} agree here
          </p>
        </template>
        <p v-else class="empty">
          {{
            humaniseError(targetRes.error.value, 'Price targets') ??
            targets?.reason ??
            'Locating attractors…'
          }}
        </p>
      </section>
    </div>

    <!-- ── row 3: chain + worries ──────────────────────────────────────── -->
    <div class="row row-bot">
      <section
        class="card"
        role="link"
        tabindex="0"
        @click="drill('flow')"
        @keyup.enter="drill('flow')"
      >
        <header class="card-head">
          <h2 class="card-title">Unusual options in</h2>
          <span class="card-src label">FLOW →</span>
        </header>
        <div v-if="summary" class="prem">
          <span class="prem-bar" aria-hidden="true">
            <i class="call" :style="{ flexGrow: summary.call_premium || 1 }" />
            <i class="put" :style="{ flexGrow: summary.put_premium || 1 }" />
          </span>
          <span class="prem-legend label">
            <b class="pos">{{ compact(summary.call_premium, 1) }} calls</b> ·
            <b class="neg">{{ compact(summary.put_premium, 1) }} puts</b>
            <template v-if="flowRow"> · rank {{ flowRow.activity_rank }}</template>
          </span>
        </div>
        <ul v-if="flowPrints.length" class="prints">
          <li v-for="(p, i) in flowPrints" :key="i">
            <span class="pr-time fig">{{ printTime(p.timestamp) }}</span>
            <span :class="['pr-con', 'fig', p.right === 'call' ? 'pos' : 'neg']"
              >{{ p.right.toUpperCase() }} {{ p.strike ?? '—' }}</span
            >
            <span class="pr-prem fig">{{ compact(p.premium, 1) }}</span>
            <span class="pr-why">{{ printWhy(p) }}</span>
          </li>
        </ul>
        <p v-else class="empty">No unusual prints on {{ symbol }} right now.</p>
      </section>
      <section
        class="card"
        role="link"
        tabindex="0"
        @click="drill('chain')"
        @keyup.enter="drill('chain')"
      >
        <header class="card-head">
          <h2 class="card-title">Worth a look</h2>
          <span class="card-src label">CHAIN →</span>
        </header>
        <ul v-if="chainPicks.length" class="picks">
          <li v-for="n in chainPicks" :key="n.symbol">
            <button type="button" class="pick" @click.stop="openSymbol(n.symbol)">
              <span class="pick-sym fig">{{ n.symbol }}</span>
              <span class="pick-el label">{{ num(n.metrics.elasticity_score, 0) }}</span>
            </button>
          </li>
        </ul>
        <p v-else class="empty">{{ chainMessage }}</p>
      </section>

      <section class="card">
        <header class="card-head">
          <h2 class="card-title">Watch out</h2>
          <span class="card-src label">{{ worries.length }}</span>
        </header>
        <ul v-if="worries.length" class="worries">
          <li v-for="(w, i) in worries" :key="i" :class="['worry', w.severity]">
            <strong>{{ w.title }}</strong>
            <span>{{ w.detail }}</span>
          </li>
        </ul>
        <p v-else class="empty ok">Nothing flagged: every lens reported cleanly.</p>
      </section>
    </div>

    <p class="foot">
      Research instrument · descriptive reads only, no order routing
      <template v-if="marketAsof"> · stack data {{ marketAsof.slice(0, 10) }}</template>
    </p>
  </div>
</template>

<style scoped>
/* Space groups, not lines: 8px inside a card, 16px between cards, 24px
   between rows — every step at least 2x the one it contains. */
.brief {
  display: flex;
  flex-direction: column;
  gap: var(--s5);
  min-width: 0;
  padding-block-end: var(--s6);
}

/* ── header ─────────────────────────────────────────────────────────────*/
.head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s5);
  flex-wrap: wrap;
  padding-block-end: var(--s3);
  border-block-end: var(--hair) solid var(--rule);
}

.ident {
  display: flex;
  align-items: baseline;
  gap: var(--s3);
  flex-wrap: wrap;
  min-width: 0;
}

h1 {
  color: var(--ink);
  font: 700 calc(var(--t-display) + 4px) / 1 var(--font-display);
  letter-spacing: var(--track-display);
}

.spot {
  color: var(--ink);
  font: 500 var(--t-fig-lg) / 1 var(--font-mono);
}

.chg {
  font: 500 var(--t-fig) / 1 var(--font-mono);
}

.chg.pos,
.pos {
  color: var(--long);
}

.chg.neg,
.neg {
  color: var(--short);
}

.coname {
  color: var(--ink-faint);
  font-size: var(--t-small);
}

.controls {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.sym-input {
  inline-size: 7rem;
  padding: 6px 10px;
  color: var(--ink);
  font: 600 var(--t-body) / 1 var(--font-mono);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: var(--panel);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
}

.sym-input.bad {
  border-color: var(--short);
}

.sym-input:focus-visible {
  outline: 2px solid var(--action-focus);
  outline-offset: 1px;
}

.btn {
  min-block-size: 30px;
  padding-inline: 12px;
  color: var(--void);
  font: 600 var(--t-small) / 1 var(--font-ui);
  background: var(--phosphor);
  border: var(--hair) solid var(--phosphor);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.btn:hover {
  background: var(--phosphor-glow);
}

.btn.ghost {
  color: var(--ink-dim);
  background: transparent;
  border-color: var(--rule-hi);
}

.btn.ghost:hover {
  color: var(--ink);
  background: var(--panel-hi);
  border-color: var(--phosphor);
}

.freshness.is-stale {
  color: var(--status-stale);
}

.freshness {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-inline-start: var(--s2);
  color: var(--ink-faint);
}

.dot {
  inline-size: 6px;
  block-size: 6px;
  border-radius: 50%;
  background: var(--phosphor);
}

.dot.stale {
  background: var(--status-stale);
}

.dot.busy {
  background: var(--status-proxy);
  animation: dot-pulse var(--dur-pulse) ease-in-out infinite;
}

@keyframes dot-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

.notice {
  padding: var(--s3) var(--s4);
  color: var(--ink);
  font-size: var(--t-small);
  border: var(--hair) solid var(--short);
  border-radius: var(--r-md);
  background: var(--short-wash);
}

/* ── one-name divider ────────────────────────────────────────────────────*/
.name-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s3);
  flex-wrap: wrap;
  padding-block-start: var(--s2);
  border-block-start: var(--hair) solid var(--rule);
}

.name-title {
  color: var(--ink-dim);
  font: 600 var(--t-body) / 1.2 var(--font-display);
  letter-spacing: var(--track-tight);
}

.name-head .label {
  color: var(--ink-faint);
}

/* ── top setups ──────────────────────────────────────────────────────────*/
.setups {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  border: var(--hair) solid var(--rule);
  border-inline-start: 1px solid var(--phosphor-dim);
  border-radius: var(--r-lg);
  background: var(--panel);
}

.setups-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s4);
  flex-wrap: wrap;
}

.setups-title-block {
  min-width: 0;
}

.setups-title {
  color: var(--ink);
  font: 600 var(--t-lead) / 1.2 var(--font-display);
  letter-spacing: var(--track-tight);
}

.setups-sub {
  margin: 4px 0 0;
  color: var(--ink-faint);
  font-size: var(--t-small);
  line-height: 1.5;
}

.setups-controls {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.setups-meta {
  color: var(--ink-faint);
  margin-inline-end: var(--s1);
}

.run-progress {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.run-progress strong {
  color: var(--ink);
  font: 500 var(--t-small) / 1.3 var(--font-ui);
}

.run-progress-track {
  display: block;
  block-size: 4px;
  border-radius: var(--r-capsule);
  background: var(--panel-hi);
  overflow: hidden;
}

.run-progress-track i {
  display: block;
  block-size: 100%;
  background: var(--phosphor);
}

.run-msg {
  color: var(--ink-dim);
}

.setup-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--s3);
  list-style: none;
}

.setup {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  padding: var(--s3);
  border: var(--hair) solid var(--rule);
  border-inline-start: 1px solid var(--unknown);
  border-radius: var(--r-md);
  background: var(--panel-wash);
}

.setup.enter {
  border-color: var(--phosphor-dim);
  border-inline-start-color: var(--phosphor);
  background: var(--phosphor-wash);
}

.setup.watch {
  border-inline-start-color: var(--warn);
}

.setup-main {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: 0;
  background: none;
  border: none;
  cursor: pointer;
  text-align: start;
}

.setup-main:hover .setup-sym {
  color: var(--phosphor);
}

.setup-rank {
  min-inline-size: 2ch;
  color: var(--ink-faint);
  font-size: var(--t-small);
}

.setup-sym {
  color: var(--ink);
  font: 600 var(--t-fig) / 1 var(--font-mono);
}

.setup-side {
  padding: 1px 7px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
}

.setup-side.pos {
  color: var(--long);
  border-color: var(--long);
}

.setup-side.neg {
  color: var(--short);
  border-color: var(--short);
}

.setup-strategy {
  color: var(--ink-dim);
  white-space: nowrap;
}

.setup-state {
  margin-inline-start: auto;
  padding: 1px 7px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  color: var(--ink-faint);
}

.setup-state.enter {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.setup-state.watch {
  color: var(--warn);
  border-color: var(--warn);
}

.setup-age {
  color: var(--ink-faint);
  white-space: nowrap;
}

.setup-body {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.setup-contract {
  margin: 0;
  color: var(--ink);
  font-size: var(--t-small);
  line-height: 1.5;
  word-break: break-word;
}

.setup-levels {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--s2);
  margin: 0;
}

.setup-levels > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.setup-levels dd {
  margin: 0;
  color: var(--ink);
  font: 500 var(--t-small) / 1.1 var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.setup-why {
  margin: 0;
  color: var(--ink-faint);
  font-size: var(--t-tiny);
  line-height: 1.45;
}

.setup-why .label {
  color: var(--long);
  margin-inline-end: 4px;
}

.setup-why.inv .label {
  color: var(--short);
}

.setup-empty {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  align-items: flex-start;
  padding: var(--s3);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-md);
  background: var(--panel-wash);
}

.setup-empty strong {
  color: var(--ink);
  font: 600 var(--t-body) / 1.2 var(--font-ui);
}

.setup-empty p {
  margin: 0;
  max-width: 68ch;
  color: var(--ink-faint);
  font-size: var(--t-small);
  line-height: 1.5;
}

@media (max-width: 720px) {
  .setup-levels {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

/* ── rows & cards ───────────────────────────────────────────────────────*/
.row {
  display: grid;
  gap: var(--s4);
  min-width: 0;
}

.row-top {
  grid-template-columns: 3fr 2fr;
}

.row-mid {
  grid-template-columns: 3fr 2fr;
}

.row-bot {
  grid-template-columns: 4fr 3fr 4fr;
}

.row > * {
  min-width: 0;
}

/* Cards stretch to their row's height, set by the tallest sibling. Pin the
   trailing block to the foot so the slack lands between lead content and the
   summary stats instead of pooling under the last line. */
.range-card .mini-figs,
.target-card > :last-child {
  margin-block-start: auto;
}

.prints,
.worries {
  flex: 1 1 auto;
  justify-content: space-evenly;
}

.picks {
  flex: 1 1 auto;
  align-content: center;
}

.card {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  padding: var(--s3) var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-lg);
  background: var(--panel);
}

.card[role='link'] {
  cursor: pointer;
}

.card[role='link']:hover,
.card[role='link']:focus-visible {
  border-color: var(--phosphor-dim);
  background: var(--panel-hi);
}

.card[role='link']:focus-visible {
  outline: 2px solid var(--action-focus);
  outline-offset: 2px;
}

.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s3);
  margin-block-end: var(--s1);
}

.card-title {
  color: var(--ink);
  font: 600 var(--t-body) / 1.2 var(--font-ui);
}

.card-src {
  color: var(--ink-faint);
  white-space: nowrap;
}

.card[role='link']:hover .card-src {
  color: var(--phosphor);
}

/* ── the call ───────────────────────────────────────────────────────────*/
.call-card {
  border-inline-start: 1px solid var(--unknown);
}

.call-card.long {
  border-inline-start-color: var(--long);
}

.call-card.short {
  border-inline-start-color: var(--short);
}

.call-figure {
  display: flex;
  align-items: baseline;
  gap: var(--s3);
  flex-wrap: wrap;
}

.side {
  color: var(--ink-dim);
  font: 700 var(--t-display) / 1 var(--font-display);
  letter-spacing: var(--track-tight);
}

.call-card.long .side {
  color: var(--long);
}

.call-card.short .side {
  color: var(--short);
}

.composite {
  color: var(--ink);
  font: 500 var(--t-fig-lg) / 1 var(--font-mono);
}

.band {
  padding: 2px 8px;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-capsule);
}

.band.conflicted {
  color: var(--warn);
  border-color: var(--warn);
}

.streams {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
  margin-block-start: var(--s2);
  list-style: none;
}

/* Contribution bars share one scale and grow from a common centre, so the
   sign is a direction on the page rather than a minus sign to notice. */
.stream {
  display: grid;
  grid-template-columns: 84px 1fr 60px 34px;
  align-items: center;
  gap: var(--s2);
}

.st-name {
  color: var(--text-secondary);
  font-size: var(--t-small);
  text-transform: capitalize;
}

.st-bar {
  position: relative;
  block-size: 6px;
  border-radius: var(--r-capsule);
  background: var(--panel-hi);
}

.st-bar::after {
  content: '';
  position: absolute;
  inset-block: -2px;
  inset-inline-start: 50%;
  inline-size: 1px;
  background: var(--ink-faint);
}

.st-fill {
  position: absolute;
  inset-block: 0;
  border-radius: var(--r-capsule);
}

.st-fill.up {
  background: var(--long);
}

.st-fill.down {
  background: var(--short);
}

.st-val {
  font: 500 var(--t-small) / 1 var(--font-mono);
  text-align: end;
}

.st-w {
  color: var(--ink-faint);
  text-align: end;
}

.reasons {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s1);
  margin-block-start: var(--s2);
}

.reason {
  padding: 2px 8px;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-capsule);
  background: var(--panel-wash);
  text-transform: none;
  letter-spacing: 0.02em;
}

.caveat {
  margin-block-start: var(--s2);
  color: var(--ink-faint);
  font-size: var(--t-tiny);
  line-height: 1.5;
}

/* ── range ──────────────────────────────────────────────────────────────*/
.range-card {
  border-inline-start: 1px solid var(--unknown);
}

.range-card.positive_gamma {
  border-inline-start-color: var(--long);
}

.range-card.negative_gamma {
  border-inline-start-color: var(--short);
}

.range-title {
  color: var(--ink);
  font: 600 var(--t-lead) / 1.2 var(--font-display);
}

.range-body {
  color: var(--text-secondary);
  font-size: var(--t-small);
  line-height: 1.5;
}

/* Spot-vs-flip ruler: center tick is the flip, marker is spot, clamped to
   ±2%. Fills the dead middle of the card without inventing figures. */
.flip-ruler {
  margin-block-start: var(--s4);
}

.flip-ruler-track {
  position: relative;
  height: 3px;
  background: var(--rule-faint);
}

.flip-ruler-tick {
  position: absolute;
  inset-block-start: -4px;
  left: 50%;
  width: 1px;
  height: 11px;
  background: var(--ink-dim);
}

.flip-ruler-marker {
  position: absolute;
  inset-block-start: -3px;
  width: 9px;
  height: 9px;
  margin-left: -4.5px;
  background: var(--phosphor);
}

.flip-ruler-read {
  display: flex;
  gap: var(--s2);
  margin-block-start: var(--s2);
  color: var(--ink-dim);
}

.flip-ruler-read .fig {
  color: var(--ink-faint);
}

.mini-figs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s2);
  margin-block-start: auto;
  padding-block-start: var(--s3);
  border-block-start: var(--hair) solid var(--rule);
}

.mini-figs dd {
  margin-block-start: 2px;
  color: var(--ink);
  font: 600 var(--t-small) / 1.2 var(--font-mono);
}

/* ── levels ─────────────────────────────────────────────────────────────*/
.levels {
  display: flex;
  flex-direction: column;
  gap: 1px;
  list-style: none;
}

.lvl {
  display: grid;
  grid-template-columns: 78px 62px 52px 1fr;
  align-items: baseline;
  gap: var(--s2);
  padding-block: 5px;
  padding-inline-start: var(--s2);
  border-inline-start: 2px solid transparent;
}

.lvl.call_wall {
  border-inline-start-color: var(--call);
}
.lvl.put_wall {
  border-inline-start-color: var(--put);
}
.lvl.gamma_flip {
  border-inline-start-color: var(--warn);
}
.lvl.pin,
.lvl.peak {
  border-inline-start-color: var(--ink-faint);
}
.lvl.vol_trigger {
  border-inline-start-color: var(--status-proxy);
}

.lvl-name {
  color: var(--ink);
  font-size: var(--t-small);
}

.lvl-price {
  color: var(--ink);
  font: 600 var(--t-small) / 1.1 var(--font-mono);
  text-align: end;
}

.lvl-dist {
  font: 500 var(--t-tiny) / 1.1 var(--font-mono);
  text-align: end;
}

.lvl-dist.above {
  color: var(--long);
}

.lvl-dist.below {
  color: var(--short);
}

.lvl-mean {
  overflow: hidden;
  color: var(--ink-faint);
  font-size: var(--t-tiny);
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── move ───────────────────────────────────────────────────────────────*/
.move {
  color: var(--ink);
  font: 600 calc(var(--t-fig-lg) + 4px) / 1 var(--font-mono);
}

.move-range {
  color: var(--ink-dim);
  font: 500 var(--t-small) / 1.2 var(--font-mono);
}

.odds {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-block-start: auto;
  padding-block-start: var(--s3);
  border-block-start: var(--hair) solid var(--rule);
}

.odds > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s2);
}

.odds dd {
  color: var(--ink);
  font: 600 var(--t-small) / 1.1 var(--font-mono);
}

.odds dd.pos {
  color: var(--call);
}

.odds dd.neg {
  color: var(--put);
}

/* ── where it's pulling ─────────────────────────────────────────────────*/
.target-card {
  border-inline-start: 1px solid var(--unknown);
}

.target-card.bullish_pull {
  border-inline-start-color: var(--long);
}

.target-card.bearish_pull {
  border-inline-start-color: var(--short);
}

.target-lead {
  display: flex;
  align-items: baseline;
  gap: var(--s2);
  flex-wrap: wrap;
}

.pull-label {
  color: var(--ink-faint);
  flex-basis: 100%;
}

.target-card.bullish_pull .pull-label {
  color: var(--long);
}

.target-card.bearish_pull .pull-label {
  color: var(--short);
}

.target-price {
  color: var(--ink);
  font: 600 calc(var(--t-fig-lg) + 4px) / 1 var(--font-mono);
}

.target-dist {
  font: 500 var(--t-fig) / 1 var(--font-mono);
}

.target-why {
  color: var(--ink-faint);
  font-size: var(--t-tiny);
  line-height: 1.4;
}

/* Destinations ranked by the stack's pull score. The bar is the ranking made
   visible, so the strongest magnet is found before any number is read. */
.targets {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-block-start: var(--s2);
  list-style: none;
}

.tgt {
  display: grid;
  grid-template-columns: 56px 46px 1fr auto;
  align-items: center;
  gap: var(--s2);
  font-size: var(--t-tiny);
}

.tgt-price {
  color: var(--ink);
  font: 500 var(--t-small) / 1.1 var(--font-mono);
}

.tgt-dist {
  font-family: var(--font-mono);
  text-align: end;
}

.tgt-bar {
  block-size: 5px;
  border-radius: var(--r-capsule);
  background: var(--panel-hi);
  overflow: hidden;
}

.tgt-fill {
  display: block;
  block-size: 100%;
  border-radius: var(--r-capsule);
}

.tgt-fill.up {
  background: var(--long);
}

.tgt-fill.down {
  background: var(--short);
}

.tgt-name {
  color: var(--ink-faint);
  white-space: nowrap;
}

.confluence {
  margin-block-start: var(--s2);
  color: var(--phosphor);
  font-size: var(--t-tiny);
}

.confluence b {
  font-family: var(--font-mono);
}

.target-em {
  margin-block-start: auto;
  padding-block-start: var(--s2);
  color: var(--ink-faint);
  font-size: var(--t-tiny);
  border-block-start: var(--hair) solid var(--rule);
}

.mass {
  color: var(--text-secondary);
  font-size: var(--t-small);
  line-height: 1.4;
}

.mass .label {
  color: var(--ink-faint);
  margin-inline-end: 4px;
}

.ladder-card {
  gap: var(--s1);
}

.ladder-note {
  color: var(--ink-faint);
  font-size: var(--t-tiny);
}

/* ── flow ───────────────────────────────────────────────────────────────*/
.prem {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
}

.prem-bar {
  display: flex;
  block-size: 8px;
  overflow: hidden;
  border-radius: var(--r-capsule);
  background: var(--panel-hi);
}

.prem-bar i {
  display: block;
  flex-basis: 0;
}

.prem-bar .call {
  background: var(--call);
}

.prem-bar .put {
  background: var(--put);
}

.prem-legend {
  color: var(--ink-faint);
  text-transform: none;
  letter-spacing: 0.02em;
}

.prints {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-block-start: var(--s2);
  list-style: none;
}

.prints li {
  display: grid;
  grid-template-columns: 44px 76px 52px 1fr;
  align-items: baseline;
  gap: var(--s2);
  font-size: var(--t-tiny);
}

.pr-time {
  color: var(--ink-faint);
  font-family: var(--font-mono);
}

.pr-con {
  font: 500 var(--t-small) / 1.1 var(--font-mono);
}

.pr-prem {
  color: var(--ink);
  font-family: var(--font-mono);
  text-align: end;
}

.pr-why {
  color: var(--ink-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── picks ──────────────────────────────────────────────────────────────*/
.picks {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
  list-style: none;
}

.pick {
  display: inline-flex;
  align-items: baseline;
  gap: var(--s2);
  padding: 5px 10px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
  background: var(--panel-wash);
  cursor: pointer;
}

.pick:hover {
  border-color: var(--phosphor-dim);
  background: var(--panel-hi);
}

.pick-sym {
  color: var(--phosphor);
  font: 600 var(--t-small) / 1 var(--font-mono);
}

.pick-el {
  color: var(--ink-faint);
}

/* ── worries ────────────────────────────────────────────────────────────*/
.worries {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  list-style: none;
}

.worry {
  display: grid;
  gap: 2px;
  padding-inline-start: var(--s3);
  border-inline-start: 2px solid var(--ink-faint);
}

.worry.high {
  border-inline-start-color: var(--short);
}

.worry.medium {
  border-inline-start-color: var(--warn);
}

.worry strong {
  color: var(--ink);
  font-size: var(--t-small);
  font-weight: 600;
}

.worry span {
  color: var(--ink-faint);
  font-size: var(--t-tiny);
  line-height: 1.45;
}

/* ── shared ─────────────────────────────────────────────────────────────*/
.empty {
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  padding-block: var(--s3);
  color: var(--ink-faint);
  font-size: var(--t-small);
  line-height: 1.5;
}

.empty.ok {
  color: var(--status-live);
}

.foot {
  color: var(--ink-faint);
  font-size: var(--t-tiny);
}

.sr-only {
  position: absolute;
  inline-size: 1px;
  block-size: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

/* Break where the content stops fitting, not at device presets. The mid row
   carries three dense columns and gives up first. */
@media (max-width: 1180px) {
  .row-bot {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 900px) {
  .row-top,
  .row-mid,
  .row-bot {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 620px) {
  .head {
    flex-direction: column;
    align-items: stretch;
    gap: var(--s3);
  }

  .controls {
    flex-wrap: wrap;
  }

  .sym-input {
    flex: 1 1 auto;
    inline-size: auto;
  }

  .stream {
    grid-template-columns: 72px 1fr 56px 30px;
  }
}
</style>
