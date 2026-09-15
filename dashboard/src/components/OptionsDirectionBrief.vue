<script setup lang="ts">
import { computed } from 'vue'
import type { OptionsDirectionRead } from '@/optionsDirection'
import type { OptionsSqueeze } from '@/api'
import { DASH, num, optSignedGex, optUsd, pctFrac } from '@/format'
import { buildSqueezeExplanation, buildTheoryIdentity } from '@/squeezeCalc'

const props = defineProps<{
  symbol: string
  read: OptionsDirectionRead
  spot?: number | null
  callWall?: number | null
  putWall?: number | null
  gammaFlip?: number | null
  regime?: string | null
  totalGexM?: number | null
  squeeze?: OptionsSqueeze | null
}>()

function signedScore(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return DASH
  const rounded = Number(value.toFixed(1))
  if (rounded === 0 || Object.is(rounded, -0)) return '+0.0'
  return `${rounded > 0 ? '+' : ''}${num(rounded, 1)}`
}

function directionArrow(state: OptionsDirectionRead['state']): string {
  if (state === 'bullish') return '↗'
  if (state === 'bearish') return '↘'
  if (state === 'mixed') return '↕'
  return '•'
}

function finiteNum(value: unknown): number | null {
  if (value == null) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

/**
 * Where spot actually sits relative to the gamma flip, in dollars and percent.
 *
 * Sign convention is the same one wallDistancePct uses: the number is what the
 * underlier has to travel to reach the level, so a flip above spot reads
 * positive. The backend publishes this same quantity as
 * gamma_flip_pct = (flip - spot) / spot.
 */
const flipMath = computed(() => {
  const spot = finiteNum(props.spot)
  const flip = finiteNum(props.gammaFlip)
  if (spot == null || spot <= 0 || flip == null || flip <= 0) return null

  const gap = flip - spot
  const pct = (gap / spot) * 100
  const rounded = Number(pct.toFixed(1))
  const flat = rounded === 0 || Object.is(rounded, -0)

  return {
    spot,
    flip,
    gap,
    // Spot's side of the boundary, from price alone. Nothing else decides this.
    side: (flat ? 'at' : gap > 0 ? 'below' : 'above') as 'at' | 'below' | 'above',
    gapText: `${gap > 0 && !flat ? '+' : gap < 0 && !flat ? '-' : '+'}${optUsd(Math.abs(gap))}`,
    pctText: flat ? '+0.0%' : `${rounded > 0 ? '+' : ''}${num(rounded, 1)}%`,
  }
})

/**
 * Dealer-gamma regime.
 *
 * Two different measurements get conflated easily, so they are kept apart:
 *   net GEX sign  -> long or short dealer gamma summed across the whole chain
 *   spot vs flip  -> which side of the hedging boundary price is on right now
 * They usually agree but they are not the same number, so the hedging thesis
 * follows spot-vs-flip whenever the flip is measured, and net GEX only labels
 * the book. When the two point opposite ways, say so rather than silently
 * picking one.
 */
const regimeInfo = computed(() => {
  const reg = (props.regime || 'unknown').toLowerCase()
  const gex = finiteNum(props.totalGexM)

  // Net GEX is the measurement; the regime string is only a fallback label for
  // payloads that omit it. These are resolved in order, never OR-ed together —
  // OR-ing sets isPos and isNeg both true when the two sources disagree.
  let isPos: boolean
  let isNeg: boolean
  if (gex != null && gex !== 0) {
    isPos = gex > 0
    isNeg = gex < 0
  } else {
    isPos = reg.includes('pos') || reg.includes('long')
    isNeg = !isPos && (reg.includes('neg') || reg.includes('short'))
  }

  const label = isPos
    ? 'LONG GAMMA · VOLATILITY DAMPENED'
    : isNeg
      ? 'SHORT GAMMA · VOLATILITY AMPLIFIED'
      : 'NEUTRAL GAMMA'
  const tone = isPos ? 'bullish' : isNeg ? 'bearish' : 'neutral'
  const gexText = gex == null ? null : optSignedGex(gex, 1)
  const dealerGexHero = gex == null ? '$0.0M' : optSignedGex(gex, 1)

  const fm = flipMath.value
  const distToFlip = fm ? `${fm.pctText} TO FLIP` : null

  let dealerThesis: string
  let actionTag: string
  if (fm?.side === 'below') {
    dealerThesis =
      'Spot is below the flip, so hedging runs with the move: dealers sell into weakness and buy into strength. Expect moves to travel further than usual.'
    actionTag = `AMPLIFY BELOW ${optUsd(fm.flip)}`
  } else if (fm?.side === 'above') {
    dealerThesis =
      'Spot is above the flip, so hedging leans against the move: dealers buy into weakness and sell into strength. Moves tend to mean-revert.'
    actionTag = `DAMPEN ABOVE ${optUsd(fm.flip)}`
  } else if (fm?.side === 'at') {
    dealerThesis =
      'Spot is sitting on the flip. Hedging influence is balanced here and changes sign with the next tick through it.'
    actionTag = `AT THE ${optUsd(fm.flip)} FLIP`
  } else if (isNeg) {
    dealerThesis =
      'No measured gamma flip. Net dealer gamma is short, so the book leans toward amplifying moves, but the boundary is unlocated.'
    actionTag = 'AMPLIFY · NO MEASURED FLIP'
  } else if (isPos) {
    dealerThesis =
      'No measured gamma flip. Net dealer gamma is long, so the book leans toward dampening moves, but the boundary is unlocated.'
    actionTag = 'DAMPEN · NO MEASURED FLIP'
  } else {
    dealerThesis =
      'Dealer gamma is balanced and no flip is measured. Directional hedging influence is minimal.'
    actionTag = 'BALANCED REGIME'
  }

  // Net GEX sums the whole chain; the flip is a near-spot crossing. A short
  // book with spot above the flip (or the reverse) is a real state, not a bug,
  // and the two readouts must not be allowed to quietly contradict each other.
  const conflict = Boolean(
    fm && fm.side !== 'at' && ((fm.side === 'below' && isPos) || (fm.side === 'above' && isNeg)),
  )

  // The arithmetic behind every claim above, shown so it can be checked by eye.
  const derivation = fm
    ? `SPOT ${optUsd(fm.spot)} → FLIP ${optUsd(fm.flip)} = ${fm.gapText} (${fm.pctText}) · SPOT ${fm.side.toUpperCase()} FLIP`
    : 'NO MEASURED FLIP · SPOT SIDE UNRESOLVED'
  const bookDerivation = `NET GEX ${dealerGexHero} · ${isPos ? 'LONG' : isNeg ? 'SHORT' : 'FLAT'} BOOK`

  return {
    label,
    tone,
    isPos,
    isNeg,
    gexText,
    distToFlip,
    dealerGexHero,
    dealerThesis,
    actionTag,
    conflict,
    derivation,
    bookDerivation,
  }
})

/**
 * Quantitative Squeeze Mechanics Model.
 * Synthesizes dealer gamma fuel, tape pressure, momentum, and boundary pinning.
 */
const squeezeDiagnostics = computed(() => {
  const sq = props.squeeze
  const read = props.read
  const reg = regimeInfo.value
  const fm = flipMath.value
  const spot = finiteNum(props.spot)
  const cw = finiteNum(props.callWall)
  const pw = finiteNum(props.putWall)

  // 1. Long Gamma Dampening: dealers absorb moves, suppressing runaway squeeze cascades
  const isDampened = Boolean(
    sq?.long_gamma_dampened ||
      (fm?.side === 'above' && reg.isPos) ||
      (reg.isPos && !reg.isNeg && fm?.side !== 'below'),
  )

  // 2. Fuel is unsigned structure: short dealer gamma vs ADV. It is not a side.
  const fuelUi = finiteNum(sq?.theory?.fuel_ui) ?? finiteNum(sq?.negative_fuel)
  let fuelLabel: string
  let fuelTone: 'bullish' | 'bearish' | 'neutral' | 'warn' | 'fuel'
  if (isDampened) {
    fuelLabel = 'FUEL: LONG Γ DAMPENED'
    fuelTone = 'warn'
  } else if (fuelUi != null && fuelUi >= 0 && fuelUi <= 1) {
    fuelLabel = `FUEL ${Math.round(fuelUi * 100)}%`
    fuelTone = fuelUi < 0.05 ? 'warn' : 'fuel'
  } else if (reg.isNeg || fm?.side === 'below') {
    fuelLabel = 'FUEL: SHORT Γ LOADED'
    fuelTone = 'fuel'
  } else {
    fuelLabel = 'FUEL UNMEASURED'
    fuelTone = 'neutral'
  }

  // 3. Trigger status (signed flow vs price momentum)
  let triggerLabel: string
  let triggerTone: 'bullish' | 'bearish' | 'neutral' | 'warn'
  if (read.signedFlow != null && Math.abs(read.signedFlow) >= 0.05) {
    const s = read.signedFlow > 0 ? '+' : ''
    triggerLabel = `TRIGGER: SIGNED TAPE ${s}${pctFrac(read.signedFlow, 1)}`
    triggerTone = read.signedFlow > 0 ? 'bullish' : 'bearish'
  } else if (read.momentum != null && Math.abs(read.momentum) >= 0.005) {
    const s = read.momentum > 0 ? '+' : ''
    triggerLabel = `TRIGGER: MOMENTUM ${s}${pctFrac(read.momentum, 2)}`
    triggerTone = read.momentum > 0 ? 'bullish' : 'bearish'
  } else {
    triggerLabel = 'TRIGGER: NO TAPE BIAS'
    triggerTone = 'neutral'
  }

  // 4. Squeeze Status / Phase Tag
  let statusTag: string
  let statusTone: 'bullish' | 'bearish' | 'neutral' | 'warn'
  let mechanicsNote: string

  if (isDampened) {
    statusTag = 'SQUEEZE DAMPENED'
    statusTone = 'warn'
    mechanicsNote =
      'Long dealer gamma absorbs volatility; dealers lean against moves and suppress runaway squeeze cascades.'
  } else if (read.state === 'bullish' && (reg.isNeg || fm?.side === 'below')) {
    statusTag = 'UPSIDE SQUEEZE RISK'
    statusTone = 'bullish'
    mechanicsNote =
      'Short gamma fuel loaded with upside directional pressure. Dealer hedging accelerates through call wall.'
  } else if (read.state === 'bearish' && (reg.isNeg || fm?.side === 'below')) {
    statusTag = 'DOWNSIDE SQUEEZE RISK'
    statusTone = 'bearish'
    mechanicsNote =
      'Short gamma fuel loaded with downside directional pressure. Dealer hedging accelerates through put wall.'
  } else if (spot != null && cw != null && pw != null && spot >= pw && spot <= cw) {
    statusTag = 'COMPRESSION COIL'
    statusTone = 'neutral'
    mechanicsNote =
      'Spot is bound within structural walls. Directional expansion pinned until outer boundary breach.'
  } else {
    statusTag =
      read.state === 'bullish'
        ? 'BULLISH LEAN'
        : read.state === 'bearish'
          ? 'BEARISH LEAN'
          : 'NEUTRAL SQUEEZE'
    statusTone =
      read.state === 'bullish' ? 'bullish' : read.state === 'bearish' ? 'bearish' : 'neutral'
    mechanicsNote = read.subhead
  }

  return {
    isDampened,
    fuelLabel,
    fuelTone,
    triggerLabel,
    triggerTone,
    statusTag,
    statusTone,
    mechanicsNote,
  }
})

const corridorSummary = computed(() => {
  const cw = finiteNum(props.callWall)
  const pw = finiteNum(props.putWall)
  const spot = finiteNum(props.spot)
  if (cw == null || pw == null || cw <= pw || spot == null || spot <= 0) return null
  const span = cw - pw
  const pct = (span / spot) * 100
  return `${optUsd(span)} (${num(pct, 1)}%) CORRIDOR`
})

const hasStructure = computed(
  () =>
    props.spot != null &&
    Number.isFinite(props.spot) &&
    props.spot > 0 &&
    ((props.callWall != null && Number.isFinite(props.callWall) && props.callWall > 0) ||
      (props.putWall != null && Number.isFinite(props.putWall) && props.putWall > 0) ||
      (props.gammaFlip != null && Number.isFinite(props.gammaFlip) && props.gammaFlip > 0)),
)

const structureRange = computed(() => {
  const spot = props.spot
  if (spot == null || !Number.isFinite(spot) || spot <= 0) return null
  const levels = [spot]
  if (props.callWall != null && Number.isFinite(props.callWall) && props.callWall > 0)
    levels.push(props.callWall)
  if (props.putWall != null && Number.isFinite(props.putWall) && props.putWall > 0)
    levels.push(props.putWall)
  if (props.gammaFlip != null && Number.isFinite(props.gammaFlip) && props.gammaFlip > 0)
    levels.push(props.gammaFlip)

  const minRaw = Math.min(...levels)
  const maxRaw = Math.max(...levels)
  const spanRaw = maxRaw - minRaw
  const pad = Math.max(spanRaw * 0.08, spot * 0.02)
  const minVal = minRaw - pad
  const maxVal = maxRaw + pad
  const span = maxVal - minVal || 1

  const toPct = (v: number | null | undefined): number | null => {
    if (v == null || !Number.isFinite(v) || v <= 0) return null
    return Math.max(2, Math.min(98, ((v - minVal) / span) * 100))
  }

  const spotPct = toPct(spot) ?? 50
  const putWallPct = props.putWall != null && props.putWall > 0 ? toPct(props.putWall) : null
  const callWallPct = props.callWall != null && props.callWall > 0 ? toPct(props.callWall) : null
  const flipPct = props.gammaFlip != null && props.gammaFlip > 0 ? toPct(props.gammaFlip) : null

  const putNearCall =
    putWallPct != null && callWallPct != null && Math.abs(putWallPct - callWallPct) < 12
  const flipNearPut = flipPct != null && putWallPct != null && Math.abs(flipPct - putWallPct) < 12
  const flipNearCall = flipPct != null && callWallPct != null && Math.abs(flipPct - callWallPct) < 12

  const putTier = 1
  const callTier = putNearCall ? 2 : 1

  let flipTier = 1
  if (flipNearPut || flipNearCall) {
    const occupied = new Set<number>()
    if (flipNearPut) occupied.add(putTier)
    if (flipNearCall) occupied.add(callTier)
    flipTier = 1
    while (occupied.has(flipTier)) {
      flipTier++
    }
  }

  const isFlipStaggered = flipTier > 1
  const isCallStaggered = callTier > 1
  const isPutStaggered = putTier > 1
  const maxTier = Math.max(putTier, callTier, flipTier)
  const paddingTop = maxTier === 3 ? 54 : maxTier === 2 ? 38 : 24

  return {
    minVal,
    maxVal,
    spotPct,
    putWallPct,
    callWallPct,
    flipPct,
    putTier,
    callTier,
    flipTier,
    isFlipStaggered,
    isCallStaggered,
    isPutStaggered,
    maxTier,
    paddingTop,
  }
})

function markerEdgeCls(pct: number | null | undefined): string {
  if (pct == null) return ''
  if (pct <= 12) return 'is-left'
  if (pct >= 88) return 'is-right'
  return ''
}

function wallDistancePct(wall: number | null | undefined): string {
  if (
    props.spot == null ||
    !Number.isFinite(props.spot) ||
    props.spot <= 0 ||
    wall == null ||
    !Number.isFinite(wall) ||
    wall <= 0
  ) {
    return ''
  }
  const diff = (wall - props.spot) / props.spot
  const diffPct = diff * 100
  const rounded = Number(diffPct.toFixed(1))
  if (rounded === 0 || Object.is(rounded, -0)) return '+0.0%'
  const sign = rounded > 0 ? '+' : ''
  return `${sign}${num(rounded, 1)}%`
}

const squeezeIdentity = computed(() => buildTheoryIdentity(props.squeeze))
const squeezeExpl = computed(() => buildSqueezeExplanation(props.squeeze, props.spot))

const squeezeMeter = computed(() => {
  const ex = squeezeExpl.value
  const fromSqueeze = Boolean(props.squeeze)
  const raw = fromSqueeze ? ex.score : props.read.score
  const has =
    raw != null &&
    Number.isFinite(raw) &&
    (!fromSqueeze || ex.dirStatus !== 'degraded')
  const clamped = has ? Math.max(-100, Math.min(100, raw as number)) : 0
  return {
    has,
    value: clamped,
    pct: fromSqueeze && has && ex.markerPct != null ? ex.markerPct : (clamped + 100) / 2,
    tone: !has ? 'unmeasured' : clamped > 8 ? 'bullish' : clamped < -8 ? 'bearish' : 'neutral',
    leanAt: ex.leanAt,
    squeezeAt: ex.squeezeAt,
  }
})

const squeezeTicks = computed(() => {
  const { leanAt, squeezeAt } = squeezeMeter.value
  return [-squeezeAt, -leanAt, leanAt, squeezeAt].map((v) => ({
    v,
    left: 50 + v / 2,
  }))
})

const scoreLabel = computed(() => {
  if (props.squeeze) {
    const ex = squeezeExpl.value
    if (!ex.measurable || ex.dirStatus === 'degraded') return DASH
    return signedScore(ex.score ?? props.read.score)
  }
  return signedScore(props.read.score)
})

const rulerTicks = Array.from({ length: 21 }, (_, i) => i * 5)
</script>

<template>
  <section
    class="direction-brief rise"
    :class="read.state"
    :aria-label="`${symbol} options direction: ${read.headline}`"
    :title="read.confirmation"
  >
    <div class="positioning-layout">
      <!-- Main Direction & Gamma Head -->
      <div class="direction-head">
        <!-- Card 1: Squeeze & Direction Engine -->
        <div class="score-block">
          <div class="card-eyebrow label">
            <span class="eyebrow-text">{{ symbol }} · UNDERLYING DIRECTION</span>
            <span class="squeeze-phase-badge label" :class="squeezeDiagnostics.statusTone">
              {{ squeezeDiagnostics.statusTag }}
            </span>
          </div>

          <div class="dir-title-line">
            <strong class="fig score-val" :class="squeezeMeter.tone">{{ scoreLabel }}</strong>
            <span class="score-max">/100</span>
            <span class="direction-mark" aria-hidden="true">{{ directionArrow(read.state) }}</span>
            <strong class="fig direction-title">{{ read.headline }}</strong>
            <span class="label confidence" :class="read.confidence">
              {{
                read.confidence === 'wait' ? 'WAIT FOR EVIDENCE' : `${read.confidence} CONVICTION`
              }}
            </span>
          </div>

          <!-- Squeeze Spectrum Telemetry Meter -->
          <div
            class="sq-meter"
            role="meter"
            :aria-valuemin="-100"
            :aria-valuemax="100"
            :aria-valuenow="squeezeMeter.has ? squeezeMeter.value : undefined"
            :aria-valuetext="`Squeeze score ${scoreLabel} of 100`"
            :aria-label="`Directional squeeze score ${scoreLabel} of 100`"
          >
            <span class="sq-end label bear">BEARISH</span>
            <span class="sq-track">
              <span class="sq-spectrum" aria-hidden="true"><i /><i /><i /><i /><i /></span>
              <i
                v-for="tk in squeezeTicks"
                :key="tk.v"
                class="sq-band-tick"
                aria-hidden="true"
                :style="{ left: `${tk.left}%` }"
              />
              <i class="sq-zero" aria-hidden="true" />
              <span
                v-if="squeezeMeter.has"
                class="sq-thumb"
                :class="squeezeMeter.tone"
                :style="{ left: `${squeezeMeter.pct}%` }"
              />
            </span>
            <span class="sq-end label bull">BULLISH</span>
          </div>

          <!-- Squeeze Model Diagnostics Row -->
          <div class="dir-sub-line">
            <span v-if="regimeInfo.distToFlip" class="flip-dist-chip label">{{
              regimeInfo.distToFlip
            }}</span>
            <span class="sq-chip label" :class="squeezeDiagnostics.fuelTone">{{
              squeezeDiagnostics.fuelLabel
            }}</span>
            <span class="sq-chip label" :class="squeezeDiagnostics.triggerTone">{{
              squeezeDiagnostics.triggerLabel
            }}</span>
          </div>

          <p v-if="squeeze" class="sq-identity-formula label">{{ squeezeIdentity.formula }}</p>
          <div v-if="squeeze" class="sq-moment" aria-label="Squeeze direction legs">
            <div
              v-for="leg in squeezeExpl.dirLegs"
              :key="leg.id"
              class="sq-moment-leg"
              :data-tone="leg.tone"
              :data-votes="leg.votes ? 'yes' : 'no'"
            >
              <span class="sq-moment-label label">{{ leg.label }}</span>
              <strong class="sq-moment-val fig">{{ leg.display }}</strong>
              <span class="sq-moment-meter" aria-hidden="true">
                <i v-if="leg.fill01 != null" :style="{ width: `${(leg.fill01 * 100).toFixed(1)}%` }" />
              </span>
            </div>
          </div>

          <!-- Descriptive Subhead / Mechanics Note -->
          <div class="dir-subhead-box">
            <p class="dir-subhead label">{{ read.subhead }}</p>
          </div>
        </div>

        <!-- Card 2: Dealer Gamma & Hedging Model -->
        <div class="dealer-gamma-card">
          <div class="card-eyebrow label">
            <span>DEALER GAMMA</span>
            <span v-if="regimeInfo.gexText" class="regime-tag-badge label" :class="regimeInfo.tone">
              {{ regimeInfo.label }}
            </span>
          </div>
          <div class="dealer-hero-row">
            <strong class="dealer-hero-num fig" :class="regimeInfo.tone">{{
              regimeInfo.dealerGexHero
            }}</strong>
            <span class="action-tag label" :class="regimeInfo.tone">{{
              regimeInfo.actionTag
            }}</span>
            <span class="hedging-flow-badge label" :class="regimeInfo.tone">{{
              regimeInfo.isPos
                ? 'MEAN-REVERTING'
                : regimeInfo.isNeg
                  ? 'TREND-ACCELERATING'
                  : 'BALANCED'
            }}</span>
          </div>
          <p class="dealer-thesis-text">{{ regimeInfo.dealerThesis }}</p>
          <div class="dealer-derivation" aria-label="How the dealer read was derived">
            <div class="deriv-item">
              <span class="deriv-row label">{{ regimeInfo.derivation }}</span>
            </div>
            <div class="deriv-item">
              <span class="deriv-row label">{{ regimeInfo.bookDerivation }}</span>
            </div>
          </div>
          <p v-if="regimeInfo.conflict" class="dealer-conflict label">
            NET GEX AND SPOT-SIDE DISAGREE: net gamma is
            {{ regimeInfo.isPos ? 'long' : 'short' }} across the chain while spot sits
            {{ regimeInfo.isPos ? 'below' : 'above' }} the flip. The hedging read above follows spot
            versus the flip.
          </p>
        </div>
      </div>

      <!-- Evidence Matrix Strip -->
      <div class="evidence-strip" aria-label="Directional evidence">
        <div class="evidence-cell basis-cell">
          <span class="label">DIRECTION COMES FROM</span>
          <strong class="fig">{{ read.basis }}</strong>
        </div>
        <div class="evidence-cell">
          <span class="label">SIGNED FLOW</span>
          <strong
            class="fig"
            :class="
              read.signedFlow != null
                ? read.signedFlow > 0
                  ? 'pos'
                  : read.signedFlow < 0
                    ? 'neg'
                    : ''
                : ''
            "
          >
            {{
              read.signedFlow == null
                ? DASH
                : `${read.signedFlow > 0 ? '+' : ''}${pctFrac(read.signedFlow, 1)}`
            }}
          </strong>
          <small class="label">{{
            read.signedConfidence == null
              ? 'NO BUY / SELL SIDE'
              : `${pctFrac(read.signedConfidence, 0)} CONF.`
          }}</small>
        </div>
        <div class="evidence-cell">
          <span class="label">PRICE MOMENTUM</span>
          <strong
            class="fig"
            :class="
              read.momentum != null
                ? read.momentum > 0
                  ? 'pos'
                  : read.momentum < 0
                    ? 'neg'
                    : ''
                : ''
            "
          >
            {{
              read.momentum == null
                ? DASH
                : `${read.momentum > 0 ? '+' : ''}${pctFrac(read.momentum, 2)}`
            }}
          </strong>
          <small class="label">{{ read.momentumFresh ? 'FRESH' : 'STALE · EXCLUDED' }}</small>
        </div>
        <div class="evidence-cell activity" :class="read.activity">
          <span class="label">CONTRACT MIX</span>
          <strong class="fig">{{
            read.callPct == null ? DASH : `${read.callPct}% C / ${read.putPct}% P`
          }}</strong>
          <small class="label">NOT DIRECTION</small>
        </div>
      </div>

      <!-- Unified Positioning Telemetry Map -->
      <div
        v-if="hasStructure && structureRange"
        class="positioning-range-meter"
        aria-label="Positioning range map"
      >
        <div class="range-meter-head">
          <div class="wall-head-item put">
            <span class="wall-head-label">PUT WALL</span>
            <strong class="wall-head-price">{{ optUsd(putWall) }}</strong>
          </div>
          <div class="meter-center">
            <span class="meter-title label">POSITIONING TELEMETRY MAP</span>
            <span v-if="corridorSummary" class="corridor-summary label">{{ corridorSummary }}</span>
          </div>
          <div class="wall-head-item call">
            <strong class="wall-head-price">{{ optUsd(callWall) }}</strong>
            <span class="wall-head-label">CALL WALL</span>
          </div>
        </div>

        <div
          class="range-track-container"
          :style="{ paddingTop: `${structureRange.paddingTop}px` }"
        >
          <div class="range-track visual-track">
            <template v-if="structureRange.flipPct != null">
              <div
                class="range-zone short-gamma"
                :style="{ left: '0%', width: `${structureRange.flipPct}%` }"
              >
                <span class="zone-label">AMPLIFY · SHORT GAMMA</span>
              </div>
              <div
                class="range-zone long-gamma"
                :style="{
                  left: `${structureRange.flipPct}%`,
                  width: `${100 - structureRange.flipPct}%`,
                }"
              >
                <span class="zone-label">DAMP · LONG GAMMA</span>
              </div>
            </template>
            <div v-else-if="regimeInfo.isNeg" class="range-zone short-gamma full-zone">
              <span class="zone-label">AMPLIFY · SHORT GAMMA</span>
            </div>
            <div v-else-if="regimeInfo.isPos" class="range-zone long-gamma full-zone">
              <span class="zone-label">DAMP · LONG GAMMA</span>
            </div>

            <!-- Put Wall Marker -->
            <div
              v-if="structureRange.putWallPct != null"
              class="range-marker put-wall"
              :class="[markerEdgeCls(structureRange.putWallPct), `tier-${structureRange.putTier}`]"
              :style="{ left: `${structureRange.putWallPct}%` }"
              :title="`Put Wall: ${optUsd(putWall)} (${wallDistancePct(putWall)})`"
            >
              <span class="marker-line put" />
              <span class="marker-pill put" :class="`tier-${structureRange.putTier}`">
                <span class="pill-label">PUT W</span>
                <strong class="pill-val">{{ optUsd(putWall) }}</strong>
                <small v-if="wallDistancePct(putWall)" class="pill-dist">{{
                  wallDistancePct(putWall)
                }}</small>
              </span>
            </div>

            <!-- Gamma Flip Boundary Marker -->
            <div
              v-if="structureRange.flipPct != null"
              class="range-marker gamma-flip"
              :class="[
                markerEdgeCls(structureRange.flipPct),
                `tier-${structureRange.flipTier}`,
                { staggered: structureRange.isFlipStaggered },
              ]"
              :style="{ left: `${structureRange.flipPct}%` }"
              :title="`Gamma Flip Boundary: ${optUsd(gammaFlip)}`"
            >
              <span
                class="marker-line flip"
                :class="[
                  `tier-${structureRange.flipTier}`,
                  { staggered: structureRange.isFlipStaggered },
                ]"
              />
              <span
                class="marker-pill flip"
                :class="[
                  `tier-${structureRange.flipTier}`,
                  { staggered: structureRange.isFlipStaggered },
                ]"
              >
                <span class="pill-label">FLIP</span>
                <strong class="pill-val">{{ optUsd(gammaFlip) }}</strong>
                <small v-if="regimeInfo.distToFlip" class="pill-dist"
                  >{{ regimeInfo.distToFlip }} away</small
                >
              </span>
            </div>

            <!-- Spot Location Needle -->
            <div
              class="range-marker spot-marker"
              :class="markerEdgeCls(structureRange.spotPct)"
              :style="{ left: `${structureRange.spotPct}%` }"
              :title="`Spot: ${optUsd(spot)}`"
            >
              <span class="marker-needle" />
              <span class="marker-pill spot">
                <span class="pill-label">SPOT</span>
                <strong class="pill-val">{{ optUsd(spot) }}</strong>
              </span>
            </div>

            <!-- Call Wall Marker -->
            <div
              v-if="structureRange.callWallPct != null"
              class="range-marker call-wall"
              :class="[
                markerEdgeCls(structureRange.callWallPct),
                `tier-${structureRange.callTier}`,
                { staggered: structureRange.isCallStaggered },
              ]"
              :style="{ left: `${structureRange.callWallPct}%` }"
              :title="`Call Wall: ${optUsd(callWall)} (${wallDistancePct(callWall)})`"
            >
              <span class="marker-line call" :class="`tier-${structureRange.callTier}`" />
              <span
                class="marker-pill call"
                :class="[
                  `tier-${structureRange.callTier}`,
                  { staggered: structureRange.isCallStaggered },
                ]"
              >
                <span class="pill-label">CALL W</span>
                <strong class="pill-val">{{ optUsd(callWall) }}</strong>
                <small v-if="wallDistancePct(callWall)" class="pill-dist">{{
                  wallDistancePct(callWall)
                }}</small>
              </span>
            </div>
          </div>

          <!-- Precision Instrument Ruler -->
          <svg
            class="range-ruler"
            viewBox="0 0 100 6"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <line class="ruler-line" x1="0" y1="0.5" x2="100" y2="0.5" />
            <line
              v-for="t in rulerTicks"
              :key="t"
              class="ruler-tick"
              :class="{ major: t % 25 === 0 }"
              :x1="t"
              :y1="0.5"
              :x2="t"
              :y2="t % 25 === 0 ? 5.5 : 3.5"
            />
          </svg>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.direction-brief {
  --direction-tone: var(--ink-dim);
  display: flex;
  flex-direction: column;
  min-height: 60px;
  border: var(--hair) solid var(--glass-border);
  background: var(--panel);
  border-radius: var(--r-xs, 2px);
  box-shadow: var(--glass-shadow-sm), var(--glass-specular-subtle);
  overflow: hidden;
}
.direction-brief.bullish {
  --direction-tone: var(--long);
}
.direction-brief.bearish {
  --direction-tone: var(--short);
}
.direction-brief.mixed {
  --direction-tone: var(--warn);
}
.direction-brief.unavailable {
  --direction-tone: var(--ink-dim);
}

