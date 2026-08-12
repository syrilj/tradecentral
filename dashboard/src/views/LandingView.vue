<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted } from 'vue'
import { api, type StatusPayload, type Readiness, type MarketClock } from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import { num, age, shortDate, DASH } from '@/format'

/**
 * The public overview of the instrument, served at / (with /about redirecting here).
 *
 * This page follows the same contract as every workspace: measured state only,
 * no promotional claims, no illustrative market data. Its primary visual object
 * is the instrument's own live state, read from the local API — when the API
 * is unreachable the page says so, with the remedy, instead of painting zeros.
 */
onMounted(() => document.body.classList.add('edge-landing-mode'))
onUnmounted(() => document.body.classList.remove('edge-landing-mode'))

/* The shell already polls status and readiness for every route; read those
   resources rather than opening duplicate requests. The XNYS clock is
   landing-local because the strip that normally shows it is hidden here. */
const status = inject<Resource<StatusPayload>>('status')!
const readiness = inject<Resource<Readiness>>('readiness')!
const clock = useResource<MarketClock>(() => api.marketClock(), { intervalMs: 60_000 })

const session = computed(() => {
  switch (clock.data.value?.market_session) {
    case 'premarket': return 'PREMARKET'
    case 'regular': return 'REGULAR SESSION'
    case 'after_hours': return 'AFTER HOURS'
    case 'closed': return 'CLOSED'
    case 'replay': return 'REPLAY'
    default: return DASH
  }
})
const sessionLive = computed(() => clock.data.value?.market_session === 'regular')
const sessionNote = computed(() => {
  const c = clock.data.value
  if (!c) return null
  if (c.is_early_close) return 'EARLY CLOSE'
  if (!c.is_trading_day) return 'NON-TRADING DAY'
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
const blockers = computed(() => {
  const reasons = readiness.data.value?.blocking_reasons
  if (!reasons) return null
  return reasons.length
})
const shadow = computed(() => {
  const s = readiness.data.value?.shadow
  if (!s) return DASH
  return `${num(s.n_sessions, 0)} / ${num(s.required, 0)}`
})

/* §13 states: total failure shows the unavailable block with the remedy;
   a failed refresh keeps last-good values and adds a stale marker; a value
   that never arrived renders —. */
const apiDown = computed(() => Boolean(status.error.value && !status.data.value))
const apiStale = computed(() => Boolean(status.error.value && status.data.value))
const contacting = computed(() => status.loading.value && !status.data.value && !status.error.value)
const staleSince = computed(() => age(status.fetchedAt.value))
const statusError = computed(() => status.error.value ?? '')

const boundaries = [
  {
    title: 'No order routing',
    copy: 'Decision support ends at readiness state. The checked-in pipeline contains no broker integration and no order submission path.',
  },
  {
    title: 'Missing stays missing',
    copy: 'Stale, degraded, proxy, and unavailable data are labelled as such. Nothing is smoothed over or zeroed to make a view look complete.',
  },
  {
    title: 'Evidence, not advice',
    copy: 'Backtests, model scores, flow metrics, and shadow outcomes are research evidence — not performance guarantees or investment advice.',
  },
]

const workspaces = [
  { idx: '01', name: 'Desk', path: '/desk', question: 'What is the market posture, and what needs attention now?' },
  { idx: '02', name: 'Market', path: '/market', question: 'What is happening in this symbol, and relative to its peers?' },
  { idx: '03', name: 'Options', path: '/options', question: 'What is the positioning and structure for one underlier?' },
  { idx: '04', name: 'Flow', path: '/flow', question: 'Where is market-wide activity concentrating?' },
  { idx: '05', name: 'Research', path: '/research', question: 'What methods, models, gates, and diagnostics support the claims?' },
]

const specialist = [
  { name: 'Sectors', path: '/sectors', note: 'Rotation and leadership' },
  { name: 'Pulse', path: '/sentiment', note: 'Structure and outliers' },
  { name: 'Momentum', path: '/momentum', note: 'Five-pillar pre-scan' },
  { name: 'Fintel', path: '/fintel', note: 'Short, borrow, ownership' },
  { name: 'Gates', path: '/gates', note: 'Pre-registered verdicts' },
  { name: 'Evolution', path: '/evolution', note: 'GA survivors lab' },
  { name: 'Live Blend', path: '/adaptive', note: 'Regime multi-stream' },
  { name: 'Graph', path: '/graph', note: 'Knowledge graph' },
  { name: 'Breaks', path: '/changepoints', note: 'Bayesian regime breaks' },
  { name: 'Cloud', path: '/cloud', note: 'Vertex AI training' },
]

const layers = [
  {
    idx: '01',
    title: 'Research and evaluation',
    copy: 'Point-in-time datasets and leak-resistant walk-forward evaluation. Expensive artifacts are built offline and served cheaply, so incidental polling never recomputes research.',
  },
  {
    idx: '02',
    title: 'Decision support',
    copy: 'Typed candidate contracts, provider adapters, evidence fusion, and options validation. Ordinal research scores are never silently converted into calibrated probability.',
  },
  {
    idx: '03',
    title: 'Gates and governance',
    copy: 'Pre-registered GO/NO-GO criteria with versioned artifacts. A readiness lamp is an operator interlock, not a substitute for strategy-specific promotion criteria.',
  },
  {
    idx: '04',
    title: 'Shadow evidence',
    copy: 'Candidates are tracked through a shadow-only lifecycle across sessions before any promotion is considered. What has not been measured is shown as unmeasured.',
  },
]
</script>

<template>
  <div class="landing-page">
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="TradeCentral overview">
        <span class="brand-word">EDGE</span>
        <span class="brand-rule" aria-hidden="true" />
        <span class="brand-sub label">TradeCentral · Research instrument</span>
      </RouterLink>

      <nav class="topnav" aria-label="Overview">
        <a href="#workspaces">Workspaces</a>
        <a href="#method">Method</a>
        <RouterLink to="/gates">Gates</RouterLink>
      </nav>

      <RouterLink class="btn btn-primary topbar-cta" to="/desk">
        Open the desk <span aria-hidden="true">→</span>
      </RouterLink>
    </header>

    <main>
      <section class="hero">
        <div class="hero-copy rise">
          <p class="kicker label"><i class="kicker-dot" aria-hidden="true" /> Local-first · US equities &amp; options · Loopback only</p>
          <h1>Markets, measured honestly.</h1>
          <p class="lede">
            TradeCentral is a quantitative research and decision-support workstation.
            It surfaces candidates, diagnostics, options structure, and readiness
            state — and keeps the difference between measured, inferred, and missing
            visible at all times.
          </p>
          <div class="hero-actions">
            <RouterLink class="btn btn-primary" to="/desk">
              Open the desk <span aria-hidden="true">→</span>
            </RouterLink>
            <RouterLink class="btn btn-ghost" to="/research">Inspect the research</RouterLink>
          </div>
          <p class="hero-note label">Research instrument · Not an execution terminal</p>
        </div>

        <aside class="state ticked rise" aria-label="Instrument state, live from the local API">
          <header class="state-head">
            <span class="label">Instrument state</span>
            <span class="state-lamp" :class="{ live: sessionLive }">
              <i aria-hidden="true" />{{ session }}
            </span>
          </header>

          <div v-if="apiDown" class="state-down" role="status">
            <span class="label down-label">Local API unavailable</span>
            <p>
              The instrument cannot report its state because the local API is not
              responding. Nothing is shown in its place.
            </p>
            <code>bash edge/tools/run_dashboard.sh</code>
            <span class="state-err">{{ statusError }}</span>
          </div>

          <template v-else>
            <dl class="state-grid">
              <div class="state-row">
                <dt>Session · XNYS</dt>
                <dd>{{ session }}<span v-if="sessionNote" class="row-sub"> · {{ sessionNote }}</span></dd>
              </div>
              <div class="state-row">
                <dt>Data as of</dt>
                <dd>{{ dataAsof }}</dd>
              </div>
              <div class="state-row">
                <dt>Broad universe · Symbols</dt>
                <dd>{{ universe }}</dd>
              </div>
              <div class="state-row">
                <dt>Searchable · Symbols</dt>
                <dd>{{ searchable }}</dd>
              </div>
              <div class="state-row">
                <dt>Gate verdicts</dt>
                <dd v-if="gates" class="gate-mix">
                  <span class="go">{{ num(gates.go, 0) }} GO</span>
                  <span class="nogo">{{ num(gates.no_go, 0) }} NO-GO</span>
                  <span class="unk">{{ num(gates.unknown, 0) }} UNKNOWN</span>
                </dd>
                <dd v-else>{{ DASH }}</dd>
              </div>
              <div class="state-row">
                <dt>Live readiness</dt>
                <dd :class="readiness.data ? (cleared ? 'readiness-ok' : 'readiness-warn') : ''">
                  {{ readinessLabel }}<span v-if="blockers !== null && !cleared" class="row-sub"> · {{ blockers }} blocking</span>
                </dd>
              </div>
              <div class="state-row">
                <dt>Shadow evidence · Sessions</dt>
                <dd>{{ shadow }}</dd>
              </div>
            </dl>

            <footer class="state-foot">
              <span v-if="apiStale" class="state-stale">Stale · Last good {{ staleSince }} ago</span>
              <span v-else-if="contacting">Contacting local API…</span>
              <span v-else>Measured now · Local API · 127.0.0.1</span>
            </footer>
          </template>
        </aside>
      </section>

      <section class="bounds" aria-label="Operating boundaries">
        <div v-for="b in boundaries" :key="b.title" class="bound">
          <h2 class="label">{{ b.title }}</h2>
          <p>{{ b.copy }}</p>
        </div>
      </section>

      <section id="workspaces" class="workspaces">
        <header class="section-head">
          <div>
            <p class="kicker label">Route index</p>
            <h2>Five workspaces. One question each.</h2>
          </div>
          <p class="section-note">
            Specialist surfaces extend the primary five. They do not duplicate them,
            and legacy routes redirect into the workspace that absorbed them.
          </p>
        </header>

        <div class="ws-list">
          <RouterLink v-for="w in workspaces" :key="w.idx" class="ws-row" :to="w.path">
            <span class="ws-idx">{{ w.idx }}</span>
            <span class="ws-name">{{ w.name }}</span>
            <span class="ws-q">{{ w.question }}</span>
            <span class="ws-path">{{ w.path }}</span>
            <span class="ws-arrow" aria-hidden="true">→</span>
          </RouterLink>
        </div>

        <div class="spec-list" aria-label="Specialist surfaces">
          <RouterLink v-for="s in specialist" :key="s.path" class="spec-row" :to="s.path">
            <span class="spec-name">{{ s.name }}</span>
            <span class="spec-note">{{ s.note }}</span>
            <span class="ws-path">{{ s.path }}</span>
          </RouterLink>
        </div>
      </section>

      <section id="method" class="method">
        <header class="section-head">
          <div>
            <p class="kicker label">Operating posture</p>
            <h2>Evidence first. Fail closed.</h2>
          </div>
          <p class="section-note">
            A number on screen can always be traced to the artifact that produced
            it. When the artifact does not exist, the surface says so.
          </p>
        </header>

        <div class="method-grid">
          <article v-for="l in layers" :key="l.idx" class="method-cell">
            <span class="method-idx">{{ l.idx }}</span>
            <h3>{{ l.title }}</h3>
            <p>{{ l.copy }}</p>
          </article>
        </div>
      </section>

      <section class="enter">
        <div>
          <p class="kicker label">No account · No sign-up · One local process</p>
          <h2>The desk is the entry point.</h2>
        </div>
        <RouterLink class="btn btn-primary" to="/desk">
          Open the desk <span aria-hidden="true">→</span>
        </RouterLink>
      </section>
    </main>

    <footer class="landing-footer">
      <span class="footer-brand">EDGE · TradeCentral</span>
      <span class="footer-note label">Research only · No execution · No investment advice</span>
      <nav class="footer-links" aria-label="Footer">
        <RouterLink to="/desk">Desk</RouterLink>
        <RouterLink to="/gates">Gates</RouterLink>
        <RouterLink to="/research">Research</RouterLink>
      </nav>
    </footer>
  </div>
</template>

<style scoped>
/* Hide the operator shell chrome while the public overview is up. */
:global(body.edge-landing-mode) {
  overflow: auto !important;
  background: var(--surface-canvas);
}

:global(body.edge-landing-mode #app) {
  height: auto;
  min-height: 100vh;
  overflow: visible !important;
}

:global(body.edge-landing-mode .shell) {
  display: block !important;
  height: auto !important;
  min-height: 100vh;
  overflow: visible !important;
}

:global(body.edge-landing-mode .rail),
:global(body.edge-landing-mode .strip),
:global(body.edge-landing-mode .foot),
:global(body.edge-landing-mode .skip-link) {
  display: none !important;
}

:global(body.edge-landing-mode .stage) {
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
  background: var(--surface-canvas);
}

.topbar,
.hero,
.bounds,
.workspaces,
.method,
.enter,
.landing-footer {
  width: min(1240px, calc(100% - var(--s7) * 2));
  margin-inline: auto;
}

/* ---- top bar ------------------------------------------------------------ */
.topbar {
  height: var(--s8);
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  border-bottom: var(--hair) solid var(--rule);
}

.brand {
  justify-self: start;
  display: inline-flex;
  align-items: center;
  gap: var(--s3);
  color: var(--ink);
}
.brand:hover { text-decoration: none; }
.brand-word {
  font-family: var(--font-ui);
  font-size: var(--t-lead);
  font-weight: 760;
  letter-spacing: -0.035em;
}
.brand-rule { width: var(--hair); height: var(--s4); background: var(--rule-hi); }
.brand-sub { color: var(--ink-faint); }

.topnav {
  display: flex;
  align-items: center;
  gap: var(--s5);
}
.topnav a {
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: var(--t-micro);
  font-weight: 500;
}
.topnav a:hover { color: var(--ink); text-decoration: none; }

.topbar-cta { justify-self: end; min-height: var(--s6); }

/* ---- buttons ------------------------------------------------------------ */
.btn {
  min-height: var(--s7);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--s3);
  padding: 0 var(--s5);
  border: var(--hair) solid var(--rule-hi);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
}
.btn:hover { text-decoration: none; }
.btn-primary {
  color: var(--void);
  background: var(--phosphor);
  border-color: var(--phosphor);
}
.btn-primary:hover { background: color-mix(in srgb, var(--phosphor) 88%, #ffffff); }
.btn-ghost { color: var(--ink); background: transparent; }
.btn-ghost:hover { border-color: var(--phosphor-dim); color: var(--phosphor); }

/* ---- hero --------------------------------------------------------------- */
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(360px, 0.95fr);
  align-items: center;
  gap: var(--s7);
  padding: var(--s8) 0;
  border-bottom: var(--hair) solid var(--rule);
}

.kicker {
  display: flex;
  align-items: center;
  gap: var(--s2);
  color: var(--ink-faint);
}
.kicker-dot {
  width: var(--s1);
  height: var(--s1);
  background: var(--phosphor);
}

.hero h1 {
  margin-top: var(--s5);
  font-family: var(--font-ui);
  font-size: var(--t-fig-lg);
  font-weight: 650;
  line-height: 1.15;
  letter-spacing: -0.02em;
  max-width: 22ch;
}

.lede {
  margin-top: var(--s5);
  max-width: 58ch;
  color: var(--ink-soft);
  font-size: var(--t-lead);
  line-height: 1.6;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s3);
  margin-top: var(--s6);
}

.hero-note {
  margin-top: var(--s5);
  padding-top: var(--s4);
  border-top: var(--hair) solid var(--rule-faint);
  color: var(--ink-faint);
}

/* ---- instrument state panel --------------------------------------------- */
.state { padding: var(--s5); }

.state-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s4);
  padding-bottom: var(--s3);
  border-bottom: var(--hair) solid var(--rule);
}

