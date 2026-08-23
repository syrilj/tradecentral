<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import type { OptionsFlowPoint, OptionsPricePoint } from '@/api'
import { linearScale, linePath, niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'
import { compact, DASH, num } from '@/format'

/**
 * Market-style dual-pane chart for options desk:
 *   · top  — underlying close + structure levels (walls / spot / flip-adjacent)
 *   · bottom — call vs put premium bars per bucket (activity, not direction)
 *
 * Shares one ordinal (session-continuous) time axis so nights/weekends collapse.
 * Hover crosshair + dense readout so the graph is practically readable.
 */
const props = withDefaults(defineProps<{
  symbol: string
  price: OptionsPricePoint[]
  flow: OptionsFlowPoint[]
  height?: number
  selectedExpiry?: string | null
  callWall?: number | null
  putWall?: number | null
  spot?: number | null
  gammaFlip?: number | null
}>(), {
  height: 360,
  selectedExpiry: null,
  callWall: null,
  putWall: null,
  spot: null,
  gammaFlip: null,
})

const frameEl = ref<HTMLDivElement | null>(null)
const svgEl = ref<SVGSVGElement | null>(null)
const uid = useId()
const { W } = useChartSize(frameEl, {
  minW: 240,
  minH: 80,
  fallbackW: 1120,
  fallbackH: props.height,
})
const H = computed(() => Math.max(220, Math.round(props.height)))

/** Cumulative premium overlay on price pane — optional, off by default. */
const showCumPrem = ref(false)

const pad = computed(() => {
  const narrow = W.value < 480
  return {
    l: narrow ? 42 : 50,
    r: showCumPrem.value ? (narrow ? 46 : 54) : (narrow ? 12 : 16),
    t: 18,
    b: 20,
    gap: 10,
  }
})

/** Price pane ~68%, activity pane ~32% of plot height. */
const priceH = computed(() => {
  const inner = H.value - pad.value.t - pad.value.b - pad.value.gap
  return Math.max(110, Math.round(inner * 0.68))
})
const flowH = computed(() => {
  const inner = H.value - pad.value.t - pad.value.b - pad.value.gap
  return Math.max(56, inner - priceH.value)
})
const priceTop = computed(() => pad.value.t)
const priceBot = computed(() => pad.value.t + priceH.value)
const flowTop = computed(() => priceBot.value + pad.value.gap)
const flowBot = computed(() => flowTop.value + flowH.value)

const hoverIdx = ref<number | null>(null)

function time(value: string): number {
  const parsed = new Date(value).getTime()
  return Number.isFinite(parsed) ? parsed : 0
}

const orderedPrice = computed(() => [...props.price]
  .filter((p) => Number.isFinite(p.close) && time(p.t))
  .sort((a, b) => time(a.t) - time(b.t)))

const orderedFlow = computed(() => [...props.flow]
  .filter((p) => time(p.t))
  .sort((a, b) => time(a.t) - time(b.t)))

const timeline = computed<number[]>(() => {
  const set = new Set<number>()
  for (const p of orderedPrice.value) set.add(time(p.t))
  for (const p of orderedFlow.value) set.add(time(p.t))
  return Array.from(set).sort((a, b) => a - b)
})

const timelineIndex = computed(() => {
  const map = new Map<number, number>()
  timeline.value.forEach((ts, i) => map.set(ts, i))
  return map
})

const xScale = computed(() => linearScale(
  [0, Math.max(timeline.value.length - 1, 0)],
  [pad.value.l, W.value - pad.value.r],
))

function ordinalIndex(ts: number): number {
  const arr = timeline.value
  const n = arr.length
  if (n === 0) return 0
  if (ts <= arr[0]) return 0
  if (ts >= arr[n - 1]) return n - 1
  let lo = 0
  let hi = n - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (arr[mid] <= ts) lo = mid
    else hi = mid
  }
  const span = arr[hi] - arr[lo]
  return span > 0 ? lo + (ts - arr[lo]) / span : lo
}

function xOf(ts: number): number {
  const exact = timelineIndex.value.get(ts)
  return xScale.value(exact ?? ordinalIndex(ts))
}