.positioning-layout {
  display: flex;
  flex-direction: column;
  background: var(--panel);
}

.direction-head {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(240px, 0.85fr);
  align-items: stretch;
  min-width: 0;
}
@media (max-width: 1080px) {
  .direction-head {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 640px) {
  .sq-moment {
    grid-template-columns: 1fr;
  }
}

.score-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  padding: 10px 14px 12px;
  background: var(--void-lift);
  border-right: var(--hair) solid var(--rule);
}
@media (max-width: 1080px) {
  .score-block {
    border-right: 0;
    border-bottom: var(--hair) solid var(--rule);
  }
}

.card-eyebrow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
  color: var(--ink-faint);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.08em;
}

.eyebrow-text {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  letter-spacing: 0.06em;
  font-weight: 700;
}

.squeeze-phase-badge {
  padding: 1px 7px;
  border-radius: var(--r-xs, 2px);
  font-size: var(--t-nano);
  font-weight: 800;
  letter-spacing: 0.06em;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void);
  color: var(--ink-dim);
  line-height: 1.35;
  white-space: nowrap;
}
.squeeze-phase-badge.warn {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 40%, var(--rule));
  background: var(--warn-wash);
}
.squeeze-phase-badge.bullish {
  color: var(--call-hi);
  border-color: color-mix(in srgb, var(--call) 40%, var(--rule));
  background: var(--call-wash);
}
.squeeze-phase-badge.bearish {
  color: var(--put-hi);
  border-color: color-mix(in srgb, var(--put) 40%, var(--rule));
  background: var(--put-wash);
}
.squeeze-phase-badge.neutral {
  color: var(--ink-dim);
  border-color: var(--rule-hi);
  background: var(--void);
}

