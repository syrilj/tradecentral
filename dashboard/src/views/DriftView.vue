<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type ChainStrikeRow,
  type OptionsIntelligence,
  type OptionsMode,
  type OptionsRange,
} from '@/api'
import { useResource } from '@/composables/useResource'
import { compact, num, shortDate, signed } from '@/format'
import Panel from '@/components/Panel.vue'
import LoadingState from '@/components/LoadingState.vue'
import GammaExposureMap from '@/components/GammaExposureMap.vue'
import PressureDriftChart from '@/components/PressureDriftChart.vue'

/**
 * Charm / pressure drift tab.
 *
 * Charm = ∂Δ/∂t — the delta decay per day the article describes. The tab
 * computes Black-Scholes charm for every contract in the chain, aggregates
 * charm flow (charm × OI × 100, shares/day) by strike under the dealer
 * sign convention, and combines it with GEX and delta-weighted live volume
 * into one pressure gauge:
 *
 *   · charm chart — selling pressure (positive flow) rises UP from zero,
 *     buying pressure (negative flow) grows DOWN
 *   · GEX map — the gamma structure behind the pressure
 *   · strike table — per-contract OI / vol / IV / delta / gamma / charm
 *
 * Missing data renders as an explicit missing/stale state, never a fake zero.
 */

const router = useRouter()
const route = useRoute()

const RANGES: { value: OptionsRange; label: string }[] = [
  { value: '1d', label: '1D' },
  { value: '5d', label: '5D' },
  { value: '1m', label: '1M' },
  { value: '3m', label: '3M' },
]

const EXPIRY_MODES: { value: 'all' | 'nearest'; label: string }[] = [
  { value: 'all', label: 'ALL EXPIRIES' },
  { value: 'nearest', label: 'NEAREST' },
]

function readSymbol(): string {
  const raw = route.query.symbol
  const value = Array.isArray(raw) ? raw[0] : raw
  return String(value || 'NVDA').trim().toUpperCase().replace(/[^A-Z0-9.-]/g, '').slice(0, 10) || 'NVDA'
}

const symbolInput = ref(readSymbol())
const symbol = ref(readSymbol())
const mode = ref<OptionsMode>('live')
const selectedRange = ref<OptionsRange>('5d')
const selectedExpiry = ref<'all' | 'nearest'>('all')
const refreshMs = ref(30_000)

/** Balanced defaults — keep some structure visible on mid-caps. */
const minPremium = ref(25_000)
const preset = ref<'strict' | 'balanced' | 'raw'>('balanced')

/** Table filter mode: 'all' | 'near_spot' | 'high_charm' */
const tableFilter = ref<'all' | 'near_spot' | 'high_charm'>('all')

const optionsRes = useResource<OptionsIntelligence>(
  () => api.options({
    symbol: symbol.value,
    mode: mode.value,
    range: selectedRange.value,
    minPremium: minPremium.value,
    expiry: selectedExpiry.value,
  }),
  { intervalMs: refreshMs.value },
)

watch(symbol, () => {
  void optionsRes.refresh({ clear: true })
})

watch(() => route.query.symbol, (val) => {
  const next = Array.isArray(val) ? val[0] : val
  if (typeof next === 'string' && next && next.toUpperCase() !== symbol.value) {
    symbol.value = next.toUpperCase()
    symbolInput.value = next.toUpperCase()
  }
})

function applySymbol(): void {
  const clean = symbolInput.value.trim().toUpperCase().replace(/[^A-Z0-9.-]/g, '').slice(0, 10)
  if (!clean || clean === symbol.value) return
  symbol.value = clean
  symbolInput.value = clean
  void router.replace({ name: 'drift', query: { symbol: clean, range: selectedRange.value } })
}

function onSymbolKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter') {
    e.preventDefault()
    applySymbol()
  }
}

function setRange(r: OptionsRange): void {
  if (r === selectedRange.value) return
  selectedRange.value = r
  void router.replace({ name: 'drift', query: { symbol: symbol.value, range: r } })
  void optionsRes.refresh({ clear: true })
}

function setExpiry(e: 'all' | 'nearest'): void {
  if (e === selectedExpiry.value) return
  selectedExpiry.value = e
  void optionsRes.refresh({ clear: true })
}

function setPreset(p: 'strict' | 'balanced' | 'raw'): void {
  preset.value = p
  if (p === 'strict') minPremium.value = 100_000
  else if (p === 'balanced') minPremium.value = 25_000
  else minPremium.value = 0
  void optionsRes.refresh({ clear: true })
}

const payload = computed(() => optionsRes.data.value)
const summary = computed(() => payload.value?.summary)
const charmSummary = computed(() => payload.value?.charm_summary)
const pressure = computed(() => payload.value?.pressure)
const charmRows = computed(() => payload.value?.charm_by_strike ?? [])
const chainRows = computed(() => payload.value?.chain_by_strike ?? [])
const gexRows = computed(() => payload.value?.gex_by_strike ?? [])
const freshness = computed(() => payload.value?.freshness)

const spot = computed(() => summary.value?.spot ?? null)
const callWall = computed(() => summary.value?.call_wall ?? null)
const putWall = computed(() => summary.value?.put_wall ?? null)
const gammaFlip = computed(() => summary.value?.gamma_flip ?? null)
const callPutRatio = computed(() => summary.value?.call_put_ratio ?? null)
const netGex = computed(() => summary.value?.total_gex_m ?? null)
const gexRegime = computed(() => summary.value?.regime ?? 'neutral')
const netCharmFlow = computed(() => charmSummary.value?.net_charm_flow ?? null)
const charmPressure = computed(() => charmSummary.value?.pressure ?? 'balanced')

