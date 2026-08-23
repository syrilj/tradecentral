<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  usePreferences,
  type DensityMode,
  type AccentTheme,
  type UserPreferences,
} from '@/composables/usePreferences'
import AppIcon from '@/components/AppIcon.vue'

export interface WorkstationTelemetry {
  apiStatus?: 'ok' | 'sync' | 'fault' | string
  latencyMs?: number
  activeRoute?: string
  feedFreshness?: string
  lastSync?: string
}

const props = withDefaults(
  defineProps<{
    modelValue?: boolean
    userEmail?: string
    userName?: string
    userAvatar?: string
    operatorRole?: string
    telemetry?: WorkstationTelemetry
  }>(),
  {
    modelValue: false,
    userEmail: '',
    userName: '',
    userAvatar: '',
    operatorRole: 'Institutional Operator',
    telemetry: () => ({
      apiStatus: 'ok',
      activeRoute: 'desk',
      feedFreshness: 'live',
    }),
  },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'close'): void
  (e: 'signOut'): void
  (e: 'updatePreferences', preferences: UserPreferences): void
}>()

const {
  preferences,
  density,
  accent,
  soundEnabled,
  streamUpdates,
  setDensity,
  setAccent,
  toggleSound,
  toggleStream,
} = usePreferences()

const sessionStartTime = ref(Date.now())
const sessionUptime = ref('00:00:00')
const isSigningOut = ref(false)
let uptimeTimer: number | undefined

function updateUptime(): void {
  const elapsedSec = Math.max(0, Math.floor((Date.now() - sessionStartTime.value) / 1000))
  const h = String(Math.floor(elapsedSec / 3600)).padStart(2, '0')
  const m = String(Math.floor((elapsedSec % 3600) / 60)).padStart(2, '0')
  const s = String(elapsedSec % 60).padStart(2, '0')
  sessionUptime.value = `${h}:${m}:${s}`
}

function handleClose(): void {
  emit('update:modelValue', false)
  emit('close')
}

function handleSignOut(): void {
  isSigningOut.value = true
  emit('signOut')
}

function onDensitySelect(mode: DensityMode): void {
  setDensity(mode)
  emit('updatePreferences', preferences.value)
}

function onAccentSelect(theme: AccentTheme): void {
  setAccent(theme)
  emit('updatePreferences', preferences.value)
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape' && props.modelValue) {
    e.preventDefault()
    handleClose()
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      updateUptime()
      if (typeof window !== 'undefined') {
        window.addEventListener('keydown', onKeydown)
      }
    } else if (typeof window !== 'undefined') {
      window.removeEventListener('keydown', onKeydown)
    }
  },
  { immediate: true },
)

onMounted(() => {
  uptimeTimer = window.setInterval(updateUptime, 1000)
})

onUnmounted(() => {
  if (uptimeTimer !== undefined) clearInterval(uptimeTimer)
  if (typeof window !== 'undefined') {
    window.removeEventListener('keydown', onKeydown)
  }
})

const operatorInitials = computed(() => {
  if (props.userName) {
    const parts = props.userName.trim().split(/\s+/)
    if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
    if (parts.length === 1 && parts[0]) return parts[0].slice(0, 2).toUpperCase()
  }
  if (props.userEmail) {
    const namePart = props.userEmail.split('@')[0]
    return namePart.slice(0, 2).toUpperCase()
  }
  return 'OP'
})

