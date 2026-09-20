<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type LiveDecisionPayload,
  type LiveDecisionState,
  type MarketRegimePayload,
  type OptionsIntelligence,
  type VpaAnalysisResult,
} from '@/api'
import type { ExecutionGatePayload } from '@/microstructureContracts'
import { useResource } from '@/composables/useResource'
import { createDecisionSources } from '@/decisionSources'
import Panel from '@/components/Panel.vue'
import LoadingState from '@/components/LoadingState.vue'

const route = useRoute()
const router = useRouter()
const POLL_MS = 5_000
const collect = createDecisionSources()

function cleanSymbol(value: unknown): string {
  return (
    String(value || 'SPY')
      .trim()
      .toUpperCase()
      .replace(/[^A-Z0-9.-]/g, '')
      .slice(0, 10) || 'SPY'
  )
}

const symbol = ref(cleanSymbol(route.query.symbol))
const symbolInput = ref(symbol.value)
const activated = ref(false)
const loadingLabel = ref('Reading market data…')

interface DecisionBundle {
  decision: LiveDecisionPayload
  state: LiveDecisionState
}

type SourceName = 'options' | 'regime' | 'microstructure' | 'vpa' | 'execution_gate'

function statusOf(result: PromiseSettledResult<unknown>): 'ready' | 'pending' | 'error' {
  if (result.status === 'fulfilled') return 'ready'
  return result.reason instanceof Error && result.reason.message === 'Source still calculating'
    ? 'pending'
    : 'error'
}

function valueOf<T>(result: PromiseSettledResult<T>): T | null {
  return result.status === 'fulfilled' ? result.value : null
}