.dir-title-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}
.score-val {
  font-size: 1.25rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--direction-tone);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
}
.score-val.bullish {
  color: var(--long);
}
.score-val.bearish {
  color: var(--short);
}
.score-val.neutral,
.score-val.unmeasured {
  color: var(--ink-dim);
}
.score-max {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: 11px;
  font-weight: 600;
}
.direction-mark {
  color: var(--direction-tone);
  font-weight: 800;
  font-size: 1.1rem;
}
.direction-title {
  color: var(--direction-tone);
  font-size: 1.05rem;
  font-weight: 800;
  letter-spacing: 0.02em;
}
.confidence {
  padding: 2px 7px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void);
  font-size: var(--t-micro);
  font-weight: 700;
  border-radius: var(--r-xs, 2px);
  letter-spacing: 0.04em;
}
.confidence.high,
.confidence.medium {
  color: var(--direction-tone);
  border-color: color-mix(in srgb, var(--direction-tone) 40%, var(--rule));
}
.confidence.low {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 50%, var(--rule));
  background: var(--warn-wash);
}
.confidence.wait {
  color: var(--ink-dim);
}

.sq-meter {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.sq-end {
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
.sq-end.bear {
  color: var(--short);
}
.sq-end.bull {
  color: var(--long);
}
.sq-track {
  position: relative;
  height: 8px;
  min-width: 0;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: 2px;
  overflow: visible;
}
.sq-spectrum {
  display: flex;
  height: 100%;
  border-radius: 1px;
  overflow: hidden;
}
.sq-spectrum i {
  flex: 1 1 0;
  display: block;
  height: 100%;
}
.sq-spectrum i:nth-child(1) {
  background: color-mix(in srgb, var(--short) 70%, transparent);
}
.sq-spectrum i:nth-child(2) {
  background: color-mix(in srgb, var(--short) 35%, transparent);
}
.sq-spectrum i:nth-child(3) {
  background: transparent;
}
.sq-spectrum i:nth-child(4) {
  background: color-mix(in srgb, var(--long) 35%, transparent);
}
.sq-spectrum i:nth-child(5) {
  background: color-mix(in srgb, var(--long) 70%, transparent);
}
.sq-zero {
  position: absolute;
  top: -3px;
  bottom: -3px;
  left: 50%;
  width: 1px;
  background: var(--rule-hi);
  transform: translateX(-50%);
  pointer-events: none;
}
.sq-band-tick {
  position: absolute;
  top: -2px;
  bottom: -2px;
  width: var(--hair);
  background: var(--rule-hi);
  transform: translateX(-50%);
  pointer-events: none;
}
.sq-thumb {
  position: absolute;
  top: 50%;
  width: 6px;
  height: 14px;
  border-radius: 1px;
  background: var(--ink);
  border: 1px solid var(--void);
  transform: translate(-50%, -50%);
  pointer-events: none;
  box-shadow: var(--shadow-1);
  z-index: 2;
}
.sq-thumb.bullish {
  background: var(--long);
}
.sq-thumb.bearish {
  background: var(--short);
}
.sq-thumb.neutral {
  background: var(--ink-soft);
}

.dir-sub-line {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}
.flip-dist-chip {
  padding: 1px 7px;
  border: var(--hair) solid color-mix(in srgb, var(--warn) 45%, var(--rule));
  color: var(--warn);
  background: var(--warn-wash);
  font-size: var(--t-nano);
  font-weight: 700;
  font-family: var(--font-data);
  border-radius: var(--r-xs, 2px);
  white-space: nowrap;
}
.sq-chip {
  padding: 1px 7px;
  border-radius: var(--r-xs, 2px);
  font-size: var(--t-nano);
  font-weight: 600;
  font-family: var(--font-data);
  letter-spacing: 0.03em;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  white-space: nowrap;
}
.sq-chip.warn {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 35%, var(--rule));
  background: var(--warn-wash);
}
.sq-chip.bullish {
  color: var(--call-hi);
  border-color: color-mix(in srgb, var(--call) 35%, var(--rule));
  background: var(--call-wash);
}
.sq-chip.bearish {
  color: var(--put-hi);
  border-color: color-mix(in srgb, var(--put) 35%, var(--rule));
  background: var(--put-wash);
}
.sq-chip.fuel {
  color: var(--phosphor);
  border-color: color-mix(in srgb, var(--phosphor) 35%, var(--rule));
  background: var(--phosphor-wash);
}

.sq-identity-formula {
  margin: 0;
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.04em;
  color: var(--ink-faint);
}

.sq-moment {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s3);
  min-width: 0;
}
.sq-moment-leg {
  --leg-tone: var(--ink-faint);
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px var(--s2);
  align-items: baseline;
}
.sq-moment-leg[data-tone='flow'] {
  --leg-tone: var(--phosphor);
}
.sq-moment-leg[data-tone='mom'] {
  --leg-tone: var(--ink);
}
.sq-moment-leg[data-tone='warn'] {
  --leg-tone: var(--warn);
}
.sq-moment-label {
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
.sq-moment-val {
  font-size: var(--t-small);
  font-weight: 700;
  color: var(--leg-tone);
  text-align: right;
}
.sq-moment-meter {
  grid-column: 1 / -1;
  height: 3px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  overflow: hidden;
}
.sq-moment-meter i {
  display: block;
  height: 100%;
  background: var(--leg-tone);
}

.dir-subhead-box {
  padding: 5px 8px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs, 2px);
  margin-top: 2px;
}