const domain = computed(() => {
  const arr = timeline.value
  if (!arr.length) return { lo: 0, hi: 1, span: 1 }
  const lo = arr[0]
  const hi = arr[arr.length - 1]
  if (lo === hi) return { lo: lo - 21_600_000, hi: hi + 21_600_000, span: 43_200_000 }
  return { lo, hi, span: hi - lo }
})

const priceDomain = computed(() => {
  let lo = Infinity
  let hi = -Infinity
  for (const p of orderedPrice.value) {
    if (p.close < lo) lo = p.close
    if (p.close > hi) hi = p.close
  }
  for (const extra of [props.spot, props.callWall, props.putWall, props.gammaFlip]) {
    if (extra != null && Number.isFinite(extra) && extra > 0) {
      if (extra < lo) lo = extra
      if (extra > hi) hi = extra
    }
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { lo: 0, hi: 1 }
  const padAmt = Math.max((hi - lo) * 0.12, hi * 0.006, 0.5)
  return { lo: lo - padAmt, hi: hi + padAmt }
})

interface FlowBucket extends OptionsFlowPoint {
  calls: number
  puts: number
  ts: number
}

const cumulativeFlow = computed<FlowBucket[]>(() => {
  let calls = 0
  let puts = 0
  return orderedFlow.value.map((point) => {
    calls += Math.max(0, point.call_premium || 0)
    puts += Math.max(0, point.put_premium || 0)
    return { ...point, calls, puts, ts: time(point.t) }
  })
})

const premiumDomain = computed(() => {
  let max = 1
  for (const p of cumulativeFlow.value) {
    if (p.calls > max) max = p.calls
    if (p.puts > max) max = p.puts
  }
  return { lo: 0, hi: max * 1.06 }
})

/** Per-bucket max for the activity bar pane. */
const bucketPremMax = computed(() => {
  let max = 1
  for (const p of orderedFlow.value) {
    max = Math.max(max, p.call_premium || 0, p.put_premium || 0)
  }
  return max
})

const priceScale = computed(() => linearScale(
  [priceDomain.value.lo, priceDomain.value.hi],
  [priceBot.value, priceTop.value],
))
function priceY(value: number): number {
  return priceScale.value(value)
}

const premiumScale = computed(() => linearScale(
  [premiumDomain.value.lo, premiumDomain.value.hi],
  [priceBot.value, priceTop.value],
))
function premiumY(value: number): number {
  return premiumScale.value(value)
}

const pricePath = computed(() => linePath(
  orderedPrice.value.map((p) => ({ x: xOf(time(p.t)), y: priceY(p.close) })),
))

function premiumPath(key: 'calls' | 'puts'): string {
  return linePath(cumulativeFlow.value.map((p) => ({ x: xOf(p.ts), y: premiumY(p[key]) })))
}

const callPath = computed(() => premiumPath('calls'))
const putPath = computed(() => premiumPath('puts'))

const priceTicks = computed(() => niceTicks(priceDomain.value.lo, priceDomain.value.hi, 5)
  .map((value) => ({ value, y: priceY(value) })))

const premiumTicks = computed(() => niceTicks(premiumDomain.value.lo, premiumDomain.value.hi, 3)
  .map((value) => ({ value, y: premiumY(value) })))

/** Activity bars: side-by-side call/put per bucket. */
const activityBars = computed(() => {
  const n = Math.max(timeline.value.length, 1)
  const slot = Math.max(2, (W.value - pad.value.l - pad.value.r) / n)
  const half = Math.min(6, slot * 0.35)
  return orderedFlow.value.map((p) => {
    const ts = time(p.t)
    const x = xOf(ts)
    const c = Math.max(0, p.call_premium || 0)
    const pu = Math.max(0, p.put_premium || 0)
    const scale = flowH.value / bucketPremMax.value
    return {
      t: p.t,
      ts,
      x,
      callH: Math.max(c > 0 ? 1.5 : 0, c * scale),
      putH: Math.max(pu > 0 ? 1.5 : 0, pu * scale),
      call: c,
      put: pu,
      half,
      anomalies: p.anomaly_count || 0,
      signed: p.signed_net_premium,
    }
  })
})

function timeLabel(timestamp: number): string {
  const date = new Date(timestamp)
  if (domain.value.span <= 2 * 86_400_000) {
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC',
    })
  }
  return date.toLocaleDateString('en-US', {
    month: 'short', day: '2-digit', timeZone: 'UTC',
  }).toUpperCase()
}

