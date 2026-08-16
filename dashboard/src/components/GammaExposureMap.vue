<script setup lang="ts">
/**
 * Net-GEX & Call/Put Strike Profile — vertical dual bars & net profile across the options desk.
 *
 *   · X axis = strike (low → high, left → right)
 *   · Call GEX / Call OI = positive call-blue bar ABOVE zero line (var(--call))
 *   · Put GEX / Put OI = negative put-amber bar BELOW zero line (var(--put))
 *   · Net GEX / Net OI = flat ink circle marker on top (var(--ink))
 *   · Net Trace = continuous profile line connecting net markers
 *   · Regime Zones = subtle demarcation of Long Gamma vs Short Gamma relative to Flip
 *
 * Dual-bar representation ensures neutral strikes (e.g. +$50M Call / -$50M Put)
 * show full gamma battleground instead of disappearing into a 0-height net line.
 */
import { computed, ref, watch } from 'vue'
import type { GexStrikeRow } from '@/api'
import { niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'
import { compact, DASH, num } from '@/format'

interface Bar extends GexStrikeRow {
  net: number
  callVal: number
  putVal: number
  callH: number
  callY: number
  putH: number
  putY: number
  netH: number
  netY: number
  cumNet: number
  cumNetY: number
  cx: number
  thickness: number
  isSpotNear: boolean
  isCallWall: boolean
  isPutWall: boolean
  isFlip: boolean
}

interface Level {
  key: string
  label: string
  value: number
  cls: string
  x: number
  labelX: number
  labelY: number
}

const props = withDefaults(defineProps<{
  rows: GexStrikeRow[]
  spot: number
  callWall: number | null
  putWall: number | null
  gammaFlip: number | null
  focusStrike?: number | null
  maxHeight?: number
}>(), { maxHeight: 620, focusStrike: null })

const emit = defineEmits<{
  'update:focusStrike': [strike: number | null]
}>()

function lockStrike(strike: number): void {
  emit('update:focusStrike', props.focusStrike === strike ? null : strike)
}

function clearLock(): void {
  emit('update:focusStrike', null)
}

function onBarKeydown(e: KeyboardEvent, strike: number): void {
  if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
    e.preventDefault()
    lockStrike(strike)
  } else if (e.key === 'Escape') {
    e.preventDefault()
    clearLock()
  } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    e.preventDefault()
    const rows = orderedRows.value
    const idx = rows.findIndex((r) => r.strike === strike)
    if (idx === -1) return
    const nextIdx = e.key === 'ArrowLeft' ? Math.max(0, idx - 1) : Math.min(rows.length - 1, idx + 1)
    const nextStrike = rows[nextIdx].strike
    hoverStrike.value = nextStrike
    if (props.focusStrike != null) {
      emit('update:focusStrike', nextStrike)
    }
  }
}

watch(
  () => props.rows,
  (rows) => {
    if (props.focusStrike == null) return
    if (!rows.some((r) => r.strike === props.focusStrike)) {
      emit('update:focusStrike', null)
    }
  },
)

const hostRef = ref<HTMLDivElement | null>(null)
const { W: hostW, H: hostH } = useChartSize(hostRef, {
  minW: 200,
  minH: 140,
  fallbackW: 800,
  fallbackH: 320,
})

const left = 52
const right = 20
const top = 30
const bottom = 36
const minCol = 14

const hoverStrike = ref<number | null>(null)
const strikeScope = ref<'atm' | 'near' | 'wide' | 'all'>('near')
const metric = ref<'gex' | 'oi'>('gex')
const viewMode = ref<'dual' | 'net' | 'cumulative'>('dual')
const showTrace = ref<boolean>(true)
const showRegimes = ref<boolean>(true)

const visible = computed(() => {
  if (!props.rows.length) return []
  if (strikeScope.value === 'all') return props.rows
  let ratio = 0.12
  if (strikeScope.value === 'atm') ratio = 0.06
  else if (strikeScope.value === 'wide') ratio = 0.25
  const filtered = props.rows.filter((r) => r.strike >= props.spot * (1 - ratio) && r.strike <= props.spot * (1 + ratio))
  return filtered.length >= 6 ? filtered : props.rows
})

const orderedRows = computed(() => [...visible.value].sort((a, b) => a.strike - b.strike))
const colCount = computed(() => Math.max(orderedRows.value.length, 1))

const H = computed(() => Math.max(140, hostH.value || 320))
const plotInnerH = computed(() => Math.max(60, H.value - top - bottom))
const plotBottom = computed(() => top + plotInnerH.value)
const zeroY = computed(() => top + plotInnerH.value / 2)
const halfPlotH = computed(() => Math.max(1, plotInnerH.value / 2 - 4))

const plotInnerW = computed(() => {
  const minNeed = colCount.value * minCol
  const hostInner = Math.max(120, hostW.value - left - right)
  return Math.max(hostInner, minNeed)
})
const W = computed(() => plotInnerW.value + left + right)
const scrollable = computed(() => W.value > hostW.value + 0.5)
const bandW = computed(() => plotInnerW.value / colCount.value)

function bandCenter(index: number): number {
  return left + bandW.value * (index + 0.5)
}

const maxAbs = computed(() => {
  if (!orderedRows.value.length) return 1e-9
  const vals: number[] = []
  for (const r of orderedRows.value) {
    if (metric.value === 'gex') {
      vals.push(Math.abs(r.call_gex_m), Math.abs(r.put_gex_m), Math.abs(r.net_gex_m))
    } else {
      vals.push(Math.abs(r.call_oi), Math.abs(r.put_oi), Math.abs(r.call_oi - r.put_oi))
    }
  }
  return Math.max(1e-9, ...vals)
})

