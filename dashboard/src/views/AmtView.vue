<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  api,
  type AmtAnalysisResult,
  type AmtAnalyzeFailure,
  type AmtAnalyzeSuccess,
  type AmtHealthPayload,
  type AmtTimeframeOption,
} from '@/api'
import { useResource } from '@/composables/useResource'
import { useChartSize } from '@/composables/useChartSize'
import { linearScale, niceTicks, candlePath, type CandleBar } from '@/charts'
import { num, signed, tone, pctFrac, DASH } from '@/format'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'

/**
 * Auction Market Theory (AMT) workspace — one question, answered at a
 * glance: is this market in balance (fade the edges) or out of balance
 * (do not fade)? Backed by GET /api/amt/analyze, /health, /playbook
 * (research/amt_engine.py). Every nullable backend field renders as DASH
 * with, where the engine supplies one, the reason it could not be derived —
 * never a plausible-looking substitute.
 */

const symbolInput = ref('SPY')
const timeframeInput = ref('')
const lookbackInput = ref(250)

const health = useResource<AmtHealthPayload>(() => api.amtHealth(symbolInput.value))
const analysis = useResource<AmtAnalysisResult>(() =>
  api.amtAnalyze(symbolInput.value, timeframeInput.value || undefined, lookbackInput.value),
)

const timeframeOptions = computed<AmtTimeframeOption[]>(() => health.data.value?.timeframes ?? [])
const capabilityKnown = computed(() => timeframeOptions.value.length > 0)

const result = computed<AmtAnalysisResult | null>(() => analysis.data.value)
const failure = computed<AmtAnalyzeFailure | null>(() => {
  const r = result.value
  return r && r.available === false ? r : null
})
const ok = computed<AmtAnalyzeSuccess | null>(() => {
  const r = result.value
  return r && r.available === true ? r : null
})

function runAnalysis(): void {
  symbolInput.value = symbolInput.value.trim().toUpperCase()
  void health.refresh({ clear: true })
  void analysis.refresh({ clear: true })
}

watch([timeframeInput, lookbackInput], () => {
  void analysis.refresh({ clear: true })
})

/* ------------------------------------------------------------------ formatting */

function fmtRiskReward(rr: number | null): string {
  if (rr == null) return DASH
  return `1 : ${rr.toFixed(2)}`
}

const ZONE_LABELS: Record<string, string> = {
  ABOVE_VALUE: 'Above value',
  VAH_EDGE: 'At value-area high',
  INSIDE_UPPER: 'Inside value (upper)',
  POC: 'At point of control',
  INSIDE_LOWER: 'Inside value (lower)',
  VAL_EDGE: 'At value-area low',
  BELOW_VALUE: 'Below value',
}
function humaniseZone(z: string): string {
  return ZONE_LABELS[z] ?? z
}

/** Kept short: these render in a narrow Readout tile already labelled "Acceptance". */
function humaniseAcceptance(a: string): string {
  if (a === 'above') return 'Above value'
  if (a === 'below') return 'Below value'
  if (a === 'none') return 'None'
  return a
}

function humaniseFailedAuction(f: string): string {
  if (f === 'look_above_fail') return 'Failed auction: look above, fail (short setup)'
  if (f === 'look_below_fail') return 'Failed auction: look below, fail (long setup)'
  return f
}

const SHAPE_LABELS: Record<string, string> = {
  p: 'P-shape (value high in range)',
  b: 'b-shape (value low in range)',
  d: 'D-shape (normal, balanced distribution)',
  double_distribution: 'Double distribution (two balance areas)',
}
function humaniseShape(s: string): string {
  return SHAPE_LABELS[s] ?? s
}

function regimeToneClass(label: string): string {
  if (label === 'BALANCE') return 'tone-balance'
  if (label === 'IMBALANCE') return 'tone-imbalance'
  if (label === 'TRANSITION') return 'tone-transition'
  return 'tone-neutral'
}

function biasToneClass(bias: string): string {
  if (bias === 'LONG') return 'tone-long'
  if (bias === 'SHORT') return 'tone-short'
  return 'tone-neutral'
}

