<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type OptionsIntelligence, type OptionsProbability } from '@/api'
import { useChartSize } from '@/composables/useChartSize'
import { debounce } from '@/composables/useResource'
import { DASH, num, usd } from '@/format'
import {
  asStrategy,
  bookAllocation,
  buildPayoffChart,
  calculateStrategyPoP,
  computeBookGreeks,
  evaluateBookDualCurves,
  evaluateRiskRewardBounds,
  findBreakevens,
  netDebit,
  nextLegId,
  samplePnlRows,
  seedBook,
  STRATEGY_PRESETS,
  usableLegs,
  type CalcLeg,
  type CalcStrategy,
  type OptionRight,
} from '@/optionsCalculator'
import Panel from '@/components/Panel.vue'
import ProbabilityDensityChart from '@/components/ProbabilityDensityChart.vue'
import Readout from '@/components/Readout.vue'

const props = defineProps<{
  defaultStrategy?: CalcStrategy | string | null
  defaultSpot?: number | null
  defaultStrike?: number | null
  defaultDte?: number | null
  defaultVol?: number | null
  defaultPremium?: number | null
  symbol?: string | null
}>()

const QUICK_TICKERS = ['SPY', 'QQQ', 'NVDA', 'AAPL', 'TSLA', 'MSFT', 'AMZN', 'AMD', 'META', 'GOOGL']

const symbolInput = ref(props.symbol ? props.symbol.toUpperCase() : '')
const strategy = ref<CalcStrategy>(asStrategy(props.defaultStrategy))
const spot = ref(props.defaultSpot && props.defaultSpot > 0 ? props.defaultSpot : 100)
const strikeHint = ref(props.defaultStrike && props.defaultStrike > 0 ? props.defaultStrike : 105)
const dte = ref(props.defaultDte != null && props.defaultDte >= 0 ? props.defaultDte : 30)
const volPct = ref(props.defaultVol && props.defaultVol > 0 ? props.defaultVol * 100 : 30)
const skewPct = ref(0)
const smilePct = ref(0)
const premiumHint = ref(
  props.defaultPremium != null && props.defaultPremium >= 0 ? props.defaultPremium : 5,
)
const callWall = ref<number | null>(null)
const putWall = ref<number | null>(null)

const liveIntel = ref<OptionsIntelligence | null>(null)
const syncingLive = ref(false)
const syncError = ref<string | null>(null)

const legs = ref<CalcLeg[]>(
  seedBook({
    strategy: strategy.value === 'custom' ? 'long_call' : strategy.value,
    strike: strikeHint.value,
    premium: premiumHint.value,
    dte: dte.value,
    vol: volPct.value,
  }),
)
const error = ref<string | null>(null)
const loading = ref(false)
const result = ref<{
  spot: number
  greeks: { delta: number; gamma: number; theta: number; vega: number; rho?: number; theo: number }
  pnl_at_expiry: Array<{ spot: number; pnl: number }>
  legs: Array<Record<string, unknown>>
} | null>(null)

async function syncLive(targetSym?: string): Promise<void> {
  const sym = (targetSym || symbolInput.value).trim().toUpperCase()
  if (!sym) return
  syncingLive.value = true
  syncError.value = null
  try {
    const intel = await api.options({ symbol: sym, mode: 'live' })
    liveIntel.value = intel
    symbolInput.value = sym
    if (intel.summary?.spot && intel.summary.spot > 0) {
      spot.value = Math.round(intel.summary.spot * 100) / 100
    }
    if (intel.probability?.atm_iv && intel.probability.atm_iv > 0) {
      volPct.value = Math.round(intel.probability.atm_iv * 1000) / 10
    }
    if (intel.probability?.horizon_days && intel.probability.horizon_days > 0) {
      dte.value = intel.probability.horizon_days
    }
    if (intel.summary?.call_wall) {
      callWall.value = intel.summary.call_wall
    }
    if (intel.summary?.put_wall) {
      putWall.value = intel.summary.put_wall
    }
    if (strategy.value !== 'custom' && spot.value > 0) {
      strikeHint.value = Math.round(spot.value)
      legs.value = seedBook({
        strategy: strategy.value,
        strike: strikeHint.value,
        premium: premiumHint.value,
        dte: dte.value,
        vol: volPct.value,
      })
    }
  } catch (err) {
    syncError.value = err instanceof Error ? err.message : 'Live chain sync failed'
  } finally {
    syncingLive.value = false
  }
}

function selectQuickTicker(sym: string): void {
  symbolInput.value = sym
  void syncLive(sym)
}

watch(
  () => props.symbol,
  (value) => {
    if (value && value.trim()) {
      symbolInput.value = value.trim().toUpperCase()
      void syncLive(value.trim().toUpperCase())
    }
  },
  { immediate: true },
)

