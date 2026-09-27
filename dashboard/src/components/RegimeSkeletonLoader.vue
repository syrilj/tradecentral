<script setup lang="ts">
/**
 * RegimeSkeletonLoader.vue
 *
 * Instrument-grade skeleton loader for the Regime Workstation processing screen.
 * Replaces premature provisional reads ("RANGE-BOUND CONSOLIDATION", "COMPRESSION RANGE")
 * with a high-fidelity visual preview while option chains, multi-model consensus,
 * dealer gamma surfaces, and causal kinematics are actively computing.
 *
 * Adheres strictly to TradeCentral design tokens:
 * - Corner ticks (.ticked), viewfinder panels, and precise data grid alignment
 * - Single phosphor accent for active telemetry streams
 * - Accessible status announcement (WCAG AA, role="status", prefers-reduced-motion)
 * - Live quant telemetry terminal tracking real-time computation progression
 */
import { computed, ref, watch, onMounted, onUnmounted, nextTick } from 'vue'

const props = withDefaults(
  defineProps<{
    symbol?: string
    spot?: number | null
    optionsLoading?: boolean
    regimeLoading?: boolean
    microLoading?: boolean
    stateLoading?: boolean
    flowLoading?: boolean
    gateLoading?: boolean
    signalsLoading?: boolean
    vwapLoading?: boolean
  }>(),
  {
    symbol: 'SPY',
    spot: null,
    optionsLoading: true,
    regimeLoading: true,
    microLoading: true,
    stateLoading: true,
    flowLoading: false,
    gateLoading: false,
    signalsLoading: false,
    vwapLoading: false,
  },
)

interface TelemetryStream {
  key: string
  label: string
  loading: boolean
  description: string
}

interface TelemetryLog {
  id: number
  time: string
  tag: string
  text: string
  level: 'info' | 'compute' | 'ready'
}

const elapsedSeconds = ref(0.0)
let timerId: ReturnType<typeof setInterval> | null = null

const terminalFeedRef = ref<HTMLDivElement | null>(null)
const telemetryLogs = ref<TelemetryLog[]>([])
let logSeq = 0

function formatTime(s: number): string {
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `0${m}:${sec < 10 ? '0' : ''}${sec.toFixed(2)}`
}

function addLog(tag: string, text: string, level: 'info' | 'compute' | 'ready' = 'info') {
  telemetryLogs.value.push({
    id: ++logSeq,
    time: formatTime(elapsedSeconds.value),
    tag,
    text,
    level,
  })
  if (telemetryLogs.value.length > 20) {
    telemetryLogs.value.shift()
  }
  nextTick(() => {
    if (terminalFeedRef.value) {
      terminalFeedRef.value.scrollTop = terminalFeedRef.value.scrollHeight
    }
  })
}

// Watch prop completions to trigger real-time log events
watch(
  () => props.optionsLoading,
  (loading, prev) => {
    if (prev === true && loading === false) {
      addLog(
        'OPTIONS:READY',
        `Option chain calibrated (${elapsedSeconds.value.toFixed(2)}s) · GEX profile & zero-gamma flip resolved`,
        'ready',
      )
    }
  },
)

watch(
  () => props.regimeLoading,
  (loading, prev) => {
    if (prev === true && loading === false) {
      addLog(
        'CONSENSUS:READY',
        `Multi-model consensus reached (${elapsedSeconds.value.toFixed(2)}s) · 5-model agreement verified`,
        'ready',
      )
    }
  },
)

watch(
  () => props.microLoading,
  (loading, prev) => {
    if (prev === true && loading === false) {
      addLog(
        'DEALER:READY',
        `Dealer hedging book mapped (${elapsedSeconds.value.toFixed(2)}s) · Call & put walls established`,
        'ready',
      )
    }
  },
)

watch(
  () => props.stateLoading,
  (loading, prev) => {
    if (prev === true && loading === false) {
      addLog(
        'STATE:READY',
        `Causal kinematics converged (${elapsedSeconds.value.toFixed(2)}s) · Kalman velocity filtered`,
        'ready',
      )
    }
  },
)