const asof = computed(() => payload.value?.asof_utc ?? null)
const modeResolved = computed(() => payload.value?.mode_resolved ?? null)
const loading = computed(() => optionsRes.loading.value && !payload.value)
const error = computed(() => optionsRes.error.value)
const hasChain = computed(() => gexRows.value.length > 0 || chainRows.value.length > 0)

const gexRegimeLabel = computed(() => ({
  positive: 'MEAN-REVERSION',
  negative: 'TRENDING',
  neutral: 'NEUTRAL',
}[gexRegime.value]))

const pressureLabel = computed(() => ({
  buying: 'BUYING PRESSURE',
  selling: 'SELLING PRESSURE',
  balanced: 'BALANCED',
}[pressure.value?.label ?? 'balanced']))

const gaugePct = computed(() => {
  const v = pressure.value?.imbalance
  if (v == null || !Number.isFinite(v)) return 50
  return Math.round(((v + 1) / 2) * 100)
})

const dataModeBadge = computed(() => {
  if (loading.value) return 'SYNC'
  if (error.value) return 'FAULT'
  if (modeResolved.value === 'live') return 'LIVE'
  if (modeResolved.value === 'history') return 'HISTORY'
  if (modeResolved.value === 'history_fallback') return 'DELAYED'
  return 'NO DATA'
})

/** Qualitative interpretation note based on microstructure. */
const microstructureAssessment = computed(() => {
  if (!pressure.value || !summary.value) return null
  const imb = pressure.value.imbalance
  const regimeStr = summary.value.regime

  if (imb > 0.35) {
    return {
      title: 'Strong Structural Buying Pressure',
      tone: 'buying',
      body: `Dealers are net short decaying OTM put contracts. As time passes without a downward move, put deltas decay toward zero, forcing dealers to systematically BUY back their short equity hedges (${compact(Math.abs(charmSummary.value?.net_charm_flow ?? 0))} shares/day).`,
      implication: 'Mechanical tailwind supporting price; dips into the Put Wall are likely to find rapid absorption.',
    }
  }
  if (imb < -0.35) {
    return {
      title: 'Strong Structural Selling Pressure',
      tone: 'selling',
      body: `Long call gamma/delta decay dominates the dealer inventory. As call deltas decay over time, dealers are forced to SELL underlying stock to remain delta-neutral (${compact(Math.abs(charmSummary.value?.net_charm_flow ?? 0))} shares/day).`,
      implication: 'Mechanical headwind capping upside; rallies toward the Call Wall face persistent dealer inventory supply.',
    }
  }
  if (regimeStr === 'positive') {
    return {
      title: 'Balanced Flow in Positive Gamma Channel',
      tone: 'balanced',
      body: `Aggregate dealer positioning is Net Long Gamma ($${compact(summary.value.total_gex_m ?? 0)}M GEX). Dealers hedge counter-cyclically (buying dips, selling rips), compressing realized volatility between Put Wall ($${num(summary.value.put_wall, 0)}) and Call Wall ($${num(summary.value.call_wall, 0)}).`,
      implication: 'High probability of range-bound mean-reversion. Fade range extremes; low breakout follow-through.',
    }
  }
  return {
    title: 'Neutral / Transitory Market Equilibrium',
    tone: 'balanced',
    body: `Charm drift and directional options flow are evenly matched. Key pivot level to monitor is the Gamma Flip point at $${num(summary.value.gamma_flip, 0)}.`,
    implication: 'Monitor live flow tape for directional sweeps or sudden volume imbalances.',
  }
})

/** Strike table: pair call/put rows per strike, sorted by strike. */
interface StrikeTableRow {
  strike: number
  call: ChainStrikeRow | null
  put: ChainStrikeRow | null
  gex: number
  netCharmFlow: number
  distPct: number | null
  isSpot: boolean
  isCallWall: boolean
  isPutWall: boolean
  isGammaFlip: boolean
}

const strikeTable = computed<StrikeTableRow[]>(() => {
  const byStrike = new Map<number, { call: ChainStrikeRow | null; put: ChainStrikeRow | null }>()
  for (const row of chainRows.value) {
    const entry = byStrike.get(row.strike) ?? { call: null, put: null }
    if (row.right === 'call') entry.call = row
    else entry.put = row
    byStrike.set(row.strike, entry)
  }
  const gexByStrike = new Map(gexRows.value.map((r) => [r.strike, r.net_gex_m]))
  const charmByStrike = new Map(charmRows.value.map((r) => [r.strike, r.net_charm_flow]))
  const spotVal = spot.value

  const list: StrikeTableRow[] = []
  for (const [strike, entry] of byStrike.entries()) {
    const distPct = spotVal && spotVal > 0 ? ((strike - spotVal) / spotVal) * 100 : null
    const isSpot = spotVal != null && Math.abs(strike - spotVal) <= (spotVal * 0.007)
    const isCallWall = callWall.value != null && Math.abs(strike - callWall.value) < 0.01
    const isPutWall = putWall.value != null && Math.abs(strike - putWall.value) < 0.01
    const isGammaFlip = gammaFlip.value != null && Math.abs(strike - gammaFlip.value) < 0.01

    list.push({
      strike,
      call: entry.call,
      put: entry.put,
      gex: gexByStrike.get(strike) ?? 0,
      netCharmFlow: charmByStrike.get(strike) ?? 0,
      distPct,
      isSpot,
      isCallWall,
      isPutWall,
      isGammaFlip,
    })
  }

  list.sort((a, b) => a.strike - b.strike)

  // Apply filters
  if (tableFilter.value === 'near_spot' && spotVal != null) {
    return list.filter((r) => r.distPct != null && Math.abs(r.distPct) <= 10)
  }
  if (tableFilter.value === 'high_charm') {
    const threshold = 1000
    return list.filter((r) => Math.abs(r.netCharmFlow) >= threshold)
  }
  return list
})

