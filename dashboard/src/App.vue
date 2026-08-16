<script setup lang="ts">
import { computed, nextTick, provide, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ClerkLoaded, ClerkLoading, UserButton, useAuth, useClerk, useUser } from '@clerk/vue'
import { api, configureApiAuth, type StatusPayload, type Readiness, type MarketClock, type ComparePayload, type ScanDepth, type SectorFlowPayload } from '@/api'
import { isAllowedOperatorEmail } from '@/auth'
import { formatMarketCountdown, marketSessionClass as sessionClassOf, marketSessionLabel as sessionLabelOf } from '@/marketSession'
import { placeToolsMenuStyle, type ToolsMenuStyle } from '@/toolsMenu'
import { useResource } from '@/composables/useResource'
import { num, age, signedPct, tone, usd } from '@/format'
import AppIcon from '@/components/AppIcon.vue'
import SearchPalette from '@/components/SearchPalette.vue'
import TradeCentralMark from '@/components/TradeCentralMark.vue'

const route = useRoute()
const router = useRouter()
const { getToken, isLoaded, isSignedIn } = useAuth()
const clerk = useClerk()
const { user } = useUser()
const publicRoute = computed(() => route.meta.public === true)
const operatorEmail = computed(() => user.value?.primaryEmailAddress?.emailAddress ?? '')
const operatorAllowed = computed(() => isAllowedOperatorEmail(operatorEmail.value))
const signingOut = ref(false)

async function signOut(): Promise<void> {
  if (signingOut.value) return
  signingOut.value = true
  try {
    await clerk.value?.signOut()
    await router.replace({ name: 'landing' })
  } finally {
    signingOut.value = false
  }
}

configureApiAuth(async () => {
  if (!isLoaded.value || !isSignedIn.value || !operatorAllowed.value) return null
  return getToken.value()
})

/* The shell owns the two feeds every view needs, and hands them down. A single
   poller for status beats four views each opening their own. */
const authEnabled = () => isSignedIn.value === true && operatorAllowed.value
const lastStatusDepth = ref<ScanDepth | undefined>(undefined)
const status = useResource<StatusPayload>(
  () => api.status(lastStatusDepth.value),
  { intervalMs: 60_000, enabled: authEnabled },
)
watch(
  () => status.data.value?.scan_summary?.depth,
  (depth) => {
    if (depth === 'deep' || depth === 'quick') lastStatusDepth.value = depth
  },
)
const readiness = useResource<Readiness>(() => api.readiness(), { intervalMs: 120_000, enabled: authEnabled })
const marketClock = useResource<MarketClock>(() => api.marketClock(), { intervalMs: 30_000, enabled: authEnabled })
/** Benchmark tape for the strip — SPY, Nasdaq (QQQ), Dow (DIA), Oil/energy (XLE). */
const tapeMarks = useResource<ComparePayload>(
  () => api.compare(['SPY', 'QQQ', 'DIA', 'XLE'], '1m'),
  { intervalMs: 120_000, enabled: authEnabled },
)

/** Sector rotation re-runs on its own clock. Status polls must not rebuild
 *  PEAD/directional tables, but money-flow cannot sit on the warmup scan. */
const sectorForceNext = ref(false)
const sectorFlowRes = useResource<SectorFlowPayload>(
  () => {
    const force = sectorForceNext.value
    sectorForceNext.value = false
    return api.sectorFlow({ force })
  },
  { intervalMs: 180_000, enabled: authEnabled },
)

async function refreshSectorFlow(opts?: { force?: boolean; clear?: boolean }): Promise<void> {
  if (opts?.force) sectorForceNext.value = true
  await sectorFlowRes.refresh({ clear: opts?.clear })
}

watch(
  [() => sectorFlowRes.data.value, () => status.data.value],
  ([flow, board]) => {
    if (!flow || !board || board.sector_flow === flow) return
    status.data.value = { ...board, sector_flow: flow }
  },
)

watch(isSignedIn, (signedIn) => {
  if (signedIn && operatorAllowed.value) {
    void Promise.all([
      status.refresh(),
      readiness.refresh(),
      marketClock.refresh(),
      tapeMarks.refresh(),
      refreshSectorFlow({ force: true }),
    ])
  } else {
    status.clear()
    readiness.clear()
    marketClock.clear()
    tapeMarks.clear()
    sectorFlowRes.clear()
  }
})

