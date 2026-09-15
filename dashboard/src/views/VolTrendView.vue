<script setup lang="ts">
/**
 * Volatility-Targeted Trend.
 *
 * Sizes every entry so its notional targets a CONSTANT annualised volatility:
 * In calm markets you carry more, in turbulent markets less, and the risk
 * taken per trade stops depending on when the trade happened.
 *
 * What this is NOT: a gate verdict. The trade list is a descriptive, in-sample
 * reconstruction with no costs or slippage.
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  WINDOWS,
  type SearchHit,
  type TrajWindow,
  type VolTargetSeriesPoint,
  type VolTargetSignalItem,
  type VolTargetSignalsPayload,
  type VolTargetTrade,
  type VolTargetTrendPayload,
} from '@/api'
import { debounce, useResource } from '@/composables/useResource'
import { DASH, num, optNum, optSigned, shortDate, usd } from '@/format'
import { linearScale, linePath, niceTicks } from '@/charts'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import LoadingState from '@/components/LoadingState.vue'
import HelpTip from '@/components/HelpTip.vue'

const route = useRoute()
const router = useRouter()

/* ---- symbol selection ---- */
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

/* ---- strategy parameters ---- */
const win = ref<TrajWindow>('1y')
const targetVolPct = ref(15) // percentage: 15 = 0.15
const levCap = ref(3.0)
const fastDays = ref(5)
const slowDays = ref(20)
const volDays = ref(20)
const capital = ref(100_000)
const barsMode = ref<'daily' | '1h'>('daily')
const showBacktest = ref(false)
const showParams = ref(false)

const targetVolRatio = computed(() => targetVolPct.value / 100.0)

/* ---- persistent tracked stocks (keeper) ---- */
const TRACKED_STORAGE_KEY = 'edge_voltrend_tracked_symbols'
const DEFAULT_TRACKED = ['SPY', 'QQQ', 'NVDA', 'TSLA', 'AAPL', 'MSFT']
const QUICK_PRESETS = ['SPY', 'QQQ', 'NVDA', 'TSLA', 'AAPL', 'MSFT', 'AMZN', 'META', 'GOOGL', 'AMD']

function loadInitialTracked(): string[] {
  try {
    if (typeof localStorage === 'undefined') return [...DEFAULT_TRACKED]
    const raw = localStorage.getItem(TRACKED_STORAGE_KEY)
    if (!raw) return [...DEFAULT_TRACKED]
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed) && parsed.length > 0) {
      return parsed.map(cleanTicker).filter(Boolean).slice(0, 40)
    }
  } catch {
    // fallback
  }
  return [...DEFAULT_TRACKED]
}

function saveTracked(list: string[]): void {
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(TRACKED_STORAGE_KEY, JSON.stringify(list))
    }
  } catch {
    // quota / private mode guard
  }
}

const trackedSymbols = ref<string[]>(loadInitialTracked())
const newTrackedInput = ref('')

const signalsResource = useResource<VolTargetSignalsPayload>(
  () =>
    api.volTargetSignals(trackedSymbols.value, {
      target_vol: targetVolRatio.value,
      lev_cap: levCap.value,
      fast_days: fastDays.value,
      slow_days: slowDays.value,
      vol_days: volDays.value,
      capital: capital.value,
      bars: barsMode.value,
    }),
  { intervalMs: 60_000, immediate: true },
)

function addTrackedSymbol(raw: string): void {
  const clean = cleanTicker(raw)
  if (!clean) return
  if (!trackedSymbols.value.includes(clean)) {
    trackedSymbols.value = [...trackedSymbols.value, clean]
    saveTracked(trackedSymbols.value)
    void signalsResource.refresh({ clear: false })
  }
  newTrackedInput.value = ''
}

function removeTrackedSymbol(sym: string): void {
  trackedSymbols.value = trackedSymbols.value.filter((s) => s !== sym)
  saveTracked(trackedSymbols.value)
  void signalsResource.refresh({ clear: false })
}

function isTracked(sym: string): boolean {
  return trackedSymbols.value.includes(cleanTicker(sym))
}

function toggleTrackCurrent(): void {
  const cur = cleanTicker(symbol.value)
  if (!cur) return
  if (isTracked(cur)) {
    removeTrackedSymbol(cur)
  } else {
    addTrackedSymbol(cur)
  }
}

