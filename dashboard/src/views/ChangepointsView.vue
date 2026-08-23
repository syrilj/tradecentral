<script setup lang="ts">
/**
 * Bayesian Online Changepoint Detection (Adams & MacKay 2007, arXiv:0710.3742).
 *
 * The model infers the run-length posterior P(r_t | x_1:t) — the probability
 * distribution, at every bar, over "how many bars since the return-generating
 * variance last reset." It is a zero-mean Gaussian observation model with a
 * Gamma(a=1, b=1e-4) prior on the precision and a constant hazard H = 1/250
 * (eq. 3-5 of the paper), run over each symbol's daily returns. r_t collapsing
 * to 0 is a changepoint: the posterior has just thrown away everything it
 * knew about the old variance regime.
 *
 * This view reproduces the paper's Figure 3 for a selected symbol — returns
 * with the predictive volatility envelope on top, the run-length posterior
 * heatmap underneath, sharing one x-axis — plus a cross-section so the desk
 * can see which names are mid-break right now.
 *
 * Detection statistic: `break_prob` = P(r_t <= 5 | x_1:t), the probability a
 * changepoint occurred within the last 5 bars (`break_prob_20` at a 20-bar
 * lookback). Note that P(r_t = 0 | x_1:t) itself never appears in this view:
 * under a constant hazard it is identically H = 1/lambda_gap on every bar
 * (~0.004), carries zero information, and was removed from the contract
 * (BOCPD_CONTRACT.md, AMENDMENT 1) — the paper's Fig. 3 signal is the
 * collapse of the run-length ridge, not the r=0 row.
 *
 * What this is NOT: break_prob says the variance just changed. It says
 * nothing about direction, magnitude, or whether a position should follow.
 * This repo authorises trades only through its own gate modules (see the
 * Gates tab); nothing here is one of them.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  WINDOWS,
  type ChangepointDetail,
  type ChangepointRow,
  type ChangepointRunlength,
  type ChangepointsPayload,
  type ChangepointSeriesPoint,
  type SearchHit,
  type TrajWindow,
} from '@/api'
import { debounce, useResource } from '@/composables/useResource'
import { age, DASH, num, pctFrac, shortDate } from '@/format'
import {
  CHANGEPOINT_FIGURE_LABELS,
  artifactAgeDays,
  artifactIsStale,
  insightFromRow,
} from '@/changepointDisplay'
import { bandPath, linearScale, niceTicks } from '@/charts'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import LoadingState from '@/components/LoadingState.vue'
import HelpTip from '@/components/HelpTip.vue'

const route = useRoute()
const router = useRouter()

/* ---- cross-section (payload A) ---------------------------------------- */
const board = useResource<ChangepointsPayload>(() => api.changepoints(), { intervalMs: 300_000 })
const boardData = computed(() => board.data.value)
const boardAvailable = computed(() => boardData.value?.available === true)
const boardAgeDays = computed(() =>
  artifactAgeDays(boardData.value?.asof, boardData.value?.generated_at),
)
const boardStale = computed(() => artifactIsStale(boardAgeDays.value))

const breakCount = computed(
  () => (boardData.value?.symbols ?? []).filter((r) => r.regime === 'BREAK').length,
)
const settlingCount = computed(
  () => (boardData.value?.symbols ?? []).filter((r) => r.regime === 'SETTLING').length,
)

function formatB(b: number | undefined): string {
  if (b == null || !Number.isFinite(b)) return DASH
  if (b !== 0 && Math.abs(b) < 0.001) return b.toExponential(0)
  return num(b, 4)
}

const modelLine = computed(() => {
  const m = boardData.value?.model
  const lambda = num(m?.lambda_gap ?? 250, 0)
  const a = num(m?.prior.a ?? 1, 0)
  const b = formatB(m?.prior.b ?? 1e-4)
  return `λ_gap = ${lambda} · Gamma(a=${a}, b=${b}) · zero-mean Gaussian`
})

// Thresholds come from the payload, never hardcoded — the contract has
// already changed this once (break: 0.30 -> 0.50, AMENDMENT 1).
const breakThresholdLabel = computed(() => pctFrac(boardData.value?.thresholds?.break ?? 0.5, 0))
const settlingThresholdLabel = computed(() => num(boardData.value?.thresholds?.settling ?? 10, 0))

const skippedInfo = computed(() => {
  const skipped = boardData.value?.skipped ?? []
  const n = boardData.value?.n_skipped ?? skipped.length
  if (!n) return null
  const reasons = skipped.length
    ? skipped.map((s) => `${s.symbol}: ${s.reason}`).join('\n')
    : 'reasons not reported'
  return { n, reasons }
})

/* ---- symbol selection ---------------------------------------------------
   Mirrors the inline search + LOAD pattern used on Market/Options: a text
   field with a debounced dropdown over the same /api/search index, rather
   than inventing a new picker. */
function cleanTicker(term: string): string {
  return term.trim().toUpperCase().replace(/[^A-Z0-9.-]/g, '').slice(0, 10)
}

const initialSymbol = typeof route.query.symbol === 'string' ? cleanTicker(route.query.symbol) : ''
const symbol = ref(initialSymbol)
const symbolInput = ref(initialSymbol)
const win = ref<TrajWindow>('1y')
const searchHits = ref<SearchHit[]>([])
const searching = ref(false)
const searchOpen = ref(false)

const detail = useResource<ChangepointDetail>(
  () => api.changepointDetail(symbol.value, win.value),
  { intervalMs: 180_000, immediate: false },
)

function loadSymbol(raw: string, opts: { pushRoute?: boolean } = {}): void {
  const clean = cleanTicker(raw)
  if (!clean) return
  symbol.value = clean
  symbolInput.value = clean
  searchOpen.value = false
  if (opts.pushRoute !== false) {
    void router.replace({ query: { ...route.query, symbol: clean } })
  }
  void detail.refresh({ clear: true })
}

if (initialSymbol) loadSymbol(initialSymbol, { pushRoute: false })

watch(
  () => route.query.symbol,
  (newSym) => {
    if (typeof newSym === 'string') {
      const clean = cleanTicker(newSym)
      if (clean && clean !== symbol.value) {
        loadSymbol(clean, { pushRoute: false })
      }
    }
  },
)

// Payload A is an offline artifact that may be unavailable independently of
// payload B (computed on demand) — but if the desk hasn't typed a ticker
// yet, the most interesting default is the top row of the cross-section.
watch(boardData, (payload) => {
  if (symbol.value || !payload?.symbols?.length) return
  loadSymbol(payload.symbols[0].symbol, { pushRoute: false })
})

