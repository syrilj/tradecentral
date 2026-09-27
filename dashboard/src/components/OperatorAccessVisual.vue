<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import Waitlist3DModel from '@/components/Waitlist3DModel.vue'

const props = withDefaults(
  defineProps<{
    mode?: 'signin' | 'waitlist'
  }>(),
  {
    mode: 'signin',
  },
)

const viewMode = ref<'3d' | 'schematic'>(props.mode === 'waitlist' ? '3d' : 'schematic')
</script>

<template>
  <figure class="access-visual" :class="{ 'mode-3d': viewMode === '3d' }" aria-labelledby="access-visual-title">
    <div class="visual-header">
      <span id="access-visual-title" class="visual-title">
        {{ mode === 'waitlist' ? 'PREVIEW PIPELINE / BOUNDARY / EVIDENCE' : 'IDENTITY / BOUNDARY / EVIDENCE' }}
      </span>

      <div class="view-mode-toggle" role="group" aria-label="Visual representation mode">
        <button
          type="button"
          class="mode-btn"
          :class="{ active: viewMode === '3d' }"
          :aria-pressed="viewMode === '3d'"
          aria-label="3D Gamma Surface Model"
          @click="viewMode = '3d'"
        >
          3D Model
        </button>
        <button
          type="button"
          class="mode-btn"
          :class="{ active: viewMode === 'schematic' }"
          :aria-pressed="viewMode === 'schematic'"
          aria-label="System Architecture Schematic"
          @click="viewMode = 'schematic'"
        >
          Schematic
        </button>
      </div>
    </div>

    <!-- 3D Three.js Model View -->
    <div v-if="viewMode === '3d'" class="view-3d-wrapper">
      <Waitlist3DModel :height="340" />

      <!-- Institutional Enclave Telemetry Cards -->
      <div class="enclave-cards-grid">
        <div class="enclave-card card-identity">
          <span class="enclave-icon" aria-hidden="true"><AppIcon name="shield" :size="16" /></span>
          <div class="enclave-text">
            <small>01 / IDENTITY</small>
            <strong>Operator session</strong>
            <p>Cryptographic operator identity.</p>
          </div>
        </div>
        <div class="enclave-card card-boundary">
          <span class="enclave-icon" aria-hidden="true"><AppIcon name="database" :size="16" /></span>
          <div class="enclave-text">
            <small>02 / BOUNDARY</small>
            <strong>Local research API</strong>
            <p>127.0.0.1 remains local.</p>
          </div>
        </div>
        <div class="enclave-card card-evidence">
          <span class="enclave-icon" aria-hidden="true"><AppIcon name="flow" :size="16" /></span>
          <div class="enclave-text">
            <small>03 / EVIDENCE</small>
            <strong>Measured Flow</strong>
            <p>The returned tape, with context.</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 2D Schematic View -->
    <div v-else class="view-schematic-wrapper">
      <svg viewBox="0 0 620 360" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
        <circle class="orbit orbit-outer" cx="310" cy="180" r="150" />
        <circle class="orbit" cx="310" cy="180" r="104" />
        <path
          class="access-trace"
          d="M50 243C115 208 142 252 199 182s92 17 143-37 98 23 143-39 65-25 91-3"
        />
        <path class="access-dash" d="M86 282C151 313 198 263 257 293s116 20 170-24 74-28 111-8" />
        <path class="register" d="M34 38h25M34 38v25M561 322h25M586 297v25" />
      </svg>
      <div class="access-core">
        <span><AppIcon name="shield" :size="30" /></span>
        <small>01 / IDENTITY</small>
        <strong>Operator session</strong>
      </div>
      <div class="access-point point-api">
        <span><AppIcon name="database" :size="17" /></span>
        <small>02 / BOUNDARY</small>
        <strong>Local research API</strong>
        <p>127.0.0.1 remains local.</p>
      </div>
      <div class="access-point point-flow">
        <span><AppIcon name="flow" :size="17" /></span>
        <small>03 / EVIDENCE</small>
        <strong>Measured Flow</strong>
        <p>The returned tape, with context.</p>
      </div>
    </div>

    <footer class="visual-footer">
      No demo tape or trade ticket · authenticate, preserve the boundary, inspect.
    </footer>
  </figure>
</template>

<style scoped>
.access-visual {
  position: relative;
  min-height: 420px;
  margin: 28px 0 0;
  color: #18181b;
}

/* ── Header Row ──────────────────────────────────────────────────────────── */
.visual-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.visual-title {
  color: #6f6f78;
  font-family: var(--font-display);
  font-size: var(--t-nano, 10px);
  font-weight: 700;
  letter-spacing: 0.12em;
}

.view-mode-toggle {
  display: inline-flex;
  padding: 2px;
  background: #eeede5;
  border: 1px solid #c9c9c4;
  gap: 2px;
}

.mode-btn {
  min-height: 24px;
  padding: 0 8px;
  font-family: var(--font-data, monospace);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: #565660;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 120ms ease;
}

.mode-btn:hover {
  color: #18181b;
}

.mode-btn:focus-visible {
  outline: 2px solid #0082e6;
  outline-offset: 1px;
}

.mode-btn.active {
  color: #fbfbf8;
  background: #09090b;
}

/* ── 3D View Area ────────────────────────────────────────────────────────── */
.view-3d-wrapper {
  display: flex;
  flex-direction: column;
  gap: 0;
  border: 1px solid #c9c9c4;
  border-top: 2px solid #0082e6;
  background: #fbfbf8;
}

.view-3d-wrapper :deep(.waitlist-3d-model) {
  border: none;
  border-top: none;
}

