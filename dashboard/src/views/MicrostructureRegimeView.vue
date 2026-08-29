<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import { useResource } from '@/composables/useResource'
import { num, optSigned } from '@/format'
import type {
  MicrostructureRegimeSnapshot,
  StateEstimationPayload,
  AnchoredVwapPayload,
  SystematicSignalsPayload,
  BacktestTearsheet,
} from '@/microstructureContracts'
import type { RegimeBreadthPayload } from '@/regimeContracts'
import {
  computeRuleOf16ExpectedMove,
  assessMoveExcursion,
  assessWallAlignment,
  type ExpectedMoveMetrics,
} from '@/expectedMove'

import Panel from '@/components/Panel.vue'
import LoadingState from '@/components/LoadingState.vue'
import RegimeBreadthStrip from '@/components/RegimeBreadthStrip.vue'
import MicrostructureTopographyCard from '@/components/MicrostructureTopographyCard.vue'
import DealerGreeksFlowCard from '@/components/DealerGreeksFlowCard.vue'
import SectorPairCorrelationCard from '@/components/SectorPairCorrelationCard.vue'
import CausalEnvelopeChart from '@/components/CausalEnvelopeChart.vue'
import KalmanKinematicPhasePlot from '@/components/KalmanKinematicPhasePlot.vue'

const route = useRoute()
const router = useRouter()

const initialSymbol = (
  typeof route.query.symbol === 'string' && route.query.symbol ? route.query.symbol : 'SPY'
).toUpperCase()
const symbol = ref(initialSymbol)
const symbolInput = ref(initialSymbol)
const window = ref('1y')
const bandwidthH = ref(20.0)
const envelopeAlpha = ref(2.0)
const kalmanQ = ref(0.001)
const breakoutZ = ref(1.6)
const exhaustionZ = ref(0.4)
const barsMode = ref<'daily' | '1h'>('daily')

// Shared multi-pane chart hover tracking
const chartHoverIndex = ref<number | null>(null)

function updateSymbol() {
  const clean = symbolInput.value
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
  if (clean && clean !== symbol.value) {
    symbol.value = clean
    router.replace({ query: { ...route.query, symbol: clean } })
  }
}

function selectPairSymbol(sym: string): void {
  symbolInput.value = sym
  updateSymbol()
}

// 1. Market Breadth Resource (15-ETF Index + Sector Universe)
const breadthActivated = ref(false)
const breadthRes = useResource<RegimeBreadthPayload>(
  () => api.gammaRegime({ force: false, trend: true }),
  {
    intervalMs: 30_000,
    immediate: false,
    enabled: () => breadthActivated.value,
  },
)

function onBreadthActivate(): void {
  breadthActivated.value = true
  void breadthRes.refresh()
}

// 2. Quotes for spot and benchmark VIX
const quotesRes = useResource(() => api.quotes([symbol.value, 'VIX', 'SPY']), {
  intervalMs: 5_000,
  immediate: true,
})

const vixQuote = computed<number | null>(() => {
  const row = quotesRes.data.value?.rows.find((r) => r.symbol === 'VIX')
  return row?.last ?? null
})

const symbolQuoteRow = computed(() => {
  return quotesRes.data.value?.rows.find((r) => r.symbol === symbol.value) ?? null
})

// 3. Fetch Microstructure Regime Snapshot
const regimeRes = useResource<MicrostructureRegimeSnapshot>(
  () => api.microstructureRegime(symbol.value),
  { intervalMs: 30_000, immediate: true },
)

const effectiveSpot = computed<number | null>(() => {
  return symbolQuoteRow.value?.last ?? regimeRes.data.value?.spot ?? null
})

/** Rule of 16 Expected Move Metrics (1D, 1W, 1M) */
const expectedMove = computed<ExpectedMoveMetrics | null>(() => {
  const spot = effectiveSpot.value
  return computeRuleOf16ExpectedMove(spot, null, vixQuote.value ?? 18.0)
})

const moveExcursion = computed(() => {
  if (!expectedMove.value) return null
  const chg =
    symbolQuoteRow.value?.last != null && symbolQuoteRow.value?.prev_close != null
      ? symbolQuoteRow.value.last - symbolQuoteRow.value.prev_close
      : 0
  return assessMoveExcursion(chg, expectedMove.value.em1dDollars)
})

