<script setup lang="ts">
/**
 * /regime — live dealer-gamma regime surface & systematic microstructure workstation.
 *
 * LAZY ACTIVATION is the point of this page: it opens idle, with an
 * explicit "GO LIVE" control, and touches the network only after the
 * operator asks for it. The backend chain read is a rate-limited paid
 * provider call, so nothing here polls on mount.
 *
 * TWO CLOCKS once live:
 *   SLOW  (~75s) — api.options(symbol). Each payload is run through
 *                  buildSmile + riskNeutralDensity exactly once and the
 *                  result is cached in `slowDerived` (a shallowRef).
 *   FAST  (~3s)  — a cheap live-spot read (api.quotes). Every tick,
 *                  buildRegimeState / deriveTilt / applyTilt /
 *                  regimeProbabilities recompute from the CACHED smile —
 *                  no network beyond the spot poll.
 *
 * The breadth strip (`/api/gamma/regime`) prices 15 option chains and is
 * activated independently of the two clocks above, only when that section
 * scrolls into view (handled inside RegimeBreadthStrip via
 * IntersectionObserver) — see `breadthActivated` / `breadthRes` below.
 */
import { computed, nextTick, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type AbsorptionSymbolPayload,
  type OptionsIntelligence,
  type OptionsTapeRow,
} from '@/api'
import { useResource } from '@/composables/useResource'
import { age, num, compact, optGex, optSigned, pctFrac, DASH } from '@/format'
import type {
  RegimeBreadthPayload,
  RegimeProbabilities,
  RegimeState,
  RiskNeutralResult,
  Smile,
  TiltParams,
} from '@/regimeContracts'
import type {
  ExecutionGatePayload,
  MicrostructureRegimeSnapshot,
  StateEstimationPayload,
  AnchoredVwapPayload,
  SystematicSignalsPayload,
  BacktestTearsheet,
} from '@/microstructureContracts'
import type { ZeroDteTapePayload } from '@/api'
import { buildRegimeState } from '@/gammaRegime'
import { availableSmileExpiries, buildSmile, riskNeutralDensity } from '@/riskNeutralDensity'
import { applyTilt, deriveTilt, regimeProbabilities } from '@/gammaTilt'
import {
  computeRuleOf16ExpectedMove,
  assessMoveExcursion,
  assessWallAlignment,
  type ExpectedMoveMetrics,
} from '@/expectedMove'
import { sessionYears, tradingDayYears } from '@/levelProbability'
import {
  buildLevelLadder,
  fairValueTarget,
  orderFlowRead,
  type MergedLevel,
} from '@/levelStructure'

import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import LoadingState from '@/components/LoadingState.vue'
import RegimeSkeletonLoader from '@/components/RegimeSkeletonLoader.vue'
import RegimeSurfaceChart from '@/components/RegimeSurfaceChart.vue'
import RegimeBreadthStrip from '@/components/RegimeBreadthStrip.vue'
import MicrostructureTopographyCard from '@/components/MicrostructureTopographyCard.vue'
import DealerGammaMap from '@/components/DealerGammaMap.vue'
import DealerGreeksFlowCard from '@/components/DealerGreeksFlowCard.vue'
import ExecutionGateCard from '@/components/ExecutionGateCard.vue'
import SectorPairCorrelationCard from '@/components/SectorPairCorrelationCard.vue'
import CausalEnvelopeChart from '@/components/CausalEnvelopeChart.vue'
import KalmanKinematicPhasePlot from '@/components/KalmanKinematicPhasePlot.vue'
import LevelMap from '@/components/LevelMap.vue'
import ZeroDteTape from '@/components/ZeroDteTape.vue'
import RegimeHeaderRibbon from '@/components/RegimeHeaderRibbon.vue'
import MarketContextCard from '@/components/MarketContextCard.vue'
import KeyLevelsCard from '@/components/KeyLevelsCard.vue'
import FlowSummaryDonutCard from '@/components/FlowSummaryDonutCard.vue'
import StrikeGammaExposureChart from '@/components/StrikeGammaExposureChart.vue'
import StrikeOpenInterestChart, {
  type StrikeOiPoint,
} from '@/components/StrikeOpenInterestChart.vue'
import NetFlowByExpiryChart, { type ExpiryFlowRow } from '@/components/NetFlowByExpiryChart.vue'
import RealTimeFlowTape from '@/components/RealTimeFlowTape.vue'
import InstantaneousHedgingCard from '@/components/InstantaneousHedgingCard.vue'
import ForwardTrajectoryCard from '@/components/ForwardTrajectoryCard.vue'
import VolatilitySurface3D from '@/components/VolatilitySurface3D.vue'
import PositioningSummaryCard from '@/components/PositioningSummaryCard.vue'
import NetGammaSpotTimeSeries, {
  type TimeSeriesPoint,
} from '@/components/NetGammaSpotTimeSeries.vue'
import LiveAlertsPanel, { type RegimeAlert } from '@/components/LiveAlertsPanel.vue'
import PrimaryRegimeCard from '@/components/PrimaryRegimeCard.vue'
import FourPillarContextGrid from '@/components/FourPillarContextGrid.vue'
import TransitionRiskGauge from '@/components/TransitionRiskGauge.vue'
import ModelAgreementMatrix from '@/components/ModelAgreementMatrix.vue'
import DynamicExplanationPanel from '@/components/DynamicExplanationPanel.vue'
import type {
  MarketRegimePayload,
  PrimaryRegimeType,
  TrendState,
  FlowStateType,
  VolatilityStateType,
  MarketStructureType,
  SimplexProbabilities,
} from '@/regimeContracts'

const SLOW_POLL_MS = 75_000
const FAST_POLL_MS = 3_000
const BREADTH_POLL_MS = 75_000

const route = useRoute()
const router = useRouter()

const initialSymbol = (
  typeof route.query.symbol === 'string' && route.query.symbol ? route.query.symbol : 'SPY'
).toUpperCase()
const symbolInput = ref(initialSymbol)
const symbol = ref(initialSymbol)

/** The one gate the whole page hangs off. Nothing below fetches until this
 *  flips true — see the module doc for why. */
const activated = ref(false)
const focusStrike = ref<number | null>(null)

const SECTIONS = [
  { id: 'tactical', label: 'TACTICAL' },
  { id: 'levels', label: 'LEVELS & FLOW' },
  { id: 'gamma', label: 'GAMMA MAP' },
  { id: 'dynamics', label: 'DYNAMICS' },
  { id: 'flow', label: 'FLOW TAPE' },
  { id: 'setups', label: 'SETUPS' },
  { id: 'surface', label: 'SURFACE' },
  { id: 'all', label: 'ALL WORKSPACES' },
] as const

const SECTION_GUIDANCE: Record<SectionId, { label: string; description: string }> = {
  tactical: {
    label: 'Start here',
    description:
      'The executive read combines trend, volatility, structure, flow, and dealer gamma into one stance.',
  },
  levels: {
    label: 'Price map',
    description:
      'Use this view to see the nearest support and resistance, the mean target, and what the tape did at each level.',
  },
  gamma: {
    label: 'Dealer positioning',
    description:
      'This view explains where dealer hedging can dampen moves, amplify them, or change across the gamma flip.',
  },
  dynamics: {
    label: 'Market motion',
    description:
      'The charts show the measured trend, velocity, envelope, and anchored VWAP context behind the current read.',
  },
  flow: {
    label: 'Participation',
    description:
      'Follow options flow, expiry pressure, institutional prints, and the dealer hedging response.',
  },
  setups: {
    label: 'Evidence check',
    description:
      'Review recent trigger setups and the backtest breakdown before treating a pattern as actionable.',
  },
  surface: {
    label: 'Probability audit',
    description:
      'Inspect the volatility surface, selected expiry, probability band, and any reasons a number is withheld.',
  },
  all: {
    label: 'Full workstation',
    description:
      'Keep every workspace visible when you need the complete chain from market read to supporting evidence.',
  },
}

type SectionId = (typeof SECTIONS)[number]['id']
const activeSection = ref<SectionId>('tactical')
const activeSectionGuidance = computed(() => SECTION_GUIDANCE[activeSection.value])

function setSection(id: SectionId): void {
  activeSection.value = id
  if (typeof globalThis.window !== 'undefined') {
    globalThis.window.scrollTo({ top: 0, behavior: 'smooth' })
    nextTick(() => {
      globalThis.window.dispatchEvent(new Event('resize'))
    })
  }
}

// Shared multi-pane chart hover tracking
const chartHoverIndex = ref<number | null>(null)

// Standard universe of liquid underliers
const QUICK_UNIVERSE = ['SPY', 'QQQ', 'IWM', 'DIA', 'NVDA', 'TSLA', 'AAPL', 'MSFT'] as const

// Microstructure execution parameters
const lookbackWindow = ref('1y')
const bandwidthH = ref(20.0)
const envelopeAlpha = ref(2.0)
const kalmanQ = ref(0.001)
const breakoutZ = ref(1.6)
const exhaustionZ = ref(0.4)
const barsMode = ref<'daily' | '1h'>('daily')

function setWindow(w: string): void {
  const norm = w.toLowerCase()
  // Map common ribbon timeframes (1d, 5d, 1m, 3m, ytd, 1y) to valid query windows
  const mapped = norm === '1d' || norm === '5d' ? '1m' : norm === 'ytd' ? '1y' : norm
  lookbackWindow.value = mapped
  void stateRes.refresh()
  void signalsRes.refresh()
}

function setBarsMode(mode: 'daily' | '1h'): void {
  barsMode.value = mode
  void stateRes.refresh()
  void signalsRes.refresh()
}

/* ---- SLOW clock: option chain / smile / risk-neutral density ----------- */

const optionsRes = useResource<OptionsIntelligence>(() => api.options({ symbol: symbol.value }), {
  intervalMs: SLOW_POLL_MS,
  immediate: false,
  enabled: () => activated.value,
})

const marketRegimeRes = useResource<MarketRegimePayload>(() => api.marketRegime(symbol.value), {
  intervalMs: SLOW_POLL_MS,
  immediate: false,
  enabled: () => activated.value,
})

/**
 * Which expiry the density is built from.
 *
 * This used to be implicit and wrong for the page: `buildSmile` took the
 * payload's blended IV surface (every expiry averaged together at each strike)
 * on the nearest-to-30-day horizon. Blending expiries is what made the repriced
 * call curve non-convex, which drove the density negative, which tripped the
 * clipped-mass guard — so "Density not reliable" was the panel's normal state
 * rather than its exception. And a 30-day distribution is the wrong question
 * for a page reading intraday dealer hedging in the first place.
 *
 * Null means "nearest expiry with a usable smile", which on a live desk is the
 * front/0DTE contract. The operator can pick another from the strip.
 */
const smileExpiry = ref<string | null>(null)

const expiryChoices = computed(() => availableSmileExpiries(optionsRes.data.value))

/** Built exactly once per SLOW payload (or expiry change), never on the fast tick. */
const slowDerived = shallowRef<{ smile: Smile | null; riskNeutral: RiskNeutralResult | null }>({
  smile: null,
  riskNeutral: null,
})

watch(
  [() => optionsRes.data.value, smileExpiry],
  ([payload, expiry]) => {
    if (!payload) {
      slowDerived.value = { smile: null, riskNeutral: null }
      return
    }
    const smile = buildSmile(payload, expiry)
    slowDerived.value = { smile, riskNeutral: riskNeutralDensity(smile) }
  },
  { immediate: true },
)

/** Reset the expiry pick when the symbol changes — an expiry string from the
 *  previous symbol's chain would silently fall through to "nearest". */
watch(symbol, () => {
  smileExpiry.value = null
})

/* ---- FAST clock: live spot & VIX benchmark quotes ----------------------- */

const spotRes = useResource(() => api.quotes([symbol.value]), {
  intervalMs: FAST_POLL_MS,
  immediate: false,
  enabled: () => activated.value,
})

const macroQuotesRes = useResource(() => api.quotes(['VIX', 'SPY', 'QQQ']), {
  intervalMs: FAST_POLL_MS,
  immediate: false,
  enabled: () => activated.value,
})

const liveSpot = computed<number | null>(() => {
  const row = spotRes.data.value?.rows.find((r) => r.symbol === symbol.value)
  return row?.last ?? null
})

const vixQuote = computed<number | null>(() => {
  const row = macroQuotesRes.data.value?.rows.find((r) => r.symbol === 'VIX')
  return row?.last ?? null
})

const symbolQuoteRow = computed(() => {
  return spotRes.data.value?.rows.find((r) => r.symbol === symbol.value) ?? null
})

/** Before the first fast tick lands, fall back to the slow payload's own
 *  spot rather than showing nothing. */
const effectiveSpot = computed<number | null>(
  () => liveSpot.value ?? optionsRes.data.value?.summary.spot ?? null,
)

/** ATM IV from calibrated smile points */
const atmIv = computed<number | null>(() => {
  const pts = slowDerived.value.smile?.points ?? []
  if (pts.length === 0) return null
  let bestPt = pts[0]
  for (const pt of pts) {
    if (Math.abs(pt.logMoneyness) < Math.abs(bestPt.logMoneyness)) {
      bestPt = pt
    }
  }
  return bestPt.iv
})

/** Rule of 16 Expected Move Metrics (1D, 1W, 1M).
 *
 * The vol input is ATM IV from the calibrated smile; a live VIX quote is the
 * fallback only when the chain offers no IV. There is deliberately no house
 * default — an earlier version fell back to a hard-coded 18.0, so on any day
 * the VIX feed was down (rows come back `source: unavailable`) every EM band
 * on the page and the "VIX 18.0" benchmark tile were invented numbers wearing
 * the market's clothes. */
const expectedMove = computed<ExpectedMoveMetrics | null>(() => {
  const spot = effectiveSpot.value ?? microRegimeRes.data.value?.spot ?? null
  const iv = atmIv.value
  return computeRuleOf16ExpectedMove(spot, iv, vixQuote.value)
})

const moveExcursion = computed(() => {
  if (!expectedMove.value) return null
  /* No prev_close means the change is unknown, not zero — computing an
   * excursion off an assumed 0 prints "0% of 1D EM" as if the tape went
   * sideways when the read simply never came back. */
  const last = symbolQuoteRow.value?.last
  const prev = symbolQuoteRow.value?.prev_close
  if (last == null || prev == null) return null
  /* On a stale mark these are the last two stored daily closes, which on CRDO
   * was the -20% 09-01 -> 09-02 gap. Measured against today's expected move it
   * printed "5.67x 1D EM · Abnormal Volatility Breakout" — a six-day-old gap
   * reported as this session's excursion. */
  const q = symbolQuoteRow.value?.quality
  if (q != null && q !== 'live' && q !== 'realtime' && q !== 'delayed') return null
  return assessMoveExcursion(last - prev, expectedMove.value.em1dDollars)
})

const wallSpatial = computed(() => {
  if (!expectedMove.value) return null
  const spot = effectiveSpot.value ?? 0
  const snap = microRegimeRes.data.value
  return assessWallAlignment(snap?.call_wall, snap?.put_wall, spot, expectedMove.value.em1dDollars)
})

/** US/Eastern session fraction remaining, 1 at the open, 0 at the close.
 *  Keyed off the fast tick's fetchedAt so it re-evaluates every ~3s without
 *  its own timer. */
function computeSessionFractionRemaining(): number {
  const now = new Date()
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: 'numeric',
    minute: 'numeric',
    hour12: false,
  }).formatToParts(now)
  const rawHour = Number(parts.find((p) => p.type === 'hour')?.value ?? '0')
  const hour = rawHour === 24 ? 0 : rawHour
  const minute = Number(parts.find((p) => p.type === 'minute')?.value ?? '0')
  const minutesNow = hour * 60 + minute
  const OPEN = 9 * 60 + 30
  const CLOSE = 16 * 60
  if (minutesNow <= OPEN) return 1
  if (minutesNow >= CLOSE) return 0
  return (CLOSE - minutesNow) / (CLOSE - OPEN)
}

const sessionFractionRemaining = computed(() => {
  void spotRes.fetchedAt.value // re-evaluate alongside the fast clock
  return computeSessionFractionRemaining()
})

/* ---- fast-recomputed regime stack (no network beyond the spot poll) ---- */

const regimeState = computed<RegimeState | null>(() => {
  const payload = optionsRes.data.value
  if (!payload) return null
  return buildRegimeState(payload, effectiveSpot.value)
})

const tilt = computed<TiltParams | null>(() => {
  if (!regimeState.value) return null
  const charm = optionsRes.data.value?.charm_summary ?? null
  return deriveTilt(regimeState.value, charm, sessionFractionRemaining.value)
})

const tiltedResult = computed<RiskNeutralResult | null>(() => {
  if (!regimeState.value || !tilt.value) return null
  return applyTilt(slowDerived.value.smile, tilt.value, regimeState.value)
})

const clippedMassPct = computed<number | null>(() => tiltedResult.value?.clippedMass ?? null)

const rawClippedMassPct = computed<number | null>(
  () => slowDerived.value.riskNeutral?.clippedMass ?? null,
)
const withheldMassPct = computed(() =>
  Math.max(clippedMassPct.value ?? 0, rawClippedMassPct.value ?? 0),
)

/**
 * Three grades, not two.
 *
 * The panel used to be all-or-nothing: above 10% clipped mass every number
 * disappeared behind "Density not reliable". Combined with the blended-expiry
 * smile that produced most of that clipping, the practical result was a
 * probability panel that was blank far more often than it was populated —
 * which reads to an operator as broken, not as careful.
 *
 * Now: under 2% the read is clean; between 2% and 25% the numbers show WITH the
 * clipped fraction stated beside them, because a distribution that lost a few
 * percent of mass to smile noise is still worth more than nothing when it is
 * labelled; above 25% the shape is clipping artifact rather than a
 * distribution and the numbers are genuinely withheld.
 */
const CLIPPED_MASS_CLEAN = 0.02
const CLIPPED_MASS_UNUSABLE = 0.25

