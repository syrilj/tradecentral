<script setup lang="ts">
/**
 * One bespoke micro-instrument per method principle.
 *
 * These are not decorative icons. Each diagram draws the rule it sits next to
 * as a mechanism a reader can inspect: the gap that never becomes a zero, the
 * wall an ordinal reading never crosses, the series latch that defaults to
 * closed, the severed connector at the system edge. Structural anatomy only —
 * no sample data, no quotes, no invented scores.
 *
 * Every diagram shares one plate geometry (260 x 112 viewBox, 8px mono labels,
 * hairline rules) so the four read as a set drawn by the same hand, while the
 * mechanism inside each one is different enough that the row never looks like
 * four copies of a template.
 */
export type PrincipleKind = 'missing' | 'typed' | 'failclosed' | 'outside'

defineProps<{ kind: PrincipleKind }>()

/* ── A · missing ───────────────────────────────────────────────────────────
   Eight sample slots on one axis. Five carry an observation; three are
   absent and are drawn as open, hatched voids that drop to a NULL rail —
   never to the baseline, which is what a silent zero-fill would look like. */
const SAMPLES: { present: boolean; h: number }[] = [
  { present: true, h: 26 },
  { present: true, h: 38 },
  { present: false, h: 0 },
  { present: true, h: 31 },
  { present: false, h: 0 },
  { present: true, h: 44 },
  { present: false, h: 0 },
  { present: true, h: 35 },
]
const SLOT_X = (i: number): number => 20 + i * 29
const BASE_Y = 74
const NULL_Y = 92

/* ── C · failclosed ────────────────────────────────────────────────────────
   Two contacts wired in series. Promotion needs both closed; the diagram
   holds one open so the output barrier is drawn in its resting state. */
const CONTACTS = [
  { x: 44, label: 'READINESS', closed: true },
  { x: 122, label: 'GATES', closed: false },
] as const
</script>