async function loadDecision(): Promise<DecisionBundle> {
  const requestedSymbol = symbol.value
  loadingLabel.value = 'Reading options, regime, VPA, and session policy…'
  const [optionsResult, regimeResult, vpaResult, gateResult] = await Promise.allSettled([
    collect(`${requestedSymbol}:options`, () =>
      api.options({ symbol: requestedSymbol, mode: 'live', range: '5d', expiry: 'all' }),
    ),
    collect(`${requestedSymbol}:regime`, () => api.marketRegime(requestedSymbol)),
    collect(`${requestedSymbol}:vpa`, () =>
      api.vpaAnalyze({
        symbol: requestedSymbol,
        timeframe: '1h',
        lookback: 160,
        asset_class: 'equities',
        notes: 'Live TypeSafe decision synthesis; use measured OHLCV only.',
      }),
    ),
    collect(`${requestedSymbol}:gate`, () =>
      api.executionGate(requestedSymbol, { sessionOnly: true }),
    ),
  ])

  const options = valueOf<OptionsIntelligence>(optionsResult)
  const regime = valueOf<MarketRegimePayload>(regimeResult)
  const vpa = valueOf<VpaAnalysisResult>(vpaResult)
  const gate = valueOf<ExecutionGatePayload>(gateResult)
  const summary = options?.summary

  const sourceStatus: Record<SourceName, string> = {
    options: statusOf(optionsResult),
    regime: statusOf(regimeResult),
    microstructure:
      regimeResult.status === 'fulfilled' && optionsResult.status === 'fulfilled'
        ? 'ready'
        : 'error',
    vpa: statusOf(vpaResult),
    execution_gate: statusOf(gateResult),
  }
  if (options && options.mode_resolved !== 'live') {
    sourceStatus.options = options.mode_resolved === 'unavailable' ? 'missing' : 'stale'
    sourceStatus.microstructure = 'stale'
  }
  if (regime && !regime.quality.measurable) sourceStatus.regime = 'missing'
  if (regime && !regime.flow.measured) sourceStatus.microstructure = 'missing'
  if (vpa?.data_status?.analysed === false) sourceStatus.vpa = 'missing'

  const state: LiveDecisionState = {
    symbol: requestedSymbol,
    observed_at: new Date().toISOString(),
    source_status: sourceStatus,
    options: {
      asof: options?.asof_utc,
      feed_age_seconds: options?.freshness.feed_age_seconds ?? options?.freshness.age_seconds,
      activity_lean: summary?.activity_lean,
      signed_flow_imbalance: summary?.signed_flow_imbalance,
      signed_flow_confidence: summary?.signed_flow_confidence,
      pressure_imbalance: options?.pressure?.imbalance,
      gex_regime: summary?.regime,
      net_gex_m: summary?.total_gex_m,
      spot: summary?.spot,
      call_wall: summary?.call_wall,
      put_wall: summary?.put_wall,
      gamma_flip: summary?.gamma_flip,
    },
    regime: {
      asof: regime?.asof_utc,
      primary: regime?.primary,
      confidence: regime?.confidence.score,
      bullish_probability: regime?.probabilities?.bullish,
      bearish_probability: regime?.probabilities?.bearish,
      neutral_probability: regime?.probabilities?.neutral,
      transition_risk: regime?.transition.level,
      trend: regime?.trend.state,
      volatility: regime?.volatility.state,
      flow: regime?.flow.state,
    },
    microstructure: {
      asof: regime?.asof_utc ?? options?.asof_utc,
      measurable: regime?.flow.measured ?? options?.quality.gex_measurable,
      regime: regime?.flow.dealerGammaRegime ?? summary?.regime,
      regime_strength: regime?.confidence.score,
      topography: regime?.structure.state,
      expected_behavior: regime?.explanation.headline,
      dealer_hedging_action: regime?.flow.hedgingPressureDirection,
    },
    vpa: {
      asof: vpa?.bars_meta?.last_bar,
      market_phase: vpa?.market_phase,
      sentiment: vpa?.dominant_sentiment,
      confidence: vpa?.confidence_score,
      bias: vpa?.trade_execution_guide.bias,
      scenario_direction: vpa?.primary_scenario.direction,
      effort_result: vpa?.effort_vs_result_verdict,
      entry_trigger: vpa?.trade_execution_guide.entry_trigger,
      invalidation: vpa?.trade_execution_guide.stop_loss_placement,
    },
    execution_gate: {
      asof: gate?.asof,
      phase: gate?.session.phase,
      may_enter: gate?.session.may_enter ?? false,
      must_be_flat: gate?.session.must_be_flat ?? false,
      reason: gate?.session.reason ?? 'Execution gate unavailable.',
      permitted_setups: gate?.session.permitted_setups ?? [],
    },
  }

  if (symbol.value !== requestedSymbol) throw new Error('Symbol changed during data collection.')
  loadingLabel.value = 'Evaluating the snapshot with TypeSafe…'
  const result = await api.typeSafeLiveDecision(state)
  if (symbol.value !== requestedSymbol) throw new Error('Symbol changed during synthesis.')
  return { state, decision: result }
}

const decisionRes = useResource<DecisionBundle>(loadDecision, {
  intervalMs: POLL_MS,
  immediate: false,
  enabled: () => activated.value,
})

const bundle = computed(() => decisionRes.data.value)
const decision = computed(() => bundle.value?.decision ?? null)
const state = computed(() => bundle.value?.state ?? null)

const actionLabel = computed(() => {
  if (!decision.value) return 'STANDBY'
  return decision.value.action === 'buy'
    ? 'BUY BIAS'
    : decision.value.action === 'sell'
      ? 'SELL BIAS'
      : 'WAIT'
})

const actionTone = computed(() => decision.value?.action ?? 'wait')
const confidencePct = computed(() => Math.round((decision.value?.confidence ?? 0) * 100))
const readyCount = computed(
  () =>
    Object.values(decision.value?.source_status ?? {}).filter((value) => value === 'ready').length,
)
const engineLabel = computed(() =>
  decision.value?.engine.mode === 'typesafe' ? 'TYPESAFE · JEV' : 'LOCAL FALLBACK',
)

function activate(): void {
  activated.value = true
  void decisionRes.refresh({ clear: true })
}

function pause(): void {
  activated.value = false
}

