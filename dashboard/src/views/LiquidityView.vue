<script setup lang="ts">
import { computed, onServerPrefetch, ref, watch } from 'vue'
import { api } from '@/api'
import type {
  LiquidityAnalysisResult,
  LiquidityAnalyzeFailure,
  LiquidityAnalyzeSuccess,
  LiquidityBar,
  LiquidityPool,
  LiquidityRange,
  LiquidityStop,
  LiquiditySweepWatch,
  LiquidityTimeframe,
} from '@/liquidityContracts'
import { useResource } from '@/composables/useResource'
import { useChartSize } from '@/composables/useChartSize'
import { linearScale, niceTicks, candlePath, type CandleBar } from '@/charts'
import { num, pctFrac, DASH } from '@/format'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'

/**
 * Liquidity workspace — where stops are likely resting around the live price,
 * whether a sweep of them looks near, which way completed sweeps lean, and a
 * stop placed beyond the pool instead of on it. Backed by
 * GET /api/liquidity/analyze (research/liquidity_map.py); spec in
 * docs/LIQUIDITY_TAB_CONTRACT.md.
 *
 * Honesty rules carried into the UI: pools are inferred from OHLCV structure
 * (never "orders"); a rate is shown only with its counted n, otherwise the row
 * says "not enough history" with the n and the engine's reason; every null
 * renders as DASH, never a plausible stand-in.
 */

const LIVE_POLL_MS = 30_000
/** Session range on 1h can be a handful of bars; keep enough candles to read structure. */
const MIN_VISIBLE_BARS = 60

const TIMEFRAMES: { value: LiquidityTimeframe; label: string }[] = [
  { value: '1m', label: '1m' },
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '1h', label: '1h' },
]
const RANGES: { value: LiquidityRange; label: string }[] = [
  { value: 'session', label: 'Session' },
  { value: '2d', label: '2D' },
  { value: '5d', label: '5D' },
  { value: '10d', label: '10D' },
]

const symbolInput = ref('SPY')
const activeSymbol = ref('SPY')
const timeframe = ref<LiquidityTimeframe>('5m')
const range = ref<LiquidityRange>('session')
const live = ref(false)

/* Polling only runs while GO LIVE is on; useResource already skips ticks while
   the tab is hidden and refreshes once on return (gated by the same flag). */
const analysis = useResource<LiquidityAnalysisResult>(
  () => api.liquidityAnalyze(activeSymbol.value, timeframe.value, range.value),
  { intervalMs: LIVE_POLL_MS, immediate: false, enabled: () => live.value },
)
const firstLoad = analysis.refresh({ clear: true })
/* No-op in the browser; lets a server render (and the view test) await the first payload. */
onServerPrefetch(() => firstLoad)

watch([timeframe, range], () => {
  void analysis.refresh({ clear: true })
})

function run(): void {
  const sym = symbolInput.value.trim().toUpperCase()
  if (!sym) return
  symbolInput.value = sym
  activeSymbol.value = sym
  void analysis.refresh({ clear: true })
}

function toggleLive(): void {
  live.value = !live.value
  if (live.value) void analysis.refresh()
}

const result = computed<LiquidityAnalysisResult | null>(() => analysis.data.value)
const failure = computed<LiquidityAnalyzeFailure | null>(() => {
  const r = result.value
  return r && r.available === false ? r : null
})
const ok = computed<LiquidityAnalyzeSuccess | null>(() => {
  const r = result.value
  if (!r || r.available !== true) return null
  // A late response for the previous symbol must not paint under the new one.
  if (r.symbol && r.symbol.toUpperCase() !== activeSymbol.value) return null
  return r
})

/* ------------------------------------------------------------------ formatting */

function sideLabel(side: string): string {
  if (side === 'buy_stops') return 'Buy stops'
  if (side === 'sell_stops') return 'Sell stops'
  return side
}
function sideShort(side: string): string {
  if (side === 'buy_stops') return 'Buy'
  if (side === 'sell_stops') return 'Sell'
  return side
}
function sideClass(side: string): string {
  return side === 'buy_stops' ? 'is-buy' : side === 'sell_stops' ? 'is-sell' : ''
}
function statusLabel(status: string): string {
  if (status === 'resting') return 'Resting'
  if (status === 'swept_reclaimed') return 'Swept · reclaimed'
  if (status === 'swept_accepted') return 'Swept · accepted'
  return status
}

const SOURCE_LABELS: Record<string, string> = {
  swing_high: 'Swing H',
  swing_low: 'Swing L',
  equal_highs: 'Equal H',
  equal_lows: 'Equal L',
  prior_session_high: 'Prior sess H',
  prior_session_low: 'Prior sess L',
  opening_range_high: 'OR H',
  opening_range_low: 'OR L',
  value_area_high: 'VAH',
  value_area_low: 'VAL',
  round_number: 'Round',
}
function sourceLabel(s: string): string {
  return SOURCE_LABELS[s] ?? s.replace(/_/g, ' ')
}

function directionTone(d: string): string {
  if (d === 'long') return 'tone-long'
  if (d === 'short') return 'tone-short'
  return 'tone-neutral'
}