<template>
  <div class="principle-plate" :class="`plate-${kind}`">
    <!-- ── A · missing stays missing ─────────────────────────────────────── -->
    <svg
      v-if="kind === 'missing'"
      viewBox="0 0 260 112"
      role="img"
      aria-label="A sample series in which three absent observations are drawn as open voids dropping to a null rail, not as zeros on the baseline."
    >
      <path class="rule-faint" d="M10 30H250M10 52H250" />
      <path class="rule-axis" :d="`M10 ${BASE_Y}H250`" />
      <path class="rule-null" :d="`M10 ${NULL_Y}H250`" />

      <g class="bar-present">
        <rect
          v-for="(s, i) in SAMPLES"
          v-show="s.present"
          :key="`p${i}`"
          :x="SLOT_X(i)"
          :y="BASE_Y - s.h"
          width="15"
          :height="s.h"
        />
      </g>

      <g class="bar-void">
        <template v-for="(s, i) in SAMPLES" :key="`v${i}`">
          <rect v-if="!s.present" :x="SLOT_X(i)" y="26" width="15" :height="BASE_Y - 26" />
          <path
            v-if="!s.present"
            class="void-drop"
            :d="`M${SLOT_X(i) + 7.5} ${BASE_Y}V${NULL_Y}`"
          />
          <rect
            v-if="!s.present"
            class="void-tick"
            :x="SLOT_X(i) + 3"
            :y="NULL_Y - 3"
            width="9"
            height="6"
          />
        </template>
      </g>

      <text class="lbl" x="10" y="20">OBSERVED</text>
      <text class="lbl accent" x="215" y="106">NULL</text>
    </svg>

    <!-- ── B · evidence stays typed ──────────────────────────────────────── -->
    <svg
      v-else-if="kind === 'typed'"
      viewBox="0 0 260 112"
      role="img"
      aria-label="An ordinal evidence ladder on the left and a continuous probability axis on the right, separated by a type wall that the ladder's arrow stops at rather than crossing."
    >
      <text class="lbl" x="10" y="20">ORDINAL</text>
      <text class="lbl" x="176" y="20">CONTINUOUS</text>

      <g class="ladder">
        <rect x="12" y="66" width="74" height="9" />
        <rect x="12" y="48" width="60" height="9" />
        <rect x="12" y="30" width="44" height="9" />
      </g>
      <g class="ladder-tick">
        <text x="92" y="74">WEAK</text>
        <text x="78" y="56">FAIR</text>
        <text x="62" y="38">STRONG</text>
      </g>

      <!-- the cast that never happens -->
      <path class="cast-arrow" d="M120 52h14" />
      <path class="cast-stop" d="M136 46l10 12M146 46l-10 12" />

      <!-- type wall -->
      <path class="wall" d="M158 16V100" />
      <text class="lbl wall-lbl" x="140" y="110">TYPE BOUNDARY</text>

      <path class="prob-axis" d="M176 62H250" />
      <g class="prob-tick">
        <path d="M176 58v8M213 58v8M250 58v8" />
      </g>
      <g class="prob-num">
        <text x="173" y="80">0</text>
        <text x="205" y="80">0.5</text>
        <text x="245" y="80">1</text>
      </g>
      <text class="lbl dim" x="176" y="44">CALIBRATED P</text>
    </svg>

    <!-- ── C · promotion fails closed ────────────────────────────────────── -->
    <svg
      v-else-if="kind === 'failclosed'"
      viewBox="0 0 260 112"
      role="img"
      aria-label="Readiness and pre-registered gates wired as two contacts in series. One contact is open, so the output barrier stays closed and nothing advances past research."
    >
      <text class="lbl" x="10" y="20">SERIES LATCH · BOTH MUST CLOSE</text>

      <path class="wire" d="M10 56H44M62 56H122M140 56H196" />

      <g v-for="c in CONTACTS" :key="c.label">
        <circle class="node" :cx="c.x" cy="56" r="4" />
        <circle class="node" :cx="c.x + 18" cy="56" r="4" />
        <path
          class="lever"
          :class="c.closed ? 'is-closed' : 'is-open'"
          :d="c.closed ? `M${c.x} 56H${c.x + 18}` : `M${c.x} 56L${c.x + 17} 40`"
        />
        <text class="lbl sm" :x="c.x - 2" y="82">{{ c.label }}</text>
        <text class="verdict" :class="c.closed ? 'ok' : 'no'" :x="c.x - 2" y="94">
          {{ c.closed ? 'CLEARED' : 'NO-GO' }}
        </text>
      </g>

      <!-- resting-state barrier: heavy, because closed is the default -->
      <g class="barrier">
        <rect x="198" y="30" width="10" height="52" />
        <path class="hatch" d="M198 38h10M198 48h10M198 58h10M198 68h10M198 78h10" />
      </g>
      <text class="lbl dim" x="214" y="52">LIVE</text>
      <text class="lbl no" x="214" y="66">HELD</text>
    </svg>

    <!-- ── D · execution stays outside ───────────────────────────────────── -->
    <svg
      v-else
      viewBox="0 0 260 112"
      role="img"
      aria-label="The checked-in pipeline drawn as a closed boundary containing research nodes, with the connector to any broker terminal cut and capped outside it."
    >
      <rect class="boundary" x="10" y="24" width="164" height="72" rx="2" />
      <text class="lbl" x="12" y="18">CHECKED-IN PIPELINE</text>

      <path class="wire" d="M40 60H74M96 60H130" />
      <g class="node-fill">
        <circle cx="32" cy="60" r="7" />
        <circle cx="85" cy="60" r="7" />
        <circle cx="138" cy="60" r="7" />
      </g>
      <!-- Each node carries a mark for what it holds: stacked records,
           a distribution, a cleared verdict. -->
      <g class="node-mark">
        <path d="M28.5 57.5h7M28.5 60h7M28.5 62.5h7" />
        <path d="M81 62.5c2.2 0 1.8-5 4-5s1.8 5 4 5" />
        <path d="M135 60l2 2 4.2-4.4" />
      </g>
      <g class="node-lbl">
        <text x="20" y="84">DATA</text>
        <text x="72" y="84">RESEARCH</text>
        <text x="126" y="84">GATES</text>
      </g>

      <!-- severed connector -->
      <path class="wire cut" d="M174 60h12" />
      <path class="cap" d="M186 52v16" />
      <path class="cut-mark" d="M192 54l10 12M202 54l-10 12" />
      <path class="cap" d="M208 52v16" />
      <path class="wire cut" d="M208 60h6" />

      <rect class="terminal" x="214" y="42" width="34" height="36" rx="2" />
      <path class="terminal-glyph" d="M221 52h20M221 60h20M221 68h12" />
      <text class="lbl dim" x="214" y="34">BROKER</text>
      <text class="lbl no" x="188" y="92">NO ROUTE</text>
    </svg>
  </div>