function applySymbol(): void {
  const next = cleanSymbol(symbolInput.value)
  symbolInput.value = next
  if (next === symbol.value) return
  symbol.value = next
  void router.replace({ name: 'decision', query: { symbol: next } })
  if (activated.value) void decisionRes.refresh({ clear: true })
}

watch(
  () => route.query.symbol,
  (next) => {
    const clean = cleanSymbol(Array.isArray(next) ? next[0] : next)
    if (clean !== symbol.value) {
      symbol.value = clean
      symbolInput.value = clean
      if (activated.value) void decisionRes.refresh({ clear: true })
    }
  },
)

function pct(value: number | undefined): string {
  return `${Math.round((value ?? 0) * 100)}%`
}

function scoreLabel(value: number): string {
  if (value >= 3.5) return 'EXTREME'
  if (value >= 2.5) return 'HIGH'
  if (value >= 1.5) return 'MODERATE'
  if (value >= 0.5) return 'LOW'
  return 'NONE'
}

function sourceRead(name: SourceName): string {
  const s = state.value
  if (!s) return 'No snapshot'
  if (name === 'options') {
    return `${String(s.options.activity_lean ?? 'no lean')} · flow ${String(s.options.signed_flow_imbalance ?? '—')}`
  }
  if (name === 'regime') {
    return `${String(s.regime.primary ?? 'unmeasured')} · ${String(s.regime.transition_risk ?? '—')} transition`
  }
  if (name === 'microstructure') {
    return `${String(s.microstructure.regime ?? 'unmeasured')} · ${String(s.microstructure.topography ?? '—')}`
  }
  if (name === 'vpa') {
    return `${String(s.vpa.bias ?? 'no bias')} · ${String(s.vpa.market_phase ?? '—')}`
  }
  return `${String(s.execution_gate.phase ?? 'unknown')} · ${s.execution_gate.may_enter ? 'entries open' : 'entries closed'}`
}

const sourceRows: Array<{ key: SourceName; label: string }> = [
  { key: 'options', label: 'OPTIONS FLOW' },
  { key: 'regime', label: 'MARKET REGIME' },
  { key: 'microstructure', label: 'DEALER BOOK' },
  { key: 'vpa', label: 'VPA' },
  { key: 'execution_gate', label: 'EXECUTION GATE' },
]
</script>

