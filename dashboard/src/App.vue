<script setup lang="ts">
import {
  computed,
  defineComponent,
  nextTick,
  provide,
  ref,
  onMounted,
  onUnmounted,
  watch,
} from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ClerkLoaded, ClerkLoading, UserButton, useAuth, useClerk, useUser } from '@clerk/vue'
import {
  api,
  configureApiAuth,
  type StatusPayload,
  type Readiness,
  type MarketClock,
  type ComparePayload,
  type ScanDepth,
  type SectorFlowPayload,
  type SentimentPayload,
} from '@/api'
import { isAllowedOperatorEmail, isLocalAuthMode } from '@/auth'
import {
  formatMarketCountdown,
  marketSessionClass as sessionClassOf,
  marketSessionLabel as sessionLabelOf,
} from '@/marketSession'
import { placeToolsMenuStyle, type ToolsMenuStyle } from '@/toolsMenu'
import { useResource } from '@/composables/useResource'
import { num, age, signedPct, tone, usd } from '@/format'
import { usePreferences } from '@/composables/usePreferences'
import AppIcon from '@/components/AppIcon.vue'
import ProfileDrawer from '@/components/ProfileDrawer.vue'
import SearchPalette from '@/components/SearchPalette.vue'
import TradeCentralMark from '@/components/TradeCentralMark.vue'

const route = useRoute()
const router = useRouter()
/* EDGE_AUTH_MODE=local runs a zero-credential workstation session: no Clerk
   plugin is installed (its composables throw outside it), so every Clerk
   touchpoint below is guarded by localMode and resolves to a local operator
   identity instead. One shell markup serves both modes: the Clerk wrappers are
   swapped for a passthrough component here, so the template keeps its
   <ClerkLoading>/<ClerkLoaded> structure verbatim. */
const localMode = isLocalAuthMode()
const Passthrough = defineComponent({
  name: 'AuthModePassthrough',
  setup(_props, { slots }) {
    return () => (slots.default ? slots.default() : null)
  },
})
/* Local mode has no async provider to await: the boot gate passes content
   straight through, and the load gate renders nothing (a permanent
   "loading operator session" splash would otherwise sit over the desk). */
const HiddenGate = defineComponent({
  name: 'AuthModeHiddenGate',
  setup() {
    return () => null
  },
})
const BootGate = localMode ? Passthrough : ClerkLoaded
const LoadGate = localMode ? HiddenGate : ClerkLoading
const { getToken, isLoaded, isSignedIn } = localMode
  ? { getToken: computed(() => async () => null), isLoaded: ref(true), isSignedIn: ref(true) }
  : useAuth()
const clerk = localMode ? ref(null) : useClerk()
const { user } = localMode ? { user: ref<null>(null) } : useUser()
const { preferences } = usePreferences()
const profileDrawerOpen = ref(false)
const publicRoute = computed(() => route.meta.public === true)
const operatorEmail = computed(() =>
  localMode
    ? String(import.meta.env.VITE_EDGE_ALLOWED_EMAILS ?? '')
        .split(',')[0]
        ?.trim() || 'local-operator'
    : (user.value?.primaryEmailAddress?.emailAddress ?? ''),
)
const operatorAllowed = computed(() => isAllowedOperatorEmail(operatorEmail.value))
const signingOut = ref(false)

const SIDEBAR_STORAGE_KEY = 'edge.sidebar.collapsed.v1'
const sidebarCollapsed = ref(false)

function toggleSidebar(): void {
  sidebarCollapsed.value = !sidebarCollapsed.value
  try {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, sidebarCollapsed.value ? 'true' : 'false')
  } catch {
    /* ignore storage failure */
  }
}

async function signOut(): Promise<void> {
  if (signingOut.value) return
  signingOut.value = true
  try {
    if (!localMode) await clerk.value?.signOut()
    await router.replace({ name: 'landing' })
  } finally {
    signingOut.value = false
  }
}

configureApiAuth(async () => {
  if (localMode) return null // loopback API needs no bearer in local mode
  if (!isLoaded.value || !isSignedIn.value || !operatorAllowed.value) return null
  return getToken.value()
})

/* The shell owns the two feeds every view needs, and hands them down. A single
   poller for status beats four views each opening their own. */
const authEnabled = () => isSignedIn.value === true && operatorAllowed.value
const lastStatusDepth = ref<ScanDepth | undefined>(undefined)
const status = useResource<StatusPayload>(() => api.status(lastStatusDepth.value), {
  intervalMs: 60_000,
  enabled: authEnabled,
})
watch(
  () => status.data.value?.scan_summary?.depth,
  (depth) => {
    if (depth === 'deep' || depth === 'quick') lastStatusDepth.value = depth
  },
)
const readiness = useResource<Readiness>(() => api.readiness(), {
  intervalMs: 120_000,
  enabled: authEnabled,
})
const marketClock = useResource<MarketClock>(() => api.marketClock(), {
  intervalMs: 30_000,
  enabled: authEnabled,
})
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
/** Desk structure composite — shown as a fear/greed gauge. Not CNN. */
const sentimentRes = useResource<SentimentPayload>(() => api.sentiment(), {
  intervalMs: 300_000,
  enabled: authEnabled,
})

async function refreshSectorFlow(opts?: { force?: boolean; clear?: boolean }): Promise<void> {
  if (opts?.force) sectorForceNext.value = true
  await sectorFlowRes.refresh({ clear: opts?.clear })
}

watch([() => sectorFlowRes.data.value, () => status.data.value], ([flow, board]) => {
  if (!flow || !board || board.sector_flow === flow) return
  status.data.value = { ...board, sector_flow: flow }
})

watch(isSignedIn, (signedIn) => {
  if (signedIn && operatorAllowed.value) {
    void Promise.all([
      status.refresh(),
      readiness.refresh(),
      marketClock.refresh(),
      tapeMarks.refresh(),
      refreshSectorFlow({ force: true }),
      sentimentRes.refresh(),
    ])
  } else {
    status.clear()
    readiness.clear()
    marketClock.clear()
    tapeMarks.clear()
    sectorFlowRes.clear()
    sentimentRes.clear()
  }
})

