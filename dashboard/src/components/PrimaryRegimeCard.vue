<script setup lang="ts">
/**
 * PrimaryRegimeCard.vue
 *
 * Instrument-grade hero card for the Multi-Dimensional Regime State (R5).
 * Visual Hierarchy:
 *  1. Hero Regime Badge with semantic color tones and pulse indicator.
 *  2. Calibrated Confidence Meter with multi-factor breakdown and penalty tags.
 *  3. Transition Risk Alert Glow when hazard T_risk >= 0.45.
 *  4. Normalized Probability Simplex Ribbon (p_bull + p_bear + p_neutral = 1.0000).
 *  5. Structural Levels Quick Strip (Spot, VWAP, Gamma Flip, Call/Put Walls).
 */
import { computed } from 'vue'
import type { MarketRegimePayload, PrimaryRegimeType, ConfidenceBand } from '@/regimeContracts'
import { DASH, pctFrac, usd, signed, signedPct } from '@/format'
import Panel from '@/components/Panel.vue'

const props = withDefaults(
  defineProps<{
    payload?: MarketRegimePayload | null
    symbol?: string
    spot?: number | null
    loading?: boolean
  }>(),
  {
    payload: null,
    symbol: 'SPY',
    spot: null,
    loading: false,
  },
)

const isMeasurable = computed<boolean>(() => {
  if (!props.payload) return false
  return props.payload.quality?.measurable !== false && props.payload.primary !== 'unmeasurable'
})

/**
 * First-load state: no payload yet while a request is in flight. This is NOT
 * "unmeasured" (a data verdict) -- it is "not yet computed". Rendering it as
 * UNMEASURED made a normal cold start look like broken telemetry.
 */
const isMeasuring = computed<boolean>(() => !props.payload && props.loading)

const activeRegime = computed<PrimaryRegimeType>(() => {
  return props.payload?.primary ?? 'unmeasurable'
})

const regimeLabel = computed<string>(() => {
  if (isMeasuring.value) return 'MEASURING REGIME'
  if (!props.payload || !isMeasurable.value) return 'REGIME UNMEASURED'
  const raw = props.payload.primaryLabel || activeRegime.value.replace(/_/g, ' ')
  return raw.toUpperCase()
})

const regimeDescription = computed<string>(() => {
  if (isMeasuring.value) {
    return 'Computing the multi-model market state. The first measurement after startup prices the option chain and can take up to ~90 seconds; it updates automatically.'
  }
  switch (activeRegime.value) {
    case 'bull_trend':
      return 'Persistent upward drift with positive velocity and supportive market structure.'
    case 'bear_trend':
      return 'Downside price expansion with negative velocity and elevated distribution.'
    case 'compression_range':
      return 'Compressed volatility corridor; low variance and pinned structural boundary.'
    case 'mean_reverting':
      return 'Sub-diffusive oscillations with fast Ornstein-Uhlenbeck half-life reversion.'
    case 'vol_expansion_breakout':
      return 'High-velocity variance shock breaking through structural volatility bounds.'
    case 'uncertain_transitional':
      return 'Inflection boundary: spot testing regime threshold. Volatility expansion and directional continuation trigger on boundary break.'
    case 'unmeasurable':
    default:
      return props.payload?.quality?.reason || 'Telemetry insufficient to compute market state.'
  }
})

const regimeClass = computed<string>(() => {
  if (!isMeasurable.value || activeRegime.value === 'unmeasurable') return 'regime-unmeasured'
  switch (activeRegime.value) {
    case 'bull_trend':
      return 'regime-bull'
    case 'bear_trend':
      return 'regime-bear'
    case 'compression_range':
      return 'regime-compression'
    case 'mean_reverting':
      return 'regime-reverting'
    case 'vol_expansion_breakout':
      return 'regime-breakout'
    case 'uncertain_transitional':
      return 'regime-transitional'
    default:
      return 'regime-unmeasured'
  }
})

// Confidence
const confidenceScore = computed<number | null>(() => {
  return props.payload?.confidence?.score ?? null
})

const confidenceBand = computed<ConfidenceBand>(() => {
  return props.payload?.confidence?.band ?? 'low'
})

/** A missing score is "nothing calibrated this", not "low confidence". Showing
 *  the band chip as LOW next to an em dash reads as a measured verdict; it is
 *  the absence of one. */
const confidenceBandLabel = computed<string>(() => {
  if (isMeasuring.value) return 'MEASURING'
  if (confidenceScore.value === null || !isMeasurable.value) return 'UNCALIBRATED'
  return confidenceBand.value.toUpperCase()
})

const formattedConfidence = computed<string>(() => {
  if (confidenceScore.value === null || !isMeasurable.value) return DASH
  return pctFrac(confidenceScore.value, 1)
})

