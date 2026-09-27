<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref } from 'vue'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { type MarketClock, type Readiness, type StatusPayload } from '@/api'
import { type Resource } from '@/composables/useResource'
import { num, DASH } from '@/format'

import AppIcon from '@/components/AppIcon.vue'
import BsLab from '@/components/BsLab.vue'
import FlowSignatureDiagram from '@/components/FlowSignatureDiagram.vue'
import GexFlowVisual from '@/components/GexFlowVisual.vue'
import McLiveHero from '@/components/McLiveHero.vue'
import PrincipleDiagram from '@/components/PrincipleDiagram.vue'
import TradeCentralMark from '@/components/TradeCentralMark.vue'
import PayoffPlate from '@/components/PayoffPlate.vue'
import optionsPositioningCapture from '@/assets/showcase/options-positioning.png'

import { impliedRange } from '@/charts/landing-math'

gsap.registerPlugin(ScrollTrigger)

/**
 * Public product overview — editorial "paper" system.
 *
 * The page follows a warm off-white, hairline-framed editorial layout: a
 * bordered masthead, a railroad frame of 1px vertical rules around the
 * content column, oversized tight grotesque headlines, near-black buttons
 * with pixel arrows, orange/yellow accents, and navy bands for the evidence
 * and closing sections. Blocks fall into place; the headline decodes.
 *
 * Market figures, when available to an authenticated operator, come from the
 * same resources as the operator shell. Public visitors do not trigger market
 * data requests. Product diagrams carry only labels and system boundaries;
 * there are no illustrative quotes, returns, or invented model scores.
 *
 * The hero is a LIVE Monte Carlo simulation (McLiveHero): GBM paths draw in
 * batch by batch while their terminal histogram accumulates against the
 * closed-form lognormal density. Below, an interactive Black-Scholes
 * workbench (BsLab) lets a visitor drag volatility/expiry/strike and watch
 * real Greeks respond. Scroll animation is driven by GSAP; the scramble and
 * fall-in entrances are rAF/IntersectionObserver. The workstation tab shows a
 * capture from an actual local research session.
 */
const status = inject<Resource<StatusPayload>>('status')!
const readiness = inject<Resource<Readiness>>('readiness')!
const clock = inject<Resource<MarketClock>>('marketClock')!

const session = computed(() => {
  switch (clock.data.value?.market_session) {
    case 'premarket':
      return 'PREMARKET'
    case 'regular':
      return 'REGULAR'
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

const universe = computed(() => num(status.data.value?.broad_universe_count, 0))
const gates = computed(() => readiness.data.value?.gates_summary ?? null)
const shadow = computed(() => {
  const value = readiness.data.value?.shadow
  if (!value) return DASH
  return `${num(value.n_sessions, 0)} / ${num(value.required, 0)}`
})

/* ── Interactive view modes for hero and flow visual banners ────────────── */
const heroViewMode = ref<'mc' | 'workstation'>('workstation')

/* ── Rotating word in the hero lede ────────────────────────────────────────── */
/* The rotating slot is sized to the longest of these and never resizes (see
   .rotating-word), so keeping them within a few characters of each other
   keeps the trailing gap down to ordinary word spacing. */
const ROTATING_WORDS = ['dealer gamma', 'signed flow', 'implied range', 'gamma flip'] as const
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

/* ── Hero headline scramble-decode (settles left to right) ───────────────────
   Deterministic charset, rAF-driven, second line trails the first. The final
   headline always lives in the h1's aria-label; the animated spans are
   aria-hidden so assistive tech never reads the churn. */
const HERO_LINES = ['Read the positioning', 'before the narrative.'] as const
const heroAriaLabel = HERO_LINES.join(' ')
const SCRAMBLE_CHARS = '01<>/[]{}#$%&*+=~ABCDEFGHIJKLMNOPQRSTUVWXYZ'
const scrambledLines = ref<string[]>([...HERO_LINES])
let scrambleRaf = 0

function runScramble(): void {
  const started = performance.now()
  const churnMs = 850
  const staggerMs = 380
  const step = (now: number): void => {
    let settledAll = true
    scrambledLines.value = HERO_LINES.map((target, li) => {
      const elapsed = now - started - li * staggerMs
      const progress = Math.min(1, Math.max(0, elapsed / churnMs))
      if (progress >= 1) return target
      settledAll = false
      const settled = Math.floor(progress * target.length)
      let out = target.slice(0, settled)
      for (let i = settled; i < target.length; i += 1) {
        out +=
          target[i] === ' '
            ? ' '
            : SCRAMBLE_CHARS[(settled * 31 + i * 17 + Math.floor(now / 45)) % SCRAMBLE_CHARS.length]
      }
      return out
    })
    if (!settledAll) scrambleRaf = requestAnimationFrame(step)
  }
  scrambleRaf = requestAnimationFrame(step)
}

/* ── Fall-in entrance for bento blocks (IntersectionObserver gated) ────────── */
let fallObserver: IntersectionObserver | undefined

function wireFallIns(reducedMotion: boolean): void {
  const blocks = document.querySelectorAll('.fall-in')
  if (reducedMotion || typeof IntersectionObserver === 'undefined') {
    blocks.forEach((el) => el.classList.add('in-view'))
    return
  }
  fallObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add('in-view')
          fallObserver?.unobserve(entry.target)
        }
      }
    },
    { threshold: 0.05, rootMargin: '100px 0px' },
  )
  blocks.forEach((el) => fallObserver?.observe(el))
}

/* ── Content data ──────────────────────────────────────────────────────────── */
const capabilities = [
  {
    kind: 'market' as const,
    icon: 'radar',
    area: 'market',
    title: 'Market structure',
    copy: 'Search a broad US equity universe, compare trajectories, inspect sector rotation, and keep source freshness visible.',
    detail: 'Price · regimes · sectors · outliers',
    stat: 'Broad universe',
    statValue: () => universe.value,
  },
  {
    kind: 'options' as const,
    icon: 'options',
    area: 'options',
    title: 'Options & flow',
    copy: 'Read positioning, gamma topology, implied ranges, unusual activity, and signed-flow coverage without collapsing them into one score.',
    detail: 'GEX · flow · ranges · contract context',
    stat: 'Gates cleared',
    statValue: () => num(gates.value?.go, 0),
  },
  {
    kind: 'governance' as const,
    icon: 'gate',
    area: 'governance',
    title: 'Research governance',
    copy: 'Trace every claim back to point-in-time tests, pre-registered gates, run artifacts, and explicit shadow evidence.',
    detail: 'Methods · diagnostics · gates · ledgers',
    stat: 'Shadow sessions',
    statValue: () => shadow.value,
  },
] as const

const flowFeatures = [
  {
    kind: 'gex' as const,
    idx: '01 · GEX PROFILE',
    title: 'Where dealers are pinned',
    copy: 'Gamma concentration by strike, with the sign flip marked: the level above which hedging damps a move and below which it feeds one.',
  },
  {
    kind: 'signed' as const,
    idx: '02 · SIGNED TAPE',
    title: 'Who hit the offer',
    copy: 'Prints split into buyer- and seller-initiated flow. When the provider gives no side, the print stays unsigned instead of being guessed.',
  },
  {
    kind: 'execution' as const,
    idx: '03 · SWEEPS & BLOCKS',
    title: 'How the order was worked',
    copy: 'Intermarket sweeps taking four venues at once, told apart from a single block resting on one exchange.',
  },
] as const

const principles = [
  {
    index: 'A',
    kind: 'missing' as const,
    title: 'A gap stays a gap',
    copy: 'Stale, unavailable, and proxied values are labelled where you read them. Nothing gets quietly filled with a zero that looks like a real number.',
  },
  {
    index: 'B',
    kind: 'typed' as const,
    title: 'Evidence keeps its type',
    copy: 'A strong ordinal reading is shown as a strong ordinal reading, never dressed up as a calibrated probability or a green light to trade.',
  },
  {
    index: 'C',
    kind: 'failclosed' as const,
    title: 'Promotion fails closed',
    copy: 'Readiness and pre-registered gates both have to clear before a strategy leaves research. One no-go holds the whole thing.',
  },
  {
    index: 'D',
    kind: 'outside' as const,
    title: 'Execution stays outside',
    copy: 'No order ticket, no broker link, no submission route anywhere in the checked-in pipeline. You place trades in your own broker.',
  },
] as const

