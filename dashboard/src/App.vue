<script setup lang="ts">
import { computed, nextTick, provide, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type StatusPayload, type Readiness, type MarketClock } from '@/api'
import { useResource } from '@/composables/useResource'
import { num, age } from '@/format'
import AppIcon from '@/components/AppIcon.vue'
import SearchPalette from '@/components/SearchPalette.vue'

const route = useRoute()
const router = useRouter()

/* The shell owns the two feeds every view needs, and hands them down. A single
   poller for status beats four views each opening their own. */
const status = useResource<StatusPayload>(() => api.status(), { intervalMs: 60_000 })
const readiness = useResource<Readiness>(() => api.readiness(), { intervalMs: 120_000 })
const marketClock = useResource<MarketClock>(() => api.marketClock(), { intervalMs: 30_000 })

provide('status', status)
provide('readiness', readiness)

const primaryNav = [
  { name: 'desk', idx: '01', title: 'Desk', hint: 'Posture · queue · arena', icon: 'desk' },
  { name: 'market', idx: '02', title: 'Market', hint: 'Symbol research', icon: 'market' },
  { name: 'options', idx: '03', title: 'Options', hint: 'One underlier', icon: 'options' },
  { name: 'flow', idx: '04', title: 'Flow', hint: 'Whole market', icon: 'flow' },
  { name: 'research', idx: '05', title: 'Research', hint: 'Methods · gates · models', icon: 'research' },
] as const

const secondaryNav = [
  { name: 'sectors', idx: 'M1', title: 'Sectors', hint: 'Rotation and leadership', icon: 'market' },
  { name: 'sentiment', idx: 'M2', title: 'Pulse', hint: 'Structure and outliers', icon: 'market' },
  { name: 'momentum', idx: 'M3', title: 'Momentum', hint: 'Five pillars scan', icon: 'market' },
  { name: 'fintel', idx: 'M4', title: 'Fintel', hint: 'Short, borrow, owners', icon: 'market' },
  { name: 'gates', idx: 'R1', title: 'Gates', hint: 'Pre-registered verdicts', icon: 'research' },
  { name: 'evolution', idx: 'R2', title: 'Evolution', hint: 'GA survivors lab', icon: 'research' },
  { name: 'adaptive', idx: 'R3', title: 'Live Blend', hint: 'Regime multi-stream', icon: 'research' },
  { name: 'graph', idx: 'R4', title: 'Graph', hint: 'Knowledge graph', icon: 'research' },
  { name: 'changepoints', idx: 'R5', title: 'Breaks', hint: 'Bayesian regime breaks', icon: 'research' },
  { name: 'cloud', idx: 'R6', title: 'Cloud', hint: 'Vertex AI training', icon: 'research' },
] as const

const moreOpen = ref(false)
const density = ref<'compact' | 'comfortable'>('compact')
const stage = ref<HTMLElement | null>(null)

const activeWorkspace = computed(() =>
  [...primaryNav, ...secondaryNav].find((item) => item.name === route.name)?.title ?? 'Desk',
)

const vol = computed(() => status.data.value?.latest_vol)
const cleared = computed(() => readiness.data.value?.cleared_for_live === true)
const universe = computed(() => status.data.value?.broad_universe_count ?? null)
const topSectorFlow = computed(() => {
  const sectors = (status.data.value?.sector_flow as any)?.sectors_ranked ?? []
  if (!sectors.length) return null
  return sectors[0]
})

