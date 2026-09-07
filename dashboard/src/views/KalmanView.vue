<script setup lang="ts">
/**
 * Kalman constant-velocity trend.
 *
 * Every moving average trades lag against smoothness, and picks that
 * trade-off once, for all regimes. A Kalman filter picks it continuously:
 * log price is modelled as a level moving at a latent velocity, and each new
 * bar is weighted by how surprising it is relative to the noise the filter
 * has been seeing. The result tracks a real trend faster than an EMA of equal
 * smoothness and absorbs a single-bar shock better.
 *
 * The traded output is the VELOCITY, not the level — pane 02. A real trend
 * keeps the filtered slope pinned above its own noise band; chop leaves it
 * oscillating around zero. Pane 03 is that slope divided by its own rolling
 * standard deviation, which is what makes one threshold mean the same thing
 * on a $3 small cap and on gold at $4,000. Entry/exit hysteresis (enter at
 * `entry_z`, exit at `exit_z`) stops the position flickering on the boundary.
 *
 * Two things this view will not hide from you:
 *   1. The score is unbounded. On a smooth trend the slope's rolling sd
 *      collapses and |score| runs into the hundreds, which on a linear axis
 *      would flatten `entry_z` and the zero line into the same pixel. Pane 03
 *      therefore uses an asinh axis — linear inside the threshold region,
 *      logarithmic in the tails — so both the crossings that trade and the
 *      excursions that don't stay readable, with nothing clipped away.
 *   2. The first `noise_bars` of any run sit on the filter's own transient
 *      (it starts at velocity 0 with P = I), so the earliest scores are
 *      measured against an artificially tiny noise estimate. The filter runs
 *      over full history precisely so this warmup falls off the left edge of
 *      the chart in every window but `max`.
 *
 * What this is NOT: a gate. The trade list is a descriptive, in-sample
 * reconstruction — no costs, no slippage, no walk-forward, no
 * multiple-testing correction. Trades are authorised only through the Gates
 * tab; nothing here is one of them.
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  WINDOWS,
  type KalmanSeriesPoint,
  type KalmanTrendPayload,
  type SearchHit,
  type TrajWindow,
} from '@/api'
import { debounce, useResource } from '@/composables/useResource'
import { DASH, num, optNum, optSigned, shortDate } from '@/format'
import { linearScale, linePath, niceTicks } from '@/charts'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import LoadingState from '@/components/LoadingState.vue'
import HelpTip from '@/components/HelpTip.vue'

const route = useRoute()
const router = useRouter()

/* ---- symbol selection (same inline search + LOAD pattern as Breaks/Market) */
function cleanTicker(term: string): string {
  return term
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
    .slice(0, 10)
}

const initialSymbol =
  typeof route.query.symbol === 'string' ? cleanTicker(route.query.symbol) : 'SPY'
const symbol = ref(initialSymbol)
const symbolInput = ref(initialSymbol)
const searchHits = ref<SearchHit[]>([])
const searchOpen = ref(false)

/* ---- parameters ---------------------------------------------------------
   Defaults mirror the model module (research/kalman_trend.py). `q` is the
   process noise with the observation variance R fixed at 1 — only the ratio
   q/R sets the gain, so exposing both would be two knobs for one degree of
   freedom. It is edited on a log10 slider because the useful range spans six
   orders of magnitude and a linear control would spend 99% of its travel in
   a region where the filter is indistinguishable from a straight line. */
const win = ref<TrajWindow>('1y')
const logQ = ref(-6)
const entryZ = ref(1.0)
const exitZ = ref(0.0)
const noiseDays = ref(20)
const allowShort = ref(false)
const barsMode = ref<'daily' | '1h'>('daily')

const qValue = computed(() => Number(Math.pow(10, logQ.value).toPrecision(3)))