/* ── Structural model parameters ──────────────────────────────────────────────
   The hero Monte Carlo and the WebGL vol surface share these constants so the
   whole page describes ONE coherent model world. Labels on every figure mark
   them as structural anatomy — live values appear only after sign-in. */
const MC = { S0: 100, sigma: 0.3, T: 0.25, mu: 0.08, r: 0.05, q: 0, totalPaths: 140, seed: 7 }

const heroRange = computed(() => impliedRange(MC.S0, MC.T, MC.sigma, MC.r, MC.q))

const landingNavOpen = ref(false)

/* ── GSAP animation orchestration ─────────────────────────────────────────── */
let ctx: gsap.Context | undefined

onMounted(() => {
  document.body.classList.add('edge-public-mode')

  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  /* GSAP context scopes all animations so ctx.revert() cleans up everything */
  ctx = gsap.context(() => {
    /* The masthead hardens once content has scrolled beneath it. Registered
       before the Reduce Motion guard: it is a material state, not motion,
       so it applies either way. The class flip keeps the scoped tokens the
       single source of truth for the appearance. */
    ScrollTrigger.create({
      start: 40,
      onToggle: ({ isActive }) => {
        document.querySelector('.masthead')?.classList.toggle('is-scrolled', isActive)
      },
    })

    if (prefersReducedMotion) return

    /* ── Hero copy fades in beside the decoding headline ─────────────────── */
    gsap.from(
      '.hero-eyebrow, .hero-lede, .hero-actions, .hero-try-note, .hero-boundary, .hero-warn-note',
      {
        y: 12,
        duration: 0.45,
        stagger: 0.07,
        ease: 'power3.out',
        delay: 0.2,
      },
    )

    /* ── Hero instrument frame draws in ───────────────────────────────────── */
    gsap.from('.hero-visual .instrument-frame', {
      y: 26,
      duration: 0.8,
      delay: 0.45,
      ease: 'power2.out',
    })

    /* ── Section reveals via ScrollTrigger ───────────────────────────────── */
    gsap.utils.toArray<HTMLElement>('.gsap-reveal').forEach((el) => {
      gsap.from(el, {
        opacity: 0,
        y: 20,
        duration: 0.55,
        ease: 'power2.out',
        scrollTrigger: {
          trigger: el,
          start: 'top 92%',
          toggleActions: 'play none none none',
          once: true,
        },
      })
    })
  })

  if (!prefersReducedMotion) runScramble()
  wireFallIns(prefersReducedMotion)
  startRotating()
  setTimeout(() => {
    ScrollTrigger.refresh()
  }, 100)
})

onUnmounted(() => {
  document.body.classList.remove('edge-public-mode')
  ctx?.revert()
  cancelAnimationFrame(scrambleRaf)
  fallObserver?.disconnect()
  stopRotating()
})
</script>

