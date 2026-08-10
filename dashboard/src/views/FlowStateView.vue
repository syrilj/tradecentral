<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type FlowStatePayload, type FlowStateRow, type BarrierFieldNode } from '@/api'
import { useResource } from '@/composables/useResource'
import { useChartSize } from '@/composables/useChartSize'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import LoadingState from '@/components/LoadingState.vue'
import HelpTip from '@/components/HelpTip.vue'
import { num, pctFrac, signed, age, DASH } from '@/format'
import { linearScale, niceTicks, niceDomain, linePath, bandPath } from '@/charts'

/* ---------------------------------------------------------------- resource */

const fs = useResource(() => api.flowState(), { intervalMs: 300_000 })
const data = computed<FlowStatePayload | null>(() => fs.data.value)
const available = computed(() => data.value?.available === true)

/* ------------------------------------------------------------- state chips */

const STATE_ORDER = ['NORMAL', 'PRESSURE', 'SHOCK', 'TEST', 'CASCADE', 'ABSORB', 'EXHAUSTION', 'FADE'] as const

/** CASCADE/SHOCK read as the --short family (breakdown risk), ABSORB/FADE as
 * --long (the flow being absorbed / reverting), NORMAL dim/muted, and the
 * remaining transitional states get their own quiet, non-signed colour so
 * they don't borrow the "bullish/bearish" read of long/short. */
function stateColorVar(state: string): string {
  switch (state) {
    case 'CASCADE':
    case 'SHOCK':
      return 'var(--short)'
    case 'ABSORB':
    case 'FADE':
      return 'var(--long)'
    case 'TEST':
      return 'var(--call)'
    case 'PRESSURE':
      return 'var(--warn)'
    case 'EXHAUSTION':
      return 'var(--put)'
    default:
      return 'var(--ink-faint)' // NORMAL
  }
}

/* ------------------------------------------------------------ header strip */

const tierLabel = computed(() => {
  const t = data.value?.tier ?? 0
  if (t >= 2) return 'T2 PAPER'
  if (t === 1) return 'T1 VALIDATED'
  return 'T0 RESEARCH'
})

const staleDays = computed<number | null>(() => {
  const asOf = data.value?.as_of
  if (!asOf) return null
  const t = new Date(`${asOf}T00:00:00Z`).getTime()
  if (Number.isNaN(t)) return null
  return Math.floor((Date.now() - t) / 86_400_000)
})
/** ">2 sessions" approximated as calendar days since as_of — this artifact
 * has no trading-calendar dependency wired in, and a rough day count is
 * enough to flag "this hasn't been rebuilt in a while". */
const isStale = computed(() => (staleDays.value ?? 0) > 2)

/* --------------------------------------------------------------- validation */

const phenomenon = computed(() => data.value?.phenomenon ?? null)
const gate = computed(() => data.value?.gate ?? null)

const GATE_CHECK_LABELS = [
  'OOS paired bootstrap vs baseline > 0',
  'expectancy CI excludes 0',
  'deflated Sharpe > 0',
  'ECE <= 0.05',
] as const

const ciHostRef = ref<HTMLElement | null>(null)
const { W: ciW, H: ciH } = useChartSize(ciHostRef, { minH: 64, fallbackH: 64, minW: 200 })

const ciChart = computed(() => {
  const p = phenomenon.value
  if (!p || !p.tested || !p.boot_ci) return null
  const [lo, hi] = p.boot_ci
  if (lo == null || hi == null) return null
  const effect = p.effect ?? 0
  const span = Math.max(Math.abs(lo), Math.abs(hi), Math.abs(effect), 1e-6) * 1.3
  const domain: [number, number] = [-span, span]
  const pad = 28
  const scale = linearScale(domain, [pad, Math.max(pad + 1, ciW.value - pad)])
  const midY = ciH.value / 2
  const ticks = niceTicks(domain[0], domain[1], 4).map((t) => ({ x: scale(t), label: pctFrac(t, 1) }))
  return {
    zeroX: scale(0),
    loX: scale(lo),
    hiX: scale(hi),
    effectX: scale(effect),
    excludesZero: lo > 0 || hi < 0,
    midY,
    ticks,
  }
})

/* ------------------------------------------------------------- state board */

type SortKey =
  | 'symbol' | 'current_state' | 'days_in_state' | 'flow_z' | 'persistence_5d'
  | 'amihud_z' | 'cs_spread' | 'continuation_score' | 'barrier_proximity'
  | 'impact_beta_z' | 'air_pocket_up' | 'air_pocket_down' | 'stress_rank'

const sortKey = ref<SortKey>('continuation_score')
const sortDir = ref<'asc' | 'desc'>('desc')

function setSort(key: SortKey): void {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = key === 'symbol' || key === 'current_state' ? 'asc' : 'desc'
  }
}

