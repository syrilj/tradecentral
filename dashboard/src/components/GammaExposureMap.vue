<script setup lang="ts">
/**
 * Net-GEX & Call/Put Strike Profile — vertical dual bars across the wide desk.
 *
 *   · X axis = strike (low → high, left → right)
 *   · Call GEX / Call OI = positive call-blue bar ABOVE zero line
 *   · Put GEX / Put OI = negative put-amber bar BELOW zero line
 *   · Net GEX / Net OI = ink circle marker on top
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
  netY: number
  cx: number
  thickness: number
}

interface Level {
  key: string
  label: string
  value: number
  cls: string
  x: number
  labelX: number
}

const props = withDefaults(defineProps<{
  rows: GexStrikeRow[]
  spot: number
  callWall: number | null
  putWall: number | null
  gammaFlip: number | null
  focusStrike?: number | null
  maxHeight?: number
}>(), { maxHeight: 380, focusStrike: null })

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
  if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return
  e.preventDefault()
  lockStrike(strike)
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
const { W: hostW, H } = useChartSize(hostRef, {
  minW: 240,
  minH: 240,
  fallbackW: 900,
  fallbackH: props.maxHeight,
})

const left = 52
const right = 24
const top = 34
const bottom = 40
const minCol = 14

const hoverStrike = ref<number | null>(null)
const strikeScope = ref<'near' | 'all'>('near')
const metric = ref<'gex' | 'oi'>('gex')

const visible = computed(() => {
  if (!props.rows.length) return []
  if (strikeScope.value === 'all') return props.rows
  const near = props.rows.filter((r) => r.strike >= props.spot * 0.88 && r.strike <= props.spot * 1.12)
  return near.length >= 8 ? near : props.rows
})

const orderedRows = computed(() => [...visible.value].sort((a, b) => a.strike - b.strike))
const colCount = computed(() => Math.max(orderedRows.value.length, 1))

const plotInnerH = computed(() => Math.max(80, H.value - top - bottom))
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

const bars = computed<Bar[]>(() =>
  orderedRows.value.map((row, index) => {
    const isGex = metric.value === 'gex'
    const callVal = isGex ? row.call_gex_m : row.call_oi
    const putVal = isGex ? Math.abs(row.put_gex_m) : row.put_oi
    const net = isGex ? row.net_gex_m : row.call_oi - row.put_oi

    const callH = Math.max(callVal > 0 ? 2 : 0, (callVal / maxAbs.value) * halfPlotH.value)
    const putH = Math.max(putVal > 0 ? 2 : 0, (putVal / maxAbs.value) * halfPlotH.value)

    const callY = zeroY.value - callH
    const putY = zeroY.value
    const netY = zeroY.value - (net / maxAbs.value) * halfPlotH.value

    const thickness = Math.max(4, Math.min(bandW.value * 0.72, 28))
    const cx = bandCenter(index)

    return {
      ...row,
      net,
      callVal,
      putVal,
      callH,
      callY,
      putH,
      putY,
      netY,
      cx,
      thickness,
    }
  }),
)

const focusBar = computed(() => {
  if (!bars.value.length) return null
  const target = hoverStrike.value ?? props.focusStrike ?? props.spot
  return bars.value.reduce((best, row) =>
    Math.abs(row.strike - target) < Math.abs(best.strike - target) ? row : best,
  )
})

const hoverBreakdown = computed(() => {
  if (!focusBar.value) return null
  const fb = focusBar.value
  const callVal = fb.callVal
  const putVal = fb.putVal
  const total = callVal + putVal
  const callPct = total > 0 ? (callVal / total) * 100 : 50
  const putPct = total > 0 ? (putVal / total) * 100 : 50
  const isPutDominant = putVal > callVal * 1.15
  const isCallDominant = callVal > putVal * 1.15

  const sumVal = bars.value.reduce((s, b) => s + b.callVal + b.putVal, 0)
  const avg = sumVal / Math.max(1, bars.value.length * 2)
  const callOverflow = avg > 0 ? callVal / avg : 0
  const putOverflow = avg > 0 ? putVal / avg : 0

  let overflowLabel = ''
  if (callOverflow >= 1.5) overflowLabel = `CALL OVERFLOW ${callOverflow.toFixed(1)}x`
  else if (putOverflow >= 1.5) overflowLabel = `PUT OVERFLOW ${putOverflow.toFixed(1)}x`

  return {
    strike: fb.strike,
    callVal,
    putVal,
    net: fb.net,
    callOi: fb.call_oi,
    putOi: fb.put_oi,
    callGex: fb.call_gex_m,
    putGex: Math.abs(fb.put_gex_m),
    total,
    callPct,
    putPct,
    isPutDominant,
    isCallDominant,
    overflowLabel,
    cx: fb.cx,
  }
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

  let lastLabelX = -Infinity
  const minGap = 54
  const minBoundary = left + 40
  const maxBoundary = left + plotInnerW.value - 40

  return placed.map((level) => {
    let desired = Math.max(minBoundary, Math.min(maxBoundary, level.x))
    if (desired < lastLabelX + minGap) {
      desired = Math.min(maxBoundary, lastLabelX + minGap)
    }
    lastLabelX = desired
    return { ...level, labelX: desired }
  })
})

const tickCount = computed(() => (H.value < 220 ? 3 : 5))

const yTicks = computed(() => {
  if (!orderedRows.value.length) return []
  return niceTicks(-maxAbs.value, maxAbs.value, tickCount.value).map((value) => ({
    value,
    y: zeroY.value - (value / maxAbs.value) * halfPlotH.value,
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
</script>

<template>
  <div class="gex-map">
    <div class="map-controls">
      <div class="control-group">
        <div class="mini-segment">
          <button class="label" :class="{ on: metric === 'gex' }" @click="metric = 'gex'">CALL & PUT GEX</button>
          <button class="label" :class="{ on: metric === 'oi' }" @click="metric = 'oi'">CALL & PUT OI</button>
        </div>
      </div>
      <div class="control-group">
        <div class="mini-segment">
          <button class="label" :class="{ on: strikeScope === 'near' }" @click="strikeScope = 'near'">NEAR (±12%)</button>
          <button class="label" :class="{ on: strikeScope === 'all' }" @click="strikeScope = 'all'">ALL STRIKES</button>
        </div>
      </div>
      <span class="coverage label">
        {{ bars.length }}/{{ rows.length }} STRIKES ·
        <span class="call-leg"><i class="leg-dot call" />CALL</span> ·
        <span class="put-leg"><i class="leg-dot put" />PUT</span> ·
        <span class="net-leg"><i class="leg-dot net" />NET</span>
      </span>
    </div>

    <div class="exposure-head">
      <div class="exposure-total call">
        <span class="label">{{ metric === 'gex' ? 'CALL GEX' : 'CALL OI' }}</span>
        <strong class="fig">{{ metricValue(callTotal, true) }}</strong>
      </div>
      <div class="exposure-total put">
        <span class="label">{{ metric === 'gex' ? 'PUT GEX' : 'PUT OI' }}</span>
        <strong class="fig">{{ metricValue(putTotal) }}</strong>
      </div>
      <div class="exposure-total net" :class="totalNet >= 0 ? 'positive' : 'negative'">
        <span class="label">NET TOTAL</span>
        <strong class="fig">{{ metricValue(totalNet, true) }}</strong>
      </div>
      <div v-if="focusBar" class="strike-focus">
        <span class="label">
          {{
            hoverStrike != null ? 'HOVER'
              : focusStrike != null ? 'LOCKED'
                : 'SPOT'
          }}
        </span>
        <strong class="fig">${{ strikeLabel(focusBar.strike) }}</strong>
        <div class="focus-split">
          <span class="pos">C {{ metric === 'gex' ? metricValue(focusBar.call_gex_m) : compact(focusBar.call_oi) }}</span>
          <span class="neg">P {{ metric === 'gex' ? metricValue(Math.abs(focusBar.put_gex_m)) : compact(focusBar.put_oi) }}</span>
          <span class="net-tag" :class="focusBar.net >= 0 ? 'pos' : 'neg'">NET {{ metricValue(focusBar.net, true) }}</span>
          <button
            v-if="focusStrike != null"
            type="button"
            class="clear-lock label"
            @click="clearLock"
          >CLR</button>
        </div>
      </div>
    </div>

    <div
      ref="hostRef"
      class="plot-scroll"
      :class="{ scrollable }"
    >
      <!-- Hover breakdown card print overlay -->
      <div
        v-if="hoverBreakdown"
        class="strike-hover-card"
        :class="{ 'put-dom': hoverBreakdown.isPutDominant, 'call-dom': hoverBreakdown.isCallDominant }"
      >
        <div class="card-hdr">
          <span class="card-strike">${{ strikeLabel(hoverBreakdown.strike) }}</span>
          <span v-if="hoverBreakdown.overflowLabel" class="overflow-badge">{{ hoverBreakdown.overflowLabel }}</span>
          <span
            class="dom-badge label"
            :class="hoverBreakdown.isPutDominant ? 'put' : hoverBreakdown.isCallDominant ? 'call' : 'neutral'"
          >
            {{ hoverBreakdown.isPutDominant ? `${hoverBreakdown.putPct.toFixed(0)}% PUT DOMINANCE` : hoverBreakdown.isCallDominant ? `${hoverBreakdown.callPct.toFixed(0)}% CALL DOMINANCE` : 'BALANCED' }}
          </span>
        </div>
        <div class="card-grid">
          <div class="card-col call">
            <span class="label">CALL GEX</span>
            <strong class="fig">${{ num(hoverBreakdown.callGex, 2) }}M</strong>
            <span class="sub">OI {{ compact(hoverBreakdown.callOi) }}</span>
          </div>
          <div class="card-col put">
            <span class="label">PUT GEX</span>
            <strong class="fig">${{ num(hoverBreakdown.putGex, 2) }}M</strong>
            <span class="sub">OI {{ compact(hoverBreakdown.putOi) }}</span>
          </div>
          <div class="card-col net">
            <span class="label">NET GEX</span>
            <strong class="fig" :class="hoverBreakdown.net >= 0 ? 'call' : 'put'">
              {{ hoverBreakdown.net >= 0 ? '+' : '' }}${{ num(hoverBreakdown.net, 2) }}M
            </strong>
            <span class="sub">TOTAL {{ hoverBreakdown.callPct.toFixed(0) }}% / {{ hoverBreakdown.putPct.toFixed(0) }}%</span>
          </div>
        </div>
        <div class="card-bar">
          <i class="bar-call" :style="{ width: `${hoverBreakdown.callPct}%` }" />
          <i class="bar-put" :style="{ width: `${hoverBreakdown.putPct}%` }" />
        </div>
      </div>

      <svg
        :viewBox="`0 0 ${W} ${H}`"
        :style="{ height: `${H}px`, width: `${W}px`, minWidth: '100%' }"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Call and Put gamma exposure by strike. Calls up, Puts down, Net indicator as circle."
      >
        <title>Call vs Put GEX by strike. Call GEX up, Put GEX down, Net as circle marker.</title>

        <rect
          class="plot-frame"
          :x="left"
          :y="top"
          :width="plotInnerW"
          :height="plotInnerH"
        />

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

        <!-- wall / flip / spot vertical guides -->
        <g v-for="level in levels" :key="level.key" class="level" :class="level.cls">
          <line :x1="level.x" :x2="level.x" :y1="top" :y2="plotBottom" />
          <text :x="level.labelX" :y="top + 11" text-anchor="middle">{{ level.label }} ${{ strikeLabel(level.value) }}</text>
        </g>

        <g v-if="focusStrike != null && lockX != null" class="level focus-lock">
          <line :x1="lockX!" :x2="lockX!" :y1="top" :y2="plotBottom" />
        </g>

        <!-- DUAL BARS: Call GEX (UP / VIBRANT GREEN) & Put GEX (DOWN / VIBRANT RED) + Net Dot -->
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

            <!-- Call GEX bar (flow call-blue, grows UP from zeroY) -->
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

            <!-- Put GEX bar (flow put-amber, grows DOWN from zeroY) -->
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

            <!-- Net GEX marker circle (same language as flow side-dots) -->
            <circle
              class="net-dot"
              :cx="bar.cx"
              :cy="bar.netY"
              r="3.25"
            />
          </g>
        </g>

        <!-- Y axis ($M) -->
        <g v-if="rows.length" class="y-axis">
          <text
            v-for="tick in yTicks"
            :key="`yt-${tick.value}`"
            :x="left - 6"
            :y="tick.y + 3"
            text-anchor="end"
          >{{ tick.value === 0 ? '0' : metricValue(tick.value, true) }}</text>
        </g>
        <text v-if="rows.length" class="axis-cap" :x="left" :y="top - 6">{{ metric === 'gex' ? 'GEX $M · CALL UP / PUT DN' : 'OI · CALL UP / PUT DN' }}</text>

        <!-- X axis (strikes) -->
        <g v-if="rows.length" class="x-axis">
          <template v-for="tick in strikeTicks" :key="`st-${tick.strike}`">
            <line :x1="tick.x" :x2="tick.x" :y1="plotBottom" :y2="plotBottom + 4" />
            <text :x="tick.x" :y="H - 8" text-anchor="middle">${{ tick.label }}</text>
          </template>
        </g>

        <text v-if="!rows.length" :x="W / 2" :y="H / 2" text-anchor="middle" class="empty">NO QUALIFYING GAMMA OBSERVATIONS</text>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.gex-map {
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  gap: var(--s3);
  background: var(--panel);
  padding: var(--s2) var(--s3) var(--s3);
}
.map-controls {
  display: flex;
  align-items: center;
  gap: var(--s2);
  margin: 0;
  min-height: 28px;
  flex: 0 0 auto;
  flex-wrap: wrap;
}
.control-group { display: flex; align-items: center; gap: 6px; }
.mini-segment {
  display: flex;
  min-height: 26px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void);
  overflow: hidden;
}
.mini-segment button {
  padding: 0 10px;
  color: var(--ink-dim);
  border-right: var(--hair) solid var(--rule);
  font: 600 10px var(--font-display);
  letter-spacing: 0.05em;
  min-height: 26px;
  cursor: pointer;
  background: transparent;
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.mini-segment button:last-child { border-right: 0; }
.mini-segment button:hover { color: var(--ink); background: var(--panel-hi); }
.mini-segment button.on {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  box-shadow: inset 0 -2px var(--phosphor);
}
.coverage {
  margin-left: auto;
  color: var(--ink-dim);
  font: 500 10px var(--font-data);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.coverage .call-leg,
.coverage .put-leg,
.coverage .net-leg {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 700;
}
.coverage .call-leg { color: var(--call-hi); }
.coverage .put-leg { color: var(--put-hi); }
.coverage .net-leg { color: var(--ink-soft); }
.leg-dot {
  width: 7px;
  height: 7px;
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
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)) minmax(0, 1.8fr);
  gap: 1px;
  flex: 0 0 auto;
  background: var(--rule);
  border: var(--hair) solid var(--rule-hi);
  overflow: hidden;
}
.exposure-total, .strike-focus {
  min-width: 0;
  min-height: 40px;
  padding: 8px 10px;
  background: var(--void-lift);
}
.exposure-total {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  position: relative;
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
  font: 700 9px var(--font-display);
  letter-spacing: 0.06em;
  flex: 0 0 auto;
}
.exposure-total strong {
  font: 700 0.9375rem var(--font-data);
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  background: var(--panel-raise);
  padding: 8px 12px;
}
.strike-focus > .label {
  color: var(--phosphor);
  font: 700 9px var(--font-display);
  letter-spacing: 0.08em;
}
.strike-focus > strong {
  font: 700 1rem var(--font-data);
  color: var(--ink);
  white-space: nowrap;
}
.focus-split {
  display: flex;
  align-items: center;
  gap: 10px;
  font: 600 10px var(--font-data);
}
.focus-split .pos { color: var(--call-hi); }
.focus-split .neg { color: var(--put-hi); }
.focus-split .net-tag.pos { color: var(--call-hi); }
.focus-split .net-tag.neg { color: var(--put-hi); }

.plot-scroll {
  position: relative;
  overflow-x: auto;
  overflow-y: hidden;
  width: 100%;
  min-width: 0;
  border: var(--hair) solid var(--rule-hi);
  flex: 1 1 auto;
  min-height: 280px;
  background: var(--void);
}

/* Hover breakdown card */
.strike-hover-card {
  position: absolute;
  top: var(--s2);
  right: var(--s2);
  z-index: 15;
  width: 248px;
  padding: 10px 12px;
  background: color-mix(in srgb, var(--void) 94%, transparent);
  border: var(--hair) solid var(--rule-hi);
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}
.strike-hover-card.call-dom { border-color: color-mix(in srgb, var(--call) 55%, var(--rule)); }
.strike-hover-card.put-dom { border-color: color-mix(in srgb, var(--put) 55%, var(--rule)); }
.card-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  flex-wrap: wrap;
}
.card-strike {
  font: 700 14px var(--font-data);
  color: var(--ink);
}
.overflow-badge {
  font: 700 9px var(--font-display);
  color: var(--warn);
  background: var(--warn-wash);
  border: var(--hair) solid color-mix(in srgb, var(--warn) 50%, var(--rule));
  padding: 1px 5px;
}
.dom-badge {
  font: 700 9px var(--font-display);
  padding: 2px 6px;
}
.dom-badge.call {
  color: var(--call-hi);
  background: var(--call-wash);
  border: var(--hair) solid color-mix(in srgb, var(--call) 45%, var(--rule));
}
.dom-badge.put {
  color: var(--put-hi);
  background: var(--put-wash);
  border: var(--hair) solid color-mix(in srgb, var(--put) 45%, var(--rule));
}
.dom-badge.neutral {
  color: var(--ink-dim);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.card-col {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.card-col .label { font: 700 8px var(--font-display); color: var(--ink-dim); }
.card-col .fig { font: 700 11px var(--font-data); color: var(--ink); }
.card-col.call .fig { color: var(--call-hi); }
.card-col.put .fig { color: var(--put-hi); }
.card-col.net .fig.call { color: var(--call-hi); }
.card-col.net .fig.put { color: var(--put-hi); }
.card-col .sub { font: 500 9px var(--font-data); color: var(--ink-faint); }
.card-bar {
  display: flex;
  height: 4px;
  overflow: hidden;
  background: var(--rule);
}
.bar-call { background: var(--call); height: 100%; }
.bar-put { background: var(--put); height: 100%; }

svg { display: block; background: var(--void); overflow: visible; }
.plot-frame {
  fill: var(--void-lift);
  stroke: var(--rule-hi);
  stroke-width: 1;
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
.y-axis text, .x-axis text {
  fill: var(--ink-dim);
  font: 600 10px var(--font-data);
  letter-spacing: 0.02em;
}
.x-axis line { stroke: var(--rule-hi); vector-effect: non-scaling-stroke; }
.axis-cap {
  fill: var(--ink-dim);
  font: 700 10px var(--font-display);
  letter-spacing: 0.08em;
}

.strike-bar { cursor: pointer; }
.strike-bar .hit { fill: transparent; pointer-events: all; }

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

.focus-lock line {
  stroke: var(--phosphor);
  stroke-width: 1.5;
  stroke-dasharray: 3 3;
  vector-effect: non-scaling-stroke;
}
.clear-lock {
  margin-left: 4px;
  padding: 2px 6px;
  min-height: 20px;
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  cursor: pointer;
  font: 700 9px var(--font-display);
}
.clear-lock:hover { color: var(--void); background: var(--phosphor); }

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
.level text {
  font: 700 9px var(--font-display);
  paint-order: stroke;
  stroke: var(--void);
  stroke-width: 3px;
  stroke-linejoin: round;
  letter-spacing: 0.05em;
}
.level.call text { fill: var(--call-hi); }
.level.put text { fill: var(--put-hi); }
.level.spot text { fill: var(--ink); }
.level.flip text { fill: var(--warn); }
.empty {
  fill: var(--ink-dim);
  font: 600 12px var(--font-display);
  letter-spacing: 0.1em;
}

@media (max-width: 900px) {
  .coverage { width: 100%; margin-left: 0; }
  .exposure-head { grid-template-columns: repeat(2, 1fr); }
  .strike-focus { grid-column: 1 / -1; }
}
</style>