watch(
  [isLoaded, isSignedIn, operatorAllowed, () => route.name, () => route.fullPath],
  () => {
    if (!isLoaded.value) return
    if (isSignedIn.value && !operatorAllowed.value && route.name !== 'auth') {
      void router.replace({ name: 'auth' })
      return
    }
    if (!isSignedIn.value && route.meta.public !== true) {
      void router.replace({
        name: 'auth',
        query: { redirect: route.fullPath },
      })
    }
  },
  { immediate: true },
)

provide('status', status)
provide('readiness', readiness)
provide('marketClock', marketClock)
provide('sectorFlow', {
  data: sectorFlowRes.data,
  error: sectorFlowRes.error,
  loading: sectorFlowRes.loading,
  fetchedAt: sectorFlowRes.fetchedAt,
  refresh: refreshSectorFlow,
  clear: sectorFlowRes.clear,
})

const primaryNav = [
  { name: 'desk', idx: '01', title: 'Desk', hint: 'Posture · queue · arena', icon: 'desk' },
  { name: 'plays', idx: '02', title: 'Plays', hint: 'Today\'s decision funnel', icon: 'radar' },
  { name: 'market', idx: '03', title: 'Market', hint: 'Symbol research', icon: 'market' },
  { name: 'options', idx: '04', title: 'Options', hint: 'One underlier', icon: 'options' },
  { name: 'flow', idx: '05', title: 'Flow', hint: 'Market-wide options tape', icon: 'flow' },
  { name: 'chain', idx: '06', title: 'Chain', hint: 'Value chain & growth', icon: 'chain' },
  { name: 'suggest', idx: '07', title: 'Setups', hint: 'Call/put + GEX sell', icon: 'suggest' },
  { name: 'research', idx: '08', title: 'Research', hint: 'Methods · gates · models', icon: 'research' },
] as const

const marketTools = [
  { name: 'sectors', idx: 'M1', title: 'Sectors', hint: 'Rotation and leadership', icon: 'sectors' },
  { name: 'sentiment', idx: 'M2', title: 'Pulse', hint: 'Structure and outliers', icon: 'pulse' },
  { name: 'momentum', idx: 'M3', title: 'Momentum', hint: 'Five pillars scan', icon: 'momentum' },
  { name: 'fintel', idx: 'M4', title: 'Fintel', hint: 'Short, borrow, owners', icon: 'fintel' },
  { name: 'insiders', idx: 'M5', title: 'Insiders', hint: 'Form 4 · Fintel tape', icon: 'insiders' },
  { name: 'calculator', idx: 'M6', title: 'Calculator', hint: 'Spot · strike · P/L', icon: 'calculator' },
] as const

const researchTools = [
  { name: 'gates', idx: 'R1', title: 'Gates', hint: 'Pre-registered verdicts', icon: 'gate' },
  { name: 'evolution', idx: 'R2', title: 'Evolution', hint: 'GA survivors lab', icon: 'evolution' },
  { name: 'adaptive', idx: 'R3', title: 'Live Blend', hint: 'Regime multi-stream', icon: 'adaptive' },
  { name: 'graph', idx: 'R4', title: 'Graph', hint: 'Knowledge graph', icon: 'graph' },
  { name: 'changepoints', idx: 'R5', title: 'Breaks', hint: 'Bayesian regime breaks', icon: 'changepoints' },
  { name: 'cloud', idx: 'R6', title: 'Cloud', hint: 'Vertex AI training', icon: 'cloud' },
] as const

const secondaryNav = [...marketTools, ...researchTools] as const

const moreOpen = ref(false)
const moreWrap = ref<HTMLDivElement | null>(null)
const moreButton = ref<HTMLButtonElement | null>(null)
const morePanel = ref<HTMLElement | null>(null)
const stage = ref<HTMLElement | null>(null)

const vol = computed(() => status.data.value?.latest_vol)

