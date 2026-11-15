<script setup lang="ts">
/**
 * Strike ladder for the pre-trade gamma screen. Call gamma sits to the right
 * of the spine, put gamma to the left. This is not the options-page GEX chart.
 */
import { computed } from 'vue'
import type { GammaStrikeRow } from '@/gammaResistance'
import { usd } from '@/format'

const props = defineProps<{
  rows: GammaStrikeRow[]
  spot: number | null
  callLevel: number | null
  supportLevel: number | null
}>()

const peak = computed(() => {
  let max = 0
  for (const row of props.rows) {
    max = Math.max(max, row.call_gex_m, Math.abs(row.put_gex_m))
  }
  return max
})

function barWidth(value: number): string {
  if (!(peak.value > 0) || !Number.isFinite(value)) return '0%'
  return `${Math.max(0, Math.min(100, (Math.abs(value) / peak.value) * 100))}%`
}

function isSpot(strike: number): boolean {
  return props.spot != null && Math.abs(strike - props.spot) <= Math.max(props.spot * 0.002, 0.05)
}
</script>

<template>
  <div
    v-if="rows.length"
    class="ladder"
    data-testid="gamma-ladder"
    role="table"
    aria-label="Gamma by strike"
  >
    <div class="ladder-head" role="row">
      <span>Put γ</span>
      <span>Strike</span>
      <span>Call γ</span>
    </div>
    <div
      v-for="row in rows"
      :key="row.strike"
      class="ladder-row"
      role="row"
      :class="{
        'is-spot': isSpot(row.strike),
        'is-call': callLevel != null && row.strike === callLevel,
        'is-support': supportLevel != null && row.strike === supportLevel,
      }"
    >
      <div class="side put" role="cell">
        <span class="bar put" :style="{ width: barWidth(row.put_gex_m) }" />
      </div>
      <div class="strike fig" role="cell">
        {{ usd(row.strike, 2) }}
        <span v-if="isSpot(row.strike)" class="tag">Spot</span>
        <span v-else-if="callLevel != null && row.strike === callLevel" class="tag"
          >Resistance</span
        >
        <span v-else-if="supportLevel != null && row.strike === supportLevel" class="tag"
          >Support</span
        >
      </div>
      <div class="side call" role="cell">
        <span class="bar call" :style="{ width: barWidth(row.call_gex_m) }" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.ladder {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: var(--s4);
}
.ladder-head,
.ladder-row {
  display: grid;
  grid-template-columns: 1fr 140px 1fr;
  align-items: center;
  gap: var(--s2);
}
.ladder-head {
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ink-dim);
}
.ladder-head span:first-child {
  text-align: right;
}
.side {
  height: 14px;
  display: flex;
  align-items: center;
}
.side.put {
  justify-content: flex-end;
}
.bar {
  display: block;
  height: 8px;
  border-radius: var(--r-xs);
  min-width: 0;
}
.bar.put {
  background: var(--put);
}
.bar.call {
  background: var(--call);
}
.strike {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--s2);
  font-size: var(--t-tiny);
  color: var(--ink);
}
.tag {
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ink-dim);
}
.ladder-row.is-call .strike,
.ladder-row.is-support .strike,
.ladder-row.is-spot .strike {
  color: var(--ink);
}
.ladder-row.is-spot {
  background: color-mix(in srgb, var(--ink) 6%, transparent);
  border-radius: var(--r-xs);
}
</style>
