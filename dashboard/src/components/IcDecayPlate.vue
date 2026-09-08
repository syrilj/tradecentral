<script setup lang="ts">
import { computed } from 'vue'
import { icDecayModel } from '@/charts/landing-viz'

/**
 * Governance band's research-diagnostics plate.
 *
 * Replaces a decorative waveform raster with the figure the section actually
 * describes: a signal-diagnostics panel in the shape of the desk's real
 * research card (IC decay curve plus the per-horizon table). Every number is
 * derived by icDecayModel from (ic1d, sd, periods) — a parameterised MODEL
 * SHAPE, clearly labelled as such; the measured walk-forward ledgers sit
 * behind sign-in.
 */
const model = computed(() =>
  icDecayModel({
    ic1d: 0.004,
    icSdDaily: 0.085,
    periods1d: 491,
    // Pinned curvature of the model: IC builds to a short-horizon peak, then
    // decays through zero by ~2 weeks. Coefficients are the figure's anatomy,
    // stated in one place rather than smeared across chart points.
    shape: [1.0, 1.18, 1.6, 1.28, 0.05, -0.25],
  }),
)

/* ── Chart geometry ───────────────────────────────────────────────────────── */
const VB_W = 560
const VB_H = 168
const PAD = { l: 44, r: 14, t: 14, b: 24 }
const plotW = VB_W - PAD.l - PAD.r
const plotH = VB_H - PAD.t - PAD.b

const hMin = 1
const hMax = 20
// Log-spaced horizon axis, matching the desk's 1..20D decay charts.
const xOf = (h: number): number =>
  PAD.l + ((Math.log(h) - Math.log(hMin)) / (Math.log(hMax) - Math.log(hMin))) * plotW

const icPad = 0.002
const icLo = computed(() => Math.min(...model.value.rows.map((r) => r.meanIc)) - icPad)
const icHi = computed(() => Math.max(...model.value.rows.map((r) => r.meanIc)) + icPad)
const yOf = computed(() => (ic: number): number =>
  PAD.t + ((icHi.value - ic) / (icHi.value - icLo.value)) * plotH,
)

const linePath = computed(() =>
  model.value.rows
    .map((r, i) => `${i === 0 ? 'M' : 'L'}${xOf(r.days).toFixed(1)},${yOf.value(r.meanIc).toFixed(1)}`)
    .join(''),
)
const areaPath = computed(
  () =>
    `${linePath.value}L${xOf(20).toFixed(1)},${yOf.value(0).toFixed(1)}L${xOf(1).toFixed(1)},${yOf.value(0).toFixed(1)}z`,
)
const zeroY = computed(() => yOf.value(0))

const horizonLabel = (h: number): string => `${h}d`
</script>