const detail = useResource<KalmanTrendPayload>(
  () =>
    api.kalmanTrend(symbol.value, {
      window: win.value,
      q: qValue.value,
      entry_z: entryZ.value,
      exit_z: exitZ.value,
      noise_days: noiseDays.value,
      allow_short: allowShort.value,
      bars: barsMode.value,
    }),
  { intervalMs: 300_000, immediate: false },
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

loadSymbol(initialSymbol, { pushRoute: false })

watch(
  () => route.query.symbol,
  (next) => {
    if (typeof next !== 'string') return
    const clean = cleanTicker(next)
    if (clean && clean !== symbol.value) loadSymbol(clean, { pushRoute: false })
  },
)

/* Every parameter change re-runs the filter server-side. Debounced so a
   slider drag issues one request, not forty. */
const rerun = debounce(() => {
  if (symbol.value) void detail.refresh({ clear: false })
}, 220)

watch([win, logQ, entryZ, exitZ, noiseDays, allowShort, barsMode], () => rerun())

const runSearch = debounce(async (term: string) => {
  const cleaned = cleanTicker(term)
  if (!cleaned) {
    searchHits.value = []
    return
  }
  try {
    const raw = await api.search(cleaned, 10)
    searchHits.value = raw.filter((h) => (h.kind ?? 'symbol') === 'symbol').slice(0, 10)
    searchOpen.value = true
  } catch {
    searchHits.value = []
  }
}, 140)

watch(symbolInput, (v) => {
  if (v.trim().toUpperCase() === symbol.value) return
  void runSearch(v)
})

/* Never paint the previous ticker's figure while a new load is in flight. */
const payloadMatches = computed(() =>
  Boolean(detail.data.value && detail.data.value.symbol === symbol.value),
)
const d = computed(() => (payloadMatches.value ? detail.data.value : null))
const available = computed(() => d.value?.available === true)
const loading = computed(
  () => detail.loading.value || (Boolean(symbol.value) && !payloadMatches.value),
)
const series = computed<KalmanSeriesPoint[]>(() => d.value?.series ?? [])

/* ---- shared geometry ----------------------------------------------------
   x is the BAR INDEX, not calendar time: these are trading bars, and a
   time-proportional axis would open a gap every weekend and holiday that the
   filter never saw. All three panes share one index scale so a feature in
   pane 03 sits directly under the bar that produced it in pane 01. */
const W = 900
const PAD_L = 62
const PAD_R = 16
const PRICE_H = 190
const SLOPE_H = 130
const SCORE_H = 150
const PAD_T = 12
const PAD_B = 10

const xScale = computed(() =>
  linearScale([0, Math.max(series.value.length - 1, 1)], [PAD_L, W - PAD_R]),
)

const xTicks = computed(() => {
  const s = series.value
  if (s.length < 2) return []
  const count = Math.min(7, s.length)
  const out: { x: number; label: string }[] = []
  for (let k = 0; k < count; k++) {
    const i = Math.round((k * (s.length - 1)) / (count - 1))
    out.push({ x: xScale.value(i), label: shortDate(s[i].d.slice(0, 10)) })
  }
  return out
})

function yAxis(
  values: number[],
  height: number,
  symmetric = false,
): {
  scale: (v: number) => number
  ticks: number[]
} {
  const finite = values.filter((v) => Number.isFinite(v))
  let lo = finite.length ? Math.min(...finite) : 0
  let hi = finite.length ? Math.max(...finite) : 1
  if (symmetric) {
    const m = Math.max(Math.abs(lo), Math.abs(hi)) || 1
    lo = -m
    hi = m
  }
  if (lo === hi) {
    lo -= 1
    hi += 1
  }
  const pad = (hi - lo) * 0.08
  const scale = linearScale([lo - pad, hi + pad], [height - PAD_B, PAD_T])
  return { scale, ticks: niceTicks(lo, hi, 4) }
}

/* ---- pane 01: price, with the position the rules were holding ---------- */
const priceChart = computed(() => {
  const s = series.value
  if (s.length < 2) return null
  const closes = s.map((p) => p.close ?? NaN)
  const { scale, ticks } = yAxis(closes, PRICE_H)
  const pts = s
    .map((p, i) => ({ x: xScale.value(i), y: scale(p.close ?? NaN) }))
    .filter((pt) => Number.isFinite(pt.y))
  return {
    path: linePath(pts),
    ticks: ticks.map((t) => ({ v: t, y: scale(t) })),
    bands: positionBands(s, PAD_T, PRICE_H - PAD_B),
  }
})

/** Contiguous runs of held position, as one rect each — one rect per bar
 *  would be ~5k nodes on a 5y daily window. */
function positionBands(
  s: KalmanSeriesPoint[],
  top: number,
  bottom: number,
): { x: number; w: number; h: number; y: number; dir: 'long' | 'short' }[] {
  const out: { x: number; w: number; h: number; y: number; dir: 'long' | 'short' }[] = []
  let start = -1
  let sign = 0
  const flush = (endExclusive: number) => {
    if (start < 0 || sign === 0) return
    const x0 = xScale.value(start)
    const x1 = xScale.value(Math.max(endExclusive - 1, start))
    out.push({
      x: x0,
      w: Math.max(x1 - x0, 1),
      y: top,
      h: bottom - top,
      dir: sign > 0 ? 'long' : 'short',
    })
  }
  for (let i = 0; i < s.length; i++) {
    const p = s[i].pos
    if (p !== sign) {
      flush(i)
      start = i
      sign = p
    }
  }
  flush(s.length)
  return out
}

/* ---- pane 02: the filtered velocity ------------------------------------ */
const slopeChart = computed(() => {
  const s = series.value
  if (s.length < 2) return null
  const vals = s.map((p) => p.slope ?? NaN)
  const { scale, ticks } = yAxis(vals, SLOPE_H, true)
  const pts = s
    .map((p, i) => ({ x: xScale.value(i), y: scale(p.slope ?? NaN) }))
    .filter((pt) => Number.isFinite(pt.y))
  return {
    path: linePath(pts),
    zeroY: scale(0),
    ticks: ticks.map((t) => ({ v: t, y: scale(t) })),
  }
})

/* ---- pane 03: slope / noise, with the thresholds actually traded -------
   Plotted on an asinh axis, not a linear one. On a smooth trend the slope's
   rolling sd collapses toward zero and |score| runs into the hundreds; a
   linear domain wide enough to hold that excursion puts entry_z, exit_z and
   zero inside one pixel, which hides the only thing this pane exists to
   show. asinh(v/K) is linear for |v| < K and logarithmic beyond it, with K
   set by entry_z — so the threshold region keeps its resolution, the tails
   stay on the chart, and no value is clipped or clamped. */
const scoreChart = computed(() => {
  const s = series.value
  if (s.length < 2) return null
  const K = Math.max(entryZ.value, 0.5)
  const warp = (v: number) => Math.asinh(v / K)
  const vals = s.map((p) => p.score ?? 0).filter((v) => Number.isFinite(v))
  let tMax = warp(K * 2)
  for (const v of vals) tMax = Math.max(tMax, Math.abs(warp(v)))
  const scale = linearScale([-tMax, tMax], [SCORE_H - PAD_B, PAD_T])
  const y = (v: number) => scale(warp(v))

  // Ticks are chosen in DATA space from a decade-ish ladder, then warped —
  // niceTicks on the warped axis would label the transform, not the score.
  const ladder = [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000]
  const inRange = ladder.filter((c) => warp(c) <= tMax * 0.96)
  const stride = Math.max(1, Math.ceil(inRange.length / 3))
  const picked = inRange.filter((_, i) => i % stride === 0 || i === inRange.length - 1)
  // Near zero the asinh axis compresses hard, so a full ladder would stack
  // three labels on the same three pixels. Keep zero, then drop any tick
  // closer than a label height to one already kept.
  const ticks = [0, ...picked, ...picked.map((c) => -c)]
    .map((v) => ({ v, y: y(v) }))
    .sort((a, b) => Math.abs(a.v) - Math.abs(b.v))
    .reduce<{ v: number; y: number }[]>((kept, t) => {
      if (t.v === 0 || kept.every((k) => Math.abs(k.y - t.y) >= 9)) kept.push(t)
      return kept
    }, [])

  return {
    path: linePath(s.map((p, i) => ({ x: xScale.value(i), y: y(p.score ?? 0) }))),
    zeroY: y(0),
    entryY: y(entryZ.value),
    entryNegY: y(-entryZ.value),
    exitY: y(exitZ.value),
    exitNegY: y(-exitZ.value),
    ticks,
    peak: vals.length ? Math.max(...vals.map((v) => Math.abs(v))) : 0,
  }
})

/* ---- readouts ---------------------------------------------------------- */
const nowBlock = computed(() => d.value?.now ?? null)
const stats = computed(() => d.value?.stats ?? null)
const positionTone = computed(() => {
  const p = nowBlock.value?.position
  return p === 'long' ? 'pos' : p === 'short' ? 'neg' : 'flat'
})
const winRateLabel = computed(() =>
  stats.value?.win_rate_pct == null ? DASH : `${num(stats.value.win_rate_pct, 1)}%`,
)
const paramsLine = computed(() => {
  const p = d.value?.params
  if (!p) return ''
  const nb = p.noise_bars == null ? DASH : num(p.noise_bars, 0)
  const bpd = p.bars_per_day == null ? DASH : num(p.bars_per_day, 2)
  return `q = ${qValue.value.toExponential(1)} · R = 1 · noise ${num(p.noise_days, 0)}d = ${nb} bars · ${bpd} bars/day`
})
const truncated = computed(() => {
  const p = d.value
  return p ? p.n_trades > p.trades.length : false
})
</script>

<template>
  <div class="view">
    <Panel
      label="Kalman constant-velocity trend"
      index="R8"
      :meta="d?.generated_at ? `computed ${shortDate(d.generated_at.slice(0, 10))}` : ''"
      class="w-full"
    >
      <div class="banner label">
        <span>
          Log price as a level moving at a latent velocity. The traded output is the velocity
          measured against its own noise, not the level, and not a gate verdict.
        </span>
        <HelpTip
          label="What the filter does"
          text="State [level, velocity] with F = [[1,1],[0,1]], process noise q on both states, observation variance R = 1. Only the ratio q/R sets the gain, so R is fixed. Signals are read at bar i and filled at bar i+1's open (no look-ahead). The trade list is an in-sample reconstruction with no costs."
        />
      </div>

      <div class="controls">
        <div class="ctl symbol-ctl">
          <label class="label" for="kal-sym">Symbol</label>
          <div class="sym-row">
            <input
              id="kal-sym"
              v-model="symbolInput"
              class="fig input"
              type="text"
              spellcheck="false"
              placeholder="TICKER"
              @keyup.enter="loadSymbol(symbolInput)"
              @focus="searchOpen = searchHits.length > 0"
            />
            <button type="button" class="btn label" @click="loadSymbol(symbolInput)">Load</button>
            <ul v-if="searchOpen && searchHits.length" class="hits">
              <li v-for="h in searchHits" :key="h.symbol">
                <button type="button" class="hit label" @click="loadSymbol(h.symbol)">
                  <span class="fig">{{ h.symbol }}</span>
                  <span class="hit-meta">{{ h.n_bars ? `${num(h.n_bars, 0)} bars` : '' }}</span>
                </button>
              </li>
            </ul>
          </div>
        </div>

        <div class="ctl">
          <label class="label" for="kal-win">Window</label>
          <select id="kal-win" v-model="win" class="fig input">
            <option v-for="w in WINDOWS" :key="w" :value="w">{{ w }}</option>
          </select>
        </div>

        <div class="ctl">
          <label class="label" for="kal-bars">Bars</label>
          <select id="kal-bars" v-model="barsMode" class="fig input">
            <option value="daily">daily</option>
            <option value="1h">1h</option>
          </select>
        </div>

        <div class="ctl wide">
          <label class="label" for="kal-q">Process noise q · 1e{{ logQ }}</label>
          <input id="kal-q" v-model.number="logQ" type="range" min="-10" max="-2" step="0.5" />
        </div>

        <div class="ctl">
          <label class="label" for="kal-entry">Entry z</label>
          <input
            id="kal-entry"
            v-model.number="entryZ"
            class="fig input"
            type="number"
            min="0"
            max="10"
            step="0.1"
          />
        </div>

        <div class="ctl">
          <label class="label" for="kal-exit">Exit z</label>
          <input
            id="kal-exit"
            v-model.number="exitZ"
            class="fig input"
            type="number"
            min="-10"
            max="10"
            step="0.1"
          />
        </div>

        <div class="ctl">
          <label class="label" for="kal-noise">Noise window (days)</label>
          <input
            id="kal-noise"
            v-model.number="noiseDays"
            class="fig input"
            type="number"
            min="1"
            max="750"
            step="1"
          />
        </div>

        <div class="ctl">
          <label class="label" for="kal-short">Shorts</label>
          <label class="switch label" for="kal-short">
            <input id="kal-short" v-model="allowShort" type="checkbox" />
            <span>{{ allowShort ? 'long + short' : 'long only' }}</span>
          </label>
        </div>
      </div>

      <p class="params label">{{ paramsLine }}</p>

      <LoadingState v-if="loading && !d" label="Running the filter over full history…" />
      <p v-else-if="detail.error.value" class="state err label">{{ detail.error.value }}</p>
      <p v-else-if="d && !available" class="state label">
        {{ d.reason ?? 'No filter output for this symbol.' }}
      </p>

      <template v-else-if="available && d">
        <div class="readout-grid">
          <Readout
            label="Position now"
            :value="(nowBlock?.position ?? 'flat').toUpperCase()"
            :tone="positionTone"
            :sub="
              nowBlock?.forced_exit ? 'still on at last bar' : `as of ${nowBlock?.date ?? DASH}`
            "
          />
          <Readout
            label="Slope / noise"
            :value="optNum(nowBlock?.score, 2)"
            :sub="`entry ${num(entryZ, 1)} · exit ${num(exitZ, 1)}`"
            tone="accent"
          />
          <Readout
            label="Implied drift"
            :value="`${optSigned(nowBlock?.slope_pct_per_day, 3)}%`"
            sub="per day, from filtered velocity"
            :tone="(nowBlock?.slope_pct_per_day ?? 0) >= 0 ? 'pos' : 'neg'"
          />
          <Readout
            label="Round trips"
            :value="num(d.n_trades, 0)"
            :sub="`${num(stats?.n_long ?? 0, 0)}L / ${num(stats?.n_short ?? 0, 0)}S · ${winRateLabel} up`"
          />
          <Readout
            label="Avg trade"
            :value="`${optSigned(stats?.avg_ret_pct, 2)}%`"
            :sub="`median ${optSigned(stats?.median_ret_pct, 2)}% · no costs`"
            :tone="(stats?.avg_ret_pct ?? 0) >= 0 ? 'pos' : 'neg'"
          />
          <Readout
            label="Time in market"
            :value="`${optNum(stats?.exposure_pct, 1)}%`"
            :sub="`${num(d.n_bars_full, 0)} bars filtered`"
          />
        </div>

        <p class="caveat label">{{ d.caveat }}</p>

        <figure class="figure">
          <figcaption class="label fig-cap">
            01 · {{ d.symbol }} close, shaded where the rules held a position
          </figcaption>
          <svg
            class="pane"
            :viewBox="`0 0 ${W} ${PRICE_H}`"
            preserveAspectRatio="none"
            role="img"
            :aria-label="`${d.symbol} close with held positions`"
          >
            <g v-if="priceChart">
              <rect
                v-for="(b, i) in priceChart.bands"
                :key="`b${i}`"
                :x="b.x"
                :y="b.y"
                :width="b.w"
                :height="b.h"
                :class="['band', b.dir]"
              />
              <g v-for="t in priceChart.ticks" :key="`pt${t.v}`">
                <line class="grid" :x1="PAD_L" :y1="t.y" :x2="W - PAD_R" :y2="t.y" />
                <text class="axis fig" :x="PAD_L - 8" :y="t.y + 3" text-anchor="end">
                  {{ num(t.v, 2) }}
                </text>
              </g>
              <path class="price-line" :d="priceChart.path" />
            </g>
          </svg>

          <figcaption class="label fig-cap">02 · Filtered velocity (log price per bar)</figcaption>
          <svg
            class="pane"
            :viewBox="`0 0 ${W} ${SLOPE_H}`"
            preserveAspectRatio="none"
            role="img"
            aria-label="Kalman slope"
          >
            <g v-if="slopeChart">
              <g v-for="t in slopeChart.ticks" :key="`st${t.v}`">
                <line class="grid" :x1="PAD_L" :y1="t.y" :x2="W - PAD_R" :y2="t.y" />
                <text class="axis fig" :x="PAD_L - 8" :y="t.y + 3" text-anchor="end">
                  {{ t.v.toExponential(0) }}
                </text>
              </g>
              <line
                class="zero"
                :x1="PAD_L"
                :y1="slopeChart.zeroY"
                :x2="W - PAD_R"
                :y2="slopeChart.zeroY"
              />
              <path class="slope-line" :d="slopeChart.path" />
            </g>
          </svg>

          <figcaption class="label fig-cap">
            03 · Slope / noise: the traded signal
            <span v-if="scoreChart" class="scale-note">
              asinh axis · peak |z| {{ num(scoreChart.peak, 1) }}
            </span>
          </figcaption>
          <svg
            class="pane"
            :viewBox="`0 0 ${W} ${SCORE_H}`"
            preserveAspectRatio="none"
            role="img"
            aria-label="Slope divided by its rolling noise"
          >
            <g v-if="scoreChart">
              <g v-for="t in scoreChart.ticks" :key="`ct${t.v}`">
                <line class="grid" :x1="PAD_L" :y1="t.y" :x2="W - PAD_R" :y2="t.y" />
                <text class="axis fig" :x="PAD_L - 8" :y="t.y + 3" text-anchor="end">
                  {{ num(t.v, Math.abs(t.v) < 10 ? 1 : 0) }}
                </text>
              </g>
              <line
                class="zero"
                :x1="PAD_L"
                :y1="scoreChart.zeroY"
                :x2="W - PAD_R"
                :y2="scoreChart.zeroY"
              />
              <line
                class="thr entry"
                :x1="PAD_L"
                :y1="scoreChart.entryY"
                :x2="W - PAD_R"
                :y2="scoreChart.entryY"
              />
              <line
                class="thr exit"
                :x1="PAD_L"
                :y1="scoreChart.exitY"
                :x2="W - PAD_R"
                :y2="scoreChart.exitY"
              />
              <template v-if="allowShort">
                <line
                  class="thr entry"
                  :x1="PAD_L"
                  :y1="scoreChart.entryNegY"
                  :x2="W - PAD_R"
                  :y2="scoreChart.entryNegY"
                />
                <line
                  class="thr exit"
                  :x1="PAD_L"
                  :y1="scoreChart.exitNegY"
                  :x2="W - PAD_R"
                  :y2="scoreChart.exitNegY"
                />
              </template>
              <path class="score-line" :d="scoreChart.path" />
            </g>
          </svg>

          <svg
            class="axis-pane"
            :viewBox="`0 0 ${W} 22`"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <text
              v-for="t in xTicks"
              :key="t.label + t.x"
              class="axis fig"
              :x="t.x"
              y="14"
              text-anchor="middle"
            >
              {{ t.label }}
            </text>
          </svg>
        </figure>
      </template>
    </Panel>

    <Panel
      v-if="available && d && d.trades.length"
      label="Reconstructed round trips"
      index="R8b"
      :meta="`${num(d.n_trades, 0)} total · newest first`"
      class="w-full"
    >
      <p v-if="truncated" class="state label">
        Showing the {{ num(d.trades.length, 0) }} most recent of {{ num(d.n_trades, 0) }}.
      </p>
      <div class="table-container">
        <table class="mtable">
          <thead>
            <tr>
              <th>Entry</th>
              <th>Exit</th>
              <th>Side</th>
              <th class="fig">Entry px</th>
              <th class="fig">Exit px</th>
              <th class="fig">Bars</th>
              <th class="fig">Entry z</th>
              <th class="fig">Return</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(t, i) in d.trades" :key="`${t.entry_d}-${i}`">
              <td>{{ shortDate(t.entry_d.slice(0, 10)) }}</td>
              <td>{{ shortDate(t.exit_d.slice(0, 10)) }}</td>
              <td :class="['side', t.dir]">{{ t.dir.toUpperCase() }}</td>
              <td class="fig">{{ optNum(t.entry_px, 2) }}</td>
              <td class="fig">{{ optNum(t.exit_px, 2) }}</td>
              <td class="fig">{{ num(t.bars, 0) }}</td>
              <td class="fig">{{ optNum(t.entry_score, 2) }}</td>
              <td class="fig" :class="(t.ret_pct ?? 0) >= 0 ? 'pos' : 'neg'">
                {{ optSigned(t.ret_pct, 2) }}%
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Panel>
  </div>
</template>

<style scoped>
.view {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  min-width: 0;
}

.w-full {
  width: 100%;
}

.banner {
  display: flex;
  align-items: flex-start;
  gap: var(--s2);
  color: var(--ink-soft);
  border-bottom: var(--hair) solid var(--rule);
  padding-bottom: var(--s3);
  margin-bottom: var(--s3);
}

.controls {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s3);
  align-items: flex-end;
}

