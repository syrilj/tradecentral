<script setup lang="ts">
import { computed, provide, ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type StatusPayload, type Readiness } from '@/api'
import { useResource } from '@/composables/useResource'
import { num, age } from '@/format'
import SearchPalette from '@/components/SearchPalette.vue'

const route = useRoute()
const router = useRouter()

/* The shell owns the two feeds every view needs, and hands them down. A single
   poller for status beats four views each opening their own. */
const status = useResource<StatusPayload>(() => api.status(), { intervalMs: 60_000 })
const readiness = useResource<Readiness>(() => api.readiness(), { intervalMs: 120_000 })

provide('status', status)
provide('readiness', readiness)

const nav = [
  { name: 'desk', idx: '01', title: 'Desk', hint: 'Signals & candidates' },
  { name: 'market', idx: '02', title: 'Market', hint: 'Search & trajectories' },
  { name: 'sectors', idx: '03', title: 'Sectors', hint: 'Sector rotation & flow' },
  { name: 'gates', idx: '04', title: 'Gates', hint: 'Pre-registered verdicts' },
  { name: 'cloud', idx: '05', title: 'Cloud', hint: 'Vertex AI training' },
] as const

const vol = computed(() => status.data.value?.latest_vol)
const cleared = computed(() => readiness.data.value?.cleared_for_live === true)
const universe = computed(() => status.data.value?.broad_universe_count ?? null)
const topSectorFlow = computed(() => {
  const sectors = (status.data.value?.sector_flow as any)?.sectors_ranked ?? []
  if (!sectors.length) return null
  return sectors[0]
})

/* Wall clock, UTC — the only timezone a multi-venue desk should trust. */
const clock = ref(utcNow())
let tick: number | undefined
function utcNow(): string {
  return new Date().toISOString().slice(11, 19)
}

const paletteOpen = ref(false)

function onKey(e: KeyboardEvent): void {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    paletteOpen.value = true
  }
  if (e.key === 'Escape') paletteOpen.value = false
  // Digit shortcuts jump between views the way a terminal function key would.
  if (!e.metaKey && !e.ctrlKey && !e.altKey && /^[1-5]$/.test(e.key)) {
    const target = document.activeElement
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return
    void router.push({ name: nav[Number(e.key) - 1].name })
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
            :class="{ on: route.name === n.name }"
            :title="`${n.title} — ${n.hint}`"
          >
            <span class="nav-idx fig">{{ n.idx }}</span>
            <span class="nav-title label">{{ n.title }}</span>
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
            {{ readiness.data.value ? `${readiness.data.value.blocking_reasons.length} blocking` : '—' }}
          </span>
        </div>
      </div>

      <span class="div" aria-hidden="true" />

      <div class="gauges">
        <div class="gauge">
          <span class="label">VIX</span>
          <span class="fig g-val">{{ num(vol?.VIX, 2) }}</span>
        </div>
        <div class="gauge">
          <span class="label">Term slope</span>
          <span class="fig g-val">{{ num(vol?.term_slope, 4) }}</span>
        </div>
        <div class="gauge">
          <span class="label">Tail risk</span>
          <span class="fig g-val">{{ num(vol?.tail_risk, 2) }}</span>
        </div>
        <div class="gauge">
          <span class="label">Universe</span>
          <span class="fig g-val">{{ universe ?? '—' }}</span>
        </div>
        <div class="gauge">
          <span class="label">Signals</span>
          <span class="fig g-val">{{ status.data.value?.directional_signals?.length ?? '—' }}</span>
        </div>
        <div class="gauge">
          <span class="label">Top Sector</span>
          <span class="fig g-val">{{ topSectorFlow ? `${topSectorFlow.etf}` : '—' }}</span>
        </div>
      </div>

      <span class="spacer" />

      <div v-if="status.error.value" class="fault label" :title="status.error.value">
        ⚠ {{ status.error.value }}
      </div>

      <div class="feed">
        <span class="label">Feed</span>
        <span class="feed-state label" :class="{ ok: !status.error.value, stale: !!status.error.value }">
          {{ status.loading.value ? 'SYNC' : status.error.value ? 'FAULT' : 'OK' }}
          <template v-if="status.fetchedAt.value"> · {{ age(status.fetchedAt.value) }}</template>
        </span>
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

    <SearchPalette v-if="paletteOpen" @close="paletteOpen = false" @select="openSymbol" />
  </div>
</template>

<style scoped>
.shell {
  position: relative;
  z-index: 2;
  display: grid;
  grid-template-columns: var(--rail-w) 1fr;
  grid-template-rows: var(--strip-h) 1fr;
  grid-template-areas:
    'rail strip'
    'rail stage';
  height: 100%;
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
  text-shadow: 0 0 14px var(--phosphor-glow);
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
  box-shadow: 0 0 10px var(--phosphor-glow);
}

.nav-idx { font-size: var(--t-micro); opacity: 0.85; font-weight: 700; }
.nav-title { color: inherit; font-size: var(--t-micro); font-weight: 700; }

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
.safe .lamp { background: var(--warn); box-shadow: 0 0 10px var(--warn-wash); }
.armed .lamp { background: var(--phosphor); box-shadow: 0 0 12px var(--phosphor-glow); }

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

.gauge { display: flex; flex-direction: column; gap: 1px; }
.g-val { font-size: var(--t-small); color: var(--ink); font-weight: 600; }

.spacer { flex: 1 1 auto; }

.fault {
  color: var(--short);
  max-width: 34ch;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 600;
}

.feed { display: flex; flex-direction: column; gap: 1px; text-align: right; }
.feed-state.ok { color: var(--long); font-weight: 700; }
.feed-state.stale { color: var(--short); font-weight: 700; }

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