watch(
  [isLoaded, isSignedIn, operatorAllowed, () => route.name, () => route.fullPath],
  () => {
    if (localMode) return // the local operator session never redirects to /auth
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

/** Five operator destinations. Everything else lives in Tools. */
const primaryNav = [
  {
    name: 'flow',
    title: 'Flow',
    hint: 'Market-wide options tape',
    icon: 'flow',
    tab: true,
  },
  {
    name: 'options',
    title: 'Options',
    hint: 'One underlier',
    icon: 'options',
    tab: true,
  },
  {
    name: 'desk',
    title: 'Desk',
    hint: 'Posture · queue · arena',
    icon: 'desk',
    tab: true,
  },
  {
    name: 'chain',
    title: 'Chain',
    hint: 'Value chain & growth',
    icon: 'chain',
    tab: true,
  },
  {
    name: 'market',
    title: 'Market',
    hint: 'Symbol research',
    icon: 'market',
    tab: true,
  },
] as const

const deskTools = [
  {
    name: 'plays',
    idx: 'D1',
    title: 'Plays',
    hint: "Today's decision funnel",
    icon: 'radar',
  },
  { name: 'drift', idx: 'D2', title: 'Drift', hint: 'Buying vs selling pressure', icon: 'drift' },
  {
    name: 'absorption',
    idx: 'D3',
    title: 'Absorption',
    hint: 'Heavy flow, held level',
    icon: 'absorption',
  },
  {
    name: 'livestack',
    idx: 'LS',
    title: 'Live Stack',
    hint: 'All lenses, one tape',
    icon: 'stack',
  },
  { name: 'suggest', idx: 'D5', title: 'Setups', hint: 'Call/put + GEX sell', icon: 'suggest' },
] as const

const marketTools = [
  {
    name: 'sectors',
    idx: 'M1',
    title: 'Sectors',
    hint: 'Rotation and leadership',
    icon: 'sectors',
  },
  { name: 'sentiment', idx: 'M2', title: 'Pulse', hint: 'Structure and outliers', icon: 'pulse' },
  { name: 'momentum', idx: 'M3', title: 'Momentum', hint: 'Five pillars scan', icon: 'momentum' },
  { name: 'fintel', idx: 'M4', title: 'Fintel', hint: 'Short, borrow, owners', icon: 'fintel' },
  {
    name: 'insiders',
    idx: 'M5',
    title: 'Insiders',
    hint: 'Form 4 · Fintel tape',
    icon: 'insiders',
  },
  {
    name: 'calculator',
    idx: 'M6',
    title: 'Calculator',
    hint: 'Spot · strike · P/L',
    icon: 'calculator',
  },
] as const

const researchTools = [
  {
    name: 'research',
    idx: 'R1',
    title: 'Research',
    hint: 'IC decay · quantile spread',
    icon: 'research',
  },
  { name: 'gates', idx: 'R2', title: 'Gates', hint: 'Pre-registered verdicts', icon: 'gate' },
  { name: 'evolution', idx: 'R3', title: 'Evolution', hint: 'GA survivors lab', icon: 'evolution' },
  {
    name: 'adaptive',
    idx: 'R4',
    title: 'Live Blend',
    hint: 'Regime multi-stream',
    icon: 'adaptive',
  },
  { name: 'graph', idx: 'R5', title: 'Graph', hint: 'Knowledge graph', icon: 'graph' },
  {
    name: 'changepoints',
    idx: 'R6',
    title: 'Breaks',
    hint: 'Bayesian regime breaks',
    icon: 'changepoints',
  },
  { name: 'cloud', idx: 'R7', title: 'Cloud', hint: 'Vertex AI training', icon: 'cloud' },
  {
    name: 'kalman',
    idx: 'R8',
    title: 'Kalman',
    hint: 'Constant-velocity trend',
    icon: 'kalman',
  },
] as const

const overflowNav = [...deskTools, ...marketTools, ...researchTools] as const

function isTabDest(item: { name: string; tab?: boolean }): boolean {
  return item.tab === true
}

function openSearchFromTools(): void {
  moreOpen.value = false
  paletteOpen.value = true
}

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
    out: sorted
      .filter((s) => Number(s.flow_score ?? 0) < 0)
      .slice(-2)
      .reverse(),
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
  return values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * 48
      const y = 14 - ((value - lo) / span) * 12
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
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
    const quality =
      price == null
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

type FearGreedBand = 'extreme-fear' | 'fear' | 'neutral' | 'greed' | 'extreme-greed' | 'missing'

const fearGreed = computed(() => {
  const payload = sentimentRes.data.value
  const composite = payload?.composite
  const score = composite?.score
  const asof = payload?.generated_at ?? null
  const rawQuality = composite?.quality
  const quality =
    rawQuality === 'ok'
      ? 'current'
      : rawQuality === 'stale' || rawQuality === 'degraded'
        ? 'stale'
        : sentimentRes.loading.value && !payload
          ? 'missing'
          : 'missing'
  if (score == null || !Number.isFinite(score)) {
    return {
      value: null as number | null,
      label: sentimentRes.loading.value && !payload ? 'SYNC' : 'NO DATA',
      band: 'missing' as FearGreedBand,
      quality,
      asofLabel: compactBarDate(asof),
      structure: '',
      title: sentimentRes.error.value
        ? `Fear/greed unavailable · ${sentimentRes.error.value}`
        : 'Desk structure composite unavailable · open Pulse',
    }
  }
  const greed = Math.round((1 - Math.max(0, Math.min(1, score))) * 100)
  const band: FearGreedBand =
    greed <= 20
      ? 'extreme-fear'
      : greed <= 40
        ? 'fear'
        : greed <= 60
          ? 'neutral'
          : greed <= 80
            ? 'greed'
            : 'extreme-greed'
  const label = {
    'extreme-fear': 'EXTREME FEAR',
    fear: 'FEAR',
    neutral: 'NEUTRAL',
    greed: 'GREED',
    'extreme-greed': 'EXTREME GREED',
    missing: 'NO DATA',
  }[band]
  const structure = (composite?.label || 'MIXED').replace(/_/g, ' ')
  return {
    value: greed,
    label,
    band,
    quality,
    asofLabel: compactBarDate(asof),
    structure,
    title: `Desk fear/greed ${greed} · ${label} · structure ${structure} (vol + COT + FINRA short + options P/C). Not CNN Fear & Greed. Open Pulse.`,
  }
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
    return (
      volAlert.value || bookHits > 0 || Boolean(top && Math.abs(Number(top.flow_score ?? 0)) > 0.02)
    )
  }
  if (name === 'options') return volAlert.value
  return false
}

const overflowActiveItem = computed(
  () => overflowNav.find((n) => route.name === n.name) ?? null,
)
const secondaryActive = computed(() => overflowActiveItem.value != null)
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
  sessionLabelOf(marketClock.data.value?.market_session, {
    error: Boolean(marketClock.error.value),
  }),
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
  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    (target instanceof HTMLElement && target.isContentEditable)
  )
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
  const next =
    e.key === 'Home'
      ? 0
      : e.key === 'End'
        ? items.length - 1
        : e.key === 'ArrowUp'
          ? current <= 0
            ? items.length - 1
            : current - 1
          : (current + 1) % items.length
  items[next]?.focus()
}

