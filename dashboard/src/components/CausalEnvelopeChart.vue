<script setup lang="ts">
import { computed, ref } from 'vue'
import type {
  StateEstimationPoint,
  AnchoredVwapSeries,
  ExecutionSignal,
} from '@/microstructureContracts'
import type { ExpectedMoveMetrics } from '@/expectedMove'
import { num, optSigned } from '@/format'

const props = withDefaults(
  defineProps<{
    points: StateEstimationPoint[]
    anchors?: AnchoredVwapSeries[]
    signals?: ExecutionSignal[]
    callWall?: number | null
    putWall?: number | null
    gammaFlip?: number | null
    expectedMove?: ExpectedMoveMetrics | null
    /**
     * Live spot from the fast clock. The HUD's price is a *bar close* off the
     * state-estimation series, which lags the tape by however long the bar is
     * (a daily series can be days behind). Printed as "SPOT PRICE" next to the
     * page's live spot, it read as a second, contradictory quote; it is now
     * labelled as the bar close, with the live price beside it.
     */
    liveSpot?: number | null
    height?: number
    hoverIndex?: number | null
  }>(),
  {
    anchors: () => [],
    signals: () => [],
    callWall: null,
    putWall: null,
    gammaFlip: null,
    expectedMove: null,
    liveSpot: null,
    height: 440,
    hoverIndex: null,
  },
)

const emit = defineEmits<{
  'update:hoverIndex': [index: number | null]
}>()

const showExpectedMove = ref(true)

const chartHeight = computed(() => props.height ?? 440)
const chartWidth = 1200
const pad = { top: 32, right: 130, bottom: 36, left: 70 }

const innerWidth = computed(() => chartWidth - pad.left - pad.right)
const innerHeight = computed(() => chartHeight.value - pad.top - pad.bottom)

/**
 * Intelligent price extent calculation:
 * Focuses on the tradeable window (points and dynamic envelope).
 * Remote strikes (e.g. 50% away) are clamped so they do not squash the price line into a flat ribbon.
 */
const priceExtent = computed(() => {
  if (!props.points || props.points.length === 0) return { min: 0, max: 100 }
  let min = Infinity
  let max = -Infinity

  for (const pt of props.points) {
    if (Number.isFinite(pt.price)) {
      if (pt.price < min) min = pt.price
      if (pt.price > max) max = pt.price
    }
    if (Number.isFinite(pt.nw_lower)) {
      if (pt.nw_lower < min) min = pt.nw_lower
    }
    if (Number.isFinite(pt.nw_upper)) {
      if (pt.nw_upper > max) max = pt.nw_upper
    }
  }

  if (min === Infinity || max === -Infinity) return { min: 0, max: 100 }

  const span = max - min || 1.0
  const maxExpansion = span * 0.35 // clamp max expansion so structural levels don't distort scale

  if (props.callWall != null && props.callWall > 0) {
    if (props.callWall > max && props.callWall <= max + maxExpansion) {
      max = props.callWall
    }
  }
  if (props.putWall != null && props.putWall > 0) {
    if (props.putWall < min && props.putWall >= min - maxExpansion) {
      min = props.putWall
    }
  }
  if (props.gammaFlip != null && props.gammaFlip > 0) {
    if (props.gammaFlip < min && props.gammaFlip >= min - maxExpansion) {
      min = props.gammaFlip
    }
    if (props.gammaFlip > max && props.gammaFlip <= max + maxExpansion) {
      max = props.gammaFlip
    }
  }

  // Include 1D Expected Move within clamped range
  if (showExpectedMove.value && props.expectedMove) {
    if (props.expectedMove.em1dHigh > max && props.expectedMove.em1dHigh <= max + maxExpansion) {
      max = props.expectedMove.em1dHigh
    }
    if (props.expectedMove.em1dLow < min && props.expectedMove.em1dLow >= min - maxExpansion) {
      min = props.expectedMove.em1dLow
    }
  }

  const finalSpan = max - min || 1.0
  return { min: min - finalSpan * 0.05, max: max + finalSpan * 0.05 }
})

