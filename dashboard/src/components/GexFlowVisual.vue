<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'

/**
 * A structural explainer for the public page. The bar proportions are visual
 * anatomy only: live GEX and flow values appear exclusively after sign-in.
 */
const strikeColumns = [
  { id: 'a', strike: '510', call: '12%', put: '32%' },
  { id: 'b', strike: '515', call: '20%', put: '48%' },
  { id: 'c', strike: '520', call: '37%', put: '23%' },
  { id: 'd', strike: '525', call: '64%', put: '16%' },
  { id: 'e', strike: '530', call: '43%', put: '21%' },
  { id: 'f', strike: '535', call: '74%', put: '10%' },
  { id: 'g', strike: '540', call: '34%', put: '29%' },
] as const
</script>

<template>
  <figure class="gex-flow-visual" aria-labelledby="gex-flow-title">
    <div class="visual-register" aria-hidden="true">
      <span class="reg-code">OPTIONS INTELLIGENCE / 01</span>
      <span class="reg-badge">GEX + FLOW ANATOMY</span>
      <span class="reg-mode">STRUCTURAL SPECIFICATION</span>
    </div>

    <figcaption id="gex-flow-title" class="visual-title">
      <span>GEX = dealer positioning by strike</span>
      <strong>See the structure<br />behind a move.</strong>
    </figcaption>

    <div
      class="gex-stage"
      aria-label="Illustrative gamma exposure profile and options flow context"
    >
      <div class="stage-label gex-label">
        <AppIcon name="options" :size="15" /> Dealer gamma by strike
      </div>
      <div class="axis-copy positive">Positive GEX</div>
      <div class="axis-copy negative">Negative GEX</div>
      <div class="zero-axis" aria-hidden="true"><span>Balance line</span></div>

      <div class="strike-columns" aria-hidden="true">
        <div v-for="bar in strikeColumns" :key="bar.id" class="strike-column">
          <i class="call-bar" :style="{ height: bar.call }" />
          <i class="put-bar" :style="{ height: bar.put }" />
          <span class="strike-label">${{ bar.strike }}</span>
        </div>
      </div>

      <div class="reference-line gamma-flip">
        <div class="ref-pill gamma-pill">
          <i class="ref-dot" />
          <span>Gamma flip</span>
        </div>
      </div>
      <div class="reference-line spot-reference">
        <div class="ref-pill spot-pill">
          <i class="ref-dot" />
          <span>Spot reference</span>
        </div>
      </div>

      <svg class="flow-trace" viewBox="0 0 660 295" preserveAspectRatio="none" aria-hidden="true">
        <path
          class="trace-base"
          d="M5 224 C88 168 126 205 189 143 S311 192 383 116 492 178 655 50"
        />
        <path
          class="trace-call"
          d="M5 224 C88 168 126 205 189 143 S311 192 383 116 492 178 655 50"
        />
        <circle cx="189" cy="143" r="4" />
        <circle cx="383" cy="116" r="4" />
        <circle cx="560" cy="109" r="4" />
      </svg>

      <div class="flow-tag flow-tag-call">
        <div class="flow-tag-badge"><i class="call-indicator" />Call flow</div>
        <div class="flow-tag-detail">
          <strong>$535 STRIKE SWEEP</strong>
          <span>upside interest</span>
        </div>
      </div>

      <div class="flow-tag flow-tag-put">
        <div class="flow-tag-badge"><i class="put-indicator" />Put flow</div>
        <div class="flow-tag-detail">
          <strong>$515 STRIKE BLOCK</strong>
          <span>downside hedging</span>
        </div>
      </div>

      <aside class="interpret-card">
        <header class="card-register">
          <span class="seq-label">Read it in sequence</span>
          <span class="seq-count">01→03</span>
        </header>
        <strong>Map concentration.<br />Locate the flip.<br />Inspect the tape.</strong>
        <div class="seq-pills" aria-hidden="true">
          <span class="seq-pill"><b class="num-box">1</b> Map GEX</span>
          <span class="seq-pill"><b class="num-box">2</b> Flip line</span>
          <span class="seq-pill"><b class="num-box">3</b> Read tape</span>
        </div>
        <p>Calls, puts, and unsigned activity stay separate until the provider gives a side.</p>
      </aside>
    </div>

    <footer class="visual-footer">
      <div class="legend-pills">
        <span><i class="legend-call" />Call GEX</span>
        <span><i class="legend-put" />Put GEX</span>
        <span><i class="legend-net" />Net positioning</span>
      </div>
      <strong>Illustrative anatomy · live chain after sign-in</strong>
    </footer>
  </figure>
