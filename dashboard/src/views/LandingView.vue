<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted } from 'vue'
import { api, type MarketClock, type Readiness, type StatusPayload } from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import { age, DASH, num, shortDate } from '@/format'
import AppIcon from '@/components/AppIcon.vue'
import EvidenceLayerVisual from '@/components/EvidenceLayerVisual.vue'
import GexFlowVisual from '@/components/GexFlowVisual.vue'
import LiveStateVisual from '@/components/LiveStateVisual.vue'
import Panel from '@/components/Panel.vue'
import ProductMockup from '@/components/ProductMockup.vue'
import Readout from '@/components/Readout.vue'
import ResearchLoopVisual from '@/components/ResearchLoopVisual.vue'
import TradeCentralMark from '@/components/TradeCentralMark.vue'

/**
 * Public product overview.
 *
 * Market figures shown here come from the same loopback resources as the
 * operator shell. Product diagrams carry only labels and system boundaries;
 * there are no illustrative quotes, returns, or invented model scores.
 */
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

/* ---- entrance motion ------------------------------------------------------
   CSS-only, one pass, and fully disabled under prefers-reduced-motion.
   The page must read instantly without JavaScript. */
onMounted(() => {
  document.body.classList.add('edge-public-mode')
})

onUnmounted(() => {
  document.body.classList.remove('edge-public-mode')
})
</script>

