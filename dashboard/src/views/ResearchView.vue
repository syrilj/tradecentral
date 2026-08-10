<script setup lang="ts">
/**
 * Factor diagnostics.
 *
 * This view exists to answer one question the repo's own README raises and
 * cannot currently answer: the cross-sectional Rank IC is small but real
 * (0.033, NW t 2.68), and the binding constraint is turnover — "10bp halves
 * the edge." So does the signal survive in the extreme quantiles, which are
 * cheap to hold, or is it spread evenly across the book, where trading costs
 * eat it?
 *
 * Two graphics answer that:
 *
 *  · IC decay — how many days the forecast stays alive. If IC survives to 10
 *    days you can rebalance weekly and the turnover problem largely goes away.
 *    If it dies after one day, no optimizer saves it.
 *  · Quantile spread against its own cost line — each bucket's mean return
 *    drawn against what that bucket costs to hold at its measured turnover.
 *    A bar that does not clear its own cost line is not a tradable bucket,
 *    however good its gross number looks.
 *
 * Nothing here is evidence for a gate. These are diagnostics computed outside
 * `simulate_long_short`, and the repo's rule is that only that module's
 * accounting counts.
 */
import { computed, ref } from 'vue'
import { api, type FactorTearsheet } from '@/api'
import { useResource } from '@/composables/useResource'
import { num, pctFrac, age, DASH } from '@/format'
import { linearScale, niceTicks, linePath } from '@/charts'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import LoadingState from '@/components/LoadingState.vue'

const res = useResource<FactorTearsheet>(() => api.factors(), { intervalMs: 300_000 })

const data = computed(() => res.data.value)
const available = computed(() => data.value?.available === true)
const icRows = computed(() => data.value?.ic_decay ?? [])
const quantiles = computed(() => (data.value?.quantiles ?? []).filter((q) => q.quantile >= 0))
const spreadRow = computed(() => (data.value?.quantiles ?? []).find((q) => q.quantile < 0) ?? null)
const turnover = computed(() => data.value?.quantile_turnover ?? [])

/** 10bp per side is the repo's DEFAULT_COST_PER_SIDE. Round trip is two sides. */
const COST_PER_SIDE = 0.001

const turnoverOf = computed(() => {
  const m = new Map<number, number>()
  for (const t of turnover.value) {
    if (t.mean_turnover != null) m.set(t.quantile, t.mean_turnover)
  }
  return m
})

/** What a bucket costs to hold, at its own measured turnover. */
function costOf(q: number): number | null {
  const t = turnoverOf.value.get(q)
  if (t == null) return null
  return t * COST_PER_SIDE * 2
}

/**
 * Bucket display label.
 *
 * The producer's quantile indexing is not assumed. `factor_tearsheet.py` emits
 * 1-based buckets today; an earlier revision emitted 0-based, and either is a
 * defensible convention. Hardcoding `quantile + 1` silently mislabels every row
 * the moment the other convention shows up — which is exactly what happened
 * here, printing "Q2…Q11" for ten buckets.
 *
 * So the offset is derived from the payload itself: whatever the lowest real
 * bucket is, it is Q1. The spread row (negative index) is excluded from that
 * calculation and never gets a Q-label.
 */
const qOffset = computed(() => {
  const real = quantiles.value.map((q) => q.quantile).filter((q) => q >= 0)
  return real.length ? Math.min(...real) : 0
})

function qLabel(q: number): string {
  return `Q${q - qOffset.value + 1}`
}

const headlineIc = computed(() => icRows.value.find((r) => r.horizon === 1) ?? icRows.value[0] ?? null)
const survivingHorizon = computed(() => {
  // The longest horizon whose IC is still significant at |t| >= 2. This is the
  // number that sets a viable rebalance period.
  const alive = icRows.value.filter((r) => r.ic_t_stat != null && Math.abs(r.ic_t_stat) >= 2)
  if (!alive.length) return null
  return Math.max(...alive.map((r) => r.horizon))
})

/* ---- IC decay chart ------------------------------------------------------ */
const IC_W = 720
const IC_H = 220
const PAD = { t: 16, r: 16, b: 30, l: 52 }