</template>

<style scoped>
.gex-flow-visual {
  --paper: var(--ink);
  --blue: var(--call);
  --orange: var(--put);
  position: relative;
  width: 100%;
  min-height: 525px;
  margin: 0;
  padding: 22px 24px 20px;
  overflow: hidden;
  color: var(--paper);
  border: 1px solid var(--rule-hi);
  border-top: 2px solid var(--blue);
  background:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px), var(--panel);
  background-size: 31px 31px;
  box-shadow: 0 1px 0 rgba(24, 24, 27, 0.05);
}
.gex-flow-visual::before,
.gex-flow-visual::after {
  content: '';
  position: absolute;
  z-index: 4;
  width: 16px;
  height: 16px;
  pointer-events: none;
}
.gex-flow-visual::before {
  top: -1px;
  left: -1px;
  border-top: 2px solid var(--paper);
  border-left: 2px solid var(--paper);
}
.gex-flow-visual::after {
  right: -1px;
  bottom: -1px;
  border-right: 2px solid var(--paper);
  border-bottom: 2px solid var(--paper);
}

.visual-register {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding-bottom: 13px;
  color: var(--ink-dim);
  border-bottom: 1px solid var(--rule);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}
.reg-badge {
  padding: 2px 7px;
  color: var(--ink);
  background: var(--void-lift);
  border: 1px solid var(--rule-hi);
  letter-spacing: 0.08em;
}