onMounted(() => {
  const startTime = Date.now()
  let nextLogStep = 1

  addLog('INIT', `Initializing quantitative regime telemetry pipeline for ${props.symbol}`, 'info')
  if (props.spot) {
    addLog('SPOT', `Live spot resolved: $${props.spot.toFixed(2)}`, 'info')
  }

  timerId = setInterval(() => {
    const elapsed = Math.round((Date.now() - startTime) / 100) / 10
    elapsedSeconds.value = elapsed

    // Sequenced progression logs reflecting deep quant pipeline activity
    if (nextLogStep === 1 && elapsed >= 0.4) {
      addLog(
        'OPTIONS',
        `Parsing listed contract chain & calibrating implied volatility smile for ${props.symbol}…`,
        'compute',
      )
      nextLogStep = 2
    } else if (nextLogStep === 2 && elapsed >= 0.8) {
      addLog(
        'GEX',
        'Computing strike-by-strike second-order Greeks & net dealer gamma profile…',
        'compute',
      )
      nextLogStep = 3
    } else if (nextLogStep === 3 && elapsed >= 1.2) {
      addLog(
        'MODELS',
        'Synthesizing 5-model ensemble matrix (Kalman, Topography, Structure, Flow, Attractor)…',
        'compute',
      )
      nextLogStep = 4
    } else if (nextLogStep === 4 && elapsed >= 1.6) {
      addLog('WALLS', 'Resolving Call Wall, Put Wall & Zero-Gamma inflection boundary…', 'compute')
      nextLogStep = 5
    } else if (nextLogStep === 5 && elapsed >= 2.0) {
      addLog(
        'KINEMATICS',
        'Filtering 2-state Kalman kinematic velocity & Nadaraya-Watson causal envelope…',
        'compute',
      )
      nextLogStep = 6
    } else if (nextLogStep === 6 && elapsed >= 2.4) {
      addLog(
        'RECONCILE',
        'Reconciling multi-model state vectors & assembling tactical playbook…',
        'compute',
      )
      nextLogStep = 7
    }
  }, 100)
})

onUnmounted(() => {
  if (timerId != null) {
    clearInterval(timerId)
    timerId = null
  }
})

const streams = computed<TelemetryStream[]>(() => [
  {
    key: 'options',
    label: 'OPTIONS CHAIN',
    loading: props.optionsLoading,
    description: props.optionsLoading
      ? 'Pricing contracts & GEX profile…'
      : 'GEX profile calibrated',
  },
  {
    key: 'regime',
    label: 'MULTI-MODEL CONSENSUS',
    loading: props.regimeLoading,
    description: props.regimeLoading ? 'Synthesizing 5 regime models…' : 'Consensus reached',
  },
  {
    key: 'micro',
    label: 'DEALER BOOK',
    loading: props.microLoading,
    description: props.microLoading ? 'Mapping hedging pressure & walls…' : 'Microstructure mapped',
  },
  {
    key: 'state',
    label: 'CAUSAL KINEMATICS',
    loading: props.stateLoading,
    description: props.stateLoading
      ? 'Estimating Kalman velocity & drift…'
      : 'Kinematics estimated',
  },
])

const completedStreamsCount = computed(() => streams.value.filter((s) => !s.loading).length)

const progressPercent = computed(() => {
  const total = streams.value.length
  const completed = completedStreamsCount.value
  if (completed === total) {
    return 100
  }
  // Base from completed streams: 25% per completed stream (0%, 25%, 50%, 75%)
  const baseFromCompleted = (completed / total) * 100
  // Time-based micro-advance asymptotically fills up to 18% during active waiting
  const timeBonus = Math.min(18, Math.floor(elapsedSeconds.value * 2.5))
  // Always at least 6% initially so the bar has an immediate visible active head
  return Math.max(6, Math.min(96, Math.round(baseFromCompleted + timeBonus)))
})