<template>
  <div class="landing-page">
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
        </nav>

        <div class="top-actions">
          <RouterLink class="sign-in" :to="{ name: 'auth', query: { mode: 'signin', redirect: '/flow' } }">
            Sign in
          </RouterLink>
          <RouterLink class="button button-accent" :to="{ name: 'auth', query: { mode: 'setup', redirect: '/flow' } }">
            Create access <AppIcon name="arrow-right" :size="15" />
          </RouterLink>
        </div>
      </div>
    </header>

    <main>
      <section class="hero landing-inner">
        <div class="hero-copy">
          <p class="eyebrow reveal"><span aria-hidden="true" /> US equities · options intelligence</p>
          <h1 class="reveal">Read the market<br><em>beneath the price.</em></h1>
          <p class="lede reveal">
            TradeCentral brings dealer positioning, options flow, and research
            controls into one evidence-first view—so a move has context before it
            has a narrative.
          </p>
          <div class="hero-actions reveal">
            <RouterLink class="button button-accent" :to="{ name: 'auth', query: { redirect: '/flow' } }">
              Explore market flow <AppIcon name="arrow-right" :size="16" />
            </RouterLink>
            <a class="button button-quiet" href="#product">
              See what you get <AppIcon name="arrow-down" :size="15" />
            </a>
          </div>
          <div class="hero-boundary reveal">
            <AppIcon name="shield" :size="16" />
            <span><strong>Research only.</strong> No order routing. No performance promises.</span>
          </div>
        </div>

        <div class="hero-visual reveal">
          <p class="hero-kicker">The Flow workspace · structural preview</p>
          <ProductMockup />
        </div>
      </section>

      <section class="stats-section" aria-label="Live instrument state">
        <div class="landing-inner stats-strip">
          <Readout label="Symbols tracked" :value="universe" sub="Broad universe" size="lg" />
          <Readout label="Searchable" :value="searchable" sub="Symbols" size="lg" />
          <Readout label="Gates cleared" :value="num(gates?.go, 0)" sub="Pre-registered" size="lg" tone="accent" />
          <Readout label="Shadow sessions" :value="shadow" sub="Evidence" size="lg" />
        </div>
      </section>

      <section class="live-proof-section">
        <LiveStateVisual
          class="landing-inner scroll-reveal"
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

      <section id="product" class="product-section">
        <div class="landing-inner">
          <header class="section-heading scroll-reveal">
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
            <Panel
              v-for="capability in capabilities"
              :key="capability.index"
              class="capability scroll-reveal"
              :label="capability.title"
              :index="capability.index"
              :meta="capability.detail"
            >
              <EvidenceLayerVisual :kind="capability.kind" />
              <p class="capability-copy">{{ capability.copy }}</p>
            </Panel>
          </div>
        </div>
      </section>

      <section class="flow-section">
        <div class="landing-inner flow-layout">
          <div class="flow-copy scroll-reveal">
            <p class="section-index">OPTIONS INTELLIGENCE / 02</p>
            <h2>See the structure<br>behind a move.</h2>
            <p>
              Map dealer gamma by strike, locate the flip, and inspect the tape.
              Calls, puts, and unsigned activity stay separate until the provider
              gives a side.
            </p>
            <RouterLink class="text-link" :to="{ name: 'auth', query: { redirect: '/flow' } }">
              Explore market flow <AppIcon name="arrow-right" :size="15" />
            </RouterLink>
          </div>
          <GexFlowVisual class="scroll-reveal" />
        </div>
      </section>

      <section id="workspaces" class="workspace-section">
        <div class="landing-inner workspace-layout">
          <div class="workspace-copy scroll-reveal">
            <p class="section-index">WORKSPACES / 03</p>
            <h2>A research path.<br>Not a menu.</h2>
            <p>
              Each workspace answers one question, then hands its context forward.
              The path stays visible, while specialist tools remain adjacent.
            </p>
            <RouterLink class="text-link" :to="{ name: 'auth', query: { redirect: '/flow' } }">
              Open Flow now <AppIcon name="arrow-right" :size="15" />
            </RouterLink>
          </div>

          <ResearchLoopVisual class="scroll-reveal" />
        </div>
      </section>

      <section id="method" class="method-section">
        <div class="landing-inner">
          <header class="section-heading method-heading scroll-reveal">
            <div>
              <p class="section-index">METHOD / 04</p>
              <h2>Trust is a system property.</h2>
            </div>
            <p>
              TradeCentral separates research, decision support, readiness, and
              execution authorization. A polished surface never gets to erase that boundary.
            </p>
          </header>

          <div class="principle-grid">
            <Panel
              v-for="principle in principles"
              :key="principle.index"
              class="principle scroll-reveal"
              :label="principle.title"
              :index="principle.index"
            >
              <p class="principle-copy">{{ principle.copy }}</p>
            </Panel>
          </div>

          <div class="method-flow scroll-reveal" aria-label="Evidence lifecycle">
            <span><AppIcon name="database" :size="16" />DATA</span><i />
            <span><AppIcon name="research" :size="16" />RESEARCH</span><i />
            <span><AppIcon name="gate" :size="16" />GATES</span><i />
            <span><AppIcon name="session" :size="16" />SHADOW</span><i />
            <span><AppIcon name="shield" :size="16" />READINESS</span>
          </div>
        </div>
      </section>

      <section class="final-cta">
        <div class="landing-inner final-inner scroll-reveal">
          <p class="section-index">THE RESEARCH LOOP</p>
          <h2>Build conviction from evidence,<br><em>not presentation.</em></h2>
          <p>One workstation for market context, options structure, and accountable research.</p>
          <RouterLink class="button button-accent" :to="{ name: 'auth', query: { redirect: '/flow' } }">
            Sign in and open Flow <AppIcon name="arrow-right" :size="16" />
          </RouterLink>
          <small>No credit card. No broker connection. Clerk session, then the measured tape.</small>
        </div>
      </section>
    </main>

    <footer class="landing-footer">
      <div class="landing-inner footer-inner">
        <RouterLink class="brand footer-brand" to="/">
          <TradeCentralMark :size="26" />
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
  background: var(--void);
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
  position: relative;
  z-index: 3;
  min-height: 100vh;
  color: var(--ink);
  background: var(--void);
  font-family: var(--font-ui);
}