<template>
  <div class="landing-page">
    <!-- ── masthead: bordered cream toolbar ────────────────────────────────── -->
    <header class="masthead">
      <div class="masthead-inner">
        <RouterLink class="brand" to="/">
          <span class="brand-mark"><TradeCentralMark :size="24" /></span>
          <span class="wordmark">
            <strong>TradeCentral</strong>
            <small>Quantitative research instrument</small>
          </span>
        </RouterLink>

        <nav
          id="landing-topnav"
          class="masthead-nav"
          :class="{ 'is-open': landingNavOpen }"
          aria-label="Product overview"
        >
          <a href="#product" @click="landingNavOpen = false">Product</a>
          <a href="#flow" @click="landingNavOpen = false">Flow</a>
          <a href="#method" @click="landingNavOpen = false">Method</a>
        </nav>

        <div class="masthead-actions">
          <button
            type="button"
            class="nav-menu-btn"
            :aria-expanded="landingNavOpen"
            aria-controls="landing-topnav"
            aria-label="Product sections"
            @click="landingNavOpen = !landingNavOpen"
          >
            <AppIcon name="density" :size="16" />
          </button>
          <RouterLink
            class="sign-in"
            :to="{ name: 'auth', query: { mode: 'signin', redirect: '/flow' } }"
          >
            Sign in
          </RouterLink>
          <RouterLink
            class="button button-primary"
            :to="{ name: 'waitlist', query: { redirect: '/flow' } }"
          >
            Join now
            <svg
              class="px-arrow"
              width="20"
              height="20"
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden="true"
            >
              <rect x="1" y="8" width="10" height="4" />
              <rect x="11" y="4" width="4" height="4" />
              <rect x="11" y="12" width="4" height="4" />
              <rect x="15" y="8" width="4" height="4" />
            </svg>
          </RouterLink>
        </div>
      </div>
    </header>

    <!-- ── railroad: the framed content column ─────────────────────────────── -->
    <main class="railroad">
      <!-- ── HERO: decoding headline over the live Monte Carlo instrument ──── -->
      <section class="hero section-pad">
        <div class="hero-copy">
          <p class="hero-eyebrow">
            <i class="eyebrow-tick" aria-hidden="true" />US equities · Options intelligence
          </p>

          <!-- The settled line is rendered (hidden) to hold the box, and the
               churning copy is painted over it. Scramble glyphs are wider
               than the lowercase they stand in for, so letting the churn size
               the headline itself rewrapped it mid-animation and shifted the
               entire hero — the page's whole remaining CLS budget. -->
          <h1 class="hero-headline" :aria-label="heroAriaLabel">
            <span
              v-for="(line, i) in HERO_LINES"
              :key="line"
              class="hero-line"
              :class="{ em: i === 1 }"
              aria-hidden="true"
            >
              <span class="hero-line-box">{{ line }}</span>
              <span class="hero-line-churn">{{ scrambledLines[i] }}</span>
            </span>
          </h1>

          <p class="hero-lede">
            Find a symbol and read the source and age of every figure on screen. One focused
            workspace for flow, positioning, and the research behind its
            <span class="rotating-word">
              <span
                v-for="(word, i) in ROTATING_WORDS"
                :key="word"
                class="rw-item"
                :class="{ active: i === rotatingIndex }"
                :aria-hidden="i !== rotatingIndex"
                >{{ word }}</span
              >
            </span>
          </p>

          <div class="hero-actions">
            <RouterLink
              class="button button-primary"
              :to="{ name: 'waitlist', query: { redirect: '/flow' } }"
            >
              Request operator access
              <svg
                class="px-arrow"
                width="20"
                height="20"
                viewBox="0 0 20 20"
                fill="currentColor"
                aria-hidden="true"
              >
                <rect x="1" y="8" width="10" height="4" />
                <rect x="11" y="4" width="4" height="4" />
                <rect x="11" y="12" width="4" height="4" />
                <rect x="15" y="8" width="4" height="4" />
              </svg>
            </RouterLink>
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
            <span><strong>Source-visible.</strong> No order routing. No performance promises.</span>
          </div>
        </div>

        <!-- ── actual workstation capture and interactive Monte Carlo ─────── -->
        <div class="hero-visual">
          <figure
            class="instrument-frame"
            aria-label="Actual options workstation capture and interactive Monte Carlo simulation"
          >
            <figcaption>
              <div class="fig-toggle-group" role="tablist" aria-label="Hero visual view">
                <button
                  type="button"
                  role="tab"
                  :aria-selected="heroViewMode === 'mc'"
                  class="fig-tab-btn"
                  :class="{ active: heroViewMode === 'mc' }"
                  @click="heroViewMode = 'mc'"
                >
                  <i class="fig-tick" aria-hidden="true" />LIVE SIMULATION
                </button>
                <button
                  type="button"
                  role="tab"
                  :aria-selected="heroViewMode === 'workstation'"
                  class="fig-tab-btn"
                  :class="{ active: heroViewMode === 'workstation' }"
                  @click="heroViewMode = 'workstation'"
                >
                  <i class="fig-tick" aria-hidden="true" />WORKSTATION
                </button>
              </div>
              <span class="fig-state">{{
                heroViewMode === 'mc'
                  ? `STRUCTURAL · 1σ [${heroRange.p1Low.toFixed(1)}–${heroRange.p1High.toFixed(1)}]`
                  : 'ACTUAL WORKSPACE · SPY'
              }}</span>
            </figcaption>

            <div v-if="heroViewMode === 'mc'" class="hero-mc-stage">
              <McLiveHero
                :s0="MC.S0"
                :sigma="MC.sigma"
                :maturity="MC.T"
                :mu="MC.mu"
                :r="MC.r"
                :q="MC.q"
                :total-paths="MC.totalPaths"
                :seed="MC.seed"
              />
            </div>

            <div v-else class="hero-desk-stage">
              <img
                :src="optionsPositioningCapture"
                alt="Actual TradeCentral options positioning view for SPY, showing gamma exposure by strike, dealer positioning, and source status"
                width="1200"
                height="750"
                decoding="async"
                fetchpriority="high"
              />
            </div>

            <footer>
              <template v-if="heroViewMode === 'mc'">
                <span class="fig-legend"><i class="leg-path" />GBM path</span>
                <span class="fig-legend"><i class="leg-hist" />Terminal hist.</span>
                <span class="fig-legend"><i class="leg-trace" />Lognormal φ</span>
                <span class="fig-legend"><i class="leg-med" />Median</span>
                <strong
                  >GBM · S₀={{ MC.S0 }} · σ={{ (MC.sigma * 100).toFixed(0) }}% · T={{
                    (MC.T * 12).toFixed(0)
                  }}M · N={{ MC.totalPaths }}</strong
                >
              </template>
              <template v-else>
                <span>Captured local research session · Sep 2026</span>
                <strong>Historical source context shown in app</strong>
                <a
                  class="capture-link"
                  :href="optionsPositioningCapture"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Open full size options positioning screenshot in a new tab"
                >
                  View full capture ↗
                </a>
              </template>
            </footer>
          </figure>
        </div>
      </section>

      <!-- ── PRODUCT: compact capability map ───────────────────────────────── -->
      <section id="product" class="bento-section section-pad">
        <header class="section-head gsap-reveal">
          <p class="section-eyebrow"><i class="eyebrow-tick" aria-hidden="true" />Product</p>
          <h2>Three evidence layers. Two ways in.</h2>
          <p class="section-lede">
            For researchers and active traders who want institutional discipline without a black-box
            confidence score. Every surface answers one question, names its source, and shows you an
            honest failure state when the data is not there.
          </p>
        </header>

        <div class="bento-grid">
          <article
            v-for="capability in capabilities"
            :key="capability.kind"
            class="bento-block fall-in"
            :class="`b-${capability.area}`"
          >
            <span class="accent-square" :class="`sq-${capability.area}`" aria-hidden="true" />
            <header class="bento-head">
              <h3>{{ capability.title }}</h3>
              <span class="bento-detail label">{{ capability.detail }}</span>
            </header>
            <p class="bento-copy">{{ capability.copy }}</p>
            <div class="bento-stat">
              <span class="stat-label">{{ capability.stat }}</span>
              <span class="stat-val fig">{{ capability.statValue() }}</span>
            </div>
          </article>
        </div>
      </section>

      <!-- ── PRODUCT: flow ───────────────────────────────────────────────────── -->
      <section id="flow" class="product-feature section-pad">
        <div class="pf-copy gsap-reveal">
          <p class="section-eyebrow"><i class="eyebrow-tick" aria-hidden="true" />Flow</p>
          <h2>See what dealers have to hedge.</h2>
          <p class="section-lede">
            Map gamma by strike, find the level where hedging flips from damping a move to feeding
            it, then read the tape underneath. Calls, puts, and unsigned prints stay separate until
            the provider gives a side.
          </p>

          <div class="flow-feature-grid" aria-label="Flow structure capabilities">
            <article v-for="feature in flowFeatures" :key="feature.kind" class="flow-feature-box">
              <FlowSignatureDiagram class="feature-figure" :kind="feature.kind" />
              <div class="feature-text">
                <span class="feature-idx label">{{ feature.idx }}</span>
                <strong>{{ feature.title }}</strong>
                <p>{{ feature.copy }}</p>
              </div>
            </article>
          </div>

          <div class="chip-row" aria-label="Flow coverage">
            <span class="chip">Gamma by strike</span>
            <span class="chip">Flip point</span>
            <span class="chip">Implied range</span>
            <span class="chip">Unusual activity</span>
            <span class="chip">Contract context</span>
          </div>

          <RouterLink class="px-link" :to="{ name: 'auth', query: { redirect: '/flow' } }">
            Open Flow now
            <svg
              class="px-arrow"
              width="20"
              height="20"
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden="true"
            >
              <rect x="1" y="8" width="10" height="4" />
              <rect x="11" y="4" width="4" height="4" />
              <rect x="11" y="12" width="4" height="4" />
              <rect x="15" y="8" width="4" height="4" />
            </svg>
          </RouterLink>
        </div>
        <div class="pf-visual-stack gsap-reveal">
          <GexFlowVisual class="pf-visual" />
        </div>
      </section>

      <!-- ── MODEL LAB: interactive Black-Scholes workbench ──────────────────── -->
      <section id="lab" class="lab-section section-pad">
        <header class="section-head gsap-reveal">
          <p class="section-eyebrow"><i class="eyebrow-tick" aria-hidden="true" />Model lab</p>
          <h2>Every figure is a formula. Go ahead, move it.</h2>
          <p class="section-lede">
            This is the actual Black-Scholes engine, running in your browser. Drag volatility and
            expiry, switch between value and the Greeks, drag the strike marker on the chart. The
            readouts recompute from the closed forms; nothing here is pre-rendered theatre.
          </p>
        </header>

        <BsLab class="lab-frame gsap-reveal" />

        <p class="lab-footnote gsap-reveal">
          Unitless model spot S₀ = $100 · carry r = 5% · dividend yield q = 0. The desk swaps these
          inputs for live quotes and chains after operator sign-in.
        </p>

        <figure
          class="instrument-frame lab-workbench-frame gsap-reveal"
          aria-label="Options desk strategy workbench showing Black-Scholes Greeks matrix, 3D implied volatility surface, and payoff diagrams"
        >
          <figcaption>
            <span class="fig-label"
              ><i class="fig-tick" aria-hidden="true" />OPTIONS DESK WORKBENCH · MULTI-LEG
              PAYOFF</span
            >
            <span class="fig-state">BLACK-SCHOLES LEGS · DRAG SPOT · SWITCH STRUCTURE</span>
          </figcaption>
          <PayoffPlate />
          <footer>
            <span class="fig-legend"><i class="leg-iv-high" />Today value</span>
            <span class="fig-legend"><i class="leg-trace" />Expiry P&amp;L</span>
            <span class="fig-legend"><i class="leg-med" />Leg strikes</span>
            <strong
              >Long call · bull call spread · iron fly — legs summed from the closed forms</strong
            >
          </footer>
        </figure>
      </section>

      <!-- ── METHOD: principles grid ─────────────────────────────────────────── -->
      <section id="method" class="method-section section-pad">
        <header class="section-head gsap-reveal">
          <p class="section-eyebrow"><i class="eyebrow-tick" aria-hidden="true" />Method</p>
          <h2>Trust is a system property.</h2>
          <p class="section-lede">
            TradeCentral separates research, decision support, readiness, and execution
            authorization. A polished surface never gets to erase that boundary.
          </p>
        </header>

        <div class="principle-grid">
          <article v-for="principle in principles" :key="principle.index" class="principle fall-in">
            <span class="principle-index fig">{{ principle.index }}</span>
            <PrincipleDiagram :kind="principle.kind" />
            <h3>{{ principle.title }}</h3>
            <p class="principle-copy">{{ principle.copy }}</p>
          </article>
        </div>
      </section>

      <!-- ── ACCESS: one clear decision ─────────────────────────────────────── -->
      <section id="access" class="access-section section-pad">
        <header class="section-head gsap-reveal">
          <p class="section-eyebrow"><i class="eyebrow-tick" aria-hidden="true" />Access</p>
          <h2>Start free. Upgrade when the desk earns it.</h2>
          <p class="section-lede">
            Operator access is open while the instrument is in private preview. There is no card,
            auto-renewal, or invented price hiding behind the button.
          </p>
        </header>
        <div class="access-grid gsap-reveal">
          <article class="access-plan access-plan-primary">
            <p class="access-plan-kicker">NOW</p>
            <h3>Operator access</h3>
            <strong class="access-price">Free</strong>
            <p>Flow, positioning, and the research path for the current preview.</p>
            <RouterLink
              class="button button-primary"
              :to="{ name: 'waitlist', query: { redirect: '/flow' } }"
            >
              Join the access list
              <span aria-hidden="true">→</span>
            </RouterLink>
          </article>
          <article class="access-plan">
            <p class="access-plan-kicker">NEXT</p>
            <h3>Pro workspaces</h3>
            <strong class="access-price">Coming soon</strong>
            <p>
              Expanded research workspaces and deeper historical context will be announced before
              billing starts.
            </p>
            <span class="access-note">No payment details collected</span>
          </article>
        </div>
      </section>

      <!-- ── NAVY BAND: closing CTA with pixel candles ───────────────────────── -->
      <section class="band-dark final-cta full-bleed">
        <svg class="cta-pixels" viewBox="0 0 232 72" width="232" height="72" aria-hidden="true">
          <g fill="var(--tc-yellow, #ffaf01)">
            <rect x="10" y="8" width="4" height="40" />
            <rect x="4" y="20" width="16" height="16" />
            <rect x="106" y="12" width="4" height="44" />
            <rect x="100" y="24" width="16" height="20" />
            <rect x="198" y="20" width="4" height="36" />
            <rect x="192" y="32" width="16" height="12" />
          </g>
          <g fill="var(--phosphor-hi, #ff8204)">
            <rect x="42" y="0" width="4" height="52" />
            <rect x="36" y="12" width="16" height="20" />
            <rect x="138" y="16" width="4" height="48" />
            <rect x="132" y="36" width="16" height="16" />
          </g>
          <g fill="var(--phosphor, #ff5229)">
            <rect x="74" y="12" width="4" height="56" />
            <rect x="68" y="32" width="16" height="20" />
            <rect x="166" y="4" width="4" height="44" />
            <rect x="160" y="12" width="16" height="24" />
          </g>
        </svg>

        <div class="section-pad final-inner gsap-reveal">
          <p class="section-eyebrow">
            <i class="eyebrow-tick" aria-hidden="true" />Private preview · Access requests open
          </p>
          <h2>Start with one symbol.</h2>
          <p class="section-lede">
            Pick a ticker, read its positioning, and follow the evidence back to the run that
            produced it. That is the whole loop.
          </p>
          <RouterLink
            class="button button-primary"
            :to="{ name: 'waitlist', query: { redirect: '/flow' } }"
          >
            Join the access list
            <svg
              class="px-arrow"
              width="20"
              height="20"
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden="true"
            >
              <rect x="1" y="8" width="10" height="4" />
              <rect x="11" y="4" width="4" height="4" />
              <rect x="11" y="12" width="4" height="4" />
              <rect x="15" y="8" width="4" height="4" />
            </svg>
          </RouterLink>
          <small
            >Access requests are reviewed during the private preview. Pro workspaces are coming
            soon.</small
          >
        </div>
      </section>
    </main>

    <footer class="landing-footer">
      <div class="footer-frame">
        <div class="footer-cols section-pad">
          <div class="footer-brand-col">
            <RouterLink class="brand footer-brand" to="/">
              <TradeCentralMark :size="22" />
              <span class="wordmark"
                ><strong>TradeCentral</strong><small>Research instrument</small></span
              >
            </RouterLink>
            <p class="footer-tagline">
              Market intelligence for US equities and options. Follow the signal from flow to
              context in one workspace.
            </p>
          </div>
          <nav class="footer-col" aria-label="Product">
            <p class="footer-col-title">Product</p>
            <a href="#product">Product layers</a>
            <a href="#flow">Flow</a>
            <a href="#lab">Model lab</a>
          </nav>
          <nav class="footer-col" aria-label="Research">
            <p class="footer-col-title">Research</p>
            <a href="#method">Method</a>
            <a href="#access">Access and pricing</a>
          </nav>
          <nav class="footer-col" aria-label="Access">
            <p class="footer-col-title">Access</p>
            <RouterLink :to="{ name: 'auth', query: { mode: 'signin', redirect: '/flow' } }"
              >Sign in</RouterLink
            >
            <RouterLink :to="{ name: 'auth', query: { mode: 'setup', redirect: '/flow' } }"
              >Request operator access</RouterLink
            >
          </nav>
          <nav class="footer-col" aria-label="Legal">
            <p class="footer-col-title">Legal</p>
            <RouterLink to="/license">License agreement</RouterLink>
            <RouterLink to="/terms">Terms of service</RouterLink>
            <RouterLink to="/terms">Regulatory disclaimers</RouterLink>
          </nav>
        </div>

        <div class="footer-watermark-wrap" aria-hidden="true">
          <svg
            aria-hidden="true"
            class="footer-watermark"
            viewBox="0 0 420 220"
            fill="currentColor"
          >
            <rect x="0" y="180" width="20" height="40" />
            <rect x="28" y="160" width="20" height="60" />
            <rect x="56" y="120" width="20" height="100" />
            <rect x="84" y="140" width="20" height="80" />
            <rect x="112" y="90" width="20" height="130" />
            <rect x="140" y="60" width="20" height="160" />
            <rect x="168" y="100" width="20" height="120" />
            <rect x="196" y="40" width="20" height="180" />
            <rect x="224" y="70" width="20" height="150" />
            <rect x="252" y="0" width="20" height="220" />
            <rect x="280" y="50" width="20" height="170" />
            <rect x="308" y="30" width="20" height="190" />
            <rect x="336" y="10" width="20" height="210" />
          </svg>
        </div>

        <div class="footer-base section-pad">
          <span>© 2026 TradeCentral · All rights reserved · Session {{ session }}</span>
          <span>
            <RouterLink to="/license">License</RouterLink> ·
            <RouterLink to="/terms">Terms</RouterLink> · No order routing · No investment advice
          </span>
        </div>
      </div>
    </footer>
  </div>