onMounted(() => {
  /* Dynamic density initialization handled by usePreferences */
  document.documentElement.dataset.density = preferences.value.density
  try {
    const savedSidebar = localStorage.getItem(SIDEBAR_STORAGE_KEY)
    if (savedSidebar === 'true') {
      sidebarCollapsed.value = true
    }
  } catch {
    /* ignore */
  }
  tick = window.setInterval(() => (clock.value = utcNow()), 1000)
  window.addEventListener('keydown', onKey)
  document.addEventListener('pointerdown', onOutsidePointer)
})
onUnmounted(() => {
  if (tick !== undefined) clearInterval(tick)
  window.removeEventListener('keydown', onKey)
  document.removeEventListener('pointerdown', onOutsidePointer)
})

watch(
  () => route.fullPath,
  async () => {
    moreOpen.value = false
    await nextTick()
    stage.value?.focus({ preventScroll: true })
  },
)

function openSymbol(sym: string): void {
  paletteOpen.value = false
  const clean = sym
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
    .slice(0, 10)
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
  const symbolViews = new Set([
    'market',
    'options',
    'drift',
    'changepoints',
    'sentiment',
    'momentum',
    'fintel',
  ])
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

function openFearGreed(): void {
  void router.push({ name: 'sentiment' })
}
</script>

<template>
  <LoadGate>
    <div class="clerk-boot" role="status">
      <TradeCentralMark :size="40" />
      <strong class="clerk-boot-word">TradeCentral</strong>
      <span class="label">Loading operator session…</span>
    </div>
  </LoadGate>

  <BootGate>
    <div
      v-if="!publicRoute && (!isSignedIn || !operatorAllowed)"
      class="clerk-redirect"
      role="status"
    >
      <span class="label">Opening operator access…</span>
    </div>

    <div
      v-else
      class="shell"
      :class="{ 'rail-collapsed': sidebarCollapsed, 'rail-expanded': !sidebarCollapsed }"
      :style="{ '--rail-w': sidebarCollapsed ? '72px' : '236px' }"
    >
      <a class="skip-link" href="#main-content">Skip to workspace</a>

      <!-- ── left rail ────────────────────────────────────────────────────── -->
      <nav
        class="rail"
        :class="{ 'is-collapsed': sidebarCollapsed, 'is-expanded': !sidebarCollapsed }"
        aria-label="TradeCentral workspaces"
      >
        <div class="rail-header">
          <RouterLink to="/" class="mark" aria-label="TradeCentral overview">
            <TradeCentralMark :size="22" />
            <span class="mark-word" aria-hidden="true">
              <strong>Trade</strong>
              <strong>Central</strong>
            </span>
          </RouterLink>

          <button
            type="button"
            class="rail-toggle-btn"
            :title="sidebarCollapsed ? 'Expand navigation sidebar' : 'Collapse navigation sidebar'"
            :aria-label="
              sidebarCollapsed ? 'Expand navigation sidebar' : 'Collapse navigation sidebar'
            "
            @click="toggleSidebar"
          >
            <AppIcon :name="sidebarCollapsed ? 'arrow-right' : 'arrow-left'" :size="13" />
          </button>
        </div>

        <ul class="nav">
          <li v-for="n in primaryNav" :key="n.name" :class="{ 'tab-dest-li': isTabDest(n) }">
            <RouterLink
              :to="{ name: n.name }"
              class="nav-item"
              :class="{
                on: route.name === n.name,
                alert: navAlert(n.name),
                'tab-dest': isTabDest(n),
              }"
              :title="
                navAlert(n.name) ? `${n.title} · ${n.hint} · attention` : `${n.title} · ${n.hint}`
              "
            >
              <AppIcon class="nav-icon" :name="n.icon" :size="16" />
              <div class="nav-label-wrap">
                <span class="nav-title label">{{ n.title }}</span>
                <span class="nav-hint">{{ n.hint }}</span>
              </div>
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
              :title="moreOpen ? 'Close tools' : 'Open remaining workspaces'"
              @click="moreOpen = !moreOpen"
              @keydown.down.prevent="openToolsMenu('first')"
              @keydown.up.prevent="openToolsMenu('last')"
            >
              <AppIcon class="nav-icon" name="more" :size="16" />
              <div class="nav-label-wrap">
                <span class="nav-title label">Tools</span>
                <span class="nav-hint">{{
                  overflowActiveItem ? overflowActiveItem.title : 'More workspaces'
                }}</span>
              </div>
            </button>
            <Teleport to="body">
              <div
                v-if="moreOpen"
                id="workspace-tools-menu"
                ref="morePanel"
                class="more-panel"
                :style="morePanelStyle"
                role="menu"
                aria-label="More workspaces"
                @keydown="onMoreMenuKey"
              >
                <button
                  class="more-search"
                  type="button"
                  role="menuitem"
                  @click="openSearchFromTools"
                >
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
                <div class="more-group label">Desk</div>
                <RouterLink
                  v-for="n in deskTools"
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

          <div
            class="clerk-user"
            :title="
              operatorEmail
                ? `Operator: ${operatorEmail} · Account and settings`
                : 'Account and settings'
            "
            @click="profileDrawerOpen = true"
          >
            <div class="operator-avatar-frame">
              <UserButton v-if="!localMode" after-sign-out-url="/" />
              <span
                v-else
                class="local-operator-avatar fig"
                title="Local operator session"
                aria-hidden="true"
                >OP</span
              >
            </div>
            <div class="operator-meta">
              <span class="nav-title label">Account</span>
              <span class="operator-mail">{{ operatorEmail || 'Local operator' }}</span>
            </div>
            <button
              type="button"
              class="account-signout label"
              :disabled="signingOut"
              :title="signingOut ? 'Signing out…' : 'Sign out of operator session'"
              aria-label="Sign out"
              @click.stop="void signOut()"
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
              <span class="label g-context" :class="volQuality">{{
                volQuality === 'stale' ? 'STALE' : 'VOL'
              }}</span>
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
              <svg
                v-if="m.spark"
                class="g-spark"
                :class="chgTone(m.chg)"
                viewBox="0 0 48 16"
                preserveAspectRatio="none"
                aria-hidden="true"
              >
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
            :title="
              topRotations.in.length || topRotations.out.length
                ? `Top sector rotation · observed ${rotationAsOf || 'date unavailable'} · in ${topRotations.in.map((s) => s.etf).join(' ')} · out ${topRotations.out.map((s) => s.etf).join(' ')} · open rotation workspace`
                : 'Sector rotation unavailable until status scan finishes'
            "
            @click="openRotation"
          >
            <span class="g-head">
              <span class="label g-symbol">ROTATION</span>
              <span class="label g-date" :class="rotationQuality">{{ rotationFreshness }}</span>
            </span>
            <span v-if="topRotations.in.length || topRotations.out.length" class="rot-board">
              <span class="rot-col rot-in">
                <span class="rot-col-h label">IN</span>
                <span class="rot-legs">
                  <span v-for="s in topRotations.in" :key="`in-${s.etf}`" class="rot-leg">
                    <span class="fig">{{ s.etf }}</span>
                    <small class="fig">{{ signedPct(Number(s.flow_score || 0) * 100, 1) }}</small>
                  </span>
                </span>
              </span>
              <span class="rot-col rot-out">
                <span class="rot-col-h label">OUT</span>
                <span class="rot-legs">
                  <span v-for="s in topRotations.out" :key="`out-${s.etf}`" class="rot-leg">
                    <span class="fig">{{ s.etf }}</span>
                    <small class="fig">{{ signedPct(Number(s.flow_score || 0) * 100, 1) }}</small>
                  </span>
                </span>
              </span>
            </span>
            <span v-else class="fig g-val">NO ROTATION DATA</span>
          </button>
          <button
            type="button"
            class="gauge gauge-btn gauge-fg"
            :class="[`quality-${fearGreed.quality}`, `band-${fearGreed.band}`]"
            :title="fearGreed.title"
            @click="openFearGreed"
          >
            <span class="g-head">
              <span class="label g-symbol">FEAR / GREED</span>
              <span class="label g-date" :class="fearGreed.quality">{{ fearGreed.asofLabel }}</span>
            </span>
            <span class="fg-body">
              <span class="fig g-val" :class="fearGreed.band">{{
                fearGreed.value == null ? fearGreed.label : fearGreed.value
              }}</span>
              <span
                class="fg-track"
                role="meter"
                :aria-valuemin="0"
                :aria-valuemax="100"
                :aria-valuenow="fearGreed.value ?? undefined"
                :aria-valuetext="fearGreed.label"
                :aria-label="fearGreed.title"
              >
                <span class="fg-spectrum" aria-hidden="true"><i /><i /><i /><i /><i /></span>
                <i class="fg-ticks" aria-hidden="true" />
                <span
                  v-if="fearGreed.value != null"
                  class="fg-thumb"
                  :class="fearGreed.band"
                  :style="{ left: `${fearGreed.value}%` }"
                />
              </span>
              <span class="label g-context" :class="fearGreed.band">{{ fearGreed.label }}</span>
            </span>
          </button>
        </div>

        <div v-if="stripWarning" class="strip-warn" :title="stripWarning">
          <AppIcon name="alert" :size="14" />
          <span class="label">{{ stripWarning }}</span>
        </div>

        <div
          class="market-clock"
          :class="[
            marketSessionClass,
            {
              early: marketClock.data.value?.is_early_close,
              mapped: Boolean(marketClock.data.value?.market_session),
            },
          ]"
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

        <button
          type="button"
          class="strip-profile-btn"
          :title="
            operatorEmail
              ? `Operator: ${operatorEmail} · Workstation preferences`
              : 'Operator profile & settings'
          "
          aria-label="Operator profile and workstation settings"
          :aria-expanded="profileDrawerOpen"
          @click="profileDrawerOpen = true"
        >
          <div class="strip-profile-avatar">
            <img v-if="user?.imageUrl" :src="user.imageUrl" alt="" class="strip-avatar-img" />
            <span v-else class="strip-avatar-initials fig">{{
              (operatorEmail || 'OP').slice(0, 2).toUpperCase()
            }}</span>
            <span class="strip-operator-lamp" aria-hidden="true" />
          </div>
          <span class="strip-profile-badge label">OP</span>
        </button>
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

      <ProfileDrawer
        v-model="profileDrawerOpen"
        :user-email="operatorEmail"
        :user-name="localMode ? 'Local operator' : (user?.fullName ?? user?.firstName ?? '')"
        :user-avatar="user?.imageUrl ?? ''"
        :telemetry="{
          apiStatus: status.error.value ? 'fault' : status.loading.value ? 'sync' : 'ok',
          activeRoute: String(route.name || route.path),
          feedFreshness: status.fetchedAt.value ? age(status.fetchedAt.value) : 'live',
        }"
        @sign-out="void signOut()"
      />
    </div>
  </BootGate>
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
  /* Defense in depth: grid item min-height / overflow protection */
  overflow: hidden;
  transition: grid-template-columns var(--dur) var(--ease-out);
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
.skip-link:focus {
  transform: none;
}

