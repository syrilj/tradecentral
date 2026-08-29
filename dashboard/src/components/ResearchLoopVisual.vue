<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'

const nodes = [
  { icon: 'desk', name: 'Desk', path: '/desk', note: 'Posture', className: 'node-desk' },
  { icon: 'market', name: 'Market', path: '/market', note: 'Context', className: 'node-market' },
  {
    icon: 'options',
    name: 'Options',
    path: '/options',
    note: 'Positioning',
    className: 'node-options',
  },
  { icon: 'flow', name: 'Flow', path: '/flow', note: 'Concentration', className: 'node-flow' },
  {
    icon: 'research',
    name: 'Research',
    path: '/research',
    note: 'Evidence',
    className: 'node-research',
  },
] as const
</script>

<template>
  <figure class="research-map" aria-labelledby="research-map-title">
    <figcaption>
      <span id="research-map-title">TradeCentral / research path</span>
      <span>05 linked workspaces</span>
    </figcaption>
    <div class="map-stage">
      <svg viewBox="0 0 760 390" preserveAspectRatio="none" aria-hidden="true">
        <path
          class="path-shadow"
          d="M65 246C143 245 141 112 237 112s92 158 195 158 83-173 183-173 80 138 104 163"
        />
        <path
          class="path-main"
          d="M65 246C143 245 141 112 237 112s92 158 195 158 83-173 183-173 80 138 104 163"
        />
        <path
          class="path-return"
          d="M719 260C644 338 560 336 486 312S329 332 243 301 115 294 65 246"
        />
        <circle cx="65" cy="246" r="5" />
        <circle cx="237" cy="112" r="5" />
        <circle cx="432" cy="270" r="5" />
        <circle cx="615" cy="97" r="5" />
        <circle cx="719" cy="260" r="5" />
      </svg>

      <RouterLink
        v-for="(node, index) in nodes"
        :key="node.path"
        class="map-node"
        :class="node.className"
        :to="{ name: 'auth', query: { redirect: node.path } }"
      >
        <small>0{{ index + 1 }}</small>
        <span><AppIcon :name="node.icon" :size="19" /></span>
        <strong>{{ node.name }}</strong>
        <em>{{ node.note }}</em>
        <AppIcon class="node-arrow" name="arrow-right" :size="14" />
      </RouterLink>

      <div class="map-annotation annotation-input"><span>INPUT</span>What needs attention?</div>
      <div class="map-annotation annotation-output"><span>OUTPUT</span>What survives scrutiny?</div>
      <div class="map-register" aria-hidden="true">
        SIGNAL → CONTEXT → POSITIONING → FLOW → EVIDENCE
      </div>
    </div>
    <footer>
      <span>Specialist tools remain adjacent—not mixed into the primary path.</span
      ><span>Sectors · Pulse · Gates · Graph · Cloud</span>
    </footer>
  </figure>
</template>