function sortArrow(key: SortKey): string {
  if (sortKey.value !== key) return ''
  return sortDir.value === 'asc' ? '▴' : '▾'
}

function sortValue(row: FlowStateRow, key: SortKey): number | string {
  const v = (row as unknown as Record<string, unknown>)[key]
  if (typeof v === 'string') return v
  if (typeof v === 'number' && Number.isFinite(v)) return v
  return -Infinity
}

function dirLabel(direction: number | null | undefined): string {
  if (direction == null || direction === 0) return '·'
  return direction > 0 ? '↑ PRESS' : '↓ PRESS'
}

function dirTone(direction: number | null | undefined): string {
  if (direction == null || direction === 0) return 'flat'
  return direction > 0 ? 'pos' : 'neg'
}

const sortedStates = computed<FlowStateRow[]>(() => {
  const rows = [...(data.value?.states ?? [])]
  const dir = sortDir.value === 'asc' ? 1 : -1
  const key = sortKey.value
  rows.sort((a, b) => {
    const av = sortValue(a, key)
    const bv = sortValue(b, key)
    const aMissing = av === -Infinity
    const bMissing = bv === -Infinity
    // Unknown measurements always stay at the bottom. Sorting ascending must
    // not make an unmeasured value look like the strongest observation.
    if (aMissing !== bMissing) return aMissing ? 1 : -1
    if (aMissing && bMissing) return a.symbol.localeCompare(b.symbol)
    if (typeof av === 'string' || typeof bv === 'string') {
      return dir * String(av).localeCompare(String(bv))
    }
    return dir * (av - bv)
  })
  return rows
})

/* --------------------------------------------------------- symbol selection
   (drives both the timeline strip and the barrier-field chart) */

const selectedSymbol = ref<string | null>(null)

const detailSymbols = computed(() => [...new Set([
  ...(data.value?.states ?? []).map((row) => row.symbol),
  ...Object.keys(data.value?.timelines ?? {}),
  ...Object.keys(data.value?.barrier_fields ?? {}),
])].sort())

const effectiveSymbol = computed<string | null>(() => {
  if (selectedSymbol.value && detailSymbols.value.includes(selectedSymbol.value)) return selectedSymbol.value
  return sortedStates.value[0]?.symbol ?? detailSymbols.value[0] ?? null
})

function selectSymbol(sym: string): void {
  selectedSymbol.value = sym
}

const timeline = computed(() => (effectiveSymbol.value ? data.value?.timelines[effectiveSymbol.value] ?? [] : []))

const barrierField = computed(() => (effectiveSymbol.value ? data.value?.barrier_fields[effectiveSymbol.value] ?? null : null))

/* ----------------------------------------------------------- timeline strip */

const timelineTotalDays = computed(() => timeline.value.length)

/* -------------------------------------------------------- barrier field chart */

const barrierHostRef = ref<HTMLElement | null>(null)
const { W: barW, H: barH } = useChartSize(barrierHostRef, { minH: 280, fallbackH: 320, minW: 200 })

interface BarrierChartGeom {
  priceScale: (v: number) => number
  densityScale: (v: number) => number
  bars: { y: number; x0: number; x1: number }[]
  priceTicks: { y: number; label: string }[]
  priceLineY: number | null
  nodeMarks: (BarrierFieldNode & { y: number })[]
  strikeMarks: number[]
}

const barrierChart = computed<BarrierChartGeom | null>(() => {
  const bf = barrierField.value
  if (!bf || !bf.grid.length || !bf.density.length) return null
  const padTop = 12
  const padBottom = 22
  const padLeft = 56
  const padRight = 12
  const priceDomain = niceDomain(Math.min(...bf.grid), Math.max(...bf.grid), 0.02)
  const priceScale = linearScale(priceDomain, [barH.value - padBottom, padTop])
  const maxDensity = Math.max(...bf.density, 1e-9)
  const densityScale = linearScale([0, maxDensity], [padLeft, Math.max(padLeft + 1, barW.value - padRight)])

  const bars = bf.grid.map((price, i) => ({
    y: priceScale(price),
    x0: padLeft,
    x1: densityScale(bf.density[i]),
  }))

  const priceTicks = niceTicks(priceDomain[0], priceDomain[1], 6).map((p) => ({
    y: priceScale(p),
    label: num(p, p >= 100 ? 0 : 2),
  }))

  const priceLineY = bf.price != null ? priceScale(bf.price) : null

  const nodeMarks = (bf.nodes ?? [])
    .filter((n) => n.price != null)
    .map((n) => ({ ...n, y: priceScale(n.price as number) }))

  const strikeMarks = (bf.strikes_overlay ?? []).map((s) => priceScale(s))

  return { priceScale, densityScale, bars, priceTicks, priceLineY, nodeMarks, strikeMarks }
})

/* --------------------------------------------------------------- events */

