<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref } from 'vue'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { api, type MarketClock, type Readiness, type StatusPayload } from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import { age, DASH, num, shortDate, usd, signedPct, tone } from '@/format'

import EvidenceLayerVisual from '@/components/EvidenceLayerVisual.vue'
import AppIcon from '@/components/AppIcon.vue'
import GexFlowVisual from '@/components/GexFlowVisual.vue'
import LiveStateVisual from '@/components/LiveStateVisual.vue'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import ResearchLoopVisual from '@/components/ResearchLoopVisual.vue'
import TradeCentralMark from '@/components/TradeCentralMark.vue'
import {
  gexProfile,
  gexBarsSvg,
  mcPathsSvg,
  monteCarlo,
  histogramSvg,
  volSurface,
  volSurfaceMeshSvg,
  lognormalDensitySvg,
  impliedRange,
} from '@/charts/landing-math'

gsap.registerPlugin(ScrollTrigger)

/**
 * Public product overview.
 *
 * Market figures shown here come from the same loopback resources as the
 * operator shell. Product diagrams carry only labels and system boundaries;
 * there are no illustrative quotes, returns, or invented model scores.
 *
 * All entrance/scroll animation is driven by GSAP. No mockup images — the
 * hero visual is a purpose-built animated SVG instrument diagram.
 */
const status = inject<Resource<StatusPayload>>('status')!
const readiness = inject<Resource<Readiness>>('readiness')!
const clock = useResource<MarketClock>(() => api.marketClock(), { intervalMs: 60_000 })

const session = computed(() => {
  switch (clock.data.value?.market_session) {
    case 'premarket':
      return 'PREMARKET'
    case 'regular':
      return 'REGULAR SESSION'
    case 'after_hours':
      return 'AFTER HOURS'
    case 'closed':
      return 'MARKET CLOSED'
    case 'replay':
      return 'REPLAY'
    default:
      return DASH
  }
})
const sessionLive = computed(() => clock.data.value?.market_session === 'regular')
const sessionNote = computed(() => {
  const value = clock.data.value
  if (!value) return null
  if (value.is_early_close) return 'Early close'
  if (!value.is_trading_day) return 'Non-trading day'
  return null
})

const dataAsof = computed(() => {
  const asof = status.data.value?.asof
  if (!asof) return DASH
  return `${shortDate(asof)} · ${age(asof)} ago`
})
const universe = computed(() => num(status.data.value?.broad_universe_count, 0))
const searchable = computed(() => num(status.data.value?.searchable_symbol_count, 0))
const gates = computed(() => readiness.data.value?.gates_summary ?? null)
const cleared = computed(() => readiness.data.value?.cleared_for_live === true)
const readinessLabel = computed(() => {
  if (!readiness.data.value) return DASH
  return cleared.value ? 'CLEARED' : 'NOT CLEARED'
})
const blockers = computed(() => readiness.data.value?.blocking_reasons?.length ?? null)
const shadow = computed(() => {
  const value = readiness.data.value?.shadow
  if (!value) return DASH
  return `${num(value.n_sessions, 0)} / ${num(value.required, 0)}`
})
const apiDown = computed(() => Boolean(status.error.value && !status.data.value))
const apiStale = computed(() => Boolean(status.error.value && status.data.value))
const contacting = computed(() => status.loading.value && !status.data.value && !status.error.value)

/* ── Rotating word in the hero lede ──────────────────────────────────────────
   Cycles one real product concept. The visual transition is CSS; GSAP
   handles the larger entrance timeline. */
const ROTATING_WORDS = ['positioning', 'flow', 'gamma structure', 'research evidence'] as const
const rotatingIndex = ref(0)
let rotateTimer: number | undefined
function startRotating(): void {
  rotateTimer = window.setInterval(() => {
    rotatingIndex.value = (rotatingIndex.value + 1) % ROTATING_WORDS.length
  }, 2600)
}
function stopRotating(): void {
  if (rotateTimer !== undefined) {
    clearInterval(rotateTimer)
    rotateTimer = undefined
  }
}

/* ── Magnetic CTA buttons (GSAP quickTo for buttery following) ─────────────── */
const magneticRefs = ref<HTMLElement[]>([])
let xTo: ((v: number) => void) | undefined
let yTo: ((v: number) => void) | undefined

function onMagneticMove(e: MouseEvent): void {
  const el = e.currentTarget as HTMLElement
  const rect = el.getBoundingClientRect()
  const cx = rect.left + rect.width / 2
  const cy = rect.top + rect.height / 2
  xTo?.((e.clientX - cx) * 0.3)
  yTo?.((e.clientY - cy) * 0.3)
}
function onMagneticLeave(): void {
  xTo?.(0)
  yTo?.(0)
}

/* ── Card spotlight (mouse-following top-border highlight) ────────────────── */
function onCardMove(e: MouseEvent, event: 'enter' | 'move' | 'leave'): void {
  const target = e.currentTarget as HTMLElement
  if (event === 'leave') {
    target.style.setProperty('--card-x', '50%')
    target.style.setProperty('--card-y', '0%')
    return
  }
  const rect = target.getBoundingClientRect()
  const x = ((e.clientX - rect.left) / rect.width) * 100
  const y = ((e.clientY - rect.top) / rect.height) * 100
  target.style.setProperty('--card-x', `${x}%`)
  target.style.setProperty('--card-y', `${y}%`)
}

/* ── Content data ──────────────────────────────────────────────────────────── */
const capabilities = [
  {
    kind: 'market' as const,
    icon: 'radar',
    index: '01',
    title: 'Market structure',
    copy: 'Search a broad US equity universe, compare trajectories, inspect sector rotation, and keep source freshness visible.',
    detail: 'Price · regimes · sectors · outliers',
    stat: 'Broad universe',
    statValue: () => universe.value,
    span: 'wide',
  },
  {
    kind: 'options' as const,
    icon: 'options',
    index: '02',
    title: 'Options & flow',
    copy: 'Read positioning, gamma topology, implied ranges, unusual activity, and signed-flow coverage without collapsing them into one score.',
    detail: 'GEX · flow · ranges · contract context',
    stat: 'Gates cleared',
    statValue: () => num(gates.value?.go, 0),
    span: 'tall',
  },
  {
    kind: 'governance' as const,
    icon: 'gate',
    index: '03',
    title: 'Research governance',
    copy: 'Trace every claim back to point-in-time tests, pre-registered gates, run artifacts, and explicit shadow evidence.',
    detail: 'Methods · diagnostics · gates · ledgers',
    stat: 'Shadow sessions',
    statValue: () => shadow.value,
    span: 'normal',
  },
] as const

const principles = [
  {
    index: 'A',
    title: 'Missing stays missing',
    copy: 'Stale, unavailable, proxy, and degraded states are labelled—not silently converted to zero.',
    svg: '<circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.3"/><path d="M8 12h8M12 8v8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/><circle cx="12" cy="12" r="2.5" stroke="currentColor" stroke-width="1.3"/>',
  },
  {
    index: 'B',
    title: 'Evidence stays typed',
    copy: 'Ordinal research evidence is never presented as calibrated probability or trade authorization.',
    svg: '<path d="M12 3l7 2.5v4.5c0 4.5-2.8 8.2-7 9.5-4.2-1.3-7-5-7-9.5V5.5L12 3z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M9 12l2 2 4.5-4.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>',
  },
  {
    index: 'C',
    title: 'Promotion fails closed',
    copy: 'Readiness and pre-registered gates must agree before any strategy can advance beyond research.',
    svg: '<rect x="5" y="10" width="14" height="10" rx="1" stroke="currentColor" stroke-width="1.3"/><path d="M8 10V7a4 4 0 0 1 8 0v3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/><circle cx="12" cy="15" r="1.2" fill="currentColor"/>',
  },
  {
    index: 'D',
    title: 'Execution stays outside',
    copy: 'The checked-in pipeline contains no broker connection, order ticket, or submission route.',
    svg: '<rect x="5" y="11" width="14" height="9" rx="1" stroke="currentColor" stroke-width="1.3"/><path d="M8 11V8a4 4 0 0 1 6.5-3.1" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/><circle cx="12" cy="15.5" r="1.2" fill="currentColor"/>',
  },
] as const

