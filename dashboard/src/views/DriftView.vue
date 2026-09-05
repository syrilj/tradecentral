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
 * Charm = ∂Δ/∂t — the delta decay per day. The tab computes Black-Scholes charm
 * for every contract in the chain, aggregates charm flow (charm × OI × 100, shares/day)
 * by strike under the dealer sign convention, and combines it with GEX and
 * delta-weighted live volume into one pressure gauge:
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

const QUICK_SYMBOLS = [
  'NVDA',
  'SPY',
  'QQQ',
  'IWM',
  'DIA',
  'AAPL',
  'TSLA',
  'AMD',
  'MSFT',
  'AMZN',
  'XLF',
  'XLE',
] as const

const RANGES: { value: OptionsRange; label: string }[] = [
  { value: '1d', label: '1D' },
  { value: '5d', label: '5D' },
  { value: '1m', label: '1M' },
  { value: '3m', label: '3M' },
]

function readSymbol(): string {
  const raw = route.query.symbol
  const value = Array.isArray(raw) ? raw[0] : raw
  return (
    String(value || 'NVDA')
      .trim()
      .toUpperCase()
      .replace(/[^A-Z0-9.-]/g, '')
      .slice(0, 10) || 'NVDA'
  )
}

const symbolInput = ref(readSymbol())
const symbol = ref(readSymbol())
const mode = ref<OptionsMode>('live')
const selectedRange = ref<OptionsRange>('5d')
const selectedExpiry = ref<string>('all')
const refreshMs = ref(30_000)

/** Balanced defaults — keep some structure visible on mid-caps. */
const minPremium = ref(25_000)
const preset = ref<'strict' | 'balanced' | 'raw'>('balanced')

/** Table filter mode: 'all' | 'nearest' | 'near_spot' | 'high_charm' | 'walls' */
type TableFilterMode = 'all' | 'nearest' | 'near_spot' | 'high_charm' | 'walls'
const tableFilter = ref<TableFilterMode>('all')
const tableSearch = ref('')
const sortCol = ref<string>('strike')
const sortAsc = ref(true)

/** Strategy display mode: 'primary' | 'all' */
const strategyViewMode = ref<'primary' | 'all'>('primary')