const icChart = computed(() => {
  const rows = icRows.value.filter((r) => r.mean_ic != null)
  if (rows.length < 2) return null
  const xs = rows.map((r) => r.horizon)
  const ys = rows.map((r) => r.mean_ic as number)
  const yMax = Math.max(...ys.map(Math.abs), 0.01) * 1.25
  const x = linearScale([Math.min(...xs), Math.max(...xs)], [PAD.l, IC_W - PAD.r])
  const y = linearScale([-yMax, yMax], [IC_H - PAD.b, PAD.t])
  const pts = rows.map((r) => ({ x: x(r.horizon), y: y(r.mean_ic as number) }))
  return {
    rows,
    x,
    y,
    path: linePath(pts),
    pts: pts.map((p, i) => ({ ...p, row: rows[i] })),
    zeroY: y(0),
    yTicks: niceTicks(-yMax, yMax, 5),
  }
})

/* ---- quantile chart ------------------------------------------------------ */
const Q_H = 240
const Q_PAD = { t: 16, r: 16, b: 34, l: 52 }

const qChart = computed(() => {
  const rows = quantiles.value
  if (!rows.length) return null
  const rets = rows.map((r) => r.mean_return ?? 0)
  const costs = rows.map((r) => costOf(r.quantile) ?? 0)
  // Zero is always in frame — a bar chart of returns that crops the zero line
  // makes a small positive number look like a large one. But only the RETURNS
  // can go negative; a cost is a magnitude and is always drawn above zero, so
  // it must not drag the lower bound down and leave half the panel empty.
  const lo = Math.min(0, ...rets)
  const hi = Math.max(0, ...rets, ...costs)
  const padAmt = (hi - lo) * 0.15 || 0.001
  const y = linearScale([lo - padAmt, hi + padAmt], [Q_H - Q_PAD.b, Q_PAD.t])
  const n = rows.length
  const slot = (100 - 0) / n
  return {
    rows,
    y,
    zeroY: y(0),
    yTicks: niceTicks(lo - padAmt, hi + padAmt, 5),
    // Bars are laid out in percentage units so the SVG stretches with the
    // panel without recomputing a pixel scale on resize.
    band: (i: number) => ({ left: i * slot, width: slot }),
    slot,
  }
})

/** A bucket is only tradable if its gross return clears its own cost. */
function clears(q: number, ret: number | null): boolean | null {
  const c = costOf(q)
  if (c == null || ret == null) return null
  return ret > c
}

const tradableCount = computed(
  () => quantiles.value.filter((q) => clears(q.quantile, q.mean_return) === true).length,
)

function toneFor(v: number | null | undefined): 'pos' | 'neg' | 'flat' {
  if (v == null || !Number.isFinite(v)) return 'flat'
  return v > 0 ? 'pos' : v < 0 ? 'neg' : 'flat'
}

const chartTab = ref<'ic' | 'quantile'>('ic')
</script>