.dir-subhead {
  margin: 0;
  color: var(--ink-soft);
  font-size: var(--t-tiny);
  line-height: 1.45;
  white-space: normal;
}

.dealer-gamma-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 14px 12px;
  background: var(--void-lift);
  min-width: 0;
}

.dealer-hero-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.dealer-hero-num {
  font-size: 1.25rem;
  font-weight: 800;
  line-height: 1.1;
  letter-spacing: -0.03em;
  font-family: var(--font-data);
}
.dealer-hero-num.bullish {
  color: var(--call-hi);
}
.dealer-hero-num.bearish {
  color: var(--put-hi);
}
.dealer-hero-num.neutral {
  color: var(--ink-dim);
}

.action-tag {
  padding: 2px 8px;
  border-radius: var(--r-xs, 2px);
  font-size: var(--t-micro);
  font-weight: 800;
  letter-spacing: 0.06em;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void);
  color: var(--ink-dim);
  white-space: nowrap;
}
.action-tag.bearish {
  color: var(--put-hi);
  border-color: color-mix(in srgb, var(--put) 40%, var(--rule));
  background: var(--put-wash);
}
.action-tag.bullish {
  color: var(--call-hi);
  border-color: color-mix(in srgb, var(--call) 40%, var(--rule));
  background: var(--call-wash);
}

