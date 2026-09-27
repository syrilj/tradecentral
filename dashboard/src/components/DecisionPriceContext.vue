<script setup lang="ts">
import { computed } from 'vue'
import type { DecisionPriceContext, DecisionPriceLevel } from '@/decisionPriceContext'

const props = defineProps<{
  context: DecisionPriceContext
  action: 'buy' | 'sell'
  keepOut?: boolean
}>()

function money(value: number | null): string {
  if (value == null) return 'Unavailable'
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: value >= 100 ? 2 : 3,
    maximumFractionDigits: value >= 100 ? 2 : 3,
  })
}

function signedDistance(level: DecisionPriceLevel): string {
  if (props.context.spot == null) return ''
  const distance = ((level.price - props.context.spot) / props.context.spot) * 100
  return `${distance > 0 ? '+' : ''}${distance.toFixed(2)}%`
}

function timeLabel(value: string | null): string {
  if (!value) return 'time unavailable'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleTimeString()
}

const postureNote = computed(() => {
  if (props.keepOut) {
    return `The ${props.action.toUpperCase()} read is blocked. These levels show structure, not an entry.`
  }
  return `The ${props.action.toUpperCase()} read is directional research. Levels do not authorize an order.`
})
</script>

<template>
  <section class="price-context" aria-labelledby="price-context-heading">
    <header class="price-context-head">
      <div>
        <h2 id="price-context-heading" class="fig">PRICE CONTEXT</h2>
        <p>Where the directional read sits against measured market structure.</p>
      </div>
      <span class="context-status fig" :class="context.status">{{ context.status }}</span>
    </header>

    <div v-if="context.spot != null" class="price-context-body">
      <div class="spot-block">
        <span class="spot-label fig">CURRENT PRICE</span>
        <strong class="spot-price fig">{{ money(context.spot) }}</strong>
        <span class="spot-source fig">
          {{ context.spotSource ?? 'source unavailable' }}
          <template v-if="context.spotQuality"> / {{ context.spotQuality }}</template>
          / {{ timeLabel(context.asof) }}
        </span>
        <p>{{ context.summary }}</p>
        <p class="posture-note">{{ postureNote }}</p>
      </div>

      <div class="structure-ladder" aria-label="Nearest measured price levels">
        <article v-if="context.nearestAbove" class="level-row above">
          <span class="level-side fig">NEXT ABOVE</span>
          <span class="level-name">{{ context.nearestAbove.label }}</span>
          <span class="level-source">{{ context.nearestAbove.source }}</span>
          <strong class="fig">{{ money(context.nearestAbove.price) }}</strong>
          <span class="distance fig">{{ signedDistance(context.nearestAbove) }}</span>
        </article>
        <article class="level-row current">
          <span class="level-side fig">NOW</span>
          <span class="level-name">{{ context.symbol }}</span>
          <span class="level-source">current observed price</span>
          <strong class="fig">{{ money(context.spot) }}</strong>
          <span class="distance fig">0.00%</span>
        </article>
        <article v-if="context.nearestBelow" class="level-row below">
          <span class="level-side fig">NEXT BELOW</span>
          <span class="level-name">{{ context.nearestBelow.label }}</span>
          <span class="level-source">{{ context.nearestBelow.source }}</span>
          <strong class="fig">{{ money(context.nearestBelow.price) }}</strong>
          <span class="distance fig">{{ signedDistance(context.nearestBelow) }}</span>
        </article>
        <p v-if="!context.nearestAbove && !context.nearestBelow" class="no-levels">
          No measured support, resistance, value-area, or dealer level is ready for this symbol.
        </p>
      </div>
    </div>

    <div v-else class="price-context-empty" role="status">
      <strong>Price context unavailable</strong>
      <p>
        The quote, options snapshot, and latest VPA close did not provide a measured current price.
        No level distance is shown.
      </p>
    </div>

    <div v-if="context.spot != null && context.nearbyLevels.length" class="nearby-tape">
      <span class="nearby-label fig">NEARBY MEASURED LEVELS</span>
      <div class="nearby-list">
        <span v-for="level in context.nearbyLevels" :key="level.id" :class="level.kind">
          <b class="fig">{{ money(level.price) }}</b>
          {{ level.label }}
        </span>
      </div>
      <span v-if="context.valueArea" class="value-location fig">
        VALUE AREA {{ context.valueArea.location.toUpperCase() }}
        <template v-if="context.valueArea.poc != null">
          / POC {{ money(context.valueArea.poc) }}
        </template>
      </span>
    </div>
  </section>
</template>

