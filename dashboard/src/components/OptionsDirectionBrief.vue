<script setup lang="ts">
import { computed } from 'vue'
import type { OptionsDirectionRead } from '@/optionsDirection'
import { num, optSignedGex, optUsd, pctFrac } from '@/format'

const props = defineProps<{
  symbol: string
  read: OptionsDirectionRead
  spot?: number | null
  callWall?: number | null
  putWall?: number | null
  gammaFlip?: number | null
  regime?: string | null
  totalGexM?: number | null
}>()

function signedScore(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return '+0.0'
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
    dealerThesis = 'Dealer gamma is balanced and no flip is measured. Directional hedging influence is minimal.'
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
    putWallPct != null && callWallPct != null && Math.abs(putWallPct - callWallPct) < 9
  const flipNearPut = flipPct != null && putWallPct != null && Math.abs(flipPct - putWallPct) < 9
  const flipNearCall = flipPct != null && callWallPct != null && Math.abs(flipPct - callWallPct) < 9

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

const squeezeMeter = computed(() => {
  const raw = props.read.score
  const has = raw != null && Number.isFinite(raw)
  const clamped = has ? Math.max(-100, Math.min(100, raw as number)) : 0
  return {
    has,
    value: clamped,
    pct: (clamped + 100) / 2,
    tone: clamped > 8 ? 'bullish' : clamped < -8 ? 'bearish' : 'neutral',
  }
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
      <div class="direction-head">
        <div class="score-block">
          <span class="eyebrow label">{{ symbol }} · UNDERLYING DIRECTION</span>
          <div class="dir-title-line">
            <strong class="fig score-val" :class="squeezeMeter.tone">{{
              signedScore(read.score)
            }}</strong>
            <span class="score-max">/100</span>
            <span class="direction-mark" aria-hidden="true">{{ directionArrow(read.state) }}</span>
            <strong class="fig direction-title">{{ read.headline }}</strong>
            <span class="label confidence" :class="read.confidence">
              {{
                read.confidence === 'wait' ? 'WAIT FOR EVIDENCE' : `${read.confidence} CONVICTION`
              }}
            </span>
          </div>
          <div
            class="sq-meter"
            role="meter"
            :aria-valuemin="-100"
            :aria-valuemax="100"
            :aria-valuenow="squeezeMeter.has ? squeezeMeter.value : undefined"
            :aria-valuetext="`Squeeze score ${signedScore(read.score)} of 100`"
            :aria-label="`Directional squeeze score ${signedScore(read.score)} of 100`"
          >
            <span class="sq-end label bear">BEARISH</span>
            <span class="sq-track">
              <span class="sq-spectrum" aria-hidden="true"><i /><i /><i /><i /><i /></span>
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
          <div class="dir-sub-line">
            <span v-if="regimeInfo.distToFlip" class="flip-dist-chip label">{{
              regimeInfo.distToFlip
            }}</span>
            <span class="dir-subhead label">{{ read.subhead }}</span>
          </div>
        </div>

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
            <span class="action-tag label" :class="regimeInfo.tone">{{ regimeInfo.actionTag }}</span>
          </div>
          <p class="dealer-thesis-text">{{ regimeInfo.dealerThesis }}</p>
          <div class="dealer-derivation" aria-label="How the dealer read was derived">
            <span class="deriv-row label">{{ regimeInfo.derivation }}</span>
            <span class="deriv-row label">{{ regimeInfo.bookDerivation }}</span>
          </div>
          <p v-if="regimeInfo.conflict" class="dealer-conflict label">
            NET GEX AND SPOT-SIDE DISAGREE — net gamma is
            {{ regimeInfo.isPos ? 'long' : 'short' }} across the chain while spot sits
            {{ regimeInfo.isPos ? 'below' : 'above' }} the flip. The hedging read above follows
            spot versus the flip.
          </p>
        </div>
      </div>

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
                  ? '+0.0%'
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
                  ? '+0.00%'
                  : `${read.momentum > 0 ? '+' : ''}${pctFrac(read.momentum, 2)}`
              }}
            </strong>
            <small class="label">{{ read.momentumFresh ? 'FRESH' : 'STALE · EXCLUDED' }}</small>
          </div>
          <div class="evidence-cell activity" :class="read.activity">
            <span class="label">CONTRACT MIX</span>
            <strong class="fig">{{
              read.callPct == null ? '0% C / 0% P' : `${read.callPct}% C / ${read.putPct}% P`
            }}</strong>
            <small class="label">NOT DIRECTION</small>
          </div>
      </div>

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
          <span class="meter-title label">POSITIONING TELEMETRY MAP</span>
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
                <small class="you-are-here">you are here</small>
              </span>
            </div>

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
  border-left: 3px solid var(--direction-tone);
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur-md);
  -webkit-backdrop-filter: var(--glass-blur-md);
  border-radius: var(--r-lg);
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
  --direction-tone: var(--ink-ghost);
}

