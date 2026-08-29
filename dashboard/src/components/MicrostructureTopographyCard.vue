<script setup lang="ts">
import { computed } from 'vue'
import type { TopographyState } from '@/microstructureContracts'
import { num } from '@/format'

const props = defineProps<{
  topography: TopographyState | null
  spot: number | null
}>()

/**
 * The four quadrants are all defined relative to the zero-gamma flip. When the
 * server could not locate one — a chain whose net gamma holds a single sign
 * across the whole tested range, which is common — it sends
 * `quadrant: 'unmeasurable'` rather than picking a label. The grid must then
 * highlight nothing and the metrics strip must not print its zeros as though
 * they were a measurement.
 */
const quadrantInfo = computed(() => {
  const t = props.topography
  return t && t.quadrant !== 'unmeasurable' ? t : null
})

/** Present but unmeasurable — distinct from absent, and worth saying why. */
const withheld = computed(() =>
  props.topography?.quadrant === 'unmeasurable' ? props.topography : null,
)

/** Level with its currency symbol, or a bare dash — never "$—". */
function level(v: number | null | undefined): string {
  return v != null && Number.isFinite(v) ? `$${num(v, 2)}` : '—'
}
</script>

<template>
  <div class="topography-card">
    <div class="header-row">
      <div>
        <span class="eyebrow">STRUCTURAL INVENTORY TOPOGRAPHY</span>
        <h3 class="main-title">{{ quadrantInfo?.title ?? '4-Quadrant Structural Map' }}</h3>
      </div>
      <div v-if="quadrantInfo" class="quadrant-badge" :class="quadrantInfo.quadrant">
        {{ quadrantInfo.quadrant.replace(/_/g, ' ').toUpperCase() }}
      </div>
    </div>

    <!-- 4-Quadrant Visual Grid Matrix -->
    <div class="quadrant-grid">
      <!-- Quad I: Backward Positive Ramp -->
      <div
        class="quad-cell"
        :class="{ active: quadrantInfo?.quadrant === 'backward_positive_ramp' }"
      >
        <div class="quad-header">
          <span class="quad-tag">QUAD I</span>
          <span class="quad-name">Backward Positive Ramp</span>
        </div>
        <div class="quad-desc">Heavy GEX cushion below spot; thin overhead resistance.</div>
        <div class="quad-flow text-call-hi">
          &rarr; Supportive dealer dip buying &amp; rapid expansion.
        </div>
      </div>

      <!-- Quad II: Forward Positive Ramp -->
      <div
        class="quad-cell"
        :class="{ active: quadrantInfo?.quadrant === 'forward_positive_ramp' }"
      >
        <div class="quad-header">
          <span class="quad-tag">QUAD II</span>
          <span class="quad-name">Forward Positive Ramp</span>
        </div>
        <div class="quad-desc">Large positive GEX stacked overhead above spot price.</div>
        <div class="quad-flow text-phosphor">
          &rarr; Dealers sell into rallies; mean-reverting pin.
        </div>
      </div>

      <!-- Quad III: Forward Negative Slide -->
      <div
        class="quad-cell"
        :class="{ active: quadrantInfo?.quadrant === 'forward_negative_slide' }"
      >
        <div class="quad-header">
          <span class="quad-tag">QUAD III</span>
          <span class="quad-name">Forward Negative Slide</span>
        </div>
        <div class="quad-desc">Deep negative GEX stacked below spot level.</div>
        <div class="quad-flow text-put-hi">
          &rarr; Breakdown cascade; forced dealer shorting &amp; void.
        </div>
      </div>

      <!-- Quad IV: Backward Negative Slide -->
      <div
        class="quad-cell"
        :class="{ active: quadrantInfo?.quadrant === 'backward_negative_slide' }"
      >
        <div class="quad-header">
          <span class="quad-tag">QUAD IV</span>
          <span class="quad-name">Backward Negative Slide</span>
        </div>
        <div class="quad-desc">Deep negative GEX overhead with spot below flip.</div>
        <div class="quad-flow text-warn">
          &rarr; Violent short-squeeze; aggressive dealer covering.
        </div>
      </div>
    </div>

    <!-- Active Quadrant Tactical Briefing -->
    <div v-if="quadrantInfo" class="tactical-guidance">
      <div class="guidance-col">
        <span class="guidance-label">DEALER HEDGING ACTION</span>
        <span class="guidance-val">{{ quadrantInfo.dealer_hedging_action }}</span>
      </div>
      <div class="guidance-col">
        <span class="guidance-label">EXPECTED MARKET TRAJECTORY</span>
        <span class="guidance-val text-phosphor font-semibold">{{
          quadrantInfo.expected_market_behavior
        }}</span>
      </div>
    </div>

    <!-- Metrics Strip -->
    <div v-if="quadrantInfo" class="metrics-grid">
      <div class="metric-item">
        <span class="m-label">GEX Above Spot</span>
        <span class="m-val font-mono text-call-hi">
          +${{ num(quadrantInfo.gex_above_spot_m, 1) }}M
        </span>
      </div>
      <div class="metric-item">
        <span class="m-label">GEX Below Spot</span>
        <span class="m-val font-mono text-put-hi">
          -${{ num(Math.abs(quadrantInfo.gex_below_spot_m), 1) }}M
        </span>
      </div>
      <div class="metric-item">
        <span class="m-label">GEX Overhead Ratio</span>
        <span class="m-val font-mono">{{ num(quadrantInfo.gex_ratio, 2) }}x</span>
      </div>
      <div class="metric-item">
        <span class="m-label">Volatility Trigger</span>
        <span class="m-val font-mono text-warn">{{ level(quadrantInfo.volatility_trigger) }}</span>
      </div>
    </div>

    <p v-else-if="withheld" class="withheld-note">{{ withheld.description }}</p>
  </div>