<style scoped>
.price-context {
  border: var(--hair) solid var(--rule);
  border-left: 3px solid var(--phosphor);
  background: var(--panel);
}
.price-context-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  border-bottom: var(--hair) solid var(--rule-faint);
}
.price-context-head h2,
.price-context-head p {
  margin: 0;
}
.price-context-head h2 {
  color: var(--phosphor);
  font: 800 var(--t-nano) var(--font-data);
  letter-spacing: 0.12em;
}
.price-context-head p {
  margin-top: 4px;
  color: var(--ink-dim);
  font-size: var(--t-micro);
}
.context-status {
  padding: 3px 8px;
  border: var(--hair) solid var(--rule);
  color: var(--ink-faint);
  font-size: var(--t-nano);
  text-transform: uppercase;
}
.context-status.ready {
  color: var(--long);
  border-color: color-mix(in srgb, var(--long) 45%, var(--rule));
}
.context-status.partial {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 45%, var(--rule));
}
.context-status.missing {
  color: var(--short);
  border-color: color-mix(in srgb, var(--short) 45%, var(--rule));
}
.price-context-body {
  display: grid;
  grid-template-columns: minmax(260px, 0.72fr) minmax(0, 1.28fr);
  min-width: 0;
}
.spot-block {
  padding: var(--s4);
  border-right: var(--hair) solid var(--rule-faint);
}
.spot-label,
.spot-source {
  display: block;
  color: var(--ink-faint);
  font-size: var(--t-nano);
  letter-spacing: 0.1em;
}
.spot-price {
  display: block;
  margin: 8px 0 6px;
  color: var(--ink);
  font-size: clamp(2.5rem, 5vw, 5rem);
  line-height: 0.92;
  letter-spacing: -0.055em;
}
.spot-block p {
  max-width: 52ch;
  margin: var(--s3) 0 0;
  color: var(--ink-soft);
  line-height: 1.45;
}
.spot-block .posture-note {
  margin-top: var(--s2);
  color: var(--ink-faint);
  font-size: var(--t-micro);
}
.structure-ladder {
  align-self: stretch;
  display: grid;
  align-content: center;
  padding: var(--s3) var(--s4);
}
.level-row {
  display: grid;
  grid-template-columns: 92px minmax(150px, 1fr) minmax(130px, 0.9fr) auto 70px;
  align-items: baseline;
  gap: var(--s2);
  padding: 14px 0;
  border-bottom: var(--hair) solid var(--rule-faint);
}
.level-row:last-of-type {
  border-bottom: 0;
}
.level-row.current {
  margin: 2px 0;
  padding-inline: var(--s2);
  background: var(--panel-hi);
  border-left: 2px solid var(--phosphor);
}
.level-row.above {
  border-left: 2px solid var(--short);
  padding-left: var(--s2);
}
.level-row.below {
  border-left: 2px solid var(--long);
  padding-left: var(--s2);
}
.level-side,
.distance {
  color: var(--ink-faint);
  font-size: var(--t-nano);
}
.level-name {
  color: var(--ink);
  font-weight: 700;
}
.level-source {
  color: var(--ink-faint);
  font-size: var(--t-nano);
}
.level-row strong {
  color: var(--ink);
  white-space: nowrap;
}
.level-row.above .distance {
  color: var(--short);
}
.level-row.below .distance {
  color: var(--long);
}
.no-levels,
.price-context-empty p {
  margin: 0;
  color: var(--ink-dim);
}
.price-context-empty {
  padding: var(--s4);
}
.price-context-empty strong {
  display: block;
  margin-bottom: 6px;
  color: var(--short);
}
.nearby-tape {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s4);
  border-top: var(--hair) solid var(--rule-faint);
  background: var(--panel-hi);
}
.nearby-label,
.value-location {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  white-space: nowrap;
}
.nearby-list {
  display: flex;
  align-items: center;
  gap: var(--s2);
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: thin;
}
.nearby-list > span {
  flex: 0 0 auto;
  padding-left: 8px;
  border-left: 2px solid var(--rule-hi);
  color: var(--ink-dim);
  font-size: var(--t-nano);
}
.nearby-list > span.support {
  border-left-color: var(--long);
}
.nearby-list > span.resistance {
  border-left-color: var(--short);
}
.nearby-list > span.value,
.nearby-list > span.pivot {
  border-left-color: var(--phosphor);
}
.nearby-list b {
  margin-right: 4px;
  color: var(--ink);
}
@media (max-width: 980px) {
  .price-context-body {
    grid-template-columns: 1fr;
  }
  .spot-block {
    border-right: 0;
    border-bottom: var(--hair) solid var(--rule-faint);
  }
  .level-row {
    grid-template-columns: 86px minmax(130px, 1fr) auto 64px;
  }
  .level-source {
    display: none;
  }
  .nearby-tape {
    grid-template-columns: 1fr;
    gap: var(--s2);
  }
}
@media (max-width: 620px) {
  .price-context-head,
  .spot-block,
  .structure-ladder,
  .price-context-empty,
  .nearby-tape {
    padding-inline: var(--s3);
  }
  .level-row {
    grid-template-columns: 76px minmax(0, 1fr) auto;
  }
  .level-row .distance {
    grid-column: 2 / -1;
  }
}
</style>