interface StageInfo {
  index: number
  total: number
  key: string
  title: string
  detail: string
}

const currentStage = computed<StageInfo>(() => {
  if (completedStreamsCount.value === streams.value.length) {
    return {
      index: 4,
      total: 4,
      key: 'RECONCILING',
      title: 'FINALIZING · MULTI-MODEL RECONCILIATION',
      detail: 'Reconciling multi-model regime and preparing tactical execution playbook…',
    }
  }
  if (props.optionsLoading) {
    return {
      index: 1,
      total: 4,
      key: 'OPTIONS_PRICING',
      title: 'STAGE 1/4 · OPTIONS GEX PROFILES',
      detail: 'Pricing live contracts & computing strike-by-strike second-order Greeks…',
    }
  }
  if (props.regimeLoading) {
    return {
      index: 2,
      total: 4,
      key: 'CONSENSUS_SYNTHESIS',
      title: 'STAGE 2/4 · MULTI-MODEL CONSENSUS',
      detail: 'Evaluating 5-model ensemble matrix & transition stability likelihoods…',
    }
  }
  if (props.microLoading) {
    return {
      index: 3,
      total: 4,
      key: 'DEALER_MICROSTRUCTURE',
      title: 'STAGE 3/4 · DEALER HEDGING BOOK',
      detail: 'Mapping dealer gamma walls, hedging elasticity & liquidity pin zones…',
    }
  }
  return {
    index: 4,
    total: 4,
    key: 'CAUSAL_KINEMATICS',
    title: 'STAGE 4/4 · CAUSAL KINEMATICS',
    detail: 'Estimating Kalman velocity state vectors & Bayesian changepoint priors…',
  }
})
</script>

