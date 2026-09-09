<script setup lang="ts">
import TradeCentralMark from '@/components/TradeCentralMark.vue'

/**
 * Structural preview of the Flow workspace.
 *
 * This is chrome only: real index names and operator labels, no invented
 * premiums, ranks, or signed-flow conclusions. Live prints appear after
 * the operator signs in and the local API returns a measured window.
 */
withDefaults(
  defineProps<{
    compact?: boolean
  }>(),
  {
    compact: false,
  },
)

const majors = [
  { symbol: 'SPY', focus: 'Index tape first' },
  { symbol: 'QQQ', focus: 'Nasdaq concentration' },
  { symbol: 'IWM', focus: 'Small-cap tape' },
  { symbol: 'DIA', focus: 'Dow concentration' },
] as const

const queue = [
  { slot: '01', label: 'Open first', question: 'Highest-review name after the window lands' },
  {
    slot: '02',
    label: 'Sweep cluster',
    question: 'Largest sweep premium, if the provider sent one',
  },
  { slot: '03', label: 'Shortest DTE', question: 'Nearest dated activity, not a trade ticket' },
] as const
</script>

<template>
  <figure
    class="flow-mock"
    :class="{ compact }"
    aria-label="Flow workspace layout. Live prints appear after sign-in."
  >
    <div class="bezel">
      <aside class="mock-rail" aria-hidden="true">
        <span class="mock-mark"><TradeCentralMark :size="24" /></span>
        <span class="mock-rail-item">Desk</span>
        <span class="mock-rail-item">Market</span>
        <span class="mock-rail-item">Options</span>
        <span class="mock-rail-item on">Flow</span>
        <span class="mock-rail-item">Research</span>
      </aside>

      <div class="mock-stage">
        <header class="mock-strip">
          <span class="lamp" />
          <strong>FLOW</strong>
          <span>MARKET-WIDE TAPE</span>
          <span>POLL 15S</span>
          <span class="muted">UNSIGNED UNTIL PROVIDER MARKS BUY/SELL</span>
        </header>

        <div class="brief">
          <div class="brief-copy">
            <p>Desk brief</p>
            <h3>Inspect the window. Then open one chain.</h3>
            <span
              >Activity lean is descriptive. Missing stays missing. No illustrative values.</span
            >
          </div>
          <div class="queue">
            <article v-for="item in queue" :key="item.slot">
              <small>{{ item.slot }} · {{ item.label }}</small>
              <strong>SYM —</strong>
              <em>{{ item.question }}</em>
            </article>
          </div>
        </div>

        <div class="majors">
          <article v-for="major in majors" :key="major.symbol">
            <header>
              <strong>{{ major.symbol }}</strong>
              <span>INDEX</span>
            </header>
            <dl>
              <div>
                <dt>Window premium</dt>
                <dd>—</dd>
              </div>
              <div>
                <dt>Activity lean</dt>
                <dd>Unknown</dd>
              </div>
            </dl>
            <p>{{ major.focus }}</p>
            <i class="bar" aria-hidden="true"><b /><b /></i>
          </article>
        </div>
      </div>
    </div>
    <figcaption>Layout only · live prints after sign-in · no illustrative quotes</figcaption>
  </figure>
</template>

<style scoped>
.flow-mock {
  --mock-void: #101112;
  --mock-panel: #161716;
  --mock-rule: #2d2e2c;
  --mock-ink: #e8e6dc;
  --mock-dim: #8a8880;
  --mock-blue: #6a9bcc;
  --mock-orange: #d97757;
  --mock-green: #788c5d;
  display: block;
  width: 100%;
  margin: 0;
}

.bezel {
  display: grid;
  grid-template-columns: 56px minmax(280px, 1fr);
  width: 100%;
  min-height: 430px;
  overflow: hidden;
  border: 1px solid #3a3b37;
  border-top: 2px solid var(--mock-blue);
  background: var(--mock-void);
  box-shadow: 0 24px 60px rgba(8, 8, 7, 0.38);
}

