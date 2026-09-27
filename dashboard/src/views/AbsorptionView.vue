<script setup lang="ts">
/**
 * Heavy Absorption — cross-section screener (`/api/absorption`) as the
 * primary surface, with a per-symbol drill-down (`/api/absorption/{SYMBOL}`)
 * below it. The detector is a streaming, O(1)-per-observation signed-flow
 * proxy (no order-book depth anywhere in this repo) — every score here is an
 * ORDINAL ranking feature, never a probability or a trade authorization.
 *
 * The board ranks by |absorption_score| (magnitude is a tiebreaker only).
 * A row can carry a high `absorption_magnitude` with `absorption_score`
 * pinned at 0 whenever `flow_direction` is flat (no directional read) — the
 * UI must never present magnitude alone as if it were a signal, so every
 * row surfaces `signal` / `flow_direction` / `reversal_direction` alongside
 * it, not just the score.
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type AbsorptionScanPayload,
  type AbsorptionScanRow,
  type AbsorptionSeriesPoint,
  type AbsorptionSymbolPayload,
} from '@/api'
import { useResource } from '@/composables/useResource'
import { useChartSize } from '@/composables/useChartSize'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import LoadingState from '@/components/LoadingState.vue'
import { age, DASH, num, pctFrac, shortDate, signed, signedPct, tone, usd } from '@/format'
import { linearScale, niceTicks, niceDomain, linePath, areaPath } from '@/charts'

const route = useRoute()
const router = useRouter()

/* ==================================================================== *
 * Board — cross-section screener
 * ==================================================================== */

const forceNextScan = ref(false)
const board = useResource<AbsorptionScanPayload>(
  () => {
    const force = forceNextScan.value
    forceNextScan.value = false
    return api.absorptionScan(force ? { force: true } : undefined)
  },
  { intervalMs: 300_000 },
)
const boardData = computed(() => board.data.value)
const boardRows = computed<AbsorptionScanRow[]>(() => boardData.value?.rows ?? [])
const boardHasRows = computed(() => boardRows.value.length > 0)
const boardAge = computed(() => age(boardData.value?.asof))

function refreshBoard(): void {
  forceNextScan.value = true
  void board.refresh({ clear: false })
}

/* ---- signal filter + sort ------------------------------------------------
   Default sort mirrors the corrected backend rank (|score| desc, magnitude
   desc tiebreak) so the board reads right even before that fix is deployed,
   and stays a harmless no-op once it is. */
type SortKey = 'symbol' | 'abs_score' | 'absorption_magnitude' | 'price' | 'vol_ratio' | 'imbalance'
const sortKey = ref<SortKey>('abs_score')
const sortDir = ref<'asc' | 'desc'>('desc')

function setSort(key: SortKey): void {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortKey.value = key
    sortDir.value = key === 'symbol' ? 'asc' : 'desc'
  }
}
function sortArrow(key: SortKey): string {
  if (sortKey.value !== key) return ''
  return sortDir.value === 'asc' ? '▴' : '▾'
}
function sortValue(row: AbsorptionScanRow, key: SortKey): number | string {
  switch (key) {
    case 'symbol':
      return row.symbol
    case 'abs_score':
      return Math.abs(row.absorption_score)
    case 'absorption_magnitude':
      return row.absorption_magnitude
    case 'price':
      return row.price
    case 'vol_ratio':
      return row.vol_ratio
    case 'imbalance':
      return row.imbalance
    default:
      return 0
  }
}

type SignalFilter = 'ALL' | 'SIGNAL' | 'NO_READ'
const signalFilter = ref<SignalFilter>('ALL')
const signalCounts = computed(() => {
  const rows = boardRows.value
  return {
    ALL: rows.length,
    SIGNAL: rows.filter((r) => r.signal).length,
    NO_READ: rows.filter((r) => !r.signal).length,
  }
})

const tableRows = computed(() => {
  let list = boardRows.value
  if (signalFilter.value === 'SIGNAL') list = list.filter((r) => r.signal)
  else if (signalFilter.value === 'NO_READ') list = list.filter((r) => !r.signal)
  const dir = sortDir.value === 'asc' ? 1 : -1
  const key = sortKey.value
  return [...list].sort((a, b) => {
    const av = sortValue(a, key)
    const bv = sortValue(b, key)
    if (typeof av === 'string' || typeof bv === 'string')
      return dir * String(av).localeCompare(String(bv))
    const primary = dir * (av - bv)
    // Backend tiebreak: |score| ties fall back to raw magnitude, descending.
    if (primary !== 0 || key !== 'abs_score') return primary
    return dir * (a.absorption_magnitude - b.absorption_magnitude)
  })
})

/** Glyph only — color comes from the shared `tone()` classes so it matches
 *  every other signed figure on the desk. */
function dirGlyph(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return DASH
  if (n > 0) return '▲'
  if (n < 0) return '▼'
  return '·'
}

function signalLabel(row: AbsorptionScanRow): string {
  if (!row.signal) return 'NO READ'
  if (row.signal_kind === 'sell_absorption') return 'SELL ABS → UP'
  if (row.signal_kind === 'buy_absorption') return 'BUY ABS → DOWN'
  return 'SIGNAL'
}
function signalClass(row: AbsorptionScanRow): string {
  if (!row.signal) return 'no-read'
  return row.signal_kind === 'sell_absorption' ? 'sig-up' : 'sig-down'
}

/* ==================================================================== *
 * Symbol detail — drill-down
 * ==================================================================== */

function cleanTicker(term: string): string {
  return term
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
    .slice(0, 10)
}