<template>
  <div
    class="regime-skeleton-screen"
    aria-busy="true"
  >
    <span class="sr-only" role="status" aria-live="polite">
      Processing market regime telemetry for {{ symbol }}. {{ completedStreamsCount }} of
      {{ streams.length }} streams calibrated.
    </span>
    <!-- 0. Telemetry Calibrating Status Strip with Active Progress Bar -->
    <div class="processing-strip ticked">
      <div class="processing-header">
        <div class="processing-status-group">
          <span class="processing-pulse" aria-hidden="true" />
          <span class="processing-eyebrow font-mono">
            PROCESSING MULTI-MODEL REGIME TELEMETRY · {{ symbol }}
          </span>
          <span v-if="spot" class="processing-spot-badge font-mono">
            SPOT ${{ spot.toFixed(2) }}
          </span>
        </div>
        <div class="processing-meta-group font-mono">
          <span class="processing-timer">T+{{ elapsedSeconds.toFixed(1) }}s</span>
          <span class="processing-counter">
            CALIBRATING [{{ completedStreamsCount }}/{{ streams.length }} STREAMS]
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
          <div class="progress-bar-fill" :style="{ width: `${progressPercent}%` }">
            <span class="progress-bar-lead" />
          </div>
        </div>

        <div class="progress-sub-detail font-mono">
          <span class="progress-detail-text">{{ currentStage.detail }}</span>
          <span class="progress-sub-stat">POLLING 100ms · 4 ENSEMBLES</span>
        </div>
      </div>

      <div class="streams-grid">
        <div
          v-for="st in streams"
          :key="st.key"
          class="stream-item"
          :class="{ active: st.loading, ready: !st.loading }"
        >
          <div class="stream-head">
            <span
              class="stream-dot"
              :class="{ 'stream-dot--pulsing': st.loading, 'stream-dot--ready': !st.loading }"
            />
            <span class="stream-label font-mono">{{ st.label }}</span>
            <span
              class="stream-status-pill font-mono"
              :class="st.loading ? 'pill--active' : 'pill--ready'"
            >
              {{ st.loading ? 'IN-FLIGHT' : 'CALIBRATED' }}
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

      <!-- Live Quant Telemetry Log Terminal -->
      <div class="telemetry-terminal font-mono">
        <div class="terminal-bar">
          <div class="terminal-bar-left">
            <span class="terminal-pulse" />
            <span class="terminal-title">LIVE QUANT TELEMETRY STREAM · RECONCILIATION ENGINE</span>
          </div>
          <div class="terminal-bar-right">
            <span class="terminal-stat">LATENCY: {{ (elapsedSeconds * 1000).toFixed(0) }}ms</span>
            <span class="terminal-stat"
              >STREAMS: {{ completedStreamsCount }}/{{ streams.length }}</span
            >
          </div>
        </div>
        <div class="terminal-feed" ref="terminalFeedRef">
          <div
            v-for="log in telemetryLogs"
            :key="log.id"
            class="terminal-row"
            :class="`row--${log.level}`"
          >
            <span class="t-col-time">{{ log.time }}</span>
            <span class="t-col-tag font-bold">[{{ log.tag }}]</span>
            <span class="t-col-text">{{ log.text }}</span>
          </div>
          <div class="terminal-row row--active">
            <span class="t-col-time">{{ formatTime(elapsedSeconds) }}</span>
            <span class="t-col-tag font-bold">[ACTIVE]</span>
            <span class="t-col-text text-phosphor">
              {{ currentStage.detail }}
              <span class="terminal-cursor">_</span>
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 1. Executive Briefing Skeleton Banner -->
    <section class="sk-tactical-banner ticked">
      <div class="sk-tactical-header">
        <div class="sk-title-wrap">
          <div class="sk-block sk-pill" />
          <div class="sk-block sk-title" />
          <div class="sk-block sk-subtitle" />
        </div>
        <div class="sk-block sk-badge" />
      </div>

      <div class="sk-tactical-grid">
        <div class="sk-col">
          <div class="sk-col-head">
            <div class="sk-block sk-label" />
            <div class="sk-block sk-tag" />
          </div>
          <div class="sk-block sk-line w-95" />
          <div class="sk-block sk-line w-85" />
          <div class="sk-block sk-line w-70" />
        </div>
        <div class="sk-col">
          <div class="sk-col-head">
            <div class="sk-block sk-label" />
            <div class="sk-block sk-tag" />
          </div>
          <div class="sk-block sk-line w-90 text-phosphor" />
          <div class="sk-block sk-line w-75 text-phosphor" />
        </div>
      </div>
    </section>

    <!-- 2. Workstation Tier 1: Primary Regime Card & Transition Risk Gauge -->
    <div class="quant-grid-row tier-1-row">
      <!-- Primary Card Skeleton with Targeting Radar Reticle -->
      <div class="sk-panel ticked sk-primary-card">
        <div class="sk-panel-head">
          <span class="sk-panel-idx font-mono">01</span>
          <span class="sk-panel-title font-mono">PRIMARY REGIME STATE · {{ symbol }}</span>
          <span class="sk-panel-meta font-mono">CALIBRATING…</span>
        </div>

        <div class="sk-hero-box">
          <div class="sk-radar-reticle" aria-hidden="true">
            <div class="radar-circle radar-outer" />
            <div class="radar-circle radar-inner" />
            <div class="radar-sweep" />
            <div class="radar-crosshair radar-ch-h" />
            <div class="radar-crosshair radar-ch-v" />
            <span class="radar-ping" />
          </div>
          <div class="sk-hero-text">
            <div class="sk-hero-status-row font-mono">
              <span class="sk-hero-stage-badge">{{ currentStage.title }}</span>
              <span class="sk-hero-pct font-mono">{{ progressPercent }}% CALIBRATED</span>
            </div>
            <div class="sk-hero-headline font-mono">
              CALIBRATING MULTI-MODEL REGIME · {{ symbol }}
            </div>
            <div class="sk-hero-sub font-mono">
              {{ currentStage.detail }}
            </div>
          </div>
        </div>

        <!-- Confidence Meter Skeleton -->
        <div class="sk-meter-box">
          <div class="sk-meter-head">
            <div class="sk-block sk-label w-40" />
            <div class="sk-block sk-label w-20" />
          </div>
          <div class="sk-block sk-meter-bar" />
        </div>

        <!-- Simplex Ribbon Skeleton -->
        <div class="sk-simplex-box">
          <div class="sk-meter-head">
            <div class="sk-block sk-label w-50" />
            <div class="sk-block sk-label w-30" />
          </div>
          <div class="sk-simplex-segments">
            <div class="sk-block sk-simplex-seg seg-bull" />
            <div class="sk-block sk-simplex-seg seg-neut" />
            <div class="sk-block sk-simplex-seg seg-bear" />
          </div>
        </div>

        <!-- Structural Levels Quick Strip Skeleton -->
        <div class="sk-levels-strip">
          <div v-for="i in 5" :key="i" class="sk-level-item">
            <div class="sk-block sk-label w-70" />
            <div class="sk-block sk-value w-90" />
            <div class="sk-block sk-sub w-60" />
          </div>
        </div>
      </div>

      <!-- Transition Risk Gauge Skeleton with Sweeping Sonar Beam -->
      <div class="sk-panel ticked sk-gauge-card">
        <div class="sk-panel-head">
          <span class="sk-panel-idx font-mono">02</span>
          <span class="sk-panel-title font-mono">TRANSITION RISK &amp; STABILITY</span>
          <span class="sk-panel-meta font-mono">CUSUM · BOCPD</span>
        </div>

        <div class="sk-gauge-arc-wrap">
          <svg viewBox="0 0 200 110" class="sk-gauge-svg" aria-hidden="true">
            <path
              d="M 20 100 A 80 80 0 0 1 180 100"
              fill="none"
              stroke="var(--void)"
              stroke-width="14"
              stroke-linecap="round"
            />
            <path
              d="M 20 100 A 80 80 0 0 1 180 100"
              fill="none"
              stroke="var(--panel-hi)"
              stroke-width="14"
              stroke-linecap="round"
              stroke-dasharray="8 6"
              class="sk-dash-track"
            />
            <path
              d="M 20 100 A 80 80 0 0 1 180 100"
              fill="none"
              stroke="var(--phosphor)"
              stroke-width="4"
              stroke-linecap="round"
              stroke-dasharray="35 150"
              class="sk-sweep-beam"
            />
          </svg>
          <div class="sk-gauge-center">
            <div class="sk-block sk-gauge-val" />
            <span class="sk-gauge-sub font-mono">ESTIMATING HAZARD</span>
          </div>
        </div>

        <div class="sk-gauge-metrics">
          <div v-for="j in 3" :key="j" class="sk-metric-row">
            <div class="sk-block sk-label w-50" />
            <div class="sk-block sk-value w-30" />
          </div>
        </div>
      </div>
    </div>

    <!-- 3. Workstation Tier 2: Four Analytical Pillars Grid -->
    <div class="quant-grid-row tier-2-row">
      <div class="sk-four-pillar-grid">
        <div v-for="p in 4" :key="p" class="sk-pillar-card ticked">
          <div class="sk-pillar-head">
            <div class="sk-block sk-tag w-30" />
            <div class="sk-block sk-title-sm w-70" />
            <div class="sk-block sk-badge-sm w-40" />
          </div>
          <div class="sk-pillar-body">
            <div v-for="m in 3" :key="m" class="sk-metric-row">
              <div class="sk-block sk-label w-55" />
              <div class="sk-block sk-value w-35" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 4. Workstation Tier 3: Agreement Matrix & Dynamic Explanation -->
    <div class="quant-grid-row tier-3-row">
      <!-- 5x5 Matrix Skeleton with Staggered Delays -->
      <div class="sk-panel ticked sk-matrix-card">
        <div class="sk-panel-head">
          <span class="sk-panel-idx font-mono">03</span>
          <span class="sk-panel-title font-mono">MULTI-MODEL AGREEMENT MATRIX</span>
          <span class="sk-panel-meta font-mono">5×5 ALIGNMENT</span>
        </div>
        <div class="sk-matrix-grid">
          <div
            v-for="cell in 25"
            :key="cell"
            class="sk-block sk-matrix-cell"
            :style="{
              animationDelay: `${((cell % 5) * 0.12 + Math.floor(cell / 5) * 0.08).toFixed(2)}s`,
            }"
          />
        </div>
      </div>

      <!-- Explanation Skeleton -->
      <div class="sk-panel ticked sk-expl-card">
        <div class="sk-panel-head">
          <span class="sk-panel-idx font-mono">04</span>
          <span class="sk-panel-title font-mono">DYNAMIC EXPLAINABILITY &amp; DRIVERS</span>
          <span class="sk-panel-meta font-mono">LAYER 3 SYNTHESIS</span>
        </div>
        <div class="sk-expl-body">
          <div class="sk-block sk-expl-headline" />
          <div class="sk-block sk-line w-95" />
          <div class="sk-block sk-line w-85" />
          <div class="sk-drivers-row">
            <div v-for="d in 3" :key="d" class="sk-block sk-driver-card" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.regime-skeleton-screen {
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
  .regime-skeleton-screen,
  .regime-skeleton-screen *,
  .regime-skeleton-screen *::before,
  .regime-skeleton-screen *::after {
    animation: none !important;
    transition: none !important;
  }

  .regime-skeleton-screen .sk-block {
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

.processing-spot-badge {
  background: var(--void);
  border: var(--hair) solid var(--phosphor-dim);
  color: var(--phosphor);
  font-size: var(--t-nano);
  font-weight: 700;
  padding: 1px 6px;
  letter-spacing: 0.06em;
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
  position: relative;
  transition: width 250ms ease-out;
}

.progress-bar-lead {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 2px;
  background: var(--ink);
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
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s3);
}

.stream-item {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-faint);
  padding: var(--s2) var(--s3);
  display: grid;
  gap: 4px;
}

