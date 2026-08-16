<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'

/**
 * A structural explainer for the public page. The bar proportions are visual
 * anatomy only: live GEX and flow values appear exclusively after sign-in.
 */
const strikeColumns = [
  { id: 'a', call: '12%', put: '32%' },
  { id: 'b', call: '20%', put: '48%' },
  { id: 'c', call: '37%', put: '23%' },
  { id: 'd', call: '64%', put: '16%' },
  { id: 'e', call: '43%', put: '21%' },
  { id: 'f', call: '74%', put: '10%' },
  { id: 'g', call: '34%', put: '29%' },
] as const
</script>

<template>
  <figure class="gex-flow-visual" aria-labelledby="gex-flow-title">
    <div class="visual-register" aria-hidden="true">
      <span>OPTIONS INTELLIGENCE / 01</span>
      <span>GEX + FLOW</span>
    </div>

    <figcaption id="gex-flow-title" class="visual-title">
      <span>GEX = dealer positioning by strike</span>
      <strong>See the structure<br>behind a move.</strong>
    </figcaption>

    <div class="gex-stage" aria-label="Illustrative gamma exposure profile and options flow context">
      <div class="stage-label gex-label"><AppIcon name="options" :size="15" /> Dealer gamma by strike</div>
      <div class="axis-copy positive">Positive GEX</div>
      <div class="axis-copy negative">Negative GEX</div>
      <div class="zero-axis" aria-hidden="true"><span>Balance line</span></div>

      <div class="strike-columns" aria-hidden="true">
        <div v-for="bar in strikeColumns" :key="bar.id" class="strike-column">
          <i class="call-bar" :style="{ height: bar.call }" />
          <i class="put-bar" :style="{ height: bar.put }" />
        </div>
      </div>

      <div class="reference-line gamma-flip"><span>Gamma flip</span></div>
      <div class="reference-line spot-reference"><span>Spot reference</span></div>

      <svg class="flow-trace" viewBox="0 0 660 295" preserveAspectRatio="none" aria-hidden="true">
        <path class="trace-base" d="M5 224 C88 168 126 205 189 143 S311 192 383 116 492 178 655 50" />
        <path class="trace-call" d="M5 224 C88 168 126 205 189 143 S311 192 383 116 492 178 655 50" />
        <circle cx="189" cy="143" r="4" />
        <circle cx="383" cy="116" r="4" />
        <circle cx="560" cy="109" r="4" />
      </svg>

      <div class="flow-tag flow-tag-call"><i />Call flow<br><span>upside interest</span></div>
      <div class="flow-tag flow-tag-put"><i />Put flow<br><span>downside hedging</span></div>

      <aside class="interpret-card">
        <span>Read it in sequence</span>
        <strong>Map concentration.<br>Locate the flip.<br>Inspect the tape.</strong>
        <p>Calls, puts, and unsigned activity stay separate until the provider gives a side.</p>
      </aside>
    </div>

    <footer class="visual-footer">
      <span><i class="legend-call" />Call GEX</span>
      <span><i class="legend-put" />Put GEX</span>
      <span><i class="legend-net" />Net positioning</span>
      <strong>Illustrative anatomy · live chain after sign-in</strong>
    </footer>
  </figure>
</template>

<style scoped>
.gex-flow-visual {
  --paper: var(--ink);
  --ink: var(--ink);
  --rule: var(--rule);
  --blue: var(--call);
  --orange: var(--put);
  --green: var(--phosphor);
  position: relative;
  width: 100%;
  min-height: 525px;
  margin: 0;
  padding: 21px 24px 19px;
  overflow: hidden;
  color: var(--paper);
  border: 1px solid var(--rule-hi);
  border-top: 2px solid var(--blue);
  background:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px),
    var(--panel);
  background-size: 31px 31px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
}
.gex-flow-visual::before,
.gex-flow-visual::after {
  content: '';
  position: absolute;
  z-index: 4;
  width: 15px;
  height: 15px;
  pointer-events: none;
}
.gex-flow-visual::before { top: -1px; left: -1px; border-top: 2px solid var(--paper); border-left: 2px solid var(--paper); }
.gex-flow-visual::after { right: -1px; bottom: -1px; border-right: 2px solid var(--paper); border-bottom: 2px solid var(--paper); }
.visual-register {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  padding-bottom: 13px;
  color: var(--ink-dim);
  border-bottom: 1px solid var(--rule);
  font-family: var(--font-data);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}