/** Majors hedge funds pin risk to — warn pulse on rail when desk sees activity. */
const MAJORS = new Set([
  'SPY', 'QQQ', 'IWM', 'DIA', 'AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AMD',
])
const majorHits = computed(() => {
  const signals = (status.data.value?.directional_signals ?? []) as { symbol?: string; probability?: number }[]
  const pead = (status.data.value?.pead_candidates ?? []) as { symbol?: string }[]
  const hits = new Set<string>()
  for (const s of signals) {
    const sym = String(s.symbol || '').toUpperCase()
    if (MAJORS.has(sym) && (s.probability ?? 0) >= 0.55) hits.add(sym)
  }
  for (const p of pead) {
    const sym = String(p.symbol || '').toUpperCase()
    if (MAJORS.has(sym)) hits.add(sym)
  }
  return [...hits].slice(0, 6)
})
const volAlert = computed(() => {
  const v = vol.value
  if (!v) return false
  return (v.tail_risk ?? 0) >= 1.5 || (v.VIX ?? 0) >= 25
})
const enterCount = computed(() => {
  const signals = (status.data.value?.directional_signals ?? []) as { state?: string }[]
  return signals.filter((s) => s.state === 'ENTER').length
})
const stripWarning = computed(() => {
  if (status.error.value) return status.error.value
  if (volAlert.value) {
    const v = vol.value
    if ((v?.VIX ?? 0) >= 25) return `VIX elevated ${Number(v?.VIX).toFixed(1)}`
    if ((v?.tail_risk ?? 0) >= 1.5) return `Tail risk ${Number(v?.tail_risk).toFixed(2)}`
  }
  if (marketClock.data.value?.warning) return marketClock.data.value.warning
  return null
})
function navAlert(name: string): boolean {
  if (name === 'desk' || name === 'market') return majorHits.value.length > 0 || enterCount.value > 0
  if (name === 'flow') return volAlert.value || Boolean(topSectorFlow.value && Math.abs(Number((topSectorFlow.value as any).flow_score ?? 0)) > 0.02)
  if (name === 'options') return volAlert.value
  return false
}

const secondaryActive = computed(() =>
  secondaryNav.some((n) => route.name === n.name)
)
function gaugeTone(kind: 'vix' | 'tail' | 'signals'): string {
  if (kind === 'vix') {
    const v = vol.value?.VIX ?? 0
    if (v >= 25) return 'hot'
    if (v >= 18) return 'warm'
    return 'ok'
  }
  if (kind === 'tail') {
    const t = vol.value?.tail_risk ?? 0
    if (t >= 1.5) return 'hot'
    if (t >= 1.0) return 'warm'
    return 'ok'
  }
  return enterCount.value > 0 ? 'hot' : 'ok'
}

/* Wall clock, UTC — the only timezone a multi-venue desk should trust. */
const clock = ref(utcNow())
let tick: number | undefined
function utcNow(): string {
  return new Date().toISOString().slice(11, 19)
}

const marketSessionLabel = computed(() => {
  if (marketClock.error.value) return 'CAL FAULT'
  const labels: Record<string, string> = {
    regular: 'RTH OPEN',
    premarket: 'PREMARKET',
    after_hours: 'AFTER HOURS',
    closed: 'MARKET CLOSED',
    replay: 'REPLAY',
  }
  return labels[marketClock.data.value?.market_session ?? ''] ?? 'CAL SYNC'
})

const marketSessionClass = computed(() => marketClock.data.value?.market_session ?? 'unknown')

const marketTransition = computed(() => {
  // Reading clock.value makes this countdown update on the shell's 1s timer.
  void clock.value
  const data = marketClock.data.value
  if (!data?.next_transition_utc || !data.next_transition) return 'NEXT n/a'
  const seconds = Math.max(0, Math.floor((Date.parse(data.next_transition_utc) - Date.now()) / 1000))
  const days = Math.floor(seconds / 86_400)
  const hours = Math.floor((seconds % 86_400) / 3_600)
  const minutes = Math.floor((seconds % 3_600) / 60)
  const secs = seconds % 60
  const countdown = days > 0
    ? `${days}D ${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
    : `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
  const verbs: Record<string, string> = {
    premarket_opens: 'PRE IN',
    regular_opens: 'OPEN IN',
    regular_closes: 'CLOSE IN',
    after_hours_closes: 'EXT CLOSE',
  }
  return `${verbs[data.next_transition] ?? 'NEXT'} ${countdown}`
})

const marketClockTitle = computed(() => {
  const data = marketClock.data.value
  if (!data) return marketClock.error.value ?? 'Loading XNYS calendar'
  const details = [`Source: ${data.calendar_source}`]
  if (data.regular_close_utc) details.push(`RTH close: ${data.regular_close_utc}`)
  if (data.warning) details.push(data.warning)
  return details.join('\n')
})

const paletteOpen = ref(false)

function isTypingTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLInputElement
    || target instanceof HTMLTextAreaElement
    || target instanceof HTMLSelectElement
    || (target instanceof HTMLElement && target.isContentEditable)
}

function toggleDensity(): void {
  density.value = density.value === 'compact' ? 'comfortable' : 'compact'
}

