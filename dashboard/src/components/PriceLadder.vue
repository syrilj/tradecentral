<script setup lang="ts">
/**
 * The price ladder: every level and every attractor on one vertical scale.
 *
 * Position means price and nothing else, and bar length means gravitational
 * pull. That separation is the whole point — an earlier version of this page
 * drew net gamma as a rising line over a price axis, which read as the stock
 * going up. Here nothing moves along the horizontal except pull.
 *
 * Rungs arrive pre-merged, so a price carrying four roles is one row rather
 * than four identical numbers stacked in two lists.
 */
import { computed, ref } from 'vue'
import { useChartSize } from '@/composables/useChartSize'
import type { Rung } from '@/briefRead'

const props = withDefaults(
  defineProps<{
    spot: number | null
    rungs: Rung[]
    expectedLow?: number | null
    expectedHigh?: number | null
    horizonLabel?: string | null
    /** Reason the frame is withheld; when set, nothing is plotted. */
    unmeasurableReason?: string | null
  }>(),
  { expectedLow: null, expectedHigh: null, horizonLabel: null, unmeasurableReason: null },
)

const host = ref<HTMLElement | null>(null)
const { W } = useChartSize(host, { minW: 280, minH: 260, fallbackW: 620, fallbackH: 300 })

const ROW_H = 26
const PAD_TOP = 22
const PAD_BOTTOM = 16
const PRICE_COL = 66
const BAR_GAP = 10

/** One row per rung plus the spot row, so nothing ever overlaps. */
const H = computed(() => PAD_TOP + PAD_BOTTOM + Math.max(1, rowOrder.value.length) * ROW_H)

const barMax = computed(() => Math.max(60, W.value - PRICE_COL - BAR_GAP - 150))

/**
 * Rows are laid out by rank, not by a linear price scale.
 *
 * A linear axis puts AMD's 400 and 600 rungs at the frame edges and crushes
 * the four rungs that sit within 3% of spot into a few pixels — the ones that
 * actually matter. Even rows keep every rung readable; the signed distance
 * column carries the real geometry, and spot always sits in its true rank
 * order between the rungs above and below it.
 */
interface Row {
  kind: 'rung' | 'spot'
  rung?: Rung
  y: number
}

const rowOrder = computed<Row[]>(() => {
  const spot = props.spot
  const above = props.rungs.filter((r) => r.side === 'above')
  const below = props.rungs.filter((r) => r.side === 'below')
  const rows: Row[] = []
  let i = 0
  for (const r of above) rows.push({ kind: 'rung', rung: r, y: PAD_TOP + i++ * ROW_H })
  if (typeof spot === 'number' && spot > 0) rows.push({ kind: 'spot', y: PAD_TOP + i++ * ROW_H })
  for (const r of below) rows.push({ kind: 'rung', rung: r, y: PAD_TOP + i++ * ROW_H })
  return rows
})

const maxPull = computed(() => Math.max(...props.rungs.map((r) => r.pull ?? 0), 1))

function barWidth(pull: number | null): number {
  if (pull === null || pull <= 0) return 0
  return Math.max(3, (pull / maxPull.value) * barMax.value)
}

function priceLabel(v: number): string {
  return Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(2)
}

/** The expected-move band, as the rank rows it actually spans. */
const emRows = computed(() => {
  const lo = props.expectedLow
  const hi = props.expectedHigh
  if (typeof lo !== 'number' || typeof hi !== 'number' || hi <= lo) return null
  const inside = rowOrder.value.filter(
    (r) => r.kind === 'spot' || (r.rung != null && r.rung.price >= lo && r.rung.price <= hi),
  )
  if (!inside.length) return null
  const top = Math.min(...inside.map((r) => r.y))
  const bottom = Math.max(...inside.map((r) => r.y))
  return { y: top - ROW_H / 2 + 2, h: bottom - top + ROW_H - 4 }
})

const hasFrame = computed(() => !props.unmeasurableReason && props.rungs.length > 0)
</script>