const totalNet = computed(() =>
  orderedRows.value.reduce((s, r) => s + (metric.value === 'gex' ? r.net_gex_m : r.call_oi - r.put_oi), 0),
)
const callTotal = computed(() =>
  orderedRows.value.reduce((s, r) => s + (metric.value === 'gex' ? r.call_gex_m : r.call_oi), 0),
)
const putTotal = computed(() =>
  orderedRows.value.reduce((s, r) => s + (metric.value === 'gex' ? Math.abs(r.put_gex_m) : r.put_oi), 0),
)

const gexRatio = computed(() => {
  const c = Math.abs(callTotal.value)
  const p = Math.abs(putTotal.value)
  if (p <= 1e-6) return c > 0 ? 'CALL DOM' : 'BALANCED'
  if (c <= 1e-6) return p > 0 ? 'PUT DOM' : 'BALANCED'
  const r = c / p
  if (r >= 1.2) return `${num(r, 1)}x CALL`
  if (r <= 0.83) return `${num(1 / r, 1)}x PUT`
  return 'BALANCED'
})

const maxCumulative = computed(() => {
  if (!orderedRows.value.length) return 1e-9
  let sum = 0
  let peak = 1e-9
  for (const r of orderedRows.value) {
    sum += (metric.value === 'gex' ? r.net_gex_m : r.call_oi - r.put_oi)
    if (Math.abs(sum) > peak) peak = Math.abs(sum)
  }
  return peak
})

function metricValue(value: number, signed = false): string {
  if (!Number.isFinite(value)) return DASH
  const sign = value > 0 ? (signed ? '+' : '') : value < 0 ? '-' : ''
  const abs = Math.abs(value)
  return metric.value === 'gex' ? `${sign}$${num(abs, 1)}M` : `${sign}${compact(abs)}`
}

function strikeLabel(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return DASH
  return num(value, Number.isInteger(value) ? 0 : 2)
}

function distanceLabel(strike: number): string {
  if (!props.spot || props.spot <= 0) return ''
  const diff = strike - props.spot
  const pct = (diff / props.spot) * 100
  const sign = diff >= 0 ? '+' : ''
  const side = diff > 0 ? 'OTM' : diff < 0 ? 'ITM' : 'ATM'
  return `${sign}$${num(Math.abs(diff), 2)} (${sign}${num(pct, 1)}% ${side})`
}

const bars = computed<Bar[]>(() => {
  let runningCum = 0
  const cumDenominator = maxCumulative.value || 1e-9

  return orderedRows.value.map((row, index) => {
    const isGex = metric.value === 'gex'
    const callVal = isGex ? row.call_gex_m : row.call_oi
    const putVal = isGex ? Math.abs(row.put_gex_m) : row.put_oi
    const net = isGex ? row.net_gex_m : row.call_oi - row.put_oi

    runningCum += net
    const cumNet = runningCum

    const callH = Math.max(callVal > 0 ? 2 : 0, (callVal / maxAbs.value) * halfPlotH.value)
    const putH = Math.max(putVal > 0 ? 2 : 0, (putVal / maxAbs.value) * halfPlotH.value)

    const callY = zeroY.value - callH
    const putY = zeroY.value
    const netY = zeroY.value - (net / maxAbs.value) * halfPlotH.value
    const netH = Math.max(2, (Math.abs(net) / maxAbs.value) * halfPlotH.value)
    const cumNetY = zeroY.value - (cumNet / cumDenominator) * halfPlotH.value

    const thickness = Math.max(4, Math.min(bandW.value * 0.72, 28))
    const cx = bandCenter(index)

    const isSpotNear = Math.abs(row.strike - props.spot) <= (bandW.value > 0 ? (props.spot * 0.01) : 0.5)
    const isCallWall = props.callWall != null && Math.abs(row.strike - props.callWall) < 0.01
    const isPutWall = props.putWall != null && Math.abs(row.strike - props.putWall) < 0.01
    const isFlip = props.gammaFlip != null && Math.abs(row.strike - props.gammaFlip) < 0.01

    return {
      ...row,
      net,
      callVal,
      putVal,
      callH,
      callY,
      putH,
      putY,
      netH,
      netY,
      cumNet,
      cumNetY,
      cx,
      thickness,
      isSpotNear,
      isCallWall,
      isPutWall,
      isFlip,
    }
  })
})

const focusBar = computed(() => {
  if (!bars.value.length) return null
  const target = hoverStrike.value ?? props.focusStrike ?? props.spot
  return bars.value.reduce((best, row) =>
    Math.abs(row.strike - target) < Math.abs(best.strike - target) ? row : best,
  )
})

function xOfPrice(price: number): number | null {
  const rows = orderedRows.value
  if (!rows.length) return null
  if (price <= rows[0].strike) return bandCenter(0)
  const lastIndex = rows.length - 1
  if (price >= rows[lastIndex].strike) return bandCenter(lastIndex)
  for (let i = 0; i < lastIndex; i++) {
    const lo = rows[i]
    const hi = rows[i + 1]
    if (price >= lo.strike && price <= hi.strike) {
      const span = hi.strike - lo.strike
      const t = span > 1e-9 ? (price - lo.strike) / span : 0
      return bandCenter(i + t)
    }
  }
  return null
}

const lockX = computed(() => (props.focusStrike != null ? xOfPrice(props.focusStrike) : null))
const flipX = computed(() => (props.gammaFlip != null ? xOfPrice(props.gammaFlip) : null))