const densityGrade = computed<'clean' | 'degraded' | 'unusable'>(() => {
  if (withheldMassPct.value > CLIPPED_MASS_UNUSABLE) return 'unusable'
  if (withheldMassPct.value > CLIPPED_MASS_CLEAN) return 'degraded'
  return 'clean'
})

const densityUnreliable = computed(() => densityGrade.value === 'unusable')
const clippedMassMaterial = computed(() => densityGrade.value === 'degraded')

/** Density from a blended smile is not a density of anything the market
 *  quotes — see buildSmile. Withhold rather than label. */
const smileBlended = computed(() => slowDerived.value.smile?.blended === true)

const probabilities = computed<RegimeProbabilities | null>(() => {
  if (!regimeState.value) return null
  if (densityUnreliable.value || smileBlended.value) return null
  return regimeProbabilities(tiltedResult.value?.grid ?? null, regimeState.value)
})

/** The horizon every probability below is stated over. Without this on screen
 *  the numbers are unreadable: "62% between the walls" means something
 *  completely different at 0DTE than at 30 days. */
const probabilityHorizon = computed<string | null>(() => {
  const sm = slowDerived.value.smile
  if (!sm) return null
  const d = sm.dte
  if (d == null) return sm.expiry || null
  if (d <= 0) return 'today (0DTE)'
  if (d === 1) return '1 day'
  return `${d} days`
})

const verdictText = computed<string | null>(() => {
  const s = regimeState.value
  if (!s || s.regime === 'unmeasurable') return null
  const distTxt = s.distanceToFlip != null ? pctFrac(Math.abs(s.distanceToFlip), 2) : DASH
  if (s.regime === 'short')
    return `Short gamma: dealer hedging amplifies moves. ${distTxt} below the zero-gamma flip.`
  if (s.regime === 'long')
    return `Long gamma: dealer hedging dampens moves. ${distTxt} above the zero-gamma flip.`
  return `Gamma flip boundary: spot is ${distTxt} from the zero-gamma inflection ($${num(s.zeroGamma, 2)}). Directional momentum and volatility expansion trigger on break.`
})

interface PlaybookLine {
  kind: 'stance' | 'trigger' | 'watch'
  text: string
}

const playbook = computed<PlaybookLine[]>(() => {
  const s = regimeState.value
  if (!s || !s.measurable || s.regime === 'unmeasurable') return []
  const out: PlaybookLine[] = []
  const lvl = (v: number | null) => (v != null ? num(v, 2) : DASH)
  const distTxt = s.distanceToFlip != null ? pctFrac(Math.abs(s.distanceToFlip), 2) : null

  if (s.regime === 'short') {
    out.push({
      kind: 'stance',
      text: 'Short-gamma tape: dealer hedging sells weakness and buys strength, so moves extend instead of reverting. Trade with momentum and give positions room; mean-reversion entries and short premium fight the dominant flow.',
    })
  } else if (s.regime === 'long') {
    out.push({
      kind: 'stance',
      text: 'Long-gamma tape: dealer hedging sells strength and buys weakness, so extensions fade and price gravitates to heavy open interest. Fading moves into the walls has the flow behind it; breakout bets fight it.',
    })
  } else {
    out.push({
      kind: 'stance',
      text: `Spot is testing the zero-gamma flip${distTxt ? ` (${distTxt} from the flip)` : ''}. Dealer hedging is shifting across the boundary: above it dampens volatility, below it amplifies moves. Watch the breakout triggers below.`,
    })
  }

  if (s.zeroGamma != null && s.regime === 'short') {
    out.push({
      kind: 'trigger',
      text: `Reclaim ${lvl(s.zeroGamma)} (flip) and hedging flips back to dampening. That is the squeeze back up and the point to stop pressing shorts.`,
    })
  } else if (s.zeroGamma != null) {
    out.push({
      kind: 'trigger',
      text: `Lose ${lvl(s.zeroGamma)} (flip) and damping becomes amplification: below it, downside moves feed on dealer supply instead of meeting it.`,
    })
  }
  if (s.callWall != null) {
    out.push({
      kind: 'trigger',
      text: `Above ${lvl(s.callWall)} (call wall) dealers run out of upside gamma, so breaks through it can gap rather than grind.`,
    })
  }
  if (s.putWall != null) {
    out.push({
      kind: 'trigger',
      text: `Below ${lvl(s.putWall)} (put wall) the dealer put inventory cushioning declines is gone, so downside accelerates once it gives.`,
    })
  }
  if (s.regime === 'long' && s.pinStrike != null) {
    out.push({
      kind: 'watch',
      text: `Pin gravity toward ${lvl(s.pinStrike)} strengthens into the close as charm decays, so expect price to stall near it late in the session.`,
    })
  }
  if (densityUnreliable.value) {
    out.push({
      kind: 'watch',
      text: 'Probabilities are withheld today (noisy smile), so the direction and trigger levels above stand but nothing here sizes a move: treat conviction as unquantified.',
    })
  }
  return out
})

/* ---- MICROSTRUCTURE QUANT WORKSTATION RESOURCES ---------------------- */

const microRegimeRes = useResource<MicrostructureRegimeSnapshot>(
  () => api.microstructureRegime(symbol.value),
  { intervalMs: 30_000, immediate: false, enabled: () => activated.value },
)

/* The execution-side gates: session phase, expiry policy, opening range and
   the routed contract. Polled faster than the regime read because its lead
   value is the clock, and a phase boundary that lands 30s late is a boundary
   the operator can trade through. */
const executionGateRes = useResource<ExecutionGatePayload>(() => api.executionGate(symbol.value), {
  intervalMs: 15_000,
  immediate: false,
  enabled: () => activated.value,
})

const stateRes = useResource<StateEstimationPayload>(
  () =>
    api.stateEstimation(symbol.value, {
      window: lookbackWindow.value,
      h: bandwidthH.value,
      alpha: envelopeAlpha.value,
      q: kalmanQ.value,
      bars: barsMode.value,
    }),
  { intervalMs: 60_000, immediate: false, enabled: () => activated.value },
)

/**
 * 0DTE tape — the same-day expiry's magnets against the session's real bars.
 *
 * Polls faster than the rest of the page on purpose: a 0DTE magnet moves with
 * the clock, not just with the chain, because time-to-expiry is an input to
 * every gamma number behind it.
 */
const zeroDteTf = ref<'1m' | '5m' | '15m'>('5m')
const zeroDteRes = useResource<ZeroDteTapePayload>(
  () => api.zeroDte(symbol.value, { tf: zeroDteTf.value }),
  { intervalMs: 30_000, immediate: false, enabled: () => activated.value },
)

function setZeroDteTimeframe(tf: '1m' | '5m' | '15m') {
  if (tf === zeroDteTf.value) return
  zeroDteTf.value = tf
  void zeroDteRes.refresh()
}

const vwapRes = useResource<AnchoredVwapPayload>(
  () => api.anchoredVwap(symbol.value, { window: lookbackWindow.value, bars: barsMode.value }),
  { intervalMs: 60_000, immediate: false, enabled: () => activated.value },
)

const signalsRes = useResource<SystematicSignalsPayload>(
  () =>
    api.systematicSignals(symbol.value, {
      window: lookbackWindow.value,
      h: bandwidthH.value,
      alpha: envelopeAlpha.value,
      breakout_z: breakoutZ.value,
      exhaustion_z: exhaustionZ.value,
      bars: barsMode.value,
    }),
  { intervalMs: 30_000, immediate: false, enabled: () => activated.value },
)

/**
 * ORDER FLOW — the lens this page was missing entirely.
 *
 * `/api/absorption/<symbol>` has been shipping a fixed-range order-flow matrix
 * on every call: volume-at-price split buy/sell, per-bin signed delta, wick
 * absorption (size that pushed into a price and was refused), touch and
 * rejection counts, and scored support/resistance zones. The regime page read
 * none of it and derived its levels from dealer gamma alone — positioning with
 * no read on what the tape actually did at those prices.
 *
 * Polled slowly (120s): the matrix is a trailing-window statistic over ~220
 * bars, so it does not meaningfully move on the 3s spot clock, and the
 * endpoint runs an absorption backtest on the cold path.
 */
const absorptionRes = useResource<AbsorptionSymbolPayload>(
  () => api.absorptionSymbol(symbol.value, { limit: 10 }),
  { intervalMs: 120_000, immediate: false, enabled: () => activated.value },
)

const flowMatrix = computed(() => absorptionRes.data.value?.matrix ?? null)

const backtestRunning = ref(false)
const backtestResult = ref<BacktestTearsheet | null>(null)
const backtestCapital = ref(100_000)
const backtestRiskPct = ref(0.02)
const backtestSlippage = ref(2.0)

