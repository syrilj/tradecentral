<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type LiveDecisionPayload,
  type LiveDecisionState,
  type KronosEvidencePayload,
  type LiveDecisionForecastEvidence,
  type MarketRegimePayload,
  type OptionsIntelligence,
  type QuotesPayload,
  type VpaAnalysisResult,
} from '@/api'
import type { ExecutionGatePayload } from '@/microstructureContracts'
import { useResource } from '@/composables/useResource'
import { createDecisionSources } from '@/decisionSources'
import {
  buildDecisionPriceContext,
  type DecisionPriceContext as DecisionPriceContextState,
} from '@/decisionPriceContext'
import Panel from '@/components/Panel.vue'
import DecisionBacktestPanel from '@/components/DecisionBacktestPanel.vue'
import DecisionPriceContext from '@/components/DecisionPriceContext.vue'
import DecisionSkeletonLoader, {
  type DecisionStreamState,
} from '@/components/DecisionSkeletonLoader.vue'

const route = useRoute()
const router = useRouter()
const POLL_MS = 5_000
const collect = createDecisionSources(20_000)

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
const activated = ref(true)
const sessionLocked = ref(false)
const previousDecision = ref<LiveDecisionState['previous_decision']>(null)
const loadingLabel = ref('Reading market data…')
const isCalibrating = ref(false)
const viewMode = computed<'live' | 'backtest'>(() =>
  route.query.tab === 'backtest' ? 'backtest' : 'live',
)

const QUICK_SYMBOLS = ['SPY', 'QQQ', 'NVDA', 'AAPL', 'TSLA', 'MSFT', 'IWM'] as const

function selectSymbol(sym: string): void {
  symbolInput.value = sym
  applySymbol()
}

const streamsState = ref<DecisionStreamState[]>([
  {
    key: 'options',
    label: 'OPTIONS FLOW & GEX',
    loading: true,
    status: 'in-flight',
    description: 'Pricing live option contracts & GEX profile…',
  },
  {
    key: 'regime',
    label: 'MARKET REGIME',
    loading: true,
    status: 'in-flight',
    description: 'Synthesizing 5 regime models & transition risk…',
  },
  {
    key: 'microstructure',
    label: 'DEALER BOOK',
    loading: true,
    status: 'in-flight',
    description: 'Mapping hedging pressure & gamma walls…',
  },
  {
    key: 'vpa',
    label: 'VOLUME PRICE ANALYSIS',
    loading: true,
    status: 'in-flight',
    description: 'Evaluating volume-price spread & market phase…',
  },
  {
    key: 'forecast',
    label: 'MODEL FORECAST',
    loading: true,
    status: 'in-flight',
    description: 'Retrieving Kronos horizon evidence…',
  },
  {
    key: 'execution_gate',
    label: 'EXECUTION GATE',
    loading: true,
    status: 'in-flight',
    description: 'Checking session timing & risk limits…',
  },
])

function resetStreams(sym: string): void {
  streamsState.value = [
    {
      key: 'options',
      label: 'OPTIONS FLOW & GEX',
      loading: true,
      status: 'in-flight',
      description: `Pricing ${sym} option contracts & GEX profile…`,
    },
    {
      key: 'regime',
      label: 'MARKET REGIME',
      loading: true,
      status: 'in-flight',
      description: `Evaluating ${sym} 5-model consensus & transition risk…`,
    },
    {
      key: 'microstructure',
      label: 'DEALER BOOK',
      loading: true,
      status: 'in-flight',
      description: `Mapping ${sym} dealer hedging & gamma walls…`,
    },
    {
      key: 'vpa',
      label: 'VOLUME PRICE ANALYSIS',
      loading: true,
      status: 'in-flight',
      description: `Analyzing ${sym} volume-price spread & accumulation phase…`,
    },
    {
      key: 'forecast',
      label: 'MODEL FORECAST',
      loading: true,
      status: 'in-flight',
      description: `Retrieving ${sym} Kronos horizon forecast…`,
    },
    {
      key: 'execution_gate',
      label: 'EXECUTION GATE',
      loading: true,
      status: 'in-flight',
      description: `Verifying ${sym} session timing & risk limits…`,
    },
  ]
}

function updateStream(key: string, loading: boolean, status: string, description: string): void {
  const item = streamsState.value.find((s) => s.key === key)
  if (item) {
    item.loading = loading
    item.status = status
    item.description = description
  }
}

const completedStreamsCount = computed(() => {
  return streamsState.value.filter((s) => !s.loading).length
})

interface DecisionBundle {
  decision: LiveDecisionPayload
  state: LiveDecisionState
  priceContext: DecisionPriceContextState
  forwardScenario: ForwardScenario | null
  forecastSourceReason: string | null
}

interface ForwardScenario {
  direction: string
  likelyMove: string
  horizon: string
  targetZone: string
  supportPct: number | null
  rationale: string
  asof: string | null
}

