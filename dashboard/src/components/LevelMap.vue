<script setup lang="ts">
/**
 * The level map: one price axis, every lens on it, probabilities attached.
 *
 * WHY IT EXISTS ALONGSIDE THE PIVOT STRIP
 * The page states its levels as a horizontal strip of "CALL WALL $612.00"
 * chips. That layout puts prices in reading order, not in PRICE order, so it
 * hides what an operator needs at a glance: which levels sit above and below,
 * how far, how bunched, and which one price is leaning on. Two levels 0.1%
 * apart and two 4% apart look identical in a pill strip. The strip is kept
 * as a compact readout; this is the chart you actually read a level off.
 *
 * WHY ECHARTS AND NOT HAND-ROLLED SVG
 * The first cut of this chart drew its own axes, scales and label collision
 * pass. Every one of those is a solved problem, and the hand-rolled versions
 * were the parts that read as broken: labels occluding each other in a dense
 * cluster, no zoom, no tooltip, no hit-testing. ECharts (Apache-2.0) supplies
 * axis rendering, `labelLayout.moveOverlap` for occlusion, inside-drag price
 * zoom and item tooltips, so this file is left describing WHAT to draw.
 *
 * Two grids share one price axis:
 *   left  : volume traded at each price, split buy vs sell so the shelf's
 *           composition is visible, not just its size.
 *   right : one rule per merged level with its label and P(touch) bar, plus
 *           spot and the fair-value target as marked lines.
 *
 * Every label carries its own price, so when ECharts shifts one off its rule
 * to avoid an overlap the reading stays unambiguous.
 *
 * Colours are read from the design tokens at runtime rather than written as
 * literals, so this chart follows the theme like every other surface.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { CustomChart, ScatterChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { AbsorptionMatrix } from '@/api'
import type { FairValue, MergedLevel } from '@/levelStructure'
import { num } from '@/format'

echarts.use([
  CustomChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  MarkLineComponent,
  DataZoomComponent,
  CanvasRenderer,
])

const props = withDefaults(
  defineProps<{
    levels: MergedLevel[]
    spot?: number | null
    fairValue?: FairValue | null
    matrix?: AbsorptionMatrix | null
    /** 1-day expected move in dollars, the frame's natural unit. Without it
     *  the zoom presets fall back to fixed percentages of spot. */
    em1dDollars?: number | null
    /** Stated beside every probability. Null hides the probability lane
     *  rather than printing unlabelled numbers. */
    horizonLabel?: string | null
  }>(),
  { spot: null, fairValue: null, matrix: null, em1dDollars: null, horizonLabel: null },
)

/**
 * FRAME: the single thing that decides whether this chart is readable.
 *
 * Fitting every level in view sounds right and is wrong in practice. The
 * order-flow matrix measures a 220-bar window that routinely spans 15% of
 * price, and one swing zone 11% away then compresses the call wall, both
 * expected-move bands, the put wall and spot into the top eighth of the
 * frame, which is exactly the unreadable chart this view replaced.
 *
 * So the default is sized by what is ACTIONABLE, not by what exists: the
 * median level distance, which is robust to the far outliers that cause the
 * problem, floored on the expected-move scale so a quiet tape still gets a
 * sane window. Anything outside is counted, named, and one click away.
 */
type ZoomMode = 'near' | 'auto' | 'wide'
const zoom = ref<ZoomMode>('auto')

const ZOOMS: Array<{ key: ZoomMode; label: string; title: string }> = [
  { key: 'near', label: 'NEAR', title: 'Two expected moves either side of spot' },
  { key: 'auto', label: 'AUTO', title: 'Sized to the levels that cluster around spot' },
  { key: 'wide', label: 'WIDE', title: 'Every measured level and the whole order-flow window' },
]

/** Hard ceiling on any frame, so WIDE on a symbol carrying one stale far-out
 *  strike still renders a price axis rather than a flat line at spot. */
const MAX_HALF_PCT = 0.25

