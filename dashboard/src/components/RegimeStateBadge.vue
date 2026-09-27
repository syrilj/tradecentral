<script setup lang="ts">
/**
 * RegimeStateBadge.vue
 *
 * Instrument-grade badge displaying active volatility/flow market regime state,
 * scale-free regime conviction strength, and dominant gravitational pull vector.
 *
 * Adheres strictly to tokens.css design variables, monospace data figures,
 * and zero-spoofing / missing data protocols.
 */
import { computed } from 'vue'
import type {
  PriceDrawTelemetryPayload,
  MarketRegimeType,
  DominantDirectionType,
  PriceDrawLevel,
} from '@/priceDrawContracts'
import { DASH, pctFrac, usd, signedPct } from '@/format'

const props = withDefaults(
  defineProps<{
    payload?: PriceDrawTelemetryPayload | null
    regimeState?: MarketRegimeType
    regimeLabel?: string
    regimeStrength?: number | null
    dominantDirection?: DominantDirectionType
    primaryMagnet?: PriceDrawLevel | null
    measurable?: boolean
    compact?: boolean
    showVector?: boolean
    showStrength?: boolean
    showPrimaryMagnet?: boolean
  }>(),
  {
    payload: null,
    regimeState: undefined,
    regimeLabel: undefined,
    regimeStrength: undefined,
    dominantDirection: undefined,
    primaryMagnet: undefined,
    measurable: undefined,
    compact: false,
    showVector: true,
    showStrength: true,
    showPrimaryMagnet: false,
  },
)

const activeState = computed<MarketRegimeType>(() => {
  if (props.regimeState) return props.regimeState
  if (props.payload?.regime_state) return props.payload.regime_state
  return 'unmeasurable'
})

const isMeasurable = computed<boolean>(() => {
  if (props.measurable !== undefined) return props.measurable
  if (props.payload?.quality) return props.payload.quality.measurable
  return activeState.value !== 'unmeasurable'
})

function getStandardRegimeLabel(state: MarketRegimeType): string {
  switch (state) {
    case 'volatility_dampening':
      return 'VOL DAMPENING · LONG Γ'
    case 'volatility_amplification':
      return 'VOL AMPLIFICATION · SHORT Γ'
    case 'charm_decay_selling':
      return 'CHARM DECAY · SELLING DRIFT'
    case 'charm_decay_buying':
      return 'CHARM DECAY · BUYING DRIFT'
    case 'vanna_vol_expansion':
      return 'VANNA EXPANSION · VOL SHOCK'
    case 'neutral_transition':
      return 'TRANSITION STRADDLE · Γ-FLIP'
    case 'unmeasurable':
    default:
      return 'REGIME UNMEASURED'
  }
}

const displayRegimeLabel = computed<string>(() => {
  if (!isMeasurable.value || activeState.value === 'unmeasurable') {
    return 'REGIME UNMEASURED'
  }
  if (props.regimeLabel) return props.regimeLabel
  return getStandardRegimeLabel(activeState.value)
})

const activeStrength = computed<number | null>(() => {
  if (!isMeasurable.value) return null
  if (props.regimeStrength !== undefined) return props.regimeStrength
  return props.payload?.regime_strength ?? null
})

const formattedStrength = computed<string>(() => {
  const val = activeStrength.value
  if (val === null || !Number.isFinite(val) || !isMeasurable.value) return DASH
  return pctFrac(val, 0)
})

const activeDirection = computed<DominantDirectionType>(() => {
  if (!isMeasurable.value) return 'unmeasured'
  if (props.dominantDirection) return props.dominantDirection
  if (props.payload?.dominant_direction) return props.payload.dominant_direction
  return 'unmeasured'
})

const directionLabel = computed<string>(() => {
  if (!isMeasurable.value) return DASH
  switch (activeDirection.value) {
    case 'bullish_pull':
      return '▲ BULLISH PULL'
    case 'bearish_pull':
      return '▼ BEARISH PULL'
    case 'neutral_pin':
      return '● NEUTRAL PIN'
    case 'unmeasured':
    default:
      return DASH
  }
})

const directionClass = computed<string>(() => {
  if (!isMeasurable.value) return 'vector-unmeasured'
  switch (activeDirection.value) {
    case 'bullish_pull':
      return 'vector-bullish'
    case 'bearish_pull':
      return 'vector-bearish'
    case 'neutral_pin':
      return 'vector-neutral'
    case 'unmeasured':
    default:
      return 'vector-unmeasured'
  }
})

const regimeClass = computed<string>(() => {
  if (!isMeasurable.value || activeState.value === 'unmeasurable') {
    return 'regime-unmeasured'
  }
  switch (activeState.value) {
    case 'volatility_dampening':
      return 'regime-dampening'
    case 'volatility_amplification':
      return 'regime-amplification'
    case 'charm_decay_selling':
    case 'charm_decay_buying':
      return 'regime-charm'
    case 'vanna_vol_expansion':
      return 'regime-vanna'
    case 'neutral_transition':
      return 'regime-transition'
    default:
      return 'regime-unmeasured'
  }
})

const activePrimaryMagnet = computed<PriceDrawLevel | null>(() => {
  if (!isMeasurable.value) return null
  if (props.primaryMagnet) return props.primaryMagnet
  return props.payload?.primary_magnet ?? null
})
</script>