watch(
  () => props.defaultStrategy,
  (value) => {
    if (!value) return
    applyPreset(asStrategy(value))
  },
)
watch(
  () => props.defaultSpot,
  (value) => {
    if (value && value > 0) spot.value = value
  },
)
watch(
  () => props.defaultStrike,
  (value) => {
    if (value && value > 0) {
      strikeHint.value = value
      if (strategy.value !== 'custom') {
        legs.value = seedBook({
          strategy: strategy.value,
          strike: value,
          premium: premiumHint.value,
          dte: dte.value,
          vol: volPct.value,
        })
      }
    }
  },
)
watch(
  () => props.defaultDte,
  (value) => {
    if (value != null && value >= 0) dte.value = value
  },
)
watch(
  () => props.defaultVol,
  (value) => {
    if (value && value > 0) volPct.value = value * 100
  },
)
watch(
  () => props.defaultPremium,
  (value) => {
    if (value != null && value >= 0) {
      premiumHint.value = value
      if (strategy.value !== 'custom') {
        legs.value = seedBook({
          strategy: strategy.value,
          strike: strikeHint.value,
          premium: value,
          dte: dte.value,
          vol: volPct.value,
        })
      }
    }
  },
)
watch(strikeHint, (value) => {
  if (strategy.value !== 'custom' && value > 0) {
    legs.value = seedBook({
      strategy: strategy.value,
      strike: value,
      premium: premiumHint.value,
      dte: dte.value,
      vol: volPct.value,
    })
  }
})

const activePresetMeta = computed(() =>
  strategy.value !== 'custom' ? STRATEGY_PRESETS[strategy.value] : null,
)

const strategyLabel = computed(() => {
  if (strategy.value === 'custom') return 'Custom book'
  return STRATEGY_PRESETS[strategy.value]?.label ?? 'Options Strategy'
})

const book = computed(() => usableLegs(legs.value))
const debit = computed(() => netDebit(legs.value))
const allocation = computed(() => bookAllocation(legs.value))

// High-speed client-side dual curve and Greeks calculation
const dualSeries = computed(() =>
  evaluateBookDualCurves({
    legs: legs.value,
    spot: spot.value,
    dteDays: dte.value,
    volPct: volPct.value,
    skewPct: skewPct.value,
    smilePct: smilePct.value,
  }),
)

const clientGreeks = computed(() =>
  computeBookGreeks(legs.value, spot.value, dte.value, volPct.value),
)

const bounds = computed(() => evaluateRiskRewardBounds(legs.value, dualSeries.value))
const breakevens = computed(() => findBreakevens(dualSeries.value))
const samplePnl = computed(() =>
  samplePnlRows(dualSeries.value, [spot.value, ...legs.value.map((leg) => Number(leg.strike))]),
)

const strategyPoP = computed(() =>
  calculateStrategyPoP({
    legs: legs.value,
    spot: spot.value,
    dteDays: dte.value,
    volPct: volPct.value,
    breakevens: breakevens.value,
  }),
)

const activeProbability = computed<OptionsProbability | null>(() => {
  if (
    liveIntel.value?.probability?.available &&
    liveIntel.value.probability.atm_iv &&
    liveIntel.value.probability.horizon_days
  ) {
    return liveIntel.value.probability
  }
  const S = Number(spot.value)
  const iv = volPct.value > 2.0 ? volPct.value / 100 : volPct.value
  const T = Math.max(dte.value, 1) / 365.0
  const sigma = iv * Math.sqrt(T)
  const expMove = S * sigma
  return {
    available: true,
    method: 'black_scholes_lognormal',
    atm_iv: iv,
    horizon_days: dte.value,
    expected_move: expMove,
    expected_low: Math.max(0.01, S - expMove),
    expected_high: S + expMove,
    prob_above_call_wall: null,
    prob_below_put_wall: null,
    prob_between_walls: null,
  }
})

const chartHost = ref<HTMLElement | null>(null)
const { W: chartW } = useChartSize(chartHost, {
  minW: 320,
  minH: 220,
  fallbackW: 720,
  fallbackH: 240,
})
const hoverX = ref<number | null>(null)

const payoff = computed(() =>
  buildPayoffChart({
    series: dualSeries.value,
    spot: spot.value,
    strikes: legs.value,
    width: chartW.value,
    height: 240,
    bounds: bounds.value,
  }),
)

const hoverRead = computed(() => {
  const chart = payoff.value
  const series = dualSeries.value
  if (!chart || hoverX.value == null || series.length < 2) return null
  const t = (hoverX.value - chart.pad.l) / Math.max(1, chart.plotWidth)
  const idx = Math.min(series.length - 1, Math.max(0, Math.round(t * (series.length - 1))))
  const point = series[idx]
  return {
    x: Math.min(chart.width - chart.pad.r, Math.max(chart.pad.l, hoverX.value)),
    spot: point.spot,
    pnl: point.pnlExpiry,
    t0Pnl: point.pnlTheo,
  }
})

function onChartMove(event: PointerEvent): void {
  const host = chartHost.value
  if (!host || !payoff.value) return
  const box = host.getBoundingClientRect()
  const x = ((event.clientX - box.left) / Math.max(1, box.width)) * payoff.value.width
  hoverX.value = x
}