/* ---- entrance motion ------------------------------------------------------
   CSS-only: the hero resolves in one short pass, sections fade up as they
   enter the viewport. No library, no continuous animation, and everything
   collapses to zero under prefers-reduced-motion. */
@keyframes landing-rise {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: none; }
}
.reveal {
  animation: landing-rise 0.55s var(--ease-out) both;
}
.reveal:nth-child(2) { animation-delay: 0.06s; }
.reveal:nth-child(3) { animation-delay: 0.12s; }
.reveal:nth-child(4) { animation-delay: 0.18s; }
.reveal:nth-child(5) { animation-delay: 0.24s; }
.scroll-reveal {
  animation: landing-rise 0.6s var(--ease-out) both;
  animation-timeline: view();
  animation-range: entry 0% entry 32%;
}
@supports not (animation-timeline: view()) {
  .scroll-reveal { animation: none; }
}

.landing-inner {
  width: min(1240px, calc(100% - 72px));
  margin-inline: auto;
}

/* ---- topbar -------------------------------------------------------------- */
.topbar-shell {
  position: sticky;
  z-index: 20;
  top: 0;
  border-bottom: var(--hair) solid var(--rule);
  background: rgba(8, 9, 12, 0.9);
  backdrop-filter: blur(16px);
}
.topbar {
  min-height: 72px;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
}
.brand { display: inline-flex; align-items: center; gap: 11px; color: var(--ink); }
.brand:hover { text-decoration: none; }
.brand-mark {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  color: var(--phosphor);
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
}
.wordmark { display: grid; line-height: 1; }
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
.topnav { display: flex; align-items: center; gap: 2px; padding: 3px; border: var(--hair) solid var(--rule); background: var(--void-lift); }
.topnav a,
.sign-in {
  color: var(--ink-soft);
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 500;
}
.topnav a { min-height: 32px; display: inline-flex; align-items: center; gap: 8px; padding: 0 12px; }
.topnav a small { color: var(--ink-ghost); font-family: var(--font-data); font-size: 7px; }
.topnav a:hover,
.sign-in:hover { color: var(--ink); background: var(--panel-hi); text-decoration: none; }
.top-actions { justify-self: end; display: flex; align-items: center; gap: 18px; }
.sign-in { min-height: 36px; display: inline-flex; align-items: center; padding: 0 3px; }

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
  transition: transform var(--dur-fast), background var(--dur-fast), border-color var(--dur-fast), color var(--dur-fast);
}
.button:hover { text-decoration: none; transform: translateY(-1px); }
.button:active { transform: translateY(0); }
.button-accent { color: var(--void); background: var(--phosphor); }
.button-accent:hover { background: var(--phosphor-dim); }
.button-quiet { color: var(--ink); border-color: var(--rule-hi); background: transparent; }
.button-quiet:hover { color: var(--phosphor); border-color: var(--phosphor); }