.hedging-flow-badge {
  padding: 2px 7px;
  border-radius: var(--r-xs, 2px);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.05em;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  white-space: nowrap;
}
.hedging-flow-badge.bullish {
  color: var(--call-hi);
  border-color: color-mix(in srgb, var(--call) 30%, var(--rule));
}
.hedging-flow-badge.bearish {
  color: var(--put-hi);
  border-color: color-mix(in srgb, var(--put) 30%, var(--rule));
}

.dealer-thesis-text {
  margin: 0;
  color: var(--ink-soft);
  font-size: var(--t-tiny);
  line-height: 1.4;
  white-space: normal;
}

.dealer-derivation {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 4px;
  padding-top: 6px;
  border-top: var(--hair) solid var(--rule);
}
.deriv-item {
  display: flex;
  align-items: baseline;
  padding: 3px 8px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs, 2px);
}
.deriv-row {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  color: var(--ink-faint);
  letter-spacing: 0.02em;
  white-space: normal;
  line-height: 1.35;
}

.dealer-conflict {
  margin: 4px 0 0;
  padding: 4px 8px;
  border: var(--hair) solid var(--warn);
  background: var(--warn-wash);
  color: var(--warn);
  font-size: var(--t-micro);
  line-height: 1.35;
  white-space: normal;
  border-radius: var(--r-xs, 2px);
}