const timeTicks = computed(() => {
  const arr = timeline.value
  const n = arr.length
  if (!n) return [] as { x: number; label: string }[]
  const count = Math.min(6, n)
  const indices = new Set<number>()
  if (count <= 1) indices.add(0)
  else {
    for (let k = 0; k < count; k++) {
      indices.add(Math.round((k * (n - 1)) / (count - 1)))
    }
  }
  return Array.from(indices)
    .sort((a, b) => a - b)
    .map((i) => ({ x: xScale.value(i), label: timeLabel(arr[i]) }))
})

const lastPrice = computed(() => orderedPrice.value.at(-1)?.close)

const totalCallPrem = computed(() => cumulativeFlow.value.at(-1)?.calls ?? 0)
const totalPutPrem = computed(() => cumulativeFlow.value.at(-1)?.puts ?? 0)
const netActivity = computed(() => {
  const c = totalCallPrem.value
  const p = totalPutPrem.value
  if (c + p <= 0) return null
  return (c - p) / (c + p)
})

const opexMarkers = computed(() => {
  const { lo, hi } = domain.value
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return [] as { ts: number; x: number; label: string }[]
  const out: { ts: number; x: number; label: string }[] = []
  const start = new Date(lo)
  const end = new Date(hi)
  let y = start.getUTCFullYear()
  let m = start.getUTCMonth()
  const endY = end.getUTCFullYear()
  const endM = end.getUTCMonth()
  while (y < endY || (y === endY && m <= endM)) {
    const first = new Date(Date.UTC(y, m, 1))
    const dow = first.getUTCDay()
    const firstFri = 1 + ((5 - dow + 7) % 7)
    const thirdFri = firstFri + 14
    const ts = Date.UTC(y, m, thirdFri, 20, 0, 0)
    if (ts >= lo && ts <= hi) {
      out.push({
        ts,
        x: xOf(ts),
        label: new Date(ts).toLocaleDateString('en-US', { month: 'short', day: '2-digit', timeZone: 'UTC' }).toUpperCase(),
      })
    }
    m += 1
    if (m > 11) { m = 0; y += 1 }
  }
  return out
})

const selectedExpiryMarker = computed(() => {
  if (!props.selectedExpiry) return null
  const ts = Date.parse(`${props.selectedExpiry}T20:00:00Z`)
  if (!Number.isFinite(ts)) return null
  const { lo, hi } = domain.value
  if (ts < lo || ts > hi) return null
  return { ts, x: xOf(ts), label: 'SEL EXP' }
})

const levelGuides = computed(() => {
  const raw: { value: number; y: number; cls: string; label: string; labelY: number }[] = []
  if (props.putWall != null && Number.isFinite(props.putWall)) {
    raw.push({ value: props.putWall, y: priceY(props.putWall), cls: 'put', label: 'PUT', labelY: 0 })
  }
  if (props.gammaFlip != null && Number.isFinite(props.gammaFlip)) {
    raw.push({ value: props.gammaFlip, y: priceY(props.gammaFlip), cls: 'flip', label: 'FLIP', labelY: 0 })
  }
  if (props.callWall != null && Number.isFinite(props.callWall)) {
    raw.push({ value: props.callWall, y: priceY(props.callWall), cls: 'call', label: 'CALL', labelY: 0 })
  }
  if (props.spot != null && Number.isFinite(props.spot)) {
    raw.push({ value: props.spot, y: priceY(props.spot), cls: 'spot', label: 'SPOT', labelY: 0 })
  }

  const sorted = raw
    .filter((g) => g.y >= priceTop.value && g.y <= priceBot.value)
    .sort((a, b) => a.y - b.y)

  const MIN_GAP = 13
  let prevLabelY = -Infinity
  for (const g of sorted) {
    g.labelY = Math.max(g.y, prevLabelY + MIN_GAP)
    prevLabelY = g.labelY
  }
  const overflow = prevLabelY - (priceBot.value - 2)
  if (overflow > 0) {
    for (const g of sorted) g.labelY -= overflow
  }
  return sorted
})

