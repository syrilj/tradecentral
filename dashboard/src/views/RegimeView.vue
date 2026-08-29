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
import { computed, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type OptionsIntelligence } from '@/api'
import { useResource } from '@/composables/useResource'
import { age, num, optGex, optSigned, pctFrac, DASH } from '@/format'
import type {
  RegimeBreadthPayload,
  RegimeProbabilities,
  RegimeState,
  RiskNeutralResult,
  Smile,
  TiltParams,
} from '@/regimeContracts'
import type {
  MicrostructureRegimeSnapshot,
  StateEstimationPayload,
  AnchoredVwapPayload,
  SystematicSignalsPayload,
  BacktestTearsheet,
} from '@/microstructureContracts'
import { buildRegimeState } from '@/gammaRegime'
import { availableSmileExpiries, buildSmile, riskNeutralDensity } from '@/riskNeutralDensity'
import { applyTilt, deriveTilt, regimeProbabilities } from '@/gammaTilt'
import {
  computeRuleOf16ExpectedMove,
  assessMoveExcursion,
  assessWallAlignment,
  type ExpectedMoveMetrics,
} from '@/expectedMove'

import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import LoadingState from '@/components/LoadingState.vue'
import RegimeSurfaceChart from '@/components/RegimeSurfaceChart.vue'
import RegimeBreadthStrip from '@/components/RegimeBreadthStrip.vue'
import MicrostructureTopographyCard from '@/components/MicrostructureTopographyCard.vue'
import DealerGammaMap from '@/components/DealerGammaMap.vue'
import DealerGreeksFlowCard from '@/components/DealerGreeksFlowCard.vue'
import SectorPairCorrelationCard from '@/components/SectorPairCorrelationCard.vue'
import CausalEnvelopeChart from '@/components/CausalEnvelopeChart.vue'
import KalmanKinematicPhasePlot from '@/components/KalmanKinematicPhasePlot.vue'

const SLOW_POLL_MS = 75_000
const FAST_POLL_MS = 3_000
const BREADTH_POLL_MS = 75_000

const route = useRoute()
const router = useRouter()

const initialSymbol = (typeof route.query.symbol === 'string' && route.query.symbol ? route.query.symbol : 'SPY').toUpperCase()
const symbolInput = ref(initialSymbol)
const symbol = ref(initialSymbol)

/** The one gate the whole page hangs off. Nothing below fetches until this
 *  flips true — see the module doc for why. */
const activated = ref(false)
const focusStrike = ref<number | null>(null)
const activeTab = ref<'microstructure' | 'surface'>('microstructure')

// Shared multi-pane chart hover tracking
const chartHoverIndex = ref<number | null>(null)

// Microstructure execution parameters
const window = ref('1y')
const bandwidthH = ref(20.0)
const envelopeAlpha = ref(2.0)
const kalmanQ = ref(0.001)
const breakoutZ = ref(1.6)
const exhaustionZ = ref(0.4)
const barsMode = ref<'daily' | '1h'>('daily')

/* ---- SLOW clock: option chain / smile / risk-neutral density ----------- */

