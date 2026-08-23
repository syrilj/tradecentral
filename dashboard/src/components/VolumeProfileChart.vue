<script setup lang="ts">
/**
 * Volume-by-price histogram — where real trading activity stacked up, where
 * it thinned out. Horizontal bars: y = price bin, width = session volume.
 *   · POC        = heaviest bin (solid call-emerald)
 *   · Value area = 70% expansion around POC (washed fill)
 *   · LVN bins   = local-minima thin zones (dim + hatched edge)
 *   · Spot       = phosphor rule
 * Daily-bar approximation of intrabar tape — the summary label says so.
 */
import { computed, ref, useId } from 'vue'
import type { VolumeProfileBin } from '@/api'
import { linearScale, niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'
import { compact, num } from '@/format'

const props = withDefaults(
  defineProps<{
    bins: VolumeProfileBin[]
    spot?: number | null
    poc?: number | null
    valueAreaLow?: number | null
    valueAreaHigh?: number | null
  }>(),
  {
    spot: null,
    poc: null,
    valueAreaLow: null,
    valueAreaHigh: null,
  },
)

const hostRef = ref<HTMLDivElement | null>(null)
const uid = useId()
const { W } = useChartSize(hostRef, {
  minW: 240,
  minH: 220,
  fallbackW: 560,
  fallbackH: 320,
})
const H = computed(() => Math.max(200, W.value * 0.56))

const pad = { l: 8, r: 64, t: 14, b: 22 }

const ordered = computed(() =>
  [...props.bins].filter((b) => Number.isFinite(b.price)).sort((a, b) => b.price - a.price),
) // highest price on top

const priceDomain = computed(() => {
  const lows = ordered.value.map((b) => b.low)
  const highs = ordered.value.map((b) => b.high)
  if (!lows.length) return { lo: 0, hi: 1 }
  return { lo: Math.min(...lows), hi: Math.max(...highs) }
})

const yScale = computed(() =>
  linearScale([priceDomain.value.lo, priceDomain.value.hi], [H.value - pad.b, pad.t]),
)

const volMax = computed(() => Math.max(1, ...ordered.value.map((b) => b.volume)))

const xScale = computed(() => linearScale([0, volMax.value], [pad.l, W.value - pad.r]))

const barH = computed(() => {
  const n = ordered.value.length || 1
  const raw = ((H.value - pad.t - pad.b) / n) * 0.78
  return Math.max(2, Math.min(18, raw))
})

function binClass(bin: VolumeProfileBin): string {
  if (
    props.poc != null &&
    Math.abs((bin.low + bin.high) / 2 - props.poc) < (bin.high - bin.low) / 2 + 1e-9
  ) {
    // exact POC bin only
    if (bin.price === props.bins.find((b) => b.volume === volMax.value)?.price) return 'is-poc'
  }
  if (bin.in_value_area) return 'is-va'
  return 'is-lvn'
}

const ticks = computed(() => niceTicks(0, volMax.value, 3))

const spotY = computed(() => {
  const s = props.spot
  if (s == null || s < priceDomain.value.lo || s > priceDomain.value.hi) return null
  return yScale.value(s)
})

/** Hover readout */
const hoverIdx = ref<number | null>(null)
const hoverBin = computed(() =>
  hoverIdx.value == null ? null : (ordered.value[hoverIdx.value] ?? null),
)

interface Row {
  y: number
  w: number
  cls: string
  pctLabel: string
  inVa: boolean
}
const rows = computed<Row[]>(() =>
  ordered.value.map((b) => ({
    y: yScale.value(b.price),
    w: Math.max(1, xScale.value(b.volume) - pad.l),
    cls: binClass(b),
    pctLabel: b.pct_of_peak == null ? '' : `${Math.round(b.pct_of_peak * 100)}%`,
    inVa: b.in_value_area,
  })),
)
</script>

<template>
  <div class="vp-wrap">
    <div ref="hostRef" class="host">
      <svg
        :width="W"
        :height="H"
        :viewBox="`0 0 ${W} ${H}`"
        role="img"
        aria-label="Volume profile by price"
      >
        <defs>
          <pattern
            :id="`${uid}-lvn`"
            width="6"
            height="6"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <rect width="6" height="6" fill="transparent" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--ink-ghost)" stroke-width="1" />
          </pattern>
        </defs>

        <!-- value area band -->
        <rect
          v-if="valueAreaLow != null && valueAreaHigh != null"
          :x="pad.l"
          :y="yScale(Math.max(valueAreaHigh, valueAreaLow))"
          :width="W - pad.r - pad.l"
          :height="
            Math.max(
              2,
              yScale(Math.min(valueAreaHigh, valueAreaLow)) -
                yScale(Math.max(valueAreaHigh, valueAreaLow)),
            )
          "
          fill="var(--phosphor-wash)"
        />

        <!-- volume ticks -->
        <g v-for="tick in ticks" :key="`t${tick}`">
          <line
            :x1="xScale(tick)"
            :x2="xScale(tick)"
            :y1="pad.t"
            :y2="H - pad.b"
            stroke="var(--rule-faint)"
            stroke-width="1"
          />
          <text :x="xScale(tick)" :y="H - pad.b + 12" text-anchor="middle" class="axis fig">
            {{ compact(tick) }}
          </text>
        </g>

        <!-- bars -->
        <g
          v-for="(row, i) in rows"
          :key="i"
          @mouseenter="hoverIdx = i"
          @mouseleave="hoverIdx = null"
        >
          <rect
            :x="pad.l"
            :y="row.y - barH / 2"
            :width="row.w"
            :height="barH"
            :class="['vp-bar', row.cls]"
            :fill="
              row.cls === 'is-poc'
                ? 'var(--call)'
                : row.cls === 'is-va'
                  ? 'var(--call-dim)'
                  : `url(#${uid}-lvn)`
            "
            :stroke="row.cls === 'is-lvn' ? 'var(--ink-ghost)' : 'none'"
            stroke-width="0.5"
          />
          <!-- LVN tag -->
          <text
            v-if="row.cls === 'is-lvn' && row.w < (W - pad.r - pad.l) * 0.35"
            :x="pad.l + row.w + 4"
            :y="row.y + 3"
            class="axis fig lvn-tag"
          >
            LVN
          </text>
        </g>

        <!-- POC rule -->
        <line
          v-if="poc != null && poc >= priceDomain.lo && poc <= priceDomain.hi"
          :x1="pad.l"
          :x2="W - pad.r"
          :y1="yScale(poc)"
          :y2="yScale(poc)"
          stroke="var(--call-hi)"
          stroke-width="1.25"
          stroke-dasharray="4 3"
        />
        <text
          v-if="poc != null && poc >= priceDomain.lo && poc <= priceDomain.hi"
          :x="W - pad.r + 4"
          :y="yScale(poc) + 3"
          class="axis fig poc-label"
        >
          POC {{ num(poc, 0) }}
        </text>

        <!-- spot rule -->
        <g v-if="spotY != null">
          <line
            :x1="pad.l"
            :x2="W - pad.r"
            :y1="spotY"
            :y2="spotY"
            stroke="var(--phosphor)"
            stroke-width="1.5"
          />
          <text :x="W - pad.r + 4" :y="spotY + 3" class="axis fig spot-label">SPOT</text>
        </g>
      </svg>
    </div>

    <div v-if="hoverBin" class="readout mono fig">
      <span>{{ num(hoverBin.low, 2) }}–{{ num(hoverBin.high, 2) }}</span>
      <span>{{ compact(hoverBin.volume) }} vol</span>
      <span v-if="hoverBin.in_value_area" class="va-chip">VALUE AREA</span>
      <span v-else class="lvn-chip">THIN ZONE</span>
    </div>
    <p class="method-note">
      Daily-bar approximation of intrabar tape · LVNs mark where activity thinned out.
    </p>
  </div>
