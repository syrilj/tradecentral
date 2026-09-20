<script setup lang="ts">
import { computed } from 'vue'
import { num } from '@/format'
import type { GammaRegime } from '@/regimeContracts'
import type { FairValue } from '@/levelStructure'

export interface TrajectoryStep {
  price: number
  tag: string
  desc: string
  isActive?: boolean
  tone?: 'bullish' | 'bearish' | 'warn' | 'neutral'
}

const props = withDefaults(
  defineProps<{
    symbol: string
    spot: number | null
    regime?: GammaRegime | null
    gammaFlip?: number | null
    callWall?: number | null
    putWall?: number | null
    pinStrike?: number | null
    fairValue?: FairValue | null
    quadrantTitle?: string | null
  }>(),
  {
    regime: null,
    gammaFlip: null,
    callWall: null,
    putWall: null,
    pinStrike: null,
    fairValue: null,
    quadrantTitle: null,
  },
)

/** Half-width of the neutral band around the flip, as a fraction of spot. */
const FLIP_BAND_PCT = 0.0025

const atFlip = computed(() => {
  const s = props.spot
  const flip = props.gammaFlip
  if (s == null || flip == null || !(s > 0)) return false
  return Math.abs((s - flip) / s) <= FLIP_BAND_PCT
})

const title = computed(() => {
  if (atFlip.value) return 'FLAT / UNDECIDED AT FLIP'
  if (props.quadrantTitle) return props.quadrantTitle.toUpperCase()
  if (props.regime === 'short') return 'FORWARD NEGATIVE SLIDE'
  if (props.regime === 'long') return 'FORWARD POSITIVE RAMP'
  return 'FORWARD REGIME TRAJECTORY'
})

const steps = computed<TrajectoryStep[]>(() => {
  const sym = props.symbol || 'SPY'
  if (
    props.spot == null &&
    props.gammaFlip == null &&
    props.callWall == null &&
    props.putWall == null
  ) {
    return []
  }
  const flip = props.gammaFlip
  const callW = props.callWall
  const putW = props.putWall
  const pin = props.pinStrike
  const list: TrajectoryStep[] = []

  if (props.regime === 'short' && !atFlip.value) {
    if (flip != null) {
      list.push({
        price: flip,
        tag: '(Break of Support)',
        desc: `If ${sym} breaks below ${num(flip, 0)}, negative gamma increases.`,
        isActive: false,
        tone: 'warn',
      })
    }
    if (putW != null) {
      list.push({
        price: putW,
        tag: '(High Risk Level)',
        desc: `Break below ${num(putW, 0)} triggers acceleration of downside.`,
        isActive: true,
        tone: 'bearish',
      })
    }
    return list
  }

  if (props.regime === 'long' && !atFlip.value) {
    if (pin != null) {
      list.push({
        price: pin,
        tag: '(Pin Magnet)',
        desc: `High gamma concentration creates strong pull toward ${num(pin, 0)}.`,
        isActive: true,
        tone: 'bullish',
      })
    }
    if (callW != null) {
      list.push({
        price: callW,
        tag: '(Resistance Wall)',
        desc: `At ${num(callW, 0)}, dealer supply builds, damping upward extensions.`,
        isActive: false,
        tone: 'bullish',
      })
    }
    if (flip != null) {
      list.push({
        price: flip,
        tag: '(Lower Boundary)',
        desc: `Damping holds as long as price defends the flip at ${num(flip, 0)}.`,
        isActive: false,
        tone: 'warn',
      })
    }
    return list
  }

  if (callW != null) {
    list.push({
      price: callW,
      tag: '(Upside Breakout)',
      desc: `Break above ${num(callW, 0)} triggers call squeeze and dealer buying.`,
      isActive: false,
      tone: 'bullish',
    })
  }
  if (flip != null) {
    list.push({
      price: flip,
      tag: '(Neutral Axis S*)',
      desc: `Currently straddling the flip at ${num(flip, 0)}. Awaiting directional resolution.`,
      isActive: true,
      tone: 'warn',
    })
  }
  if (putW != null) {
    list.push({
      price: putW,
      tag: '(Downside Breakdown)',
      desc: `Loss of ${num(putW, 0)} initiates negative gamma slide.`,
      isActive: false,
      tone: 'bearish',
    })
  }
  return list
})
</script>