function timeLabel(ts: string | null | undefined): string {
  if (!ts) return DASH
  const d = new Date(ts)
  if (!Number.isFinite(d.getTime())) return DASH
  return d.toLocaleString('en-US', {
    timeZone: 'America/New_York',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function atrText(v: number | null | undefined): string {
  return v == null ? DASH : `${num(v, 2)} ATR`
}

const minSamples = computed<number | null>(() => {
  const v = ok.value?.thresholds?.min_samples
  return typeof v === 'number' && Number.isFinite(v) ? v : null
})

/** The single phrasing for a rate withheld by the engine. Always carries n. */
function notEnoughHistory(n: number | null | undefined): string {
  const floor = minSamples.value != null ? `, need ${minSamples.value}` : ''
  return `not enough history (n=${n == null ? DASH : n}${floor})`
}

const priceSub = computed(() => {
  const p = ok.value?.price
  if (!p) return ''
  const src = p.source ?? 'source unknown'
  return p.stale_seconds == null ? src : `${src} · ${Math.round(p.stale_seconds)}s old`
})

const basisBadge = computed(() => {
  const r = ok.value
  if (!r) return { cls: 'badge-structure', text: '' }
  if (r.bias.confidence_basis === 'counted_history') {
    const n = r.calibration?.sweep_reclaim_follow_through?.n
    return { cls: 'badge-counted', text: n != null ? `Counted history · n=${n}` : 'Counted history' }
  }
  return { cls: 'badge-structure', text: 'Structure only' }
})

const followThrough = computed(() => {
  const c = ok.value?.calibration
  if (!c) return null
  const f = c.sweep_reclaim_follow_through
  const source =
    c.source === 'symbol_history'
      ? 'this symbol’s history'
      : c.source === 'study_file'
        ? 'the calibration study'
        : 'no calibration source'
  if (f && f.rate != null && f.n != null) {
    return {
      enough: true,
      text: `Reclaimed sweeps followed through in ${pctFrac(f.rate, 0)} of n=${f.n} (horizon ${f.horizon_bars ?? DASH} bars, ${source}).`,
      reason: null as string | null,
    }
  }
  return {
    enough: false,
    text: `Sweep-reclaim follow-through: ${notEnoughHistory(f?.n)} (${source}).`,
    reason: f?.reason ?? c.sweep_reclaim_follow_through_reason ?? c.reason ?? null,
  }
})

const poolById = computed(() => new Map((ok.value?.pools ?? []).map((p) => [p.id, p])))

interface WatchRow {
  item: LiquiditySweepWatch
  levelText: string
  enough: boolean
  rateText: string
  detail: string
}
const watchRows = computed<WatchRow[]>(() =>
  (ok.value?.sweep_watch ?? []).map((w) => {
    const pool = poolById.value.get(w.pool_id)
    const br = w.base_rate
    if (br && br.p_touch != null && br.n != null) {
      return {
        item: w,
        levelText: pool ? num(pool.level, 2) : w.pool_id,
        enough: true,
        rateText: pctFrac(br.p_touch, 0),
        detail: `reached the pool within ${br.within_bars ?? DASH} bars · n=${br.n}`,
      }
    }
    return {
      item: w,
      levelText: pool ? num(pool.level, 2) : w.pool_id,
      enough: false,
      rateText: notEnoughHistory(br?.n),
      detail: br?.reason ?? w.base_rate_reason ?? w.reason ?? '',
    }
  }),
)

const watchMeta = computed(() => {
  const watchAtr = ok.value?.thresholds?.watch_atr
  return typeof watchAtr === 'number' ? `resting pools within ${watchAtr} ATR` : 'resting pools near price'
})

function stopMethodLabel(stop: LiquidityStop): string {
  if (stop.method === 'beyond_pool') {
    return stop.beyond_pool_id ? `Beyond pool ${stop.beyond_pool_id}` : 'Beyond pool'
  }
  if (stop.method === 'atr_fallback') return 'ATR fallback · no pool in reach'
  return stop.method
}

const stopSides = computed(() => {
  const s = ok.value?.stops
  return [
    { key: 'long', title: 'Long stop', tone: 'tone-long', stop: s?.long ?? null },
    { key: 'short', title: 'Short stop', tone: 'tone-short', stop: s?.short ?? null },
  ]
})

type PoolTableRow = { kind: 'pool'; pool: LiquidityPool } | { kind: 'last' }
/** Buy-stop pools (above price) high→low, the last price, then sell-stop pools. */
const poolTableRows = computed<PoolTableRow[]>(() => {
  const pools = [...(ok.value?.pools ?? [])].sort((a, b) => b.level - a.level)
  const above = pools.filter((p) => p.side === 'buy_stops')
  const below = pools.filter((p) => p.side !== 'buy_stops')
  return [
    ...above.map((pool): PoolTableRow => ({ kind: 'pool', pool })),
    { kind: 'last' },
    ...below.map((pool): PoolTableRow => ({ kind: 'pool', pool })),
  ]
})

const profileNote = computed(() => {
  const p = ok.value?.profile
  if (!p) return ''
  const method =
    p.method === 'bar_range_distribution'
      ? 'each bar’s volume is spread evenly across its high–low range'
      : p.method
  return `Profile: ${method}; ${p.bars_used} bars, ${timeLabel(p.range_start)} → ${timeLabel(p.range_end)}, bin ${num(p.bin_size, 2)}.`
})

/* ------------------------------------------------------------------ chart */

const hostRef = ref<HTMLDivElement | null>(null)
const { W, H } = useChartSize(hostRef, { minW: 360, minH: 360, fallbackW: 820, fallbackH: 460 })

const pad = { l: 52, r: 88, t: 14, b: 24 }
const GAP = 8

const plotX0 = pad.l
const plotX1 = computed(() => Math.max(plotX0 + 120, W.value - pad.r))
const profileW = computed(() => Math.max(40, Math.min(160, (plotX1.value - plotX0) * 0.2)))
const candleX1 = computed(() => plotX1.value - profileW.value - GAP)

function tsMs(ts: string | null | undefined): number | null {
  if (!ts) return null
  const v = Date.parse(ts)
  return Number.isFinite(v) ? v : null
}

/** Candles cover the profile range (so the histogram and the bars describe the same
 *  auction), widened to MIN_VISIBLE_BARS when the range is short. */
const visibleStart = computed(() => {
  const all = ok.value?.bars ?? []
  const startMs = tsMs(ok.value?.profile.range_start)
  let start = 0
  if (startMs != null) {
    const i = all.findIndex((b) => {
      const t = tsMs(b.ts)
      return t != null && t >= startMs
    })
    start = i >= 0 ? i : all.length
  }
  return Math.max(0, Math.min(start, all.length - MIN_VISIBLE_BARS))
})
const visibleBars = computed<LiquidityBar[]>(() => (ok.value?.bars ?? []).slice(visibleStart.value))

const priceDomain = computed<[number, number]>(() => {
  const r = ok.value
  if (!r) return [0, 1]
  const vals: number[] = []
  for (const b of visibleBars.value) {
    if (b.low != null) vals.push(b.low)
    if (b.high != null) vals.push(b.high)
  }
  for (const p of r.pools) vals.push(p.zone_lo, p.zone_hi)
  const refs = [
    r.profile.poc,
    r.profile.vah,
    r.profile.val,
    r.price.last,
    r.stops.long?.suggested,
    r.stops.short?.suggested,
  ]
  for (const v of refs) if (v != null) vals.push(v)
  const finite = vals.filter((v) => Number.isFinite(v))
  if (!finite.length) return [0, 1]
  const lo = Math.min(...finite)
  const hi = Math.max(...finite)
  const padAmt = (hi - lo) * 0.04 || Math.abs(hi) * 0.001 || 1
  return [lo - padAmt, hi + padAmt]
})

const yScale = computed(() => linearScale(priceDomain.value, [H.value - pad.b, pad.t]))
const priceTicks = computed(() => niceTicks(priceDomain.value[0], priceDomain.value[1], 6))

const xScale = computed(() =>
  linearScale(
    [0, Math.max(visibleBars.value.length - 1, 1)],
    [plotX0 + 4, candleX1.value - 4],
  ),
)

const candleGeom = computed(() => {
  const bars = visibleBars.value
  if (!bars.length) return { up: '', down: '', wicks: '' }
  const halfWidth = Math.max(
    0.6,
    Math.min(5, ((candleX1.value - plotX0) / Math.max(bars.length, 1)) * 0.35),
  )
  const pts: CandleBar[] = []
  bars.forEach((b, i) => {
    if (b.open == null || b.high == null || b.low == null || b.close == null) return
    pts.push({
      x: xScale.value(i),
      o: yScale.value(b.open),
      h: yScale.value(b.high),
      l: yScale.value(b.low),
      c: yScale.value(b.close),
    })
  })
  return candlePath(pts, halfWidth)
})

const timeAxis = computed(() => {
  const bars = visibleBars.value
  if (!bars.length) return null
  return { first: timeLabel(bars[0]?.ts), last: timeLabel(bars[bars.length - 1]?.ts) }
})

function clamp01(v: number): number {
  return Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0
}

const profileRows = computed(() => {
  const p = ok.value?.profile
  if (!p || !p.bins.length) return []
  const maxVol = Math.max(0, ...p.bins.map((b) => (Number.isFinite(b.volume) ? b.volume : 0)))
  if (maxVol <= 0) return []
  return p.bins.map((b, i) => {
    const yTop = yScale.value(b.price_hi)
    const yBot = yScale.value(b.price_lo)
    const w = Math.max(0, (b.volume / maxVol) * profileW.value)
    const isPoc = p.poc != null && p.poc >= b.price_lo && p.poc < b.price_hi
    const inValue = p.vah != null && p.val != null && b.price_mid <= p.vah && b.price_mid >= p.val
    return {
      key: i,
      x: plotX1.value - w,
      y: Math.min(yTop, yBot),
      w,
      h: Math.max(1, Math.abs(yBot - yTop) - 0.5),
      cls: {
        'is-value': inValue,
        'is-poc': isPoc,
        'is-lvn': b.node === 'lvn',
        'is-hvn': b.node === 'hvn',
      },
    }
  })
})

const poolBands = computed(() =>
  (ok.value?.pools ?? []).map((p) => {
    const y0 = yScale.value(p.zone_hi)
    const y1 = yScale.value(p.zone_lo)
    const score = clamp01(p.score)
    return {
      id: p.id,
      sideCls: sideClass(p.side),
      swept: p.status !== 'resting',
      y: Math.min(y0, y1),
      h: Math.max(2, Math.abs(y1 - y0)),
      levelY: yScale.value(p.level),
      labelY: p.side === 'buy_stops' ? Math.min(y0, y1) - 3 : Math.max(y0, y1) + 10,
      fillOpacity: 0.06 + 0.3 * score,
      lineOpacity: 0.35 + 0.65 * score,
      label: `${p.side === 'buy_stops' ? 'BUY STOPS' : 'SELL STOPS'} ${num(p.level, 2)} · ${num(score, 2)}`,
    }
  }),
)

const sweepMarks = computed(() => {
  const r = ok.value
  if (!r) return []
  const bars = visibleBars.value
  const byTs = new Map<string, number>()
  const byMs = new Map<number, number>()
  bars.forEach((b, i) => {
    byTs.set(b.ts, i)
    const t = tsMs(b.ts)
    if (t != null) byMs.set(t, i)
  })
  const out: { key: string; path: string; outcome: string; title: string }[] = []
  for (const s of r.sweeps) {
    let i = byTs.get(s.ts)
    if (i == null) {
      const t = tsMs(s.ts)
      if (t != null) i = byMs.get(t)
    }
    if (i == null || !Number.isFinite(s.extreme)) continue
    const x = xScale.value(i)
    const y = yScale.value(s.extreme)
    const k = 4.5
    // Sell-stop sweep wicks below: marker sits under the wick pointing up. Buy-stop mirrors.
    const path =
      s.side === 'sell_stops'
        ? `M${x} ${y + 2}l${k} ${k * 1.6}h${-2 * k}Z`
        : `M${x} ${y - 2}l${k} ${-k * 1.6}h${-2 * k}Z`
    out.push({
      key: `${s.pool_id}-${s.ts}`,
      path,
      outcome: s.outcome,
      title: `${sideLabel(s.side)} ${num(s.level, 2)} swept to ${num(s.extreme, 2)} · ${s.outcome}${
        s.bars_to_reclaim != null ? ` in ${s.bars_to_reclaim} bars` : ''
      } · ${timeLabel(s.ts)}`,
    })
  }
  return out
})

const stopLines = computed(() => {
  const s = ok.value?.stops
  const out: { key: string; y: number; cls: string; label: string }[] = []
  if (s?.long?.suggested != null) {
    out.push({
      key: 'long',
      y: yScale.value(s.long.suggested),
      cls: 'stop-long',
      label: `LONG STOP ${num(s.long.suggested, 2)}`,
    })
  }
  if (s?.short?.suggested != null) {
    out.push({
      key: 'short',
      y: yScale.value(s.short.suggested),
      cls: 'stop-short',
      label: `SHORT STOP ${num(s.short.suggested, 2)}`,
    })
  }
  return out
})

const refLines = computed(() => {
  const r = ok.value
  if (!r) return []
  const out: { key: string; y: number; cls: string; label: string }[] = []
  const add = (key: string, v: number | null, cls: string, name: string) => {
    if (v != null && Number.isFinite(v)) out.push({ key, y: yScale.value(v), cls, label: `${name} ${num(v, 2)}` })
  }
  add('poc', r.profile.poc, 'poc-line', 'POC')
  add('vah', r.profile.vah, 'va-line', 'VAH')
  add('val', r.profile.val, 'va-line', 'VAL')
  return out
})

const lastY = computed(() => {
  const v = ok.value?.price.last
  return v != null && Number.isFinite(v) ? yScale.value(v) : null
})

const chartMeta = computed(() => {
  const r = ok.value
  if (!r) return ''
  const hidden = r.sweeps.length - sweepMarks.value.length
  const base = `${visibleBars.value.length} of ${r.bars.length} bars · ${r.sweeps.length} sweeps`
  return hidden > 0 ? `${base} (${hidden} before window)` : base
})

const chartState = computed<string | null>(() => {
  if (ok.value) return ok.value.bars.length ? null : 'No bars in this response.'
  if (analysis.loading.value) return 'Loading liquidity map…'
  if (failure.value) return 'No chart: liquidity map unavailable for this request.'
  if (analysis.error.value) return 'No chart: request failed.'
  return 'No data yet.'
})
</script>

<template>
  <div class="liq">
    <div class="controls">
      <input
        v-model="symbolInput"
        class="symbol-input"
        maxlength="10"
        autocomplete="off"
        spellcheck="false"
        placeholder="SYMBOL"
        aria-label="Symbol"
        @keydown.enter="run"
      />
      <button type="button" class="run-btn label" @click="run">
        {{ analysis.loading.value ? 'LOADING…' : 'RUN' }}
      </button>
      <div class="seg" role="group" aria-label="Timeframe">
        <button
          v-for="tf in TIMEFRAMES"
          :key="tf.value"
          type="button"
          class="seg-btn"
          :class="{ on: timeframe === tf.value }"
          :aria-pressed="timeframe === tf.value"
          @click="timeframe = tf.value"
        >
          {{ tf.label }}
        </button>
      </div>
      <div class="seg" role="group" aria-label="Profile range">
        <button
          v-for="r in RANGES"
          :key="r.value"
          type="button"
          class="seg-btn"
          :class="{ on: range === r.value }"
          :aria-pressed="range === r.value"
          @click="range = r.value"
        >
          {{ r.label }}
        </button>
      </div>
      <button
        type="button"
        class="live-btn label"
        :class="{ on: live }"
        :aria-pressed="live"
        @click="toggleLive"
      >
        {{ live ? 'LIVE · 30s' : 'GO LIVE' }}
      </button>
      <span v-if="ok" class="asof label">generated {{ timeLabel(ok.generated_at) }} ET</span>
    </div>

    <p v-if="analysis.error.value" class="err">{{ analysis.error.value }}</p>

    <Panel v-if="failure" label="Liquidity" index="01" meta="unavailable">
      <p class="fail-reason">
        {{ failure.reason ?? 'The engine returned available:false without a reason.' }}
      </p>
    </Panel>

    <div class="liq-grid">
      <div class="main-col">
        <Panel
          v-if="ok"
          :label="`${ok.symbol} · ${ok.timeframe} · bias`"
          index="01"
          :meta="basisBadge.text"
          :live="live"
        >
          <div class="bias-head">
            <span class="bias-dir" :class="directionTone(ok.bias.direction)">
              {{ ok.bias.direction.toUpperCase() }}
            </span>
            <span class="badge" :class="basisBadge.cls">{{ basisBadge.text }}</span>
          </div>
          <p class="bias-summary">{{ ok.bias.summary || DASH }}</p>
          <div class="readouts">
            <Readout label="Last" :value="num(ok.price.last, 2)" :sub="priceSub" />
            <Readout :label="`ATR (${ok.atr.period})`" :value="num(ok.atr.value, 2)" />
            <Readout label="POC" :value="num(ok.profile.poc, 2)" />
            <Readout
              label="VAH / VAL"
              :value="`${num(ok.profile.vah, 2)} / ${num(ok.profile.val, 2)}`"
            />
          </div>
          <table v-if="ok.bias.evidence.length" class="grid evidence">
            <thead>
              <tr>
                <th class="label">Signal</th>
                <th class="label">Lean</th>
                <th class="label num">Weight</th>
                <th class="label">Detail</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(ev, i) in ok.bias.evidence" :key="i" class="evidence-row">
                <td>{{ ev.signal }}</td>
                <td :class="directionTone(ev.direction)">{{ ev.direction }}</td>
                <td class="fig num">{{ num(ev.weight, 2) }}</td>
                <td class="dim">{{ ev.detail }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="note">No evidence lines in this response.</p>
        </Panel>

        <!-- The chart host stays mounted for the life of the view: swapping it with
             v-if strands useChartSize's ResizeObserver on a detached node. -->
        <Panel label="Price · pools · profile" index="02" :meta="chartMeta" flush>
          <div ref="hostRef" class="chart-host">
            <svg
              v-if="ok && ok.bars.length"
              :width="W"
              :height="H"
              :viewBox="`0 0 ${W} ${H}`"
              preserveAspectRatio="none"
              role="img"
              aria-label="Candles with inferred stop-pool zones, sweep markers, suggested stops and a fixed-range volume profile on the right edge."
            >
              <g v-for="t in priceTicks" :key="`pt-${t}`">
                <line :x1="plotX0" :x2="plotX1" :y1="yScale(t)" :y2="yScale(t)" class="grid-line" />
                <text :x="4" :y="yScale(t) + 3" class="axis-label fig">{{ num(t, 2) }}</text>
              </g>

              <g v-for="b in poolBands" :key="`pool-${b.id}`" :class="['pool', b.sideCls]">
                <rect
                  :x="plotX0"
                  :y="b.y"
                  :width="plotX1 - plotX0"
                  :height="b.h"
                  class="pool-zone"
                  :fill-opacity="b.fillOpacity"
                />
                <line
                  :x1="plotX0"
                  :x2="plotX1"
                  :y1="b.levelY"
                  :y2="b.levelY"
                  :class="['pool-edge', { swept: b.swept }]"
                  :stroke-opacity="b.lineOpacity"
                />
                <text :x="plotX0 + 4" :y="b.labelY" class="pool-label">{{ b.label }}</text>
              </g>

              <rect
                v-for="row in profileRows"
                :key="`pb-${row.key}`"
                :x="row.x"
                :y="row.y"
                :width="row.w"
                :height="row.h"
                :class="['profile-bar', row.cls]"
              />

              <path :d="candleGeom.wicks" class="candle-wick" />
              <path :d="candleGeom.up" class="candle-up" />
              <path :d="candleGeom.down" class="candle-down" />

              <g v-for="l in refLines" :key="`ref-${l.key}`">
                <line :x1="plotX0" :x2="plotX1" :y1="l.y" :y2="l.y" :class="['ref-line', l.cls]" />
                <text :x="plotX1 + 4" :y="l.y + 3" :class="['ref-label', l.cls]">{{ l.label }}</text>
              </g>

              <g v-for="s in stopLines" :key="`stop-${s.key}`">
                <line :x1="plotX0" :x2="candleX1" :y1="s.y" :y2="s.y" :class="['stop-line', s.cls]" />
                <text :x="candleX1 - 4" :y="s.y - 3" text-anchor="end" :class="['stop-label', s.cls]">
                  {{ s.label }}
                </text>
              </g>

              <g v-if="lastY != null">
                <line :x1="plotX0" :x2="plotX1" :y1="lastY" :y2="lastY" class="last-line" />
                <text :x="plotX1 + 4" :y="lastY - 4" class="ref-label last-label">
                  LAST {{ num(ok.price.last, 2) }}
                </text>
              </g>

              <path
                v-for="m in sweepMarks"
                :key="`sw-${m.key}`"
                :d="m.path"
                :class="['sweep-mark', `sweep-${m.outcome}`]"
              >
                <title>{{ m.title }}</title>
              </path>

              <g v-if="timeAxis">
                <text :x="plotX0 + 4" :y="H - 8" class="axis-label">{{ timeAxis.first }}</text>
                <text :x="candleX1 - 4" :y="H - 8" text-anchor="end" class="axis-label">
                  {{ timeAxis.last }}
                </text>
              </g>
            </svg>
            <p v-if="chartState" class="chart-state">{{ chartState }}</p>
          </div>
          <div class="legend label">
            <span class="lg"><i class="sw sw-buy" />Buy-stop zone (above price)</span>
            <span class="lg"><i class="sw sw-sell" />Sell-stop zone (below price)</span>
            <span class="lg"><i class="mk mk-reclaimed" />Sweep reclaimed</span>
            <span class="lg"><i class="mk mk-accepted" />Sweep accepted</span>
            <span class="lg"><i class="dash dash-long" />Suggested long stop</span>
            <span class="lg"><i class="dash dash-short" />Suggested short stop</span>
            <span class="lg dim">Zone opacity = pool score</span>
          </div>
        </Panel>
      </div>

      <aside v-if="ok" class="side-col">
        <Panel label="Sweep watch" index="03" :meta="watchMeta">
          <ul v-if="watchRows.length" class="watch-list">
            <li
              v-for="w in watchRows"
              :key="w.item.pool_id"
              class="watch-item"
              :data-pool="w.item.pool_id"
            >
              <div class="watch-head">
                <span class="side-tag" :class="sideClass(w.item.side)">{{ sideLabel(w.item.side) }}</span>
                <span class="fig">{{ w.levelText }}</span>
                <span class="fig dim">{{ atrText(w.item.distance_atr) }}</span>
              </div>
              <div v-if="w.item.drivers.length" class="drivers">
                <span v-for="(d, i) in w.item.drivers" :key="i" class="driver">{{ d }}</span>
              </div>
              <p class="base-rate" :class="{ thin: !w.enough }">
                <template v-if="w.enough">
                  <span class="fig">{{ w.rateText }}</span> {{ w.detail }}
                </template>
                <template v-else>
                  <span>{{ w.rateText }}</span>
                  <span v-if="w.detail" class="dim"> · {{ w.detail }}</span>
                </template>
              </p>
            </li>
          </ul>
          <p v-else class="note">No resting pool inside the watch distance.</p>
        </Panel>

        <Panel label="Stops" index="04" meta="naive vs beyond the pool">
          <div v-for="side in stopSides" :key="side.key" class="stop-block">
            <div class="stop-head">
              <span class="label" :class="side.tone">{{ side.title }}</span>
              <span v-if="side.stop" class="chip">{{ stopMethodLabel(side.stop) }}</span>
            </div>
            <template v-if="side.stop">
              <div class="stop-figs">
                <Readout label="Naive" :value="num(side.stop.naive, 2)" sub="where a sweep hunts" size="sm" />
                <Readout label="Suggested" :value="num(side.stop.suggested, 2)" tone="accent" size="sm" />
                <Readout label="Risk" :value="atrText(side.stop.risk_atr)" size="sm" />
              </div>
              <p class="rationale">{{ side.stop.rationale || DASH }}</p>
            </template>
            <p v-else class="note">No {{ side.key }} stop in this response.</p>
          </div>
        </Panel>

        <Panel label="Pools" index="05" :meta="`${ok.pools.length} inferred`" flush>
          <div class="table-scroll">
            <table v-if="ok.pools.length" class="grid pools">
              <thead>
                <tr>
                  <th class="label num">Level</th>
                  <th class="label">Side</th>
                  <th class="label">Sources</th>
                  <th class="label num">Dist</th>
                  <th class="label num">Score</th>
                  <th class="label">Status</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="(row, i) in poolTableRows" :key="row.kind === 'pool' ? row.pool.id : `last-${i}`">
                  <tr v-if="row.kind === 'pool'" class="pool-row" :class="sideClass(row.pool.side)">
                    <td class="fig num">{{ num(row.pool.level, 2) }}</td>
                    <td class="side-cell">{{ sideShort(row.pool.side) }}</td>
                    <td>
                      <span class="sources">
                        <span v-for="src in row.pool.sources" :key="src" class="src-chip">{{ sourceLabel(src) }}</span>
                        <span v-if="row.pool.thin_liquidity_between" class="src-chip thin-chip">thin path</span>
                      </span>
                    </td>
                    <td class="fig num">{{ num(row.pool.distance.atr, 2) }}</td>
                    <td class="fig num">{{ num(row.pool.score, 2) }}</td>
                    <td :class="['status', `st-${row.pool.status}`]">{{ statusLabel(row.pool.status) }}</td>
                  </tr>
                  <tr v-else class="last-row">
                    <td class="fig num">{{ num(ok.price.last, 2) }}</td>
                    <td colspan="5" class="label">Last price · distance in ATR</td>
                  </tr>
                </template>
              </tbody>
            </table>
            <p v-else class="note pad">No pools within the engine’s max distance.</p>
          </div>
        </Panel>
      </aside>
    </div>

    <footer class="footnote">
      <p>
        Stop pools are inferred from price structure and bar volume — no order-book data. Nothing
        here observes resting stop orders; zones mark where stops tend to sit beyond swings,
        equal highs/lows, session extremes and value-area edges.
      </p>
      <p v-if="ok">{{ profileNote }}</p>
      <p v-if="followThrough" :class="{ thin: !followThrough.enough }">
        {{ followThrough.text }}
        <span v-if="followThrough.reason" class="dim">{{ followThrough.reason }}</span>
      </p>
      <p v-if="ok?.calibration?.notes" class="dim">{{ ok.calibration.notes }}</p>
    </footer>
  </div>
</template>

<style scoped>
.liq {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s2);
}
.symbol-input {
  width: 110px;
  height: 28px;
  padding: 0 8px;
  font: 600 0.85rem var(--font-data);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  color: var(--ink);
}
.run-btn {
  height: 28px;
  padding: 0 var(--s3);
  color: var(--ink-soft);
  border: var(--hair) solid var(--rule-hi);
  background: transparent;
  cursor: pointer;
}
.seg {
  display: flex;
  gap: 2px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.seg-btn {
  min-height: 28px;
  padding: 3px 10px;
  color: var(--ink-dim);
  background: transparent;
  border: none;
  cursor: pointer;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out);
}
.seg-btn:hover {
  color: var(--ink);
  background: var(--panel-hi);
}
.seg-btn.on {
  color: var(--phosphor);
  background: var(--phosphor-wash);
}
.live-btn {
  height: 28px;
  padding: 0 var(--s3);
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: transparent;
  border-radius: var(--r-sm);
  cursor: pointer;
}
.live-btn.on {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
}
.asof {
  color: var(--ink-faint);
}

.err {
  font-size: var(--t-small);
  color: var(--short);
}
.fail-reason {
  font-size: var(--t-body);
  color: var(--ink-soft);
}

.liq-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(20rem, 25rem);
  gap: var(--s4);
  align-items: start;
}
.main-col,
.side-col {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  min-width: 0;
}

.tone-long {
  color: var(--long);
}
.tone-short {
  color: var(--short);
}
.tone-neutral {
  color: var(--ink-dim);
}

.bias-head {
  display: flex;
  align-items: baseline;
  gap: var(--s3);
}
.bias-dir {
  font-family: var(--font-display);
  font-size: var(--t-fig-lg);
  font-weight: 700;
  letter-spacing: -0.01em;
}
.badge {
  padding: 2px 8px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-capsule);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.badge-counted {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}
.badge-structure {
  color: var(--warn);
  border-color: var(--warn);
}
.bias-summary {
  margin: var(--s2) 0 var(--s3);
  font-size: var(--t-body);
  color: var(--ink-soft);
  max-width: 80ch;
}
.readouts {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(8.5rem, 1fr));
  gap: var(--s3);
  margin-bottom: var(--s3);
}
.evidence td {
  font-size: var(--t-small);
}

.chart-host {
  position: relative;
  width: 100%;
  height: 460px;
  overflow: hidden;
}
.chart-host svg {
  display: block;
}
.chart-state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  font-size: var(--t-small);
  color: var(--ink-dim);
}
.grid-line {
  stroke: var(--rule-faint);
  stroke-width: 1;
}
.axis-label {
  fill: var(--ink-faint);
  font-size: var(--t-micro);
}
.pool.is-buy .pool-zone {
  fill: var(--call);
}
.pool.is-sell .pool-zone {
  fill: var(--put);
}
.pool-edge {
  stroke-width: 1;
}
.pool.is-buy .pool-edge {
  stroke: var(--call);
}
.pool.is-sell .pool-edge {
  stroke: var(--put);
}
.pool-edge.swept {
  stroke-dasharray: 2 3;
}
.pool-label {
  font-size: var(--t-micro);
  letter-spacing: 0.03em;
}
.pool.is-buy .pool-label {
  fill: var(--call);
}
.pool.is-sell .pool-label {
  fill: var(--put);
}
.profile-bar {
  fill: var(--panel-raise);
}
.profile-bar.is-value {
  fill: var(--phosphor-dim);
}
.profile-bar.is-lvn {
  fill: var(--rule);
}
.profile-bar.is-poc {
  fill: var(--phosphor);
}
.candle-up {
  fill: var(--long);
}
.candle-down {
  fill: var(--short);
}
.candle-wick {
  stroke: var(--ink-faint);
  stroke-width: 1;
  fill: none;
}
.ref-line {
  stroke-width: 1;
  stroke-dasharray: 4 3;
}
.ref-line.poc-line {
  stroke: var(--phosphor);
}
.ref-line.va-line {
  stroke: var(--ink-ghost);
}
.ref-label {
  font-size: var(--t-micro);
  letter-spacing: 0.03em;
}
.ref-label.poc-line {
  fill: var(--phosphor);
}
.ref-label.va-line {
  fill: var(--ink-faint);
}
.last-line {
  stroke: var(--ink-soft);
  stroke-width: 1.25;
}
.last-label {
  fill: var(--ink-soft);
}
.stop-line {
  stroke-width: 1.25;
  stroke-dasharray: 6 4;
}
.stop-label {
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.04em;
}
.stop-line.stop-long {
  stroke: var(--long);
}
.stop-line.stop-short {
  stroke: var(--short);
}
.stop-label.stop-long {
  fill: var(--long);
}
.stop-label.stop-short {
  fill: var(--short);
}
.sweep-mark {
  stroke-width: 1.25;
}
.sweep-reclaimed {
  fill: var(--phosphor);
  stroke: var(--phosphor);
}
.sweep-accepted {
  fill: var(--void);
  stroke: var(--warn);
}
.sweep-pending {
  fill: var(--void);
  stroke: var(--ink-faint);
  stroke-dasharray: 2 2;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2) var(--s4);
  padding: var(--s2) var(--s3);
  border-top: var(--hair) solid var(--rule-faint);
  color: var(--ink-dim);
}
.lg {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.sw {
  display: inline-block;
  width: 14px;
  height: 8px;
  border: var(--hair) solid currentColor;
}
.sw-buy {
  color: var(--call);
  background: var(--call-dim);
}
.sw-sell {
  color: var(--put);
  background: var(--put-dim);
}
.mk {
  display: inline-block;
  width: 8px;
  height: 8px;
  border: 1.5px solid currentColor;
}
.mk-reclaimed {
  color: var(--phosphor);
  background: var(--phosphor);
}
.mk-accepted {
  color: var(--warn);
}
.dash {
  display: inline-block;
  width: 16px;
  border-top: 1.5px dashed currentColor;
}
.dash-long {
  color: var(--long);
}
.dash-short {
  color: var(--short);
}

.watch-list {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  margin: 0;
  padding: 0;
  list-style: none;
}
.watch-item {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
  padding-bottom: var(--s3);
  border-bottom: var(--hair) solid var(--rule-faint);
}
.watch-item:last-child {
  padding-bottom: 0;
  border-bottom: none;
}
.watch-head {
  display: flex;
  align-items: baseline;
  gap: var(--s2);
  font-size: var(--t-small);
}
.side-tag {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.side-tag.is-buy,
.pool-row.is-buy .side-cell {
  color: var(--call);
}
.side-tag.is-sell,
.pool-row.is-sell .side-cell {
  color: var(--put);
}
.drivers {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--t-small);
  color: var(--ink-soft);
}
.driver::before {
  content: '· ';
  color: var(--ink-faint);
}
.base-rate {
  margin: 0;
  font-size: var(--t-small);
  color: var(--ink);
}
.base-rate.thin,
.footnote .thin {
  color: var(--warn);
}

.stop-block + .stop-block {
  margin-top: var(--s3);
  padding-top: var(--s3);
  border-top: var(--hair) solid var(--rule-faint);
}
.stop-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s2);
  margin-bottom: var(--s2);
}
.chip,
.src-chip {
  padding: 1px 6px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-capsule);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.03em;
  color: var(--ink-soft);
  white-space: nowrap;
}
.thin-chip {
  color: var(--warn);
  border-color: var(--warn);
}
.stop-figs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s2);
}
.rationale {
  margin: var(--s2) 0 0;
  font-size: var(--t-small);
  color: var(--ink-soft);
}

.table-scroll {
  overflow-x: auto;
}
.pools td {
  font-size: var(--t-small);
  vertical-align: top;
}
.sources {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}
.last-row td {
  color: var(--ink-soft);
  border-top: var(--hair) solid var(--rule-hi);
  border-bottom: var(--hair) solid var(--rule-hi);
}
.status {
  white-space: nowrap;
  color: var(--ink-dim);
}
.st-swept_reclaimed {
  color: var(--phosphor);
}
.st-swept_accepted {
  color: var(--warn);
}

.dim {
  color: var(--ink-faint);
}
.note {
  font-size: var(--t-small);
  color: var(--ink-dim);
}
.pad {
  padding: var(--s3) var(--s4);
}

.footnote {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
  padding-top: var(--s3);
  border-top: var(--hair) solid var(--rule-faint);
  font-size: var(--t-small);
  color: var(--ink-dim);
}
.footnote p {
  margin: 0;
  max-width: 110ch;
}

@media (max-width: 1180px) {
  .liq-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
