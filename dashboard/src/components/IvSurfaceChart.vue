<script setup lang="ts">
/**
 * IV smile by strike — where the options market prices uncertainty.
 *   · Call IV trace  = call-emerald, put IV trace = put-crimson
 *   · ATM baseline    = faint rule at the summary's ATM IV
 *   · IV walls        = solid dots on each side (peak IV above ATM with size)
 * Skew readout: negative skew = puts bid over calls (crash premium).
 */
import { computed, ref } from 'vue'
import type { IvStrikeRow, IvSurfaceSummary } from '@/api'
import { linearScale, niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'
import { num } from '@/format'

const props = defineProps<{
  rows: IvStrikeRow[]
  spot: number | null
  summary: IvSurfaceSummary | null
}>()

const hostRef = ref<HTMLDivElement | null>(null)
const { W } = useChartSize(hostRef, {
  minW: 240,
  minH: 200,
  fallbackW: 560,
  fallbackH: 260,
})
const H = computed(() => Math.max(200, W.value * 0.46))

const pad = computed(() => ({
  l: props.spot != null && W.value > 420 ? 56 : 48,
  r: 14,
  t: 18,
  b: 26,
}))

const ordered = computed(() =>
  [...props.rows].filter((r) => Number.isFinite(r.strike)).sort((a, b) => a.strike - b.strike),
)

const strikeDomain = computed(() => {
  const strikes = ordered.value.map((r) => r.strike)
  if (!strikes.length) return { lo: 0, hi: 1 }
  const lo = Math.min(...strikes)
  const hi = Math.max(...strikes)
  if (lo === hi) return { lo: lo - 1, hi: hi + 1 }
  const padAmt = (hi - lo) * 0.05
  return { lo: lo - padAmt, hi: hi + padAmt }
})

const xScale = computed(() =>
  linearScale([strikeDomain.value.lo, strikeDomain.value.hi], [pad.value.l, W.value - pad.value.r]),
)

const ivValues = computed(() =>
  ordered.value.flatMap((r) => [r.call_iv, r.put_iv].filter((v): v is number => v != null)),
)

const ivDomain = computed(() => {
  const values = ivValues.value
  if (!values.length) return { lo: 0, hi: 1 }
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const span = Math.max(hi - lo, hi * 0.05, 0.005)
  return { lo: Math.max(0, lo - span * 0.15), hi: hi + span * 0.15 }
})

const yScale = computed(() =>
  linearScale([ivDomain.value.lo, ivDomain.value.hi], [H.value - pad.value.b, pad.value.t]),
)

const ivTicks = computed(() => niceTicks(ivDomain.value.lo, ivDomain.value.hi, 4))

function pts(side: 'call_iv' | 'put_iv') {
  return ordered.value
    .filter((r) => r[side] != null)
    .map((r) => ({ x: xScale.value(r.strike), y: yScale.value(r[side] as number) }))
}

const callPath = computed(() => pts('call_iv'))
const putPath = computed(() => pts('put_iv'))

function pathStr(points: { x: number; y: number }[]): string {
  if (!points.length) return ''
  return points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
}

const spotX = computed(() => {
  const s = props.spot
  if (s == null || s < strikeDomain.value.lo || s > strikeDomain.value.hi) return null
  return xScale.value(s)
})

const atmY = computed(() => {
  const v = props.summary?.atm_iv
  if (v == null || v < ivDomain.value.lo || v > ivDomain.value.hi) return null
  return yScale.value(v)
})

interface Wall {
  side: 'call' | 'put'
  strike: number
  x: number
  y: number
}
const walls = computed<Wall[]>(() => {
  const out: Wall[] = []
  const cs = props.summary?.call_iv_wall
  if (cs != null) {
    const row = ordered.value.find((r) => r.strike === cs && r.call_iv != null)
    if (row)
      out.push({
        side: 'call',
        strike: cs,
        x: xScale.value(cs),
        y: yScale.value(row.call_iv as number),
      })
  }
  const ps = props.summary?.put_iv_wall
  if (ps != null) {
    const row = ordered.value.find((r) => r.strike === ps && r.put_iv != null)
    if (row)
      out.push({
        side: 'put',
        strike: ps,
        x: xScale.value(ps),
        y: yScale.value(row.put_iv as number),
      })
  }
  return out
})

/** Median skew across matched strikes — the crash-premium read. */
const skewReadout = computed(() => {
  const skews = ordered.value.map((r) => r.skew).filter((s): s is number => s != null)
  if (!skews.length) return null
  const sorted = [...skews].sort((a, b) => a - b)
  const median = sorted[Math.floor(sorted.length / 2)]
  if (median < -0.01)
    return {
      label: 'PUT SKEW',
      note: 'puts priced over calls — downside protection bid',
      tone: 'neg' as const,
    }
  if (median > 0.01)
    return {
      label: 'CALL SKEW',
      note: 'calls priced over puts — upside chase bid',
      tone: 'pos' as const,
    }
  return {
    label: 'FLAT SKEW',
    note: 'calls and puts priced evenly near the money',
    tone: 'flat' as const,
  }
})
</script>

<template>
  <div class="iv-wrap">
    <div ref="hostRef" class="host">
      <svg
        :width="W"
        :height="H"
        :viewBox="`0 0 ${W} ${H}`"
        role="img"
        aria-label="Implied volatility by strike"
      >
        <!-- iv ticks -->
        <g v-for="tick in ivTicks" :key="`y${tick}`">
          <line
            :x1="pad.l"
            :x2="W - pad.r"
            :y1="yScale(tick)"
            :y2="yScale(tick)"
            stroke="var(--rule-faint)"
            stroke-width="1"
          />
          <text :x="pad.l - 6" :y="yScale(tick) + 3" text-anchor="end" class="axis fig">
            {{ (tick * 100).toFixed(0) }}%
          </text>
        </g>

        <!-- atm baseline -->
        <line
          v-if="atmY != null"
          :x1="pad.l"
          :x2="W - pad.r"
          :y1="atmY"
          :y2="atmY"
          stroke="var(--ink-faint)"
          stroke-width="1"
          stroke-dasharray="3 4"
        />
        <text v-if="atmY != null" :x="pad.l + 4" :y="atmY - 4" class="axis fig">ATM</text>

        <!-- traces -->
        <path :d="pathStr(callPath)" fill="none" stroke="var(--call)" stroke-width="1.75" />
        <path :d="pathStr(putPath)" fill="none" stroke="var(--put)" stroke-width="1.75" />

        <!-- dots -->
        <g v-for="row in ordered" :key="`c${row.strike}`">
          <circle
            v-if="row.call_iv != null"
            :cx="xScale(row.strike)"
            :cy="yScale(row.call_iv)"
            r="2.4"
            fill="var(--call)"
          />
          <circle
            v-if="row.put_iv != null"
            :cx="xScale(row.strike)"
            :cy="yScale(row.put_iv)"
            r="2.4"
            fill="var(--put)"
          />
        </g>

        <!-- iv walls -->
        <g v-for="wall in walls" :key="wall.side">
          <circle
            :cx="wall.x"
            :cy="wall.y"
            r="5"
            :fill="wall.side === 'call' ? 'var(--call-hi)' : 'var(--put-hi)'"
            :stroke="'var(--panel)'"
            stroke-width="1.5"
          />
          <text
            :x="wall.x"
            :y="wall.y - 10"
            text-anchor="middle"
            :class="['axis', 'fig', wall.side === 'call' ? 'call-label' : 'put-label']"
          >
            IV WALL {{ num(wall.strike, 0) }}
          </text>
        </g>

        <!-- spot -->
        <g v-if="spotX != null">
          <line
            :x1="spotX"
            :x2="spotX"
            :y1="pad.t"
            :y2="H - pad.b"
            stroke="var(--phosphor)"
            stroke-width="1.5"
          />
          <text
            :x="spotX + (spotX > W / 2 ? -6 : 6)"
            :text-anchor="spotX > W / 2 ? 'end' : 'start'"
            :y="pad.t + 10"
            class="axis fig spot-label"
          >
            SPOT
          </text>
        </g>

        <!-- strike axis -->
        <g v-for="tick in niceTicks(strikeDomain.lo, strikeDomain.hi, 5)" :key="`x${tick}`">
          <text
            v-if="tick >= strikeDomain.lo && tick <= strikeDomain.hi"
            :x="xScale(tick)"
            :y="H - pad.b + 16"
            text-anchor="middle"
            class="axis fig"
          >
            {{ num(tick, 0) }}
          </text>
        </g>
      </svg>
    </div>

    <div class="legend mono">
      <span class="legend-item"><span class="swatch call" />CALL IV</span>
      <span class="legend-item"><span class="swatch put" />PUT IV</span>
      <span v-if="skewReadout" class="skew" :class="skewReadout.tone">
        {{ skewReadout.label }} · {{ skewReadout.note }}
      </span>
    </div>
    <p class="method-note">
      OI+volume weighted mean IV per strike{{ summary?.method ? ` · ${summary.method}` : '' }}
      <template v-if="summary?.available === false"> · no usable IV quotes</template>
    </p>
  </div>
</template>

<style scoped>
.iv-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  min-width: 0;
}

.host {
  width: 100%;
  overflow: hidden;
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

.call-label {
  fill: var(--call-hi);
}

.put-label {
  fill: var(--put-hi);
}

.spot-label {
  fill: var(--phosphor);
}

.legend {
  display: flex;
  gap: var(--s3);
  align-items: center;
  flex-wrap: wrap;
  font-size: var(--t-micro);
  color: var(--ink-soft);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  letter-spacing: 0.05em;
}

.swatch {
  width: 12px;
  height: 2px;
  display: inline-block;
}

.swatch.call {
  background: var(--call);
}

.swatch.put {
  background: var(--put);
}

.skew {
  letter-spacing: 0.04em;
}

.skew.neg {
  color: var(--warn);
}

.skew.pos {
  color: var(--phosphor);
}

.skew.flat {
  color: var(--ink-dim);
}

.method-note {
  margin: 0;
  color: var(--ink-faint);
  font-size: var(--t-micro);
}
</style>