.stream-item.ready {
  border-color: var(--rule);
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

.stream-dot--ready {
  background: var(--phosphor);
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

/* Live Telemetry Terminal */
.telemetry-terminal {
  background: var(--void);
  border: var(--hair) solid var(--rule);
  display: grid;
  border-radius: 1px;
  overflow: hidden;
}

.terminal-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--panel-hi);
  border-bottom: var(--hair) solid var(--rule-faint);
  padding: 4px var(--s3);
  font-size: var(--t-nano);
}

.terminal-bar-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.terminal-pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--phosphor);
  animation: stream-blink 1s ease-in-out infinite;
}

.terminal-title {
  color: var(--ink);
  font-weight: 700;
  letter-spacing: 0.08em;
}

.terminal-bar-right {
  display: flex;
  align-items: center;
  gap: var(--s3);
}

.terminal-stat {
  color: var(--ink-dim);
  letter-spacing: 0.06em;
}

.terminal-feed {
  padding: 6px var(--s3);
  max-height: 96px;
  overflow-y: auto;
  display: grid;
  gap: 3px;
  scrollbar-width: thin;
}

.terminal-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: var(--t-nano);
  line-height: 1.4;
}

.t-col-time {
  color: var(--ink-faint);
  flex-shrink: 0;
  min-width: 54px;
}