const initialSymbol = typeof route.query.symbol === 'string' ? cleanTicker(route.query.symbol) : ''
const searchInput = ref(initialSymbol)
const selectedSymbol = ref<string | null>(initialSymbol || null)

const detail = useResource<AbsorptionSymbolPayload>(
  () => api.absorptionSymbol(selectedSymbol.value ?? ''),
  { immediate: false },
)
const detailData = computed(() => detail.data.value)

function selectSymbol(raw: string, opts: { pushRoute?: boolean } = {}): void {
  const clean = cleanTicker(raw)
  if (!clean) return
  selectedSymbol.value = clean
  searchInput.value = clean
  if (opts.pushRoute !== false) {
    void router.replace({ query: { ...route.query, symbol: clean } })
  }
  void detail.refresh({ clear: true })
}

function submitSearch(): void {
  selectSymbol(searchInput.value)
}

if (initialSymbol) selectSymbol(initialSymbol, { pushRoute: false })

watch(
  () => route.query.symbol,
  (newSym) => {
    if (typeof newSym === 'string') {
      const clean = cleanTicker(newSym)
      if (clean && clean !== selectedSymbol.value) selectSymbol(clean, { pushRoute: false })
    }
  },
)

/* ---- series windowing --------------------------------------------------
   The symbol endpoint windows `series` to `series_limit` most-recent points
   and reports counts both over the full evaluated range (`*_total`/
   `*_total_count`) and within the returned window (`*_window_count`) — see
   AbsorptionSymbolPayload in api.ts. `series_first_ts`/`series_last_ts` are
   the bounds of the FULL range, not the window, so the window's own ts
   bounds are read off the returned `series` array itself. A window with
   zero signals (or zero warming points) while the *_total figure is > 0
   must read as "exists outside this window", never as "none found" — see
   `windowCoverageNote` below. */
const rawSeries = computed<AbsorptionSeriesPoint[]>(() => detailData.value?.series ?? [])

/* ---- order-flow absorption matrix --------------------------------------
   Fixed-range profile over the trailing bars window: liquidity profile
   (buy/sell split, strong-volume shade), delta + absorption columns,
   strength zones and the pressure score. Absent (null) is an explicit
   state — the panel renders nothing, never a fabricated profile. */
const matrix = computed(() => {
  const m = detailData.value?.matrix
  return m && m.available && m.bins?.length ? m : null
})

/** Display order: highest price first. */
const matrixRows = computed(() => (matrix.value ? [...matrix.value.bins].reverse() : []))

const matrixMaxVol = computed(() => Math.max(0, ...matrixRows.value.map((b) => b.total)))
const matrixMaxAbs = computed(() => Math.max(0, ...matrixRows.value.map((b) => b.absorption)))

function widthPct(part: number, whole: number): string {
  if (whole <= 0 || part <= 0) return '0%'
  return `${Math.min(100, (part / whole) * 100).toFixed(1)}%`
}

function fmtCompact(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH
  const av = Math.abs(v)
  const sg = v < 0 ? '-' : ''
  if (av >= 1e9) return `${sg}${(av / 1e9).toFixed(2)}B`
  if (av >= 1e6) return `${sg}${(av / 1e6).toFixed(2)}M`
  if (av >= 1e3) return `${sg}${(av / 1e3).toFixed(1)}K`
  return `${sg}${Math.round(av)}`
}

function zoneStars(strength: number): string {
  if (strength >= 8) return '★★★★★'
  if (strength >= 6.5) return '★★★★'
  if (strength >= 5) return '★★★'
  if (strength >= 3.5) return '★★'
  if (strength >= 2) return '★'
  return '·'
}

function windowCoverageNote(windowCount: number, totalCount: number, noun: string): string {
  if (windowCount === 0 && totalCount > 0)
    return `0 shown — ${num(totalCount, 0)} ${noun} outside this window`
  return `in the returned window`
}

/* ---- chart: bounded render, single O(n) pass over the raw series --------
   The backend was returning the entire history (5,082 points measured for
   AAPL) and the old computed mapped over it three separate times per
   recompute. `buildChart` walks the raw array exactly once — selecting an
   evenly-strided subset capped at MAX_CHART_POINTS, always keeping real
   signal points and the baseline-warming on/off transition — so every
   downstream pixel computation (scales, paths, ticks) runs over a bounded
   array instead of the raw one. */
const MAX_CHART_POINTS = 400

function buildChart(raw: AbsorptionSeriesPoint[]): AbsorptionSeriesPoint[] {
  const n = raw.length
  const keep = new Set<number>()
  const stride = n > MAX_CHART_POINTS ? Math.ceil(n / MAX_CHART_POINTS) : 1
  let prevWarming: boolean | null | undefined = null

  for (let i = 0; i < n; i++) {
    const p = raw[i]
    if (i % stride === 0 || i === n - 1) keep.add(i)
    if (p.signal) keep.add(i)
    if (prevWarming !== null && p.baseline_warming !== prevWarming) {
      keep.add(i)
      keep.add(Math.max(0, i - 1))
    }
    prevWarming = p.baseline_warming
  }

  return Array.from(keep)
    .sort((a, b) => a - b)
    .map((i) => raw[i])
}

const chartPoints = computed(() => buildChart(rawSeries.value))

const seriesWindow = computed(() => {
  const raw = rawSeries.value
  if (!raw.length) return null
  return {
    shownCount: raw.length,
    firstTs: raw[0]?.ts ?? null,
    lastTs: raw[raw.length - 1]?.ts ?? null,
    downsampled: chartPoints.value.length < raw.length,
    renderedCount: chartPoints.value.length,
  }
})