const optionsRes = useResource<OptionsIntelligence>(() => api.options({ symbol: symbol.value }), {
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

/** Rule of 16 Expected Move Metrics (1D, 1W, 1M) */
const expectedMove = computed<ExpectedMoveMetrics | null>(() => {
  const spot = effectiveSpot.value ?? microRegimeRes.data.value?.spot ?? null
  const iv = atmIv.value
  return computeRuleOf16ExpectedMove(spot, iv, vixQuote.value ?? 18.0)
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
    return `Short gamma — dealer hedging amplifies moves. ${distTxt} below the zero-gamma flip.`
  if (s.regime === 'long')
    return `Long gamma — dealer hedging dampens moves. ${distTxt} above the zero-gamma flip.`
  return `Straddling the zero-gamma flip (${distTxt} away) — regime not yet established either way.`
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
      text: 'Short-gamma tape — dealer hedging sells weakness and buys strength, so moves extend instead of reverting. Trade with momentum and give positions room; mean-reversion entries and short premium fight the dominant flow.',
    })
  } else if (s.regime === 'long') {
    out.push({
      kind: 'stance',
      text: 'Long-gamma tape — dealer hedging sells strength and buys weakness, so extensions fade and price gravitates to heavy open interest. Fading moves into the walls has the flow behind it; breakout bets fight it.',
    })
  } else {
    out.push({
      kind: 'stance',
      text: `Inside the zero-gamma band${distTxt ? ` (${distTxt} from the flip)` : ''} — the regime is genuinely undecided and this surface gives no directional edge. The tradeable events are the boundary breaks listed below; until one fires, this is a wait, not a position.`,
    })
  }

  if (s.zeroGamma != null && s.regime === 'short') {
    out.push({
      kind: 'trigger',
      text: `Reclaim ${lvl(s.zeroGamma)} (flip) and hedging flips back to dampening — that is the squeeze back up and the point to stop pressing shorts.`,
    })
  } else if (s.zeroGamma != null) {
    out.push({
      kind: 'trigger',
      text: `Lose ${lvl(s.zeroGamma)} (flip) and damping becomes amplification — below it, downside moves feed on dealer supply instead of meeting it.`,
    })
  }
  if (s.callWall != null) {
    out.push({
      kind: 'trigger',
      text: `Above ${lvl(s.callWall)} (call wall) dealers run out of upside gamma — breaks through it can gap, not grind.`,
    })
  }
  if (s.putWall != null) {
    out.push({
      kind: 'trigger',
      text: `Below ${lvl(s.putWall)} (put wall) the dealer put inventory cushioning declines is gone — downside accelerates once it gives.`,
    })
  }
  if (s.regime === 'long' && s.pinStrike != null) {
    out.push({
      kind: 'watch',
      text: `Pin gravity toward ${lvl(s.pinStrike)} strengthens into the close as charm decays — expect price to stall near it late in the session.`,
    })
  }
  if (densityUnreliable.value) {
    out.push({
      kind: 'watch',
      text: 'Probabilities are withheld today (noisy smile), so the direction and trigger levels above stand but nothing here sizes a move — treat conviction as unquantified.',
    })
  }
  return out
})

/* ---- MICROSTRUCTURE QUANT WORKSTATION RESOURCES ---------------------- */

const microRegimeRes = useResource<MicrostructureRegimeSnapshot>(
  () => api.microstructureRegime(symbol.value),
  { intervalMs: 30_000, immediate: false, enabled: () => activated.value },
)

const stateRes = useResource<StateEstimationPayload>(
  () =>
    api.stateEstimation(symbol.value, {
      window: window.value,
      h: bandwidthH.value,
      alpha: envelopeAlpha.value,
      q: kalmanQ.value,
      bars: barsMode.value,
    }),
  { intervalMs: 60_000, immediate: false, enabled: () => activated.value },
)

const vwapRes = useResource<AnchoredVwapPayload>(
  () => api.anchoredVwap(symbol.value, { window: window.value, bars: barsMode.value }),
  { intervalMs: 60_000, immediate: false, enabled: () => activated.value },
)

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
  { intervalMs: 30_000, immediate: false, enabled: () => activated.value },
)

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

