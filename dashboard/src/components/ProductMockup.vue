<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import TradeCentralMark from '@/components/TradeCentralMark.vue'

/**
 * Structural preview of the Flow workspace.
 *
 * This is chrome only: real index names and operator labels, no invented
 * premiums, ranks, or signed-flow conclusions. Live prints appear after
 * the operator signs in and the local API returns a measured window.
 */
const nav = [
  { icon: 'desk', label: 'Desk', on: false },
  { icon: 'market', label: 'Market', on: false },
  { icon: 'options', label: 'Options', on: false },
  { icon: 'flow', label: 'Flow', on: true },
  { icon: 'research', label: 'Research', on: false },
] as const

const majors = [
  { symbol: 'SPY', focus: 'Index tape first' },
  { symbol: 'QQQ', focus: 'Nasdaq concentration' },
  { symbol: 'IWM', focus: 'Small-cap tape' },
  { symbol: 'DIA', focus: 'Dow concentration' },
] as const

const queue = [
  { slot: '01', label: 'Open first', question: 'Highest-review name after the window lands' },
  { slot: '02', label: 'Sweep cluster', question: 'Largest sweep premium, if the provider sent one' },
  { slot: '03', label: 'Shortest DTE', question: 'Nearest dated activity, not a trade ticket' },
] as const
</script>

<template>
  <figure class="product-mock" aria-label="Flow workspace layout. Live prints appear after sign-in.">
    <div class="shell">
      <aside class="rail" aria-hidden="true">
        <span class="mark"><TradeCentralMark :size="24" /></span>
        <span v-for="item in nav" :key="item.label" class="rail-item" :class="{ on: item.on }">
          <AppIcon :name="item.icon" :size="16" />
          <small>{{ item.label }}</small>
        </span>
      </aside>

      <header class="strip" aria-hidden="true">
        <span class="gauge">
          <span class="g-head"><span class="label">VIX</span><span class="label dim">VOL</span></span>
          <span class="g-val fig">—</span>
        </span>
        <span class="gauge">
          <span class="g-head"><span class="label">SPY</span><span class="label dim">S&P 500</span></span>
          <span class="g-val fig">—</span>
        </span>
        <span class="gauge">
          <span class="g-head"><span class="label">QQQ</span><span class="label dim">Nasdaq</span></span>
          <span class="g-val fig">—</span>
        </span>
        <span class="gauge">
          <span class="g-head"><span class="label">DIA</span><span class="label dim">Dow</span></span>
          <span class="g-val fig">—</span>
        </span>
        <span class="gauge">
          <span class="g-head"><span class="label">XLE</span><span class="label dim">Energy</span></span>
          <span class="g-val fig">—</span>
        </span>
      </header>

      <main class="stage">
        <Panel label="Desk brief" index="01" meta="FLOW · MARKET-WIDE TAPE" live>
          <div class="brief">
            <div class="brief-copy">
              <h3>Inspect the window. Then open one chain.</h3>
              <p>Activity lean is descriptive. Missing stays missing. No illustrative values.</p>
            </div>
            <div class="queue">
              <article v-for="item in queue" :key="item.slot">
                <small>{{ item.slot }} · {{ item.label }}</small>
                <strong>SYM —</strong>
                <em>{{ item.question }}</em>
              </article>
            </div>
          </div>
        </Panel>

        <Panel label="Index majors" index="02" meta="UNSIGNED UNTIL PROVIDER MARKS BUY/SELL">
          <div class="majors">
            <article v-for="major in majors" :key="major.symbol">
              <header>
                <strong>{{ major.symbol }}</strong>
                <span>INDEX</span>
              </header>
              <Readout label="Window premium" value="—" size="sm" />
              <Readout label="Activity lean" value="Unknown" size="sm" />
              <p>{{ major.focus }}</p>
              <i class="bar" aria-hidden="true"><b /><b /></i>
            </article>
          </div>
        </Panel>
      </main>
    </div>
    <figcaption>Layout only · live prints after sign-in · no illustrative quotes</figcaption>
  </figure>
</template>

<style scoped>
.product-mock {
  display: block;
  width: 100%;
  margin: 0;
}

.shell {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  grid-template-rows: 52px minmax(0, 1fr);
  grid-template-areas:
    'rail strip'
    'rail stage';
  min-height: 460px;
  overflow: hidden;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
}

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
  transition: background var(--dur-fast), color var(--dur-fast);
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
  grid-template-rows: auto auto;
  justify-content: center;
  gap: 4px;
  padding: 0 10px;
  border-right: var(--hair) solid var(--rule);
}
.gauge:last-child { border-right: 0; }
.g-head { display: flex; align-items: center; gap: 6px; }
.g-head .label { color: var(--ink); font-size: 8px; }
.g-head .label.dim { color: var(--ink-ghost); font-size: 7px; }
.g-val { color: var(--ink-dim); font-size: var(--t-small); font-weight: 600; }

.stage {
  grid-area: stage;
  min-width: 0;
  display: grid;
  gap: 12px;
  padding: 12px;
  overflow: hidden;
}

.brief {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.4fr);
  gap: 10px;
}
.brief-copy h3 {
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.2;
}
.brief-copy p {
  margin-top: 8px;
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: 11px;
  line-height: 1.45;
}
.queue {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.queue article {
  display: grid;
  align-content: start;
  gap: 6px;
  padding: 10px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--void-lift);
}
.queue small {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: 7px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.queue strong {
  color: var(--ink);
  font-family: var(--font-data);
  font-size: 14px;
  font-weight: 500;
}
.queue em {
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: 10px;
  font-style: normal;
  line-height: 1.35;
}

.majors {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
.majors article {
  min-width: 0;
  display: grid;
  gap: 8px;
  padding: 10px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--void-lift);
}
.majors header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.majors header strong {
  color: var(--ink);
  font-family: var(--font-data);
  font-size: 13px;
}
.majors header span {
  color: var(--call);
  font-family: var(--font-data);
  font-size: 7px;
  letter-spacing: 0.08em;
}
.majors p {
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: 10px;
}
.bar {
  display: flex;
  height: 3px;
  border-radius: 2px;
  background: var(--rule);
  overflow: hidden;
}
.bar b:first-child { flex: 1.1; background: var(--call); }
.bar b:last-child { flex: 0.9; background: var(--put); }

figcaption {
  margin-top: 10px;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: 8px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

@media (max-width: 860px) {
  .shell { grid-template-columns: 1fr; grid-template-rows: 52px minmax(0, 1fr); grid-template-areas: 'strip' 'stage'; }
  .rail { display: none; }
  .brief,
  .queue,
  .majors { grid-template-columns: 1fr; }
  .majors article:nth-child(n + 3) { display: none; }
}
</style>