interface SectorRow {
  etf?: string
  name?: string
  flow_score?: number
}
const sectorFlow = computed(() => status.data.value?.sector_flow)
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
  if (name === 'plays') return enterCount.value > 0
  if (name === 'flow') {
    const top = topRotations.value.in[0]
    let bookHits = 0
    try {
      bookHits = Number(localStorage.getItem('edge.flow.alert-unread.v1') || 0)
    } catch {
      bookHits = 0
    }
    return volAlert.value || bookHits > 0 || Boolean(top && Math.abs(Number(top.flow_score ?? 0)) > 0.02)
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

const marketSessionLabel = computed(() =>
  sessionLabelOf(marketClock.data.value?.market_session, { error: Boolean(marketClock.error.value) }),
)

const marketSessionClass = computed(() => sessionClassOf(marketClock.data.value?.market_session))

const marketTransition = computed(() => {
  // Reading clock.value makes this countdown update on the shell's 1s timer.
  void clock.value
  const data = marketClock.data.value
  return formatMarketCountdown(data?.next_transition_utc, data?.next_transition, Date.now())
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

function onOutsidePointer(e: PointerEvent): void {
  if (!moreOpen.value || !(e.target instanceof Node)) return
  if (moreWrap.value?.contains(e.target) || morePanel.value?.contains(e.target)) return
  moreOpen.value = false
}

const morePanelStyle = ref<Partial<ToolsMenuStyle>>({})

function placeToolsMenu(): void {
  const rect = moreButton.value?.getBoundingClientRect()
  if (!rect) return
  morePanelStyle.value = placeToolsMenuStyle(rect, {
    width: window.innerWidth,
    height: window.innerHeight,
  })
}

async function openToolsMenu(edge: 'first' | 'last' = 'first'): Promise<void> {
  moreOpen.value = true
  await nextTick()
  placeToolsMenu()
  const items = Array.from(
    morePanel.value?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [],
  )
  items[edge === 'first' ? 0 : items.length - 1]?.focus()
}

watch(moreOpen, async (open) => {
  if (!open) return
  await nextTick()
  placeToolsMenu()
})

function onMoreMenuKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    e.preventDefault()
    moreOpen.value = false
    moreButton.value?.focus()
    return
  }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return
  const items = Array.from(
    morePanel.value?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [],
  )
  if (!items.length) return
  e.preventDefault()
  const current = items.indexOf(document.activeElement as HTMLElement)
  const next = e.key === 'Home'
    ? 0
    : e.key === 'End'
      ? items.length - 1
      : e.key === 'ArrowUp'
        ? (current <= 0 ? items.length - 1 : current - 1)
        : (current + 1) % items.length
  items[next]?.focus()
}

onMounted(() => {
  /* Default density stays compact; no user toggle — layout is fixed. */
  document.documentElement.dataset.density = 'compact'
  tick = window.setInterval(() => (clock.value = utcNow()), 1000)
  window.addEventListener('keydown', onKey)
  document.addEventListener('pointerdown', onOutsidePointer)
})
onUnmounted(() => {
  if (tick !== undefined) clearInterval(tick)
  window.removeEventListener('keydown', onKey)
  document.removeEventListener('pointerdown', onOutsidePointer)
})

watch(() => route.fullPath, async () => {
  moreOpen.value = false
  await nextTick()
  stage.value?.focus({ preventScroll: true })
})

function openSymbol(sym: string): void {
  paletteOpen.value = false
  const clean = sym.trim().toUpperCase().replace(/[^A-Z0-9.-]/g, '').slice(0, 10)
  if (!clean) return
  const currentName = String(route.name || '')
  /* Flow is market-wide; a symbol search belongs on Options for one underlier. */
  if (currentName === 'flow' || currentName === 'flowstate') {
    void router.push({ name: 'options', query: { symbol: clean } })
    return
  }
  if (currentName === 'suggest') {
    void router.push({ name: 'suggest', query: { symbol: clean } })
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
  <ClerkLoading>
    <div class="clerk-boot" role="status">
      <TradeCentralMark :size="40" />
      <strong class="clerk-boot-word">TradeCentral</strong>
      <span class="label">Loading operator session…</span>
    </div>
  </ClerkLoading>

  <ClerkLoaded>
    <div v-if="!publicRoute && (!isSignedIn || !operatorAllowed)" class="clerk-redirect" role="status">
      <span class="label">Opening operator access…</span>
    </div>

    <div v-else class="shell">
    <a class="skip-link" href="#main-content">Skip to workspace</a>
    <!-- ── left rail ────────────────────────────────────────────────────── -->
    <nav class="rail" aria-label="TradeCentral workspaces">
      <RouterLink to="/" class="mark" aria-label="TradeCentral overview">
        <TradeCentralMark :size="28" />
        <span class="mark-word" aria-hidden="true">
          <strong>Trade</strong>
          <strong>Central</strong>
        </span>
        <span class="mark-rule" aria-hidden="true" />
      </RouterLink>

      <ul class="nav">
        <li v-for="n in primaryNav" :key="n.name">
          <RouterLink
            :to="{ name: n.name }"
            class="nav-item"
            :class="{ on: route.name === n.name, alert: navAlert(n.name) }"
            :title="navAlert(n.name)
              ? `${n.title} [${n.idx}] · ${n.hint} · attention`
              : `${n.title} [${n.idx}] · ${n.hint}`"
          >
            <span class="nav-idx fig" aria-hidden="true">{{ n.idx }}</span>
            <AppIcon class="nav-icon" :name="n.icon" :size="18" />
            <span class="nav-title label">{{ n.title }}</span>
            <span v-if="navAlert(n.name)" class="nav-pulse" aria-hidden="true" />
          </RouterLink>
        </li>
      </ul>

      <div class="rail-foot">
      <!-- More: secondary views dropdown -->
      <div ref="moreWrap" class="more-wrap">
        <button
          ref="moreButton"
          type="button"
          class="more-btn nav-item"
          :class="{ on: secondaryActive || moreOpen }"
          :aria-expanded="moreOpen"
          aria-haspopup="menu"
          aria-controls="workspace-tools-menu"
          :title="moreOpen ? 'Close tools' : 'Open market and research tools'"
          @click="moreOpen = !moreOpen"
          @keydown.down.prevent="openToolsMenu('first')"
          @keydown.up.prevent="openToolsMenu('last')"
        >
          <span class="nav-idx fig" aria-hidden="true">TOOLS</span>
          <AppIcon class="nav-icon" name="more" :size="18" />
          <span class="nav-title label">Tools</span>
        </button>
        <Teleport to="body">
        <div
          v-if="moreOpen"
          id="workspace-tools-menu"
          ref="morePanel"
          class="more-panel"
          :style="morePanelStyle"
          role="menu"
          aria-label="Market and research tools"
          @keydown="onMoreMenuKey"
        >
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
            <AppIcon name="home" :size="16" />
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
        </Teleport>
      </div>

      <div class="clerk-user" :title="operatorEmail ? `Operator: ${operatorEmail} · Account and sign out` : 'Account and sign out'">
        <div class="operator-status" aria-hidden="true">
          <span class="operator-lamp" />
          <span class="operator-badge label">OP</span>
        </div>
        <div class="operator-avatar-frame">
          <UserButton after-sign-out-url="/" />
        </div>
        <span class="nav-title label">Account</span>
        <button
          type="button"
          class="account-signout label"
          :disabled="signingOut"
          :title="signingOut ? 'Signing out…' : 'Sign out of operator session'"
          aria-label="Sign out"
          @click="void signOut()"
        >
          <AppIcon name="signout" :size="10" class="signout-icon" />
          <span>{{ signingOut ? 'EXITING' : 'SIGN OUT' }}</span>
        </button>
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
        :class="[marketSessionClass, { early: marketClock.data.value?.is_early_close, mapped: Boolean(marketClock.data.value?.market_session) }]"
        :title="marketClockTitle"
        role="status"
        aria-live="polite"
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
  </ClerkLoaded>
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
  padding: var(--s3) 0 0;
  border-right: var(--hair) solid var(--rule);
  background: var(--void-lift);
  z-index: var(--z-rail);
  /* .rail spans all three grid rows as one item, so its automatic minimum
     size (min-content height) would otherwise force the shared 1fr row —
     and with it #app/.shell/the whole document — to grow past the viewport
     whenever the 13 nav items + logo + find button don't fit. min-height: 0
     opts out of that; the nav list scrolls so Account stays pinned. */
  min-height: 0;
  overflow: hidden;
  user-select: none;
}
.nav {
  list-style: none;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 2px;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 0 4px;
}
.rail-foot {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  margin-top: auto;
  padding: 0 4px 4px;
  overflow: visible;
}

.mark {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 2px 4px var(--s3);
  color: var(--ink);
  text-decoration: none;
  transition: color var(--dur-fast) var(--ease-out);
}
.mark:hover { color: var(--phosphor); text-decoration: none; }
.mark:hover .mark-rule { background: var(--phosphor); }

.mark-word {
  display: flex;
  flex-direction: column;
  align-items: center;
  font-family: var(--font-display);
  font-size: 8px;
  font-weight: 750;
  line-height: 0.95;
  letter-spacing: 0.055em;
  text-transform: uppercase;
}
.mark-word strong:last-child { color: var(--ink-dim); }
.mark:hover .mark-word strong:last-child { color: currentColor; }

.mark-rule {
  width: 22px;
  height: var(--hair);
  background: var(--rule-hi);
  transition: background var(--dur-fast) var(--ease-out);
}

/* ---- nav ------------------------------------------------------------------ */

.nav-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  min-height: 52px;
  padding: 6px 4px;
  color: var(--ink-dim);
  border-radius: var(--r-sm);
  text-decoration: none;
  transition: color var(--dur-fast) var(--ease-out),
              background var(--dur-fast) var(--ease-out),
              transform var(--dur-fast) var(--ease-out);
}
.nav-item:hover { color: var(--ink); background: var(--panel-hi); text-decoration: none; }

.nav-idx {
  font-family: var(--font-data);
  font-size: 8px;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--ink-ghost);
  opacity: 0.85;
  line-height: 1;
  transition: color var(--dur-fast) var(--ease-out);
}
.nav-item:hover .nav-idx { color: var(--ink-dim); }