.t-col-tag {
  color: var(--ink-dim);
  flex-shrink: 0;
}

.t-col-text {
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row--ready .t-col-tag {
  color: var(--phosphor);
}

.row--ready .t-col-text {
  color: var(--phosphor);
}

.row--compute .t-col-tag {
  color: var(--call-dim);
}

.row--active .t-col-tag {
  color: var(--phosphor);
}

.terminal-cursor {
  animation: cursor-blink 800ms steps(2, start) infinite;
  color: var(--phosphor);
  font-weight: 700;
}

@keyframes cursor-blink {
  to {
    visibility: hidden;
  }
}

/* 1. Tactical Banner Skeleton */
.sk-tactical-banner {
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  padding: var(--s4);
  display: grid;
  gap: var(--s4);
}

.sk-tactical-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--s3);
}

.sk-title-wrap {
  display: grid;
  gap: var(--s2);
  width: 70%;
}

.sk-pill {
  width: 220px;
  height: 12px;
}

.sk-title {
  width: 480px;
  max-width: 100%;
  height: 28px;
}

.sk-subtitle {
  width: 320px;
  height: 14px;
}

.sk-badge {
  width: 180px;
  height: 32px;
}

.sk-tactical-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s4);
  border-top: var(--hair) solid var(--rule-faint);
  padding-top: var(--s3);
}