.enclave-cards-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  background: #c9c9c4;
  border-top: 1px solid #c9c9c4;
}

.enclave-card {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 9px 12px;
  background: #fbfbf8;
  border: none;
  border-top: 2px solid transparent;
  transition: background 120ms ease;
}

.enclave-card:hover {
  background: #f5f4ef;
}

.enclave-card.card-identity {
  border-top-color: #0082e6;
}

.enclave-card.card-boundary {
  border-top-color: #ff5229;
}

.enclave-card.card-evidence {
  border-top-color: #0f8a5f;
}

.enclave-icon {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  color: #18181b;
  flex-shrink: 0;
  margin-top: 1px;
}

.card-identity .enclave-icon {
  color: #0082e6;
}

.card-boundary .enclave-icon {
  color: #ff5229;
}

.card-evidence .enclave-icon {
  color: #0f8a5f;
}

.enclave-text small {
  display: block;
  font-family: var(--font-display);
  font-size: var(--t-nano, 10px);
  color: #71717a;
  font-weight: 700;
  letter-spacing: 0.08em;
  line-height: 1;
}

.enclave-text strong {
  display: block;
  margin-top: 2px;
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 600;
  color: #18181b;
  line-height: 1.25;
}

.enclave-text p {
  margin: 2px 0 0;
  font-family: var(--font-ui);
  font-size: 10px;
  color: #565660;
  line-height: 1.3;
}

/* ── 2D Schematic View Area ──────────────────────────────────────────────── */
.view-schematic-wrapper {
  position: relative;
  min-height: 360px;
  overflow: hidden;
}

.view-schematic-wrapper::before {
  content: '';
  position: absolute;
  inset: 10px 2px 25px;
  background: radial-gradient(circle at 50% 46%, rgba(0, 130, 230, 0.08), transparent 44%);
}

svg {
  position: absolute;
  inset: 6px 0 30px;
  width: 100%;
  height: calc(100% - 36px);
  fill: none;
  stroke: #c9c9c4;
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.orbit-outer {
  stroke-dasharray: 3 7;
}

.access-trace {
  stroke: #0082e6;
  stroke-width: 1.6;
}

.access-dash {
  stroke: #ff5229;
  stroke-dasharray: 5 7;
}

.register {
  stroke: #a8a8a2;
}

.access-core {
  position: absolute;
  z-index: 2;
  top: 49%;
  left: 50%;
  width: 180px;
  height: 180px;
  display: grid;
  place-content: center;
  justify-items: center;
  transform: translate(-50%, -50%);
  border: 1px solid #c9c9c4;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.92);
}

.access-core::before {
  content: '';
  position: absolute;
  inset: 10px;
  border: 1px solid #e4e3de;
  border-radius: 50%;
}

.access-core > span {
  width: 52px;
  height: 52px;
  display: grid;
  place-items: center;
  color: var(--go, #0082e6);
  border: 1px solid #c9c9c4;
}

.access-core small,
.access-point small {
  margin-top: 12px;
  color: var(--no-go, #ff5229);
  font-family: var(--font-display);
  font-size: var(--t-nano, 10px);
  font-weight: 700;
  letter-spacing: 0.09em;
}

.access-core strong {
  margin-top: 5px;
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 600;
}

.access-point {
  position: absolute;
  z-index: 3;
  width: 184px;
  display: grid;
  grid-template-columns: 31px 1fr;
  grid-template-rows: auto auto auto;
  column-gap: 9px;
  padding: 13px;
  border-left: 2px solid #0082e6;
  background: #f5f4ef;
}

.access-point > span {
  grid-row: 1 / 3;
  width: 31px;
  height: 31px;
  display: grid;
  place-items: center;
  color: #0082e6;
  border: 1px solid #c9c9c4;
}

.access-point small {
  grid-column: 2;
  display: block;
  margin-top: 0;
}

.access-point strong {
  grid-column: 2;
  display: block;
  margin-top: 3px;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
}

.access-point p {
  grid-column: 1 / -1;
  padding-top: 8px;
  color: #565660;
  font-family: var(--font-ui);
  font-size: var(--t-nano, 10px);
}

.point-api {
  top: 50px;
  left: 3px;
}

.point-flow {
  right: 4px;
  bottom: 58px;
  border-color: var(--go, #0082e6);
}

.point-flow > span {
  color: var(--go, #0082e6);
}

/* ── Footer ──────────────────────────────────────────────────────────────── */
.visual-footer {
  margin-top: 14px;
  padding-top: 10px;
  color: #6f6f78;
  border-top: 1px solid #e4e3de;
  font-family: var(--font-display);
  font-size: var(--t-nano, 10px);
  letter-spacing: 0.07em;
  text-transform: uppercase;
}

@media (max-width: 620px) {
  .enclave-cards-grid {
    grid-template-columns: 1fr;
  }
  .enclave-card {
    border-top: none;
    border-left: 2px solid transparent;
  }
  .enclave-card.card-identity {
    border-left-color: #0082e6;
  }
  .enclave-card.card-boundary {
    border-left-color: #ff5229;
  }
  .enclave-card.card-evidence {
    border-left-color: #0f8a5f;
  }
  .view-schematic-wrapper {
    min-height: 480px;
  }
  .access-core {
    top: 45%;
    width: 158px;
    height: 158px;
  }
  .access-point {
    width: 190px;
  }
  .access-point strong {
    font-size: 11px;
  }
  .point-api {
    top: 42px;
  }
  .point-flow {
    bottom: 70px;
  }
}
</style>
