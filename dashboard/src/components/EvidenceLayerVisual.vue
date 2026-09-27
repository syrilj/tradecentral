<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

const props = defineProps<{
  kind: 'market' | 'options' | 'governance'
}>()

const meta = computed(
  () =>
    ({
      market: {
        code: 'MKT / STRUCTURE',
        icon: 'radar',
        label: 'Market structure map',
      },
      options: {
        code: 'OPT / POSITIONING',
        icon: 'options',
        label: 'Options positioning profile',
      },
      governance: {
        code: 'RSH / CONTROL',
        icon: 'gate',
        label: 'Research governance path',
      },
    })[props.kind],
)
</script>

<template>
  <figure class="evidence-visual" :class="`evidence-${kind}`" :aria-label="meta.label">
    <figcaption>
      <span class="visual-symbol"><AppIcon :name="meta.icon" :size="16" /></span>
      <span>{{ meta.code }}</span>
      <i aria-hidden="true" />
    </figcaption>

    <svg
      v-if="kind === 'market'"
      viewBox="0 0 360 148"
      role="img"
      aria-label="Price path moving through regime and sector context"
    >
      <g class="grid-lines">
        <path d="M18 25H342M18 61H342M18 97H342M18 133H342" />
        <path d="M53 12V136M126 12V136M199 12V136M272 12V136" />
      </g>
      <path
        class="context-band"
        d="M18 104C66 94 91 113 126 86s65-12 97-30 66-13 119-30v45c-44 20-80 15-116 33s-73 1-108 17-68 6-100 10Z"
      />
      <path
        class="primary-trace"
        d="M18 116C48 110 64 90 88 96s34 21 56 4 31-46 58-39 32 29 58 15 42-43 82-52"
      />
      <g class="trace-points">
        <circle cx="88" cy="96" r="4" />
        <circle cx="202" cy="61" r="4" />
        <circle cx="342" cy="24" r="4" />
      </g>
      <path class="register-mark" d="M18 17h15M18 17v15M327 133h15M342 118v15" />
      <text x="23" y="44">REGIME</text>
      <text x="252" y="124">PEER CONTEXT</text>
    </svg>

    <svg
      v-else-if="kind === 'options'"
      viewBox="0 0 360 148"
      role="img"
      aria-label="Call and put gamma separated around a balance line"
    >
      <g class="grid-lines">
        <path d="M18 27H342M18 74H342M18 121H342" />
        <path d="M62 14V134M114 14V134M166 14V134M218 14V134M270 14V134M322 14V134" />
      </g>
      <path class="balance-line" d="M18 74H342" />
      <g class="position-bars call-bars">
        <path d="M43 74V49M95 74V36M147 74V55M199 74V23M251 74V44M303 74V31" />
      </g>
      <g class="position-bars put-bars">
        <path d="M43 74v14M95 74v32M147 74v45M199 74v19M251 74v38M303 74v22" />
      </g>
      <path class="flip-line" d="M176 16V132" />
      <circle class="spot-dot" cx="225" cy="74" r="5" />
      <!-- Labels sit in the gutters between bars (bars are 11px wide, centred
           on x = 43 + 52n) so none of them overprints a column. -->
      <text x="160" y="22" text-anchor="end">FLIP</text>
      <text x="225" y="139" text-anchor="middle">SPOT</text>
      <text x="18" y="20">CALL</text>
      <text x="18" y="139">PUT</text>
    </svg>

    <svg
      v-else
      viewBox="0 0 360 148"
      role="img"
      aria-label="Evidence passing through research gates into a fail-closed readiness state"
    >
      <g class="governance-path">
        <path d="M28 74H332" />
        <path d="M82 74 104 52l22 22-22 22Z" />
        <path d="M174 74 196 52l22 22-22 22Z" />
        <path d="M266 74 288 52l22 22-22 22Z" />
      </g>
      <g class="governance-node">
        <circle cx="28" cy="74" r="8" />
        <circle cx="104" cy="74" r="7" />
        <circle cx="196" cy="74" r="7" />
        <circle cx="288" cy="74" r="7" />
        <circle cx="332" cy="74" r="8" />
      </g>
      <path class="register-mark" d="M18 17h15M18 17v15M327 133h15M342 118v15" />
      <text x="18" y="111">SOURCE</text>
      <text x="79" y="36">METHOD</text>
      <text x="177" y="119">GATE</text>
      <text x="261" y="36">SHADOW</text>
      <text x="301" y="111">READINESS</text>
    </svg>

    <footer>
      <span>Evidence layer</span>
      <span>Source visible</span>
    </footer>
  </figure>
</template>

<style scoped>
.evidence-visual {
  --plate-accent: var(--call);
  position: relative;
  min-height: 220px;
  margin: 0;
  padding: 15px 15px 11px;
  overflow: hidden;
  color: var(--ink);
  border: 1px solid var(--rule-hi);
  border-top: 2px solid var(--plate-accent);
  background:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px), var(--panel);
  background-size: 27px 27px;
}
.evidence-options {
  --plate-accent: var(--warn);
}
.evidence-governance {
  --plate-accent: var(--phosphor);
}
.evidence-visual::before,
.evidence-visual::after {
  content: '';
  position: absolute;
  width: 10px;
  height: 10px;
  pointer-events: none;
}
.evidence-visual::before {
  top: -1px;
  left: -1px;
  border-top: 1px solid var(--ink);
  border-left: 1px solid var(--ink);
}
.evidence-visual::after {
  right: -1px;
  bottom: -1px;
  border-right: 1px solid var(--ink);
  border-bottom: 1px solid var(--ink);
}
figcaption,
footer {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 650;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
figcaption {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--rule);
}
figcaption i {
  flex: 1;
  height: 1px;
  background: var(--rule);
}
.visual-symbol {
  width: 27px;
  height: 27px;
  display: grid;
  place-items: center;
  color: var(--plate-accent);
  border: 1px solid var(--rule-hi);
  background: var(--void-lift);
}
/* Direct child only. An unscoped `svg` selector also matched the AppIcon
   inside .visual-symbol, stretching a 16px glyph to 100% x 142px so it broke
   out of its caption box and floated over the plot. */
.evidence-visual > svg {
  display: block;
  width: 100%;
  height: 142px;
  margin-top: 7px;
  overflow: visible;
}
.grid-lines {
  fill: none;
  stroke: var(--rule);
  stroke-width: 1;
}
.context-band {
  fill: var(--call-wash);
  stroke: none;
}
.primary-trace {
  fill: none;
  stroke: var(--call);
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}
.trace-points circle {
  fill: var(--void);
  stroke: var(--call);
  stroke-width: 2;
}
.register-mark {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1;
}
text {
  fill: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
}
.balance-line {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1;
  stroke-dasharray: 4 4;
}
.position-bars {
  fill: none;
  stroke-width: 11;
}
.call-bars {
  stroke: var(--call);
}
.put-bars {
  stroke: var(--put);
}
.flip-line {
  stroke: var(--put);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}
.spot-dot {
  fill: var(--void);
  stroke: var(--phosphor);
  stroke-width: 2;
}
.governance-path {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1;
}
.governance-node {
  fill: var(--void);
  stroke: var(--phosphor);
  stroke-width: 2;
}
.governance-node circle:nth-child(3) {
  stroke: var(--put);
}
footer {
  justify-content: space-between;
  padding-top: 9px;
  border-top: 1px solid var(--rule);
}
footer span:last-child {
  color: var(--plate-accent);
}

@media (max-width: 800px) {
  .evidence-visual {
    min-height: 205px;
  }
  .evidence-visual > svg {
    height: 126px;
  }
}
</style>