<template>
  <div class="research">
    <Panel
      label="Factor diagnostics"
      index="09"
      :meta="data?.generated_at ? `computed ${age(data.generated_at)} ago` : 'diagnostics only'"
      class="w-full"
    >
      <LoadingState v-if="res.loading.value && !data" label="computing tearsheet" />
      <p v-else-if="res.error.value" class="err">{{ res.error.value }}</p>

      <template v-else-if="available">
        <div class="banner">
          <span class="pill">DIAGNOSTIC ONLY</span>
          <span class="banner-text">
            Computed outside <code>simulate_long_short</code>. These numbers describe the shape of
            the signal — they are not evidence for a gate and never authorise a trade.
          </span>
        </div>
        <div class="counts">
          <Readout
            label="Rank IC (1d)"
            :value="num(headlineIc?.mean_ic, 4)"
            :sub="headlineIc?.ic_t_stat != null ? `NW t ${num(headlineIc.ic_t_stat, 2)}` : undefined"
            :tone="toneFor(headlineIc?.mean_ic)"
          />
          <Readout
            label="Signal half-life"
            :value="survivingHorizon != null ? `${survivingHorizon}d` : DASH"
            sub="last horizon with |t| ≥ 2"
            :tone="survivingHorizon != null && survivingHorizon >= 5 ? 'pos' : 'flat'"
          />
          <Readout
            label="Monotonicity"
            :value="num(data?.monotonicity, 3)"
            sub="quantile rank vs return"
            :tone="toneFor(data?.monotonicity)"
          />
          <Readout
            label="Buckets clearing cost"
            :value="`${tradableCount}/${quantiles.length}`"
            sub="gross return > own turnover cost"
            :tone="tradableCount > 0 ? 'pos' : 'neg'"
          />
        </div>
        <p class="dims">
          {{ data?.n_dates }} dates · {{ data?.n_symbols }} symbols · execution lag
          {{ data?.execution_lag }} bar{{ data?.execution_lag === 1 ? '' : 's' }}
          <span v-if="data?.source"> · {{ data.source }}</span>
        </p>
      </template>

      <div v-else class="empty">
        <p class="note">
          No tearsheet yet{{ data?.reason ? ` — ${data.reason}` : '' }}. Build one:
        </p>
        <ul class="cmds">
          <li>
            <code>edge/.venv-qlib/bin/python edge/tools/factor_tearsheet.py</code>
            <span class="dim">writes runs/factor_diagnostics/</span>
          </li>
        </ul>
      </div>
    </Panel>

    <template v-if="available">
      <Panel
        label="Signal diagnostics"
        index="—"
        :meta="chartTab === 'ic' ? 'IC decay' : `top−bottom ${spreadRow ? pctFrac(spreadRow.mean_return, 3) : '—'}`"
        :delay="40"
        class="w-full"
      >
        <!-- tab strip -->
        <div class="chart-tabs">
          <button type="button" class="ctab label" :class="{ on: chartTab === 'ic' }" @click="chartTab = 'ic'">IC DECAY</button>
          <button type="button" class="ctab label" :class="{ on: chartTab === 'quantile' }" @click="chartTab = 'quantile'">QUANTILE SPREAD</button>
        </div>

        <!-- IC DECAY tab -->
        <template v-if="chartTab === 'ic'">
          <svg v-if="icChart" :viewBox="`0 0 ${IC_W} ${IC_H}`" class="chart" preserveAspectRatio="none">
            <g class="axis">
              <line
                v-for="t in icChart.yTicks"
                :key="`gy-${t}`"
                :x1="PAD.l"
                :x2="IC_W - PAD.r"
                :y1="icChart.y(t)"
                :y2="icChart.y(t)"
                class="gridline"
              />
              <text
                v-for="t in icChart.yTicks"
                :key="`ly-${t}`"
                :x="PAD.l - 8"
                :y="icChart.y(t) + 3"
                text-anchor="end"
                class="tick-label"
              >{{ t.toFixed(3) }}</text>
            </g>

            <line
              :x1="PAD.l"
              :x2="IC_W - PAD.r"
              :y1="icChart.zeroY"
              :y2="icChart.zeroY"
              class="zero"
            />

            <path :d="icChart.path" class="ic-line" />

            <g v-for="p in icChart.pts" :key="`p-${p.row.horizon}`">
              <circle
                :cx="p.x"
                :cy="p.y"
                r="3.5"
                :class="[
                  'ic-dot',
                  p.row.ic_t_stat != null && Math.abs(p.row.ic_t_stat) >= 2 ? 'sig' : 'weak',
                ]"
              />
              <text :x="p.x" :y="IC_H - 10" text-anchor="middle" class="tick-label">
                {{ p.row.horizon }}d
              </text>
            </g>
          </svg>
          <p v-else class="note">Not enough horizons to plot a decay curve.</p>

          <table v-if="icRows.length" class="grid ic-table">
            <thead>
              <tr>
                <th class="label">Horizon</th>
                <th class="label num">Mean IC</th>
                <th class="label num">NW t</th>
                <th class="label num">IC IR</th>
                <th class="label num">% positive</th>
                <th class="label num">Periods</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in icRows"
                :key="r.horizon"
                :class="{ faded: r.ic_t_stat == null || Math.abs(r.ic_t_stat) < 2 }"
              >
                <td class="fig">{{ r.horizon }}d</td>
                <td class="fig num" :class="toneFor(r.mean_ic)">{{ num(r.mean_ic, 4) }}</td>
                <td class="fig num">{{ num(r.ic_t_stat, 2) }}</td>
                <td class="fig num">{{ num(r.ic_ir, 3) }}</td>
                <td class="fig num">{{ pctFrac(r.pct_positive, 1) }}</td>
                <td class="fig num dim">{{ r.n_periods }}</td>
              </tr>
            </tbody>
          </table>
        </template>

        <!-- QUANTILE SPREAD tab -->
        <template v-else-if="chartTab === 'quantile'">
          <div v-if="qChart" class="qwrap">
            <svg :viewBox="`0 0 100 ${Q_H}`" class="chart qchart" preserveAspectRatio="none">
              <line
                v-for="t in qChart.yTicks"
                :key="`qg-${t}`"
                x1="0"
                x2="100"
                :y1="qChart.y(t)"
                :y2="qChart.y(t)"
                class="gridline"
                vector-effect="non-scaling-stroke"
              />
              <line
                x1="0"
                x2="100"
                :y1="qChart.zeroY"
                :y2="qChart.zeroY"
                class="zero"
                vector-effect="non-scaling-stroke"
              />

              <g v-for="(r, i) in qChart.rows" :key="`bar-${r.quantile}`">
                <rect
                  :x="qChart.band(i).left + qChart.slot * 0.22"
                  :y="Math.min(qChart.zeroY, qChart.y(r.mean_return ?? 0))"
                  :width="qChart.slot * 0.56"
                  :height="Math.abs(qChart.y(r.mean_return ?? 0) - qChart.zeroY)"
                  :class="['qbar', (r.mean_return ?? 0) >= 0 ? 'up' : 'down']"
                />
                <line
                  v-if="costOf(r.quantile) != null"
                  :x1="qChart.band(i).left + qChart.slot * 0.14"
                  :x2="qChart.band(i).left + qChart.slot * 0.86"
                  :y1="qChart.y(costOf(r.quantile) as number)"
                  :y2="qChart.y(costOf(r.quantile) as number)"
                  class="costline"
                  vector-effect="non-scaling-stroke"
                />
              </g>
            </svg>
            <div class="qaxis">
              <span v-for="r in qChart.rows" :key="`qa-${r.quantile}`" class="label qlab">
                {{ qLabel(r.quantile) }}
              </span>
            </div>
            <div class="legend">
              <span class="key"><i class="sw up" /> mean forward return</span>
              <span class="key"><i class="sw cost" /> round-trip cost at measured turnover</span>
            </div>
          </div>
          <p v-else class="note">No quantile rows.</p>

          <table v-if="quantiles.length" class="grid">
            <thead>
              <tr>
                <th class="label">Bucket</th>
                <th class="label num">Mean return</th>
                <th class="label num">Sharpe</th>
                <th class="label num">Turnover</th>
                <th class="label num">Cost</th>
                <th class="label num">Net</th>
                <th class="label num">Names</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in quantiles" :key="`qt-${r.quantile}`">
                <td class="fig">{{ qLabel(r.quantile) }}</td>
                <td class="fig num" :class="toneFor(r.mean_return)">{{ pctFrac(r.mean_return, 3) }}</td>
                <td class="fig num">{{ num(r.sharpe, 2) }}</td>
                <td class="fig num dim">{{ pctFrac(turnoverOf.get(r.quantile), 1) }}</td>
                <td class="fig num dim">{{ pctFrac(costOf(r.quantile), 3) }}</td>
                <td
                  class="fig num"
                  :class="clears(r.quantile, r.mean_return) ? 'pos' : 'neg'"
                >
                  {{
                    r.mean_return != null && costOf(r.quantile) != null
                      ? pctFrac(r.mean_return - (costOf(r.quantile) as number), 3)
                      : DASH
                  }}
                </td>
                <td class="fig num dim">{{ num(r.mean_count, 0) }}</td>
              </tr>
              <tr v-if="spreadRow" class="spread-row">
                <td class="fig">Spread</td>
                <td class="fig num" :class="toneFor(spreadRow.mean_return)">
                  {{ pctFrac(spreadRow.mean_return, 3) }}
                </td>
                <td class="fig num">{{ num(spreadRow.sharpe, 2) }}</td>
                <td class="fig num dim" colspan="4">top minus bottom, gross</td>
              </tr>
            </tbody>
          </table>
        </template>
      </Panel>
    </template>
  </div>
