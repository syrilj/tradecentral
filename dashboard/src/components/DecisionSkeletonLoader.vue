<script setup lang="ts">
/**
 * DecisionSkeletonLoader.vue
 *
 * Instrument-grade shadow/skeleton loader for the Live Decision Workstation.
 * Replaces premature partial reads ("1/4 DECISION LENSES READY") with a high-fidelity
 * visual preview while Options, Market Regime, Dealer Book, VPA, Kronos Forecast,
 * and Execution Gate telemetry streams are computing.
 *
 * Adheres to TradeCentral design tokens:
 * - Corner ticks (.ticked), viewfinder panels, and precise data grid alignment
 * - Phosphor accent for active telemetry streams
 * - Accessible status announcement (WCAG AA, role="status", prefers-reduced-motion)
 */
import { computed, ref, onMounted, onUnmounted } from 'vue'

export interface DecisionStreamState {
  key: string
  label: string
  loading: boolean
  status: string
  description: string
}

const props = withDefaults(
  defineProps<{
    symbol?: string
    streams?: DecisionStreamState[]
    completedCount?: number
    totalCount?: number
  }>(),
  {
    symbol: 'SPY',
    streams: () => [],
    completedCount: 0,
    totalCount: 6,
  },
)

const elapsedSeconds = ref(0.0)
let timerId: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  const startTime = Date.now()
  timerId = setInterval(() => {
    elapsedSeconds.value = Math.round((Date.now() - startTime) / 100) / 10
  }, 100)
})

onUnmounted(() => {
  if (timerId != null) {
    clearInterval(timerId)
    timerId = null
  }
})

const defaultStreams: DecisionStreamState[] = [
  {
    key: 'options',
    label: 'OPTIONS FLOW & GEX',
    loading: true,
    status: 'in-flight',
    description: 'Pricing live contracts & GEX profile…',
  },
  {
    key: 'regime',
    label: 'MARKET REGIME',
    loading: true,
    status: 'in-flight',
    description: 'Synthesizing 5 regime models…',
  },
  {
    key: 'microstructure',
    label: 'DEALER BOOK',
    loading: true,
    status: 'in-flight',
    description: 'Mapping hedging pressure & gamma walls…',
  },
  {
    key: 'vpa',
    label: 'VOLUME PRICE ANALYSIS',
    loading: true,
    status: 'in-flight',
    description: 'Evaluating volume-price spread & market phase…',
  },
  {
    key: 'forecast',
    label: 'MODEL FORECAST',
    loading: true,
    status: 'in-flight',
    description: 'Retrieving Kronos horizon evidence…',
  },
  {
    key: 'execution_gate',
    label: 'EXECUTION GATE',
    loading: true,
    status: 'in-flight',
    description: 'Checking session timing & risk limits…',
  },
]

const activeStreams = computed<DecisionStreamState[]>(() => {
  if (props.streams && props.streams.length > 0) {
    return props.streams
  }
  return defaultStreams
})

const resolvedCompletedCount = computed(() => {
  if (props.completedCount > 0) return props.completedCount
  return activeStreams.value.filter((s) => !s.loading).length
})

const totalStreamsCount = computed(() => {
  return props.totalCount || activeStreams.value.length || 6
})

const progressPercent = computed(() => {
  const total = totalStreamsCount.value
  const completed = resolvedCompletedCount.value
  if (completed >= total) return 100

  const baseFromCompleted = (completed / total) * 100
  // Time-based micro-advance asymptotically fills up to 14% during active waiting
  const timeBonus = Math.min(14, Math.floor(elapsedSeconds.value * 2.0))
  return Math.max(8, Math.min(96, Math.round(baseFromCompleted + timeBonus)))
})

interface StageInfo {
  index: number
  total: number
  title: string
  detail: string
}