function onChartLeave(): void {
  hoverX.value = null
}

function axisMoney(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 1000) return `${value < 0 ? '−' : ''}${usd(abs, 0)}`
  return usd(value, value % 1 === 0 ? 0 : 2)
}

function sharePct(value: number | null): string {
  return value == null ? DASH : `${Math.round(value * 100)}%`
}

function applyPreset(next: CalcStrategy): void {
  strategy.value = next === 'custom' ? 'custom' : next
  if (next === 'custom') return
  legs.value = seedBook({
    strategy: next,
    strike: strikeHint.value,
    premium: premiumHint.value,
    dte: dte.value,
    vol: volPct.value,
  })
}

function addLeg(): void {
  const last = legs.value[legs.value.length - 1]
  legs.value = [
    ...legs.value,
    {
      id: nextLegId(legs.value),
      right: last?.right ?? 'call',
      strike: last?.strike ?? strikeHint.value,
      quantity: last && last.quantity < 0 ? -1 : 1,
      premium: last?.premium ?? premiumHint.value,
      dte: last?.dte ?? dte.value,
      vol: last?.vol ?? volPct.value,
    },
  ]
  strategy.value = 'custom'
}

function removeLeg(id: string): void {
  if (legs.value.length <= 1) return
  legs.value = legs.value.filter((leg) => leg.id !== id)
  strategy.value = 'custom'
}

function patchLeg(id: string, patch: Partial<CalcLeg>): void {
  legs.value = legs.value.map((leg) => (leg.id === id ? { ...leg, ...patch } : leg))
  strategy.value = 'custom'
}

function setSide(leg: CalcLeg, sign: 1 | -1): void {
  const mag = Math.abs(Number(leg.quantity)) || 1
  patchLeg(leg.id, { quantity: sign * mag })
}

function setRight(leg: CalcLeg, right: OptionRight): void {
  patchLeg(leg.id, { right })
}

function setQty(leg: CalcLeg, event: Event): void {
  const mag = Math.abs(Number((event.target as HTMLInputElement).value))
  const sign = Number(leg.quantity) < 0 ? -1 : 1
  patchLeg(leg.id, { quantity: (Number.isFinite(mag) && mag > 0 ? mag : 1) * sign })
}

function setStrike(leg: CalcLeg, event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  patchLeg(leg.id, { strike: value })
  if (value > 0) strikeHint.value = value
}

function setPremium(leg: CalcLeg, event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  patchLeg(leg.id, { premium: value })
  if (value >= 0) premiumHint.value = value
}

function setLegVol(leg: CalcLeg, event: Event): void {
  const raw = (event.target as HTMLInputElement).value
  const value = raw === '' ? undefined : Number(raw)
  patchLeg(leg.id, {
    vol: value != null && Number.isFinite(value) && value > 0 ? value : undefined,
  })
}

