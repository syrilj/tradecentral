<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import TradeCentralMark from '@/components/TradeCentralMark.vue'

/**
 * Structural preview of the Flow workspace for the public page.
 *
 * Anatomy only: real workspace chrome, index names, and badge vocabulary —
 * no invented quotes, premiums, ranks, or scores. Live prints appear after
 * the operator signs in and the local API returns a measured window.
 */
const nav = [
  { icon: 'desk', label: 'Desk', on: false },
  { icon: 'market', label: 'Market', on: false },
  { icon: 'options', label: 'Options', on: false },
  { icon: 'flow', label: 'Flow', on: true },
  { icon: 'research', label: 'Research', on: false },
] as const

/* Sparkline shapes — trajectory anatomy, no figures attached. */
const gauges = [
  { sym: 'SPY', label: 'S&P 500', d: 'M1 15 C6 13 9 9 14 10 S22 14 27 8 35 4 41 7 47 5 48 3' },
  { sym: 'QQQ', label: 'Nasdaq', d: 'M1 16 C7 15 10 8 16 11 S24 15 29 9 37 5 42 8 47 6 48 4' },
  { sym: 'DIA', label: 'Dow', d: 'M1 12 C6 14 11 15 16 12 S24 7 29 10 37 13 42 9 47 8 48 8' },
  { sym: 'IWM', label: 'Russell', d: 'M1 8 C7 7 10 13 16 11 S23 5 29 8 36 14 42 11 47 10 48 12' },
  { sym: 'VIX', label: 'Volatility', d: 'M1 6 C6 8 10 4 15 7 S23 13 28 10 36 5 41 9 47 12 48 14' },
] as const

/* Gamma-by-strike anatomy: bar proportions are visual only. */
const strikes = [
  { call: 18, put: 44 },
  { call: 26, put: 58 },
  { call: 41, put: 36 },
  { call: 68, put: 22 },
  { call: 52, put: 30 },
  { call: 84, put: 12 },
  { call: 46, put: 26 },
  { call: 30, put: 38 },
  { call: 22, put: 30 },
] as const

const queue = [
  { idx: '01', badge: 'sweep', badgeLabel: 'SWEEP', note: 'Largest premium print in the window', a: '74%', b: '42%' },
  { idx: '02', badge: 'golden-sweep', badgeLabel: 'GOLDEN', note: 'Repeat aggression across strikes', a: '58%', b: '66%' },
  { idx: '03', badge: 'block', badgeLabel: 'BLOCK', note: 'Nearest dated institutional size', a: '63%', b: '31%' },
] as const
</script>

<template>
  <figure class="mock" aria-label="Flow workspace layout. Live prints appear after sign-in.">
    <span class="float-chip chip-tr" aria-hidden="true"><i />Gamma flip located</span>
    <span class="float-chip chip-bl" aria-hidden="true"><i />Unusual activity</span>

    <div class="frame">
      <header class="chrome" aria-hidden="true">
        <span class="dots"><i /><i /><i /></span>
        <span class="chrome-title">TRADECENTRAL · FLOW</span>
        <span class="chrome-live"><i class="lamp" />LIVE</span>
      </header>

      <div class="shell">
        <aside class="rail" aria-hidden="true">
          <span class="mark"><TradeCentralMark :size="24" /></span>
          <span v-for="item in nav" :key="item.label" class="rail-item" :class="{ on: item.on }">
            <AppIcon :name="item.icon" :size="16" />
            <small>{{ item.label }}</small>
          </span>
        </aside>

        <header class="strip" aria-hidden="true">
          <span v-for="g in gauges" :key="g.sym" class="gauge">
            <span class="g-head"><b>{{ g.sym }}</b><small>{{ g.label }}</small></span>
            <svg viewBox="0 0 48 20" preserveAspectRatio="none"><path :d="g.d" /></svg>
          </span>
        </header>

        <main class="stage">
          <section class="gamma" aria-label="Illustrative dealer gamma profile by strike">
            <header class="p-head">
              <span class="idx">01</span>
              <span class="p-label">Dealer gamma · by strike</span>
              <span class="p-meta">ILLUSTRATIVE</span>
            </header>
            <div class="gamma-plot">
              <span class="zero" aria-hidden="true" />
              <span class="flip" aria-hidden="true"><em>FLIP</em></span>
              <div class="bars" aria-hidden="true">
                <span v-for="(s, i) in strikes" :key="i" class="strike">
                  <i class="call" :style="{ height: `${s.call}%` }" />
                  <i class="put" :style="{ height: `${s.put}%` }" />
                </span>
              </div>
              <svg class="net" viewBox="0 0 360 150" preserveAspectRatio="none" aria-hidden="true">
                <path d="M8 112 C50 100 78 116 118 88 S188 100 232 58 310 74 352 26" />
                <circle cx="118" cy="88" r="3.5" />
                <circle cx="232" cy="58" r="3.5" />
                <circle cx="352" cy="26" r="3.5" />
              </svg>
            </div>
            <footer class="legend" aria-hidden="true">
              <span><i class="lg-call" />Call GEX</span>
              <span><i class="lg-put" />Put GEX</span>
              <span><i class="lg-net" />Net profile</span>
            </footer>
          </section>

          <section class="queue" aria-label="Illustrative flow attention queue">
            <header class="p-head">
              <span class="idx">02</span>
              <span class="p-label">Attention queue</span>
              <span class="p-meta">UNSIGNED</span>
            </header>
            <article v-for="row in queue" :key="row.idx" class="q-row">
              <span class="q-idx fig">{{ row.idx }}</span>
              <span class="q-body">
                <span class="flow-badge" :class="`badge-${row.badge}`">{{ row.badgeLabel }}</span>
                <span class="q-note">{{ row.note }}</span>
                <span class="q-bars" aria-hidden="true">
                  <i :style="{ width: row.a }" />
                  <i :style="{ width: row.b }" />
                </span>
              </span>
              <AppIcon class="q-chevron" name="chevron" :size="13" />
            </article>
            <p class="q-foot">Ranked by premium, never by promise.</p>
          </section>
        </main>
      </div>
    </div>

    <figcaption><span class="cap-dot" aria-hidden="true" />Illustrative anatomy · live prints after sign-in</figcaption>
  </figure>