const levels = computed<Level[]>(() => {
  const raw: { key: string; label: string; value: number | null; cls: string }[] = [
    { key: 'put', label: 'PUT W', value: props.putWall, cls: 'put' },
    { key: 'flip', label: 'FLIP', value: props.gammaFlip, cls: 'flip' },
    { key: 'spot', label: 'SPOT', value: props.spot, cls: 'spot' },
    { key: 'call', label: 'CALL W', value: props.callWall, cls: 'call' },
  ]
  const placed = raw
    .map((level) => ({ ...level, x: level.value != null ? xOfPrice(level.value) : null }))
    .filter((level): level is { key: string; label: string; value: number; cls: string; x: number } => level.x != null)
    .sort((a, b) => a.x - b.x)

  if (!placed.length) return []

  const minGap = 52
  const minBoundary = left + 28
  const maxBoundary = left + plotInnerW.value - 28

  // 1. Initial clamp to plot interior
  const xs = placed.map((l) => Math.max(minBoundary, Math.min(maxBoundary, l.x)))

  // 2. Forward pass (push right)
  for (let i = 1; i < xs.length; i++) {
    if (xs[i] < xs[i - 1] + minGap) {
      xs[i] = xs[i - 1] + minGap
    }
  }

  // 3. Backward pass (pull left if rightmost exceeds maxBoundary)
  if (xs[xs.length - 1] > maxBoundary) {
    xs[xs.length - 1] = maxBoundary
    for (let i = xs.length - 2; i >= 0; i--) {
      if (xs[i] > xs[i + 1] - minGap) {
        xs[i] = xs[i + 1] - minGap
      }
    }
  }

  // 4. Clamp check at left boundary
  if (xs[0] < minBoundary) {
    xs[0] = minBoundary
    for (let i = 1; i < xs.length; i++) {
      if (xs[i] < xs[i - 1] + minGap) {
        xs[i] = xs[i - 1] + minGap
      }
    }
  }

  // 5. Detect remaining congestion for vertical tier staggering
  const hasRemainingOverlap = xs.some((x, i) => i > 0 && Math.abs(x - xs[i - 1]) < 48)
  const isWidthConstrained = (maxBoundary - minBoundary) < (placed.length * minGap)

  return placed.map((level, i) => {
    const labelX = Math.max(minBoundary, Math.min(maxBoundary, xs[i]))
    // Stagger tier 0 (top + 10) vs tier 1 (top + 22) when congested
    const labelY = (hasRemainingOverlap || isWidthConstrained)
      ? (i % 2 === 0 ? top + 10 : top + 22)
      : top + 10

    return {
      ...level,
      labelX,
      labelY,
    }
  })
})

const netTracePath = computed(() => {
  if (bars.value.length <= 1) return ''
  return bars.value.map((b, i) => `${i === 0 ? 'M' : 'L'} ${b.cx.toFixed(1)} ${b.netY.toFixed(1)}`).join(' ')
})

const cumulativeAreaPath = computed(() => {
  if (bars.value.length <= 1) return ''
  const first = bars.value[0]
  const last = bars.value[bars.value.length - 1]
  const line = bars.value.map((b, i) => `${i === 0 ? 'M' : 'L'} ${b.cx.toFixed(1)} ${b.cumNetY.toFixed(1)}`).join(' ')
  return `${line} L ${last.cx.toFixed(1)} ${zeroY.value.toFixed(1)} L ${first.cx.toFixed(1)} ${zeroY.value.toFixed(1)} Z`
})

const cumulativeLinePath = computed(() => {
  if (bars.value.length <= 1) return ''
  return bars.value.map((b, i) => `${i === 0 ? 'M' : 'L'} ${b.cx.toFixed(1)} ${b.cumNetY.toFixed(1)}`).join(' ')
})

const tickCount = computed(() => (H.value < 220 ? 3 : 5))

const yTicks = computed(() => {
  if (!orderedRows.value.length) return []
  const maxVal = viewMode.value === 'cumulative' ? maxCumulative.value : maxAbs.value
  return niceTicks(-maxVal, maxVal, tickCount.value).map((value) => ({
    value,
    y: zeroY.value - (value / maxVal) * halfPlotH.value,
  }))
})

const strikeTicks = computed(() => {
  const rows = orderedRows.value
  const n = rows.length
  if (!n) return [] as { x: number; label: string; strike: number }[]
  const maxLabels = Math.min(n, Math.max(4, Math.floor(plotInnerW.value / 48)))
  const indices = new Set<number>()
  if (maxLabels <= 1) indices.add(0)
  else {
    for (let k = 0; k < maxLabels; k++) {
      indices.add(Math.round((k * (n - 1)) / (maxLabels - 1)))
    }
  }
  let nearest = 0
  let best = Infinity
  rows.forEach((r, i) => {
    const d = Math.abs(r.strike - props.spot)
    if (d < best) { best = d; nearest = i }
  })
  indices.add(nearest)
  return Array.from(indices)
    .sort((a, b) => a - b)
    .map((i) => ({ x: bandCenter(i), label: strikeLabel(rows[i].strike), strike: rows[i].strike }))
})

function barAriaLabel(bar: Bar): string {
  const callText = metric.value === 'gex' ? `call GEX ${metricValue(bar.call_gex_m)}` : `call OI ${compact(bar.call_oi)}`
  const putText = metric.value === 'gex' ? `put GEX ${metricValue(Math.abs(bar.put_gex_m))}` : `put OI ${compact(bar.put_oi)}`
  const netText = `net ${metricValue(bar.net, true)}`
  return `Strike $${strikeLabel(bar.strike)}. ${callText}, ${putText}, ${netText}.`
}