const detail = useResource<VolTargetTrendPayload>(
  () =>
    api.volTargetTrend(symbol.value, {
      window: win.value,
      target_vol: targetVolRatio.value,
      lev_cap: levCap.value,
      fast_days: fastDays.value,
      slow_days: slowDays.value,
      vol_days: volDays.value,
      capital: capital.value,
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

const rerun = debounce(() => {
  if (symbol.value) void detail.refresh({ clear: false })
  void signalsResource.refresh({ clear: false })
}, 220)

watch([win, targetVolPct, levCap, fastDays, slowDays, volDays, capital, barsMode], () => rerun())

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

const payloadMatches = computed(() =>
  Boolean(detail.data.value && detail.data.value.symbol === symbol.value),
)
const d = computed(() => (payloadMatches.value ? detail.data.value : null))
const available = computed(() => d.value?.available === true)
const loading = computed(
  () => detail.loading.value || (Boolean(symbol.value) && !payloadMatches.value),
)
const series = computed<VolTargetSeriesPoint[]>(() => d.value?.series ?? [])
const signalItems = computed<VolTargetSignalItem[]>(() => signalsResource.data.value?.signals ?? [])

/* ---- shared geometry ---- */
const W = 900
const PAD_L = 62
const PAD_R = 16
const PRICE_H = 190
const VOL_H = 120
const LEV_H = 120
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
  loFloor?: number,
): {
  scale: (v: number) => number
  ticks: number[]
} {
  const finite = values.filter((v) => Number.isFinite(v))
  let lo = finite.length ? Math.min(...finite) : 0
  let hi = finite.length ? Math.max(...finite) : 1
  if (loFloor !== undefined) lo = Math.min(lo, loFloor)
  if (lo === hi) {
    lo -= 1
    hi += 1
  }
  const pad = (hi - lo) * 0.08
  const scale = linearScale([lo - pad, hi + pad], [height - PAD_B, PAD_T])
  return { scale, ticks: niceTicks(lo, hi, 4) }
}

/* ---- pane 01: price, EMA fast, EMA slow, and position bands ---- */
const priceChart = computed(() => {
  const s = series.value
  if (s.length < 2) return null
  const closes = s.map((p) => p.close ?? NaN)
  const emas = s.flatMap((p) => [p.ema_f ?? NaN, p.ema_s ?? NaN])
  const { scale, ticks } = yAxis([...closes, ...emas], PRICE_H)

  const closePts = s
    .map((p, i) => ({ x: xScale.value(i), y: scale(p.close ?? NaN) }))
    .filter((pt) => Number.isFinite(pt.y))

  const emaFPts = s
    .map((p, i) => ({ x: xScale.value(i), y: scale(p.ema_f ?? NaN) }))
    .filter((pt) => Number.isFinite(pt.y))

  const emaSPts = s
    .map((p, i) => ({ x: xScale.value(i), y: scale(p.ema_s ?? NaN) }))
    .filter((pt) => Number.isFinite(pt.y))

  return {
    closePath: linePath(closePts),
    emaFPath: linePath(emaFPts),
    emaSPath: linePath(emaSPts),
    ticks: ticks.map((t) => ({ v: t, y: scale(t) })),
    bands: positionBands(s, PAD_T, PRICE_H - PAD_B),
  }
})

function positionBands(
  s: VolTargetSeriesPoint[],
  top: number,
  bottom: number,
): { x: number; w: number; h: number; y: number }[] {
  const out: { x: number; w: number; h: number; y: number }[] = []
  let start = -1
  let inPosition = false
  const flush = (endExclusive: number) => {
    if (start < 0 || !inPosition) return
    const x0 = xScale.value(start)
    const x1 = xScale.value(Math.max(endExclusive - 1, start))
    out.push({
      x: x0,
      w: Math.max(x1 - x0, 1),
      y: top,
      h: bottom - top,
    })
  }
  for (let i = 0; i < s.length; i++) {
    const p = s[i].pos > 0
    if (p !== inPosition) {
      flush(i)
      start = i
      inPosition = p
    }
  }
  flush(s.length)
  return out
}

/* ---- pane 02: annualised vol vs target vol ---- */
const volChart = computed(() => {
  const s = series.value
  if (s.length < 2) return null
  const vals = s.map((p) => (p.ann_vol != null ? p.ann_vol * 100.0 : NaN))
  const target = targetVolRatio.value * 100.0
  const { scale, ticks } = yAxis([...vals, target], VOL_H, 0)
  const pts = s
    .map((p, i) => ({
      x: xScale.value(i),
      y: scale(p.ann_vol != null ? p.ann_vol * 100.0 : NaN),
    }))
    .filter((pt) => Number.isFinite(pt.y))

  return {
    path: linePath(pts),
    targetY: scale(target),
    ticks: ticks.map((t) => ({ v: t, y: scale(t) })),
  }
})

/* ---- pane 03: leverage & cap ---- */
const leverageChart = computed(() => {
  const s = series.value
  if (s.length < 2) return null
  const vals = s.map((p) => p.leverage ?? NaN)
  const cap = levCap.value
  const { scale, ticks } = yAxis([...vals, cap], LEV_H, 0)
  const pts = s
    .map((p, i) => ({
      x: xScale.value(i),
      y: scale(p.leverage ?? NaN),
    }))
    .filter((pt) => Number.isFinite(pt.y))

  return {
    path: linePath(pts),
    capY: scale(cap),
    ticks: ticks.map((t) => ({ v: t, y: scale(t) })),
  }
})

/* ---- readouts & summary ---- */
const nowBlock = computed(() => d.value?.now ?? null)
const isBuySignal = computed(() => nowBlock.value?.signal === 'BUY')
const stats = computed(() => d.value?.stats ?? null)
const trades = computed<VolTargetTrade[]>(() => d.value?.trades ?? [])
const positionTone = computed(() => (nowBlock.value?.position === 'long' ? 'pos' : 'flat'))
const winRateLabel = computed(() =>
  stats.value?.win_rate_pct == null ? DASH : `${num(stats.value.win_rate_pct, 1)}%`,
)
const pnlTone = computed(() => ((stats.value?.total_pnl ?? 0) >= 0 ? 'pos' : 'neg'))
const paramsLine = computed(() => {
  const p = d.value?.params
  if (!p) return ''
  const bpd = p.bars_per_day == null ? DASH : num(p.bars_per_day, 2)
  const fb = p.fast_bars == null ? DASH : num(p.fast_bars, 0)
  const sb = p.slow_bars == null ? DASH : num(p.slow_bars, 0)
  const vb = p.vol_bars == null ? DASH : num(p.vol_bars, 0)
  return `Target Vol: ${num(p.target_vol * 100, 1)}% · Lev Cap: ${num(p.lev_cap, 1)}x · Fast: ${num(p.fast_days, 0)}d (${fb}b) · Slow: ${num(p.slow_days, 0)}d (${sb}b) · Vol Lookback: ${num(p.vol_days, 0)}d (${vb}b) · ${bpd} bars/day`
})
</script>

<template>
  <div class="view">
    <Panel
      label="Volatility-Targeted Trend"
      index="16"
      :meta="d?.generated_at ? `computed ${shortDate(d.generated_at.slice(0, 10))}` : ''"
      class="w-full"
    >
      <div class="banner label">
        <span>
          <strong>Live Signal Desk:</strong> Keep your stocks in the watchlist below to monitor real-time BUY / SELL signals and volatility-targeted position sizing.
        </span>
        <HelpTip
          label="Signal & Sizing Rules"
          text="leverage = min(target_vol / ann_vol, lev_cap). Signal triggers BUY on Fast EMA > Slow EMA crossover, and SELL on cross below. Size is fixed at entry based on volatility known at signal time without look-ahead."
        />
      </div>

      <div class="controls">
        <div class="ctl symbol-ctl">
          <label class="label" for="vol-sym">Inspect Symbol</label>
          <div class="sym-row">
            <input
              id="vol-sym"
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
          <label class="label" for="vol-capital">Capital ($)</label>
          <input
            id="vol-capital"
            v-model.number="capital"
            class="fig input"
            type="number"
            min="1000"
            max="100000000"
            step="10000"
          />
        </div>

        <div class="ctl">
          <label class="label" for="vol-target">Target Vol %</label>
          <input
            id="vol-target"
            v-model.number="targetVolPct"
            class="fig input"
            type="number"
            min="1"
            max="100"
            step="1"
          />
        </div>

        <div class="ctl settings-toggle-ctl">
          <label class="label">Calibration</label>
          <button
            type="button"
            class="btn label params-toggle-btn"
            :class="{ active: showParams }"
            @click="showParams = !showParams"
          >
            ⚙ {{ showParams ? 'Hide Calibration' : 'Calibration' }}
          </button>
        </div>
      </div>

      <div v-show="showParams" class="controls-sub">
        <div class="ctl">
          <label class="label" for="vol-win">Window</label>
          <select id="vol-win" v-model="win" class="fig input">
            <option v-for="w in WINDOWS" :key="w" :value="w">{{ w }}</option>
          </select>
        </div>

        <div class="ctl">
          <label class="label" for="vol-bars">Bars</label>
          <select id="vol-bars" v-model="barsMode" class="fig input">
            <option value="daily">daily</option>
            <option value="1h">1h</option>
          </select>
        </div>

        <div class="ctl">
          <label class="label" for="vol-lev-cap">Leverage Cap</label>
          <input
            id="vol-lev-cap"
            v-model.number="levCap"
            class="fig input"
            type="number"
            min="0.5"
            max="10"
            step="0.5"
          />
        </div>

        <div class="ctl">
          <label class="label" for="vol-fast">Fast EMA (days)</label>
          <input
            id="vol-fast"
            v-model.number="fastDays"
            class="fig input"
            type="number"
            min="1"
            max="100"
            step="1"
          />
        </div>

        <div class="ctl">
          <label class="label" for="vol-slow">Slow EMA (days)</label>
          <input
            id="vol-slow"
            v-model.number="slowDays"
            class="fig input"
            type="number"
            min="2"
            max="300"
            step="1"
          />
        </div>

        <div class="ctl">
          <label class="label" for="vol-lookback">Vol Window (days)</label>
          <input
            id="vol-lookback"
            v-model.number="volDays"
            class="fig input"
            type="number"
            min="2"
            max="200"
            step="1"
          />
        </div>

        <p class="params label">{{ paramsLine }}</p>
      </div>

      <!-- Tracked Watchlist & Live Signals Board -->
      <section class="watchlist-section" aria-label="Tracked Stocks and Real-Time Signals">
        <div class="wl-head">
          <div class="wl-title-col">
            <h2 class="label wl-title">MY TRACKED STOCKS & SIGNALS</h2>
            <span class="label wl-sub">
              Keep your stocks pinned here for continuous BUY / SELL tracking &amp; dynamic sizing
            </span>
          </div>

          <div class="wl-add-row">
            <input
              v-model="newTrackedInput"
              class="fig input wl-input"
              type="text"
              spellcheck="false"
              placeholder="ADD TICKER..."
              aria-label="Add ticker to tracked stocks"
              @keyup.enter="addTrackedSymbol(newTrackedInput)"
            />
            <button
              type="button"
              class="btn label wl-add-btn"
              @click="addTrackedSymbol(newTrackedInput)"
            >
              + Keep Stock
            </button>
            <button
              type="button"
              class="btn label wl-refresh-btn"
              title="Refresh tracked signals"
              @click="signalsResource.refresh({ clear: false })"
            >
              ↻
            </button>
          </div>
        </div>

        <div class="presets-row">
          <span class="label presets-label">Quick Presets:</span>
          <button
            v-for="sym in QUICK_PRESETS"
            :key="sym"
            type="button"
            class="preset-chip label"
            :class="{ active: isTracked(sym) }"
            @click="isTracked(sym) ? removeTrackedSymbol(sym) : addTrackedSymbol(sym)"
          >
            {{ isTracked(sym) ? `✓ ${sym}` : `+ ${sym}` }}
          </button>
        </div>

        <div class="table-wrap wl-table-wrap">
          <table class="table fig">
            <thead>
              <tr>
                <th class="label">Stock</th>
                <th class="label center">Current Signal</th>
                <th class="label">Signal Since</th>
                <th class="label right">Entry Px</th>
                <th class="label right">Last Px</th>
                <th class="label right">Signal Return</th>
                <th class="label right">Ann Vol</th>
                <th class="label right">Lev</th>
                <th class="label right">Target Qty</th>
                <th class="label right">Notional</th>
                <th class="label center">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in signalItems"
                :key="item.symbol"
                :class="{ 'active-row': item.symbol === symbol }"
              >
                <td>
                  <button
                    type="button"
                    class="sym-btn fig"
                    :title="`Inspect ${item.symbol} chart & details`"
                    @click="loadSymbol(item.symbol)"
                  >
                    {{ item.symbol }}
                  </button>
                </td>
                <td class="center">
                  <span
                    class="signal-badge label"
                    :class="item.signal === 'BUY' ? 'badge-buy' : 'badge-sell'"
                  >
                    <span class="signal-dot" />
                    {{ item.signal === 'BUY' ? 'BUY / LONG' : 'SELL / CASH' }}
                  </span>
                </td>
                <td>
                  <span v-if="item.signal_date">
                    {{ shortDate(item.signal_date.slice(0, 10)) }}
                    <span class="bars-ago label">({{ item.signal_bars }}b ago)</span>
                  </span>
                  <span v-else>{{ DASH }}</span>
                </td>
                <td class="right">{{ item.signal_px != null ? usd(item.signal_px) : DASH }}</td>
                <td class="right">{{ item.close != null ? usd(item.close) : DASH }}</td>
                <td
                  class="right"
                  :class="{ pos: item.signal_pnl_pct > 0, neg: item.signal_pnl_pct < 0 }"
                >
                  {{ item.signal_pnl_pct != null ? `${optSigned(item.signal_pnl_pct, 2)}%` : DASH }}
                </td>
                <td class="right">
                  {{ item.ann_vol != null ? `${num(item.ann_vol * 100, 1)}%` : DASH }}
                </td>
                <td class="right">{{ item.leverage != null ? `${num(item.leverage, 2)}x` : DASH }}</td>
                <td class="right">
                  {{
                    item.signal === 'BUY' && item.target_qty != null
                      ? `${num(item.target_qty, 0)} shs`
                      : '0 shs'
                  }}
                </td>
                <td class="right">
                  {{
                    item.signal === 'BUY' && item.target_notional != null
                      ? usd(item.target_notional)
                      : '$0'
                  }}
                </td>
                <td class="center actions-cell">
                  <button
                    type="button"
                    class="action-inspect label"
                    :class="{ current: item.symbol === symbol }"
                    @click="loadSymbol(item.symbol)"
                  >
                    {{ item.symbol === symbol ? 'Viewing' : 'Chart' }}
                  </button>
                  <button
                    type="button"
                    class="action-remove label"
                    :title="`Remove ${item.symbol} from tracked stocks`"
                    @click="removeTrackedSymbol(item.symbol)"
                  >
                    ×
                  </button>
                </td>
              </tr>
              <tr v-if="!signalItems.length">
                <td colspan="11" class="empty label">
                  <template v-if="signalsResource.error.value">
                    <span class="neg">Failed to load signals: {{ signalsResource.error.value }}</span>
                    <button type="button" class="btn label wl-retry-btn" @click="signalsResource.refresh({ clear: true })">Retry</button>
                  </template>
                  <template v-else-if="signalsResource.loading.value">
                    Loading tracked signals...
                  </template>
                  <template v-else>
                    No stocks currently tracked. Add a ticker above to begin monitoring signals.
                  </template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <LoadingState v-if="loading && !d" label="Evaluating volatility-targeted trend..." />
      <p v-else-if="detail.error.value" class="state err label">{{ detail.error.value }}</p>
      <p v-else-if="d && !available" class="state label">
        {{ d.reason ?? 'No trend output for this symbol.' }}
      </p>

      <template v-else-if="available && d">
        <!-- Decision Blueprint Hero Card -->
        <div class="blueprint-card" :class="isBuySignal ? 'bp-buy' : 'bp-sell'">
          <div class="bp-top">
            <div class="bp-signal-box">
              <div class="bp-badge-row">
                <span class="bp-badge label" :class="isBuySignal ? 'badge-buy' : 'badge-sell'">
                  <span class="bp-pulse" />
                  {{ isBuySignal ? 'BUY / LONG SIGNAL' : 'SELL / CASH EXIT' }}
                </span>
                <span class="bp-ticker fig">{{ d.symbol }}</span>
              </div>
              <p class="bp-rationale label">
                <template v-if="isBuySignal">
                  Fast EMA ({{ optNum(nowBlock?.ema_fast, 2) }}) &gt; Slow EMA ({{ optNum(nowBlock?.ema_slow, 2) }}).
                  Bullish regime active for {{ nowBlock?.signal_bars ?? 0 }} bars since {{ nowBlock?.signal_date ?? DASH }}.
                  Vol is {{ num((nowBlock?.ann_vol ?? 0) * 100, 1) }}% (target: {{ targetVolPct }}%).
                </template>
                <template v-else>
                  Fast EMA ({{ optNum(nowBlock?.ema_fast, 2) }}) &le; Slow EMA ({{ optNum(nowBlock?.ema_slow, 2) }}).
                  Trend crossover absent or negative. Sizing is defensive (100% Cash preservation).
                </template>
              </p>
            </div>

            <div class="bp-track-col">
              <button
                type="button"
                class="btn label bp-track-btn"
                :class="{ tracked: isTracked(d.symbol) }"
                @click="toggleTrackCurrent"
              >
                {{ isTracked(d.symbol) ? '✓ Keep in Tracked' : '+ Keep This Stock' }}
              </button>
            </div>
          </div>

          <div class="bp-specs-grid">
            <div class="bp-spec">
              <span class="label bp-spec-label">Order Action</span>
              <span class="fig bp-spec-val" :class="isBuySignal ? 'pos' : ''">
                {{ isBuySignal ? 'ENTER / HOLD LONG' : 'EXIT TO CASH' }}
              </span>
              <span class="label bp-spec-sub">
                {{ isBuySignal ? 'Execute at next bar open' : 'Stand aside in defensive cash' }}
              </span>
            </div>

            <div class="bp-spec">
              <span class="label bp-spec-label">Recommended Size</span>
              <span class="fig bp-spec-val">
                {{ isBuySignal && nowBlock?.target_qty != null ? `${num(nowBlock.target_qty, 0)} shares` : '0 shares' }}
              </span>
              <span class="label bp-spec-sub">
                {{ isBuySignal && nowBlock?.target_notional != null ? usd(nowBlock.target_notional) : '$0 notional' }}
              </span>
            </div>

            <div class="bp-spec">
              <span class="label bp-spec-label">Target Leverage</span>
              <span class="fig bp-spec-val">
                {{ isBuySignal && nowBlock?.leverage != null ? `${num(nowBlock.leverage, 2)}x` : '0.00x' }}
              </span>
              <span class="label bp-spec-sub">Capped at {{ num(levCap, 1) }}x</span>
            </div>

            <div class="bp-spec">
              <span class="label bp-spec-label">Signal Entry / P&amp;L</span>
              <span
                class="fig bp-spec-val"
                :class="{ pos: (nowBlock?.signal_pnl_pct ?? 0) > 0, neg: (nowBlock?.signal_pnl_pct ?? 0) < 0 }"
              >
                {{ nowBlock?.signal_pnl_pct != null ? `${optSigned(nowBlock.signal_pnl_pct, 2)}%` : DASH }}
              </span>
              <span class="label bp-spec-sub">
                {{ nowBlock?.signal_px != null ? `Entry: ${usd(nowBlock.signal_px)}` : 'Entry: —' }}
              </span>
            </div>
          </div>
        </div>

        <!-- Collapsible Historical Backtest & Technical Charts (Optional) -->
        <div class="backtest-drawer">
          <button
            type="button"
            class="btn label backtest-toggle-btn"
            @click="showBacktest = !showBacktest"
          >
            <span>{{ showBacktest ? '▲ Hide Historical Backtest & Technical Charts' : '▼ Show Historical Backtest & Technical Charts (Optional)' }}</span>
            <span class="backtest-hint label">Win Rate · Reconstructed Trades · Multi-Pane Charts</span>
          </button>

          <div v-show="showBacktest" class="backtest-body">
            <div class="readout-grid">
              <Readout
                label="Position Now"
            :value="(nowBlock?.position ?? 'flat').toUpperCase()"
            :tone="positionTone"
            :sub="nowBlock?.forced_exit ? 'open at end of data' : `as of ${nowBlock?.date ?? DASH}`"
          />
          <Readout
            label="Signal State"
            :value="nowBlock?.up_trend ? 'BULLISH CROSS' : 'BEARISH / FLAT'"
            :tone="nowBlock?.up_trend ? 'pos' : 'flat'"
            :sub="`Fast ${fastDays}d vs Slow ${slowDays}d`"
          />
          <Readout
            label="Realised Vol"
            :value="nowBlock?.ann_vol != null ? `${num(nowBlock.ann_vol * 100, 1)}%` : DASH"
            :sub="`Target: ${targetVolPct}%`"
            :tone="(nowBlock?.ann_vol ?? 0) <= targetVolRatio ? 'pos' : 'flat'"
          />
          <Readout
            label="Target Leverage"
            :value="nowBlock?.leverage != null ? `${num(nowBlock.leverage, 2)}x` : DASH"
            :sub="`Cap: ${num(levCap, 1)}x`"
            tone="accent"
          />
          <Readout
            label="Target Notional"
            :value="nowBlock?.target_notional != null ? usd(nowBlock.target_notional) : DASH"
            :sub="nowBlock?.target_qty != null ? `${num(nowBlock.target_qty, 0)} shares` : ''"
          />
          <Readout
            label="Win Rate"
            :value="winRateLabel"
            :sub="`${stats?.n_trades ?? 0} round trips`"
          />
          <Readout
            label="Total P&L"
            :value="stats?.total_pnl != null ? usd(stats.total_pnl) : DASH"
            :sub="
              stats?.compounded_pct != null
                ? `${optSigned(stats.compounded_pct, 1)}% on capital`
                : ''
            "
            :tone="pnlTone"
          />
          <Readout
            label="Profit Factor"
            :value="stats?.profit_factor != null ? num(stats.profit_factor, 2) : DASH"
            :sub="
              stats?.max_drawdown_pct != null ? `Max DD: -${num(stats.max_drawdown_pct, 1)}%` : ''
            "
          />
        </div>

        <p class="caveat label">{{ d.caveat }}</p>

        <figure class="figure">
          <!-- Pane 01: Price and EMAs -->
          <div class="pane-header">
            <figcaption class="label fig-cap">
              01 · {{ d.symbol }} close with Fast EMA (cyan), Slow EMA (rule), and held position
              bands
            </figcaption>
            <div class="legend label">
              <span class="legend-item"><span class="swatch close-swatch" /> Close</span>
              <span class="legend-item"
                ><span class="swatch fast-swatch" /> Fast EMA ({{ fastDays }}d)</span
              >
              <span class="legend-item"
                ><span class="swatch slow-swatch" /> Slow EMA ({{ slowDays }}d)</span
              >
              <span class="legend-item"><span class="swatch pos-swatch" /> Long Held</span>
            </div>
          </div>
          <svg
            class="pane"
            :viewBox="`0 0 ${W} ${PRICE_H}`"
            preserveAspectRatio="none"
            role="img"
            :aria-label="`${d.symbol} close with trend signals`"
          >
            <g v-if="priceChart">
              <rect
                v-for="(b, i) in priceChart.bands"
                :key="`b${i}`"
                :x="b.x"
                :y="b.y"
                :width="b.w"
                :height="b.h"
                class="band long"
              />
              <g v-for="t in priceChart.ticks" :key="`pt${t.v}`">
                <line class="grid" :x1="PAD_L" :y1="t.y" :x2="W - PAD_R" :y2="t.y" />
                <text class="axis fig" :x="PAD_L - 8" :y="t.y + 3" text-anchor="end">
                  {{ num(t.v, 2) }}
                </text>
              </g>
              <path class="slow-line" :d="priceChart.emaSPath" />
              <path class="fast-line" :d="priceChart.emaFPath" />
              <path class="price-line" :d="priceChart.closePath" />
            </g>
          </svg>

          <!-- Pane 02: Realised Volatility -->
          <div class="pane-header">
            <figcaption class="label fig-cap">
              02 · Annualised realised volatility (%) vs target volatility ({{ targetVolPct }}%)
            </figcaption>
          </div>
          <svg
            class="pane"
            :viewBox="`0 0 ${W} ${VOL_H}`"
            preserveAspectRatio="none"
            role="img"
            aria-label="Realised volatility vs target"
          >
            <g v-if="volChart">
              <g v-for="t in volChart.ticks" :key="`vt${t.v}`">
                <line class="grid" :x1="PAD_L" :y1="t.y" :x2="W - PAD_R" :y2="t.y" />
                <text class="axis fig" :x="PAD_L - 8" :y="t.y + 3" text-anchor="end">
                  {{ num(t.v, 0) }}%
                </text>
              </g>
              <line
                class="ref-line"
                :x1="PAD_L"
                :y1="volChart.targetY"
                :x2="W - PAD_R"
                :y2="volChart.targetY"
              />
              <path class="vol-line" :d="volChart.path" />
            </g>
          </svg>

          <!-- Pane 03: Leverage & Sizing -->
          <div class="pane-header">
            <figcaption class="label fig-cap">
              03 · Dynamic entry leverage (notional / capital) vs cap ({{ levCap }}x)
            </figcaption>
          </div>
          <svg
            class="pane"
            :viewBox="`0 0 ${W} ${LEV_H}`"
            preserveAspectRatio="none"
            role="img"
            aria-label="Dynamic leverage"
          >
            <g v-if="leverageChart">
              <g v-for="t in leverageChart.ticks" :key="`lt${t.v}`">
                <line class="grid" :x1="PAD_L" :y1="t.y" :x2="W - PAD_R" :y2="t.y" />
                <text class="axis fig" :x="PAD_L - 8" :y="t.y + 3" text-anchor="end">
                  {{ num(t.v, 1) }}x
                </text>
              </g>
              <line
                class="ref-line cap-line"
                :x1="PAD_L"
                :y1="leverageChart.capY"
                :x2="W - PAD_R"
                :y2="leverageChart.capY"
              />
              <path class="lev-line" :d="leverageChart.path" />
            </g>
          </svg>

          <!-- Shared Time Axis -->
          <svg
            class="axis-bar"
            :viewBox="`0 0 ${W} 22`"
            preserveAspectRatio="none"
            role="presentation"
          >
            <g v-for="(t, i) in xTicks" :key="`xt${i}`">
              <line class="axis-tick" :x1="t.x" y1="0" :x2="t.x" y2="4" />
              <text class="axis fig" :x="t.x" y="15" text-anchor="middle">
                {{ t.label }}
              </text>
            </g>
          </svg>
        </figure>

        <!-- Trades Table -->
        <div class="trades-panel">
          <div class="trades-head">
            <h3 class="label panel-title">RECONSTRUCTED ROUND TRIPS ({{ trades.length }})</h3>
            <span class="label trades-sub">Filled at bar i+1 open without look-ahead</span>
          </div>

          <div v-if="trades.length" class="table-wrap">
            <table class="table fig">
              <thead>
                <tr>
                  <th class="label">Entry Date</th>
                  <th class="label">Exit Date</th>
                  <th class="label">Dir</th>
                  <th class="label right">Entry Px</th>
                  <th class="label right">Exit Px</th>
                  <th class="label right">Size (Qty)</th>
                  <th class="label right">Notional</th>
                  <th class="label right">Leverage</th>
                  <th class="label right">Return</th>
                  <th class="label right">P&L ($)</th>
                  <th class="label right">Bars</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(t, i) in trades" :key="`t${i}`">
                  <td>{{ t.entry_d }}</td>
                  <td>
                    {{ t.exit_d }}
                    <span v-if="t.forced_exit" class="chip forced-chip">OPEN</span>
                  </td>
                  <td>
                    <span class="chip long-chip">LONG</span>
                  </td>
                  <td class="right">{{ optNum(t.entry_px, 2) }}</td>
                  <td class="right">{{ optNum(t.exit_px, 2) }}</td>
                  <td class="right">{{ num(t.qty, 0) }}</td>
                  <td class="right">{{ usd(t.notional) }}</td>
                  <td class="right">{{ num(t.leverage, 2) }}x</td>
                  <td
                    class="right"
                    :class="{ pos: (t.ret_pct ?? 0) > 0, neg: (t.ret_pct ?? 0) < 0 }"
                  >
                    {{ optSigned(t.ret_pct, 2) }}%
                  </td>
                  <td class="right" :class="{ pos: (t.pnl ?? 0) > 0, neg: (t.pnl ?? 0) < 0 }">
                    {{ usd(t.pnl) }}
                  </td>
                  <td class="right">{{ t.bars }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="empty label">No trades triggered in this window.</p>
        </div>
      </div>
    </div>
  </template>
    </Panel>
  </div>
</template>

<style scoped>
.view {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  padding: var(--s4);
}

.banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  margin-bottom: var(--s3);
  color: var(--ink-soft);
  background: var(--surface-overlay);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--s3);
  padding-bottom: var(--s3);
  border-bottom: var(--hair) solid var(--rule);
}

.ctl {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ctl label {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  text-transform: uppercase;
  letter-spacing: 0.04em;
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
  min-width: 200px;
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

.params {
  margin: var(--s2) 0 0;
  color: var(--ink-faint);
  font-size: var(--t-small);
}

.readout-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--s3);
  margin-top: var(--s4);
}

.caveat {
  margin: var(--s3) 0 var(--s2);
  color: var(--ink-faint);
  font-size: var(--t-small);
}

.figure {
  margin: 0;
  padding: var(--s3);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.pane-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--s2);
  margin-top: var(--s2);
}