/* ---- hero ----------------------------------------------------------------- */
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
.hero-visual { position: relative; z-index: 1; }
.hero-visual { min-width: 0; width: 100%; }
.hero-kicker {
  margin: 0 0 12px;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.eyebrow,
.section-index {
  font-family: var(--font-data);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.eyebrow { display: flex; align-items: center; gap: 11px; color: var(--ink-dim); }
.eyebrow span { width: 25px; height: 2px; background: var(--phosphor); }
.hero h1 {
  margin-top: 24px;
  font-family: var(--font-display);
  font-size: clamp(48px, 5.4vw, 76px);
  font-weight: 600;
  line-height: 1.0;
  letter-spacing: -0.04em;
}
.hero h1 em { color: var(--phosphor); font-style: normal; }
.lede {
  margin-top: 26px;
  max-width: 54ch;
  color: var(--ink-soft);
  font-family: var(--font-ui);
  font-size: 16px;
  line-height: 1.7;
}
.hero-actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 34px; }
.hero-boundary {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 26px;
  color: var(--ink-faint);
  font-family: var(--font-ui);
  font-size: 12px;
}
.hero-boundary strong { color: var(--ink-soft); font-weight: 600; }
.hero-boundary .app-icon { color: var(--phosphor); }

/* ---- stats ----------------------------------------------------------------- */
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
.stats-strip :deep(.readout:first-child) { border-left: 0; padding-left: 0; }

/* ---- live proof ----------------------------------------------------------- */
.live-proof-section {
  border-bottom: var(--hair) solid var(--rule);
  background: var(--void);
}

/* ---- product / method sections -------------------------------------------- */
.product-section,
.workspace-section,
.method-section { scroll-margin-top: 72px; }
.product-section { padding-block: 104px; }
.section-heading {
  display: grid;
  grid-template-columns: 1fr minmax(300px, 0.6fr);
  gap: 80px;
  align-items: end;
}
.section-index { color: var(--phosphor); }
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
.capability-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-top: 60px; }
.capability-copy { margin-top: 14px; color: var(--ink-dim); font-family: var(--font-ui); font-size: 13px; line-height: 1.65; }

/* ---- flow section --------------------------------------------------------- */
.flow-section { padding-block: 104px; border-top: var(--hair) solid var(--rule); background: var(--void-lift); }
.flow-layout { display: grid; grid-template-columns: minmax(280px, 0.42fr) minmax(560px, 1fr); gap: clamp(48px, 6vw, 88px); align-items: center; }
.flow-copy { align-self: start; padding-top: 12px; }
.flow-copy .section-index { color: var(--call); }
.flow-copy > p:not(.section-index) { margin-top: 22px; }
.text-link { display: inline-flex; align-items: center; gap: 10px; margin-top: 28px; color: var(--ink); font-family: var(--font-ui); font-size: 13px; font-weight: 600; }
.text-link:hover { color: var(--phosphor); text-decoration: none; }

/* ---- workspaces ----------------------------------------------------------- */
.workspace-section { padding-block: 104px; border-top: var(--hair) solid var(--rule); }
.workspace-layout { display: grid; grid-template-columns: minmax(270px, 0.42fr) minmax(620px, 1fr); gap: clamp(48px, 6vw, 88px); align-items: center; }
.workspace-copy { align-self: start; padding-top: 12px; }
.workspace-copy .section-index { color: var(--call); }
.workspace-copy > p:not(.section-index) { margin-top: 22px; }

/* ---- method --------------------------------------------------------------- */
.method-section { padding-block: 104px; border-top: var(--hair) solid var(--rule); background: var(--void-lift); }
.method-heading { align-items: center; }
.principle-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-top: 56px; }
.principle-copy { color: var(--ink-dim); font-family: var(--font-ui); font-size: 12px; line-height: 1.6; }
.method-flow { display: flex; align-items: center; gap: 12px; margin-top: 44px; }
.method-flow span {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 14px;
  color: var(--ink-soft);
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  font-family: var(--font-data);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.08em;
}
.method-flow span:nth-of-type(1) .app-icon,
.method-flow span:nth-of-type(2) .app-icon { color: var(--call); }
.method-flow span:nth-of-type(3) .app-icon { color: var(--warn); }
.method-flow span:nth-of-type(4) .app-icon,
.method-flow span:nth-of-type(5) .app-icon { color: var(--phosphor); }
.method-flow i { flex: 1; height: 1px; background: var(--rule-hi); }

/* ---- final CTA ------------------------------------------------------------ */
.final-cta {
  position: relative;
  overflow: hidden;
  padding-block: 100px 92px;
  text-align: center;
  border-top: var(--hair) solid var(--rule);
  background: var(--void);
}
.final-inner { position: relative; }
.final-inner .section-index { color: var(--call); }
.final-inner h2 { margin-top: 18px; }
.final-inner h2 em {
  font-family: var(--font-serif);
  font-style: italic;
  font-weight: 500;
  letter-spacing: -0.01em;
}
.final-inner > p:not(.section-index) { margin-top: 20px; color: var(--ink-dim); font-family: var(--font-ui); font-size: 15px; }
.final-inner .button { margin-top: 30px; }
.final-inner small { display: block; margin-top: 16px; color: var(--ink-faint); font-family: var(--font-ui); font-size: 11px; }