type OutcomeFilter = 'ALL' | 'DOWN_FIRST' | 'UP_FIRST' | 'NEITHER' | 'AMBIGUOUS' | 'MISSING'
const outcomeFilter = ref<OutcomeFilter>('ALL')

const filteredEvents = computed(() => {
  const evs = data.value?.events ?? []
  if (outcomeFilter.value === 'ALL') return evs
  if (outcomeFilter.value === 'MISSING') return evs.filter((e) => e.outcome == null)
  return evs.filter((e) => e.outcome === outcomeFilter.value)
})

const eventLimit = ref(100)
const visibleEvents = computed(() => filteredEvents.value.slice(0, eventLimit.value))

watch(outcomeFilter, () => {
  eventLimit.value = 100
})

function outcomeTone(outcome: string | null): string {
  if (outcome === 'DOWN_FIRST') return 'neg'
  if (outcome === 'UP_FIRST') return 'pos'
  return 'flat'
}

/* --------------------------------------------------------- impact response */

const impactHostRef = ref<HTMLElement | null>(null)
const { W: impW, H: impH } = useChartSize(impactHostRef, { minH: 200, fallbackH: 220, minW: 200 })

const impactChart = computed(() => {
  const curve = data.value?.impact_curve
  if (!curve || !curve.lags.length) return null
  const padTop = 14
  const padBottom = 24
  const padLeft = 44
  const padRight = 14

  const lagDomain: [number, number] = [Math.min(...curve.lags), Math.max(...curve.lags)]
  const xScale = linearScale(lagDomain, [padLeft, Math.max(padLeft + 1, impW.value - padRight)])

  const values = [...curve.mean_cum_ret, ...curve.ci_lo, ...curve.ci_hi].filter(
    (v): v is number => v != null && Number.isFinite(v),
  )
  if (!values.length) return null
  const yDomain = niceDomain(Math.min(...values, 0), Math.max(...values, 0), 0.15)
  const yScale = linearScale(yDomain, [impH.value - padBottom, padTop])

  const meanPts: { x: number; y: number }[] = []
  const upperPts: { x: number; y: number }[] = []
  const lowerPts: { x: number; y: number }[] = []
  curve.lags.forEach((lag, i) => {
    const m = curve.mean_cum_ret[i]
    const lo = curve.ci_lo[i]
    const hi = curve.ci_hi[i]
    if (m != null) meanPts.push({ x: xScale(lag), y: yScale(m) })
    if (lo != null && hi != null) {
      upperPts.push({ x: xScale(lag), y: yScale(hi) })
      lowerPts.push({ x: xScale(lag), y: yScale(lo) })
    }
  })

  const zeroY = yScale(0)
  const yTicks = niceTicks(yDomain[0], yDomain[1], 4).map((t) => ({ y: yScale(t), label: pctFrac(t, 1) }))

  return {
    linePath: linePath(meanPts),
    bandPath: bandPath(upperPts, lowerPts),
    zeroY,
    yTicks,
    xTicks: curve.lags.map((lag) => ({ x: xScale(lag), label: String(lag) })),
  }
})

/* ---------------------------------------------------------------- caveats */

const staleReason = computed(() =>
  isStale.value ? `Artifact is ${staleDays.value}d old — rebuild with tools/build_flow_state.py.` : null,
)
</script>