.fig-cap {
  color: var(--ink-soft);
  font-size: var(--t-small);
}

.legend {
  display: flex;
  gap: var(--s3);
  color: var(--ink-faint);
  font-size: var(--t-nano);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.swatch {
  display: inline-block;
  width: 12px;
  height: 3px;
  border-radius: 1px;
}

.close-swatch {
  background: var(--ink);
}

.fast-swatch {
  background: var(--phosphor);
}

.slow-swatch {
  background: var(--action-focus);
}

.pos-swatch {
  background: var(--long-wash);
  height: 8px;
  width: 8px;
}

.pane {
  width: 100%;
  height: auto;
  display: block;
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.axis-bar {
  width: 100%;
  height: 22px;
  display: block;
}

.grid {
  stroke: var(--rule);
  stroke-width: 1px;
  stroke-dasharray: 2 4;
}

.axis {
  fill: var(--ink-faint);
  font-size: var(--t-nano);
}

.axis-tick {
  stroke: var(--rule-hi);
  stroke-width: 1px;
}

.price-line {
  fill: none;
  stroke: var(--ink);
  stroke-width: 1.5px;
}

.fast-line {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1.2px;
}

.slow-line {
  fill: none;
  stroke: var(--action-focus);
  stroke-width: 1.2px;
}

.vol-line {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1.5px;
}

.lev-line {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1.5px;
}

.ref-line {
  stroke: var(--ink-soft);
  stroke-width: 1px;
  stroke-dasharray: 4 4;
}

.cap-line {
  stroke: var(--warn);
}

.band.long {
  fill: var(--long-wash);
}

.trades-panel {
  margin-top: var(--s4);
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.trades-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.panel-title {
  color: var(--ink);
  font-size: var(--t-small);
  letter-spacing: 0.04em;
}

.trades-sub {
  color: var(--ink-faint);
  font-size: var(--t-nano);
}

.table-wrap {
  overflow-x: auto;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--panel);
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-small);
}

.table th,
.table td {
  padding: 6px var(--s2);
  border-bottom: var(--hair) solid var(--rule);
  white-space: nowrap;
}

.table th {
  background: var(--panel-hi);
  color: var(--ink-faint);
  font-size: var(--t-nano);
  text-align: left;
}

.table td {
  color: var(--ink);
}

.table tr:hover td {
  background: var(--panel-hi);
}

.right {
  text-align: right;
}

.pos {
  color: var(--long) !important;
}

.neg {
  color: var(--short) !important;
}

.chip {
  display: inline-block;
  padding: 1px 4px;
  font-size: var(--t-nano);
  border-radius: var(--r-sm);
}

.long-chip {
  background: var(--long-wash);
  color: var(--long);
}

.forced-chip {
  background: var(--warn-wash);
  color: var(--warn);
  margin-left: 4px;
}

.empty {
  padding: var(--s3);
  color: var(--ink-faint);
  text-align: center;
}

.state {
  padding: var(--s4);
  color: var(--ink-faint);
  text-align: center;
}

.state.err {
  color: var(--short);
}

/* Watchlist & signals section */
.watchlist-section {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  margin-top: var(--s2);
  padding: var(--s3);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.wl-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: var(--s3);
}

.wl-title-col {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.wl-title {
  color: var(--ink);
  font-size: var(--t-display);
  letter-spacing: 0.04em;
  margin: 0;
}

.wl-sub {
  color: var(--ink-faint);
  font-size: var(--t-small);
}

.wl-add-row {
  display: flex;
  gap: var(--s1);
  align-items: center;
}

.wl-input {
  width: 140px;
}

.wl-add-btn {
  background: var(--panel-hi);
  color: var(--phosphor);
  border-color: var(--rule-hi);
}

.wl-add-btn:hover {
  background: var(--panel-raise);
}

.wl-refresh-btn {
  background: var(--panel-hi);
  color: var(--ink-faint);
  border-color: var(--rule-hi);
  padding: 0 var(--s2);
}

.wl-refresh-btn:hover {
  color: var(--ink);
  background: var(--panel-raise);
}

.wl-retry-btn {
  margin-left: var(--s2);
  padding: 2px var(--s2);
  font-size: var(--t-nano);
  background: var(--panel-raise);
  color: var(--ink);
}

.presets-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s1);
  margin-top: 4px;
}