const pipelineSteps = [
  {
    label: 'DATA',
    note: 'Point-in-time capture',
    idx: '01',
    svg: '<rect x="4" y="3" width="16" height="4" rx="0.5" stroke="currentColor" stroke-width="1.3"/><rect x="4" y="10" width="16" height="4" rx="0.5" stroke="currentColor" stroke-width="1.3"/><rect x="4" y="17" width="16" height="4" rx="0.5" stroke="currentColor" stroke-width="1.3"/><circle cx="7.5" cy="5" r="0.8" fill="currentColor"/><circle cx="7.5" cy="12" r="0.8" fill="currentColor"/><circle cx="7.5" cy="19" r="0.8" fill="currentColor"/>',
  },
  {
    label: 'RESEARCH',
    note: 'IC decay · quantiles',
    idx: '02',
    svg: '<path d="M10 3v6.5L5 18a2 2 0 0 0 1.7 3.2h10.6A2 2 0 0 0 19 18l-5-8.5V3" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M8 3h4M8.5 15h7" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>',
  },
  {
    label: 'GATES',
    note: 'Pre-registered verdicts',
    idx: '03',
    svg: '<path d="M5 21V7l7-3 7 3v14" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M9.5 21v-6h5v6M4 21h16" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>',
  },
  {
    label: 'SHADOW',
    note: 'Live, unscored',
    idx: '04',
    svg: '<circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="1.3"/><path d="M12 7v5l3.5 2" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>',
  },
  {
    label: 'READINESS',
    note: 'Fail-closed promotion',
    idx: '05',
    svg: '<path d="M12 3l7 2.5v4.5c0 4.5-2.8 8.2-7 9.5-4.2-1.3-7-5-7-9.5V5.5L12 3z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M9 12l2 2 4.5-4.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>',
  },
] as const

/* ── Math-driven hero instrument diagram ─────────────────────────────────────
   All geometry is computed from named financial models, not hand-picked
   decorative shapes. Parameters are structural and labelled as illustrative
   anatomy — live values appear only after sign-in.

   Models used:
     · Implied volatility surface (parametric smile + term structure)
     · Black-Scholes gamma → GEX-by-strike profile
     · Monte Carlo GBM → terminal distribution fan chart + histogram
     · Lognormal risk-neutral density → implied range cone
 */
const MODEL = {
  S0: 100,
  mu: 0.08,
  sigma: 0.3,
  T: 0.25,
  r: 0.05,
  q: 0,
  steps: 60,
  nStrikes: 21,
  strikeRange: 0.25,
  // Vol surface parameters
  volSkew: -0.8, // equity put skew (higher IV for downside)
  volCurve: 1.2, // smile curvature (wings)
  volTermDecay: 0.3, // term structure decay
  // Monte Carlo parameters
  mcPaths: 40,
  mcBins: 24,
  mcSeed: 42,
} as const

/* Strike and maturity grids for the vol surface */
const volStrikes = Array.from({ length: 11 }, (_, i) => MODEL.S0 * (0.8 + 0.04 * i))
const volMaturities = [0.083, 0.167, 0.25, 0.5, 0.75, 1.0] // 1M, 2M, 3M, 6M, 9M, 12M

/* ── Volatility surface (3D mesh) ─────────────────────────────────────────── */
const volSurfaceData = computed(() =>
  volSurface(
    MODEL.S0,
    MODEL.r,
    MODEL.q,
    volStrikes,
    volMaturities,
    MODEL.sigma,
    MODEL.volSkew,
    MODEL.volCurve,
    MODEL.volTermDecay,
  ),
)
const volMesh = computed(() =>
  volSurfaceMeshSvg(
    volSurfaceData.value,
    volStrikes,
    volMaturities,
    { x: 0, y: 0, w: 500, h: 330 },
    0.5,
    0.65,
  ),
)

/* ── GEX profile (Black-Scholes gamma) ────────────────────────────────────── */
const gexGeometry = computed(() => {
  const profile = gexProfile(
    MODEL.S0,
    MODEL.T,
    MODEL.sigma,
    MODEL.r,
    MODEL.q,
    MODEL.nStrikes,
    MODEL.strikeRange,
  )
  return gexBarsSvg(profile, { x: 40, y: 40, w: 460, h: 120 }, 16)
})

/* ── Monte Carlo terminal distribution ────────────────────────────────────── */
const mcResult = computed(() =>
  monteCarlo(
    MODEL.S0,
    MODEL.mu,
    MODEL.sigma,
    MODEL.T,
    MODEL.mcPaths,
    MODEL.steps,
    MODEL.mcSeed,
    MODEL.mcBins,
  ),
)
const mcFanPaths = computed(() =>
  mcPathsSvg(mcResult.value.paths, { x: 20, y: 200, w: 480, h: 120 }),
)
const mcHistogram = computed(() =>
  histogramSvg(mcResult.value.histogram, { x: 20, y: 200, w: 480, h: 120 }, 14),
)

/* ── Lognormal risk-neutral density ────────────────────────────────────────── */
const densityGeometry = computed(() =>
  lognormalDensitySvg(
    MODEL.S0,
    MODEL.T,
    MODEL.sigma,
    MODEL.r,
    MODEL.q,
    { x: 20, y: 200, w: 480, h: 120 },
    80,
  ),
)

/* ── Risk-neutral implied range ────────────────────────────────────────────── */
const range = computed(() => impliedRange(MODEL.S0, MODEL.T, MODEL.sigma, MODEL.r, MODEL.q))

/* ── Ticker tape ───────────────────────────────────────────────────────────── */
const TAPE = [
  { sym: 'SPY', label: 'S&P 500' },
  { sym: 'QQQ', label: 'Nasdaq' },
  { sym: 'DIA', label: 'Dow' },
  { sym: 'XLE', label: 'Energy' },
  { sym: 'IWM', label: 'Russell 2000' },
  { sym: 'VIX', label: 'Volatility' },
] as const

const tapeData = ref<{ sym: string; label: string; price: number | null; chg: number | null }[]>([])

async function loadTape(): Promise<void> {
  try {
    const payload = await api.compare(['SPY', 'QQQ', 'DIA', 'XLE'], '1m')
    const stats = payload.stats ?? {}
    tapeData.value = TAPE.map((t) => {
      const s = stats[t.sym]
      const price = typeof s?.last_price === 'number' ? s.last_price : null
      const chg =
        typeof s?.chg_1d_pct === 'number'
          ? s.chg_1d_pct
          : typeof s?.chg_window_pct === 'number'
            ? s.chg_window_pct
            : null
      return { sym: t.sym, label: t.label, price, chg }
    })
  } catch {
    tapeData.value = TAPE.map((t) => ({ sym: t.sym, label: t.label, price: null, chg: null }))
  }
}

/* ── GSAP animation orchestration ─────────────────────────────────────────── */
let ctx: gsap.Context | undefined
const heroSvgRef = ref<SVGSVGElement | null>(null)
const prefersReducedMotion = ref(false)

function setupMagnetic(): void {
  if (prefersReducedMotion.value || magneticRefs.value.length === 0) return
  xTo = gsap.quickTo(magneticRefs.value, 'x', { duration: 0.5, ease: 'power3.out' })
  yTo = gsap.quickTo(magneticRefs.value, 'y', { duration: 0.5, ease: 'power3.out' })
}