<template>
  <div class="decision-page">
    <header class="decision-head">
      <div>
        <div class="eyebrow fig">LIVE DECISION ENGINE · TYPESAFE SYSTEM ONE</div>
        <h1 class="title">One read. Every lens. Right now.</h1>
        <p class="subtitle">
          Options flow, dealer positioning, market regime, VPA and execution policy reconciled into
          a single posture. No order routing.
        </p>
      </div>
      <form class="symbol-form" @submit.prevent="applySymbol">
        <input v-model="symbolInput" aria-label="Ticker symbol" maxlength="10" spellcheck="false" />
        <button type="submit">LOAD</button>
      </form>
    </header>

    <section v-if="!activated" class="launch-card">
      <div class="launch-orbit" aria-hidden="true"><span>5</span></div>
      <div>
        <span class="launch-kicker fig">PAID LIVE SOURCES · OPERATOR ACTIVATED</span>
        <h2>Start the {{ symbol }} live read</h2>
        <p>
          Activating polls the five source lenses every {{ POLL_MS / 1000 }} seconds and sends one
          compact, parallel judgment batch to TypeSafe. Each read collects sources for up to 2.5
          seconds; slower lenses remain pending until a subsequent refresh.
        </p>
      </div>
      <button class="go-live" type="button" @click="activate">START LIVE READ</button>
    </section>

    <template v-else>
      <div class="live-controls">
        <span class="live-dot" />
        <span class="fig">LIVE · {{ POLL_MS / 1000 }}S LOOP</span>
        <span v-if="decisionRes.fetchedAt.value" class="muted fig">
          UPDATED {{ new Date(decisionRes.fetchedAt.value).toLocaleTimeString() }}
        </span>
        <button type="button" :disabled="decisionRes.loading.value" @click="decisionRes.refresh()">
          {{ decisionRes.loading.value ? 'READING…' : 'REFRESH NOW' }}
        </button>
        <button type="button" class="quiet" @click="pause">PAUSE</button>
      </div>

      <LoadingState v-if="decisionRes.loading.value && !bundle" :label="loadingLabel" />
      <div v-if="decisionRes.error.value" class="fault">
        LIVE READ DEGRADED · {{ decisionRes.error.value }}
      </div>

      <template v-if="decision">
        <section class="verdict-card" :class="`tone-${actionTone}`">
          <div class="verdict-main">
            <div class="verdict-topline">
              <span class="engine-badge">{{ engineLabel }}</span>
              <span class="fig">{{ readyCount }}/5 SOURCES READY</span>
              <span class="fig">{{ decision.engine.latency_ms }}MS SYNTHESIS</span>
            </div>
            <div class="symbol-lockup fig">{{ decision.symbol }}</div>
            <div class="action fig">{{ actionLabel }}</div>
            <p class="action-sub">
              DIRECTIONAL LEAN · {{ (decision.lean ?? 'unknown').toUpperCase() }}
            </p>
            <p class="action-sub">
              {{ decision.setup.replace(/_/g, ' ').toUpperCase() }} · {{ confidencePct }}% model
              confidence
            </p>
          </div>

          <div class="probability-stack" aria-label="Action probability distribution">
            <div v-for="key in ['buy', 'wait', 'sell'] as const" :key="key" class="prob-row">
              <div class="prob-head fig">
                <span>{{ key }}</span
                ><span>{{ pct(decision.probabilities[key]) }}</span>
              </div>
              <div class="prob-track">
                <span :class="key" :style="{ width: pct(decision.probabilities[key]) }" />
              </div>
            </div>
            <p v-if="decision.engine.mode !== 'typesafe'" class="fallback-note">
              Add <code>TYPESAFE_API_KEY</code> to <code>.env</code> for Jev judgments. This read is
              the conservative local fallback.
            </p>
          </div>
        </section>

        <div class="metric-grid">
          <article>
            <span class="metric-label fig">ALIGNMENT</span>
            <strong>{{ decision.alignment.score.toFixed(1) }}<small>/4</small></strong>
            <span>{{ scoreLabel(decision.alignment.score) }}</span>
          </article>
          <article>
            <span class="metric-label fig">TIMING</span>
            <strong>{{ decision.timing.score.toFixed(1) }}<small>/4</small></strong>
            <span>{{ scoreLabel(decision.timing.score) }}</span>
          </article>
          <article :class="{ danger: decision.risk.score >= 3 }">
            <span class="metric-label fig">EXECUTION RISK</span>
            <strong>{{ decision.risk.score.toFixed(1) }}<small>/4</small></strong>
            <span>{{ scoreLabel(decision.risk.score) }}</span>
          </article>
        </div>

        <div class="content-grid">
          <Panel label="WHY THIS READ" index="01" :meta="decision.action.toUpperCase()">
            <ul class="reason-list">
              <li v-for="reason in decision.reasons" :key="reason">{{ reason }}</li>
            </ul>
          </Panel>
          <Panel label="POLICY BLOCKERS" index="02" :meta="`${decision.blockers.length} ACTIVE`">
            <ul v-if="decision.blockers.length" class="blocker-list">
              <li v-for="blocker in decision.blockers" :key="blocker">{{ blocker }}</li>
            </ul>
            <p v-else class="all-clear">No deterministic blocker is active.</p>
          </Panel>
        </div>

        <Panel
          label="SOURCE TAPE"
          index="03"
          :meta="`OBSERVED ${new Date(decision.observed_at).toLocaleTimeString()}`"
        >
          <div class="source-grid">
            <article v-for="source in sourceRows" :key="source.key">
              <div class="source-head">
                <span class="fig">{{ source.label }}</span>
                <span class="status" :class="decision.source_status[source.key]">
                  {{ decision.source_status[source.key] ?? 'missing' }}
                </span>
              </div>
              <p>{{ sourceRead(source.key) }}</p>
            </article>
          </div>
        </Panel>

        <footer class="decision-footer fig">
          {{ decision.notice }} · confidence is model certainty, not win probability · final policy
          stays in code
        </footer>
      </template>
    </template>
  </div>
