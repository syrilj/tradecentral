<script setup lang="ts">
import { computed } from 'vue'
import { num, optSigned, DASH } from '@/format'
import type { GammaRegime } from '@/regimeContracts'

const props = withDefaults(
  defineProps<{
    symbol: string
    symbolsList?: readonly string[] | string[]
    spot?: number | null
    dayChangeDollar?: number | null
    dayChangePct?: number | null
    ivRank?: number | null
    ivPercentile?: number | null
    hv20d?: number | null
    hv30d?: number | null
    putCallRatio?: number | null
    totalGexM?: number | null
    netFlowM?: number | null
    nextExpiryDte?: number | null
    nextExpiryDate?: string | null
    regime?: GammaRegime | null
    customRegimeLabel?: string | null
    activeTimeframe?: string
    sparklinePoints?: number[]
    callWall?: number | null
    putWall?: number | null
    gammaFlip?: number | null
    pinStrike?: number | null
    em1dDollars?: number | null
    em1dPct?: number | null
    /** Bar timestamp the quote came from — never the request time. */
    quoteAsof?: string | null
    /** 'live' when a real-time mark backed it; 'local' when the provider
     *  failed and the last stored daily close was substituted. */
    quoteQuality?: string | null
  }>(),
  {
    symbolsList: () => [],
    spot: null,
    dayChangeDollar: null,
    dayChangePct: null,
    ivRank: null,
    ivPercentile: null,
    hv20d: null,
    hv30d: null,
    putCallRatio: null,
    totalGexM: null,
    netFlowM: null,
    nextExpiryDte: null,
    nextExpiryDate: null,
    regime: null,
    customRegimeLabel: null,
    activeTimeframe: '1D',
    sparklinePoints: () => [],
    callWall: null,
    putWall: null,
    gammaFlip: null,
    pinStrike: null,
    em1dDollars: null,
    em1dPct: null,
    quoteAsof: null,
    quoteQuality: null,
  },
)

/**
 * The provider falls back to the last stored daily close whenever the LSE
 * quota trips, and says so honestly in `quality`/`asof`. This ribbon used to
 * discard both, so a six-day-old $164.75 close rendered exactly like a live
 * mark and its close-to-close move printed as "-41.88 (-20.27%)" — the
 * 09-01→09-02 session presented as today's tape.
 */
const quoteIsLive = computed(() => {
  const q = props.quoteQuality
  if (q === 'local' || q === 'eod_parquet' || q === 'unavailable' || q === 'stale') return false
  if (quoteAgeDays.value != null && quoteAgeDays.value >= 1) return false
  return q == null || q === 'live' || q === 'realtime' || q === 'delayed'
})

/** Calendar days between the quote's bar and now, or null when undatable. */
const quoteAgeDays = computed<number | null>(() => {
  if (!props.quoteAsof) return null
  const t = Date.parse(props.quoteAsof)
  if (Number.isNaN(t)) return null
  return Math.floor((Date.now() - t) / 86_400_000)
})

const quoteAsofLabel = computed<string | null>(() =>
  props.quoteAsof ? String(props.quoteAsof).slice(0, 10) : null,
)

/** Shown only when the mark is not live: a stale close is not "today". */
const staleNote = computed<string | null>(() => {
  if (quoteIsLive.value) return null
  const age = quoteAgeDays.value
  const asof = quoteAsofLabel.value
  if (asof == null) return 'STALE MARK'
  return age != null && age >= 1 ? `STALE · ${asof} (${age}d old)` : `STALE · ${asof}`
})

const emit = defineEmits<{
  'select-symbol': [symbol: string]
  'select-timeframe': [timeframe: string]
}>()

const changeTone = computed(() => {
  const pct = props.dayChangePct ?? props.dayChangeDollar
  if (pct == null) return 'neutral'
  return pct > 0 ? 'pos' : pct < 0 ? 'neg' : 'neutral'
})