watch(win, () => {
  if (symbol.value) void detail.refresh({ clear: true })
})

const runSearch = debounce(async (term: string) => {
  const cleaned = cleanTicker(term)
  if (!cleaned) {
    searchHits.value = []
    return
  }
  searching.value = true
  try {
    const raw = await api.search(cleaned, 10)
    let list = raw.filter((h) => (h.kind ?? 'symbol') === 'symbol')
    if (!list.some((h) => h.symbol === cleaned)) {
      list = [
        { symbol: cleaned, kind: 'symbol', tier: 'wide', n_bars: 0, first_date: '', last_date: '' },
        ...list,
      ]
    }
    searchHits.value = list.slice(0, 10)
    searchOpen.value = true
  } catch {
    searchHits.value = []
  } finally {
    searching.value = false
  }
}, 140)

watch(symbolInput, (v) => {
  if (v.trim().toUpperCase() === symbol.value) return
  void runSearch(v)
})

function selectSymbol(): void {
  loadSymbol(symbolInput.value)
}

/* Only trust the payload when it matches the symbol currently selected —
   prevents painting the previous ticker's figure while a new load is
   in flight (same guard OptionsView uses). */
const payloadMatches = computed(() => Boolean(detail.data.value && detail.data.value.symbol === symbol.value))
const d = computed(() => (payloadMatches.value ? detail.data.value : null))
const detailAvailable = computed(() => d.value?.available === true)
const detailLoading = computed(() => detail.loading.value || (Boolean(symbol.value) && !payloadMatches.value))

/* ---- shared x-axis (real calendar time, not bar index) -----------------
   The heatmap's columns are a downsampled stride of the same date range the
   series covers, not a 1:1 index match, so the two panels are aligned by
   parsing actual dates onto one timestamp scale rather than by position. */
const W = 860
const PAD_L = 56
const PAD_R = 16
const TOP_H = 170
const TOP_PAD_T = 12
const TOP_PAD_B = 8
const BOT_H = 360
const BOT_PAD_T = 24
const BOT_PAD_B = 30

function parseUTC(dateStr: string): number {
  const t = Date.parse(dateStr.length <= 10 ? `${dateStr}T00:00:00Z` : dateStr)
  return Number.isFinite(t) ? t : NaN
}

const xDomain = computed<[number, number]>(() => {
  const detailNow = d.value
  const first = detailNow ? parseUTC(detailNow.first_date) : NaN
  const last = detailNow ? parseUTC(detailNow.last_date) : NaN
  if (!Number.isFinite(first) || !Number.isFinite(last) || first === last) {
    const fallback = Number.isFinite(first) ? first : Date.now()
    return [fallback - 86_400_000, fallback + 86_400_000]
  }
  return [first, last]
})
const xScale = computed(() => linearScale(xDomain.value, [PAD_L, W - PAD_R]))
function xOf(dateStr: string): number {
  return xScale.value(parseUTC(dateStr))
}

const xTicks = computed(() => {
  const series = d.value?.series ?? []
  if (series.length < 2) return []
  const count = 6
  const idxs = new Set<number>()
  for (let k = 0; k < count; k++) idxs.add(Math.round((k * (series.length - 1)) / (count - 1)))
  return [...idxs].sort((a, b) => a - b).map((i) => ({ x: xOf(series[i].d), label: shortDate(series[i].d) }))
})

/* ---- top panel: returns + predictive volatility envelope -----------------
   The y-domain is derived by scanning every bar's pred_vol, not fixed — the
   paper's §3.1 point is that predictive variance flares 2-3x in the bars
   right after a break, and a hardcoded range would clip exactly the feature
   this panel exists to show. */
const topChart = computed(() => {
  const series = d.value?.series ?? []
  if (!series.length) return null
  let maxAbs = 0.005
  for (const p of series) {
    maxAbs = Math.max(maxAbs, Math.abs(p.ret), Math.abs(p.pred_mean) + 2 * Math.abs(p.pred_vol))
  }
  maxAbs *= 1.15
  const yRet = linearScale([-maxAbs, maxAbs], [TOP_H - TOP_PAD_B, TOP_PAD_T])
  const upper = series.map((p) => ({ x: xOf(p.d), y: yRet(p.pred_mean + p.pred_vol) }))
  const lower = series.map((p) => ({ x: xOf(p.d), y: yRet(p.pred_mean - p.pred_vol) }))
  const upper2 = series.map((p) => ({ x: xOf(p.d), y: yRet(p.pred_mean + 2 * p.pred_vol) }))
  const lower2 = series.map((p) => ({ x: xOf(p.d), y: yRet(p.pred_mean - 2 * p.pred_vol) }))
  return {
    series,
    yRet,
    zeroY: yRet(0),
    band: bandPath(upper, lower),
    band2: bandPath(upper2, lower2),
    yTicks: niceTicks(-maxAbs, maxAbs, 4),
  }
})

/* ---- bottom panel: run-length posterior heatmap --------------------------
   Rendered to a canvas at 1px-per-cell and embedded as an <image> — an SVG
   with one <rect> per matrix cell (up to 130x260 = ~33.8k) visibly drops
   frames on hover/resize; a canvas blit does not. */
function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.trim().replace('#', '')
  if (clean.length === 6) {
    return [parseInt(clean.slice(0, 2), 16), parseInt(clean.slice(2, 4), 16), parseInt(clean.slice(4, 6), 16)]
  }
  if (clean.length === 3) {
    return [
      parseInt(clean[0] + clean[0], 16),
      parseInt(clean[1] + clean[1], 16),
      parseInt(clean[2] + clean[2], 16),
    ]
  }
  // phosphor fallback (matches tokens.css --phosphor) when no hex is supplied
  return [169, 196, 108]
}

/** Read once — the instrument runs one dark theme only (see tokens.css).
 *  RGB tuples are populated from computed style at mount; the numeric
 *  fallbacks mirror --phosphor / --void so canvas pixel math always has a
 *  valid color even before mount (e.g. SSR). */
