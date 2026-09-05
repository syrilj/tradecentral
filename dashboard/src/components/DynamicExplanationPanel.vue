<script setup lang="ts">
/**
 * DynamicExplanationPanel.vue
 *
 * Surfaces dynamic human-readable explainability, leading feature drivers,
 * active risk factors, and sources of model uncertainty without canned templates.
 */
import { computed } from 'vue'
import type { DynamicExplanation } from '@/regimeContracts'
import Panel from '@/components/Panel.vue'

const props = withDefaults(
  defineProps<{
    explanation?: DynamicExplanation | null
    measurable?: boolean
  }>(),
  {
    explanation: null,
    // Undefined (caller still loading) must not read as measured.
    measurable: false,
  },
)

const isMeasured = computed<boolean>(() => props.measurable !== false && props.explanation != null)
const headline = computed(
  () => props.explanation?.headline || 'Deterministic Regime Synthesis Active',
)
const summaryText = computed(() =>
  isMeasured.value
    ? props.explanation?.summary || 'No synthesized narrative available.'
    : 'Multi-model synthesis will appear after the first market-state computation completes (~60–90s after activation).',
)
const leadingDrivers = computed(() =>
  isMeasured.value ? props.explanation?.leadingDrivers || [] : [],
)
const riskFactors = computed(() => (isMeasured.value ? props.explanation?.riskFactors || [] : []))
const uncertaintySources = computed(() =>
  isMeasured.value ? props.explanation?.uncertaintySources || [] : [],
)
</script>

<template>
  <Panel
    label="DYNAMIC EXPLAINABILITY & DRIVERS"
    meta="LAYER 3 SYNTHESIS"
    index="04"
    class="explanation-panel"
  >
    <div class="explanation-layout">
      <!-- Dynamic Headline & Summary -->
      <div class="narrative-box">
        <h4 class="narrative-headline">{{ headline }}</h4>
        <p class="narrative-body">{{ summaryText }}</p>
      </div>

      <!-- Leading Feature Drivers -->
      <div v-if="leadingDrivers.length > 0" class="drivers-section">
        <div class="section-title">TOP ATTRIBUTED FEATURE DRIVERS</div>
        <div class="drivers-list">
          <div v-for="(driver, idx) in leadingDrivers" :key="idx" class="driver-card">
            <span class="driver-idx mono">0{{ idx + 1 }}</span>
            <span class="driver-text">{{ driver }}</span>
          </div>
        </div>
      </div>

      <!-- Active Risk Factors & Uncertainty Sources -->
      <div v-if="riskFactors.length > 0 || uncertaintySources.length > 0" class="alerts-section">
        <div v-if="riskFactors.length > 0" class="alert-group">
          <span class="alert-hdr">ACTIVE RISK FACTORS</span>
          <ul class="alert-list">
            <li v-for="(rf, idx) in riskFactors" :key="idx" class="alert-item risk-item">
              {{ rf }}
            </li>
          </ul>
        </div>
        <div v-if="uncertaintySources.length > 0" class="alert-group">
          <span class="alert-hdr">DECISION CATALYSTS &amp; SENSITIVITIES</span>
          <ul class="alert-list">
            <li v-for="(us, idx) in uncertaintySources" :key="idx" class="alert-item unc-item">
              {{ us }}
            </li>
          </ul>
        </div>
      </div>
    </div>
  </Panel>
</template>

<style scoped>
.explanation-layout {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.narrative-box {
  padding: var(--s3);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.narrative-headline {
  margin: 0 0 var(--s1) 0;
  font-family: var(--font-display);
  font-size: 0.875rem;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.35;
}

.narrative-body {
  margin: 0;
  font-family: var(--font-ui);
  font-size: 0.8125rem;
  color: var(--ink-soft);
  line-height: 1.5;
}

.drivers-section {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.section-title {
  font-family: var(--font-ui);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--ink-dim);
}

.drivers-list {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
}

.driver-card {
  display: flex;
  align-items: flex-start;
  gap: var(--s2);
  padding: 0.5rem 0.625rem;
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
}

.driver-idx {
  font-size: 0.75rem;
  font-weight: 800;
  color: var(--phosphor);
}

.driver-text {
  font-family: var(--font-ui);
  font-size: 0.8125rem;
  color: var(--ink);
  line-height: 1.4;
}

.alerts-section {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s2);
}

@media (max-width: 700px) {
  .alerts-section {
    grid-template-columns: 1fr;
  }
}

.alert-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.alert-hdr {
  font-family: var(--font-ui);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--warn);
}

.alert-list {
  margin: 0;
  padding-left: var(--s3);
  font-family: var(--font-ui);
  font-size: 0.8125rem;
  color: var(--ink-soft);
  line-height: 1.45;
}

.risk-item {
  color: var(--warn);
}
.unc-item {
  color: var(--ink-dim);
}
.mono {
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
}
</style>