<template>
  <div class="forward-trajectory-card">
    <div class="card-header">
      <div class="header-left">
        <span class="card-eyebrow font-mono">REGIME TRAJECTORY</span>
        <h3 class="card-title font-mono font-bold">{{ title }}</h3>
      </div>
      <div
        v-if="atFlip || fairValue"
        class="mean-pull-badge font-mono"
        :class="atFlip ? 'dir-at' : fairValue ? `dir-${fairValue.direction}` : ''"
      >
        <template v-if="atFlip">FLAT / UNDECIDED AT FLIP</template>
        <template v-else-if="fairValue">
          {{
            fairValue.direction === 'at'
              ? 'AT EQUILIBRIUM'
              : fairValue.direction === 'up'
                ? '▲ PULL UP'
                : '▼ PULL DOWN'
          }}
          {{ fairValue.distancePct >= 0 ? '+' : '' }}{{ num(fairValue.distancePct, 1) }}%
        </template>
      </div>
    </div>

    <!-- Step-by-step cascade ladder -->
    <div v-if="steps.length > 0" class="steps-stack">
      <div
        v-for="step in steps"
        :key="step.price"
        class="step-card"
        :class="[{ active: step.isActive }, `tone-${step.tone}`]"
      >
        <div class="step-head">
          <span class="step-price font-mono font-bold">${{ num(step.price, 0) }}</span>
          <span class="step-tag font-mono font-semibold">{{ step.tag }}</span>
        </div>
        <p class="step-desc font-mono">{{ step.desc }}</p>
      </div>
    </div>
    <div v-else class="empty-steps font-mono text-ink-dim">
      Trajectory levels unmeasured (no active strikes in range).
    </div>

    <!-- Equilibrium Anchors if available -->
    <div v-if="fairValue && fairValue.anchors?.length" class="anchors-row font-mono">
      <span class="anchors-label text-ink-dim">Equilibrium Anchors:</span>
      <span v-for="a in fairValue.anchors" :key="a.label" class="anchor-pill">
        {{ a.label }} <b>${{ num(a.price, 2) }}</b>
      </span>
    </div>

    <!-- Card Footer -->
    <div class="card-footer">
      <span class="sub-caption font-mono text-ink-dim">
        Levels derived from GEX, OI, and dealer positioning.
      </span>
    </div>
  </div>
</template>

<style scoped>
.forward-trajectory-card {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: 0.875rem 1rem;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 0.5rem;
  box-sizing: border-box;
  overflow: hidden;
  min-width: 0;
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.card-eyebrow {
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  color: var(--ink-dim);
}

.card-title {
  font-size: 0.9375rem;
  color: var(--ink);
  margin: 0;
}

.mean-pull-badge {
  font-size: var(--t-micro);
  padding: 0.2rem 0.5rem;
  border-radius: var(--r-xs);
}

.mean-pull-badge.dir-up {
  background: var(--call-wash);
  color: var(--call-hi);
  border: 1px solid var(--call-dim);
}

.mean-pull-badge.dir-down {
  background: var(--put-wash);
  color: var(--put-hi);
  border: 1px solid var(--put-dim);
}

.mean-pull-badge.dir-at {
  background: var(--panel-hi);
  color: var(--ink-soft);
  border: 1px solid var(--rule-hi);
}

.steps-stack {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.step-card {
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  border-radius: var(--r-sm);
  padding: 0.625rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  transition: all var(--dur-fast) ease;
}

.step-card.active {
  border-color: var(--phosphor);
  background: var(--phosphor-wash);
}

.step-head {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}

.step-price {
  font-size: 0.9375rem;
  color: var(--ink);
}

.step-tag {
  font-size: 0.75rem;
  color: var(--ink-dim);
}

.step-card.active .step-tag {
  color: var(--phosphor);
}

.step-desc {
  font-size: var(--t-micro);
  color: var(--ink-soft);
  line-height: 1.35;
  margin: 0;
}

.empty-steps {
  padding: 1rem 0;
  font-size: var(--t-tiny);
  text-align: center;
}

.anchors-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  font-size: var(--t-nano);
}

.anchor-pill {
  background: var(--panel-raise);
  border: 1px solid var(--rule);
  padding: 0.125rem 0.375rem;
  border-radius: 2px;
  color: var(--ink-soft);
}

.anchor-pill b {
  color: var(--ink);
}

.card-footer {
  padding-top: 0.25rem;
  border-top: 1px solid var(--rule-faint);
}

.sub-caption {
  font-size: var(--t-micro);
}
</style>