<template>
  <div class="flowstate-view">
    <!-- 1. Header strip -->
    <Panel label="Barrier Sleeve · Flow State" index="15" :meta="data?.as_of ? `as of ${data.as_of}` : 'barrier-conditioned continuation monitor'" class="w-full" :live="!fs.error.value">
      <template #action>
        <button
          type="button"
          class="refresh-btn label"
          :disabled="fs.loading.value"
          title="Reload flow-state artifact"
          @click="fs.refresh({ clear: false })"
        >
          <span class="refresh-icon" :class="{ spinning: fs.loading.value }">↻</span>
          {{ fs.loading.value ? 'RELOADING…' : 'REFRESH' }}
        </button>
      </template>

      <LoadingState v-if="fs.loading.value && !data" label="loading flow-state artifact" />
      <p v-else-if="fs.error.value && !data" class="state err label">{{ fs.error.value }}</p>

      <template v-else-if="available">
        <p v-if="fs.error.value" class="state err stale-artifact label">
          Refresh failed: {{ fs.error.value }} · showing the last successful artifact.
        </p>
        <div class="banner label">
          <span>
            Evidence-backed sleeve: abnormal flow × elevated impact × barrier proximity → continuation candidate.
            Cascade/fade are research-only; this is not a bottom predictor.
          </span>
          <HelpTip
            label="Continuation score"
            text="S = |flow_z| × max(impact_beta_z, 0) × persistence × exp(−d_barrier/τ). Built from daily-bar proxies (no true OFI/L2). Rank and inspect — never a trade authorization. Bottoms require ABSORB/FADE evidence that has not cleared sample size yet."
          />
        </div>

        <div class="readout-grid">
          <Readout label="Tier" :value="tierLabel" :sub="data?.tier ? 'validated vs matched controls' : 'states + events only'" :tone="data?.tier ? 'accent' : 'flat'" />
          <Readout
            label="Decision authorized"
            :value="data?.decision_authorized ? 'YES' : 'NO'"
            sub="never true below tier 2"
            :tone="data?.decision_authorized ? 'pos' : 'flat'"
          />
          <Readout label="As of" :value="data?.as_of ?? DASH" :sub="isStale ? `${staleDays}d old — stale` : 'current'" :tone="isStale ? 'neg' : 'flat'" />
          <Readout label="Symbols" :value="num(sortedStates.length, 0)" sub="in this run" />
        </div>
        <p v-if="staleReason" class="stale-note label">{{ staleReason }}</p>
      </template>

      <div v-else class="empty-state">
        <p class="state label">No flow-state artifact yet{{ data?.reason ? ` — ${data.reason}` : '' }}.</p>
        <ul class="cmds">
          <li>
            <code>PYTHONPATH=&lt;repo&gt; python3 edge/tools/build_flow_state.py</code>
            <span class="dim">writes runs/flow_state/</span>
          </li>
        </ul>
        <p class="subnote label">producing_script: {{ data?.producing_script ?? 'tools/build_flow_state.py' }}</p>
      </div>
    </Panel>

    <template v-if="available">
      <!-- 2. Validation / phenomenon panel -->
      <Panel label="Validation — matched-control phenomenon" index="—" meta="Phase 2 statistical test, not ML" :delay="30">
        <template v-if="phenomenon?.tested">
          <div class="readout-grid">
            <Readout label="Effect (Δ terminal return)" :value="signed(phenomenon.effect != null ? phenomenon.effect * 100 : null, 2) + '%'" :tone="(phenomenon.effect ?? 0) > 0 ? 'pos' : (phenomenon.effect ?? 0) < 0 ? 'neg' : 'flat'" />
            <Readout label="Newey-West t" :value="num(phenomenon.nw_t, 2)" />
            <Readout label="Permutation p (deflated)" :value="num(phenomenon.perm_p, 4)" :tone="(phenomenon.perm_p ?? 1) < 0.01 ? 'pos' : 'flat'" />
            <Readout label="n events / controls" :value="`${num(phenomenon.n_events, 0)} / ${num(phenomenon.n_controls, 0)}`" />
            <Readout label="Prereg id" :value="phenomenon.prereg_id ?? DASH" size="sm" />
            <Readout label="T1 result" :value="phenomenon.passed ? 'PASS' : 'FAIL'" :tone="phenomenon.passed ? 'pos' : 'neg'" sub="CI excludes 0 AND deflated p < 0.01" />
          </div>

          <div v-if="ciChart" ref="ciHostRef" class="ci-chart-host">
            <svg :width="ciW" :height="ciH" class="ci-svg">
              <line :x1="0" :x2="ciW" :y1="ciChart.midY" :y2="ciChart.midY" class="ci-axis" />
              <line :x1="ciChart.zeroX" :x2="ciChart.zeroX" :y1="6" :y2="ciH - 6" class="ci-zero" />
              <line :x1="ciChart.loX" :x2="ciChart.hiX" :y1="ciChart.midY" :y2="ciChart.midY" class="ci-whisker" :class="{ excludes: ciChart.excludesZero }" />
              <line :x1="ciChart.loX" :x2="ciChart.loX" :y1="ciChart.midY - 7" :y2="ciChart.midY + 7" class="ci-cap" />
              <line :x1="ciChart.hiX" :x2="ciChart.hiX" :y1="ciChart.midY - 7" :y2="ciChart.midY + 7" class="ci-cap" />
              <circle :cx="ciChart.effectX" :cy="ciChart.midY" r="4" class="ci-effect" />
              <g v-for="t in ciChart.ticks" :key="t.x">
                <text :x="t.x" :y="ciH - 4" class="ci-tick label">{{ t.label }}</text>
              </g>
            </svg>
          </div>
          <p class="chart-caption label">Bootstrap CI whisker for Δ terminal return, event vs matched controls (date-block bootstrap, 95%). Descriptive of the study result — not a forecast.</p>
        </template>
        <div v-else class="empty-state">
          <p class="state label">Study not yet run.</p>
          <ul class="cmds">
            <li>
              <code>PYTHONPATH=&lt;repo&gt; python3 edge/tools/build_flow_state_study.py</code>
              <span class="dim">writes runs/flow_state/study_*.json</span>
            </li>
          </ul>
        </div>

        <div class="gate-block">
          <p class="gate-title label">Development gate (Phase 3)</p>
          <p v-if="!gate?.evaluated" class="gate-pending label">
            Not yet evaluated — Phase 3 (cascade/fade models) does not exist yet. Expected checks once it does:
          </p>
          <ul class="checks">
            <li v-for="label in GATE_CHECK_LABELS" :key="label" class="check pending">
              <span class="c-mark" aria-hidden="true">○</span>
              <span class="c-k label">{{ label }}</span>
            </li>
          </ul>
          <p v-if="gate?.ledger_id" class="dim label">ledger: {{ gate.ledger_id }}</p>
        </div>
      </Panel>

      <!-- 3. State board -->
      <Panel label="Barrier sleeve board" index="—" :meta="`${sortedStates.length} symbols · ranked by continuation_score`" flush :delay="50">
        <div class="table-scroll">
          <table class="grid">
            <thead>
              <tr>
                <th class="sortable" @click="setSort('symbol')">Symbol {{ sortArrow('symbol') }}</th>
                <th class="sortable" @click="setSort('current_state')">State {{ sortArrow('current_state') }}</th>
                <th class="num sortable" @click="setSort('continuation_score')">
                  Cont. S {{ sortArrow('continuation_score') }}
                  <HelpTip label="Continuation score" text="|flow_z| × max(impact_beta_z,0) × persistence × barrier proximity. High S means persistent abnormal pressure with elevated impact near a structural barrier — the continuation candidate, not a fade/bottom signal." />
                </th>
                <th class="label">Dir</th>
                <th class="num sortable" @click="setSort('flow_z')">Flow z {{ sortArrow('flow_z') }}</th>
                <th class="num sortable" @click="setSort('impact_beta_z')">Impact z {{ sortArrow('impact_beta_z') }}</th>
                <th class="num sortable" @click="setSort('persistence_5d')">Persist 5d {{ sortArrow('persistence_5d') }}</th>
                <th class="num sortable" @click="setSort('barrier_proximity')">Near barrier {{ sortArrow('barrier_proximity') }}</th>
                <th class="num sortable" @click="setSort('amihud_z')">Amihud z {{ sortArrow('amihud_z') }}</th>
                <th class="num">Support</th>
                <th class="num">Resistance</th>
                <th class="num sortable" @click="setSort('stress_rank')">
                  Rank {{ sortArrow('stress_rank') }}
                  <HelpTip label="Stress rank" text="Ordinal rank across the symbols in this run (1 = highest continuation_score) — never a probability or expected value." />
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in sortedStates"
                :key="row.symbol"
                :class="{ active: row.symbol === effectiveSymbol }"
                tabindex="0"
                role="button"
                :aria-label="`Inspect ${row.symbol} barrier detail`"
                @click="selectSymbol(row.symbol)"
                @keydown.enter="selectSymbol(row.symbol)"
                @keydown.space.prevent="selectSymbol(row.symbol)"
              >
                <td class="fig sym">{{ row.symbol }}</td>
                <td>
                  <span class="state-chip label" :style="{ color: stateColorVar(row.current_state), borderColor: stateColorVar(row.current_state) }">
                    {{ row.current_state }}
                  </span>
                </td>
                <td class="fig num">{{ num(row.continuation_score ?? null, 3) }}</td>
                <td>
                  <span class="dir-chip label" :class="dirTone(row.continuation_direction)">
                    {{ dirLabel(row.continuation_direction) }}
                  </span>
                </td>
                <td class="fig num">{{ num(row.flow_z, 2) }}</td>
                <td class="fig num">{{ num(row.impact_beta_z ?? null, 2) }}</td>
                <td class="fig num">{{ num(row.persistence_5d, 0) }}</td>
                <td class="fig num">{{ num(row.barrier_proximity ?? null, 2) }}</td>
                <td class="fig num">{{ num(row.amihud_z, 2) }}</td>
                <td class="fig num dim">{{ row.next_support != null ? num(row.next_support, 2) : DASH }}</td>
                <td class="fig num dim">{{ row.next_resistance != null ? num(row.next_resistance, 2) : DASH }}</td>
                <td class="fig num">{{ row.stress_rank }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <!-- 4. State timeline strip -->
      <Panel :label="effectiveSymbol ? `State timeline — ${effectiveSymbol}` : 'State timeline'" index="—" :meta="`${timelineTotalDays} sessions`" :delay="70">
        <div class="symbol-picker">
          <label class="label" for="fs-symbol-select">Symbol</label>
          <select id="fs-symbol-select" class="symbol-select" :value="effectiveSymbol ?? ''" @change="selectSymbol(($event.target as HTMLSelectElement).value)">
            <option v-for="sym in detailSymbols" :key="sym" :value="sym">{{ sym }}</option>
          </select>
        </div>

        <div v-if="timeline.length" class="timeline-strip">
          <span
            v-for="(pt, i) in timeline"
            :key="`${pt.date}-${i}`"
            class="timeline-cell"
            :style="{ background: stateColorVar(pt.state) }"
            :title="`${pt.date}: ${pt.state}`"
          />
        </div>
        <p v-else class="state label dim">No timeline available for this symbol (timelines are kept for the top-N symbols by stress_rank).</p>

        <div class="legend">
          <span v-for="s in STATE_ORDER" :key="s" class="legend-item label">
            <i class="legend-swatch" :style="{ background: stateColorVar(s) }" />{{ s }}
          </span>
        </div>
      </Panel>

      <!-- 5. Barrier-field chart -->
      <Panel :label="effectiveSymbol ? `Barrier field — ${effectiveSymbol}` : 'Barrier field'" index="—" meta="B(p) density profile" :delay="90">
        <template v-if="barrierChart">
          <div ref="barrierHostRef" class="barrier-chart-host">
            <svg :width="barW" :height="barH" class="barrier-svg">
              <g v-for="t in barrierChart.priceTicks" :key="t.y">
                <line :x1="52" :x2="barW" :y1="t.y" :y2="t.y" class="barrier-gridline" />
                <text :x="0" :y="t.y + 3" class="barrier-tick label">{{ t.label }}</text>
              </g>
              <rect
                v-for="(b, i) in barrierChart.bars"
                :key="i"
                :x="b.x0"
                :y="b.y - 1"
                :width="Math.max(0, b.x1 - b.x0)"
                height="2"
                class="barrier-bar"
              />
              <line v-if="barrierChart.priceLineY != null" :x1="52" :x2="barW" :y1="barrierChart.priceLineY" :y2="barrierChart.priceLineY" class="barrier-price-line" />
              <circle v-for="(n, i) in barrierChart.nodeMarks" :key="i" :cx="barrierChart.densityScale((n.mass ?? 0))" :cy="n.y" r="3" class="barrier-node" />
              <line v-for="(y, i) in barrierChart.strikeMarks" :key="`strike-${i}`" :x1="52" :x2="barW" :y1="y" :y2="y" class="barrier-strike" />
            </svg>
          </div>
          <p class="chart-caption label">
            Horizontal profile is B(p) mass by price level; the phosphor line marks the last close, dots mark local-maxima nodes.
            <template v-if="barrierField?.strikes_overlay">Amber ticks: today's option chain strikes only.</template>
          </p>
        </template>
        <p v-else class="state label dim">No barrier field kept for this symbol (top-N by stress_rank only, to keep payload size sane).</p>
      </Panel>

      <!-- 6. Event table -->
      <Panel label="Events" index="—" :meta="`${visibleEvents.length}/${filteredEvents.length} filtered · ${data?.events.length ?? 0} total`" flush :delay="110">
        <template #action>
          <select v-model="outcomeFilter" class="outcome-filter">
            <option value="ALL">All outcomes</option>
            <option value="DOWN_FIRST">Down first</option>
            <option value="UP_FIRST">Up first</option>
            <option value="NEITHER">Neither</option>
            <option value="AMBIGUOUS">Ambiguous</option>
            <option value="MISSING">Missing</option>
          </select>
        </template>
        <div class="table-scroll">
          <table class="grid">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>t0</th>
                <th class="num">Dir</th>
                <th>State path</th>
                <th>Outcome</th>
                <th class="num">TTH (d)</th>
                <th class="num">MFE</th>
                <th class="num">MAE</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(e, i) in visibleEvents" :key="`${e.symbol}-${e.t0}-${i}`">
                <td class="fig sym">{{ e.symbol }}</td>
                <td class="fig">{{ e.t0 }}</td>
                <td class="fig num" :class="e.direction > 0 ? 'pos' : e.direction < 0 ? 'neg' : ''">{{ e.direction > 0 ? '+1' : e.direction < 0 ? '-1' : '0' }}</td>
                <td class="path-cell">
                  <span v-for="(s, j) in e.state_path.slice(0, 8)" :key="j" class="path-dot" :style="{ background: stateColorVar(s) }" :title="s" />
                  <span v-if="e.state_path.length > 8" class="dim label">+{{ e.state_path.length - 8 }}</span>
                </td>
                <td :class="outcomeTone(e.outcome)">{{ e.outcome ?? 'MISSING' }}</td>
                <td class="fig num">{{ e.time_to_hit != null ? num(e.time_to_hit, 0) : DASH }}</td>
                <td class="fig num">{{ e.mfe != null ? num(e.mfe * 100, 2) + '%' : DASH }}</td>
                <td class="fig num">{{ e.mae != null ? num(e.mae * 100, 2) + '%' : DASH }}</td>
              </tr>
              <tr v-if="!filteredEvents.length">
                <td colspan="8" class="state label dim">No events match this filter.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="visibleEvents.length < filteredEvents.length" class="event-more">
          <button type="button" class="refresh-btn label" @click="eventLimit += 100">
            SHOW NEXT {{ Math.min(100, filteredEvents.length - visibleEvents.length) }} EVENTS
          </button>
        </div>
      </Panel>

      <!-- 7. Impact response panel -->
      <Panel label="Impact response" index="—" meta="event-study, pooled across symbols" :delay="130">
        <template v-if="impactChart">
          <div ref="impactHostRef" class="impact-chart-host">
            <svg :width="impW" :height="impH" class="impact-svg">
              <g v-for="t in impactChart.yTicks" :key="t.y">
                <line :x1="44" :x2="impW" :y1="t.y" :y2="t.y" class="barrier-gridline" />
                <text :x="0" :y="t.y + 3" class="barrier-tick label">{{ t.label }}</text>
              </g>
              <line :x1="44" :x2="impW" :y1="impactChart.zeroY" :y2="impactChart.zeroY" class="impact-zero" />
              <path :d="impactChart.bandPath" class="impact-band" />
              <path :d="impactChart.linePath" class="impact-line" />
              <g v-for="t in impactChart.xTicks" :key="t.x">
                <text :x="t.x" :y="impH - 6" class="barrier-tick label">{{ t.label }}</text>
              </g>
            </svg>
          </div>
        </template>
        <p v-else class="state label dim">No impact-curve samples in this run.</p>
        <p class="chart-caption label">Mean cumulative return at lags 1–10 sessions after a SHOCK, with a normal-approximation 95% band, pooled sample-size-weighted across symbols. Descriptive event-study curve — not a causal impact estimate.</p>
      </Panel>

      <!-- 8. Model / EV panel — permanently locked while tier < 2 -->
      <Panel label="Model / EV" index="—" meta="locked" :delay="150">
        <div class="locked-panel">
          <span class="lock-glyph" aria-hidden="true">🔒</span>
          <p class="state label">Unlocks when the development gate passes (see the Validation panel above).</p>
          <p class="subnote label">P(Cascade), P(Fade|Cascade), calibration, ablation, and per-event EV all require Phase-3 models, which do not exist yet — models is always null at tier &lt; 2.</p>
        </div>
      </Panel>

      <!-- caveats -->
      <Panel label="Caveats" index="—" :delay="170">
        <ul class="caveats-list">
          <li v-for="(c, i) in data?.caveats ?? []" :key="i" class="label">{{ c }}</li>
        </ul>
        <p class="subnote label">producing_script: {{ data?.producing_script }} · last refreshed {{ age(fs.fetchedAt.value) }} ago</p>
      </Panel>
    </template>
  </div>
</template>

<style scoped>
.flowstate-view {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  width: 100%;
  max-width: none;
  min-width: 0;
}

.w-full { width: 100%; min-width: 0; }

.banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s3);
  color: var(--ink-soft);
  font-size: var(--t-small);
  border-bottom: var(--hair) solid var(--rule);
  background: var(--void-lift);
}