const accentOptions: { id: AccentTheme; label: string; tokenColor: string }[] = [
  { id: 'phosphor', label: 'Phosphor', tokenColor: 'var(--phosphor)' },
  { id: 'amber', label: 'Amber', tokenColor: 'var(--warn)' },
  { id: 'cyan', label: 'Cyan', tokenColor: 'var(--cat-1)' },
  { id: 'monochrome', label: 'Mono', tokenColor: 'var(--ink-soft)' },
]
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="drawer-backdrop" aria-hidden="true" @click="handleClose" />

    <Transition name="drawer-slide">
      <aside
        v-if="modelValue"
        class="profile-drawer glass-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Operator Profile & Workstation Settings"
      >
        <!-- Header -->
        <header class="drawer-head">
          <div class="head-title-wrap">
            <span class="label head-pre">WORKSTATION</span>
            <h2 class="head-title">Operator Profile</h2>
          </div>
          <button
            type="button"
            class="btn-close"
            title="Close drawer (Esc)"
            aria-label="Close operator profile drawer"
            @click="handleClose"
          >
            <span aria-hidden="true">✕</span>
          </button>
        </header>

        <!-- Body -->
        <div class="drawer-body">
          <!-- Section 1: Operator Identity -->
          <section class="drawer-card glass-card operator-card" aria-label="Operator Credentials">
            <div class="operator-row">
              <div class="operator-avatar-wrap">
                <img
                  v-if="userAvatar"
                  :src="userAvatar"
                  alt="Operator Avatar"
                  class="operator-avatar-img"
                />
                <span v-else class="operator-avatar-initials fig">{{ operatorInitials }}</span>
                <span class="operator-live-lamp" :title="'Clearance: Verified Active'" />
              </div>
              <div class="operator-meta">
                <div class="operator-name-row">
                  <span class="operator-name">{{
                    userName || userEmail || 'Institutional Operator'
                  }}</span>
                  <span class="operator-badge label">OP·AUTH</span>
                </div>
                <span v-if="userEmail" class="operator-email mono">{{ userEmail }}</span>
                <span class="operator-role label">{{ operatorRole }}</span>
              </div>
            </div>

            <div class="operator-status-grid">
              <div class="status-cell">
                <span class="status-label label">CLEARANCE</span>
                <span class="status-val pos mono">VERIFIED · LEVEL 4</span>
              </div>
              <div class="status-cell">
                <span class="status-label label">UPTIME</span>
                <span class="status-val fig">{{ sessionUptime }}</span>
              </div>
            </div>
          </section>

          <!-- Section 2: Workstation Preferences -->
          <section class="drawer-section" aria-label="Workstation Preferences">
            <span class="label section-label">WORKSTATION PREFERENCES</span>

            <!-- Density Control -->
            <div class="pref-group">
              <div class="pref-head">
                <span class="pref-title">Layout Spacing Density</span>
                <span class="pref-state label fig">{{
                  density === 'compact' ? '28px ROW' : '36px ROW'
                }}</span>
              </div>
              <p class="pref-desc">Adjust table row heights and data padding across workspaces.</p>
              <div class="segmented-control" role="radiogroup" aria-label="Layout density">
                <button
                  type="button"
                  class="segment-btn"
                  :class="{ active: density === 'compact' }"
                  role="radio"
                  :aria-checked="density === 'compact'"
                  @click="onDensitySelect('compact')"
                >
                  <AppIcon name="density" :size="13" class="segment-icon" />
                  <span class="segment-text">Compact</span>
                  <span class="segment-sub mono">28px</span>
                </button>
                <button
                  type="button"
                  class="segment-btn"
                  :class="{ active: density === 'comfortable' }"
                  role="radio"
                  :aria-checked="density === 'comfortable'"
                  @click="onDensitySelect('comfortable')"
                >
                  <AppIcon name="density" :size="13" class="segment-icon" />
                  <span class="segment-text">Comfortable</span>
                  <span class="segment-sub mono">36px</span>
                </button>
              </div>
            </div>

            <!-- Accent Theme Selector -->
            <div class="pref-group">
              <div class="pref-head">
                <span class="pref-title">Workstation Accent Tone</span>
                <span class="pref-state label">{{ accent }}</span>
              </div>
              <p class="pref-desc">Color marker for live data, selected views, and visual cues.</p>
              <div class="accent-swatches" role="radiogroup" aria-label="Accent theme">
                <button
                  v-for="opt in accentOptions"
                  :key="opt.id"
                  type="button"
                  class="accent-pill"
                  :class="{ active: accent === opt.id }"
                  role="radio"
                  :aria-checked="accent === opt.id"
                  :title="`Accent: ${opt.label}`"
                  @click="onAccentSelect(opt.id)"
                >
                  <span class="swatch-dot" :style="{ backgroundColor: opt.tokenColor }" />
                  <span class="swatch-label label">{{ opt.label }}</span>
                </button>
              </div>
            </div>

            <!-- Streaming updates toggle -->
            <div class="pref-toggle-row" @click="toggleStream">
              <div class="toggle-meta">
                <span class="toggle-title">Real-Time Stream Updates</span>
                <span class="toggle-desc"
                  >Live order flow tape, quote polling, and ticker animation.</span
                >
              </div>
              <button
                type="button"
                class="toggle-switch"
                :class="{ on: streamUpdates }"
                role="switch"
                :aria-checked="streamUpdates"
                aria-label="Toggle real-time stream updates"
              >
                <span class="toggle-knob" />
              </button>
            </div>

            <!-- Sound alerts toggle -->
            <div class="pref-toggle-row" @click="toggleSound">
              <div class="toggle-meta">
                <span class="toggle-title">Auditory Flow Signals</span>
                <span class="toggle-desc"
                  >Audio cues for unusual whale sweeps and gate alerts.</span
                >
              </div>
              <button
                type="button"
                class="toggle-switch"
                :class="{ on: soundEnabled }"
                role="switch"
                :aria-checked="soundEnabled"
                aria-label="Toggle audio cue alerts"
              >
                <span class="toggle-knob" />
              </button>
            </div>
          </section>

          <!-- Section 3: Telemetry & System Status -->
          <section class="drawer-section" aria-label="Workstation Telemetry">
            <span class="label section-label">SYSTEM TELEMETRY</span>
            <div class="drawer-card glass-card telemetry-card">
              <div class="telemetry-row">
                <span class="t-key label">API ENDPOINT</span>
                <div class="t-val-wrap">
                  <span class="t-lamp pos" />
                  <span class="t-val mono">127.0.0.1:8787 (LOCAL)</span>
                </div>
              </div>
              <div class="telemetry-row">
                <span class="t-key label">FEED STATUS</span>
                <span class="t-val mono" :class="telemetry?.apiStatus === 'fault' ? 'neg' : 'pos'">
                  {{ (telemetry?.apiStatus || 'OK').toUpperCase() }} ·
                  {{ telemetry?.feedFreshness || 'LIVE' }}
                </span>
              </div>
              <div class="telemetry-row">
                <span class="t-key label">QUANT KERNEL</span>
                <span class="t-val mono">PYTHON 3.10 · NUMPY / SCIPY</span>
              </div>
              <div class="telemetry-row">
                <span class="t-key label">ACTIVE DESK</span>
                <span class="t-val mono">{{ telemetry?.activeRoute || 'DESK' }}</span>
              </div>
            </div>
          </section>
        </div>

        <!-- Footer / Sign-out -->
        <footer class="drawer-foot">
          <button type="button" class="btn-signout" :disabled="isSigningOut" @click="handleSignOut">
            <AppIcon name="signout" :size="14" class="signout-btn-icon" />
            <span class="signout-btn-label label">
              {{ isSigningOut ? 'EXITING OPERATOR SESSION…' : 'SIGN OUT OF OPERATOR WORKSTATION' }}
            </span>
          </button>
        </footer>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
.drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  background: var(--glass-overlay);
  backdrop-filter: var(--glass-blur-sm);
  -webkit-backdrop-filter: var(--glass-blur-sm);
  transition: opacity var(--dur) var(--ease-out);
}

.profile-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(400px, 100vw);
  z-index: calc(var(--z-overlay) + 1);
  display: flex;
  flex-direction: column;
  background: var(--glass-surface-hi);
  backdrop-filter: var(--glass-blur-lg);
  -webkit-backdrop-filter: var(--glass-blur-lg);
  border-left: var(--hair) solid var(--glass-border-hi);
  border-top: none;
  border-right: none;
  border-bottom: none;
  border-radius: 0;
  box-shadow: var(--glass-shadow-drawer), var(--glass-specular);
  overflow: hidden;
}

/* Slide Transition */
.drawer-slide-enter-active,
.drawer-slide-leave-active {
  transition:
    transform var(--dur) var(--ease-out),
    opacity var(--dur) var(--ease-out);
}
.drawer-slide-enter-from,
.drawer-slide-leave-to {
  transform: translateX(100%);
  opacity: 0.8;
}

/* Header */
.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--s4) var(--s5);
  border-bottom: var(--hair) solid var(--glass-border);
  background: rgba(0, 0, 0, 0.2);
}
.head-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.head-pre {
  color: var(--ink-ghost);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
}
.head-title {
  font-family: var(--font-display);
  font-size: var(--t-body);
  font-weight: 700;
  color: var(--ink);
  letter-spacing: var(--track-tight);
}
.btn-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--r-sm);
  border: var(--hair) solid var(--glass-border);
  background: rgba(255, 255, 255, 0.03);
  color: var(--ink-dim);
  font-size: var(--t-small);
  transition: all var(--dur-fast) var(--ease-out);
}
.btn-close:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: var(--glass-border-hi);
  color: var(--ink);
}