const wallSpatial = computed(() => {
  if (!expectedMove.value) return null
  const spot = effectiveSpot.value ?? 0
  const snap = regimeRes.data.value
  return assessWallAlignment(snap?.call_wall, snap?.put_wall, spot, expectedMove.value.em1dDollars)
})

// 4. Fetch State Estimation (Causal NW + Kinematic Kalman)
const stateRes = useResource<StateEstimationPayload>(
  () =>
    api.stateEstimation(symbol.value, {
      window: window.value,
      h: bandwidthH.value,
      alpha: envelopeAlpha.value,
      q: kalmanQ.value,
      bars: barsMode.value,
    }),
  { intervalMs: 60_000, immediate: true },
)

// 5. Fetch Microstructure Anchored VWAP
const vwapRes = useResource<AnchoredVwapPayload>(
  () => api.anchoredVwap(symbol.value, { window: window.value, bars: barsMode.value }),
  { intervalMs: 60_000, immediate: true },
)

// 6. Fetch Live Execution Signals
const signalsRes = useResource<SystematicSignalsPayload>(
  () =>
    api.systematicSignals(symbol.value, {
      window: window.value,
      h: bandwidthH.value,
      alpha: envelopeAlpha.value,
      breakout_z: breakoutZ.value,
      exhaustion_z: exhaustionZ.value,
      bars: barsMode.value,
    }),
  { intervalMs: 30_000, immediate: true },
)

// 7. Backtest Runner
const backtestRunning = ref(false)
const backtestResult = ref<BacktestTearsheet | null>(null)
const backtestCapital = ref(100_000)
const backtestRiskPct = ref(0.02)
const backtestSlippage = ref(2.0)

async function runBacktest() {
  backtestRunning.value = true
  try {
    const res = await api.systematicBacktest(symbol.value, {
      window: window.value,
      capital: backtestCapital.value,
      risk_pct: backtestRiskPct.value,
      slippage_bps: backtestSlippage.value,
      bars: barsMode.value,
    })
    backtestResult.value = res
  } catch (err) {
    console.error('Backtest failed:', err)
  } finally {
    backtestRunning.value = false
  }
}

// Run initial backtest once on mount & ticker switch
watch(
  () => symbol.value,
  () => {
    runBacktest()
  },
  { immediate: true },
)

const activeSignal = computed(() => {
  if (!signalsRes.data.value?.latest_signal) return null
  const s = signalsRes.data.value.latest_signal
  return s.action !== 'NONE' ? s : null
})

const recentSignals = computed(() => {
  if (!signalsRes.data.value?.signals) return []
  return signalsRes.data.value.signals
    .filter((s) => s.action === 'ENTER_LONG' || s.action === 'ENTER_SHORT')
    .slice(-12)
    .reverse()
})

const latestStatePoint = computed(() => {
  const pts = stateRes.data.value?.points ?? []
  return pts.length > 0 ? pts[pts.length - 1] : null
})