.state-lamp {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: var(--track-label);
  color: var(--ink-faint);
}
.state-lamp i {
  width: var(--s2);
  height: var(--s2);
  border-radius: 50%;
  background: var(--rule-hi);
}
.state-lamp.live { color: var(--phosphor); }
.state-lamp.live i { background: var(--phosphor); }

.state-grid { margin-top: var(--s2); }
.state-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s4);
  padding: var(--s3) 0;
  border-bottom: var(--hair) solid var(--rule-faint);
}
.state-row:last-child { border-bottom: 0; }
.state-row dt {
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ink-faint);
  white-space: nowrap;
}
.state-row dd {
  font-family: var(--font-data);
  font-size: var(--t-small);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
  text-align: right;
}
.row-sub { color: var(--ink-faint); }

.gate-mix { display: inline-flex; gap: var(--s3); }
.gate-mix .go { color: var(--go); }
.gate-mix .nogo { color: var(--no-go); }
.gate-mix .unk { color: var(--unknown); }

.readiness-ok { color: var(--phosphor); }
.readiness-warn { color: var(--warn); }

.state-foot {
  margin-top: var(--s4);
  padding-top: var(--s3);
  border-top: var(--hair) solid var(--rule-faint);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ink-faint);
}
.state-stale { color: var(--warn); }