const priceByTs = computed(() => {
  const map = new Map<number, OptionsPricePoint>()
  for (const p of orderedPrice.value) map.set(time(p.t), p)
  return map
})

const flowByTs = computed(() => {
  const map = new Map<number, FlowBucket>()
  for (const p of cumulativeFlow.value) map.set(p.ts, p)
  return map
})

const flowRawByTs = computed(() => {
  const map = new Map<number, OptionsFlowPoint>()
  for (const p of orderedFlow.value) map.set(time(p.t), p)
  return map
})

const focus = computed(() => {
  const idx = hoverIdx.value
  if (idx == null) return null
  const ts = timeline.value[idx]
  if (ts == null) return null
  const price = priceByTs.value.get(ts) ?? null
  const flow = flowByTs.value.get(ts) ?? null
  const raw = flowRawByTs.value.get(ts) ?? null
  return {
    ts,
    x: xScale.value(idx),
    price: price?.close ?? null,
    calls: flow?.calls ?? null,
    puts: flow?.puts ?? null,
    bucketCall: raw?.call_premium ?? null,
    bucketPut: raw?.put_premium ?? null,
    signed: raw?.signed_net_premium ?? null,
    anomalies: raw?.anomaly_count ?? 0,
  }
})

function onMove(e: MouseEvent): void {
  const el = svgEl.value
  const n = timeline.value.length
  if (!el || n === 0) {
    hoverIdx.value = null
    return
  }
  const box = el.getBoundingClientRect()
  if (box.width <= 0 || box.height <= 0) {
    hoverIdx.value = null
    return
  }
  const px = ((e.clientX - box.left) / box.width) * W.value
  const py = ((e.clientY - box.top) / box.height) * H.value
  if (px < pad.value.l || px > W.value - pad.value.r || py < pad.value.t || py > flowBot.value) {
    hoverIdx.value = null
    return
  }
  const idx = Math.round(xScale.value.invert(px))
  hoverIdx.value = Math.max(0, Math.min(n - 1, idx))
}
</script>