function scaleX(index: number): number {
  const n = props.points.length
  if (n <= 1) return pad.left
  const clampedIdx = Math.max(0, Math.min(n - 1, index))
  return pad.left + (clampedIdx / (n - 1)) * innerWidth.value
}

function scaleY(val: number): number {
  const { min, max } = priceExtent.value
  if (max === min) return pad.top + innerHeight.value / 2
  const norm = (val - min) / (max - min)
  return pad.top + (1 - norm) * innerHeight.value
}

// Path for price series
const pricePath = computed(() => {
  if (!props.points || props.points.length === 0) return ''
  return props.points
    .map((pt, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(i).toFixed(1)} ${scaleY(pt.price).toFixed(1)}`)
    .join(' ')
})

// Path for NW regression mean
const nwMeanPath = computed(() => {
  if (!props.points || props.points.length === 0) return ''
  return props.points
    .map(
      (pt, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(i).toFixed(1)} ${scaleY(pt.nw_mean).toFixed(1)}`,
    )
    .join(' ')
})

// Ribbon Area for NW Envelope
const nwEnvelopeAreaPath = computed(() => {
  if (!props.points || props.points.length === 0) return ''
  const upperPts = props.points
    .map(
      (pt, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(i).toFixed(1)} ${scaleY(pt.nw_upper).toFixed(1)}`,
    )
    .join(' ')
  const lowerPts = [...props.points]
    .reverse()
    .map((pt, i) => {
      const origIdx = props.points.length - 1 - i
      return `L ${scaleX(origIdx).toFixed(1)} ${scaleY(pt.nw_lower).toFixed(1)}`
    })
    .join(' ')
  return `${upperPts} ${lowerPts} Z`
})

// Anchored VWAP Paths
const vwapPaths = computed(() => {
  if (!props.anchors || props.anchors.length === 0 || props.points.length === 0) return []
  return props.anchors.map((anc) => {
    const validPts = anc.series.filter((s) => Number.isFinite(s.vwap))
    if (validPts.length === 0) return { name: anc.anchor_name, path: '' }
    const pathStr = validPts
      .map((pt, idx) => {
        const ptIdx = props.points.findIndex((p) => p.t === pt.t)
        const effectiveIdx =
          ptIdx >= 0 ? ptIdx : Math.min(props.points.length - 1, anc.anchor_index + idx)
        const x = scaleX(effectiveIdx)
        return `${idx === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${scaleY(pt.vwap).toFixed(1)}`
      })
      .join(' ')
    return { name: anc.anchor_name, path: pathStr }
  })
})

/**
 * How many bars back a signal may sit and still be drawn as a live plan.
 * Beyond this it is history: a five-month-old short's $586 target projected
 * across a chart trading at $766 reads as the current trade, which is the one
 * thing a stop line must never do.
 */
const SIGNAL_PROJECTION_MAX_AGE_BARS = 5

/** The last entry signal in the window, live or not — the marker layer wants
 *  it either way. */
const lastEntrySignal = computed(() => {
  if (!props.signals || props.signals.length === 0) return null
  const candidates = props.signals.filter(
    (s) => s.action === 'ENTER_LONG' || s.action === 'ENTER_SHORT',
  )
  return candidates.length > 0 ? candidates[candidates.length - 1] : null
})

/** Bars between the last entry signal and the right edge of the series. */
const lastSignalAgeBars = computed<number | null>(() => {
  const sig = lastEntrySignal.value
  const n = props.points.length
  if (!sig || n === 0) return null
  if (!Number.isFinite(sig.bar_index) || sig.bar_index < 0) return null
  return Math.max(0, n - 1 - sig.bar_index)
})

/** Target/stop projections, drawn only while the signal is still current. */
const latestSignal = computed(() => {
  const age = lastSignalAgeBars.value
  if (age == null || age > SIGNAL_PROJECTION_MAX_AGE_BARS) return null
  return lastEntrySignal.value
})

/** Set when there is an entry signal but it is too old to project — so its
 *  absence reads as "stale", not as "no setup found". */
const staleSignalNote = computed<string | null>(() => {
  const sig = lastEntrySignal.value
  const age = lastSignalAgeBars.value
  if (!sig || age == null || age <= SIGNAL_PROJECTION_MAX_AGE_BARS) return null
  const when = sig.timestamp ? sig.timestamp.slice(0, 10) : `${age} bars ago`
  return `Last setup (${sig.action.replace('ENTER_', '')} ${when}, ${age} bars back) is stale; its target and stop are not projected.`
})

// Signal Markers
const signalMarkers = computed(() => {
  if (!props.signals || props.signals.length === 0 || props.points.length === 0) return []
  return props.signals
    .filter((s) => s.action === 'ENTER_LONG' || s.action === 'ENTER_SHORT')
    .map((s) => {
      const idx =
        s.bar_index >= 0 && s.bar_index < props.points.length
          ? s.bar_index
          : props.points.length - 1
      const x = scaleX(idx)
      const y = scaleY(s.price)
      return {
        ...s,
        x,
        y,
        isLong: s.action === 'ENTER_LONG',
      }
    })
})

// Y-Axis Ticks
const yTicks = computed(() => {
  const { min, max } = priceExtent.value
  const steps = 6
  const ticks = []
  for (let i = 0; i <= steps; i++) {
    const val = min + (i / steps) * (max - min)
    ticks.push({ val, y: scaleY(val) })
  }
  return ticks
})

function formatDateLabel(isoStr: string): string {
  try {
    const d = new Date(isoStr)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
  } catch {
    return isoStr.slice(5, 10)
  }
}

// X-Axis Date Ticks
const xTicks = computed(() => {
  const n = props.points.length
  if (n === 0) return []
  const count = Math.min(8, n)
  const ticks = []
  for (let i = 0; i < count; i++) {
    const idx = Math.floor((i / (count - 1)) * (n - 1))
    const pt = props.points[idx]
    ticks.push({
      label: formatDateLabel(pt.t),
      rawTime: pt.t,
      x: scaleX(idx),
    })
  }
  return ticks
})

// Local & Synced Hover State
const localHoverIndex = ref<number | null>(null)
const activeHoverIndex = computed(() => props.hoverIndex ?? localHoverIndex.value)

const hoveredPoint = computed(() => {
  if (activeHoverIndex.value != null && props.points[activeHoverIndex.value]) {
    return props.points[activeHoverIndex.value]
  }
  return props.points.length > 0 ? props.points[props.points.length - 1] : null
})

/**
 * Live spot alongside the bar close, but only on the bar the series actually
 * ends on: quoting today's price against a bar from March would be a second
 * meaningless comparison in place of the one being fixed. Suppressed while the
 * two agree to the cent, so the HUD does not carry a tile that repeats itself.
 */
const liveSpotGap = computed<{ spot: number; pct: number } | null>(() => {
  const spot = props.liveSpot
  const pts = props.points
  if (spot == null || !Number.isFinite(spot) || !(spot > 0) || pts.length === 0) return null
  const onLastBar = activeHoverIndex.value == null || activeHoverIndex.value === pts.length - 1
  if (!onLastBar) return null
  const barClose = pts[pts.length - 1].price
  if (!Number.isFinite(barClose) || !(barClose > 0)) return null
  const pct = ((spot - barClose) / barClose) * 100
  return Math.abs(pct) >= 0.01 ? { spot, pct } : null
})

const hoveredSignal = computed(() => {
  if (!hoveredPoint.value || !props.signals) return null
  return (
    props.signals.find((s) => s.timestamp === hoveredPoint.value?.t && s.action !== 'NONE') ?? null
  )
})

function onSvgMouseMove(evt: MouseEvent): void {
  const svg = evt.currentTarget as SVGSVGElement
  const rect = svg.getBoundingClientRect()
  const mouseX = evt.clientX - rect.left
  const svgX = (mouseX / rect.width) * chartWidth

  const n = props.points.length
  if (n <= 1) return

  const relX = Math.max(0, Math.min(innerWidth.value, svgX - pad.left))
  const idx = Math.round((relX / innerWidth.value) * (n - 1))
  const finalIdx = Math.max(0, Math.min(n - 1, idx))
  localHoverIndex.value = finalIdx
  emit('update:hoverIndex', finalIdx)
}

function onSvgMouseLeave(): void {
  localHoverIndex.value = null
  emit('update:hoverIndex', null)
}
</script>

<template>
  <div class="envelope-chart-container">
    <!-- Top Interactive HUD Bar -->
    <div v-if="hoveredPoint" class="chart-hud">
      <div class="hud-item">
        <span class="hud-k">BAR DATE</span>
        <span class="hud-v font-mono font-semibold">{{ hoveredPoint.t.slice(0, 10) }}</span>
      </div>
      <div class="hud-item">
        <span class="hud-k">BAR CLOSE</span>
        <span class="hud-v font-mono font-bold">${{ num(hoveredPoint.price, 2) }}</span>
      </div>
      <!-- The live quote, when it has moved away from the bar this series
           ends on. Same surface, two clocks — say which is which. -->
      <div v-if="liveSpotGap" class="hud-item">
        <span class="hud-k">LIVE SPOT</span>
        <span class="hud-v font-mono font-bold text-warn"
          >${{ num(liveSpotGap.spot, 2) }} ({{ optSigned(liveSpotGap.pct, 2) }}% vs bar)</span
        >
      </div>
      <div class="hud-item">
        <span class="hud-k">KERNEL MEAN m(t)</span>
        <span class="hud-v font-mono text-phosphor">${{ num(hoveredPoint.nw_mean, 2) }}</span>
      </div>
      <div class="hud-item">
        <span class="hud-k">CAUSAL ENVELOPE</span>
        <span class="hud-v font-mono text-call-hi"
          >[${{ num(hoveredPoint.nw_lower, 2) }} to ${{ num(hoveredPoint.nw_upper, 2) }}]</span
        >
      </div>
      <div v-if="expectedMove" class="hud-item">
        <span class="hud-k">1D EXP MOVE (VIX/16)</span>
        <span class="hud-v font-mono text-warn"
          >&plusmn;${{ num(expectedMove.em1dDollars, 2) }} (&plusmn;{{
            num(expectedMove.em1dPct, 1)
          }}%)</span
        >
      </div>
      <div class="hud-item">
        <span class="hud-k">KALMAN VELOCITY</span>
        <span
          class="hud-v font-mono font-semibold"
          :class="{
            'text-emerald': hoveredPoint.kalman_velocity > 0,
            'text-rose': hoveredPoint.kalman_velocity < 0,
          }"
        >
          {{ optSigned(hoveredPoint.kalman_velocity, 3) }} ({{
            optSigned(hoveredPoint.kalman_zscore, 2)
          }}&sigma;)
        </span>
      </div>
      <div v-if="hoveredSignal" class="hud-signal" :class="hoveredSignal.action">
        <span class="signal-tag">{{ hoveredSignal.action }}</span>
        <span class="signal-name">{{ hoveredSignal.setup_name }}</span>
      </div>
    </div>

    <!-- Chart Legend & Controls Bar -->
    <div class="chart-legend">
      <div class="legend-item"><span class="swatch price"></span> Spot Price</div>
      <div class="legend-item"><span class="swatch nw-mean"></span> Causal Kernel Mean m(t)</div>
      <div class="legend-item">
        <span class="swatch nw-env"></span> Dynamic Envelope (&plusmn;&alpha;&middot;&sigma;)
      </div>
      <div class="legend-item"><span class="swatch vwap"></span> Anchored VWAP</div>
      <div v-if="callWall" class="legend-item">
        <span class="swatch call-wall"></span> Call Wall (${{ num(callWall, 1) }})
      </div>
      <div v-if="putWall" class="legend-item">
        <span class="swatch put-wall"></span> Put Wall (${{ num(putWall, 1) }})
      </div>
      <div v-if="gammaFlip" class="legend-item">
        <span class="swatch gamma-flip"></span> Gamma Flip S* (${{ num(gammaFlip, 1) }})
      </div>
      <div v-if="expectedMove" class="legend-item">
        <span class="swatch exp-move"></span> 1D EM Corridor (VIX/16)
      </div>
    </div>

    <!-- A withheld projection must say it was withheld, or the operator reads
         the empty chart as "no setup" rather than "the setup expired". -->
    <p v-if="staleSignalNote" class="stale-signal-note">{{ staleSignalNote }}</p>

    <!-- Main Responsive SVG Canvas -->
    <div class="svg-canvas-wrapper">
      <svg role="img" aria-label="Causal Nadaraya-Watson price envelope with band boundaries."
        :viewBox="`0 0 ${chartWidth} ${chartHeight}`"
        class="chart-svg"
        preserveAspectRatio="xMidYMid meet"
        @mousemove="onSvgMouseMove"
        @mouseleave="onSvgMouseLeave"
      >
        <!-- Grid Lines -->
        <g class="grid-lines">
          <line
            v-for="tick in yTicks"
            :key="tick.val"
            :x1="pad.left"
            :y1="tick.y"
            :x2="chartWidth - pad.right"
            :y2="tick.y"
            stroke="var(--rule-faint)"
            stroke-dasharray="2 3"
          />
        </g>

        <!-- Rule of 16 Expected Move Projection Corridor -->
        <g v-if="showExpectedMove && expectedMove" class="expected-move-corridor">
          <!-- 1D Expected Move Upper Band (VIX/16) -->
          <line
            :x1="pad.left"
            :y1="scaleY(expectedMove.em1dHigh)"
            :x2="chartWidth - pad.right"
            :y2="scaleY(expectedMove.em1dHigh)"
            stroke="var(--warn)"
            stroke-width="1.2"
            stroke-dasharray="3 3"
            opacity="0.75"
          />
          <!-- 1D Expected Move Lower Band -->
          <line
            :x1="pad.left"
            :y1="scaleY(expectedMove.em1dLow)"
            :x2="chartWidth - pad.right"
            :y2="scaleY(expectedMove.em1dLow)"
            stroke="var(--warn)"
            stroke-width="1.2"
            stroke-dasharray="3 3"
            opacity="0.75"
          />
          <!-- 1W Expected Move Upper Band -->
          <line
            :x1="pad.left"
            :y1="scaleY(expectedMove.em1wHigh)"
            :x2="chartWidth - pad.right"
            :y2="scaleY(expectedMove.em1wHigh)"
            stroke="var(--ink-dim)"
            stroke-width="1"
            stroke-dasharray="2 4"
            opacity="0.5"
          />
          <!-- 1W Expected Move Lower Band -->
          <line
            :x1="pad.left"
            :y1="scaleY(expectedMove.em1wLow)"
            :x2="chartWidth - pad.right"
            :y2="scaleY(expectedMove.em1wLow)"
            stroke="var(--ink-dim)"
            stroke-width="1"
            stroke-dasharray="2 4"
            opacity="0.5"
          />
        </g>

        <!-- Structural Boundary Lines -->
        <g class="structural-lines">
          <!-- Call Wall Line -->
          <line
            v-if="callWall && callWall > 0"
            :x1="pad.left"
            :y1="scaleY(callWall)"
            :x2="chartWidth - pad.right"
            :y2="scaleY(callWall)"
            stroke="var(--call)"
            stroke-width="1.5"
            stroke-dasharray="5 3"
          />
          <!-- Put Wall Line -->
          <line
            v-if="putWall && putWall > 0"
            :x1="pad.left"
            :y1="scaleY(putWall)"
            :x2="chartWidth - pad.right"
            :y2="scaleY(putWall)"
            stroke="var(--put)"
            stroke-width="1.5"
            stroke-dasharray="5 3"
          />
          <!-- Gamma Flip S* Line -->
          <line
            v-if="gammaFlip && gammaFlip > 0"
            :x1="pad.left"
            :y1="scaleY(gammaFlip)"
            :x2="chartWidth - pad.right"
            :y2="scaleY(gammaFlip)"
            stroke="var(--warn)"
            stroke-width="1.5"
            stroke-dasharray="3 2"
          />
        </g>

        <!-- Active Signal Target & Stop Projection Corridors -->
        <g v-if="latestSignal && latestSignal.take_profit > 0" class="signal-projections">
          <!-- Take Profit Line -->
          <line
            :x1="pad.left"
            :y1="scaleY(latestSignal.take_profit)"
            :x2="chartWidth - pad.right"
            :y2="scaleY(latestSignal.take_profit)"
            stroke="var(--call-hi)"
            stroke-width="1.2"
            stroke-dasharray="4 4"
            opacity="0.8"
          />
          <!-- Stop Loss Line -->
          <line
            v-if="latestSignal.stop_loss > 0"
            :x1="pad.left"
            :y1="scaleY(latestSignal.stop_loss)"
            :x2="chartWidth - pad.right"
            :y2="scaleY(latestSignal.stop_loss)"
            stroke="var(--put-hi)"
            stroke-width="1.2"
            stroke-dasharray="4 4"
            opacity="0.8"
          />
        </g>

        <!-- Shaded Causal Envelope Ribbon -->
        <path :d="nwEnvelopeAreaPath" fill="var(--phosphor-wash)" opacity="0.85" />

        <!-- Causal NW Upper & Lower Boundary Lines -->
        <path
          v-if="points.length > 0"
          :d="
            points
              .map(
                (pt, i) =>
                  `${i === 0 ? 'M' : 'L'} ${scaleX(i).toFixed(1)} ${scaleY(pt.nw_upper).toFixed(1)}`,
              )
              .join(' ')
          "
          fill="none"
          stroke="var(--phosphor)"
          stroke-width="1.2"
          stroke-dasharray="4 3"
          opacity="0.85"
        />
        <path
          v-if="points.length > 0"
          :d="
            points
              .map(
                (pt, i) =>
                  `${i === 0 ? 'M' : 'L'} ${scaleX(i).toFixed(1)} ${scaleY(pt.nw_lower).toFixed(1)}`,
              )
              .join(' ')
          "
          fill="none"
          stroke="var(--phosphor)"
          stroke-width="1.2"
          stroke-dasharray="4 3"
          opacity="0.85"
        />

        <!-- Anchored VWAP Curves -->
        <path
          v-for="v in vwapPaths"
          :key="v.name"
          :d="v.path"
          fill="none"
          stroke="var(--warn)"
          stroke-width="1.6"
          opacity="0.9"
        />

        <!-- Causal Kernel Regression Line -->
        <path :d="nwMeanPath" fill="none" stroke="var(--phosphor)" stroke-width="2.2" />

        <!-- Underlying Price Line -->
        <path :d="pricePath" fill="none" stroke="var(--ink)" stroke-width="2.2" />

        <!-- Execution Signal Markers -->
        <g class="signal-markers">
          <g
            v-for="(sig, i) in signalMarkers"
            :key="i"
            :transform="`translate(${sig.x}, ${sig.y})`"
          >
            <!-- Long Signal (Upward Emerald Triangle) -->
            <polygon
              v-if="sig.isLong"
              points="0,-14 8,2 -8,2"
              fill="var(--call)"
              stroke="var(--void)"
              stroke-width="1.5"
            />
            <!-- Short Signal (Downward Rose Triangle) -->
            <polygon
              v-else
              points="0,14 8,-2 -8,-2"
              fill="var(--put)"
              stroke="var(--void)"
              stroke-width="1.5"
            />
          </g>
        </g>

        <!-- Interactive Hover Crosshair -->
        <g v-if="activeHoverIndex != null && points[activeHoverIndex]" class="hover-crosshair">
          <line
            :x1="scaleX(activeHoverIndex)"
            :y1="pad.top"
            :x2="scaleX(activeHoverIndex)"
            :y2="chartHeight - pad.bottom"
            stroke="var(--ink-dim)"
            stroke-width="1"
            stroke-dasharray="3 3"
          />
          <!-- Spot Dot -->
          <circle
            :cx="scaleX(activeHoverIndex)"
            :cy="scaleY(points[activeHoverIndex].price)"
            r="4.5"
            fill="var(--ink)"
            stroke="var(--void)"
            stroke-width="2"
          />
          <!-- Kernel Mean Dot -->
          <circle
            :cx="scaleX(activeHoverIndex)"
            :cy="scaleY(points[activeHoverIndex].nw_mean)"
            r="3.5"
            fill="var(--phosphor)"
            stroke="var(--void)"
            stroke-width="1.5"
          />
        </g>

        <!-- Right Structural Level Badges -->
        <g class="level-badges">
          <!-- Call Wall Badge -->
          <g
            v-if="callWall && callWall > 0"
            :transform="`translate(${chartWidth - pad.right + 6}, ${scaleY(callWall)})`"
          >
            <rect
              x="0"
              y="-9"
              width="118"
              height="18"
              rx="2"
              fill="var(--call-wash)"
              stroke="var(--call)"
              stroke-width="1"
            />
            <text
              x="6"
              y="4"
              fill="var(--call)"
              font-size="10"
              font-family="monospace"
              font-weight="700"
            >
              ${{ num(callWall, 1) }} CALL W
            </text>
          </g>
          <!-- 1D Expected Move High Badge -->
          <g
            v-if="showExpectedMove && expectedMove"
            :transform="`translate(${chartWidth - pad.right + 6}, ${scaleY(expectedMove.em1dHigh)})`"
          >
            <rect
              x="0"
              y="-9"
              width="118"
              height="18"
              rx="2"
              fill="var(--panel-hi)"
              stroke="var(--warn)"
              stroke-width="1"
            />
            <text
              x="6"
              y="4"
              fill="var(--warn)"
              font-size="10"
              font-family="monospace"
              font-weight="700"
            >
              +1D EM ${{ num(expectedMove.em1dHigh, 1) }}
            </text>
          </g>
          <!-- Gamma Flip Badge -->
          <g
            v-if="gammaFlip && gammaFlip > 0"
            :transform="`translate(${chartWidth - pad.right + 6}, ${scaleY(gammaFlip)})`"
          >
            <rect
              x="0"
              y="-9"
              width="118"
              height="18"
              rx="2"
              fill="var(--warn-wash)"
              stroke="var(--warn)"
              stroke-width="1"
            />
            <text
              x="6"
              y="4"
              fill="var(--warn)"
              font-size="10"
              font-family="monospace"
              font-weight="700"
            >
              ${{ num(gammaFlip, 1) }} FLIP S*
            </text>
          </g>
          <!-- 1D Expected Move Low Badge -->
          <g
            v-if="showExpectedMove && expectedMove"
            :transform="`translate(${chartWidth - pad.right + 6}, ${scaleY(expectedMove.em1dLow)})`"
          >
            <rect
              x="0"
              y="-9"
              width="118"
              height="18"
              rx="2"
              fill="var(--panel-hi)"
              stroke="var(--warn)"
              stroke-width="1"
            />
            <text
              x="6"
              y="4"
              fill="var(--warn)"
              font-size="10"
              font-family="monospace"
              font-weight="700"
            >
              -1D EM ${{ num(expectedMove.em1dLow, 1) }}
            </text>
          </g>
          <!-- Put Wall Badge -->
          <g
            v-if="putWall && putWall > 0"
            :transform="`translate(${chartWidth - pad.right + 6}, ${scaleY(putWall)})`"
          >
            <rect
              x="0"
              y="-9"
              width="118"
              height="18"
              rx="2"
              fill="var(--put-wash)"
              stroke="var(--put)"
              stroke-width="1"
            />
            <text
              x="6"
              y="4"
              fill="var(--put)"
              font-size="10"
              font-family="monospace"
              font-weight="700"
            >
              ${{ num(putWall, 1) }} PUT W
            </text>
          </g>
          <!-- Active Target Badge -->
          <g
            v-if="latestSignal && latestSignal.take_profit > 0"
            :transform="`translate(${chartWidth - pad.right + 6}, ${scaleY(latestSignal.take_profit)})`"
          >
            <rect
              x="0"
              y="-9"
              width="118"
              height="18"
              rx="2"
              fill="var(--panel-hi)"
              stroke="var(--call-hi)"
              stroke-width="1"
            />
            <text
              x="6"
              y="4"
              fill="var(--call-hi)"
              font-size="10"
              font-family="monospace"
              font-weight="700"
            >
              ${{ num(latestSignal.take_profit, 1) }} TARGET
            </text>
          </g>
          <!-- Active Stop Badge -->
          <g
            v-if="latestSignal && latestSignal.stop_loss > 0"
            :transform="`translate(${chartWidth - pad.right + 6}, ${scaleY(latestSignal.stop_loss)})`"
          >
            <rect
              x="0"
              y="-9"
              width="118"
              height="18"
              rx="2"
              fill="var(--panel-hi)"
              stroke="var(--put-hi)"
              stroke-width="1"
            />
            <text
              x="6"
              y="4"
              fill="var(--put-hi)"
              font-size="10"
              font-family="monospace"
              font-weight="700"
            >
              ${{ num(latestSignal.stop_loss, 1) }} STOP
            </text>
          </g>
        </g>

        <!-- Y-Axis Price Labels (Left) -->
        <g class="y-axis-labels">
          <text
            v-for="tick in yTicks"
            :key="tick.val"
            :x="pad.left - 10"
            :y="tick.y + 4"
            text-anchor="end"
            fill="var(--ink-dim)"
            font-size="11"
            font-family="monospace"
          >
            ${{ tick.val.toFixed(1) }}
          </text>
        </g>

        <!-- X-Axis Date Labels (Bottom) -->
        <g class="x-axis-labels">
          <text
            v-for="tick in xTicks"
            :key="tick.rawTime"
            :x="tick.x"
            :y="chartHeight - 10"
            text-anchor="middle"
            fill="var(--ink-dim)"
            font-size="11"
            font-family="monospace"
          >
            {{ tick.label }}
          </text>
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.stale-signal-note {
  margin: 0 0 var(--s2);
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.5;
}

.envelope-chart-container {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
  width: 100%;
}

.chart-hud {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1.25rem;
  padding: 0.5rem 0.875rem;
  background: var(--panel-hi);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  font-size: 0.75rem;
}

.hud-item {
  display: flex;
  align-items: baseline;
  gap: 0.375rem;
}

.hud-k {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: 0.04em;
}

.hud-v {
  color: var(--ink);
}

.hud-signal {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.125rem 0.5rem;
  border-radius: 3px;
  font-family: var(--font-mono, monospace);
  font-size: var(--t-micro);
  font-weight: 600;
  margin-left: auto;
}

.hud-signal.ENTER_LONG {
  background: var(--call-wash);
  border: 1px solid var(--call);
  color: var(--call);
}

.hud-signal.ENTER_SHORT {
  background: var(--put-wash);
  border: 1px solid var(--put);
  color: var(--put);
}

.chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 1.25rem;
  font-size: 0.75rem;
  color: var(--ink-dim);
  font-family: var(--font-mono, monospace);
  padding: 0.375rem 0.75rem;
  background: var(--panel);
  border: 1px solid var(--rule-faint);
  border-radius: var(--r-sm);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.swatch {
  width: 14px;
  height: 3px;
  border-radius: 1px;
}

.swatch.price {
  background: var(--ink);
  height: 2px;
}

.swatch.nw-mean {
  background: var(--phosphor);
  height: 2px;
}

.swatch.nw-env {
  background: var(--phosphor-wash);
  height: 8px;
  border: 1px solid var(--phosphor);
}

.swatch.vwap {
  background: var(--warn);
  height: 2px;
}

.swatch.call-wall {
  background: var(--call);
  height: 2px;
}

.swatch.put-wall {
  background: var(--put);
  height: 2px;
}

.swatch.gamma-flip {
  background: var(--warn);
  height: 2px;
}

.svg-canvas-wrapper {
  width: 100%;
  position: relative;
  overflow: hidden;
}

.chart-svg {
  width: 100%;
  height: auto;
  display: block;
  background: var(--void-lift);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  cursor: crosshair;
}

.text-phosphor {
  color: var(--phosphor);
}

.text-call-hi {
  color: var(--call-hi);
}

.text-ink-dim {
  color: var(--ink-dim);
}

.text-emerald {
  color: var(--long);
}

.text-rose {
  color: var(--short);
}
</style>