.state-down { padding: var(--s4) 0 var(--s2); }
.down-label { color: var(--warn); }
.state-down p {
  margin-top: var(--s3);
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.55;
}
.state-down code {
  display: inline-block;
  margin-top: var(--s3);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  color: var(--ink);
}
.state-err {
  display: block;
  margin-top: var(--s2);
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  color: var(--ink-faint);
  word-break: break-word;
}

/* ---- boundaries --------------------------------------------------------- */
.bounds {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  border-bottom: var(--hair) solid var(--rule);
}
.bound {
  padding: var(--s6) var(--s5);
  border-left: var(--hair) solid var(--rule);
}
.bound:first-child { border-left: 0; padding-left: 0; }
.bound:last-child { padding-right: 0; }
.bound h2 { color: var(--ink); }
.bound p {
  margin-top: var(--s3);
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.55;
}

/* ---- section headers ---------------------------------------------------- */
.section-head {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: var(--s7);
  align-items: end;
  padding: var(--s8) 0 var(--s6);
}
.section-head h2 {
  margin-top: var(--s3);
  font-family: var(--font-ui);
  font-size: var(--t-display);
  font-weight: 650;
  letter-spacing: var(--track-tight);
}
.section-note {
  max-width: 52ch;
  color: var(--ink-dim);
  font-size: var(--t-body);
  line-height: 1.6;
}

