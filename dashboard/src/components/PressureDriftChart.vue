<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import type { CharmStrikeRow } from '@/api'
import { linearScale, linePath, niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'
import { compact, num } from '@/format'

/**
 * Charm flow by strike — the time-decay pressure chart.
 *
 * Charm = ∂Δ/∂t (delta decay per day). Charm flow = charm × OI × 100, the
 * shares/day dealers must trade to stay delta-hedged purely from time decay.
 * Dealer sign convention (calls +, puts −):
 *
 *   · TOP HALF    — positive net charm flow → dealers sell to stay neutral
 *                   → SELLING PRESSURE builds (red, rises UP from zero)
 *   · BOTTOM HALF — negative net charm flow → dealers buy
 *                   → BUYING PRESSURE builds (green, grows DOWN from zero)
 *
 * The zero midline is the balance line; the net trace connects per-strike
 * net flow so the pressure profile reads left to right across strikes.
 * This is a positioning proxy, not observed flow — the readout says so.
 */
const props = withDefaults(defineProps<{
  symbol: string
  rows: CharmStrikeRow[]
  spot?: number | null
  height?: number
  callWall?: number | null
  putWall?: number | null
  gammaFlip?: number | null
}>(), {
  spot: null,
  height: 440,
  callWall: null,
  putWall: null,
  gammaFlip: null,
})

const frameEl = ref<HTMLDivElement | null>(null)
const svgEl = ref<SVGSVGElement | null>(null)
const uid = useId()
const { W } = useChartSize(frameEl, {
  minW: 280,
  minH: 220,
  fallbackW: 1120,
  fallbackH: props.height,
})
const H = computed(() => Math.max(300, Math.round(props.height)))

const pad = computed(() => {
  const narrow = W.value < 480
  return {
    l: narrow ? 52 : 64,
    r: narrow ? 18 : 24,
    t: 26,
    b: 28,
  }
})

/** Zero midline sits dead-centre; each pane is half the inner height. */
const plotTop = computed(() => pad.value.t)
const plotBot = computed(() => H.value - pad.value.b)
const plotH = computed(() => Math.max(60, plotBot.value - plotTop.value))
const zeroY = computed(() => plotTop.value + plotH.value / 2)
const halfH = computed(() => plotH.value / 2)

const hoverIdx = ref<number | null>(null)

const ordered = computed(() => [...props.rows]
  .filter((r) => Number.isFinite(r.strike) && Number.isFinite(r.net_charm_flow))
  .sort((a, b) => a.strike - b.strike))

const strikeDomain = computed(() => {
  const strikes = ordered.value.map((r) => r.strike)
  if (!strikes.length) return { lo: 0, hi: 1 }
  const lo = Math.min(...strikes)
  const hi = Math.max(...strikes)
  if (lo === hi) return { lo: lo - 1, hi: hi + 1 }
  const padAmt = (hi - lo) * 0.05
  return { lo: lo - padAmt, hi: hi + padAmt }
})

const xScale = computed(() => linearScale(
  [strikeDomain.value.lo, strikeDomain.value.hi],
  [pad.value.l, W.value - pad.value.r],
))

/** Dynamic bar width based on strike spacing. */
const barWidth = computed(() => {
  const n = ordered.value.length
  if (n <= 1) return 16
  let minDx = Infinity
  for (let i = 1; i < ordered.value.length; i++) {
    const dx = Math.abs(xScale.value(ordered.value[i].strike) - xScale.value(ordered.value[i - 1].strike))
    if (dx > 0 && dx < minDx) minDx = dx
  }
  if (!Number.isFinite(minDx)) return 12
  return Math.max(6, Math.min(22, Math.floor(minDx * 0.72)))
})

/** Symmetric flow scale — both panes share one axis (shares/day). */
const flowMax = computed(() => {
  let max = 1
  for (const r of ordered.value) {
    max = Math.max(max, Math.abs(r.net_charm_flow))
  }
  return max
})

const yScale = computed(() => linearScale(
  [-flowMax.value, flowMax.value],
  [plotBot.value, plotTop.value],
))

interface FlowBar {
  strike: number
  x: number
  net: number
  sellH: number
  buyH: number
  callFlow: number
  putFlow: number
  callOi: number
  putOi: number
}

const bars = computed<FlowBar[]>(() => {
  return ordered.value.map((r) => {
    const net = r.net_charm_flow
    const sell = Math.max(0, net)
    const buy = Math.max(0, -net)
    return {
      strike: r.strike,
      x: xScale.value(r.strike),
      net,
      sellH: Math.max(sell > 0 ? 2 : 0, sell * (halfH.value / flowMax.value)),
      buyH: Math.max(buy > 0 ? 2 : 0, buy * (halfH.value / flowMax.value)),
      callFlow: r.call_charm_flow,
      putFlow: r.put_charm_flow,
      callOi: r.call_oi,
      putOi: r.put_oi,
    }
  })
})

/** Net pressure trace across strikes. */
const netPath = computed(() => linePath(
  ordered.value.map((r) => ({ x: xScale.value(r.strike), y: yScale.value(r.net_charm_flow) })),
))

/** Totals: positive net flow = selling pressure, negative = buying pressure. */
const totalSell = computed(() => ordered.value.reduce((a, r) => a + Math.max(0, r.net_charm_flow), 0))
const totalBuy = computed(() => ordered.value.reduce((a, r) => a + Math.max(0, -r.net_charm_flow), 0))
const netTotal = computed(() => totalSell.value - totalBuy.value)
const regime = computed<'selling' | 'buying' | 'balanced'>(() => {
  const total = totalSell.value + totalBuy.value
  if (total <= 0) return 'balanced'
  const share = netTotal.value / total
  if (share > 0.05) return 'selling'
  if (share < -0.05) return 'buying'
  return 'balanced'
})

const flowTicks = computed(() => {
  const t = niceTicks(0, flowMax.value, 3)
  return t.map((value) => ({
    value,
    sellY: zeroY.value - (value / flowMax.value) * halfH.value,
    buyY: zeroY.value + (value / flowMax.value) * halfH.value,
  }))
})

const strikeTicks = computed(() => {
  const t = niceTicks(strikeDomain.value.lo, strikeDomain.value.hi, 6)
  return t.map((value) => ({ value, x: xScale.value(value) }))
})

const spotX = computed(() => props.spot != null && Number.isFinite(props.spot)
  ? xScale.value(props.spot)
  : null)

const callWallX = computed(() => props.callWall != null && Number.isFinite(props.callWall)
  ? xScale.value(props.callWall)
  : null)

const putWallX = computed(() => props.putWall != null && Number.isFinite(props.putWall)
  ? xScale.value(props.putWall)
  : null)

const gammaFlipX = computed(() => props.gammaFlip != null && Number.isFinite(props.gammaFlip)
  ? xScale.value(props.gammaFlip)
  : null)

const focus = computed(() => {
  const idx = hoverIdx.value
  if (idx == null) return null
  const bar = bars.value[idx]
  if (!bar) return null
  const spotPrice = props.spot
  const distPct = spotPrice && spotPrice > 0
    ? ((bar.strike - spotPrice) / spotPrice) * 100
    : null
  return {
    strike: bar.strike,
    x: bar.x,
    net: bar.net,
    sellH: bar.sellH,
    buyH: bar.buyH,
    callFlow: bar.callFlow,
    putFlow: bar.putFlow,
    callOi: bar.callOi,
    putOi: bar.putOi,
    distPct,
    dealerAction: bar.net > 0 ? 'SELL STOCK' : bar.net < 0 ? 'BUY STOCK' : 'NEUTRAL',
    pressureType: bar.net > 0 ? 'SELLING PRESSURE' : bar.net < 0 ? 'BUYING PRESSURE' : 'BALANCED',
  }
})

function onMove(e: MouseEvent): void {
  const el = svgEl.value
  const n = bars.value.length
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
  if (px < pad.value.l || px > W.value - pad.value.r || py < plotTop.value || py > plotBot.value) {
    hoverIdx.value = null
    return
  }
  const strike = xScale.value.invert(px)
  let best = 0
  let bestDist = Infinity
  for (let i = 0; i < bars.value.length; i++) {
    const dist = Math.abs(bars.value[i].strike - strike)
    if (dist < bestDist) {
      bestDist = dist
      best = i
    }
  }
  hoverIdx.value = best
}
</script>

<template>
  <div class="pressure-wrap">
    <!-- Header readout / HUD -->
    <div class="chart-readout">
      <div class="readout-left">
        <span class="main-px">
          <i class="key net" />{{ symbol }}
          <b class="fig" :class="regime">
            {{ regime === 'selling' ? 'SELLING PRESSURE' : regime === 'buying' ? 'BUYING PRESSURE' : 'BALANCED' }}
          </b>
        </span>
        <span class="prem-sum sell">Σ SELL {{ compact(totalSell) }} sh/d</span>
        <span class="prem-sum buy">Σ BUY {{ compact(totalBuy) }} sh/d</span>
        <span
          class="imbalance"
          :class="regime"
          title="Net charm flow: shares/day dealers must trade to stay delta-hedged from time decay"
        >
          NET {{ netTotal > 0 ? '+' : '' }}{{ compact(netTotal) }} sh/d
        </span>
      </div>

      <div v-if="focus" class="probe-inline">
        <span class="probe-strike fig">K ${{ num(focus.strike, 0) }}</span>
        <span v-if="focus.distPct != null" class="probe-moneyness label">
          {{ focus.distPct >= 0 ? '+' : '' }}{{ focus.distPct.toFixed(1) }}%
        </span>
        <span class="probe-action label" :class="focus.net > 0 ? 'sell' : focus.net < 0 ? 'buy' : ''">
          DEALERS {{ focus.dealerAction }}
        </span>
        <span v-if="focus.net > 0" class="sell fig">SELL {{ compact(focus.net) }} sh/d</span>
        <span v-else-if="focus.net < 0" class="buy fig">BUY {{ compact(-focus.net) }} sh/d</span>
        <span class="label flow-breakdown">
          C: {{ compact(focus.callFlow) }} sh/d ({{ compact(focus.callOi) }} OI) ·
          P: {{ compact(focus.putFlow) }} sh/d ({{ compact(focus.putOi) }} OI)
        </span>
      </div>
      <div v-else class="scale-note label">shares/day · hover any strike bar to inspect dealer hedge flow</div>
    </div>

    <!-- Chart canvas -->
    <div ref="frameEl" class="pressure-canvas" :style="{ height: `${H}px` }">
      <svg
        ref="svgEl"
        class="pressure-svg"
        :viewBox="`0 0 ${W} ${H}`"
        role="img"
        :aria-label="`${symbol} charm flow by strike — selling pressure above zero, buying pressure below`"
        preserveAspectRatio="xMidYMid meet"
        @mousemove="onMove"
        @mouseleave="hoverIdx = null"
      >
        <title>{{ symbol }} charm flow by strike (dealer hedge pressure from time decay)</title>
        <defs>
          <pattern :id="`pgrid-${uid}`" width="28" height="28" patternUnits="userSpaceOnUse">
            <path d="M 28 0 L 0 0 0 28" fill="none" stroke="var(--grid)" stroke-width="1" />
          </pattern>
          <linearGradient :id="`sell-grad-${uid}`" x1="0" y1="1" x2="0" y2="0">
            <stop offset="0%" stop-color="var(--put)" stop-opacity="0.12" />
            <stop offset="100%" stop-color="var(--put)" stop-opacity="0.32" />
          </linearGradient>
          <linearGradient :id="`buy-grad-${uid}`" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="var(--call)" stop-opacity="0.12" />
            <stop offset="100%" stop-color="var(--call)" stop-opacity="0.32" />
          </linearGradient>
        </defs>

        <!-- Plot background -->
        <rect
          :x="pad.l"
          :y="plotTop"
          :width="W - pad.l - pad.r"
          :height="plotH"
          :fill="`url(#pgrid-${uid})`"
        />

        <!-- Zone background highlights -->
        <rect
          :x="pad.l"
          :y="plotTop"
          :width="W - pad.l - pad.r"
          :height="halfH"
          :fill="`url(#sell-grad-${uid})`"
          class="zone-bg sell-zone"
        />
        <rect
          :x="pad.l"
          :y="zeroY"
          :width="W - pad.l - pad.r"
          :height="halfH"
          :fill="`url(#buy-grad-${uid})`"
          class="zone-bg buy-zone"
        />

        <!-- Pane captions -->
        <g class="pane-headers">
          <text class="pane-cap sell" :x="pad.l + 8" :y="plotTop + 14">▲ SELLING PRESSURE · DEALERS SELL SHARES</text>
          <text class="pane-cap buy" :x="pad.l + 8" :y="plotBot - 8">▼ BUYING PRESSURE · DEALERS BUY SHARES</text>
        </g>

        <!-- Left-axis ticks (shared scale, mirrored about zero) -->
        <g class="grid-lines">
          <line class="zero" :x1="pad.l" :x2="W - pad.r" :y1="zeroY" :y2="zeroY" />
          <template v-for="tick in flowTicks" :key="`ft-${tick.value}`">
            <line v-if="tick.value > 0" :x1="pad.l" :x2="W - pad.r" :y1="tick.sellY" :y2="tick.sellY" />
            <line v-if="tick.value > 0" :x1="pad.l" :x2="W - pad.r" :y1="tick.buyY" :y2="tick.buyY" />
            <text :x="pad.l - 8" :y="tick.sellY + 3" text-anchor="end">+{{ compact(tick.value) }}</text>
            <text :x="pad.l - 8" :y="tick.buyY + 3" text-anchor="end">-{{ compact(tick.value) }}</text>
          </template>
          <text :x="pad.l - 8" :y="zeroY + 3" text-anchor="end" class="zero-label">0</text>
        </g>

        <!-- Wall markers if present -->
        <g v-if="putWallX != null" class="wall-marker put-wall">
          <line :x1="putWallX" :x2="putWallX" :y1="plotTop" :y2="plotBot" class="wall-line" />
          <text :x="putWallX + 3" :y="plotTop + 34" class="wall-label">PUT WALL ${{ num(putWall, 0) }}</text>
        </g>
        <g v-if="callWallX != null" class="wall-marker call-wall">
          <line :x1="callWallX" :x2="callWallX" :y1="plotTop" :y2="plotBot" class="wall-line" />
          <text :x="callWallX + 3" :y="plotTop + 34" class="wall-label">CALL WALL ${{ num(callWall, 0) }}</text>
        </g>
        <g v-if="gammaFlipX != null" class="wall-marker gamma-flip">
          <line :x1="gammaFlipX" :x2="gammaFlipX" :y1="plotTop" :y2="plotBot" class="wall-line" />
          <text :x="gammaFlipX + 3" :y="plotTop + 48" class="wall-label">FLIP ${{ num(gammaFlip, 0) }}</text>
        </g>

        <!-- Spot marker -->
        <g v-if="spotX != null" class="spot-marker">
          <line :x1="spotX" :x2="spotX" :y1="plotTop" :y2="plotBot" class="spot-line" />
          <rect :x="spotX - 32" :y="plotTop + 2" width="64" height="18" rx="2" class="spot-badge" />
          <text :x="spotX" :y="plotTop + 14" class="spot-label" text-anchor="middle">SPOT ${{ num(spot) }}</text>
        </g>

        <!-- Net pressure trace across strikes -->
        <path v-if="netPath" class="net-trace" :d="netPath" />

        <!-- Charm flow bars: selling up (red), buying down (green) -->
        <g class="pressure-bars">
          <g
            v-for="bar in bars"
            :key="bar.strike"
            :class="{ 'is-active': focus && focus.strike === bar.strike }"
          >
            <!-- Selling pressure bar (rises UP from zeroY) -->
            <rect
              v-if="bar.sellH > 0"
              class="bar sell"
              :x="bar.x - barWidth / 2"
              :y="zeroY - bar.sellH"
              :width="barWidth"
              :height="bar.sellH"
              rx="1.5"
            >
              <title>K {{ num(bar.strike) }} · selling pressure {{ compact(bar.net) }} sh/d</title>
            </rect>

            <!-- Buying pressure bar (grows DOWN from zeroY) -->
            <rect
              v-if="bar.buyH > 0"
              class="bar buy"
              :x="bar.x - barWidth / 2"
              :y="zeroY"
              :width="barWidth"
              :height="bar.buyH"
              rx="1.5"
            >
              <title>K {{ num(bar.strike) }} · buying pressure {{ compact(-bar.net) }} sh/d</title>
            </rect>

            <!-- Active strike highlight marker on trace -->
            <circle
              v-if="focus && focus.strike === bar.strike"
              :cx="bar.x"
              :cy="yScale(bar.net)"
              r="4.5"
              class="trace-dot"
            />
          </g>
        </g>

        <!-- Crosshair on hover -->
        <g v-if="focus" class="crosshair">
          <line :x1="focus.x" :x2="focus.x" :y1="plotTop" :y2="plotBot" class="crosshair-v" />
          <line :x1="pad.l" :x2="W - pad.r" :y1="yScale(focus.net)" :y2="yScale(focus.net)" class="crosshair-h" />
          <circle :cx="focus.x" :cy="zeroY" r="3.5" class="zero-dot" />
        </g>

        <!-- Strike axis -->
        <g class="strike-axis">
          <template v-for="tick in strikeTicks" :key="`st-${tick.value}`">
            <line :x1="tick.x" :x2="tick.x" :y1="plotBot" :y2="plotBot + 5" />
            <text :x="tick.x" :y="H - 7" text-anchor="middle">${{ num(tick.value, 0) }}</text>
          </template>
        </g>

        <!-- Empty state -->
        <text v-if="!bars.length" class="empty" :x="W / 2" :y="zeroY" text-anchor="middle">
          NO CHARM DATA — CHAIN MISSING IV OR OI
        </text>
      </svg>
    </div>

    <!-- Clear footer legend & interpretation guide -->
    <div class="legend label">
      <span class="leg"><i class="swatch sell" /> <b>Top Pane (↑):</b> Positive charm flow → Dealer delta increases → <b>Dealers SELL underlying</b> (Selling Pressure)</span>
      <span class="leg"><i class="swatch buy" /> <b>Bottom Pane (↓):</b> Negative charm flow → Dealer delta decreases → <b>Dealers BUY underlying</b> (Buying Pressure)</span>
      <span class="leg"><i class="swatch net" /> Net trace across strikes</span>
      <span class="leg note">Positioning proxy from open interest, not observed flow. Units in shares/day.</span>
    </div>
  </div>
</template>

<style scoped>
/* Surface glass token: var(--glass-surface-hi) */
.pressure-wrap {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--surface-base);
  border-radius: var(--r-sm);
}