onMounted(() => {
  document.body.classList.add('edge-public-mode')
  void loadTape()

  prefersReducedMotion.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  /* GSAP context scopes all animations so ctx.revert() cleans up everything */
  ctx = gsap.context(() => {
    if (prefersReducedMotion.value) return

    /* ── Hero entrance timeline ──────────────────────────────────────────── */
    const heroTl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    heroTl
      .from('.hero-eyebrow', { opacity: 0, y: 12, duration: 0.45 })
      .from(
        '.hero-headline .word',
        { opacity: 0, y: 24, filter: 'blur(6px)', stagger: 0.05, duration: 0.55 },
        '-=0.15',
      )
      .from('.hero-lede', { opacity: 0, y: 12, duration: 0.4 }, '-=0.2')
      .from('.hero-actions', { opacity: 0, y: 12, duration: 0.4 }, '-=0.15')
      .from('.hero-boundary', { opacity: 0, y: 10, duration: 0.35 }, '-=0.1')
      .from('.hero-warn-note', { opacity: 0, y: 8, duration: 0.3 }, '-=0.1')

    /* ── Hero SVG instrument diagram draws in ────────────────────────────── */
    const svg = heroSvgRef.value
    if (svg) {
      const svgTl = gsap.timeline({ delay: 0.4, defaults: { ease: 'power2.out' } })
      svgTl
        .from('.hero-svg-grid path', { opacity: 0, stagger: 0.02, duration: 0.3 })
        // Vol surface mesh draws in
        .from('.hero-svg-surface-ribbon', { opacity: 0, stagger: 0.04, duration: 0.4 }, '-=0.1')
        .from('.hero-svg-mesh-line', { opacity: 0, stagger: 0.015, duration: 0.5 }, '-=0.3')
        .from('.hero-svg-contour', { opacity: 0, stagger: 0.1, duration: 0.4 }, '-=0.3')
        // GEX bars grow up
        .from(
          '.hero-svg-bar',
          { scaleY: 0, transformOrigin: 'center bottom', stagger: 0.03, duration: 0.4 },
          '-=0.2',
        )
        .from(
          '.hero-svg-zero',
          { scaleX: 0, transformOrigin: 'left center', duration: 0.4 },
          '-=0.2',
        )
        .from('.hero-svg-flip', { scaleY: 0, transformOrigin: 'center', duration: 0.3 }, '-=0.2')
        // MC fan paths draw in
        .from('.hero-svg-mc-path', { opacity: 0, stagger: 0.01, duration: 0.3 }, '-=0.2')
        .from(
          '.hero-svg-histogram',
          { scaleY: 0, transformOrigin: 'bottom', duration: 0.4 },
          '-=0.2',
        )
        // Density curve draws in
        .from('.hero-svg-density-area', { opacity: 0, duration: 0.4 }, '-=0.2')
        .from(
          '.hero-svg-trace',
          { strokeDashoffset: 1200, duration: 1.2, ease: 'power2.inOut' },
          '-=0.2',
        )
        .from(
          '.hero-svg-range',
          { scaleY: 0, transformOrigin: 'top', stagger: 0.1, duration: 0.3 },
          '-=0.5',
        )
        .from('.hero-svg-median', { scaleY: 0, transformOrigin: 'top', duration: 0.3 }, '-=0.2')
        // Labels + corners
        .from('.hero-svg-label', { opacity: 0, stagger: 0.02, duration: 0.2 }, '-=0.3')
        .from('.hero-svg-corner', { opacity: 0, stagger: 0.05, duration: 0.2 }, '-=0.2')
    }

    /* ── Magnetic buttons ────────────────────────────────────────────────── */
    setupMagnetic()

    /* ── Section reveals via ScrollTrigger ───────────────────────────────── */
    gsap.utils.toArray<HTMLElement>('.gsap-reveal').forEach((el) => {
      gsap.from(el, {
        opacity: 0,
        y: 28,
        duration: 0.65,
        ease: 'power2.out',
        scrollTrigger: { trigger: el, start: 'top 85%', toggleActions: 'play none none none' },
      })
    })

    /* ── Stat counters animate when the strip enters view ─────────────────── */
    const statTargets = [
      { el: '.stat-universe', value: Number(status.data.value?.broad_universe_count ?? 0) },
      { el: '.stat-searchable', value: Number(status.data.value?.searchable_symbol_count ?? 0) },
      { el: '.stat-gates', value: Number(gates.value?.go ?? 0) },
    ]
    statTargets.forEach(({ el, value }) => {
      const node = document.querySelector(el)
      if (!node || value === 0) return
      const obj = { val: 0 }
      gsap.to(obj, {
        val: value,
        duration: 1.4,
        ease: 'power2.out',
        snap: { val: 1 },
        onUpdate: () => {
          node.textContent = num(obj.val, 0)
        },
        scrollTrigger: {
          trigger: '.stats-section',
          start: 'top 80%',
          toggleActions: 'play none none none',
        },
      })
    })

    /* ── Tracing beam fills as you scroll through the evidence section ───── */
    gsap.fromTo(
      '.beam-fill',
      { height: '0%' },
      {
        height: '100%',
        ease: 'none',
        scrollTrigger: {
          trigger: '.tracing-beam-wrap',
          start: 'top 65%',
          end: 'bottom 75%',
          scrub: 0.6,
        },
      },
    )

    /* ── Pipeline nodes light up as the beam passes ────────────────────────── */
    gsap.utils.toArray<HTMLElement>('.pipeline-step').forEach((step, i) => {
      gsap.to(step, {
        scrollTrigger: {
          trigger: step,
          start: 'top 70%',
          toggleActions: 'add none none none',
          onEnter: () => step.classList.add('done'),
        },
        duration: 0.01,
        delay: i * 0.01,
      })
    })

    /* ── Topbar subtle background gain on scroll ─────────────────────────── */
    gsap.to('.topbar-shell', {
      backgroundColor: 'rgba(8, 9, 12, 0.96)',
      borderBottomColor: 'var(--rule-hi)',
      duration: 0.3,
      ease: 'none',
      scrollTrigger: { start: 40, toggleActions: 'play none none reverse' },
    })
  })

  startRotating()
})

onUnmounted(() => {
  document.body.classList.remove('edge-public-mode')
  ctx?.revert()
  stopRotating()
})
</script>