.ctl {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 92px;
}

.ctl.wide {
  min-width: 190px;
  flex: 1 1 190px;
}

.ctl .label {
  color: var(--ink-dim);
}

.input {
  height: var(--density-control-h);
  padding: 0 var(--s2);
  color: var(--ink);
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  font-size: var(--t-small);
}

.input:focus-visible {
  outline: var(--hair) solid var(--action-focus);
  outline-offset: 1px;
}

.symbol-ctl {
  min-width: 220px;
}

.sym-row {
  position: relative;
  display: flex;
  gap: var(--s1);
}

.sym-row .input {
  flex: 1 1 auto;
  min-width: 0;
}

.btn {
  height: var(--density-control-h);
  padding: 0 var(--s3);
  color: var(--ink);
  background: var(--panel-raise);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.btn:hover {
  border-color: var(--phosphor);
  color: var(--phosphor);
}

.hits {
  position: absolute;
  top: calc(var(--density-control-h) + 2px);
  left: 0;
  right: 0;
  z-index: var(--z-popover);
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 220px;
  overflow-y: auto;
  background: var(--surface-overlay);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
}

.hit {
  display: flex;
  justify-content: space-between;
  gap: var(--s2);
  width: 100%;
  padding: 6px var(--s2);
  background: none;
  border: 0;
  color: var(--ink);
  cursor: pointer;
  text-align: left;
}

.hit:hover {
  background: var(--panel-hi);
  color: var(--phosphor);
}

.hit-meta {
  color: var(--ink-faint);
}

.switch {
  display: flex;
  align-items: center;
  gap: 6px;
  height: var(--density-control-h);
  color: var(--ink-soft);
  cursor: pointer;
}

.params {
  margin: var(--s3) 0 0;
  color: var(--ink-faint);
}

.readout-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--s3);
  margin-top: var(--s3);
  padding-top: var(--s3);
  border-top: var(--hair) solid var(--rule);
}