<template>
  <div class="drift-wrap">
    <div class="chart-readout">
      <span class="main-px">
        <i class="key price" />{{ symbol }}
        <b class="fig">{{ lastPrice != null ? num(lastPrice) : DASH }}</b>
      </span>
      <span class="struct call" v-if="callWall != null">C-WALL {{ num(callWall) }}</span>
      <span class="struct put" v-if="putWall != null">P-WALL {{ num(putWall) }}</span>
      <span class="struct flip" v-if="gammaFlip != null">FLIP {{ num(gammaFlip) }}</span>
      <span class="struct spot" v-if="spot != null">SPOT {{ num(spot) }}</span>
      <span class="prem-sum call">ΣC ${{ compact(totalCallPrem) }}</span>
      <span class="prem-sum put">ΣP ${{ compact(totalPutPrem) }}</span>
      <span
        v-if="netActivity != null"
        class="imbalance"
        :class="netActivity > 0.05 ? 'call' : netActivity < -0.05 ? 'put' : ''"
        title="Call−put activity share (not bought/sold direction)"
      >
        IMB {{ netActivity > 0 ? '+' : '' }}{{ (netActivity * 100).toFixed(0) }}%
      </span>
      <button type="button" class="prem-toggle label" :class="{ on: showCumPrem }" @click="showCumPrem = !showCumPrem">
        {{ showCumPrem ? 'HIDE Σ' : 'Σ PREM' }}
      </button>
      <span v-if="focus" class="probe-inline">
        <span class="label">{{ new Date(focus.ts).toISOString().slice(0, 16).replace('T', ' ') }}Z</span>
        <span v-if="focus.price != null"> <b class="fig">{{ num(focus.price) }}</b></span>
        <span v-if="focus.bucketCall != null" class="call"> C ${{ compact(focus.bucketCall) }}</span>
        <span v-if="focus.bucketPut != null" class="put"> P ${{ compact(focus.bucketPut) }}</span>
        <span v-if="focus.signed != null" :class="focus.signed >= 0 ? 'call' : 'put'">
          · signed ${{ compact(focus.signed) }}
        </span>
        <span v-if="focus.anomalies" class="anomaly-readout"> · {{ focus.anomalies }} FLAG</span>
      </span>
      <span v-else class="scale-note label">UTC · hover for bucket premium</span>
    </div>

    <div ref="frameEl" class="drift-canvas" :style="{ height: `${H}px` }">
      <svg
        ref="svgEl"
        class="drift-svg"
        :viewBox="`0 0 ${W} ${H}`"
        role="img"
        :aria-label="`${symbol} price with call/put premium activity`"
        preserveAspectRatio="xMidYMid meet"
        @mousemove="onMove"
        @mouseleave="hoverIdx = null"
      >
        <title>{{ symbol }} price vs structure with call/put premium activity bars</title>
        <defs>
          <pattern :id="`optionGrid-${uid}`" width="28" height="28" patternUnits="userSpaceOnUse">
            <path d="M 28 0 L 0 0 0 28" fill="none" stroke="var(--grid)" stroke-width="1" />
          </pattern>
        </defs>

        <!-- PRICE PANE -->
        <rect
          :x="pad.l"
          :y="priceTop"
          :width="W - pad.l - pad.r"
          :height="priceH"
          :fill="`url(#optionGrid-${uid})`"
        />
        <text class="pane-cap" :x="pad.l + 4" :y="priceTop + 11">PRICE / STRUCTURE</text>

        <g class="opex-marks">
          <g v-for="m in opexMarkers" :key="`opex-${m.ts}`">
            <line :x1="m.x" :x2="m.x" :y1="priceTop" :y2="priceBot" class="opex-line" />
            <text :x="m.x + 3" :y="priceTop + 22" class="opex-label">OPEX {{ m.label }}</text>
          </g>
          <g v-if="selectedExpiryMarker">
            <line
              :x1="selectedExpiryMarker.x"
              :x2="selectedExpiryMarker.x"
              :y1="priceTop"
              :y2="priceBot"
              class="selected-exp-line"
            />
            <text :x="selectedExpiryMarker.x + 3" :y="priceTop + 33" class="selected-exp-label">
              {{ selectedExpiryMarker.label }}
            </text>
          </g>
        </g>

        <g class="level-guides">
          <g v-for="g in levelGuides" :key="`${g.cls}-${g.value}`">
            <line :x1="pad.l" :x2="W - pad.r" :y1="g.y" :y2="g.y" :class="['level-line', g.cls]" />
            <line
              v-if="Math.abs(g.labelY - g.y) > 1"
              :x1="W - pad.r - 2"
              :x2="W - pad.r - 2"
              :y1="g.y"
              :y2="g.labelY - 8"
              :class="['level-leader', g.cls]"
            />
            <text :x="W - pad.r - 4" :y="g.labelY - 3" text-anchor="end" :class="['level-label', g.cls]">
              {{ g.label }} {{ num(g.value) }}
            </text>
          </g>
        </g>

        <g class="grid-lines">
          <template v-for="tick in priceTicks" :key="`p-${tick.y}`">
            <line :x1="pad.l" :x2="W - pad.r" :y1="tick.y" :y2="tick.y" />
            <text :x="pad.l - 6" :y="tick.y + 3" text-anchor="end">{{ num(tick.value) }}</text>
          </template>
        </g>

        <g v-if="showCumPrem" class="premium-axis">
          <line class="premium-axis-rule" :x1="W - pad.r" :x2="W - pad.r" :y1="priceTop" :y2="priceBot" />
          <template v-for="tick in premiumTicks" :key="`f-${tick.y}`">
            <line class="premium-axis-tick" :x1="W - pad.r" :x2="W - pad.r + 4" :y1="tick.y" :y2="tick.y" />
            <text :x="W - pad.r + 6" :y="tick.y + 3">${{ compact(tick.value) }}</text>
          </template>
        </g>

        <path v-if="showCumPrem && callPath" class="flow-trace call" :d="callPath" />
        <path v-if="showCumPrem && putPath" class="flow-trace put" :d="putPath" />

        <path v-if="pricePath" class="price-trace" :d="pricePath" />
        <circle
          v-if="orderedPrice.length && lastPrice != null"
          :cx="xOf(time(orderedPrice.at(-1)!.t))"
          :cy="priceY(lastPrice)"
          r="3.5"
          class="last-dot"
        />

        <!-- ACTIVITY PANE -->
        <rect
          class="flow-pane-bg"
          :x="pad.l"
          :y="flowTop"
          :width="W - pad.l - pad.r"
          :height="flowH"
        />
        <text class="pane-cap" :x="pad.l + 4" :y="flowTop + 11">CALL / PUT PREMIUM · BUCKET</text>
        <line class="pane-div" :x1="pad.l" :x2="W - pad.r" :y1="flowTop" :y2="flowTop" />

        <g class="activity-bars">
          <g v-for="bar in activityBars" :key="bar.t" :class="{ 'is-active': focus && Math.abs(focus.x - bar.x) < (bar.half + 2) }">
            <rect
              class="bar call"
              :x="bar.x - bar.half - 0.5"
              :y="flowBot - bar.callH"
              :width="bar.half"
              :height="bar.callH"
            >
              <title>Call ${{ compact(bar.call) }} · {{ bar.t }}</title>
            </rect>
            <rect
              class="bar put"
              :x="bar.x + 0.5"
              :y="flowBot - bar.putH"
              :width="bar.half"
              :height="bar.putH"
            >
              <title>Put ${{ compact(bar.put) }} · {{ bar.t }}</title>
            </rect>
            <circle
              v-if="bar.anomalies"
              :cx="bar.x"
              :cy="flowTop + 14"
              r="2.5"
              class="anomaly-dot"
            />
          </g>
        </g>
        <text class="axis-cap flow-y" :x="pad.l - 6" :y="flowTop + flowH / 2" text-anchor="end">$</text>

        <g v-if="focus" class="crosshair">
          <line :x1="focus.x" :x2="focus.x" :y1="priceTop" :y2="flowBot" class="crosshair-v" />
          <line v-if="focus.price != null" :x1="pad.l" :x2="W - pad.r" :y1="priceY(focus.price)" :y2="priceY(focus.price)" class="crosshair-h" />
          <circle v-if="focus.price != null" :cx="focus.x" :cy="priceY(focus.price)" r="4" class="price-dot" />
          <g v-if="focus.price != null" class="crosshair-badge">
            <rect
              :x="pad.l - (W < 480 ? 40 : 48)"
              :y="priceY(focus.price) - 8"
              :width="W < 480 ? 38 : 46"
              height="16"
              class="crosshair-pill-bg"
            />
            <text
              :x="pad.l - 4"
              :y="priceY(focus.price) + 3.5"
              text-anchor="end"
              class="crosshair-pill-text"
            >{{ num(focus.price) }}</text>
          </g>
        </g>

        <g v-if="pricePath || flow.length" class="time-axis">
          <template v-for="tick in timeTicks" :key="tick.x">
            <line :x1="tick.x" :x2="tick.x" :y1="flowBot" :y2="flowBot + 4" />
            <text :x="tick.x" :y="H - 5" text-anchor="middle">{{ tick.label }}</text>
          </template>
        </g>

        <text v-if="!pricePath" class="empty" :x="W / 2" :y="priceTop + priceH / 2" text-anchor="middle">
          NO PRICE TRACE IN SELECTED RANGE
        </text>
        <text
          v-if="pricePath && !activityBars.length"
          class="empty-soft"
          :x="W / 2"
          :y="flowTop + flowH / 2"
          text-anchor="middle"
        >
          NO QUALIFIED PREMIUM BUCKETS — try RAW filter
        </text>
      </svg>
    </div>
  </div>