const themeRgb = ref<{ phosphor: [number, number, number]; void: [number, number, number] }>({
  phosphor: [169, 196, 108],
  void: [8, 9, 12],
})
onMounted(() => {
  const cs = getComputedStyle(document.documentElement)
  const phosphor = cs.getPropertyValue('--phosphor').trim()
  const voidColor = cs.getPropertyValue('--void').trim()
  themeRgb.value = {
    phosphor: phosphor ? hexToRgb(phosphor) : themeRgb.value.phosphor,
    void: voidColor ? hexToRgb(voidColor) : themeRgb.value.void,
  }
})

/**
 * Row i of `matrix` is run length `run_values[i]` (smallest first, per the
 * contract). The canvas is flipped vertically so the smallest run length —
 * typically 0 — lands at the BOTTOM of the image, matching Fig. 3: after a
 * changepoint the ridge collapses to the bottom edge, not the top.
 */
function buildHeatmapDataUrl(rl: ChangepointRunlength, phosphorRgb: [number, number, number], voidRgb: [number, number, number]): string {
  if (typeof document === 'undefined' || !rl.n_rows || !rl.n_cols) return ''
  const canvas = document.createElement('canvas')
  canvas.width = rl.n_cols
  canvas.height = rl.n_rows
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''
  const img = ctx.createImageData(rl.n_cols, rl.n_rows)
  const [pr, pg, pb] = phosphorRgb
  const [vr, vg, vb] = voidRgb
  const floor = Number.isFinite(rl.log_floor) && rl.log_floor < 0 ? rl.log_floor : -6
  for (let i = 0; i < rl.n_rows; i++) {
    const row = rl.matrix[i]
    const canvasRow = rl.n_rows - 1 - i
    for (let j = 0; j < rl.n_cols; j++) {
      const v = row ? row[j] : null
      const idx = (canvasRow * rl.n_cols + j) * 4
      if (v == null || !Number.isFinite(v)) {
        img.data[idx] = vr
        img.data[idx + 1] = vg
        img.data[idx + 2] = vb
        img.data[idx + 3] = 0 // transparent background
        continue
      }
      const clipped = Math.min(0, Math.max(floor, v))
      const t = floor === 0 ? 1 : (clipped - floor) / (0 - floor)
      const g = Math.pow(Math.min(1, Math.max(0, t)), 0.5)

      if (g < 0.35) {
        const u = g / 0.35
        img.data[idx] = Math.round(vr + (24 - vr) * u)
        img.data[idx + 1] = Math.round(vg + (80 - vg) * u)
        img.data[idx + 2] = Math.round(vb + (80 - vb) * u)
      } else if (g < 0.75) {
        const u = (g - 0.35) / 0.40
        img.data[idx] = Math.round(24 + (pr - 24) * u)
        img.data[idx + 1] = Math.round(80 + (pg - 80) * u)
        img.data[idx + 2] = Math.round(pb + (80 - pb) * u)
      } else {
        const u = (g - 0.75) / 0.25
        img.data[idx] = Math.round(pr + (240 - pr) * u)
        img.data[idx + 1] = Math.round(pg + (255 - pg) * u)
        img.data[idx + 2] = Math.round(pb + (200 - pb) * u)
      }
      // Crisp alpha: low-probability background is transparent, active ridge glows bright
      const alpha = g < 0.1 ? 0 : Math.round(255 * Math.pow((g - 0.1) / 0.9, 1.2))
      img.data[idx + 3] = Math.min(255, Math.max(0, alpha))
    }
  }
  ctx.putImageData(img, 0, 0)
  return canvas.toDataURL()
}

const heatmap = computed(() => {
  const rl = d.value?.runlength
  if (!rl || !rl.n_rows || !rl.n_cols || !rl.dates.length) return null
  const url = buildHeatmapDataUrl(rl, themeRgb.value.phosphor, themeRgb.value.void)
  if (!url) return null
  const x0 = xOf(rl.dates[0])
  const x1 = xOf(rl.dates[rl.dates.length - 1])
  const plotTop = BOT_PAD_T
  const plotH = BOT_H - BOT_PAD_B - BOT_PAD_T
  const nRows = rl.n_rows
  const tickCount = Math.min(6, nRows)
  const idxs = new Set<number>()
  if (tickCount <= 1) idxs.add(0)
  else for (let k = 0; k < tickCount; k++) idxs.add(Math.round((k * (nRows - 1)) / (tickCount - 1)))
  const yTicks = [...idxs]
    .sort((a, b) => a - b)
    .map((i) => {
      const canvasRow = nRows - 1 - i
      return { y: plotTop + ((canvasRow + 0.5) / nRows) * plotH, label: num(rl.run_values[i] ?? i, 0) }
    })
  return {
    url,
    x: x0,
    y: plotTop,
    width: Math.max(1, x1 - x0),
    height: plotH,
    yTicks,
  }
})

const breakMarks = computed(() => (d.value?.breaks ?? []).map((b) => ({ ...b, x: xOf(b.date) })))

/* ---- shared crosshair ---------------------------------------------------- */
function nearestIndexByTime(series: ChangepointSeriesPoint[], ts: number): number {
  let lo = 0
  let hi = series.length - 1
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (parseUTC(series[mid].d) < ts) lo = mid + 1
    else hi = mid
  }
  if (lo > 0 && Math.abs(parseUTC(series[lo - 1].d) - ts) < Math.abs(parseUTC(series[lo].d) - ts)) return lo - 1
  return lo
}

const figureHost = ref<HTMLDivElement | null>(null)
const hoveredIndex = ref<number | null>(null)

function onFigureMove(e: MouseEvent): void {
  const series = d.value?.series
  const host = figureHost.value
  if (!series?.length || !host) return
  const rect = host.getBoundingClientRect()
  if (rect.width <= 0) return
  const frac = (e.clientX - rect.left) / rect.width
  const vx = frac * W
  const targetTs = xScale.value.invert(vx)
  hoveredIndex.value = nearestIndexByTime(series, targetTs)
}
function onFigureLeave(): void {
  hoveredIndex.value = null
}

const cursorPoint = computed<ChangepointSeriesPoint | null>(() => {
  const series = d.value?.series
  if (!series?.length) return null
  if (hoveredIndex.value != null && series[hoveredIndex.value]) return series[hoveredIndex.value]
  return series[series.length - 1]
})
const cursorIsLive = computed(() => hoveredIndex.value == null)
const crosshairX = computed(() => (cursorPoint.value ? xOf(cursorPoint.value.d) : null))

function signedFrac(v: number | null | undefined, dp = 2): string {
  if (v == null || !Number.isFinite(v)) return DASH
  return `${v > 0 ? '+' : ''}${pctFrac(v, dp)}`
}