.positioning-layout {
  display: flex;
  flex-direction: column;
  background: var(--panel);
}

.direction-head {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(220px, 0.85fr);
  align-items: stretch;
  min-width: 0;
}
@media (max-width: 1080px) {
  .direction-head {
    grid-template-columns: 1fr;
  }
}

.score-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  padding: 8px 12px 10px;
  background: var(--void-lift);
  border-right: var(--hair) solid var(--rule);
}
@media (max-width: 1080px) {
  .score-block {
    border-right: 0;
    border-bottom: var(--hair) solid var(--rule);
  }
}

.score-block .eyebrow {
  color: var(--ink-ghost);
  font-size: 9px;
  letter-spacing: 0.06em;
}

.score-val {
  font-size: 1.15rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--direction-tone);
  font-variant-numeric: tabular-nums;
}
.score-val.bullish {
  color: var(--long);
}
.score-val.bearish {
  color: var(--short);
}
.score-val.neutral {
  color: var(--ink-dim);
}
.score-max {
  color: var(--ink-ghost);
  font-family: var(--font-data);
  font-size: 10px;
  font-weight: 600;
}

.sq-meter {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.sq-end {
  font-size: 8px;
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
  border-radius: 1px;
}
.sq-spectrum {
  display: flex;
  height: 100%;
}
.sq-spectrum i {
  flex: 1 1 0;
  display: block;
  height: 100%;
}
.sq-spectrum i:nth-child(1) {
  background: var(--short);
}
.sq-spectrum i:nth-child(2) {
  background: color-mix(in srgb, var(--short) 55%, var(--warn));
}
.sq-spectrum i:nth-child(3) {
  background: var(--ink-faint);
}
.sq-spectrum i:nth-child(4) {
  background: color-mix(in srgb, var(--long) 55%, var(--warn));
}
.sq-spectrum i:nth-child(5) {
  background: var(--long);
}
.sq-zero {
  position: absolute;
  top: -2px;
  bottom: -2px;
  left: 50%;
  width: 1px;
  background: var(--ink);
  transform: translateX(-50%);
  pointer-events: none;
}
.sq-thumb {
  position: absolute;
  top: 50%;
  width: 8px;
  height: 12px;
  border-radius: 1px;
  background: var(--ink);
  border: var(--hair) solid var(--void-lift);
  transform: translate(-50%, -50%);
  pointer-events: none;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.28);
}
.sq-thumb.bullish {
  background: var(--long);
}
.sq-thumb.bearish {
  background: var(--short);
}

.dir-title-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}
.direction-mark {
  color: var(--direction-tone);
  font-weight: 800;
  font-size: 1rem;
}
.direction-title {
  color: var(--direction-tone);
  font-size: 1.05rem;
  font-weight: 800;
  letter-spacing: 0.02em;
}
.confidence {
  padding: 1px 6px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void);
  font-size: var(--t-micro);
  font-weight: 700;
  border-radius: var(--r-xs);
}
.confidence.high,
.confidence.medium {
  color: var(--direction-tone);
  border-color: color-mix(in srgb, var(--direction-tone) 45%, var(--rule));
}
.confidence.low {
  color: var(--warn);
  border-color: var(--warn);
}
.confidence.wait {
  color: var(--ink-dim);
}

.dir-sub-line {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}
.dir-subhead {
  overflow: hidden;
  color: var(--ink-ghost);
  font-size: 9px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1 1 auto;
}
.flip-dist-chip {
  padding: 1px 6px;
  border: var(--hair) solid var(--warn);
  color: var(--warn);
  background: var(--warn-wash);
  font-size: 9px;
  border-radius: var(--r-xs);
  white-space: nowrap;
}

.dealer-gamma-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 12px 10px;
  min-width: 0;
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