</template>

<style scoped>
.research {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.w-full { width: 100%; min-width: 0; }

/* ---- chart tab strip ----------------------------------------------------- */
.chart-tabs {
  display: flex;
  margin: calc(-1 * var(--s4)) calc(-1 * var(--s4)) var(--s4);
  border-bottom: var(--hair) solid var(--rule);
}
.ctab {
  padding: 5px 14px;
  border: none;
  border-right: var(--hair) solid var(--rule);
  background: transparent;
  color: var(--ink-dim);
  cursor: pointer;
  font-weight: 700;
  letter-spacing: 0.06em;
  font-size: var(--t-micro);
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.ctab:hover { color: var(--ink); background: var(--panel-hi); }
.ctab.on {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border-bottom: 2px solid var(--phosphor);
}

.banner {
  display: flex;
  align-items: flex-start;
  gap: var(--s3);
  margin-bottom: var(--s3);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.pill {
  flex: 0 0 auto;
  font-family: var(--font-display);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  font-weight: 700;
  color: var(--phosphor);
}
.banner-text {
  font-size: var(--t-small);
  line-height: 1.4;
  color: var(--ink-soft);
}
.banner-text code {
  font-family: var(--font-data);
  color: var(--ink);
}

.counts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s3);
}

.dims {
  margin-top: var(--s3);
  font-size: var(--t-tiny);
  color: var(--ink-faint);
  font-family: var(--font-data);
}

/* ---- charts -------------------------------------------------------------- */
.chart {
  display: block;
  width: 100%;
  height: 220px;
}
.qchart { height: 240px; }

.gridline {
  stroke: var(--grid);
  stroke-width: 1;
}
.zero {
  stroke: var(--rule-hi);
  stroke-width: 1;
}
.tick-label {
  font-family: var(--font-data);
  font-size: 9px;
  fill: var(--ink-faint);
}

.ic-line {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
}
.ic-dot.sig { fill: var(--phosphor); }
/* An insignificant point is drawn hollow rather than in a different hue —
   significance is a confidence statement, not a second data series. */
.ic-dot.weak {
  fill: var(--panel);
  stroke: var(--ink-faint);
  stroke-width: 1.5;
}

.qbar.up { fill: var(--long); }
.qbar.down { fill: var(--short); }
.costline {
  stroke: var(--warn);
  stroke-width: 1.5;
  stroke-dasharray: 3 2;
}

.qwrap { padding-top: var(--s2); }
.qaxis {
  display: flex;
  margin-top: var(--s1);
}
.qlab {
  flex: 1 1 0;
  text-align: center;
  color: var(--ink-faint);
}

.legend {
  display: flex;
  gap: var(--s5);
  margin-top: var(--s3);
  font-size: var(--t-tiny);
  color: var(--ink-dim);
}
.key { display: flex; align-items: center; gap: var(--s2); }
.sw {
  width: 12px;
  height: 3px;
  display: inline-block;
}
.sw.up { background: var(--long); }
.sw.cost { background: var(--warn); }

/* ---- tables -------------------------------------------------------------- */
.ic-table { margin-top: var(--s4); }
.faded td { color: var(--ink-faint); }
.spread-row td {
  border-top: var(--hair) solid var(--rule-hi);
  font-weight: 600;
}
.dim { color: var(--ink-faint); }
.pos { color: var(--long); }
.neg { color: var(--short); }

.empty { padding-top: var(--s2); }
.cmds {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  margin-top: var(--s3);
}
.cmds li {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s3);
  align-items: baseline;
}
.cmds code {
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  padding: 2px var(--s1);
  background: var(--panel-raise);
  color: var(--ink-soft);
}

.note { font-size: var(--t-small); color: var(--ink-dim); }
.err { font-size: var(--t-small); color: var(--short); }

@media (max-width: 960px) {
  .counts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .legend { flex-direction: column; gap: var(--s2); }
}
</style>