function median(xs: number[]): number {
  if (!xs.length) return 0
  const s = [...xs].sort((a, b) => a - b)
  const m = s.length >> 1
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

const domain = computed<[number, number]>(() => {
  const spot = props.spot
  const prices = props.levels.map((l) => l.price).filter((v) => Number.isFinite(v) && v > 0)

  // Without a spot there is nothing to centre on; fall back to the extent of
  // whatever levels exist rather than inventing a centre.
  if (spot == null || !(spot > 0)) {
    if (!prices.length) return [0, 1]
    const lo = Math.min(...prices)
    const hi = Math.max(...prices)
    return hi > lo ? [lo, hi] : [lo * 0.98, lo * 1.02]
  }

  const em = props.em1dDollars != null && props.em1dDollars > 0 ? props.em1dDollars : null
  const emHalf = em ?? spot * 0.004
  const dists = prices.map((p) => Math.abs(p - spot))

  let half: number
  if (zoom.value === 'near') {
    half = Math.max(2 * emHalf, spot * 0.006)
  } else if (zoom.value === 'wide') {
    const cand = [...dists]
    if (props.fairValue) cand.push(Math.abs(props.fairValue.target - spot))
    if (props.matrix?.available) {
      if (props.matrix.window_low != null) cand.push(Math.abs(props.matrix.window_low - spot))
      if (props.matrix.window_high != null) cand.push(Math.abs(props.matrix.window_high - spot))
    }
    half = cand.length ? Math.max(...cand) : spot * 0.05
  } else {
    // AUTO: the median distance is what makes this robust. A single zone 11%
    // away moves the max but not the median, so it cannot squash the cluster.
    const med = dists.length ? median(dists) : 0
    half = Math.min(Math.max(med * 1.6, 3 * emHalf, spot * 0.008), spot * 0.06)
  }

  half = Math.min(half, spot * MAX_HALF_PCT)
  // The fair-value target is the page's headline; pull it in when it is close
  // enough to belong, but never let it alone open the frame past the cap.
  if (props.fairValue) {
    const d = Math.abs(props.fairValue.target - spot)
    if (d <= spot * MAX_HALF_PCT && d > half && zoom.value !== 'near') half = d * 1.05
  }
  const pad = half * 0.06
  return [spot - half - pad, spot + half + pad]
})

/** Half-frame as a percentage of spot, for the zoom readout and footnote. */
const framePct = computed(() => {
  const spot = props.spot
  if (spot == null || !(spot > 0)) return null
  const [lo, hi] = domain.value
  return ((hi - lo) / 2 / spot) * 100
})

const inFrame = computed(() => {
  const [lo, hi] = domain.value
  return props.levels.filter((l) => l.price >= lo && l.price <= hi)
})

/**
 * Levels the frame excluded, split by side and named.
 *
 * A bare count ("2 not drawn") tells the operator a level exists somewhere
 * and nothing about whether it matters. The nearest one each way is the part
 * that changes a decision, so it is printed.
 */
const offFrame = computed(() => {
  const [lo, hi] = domain.value
  const above = props.levels.filter((l) => l.price > hi).sort((a, b) => a.price - b.price)
  const below = props.levels.filter((l) => l.price < lo).sort((a, b) => b.price - a.price)
  return { count: above.length + below.length, above, below }
})

const hasProb = computed(
  () => props.horizonLabel != null && inFrame.value.some((l) => l.prob != null),
)

const empty = computed(() => !props.levels.length || !(props.spot && props.spot > 0))

/* ---- theme tokens, read from CSS rather than written as literals -------- */
type Tokens = Record<string, string>
const tokens = shallowRef<Tokens>({})

const TOKEN_KEYS = [
  'ink',
  'ink-soft',
  'ink-dim',
  'ink-faint',
  'ink-ghost',
  'rule',
  'rule-faint',
  'panel',
  'panel-hi',
  'phosphor',
  'phosphor-dim',
  'call',
  'call-hi',
  'call-dim',
  'put',
  'put-hi',
  'put-dim',
  'warn',
  'void',
]

function readTokens(el: HTMLElement): Tokens {
  const cs = getComputedStyle(el)
  const out: Tokens = {}
  for (const key of TOKEN_KEYS) {
    out[key] = cs.getPropertyValue(`--${key}`).trim() || 'currentColor'
  }
  return out
}

/** ECharts custom-series render API, narrowed to what this chart uses. */
interface EChartsApi {
  value(dim: number): number
  coord(pt: number[]): number[]
}

/* ---- chart ------------------------------------------------------------- */
const hostRef = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null

const MONO = 'ui-monospace, SFMono-Regular, monospace'

interface VolRow {
  low: number
  high: number
  buy: number
  sell: number
  inVa: boolean
}

const volRows = computed<VolRow[]>(() => {
  const [lo, hi] = domain.value
  return (props.matrix?.bins ?? [])
    .filter((b) => b.high >= lo && b.low <= hi)
    .map((b) => ({ low: b.low, high: b.high, buy: b.buy, sell: b.sell, inVa: b.in_value_area }))
})

const volMax = computed(() => Math.max(1, ...volRows.value.map((r) => r.buy + r.sell)))

/** Conviction 0-100 mapped to rule thickness. Kept narrow: this is a ranking
 *  aid and a 6px rule would read as a certainty it does not carry. */
function ruleWidth(conviction: number): number {
  return 1.2 + (Math.min(100, Math.max(0, conviction)) / 100) * 2.4
}

function levelColor(l: MergedLevel, t: Tokens): string {
  const d = l.flow?.deltaFrac ?? 0
  if (d >= 0.35) return t['call-hi']
  if (d <= -0.35) return t['put-hi']
  return l.role === 'support' ? t['call-dim'] : t['put-dim']
}

function buildOption(t: Tokens): Record<string, unknown> {
  const [yLo, yHi] = domain.value
  const levels = inFrame.value
  const showProb = hasProb.value

  const axisCommon = {
    min: yLo,
    max: yHi,
    type: 'value' as const,
    axisLine: { show: false },
    axisTick: { show: false },
  }

  const markLines: Array<Record<string, unknown>> = []
  if (props.spot != null && props.spot > 0) {
    markLines.push({
      yAxis: props.spot,
      lineStyle: { color: t.phosphor, width: 1.8, type: 'solid' },
      label: {
        formatter: `SPOT ${num(props.spot, 2)}`,
        position: 'insideEndBottom',
        color: t.void,
        backgroundColor: t.phosphor,
        padding: [2, 5],
        fontFamily: MONO,
        fontSize: 10,
        fontWeight: 'bold',
      },
    })
  }
  if (props.fairValue) {
    markLines.push({
      yAxis: props.fairValue.target,
      lineStyle: { color: t.warn, width: 1.4, type: 'dashed' },
      label: {
        formatter: `MEAN ${num(props.fairValue.target, 2)}`,
        position: 'insideEndTop',
        color: t.warn,
        fontFamily: MONO,
        fontSize: 10,
      },
    })
  }

  return {
    animation: false,
    backgroundColor: 'transparent',
    grid: [
      { left: 8, width: '22%', top: 34, bottom: 30 },
      { left: '27%', right: 74, top: 34, bottom: 30 },
    ],
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: t['panel-hi'],
      borderColor: t.rule,
      textStyle: { color: t['ink-soft'], fontFamily: MONO, fontSize: 11 },
    },
    xAxis: [
      {
        gridIndex: 0,
        type: 'value',
        min: 0,
        max: volMax.value,
        inverse: true,
        axisLabel: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
      },
      {
        gridIndex: 1,
        type: 'value',
        min: 0,
        max: 1,
        axisLabel: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
      },
    ],
    yAxis: [
      {
        ...axisCommon,
        gridIndex: 0,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
      {
        ...axisCommon,
        gridIndex: 1,
        position: 'right',
        splitLine: { show: true, lineStyle: { color: t['rule-faint'] } },
        axisLabel: {
          color: t['ink-faint'],
          fontFamily: MONO,
          fontSize: 10,
          formatter: (v: number) => num(v, 2),
        },
      },
    ],
    // Drag or wheel on the price axis. The preset chips set the window; this
    // lets the operator fine-tune without leaving the chart.
    dataZoom: [{ type: 'inside', yAxisIndex: [0, 1], filterMode: 'none' }],
    series: [
      // Value area, behind the volume lane.
      {
        type: 'custom',
        name: 'value area',
        xAxisIndex: 0,
        yAxisIndex: 0,
        silent: true,
        z: 1,
        data:
          props.matrix?.available && props.matrix.val != null && props.matrix.vah != null
            ? [[props.matrix.val, props.matrix.vah]]
            : [],
        renderItem: (_p: unknown, api: EChartsApi) => {
          const lowPt = api.coord([0, api.value(0)])
          const highPt = api.coord([volMax.value, api.value(1)])
          return {
            type: 'rect',
            shape: {
              x: Math.min(lowPt[0], highPt[0]),
              y: highPt[1],
              width: Math.abs(highPt[0] - lowPt[0]),
              height: Math.max(0, lowPt[1] - highPt[1]),
            },
            style: { fill: t.phosphor, opacity: 0.05 },
          }
        },
      },
      // Volume at price: buy portion, then sell stacked beyond it.
      {
        type: 'custom',
        name: 'volume at price',
        xAxisIndex: 0,
        yAxisIndex: 0,
        z: 2,
        data: volRows.value.map((r) => [r.low, r.high, r.buy, r.sell, r.inVa ? 1 : 0]),
        tooltip: {
          formatter: (p: { value: number[] }) =>
            `${num(p.value[0], 2)} to ${num(p.value[1], 2)}<br/>buy ${num(p.value[2], 0)}<br/>sell ${num(p.value[3], 0)}`,
        },
        renderItem: (_p: unknown, api: EChartsApi) => {
          const low = api.value(0)
          const high = api.value(1)
          const buy = api.value(2)
          const sell = api.value(3)
          const inVa = api.value(4) === 1
          const zero = api.coord([0, low])
          const buyEnd = api.coord([buy, low])
          const totEnd = api.coord([buy + sell, low])
          const yTop = api.coord([0, high])[1]
          const h = Math.max(1.5, zero[1] - yTop - 1)
          const op = inVa ? 0.8 : 0.32
          return {
            type: 'group',
            children: [
              {
                type: 'rect',
                shape: {
                  x: Math.min(zero[0], buyEnd[0]),
                  y: yTop,
                  width: Math.abs(buyEnd[0] - zero[0]),
                  height: h,
                },
                style: { fill: t.call, opacity: op },
              },
              {
                type: 'rect',
                shape: {
                  x: Math.min(buyEnd[0], totEnd[0]),
                  y: yTop,
                  width: Math.abs(totEnd[0] - buyEnd[0]),
                  height: h,
                },
                style: { fill: t.put, opacity: op * 0.85 },
              },
            ],
          }
        },
      },
      // Level rules plus the P(touch) bar, drawn together so a level's weight
      // and its probability cannot drift apart.
      {
        type: 'custom',
        name: 'levels',
        xAxisIndex: 1,
        yAxisIndex: 1,
        z: 3,
        data: levels.map((l) => [l.price, l.prob?.touch ?? 0, l.prob?.terminal ?? 0, l.conviction]),
        tooltip: {
          formatter: (p: { dataIndex: number }) => {
            const l = levels[p.dataIndex]
            if (!l) return ''
            const probTxt = l.prob
              ? `P(touch) ${Math.round(l.prob.touch * 100)}%<br/>P(settle beyond) ${Math.round(l.prob.terminal * 100)}%<br/>`
              : 'no probability: no ATM IV<br/>'
            return `<b>${l.label}</b> ${num(l.price, 2)}<br/>${l.distancePct >= 0 ? '+' : ''}${num(l.distancePct, 2)}% from spot<br/>${probTxt}lenses: ${l.lenses.join(', ')}<br/>conviction ${l.conviction}<br/>${l.evidence.join('<br/>')}`
          },
        },
        renderItem: (p: { dataIndex: number }, api: EChartsApi) => {
          const l = levels[p.dataIndex]
          if (!l) return { type: 'group', children: [] }
          const price = api.value(0)
          const touch = api.value(1)
          const terminal = api.value(2)
          const conviction = api.value(3)
          const y = api.coord([0, price])[1]
          const x0 = api.coord([0, price])[0]
          const x1 = api.coord([1, price])[0]
          const colour = levelColor(l, t)
          const children: Array<Record<string, unknown>> = [
            {
              type: 'line',
              shape: { x1: x0, y1: y, x2: x1, y2: y },
              style: { stroke: colour, lineWidth: ruleWidth(conviction), opacity: 0.9 },
            },
          ]
          if (showProb && l.prob) {
            // Below the rule: the label sits above it, and stacking both on
            // the same side is what made the first cut unreadable.
            const barH = 7
            const barY = y + 2
            children.push({
              type: 'rect',
              shape: {
                x: x0,
                y: barY,
                width: Math.max(0, api.coord([touch, price])[0] - x0),
                height: barH,
              },
              style: { fill: t.phosphor, opacity: 0.28 },
            })
            children.push({
              type: 'rect',
              shape: {
                x: x0,
                y: barY,
                width: Math.max(0, api.coord([terminal, price])[0] - x0),
                height: barH,
              },
              style: { fill: t.phosphor, opacity: 0.7 },
            })
          }
          return { type: 'group', children }
        },
      },
      // Labels only. A separate series so ECharts can resolve occlusion by
      // shifting them; every label states its own price, so a shifted label
      // still cannot be misread as belonging to another level.
      {
        type: 'scatter',
        name: 'level labels',
        xAxisIndex: 1,
        yAxisIndex: 1,
        z: 4,
        symbolSize: 1,
        // A transparent FILL, not opacity: 0. ECharts applies element opacity
        // to the label as well as the symbol, so zeroing it hides the text
        // this series exists to draw.
        itemStyle: { color: 'transparent' },
        silent: true,
        data: levels.map((l) => ({ value: [0, l.price], lvl: l })),
        label: {
          show: true,
          position: 'right',
          offset: [4, -8],
          color: t['ink-soft'],
          fontFamily: MONO,
          fontSize: 10,
          // Vertical padding inflates the label's bounding box, which is what
          // `moveOverlap` measures. Without it ECharts separates two labels to
          // exactly touching, which still reads as a collision.
          padding: [3, 0, 3, 0],
          formatter: (p: { data: { lvl: MergedLevel } }) => {
            const l = p.data.lvl
            const pct = `${l.distancePct >= 0 ? '+' : ''}${num(l.distancePct, 2)}%`
            const probTxt = l.prob ? `  ${Math.round(l.prob.touch * 100)}%` : ''
            return `${l.label}  ${num(l.price, 2)}  ${pct}${probTxt}`
          },
        },
        labelLayout: { moveOverlap: 'shiftY', hideOverlap: false },
        markLine: { silent: true, symbol: 'none', data: markLines },
      },
    ],
  }
}

/**
 * Initialise on first paint of the host element, not on mount.
 *
 * The host only exists once there is something to draw (see `empty`), and on
 * a lazily-activated page that is several seconds after this component
 * mounts. Binding the chart in `onMounted` therefore bound it to nothing and
 * the panel rendered its chrome around an empty box forever.
 */
async function ensureChart(): Promise<void> {
  if (chart || empty.value) return
  await nextTick()
  const host = hostRef.value
  if (!host) return
  tokens.value = readTokens(host)
  chart = echarts.init(host, undefined, { renderer: 'canvas' })
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => chart?.resize())
    ro.observe(host)
  }
}