</template>

<style scoped>
:global(body.edge-public-mode) {
  overflow: auto !important;
  overflow-x: hidden !important;
  background: #fbfbf8;
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

/* ── Paper system remap ────────────────────────────────────────────────────
   The landing page keeps the desk's token vocabulary but resolves it to a
   warm editorial paper scheme: cream surfaces, hairline rules, zinc ink, one
   orange accent, navy bands. The desk itself is untouched; these overrides
   are scoped to this page. Every child visual (McLiveHero, BsLab, the SVG
   figures) inherits the remap through the cascade. */
.landing-page {
  --void: #fbfbf8;
  --void-lift: #f7f6f1;
  --panel: #f5f4ef;
  --panel-hi: #ebe9e0;
  --panel-raise: #e4e2d6;
  --rule: #e4e3de;
  --rule-hi: #c9c9c4;
  --rule-faint: #efeee9;
  --grid: rgba(24, 24, 27, 0.045);
  --ink: #18181b;
  --ink-soft: #27272a;
  --ink-dim: #3f3f46;
  --ink-faint: #565660;
  --ink-ghost: #6f6f78;
  --phosphor: #ff5229;
  --phosphor-hi: #ff8204;
  --phosphor-dim: #c93a10;
  --phosphor-wash: rgba(255, 82, 41, 0.07);
  --phosphor-glow: rgba(255, 82, 41, 0.15);
  /* Deepened from #0f8a5f / #a06a00: both are used as body text on this cream
     ground (ticker changes, the stale-data note) and both landed under the
     4.5:1 AA floor there — 4.20:1 and 4.45:1. These clear it at 5.17:1 and
     5.66:1 while reading as the same green and amber in the figures. */
  --call: #0a7a53;
  --call-wash: rgba(10, 122, 83, 0.1);
  --put: #d92620;
  --put-wash: rgba(217, 38, 32, 0.08);
  --long: #0a7a53;
  --short: #d92620;
  --warn: #8a5b00;

  /* Page-local palette: bright yellows/blues stay decorative-only (progress
     ticks, accents); text roles stay on the AA-checked ramp above. */
  --tc-yellow: #ffaf01;
  --tc-blue: #0082e6;
  --tc-navy: #151524;
  --tc-navy-2: #242433;
  --tc-cream: #fafaf4;
  --tc-black: #09090b;

  /* Editorial typography (page-scoped; desk stacks untouched). */
  --font-display:
    'Inter Tight Variable', 'Inter Tight', 'Inter Tight Metric Fallback', 'Geist Variable', 'Geist',
    sans-serif;
  --font-ui:
    'Inter Variable', 'Inter', 'Inter Metric Fallback', 'Geist Variable', 'Geist', sans-serif;
  --font-data: 'Space Mono', 'IBM Plex Mono', 'Geist Mono Variable', monospace;
  --font-mono: 'Space Mono', 'IBM Plex Mono', 'Geist Mono Variable', monospace;

  /* Height of the fixed masthead. */
  --chrome-h: 56px;

  position: relative;
  z-index: 3;
  min-height: 100vh;
  color: var(--ink);
  background: var(--void);
  font-family: var(--font-ui);
  font-size: 16px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}

/* Anchored sections must clear the fixed masthead when jumped to. */
.landing-page section[id] {
  scroll-margin-top: calc(var(--chrome-h) + 16px);
}

/* ── Shared layout primitives ─────────────────────────────────────────────── */
.railroad {
  width: min(1480px, 100% - 48px);
  margin-inline: auto;
  border-inline: var(--hair) solid var(--rule);
  padding-top: var(--chrome-h);
}
.section-pad {
  padding-inline: clamp(20px, 4.5vw, 64px);
}
.full-bleed {
  margin-inline: calc(50% - 50vw);
}

.section-head {
  display: grid;
  gap: 14px;
  max-width: 720px;
  margin-bottom: clamp(36px, 5vw, 64px);
}
.section-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-data);
  font-size: 13px;
  font-weight: 400;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink-faint);
}
.eyebrow-tick {
  width: 8px;
  height: 8px;
  background: var(--phosphor);
}
.section-head h2 {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: clamp(34px, 4.4vw, 56px);
  line-height: 1.06;
  letter-spacing: -0.02em;
  color: var(--ink);
}
.section-head h2,
.hero-headline,
.hero-lede {
  text-wrap: balance;
}
.section-lede {
  max-width: 640px;
  font-size: 18px;
  line-height: 1.6;
  color: var(--ink-dim);
  text-wrap: pretty;
}