const chartHostRef = ref<HTMLElement | null>(null)
const { W: chartW, H: chartH } = useChartSize(chartHostRef, {
  minH: 220,
  fallbackH: 240,
  minW: 200,
})

const chart = computed(() => {
  const points = chartPoints.value
  if (points.length < 2) return null
  const padTop = 12
  const padBottom = 22
  const padLeft = 52
  const padRight = 12

  const prices = points.map((p) => p.price)
  const priceDomain = niceDomain(Math.min(...prices), Math.max(...prices), 0.05)
  const priceScale = linearScale(priceDomain, [chartH.value - padBottom, padTop])
  const xScale = linearScale(
    [0, points.length - 1],
    [padLeft, Math.max(padLeft + 1, chartW.value - padRight)],
  )

  const linePts = points.map((p, i) => ({ x: xScale(i), y: priceScale(p.price) }))
  const area = areaPath(linePts, chartH.value - padBottom)

  const signals: { x: number; y: number; kind: AbsorptionSeriesPoint['signal_kind'] }[] = []
  let warmX0: number | null = null
  let warmX1: number | null = null
  for (let i = 0; i < points.length; i++) {
    const p = points[i]
    if (p.signal) signals.push({ x: xScale(i), y: priceScale(p.price), kind: p.signal_kind })
    if (p.baseline_warming) {
      if (warmX0 == null) warmX0 = xScale(i)
      warmX1 = xScale(i)
    }
  }
  const warmingRect =
    warmX0 != null
      ? {
          x: padLeft,
          width: Math.max(3, (warmX1 ?? warmX0) - padLeft + 4),
          y: padTop,
          height: chartH.value - padBottom - padTop,
        }
      : null

  const priceTicks = niceTicks(priceDomain[0], priceDomain[1], 5).map((t) => ({
    y: priceScale(t),
    label: num(t, t >= 100 ? 0 : 2),
  }))

  /* Order-flow matrix overlays: strength-zone bands and POC/VAH/VAL levels
     projected through the price scale. Zones/levels outside the chart's
     price domain are dropped rather than drawn off-canvas. These levels are
     computed over the matrix's trailing window (default 220 bars), which is
     a different slice than the chart's series window — full-width bands, not
     claimed per-bar alignment. */
  const zoneBands: { y: number; height: number; cls: string; label: string }[] = []
  const levelLines: { y: number; cls: string; label: string }[] = []
  const mx = matrix.value
  if (mx) {
    for (const z of mx.zones) {
      const yTop = priceScale(z.high)
      const yBot = priceScale(z.low)
      if (!Number.isFinite(yTop) || !Number.isFinite(yBot)) continue
      if (yBot < padTop || yTop > chartH.value - padBottom) continue
      zoneBands.push({
        y: Math.max(padTop, yTop),
        height: Math.min(yBot, chartH.value - padBottom) - Math.max(padTop, yTop),
        cls: z.side === 'support' ? 'zone-sup' : 'zone-res',
        label: `★${z.strength} ${z.side === 'support' ? 'S' : 'R'}`,
      })
    }
    const levels: { price: number | null; cls: string; label: string }[] = [
      { price: mx.poc, cls: 'lv-poc', label: `POC ${num(mx.poc ?? 0, 2)}` },
      { price: mx.vah, cls: 'lv-va', label: 'VAH' },
      { price: mx.val, cls: 'lv-va', label: 'VAL' },
    ]
    for (const lv of levels) {
      if (lv.price == null) continue
      const y = priceScale(lv.price)
      if (!Number.isFinite(y) || y < padTop || y > chartH.value - padBottom) continue
      levelLines.push({ y, cls: lv.cls, label: lv.label })
    }
  }

  return {
    linePath: linePath(linePts),
    area,
    signals,
    priceTicks,
    warmingRect,
    zoneBands,
    levelLines,
  }
})

/* ---- backtest read --------------------------------------------------- */

const bt = computed(() => detailData.value?.backtest ?? null)

function btTone(v: number | null | undefined, flip = false): 'pos' | 'neg' | 'flat' {
  if (v == null || !Number.isFinite(v)) return 'flat'
  const n = Number(v)
  if (n === 0) return 'flat'
  const positive = flip ? n < 0 : n > 0
  return positive ? 'pos' : 'neg'
}
</script>