const regimeLabel = computed(() => {
  if (props.customRegimeLabel) return props.customRegimeLabel
  if (props.regime === 'long') return 'Neutral → Bullish'
  if (props.regime === 'short') return 'Bearish Amplification'
  if (props.regime === 'flip') return 'At Gamma Flip'
  return 'Unmeasured'
})

const effectiveSymbols = computed(() => {
  const list =
    props.symbolsList && props.symbolsList.length > 0
      ? [...props.symbolsList]
      : ['SPY', 'QQQ', 'IWM', 'DIA', 'NVDA', 'TSLA', 'AAPL', 'MSFT']
  if (props.symbol && !list.includes(props.symbol)) {
    list.unshift(props.symbol)
  }
  return list
})

const regimeBadgeClass = computed(() => {
  if (props.customRegimeLabel) {
    const lbl = props.customRegimeLabel.toLowerCase()
    if (lbl.includes('bull') || lbl.includes('long')) return 'regime-bullish'
    if (lbl.includes('bear') || lbl.includes('short') || lbl.includes('breakdown'))
      return 'regime-bearish'
    if (lbl.includes('squeeze') || lbl.includes('breakout') || lbl.includes('flip'))
      return 'regime-warn'
    return 'regime-neutral'
  }
  if (props.regime === 'long') return 'regime-bullish'
  if (props.regime === 'short') return 'regime-bearish'
  if (props.regime === 'flip') return 'regime-warn'
  return 'regime-neutral'
})

const hasSparkline = computed(() => (props.sparklinePoints?.length ?? 0) >= 2)