.visual-title {
  display: grid;
  gap: 7px;
  margin-top: 17px;
}
.visual-title span {
  color: var(--orange);
  font-family: var(--font-data);
  font-size: var(--t-nano);
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

.gex-stage {
  position: relative;
  height: 326px;
  margin-top: 15px;
  border: 1px solid var(--rule);
  background: var(--panel-hi);
  box-shadow: inset 0 0 0 1px rgba(24, 24, 27, 0.05);
}

.stage-label {
  position: absolute;
  z-index: 3;
  top: 14px;
  left: 16px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 3px 8px;
  color: var(--ink);
  border: 1px solid var(--rule-hi);
  background: var(--panel-hi);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.stage-label .app-icon {
  color: var(--blue);
}

.axis-copy {
  position: absolute;
  z-index: 2;
  left: 17px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 6px;
  color: var(--ink-soft);
  background: var(--panel);
  border: 1px solid var(--rule);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.axis-copy::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
}
.positive {
  top: 58px;
}
.positive::before {
  background: var(--blue);
}
.negative {
  top: 198px;
}
.negative::before {
  background: var(--orange);
}

.zero-axis {
  position: absolute;
  z-index: 1;
  top: 150px;
  right: 0;
  left: 0;
  height: 1px;
  border-top: 1px dashed var(--rule-hi);
}
.zero-axis span {
  position: absolute;
  right: 15px;
  top: -15px;
  padding: 1px 5px;
  color: var(--ink-dim);
  background: var(--panel-hi);
  border: 1px solid var(--rule);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.07em;
  text-transform: uppercase;
}

.strike-columns {
  position: absolute;
  z-index: 1;
  top: 50px;
  bottom: 22px;
  left: 122px;
  width: 45%;
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  align-items: stretch;
  gap: 6px;
}
.strike-column {
  position: relative;
  height: 100%;
  border-right: 1px solid var(--rule-faint);
}
.strike-column i {
  position: absolute;
  left: 20%;
  width: 60%;
  border-radius: 1px;
}
.call-bar {
  bottom: 50%;
  background: var(--blue);
}
.put-bar {
  top: 50%;
  background: var(--orange);
}
.strike-label {
  position: absolute;
  bottom: 2px;
  left: 50%;
  transform: translateX(-50%);
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 600;
  letter-spacing: 0.04em;
}

.reference-line {
  position: absolute;
  z-index: 2;
  top: 45px;
  bottom: 33px;
  width: 1px;
  border-left: 1px dashed;
}
.ref-pill {
  position: absolute;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 7px;
  border: 1px solid;
  background: var(--panel-hi);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  white-space: nowrap;
}
.ref-dot {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
}
.gamma-flip {
  left: 47%;
  border-color: var(--orange);
}
.gamma-pill {
  bottom: 6px;
  left: 6px;
  color: var(--put-hi);
  border-color: var(--orange);
}
.gamma-pill .ref-dot {
  background: var(--orange);
}

.spot-reference {
  left: 62%;
  border-color: var(--ink-soft);
}
.spot-pill {
  top: 36px;
  right: 6px;
  transform: translateX(-100%);
  color: var(--ink-soft);
  border-color: var(--rule-hi);
}
.spot-pill .ref-dot {
  background: var(--ink-soft);
}

.flow-trace {
  position: absolute;
  z-index: 2;
  right: 18px;
  bottom: 16px;
  width: 58%;
  height: 150px;
  overflow: visible;
}
.trace-base {
  fill: none;
  stroke: var(--rule-hi);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
  stroke-dasharray: 4 5;
}
.trace-call {
  fill: none;
  stroke: var(--ink-soft);
  stroke-width: 1.8;
  vector-effect: non-scaling-stroke;
  stroke-dasharray: 22 160;
}
.flow-trace circle {
  fill: var(--void);
  stroke: var(--ink-soft);
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
}

/* ── Flow Callout Boxes ─────────────────────────────────────────────────── */
.flow-tag {
  position: absolute;
  z-index: 3;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  color: var(--ink);
  background: var(--panel-hi);
  border: 1px solid var(--rule-hi);
  box-shadow: 0 1px 0 rgba(24, 24, 27, 0.06);
  font-family: var(--font-data);
}
.flow-tag-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--t-nano);
  font-weight: 750;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.call-indicator,
.put-indicator {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 1px;
}
.call-indicator {
  background: var(--blue);
}
.put-indicator {
  background: var(--orange);
}

.flow-tag-detail {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.flow-tag-detail strong {
  color: var(--ink);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.flow-tag-detail span {
  color: var(--ink-dim);
  font-size: var(--t-nano);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.flow-tag-call {
  right: 28px;
  /* Clears the interpret card below it — at 92px the two boxes overlapped by
     ~10px and the tag's last line was hidden behind the card. */
  top: 56px;
  border-left: 3px solid var(--blue);
}
.flow-tag-put {
  left: 18px;
  bottom: 24px;
  border-left: 3px solid var(--orange);
}

/* ── Interpret Sequence Box ─────────────────────────────────────────────── */
.interpret-card {
  position: absolute;
  z-index: 4;
  right: 16px;
  bottom: 12px;
  width: min(220px, 42%);
  padding: 12px 14px;
  color: var(--ink);
  border: 1px solid var(--rule-hi);
  border-left: 3px solid var(--ink-soft);
  background: var(--panel-hi);
  box-shadow: 0 1px 0 rgba(24, 24, 27, 0.06);
}
.card-register {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 5px;
  border-bottom: 1px solid var(--rule);
}
.seq-label {
  color: var(--put-hi);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.seq-count {
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.06em;
}
.interpret-card strong {
  display: block;
  margin-top: 6px;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.1;
}
.seq-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 7px;
}
.seq-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 5px;
  background: var(--void-lift);
  border: 1px solid var(--rule);
  color: var(--ink-soft);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.num-box {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 10px;
  height: 10px;
  color: var(--ink);
  background: var(--rule-hi);
  font-size: var(--t-nano);
  font-weight: 800;
}
.interpret-card p {
  margin-top: 7px;
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: var(--t-nano);
  line-height: 1.35;
}

/* ── Visual Footer ──────────────────────────────────────────────────────── */
.visual-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 14px;
  margin-top: 14px;
  color: var(--ink-soft);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.legend-pills {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
.legend-pills span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.visual-footer i {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 1px;
}
.legend-call {
  background: var(--blue);
}
.legend-put {
  background: var(--orange);
}
.legend-net {
  border: 1px solid var(--rule-hi);
}
.visual-footer strong {
  color: var(--ink-dim);
  font-size: var(--t-nano);
  font-weight: 500;
}

@media (max-width: 620px) {
  .gex-flow-visual {
    min-height: 566px;
    padding: 18px 17px;
  }
  .reg-mode {
    display: none;
  }
  .gex-stage {
    height: 346px;
  }
  .strike-columns {
    left: 78px;
    width: 50%;
  }
  .axis-copy {
    left: 12px;
    font-size: var(--t-nano);
  }
  .positive {
    top: 57px;
  }
  .negative {
    top: 183px;
  }
  .flow-trace {
    width: 70%;
    right: 8px;
    bottom: 27px;
  }
  .flow-tag-call {
    display: none;
  }
  .flow-tag-put {
    left: 12px;
    bottom: 35px;
  }
  .interpret-card {
    right: 10px;
    bottom: 9px;
    width: 53%;
    padding: 10px;
  }
  .interpret-card strong {
    font-size: 12px;
  }
  .interpret-card p {
    font-size: var(--t-nano);
  }
  .visual-footer strong {
    width: 100%;
    margin-left: 0;
  }
}
</style>