async function runBacktest() {
  backtestRunning.value = true
  try {
    const res = await api.systematicBacktest(symbol.value, {
      window: lookbackWindow.value,
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

const activeSignal = computed(() => {
  if (!signalsRes.data.value?.latest_signal) return null
  const s = signalsRes.data.value.latest_signal
  return s.action !== 'NONE' ? s : null
})

const recentSignals = computed(() => {
  if (!signalsRes.data.value?.signals) return []
  return signalsRes.data.value.signals
    .filter((s) => s.action === 'ENTER_LONG' || s.action === 'ENTER_SHORT')
    .slice(-10)
    .reverse()
})

/* ---- SYNTHESIZED EXECUTIVE REGIME TACTICAL INTELLIGENCE --------------- */

const latestStatePoint = computed(() => {
  const pts = stateRes.data.value?.points ?? []
  return pts.length > 0 ? pts[pts.length - 1] : null
})

/**
 * THE regime read for this page.
 *
 * Both tabs used to answer "what regime is this" independently: the briefing
 * below re-derived it from the microstructure endpoint's net GEX and flip,
 * while the surface tab's verdict came from `buildRegimeState` over
 * `gex_price_profile`. Two derivations, two sign conventions upstream, and no
 * indication to the operator which one to believe when they disagreed -- which
 * on any single-name symbol was always.
 *
 * There is now one read. `regimeState` is it: it recomputes on the fast spot
 * clock from the same GEX profile the server classifies against, so the
 * briefing, the verdict, the playbook and the map all move together. The
 * snapshot contributes the things only it measures -- higher-order Greeks,
 * topography, chain quality -- and never a second opinion on the regime.
 */
const chainMeasurable = computed(() => microRegimeRes.data.value?.quality?.measurable !== false)

const regimeRead = computed(() => {
  const s = regimeState.value
  const snap = microRegimeRes.data.value
  const measurable = s != null && s.regime !== 'unmeasurable' && chainMeasurable.value
  return {
    /** 'long' | 'short' | 'flip' | null when withheld. */
    side: measurable ? s!.regime : null,
    netGammaM: measurable ? s!.netGammaM : null,
    spot: s?.spot ?? snap?.spot ?? null,
    zeroGamma: measurable ? s!.zeroGamma : null,
    callWall: measurable ? s!.callWall : null,
    putWall: measurable ? s!.putWall : null,
    pinStrike: measurable ? s!.pinStrike : null,
    distanceToFlip: measurable ? s!.distanceToFlip : null,
    strength: snap?.regime_strength ?? null,
    withheldReason: measurable
      ? null
      : (snap?.quality?.reason ??
        (s == null ? 'waiting for the first chain read' : 'no open interest observed')),
  }
})

/**
 * Core regime telemetry is processing when options/market-regime/microstructure
 * are still loading on cold start or symbol switch and have not yet settled.
 * When true, the workstation withholds provisional/wrong reads ("Range-Bound Consolidation",
 * "Compression Range") and renders the instrument-grade RegimeSkeletonLoader.
 */
const isRegimeProcessing = computed<boolean>(() => {
  if (!activated.value) return false
  const hasOptions = optionsRes.data.value != null
  const hasMarketRegime = marketRegimeRes.data.value != null
  const hasMicroRegime = microRegimeRes.data.value != null
  const hasState = stateRes.data.value != null
  const isLoadingCore =
    (optionsRes.loading.value && !hasOptions) ||
    (marketRegimeRes.loading.value && !hasMarketRegime) ||
    (microRegimeRes.loading.value && !hasMicroRegime) ||
    (stateRes.loading.value && !hasState)
  return isLoadingCore
})

const tacticalBiasRead = computed(() => {
  const r = regimeRead.value
  const pt = latestStatePoint.value
  const vel = pt?.kalman_velocity ?? 0
  const spot = r.spot ?? effectiveSpot.value

  if (isRegimeProcessing.value) {
    return {
      title: 'CALIBRATING MULTI-MODEL REGIME',
      bias: 'CALIBRATING…',
      toneClass: 'neutral',
      stance:
        'Pricing live option chains and synthesizing multi-model regime telemetry. Real-time dealer gamma, volatility structure, and causal kinematics are processing.',
      action: 'Awaiting initial multi-model consensus before issuing tactical playbook guidance.',
    }
  }

  if (r.side == null) {
    if (pt != null && spot != null) {
      if (vel > 0.0005) {
        return {
          title: 'KINEMATIC DRIFT · BULLISH MOMENTUM',
          bias: 'BULLISH TREND',
          toneClass: 'bullish',
          stance: `Kalman kinematic velocity is positive (+${num(vel, 4)}). Price ($${num(spot, 2)}) is advancing in an upward drift.`,
          action: 'Follow momentum; trail stops below the causal kernel mean.',
        }
      } else if (vel < -0.0005) {
        return {
          title: 'KINEMATIC CASCADE · BEARISH MOMENTUM',
          bias: 'BEARISH TREND',
          toneClass: 'bearish',
          stance: `Kalman kinematic velocity is negative (${num(vel, 4)}). Price ($${num(spot, 2)}) is decelerating downward.`,
          action: 'Sell rallies; trail stops above the causal kernel mean.',
        }
      } else {
        return {
          title: 'RANGE-BOUND CONSOLIDATION',
          bias: 'NEUTRAL / RANGE',
          toneClass: 'neutral',
          stance: `Kinematic velocity is near zero (${num(vel, 4)}). Price ($${num(spot, 2)}) is oscillating within range.`,
          action: 'Fade extremes; await directional breakout before sizing up.',
        }
      }
    }
    if (spot != null && spot > 0) {
      return {
        title: 'SPOT BASELINE · CONSOLIDATION',
        bias: 'RANGE-BOUND CONSOLIDATION',
        toneClass: 'neutral',
        stance: `Live spot price is $${num(spot, 2)}. Baseline structure indicates consolidation while full options depth calibrates.`,
        action: 'Monitor key boundaries around spot; follow break of consolidation range.',
      }
    }
    return {
      title: 'INITIALIZING TELEMETRY',
      bias: 'COMPUTING READ',
      toneClass: 'neutral',
      stance: `Awaiting initial telemetry feeds: ${r.withheldReason}.`,
      action: 'Telemetry initializing; stream updates automatically on incoming market ticks.',
    }
  }

  // A flip level is not required to state the regime — the sign of net dealer
  // gamma is the regime. It is only required to name a *boundary*, so every
  // line that cites S* below is guarded on it existing.
  const hasFlip = r.zeroGamma != null

  if (r.side === 'long') {
    return vel >= 0
      ? {
          title: 'LONG GAMMA · SUPPORTIVE INTO STRENGTH',
          bias: 'BULLISH / UPWARD DRIFT',
          toneClass: 'bullish',
          stance:
            'Dealers are long gamma: they sell strength and buy weakness, so extensions fade and price gravitates toward heavy open interest. Kalman velocity is positive, so the drift inside that damping is upward.',
          action:
            'Buy pullbacks toward the causal kernel mean m(t); target the call wall, and expect the grind rather than the gap.',
        }
      : {
          title: 'LONG GAMMA CONVERGENCE (MEAN-REVERTING)',
          bias: 'MEAN-REVERT',
          toneClass: 'bullish',
          stance:
            'Dealers are long gamma and hedging damps both directions toward the pin. Velocity is negative, so the fade is currently working downward.',
          action:
            'Fade envelope extremes back to the kernel mean; take profit quickly, because the same damping that gives the entry caps the target.',
        }
  }

  if (r.side === 'short') {
    return vel <= 0
      ? {
          title: 'SHORT GAMMA · DOWNSIDE AMPLIFICATION',
          bias: 'BEARISH TREND',
          toneClass: 'bearish',
          stance:
            'Dealers are short gamma: hedging sells into weakness, so down moves feed on dealer supply instead of meeting it. Velocity is negative and aligned with that flow.',
          action: hasFlip
            ? 'Sell rallies that fail beneath the flip; size down and widen stops, because realized vol expands in this regime.'
            : 'Sell rallies that fail at the upper envelope; size down and widen stops, because realized vol expands in this regime.',
        }
      : {
          title: 'SHORT GAMMA · SQUEEZE EXPANSION',
          bias: 'SHORT SQUEEZE (BULLISH)',
          toneClass: 'squeeze',
          stance:
            'Dealers are short gamma while velocity has turned up, so the same hedging that accelerated the decline now forces buying into the rally.',
          action: hasFlip
            ? 'Momentum long with a trailing stop at the flip; the squeeze ends where hedging flips back to damping.'
            : 'Momentum long with a trailing stop at the kernel mean; no flip level is measurable to anchor the exit.',
        }
  }

  const distTxt = r.distanceToFlip != null ? pctFrac(Math.abs(r.distanceToFlip), 2) : '0%'
  const flipPrice = r.zeroGamma != null ? `$${num(r.zeroGamma, 2)}` : 'the flip'
  const cwPrice = r.callWall != null ? `$${num(r.callWall, 2)}` : 'Call Wall'
  const pwPrice = r.putWall != null ? `$${num(r.putWall, 2)}` : 'Put Wall'

  if (vel >= 0) {
    return {
      title: 'GAMMA FLIP TRANSITION · UPSIDE BREAKOUT',
      bias: 'BREAKOUT WATCH (BULLISH)',
      toneClass: 'squeeze',
      stance: `Spot is testing the zero-gamma flip at ${flipPrice} (${distTxt} away) with positive kinematic velocity (+${num(vel, 4)}). Moving above shifts dealer hedging into damping; momentum continues toward ${cwPrice}.`,
      action: `Long breakout with stop trailed tightly at ${flipPrice}; take profit into ${cwPrice} where call resistance builds.`,
    }
  } else {
    return {
      title: 'GAMMA FLIP TRANSITION · DOWNSIDE BREAKDOWN RISK',
      bias: 'BREAKDOWN WATCH (BEARISH)',
      toneClass: 'bearish',
      stance: `Spot is testing the zero-gamma flip at ${flipPrice} (${distTxt} away) with negative kinematic velocity (${num(vel, 4)}). Sustained break below enters short gamma, accelerating downside realized vol toward ${pwPrice}.`,
      action: `Fade failed tests at ${flipPrice}; target ${pwPrice} with stops placed just above the flip.`,
    }
  }
})

/**
 * The briefing above answers from whatever has arrived.
 *
 * Before the option chain lands, `regimeRead.side` is null and the read is
 * price-only: Kalman velocity and spot, no dealer gamma. That read is worth
 * showing -- it beats an empty banner -- but it used to be rendered with the
 * exact typography, tone and imperative voice as the finished gamma read, so
 * when the chain arrived ~a minute later the banner silently rewrote itself
 * ("KINEMATIC CASCADE" -> "SHORT GAMMA · DOWNSIDE AMPLIFICATION") and the
 * operator had no way to know the first one had been provisional all along.
 *
 * It is now labelled while it is provisional, so the rewrite is the expected
 * outcome of the chain landing rather than the page changing its mind.
 */
const tacticalBias = computed(() => {
  const provisional = regimeRead.value.side == null
  return {
    ...tacticalBiasRead.value,
    provisional,
    provisionalNote: isRegimeProcessing.value
      ? null
      : provisional
        ? `Price-only read — dealer gamma pending (${regimeRead.value.withheldReason ?? 'chain loading'})`
        : null,
  }
})

/**
 * The direction the briefing above is actually arguing for, as a value rather
 * than as prose.
 *
 * The ticket comes from `/api/systematic-execution/signals`, which reports
 * `gamma_conditioned: false` — it reads price and volume structure only. The
 * briefing comes from the dealer-gamma read. Nothing reconciled them, so the
 * banner could say SHORT SQUEEZE (BULLISH) while the ticket underneath it said
 * ENTER_SHORT, and the page presented both as its own conclusion.
 *
 * It is not that one engine is right. Two lenses disagreeing is information —
 * a breakdown ticket firing into a squeeze read is exactly the setup that gets
 * run over. But it has to be shown as a disagreement, not as an instruction.
 */
const briefingSide = computed<'long' | 'short' | 'neutral'>(() => {
  const r = regimeRead.value
  const vel = latestStatePoint.value?.kalman_velocity ?? 0
  if (r.side === 'long') return vel >= 0 ? 'long' : 'neutral' // damped: fade both ways
  if (r.side === 'short') return vel > 0 ? 'long' : 'short' // squeeze vs cascade
  if (r.side === 'flip') return vel >= 0 ? 'long' : 'short'
  if (vel > 0.0005) return 'long'
  if (vel < -0.0005) return 'short'
  return 'neutral'
})

/**
 * The ticket as the page is entitled to present it: its own numbers, plus how
 * old it is and whether it contradicts the regime read.
 */
const ticketRead = computed(() => {
  const sig = activeSignal.value
  if (!sig) return null

  const bias = briefingSide.value
  const conflict = bias !== 'neutral' && sig.direction !== bias

  // Age. `latest_signal` is the last bar of the requested window, which on a
  // daily window is yesterday's close — the ticket was quoted against a price
  // that is no longer spot. That was invisible: the row printed an entry with
  // no date on it.
  const barTs = Date.parse(sig.timestamp)
  const ageMs = Number.isFinite(barTs) ? Date.now() - barTs : null
  const ageHours = ageMs != null ? ageMs / 3_600_000 : null
  const spot = effectiveSpot.value ?? regimeRead.value.spot ?? null
  const driftPct =
    spot != null && sig.entry_price > 0 ? ((spot - sig.entry_price) / sig.entry_price) * 100 : null

  // The entry is only still live if spot has not already walked through the
  // stop or the target.
  let staleReason: string | null = null
  if (spot != null && sig.stop_loss > 0) {
    const stopHit = sig.direction === 'long' ? spot <= sig.stop_loss : spot >= sig.stop_loss
    const tgtHit = sig.direction === 'long' ? spot >= sig.take_profit : spot <= sig.take_profit
    if (stopHit) staleReason = 'spot has already traded through the stop'
    else if (tgtHit) staleReason = 'spot has already reached the target'
  }
  if (staleReason == null && ageHours != null && ageHours > 20) {
    staleReason = `quoted ${ageHours >= 48 ? `${Math.round(ageHours / 24)}d` : `${Math.round(ageHours)}h`} ago on a ${num(sig.entry_price, 2)} close`
  }

  return {
    sig,
    conflict,
    biasSide: bias,
    staleReason,
    driftPct,
    /** Risk in dollars per share — one R. */
    riskPerShare: Math.abs(sig.entry_price - sig.stop_loss),
    unitLabel:
      sig.risk_unit_basis === 'implied_1bar'
        ? 'implied 1-bar σ'
        : sig.risk_unit_basis === 'atr'
          ? 'ATR'
          : sig.risk_unit_basis === 'close_to_close'
            ? 'close-to-close σ'
            : 'unmeasured',
    actionable: !conflict && staleReason == null,
  }
})

/* ---- EVIDENCE STRIP --------------------------------------------------------
 *
 * The briefing above speaks in plain sentences, and sentences are where false
 * confidence lives. This strip is the counterweight: every claim the banner
 * makes stands on one of these chips, and each chip declares how it was
/**
 * Structural pivot ladder — every level the operator can act on, on one price
 * axis, sorted high to low.
 *
 * Gamma levels come from `regimeRead` (the single regime read), NOT from the
 * snapshot directly, so the ladder cannot print a wall the verdict above it
 * disagrees with. Levels that are genuinely unmeasurable are dropped rather
 * than defaulted — a "PUT WALL" line at a placeholder price is worse than no
 * line, because the operator will hang a stop on it.
 */
const pivotLadder = computed(() => {
  const r = regimeRead.value
  const spot = r.spot ?? 0
  const pt = latestStatePoint.value
  const em = expectedMove.value

  const list: Array<{ label: string; price: number | null; role: string; tone: string }> = [
    { label: 'CALL WALL', price: r.callWall, role: 'Heaviest call gamma above spot', tone: 'call' },
    ...(em
      ? [
          {
            label:
              expectedMove.value?.ivBasis === 'vix_proxy' ? '+1D EM (VIX/16)' : '+1D EM (IV/16)',
            price: em.em1dHigh,
            role: 'Rule of 16 upper 1σ',
            tone: 'warn',
          },
        ]
      : []),
    ...(pt
      ? [{ label: 'UPPER ENVELOPE', price: pt.nw_upper, role: 'Causal NW +ασ band', tone: 'call' }]
      : []),
    {
      label: 'SPOT PRICE',
      price: spot > 0 ? spot : null,
      role: 'Current underlying',
      tone: 'spot',
    },
    ...(pt
      ? [
          {
            label: 'KERNEL MEAN m(t)',
            price: pt.nw_mean,
            role: 'Latent equilibrium',
            tone: 'phosphor',
          },
        ]
      : []),
    { label: 'PIN', price: r.pinStrike, role: 'Peak |net GEX| strike', tone: 'phosphor' },
    { label: 'GAMMA FLIP S*', price: r.zeroGamma, role: 'Regime boundary', tone: 'warn' },
    ...(pt
      ? [{ label: 'LOWER ENVELOPE', price: pt.nw_lower, role: 'Causal NW −ασ band', tone: 'put' }]
      : []),
    ...(em
      ? [
          {
            label: em.ivBasis === 'vix_proxy' ? '-1D EM (VIX/16)' : '-1D EM (IV/16)',
            price: em.em1dLow,
            role: 'Rule of 16 lower 1σ',
            tone: 'warn',
          },
        ]
      : []),
    { label: 'PUT WALL', price: r.putWall, role: 'Heaviest put gamma below spot', tone: 'put' },
  ]

  return list
    .filter(
      (x): x is { label: string; price: number; role: string; tone: string } =>
        x.price != null && Number.isFinite(x.price) && x.price > 0,
    )
    .sort((a, b) => b.price - a.price)
})

/** Levels the ladder had to drop, named so their absence is visible rather
 *  than silently looking like a shorter list. */
const missingLevels = computed<string[]>(() => {
  const r = regimeRead.value
  if (r.side == null) return []
  const out: string[] = []
  if (r.callWall == null) out.push('call wall')
  if (r.putWall == null) out.push('put wall')
  if (r.zeroGamma == null) out.push('gamma flip')
  return out
})

function pivotDeltaPct(price: number | null): string | null {
  const s = regimeRead.value.spot ?? effectiveSpot.value
  if (!s || s <= 0 || !price) return null
  const diff = ((price - s) / s) * 100
  return `${diff >= 0 ? '+' : ''}${num(diff, 1)}%`
}

/* ---- LEVEL MAP: probabilities, order flow, and the mean -----------------
 *
 * Three things the ladder above could not answer, and now does:
 *   · how likely each level is to be REACHED (first passage, not settlement)
 *   · whether the tape has defended that price (order-flow matrix)
 *   · where price is being pulled back to (POC / VWAP / kernel mean)
 */

/** Latest anchored-VWAP value, from the most recent anchor rather than the
 *  window-wide one: an equilibrium estimate that still carries three months
 *  of pre-event volume is not the mean today's tape is reverting to. */
const latestVwap = computed<number | null>(() => {
  const anchors = vwapRes.data.value?.anchors ?? []
  if (!anchors.length) return null
  const newest = anchors.reduce((a, b) => (b.anchor_index > a.anchor_index ? b : a))
  const series = newest.series
  const last = series.length ? series[series.length - 1] : null
  return last?.vwap ?? null
})

/** Calendar DTE is quoted in calendar days; variance accrues on trading days.
 *  Converting explicitly keeps one clock across every horizon on the page. */
const TRADING_DAYS_PER_CALENDAR_DAY = 252 / 365

/**
 * The horizon every level probability is stated over, and the vol it uses.
 *
 * Null when there is no ATM IV, which withholds the whole probability lane
 * rather than defaulting to a house volatility — a level probability computed
 * off an assumed sigma is a number the operator cannot audit.
 */
const levelHorizon = computed<{ label: string; tYears: number; sigma: number } | null>(() => {
  const sigma = atmIv.value
  if (sigma == null || !Number.isFinite(sigma) || sigma <= 0) return null
  const dte = slowDerived.value.smile?.dte ?? null
  if (dte != null && dte <= 0) {
    const t = sessionYears(sessionFractionRemaining.value)
    return t > 0 ? { label: 'rest of session', tYears: t, sigma } : null
  }
  const days = dte != null && dte > 0 ? dte : 1
  return {
    label: days === 1 ? '1 day' : `${days} days`,
    tYears: tradingDayYears(days * TRADING_DAYS_PER_CALENDAR_DAY),
    sigma,
  }
})

/**
 * Reconciled multi-model Layer 3 market regime payload.
 * Fuses the multi-model classification with the authoritative structural levels
 * (call wall, put wall, gamma flip, session vwap) and spot so that the primary regime card,
 * four pillars, transition gauge, level map, and tactical briefing are in 100% agreement.
 */
const reconciledMarketRegime = computed<MarketRegimePayload | null>(() => {
  const raw = marketRegimeRes.data.value
  const r = regimeRead.value
  const pt = latestStatePoint.value
  const vel = pt?.kalman_velocity ?? 0
  const spot = r.spot ?? effectiveSpot.value ?? raw?.spot ?? null

  if (!spot && !raw) return null

  // When the multi-model regime engine is still calculating, withhold synthesizing
  // a provisional regime rather than spoofing "Compression Range" or a premature trend.
  if (marketRegimeRes.loading.value && !raw) {
    return null
  }

  const measurable = r.side != null && r.side !== 'unmeasurable' && chainMeasurable.value

  // Determine decisive reconciled primary regime and label:
  let primary: PrimaryRegimeType =
    raw?.primary ?? (measurable ? 'compression_range' : 'unmeasurable')
  let primaryLabel = raw?.primaryLabel ?? (measurable ? 'Compression Range' : 'Unmeasured')
  // Calibrated confidence and the probability simplex are outputs of the regime
  // engine (`compute_calibrated_confidence` / `compute_regime_probabilities`).
  // There is deliberately no local seed for either. An earlier version defaulted
  // the score to 0.78 and floored it at 0.72, so the hero card read
  // "CALIBRATED CONFIDENCE · MODERATE · 72.0%" on every symbol whose
  // /api/market-regime call had not landed -- a number nothing had calibrated.
  let confidenceScore: number | null = raw?.confidence?.score ?? null
  let confidenceBand: 'high' | 'moderate' | 'low' = raw?.confidence?.band ?? 'low'
  let penaltyFactors: string[] = []
  let probs: SimplexProbabilities | null = raw?.probabilities ? { ...raw.probabilities } : null

  if (measurable) {
    // If raw primary is uncertain/unmeasurable or contradicts the live workstation read, reconcile decisively:
    if (
      !raw ||
      raw.primary === 'uncertain_transitional' ||
      raw.primary === 'unmeasurable' ||
      (r.side === 'long' && raw.primary === 'bear_trend') ||
      (r.side === 'short' && raw.primary === 'bull_trend')
    ) {
      if (r.side === 'long') {
        if (vel >= 0) {
          primary = 'bull_trend'
          primaryLabel = 'BULLISH TREND (LONG GAMMA DRIFT)'
        } else {
          primary = 'mean_reverting'
          primaryLabel = 'MEAN REVERTING (LONG GAMMA CONVERGENCE)'
        }
      } else if (r.side === 'short') {
        if (vel <= 0) {
          primary = 'bear_trend'
          primaryLabel = 'BEARISH TREND (SHORT GAMMA AMPLIFICATION)'
        } else {
          primary = 'vol_expansion_breakout'
          primaryLabel = 'SHORT SQUEEZE (GAMMA EXPANSION)'
        }
      } else if (r.side === 'flip') {
        primary = 'vol_expansion_breakout'
        primaryLabel = vel >= 0 ? 'GAMMA FLIP BREAKOUT (UPSIDE)' : 'GAMMA FLIP BREAKDOWN (DOWNSIDE)'
      }
    } else {
      primary = raw.primary
      primaryLabel = raw.primaryLabel || primary.replace(/_/g, ' ').toUpperCase()
    }
  } else if (spot != null) {
    // Non-options or loading tape fallback: reconcile from price kinematics and structure
    if (vel > 0.0005) {
      primary = 'bull_trend'
      primaryLabel = 'BULLISH TREND (KINEMATIC DRIFT)'
    } else if (vel < -0.0005) {
      primary = 'bear_trend'
      primaryLabel = 'BEARISH TREND (KINEMATIC CASCADE)'
    } else {
      primary = 'compression_range'
      primaryLabel = 'COMPRESSION RANGE (CONSOLIDATION)'
    }
  }

  // The engine's calibrated confidence and simplex describe the label the
  // engine chose. When the live chain read overrides that label above, neither
  // number transfers to the label actually on screen, so both are withheld
  // rather than relabelled -- the card renders an em dash and an UNCALIBRATED
  // chip instead of a confident-looking figure nothing produced.
  const labelIsLocallyReconciled = raw == null || primary !== raw.primary
  if (labelIsLocallyReconciled) {
    confidenceScore = null
    confidenceBand = 'low'
    probs = null
  }

  // Keep engine-authored confidence penalties only. Walls, flip distance and
  // kinematic speed are signed reads, not ⚠ penalties — stuffing them into
  // penaltyFactors painted the confidence box red and overflowed the gauge.
  penaltyFactors = labelIsLocallyReconciled ? [] : (raw?.confidence?.penaltyFactors ?? [])

  const trendState: TrendState =
    vel > 0.005
      ? 'strong_up'
      : vel > 0.0005
        ? 'up'
        : vel < -0.005
          ? 'strong_down'
          : vel < -0.0005
            ? 'down'
            : 'flat'

  const trendObj = raw?.trend
    ? {
        ...raw.trend,
        state: trendState,
        kalmanVelocity: vel,
        kalmanZScore: pt?.kalman_zscore ?? vel / 0.001,
        measured: true,
      }
    : {
        state: trendState,
        slope: vel,
        kalmanVelocity: vel,
        kalmanZScore: pt?.kalman_zscore ?? vel / 0.001,
        // Persistence is a fitted statistic, not a constant. Without the
        // engine payload there is nothing to report; 1.0 rendered as
        // "Persistence Index 100%" on a page that had measured nothing.
        trendPersistence: null,
        measured: pt != null,
      }

  const flowState: FlowStateType = (r.netGammaM ?? 0) >= 0 ? 'accumulation' : 'distribution'
  const flowObj = raw?.flow
    ? {
        ...raw.flow,
        netGexM: r.netGammaM ?? raw.flow.netGexM,
        dealerGammaRegime: r.side ?? raw.flow.dealerGammaRegime,
        state: flowState,
        measured: true,
      }
    : {
        state: flowState,
        dealerGammaRegime: r.side ?? 'long',
        netGexM: r.netGammaM ?? null,
        netVexM: null,
        netCharmDriftM: null,
        orderFlowDeltaM: netFlowM.value ?? null,
        hedgingPressureDirection: r.side === 'long' ? 'supportive' : 'pressuring',
        measured: r.side != null,
      }

  const flipDesc =
    r.zeroGamma != null
      ? `${r.side === 'long' ? 'above' : r.side === 'short' ? 'below' : 'at'} the Gamma Flip ($${num(r.zeroGamma, 2)})`
      : 'relative to dynamic price channels'
  const velDesc = `${vel >= 0 ? 'positive' : 'negative'} kinematic momentum (${vel >= 0 ? '+' : ''}${num(vel, 4)})`
  const reconciledHeadline = `${primaryLabel} · Structural Driver Synthesis`
  const reconciledSummary = `Market regime is driven by ${primaryLabel}. Spot ($${num(spot, 2)}) is ${flipDesc} with ${velDesc}.`

  const isHeadlineUncertain =
    !raw?.explanation?.headline ||
    primary !== raw?.primary ||
    /uncertain|unmeasured|withheld|dispersion|transition|conflict|disagree/i.test(
      raw.explanation.headline,
    )

  const isSummaryUncertain =
    !raw?.explanation?.summary ||
    primary !== raw?.primary ||
    /uncertain|unmeasured|withheld|dispersion|transition|conflict|disagree/i.test(
      raw.explanation.summary,
    )

  const explanationObj = {
    headline: isHeadlineUncertain ? reconciledHeadline : raw!.explanation.headline,
    summary: isSummaryUncertain ? reconciledSummary : raw!.explanation.summary,
    leadingDrivers:
      raw?.explanation?.leadingDrivers &&
      raw.explanation.leadingDrivers.length > 0 &&
      primary === raw?.primary &&
      !raw.explanation.leadingDrivers.some((d: string) => /conflict|uncertain|disagree/i.test(d))
        ? raw.explanation.leadingDrivers
        : [
            `Dealer Gamma: ${r.side ? r.side.toUpperCase() + ' Γ' : 'ACTIVE'} (${r.netGammaM != null ? optGex(r.netGammaM) : DASH})`,
            `Kinematic Velocity: ${vel >= 0 ? '+' : ''}${num(vel, 4)}`,
            r.zeroGamma != null
              ? `Gamma Flip S*: $${num(r.zeroGamma, 2)}`
              : `Session VWAP: $${num(latestVwap.value, 2)}`,
          ],
    riskFactors:
      raw?.explanation?.riskFactors && raw.explanation.riskFactors.length > 0
        ? raw.explanation.riskFactors
        : [
            r.callWall != null
              ? `Resistance at Call Wall $${num(r.callWall, 2)}`
              : 'Resistance channel dynamic',
            r.putWall != null
              ? `Support at Put Wall $${num(r.putWall, 2)}`
              : 'Support channel dynamic',
          ],
    uncertaintySources:
      raw?.explanation?.uncertaintySources && raw.explanation.uncertaintySources.length > 0
        ? raw.explanation.uncertaintySources
        : [],
  }

  const volState: VolatilityStateType =
    (expectedMove.value?.ivAnnualPct ?? 0) > 30 ? 'elevated' : 'normal'
  const structState: MarketStructureType =
    (pt?.ou_half_life ?? 0) < 15 ? 'mean_reverting' : 'trending'

  return {
    symbol: symbol.value,
    asof_utc: raw?.asof_utc ?? new Date().toISOString(),
    spot,
    primary,
    primaryLabel,
    confidence: {
      score: confidenceScore,
      band: confidenceBand,
      penaltyFactors,
    },
    probabilities: probs,
    trend: trendObj,
    volatility: raw?.volatility ?? {
      state: volState,
      realizedVolPct: hv20d.value ?? null,
      impliedVolPct: expectedMove.value?.ivAnnualPct ?? null,
      volPercentile: null,
      parkinsonVolPct: null,
      ivHvRatio: null,
      measured: hv20d.value != null || expectedMove.value?.ivAnnualPct != null,
    },
    structure: raw?.structure ?? {
      state: structState,
      ouHalfLifeBars: pt?.ou_half_life ?? null,
      hurstExponent: null,
      breakoutZScore: null,
      exhaustionZScore: null,
      measured: pt != null,
    },
    flow: flowObj,
    // CUSUM/BOCPD hazard, run length and stability come from the engine or not
    // at all. The previous clamps (`Math.min(.. , 0.28)`, `Math.max(.., 0.78)`)
    // did not reconcile anything -- they capped a real hazard while inventing
    // "15.0% LOW HAZARD / 85% stability / 45 of 50 bars" whenever the engine
    // was silent.
    transition: {
      level: raw?.transition?.level ?? 'low',
      changepointProb5d: raw?.transition?.changepointProb5d ?? null,
      changepointProb20d: raw?.transition?.changepointProb20d ?? null,
      mapRunLength: raw?.transition?.mapRunLength ?? null,
      expectedRunLength: raw?.transition?.expectedRunLength ?? null,
      stabilityScore: raw?.transition?.stabilityScore ?? null,
      measured: raw?.transition?.measured ?? false,
    },
    // Consensus is whatever the 5x5 pairwise matrix says. Asserting a fixed 85%
    // agreement across four named models while every matrix cell rendered an em
    // dash was the page contradicting itself in two adjacent panels.
    agreement: raw?.agreement ?? {
      band: 'low',
      agreementScore: null,
      agreeingModels: [],
      conflictingModels: [],
      divergenceSummary: null,
      pairwiseMatrix: null,
      conflicts: [],
    },
    explanation: explanationObj,
    levels: {
      callWall: r.callWall ?? raw?.levels?.callWall ?? null,
      putWall: r.putWall ?? raw?.levels?.putWall ?? null,
      gammaFlip: r.zeroGamma ?? raw?.levels?.gammaFlip ?? null,
      sessionVwap: latestVwap.value ?? raw?.levels?.sessionVwap ?? null,
    },
    quality: {
      // Measurable means "some lens measured something", not "every lens did".
      // The price-only path still has a real Kalman state off real bars, so the
      // label stands; what it lacks is named in missingLenses, and every figure
      // the missing lenses would have produced is already null above.
      measurable: measurable || raw?.quality?.measurable === true || (pt != null && spot != null),
      dataCompleteness: raw?.quality?.dataCompleteness,
      reason: measurable ? null : (r.withheldReason ?? raw?.quality?.reason ?? null),
      missingLenses: measurable ? [] : ['dealer gamma', 'order flow'],
    },
  }
})

const unifiedVerdictText = computed<string>(() => {
  if (verdictText.value) return verdictText.value
  const p = reconciledMarketRegime.value
  const pt = latestStatePoint.value
  const vel = pt?.kalman_velocity ?? 0
  const spot = regimeRead.value.spot ?? effectiveSpot.value
  if (p) {
    const dir = vel >= 0 ? 'upward drift' : 'downward acceleration'
    const spotStr = spot ? ` Spot is $${num(spot, 2)}.` : ''
    return `${p.primaryLabel}: Kinematic momentum is ${dir} with velocity ${vel >= 0 ? '+' : ''}${num(vel, 4)}.${spotStr} Action: ${tacticalBias.value.action}`
  }
  return 'Synthesizing market telemetry from live price action and options flow.'
})

const unifiedPlaybook = computed<PlaybookLine[]>(() => {
  if (playbook.value.length) return playbook.value
  const tb = tacticalBias.value
  const r = regimeRead.value
  const spot = r.spot ?? effectiveSpot.value
  const lines: PlaybookLine[] = []
  lines.push({
    kind: 'stance',
    text: tb.stance,
  })
  lines.push({
    kind: 'trigger',
    text: tb.action,
  })
  if (r.callWall != null) {
    lines.push({
      kind: 'trigger',
      text: `Call Wall at $${num(r.callWall, 2)} acts as primary overhead resistance target.`,
    })
  } else if (spot != null) {
    lines.push({
      kind: 'trigger',
      text: `Key upper resistance level at $${num(spot * 1.01, 2)} (1% upper channel).`,
    })
  }
  if (r.putWall != null) {
    lines.push({
      kind: 'watch',
      text: `Put Wall at $${num(r.putWall, 2)} marks downside dealer support floor.`,
    })
  } else if (spot != null) {
    lines.push({
      kind: 'watch',
      text: `Key support level at $${num(spot * 0.99, 2)} (1% lower channel).`,
    })
  }
  return lines
})

const levelLadder = computed<MergedLevel[]>(() => {
  const spot = regimeRead.value.spot ?? effectiveSpot.value
  if (spot == null || !(spot > 0)) return []
  const pt = latestStatePoint.value
  const em = expectedMove.value
  const h = levelHorizon.value
  return buildLevelLadder({
    spot,
    sigma: h?.sigma ?? null,
    tYears: h?.tYears ?? null,
    em1dDollars: em?.em1dDollars ?? null,
    matrix: flowMatrix.value,
    gamma: {
      callWall: regimeRead.value.callWall,
      putWall: regimeRead.value.putWall,
      zeroGamma: regimeRead.value.zeroGamma,
      pinStrike: regimeRead.value.pinStrike,
    },
    kernel: {
      mean: pt?.nw_mean ?? null,
      upper: pt?.nw_upper ?? null,
      lower: pt?.nw_lower ?? null,
      vwap: latestVwap.value,
    },
    vol: { emHigh: em?.em1dHigh ?? null, emLow: em?.em1dLow ?? null },
  })
})

/** Nearest actionable level each side of spot — what price is leaning on now. */
/**
 * A merged level's price is the cluster centroid, so on a multi-lens level the
 * headline price is nobody's actual level. Spell the members out rather than
 * letting "Call wall $770.17" stand for a call wall at $770.00.
 */
function memberBreakdown(lvl: MergedLevel | null): string | null {
  if (!lvl || lvl.members.length < 2) return null
  return lvl.members.map((m) => `${m.label} ${num(m.price, 2)}`).join(' · ')
}

const nearestAbove = computed<MergedLevel | null>(() => {
  const above = levelLadder.value.filter((l) => l.role === 'resistance')
  return above.length ? above[above.length - 1] : null
})
const nearestBelow = computed<MergedLevel | null>(
  () => levelLadder.value.find((l) => l.role === 'support') ?? null,
)

const fairValue = computed(() => {
  const spot = regimeRead.value.spot ?? effectiveSpot.value
  if (spot == null || !(spot > 0)) return null
  const m = flowMatrix.value
  return fairValueTarget({
    spot,
    poc: m?.poc ?? null,
    vwap: latestVwap.value,
    kernelMean: latestStatePoint.value?.nw_mean ?? null,
    valueAreaLow: m?.val ?? null,
    valueAreaHigh: m?.vah ?? null,
    halfLifeBars: latestStatePoint.value?.ou_half_life ?? null,
    em1dDollars: expectedMove.value?.em1dDollars ?? null,
  })
})

const flowRead = computed(() => orderFlowRead(flowMatrix.value))

/** Bars the OU half-life is measured in, so "3.4" is never bare. */
const barUnit = computed(() => (barsMode.value === '1h' ? 'hours' : 'sessions'))

/**
 * One sentence on where price is trying to go, and whether the flow agrees.
 *
 * Gamma positioning and order flow are allowed to disagree here on purpose:
 * when the dealer surface says damping and the tape says distribution, that
 * conflict IS the read, and averaging them into a single score would erase it.
 */
const meanReversionNote = computed<string | null>(() => {
  const fv = fairValue.value
  if (!fv) return null
  // A single target price off anchors that disagree by more than two expected
  // moves is invented precision. Lead with the range when they do.
  const dirTxt = fv.dispersed
    ? `Fair Value Zone: $${num(fv.zone.low, 2)} to $${num(fv.zone.high, 2)}, ${fv.direction === 'up' ? 'discounted below' : fv.direction === 'down' ? 'extended above' : 'centered at'} spot`
    : fv.direction === 'at'
      ? 'Price is AT fair value'
      : `Price is being pulled ${fv.direction === 'up' ? 'UP toward' : 'DOWN toward'} $${num(fv.target, 2)}`
  const emTxt =
    fv.dispersed || fv.emMultiple == null
      ? ''
      : ` (${num(fv.emMultiple, 2)}× the 1-day expected move away)`
  const hlTxt =
    fv.halfLifeBars != null && fv.halfLifeBars > 0
      ? ` Half the gap typically closes in ~${num(fv.halfLifeBars, 1)} ${barUnit.value}.`
      : ''
  const vaTxt =
    fv.insideValueArea === true
      ? ' Spot is inside the value area (balanced range).'
      : fv.insideValueArea === false
        ? ' Spot is OUTSIDE the value area (price discovery; pull back into value is active).'
        : ''
  const agreeTxt =
    fv.anchors.length > 1
      ? ` ${fv.anchors.length} structural anchors across ${num(fv.spreadPct, 2)}% range.`
      : ' Single anchor benchmark.'
  return `${dirTxt}${emTxt}.${hlTxt}${vaTxt}${agreeTxt}`
})

/* ---- activation --------------------------------------------------------- */

function goLive(): void {
  if (activated.value) return
  activated.value = true
  void optionsRes.refresh()
  void spotRes.refresh()
  void microRegimeRes.refresh()
  void executionGateRes.refresh()
  void marketRegimeRes.refresh()
  void stateRes.refresh()
  void vwapRes.refresh()
  void signalsRes.refresh()
  void absorptionRes.refresh()
  void zeroDteRes.refresh()
  if (activeSection.value === 'setups') {
    void runBacktest()
  }
}

function applySymbol(): void {
  const clean = symbolInput.value.trim().toUpperCase()
  if (!clean) return
  symbolInput.value = clean
  if (clean === symbol.value) return
  symbol.value = clean
  void router.replace({ query: { ...route.query, symbol: clean } })
  if (activated.value) {
    focusStrike.value = null
    void optionsRes.refresh({ clear: true })
    void spotRes.refresh({ clear: true })
    void microRegimeRes.refresh({ clear: true })
    void executionGateRes.refresh({ clear: true })
    void marketRegimeRes.refresh({ clear: true })
    void stateRes.refresh({ clear: true })
    void vwapRes.refresh({ clear: true })
    void signalsRes.refresh({ clear: true })
    void absorptionRes.refresh({ clear: true })
    void zeroDteRes.refresh({ clear: true })
    backtestResult.value = null
    if (activeSection.value === 'setups') {
      void runBacktest()
    }
  }
}

function selectPairSymbol(sym: string): void {
  symbolInput.value = sym
  applySymbol()
}

watch(
  () => route.query.symbol,
  (q) => {
    const next = typeof q === 'string' && q ? q.trim().toUpperCase() : ''
    if (!next || next === symbol.value) return
    symbolInput.value = next
    symbol.value = next
    focusStrike.value = null
    if (activated.value) {
      void optionsRes.refresh({ clear: true })
      void spotRes.refresh({ clear: true })
      void microRegimeRes.refresh({ clear: true })
      void executionGateRes.refresh({ clear: true })
      void marketRegimeRes.refresh({ clear: true })
      void stateRes.refresh({ clear: true })
      void vwapRes.refresh({ clear: true })
      void signalsRes.refresh({ clear: true })
      void absorptionRes.refresh({ clear: true })
      void zeroDteRes.refresh({ clear: true })
      backtestResult.value = null
      if (activeSection.value === 'setups') {
        void runBacktest()
      }
    }
  },
)

watch(
  [activeSection, activated],
  ([sec, isLive]) => {
    if (sec === 'setups' && isLive && !backtestResult.value && !backtestRunning.value) {
      void runBacktest()
    }
  },
  { immediate: false },
)

/* ---- INSTITUTIONAL QUANT WORKSTATION COMPUTEDS ------------------------- */

const dayChangeDollar = computed<number | null>(() => {
  const last = symbolQuoteRow.value?.last
  const prev = symbolQuoteRow.value?.prev_close
  return last != null && prev != null ? last - prev : null
})

const dayChangePct = computed<number | null>(() => {
  return symbolQuoteRow.value?.chg_1d_pct ?? null
})

const totalGexM = computed<number | null>(() => {
  return regimeRead.value.netGammaM ?? optionsRes.data.value?.summary?.total_gex_m ?? null
})

const netFlowM = computed<number | null>(() => {
  // No literal fallback: +312.6M rendered identically to a measured net premium
  // and never changed, so an unmeasured session read as a heavy bullish tape.
  const p = optionsRes.data.value?.summary?.signed_net_premium
  return p != null ? p / 1e6 : null
})

/* HV 20D/30D were never wired to the ribbon, so both pills read "—" forever.
 * `price_series` only carries the few sessions the sparkline draws, so the
 * server derives realised vol from the full local daily history instead. */
const hv20d = computed<number | null>(() => optionsRes.data.value?.summary?.hv_20d ?? null)
const hv30d = computed<number | null>(() => optionsRes.data.value?.summary?.hv_30d ?? null)

/* IV rank and IV percentile both need a trailing IV history, which the options
 * payload does not carry. The ribbon previously showed a pinned `48.2` IV rank
 * for every symbol on every day -- a constant indistinguishable from a reading.
 * Until an IV history is served, these must report absent. */
const ivRank = computed<number | null>(() => null)
const ivPercentile = computed<number | null>(() => null)

const putCallRatio = computed<number | null>(() => {
  const ratio = optionsRes.data.value?.summary?.call_put_ratio
  return ratio != null && ratio !== 0 ? 1 / ratio : null
})

const nextExpiryDate = computed<string | null>(() => slowDerived.value.smile?.expiry ?? null)

/** Calendar days to the observed expiry — previously pinned at the literal 2.
 *
 * Negative is a real and important answer: the chain snapshot's nearest expiry
 * has already passed, which means the board is stale. `Math.max(0, ...)` turned
 * that into "0D" and the desk advertised an expired board as a 0DTE session. */
const nextExpiryDte = computed<number | null>(() => {
  const expiry = nextExpiryDate.value
  if (!expiry) return null
  const target = Date.parse(`${expiry.slice(0, 10)}T00:00:00Z`)
  if (Number.isNaN(target)) return null
  const today = new Date()
  const todayUtc = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate())
  return Math.round((target - todayUtc) / 86_400_000)
})

const strikeOiRows = computed<StrikeOiPoint[]>(() => {
  const rawOi = optionsRes.data.value?.oi_by_strike
  if (rawOi && rawOi.length) {
    return rawOi.map((r) => ({
      strike: r.strike,
      call_oi: r.call_oi,
      put_oi: r.put_oi,
      total_oi: r.total_oi,
    }))
  }
  const strikes = microRegimeRes.data.value?.strikes
  if (strikes && strikes.length) {
    return strikes.map((s) => ({
      strike: s.strike,
      call_oi: s.call_oi,
      put_oi: s.put_oi,
      total_oi: s.call_oi + s.put_oi,
    }))
  }
  // Third source: the GEX-by-strike rows sometimes carry real open interest.
  // Only rows that actually do are usable. The previous version manufactured
  // the missing side with `Math.abs(call_gex_m || 10) * 850` -- an 850x magic
  // multiplier on a gamma number, defaulting to 10 when even that was absent,
  // rendered as a contract count. Open interest is a reported figure; it
  // cannot be derived from gamma exposure, and inventing it put fabricated
  // contract counts on a chart a trader reads as position data.
  const gexStrikes = optionsRes.data.value?.gex_by_strike ?? []
  if (gexStrikes.length) {
    const withRealOi = gexStrikes.filter(
      (g) => typeof g.call_oi === 'number' && typeof g.put_oi === 'number',
    )
    if (withRealOi.length) {
      return withRealOi.map((g) => ({
        strike: g.strike,
        call_oi: g.call_oi as number,
        put_oi: g.put_oi as number,
        total_oi: (g.call_oi as number) + (g.put_oi as number),
      }))
    }
  }
  return []
})

const expiryFlowRows = computed<ExpiryFlowRow[]>(() => {
  const gexExp = optionsRes.data.value?.gex_by_expiry
  if (gexExp && gexExp.length) {
    return gexExp.map((e) => ({
      expiry: e.expiry,
      dte: e.dte,
      bullish_flow_m: Math.max(0, e.call_gex_m),
      bearish_flow_m: Math.max(0, Math.abs(e.put_gex_m)),
      net_flow: e.net_gex_m,
    }))
  }
  // No dealer-gamma-by-expiry on the response means we do not know the
  // expiry flow distribution. This used to return five hardcoded rows --
  // fixed May/June dates and invented $M figures -- which rendered
  // identically to real data in the chart, with nothing on screen to tell a
  // trader that the entire panel was fabricated. NetFlowByExpiryChart draws
  // an empty chart for an empty array by design.
  return []
})

const timeSeriesPoints = computed<TimeSeriesPoint[]>(() => {
  const gexHist = optionsRes.data.value?.gex_history ?? []
  const priceHist = optionsRes.data.value?.price_series ?? []
  if (gexHist.length >= 4) {
    const points: TimeSeriesPoint[] = []
    gexHist.forEach((g, i) => {
      // A price point needs a price. The old `?? 525` put a plausible
      // index-like level on the chart for any symbol whose history was
      // missing -- wrong by an order of magnitude on most tickers and
      // indistinguishable from a real print.
      const p = priceHist[i]?.close ?? effectiveSpot.value
      if (p == null) return
      points.push({
        // gex_history timestamps arrive either as full ISO stamps
        // ("...T14:35:00Z") or as plain dates ("2026-08-29"); slicing a date
        // at offset 11 yields an empty label, so pick the right segment.
        time: g.t ? (g.t.length > 10 ? g.t.slice(11, 16) : g.t.slice(5, 10)) : `T${i}`,
        netGammaM: g.total_gex_m,
        price: p,
        // `volumeDelta` is deliberately omitted. It was `total_gex_m * 25`:
        // a gamma-exposure figure rescaled by a magic constant and labelled
        // as order-flow volume delta. There is no volume-delta series in this
        // repo's data at all (no trades, no aggressor side), so the honest
        // value is absent.
      })
    })
    return points
  }
  return []
})

const liveAlertsList = computed<RegimeAlert[]>(() => {
  const sym = symbol.value
  const r = regimeRead.value
  const clockTime = optionsRes.fetchedAt.value
    ? new Date(optionsRes.fetchedAt.value).toLocaleTimeString([], {
        hour: 'numeric',
        minute: '2-digit',
      })
    : ''
  const alerts: RegimeAlert[] = []

  if (r.side != null && r.zeroGamma != null && r.spot != null) {
    const gammaDesc =
      r.side === 'long'
        ? 'dealer gamma positive'
        : r.side === 'short'
          ? 'dealer gamma negative'
          : 'dealer gamma straddling the flip'
    alerts.push({
      id: 'alert-gex-flip',
      type: 'gex_flip',
      title: 'GEX Flip',
      desc: `${sym} flip at $${num(r.zeroGamma, 0)} · ${gammaDesc}`,
      time: clockTime,
      tone: r.side === 'short' ? 'bearish' : r.side === 'flip' ? 'warn' : 'bullish',
    })
  }

  const tape = optionsRes.data.value?.flow_tape ?? []
  let biggest: OptionsTapeRow | null = null
  for (const rowTape of tape) {
    if (rowTape.premium == null) continue
    if (biggest == null || rowTape.premium > biggest.premium) biggest = rowTape
  }
  if (biggest && biggest.premium > 0 && biggest.strike != null) {
    const biasLabel =
      biggest.bias === 'bullish'
        ? 'Bullish flow'
        : biggest.bias === 'bearish'
          ? 'Bearish flow'
          : 'Flow'
    alerts.push({
      id: 'alert-large-flow',
      type: 'large_flow',
      title: 'Large Flow',
      desc: `${biasLabel}: $${compact(biggest.premium)} in ${sym} ${num(biggest.strike, 0)}${
        biggest.right === 'call' ? 'C' : 'P'
      }`,
      time: biggest.timestamp ? biggest.timestamp.slice(11, 16) : '',
      tone:
        biggest.bias === 'bullish' ? 'bullish' : biggest.bias === 'bearish' ? 'bearish' : 'warn',
    })
  }

  if (r.side != null && r.spot != null && (r.callWall != null || r.putWall != null)) {
    const spot = r.spot
    const walls: Array<{ kind: 'call' | 'put'; level: number }> = []
    if (r.callWall != null) walls.push({ kind: 'call', level: r.callWall })
    if (r.putWall != null) walls.push({ kind: 'put', level: r.putWall })
    walls.sort((a, b) => Math.abs(a.level - spot) - Math.abs(b.level - spot))
    const wall = walls[0]
    const pct = ((wall.level - spot) / spot) * 100
    const dir = pct >= 0 ? 'above' : 'below'
    alerts.push({
      id: 'alert-wall-watch',
      type: 'wall_pin',
      title: 'Wall Watch',
      desc: `${sym} ${wall.kind} wall ${num(wall.level, 2)} ${Math.abs(pct).toFixed(1)}% ${dir} spot`,
      time: clockTime,
      tone: 'warn',
    })
  }

  return alerts
})

/* ---- breadth strip: independent lazy activation ------------------------- */

async function fetchBreadth(): Promise<RegimeBreadthPayload> {
  return api.gammaRegime()
}

const breadthActivated = ref(false)
const breadthRes = useResource<RegimeBreadthPayload>(fetchBreadth, {
  intervalMs: BREADTH_POLL_MS,
  immediate: false,
  enabled: () => breadthActivated.value,
})

function onBreadthActivate(): void {
  if (breadthActivated.value) return
  breadthActivated.value = true
  void breadthRes.refresh()
}
</script>

<template>
  <div class="regime-view">
    <!-- Top Desk Header -->
    <header class="view-header ticked rise">
      <div class="header-top">
        <div>
          <span class="label">05 · Live surface</span>
          <h1>Dealer-Gamma Regime &amp; Microstructure Dynamics</h1>
          <p class="dek">
            Integrating Dealer Greeks, 2-State Kinematic State-Space Filtering, Causal
            Nadaraya-Watson Envelopes, and Systematic Intraday Execution.
          </p>
        </div>

        <!-- Unified Workstation Section Quick-Jump Bar -->
        <div v-if="activated" class="mode-tabs" role="navigation" aria-label="Workstation sections">
          <button
            v-for="sec in SECTIONS"
            :key="sec.id"
            type="button"
            class="tab-btn"
            :class="{ active: activeSection === sec.id }"
            :aria-pressed="activeSection === sec.id"
            @click="setSection(sec.id)"
          >
            {{ sec.label }}
          </button>
        </div>
      </div>

      <div v-if="activated" class="section-guide" aria-live="polite">
        <span class="section-guide-label font-mono">{{ activeSectionGuidance.label }}</span>
        <span class="section-guide-text">{{ activeSectionGuidance.description }}</span>
      </div>

      <!-- Controls & Quick Universe Bar -->
      <div class="controls-line">
        <form class="symbol-form" @submit.prevent="applySymbol">
          <label for="regime-symbol" class="label">Symbol</label>
          <input
            id="regime-symbol"
            v-model="symbolInput"
            class="symbol-input fig font-mono"
            autocomplete="off"
            spellcheck="false"
            maxlength="10"
          />
          <button type="submit" class="apply-btn label">APPLY</button>
        </form>

        <!-- Quick Ticker Chips -->
        <div class="quick-tickers">
          <button
            v-for="sym in QUICK_UNIVERSE"
            :key="sym"
            class="ticker-chip font-mono"
            :class="{ active: symbol === sym }"
            @click="selectPairSymbol(sym)"
          >
            {{ sym }}
          </button>
        </div>

        <!-- Timeframe & Bar Mode Controls -->
        <div v-if="activated" class="timeframe-controls">
          <div class="window-chips">
            <button
              v-for="w in ['1m', '3m', '6m', '1y']"
              :key="w"
              class="win-chip font-mono"
              :class="{ active: lookbackWindow === w }"
              @click="setWindow(w)"
            >
              {{ w.toUpperCase() }}
            </button>
          </div>
          <div class="bars-chips">
            <button
              class="win-chip font-mono"
              :class="{ active: barsMode === 'daily' }"
              @click="setBarsMode('daily')"
            >
              1D
            </button>
            <button
              class="win-chip font-mono"
              :class="{ active: barsMode === '1h' }"
              @click="setBarsMode('1h')"
            >
              1H
            </button>
          </div>
        </div>
      </div>
    </header>

    <!-- Idle Gate before activation -->
    <section v-if="!activated" class="idle-gate" aria-live="polite">
      <p class="idle-copy">
        This workstation queries live option chains, dealer gamma surfaces, causal state estimators,
        and systematic execution models. It stays idle, with no requests and no timers, until you
        start it.
      </p>
      <button type="button" class="go-live-btn" @click="goLive">GO LIVE</button>
      <ol class="idle-sections label" aria-label="Sections that activate">
        <li>Tactical brief</li>
        <li>Levels &amp; flow</li>
        <li>Gamma map</li>
        <li>Dynamics</li>
        <li>Flow tape</li>
        <li>Setups</li>
        <li>Surface</li>
      </ol>
    </section>

    <!-- ACTIVE WORKSTATION BODY -->
    <template v-else>
      <!-- UNIFIED QUANTITATIVE & MICROSTRUCTURE WORKSTATION -->
      <div class="unified-workstation-container">
        <!-- Top Header Ribbon -->
        <RegimeHeaderRibbon
          :symbol="symbol"
          :symbols-list="QUICK_UNIVERSE"
          :spot="regimeRead.spot ?? effectiveSpot"
          :day-change-dollar="dayChangeDollar"
          :day-change-pct="dayChangePct"
          :iv-rank="ivRank"
          :iv-percentile="ivPercentile"
          :hv20d="hv20d"
          :hv30d="hv30d"
          :put-call-ratio="putCallRatio"
          :total-gex-m="totalGexM"
          :net-flow-m="netFlowM"
          :quote-asof="symbolQuoteRow?.asof ?? null"
          :quote-quality="symbolQuoteRow?.quality ?? null"
          :next-expiry-dte="nextExpiryDte"
          :next-expiry-date="nextExpiryDate ? nextExpiryDate.slice(5) : null"
          :regime="isRegimeProcessing ? null : regimeRead.side"
          :custom-regime-label="
            isRegimeProcessing
              ? 'CALIBRATING REGIME…'
              : reconciledMarketRegime?.primaryLabel || tacticalBias.bias || null
          "
          :active-timeframe="
            lookbackWindow === '1d'
              ? '1D'
              : lookbackWindow === '5d'
                ? '5D'
                : lookbackWindow === '1m'
                  ? '1M'
                  : lookbackWindow === '3m'
                    ? '3M'
                    : '1Y'
          "
          :sparkline-points="optionsRes.data.value?.price_series?.map((p) => p.close) ?? []"
          :call-wall="regimeRead.callWall"
          :put-wall="regimeRead.putWall"
          :gamma-flip="regimeRead.zeroGamma"
          :pin-strike="regimeRead.pinStrike"
          :em1d-dollars="expectedMove?.em1dDollars ?? null"
          :em1d-pct="expectedMove?.em1dPct ?? null"
          @select-symbol="selectPairSymbol"
          @select-timeframe="(tf) => setWindow(tf.toLowerCase())"
        />

        <!-- Synchronized Active Calibration Banner for non-tactical sections -->
        <div
          v-if="isRegimeProcessing && activeSection !== 'all' && activeSection !== 'tactical'"
          class="section-calibrating-banner ticked font-mono"
          role="status"
          aria-live="polite"
        >
          <div class="scb-left">
            <span class="processing-pulse" aria-hidden="true" />
            <span class="scb-eyebrow">CALIBRATING MULTI-MODEL REGIME TELEMETRY · {{ symbol }}</span>
            <span class="scb-detail font-sans">
              Pricing live option chains, dealer gamma topography, and causal kinematics…
            </span>
          </div>
          <button type="button" class="scb-jump-btn font-mono" @click="setSection('tactical')">
            VIEW TELEMETRY CONSOLE &rarr;
          </button>
        </div>

        <!-- 1. Executive Tactical Briefing & Multi-Model Regime Workstation -->
        <div
          v-show="activeSection === 'all' || activeSection === 'tactical'"
          id="sec-tactical"
          class="section-container"
        >
          <!-- Processing Skeleton Screen while core regime streams are calibrating -->
          <RegimeSkeletonLoader
            v-if="isRegimeProcessing"
            :symbol="symbol"
            :spot="regimeRead.spot ?? effectiveSpot"
            :options-loading="optionsRes.loading.value && !optionsRes.data.value"
            :regime-loading="marketRegimeRes.loading.value && !marketRegimeRes.data.value"
            :micro-loading="microRegimeRes.loading.value && !microRegimeRes.data.value"
            :state-loading="stateRes.loading.value && !stateRes.data.value"
            :flow-loading="absorptionRes.loading.value && !absorptionRes.data.value"
            :gate-loading="executionGateRes.loading.value && !executionGateRes.data.value"
            :signals-loading="signalsRes.loading.value && !signalsRes.data.value"
            :vwap-loading="vwapRes.loading.value && !vwapRes.data.value"
          />

          <template v-else>
            <section class="tactical-banner ticked" :class="tacticalBias.toneClass">
              <div class="tactical-header">
                <div class="tactical-title-wrap">
                  <span class="tactical-eyebrow font-mono"
                    >EXECUTIVE REGIME TACTICAL BRIEFING · {{ symbol }}</span
                  >
                  <h2 class="tactical-title">{{ tacticalBias.title }}</h2>
                  <span v-if="tacticalBias.provisionalNote" class="tactical-provisional font-mono">
                    {{ tacticalBias.provisionalNote }}
                  </span>
                </div>
                <div class="tactical-bias-badge font-mono" :class="tacticalBias.toneClass">
                  BIAS: {{ tacticalBias.bias }}
                </div>
              </div>

              <div class="tactical-body-grid">
                <div class="tactical-col stance-col">
                  <div class="col-header">
                    <span class="col-label font-mono">MARKET MICROSTRUCTURE STANCE</span>
                    <span class="col-tag font-mono">DEALER DYNAMICS</span>
                  </div>
                  <p class="col-text">{{ tacticalBias.stance }}</p>
                </div>
                <div class="tactical-col action-col">
                  <div class="col-header">
                    <span class="col-label font-mono">ACTIONABLE EXECUTION PLAN</span>
                    <span class="col-tag font-mono action-tag">TACTICAL PLAYBOOK</span>
                  </div>
                  <p class="col-text text-phosphor font-semibold">{{ tacticalBias.action }}</p>
                </div>
              </div>

              <!-- Active Execution Ticket Overlay if present -->
              <div
                v-if="ticketRead"
                class="active-ticket-row"
                :class="[ticketRead.sig.action, { conflicted: !ticketRead.actionable }]"
              >
                <div class="ticket-status-pill font-mono">
                  {{ ticketRead.actionable ? 'ACTIVE TICKET' : 'UNCONFIRMED TICKET' }}:
                  {{ ticketRead.sig.action }} &middot; {{ ticketRead.sig.setup_name }}
                </div>

                <!-- A price-structure ticket pointing the other way from the
                   dealer-gamma read is stated as the disagreement it is. -->
                <p v-if="ticketRead.conflict" class="ticket-conflict font-mono">
                  ⚠ CONFLICTS WITH THE REGIME READ — the briefing above is
                  {{ ticketRead.biasSide === 'long' ? 'bullish' : 'bearish' }}; this ticket is
                  {{ ticketRead.sig.direction }}. It is generated from price and volume structure
                  only (no dealer gamma in history), so treat it as a second opinion, not an order.
                </p>
                <p v-else-if="ticketRead.staleReason" class="ticket-conflict font-mono">
                  ⚠ NOT LIVE — {{ ticketRead.staleReason }}.
                  <template v-if="ticketRead.driftPct != null">
                    Spot has moved {{ ticketRead.driftPct >= 0 ? '+' : ''
                    }}{{ num(ticketRead.driftPct, 1) }}% since the quote.
                  </template>
                </p>

                <div class="ticket-metrics-list">
                  <div>
                    Entry:
                    <span class="font-mono font-bold"
                      >${{ num(ticketRead.sig.entry_price, 2) }}</span
                    >
                  </div>
                  <div>
                    Stop:
                    <span class="font-mono font-bold text-rose"
                      >${{ num(ticketRead.sig.stop_loss, 2) }}</span
                    >
                    <span class="ticket-sub font-mono"
                      >1R ${{ num(ticketRead.riskPerShare, 2) }}</span
                    >
                  </div>
                  <div>
                    Target:
                    <span class="font-mono font-bold text-emerald"
                      >${{ num(ticketRead.sig.take_profit, 2) }}</span
                    >
                    <span class="ticket-sub font-mono"
                      >{{ num(ticketRead.sig.risk_reward, 2) }}R</span
                    >
                  </div>
                  <div>
                    Scale:
                    <span class="font-mono"
                      >${{ num(ticketRead.sig.target_1r, 2) }} / ${{
                        num(ticketRead.sig.target_2r, 2)
                      }}
                      / ${{ num(ticketRead.sig.target_3r, 2) }}</span
                    >
                    <span class="ticket-sub font-mono">1R / 2R / 3R</span>
                  </div>
                  <div>
                    Conviction:
                    <span class="font-mono font-bold"
                      >{{ Math.round(ticketRead.sig.conviction * 100) }}%</span
                    >
                  </div>
                  <div>
                    Size:
                    <span class="font-mono font-bold"
                      >{{ ticketRead.sig.suggested_size_pct }}% capital</span
                    >
                    <span class="ticket-sub font-mono"
                      >risks
                      {{
                        num(
                          (ticketRead.sig.suggested_size_pct * ticketRead.riskPerShare) /
                            Math.max(ticketRead.sig.entry_price, 1e-9),
                          2,
                        )
                      }}% of capital</span
                    >
                  </div>
                </div>

                <!-- Say what the stop is a multiple of. Without this the numbers
                   look chosen; they are 1x a measured bar volatility. -->
                <p class="ticket-basis font-mono">
                  Levels sized off {{ ticketRead.unitLabel }} = ${{
                    num(ticketRead.sig.risk_unit, 2)
                  }}/share &middot; bar {{ ticketRead.sig.timestamp.slice(0, 10) }}
                </p>
              </div>

              <!-- Microstructure Pivot Ladder -->
              <div class="pivot-ladder-strip">
                <span class="ladder-title font-mono">PIVOT LADDER:</span>
                <div class="ladder-pills">
                  <span
                    v-for="p in pivotLadder"
                    :key="p.label"
                    class="ladder-pill font-mono"
                    :class="[p.tone, { 'is-spot': p.tone === 'spot' }]"
                    :title="p.role"
                  >
                    <span v-if="p.tone === 'spot'" class="spot-live-dot" aria-hidden="true" />
                    <span class="p-name">{{ p.label }}</span>
                    <span class="p-price">${{ num(p.price, 2) }}</span>
                    <span
                      v-if="p.tone !== 'spot' && pivotDeltaPct(p.price)"
                      class="p-delta font-mono"
                      :class="
                        p.price >= (regimeRead.spot ?? effectiveSpot ?? 0) ? 'above' : 'below'
                      "
                    >
                      {{ pivotDeltaPct(p.price) }}
                    </span>
                  </span>
                </div>
                <!-- Levels outside the immediate window are noted without evasive wording -->
                <span v-if="missingLevels.length" class="ladder-missing font-mono">
                  outside active window: {{ missingLevels.join(', ') }}
                </span>
              </div>

              <!-- Rule of 16 Expected Move Volatility Strip -->
              <div v-if="expectedMove" class="expected-move-strip">
                <div class="em-item">
                  <span class="em-label font-mono"
                    >1-DAY EXPECTED MOVE ({{
                      expectedMove?.ivBasis === 'vix_proxy' ? 'VIX / 16' : 'ATM IV / 16'
                    }})</span
                  >
                  <span class="em-val font-mono font-bold text-warn">
                    &plusmn;${{ num(expectedMove.em1dDollars, 2) }} (&plusmn;{{
                      num(expectedMove.em1dPct, 1)
                    }}%)
                  </span>
                  <span class="em-sub font-mono text-ink-dim"
                    >[${{ num(expectedMove.em1dLow, 2) }} to ${{
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
                    >[${{ num(expectedMove.em1wLow, 2) }} to ${{
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
                  <!-- `ivAnnualPct` is whatever fed the corridor, which after a
                     VIX fallback IS the VIX. Printing that under an "ATM IV"
                     label reported the index vol as the symbol's own. -->
                  <span class="em-val font-mono text-phosphor font-semibold">
                    VIX {{ vixQuote != null ? num(vixQuote, 1) : DASH }} &middot; ATM IV
                    {{ atmIv != null ? `${num(atmIv > 1.5 ? atmIv : atmIv * 100, 1)}%` : DASH }}
                  </span>
                  <span class="em-sub font-mono text-ink-faint"
                    >EM = S &times; ({{ expectedMove?.ivBasisLabel ?? 'IV / 16' }})</span
                  >
                </div>
              </div>
            </section>

            <!-- Multi-Dimensional Market Regime Workstation Tier (Reconciled Models) -->
            <div class="quant-grid-row tier-1-row">
              <PrimaryRegimeCard
                :payload="reconciledMarketRegime"
                :symbol="symbol"
                :spot="regimeRead.spot ?? effectiveSpot"
                :loading="marketRegimeRes.loading.value"
              />
              <TransitionRiskGauge
                :transition="reconciledMarketRegime?.transition"
                :measurable="reconciledMarketRegime?.quality?.measurable"
              />
            </div>

            <div class="quant-grid-row tier-2-row">
              <FourPillarContextGrid
                :payload="reconciledMarketRegime"
                :loading="marketRegimeRes.loading.value"
              />
            </div>

            <div class="quant-grid-row tier-3-row">
              <ModelAgreementMatrix :agreement="reconciledMarketRegime?.agreement" />
              <DynamicExplanationPanel
                :explanation="reconciledMarketRegime?.explanation"
                :measurable="reconciledMarketRegime?.quality?.measurable"
              />
            </div>
          </template>
        </div>

        <!-- 2. Levels, Probability & Order Flow Map -->
        <div
          v-show="activeSection === 'all' || activeSection === 'levels'"
          id="sec-levels"
          class="section-container"
        >
          <!-- 1b. LEVEL MAP: the page's primary answer, which prices matter,
               how likely each is to be reached, what the tape did there, and
               where the mean is pulling. Placed above the analytics grid because
               it is the read an operator acts on; everything below explains it. -->
          <Panel label="0DTE tape · bars and their magnets" index="00" :live="activated">
            <LoadingState v-if="zeroDteRes.loading.value && !zeroDteRes.data.value" />
            <ZeroDteTape
              v-else
              :payload="zeroDteRes.data.value"
              :loading="zeroDteRes.loading.value"
              @timeframe="setZeroDteTimeframe"
            />
          </Panel>

          <Panel label="Levels · probability · order flow" index="01" :live="activated">
            <template #action>
              <span class="label">
                {{
                  flowMatrix?.available
                    ? `ORDER FLOW ${flowMatrix.window_bars} BARS · ${flowMatrix.bins_used} BINS`
                    : absorptionRes.loading.value
                      ? 'ORDER FLOW LOADING'
                      : 'ORDER FLOW UNAVAILABLE'
                }}
              </span>
            </template>

            <div class="lm-top-grid">
              <!-- Where price is trying to go. First, because it is the question
                 the level ladder exists to answer. -->
              <div v-if="fairValue" class="fv-block" :class="`pull-${fairValue.pull}`">
                <div class="fv-head">
                  <span class="fv-tag font-mono">{{
                    fairValue.dispersed ? 'MEAN ZONE' : 'MEAN TARGET'
                  }}</span>
                  <span v-if="fairValue.dispersed" class="fv-price font-mono font-bold"
                    >${{ num(fairValue.zone.low, 2) }}–${{ num(fairValue.zone.high, 2) }}</span
                  >
                  <span v-else class="fv-price font-mono font-bold"
                    >${{ num(fairValue.target, 2) }}</span
                  >
                  <span v-if="fairValue.dispersed" class="fv-dir font-mono text-ink-dim">
                    ANCHOR SPREAD {{ num(fairValue.spreadPct, 1) }}%
                  </span>
                  <span
                    v-else
                    class="fv-dir font-mono"
                    :class="
                      fairValue.direction === 'up'
                        ? 'text-call-hi'
                        : fairValue.direction === 'down'
                          ? 'text-put-hi'
                          : 'text-ink-dim'
                    "
                  >
                    {{
                      fairValue.direction === 'at'
                        ? 'AT VALUE'
                        : fairValue.direction === 'up'
                          ? '▲ PULL UP'
                          : '▼ PULL DOWN'
                    }}
                    {{ fairValue.distancePct >= 0 ? '+' : '' }}{{ num(fairValue.distancePct, 2) }}%
                  </span>
                </div>
                <p class="fv-note wraps">{{ meanReversionNote }}</p>
                <div class="fv-anchors">
                  <span v-for="a in fairValue.anchors" :key="a.label" class="fv-anchor font-mono">
                    {{ a.label }} <b>${{ num(a.price, 2) }}</b>
                  </span>
                </div>
              </div>
              <p v-else class="unmeasurable-note" role="status">
                No mean target: it needs at least one of the volume point of control, anchored VWAP
                or the causal kernel mean, and none has read yet. A midpoint of spot and a guess is
                not a substitute.
              </p>

              <!-- Order flow read, kept separate from the gamma verdict. -->
              <div v-if="flowRead" class="flow-read" :class="`fr-${flowRead.regime.toLowerCase()}`">
                <div class="fr-head">
                  <span class="fr-tag font-mono">ORDER FLOW</span>
                  <span class="fr-regime font-mono font-bold">{{ flowRead.regime }}</span>
                  <span class="fr-score font-mono">pressure {{ num(flowRead.score, 1) }}</span>
                </div>
                <p class="fr-headline">{{ flowRead.headline }}</p>
                <p class="fr-detail label wraps">{{ flowRead.detail }}</p>
              </div>
              <p v-else class="unmeasurable-note" role="status">
                No order-flow window for {{ symbol }}. The level map below falls back to dealer
                gamma and the kernel alone, and every level is marked as having no flow coverage
                rather than being scored as if it did.
              </p>
            </div>

            <!-- Nearest level each side, with the number that matters. -->
            <div class="near-grid">
              <div class="near-card is-res">
                <span class="near-label font-mono">NEAREST RESISTANCE</span>
                <template v-if="nearestAbove">
                  <span class="near-price font-mono font-bold"
                    >${{ num(nearestAbove.price, 2) }}</span
                  >
                  <span class="near-sub font-mono"
                    >{{ nearestAbove.label }} · +{{ num(nearestAbove.distancePct, 2) }}%</span
                  >
                  <span v-if="memberBreakdown(nearestAbove)" class="near-members font-mono">{{
                    memberBreakdown(nearestAbove)
                  }}</span>
                  <span v-if="nearestAbove.prob" class="near-prob font-mono">
                    {{ Math.round(nearestAbove.prob.touch * 100) }}% touch ·
                    {{ Math.round(nearestAbove.prob.terminal * 100) }}% close beyond
                  </span>
                  <span class="near-ev label wraps">{{ nearestAbove.evidence[0] }}</span>
                </template>
                <span v-else class="near-sub font-mono text-ink-faint"
                  >none measurable above spot</span
                >
              </div>
              <div class="near-card is-sup">
                <span class="near-label font-mono">NEAREST SUPPORT</span>
                <template v-if="nearestBelow">
                  <span class="near-price font-mono font-bold"
                    >${{ num(nearestBelow.price, 2) }}</span
                  >
                  <span class="near-sub font-mono"
                    >{{ nearestBelow.label }} · {{ num(nearestBelow.distancePct, 2) }}%</span
                  >
                  <span v-if="memberBreakdown(nearestBelow)" class="near-members font-mono">{{
                    memberBreakdown(nearestBelow)
                  }}</span>
                  <span v-if="nearestBelow.prob" class="near-prob font-mono">
                    {{ Math.round(nearestBelow.prob.touch * 100) }}% touch ·
                    {{ Math.round(nearestBelow.prob.terminal * 100) }}% close beyond
                  </span>
                  <span class="near-ev label wraps">{{ nearestBelow.evidence[0] }}</span>
                </template>
                <span v-else class="near-sub font-mono text-ink-faint"
                  >none measurable below spot</span
                >
              </div>
            </div>

            <LevelMap
              :levels="levelLadder"
              :spot="regimeRead.spot ?? effectiveSpot"
              :fair-value="fairValue"
              :matrix="flowMatrix"
              :em1d-dollars="expectedMove?.em1dDollars ?? null"
              :horizon-label="levelHorizon?.label ?? null"
            />

            <p v-if="!levelHorizon" class="unmeasurable-note" role="status">
              Touch probabilities are withheld: they need an ATM implied vol from a calibrated smile
              and none has read yet. The levels below still stand, because they are measured rather
              than modelled, but nothing here is sizing how likely price is to reach them.
            </p>
          </Panel>

          <!-- Context Cards: Market Context, Key Levels, Alerts -->
          <div class="quant-grid-row top-row">
            <MarketContextCard
              :symbol="symbol"
              :spot="regimeRead.spot ?? effectiveSpot"
              :vwap="latestVwap"
              :gamma-flip="regimeRead.zeroGamma"
              :call-wall="regimeRead.callWall"
              :put-wall="regimeRead.putWall"
              :regime="regimeRead.side"
              :net-flow-m="netFlowM"
              :kalman-velocity="latestStatePoint?.kalman_velocity"
              :custom-narrative="tacticalBias.stance"
            />
            <KeyLevelsCard
              :spot="regimeRead.spot ?? effectiveSpot"
              :gamma-flip="regimeRead.zeroGamma"
              :max-pain="regimeRead.pinStrike ?? regimeRead.zeroGamma"
              :vwap="latestVwap"
              :resistance="regimeRead.callWall"
              :support="regimeRead.putWall"
            />
            <LiveAlertsPanel
              :symbol="symbol"
              :alerts="liveAlertsList"
              @view-all="setSection('setups')"
            />
          </div>
        </div>

        <!-- 3. Dealer Gamma Topography & Structure -->
        <div
          v-show="activeSection === 'all' || activeSection === 'gamma'"
          id="sec-gamma"
          class="section-container"
        >
          <!-- Dealer gamma map: the surface every level above is read off. -->
          <Panel label="Dealer gamma map" index="G">
            <template #action>
              <span class="label">
                {{
                  microRegimeRes.data.value?.quality?.dealer_convention === 'equity'
                    ? 'EQUITY CONVENTION'
                    : 'INDEX CONVENTION · DEALER LONG CALLS / SHORT PUTS'
                }}
              </span>
            </template>
            <DealerGammaMap
              :profile="microRegimeRes.data.value?.gex_profile ?? []"
              :strikes="microRegimeRes.data.value?.strikes ?? []"
              :quality="microRegimeRes.data.value?.quality ?? null"
              :spot="regimeRead.spot ?? effectiveSpot"
              :zero-gamma="regimeRead.zeroGamma"
              :call-wall="regimeRead.callWall"
              :put-wall="regimeRead.putWall"
              :pin-strike="regimeRead.pinStrike"
              :regime="regimeRead.side"
            />
          </Panel>

          <Panel label="Execution gate · clock, expiry, opening range, routed contract" index="EG">
            <ExecutionGateCard :gate="executionGateRes.data.value" />
          </Panel>

          <!-- 2. Hero 2-Column Analytics Grid: Greeks Flow, Topography, Sector Correlation -->
          <div class="hero-grid">
            <DealerGreeksFlowCard
              :snapshot="microRegimeRes.data.value"
              :spot="regimeRead.spot ?? effectiveSpot"
              :gamma-flip="regimeRead.zeroGamma"
              :call-wall="regimeRead.callWall"
              :put-wall="regimeRead.putWall"
              :pin-strike="regimeRead.pinStrike"
              :net-gamma-at-spot-m="regimeRead.netGammaM"
            />
            <MicrostructureTopographyCard
              :topography="microRegimeRes.data.value?.topography ?? null"
              :spot="regimeRead.spot ?? effectiveSpot"
              :regime="regimeRead.side"
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

          <!-- Strike Gamma Exposure and Open Interest Charts -->
          <div class="quant-grid-row mid-row">
            <StrikeGammaExposureChart
              :rows="optionsRes.data.value?.gex_by_strike ?? []"
              :spot="regimeRead.spot ?? effectiveSpot"
              :total-gex-m="totalGexM"
              :gamma-flip="regimeRead.zeroGamma"
              :call-wall="regimeRead.callWall"
              :put-wall="regimeRead.putWall"
            />
            <StrikeOpenInterestChart
              :rows="strikeOiRows"
              :spot="regimeRead.spot ?? effectiveSpot"
              :expiry-label="slowDerived.smile?.expiry ?? null"
              :call-wall="regimeRead.callWall"
              :put-wall="regimeRead.putWall"
            />
          </div>
        </div>

        <!-- 4. Dual-Pane Synchronized Interactive Visualizers -->
        <div
          v-show="activeSection === 'all' || activeSection === 'dynamics'"
          id="sec-dynamics"
          class="section-container"
        >
          <Panel label="Causal Nadaraya-Watson Envelope & Anchored VWAP">
            <template #action>
              <div class="chart-params">
                <label
                  >h (Bandwidth):
                  <span class="font-mono text-phosphor">{{ bandwidthH }}</span></label
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
              :call-wall="regimeRead.callWall"
              :put-wall="regimeRead.putWall"
              :gamma-flip="regimeRead.zeroGamma"
              :expected-move="expectedMove"
              :live-spot="regimeRead.spot ?? effectiveSpot"
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
                <input
                  v-model.number="kalmanQ"
                  type="range"
                  min="0.00001"
                  max="0.01"
                  step="0.0001"
                />
              </div>
            </template>

            <KalmanKinematicPhasePlot
              v-model:hover-index="chartHoverIndex"
              :points="stateRes.data.value?.points ?? []"
              :breakout-z="breakoutZ"
              :exhaustion-z="exhaustionZ"
            />
          </Panel>
        </div>

        <!-- 5. Real-Time Options Flow & Positioning -->
        <div
          v-show="activeSection === 'all' || activeSection === 'flow'"
          id="sec-flow"
          class="section-container"
        >
          <div class="flow-section-heading">
            <div>
              <span class="flow-section-kicker font-mono">FLOW &amp; POSITIONING</span>
              <h2>Follow the money, then check the hedge</h2>
            </div>
            <p>
              Start with the measured premium split, use the tape to find fresh participation, and
              finish with the dealer response. None of these panels is a trade signal by itself.
            </p>
          </div>

          <!-- Flow Summary Metrics & Positioning Matrix -->
          <div class="quant-grid-row flow-summary-row">
            <FlowSummaryDonutCard
              :total-premium-m="
                optionsRes.data.value?.summary
                  ? (optionsRes.data.value.summary.call_premium +
                      optionsRes.data.value.summary.put_premium) /
                    1e6
                  : null
              "
              :bullish-premium-m="
                optionsRes.data.value?.summary
                  ? optionsRes.data.value.summary.call_premium / 1e6
                  : null
              "
              :bearish-premium-m="
                optionsRes.data.value?.summary
                  ? optionsRes.data.value.summary.put_premium / 1e6
                  : null
              "
              :net-flow-m="netFlowM"
            />
            <NetFlowByExpiryChart :rows="expiryFlowRows" />
            <PositioningSummaryCard
              :regime="regimeRead.side"
              :dealer-bias="microRegimeRes.data.value?.topography?.dealer_hedging_action ?? null"
              :crowd-positioning="
                optionsRes.data.value?.summary?.signed_net_premium != null
                  ? optionsRes.data.value.summary.signed_net_premium >= 0
                    ? 'Bullish'
                    : 'Bearish'
                  : null
              "
              :smart-money-flow="
                totalGexM != null ? (totalGexM >= 0 ? 'Bullish' : 'Bearish') : null
              "
              :net-delta-m="totalGexM"
            />
          </div>

          <!-- Real-Time Institutional Flow Tape & Instantaneous Dealer Hedging -->
          <div class="quant-grid-row flow-tape-row">
            <RealTimeFlowTape
              :symbol="symbol"
              :prints="optionsRes.data.value?.flow_tape ?? []"
              @view-all="router.push('/flow')"
            />
            <InstantaneousHedgingCard
              :snapshot="microRegimeRes.data.value"
              :spot="regimeRead.spot ?? effectiveSpot"
              :net-gamma-m="regimeRead.netGammaM"
            />
          </div>

          <!-- Net Gamma & Spot Price Time Series -->
          <div class="quant-grid-row flow-timeseries-row">
            <NetGammaSpotTimeSeries
              :symbol="symbol"
              :live-spot="regimeRead.spot ?? effectiveSpot"
              :points="timeSeriesPoints"
            />
          </div>
        </div>

        <!-- 6. Bottom Grid: Signals History & Systematic Backtest Engine -->
        <div
          v-show="activeSection === 'all' || activeSection === 'setups'"
          id="sec-setups"
          class="section-container"
        >
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
                      <td colspan="7" class="text-center text-muted">
                        No trigger setups in window
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </Panel>

            <!-- Backtest Tearsheet Panel -->
            <Panel label="Systematic Microstructure Backtester">
              <template #action>
                <button
                  class="btn btn-primary btn-sm"
                  :disabled="backtestRunning"
                  @click="runBacktest"
                >
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
                      >{{ num(backtestResult.win_rate, 1) }}% ({{
                        backtestResult.total_trades
                      }})</span
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
              <div v-else class="backtest-empty-state">
                <p v-if="backtestRunning" class="note pad">
                  Running systematic backtest simulation on historical microstructure signals…
                </p>
                <div v-else class="empty-prompt">
                  <p class="note">No simulation run yet for {{ symbol }}.</p>
                  <p class="note tiny text-muted">
                    Click "Run Simulation" above to evaluate microstructure execution gates, win
                    rates, and regime-segmented P&amp;L attribution.
                  </p>
                </div>
              </div>
            </Panel>
          </div>
        </div>

        <!-- 7. DEALER GAMMA SURFACE & PROBABILITY AUDIT -->
        <div
          v-show="activeSection === 'all' || activeSection === 'surface'"
          id="sec-surface"
          class="section-container"
        >
          <div class="surface-grid">
            <div class="surface-col">
              <RegimeSurfaceChart
                v-if="regimeState"
                v-model:focus-strike="focusStrike"
                :symbol="symbol"
                :gex-by-strike="optionsRes.data.value?.gex_by_strike ?? []"
                :tilted-grid="tiltedResult?.grid ?? null"
                :untilted-grid="slowDerived.riskNeutral?.grid ?? null"
                :density-reliable="!densityUnreliable"
                :state="regimeState"
              />
              <LoadingState v-else-if="optionsRes.loading.value" label="Loading regime surface" />
              <p v-else-if="optionsRes.error.value" class="error-copy" role="alert">
                {{ optionsRes.error.value }}
              </p>
              <p v-else class="label wraps">No regime surface yet for {{ symbol }}.</p>

              <p
                v-if="tiltedResult?.unavailableReason"
                class="unavailable-note label wraps"
                role="status"
              >
                Density unavailable: {{ tiltedResult.unavailableReason }}.
              </p>

              <VolatilitySurface3D
                :symbol="symbol"
                :spot="regimeRead.spot ?? effectiveSpot"
                :horizon-label="probabilityHorizon || '30D'"
              />
            </div>

            <aside class="rail" aria-label="Regime verdict and probabilities">
              <Panel label="Verdict" index="A" :live="activated">
                <p v-if="!regimeState" class="label">Awaiting first read…</p>
                <p
                  v-else-if="regimeState.regime === 'unmeasurable'"
                  class="unmeasurable-note"
                  role="status"
                >
                  Regime not measurable for {{ symbol }}: no open interest observed. Withholding
                  every downstream claim rather than rendering a neutral-looking read.
                </p>
                <p v-else class="verdict-text">{{ unifiedVerdictText }}</p>
              </Panel>

              <Panel
                v-if="regimeState && regimeState.regime !== 'unmeasurable'"
                label="Playbook"
                index="B"
              >
                <ul class="playbook" role="list">
                  <li
                    v-for="(line, i) in playbook.length ? playbook : unifiedPlaybook"
                    :key="i"
                    class="playbook-line"
                    :data-kind="line.kind"
                  >
                    <span class="playbook-tag label">{{ line.kind }}</span>
                    <span class="playbook-text">{{ line.text }}</span>
                  </li>
                </ul>
              </Panel>

              <Panel
                v-if="regimeState && regimeState.regime !== 'unmeasurable'"
                label="Probabilities"
                index="C"
              >
                <!-- Horizon first. Every number below is conditional on it, and
                       the same figure means something entirely different at 0DTE
                       than at 30 days. -->
                <p v-if="probabilityHorizon" class="prob-horizon label wraps">
                  Over <b>{{ probabilityHorizon }}</b>
                  <template v-if="slowDerived.smile?.expiry">
                    · expiry {{ slowDerived.smile.expiry }}</template
                  >
                </p>

                <div v-if="expiryChoices.length > 1" class="expiry-strip">
                  <button
                    class="exp-chip font-mono"
                    :class="{ active: smileExpiry === null }"
                    @click="smileExpiry = null"
                  >
                    NEAREST
                  </button>
                  <button
                    v-for="e in expiryChoices.slice(0, 6)"
                    :key="e.expiry"
                    class="exp-chip font-mono"
                    :class="{ active: smileExpiry === e.expiry }"
                    @click="smileExpiry = e.expiry"
                  >
                    {{ e.dte != null ? `${e.dte}D` : e.expiry }}
                  </button>
                </div>

                <p v-if="smileBlended" class="unmeasurable-note" role="status">
                  This chain payload carries no per-expiry smile, only the surface blended across
                  every expiry. A blended smile is not any traded expiry's, so a density built from
                  it is mostly clipping artifact: no probability is stated rather than one that
                  looks precise and is not.
                </p>
                <p v-else-if="densityUnreliable" class="unmeasurable-note" role="status">
                  Density not usable: {{ pctFrac(withheldMassPct) }} of its mass was negative before
                  clipping, so the shape is artifact rather than a distribution. Usually a put/call
                  step at the money on a very short expiry; try a later expiry above.
                </p>
                <div v-else class="prob-grid">
                  <Readout
                    label="Above call wall"
                    :value="
                      probabilities?.probAboveCallWall != null
                        ? pctFrac(probabilities.probAboveCallWall)
                        : reconciledMarketRegime?.probabilities?.bullish != null
                          ? pctFrac(reconciledMarketRegime.probabilities.bullish)
                          : DASH
                    "
                  />
                  <Readout
                    label="Below put wall"
                    :value="
                      probabilities?.probBelowPutWall != null
                        ? pctFrac(probabilities.probBelowPutWall)
                        : reconciledMarketRegime?.probabilities?.bearish != null
                          ? pctFrac(reconciledMarketRegime.probabilities.bearish)
                          : DASH
                    "
                  />
                  <Readout
                    label="Between walls"
                    :value="
                      probabilities?.probBetweenWalls != null
                        ? pctFrac(probabilities.probBetweenWalls)
                        : reconciledMarketRegime?.probabilities?.neutral != null
                          ? pctFrac(reconciledMarketRegime.probabilities.neutral)
                          : DASH
                    "
                  />
                  <Readout
                    label="Modal target"
                    :value="
                      probabilities?.modalTarget != null
                        ? num(probabilities.modalTarget, 2)
                        : (regimeRead.spot ?? effectiveSpot)
                          ? num(regimeRead.spot ?? effectiveSpot, 2)
                          : DASH
                    "
                  />
                  <Readout
                    label="68% band"
                    :value="
                      probabilities?.band68
                        ? `${num(probabilities.band68.low, 2)} – ${num(probabilities.band68.high, 2)}`
                        : expectedMove
                          ? `$${num(expectedMove.em1dLow, 2)} – $${num(expectedMove.em1dHigh, 2)}`
                          : DASH
                    "
                    wrap
                  />
                </div>
                <p
                  v-if="clippedMassMaterial && !densityUnreliable && !smileBlended"
                  class="clipped-warning"
                  role="alert"
                >
                  {{ pctFrac(withheldMassPct) }} of density mass was negative before clipping; the
                  smile is noisy here, so read these as approximate. They are shown rather than
                  hidden because a labelled approximation beats a blank panel.
                </p>
              </Panel>

              <Panel v-if="tilt" label="Tilt audit" index="D">
                <div class="tilt-grid">
                  <Readout label="lambda" :value="num(tilt.constants.lambda, 3)" size="sm" />
                  <Readout label="kappa" :value="num(tilt.constants.kappa, 3)" size="sm" />
                  <Readout label="vol scale" :value="num(tilt.volScale, 3)" size="sm" />
                  <Readout label="theta" :value="num(tilt.theta, 3)" size="sm" />
                  <Readout label="pin pull" :value="num(tilt.pinPull, 3)" size="sm" />
                </div>
                <p
                  v-if="
                    regimeState &&
                    (regimeState.gammaScaleM != null || regimeState.slopeScaleM != null)
                  "
                  class="scale-note label wraps"
                >
                  Normalized against this symbol's own profile: gamma scale
                  {{ regimeState.gammaScaleM != null ? optGex(regimeState.gammaScaleM) : DASH }},
                  slope scale
                  {{ regimeState.slopeScaleM != null ? optGex(regimeState.slopeScaleM) : DASH }}.
                </p>
              </Panel>

              <ForwardTrajectoryCard
                :symbol="symbol"
                :spot="regimeRead.spot ?? effectiveSpot"
                :regime="regimeRead.side"
                :gamma-flip="regimeRead.zeroGamma"
                :call-wall="regimeRead.callWall"
                :put-wall="regimeRead.putWall"
                :pin-strike="regimeRead.pinStrike"
                :fair-value="fairValue"
                :quadrant-title="microRegimeRes.data.value?.topography?.title"
              />

              <Panel label="Freshness" index="E">
                <p class="label">
                  CHAIN (slow) ·
                  {{ optionsRes.fetchedAt.value ? `${age(optionsRes.fetchedAt.value)} ago` : DASH }}
                </p>
                <p class="label">
                  SPOT (fast) ·
                  {{ spotRes.fetchedAt.value ? `${age(spotRes.fetchedAt.value)} ago` : DASH }}
                </p>
              </Panel>
            </aside>
          </div>

          <!-- Market Gamma Breadth Strip: Full-Width Universe Matrix -->
          <Panel label="Market Gamma Breadth Strip" index="06" flush class="breadth-panel">
            <RegimeBreadthStrip
              :payload="breadthRes.data.value"
              :activated="breadthActivated"
              :loading="breadthRes.loading.value"
              :error="breadthRes.error.value"
              :fetched-at="breadthRes.fetchedAt.value"
              @activate="onBreadthActivate"
            />
          </Panel>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.mode-tabs .tab-btn:focus-visible,
.ticker-chip:focus-visible,
.win-chip:focus-visible,
.apply-btn:focus-visible,
.go-live-btn:focus-visible,
.scb-jump-btn:focus-visible {
  outline: var(--hair) solid var(--phosphor);
  outline-offset: 2px;
  position: relative;
  z-index: 1;
}

.mode-tabs .tab-btn[aria-pressed='true'] {
  box-shadow: inset 0 -2px 0 color-mix(in srgb, var(--phosphor) 70%, white);
}

.mode-tabs .tab-btn {
  line-height: 1.25;
}

.view-header h1 {
  max-width: 25ch;
  font-size: var(--t-view-title);
  line-height: 1.08;
  letter-spacing: var(--track-display);
  text-wrap: balance;
}

.dek {
  font-size: var(--t-reading);
  line-height: 1.5;
}

.signals-table {
  min-width: 38rem;
}

.signals-table tbody tr:hover {
  background: var(--wash-2);
}

.signals-table tbody tr:last-child td {
  border-bottom-color: transparent;
}

.action-pill {
  display: inline-block;
  white-space: nowrap;
}

.kpi-box {
  min-width: 0;
}

.kpi-val {
  overflow-wrap: anywhere;
}

@media (max-width: 700px) {
  .view-header {
    padding: var(--s3);
  }

  .view-header h1 {
    font-size: var(--t-lead);
  }

  .header-top {
    gap: var(--s3);
  }

  .mode-tabs {
    flex: 1 1 100%;
    min-width: 0;
    gap: 0.25rem;
  }

  .mode-tabs .tab-btn {
    min-height: 2.75rem;
    padding-inline: 0.5rem;
  }

  .controls-line {
    gap: var(--s3);
  }

  .timeframe-controls {
    margin-left: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .mode-tabs .tab-btn,
  .ticker-chip,
  .win-chip,
  .apply-btn {
    transition: none;
  }
}

.regime-view {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  min-width: 0;
  width: 100%;
  box-sizing: border-box;
}

.view-header {
  padding: var(--s4);
  border: var(--hair) solid var(--rule);
  background: var(--panel);
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.header-top {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}

.view-header h1 {
  margin-top: 4px;
  color: var(--ink);
  font: 700 var(--t-display) / 1.15 var(--font-display);
}

.dek {
  max-width: 76ch;
  margin-top: var(--s1);
  color: var(--ink-dim);
  font-size: var(--t-small);
}

.mode-tabs {
  display: flex;
  flex-wrap: wrap;
  flex: 1 1 620px;
  min-width: min(100%, 480px);
  max-width: 760px;
  gap: 0.375rem;
  background: var(--panel-hi);
  padding: 0.25rem;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.tab-btn {
  flex: 1 1 0;
  min-width: 0;
  min-height: 2.25rem;
  background: transparent;
  border: none;
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 700;
  padding: 0.375rem 0.75rem;
  border-radius: var(--r-xs);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.section-guide {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding: 0.625rem 0.75rem;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  background: var(--void-lift);
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.45;
}

.section-guide-label {
  flex: 0 0 auto;
  color: var(--phosphor);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.section-guide-text {
  max-width: 92ch;
}

.tab-btn:hover:not(.active) {
  color: var(--ink);
  background: var(--panel-raise);
}

.tab-btn.active {
  background: var(--phosphor);
  color: var(--void);
}

.controls-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1.25rem;
}

.symbol-form {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.symbol-input {
  width: 9ch;
  padding: var(--s1) var(--s2);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
  background: var(--surface-base);
  color: var(--ink);
  font-size: var(--t-body);
  text-transform: uppercase;
}

.apply-btn {
  padding: var(--s1) var(--s3);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
  background: var(--surface-raised);
  color: var(--ink-dim);
  transition:
    color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}

.apply-btn:hover {
  color: var(--ink);
  border-color: var(--phosphor);
}

.quick-tickers {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.ticker-chip,
.win-chip {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-faint);
  border-radius: var(--r-xs);
  color: var(--ink-dim);
  padding: 0.25rem 0.5rem;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.ticker-chip:hover:not(.active),
.win-chip:hover:not(.active) {
  color: var(--ink);
  background: var(--panel-raise);
  border-color: var(--rule-hi);
}

.ticker-chip.active,
.win-chip.active {
  background: var(--phosphor);
  border-color: var(--phosphor);
  color: var(--void);
  font-weight: 700;
}

.timeframe-controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-left: auto;
}

.window-chips,
.bars-chips {
  display: flex;
  gap: 0.25rem;
}

.idle-gate {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--s3);
  padding: var(--s6);
  border: var(--hair) dashed var(--rule-hi);
  border-radius: var(--r-lg);
  background: var(--surface-base);
}

.idle-copy {
  max-width: 60ch;
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.5;
}

/* Names the surfaces the live run will populate, so the idle page reads as
   a staged instrument rather than an empty one. No figures are claimed. */
.idle-sections {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2) var(--s4);
  margin: var(--s2) 0 0;
  padding: 0;
  list-style: none;
}
.idle-sections li {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
  color: var(--ink-faint);
}
.idle-sections li::before {
  content: '';
  width: 7px;
  height: 7px;
  border: var(--hair) solid var(--ink-ghost);
  border-left-color: transparent;
  border-top-color: transparent;
}

.go-live-btn {
  padding: var(--s2) var(--s5);
  border: var(--hair) solid var(--phosphor);
  border-radius: var(--r-sm);
  background: var(--phosphor-wash);
  color: var(--phosphor);
  font-family: var(--font-display);
  font-size: var(--t-small);
  font-weight: 700;
  letter-spacing: 0.06em;
  transition: background var(--dur-fast) var(--ease-out);
  cursor: pointer;
}

.go-live-btn:hover {
  background: var(--phosphor-glow);
}

.microstructure-workstation {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  width: 100%;
}

/* Tactical Intelligence Briefing Banner */
.tactical-banner {
  padding: 1.125rem 1.35rem;
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-1);
  display: flex;
  flex-direction: column;
  gap: 1rem;
  position: relative;
  overflow: visible;
  min-width: 0;
}

.tactical-banner.bullish {
  border-color: var(--call-dim);
}

.tactical-banner.bearish {
  border-color: var(--put-dim);
}

.tactical-banner.squeeze {
  border-color: var(--warn);
}

.tactical-banner.transition {
  border-color: var(--rule-hi);
}

.tactical-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}

/* The briefing is the one block of real prose on the desk, and it was set like
   a data cell: uppercase display strings at default tracking, 13px sentences at
   1.35 leading, columns free to stretch to the full panel width. Uppercase
   needs positive tracking to breathe, and prose needs a measure and leading.
   Both are set explicitly here rather than inherited from the table styles. */
.tactical-eyebrow {
  font-size: var(--t-nano);
  font-weight: 600;
  letter-spacing: 0.16em;
  color: var(--ink-faint);
}

.tactical-title {
  margin: 0.25rem 0 0;
  font-family: var(--font-display);
  font-size: 1.125rem;
  font-weight: 700;
  /* The titles are set uppercase; without tracking the caps collide. */
  letter-spacing: 0.035em;
  line-height: 1.25;
  text-wrap: balance;
  color: var(--ink);
}

.tactical-provisional {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  margin-top: 0.375rem;
  padding: 0.1875rem 0.5rem;
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  color: var(--warn);
  background: var(--warn-wash);
  border: 1px solid var(--warn-dim, var(--rule-hi));
  border-radius: var(--r-sm);
}

.tactical-provisional::before {
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  animation: tactical-pending-pulse 1.6s ease-in-out infinite;
}

@keyframes tactical-pending-pulse {
  0%,
  100% {
    opacity: 0.25;
  }
  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .tactical-provisional::before {
    animation: none;
    opacity: 0.8;
  }
}

.tactical-bias-badge {
  font-size: var(--t-micro);
  font-weight: 700;
  padding: 0.3rem 0.75rem;
  border-radius: var(--r-xs);
  letter-spacing: 0.04em;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
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
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 0.875rem 1.25rem;
  min-width: 0;
}

.tactical-col {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  min-width: 0;
  padding: 0.875rem 1.125rem;
  background: var(--void-lift);
  border: 1px solid var(--rule-faint);
  border-radius: var(--r-sm);
  transition:
    border-color 0.15s ease,
    background-color 0.15s ease;
}

.tactical-col:hover {
  border-color: var(--rule);
}

.tactical-col.action-col {
  background: var(--phosphor-wash);
  border-color: var(--phosphor-dim);
}

.tactical-col.action-col:hover {
  border-color: var(--phosphor);
}

.col-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
}

.col-tag {
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  padding: 1px 6px;
  border-radius: var(--r-xs);
  background: var(--panel-hi);
  color: var(--ink-dim);
  border: 1px solid var(--rule-faint);
}

.col-tag.action-tag {
  background: var(--phosphor-wash);
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  font-weight: 600;
}

.col-label {
  font-size: var(--t-nano);
  font-weight: 600;
  color: var(--ink-faint);
  letter-spacing: var(--track-label);
}

.col-text {
  margin: 0;
  font-family: var(--font-ui);
  font-size: var(--t-body);
  color: var(--ink-dim);
  line-height: 1.55;
  letter-spacing: 0.005em;
  /* Cap the measure so a wide desk does not run a sentence 140 characters
     across the panel. */
  max-width: 64ch;
  text-wrap: pretty;
}

.col-text.text-phosphor {
  color: var(--phosphor, var(--ink));
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
  border-radius: var(--r-sm);
}

.active-ticket-row.conflicted {
  border-style: dashed;
  opacity: 0.92;
}
.ticket-conflict {
  grid-column: 1 / -1;
  margin: 0.35rem 0 0;
  font-size: 0.68rem;
  line-height: 1.45;
  color: var(--warn);
  letter-spacing: 0.02em;
}
.ticket-basis {
  grid-column: 1 / -1;
  margin: 0.4rem 0 0;
  font-size: var(--t-nano);
  color: var(--ink-faint);
  letter-spacing: 0.03em;
}
.ticket-sub {
  margin-left: 0.4rem;
  font-size: var(--t-nano);
  color: var(--ink-faint);
}
.active-ticket-row.ENTER_SHORT {
  border-color: var(--put-dim);
}

.ticket-status-pill {
  font-size: var(--t-micro);
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

.prob-horizon {
  margin-bottom: var(--s2);
  color: var(--ink-dim);
}

.prob-horizon b {
  color: var(--ink);
  font-weight: 600;
}

.expiry-strip {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s1);
  margin-bottom: var(--s3);
}

.exp-chip {
  padding: 2px var(--s2);
  border: var(--hair) solid var(--rule);
  background: transparent;
  color: var(--ink-dim);
  font-size: var(--t-micro);
  cursor: pointer;
}

.exp-chip.active {
  border-color: var(--phosphor);
  color: var(--phosphor);
}

.ladder-missing {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
}

.pivot-ladder-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.625rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--rule-faint);
}

.expected-move-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: var(--void-lift);
  border: 1px solid var(--rule-faint);
  border-radius: var(--r-sm);
}

.em-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.5rem 0.75rem;
  background: var(--panel);
  border: 1px solid var(--rule-faint);
  border-radius: var(--r-xs);
  transition: border-color 0.15s ease;
}

.em-item:hover {
  border-color: var(--rule);
}

.em-label {
  font-size: var(--t-nano);
  color: var(--ink-faint);
  letter-spacing: 0.05em;
  font-weight: 500;
}

.em-val {
  font-size: 0.9375rem;
  color: var(--ink);
  line-height: 1.25;
}

.em-sub {
  font-size: var(--t-nano);
  line-height: 1.35;
  color: var(--ink-dim);
}

.ladder-title {
  font-size: var(--t-nano);
  color: var(--ink-faint);
  letter-spacing: 0.08em;
  font-weight: 600;
}

.ladder-pills {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.375rem;
}

.ladder-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.2rem 0.55rem;
  border-radius: var(--r-xs);
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  font-size: var(--t-micro);
  transition:
    border-color 0.1s ease,
    transform 0.1s ease;
}

.ladder-pill:hover {
  border-color: var(--rule-hi);
}

.ladder-pill.spot,
.ladder-pill.is-spot {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
  color: var(--phosphor);
  font-weight: 700;
}

.spot-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--phosphor);
  animation: spot-live-pulse 1.8s ease-in-out infinite;
}

@keyframes spot-live-pulse {
  0%,
  100% {
    opacity: 0.35;
    transform: scale(0.9);
  }
  50% {
    opacity: 1;
    transform: scale(1.2);
  }
}

.ladder-pill.call {
  background: var(--call-wash);
  border-color: var(--call-dim);
  color: var(--call-hi);
}

.ladder-pill.put {
  background: var(--put-wash);
  border-color: var(--put-dim);
  color: var(--put-hi);
}

.ladder-pill.warn {
  background: var(--warn-wash);
  border-color: var(--warn);
  color: var(--warn);
}

.ladder-pill.phosphor {
  background: var(--phosphor-wash);
  border-color: var(--phosphor-dim);
  color: var(--phosphor);
}

.p-name {
  font-size: var(--t-nano);
  letter-spacing: 0.04em;
  opacity: 0.85;
}

.p-price {
  font-weight: 700;
}

.p-delta {
  font-size: var(--t-nano);
  font-weight: 600;
  padding: 0 3px;
  border-radius: 2px;
  line-height: 1.2;
}

.p-delta.above {
  color: var(--call-hi);
  background: var(--call-wash);
}

.p-delta.below {
  color: var(--put-hi);
  background: var(--put-wash);
}

.hero-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s3);
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
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s3);
}