<template>
  <div class="regime-badge-container" :class="[{ 'is-compact': compact }, regimeClass]">
    <!-- Active Regime Mode Pill -->
    <div
      class="badge-pill regime-pill"
      :class="regimeClass"
      :title="`Active Market Regime: ${displayRegimeLabel}`"
    >
      <span class="regime-status-dot" />
      <span class="regime-label-text">{{ displayRegimeLabel }}</span>
      <span
        v-if="showStrength && isMeasurable && activeStrength !== null"
        class="regime-strength-tag"
      >
        {{ formattedStrength }}
      </span>
    </div>

    <!-- Directional Pull Vector Pill -->
    <div
      v-if="showVector"
      class="badge-pill vector-pill"
      :class="directionClass"
      :title="`Dominant Price Attraction Vector: ${directionLabel}`"
    >
      <span class="vector-text">{{ directionLabel }}</span>
    </div>

    <!-- Optional Primary Magnet Target Pill -->
    <div
      v-if="showPrimaryMagnet && isMeasurable && activePrimaryMagnet"
      class="badge-pill magnet-pill"
      :title="`Primary Magnet Target: ${activePrimaryMagnet.label} at ${usd(activePrimaryMagnet.price)} (${signedPct(activePrimaryMagnet.distance_pct)})`"
    >
      <span class="magnet-indicator">★</span>
      <span class="magnet-target-name">{{ activePrimaryMagnet.label }}</span>
      <span class="magnet-price mono-val">{{ usd(activePrimaryMagnet.price) }}</span>
      <span v-if="activePrimaryMagnet.distance_pct !== null" class="magnet-dist mono-val">
        ({{ signedPct(activePrimaryMagnet.distance_pct) }})
      </span>
    </div>
  </div>
</template>

<style scoped>
.regime-badge-container {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.regime-badge-container.is-compact {
  gap: var(--s1);
}

.badge-pill {
  display: inline-flex;
  align-items: center;
  gap: var(--s1);
  min-height: 22px;
  padding: 2px 8px;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.04em;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
  color: var(--ink-dim);
  white-space: nowrap;
  user-select: none;
}

.is-compact .badge-pill {
  min-height: 18px;
  padding: 1px 6px;
  font-size: var(--t-micro);
}

.regime-status-dot {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ink-ghost);
  flex-shrink: 0;
}

.regime-strength-tag {
  margin-left: 2px;
  padding: 0 4px;
  border-radius: var(--r-xs);
  background: var(--panel-wash);
  color: var(--ink);
  font-weight: 800;
}

/* Regime Semantic Styles */
.regime-pill.regime-dampening {
  color: var(--call-hi);
  border-color: color-mix(in srgb, var(--call) 45%, var(--rule));
  background: var(--call-wash);
}
.regime-pill.regime-dampening .regime-status-dot {
  background: var(--call);
}

.regime-pill.regime-amplification {
  color: var(--put-hi);
  border-color: color-mix(in srgb, var(--put) 45%, var(--rule));
  background: var(--put-wash);
}
.regime-pill.regime-amplification .regime-status-dot {
  background: var(--put);
}

.regime-pill.regime-charm {
  color: var(--badge-split);
  border-color: color-mix(in srgb, var(--cat-4) 45%, var(--rule));
  background: var(--badge-split-wash);
}
.regime-pill.regime-charm .regime-status-dot {
  background: var(--cat-4);
}

.regime-pill.regime-vanna {
  color: var(--badge-sweep);
  border-color: color-mix(in srgb, var(--cat-1) 45%, var(--rule));
  background: var(--badge-sweep-wash);
}
.regime-pill.regime-vanna .regime-status-dot {
  background: var(--cat-1);
}

.regime-pill.regime-transition {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 45%, var(--rule));
  background: var(--warn-wash);
}
.regime-pill.regime-transition .regime-status-dot {
  background: var(--warn);
}

.regime-pill.regime-unmeasured {
  color: var(--ink-faint);
  border-color: var(--rule-faint);
  background: var(--void-lift);
}
.regime-pill.regime-unmeasured .regime-status-dot {
  background: var(--ink-ghost);
}

/* Vector Semantic Styles */
.vector-pill.vector-bullish {
  color: var(--call-hi);
  border-color: color-mix(in srgb, var(--call) 45%, var(--rule));
  background: var(--call-wash);
}

.vector-pill.vector-bearish {
  color: var(--put-hi);
  border-color: color-mix(in srgb, var(--put) 45%, var(--rule));
  background: var(--put-wash);
}

.vector-pill.vector-neutral {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 45%, var(--rule));
  background: var(--warn-wash);
}

.vector-pill.vector-unmeasured {
  color: var(--ink-faint);
  border-color: var(--rule-faint);
  background: var(--void-lift);
}

/* Primary Magnet Pill */
.magnet-pill {
  color: var(--ink);
  border-color: color-mix(in srgb, var(--phosphor) 35%, var(--rule));
  background: var(--phosphor-wash);
}

.magnet-indicator {
  color: var(--phosphor);
  font-size: var(--t-tiny);
}

.magnet-target-name {
  color: var(--ink);
  font-weight: 750;
}

.magnet-price {
  color: var(--ink-soft);
}

.magnet-dist {
  color: var(--phosphor-dim);
}

.mono-val {
  font-family: var(--font-data);
}
</style>