async function run(): Promise<void> {
  const priced = book.value
  if (!priced.length) {
    result.value = null
    error.value = 'Add a contract to the book'
    loading.value = false
    return
  }
  loading.value = true
  error.value = null
  try {
    result.value = await api.optionsCalculator({
      strategy: strategy.value,
      spot: spot.value,
      strike: priced[0].strike,
      dte: dte.value,
      vol: volPct.value / 100,
      premium: priced[0].premium,
      legs: priced,
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Calculator unavailable'
  } finally {
    loading.value = false
  }
}

const refresh = debounce(run, 250)
watch(
  [strategy, spot, strikeHint, dte, volPct, skewPct, smilePct, legs],
  () => {
    void refresh()
  },
  { immediate: true, deep: true },
)
</script>

<template>
  <div class="calc">
    <!-- Underlier & Live Chain Sync Shelf -->
    <div class="underlier-shelf">
      <div class="symbol-sync-group">
        <span class="label group-tag">UNDERLIER</span>
        <div class="symbol-input-box">
          <input
            v-model="symbolInput"
            type="text"
            placeholder="TICKER (e.g. SPY, NVDA)"
            class="sym-input"
            @keyup.enter="syncLive()"
          />
          <button
            type="button"
            class="btn-quiet sync-btn"
            :disabled="syncingLive || !symbolInput.trim()"
            @click="syncLive()"
          >
            {{ syncingLive ? 'SYNCING LIVE…' : 'SYNC LIVE CHAIN' }}
          </button>
        </div>
        <div class="quick-tickers">
          <button
            v-for="sym in QUICK_TICKERS"
            :key="sym"
            type="button"
            class="btn-quiet ticker-pill"
            :class="{ on: symbolInput.toUpperCase() === sym }"
            @click="selectQuickTicker(sym)"
          >
            {{ sym }}
          </button>
        </div>
      </div>
      <div v-if="liveIntel?.summary" class="live-meta-facts">
        <span class="gex-meta-badge">LIVE SPOT {{ usd(liveIntel.summary.spot) }}</span>
        <span v-if="liveIntel.summary.call_wall" class="gex-meta-badge call"
          >CALL WALL {{ usd(liveIntel.summary.call_wall, 0) }}</span
        >
        <span v-if="liveIntel.summary.put_wall" class="gex-meta-badge put"
          >PUT WALL {{ usd(liveIntel.summary.put_wall, 0) }}</span
        >
        <span v-if="liveIntel.summary.total_gex_m != null" class="gex-meta-badge"
          >GEX {{ liveIntel.summary.total_gex_m >= 0 ? '+' : ''
          }}{{ num(liveIntel.summary.total_gex_m, 1) }}M</span
        >
      </div>
      <p v-if="syncError" class="sync-error-text label">{{ syncError }}</p>
    </div>

    <!-- Strategy Presets Toolbar (11 Institutional Presets) -->
    <div class="presets-shelf">
      <div class="presets-group">
        <span class="label group-tag">DIRECTIONAL</span>
        <div class="presets-btns">
          <button
            type="button"
            class="btn-quiet"
            :class="{ on: strategy === 'long_call' }"
            @click="applyPreset('long_call')"
          >
            Long Call
          </button>
          <button
            type="button"
            class="btn-quiet"
            :class="{ on: strategy === 'long_put' }"
            @click="applyPreset('long_put')"
          >
            Long Put
          </button>
          <button
            type="button"
            class="btn-quiet"
            :class="{ on: strategy === 'bull_call_spread' }"
            @click="applyPreset('bull_call_spread')"
          >
            Bull Call Spread
          </button>
          <button
            type="button"
            class="btn-quiet"
            :class="{ on: strategy === 'bear_put_spread' }"
            @click="applyPreset('bear_put_spread')"
          >
            Bear Put Spread
          </button>
        </div>
      </div>
      <div class="presets-group">
        <span class="label group-tag">INCOME</span>
        <div class="presets-btns">
          <button
            type="button"
            class="btn-quiet"
            :class="{ on: strategy === 'bull_put_spread' }"
            @click="applyPreset('bull_put_spread')"
          >
            Bull Put Spread
          </button>
          <button
            type="button"
            class="btn-quiet"
            :class="{ on: strategy === 'bear_call_spread' }"
            @click="applyPreset('bear_call_spread')"
          >
            Bear Call Spread
          </button>
          <button
            type="button"
            class="btn-quiet"
            :class="{ on: strategy === 'iron_condor' }"
            @click="applyPreset('iron_condor')"
          >
            Iron Condor
          </button>
          <button
            type="button"
            class="btn-quiet"
            :class="{ on: strategy === 'covered_call' }"
            @click="applyPreset('covered_call')"
          >
            Covered Call
          </button>
        </div>
      </div>
      <div class="presets-group">
        <span class="label group-tag">VOLATILITY</span>
        <div class="presets-btns">
          <button
            type="button"
            class="btn-quiet"
            :class="{ on: strategy === 'long_straddle' }"
            @click="applyPreset('long_straddle')"
          >
            Long Straddle
          </button>
          <button
            type="button"
            class="btn-quiet"
            :class="{ on: strategy === 'long_strangle' }"
            @click="applyPreset('long_strangle')"
          >
            Long Strangle
          </button>
          <button
            type="button"
            class="btn-quiet"
            :class="{ on: strategy === 'calendar_spread' }"
            @click="applyPreset('calendar_spread')"
          >
            Calendar Spread
          </button>
        </div>
      </div>
      <div v-if="activePresetMeta" class="strategy-thesis-strip">
        <span class="label thesis-tag">{{ activePresetMeta.category.toUpperCase() }}</span>
        <span class="thesis-desc">{{ activePresetMeta.description }}</span>
      </div>
    </div>

    <!-- Parameter Controls Grid -->
    <div class="calc-controls">
      <label
        ><span class="label">Spot</span
        ><input v-model.number="spot" type="number" min="0.01" step="0.5"
      /></label>
      <label
        ><span class="label">Strike</span
        ><input v-model.number="strikeHint" type="number" min="0.01" step="0.5"
      /></label>
      <label
        ><span class="label">Expiry DTE</span
        ><input v-model.number="dte" type="number" min="0" max="730" step="1"
      /></label>
      <label
        ><span class="label">Vol %</span
        ><input v-model.number="volPct" type="number" min="1" max="300" step="0.5"
      /></label>
      <label
        ><span class="label">IV Skew %</span
        ><input
          v-model.number="skewPct"
          type="number"
          min="-50"
          max="50"
          step="1"
          title="Volatility skew adjustment"
      /></label>
      <label
        ><span class="label">IV Smile %</span
        ><input
          v-model.number="smilePct"
          type="number"
          min="0"
          max="50"
          step="1"
          title="Volatility smile convexity adjustment"
      /></label>
    </div>

    <div class="calc-desk">
      <Panel
        label="Book"
        index="01"
        flush
        :meta="`${symbolInput || symbol ? `${symbolInput || symbol} · ` : ''}${strategyLabel} · ${legs.length} LEG${legs.length === 1 ? '' : 'S'}`"
      >
        <template #action>
          <button type="button" class="btn-quiet" @click="addLeg">Add leg</button>
        </template>
        <div class="table-scroll">
          <table class="grid">
            <thead>
              <tr>
                <th class="label">Side</th>
                <th class="label">Right</th>
                <th class="label num">Strike</th>
                <th class="label num">Qty</th>
                <th class="label num">Premium</th>
                <th class="label num">IV %</th>
                <th class="label num">Debit</th>
                <th class="label"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="leg in legs" :key="leg.id">
                <td>
                  <div class="seg">
                    <button
                      type="button"
                      class="btn-quiet side-long"
                      :class="{ on: leg.quantity > 0 }"
                      @click="setSide(leg, 1)"
                    >
                      Long
                    </button>
                    <button
                      type="button"
                      class="btn-quiet side-short"
                      :class="{ on: leg.quantity < 0 }"
                      @click="setSide(leg, -1)"
                    >
                      Short
                    </button>
                  </div>
                </td>
                <td>
                  <div class="seg">
                    <button
                      type="button"
                      class="btn-quiet right-call"
                      :class="{ on: leg.right === 'call' }"
                      @click="setRight(leg, 'call')"
                    >
                      Call
                    </button>
                    <button
                      type="button"
                      class="btn-quiet right-put"
                      :class="{ on: leg.right === 'put' }"
                      @click="setRight(leg, 'put')"
                    >
                      Put
                    </button>
                  </div>
                </td>
                <td class="num">
                  <input
                    class="fig"
                    :value="leg.strike"
                    type="number"
                    min="0.01"
                    step="0.5"
                    @input="setStrike(leg, $event)"
                  />
                </td>
                <td class="num">
                  <input
                    class="fig"
                    :value="Math.abs(leg.quantity)"
                    type="number"
                    min="1"
                    step="1"
                    @input="setQty(leg, $event)"
                  />
                </td>
                <td class="num">
                  <input
                    class="fig"
                    :value="leg.premium"
                    type="number"
                    min="0"
                    step="0.05"
                    @input="setPremium(leg, $event)"
                  />
                </td>
                <td class="num">
                  <input
                    class="fig"
                    :value="leg.vol ?? ''"
                    :placeholder="`${volPct}%`"
                    type="number"
                    min="1"
                    max="300"
                    step="1"
                    title="Per-leg implied volatility override"
                    @input="setLegVol(leg, $event)"
                  />
                </td>
                <td
                  class="fig num"
                  :class="
                    leg.premium * leg.quantity > 0
                      ? 'neg'
                      : leg.premium * leg.quantity < 0
                        ? 'pos'
                        : ''
                  "
                >
                  {{ usd(leg.premium * 100 * leg.quantity, 0) }}
                </td>
                <td>
                  <button
                    type="button"
                    class="btn-quiet"
                    :disabled="legs.length <= 1"
                    @click="removeLeg(leg.id)"
                  >
                    Remove
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <aside class="alloc-stack">
        <section class="alloc-card ticked" aria-label="Option portfolio allocation">
          <header>
            <span class="label">Allocation</span>
            <strong class="fig">{{ usd(allocation.net, 0) }} net</strong>
          </header>
          <div class="alloc-bar" aria-hidden="true">
            <i class="call-seg" :style="{ width: sharePct(allocation.callShare) }" />
            <i class="put-seg" :style="{ width: sharePct(allocation.putShare) }" />
          </div>
          <dl class="alloc-grid">
            <div>
              <dt class="label call-text">Call cash</dt>
              <dd
                class="fig"
                :class="allocation.callDebit > 0 ? 'neg' : allocation.callDebit < 0 ? 'pos' : ''"
              >
                {{ usd(allocation.callDebit, 0) }}
              </dd>
              <small>{{ sharePct(allocation.callShare) }}</small>
            </div>
            <div>
              <dt class="label put-text">Put cash</dt>
              <dd
                class="fig"
                :class="allocation.putDebit > 0 ? 'neg' : allocation.putDebit < 0 ? 'pos' : ''"
              >
                {{ usd(allocation.putDebit, 0) }}
              </dd>
              <small>{{ sharePct(allocation.putShare) }}</small>
            </div>
            <div>
              <dt class="label">Long notional</dt>
              <dd class="fig neg">{{ usd(allocation.longNotional, 0) }}</dd>
            </div>
            <div>
              <dt class="label">Short credit</dt>
              <dd class="fig pos">{{ usd(allocation.shortCredit, 0) }}</dd>
            </div>
          </dl>
        </section>

        <dl class="greeks">
          <Readout
            label="Delta"
            :value="
              clientGreeks
                ? num(clientGreeks.delta, 3)
                : result
                  ? num(result.greeks.delta, 3)
                  : DASH
            "
          />
          <Readout
            label="Gamma"
            :value="
              clientGreeks
                ? num(clientGreeks.gamma, 4)
                : result
                  ? num(result.greeks.gamma, 4)
                  : DASH
            "
          />
          <Readout
            label="Theta"
            :value="
              clientGreeks
                ? usd(clientGreeks.theta, 2)
                : result
                  ? usd(result.greeks.theta, 2)
                  : DASH
            "
          />
          <Readout
            label="Vega"
            :value="
              clientGreeks ? usd(clientGreeks.vega, 2) : result ? usd(result.greeks.vega, 2) : DASH
            "
          />
          <Readout
            label="Rho"
            :value="
              clientGreeks
                ? usd(clientGreeks.rho, 2)
                : result?.greeks?.rho != null
                  ? usd(result.greeks.rho, 2)
                  : DASH
            "
          />
          <Readout
            label="Theo"
            :value="
              clientGreeks ? usd(clientGreeks.theo, 2) : result ? usd(result.greeks.theo, 2) : DASH
            "
          />
          <Readout
            label="Net debit"
            :value="usd(debit, 0)"
            :tone="debit > 0 ? 'neg' : debit < 0 ? 'pos' : 'flat'"
          />
          <Readout
            label="Prob of Profit"
            :value="strategyPoP.popPctFormatted"
            :tone="strategyPoP.pop >= 0.5 ? 'pos' : 'neg'"
            :title="strategyPoP.profitZoneDesc"
          />
        </dl>
      </aside>
    </div>

    <p v-if="error" class="calc-error">{{ error }}</p>

    <!-- Panel 02: P/L at Expiry & T+0 Curve -->
    <Panel
      label="P/L at expiry"
      index="02"
      flush
      :meta="
        loading
          ? 'PRICING…'
          : payoff
            ? `MAX ${bounds.formattedMaxProfit} · MAX ${bounds.formattedMaxLoss}${breakevens.length ? ` · BE ${breakevens.map((level) => usd(level, 2)).join(' · ')}` : ''}`
            : 'READY'
      "
    >
      <div
        ref="chartHost"
        class="payoff-host"
        @pointermove="onChartMove"
        @pointerleave="onChartLeave"
      >
        <svg
          v-if="payoff"
          class="payoff"
          :viewBox="`0 0 ${payoff.width} ${payoff.height}`"
          role="img"
          aria-label="Expiry P/L and T+0 theoretical curve versus underlying"
        >
          <g class="gridlines" aria-hidden="true">
            <line
              v-for="tick in payoff.yTicks"
              :key="`y-${tick.label}`"
              :x1="payoff.pad.l"
              :x2="payoff.width - payoff.pad.r"
              :y1="tick.y"
              :y2="tick.y"
            />
          </g>
          <path class="loss-fill" :d="payoff.lossArea" />
          <path class="profit-fill" :d="payoff.profitArea" />
          <line
            class="axis"
            :x1="payoff.pad.l"
            :x2="payoff.width - payoff.pad.r"
            :y1="payoff.zeroY"
            :y2="payoff.zeroY"
          />
          <line
            class="spot"
            :x1="payoff.spotX"
            :x2="payoff.spotX"
            :y1="payoff.pad.t"
            :y2="payoff.height - payoff.pad.b"
          />
          <line
            v-for="mark in payoff.strikes"
            :key="`k-${mark.right}-${mark.strike}`"
            class="strike"
            :class="mark.right"
            :x1="mark.x"
            :x2="mark.x"
            :y1="payoff.pad.t"
            :y2="payoff.height - payoff.pad.b"
          />
          <!-- Expiration P/L Curve (Solid) -->
          <path class="curve" :d="payoff.line" />
          <!-- T+0 Theoretical Black-Scholes Curve (Colored) -->
          <path v-if="payoff.t0Line" class="t0-curve" :d="payoff.t0Line" />
          <circle
            v-for="mark in payoff.breakevens"
            :key="`be-${mark.spot}`"
            class="be-dot"
            :cx="mark.x"
            :cy="payoff.zeroY"
            r="3"
          />
          <line
            v-if="hoverRead"
            class="hover"
            :x1="hoverRead.x"
            :x2="hoverRead.x"
            :y1="payoff.pad.t"
            :y2="payoff.height - payoff.pad.b"
          />
          <g class="axis-labels">
            <text
              v-for="tick in payoff.yTicks"
              :key="`yl-${tick.label}`"
              :x="payoff.pad.l - 6"
              :y="tick.y + 3"
            >
              {{ axisMoney(tick.label) }}
            </text>
            <text
              v-for="tick in payoff.xTicks"
              :key="`xl-${tick.label}`"
              class="x-tick"
              :x="tick.x"
              :y="payoff.height - 8"
            >
              {{ axisMoney(tick.label) }}
            </text>
            <text class="spot-tag" :x="payoff.spotX + 4" :y="payoff.pad.t + 10">
              SPOT {{ usd(spot) }}
            </text>
            <text
              v-for="mark in payoff.breakevens"
              :key="`bel-${mark.spot}`"
              class="be-tag"
              :x="mark.x + 4"
              :y="payoff.zeroY - 6"
            >
              BE {{ usd(mark.spot, 2) }}
            </text>
          </g>
        </svg>
        <div v-if="hoverRead" class="hover-read fig">
          {{ usd(hoverRead.spot) }} · EXP:
          <span :class="hoverRead.pnl >= 0 ? 'pos' : 'neg'">{{ usd(hoverRead.pnl, 0) }}</span> ·
          T+0:
          <span :class="hoverRead.t0Pnl >= 0 ? 'pos' : 'neg'">{{ usd(hoverRead.t0Pnl, 0) }}</span>
        </div>
        <div class="curve-legend label" aria-hidden="true">
          <span class="leg-item"><i class="swatch expiry" /> EXPIRATION</span>
          <span class="leg-item"><i class="swatch theo" /> T+0 THEORETICAL</span>
        </div>
      </div>
      <div v-if="samplePnl.length" class="table-scroll">
        <table class="grid">
          <thead>
            <tr>
              <th class="label">Underlying</th>
              <th class="label num">P/L at expiry</th>
              <th class="label num">T+0 Theo P/L</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="point in samplePnl" :key="point.spot">
              <td class="fig">{{ usd(point.spot) }}</td>
              <td class="fig num" :class="point.pnlExpiry >= 0 ? 'pos' : 'neg'">
                {{ usd(point.pnlExpiry, 0) }}
              </td>
              <td class="fig num" :class="point.pnlTheo >= 0 ? 'pos' : 'neg'">
                {{ usd(point.pnlTheo, 0) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Panel>

    <!-- Panel 03: Risk-Neutral Probability & Target Analysis -->
    <Panel
      label="Risk-neutral probability"
      index="03"
      flush
      :meta="`${symbolInput || symbol || 'PORTFOLIO'} · IV ${num(volPct, 1)}% · ${dte}D HORIZON · ±1σ ${usd(spot * (volPct / 100) * Math.sqrt(Math.max(dte, 1) / 365))}`"
    >
      <ProbabilityDensityChart
        :probability="activeProbability"
        :spot="spot"
        :dte="dte"
        :vol="volPct"
        :call-wall="callWall"
        :put-wall="putWall"
        :breakevens="breakevens"
        :strikes="legs"
        :pop="strategyPoP.pop"
        :strategy-label="strategyLabel"
        :height="220"
      />
    </Panel>

    <p class="calc-note">
      Multi-leg P/L is computed using closed-form Black-Scholes and intrinsic expiry curves.
      Diagnostic only — not an order ticket.
    </p>
  </div>
</template>

<style scoped>
/* Surface glass token: var(--glass-surface-hi) */
.calc {
  display: grid;
  gap: var(--s4);
}

.underlier-shelf {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  padding: var(--s3);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
}

.symbol-sync-group {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
}

.symbol-input-box {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sym-input {
  width: 140px;
  min-height: var(--density-control-h);
  padding: 0 var(--s3);
  color: var(--ink);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-hi);
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-small);
  text-transform: uppercase;
}

.sym-input:focus {
  border-color: var(--phosphor);
  outline: none;
}

.sync-btn {
  min-height: var(--density-control-h);
  padding: 0 12px;
  font-size: var(--t-micro, 10px);
  font-weight: 700;
}

.quick-tickers {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.ticker-pill {
  padding: 2px 8px;
  font-size: 10px;
  font-weight: 600;
}

.ticker-pill.on {
  color: var(--phosphor);
  border-color: var(--phosphor);
  background: var(--phosphor-wash);
}

.live-meta-facts {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 4px;
}

.gex-meta-badge {
  font-size: var(--t-micro, 10px);
  color: var(--ink-dim);
  font-family: var(--font-data);
  padding: 2px 6px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
}

.gex-meta-badge.call {
  color: var(--call-hi);
  border-color: var(--call-dim);
}
.gex-meta-badge.put {
  color: var(--put-hi);
  border-color: var(--put-dim);
}

.sync-error-text {
  color: var(--warn);
  font-size: 10px;
  margin-top: 4px;
}

.presets-shelf {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  padding: var(--s3);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
}

.presets-group {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
}

.group-tag {
  font-size: var(--t-micro, 10px);
  color: var(--ink-dim);
  min-width: 90px;
  letter-spacing: var(--track-label);
  font-weight: 700;
}

.presets-btns {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.strategy-thesis-strip {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: 6px var(--s3);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-hi);
  border-left: 1px solid var(--phosphor);
  font-size: var(--t-tiny);
  margin-top: 2px;
}

.thesis-tag {
  color: var(--phosphor);
  font-weight: 700;
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  flex-shrink: 0;
}

.thesis-desc {
  color: var(--ink-soft);
  font-size: var(--t-tiny);
}

.calc-controls {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: var(--s3);
}

.calc-controls label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.calc-controls input,
.grid input {
  min-height: var(--density-control-h);
  width: 100%;
  padding: 0 var(--s3);
  color: var(--ink);
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
  font-family: var(--font-data);
  font-size: var(--t-small);
  border-radius: 2px;
  transition: border-color var(--dur-fast) var(--ease-out);
}

.calc-controls input:focus,
.grid input:focus {
  outline: none;
  border-color: var(--phosphor);
}

.btn-quiet.on {
  color: var(--phosphor);
  border-color: var(--phosphor);
  background: var(--phosphor-wash);
}

.btn-quiet.side-long.on {
  color: var(--call-hi);
  border-color: var(--call);
  background: var(--call-wash);
  font-weight: 700;
}

.btn-quiet.side-short.on {
  color: var(--put-hi);
  border-color: var(--put);
  background: var(--put-wash);
  font-weight: 700;
}

.btn-quiet.right-call.on {
  color: var(--call-hi);
  border-color: var(--call);
  background: var(--call-wash);
  font-weight: 700;
}

.btn-quiet.right-put.on {
  color: var(--put-hi);
  border-color: var(--put);
  background: var(--put-wash);
  font-weight: 700;
}

.calc-desk {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: var(--s4);
  align-items: start;
}

@media (max-width: 960px) {
  .calc-desk {
    grid-template-columns: 1fr;
  }
}

.table-scroll {
  overflow-x: auto;
  max-width: 100%;
}

.grid {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-small);
}

.grid th,
.grid td {
  padding: var(--s2) var(--s3);
  border-bottom: var(--hair) solid var(--rule);
  text-align: left;
  vertical-align: middle;
}

.grid th.num,
.grid td.num {
  text-align: right;
}

.seg {
  display: inline-flex;
  gap: 2px;
}

.alloc-stack {
  display: grid;
  gap: var(--s3);
}

.alloc-card {
  padding: var(--s3);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  display: grid;
  gap: var(--s3);
}

.alloc-card header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.alloc-bar {
  display: flex;
  height: 6px;
  background: var(--void-lift);
  overflow: hidden;
  border-radius: 1px;
}

.alloc-bar .call-seg {
  background: var(--call);
  height: 100%;
}

.alloc-bar .put-seg {
  background: var(--put);
  height: 100%;
}

.alloc-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s2) var(--s3);
  margin: 0;
}

.alloc-grid dt {
  font-size: var(--t-micro);
  color: var(--ink-dim);
}
.alloc-grid dd {
  margin: 0;
  font-family: var(--font-data);
  font-size: var(--t-small);
  font-weight: 600;
}
.alloc-grid small {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.call-text {
  color: var(--call-hi);
}
.put-text {
  color: var(--put-hi);
}

.greeks {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--s2);
  margin: 0;
}

.calc-error {
  color: var(--warn);
  padding: var(--s2) var(--s3);
  background: var(--warn-wash);
  border: var(--hair) solid var(--warn);
  font-size: var(--t-small);
}

.payoff-host {
  position: relative;
  width: 100%;
  background: var(--void);
  border: var(--hair) solid var(--rule-hi);
  overflow: hidden;
}

.payoff {
  display: block;
  width: 100%;
  height: auto;
}

.gridlines line {
  stroke: var(--rule);
  stroke-dasharray: 2 4;
}

.profit-fill {
  fill: var(--call-wash);
  opacity: 0.85;
}

.loss-fill {
  fill: var(--put-wash);
  opacity: 0.85;
}

.axis {
  stroke: var(--rule-hi);
  stroke-width: 1px;
}

.spot {
  stroke: var(--ink-dim);
  stroke-width: 1px;
  stroke-dasharray: 4 4;
}

.strike {
  stroke-width: 1px;
  stroke-dasharray: 2 2;
  opacity: 0.8;
}
.strike.call {
  stroke: var(--call);
}
.strike.put {
  stroke: var(--put);
}

.curve {
  fill: none;
  stroke: var(--ink);
  stroke-width: 2px;
}

.t0-curve {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 2px;
  stroke-dasharray: 5 3;
}

.be-dot {
  fill: var(--phosphor);
  stroke: var(--void);
  stroke-width: 1px;
}

.hover {
  stroke: var(--phosphor);
  stroke-width: 1px;
  stroke-dasharray: 2 2;
}

.axis-labels text {
  fill: var(--ink-dim);
  font-family: var(--font-data);
  font-size: 10px;
}

.spot-tag {
  fill: var(--ink) !important;
  font-weight: 700;
}

.be-tag {
  fill: var(--phosphor) !important;
  font-weight: 700;
}

.hover-read {
  position: absolute;
  top: 8px;
  right: 12px;
  padding: 4px 8px;
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  font-size: 11px;
  color: var(--ink);
}

.curve-legend {
  position: absolute;
  bottom: 8px;
  left: 12px;
  display: flex;
  gap: 12px;
  font-size: 10px;
  color: var(--ink-dim);
  background: var(--panel-wash);
  padding: 2px 6px;
  border: var(--hair) solid var(--rule);
}

.leg-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.swatch {
  display: inline-block;
  width: 12px;
  height: 2px;
}
.swatch.expiry {
  background: var(--ink);
}
.swatch.theo {
  background: var(--phosphor);
}

.calc-note {
  font-size: var(--t-micro);
  color: var(--ink-faint);
  margin-top: var(--s2);
}
</style>