.nav-item.on {
  color: var(--ink);
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  font-weight: 600;
}
.nav-item.on .nav-idx {
  color: var(--phosphor);
}

/* The active marker is a phosphor bar on the inner edge */
.nav-item.on::after {
  content: '';
  position: absolute;
  left: 0;
  top: 18%;
  bottom: 18%;
  width: 2px;
  border-radius: 1px;
  background: var(--phosphor);
}

.nav-item.alert {
  color: var(--warn);
}
.nav-item.alert.on { color: var(--phosphor); }
.nav-pulse {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warn);
  box-shadow: 0 0 6px rgba(217, 164, 65, 0.6);
  animation: pulse-lamp 2s ease-in-out infinite;
}

.nav-icon { color: currentColor; }
.nav-title {
  color: inherit;
  font-family: var(--font-ui);
  font-size: var(--t-micro);
  font-weight: 600;
  line-height: 1.1;
}

/* ---- more dropdown ------------------------------------------------------- */
.more-wrap {
  position: relative;
  margin-bottom: 4px;
}
.clerk-user {
  position: relative;
  width: 100%;
  min-height: 84px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  padding: 8px 4px 6px;
  border-top: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--void-lift);
}

.operator-status {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 2px;
}
.operator-lamp {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--phosphor);
  box-shadow: 0 0 4px var(--phosphor);
}
.operator-badge {
  color: var(--ink-ghost);
  font-family: var(--font-data);
  font-size: 7.5px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.operator-avatar-frame {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1px;
  border-radius: var(--r-xs);
}
.clerk-user :deep(.cl-avatarBox),
.clerk-user :deep(.cl-userButtonAvatarBox) {
  width: 26px !important;
  height: 26px !important;
  border-radius: var(--r-xs) !important;
  border: var(--hair) solid var(--rule-hi) !important;
  transition: border-color var(--dur-fast) var(--ease-out);
}
.clerk-user :deep(.cl-userButtonTrigger:hover .cl-avatarBox) {
  border-color: var(--phosphor) !important;
}

.account-signout {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  padding: 2px 5px;
  min-height: 18px;
  margin-top: 2px;
  color: var(--ink-ghost);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  background: var(--panel);
  font-family: var(--font-data);
  font-size: 7.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease-out),
              border-color var(--dur-fast) var(--ease-out),
              background var(--dur-fast) var(--ease-out);
}
.account-signout .signout-icon {
  color: inherit;
  opacity: 0.85;
}
.account-signout:hover:not(:disabled) {
  color: var(--short);
  border-color: color-mix(in srgb, var(--short) 60%, var(--rule));
  background: var(--short-wash);
}
.account-signout:disabled {
  opacity: 0.6;
  cursor: wait;
}