function jumpToLevel(strike: number | null): void {
  if (strike == null || !Number.isFinite(strike)) return
  const closest = orderedRows.value.reduce((best, row) =>
    Math.abs(row.strike - strike) < Math.abs(best.strike - strike) ? row : best,
    orderedRows.value[0],
  )
  if (closest) {
    lockStrike(closest.strike)
  }
}
</script>

<template>
  <div class="gex-map" @keydown.esc="clearLock">
    <!-- Top toolbar: metric switch, range scope, view mode, overlays & legend -->
    <div class="map-controls">
      <div class="control-group">
        <div class="mini-segment" role="group" aria-label="Metric selection">
          <button
            type="button"
            class="label"
            :class="{ on: metric === 'gex' }"
            @click="metric = 'gex'"
            title="Display Dollar Gamma Exposure ($M per 1% move)"
          >CALL & PUT GEX</button>
          <button
            type="button"
            class="label"
            :class="{ on: metric === 'oi' }"
            @click="metric = 'oi'"
            title="Display Open Interest in Contracts"
          >CALL & PUT OI</button>
        </div>
      </div>

      <div class="control-group">
        <div class="mini-segment" role="group" aria-label="Strike range preset">
          <button type="button" class="label" :class="{ on: strikeScope === 'atm' }" @click="strikeScope = 'atm'">ATM (±6%)</button>
          <button type="button" class="label" :class="{ on: strikeScope === 'near' }" @click="strikeScope = 'near'">NEAR (±12%)</button>
          <button type="button" class="label" :class="{ on: strikeScope === 'wide' }" @click="strikeScope = 'wide'">WIDE (±25%)</button>
          <button type="button" class="label" :class="{ on: strikeScope === 'all' }" @click="strikeScope = 'all'">ALL STRIKES</button>
        </div>
      </div>

      <div class="control-group">
        <div class="mini-segment" role="group" aria-label="View format">
          <button type="button" class="label" :class="{ on: viewMode === 'dual' }" @click="viewMode = 'dual'" title="Dual Call / Put Bars">DUAL BARS</button>
          <button type="button" class="label" :class="{ on: viewMode === 'net' }" @click="viewMode = 'net'" title="Single Net Exposure Bar per Strike">NET PROFILE</button>
          <button type="button" class="label" :class="{ on: viewMode === 'cumulative' }" @click="viewMode = 'cumulative'" title="Cumulative Hedge Requirement across Strikes">CUMULATIVE</button>
        </div>
      </div>

      <div class="control-group toggles">
        <button
          type="button"
          class="pill-toggle label"
          :class="{ active: showTrace }"
          @click="showTrace = !showTrace"
          title="Toggle Net Profile Trace Line"
        >
          NET TRACE
        </button>
        <button
          v-if="gammaFlip != null"
          type="button"
          class="pill-toggle label"
          :class="{ active: showRegimes }"
          @click="showRegimes = !showRegimes"
          title="Toggle Positive vs Negative Gamma Regime Zones"
        >
          REGIMES
        </button>
      </div>

      <div class="quick-levels" v-if="putWall != null || gammaFlip != null || spot || callWall != null">
        <span class="label quick-title">JUMP:</span>
        <button
          v-if="putWall != null"
          type="button"
          class="level-chip put label"
          @click="jumpToLevel(putWall)"
          title="Jump to Put Wall"
        >PUT W ${{ strikeLabel(putWall) }}</button>
        <button
          v-if="gammaFlip != null"
          type="button"
          class="level-chip flip label"
          @click="jumpToLevel(gammaFlip)"
          title="Jump to Gamma Flip"
        >FLIP ${{ strikeLabel(gammaFlip) }}</button>
        <button
          v-if="spot"
          type="button"
          class="level-chip spot label"
          @click="jumpToLevel(spot)"
          title="Jump to Spot"
        >SPOT ${{ strikeLabel(spot) }}</button>
        <button
          v-if="callWall != null"
          type="button"
          class="level-chip call label"
          @click="jumpToLevel(callWall)"
          title="Jump to Call Wall"
        >CALL W ${{ strikeLabel(callWall) }}</button>
      </div>

      <span class="coverage label">
        {{ bars.length }}/{{ rows.length }} STRIKES ·
        <span class="call-leg"><i class="leg-dot call" />CALL</span> ·
        <span class="put-leg"><i class="leg-dot put" />PUT</span> ·
        <span class="net-leg"><i class="leg-dot net" />NET</span>
      </span>
    </div>

    <!-- Aggregate HUD bar + Interactive Strike Inspector -->
    <div class="exposure-head">
      <div class="exposure-totals">
        <div class="exposure-total call">
          <span class="label">{{ metric === 'gex' ? 'CALL GEX' : 'CALL OI' }}</span>
          <strong class="fig">{{ metricValue(callTotal, true) }}</strong>
        </div>
        <div class="exposure-total put">
          <span class="label">{{ metric === 'gex' ? 'PUT GEX' : 'PUT OI' }}</span>
          <strong class="fig">{{ metricValue(putTotal) }}</strong>
        </div>
        <div class="exposure-total net" :class="totalNet >= 0 ? 'positive' : 'negative'">
          <span class="label">NET ({{ gexRatio }})</span>
          <strong class="fig">{{ metricValue(totalNet, true) }}</strong>
        </div>
      </div>

      <div v-if="focusBar" class="strike-focus" :class="{ locked: focusStrike != null }">
        <div class="focus-strike">
          <span class="label">
            {{ hoverStrike != null ? 'INSPECTING' : focusStrike != null ? 'LOCKED STRIKE' : 'NEAREST SPOT' }}
          </span>
          <strong class="fig">${{ strikeLabel(focusBar.strike) }}</strong>
          <small class="dist-tag">{{ distanceLabel(focusBar.strike) }}</small>
        </div>
        <div class="focus-metric call">
          <span class="label">CALL {{ metric === 'gex' ? 'GEX' : 'OI' }}</span>
          <strong class="fig">{{ metricValue(focusBar.callVal) }}</strong>
          <small>OI {{ compact(focusBar.call_oi) }}</small>
        </div>
        <div class="focus-metric put">
          <span class="label">PUT {{ metric === 'gex' ? 'GEX' : 'OI' }}</span>
          <strong class="fig">{{ metricValue(focusBar.putVal) }}</strong>
          <small>OI {{ compact(focusBar.put_oi) }}</small>
        </div>
        <div class="focus-metric net" :class="focusBar.net >= 0 ? 'positive' : 'negative'">
          <span class="label">NET {{ metric === 'gex' ? 'GEX' : 'OI' }}</span>
          <strong class="fig">{{ metricValue(focusBar.net, true) }}</strong>
          <small>
            <template v-if="focusBar.isCallWall">★ CALL WALL</template>
            <template v-else-if="focusBar.isPutWall">★ PUT WALL</template>
            <template v-else-if="focusBar.isFlip">◆ GAMMA FLIP</template>
            <template v-else-if="focusBar.isSpotNear">● ATM</template>
            <template v-else>click bar to lock</template>
          </small>
        </div>
        <button
          v-if="focusStrike != null"
          type="button"
          class="clear-lock label"
          @click="clearLock"
          title="Clear locked strike (Esc)"
        >CLEAR</button>
      </div>
    </div>

    <!-- Main Chart Area with SVG Viewbox -->
    <div
      ref="hostRef"
      class="plot-scroll"
      :class="{ scrollable }"
    >
      <svg
        :viewBox="`0 0 ${W} ${H}`"
        :style="{
          height: '100%',
          width: scrollable ? `${W}px` : '100%',
          minWidth: scrollable ? `${W}px` : '100%',
          display: 'block'
        }"
        preserveAspectRatio="none"
        role="img"
        aria-label="Call and Put gamma exposure by strike. Calls up, Puts down, Net indicator as circle."
      >
        <title>Call vs Put GEX by strike. Call GEX up, Put GEX down, Net as circle marker.</title>

        <!-- Base Plot Background Frame -->
        <rect
          class="plot-frame"
          :x="left"
          :y="top"
          :width="plotInnerW"
          :height="plotInnerH"
        />

        <!-- Optional Gamma Regime Zones Background Shading -->
        <g v-if="showRegimes && flipX != null && rows.length" class="regime-zones" aria-hidden="true">
          <!-- Negative Gamma Zone (Below Flip) -->
          <rect
            v-if="flipX > left"
            class="regime-zone neg"
            :x="left"
            :y="top"
            :width="Math.min(flipX - left, plotInnerW)"
            :height="plotInnerH"
          />
          <!-- Positive Gamma Zone (Above Flip) -->
          <rect
            v-if="flipX < left + plotInnerW"
            class="regime-zone pos"
            :x="Math.max(flipX, left)"
            :y="top"
            :width="Math.max(0, left + plotInnerW - Math.max(flipX, left))"
            :height="plotInnerH"
          />
          <text
            v-if="flipX > left + 70"
            :x="left + 8"
            :y="plotBottom - 6"
            class="regime-label neg"
          >SHORT GAMMA · VOLATILITY AMPLIFIED</text>
          <text
            v-if="flipX < left + plotInnerW - 70"
            :x="left + plotInnerW - 8"
            :y="top + 12"
            text-anchor="end"
            class="regime-label pos"
          >LONG GAMMA · VOLATILITY DAMPENED</text>
        </g>

        <!-- Y Grid Lines -->
        <g v-if="rows.length" class="grid">
          <line
            v-for="tick in yTicks"
            :key="`grid-${tick.value}`"
            :x1="left"
            :x2="left + plotInnerW"
            :y1="tick.y"
            :y2="tick.y"
            :class="{ zero: tick.value === 0 }"
          />
        </g>

        <!-- Zero Axis Baseline Tag -->
        <g v-if="rows.length" class="zero-baseline-group">
          <line
            :x1="left"
            :x2="left + plotInnerW"
            :y1="zeroY"
            :y2="zeroY"
            class="zero-baseline"
          />
        </g>

        <!-- Vertical Structural Levels (Put Wall, Flip, Spot, Call Wall) -->
        <g v-for="level in levels" :key="level.key" class="level" :class="level.cls">
          <line :x1="level.x" :x2="level.x" :y1="top" :y2="plotBottom" />
          <path
            v-if="Math.abs(level.labelX - level.x) > 3"
            :d="`M ${level.x} ${top} L ${level.labelX} ${level.labelY - 8}`"
            class="level-connector"
          />
          <text :x="level.labelX" :y="level.labelY" text-anchor="middle">
            {{ level.label }} ${{ strikeLabel(level.value) }}
          </text>
        </g>

        <!-- Hover / Focus Column Guide Beam -->
        <g v-if="focusBar" class="focus-beam" aria-hidden="true">
          <rect
            :x="focusBar.cx - bandW / 2"
            :y="top"
            :width="bandW"
            :height="plotInnerH"
            class="beam-rect"
          />
        </g>

        <!-- Focus Lock Marker Line -->
        <g v-if="focusStrike != null && lockX != null" class="level focus-lock">
          <line :x1="lockX!" :x2="lockX!" :y1="top" :y2="plotBottom" />
        </g>

        <!-- Cumulative Area / Line (when in cumulative viewMode) -->
        <g v-if="viewMode === 'cumulative' && rows.length" class="cumulative-group">
          <path class="cum-area" :d="cumulativeAreaPath" />
          <path class="cum-line" :d="cumulativeLinePath" />
        </g>

        <!-- STRIKE DATA BARS & INTERACTIVE TARGETS -->
        <g v-if="rows.length" class="bars">
          <g
            v-for="bar in bars"
            :key="bar.strike"
            class="strike-bar"
            :class="{
              active: focusBar?.strike === bar.strike,
              locked: focusStrike === bar.strike,
              'put-dominant': bar.putVal > bar.callVal * 1.15,
              'call-dominant': bar.callVal > bar.putVal * 1.15,
            }"
            tabindex="0"
            role="button"
            :aria-pressed="focusStrike === bar.strike"
            :aria-label="barAriaLabel(bar)"
            @mouseenter="hoverStrike = bar.strike"
            @mouseleave="hoverStrike = null"
            @focus="hoverStrike = bar.strike"
            @blur="hoverStrike = null"
            @click="lockStrike(bar.strike)"
            @keydown="onBarKeydown($event, bar.strike)"
          >
            <!-- Full column mouse hit area -->
            <rect
              class="hit"
              :x="bar.cx - bandW / 2"
              :y="top"
              :width="bandW"
              :height="plotInnerH"
            />

            <!-- DUAL BARS MODE: Call UP / Put DOWN -->
            <template v-if="viewMode === 'dual'">
              <!-- Call Bar (Call Blue, grows UP from zeroY) -->
              <rect
                v-if="bar.callH > 0"
                class="call-bar"
                :x="bar.cx - bar.thickness / 2"
                :y="bar.callY"
                :width="bar.thickness"
                :height="bar.callH"
              >
                <title>${{ strikeLabel(bar.strike) }} Call {{ metricValue(bar.callVal) }}</title>
              </rect>

              <!-- Put Bar (Put Amber, grows DOWN from zeroY) -->
              <rect
                v-if="bar.putH > 0"
                class="put-bar"
                :x="bar.cx - bar.thickness / 2"
                :y="bar.putY"
                :width="bar.thickness"
                :height="bar.putH"
              >
                <title>${{ strikeLabel(bar.strike) }} Put {{ metricValue(bar.putVal) }}</title>
              </rect>
            </template>

            <!-- NET PROFILE MODE: Single Net Bar per Strike -->
            <template v-else-if="viewMode === 'net'">
              <rect
                v-if="bar.netH > 0"
                :class="bar.net >= 0 ? 'call-bar' : 'put-bar'"
                :x="bar.cx - bar.thickness / 2"
                :y="bar.net >= 0 ? zeroY - bar.netH : zeroY"
                :width="bar.thickness"
                :height="bar.netH"
              >
                <title>${{ strikeLabel(bar.strike) }} Net {{ metricValue(bar.net, true) }}</title>
              </rect>
            </template>

            <!-- Net Indicator Circle Marker (Flat ink token) -->
            <circle
              v-if="viewMode !== 'cumulative'"
              class="net-dot"
              :cx="bar.cx"
              :cy="bar.netY"
              r="3.25"
            />
          </g>
        </g>

        <!-- Continuous Net Trace Polyline -->
        <g v-if="showTrace && viewMode !== 'cumulative' && rows.length" class="net-trace-group" aria-hidden="true">
          <path class="net-trace-path" :d="netTracePath" />
        </g>

        <!-- Y Axis Numbers & Metric Header -->
        <g v-if="rows.length" class="y-axis">
          <text
            v-for="tick in yTicks"
            :key="`yt-${tick.value}`"
            :x="left - 6"
            :y="tick.y + 3"
            text-anchor="end"
          >{{ tick.value === 0 ? '0' : metricValue(tick.value, true) }}</text>
        </g>
        <text
          v-if="rows.length"
          class="axis-cap"
          :x="left"
          :y="top - 6"
        >
          {{
            viewMode === 'cumulative'
              ? (metric === 'gex' ? 'CUMULATIVE NET GEX $M' : 'CUMULATIVE NET OI')
              : (metric === 'gex' ? 'GEX $M · CALL UP / PUT DN' : 'OI · CALL UP / PUT DN')
          }}
        </text>

        <!-- X Axis Strikes & Tick Marks -->
        <g v-if="rows.length" class="x-axis">
          <template v-for="tick in strikeTicks" :key="`st-${tick.strike}`">
            <line :x1="tick.x" :x2="tick.x" :y1="plotBottom" :y2="plotBottom + 4" />
            <text :x="tick.x" :y="H - 6" text-anchor="middle">${{ tick.label }}</text>
          </template>
        </g>

        <!-- Empty State Viewfinder -->
        <g v-if="!rows.length" class="empty-group">
          <rect
            :x="W / 2 - 140"
            :y="H / 2 - 24"
            width="280"
            height="48"
            class="empty-frame"
          />
          <text :x="W / 2" :y="H / 2 + 4" text-anchor="middle" class="empty">
            NO QUALIFYING GAMMA OBSERVATIONS
          </text>
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.gex-map {
  width: 100%;
  max-width: 100%;
  height: 100%;
  max-height: 100%;
  box-sizing: border-box;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  gap: 6px;
  background: var(--panel);
  padding: 6px 10px 8px;
}