<template>
  <div class="absorption-view">
    <!-- 1. Cross-section screener -->
    <Panel
      label="Heavy Absorption Screener"
      index="16"
      :meta="
        boardData
          ? `${num(boardData.evaluated, 0)} of ${num(boardData.universe_size, 0)} evaluated · asof ${boardAge} ago`
          : ''
      "
      class="w-full"
      flush
      :live="!board.error.value"
    >
      <template #action>
        <button
          type="button"
          class="btn-quiet refresh-btn label"
          :disabled="board.loading.value"
          @click="refreshBoard"
        >
          {{ board.loading.value ? 'REFRESHING…' : '↻ REFRESH' }}
        </button>
      </template>

      <LoadingState v-if="board.loading.value && !boardData" label="loading absorption screener" />
      <p v-else-if="board.error.value && !boardData" class="state err label pad">
        {{ board.error.value }}
      </p>

      <template v-else-if="boardData">
        <p v-if="board.error.value" class="state err stale-artifact label">
          Refresh failed: {{ board.error.value }} · showing the last successful scan.
        </p>

        <div v-if="!boardHasRows" class="empty-state">
          <p class="state label dim">
            No symbols evaluated yet (0 of {{ num(boardData.universe_size, 0) }} universe) — the
            hourly bar universe may still be loading.
          </p>
        </div>

        <template v-else>
          <div class="filter-row">
            <button
              v-for="f in ['ALL', 'SIGNAL', 'NO_READ'] as SignalFilter[]"
              :key="f"
              type="button"
              class="sf-chip label"
              :class="{ on: signalFilter === f }"
              @click="signalFilter = f"
            >
              {{ f === 'NO_READ' ? 'NO READ' : f }} · {{ signalCounts[f] }}
            </button>
          </div>

          <div v-if="!tableRows.length" class="empty-state">
            <p class="state label dim">No rows match this filter.</p>
            <button type="button" class="btn-quiet label" @click="signalFilter = 'ALL'">
              CLEAR FILTER
            </button>
          </div>

          <div v-else class="table-scroll">
            <table class="grid">
              <thead>
                <tr>
                  <th class="label sortable" @click="setSort('symbol')">
                    Symbol {{ sortArrow('symbol') }}
                  </th>
                  <th class="label">Read</th>
                  <th
                    class="label num sortable"
                    title="Ranked by |absorption_score| — the directional read, not raw magnitude"
                    @click="setSort('abs_score')"
                  >
                    Score {{ sortArrow('abs_score') }}
                  </th>
                  <th class="label" title="Flow direction / expected reversal direction">
                    Flow → Rev
                  </th>
                  <th
                    class="label num sortable"
                    title="Non-directional strength only — can be high with no signal. Never a signal on its own."
                    @click="setSort('absorption_magnitude')"
                  >
                    Magnitude {{ sortArrow('absorption_magnitude') }}
                  </th>
                  <th class="label num sortable" @click="setSort('price')">
                    Price {{ sortArrow('price') }}
                  </th>
                  <th class="label num sortable" @click="setSort('vol_ratio')">
                    Vol ratio {{ sortArrow('vol_ratio') }}
                  </th>
                  <th
                    class="label num sortable"
                    title="Net signed-volume proxy (close-location-value × volume) as a share of gross flow — a bar-geometry proxy, not measured order-book imbalance. There is no trades/quotes/L2 data behind this repo."
                    @click="setSort('imbalance')"
                  >
                    Imbalance {{ sortArrow('imbalance') }}
                  </th>
                  <th class="label num" title="Price move over the flow window, in ATR fractions">
                    Move / ATR
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in tableRows"
                  :key="row.symbol"
                  :class="{ active: row.symbol === selectedSymbol }"
                >
                  <td class="fig sym">
                    <button
                      type="button"
                      class="row-symbol-btn"
                      :title="`asof ${row.asof}`"
                      @click="selectSymbol(row.symbol)"
                    >
                      {{ row.symbol }}
                    </button>
                  </td>
                  <td>
                    <span class="signal-chip label" :class="signalClass(row)">{{
                      signalLabel(row)
                    }}</span>
                  </td>
                  <td class="fig num" :class="tone(row.absorption_score)">
                    {{ signed(row.absorption_score, 3) }}
                  </td>
                  <td class="fig num dir-cell">
                    <span
                      class="dir-glyph"
                      :class="tone(row.flow_direction)"
                      title="Flow direction"
                      >{{ dirGlyph(row.flow_direction) }}</span
                    >
                    <span class="dir-sep">→</span>
                    <span
                      class="dir-glyph"
                      :class="tone(row.reversal_direction)"
                      title="Expected reversal direction"
                      >{{ dirGlyph(row.reversal_direction) }}</span
                    >
                  </td>
                  <td
                    class="fig num dim"
                    title="Non-directional strength only — never a signal on its own"
                  >
                    {{ num(row.absorption_magnitude, 3) }}
                  </td>
                  <td class="fig num">{{ usd(row.price, 2) }}</td>
                  <td class="fig num">{{ num(row.vol_ratio, 2) }}×</td>
                  <td class="fig num">{{ signedPct(row.imbalance * 100, 1) }}</td>
                  <td class="fig num dim">
                    {{ row.price_move != null ? signedPct(row.price_move * 100, 2) : DASH }} /
                    {{ pctFrac(row.atr_frac, 1) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>

        <ul v-if="boardData.caveats?.length" class="caveats-list">
          <li v-for="(c, i) in boardData.caveats" :key="i" class="label">{{ c }}</li>
        </ul>
      </template>
    </Panel>

    <!-- 2. Symbol detail (drill-down) -->
    <Panel
      :label="selectedSymbol ? `Absorption Detail: ${selectedSymbol}` : 'Absorption Detail'"
      :meta="selectedSymbol ? `analyzing ${selectedSymbol}` : 'select a row, or search a symbol'"
      class="w-full"
      :live="!detail.error.value"
    >
      <form class="search-row" @submit.prevent="submitSearch">
        <input
          v-model="searchInput"
          class="search-input"
          type="text"
          placeholder="SYMBOL (e.g. SPY, NVDA)"
          autocomplete="off"
          spellcheck="false"
          aria-label="Symbol to analyze"
        />
        <button type="submit" class="refresh-btn label" :disabled="detail.loading.value">
          {{ detail.loading.value ? 'LOADING…' : 'ANALYZE' }}
        </button>
      </form>

      <div v-if="!selectedSymbol" class="empty-state">
        <p class="state label dim">Click a row above, or type a symbol and press Analyze.</p>
      </div>

      <LoadingState
        v-else-if="detail.loading.value && !detailData"
        label="loading absorption detail"
      />
      <p v-else-if="detail.error.value && !detailData" class="state err label">
        {{ detail.error.value }}
      </p>

      <template v-else-if="detailData && detailData.available">
        <p v-if="detail.error.value" class="state err stale-artifact label">
          Refresh failed: {{ detail.error.value }} · showing the last successful detail.
        </p>

        <div v-if="seriesWindow" class="window-grid" aria-label="Series window and coverage">
          <Readout
            label="Shown window"
            :value="`${shortDate(seriesWindow.firstTs)} → ${shortDate(seriesWindow.lastTs)}`"
            :sub="`${num(seriesWindow.shownCount, 0)} of ${num(detailData.series_total, 0)} total bars (cap ${num(detailData.series_limit, 0)})`"
          />
          <Readout
            label="Full history range"
            :value="`${shortDate(detailData.series_first_ts)} → ${shortDate(detailData.series_last_ts)}`"
            sub="full evaluated range"
          />
          <Readout
            label="Signals (window)"
            :value="num(detailData.signal_window_count, 0)"
            :sub="
              windowCoverageNote(
                detailData.signal_window_count,
                detailData.signal_total_count,
                'signal(s)',
              )
            "
            tone="accent"
          />
          <Readout
            label="Signals (all history)"
            :value="num(detailData.signal_total_count, 0)"
            sub="across full history"
          />
          <Readout
            label="Baseline warming (window)"
            :value="num(detailData.baseline_warming_window_count, 0)"
            :sub="
              windowCoverageNote(
                detailData.baseline_warming_window_count,
                detailData.baseline_warming_total_count,
                'bar(s)',
              )
            "
          />
          <Readout
            label="Warming (all history)"
            :value="num(detailData.baseline_warming_total_count, 0)"
            sub="across full history"
          />
        </div>

        <div v-if="chart" ref="chartHostRef" class="chart-host">
          <svg
            :width="chartW"
            :height="chartH"
            class="chart-svg"
            role="img"
            aria-label="Price series with absorption signals and baseline-warming region"
          >
            <g v-for="t in chart.priceTicks" :key="t.y">
              <line :x1="48" :x2="chartW" :y1="t.y" :y2="t.y" class="gridline" />
              <text :x="0" :y="t.y + 3" class="tick label">{{ t.label }}</text>
            </g>
            <rect
              v-if="chart.warmingRect"
              :x="chart.warmingRect.x"
              :y="chart.warmingRect.y"
              :width="chart.warmingRect.width"
              :height="chart.warmingRect.height"
              class="warming-band"
            />
            <rect
              v-for="(z, i) in chart.zoneBands"
              :key="`z${i}`"
              :x="48"
              :y="z.y"
              :width="chartW - 60"
              :height="Math.max(1.5, z.height)"
              :class="z.cls"
            />
            <path :d="chart.area" class="area" />
            <path :d="chart.linePath" class="line" />
            <g v-for="(lv, i) in chart.levelLines" :key="`lv${i}`">
              <line :x1="48" :x2="chartW" :y1="lv.y" :y2="lv.y" :class="lv.cls" />
              <text :x="chartW - 2" :y="lv.y - 2" class="tick label lv-label">{{ lv.label }}</text>
            </g>
            <circle
              v-for="(s, i) in chart.signals"
              :key="i"
              :cx="s.x"
              :cy="s.y"
              r="3"
              :class="s.kind === 'sell_absorption' ? 'sig-sell' : 'sig-buy'"
            />
          </svg>
        </div>
        <p v-else class="state label dim">Not enough series data to chart.</p>
        <p class="chart-caption label">
          Price series with absorption signals marked (green = sell absorption → reversal up, red =
          buy absorption → reversal down){{
            chart?.warmingRect
              ? '. Shaded band = baseline still warming, not yet evaluable for a signal.'
              : '.'
          }}
          {{
            seriesWindow?.downsampled
              ? ` Rendered at ${seriesWindow.renderedCount} of ${seriesWindow.shownCount} points for performance; every real signal is preserved.`
              : ''
          }}
        </p>

        <div v-if="matrix" class="matrix-block" aria-label="Order-flow absorption matrix">
          <div class="matrix-head">
            <span class="label">ORDERFLOW MATRIX</span>
            <span class="label dim">
              {{ num(matrix.window_bars, 0) }} bars · {{ num(matrix.window_low, 2) }} –
              {{ num(matrix.window_high, 2)
              }}<template v-if="matrix.atr"> · ATR {{ num(matrix.atr, 2) }}</template>
            </span>
          </div>

          <div class="matrix-layout">
            <!-- Liquidity profile + delta + absorption columns -->
            <div
              class="matrix-profile"
              role="img"
              aria-label="Volume profile with delta and absorption columns"
            >
              <div class="mx-cols label dim">
                <span>LIQUIDITY</span>
                <span>Δ</span>
                <span>ABSORB</span>
              </div>
              <div
                v-for="b in matrixRows"
                :key="b.index"
                class="mx-row"
                :class="{
                  'mx-va': b.in_value_area,
                  'mx-poc': matrix.poc != null && b.low <= matrix.poc && matrix.poc < b.high,
                }"
                :title="`${num(b.low, 2)}–${num(b.high, 2)} · vol ${fmtCompact(b.total)} · buy ${fmtCompact(b.buy)} / sell ${fmtCompact(b.sell)} · Δ ${fmtCompact(b.delta)} · absorb ${fmtCompact(b.absorption)} · touches ${b.touches} · rejections ${b.rejections} · strength ${num(b.strength, 1)}`"
              >
                <div class="mx-liq">
                  <div class="mx-seg mx-sell" :style="{ width: widthPct(b.sell, matrixMaxVol) }">
                    <div
                      class="mx-seg-strong"
                      :style="{ width: widthPct(b.strong_sell, Math.max(b.sell, 1)) }"
                    />
                  </div>
                  <div class="mx-seg mx-buy" :style="{ width: widthPct(b.buy, matrixMaxVol) }">
                    <div
                      class="mx-seg-strong"
                      :style="{ width: widthPct(b.strong_buy, Math.max(b.buy, 1)) }"
                    />
                  </div>
                </div>
                <div class="mx-delta label" :class="tone(b.delta)">
                  <div
                    class="mx-delta-fill"
                    :class="tone(b.delta)"
                    :style="{ opacity: 0.08 + b.delta_frac * 0.3 }"
                  />
                  <span>{{ b.delta === 0 ? '·' : fmtCompact(b.delta) }}</span>
                </div>
                <div class="mx-abs">
                  <div
                    class="mx-abs-bar"
                    :style="{ width: widthPct(b.absorption, matrixMaxAbs) }"
                  />
                </div>
              </div>
            </div>

            <!-- Right rail: pressure, last print, zones -->
            <div class="matrix-rail">
              <div v-if="matrix.pressure" class="rail-block">
                <p
                  class="rail-title label"
                  title="Score, Buy/Sell, CVD bias and Absorption side are all derived from the CLV × volume signed-flow proxy on OHLCV bars — descriptive proxies, not measured order flow."
                >
                  FLOW PRESSURE
                </p>
                <div class="rail-grid">
                  <Readout
                    label="Score"
                    :value="`${signed(matrix.pressure.score, 0)} ${matrix.pressure.regime}`"
                    :tone="
                      btTone(matrix.pressure.score > 20 ? 1 : matrix.pressure.score < -20 ? -1 : 0)
                    "
                  />
                  <Readout
                    label="Buy / Sell"
                    :value="`${pctFrac(matrix.pressure.buy_share, 0)} / ${pctFrac(matrix.pressure.sell_share, 0)}`"
                    :tone="btTone(matrix.pressure.imbalance)"
                  />
                  <Readout
                    label="CVD bias"
                    :value="signedPct(matrix.pressure.cvd_bias * 100, 0)"
                    :tone="btTone(matrix.pressure.cvd_bias)"
                  />
                  <Readout
                    label="Absorption side"
                    :value="matrix.pressure.absorption_side"
                    :tone="
                      matrix.pressure.absorption_side === 'SUPPORT'
                        ? 'pos'
                        : matrix.pressure.absorption_side === 'RESISTANCE'
                          ? 'neg'
                          : 'flat'
                    "
                  />
                </div>
              </div>

              <div v-if="matrix.last_print && matrix.last_print.tier" class="rail-block">
                <p
                  class="rail-title label"
                  title="BUY/SELL is the sign of the CLV × volume proxy for this bar, not a measured aggressor side — there is no trade tape behind this repo's equity bars."
                >
                  LAST PRINT
                </p>
                <p
                  class="rail-big label"
                  :class="
                    matrix.last_print.side === 'BUY'
                      ? 'pos'
                      : matrix.last_print.side === 'SELL'
                        ? 'neg'
                        : ''
                  "
                >
                  {{ matrix.last_print.tier }} · {{ matrix.last_print.side }}
                </p>
                <p class="rail-sub label dim">
                  Δ {{ fmtCompact(matrix.last_print.bar_delta) }} · vol
                  {{ fmtCompact(matrix.last_print.bar_volume) }} ({{
                    num(matrix.last_print.vol_ratio, 2)
                  }}×)
                </p>
              </div>

              <div class="rail-block">
                <p class="rail-title label">
                  STRENGTH ZONES ·
                  <template v-if="matrix.poc != null"
                    >POC {{ num(matrix.poc, 2) }} · VA {{ num(matrix.val, 2) }}–{{
                      num(matrix.vah, 2)
                    }}</template
                  >
                  <template v-else>—</template>
                </p>
                <p v-if="!matrix.zones.length" class="rail-sub label dim">
                  No zone clears the minimum strength bar in this window.
                </p>
                <ul v-else class="zone-list">
                  <li v-for="(z, i) in matrix.zones" :key="i" class="zone-item">
                    <span class="zone-stars">{{ zoneStars(z.strength) }}</span>
                    <span class="zone-px label">{{ num(z.mid, 2) }}</span>
                    <span class="zone-side label" :class="z.side === 'support' ? 'pos' : 'neg'">
                      {{ z.side === 'support' ? 'SUP' : 'RES' }} · {{ z.tier }}
                    </span>
                    <span class="zone-stats label dim">
                      V {{ fmtCompact(z.volume) }} · A {{ fmtCompact(z.absorption) }} · T
                      {{ z.touches }} · R {{ z.rejections }}
                    </span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
          <p class="chart-caption label">
            Order-flow matrix over the trailing {{ num(matrix.window_bars, 0) }} bars: LIQUIDITY is
            candle-direction volume by price bin (bright = strong-volume bars), Δ is net signed flow
            (CLV × volume proxy), ABSORB is wick-defended volume. Zones are scored on volume,
            absorption, touches, rejections and recency. Descriptive proxies — no trades/quotes/L2
            data; never a trade authorization.
          </p>
        </div>

        <div v-if="bt" class="bt-grid">
          <Readout label="Signals" :value="num(bt.n_signals, 0)" sub="in sample" />
          <Readout label="Hits" :value="num(bt.n_hits, 0)" sub="reversal reached" />
          <Readout
            label="Precision"
            :value="bt.precision != null ? pctFrac(bt.precision, 1) : DASH"
            :tone="btTone(bt.precision)"
          />
          <Readout
            label="ROC AUC"
            :value="bt.roc_auc != null ? num(bt.roc_auc, 3) : DASH"
            :tone="btTone(bt.roc_auc)"
          />
          <Readout
            label="PR AUC"
            :value="bt.pr_auc != null ? num(bt.pr_auc, 3) : DASH"
            :tone="btTone(bt.pr_auc)"
          />
          <Readout
            label="Win rate"
            :value="bt.win_rate != null ? pctFrac(bt.win_rate, 1) : DASH"
            :tone="btTone(bt.win_rate)"
          />
          <Readout
            label="Expectancy"
            :value="bt.expectancy != null ? pctFrac(bt.expectancy, 2) : DASH"
            :tone="btTone(bt.expectancy)"
          />
          <Readout
            label="Sharpe"
            :value="bt.sharpe != null ? num(bt.sharpe, 2) : DASH"
            :tone="btTone(bt.sharpe)"
          />
          <Readout
            label="Max drawdown"
            :value="bt.max_drawdown != null ? pctFrac(bt.max_drawdown, 1) : DASH"
            :tone="btTone(bt.max_drawdown, true)"
          />
          <Readout
            label="Profit factor"
            :value="bt.profit_factor != null ? num(bt.profit_factor, 2) : DASH"
            :tone="btTone(bt.profit_factor)"
          />
        </div>
        <p v-if="bt" class="chart-caption label">
          Backtest: hypothetical reversal position held {{ bt.horizon }} bars, threshold
          {{ pctFrac(bt.threshold, 1) }}. Returns are per-bar close-to-close, NOT net of
          slippage/fees. recall/f1 are null (no ground-truth reversal set).
        </p>

        <ul v-if="detailData.caveats?.length" class="caveats-list">
          <li v-for="(c, i) in detailData.caveats" :key="i" class="label">{{ c }}</li>
        </ul>
      </template>

      <div v-else-if="detailData" class="empty-state">
        <p class="state label">{{ detailData.reason ?? 'No absorption data for this symbol.' }}</p>
      </div>
    </Panel>
  </div>
</template>

<style scoped>
.absorption-view {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  width: 100%;
  max-width: none;
  min-width: 0;
}

.w-full {
  width: 100%;
  min-width: 0;
}

.pad {
  padding: var(--s4);
}

.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  height: 28px;
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-micro);
  letter-spacing: 0.05em;
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
  cursor: pointer;
}
.refresh-btn:hover:not(:disabled) {
  background: var(--phosphor);
  color: var(--void);
}
.refresh-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.empty-state {
  padding: var(--s5) var(--s4);
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  align-items: flex-start;
}
.state.err {
  color: var(--short);
  padding: var(--s4);
}
.state.err.stale-artifact {
  border-bottom: var(--hair) solid var(--rule);
  background: color-mix(in srgb, var(--short) 7%, var(--void-lift));
  padding: var(--s3) var(--s4);
}
.state.dim {
  color: var(--ink-faint);
}