.visual-title { display: grid; gap: 7px; margin-top: 17px; }
.visual-title span {
  color: var(--orange);
  font-family: var(--font-data);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.visual-title strong {
  color: var(--ink);
  font-family: var(--font-display);
  font-size: clamp(22px, 2.45vw, 31px);
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 0.98;
}
.gex-stage { position: relative; height: 313px; margin-top: 13px; border: 1px solid var(--rule); background: rgba(8, 9, 12, 0.73); }
.stage-label {
  position: absolute;
  z-index: 3;
  top: 15px;
  left: 16px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--ink);
  font-family: var(--font-data);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.stage-label .app-icon { color: var(--blue); }
.axis-copy {
  position: absolute;
  z-index: 2;
  left: 17px;
  color: var(--ink-soft);
  font-family: var(--font-data);
  font-size: 8px;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.axis-copy::before { content: ''; display: inline-block; width: 7px; height: 7px; margin-right: 6px; }
.positive { top: 62px; }.positive::before { background: var(--blue); }
.negative { top: 187px; }.negative::before { background: var(--orange); }
.zero-axis { position: absolute; z-index: 1; top: 150px; right: 0; left: 0; height: 1px; border-top: 1px dashed var(--rule-hi); }
.zero-axis span { position: absolute; right: 15px; top: -15px; color: var(--ink-dim); font-family: var(--font-data); font-size: 8px; letter-spacing: 0.07em; text-transform: uppercase; }
.strike-columns {
  position: absolute;
  z-index: 1;
  top: 54px;
  bottom: 40px;
  left: 117px;
  width: 46%;
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  align-items: stretch;
  gap: 5px;
}
.strike-column { position: relative; height: 100%; border-right: 1px solid var(--rule-faint); }
.strike-column i { position: absolute; left: 22%; width: 56%; }
.call-bar { bottom: 50%; background: var(--blue); }
.put-bar { top: 50%; background: var(--orange); }
.reference-line { position: absolute; z-index: 2; top: 45px; bottom: 33px; width: 1px; border-left: 1px dashed; }
.reference-line span { position: absolute; width: 74px; color: var(--ink-soft); font-family: var(--font-data); font-size: 8px; font-weight: 700; letter-spacing: 0.07em; line-height: 1.2; text-transform: uppercase; }
.gamma-flip { left: 47%; border-color: var(--orange); }.gamma-flip span { bottom: 3px; left: 5px; color: var(--put-hi); }
.spot-reference { left: 62%; border-color: var(--green); }.spot-reference span { top: 36px; right: 5px; transform: translateX(-100%); color: var(--phosphor); text-align: right; }
.flow-trace { position: absolute; z-index: 2; right: 18px; bottom: 16px; width: 58%; height: 150px; overflow: visible; }
.trace-base { fill: none; stroke: var(--rule-hi); stroke-width: 1; vector-effect: non-scaling-stroke; stroke-dasharray: 4 5; }
.trace-call { fill: none; stroke: var(--green); stroke-width: 1.8; vector-effect: non-scaling-stroke; stroke-dasharray: 22 160; animation: gex-trace 6.8s linear infinite; }
.flow-trace circle { fill: var(--void); stroke: var(--green); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.flow-tag {
  position: absolute;
  z-index: 3;
  display: grid;
  grid-template-columns: 7px 1fr;
  column-gap: 7px;
  color: var(--ink);
  font-family: var(--font-data);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.07em;
  line-height: 1.25;
  text-transform: uppercase;
}
.flow-tag i { grid-row: span 2; width: 7px; height: 7px; margin-top: 2px; background: var(--green); }
.flow-tag span { color: var(--ink-dim); font-size: 8px; font-weight: 500; }
.flow-tag-call { right: 28px; top: 98px; }.flow-tag-put { left: 18px; bottom: 28px; }.flow-tag-put i { background: var(--orange); }
.interpret-card {
  position: absolute;
  z-index: 4;
  right: 16px;
  bottom: 13px;
  width: min(205px, 39%);
  padding: 13px 14px;
  color: var(--ink);
  border: 1px solid var(--rule-hi);
  border-left: 3px solid var(--green);
  background: rgba(18, 20, 26, 0.94);
}
.interpret-card > span { color: var(--put-hi); font-family: var(--font-data); font-size: 8px; font-weight: 700; letter-spacing: 0.09em; text-transform: uppercase; }
.interpret-card strong { display: block; margin-top: 7px; color: var(--ink); font-family: var(--font-display); font-size: 15px; font-weight: 600; letter-spacing: -0.01em; line-height: 1.05; }
.interpret-card p { margin-top: 8px; color: var(--ink-dim); font-family: var(--font-ui); font-size: 9px; line-height: 1.38; }
.visual-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
  margin-top: 14px;
  color: var(--ink-soft);
  font-family: var(--font-data);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.visual-footer span { display: inline-flex; align-items: center; gap: 5px; }.visual-footer i { display: inline-block; width: 7px; height: 7px; }.legend-call { background: var(--blue); }.legend-put { background: var(--orange); }.legend-net { border: 1px solid var(--green); }
.visual-footer strong { margin-left: auto; color: var(--ink-dim); font-size: 8px; font-weight: 500; }

@keyframes gex-trace { to { stroke-dashoffset: -182; } }

@media (max-width: 620px) {
  .gex-flow-visual { min-height: 566px; padding: 18px 17px; }
  .visual-register span:last-child { display: none; }
  .gex-stage { height: 346px; }
  .strike-columns { left: 78px; width: 50%; }
  .axis-copy { left: 12px; font-size: 6px; }.positive { top: 57px; }.negative { top: 183px; }
  .flow-trace { width: 70%; right: 8px; bottom: 27px; }
  .flow-tag-call { display: none; }.flow-tag-put { left: 12px; bottom: 35px; }
  .interpret-card { right: 10px; bottom: 9px; width: 53%; padding: 11px; }
  .interpret-card strong { font-size: 13px; }.interpret-card p { font-size: 8px; }
  .visual-footer strong { width: 100%; margin-left: 0; }
}

@media (prefers-reduced-motion: reduce) { .trace-call { animation: none; } }
</style>