/* ---- rail ----------------------------------------------------------------
   Functional-layer chrome: Liquid Glass over the canvas. Translucent fill +
   saturate/blur so content visually passes beneath; monochromatic ink;
   exactly one accent reserved for the active destination. */
.rail {
  grid-area: rail;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  padding: 4px 0 0;
  border-right: var(--hair) solid var(--glass-border);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0) 120px),
    var(--glass-base);
  backdrop-filter: var(--chrome-optics-lg);
  -webkit-backdrop-filter: var(--chrome-optics-lg);
  box-shadow: inset -1px 0 0 rgba(255, 255, 255, 0.03);
  z-index: var(--z-rail);
  min-height: 0;
  overflow: hidden;
  user-select: none;
  transition: width var(--dur) var(--ease-out);
}

@media (prefers-reduced-transparency: reduce) {
  .rail {
    background: var(--void-lift);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

.rail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  padding: 2px 6px;
  min-height: 36px;
  min-width: 0;
}
.rail.is-collapsed .rail-header {
  flex-direction: column;
  gap: 2px;
  padding: 2px 4px;
}

.rail-toggle-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  min-width: 28px;
  min-height: 28px;
  padding: 0;
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-xs);
  background: rgba(255, 255, 255, 0.02);
  color: var(--ink-dim);
  cursor: pointer;
  flex: 0 0 auto;
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}
.rail-toggle-btn::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 44px;
  height: 44px;
  transform: translate(-50%, -50%);
}
.rail-toggle-btn:hover {
  background: var(--panel-hi);
  border-color: var(--glass-border-hi);
  color: var(--ink);
}