/* ---- board: filter chips, table ----------------------------------------- */
.filter-row {
  display: flex;
  gap: var(--s2);
  padding: var(--s3) var(--s4) 0;
  flex-wrap: wrap;
}
.sf-chip {
  padding: 4px 10px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  background: var(--void-lift);
  color: var(--ink-dim);
  cursor: pointer;
}
.sf-chip.on {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.table-scroll {
  max-height: 560px;
  overflow: auto;
  margin-top: var(--s3);
}
.sortable {
  cursor: pointer;
  user-select: none;
}
.sortable:hover {
  color: var(--ink);
}
.sym {
  font-weight: 600;
  letter-spacing: 0.03em;
}

.row-symbol-btn {
  display: inline-block;
  padding: 2px 0;
  color: var(--ink);
  font: inherit;
  font-weight: 700;
  cursor: pointer;
  border-bottom: var(--hair) dashed var(--rule-hi);
}
.row-symbol-btn:hover {
  color: var(--phosphor);
  border-bottom-color: var(--phosphor);
}

.grid tbody tr.active {
  background: var(--phosphor-wash);
  box-shadow: inset 2px 0 0 var(--phosphor);
}

.signal-chip {
  display: inline-flex;
  padding: 3px 8px;
  border: var(--hair) solid currentColor;
  border-radius: var(--r-xs);
  white-space: nowrap;
}
.signal-chip.sig-up {
  color: var(--long);
  background: color-mix(in srgb, var(--long) 12%, transparent);
}
.signal-chip.sig-down {
  color: var(--short);
  background: color-mix(in srgb, var(--short) 12%, transparent);
}
.signal-chip.no-read {
  color: var(--ink-faint);
  background: transparent;
}

.dir-cell {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  white-space: nowrap;
}
.dir-glyph {
  font-weight: 700;
}
.dir-sep {
  color: var(--ink-faint);
}

.caveats-list {
  list-style: none;
  margin: 0;
  padding: var(--s3) var(--s4);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.caveats-list li {
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.5;
}

/* ---- detail: search, coverage, chart ------------------------------------ */
.search-row {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: var(--s3);
  border-bottom: var(--hair) solid var(--rule);
}
.search-input {
  flex: 1 1 auto;
  min-width: 0;
  height: 30px;
  padding: 0 10px;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink);
  font-family: var(--font-data);
  font-size: var(--t-small);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.search-input:focus {
  outline: 1px solid var(--phosphor);
  outline-offset: -1px;
}

.window-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--s3);
  padding: var(--s3);
  border-bottom: var(--hair) solid var(--rule-faint);
}