/** Strategy evaluation based on section 5 of the report. */
const strategies = computed(() => {
  const spotVal = spot.value
  const cw = callWall.value
  const pw = putWall.value
  const flip = gammaFlip.value
  const gex = netGex.value ?? 0
  const charm = netCharmFlow.value ?? 0

  // Strategy 1: Mean-Reversion in Heavy Positive Gamma
  const s1Active = gex > 0 && spotVal != null && pw != null && cw != null && spotVal >= pw && spotVal <= cw
  // Strategy 2: Breakout Expansion Below Gamma Flip
  const s2Active = flip != null && spotVal != null && spotVal < flip && gex < 0
  // Strategy 3: OpEx Charm Drift
  const s3Active = charm < -5000 // Negative charm flow = buying pressure

  return [
    {
      id: 'strat-1',
      title: 'Strategy 1: Mean-Reversion Channeling',
      regime: 'Positive Gamma (+GEX)',
      status: s1Active ? 'ACTIVE' : 'MONITORING',
      condition: `Spot ($${num(spotVal, 0)}) bounded between Put Wall ($${num(pw, 0)}) and Call Wall ($${num(cw, 0)}), Net GEX > 0`,
      trade: 'Fade range extremes (VWAP ±2σ), sell OTM strangles, buy dips at Put Wall, take profit at Call Wall.',
      mechanic: 'Dealer counter-cyclical hedging dampens realized volatility and creates range compression.',
    },
    {
      id: 'strat-2',
      title: 'Strategy 2: Breakout Expansion Below Flip',
      regime: 'Negative Gamma (-GEX)',
      status: s2Active ? 'TRIGGERED' : 'MONITORING',
      condition: `Spot ($${num(spotVal, 0)}) breaches below Zero Gamma Flip ($${num(flip, 0)})`,
      trade: 'Long directional momentum (long puts / short futures) or long straddles for volatility breakout.',
      mechanic: 'Dealers are net short gamma and forced to sell into market declines, accelerating cascades.',
    },
    {
      id: 'strat-3',
      title: 'Strategy 3: OpEx Charm Drift / Unwind',
      regime: 'Time-Decay Dynamics (dΔ/dt)',
      status: s3Active ? 'ACTIVE' : 'MONITORING',
      condition: `Net charm flow negative (${signed(charm, 0)} sh/d buying pressure) heading into expiry`,
      trade: 'Long delta bias via futures or call spreads from Thursday afternoon through Friday OpEx.',
      mechanic: 'Dealer short OTM put hedges decay toward 0 delta, forcing mechanical stock buying to unwind.',
    },
  ]
})

const focusStrike = ref<number | null>(null)
</script>