const currentStage = computed<StageInfo>(() => {
  const completed = resolvedCompletedCount.value
  const total = totalStreamsCount.value
  if (completed >= total) {
    return {
      index: 4,
      total: 4,
      title: 'STAGE 4/4 · FINALIZING TYPESAFE SYNTHESIS',
      detail: 'Reconciling multi-lens evidence with causal decision tree…',
    }
  }

  const streams = activeStreams.value
  const optionsLoading = streams.find((s) => s.key === 'options')?.loading ?? true
  const regimeLoading = streams.find((s) => s.key === 'regime')?.loading ?? true
  const vpaLoading = streams.find((s) => s.key === 'vpa')?.loading ?? true

  if (optionsLoading) {
    return {
      index: 1,
      total: 4,
      title: 'STAGE 1/4 · OPTIONS GEX & ORDER FLOW',
      detail: 'Pricing live option chains, dealer gamma walls, and signed flow…',
    }
  }
  if (regimeLoading) {
    return {
      index: 2,
      total: 4,
      title: 'STAGE 2/4 · MARKET REGIME ENSEMBLE',
      detail: 'Evaluating 5-model regime classification, transition risk & stability…',
    }
  }
  if (vpaLoading) {
    return {
      index: 3,
      total: 4,
      title: 'STAGE 3/4 · VOLUME PRICE ANALYSIS',
      detail: 'Assessing volume-price effort vs result and accumulation phase…',
    }
  }
  return {
    index: 4,
    total: 4,
    title: 'STAGE 4/4 · TYPESAFE SYNTHESIS',
    detail: 'Evaluating parallel lenses and causal decision tree…',
  }
})
</script>