/* Both panels stretch to one row height; let each side's table rows absorb
   the slack instead of leaving a dead band under the shorter table. */
.table-wrap,
.backtest-summary,
.regime-table-wrap {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.table-wrap {
  overflow-x: auto;
}

.signals-table,
.regime-perf-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-tiny);
  font-variant-numeric: tabular-nums;
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
  font-size: var(--t-micro);
}

.action-pill {
  font-size: var(--t-micro);
  font-weight: 700;
  padding: 0.15rem 0.35rem;
  border-radius: var(--r-sm);
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
  border-radius: var(--r-sm);
  padding: 0.625rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.kpi-label {
  font-size: var(--t-nano);
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
  border-radius: var(--r-sm);
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
  font-size: var(--t-micro);
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

.surface-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: var(--s4);
  align-items: stretch;
  min-width: 0;
}

@media (max-width: 1024px) {
  .hero-grid,
  .bottom-grid,
  .surface-grid,
  .tactical-body-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 700px) {
  .mode-tabs {
    min-width: 100%;
    max-width: none;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .section-guide {
    align-items: flex-start;
    flex-direction: column;
    gap: 0.25rem;
  }
}

.surface-col {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  min-height: 480px;
  min-width: 0;
}

/* The verdict rail sets the row height; the trailing chart card absorbs the
   difference instead of stranding it as a void above the breadth strip. The
   first child is held to content height: its internal chart measures its own
   host, and a stretched height:100% chain there feeds back into the observer
   and inflates the svg without bound. */
.surface-col > :first-child {
  height: auto;
}

.surface-col > :last-child {
  flex: 1 1 auto;
}

.error-copy {
  color: var(--short);
}

.unavailable-note {
  color: var(--warn);
}

.rail {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  min-width: 0;
}

.verdict-text {
  color: var(--ink);
  font-size: var(--t-small);
  line-height: 1.5;
}

.playbook {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.playbook-line {
  display: flex;
  align-items: baseline;
  gap: var(--s2);
}

.playbook-tag {
  flex: 0 0 auto;
  min-width: 52px;
  color: var(--ink-faint);
  text-transform: uppercase;
}

.playbook-line[data-kind='stance'] .playbook-tag {
  color: var(--phosphor);
}

.playbook-line[data-kind='trigger'] .playbook-tag {
  color: var(--warn);
}

.playbook-text {
  color: var(--ink);
  font-size: var(--t-small);
  line-height: 1.5;
}

.unmeasurable-note {
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.5;
}

.prob-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s3);
}

.tilt-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s3);
}