type SourceName = 'options' | 'regime' | 'microstructure' | 'vpa' | 'forecast' | 'execution_gate'

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
  resetStreams(requestedSymbol)
  isCalibrating.value = true
  loadingLabel.value = 'Reading options, regime, VPA, forecast, and session policy…'

  const quotePromise = collect(`${requestedSymbol}:quote`, () => api.quotes([requestedSymbol]))

  const optionsPromise = collect(`${requestedSymbol}:options`, () =>
    api.options({ symbol: requestedSymbol, mode: 'live', range: '5d', expiry: 'all' }),
  ).then(
    (res) => {
      const isReady = res.mode_resolved === 'live' || Boolean(res.summary?.regime)
      updateStream(
        'options',
        false,
        isReady ? 'ready' : res.mode_resolved || 'missing',
        isReady ? 'Option contracts priced & GEX profile calibrated' : 'Options mode unavailable',
      )
      return res
    },
    (err) => {
      updateStream('options', false, 'error', 'Options provider offline')
      throw err
    },
  )

  const regimePromise = collect(`${requestedSymbol}:regime`, () =>
    api.marketRegime(requestedSymbol),
  ).then(
    (res) => {
      const isReady = res.quality?.measurable ?? true
      updateStream(
        'regime',
        false,
        isReady ? 'ready' : 'missing',
        isReady ? '5-model regime consensus reached' : 'Regime unmeasurable',
      )
      updateStream(
        'microstructure',
        false,
        isReady ? 'ready' : 'missing',
        isReady ? 'Dealer hedging pressure & walls mapped' : 'Microstructure unmeasured',
      )
      return res
    },
    (err) => {
      updateStream('regime', false, 'error', 'Regime models offline')
      updateStream('microstructure', false, 'error', 'Dealer book unmeasured')
      throw err
    },
  )

  const vpaPromise = collect(`${requestedSymbol}:vpa`, () =>
    api.vpaAnalyze({
      symbol: requestedSymbol,
      timeframe: '1h',
      lookback: 160,
      asset_class: 'equities',
      notes: 'Live TypeSafe decision synthesis; use measured OHLCV only.',
    }),
  ).then(
    (res) => {
      const isReady = res?.data_status?.analysed !== false
      updateStream(
        'vpa',
        false,
        isReady ? 'ready' : 'missing',
        isReady
          ? `VPA calibrated · ${res?.dominant_sentiment ?? 'markup phase'}`
          : 'VPA unanalysed',
      )
      return res
    },
    (err) => {
      updateStream('vpa', false, 'error', 'VPA analysis offline')
      throw err
    },
  )

  const gatePromise = collect(`${requestedSymbol}:gate`, () =>
    api.executionGate(requestedSymbol, { sessionOnly: true }),
  ).then(
    (res) => {
      updateStream(
        'execution_gate',
        false,
        'ready',
        `Session phase ${res?.session?.phase ?? 'verified'} · entries ${res?.session?.may_enter ? 'open' : 'closed'}`,
      )
      return res
    },
    (err) => {
      updateStream('execution_gate', false, 'error', 'Execution gate offline')
      throw err
    },
  )

  const forecastPromise = collect(`${requestedSymbol}:forecast`, () =>
    api.kronosEvidence(requestedSymbol),
  ).then(
    (res) => {
      const status = res?.status ?? 'missing'
      updateStream(
        'forecast',
        false,
        status,
        res?.evidence
          ? 'Kronos horizon evidence retrieved'
          : 'Kronos missing (VPA fallback active)',
      )
      return res
    },
    (err) => {
      updateStream('forecast', false, 'missing', 'Kronos missing (VPA fallback active)')
      throw err
    },
  )

  try {
    const [quoteResult, optionsResult, regimeResult, vpaResult, gateResult, forecastResult] =
      await Promise.allSettled([
        quotePromise,
        optionsPromise,
        regimePromise,
        vpaPromise,
        gatePromise,
        forecastPromise,
      ])

    const quotes = valueOf<QuotesPayload>(quoteResult)
    const quote = quotes?.rows.find((row) => row.symbol === requestedSymbol) ?? null
    const options = valueOf<OptionsIntelligence>(optionsResult)
    const regime = valueOf<MarketRegimePayload>(regimeResult)
    const vpa = valueOf<VpaAnalysisResult>(vpaResult)
    const gate = valueOf<ExecutionGatePayload>(gateResult)
    const forecast = valueOf<KronosEvidencePayload>(forecastResult)
    const forecastEvidence = forecast?.evidence
    const summary = options?.summary

    const sourceStatus: Record<SourceName, string> = {
      options: statusOf(optionsResult),
      regime: statusOf(regimeResult),
      microstructure:
        regimeResult.status === 'fulfilled' && optionsResult.status === 'fulfilled'
          ? 'ready'
          : 'error',
      vpa: statusOf(vpaResult),
      forecast: forecast?.status ?? statusOf(forecastResult),
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
      forecast: {
        source: forecastEvidence?.source ?? null,
        asof_utc: forecastEvidence?.asof_utc ?? null,
        direction: forecastEvidence?.direction ?? null,
        horizon: forecastEvidence?.forecast.horizon ?? null,
        point_pct: forecastEvidence?.forecast.point_pct ?? null,
        interval_80: forecastEvidence?.forecast.interval_80 ?? null,
        confidence_kind: forecastEvidence?.research_confidence.kind ?? null,
        confidence_score: forecastEvidence?.research_confidence.score ?? null,
        confidence_label: forecastEvidence?.research_confidence.label ?? null,
        selective_actionable: forecastEvidence?.research_confidence.selective_actionable ?? false,
        provenance: forecastEvidence?.provenance ?? {},
      },
      previous_decision: previousDecision.value,
    }

    if (symbol.value !== requestedSymbol) throw new Error('Symbol changed during data collection.')
    loadingLabel.value = 'Evaluating the snapshot with TypeSafe…'
    const result = await api.typeSafeLiveDecision(state)
    if (symbol.value !== requestedSymbol) throw new Error('Symbol changed during synthesis.')
    previousDecision.value = {
      action: result.action,
      consensus_score: result.brain?.consensus_score ?? 0,
      decided_at: result.asof_utc,
    }
    if (
      state.source_status.execution_gate === 'ready' &&
      (state.execution_gate.must_be_flat === true || state.execution_gate.may_enter !== true)
    ) {
      sessionLocked.value = true
    }
    return {
      state,
      decision: result,
      priceContext: buildDecisionPriceContext({ symbol: requestedSymbol, quote, options, vpa }),
      forwardScenario:
        vpa && sourceStatus.vpa === 'ready'
          ? {
              direction: vpa.primary_scenario.direction,
              likelyMove: vpa.primary_scenario.likely_move,
              horizon: vpa.primary_scenario.expected_horizon,
              targetZone: vpa.primary_scenario.target_zone,
              supportPct: vpa.primary_scenario.probability_pct,
              rationale: vpa.primary_scenario.rationale,
              asof: vpa.bars_meta?.last_bar ?? null,
            }
          : null,
      forecastSourceReason: forecast?.reason ?? null,
    }
  } finally {
    isCalibrating.value = false
  }
}