const tacticalBias = computed(() => {
  const spot = effectiveSpot.value ?? regimeRes.data.value?.spot ?? null
  const flip = regimeRes.data.value?.gamma_flip ?? null
  const netGex = regimeRes.data.value?.net_gex_m ?? 0
  const vel = latestStatePoint.value?.kalman_velocity ?? 0

  if (!spot || !flip) {
    return {
      title: 'AWAITING SURFACE READ',
      bias: 'NEUTRAL',
      toneClass: 'neutral',
      stance: 'Calculating structural levels...',
      action: 'Wait for network sync',
    }
  }

  const isAboveFlip = spot >= flip

  if (isAboveFlip && netGex > 0) {
    if (vel >= 0) {
      return {
        title: 'BULLISH EXPANSION & SUPPORTIVE GEX',
        bias: 'BULLISH',
        toneClass: 'bullish',
        stance:
          'Dealers provide supportive gamma cushion below spot. Upside momentum supported by dealer rebalancing.',
        action: 'Buy pullbacks toward Causal Kernel Mean m(t) with target at Call Wall.',
      }
    } else {
      return {
        title: 'LONG GAMMA CONVERGENCE (MEAN-REVERTING)',
        bias: 'RANGE-BOUND / MEAN-REVERT',
        toneClass: 'bullish',
        stance:
          'Dealers actively sell rallies and buy dips, dampening volatility toward latent equilibrium.',
        action: 'Fade upper/lower envelope extremes; take profits quickly near Kernel Mean.',
      }
    }
  } else if (!isAboveFlip && netGex < 0) {
    if (vel <= 0) {
      return {
        title: 'BEARISH CASCADE RISK (NEGATIVE GEX)',
        bias: 'BEARISH',
        toneClass: 'bearish',
        stance:
          'Short gamma tape. Dealer delta hedging accelerates selling on down moves. High downside void risk.',
        action: 'Sell breakdown rallies to Gamma Flip S*; avoid unhedged long positions.',
      }
    } else {
      return {
        title: 'SHORT-SQUEEZE EXPANSION SPRINT',
        bias: 'SHORT SQUEEZE',
        toneClass: 'squeeze',
        stance:
          'Price rebounding below flip against negative GEX overhead. Dealers forced to cover delta on rallies.',
        action: 'Momentum long with tight trailing stop at Gamma Flip S*.',
      }
    }
  } else {
    return {
      title: 'TRANSITION FLIP PIVOT STRADDLE',
      bias: 'BREAKOUT WATCH',
      toneClass: 'transition',
      stance:
        'Spot is straddling the Zero-Gamma Flip boundary. Tape is undecided with symmetric trigger risk.',
      action: 'Wait for confirmed breakout above Call Wall or breakdown below Put Wall.',
    }
  }
})

// Structural Pivot Ladder for quick orientation
const pivotLadder = computed(() => {
  const spot = effectiveSpot.value ?? regimeRes.data.value?.spot ?? 0
  const pt = latestStatePoint.value
  const snap = regimeRes.data.value
  const em = expectedMove.value
  if (!snap || !pt) return []

  const list = [
    { label: 'CALL WALL', price: snap.call_wall, role: 'Resistance Wall', tone: 'call' },
    ...(em
      ? [
          {
            label: '+1D EM (VIX/16)',
            price: em.em1dHigh,
            role: 'Rule of 16 Upper 1σ',
            tone: 'warn',
          },
        ]
      : []),
    { label: 'UPPER ENVELOPE', price: pt.nw_upper, role: 'Dynamic +2σ Band', tone: 'call' },
    { label: 'SPOT PRICE', price: spot, role: 'Current Underlying', tone: 'spot' },
    { label: 'KERNEL MEAN m(t)', price: pt.nw_mean, role: 'Latent Equilibrium', tone: 'phosphor' },
    { label: 'GAMMA FLIP S*', price: snap.gamma_flip, role: 'Regime Boundary', tone: 'warn' },
    { label: 'LOWER ENVELOPE', price: pt.nw_lower, role: 'Dynamic -2σ Band', tone: 'put' },
    ...(em
      ? [{ label: '-1D EM (VIX/16)', price: em.em1dLow, role: 'Rule of 16 Lower 1σ', tone: 'warn' }]
      : []),
    { label: 'PUT WALL', price: snap.put_wall, role: 'Support Floor', tone: 'put' },
  ]

  return list
    .filter((x) => x.price != null && x.price > 0)
    .sort((a, b) => (b.price ?? 0) - (a.price ?? 0))
})
</script>