.regime-tag-badge {
  padding: 1px 8px;
  border: var(--hair) solid var(--rule-hi);
  font-size: var(--t-micro);
  font-weight: 700;
  border-radius: var(--r-xs, 2px);
  background: var(--void);
  color: var(--ink-dim);
  white-space: nowrap;
}
.regime-tag-badge.bullish {
  color: var(--call-hi);
  border-color: color-mix(in srgb, var(--call) 40%, var(--rule));
  background: var(--call-wash);
}
.regime-tag-badge.bearish {
  color: var(--put-hi);
  border-color: color-mix(in srgb, var(--put) 40%, var(--rule));
  background: var(--put-wash);
}

.evidence-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  background: var(--rule);
  border-top: var(--hair) solid var(--rule);
  border-bottom: var(--hair) solid var(--rule);
  overflow: hidden;
}
@media (max-width: 700px) {
  .evidence-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.evidence-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 12px;
  background: var(--panel);
  min-width: 0;
}
.evidence-cell > span {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  letter-spacing: 0.05em;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.evidence-cell strong {
  color: var(--ink);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 700;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.evidence-cell small {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  font-weight: 600;
  letter-spacing: 0.03em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.evidence-cell strong.pos {
  color: var(--long);
}
.evidence-cell strong.neg {
  color: var(--short);
}
.evidence-cell.activity.call strong {
  color: var(--call-hi, var(--call));
}
.evidence-cell.activity.put strong {
  color: var(--put-hi, var(--put));
}

.positioning-range-meter {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 14px 12px;
  background: var(--void);
}

.range-meter-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--t-micro);
  color: var(--ink-faint);
  letter-spacing: 0.06em;
  padding-bottom: 2px;
}
.wall-head-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.wall-head-item.put .wall-head-label,
.wall-head-item.put .wall-head-price {
  color: var(--put-hi, var(--put));
}
.wall-head-item.call .wall-head-label,
.wall-head-item.call .wall-head-price {
  color: var(--call-hi, var(--call));
}
.wall-head-label {
  font-weight: 700;
  font-size: 10px;
}
.wall-head-price {
  font-family: var(--font-data);
  font-weight: 800;
  font-size: 13px;
}
.meter-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.meter-title {
  font-weight: 700;
  color: var(--ink-faint);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
}
.corridor-summary {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  color: var(--phosphor-dim);
  font-weight: 700;
  letter-spacing: 0.04em;
}

.range-track-container {
  position: relative;
  width: 100%;
  padding-top: 28px;
  padding-bottom: 12px;
}

.range-track.visual-track {
  position: relative;
  height: 48px;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs, 2px);
  overflow: visible;
}