const decisionRes = useResource<DecisionBundle>(loadDecision, {
  intervalMs: POLL_MS,
  immediate: true,
  enabled: () => activated.value && viewMode.value === 'live' && !sessionLocked.value,
})

const bundle = computed(() => decisionRes.data.value)
const decision = computed(() => bundle.value?.decision ?? null)
const state = computed(() => bundle.value?.state ?? null)
const priceContext = computed(() => bundle.value?.priceContext ?? null)
const forwardScenario = computed(() => bundle.value?.forwardScenario ?? null)
const forecastEvidence = computed<LiveDecisionForecastEvidence | null>(
  () => decision.value?.forecast_evidence ?? null,
)
const forecastStatus = computed(
  () =>
    forecastEvidence.value?.status ??
    decision.value?.source_status.forecast ??
    state.value?.source_status.forecast ??
    'missing',
)
const forecastAvailable = computed(
  () => forecastEvidence.value?.available === true && forecastStatus.value === 'ready',
)
const forecastFallbackAvailable = computed(
  () => !forecastAvailable.value && forwardScenario.value !== null,
)
const forecastUnavailableText = computed(() => {
  if (bundle.value?.forecastSourceReason === 'kronos_same_session_artifact_missing') {
    return 'Forecast unavailable · no same-session Kronos run exists for this symbol.'
  }
  const reason = forecastEvidence.value?.reason
  return reason
    ? `Forecast unavailable · ${forecastStatus.value} · ${reason}`
    : `Forecast unavailable · ${forecastStatus.value} · no advisory evidence available for this read.`
})
const forecastAsOf = computed(
  () =>
    (forecastAvailable.value
      ? (forecastEvidence.value?.asof_utc ?? state.value?.forecast.asof_utc)
      : forwardScenario.value?.asof) ?? null,
)
const forecastProvenance = computed(() => {
  if (forecastFallbackAvailable.value) return 'Measured OHLCV · VPA forward scenario'
  const provenance = forecastEvidence.value?.provenance ?? state.value?.forecast.provenance
  const rawSource = provenance?.raw_source
  return typeof rawSource === 'string'
    ? rawSource
    : (forecastEvidence.value?.source ?? state.value?.forecast.source ?? 'Unavailable')
})

const decisionLensKeys = ['options', 'regime', 'microstructure', 'vpa'] as const
const readyCount = computed(
  () => decisionLensKeys.filter((key) => decision.value?.source_status[key] === 'ready').length,
)

const modelRead = computed(() => decision.value?.decision_model ?? null)

const actionLabel = computed(() => {
  if (readyCount.value < 3) return 'STANDBY'
  if (decision.value?.action === 'buy') return 'BUY'
  if (decision.value?.action === 'sell') return 'SELL'
  return 'STANDBY'
})

const actionTone = computed(() => {
  if (readyCount.value < 3) return 'standby'
  if (decision.value?.action === 'sell') return 'sell'
  if (decision.value?.action === 'buy') return 'buy'
  return 'standby'
})
const confidencePct = computed(() => {
  const value = decision.value?.confidence
  if (value == null || !Number.isFinite(value)) return null
  return Math.round(value * 100)
})
const priceAction = computed((): 'buy' | 'sell' => {
  return decision.value?.action === 'sell' ? 'sell' : 'buy'
})

const clampedConsensus = computed(() => {
  const score = decision.value?.brain?.consensus_score ?? 0
  return Math.max(-1, Math.min(1, score))
})

const meterPointerLeft = computed(() => `${50 + clampedConsensus.value * 50}%`)

const meterFillStyle = computed(() => {
  const score = clampedConsensus.value
  const widthPct = Math.abs(score) * 50
  return score >= 0
    ? { left: '50%', width: `${widthPct}%` }
    : { left: `${50 - widthPct}%`, width: `${widthPct}%` }
})
const showRiskAssessment = computed(() => {
  const current = decision.value
  if (!current) return false
  return (
    Boolean(current.risk_assessment?.keep_out) ||
    current.blockers.length > 0 ||
    current.risk.score >= 3 ||
    (current.risk_assessment?.reasons?.length ?? 0) > 0
  )
})
const riskReasons = computed(() => {
  const current = decision.value
  if (!current) return []
  const assessed = current.risk_assessment?.reasons?.filter(Boolean) ?? []
  if (assessed.length) return assessed
  if (current.blockers.length) return current.blockers
  if (current.risk.score >= 3) {
    return [
      current.risk_assessment?.label ||
        `Execution risk is ${scoreLabel(current.risk.score).toLowerCase()}.`,
    ]
  }
  return []
})
const engineLabel = computed(() =>
  decision.value?.engine.mode === 'typesafe' ? 'TYPESAFE · JEV' : 'LOCAL FALLBACK',
)

function activate(): void {
  activated.value = true
  sessionLocked.value = false
  void decisionRes.refresh({ clear: true })
}

function pause(): void {
  activated.value = false
}

function switchMode(mode: 'live' | 'backtest'): void {
  void router.replace({
    name: 'decision',
    query:
      mode === 'backtest' ? { symbol: symbol.value, tab: 'backtest' } : { symbol: symbol.value },
  })
}

function applySymbol(): void {
  const next = cleanSymbol(symbolInput.value)
  symbolInput.value = next
  if (next === symbol.value) return
  sessionLocked.value = false
  previousDecision.value = null
  symbol.value = next
  void router.replace({ name: 'decision', query: { symbol: next } })
  if (activated.value) void decisionRes.refresh({ clear: true })
}