.chart-readout {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px 12px;
  min-height: 28px;
  padding: 6px 10px;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.03em;
  color: var(--ink-dim);
  border-bottom: var(--hair) solid var(--rule);
  background: var(--panel-hi);
}

.readout-left {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.readout-left span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.main-px {
  font-weight: 700;
  color: var(--ink);
}
.main-px b.selling { color: var(--put-hi); }
.main-px b.buying { color: var(--call-hi); }
.main-px b.balanced { color: var(--ink-dim); }

.prem-sum.sell { color: var(--put-hi); }
.prem-sum.buy { color: var(--call-hi); }

.imbalance {
  font-weight: 700;
  padding: 2px 6px;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
}
.imbalance.selling {
  color: var(--put-hi);
  border-color: var(--put-dim);
  background: var(--put-wash);
}
.imbalance.buying {
  color: var(--call-hi);
  border-color: var(--call-dim);
  background: var(--call-wash);
}
.imbalance.balanced {
  color: var(--ink-dim);
}

.probe-inline {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 2px 8px;
  border: var(--hair) solid var(--phosphor-dim);
  border-radius: var(--r-xs);
  background: var(--void);
  color: var(--ink);
}

.probe-strike {
  font-weight: 700;
  color: var(--ink);
}

.probe-moneyness {
  color: var(--ink-faint);
}

.probe-action {
  font-weight: 700;
  padding: 1px 4px;
  border-radius: 2px;
}
.probe-action.sell { color: var(--put-hi); background: var(--put-wash); }
.probe-action.buy { color: var(--call-hi); background: var(--call-wash); }

.probe-inline .sell { color: var(--put-hi); font-weight: 600; }
.probe-inline .buy { color: var(--call-hi); font-weight: 600; }
.flow-breakdown { color: var(--ink-dim); font-size: 10px; }

.scale-note {
  color: var(--ink-faint);
  font-style: italic;
}

.key {
  width: 12px;
  height: 2px;
  display: inline-block;
  border-radius: 1px;
}
.key.net { background: var(--phosphor); }

.pressure-canvas {
  position: relative;
  width: 100%;
  min-width: 0;
  overflow: hidden;
}

.pressure-svg {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
  background: var(--void);
  cursor: crosshair;
}

.zone-bg {
  pointer-events: none;
}

.pane-cap {
  font: 700 9px var(--font-data);
  letter-spacing: 0.08em;
}
.pane-cap.sell { fill: var(--put-dim); }
.pane-cap.buy { fill: var(--call-dim); }

.grid-lines line {
  stroke: var(--rule-faint);
  stroke-width: 1px;
  vector-effect: non-scaling-stroke;
}
.grid-lines line.zero {
  stroke: var(--rule-hi);
  stroke-width: 1.5px;
  vector-effect: non-scaling-stroke;
}
.grid-lines text, .strike-axis text {
  fill: var(--ink-dim);
  font: 600 10px var(--font-data);
  letter-spacing: 0.02em;
}
.grid-lines text.zero-label {
  fill: var(--ink-faint);
}

.spot-marker .spot-line {
  stroke: var(--phosphor);
  stroke-width: 1.2px;
  stroke-dasharray: 4 3;
  opacity: 0.85;
  vector-effect: non-scaling-stroke;
}
.spot-marker .spot-badge {
  fill: var(--phosphor);
}
.spot-marker .spot-label {
  fill: var(--void);
  font: 700 9px var(--font-data);
  letter-spacing: 0.04em;
}

.wall-marker .wall-line {
  stroke-width: 1px;
  stroke-dasharray: 2 3;
  opacity: 0.6;
  vector-effect: non-scaling-stroke;
}
.wall-marker.call-wall .wall-line { stroke: var(--call); }
.wall-marker.put-wall .wall-line { stroke: var(--put); }
.wall-marker.gamma-flip .wall-line { stroke: var(--warn); }
.wall-marker .wall-label {
  font: 600 8.5px var(--font-data);
  letter-spacing: 0.04em;
}
.wall-marker.call-wall .wall-label { fill: var(--call-dim); }
.wall-marker.put-wall .wall-label { fill: var(--put-dim); }
.wall-marker.gamma-flip .wall-label { fill: var(--warn); }

.net-trace {
  stroke: var(--phosphor);
  fill: none;
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
  stroke-linejoin: round;
  stroke-linecap: round;
  opacity: 0.95;
}

.trace-dot {
  fill: var(--phosphor);
  stroke: var(--void);
  stroke-width: 1.5px;
}

.pressure-bars .bar {
  vector-effect: non-scaling-stroke;
  stroke-width: 1px;
  opacity: 0.85;
  transition: opacity 0.15s ease, stroke-width 0.15s ease, fill 0.15s ease;
}
.pressure-bars .bar.sell {
  fill: var(--put);
  stroke: var(--put-hi);
}
.pressure-bars .bar.buy {
  fill: var(--call);
  stroke: var(--call-hi);
}

.pressure-bars g:hover .bar,
.pressure-bars g.is-active .bar {
  opacity: 1;
  stroke-width: 1.5px;
}
.pressure-bars g:hover .bar.sell,
.pressure-bars g.is-active .bar.sell {
  fill: var(--put-hi);
}
.pressure-bars g:hover .bar.buy,
.pressure-bars g.is-active .bar.buy {
  fill: var(--call-hi);
}

.strike-axis line {
  stroke: var(--rule-hi);
  vector-effect: non-scaling-stroke;
}

.crosshair .crosshair-v {
  stroke: var(--phosphor);
  stroke-width: 1px;
  stroke-dasharray: 2 3;
  opacity: 0.8;
  vector-effect: non-scaling-stroke;
}
.crosshair .crosshair-h {
  stroke: var(--rule-hi);
  stroke-width: 1px;
  stroke-dasharray: 2 2;
  opacity: 0.75;
  vector-effect: non-scaling-stroke;
}
.crosshair .zero-dot {
  fill: var(--phosphor);
  stroke: var(--void);
  stroke-width: 1.5px;
}

.empty {
  fill: var(--ink-faint);
  font: 11px var(--font-display);
  letter-spacing: 0.1em;
}

.legend {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.02em;
  background: var(--panel);
  border-top: var(--hair) solid var(--rule);
}
.legend .leg {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.legend .leg b {
  color: var(--ink);
}
.legend .note {
  color: var(--ink-faint);
  font-style: italic;
  margin-top: 2px;
}
.legend .swatch {
  display: inline-block;
  width: 12px;
  height: 9px;
  border-radius: 1.5px;
}
.legend .swatch.sell { background: var(--put); }
.legend .swatch.buy { background: var(--call); }
.legend .swatch.net { background: var(--phosphor); }

@media (max-width: 900px) {
  .chart-readout {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
  .probe-inline {
    width: 100%;
  }
}
</style>