const sparklinePath = computed(() => {
  const pts = props.sparklinePoints ?? []
  if (pts.length < 2) return ''
  const min = Math.min(...pts)
  const max = Math.max(...pts)
  const range = max - min || 1
  const w = 120
  const h = 20
  return pts
    .map((p, i) => {
      const x = (i / (pts.length - 1)) * w
      const y = h - ((p - min) / range) * (h - 4) - 2
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
})

const timeframes = ['1D', '5D', '1M', '3M', 'YTD', '1Y']

function levelDist(lvl: number | null): string {
  if (props.spot == null || lvl == null || props.spot <= 0) return ''
  const diff = ((lvl - props.spot) / props.spot) * 100
  const sign = diff >= 0 ? '+' : ''
  return `${sign}${num(diff, 1)}%`
}
</script>

<template>
  <div class="regime-header-ribbon">
    <div class="ticker-spot-block">
      <div class="symbol-dropdown-wrap">
        <!-- This drives the whole Regime workspace, so it needs a name: the
             visible "US EQUITIES / INDEX" beneath it is a caption, not a label,
             and unnamed it announced only as "combobox". -->
        <select
          :value="symbol"
          class="symbol-select font-mono font-bold"
          aria-label="Symbol"
          @change="emit('select-symbol', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="s in effectiveSymbols" :key="s" :value="s">{{ s }}</option>
        </select>
        <span class="symbol-sub text-ink-dim">US EQUITIES / INDEX</span>
      </div>

      <div class="spot-price-wrap">
        <div class="spot-val font-mono font-bold" :class="{ 'is-stale': !quoteIsLive }">
          {{ spot != null ? `$${num(spot, 2)}` : DASH }}
        </div>
        <div class="spot-chg font-mono font-semibold" :class="`text-${changeTone}`">
          <template v-if="dayChangeDollar != null || dayChangePct != null">
            {{ dayChangeDollar != null ? optSigned(dayChangeDollar, 2) : DASH }}
            ({{ dayChangePct != null ? optSigned(dayChangePct, 2) : DASH }}%)
            <!-- A stale mark's move is the last two stored closes, not today's
                 session. Saying which it is costs three words. -->
            <span v-if="!quoteIsLive" class="chg-basis font-mono">last 2 closes</span>
          </template>
          <template v-else>CHANGE UNMEASURED</template>
        </div>
        <div v-if="staleNote" class="spot-stale font-mono" :title="`Quote as of ${quoteAsofLabel}`">
          {{ staleNote }}
        </div>
      </div>

      <div class="sparkline-wrap" title="Intraday price trajectory">
        <!-- Not decorative: when the trace is missing this renders "NO PRICE
             TRACE", which is a real state an operator needs to hear. -->
        <svg
          class="sparkline-svg"
          role="img"
          :aria-label="
            hasSparkline
              ? `Intraday price trajectory, ${changeTone === 'pos' ? 'up' : changeTone === 'neg' ? 'down' : 'flat'} on the day`
              : 'Intraday price trajectory unavailable — no price trace'
          "
          viewBox="0 0 120 24"
          preserveAspectRatio="none"
        >
          <path
            v-if="hasSparkline"
            :d="sparklinePath"
            fill="none"
            :stroke="
              changeTone === 'pos'
                ? 'var(--call-hi)'
                : changeTone === 'neg'
                  ? 'var(--put-hi)'
                  : 'var(--ink-faint)'
            "
            stroke-width="1.75"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <text v-else x="60" y="15" text-anchor="middle" class="sparkline-missing font-mono">
            NO PRICE TRACE
          </text>
        </svg>
      </div>
    </div>

    <div class="metrics-ribbon">
      <div class="metric-pill">
        <span class="pill-label">IV Rank</span>
        <span class="pill-val font-mono font-bold text-ink">
          {{ ivRank != null ? num(ivRank, 1) : DASH }}
        </span>
      </div>
      <div class="metric-pill">
        <span class="pill-label">IV Percentile</span>
        <span class="pill-val font-mono font-bold text-ink">
          {{ ivPercentile != null ? `${num(ivPercentile, 0)}%` : DASH }}
        </span>
      </div>
      <div class="metric-pill">
        <span class="pill-label">HV 20D</span>
        <span class="pill-val font-mono font-bold text-ink">
          {{ hv20d != null ? `${num(hv20d, 1)}%` : DASH }}
        </span>
      </div>
      <div class="metric-pill">
        <span class="pill-label">HV 30D</span>
        <span class="pill-val font-mono font-bold text-ink">
          {{ hv30d != null ? `${num(hv30d, 1)}%` : DASH }}
        </span>
      </div>
      <div class="metric-pill">
        <span class="pill-label">Put/Call Vol</span>
        <span class="pill-val font-mono font-bold text-ink">
          {{ putCallRatio != null ? num(putCallRatio, 2) : DASH }}
        </span>
      </div>
      <div class="metric-pill">
        <span class="pill-label">Gamma Exposure</span>
        <span
          class="pill-val font-mono font-bold"
          :class="
            totalGexM == null ? 'text-ink-faint' : totalGexM >= 0 ? 'text-call-hi' : 'text-put-hi'
          "
        >
          {{ totalGexM != null ? `${optSigned(totalGexM, 1)}M` : DASH }}
        </span>
      </div>
      <div class="metric-pill">
        <span class="pill-label">Net Flow (Today)</span>
        <span
          class="pill-val font-mono font-bold"
          :class="
            netFlowM == null ? 'text-ink-faint' : netFlowM >= 0 ? 'text-call-hi' : 'text-put-hi'
          "
        >
          {{ netFlowM != null ? `${optSigned(netFlowM, 1)}M` : DASH }}
        </span>
      </div>
      <div class="metric-pill">
        <span class="pill-label">Next Expiry</span>
        <span
          class="pill-val font-mono font-bold"
          :class="nextExpiryDte != null && nextExpiryDte < 0 ? 'text-warn' : 'text-ink'"
        >
          <!-- A negative DTE was clamped to 0, so a chain whose nearest expiry
               had already passed advertised itself as a 0DTE board. -->
          {{
            nextExpiryDte == null
              ? DASH
              : nextExpiryDte < 0
                ? `EXPIRED ${-nextExpiryDte}D`
                : `${nextExpiryDte}D`
          }}
          <span class="pill-sub font-mono text-ink-dim">({{ nextExpiryDate || DASH }})</span>
        </span>
      </div>
      <div class="metric-pill regime-pill">
        <span class="pill-label">Market Regime</span>
        <span class="regime-badge font-mono font-bold" :class="regimeBadgeClass">
          {{ regimeLabel }}
        </span>
      </div>
    </div>

    <!-- InsiderFinance Institutional Key Gamma Levels HUD -->
    <div
      v-if="callWall != null || putWall != null || gammaFlip != null || pinStrike != null"
      class="gamma-levels-strip"
      aria-label="Institutional key gamma levels"
    >
      <span class="strip-tag font-mono">KEY LEVELS</span>
      <div
        v-if="callWall != null"
        class="level-chip chip-call"
        title="Major Call Wall (Dealer Resistance)"
      >
        <span class="lvl-name">CALL WALL</span>
        <span class="lvl-val font-mono font-bold">${{ num(callWall, 0) }}</span>
        <span v-if="levelDist(callWall)" class="lvl-dist font-mono">{{ levelDist(callWall) }}</span>
      </div>
      <div
        v-if="putWall != null"
        class="level-chip chip-put"
        title="Major Put Wall (Dealer Support)"
      >
        <span class="lvl-name">PUT WALL</span>
        <span class="lvl-val font-mono font-bold">${{ num(putWall, 0) }}</span>
        <span v-if="levelDist(putWall)" class="lvl-dist font-mono">{{ levelDist(putWall) }}</span>
      </div>
      <div
        v-if="gammaFlip != null"
        class="level-chip chip-flip"
        title="Zero-Gamma Inflection Level"
      >
        <span class="lvl-name">0-GAMMA</span>
        <span class="lvl-val font-mono font-bold">${{ num(gammaFlip, 0) }}</span>
        <span v-if="levelDist(gammaFlip)" class="lvl-dist font-mono">{{
          levelDist(gammaFlip)
        }}</span>
      </div>
      <div
        v-if="pinStrike != null"
        class="level-chip chip-pin"
        title="Max Pain / Expected Pin Strike"
      >
        <span class="lvl-name">MAX PAIN</span>
        <span class="lvl-val font-mono font-bold">${{ num(pinStrike, 0) }}</span>
        <span v-if="levelDist(pinStrike)" class="lvl-dist font-mono">{{
          levelDist(pinStrike)
        }}</span>
      </div>
      <div
        v-if="em1dDollars != null"
        class="level-chip chip-em"
        title="1-Day Expected Move (VIX / 16)"
      >
        <span class="lvl-name">1D MOVE</span>
        <span class="lvl-val font-mono font-bold">
          &plusmn;${{ num(em1dDollars, 2) }}{{ em1dPct != null ? ` (${num(em1dPct, 1)}%)` : '' }}
        </span>
      </div>
    </div>

    <div class="timeframe-group" role="group" aria-label="Timeframe selection">
      <button
        v-for="tf in timeframes"
        :key="tf"
        type="button"
        class="tf-btn"
        :class="{ active: activeTimeframe === tf }"
        @click="emit('select-timeframe', tf)"
      >
        {{ tf }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.regime-header-ribbon {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.75rem 1.25rem;
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  flex-wrap: wrap;
}

.ticker-spot-block {
  display: flex;
  align-items: center;
  gap: 1.25rem;
}

.symbol-dropdown-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.symbol-select {
  background: var(--panel-hi);
  border: 1px solid var(--rule-hi);
  color: var(--ink);
  font-size: 1.125rem;
  padding: 0.25rem 0.625rem;
  border-radius: var(--r-sm);
  cursor: pointer;
}

.symbol-sub {
  font-size: var(--t-nano);
  letter-spacing: 0.06em;
}

.spot-price-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.spot-val {
  color: var(--ink);
  font-size: 1.25rem;
}

.spot-val.is-stale {
  color: var(--ink-dim);
}
.spot-stale {
  margin-top: 0.15rem;
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  color: var(--warn);
}
.chg-basis {
  margin-left: 0.3rem;
  font-size: var(--t-nano);
  letter-spacing: 0.06em;
  color: var(--ink-faint);
}
.spot-chg {
  font-size: var(--t-micro);
}

.sparkline-wrap {
  width: 120px;
  height: 24px;
}

.sparkline-svg {
  width: 100%;
  height: 100%;
}

.sparkline-missing {
  fill: var(--ink-faint);
  font-size: var(--t-nano);
  letter-spacing: 0.03em;
}

.metrics-ribbon {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.metric-pill {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.25rem 0.5rem;
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  border-radius: var(--r-xs);
}

.pill-label {
  font-size: var(--t-nano);
  color: var(--ink-dim);
  letter-spacing: 0.04em;
}

.pill-val {
  font-size: var(--t-micro);
}

.pill-sub {
  font-size: var(--t-nano);
}

.regime-badge {
  padding: 0.1rem 0.35rem;
  border-radius: var(--r-xs);
  font-size: var(--t-nano);
}

.regime-bullish {
  background: var(--call-wash);
  color: var(--call-hi);
  border: 1px solid var(--call-dim);
}

.regime-bearish {
  background: var(--put-wash);
  color: var(--put-hi);
  border: 1px solid var(--put-dim);
}

.regime-warn {
  background: var(--warn-wash);
  color: var(--warn);
  border: 1px solid color-mix(in srgb, var(--warn) 45%, var(--rule));
}

.regime-neutral {
  background: var(--panel);
  color: var(--ink-faint);
  border: 1px solid var(--rule-hi);
}

.timeframe-group {
  display: flex;
  gap: 0.25rem;
}

.tf-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 28px;
  min-width: 28px;
  background: transparent;
  border: 1px solid var(--rule-faint);
  color: var(--ink-dim);
  font-size: var(--t-nano);
  padding: 0.1rem 0.4rem;
  border-radius: var(--r-xs);
  cursor: pointer;
}

.tf-btn.active,
.tf-btn:hover {
  background: var(--phosphor-wash);
  border-color: var(--phosphor-dim);
  color: var(--phosphor);
}

.gamma-levels-strip {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
  padding: 0.2rem 0.4rem;
  border-radius: var(--r-xs);
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-faint);
}

.strip-tag {
  font-size: var(--t-nano);
  color: var(--ink-dim);
  letter-spacing: 0.05em;
  margin-right: 0.2rem;
}

.level-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.15rem 0.4rem;
  border-radius: var(--r-xs);
  font-size: var(--t-micro);
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-raise);
}

.level-chip.chip-call {
  border-color: color-mix(in srgb, var(--call) 45%, var(--rule));
  color: var(--call-hi);
  background: var(--call-wash);
}

.level-chip.chip-put {
  border-color: color-mix(in srgb, var(--put) 45%, var(--rule));
  color: var(--put-hi);
  background: var(--put-wash);
}

.level-chip.chip-flip {
  border-color: color-mix(in srgb, var(--warn) 45%, var(--rule));
  color: var(--warn);
  background: var(--warn-wash);
}

.level-chip.chip-pin {
  border-color: var(--rule-hi);
  color: var(--ink-soft);
  background: var(--panel-raise);
}

.level-chip.chip-em {
  border-color: color-mix(in srgb, var(--phosphor) 40%, var(--rule));
  color: var(--phosphor);
  background: var(--phosphor-wash);
}

.lvl-name {
  font-size: var(--t-nano);
  letter-spacing: 0.04em;
  color: var(--ink-dim);
}

.lvl-val {
  font-size: var(--t-micro);
}

.lvl-dist {
  font-size: var(--t-nano);
  opacity: 0.85;
  margin-left: 0.15rem;
}
</style>