<template>
  <div class="landing-page">
    <!-- ── topbar ───────────────────────────────────────────────────────────── -->
    <header class="topbar-shell">
      <div class="topbar landing-inner">
        <RouterLink class="brand" to="/" aria-label="TradeCentral home">
          <span class="brand-mark"><TradeCentralMark :size="28" /></span>
          <span class="wordmark">
            <strong>TradeCentral</strong>
            <small>Quantitative research instrument</small>
          </span>
        </RouterLink>

        <nav class="topnav" aria-label="Product overview">
          <a href="#product"><small>01</small>Product</a>
          <a href="#workspaces"><small>02</small>Workspaces</a>
          <a href="#method"><small>03</small>Method</a>
          <a href="#evidence"><small>04</small>Evidence</a>
        </nav>

        <div class="top-actions">
          <RouterLink
            class="sign-in"
            :to="{ name: 'auth', query: { mode: 'signin', redirect: '/flow' } }"
          >
            Sign in
          </RouterLink>
          <RouterLink
            class="button button-accent"
            :to="{ name: 'auth', query: { mode: 'setup', redirect: '/flow' } }"
          >
            Create access
            <svg
              class="btn-chevron"
              width="14"
              height="14"
              viewBox="0 0 14 14"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M3 7h8M8 3.5l3.5 3.5L8 10.5"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </RouterLink>
        </div>
      </div>
    </header>

    <!-- ── animated ticker tape ──────────────────────────────────────────────── -->
    <div class="ticker-tape" aria-hidden="true">
      <div class="ticker-track">
        <div class="ticker-row">
          <span
            v-for="(item, i) in [...tapeData, ...tapeData]"
            :key="`${item.sym}-${i}`"
            class="ticker-item"
          >
            <span class="ticker-sym">{{ item.sym }}</span>
            <span class="ticker-sep">·</span>
            <span class="ticker-price">{{ item.price != null ? usd(item.price) : 'SYNC' }}</span>
            <span v-if="item.chg != null" class="ticker-chg" :class="tone(item.chg)">{{
              signedPct(item.chg, 2)
            }}</span>
          </span>
        </div>
        <div class="ticker-row" aria-hidden="true">
          <span
            v-for="(item, i) in [...tapeData, ...tapeData]"
            :key="`${item.sym}-dup-${i}`"
            class="ticker-item"
          >
            <span class="ticker-sym">{{ item.sym }}</span>
            <span class="ticker-sep">·</span>
            <span class="ticker-price">{{ item.price != null ? usd(item.price) : 'SYNC' }}</span>
            <span v-if="item.chg != null" class="ticker-chg" :class="tone(item.chg)">{{
              signedPct(item.chg, 2)
            }}</span>
          </span>
        </div>
      </div>
    </div>

    <main>
      <!-- ── HERO ──────────────────────────────────────────────────────────── -->
      <section class="hero landing-inner">
        <div class="hero-copy">
          <p class="hero-eyebrow"><span aria-hidden="true" /> US equities · options intelligence</p>

          <h1 class="hero-headline">
            <span v-for="(w, i) in 'Read the market'.split(' ')" :key="`a-${i}`" class="word"
              >{{ w }}&nbsp;</span
            >
            <br />
            <span v-for="(w, i) in 'beneath the price.'.split(' ')" :key="`b-${i}`" class="word em"
              >{{ w }}&nbsp;</span
            >
          </h1>

          <p class="hero-lede">
            TradeCentral brings dealer positioning, options flow, and research controls into one
            evidence-first view—so a move has
            <span class="rotating-word">
              <span
                v-for="(word, i) in ROTATING_WORDS"
                :key="word"
                class="rw-item"
                :class="{ active: i === rotatingIndex }"
                >{{ word }}</span
              >
            </span>
            before it has a narrative.
          </p>

          <div class="hero-actions">
            <span
              ref="magneticRefs"
              class="magnetic-wrap"
              @mousemove="onMagneticMove"
              @mouseleave="onMagneticLeave"
            >
              <RouterLink
                class="button button-accent"
                :to="{ name: 'auth', query: { redirect: '/flow' } }"
              >
                Explore market flow
                <AppIcon name="flow" :size="15" class="btn-icon" />
              </RouterLink>
            </span>
            <a class="button button-quiet" href="#product">
              See what you get
              <svg
                class="btn-chevron"
                width="14"
                height="14"
                viewBox="0 0 14 14"
                fill="none"
                aria-hidden="true"
              >
                <path
                  d="M7 3v8M3.5 7.5l3.5 3.5L10.5 7.5"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </a>
          </div>

          <div class="hero-boundary">
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              aria-hidden="true"
              class="boundary-icon"
            >
              <path
                d="M8 2l5 2v4c0 3.5-2 6.5-5 8-3-1.5-5-4.5-5-8V4l5-2z"
                stroke="currentColor"
                stroke-width="1.2"
                stroke-linejoin="round"
              />
              <path
                d="M6 8l1.5 1.5L10.5 6.5"
                stroke="currentColor"
                stroke-width="1.2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            <span><strong>Research only.</strong> No order routing. No performance promises.</span>
          </div>
          <p class="hero-warn-note">
            Stale or missing data is shown as stale or missing — never as a fake zero.
          </p>
        </div>

        <!-- ── animated SVG instrument diagram (math-driven) ───────────────── -->
        <div class="hero-visual">
          <figure
            class="instrument-frame"
            aria-label="Quantitative models: implied volatility surface, GEX profile, and Monte Carlo terminal distribution. Live prints appear after sign-in."
          >
            <figcaption>
              <span class="fig-label">QUANT MODELS</span>
              <span class="fig-state"
                >STRUCTURAL · 1σ [{{ range.p1Low.toFixed(1) }}–{{ range.p1High.toFixed(1) }}]</span
              >
            </figcaption>

            <div class="instrument-stage">
              <svg
                ref="heroSvgRef"
                viewBox="0 0 520 400"
                preserveAspectRatio="xMidYMid meet"
                class="hero-svg"
              >
                <!-- ── measurement grid ──────────────────────────────────────── -->
                <g class="hero-svg-grid">
                  <path
                    d="M10 10H510M10 60H510M10 110H510M10 160H510M10 210H510M10 260H510M10 310H510M10 360H510M10 390H510"
                  />
                  <path
                    d="M60 10V390M120 10V390M180 10V390M240 10V390M300 10V390M360 10V390M420 10V390M480 10V390"
                  />
                </g>

                <!-- ── PANEL 1: Volatility surface 3D mesh (top, largest) ──── -->
                <g class="vol-surface-panel">
                  <text class="hero-svg-label" x="14" y="24">IMPLIED VOLATILITY SURFACE</text>
                  <text class="hero-svg-label dim" x="430" y="24">σ(K,T)</text>

                  <!-- surface fill ribbons (depth shading) -->
                  <path
                    v-for="(ribbon, i) in volMesh.surfaceLines"
                    :key="`ribbon-${i}`"
                    class="hero-svg-surface-ribbon"
                    :d="ribbon"
                    :style="{ opacity: 0.04 + 0.05 * (i % 4) }"
                  />

                  <!-- mesh grid lines -->
                  <path
                    v-for="(line, i) in volMesh.gridLines"
                    :key="`grid-${i}`"
                    class="hero-svg-mesh-line"
                    :d="line"
                  />

                  <!-- contour lines at IV levels -->
                  <path
                    v-for="(contour, i) in volMesh.contourLines"
                    :key="`contour-${i}`"
                    class="hero-svg-contour"
                    :d="contour"
                  />
                </g>

                <!-- ── PANEL 2: GEX profile (middle) ────────────────────────── -->
                <g class="gex-panel" transform="translate(0, 215)">
                  <text class="hero-svg-label" x="14" y="14">GEX BY STRIKE</text>
                  <text class="hero-svg-label dim" x="430" y="14">BS γ</text>

                  <path class="hero-svg-bar" :d="gexGeometry.callBars" />
                  <path class="hero-svg-bar put" :d="gexGeometry.putBars" />
                  <line
                    class="hero-svg-zero"
                    :x1="40"
                    :y1="gexGeometry.zeroY - 215"
                    :x2="500"
                    :y2="gexGeometry.zeroY - 215"
                  />
                  <line
                    class="hero-svg-flip"
                    :x1="gexGeometry.flipX"
                    :y1="10"
                    :x2="gexGeometry.flipX"
                    :y2="120"
                  />
                  <text class="hero-svg-label dim" :x="gexGeometry.flipX - 16" y="6">FLIP</text>
                </g>

                <!-- ── PANEL 3: MC fan chart + density (bottom) ─────────────── -->
                <g class="mc-panel" transform="translate(0, 270)">
                  <text class="hero-svg-label" x="14" y="14">MONTE CARLO · LOGNORMAL DENSITY</text>
                  <text class="hero-svg-label dim" x="380" y="14">
                    {{ mcResult.paths.length }} paths
                  </text>

                  <!-- MC fan paths -->
                  <path
                    v-for="(p, i) in mcFanPaths"
                    :key="`mc-${i}`"
                    class="hero-svg-mc-path"
                    :d="p.d"
                    :style="{ opacity: p.opacity }"
                  />

                  <!-- histogram bars -->
                  <path class="hero-svg-histogram" :d="mcHistogram" />

                  <!-- lognormal density curve overlay -->
                  <path class="hero-svg-density-area" :d="densityGeometry.area" />
                  <path class="hero-svg-trace" :d="densityGeometry.d" pathLength="1200" />

                  <!-- 1σ range bounds -->
                  <line
                    class="hero-svg-range"
                    :x1="densityGeometry.p1LowX"
                    :y1="10"
                    :x2="densityGeometry.p1LowX"
                    :y2="115"
                  />
                  <line
                    class="hero-svg-range"
                    :x1="densityGeometry.p1HighX"
                    :y1="10"
                    :x2="densityGeometry.p1HighX"
                    :y2="115"
                  />

                  <!-- median -->
                  <line
                    class="hero-svg-median"
                    :x1="densityGeometry.medianX"
                    :y1="10"
                    :x2="densityGeometry.medianX"
                    :y2="115"
                  />

                  <text class="hero-svg-label dim" :x="densityGeometry.p1LowX - 8" y="125">
                    -1σ
                  </text>
                  <text class="hero-svg-label dim" :x="densityGeometry.medianX - 14" y="125">
                    MED
                  </text>
                  <text class="hero-svg-label dim" :x="densityGeometry.p1HighX - 8" y="125">
                    +1σ
                  </text>
                </g>

                <!-- ── corner registration marks ────────────────────────────── -->
                <path class="hero-svg-corner" d="M10 10h12M10 10v12" />
                <path class="hero-svg-corner" d="M500 10h-12M500 10v12" />
                <path class="hero-svg-corner" d="M10 390h12M10 390v-12" />
                <path class="hero-svg-corner" d="M500 390h-12M500 390v-12" />
              </svg>

              <!-- axis annotations -->
              <div class="axis-label axis-vol">Vol surface</div>
              <div class="axis-label axis-gex">GEX profile</div>
              <div class="axis-label axis-mc">MC terminal</div>
            </div>

            <footer>
              <span class="fig-legend"><i class="leg-mesh" />Vol mesh</span>
              <span class="fig-legend"><i class="leg-call" />Call GEX</span>
              <span class="fig-legend"><i class="leg-put" />Put GEX</span>
              <span class="fig-legend"><i class="leg-trace" />Lognormal</span>
              <strong
                >BS + GBM · σ={{ (MODEL.sigma * 100).toFixed(0) }}% · T={{
                  (MODEL.T * 12).toFixed(0)
                }}M · N={{ mcResult.paths.length }}</strong
              >
            </footer>
          </figure>
        </div>
      </section>

      <!-- ── animated stats strip ───────────────────────────────────────────── -->
      <section class="stats-section" aria-label="Live instrument state">
        <div class="landing-inner stats-strip">
          <Readout
            label="Symbols tracked"
            value="0"
            sub="Broad universe"
            size="lg"
            class="stat-universe"
          />
          <Readout label="Searchable" value="0" sub="Symbols" size="lg" class="stat-searchable" />
          <Readout
            label="Gates cleared"
            value="0"
            sub="Pre-registered"
            size="lg"
            tone="accent"
            class="stat-gates"
          />
          <Readout label="Shadow sessions" :value="shadow" sub="Evidence" size="lg" />
        </div>
      </section>

      <section class="live-proof-section">
        <LiveStateVisual
          class="landing-inner gsap-reveal"
          :session="session"
          :session-live="sessionLive"
          :session-note="sessionNote"
          :data-asof="dataAsof"
          :universe="universe"
          :searchable="searchable"
          :readiness-label="readinessLabel"
          :cleared="cleared"
          :blockers="blockers"
          :shadow="shadow"
          :gate-go="num(gates?.go, 0)"
          :gate-no-go="num(gates?.no_go, 0)"
          :gate-unknown="num(gates?.unknown, 0)"
          :api-down="apiDown"
          :api-stale="apiStale"
          :contacting="contacting"
        />
      </section>

      <!-- ── PRODUCT / bento grid ───────────────────────────────────────────── -->
      <section id="product" class="product-section">
        <div class="landing-inner">
          <header class="section-heading gsap-reveal">
            <div>
              <p class="section-index">PRODUCT / 01</p>
              <h2>One instrument.<br />Three evidence layers.</h2>
            </div>
            <p>
              Built for researchers and active traders who want institutional discipline without a
              black-box confidence meter. Every surface has a specific question, a source, and an
              honest failure state.
            </p>
          </header>

          <div class="bento-grid">
            <Panel
              v-for="capability in capabilities"
              :key="capability.index"
              class="bento-card gsap-reveal"
              :class="`span-${capability.span}`"
              :label="capability.title"
              :index="capability.index"
              :meta="capability.detail"
            >
              <div
                class="card-spotlight-target"
                @mouseenter="(e) => onCardMove(e, 'enter')"
                @mousemove="(e) => onCardMove(e, 'move')"
                @mouseleave="(e) => onCardMove(e, 'leave')"
              >
                <EvidenceLayerVisual :kind="capability.kind" />
                <p class="capability-copy">{{ capability.copy }}</p>
                <div class="capability-stat">
                  <span class="stat-label">{{ capability.stat }}</span>
                  <span class="stat-val fig">{{ capability.statValue() }}</span>
                </div>
              </div>
            </Panel>
          </div>
        </div>
      </section>

      <section class="flow-section">
        <div class="landing-inner flow-layout">
          <div class="flow-copy gsap-reveal">
            <p class="section-index">OPTIONS INTELLIGENCE / 02</p>
            <h2>See the structure<br />behind a move.</h2>
            <p>
              Map dealer gamma by strike, locate the flip, and inspect the tape. Calls, puts, and
              unsigned activity stay separate until the provider gives a side.
            </p>
            <RouterLink class="text-link" :to="{ name: 'auth', query: { redirect: '/flow' } }">
              Explore market flow
              <svg
                class="link-chevron"
                width="14"
                height="14"
                viewBox="0 0 14 14"
                fill="none"
                aria-hidden="true"
              >
                <path
                  d="M3 7h8M8 3.5l3.5 3.5L8 10.5"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </RouterLink>
          </div>
          <GexFlowVisual class="gsap-reveal" />
        </div>
      </section>

      <section id="workspaces" class="workspace-section">
        <div class="landing-inner workspace-layout">
          <div class="workspace-copy gsap-reveal">
            <p class="section-index">WORKSPACES / 03</p>
            <h2>A research path.<br />Not a menu.</h2>
            <p>
              Each workspace answers one question, then hands its context forward. The path stays
              visible, while specialist tools remain adjacent.
            </p>
            <RouterLink class="text-link" :to="{ name: 'auth', query: { redirect: '/flow' } }">
              Open Flow now
              <svg
                class="link-chevron"
                width="14"
                height="14"
                viewBox="0 0 14 14"
                fill="none"
                aria-hidden="true"
              >
                <path
                  d="M3 7h8M8 3.5l3.5 3.5L8 10.5"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </RouterLink>
          </div>
          <ResearchLoopVisual class="gsap-reveal" />
        </div>
      </section>

      <!-- ── EVIDENCE / tracing beam pipeline ───────────────────────────────── -->
      <section id="evidence" class="evidence-section">
        <div class="landing-inner">
          <header class="section-heading evidence-heading gsap-reveal">
            <div>
              <p class="section-index">EVIDENCE / 04</p>
              <h2>The research loop.<br />Traced end to end.</h2>
            </div>
            <p>
              Every signal moves through the same path: data, research, gates, shadow, readiness. No
              shortcut, no override, no silent promotion.
            </p>
          </header>

          <div class="tracing-beam-wrap gsap-reveal" aria-label="Research evidence pipeline">
            <div class="tracing-beam-rail">
              <span class="beam-fill" />
            </div>

            <div class="pipeline">
              <div v-for="(step, i) in pipelineSteps" :key="step.label" class="pipeline-step">
                <div class="pipeline-node">
                  <span class="pipeline-idx fig">{{ step.idx }}</span>
                  <span
                    class="pipeline-icon"
                    v-html="
                      `<svg width='24' height='24' viewBox='0 0 24 24' fill='none' aria-hidden='true'>${step.svg}</svg>`
                    "
                  />
                  <strong class="pipeline-label">{{ step.label }}</strong>
                  <em class="pipeline-note">{{ step.note }}</em>
                </div>
                <div v-if="i < 4" class="pipeline-connector" aria-hidden="true">
                  <span class="connector-line" />
                  <span class="connector-arrow"
                    ><svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                      <path
                        d="M3 7h8M8 3.5l3.5 3.5L8 10.5"
                        stroke="currentColor"
                        stroke-width="1.5"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      /></svg
                  ></span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="method" class="method-section">
        <div class="landing-inner">
          <header class="section-heading method-heading gsap-reveal">
            <div>
              <p class="section-index">METHOD / 05</p>
              <h2>Trust is a system property.</h2>
            </div>
            <p>
              TradeCentral separates research, decision support, readiness, and execution
              authorization. A polished surface never gets to erase that boundary.
            </p>
          </header>

          <div class="principle-grid">
            <Panel
              v-for="principle in principles"
              :key="principle.index"
              class="principle gsap-reveal"
              :label="principle.title"
              :index="principle.index"
            >
              <div
                class="principle-inner"
                @mouseenter="(e) => onCardMove(e, 'enter')"
                @mousemove="(e) => onCardMove(e, 'move')"
                @mouseleave="(e) => onCardMove(e, 'leave')"
              >
                <div
                  class="principle-icon"
                  v-html="
                    `<svg width='22' height='22' viewBox='0 0 24 24' fill='none' aria-hidden='true'>${principle.svg}</svg>`
                  "
                />
                <p class="principle-copy">{{ principle.copy }}</p>
              </div>
            </Panel>
          </div>
        </div>
      </section>

      <section class="final-cta">
        <div class="landing-inner final-inner gsap-reveal">
          <p class="section-index">THE RESEARCH LOOP</p>
          <h2>Build conviction from evidence,<br /><em>not presentation.</em></h2>
          <p>One workstation for market context, options structure, and accountable research.</p>
          <span
            ref="magneticRefs"
            class="magnetic-wrap magnetic-center"
            @mousemove="onMagneticMove"
            @mouseleave="onMagneticLeave"
          >
            <RouterLink
              class="button button-accent"
              :to="{ name: 'auth', query: { redirect: '/flow' } }"
            >
              Sign in and open Flow
              <svg
                class="btn-chevron"
                width="15"
                height="15"
                viewBox="0 0 15 15"
                fill="none"
                aria-hidden="true"
              >
                <path
                  d="M3 7.5h9M9.5 4l3.5 3.5L9.5 11"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </RouterLink>
          </span>
          <small
            >No credit card. No broker connection. Clerk session, then the measured tape.</small
          >
        </div>
      </section>
    </main>

    <footer class="landing-footer">
      <div class="landing-inner footer-inner">
        <RouterLink class="brand footer-brand" to="/">
          <TradeCentralMark :size="26" />
          <span class="wordmark"
            ><strong>TradeCentral</strong><small>Research instrument</small></span
          >
        </RouterLink>
        <p>Research only · No execution · No investment advice</p>
        <nav aria-label="Footer links">
          <a href="#product">Product</a>
          <a href="#method">Method</a>
          <RouterLink :to="{ name: 'auth', query: { mode: 'signin', redirect: '/flow' } }"
            >Sign in</RouterLink
          >
        </nav>
      </div>
    </footer>
  </div>