/* ---- cross-section table -------------------------------------------------- */
type SortKey =
  | 'symbol'
  | 'break_prob'
  | 'map_run_length'
  | 'days_since_break'
  | 'predictive_vol'
  | 'trailing_vol_20d'
  | 'vol_ratio'
type RegimeFilter = 'ALL' | 'BREAK' | 'SETTLING' | 'STABLE'

const sortKey = ref<SortKey>('break_prob')
const sortDir = ref<'asc' | 'desc'>('desc')
const regimeFilter = ref<RegimeFilter>('ALL')

function setSort(key: SortKey): void {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortKey.value = key
    sortDir.value = key === 'symbol' ? 'asc' : 'desc'
  }
}

function sortValue(row: ChangepointRow, key: SortKey): number | string {
  switch (key) {
    case 'symbol': return row.symbol
    case 'break_prob': return row.break_prob
    case 'map_run_length': return row.map_run_length
    case 'days_since_break': return row.days_since_break ?? -Infinity
    case 'predictive_vol': return row.predictive_vol
    case 'trailing_vol_20d': return row.trailing_vol_20d
    case 'vol_ratio': return row.vol_ratio ?? -Infinity
    default: return 0
  }
}

const regimeCounts = computed(() => {
  const counts: Record<string, number> = { BREAK: 0, SETTLING: 0, STABLE: 0 }
  for (const r of boardData.value?.symbols ?? []) counts[r.regime] = (counts[r.regime] ?? 0) + 1
  return counts
})

const tableRows = computed(() => {
  let list = [...(boardData.value?.symbols ?? [])]
  if (regimeFilter.value !== 'ALL') list = list.filter((r) => r.regime === regimeFilter.value)
  const dir = sortDir.value === 'asc' ? 1 : -1
  const key = sortKey.value
  list.sort((a, b) => {
    const av = sortValue(a, key)
    const bv = sortValue(b, key)
    if (typeof av === 'string' || typeof bv === 'string') return dir * String(av).localeCompare(String(bv))
    return dir * (av - bv)
  })
  return list
})

function regimeClass(r: string): string {
  if (r === 'BREAK') return 'r-break'
  if (r === 'SETTLING') return 'r-settling'
  if (r === 'STABLE') return 'r-stable'
  return 'r-unknown'
}

function sortArrow(key: SortKey): string {
  if (sortKey.value !== key) return ''
  return sortDir.value === 'asc' ? '▴' : '▾'
}

/* ---- selected-row insight ------------------------------------------------- */
const selectedRow = computed<ChangepointRow | null>(() => {
  if (d.value?.stats && d.value.stats.symbol === symbol.value) return d.value.stats
  if (!symbol.value) return null
  return boardData.value?.symbols?.find((r) => r.symbol === symbol.value) ?? null
})

const symbolInsight = computed(() => {
  const row = selectedRow.value
  if (!row) return null
  const thresholds = d.value?.thresholds ?? boardData.value?.thresholds ?? { break: 0.5, settling: 10 }
  return insightFromRow(row, thresholds)
})
</script>