/* ── Buttons and links ────────────────────────────────────────────────────── */
.button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 48px;
  padding-inline: 20px;
  border-radius: 6px;
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 15px;
  letter-spacing: 0.01em;
  text-decoration: none;
  cursor: pointer;
  transition:
    background var(--dur) var(--ease-out),
    border-color var(--dur) var(--ease-out),
    color var(--dur) var(--ease-out);
}
.button-primary {
  background: var(--tc-black);
  color: #fbfbf8;
}
.button-primary:hover {
  background: #26262c;
}
.button:focus-visible {
  outline: 2px solid var(--phosphor);
  outline-offset: 2px;
}
.button:active {
  transform: translateY(1px);
}
.button-ghost {
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink);
  background: transparent;
}
.button-ghost:hover {
  background: var(--panel-hi);
}
.button-ghost:focus-visible {
  outline: 2px solid var(--phosphor);
  outline-offset: 2px;
}
.px-link:focus-visible {
  outline: 2px solid var(--phosphor);
  outline-offset: 4px;
}
.px-arrow {
  flex: none;
  transition: transform 280ms var(--ease-out) 40ms;
}
.button:hover .px-arrow,
.px-link:hover .px-arrow {
  transform: translateX(3px);
}
.px-down {
  transform: translateY(-2px);
}
.button:hover .px-down {
  transform: translateY(2px);
}

.px-link {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-top: 26px;
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 16px;
  color: var(--ink);
  text-decoration: none;
}
.px-link::after {
  content: '';
  position: absolute;
  left: 0;
  bottom: -3px;
  height: 1px;
  width: calc(100% - 30px);
  background: currentColor;
  transform: scaleX(0);
  transform-origin: left;
  transition: transform var(--dur-slow) var(--ease-out);
}
.px-link:hover::after {
  transform: scaleX(1);
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 26px;
}
.chip {
  font-family: var(--font-data);
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule-hi);
  border-radius: 6px;
  padding: 5px 12px;
  white-space: nowrap;
}
.chip-strong {
  color: var(--ink);
  border-color: var(--ink);
}

/* ── Masthead ─────────────────────────────────────────────────────────────── */
.masthead {
  position: fixed;
  z-index: 20;
  inset: 0 0 auto;
  background: var(--void);
  border-bottom: var(--hair) solid var(--rule);
  transition: border-color var(--dur) var(--ease-out);
}
.masthead.is-scrolled {
  border-bottom-color: var(--rule-hi);
}
.masthead-inner {
  width: min(1480px, 100% - 48px);
  margin-inline: auto;
  min-height: var(--chrome-h);
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: stretch;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  padding-right: 20px;
  border-right: var(--hair) solid var(--rule);
  margin-right: 20px;
  text-decoration: none;
  color: var(--ink);
  text-wrap: balance;
}
.section-head h2,
.hero-headline {
  text-wrap: balance;
}
.brand-mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: 6px;
  background: var(--tc-cream);
}
.wordmark {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
}
.wordmark strong {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 15px;
  letter-spacing: -0.01em;
}
.wordmark small {
  font-family: var(--font-data);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ink-faint);
}
.masthead-nav {
  display: flex;
  align-items: center;
  gap: 4px;
}
.masthead-nav a {
  position: relative;
  padding: 8px 12px;
  font-size: 14px;
  color: var(--ink-dim);
  text-decoration: none;
  transition: color var(--dur) var(--ease-out);
}
.masthead-nav a::after {
  content: '';
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: 2px;
  height: 1px;
  background: var(--ink);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform var(--dur-slow) var(--ease-out);
}
.masthead-nav a:hover {
  color: var(--ink);
}
.masthead-nav a:hover::after {
  transform: scaleX(1);
}
.masthead-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-left: 20px;
  border-left: var(--hair) solid var(--rule);
}
.sign-in {
  font-size: 14px;
  color: var(--ink-dim);
  text-decoration: none;
  transition: color var(--dur) var(--ease-out);
}
.sign-in:hover {
  color: var(--ink);
}
.sign-in:focus-visible {
  outline: 2px solid var(--phosphor);
  outline-offset: 3px;
}
.masthead-actions .button {
  min-height: 40px;
  padding-inline: 16px;
  font-size: 14px;
}
.nav-menu-btn {
  display: none;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: 6px;
  background: transparent;
  color: var(--ink);
  cursor: pointer;
}
.nav-menu-btn:focus-visible {
  outline: 2px solid var(--phosphor);
  outline-offset: 2px;
}
.nav-menu-btn:active {
  transform: scale(0.98);
}

/* ── Hero ─────────────────────────────────────────────────────────────────── */
.hero {
  display: grid;
  grid-template-columns: minmax(0, 6.5fr) minmax(0, 5.5fr);
  gap: clamp(36px, 5vw, 72px);
  align-items: center;
  /* Tightened from clamp(64px, 8vw, 120px): with the headline set at up to
     92px the old top padding pushed the primary call to action past the fold
     on a 900px laptop viewport, so the first screen ended on body copy. */
  padding-block: clamp(40px, 5vw, 76px);
}
.hero-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  font-family: var(--font-data);
  font-size: 13px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink-faint);
}
.hero-headline {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: clamp(40px, 5.4vw, 78px);
  line-height: 1;
  letter-spacing: -0.025em;
  color: var(--ink);
  margin-bottom: 22px;
  text-wrap: balance;
}
.hero-line {
  display: block;
  position: relative;
}
.hero-line.em {
  color: var(--ink);
}
.hero-line-box {
  visibility: hidden;
}
.hero-line-churn {
  position: absolute;
  inset: 0;
}
.hero-lede {
  max-width: 560px;
  font-size: 19px;
  line-height: 1.6;
  color: var(--ink-dim);
  margin-bottom: 34px;
  text-wrap: balance;
}
/* Every word occupies the same single grid cell, so the container is
   permanently as wide as the longest of them. Taking the inactive words out
   of flow (the previous `position: absolute`) made the container resize on
   each swap, reflowing the lede and everything under it — a layout shift
   every 2.6s for as long as the page stayed open, and the largest single
   contributor to CLS on mobile. */
.rotating-word {
  display: inline-grid;
  color: var(--phosphor-dim);
  font-weight: 500;
}
.rw-item {
  grid-area: 1 / 1;
  transition:
    opacity var(--dur-slow) var(--ease-out),
    transform var(--dur-slow) var(--ease-out);
}
.rw-item:not(.active) {
  opacity: 0;
  transform: translateY(8px);
  pointer-events: none;
}
.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 30px;
}
.hero-boundary {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--ink-dim);
}
.hero-boundary strong {
  color: var(--call);
}
.hero-boundary .boundary-icon {
  flex: none;
  color: var(--phosphor-dim);
}
.hero-boundary strong {
  color: var(--ink);
  font-weight: 600;
}
.hero-try-note {
  max-width: 480px;
  font-size: 14px;
  line-height: 1.55;
  color: var(--ink-faint);
}
.hero-warn-note {
  margin-top: 10px;
  font-family: var(--font-data);
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--warn);
}

