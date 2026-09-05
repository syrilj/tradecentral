<script setup lang="ts">
/**
 * TransitionRiskGauge.vue
 *
 * Dedicated gauge visualizing CUSUM/BOCPD changepoint hazard probability,
 * regime tenure run-length, and continuous gamma flip proximity.
 */
import { computed } from 'vue'
import type { TransitionRisk, TransitionRiskLevel } from '@/regimeContracts'
import { DASH, num, pctFrac } from '@/format'
import Panel from '@/components/Panel.vue'

const props = withDefaults(
  defineProps<{
    transition?: TransitionRisk | null
    measurable?: boolean
  }>(),
  {
    transition: null,
    // Absent data must NOT look measured: when the caller has no payload yet
    // (still loading), `measurable` is undefined and the gauge must fall back
    // to DASH everywhere rather than spoofing 0% hazard / 100% stability.
    measurable: false,
  },
)

const hazardScore = computed<number>(() => props.transition?.changepointProb5d ?? 0)
const hazardLevel = computed<TransitionRiskLevel>(() => props.transition?.level ?? 'low')
// A null field is "the changepoint model reported nothing", which is not the
// same claim as 100% stability or a zero-bar tenure. Each row below renders an
// em dash for null instead of a placebo number.
const stabilityScore = computed<number | null>(() => props.transition?.stabilityScore ?? null)
const mapRunLength = computed<number | null>(() => props.transition?.mapRunLength ?? null)
const expectedRunLength = computed<number | null>(() => props.transition?.expectedRunLength ?? null)

const strokeDashoffset = computed<number>(() => {
  // Semi-circle SVG arc circumference ~ 251.3
  const progress = Math.min(1.0, Math.max(0.0, hazardScore.value))
  return 251.3 * (1 - progress)
})

const levelClass = computed<string>(() => `lvl-${hazardLevel.value}`)
const isMeasured = computed<boolean>(
  () => props.measurable !== false && props.transition?.measured !== false,
)
</script>

<template>
  <Panel
    label="TRANSITION RISK & STABILITY"
    meta="CUSUM · BOCPD"
    index="02"
    class="transition-gauge-panel"
  >
    <div class="gauge-container">
      <!-- Arc SVG Gauge -->
      <div class="arc-wrapper">
        <svg viewBox="0 0 200 110" class="gauge-svg" role="img" aria-label="Transition Risk Gauge">
          <!-- Background track -->
          <path
            d="M 20 100 A 80 80 0 0 1 180 100"
            fill="none"
            stroke="var(--void)"
            stroke-width="14"
            stroke-linecap="round"
          />
          <!-- Active Hazard arc -->
          <path
            d="M 20 100 A 80 80 0 0 1 180 100"
            fill="none"
            stroke="currentColor"
            stroke-width="14"
            stroke-linecap="round"
            stroke-dasharray="251.3"
            :stroke-dashoffset="isMeasured ? strokeDashoffset : 251.3"
            class="active-arc"
            :class="isMeasured ? levelClass : 'lvl-unmeasured'"
          />
        </svg>
        <div class="gauge-center-readout">
          <span class="hazard-pct mono">{{ isMeasured ? pctFrac(hazardScore, 1) : DASH }}</span>
          <span class="hazard-tag" :class="isMeasured ? levelClass : 'lvl-unmeasured'">
            {{ isMeasured ? `${hazardLevel.toUpperCase()} HAZARD` : 'UNMEASURED' }}
          </span>
        </div>
      </div>

      <!-- Metrics Breakdown Grid -->
      <div class="gauge-stats">
        <div class="stat-cell">
          <span class="st-label">Stability Index</span>
          <span class="st-val mono">{{
            isMeasured && stabilityScore != null ? pctFrac(stabilityScore, 0) : DASH
          }}</span>
        </div>
        <div class="stat-cell">
          <span class="st-label">5d Horizon P(τ)</span>
          <span class="st-val mono">{{
            isMeasured && transition?.changepointProb5d != null
              ? pctFrac(transition.changepointProb5d, 1)
              : DASH
          }}</span>
        </div>
        <div class="stat-cell">
          <span class="st-label">Regime Tenure</span>
          <span class="st-val mono">{{
            isMeasured && mapRunLength != null ? `${mapRunLength} bars` : DASH
          }}</span>
        </div>
        <div class="stat-cell">
          <span class="st-label">Expected Tenure</span>
          <span class="st-val mono">{{
            isMeasured && expectedRunLength != null ? `${num(expectedRunLength, 0)} bars` : DASH
          }}</span>
        </div>
      </div>
    </div>
  </Panel>
</template>

<style scoped>
.gauge-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s3);
}

.arc-wrapper {
  position: relative;
  width: 200px;
  height: 110px;
}

.gauge-svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}

.active-arc {
  transition: stroke-dashoffset var(--dur-slow) var(--ease-out);
}

.active-arc.lvl-low {
  stroke: var(--call);
}
.active-arc.lvl-moderate {
  stroke: var(--warn);
}
.active-arc.lvl-high {
  stroke: var(--warn);
}
.active-arc.lvl-critical {
  stroke: var(--put);
}
.active-arc.lvl-unmeasured {
  stroke: var(--rule-hi);
}

.gauge-center-readout {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.hazard-pct {
  font-size: var(--t-fig);
  font-weight: 800;
  color: var(--ink);
  font-family: var(--font-data);
}

.hazard-tag {
  font-family: var(--font-ui);
  font-size: 0.6875rem;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: var(--r-xs);
  letter-spacing: 0.04em;
}

.hazard-tag.lvl-low {
  color: var(--call-hi);
  background: var(--call-wash);
}
.hazard-tag.lvl-moderate {
  color: var(--warn);
  background: var(--warn-wash);
}
.hazard-tag.lvl-high {
  color: var(--warn);
  background: var(--warn-wash);
}
.hazard-tag.lvl-critical {
  color: var(--put-hi);
  background: var(--put-wash);
}
.hazard-tag.lvl-unmeasured {
  color: var(--ink-dim);
  background: var(--void-lift);
}

.gauge-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s3);
  width: 100%;
  padding-top: var(--s3);
  border-top: var(--hair) solid var(--rule);
}

.stat-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.st-label {
  font-family: var(--font-ui);
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--ink-dim);
}

.st-val {
  font-family: var(--font-data);
  font-size: 0.875rem;
  font-weight: 700;
  color: var(--ink);
}

.mono {
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
}
</style>