.presets-label {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  text-transform: uppercase;
  margin-right: 4px;
}

.preset-chip {
  padding: 2px 6px;
  background: var(--panel-hi);
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  cursor: pointer;
  font-size: var(--t-nano);
}

.preset-chip:hover {
  color: var(--ink);
  border-color: var(--rule-hi);
}

.preset-chip.active {
  background: var(--phosphor-wash);
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

.wl-table-wrap {
  margin-top: var(--s2);
}

.center {
  text-align: center;
}

.active-row td {
  background: var(--wash-2);
}

.sym-btn {
  background: none;
  border: 0;
  color: var(--ink);
  font-weight: bold;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: var(--r-sm);
}

.sym-btn:hover {
  color: var(--phosphor);
  text-decoration: underline;
}

.signal-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: var(--r-sm);
  font-weight: bold;
  font-size: var(--t-nano);
  letter-spacing: 0.04em;
}

.badge-buy {
  background: var(--long-wash);
  color: var(--long);
  border: var(--hair) solid var(--long);
}

.badge-sell {
  background: var(--short-wash);
  color: var(--short);
  border: var(--hair) solid var(--short);
}

.signal-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.bars-ago {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  margin-left: 4px;
}

.actions-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--s1);
}

.action-inspect {
  padding: 2px 6px;
  background: var(--panel-raise);
  color: var(--ink-soft);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  cursor: pointer;
  font-size: var(--t-nano);
}