<template>
  <div class="changepoints-view">
    <Panel
      label="Bayesian regime breaks"
      index="13"
      :meta="boardData?.asof
        ? `asof ${boardData.asof} · ${age(boardData.generated_at)} ago${boardStale ? ' · STALE ARTIFACT' : ''}`
        : 'diagnostics only'"
      class="w-full"
    >
      <template #action>
        <button
          type="button"
          class="cp-refresh-btn label"
          :disabled="board.loading.value"
          title="Reload changepoints cross-section artifact"
          @click="board.refresh({ clear: false })"
        >
          <span class="refresh-icon" :class="{ spinning: board.loading.value }">↻</span>
          {{ board.loading.value ? 'RELOADING...' : 'REFRESH' }}
        </button>
      </template>

      <LoadingState v-if="board.loading.value && !boardData" label="loading changepoint artifact" />
      <p v-else-if="board.error.value" class="err">{{ board.error.value }}</p>

      <template v-else-if="boardAvailable">
        <div class="banner">
          <span class="pill">DIAGNOSTIC ONLY</span>
          <span class="banner-text">
            The run-length posterior P(r<sub>t</sub> | x<sub>1:t</sub>) is the model's belief, at
            each bar, about how many bars since the return variance last reset.
            <code>break_prob</code> = P(r<sub>t</sub> ≤ 5 | x<sub>1:t</sub>) summarises that: the
            probability a break happened within the last 5 bars. A high break_prob means the
            variance just changed — it is not a forecast of direction and it does not authorise a
            trade. Only the repo's own gate modules
            (see <RouterLink :to="{ name: 'gates' }">Gates</RouterLink>) do that.
            <HelpTip
              label="Run-length posterior"
              text="r_t = bars since the last changepoint. P(r_t | x_1:t) is inferred online via Adams & MacKay's exact recursion (eq. 3): grow-or-reset at every bar, weighted by a constant hazard H = 1/lambda_gap. r_t collapsing toward 0 across bars is the model discarding the old variance estimate — a break. break_prob = P(r_t <= 5 | x_1:t) reads that off directly, and break_prob_20 does the same at a 20-bar lookback. This view is diagnostic; it never authorises capital."
            />
          </span>
        </div>
        <div class="counts">
          <Readout label="In BREAK" :value="String(breakCount)" :sub="`break_prob ≥ ${breakThresholdLabel}`" :tone="breakCount > 0 ? 'neg' : 'pos'" />
          <Readout label="Settling" :value="String(settlingCount)" :sub="`map run ≤ ${settlingThresholdLabel}`" tone="flat" />
          <Readout label="Universe" :value="num(boardData?.n_symbols, 0)" :sub="`${num(boardData?.lookback_days, 0)}d lookback`" />
        </div>
        <p class="model-line fig">{{ modelLine }}</p>
        <p class="dims" v-if="boardData?.source">{{ boardData.source }}</p>
        <p v-if="boardStale" class="note stale-board">
          Cross-section artifact is {{ boardAgeDays }}d old (asof {{ boardData?.asof }}).
          Selected-symbol detail below is live BOCPD on current bars — not this board.
        </p>
        <p v-if="skippedInfo" class="dims skipped-note" :title="skippedInfo.reasons">
          {{ skippedInfo.n }} symbol{{ skippedInfo.n === 1 ? '' : 's' }} skipped — hover for reasons
        </p>
      </template>

      <div v-else class="empty">
        <p class="note">No changepoint artifact yet{{ boardData?.reason ? ` — ${boardData.reason}` : '' }}. Build one:</p>
        <ul class="cmds">
          <li>
            <code>edge/.venv-qlib/bin/python edge/tools/build_changepoints.py</code>
            <span class="dim">writes runs/changepoints/</span>
          </li>
        </ul>
      </div>
    </Panel>

    <Panel
      :label="symbol ? `Run-length posterior — ${symbol}` : 'Run-length posterior'"
      index="—"
      meta="Fig. 3 · returns + predictive vol · P(r_t | x_1:t)"
      flush
      :delay="40"
    >
      <template #action>
        <button
          type="button"
          class="cp-refresh-btn label"
          :disabled="detail.loading.value"
          title="Recompute single symbol run-length posterior"
          @click="detail.refresh({ clear: false })"
        >
          <span class="refresh-icon" :class="{ spinning: detail.loading.value }">↻</span>
          {{ detail.loading.value ? 'RECOMPUTING...' : 'RECOMPUTE' }}
        </button>
      </template>
      <div class="figure-controls">
        <form class="symbol-form" @submit.prevent="selectSymbol">
          <input
            v-model="symbolInput"
            class="symbol-input"
            maxlength="10"
            autocomplete="off"
            spellcheck="false"
            placeholder="TICKER"
            aria-label="Symbol"
            @focus="searchOpen = searchHits.length > 0"
            @keydown.escape="searchOpen = false"
          />
          <button class="load-btn label" type="submit" :disabled="detailLoading">
            {{ detailLoading ? '…' : 'LOAD' }}
          </button>
          <ul v-if="searchOpen && searchHits.length" class="search-hits" role="listbox">
            <li
              v-for="hit in searchHits"
              :key="hit.symbol"
              role="option"
              class="label"
              :class="{ on: hit.symbol === symbol }"
              @mousedown.prevent="loadSymbol(hit.symbol)"
            >
              <span class="fig">{{ hit.symbol }}</span>
              <span class="tier">{{ hit.n_bars ? hit.tier : 'enter' }}</span>
            </li>
          </ul>
        </form>
        <div class="segment">
          <button
            v-for="w in WINDOWS"
            :key="w"
            type="button"
            class="seg label"
            :class="{ on: win === w }"
            @click="win = w"
          >{{ w.toUpperCase() }}</button>
        </div>
        <div v-if="cursorPoint" class="cursor-readout">
          <span class="label cr-tag" :class="{ live: cursorIsLive }">{{ cursorIsLive ? 'LATEST' : 'CURSOR' }}</span>
          <span class="cr-item"><span class="label">Date</span><span class="fig">{{ cursorPoint.d }}</span></span>
          <span class="cr-item"><span class="label">Ret</span><span class="fig">{{ signedFrac(cursorPoint.ret) }}</span></span>
          <span class="cr-item"><span class="label">break 5d</span><span class="fig">{{ pctFrac(cursorPoint.break_prob, 1) }}</span></span>
          <span class="cr-item"><span class="label">MAP run</span><span class="fig">{{ num(cursorPoint.map_run, 0) }}</span></span>
          <span class="cr-item"><span class="label">Pred vol</span><span class="fig">{{ pctFrac(cursorPoint.pred_vol, 2) }}</span></span>
        </div>
      </div>

      <!-- ── symbol insight card ─────────────────────────────────────────── -->
      <div v-if="selectedRow && symbolInsight" class="sym-insight">
        <div class="si-header">
          <span class="si-sym fig">{{ selectedRow.symbol }}</span>
          <span class="regime-chip label" :class="regimeClass(selectedRow.regime)">{{ selectedRow.regime }}</span>
          <span class="si-nav">
            <RouterLink :to="{ name: 'options', query: { symbol: selectedRow.symbol } }" class="si-link label">→ Options</RouterLink>
            <RouterLink :to="{ name: 'market', query: { symbol: selectedRow.symbol } }" class="si-link label">→ Market</RouterLink>
          </span>
        </div>
        <div class="si-rows">
          <div v-for="line in symbolInsight" :key="line.label" class="si-row">
            <span class="label si-lbl">{{ line.label }}</span>
            <span class="fig si-val" :class="`si-${line.tone}`">{{ line.value }}</span>
            <span class="label si-note">{{ line.note }}</span>
          </div>
        </div>
      </div>

      <LoadingState v-if="detailLoading && !d" label="computing posterior" />
      <p v-else-if="detail.error.value" class="err pad">{{ detail.error.value }}</p>
      <div v-else-if="!symbol" class="empty pad">
        <p class="note">Pick a symbol above, or wait for the cross-section to load a default.</p>
      </div>
      <div v-else-if="!detailAvailable" class="empty pad">
        <p class="note">
          No posterior for <b class="fig">{{ symbol }}</b>{{ d?.reason ? ` — ${d.reason}` : '' }}.
          Minimum 60 bars are required to compute a run-length posterior.
        </p>
      </div>

      <template v-else>
        <div ref="figureHost" class="figure-stack" @mousemove="onFigureMove" @mouseleave="onFigureLeave">
          <div class="fig-axis-row">
            <span class="fig-ylab label">{{ CHANGEPOINT_FIGURE_LABELS.yTop }}</span>
            <svg
            :viewBox="`0 0 ${W} ${TOP_H}`"
            class="chart top-chart"
            preserveAspectRatio="none"
            role="img"
            :aria-label="`${CHANGEPOINT_FIGURE_LABELS.yTop} with predictive volatility envelope`"
          >
            <template v-if="topChart">
              <g class="axis">
                <line
                  v-for="t in topChart.yTicks"
                  :key="`ty-${t}`"
                  :x1="PAD_L" :x2="W - PAD_R"
                  :y1="topChart.yRet(t)" :y2="topChart.yRet(t)"
                  class="gridline"
                />
                <text
                  v-for="t in topChart.yTicks"
                  :key="`tyl-${t}`"
                  :x="PAD_L - 8" :y="topChart.yRet(t) + 3"
                  text-anchor="end" class="tick-label"
                >{{ pctFrac(t, 1) }}</text>
              </g>

              <path :d="topChart.band2" class="vol-band-outer" />
              <path :d="topChart.band" class="vol-band" />
              <line :x1="PAD_L" :x2="W - PAD_R" :y1="topChart.zeroY" :y2="topChart.zeroY" class="zero" />

              <g class="needles">
                <line
                  v-for="p in topChart.series"
                  :key="`ret-${p.d}`"
                  :x1="xOf(p.d)" :x2="xOf(p.d)"
                  :y1="topChart.zeroY" :y2="topChart.yRet(p.ret)"
                  :class="['needle', p.ret >= 0 ? 'up' : 'down']"
                />
              </g>
            </template>

            <line
              v-for="b in breakMarks" :key="`brk-top-${b.date}`"
              :x1="b.x" :x2="b.x" :y1="TOP_PAD_T" :y2="TOP_H - TOP_PAD_B"
              class="break-line"
            />

            <line
              v-if="crosshairX != null"
              :x1="crosshairX" :x2="crosshairX" :y1="0" :y2="TOP_H"
              class="crosshair"
            />
          </svg>
          </div>

          <div class="fig-axis-row">
            <span class="fig-ylab label">{{ CHANGEPOINT_FIGURE_LABELS.yBottom }}</span>
            <svg
            :viewBox="`0 0 ${W} ${BOT_H}`"
            class="chart bottom-chart"
            preserveAspectRatio="none"
            role="img"
            :aria-label="`${CHANGEPOINT_FIGURE_LABELS.yBottom}: ${CHANGEPOINT_FIGURE_LABELS.heatmap}`"
          >
            <template v-if="heatmap">
              <image
                :href="heatmap.url"
                :x="heatmap.x" :y="heatmap.y"
                :width="heatmap.width" :height="heatmap.height"
                preserveAspectRatio="none"
                class="heat-image"
              />
              <g class="axis">
                <text
                  v-for="t in heatmap.yTicks"
                  :key="`ry-${t.y}`"
                  :x="PAD_L - 8" :y="t.y + 3"
                  text-anchor="end" class="tick-label"
                >{{ t.label }}</text>
              </g>
            </template>
            <rect
              v-else
              :x="PAD_L" :y="BOT_PAD_T" :width="W - PAD_L - PAD_R" :height="BOT_H - BOT_PAD_T - BOT_PAD_B"
              class="heat-empty"
            />
            <text :x="PAD_L - 40" :y="BOT_PAD_T - 8" class="axis-title">run r</text>

            <g v-for="t in xTicks" :key="`xt-${t.x}`">
              <text :x="t.x" :y="BOT_H - BOT_PAD_B + 16" text-anchor="middle" class="tick-label">{{ t.label }}</text>
            </g>

            <g v-for="b in breakMarks" :key="`brk-bot-${b.date}`">
              <line :x1="b.x" :x2="b.x" :y1="BOT_PAD_T" :y2="BOT_H - BOT_PAD_B" class="break-line" />
              <text :x="b.x + 3" :y="BOT_PAD_T - 6" class="break-label">
                {{ shortDate(b.date) }} · brk {{ pctFrac(b.break_prob, 0) }}
              </text>
            </g>

            <line
              v-if="crosshairX != null"
              :x1="crosshairX" :x2="crosshairX" :y1="0" :y2="BOT_H"
              class="crosshair"
            />
          </svg>
          </div>
          <div class="fig-xlab label">{{ CHANGEPOINT_FIGURE_LABELS.x }} · {{ CHANGEPOINT_FIGURE_LABELS.heatmap }}</div>
          <div class="fig-legend label">
            <span>low P</span>
            <span class="leg-scale" aria-hidden="true"><i /><i /><i /><i /><i /></span>
            <span>high P (ridge = recent break)</span>
          </div>
        </div>

        <div v-if="breakMarks.length" class="break-list">
          <span class="label bl-title">Breaks in window</span>
          <span v-for="b in breakMarks" :key="`bl-${b.date}`" class="break-chip">
            <span class="fig">{{ shortDate(b.date) }}</span>
            <span class="label">brk {{ pctFrac(b.break_prob, 0) }}</span>
            <span class="label dim">vol {{ pctFrac(b.pred_vol_before, 2) }} → {{ pctFrac(b.pred_vol_after, 2) }}</span>
          </span>
        </div>
      </template>
    </Panel>

    <Panel label="Cross-section" index="—" :meta="`${tableRows.length}/${boardData?.symbols?.length ?? 0} names`" :delay="80">
      <LoadingState v-if="board.loading.value && !boardData" label="loading cross-section" compact />
      <p v-else-if="board.error.value" class="err">{{ board.error.value }}</p>
      <div v-else-if="!boardAvailable" class="empty">
        <p class="note">No cross-section available{{ boardData?.reason ? ` — ${boardData.reason}` : '' }}.</p>
      </div>

      <template v-else>
        <div class="regime-filter">
          <button
            v-for="f in (['ALL', 'BREAK', 'SETTLING', 'STABLE'] as RegimeFilter[])"
            :key="f"
            type="button"
            class="rf-chip label"
            :class="[{ on: regimeFilter === f }, f !== 'ALL' ? regimeClass(f) : '']"
            @click="regimeFilter = f"
          >{{ f }}{{ f !== 'ALL' ? ` · ${regimeCounts[f] ?? 0}` : '' }}</button>
        </div>

        <div class="table-scroll">
          <table class="grid">
            <thead>
              <tr>
                <th class="label sortable" @click="setSort('symbol')">Symbol {{ sortArrow('symbol') }}</th>
                <th class="label num sortable" @click="setSort('break_prob')" title="P(break in last 5 bars) · quieter figure is the 20-bar lookback">Break 5d {{ sortArrow('break_prob') }}</th>
                <th class="label num sortable" @click="setSort('map_run_length')">MAP run {{ sortArrow('map_run_length') }}</th>
                <th class="label num sortable" @click="setSort('days_since_break')">Days since brk {{ sortArrow('days_since_break') }}</th>
                <th class="label num sortable" @click="setSort('predictive_vol')">Pred vol {{ sortArrow('predictive_vol') }}</th>
                <th class="label num sortable" @click="setSort('trailing_vol_20d')">Trail 20d {{ sortArrow('trailing_vol_20d') }}</th>
                <th class="label num sortable" @click="setSort('vol_ratio')">Vol ratio {{ sortArrow('vol_ratio') }}</th>
                <th class="label">Regime</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in tableRows"
                :key="row.symbol"
                :class="{ active: row.symbol === symbol }"
                @click="loadSymbol(row.symbol)"
              >
                <td class="fig sym">{{ row.symbol }}</td>
                <td class="fig num break-cell">
                  <span class="break-bar"><i :style="{ width: `${Math.min(100, Math.max(0, row.break_prob * 100))}%` }" /></span>
                  <span class="break-primary">{{ pctFrac(row.break_prob, 1) }}</span>
                  <span class="break-secondary dim" title="break_prob_20 — same statistic at a 20-bar lookback">/{{ pctFrac(row.break_prob_20, 0) }}</span>
                </td>
                <td class="fig num">{{ num(row.map_run_length, 0) }}</td>
                <td class="fig num dim">{{ row.days_since_break == null ? DASH : num(row.days_since_break, 0) }}</td>
                <td class="fig num">{{ pctFrac(row.predictive_vol, 2) }}</td>
                <td class="fig num dim">{{ pctFrac(row.trailing_vol_20d, 2) }}</td>
                <td class="fig num">{{ row.vol_ratio == null ? DASH : num(row.vol_ratio, 2) }}</td>
                <td><span class="regime-chip label" :class="regimeClass(row.regime)">{{ row.regime }}</span></td>
              </tr>
              <tr v-if="!tableRows.length"><td colspan="8" class="note pad">No rows match this filter.</td></tr>
            </tbody>
          </table>
        </div>
      </template>
    </Panel>
  </div>
