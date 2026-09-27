<script setup lang="ts">
/**
 * Three small bespoke diagrams for the Flow feature boxes.
 *
 * Each one draws the thing its box names — a gamma profile with its sign
 * flip, a tape whose prints carry an aggressor side (or don't), a sweep
 * spread across venues beside a single-venue block. Structural anatomy: the
 * shapes are hand-placed to read clearly at card size, not sampled from a
 * quote feed. Live per-symbol versions of all three sit behind sign-in.
 */
export type FlowSignatureKind = 'gex' | 'signed' | 'execution'

defineProps<{ kind: FlowSignatureKind }>()

/* ── gex: dealer gamma by strike, sign flipping between slots 3 and 4 ─────── */
const GEX_BARS = [18, 27, 11, -22, -14, -30, -9] as const
const GEX_X = (i: number): number => 16 + i * 27
const GEX_ZERO = 40

/* ── signed: prints down the tape, two of them without a provider side ────── */
const PRINTS = [
  { side: 'buy', w: 52 },
  { side: 'sell', w: 34 },
  { side: 'none', w: 44 },
  { side: 'buy', w: 68 },
  { side: 'sell', w: 26 },
  { side: 'none', w: 38 },
] as const

/* ── execution: one sweep across four venues, one block on a single venue ── */
const SWEEP_FILLS = [
  { x: 74, w: 22 },
  { x: 104, w: 15 },
  { x: 127, w: 26 },
  { x: 161, w: 18 },
] as const
</script>

<template>
  <div class="flow-sig" :class="`sig-${kind}`">
    <!-- ── 01 · gamma topology ───────────────────────────────────────────── -->
    <svg
      v-if="kind === 'gex'"
      viewBox="0 0 220 76"
      role="img"
      aria-label="Dealer gamma by strike: positive exposure above the zero line, negative below, with the flip strike marked where the sign changes."
    >
      <path class="zero" :d="`M8 ${GEX_ZERO}H212`" />
      <g class="gex-bar">
        <rect
          v-for="(v, i) in GEX_BARS"
          :key="i"
          :class="v >= 0 ? 'pos' : 'neg'"
          :x="GEX_X(i)"
          :y="v >= 0 ? GEX_ZERO - v : GEX_ZERO"
          width="14"
          :height="Math.abs(v)"
        />
      </g>
      <path class="flip" d="M94 8V68" />
      <text class="lbl flip-lbl" x="97" y="15">FLIP</text>
      <text class="lbl pos-lbl" x="8" y="15">+γ</text>
      <text class="lbl neg-lbl" x="8" y="72">−γ</text>
      <text class="lbl dim" x="176" y="72">STRIKE →</text>
    </svg>

    <!-- ── 02 · signed tape ──────────────────────────────────────────────── -->
    <svg
      v-else-if="kind === 'signed'"
      viewBox="0 0 220 86"
      role="img"
      aria-label="A tape of prints separated into buyer-initiated and seller-initiated flow, with prints the provider left unsigned drawn as hollow outlines rather than assigned a side."
    >
      <path class="mid" d="M104 4V72" />
      <g class="print">
        <template v-for="(p, i) in PRINTS" :key="i">
          <rect
            v-if="p.side === 'buy'"
            class="buy"
            :x="106"
            :y="6 + i * 11"
            :width="p.w"
            height="7"
          />
          <rect
            v-else-if="p.side === 'sell'"
            class="sell"
            :x="102 - p.w"
            :y="6 + i * 11"
            :width="p.w"
            height="7"
          />
          <rect
            v-else
            class="unsigned"
            :x="104 - p.w / 2"
            :y="6 + i * 11"
            :width="p.w"
            height="7"
          />
        </template>
      </g>
      <text class="lbl sell-lbl" x="8" y="83">SELLER INIT.</text>
      <text class="lbl buy-lbl" x="212" y="83" text-anchor="end">BUYER INIT.</text>
      <text class="lbl dim" x="104" y="83" text-anchor="middle">UNSIGNED</text>
    </svg>

    <!-- ── 03 · execution class ──────────────────────────────────────────── -->
    <svg
      v-else
      viewBox="0 0 220 76"
      role="img"
      aria-label="An intermarket sweep filling across four exchange rails, drawn beside a single block resting on one rail."
    >
      <text class="lbl sweep-lbl" x="212" y="8" text-anchor="end">SWEEP · TAKES 4 VENUES</text>

      <g class="venue-rail">
        <path d="M58 16H212M58 28H212M58 40H212M58 52H212" />
      </g>
      <g class="rail-lbl">
        <text x="6" y="19">XNAS</text>
        <text x="6" y="31">ARCA</text>
        <text x="6" y="43">BATS</text>
        <text x="6" y="55">EDGX</text>
      </g>

      <!-- one parent order fanning into four venue fills -->
      <path
        class="fan"
        d="M46 34C54 34 54 16 74 16M46 34C54 34 54 28 104 28M46 34C54 34 54 40 127 40M46 34C54 34 54 52 161 52"
      />
      <circle class="parent" cx="44" cy="34" r="4" />
      <g class="fill sweep">
        <rect
          v-for="(f, i) in SWEEP_FILLS"
          :key="i"
          :x="f.x"
          :y="12 + i * 12"
          :width="f.w"
          height="8"
        />
      </g>

      <!-- single-venue block for contrast -->
      <path class="venue-rail single" d="M58 68H212" />
      <rect class="fill block" x="104" y="64" width="58" height="9" />
      <text class="lbl dim" x="6" y="71">BLOCK</text>
    </svg>
  </div>