</template>

<style scoped>
.mock {
  position: relative;
  display: block;
  width: 100%;
  margin: 0;
}

/* ---- floating annotation chips ------------------------------------------- */
.float-chip {
  position: absolute;
  z-index: 3;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  color: var(--ink-soft);
  font-family: var(--font-data);
  font-size: 8px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  white-space: nowrap;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
  background: var(--panel-hi);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.5);
  animation: chip-float 7s var(--ease-in-out) infinite;
}
.float-chip i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--phosphor);
  animation: pulse-lamp 2.4s var(--ease-in-out) infinite;
}
.chip-tr { top: -13px; right: 26px; }
.chip-bl { bottom: 46px; left: -16px; animation-delay: 1.6s; }
@keyframes chip-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-5px); }
}

/* ---- window frame --------------------------------------------------------- */
.frame {
  overflow: hidden;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-lg);
  background: var(--void);
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.55), 0 4px 16px rgba(0, 0, 0, 0.4);
}

.chrome {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 36px;
  padding: 0 14px;
  border-bottom: var(--hair) solid var(--rule);
  background: var(--void-lift);
}
.dots { display: inline-flex; gap: 5px; }
.dots i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--rule-hi);
}
.chrome-title {
  flex: 1 1 auto;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: 8px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-align: center;
}
.chrome-live {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--phosphor);
  font-family: var(--font-data);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.12em;
}
.lamp {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--phosphor);
  animation: pulse-lamp 2.4s var(--ease-in-out) infinite;
}

.shell {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  grid-template-rows: 58px minmax(0, 1fr);
  grid-template-areas:
    'rail strip'
    'rail stage';
  min-height: 470px;
}