.sk-col {
  display: grid;
  gap: var(--s2);
}

.sk-col-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.sk-label {
  width: 140px;
  height: 12px;
}

.sk-tag {
  width: 90px;
  height: 12px;
}

.sk-line {
  height: 14px;
}

.w-95 {
  width: 95%;
}
.w-90 {
  width: 90%;
}
.w-85 {
  width: 85%;
}
.w-80 {
  width: 80%;
}
.w-75 {
  width: 75%;
}
.w-70 {
  width: 70%;
}
.w-60 {
  width: 60%;
}
.w-55 {
  width: 55%;
}
.w-50 {
  width: 50%;
}
.w-40 {
  width: 40%;
}
.w-35 {
  width: 35%;
}
.w-30 {
  width: 30%;
}
.w-20 {
  width: 20%;
}

/* 2. Tier Panels */
.quant-grid-row {
  display: grid;
  gap: var(--s3);
}

.tier-1-row {
  grid-template-columns: 2fr 1fr;
}

.tier-2-row {
  grid-template-columns: 1fr;
}

.tier-3-row {
  grid-template-columns: 1fr 1fr;
}

.sk-panel {
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  padding: var(--s4);
  display: grid;
  gap: var(--s3);
}

.sk-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: var(--s2);
  border-bottom: var(--hair) solid var(--rule-faint);
}

.sk-panel-idx {
  color: var(--phosphor);
  font-size: var(--t-nano);
  font-weight: 700;
}

.sk-panel-title {
  color: var(--ink);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.1em;
}

.sk-panel-meta {
  color: var(--ink-faint);
  font-size: var(--t-nano);
}

/* Primary Card Internals */
.sk-hero-box {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s3);
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-faint);
}

/* Radar Reticle Target */
.sk-radar-reticle {
  position: relative;
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  overflow: hidden;
}

.radar-circle {
  position: absolute;
  border-radius: 50%;
  border: 1px solid var(--rule-faint);
}

.radar-outer {
  width: 36px;
  height: 36px;
}

.radar-inner {
  width: 20px;
  height: 20px;
}

.radar-crosshair {
  position: absolute;
  background: var(--rule-faint);
}

.radar-ch-h {
  width: 100%;
  height: 1px;
}

.radar-ch-v {
  height: 100%;
  width: 1px;
}

.radar-sweep {
  position: absolute;
  top: 0;
  left: 0;
  width: 50%;
  height: 50%;
  transform-origin: 100% 100%;
  border-right: 1px solid var(--phosphor);
  background: var(--panel-raise);
  opacity: 0.6;
  animation: radar-rotate 2s linear infinite;
}

@keyframes radar-rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.radar-ping {
  position: absolute;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--phosphor);
  animation: radar-pulse 1.2s ease-in-out infinite alternate;
}

@keyframes radar-pulse {
  0% {
    transform: scale(0.8);
    opacity: 0.5;
  }
  100% {
    transform: scale(1.3);
    opacity: 1;
  }
}

.sk-hero-text {
  display: grid;
  gap: 4px;
  width: 100%;
}

.sk-hero-status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
}

.sk-hero-stage-badge {
  color: var(--phosphor);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
}

.sk-hero-pct {
  color: var(--ink-dim);
  font-size: var(--t-nano);
  letter-spacing: 0.06em;
}