.action-inspect:hover,
.action-inspect.current {
  color: var(--phosphor);
  border-color: var(--phosphor);
}

.action-remove {
  padding: 2px 6px;
  background: none;
  border: var(--hair) solid transparent;
  color: var(--ink-faint);
  border-radius: var(--r-sm);
  cursor: pointer;
  font-size: var(--t-small);
}

.action-remove:hover {
  color: var(--short);
  border-color: var(--rule-hi);
}

/* Blueprint Hero Card */
.blueprint-card {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s3);
  border-radius: var(--r-sm);
  border: var(--hair) solid var(--rule);
  margin-top: var(--s3);
  background: var(--panel);
}

.bp-buy {
  border-color: var(--call-dim);
  background: var(--long-wash);
}

.bp-sell {
  border-color: var(--rule-hi);
  background: var(--panel-hi);
}

.bp-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: var(--s2);
}

.bp-signal-box {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
}

.bp-badge-row {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.bp-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--r-sm);
  font-size: var(--t-small);
  font-weight: bold;
  letter-spacing: 0.05em;
}

.bp-pulse {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

.bp-ticker {
  font-size: var(--t-display);
  font-weight: bold;
  color: var(--ink);
}

.bp-rationale {
  color: var(--ink-soft);
  font-size: var(--t-small);
  margin: 0;
  max-width: 650px;
}

.bp-track-btn {
  font-size: var(--t-small);
  background: var(--panel-raise);
  color: var(--ink);
  border: var(--hair) solid var(--rule-hi);
}

.bp-track-btn.tracked {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.bp-specs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--s2);
  padding-top: var(--s2);
  border-top: var(--hair) solid var(--rule);
}