const tacticalBias = computed(() => {
  const r = regimeRead.value
  const vel = latestStatePoint.value?.kalman_velocity ?? 0

  if (r.side == null) {
    return {
      title: 'REGIME WITHHELD',
      bias: 'NO READ',
      toneClass: 'neutral',
      stance: `No dealer-gamma surface is measurable right now — ${r.withheldReason}.`,
      action:
        'This surface contributes nothing to a decision until a chain reads. Do not infer a neutral tape from a blank one.',
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
          bias: 'RANGE-BOUND / UPWARD DRIFT',
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
            'Fade envelope extremes back to the kernel mean; take profit quickly — the same damping that gives the entry caps the target.',
        }
  }

  if (r.side === 'short') {
    return vel <= 0
      ? {
          title: 'SHORT GAMMA · DOWNSIDE AMPLIFICATION',
          bias: 'BEARISH',
          toneClass: 'bearish',
          stance:
            'Dealers are short gamma: hedging sells into weakness, so down moves feed on dealer supply instead of meeting it. Velocity is negative and aligned with that flow.',
          action: hasFlip
            ? 'Sell rallies that fail beneath the flip; size down and widen stops — realized vol expands in this regime.'
            : 'Sell rallies that fail at the upper envelope; size down and widen stops — realized vol expands in this regime.',
        }
      : {
          title: 'SHORT GAMMA · SQUEEZE EXPANSION',
          bias: 'SHORT SQUEEZE',
          toneClass: 'squeeze',
          stance:
            'Dealers are short gamma while velocity has turned up, so the same hedging that accelerated the decline now forces buying into the rally.',
          action: hasFlip
            ? 'Momentum long with a trailing stop at the flip — the squeeze ends where hedging flips back to damping.'
            : 'Momentum long with a trailing stop at the kernel mean; no flip level is measurable to anchor the exit.',
        }
  }

  return {
    title: 'STRADDLING THE ZERO-GAMMA FLIP',
    bias: 'BREAKOUT WATCH',
    toneClass: 'transition',
    stance:
      'Net dealer gamma is inside the neutral band around the flip. The regime is genuinely undecided, and this surface gives no directional edge until it resolves.',
    action:
      'Wait. The tradeable event is the boundary break — above the call wall or below the put wall — not a position taken inside the band.',
  }
})

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
      ? [{ label: '+1D EM (VIX/16)', price: em.em1dHigh, role: 'Rule of 16 upper 1σ', tone: 'warn' }]
      : []),
    ...(pt
      ? [{ label: 'UPPER ENVELOPE', price: pt.nw_upper, role: 'Causal NW +ασ band', tone: 'call' }]
      : []),
    { label: 'SPOT PRICE', price: spot > 0 ? spot : null, role: 'Current underlying', tone: 'spot' },
    ...(pt
      ? [{ label: 'KERNEL MEAN m(t)', price: pt.nw_mean, role: 'Latent equilibrium', tone: 'phosphor' }]
      : []),
    { label: 'PIN', price: r.pinStrike, role: 'Peak |net GEX| strike', tone: 'phosphor' },
    { label: 'GAMMA FLIP S*', price: r.zeroGamma, role: 'Regime boundary', tone: 'warn' },
    ...(pt
      ? [{ label: 'LOWER ENVELOPE', price: pt.nw_lower, role: 'Causal NW −ασ band', tone: 'put' }]
      : []),
    ...(em
      ? [{ label: '-1D EM (VIX/16)', price: em.em1dLow, role: 'Rule of 16 lower 1σ', tone: 'warn' }]
      : []),
    { label: 'PUT WALL', price: r.putWall, role: 'Heaviest put gamma below spot', tone: 'put' },
  ]

  return list
    .filter((x): x is { label: string; price: number; role: string; tone: string } =>
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

/* ---- activation --------------------------------------------------------- */

function goLive(): void {
  if (activated.value) return
  activated.value = true
  void optionsRes.refresh()
  void spotRes.refresh()
  void microRegimeRes.refresh()
  void stateRes.refresh()
  void vwapRes.refresh()
  void signalsRes.refresh()
  void runBacktest()
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
    void stateRes.refresh({ clear: true })
    void vwapRes.refresh({ clear: true })
    void signalsRes.refresh({ clear: true })
    void runBacktest()
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
      void stateRes.refresh({ clear: true })
      void vwapRes.refresh({ clear: true })
      void signalsRes.refresh({ clear: true })
      void runBacktest()
    }
  },
)

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

        <!-- Mode Switcher Tabs -->
        <div v-if="activated" class="mode-tabs">
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'microstructure' }"
            @click="activeTab = 'microstructure'"
          >
            MICROSTRUCTURE WORKSTATION
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'surface' }"
            @click="activeTab = 'surface'"
          >
            DEALER GAMMA SURFACE
          </button>
        </div>
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
            v-for="sym in ['SPY', 'QQQ', 'IWM', 'DIA', 'NVDA', 'TSLA', 'AAPL', 'MSFT']"
            :key="sym"
            class="ticker-chip font-mono"
            :class="{ active: symbol === sym }"
            @click="
              symbolInput = sym;
              applySymbol();
            "
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
              :class="{ active: window === w }"
              @click="
                window = w;
                void stateRes.refresh();
                void signalsRes.refresh();
              "
            >
              {{ w.toUpperCase() }}
            </button>
          </div>
          <div class="bars-chips">
            <button
              class="win-chip font-mono"
              :class="{ active: barsMode === 'daily' }"
              @click="
                barsMode = 'daily';
                void stateRes.refresh();
                void signalsRes.refresh();
              "
            >
              1D
            </button>
            <button
              class="win-chip font-mono"
              :class="{ active: barsMode === '1h' }"
              @click="
                barsMode = '1h';
                void stateRes.refresh();
                void signalsRes.refresh();
              "
            >
              1H
            </button>
          </div>
        </div>
      </div>
    </header>

    <!-- Market Gamma Breadth Strip (Always Accessible) -->
    <Panel label="Breadth" index="06" flush class="breadth-panel">
      <RegimeBreadthStrip
        :payload="breadthRes.data.value"
        :activated="breadthActivated"
        :loading="breadthRes.loading.value"
        :error="breadthRes.error.value"
        :fetched-at="breadthRes.fetchedAt.value"
        @activate="onBreadthActivate"
      />
    </Panel>

    <!-- Idle Gate before activation -->
    <section v-if="!activated" class="idle-gate" aria-live="polite">
      <p class="idle-copy">
        This workstation queries live option chains, dealer gamma surfaces, causal state estimators,
        and systematic execution models. It stays idle — no requests, no timers — until you start
        it.
      </p>
      <button type="button" class="go-live-btn" @click="goLive">GO LIVE</button>
    </section>

    <!-- ACTIVE WORKSTATION BODY -->
    <template v-else>
      <!-- TAB 1: FULL MICROSTRUCTURE EXECUTION WORKSTATION -->
      <div v-if="activeTab === 'microstructure'" class="microstructure-workstation">
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
            <!-- Levels that could not be measured are named, not silently
                 omitted: a shorter ladder otherwise looks like a complete one. -->
            <span v-if="missingLevels.length" class="ladder-missing font-mono">
              not measurable: {{ missingLevels.join(', ') }}
            </span>
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

        <!-- 2. Hero 2-Column Analytics Grid: Greeks Flow, Topography, Sector Correlation -->
        <div class="hero-grid">
          <DealerGreeksFlowCard :snapshot="microRegimeRes.data.value" />
          <MicrostructureTopographyCard
            :topography="microRegimeRes.data.value?.topography ?? null"
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

        <!-- Dealer gamma map: the surface every level above is read off.
             The endpoint has always computed this; until now nothing drew it,
             so the page asserted a flip and two walls with no way to see
             whether the curve behind them supported the claim. -->
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
            :spot="regimeRead.spot"
            :zero-gamma="regimeRead.zeroGamma"
            :call-wall="regimeRead.callWall"
            :put-wall="regimeRead.putWall"
            :pin-strike="regimeRead.pinStrike"
          />
        </Panel>

        <!-- 3. Dual-Pane Synchronized Interactive Visualizers -->
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
            :call-wall="regimeRead.callWall"
            :put-wall="regimeRead.putWall"
            :gamma-flip="regimeRead.zeroGamma"
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

        <!-- 4. Bottom Grid: Signals History & Systematic Backtest Engine -->
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
          </Panel>
        </div>
      </div>

      <!-- TAB 2: DEALER GAMMA SURFACE & PROBABILITY AUDIT -->
      <div v-else class="surface-grid">
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
            Density unavailable — {{ tiltedResult.unavailableReason }}.
          </p>
        </div>

        <aside class="rail" aria-label="Regime verdict and probabilities">
          <Panel label="Verdict" index="A" :live="activated">
            <p v-if="!regimeState" class="label">Awaiting first read…</p>
            <p
              v-else-if="regimeState.regime === 'unmeasurable'"
              class="unmeasurable-note"
              role="status"
            >
              Regime not measurable for {{ symbol }} — no open interest observed. Withholding every
              downstream claim rather than rendering a neutral-looking read.
            </p>
            <p v-else class="verdict-text">{{ verdictText }}</p>
          </Panel>

          <Panel
            v-if="regimeState && regimeState.regime !== 'unmeasurable' && playbook.length"
            label="Playbook"
            index="B"
          >
            <ul class="playbook" role="list">
              <li
                v-for="(line, i) in playbook"
                :key="i"
                class="playbook-line"
                :data-kind="line.kind"
              >
                <span class="playbook-tag label">{{ line.kind }}</span>
                <span class="playbook-text">{{ line.text }}</span>
              </li>
            </ul>
          </Panel>

          <Panel v-if="regimeState && regimeState.regime !== 'unmeasurable'" label="Probabilities" index="C">
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
              This chain payload carries no per-expiry smile, only the surface blended across every
              expiry. A blended smile is not any traded expiry's, so a density built from it is
              mostly clipping artifact — no probability is stated rather than one that looks
              precise and is not.
            </p>
            <p v-else-if="densityUnreliable" class="unmeasurable-note" role="status">
              Density not usable — {{ pctFrac(withheldMassPct) }} of its mass was negative before
              clipping, so the shape is artifact rather than a distribution. Usually a put/call step
              at the money on a very short expiry; try a later expiry above.
            </p>
            <div v-else class="prob-grid">
              <Readout
                label="Above call wall"
                :value="
                  probabilities?.probAboveCallWall != null
                    ? pctFrac(probabilities.probAboveCallWall)
                    : DASH
                "
              />
              <Readout
                label="Below put wall"
                :value="
                  probabilities?.probBelowPutWall != null
                    ? pctFrac(probabilities.probBelowPutWall)
                    : DASH
                "
              />
              <Readout
                label="Between walls"
                :value="
                  probabilities?.probBetweenWalls != null
                    ? pctFrac(probabilities.probBetweenWalls)
                    : DASH
                "
              />
              <Readout
                label="Modal target"
                :value="
                  probabilities?.modalTarget != null ? num(probabilities.modalTarget, 2) : DASH
                "
              />
              <Readout
                label="68% band"
                :value="
                  probabilities?.band68
                    ? `${num(probabilities.band68.low, 2)} – ${num(probabilities.band68.high, 2)}`
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
              {{ pctFrac(withheldMassPct) }} of density mass was negative before clipping — the
              smile is noisy here, so read these as approximate. They are shown rather than hidden
              because a labelled approximation beats a blank panel.
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
                regimeState && (regimeState.gammaScaleM != null || regimeState.slopeScaleM != null)
              "
              class="scale-note label wraps"
            >
              Normalized against this symbol's own profile — gamma scale
              {{ regimeState.gammaScaleM != null ? optGex(regimeState.gammaScaleM) : DASH }}, slope
              scale {{ regimeState.slopeScaleM != null ? optGex(regimeState.slopeScaleM) : DASH }}.
            </p>
          </Panel>

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
    </template>
  </div>
</template>

<style scoped>
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
  gap: 0.375rem;
  background: var(--panel-hi);
  padding: 0.25rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius-sm, 4px);
}

.tab-btn {
  background: transparent;
  border: none;
  color: var(--ink-dim);
  font-family: var(--font-mono, monospace);
  font-size: 0.6875rem;
  font-weight: 700;
  padding: 0.375rem 0.75rem;
  border-radius: 3px;
  cursor: pointer;
  transition: all var(--duration-fast, 120ms) ease;
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

.surface-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: var(--s4);
  align-items: start;
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

.surface-col {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  min-height: 480px;
  min-width: 0;
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
</style>