/* Body */
.drawer-body {
  flex: 1 1 auto;
  overflow-y: auto;
  overflow-x: hidden;
  padding: var(--s4) var(--s5);
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

/* Cards & Sections */
.drawer-section {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}
.section-label {
  color: var(--ink-ghost);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: var(--track-label);
}

.drawer-card {
  padding: var(--s3) var(--s4);
  background: rgba(0, 0, 0, 0.35);
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-md);
  box-shadow: var(--glass-shadow-sm), var(--glass-specular-subtle);
}

/* Operator Identity Card */
.operator-card {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  background: rgba(0, 0, 0, 0.45);
}
.operator-row {
  display: flex;
  align-items: center;
  gap: var(--s3);
}
.operator-avatar-wrap {
  position: relative;
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  border-radius: var(--r-sm);
  border: var(--hair) solid var(--glass-border-hi);
  background: var(--void-lift);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: visible;
}
.operator-avatar-img {
  width: 100%;
  height: 100%;
  border-radius: var(--r-sm);
  object-fit: cover;
}
.operator-avatar-initials {
  font-family: var(--font-data);
  font-size: var(--t-lead);
  font-weight: 700;
  color: var(--phosphor);
}
.operator-live-lamp {
  position: absolute;
  bottom: -2px;
  right: -2px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--phosphor);
  border: 1.5px solid var(--void);
}
.operator-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.operator-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.operator-name {
  font-family: var(--font-display);
  font-size: var(--t-small);
  font-weight: 700;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.operator-badge {
  font-size: 7.5px;
  font-weight: 700;
  padding: 1px 4px;
  border-radius: var(--r-xs);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
  color: var(--phosphor);
}
.operator-email {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.operator-role {
  font-size: 8.5px;
  color: var(--ink-ghost);
}

.operator-status-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s2);
  padding-top: var(--s2);
  border-top: var(--hair) solid var(--glass-border-subtle);
}
.status-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.status-label {
  font-size: 8px;
  color: var(--ink-ghost);
}
.status-val {
  font-size: var(--t-tiny);
  font-weight: 600;
  color: var(--ink-soft);
}

/* Preferences Controls */
.pref-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-bottom: var(--s3);
  border-bottom: var(--hair) solid var(--glass-border-subtle);
}
.pref-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.pref-title {
  font-size: var(--t-small);
  font-weight: 600;
  color: var(--ink);
}
.pref-state {
  font-size: var(--t-micro);
  color: var(--phosphor);
}
.pref-desc {
  font-size: var(--t-micro);
  color: var(--ink-faint);
  line-height: 1.35;
}