watch(
  () => route.query.symbol,
  (next) => {
    const clean = cleanSymbol(Array.isArray(next) ? next[0] : next)
    if (clean !== symbol.value) {
      sessionLocked.value = false
      previousDecision.value = null
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
  if (name === 'forecast') {
    const status = s.source_status.forecast ?? 'missing'
    if (status !== 'ready') {
      return forwardScenario.value
        ? `Kronos ${status} · VPA fallback active`
        : `Unavailable · ${status}`
    }
    const source = s.forecast.source ?? 'Kronos'
    const horizon = s.forecast.horizon?.replace(/[_-]+/g, ' ') ?? 'horizon unavailable'
    return `${source} · ${horizon}`
  }
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
  { key: 'forecast', label: 'MODEL FORECAST' },
  { key: 'execution_gate', label: 'EXECUTION GATE' },
]

function formatForecastPct(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

function formatForecastRange(interval: number[]): string {
  return interval.map((value) => value.toLocaleString()).join('–')
}

function formatForecastHorizon(horizon: string): string {
  return horizon.replace(/[_-]+/g, ' ').toUpperCase()
}

function modelLabel(key: string): string {
  switch (key) {
    case 'options_flow':
      return 'OPTIONS FLOW & GEX'
    case 'regime':
      return 'MARKET REGIME'
    case 'microstructure':
      return 'DEALER BOOK'
    case 'vpa':
      return 'VOLUME PRICE ANALYSIS'
    default:
      return String(key).toUpperCase()
  }
}
</script>

<template>
  <div class="decision-page">
    <header class="decision-head">
      <div>
        <div class="eyebrow fig">
          {{
            viewMode === 'live'
              ? 'LIVE DECISION ENGINE · TYPESAFE SYSTEM ONE'
              : 'DECISION RELIABILITY LAB · SEALED OOS'
          }}
        </div>
        <h1 class="title">
          {{
            viewMode === 'live'
              ? 'One read. Every lens. Right now.'
              : 'Trust is earned on unseen sessions.'
          }}
        </h1>
        <p v-if="viewMode === 'live'" class="subtitle">
          The decision model uses the same as-of rule as the backtest. It buys, sells, or abstains.
          TypeSafe remains the narrative. No order routing.
        </p>
        <p v-else class="subtitle">
          A causal decision tree trained before last week, filled on the next open, charged costs,
          and allowed to abstain when its confidence is indistinguishable from chance.
        </p>
      </div>
      <div v-if="viewMode === 'live'" class="symbol-panel">
        <div class="quick-chips" aria-label="Quick symbols">
          <button
            v-for="sym in QUICK_SYMBOLS"
            :key="sym"
            type="button"
            class="chip-btn fig"
            :class="{ active: symbol === sym }"
            @click="selectSymbol(sym)"
          >
            {{ sym }}
          </button>
        </div>
        <form class="symbol-form" @submit.prevent="applySymbol">
          <input
            v-model="symbolInput"
            aria-label="Ticker symbol"
            maxlength="10"
            spellcheck="false"
          />
          <button type="submit">LOAD</button>
        </form>
      </div>
    </header>

    <nav class="decision-modes" aria-label="Decision workspace modes">
      <button type="button" :class="{ active: viewMode === 'live' }" @click="switchMode('live')">
        <span class="fig">01</span> LIVE READ
      </button>
      <button
        type="button"
        :class="{ active: viewMode === 'backtest' }"
        @click="switchMode('backtest')"
      >
        <span class="fig">02</span> OOS BACKTEST
      </button>
    </nav>

    <DecisionBacktestPanel v-if="viewMode === 'backtest'" />

    <template v-else>
      <section v-if="!activated && !bundle" class="launch-card">
        <div class="launch-orbit" aria-hidden="true">
          <span>{{ sourceRows.length }}</span>
        </div>
        <div>
          <span class="launch-kicker fig">LIVE SOURCE LENSES · OPERATOR ACTIVATED</span>
          <h2>Start the {{ symbol }} live read</h2>
          <p>
            Activating polls {{ sourceRows.length }} source lenses every
            {{ POLL_MS / 1000 }} seconds and sends one compact, parallel judgment batch to TypeSafe.
            Each read collects sources for up to 2.5 seconds; slower lenses remain pending until a
            subsequent refresh.
          </p>
        </div>
        <button class="go-live" type="button" @click="activate">START LIVE READ</button>
      </section>

      <template v-else>
        <div class="live-controls">
          <span class="live-dot" :class="{ paused: !activated }" />
          <span class="fig">{{
            sessionLocked
              ? 'SESSION CLOSED · READ LOCKED'
              : activated
                ? `LIVE · ${POLL_MS / 1000}S LOOP`
                : 'PAUSED · READ FROZEN'
          }}</span>
          <span v-if="decisionRes.fetchedAt.value" class="muted fig">
            UPDATED {{ new Date(decisionRes.fetchedAt.value).toLocaleTimeString() }}
          </span>
          <button
            type="button"
            :disabled="decisionRes.loading.value"
            @click="decisionRes.refresh({ clear: true })"
          >
            {{ decisionRes.loading.value ? 'READING…' : 'REFRESH NOW' }}
          </button>
          <button v-if="activated" type="button" class="quiet" @click="pause">PAUSE</button>
          <button v-else type="button" class="quiet resume-btn" @click="activate">RESUME</button>
        </div>

        <DecisionSkeletonLoader
          v-if="(decisionRes.loading.value && !bundle) || (isCalibrating && !bundle)"
          :symbol="symbol"
          :streams="streamsState"
          :completed-count="completedStreamsCount"
          :total-count="streamsState.length"
        />
        <div v-if="decisionRes.error.value && !bundle" class="fault">
          LIVE READ DEGRADED · {{ decisionRes.error.value }}
        </div>

        <template v-if="decision && bundle">
          <section class="verdict-card" :class="`tone-${actionTone}`">
            <div class="verdict-main">
              <div class="verdict-topline">
                <span class="engine-badge">{{ engineLabel }}</span>
                <span
                  v-if="decision.brain"
                  class="brain-pill fig"
                  :class="decision.brain.confluence.toLowerCase()"
                >
                  BRAIN: {{ decision.brain.confluence }}
                </span>
                <span
                  v-if="modelRead"
                  class="fig model-gate-pill"
                  :class="{ qualified: modelRead.trade, filtered: !modelRead.trade }"
                >
                  DECISION TREE:
                  {{
                    (modelRead.trade ? (modelRead.action ?? 'STANDBY') : 'ABSTAIN').toUpperCase()
                  }}
                  ·
                  {{ modelRead.trade ? 'QUALIFIED' : 'FILTERED (HOLD)' }}
                </span>
                <span class="fig">{{ readyCount }}/4 DECISION LENSES READY</span>
                <span class="fig">{{ decision.engine.latency_ms }}MS SYNTHESIS</span>
              </div>
              <div class="symbol-lockup fig">{{ decision.symbol }}</div>
              <div class="action fig">{{ actionLabel }}</div>
              <p v-if="readyCount < 3" class="action-sub">
                Insufficient lenses ready ({{ readyCount }}/4) · operating in cautious standby
                posture
              </p>
              <p v-else-if="confidencePct != null" class="action-sub">
                {{ confidencePct }}% model certainty · not win probability
              </p>
              <p v-else class="action-sub">Model confidence unavailable · not a trade</p>
              <p class="action-sub">
                LEAN {{ (decision.lean ?? 'unknown').toUpperCase() }} ·
                {{ decision.setup.replace(/_/g, ' ').toUpperCase() }}
              </p>
              <p
                class="execution-posture fig"
                :class="{ 'stand-down': decision.risk_assessment?.keep_out }"
                aria-label="Execution posture"
              >
                <template v-if="decision.risk_assessment?.keep_out">
                  EXECUTION POSTURE · STAND DOWN
                </template>
                <template v-else>DECISION SUPPORT · NO ORDER AUTHORIZED</template>
              </p>
            </div>

            <div class="probability-stack" aria-label="TypeSafe narrative probabilities">
              <div v-for="key in ['buy', 'sell'] as const" :key="key" class="prob-row">
                <div class="prob-head fig">
                  <span>{{ key }}</span
                  ><span>{{ pct(decision.probabilities[key]) }}</span>
                </div>
                <div class="prob-track">
                  <span :class="key" :style="{ width: pct(decision.probabilities[key]) }" />
                </div>
              </div>
              <p v-if="decision.engine.mode !== 'typesafe'" class="fallback-note">
                Add <code>TYPESAFE_API_KEY</code> to <code>.env</code> for Jev judgments. This read
                is the conservative local fallback.
              </p>
            </div>
          </section>

          <DecisionPriceContext
            v-if="priceContext"
            :context="priceContext"
            :action="priceAction"
            :keep-out="Boolean(decision.risk_assessment?.keep_out)"
          />

          <section v-if="decision.brain" class="brain-card">
            <div class="brain-head">
              <div class="brain-title-lockup">
                <span class="brain-badge fig">DECISION BRAIN</span>
                <span class="confluence-badge fig" :class="decision.brain.confluence.toLowerCase()">
                  {{ decision.brain.confluence }} CONFLUENCE
                </span>
                <span class="shield-badge fig" :title="decision.stability?.reason">
                  <span class="shield-dot" />
                  {{ decision.stability?.session_locked ? 'SESSION LOCKED' : 'HYSTERESIS ACTIVE' }}
                </span>
              </div>
              <div class="brain-score-lockup fig">
                <span class="consensus-count"
                  >{{ decision.brain.agreeing_models }}/{{ decision.brain.total_models }} MODELS IN
                  CONSENSUS</span
                >
                <span class="consensus-score">
                  SCORE {{ decision.brain.consensus_score > 0 ? '+' : ''
                  }}{{ decision.brain.consensus_score.toFixed(2) }}
                </span>
              </div>
            </div>

            <div class="brain-meter-container">
              <div class="meter-labels fig">
                <span class="bear">MAX BEAR (-1.0)</span>
                <span class="mid">0.0 BALANCED</span>
                <span class="bull">MAX BULL (+1.0)</span>
              </div>
              <div class="meter-bar">
                <div class="meter-center-axis" />
                <div
                  class="meter-fill"
                  :class="clampedConsensus >= 0 ? 'bull' : 'bear'"
                  :style="meterFillStyle"
                />
                <div class="meter-pointer" :style="{ left: meterPointerLeft }" />
              </div>
            </div>

            <div class="brain-rationale-box">
              <span class="rationale-kicker fig">MODEL CONVERGENCE</span>
              <p>{{ decision.brain.rationale }}</p>
            </div>

            <div class="model-cards-grid">
              <article
                v-for="(model, key) in decision.brain.models"
                :key="key"
                class="model-vote-card"
                :class="`vote-${model.signal}`"
              >
                <div class="model-vote-header">
                  <span class="model-name fig">{{ modelLabel(key) }}</span>
                  <span class="model-vote-tag fig" :class="model.signal">
                    {{ model.signal.toUpperCase() }}
                  </span>
                </div>
                <div class="model-contrib-row fig">
                  <span>SIGNAL IMPACT</span>
                  <strong>{{ model.score > 0 ? '+' : '' }}{{ model.score.toFixed(2) }}</strong>
                </div>
                <p class="model-desc">{{ model.summary }}</p>
              </article>
            </div>
          </section>

          <section class="forecast-card" aria-labelledby="forecast-heading">
            <div class="forecast-head">
              <h2 id="forecast-heading" class="fig">MODEL FORECAST</h2>
              <p class="forecast-source-status">
                <span>SOURCE STATUS</span>
                <span class="status" :class="forecastStatus">{{ forecastStatus }}</span>
              </p>
            </div>

            <p
              v-if="!forecastAvailable && !forecastFallbackAvailable"
              class="forecast-unavailable"
              role="status"
            >
              {{ forecastUnavailableText }}
            </p>
            <template v-else-if="forecastFallbackAvailable">
              <p class="forecast-fallback-note" role="status">
                {{ forecastUnavailableText }} Showing the current measured VPA scenario as a
                fallback; it is not a Kronos model forecast.
              </p>
              <div class="forecast-grid">
                <article>
                  <span class="forecast-label fig">VPA DIRECTION</span>
                  <strong>{{ forwardScenario?.direction ?? 'UNKNOWN' }}</strong>
                </article>
                <article>
                  <span class="forecast-label fig">EXPECTED HORIZON</span>
                  <strong>{{ forwardScenario?.horizon ?? 'Unavailable' }}</strong>
                </article>
                <article>
                  <span class="forecast-label fig">TARGET ZONE</span>
                  <strong>{{ forwardScenario?.targetZone ?? 'Unavailable' }}</strong>
                </article>
                <article>
                  <span class="forecast-label fig">SCENARIO SUPPORT</span>
                  <strong>
                    {{
                      forwardScenario?.supportPct != null
                        ? `${forwardScenario.supportPct}% · NOT WIN PROBABILITY`
                        : 'Unscored'
                    }}
                  </strong>
                </article>
              </div>
              <p v-if="forwardScenario?.likelyMove" class="forecast-fallback-rationale">
                <span class="forecast-label fig">MEASURED OUTLOOK</span>
                {{ forwardScenario.likelyMove }}
                <span v-if="forwardScenario.rationale"> · {{ forwardScenario.rationale }}</span>
              </p>
            </template>
            <div v-else class="forecast-grid">
              <article>
                <span class="forecast-label fig">DIRECTION</span>
                <strong>{{ (forecastEvidence?.direction ?? 'unknown').toUpperCase() }}</strong>
              </article>
              <article v-if="forecastEvidence?.horizon">
                <span class="forecast-label fig">HORIZON</span>
                <strong>{{ formatForecastHorizon(forecastEvidence.horizon) }}</strong>
              </article>
              <article v-if="forecastEvidence?.point_pct != null">
                <span class="forecast-label fig">POINT MOVE</span>
                <strong>{{ formatForecastPct(forecastEvidence.point_pct) }}</strong>
              </article>
              <article v-if="forecastEvidence?.interval_80?.length">
                <span class="forecast-label fig">PI80 · PRICE INTERVAL</span>
                <strong>{{ formatForecastRange(forecastEvidence.interval_80) }}</strong>
              </article>
              <article
                v-if="
                  forecastEvidence?.confidence_kind ||
                  forecastEvidence?.confidence_score != null ||
                  forecastEvidence?.confidence_label
                "
              >
                <span class="forecast-label fig">RESEARCH CONFIDENCE</span>
                <strong>
                  <template v-if="forecastEvidence?.confidence_score != null">
                    {{ forecastEvidence.confidence_score }}
                  </template>
                  <template v-if="forecastEvidence?.confidence_label">
                    {{ forecastEvidence.confidence_score != null ? ' · ' : ''
                    }}{{ forecastEvidence.confidence_label }}
                  </template>
                  <template v-if="forecastEvidence?.confidence_kind">
                    {{
                      forecastEvidence.confidence_score != null || forecastEvidence.confidence_label
                        ? ' · '
                        : ''
                    }}{{ forecastEvidence.confidence_kind.replace(/_/g, ' ') }}
                  </template>
                </strong>
              </article>
              <article>
                <span class="forecast-label fig">MODEL FILTER</span>
                <strong>{{
                  forecastEvidence?.selective_actionable
                    ? 'SELECTED FOR RESEARCH'
                    : 'MODEL ABSTAINED'
                }}</strong>
              </article>
            </div>

            <p
              v-if="forecastAvailable && forecastEvidence?.conflict_with_action"
              class="forecast-conflict"
              role="alert"
            >
              Forecast direction conflicts with the current
              {{ decision.action.toUpperCase() }} action.
              <span v-if="forecastEvidence.reason">{{ forecastEvidence.reason }}</span>
            </p>

            <div class="forecast-meta">
              <p>
                <span class="forecast-label fig">AS OF</span>
                <time v-if="forecastAsOf" :datetime="forecastAsOf">{{ forecastAsOf }}</time>
                <span v-else>Unavailable</span>
              </p>
              <p>
                <span class="forecast-label fig">PROVENANCE</span>
                <span>{{ forecastProvenance }}</span>
              </p>
            </div>
            <p class="forecast-safety">
              This is ordinal research evidence, not win probability and not execution
              authorization.
            </p>
          </section>

          <section v-if="showRiskAssessment" class="risk-assessment">
            <div class="risk-head">
              <span class="fig">RISK ASSESSMENT</span>
              <span class="fig">
                {{ (decision.risk_assessment?.score ?? decision.risk.score).toFixed(1) }}/4 ·
                {{ decision.risk_assessment?.label ?? scoreLabel(decision.risk.score) }}
              </span>
            </div>
            <p v-if="decision.risk_assessment?.keep_out" class="risk-keep-out fig">KEEP OUT</p>
            <ul v-if="riskReasons.length" class="risk-reasons">
              <li v-for="reason in riskReasons" :key="reason">{{ reason }}</li>
            </ul>
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
                <li v-if="modelRead">
                  <strong>Decision Tree Model:</strong>
                  {{
                    (modelRead.trade ? (modelRead.action ?? 'STANDBY') : 'ABSTAIN').toUpperCase()
                  }}
                  <template v-if="modelRead.confidence != null">
                    ({{ Math.round(modelRead.confidence * 100) }}% confidence
                    <template v-if="modelRead.trade"> · clears trade threshold</template>
                    <template v-else> · held below trade threshold</template>)
                  </template>
                  <template v-if="modelRead.reason">
                    · {{ modelRead.reason.replace(/_/g, ' ') }}</template
                  >.
                </li>
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
                <p v-if="source.key === 'vpa' && decision.vpa_judgment" class="vpa-next">
                  VPA next {{ decision.vpa_judgment.direction.toUpperCase() }} · support
                  {{ (decision.vpa_judgment.claim_support?.score ?? 0).toFixed(1) }}/4
                </p>
              </article>
            </div>
          </Panel>

          <footer class="decision-footer fig">
            {{ decision.notice }} · confidence is model certainty, not win probability · no order
            routing · issues surface as risk
          </footer>
        </template>
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
  color: var(--ink-dim);
  max-width: 780px;
  margin: 0;
}
.decision-modes {
  display: flex;
  min-height: 38px;
  border-bottom: var(--hair) solid var(--rule);
}
.decision-modes button {
  min-height: 38px;
  padding: 0 var(--s3);
  border: 0;
  border-right: var(--hair) solid var(--rule);
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--ink-faint);
  font: 750 var(--t-micro) var(--font-data);
  cursor: pointer;
}
.decision-modes button span {
  margin-right: 8px;
  color: var(--ink-faint);
}
.decision-modes button.active {
  color: var(--ink);
  border-bottom-color: var(--phosphor);
  background: color-mix(in srgb, var(--phosphor) 5%, transparent);
}
.symbol-panel {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}
.quick-chips {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.chip-btn {
  border: var(--hair) solid var(--rule);
  background: var(--panel);
  color: var(--ink-faint);
  padding: 6px 10px;
  font: 700 var(--t-nano) var(--font-data);
  cursor: pointer;
  transition: all 0.15s ease;
}
.chip-btn:hover {
  background: var(--panel-hi);
  color: var(--ink);
  border-color: var(--rule-hi);
}
.chip-btn.active {
  background: color-mix(in srgb, var(--phosphor) 15%, var(--panel));
  color: var(--phosphor);
  border-color: var(--phosphor);
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
  background: var(--panel);
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
  color: var(--ink-dim);
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
}
.live-dot.paused {
  background: var(--ink-faint);
  box-shadow: none;
}
.live-controls .resume-btn {
  color: var(--phosphor);
  border-color: color-mix(in srgb, var(--phosphor) 40%, transparent);
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
.brain-pill {
  border: var(--hair) solid var(--rule);
  padding: 2px 7px;
  font: 700 var(--t-nano) var(--font-data);
}
.brain-pill.high {
  color: var(--long);
  border-color: color-mix(in srgb, var(--long) 50%, transparent);
}
.brain-pill.moderate {
  color: var(--phosphor);
  border-color: color-mix(in srgb, var(--phosphor) 50%, transparent);
}
.brain-pill.contested,
.brain-pill.balanced {
  color: var(--ink-faint);
}
.model-gate-pill {
  border: var(--hair) solid var(--rule);
  padding: 2px 7px;
  font: 700 var(--t-nano) var(--font-data);
}
.model-gate-pill.qualified {
  color: var(--long);
  border-color: color-mix(in srgb, var(--long) 50%, transparent);
}
.model-gate-pill.filtered {
  color: var(--ink-faint);
  border-color: var(--rule);
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
.tone-standby .action {
  color: var(--ink);
}
.verdict-card.tone-standby::before {
  background: var(--ink-faint);
}
.action-sub {
  color: var(--ink-dim);
  margin: 0;
  letter-spacing: 0.05em;
}
.execution-posture {
  width: fit-content;
  margin: var(--s2) 0 0;
  padding: 6px 8px;
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.1em;
}
.execution-posture.stand-down {
  border-color: var(--short);
  color: var(--short);
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
  color: var(--ink-dim);
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
.brain-card {
  border: var(--hair) solid var(--rule);
  background: var(--panel);
  padding: var(--s4);
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  position: relative;
}
.forecast-card {
  min-width: 0;
  border: var(--hair) solid var(--rule);
  background: var(--panel);
  padding: var(--s3) var(--s4);
  display: grid;
  gap: var(--s2);
}
.forecast-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--s2);
  padding-bottom: var(--s2);
  border-bottom: var(--hair) solid var(--rule-faint);
}
.forecast-head h2 {
  margin: 0;
  color: var(--phosphor);
  font: 800 var(--t-nano) var(--font-data);
  letter-spacing: 0.12em;
}
.forecast-source-status {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: var(--ink-dim);
  font: 700 var(--t-nano) var(--font-data);
}
.forecast-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s2);
}
.forecast-grid article {
  min-width: 0;
  padding: var(--s2);
  border: var(--hair) solid var(--rule-faint);
  background: var(--panel-hi);
  display: grid;
  align-content: start;
  gap: 6px;
}
.forecast-grid strong,
.forecast-meta p,
.forecast-unavailable,
.forecast-fallback-note,
.forecast-fallback-rationale,
.forecast-conflict,
.forecast-safety {
  overflow-wrap: anywhere;
}
.forecast-grid strong {
  color: var(--ink);
  font: 700 var(--t-small) var(--font-data);
}
.forecast-label {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  letter-spacing: 0.1em;
}
.forecast-unavailable,
.forecast-fallback-note,
.forecast-fallback-rationale,
.forecast-conflict,
.forecast-safety {
  margin: 0;
  color: var(--ink-dim);
  line-height: 1.5;
}
.forecast-fallback-note {
  padding: var(--s2);
  border-left: 3px solid var(--warn);
  background: var(--warn-wash);
  color: var(--ink);
}
.forecast-fallback-rationale {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.forecast-conflict {
  padding: var(--s2);
  border-left: 3px solid var(--short);
  background: var(--put-wash);
  color: var(--ink);
}
.forecast-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s3);
}
.forecast-meta p {
  min-width: 0;
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  color: var(--ink-dim);
  font-size: var(--t-micro);
}
.forecast-safety {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}
.brain-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--phosphor);
}
.brain-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--s2);
  padding-bottom: var(--s2);
  border-bottom: var(--hair) solid var(--rule-faint);
}
.brain-title-lockup {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}
.brain-badge {
  color: var(--phosphor);
  font: 800 var(--t-nano) var(--font-data);
  letter-spacing: 0.12em;
}
.confluence-badge {
  padding: 3px 8px;
  font: 700 var(--t-nano) var(--font-data);
  letter-spacing: 0.08em;
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
}
.confluence-badge.high {
  color: var(--long);
  border-color: color-mix(in srgb, var(--long) 40%, transparent);
  background: var(--call-wash);
}
.confluence-badge.moderate {
  color: var(--phosphor);
  border-color: color-mix(in srgb, var(--phosphor) 40%, transparent);
}
.confluence-badge.contested,
.confluence-badge.balanced {
  color: var(--ink-faint);
}
.shield-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-faint);
  font: var(--t-nano) var(--font-data);
}
.shield-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--phosphor);
}
.brain-score-lockup {
  display: flex;
  align-items: center;
  gap: var(--s3);
  font-size: var(--t-nano);
}
.consensus-count {
  color: var(--ink-dim);
}
.consensus-score {
  color: var(--ink);
  font-weight: 700;
}
.brain-meter-container {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.meter-labels {
  display: flex;
  justify-content: space-between;
  font-size: var(--t-nano);
  color: var(--ink-faint);
}
.meter-labels .bear {
  color: var(--short);
}
.meter-labels .bull {
  color: var(--long);
}
.meter-bar {
  height: 10px;
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  position: relative;
  overflow: visible;
}
.meter-center-axis {
  position: absolute;
  top: -2px;
  bottom: -2px;
  left: 50%;
  width: 2px;
  background: var(--ink-faint);
  z-index: 2;
}
.meter-fill {
  position: absolute;
  top: 0;
  bottom: 0;
  transition:
    width 0.3s ease,
    left 0.3s ease;
}
.meter-fill.bull {
  background: color-mix(in srgb, var(--long) 70%, transparent);
}
.meter-fill.bear {
  background: color-mix(in srgb, var(--short) 70%, transparent);
}
.meter-pointer {
  position: absolute;
  top: -4px;
  bottom: -4px;
  width: 3px;
  background: var(--ink);
  transform: translateX(-50%);
  z-index: 3;
}
.brain-rationale-box {
  padding: var(--s2) var(--s3);
  background: var(--panel-hi);
  border-left: 2px solid var(--phosphor);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.rationale-kicker {
  color: var(--phosphor);
  font: 700 var(--t-nano) var(--font-data);
  letter-spacing: 0.1em;
}
.brain-rationale-box p {
  margin: 0;
  color: var(--ink-soft);
  font: var(--t-micro) var(--font-data);
  line-height: 1.5;
}
.model-cards-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--s2);
}
.model-vote-card {
  padding: var(--s2);
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: border-color 0.2s;
}
.model-vote-card.vote-bullish {
  border-left: 2px solid var(--long);
}
.model-vote-card.vote-bearish {
  border-left: 2px solid var(--short);
}
.model-vote-card.vote-neutral {
  border-left: 2px solid var(--rule-hi);
}
.model-vote-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.model-name {
  font: 700 var(--t-nano) var(--font-data);
  color: var(--ink-faint);
  letter-spacing: 0.08em;
}
.model-vote-tag {
  font: 800 var(--t-nano) var(--font-data);
  padding: 1px 5px;
}
.model-vote-tag.bullish {
  color: var(--long);
  background: var(--call-wash);
}
.model-vote-tag.bearish {
  color: var(--short);
  background: var(--put-wash);
}
.model-vote-tag.neutral {
  color: var(--ink-faint);
  background: var(--panel-raise);
}
.model-contrib-row {
  display: flex;
  justify-content: space-between;
  font-size: var(--t-nano);
  color: var(--ink-faint);
}
.model-contrib-row strong {
  color: var(--ink);
}
.model-desc {
  margin: 0;
  color: var(--ink-dim);
  font-size: var(--t-nano);
  line-height: 1.4;
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
  color: var(--ink-dim);
  font: var(--t-micro) var(--font-data);
}
.metric-grid article.danger strong,
.metric-grid article.danger > span:last-child {
  color: var(--short);
}
.risk-assessment {
  border: var(--hair) solid var(--short);
  background: var(--put-wash);
  padding: var(--s3) var(--s4);
  display: grid;
  gap: var(--s2);
}
.risk-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--s2);
  color: var(--short);
  font: 700 var(--t-nano) var(--font-data);
  letter-spacing: 0.12em;
}
.risk-keep-out {
  margin: 0;
  color: var(--short);
  letter-spacing: 0.14em;
}
.risk-reasons {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--s2);
}
.risk-reasons li {
  padding: 10px 12px;
  border-left: 2px solid var(--short);
  background: var(--panel);
  color: var(--ink);
  font: var(--t-micro) var(--font-data);
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
.status.missing,
.status.stale {
  color: var(--short);
  background: var(--put-wash);
}
.source-grid p {
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.45;
}
.vpa-next {
  color: var(--phosphor);
  font: var(--t-nano) var(--font-data);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin: 6px 0 0;
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
  .model-cards-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .forecast-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .source-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 620px) {
  .metric-grid,
  .source-grid,
  .model-cards-grid {
    grid-template-columns: 1fr;
  }
  .forecast-grid {
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