</template>

<style scoped>
.flow-sig {
  margin-top: 2px;
  padding: 7px 8px 5px;
  border: var(--hair) solid var(--rule);
  background: var(--panel);
}
.flow-sig > svg {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}

.lbl {
  fill: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
}
.lbl.dim {
  fill: var(--ink-faint);
}

/* ── gex ──────────────────────────────────────────────────────────────────── */
.zero {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1;
}
.gex-bar .pos {
  fill: var(--call);
}
.gex-bar .neg {
  fill: var(--put);
}
.flip {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1;
  stroke-dasharray: 3 2;
}
.flip-lbl {
  fill: var(--phosphor);
}
.pos-lbl {
  fill: var(--call);
}
.neg-lbl {
  fill: var(--put);
}

/* ── signed tape ──────────────────────────────────────────────────────────── */
.mid {
  fill: none;
  stroke: var(--rule-hi);
  stroke-width: 1;
}
.print .buy {
  fill: var(--call);
}
.print .sell {
  fill: var(--put);
}
.print .unsigned {
  fill: none;
  stroke: var(--ink-ghost);
  stroke-width: 1;
  stroke-dasharray: 2 2;
}
.buy-lbl {
  fill: var(--call);
}
.sell-lbl {
  fill: var(--put);
}

/* ── execution ────────────────────────────────────────────────────────────── */
/* .venue-rail, not .rail: the landing page hides the desk shell's `.rail`
   sidebar with a global `display: none !important` that a bare `.rail` here
   would inherit, taking the exchange rails with it. */
.venue-rail {
  fill: none;
  stroke: var(--rule-hi);
  stroke-width: 1;
}
/* Without this the venue names inherit the SVG default of 16px and print
   straight over their own rails. */
.rail-lbl text {
  fill: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.06em;
}
.fan {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1;
  opacity: 0.75;
}
.parent {
  fill: var(--void);
  stroke: var(--phosphor);
  stroke-width: 1.4;
}
.fill.sweep rect {
  fill: var(--phosphor);
}
.fill.block {
  fill: var(--ink-soft);
}
.sweep-lbl {
  fill: var(--phosphor);
}
</style>