</template>

<style scoped>
.decision-page {
  max-width: 1500px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}
.decision-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s4);
  padding: var(--s4) 0 var(--s3);
  border-bottom: var(--hair) solid var(--rule);
}
.eyebrow,
.metric-label {
  color: var(--phosphor);
  font-size: var(--t-nano);
  letter-spacing: 0.12em;
}
.title {
  margin: var(--s1) 0;
  font-size: clamp(2rem, 4vw, 4.8rem);
  line-height: 0.96;
  max-width: 900px;
  letter-spacing: -0.045em;
}
.subtitle {
  color: var(--ink-muted);
  max-width: 780px;
  margin: 0;
}
.symbol-form {
  display: flex;
  min-width: 250px;
}
.symbol-form input {
  width: 135px;
  background: var(--panel);
  color: var(--ink);
  border: var(--hair) solid var(--rule);
  border-right: 0;
  padding: 12px 14px;
  font: 700 1.1rem var(--font-data);
  text-transform: uppercase;
}
.symbol-form button,
.live-controls button {
  border: var(--hair) solid var(--rule);
  background: var(--panel-hi);
  color: var(--ink);
  padding: 0 16px;
  font: 700 var(--t-micro) var(--font-data);
  cursor: pointer;
}
.launch-card {
  min-height: 380px;
  border: var(--hair) solid var(--rule);
  background:
    radial-gradient(
      circle at 15% 50%,
      color-mix(in srgb, var(--phosphor) 13%, transparent),
      transparent 34%
    ),
    var(--panel);
  display: grid;
  grid-template-columns: 160px 1fr auto;
  align-items: center;
  gap: var(--s5);
  padding: clamp(24px, 5vw, 72px);
}
.launch-orbit {
  width: 132px;
  aspect-ratio: 1;
  border: var(--hair) solid var(--phosphor);
  border-radius: 50%;
  display: grid;
  place-items: center;
  box-shadow: 0 0 50px color-mix(in srgb, var(--phosphor) 18%, transparent);
}
.launch-orbit span {
  font: 700 3rem var(--font-data);
  color: var(--phosphor);
}
.launch-card h2 {
  margin: 8px 0;
  font-size: clamp(1.8rem, 3vw, 3.3rem);
}
.launch-card p {
  color: var(--ink-muted);
  max-width: 650px;
}
.launch-kicker {
  color: var(--ink-faint);
  letter-spacing: 0.1em;
}
.go-live {
  padding: 16px 24px;
  border: 0;
  background: var(--phosphor);
  color: var(--void);
  font: 800 var(--t-small) var(--font-data);
  cursor: pointer;
  box-shadow: 0 0 30px color-mix(in srgb, var(--phosphor) 20%, transparent);
}
.live-controls {
  display: flex;
  align-items: center;
  gap: var(--s2);
  min-height: 38px;
}
.live-controls button {
  padding: 8px 12px;
  margin-left: auto;
}
.live-controls button + button {
  margin-left: 0;
}
.live-controls .quiet {
  background: transparent;
  color: var(--ink-faint);
}
.live-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--long);
  box-shadow: 0 0 10px var(--long);
}
.muted {
  color: var(--ink-faint);
}
.fault {
  border-left: 3px solid var(--short);
  background: var(--put-wash);
  color: var(--short);
  padding: var(--s2) var(--s3);
  font: var(--t-micro) var(--font-data);
}
.verdict-card {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.75fr);
  gap: var(--s5);
  padding: clamp(24px, 5vw, 64px);
  border: var(--hair) solid var(--rule);
  background: var(--panel);
  position: relative;
  overflow: hidden;
}
.verdict-card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 5px;
  background: var(--ink-faint);
}
.verdict-card.tone-buy::before {
  background: var(--long);
}
.verdict-card.tone-sell::before {
  background: var(--short);
}
.verdict-topline {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
  color: var(--ink-faint);
  font-size: var(--t-nano);
}
.engine-badge {
  color: var(--phosphor);
  border: var(--hair) solid color-mix(in srgb, var(--phosphor) 40%, transparent);
  padding: 2px 7px;
  font: 700 var(--t-nano) var(--font-data);
}
.symbol-lockup {
  margin-top: var(--s3);
  color: var(--ink-faint);
  font-size: var(--t-small);
  letter-spacing: 0.18em;
}
.action {
  font-size: clamp(4rem, 10vw, 9rem);
  line-height: 0.86;
  letter-spacing: -0.07em;
  margin: 12px 0 18px;
}
.tone-buy .action {
  color: var(--long);
}
.tone-sell .action {
  color: var(--short);
}
.action-sub {
  color: var(--ink-muted);
  margin: 0;
  letter-spacing: 0.05em;
}
.probability-stack {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--s3);
}
.prob-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
  text-transform: uppercase;
  color: var(--ink-muted);
}
.prob-track {
  height: 8px;
  background: var(--panel-hi);
  overflow: hidden;
}
.prob-track span {
  height: 100%;
  display: block;
  background: var(--ink-faint);
}
.prob-track .buy {
  background: var(--long);
}
.prob-track .sell {
  background: var(--short);
}
.fallback-note {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  line-height: 1.5;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--s3);
}
.metric-grid article {
  border: var(--hair) solid var(--rule);
  background: var(--panel);
  padding: var(--s3);
  display: grid;
  gap: 4px;
}
.metric-grid strong {
  font: 700 clamp(2rem, 4vw, 4rem) var(--font-data);
}
.metric-grid small {
  color: var(--ink-faint);
  font-size: 0.35em;
}
.metric-grid article > span:last-child {
  color: var(--ink-muted);
  font: var(--t-micro) var(--font-data);
}
.metric-grid article.danger strong,
.metric-grid article.danger > span:last-child {
  color: var(--short);
}
.content-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s3);
}
.reason-list,
.blocker-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--s2);
}
.reason-list li,
.blocker-list li {
  padding: 10px 12px;
  border-left: 2px solid var(--phosphor);
  background: var(--panel);
}
.blocker-list li {
  border-left-color: var(--short);
}
.all-clear {
  color: var(--long);
}
.source-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--s2);
}
.source-grid article {
  padding: var(--s2);
  border: var(--hair) solid var(--rule-faint);
  background: var(--panel);
  min-height: 100px;
}
.source-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: var(--t-nano);
}
.status {
  border-radius: 999px;
  padding: 2px 7px;
  color: var(--ink-faint);
  background: var(--panel-hi);
  text-transform: uppercase;
  font: var(--t-nano) var(--font-data);
}
.status.ready {
  color: var(--long);
  background: var(--call-wash);
}
.status.error,
.status.missing {
  color: var(--short);
  background: var(--put-wash);
}
.source-grid p {
  color: var(--ink-muted);
  font-size: var(--t-micro);
  line-height: 1.45;
}
.decision-footer {
  color: var(--ink-faint);
  text-transform: uppercase;
  font-size: var(--t-nano);
  text-align: center;
  padding: var(--s2);
}
@media (max-width: 980px) {
  .decision-head,
  .launch-card {
    align-items: stretch;
  }
  .decision-head {
    flex-direction: column;
  }
  .launch-card {
    grid-template-columns: 1fr;
  }
  .launch-orbit {
    width: 90px;
  }
  .verdict-card,
  .content-grid {
    grid-template-columns: 1fr;
  }
  .source-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 620px) {
  .metric-grid,
  .source-grid {
    grid-template-columns: 1fr;
  }
  .live-controls {
    flex-wrap: wrap;
  }
  .live-controls button {
    margin-left: 0;
  }
}
</style>