</template>

<style scoped>
.withheld-note {
  padding: var(--s3);
  border-top: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.5;
}

.topography-card {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--radius-sm, 4px);
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.eyebrow {
  font-size: 0.6875rem;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
  font-family: var(--font-mono, monospace);
}

.main-title {
  margin: 0.25rem 0 0;
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--ink);
}

.quadrant-badge {
  font-size: 0.6875rem;
  font-weight: 700;
  padding: 0.25rem 0.625rem;
  border-radius: var(--radius-sm, 4px);
  font-family: var(--font-mono, monospace);
  background: var(--panel-hi);
  color: var(--ink-dim);
  border: 1px solid var(--rule-hi);
}

.quadrant-badge.forward_positive_ramp,
.quadrant-badge.backward_positive_ramp {
  background: var(--call-wash);
  color: var(--call-hi);
  border-color: var(--call-dim);
}

.quadrant-badge.forward_negative_slide,
.quadrant-badge.backward_negative_slide {
  background: var(--put-wash);
  color: var(--put-hi);
  border-color: var(--put-dim);
}

.quadrant-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.quad-cell {
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  border-radius: var(--radius-sm, 4px);
  padding: 0.625rem 0.75rem;
  transition: all var(--dur-fast) ease;
}

.quad-cell.active {
  border-color: var(--phosphor);
  background: var(--phosphor-wash);
}

.quad-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}

.quad-tag {
  font-size: 0.5625rem;
  font-family: var(--font-mono, monospace);
  font-weight: 700;
  padding: 0.1rem 0.3rem;
  border-radius: 2px;
  background: var(--panel-raise);
  color: var(--ink-soft);
}

.quad-cell.active .quad-tag {
  background: var(--phosphor);
  color: var(--void);
}

.quad-name {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--ink);
}

.quad-desc {
  font-size: 0.6875rem;
  color: var(--ink-dim);
  line-height: 1.25;
}

.quad-flow {
  margin-top: 0.25rem;
  font-size: 0.6875rem;
  font-family: var(--font-mono, monospace);
}

.tactical-guidance {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  padding: 0.625rem 0.75rem;
  background: var(--void-lift);
  border: 1px solid var(--rule-faint);
  border-radius: var(--radius-sm, 4px);
}

.guidance-col {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.guidance-label {
  font-size: 0.625rem;
  color: var(--ink-faint);
  font-family: var(--font-mono, monospace);
}

.guidance-val {
  font-size: 0.75rem;
  color: var(--ink);
  line-height: 1.3;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--rule-faint);
}

.metric-item {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.m-label {
  font-size: 0.625rem;
  color: var(--ink-faint);
  font-family: var(--font-mono, monospace);
}

.m-val {
  font-size: 0.875rem;
  font-weight: 700;
  color: var(--ink);
}

.text-call-hi {
  color: var(--call-hi);
}

.text-put-hi {
  color: var(--put-hi);
}

.text-warn {
  color: var(--warn);
}

.text-phosphor {
  color: var(--phosphor);
}
</style>