const penaltyFactors = computed<string[]>(() => {
  return props.payload?.confidence?.penaltyFactors ?? []
})

// Transition Risk & Alert Glow
const transitionRisk = computed<number>(() => {
  return props.payload?.transition?.changepointProb5d ?? 0
})

const isHighHazard = computed<boolean>(() => {
  return (
    isMeasurable.value &&
    (transitionRisk.value >= 0.45 ||
      props.payload?.transition?.level === 'critical' ||
      props.payload?.transition?.level === 'high')
  )
})

// Probability Simplex
const probBull = computed<number>(() => props.payload?.probabilities?.bullish ?? 0.3333)
const probBear = computed<number>(() => props.payload?.probabilities?.bearish ?? 0.3333)
const probNeut = computed<number>(() => props.payload?.probabilities?.neutral ?? 0.3334)

// Levels
const currentSpot = computed<number | null>(() => props.spot ?? props.payload?.spot ?? null)
const kalmanVelocity = computed<number | null>(() => props.payload?.trend?.kalmanVelocity ?? null)
const sessionVwap = computed<number | null>(() => props.payload?.levels?.sessionVwap ?? null)
const gammaFlip = computed<number | null>(() => props.payload?.levels?.gammaFlip ?? null)
const callWall = computed<number | null>(() => props.payload?.levels?.callWall ?? null)
const putWall = computed<number | null>(() => props.payload?.levels?.putWall ?? null)

function levelDeltaPct(level: number | null): string {
  if (!currentSpot.value || !level) return DASH
  const pctVal = ((currentSpot.value - level) / level) * 100
  return signedPct(pctVal, 1)
}
</script>

<template>
  <Panel
    :label="`PRIMARY REGIME STATE · ${symbol}`"
    :meta="payload?.asof_utc ? `ASOF ${payload.asof_utc.slice(11, 19)} UTC` : 'LIVE'"
    index="01"
    :live="isMeasurable"
    class="primary-regime-card"
    :class="[{ 'hazard-alert-glow': isHighHazard }]"
  >
    <div class="card-layout">
      <!-- Top Row: Hero Regime Badge & Confidence Meter -->
      <div class="hero-section" :class="regimeClass">
        <div class="regime-hero-badge">
          <div class="badge-status-ring">
            <span class="status-pulse" />
          </div>
          <div class="badge-text-group">
            <div class="regime-category-tag">MULTI-DIMENSIONAL RECONCILED STATE</div>
            <h1 class="regime-hero-title">{{ regimeLabel }}</h1>
            <p class="regime-hero-desc">{{ regimeDescription }}</p>
            <div v-if="kalmanVelocity != null && isMeasurable" class="speed-read">
              <span class="speed-label font-mono">KINEMATIC SPEED</span>
              <span
                class="speed-val font-mono"
                :class="{
                  'c-pos': kalmanVelocity > 0,
                  'c-neg': kalmanVelocity < 0,
                }"
              >
                {{ signed(kalmanVelocity, 4) }}
              </span>
            </div>
          </div>
        </div>

        <!-- Confidence Gauge Pill -->
        <div class="confidence-gauge-box" :class="`band-${confidenceBand}`">
          <div class="conf-header">
            <span class="conf-title">CALIBRATED CONFIDENCE</span>
            <span class="conf-band-chip">{{ confidenceBandLabel }}</span>
          </div>
          <div class="conf-figure fig">{{ formattedConfidence }}</div>
          <div class="conf-meter-bar">
            <div
              class="conf-fill"
              :style="{
                width:
                  isMeasurable && confidenceScore !== null
                    ? `${Math.min(100, Math.max(0, confidenceScore * 100))}%`
                    : '0%',
              }"
            />
          </div>
          <div v-if="penaltyFactors.length > 0" class="penalty-chips">
            <span v-for="(factor, idx) in penaltyFactors" :key="idx" class="penalty-tag">
              ⚠ {{ factor }}
            </span>
          </div>
          <div
            v-if="confidenceBandLabel === 'UNCALIBRATED' && isMeasurable"
            class="conf-uncalibrated-hint font-mono"
          >
            Reconciled with live chain &middot; score withheld to prevent false precision
          </div>
        </div>
      </div>

      <!-- Transition Risk Alert Glow Banner (When Hazard >= 0.45) -->
      <div v-if="isHighHazard" class="hazard-banner">
        <span class="hazard-icon">⚡</span>
        <div class="hazard-text">
          <span class="hazard-title"
            >ELEVATED TRANSITION HAZARD ({{ pctFrac(transitionRisk, 0) }})</span
          >
          <span class="hazard-sub"
            >Active change-point probability detected. Regime persistence reduced.</span
          >
        </div>
      </div>

      <!-- Probability Simplex Ribbon (p_bull + p_bear + p_neutral = 1.0000) -->
      <div v-if="isMeasurable && payload?.probabilities" class="probability-simplex-box">
        <div class="simplex-header">
          <span class="simplex-title">PROBABILITY SIMPLEX DISTRIBUTION</span>
          <span class="simplex-sum">∑ p = 1.0000</span>
        </div>
        <div class="simplex-bar">
          <div
            class="seg seg-bull"
            :style="{ width: `${probBull * 100}%` }"
            :title="`Bullish: ${pctFrac(probBull, 1)}`"
          >
            <span v-if="probBull >= 0.15" class="seg-label">BULL {{ pctFrac(probBull, 0) }}</span>
          </div>
          <div
            class="seg seg-neut"
            :style="{ width: `${probNeut * 100}%` }"
            :title="`Neutral: ${pctFrac(probNeut, 1)}`"
          >
            <span v-if="probNeut >= 0.15" class="seg-label">NEUT {{ pctFrac(probNeut, 0) }}</span>
          </div>
          <div
            class="seg seg-bear"
            :style="{ width: `${probBear * 100}%` }"
            :title="`Bearish: ${pctFrac(probBear, 1)}`"
          >
            <span v-if="probBear >= 0.15" class="seg-label">BEAR {{ pctFrac(probBear, 0) }}</span>
          </div>
        </div>
      </div>

      <!-- Structural Levels Strip -->
      <div class="levels-strip">
        <div class="level-cell">
          <span class="lvl-label">SPOT PRICE</span>
          <span class="lvl-val mono">{{ usd(currentSpot) }}</span>
        </div>
        <div class="level-cell">
          <span class="lvl-label">SESSION VWAP</span>
          <span class="lvl-val mono">{{ usd(sessionVwap) }}</span>
          <span v-if="sessionVwap" class="lvl-sub">{{ levelDeltaPct(sessionVwap) }}</span>
        </div>
        <div class="level-cell">
          <span class="lvl-label">GAMMA FLIP</span>
          <span class="lvl-val mono">{{ gammaFlip ? usd(gammaFlip) : 'none in range' }}</span>
          <span v-if="gammaFlip" class="lvl-sub">{{ levelDeltaPct(gammaFlip) }}</span>
        </div>
        <div class="level-cell">
          <span class="lvl-label">CALL WALL</span>
          <span class="lvl-val mono">{{ usd(callWall) }}</span>
          <span v-if="callWall" class="lvl-sub">{{ levelDeltaPct(callWall) }}</span>
        </div>
        <div class="level-cell">
          <span class="lvl-label">PUT WALL</span>
          <span class="lvl-val mono">{{ usd(putWall) }}</span>
          <span v-if="putWall" class="lvl-sub">{{ levelDeltaPct(putWall) }}</span>
        </div>
      </div>
    </div>
  </Panel>