.dealer-hero-row {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
}
.dealer-hero-num {
  font-size: var(--t-fig);
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
  padding: 3px 10px;
  border-radius: var(--r-xs, 2px);
  font-size: var(--t-micro);
  font-weight: 800;
  letter-spacing: 0.06em;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void);
  color: var(--ink-dim);
  box-shadow: var(--glass-specular-subtle);
}
.action-tag.bearish {
  color: var(--put-hi);
  border-color: var(--put);
  background: var(--put-wash);
}
.action-tag.bullish {
  color: var(--call-hi);
  border-color: var(--call);
  background: var(--call-wash);
}

.dealer-thesis-text {
  margin: 0;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.dealer-derivation {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: var(--hair) solid var(--rule);
}
.deriv-row {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 700;
  color: var(--ink-faint);
  letter-spacing: 0.02em;
  white-space: normal;
  line-height: 1.35;
}

.dealer-conflict {
  margin: 6px 0 0;
  padding: 4px 6px;
  border-left: 2px solid var(--warn, var(--ink-dim));
  background: var(--glass-wash, transparent);
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.35;
  white-space: normal;
  text-transform: none;
  letter-spacing: 0;
}

.regime-tag-badge {
  padding: 1px 8px;
  border: var(--hair) solid var(--rule-hi);
  font-size: var(--t-micro);
  font-weight: 700;
  border-radius: var(--r-xs, 2px);
  background: var(--void);
  color: var(--ink-dim);
  box-shadow: var(--glass-specular-subtle);
}
.regime-tag-badge.bullish {
  color: var(--call-hi);
  border-color: var(--call);
  background: var(--call-wash);
}
.regime-tag-badge.bearish {
  color: var(--put-hi);
  border-color: var(--put);
  background: var(--put-wash);
}

.evidence-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  background: var(--glass-border);
  border: 0;
  border-top: var(--hair) solid var(--glass-border);
  border-radius: 0;
  overflow: hidden;
  margin-top: 0;
}
@media (max-width: 700px) {
  .evidence-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.evidence-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 4px 8px;
  background: var(--panel);
  min-width: 0;
}
.evidence-cell > span {
  color: var(--ink-faint);
  font-size: 8px;
  letter-spacing: 0.04em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.evidence-cell strong {
  color: var(--ink);
  font-size: var(--t-micro);
  line-height: 1.15;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.evidence-cell small {
  color: var(--ink-ghost);
  font-size: 8px;
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
  gap: var(--s2);
  padding: 8px 12px 10px;
  background: var(--void);
  border-top: var(--hair) solid var(--rule);
}

.range-meter-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  font-size: var(--t-micro);
  color: var(--ink-faint);
  letter-spacing: 0.08em;
  padding-bottom: 4px;
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
.meter-title {
  font-weight: 700;
  color: var(--ink-ghost);
  font-size: 9px;
  letter-spacing: 0.08em;
}

.range-track-container {
  position: relative;
  width: 100%;
  padding-top: 28px;
  padding-bottom: 14px;
}

.range-track.visual-track {
  position: relative;
  height: 52px;
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
  border-radius: var(--r-xs, 2px);
}
.range-zone.short-gamma {
  background: var(--put-wash);
  border-right: var(--hair) solid color-mix(in srgb, var(--put) 35%, var(--rule));
  justify-content: flex-start;
}
.range-zone.long-gamma {
  background: var(--call-wash);
  border-left: var(--hair) solid color-mix(in srgb, var(--call) 35%, var(--rule));
  justify-content: flex-end;
}
.range-zone.full-zone {
  border: 0;
}
.zone-label {
  font: 800 9px var(--font-display);
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
  top: -8px;
  bottom: -8px;
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
  top: -3px;
  bottom: -3px;
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
  padding: 1px 5px;
  border-radius: var(--r-xs, 2px);
  font-size: var(--t-micro);
  line-height: 1.1;
  white-space: nowrap;
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
}
.marker-pill.put {
  color: var(--put-hi);
  border-color: var(--put);
  background: var(--put-wash);
}
.marker-pill.call {
  color: var(--call-hi);
  border-color: var(--call);
  background: var(--call-wash);
}
.marker-pill.flip {
  color: var(--warn);
  border-color: var(--warn);
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
  background: var(--panel-hi);
  font-weight: 700;
  top: 16px;
}

.pill-label {
  font-size: var(--t-micro);
  opacity: 0.8;
}
.pill-val {
  font-family: var(--font-data);
  font-weight: 700;
}
.pill-dist {
  font-size: var(--t-micro);
  opacity: 0.85;
  margin-left: 2px;
}

.you-are-here {
  display: block;
  font-size: 7.5px;
  color: var(--phosphor);
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: lowercase;
}
</style>