.map-controls {
  display: flex;
  align-items: center;
  gap: 4px 6px;
  margin: 0;
  flex: 0 0 auto;
  flex-wrap: wrap;
  min-width: 0;
  max-width: 100%;
}

.control-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.mini-segment {
  display: flex;
  min-height: 22px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void);
  overflow: hidden;
}

.mini-segment button {
  padding: 0 7px;
  color: var(--ink-dim);
  border-right: var(--hair) solid var(--rule);
  font: 600 9px var(--font-display);
  letter-spacing: 0.04em;
  min-height: 22px;
  cursor: pointer;
  background: transparent;
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}

.mini-segment button:last-child {
  border-right: 0;
}

.mini-segment button:hover {
  color: var(--ink);
  background: var(--panel-hi);
}

.mini-segment button.on {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  box-shadow: inset 0 -2px var(--phosphor);
}

.pill-toggle {
  padding: 1px 6px;
  min-height: 22px;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule-hi);
  background: var(--void);
  font: 600 8.5px var(--font-display);
  letter-spacing: 0.05em;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.pill-toggle:hover {
  color: var(--ink);
  background: var(--panel-hi);
}

.pill-toggle.active {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.quick-levels {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--void);
  padding: 2px 5px;
  border: var(--hair) solid var(--rule);
  flex-wrap: wrap;
}