</template>

<style scoped>
:global(body.edge-public-mode) {
  overflow: auto !important;
  overflow-x: hidden !important;
  background: var(--void);
}
:global(body.edge-public-mode #app),
:global(body.edge-public-mode .shell) {
  height: auto !important;
  min-height: 100vh;
  overflow: visible !important;
}
:global(body.edge-public-mode .shell) {
  display: block !important;
}
:global(body.edge-public-mode .rail),
:global(body.edge-public-mode .strip),
:global(body.edge-public-mode .foot),
:global(body.edge-public-mode .skip-link) {
  display: none !important;
}
:global(body.edge-public-mode .stage) {
  display: block !important;
  width: 100% !important;
  height: auto !important;
  min-height: 100vh !important;
  padding: 0 !important;
  overflow: visible !important;
}

.landing-page {
  position: relative;
  z-index: 3;
  min-height: 100vh;
  color: var(--ink);
  background: var(--void);
  font-family: var(--font-ui);
}

.landing-inner {
  width: min(1240px, calc(100% - 72px));
  margin-inline: auto;
}

/* ── topbar ─────────────────────────────────────────────────────────────── */
.topbar-shell {
  position: sticky;
  z-index: 20;
  top: 0;
  border-bottom: var(--hair) solid var(--rule);
  background: rgba(8, 9, 12, 0.82);
  backdrop-filter: blur(18px);
}
.topbar {
  min-height: 72px;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 11px;
  color: var(--ink);
}
.brand:hover {
  text-decoration: none;
}
.brand-mark {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  color: var(--phosphor);
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  transition: border-color var(--dur) var(--ease-out);
}
.brand:hover .brand-mark {
  border-color: var(--phosphor);
}
.wordmark {
  display: grid;
  line-height: 1;
}
.wordmark strong {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.02em;
}
.wordmark small {
  margin-top: 6px;
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: 8px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.topnav {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
}
.topnav a,
.sign-in {
  color: var(--ink-soft);
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 500;
}
.topnav a {
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
}
.topnav a small {
  color: var(--ink-ghost);
  font-family: var(--font-data);
  font-size: 7px;
}
.topnav a:hover,
.sign-in:hover {
  color: var(--ink);
  background: var(--panel-hi);
  text-decoration: none;
}
.top-actions {
  justify-self: end;
  display: flex;
  align-items: center;
  gap: 18px;
}
.sign-in {
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  padding: 0 3px;
}

.button {
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 0 20px;
  border: var(--hair) solid transparent;
  border-radius: var(--r-sm);
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.01em;
  transition:
    transform var(--dur-fast),
    background var(--dur-fast),
    border-color var(--dur-fast),
    color var(--dur-fast);
}
.button:hover {
  text-decoration: none;
  transform: translateY(-1px);
}
.button:active {
  transform: translateY(0);
}
.button-accent {
  color: var(--void);
  background: var(--phosphor);
}
.button-accent:hover {
  background: var(--phosphor-dim);
}
.button-quiet {
  color: var(--ink);
  border-color: var(--rule-hi);
  background: transparent;
}
.button-quiet:hover {
  color: var(--phosphor);
  border-color: var(--phosphor);
}
.btn-chevron {
  transition: transform var(--dur-fast) var(--ease-out);
}
.button:hover .btn-chevron {
  transform: translateX(2px);
}
.link-chevron {
  display: inline-block;
  transition: transform var(--dur-fast) var(--ease-out);
}
.text-link:hover .link-chevron {
  transform: translateX(2px);
}
.boundary-icon {
  flex-shrink: 0;
  color: var(--phosphor);
}

/* ── magnetic button wrapper ────────────────────────────────────────────── */
.magnetic-wrap {
  display: inline-flex;
  will-change: transform;
}
.magnetic-center {
  display: inline-flex;
  margin-top: 30px;
}

/* ── ticker tape ─────────────────────────────────────────────────────────── */
.ticker-tape {
  position: relative;
  overflow: hidden;
  border-bottom: var(--hair) solid var(--rule);
  background: var(--void-lift);
  height: 34px;
  display: flex;
  align-items: center;
}
.ticker-tape::before,
.ticker-tape::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  width: 60px;
  z-index: 2;
  pointer-events: none;
}
.ticker-tape::before {
  left: 0;
  background: linear-gradient(to right, var(--void-lift), transparent);
}
.ticker-tape::after {
  right: 0;
  background: linear-gradient(to left, var(--void-lift), transparent);
}
.ticker-track {
  display: flex;
  gap: 0;
  width: max-content;
  animation: ticker-scroll 40s linear infinite;
}
.ticker-row {
  display: flex;
  align-items: center;
  gap: 0;
  flex: 0 0 auto;
}
.ticker-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 20px;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  border-right: var(--hair) solid var(--rule);
}
.ticker-sym {
  color: var(--ink);
  font-weight: 700;
}
.ticker-sep {
  color: var(--ink-ghost);
}
.ticker-price {
  color: var(--ink-soft);
}
.ticker-chg {
  font-weight: 600;
}
.ticker-chg.pos {
  color: var(--long);
}
.ticker-chg.neg {
  color: var(--short);
}
.ticker-chg.flat {
  color: var(--ink-dim);
}
@keyframes ticker-scroll {
  from {
    transform: translateX(0);
  }
  to {
    transform: translateX(-50%);
  }
}