.readout-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--s3);
  padding: var(--s3);
}

.stale-note {
  padding: 0 var(--s3) var(--s3);
  color: var(--warn);
}

.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  height: 28px;
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-micro);
  letter-spacing: 0.05em;
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
  cursor: pointer;
}
.refresh-btn:hover:not(:disabled) { background: var(--phosphor); color: var(--void); }
.refresh-btn:disabled { opacity: 0.6; cursor: wait; }
.refresh-icon { display: inline-block; font-size: 0.9rem; line-height: 1; }
.refresh-icon.spinning { animation: spin 0.8s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

.empty-state {
  padding: var(--s5) var(--s4);
}
.cmds { list-style: none; margin: var(--s2) 0 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.cmds code {
  display: inline-block;
  padding: 3px 8px;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-hi);
  color: var(--phosphor);
  font-family: var(--font-data);
  font-size: var(--t-tiny);
}
.cmds .dim { margin-left: var(--s2); color: var(--ink-faint); font-size: var(--t-micro); }
.subnote { margin-top: var(--s2); color: var(--ink-ghost); font-size: var(--t-small); }

.state.err { color: var(--short); padding: var(--s4); }
.state.err.stale-artifact { border-bottom: var(--hair) solid var(--rule); background: color-mix(in srgb, var(--short) 7%, var(--void-lift)); }

/* ---- validation panel ---- */
.ci-chart-host { width: 100%; height: 64px; }
.ci-svg { display: block; width: 100%; height: 100%; }
.ci-axis { stroke: var(--rule); stroke-width: 1; }
.ci-zero { stroke: var(--rule-hi); stroke-width: 1; stroke-dasharray: 3 3; }
.ci-whisker { stroke: var(--ink-dim); stroke-width: 3; }
.ci-whisker.excludes { stroke: var(--phosphor); }
.ci-cap { stroke: var(--ink-dim); stroke-width: 2; }
.ci-effect { fill: var(--ink); }
.ci-tick { fill: var(--ink-faint); font-size: var(--t-micro); text-anchor: middle; }
.chart-caption { padding: var(--s2) var(--s3) 0; color: var(--ink-faint); font-size: var(--t-small); line-height: 1.5; }

.gate-block { padding: var(--s3); border-top: var(--hair) solid var(--rule); margin-top: var(--s2); }
.gate-title { color: var(--ink-dim); margin-bottom: var(--s2); font-weight: 700; }
.gate-pending { color: var(--ink-faint); margin-bottom: var(--s2); }
.checks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.check { display: flex; align-items: center; gap: var(--s2); }
.check .c-mark { color: var(--ink-ghost); width: 14px; text-align: center; }
.check.pending .c-mark { color: var(--ink-ghost); }
.check .c-k { color: var(--ink-dim); }

/* ---- state board ---- */
.table-scroll { max-height: 560px; overflow: auto; }
.state-chip {
  display: inline-block;
  padding: 1px 7px;
  border: var(--hair) solid;
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-micro);
  letter-spacing: 0.04em;
}
.grid tbody tr { cursor: pointer; }
.grid tbody tr:hover { background: var(--panel-hi); }
.grid tbody tr:focus-visible { outline: 1px solid var(--phosphor); outline-offset: -1px; background: var(--phosphor-wash); }
.grid tbody tr.active { background: var(--phosphor-wash); }
.grid th.sortable { cursor: pointer; user-select: none; }
.grid th.sortable:hover { color: var(--ink); }
.pos { color: var(--long); }
.neg { color: var(--short); }
.flat { color: var(--ink-dim); }
.dim { color: var(--ink-faint); }
.dir-chip {
  display: inline-flex;
  align-items: center;
  min-height: 18px;
  padding: 1px 5px;
  border: var(--hair) solid var(--rule-hi);
  font-size: var(--t-micro);
  letter-spacing: 0.04em;
}
.dir-chip.pos { color: var(--long); border-color: color-mix(in srgb, var(--long) 40%, transparent); }
.dir-chip.neg { color: var(--short); border-color: color-mix(in srgb, var(--short) 40%, transparent); }
.dir-chip.flat { color: var(--ink-faint); }

