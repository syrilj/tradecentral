<script setup lang="ts">
/**
 * Bento-card diagram of the workspace path.
 *
 * Five workspaces on one rail, each labelled with the single question it
 * answers, and each handing its context to the next. The numbering is load
 * bearing here: the order is the research sequence, not decoration.
 *
 * The full-size version of this idea (ResearchLoopVisual) sits in the
 * Workspaces section; this is the compact statement of it.
 */
const STOPS = [
  { n: '01', name: 'Desk', asks: 'What needs attention?' },
  { n: '02', name: 'Market', asks: 'What is the context?' },
  { n: '03', name: 'Options', asks: 'How is it positioned?' },
  { n: '04', name: 'Flow', asks: 'Where is the pressure?' },
  { n: '05', name: 'Research', asks: 'What survives scrutiny?' },
] as const
</script>

<template>
  <figure
    class="path-plate"
    aria-label="Five workspaces on one research path — Desk, Market, Options, Flow, Research — each answering a single question and handing its context to the next."
  >
    <figcaption>
      <span>RESEARCH PATH</span>
      <i aria-hidden="true" />
      <span class="dim">CONTEXT CARRIES FORWARD</span>
    </figcaption>

    <ol class="stops">
      <li v-for="(stop, i) in STOPS" :key="stop.n" class="stop">
        <span class="stop-rail" aria-hidden="true">
          <i class="dot" />
          <i v-if="i < STOPS.length - 1" class="link" />
        </span>
        <span class="idx">{{ stop.n }}</span>
        <strong class="name">{{ stop.name }}</strong>
        <span class="asks">{{ stop.asks }}</span>
      </li>
    </ol>
  </figure>
</template>

<style scoped>
.path-plate {
  margin: 0;
  padding: 9px 10px 8px;
  border: var(--hair) solid var(--rule);
  border-top: 2px solid var(--tc-blue);
  background: var(--panel);
}
figcaption {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 8px;
  border-bottom: var(--hair) solid var(--rule);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.09em;
  color: var(--ink-faint);
}
figcaption i {
  flex: 1;
  height: 1px;
  background: var(--rule);
}
.dim {
  color: var(--ink-faint);
}

.stops {
  display: grid;
  gap: 0;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}
.stop {
  display: grid;
  grid-template-columns: 14px 20px 64px minmax(0, 1fr);
  align-items: center;
  gap: 4px 9px;
  padding-block: 5px;
}

/* The rail: a dot per stop, joined by a hairline that stops at the last one.
   Named .stop-rail, not .rail — the landing page hides the desk shell's own
   `.rail` sidebar with a global `display: none !important`, which a bare
   `.rail` here inherits and which scoped styles cannot outrank.
   align-self: stretch is load bearing too: the parent centres its items, so a
   height:100% rail would collapse and take the connecting line with it. */
.stop-rail {
  position: relative;
  display: block;
  align-self: stretch;
  width: 14px;
  min-height: 22px;
}
.dot {
  position: absolute;
  top: 50%;
  left: 4px;
  width: 6px;
  height: 6px;
  margin-top: -3px;
  background: var(--phosphor);
}
.link {
  position: absolute;
  top: calc(50% + 3px);
  left: 6.5px;
  width: 1px;
  height: calc(100% + 4px);
  background: var(--rule-hi);
}

.idx {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
.name {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 13px;
  letter-spacing: -0.01em;
  color: var(--ink);
}
.asks {
  min-width: 0;
  font-family: var(--font-data);
  font-size: var(--t-nano);
  line-height: 1.3;
  letter-spacing: 0.02em;
  color: var(--ink-faint);
}

@media (max-width: 560px) {
  .stop {
    grid-template-columns: 14px 20px minmax(0, 1fr);
    align-items: start;
  }
  .name {
    align-self: center;
  }
  .asks {
    grid-column: 3;
    grid-row: 2;
  }
}
</style>
