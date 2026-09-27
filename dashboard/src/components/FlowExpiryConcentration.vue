<script setup lang="ts">
/**
 * Where the tape's premium sits on the expiry curve — horizon tiles, a
 * stacked share bar and a ranked expiry ladder. Pure presentation: every
 * number here comes straight off `computeFlowConcentration`; nothing is
 * re-aggregated in the component.
 */
import type { ExpiryBucket, FlowConcentration } from '@/flowConcentration'
import { EXPIRY_MISSING } from '@/flowConcentration'
import { compact, pctFrac } from '@/format'
import { computed, ref } from 'vue'

const props = defineProps<{ concentration: FlowConcentration }>()

const VISIBLE_ROWS = 8
const expanded = ref(false)

const hasMoreExpiries = computed(() => props.concentration.expiries.length > VISIBLE_ROWS)

const visibleExpiries = computed(() =>
  expanded.value
    ? props.concentration.expiries
    : props.concentration.expiries.slice(0, VISIBLE_ROWS),
)

const horizonBarLabel = computed(
  () =>
    `Premium share by horizon: ${props.concentration.horizons
      .map((h) => `${h.range} ${pctFrac(h.share, 1)}`)
      .join(', ')}`,
)

/** Row-fill width, normalised so the richest expiry fills the track. */
function trackWidth(share: number | null): string {
  const peak = props.concentration.peakShare
  if (share == null || !peak) return '0%'
  return `${Math.max(0, Math.min(100, (share / peak) * 100))}%`
}

function expiryRowLabel(e: ExpiryBucket): string {
  return `${e.label} expiry, ${e.dteLabel}: ${pctFrac(e.share, 1)} of measured premium, $${compact(e.premium)}`
}

const footerMeta = computed(() => {
  const { missingExpiry, unmeasuredPrints } = props.concentration
  const parts: string[] = []
  if (missingExpiry > 0) {
    parts.push(`${missingExpiry} print${missingExpiry === 1 ? '' : 's'} ${EXPIRY_MISSING}`)
  }
  if (unmeasuredPrints > 0) {
    parts.push(`${unmeasuredPrints} print${unmeasuredPrints === 1 ? '' : 's'} no premium figure`)
  }
  return parts.join(' · ')
})
</script>

<template>
  <div class="flow-expiry-concentration">
    <p v-if="concentration.measuredPrints === 0" class="empty-line label wraps">
      No measured premium in this provider window.
    </p>

    <template v-else>
      <div class="horizon-grid">
        <div v-for="h in concentration.horizons" :key="h.key" class="horizon-tile">
          <span class="label horizon-range">{{ h.range }}</span>
          <strong class="fig horizon-share">{{ pctFrac(h.share, 1) }}</strong>
          <span class="fig horizon-premium">${{ compact(h.premium) }}</span>
        </div>
      </div>

      <div
        v-if="concentration.totalPremium > 0"
        class="horizon-bar"
        role="img"
        :aria-label="horizonBarLabel"
      >
        <i
          v-for="h in concentration.horizons"
          :key="h.key"
          class="horizon-seg"
          :class="`seg-${h.key}`"
          :style="{ flexGrow: h.share ?? 0 }"
          aria-hidden="true"
        />
      </div>

      <div v-if="concentration.expiries.length > 0" class="expiry-ladder">
        <div class="ladder-head">
          <span class="label">Expiry</span>
          <span class="label ladder-head-share">Share of premium</span>
        </div>
        <div v-for="e in visibleExpiries" :key="e.key" class="expiry-row">
          <div class="expiry-date">
            <span class="fig expiry-day">{{ e.label }}</span>
            <span class="label dte-chip">{{ e.dteLabel }}</span>
          </div>
          <div class="expiry-track" role="img" :aria-label="expiryRowLabel(e)">
            <div class="expiry-fill" :style="{ width: trackWidth(e.share) }">
              <i class="expiry-call" :style="{ flexGrow: e.callPremium || 0 }" aria-hidden="true" />
              <i class="expiry-put" :style="{ flexGrow: e.putPremium || 0 }" aria-hidden="true" />
            </div>
          </div>
          <div class="expiry-figures">
            <strong class="fig expiry-share">{{ pctFrac(e.share, 1) }}</strong>
            <span class="fig expiry-premium">${{ compact(e.premium) }}</span>
          </div>
        </div>
        <button
          v-if="hasMoreExpiries"
          type="button"
          class="ladder-toggle label"
          @click="expanded = !expanded"
        >
          {{ expanded ? 'Show fewer' : `+${concentration.expiries.length - VISIBLE_ROWS} more` }}
        </button>
      </div>

      <p v-if="footerMeta" class="footer-meta label wraps">{{ footerMeta }}</p>
    </template>
  </div>
</template>

<style scoped>
.flow-expiry-concentration {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  min-width: 0;
}

.empty-line {
  color: var(--ink-faint);
}

/* ---- horizon tiles ------------------------------------------------------ */
.horizon-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s2);
}

.horizon-tile {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-width: 0;
  padding: var(--s2) var(--s3);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.horizon-range.label {
  font-size: var(--t-nano);
  color: var(--ink-faint);
}

.horizon-share.fig {
  font-size: var(--t-fig);
  font-weight: 750;
  color: var(--ink);
  line-height: 1.15;
}

.horizon-premium.fig {
  font-size: var(--t-nano);
  color: var(--ink-dim);
}

/* ---- stacked share bar --------------------------------------------------- */
.horizon-bar {
  display: flex;
  height: 8px;
  overflow: hidden;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
}

.horizon-seg {
  height: 100%;
}

.seg-zero {
  background: var(--phosphor-wash);
}
.seg-week {
  background: var(--wash-3);
}
.seg-month {
  background: var(--wash-2);
}
.seg-beyond {
  background: var(--wash-1);
}

/* ---- expiry ladder ------------------------------------------------------- */
.expiry-ladder {
  display: flex;
  flex-direction: column;
}

.ladder-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: var(--s1);
  border-bottom: var(--hair) solid var(--rule);
}

.ladder-head-share {
  text-align: right;
}

.expiry-row {
  display: grid;
  grid-template-columns: 68px minmax(0, 1fr) 84px;
  align-items: center;
  gap: var(--s2);
  padding: var(--s2) 0;
  border-bottom: var(--hair) solid var(--rule-faint);
}

.expiry-row:last-child {
  border-bottom: none;
}

.expiry-date {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.expiry-day.fig {
  font-size: var(--t-small);
  color: var(--ink-soft);
}

.dte-chip.label {
  font-size: var(--t-nano);
  color: var(--ink-faint);
}

.expiry-track {
  position: relative;
  height: 14px;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  overflow: hidden;
}

.expiry-fill {
  display: flex;
  height: 100%;
  min-width: 2px;
}

.expiry-call {
  flex-shrink: 0;
  background: var(--call);
}

.expiry-put {
  flex-shrink: 0;
  background: var(--put);
}

.expiry-figures {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  text-align: right;
}

.expiry-share.fig {
  font-size: var(--t-small);
  color: var(--ink);
}

.expiry-premium.fig {
  font-size: var(--t-nano);
  color: var(--ink-dim);
}

.ladder-toggle {
  align-self: flex-start;
  margin-top: var(--s2);
  padding: 2px 8px;
  color: var(--ink-faint);
  background: transparent;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}

.ladder-toggle:hover {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

/* ---- footer meta ---------------------------------------------------------- */
.footer-meta.label {
  color: var(--ink-faint);
}
</style>