.caveat {
  margin: var(--s3) 0 0;
  color: var(--warn);
}

.figure {
  margin: var(--s4) 0 0;
}

.fig-cap {
  display: block;
  color: var(--ink-dim);
  margin-bottom: 4px;
}

.fig-cap + .fig-cap {
  margin-top: var(--s3);
}

.scale-note {
  color: var(--ink-faint);
  margin-left: var(--s2);
}

.pane {
  display: block;
  width: 100%;
  height: auto;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.axis-pane {
  display: block;
  width: 100%;
  height: auto;
}

.grid {
  stroke: var(--rule-faint);
  stroke-width: 1;
}

.zero {
  stroke: var(--rule-hi);
  stroke-width: 1;
}

.thr {
  stroke-width: 1;
  stroke-dasharray: 4 3;
}

.thr.entry {
  stroke: var(--phosphor);
}

.thr.exit {
  stroke: var(--ink-faint);
}

.axis {
  fill: var(--ink-faint);
  font-size: var(--t-tiny);
}

.price-line,
.slope-line,
.score-line {
  fill: none;
  stroke-width: 1.4;
  vector-effect: non-scaling-stroke;
}

.price-line {
  stroke: var(--ink);
}

.slope-line {
  stroke: var(--phosphor);
}

.score-line {
  stroke: var(--phosphor);
}

.band.long {
  fill: var(--long-wash);
}

.band.short {
  fill: var(--short-wash);
}

.state {
  margin: var(--s3) 0 0;
  color: var(--ink-dim);
}

.state.err {
  color: var(--no-go);
}

.table-container {
  overflow-x: auto;
}

.mtable {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-small);
}

.mtable th {
  text-align: right;
  padding: var(--density-cell-padding);
  color: var(--ink-dim);
  border-bottom: var(--hair) solid var(--rule);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
}

.mtable th:first-child,
.mtable th:nth-child(2),
.mtable th:nth-child(3) {
  text-align: left;
}

.mtable td {
  padding: var(--density-cell-padding);
  text-align: right;
  color: var(--ink-soft);
  border-bottom: var(--hair) solid var(--rule-faint);
  font-variant-numeric: tabular-nums;
}

.mtable td:first-child,
.mtable td:nth-child(2),
.mtable td.side {
  text-align: left;
}

.side.long {
  color: var(--long);
}

.side.short {
  color: var(--short);
}

.pos {
  color: var(--go);
}

.neg {
  color: var(--no-go);
}
</style>