/* Segmented Control */
.segmented-control {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  background: rgba(0, 0, 0, 0.4);
  padding: 3px;
  border-radius: var(--r-sm);
  border: var(--hair) solid var(--glass-border);
}
.segment-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: var(--r-xs);
  border: var(--hair) solid transparent;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  font-weight: 600;
  transition: all var(--dur-fast) var(--ease-out);
}
.segment-btn:hover {
  color: var(--ink);
  background: rgba(255, 255, 255, 0.04);
}
.segment-btn.active {
  color: var(--ink);
  background: var(--panel-raise);
  border-color: var(--glass-border-hi);
  box-shadow: var(--glass-specular-subtle);
}
.segment-sub {
  font-size: 8px;
  color: var(--ink-ghost);
}
.segment-btn.active .segment-sub {
  color: var(--phosphor);
}
.segment-icon {
  opacity: 0.8;
}

/* Accent Swatches */
.accent-swatches {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
}
.accent-pill {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 6px 4px;
  border-radius: var(--r-sm);
  border: var(--hair) solid var(--glass-border);
  background: rgba(0, 0, 0, 0.3);
  color: var(--ink-dim);
  transition: all var(--dur-fast) var(--ease-out);
}
.accent-pill:hover {
  border-color: var(--glass-border-hi);
  color: var(--ink);
}
.accent-pill.active {
  border-color: var(--glass-border-accent);
  background: rgba(255, 255, 255, 0.05);
  box-shadow: var(--glass-specular-subtle);
  color: var(--ink);
}
.swatch-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: 0 0 8px;
}
.swatch-label {
  font-size: 8.5px;
}

/* Toggle Rows */
.pref-toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s2) 0;
  cursor: pointer;
}
.toggle-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.toggle-title {
  font-size: var(--t-small);
  font-weight: 600;
  color: var(--ink);
}
.toggle-desc {
  font-size: var(--t-micro);
  color: var(--ink-faint);
  line-height: 1.3;
}
.toggle-switch {
  position: relative;
  width: 36px;
  height: 20px;
  flex: 0 0 36px;
  border-radius: 10px;
  border: var(--hair) solid var(--rule);
  background: rgba(0, 0, 0, 0.5);
  transition: all var(--dur-fast) var(--ease-out);
}
.toggle-switch.on {
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.toggle-knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--ink-ghost);
  transition:
    transform var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out);
}
.toggle-switch.on .toggle-knob {
  transform: translateX(16px);
  background: var(--phosphor);
}

/* Telemetry Card */
.telemetry-card {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}
.telemetry-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 3px 0;
  font-size: var(--t-micro);
}
.t-key {
  color: var(--ink-ghost);
  font-size: 8px;
}
.t-val-wrap {
  display: flex;
  align-items: center;
  gap: 5px;
}
.t-lamp {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--phosphor);
}
.t-val {
  font-size: var(--t-micro);
  color: var(--ink-soft);
}

/* Footer / Sign-out */
.drawer-foot {
  padding: var(--s4) var(--s5);
  border-top: var(--hair) solid var(--glass-border);
  background: rgba(0, 0, 0, 0.25);
}
.btn-signout {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--s2);
  width: 100%;
  min-height: 36px;
  padding: var(--s2) var(--s4);
  border-radius: var(--r-sm);
  border: var(--hair) solid var(--rule);
  background: rgba(255, 255, 255, 0.02);
  color: var(--ink-dim);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.btn-signout:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--short) 60%, var(--rule));
  background: var(--short-wash);
  color: var(--short);
}
.btn-signout:disabled {
  opacity: 0.5;
  cursor: wait;
}
.signout-btn-icon {
  color: inherit;
}
.signout-btn-label {
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: inherit;
}
</style>