</template>

<style scoped>
.primary-regime-card {
  position: relative;
  transition: border-color var(--dur) var(--ease-out);
}

.primary-regime-card.hazard-alert-glow {
  border-color: var(--warn);
}

.card-layout {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.hero-section {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 260px);
  gap: var(--s4);
  padding: var(--s4);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  position: relative;
  overflow: visible;
  min-width: 0;
  align-items: start;
}

@media (max-width: 900px) {
  .hero-section {
    grid-template-columns: 1fr;
  }
}

.regime-hero-badge {
  display: flex;
  align-items: flex-start;
  gap: var(--s3);
}

.badge-status-ring {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--rule-hi);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 6px;
  flex-shrink: 0;
}

.status-pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: inherit;
}

.badge-text-group {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
}

.regime-category-tag {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--ink-dim);
}

.regime-hero-title {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--t-fig);
  font-weight: 800;
  letter-spacing: var(--track-display);
  line-height: 1.15;
  color: var(--ink);
}

.regime-hero-desc {
  margin: 0;
  font-family: var(--font-ui);
  font-size: var(--t-small);
  color: var(--ink-soft);
  line-height: 1.4;
  max-width: 600px;
}

.speed-read {
  display: flex;
  align-items: baseline;
  gap: var(--s2);
  margin-top: var(--s2);
  min-width: 0;
}

.speed-label {
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--ink-dim);
}

.speed-val {
  font-size: var(--t-small);
  font-weight: 800;
  color: var(--ink);
}

.speed-val.c-pos {
  color: var(--call-hi);
}

.speed-val.c-neg {
  color: var(--put-hi);
}

/* Regime Semantic Styles */
.hero-section.regime-bull {
  border-color: var(--call-dim);
  background: var(--panel);
}
.hero-section.regime-bull .badge-status-ring {
  background: var(--call);
}
.hero-section.regime-bull .regime-hero-title {
  color: var(--call-hi);
}

.hero-section.regime-bear {
  border-color: var(--put-dim);
  background: var(--panel);
}
.hero-section.regime-bear .badge-status-ring {
  background: var(--put);
}
.hero-section.regime-bear .regime-hero-title {
  color: var(--put-hi);
}