<template>
  <div class="drift-view">
    <!-- Header banner -->
    <header class="drift-head ticked rise">
      <div class="drift-title">
        <span class="label eyebrow"><i aria-hidden="true" class="live-dot" /> CHARM &amp; DEALER HEDGING DYNAMICS</span>
        <h1>Charm &amp; Pressure Drift</h1>
        <p>
          Charm ($\partial\Delta/\partial t$) measures the mechanical daily change in option delta solely due to the passage of time.
          Because dealers run delta-neutral books, decaying OTM options force predictable, time-dependent rebalancing flows into the underlying market.
        </p>
      </div>

      <div class="controls">
        <div class="symbol-box">
          <label class="label" for="drift-symbol">SYMBOL</label>
          <input
            id="drift-symbol"
            v-model="symbolInput"
            class="symbol-input fig"
            type="text"
            spellcheck="false"
            autocomplete="off"
            maxlength="10"
            :aria-label="`Symbol for ${symbol}`"
            @keydown="onSymbolKeydown"
            @blur="applySymbol"
          />
        </div>

        <div class="range-box" role="group" aria-label="Range">
          <button
            v-for="r in RANGES"
            :key="r.value"
            type="button"
            class="range-btn label"
            :class="{ on: selectedRange === r.value }"
            :aria-pressed="selectedRange === r.value"
            @click="setRange(r.value)"
          >
            {{ r.label }}
          </button>
        </div>

        <div class="expiry-box" role="group" aria-label="Expiry filter">
          <button
            v-for="e in EXPIRY_MODES"
            :key="e.value"
            type="button"
            class="expiry-btn label"
            :class="{ on: selectedExpiry === e.value }"
            :aria-pressed="selectedExpiry === e.value"
            @click="setExpiry(e.value)"
          >
            {{ e.label }}
          </button>
        </div>

        <div class="preset-box" role="group" aria-label="Noise preset">
          <button
            v-for="p in ['strict', 'balanced', 'raw'] as const"
            :key="p"
            type="button"
            class="preset-btn label"
            :class="{ on: preset === p }"
            :aria-pressed="preset === p"
            @click="setPreset(p)"
          >
            {{ p }}
          </button>
        </div>
      </div>
    </header>

    <!-- KPI summary cards -->
    <section class="kpi-row">
      <div class="kpi" :class="{ stale: netGex == null }">
        <span class="label k-key">NET GEX</span>
        <span class="fig k-val" :class="gexRegime">{{ netGex != null ? `$${compact(netGex)}M` : '—' }}</span>
        <span class="label k-tag" :class="gexRegime">{{ gexRegimeLabel }}</span>
      </div>
      <div class="kpi" :class="{ stale: netCharmFlow == null }">
        <span class="label k-key">NET CHARM FLOW</span>
        <span class="fig k-val" :class="charmPressure">
          {{ netCharmFlow != null ? `${signed(netCharmFlow, 0)} sh/d` : '—' }}
        </span>
        <span class="label k-tag" :class="charmPressure">{{ charmPressure.toUpperCase() }}</span>
      </div>
      <div class="kpi" :class="{ stale: callPutRatio == null }">
        <span class="label k-key">PUT / CALL RATIO</span>
        <span class="fig k-val">{{ num(callPutRatio) }}</span>
        <span class="label k-tag">VOLUME</span>
      </div>
      <div class="kpi" :class="{ stale: asof == null }">
        <span class="label k-key">LAST UPDATE</span>
        <span class="fig k-val">{{ asof ? shortDate(asof) : '—' }}</span>
        <span class="label k-tag" :class="{ live: modeResolved === 'live' }">{{ dataModeBadge }}</span>
      </div>
    </section>

    <!-- Pressure Gauge & Multi-Factor Decomposition -->
    <Panel label="PRESSURE GAUGE &amp; FLOW POSTURE" :meta="pressureLabel" live>
      <div class="gauge-card-container">
        <!-- Main Gauge Bar -->
        <div class="gauge-body">
          <div class="gauge-header">
            <div class="gauge-title-row">
              <span class="label">MICROSTRUCTURE PRESSURE IMBALANCE</span>
              <span v-if="pressure" class="fig gauge-score" :class="pressure.label">
                {{ signed(pressure.imbalance, 2) }}
              </span>
            </div>
          </div>

          <div
            class="gauge-track"
            role="meter"
            :aria-valuemin="-1"
            :aria-valuemax="1"
            :aria-valuenow="pressure?.imbalance ?? 0"
            :aria-valuetext="pressureLabel"
            :aria-label="`Pressure imbalance ${pressure?.imbalance ?? 'unavailable'}`"
          >
            <span class="gauge-zones" aria-hidden="true">
              <i class="zone-sell-heavy" title="Heavy Selling Pressure (-1.0 to -0.5)" />
              <i class="zone-sell-mod" title="Moderate Selling Pressure (-0.5 to -0.2)" />
              <i class="zone-neutral" title="Balanced / Neutral (-0.2 to +0.2)" />
              <i class="zone-buy-mod" title="Moderate Buying Pressure (+0.2 to +0.5)" />
              <i class="zone-buy-heavy" title="Heavy Buying Pressure (+0.5 to +1.0)" />
            </span>
            <span class="gauge-ticks" aria-hidden="true" />
            <span
              v-if="pressure"
              class="gauge-needle"
              :class="pressure.label"
              :style="{ left: `${gaugePct}%` }"
            />
          </div>

          <div class="gauge-labels label">
            <span class="sell">◀ SELLING PRESSURE (−1.0)</span>
            <span class="neutral">BALANCED (0.0)</span>
            <span class="buy">BUYING PRESSURE (+1.0) ▶</span>
          </div>

          <p v-if="pressure" class="gauge-note label">
            Charm flow {{ signed(pressure.components.net_charm_flow, 0) }} sh/d ·
            ΔW call vol {{ compact(pressure.components.delta_weighted_call_vol) }} ·
            ΔW put vol {{ compact(pressure.components.delta_weighted_put_vol) }} ·
            GEX {{ signed(pressure.components.net_gex_m, 1) }}M ·
            α {{ pressure.weights.alpha }} · β {{ pressure.weights.beta }}
          </p>
          <p v-else class="gauge-note label">Pressure unavailable until the chain loads.</p>
        </div>

        <!-- 3-Factor Breakdown Cards -->
        <div v-if="pressure" class="factor-grid">
          <div class="factor-card" :class="charmPressure">
            <div class="factor-head">
              <span class="label">1. CHARM TIME DECAY</span>
              <span class="factor-badge label" :class="charmPressure">{{ charmPressure.toUpperCase() }}</span>
            </div>
            <div class="factor-metric fig" :class="charmPressure">
              {{ signed(pressure.components.net_charm_flow, 0) }} <small>sh/d</small>
            </div>
            <p class="factor-desc">
              {{ netCharmFlow && netCharmFlow < 0
                ? 'Dealers short decaying OTM puts → Must BUY stock to unwind hedges.'
                : netCharmFlow && netCharmFlow > 0
                  ? 'Dealers long decaying calls → Must SELL stock to re-neutralize.'
                  : 'Time decay flow is balanced between calls and puts.' }}
            </p>
          </div>

          <div class="factor-card" :class="gexRegime">
            <div class="factor-head">
              <span class="label">2. GEX REGIME</span>
              <span class="factor-badge label" :class="gexRegime">{{ gexRegimeLabel }}</span>
            </div>
            <div class="factor-metric fig" :class="gexRegime">
              {{ signed(pressure.components.net_gex_m, 1) }} <small>$M</small>
            </div>
            <p class="factor-desc">
              {{ gexRegime === 'positive'
                ? 'Long Gamma: Counter-cyclical rehedging compresses volatility.'
                : gexRegime === 'negative'
                  ? 'Short Gamma: Pro-cyclical rehedging amplifies breakouts & slips.'
                  : 'Gamma exposure neutral near current spot.' }}
            </p>
          </div>

          <div class="factor-card">
            <div class="factor-head">
              <span class="label">3. LIVE FLOW AGGRESSION</span>
              <span class="factor-badge label">INTRADAY</span>
            </div>
            <div class="factor-metric fig">
              C: {{ compact(pressure.components.delta_weighted_call_vol) }} · P: {{ compact(pressure.components.delta_weighted_put_vol) }}
            </div>
            <p class="factor-desc">
              {{ pressure.components.delta_weighted_call_vol > pressure.components.delta_weighted_put_vol
                ? 'Call taker volume leads put taker volume on a delta-weighted basis.'
                : 'Put taker volume leads call taker volume on a delta-weighted basis.' }}
            </p>
          </div>
        </div>

        <!-- Microstructure Interpretation Banner -->
        <div v-if="microstructureAssessment" class="assessment-box" :class="microstructureAssessment.tone">
          <div class="assessment-header">
            <span class="label assess-tag">MICROSTRUCTURE IMPLICATION</span>
            <span class="assess-title">{{ microstructureAssessment.title }}</span>
          </div>
          <p class="assess-body">{{ microstructureAssessment.body }}</p>
          <div class="assess-footer label">
            <b>Actionable read:</b> {{ microstructureAssessment.implication }}
          </div>
        </div>
      </div>
    </Panel>

    <!-- Charm flow by strike chart -->
    <Panel
      :label="`${symbol} · CHARM FLOW BY STRIKE`"
      :meta="charmSummary ? `${charmSummary.contracts_measured} contracts · ${charmSummary.contracts_skipped} skipped` : 'NO CHAIN'"
      live
      flush
    >
      <template #action>
        <span v-if="loading" class="state-chip label live">SYNC</span>
        <span v-else-if="error" class="state-chip label fault" :title="error">FAULT</span>
        <span v-else-if="modeResolved" class="state-chip label">{{ modeResolved }}</span>
      </template>

      <div class="chart-slot">
        <LoadingState v-if="loading" label="Computing charm from the chain…" />
        <div v-else-if="error" class="placeholder">
          <span class="ph-msg fault" :title="error">Unable to load the chain.</span>
        </div>
        <div v-else-if="!hasChain" class="placeholder">
          <span class="ph-msg">No chain data for {{ symbol }} — try another symbol or expiry.</span>
        </div>
        <PressureDriftChart
          v-else
          :symbol="symbol"
          :rows="charmRows"
          :spot="spot"
          :call-wall="callWall"
          :put-wall="putWall"
          :gamma-flip="gammaFlip"
          :height="440"
        />
      </div>
    </Panel>

    <!-- GEX Map -->
    <Panel
      label="GEX BY STRIKE (GAMMA EXPOSURE PROFILE)"
      :meta="netGex != null ? `NET $${compact(netGex)}M · ${gexRegimeLabel}` : 'NO GEX'"
      flush
    >
      <div class="chart-slot">
        <LoadingState v-if="loading" label="Building GEX profile…" />
        <div v-else-if="!gexRows.length" class="placeholder">
          <span class="ph-msg">GEX unavailable — open interest missing for {{ symbol }}.</span>
        </div>
        <GammaExposureMap
          v-else
          :rows="gexRows"
          :spot="spot ?? 0"
          :call-wall="callWall"
          :put-wall="putWall"
          :gamma-flip="gammaFlip"
          :focus-strike="focusStrike"
          :max-height="420"
          @update:focus-strike="focusStrike = $event"
        />
      </div>
    </Panel>

    <!-- Quantitative Trading Strategies Playbook -->
    <Panel label="ACTIONABLE QUANTITATIVE STRATEGIES" meta="MICROSTRUCTURE PLAYBOOK" live>
      <div class="strategies-grid">
        <div
          v-for="strat in strategies"
          :key="strat.id"
          class="strategy-card"
          :class="{ active: strat.status === 'ACTIVE' || strat.status === 'TRIGGERED' }"
        >
          <div class="strat-top">
            <span class="strat-title">{{ strat.title }}</span>
            <span
              class="strat-status label"
              :class="{
                active: strat.status === 'ACTIVE',
                triggered: strat.status === 'TRIGGERED',
                monitoring: strat.status === 'MONITORING',
              }"
            >
              {{ strat.status }}
            </span>
          </div>

          <div class="strat-regime label">{{ strat.regime }}</div>

          <div class="strat-section">
            <span class="strat-label label">Condition:</span>
            <span class="strat-text">{{ strat.condition }}</span>
          </div>

          <div class="strat-section">
            <span class="strat-label label">Playbook Setup:</span>
            <span class="strat-text highlight">{{ strat.trade }}</span>
          </div>

          <div class="strat-section">
            <span class="strat-label label">Microstructure Mechanic:</span>
            <span class="strat-text note">{{ strat.mechanic }}</span>
          </div>
        </div>
      </div>
    </Panel>

    <!-- Strike Greeks & Dealer Flow Table -->
    <Panel
      :label="`${symbol} · STRIKE TABLE (PER-CONTRACT GREEKS &amp; DEALER HEDGE FLOW)`"
      :meta="`${strikeTable.length} strikes · OI / VOL / IV / Δ / Γ / CHARM`"
      flush
    >
      <template #action>
        <div class="table-controls">
          <div class="mini-segment" role="group" aria-label="Strike filter">
            <button
              type="button"
              class="label"
              :class="{ on: tableFilter === 'all' }"
              @click="tableFilter = 'all'"
            >
              ALL STRIKES
            </button>
            <button
              type="button"
              class="label"
              :class="{ on: tableFilter === 'near_spot' }"
              @click="tableFilter = 'near_spot'"
            >
              NEAR SPOT (±10%)
            </button>
            <button
              type="button"
              class="label"
              :class="{ on: tableFilter === 'high_charm' }"
              @click="tableFilter = 'high_charm'"
            >
              HIGH CHARM
            </button>
          </div>
        </div>
      </template>

      <div class="table-wrap">
        <LoadingState v-if="loading" label="Loading contracts…" />
        <div v-else-if="!strikeTable.length" class="placeholder">
          <span class="ph-msg">No contracts pass the active filters.</span>
        </div>
        <table v-else class="strike-table">
          <thead>
            <!-- Grouping Row -->
            <tr class="header-group">
              <th colspan="2" class="group-center">STRIKE IDENTIFIER</th>
              <th colspan="5" class="group-call">CALL OPTIONS (DEALER LONG INVENTORY)</th>
              <th colspan="5" class="group-put">PUT OPTIONS (DEALER SHORT INVENTORY)</th>
              <th colspan="2" class="group-net">DEALER NET FLOW</th>
            </tr>
            <!-- Individual Column Headers -->
            <tr class="header-cols">
              <th class="num strike-col">STRIKE</th>
              <th class="num moneyness-col">MONEYNESS</th>

              <!-- Call columns -->
              <th class="num call-head" title="Call Open Interest">CALL OI</th>
              <th class="num call-head" title="Call Volume Today">CALL VOL</th>
              <th class="num call-head" title="Implied Volatility">IV</th>
              <th class="num call-head" title="Black-Scholes Delta (∂V/∂S)">Δ (DELTA)</th>
              <th class="num call-head" title="Daily Charm (∂Δ/∂t per day)">CHARM/d</th>

              <!-- Put columns -->
              <th class="num put-head" title="Put Open Interest">PUT OI</th>
              <th class="num put-head" title="Put Volume Today">PUT VOL</th>
              <th class="num put-head" title="Implied Volatility">IV</th>
              <th class="num put-head" title="Black-Scholes Delta (∂V/∂S)">Δ (DELTA)</th>
              <th class="num put-head" title="Daily Charm (∂Δ/∂t per day)">CHARM/d</th>

              <!-- Net flow columns -->
              <th class="num net-head" title="Net shares/day dealers must trade to stay delta-neutral">NET CHARM FLOW</th>
              <th class="num net-head" title="Net Dollar Gamma Exposure per 1% move ($M)">NET GEX $M</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in strikeTable"
              :key="row.strike"
              :class="{
                'at-spot': row.isSpot,
                'at-call-wall': row.isCallWall,
                'at-put-wall': row.isPutWall,
                'at-gamma-flip': row.isGammaFlip,
              }"
            >
              <!-- Strike & Badges -->
              <td class="num strike-cell">
                <span class="strike-val">${{ num(row.strike, 0) }}</span>
                <span v-if="row.isSpot" class="badge spot-badge label">SPOT</span>
                <span v-if="row.isCallWall" class="badge call-wall-badge label">CALL WALL</span>
                <span v-if="row.isPutWall" class="badge put-wall-badge label">PUT WALL</span>
                <span v-if="row.isGammaFlip" class="badge flip-badge label">FLIP</span>
              </td>

              <!-- Moneyness -->
              <td class="num moneyness-cell">
                {{ row.distPct != null ? (row.distPct >= 0 ? `+${row.distPct.toFixed(1)}%` : `${row.distPct.toFixed(1)}%`) : '—' }}
              </td>

              <!-- Call Side -->
              <td class="num call-oi">{{ compact(row.call?.open_interest ?? null) }}</td>
              <td class="num call-vol">{{ compact(row.call?.volume ?? null) }}</td>
              <td class="num">{{ row.call?.iv != null ? `${(row.call.iv * 100).toFixed(0)}%` : '—' }}</td>
              <td class="num call-delta">{{ num(row.call?.delta ?? null, 3) }}</td>
              <td class="num call-charm">{{ row.call?.charm_per_day != null ? signed(row.call.charm_per_day, 5) : '—' }}</td>

              <!-- Put Side -->
              <td class="num put-oi">{{ compact(row.put?.open_interest ?? null) }}</td>
              <td class="num put-vol">{{ compact(row.put?.volume ?? null) }}</td>
              <td class="num">{{ row.put?.iv != null ? `${(row.put.iv * 100).toFixed(0)}%` : '—' }}</td>
              <td class="num put-delta">{{ num(row.put?.delta ?? null, 3) }}</td>
              <td class="num put-charm">{{ row.put?.charm_per_day != null ? signed(row.put.charm_per_day, 5) : '—' }}</td>

              <!-- Dealer Net Impact -->
              <td
                class="num net-charm-cell"
                :class="row.netCharmFlow > 0 ? 'sell-flow' : row.netCharmFlow < 0 ? 'buy-flow' : ''"
              >
                {{ row.netCharmFlow !== 0 ? signed(row.netCharmFlow, 0) : '0' }} <small>sh/d</small>
              </td>
              <td class="num gex-cell" :class="row.gex >= 0 ? 'call' : 'put'">
                {{ signed(row.gex, 2) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Panel>

    <!-- Freshness and compliance footer -->
    <p v-if="freshness?.feed_age_seconds != null && payload" class="freshness-note label">
      Feed age {{ Math.round(freshness.feed_age_seconds) }}s ·
      activity basis {{ payload.provider?.activity_basis ?? 'unavailable' }} ·
      charm source {{ charmSummary?.source ?? 'unavailable' }}
    </p>
    <p v-if="pressure" class="freshness-note label">{{ pressure.convention_note }}</p>
  </div>
</template>

<style scoped>
.drift-view {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  min-width: 0;
  padding-bottom: var(--s6);
}

.drift-head {
  position: relative;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s6);
  padding: var(--s4) var(--s5);
  border: var(--hair) solid var(--rule);
  border-left: 3px solid var(--phosphor);
  border-radius: var(--r-md);
  background: var(--surface-base);
}

.drift-title { min-width: 0; }
.eyebrow { color: var(--phosphor); }

h1 {
  margin: var(--s2) 0 0;
  color: var(--ink);
  font: 700 var(--t-display) / 1.15 var(--font-display);
  letter-spacing: var(--track-tight);
}

.drift-title p {
  max-width: 82ch;
  margin-top: var(--s3);
  color: var(--text-secondary);
  font-size: var(--t-body);
  line-height: 1.55;
}

.controls {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  align-items: flex-end;
}

.symbol-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.symbol-box .label {
  color: var(--ink-ghost);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
}
.symbol-input {
  width: 110px;
  padding: 4px 8px;
  color: var(--ink);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-size: var(--t-body);
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  text-align: right;
  transition: border-color var(--dur-fast) var(--ease-out);
}
.symbol-input:focus {
  outline: none;
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.range-box, .expiry-box, .preset-box {
  display: flex;
  gap: 2px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.range-btn, .expiry-btn, .preset-btn {
  min-height: var(--density-control-h);
  padding: 3px 10px;
  color: var(--ink-dim);
  background: transparent;
  border: none;
  cursor: pointer;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.range-btn:hover, .expiry-btn:hover, .preset-btn:hover { color: var(--ink); background: var(--panel-hi); }
.range-btn.on, .expiry-btn.on, .preset-btn.on {
  color: var(--phosphor);
  background: var(--phosphor-wash);
}

/* KPI cards */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--s2);
}
.kpi {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--panel);
}
.kpi.stale .k-val { color: var(--ink-faint); }
.k-key {
  color: var(--ink-ghost);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
}
.k-val {
  color: var(--ink);
  font-family: var(--font-data);
  font-size: var(--t-body);
  font-weight: 600;
}
.k-val.positive { color: var(--call-hi); }
.k-val.negative { color: var(--put-hi); }
.k-val.neutral { color: var(--ink-dim); }
.k-val.selling { color: var(--put-hi); }
.k-val.buying { color: var(--call-hi); }
.k-val.balanced { color: var(--ink-dim); }
.k-tag {
  align-self: flex-start;
  padding: 1px 5px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  color: var(--ink-dim);
}
.k-tag.positive { color: var(--call-hi); border-color: var(--call-dim); }
.k-tag.negative { color: var(--put-hi); border-color: var(--put-dim); }
.k-tag.selling { color: var(--put-hi); border-color: var(--put-dim); background: var(--put-wash); }
.k-tag.buying { color: var(--call-hi); border-color: var(--call-dim); background: var(--call-wash); }
.k-tag.live { color: var(--phosphor); border-color: var(--phosphor-dim); background: var(--phosphor-wash); }

/* Pressure gauge container */
.gauge-card-container {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.gauge-body {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  padding: var(--s3);
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.gauge-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.gauge-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.gauge-score {
  font-size: var(--t-body);
  font-weight: 700;
}
.gauge-score.selling { color: var(--put-hi); }
.gauge-score.buying { color: var(--call-hi); }
.gauge-score.balanced { color: var(--ink-dim); }

.gauge-track {
  position: relative;
  height: 20px;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: 3px;
  overflow: hidden;
}

.gauge-zones {
  display: flex;
  height: 100%;
}
.gauge-zones i {
  height: 100%;
  display: block;
}
.zone-sell-heavy { flex: 25; background: var(--put); opacity: 0.65; }
.zone-sell-mod { flex: 15; background: var(--put); opacity: 0.35; }
.zone-neutral { flex: 20; background: var(--surface-base); opacity: 0.4; }
.zone-buy-mod { flex: 15; background: var(--call); opacity: 0.35; }
.zone-buy-heavy { flex: 25; background: var(--call); opacity: 0.65; }

.gauge-ticks {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(var(--rule-hi), var(--rule-hi)) 25% 0 / 1px 100% no-repeat,
    linear-gradient(var(--rule-hi), var(--rule-hi)) 50% 0 / 1.5px 100% no-repeat,
    linear-gradient(var(--rule-hi), var(--rule-hi)) 75% 0 / 1px 100% no-repeat;
  pointer-events: none;
}

.gauge-needle {
  position: absolute;
  top: 50%;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--ink);
  border: 2px solid var(--rule-hi);
  transform: translate(-50%, -50%);
  pointer-events: none;
  transition: left var(--dur) var(--ease-out);
}
.gauge-needle.selling { background: var(--put-hi); }
.gauge-needle.buying { background: var(--call-hi); }
.gauge-needle.balanced { background: var(--ink); }

.gauge-labels {
  display: flex;
  justify-content: space-between;
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.05em;
  font-weight: 600;
}
.gauge-labels .sell { color: var(--put-hi); }
.gauge-labels .buy { color: var(--call-hi); }
.gauge-labels .neutral { color: var(--ink-dim); }

.gauge-note {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.03em;
}

/* 3-Factor Breakdown Grid */
.factor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--s3);
}