.mock-rail {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 8px;
  color: var(--mock-dim);
  border-right: 1px solid var(--mock-rule);
  background: #0d0e0d;
  font-family: var(--font-display);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.mock-mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin: 0 auto 10px;
  color: var(--mock-ink);
}
.mock-rail-item {
  min-height: 34px;
  display: grid;
  place-items: center;
  text-align: center;
}
.mock-rail-item.on {
  color: var(--mock-ink);
  background: #1c1d1b;
  outline: 1px solid #3f403b;
}

.mock-stage {
  min-width: 0;
  display: grid;
  grid-template-rows: auto auto 1fr;
}
.mock-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  min-height: 36px;
  padding: 0 14px;
  color: #b7b5ad;
  border-bottom: 1px solid var(--mock-rule);
  font-family: var(--font-display);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
}
.mock-strip strong {
  color: var(--mock-ink);
  font-family: var(--font-display);
  font-size: 11px;
  letter-spacing: -0.03em;
}
.lamp {
  width: 7px;
  height: 7px;
  background: var(--mock-green);
}
.muted {
  color: var(--mock-dim);
}

.brief {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.4fr);
  gap: 10px;
  padding: 12px;
  border-bottom: 1px solid var(--mock-rule);
}
.brief-copy {
  padding: 12px 13px;
  border: 1px solid var(--mock-rule);
  border-left: 1px solid var(--mock-orange);
  background: var(--mock-panel);
}
.brief-copy p {
  color: var(--mock-orange);
  font-family: var(--font-display);
  font-size: var(--t-nano);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.brief-copy h3 {
  margin-top: 7px;
  color: var(--mock-ink);
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.15;
}
.brief-copy span {
  display: block;
  margin-top: 8px;
  color: var(--mock-dim);
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
  border: 1px solid var(--mock-rule);
  background: #131413;
}
.queue small {
  color: var(--mock-dim);
  font-family: var(--font-display);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.queue strong {
  color: var(--mock-ink);
  font-family: var(--font-data);
  font-size: 15px;
  font-weight: 500;
}
.queue em {
  color: var(--mock-dim);
  font-family: var(--font-ui);
  font-size: 10px;
  font-style: normal;
  line-height: 1.35;
}

.majors {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  padding: 12px;
}
.majors article {
  min-width: 0;
  padding: 11px;
  border: 1px solid var(--mock-rule);
  background: var(--mock-panel);
}
.majors header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.majors header strong {
  color: var(--mock-ink);
  font-family: var(--font-data);
  font-size: 14px;
}
.majors header span {
  color: var(--mock-blue);
  font-family: var(--font-display);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
}
.majors dl {
  display: grid;
  gap: 7px;
  margin-top: 12px;
}
.majors dt {
  color: var(--mock-dim);
  font-family: var(--font-display);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.majors dd {
  margin-top: 3px;
  color: #cfcbc2;
  font-family: var(--font-data);
  font-size: 13px;
}
.majors p {
  margin-top: 10px;
  color: var(--mock-dim);
  font-family: var(--font-ui);
  font-size: 10px;
}
.bar {
  display: flex;
  height: 3px;
  margin-top: 11px;
  background: #2a2b29;
}
.bar b:first-child {
  flex: 1.1;
  background: var(--mock-blue);
}
.bar b:last-child {
  flex: 0.9;
  background: var(--mock-orange);
}

figcaption {
  margin-top: 10px;
  color: var(--mock-dim);
  font-family: var(--font-display);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.compact .bezel {
  min-height: 360px;
}
.compact .brief-copy h3 {
  font-size: 14px;
}
.compact .majors {
  display: none;
}

@media (max-width: 860px) {
  .bezel {
    grid-template-columns: 1fr;
  }
  .mock-rail {
    display: none;
  }
  .brief,
  .queue,
  .majors {
    grid-template-columns: 1fr;
  }
  .majors article:nth-child(n + 3) {
    display: none;
  }
}
</style>