/* ---- timeline ---- */
.symbol-picker { display: flex; align-items: center; gap: var(--s2); padding: var(--s3) var(--s3) 0; }
.symbol-select {
  height: 26px;
  padding: 0 6px;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink);
  font-family: var(--font-data);
  font-size: var(--t-small);
}
.timeline-strip {
  display: flex;
  width: 100%;
  height: 28px;
  margin: var(--s3);
  border: var(--hair) solid var(--rule);
}
.timeline-cell { flex: 1 1 0; min-width: 1px; }
.legend { display: flex; flex-wrap: wrap; gap: var(--s3); padding: 0 var(--s3) var(--s3); }
.legend-item { display: inline-flex; align-items: center; gap: 5px; color: var(--ink-dim); font-size: var(--t-micro); }
.legend-swatch { width: 9px; height: 9px; display: inline-block; }

/* ---- barrier chart ---- */
.barrier-chart-host { width: 100%; height: 320px; }
.barrier-svg { display: block; width: 100%; height: 100%; }
.barrier-gridline { stroke: var(--grid); stroke-width: 1; }
.barrier-tick { fill: var(--ink-faint); font-size: var(--t-micro); dominant-baseline: middle; }
.barrier-bar { fill: var(--phosphor-dim); opacity: 0.7; }
.barrier-price-line { stroke: var(--phosphor); stroke-width: 1.5; }
.barrier-node { fill: var(--ink-soft); }
.barrier-strike { stroke: var(--put); stroke-width: 1; stroke-dasharray: 2 2; }