function onKey(e: KeyboardEvent): void {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    paletteOpen.value = true
  }
  if (e.key === 'Escape') paletteOpen.value = false
  if (e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey && !isTypingTarget(e.target)) {
    e.preventDefault()
    paletteOpen.value = true
  }
}

onMounted(() => {
  const savedDensity = window.localStorage.getItem('edge-density')
  if (savedDensity === 'compact' || savedDensity === 'comfortable') density.value = savedDensity
  tick = window.setInterval(() => (clock.value = utcNow()), 1000)
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => {
  if (tick !== undefined) clearInterval(tick)
  window.removeEventListener('keydown', onKey)
})

watch(density, (value) => {
  document.documentElement.dataset.density = value
  window.localStorage.setItem('edge-density', value)
}, { immediate: true })

watch(() => route.fullPath, async () => {
  moreOpen.value = false
  await nextTick()
  stage.value?.focus({ preventScroll: true })
})

function openSymbol(sym: string): void {
  paletteOpen.value = false
  const clean = sym.trim().toUpperCase()
  if (!clean) return
  const currentName = String(route.name || '')
  if (currentName === 'flow' || currentName === 'flowstate') {
    void router.push({ name: 'options', query: { symbol: clean } })
    return
  }
  const symbolViews = new Set(['market', 'options', 'changepoints', 'sentiment', 'momentum'])
  const targetRouteName = symbolViews.has(currentName) ? currentName : 'market'
  void router.push({ name: targetRouteName, query: { ...route.query, symbol: clean } })
}
</script>

<template>
  <div class="shell">
    <a class="skip-link" href="#main-content">Skip to workspace</a>
    <!-- ── left rail ────────────────────────────────────────────────────── -->
    <nav class="rail" aria-label="Primary">
      <!-- Profile / armed state block -->
      <div class="profile-block" :class="cleared ? 'armed' : 'safe'" :title="cleared ? 'Live armed — cleared for trading' : 'Research only — not cleared for live'">
        <span class="profile-dot" aria-hidden="true" />
        <span class="profile-label label">{{ cleared ? 'LIVE' : 'RSCH' }}</span>
      </div>

      <RouterLink to="/" class="mark" aria-label="Edge instrument home">
        <span class="mark-e">E</span>
        <span class="mark-rule" aria-hidden="true" />
      </RouterLink>

      <ul class="nav">
        <li v-for="n in primaryNav" :key="n.name">
          <RouterLink
            :to="{ name: n.name }"
            class="nav-item"
            :class="{ on: route.name === n.name, alert: navAlert(n.name) }"
            :title="navAlert(n.name)
              ? `${n.title} · ${n.hint} · alert: ${majorHits.join(' ') || 'elevated regime'}`
              : `${n.title} · ${n.hint}`"
          >
            <AppIcon class="nav-icon" :name="n.icon" :size="18" />
            <span class="nav-title label">{{ n.title }}</span>
            <span v-if="navAlert(n.name)" class="nav-pulse" aria-hidden="true" />
          </RouterLink>
        </li>
      </ul>

      <!-- More: secondary views dropdown -->
      <div class="more-wrap">
        <button
          class="more-btn nav-item"
          :class="{ on: secondaryActive || moreOpen }"
          :aria-expanded="moreOpen"
          :title="moreOpen ? 'Close tools' : 'Open market and research tools'"
          @click="moreOpen = !moreOpen"
        >
          <AppIcon class="nav-icon" name="more" :size="18" />
          <span class="nav-title label">Tools</span>
        </button>
        <div v-if="moreOpen" class="more-panel" role="menu" aria-label="Market and research tools">
          <button class="more-search" type="button" role="menuitem" @click="moreOpen = false; paletteOpen = true">
            <AppIcon name="search" :size="16" />
            <span class="more-title label">Search</span>
            <span class="more-idx fig">⌘K</span>
          </button>
          <RouterLink
            v-for="n in secondaryNav"
            :key="n.name"
            :to="{ name: n.name }"
            class="more-item"
            :class="{ on: route.name === n.name }"
            :title="n.hint"
            role="menuitem"
            @click="moreOpen = false"
          >
            <AppIcon :name="n.icon" :size="16" />
            <span class="more-title label">{{ n.title }}</span>
            <span class="more-idx fig">{{ n.idx }}</span>
          </RouterLink>
        </div>
      </div>

      <button class="find" type="button" @click="paletteOpen = true" title="Search symbols and workspaces (⌘K)">
        <AppIcon name="search" :size="18" />
        <span class="label find-label">Search</span>
        <span class="label find-key">⌘K</span>
      </button>
    </nav>

    <!-- ── instrument strip ─────────────────────────────────────────────── -->
    <header class="strip">
      <div class="lamp-block" :class="cleared ? 'armed' : 'safe'">
        <span class="lamp" aria-hidden="true" />
        <div class="lamp-txt">
          <span class="label lamp-lab">{{ cleared ? 'Live armed' : 'Research only' }}</span>
          <span class="label lamp-sub">
            {{ readiness.data.value ? `${readiness.data.value.blocking_reasons.length} blocking` : 'n/a' }}
          </span>
        </div>
      </div>

      <span class="div" aria-hidden="true" />

      <div class="workspace-context">
        <span class="label">Workspace</span>
        <span class="fig workspace-name">{{ activeWorkspace }}</span>
      </div>

      <div class="gauges">
        <div
          class="gauge"
          :class="gaugeTone('vix')"
          :title="`VIX ${num(vol?.VIX, 2)} — implied vol index priced from the options chain. Backward propagation computes sensitivity and realized-variance premia backward across dealer books; forward propagation marks where new hedges will print next. Elevated ≥25 signals tail-risk hedging demand and compressed carry.`"
        >
          <span class="label">VIX</span>
          <span class="fig g-val">{{ num(vol?.VIX, 2) }}</span>
          <span class="g-spark" aria-hidden="true"><i :style="{ width: `${Math.min(100, ((vol?.VIX ?? 0) / 40) * 100)}%` }" /></span>
        </div>
        <div class="gauge">
          <span class="label">Term slope</span>
          <span class="fig g-val">{{ num(vol?.term_slope, 4) }}</span>
        </div>
        <div class="gauge" :class="gaugeTone('tail')">
          <span class="label">Tail risk</span>
          <span class="fig g-val">{{ num(vol?.tail_risk, 2) }}</span>
          <span class="g-spark" aria-hidden="true"><i :style="{ width: `${Math.min(100, ((vol?.tail_risk ?? 0) / 2.5) * 100)}%` }" /></span>
        </div>
        <div class="gauge">
          <span class="label">Universe</span>
          <span class="fig g-val">{{ universe ?? 'n/a' }}</span>
        </div>
        <div class="gauge" :class="gaugeTone('signals')" :title="`${enterCount} ENTER · ${status.data.value?.directional_signals?.length ?? 0} scored`">
          <span class="label">Signals</span>
          <span class="fig g-val">
            <template v-if="status.data.value?.directional_signals">
              {{ enterCount }}<span class="g-sub">/{{ status.data.value.directional_signals.length }}</span>
            </template>
            <template v-else>n/a</template>
          </span>
        </div>
        <div class="gauge" :title="topSectorFlow ? `${topSectorFlow.name || topSectorFlow.etf}` : ''">
          <span class="label">Top Sector</span>
          <span class="fig g-val">{{ topSectorFlow ? `${topSectorFlow.etf}` : 'n/a' }}</span>
        </div>
        <div v-if="majorHits.length" class="gauge gauge-alert" :title="`Major names flagged: ${majorHits.join(', ')}`">
          <span class="label">Majors</span>
          <span class="fig g-val alert-val">{{ majorHits.slice(0, 3).join(' ') }}</span>
        </div>
      </div>

      <span class="spacer" />

      <div
        v-if="stripWarning"
        class="strip-warn"
        :title="stripWarning"
      >
        <AppIcon name="alert" :size="14" />
        <span class="label">{{ stripWarning }}</span>
      </div>

      <div
        class="market-clock"
        :class="[marketSessionClass, { early: marketClock.data.value?.is_early_close }]"
        :title="marketClockTitle"
      >
        <span class="label market-state">
          {{ marketSessionLabel }}
          <template v-if="marketClock.data.value?.is_early_close"> · EARLY CLOSE</template>
        </span>
        <span class="fig market-next">{{ marketTransition }}</span>
      </div>



      <button
        class="density-control"
        type="button"
        :title="`Density: ${density}. Toggle compact and comfortable layouts.`"
        @click="toggleDensity"
      >
        <AppIcon name="density" :size="15" />
        <span class="label">{{ density === 'compact' ? 'Compact' : 'Comfort' }}</span>
      </button>

      <div class="clock">
        <span class="fig clock-val">{{ clock }}</span>
        <span class="label">UTC</span>
      </div>
    </header>

    <!-- ── content ──────────────────────────────────────────────────────── -->
    <main id="main-content" ref="stage" class="stage" tabindex="-1">
      <RouterView v-slot="{ Component }">
        <component :is="Component" />
      </RouterView>
    </main>

    <!-- ── status footer — always visible ─────────────────────────────────── -->
    <footer class="foot">
      <span class="foot-label label">Feed</span>
      <span
        class="foot-state label"
        :class="{ ok: !status.error.value, stale: !!status.error.value }"
        :title="status.error.value ?? 'Backend status feed'"
      >
        {{ status.loading.value ? 'SYNC' : status.error.value ? 'FAULT' : 'OK' }}
        <template v-if="status.fetchedAt.value"> · {{ age(status.fetchedAt.value) }}</template>
      </span>
      <span class="foot-div" aria-hidden="true" />
      <span class="foot-label label">UTC</span>
      <span class="fig foot-clock">{{ clock }}</span>
    </footer>

    <SearchPalette
      v-if="paletteOpen"
      :symbol-count="status.data.value?.searchable_symbol_count"
      @close="paletteOpen = false"
      @select="openSymbol"
    />
  </div>
</template>

<style scoped>
.shell {
  position: relative;
  z-index: 2;
  display: grid;
  /* `minmax(0, 1fr)` keeps a wide data table inside the stage's own scroll
     region instead of allowing its intrinsic width to push the shell past the
     viewport. */
  grid-template-columns: var(--rail-w) minmax(0, 1fr);
  grid-template-rows: var(--strip-h) 1fr auto;
  grid-template-areas:
    'rail strip'
    'rail stage'
    'rail foot';
  height: 100%;
  /* Defense in depth, matching body's promise below: a grid item's intrinsic
     min-content size can otherwise force this box (and the document with it)
     taller than the viewport — see .rail's min-height/overflow for the actual
     fix. This just guarantees nothing can silently repeat that upward. */
  overflow: hidden;
}

.skip-link {
  position: fixed;
  left: var(--s3);
  top: var(--s3);
  z-index: var(--z-toast);
  transform: translateY(-160%);
  padding: var(--s2) var(--s3);
  color: var(--void);
  background: var(--phosphor);
  font: 700 var(--t-small) var(--font-display);
  text-decoration: none;
}
.skip-link:focus { transform: none; }

/* ---- rail ---------------------------------------------------------------- */
.rail {
  grid-area: rail;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: var(--s2);
  padding: var(--s3) 0 var(--s4);
  border-right: var(--hair) solid var(--rule);
  background: var(--void-lift);
  z-index: var(--z-rail);
  /* .rail spans all three grid rows as one item, so its automatic minimum
     size (min-content height) would otherwise force the shared 1fr row —
     and with it #app/.shell/the whole document — to grow past the viewport
     whenever the 13 nav items + logo + find button don't fit. min-height: 0
     opts out of that, so an overflowing rail scrolls internally instead. */
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}

.mark {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s2);
  padding-bottom: var(--s2);
  text-decoration: none;
}
.mark:hover { text-decoration: none; }