.factor-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--s3);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--panel);
}
.factor-card.buying { border-left: 2px solid var(--call); }
.factor-card.selling { border-left: 2px solid var(--put); }
.factor-card.positive { border-left: 2px solid var(--call); }
.factor-card.negative { border-left: 2px solid var(--put); }

.factor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.factor-badge {
  padding: 1px 5px;
  border-radius: 2px;
  font-size: 9px;
  font-weight: 700;
  border: var(--hair) solid var(--rule);
}
.factor-badge.buying, .factor-badge.positive { color: var(--call-hi); border-color: var(--call-dim); background: var(--call-wash); }
.factor-badge.selling, .factor-badge.negative { color: var(--put-hi); border-color: var(--put-dim); background: var(--put-wash); }

.factor-metric {
  font-size: var(--t-display);
  font-weight: 700;
  color: var(--ink);
}
.factor-metric.buying, .factor-metric.positive { color: var(--call-hi); }
.factor-metric.selling, .factor-metric.negative { color: var(--put-hi); }
.factor-metric small { font-size: var(--t-micro); color: var(--ink-dim); }

.factor-desc {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  line-height: 1.45;
  margin: 0;
}

/* Microstructure Assessment Box */
.assessment-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: var(--s3) var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--surface-base);
}
.assessment-box.buying { border-left: 3px solid var(--call-hi); }
.assessment-box.selling { border-left: 3px solid var(--put-hi); }
.assessment-box.balanced { border-left: 3px solid var(--phosphor); }