/* ── Instrument frames (hero Monte Carlo, vol surface) ────────────────────── */
.instrument-frame {
  display: flex;
  flex-direction: column;
  border: var(--hair) solid var(--rule-hi);
  border-radius: 8px;
  background: var(--tc-cream);
  overflow: hidden;
}
.instrument-frame figcaption {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: var(--hair) solid var(--rule);
}
.fig-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-data);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--ink);
}
.fig-tick {
  width: 8px;
  height: 8px;
  background: var(--tc-yellow);
}
.fig-state {
  font-family: var(--font-data);
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--ink-faint);
  text-align: right;
}
.hero-mc-stage {
  height: 340px;
  border-bottom: var(--hair) solid var(--rule);
}
.instrument-frame > footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 16px;
  padding: 10px 16px;
  font-family: var(--font-data);
  font-size: 11px;
  color: var(--ink-faint);
}
.instrument-frame > footer strong {
  margin-left: auto;
  font-weight: 400;
  color: var(--ink-faint);
}
.capture-link {
  color: var(--ink);
  text-underline-offset: 3px;
}
.capture-link:hover {
  color: var(--tc-orange, #ff5229);
}
.capture-link:focus-visible {
  outline: 2px solid var(--tc-orange, #ff5229);
  outline-offset: 3px;
}
.fig-legend {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.fig-legend i {
  width: 10px;
  height: 2px;
}
/* These swatches must match what McLiveHero actually paints on the canvas:
   the path fan and histogram are --ink-dim at low alpha, the closed-form
   density is solid --ink, and the median rule is the dashed --phosphor. The
   previous values named an orange path and a blue density that appear
   nowhere in the figure, so the legend mislabelled its own chart. */
.leg-path {
  background: var(--ink-dim);
  opacity: 0.55;
}
.leg-hist {
  background: var(--ink-dim);
  opacity: 0.35;
}
.leg-trace {
  background: var(--ink);
}
.leg-med {
  background: repeating-linear-gradient(90deg, var(--phosphor) 0 3px, transparent 3px 5px);
}

/* ── Navy bands ───────────────────────────────────────────────────────────── */
.band-dark {
  --void: var(--tc-navy);
  --void-lift: #191927;
  --panel: #1d1d30;
  --panel-hi: var(--tc-navy-2);
  --panel-raise: #2c2c3f;
  --rule: rgba(250, 250, 244, 0.14);
  --rule-hi: rgba(250, 250, 244, 0.3);
  --rule-faint: rgba(250, 250, 244, 0.08);
  --grid: rgba(250, 250, 244, 0.05);
  --ink: #fafaf4;
  --ink-soft: #e6e6de;
  --ink-dim: #c0c0c8;
  --ink-faint: #9a9aa4;
  --ink-ghost: #80808c;
  --phosphor: #ff8204;
  --phosphor-dim: #ffa149;
  --phosphor-wash: rgba(255, 130, 4, 0.1);
  /* Signed market colors brighten on navy so figures keep their contrast. */
  --call: #4ade80;
  --call-wash: rgba(74, 222, 128, 0.12);
  --put: #ff7a70;
  --put-wash: rgba(255, 122, 112, 0.12);
  --long: #4ade80;
  --short: #ff7a70;
  --warn: #ffc95e;
  background: var(--tc-navy);
  color: var(--ink);
}
.band-dark .section-head h2,
.band-dark .hero-lede {
  color: var(--ink);
}
.band-dark .section-lede {
  color: var(--ink-dim);
}
.band-dark .button-primary {
  background: var(--tc-cream);
  color: var(--tc-navy);
}
.band-dark .button-primary:hover {
  background: #ffffff;
}

/* ── Evidence band internals ──────────────────────────────────────────────── */
.evidence-section {
  padding-block: clamp(64px, 8vw, 130px);
}
.live-grid {
  display: grid;
  grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
  gap: 20px;
  margin-bottom: clamp(48px, 6vw, 80px);
  align-items: stretch;
}
.live-state-frame {
  border: var(--hair) solid var(--rule);
  border-radius: 8px;
  background: var(--panel);
  padding: 18px;
}
.readiness-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  border: var(--hair) solid var(--rule);
  border-radius: 8px;
  background: var(--panel);
  padding: 20px;
}
.readiness-eyebrow {
  font-family: var(--font-data);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-faint);
}
.readiness-rows {
  display: flex;
  flex-direction: column;
}
.readiness-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 0;
  border-bottom: var(--hair) solid var(--rule-faint);
  font-size: 13px;
}
.readiness-row span {
  color: var(--ink-faint);
}
.readiness-row strong {
  font-family: var(--font-data);
  font-weight: 700;
  font-size: 12px;
  letter-spacing: 0.06em;
  color: var(--ink);
}
.readiness-row strong.ok {
  color: var(--call-hi);
}
.readiness-row strong.warn {
  color: var(--tc-yellow);
}
.readiness-note {
  margin-top: auto;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-faint);
}
.readiness-note.warn {
  color: var(--tc-yellow);
}

.tracing-beam-wrap {
  display: flex;
  flex-direction: column;
  gap: 28px;
}
.tracing-beam-rail {
  position: relative;
  height: 2px;
  background: var(--rule-faint);
}
.beam-fill {
  position: absolute;
  inset: 0 auto 0 0;
  width: 0%;
  height: 100%;
  background: var(--tc-yellow);
}
.pipeline {
  display: flex;
  gap: 12px;
}
.pipeline-step {
  flex: 1 1 0;
  min-width: 0;
}
.pipeline-node {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border: var(--hair) solid var(--rule);
  border-radius: 8px;
  background: var(--panel);
  color: var(--ink-dim);
  transition:
    border-color var(--dur-slow) var(--ease-out),
    color var(--dur-slow) var(--ease-out);
}
.pipeline-idx {
  font-size: 11px;
  color: var(--ink-faint);
}
.pipeline-icon {
  color: var(--ink-faint);
  transition: color var(--dur-slow) var(--ease-out);
}
.pipeline-label {
  font-family: var(--font-data);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
}
.pipeline-note {
  font-family: var(--font-data);
  font-size: 11px;
  font-style: normal;
  color: var(--ink-faint);
}
.pipeline-step.done .pipeline-node {
  border-color: var(--rule-hi);
  color: var(--ink);
}
.pipeline-step.done .pipeline-icon {
  color: var(--phosphor);
}
.pipeline-connector {
  display: none;
}

/* ── Editorial headline ───────────────────────────────────────────────────── */
.editorial-section {
  padding-block: clamp(72px, 9vw, 150px);
  text-align: center;
}
.editorial-headline {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: clamp(36px, 5.2vw, 68px);
  line-height: 1.04;
  letter-spacing: -0.02em;
  color: var(--ink);
  max-width: 900px;
  margin-inline: auto;
}

/* ── Markitecture bento ───────────────────────────────────────────────────── */
.bento-section {
  padding-block: clamp(64px, 8vw, 130px) clamp(80px, 9vw, 150px);
}
.bento-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  grid-auto-rows: minmax(88px, auto);
  grid-template-areas: 'market market options options governance governance';
  border-top: var(--hair) solid var(--rule-hi);
  border-left: var(--hair) solid var(--rule-hi);
}
.bento-block {
  position: relative;
  grid-column: span 2;
  padding: 20px;
  border-right: var(--hair) solid var(--rule-hi);
  border-bottom: var(--hair) solid var(--rule-hi);
  background: var(--void);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.b-market {
  grid-area: market;
}
.b-options {
  grid-area: options;
}
.b-governance {
  grid-area: governance;
}
.b-lab {
  grid-area: lab;
}
.b-work {
  grid-area: work;
}
.accent-square {
  position: absolute;
  top: 0;
  left: 0;
  width: 24px;
  height: 24px;
}
.sq-market {
  background: var(--tc-blue);
}
.sq-options {
  background: var(--phosphor);
}
.sq-governance {
  background: var(--tc-yellow);
}
.sq-yellow {
  background: var(--tc-yellow);
}
.sq-blue {
  background: var(--tc-blue);
}
.bento-head {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-left: 30px;
}
.bento-head h3,
.bento-chip h3 {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 22px;
  letter-spacing: -0.01em;
  color: var(--ink);
}
.bento-detail {
  color: var(--ink-faint);
}
.bento-copy {
  max-width: 520px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--ink-dim);
}
.bento-stat {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-top: auto;
  padding-top: 14px;
  border-top: var(--hair) solid var(--rule);
}
.stat-label {
  font-family: var(--font-data);
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ink-faint);
}
.stat-val {
  font-size: 20px;
  color: var(--ink);
}
.bento-chip .bento-copy {
  font-size: 13px;
}
/* Mirrors .bento-stat's role in the evidence cards: a footer line that pins
   to the bottom of the cell, so a five-cell row never ends on ragged
   whitespace — and gives the two lightest cards somewhere to send a reader. */