.chart-host {
  width: 100%;
  height: 240px;
}
.chart-svg {
  display: block;
  width: 100%;
  height: 100%;
}
.gridline {
  stroke: var(--grid);
  stroke-width: 1;
}
.tick {
  fill: var(--ink-faint);
  font-size: var(--t-micro);
  dominant-baseline: middle;
}
.area {
  fill: var(--phosphor-glow);
  stroke: none;
}
.line {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1.5;
}
.sig-sell {
  fill: var(--long);
}
.sig-buy {
  fill: var(--short);
}
.warming-band {
  fill: var(--warn);
  opacity: 0.12;
  stroke: var(--warn);
  stroke-width: 1;
  stroke-dasharray: 2 2;
}
.chart-caption {
  padding: var(--s2) var(--s3) 0;
  color: var(--ink-faint);
  font-size: var(--t-small);
  line-height: 1.5;
}

.bt-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--s3);
  padding: var(--s3);
}

/* ---- order-flow matrix -------------------------------------------------- */
.zone-sup {
  fill: var(--long);
  opacity: 0.07;
}
.zone-res {
  fill: var(--short);
  opacity: 0.07;
}
.lv-poc {
  stroke: var(--phosphor);
  stroke-width: 1.5;
}
.lv-va {
  stroke: var(--ink-ghost);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}