function evidenceToneClass(direction: string): string {
  if (direction === 'bullish') return 'tone-long'
  if (direction === 'bearish') return 'tone-short'
  if (direction === 'balance') return 'tone-balance'
  if (direction === 'imbalance') return 'tone-imbalance'
  return 'tone-neutral'
}

/* ------------------------------------------------------------------ regime components */

type RegimeComponentKey = 'va_overlap' | 'containment' | 'chop_index' | 'efficiency' | 'rotation'
const COMPONENT_LABELS: Record<RegimeComponentKey, string> = {
  va_overlap: 'Value-area overlap',
  containment: 'Containment',
  chop_index: 'Chop index',
  efficiency: 'Efficiency',
  rotation: 'Rotation',
}
interface RegimeComponentRow {
  key: RegimeComponentKey
  label: string
  value: number | null
  weight: number
}
const regimeComponentRows = computed<RegimeComponentRow[]>(() => {
  const r = ok.value?.regime
  if (!r) return []
  const keys: RegimeComponentKey[] = [
    'va_overlap',
    'containment',
    'chop_index',
    'efficiency',
    'rotation',
  ]
  return keys.map((k) => ({
    key: k,
    label: COMPONENT_LABELS[k],
    value: r.components[k],
    weight: r.weights[k],
  }))
})

/* ------------------------------------------------------------------ profile + candle chart */

const hostRef = ref<HTMLDivElement | null>(null)
const { W, H } = useChartSize(hostRef, { minW: 320, minH: 320, fallbackW: 760, fallbackH: 420 })

const pad = { l: 48, r: 58, t: 14, b: 22 }
const gapW = 14

const innerW = computed(() => Math.max(0, W.value - pad.l - pad.r))
const candleW = computed(() => innerW.value * 0.4)
const profileW = computed(() => Math.max(0, innerW.value - candleW.value - gapW))
const candleX0 = computed(() => pad.l)
const profileX0 = computed(() => pad.l + candleW.value + gapW)
const chartRight = computed(() => profileX0.value + profileW.value)

/**
 * The candles must cover the same bars the profile was built from. The response
 * carries the full lookback in `bars` but the composite profile is built only on
 * the current balance window, so plotting all of them puts the histogram in the
 * top sliver of a chart scaled to a year of price and stacks POC/VAH/VAL on one
 * pixel row. Slice to the window; `context_profile` still reports the wider range.
 */
const barsRaw = computed(() => {
  const all = ok.value?.bars ?? []
  const start = ok.value?.balance_window?.bar_index_start
  if (start == null || start <= 0 || start >= all.length) return all
  return all.slice(start)
})

const priceDomain = computed<[number, number]>(() => {
  const c = ok.value?.composite
  const lows: number[] = []
  const highs: number[] = []
  if (c?.low != null) lows.push(c.low)
  if (c?.high != null) highs.push(c.high)
  for (const b of barsRaw.value) {
    if (b.low != null) lows.push(b.low)
    if (b.high != null) highs.push(b.high)
  }
  if (!lows.length || !highs.length) return [0, 1]
  const lo = Math.min(...lows)
  const hi = Math.max(...highs)
  const padAmt = (hi - lo) * 0.04 || 1
  return [lo - padAmt, hi + padAmt]
})

const yScale = computed(() => linearScale(priceDomain.value, [H.value - pad.b, pad.t]))
const priceTicks = computed(() => niceTicks(priceDomain.value[0], priceDomain.value[1], 5))

const candleGeom = computed(() => {
  const bars = barsRaw.value
  if (!bars.length) return { up: '', down: '', wicks: '' }
  const n = bars.length
  const xScale = linearScale(
    [0, Math.max(n - 1, 0)],
    [candleX0.value + 4, candleX0.value + candleW.value - 4],
  )
  const halfWidth = Math.max(0.6, Math.min(5, (candleW.value / Math.max(n, 1)) * 0.35))
  const pts: CandleBar[] = []
  bars.forEach((b, i) => {
    if (b.open == null || b.high == null || b.low == null || b.close == null) return
    pts.push({
      x: xScale(i),
      o: yScale.value(b.open),
      h: yScale.value(b.high),
      l: yScale.value(b.low),
      c: yScale.value(b.close),
    })
  })
  return candlePath(pts, halfWidth)
})

