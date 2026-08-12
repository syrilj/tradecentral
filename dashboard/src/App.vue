<script setup lang="ts">
import { computed, nextTick, provide, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type StatusPayload, type Readiness, type MarketClock, type ComparePayload } from '@/api'
import { useResource } from '@/composables/useResource'
import { num, age, signedPct, tone, usd } from '@/format'
import AppIcon from '@/components/AppIcon.vue'
import SearchPalette from '@/components/SearchPalette.vue'

const route = useRoute()
const router = useRouter()

/* The shell owns the two feeds every view needs, and hands them down. A single
   poller for status beats four views each opening their own. */
const status = useResource<StatusPayload>(() => api.status(), { intervalMs: 60_000 })
const readiness = useResource<Readiness>(() => api.readiness(), { intervalMs: 120_000 })
const marketClock = useResource<MarketClock>(() => api.marketClock(), { intervalMs: 30_000 })
/** Benchmark tape for the strip — SPY, Nasdaq (QQQ), Dow (DIA), Oil/energy (XLE). */
const tapeMarks = useResource<ComparePayload>(
  () => api.compare(['SPY', 'QQQ', 'DIA', 'XLE'], '1m'),
  { intervalMs: 120_000 },
)

provide('status', status)
provide('readiness', readiness)

const primaryNav = [
  { name: 'desk', idx: '01', title: 'Desk', hint: 'Posture · queue · arena', icon: 'desk' },
  { name: 'market', idx: '02', title: 'Market', hint: 'Symbol research', icon: 'market' },
  { name: 'options', idx: '03', title: 'Options', hint: 'One underlier', icon: 'options' },
  { name: 'flow', idx: '04', title: 'Flow', hint: 'Market-wide options tape', icon: 'flow' },
  { name: 'research', idx: '05', title: 'Research', hint: 'Methods · gates · models', icon: 'research' },
] as const

const marketTools = [
  { name: 'sectors', idx: 'M1', title: 'Sectors', hint: 'Rotation and leadership', icon: 'market' },
  { name: 'sentiment', idx: 'M2', title: 'Pulse', hint: 'Structure and outliers', icon: 'market' },
  { name: 'momentum', idx: 'M3', title: 'Momentum', hint: 'Five pillars scan', icon: 'market' },
  { name: 'fintel', idx: 'M4', title: 'Fintel', hint: 'Short, borrow, owners', icon: 'market' },
] as const

const researchTools = [
  { name: 'gates', idx: 'R1', title: 'Gates', hint: 'Pre-registered verdicts', icon: 'research' },
  { name: 'evolution', idx: 'R2', title: 'Evolution', hint: 'GA survivors lab', icon: 'research' },
  { name: 'adaptive', idx: 'R3', title: 'Live Blend', hint: 'Regime multi-stream', icon: 'research' },
  { name: 'graph', idx: 'R4', title: 'Graph', hint: 'Knowledge graph', icon: 'research' },
  { name: 'changepoints', idx: 'R5', title: 'Breaks', hint: 'Bayesian regime breaks', icon: 'research' },
  { name: 'cloud', idx: 'R6', title: 'Cloud', hint: 'Vertex AI training', icon: 'research' },
] as const

const secondaryNav = [...marketTools, ...researchTools] as const

const moreOpen = ref(false)
const stage = ref<HTMLElement | null>(null)

const vol = computed(() => status.data.value?.latest_vol)