</template>

<style scoped>
/* Surface glass token: var(--glass-surface-hi) */
.drift-wrap {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.chart-readout {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 8px;
  min-height: 22px;
  flex: 0 0 auto;
  padding: 3px 6px 2px;
  font-family: var(--font-display);
  font-size: 10px;
  letter-spacing: .04em;
  color: var(--ink-dim);
  border-bottom: var(--hair) solid var(--rule-faint);
  background: var(--panel-hi);
}
.chart-readout span { display: inline-flex; align-items: center; gap: 3px; }
.chart-readout b { color: var(--ink); font-weight: 650; }
.main-px { font-weight: 700; color: var(--ink); }
.struct { font-size: 9px; font-weight: 700; letter-spacing: 0.04em; padding: 1px 4px; border: var(--hair) solid var(--rule); }
.struct.call { color: var(--call); }
.struct.put { color: var(--put); }
.struct.flip { color: var(--warn); }
.struct.spot { color: var(--ink); }
.prem-sum.call, .chart-readout .call, .probe-inline .call { color: var(--call); }
.prem-sum.put, .chart-readout .put, .probe-inline .put { color: var(--put); }
.imbalance { font-weight: 700; }
.probe-inline {
  margin-left: auto;
  padding: 1px 6px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  color: var(--ink);
  min-height: 20px;
  transition: transform 0.15s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.15s ease;
}
.scale-note { margin-left: auto; color: var(--ink-faint); }
.anomaly-readout { color: var(--warn); }
.prem-toggle {
  padding: 1px 6px;
  min-height: 20px;
  color: var(--ink-faint);
  border: var(--hair) solid var(--rule-hi);
  background: transparent;
  cursor: pointer;
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}
.prem-toggle.on { color: var(--phosphor); border-color: var(--phosphor-dim); background: var(--phosphor-wash); }
.key { width: 12px; height: 2px; display: inline-block; border-radius: 1px; }
.key.price { background: var(--ink); }
.drift-canvas {
  position: relative;
  width: 100%;
  min-width: 0;
  overflow: hidden;
}
.drift-svg { display: block; width: 100%; height: 100%; overflow: visible; background: var(--void-lift); cursor: crosshair; }
.pane-cap {
  fill: var(--ink-faint);
  font: 600 9px var(--font-display);
  letter-spacing: 0.1em;
}
.pane-div { stroke: var(--rule-hi); stroke-width: 1px; vector-effect: non-scaling-stroke; }
.flow-pane-bg { fill: var(--panel); }
.grid-lines line {
  stroke: var(--rule);
  stroke-width: 1px;
  vector-effect: non-scaling-stroke;
}
.grid-lines text, .premium-axis text, .time-axis text, .axis-cap {
  fill: var(--ink-dim);
  font: 600 10px var(--font-data);
  letter-spacing: .03em;
}
.premium-axis text { fill: var(--ink-faint); }
.premium-axis-rule, .premium-axis-tick {
  stroke: var(--rule-faint);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.axis-cap.flow-y { fill: var(--ink-faint); font-size: 9px; }
.time-axis line { stroke: var(--rule-hi); vector-effect: non-scaling-stroke; }
.price-trace {
  fill: none;
  stroke: var(--ink);
  stroke-width: 2.2;
  vector-effect: non-scaling-stroke;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.last-dot { fill: var(--ink); stroke: var(--void); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.flow-trace {
  fill: none;
  vector-effect: non-scaling-stroke;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.3;
  opacity: .4;
}
.flow-trace.call { stroke: var(--call-hi); stroke-width: 1.75; }
.flow-trace.put { stroke: var(--put-hi); stroke-width: 1.75; }

/* Activity bars: crisp solid fills, border strokes, and responsive hover transitions */
.activity-bars .bar {
  vector-effect: non-scaling-stroke;
  stroke-width: 1px;
  opacity: 0.92;
  transition: opacity 0.15s cubic-bezier(0.16, 1, 0.3, 1), stroke-width 0.15s ease, fill 0.15s ease;
}
.activity-bars .bar.call { fill: var(--call); stroke: var(--call-hi); }
.activity-bars .bar.put { fill: var(--put); stroke: var(--put-hi); }
.activity-bars g:hover .bar,
.activity-bars g.is-active .bar {
  opacity: 1;
  stroke-width: 1.5px;
}
.activity-bars g:hover .bar.call,
.activity-bars g.is-active .bar.call { fill: var(--call-hi); }
.activity-bars g:hover .bar.put,
.activity-bars g.is-active .bar.put { fill: var(--put-hi); }

.anomaly-dot { fill: var(--warn); }
.opex-marks .opex-line {
  stroke: var(--phosphor-dim);
  stroke-width: 1;
  stroke-dasharray: 5 5;
  opacity: .5;
  vector-effect: non-scaling-stroke;
}
.opex-marks .selected-exp-line {
  stroke: var(--phosphor);
  stroke-width: 1.3;
  stroke-dasharray: 2 3;
  opacity: .85;
  vector-effect: non-scaling-stroke;
}
.opex-label, .selected-exp-label {
  fill: var(--phosphor-dim);
  font: 600 9px var(--font-display);
  letter-spacing: .05em;
  paint-order: stroke;
  stroke: var(--void);
  stroke-width: 3px;
}
.selected-exp-label { fill: var(--phosphor); }
.level-line {
  stroke-width: 1.25px;
  stroke-dasharray: 5 4;
  opacity: .9;
  vector-effect: non-scaling-stroke;
  transition: stroke 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}
.level-line.put { stroke: var(--put); }
.level-line.call { stroke: var(--call); }
.level-line.flip { stroke: var(--warn); stroke-dasharray: 3 3; }
.level-line.spot { stroke: var(--ink); stroke-dasharray: none; stroke-width: 1.15px; opacity: .5; }
.level-leader { stroke-width: 1px; opacity: .55; vector-effect: non-scaling-stroke; }
.level-leader.put { stroke: var(--put); }
.level-leader.call { stroke: var(--call); }
.level-leader.flip { stroke: var(--warn); }
.level-leader.spot { stroke: var(--ink); }
.level-label {
  font: 700 10px var(--font-display);
  letter-spacing: .04em;
  paint-order: stroke;
  stroke: var(--void);
  stroke-width: 3.5px;
  transition: fill 0.15s ease;
}
.level-label.put { fill: var(--put-hi); }
.level-label.call { fill: var(--call-hi); }
.level-label.flip { fill: var(--warn); }
.level-label.spot { fill: var(--ink); }

/* Crosshair overlay */
.crosshair {
  transition: opacity 0.15s ease;
}
.crosshair .crosshair-v {
  stroke: var(--phosphor);
  stroke-width: 1px;
  stroke-dasharray: 2 3;
  opacity: .85;
  vector-effect: non-scaling-stroke;
}
.crosshair .crosshair-h {
  stroke: var(--rule-hi);
  stroke-width: 1px;
  stroke-dasharray: 2 2;
  opacity: .75;
  vector-effect: non-scaling-stroke;
}
.crosshair .price-dot {
  fill: var(--phosphor);
  stroke: var(--void);
  stroke-width: 1.5px;
  transition: transform 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}
.crosshair-pill-bg {
  fill: var(--panel-raise);
  stroke: var(--phosphor-dim);
  stroke-width: 1px;
}
.crosshair-pill-text {
  fill: var(--phosphor);
  font: 700 9px var(--font-data);
}

.empty { fill: var(--ink-faint); font: 11px var(--font-display); letter-spacing: .1em; }
.empty-soft { fill: var(--ink-ghost); font: 10px var(--font-display); letter-spacing: .08em; }
@media (max-width: 900px) {
  .chart-readout { gap: 3px 5px; }
  .scale-note, .probe-inline { width: 100%; margin-left: 0; }
  .struct { display: none; }
}
</style>