const optionsRes = useResource<OptionsIntelligence>(
  () =>
    api.options({
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

watch(
  () => route.query.symbol,
  (val) => {
    const next = Array.isArray(val) ? val[0] : val
    if (typeof next === 'string' && next && next.toUpperCase() !== symbol.value) {
      symbol.value = next.toUpperCase()
      symbolInput.value = next.toUpperCase()
    }
  },
)

function applySymbol(): void {
  const clean = symbolInput.value
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
    .slice(0, 10)
  if (!clean || clean === symbol.value) return
  symbol.value = clean
  symbolInput.value = clean
  void router.replace({ name: 'drift', query: { symbol: clean, range: selectedRange.value } })
}

function selectQuickSymbol(sym: string): void {
  if (sym === symbol.value) return
  symbol.value = sym
  symbolInput.value = sym
  void router.replace({ name: 'drift', query: { symbol: sym, range: selectedRange.value } })
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

function setExpiry(e: string): void {
  if (e === selectedExpiry.value) return
  selectedExpiry.value = e
  void optionsRes.refresh({ clear: true })
}

function onExpirySelectChange(e: Event): void {
  const val = (e.target as HTMLSelectElement).value
  setExpiry(val)
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
const chainContext = computed(() => payload.value?.chain_context)
const availableExpiries = computed(() => chainContext.value?.available_expiries ?? [])
const probability = computed(() => payload.value?.probability)

const spot = computed(() => summary.value?.spot ?? null)
const callWall = computed(() => summary.value?.call_wall ?? null)
const putWall = computed(() => summary.value?.put_wall ?? null)
const gammaFlip = computed(() => summary.value?.gamma_flip ?? null)
const callPutRatio = computed(() => summary.value?.call_put_ratio ?? null)
const netGex = computed(() => summary.value?.total_gex_m ?? null)
const gexRegime = computed(() => summary.value?.regime ?? 'neutral')
const netCharmFlow = computed(() => charmSummary.value?.net_charm_flow ?? null)
const charmPressure = computed(() => charmSummary.value?.pressure ?? 'balanced')

/**
 * Net charm flow as a share of the chain's own gross charm magnitude, in [-1, 1].
 *
 * Net charm flow is shares/day and scales with open interest, so absolute
 * cutoffs (the old ±1500 / −2000) fired on essentially every liquid symbol and
 * never on an illiquid one — which made the "charm is one-sided" branches
 * unconditional for large caps and silently overrode the pressure gauge.
 * Dividing by gross makes the test scale-free and comparable across symbols.
 * Negative = dealers buy (bullish tailwind); positive = dealers sell.
 */
const charmRatio = computed(() => {
  const gross = charmSummary.value?.abs_charm_flow ?? 0
  const net = charmSummary.value?.net_charm_flow ?? 0
  return gross > 0 ? net / gross : 0
})
/** A fifth of all charm flow pointing one way counts as one-sided. */
const CHARM_ONE_SIDED = 0.2

/**
 * Render one pressure-gauge channel ratio. `null` means the channel had no gross
 * magnitude and abstained from the blend — show that, never a 0 it didn't vote.
 */
function channelText(value: number | null): string {
  return value == null || !Number.isFinite(value) ? 'n/a' : signed(value, 2)
}

/** Human-readable cause when part (or all) of the chain could not be charmed. */
const CHARM_SKIP_LABELS: Record<string, string> = {
  malformed_row: 'missing strike/right',
  missing_dte: 'unknown expiry',
  expiring_within_one_day: 'expiring within 1 day',
  missing_or_implausible_iv: 'missing or implausible IV',
}
const charmSkipDetail = computed(() => {
  const reasons = charmSummary.value?.skipped_reasons
  if (!reasons) return null
  const parts = Object.entries(reasons)
    .filter(([, count]) => typeof count === 'number' && count > 0)
    .map(([key, count]) => `${count} ${CHARM_SKIP_LABELS[key] ?? key}`)
  return parts.length ? parts.join(' · ') : null
})
/**
 * True when the chain arrived but nothing in it was measurable. The chart would
 * otherwise render an axis full of legitimate-looking zeros — the "data is not
 * present" case has to say so out loud.
 */
const charmAllSkipped = computed(
  () => !!charmSummary.value && charmSummary.value.contracts_measured === 0,
)
/**
 * Actionable hint for the dominant skip reason. On expiration day the "nearest"
 * expiry is entirely 0DTE, where charm diverges and the model has no answer —
 * the fix is to pick a later expiry, so say that rather than just "no data".
 */
const charmSkipHint = computed(() => {
  const reasons = charmSummary.value?.skipped_reasons
  if (!reasons) return null
  if (reasons.expiring_within_one_day) {
    return 'Charm is undefined at expiry — select a later expiry above.'
  }
  if (reasons.missing_or_implausible_iv) {
    return 'The provider did not return usable implied vol for this chain.'
  }
  return null
})

const expectedMove = computed(
  () => probability.value?.expected_move ?? (spot.value ? spot.value * 0.035 : null),
)
const atmIv = computed(() => probability.value?.atm_iv ?? null)

const asof = computed(() => payload.value?.asof_utc ?? null)
const modeResolved = computed(() => payload.value?.mode_resolved ?? null)
const spotSource = computed(() => payload.value?.spot_source ?? null)
const loading = computed(() => optionsRes.loading.value && !payload.value)
/** True during any in-flight fetch including background polls — used for the
 *  subtle "refreshing" spinner on the KPI row and chart panel. */
const refreshing = computed(() => optionsRes.loading.value)
const error = computed(() => optionsRes.error.value)
const hasChain = computed(() => gexRows.value.length > 0 || chainRows.value.length > 0)

/** Spot is structurally stale when its source is a frozen snapshot or a
 *  multi-day local close — the chain may be live while the spot is not. */
const spotStale = computed(() => {
  const src = spotSource.value
  if (!src) return false
  return src.startsWith('cached_chain_spot') || src.startsWith('local_daily_close')
})

const gexRegimeLabel = computed(
  () =>
    ({
      positive: 'MEAN-REVERSION',
      negative: 'TRENDING',
      neutral: 'NEUTRAL',
    })[gexRegime.value],
)

const pressureLabel = computed(
  () =>
    ({
      buying: 'BUYING PRESSURE',
      selling: 'SELLING PRESSURE',
      balanced: 'BALANCED',
    })[pressure.value?.label ?? 'balanced'],
)

const gaugePct = computed(() => {
  const v = pressure.value?.imbalance
  if (v == null || !Number.isFinite(v)) return 50
  return Math.round(((v + 1) / 2) * 100)
})

/** Server-side read: confidence band, actionability and the channels behind it. */
const pressureBand = computed(() => pressure.value?.confidence?.band ?? 'unmeasurable')
const pressureActionable = computed(() => pressure.value?.actionable === true)
const pressureVerdict = computed(() => pressure.value?.verdict ?? pressureLabel.value)
const tapeChannel = computed(() => pressure.value?.tape ?? null)
const underlyingChannel = computed(() => pressure.value?.underlying ?? null)
const pressureConflicts = computed(() => pressure.value?.conflicts ?? [])
const pressureReasons = computed(() => pressure.value?.reasons ?? [])

/** How the tape's sides were resolved — the trader should see what kind of evidence this is. */
const tapeSideMixText = computed(() => {
  const tape = tapeChannel.value
  if (!tape || tape.n_total === 0) return 'no prints in window'
  const mix = tape.source_mix
  const parts: string[] = []
  if (mix.vendor) parts.push(`${mix.vendor} vendor-signed`)
  if (mix.quote_rule_live) parts.push(`${mix.quote_rule_live} vs live quote`)
  if (mix.quote_rule_delayed) parts.push(`${mix.quote_rule_delayed} vs delayed quote (½ weight)`)
  if (mix.tick_rule) parts.push(`${mix.tick_rule} by tick test (0.4 weight)`)
  if (mix.unresolved) parts.push(`${mix.unresolved} unresolved`)
  return parts.join(' · ')
})

interface PressureChannelRow {
  key: 'charm' | 'tape' | 'underlying'
  name: string
  ratio: number | null
  weight: number
  detail: string
  tone: 'buying' | 'selling' | 'balanced' | 'na'
}

/** One row per voting channel: what it read, how much it weighs, and why it may have abstained. */
const pressureChannelRows = computed<PressureChannelRow[]>(() => {
  const p = pressure.value
  if (!p) return []
  const tone = (ratio: number | null): PressureChannelRow['tone'] => {
    if (ratio == null || !Number.isFinite(ratio)) return 'na'
    const threshold = p.thresholds?.direction ?? 0.25
    return ratio > threshold ? 'buying' : ratio < -threshold ? 'selling' : 'balanced'
  }
  const charmMeasured = charmSummary.value?.contracts_measured ?? 0
  const charmSkipped = charmSummary.value?.contracts_skipped ?? 0
  const tape = tapeChannel.value
  const und = underlyingChannel.value
  return [
    {
      key: 'charm',
      name: 'Charm positioning',
      ratio: p.channels.charm,
      weight: p.weights.charm,
      detail:
        p.channels.charm == null
          ? 'no measurable charm flow'
          : `${signed(p.components.net_charm_flow, 0)} sh/d · ${charmMeasured}/${charmMeasured + charmSkipped} contracts · model proxy`,
      tone: tone(p.channels.charm),
    },
    {
      key: 'tape',
      name: 'Tape buyers vs sellers',
      ratio: p.channels.tape,
      weight: p.weights.tape,
      detail: tape
        ? `${tape.n_signed}/${tape.n_total} prints sided · ${Math.round(tape.coverage * 100)}% of premium · ${tapeSideMixText.value}`
        : 'no flow prints available',
      tone: tone(p.channels.tape),
    },
    {
      key: 'underlying',
      name: 'Underlying volume read',
      ratio: p.channels.underlying,
      weight: p.weights.underlying,
      detail: und
        ? `${und.bars_used} × ${und.timeframe ?? '?'} bars · rvol ${und.rvol != null ? und.rvol.toFixed(2) + '×' : 'n/a'} · close-location proxy${und.stale ? ' · STALE' : ''}`
        : 'no underlying bars supplied',
      tone: tone(p.channels.underlying),
    },
  ]
})

const dataModeBadge = computed(() => {
  if (loading.value) return 'SYNC'
  if (error.value) return 'FAULT'
  if (modeResolved.value === 'live') return spotStale.value ? 'LIVE · SPOT STALE' : 'LIVE'
  if (modeResolved.value === 'history') return 'HISTORY'
  if (modeResolved.value === 'history_fallback') return 'DELAYED'
  return 'NO DATA'
})

const activeExpiryLabel = computed(() => {
  if (selectedExpiry.value === 'all') return 'ALL EXPIRIES (COMPOSITE)'
  if (selectedExpiry.value === 'nearest') {
    const activeDate = chainContext.value?.selected_expiry
    const activeDte = chainContext.value?.selected_dte
    return activeDate ? `NEAREST · ${activeDate} (${activeDte} DTE)` : 'NEAREST EXPIRY'
  }
  const match = availableExpiries.value.find((e) => e.expiry === selectedExpiry.value)
  return match ? `${match.expiry} (${match.dte} DTE)` : selectedExpiry.value
})

/** Directional assessment with unambiguous Long vs Short / Buying vs Selling signals. */
const microstructureAssessment = computed(() => {
  if (!pressure.value || !summary.value) return null
  const imb = pressure.value.imbalance
  const regimeStr = summary.value.regime
  const flowVal = charmSummary.value?.net_charm_flow ?? 0
  const ratio = charmRatio.value
  const spotVal = spot.value
  const cw = callWall.value
  const pw = putWall.value
  const flip = gammaFlip.value

  // 1. Breakout Above Resistance / Flip
  if (cw != null && spotVal != null && spotVal >= cw) {
    return {
      title: 'Bullish Breakout Above Call Wall Resistance',
      direction: 'LONG BIAS (BREAKOUT CONTINUATION)',
      action: 'UPWARD VOLATILITY EXPANSION',
      tone: 'buying',
      body: `Spot ($${num(spotVal, 2)}) has breached above Call Wall ($${num(cw, 0)}). Dealer call gamma flips and dealer inventory short-covering accelerates upside continuation.`,
      implication: `Ride bullish expansion momentum with trailing stops below Call Wall ($${num(cw, 0)}). Target +1 EM move.`,
    }
  }

  // 2. Breakdown Below Support / Flip
  if (
    (pw != null && spotVal != null && spotVal <= pw) ||
    (flip != null && spotVal != null && spotVal < flip && regimeStr === 'negative')
  ) {
    return {
      title: 'Bearish Breakdown Below Key Structural Support',
      direction: 'SHORT BIAS (SELLING HEADWIND)',
      action: 'DOWNSIDE VOLATILITY CASCADE',
      tone: 'selling',
      body: `Spot ($${num(spotVal, 2)}) is trading below key structural support (Put Wall $${num(pw, 0)} / Flip $${num(flip, 0)}). Dealer pro-cyclical short hedging accelerates downward slip.`,
      implication: `Favors Bear Put Spreads and fading counter-trend bounces with invalidation on reclaim above $${num(pw ?? flip, 0)}.`,
    }
  }

  // 3. A directional lean the server could not confirm. This used to be
  // promoted straight to "Strong Structural Buying/Selling Pressure" off the
  // gauge sign alone; now the read says it is unconfirmed and why — a charm
  // positioning proxy with no tape or underlying corroboration is a watch
  // item, not a trade.
  const actionable = pressure.value.actionable === true
  const band = pressure.value.confidence?.band ?? 'unmeasurable'
  if (!actionable && (Math.abs(imb) > 0.25 || Math.abs(ratio) >= CHARM_ONE_SIDED)) {
    const lean = imb > 0.25 ? 'buying' : imb < -0.25 ? 'selling' : ratio < 0 ? 'buying' : 'selling'
    const conflictText = pressure.value.conflicts.map((c) => c.note).join('; ')
    const active = pressure.value.confidence?.channels_active ?? 0
    return {
      title: `Unconfirmed ${lean === 'buying' ? 'Buying' : 'Selling'} Lean`,
      direction: 'NO TRADE · WAIT FOR CONFIRMATION',
      action: `${band.toUpperCase()} CONFIDENCE`,
      tone: 'balanced',
      body: conflictText
        ? `The evidence disagrees: ${conflictText}.`
        : `The ${lean} read rests on ${active} directional channel${active === 1 ? '' : 's'} and is not corroborated by the tape or the underlying.`,
      implication:
        pressure.value.reasons.slice(0, 3).join(' · ') ||
        'Wait for side-resolved tape flow or the underlying to confirm the positioning read.',
    }
  }

  // 4. Charm Buying Tailwind — only when the blended read is confirmed.
  if (actionable && imb > 0.25) {
    return {
      title: 'Strong Structural Buying Pressure',
      direction: 'LONG BIAS (BUYING TAILWIND)',
      action: 'BUYING EQUILIBRIUM',
      tone: 'buying',
      body: `Dealers are net short decaying OTM put contracts. As time passes without a downward move, put deltas decay toward zero, forcing dealers to systematically BUY back their short equity hedges (${compact(Math.abs(flowVal))} shares/day).`,
      implication:
        'Mechanical tailwind supporting price; dips into the Put Wall ($' +
        num(summary.value.put_wall, 0) +
        ') find rapid absorption. Favors Long Call Spreads and buying pullback support.',
    }
  }

  // 5. Charm Selling Headwind — same guard as branch 4, mirrored.
  if (actionable && imb < -0.25) {
    return {
      title: 'Strong Structural Selling Pressure',
      direction: 'SHORT BIAS (SELLING HEADWIND)',
      action: 'SELLING OVERHANG',
      tone: 'selling',
      body: `Long call gamma/delta decay dominates dealer inventory. As call deltas decay over time, dealers are forced to SELL underlying stock to remain delta-neutral (${compact(Math.abs(flowVal))} shares/day).`,
      implication:
        'Mechanical headwind capping upside; rallies toward the Call Wall ($' +
        num(summary.value.call_wall, 0) +
        ') face persistent dealer inventory supply. Favors selling rips or Long Put Spreads.',
    }
  }

  // 5. Range Mean-Reversion in Positive Gamma Channel
  if (
    regimeStr === 'positive' ||
    (spotVal != null && pw != null && cw != null && spotVal >= pw && spotVal <= cw)
  ) {
    return {
      title: 'Balanced Flow in Positive Gamma Channel',
      direction: 'RANGE MEAN-REVERSION (BUY LOW / SELL HIGH)',
      action: 'VOLATILITY DAMPENING',
      tone: 'range',
      body: `Dealer positioning is Net Long Gamma ($${compact(summary.value.total_gex_m ?? 0)}M GEX). Dealers hedge counter-cyclically (buying dips, selling rips), compressing realized volatility between Put Wall ($${num(summary.value.put_wall, 0)}) and Call Wall ($${num(summary.value.call_wall, 0)}).`,
      implication:
        'High probability of range-bound mean-reversion. Fade range extremes (buy support at Put Wall, take profit at Call Wall); breakout follow-through is low.',
    }
  }

  // 6. Neutral Consolidation
  return {
    title: 'Neutral / Transitory Market Equilibrium',
    direction: 'NEUTRAL PIVOT WATCH',
    action: 'BREAKOUT EXPANSION MONITOR',
    tone: 'balanced',
    body: `Charm drift and directional options flow are evenly matched. The key structural pivot to monitor is the Gamma Flip point at $${num(summary.value.gamma_flip, 0)}.`,
    implication:
      'Monitor live flow tape for directional sweeps or sudden volume imbalances across near-the-money strikes.',
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

/** Complete union of all strikes with Greeks and dealer flow. */
const allStrikeRows = computed<StrikeTableRow[]>(() => {
  const byStrike = new Map<number, { call: ChainStrikeRow | null; put: ChainStrikeRow | null }>()

  // Index chain rows
  for (const row of chainRows.value) {
    const entry = byStrike.get(row.strike) ?? { call: null, put: null }
    if (row.right === 'call') entry.call = row
    else entry.put = row
    byStrike.set(row.strike, entry)
  }

  // Ensure all strikes from gexRows and charmRows are present
  for (const row of gexRows.value) {
    if (!byStrike.has(row.strike)) {
      byStrike.set(row.strike, { call: null, put: null })
    }
  }
  for (const row of charmRows.value) {
    if (!byStrike.has(row.strike)) {
      byStrike.set(row.strike, { call: null, put: null })
    }
  }

  const gexByStrike = new Map(gexRows.value.map((r) => [r.strike, r.net_gex_m]))
  const charmByStrike = new Map(charmRows.value.map((r) => [r.strike, r.net_charm_flow]))
  const spotVal = spot.value

  const list: StrikeTableRow[] = []
  for (const [strike, entry] of byStrike.entries()) {
    const distPct = spotVal && spotVal > 0 ? ((strike - spotVal) / spotVal) * 100 : null
    const isSpot = spotVal != null && Math.abs(strike - spotVal) <= spotVal * 0.007
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

  return list.sort((a, b) => a.strike - b.strike)
})

/** Filtered and sorted strike table. */
const strikeTable = computed<StrikeTableRow[]>(() => {
  let list = allStrikeRows.value
  const spotVal = spot.value

  // Text search filter
  if (tableSearch.value.trim()) {
    const q = tableSearch.value.trim().toLowerCase()
    list = list.filter((r) => r.strike.toString().includes(q))
  }

  // Filter modes
  if (tableFilter.value === 'nearest' && spotVal != null && list.length > 0) {
    // 10 closest strikes below and 10 closest strikes above spot
    const below = list.filter((r) => r.strike <= spotVal).slice(-10)
    const above = list.filter((r) => r.strike > spotVal).slice(0, 10)
    const combined = new Map<number, StrikeTableRow>()
    for (const r of [...below, ...above]) combined.set(r.strike, r)
    list = Array.from(combined.values()).sort((a, b) => a.strike - b.strike)
  } else if (tableFilter.value === 'near_spot' && spotVal != null) {
    list = list.filter((r) => r.distPct != null && Math.abs(r.distPct) <= 10)
  } else if (tableFilter.value === 'high_charm') {
    // A flat 500 sh/d cutoff is meaningless across symbols: every strike on a
    // mega-cap clears it (the filter did nothing) while no strike on a thin name
    // does (the table came back empty and read as missing data). Scale to the
    // chain's own largest strike so "high charm" means high *for this chain*.
    const peak = list.reduce((max, r) => Math.max(max, Math.abs(r.netCharmFlow)), 0)
    list = peak > 0 ? list.filter((r) => Math.abs(r.netCharmFlow) >= peak * 0.2) : []
  } else if (tableFilter.value === 'walls') {
    list = list.filter((r) => r.isSpot || r.isCallWall || r.isPutWall || r.isGammaFlip)
  }

  // Column sorting
  const col = sortCol.value
  const asc = sortAsc.value
  return [...list].sort((a, b) => {
    let va = 0
    let vb = 0
    if (col === 'strike') {
      va = a.strike
      vb = b.strike
    } else if (col === 'moneyness') {
      va = a.distPct ?? 0
      vb = b.distPct ?? 0
    } else if (col === 'call_oi') {
      va = a.call?.open_interest ?? 0
      vb = b.call?.open_interest ?? 0
    } else if (col === 'call_vol') {
      va = a.call?.volume ?? 0
      vb = b.call?.volume ?? 0
    } else if (col === 'call_iv') {
      va = a.call?.iv ?? 0
      vb = b.call?.iv ?? 0
    } else if (col === 'call_delta') {
      va = a.call?.delta ?? 0
      vb = b.call?.delta ?? 0
    } else if (col === 'call_gamma') {
      va = a.call?.gamma ?? 0
      vb = b.call?.gamma ?? 0
    } else if (col === 'call_charm') {
      va = a.call?.charm_per_day ?? 0
      vb = b.call?.charm_per_day ?? 0
    } else if (col === 'put_oi') {
      va = a.put?.open_interest ?? 0
      vb = b.put?.open_interest ?? 0
    } else if (col === 'put_vol') {
      va = a.put?.volume ?? 0
      vb = b.put?.volume ?? 0
    } else if (col === 'put_iv') {
      va = a.put?.iv ?? 0
      vb = b.put?.iv ?? 0
    } else if (col === 'put_delta') {
      va = a.put?.delta ?? 0
      vb = b.put?.delta ?? 0
    } else if (col === 'put_gamma') {
      va = a.put?.gamma ?? 0
      vb = b.put?.gamma ?? 0
    } else if (col === 'put_charm') {
      va = a.put?.charm_per_day ?? 0
      vb = b.put?.charm_per_day ?? 0
    } else if (col === 'net_charm') {
      va = a.netCharmFlow
      vb = b.netCharmFlow
    } else if (col === 'gex') {
      va = a.gex
      vb = b.gex
    }
    return asc ? va - vb : vb - va
  })
})

function toggleSort(col: string): void {
  if (sortCol.value === col) {
    sortAsc.value = !sortAsc.value
  } else {
    sortCol.value = col
    sortAsc.value = col === 'strike'
  }
}

function exportCsv(): void {
  const rows = strikeTable.value
  if (!rows.length) return
  const headers = [
    'Strike',
    'Moneyness_Pct',
    'Call_OI',
    'Call_Vol',
    'Call_IV_Pct',
    'Call_Delta',
    'Call_Gamma',
    'Call_Charm_Day',
    'Put_OI',
    'Put_Vol',
    'Put_IV_Pct',
    'Put_Delta',
    'Put_Gamma',
    'Put_Charm_Day',
    'Net_Charm_Flow_Shares_Day',
    'Net_GEX_Millions',
  ]
  const lines = [headers.join(',')]
  for (const r of rows) {
    lines.push(
      [
        r.strike,
        r.distPct != null ? r.distPct.toFixed(2) : '',
        r.call?.open_interest ?? 0,
        r.call?.volume ?? 0,
        r.call?.iv != null ? (r.call.iv * 100).toFixed(1) : '',
        r.call?.delta != null ? r.call.delta.toFixed(3) : '',
        r.call?.gamma != null ? r.call.gamma.toFixed(4) : '',
        r.call?.charm_per_day != null ? r.call.charm_per_day.toFixed(5) : '',
        r.put?.open_interest ?? 0,
        r.put?.volume ?? 0,
        r.put?.iv != null ? (r.put.iv * 100).toFixed(1) : '',
        r.put?.delta != null ? r.put.delta.toFixed(3) : '',
        r.put?.gamma != null ? r.put.gamma.toFixed(4) : '',
        r.put?.charm_per_day != null ? r.put.charm_per_day.toFixed(5) : '',
        r.netCharmFlow.toFixed(1),
        r.gex.toFixed(3),
      ].join(','),
    )
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${symbol.value}_drift_strike_table_${selectedRange.value}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

/** Actionable quantitative trading strategies playbook with unambiguous Long/Short signals. */
const strategies = computed(() => {
  const spotVal = spot.value
  const cw = callWall.value
  const pw = putWall.value
  const flip = gammaFlip.value
  const gex = netGex.value ?? 0
  const charm = netCharmFlow.value ?? 0
  const em = expectedMove.value ?? (spotVal ? spotVal * 0.03 : 5.0)
  const imb = pressure.value?.imbalance ?? 0

  // Structural breakdown: spot is below a key support level in negative-gamma regime.
  // This takes priority over pressure-gauge-only signals (mirrors microstructureAssessment ordering).
  const structuralBreakdown =
    (pw != null && spotVal != null && spotVal <= pw) ||
    (flip != null && spotVal != null && spotVal < flip && gex < 0)

  // Only a server-confirmed directional read can arm a pressure-driven
  // strategy. An unconfirmed lean leaves the range regime standing.
  const actionable = pressure.value?.actionable === true
  const s1Active =
    gex >= 0 &&
    spotVal != null &&
    pw != null &&
    cw != null &&
    spotVal >= pw &&
    spotVal <= cw &&
    (Math.abs(imb) <= 0.25 || !actionable)
  // s2Active (LONG/buying) is suppressed when the structural breakdown condition holds —
  // a bullish gauge reading alone does not override a structural support break.
  // Charm one-sidedness on its own no longer arms it: a positioning proxy
  // cannot corroborate itself.
  const s2Active =
    !structuralBreakdown &&
    ((cw != null && spotVal != null && spotVal >= cw) ||
      (actionable && imb > 0.25 && (cw == null || (spotVal != null && spotVal < cw))))
  const s3Active = structuralBreakdown || (actionable && imb < -0.25)

  return [
    {
      id: 'strat-1',
      title: 'Strategy 1: Mean-Reversion Channeling',
      regime: 'Positive Gamma (+GEX)',
      direction: 'LONG at Put Wall / SHORT at Call Wall',
      directionType: 'range' as const,
      biasTag: 'RANGE MEAN-REVERSION',
      status: s1Active ? 'ACTIVE' : 'MONITORING',
      isActive: s1Active,
      entryZone: pw != null ? `$${num(pw, 0)} (Put Wall Support)` : `Near Spot $${num(spotVal, 0)}`,
      target1: spotVal != null ? `$${num(spotVal + em * 0.5, 2)} (Equilibrium)` : 'Equilibrium',
      target2: cw != null ? `$${num(cw, 0)} (Call Wall Ceiling)` : 'Call Wall',
      stopLoss: pw != null ? `$${num(pw * 0.985, 2)} (Below Put Wall)` : 'Below Support',
      riskReward:
        pw && cw && spotVal && spotVal > pw
          ? ((cw - spotVal) / (spotVal - pw * 0.985)).toFixed(1) + 'x'
          : '2.2x',
      condition: `Spot ($${num(spotVal, 0)}) bounded between Put Wall ($${num(pw, 0)}) and Call Wall ($${num(cw, 0)}), Net GEX > 0`,
      trade:
        'Fade range boundaries. BUY: Enter long call spreads / long shares near Put Wall support. SELL: Take profit and sell call spreads near Call Wall resistance.',
      mechanic:
        'Dealer counter-cyclical hedging dampens realized volatility: dealers buy falling prices and sell rising prices, enforcing range compression.',
      stages: [
        {
          name: 'Stage 1 · Absorption [BUY ZONE]',
          note: 'Spot tests Put Wall ($' + num(pw, 0) + '). Dealers buy dips to hedge put gamma.',
        },
        {
          name: 'Stage 2 · Mean Reversion [DRIFT UP]',
          note: 'Price drifts toward spot equilibrium / VWAP baseline.',
        },
        {
          name: 'Stage 3 · Resistance Pin [SELL / TAKE PROFIT]',
          note: 'Price reaches Call Wall ($' + num(cw, 0) + '). Dealer supply caps upside.',
        },
      ],
    },
    {
      id: 'strat-2',
      title: 'Strategy 2: Breakout Expansion & Charm Inflow',
      regime: 'Breakout Expansion & Time-Decay (dΔ/dt)',
      direction: 'LONG BIAS (BUYING MOMENTUM)',
      directionType: 'buying' as const,
      biasTag: 'LONG BIAS',
      status: s2Active ? 'ACTIVE' : 'MONITORING',
      isActive: s2Active,
      entryZone:
        cw != null && spotVal != null && spotVal >= cw
          ? `$${num(cw, 0)} (Breakout Above Wall)`
          : `$${num(spotVal, 2)} (Dip Inflow)`,
      target1:
        spotVal != null ? `$${num(spotVal + em, 2)} (+${num(em, 1)} Move)` : 'Upside Target 1',
      target2:
        spotVal != null
          ? `$${num(spotVal + em * 2, 2)} (+${num(em * 2, 1)} Expansion)`
          : 'Call Wall Expansion',
      stopLoss:
        cw != null && spotVal != null && spotVal >= cw
          ? `$${num(cw * 0.99, 2)} (Below Breakout)`
          : pw != null
            ? `$${num(pw, 2)} (Put Wall Floor)`
            : 'Support Floor',
      riskReward: '2.6x',
      condition: `Spot ($${num(spotVal, 0)}) breaking above Call Wall ($${num(cw, 0)}) OR Net Charm Flow negative (${signed(charm, 0)} sh/d buying tailwind)`,
      trade:
        'DIRECTIONAL LONG: Buy Spot, Call Options, or Bull Call Spreads. Ride dealer short-covering tailwind and upside breakout momentum.',
      mechanic:
        'Dealer short OTM put hedges decay toward 0 delta as time passes, forcing continuous buyback of short stock hedges. Above Call Wall, gamma flips to fuel acceleration.',
      stages: [
        {
          name: 'Stage 1 · Time Decay Accumulation [BUY ACCUMULATION]',
          note: 'OTM puts decay rapidly into expiration; dealer delta approaches 0.',
        },
        {
          name: 'Stage 2 · Mechanical Buying [UPWARD DRIFT]',
          note: 'Dealers buy +' + compact(Math.abs(charm)) + ' shares/day to unwind short hedges.',
        },
        {
          name: 'Stage 3 · Resistance Break [BREAKOUT EXPANSION]',
          note: 'Price clears Call Wall ($' + num(cw, 0) + '), triggering momentum follow-through.',
        },
      ],
    },
    {
      id: 'strat-3',
      title: 'Strategy 3: Breakdown Expansion Below Key Support',
      regime: 'Negative Gamma (-GEX / Below Support)',
      direction: 'SHORT BIAS (SELLING HEADWIND)',
      directionType: 'selling' as const,
      biasTag: 'SHORT BIAS',
      status: s3Active ? 'TRIGGERED' : 'MONITORING',
      isActive: s3Active,
      entryZone:
        pw != null
          ? `$${num(pw, 0)} (Below Put Wall)`
          : flip != null
            ? `$${num(flip, 0)} (Below Flip)`
            : `Below $${num(spotVal, 0)}`,
      target1:
        spotVal != null ? `$${num(spotVal - em, 2)} (-${num(em, 1)} Move)` : 'Downside Pivot',
      target2:
        spotVal != null
          ? `$${num(spotVal - em * 2, 2)} (-${num(em * 2, 1)} Cascade)`
          : 'Major Downside Band',
      stopLoss:
        pw != null
          ? `$${num(pw * 1.01, 2)} (Above Put Wall)`
          : flip != null
            ? `$${num(flip * 1.01, 2)}`
            : 'Above Pivot',
      riskReward: '2.8x',
      condition: `Spot ($${num(spotVal, 0)}) breaches below Put Wall ($${num(pw, 0)}) / Gamma Flip ($${num(flip, 0)}) into negative gamma territory`,
      trade:
        'DIRECTIONAL SHORT: Buy Put options, Bear Put debit spreads, or fade counter-trend bounces to capture downside volatility cascades.',
      mechanic:
        'Dealers are net short gamma. As price falls, dealers are mathematically forced to sell more underlying stock to stay delta-neutral, accelerating selloffs.',
      stages: [
        {
          name: 'Stage 1 · Regime Breach [SHORT TRIGGER]',
          note:
            'Spot falls below Put Wall ($' + num(pw, 0) + ') / Gamma Flip ($' + num(flip, 0) + ').',
        },
        {
          name: 'Stage 2 · Dealer Cascade [FORCED SELLING]',
          note: 'Pro-cyclical dealer selling accelerates downward slippage.',
        },
        {
          name: 'Stage 3 · Target Support [EXIT SHORT]',
          note: 'Downside expansion target: major historical support / lower volatility boundary.',
        },
      ],
    },
  ]
})

/** The single dominant primary active strategy.
 *
 * Priority mirrors microstructureAssessment:
 *   1. Breakdown (s3 / SHORT) — structural break overrides gauge signals
 *   2. Range channel (s1 / MEAN-REVERSION) — positive gamma pinning
 *   3. Buying expansion (s2 / LONG) — charm tailwind / breakout
 */
const primaryStrategy = computed(() => {
  const strats = strategies.value
  // Honour the same priority as microstructureAssessment so the two never contradict.
  if (strats[2].isActive) return strats[2] // s3: structural breakdown wins first
  if (strats[0].isActive) return strats[0] // s1: range channel
  if (strats[1].isActive) return strats[1] // s2: buying / breakout expansion
  // Fallback: no strategy is active — use microstructure tone to pick the most relevant.
  const tone = microstructureAssessment.value?.tone
  if (tone === 'selling') return strats[2]
  if (tone === 'buying') return strats[1]
  return strats[0]
})

const focusStrike = ref<number | null>(null)

/** True when the server is serving a cached snapshot (no live feed available).
 *  Used to surface a visible staleness warning on the chart and cascade panels. */
const isHistoryFallback = computed(
  () => modeResolved.value === 'history_fallback' || modeResolved.value === 'history',
)

/** Changing this key forces PressureDriftChart to remount when the symbol or
 *  charm-data shape changes — avoids SVG geometry sticking between navigations. */
const charmChartKey = computed(
  () => `${symbol.value}_${charmRows.value.length}_${modeResolved.value ?? 'init'}`,
)
</script>

<template>
  <div class="drift-view">
    <!-- Header banner -->
    <header class="drift-head ticked rise">
      <div class="drift-title">
        <span class="label eyebrow"
          ><i aria-hidden="true" class="live-dot" /> CHARM &amp; DEALER HEDGING DYNAMICS</span
        >
        <h1>Charm &amp; Pressure Drift</h1>
        <p>
          Charm (∂Δ/∂t) measures the mechanical daily change in option delta solely due to the
          passage of time. Because dealers run delta-neutral books, decaying OTM options force
          predictable, time-dependent rebalancing flows into the underlying market.
        </p>

        <!-- Quick Ticker Chips -->
        <div class="quick-chips" role="group" aria-label="Quick symbols">
          <span class="label quick-label">QUICK TICKERS:</span>
          <button
            v-for="sym in QUICK_SYMBOLS"
            :key="sym"
            type="button"
            class="chip-btn label"
            :class="{ on: symbol === sym }"
            @click="selectQuickSymbol(sym)"
          >
            {{ sym }}
          </button>
        </div>
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

        <!-- Expiry filter with dropdown -->
        <div class="expiry-controls">
          <div class="expiry-box" role="group" aria-label="Expiry mode">
            <button
              type="button"
              class="expiry-btn label"
              :class="{ on: selectedExpiry === 'all' }"
              :aria-pressed="selectedExpiry === 'all'"
              @click="setExpiry('all')"
            >
              ALL
            </button>
            <button
              type="button"
              class="expiry-btn label"
              :class="{ on: selectedExpiry === 'nearest' }"
              :aria-pressed="selectedExpiry === 'nearest'"
              @click="setExpiry('nearest')"
            >
              NEAREST
            </button>
          </div>

          <div v-if="availableExpiries.length > 0" class="expiry-select-wrap">
            <select
              class="expiry-select label"
              :value="selectedExpiry"
              aria-label="Select exact expiration date"
              @change="onExpirySelectChange"
            >
              <option value="all">ALL EXPIRIES (Composite)</option>
              <option value="nearest">NEAREST EXPIRY</option>
              <option v-for="exp in availableExpiries" :key="exp.expiry" :value="exp.expiry">
                {{ exp.expiry }} ({{ exp.dte }} DTE · {{ exp.contracts }}c)
              </option>
            </select>
          </div>
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

    <!-- Expiry status bar -->
    <div class="expiry-status-bar label">
      <span class="active-exp-badge"
        >ACTIVE EXPIRY: <b>{{ activeExpiryLabel }}</b></span
      >
      <span v-if="chainContext?.snapshot_dte != null" class="dte-note">
        Snapshot DTE: {{ chainContext.snapshot_dte }}d · Selection: {{ chainContext.selection }}
      </span>
      <span v-if="atmIv != null" class="iv-note">ATM IV: {{ (atmIv * 100).toFixed(1) }}%</span>
    </div>

    <!-- KPI summary cards with rich tooltips -->
    <section class="kpi-row">
      <div
        class="kpi tooltip-card"
        :class="{ stale: netGex == null }"
        title="Net Gamma Exposure ($M per 1% move). Positive = Dealers long gamma (Mean-Reversion / Buy Dips, Sell Rallies). Negative = Dealers short gamma (Trending / Cascading Breakouts)."
      >
        <div class="k-head">
          <span class="label k-key">NET GEX</span>
          <span class="info-dot" title="Dollar gamma exposure per 1% move">?</span>
        </div>
        <span class="fig k-val" :class="gexRegime">{{
          netGex != null ? `$${compact(netGex)}M` : '—'
        }}</span>
        <span class="label k-tag" :class="gexRegime">{{ gexRegimeLabel }}</span>
      </div>

      <div
        class="kpi tooltip-card"
        :class="{ stale: netCharmFlow == null }"
        title="Net Charm Flow (shares/day dealers must trade from time decay). Negative = Dealers short decaying puts → BUYING pressure. Positive = Dealers long decaying calls → SELLING pressure."
      >
        <div class="k-head">
          <span class="label k-key">NET CHARM FLOW</span>
          <span class="info-dot" title="Daily delta decay rehedging in shares/day">?</span>
        </div>
        <span class="fig k-val" :class="charmPressure">
          {{ netCharmFlow != null ? `${signed(netCharmFlow, 0)} sh/d` : '—' }}
        </span>
        <span class="label k-tag" :class="charmPressure">{{ charmPressure.toUpperCase() }}</span>
      </div>

      <div
        class="kpi tooltip-card"
        :class="{ stale: callPutRatio == null }"
        title="Ratio of total Put volume / Call volume. Below 0.65 indicates bullish call taker dominance; above 1.0 indicates defensive put positioning."
      >
        <div class="k-head">
          <span class="label k-key">PUT / CALL RATIO</span>
          <span class="info-dot" title="Total Put volume / Call volume">?</span>
        </div>
        <span class="fig k-val">{{ num(callPutRatio) }}</span>
        <span class="label k-tag">VOLUME</span>
      </div>

      <div
        class="kpi tooltip-card"
        :class="{ stale: asof == null }"
        title="Observation timestamp and feed quality mode (LIVE = Real-time WebSocket/Tape, DELAYED/HISTORY = Reference Snapshot)."
      >
        <div class="k-head">
          <span class="label k-key">LAST UPDATE</span>
          <span class="info-dot" title="Feed observation time and sync status">?</span>
        </div>
        <span class="fig k-val">{{ asof ? shortDate(asof) : '—' }}</span>
        <span
          class="label k-tag"
          :class="{
            live: modeResolved === 'live' && !spotStale,
            stale: spotStale,
            refreshing: refreshing && !loading,
          }"
          :title="
            refreshing && !loading
              ? 'Fetching updated data…'
              : spotStale
                ? `Spot source: ${spotSource ?? 'unknown'} — spot may lag the live session`
                : undefined
          "
          >{{ refreshing && !loading ? 'SYNCING…' : dataModeBadge }}</span
        >
      </div>
    </section>

    <!-- Pressure Gauge & Multi-Factor Decomposition -->
    <Panel label="PRESSURE GAUGE &amp; FLOW POSTURE" :meta="pressureVerdict" live>
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
            :aria-valuenow="pressure ? pressure.imbalance : undefined"
            :aria-valuetext="pressure ? pressureLabel : 'Unavailable'"
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

          <!--
            The read: verdict + confidence, then each voting channel's own
            net/gross ratio. "n/a" means that channel abstained (no data or
            below its evidence floor) — it did NOT vote balanced, so it must
            not render as 0. Call/put mix and GEX sign are context, not votes.
          -->
          <div v-if="pressure" class="read-block" data-testid="pressure-read">
            <div class="read-verdict">
              <span class="fig read-verdict-text" :class="pressure.direction">{{ pressure.verdict }}</span>
              <span class="conf-chip label" :class="pressureBand">
                {{ pressureBand.toUpperCase() }} · {{ Math.round(pressure.confidence.score * 100) }}
              </span>
              <span class="conf-chip label" :class="pressureActionable ? 'actionable' : 'hold'">
                {{ pressureActionable ? 'ACTIONABLE' : 'NO TRADE' }}
              </span>
            </div>
            <div class="channel-list">
              <template v-for="row in pressureChannelRows" :key="row.key">
                <span class="label channel-name">{{ row.name }}</span>
                <span class="fig channel-ratio" :class="row.tone">{{ channelText(row.ratio) }}</span>
                <span class="label channel-detail">w {{ row.weight }} · {{ row.detail }}</span>
              </template>
            </div>
            <p class="gauge-note label">
              Context (not votes) · call/put mix {{ channelText(pressure.context.call_put_mix) }} · GEX
              {{ signed(pressure.components.net_gex_m, 1) }}M {{ pressure.context.gex_regime }} —
              {{ pressure.context.follow_through }} · agreement
              {{ Math.round(pressure.confidence.agreement * 100) }}% · evidence
              {{ Math.round(pressure.confidence.evidence * 100) }}% · freshness
              {{ Math.round(pressure.confidence.freshness * 100) }}%
            </p>
            <ul v-if="pressureConflicts.length" class="reason-list conflict label">
              <li v-for="c in pressureConflicts" :key="c.channel">⚠ {{ c.note }} ({{ signed(c.ratio, 2) }})</li>
            </ul>
            <ul v-if="pressureReasons.length" class="reason-list label">
              <li v-for="(r, i) in pressureReasons" :key="i">{{ r }}</li>
            </ul>
          </div>
          <p v-else class="gauge-note label">Pressure unavailable until the chain loads.</p>
        </div>

        <!-- 3-Factor Breakdown Cards -->
        <div v-if="pressure" class="factor-grid">
          <div class="factor-card" :class="charmPressure">
            <div class="factor-head">
              <span class="label">1. CHARM TIME DECAY</span>
              <span class="factor-badge label" :class="charmPressure">{{
                charmPressure.toUpperCase()
              }}</span>
            </div>
            <div class="factor-metric fig" :class="charmPressure">
              {{ signed(pressure.components.net_charm_flow, 0) }} <small>sh/d</small>
            </div>
            <p class="factor-desc">
              {{
                netCharmFlow && netCharmFlow < 0
                  ? 'Dealers short decaying OTM puts → Must BUY stock to unwind hedges (LONG tailwind).'
                  : netCharmFlow && netCharmFlow > 0
                    ? 'Dealers long decaying calls → Must SELL stock to re-neutralize (SHORT headwind).'
                    : 'Time decay flow is balanced between calls and puts.'
              }}
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
              {{
                gexRegime === 'positive'
                  ? 'Long Gamma: Counter-cyclical rehedging compresses volatility (Buy Dips, Sell Rallies).'
                  : gexRegime === 'negative'
                    ? 'Short Gamma: Pro-cyclical rehedging amplifies breakouts & slips (Accelerating Trends).'
                    : 'Gamma exposure neutral near current spot.'
              }}
            </p>
          </div>

          <!--
            Buyer/seller imbalance from side-resolved prints. Call-vs-put volume
            used to sit here captioned "Bullish/Bearish bias" — a bought put and
            a sold put are the same row in that number, so it never measured
            who was pressing. The mix is still shown, as context.
          -->
          <div class="factor-card" :class="pressureChannelRows[1]?.tone">
            <div class="factor-head">
              <span class="label">3. TAPE BUYERS VS SELLERS</span>
              <span class="factor-badge label" :class="pressureChannelRows[1]?.tone">
                {{ pressureChannelRows[1]?.tone === 'na' ? 'ABSTAINS' : (pressureChannelRows[1]?.tone ?? 'n/a').toUpperCase() }}
              </span>
            </div>
            <div class="factor-metric fig" :class="pressureChannelRows[1]?.tone">
              {{ channelText(pressure.channels.tape) }}
              <small v-if="tapeChannel">{{ tapeChannel.n_signed }}/{{ tapeChannel.n_total }} sided</small>
            </div>
            <p class="factor-desc">
              {{
                tapeChannel && tapeChannel.n_total > 0
                  ? `Buy ${compact(tapeChannel.buy_premium)} vs sell ${compact(tapeChannel.sell_premium)} premium on the underlying (buy call / sell put = buying). ${tapeSideMixText}. Call/put mix ${channelText(pressure.context.call_put_mix)} is contract identity, not side.`
                  : 'No prints in the window, so the tape cannot say who is pressing.'
              }}
            </p>
          </div>

          <div class="factor-card" :class="pressureChannelRows[2]?.tone">
            <div class="factor-head">
              <span class="label">4. UNDERLYING VOLUME READ</span>
              <span class="factor-badge label" :class="pressureChannelRows[2]?.tone">
                {{ pressureChannelRows[2]?.tone === 'na' ? 'ABSTAINS' : (pressureChannelRows[2]?.tone ?? 'n/a').toUpperCase() }}
              </span>
            </div>
            <div class="factor-metric fig" :class="pressureChannelRows[2]?.tone">
              {{ channelText(pressure.channels.underlying) }}
              <small v-if="underlyingChannel">rvol {{ underlyingChannel.rvol != null ? underlyingChannel.rvol.toFixed(2) + '×' : 'n/a' }}</small>
            </div>
            <p class="factor-desc">
              {{
                underlyingChannel
                  ? `Closes ${underlyingChannel.ratio > 0.25 ? 'near the highs' : underlyingChannel.ratio < -0.25 ? 'near the lows' : 'mid-range'} on volume over the last ${underlyingChannel.bars_used} × ${underlyingChannel.timeframe ?? '?'} bars (${signed(underlyingChannel.close_change_pct ?? 0, 2)}%). ${underlyingChannel.note}`
                  : 'No underlying bars were supplied, so the stock itself cannot corroborate the options read.'
              }}
            </p>
          </div>
        </div>

        <!-- Microstructure Interpretation Banner with Directional Action -->
        <div
          v-if="microstructureAssessment"
          class="assessment-box"
          :class="microstructureAssessment.tone"
        >
          <div class="assessment-header">
            <span class="label assess-tag">MICROSTRUCTURE IMPLICATION</span>
            <span class="assess-title">{{ microstructureAssessment.title }}</span>
            <span class="badge assess-dir-badge label" :class="microstructureAssessment.tone">
              {{ microstructureAssessment.direction }}
            </span>
          </div>
          <p class="assess-body">{{ microstructureAssessment.body }}</p>
          <div class="assess-footer label">
            <b>Actionable Strategy:</b> {{ microstructureAssessment.implication }}
          </div>
        </div>
      </div>
    </Panel>

    <!-- Step-by-Step Dealer Flow Cascade Diagram -->
    <Panel
      label="DEALER REBALANCING FLOW CASCADE &amp; MICROSTRUCTURE MECHANISM"
      meta="STEP-BY-STEP FLOWCHART"
      live
    >
      <!-- Snapshot data notice -->
      <div v-if="isHistoryFallback" class="snapshot-notice label">
        <span class="snap-icon">⏸</span>
        SNAPSHOT DATA — live feed unavailable for {{ symbol }}. Values reflect the last cached chain
        ({{ asof ? shortDate(asof) : '—' }}). Cascade mechanics are correct for the snapshot; they
        update when a live feed reconnects.
      </div>
      <div class="flow-cascade-container">
        <div class="cascade-step">
          <div class="step-num label">STEP 1</div>
          <div class="step-title">Time &amp; Price State</div>
          <div class="step-metric fig">Spot: ${{ num(spot) }}</div>
          <p class="step-desc">
            Time advances (Δt = 1d), decaying extrinsic value across all open contracts.
          </p>
        </div>

        <div class="cascade-arrow">➔</div>

        <div class="cascade-step">
          <div class="step-num label">STEP 2</div>
          <div class="step-title">Greeks Repricing</div>
          <div class="step-metric fig">Charm ∂Δ/∂t</div>
          <p class="step-desc">
            OTM put delta shrinks toward 0; OTM call delta shrinks toward 0. Gamma profile adjusts.
          </p>
        </div>

        <div class="cascade-arrow">➔</div>

        <div class="cascade-step" :class="charmPressure">
          <div class="step-num label">STEP 3</div>
          <div class="step-title">Dealer Inventory</div>
          <div class="step-metric fig" :class="charmPressure">
            {{
              netCharmFlow && netCharmFlow < 0
                ? 'DEALERS SHORT PUTS'
                : netCharmFlow && netCharmFlow > 0
                  ? 'DEALERS LONG CALLS'
                  : 'BALANCED BOOK'
            }}
          </div>
          <p class="step-desc">
            Dealer book delta drifts off zero; hedge ratio requires mechanical adjustment.
          </p>
        </div>

        <div class="cascade-arrow">➔</div>

        <div class="cascade-step highlight" :class="charmPressure">
          <div class="step-num label">STEP 4 · FORCED FLOW</div>
          <div class="step-title" :class="charmPressure">
            {{
              netCharmFlow && netCharmFlow < 0
                ? '▲ DEALERS BUY SHARES'
                : netCharmFlow && netCharmFlow > 0
                  ? '▼ DEALERS SELL SHARES'
                  : 'NEUTRAL REBALANCE'
            }}
          </div>
          <div class="step-metric fig" :class="charmPressure">
            {{ netCharmFlow != null ? `${signed(netCharmFlow, 0)} sh/d` : '—' }}
          </div>
          <p class="step-desc">
            {{
              netCharmFlow && netCharmFlow < 0
                ? 'LONG TAILWIND: Mandatory buying pressure lifting price off supports.'
                : netCharmFlow && netCharmFlow > 0
                  ? 'SHORT HEADWIND: Mandatory selling supply capping price rallies.'
                  : 'Neutral order flow equilibrium across strikes.'
            }}
          </p>
        </div>

        <div class="cascade-arrow">➔</div>

        <div class="cascade-step">
          <div class="step-num label">STEP 5</div>
          <div class="step-title">Structural Walls</div>
          <div class="step-metric fig">
            PW: ${{ num(putWall, 0) }} · CW: ${{ num(callWall, 0) }}
          </div>
          <p class="step-desc">
            Put Wall acts as bounce floor; Call Wall acts as overhead supply ceiling.
          </p>
        </div>
      </div>
    </Panel>

    <!-- Charm flow by strike chart -->
    <Panel
      :label="`${symbol} · CHARM FLOW BY STRIKE`"
      :meta="
        charmSummary
          ? `${charmSummary.contracts_measured} charmed · ${charmSummary.contracts_skipped} skipped`
          : 'NO CHAIN'
      "
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
        <!--
          Chain arrived but nothing in it was measurable. Every strike would plot
          as a legitimate-looking 0, so name the cause instead of drawing a flat
          axis the reader would misread as "balanced".
        -->
        <div v-else-if="charmAllSkipped" class="placeholder">
          <span class="ph-msg">
            Charm not measurable for {{ symbol }} — no contract in the chain met the model's inputs.
          </span>
          <span v-if="charmSkipDetail" class="ph-sub label">{{ charmSkipDetail }}</span>
          <span v-if="charmSkipHint" class="ph-sub label">{{ charmSkipHint }}</span>
        </div>
        <PressureDriftChart
          v-else
          :key="charmChartKey"
          :symbol="symbol"
          :rows="charmRows"
          :spot="spot"
          :call-wall="callWall"
          :put-wall="putWall"
          :gamma-flip="gammaFlip"
          :height="440"
        />
        <div v-if="isHistoryFallback && hasChain" class="snapshot-chart-notice label">
          ⏸ Chart shows cached snapshot ({{ asof ? shortDate(asof) : '—' }}). Bar heights will
          refresh when a live chain reconnects.
        </div>
        <!-- Partial coverage: the chart is real but incomplete. Say which strikes are absent. -->
        <div
          v-if="!loading && !error && hasChain && !charmAllSkipped && charmSkipDetail"
          class="snapshot-chart-notice label"
        >
          ⚠ {{ charmSummary?.contracts_skipped }} of
          {{ (charmSummary?.contracts_measured ?? 0) + (charmSummary?.contracts_skipped ?? 0) }}
          contracts excluded — {{ charmSkipDetail }}. Those strikes are absent from the chart, not
          flat.
        </div>
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

    <!-- Actionable Quantitative Strategies & Directional Trade Ticket -->
    <Panel
      label="ACTIONABLE QUANTITATIVE STRATEGIES &amp; TRADE EXECUTION"
      meta="LIVE TRADE PLAYBOOK"
      live
    >
      <template #action>
        <div class="mini-segment" role="group" aria-label="Strategy view mode">
          <button
            type="button"
            class="label"
            :class="{ on: strategyViewMode === 'primary' }"
            @click="strategyViewMode = 'primary'"
          >
            PRIMARY LIVE SETUP
          </button>
          <button
            type="button"
            class="label"
            :class="{ on: strategyViewMode === 'all' }"
            @click="strategyViewMode = 'all'"
          >
            ALL PLAYBOOK REGIMES
          </button>
        </div>
      </template>

      <!-- Primary Actionable Trade Ticket (When 'primary' view is active) -->
      <div v-if="strategyViewMode === 'primary' && primaryStrategy" class="primary-ticket-wrap">
        <div class="primary-ticket" :class="primaryStrategy.directionType">
          <div class="ticket-head">
            <div class="ticket-title-group">
              <span class="badge primary-tag label">PRIMARY ACTIONABLE SETUP</span>
              <span class="ticket-title">{{ primaryStrategy.title }}</span>
            </div>
            <div class="ticket-badges">
              <span class="badge dir-badge label" :class="primaryStrategy.directionType">
                {{ primaryStrategy.biasTag }}
              </span>
              <span class="strat-status label" :class="primaryStrategy.status.toLowerCase()">
                {{ primaryStrategy.status }}
              </span>
            </div>
          </div>

          <!-- Trade Execution Level Grid -->
          <div class="ticket-levels-grid">
            <div class="level-box">
              <span class="label lvl-label">ENTRY REFERENCE</span>
              <span class="fig lvl-val highlight">{{ primaryStrategy.entryZone }}</span>
            </div>
            <div class="level-box">
              <span class="label lvl-label">TARGET 1</span>
              <span class="fig lvl-val call-hi">{{ primaryStrategy.target1 }}</span>
            </div>
            <div class="level-box">
              <span class="label lvl-label">TARGET 2 (WALL)</span>
              <span class="fig lvl-val call-hi">{{ primaryStrategy.target2 }}</span>
            </div>
            <div class="level-box">
              <span class="label lvl-label">STOP / INVALIDATION</span>
              <span class="fig lvl-val put-hi">{{ primaryStrategy.stopLoss }}</span>
            </div>
            <div class="level-box">
              <span class="label lvl-label">RISK / REWARD</span>
              <span class="fig lvl-val phosphor">{{ primaryStrategy.riskReward }}</span>
            </div>
          </div>

          <!-- Trade Playbook Instruction -->
          <div class="ticket-instruction">
            <span class="label inst-label">Directional Execution:</span>
            <span class="inst-text" :class="primaryStrategy.directionType">{{
              primaryStrategy.trade
            }}</span>
          </div>

          <!-- Lifecycle Stages Breakdown with Active Indicator -->
          <div class="strat-stages-wrap">
            <span class="strat-label label">Lifecycle Stages &amp; Flow Direction:</span>
            <div class="strat-stages-list">
              <div
                v-for="(stg, idx) in primaryStrategy.stages"
                :key="stg.name"
                class="stage-item"
                :class="{ 'is-first': idx === 0 }"
              >
                <span class="stage-name label">{{ stg.name }}</span>
                <span class="stage-note">{{ stg.note }}</span>
              </div>
            </div>
          </div>

          <div class="ticket-mechanic">
            <span class="label mech-label">DEALER INVENTORY MECHANIC:</span>
            <span class="mech-text">{{ primaryStrategy.mechanic }}</span>
          </div>
        </div>

        <!-- Real-time Level Watch & If-Then Trigger Board -->
        <div class="trigger-matrix-board">
          <div class="matrix-header">
            <span class="label matrix-title">IF / THEN LEVEL WATCH &amp; EXECUTION TRIGGERS</span>
            <span class="label current-spot-badge">
              SPOT: <b>${{ num(spot, 2) }}</b> · REGIME: <b>{{ gexRegimeLabel }}</b> · CHARM:
              <b>{{ charmPressure.toUpperCase() }}</b>
            </span>
          </div>
          <div class="matrix-grid">
            <!-- Bullish Breakout Trigger -->
            <div
              class="matrix-card bullish"
              :class="{ active: spot != null && callWall != null && spot >= callWall }"
            >
              <div class="m-head">
                <span class="m-dir label call">▲ ABOVE CALL WALL (${{ num(callWall, 0) }})</span>
                <span
                  class="m-badge label"
                  :class="
                    spot != null && callWall != null && spot >= callWall ? 'active' : 'pending'
                  "
                >
                  {{
                    spot != null && callWall != null && spot >= callWall
                      ? 'TRIGGERED / EXPANDING'
                      : 'WATCH LEVEL'
                  }}
                </span>
              </div>
              <div class="m-rule">
                <b>IF Spot &gt; ${{ num(callWall, 0) }}:</b> Dealer call gamma flips / resistance
                breaks. Buy Long Calls / Momentum Continuation.
              </div>
              <div class="m-levels label">
                Target: ${{ num(spot != null ? spot + (expectedMove ?? 5) : 0, 1) }} · Invalidation:
                Below ${{ num(callWall, 0) }}
              </div>
            </div>

            <!-- In-Channel Mean-Reversion Trigger -->
            <div
              class="matrix-card channel"
              :class="{
                active:
                  spot != null &&
                  putWall != null &&
                  callWall != null &&
                  spot >= putWall &&
                  spot <= callWall,
              }"
            >
              <div class="m-head">
                <span class="m-dir label phosphor"
                  >↔ IN CHANNEL [${{ num(putWall, 0) }} — ${{ num(callWall, 0) }}]</span
                >
                <span
                  class="m-badge label"
                  :class="
                    spot != null &&
                    putWall != null &&
                    callWall != null &&
                    spot >= putWall &&
                    spot <= callWall
                      ? 'active'
                      : 'pending'
                  "
                >
                  {{
                    spot != null &&
                    putWall != null &&
                    callWall != null &&
                    spot >= putWall &&
                    spot <= callWall
                      ? 'ACTIVE IN CHANNEL'
                      : 'WATCH CHANNEL'
                  }}
                </span>
              </div>
              <div class="m-rule">
                <b>IF ${{ num(putWall, 0) }} &le; Spot &le; ${{ num(callWall, 0) }}:</b>
                {{
                  gexRegime === 'positive'
                    ? `Long Gamma dampening. BUY near $${num(putWall, 0)} Put Wall, SELL near $${num(callWall, 0)} Call Wall.`
                    : `Short Gamma channel — use caution. Range boundaries are less reliable; pro-cyclical hedging can accelerate breakouts in either direction.`
                }}
              </div>
              <div class="m-levels label">
                Equilibrium: ${{
                  num(
                    spot != null && putWall != null && callWall != null
                      ? (putWall + callWall) / 2
                      : 0,
                    1,
                  )
                }}
                · Stop: Below ${{ num(putWall, 0) }}
              </div>
            </div>

            <!-- Bearish Breakdown Trigger -->
            <div
              class="matrix-card bearish"
              :class="{ active: spot != null && putWall != null && spot < putWall }"
            >
              <div class="m-head">
                <span class="m-dir label put">▼ BELOW PUT WALL (${{ num(putWall, 0) }})</span>
                <span
                  class="m-badge label"
                  :class="spot != null && putWall != null && spot < putWall ? 'active' : 'pending'"
                >
                  {{
                    spot != null && putWall != null && spot < putWall
                      ? 'TRIGGERED / CASCADING'
                      : 'WATCH LEVEL'
                  }}
                </span>
              </div>
              <div class="m-rule">
                <b>IF Spot &lt; ${{ num(putWall, 0) }}:</b> Dealer put gamma support breaks. Buy
                Long Puts / Bear Put Spreads for cascading downside.
              </div>
              <div class="m-levels label">
                Target: ${{ num(spot != null ? spot - (expectedMove ?? 5) : 0, 1) }} · Invalidation:
                Reclaim above ${{ num(putWall, 0) }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- All Playbook Regimes Grid (When 'all' view is active) -->
      <div v-else class="strategies-grid">
        <div
          v-for="strat in strategies"
          :key="strat.id"
          class="strategy-card"
          :class="[
            strat.directionType,
            { active: strat.status === 'ACTIVE' || strat.status === 'TRIGGERED' },
          ]"
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

          <div class="strat-bias-bar">
            <span class="badge dir-badge label" :class="strat.directionType">
              {{ strat.biasTag }}
            </span>
            <span class="strat-regime label">{{ strat.regime }}</span>
          </div>

          <div class="strat-section">
            <span class="strat-label label">Condition:</span>
            <span class="strat-text">{{ strat.condition }}</span>
          </div>

          <div class="strat-section">
            <span class="strat-label label">Directional Execution:</span>
            <span class="strat-text highlight" :class="strat.directionType">{{ strat.trade }}</span>
          </div>

          <!-- Execution Stages (Stage 1 -> Stage 2 -> Stage 3) -->
          <div class="strat-stages-wrap">
            <span class="strat-label label">Lifecycle Stages &amp; Flow Direction:</span>
            <div class="strat-stages-list">
              <div v-for="stg in strat.stages" :key="stg.name" class="stage-item">
                <span class="stage-name label">{{ stg.name }}</span>
                <span class="stage-note">{{ stg.note }}</span>
              </div>
            </div>
          </div>

          <div class="strat-section">
            <span class="strat-label label">Dealer Hedging Mechanic:</span>
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
          <div class="table-search-box">
            <input
              v-model="tableSearch"
              type="text"
              class="table-search-input label"
              placeholder="Filter strike…"
              spellcheck="false"
            />
          </div>

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
              :class="{ on: tableFilter === 'nearest' }"
              title="10 closest strikes below and above spot"
              @click="tableFilter = 'nearest'"
            >
              NEAREST (±10)
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
            <button
              type="button"
              class="label"
              :class="{ on: tableFilter === 'walls' }"
              @click="tableFilter = 'walls'"
            >
              WALLS &amp; FLIP
            </button>
          </div>

          <button
            type="button"
            class="export-btn label"
            title="Export strike table to CSV"
            @click="exportCsv"
          >
            EXPORT CSV
          </button>
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
              <th colspan="6" class="group-call">CALL OPTIONS (DEALER LONG INVENTORY)</th>
              <th colspan="6" class="group-put">PUT OPTIONS (DEALER SHORT INVENTORY)</th>
              <th colspan="2" class="group-net">DEALER NET FLOW</th>
            </tr>
            <!-- Individual Column Headers (Sortable) -->
            <tr class="header-cols">
              <th class="num strike-col sortable" @click="toggleSort('strike')">
                STRIKE {{ sortCol === 'strike' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>
              <th class="num moneyness-col sortable" @click="toggleSort('moneyness')">
                MONEYNESS {{ sortCol === 'moneyness' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>

              <!-- Call columns -->
              <th
                class="num call-head sortable"
                title="Call Open Interest"
                @click="toggleSort('call_oi')"
              >
                CALL OI {{ sortCol === 'call_oi' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>
              <th
                class="num call-head sortable"
                title="Call Volume Today"
                @click="toggleSort('call_vol')"
              >
                CALL VOL {{ sortCol === 'call_vol' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>
              <th
                class="num call-head sortable"
                title="Implied Volatility"
                @click="toggleSort('call_iv')"
              >
                IV {{ sortCol === 'call_iv' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>
              <th
                class="num call-head sortable"
                title="Black-Scholes Delta (∂V/∂S)"
                @click="toggleSort('call_delta')"
              >
                Δ (DELTA) {{ sortCol === 'call_delta' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>
              <th
                class="num call-head sortable"
                title="Black-Scholes Gamma (∂²V/∂S²)"
                @click="toggleSort('call_gamma')"
              >
                Γ (GAMMA) {{ sortCol === 'call_gamma' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>
              <th
                class="num call-head sortable"
                title="Daily Charm (∂Δ/∂t per day)"
                @click="toggleSort('call_charm')"
              >
                CHARM/d {{ sortCol === 'call_charm' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>

              <!-- Put columns -->
              <th
                class="num put-head sortable"
                title="Put Open Interest"
                @click="toggleSort('put_oi')"
              >
                PUT OI {{ sortCol === 'put_oi' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>
              <th
                class="num put-head sortable"
                title="Put Volume Today"
                @click="toggleSort('put_vol')"
              >
                PUT VOL {{ sortCol === 'put_vol' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>
              <th
                class="num put-head sortable"
                title="Implied Volatility"
                @click="toggleSort('put_iv')"
              >
                IV {{ sortCol === 'put_iv' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>
              <th
                class="num put-head sortable"
                title="Black-Scholes Delta (∂V/∂S)"
                @click="toggleSort('put_delta')"
              >
                Δ (DELTA) {{ sortCol === 'put_delta' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>
              <th
                class="num put-head sortable"
                title="Black-Scholes Gamma (∂²V/∂S²)"
                @click="toggleSort('put_gamma')"
              >
                Γ (GAMMA) {{ sortCol === 'put_gamma' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>
              <th
                class="num put-head sortable"
                title="Daily Charm (∂Δ/∂t per day)"
                @click="toggleSort('put_charm')"
              >
                CHARM/d {{ sortCol === 'put_charm' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>

              <!-- Net flow columns -->
              <th
                class="num net-head sortable"
                title="Net shares/day dealers must trade to stay delta-neutral"
                @click="toggleSort('net_charm')"
              >
                NET CHARM FLOW {{ sortCol === 'net_charm' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>
              <th
                class="num net-head sortable"
                title="Net Dollar Gamma Exposure per 1% move ($M)"
                @click="toggleSort('gex')"
              >
                NET GEX $M {{ sortCol === 'gex' ? (sortAsc ? '▲' : '▼') : '' }}
              </th>
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
                {{
                  row.distPct != null
                    ? row.distPct >= 0
                      ? `+${row.distPct.toFixed(1)}%`
                      : `${row.distPct.toFixed(1)}%`
                    : '—'
                }}
              </td>

              <!-- Call Side -->
              <td class="num call-oi">
                {{ row.call?.open_interest != null ? compact(row.call.open_interest) : '—' }}
              </td>
              <td class="num call-vol">
                {{ row.call?.volume != null ? compact(row.call.volume) : '—' }}
              </td>
              <td class="num">
                {{ row.call?.iv != null ? `${(row.call.iv * 100).toFixed(0)}%` : '—' }}
              </td>
              <td class="num call-delta">
                {{ row.call?.delta != null ? num(row.call.delta, 3) : '—' }}
              </td>
              <td class="num call-gamma">
                {{ row.call?.gamma != null ? num(row.call.gamma, 4) : '—' }}
              </td>
              <td class="num call-charm">
                {{ row.call?.charm_per_day != null ? signed(row.call.charm_per_day, 5) : '—' }}
              </td>

              <!-- Put Side -->
              <td class="num put-oi">
                {{ row.put?.open_interest != null ? compact(row.put.open_interest) : '—' }}
              </td>
              <td class="num put-vol">
                {{ row.put?.volume != null ? compact(row.put.volume) : '—' }}
              </td>
              <td class="num">
                {{ row.put?.iv != null ? `${(row.put.iv * 100).toFixed(0)}%` : '—' }}
              </td>
              <td class="num put-delta">
                {{ row.put?.delta != null ? num(row.put.delta, 3) : '—' }}
              </td>
              <td class="num put-gamma">
                {{ row.put?.gamma != null ? num(row.put.gamma, 4) : '—' }}
              </td>
              <td class="num put-charm">
                {{ row.put?.charm_per_day != null ? signed(row.put.charm_per_day, 5) : '—' }}
              </td>

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
      Feed age {{ Math.round(freshness.feed_age_seconds) }}s · activity basis
      {{ payload.provider?.activity_basis ?? 'unavailable' }} · charm source
      {{ charmSummary?.source ?? 'unavailable' }}
    </p>
    <p v-if="pressure" class="freshness-note label">{{ pressure.convention_note }}</p>
  </div>
</template>

<style scoped>
/* Surface glass token: var(--glass-surface-hi) */
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

.drift-title {
  min-width: 0;
}
.eyebrow {
  color: var(--phosphor);
}

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

.quick-chips {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: var(--s3);
  flex-wrap: wrap;
}
.quick-label {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  margin-right: 4px;
}
.chip-btn {
  padding: 2px 7px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  background: var(--panel);
  color: var(--ink-dim);
  font-size: var(--t-nano);
  font-weight: 700;
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}
.chip-btn:hover {
  color: var(--ink);
  background: var(--panel-hi);
  border-color: var(--rule-hi);
}
.chip-btn.on {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border-color: var(--phosphor-dim);
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
  color: var(--ink-faint);
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

.range-box,
.preset-box {
  display: flex;
  gap: 2px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.range-btn,
.expiry-btn,
.preset-btn {
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
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out);
}
.range-btn:hover,
.expiry-btn:hover,
.preset-btn:hover {
  color: var(--ink);
  background: var(--panel-hi);
}
.range-btn.on,
.expiry-btn.on,
.preset-btn.on {
  color: var(--phosphor);
  background: var(--phosphor-wash);
}

.expiry-controls {
  display: flex;
  gap: 4px;
  align-items: center;
}
.expiry-box {
  display: flex;
  gap: 2px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.expiry-select-wrap {
  display: inline-flex;
}
.expiry-select {
  padding: 3px 8px;
  color: var(--ink);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  cursor: pointer;
}
.expiry-select:focus {
  outline: none;
  border-color: var(--phosphor-dim);
}

.expiry-status-bar {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  background: var(--panel);
  color: var(--ink-dim);
  font-size: var(--t-micro);
}
.active-exp-badge {
  color: var(--ink);
}
.active-exp-badge b {
  color: var(--phosphor);
}
.dte-note {
  color: var(--ink-faint);
}
.iv-note {
  color: var(--call-hi);
  margin-left: auto;
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
.kpi.stale .k-val {
  color: var(--ink-faint);
}
.k-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.k-key {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
}
.info-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--panel-hi);
  color: var(--ink-faint);
  font-size: var(--t-nano);
  font-weight: 700;
  cursor: help;
}
.k-val {
  color: var(--ink);
  font-family: var(--font-data);
  font-size: var(--t-body);
  font-weight: 600;
}
.k-val.positive {
  color: var(--call-hi);
}
.k-val.negative {
  color: var(--put-hi);
}
.k-val.neutral {
  color: var(--ink-dim);
}
.k-val.selling {
  color: var(--put-hi);
}
.k-val.buying {
  color: var(--call-hi);
}
.k-val.balanced {
  color: var(--ink-dim);
}
.k-tag {
  align-self: flex-start;
  padding: 1px 5px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  color: var(--ink-dim);
}
.k-tag.positive {
  color: var(--call-hi);
  border-color: var(--call-dim);
}
.k-tag.negative {
  color: var(--put-hi);
  border-color: var(--put-dim);
}
.k-tag.selling {
  color: var(--put-hi);
  border-color: var(--put-dim);
  background: var(--put-wash);
}
.k-tag.buying {
  color: var(--call-hi);
  border-color: var(--call-dim);
  background: var(--call-wash);
}
.k-tag.live {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.k-tag.stale {
  color: var(--warn);
  border-color: var(--rule);
  background: var(--warn-wash);
}

.k-tag.refreshing {
  color: var(--phosphor-dim);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
  opacity: 0.85;
  animation: blink-tag 1.2s ease-in-out infinite;
}

@keyframes blink-tag {
  0%,
  100% {
    opacity: 0.85;
  }
  50% {
    opacity: 0.5;
  }
}

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
.gauge-score.selling {
  color: var(--put-hi);
}
.gauge-score.buying {
  color: var(--call-hi);
}
.gauge-score.balanced {
  color: var(--ink-dim);
}

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
.zone-sell-heavy {
  flex: 25;
  background: var(--put);
  opacity: 0.65;
}
.zone-sell-mod {
  flex: 15;
  background: var(--put);
  opacity: 0.35;
}
.zone-neutral {
  flex: 20;
  background: var(--surface-base);
  opacity: 0.4;
}
.zone-buy-mod {
  flex: 15;
  background: var(--call);
  opacity: 0.35;
}
.zone-buy-heavy {
  flex: 25;
  background: var(--call);
  opacity: 0.65;
}

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
.gauge-needle.selling {
  background: var(--put-hi);
}
.gauge-needle.buying {
  background: var(--call-hi);
}
.gauge-needle.balanced {
  background: var(--ink);
}

.gauge-labels {
  display: flex;
  justify-content: space-between;
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.05em;
  font-weight: 600;
}
.gauge-labels .sell {
  color: var(--put-hi);
}
.gauge-labels .buy {
  color: var(--call-hi);
}
.gauge-labels .neutral {
  color: var(--ink-dim);
}

.gauge-note {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.03em;
}

/* Pressure read: verdict, confidence, channel table, reasons */
.read-block {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  margin-top: var(--s2);
}
.read-verdict {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}
.read-verdict-text {
  font-weight: 700;
  letter-spacing: 0.04em;
}
.read-verdict-text.buying {
  color: var(--call-hi);
}
.read-verdict-text.selling {
  color: var(--put-hi);
}
.read-verdict-text.balanced {
  color: var(--ink-dim);
}
.conf-chip {
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid currentColor;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
.conf-chip.high,
.conf-chip.actionable {
  color: var(--call-hi);
}
.conf-chip.medium {
  color: var(--ink);
}
.conf-chip.low,
.conf-chip.unmeasurable,
.conf-chip.hold {
  color: var(--put-hi);
}
.channel-list {
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 2px var(--s3);
  align-items: baseline;
}
.channel-name {
  color: var(--ink-dim);
}
.channel-ratio {
  font-weight: 700;
}
.channel-ratio.buying {
  color: var(--call-hi);
}
.channel-ratio.selling {
  color: var(--put-hi);
}
.channel-ratio.balanced,
.channel-ratio.na {
  color: var(--ink-dim);
}
.channel-detail {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-micro);
}
.reason-list {
  margin: 0;
  padding-left: 1.1em;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  line-height: 1.5;
}
.reason-list.conflict {
  color: var(--put-hi);
}
.factor-card.na {
  opacity: 0.75;
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
.factor-card.buying {
  border-left: 2px solid var(--call);
}
.factor-card.selling {
  border-left: 2px solid var(--put);
}
.factor-card.positive {
  border-left: 2px solid var(--call);
}
.factor-card.negative {
  border-left: 2px solid var(--put);
}

.factor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.factor-badge {
  padding: 1px 5px;
  border-radius: 2px;
  font-size: var(--t-nano);
  font-weight: 700;
  border: var(--hair) solid var(--rule);
}
.factor-badge.buying,
.factor-badge.positive {
  color: var(--call-hi);
  border-color: var(--call-dim);
  background: var(--call-wash);
}
.factor-badge.selling,
.factor-badge.negative {
  color: var(--put-hi);
  border-color: var(--put-dim);
  background: var(--put-wash);
}

.factor-metric {
  font-size: var(--t-display);
  font-weight: 700;
  color: var(--ink);
}
.factor-metric.buying,
.factor-metric.positive {
  color: var(--call-hi);
}
.factor-metric.selling,
.factor-metric.negative {
  color: var(--put-hi);
}
.factor-metric small {
  font-size: var(--t-micro);
  color: var(--ink-dim);
}

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
.assessment-box.buying {
  border-left: 3px solid var(--call-hi);
}
.assessment-box.selling {
  border-left: 3px solid var(--put-hi);
}
.assessment-box.balanced {
  border-left: 3px solid var(--phosphor);
}

.assessment-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.assess-tag {
  color: var(--ink-faint);
  font-size: var(--t-nano);
}
.assess-title {
  font-size: var(--t-body);
  font-weight: 700;
  color: var(--ink);
}
.assess-dir-badge {
  margin-left: auto;
}
.assess-dir-badge.buying {
  color: var(--call-hi);
  border-color: var(--call-dim);
  background: var(--call-wash);
}
.assess-dir-badge.selling {
  color: var(--put-hi);
  border-color: var(--put-dim);
  background: var(--put-wash);
}
.assess-dir-badge.balanced {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
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
.assess-footer b {
  color: var(--phosphor);
}

/* Flow Cascade Diagram */
.flow-cascade-container {
  display: flex;
  align-items: stretch;
  gap: var(--s2);
  overflow-x: auto;
  padding: var(--s2) 0;
}

.cascade-step {
  flex: 1 1 0;
  min-width: 170px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--s3);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--panel);
}
.cascade-step.highlight {
  border-color: var(--phosphor-dim);
  background: var(--surface-base);
}
.cascade-step.buying {
  border-left: 3px solid var(--call-hi);
}
.cascade-step.selling {
  border-left: 3px solid var(--put-hi);
}

.step-num {
  font-size: var(--t-nano);
  font-weight: 700;
  color: var(--ink-faint);
  letter-spacing: 0.06em;
}
.step-title {
  font-size: var(--t-micro);
  font-weight: 700;
  color: var(--ink);
}
.step-title.buying {
  color: var(--call-hi);
}
.step-title.selling {
  color: var(--put-hi);
}

.step-metric {
  font-size: var(--t-micro);
  font-weight: 600;
  color: var(--ink-soft);
}
.step-metric.buying {
  color: var(--call-hi);
}
.step-metric.selling {
  color: var(--put-hi);
}

.step-desc {
  font-size: 10px;
  color: var(--ink-faint);
  line-height: 1.4;
  margin: 0;
}

.cascade-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-faint);
  font-size: 14px;
  font-weight: 700;
  padding: 0 2px;
}

/* Primary Trade Ticket */
.primary-ticket-wrap {
  display: flex;
  flex-direction: column;
}
.primary-ticket {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  background: var(--surface-base);
}
.primary-ticket.buying {
  border-left: 4px solid var(--call-hi);
}
.primary-ticket.selling {
  border-left: 4px solid var(--put-hi);
}
.primary-ticket.range {
  border-left: 4px solid var(--phosphor);
}

.ticket-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.ticket-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.primary-tag {
  background: var(--phosphor-wash);
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  font-size: var(--t-nano);
}
.ticket-title {
  font-size: var(--t-display);
  font-weight: 700;
  color: var(--ink);
}
.ticket-badges {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ticket-levels-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: var(--s2);
}
.level-box {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  background: var(--panel);
}
.lvl-label {
  font-size: var(--t-nano);
  color: var(--ink-faint);
  letter-spacing: 0.05em;
}
.lvl-val {
  font-size: var(--t-body);
  font-weight: 700;
}
.lvl-val.highlight {
  color: var(--ink);
}
.lvl-val.call-hi {
  color: var(--call-hi);
}
.lvl-val.put-hi {
  color: var(--put-hi);
}
.lvl-val.phosphor {
  color: var(--phosphor);
}

.ticket-instruction {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: var(--s3);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  background: var(--void);
}
.inst-label {
  font-size: var(--t-nano);
  font-weight: 700;
  color: var(--ink-faint);
}
.inst-text {
  font-size: var(--t-body);
  font-weight: 600;
  line-height: 1.45;
}
.inst-text.buying {
  color: var(--call-hi);
}
.inst-text.selling {
  color: var(--put-hi);
}
.inst-text.range {
  color: var(--ink);
}

.ticket-mechanic {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: var(--s2);
  border-top: var(--hair) solid var(--rule-faint);
}
.mech-label {
  font-size: var(--t-nano);
  color: var(--ink-faint);
}
.mech-text {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  line-height: 1.4;
}

/* Strategies Grid */
.strategies-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
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
.strategy-card.buying {
  border-top: 2px solid var(--call);
}
.strategy-card.selling {
  border-top: 2px solid var(--put);
}
.strategy-card.range {
  border-top: 2px solid var(--phosphor);
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
  font-size: var(--t-nano);
  font-weight: 700;
  border: var(--hair) solid var(--rule);
}
.strat-status.active {
  color: var(--call-hi);
  border-color: var(--call-dim);
  background: var(--call-wash);
}
.strat-status.triggered {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}
.strat-status.monitoring {
  color: var(--ink-faint);
}

.strat-bias-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.dir-badge {
  font-size: var(--t-nano);
  font-weight: 700;
}
.dir-badge.buying {
  color: var(--call-hi);
  border-color: var(--call-dim);
  background: var(--call-wash);
}
.dir-badge.selling {
  color: var(--put-hi);
  border-color: var(--put-dim);
  background: var(--put-wash);
}
.dir-badge.range {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.strat-regime {
  color: var(--ink-faint);
  font-size: 10px;
}

.strat-section {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.strat-label {
  color: var(--ink-faint);
  font-size: var(--t-nano);
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
.strat-text.highlight.buying {
  color: var(--call-hi);
}
.strat-text.highlight.selling {
  color: var(--put-hi);
}
.strat-text.note {
  color: var(--ink-faint);
  font-style: italic;
}

.strat-stages-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
}
.strat-stages-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stage-item {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.stage-item.is-first .stage-name {
  color: var(--phosphor);
}
.stage-name {
  color: var(--ink-soft);
  font-size: var(--t-nano);
  font-weight: 700;
}
.stage-note {
  color: var(--ink-dim);
  font-size: 10px;
  line-height: 1.35;
}

/* Real-time Level Watch & If-Then Trigger Board */
.trigger-matrix-board {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  margin-top: var(--s3);
  padding-top: var(--s3);
  border-top: var(--hair) solid var(--rule);
}
.matrix-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  flex-wrap: wrap;
}
.matrix-title {
  color: var(--ink-faint);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
}
.current-spot-badge {
  color: var(--ink-dim);
  font-size: var(--t-nano);
}
.current-spot-badge b {
  color: var(--ink);
}
.matrix-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--s3);
}
.matrix-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--s3);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  background: var(--surface-base);
  transition:
    border-color var(--dur-fast),
    background var(--dur-fast);
}
.matrix-card.active {
  border-color: var(--phosphor);
  background: var(--panel-hi);
}
.matrix-card.bullish {
  border-left: 3px solid var(--call);
}
.matrix-card.channel {
  border-left: 3px solid var(--phosphor);
}
.matrix-card.bearish {
  border-left: 3px solid var(--put);
}

.m-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.m-dir {
  font-weight: 700;
  font-size: var(--t-nano);
  letter-spacing: 0.04em;
}
.m-dir.call {
  color: var(--call-hi);
}
.m-dir.phosphor {
  color: var(--phosphor);
}
.m-dir.put {
  color: var(--put-hi);
}

.m-badge {
  padding: 1px 5px;
  border-radius: var(--r-xs);
  font-size: var(--t-nano);
  font-weight: 700;
  border: var(--hair) solid var(--rule);
}
.m-badge.active {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border-color: var(--phosphor-dim);
}
.m-badge.pending {
  color: var(--ink-faint);
  background: var(--void);
}
.m-rule {
  font-size: var(--t-micro);
  color: var(--ink);
  line-height: 1.4;
}
.m-levels {
  font-size: var(--t-nano);
  color: var(--ink-faint);
}

/* Table controls */
.table-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.table-search-box {
  display: inline-flex;
}
.table-search-input {
  width: 100px;
  padding: 2px 6px;
  color: var(--ink);
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  font-size: var(--t-nano);
}
.table-search-input:focus {
  outline: none;
  border-color: var(--phosphor-dim);
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
  font-size: var(--t-nano);
  font-weight: 600;
  cursor: pointer;
  text-transform: uppercase;
}
.mini-segment button.on {
  background: var(--phosphor-wash);
  color: var(--phosphor);
}

.export-btn {
  padding: 2px 8px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  background: var(--panel);
  color: var(--ink-dim);
  font-size: var(--t-nano);
  font-weight: 700;
  cursor: pointer;
}
.export-btn:hover {
  color: var(--ink);
  background: var(--panel-hi);
  border-color: var(--rule-hi);
}

/* Enhanced Bulletproof Sticky Strike table */
.table-wrap {
  min-width: 0;
  overflow-x: auto;
  overflow-y: auto;
  max-height: 540px;
  position: relative;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--surface-base);
}

.strike-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  color: var(--ink-dim);
}

.header-group th {
  position: sticky;
  top: 0;
  z-index: 10;
  padding: 4px 8px;
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.06em;
  text-align: center;
  border-bottom: var(--hair) solid var(--rule);
  box-sizing: border-box;
}
.group-center {
  background: var(--void-lift);
  color: var(--ink);
}
.group-call {
  background: var(--panel-hi);
  color: var(--call-hi);
  border-left: var(--hair) solid var(--rule);
}
.group-put {
  background: var(--panel-hi);
  color: var(--put-hi);
  border-left: var(--hair) solid var(--rule);
}
.group-net {
  background: var(--panel-hi);
  color: var(--phosphor);
  border-left: var(--hair) solid var(--rule);
}

.header-cols th {
  position: sticky;
  top: 26px;
  z-index: 9;
  padding: 6px 8px;
  color: var(--ink-faint);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-align: right;
  background: var(--panel-hi);
  border-bottom: var(--hair) solid var(--rule-hi);
  white-space: nowrap;
  box-sizing: border-box;
}
.header-cols th.sortable {
  cursor: pointer;
  user-select: none;
}
.header-cols th.sortable:hover {
  color: var(--ink);
  background: var(--panel);
}

.strike-col {
  text-align: left;
  position: sticky;
  left: 0;
  z-index: 12;
  background: var(--panel-hi);
}
.call-head {
  color: var(--call-dim);
}
.put-head {
  color: var(--put-dim);
}
.net-head {
  color: var(--ink);
}

.strike-table td {
  padding: 4px 8px;
  text-align: right;
  border-bottom: var(--hair) solid var(--rule-faint);
  white-space: nowrap;
  background: var(--panel);
}
.strike-table .num {
  font-variant-numeric: tabular-nums;
}

.strike-cell {
  text-align: left;
  position: sticky;
  left: 0;
  z-index: 4;
  background: var(--panel);
}
.strike-val {
  color: var(--ink);
  font-weight: 700;
  margin-right: 4px;
}

.badge {
  display: inline-block;
  padding: 1px 4px;
  border-radius: 2px;
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.04em;
  border: var(--hair) solid var(--rule);
}
.spot-badge {
  background: var(--phosphor);
  color: var(--void);
  border-color: var(--phosphor);
}
.call-wall-badge {
  background: var(--call-dim);
  color: var(--void);
  border-color: var(--call-dim);
}
.put-wall-badge {
  background: var(--put-dim);
  color: var(--void);
  border-color: var(--put-dim);
}
.flip-badge {
  background: var(--warn);
  color: var(--void);
  border-color: var(--warn);
}

.moneyness-cell {
  color: var(--ink-faint);
  font-size: 10px;
}

.call-oi,
.call-vol {
  color: var(--ink);
}
.call-delta {
  color: var(--call-dim);
  font-weight: 600;
}
.call-gamma {
  color: var(--call-dim);
}
.call-charm {
  color: var(--call-dim);
}

.put-oi,
.put-vol {
  color: var(--ink);
}
.put-delta {
  color: var(--put-dim);
  font-weight: 600;
}
.put-gamma {
  color: var(--put-dim);
}
.put-charm {
  color: var(--put-dim);
}

.net-charm-cell {
  font-weight: 600;
}
.net-charm-cell.sell-flow {
  color: var(--put-hi);
}
.net-charm-cell.buy-flow {
  color: var(--call-hi);
}

.gex-cell {
  font-weight: 600;
}
.gex-cell.call {
  color: var(--call-hi);
}
.gex-cell.put {
  color: var(--put-hi);
}

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
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 220px;
  padding: 0 16px;
  text-align: center;
  color: var(--ink-faint);
  font-family: var(--font-display);
  font-size: 12px;
  letter-spacing: 0.08em;
  background: var(--void-lift);
}
.ph-msg.fault {
  color: var(--warn);
}
/* Secondary line naming why a panel is empty (e.g. the charm skip breakdown). */
.ph-sub {
  font-size: 10px;
  opacity: 0.7;
}

.state-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 6px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  color: var(--ink-dim);
}
.state-chip.live {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.state-chip.fault {
  color: var(--warn);
  border-color: var(--warn);
}

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
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
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
  .symbol-box {
    align-items: flex-start;
  }
  .symbol-input {
    width: 100%;
    text-align: left;
  }
  .range-box,
  .preset-box {
    width: 100%;
  }
  .range-btn,
  .expiry-btn,
  .preset-btn {
    flex: 1 1 0;
  }
  .expiry-controls {
    width: 100%;
  }
  .expiry-box {
    flex: 1 1 0;
  }
  .expiry-select {
    width: 100%;
  }
  .flow-cascade-container {
    flex-direction: column;
  }
  .cascade-arrow {
    transform: rotate(90deg);
    margin: 4px 0;
  }
}

/* ── Snapshot / history-fallback notices ────────────────────────────────── */
.snapshot-notice {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 12px;
  margin-bottom: var(--s3);
  border: var(--hair) solid var(--rule);
  border-left: 3px solid var(--warn);
  border-radius: var(--r-sm);
  background: var(--warn-wash);
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.03em;
  line-height: 1.5;
}

.snap-icon {
  flex-shrink: 0;
  color: var(--warn);
  font-size: 11px;
  padding-top: 1px;
}

.snapshot-chart-notice {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  margin-top: 4px;
  border-top: var(--hair) solid var(--rule);
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.03em;
  background: var(--panel);
}
</style>