.nav {
  list-style: none;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 1px;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 0 6px;
}
.rail.is-collapsed .nav {
  padding: 0 4px;
}

.rail-foot {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  margin-top: auto;
  padding: 0 6px 6px;
  overflow: visible;
  border-top: var(--hair) solid var(--rule-faint);
}
.rail.is-collapsed .rail-foot {
  padding: 0 4px 4px;
}

.mark {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  padding: 2px 2px;
  color: var(--ink);
  text-decoration: none;
  transition: color var(--dur-fast) var(--ease-out);
  overflow: hidden;
}
.rail.is-collapsed .mark {
  justify-content: center;
  padding: 2px 0;
}
.mark:hover {
  color: var(--phosphor);
  text-decoration: none;
}

.mark-word {
  display: flex;
  flex-direction: column;
  font-family: var(--font-display);
  font-size: 9px;
  font-weight: 750;
  line-height: 0.95;
  letter-spacing: 0.055em;
  text-transform: uppercase;
  white-space: nowrap;
}
.rail.is-collapsed .mark-word {
  display: none;
}
.mark-word strong:last-child {
  color: var(--ink-dim);
}
.mark:hover .mark-word strong:last-child {
  color: currentColor;
}

/* ---- nav ------------------------------------------------------------------ */

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 6px 8px;
  color: var(--ink-dim);
  border: var(--hair) solid transparent;
  border-radius: var(--r-capsule);
  text-decoration: none;
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}
.rail.is-collapsed .nav-item {
  flex-direction: column;
  justify-content: center;
  min-height: 44px;
  padding: 4px 2px;
  gap: 2px;
}
.nav-item:hover {
  color: var(--ink);
  background: var(--panel-hi);
  border-color: var(--glass-border);
  text-decoration: none;
}

.nav-item.on {
  color: var(--ink);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.07), rgba(255, 255, 255, 0.02));
  border: var(--hair) solid var(--glass-border);
  box-shadow:
    var(--glass-specular-subtle),
    0 1px 4px rgba(0, 0, 0, 0.35);
  font-weight: 600;
}
.nav-item.on .nav-icon {
  color: var(--phosphor);
}

/* The active marker is a phosphor capsule edge on the leading side */
.nav-item.on::after {
  content: '';
  position: absolute;
  left: -1px;
  top: 22%;
  bottom: 22%;
  width: 3px;
  border-radius: var(--r-capsule);
  background: var(--phosphor);
}

.nav-label-wrap {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
}
.rail.is-collapsed .nav-label-wrap {
  align-items: center;
}
.rail.is-collapsed .nav-label-wrap .nav-hint {
  display: none;
}

.nav-hint {
  font-family: var(--font-data);
  font-size: 8px;
  color: var(--ink-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.1;
}

.nav-item.alert {
  color: var(--warn);
}
.nav-item.alert.on {
  color: var(--phosphor);
}
.nav-pulse {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warn);
  animation: pulse-lamp var(--dur-pulse) ease-in-out infinite;
}