/* ── hero ────────────────────────────────────────────────────────────────── */
.hero {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(480px, 1.1fr);
  align-items: center;
  gap: clamp(48px, 6vw, 88px);
  min-height: 640px;
  padding-block: 72px;
}
.hero::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px);
  background-size: 40px 40px;
  mask-image: linear-gradient(to right, transparent 0, #000 55%, #000 100%);
}
.hero-copy,
.hero-visual {
  position: relative;
  z-index: 1;
}
.hero-visual {
  min-width: 0;
  width: 100%;
}
.hero-eyebrow,
.section-index {
  font-family: var(--font-data);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.hero-eyebrow {
  display: flex;
  align-items: center;
  gap: 11px;
  color: var(--ink-dim);
}
.hero-eyebrow span {
  width: 25px;
  height: 2px;
  background: var(--phosphor);
}

.hero-headline {
  margin-top: 24px;
  font-family: var(--font-display);
  font-size: clamp(48px, 5.4vw, 76px);
  font-weight: 600;
  line-height: 1;
  letter-spacing: -0.04em;
}
.hero-headline .word {
  display: inline-block;
}
.hero-headline .word.em {
  color: var(--phosphor);
}

.hero-lede {
  margin-top: 26px;
  max-width: 54ch;
  color: var(--ink-soft);
  font-family: var(--font-ui);
  font-size: 16px;
  line-height: 1.7;
}
.rotating-word {
  display: inline-flex;
  position: relative;
  height: 1.5em;
  vertical-align: bottom;
  overflow: hidden;
  min-width: 140px;
}
.rw-item {
  position: absolute;
  left: 0;
  top: 0;
  color: var(--phosphor);
  font-weight: 600;
  white-space: nowrap;
  opacity: 0;
  transform: translateY(100%);
  transition:
    opacity 0.4s var(--ease-out),
    transform 0.4s var(--ease-out);
}
.rw-item.active {
  opacity: 1;
  transform: translateY(0);
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 34px;
}
.hero-boundary {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 26px;
  color: var(--ink-faint);
  font-family: var(--font-ui);
  font-size: 12px;
}
.hero-boundary strong {
  color: var(--ink-soft);
  font-weight: 600;
}
.hero-warn-note {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 54ch;
  color: var(--warn);
  font-family: var(--font-data);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.hero-warn-note::before {
  content: '';
  width: 6px;
  height: 6px;
  background: var(--warn);
  border-radius: 1px;
  flex: 0 0 auto;
}

/* ── hero instrument frame (animated SVG) ────────────────────────────────── */
.instrument-frame {
  position: relative;
  margin: 0;
  padding: 17px 19px 14px;
  overflow: hidden;
  color: var(--ink);
  border: var(--hair) solid var(--rule-hi);
  border-top: 2px solid var(--phosphor);
  background:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px), var(--panel);
  background-size: 28px 28px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
}
.instrument-frame::before,
.instrument-frame::after {
  content: '';
  position: absolute;
  z-index: 4;
  width: 13px;
  height: 13px;
  pointer-events: none;
}
.instrument-frame::before {
  top: -1px;
  left: -1px;
  border-top: 1px solid var(--ink);
  border-left: 1px solid var(--ink);
}
.instrument-frame::after {
  right: -1px;
  bottom: -1px;
  border-right: 1px solid var(--ink);
  border-bottom: 1px solid var(--ink);
}
.instrument-frame figcaption,
.instrument-frame footer {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: 8px;
  font-weight: 650;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.instrument-frame figcaption {
  justify-content: space-between;
  padding-bottom: 10px;
  border-bottom: var(--hair) solid var(--rule);
}
.fig-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink);
}
.fig-label .app-icon {
  color: var(--phosphor);
}
.fig-state {
  color: var(--ink-faint);
}
.instrument-stage {
  position: relative;
  margin-top: 8px;
  border: var(--hair) solid var(--rule);
  background: rgba(8, 9, 12, 0.6);
  overflow: hidden;
}
.hero-svg {
  display: block;
  width: 100%;
  height: auto;
  min-height: 380px;
}
.hero-svg-grid path {
  fill: none;
  stroke: var(--rule);
  stroke-width: 1;
}