</template>

<style scoped>
.changepoints-view {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

/* ---- header banner --------------------------------------------------- */
.banner {
  display: flex;
  align-items: flex-start;
  gap: var(--s3);
  margin-bottom: var(--s3);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.pill {
  flex: 0 0 auto;
  font-family: var(--font-display);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  font-weight: 700;
  color: var(--phosphor);
}
.banner-text {
  font-size: var(--t-small);
  line-height: 1.45;
  color: var(--ink-soft);
}
.banner-text code { font-family: var(--font-data); color: var(--ink); }
.banner-text a { font-weight: 600; }

.counts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s3);
}
.model-line {
  margin-top: var(--s3);
  font-size: var(--t-small);
  color: var(--ink-soft);
}
.dims { margin-top: var(--s1); font-size: var(--t-tiny); color: var(--ink-faint); font-family: var(--font-data); }
.skipped-note { cursor: help; text-decoration: underline dotted var(--ink-ghost); text-underline-offset: 3px; }

.empty.pad, .err.pad { padding: var(--s3) var(--s2); }
.note { font-size: var(--t-small); color: var(--ink-dim); }
.err { font-size: var(--t-small); color: var(--short); }
.cmds { list-style: none; display: flex; flex-direction: column; gap: var(--s2); margin-top: var(--s3); }
.cmds li { display: flex; flex-wrap: wrap; gap: var(--s3); align-items: baseline; }
.cmds code { font-family: var(--font-data); font-size: var(--t-tiny); padding: 2px var(--s1); background: var(--panel-raise); color: var(--ink-soft); }
.dim { color: var(--ink-faint); }