<template>
  <div class="microstructure-view">
    <!-- Top Control Bar -->
    <header class="control-bar ticked">
      <div class="symbol-search-group">
        <label class="input-label">UNDERLIER</label>
        <div class="input-wrap">
          <input
            v-model="symbolInput"
            type="text"
            class="symbol-input font-mono"
            placeholder="SPY"
            @keyup.enter="updateSymbol"
          />
          <button class="btn btn-primary" @click="updateSymbol">LOAD</button>
        </div>
      </div>

      <!-- Quick Tickers -->
      <div class="quick-tickers">
        <button
          v-for="sym in ['SPY', 'QQQ', 'IWM', 'DIA', 'NVDA', 'TSLA', 'AAPL', 'MSFT']"
          :key="sym"
          class="ticker-chip font-mono"
          :class="{ active: symbol === sym }"
          @click="
            symbolInput = sym;
            updateSymbol();
          "
        >
          {{ sym }}
        </button>
      </div>

      <!-- Timeframe & Bar Mode Selector -->
      <div class="window-selector">
        <div class="chips-group">
          <button
            v-for="w in ['1m', '3m', '6m', '1y', '3y']"
            :key="w"
            class="win-chip font-mono"
            :class="{ active: window === w }"
            @click="window = w"
          >
            {{ w.toUpperCase() }}
          </button>
        </div>
        <div class="chips-group">
          <button
            class="win-chip font-mono"
            :class="{ active: barsMode === 'daily' }"
            @click="barsMode = 'daily'"
          >
            1D
          </button>
          <button
            class="win-chip font-mono"
            :class="{ active: barsMode === '1h' }"
            @click="barsMode = '1h'"
          >
            1H
          </button>
        </div>
      </div>
    </header>

    <!-- Market Gamma Breadth Strip -->
    <RegimeBreadthStrip
      :payload="breadthRes.data.value"
      :activated="breadthActivated"
      :loading="breadthRes.loading.value"
      :error="breadthRes.error.value"
      :fetched-at="breadthRes.fetchedAt.value"
      @activate="onBreadthActivate"
    />

    <!-- Loading State -->
    <LoadingState
      v-if="regimeRes.loading.value && !regimeRes.data.value"
      label="Computing Dealer Greeks Surface &amp; State Estimators..."
    />

    <template v-else>
      <!-- 1. Executive Tactical Briefing & Signal Command Card -->
      <section class="tactical-banner ticked" :class="tacticalBias.toneClass">
        <div class="tactical-header">
          <div class="tactical-title-wrap">
            <span class="tactical-eyebrow font-mono"
              >EXECUTIVE REGIME TACTICAL BRIEFING · {{ symbol }}</span
            >
            <h2 class="tactical-title">{{ tacticalBias.title }}</h2>
          </div>
          <div class="tactical-bias-badge font-mono" :class="tacticalBias.toneClass">
            BIAS: {{ tacticalBias.bias }}
          </div>
        </div>

        <div class="tactical-body-grid">
          <div class="tactical-col">
            <span class="col-label font-mono">MARKET MICROSTRUCTURE STANCE</span>
            <p class="col-text">{{ tacticalBias.stance }}</p>
          </div>
          <div class="tactical-col">
            <span class="col-label font-mono">ACTIONABLE EXECUTION PLAN</span>
            <p class="col-text text-phosphor font-semibold">{{ tacticalBias.action }}</p>
          </div>
        </div>

        <!-- Active Execution Ticket Overlay if present -->
        <div v-if="activeSignal" class="active-ticket-row" :class="activeSignal.action">
          <div class="ticket-status-pill font-mono">
            ACTIVE TICKET: {{ activeSignal.action }} &middot; {{ activeSignal.setup_name }}
          </div>
          <div class="ticket-metrics-list">
            <div>
              Entry:
              <span class="font-mono font-bold">${{ num(activeSignal.entry_price, 2) }}</span>
            </div>
            <div>
              Stop:
              <span class="font-mono font-bold text-rose"
                >${{ num(activeSignal.stop_loss, 2) }}</span
              >
            </div>
            <div>
              Target:
              <span class="font-mono font-bold text-emerald"
                >${{ num(activeSignal.take_profit, 2) }}</span
              >
            </div>
            <div>
              Conviction:
              <span class="font-mono font-bold"
                >{{ Math.round(activeSignal.conviction * 100) }}%</span
              >
            </div>
            <div>
              Size:
              <span class="font-mono font-bold"
                >{{ activeSignal.suggested_size_pct }}% capital</span
              >
            </div>
          </div>
        </div>

        <!-- Microstructure Pivot Ladder -->
        <div class="pivot-ladder-strip">
          <span class="ladder-title font-mono">PIVOT LADDER:</span>
          <div class="ladder-pills">
            <span
              v-for="p in pivotLadder"
              :key="p.label"
              class="ladder-pill font-mono"
              :class="p.tone"
            >
              <span class="p-name">{{ p.label }}</span>
              <span class="p-price">${{ num(p.price, 2) }}</span>
            </span>
          </div>
        </div>

        <!-- Rule of 16 Expected Move Volatility Strip -->
        <div v-if="expectedMove" class="expected-move-strip">
          <div class="em-item">
            <span class="em-label font-mono">1-DAY EXPECTED MOVE (VIX / 16)</span>
            <span class="em-val font-mono font-bold text-warn">
              &plusmn;${{ num(expectedMove.em1dDollars, 2) }} (&plusmn;{{
                num(expectedMove.em1dPct, 1)
              }}%)
            </span>
            <span class="em-sub font-mono text-ink-dim"
              >[${{ num(expectedMove.em1dLow, 2) }} &mdash; ${{
                num(expectedMove.em1dHigh, 2)
              }}]</span
            >
          </div>
          <div class="em-item">
            <span class="em-label font-mono">1-WEEK EXPECTED MOVE</span>
            <span class="em-val font-mono font-semibold">
              &plusmn;${{ num(expectedMove.em1wDollars, 2) }} (&plusmn;{{
                num(expectedMove.em1wPct, 1)
              }}%)
            </span>
            <span class="em-sub font-mono text-ink-dim"
              >[${{ num(expectedMove.em1wLow, 2) }} &mdash; ${{
                num(expectedMove.em1wHigh, 2)
              }}]</span
            >
          </div>
          <div class="em-item">
            <span class="em-label font-mono">INTRADAY MOVE EXCURSION</span>
            <span class="em-val font-mono font-semibold text-call-hi">
              {{ moveExcursion?.label }}
            </span>
            <span class="em-sub text-ink-dim">
              {{
                wallSpatial?.callWallInside1d
                  ? 'Call Wall inside 1D EM (High-Probability Pin)'
                  : 'Call Wall beyond 1D EM'
              }}
            </span>
          </div>
          <div class="em-item">
            <span class="em-label font-mono">VOL COMPLEX BENCHMARK</span>
            <span class="em-val font-mono text-phosphor font-semibold">
              VIX {{ vixQuote ? num(vixQuote, 1) : '18.0' }} &middot; ATM IV
              {{ num(expectedMove.ivAnnualPct, 1) }}%
            </span>
            <span class="em-sub font-mono text-ink-faint">EM = S &times; (IV / 16)</span>
          </div>
        </div>
      </section>

      <!-- 2. Hero Topography & Greeks Grid -->
      <div class="hero-grid">
        <DealerGreeksFlowCard :snapshot="regimeRes.data.value" />
        <MicrostructureTopographyCard
          :topography="regimeRes.data.value?.topography ?? null"
          :spot="effectiveSpot"
        />
      </div>

      <!-- Sector Rotation & Pair Correlation Card -->
      <SectorPairCorrelationCard
        :symbol="symbol"
        :spot="effectiveSpot"
        :day-change-pct="symbolQuoteRow?.chg_1d_pct ?? null"
        :breadth-payload="breadthRes.data.value"
        @select-symbol="selectPairSymbol"
      />

      <!-- 3. Main Multi-Pane Chart Section -->
      <Panel label="Causal Nadaraya-Watson Envelope & Anchored VWAP">
        <template #action>
          <div class="chart-params">
            <label
              >h (Bandwidth): <span class="font-mono text-phosphor">{{ bandwidthH }}</span></label
            >
            <input v-model.number="bandwidthH" type="range" min="5" max="60" step="1" />
            <label
              >&alpha; (Envelope):
              <span class="font-mono text-call-hi">{{ envelopeAlpha }}&sigma;</span></label
            >
            <input v-model.number="envelopeAlpha" type="range" min="1" max="4" step="0.2" />
          </div>
        </template>

        <CausalEnvelopeChart
          v-model:hover-index="chartHoverIndex"
          :points="stateRes.data.value?.points ?? []"
          :anchors="vwapRes.data.value?.anchors ?? []"
          :signals="signalsRes.data.value?.signals ?? []"
          :call-wall="regimeRes.data.value?.call_wall ?? null"
          :put-wall="regimeRes.data.value?.put_wall ?? null"
          :gamma-flip="regimeRes.data.value?.gamma_flip ?? null"
          :expected-move="expectedMove"
        />
      </Panel>

      <!-- Kinematic Kalman Velocity Sub-Panel (Synchronized Hover) -->
      <Panel label="2-State Kinematic State-Space Velocity & Acceleration">
        <template #action>
          <div class="chart-params">
            <label
              >Process Noise Q:
              <span class="font-mono text-call-hi">{{ kalmanQ.toExponential(1) }}</span></label
            >
            <input v-model.number="kalmanQ" type="range" min="0.00001" max="0.01" step="0.0001" />
          </div>
        </template>

        <KalmanKinematicPhasePlot
          v-model:hover-index="chartHoverIndex"
          :points="stateRes.data.value?.points ?? []"
          :breakout-z="breakoutZ"
          :exhaustion-z="exhaustionZ"
        />
      </Panel>

      <!-- 4. Systematic Signal History & Backtest Engine -->
      <div class="bottom-grid">
        <!-- Signal History Table -->
        <Panel label="Recent Microstructure Trade Setups">
          <div class="table-wrap">
            <table class="signals-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Action</th>
                  <th>Setup</th>
                  <th>Price</th>
                  <th>Stop</th>
                  <th>Target</th>
                  <th>Conviction</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(s, idx) in recentSignals" :key="idx">
                  <td class="font-mono text-muted">{{ s.timestamp.slice(0, 10) }}</td>
                  <td>
                    <span class="action-pill" :class="s.action">{{ s.action }}</span>
                  </td>
                  <td class="font-semibold">{{ s.setup_name }}</td>
                  <td class="font-mono">${{ num(s.price, 2) }}</td>
                  <td class="font-mono text-rose">${{ num(s.stop_loss, 2) }}</td>
                  <td class="font-mono text-emerald">${{ num(s.take_profit, 2) }}</td>
                  <td class="font-mono">{{ Math.round(s.conviction * 100) }}%</td>
                </tr>
                <tr v-if="recentSignals.length === 0">
                  <td colspan="7" class="text-center text-muted">No trigger setups in window</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Panel>

        <!-- Backtest Tearsheet Panel -->
        <Panel label="Systematic Microstructure Backtester">
          <template #action>
            <button class="btn btn-primary btn-sm" :disabled="backtestRunning" @click="runBacktest">
              {{ backtestRunning ? 'Running...' : 'Run Simulation' }}
            </button>
          </template>

          <div v-if="backtestResult" class="backtest-summary">
            <div class="kpi-grid">
              <div class="kpi-box">
                <span class="kpi-label">TOTAL NET P&amp;L</span>
                <span
                  class="kpi-val font-mono"
                  :class="{
                    'text-emerald': backtestResult.total_net_pnl >= 0,
                    'text-rose': backtestResult.total_net_pnl < 0,
                  }"
                >
                  ${{ num(backtestResult.total_net_pnl, 2) }} ({{
                    optSigned(backtestResult.total_return_pct, 1)
                  }}%)
                </span>
              </div>
              <div class="kpi-box">
                <span class="kpi-label">SHARPE RATIO</span>
                <span class="kpi-val font-mono text-call">{{
                  num(backtestResult.sharpe_ratio, 2)
                }}</span>
              </div>
              <div class="kpi-box">
                <span class="kpi-label">MAX DRAWDOWN</span>
                <span class="kpi-val font-mono text-rose"
                  >-{{ num(backtestResult.max_drawdown_pct, 2) }}%</span
                >
              </div>
              <div class="kpi-box">
                <span class="kpi-label">WIN RATE / TRADES</span>
                <span class="kpi-val font-mono"
                  >{{ num(backtestResult.win_rate, 1) }}% ({{ backtestResult.total_trades }})</span
                >
              </div>
              <div class="kpi-box">
                <span class="kpi-label">PROFIT FACTOR</span>
                <span class="kpi-val font-mono text-emerald">{{
                  num(backtestResult.profit_factor, 2)
                }}</span>
              </div>
              <div class="kpi-box">
                <span class="kpi-label">GAMMA P&amp;L ATTRIBUTION</span>
                <span class="kpi-val font-mono text-call"
                  >${{ num(backtestResult.total_gamma_pnl, 2) }}</span
                >
              </div>
            </div>

            <!-- Regime Breakdown -->
            <div class="regime-table-wrap">
              <h4 class="sub-heading">Regime-Segmented Performance</h4>
              <table class="regime-perf-table">
                <thead>
                  <tr>
                    <th>Regime</th>
                    <th>Trades</th>
                    <th>Win Rate</th>
                    <th>Profit Factor</th>
                    <th>Net P&amp;L</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(rm, rname) in backtestResult.regime_breakdown" :key="rname">
                    <td class="font-mono font-semibold">
                      {{ String(rname).toUpperCase().replace(/_/g, ' ') }}
                    </td>
                    <td>{{ rm.n_trades }}</td>
                    <td>{{ rm.win_rate }}%</td>
                    <td>{{ rm.profit_factor }}</td>
                    <td
                      class="font-mono"
                      :class="{
                        'text-emerald': rm.total_net_pnl >= 0,
                        'text-rose': rm.total_net_pnl < 0,
                      }"
                    >
                      ${{ num(rm.total_net_pnl, 2) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </Panel>
      </div>
    </template>
  </div>
</template>

<style scoped>
.microstructure-view {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.25rem 1.5rem;
  width: 100%;
  box-sizing: border-box;
}

.control-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.75rem 1rem;
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--radius-sm, 4px);
}