.quick-title {
  color: var(--ink-ghost);
  font: 700 8px var(--font-display);
  letter-spacing: 0.06em;
}

.level-chip {
  padding: 1px 5px;
  font: 700 8.5px var(--font-display);
  letter-spacing: 0.03em;
  cursor: pointer;
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
  transition: all var(--dur-fast) var(--ease-out);
  white-space: nowrap;
}

.level-chip:hover {
  background: var(--panel-hi);
}

.level-chip.put { color: var(--put-hi); border-color: var(--put); }
.level-chip.call { color: var(--call-hi); border-color: var(--call); }
.level-chip.flip { color: var(--warn); border-color: var(--warn); }
.level-chip.spot { color: var(--ink); border-color: var(--ink-dim); }

.coverage {
  margin-left: auto;
  color: var(--ink-dim);
  font: 500 9.5px var(--font-data);
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}

.coverage .call-leg,
.coverage .put-leg,
.coverage .net-leg {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-weight: 700;
}

.coverage .call-leg { color: var(--call-hi); }
.coverage .put-leg { color: var(--put-hi); }
.coverage .net-leg { color: var(--ink-soft); }

.leg-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: 0 0 auto;
}

.leg-dot.call { background: var(--call); }
.leg-dot.put { background: var(--put); }
.leg-dot.net {
  background: var(--ink);
  border: 1px solid var(--void);
  box-shadow: 0 0 0 1px var(--rule-hi);
}