.clerk-boot,
.clerk-redirect {
  position: relative;
  z-index: 5;
  min-height: 100vh;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: var(--s4);
  color: var(--ink-dim);
  background: var(--void);
}
.clerk-boot-word { color: var(--ink); font: 600 var(--t-display) var(--font-display); }
.more-btn {
  width: 100%;
  border: none;
  cursor: pointer;
  background: transparent;
}
.more-panel {
  position: fixed;
  z-index: var(--z-overlay);
  background: var(--panel);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-lg);
  min-width: 220px;
  max-height: min(72vh, 540px);
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  display: flex;
  flex-direction: column;
  padding: 4px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.85), 0 0 0 1px rgba(255, 255, 255, 0.05);
}
.more-item {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  margin: 1px 0;
  border-radius: var(--r-sm);
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
  margin-bottom: 3px;
  border-radius: var(--r-sm);
  color: var(--ink-soft);
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
  text-align: left;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.more-search:hover { color: var(--phosphor); background: var(--phosphor-wash); border-color: var(--phosphor-dim); }
.more-item:hover { background: var(--panel-hi); color: var(--ink); }
.more-item.on { color: var(--phosphor); background: var(--phosphor-wash); font-weight: 600; }
.more-idx { font-family: var(--font-data); font-size: var(--t-micro); opacity: 0.85; font-weight: 600; min-width: 2.5ch; margin-left: auto; color: var(--ink-ghost); text-align: right; }
.more-title { font-family: var(--font-ui); font-size: var(--t-micro); font-weight: 600; }
.more-group {
  padding: var(--s2) var(--s3) var(--s1);
  color: var(--ink-ghost);
  font-family: var(--font-data);
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  border-top: var(--hair) solid var(--rule-faint);
  background: transparent;
  margin-top: 4px;
}

/* ---- strip --------------------------------------------------------------- */
.strip {
  grid-area: strip;
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: 0 var(--s4);
  border-bottom: var(--hair) solid var(--rule);
  background: rgba(13, 15, 20, 0.88);
  backdrop-filter: blur(12px);
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
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.05em;
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
.g-val { flex: 0 0 auto; color: var(--ink); font-size: var(--t-small); font-weight: 600; line-height: 1.15; white-space: nowrap; }
.g-chg { margin-left: auto; font-size: var(--t-micro); font-weight: 600; letter-spacing: 0.02em; white-space: nowrap; }
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
.rot-leg { display: flex; align-items: baseline; gap: 5px; min-width: 0; font-weight: 600; }
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
  font-family: var(--font-data);
  font-weight: 600;
  font-size: var(--t-micro);
  padding: 3px 8px;
  border-radius: var(--r-sm);
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
  min-width: 108px;
  padding-left: var(--s4);
  border-left: var(--hair) solid var(--rule);
}
.market-clock.mapped .market-next { color: var(--ink); }
.market-state { color: var(--ink-dim); font-family: var(--font-data); font-weight: 600; font-size: var(--t-micro); }
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
  min-height: 28px;
  padding: 2px 8px;
  border-radius: var(--r-sm);
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
}
.strip-search:hover { color: var(--ink); background: var(--panel-hi); border-color: var(--rule-hi); }
.strip-search .label { color: inherit; }
.strip-search kbd {
  padding: 1px 4px;
  color: var(--ink-ghost);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  background: var(--panel);
  font-family: var(--font-data);
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
  .nav { flex: 1 1 auto; flex-direction: row; gap: 0; min-width: 0; overflow-x: auto; padding: 0; }
  .nav li { display: flex; flex: 1 0 52px; }
  .nav-idx { display: none; }
  .nav-item {
    flex: 1 1 auto;
    min-height: 64px;
    height: 64px;
    justify-content: center;
    padding: 6px 3px;
    border-radius: 0;
  }
  .nav-item.on::after { top: auto; right: 18%; bottom: 0; left: 18%; width: auto; height: 2px; }
  .nav-pulse { top: 8px; right: calc(50% - 15px); }
  .rail-foot { flex-direction: row; margin-top: 0; padding: 0; }
  .more-wrap { flex: 0 0 52px; width: 52px; margin-top: 0; margin-bottom: 0; }
  .clerk-user {
    display: flex;
    flex: 0 0 52px;
    width: 52px;
    margin-top: 0;
    min-height: 64px;
    height: 64px;
    padding: 6px 3px;
    border-top: 0;
    border-radius: 0;
    border-left: var(--hair) solid var(--rule-faint);
  }
  .operator-status { display: none; }
  .account-signout { display: none; }
  .more-btn { min-height: 64px; height: 64px; border-radius: 0; }
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
}
</style>