.bento-jump {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-top: auto;
  padding-top: 14px;
  border-top: var(--hair) solid var(--rule);
  font-family: var(--font-data);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink);
  text-decoration: none;
}
.bento-jump i {
  font-style: normal;
  color: var(--phosphor);
  transition: transform var(--dur) var(--ease-out);
}
.bento-jump:hover i {
  transform: translateY(3px);
}

/* ── Fall-in entrance (bento blocks, principles) ──────────────────────────── */
.fall-in {
  opacity: 1;
  transition:
    opacity 0.4s ease,
    transform 0.4s ease;
}
@media (prefers-reduced-motion: no-preference) {
  .fall-in:not(.in-view) {
    opacity: 0;
    transform: translateY(-24px);
  }
  .fall-in.in-view {
    opacity: 1;
    transform: translateY(0);
    animation: fall-in 0.6s cubic-bezier(0.2, 0.8, 0.2, 1) both;
    animation-delay: calc(var(--fall-i, 0) * 60ms);
  }
}
.bento-grid > :nth-child(1) {
  --fall-i: 0;
}
.bento-grid > :nth-child(2) {
  --fall-i: 1;
}
.bento-grid > :nth-child(3) {
  --fall-i: 2;
}
.bento-grid > :nth-child(4) {
  --fall-i: 3;
}
.bento-grid > :nth-child(5) {
  --fall-i: 4;
}
.bento-grid > :nth-child(6) {
  --fall-i: 5;
}
.principle-grid > :nth-child(1) {
  --fall-i: 0;
}
.principle-grid > :nth-child(2) {
  --fall-i: 1;
}
.principle-grid > :nth-child(3) {
  --fall-i: 2;
}
.principle-grid > :nth-child(4) {
  --fall-i: 3;
}
@keyframes fall-in {
  0% {
    transform: translateY(-24px);
    opacity: 0;
  }
  100% {
    transform: translateY(0);
    opacity: 1;
  }
}

/* ── Product feature sections (alternating) ───────────────────────────────── */
.product-feature {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: clamp(36px, 5vw, 80px);
  align-items: center;
  padding-block: clamp(72px, 9vw, 150px);
  border-top: var(--hair) solid var(--rule);
}
.product-feature-alt {
  grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
}
.product-feature-alt .pf-copy {
  order: 2;
}
.pf-copy h2 {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: clamp(32px, 3.8vw, 48px);
  line-height: 1.06;
  letter-spacing: -0.02em;
  color: var(--ink);
  margin-block: 14px 16px;
}
.pf-copy .section-lede {
  font-size: 17px;
}
.pf-visual {
  min-width: 0;
}

/* Stacked rows, not three narrow columns. In a half-width copy column, three
   side-by-side cards squeezed each diagram to ~190px — small enough that the
   8px instrument labels collided with the geometry they were labelling. A row
   gives the figure a stable 210px and the sentence a readable measure. */
.flow-feature-grid {
  display: grid;
  gap: 0;
  margin-top: 26px;
  border-top: var(--hair) solid var(--rule-hi);
}
.flow-feature-box {
  display: grid;
  grid-template-columns: 210px minmax(0, 1fr);
  align-items: center;
  gap: 18px;
  padding-block: 16px;
  border-bottom: var(--hair) solid var(--rule-hi);
  transition: background var(--dur) var(--ease-out);
}
.flow-feature-box:hover {
  background: var(--void-lift);
}
.feature-figure {
  min-width: 0;
}
.feature-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.feature-idx {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--ink-faint);
}
.flow-feature-box strong {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 17px;
  letter-spacing: -0.01em;
  color: var(--ink);
}
.flow-feature-box p {
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--ink-dim);
}

.surface-params {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 26px;
}
.surface-params span {
  font-family: var(--font-data);
  font-size: 12px;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule-hi);
  border-radius: 6px;
  padding: 6px 10px;
}

/* ── Model lab ────────────────────────────────────────────────────────────── */
.lab-section {
  padding-block: clamp(72px, 9vw, 150px);
  border-top: var(--hair) solid var(--rule);
}
.lab-frame {
  margin-inline: auto;
}
.lab-footnote {
  margin-top: 20px;
  max-width: 720px;
  margin-inline: auto;
  text-align: center;
  font-family: var(--font-data);
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--ink-faint);
}

/* ── Principles ───────────────────────────────────────────────────────────── */
.method-section {
  padding-block: clamp(72px, 9vw, 150px);
  border-top: var(--hair) solid var(--rule);
}
.principle-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.principle {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 22px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: 8px;
  background: var(--void);
  transition:
    transform var(--dur) var(--ease-out),
    border-color var(--dur) var(--ease-out);
}
.principle:hover {
  transform: translateY(-4px);
  border-color: var(--ink);
}
.principle-index {
  font-family: var(--font-data);
  font-size: 11px;
  letter-spacing: 0.1em;
  color: var(--phosphor-dim);
}
.principle h3 {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 18px;
  letter-spacing: -0.01em;
  color: var(--ink);
}
.principle-copy {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--ink-dim);
}

/* ── Access section ───────────────────────────────────────────────────────── */
.access-section {
  padding-block: clamp(72px, 9vw, 150px);
  border-top: var(--hair) solid var(--rule);
}
.access-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}
.access-plan {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 14px;
  min-height: 290px;
  padding: clamp(24px, 3vw, 36px);
  border: var(--hair) solid var(--rule-hi);
  background: var(--void);
}
.access-plan-primary {
  background: var(--tc-navy);
  border-color: var(--tc-navy);
  color: var(--tc-cream);
}
.access-plan-kicker {
  font-family: var(--font-data);
  font-size: 11px;
  letter-spacing: 0.12em;
  color: var(--phosphor);
}
.access-plan h3 {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 500;
  line-height: 1.1;
}
.access-price {
  font-family: var(--font-display);
  font-size: clamp(30px, 4vw, 46px);
  font-weight: 500;
  line-height: 1;
}
.access-plan p:not(.access-plan-kicker) {
  max-width: 440px;
  margin-bottom: auto;
  color: var(--ink-dim);
}
.access-plan-primary p:not(.access-plan-kicker) {
  color: rgba(250, 250, 244, 0.72);
}
.access-plan-primary .button-primary {
  background: var(--tc-cream);
  color: var(--tc-navy);
}
.access-note {
  font-family: var(--font-data);
  font-size: 11px;
  color: var(--ink-faint);
}
.access-plan-primary .access-note {
  color: rgba(250, 250, 244, 0.62);
}
.access-plan .button {
  margin-top: auto;
}
.access-plan + .access-plan {
  border-left: var(--hair) solid var(--rule-hi);
}
.access-plan + .access-plan::after {
  content: '';
}
.boundary-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  border: var(--hair) solid var(--rule-hi);
}
.boundary-col {
  padding: 26px;
  border-left: var(--hair) solid var(--rule-hi);
}
.boundary-col:first-child {
  border-left: 0;
}
.boundary-col h3 {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 20px;
  letter-spacing: -0.01em;
  color: var(--ink);
  margin-bottom: 10px;
}
.boundary-col p {
  font-size: 14px;
  line-height: 1.6;
  color: var(--ink-dim);
}
.boundary-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