.lv-label {
  text-anchor: end;
  fill: var(--ink-dim);
}

.matrix-block {
  border-top: var(--hair) solid var(--rule);
}
.matrix-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s3);
}
.matrix-head .label:first-child {
  color: var(--phosphor);
  font-weight: 700;
  letter-spacing: 0.08em;
}
.matrix-layout {
  display: flex;
  gap: var(--s4);
  padding: 0 var(--s3) var(--s3);
  align-items: flex-start;
}
@media (max-width: 900px) {
  .matrix-layout {
    flex-direction: column;
  }
}

.matrix-profile {
  flex: 1 1 58%;
  min-width: 0;
}
.mx-cols {
  display: grid;
  grid-template-columns: 1fr 72px 72px;
  gap: 6px;
  padding-bottom: 3px;
  letter-spacing: 0.08em;
}
.mx-cols span:nth-child(2),
.mx-cols span:nth-child(3) {
  text-align: right;
}
.mx-row {
  display: grid;
  grid-template-columns: 1fr 72px 72px;
  gap: 6px;
  align-items: stretch;
  height: 14px;
  border-left: 1px solid transparent;
}
.mx-va {
  border-left-color: var(--phosphor-dim);
}
.mx-poc {
  outline: 1px solid var(--phosphor);
  outline-offset: -1px;
}
.mx-liq {
  position: relative;
  background: color-mix(in srgb, var(--void-lift) 55%, transparent);
  overflow: hidden;
}
.mx-seg {
  position: absolute;
  top: 0;
  bottom: 0;
  opacity: 0.85;
}
.mx-buy {
  right: 50%;
  background: var(--long);
  opacity: 0.32;
}
.mx-sell {
  left: 50%;
  background: var(--short);
  opacity: 0.32;
}
/* Strong-volume segment: a brighter token rather than a CSS brightness
   filter, which the design guard forbids. The parent's opacity applies to
   the whole subtree, so the lift has to come from the colour itself. */
