<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted } from 'vue'
import { api, type MarketClock, type Readiness, type StatusPayload } from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import { age, DASH, num, shortDate } from '@/format'
import AppIcon from '@/components/AppIcon.vue'
import EvidenceLayerVisual from '@/components/EvidenceLayerVisual.vue'
import GexFlowVisual from '@/components/GexFlowVisual.vue'
import LiveStateVisual from '@/components/LiveStateVisual.vue'
import ResearchLoopVisual from '@/components/ResearchLoopVisual.vue'
import TradeCentralMark from '@/components/TradeCentralMark.vue'

/**
 * Public product overview.
 *
 * Market figures shown here come from the same loopback resources as the
 * operator shell. Product diagrams carry only labels and system boundaries;
 * there are no illustrative quotes, returns, or invented model scores.
 */
onMounted(() => document.body.classList.add('edge-public-mode'))
onUnmounted(() => document.body.classList.remove('edge-public-mode'))

const status = inject<Resource<StatusPayload>>('status')!
const readiness = inject<Resource<Readiness>>('readiness')!
const clock = useResource<MarketClock>(() => api.marketClock(), { intervalMs: 60_000 })

const session = computed(() => {
  switch (clock.data.value?.market_session) {
    case 'premarket': return 'PREMARKET'
    case 'regular': return 'REGULAR SESSION'
    case 'after_hours': return 'AFTER HOURS'
    case 'closed': return 'MARKET CLOSED'
    case 'replay': return 'REPLAY'
    default: return DASH
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

const capabilities = [
  {
    kind: 'market',
    icon: 'radar',
    index: '01',
    title: 'Market structure',
    copy: 'Search a broad US equity universe, compare trajectories, inspect sector rotation, and keep source freshness visible.',
    detail: 'Price · regimes · sectors · outliers',
  },
  {
    kind: 'options',
    icon: 'options',
    index: '02',
    title: 'Options & flow',
    copy: 'Read positioning, gamma topology, implied ranges, unusual activity, and signed-flow coverage without collapsing them into one score.',
    detail: 'GEX · flow · ranges · contract context',
  },
  {
    kind: 'governance',
    icon: 'gate',
    index: '03',
    title: 'Research governance',
    copy: 'Trace every claim back to point-in-time tests, pre-registered gates, run artifacts, and explicit shadow evidence.',
    detail: 'Methods · diagnostics · gates · ledgers',
  },
] as const

const principles = [
  {
    index: 'A',
    title: 'Missing stays missing',
    copy: 'Stale, unavailable, proxy, and degraded states are labelled—not silently converted to zero.',
  },
  {
    index: 'B',
    title: 'Evidence stays typed',
    copy: 'Ordinal research evidence is never presented as calibrated probability or trade authorization.',
  },
  {
    index: 'C',
    title: 'Promotion fails closed',
    copy: 'Readiness and pre-registered gates must agree before any strategy can advance beyond research.',
  },
  {
    index: 'D',
    title: 'Execution stays outside',
    copy: 'The checked-in pipeline contains no broker connection, order ticket, or submission route.',
  },
]
</script>

<template>
  <div class="landing-page">
    <header class="topbar-shell">
      <div class="topbar landing-inner">
        <RouterLink class="brand" to="/" aria-label="TradeCentral home">
          <span class="brand-mark"><TradeCentralMark :size="32" /></span>
          <span class="wordmark">
            <strong>TradeCentral</strong>
            <small>Quantitative research instrument</small>
          </span>
        </RouterLink>

        <nav class="topnav" aria-label="Product overview">
          <a href="#product"><small>01</small>Product</a>
          <a href="#workspaces"><small>02</small>Workspaces</a>
          <a href="#method"><small>03</small>Method</a>
        </nav>

        <div class="top-actions">
          <RouterLink class="sign-in" :to="{ name: 'auth', query: { mode: 'signin', redirect: '/flow' } }">
            Sign in
          </RouterLink>
          <RouterLink class="button button-paper nav-access" :to="{ name: 'auth', query: { mode: 'setup', redirect: '/flow' } }">
            Create access <AppIcon name="arrow-right" :size="15" />
          </RouterLink>
        </div>
      </div>
    </header>

    <main>
      <section class="hero landing-inner">
        <div class="hero-copy reveal reveal-1">
          <p class="eyebrow"><span aria-hidden="true" /> US equities · options intelligence</p>
          <h1>Read the market<br>beneath the price.</h1>
          <p class="lede">
            TradeCentral brings dealer positioning, options flow, and research
            controls into one evidence-first view—so a move has context before it
            has a narrative.
          </p>
          <div class="hero-actions">
            <RouterLink class="button button-accent" :to="{ name: 'auth', query: { redirect: '/flow' } }">
              Explore market flow <AppIcon name="arrow-right" :size="16" />
            </RouterLink>
            <a class="button button-quiet" href="#product">
              See what you get <AppIcon name="arrow-down" :size="15" />
            </a>
          </div>
          <div class="hero-boundary">
            <AppIcon name="shield" :size="17" />
            <span><strong>Research only.</strong> No order routing. No performance promises.</span>
          </div>
        </div>

        <div class="hero-visual reveal reveal-2">
          <GexFlowVisual />
        </div>
      </section>

      <section class="live-proof-section paper-section">
        <LiveStateVisual
          class="landing-inner reveal"
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

      <section class="trust-strip" aria-label="Product boundaries">
        <div class="landing-inner trust-inner">
          <div><AppIcon name="database" :size="21" /><span><strong>Point-in-time data</strong><small>Sources and as-of state remain visible</small></span></div>
          <div><AppIcon name="options" :size="21" /><span><strong>Truth-preserving options</strong><small>Calls, puts, and direction stay distinct</small></span></div>
          <div><AppIcon name="gate" :size="21" /><span><strong>Pre-registered gates</strong><small>Evidence before promotion</small></span></div>
          <div><AppIcon name="shield" :size="21" /><span><strong>Fail-closed posture</strong><small>Unavailable never becomes approved</small></span></div>
        </div>
      </section>

      <section id="product" class="product-section paper-section">
        <div class="landing-inner">
          <header class="section-heading">
            <div>
              <p class="section-index">PRODUCT / 01</p>
              <h2>One instrument.<br>Three evidence layers.</h2>
            </div>
            <p>
              Built for researchers and active traders who want institutional
              discipline without a black-box confidence meter. Every surface has a
              specific question, a source, and an honest failure state.
            </p>
          </header>

          <div class="capability-grid">
            <article v-for="capability in capabilities" :key="capability.index" class="capability">
              <EvidenceLayerVisual :kind="capability.kind" />
              <header>
                <span class="capability-icon"><AppIcon :name="capability.icon" :size="19" /></span>
                <span class="capability-index">{{ capability.index }}</span>
              </header>
              <h3>{{ capability.title }}</h3>
              <p>{{ capability.copy }}</p>
              <footer>{{ capability.detail }}</footer>
            </article>
          </div>
        </div>
      </section>

      <section id="workspaces" class="workspace-section">
        <div class="landing-inner workspace-layout">
          <div class="workspace-copy">
            <p class="section-index">WORKSPACES / 02</p>
            <h2>A research path.<br>Not a menu.</h2>
            <p>
              Each workspace answers one question, then hands its context forward.
              The path stays visible, while specialist tools remain adjacent.
            </p>
            <RouterLink class="text-link" :to="{ name: 'auth', query: { redirect: '/flow' } }">
              Open Flow now <AppIcon name="arrow-right" :size="15" />
            </RouterLink>
          </div>

          <ResearchLoopVisual />
        </div>
      </section>

      <section id="method" class="method-section paper-section">
        <div class="landing-inner">
          <header class="section-heading method-heading">
            <div>
              <p class="section-index">METHOD / 03</p>
              <h2>Trust is a system property.</h2>
            </div>
            <p>
              TradeCentral separates research, decision support, readiness, and
              execution authorization. A polished surface never gets to erase that boundary.
            </p>
          </header>

          <div class="principle-grid">
            <article v-for="principle in principles" :key="principle.index">
              <span>{{ principle.index }}</span>
              <h3>{{ principle.title }}</h3>
              <p>{{ principle.copy }}</p>
            </article>
          </div>

          <div class="method-flow" aria-label="Evidence lifecycle">
            <span><AppIcon name="database" :size="18" />DATA</span><i />
            <span><AppIcon name="research" :size="18" />RESEARCH</span><i />
            <span><AppIcon name="gate" :size="18" />GATES</span><i />
            <span><AppIcon name="session" :size="18" />SHADOW</span><i />
            <span><AppIcon name="shield" :size="18" />READINESS</span>
          </div>
        </div>
      </section>

      <section class="final-cta">
        <div class="landing-inner final-inner">
          <p class="section-index">THE RESEARCH LOOP</p>
          <h2>Build conviction from evidence,<br>not presentation.</h2>
          <p>One workstation for market context, options structure, and accountable research.</p>
          <RouterLink class="button button-accent" :to="{ name: 'auth', query: { redirect: '/flow' } }">
            Sign in and open Flow <AppIcon name="arrow-right" :size="16" />
          </RouterLink>
          <small>No credit card. No broker connection. Clerk session, then the measured tape.</small>
          <svg class="cta-traces" viewBox="0 0 1200 130" preserveAspectRatio="none" aria-hidden="true">
            <path d="M0 106 C130 104 165 52 282 73 S480 118 597 64 785 25 903 70 1080 105 1200 48" />
            <path d="M0 120 C145 84 214 116 330 94 S516 45 645 84 835 125 956 82 1105 54 1200 76" />
            <path d="M0 88 C126 125 210 68 338 82 S548 114 673 70 862 48 993 88 1120 114 1200 96" />
          </svg>
        </div>
      </section>
    </main>

    <footer class="landing-footer">
      <div class="landing-inner footer-inner">
        <RouterLink class="brand footer-brand" to="/">
          <TradeCentralMark :size="28" />
          <span class="wordmark"><strong>TradeCentral</strong><small>Research instrument</small></span>
        </RouterLink>
        <p>Research only · No execution · No investment advice</p>
        <nav aria-label="Footer links">
          <a href="#product">Product</a>
          <a href="#method">Method</a>
          <RouterLink :to="{ name: 'auth', query: { mode: 'signin', redirect: '/flow' } }">Sign in</RouterLink>
        </nav>
      </div>
    </footer>
  </div>
</template>

<style scoped>
:global(body.edge-public-mode) {
  overflow: auto !important;
  overflow-x: hidden !important;
  background: #141413;
}
:global(body.edge-public-mode #app),
:global(body.edge-public-mode .shell) {
  height: auto !important;
  min-height: 100vh;
  overflow: visible !important;
}
:global(body.edge-public-mode .shell) { display: block !important; }
:global(body.edge-public-mode .rail),
:global(body.edge-public-mode .strip),
:global(body.edge-public-mode .foot),
:global(body.edge-public-mode .skip-link) { display: none !important; }
:global(body.edge-public-mode .stage) {
  display: block !important;
  width: 100% !important;
  height: auto !important;
  min-height: 100vh !important;
  padding: 0 !important;
  overflow: visible !important;
}

.landing-page {
  --brand-dark: #141413;
  --brand-paper: #faf9f5;
  --brand-gray: #b0aea5;
  --brand-light-gray: #e8e6dc;
  --brand-orange: #d97757;
  --brand-blue: #6a9bcc;
  --brand-green: #788c5d;
  --brand-rule: #373631;
  position: relative;
  z-index: 3;
  min-height: 100vh;
  color: var(--brand-paper);
  background: var(--brand-dark);
  font-family: 'Lora', Georgia, var(--font-ui);
}

.landing-inner {
  width: min(1280px, calc(100% - 72px));
  margin-inline: auto;
}

.topbar-shell {
  position: sticky;
  z-index: 20;
  top: 0;
  border-bottom: 1px solid rgba(250, 249, 245, 0.15);
  background: rgba(20, 20, 19, 0.90);
  backdrop-filter: blur(18px);
}
.topbar {
  min-height: 78px;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
}
.brand { display: inline-flex; align-items: center; gap: 11px; color: var(--brand-paper); }
.brand:hover { text-decoration: none; }
.brand-mark { width: 42px; height: 42px; display: grid; place-items: center; color: var(--brand-paper); border: 1px solid #44443f; background: #191a18; }
.wordmark { display: grid; line-height: 1; }
.wordmark strong {
  font-family: 'Poppins', var(--font-ui);
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.025em;
}
.wordmark small {
  margin-top: 6px;
  color: var(--brand-gray);
  font-family: var(--font-display);
  font-size: 8px;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}
.topnav { display: flex; align-items: center; gap: 4px; padding: 4px; border: 1px solid #3a3a36; background: #191a18; }
.topnav a,
.sign-in {
  color: #c7c5bd;
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 540;
}
.topnav a { min-height: 34px; display: inline-flex; align-items: center; gap: 8px; padding: 0 12px; }
.topnav a small { color: #706f69; font-family: var(--font-data); font-size: 7px; }
.topnav a:hover,
.sign-in:hover { color: var(--brand-paper); background: #252622; text-decoration: none; }
.top-actions { justify-self: end; display: flex; align-items: center; gap: 20px; }
.sign-in { min-height: 38px; display: inline-flex; align-items: center; padding: 0 3px; }
.nav-access { border-left: 3px solid var(--brand-orange); }

.button {
  min-height: 46px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 0 20px;
  border: 1px solid transparent;
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.085em;
  text-transform: uppercase;
  transition: transform var(--dur-fast), background var(--dur-fast), border-color var(--dur-fast), color var(--dur-fast);
}
.button:hover { text-decoration: none; transform: translateY(-1px); }
.button-paper { min-height: 38px; color: var(--brand-dark); background: var(--brand-paper); }
.button-paper:hover { background: var(--brand-light-gray); }
.button-accent { color: var(--brand-paper); background: var(--brand-orange); }
.button-accent:hover { background: #c8684b; }
.button-quiet { color: var(--brand-paper); border-color: #494841; background: transparent; }
.button-quiet:hover { color: var(--brand-blue); border-color: var(--brand-blue); }

.hero {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 0.86fr) minmax(500px, 1.14fr);
  align-items: center;
  gap: clamp(54px, 6.5vw, 94px);
  min-height: 680px;
  padding-block: 82px;
}
.hero::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(250, 249, 245, 0.022) 1px, transparent 1px),
    linear-gradient(90deg, rgba(250, 249, 245, 0.022) 1px, transparent 1px);
  background-size: 38px 38px;
  mask-image: linear-gradient(to right, transparent 0, #000 52%, #000 100%);
}
.hero-copy,
.hero-visual { position: relative; z-index: 1; }
.hero-visual { min-width: 0; width: 100%; }
.eyebrow,
.section-index {
  font-family: var(--font-display);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.eyebrow { display: flex; align-items: center; gap: 11px; color: var(--brand-gray); }
.eyebrow span { width: 25px; height: 2px; background: var(--brand-orange); }
.hero h1 {
  margin-top: 25px;
  font-family: 'Poppins', var(--font-ui);
  font-size: clamp(52px, 5.2vw, 74px);
  font-weight: 560;
  line-height: 0.96;
  letter-spacing: -0.058em;
}
.lede {
  margin-top: 27px;
  max-width: 57ch;
  color: #ceccc4;
  font-family: var(--font-ui);
  font-size: 16px;
  line-height: 1.72;
}
.hero-actions { display: flex; flex-wrap: wrap; gap: 11px; margin-top: 34px; }
.hero-boundary {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 27px;
  color: #98958d;
  font-family: var(--font-ui);
  font-size: 11px;
}
.hero-boundary strong { color: #c9c7be; font-weight: 620; }
.hero-boundary .app-icon { color: var(--brand-green); }

.live-proof-section { background: #faf9f5; }
.trust-strip { border-top: 1px solid var(--brand-rule); border-bottom: 1px solid var(--brand-rule); background: #181817; }
.trust-inner { display: grid; grid-template-columns: repeat(4, 1fr); }
.trust-inner > div {
  min-width: 0;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 13px;
  align-items: start;
  padding: 22px 20px;
  border-left: 1px solid var(--brand-rule);
  color: var(--brand-blue);
}
.trust-inner > div:first-child { border-left: 0; padding-left: 0; }
.trust-inner span { display: grid; gap: 4px; }
.trust-inner strong { color: #e5e3dc; font-family: var(--font-ui); font-size: 11px; font-weight: 620; }
.trust-inner small { color: #85827b; font-family: var(--font-ui); font-size: 10px; line-height: 1.35; }

.paper-section { color: var(--brand-dark); background: var(--brand-paper); }
.product-section,
.workspace-section,
.method-section { scroll-margin-top: 78px; }
.product-section { padding-block: 112px; }
.section-heading {
  display: grid;
  grid-template-columns: 1fr minmax(300px, 0.62fr);
  gap: 80px;
  align-items: end;
}
.section-index { color: var(--brand-orange); }
.section-heading h2,
.workspace-copy h2,
.final-inner h2 {
  margin-top: 17px;
  font-family: 'Poppins', var(--font-ui);
  font-size: clamp(42px, 4.5vw, 64px);
  font-weight: 560;
  line-height: 1.03;
  letter-spacing: -0.052em;
}
.section-heading > p,
.workspace-copy > p:not(.section-index) {
  color: #65635d;
  font-family: var(--font-ui);
  font-size: 15px;
  line-height: 1.72;
}
.capability-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; margin-top: 67px; }
.capability { min-width: 0; display: flex; flex-direction: column; padding: 0 0 1px; }
.capability header { display: flex; align-items: center; justify-content: space-between; margin-top: 18px; padding-bottom: 14px; border-bottom: 1px solid #d3d0c7; }
.capability-icon { width: 34px; height: 34px; display: grid; place-items: center; color: var(--brand-dark); border: 1px solid #cbc8be; background: transparent; }
.capability:nth-child(1) .capability-icon { color: #3d6791; }
.capability:nth-child(2) .capability-icon { color: #a95f46; }
.capability:nth-child(3) .capability-icon { color: #63794d; }
.capability-index { color: #8b8880; font-family: var(--font-data); font-size: 10px; }
.capability h3 { margin-top: 20px; font-family: 'Poppins', var(--font-ui); font-size: 22px; font-weight: 590; letter-spacing: -0.03em; }
.capability > p { margin-top: 14px; color: #68665f; font-family: var(--font-ui); font-size: 13px; line-height: 1.65; }
.capability footer { margin-top: auto; padding: 22px 0 16px; color: #706d65; font-family: var(--font-display); font-size: 8px; letter-spacing: 0.08em; text-transform: uppercase; }

.workspace-section { padding-block: 112px; color: var(--brand-paper); background: #191a19; border-top: 1px solid var(--brand-rule); border-bottom: 1px solid var(--brand-rule); }
.workspace-layout { display: grid; grid-template-columns: minmax(270px, 0.42fr) minmax(620px, 1fr); gap: clamp(54px, 7vw, 100px); align-items: center; }
.workspace-copy { align-self: start; padding-top: 18px; }
.workspace-copy .section-index { color: var(--brand-blue); }
.workspace-copy > p:not(.section-index) { margin-top: 25px; color: #aaa79f; }
.text-link { display: inline-flex; align-items: center; gap: 10px; margin-top: 29px; color: var(--brand-paper); font-family: var(--font-display); font-size: 9px; font-weight: 700; letter-spacing: 0.09em; text-transform: uppercase; }
.text-link:hover { color: var(--brand-blue); text-decoration: none; }
.method-section { padding-block: 112px; }
.method-heading { align-items: center; }
.principle-grid { display: grid; grid-template-columns: repeat(4, 1fr); margin-top: 64px; border-top: 1px solid #cbc8be; border-bottom: 1px solid #cbc8be; }
.principle-grid article { padding: 26px 24px 31px; border-left: 1px solid #cbc8be; }
.principle-grid article:first-child { padding-left: 0; border-left: 0; }
.principle-grid article > span { color: var(--brand-orange); font-family: var(--font-data); font-size: 10px; }
.principle-grid h3 { margin-top: 24px; font-family: 'Poppins', var(--font-ui); font-size: 16px; font-weight: 600; letter-spacing: -0.025em; }
.principle-grid p { margin-top: 10px; color: #6b6962; font-family: var(--font-ui); font-size: 12px; line-height: 1.6; }
.method-flow { display: flex; align-items: center; gap: 14px; margin-top: 48px; }
.method-flow span { min-height: 38px; display: inline-flex; align-items: center; gap: 8px; padding: 0 10px; color: #55534e; border: 1px solid #cbc8be; background: #f2f0e8; font-family: var(--font-display); font-size: 8px; font-weight: 700; letter-spacing: 0.08em; }
.method-flow span:nth-of-type(1) .app-icon,
.method-flow span:nth-of-type(2) .app-icon { color: var(--brand-blue); }
.method-flow span:nth-of-type(3) .app-icon { color: var(--brand-orange); }
.method-flow span:nth-of-type(4) .app-icon,
.method-flow span:nth-of-type(5) .app-icon { color: var(--brand-green); }
.method-flow i { flex: 1; height: 1px; background: #c8c5bb; }

.final-cta { position: relative; overflow: hidden; padding-block: 100px 88px; text-align: center; background: var(--brand-dark); }
.final-inner { position: relative; }
.final-inner .section-index { color: var(--brand-blue); }
.final-inner h2 { position: relative; z-index: 2; margin-top: 18px; }
.final-inner > p:not(.section-index) { position: relative; z-index: 2; margin-top: 20px; color: #a6a39b; font-family: var(--font-ui); font-size: 14px; }
.final-inner .button { position: relative; z-index: 2; margin-top: 29px; }
.final-inner small { position: relative; z-index: 2; display: block; margin-top: 16px; color: #77746d; font-family: var(--font-ui); font-size: 10px; }
.cta-traces { position: absolute; z-index: 1; right: 0; bottom: -77px; left: 0; width: 100%; height: 155px; opacity: 0.36; }
.cta-traces path { fill: none; stroke: var(--brand-blue); stroke-width: 1; vector-effect: non-scaling-stroke; stroke-dasharray: 8 7; animation: trace-drift 14s linear infinite; }
.cta-traces path:nth-child(2) { stroke: var(--brand-green); animation-duration: 19s; }
.cta-traces path:nth-child(3) { stroke: var(--brand-orange); animation-duration: 23s; }

.landing-footer { color: var(--brand-dark); background: var(--brand-paper); }
.footer-inner { min-height: 84px; display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 28px; }
.footer-brand { color: var(--brand-dark); }
.footer-inner > p { color: #7d7a72; font-family: var(--font-display); font-size: 8px; letter-spacing: 0.08em; text-transform: uppercase; }
.footer-inner nav { justify-self: end; display: flex; align-items: center; gap: 24px; }
.footer-inner nav a { color: #5e5c56; font-family: var(--font-ui); font-size: 11px; }
.footer-inner nav a:hover { color: var(--brand-dark); text-decoration: none; }

@keyframes landing-rise {
  from { opacity: 0; transform: translateY(15px); }
  to { opacity: 1; transform: none; }
}
@keyframes trace-drift {
  to { stroke-dashoffset: -120; }
}
.reveal { animation: landing-rise 720ms var(--ease-out) both; }
.reveal-2 { animation-delay: 110ms; }

@media (max-width: 1080px) {
  .hero { grid-template-columns: 1fr; min-height: auto; padding-block: 76px; }
  .hero-copy { max-width: 720px; }
  .trust-inner { grid-template-columns: repeat(2, 1fr); }
  .trust-inner > div:nth-child(3) { border-left: 0; }
  .workspace-layout { grid-template-columns: 1fr; }
  .workspace-copy { max-width: 610px; }
  .principle-grid { grid-template-columns: repeat(2, 1fr); }
  .principle-grid article:nth-child(3) { border-left: 0; border-top: 1px solid #cbc8be; }
  .principle-grid article:nth-child(4) { border-top: 1px solid #cbc8be; }
}

@media (max-width: 800px) {
  .landing-inner { width: min(100% - 40px, 1280px); }
  .topbar { grid-template-columns: 1fr auto; }
  .topnav { display: none; }
  .hero h1 { font-size: clamp(50px, 11vw, 72px); }
  .section-heading { grid-template-columns: 1fr; gap: 28px; }
  .capability-grid { grid-template-columns: 1fr; }
  .capability,
  .capability:first-child,
  .capability:last-child { padding: 0 0 27px; border-left: 0; border-bottom: 1px solid #ccc9bf; }
  .method-flow { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 24px; }
  .method-flow i { display: none; }
  .footer-inner { grid-template-columns: 1fr auto; }
  .footer-inner > p { display: none; }
}

@media (max-width: 580px) {
  .landing-inner { width: min(100% - 30px, 1280px); }
  .topbar { min-height: 68px; grid-template-columns: 1fr auto; gap: 14px; }
  .wordmark small { display: none; }
  .brand-mark { width: 36px; height: 36px; }
  .top-actions { gap: 0; }
  .top-actions .sign-in { display: none; }
  .nav-access { min-height: 36px; padding-inline: 12px; font-size: 8px; }
  .hero { gap: 49px; padding-block: 57px; }
  .hero h1 { font-size: 42px; line-height: 1.02; }
  .lede { font-size: 14px; }
  .hero-actions { display: grid; }
  .hero-actions .button { width: 100%; }
  .trust-inner { grid-template-columns: 1fr; }
  .trust-inner > div,
  .trust-inner > div:first-child { padding: 18px 0; border-left: 0; border-top: 1px solid var(--brand-rule); }
  .trust-inner > div:first-child { border-top: 0; }
  .product-section,
  .workspace-section,
  .method-section { padding-block: 78px; }
  .section-heading h2,
  .workspace-copy h2,
  .final-inner h2 { font-size: clamp(38px, 11.5vw, 52px); }
  .principle-grid { grid-template-columns: 1fr; }
  .principle-grid article,
  .principle-grid article:first-child { padding: 24px 0; border-left: 0; border-top: 1px solid #cbc8be; }
  .principle-grid article:first-child { border-top: 0; }
  .method-flow { grid-template-columns: 1fr; }
  .final-cta { padding-block: 78px 72px; }
  .footer-inner { min-height: 104px; grid-template-columns: 1fr; padding-block: 20px; }
  .footer-inner nav { justify-self: start; }
}

@media (prefers-reduced-motion: reduce) {
  .reveal,
  .cta-traces path { animation: none; }
  .button,
  .topnav a { transition: none; }
}
</style>