interface SectorRow {
  etf?: string
  name?: string
  flow_score?: number
}
interface SectorFlowPayload {
  asof?: string | null
  asof_bar?: string | null
  source?: string | null
  sectors_ranked?: SectorRow[]
}
const sectorFlow = computed(() =>
  status.data.value?.sector_flow as SectorFlowPayload | undefined,
)
const sectorsRanked = computed((): SectorRow[] => {
  const raw = sectorFlow.value?.sectors_ranked
  return Array.isArray(raw) ? raw : []
})
const topRotations = computed(() => {
  const ranked = [...sectorsRanked.value].filter((s) => s.etf)
  if (!ranked.length) return { in: [] as SectorRow[], out: [] as SectorRow[] }
  const sorted = ranked.sort((a, b) => Number(b.flow_score ?? 0) - Number(a.flow_score ?? 0))
  return {
    in: sorted.filter((s) => Number(s.flow_score ?? 0) > 0).slice(0, 2),
    out: sorted.filter((s) => Number(s.flow_score ?? 0) < 0).slice(-2).reverse(),
  }
})

/** Strip tape marks: last observed price + change between observed closes. */
const TAPE = [
  { sym: 'SPY', label: 'S&P 500' },
  { sym: 'QQQ', label: 'Nasdaq' },
  { sym: 'DIA', label: 'Dow' },
  { sym: 'XLE', label: 'Energy' },
] as const

function observedAgeDays(value: string | null | undefined): number | null {
  if (!value) return null
  const stamp = Date.parse(value.length <= 10 ? `${value}T00:00:00Z` : value)
  if (!Number.isFinite(stamp)) return null
  return Math.max(0, Math.floor((Date.now() - stamp) / 86_400_000))
}

function compactBarDate(value: string | null | undefined): string {
  if (!value) return 'DATE —'
  const stamp = new Date(value.length <= 10 ? `${value}T00:00:00Z` : value)
  if (Number.isNaN(stamp.getTime())) return 'DATE —'
  const day = String(stamp.getUTCDate()).padStart(2, '0')
  const month = stamp.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' }).toUpperCase()
  return `${day} ${month}`
}