/* ---- figure controls --------------------------------------------------- */
.figure-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  border-bottom: var(--hair) solid var(--rule);
}
.symbol-form { position: relative; flex: 0 0 auto; }
.symbol-input {
  width: 100px;
  height: 28px;
  padding: 0 8px;
  font: 600 0.85rem var(--font-data);
  letter-spacing: .05em;
  text-transform: uppercase;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  color: var(--ink);
}
.load-btn {
  height: 28px;
  margin-left: 4px;
  padding: 0 10px;
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.load-btn:disabled { opacity: .5; cursor: wait; }
.search-hits {
  position: absolute;
  top: calc(100% + 2px);
  left: 0;
  z-index: var(--z-popover); /* was 40, tied --z-strip and fell to paint order */
  min-width: 180px;
  margin: 0;
  padding: 0;
  list-style: none;
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-raise);
  max-height: 220px;
  overflow: auto;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.35);
}
.search-hits li {
  display: flex;
  justify-content: space-between;
  gap: var(--s2);
  padding: 6px 10px;
  cursor: pointer;
  color: var(--ink-dim);
  border-bottom: var(--hair) solid var(--rule);
}
.search-hits li:hover, .search-hits li.on { background: var(--phosphor-wash); color: var(--ink); }
.search-hits .tier { color: var(--ink-ghost); font-size: 9px; }

.segment { display: flex; flex: 0 0 auto; border: var(--hair) solid var(--rule-hi); }
.seg { padding: 5px 9px; color: var(--ink-dim); border-right: var(--hair) solid var(--rule); }
.seg:last-child { border-right: none; }
.seg.on { color: var(--phosphor); background: var(--phosphor-wash); }

.cursor-readout {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s4);
  margin-left: auto;
  padding: 2px var(--s2);
}
.cr-tag {
  padding: 2px 6px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-faint);
}
.cr-tag.live { color: var(--phosphor); border-color: var(--phosphor-dim); }
.cr-item { display: flex; flex-direction: column; gap: 1px; align-items: flex-start; }
.cr-item .label { font-size: 9px; }
.cr-item .fig { font-size: var(--t-small); color: var(--ink); }

.cp-refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  height: 22px;
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-micro);
  letter-spacing: 0.05em;
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
  cursor: pointer;
  transition: all 0.12s ease;
}
.cp-refresh-btn:hover:not(:disabled) {
  background: var(--phosphor);
  color: var(--void);
}
.cp-refresh-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}
.refresh-icon {
  display: inline-block;
  font-size: 0.85rem;
  line-height: 1;
}
.refresh-icon.spinning {
  animation: spin var(--dur-spin) linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* ---- figure charts ------------------------------------------------------ */
.figure-stack {
  display: flex;
  flex-direction: column;
  cursor: crosshair;
  background: var(--void);
}
.fig-axis-row {
  display: grid;
  grid-template-columns: 4.5rem minmax(0, 1fr);
  align-items: stretch;
}
.fig-ylab {
  display: flex;
  align-items: center;
  justify-content: center;
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  letter-spacing: 0.06em;
  padding: var(--s2) 0;
}
.fig-xlab {
  text-align: center;
  color: var(--ink-dim);
  padding: var(--s1) 0 var(--s2);
  font-size: var(--t-tiny);
}
.fig-legend {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--s2);
  padding: 0 var(--s3) var(--s3);
  color: var(--ink-faint);
  font-size: var(--t-tiny);
}
.leg-scale {
  display: inline-flex;
  width: 88px;
  height: 8px;
  gap: 1px;
}
.leg-scale i {
  flex: 1 1 0;
  display: block;
  height: 100%;
}
.leg-scale i:nth-child(1) { background: var(--void-lift); }
.leg-scale i:nth-child(2) { background: color-mix(in srgb, var(--phosphor) 25%, var(--void)); }
.leg-scale i:nth-child(3) { background: color-mix(in srgb, var(--phosphor) 50%, var(--void)); }
.leg-scale i:nth-child(4) { background: color-mix(in srgb, var(--phosphor) 75%, var(--void)); }
.leg-scale i:nth-child(5) { background: var(--phosphor); }
.stale-board { color: var(--warn); }
.chart { display: block; width: 100%; }
.top-chart { height: 200px; border-bottom: var(--hair) solid var(--rule-faint); }
.bottom-chart { height: 400px; }

