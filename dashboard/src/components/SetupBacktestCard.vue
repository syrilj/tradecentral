<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '@/api'
import type { BacktestTearsheet } from '@/microstructureContracts'
import { DASH, num, pct, signedPct, usd } from '@/format'
import { classifyBacktestEdge } from '@/setupBacktest'

const props = defineProps<{
  symbol: string
}>()

export type BacktestWindow = '3M' | '6M' | '1Y' | '2Y' | 'ALL'
const WINDOW_OPTIONS: readonly BacktestWindow[] = ['3M', '6M', '1Y', '2Y', 'ALL'] as const

const windowOption = ref<BacktestWindow>('1Y')
const tearsheet = ref<BacktestTearsheet | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const showTrades = ref(false)

const activeScrubIndex = ref<number | null>(null)

let fetchCounter = 0

async function loadBacktest(): Promise<void> {
  const currentSymbol = props.symbol?.trim()
  if (!currentSymbol) {
    tearsheet.value = null
    error.value = null
    activeScrubIndex.value = null
    return
  }

  const currentFetchId = ++fetchCounter
  loading.value = true
  error.value = null
  activeScrubIndex.value = null

  try {
    const data = await api.systematicBacktest(currentSymbol, {
      window: windowOption.value.toLowerCase(),
      capital: 100_000,
      risk_pct: 0.02,
      slippage_bps: 2.0,
      bars: 'daily',
    })
    if (currentFetchId === fetchCounter) {
      tearsheet.value = data
    }
  } catch (err) {
    if (currentFetchId === fetchCounter) {
      error.value = err instanceof Error ? err.message : 'Failed to compute backtest'
      tearsheet.value = null
    }
  } finally {
    if (currentFetchId === fetchCounter) {
      loading.value = false
    }
  }
}

watch(
  () => [props.symbol, windowOption.value],
  () => {
    void loadBacktest()
  },
  { immediate: true },
)

const edgeStatus = computed(() => {
  if (!tearsheet.value) return null
  const status = classifyBacktestEdge({
    total_trades: tearsheet.value.total_trades,
    profit_factor: tearsheet.value.profit_factor,
    win_rate: tearsheet.value.win_rate,
    window: windowOption.value,
  })
  return {
    ...status,
    class: `edge-${status.tone}`,
  }
})

const recentTrades = computed(() => {
  if (!tearsheet.value?.trades) return []
  return tearsheet.value.trades.slice(-8).reverse()
})

const totalFriction = computed(() => {
  if (!tearsheet.value) return null
  return (tearsheet.value.total_slippage || 0) + (tearsheet.value.total_commissions || 0)
})

/* SVG Equity Curve Chart Math */
const chartData = computed(() => {
  const curve = tearsheet.value?.equity_curve
  if (!curve || curve.length < 2) return null

  const initial = tearsheet.value?.initial_capital || 100_000
  let min = initial
  let max = initial
  for (const pt of curve) {
    if (pt.equity < min) min = pt.equity
    if (pt.equity > max) max = pt.equity
  }
  const pad = Math.max((max - min) * 0.12, initial * 0.005)
  const yMin = min - pad
  const yMax = max + pad
  const yRange = yMax - yMin || 1

  const width = 500
  const height = 120
  const padTop = 10
  const padBottom = 16
  const padLeft = 8
  const padRight = 8
  const drawWidth = width - padLeft - padRight
  const drawHeight = height - padTop - padBottom

  const n = curve.length
  const points = curve.map((pt, i) => {
    const x = padLeft + (i / (n - 1)) * drawWidth
    const y = height - padBottom - ((pt.equity - yMin) / yRange) * drawHeight
    return { x: Number(x.toFixed(1)), y: Number(y.toFixed(1)), pt }
  })

  const baseY = height - padBottom - ((initial - yMin) / yRange) * drawHeight

  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')
  const areaD = `${pathD} L ${points[points.length - 1].x} ${baseY.toFixed(1)} L ${points[0].x} ${baseY.toFixed(1)} Z`

  return {
    width,
    height,
    points,
    pathD,
    areaD,
    baseY: Number(baseY.toFixed(1)),
    isProfitable: (tearsheet.value?.total_net_pnl || 0) >= 0,
    initial,
  }
})