.mark-e {
  font-family: var(--font-display);
  font-size: 1.125rem;
  font-weight: 800;
  color: var(--phosphor);
  letter-spacing: -0.04em;
  line-height: 1;
}

.mark-rule {
  width: 22px;
  height: var(--hair);
  background: var(--rule-hi);
}

/* ---- profile block ------------------------------------------------------- */
.profile-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: var(--s2) 0 var(--s1);
  cursor: default;
}
.profile-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: 0 0 auto;
}
.safe .profile-dot { background: var(--warn); }
.armed .profile-dot {
  background: var(--phosphor);
}
.profile-label {
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.08em;
}
.safe .profile-label { color: var(--warn); }
.armed .profile-label { color: var(--phosphor); }

/* ---- nav ------------------------------------------------------------------ */
.nav {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  min-height: 48px;
  padding: var(--s2) var(--s2);
  color: var(--ink-dim);
  text-decoration: none;
  transition: color var(--dur-fast) var(--ease-out),
              background var(--dur-fast) var(--ease-out);
}
.nav-item:hover { color: var(--ink); background: var(--panel-hi); text-decoration: none; }

.nav-item.on {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  font-weight: 700;
}

/* The active marker is a phosphor bar on the inner edge */
.nav-item.on::after {
  content: '';
  position: absolute;
  right: 0;
  top: 15%;
  bottom: 15%;
  width: 3px;
  background: var(--phosphor);
}