<template>
  <div ref="host" class="ladder">
    <p v-if="!hasFrame" class="withheld">
      {{ unmeasurableReason || 'No levels could be located on this chain.' }}
    </p>

    <svg v-else :viewBox="`0 0 ${W} ${H}`" :height="H" class="frame" role="img">
      <title>Price levels and attractor pull, strongest pull drawn longest</title>

      <text :x="0" :y="12" class="axis-label">PRICE</text>
      <text :x="PRICE_COL + BAR_GAP" :y="12" class="axis-label">
        GRAVITATIONAL PULL{{ horizonLabel ? ` · EXPECTED MOVE ${horizonLabel}` : '' }}
      </text>

      <!-- expected-move band, drawn behind everything -->
      <rect
        v-if="emRows"
        :x="PRICE_COL - 6"
        :y="emRows.y"
        :width="Math.max(0, W - PRICE_COL + 6)"
        :height="emRows.h"
        class="em"
      />

      <g v-for="(row, i) in rowOrder" :key="i">
        <template v-if="row.kind === 'spot'">
          <line :x1="0" :x2="W" :y1="row.y" :y2="row.y" class="spot-line" />
          <text :x="0" :y="row.y - 4" class="spot-price">
            {{ spot === null ? '' : priceLabel(spot) }}
          </text>
          <text :x="PRICE_COL + BAR_GAP" :y="row.y - 4" class="spot-tag">SPOT</text>
        </template>

        <template v-else-if="row.rung">
          <text
            :x="PRICE_COL - 8"
            :y="row.y + 4"
            :class="['rung-price', row.rung.side]"
            text-anchor="end"
          >
            {{ priceLabel(row.rung.price) }}
          </text>

          <rect
            v-if="barWidth(row.rung.pull) > 0"
            :x="PRICE_COL + BAR_GAP"
            :y="row.y - 5"
            :width="barWidth(row.rung.pull)"
            :height="10"
            :class="['bar', row.rung.side]"
            rx="2"
          />
          <line
            v-else
            :x1="PRICE_COL + BAR_GAP"
            :x2="PRICE_COL + BAR_GAP + 10"
            :y1="row.y"
            :y2="row.y"
            class="tick"
          />

          <text
            :x="PRICE_COL + BAR_GAP + Math.max(barWidth(row.rung.pull), 10) + 8"
            :y="row.y + 4"
            class="rung-label"
          >
            {{ row.rung.roles.join(' · ') }}
            <tspan v-if="row.rung.pull !== null" class="rung-pull">
              {{ row.rung.pull.toFixed(0) }}
            </tspan>
            <tspan v-if="row.rung.lenses.length > 1" class="rung-lens">
              {{ row.rung.lenses.length }} lenses
            </tspan>
          </text>

          <text :x="W" :y="row.y + 4" :class="['rung-dist', row.rung.side]" text-anchor="end">
            {{ row.rung.distPct >= 0 ? '+' : '' }}{{ row.rung.distPct.toFixed(1) }}%
          </text>
        </template>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.ladder {
  inline-size: 100%;
  min-inline-size: 0;
}

.frame {
  display: block;
  inline-size: 100%;
}

.withheld {
  padding-block: var(--s3);
  color: var(--ink-faint);
  font-size: var(--t-small);
}

.axis-label {
  fill: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 600;
  letter-spacing: var(--track-label);
}

.em {
  fill: var(--phosphor-wash);
  opacity: 0.35;
}

.spot-line {
  stroke: var(--phosphor);
  stroke-width: 1.2;
}

.spot-price {
  fill: var(--phosphor);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
}

.spot-tag {
  fill: var(--phosphor);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: var(--track-label);
}

.rung-price {
  fill: var(--ink);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 500;
}

.bar.above {
  fill: var(--long);
}

.bar.below {
  fill: var(--short);
}

.tick {
  stroke: var(--ink-faint);
  stroke-width: 2;
}

.rung-label {
  fill: var(--text-secondary);
  font-size: 10px;
}

.rung-pull {
  fill: var(--ink-faint);
  font-family: var(--font-mono);
  font-size: var(--t-nano);
}

.rung-lens {
  fill: var(--phosphor);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: var(--track-label);
}

.rung-dist {
  font-family: var(--font-mono);
  font-size: 10px;
}

.rung-dist.above {
  fill: var(--long);
}

.rung-dist.below {
  fill: var(--short);
}
</style>