.symbol-search-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.input-label {
  font-size: 0.6875rem;
  font-family: var(--font-mono, monospace);
  color: var(--ink-faint);
}

.input-wrap {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.symbol-input {
  background: var(--void-lift);
  border: 1px solid var(--rule-hi);
  border-radius: var(--radius-sm, 4px);
  color: var(--ink);
  padding: 0.375rem 0.625rem;
  font-size: 0.875rem;
  width: 90px;
  text-transform: uppercase;
}

.quick-tickers,
.window-selector {
  display: flex;
  gap: 0.5rem;
}

.chips-group {
  display: flex;
  gap: 0.25rem;
}

.ticker-chip,
.win-chip {
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  border-radius: var(--radius-sm, 4px);
  color: var(--ink-dim);
  padding: 0.25rem 0.5rem;
  font-size: 0.6875rem;
  cursor: pointer;
  transition: all var(--dur-fast) ease;
}

.ticker-chip.active,
.win-chip.active {
  background: var(--phosphor);
  border-color: var(--phosphor);
  color: var(--void);
  font-weight: 700;
}

/* Tactical Intelligence Briefing Banner */
.tactical-banner {
  padding: 1rem 1.25rem;
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--radius-sm, 4px);
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.tactical-banner.bullish {
  border-left: 4px solid var(--long);
}

.tactical-banner.bearish {
  border-left: 4px solid var(--short);
}

.tactical-banner.squeeze {
  border-left: 4px solid var(--warn);
}

.tactical-banner.transition {
  border-left: 4px solid var(--rule-hi);
}

.tactical-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}