.gridline { stroke: var(--grid); stroke-width: 1; }
.zero { stroke: var(--rule-hi); stroke-width: 1; }
.tick-label { font-family: var(--font-data); font-size: 11px; fill: var(--ink-dim); }
.axis-title { font-family: var(--font-data); font-size: 11px; fill: var(--ink-soft); }

.vol-band-outer { fill: var(--phosphor-wash); stroke: color-mix(in srgb, var(--phosphor) 22%, transparent); stroke-width: 1; stroke-dasharray: 3 3; vector-effect: non-scaling-stroke; }
.vol-band { fill: var(--phosphor-wash); stroke: var(--phosphor-dim); stroke-width: 1; vector-effect: non-scaling-stroke; }

.needle { stroke-width: 1.3; vector-effect: non-scaling-stroke; }
.needle.up { stroke: var(--long); }
.needle.down { stroke: var(--short); }

.heat-image { image-rendering: pixelated; }
.heat-empty { fill: var(--void-lift); }

.break-line { stroke: var(--warn); stroke-width: 1; stroke-dasharray: 3 2; vector-effect: non-scaling-stroke; }
.break-label { font-family: var(--font-data); font-size: 8px; fill: var(--warn); }

/* var(--ink), not phosphor — the heatmap ridge is already phosphor-coloured,
   so a phosphor crosshair disappears exactly where it crosses the ridge. */
.crosshair { stroke: var(--ink); stroke-width: 1; opacity: .85; vector-effect: non-scaling-stroke; pointer-events: none; }

.break-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  border-top: var(--hair) solid var(--rule-faint);
}
.bl-title { color: var(--ink-faint); }
.break-chip {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 3px 8px;
  border: var(--hair) solid var(--rule);
  color: var(--ink-soft);
}
.break-chip .fig { color: var(--ink); font-size: var(--t-small); }

/* ---- cross-section table -------------------------------------------------- */
.regime-filter { display: flex; gap: var(--s2); padding: 0 var(--s2) var(--s3); }
.rf-chip { padding: 4px 9px; border: var(--hair) solid var(--rule-hi); color: var(--ink-dim); }
.rf-chip.on { color: var(--ink); background: var(--panel-hi); }
.rf-chip.r-break.on { color: var(--no-go); border-color: var(--no-go); background: var(--short-wash); }
.rf-chip.r-settling.on { color: var(--warn); border-color: var(--warn); background: var(--warn-wash); }
.rf-chip.r-stable.on { color: var(--go); border-color: var(--go); background: var(--long-wash); }

.table-scroll { max-height: 480px; overflow: auto; }
.sortable { cursor: pointer; user-select: none; }
.sortable:hover { color: var(--ink); }
.sym { font-weight: 600; letter-spacing: .03em; }

.break-cell { display: flex; align-items: center; justify-content: flex-end; gap: 6px; }
.break-bar { display: block; width: 44px; height: 4px; background: var(--rule); overflow: hidden; flex: 0 0 auto; }
.break-bar i { display: block; height: 100%; background: var(--phosphor); }
.break-primary { min-width: 3.5ch; text-align: right; }
.break-secondary { font-size: 0.85em; }

.regime-chip { display: inline-flex; align-items: center; padding: 2px 7px; border: var(--hair) solid currentColor; letter-spacing: .06em; }
.r-break { color: var(--no-go); background: var(--short-wash); }
.r-settling { color: var(--warn); background: var(--warn-wash); }
.r-stable { color: var(--go); background: var(--long-wash); }
.r-unknown { color: var(--unknown); }

.grid tbody tr { cursor: pointer; }
.grid tbody tr:hover { background: var(--panel-hi); }
.grid tbody tr.active { background: var(--phosphor-wash); box-shadow: inset 2px 0 0 var(--phosphor); }

@media (max-width: 960px) {
  .counts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .cursor-readout { margin-left: 0; }
}

/* ---- symbol insight card ----------------------------------------------- */
.sym-insight {
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-hi);
  margin: var(--s3) 0 0;
}

.si-header {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  border-bottom: var(--hair) solid var(--rule);
  background: var(--void-lift);
}

.si-sym {
  font-size: var(--t-small);
  font-weight: 700;
  color: var(--ink);
  min-width: 5ch;
}

.si-nav {
  display: flex;
  gap: var(--s3);
  margin-left: auto;
}

.si-link {
  display: inline-block;
  padding: 3px 8px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
  text-decoration: none;
  transition: color 0.12s, border-color 0.12s;
}
.si-link:hover {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  text-decoration: none;
}

.si-rows {
  display: flex;
  flex-direction: column;
}

.si-row {
  display: grid;
  grid-template-columns: 14ch 14ch 1fr;
  align-items: baseline;
  gap: var(--s3);
  padding: var(--s2) var(--s4);
  border-bottom: var(--hair) solid var(--rule);
}
.si-row:last-child { border-bottom: none; }

.si-lbl { color: var(--ink-ghost); font-size: var(--t-micro); }

.si-val {
  font-size: var(--t-small);
  font-weight: 600;
  min-width: 6ch;
}

.si-note {
  color: var(--ink-dim);
  white-space: normal;
  line-height: 1.5;
}

/* Tone colours — match the severity of the reading */
.si-hot  { color: var(--short); }
.si-warn { color: var(--warn); }
.si-ok   { color: var(--long); }
.si-dim  { color: var(--ink-faint); }

/* Notes inherit muted color unless overridden */
.si-row:has(.si-hot) .si-note  { color: color-mix(in srgb, var(--short) 70%, var(--ink-dim)); }
.si-row:has(.si-warn) .si-note { color: color-mix(in srgb, var(--warn) 60%, var(--ink-dim)); }
</style>