</template>

<style scoped>
.principle-plate {
  --plate-accent: var(--phosphor);
  position: relative;
  margin-block: 2px 4px;
  padding: 10px 12px;
  border: var(--hair) solid var(--rule);
  background:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px), var(--panel);
  background-size: 22px 22px;
}
.plate-typed {
  --plate-accent: var(--tc-blue);
}
.plate-failclosed {
  --plate-accent: var(--put);
}
.plate-outside {
  --plate-accent: var(--ink);
}

.principle-plate > svg {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}

/* ── shared vocabulary ────────────────────────────────────────────────────── */
.rule-faint {
  fill: none;
  stroke: var(--rule);
  stroke-width: 1;
}
.rule-axis {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1;
}
.rule-null {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1;
  stroke-dasharray: 2 3;
}
.wire {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1.2;
}
.lbl {
  fill: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.09em;
}
.lbl.sm {
  font-size: var(--t-nano);
}
.lbl.dim {
  fill: var(--ink-faint);
}
.lbl.accent {
  fill: var(--plate-accent);
}
.lbl.no {
  fill: var(--put);
}

/* ── A · missing ──────────────────────────────────────────────────────────── */
.bar-present rect {
  fill: var(--ink-soft);
}
.bar-void rect {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}
.void-drop {
  stroke: var(--phosphor);
  stroke-width: 1;
  stroke-dasharray: 2 2;
}
/* Class selector qualified by the element so it outranks `.bar-void rect`
   above — otherwise the rail tick inherits the hollow dashed treatment meant
   for the void column and the NULL rail reads as three more empty boxes. */
.bar-void rect.void-tick {
  fill: var(--phosphor);
  stroke: none;
}

/* ── B · typed ────────────────────────────────────────────────────────────── */
.ladder rect {
  fill: var(--tc-blue);
}
.ladder-tick text {
  fill: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
}
.cast-arrow {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1.2;
}
.cast-stop {
  fill: none;
  stroke: var(--put);
  stroke-width: 1.4;
  stroke-linecap: round;
}
.wall {
  fill: none;
  stroke: var(--ink);
  stroke-width: 2.5;
}
.wall-lbl {
  font-size: var(--t-nano);
}
.prob-axis {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1;
}
.prob-tick {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1;
}
.prob-num text {
  fill: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
}

/* ── C · failclosed ───────────────────────────────────────────────────────── */
.node {
  fill: var(--void);
  stroke: var(--ink-faint);
  stroke-width: 1.2;
}
.lever {
  fill: none;
  stroke-width: 2;
  stroke-linecap: round;
}
.lever.is-closed {
  stroke: var(--call);
}
.lever.is-open {
  stroke: var(--put);
}
.verdict {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
}
.verdict.ok {
  fill: var(--call);
}
.verdict.no {
  fill: var(--put);
}
.barrier rect {
  fill: var(--ink);
}
.barrier .hatch {
  stroke: var(--void);
  stroke-width: 1;
}

/* ── D · outside ──────────────────────────────────────────────────────────── */
.boundary {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1;
  stroke-dasharray: 4 3;
}
.node-fill circle {
  fill: var(--void);
  stroke: var(--ink);
  stroke-width: 1.2;
}
.node-mark {
  fill: none;
  stroke: var(--ink);
  stroke-width: 1.1;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.node-lbl text {
  fill: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.06em;
}
.wire.cut {
  stroke: var(--ink-ghost);
  stroke-dasharray: 3 2;
}
.cap {
  fill: none;
  stroke: var(--ink);
  stroke-width: 1.6;
}
.cut-mark {
  fill: none;
  stroke: var(--put);
  stroke-width: 1.4;
  stroke-linecap: round;
}
.terminal {
  fill: none;
  stroke: var(--ink-ghost);
  stroke-width: 1;
}
.terminal-glyph {
  fill: none;
  stroke: var(--ink-ghost);
  stroke-width: 1;
  stroke-linecap: round;
}
</style>