async function render(): Promise<void> {
  await ensureChart()
  if (!chart || empty.value) return
  chart.setOption(buildOption(tokens.value), { notMerge: true })
  chart.resize()
}

onMounted(() => {
  void render()
})

onBeforeUnmount(() => {
  ro?.disconnect()
  ro = null
  chart?.dispose()
  chart = null
})

watch(
  [() => props.levels, () => props.spot, () => props.fairValue, () => props.matrix, zoom, empty],
  () => void render(),
)

/** Chart height scales with how many levels are in view: floored so a sparse
 *  ladder still reads as a price axis, capped so a dense one is not a scroll. */
const chartHeight = computed(() => {
  const rows = Math.max(9, Math.min(24, inFrame.value.length + 5))
  return Math.max(400, Math.min(720, rows * 30))
})
</script>

<template>
  <div class="level-map">
    <p v-if="empty" class="lm-empty label">
      No level ladder yet. This map draws once a chain, a spot price and the order-flow window have
      all read; nothing is inferred from a partial set.
    </p>
    <template v-else>
      <div class="lm-zoom" role="group" aria-label="Price frame">
        <button
          v-for="z in ZOOMS"
          :key="z.key"
          type="button"
          class="lm-zoom-chip font-mono"
          :class="{ active: zoom === z.key }"
          :title="z.title"
          :aria-pressed="zoom === z.key"
          @click="zoom = z.key"
        >
          {{ z.label }}
        </button>
        <span v-if="framePct != null" class="lm-zoom-span font-mono"
          >&plusmn;{{ num(framePct, 1) }}% of spot &middot; drag or scroll to fine-tune</span
        >
        <span class="lm-zoom-legend font-mono">
          <i class="sw buy"></i> buy <i class="sw sell"></i> sell
          <template v-if="hasProb"><i class="sw prob"></i> P(touch) {{ horizonLabel }}</template>
        </span>
      </div>
      <div ref="hostRef" class="lm-canvas" :style="{ height: `${chartHeight}px` }"></div>
      <p class="lm-foot label wraps">
        Rule thickness is conviction: confluence, order-flow zone strength, touches and rejections,
        and volume share. It ranks levels; it is not a probability.
        <template v-if="hasProb">
          The pale bar is P(touch before horizon), the solid inner bar is P(settle beyond); the gap
          between them is how often price visits a level and is rejected.
        </template>
        <template v-if="offFrame.count > 0">
          Outside this
          <template v-if="framePct != null">&plusmn;{{ num(framePct, 1) }}%</template> frame:
          <template v-if="offFrame.above.length">
            {{ offFrame.above[0].label }} at {{ num(offFrame.above[0].price, 2) }} above<template
              v-if="offFrame.above.length > 1"
            >
              (+{{ offFrame.above.length - 1 }} more)</template
            ><template v-if="offFrame.below.length">, </template>
          </template>
          <template v-if="offFrame.below.length">
            {{ offFrame.below[0].label }} at {{ num(offFrame.below[0].price, 2) }} below<template
              v-if="offFrame.below.length > 1"
            >
              (+{{ offFrame.below.length - 1 }} more)</template
            >
          </template>
          . Press WIDE to include them.
        </template>
      </p>
    </template>
  </div>
</template>

<style scoped>
.level-map {
  width: 100%;
}
.lm-empty {
  padding: 18px 4px;
  color: var(--ink-dim);
}
.lm-canvas {
  width: 100%;
}
.lm-zoom {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.lm-zoom-chip {
  background: transparent;
  border: 1px solid var(--rule);
  color: var(--ink-faint);
  font-size: var(--t-nano);
  letter-spacing: 0.09em;
  padding: 2px 8px;
  cursor: pointer;
}
.lm-zoom-chip:hover {
  color: var(--ink-soft);
  border-color: var(--rule-hi);
}
.lm-zoom-chip.active {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.lm-zoom-span {
  font-size: var(--t-nano);
  color: var(--ink-faint);
  margin-left: 4px;
}
.lm-zoom-legend {
  font-size: var(--t-nano);
  color: var(--ink-faint);
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.sw {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-left: 6px;
}
.sw.buy {
  background: var(--call);
}
.sw.sell {
  background: var(--put);
}
.sw.prob {
  background: var(--phosphor);
}
.lm-foot {
  margin-top: 8px;
  color: var(--ink-faint);
  line-height: 1.5;
}
</style>