.nav-item.alert {
  color: var(--warn);
}
.nav-item.alert.on { color: var(--phosphor); }
.nav-pulse {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warn);
  opacity: 0.9;
}

.nav-icon { color: currentColor; }
.nav-title { color: inherit; font-size: var(--t-micro); font-weight: 700; }
.gauge-alert .alert-val {
  color: var(--warn);
  max-width: 14ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---- more dropdown ------------------------------------------------------- */
.more-wrap {
  position: relative;
}
.more-btn {
  width: 100%;
  border: none;
  cursor: pointer;
  background: transparent;
}
.more-panel {
  position: absolute;
  left: calc(100% + 2px);
  top: 0;
  z-index: calc(var(--z-rail) + 10);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-hi);
  min-width: 208px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.4);
}
.more-item {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  color: var(--ink-dim);
  text-decoration: none;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
  white-space: nowrap;
}
.more-search {
  display: flex;
  width: 100%;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  color: var(--ink-soft);
  border-bottom: var(--hair) solid var(--rule);
  background: var(--panel);
  text-align: left;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.more-search:hover { color: var(--phosphor); background: var(--phosphor-wash); }
.more-item:hover { background: var(--panel-hi); color: var(--ink); }
.more-item.on { color: var(--phosphor); background: var(--phosphor-wash); font-weight: 700; }
.more-idx { font-size: var(--t-micro); opacity: 0.85; font-weight: 700; min-width: 2.5ch; }
.more-idx { margin-left: auto; color: var(--ink-ghost); text-align: right; }
.more-title { font-size: var(--t-micro); font-weight: 700; }

/* ---- find ---------------------------------------------------------------- */
.find {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  min-height: 48px;
  padding: var(--s2) var(--s1);
  color: var(--ink-dim);
  transition: color var(--dur-fast) var(--ease-out);
}
.find:hover { color: var(--phosphor); }
.find-label { color: inherit; font-size: 9px; }
.find-key { color: var(--ink-ghost); font-size: 8px; }

/* ---- strip --------------------------------------------------------------- */
.strip {
  grid-area: strip;
  display: flex;
  align-items: center;
  gap: var(--s4);
  padding: 0 var(--s5) 0 var(--s4);
  border-bottom: var(--hair) solid var(--rule);
  background: var(--void-lift);
  z-index: var(--z-strip);
}

.lamp-block {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex: 0 0 auto;
}

.lamp {
  position: relative;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  overflow: hidden;
  flex: 0 0 auto;
}

/* Not-cleared is the truthful resting state */
.safe .lamp { background: var(--warn); }
.armed .lamp { background: var(--phosphor); }

.armed .lamp::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(to bottom, transparent, rgba(255, 255, 255, 0.9), transparent);
  animation: sweep 1.8s var(--ease-in-out) infinite;
}