.tactical-eyebrow {
  font-size: 0.625rem;
  letter-spacing: 0.06em;
  color: var(--ink-faint);
}

.tactical-title {
  margin: 0.125rem 0 0;
  font-size: 1.125rem;
  font-weight: 700;
  color: var(--ink);
}

.tactical-bias-badge {
  font-size: 0.6875rem;
  font-weight: 700;
  padding: 0.25rem 0.625rem;
  border-radius: var(--radius-sm, 4px);
}

.tactical-bias-badge.bullish {
  background: var(--call-wash);
  color: var(--call-hi);
  border: 1px solid var(--call-dim);
}

.tactical-bias-badge.bearish {
  background: var(--put-wash);
  color: var(--put-hi);
  border: 1px solid var(--put-dim);
}

.tactical-bias-badge.squeeze {
  background: var(--warn-wash);
  color: var(--warn);
  border: 1px solid var(--warn);
}

.tactical-bias-badge.transition,
.tactical-bias-badge.neutral {
  background: var(--panel-hi);
  color: var(--ink-dim);
  border: 1px solid var(--rule-hi);
}

.tactical-body-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.tactical-col {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.col-label {
  font-size: 0.625rem;
  color: var(--ink-faint);
  letter-spacing: 0.04em;
}

.col-text {
  font-size: 0.8125rem;
  color: var(--ink);
  line-height: 1.35;
}

.active-ticket-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.625rem 0.875rem;
  background: var(--void-lift);
  border: 1px solid var(--call-dim);
  border-radius: var(--radius-sm, 4px);
}