.clipped-warning {
  margin-top: var(--s3);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--warn);
  border-radius: var(--r-sm);
  background: var(--warn-wash);
  color: var(--warn);
  font-size: var(--t-micro);
  line-height: 1.5;
}

.scale-note {
  margin-top: var(--s3);
  color: var(--ink-faint);
}

.breadth-panel {
  min-width: 0;
  width: 100%;
}

@media (prefers-reduced-motion: reduce) {
  .apply-btn,
  .go-live-btn {
    transition: none;
  }
}

/* ---- level map panel: mean target, order-flow read, nearest levels ------ */
.lm-top-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 8px;
  align-items: start;
  margin-bottom: 10px;
}
.lm-top-grid > .fv-block,
.lm-top-grid > .flow-read,
.lm-top-grid > .unmeasurable-note {
  margin-bottom: 0;
  height: 100%;
}
.fv-block {
  border: 1px solid var(--rule);
  border-left-color: var(--ink-faint);
  background: var(--panel-raise);
  padding: 10px 12px;
  margin-bottom: 10px;
}
.fv-block.pull-strong {
  border-left-color: var(--warn);
}
.fv-block.pull-moderate {
  border-left-color: var(--phosphor-dim);
}
.fv-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}
.fv-tag,
.fr-tag {
  font-size: var(--t-nano);
  letter-spacing: 0.1em;
  color: var(--ink-faint);
}
.fv-price {
  font-size: 1.15rem;
  color: var(--ink);
}
.fv-dir {
  font-size: 0.74rem;
}
.fv-note {
  margin: 6px 0 0;
  font-size: 0.76rem;
  line-height: 1.55;
  color: var(--ink-soft);
}
.fv-anchors {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.fv-anchor {
  font-size: 0.66rem;
  color: var(--ink-dim);
  border: 1px solid var(--rule);
  padding: 2px 7px;
}
.fv-anchor b {
  color: var(--ink-soft);
}
.flow-read {
  border: 1px solid var(--rule);
  border-left-color: var(--ink-faint);
  background: var(--panel-raise);
  padding: 10px 12px;
  margin-bottom: 10px;
}
.flow-read.fr-accum {
  border-left-color: var(--call);
}
.flow-read.fr-distrib {
  border-left-color: var(--put);
}
.flow-read.fr-balanced {
  border-left-color: var(--phosphor-dim);
}
.fr-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}
.fr-regime {
  font-size: 0.9rem;
  color: var(--ink);
  letter-spacing: 0.06em;
}
.fr-score {
  font-size: 0.68rem;
  color: var(--ink-faint);
}
.fr-headline {
  margin: 5px 0 0;
  font-size: 0.8rem;
  color: var(--ink-soft);
}
.fr-detail {
  margin: 4px 0 0;
  line-height: 1.5;
  color: var(--ink-faint);
}
.near-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}
.near-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid var(--rule);
  border-top-width: 2px;
  background: var(--panel-raise);
  padding: 9px 11px;
}
.near-card.is-res {
  border-top-color: var(--put-dim);
}
.near-card.is-sup {
  border-top-color: var(--call-dim);
}
.near-label {
  font-size: var(--t-nano);
  letter-spacing: 0.1em;
  color: var(--ink-faint);
}
.near-price {
  font-size: 1.05rem;
  color: var(--ink);
}
.near-sub {
  font-size: 0.68rem;
  color: var(--ink-dim);
}
.near-members {
  font-size: 0.66rem;
  color: var(--ink-faint);
}
.near-prob {
  font-size: 0.7rem;
  color: var(--phosphor);
}
.near-ev {
  margin-top: 3px;
  line-height: 1.45;
  color: var(--ink-faint);
}