const activeScrubPoint = computed(() => {
  if (activeScrubIndex.value == null || !chartData.value) return null
  return chartData.value.points[activeScrubIndex.value] || null
})

const activeScrub = computed(() => {
  const sp = activeScrubPoint.value
  if (!sp || !chartData.value) return null
  const pt = sp.pt
  const returnPct = ((pt.equity - chartData.value.initial) / chartData.value.initial) * 100
  return {
    date: pt.timestamp ? String(pt.timestamp).slice(0, 10) : `Bar ${pt.bar}`,
    equity: pt.equity,
    returnPct,
    spot: pt.spot,
  }
})

function onChartMouseMove(event: MouseEvent) {
  const data = chartData.value
  if (!data) return
  const target = event.currentTarget as SVGSVGElement
  const rect = target.getBoundingClientRect()
  if (rect.width <= 0) return
  const mouseX = event.clientX - rect.left
  const pctRatio = Math.max(0, Math.min(1, mouseX / rect.width))
  activeScrubIndex.value = Math.min(
    data.points.length - 1,
    Math.max(0, Math.round(pctRatio * (data.points.length - 1))),
  )
}

function onChartMouseLeave() {
  activeScrubIndex.value = null
}
</script>

<template>
  <section class="setup-backtest-card" aria-label="Setup Microstructure Backtest">
    <header class="card-header">
      <div class="title-meta">
        <span class="eyebrow label">Realistic execution validation</span>
        <h3 class="title">Systematic Edge Verification</h3>
      </div>
      <div class="controls">
        <div class="window-toggle" role="group" aria-label="Backtest window selector">
          <button
            v-for="win in WINDOW_OPTIONS"
            :key="win"
            type="button"
            class="window-btn"
            :class="{ active: windowOption === win }"
            :disabled="loading"
            @click="windowOption = win"
          >
            {{ win }}
          </button>
        </div>
        <button
          type="button"
          class="refresh-btn"
          :disabled="loading"
          title="Re-run simulation"
          @click="loadBacktest"
        >
          <span v-if="loading" class="spinner" aria-hidden="true" />
          <span v-else>↻</span>
        </button>
      </div>
    </header>

    <div v-if="loading && !tearsheet" class="loading-state">
      <span class="label">Simulating sequential event-driven execution for {{ symbol }}...</span>
    </div>

    <div v-else-if="error" class="error-state">
      <span class="label error-text">Simulation failed: {{ error }}</span>
      <button type="button" class="retry-btn" @click="loadBacktest">Retry</button>
    </div>

    <div v-else-if="tearsheet" class="backtest-content">
      <!-- Edge Assessment Banner -->
      <div v-if="edgeStatus" class="edge-banner" :class="edgeStatus.class">
        <div class="edge-headline">
          <span class="status-indicator" />
          <strong class="label">{{ edgeStatus.label }}</strong>
        </div>
        <p class="edge-desc">{{ edgeStatus.detail }}</p>
      </div>

      <!-- Interactive SVG Equity Curve Mini-Chart -->
      <div v-if="chartData" class="equity-chart-box">
        <div class="chart-readout-row">
          <div class="chart-title-tag">
            <span class="label chart-tag">EQUITY CURVE</span>
            <span class="chart-dates label mute">
              {{ tearsheet.start_date ? tearsheet.start_date.slice(0, 10) : 'Start' }} →
              {{ tearsheet.end_date ? tearsheet.end_date.slice(0, 10) : 'End' }}
            </span>
          </div>
          <div v-if="activeScrub" class="scrub-readout">
            <span class="scrub-date label">{{ activeScrub.date }}</span>
            <span
              class="scrub-val fig"
              :class="{
                pos: activeScrub.equity >= chartData.initial,
                neg: activeScrub.equity < chartData.initial,
              }"
            >
              {{ usd(activeScrub.equity) }} ({{ signedPct(activeScrub.returnPct, 1) }})
            </span>
            <span class="scrub-spot label">Spot {{ num(activeScrub.spot, 2) }}</span>
          </div>
          <div v-else class="scrub-readout idle">
            <span class="label mute">Hover curve to inspect point-in-time equity</span>
          </div>
        </div>

        <div class="svg-container">
          <svg
            class="equity-svg"
            role="img"
            aria-label="Systematic backtest equity curve"
            viewBox="0 0 500 120"
            preserveAspectRatio="none"
            @mousemove="onChartMouseMove"
            @mouseleave="onChartMouseLeave"
          >
            <defs>
              <linearGradient id="eqGreenGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#10b981" stop-opacity="0.30" />
                <stop offset="100%" stop-color="#10b981" stop-opacity="0.0" />
              </linearGradient>
              <linearGradient id="eqRedGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#f43f5e" stop-opacity="0.30" />
                <stop offset="100%" stop-color="#f43f5e" stop-opacity="0.0" />
              </linearGradient>
            </defs>

            <!-- Starting Capital Baseline -->
            <line
              x1="0"
              :y1="chartData.baseY"
              x2="500"
              :y2="chartData.baseY"
              class="baseline-line"
            />
            <text x="8" :y="chartData.baseY - 4" class="baseline-text">$100k Base</text>

            <!-- Area fill -->
            <path
              :d="chartData.areaD"
              :fill="chartData.isProfitable ? 'url(#eqGreenGrad)' : 'url(#eqRedGrad)'"
              class="equity-area"
            />

            <!-- Stroke curve -->
            <path
              :d="chartData.pathD"
              class="equity-stroke"
              :class="{ pos: chartData.isProfitable, neg: !chartData.isProfitable }"
            />

            <!-- Active Scrub Guide Line & Dot -->
            <g v-if="activeScrubPoint">
              <line
                :x1="activeScrubPoint.x"
                y1="0"
                :x2="activeScrubPoint.x"
                y2="120"
                class="scrub-guide-line"
              />
              <circle
                :cx="activeScrubPoint.x"
                :cy="activeScrubPoint.y"
                r="3.5"
                class="scrub-dot"
                :class="{
                  pos: activeScrubPoint.pt.equity >= chartData.initial,
                  neg: activeScrubPoint.pt.equity < chartData.initial,
                }"
              />
            </g>
          </svg>
        </div>
      </div>

      <!-- Core Metrics Bento Grid -->
      <div class="metrics-grid">
        <div class="metric-cell">
          <span class="label">Win Rate</span>
          <span class="fig metric-val">{{ pct(tearsheet.win_rate, 1) }}</span>
          <span class="metric-sub"
            >{{ tearsheet.winning_trades }}W / {{ tearsheet.losing_trades }}L ({{
              tearsheet.total_trades
            }}
            total)</span
          >
        </div>

        <div class="metric-cell">
          <span class="label">Profit Factor</span>
          <span
            class="fig metric-val"
            :class="{
              pos: tearsheet.profit_factor >= 1.2,
              warn: tearsheet.profit_factor >= 1.0 && tearsheet.profit_factor < 1.2,
              neg: tearsheet.profit_factor < 1.0,
            }"
          >
            {{ num(tearsheet.profit_factor, 2) }}
          </span>
          <span class="metric-sub">Win/Loss: {{ num(tearsheet.win_loss_ratio, 2) }}</span>
        </div>

        <div class="metric-cell">
          <span class="label">Net Return</span>
          <span
            class="fig metric-val"
            :class="{ pos: tearsheet.total_net_pnl > 0, neg: tearsheet.total_net_pnl < 0 }"
          >
            {{ signedPct(tearsheet.total_return_pct, 1) }}
          </span>
          <span class="metric-sub">{{ usd(tearsheet.total_net_pnl) }}</span>
        </div>

        <div class="metric-cell">
          <span class="label">Max Drawdown</span>
          <span class="fig metric-val neg">{{ pct(tearsheet.max_drawdown_pct, 1) }}</span>
          <span class="metric-sub">{{ usd(tearsheet.max_drawdown_dollar) }}</span>
        </div>

        <div class="metric-cell">
          <span class="label">Sharpe Ratio</span>
          <span class="fig metric-val">{{ num(tearsheet.sharpe_ratio, 2) }}</span>
          <span class="metric-sub">Sortino: {{ num(tearsheet.sortino_ratio, 2) }}</span>
        </div>

        <div class="metric-cell">
          <span class="label">Expectancy / Trade</span>
          <span
            class="fig metric-val"
            :class="{
              pos: tearsheet.expectancy_per_trade > 0,
              neg: tearsheet.expectancy_per_trade < 0,
            }"
          >
            {{ usd(tearsheet.expectancy_per_trade) }}
          </span>
          <span class="metric-sub">Avg hold: {{ num(tearsheet.avg_holding_bars, 1) }} bars</span>
        </div>
      </div>

      <!-- Friction and Realism Disclosures -->
      <div class="realism-box">
        <div class="realism-title-row">
          <span class="label realism-tag">HONEST FRICTION MODEL</span>
          <span v-if="totalFriction != null" class="friction-deducted">
            Friction deducted: {{ usd(totalFriction) }}
          </span>
        </div>
        <p class="realism-copy">
          Simulation models 2.0 bps entry/exit slippage and $0.005/share commissions across
          {{ tearsheet.n_bars }} daily bars with strictly zero lookahead.
          {{
            tearsheet.gamma_conditioned
              ? 'Dealer gamma regime conditioned.'
              : 'Unconditioned microstructure basis (no historical chain archive).'
          }}
        </p>
      </div>

      <!-- Simulated Trades Toggle -->
      <div v-if="recentTrades.length" class="trades-preview">
        <button type="button" class="trades-toggle-btn label" @click="showTrades = !showTrades">
          <span
            >{{ showTrades ? 'Hide recent simulated trades' : 'Show recent simulated trades' }} ({{
              recentTrades.length
            }})</span
          >
          <span class="toggle-arrow">{{ showTrades ? '▴' : '▾' }}</span>
        </button>

        <div v-if="showTrades" class="trades-table-wrap">
          <table class="trades-table">
            <thead>
              <tr>
                <th class="label">Date</th>
                <th class="label">Side</th>
                <th class="label">Setup</th>
                <th class="label">Entry</th>
                <th class="label">Exit</th>
                <th class="label">Hold</th>
                <th class="label">Reason</th>
                <th class="label text-right">Net PnL</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="tr in recentTrades" :key="tr.trade_id">
                <td class="date-col">{{ tr.entry_time ? tr.entry_time.slice(0, 10) : DASH }}</td>
                <td :class="tr.direction === 'long' ? 'side-long' : 'side-short'">
                  {{ tr.direction.toUpperCase() }}
                </td>
                <td class="setup-name-col">{{ tr.setup_name.replaceAll('_', ' ') }}</td>
                <td class="fig">{{ num(tr.entry_price, 2) }}</td>
                <td class="fig">{{ tr.exit_price != null ? num(tr.exit_price, 2) : 'Active' }}</td>
                <td>{{ tr.holding_bars }}b</td>
                <td>
                  <span class="reason-pill" :class="tr.exit_reason || 'open'">{{
                    (tr.exit_reason || 'open').replaceAll('_', ' ')
                  }}</span>
                </td>
                <td class="fig text-right" :class="{ pos: tr.net_pnl > 0, neg: tr.net_pnl < 0 }">
                  {{ usd(tr.net_pnl) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      <span class="label mute">No historical simulation data available for {{ symbol }}.</span>
    </div>
  </section>
</template>

<style scoped>
.setup-backtest-card {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 0.85rem;
  background: var(--bg-card, #111417);
  border: 1px solid var(--border, #22262c);
  border-radius: 4px;
  font-family: var(--font-sans, system-ui, -apple-system, sans-serif);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.5rem;
  border-bottom: 1px solid var(--border-subtle, #1c2026);
  padding-bottom: 0.5rem;
}

.title-meta {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.eyebrow {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-dim, #717d8a);
}

.title {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-primary, #e6ecf1);
  letter-spacing: 0.02em;
}

.controls {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.window-toggle {
  display: flex;
  background: var(--bg-well, #0a0c0e);
  border: 1px solid var(--border-subtle, #1c2026);
  border-radius: 3px;
  padding: 1px;
}

.window-btn {
  background: transparent;
  border: none;
  color: var(--text-dim, #717d8a);
  font-size: 0.65rem;
  font-family: var(--font-mono, monospace);
  padding: 0.2rem 0.45rem;
  cursor: pointer;
  border-radius: 2px;
  transition: all 0.15s ease;
}

.window-btn:hover:not(:disabled) {
  color: var(--text-primary, #e6ecf1);
}

.window-btn.active {
  background: var(--border, #22262c);
  color: var(--text-primary, #ffffff);
  font-weight: 600;
}

.window-btn:disabled,
.refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.refresh-btn {
  background: var(--bg-well, #0a0c0e);
  border: 1px solid var(--border-subtle, #1c2026);
  color: var(--text-dim, #717d8a);
  font-size: 0.75rem;
  width: 1.5rem;
  height: 1.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.refresh-btn:hover:not(:disabled) {
  color: var(--text-primary, #e6ecf1);
  border-color: var(--border, #22262c);
}

.spinner {
  width: 0.7rem;
  height: 0.7rem;
  border: 1px solid var(--text-dim, #717d8a);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.loading-state,
.empty-state,
.error-state {
  padding: 1rem;
  text-align: center;
  background: var(--bg-well, #0a0c0e);
  border-radius: 3px;
}

.error-text {
  color: var(--red, #f43f5e);
  font-size: 0.72rem;
}

.retry-btn {
  margin-top: 0.5rem;
  padding: 0.25rem 0.6rem;
  font-size: 0.7rem;
  background: var(--border, #22262c);
  color: var(--text-primary, #e6ecf1);
  border: 1px solid var(--border-subtle, #1c2026);
  border-radius: 3px;
  cursor: pointer;
}

.backtest-content {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* Edge Banner */
.edge-banner {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.5rem 0.65rem;
  border-radius: 3px;
  border-left: 3px solid transparent;
}

.edge-headline {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.status-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.edge-desc {
  margin: 0;
  font-size: 0.7rem;
  color: var(--text-dim, #8b99a7);
  line-height: 1.3;
}

.edge-confirmed {
  background: rgba(16, 185, 129, 0.08);
  border-left-color: var(--green, #10b981);
}
.edge-confirmed .status-indicator {
  background: var(--green, #10b981);
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.5);
}
.edge-confirmed .label {
  color: var(--green, #10b981);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.05em;
}

.edge-marginal {
  background: rgba(245, 158, 11, 0.08);
  border-left-color: var(--amber, #f59e0b);
}
.edge-marginal .status-indicator {
  background: var(--amber, #f59e0b);
}
.edge-marginal .label {
  color: var(--amber, #f59e0b);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.05em;
}

.edge-negative {
  background: rgba(244, 63, 94, 0.08);
  border-left-color: var(--red, #f43f5e);
}
.edge-negative .status-indicator {
  background: var(--red, #f43f5e);
}
.edge-negative .label {
  color: var(--red, #f43f5e);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.05em;
}

.sample-low,
.edge-sample-low {
  background: rgba(113, 125, 138, 0.08);
  border-left-color: var(--text-dim, #717d8a);
}
.sample-low .status-indicator,
.edge-sample-low .status-indicator {
  background: var(--text-dim, #717d8a);
}
.sample-low .label,
.edge-sample-low .label {
  color: var(--text-dim, #717d8a);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.05em;
}

/* Equity Chart Box */
.equity-chart-box {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.5rem 0.65rem;
  background: var(--bg-well, #0a0c0e);
  border: 1px solid var(--border-subtle, #1c2026);
  border-radius: 3px;
}

.chart-readout-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 1.2rem;
}

.chart-title-tag {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.chart-tag {
  font-size: 0.62rem;
  font-weight: 600;
  color: var(--text-dim, #717d8a);
  letter-spacing: 0.06em;
}

.chart-dates {
  font-size: 0.6rem;
  font-family: var(--font-mono, monospace);
  color: var(--text-dim, #56616d);
}

.scrub-readout {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.68rem;
}

.scrub-date {
  color: var(--text-dim, #717d8a);
}

.scrub-val {
  font-weight: 600;
}

.scrub-spot {
  font-size: 0.62rem;
  color: var(--text-dim, #56616d);
}

.idle {
  color: var(--text-dim, #56616d);
  font-size: 0.62rem;
}

.svg-container {
  width: 100%;
  height: 90px;
  position: relative;
  overflow: hidden;
}

.equity-svg {
  width: 100%;
  height: 100%;
  display: block;
  cursor: crosshair;
}

.baseline-line {
  stroke: var(--border-subtle, #252b33);
  stroke-dasharray: 3 3;
  stroke-width: 1;
}

.baseline-text {
  font-size: var(--t-nano);
  fill: var(--text-dim, #56616d);
  font-family: var(--font-mono, monospace);
}

.equity-stroke {
  fill: none;
  stroke-width: 1.5;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.equity-stroke.pos {
  stroke: var(--green, #10b981);
}

.equity-stroke.neg {
  stroke: var(--red, #f43f5e);
}

.scrub-guide-line {
  stroke: rgba(255, 255, 255, 0.25);
  stroke-dasharray: 2 2;
  stroke-width: 1;
}

.scrub-dot {
  stroke: #ffffff;
  stroke-width: 1.5;
}

.scrub-dot.pos {
  fill: var(--green, #10b981);
}

.scrub-dot.neg {
  fill: var(--red, #f43f5e);
}

/* Metrics Bento Grid */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.4rem;
}

.metric-cell {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  padding: 0.45rem 0.5rem;
  background: var(--bg-well, #0a0c0e);
  border: 1px solid var(--border-subtle, #1c2026);
  border-radius: 3px;
}

.metric-cell .label {
  font-size: 0.62rem;
  color: var(--text-dim, #717d8a);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.metric-val {
  font-size: 0.95rem;
  font-weight: 600;
  font-family: var(--font-mono, monospace);
  color: var(--text-primary, #e6ecf1);
}

.metric-sub {
  font-size: 0.62rem;
  font-family: var(--font-mono, monospace);
  color: var(--text-dim, #717d8a);
}

.pos {
  color: var(--green, #10b981) !important;
}

.warn {
  color: var(--amber, #f59e0b) !important;
}

.neg {
  color: var(--red, #f43f5e) !important;
}

/* Realism Disclosures */
.realism-box {
  padding: 0.5rem 0.65rem;
  background: var(--bg-well, #0a0c0e);
  border: 1px solid var(--border-subtle, #1c2026);
  border-radius: 3px;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.realism-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.realism-tag {
  font-size: 0.6rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--accent, #6366f1);
}

.friction-deducted {
  font-size: 0.62rem;
  font-family: var(--font-mono, monospace);
  color: var(--amber, #f59e0b);
}

.realism-copy {
  margin: 0;
  font-size: 0.68rem;
  color: var(--text-dim, #8b99a7);
  line-height: 1.35;
}

/* Simulated Trades Preview */
.trades-preview {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.trades-toggle-btn {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: transparent;
  border: 1px solid var(--border-subtle, #1c2026);
  border-radius: 3px;
  padding: 0.35rem 0.5rem;
  color: var(--text-dim, #717d8a);
  font-size: 0.68rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.trades-toggle-btn:hover {
  color: var(--text-primary, #e6ecf1);
  background: var(--bg-well, #0a0c0e);
}

.trades-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--border-subtle, #1c2026);
  border-radius: 3px;
}

.trades-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.68rem;
  font-family: var(--font-mono, monospace);
}

.trades-table th {
  background: var(--bg-well, #0a0c0e);
  color: var(--text-dim, #717d8a);
  text-align: left;
  padding: 0.3rem 0.45rem;
  font-weight: 500;
  font-size: 0.6rem;
  border-bottom: 1px solid var(--border-subtle, #1c2026);
}

.trades-table td {
  padding: 0.3rem 0.45rem;
  border-bottom: 1px solid var(--border-subtle, #14181d);
  color: var(--text-primary, #c9d3dd);
}

.setup-name-col {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.62rem;
  color: var(--text-dim, #8b99a7);
}

.reason-pill {
  padding: 0.1rem 0.3rem;
  border-radius: 2px;
  font-size: var(--t-nano);
  text-transform: uppercase;
}

.reason-pill.take_profit {
  background: rgba(16, 185, 129, 0.12);
  color: var(--green, #10b981);
}

.reason-pill.stop_loss {
  background: rgba(244, 63, 94, 0.12);
  color: var(--red, #f43f5e);
}

.reason-pill.trailing_stop {
  background: rgba(245, 158, 11, 0.12);
  color: var(--amber, #f59e0b);
}

.side-long {
  color: var(--green, #10b981);
  font-weight: 600;
}

.side-short {
  color: var(--red, #f43f5e);
  font-weight: 600;
}

.text-right {
  text-align: right;
}
</style>