.assessment-header {
  display: flex;
  align-items: center;
  gap: 10px;
}
.assess-tag {
  color: var(--ink-ghost);
  font-size: 9px;
}
.assess-title {
  font-size: var(--t-body);
  font-weight: 700;
  color: var(--ink);
}
.assess-body {
  font-size: var(--t-body);
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0;
}
.assess-footer {
  font-size: var(--t-micro);
  color: var(--ink);
  padding-top: 6px;
  border-top: var(--hair) solid var(--rule-faint);
}
.assess-footer b { color: var(--phosphor); }

/* Strategies Grid */
.strategies-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--s3);
}

.strategy-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: var(--s3) var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--panel);
}
.strategy-card.active {
  border-color: var(--phosphor-dim);
  background: var(--surface-base);
}

.strat-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.strat-title {
  font-size: var(--t-body);
  font-weight: 700;
  color: var(--ink);
}
.strat-status {
  padding: 1px 6px;
  border-radius: var(--r-xs);
  font-size: 9px;
  font-weight: 700;
  border: var(--hair) solid var(--rule);
}
.strat-status.active { color: var(--call-hi); border-color: var(--call-dim); background: var(--call-wash); }
.strat-status.triggered { color: var(--warn); border-color: var(--warn); background: var(--warn-wash); }
.strat-status.monitoring { color: var(--ink-faint); }