.active-ticket-row.ENTER_SHORT {
  border-color: var(--put-dim);
}

.ticket-status-pill {
  font-size: 0.6875rem;
  font-weight: 700;
  color: var(--call-hi);
}

.active-ticket-row.ENTER_SHORT .ticket-status-pill {
  color: var(--put-hi);
}

.ticket-metrics-list {
  display: flex;
  flex-wrap: wrap;
  gap: 1.25rem;
  font-size: 0.75rem;
  color: var(--ink-dim);
}

.pivot-ladder-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--rule-faint);
}

.expected-move-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.75rem;
  padding: 0.625rem 0.875rem;
  background: var(--void-lift);
  border: 1px solid var(--rule-faint);
  border-radius: var(--radius-sm, 4px);
}

.em-item {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.em-label {
  font-size: 0.5625rem;
  color: var(--ink-faint);
  letter-spacing: 0.04em;
}

.em-val {
  font-size: 0.875rem;
  color: var(--ink);
}

.em-sub {
  font-size: 0.625rem;
  line-height: 1.25;
}

.ladder-title {
  font-size: 0.625rem;
  color: var(--ink-faint);
}

.ladder-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.ladder-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.15rem 0.5rem;
  border-radius: 3px;
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  font-size: 0.6875rem;
}

.ladder-pill.spot {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
  color: var(--phosphor);
  font-weight: 700;
}