/* ---- Institutional Quant Workstation Grid ------------------------------- */
.unified-workstation-container,
.quant-workstation-container {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  width: 100%;
  min-width: 0;
}

.section-container {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  width: 100%;
  min-width: 0;
  padding-bottom: var(--s3);
}

.quant-grid-row {
  display: grid;
  gap: 1rem;
  width: 100%;
}

.quant-grid-row.tier-1-row {
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  align-items: stretch;
}

.quant-grid-row.tier-2-row {
  grid-template-columns: minmax(0, 1fr);
}

.quant-grid-row.tier-3-row {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: stretch;
}

.quant-grid-row.top-row {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: stretch;
}

.quant-grid-row.mid-row {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: stretch;
}

.quant-grid-row.lower-row {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  align-items: stretch;
}

.quant-grid-row.flow-summary-row {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: stretch;
}

.quant-grid-row.flow-tape-row {
  grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr);
  align-items: stretch;
}

.quant-grid-row.flow-timeseries-row {
  grid-template-columns: 1fr;
}

.flow-section-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1.5rem;
  padding: 0 0.25rem 0.25rem;
  border-bottom: 1px solid var(--rule-faint);
}

.flow-section-kicker {
  color: var(--phosphor);
  font-size: var(--t-nano);
  letter-spacing: 0.12em;
}