.lamp-txt { display: flex; flex-direction: column; gap: 1px; }
.lamp-lab { color: var(--ink); font-weight: 700; }
.safe .lamp-lab { color: var(--warn); }
.armed .lamp-lab { color: var(--phosphor); }
.lamp-sub { color: var(--ink-dim); font-size: var(--t-micro); }

.div {
  width: var(--hair);
  height: 28px;
  background: var(--rule);
  flex: 0 0 auto;
}

.workspace-context {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 0 0 auto;
  min-width: 72px;
}
.workspace-name {
  color: var(--ink);
  font-size: var(--t-small);
  font-weight: 600;
}

.gauges {
  display: flex;
  align-items: center;
  gap: var(--s5);
  min-width: 0;
  overflow: hidden;
}

.gauge { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.g-val { font-size: var(--t-small); color: var(--ink); font-weight: 600; }
.g-sub { color: var(--ink-ghost); font-weight: 500; font-size: 0.85em; }
.g-spark {
  display: block;
  width: 48px;
  height: 2px;
  margin-top: 3px;
  background: var(--rule);
  overflow: hidden;
}
.g-spark i { display: block; height: 100%; background: var(--phosphor-dim); }
.gauge.warm .g-val { color: var(--warn); }
.gauge.warm .g-spark i { background: var(--warn); }
.gauge.hot .g-val { color: var(--short); }
.gauge.hot .g-spark i { background: var(--short); }
.gauge.ok .g-spark i { background: var(--phosphor-dim); }

.strip-warn {
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: 28ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--warn);
  font-weight: 700;
  padding: 3px 8px;
  border: var(--hair) solid color-mix(in srgb, var(--warn) 45%, transparent);
  background: var(--warn-wash);
  flex: 0 0 auto;
}

