<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'

const nodes = [
  { icon: 'desk', name: 'Desk', path: '/desk', note: 'Posture', className: 'node-desk' },
  { icon: 'market', name: 'Market', path: '/market', note: 'Context', className: 'node-market' },
  { icon: 'options', name: 'Options', path: '/options', note: 'Positioning', className: 'node-options' },
  { icon: 'flow', name: 'Flow', path: '/flow', note: 'Concentration', className: 'node-flow' },
  { icon: 'research', name: 'Research', path: '/research', note: 'Evidence', className: 'node-research' },
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
        <path class="path-shadow" d="M65 246C143 245 141 112 237 112s92 158 195 158 83-173 183-173 80 138 104 163" />
        <path class="path-main" d="M65 246C143 245 141 112 237 112s92 158 195 158 83-173 183-173 80 138 104 163" />
        <path class="path-return" d="M719 260C644 338 560 336 486 312S329 332 243 301 115 294 65 246" />
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
      <div class="map-register" aria-hidden="true">SIGNAL → CONTEXT → POSITIONING → FLOW → EVIDENCE</div>
    </div>
    <footer><span>Specialist tools remain adjacent—not mixed into the primary path.</span><span>Sectors · Pulse · Gates · Graph · Cloud</span></footer>
  </figure>
</template>

<style scoped>
.research-map { position: relative; margin: 0; padding: 17px 19px 14px; overflow: hidden; color: #191a17; border: 1px solid #c9c5ba; border-top: 2px solid #788c5d; background: #e9e6dc; box-shadow: 18px 20px 0 rgba(120,140,93,.13); }
.research-map::before,
.research-map::after { content: ''; position: absolute; width: 13px; height: 13px; z-index: 4; pointer-events: none; }
.research-map::before { top: -1px; left: -1px; border-top: 1px solid #141413; border-left: 1px solid #141413; }
.research-map::after { right: -1px; bottom: -1px; border-right: 1px solid #141413; border-bottom: 1px solid #141413; }
figcaption,
footer { display: flex; justify-content: space-between; gap: 20px; color: #77746c; font-family: var(--font-display); font-size: 8px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
figcaption { padding-bottom: 13px; border-bottom: 1px solid #c7c3b8; }
.map-stage { position: relative; height: 390px; overflow: hidden; background: linear-gradient(rgba(20,20,19,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(20,20,19,.045) 1px, transparent 1px); background-size: 30px 30px; }
.map-stage > svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; fill: #faf9f5; stroke: #788c5d; stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.path-shadow { fill: none; stroke: rgba(20,20,19,.16); stroke-width: 11; }
.path-main { fill: none; stroke: #6a9bcc; stroke-width: 2; }
.path-return { fill: none; stroke: #d97757; stroke-width: 1; stroke-dasharray: 5 6; }
.map-node { position: absolute; z-index: 2; width: 126px; min-height: 98px; display: grid; grid-template-columns: 28px 1fr auto; grid-template-rows: auto auto auto; align-items: center; gap: 2px 9px; padding: 11px; color: #25251f; border: 1px solid #aaa69c; background: rgba(250,249,245,.96); transition: transform var(--dur-fast), border-color var(--dur-fast), box-shadow var(--dur-fast); }
.map-node:hover { transform: translateY(-4px); border-color: #57554e; box-shadow: 6px 7px 0 rgba(20,20,19,.10); text-decoration: none; }
.map-node small { grid-column: 1 / -1; color: #858178; font-family: var(--font-data); font-size: 8px; }
.map-node > span { grid-row: 2 / 4; width: 28px; height: 28px; display: grid; place-items: center; color: #426f98; border: 1px solid #bcb8ae; }
.map-node strong { font-family: var(--font-ui); font-size: 12px; font-style: normal; font-weight: 680; }
.map-node em { color: #77746c; font-family: var(--font-display); font-size: 7px; font-style: normal; letter-spacing: .06em; text-transform: uppercase; }
.node-arrow { grid-row: 2 / 4; color: #788c5d; }
.node-desk { left: 1%; top: 47%; }
.node-market { left: 18%; top: 6%; }
.node-options { left: 44%; top: 53%; }
.node-flow { right: 10%; top: 3%; }
.node-research { right: 0; top: 50%; }
.map-annotation { position: absolute; color: #68665f; font-family: var(--font-ui); font-size: 10px; }
.map-annotation span { display: block; margin-bottom: 4px; color: #d97757; font-family: var(--font-display); font-size: 7px; font-weight: 700; letter-spacing: .09em; }
.annotation-input { left: 2%; bottom: 28px; }
.annotation-output { right: 1%; bottom: 28px; text-align: right; }
.map-register { position: absolute; right: 23%; bottom: 24px; left: 23%; color: #8a877e; font-family: var(--font-display); font-size: 7px; letter-spacing: .08em; text-align: center; }
footer { padding-top: 13px; border-top: 1px solid #c7c3b8; }
footer span:last-child { color: #5f7650; text-align: right; }

@media (max-width: 720px) {
  .research-map { box-shadow: 9px 11px 0 rgba(120,140,93,.13); }
  .map-stage { height: auto; display: grid; gap: 14px; padding-block: 24px; }
  .map-stage::before { content: ''; position: absolute; z-index: 0; top: 24px; bottom: 24px; left: 50%; width: 2px; transform: translateX(-50%); background: linear-gradient(#6a9bcc 0 58%, #d97757 58% 72%, #788c5d 72%); }
  .map-stage > svg,
  .map-annotation,
  .map-register { display: none; }
  .map-node { position: relative; z-index: 1; inset: auto; width: 86%; min-height: 72px; grid-template-columns: 26px 32px 1fr auto; grid-template-rows: 1fr 1fr; box-shadow: 4px 5px 0 rgba(20,20,19,.07); }
  .map-node:nth-of-type(odd) { justify-self: start; }
  .map-node:nth-of-type(even) { justify-self: end; }
  .map-node small { grid-column: 1; grid-row: 1 / 3; }
  .map-node > span { grid-column: 2; grid-row: 1 / 3; }
  .map-node strong { grid-column: 3; grid-row: 1; align-self: end; }
  .map-node em { grid-column: 3; grid-row: 2; align-self: start; }
  .node-arrow { grid-column: 4; grid-row: 1 / 3; }
  footer { align-items: flex-start; flex-direction: column; }
  footer span:last-child { text-align: left; }
}
@media (prefers-reduced-motion: reduce) { .map-node { transition: none; } }
</style>