/* ---- route index -------------------------------------------------------- */
.workspaces { border-bottom: var(--hair) solid var(--rule); padding-bottom: var(--s8); }

.ws-list { border-top: var(--hair) solid var(--rule); }
.ws-row {
  display: grid;
  grid-template-columns: var(--s7) 160px minmax(0, 1fr) 110px var(--s5);
  align-items: baseline;
  gap: var(--s4);
  padding: var(--s4) var(--s3);
  border-bottom: var(--hair) solid var(--rule);
  color: var(--ink);
}
.ws-row:hover { text-decoration: none; background: var(--void-lift); }
.ws-idx {
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  color: var(--ink-faint);
}
.ws-name { font-family: var(--font-ui); font-size: var(--t-lead); font-weight: 600; }
.ws-q { color: var(--ink-dim); font-size: var(--t-small); }
.ws-path {
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  color: var(--ink-faint);
  text-align: right;
}
.ws-arrow {
  color: var(--phosphor);
  opacity: 0;
  transition: opacity var(--dur-fast) ease;
  justify-self: end;
}
.ws-row:hover .ws-arrow,
.ws-row:focus-visible .ws-arrow { opacity: 1; }

.spec-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: var(--s6);
  margin-top: var(--s6);
  border-top: var(--hair) solid var(--rule-faint);
}
.spec-row {
  display: grid;
  grid-template-columns: 140px minmax(0, 1fr) 110px;
  align-items: baseline;
  gap: var(--s4);
  padding: var(--s3) var(--s3);
  border-bottom: var(--hair) solid var(--rule-faint);
  color: var(--ink);
}
.spec-row:hover { text-decoration: none; background: var(--void-lift); }
.spec-name { font-family: var(--font-ui); font-size: var(--t-small); font-weight: 600; }
.spec-note { color: var(--ink-faint); font-size: var(--t-tiny); }