.nav-icon {
  color: currentColor;
  flex: 0 0 auto;
}
.nav-title {
  color: inherit;
  font-family: var(--font-ui);
  font-size: var(--t-micro);
  font-weight: 600;
  line-height: 1.15;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ---- more dropdown ------------------------------------------------------- */
.more-wrap {
  position: relative;
  margin-bottom: 4px;
  margin-top: 4px;
}
.clerk-user {
  position: relative;
  width: 100%;
  min-height: 44px;
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-top: var(--hair) solid var(--rule-faint);
  border-radius: var(--r-xs);
  cursor: pointer;
}
.rail.is-collapsed .clerk-user {
  flex-direction: column;
  justify-content: center;
  padding: 6px 2px;
  min-height: 44px;
  gap: 4px;
}

.operator-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1 1 auto;
  gap: 1px;
}
.rail.is-collapsed .operator-meta {
  display: none;
}
.rail.is-collapsed .account-signout span {
  display: none;
}
.rail.is-collapsed .account-signout {
  margin-left: 0;
  padding: 2px 4px;
}
.operator-mail {
  color: var(--ink-ghost);
  font-family: var(--font-data);
  font-size: 8px;
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.operator-avatar-frame {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  padding: 0;
  border-radius: var(--r-xs);
}
.local-operator-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  color: var(--ink);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  background: var(--panel-hi);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
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
  padding: 2px 6px;
  min-height: 26px;
  margin-top: 0;
  margin-left: auto;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  background: var(--panel);
  font-family: var(--font-data);
  font-size: 7.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
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
.clerk-boot-word {
  color: var(--ink);
  font: 600 var(--t-display) var(--font-display);
}
.more-btn {
  width: 100%;
  border: none;
  cursor: pointer;
  background: transparent;
}
.more-panel {
  position: fixed;
  z-index: var(--z-overlay);
  background: var(--glass-overlay);
  backdrop-filter: var(--chrome-optics-xl);
  -webkit-backdrop-filter: var(--chrome-optics-xl);
  border: var(--hair) solid var(--glass-border-hi);
  border-radius: var(--r-xl);
  min-width: 220px;
  max-height: min(72vh, 540px);
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  display: flex;
  flex-direction: column;
  padding: 4px;
  box-shadow: var(--glass-shadow-lg), var(--glass-specular);
}
@media (prefers-reduced-transparency: reduce) {
  .more-panel {
    background: var(--panel);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
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
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
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
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}
.more-search:hover {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border-color: var(--phosphor-dim);
}
.more-item:hover {
  background: var(--panel-hi);
  color: var(--ink);
}
.more-item.on {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  font-weight: 600;
}
.more-idx {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  opacity: 0.85;
  font-weight: 600;
  min-width: 2.5ch;
  margin-left: auto;
  color: var(--ink-dim);
  text-align: right;
}
.more-title {
  font-family: var(--font-ui);
  font-size: var(--t-micro);
  font-weight: 600;
}
.more-group {
  padding: var(--s2) var(--s3) var(--s1);
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: 8.5px;
  font-weight: 750;
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
  border-bottom: var(--hair) solid var(--glass-border);
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur-md);
  -webkit-backdrop-filter: var(--glass-blur-md);
  box-shadow: var(--glass-specular-subtle), var(--glass-shadow-sm);
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
  grid-template-rows: auto 1fr;
  justify-content: stretch;
  justify-items: stretch;
  align-content: stretch;
  gap: 3px;
  min-width: 0;
  flex: 1 1 132px;
  padding: 7px 12px;
  border-right: var(--hair) solid var(--glass-border);
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
.gauge.quality-current::after {
  background: var(--phosphor-dim);
  opacity: 0.8;
}
.gauge.quality-stale::after {
  background: var(--warn);
  opacity: 0.9;
}
.gauge.quality-missing::after,
.gauge.fault::after {
  background: var(--short);
  opacity: 0.75;
}
.gauge-vol {
  flex: 0 0 104px;
}
.gauge-mark {
  min-width: 118px;
}
.gauge-rot {
  flex: 1.6 1 240px;
  min-width: 196px;
}
.gauge-fg {
  flex: 1.2 1 200px;
  min-width: 176px;
}
.gauge:last-child {
  border-right: none;
}
.gauge-btn {
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  color: inherit;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}
.gauge-btn:hover {
  background: var(--glass-surface-hi);
}
.gauge-btn:hover::after {
  height: 2px;
  background: var(--phosphor);
  opacity: 1;
}
.gauge-btn:hover .g-val {
  color: var(--phosphor);
}
.gauge-btn.loading .g-val {
  color: var(--ink-dim);
}
.gauge-btn.fault .g-val {
  color: var(--warn);
}
.g-head,
.g-body {
  display: flex;
  align-items: center;
  min-width: 0;
}
.g-head {
  gap: 6px;
}
.g-body {
  gap: 7px;
  align-self: end;
}
.gauge .label,
.strip-search .label {
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.g-symbol {
  flex: 0 0 auto;
  color: var(--ink) !important;
  white-space: nowrap;
}
/* Name, date and spark absorb every pixel of shrink so the symbol, price and
   change never collapse into unreadable slivers. */
.g-name {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  color: var(--ink-dim) !important;
  font-size: 8px !important;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.g-date {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  margin-left: auto;
  color: var(--ink-dim) !important;
  font-size: 8px !important;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.g-date.stale {
  color: var(--warn) !important;
}
.g-date.missing {
  color: var(--short) !important;
}
.g-val {
  flex: 0 0 auto;
  color: var(--ink);
  font-size: var(--t-small);
  font-weight: 600;
  line-height: 1.15;
  white-space: nowrap;
}
.g-chg {
  flex: 0 0 auto;
  margin-left: auto;
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
}
.g-chg.pos {
  color: var(--long);
}
.g-chg.neg {
  color: var(--short);
}
.g-chg.flat {
  color: var(--ink-dim);
}
.g-basis {
  flex: 0 0 auto;
  color: var(--ink-dim) !important;
  font-size: 8px !important;
  white-space: nowrap;
}
.g-context {
  flex: 0 0 auto;
  margin-left: auto;
  white-space: nowrap;
  color: var(--ink-dim) !important;
  font-size: 8px !important;
}
.g-context.stale {
  color: var(--warn) !important;
}
.g-spark {
  flex: 0 1 48px;
  width: 48px;
  min-width: 0;
  height: 16px;
  overflow: visible;
  color: var(--ink-dim);
}
.g-spark path {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.35;
  vector-effect: non-scaling-stroke;
}
.g-spark.pos {
  color: var(--long);
}
.g-spark.neg {
  color: var(--short);
}
.rot-board {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 8px 12px;
  min-width: 0;
  align-self: end;
  width: 100%;
}
.rot-col {
  display: grid;
  grid-template-rows: auto auto;
  gap: 2px;
  min-width: 0;
}
.rot-col-h {
  color: var(--ink-dim) !important;
  font-size: 8px !important;
  letter-spacing: 0.08em;
}
.rot-legs {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
}
.rot-leg {
  display: flex;
  align-items: baseline;
  gap: 4px;
  min-width: 0;
  font-weight: 600;
  white-space: nowrap;
}
.rot-leg small {
  font-size: 8px;
}
.rot-in {
  color: var(--long);
}
.rot-out {
  color: var(--short);
}
.fg-body {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  min-width: 0;
  align-self: end;
  width: 100%;
}
.fg-track {
  position: relative;
  height: 7px;
  min-width: 0;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
}
.fg-spectrum {
  display: flex;
  height: 100%;
  gap: 0;
}
.fg-spectrum i {
  flex: 1 1 0;
  display: block;
  height: 100%;
}
.fg-spectrum i:nth-child(1) {
  background: var(--short);
}
.fg-spectrum i:nth-child(2) {
  background: color-mix(in srgb, var(--short) 55%, var(--warn));
}
.fg-spectrum i:nth-child(3) {
  background: var(--ink-faint);
}
.fg-spectrum i:nth-child(4) {
  background: color-mix(in srgb, var(--long) 55%, var(--warn));
}
.fg-spectrum i:nth-child(5) {
  background: var(--long);
}
.fg-ticks {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(var(--void-lift), var(--void-lift)) 20% 0 / 1px 100% no-repeat,
    linear-gradient(var(--void-lift), var(--void-lift)) 40% 0 / 1px 100% no-repeat,
    linear-gradient(var(--void-lift), var(--void-lift)) 60% 0 / 1px 100% no-repeat,
    linear-gradient(var(--void-lift), var(--void-lift)) 80% 0 / 1px 100% no-repeat;
  pointer-events: none;
}
.fg-thumb {
  position: absolute;
  top: 50%;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--ink);
  border: 2px solid var(--void-lift);
  transform: translate(-50%, -50%);
  pointer-events: none;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.28);
}
.fg-thumb.extreme-fear,
.fg-thumb.fear {
  background: var(--short);
}
.fg-thumb.greed,
.fg-thumb.extreme-greed {
  background: var(--long);
}
.g-val.extreme-fear,
.g-val.fear,
.g-context.extreme-fear,
.g-context.fear {
  color: var(--short) !important;
}
.g-val.greed,
.g-val.extreme-greed,
.g-context.greed,
.g-context.extreme-greed {
  color: var(--long) !important;
}
.g-val.neutral,
.g-context.neutral {
  color: var(--ink-dim) !important;
}
.g-val.missing {
  color: var(--ink-dim) !important;
}
.gauge.warm .g-val {
  color: var(--warn);
}
.gauge.hot .g-val {
  color: var(--short);
}

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
  border-left: var(--hair) solid var(--glass-border);
}
.market-clock.mapped .market-next {
  color: var(--ink);
}
.market-state {
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-weight: 600;
  font-size: var(--t-micro);
}
.market-next {
  color: var(--ink);
  font-size: var(--t-small);
  font-weight: 600;
}
.market-clock.regular .market-state {
  color: var(--phosphor);
}
.market-clock.premarket .market-state,
.market-clock.after_hours .market-state {
  color: var(--ink-soft);
}
.market-clock.closed .market-state,
.market-clock.early .market-state,
.market-clock.unknown .market-state {
  color: var(--warn);
}
.mobile-market-state {
  display: none;
}

.strip-search {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 44px;
  padding: 2px 12px;
  border-radius: var(--r-capsule);
  color: var(--ink-dim);
  border: var(--hair) solid var(--glass-border);
  background: var(--glass-surface);
  backdrop-filter: var(--chrome-optics-sm);
  -webkit-backdrop-filter: var(--chrome-optics-sm);
  box-shadow: var(--glass-specular-subtle);
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out);
}
.strip-search:hover {
  color: var(--ink);
  background: var(--panel-hi);
  border-color: var(--glass-border-hi);
  box-shadow: var(--glass-specular);
}
.strip-search .label {
  color: inherit;
}
.strip-search kbd {
  padding: 1px 4px;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  background: var(--panel);
  font-family: var(--font-data);
  font-size: 8px;
}

.clock {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
}
.clock-val {
  font-size: var(--t-small);
  color: var(--ink);
  font-weight: 600;
  letter-spacing: 0.04em;
}

.strip-profile-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 2px 10px 2px 4px;
  border-radius: var(--r-capsule);
  border: var(--hair) solid var(--glass-border);
  background: var(--glass-surface);
  backdrop-filter: var(--chrome-optics-sm);
  -webkit-backdrop-filter: var(--chrome-optics-sm);
  box-shadow: var(--glass-specular-subtle);
  color: var(--ink-soft);
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out);
}
.strip-profile-btn:hover {
  background: var(--panel-hi);
  border-color: var(--glass-border-hi);
  box-shadow: var(--glass-specular);
  color: var(--ink);
}
.strip-profile-avatar {
  position: relative;
  width: 22px;
  height: 22px;
  border-radius: var(--r-xs);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-hi);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: visible;
}
.strip-avatar-img {
  width: 100%;
  height: 100%;
  border-radius: var(--r-xs);
  object-fit: cover;
}
.strip-avatar-initials {
  font-family: var(--font-data);
  font-size: 8.5px;
  font-weight: 700;
  color: var(--phosphor);
}
.strip-operator-lamp {
  position: absolute;
  bottom: -2px;
  right: -2px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--phosphor);
  border: 1px solid var(--void);
}
.strip-profile-badge {
  font-size: 8px;
  font-weight: 700;
  color: var(--ink-dim);
  letter-spacing: 0.06em;
}
.strip-profile-btn:hover .strip-profile-badge {
  color: var(--phosphor);
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
  border-top: var(--hair) solid var(--glass-border);
  background: var(--void-lift);
  backdrop-filter: var(--glass-blur-md);
  -webkit-backdrop-filter: var(--glass-blur-md);
  z-index: var(--z-strip);
}