function sparklinePath(points: { cum: number }[] | undefined): string {
  const values = (points ?? [])
    .map((point) => Number(point.cum))
    .filter(Number.isFinite)
    .slice(-20)
  if (values.length < 2) return ''
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const span = Math.max(hi - lo, Math.abs(hi) * 0.0005, 0.0001)
  return values.map((value, index) => {
    const x = (index / (values.length - 1)) * 48
    const y = 14 - ((value - lo) / span) * 12
    return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

const tapeRows = computed(() => {
  const stats = tapeMarks.data.value?.stats ?? {}
  const series = tapeMarks.data.value?.series ?? {}
  const err = tapeMarks.error.value
  return TAPE.map((t) => {
    const s = stats[t.sym]
    const price = typeof s?.last_price === 'number' ? s.last_price : null
    const chg1d = typeof s?.chg_1d_pct === 'number' ? s.chg_1d_pct : null
    const chgWin = typeof s?.chg_window_pct === 'number' ? s.chg_window_pct : null
    const asof = typeof s?.asof === 'string' ? s.asof : null
    const ageDays = typeof s?.age_days === 'number' ? s.age_days : observedAgeDays(asof)
    const quality = price == null
      ? 'missing'
      : s?.quality === 'stale' || ageDays == null || ageDays > 3
        ? 'stale'
        : 'current'
    return {
      ...t,
      price,
      chg: chg1d ?? chgWin,
      changeBasis: chg1d != null ? '1D' : '1M',
      asof,
      asofLabel: compactBarDate(asof),
      ageDays,
      quality,
      source: s?.source ?? null,
      spark: sparklinePath(series[t.sym]),
      loading: tapeMarks.loading.value && price == null,
      fault: Boolean(err) && price == null,
    }
  })
})

const volAsOf = computed(() => vol.value?.date ?? null)
const volAgeDays = computed(() => observedAgeDays(volAsOf.value))
const volQuality = computed(() => {
  if (!vol.value || vol.value.VIX == null) return 'missing'
  return volAgeDays.value == null || volAgeDays.value > 3 ? 'stale' : 'current'
})

const rotationAsOf = computed(() => sectorFlow.value?.asof_bar ?? null)
const rotationAgeDays = computed(() => observedAgeDays(rotationAsOf.value))
const rotationQuality = computed(() => {
  if (!sectorsRanked.value.length || !rotationAsOf.value) return 'missing'
  return rotationAgeDays.value == null || rotationAgeDays.value > 3 ? 'stale' : 'current'
})
const rotationFreshness = computed(() => {
  if (!rotationAsOf.value) return 'DATE UNKNOWN'
  const suffix = rotationQuality.value === 'stale' ? ' · STALE' : ''
  return `BAR ${compactBarDate(rotationAsOf.value)}${suffix}`
})

const volAlert = computed(() => {
  const v = vol.value
  if (!v) return false
  return (v.VIX ?? 0) >= 25
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
  }
  if (marketClock.data.value?.warning) return marketClock.data.value.warning
  return null
})
function navAlert(name: string): boolean {
  if (name === 'desk') return enterCount.value > 0
  if (name === 'flow') {
    const top = topRotations.value.in[0]
    return volAlert.value || Boolean(top && Math.abs(Number(top.flow_score ?? 0)) > 0.02)
  }
  if (name === 'options') return volAlert.value
  return false
}

const secondaryActive = computed(() =>
  secondaryNav.some((n) => route.name === n.name)
)
function gaugeTone(): string {
  const v = vol.value?.VIX ?? 0
  if (v >= 25) return 'hot'
  if (v >= 18) return 'warm'
  return 'ok'
}
function chgTone(v: number | null | undefined): string {
  return tone(v)
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

function onKey(e: KeyboardEvent): void {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    paletteOpen.value = true
  }
  if (e.key === 'Escape') {
    paletteOpen.value = false
    moreOpen.value = false
  }
  if (e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey && !isTypingTarget(e.target)) {
    e.preventDefault()
    paletteOpen.value = true
  }
}

onMounted(() => {
  /* Default density stays compact; no user toggle — layout is fixed. */
  document.documentElement.dataset.density = 'compact'
  tick = window.setInterval(() => (clock.value = utcNow()), 1000)
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => {
  if (tick !== undefined) clearInterval(tick)
  window.removeEventListener('keydown', onKey)
})

watch(() => route.fullPath, async () => {
  moreOpen.value = false
  await nextTick()
  stage.value?.focus({ preventScroll: true })
})

function openSymbol(sym: string): void {
  paletteOpen.value = false
  const clean = sym.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, '').slice(0, 10)
  if (!clean) return
  const currentName = String(route.name || '')
  /* Flow is market-wide; a symbol search belongs on Options for one underlier. */
  if (currentName === 'flow' || currentName === 'flowstate') {
    void router.push({ name: 'options', query: { symbol: clean } })
    return
  }
  /* Always land on Market for symbol research when not already on a symbol workspace. */
  const symbolViews = new Set(['market', 'options', 'changepoints', 'sentiment', 'momentum', 'fintel'])
  const targetRouteName = symbolViews.has(currentName) ? currentName : 'market'
  void router.push({ name: targetRouteName, query: { symbol: clean } })
}

function openMark(sym: string): void {
  void router.push({ name: 'market', query: { symbol: sym } })
}

function openRotation(): void {
  void router.push({ name: 'sectors' })
}

function openVol(): void {
  void router.push({ name: 'sentiment' })
}
</script>

<template>
  <div class="shell">
    <a class="skip-link" href="#main-content">Skip to workspace</a>
    <!-- ── left rail ────────────────────────────────────────────────────── -->
    <nav class="rail" aria-label="Primary">
      <RouterLink to="/" class="mark" aria-label="Overview home">
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
              ? `${n.title} · ${n.hint} · attention`
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
            <span class="more-title label">Search symbol</span>
            <span class="more-idx fig">⌘K</span>
          </button>
          <RouterLink
            to="/"
            class="more-item"
            :class="{ on: route.name === 'landing' }"
            title="Instrument overview and readiness"
            role="menuitem"
            @click="moreOpen = false"
          >
            <AppIcon name="desk" :size="16" />
            <span class="more-title label">Overview</span>
            <span class="more-idx fig">HOME</span>
          </RouterLink>
          <div class="more-group label">Market</div>
          <RouterLink
            v-for="n in marketTools"
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
          <div class="more-group label">Research</div>
          <RouterLink
            v-for="n in researchTools"
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

    </nav>

    <!-- ── instrument strip ─────────────────────────────────────────────── -->
    <header class="strip">
      <div class="gauges" aria-label="Benchmark tape and sector rotation">
        <button
          type="button"
          class="gauge gauge-btn gauge-vol"
          :class="[gaugeTone(), `quality-${volQuality}`]"
          :title="`VIX ${num(vol?.VIX, 2)} · observed ${volAsOf || 'date unavailable'} · open volatility context`"
          @click="openVol"
        >
          <span class="g-head">
            <span class="label g-symbol">VIX</span>
            <span class="label g-date" :class="volQuality">{{ compactBarDate(volAsOf) }}</span>
          </span>
          <span class="g-body">
            <span class="fig g-val">{{ num(vol?.VIX, 2) }}</span>
            <span class="label g-context" :class="volQuality">{{ volQuality === 'stale' ? 'STALE' : 'VOL' }}</span>
          </span>
        </button>
        <button
          v-for="m in tapeRows"
          :key="m.sym"
          type="button"
          class="gauge gauge-btn gauge-mark"
          :class="[
            `quality-${m.quality}`,
            `mark-${m.sym.toLowerCase()}`,
            { loading: m.loading, fault: m.fault, 'primary-mark': m.sym === 'SPY' },
          ]"
          :title="`${m.label} (${m.sym}) · observed ${m.asof || 'date unavailable'} · ${m.source || 'source unavailable'} · open in Market`"
          @click="openMark(m.sym)"
        >
          <span class="g-head">
            <span class="label g-symbol">{{ m.sym }}</span>
            <span class="label g-name">{{ m.label }}</span>
            <span class="label g-date" :class="m.quality">
              {{ m.quality === 'stale' ? `${m.asofLabel} · STALE` : m.asofLabel }}
            </span>
          </span>
          <span class="g-body">
            <span class="fig g-val">
              <template v-if="m.price != null">{{ usd(m.price) }}</template>
              <template v-else-if="m.loading">SYNC</template>
              <template v-else>NO DATA</template>
            </span>
            <svg v-if="m.spark" class="g-spark" :class="chgTone(m.chg)" viewBox="0 0 48 16" preserveAspectRatio="none" aria-hidden="true">
              <path :d="m.spark" />
            </svg>
            <span class="fig g-chg" :class="chgTone(m.chg)">{{ signedPct(m.chg, 2) }}</span>
            <span class="label g-basis">{{ m.changeBasis }}</span>
          </span>
        </button>
        <button
          type="button"
          class="gauge gauge-btn gauge-rot"
          :class="`quality-${rotationQuality}`"
          :title="topRotations.in.length || topRotations.out.length
            ? `Top sector rotation · observed ${rotationAsOf || 'date unavailable'} · in ${topRotations.in.map((s) => s.etf).join(' ')} · out ${topRotations.out.map((s) => s.etf).join(' ')} · open rotation workspace`
            : 'Sector rotation unavailable until status scan finishes'"
          @click="openRotation"
        >
          <span class="g-head">
            <span class="label g-symbol">ROTATION</span>
            <span class="label g-date" :class="rotationQuality">{{ rotationFreshness }}</span>
          </span>
          <span v-if="topRotations.in.length || topRotations.out.length" class="rot-pair">
            <span v-if="topRotations.in[0]" class="rot-leg rot-in">
              <span class="fig">{{ topRotations.in[0].etf }}</span>
              <small class="fig">{{ signedPct(Number(topRotations.in[0].flow_score || 0) * 100, 1) }}</small>
            </span>
            <span class="rot-arrow label">LEADS / LAGS</span>
            <span v-if="topRotations.out[0]" class="rot-leg rot-out">
              <span class="fig">{{ topRotations.out[0].etf }}</span>
              <small class="fig">{{ signedPct(Number(topRotations.out[0].flow_score || 0) * 100, 1) }}</small>
            </span>
          </span>
          <span v-else class="fig g-val">NO ROTATION DATA</span>
        </button>
      </div>

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
        type="button"
        class="strip-search"
        title="Search symbols and workspaces (⌘K)"
        aria-label="Search symbols and workspaces"
        @click="paletteOpen = true"
      >
        <AppIcon name="search" :size="15" />
        <span class="label">SEARCH</span>
        <kbd class="fig">⌘K</kbd>
      </button>

      <span
        class="mobile-market-state label"
        :class="marketSessionClass"
        :title="marketClockTitle"
      >
        {{ marketSessionLabel }}
      </span>

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
.more-group {
  padding: var(--s2) var(--s3) var(--s1);
  color: var(--ink-ghost);
  font-size: var(--t-micro);
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  border-top: var(--hair) solid var(--rule);
  background: var(--panel);
}

/* ---- strip --------------------------------------------------------------- */
.strip {
  grid-area: strip;
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: 0 var(--s4);
  border-bottom: var(--hair) solid var(--rule);
  background:
    linear-gradient(90deg, color-mix(in srgb, var(--phosphor) 4%, transparent), transparent 24%),
    var(--void-lift);
  z-index: var(--z-strip);
  min-width: 0;
}

.gauges {
  display: flex;
  align-items: stretch;
  gap: 0;
  min-width: 0;
  flex: 1 1 auto;
  align-self: stretch;
  overflow: hidden;
}

.gauge {
  position: relative;
  display: grid;
  grid-template-rows: auto auto;
  justify-content: center;
  gap: 4px;
  min-width: 0;
  flex: 1 1 145px;
  padding: 0 12px;
  border-right: var(--hair) solid var(--rule);
}
.gauge::after {
  content: '';
  position: absolute;
  right: 12px;
  bottom: 0;
  left: 12px;
  height: 1px;
  background: var(--rule-hi);
  opacity: 0.45;
}
.gauge.quality-current::after { background: var(--phosphor-dim); opacity: 0.8; }
.gauge.quality-stale::after { background: var(--warn); opacity: 0.9; }
.gauge.quality-missing::after,
.gauge.fault::after { background: var(--short); opacity: 0.75; }
.gauge-vol { flex: 0 0 118px; }
.gauge-rot { flex: 1.4 1 225px; }
.gauge:last-child { border-right: none; }
.gauge-btn {
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  color: inherit;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.gauge-btn:hover { background: var(--panel-hi); }
.gauge-btn:hover::after { height: 2px; background: var(--phosphor); opacity: 1; }
.gauge-btn:hover .g-val { color: var(--phosphor); }
.gauge-btn.loading .g-val { color: var(--ink-dim); }
.gauge-btn.fault .g-val { color: var(--warn); }
.g-head,
.g-body {
  display: flex;
  align-items: center;
  min-width: 0;
}
.g-head { gap: 6px; }
.g-body { gap: 7px; }
.gauge .label,
.strip-search .label {
  color: var(--ink-dim);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.g-symbol { color: var(--ink) !important; }
.g-name { overflow: hidden; color: var(--ink-ghost) !important; font-size: 8px !important; text-overflow: ellipsis; }
.g-date {
  overflow: hidden;
  margin-left: auto;
  color: var(--ink-ghost) !important;
  font-size: 8px !important;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.g-date.stale { color: var(--warn) !important; }
.g-date.missing { color: var(--short) !important; }
.g-val { flex: 0 0 auto; color: var(--ink); font-size: var(--t-small); font-weight: 700; line-height: 1.15; white-space: nowrap; }
.g-chg { margin-left: auto; font-size: var(--t-micro); font-weight: 700; letter-spacing: 0.02em; white-space: nowrap; }
.g-chg.pos { color: var(--long); }
.g-chg.neg { color: var(--short); }
.g-chg.flat { color: var(--ink-dim); }
.g-basis { color: var(--ink-ghost) !important; font-size: 8px !important; }
.g-context { margin-left: auto; color: var(--ink-ghost) !important; font-size: 8px !important; }
.g-context.stale { color: var(--warn) !important; }
.g-spark {
  width: 48px;
  height: 16px;
  overflow: visible;
  color: var(--ink-dim);
}
.g-spark path { fill: none; stroke: currentColor; stroke-width: 1.35; vector-effect: non-scaling-stroke; }
.g-spark.pos { color: var(--long); }
.g-spark.neg { color: var(--short); }
.rot-pair {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}
.rot-leg { display: flex; align-items: baseline; gap: 5px; min-width: 0; font-weight: 700; }
.rot-leg small { font-size: 8px; }
.rot-in { color: var(--long); }
.rot-out { color: var(--short); }
.rot-arrow { overflow: hidden; color: var(--ink-ghost) !important; font-size: 8px !important; text-overflow: ellipsis; white-space: nowrap; }
.gauge.warm .g-val { color: var(--warn); }
.gauge.hot .g-val { color: var(--short); }

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
.mobile-market-state { display: none; }

.strip-search {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 9px;
  color: var(--ink-dim);
  border-left: var(--hair) solid var(--rule);
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.strip-search:hover { color: var(--phosphor); background: var(--phosphor-wash); }
.strip-search .label { color: inherit; }
.strip-search kbd {
  padding: 1px 4px;
  color: var(--ink-ghost);
  border: var(--hair) solid var(--rule);
  font-size: 8px;
}

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

@media (max-width: 1180px) {
  .gauge-rot { display: none; }
  .strip-search { min-width: 34px; padding: 0 8px; }
  .strip-search .label,
  .strip-search kbd { display: none; }
}
@media (max-width: 1080px) {
  .mark-dia,
  .mark-xle { display: none; }
  .strip-warn { display: none; }
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
  .mark { display: none; }
  .nav li:nth-child(5) { display: none; }
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
  .more-wrap { flex: 0 0 52px; width: 52px; margin-top: 0; }
  .more-btn { min-height: 64px; height: 64px; }
  .more-panel { top: auto; right: 0; bottom: calc(100% + 2px); left: auto; }
  .foot { display: none; }
  .gauges { display: flex; flex: 1 1 auto; }
  .gauge-vol,
  .gauge-rot,
  .gauge-mark:not(.primary-mark) { display: none; }
  .gauge-mark.primary-mark { display: grid; flex: 1 1 auto; max-width: 178px; padding: 0 9px; border-right: 0; }
  .gauge-mark.primary-mark .g-date,
  .gauge-mark.primary-mark .g-name { display: none; }
  .gauge-mark.primary-mark .g-basis { display: none; }
  .gauge-mark.primary-mark .g-body { gap: 5px; }
  .gauge-mark.primary-mark .g-spark { width: 40px; }
  .stage { padding: var(--s3); }
  .nav-title { font-size: 8px; }
  .clock { display: none; }
  .strip-warn { display: none; }
  .strip { gap: var(--s2); padding: 0 var(--s3); overflow: hidden; }
  .market-clock { display: none; }
  .strip-search { min-width: 34px; padding: 0 8px; border-left: 0; }
  .strip-search .label,
  .strip-search kbd { display: none; }
  .mobile-market-state {
    display: block;
    margin-left: auto;
    color: var(--phosphor);
  }
  .mobile-market-state.closed,
  .mobile-market-state.unknown { color: var(--warn); }
  .more-panel { left: calc(100% + 1px); }
}
</style>