.bp-spec {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.bp-spec-label {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.bp-spec-val {
  color: var(--ink);
  font-size: var(--t-body);
  font-weight: bold;
}

.bp-spec-sub {
  color: var(--ink-dim);
  font-size: var(--t-nano);
}

/* Calibration & sub-controls */
.settings-toggle-ctl {
  justify-content: flex-end;
}

.params-toggle-btn {
  height: var(--density-control-h);
  background: var(--panel-raise);
  color: var(--ink-soft);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
  cursor: pointer;
  padding: 0 var(--s3);
  font-size: var(--t-nano);
}

.params-toggle-btn:hover {
  color: var(--ink);
  border-color: var(--phosphor);
}

.params-toggle-btn.active {
  color: var(--phosphor);
  border-color: var(--phosphor);
  background: var(--phosphor-wash);
}

.controls-sub {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--s3);
  padding: var(--s2) 0;
  border-bottom: var(--hair) solid var(--rule);
}

/* Backtest Collapsible Drawer */
.backtest-drawer {
  margin-top: var(--s4);
  padding-top: var(--s3);
  border-top: var(--hair) solid var(--rule);
}

.backtest-toggle-btn {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  height: 38px;
  padding: 0 var(--s3);
  background: var(--panel-hi);
  color: var(--ink-soft);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  cursor: pointer;
  font-size: var(--t-small);
}

.backtest-toggle-btn:hover {
  color: var(--ink);
  border-color: var(--rule-hi);
  background: var(--panel-raise);
}

.backtest-hint {
  color: var(--ink-faint);
  font-size: var(--t-nano);
}

.backtest-body {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  margin-top: var(--s3);
}
</style>