/* ---- rail ----------------------------------------------------------------- */
.rail {
  grid-area: rail;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 8px;
  border-right: var(--hair) solid var(--rule);
  background: var(--void-lift);
}
.mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  margin: 0 auto 10px;
  color: var(--phosphor);
}
.rail-item {
  min-height: 44px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  color: var(--ink-faint);
  border-radius: var(--r-sm);
}
.rail-item small {
  font-family: var(--font-data);
  font-size: 7px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.rail-item.on {
  color: var(--ink);
  background: var(--panel-hi);
  outline: var(--hair) solid var(--rule);
}

/* ---- strip gauges ---------------------------------------------------------- */
.strip {
  grid-area: strip;
  display: flex;
  align-items: stretch;
  border-bottom: var(--hair) solid var(--rule);
  background: rgba(13, 15, 20, 0.9);
}
.gauge {
  flex: 1 1 0;
  min-width: 0;
  display: grid;
  grid-template-rows: auto 1fr;
  gap: 4px;
  padding: 8px 10px 7px;
  border-right: var(--hair) solid var(--rule);
}
.gauge:last-child { border-right: 0; }
.g-head {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}
.g-head b {
  color: var(--ink);
  font-family: var(--font-data);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.g-head small {
  color: var(--ink-ghost);
  font-family: var(--font-data);
  font-size: 7px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.gauge svg {
  width: 100%;
  height: 18px;
  align-self: end;
}
.gauge svg path {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1.4;
  stroke-linecap: round;
  vector-effect: non-scaling-stroke;
  opacity: 0.85;
}

/* ---- stage ----------------------------------------------------------------- */
.stage {
  grid-area: stage;
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr);
  gap: 10px;
  padding: 12px;
  overflow: hidden;
}

.p-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding: 0 10px;
  border-bottom: var(--hair) solid var(--rule-faint);
  background: var(--panel-hi);
}
.p-head .idx {
  color: var(--phosphor);
  font-family: var(--font-data);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 5px;
  border: var(--hair) solid color-mix(in srgb, var(--phosphor) 20%, transparent);
  border-radius: var(--r-xs);
  background: var(--phosphor-wash);
}
.p-label {
  flex: 1 1 auto;
  color: var(--ink);
  font-family: var(--font-data);
  font-size: 8px;
  font-weight: 600;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.p-meta {
  color: var(--ink-ghost);
  font-family: var(--font-data);
  font-size: 7px;
  letter-spacing: 0.08em;
}

/* ---- gamma panel ------------------------------------------------------------ */
.gamma {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  background: var(--panel);
}
.gamma-plot {
  position: relative;
  flex: 1 1 auto;
  min-height: 168px;
  margin: 12px 12px 6px;
}
.zero {
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  height: 1px;
  background: var(--rule-hi);
}
.flip {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 56%;
  border-left: 1px dashed color-mix(in srgb, var(--warn) 55%, transparent);
}
.flip em {
  position: absolute;
  top: -2px;
  left: 5px;
  color: var(--warn);
  font-family: var(--font-data);
  font-size: 7px;
  font-style: normal;
  font-weight: 700;
  letter-spacing: 0.1em;
}
.bars {
  position: absolute;
  inset: 0;
  display: flex;
  gap: 7px;
}
.strike {
  position: relative;
  flex: 1 1 0;
  height: 100%;
}
.strike i {
  position: absolute;
  left: 50%;
  width: 8px;
  transform: translateX(-50%);
}
.strike .call {
  bottom: 50%;
  border-radius: 2px 2px 0 0;
  background: var(--call);
}
.strike .put {
  top: 50%;
  border-radius: 0 0 2px 2px;
  background: var(--put);
}
.net {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
.net path {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1.5;
  stroke-linecap: round;
  vector-effect: non-scaling-stroke;
}
.net circle {
  fill: var(--void);
  stroke: var(--phosphor);
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
}
.legend {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 8px 12px 10px;
}
.legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: 7px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.legend i {
  width: 8px;
  height: 8px;
  border-radius: 2px;
}
.legend .lg-call { background: var(--call); }
.legend .lg-put { background: var(--put); }
.legend .lg-net {
  border-radius: 50%;
  background: transparent;
  border: 1.5px solid var(--phosphor);
}

/* ---- queue panel ------------------------------------------------------------- */
.queue {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  background: var(--panel);
}
.q-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border-bottom: var(--hair) solid var(--rule-faint);
  transition: background var(--dur-fast) var(--ease-out);
}
.q-row:hover { background: var(--panel-hi); }
.q-idx {
  flex: 0 0 auto;
  color: var(--ink-ghost);
  font-size: 9px;
  font-weight: 600;
}
.q-body {
  flex: 1 1 auto;
  min-width: 0;
  display: grid;
  gap: 5px;
}
.q-note {
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: 9px;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.q-bars {
  display: grid;
  gap: 3px;
}
.q-bars i {
  height: 2px;
  border-radius: 1px;
  background: var(--rule-hi);
}
.q-bars i:first-child { background: color-mix(in srgb, var(--phosphor) 45%, var(--rule)); }
.q-chevron {
  flex: 0 0 auto;
  color: var(--ink-ghost);
}
.q-foot {
  margin-top: auto;
  padding: 10px 12px;
  color: var(--ink-faint);
  font-family: var(--font-ui);
  font-size: 9px;
  font-style: italic;
}

figcaption {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: 8px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.cap-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--phosphor);
}

@media (max-width: 1080px) {
  .float-chip { display: none; }
}
@media (max-width: 860px) {
  .shell {
    grid-template-columns: 1fr;
    grid-template-rows: 52px minmax(0, 1fr);
    grid-template-areas: 'strip' 'stage';
    min-height: 0;
  }
  .rail { display: none; }
  .stage { grid-template-columns: 1fr; }
  .gauge:nth-child(n + 4) { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .float-chip,
  .float-chip i,
  .lamp { animation: none; }
}
</style>