<style scoped>
.research-map {
  position: relative;
  margin: 0;
  padding: 17px 19px 14px;
  overflow: hidden;
  color: var(--ink);
  border: 1px solid var(--rule-hi);
  border-top: 2px solid var(--phosphor);
  background: var(--panel);
  box-shadow: 0 1px 0 rgba(24, 24, 27, 0.05);
}
.research-map::before,
.research-map::after {
  content: '';
  position: absolute;
  width: 13px;
  height: 13px;
  z-index: 4;
  pointer-events: none;
}
.research-map::before {
  top: -1px;
  left: -1px;
  border-top: 1px solid var(--ink);
  border-left: 1px solid var(--ink);
}
.research-map::after {
  right: -1px;
  bottom: -1px;
  border-right: 1px solid var(--ink);
  border-bottom: 1px solid var(--ink);
}
figcaption,
footer {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
figcaption {
  padding-bottom: 13px;
  border-bottom: 1px solid var(--rule);
}
.map-stage {
  position: relative;
  height: 390px;
  overflow: hidden;
  background:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px);
  background-size: 30px 30px;
}
.map-stage > svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
  fill: var(--void);
  stroke: var(--phosphor);
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
}
.path-shadow {
  fill: none;
  stroke: var(--rule);
  stroke-width: 11;
}
.path-main {
  fill: none;
  stroke: var(--call);
  stroke-width: 2;
}
.path-return {
  fill: none;
  stroke: var(--put);
  stroke-width: 1;
  stroke-dasharray: 5 6;
}
.map-node {
  position: absolute;
  z-index: 2;
  width: 126px;
  min-height: 98px;
  display: grid;
  grid-template-columns: 28px 1fr auto;
  grid-template-rows: auto auto auto;
  align-items: center;
  gap: 2px 9px;
  padding: 11px;
  color: var(--ink);
  border: 1px solid var(--rule-hi);
  background: var(--panel-hi);
  transition:
    transform var(--dur-fast),
    border-color var(--dur-fast),
    box-shadow var(--dur-fast);
}
.map-node:hover {
  transform: translateY(-2px);
  border-color: var(--phosphor);
  text-decoration: none;
}
.map-node small {
  grid-column: 1 / -1;
  color: var(--ink-ghost);
  font-family: var(--font-data);
  font-size: 8px;
}
.map-node > span {
  grid-row: 2 / 4;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  color: var(--call);
  border: 1px solid var(--rule-hi);
}
.map-node strong {
  font-family: var(--font-display);
  font-size: 12px;
  font-style: normal;
  font-weight: 600;
}
.map-node em {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: 7px;
  font-style: normal;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.node-arrow {
  grid-row: 2 / 4;
  color: var(--phosphor);
}
.node-desk {
  left: 1%;
  top: 47%;
}
.node-market {
  left: 18%;
  top: 6%;
}
.node-options {
  left: 44%;
  top: 53%;
}
.node-flow {
  right: 10%;
  top: 3%;
}
.node-research {
  right: 0;
  top: 50%;
}
.map-annotation {
  position: absolute;
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: 10px;
}
.map-annotation span {
  display: block;
  margin-bottom: 4px;
  color: var(--put);
  font-family: var(--font-data);
  font-size: 7px;
  font-weight: 700;
  letter-spacing: 0.09em;
}
.annotation-input {
  left: 2%;
  bottom: 28px;
}
.annotation-output {
  right: 1%;
  bottom: 28px;
  text-align: right;
}
.map-register {
  position: absolute;
  right: 23%;
  bottom: 24px;
  left: 23%;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: 7px;
  letter-spacing: 0.08em;
  text-align: center;
}
footer {
  padding-top: 13px;
  border-top: 1px solid var(--rule);
}
footer span:last-child {
  color: var(--phosphor);
  text-align: right;
}

@media (max-width: 720px) {
  .research-map {
    box-shadow: 0 1px 0 rgba(24, 24, 27, 0.05);
  }
  .map-stage {
    height: auto;
    display: grid;
    gap: 14px;
    padding-block: 24px;
  }
  .map-stage::before {
    content: '';
    position: absolute;
    z-index: 0;
    top: 24px;
    bottom: 24px;
    left: 50%;
    width: 2px;
    transform: translateX(-50%);
    background: linear-gradient(var(--call) 0 58%, var(--put) 58% 72%, var(--phosphor) 72%);
  }
  .map-stage > svg,
  .map-annotation,
  .map-register {
    display: none;
  }
  .map-node {
    position: relative;
    z-index: 1;
    inset: auto;
    width: 86%;
    min-height: 72px;
    grid-template-columns: 26px 32px 1fr auto;
    grid-template-rows: 1fr 1fr;
  }
  .map-node:nth-of-type(odd) {
    justify-self: start;
  }
  .map-node:nth-of-type(even) {
    justify-self: end;
  }
  .map-node small {
    grid-column: 1;
    grid-row: 1 / 3;
  }
  .map-node > span {
    grid-column: 2;
    grid-row: 1 / 3;
  }
  .map-node strong {
    grid-column: 3;
    grid-row: 1;
    align-self: end;
  }
  .map-node em {
    grid-column: 3;
    grid-row: 2;
    align-self: start;
  }
  .node-arrow {
    grid-column: 4;
    grid-row: 1 / 3;
  }
  footer {
    align-items: flex-start;
    flex-direction: column;
  }
  footer span:last-child {
    text-align: left;
  }
}
@media (prefers-reduced-motion: reduce) {
  .map-node {
    transition: none;
  }
}
</style>