/* ── Closing CTA ──────────────────────────────────────────────────────────── */
.final-cta {
  position: relative;
  padding-block: clamp(56px, 7vw, 104px);
  text-align: center;
  border-top: 3px solid var(--tc-orange, #ff5229);
}
.cta-pixels {
  display: block;
  margin: 0 auto clamp(28px, 4vw, 44px);
}
.final-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
}
.final-inner .section-eyebrow {
  justify-content: center;
}
.final-inner h2 {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: clamp(36px, 4.6vw, 60px);
  line-height: 1.05;
  letter-spacing: -0.02em;
  color: var(--ink);
}
.final-inner .section-lede {
  max-width: 560px;
  margin-inline: auto;
}
.final-inner .button {
  margin-top: 8px;
}
.final-inner small {
  font-family: var(--font-data);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ink-faint);
}

/* ── Footer ───────────────────────────────────────────────────────────────── */
.landing-footer {
  --void: #151524;
  --rule: rgba(250, 250, 244, 0.14);
  --rule-hi: rgba(250, 250, 244, 0.3);
  --ink: #fafaf4;
  --ink-dim: #c0c0c8;
  --ink-faint: #9a9aa4;
  position: relative;
  border-top: var(--hair) solid rgba(250, 250, 244, 0.14);
  background: #151524;
  color: #fafaf4;
  overflow: hidden;
}
.footer-frame {
  width: min(1480px, 100% - 48px);
  margin-inline: auto;
  border-inline: var(--hair) solid var(--rule);
}
.footer-cols {
  display: grid;
  grid-template-columns: minmax(0, 1.8fr) repeat(4, minmax(0, 1fr));
  gap: 36px;
  padding-block: clamp(48px, 6vw, 80px);
}
.footer-brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  text-decoration: none;
  color: var(--ink);
}
.footer-tagline {
  max-width: 340px;
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--ink-dim);
}
.footer-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.footer-col-title {
  font-family: var(--font-data);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-faint);
  margin-bottom: 6px;
}
.footer-col a {
  font-size: 14px;
  color: var(--ink-dim);
  text-decoration: none;
  transition: color var(--dur) var(--ease-out);
}
.footer-col a:hover {
  color: var(--ink);
}
.footer-watermark-wrap {
  position: relative;
  height: 0;
}
.footer-watermark {
  position: absolute;
  right: clamp(8px, 3vw, 40px);
  bottom: 34px;
  width: clamp(200px, 22vw, 340px);
  color: #fafaf4;
  opacity: 0.06;
  pointer-events: none;
}
.footer-base {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding-block: 18px;
  border-top: var(--hair) solid var(--rule);
  font-family: var(--font-data);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ink-faint);
}
.footer-base a {
  color: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.footer-base a:hover {
  color: var(--ink);
}

/* ── Responsive ───────────────────────────────────────────────────────────── */
@media (max-width: 1100px) {
  .bento-grid {
    grid-template-columns: repeat(2, 1fr);
    grid-template-areas:
      'market options'
      'governance governance';
  }
  .principle-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .product-feature,
  .product-feature-alt {
    grid-template-columns: 1fr;
    gap: 40px;
  }
  .product-feature-alt .pf-copy {
    order: 0;
  }
  .live-grid {
    grid-template-columns: 1fr;
  }
  .footer-cols {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 800px) {
  .railroad,
  .masthead-inner,
  .footer-frame {
    width: min(100% - 32px, 1480px);
  }
  .masthead-inner {
    grid-template-columns: 1fr auto;
  }
  .brand {
    border-right: 0;
    margin-right: 0;
  }
  .masthead-nav {
    display: none;
    position: absolute;
    top: calc(100% + 1px);
    left: 0;
    right: 0;
    flex-direction: column;
    align-items: stretch;
    background: var(--void);
    border-bottom: var(--hair) solid var(--rule-hi);
    padding: 8px 16px 16px;
    z-index: 5;
  }
  .masthead:has(.nav-menu-btn[aria-expanded='true']) .masthead-nav,
  .masthead-nav.is-open {
    display: flex;
  }
  .masthead-nav a {
    padding: 12px 4px;
    font-size: 16px;
    border-bottom: var(--hair) solid var(--rule-faint);
  }
  .masthead-nav a::after {
    display: none;
  }
  .masthead-actions {
    border-left: 0;
    padding-left: 0;
  }
  .nav-menu-btn {
    display: inline-flex;
  }
  .hero {
    grid-template-columns: 1fr;
    gap: 44px;
    padding-block: 56px;
  }
  .hero-headline {
    font-size: clamp(38px, 10vw, 56px);
  }
  .access-grid {
    grid-template-columns: 1fr;
  }
  .access-plan + .access-plan {
    border-left: var(--hair) solid var(--rule-hi);
  }
  .pipeline {
    flex-wrap: wrap;
  }
  .pipeline-step {
    flex: 1 1 45%;
  }
  .boundary-grid {
    grid-template-columns: 1fr;
  }
  .boundary-col {
    border-left: 0;
    border-top: var(--hair) solid var(--rule-hi);
  }
  .boundary-col:first-child {
    border-top: 0;
  }
  .footer-watermark {
    opacity: 0.04;
  }
}

@media (max-width: 580px) {
  .wordmark small {
    display: none;
  }
  .masthead-actions .sign-in {
    display: none;
  }
  .masthead-actions .button {
    min-height: 40px;
    padding-inline: 12px;
    font-size: 13px;
    gap: 6px;
  }
  .hero {
    padding-block: 44px;
  }
  .hero-headline {
    font-size: clamp(34px, 9.6vw, 46px);
  }
  .hero-lede {
    font-size: 16px;
  }
  .hero-actions {
    display: grid;
  }
  .hero-mc-stage {
    height: 280px;
  }
  .hero-desk-stage {
    height: 340px;
  }
  .evidence-stats {
    grid-template-columns: 1fr;
  }
  .evidence-stats :deep(.readout) {
    border-inline: 0;
    border-top: var(--hair) solid var(--rule);
  }
  .evidence-stats :deep(.readout:first-child) {
    border-top: 0;
  }
  .flow-feature-box {
    grid-template-columns: 1fr;
    gap: 12px;
  }
  .principle-grid {
    grid-template-columns: 1fr;
  }
  .pipeline-step {
    flex: 1 1 100%;
  }
  .bento-grid {
    grid-template-columns: 1fr;
    grid-template-areas:
      'market'
      'options'
      'governance'
      'lab'
      'work';
  }
  .footer-cols {
    grid-template-columns: 1fr;
    gap: 28px;
  }
  .footer-base {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
}

/* ── Visual banner stages & view toggles ──────────────────────────────────── */
.fig-toggle-group {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  border-radius: 6px;
  padding: 2px;
}
.fig-tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  font-family: var(--font-data);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
  background: transparent;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: all var(--dur) var(--ease-out);
}
.fig-tab-btn:hover {
  color: var(--ink);
}
.fig-tab-btn.active {
  color: var(--ink);
  background: var(--tc-cream);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
.hero-desk-stage {
  height: 360px;
  overflow: hidden;
  border-bottom: var(--hair) solid var(--rule);
}
.hero-desk-stage img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: top center;
}

.pf-visual-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.product-feature-regimes {
  border-top: var(--hair) solid var(--rule);
}
.lab-workbench-frame {
  margin-top: 36px;
}
.gov-terminal-wrap {
  margin-top: 36px;
}

/* Increase Contrast: rules harden and secondary ink steps up a level. */
@media (prefers-contrast: more) {
  .masthead {
    border-bottom-color: var(--ink);
  }
  .bento-block,
  .principle,
  .flow-feature-box,
  .boundary-grid,
  .instrument-frame {
    border-color: var(--ink-dim);
  }
  .section-lede,
  .masthead-nav a,
  .sign-in,
  .px-link {
    color: var(--ink);
  }
  .hero-lede {
    color: var(--ink-soft);
  }
  .hero-boundary,
  .lab-footnote,
  .pipeline-note,
  .footer-base {
    color: var(--ink-soft);
  }
  .button-ghost {
    border-color: var(--ink-dim);
  }
}

@media (prefers-reduced-motion: reduce) {
  .rw-item,
  .rw-item:not(.active) {
    transition: none !important;
  }
  .fall-in {
    opacity: 1;
    animation: none !important;
  }
  .px-arrow,
  .button:hover .px-arrow,
  .px-link:hover .px-arrow,
  .button:hover .px-down {
    transform: none !important;
    transition: none !important;
  }
  .px-link::after {
    transition: none !important;
  }
  .masthead-nav a::after {
    transition: none !important;
  }
}
</style>