.mx-seg-strong {
  height: 100%;
  background: inherit;
}
.mx-buy .mx-seg-strong {
  margin-left: auto;
  background: var(--call-hi);
}
.mx-sell .mx-seg-strong {
  background: var(--put-hi);
}
.mx-delta {
  position: relative;
  overflow: hidden;
  text-align: right;
  font-size: var(--t-micro);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 3px;
}
.mx-delta-fill {
  position: absolute;
  inset: 0;
}
.mx-delta-fill.pos {
  background: var(--long);
}
.mx-delta-fill.neg {
  background: var(--short);
}
.mx-delta span {
  position: relative;
}
.mx-abs {
  position: relative;
  background: color-mix(in srgb, var(--void-lift) 40%, transparent);
  overflow: hidden;
}
.mx-abs-bar {
  position: absolute;
  top: 0;
  bottom: 0;
  right: 0;
  background: var(--warn);
  opacity: 0.45;
  border-left: 1px solid var(--warn);
}

.matrix-rail {
  flex: 1 1 42%;
  min-width: 240px;
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}
.rail-title {
  color: var(--ink-faint);
  letter-spacing: 0.08em;
  margin: 0 0 var(--s2);
}
.rail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: var(--s2);
}
.rail-big {
  margin: 0;
  font-weight: 700;
  font-size: var(--t-small);
}
.rail-sub {
  margin: 2px 0 0;
}

.zone-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}
.zone-item {
  display: grid;
  grid-template-columns: 52px 72px 110px 1fr;
  gap: var(--s2);
  align-items: baseline;
  padding: 3px 0;
  border-bottom: var(--hair) solid var(--rule-faint);
}
.zone-stars {
  color: var(--phosphor);
  font-size: var(--t-micro);
  letter-spacing: 1px;
}
.zone-px {
  font-weight: 700;
}
.zone-side {
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
}
.zone-stats {
  font-size: var(--t-micro);
}
</style>