/* ---- footer --------------------------------------------------------------- */
.landing-footer { border-top: var(--hair) solid var(--rule); background: var(--void-lift); }
.footer-inner { min-height: 84px; display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 28px; }
.footer-brand { color: var(--ink); }
.footer-inner > p { color: var(--ink-faint); font-family: var(--font-data); font-size: 8px; letter-spacing: 0.08em; text-transform: uppercase; }
.footer-inner nav { justify-self: end; display: flex; align-items: center; gap: 24px; }
.footer-inner nav a { color: var(--ink-dim); font-family: var(--font-ui); font-size: 12px; }
.footer-inner nav a:hover { color: var(--ink); text-decoration: none; }

@media (max-width: 1080px) {
  .hero { grid-template-columns: 1fr; min-height: auto; padding-block: 60px; }
  .hero-copy { max-width: 720px; }
  .stats-strip { grid-template-columns: repeat(2, 1fr); }
  .stats-strip :deep(.readout:nth-child(3)) { border-left: 0; }
  .flow-layout,
  .workspace-layout { grid-template-columns: 1fr; }
  .flow-copy,
  .workspace-copy { max-width: 640px; }
  .principle-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 800px) {
  .landing-inner { width: min(100% - 40px, 1240px); }
  .topbar { grid-template-columns: 1fr auto; }
  .topnav { display: none; }
  .hero h1 { font-size: clamp(44px, 11vw, 68px); }
  .section-heading { grid-template-columns: 1fr; gap: 26px; }
  .capability-grid { grid-template-columns: 1fr; }
  .method-flow { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .method-flow i { display: none; }
  .footer-inner { grid-template-columns: 1fr auto; }
  .footer-inner > p { display: none; }
}

@media (max-width: 580px) {
  .landing-inner { width: min(100% - 30px, 1240px); }
  .topbar { min-height: 64px; grid-template-columns: 1fr auto; gap: 14px; }
  .wordmark small { display: none; }
  .brand-mark { width: 34px; height: 34px; }
  .top-actions { gap: 0; }
  .top-actions .sign-in { display: none; }
  .button { min-height: 40px; padding-inline: 16px; font-size: 11px; }
  .hero { gap: 44px; padding-block: 48px; }
  .hero h1 { font-size: 40px; line-height: 1.04; }
  .lede { font-size: 14px; }
  .hero-actions { display: grid; }
  .hero-actions .button { width: 100%; }
  .stats-strip { grid-template-columns: 1fr; }
  .stats-strip :deep(.readout),
  .stats-strip :deep(.readout:first-child) { padding: 18px 0; border-left: 0; border-top: var(--hair) solid var(--rule); }
  .stats-strip :deep(.readout:first-child) { border-top: 0; }
  .product-section,
  .flow-section,
  .workspace-section,
  .method-section { padding-block: 76px; }
  .section-heading h2,
  .flow-copy h2,
  .workspace-copy h2,
  .final-inner h2 { font-size: clamp(36px, 11vw, 50px); }
  .principle-grid { grid-template-columns: 1fr; }
  .method-flow { grid-template-columns: 1fr; }
  .final-cta { padding-block: 76px 72px; }
  .footer-inner { min-height: 104px; grid-template-columns: 1fr; padding-block: 20px; }
  .footer-inner nav { justify-self: start; }
}

@media (prefers-reduced-motion: reduce) {
  .reveal,
  .scroll-reveal { animation: none; }
  .button,
  .topnav a { transition: none; }
}
</style>