/* ── Vol surface mesh ────────────────────────────────────────────────────── */
.hero-svg-surface-ribbon {
  fill: var(--call-wash);
  stroke: none;
}
.hero-svg-mesh-line {
  fill: none;
  stroke: var(--call);
  stroke-width: 0.8;
  vector-effect: non-scaling-stroke;
  opacity: 0.35;
}
.hero-svg-contour {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1.2;
  vector-effect: non-scaling-stroke;
  opacity: 0.5;
  stroke-dasharray: 3 4;
}

/* ── GEX bars ─────────────────────────────────────────────────────────────── */
.hero-svg-bar {
  fill: var(--call);
}
.hero-svg-bar.put {
  fill: var(--put);
}
.hero-svg-zero {
  stroke: var(--ink-faint);
  stroke-width: 1;
  stroke-dasharray: 4 4;
}
.hero-svg-flip {
  stroke: var(--put);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}

/* ── MC fan paths ─────────────────────────────────────────────────────────── */
.hero-svg-mc-path {
  fill: none;
  stroke: var(--phosphor-dim);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.hero-svg-histogram {
  fill: var(--phosphor-wash);
  stroke: var(--phosphor-dim);
  stroke-width: 0.5;
  vector-effect: non-scaling-stroke;
  opacity: 0.7;
}

/* ── Density curve ────────────────────────────────────────────────────────── */
.hero-svg-density-area {
  fill: var(--phosphor-glow);
  stroke: none;
  opacity: 0.4;
}
.hero-svg-trace {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1.8;
  vector-effect: non-scaling-stroke;
  stroke-dasharray: 1200;
  stroke-dashoffset: 0;
}

/* ── Range + median lines ─────────────────────────────────────────────────── */
.hero-svg-range {
  stroke: var(--ink-dim);
  stroke-width: 1;
  stroke-dasharray: 2 3;
  opacity: 0.5;
}
.hero-svg-median {
  stroke: var(--phosphor);
  stroke-width: 1;
  stroke-dasharray: 4 4;
  opacity: 0.4;
}

/* ── Labels + corners ────────────────────────────────────────────────────── */
.hero-svg-label {
  fill: var(--ink-faint);
  font-family: var(--font-data);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.hero-svg-label.dim {
  fill: var(--ink-ghost);
}
.hero-svg-corner {
  fill: none;
  stroke: var(--ink-soft);
  stroke-width: 1.5;
}

/* ── Axis annotations ────────────────────────────────────────────────────── */
.axis-label {
  position: absolute;
  left: 22px;
  color: var(--ink-soft);
  font-family: var(--font-data);
  font-size: 8px;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.axis-label::before {
  content: '';
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 6px;
}
.axis-vol {
  top: 24px;
}
.axis-vol::before {
  background: var(--call);
}
.axis-gex {
  top: 240px;
}
.axis-gex::before {
  background: var(--call);
}
.axis-mc {
  top: 300px;
}
.axis-mc::before {
  background: var(--phosphor);
}
.instrument-frame footer {
  justify-content: flex-start;
  gap: 14px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: var(--hair) solid var(--rule);
}
.fig-legend {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--ink-soft);
}
.fig-legend i {
  display: inline-block;
  width: 7px;
  height: 7px;
}
.leg-mesh {
  background: var(--call);
  opacity: 0.4;
}
.leg-call {
  background: var(--call);
}
.leg-put {
  background: var(--put);
}
.leg-trace {
  border: 1px solid var(--phosphor);
}
.instrument-frame footer strong {
  margin-left: auto;
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: 8px;
  font-weight: 500;
}

/* ── stats ────────────────────────────────────────────────────────────────── */
.stats-section {
  border-top: var(--hair) solid var(--rule);
  border-bottom: var(--hair) solid var(--rule);
  background: var(--void-lift);
}
.stats-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
}
.stats-strip :deep(.readout) {
  padding: 22px 24px;
  border-left: var(--hair) solid var(--rule);
}
.stats-strip :deep(.readout:first-child) {
  border-left: 0;
  padding-left: 0;
}

/* ── live proof ───────────────────────────────────────────────────────────── */
.live-proof-section {
  border-bottom: var(--hair) solid var(--rule);
  background: var(--void);
}

/* ── product / bento grid ─────────────────────────────────────────────────── */
.product-section,
.workspace-section,
.method-section,
.evidence-section {
  scroll-margin-top: 72px;
}
.product-section {
  padding-block: 104px;
}
.section-heading {
  display: grid;
  grid-template-columns: 1fr minmax(300px, 0.6fr);
  gap: 80px;
  align-items: end;
}
.section-index {
  color: var(--phosphor);
}
.section-heading h2,
.flow-copy h2,
.workspace-copy h2,
.final-inner h2 {
  margin-top: 16px;
  font-family: var(--font-display);
  font-size: clamp(40px, 4.4vw, 60px);
  font-weight: 600;
  line-height: 1.05;
  letter-spacing: -0.035em;
}
.section-heading > p,
.flow-copy > p:not(.section-index),
.workspace-copy > p:not(.section-index) {
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: 15px;
  line-height: 1.7;
}
.bento-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-top: 60px;
}
.bento-card {
  border-top: 1px solid var(--rule-hi);
  transition: border-color var(--dur) var(--ease-out);
}
.bento-card:hover {
  border-top-color: var(--phosphor);
}
.bento-card.span-wide {
  grid-column: span 2;
  border-top-color: var(--call);
}
.bento-card.span-tall {
  grid-row: span 2;
  border-top-color: var(--put);
}
.card-spotlight-target,
.principle-inner {
  position: relative;
}
.card-spotlight-target::before,
.principle-inner::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: radial-gradient(
    200px circle at var(--card-x, 50%) var(--card-y, 0%),
    var(--phosphor),
    transparent 70%
  );
  opacity: 0;
  transition: opacity 0.3s var(--ease-out);
  pointer-events: none;
}
.card-spotlight-target:hover::before,
.principle-inner:hover::before {
  opacity: 0.7;
}
.capability-copy {
  margin-top: 14px;
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: 13px;
  line-height: 1.65;
}
.capability-stat {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16px;
  padding-top: 12px;
  border-top: var(--hair) solid var(--rule);
}
.capability-stat .stat-label {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.capability-stat .stat-val {
  color: var(--phosphor);
  font-family: var(--font-data);
  font-size: var(--t-fig);
  font-weight: 600;
}

/* ── flow section ─────────────────────────────────────────────────────────── */
.flow-section {
  padding-block: 104px;
  border-top: var(--hair) solid var(--rule);
  background: var(--void-lift);
}
.flow-layout {
  display: grid;
  grid-template-columns: minmax(280px, 0.42fr) minmax(560px, 1fr);
  gap: clamp(48px, 6vw, 88px);
  align-items: center;
}
.flow-copy {
  align-self: start;
  padding-top: 12px;
}
.flow-copy .section-index {
  color: var(--call);
}
.flow-copy > p:not(.section-index) {
  margin-top: 22px;
}
.text-link {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-top: 28px;
  color: var(--ink);
  font-family: var(--font-ui);
  font-size: 13px;
  font-weight: 600;
}
.text-link:hover {
  color: var(--phosphor);
  text-decoration: none;
}

/* ── workspaces ───────────────────────────────────────────────────────────── */
.workspace-section {
  padding-block: 104px;
  border-top: var(--hair) solid var(--rule);
}
.workspace-layout {
  display: grid;
  grid-template-columns: minmax(270px, 0.42fr) minmax(620px, 1fr);
  gap: clamp(48px, 6vw, 88px);
  align-items: center;
}
.workspace-copy {
  align-self: start;
  padding-top: 12px;
}
.workspace-copy .section-index {
  color: var(--call);
}
.workspace-copy > p:not(.section-index) {
  margin-top: 22px;
}

/* ── evidence / tracing beam pipeline ────────────────────────────────────── */
.evidence-section {
  padding-block: 104px;
  border-top: var(--hair) solid var(--rule);
  background: var(--void-lift);
}
.evidence-heading {
  align-items: center;
}
.evidence-heading .section-index {
  color: var(--put);
}
.tracing-beam-wrap {
  position: relative;
  display: flex;
  gap: 32px;
  margin-top: 56px;
}
.tracing-beam-rail {
  position: relative;
  width: 2px;
  flex: 0 0 auto;
  background: var(--rule);
  border-radius: 1px;
  overflow: hidden;
}
.beam-fill {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 0%;
  background: var(--phosphor);
  border-radius: 1px;
}
.pipeline {
  display: flex;
  align-items: stretch;
  gap: 0;
  flex: 1 1 auto;
}
.pipeline-step {
  display: flex;
  align-items: center;
  flex: 1 1 0;
  min-width: 0;
}
.pipeline-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 20px 12px;
  width: 100%;
  text-align: center;
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel);
  transition: border-color var(--dur) var(--ease-out);
}
.pipeline-step.done .pipeline-node {
  border-color: var(--phosphor);
}
.pipeline-step.done .pipeline-icon {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}
.pipeline-idx {
  font-family: var(--font-data);
  font-size: 8px;
  font-weight: 600;
  color: var(--ink-ghost);
  letter-spacing: 0.08em;
}
.pipeline-icon {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  color: var(--phosphor);
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  transition:
    color var(--dur) var(--ease-out),
    border-color var(--dur) var(--ease-out),
    background var(--dur) var(--ease-out);
}
.pipeline-icon svg {
  display: block;
}
.pipeline-step:hover .pipeline-icon {
  border-color: var(--phosphor);
  background: var(--panel-hi);
}
.pipeline-label {
  color: var(--ink);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.06em;
}
.pipeline-step.done .pipeline-label {
  color: var(--phosphor);
}
.pipeline-note {
  color: var(--ink-faint);
  font-family: var(--font-ui);
  font-size: 10px;
  font-style: normal;
  line-height: 1.4;
}
.pipeline-connector {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  min-width: 32px;
}
.connector-line {
  position: absolute;
  inset: 0;
  top: 50%;
  bottom: 50%;
  height: 1px;
  background: var(--rule-hi);
}
.connector-arrow {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  color: var(--phosphor-dim);
  background: var(--void-lift);
}
.pipeline-step.done ~ .pipeline-connector .connector-arrow {
  color: var(--phosphor);
}