.range-zone {
  position: absolute;
  top: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  overflow: hidden;
}
.range-zone.short-gamma {
  background: var(--put-wash);
  border-right: 1px dashed color-mix(in srgb, var(--put) 40%, var(--rule));
  justify-content: flex-start;
}
.range-zone.long-gamma {
  background: var(--call-wash);
  border-left: 1px dashed color-mix(in srgb, var(--call) 40%, var(--rule));
  justify-content: flex-end;
}
.range-zone.full-zone {
  border: 0;
}
.zone-label {
  font: 800 var(--t-nano) var(--font-display);
  letter-spacing: 0.06em;
  white-space: nowrap;
  padding: 0 10px;
}
.range-zone.short-gamma .zone-label {
  color: var(--put-hi, var(--put));
}
.range-zone.long-gamma .zone-label {
  color: var(--call-hi, var(--call));
}

.range-ruler {
  display: block;
  width: 100%;
  height: 6px;
  margin-top: 6px;
}
.ruler-line {
  stroke: var(--rule);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.ruler-tick {
  stroke: var(--rule);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.ruler-tick.major {
  stroke: var(--rule-hi);
}

.range-marker {
  position: absolute;
  top: -6px;
  bottom: -6px;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  pointer-events: auto;
  z-index: 3;
}

.range-marker.is-left .marker-pill {
  left: 0;
  transform: translateX(0);
}

.range-marker.is-right .marker-pill {
  left: auto;
  right: 0;
  transform: translateX(0);
}

.marker-line {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  border-radius: 1px;
}
.marker-line.put {
  background: var(--put);
}
.marker-line.call {
  background: var(--call);
}
.marker-line.flip {
  background: var(--warn);
  width: 1px;
  border-style: dashed;
}
.marker-line.flip.staggered,
.marker-line.tier-2 {
  top: -16px;
}
.marker-line.tier-3 {
  top: -32px;
}

.marker-needle {
  position: absolute;
  top: -2px;
  bottom: -2px;
  width: 3px;
  background: var(--ink);
  border-radius: 1px;
  outline: var(--hair) solid var(--void);
}

.marker-pill {
  position: absolute;
  top: -20px;
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
  padding: 1px 6px;
  border-radius: var(--r-xs, 2px);
  font-size: var(--t-micro);
  line-height: 1.1;
  white-space: nowrap;
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
  box-shadow: var(--shadow-1);
}
.marker-pill.put {
  color: var(--put-hi);
  border-color: color-mix(in srgb, var(--put) 45%, var(--rule));
  background: var(--put-wash);
}
.marker-pill.call {
  color: var(--call-hi);
  border-color: color-mix(in srgb, var(--call) 45%, var(--rule));
  background: var(--call-wash);
}
.marker-pill.flip {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 45%, var(--rule));
  background: var(--warn-wash);
  top: -20px;
}
.marker-pill.flip.staggered,
.marker-pill.tier-2 {
  top: -36px;
}
.marker-pill.tier-3 {
  top: -52px;
}
.marker-pill.spot {
  color: var(--ink);
  border-color: var(--ink-dim);
  background: var(--panel-raise);
  font-weight: 700;
  top: 14px;
  white-space: nowrap;
  min-width: max-content;
  padding: 2px 8px;
}

.pill-label {
  font-size: var(--t-micro);
  font-weight: 600;
  opacity: 0.85;
}
.pill-val {
  font-family: var(--font-data);
  font-weight: 800;
}
.pill-dist {
  font-size: var(--t-micro);
  font-family: var(--font-data);
  opacity: 0.9;
  margin-left: 2px;
}
</style>
