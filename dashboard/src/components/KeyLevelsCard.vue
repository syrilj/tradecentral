<script setup lang="ts">
import { computed } from 'vue'
import { num, DASH } from '@/format'

const props = withDefaults(
  defineProps<{
    spot?: number | null
    maxPain?: number | null
    vwap?: number | null
    resistance?: number | null
    support?: number | null
    gammaFlip?: number | null
  }>(),
  {
    spot: null,
    maxPain: null,
    vwap: null,
    resistance: null,
    support: null,
    gammaFlip: null,
  },
)

function dist(lvl: number | null): string {
  if (props.spot == null || lvl == null || props.spot <= 0) return ''
  const diff = ((lvl - props.spot) / props.spot) * 100
  const sign = diff >= 0 ? '+' : ''
  return `${sign}${num(diff, 1)}%`
}

const levelsList = computed(() => {
  if (props.gammaFlip != null) {
    return [
      {
        label: 'Spot Price',
        price: props.spot,
        role: 'Current live tape',
        tone: 'spot',
      },
      {
        label: 'Gamma Flip S*',
        price: props.gammaFlip,
        role: 'Regime inflection boundary',
        tone: 'warn',
      },
      {
        label: 'VWAP',
        price: props.vwap,
        role: 'Volume weighted mean',
        tone: 'cyan',
      },
      {
        label: 'Resistance',
        price: props.resistance,
        role: 'Major Call Wall',
        tone: 'call',
      },
      {
        label: 'Support',
        price: props.support,
        role: 'Major Put Wall',
        tone: 'put',
      },
      {
        label: 'Max Pain',
        price: props.maxPain,
        role: 'Options settlement anchor',
        tone: 'phosphor',
      },
    ]
  }
  return [
    {
      label: 'Max Pain',
      price: props.maxPain,
      role: 'Options settlement anchor',
      tone: 'phosphor',
    },
    {
      label: 'Spot Price',
      price: props.spot,
      role: 'Current live tape',
      tone: 'spot',
    },
    {
      label: 'VWAP',
      price: props.vwap,
      role: 'Volume weighted mean',
      tone: 'cyan',
    },
    {
      label: 'Resistance',
      price: props.resistance,
      role: 'Major Call Wall',
      tone: 'call',
    },
    {
      label: 'Support',
      price: props.support,
      role: 'Major Put Wall',
      tone: 'put',
    },
  ]
})
</script>

<template>
  <div class="key-levels-card">
    <div class="card-header">
      <span class="card-eyebrow font-display font-semibold">KEY LEVELS</span>
    </div>

    <div class="levels-grid">
      <div
        v-for="item in levelsList"
        :key="item.label"
        class="level-box"
        :class="`box-${item.tone}`"
      >
        <span class="level-label font-ui font-medium">{{ item.label }}</span>
        <div class="level-price-row">
          <span class="level-price font-mono font-bold">
            {{ item.price != null ? `$${num(item.price, 2)}` : DASH }}
          </span>
          <span
            v-if="item.label !== 'Spot Price' && item.price != null && spot != null"
            class="level-dist font-mono text-ink-dim"
          >
            {{ dist(item.price) }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.key-levels-card {
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

/* Two rows (3 + 2) instead of five-across: at five columns each chip is
   ~55px and every label ellipsizes. Three columns give a full label room. */
.levels-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.5rem;
  width: 100%;
  flex: 1 1 auto;
  align-content: space-evenly;
}

.level-box {
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  border-radius: var(--r-sm);
  padding: 0.5rem 0.625rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
  box-sizing: border-box;
}

.level-box.box-spot {
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.level-label {
  font-family: var(--font-ui);
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--ink-dim);
  white-space: nowrap;
  letter-spacing: 0.02em;
}

.level-price-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.25rem;
  flex-wrap: wrap;
}

.level-price {
  font-family: var(--font-data);
  font-size: 0.9375rem;
  color: var(--ink);
  white-space: nowrap;
}

.box-call .level-price {
  color: var(--call-hi);
}

.box-put .level-price {
  color: var(--put-hi);
}

.box-spot .level-price {
  color: var(--phosphor);
}

.box-cyan .level-price {
  color: var(--ink-soft);
}

.box-warn .level-price {
  color: var(--warn);
}

.level-dist {
  font-family: var(--font-data);
  font-size: 0.75rem;
  white-space: nowrap;
}

@media (max-width: 1200px) {
  .levels-grid {
    grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
  }
}
</style>