/* ── method ───────────────────────────────────────────────────────────────── */
.method-section {
  padding-block: 104px;
  border-top: var(--hair) solid var(--rule);
  background: var(--void-lift);
}
.method-heading {
  align-items: center;
}
.method-heading .section-index {
  color: var(--warn);
}
.principle-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-top: 56px;
}
.principle-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  margin-bottom: 12px;
  color: var(--phosphor);
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  transition:
    color var(--dur) var(--ease-out),
    border-color var(--dur) var(--ease-out),
    background var(--dur) var(--ease-out);
}
.principle-icon svg {
  display: block;
}
.principle:hover .principle-icon {
  border-color: var(--phosphor);
  background: var(--panel-hi);
}
.principle-copy {
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: 12px;
  line-height: 1.6;
}

/* ── final CTA ────────────────────────────────────────────────────────────── */
.final-cta {
  position: relative;
  overflow: hidden;
  padding-block: 100px 92px;
  text-align: center;
  border-top: var(--hair) solid var(--rule);
  background: var(--void);
}
.final-cta::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px);
  background-size: 40px 40px;
  mask-image: radial-gradient(ellipse at center, #000 0%, transparent 70%);
}
.final-inner {
  position: relative;
}
.final-inner .section-index {
  color: var(--call);
}
.final-inner h2 {
  margin-top: 18px;
}
.final-inner h2 em {
  font-family: var(--font-serif);
  font-style: italic;
  font-weight: 500;
  letter-spacing: -0.01em;
}
.final-inner > p:not(.section-index) {
  margin-top: 20px;
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: 15px;
}
.final-inner small {
  display: block;
  margin-top: 16px;
  color: var(--ink-faint);
  font-family: var(--font-ui);
  font-size: 11px;
}

/* ── footer ────────────────────────────────────────────────────────────────── */
.landing-footer {
  border-top: var(--hair) solid var(--rule);
  background: var(--void-lift);
}
.footer-inner {
  min-height: 84px;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 28px;
}
.footer-brand {
  color: var(--ink);
}
.footer-inner > p {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: 8px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.footer-inner nav {
  justify-self: end;
  display: flex;
  align-items: center;
  gap: 24px;
}
.footer-inner nav a {
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: 12px;
}
.footer-inner nav a:hover {
  color: var(--ink);
  text-decoration: none;
}

/* ── responsive ───────────────────────────────────────────────────────────── */
@media (max-width: 1080px) {
  .hero {
    grid-template-columns: 1fr;
    min-height: auto;
    padding-block: 60px;
  }
  .hero-copy {
    max-width: 720px;
  }
  .hero-visual {
    max-width: 640px;
  }
  .stats-strip {
    grid-template-columns: repeat(2, 1fr);
  }
  .stats-strip :deep(.readout:nth-child(3)) {
    border-left: 0;
  }
  .flow-layout,
  .workspace-layout {
    grid-template-columns: 1fr;
  }
  .flow-copy,
  .workspace-copy {
    max-width: 640px;
  }
  .principle-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .bento-grid {
    grid-template-columns: 1fr;
  }
  .bento-card.span-wide,
  .bento-card.span-tall {
    grid-column: auto;
    grid-row: auto;
  }
  .pipeline {
    flex-wrap: wrap;
    gap: 12px;
  }
  .pipeline-step {
    flex: 1 1 45%;
  }
  .pipeline-connector {
    display: none;
  }
  .tracing-beam-wrap {
    flex-direction: column;
    gap: 20px;
  }
  .tracing-beam-rail {
    width: 100%;
    height: 2px;
  }
  .beam-fill {
    height: 100%;
    width: 0%;
  }
}

@media (max-width: 800px) {
  .landing-inner {
    width: min(100% - 40px, 1240px);
  }
  .topbar {
    grid-template-columns: 1fr auto;
  }
  .topnav {
    display: none;
  }
  .hero h1 {
    font-size: clamp(44px, 11vw, 68px);
  }
  .section-heading {
    grid-template-columns: 1fr;
    gap: 26px;
  }
  .capability-grid {
    grid-template-columns: 1fr;
  }
  .pipeline-step {
    flex: 1 1 100%;
  }
  .footer-inner {
    grid-template-columns: 1fr auto;
  }
  .footer-inner > p {
    display: none;
  }
}

@media (max-width: 580px) {
  .landing-inner {
    width: min(100% - 30px, 1240px);
  }
  .topbar {
    min-height: 64px;
    grid-template-columns: 1fr auto;
    gap: 14px;
  }
  .wordmark small {
    display: none;
  }
  .brand-mark {
    width: 34px;
    height: 34px;
  }
  .top-actions {
    gap: 0;
  }
  .top-actions .sign-in {
    display: none;
  }
  .button {
    min-height: 40px;
    padding-inline: 16px;
    font-size: 11px;
  }
  .hero {
    gap: 44px;
    padding-block: 48px;
  }
  .hero h1 {
    font-size: 40px;
    line-height: 1.04;
  }
  .hero-lede {
    font-size: 14px;
  }
  .rotating-word {
    min-width: 110px;
  }
  .hero-actions {
    display: grid;
  }
  .hero-actions .button,
  .hero-actions .magnetic-wrap {
    width: 100%;
  }
  .hero-actions .button {
    width: 100%;
  }
  .stats-strip {
    grid-template-columns: 1fr;
  }
  .stats-strip :deep(.readout),
  .stats-strip :deep(.readout:first-child) {
    padding: 18px 0;
    border-left: 0;
    border-top: var(--hair) solid var(--rule);
  }
  .stats-strip :deep(.readout:first-child) {
    border-top: 0;
  }
  .product-section,
  .flow-section,
  .workspace-section,
  .method-section,
  .evidence-section {
    padding-block: 76px;
  }
  .section-heading h2,
  .flow-copy h2,
  .workspace-copy h2,
  .final-inner h2 {
    font-size: clamp(36px, 11vw, 50px);
  }
  .principle-grid {
    grid-template-columns: 1fr;
  }
  .final-cta {
    padding-block: 76px 72px;
  }
  .footer-inner {
    min-height: 104px;
    grid-template-columns: 1fr;
    padding-block: 20px;
  }
  .footer-inner nav {
    justify-self: start;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ticker-track {
    animation: none !important;
  }
  .rw-item {
    transition: none !important;
  }
  .card-spotlight-target::before,
  .principle-inner::before {
    display: none;
  }
}
</style>