<template>
  <div
    class="ic-plate"
    role="img"
    aria-label="Signal diagnostics model: rank IC decay from 1 to 20 days as a curve over a per-horizon table of mean IC, Newey-West t, IC IR, percent positive, and periods. Parameterised model shape; measured ledgers appear after sign-in."
  >
    <div class="banner">
      <span class="b-chip">MODEL SHAPE</span>
      <span class="b-copy"
        >Diagnostics describe the shape of a signal — never evidence for a gate. Measured
        walk-forward ledgers appear after sign-in.</span
      >
    </div>

    <div class="kpis">
      <div class="kpi">
        <span class="k-label">Rank IC (1D)</span>
        <strong class="k-val">{{ model.ic1d.toFixed(4) }}</strong>
      </div>
      <div class="kpi">
        <span class="k-label">IC peak</span>
        <strong class="k-val pos">{{
          Math.max(...model.rows.map((r) => r.meanIc)).toFixed(4)
        }}</strong>
        <span class="k-sub">AT {{ model.peakDays }}D</span>
      </div>
      <div class="kpi">
        <span class="k-label">Half-life</span>
        <strong class="k-val">{{ model.halfLifeDays.toFixed(1) }}D</strong>
        <span class="k-sub">IC ÷ 2 FROM PEAK</span>
      </div>
      <div class="kpi">
        <span class="k-label">Sign persistence</span>
        <strong class="k-val">{{ (model.signPersistence * 100).toFixed(0) }}%</strong>
        <span class="k-sub">OF 6 HORIZONS</span>
      </div>
    </div>

    <div class="chart-zone">
      <div class="zone-head">
        <span class="z-title">IC DECAY · 1..20D</span>
        <span class="z-meta">σ(DAILY IC) 0.085 · 491 PERIODS</span>
      </div>
      <svg :viewBox="`0 0 ${VB_W} ${VB_H}`" aria-hidden="true">
        <!-- zero reference + y gridlines -->
        <line :x1="PAD.l" :y1="zeroY" :x2="VB_W - PAD.r" :y2="zeroY" class="zero" />
        <line
          v-for="g in [-0.005, 0.005, 0.01]"
          :key="g"
          :x1="PAD.l"
          :y1="yOf(g)"
          :x2="VB_W - PAD.r"
          :y2="yOf(g)"
          class="grid"
          v-show="g > icLo && g < icHi"
        />
        <text
          v-for="g in [-0.005, 0.005, 0.01]"
          :key="`t-${g}`"
          :x="PAD.l - 6"
          :y="yOf(g) + 3"
          text-anchor="end"
          class="y-label"
          v-show="g > icLo && g < icHi"
        >
          {{ g >= 0 ? '+' : '' }}{{ g.toFixed(3) }}
        </text>

        <!-- area under/over the zero line + curve -->
        <path :d="areaPath" class="ic-area" />
        <path :d="linePath" class="ic-line" />

        <!-- horizon markers + x labels -->
        <g v-for="row in model.rows" :key="row.days">
          <line
            :x1="xOf(row.days)"
            :y1="yOf(row.meanIc)"
            :x2="xOf(row.days)"
            :y2="zeroY"
            class="drop"
          />
          <circle
            :cx="xOf(row.days)"
            :cy="yOf(row.meanIc)"
            r="3.2"
            :class="row.meanIc >= 0 ? 'dot pos' : 'dot neg'"
          />
          <text :x="xOf(row.days)" :y="VB_H - 8" text-anchor="middle" class="x-label">
            {{ horizonLabel(row.days) }}
          </text>
        </g>
      </svg>
    </div>

    <table class="ic-table">
      <thead>
        <tr>
          <th>Horizon</th>
          <th>Mean IC</th>
          <th>NW t</th>
          <th>IC IR</th>
          <th>% positive</th>
          <th>Periods</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in model.rows" :key="row.days">
          <td>{{ horizonLabel(row.days) }}</td>
          <td :class="row.meanIc >= 0 ? 'pos' : 'neg'">{{ row.meanIc.toFixed(4) }}</td>
          <td>{{ row.nwT.toFixed(2) }}</td>
          <td>{{ row.icIr.toFixed(3) }}</td>
          <td>{{ (row.pctPositive * 100).toFixed(1) }}%</td>
          <td>{{ row.periods }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
/* Lives inside the navy evidence band, so it inherits the band's remapped
   tokens (--panel, --ink-*, --call/--put, --tc-yellow) directly. */
.ic-plate {
  display: flex;
  flex-direction: column;
  background: var(--void);
  color: var(--ink);
  font-family: var(--font-data);
}

.banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  border-bottom: var(--hair) solid var(--rule);
  background: var(--panel-hi);
}
.b-chip {
  flex: none;
  padding: 2px 7px;
  background: var(--tc-yellow);
  color: var(--tc-navy);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
}
.b-copy {
  font-size: 9.5px;
  letter-spacing: 0.03em;
  color: var(--ink-dim);
}

.kpis {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border-bottom: var(--hair) solid var(--rule);
}
.kpi {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 11px 14px;
  border-left: var(--hair) solid var(--rule);
}
.kpi:first-child {
  border-left: 0;
}
.k-label {
  font-size: 9px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-faint);
}
.k-val {
  font-size: 15px;
  font-weight: 700;
}
.k-val.pos {
  color: var(--call);
}
.k-sub {
  font-size: 8.5px;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}

.chart-zone {
  padding: 12px 14px 6px;
  border-bottom: var(--hair) solid var(--rule);
}
.zone-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 2px;
}
.z-title {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--ink-dim);
}
.z-meta {
  font-size: 9px;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
svg {
  display: block;
  width: 100%;
  height: auto;
}
.zero {
  stroke: var(--ink-ghost);
  stroke-width: 1;
}
.grid {
  stroke: var(--rule);
  stroke-width: 1;
}
.y-label,
.x-label {
  font-family: var(--font-data);
  font-size: 8.5px;
  fill: var(--ink-faint);
  letter-spacing: 0.04em;
}
.ic-area {
  fill: rgba(255, 130, 4, 0.08);
}
.ic-line {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1.8;
}
.drop {
  stroke: var(--rule);
  stroke-width: 1;
  stroke-dasharray: 2 3;
}
.dot {
  stroke: var(--void);
  stroke-width: 1.2;
}
.dot.pos {
  fill: var(--phosphor);
}
.dot.neg {
  fill: var(--ink-faint);
}

.ic-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 10.5px;
  letter-spacing: 0.04em;
}
.ic-table th {
  padding: 8px 14px;
  text-align: left;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-faint);
  border-bottom: var(--hair) solid var(--rule);
}
.ic-table td {
  padding: 6px 14px;
  border-bottom: var(--hair) solid var(--rule-faint);
  color: var(--ink-dim);
}
.ic-table tr:last-child td {
  border-bottom: 0;
}
.ic-table td.pos {
  color: var(--call);
}
.ic-table td.neg {
  color: var(--put);
}
.ic-table th:not(:first-child),
.ic-table td:not(:first-child) {
  text-align: right;
}

@media (max-width: 700px) {
  .kpis {
    grid-template-columns: repeat(2, 1fr);
  }
  .kpi:nth-child(3) {
    border-left: 0;
  }
  .kpi:nth-child(n + 3) {
    border-top: var(--hair) solid var(--rule);
  }
  .ic-table th:nth-child(5),
  .ic-table td:nth-child(5) {
    display: none;
  }
}
</style>