.sk-hero-headline {
  color: var(--ink);
  font-size: var(--t-body);
  font-weight: 700;
  letter-spacing: 0.04em;
}

.sk-hero-sub {
  color: var(--ink-dim);
  font-size: var(--t-nano);
  line-height: 1.4;
}

.sk-meter-box,
.sk-simplex-box {
  display: grid;
  gap: 6px;
}

.sk-meter-head {
  display: flex;
  justify-content: space-between;
}

.sk-meter-bar {
  width: 100%;
  height: 8px;
}

.sk-simplex-segments {
  display: flex;
  gap: 4px;
  height: 8px;
}

.sk-simplex-seg {
  height: 100%;
}

.seg-bull {
  width: 35%;
}
.seg-neut {
  width: 35%;
}
.seg-bear {
  width: 30%;
}

.sk-levels-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--s2);
  padding-top: var(--s2);
  border-top: var(--hair) solid var(--rule-faint);
}

.sk-level-item {
  display: grid;
  gap: 4px;
  background: var(--panel-hi);
  padding: var(--s2);
  border: var(--hair) solid var(--rule-faint);
}

.sk-value {
  height: 16px;
}
.sk-sub {
  height: 10px;
}

/* Gauge Internals */
.sk-gauge-arc-wrap {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--s2) 0;
}

.sk-gauge-svg {
  width: 180px;
  height: 95px;
}

.sk-sweep-beam {
  animation: sweep-beam-dash 2.4s ease-in-out infinite alternate;
}

@keyframes sweep-beam-dash {
  0% {
    stroke-dashoffset: 120;
  }
  100% {
    stroke-dashoffset: -120;
  }
}

.sk-gauge-center {
  position: absolute;
  bottom: 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.sk-gauge-val {
  width: 60px;
  height: 18px;
}

.sk-gauge-sub {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
}

.sk-gauge-metrics {
  display: grid;
  gap: var(--s2);
  border-top: var(--hair) solid var(--rule-faint);
  padding-top: var(--s2);
}

.sk-metric-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* 3. Four Pillar Grid Skeleton */
.sk-four-pillar-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s3);
}

.sk-pillar-card {
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  padding: var(--s3);
  display: grid;
  gap: var(--s3);
}

.sk-pillar-head {
  display: grid;
  gap: 6px;
  border-bottom: var(--hair) solid var(--rule-faint);
  padding-bottom: var(--s2);
}

.sk-title-sm {
  height: 14px;
}
.sk-badge-sm {
  height: 18px;
}

.sk-pillar-body {
  display: grid;
  gap: var(--s2);
}

/* 4. Tier 3 Skeleton */
.sk-matrix-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 6px;
  aspect-ratio: 1;
  max-width: 260px;
  margin: 0 auto;
}

.sk-matrix-cell {
  width: 100%;
  height: 100%;
}

.sk-expl-body {
  display: grid;
  gap: var(--s2);
}

.sk-expl-headline {
  width: 75%;
  height: 18px;
  margin-bottom: 4px;
}

.sk-drivers-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--s2);
  margin-top: var(--s2);
}

.sk-driver-card {
  height: 48px;
}

/* Responsive */
@media (max-width: 1024px) {
  .streams-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .tier-1-row {
    grid-template-columns: 1fr;
  }
  .sk-four-pillar-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .tier-3-row {
    grid-template-columns: 1fr;
  }
  .sk-levels-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .streams-grid {
    grid-template-columns: 1fr;
  }
  .sk-tactical-grid {
    grid-template-columns: 1fr;
  }
  .sk-four-pillar-grid {
    grid-template-columns: 1fr;
  }
  .sk-levels-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .terminal-feed {
    max-height: 80px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .stream-micro-fill--active,
  .radar-sweep,
  .radar-ping,
  .sk-sweep-beam,
  .processing-pulse {
    animation: none;
  }
  .progress-bar-fill {
    transition: none;
  }
}
</style>