/* ---- method ------------------------------------------------------------- */
.method { border-bottom: var(--hair) solid var(--rule); padding-bottom: var(--s8); }
.method-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-top: var(--hair) solid var(--rule);
  border-left: var(--hair) solid var(--rule);
}
.method-cell {
  padding: var(--s5);
  border-right: var(--hair) solid var(--rule);
  border-bottom: var(--hair) solid var(--rule);
}
.method-idx {
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  color: var(--phosphor-dim);
}
.method-cell h3 {
  margin-top: var(--s3);
  font-family: var(--font-ui);
  font-size: var(--t-body);
  font-weight: 650;
}
.method-cell p {
  margin-top: var(--s2);
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.6;
}

/* ---- entry -------------------------------------------------------------- */
.enter {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s6);
  padding: var(--s8) 0;
  border-bottom: var(--hair) solid var(--rule);
}
.enter h2 {
  margin-top: var(--s3);
  font-family: var(--font-ui);
  font-size: var(--t-display);
  font-weight: 650;
  letter-spacing: var(--track-tight);
}

/* ---- footer ------------------------------------------------------------- */
.landing-footer {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  padding: var(--s5) 0;
  color: var(--ink-faint);
}
.footer-brand { font-family: var(--font-ui); font-size: var(--t-body); font-weight: 700; color: var(--ink); }
.footer-links { justify-self: end; display: flex; gap: var(--s5); }
.footer-links a {
  color: var(--ink-faint);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
}
.footer-links a:hover { color: var(--ink); text-decoration: none; }