const lastBarClose = computed<number | null>(() => {
  const bars = barsRaw.value
  for (let i = bars.length - 1; i >= 0; i--) {
    const c = bars[i]?.close
    if (c != null) return c
  }
  return null
})
const lastCloseY = computed(() =>
  lastBarClose.value != null ? yScale.value(lastBarClose.value) : null,
)

interface ProfileRow {
  y0: number
  y1: number
  barW: number
  inValue: boolean
  isPoc: boolean
}
const profileBins = computed(() => ok.value?.composite.bins ?? [])
const maxBinVolume = computed(() => Math.max(1, ...profileBins.value.map((b) => b.volume ?? 0)))
const volScale = computed(() =>
  linearScale([0, maxBinVolume.value], [profileX0.value, profileX0.value + profileW.value]),
)
const profileRows = computed<ProfileRow[]>(() =>
  profileBins.value
    .filter((b) => b.lo != null && b.hi != null)
    .map((b) => {
      const y0 = yScale.value(b.hi as number)
      const y1 = yScale.value(b.lo as number)
      const w = b.volume != null ? volScale.value(b.volume) - profileX0.value : 0
      return { y0, y1, barW: Math.max(0, w), inValue: b.in_value, isPoc: b.is_poc }
    }),
)
</script>

<template>
  <div class="amt">
    <div class="controls">
      <input
        v-model="symbolInput"
        class="symbol-input"
        maxlength="10"
        autocomplete="off"
        spellcheck="false"
        placeholder="SYMBOL"
        aria-label="Symbol"
        @keydown.enter="runAnalysis"
      />
      <select
        v-model="timeframeInput"
        class="tf-select label"
        aria-label="Timeframe"
        :disabled="!capabilityKnown"
      >
        <option value="">AUTO (SERVER DEFAULT)</option>
        <option
          v-for="tf in timeframeOptions"
          :key="tf.value"
          :value="tf.value"
          :disabled="!tf.available"
        >
          {{ tf.label }}{{ !tf.available ? ` — ${tf.reason ?? 'unavailable'}` : '' }}
        </option>
      </select>
      <select v-model.number="lookbackInput" class="lb-select label" aria-label="Lookback bars">
        <option :value="120">120 BARS</option>
        <option :value="250">250 BARS</option>
        <option :value="500">500 BARS</option>
      </select>
      <button type="button" class="run-btn label" @click="runAnalysis">
        {{ analysis.loading.value ? 'RUNNING…' : 'RUN' }}
      </button>
      <span v-if="!capabilityKnown" class="cap-warn label">
        Timeframe capability report unavailable
      </span>
    </div>

    <p v-if="analysis.error.value" class="err">{{ analysis.error.value }}</p>

    <template v-else-if="failure">
      <Panel label="Auction Market Theory" index="08" class="w-full">
        <p class="fail-reason">{{ failure.reason }}</p>
      </Panel>
    </template>

    <template v-else-if="ok">
      <div v-if="ok.bars_meta.downgraded" class="downgrade-banner">
        <span class="downgrade-label label">TIMEFRAME DOWNGRADED</span>
        <span>{{ ok.bars_meta.downgrade_reason ?? DASH }}</span>
      </div>

      <!-- A. Regime verdict -->
      <Panel :label="`${ok.symbol} · ${ok.timeframe}`" index="01" meta="Regime verdict" live>
        <div class="verdict-row">
          <div class="verdict-headline" :class="regimeToneClass(ok.regime.label)">
            <span class="verdict-label">{{ ok.regime.label }}</span>
            <span class="verdict-score fig">{{ num(ok.regime.score, 2) }}</span>
          </div>
          <p class="narrative">{{ ok.narrative }}</p>
        </div>
        <div class="components">
          <div v-for="row in regimeComponentRows" :key="row.key" class="comp-row">
            <span class="comp-label label">
              {{ row.label }}
              <span class="comp-weight">w={{ row.weight.toFixed(2) }}</span>
            </span>
            <div v-if="row.value != null" class="comp-bar-track">
              <div
                class="comp-bar-fill"
                :style="{ width: `${Math.max(0, Math.min(100, row.value * 100))}%` }"
              />
            </div>
            <span v-else class="comp-dash">
              {{ DASH }}
              <span class="comp-note">not derivable</span>
            </span>
            <span v-if="row.value != null" class="comp-value fig">{{ row.value.toFixed(2) }}</span>
          </div>
        </div>
      </Panel>

      <!-- B. Profile chart -->
      <Panel
        label="Price & volume profile"
        index="02"
        :meta="`balance window · ${barsRaw.length} of ${ok.bars.length} bars`"
        flush
      >
        <div ref="hostRef" class="chart-host">
          <svg
            :width="W"
            :height="H"
            :viewBox="`0 0 ${W} ${H}`"
            preserveAspectRatio="none"
            role="img"
            aria-label="Candlestick price series and volume profile sharing one price axis."
          >
            <rect
              v-if="ok.composite.vah != null && ok.composite.val != null"
              :x="candleX0"
              :y="Math.min(yScale(ok.composite.vah), yScale(ok.composite.val))"
              :width="chartRight - candleX0"
              :height="Math.abs(yScale(ok.composite.val) - yScale(ok.composite.vah))"
              class="va-band"
            />

            <g v-for="t in priceTicks" :key="`pt-${t}`">
              <line
                :x1="candleX0"
                :x2="chartRight"
                :y1="yScale(t)"
                :y2="yScale(t)"
                class="grid-line"
              />
              <text :x="2" :y="yScale(t) + 3" class="axis-label fig">{{ num(t, 2) }}</text>
            </g>

            <path :d="candleGeom.up" class="candle-up" />
            <path :d="candleGeom.down" class="candle-down" />
            <path :d="candleGeom.wicks" class="candle-wick" />

            <g v-for="(row, i) in profileRows" :key="`pb-${i}`">
              <rect
                :x="profileX0"
                :y="row.y0"
                :width="row.barW"
                :height="Math.max(1, row.y1 - row.y0)"
                :class="['profile-bar', { 'is-value': row.inValue, 'is-poc': row.isPoc }]"
              />
            </g>

            <g v-if="ok.composite.poc != null">
              <line
                :x1="candleX0"
                :x2="chartRight"
                :y1="yScale(ok.composite.poc)"
                :y2="yScale(ok.composite.poc)"
                class="ref-line poc-line"
              />
              <text :x="chartRight + 4" :y="yScale(ok.composite.poc) + 3" class="ref-label poc-label">
                POC {{ num(ok.composite.poc, 2) }}
              </text>
            </g>
            <g v-if="ok.composite.vah != null">
              <line
                :x1="candleX0"
                :x2="chartRight"
                :y1="yScale(ok.composite.vah)"
                :y2="yScale(ok.composite.vah)"
                class="ref-line vah-line"
              />
              <text :x="chartRight + 4" :y="yScale(ok.composite.vah) + 3" class="ref-label vah-label">
                VAH {{ num(ok.composite.vah, 2) }}
              </text>
            </g>
            <g v-if="ok.composite.val != null">
              <line
                :x1="candleX0"
                :x2="chartRight"
                :y1="yScale(ok.composite.val)"
                :y2="yScale(ok.composite.val)"
                class="ref-line val-line"
              />
              <text :x="chartRight + 4" :y="yScale(ok.composite.val) + 3" class="ref-label val-label">
                VAL {{ num(ok.composite.val, 2) }}
              </text>
            </g>

            <g v-if="lastCloseY != null">
              <line
                :x1="candleX0"
                :x2="chartRight"
                :y1="lastCloseY"
                :y2="lastCloseY"
                class="close-line"
              />
              <text :x="chartRight + 4" :y="lastCloseY - 4" class="ref-label close-label">
                LAST {{ num(lastBarClose, 2) }}
              </text>
            </g>
          </svg>
        </div>
      </Panel>

      <!-- C. Location & acceptance -->
      <Panel label="Location & acceptance" index="03" class="w-full">
        <div class="readouts">
          <Readout label="Zone" :value="humaniseZone(ok.location.zone)" tone="accent" />
          <Readout label="Close" :value="num(ok.location.close, 2)" />
          <Readout
            label="Dist to POC (ATR)"
            :value="signed(ok.location.dist_to_poc_atr, 2)"
            :tone="tone(ok.location.dist_to_poc_atr)"
          />
          <Readout
            label="Dist to VAH (ATR)"
            :value="signed(ok.location.dist_to_vah_atr, 2)"
            :tone="tone(ok.location.dist_to_vah_atr)"
          />
          <Readout
            label="Dist to VAL (ATR)"
            :value="signed(ok.location.dist_to_val_atr, 2)"
            :tone="tone(ok.location.dist_to_val_atr)"
          />
          <Readout label="Acceptance" :value="humaniseAcceptance(ok.location.acceptance)" />
        </div>
        <div v-if="ok.location.failed_auction !== 'none'" class="failed-auction">
          <span class="label">Failed auction</span>
          <span>{{ humaniseFailedAuction(ok.location.failed_auction) }}</span>
          <span v-if="ok.location.failed_auction_extreme != null" class="fig">
            extreme {{ num(ok.location.failed_auction_extreme, 2) }}
          </span>
        </div>
      </Panel>

      <!-- D. Trade plan -->
      <Panel label="Trade plan" index="04" class="w-full">
        <div class="plan-head">
          <span class="plan-bias" :class="biasToneClass(ok.trade_plan.bias)">
            {{ ok.trade_plan.bias }}
          </span>
          <span class="plan-setup">{{ ok.trade_plan.setup }}</span>
        </div>
        <div class="readouts">
          <Readout label="Entry" :value="num(ok.trade_plan.entry, 2)" />
          <Readout label="Stop" :value="num(ok.trade_plan.stop, 2)" />
          <Readout label="Target 1" :value="num(ok.trade_plan.target_1, 2)" />
          <Readout label="Target 2" :value="num(ok.trade_plan.target_2, 2)" />
          <Readout label="Risk / unit" :value="num(ok.trade_plan.risk_per_unit, 2)" />
          <Readout label="Risk:Reward" :value="fmtRiskReward(ok.trade_plan.risk_reward)" />
        </div>
        <p v-if="ok.trade_plan.risk_reward == null" class="rr-reason">
          {{ ok.trade_plan.risk_reward_unavailable_reason ?? 'Risk:reward not derivable.' }}
        </p>
        <p class="invalidation"><span class="label">Invalidation</span> {{ ok.trade_plan.invalidation }}</p>
        <ul v-if="ok.trade_plan.rules_applied.length" class="rules-applied">
          <li v-for="(r, i) in ok.trade_plan.rules_applied" :key="i">{{ r }}</li>
        </ul>
      </Panel>

      <!-- E. Evidence ledger -->
      <Panel label="Evidence ledger" index="05" :meta="`${ok.evidence.length} signals`" flush>
        <table v-if="ok.evidence.length" class="grid">
          <thead>
            <tr>
              <th class="label">Signal</th>
              <th class="label">Direction</th>
              <th class="label num">Weight</th>
              <th class="label">Detail</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(ev, i) in ok.evidence" :key="i">
              <td class="fig">{{ ev.signal }}</td>
              <td :class="evidenceToneClass(ev.direction)">{{ ev.direction }}</td>
              <td class="fig num">{{ num(ev.weight, 2) }}</td>
              <td class="dim">{{ ev.detail }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">No evidence lines in this response.</p>
        <div class="lean">
          <span class="label">Directional lean</span>
          <span :class="evidenceToneClass(ok.directional_lean.label)">
            {{ ok.directional_lean.label }}
          </span>
          <span class="fig">bull {{ num(ok.directional_lean.bullish_weight, 2) }}</span>
          <span class="fig">bear {{ num(ok.directional_lean.bearish_weight, 2) }}</span>
        </div>
      </Panel>

      <!-- F. Rotation statistics -->
      <Panel
        label="Rotation statistics"
        index="06"
        :meta="`measured over ${ok.rotation_stats.sessions} sessions of ${ok.symbol}`"
        class="w-full"
      >
        <div class="readouts">
          <Readout label="VAL attempts" :value="String(ok.rotation_stats.val_attempts)" />
          <Readout label="VAL rotations" :value="String(ok.rotation_stats.val_rotations)" />
          <Readout
            label="VAL rotation rate"
            :value="ok.rotation_stats.val_rotation_rate == null ? DASH : pctFrac(ok.rotation_stats.val_rotation_rate)"
          />
          <Readout label="VAH attempts" :value="String(ok.rotation_stats.vah_attempts)" />
          <Readout label="VAH rotations" :value="String(ok.rotation_stats.vah_rotations)" />
          <Readout
            label="VAH rotation rate"
            :value="ok.rotation_stats.vah_rotation_rate == null ? DASH : pctFrac(ok.rotation_stats.vah_rotation_rate)"
          />
        </div>
        <p class="note">{{ ok.rotation_stats.note }}</p>
      </Panel>

      <!-- G. Structure flags -->
      <Panel label="Structure" index="07" class="w-full">
        <div class="flags">
          <span class="flag-chip shape-chip">{{ humaniseShape(ok.composite.shape) }}</span>
          <span v-if="ok.composite.poor_high" class="flag-chip warn-chip">Poor high</span>
          <span v-if="ok.composite.poor_low" class="flag-chip warn-chip">Poor low</span>
          <span v-if="ok.composite.excess_high" class="flag-chip">Excess high</span>
          <span v-if="ok.composite.excess_low" class="flag-chip">Excess low</span>
          <span class="flag-chip">HVN ×{{ ok.composite.hvn.length }}</span>
          <span class="flag-chip">LVN ×{{ ok.composite.lvn.length }}</span>
        </div>
      </Panel>

      <!-- H. Playbook -->
      <Panel label="Playbook" index="08" class="w-full" flush>
        <details class="playbook-details">
          <summary class="label">Playbook ({{ ok.playbook.length }} rules)</summary>
          <ul class="playbook-list">
            <li v-for="(p, i) in ok.playbook" :key="i">
              <strong>{{ p.rule }}</strong>
              <span>{{ p.detail }}</span>
            </li>
          </ul>
        </details>
      </Panel>
    </template>
  </div>
</template>

<style scoped>
.amt {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}
.w-full {
  width: 100%;
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

.tf-select,
.lb-select {
  height: 28px;
  max-width: 260px;
  padding: 0 var(--s2);
  color: var(--ink);
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.run-btn {
  height: 28px;
  padding: 0 var(--s3);
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.cap-warn {
  color: var(--warn);
}

.err {
  font-size: var(--t-small);
  color: var(--short);
}

.fail-reason {
  font-size: var(--t-body);
  color: var(--ink-soft);
}

.downgrade-banner {
  display: flex;
  align-items: baseline;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--warn);
  background: var(--warn-wash);
  color: var(--ink-soft);
  font-size: var(--t-small);
}
.downgrade-label {
  color: var(--warn);
}

.verdict-row {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
  margin-bottom: var(--s3);
}
.verdict-headline {
  display: flex;
  align-items: baseline;
  gap: var(--s3);
}
.verdict-label {
  font-family: var(--font-display);
  font-size: var(--t-fig-lg);
  font-weight: 700;
  letter-spacing: -0.02em;
}
.verdict-score {
  font-size: var(--t-fig);
  color: var(--ink-dim);
}
.narrative {
  font-size: var(--t-small);
  color: var(--ink-soft);
  max-width: 72ch;
}

.tone-balance {
  color: var(--phosphor);
}
.tone-imbalance {
  color: var(--warn);
}
.tone-transition {
  color: var(--ink-soft);
}
.tone-neutral {
  color: var(--ink-dim);
}
.tone-long {
  color: var(--long);
}
.tone-short {
  color: var(--short);
}

.components {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}
.comp-row {
  display: grid;
  grid-template-columns: 13rem 1fr 3rem;
  align-items: center;
  gap: var(--s2);
}
.comp-label {
  display: flex;
  gap: var(--s1);
}
.comp-weight {
  color: var(--ink-faint);
}
.comp-bar-track {
  height: 6px;
  background: var(--panel-raise);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.comp-bar-fill {
  height: 100%;
  background: var(--phosphor);
}
.comp-value {
  text-align: right;
  color: var(--ink-soft);
}
.comp-dash {
  color: var(--ink-faint);
}
.comp-note {
  margin-left: var(--s1);
  font-size: var(--t-micro);
  color: var(--ink-faint);
}

.chart-host {
  width: 100%;
  min-height: 320px;
  overflow: hidden;
}
.grid-line {
  stroke: var(--rule-faint);
  stroke-width: 1;
}
.axis-label {
  fill: var(--ink-faint);
  font-size: var(--t-micro);
}
.va-band {
  fill: var(--phosphor-wash);
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
.profile-bar {
  fill: var(--panel-raise);
}
.profile-bar.is-value {
  fill: var(--phosphor-dim);
}
.profile-bar.is-poc {
  fill: var(--phosphor);
}
.ref-line {
  stroke-width: 1;
  stroke-dasharray: 4 3;
}
.poc-line {
  stroke: var(--phosphor);
}
.vah-line,
.val-line {
  stroke: var(--ink-ghost);
}
.close-line {
  stroke: var(--ink-soft);
  stroke-dasharray: none;
  stroke-width: 1.25;
}
.ref-label {
  font-size: var(--t-micro);
  letter-spacing: 0.03em;
}
.poc-label {
  fill: var(--phosphor);
}
.vah-label,
.val-label {
  fill: var(--ink-faint);
}
.close-label {
  fill: var(--ink-soft);
}

.readouts {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr));
  gap: var(--s3);
}

.failed-auction {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--s2);
  margin-top: var(--s3);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--warn);
  background: var(--warn-wash);
  color: var(--ink-soft);
  font-size: var(--t-small);
}

.plan-head {
  display: flex;
  align-items: baseline;
  gap: var(--s3);
  margin-bottom: var(--s3);
}
.plan-bias {
  font-family: var(--font-display);
  font-size: var(--t-display);
  font-weight: 700;
  letter-spacing: 0.02em;
}
.plan-setup {
  font-size: var(--t-small);
  color: var(--ink-soft);
}
.rr-reason {
  margin-top: var(--s2);
  font-size: var(--t-small);
  color: var(--warn);
}
.invalidation {
  margin-top: var(--s3);
  font-size: var(--t-small);
  color: var(--ink-soft);
  max-width: 72ch;
}
.rules-applied {
  margin-top: var(--s2);
  padding-left: var(--s4);
  font-size: var(--t-small);
  color: var(--ink-dim);
}

.dim {
  color: var(--ink-faint);
}

.lean {
  display: flex;
  align-items: baseline;
  gap: var(--s3);
  margin-top: var(--s3);
  padding: var(--s2) var(--s3);
  font-size: var(--t-small);
}

.note {
  font-size: var(--t-small);
  color: var(--ink-dim);
}
.pad {
  padding: var(--s3) var(--s4);
}

.flags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
}
.flag-chip {
  padding: 2px 8px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-capsule);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.04em;
  color: var(--ink-soft);
}
.shape-chip {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.warn-chip {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}

.playbook-details {
  padding: var(--s3);
}
.playbook-details summary {
  cursor: pointer;
  color: var(--ink-soft);
}
.playbook-list {
  margin-top: var(--s3);
  padding-left: var(--s4);
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  font-size: var(--t-small);
}
.playbook-list li {
  color: var(--ink-soft);
}
.playbook-list strong {
  display: block;
  color: var(--ink);
}

@media (max-width: 960px) {
  .comp-row {
    grid-template-columns: 1fr;
  }
  .readouts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