/* ---- events ---- */
.outcome-filter {
  height: 26px;
  padding: 0 6px;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink);
  font-family: var(--font-data);
  font-size: var(--t-small);
}
.path-cell { display: flex; align-items: center; gap: 2px; }
.path-dot { width: 8px; height: 8px; border-radius: 1px; display: inline-block; }
.event-more { display: flex; justify-content: center; padding: var(--s3); border-top: var(--hair) solid var(--rule); }

/* ---- impact response ---- */
.impact-chart-host { width: 100%; height: 220px; }
.impact-svg { display: block; width: 100%; height: 100%; }
.impact-zero { stroke: var(--rule-hi); stroke-width: 1; stroke-dasharray: 3 3; }
.impact-band { fill: var(--phosphor-glow); stroke: none; }
.impact-line { fill: none; stroke: var(--phosphor); stroke-width: 1.75; }

/* ---- model/EV lock ---- */
.locked-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s2);
  padding: var(--s6) var(--s4);
  text-align: center;
  color: var(--ink-faint);
  opacity: 0.75;
}
.lock-glyph { font-size: 1.75rem; }

/* ---- caveats ---- */
.caveats-list { list-style: none; margin: 0; padding: var(--s3); display: flex; flex-direction: column; gap: 6px; }
.caveats-list li { color: var(--ink-dim); font-size: var(--t-small); line-height: 1.5; }
</style>