/* ---- responsive --------------------------------------------------------- */
@media (max-width: 1080px) {
  .topbar { grid-template-columns: 1fr auto; }
  .topnav { display: none; }
  .hero { grid-template-columns: 1fr; padding: var(--s7) 0; }
  .bounds { grid-template-columns: 1fr; }
  .bound { border-left: 0; border-top: var(--hair) solid var(--rule); padding: var(--s5) 0; }
  .bound:first-child { border-top: 0; }
  .section-head { grid-template-columns: 1fr; gap: var(--s4); padding: var(--s7) 0 var(--s5); }
  .ws-row { grid-template-columns: var(--s7) minmax(0, 1fr) var(--s5); }
  .ws-q { grid-column: 2; }
  .ws-path { display: none; }
  .spec-list { grid-template-columns: 1fr; }
}

@media (max-width: 680px) {
  .topbar,
  .hero,
  .bounds,
  .workspaces,
  .method,
  .enter,
  .landing-footer {
    width: calc(100% - var(--s5) * 2);
  }
  .brand-sub { display: none; }
  .hero-actions { flex-direction: column; align-items: stretch; }
  .spec-row { grid-template-columns: minmax(0, 1fr) 110px; }
  .spec-note { display: none; }
  .method-grid { grid-template-columns: 1fr; }
  .enter { flex-direction: column; align-items: flex-start; }
  .landing-footer { grid-template-columns: 1fr auto; }
  .footer-note { display: none; }
}
</style>