.exposure-head {
  display: flex;
  flex-wrap: wrap;
  gap: 1px;
  flex: 0 0 auto;
  background: var(--rule);
  border: var(--hair) solid var(--rule-hi);
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}

.exposure-totals {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  flex: 1 1 240px;
  min-width: 0;
  background: var(--rule);
}

.exposure-total {
  min-width: 0;
  min-height: 36px;
  padding: 4px 8px;
  background: var(--void-lift);
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  position: relative;
  overflow: hidden;
}

.exposure-total::after {
  content: '';
  position: absolute;
  inset: auto 0 0;
  height: 2px;
  background: currentColor;
}

.exposure-total .label {
  color: var(--ink-dim);
  font: 700 8.5px var(--font-display);
  letter-spacing: 0.05em;
  flex: 0 0 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.exposure-total strong {
  font: 700 0.875rem var(--font-data);
  line-height: 1.15;
  color: inherit;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: right;
}

.exposure-total.call { color: var(--call-hi); }
.exposure-total.put { color: var(--put-hi); }
.exposure-total.net { color: var(--phosphor); }
.exposure-total.net.negative { color: var(--put-hi); }

.strike-focus {
  display: grid;
  grid-template-columns: minmax(80px, 0.9fr) repeat(3, minmax(64px, 1fr)) auto;
  align-items: center;
  gap: 6px;
  background: var(--panel-raise);
  padding: 4px 8px;
  flex: 1.2 1 300px;
  min-width: 0;
  overflow: hidden;
}

.focus-strike, .focus-metric {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 1px;
  overflow: hidden;
}

.focus-strike > .label,
.focus-metric > .label {
  color: var(--phosphor);
  font: 700 8px var(--font-display);
  letter-spacing: 0.06em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.focus-strike > strong {
  font: 700 0.875rem var(--font-data);
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dist-tag {
  color: var(--ink-dim);
  font: 500 7.5px var(--font-data);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.focus-metric strong {
  overflow: hidden;
  font: 700 10.5px var(--font-data);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.focus-metric small {
  color: var(--ink-ghost);
  font: 500 8px var(--font-data);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.focus-metric.call strong { color: var(--call-hi); }
.focus-metric.put strong { color: var(--put-hi); }
.focus-metric.net.positive strong { color: var(--call-hi); }
.focus-metric.net.negative strong { color: var(--put-hi); }

.plot-scroll {
  position: relative;
  overflow-x: auto;
  overflow-y: hidden;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  border: var(--hair) solid var(--rule-hi);
  flex: 1 1 0;
  min-height: 0;
  background: var(--void);
}

svg {
  display: block;
  background: var(--void);
  overflow: visible;
}

.plot-frame {
  fill: var(--void-lift);
  stroke: var(--rule-hi);
  stroke-width: 1;
}

.regime-zone.neg {
  fill: rgba(193, 149, 94, 0.04);
}

.regime-zone.pos {
  fill: rgba(91, 149, 181, 0.04);
}

.regime-label {
  font: 700 8px var(--font-display);
  letter-spacing: 0.08em;
  pointer-events: none;
}

.regime-label.neg {
  fill: var(--put);
  opacity: 0.65;
}

.regime-label.pos {
  fill: var(--call);
  opacity: 0.65;
}

.grid line {
  stroke: var(--rule-hi);
  stroke-width: 1;
  opacity: 0.4;
  vector-effect: non-scaling-stroke;
}

.grid line.zero {
  stroke: var(--ink-dim);
  stroke-width: 1.5;
  opacity: 0.9;
}

.zero-baseline {
  stroke: var(--ink-dim);
  stroke-width: 1.25;
  stroke-dasharray: 2 2;
  opacity: 0.6;
  vector-effect: non-scaling-stroke;
}

.y-axis text, .x-axis text {
  fill: var(--ink-dim);
  font: 600 9.5px var(--font-data);
  letter-spacing: 0.02em;
}

.x-axis line {
  stroke: var(--rule-hi);
  vector-effect: non-scaling-stroke;
}

.axis-cap {
  fill: var(--ink-dim);
  font: 700 9px var(--font-display);
  letter-spacing: 0.08em;
}

.strike-bar {
  cursor: pointer;
}

.strike-bar:focus-visible {
  outline: var(--hair) solid var(--phosphor);
  outline-offset: 2px;
}

.strike-bar:focus-visible .hit,
.strike-bar:focus .hit {
  stroke: var(--phosphor);
  stroke-width: 1;
}

.strike-bar .hit {
  fill: transparent;
  pointer-events: all;
}

.focus-beam .beam-rect {
  fill: var(--phosphor-wash);
  stroke: var(--phosphor-dim);
  stroke-width: 1;
  stroke-dasharray: 2 2;
  pointer-events: none;
}

/* Flat call/put fills — same palette as flow momentum dots */
.strike-bar .call-bar,
.strike-bar .put-bar {
  vector-effect: non-scaling-stroke;
  stroke-width: 0.5;
  opacity: 0.92;
  transition: opacity var(--dur-fast) var(--ease-out), stroke-width var(--dur-fast) var(--ease-out);
}

.strike-bar .call-bar { fill: var(--call); stroke: var(--call-hi); }
.strike-bar .put-bar { fill: var(--put); stroke: var(--put-hi); }

.strike-bar.call-dominant .call-bar {
  fill: var(--call-hi);
  stroke: var(--call-hi);
  opacity: 1;
}

.strike-bar.put-dominant .put-bar {
  fill: var(--put-hi);
  stroke: var(--put-hi);
  opacity: 1;
}

.strike-bar .net-dot {
  fill: var(--ink);
  stroke: var(--void);
  stroke-width: 1.25px;
}

.strike-bar:hover .call-bar,
.strike-bar.active .call-bar,
.strike-bar:hover .put-bar,
.strike-bar.active .put-bar {
  opacity: 1;
  stroke-width: 1.25;
}

.strike-bar.locked .call-bar,
.strike-bar.locked .put-bar {
  opacity: 1;
  stroke-width: 1.5;
}

.strike-bar.locked .net-dot {
  fill: var(--phosphor);
  stroke: var(--void);
  stroke-width: 1.5;
}

.net-trace-path {
  fill: none;
  stroke: var(--ink);
  stroke-width: 1.5;
  stroke-dasharray: 3 3;
  opacity: 0.75;
  pointer-events: none;
  vector-effect: non-scaling-stroke;
}

.cumulative-group .cum-area {
  fill: var(--phosphor-wash);
  opacity: 0.6;
  pointer-events: none;
}

.cumulative-group .cum-line {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1.75;
  pointer-events: none;
  vector-effect: non-scaling-stroke;
}

.focus-lock line {
  stroke: var(--phosphor);
  stroke-width: 1.5;
  stroke-dasharray: 3 3;
  vector-effect: non-scaling-stroke;
}

.clear-lock {
  margin-left: 2px;
  padding: 2px 5px;
  min-height: 18px;
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  cursor: pointer;
  font: 700 8.5px var(--font-display);
}

.clear-lock:hover {
  color: var(--void);
  background: var(--phosphor);
}

.level line {
  stroke-width: 1.25;
  stroke-dasharray: 4 4;
  vector-effect: non-scaling-stroke;
  opacity: 0.95;
}

.level.call line { stroke: var(--call); }
.level.put line { stroke: var(--put); }
.level.spot line {
  stroke: var(--ink);
  stroke-dasharray: none;
  stroke-width: 1.5;
  opacity: 0.85;
}
.level.flip line { stroke: var(--warn); }

.level-connector {
  fill: none;
  stroke: var(--rule-hi);
  stroke-width: 1;
  stroke-dasharray: 2 2;
  opacity: 0.7;
  pointer-events: none;
}
.level.call .level-connector { stroke: var(--call-hi); }
.level.put .level-connector { stroke: var(--put-hi); }
.level.spot .level-connector { stroke: var(--ink-dim); }
.level.flip .level-connector { stroke: var(--warn); }

.level text {
  font: 700 8.5px var(--font-display);
  paint-order: stroke;
  stroke: var(--void);
  stroke-width: 3px;
  stroke-linejoin: round;
  letter-spacing: 0.04em;
}

.level.call text { fill: var(--call-hi); }
.level.put text { fill: var(--put-hi); }
.level.spot text { fill: var(--ink); }
.level.flip text { fill: var(--warn); }

.empty-frame {
  fill: var(--void);
  stroke: var(--rule-hi);
  stroke-width: 1;
}

.empty {
  fill: var(--ink-dim);
  font: 600 11px var(--font-display);
  letter-spacing: 0.08em;
}

@media (max-width: 900px) {
  .coverage {
    width: 100%;
    margin-left: 0;
  }
  .exposure-totals {
    flex: 1 1 100%;
  }
  .strike-focus {
    flex: 1 1 100%;
  }
}

@media (max-width: 620px) {
  .strike-focus {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .clear-lock {
    justify-self: start;
  }
}
</style>