<template>
  <div
    class="decision-skeleton-screen"
    aria-busy="true"
  >
    <span class="sr-only" role="status" aria-live="polite">
      Calibrating multi-lens live decision for {{ symbol }}. {{ resolvedCompletedCount }} of
      {{ totalStreamsCount }} lenses calibrated.
    </span>
    <!-- 0. Telemetry Calibrating Status Strip with Active Progress Bar -->
    <div class="processing-strip ticked">
      <div class="processing-header">
        <div class="processing-status-group">
          <span class="processing-pulse" aria-hidden="true" />
          <span class="processing-eyebrow font-mono">
            CALIBRATING MULTI-LENS LIVE DECISION · {{ symbol }}
          </span>
        </div>
        <div class="processing-meta-group font-mono">
          <span class="processing-timer">T+{{ elapsedSeconds.toFixed(1) }}s</span>
          <span class="processing-counter">
            CALIBRATING [{{ resolvedCompletedCount }}/{{ totalStreamsCount }} LENSES]
          </span>
          <span class="processing-pct-badge font-mono">{{ progressPercent }}%</span>
        </div>
      </div>

      <!-- Active Master Progress Track -->
      <div class="progress-track-block">
        <div class="progress-meta font-mono">
          <span class="progress-stage-title">{{ currentStage.title }}</span>
          <span class="progress-stage-pct">{{ progressPercent }}% CALIBRATED</span>
        </div>

        <div
          class="progress-bar-track"
          role="progressbar"
          :aria-valuenow="progressPercent"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-valuetext="`${progressPercent}% calibrated. ${currentStage.title}. ${currentStage.detail}`"
        >
          <div class="progress-bar-fill" :style="{ width: `${progressPercent}%` }" />
        </div>

        <div class="progress-sub-detail font-mono">
          <span class="progress-detail-text">{{ currentStage.detail }}</span>
          <span class="progress-sub-stat">PARALLEL COLLECTION · 6 LENSES</span>
        </div>
      </div>

      <!-- Streams Grid -->
      <div class="streams-grid">
        <div
          v-for="st in activeStreams"
          :key="st.key"
          class="stream-item"
          :class="{ active: st.loading, ready: !st.loading }"
        >
          <div class="stream-head">
            <span class="stream-dot" :class="{ 'stream-dot--pulsing': st.loading }" />
            <span class="stream-label font-mono">{{ st.label }}</span>
            <span
              class="stream-status-pill font-mono"
              :class="st.loading ? 'pill--active' : 'pill--ready'"
            >
              {{ st.loading ? 'IN-FLIGHT' : st.status ? st.status.toUpperCase() : 'CALIBRATED' }}
            </span>
          </div>

          <!-- Micro Progress Line -->
          <div class="stream-micro-track">
            <div
              class="stream-micro-fill"
              :class="{
                'stream-micro-fill--active': st.loading,
                'stream-micro-fill--ready': !st.loading,
              }"
            />
          </div>

          <span class="stream-desc font-mono">{{ st.description }}</span>
        </div>
      </div>
    </div>

    <!-- 1. Shimmer Verdict Card Skeleton -->
    <section class="sk-verdict-card ticked">
      <div class="sk-verdict-main">
        <div class="sk-topline-row">
          <div class="sk-block sk-pill w-160" />
          <div class="sk-block sk-pill w-120" />
          <div class="sk-block sk-pill w-200" />
        </div>
        <div class="sk-block sk-symbol-slug" />
        <div class="sk-block sk-action-hero" />
        <div class="sk-block sk-line w-280" />
        <div class="sk-block sk-line w-200" />
        <div class="sk-block sk-badge w-180" />
      </div>
      <div class="sk-prob-stack">
        <div class="sk-prob-row">
          <div class="sk-block sk-line w-60" />
          <div class="sk-block sk-track" />
        </div>
        <div class="sk-prob-row">
          <div class="sk-block sk-line w-60" />
          <div class="sk-block sk-track" />
        </div>
      </div>
    </section>

    <!-- 2. Shimmer Decision Brain Card Skeleton -->
    <section class="sk-brain-card ticked">
      <div class="sk-brain-head">
        <div class="sk-topline-row">
          <div class="sk-block sk-pill w-120" />
          <div class="sk-block sk-pill w-140" />
        </div>
        <div class="sk-block sk-pill w-160" />
      </div>
      <div class="sk-meter-wireframe">
        <div class="sk-block sk-track" />
      </div>
      <div class="sk-model-grid">
        <div v-for="i in 4" :key="i" class="sk-model-card">
          <div class="sk-topline-row">
            <div class="sk-block sk-line w-100" />
            <div class="sk-block sk-pill w-50" />
          </div>
          <div class="sk-block sk-line w-80" />
          <div class="sk-block sk-line w-140" />
        </div>
      </div>
    </section>

    <!-- 3. Shimmer Source Tape Grid Skeleton -->
    <section class="sk-tape-card ticked">
      <div class="sk-tape-head">
        <div class="sk-block sk-pill w-140" />
        <div class="sk-block sk-pill w-180" />
      </div>
      <div class="sk-source-grid">
        <div v-for="j in 6" :key="j" class="sk-source-card">
          <div class="sk-topline-row">
            <div class="sk-block sk-line w-90" />
            <div class="sk-block sk-pill w-50" />
          </div>
          <div class="sk-block sk-line w-140" />
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.decision-skeleton-screen {
  display: grid;
  gap: var(--s4);
  width: 100%;
  min-width: 0;
  animation: sk-fade-in 200ms ease-out;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@keyframes sk-fade-in {
  from {
    opacity: 0.7;
    transform: translateY(2px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Base Shimmer Block */
.sk-block {
  background: linear-gradient(
    90deg,
    var(--panel-hi) 20%,
    var(--panel-raise) 50%,
    var(--panel-hi) 80%
  );
  background-size: 200% 100%;
  animation: sk-shimmer 2.2s cubic-bezier(0.4, 0, 0.2, 1) infinite;
  border-radius: 1px;
}

@keyframes sk-shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .decision-skeleton-screen,
  .decision-skeleton-screen *,
  .decision-skeleton-screen *::before,
  .decision-skeleton-screen *::after {
    animation: none !important;
    transition: none !important;
  }

  .decision-skeleton-screen .sk-block {
    background: var(--panel-hi);
  }
}

/* 0. Calibrating Processing Strip */
.processing-strip {
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  padding: var(--s3) var(--s4);
  display: grid;
  gap: var(--s3);
}

.processing-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--s2);
  border-bottom: var(--hair) solid var(--rule-faint);
  padding-bottom: var(--s2);
}

.processing-status-group {
  display: flex;
  align-items: center;
  gap: var(--s2);
  min-width: 0;
  flex-wrap: wrap;
}

.processing-pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--phosphor);
  animation: pulse-dot 1.4s ease-in-out infinite alternate;
}

@keyframes pulse-dot {
  0% {
    opacity: 0.4;
    transform: scale(0.9);
  }
  100% {
    opacity: 1;
    transform: scale(1.15);
  }
}

.processing-eyebrow {
  color: var(--phosphor);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.12em;
}

.processing-meta-group {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
}

.processing-timer {
  color: var(--phosphor);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
}

.processing-counter {
  color: var(--ink-dim);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
}

.processing-pct-badge {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  padding: 1px 6px;
  color: var(--phosphor);
  font-size: var(--t-nano);
  font-weight: 700;
}

/* Master Progress Track */
.progress-track-block {
  display: grid;
  gap: var(--s2);
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-faint);
  padding: var(--s2) var(--s3);
}

.progress-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
}

.progress-stage-title {
  color: var(--ink);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
}

.progress-stage-pct {
  color: var(--phosphor);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
}