.flow-section-heading h2 {
  margin: 0.3rem 0 0;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 1.15rem;
  line-height: 1.2;
}

.flow-section-heading p {
  max-width: 58ch;
  margin: 0;
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.45;
}

.quant-grid-row.bottom-row {
  grid-template-columns: minmax(0, 2fr) minmax(0, 1.2fr);
  align-items: stretch;
}

@media (max-width: 1380px) {
  .quant-grid-row.tier-1-row,
  .quant-grid-row.tier-3-row {
    grid-template-columns: 1fr;
  }
  .quant-grid-row.top-row {
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  }
  .quant-grid-row.flow-summary-row {
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  }
  .quant-grid-row.flow-tape-row {
    grid-template-columns: 1fr;
  }
  .quant-grid-row.mid-row,
  .quant-grid-row.lower-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .quant-grid-row.bottom-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .quant-grid-row.top-row,
  .quant-grid-row.mid-row,
  .quant-grid-row.lower-row,
  .quant-grid-row.flow-summary-row,
  .quant-grid-row.flow-tape-row {
    grid-template-columns: 1fr;
  }

  .flow-section-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 0.5rem;
  }
}

.section-calibrating-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-left: 3px solid var(--phosphor);
  padding: var(--s2) var(--s4);
  animation: sk-fade-in 200ms ease-out;
  margin-bottom: var(--s3);
}

.scb-left {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
}

.scb-eyebrow {
  color: var(--phosphor);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.1em;
}

.scb-detail {
  color: var(--ink-dim);
  font-size: var(--t-nano);
}

.scb-jump-btn {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  color: var(--phosphor);
  font-size: var(--t-nano);
  font-weight: 700;
  padding: 3px 8px;
  cursor: pointer;
  letter-spacing: 0.06em;
  transition: all 150ms ease;
  white-space: nowrap;
}

.scb-jump-btn:hover {
  background: var(--phosphor);
  color: var(--void);
}
</style>
