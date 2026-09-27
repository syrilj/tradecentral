<script setup lang="ts">
import { computed } from 'vue'
import type { GammaRegime } from '@/regimeContracts'
import { num } from '@/format'

const props = withDefaults(
  defineProps<{
    symbol: string
    spot: number | null
    vwap: number | null
    gammaFlip: number | null
    callWall: number | null
    putWall: number | null
    regime?: GammaRegime | null
    netFlowM?: number | null
    ivRank?: number | null
    kalmanVelocity?: number | null
    customNarrative?: string | null
  }>(),
  {
    regime: null,
    netFlowM: null,
    ivRank: null,
    kalmanVelocity: null,
    customNarrative: null,
  },
)

const isAboveVwap = computed<boolean | null>(() => {
  if (props.spot == null || props.vwap == null) return null
  return props.spot >= props.vwap
})

const isBullishFlow = computed<boolean | null>(() => {
  if (props.netFlowM == null) return null
  return props.netFlowM >= 0
})

const narrative = computed(() => {
  if (props.customNarrative) return props.customNarrative
  const sym = props.symbol || 'SPY'

  if (
    props.spot == null &&
    props.gammaFlip == null &&
    props.vwap == null &&
    props.netFlowM == null
  ) {
    return `${sym} market context unmeasured: live market metrics unavailable.`
  }

  const posStr =
    isAboveVwap.value != null
      ? isAboveVwap.value
        ? 'slightly above VWAP'
        : 'beneath VWAP'
      : 'with VWAP unmeasured'
  const momStr =
    props.kalmanVelocity != null
      ? props.kalmanVelocity >= 0
        ? 'bullish intraday momentum'
        : 'bearish deceleration'
      : 'momentum uncalibrated'
  const flipStr = props.gammaFlip != null ? `$${num(props.gammaFlip, 0)}` : 'the flip'
  const putStr = props.putWall != null ? `$${num(props.putWall, 0)}` : 'key support'

  return `${sym} is trading ${posStr} with ${momStr}. Gamma exposure is positive above ${flipStr}, turning negative below ${putStr}.`
})

const tags = computed(() => {
  const list: Array<{ label: string; tone: 'bullish' | 'bearish' | 'warn' | 'neutral' }> = []

  if (props.vwap != null && props.spot != null && isAboveVwap.value != null) {
    list.push({
      label: isAboveVwap.value ? 'Price > VWAP' : 'Price < VWAP',
      tone: isAboveVwap.value ? 'bullish' : 'bearish',
    })
  }

  if (isBullishFlow.value != null) {
    list.push({
      label: isBullishFlow.value ? 'Bullish Flow' : 'Bearish Flow',
      tone: isBullishFlow.value ? 'bullish' : 'bearish',
    })
  }

  if (props.gammaFlip != null) {
    list.push({
      label: `GEX + Above ${num(props.gammaFlip, 0)}`,
      tone: 'bullish',
    })
  }

  if (props.putWall != null) {
    list.push({
      label: `Negative Below ${num(props.putWall, 0)}`,
      tone: 'bearish',
    })
  }

  if (props.ivRank != null) {
    const iv = props.ivRank
    list.push({
      label: iv > 60 ? 'IV Elevated' : iv < 30 ? 'IV Compressed' : 'IV Normal',
      tone: iv > 60 ? 'warn' : 'neutral',
    })
  }

  if (list.length === 0) {
    list.push({ label: 'Context Unmeasured', tone: 'neutral' })
  }

  return list
})
</script>

<template>
  <div class="market-context-card">
    <div class="card-header">
      <span class="card-eyebrow font-display font-semibold">MARKET CONTEXT</span>
    </div>

    <p class="context-narrative">
      {{ narrative }}
    </p>

    <div class="tags-row">
      <span
        v-for="tag in tags"
        :key="tag.label"
        class="context-tag font-semibold"
        :class="`tone-${tag.tone}`"
      >
        {{ tag.label }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.market-context-card {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: 0.875rem 1rem;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 0.625rem;
  box-sizing: border-box;
  overflow: hidden;
  min-width: 0;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-eyebrow {
  font-family: var(--font-display);
  font-size: 0.75rem;
  letter-spacing: 0.06em;
  color: var(--ink-dim);
  font-weight: 700;
  white-space: nowrap;
}

.context-narrative {
  margin: 0;
  font-family: var(--font-ui);
  font-size: 0.875rem;
  color: var(--ink-soft);
  line-height: 1.5;
  flex: 1 1 auto;
  display: flex;
  align-items: center;
}

.tags-row {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  flex-wrap: wrap;
}

.context-tag {
  font-family: var(--font-ui);
  font-size: 0.75rem;
  padding: 0.2rem 0.5rem;
  border-radius: var(--r-xs);
  display: inline-block;
  white-space: nowrap;
  letter-spacing: 0.02em;
}

.context-tag.tone-bullish {
  background: var(--call-wash);
  color: var(--call-hi);
  border: 1px solid var(--call-dim);
}

.context-tag.tone-bearish {
  background: var(--put-wash);
  color: var(--put-hi);
  border: 1px solid var(--put-dim);
}

.context-tag.tone-warn {
  background: var(--warn-wash);
  color: var(--warn);
  border: 1px solid var(--warn);
}

.context-tag.tone-neutral {
  background: var(--panel-hi);
  color: var(--ink-soft);
  border: 1px solid var(--rule-hi);
}
</style>