</template>

<style scoped>
.vp-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  min-width: 0;
}

.host {
  width: 100%;
  overflow: hidden;
}

.vp-bar {
  transition: opacity var(--dur-fast) var(--ease-out);
}

.vp-wrap:hover .vp-bar {
  opacity: 0.55;
}

.vp-wrap:hover .vp-bar:hover {
  opacity: 1;
}

.axis {
  fill: var(--ink-faint);
  font-size: var(--t-micro);
  font-family: var(--font-data);
}

.fig {
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
}

.lvn-tag,
.spot-label,
.poc-label {
  font-size: var(--t-micro);
  letter-spacing: 0.04em;
}

.lvn-tag {
  fill: var(--ink-ghost);
}

.poc-label {
  fill: var(--call-hi);
}

.spot-label {
  fill: var(--phosphor);
}

.readout {
  display: flex;
  gap: var(--s3);
  align-items: center;
  color: var(--ink-soft);
  font-size: var(--t-micro);
}

.va-chip,
.lvn-chip {
  padding: 1px 6px;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
  letter-spacing: 0.05em;
}

.va-chip {
  color: var(--phosphor);
  border-color: color-mix(in srgb, var(--phosphor) 25%, transparent);
}

.lvn-chip {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 30%, transparent);
}

.method-note {
  margin: 0;
  color: var(--ink-ghost);
  font-size: var(--t-micro);
  letter-spacing: 0.02em;
}
</style>