.progress-bar-track {
  height: 6px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  overflow: hidden;
  position: relative;
}

.progress-bar-fill {
  height: 100%;
  background: var(--phosphor);
  transition: width 250ms ease-out;
}

.progress-sub-detail {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
  flex-wrap: wrap;
}

.progress-detail-text {
  color: var(--ink-dim);
  font-size: var(--t-nano);
}

.progress-sub-stat {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  letter-spacing: 0.06em;
}

.streams-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s3);
}

@media (max-width: 900px) {
  .streams-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 600px) {
  .streams-grid {
    grid-template-columns: 1fr;
  }
}

.stream-item {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-faint);
  padding: var(--s2) var(--s3);
  display: grid;
  gap: 4px;
}

.stream-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.stream-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ink-ghost);
}

.stream-dot--pulsing {
  background: var(--phosphor);
  animation: stream-blink 1s ease-in-out infinite;
}

@keyframes stream-blink {
  0%,
  100% {
    opacity: 0.4;
  }
  50% {
    opacity: 1;
  }
}

.stream-label {
  color: var(--ink);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
}

.stream-status-pill {
  margin-left: auto;
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 4px;
}

.pill--active {
  color: var(--ink-faint);
}

.pill--ready {
  color: var(--phosphor);
}

.stream-micro-track {
  height: 2px;
  background: var(--void);
  overflow: hidden;
  position: relative;
  margin: 2px 0;
}

.stream-micro-fill--ready {
  width: 100%;
  height: 100%;
  background: var(--phosphor);
}

.stream-micro-fill--active {
  width: 40%;
  height: 100%;
  background: var(--phosphor);
  position: absolute;
  animation: stream-micro-sweep 1.4s ease-in-out infinite alternate;
}

@keyframes stream-micro-sweep {
  0% {
    left: 0%;
  }
  100% {
    left: 60%;
  }
}

.stream-desc {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 1. Shimmer Verdict Card Skeleton */
.sk-verdict-card {
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  padding: var(--s4);
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: var(--s4);
}

@media (max-width: 800px) {
  .sk-verdict-card {
    grid-template-columns: 1fr;
  }
}

.sk-verdict-main {
  display: grid;
  gap: var(--s2);
}

.sk-topline-row {
  display: flex;
  gap: var(--s2);
  align-items: center;
  flex-wrap: wrap;
}

.sk-pill {
  height: 14px;
}
.w-50 {
  width: 50px;
}
.w-60 {
  width: 60px;
}
.w-80 {
  width: 80px;
}
.w-90 {
  width: 90px;
}
.w-100 {
  width: 100px;
}
.w-120 {
  width: 120px;
}
.w-140 {
  width: 140px;
}
.w-160 {
  width: 160px;
}
.w-180 {
  width: 180px;
}
.w-200 {
  width: 200px;
}
.w-280 {
  width: 280px;
}

.sk-symbol-slug {
  width: 60px;
  height: 16px;
  margin-top: 4px;
}

.sk-action-hero {
  width: 140px;
  height: 38px;
}

.sk-line {
  height: 12px;
}

.sk-badge {
  height: 24px;
  margin-top: 4px;
}

.sk-prob-stack {
  display: grid;
  align-content: center;
  gap: var(--s3);
  border-left: var(--hair) solid var(--rule-faint);
  padding-left: var(--s4);
}

.sk-prob-row {
  display: grid;
  gap: 6px;
}

.sk-track {
  height: 10px;
  width: 100%;
}

/* 2. Shimmer Brain Card Skeleton */
.sk-brain-card {
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  padding: var(--s4);
  display: grid;
  gap: var(--s3);
}

.sk-brain-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.sk-meter-wireframe {
  height: 14px;
  margin: var(--s2) 0;
}

.sk-model-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s2);
}

@media (max-width: 900px) {
  .sk-model-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.sk-model-card {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-faint);
  padding: var(--s3);
  display: grid;
  gap: var(--s2);
}

/* 3. Shimmer Source Tape Card Skeleton */
.sk-tape-card {
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  padding: var(--s4);
  display: grid;
  gap: var(--s3);
}

.sk-tape-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: var(--s2);
  border-bottom: var(--hair) solid var(--rule-faint);
}

.sk-source-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s2);
}

@media (max-width: 900px) {
  .sk-source-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.sk-source-card {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-faint);
  padding: var(--s2) var(--s3);
  display: grid;
  gap: 6px;
}
</style>