.ladder-pill.call {
  color: var(--call-hi);
}

.ladder-pill.put {
  color: var(--put-hi);
}

.ladder-pill.warn {
  color: var(--warn);
}

.p-name {
  font-size: 0.5625rem;
  color: var(--ink-faint);
}

.p-price {
  font-weight: 600;
}

.hero-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.chart-params {
  display: flex;
  align-items: center;
  gap: 1rem;
  font-size: 0.75rem;
  color: var(--ink-dim);
}

.chart-params input[type='range'] {
  width: 80px;
}

.bottom-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.table-wrap {
  overflow-x: auto;
}

.signals-table,
.regime-perf-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
}

.signals-table th,
.signals-table td,
.regime-perf-table th,
.regime-perf-table td {
  padding: 0.5rem;
  text-align: left;
  border-bottom: 1px solid var(--rule-faint);
}

.signals-table th,
.regime-perf-table th {
  color: var(--ink-faint);
  font-family: var(--font-mono, monospace);
  font-size: 0.6875rem;
}

.action-pill {
  font-size: 0.6875rem;
  font-weight: 700;
  padding: 0.15rem 0.35rem;
  border-radius: var(--radius-sm, 4px);
  font-family: var(--font-mono, monospace);
}

.action-pill.ENTER_LONG {
  background: var(--call-wash);
  color: var(--call-hi);
}

.action-pill.ENTER_SHORT {
  background: var(--put-wash);
  color: var(--put-hi);
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.kpi-box {
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  border-radius: var(--radius-sm, 4px);
  padding: 0.625rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.kpi-label {
  font-size: 0.625rem;
  color: var(--ink-faint);
  font-family: var(--font-mono, monospace);
}

.kpi-val {
  font-size: 1rem;
  font-weight: 600;
}

.sub-heading {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--ink-dim);
  margin: 0.5rem 0 0.25rem;
}

.btn {
  background: var(--panel-raise);
  border: 1px solid var(--rule-hi);
  color: var(--ink);
  padding: 0.375rem 0.75rem;
  border-radius: var(--radius-sm, 4px);
  font-size: 0.75rem;
  cursor: pointer;
  font-weight: 600;
}

.btn-primary {
  background: var(--phosphor);
  border-color: var(--phosphor);
  color: var(--void);
}

.btn-sm {
  padding: 0.25rem 0.5rem;
  font-size: 0.6875rem;
}

.text-emerald {
  color: var(--long);
}

.text-rose {
  color: var(--short);
}

.text-call {
  color: var(--call-hi);
}

.text-call-hi {
  color: var(--call-hi);
}

.text-phosphor {
  color: var(--phosphor);
}

.text-muted {
  color: var(--ink-faint);
}

.text-center {
  text-align: center;
}

@media (max-width: 1024px) {
  .hero-grid,
  .bottom-grid,
  .tactical-body-grid {
    grid-template-columns: 1fr;
  }
}
</style>