.spacer { flex: 1 1 auto; }

.market-clock {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
  flex: 0 0 auto;
  padding-left: var(--s4);
  border-left: var(--hair) solid var(--rule);
}
.market-state { color: var(--ink-dim); font-weight: 700; }
.market-next { color: var(--ink); font-size: var(--t-small); font-weight: 600; }
.market-clock.regular .market-state { color: var(--phosphor); }
.market-clock.premarket .market-state,
.market-clock.after_hours .market-state { color: var(--ink-soft); }
.market-clock.closed .market-state,
.market-clock.early .market-state,
.market-clock.unknown .market-state { color: var(--warn); }

/* feed moved to .foot */

.density-control {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 4px 7px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
  background: var(--panel);
  transition: color var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.density-control:hover { color: var(--phosphor); border-color: var(--phosphor-dim); background: var(--panel-hi); }

.clock { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; }
.clock-val {
  font-size: var(--t-small);
  color: var(--ink);
  font-weight: 600;
  letter-spacing: 0.04em;
}

/* ---- stage --------------------------------------------------------------- */
.stage {
  grid-area: stage;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding: var(--s5);
}
.stage:focus { outline: none; }

/* ---- footer (feed + clock — always visible) ------------------------------ */
.foot {
  grid-area: foot;
  display: flex;
  align-items: center;
  gap: var(--s4);
  padding: 0 var(--s5);
  height: 28px;
  border-top: var(--hair) solid var(--rule);
  background: var(--void-lift);
  z-index: var(--z-strip);
}

.foot-label { color: var(--ink-ghost); }
.foot-state { font-weight: 700; }
.foot-state.ok { color: var(--long); }
.foot-state.stale { color: var(--short); }

.foot-div {
  width: var(--hair);
  height: 14px;
  background: var(--rule);
  flex: 0 0 auto;
}

.foot-clock {
  font-size: var(--t-small);
  color: var(--ink);
  font-weight: 600;
  letter-spacing: 0.04em;
}

@media (max-width: 1100px) {
  .gauges { gap: var(--s4); }
  .gauge:nth-child(n + 5) { display: none; }
  .workspace-context { display: none; }
}

@media (max-width: 780px) {
  .shell {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: 52px minmax(0, 1fr) 64px;
    grid-template-areas:
      'strip'
      'stage'
      'rail';
  }
  .rail {
    flex-direction: row;
    align-items: stretch;
    gap: 0;
    padding: 0;
    border-top: var(--hair) solid var(--rule-hi);
    border-right: 0;
    overflow-x: auto;
    overflow-y: hidden;
  }
  .profile-block, .mark { display: none; }
  .nav li:nth-child(5), .find { display: none; }
  .nav { flex: 1 1 auto; flex-direction: row; gap: 0; min-width: 0; overflow-x: auto; }
  .nav li { display: flex; flex: 1 0 52px; }
  .nav-item {
    flex: 1 1 auto;
    min-height: 64px;
    height: 64px;
    justify-content: center;
    padding: 6px 3px;
  }
  .nav-item.on::after { top: auto; right: 18%; bottom: 0; left: 18%; width: auto; height: 2px; }
  .nav-pulse { top: 8px; right: calc(50% - 15px); }
  .more-wrap, .find { flex: 0 0 52px; width: 52px; margin-top: 0; }
  .more-btn, .find { min-height: 64px; height: 64px; }
  .more-panel { top: auto; right: 0; bottom: calc(100% + 2px); left: auto; }
  .foot { display: none; }
  .gauges { display: none; }
  .stage { padding: var(--s3); }
  .nav-title { font-size: 8px; }
  .find-label { font-size: 8px; }
  .find-key { display: none; }
  .density-control { padding: 6px; }
  .density-control .label, .clock { display: none; }
  .lamp-txt, .strip-warn { display: none; }
  .strip { gap: var(--s3); padding: 0 var(--s3); }
  .more-panel { left: calc(100% + 1px); }
}
</style>