.foot-label {
  color: var(--ink-dim);
}
.foot-state {
  font-weight: 700;
}
.foot-state.ok {
  color: var(--long);
}
.foot-state.stale {
  color: var(--short);
}

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

/* The strip sheds tape detail, then whole gauges, as width runs out — a gauge
   is dropped rather than squeezed below the width its figures need to read. */
@media (max-width: 1900px) {
  .g-name,
  .g-spark,
  .g-basis {
    display: none;
  }
}
@media (max-width: 1560px) {
  .mark-xle {
    display: none;
  }
}
@media (max-width: 1460px) {
  .mark-dia {
    display: none;
  }
}
@media (max-width: 1320px) {
  .gauge-rot {
    display: none;
  }
  .rot-leg:nth-child(n + 2) {
    display: none;
  }
}
@media (max-width: 1180px) {
  .mark-qqq {
    display: none;
  }
  .strip-search {
    min-width: 34px;
    padding: 0 8px;
  }
  .strip-search .label,
  .strip-search kbd {
    display: none;
  }
}
@media (max-width: 1080px) {
  .mark-dia,
  .mark-xle {
    display: none;
  }
  .strip-warn {
    display: none;
  }
}

@media (max-width: 780px) {
  .shell {
    grid-template-columns: minmax(0, 1fr) !important;
    grid-template-rows: 52px minmax(0, 1fr) calc(64px + env(safe-area-inset-bottom, 0px));
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
    padding-bottom: env(safe-area-inset-bottom, 0px);
    border-top: var(--hair) solid var(--rule-hi);
    border-right: 0;
    overflow-x: auto;
    overflow-y: hidden;
    width: auto !important;
    min-height: calc(64px + env(safe-area-inset-bottom, 0px));
  }
  .rail-header {
    display: none;
  }
  .mark {
    display: none;
  }
  .nav {
    flex: 1 1 auto;
    flex-direction: row;
    gap: 0;
    min-width: 0;
    overflow-x: auto;
    padding: 0;
  }
  .nav li {
    display: none;
    flex: 1 1 0;
    min-width: 0;
  }
  .nav li.tab-dest-li {
    display: flex;
  }
  .nav-hint {
    display: none !important;
  }
  .nav-item {
    flex: 1 1 auto;
    flex-direction: column;
    min-height: 64px;
    height: 64px;
    justify-content: center;
    padding: 6px 2px;
    gap: 2px;
    border-radius: 0;
  }
  .nav-label-wrap {
    align-items: center;
    flex: 0 0 auto;
  }
  .nav-item.on::after {
    top: auto;
    right: 18%;
    bottom: 0;
    left: 18%;
    width: auto;
    height: 2px;
  }
  .nav-pulse {
    top: 8px;
    right: calc(50% - 15px);
  }
  .rail-foot {
    flex-direction: row;
    margin-top: 0;
    padding: 0;
    border-top: none;
  }
  .more-wrap {
    flex: 1 1 0;
    width: auto;
    min-width: 0;
    margin-top: 0;
    margin-bottom: 0;
  }
  .clerk-user {
    display: none;
  }
  .account-signout {
    display: none;
  }
  .more-btn {
    min-height: 64px;
    height: 64px;
    border-radius: 0;
  }
  .foot {
    display: none;
  }
  .gauges {
    display: flex;
    flex: 1 1 auto;
  }
  .gauge-vol,
  .gauge-rot,
  .gauge-fg,
  .gauge-mark:not(.primary-mark) {
    display: none;
  }
  .gauge-mark.primary-mark {
    display: grid;
    flex: 1 1 auto;
    max-width: 178px;
    padding: 0 9px;
    border-right: 0;
  }
  .gauge-mark.primary-mark .g-date,
  .gauge-mark.primary-mark .g-name {
    display: none;
  }
  .gauge-mark.primary-mark .g-basis {
    display: none;
  }
  .gauge-mark.primary-mark .g-body {
    gap: 5px;
  }
  .gauge-mark.primary-mark .g-spark {
    width: 40px;
  }
  .stage {
    padding: var(--s3);
  }
  .nav-title {
    font-size: 10px;
    letter-spacing: 0.02em;
  }
  .more-btn .nav-title {
    font-size: 10px;
  }
  .more-btn .nav-hint {
    display: none;
  }
  .clock {
    display: none;
  }
  .strip-warn {
    display: none;
  }
  .strip {
    gap: var(--s2);
    padding: 0 var(--s3);
    overflow: hidden;
  }
  .market-clock {
    display: none;
  }
  .strip-search {
    min-width: 34px;
    padding: 0 8px;
    border-left: 0;
  }
  .strip-search .label,
  .strip-search kbd {
    display: none;
  }
  .strip-profile-btn {
    padding: 2px 4px;
    min-width: 44px;
    min-height: 44px;
    height: 44px;
  }
  .strip-profile-badge {
    display: none;
  }
  .mobile-market-state {
    display: block;
    margin-left: auto;
    color: var(--phosphor);
  }
  .mobile-market-state.closed,
  .mobile-market-state.unknown {
    color: var(--warn);
  }
}
</style>