.strat-regime {
  color: var(--ink-ghost);
  font-size: 10px;
}

.strat-section {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.strat-label {
  color: var(--ink-ghost);
  font-size: 9px;
  text-transform: uppercase;
}
.strat-text {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  line-height: 1.4;
}
.strat-text.highlight {
  color: var(--ink);
  font-weight: 600;
}
.strat-text.note {
  color: var(--ink-faint);
  font-style: italic;
}

/* Table controls */
.table-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mini-segment {
  display: inline-flex;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.mini-segment button {
  padding: 2px 8px;
  border: none;
  background: transparent;
  color: var(--ink-dim);
  font-size: 9px;
  font-weight: 600;
  cursor: pointer;
  text-transform: uppercase;
}
.mini-segment button.on {
  background: var(--phosphor-wash);
  color: var(--phosphor);
}

/* Enhanced Strike table */
.table-wrap {
  min-width: 0;
  overflow-x: auto;
  max-height: 520px;
}

.strike-table {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  color: var(--ink-dim);
}

.header-group th {
  position: sticky;
  top: 0;
  z-index: 3;
  padding: 4px 8px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-align: center;
  border-bottom: var(--hair) solid var(--rule);
}
.group-center { background: var(--void-lift); color: var(--ink); }
.group-call { background: var(--call-wash); color: var(--call-hi); border-left: var(--hair) solid var(--rule); }
.group-put { background: var(--put-wash); color: var(--put-hi); border-left: var(--hair) solid var(--rule); }
.group-net { background: var(--panel-hi); color: var(--phosphor); border-left: var(--hair) solid var(--rule); }

.header-cols th {
  position: sticky;
  top: 24px;
  z-index: 2;
  padding: 6px 8px;
  color: var(--ink-ghost);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-align: right;
  background: var(--panel-hi);
  border-bottom: var(--hair) solid var(--rule-hi);
  white-space: nowrap;
}
.strike-col { text-align: left; }
.call-head { color: var(--call-dim); }
.put-head { color: var(--put-dim); }
.net-head { color: var(--ink); }

.strike-table td {
  padding: 4px 8px;
  text-align: right;
  border-bottom: var(--hair) solid var(--rule-faint);
  white-space: nowrap;
}
.strike-table .num { font-variant-numeric: tabular-nums; }

.strike-cell {
  text-align: left;
  display: flex;
  align-items: center;
  gap: 6px;
}
.strike-val {
  color: var(--ink);
  font-weight: 700;
}

.badge {
  padding: 1px 4px;
  border-radius: 2px;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.spot-badge { background: var(--phosphor); color: var(--void); }
.call-wall-badge { background: var(--call-dim); color: var(--void); }
.put-wall-badge { background: var(--put-dim); color: var(--void); }
.flip-badge { background: var(--warn); color: var(--void); }

.moneyness-cell {
  color: var(--ink-faint);
  font-size: 10px;
}

.call-oi, .call-vol { color: var(--ink); }
.call-delta { color: var(--call-dim); font-weight: 600; }
.call-charm { color: var(--call-dim); }

.put-oi, .put-vol { color: var(--ink); }
.put-delta { color: var(--put-dim); font-weight: 600; }
.put-charm { color: var(--put-dim); }

.net-charm-cell {
  font-weight: 600;
}
.net-charm-cell.sell-flow { color: var(--put-hi); }
.net-charm-cell.buy-flow { color: var(--call-hi); }

.gex-cell {
  font-weight: 600;
}
.gex-cell.call { color: var(--call-hi); }
.gex-cell.put { color: var(--put-hi); }

.strike-table tr.at-spot td {
  background: var(--phosphor-wash);
}
.strike-table tr.at-call-wall td {
  background: var(--call-wash);
}
.strike-table tr.at-put-wall td {
  background: var(--put-wash);
}
.strike-table tr:hover td {
  background: var(--panel-hi);
}

.chart-slot {
  min-width: 0;
}
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  color: var(--ink-faint);
  font-family: var(--font-display);
  font-size: 12px;
  letter-spacing: 0.08em;
  background: var(--void-lift);
}
.ph-msg.fault { color: var(--warn); }

.state-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 6px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  color: var(--ink-dim);
}
.state-chip.live { color: var(--phosphor); border-color: var(--phosphor-dim); background: var(--phosphor-wash); }
.state-chip.fault { color: var(--warn); border-color: var(--warn); }

.freshness-note {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.03em;
}

.live-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--phosphor);
  margin-right: 6px;
  vertical-align: middle;
  animation: dot-pulse 2s ease-in-out infinite;
}
@keyframes dot-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

@media (max-width: 900px) {
  .drift-head {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--s3);
  }
  .controls {
    align-items: stretch;
    width: 100%;
  }
  .symbol-box { align-items: flex-start; }
  .symbol-input { width: 100%; text-align: left; }
  .range-box, .expiry-box, .preset-box { width: 100%; }
  .range-btn, .expiry-btn, .preset-btn { flex: 1 1 0; }
}
</style>