.hero-section.regime-compression {
  border-color: var(--rule-hi);
  background: var(--panel);
}
.hero-section.regime-compression .badge-status-ring {
  background: var(--cat-1);
}
.hero-section.regime-compression .regime-hero-title {
  color: var(--badge-sweep);
}

.hero-section.regime-reverting {
  border-color: var(--rule-hi);
  background: var(--panel);
}
.hero-section.regime-reverting .badge-status-ring {
  background: var(--cat-4);
}
.hero-section.regime-reverting .regime-hero-title {
  color: var(--badge-split);
}

.hero-section.regime-breakout {
  border-color: var(--warn);
  background: var(--panel);
}
.hero-section.regime-breakout .badge-status-ring {
  background: var(--warn);
}
.hero-section.regime-breakout .regime-hero-title {
  color: var(--warn);
}

.hero-section.regime-transitional {
  border-color: var(--warn);
  background: var(--panel);
}
.hero-section.regime-transitional .badge-status-ring {
  background: var(--warn);
}
.hero-section.regime-transitional .regime-hero-title {
  color: var(--warn);
}

.hero-section.regime-unmeasured {
  border-color: var(--rule-faint);
  background: var(--void-lift);
}

/* Confidence Gauge Box */
.confidence-gauge-box {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: var(--s2) var(--s3);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  gap: var(--s1);
  min-width: 0;
}

.conf-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.conf-title {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--ink-dim);
}

.conf-band-chip {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 800;
  padding: 1px 5px;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
}

.band-high .conf-band-chip {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border-color: var(--phosphor-dim);
}
.band-moderate .conf-band-chip {
  color: var(--warn);
  background: var(--warn-wash);
  border-color: var(--warn);
}
.band-low .conf-band-chip {
  color: var(--ink-dim);
  background: var(--void-lift);
  border-color: var(--rule-hi);
}

.conf-figure {
  font-size: var(--t-fig);
  font-weight: 700;
  color: var(--ink);
  line-height: 1;
}

.conf-meter-bar {
  height: 6px;
  background: var(--void);
  border-radius: var(--r-capsule);
  overflow: hidden;
  border: var(--hair) solid var(--rule);
}

.conf-fill {
  height: 100%;
  background: var(--phosphor);
  border-radius: var(--r-capsule);
}

.band-high .conf-fill {
  background: var(--phosphor);
}
.band-moderate .conf-fill {
  background: var(--warn);
}
.band-low .conf-fill {
  background: var(--ink-faint);
}

.penalty-chips {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 4px;
  min-width: 0;
}

.penalty-tag {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  color: var(--warn);
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.conf-uncalibrated-hint {
  font-size: 0.65rem;
  color: var(--ink-faint);
  line-height: 1.35;
  margin-top: 4px;
}

/* Hazard Banner */
.hazard-banner {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: var(--s2) var(--s3);
  background: var(--warn-wash);
  border: var(--hair) solid var(--warn);
  border-radius: var(--r-sm);
}

.hazard-icon {
  font-size: var(--t-body);
  color: var(--warn);
}

.hazard-text {
  display: flex;
  flex-direction: column;
}

.hazard-title {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 700;
  color: var(--warn);
}

.hazard-sub {
  font-family: var(--font-ui);
  font-size: var(--t-tiny);
  color: var(--ink-soft);
}

/* Probability Simplex */
.probability-simplex-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--s2) var(--s3);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.simplex-header {
  display: flex;
  justify-content: space-between;
  font-family: var(--font-data);
  font-size: var(--t-nano);
  color: var(--ink-dim);
}

.simplex-bar {
  display: flex;
  height: 20px;
  border-radius: var(--r-xs);
  overflow: hidden;
  border: var(--hair) solid var(--rule);
  background: var(--void);
}

.seg {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.seg-bull {
  background: var(--call-wash);
  border-right: var(--hair) solid var(--call);
}
.seg-neut {
  background: var(--wash-3);
  border-right: var(--hair) solid var(--rule-hi);
}
.seg-bear {
  background: var(--put-wash);
}

.seg-label {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  color: var(--ink);
  white-space: nowrap;
}

/* Levels Strip */
.levels-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--s2);
  padding: var(--s2) var(--s3);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  min-width: 0;
}

@media (max-width: 800px) {
  .levels-strip {
    grid-template-columns: repeat(2, 1fr);
  }
}

.level-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.lvl-label {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  color: var(--ink-dim);
  letter-spacing: 0.04em;
}

.lvl-val {
  font-size: var(--t-small);
  font-weight: 700;
  color: var(--ink);
}

.lvl-sub {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  color: var(--ink-dim);
}

.mono {
  font-family: var(--font-data);
}
</style>
