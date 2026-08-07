<script setup lang="ts">
import { computed, provide, ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type StatusPayload, type Readiness, type MarketClock } from '@/api'
import { useResource } from '@/composables/useResource'
import { num, age } from '@/format'
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

const nav = [
  { name: 'desk', idx: '01', title: 'Desk', hint: 'Signals & candidates' },
  { name: 'market', idx: '02', title: 'Market', hint: 'Search · VWAP · EMA' },
  { name: 'sectors', idx: '03', title: 'Sectors', hint: 'Sector rotation & flow' },
  { name: 'sentiment', idx: '04', title: 'Pulse', hint: 'Structure · COT · outliers' },
  { name: 'options', idx: '05', title: 'Options', hint: 'Flow · gamma · density' },
  { name: 'gates', idx: '06', title: 'Gates', hint: 'Pre-registered verdicts' },
  { name: 'cloud', idx: '07', title: 'Cloud', hint: 'Vertex AI training' },
  { name: 'evolution', idx: '08', title: 'Evolution', hint: 'GA survivors lab' },
  { name: 'research', idx: '09', title: 'Research', hint: 'IC decay · quantile spread' },
  { name: 'graph', idx: '10', title: 'Graph', hint: 'Repo knowledge graph' },
  { name: 'adaptive', idx: '11', title: 'Live Blend', hint: 'Regime multi-stream adapt' },
  { name: 'fintel', idx: '12', title: 'Fintel', hint: 'Short · borrow · owners · flow' },
  { name: 'changepoints', idx: '13', title: 'Breaks', hint: 'Bayesian regime breaks' },
] as const

const vol = computed(() => status.data.value?.latest_vol)
const cleared = computed(() => readiness.data.value?.cleared_for_live === true)
const universe = computed(() => status.data.value?.broad_universe_count ?? null)
const topSectorFlow = computed(() => {
  const sectors = (status.data.value?.sector_flow as any)?.sectors_ranked ?? []
  if (!sectors.length) return null
  return sectors[0]
})

/** Majors hedge funds pin risk to — glow rail when desk sees activity. */
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
  if (name === 'sentiment') return volAlert.value
  if (name === 'sectors') return Boolean(topSectorFlow.value && Math.abs(Number((topSectorFlow.value as any).flow_score ?? 0)) > 0.02)
  if (name === 'options') return volAlert.value
  return false
}
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

function onKey(e: KeyboardEvent): void {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    paletteOpen.value = true
  }
  if (e.key === 'Escape') paletteOpen.value = false
  // Digit shortcuts jump between views the way a terminal function key would.
  // The regex only matches a single keypress "1".."9", so this only ever
  // reaches nav[0..8] — views 10 (Graph), 11 (Live Blend), 12 (Fintel) and
  // now 13 (Breaks) have no single-key shortcut. That was already true
  // before this view was added; ⌘K search or the rail click remain the way
  // to reach them. Not fixed here since it is a pre-existing behaviour, not
  // something this change introduced.
  if (!e.metaKey && !e.ctrlKey && !e.altKey && /^[1-9]$/.test(e.key)) {
    const target = document.activeElement
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return
    const item = nav[Number(e.key) - 1]
    if (item) void router.push({ name: item.name })
  }
}

onMounted(() => {
  tick = window.setInterval(() => (clock.value = utcNow()), 1000)
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => {
  if (tick !== undefined) clearInterval(tick)
  window.removeEventListener('keydown', onKey)
})

function openSymbol(sym: string): void {
  paletteOpen.value = false
  void router.push({ name: 'market', query: { symbol: sym } })
}
</script>

<template>
  <div class="shell">
    <!-- ── left rail ────────────────────────────────────────────────────── -->
    <nav class="rail" aria-label="Primary">
      <RouterLink to="/" class="mark" aria-label="Edge instrument home">
        <span class="mark-e">E</span>
        <span class="mark-rule" aria-hidden="true" />
      </RouterLink>

      <ul class="nav">
        <li v-for="n in nav" :key="n.name">
          <RouterLink
            :to="{ name: n.name }"
            class="nav-item"
            :class="{ on: route.name === n.name, alert: navAlert(n.name) }"
            :title="navAlert(n.name)
              ? `${n.title} · ${n.hint} · alert: ${majorHits.join(' ') || 'elevated regime'}`
              : `${n.title} · ${n.hint}`"
          >
            <span class="nav-idx fig">{{ n.idx }}</span>
            <span class="nav-title label">{{ n.title }}</span>
            <span v-if="navAlert(n.name)" class="nav-pulse" aria-hidden="true" />
          </RouterLink>
        </li>
      </ul>

      <button class="find" @click="paletteOpen = true" title="Search symbols (⌘K)">
        <span class="find-glyph" aria-hidden="true">⌕</span>
        <span class="label">⌘K</span>
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

      <div class="gauges">
        <div class="gauge" :class="gaugeTone('vix')">
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
        class="strip-warn label"
        :title="stripWarning"
      >
        ⚠ {{ stripWarning }}
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



      <div class="clock">
        <span class="fig clock-val">{{ clock }}</span>
        <span class="label">UTC</span>
      </div>
    </header>

    <!-- ── content ──────────────────────────────────────────────────────── -->
    <main class="stage">
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
  grid-template-columns: var(--rail-w) 1fr;
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
  padding: var(--s3) var(--s2);
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
  animation: nav-glow 1.6s ease-in-out infinite;
}
@keyframes nav-glow {
  0%, 100% { opacity: 0.45; transform: scale(0.9); }
  50% { opacity: 1; transform: scale(1.15); }
}

.nav-idx { font-size: var(--t-micro); opacity: 0.85; font-weight: 700; }
.nav-title { color: inherit; font-size: var(--t-micro); font-weight: 700; }
.gauge-alert .alert-val {
  color: var(--warn);
  max-width: 14ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.find {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: var(--s3) var(--s1);
  color: var(--ink-dim);
  transition: color var(--dur-fast) var(--ease-out);
}
.find:hover { color: var(--phosphor); }
.find-glyph { font-size: 1.1rem; line-height: 1; }

/* ---- strip --------------------------------------------------------------- */
.strip {
  grid-area: strip;
  display: flex;
  align-items: center;
  gap: var(--s4);
  padding: 0 var(--s5) 0 var(--s4);
  border-bottom: var(--hair) solid var(--rule);
  background: linear-gradient(to bottom, var(--void-lift), var(--void));
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
}

@media (max-width: 780px) {
  .shell { grid-template-columns: 56px 1fr; }
  .gauges { display: none; }
  .stage { padding: var(--s3); }
}
</style>
