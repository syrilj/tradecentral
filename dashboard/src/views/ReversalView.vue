<script setup lang="ts">
/**
 * Reversal timing — when does a leg turn, and does the chart stack know first?
 *
 * The operator's read: volume-profile control (POC / value area), the swing
 * anchored VWAP, the standardized MACD-HA and the higher timeframe. This tab
 * draws that stack for one symbol, and puts next to every signal and trigger
 * the number it earned *out of sample* in research/reversal_study.py.
 *
 * What this is NOT: a probability of a turn unless the model passed its
 * out-of-sample gate. When it did not, the tab says so and shows none.
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type MeasuredEdge,
  type ReversalBar,
  type ReversalPayload,
  type ReversalScanPayload,
  type ReversalScanRow,
  type ReversalSideRead,
  type ReversalTf,
} from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import { useChartSize } from '@/composables/useChartSize'
import { linearScale, niceTicks } from '@/charts'
import { DASH, num, optNum, optSigned, shortDate } from '@/format'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import LoadingState from '@/components/LoadingState.vue'
import HelpTip from '@/components/HelpTip.vue'

const route = useRoute()
const router = useRouter()

function cleanTicker(term: string): string {
  return term
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
    .slice(0, 10)
}

const symbol = ref(typeof route.query.symbol === 'string' && route.query.symbol ? cleanTicker(route.query.symbol) : 'SPY')
const symbolInput = ref(symbol.value)
const tf = ref<ReversalTf>(route.query.tf === '1h' ? '1h' : '1d')

const res = useResource<ReversalPayload>(() => api.reversal(symbol.value, { tf: tf.value }), { intervalMs: 120_000 })
const scanRunning = ref(false)
const scan: Resource<ReversalScanPayload> = useResource<ReversalScanPayload>(
  () =>
    api.reversalScan({ tf: tf.value }).then((p) => {
      scanRunning.value = p.status === 'running'
      return p
    }),
  { intervalMs: (): number => (scanRunning.value ? 4_000 : 300_000) },
)

function loadSymbol(term: string) {
  const s = cleanTicker(term)
  if (!s) return
  symbol.value = s
  symbolInput.value = s
}

watch([symbol, tf], () => {
  router.replace({ query: { ...route.query, symbol: symbol.value, tf: tf.value } })
  res.refresh({ clear: true })
})
watch(tf, () => scan.refresh({ clear: true }))

const d = computed(() => res.data.value)
const ok = computed(() => Boolean(d.value?.measurable && d.value.chart?.length))
const bars = computed<ReversalBar[]>(() => d.value?.chart ?? [])

/* ---- which side matters right now ---- */
const focusSide = ref<'bottom' | 'top'>('bottom')
watch(
  () => d.value?.setup,
  (s) => {
    if (s === 'bottom' || s === 'top') focusSide.value = s
  },
  { immediate: true },
)
const read = computed<ReversalSideRead | null>(() => d.value?.reads?.[focusSide.value] ?? null)
const tfLabel = computed(() => (tf.value === '1h' ? '1h bars · daily HTF' : 'daily bars · weekly HTF'))
const barUnit = computed(() => (tf.value === '1h' ? 'bars (1h)' : 'sessions'))

const setupHeadline = computed(() => {
  const s = d.value?.setup
  if (s === 'bottom') return { text: 'BOTTOM WATCH', sub: 'down-leg ≥ 3 ATR, structure still down — call side', tone: 'call' as const }
  if (s === 'top') return { text: 'TOP WATCH', sub: 'up-leg ≥ 3 ATR, structure still up — put side', tone: 'put' as const }
  return { text: 'NO QUALIFYING LEG', sub: 'price is not 3+ ATR into a swing leg; the study has no read here', tone: 'flat' as const }
})

const firedWithEdge = computed(() => (read.value?.triggers ?? []).filter((t) => t.fired && t.measured_edge === 'helps'))
const firedAny = computed(() => (read.value?.triggers ?? []).filter((t) => t.fired))

const verdict = computed(() => {
  const r = read.value
  if (!r || !d.value) return ''
  if (!d.value.study?.available) return 'No study artifact for this timeframe — signals are drawn but nothing is measured.'
  const side = focusSide.value === 'bottom' ? 'calls' : 'puts'
  if (!r.candidate) return `Not in a ${focusSide.value === 'bottom' ? 'down' : 'up'}-leg, so no ${side} read. Showing what the study measured for reference.`
  const rk = r.rank
  if (rk?.tier && rk.tier_edge === 'helps') {
    return `Model ranks this bar in its ${tierLabel(rk.tier)} of ${focusSide.value} setups. Out of sample that tier hit the 2:1 target ${pp(rk.tier_rate)} of the time vs ${pp(rk.base_rate_test)} for all leg bars — the strongest measured read for adding ${side}. Stop goes under the leg extreme.`
  }
  if (rk && !rk.tier) {
    return `Model ranks this bar below its top 20% of ${focusSide.value} setups — no measured reason to add ${side} yet.`
  }
  if (firedWithEdge.value.length) {
    const names = firedWithEdge.value.map((t) => t.label.toLowerCase()).join('; ')
    return `Trigger with a measured edge over the no-signal baseline just fired: ${names}. That is the study's evidence for adding ${side}, sized to the stop under the leg extreme.`
  }
  if (firedAny.value.length) {
    return `${firedAny.value.length} trigger(s) fired, but none beat the no-signal baseline out of sample. On this evidence they do not justify ${side} on their own.`
  }
  return `In a qualifying leg, no trigger in the last 10 bars. Waiting is the measured default.`
})

/* ---- chart geometry ---- */
const host = ref<HTMLElement | null>(null)
const { W } = useChartSize(host, { minW: 360, minH: 520, fallbackW: 900 })
const H_PRICE = 300
const H_VOL = 60
const H_MACD = 150
const GAP = 14
const PAD_L = 8
const PAD_R = 62
const TOTAL_H = H_PRICE + GAP + H_VOL + GAP + H_MACD + 18

const priceDomain = computed<[number, number]>(() => {
  const vals: number[] = []
  for (const b of bars.value) {
    for (const v of [b.h, b.l, b.svwap, b.poc]) if (v != null) vals.push(v)
  }
  if (!vals.length) return [0, 1]
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const pad = (hi - lo) * 0.04 || 1
  return [lo - pad, hi + pad]
})
const x = computed(() => {
  const n = Math.max(bars.value.length, 1)
  const step = (W.value - PAD_L - PAD_R) / n
  return { step, at: (i: number) => PAD_L + step * (i + 0.5) }
})
const yP = computed(() => linearScale(priceDomain.value, [H_PRICE - 6, 6]))
const priceTicks = computed(() => niceTicks(priceDomain.value[0], priceDomain.value[1], 6))

const candleW = computed(() => Math.max(1, Math.min(9, x.value.step * 0.62)))

function stepLine(key: 'svwap' | 'poc' | 'val' | 'vah', filter?: (b: ReversalBar) => boolean): string {
  let path = ''
  let open = false
  bars.value.forEach((b, i) => {
    const v = b[key]
    if (v == null || (filter && !filter(b))) {
      open = false
      return
    }
    const px = x.value.at(i)
    const py = yP.value(v)
    path += open ? ` L${px.toFixed(1)},${py.toFixed(1)}` : ` M${px.toFixed(1)},${py.toFixed(1)}`
    open = true
  })
  return path.trim()
}
/* the swing VWAP re-anchors on a flip, so each direction is its own run */
const vwapUp = computed(() => stepLine('svwap', (b) => b.dir > 0))
const vwapDn = computed(() => stepLine('svwap', (b) => b.dir < 0))
const pocPath = computed(() => stepLine('poc'))
const valPath = computed(() => stepLine('val'))
const vahPath = computed(() => stepLine('vah'))

const yV = computed(() => {
  const maxV = Math.max(1, ...bars.value.map((b) => b.v ?? 0))
  return (v: number) => H_PRICE + GAP + H_VOL - (v / maxV) * H_VOL
})
const volTop = H_PRICE + GAP

const macdTop = H_PRICE + GAP + H_VOL + GAP
const macdDomain = computed<[number, number]>(() => {
  const vals = bars.value.flatMap((b) => [b.m_h, b.m_l]).filter((v): v is number => v != null)
  const lo = Math.min(-160, ...vals)
  const hi = Math.max(160, ...vals)
  return [lo, hi]
})
const yM = computed(() => linearScale(macdDomain.value, [macdTop + H_MACD - 4, macdTop + 4]))
const macdSignalPath = computed(() => {
  let p = ''
  bars.value.forEach((b, i) => {
    if (b.m_sig == null) return
    p += `${p ? ' L' : 'M'}${x.value.at(i).toFixed(1)},${yM.value(b.m_sig).toFixed(1)}`
  })
  return p
})

const dateTicks = computed(() => {
  const n = bars.value.length
  if (!n) return []
  const every = Math.max(1, Math.round(n / 6))
  const out: { i: number; label: string }[] = []
  for (let i = 0; i < n; i += every) {
    const t = bars.value[i].t
    out.push({ i, label: tf.value === '1h' ? `${t.slice(5, 10)} ${t.slice(11, 16)}` : shortDate(t.slice(0, 10)) })
  }
  return out
})

const hover = ref<number | null>(null)
function onMove(ev: MouseEvent) {
  const el = ev.currentTarget as SVGElement
  const box = el.getBoundingClientRect()
  const px = ((ev.clientX - box.left) / box.width) * W.value
  const i = Math.floor((px - PAD_L) / x.value.step)
  hover.value = i >= 0 && i < bars.value.length ? i : null
}
const hoverBar = computed(() => (hover.value != null ? bars.value[hover.value] : null))

/* ---- formatting ---- */
function tierLabel(t: string | null | undefined): string {
  if (!t) return '< top 20%'
  const m = /top_(\d+)pct/.exec(t)
  return m ? `top ${m[1]}%` : t
}
const rankTiers = computed(() =>
  Object.entries(read.value?.rank?.tiers ?? {}).sort((a, b) => Number(/\d+/.exec(a[0])?.[0]) - Number(/\d+/.exec(b[0])?.[0])),
)
function edgeLabel(e: MeasuredEdge | 'below_top_tiers'): string {
  if (e === 'below_top_tiers') return 'below tiers'
  return e === 'helps' ? 'edge' : e === 'hurts' ? 'worse' : e === 'no_edge' ? 'no edge' : 'unmeasured'
}
function pp(v: number | null | undefined, dp = 1): string {
  return v == null ? DASH : `${(v * 100).toFixed(dp)}%`
}
function spp(v: number | null | undefined, dp = 1): string {
  return v == null ? DASH : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(dp)}pp`
}
function r(v: number | null | undefined): string {
  return v == null ? DASH : `${v >= 0 ? '+' : ''}${v.toFixed(2)}R`
}
const lag = computed(() => read.value?.lag ?? null)
const studyMeta = computed(() => d.value?.study ?? scan.data.value?.study ?? null)

const scanRows = computed<ReversalScanRow[]>(() =>
  (scan.data.value?.rows ?? []).filter((row: ReversalScanRow) => row.setup === focusSide.value),
)
</script>

<template>
  <div class="view">
    <Panel label="Reversal Timing" index="R1" :meta="d?.asof ? `as of ${d.asof.slice(0, 16).replace('T', ' ')} · ${tfLabel}` : tfLabel">
      <div class="controls">
        <div class="ctl sym">
          <label class="label" for="rev-sym">Symbol</label>
          <div class="sym-row">
            <input
              id="rev-sym"
              v-model="symbolInput"
              class="fig input"
              type="text"
              spellcheck="false"
              placeholder="TICKER"
              @keyup.enter="loadSymbol(symbolInput)"
            />
            <button type="button" class="btn label" @click="loadSymbol(symbolInput)">Load</button>
          </div>
        </div>
        <div class="ctl">
          <span class="label">Timeframe</span>
          <div class="seg" role="group" aria-label="Timeframe">
            <button type="button" class="label" :class="{ on: tf === '1d' }" @click="tf = '1d'">Daily</button>
            <button type="button" class="label" :class="{ on: tf === '1h' }" @click="tf = '1h'">1 hour</button>
          </div>
        </div>
        <div class="ctl">
          <span class="label">Side</span>
          <div class="seg" role="group" aria-label="Reversal side">
            <button type="button" class="label call-on" :class="{ on: focusSide === 'bottom' }" @click="focusSide = 'bottom'">Bottoms · calls</button>
            <button type="button" class="label put-on" :class="{ on: focusSide === 'top' }" @click="focusSide = 'top'">Tops · puts</button>
          </div>
        </div>
        <button type="button" class="btn label refresh" :disabled="res.loading.value" @click="res.refresh()">Refresh</button>
      </div>

      <LoadingState v-if="res.loading.value && !d" label="Computing the chart stack" />
      <p v-else-if="res.error.value && !d" class="fail">{{ res.error.value }}</p>
      <p v-else-if="d && !d.measurable" class="fail">{{ d.reason || d.error }}</p>

      <template v-else-if="d && ok">
        <div class="headline" :class="setupHeadline.tone">
          <div>
            <div class="setup fig">{{ setupHeadline.text }}</div>
            <div class="setup-sub label">{{ setupHeadline.sub }}</div>
          </div>
          <p class="verdict">{{ verdict }}</p>
        </div>

        <div class="readouts">
          <Readout label="Close" :value="optNum(d.last?.close)" :sub="`ATR ${optNum(d.last?.atr)}`" />
          <Readout
            label="Leg depth"
            :value="`${num(focusSide === 'bottom' ? -(d.last?.off_high_atr ?? 0) : d.last?.off_low_atr ?? 0, 1)} ATR`"
            :sub="focusSide === 'bottom' ? 'below 50-bar high' : 'above 50-bar low'"
          />
          <Readout
            label="Swing VWAP"
            :value="`${optSigned(d.last?.svwap_dist_atr, 2)} ATR`"
            :sub="`${d.last?.swing_dir === 1 ? 'structure up' : 'structure down'} · ${optNum(d.last?.svwap)}`"
            :tone="(d.last?.svwap_dist_atr ?? 0) >= 0 ? 'call' : 'put'"
          />
          <Readout label="POC" :value="`${optSigned(d.last?.poc_dist_atr, 2)} ATR`" :sub="`VAL ${optNum(d.last?.val)} · VAH ${optNum(d.last?.vah)}`" />
          <Readout label="MACD-HA" :value="optNum(d.last?.macd, 0)" :sub="`HTF ${optNum(d.last?.htf_macd, 0)} · SPY ${optNum(d.last?.mkt_macd, 0)}`" />
          <Readout
            label="Breadth"
            :value="d.last?.breadth_below == null ? DASH : `${pp(d.last?.breadth_below, 0)} / ${pp(d.last?.breadth_above, 0)}`"
            sub="universe < -100 / > +100"
          />
          <Readout
            label="Model rank"
            :value="read?.rank ? tierLabel(read.rank.tier) : DASH"
            :sub="
              read?.rank?.tier
                ? `tier hit ${pp(read.rank.tier_rate)} vs base ${pp(read.rank.base_rate_test)}`
                : read?.candidate
                  ? 'no measured edge below top 20%'
                  : 'only ranked inside a qualifying leg'
            "
            :tone="read?.rank?.tier_edge === 'helps' ? (focusSide === 'bottom' ? 'call' : 'put') : 'flat'"
          />
          <Readout
            label="Probability"
            :value="read?.probability == null ? 'withheld' : pp(read.probability)"
            :sub="read?.probability == null ? 'failed calibration gate' : `2:1 hit · base ${pp(read.base_rate_test)}`"
            :tone="read?.probability == null ? 'flat' : 'accent'"
          />
        </div>
        <p v-if="read?.probability_reason" class="note">{{ read.probability_reason }}</p>
        <p v-if="d.missing_context?.length" class="note warn">
          Live context unavailable on the last bar: {{ d.missing_context.join(', ') }} — the study had it; this read runs without it.
        </p>
      </template>
    </Panel>

    <Panel v-if="d && ok" label="Chart stack" index="R2" :meta="`${bars.length} ${barUnit}`" flush>
      <div class="legend label">
        <span><i class="sw call-bg" /> swing VWAP (up)</span>
        <span><i class="sw put-bg" /> swing VWAP (down)</span>
        <span><i class="sw poc-bg" /> POC</span>
        <span><i class="sw va-bg" /> VAL / VAH</span>
        <span>▲▼ MACD-HA OS/OB</span>
        <span>● VWAP reclaim / reject</span>
        <span>◆ divergence (first bar)</span>
        <span>┃ swing flip</span>
      </div>
      <div ref="host" class="chart-host">
        <svg
          :viewBox="`0 0 ${W} ${TOTAL_H}`"
          :width="W"
          :height="TOTAL_H"
          role="img"
          :aria-label="`${d.symbol} price, swing VWAP, volume profile levels, volume and MACD-HA`"
          @mousemove="onMove"
          @mouseleave="hover = null"
        >
          <!-- price grid -->
          <g class="grid">
            <line v-for="t in priceTicks" :key="`pt${t}`" :x1="PAD_L" :x2="W - PAD_R" :y1="yP(t)" :y2="yP(t)" />
            <text v-for="t in priceTicks" :key="`pl${t}`" :x="W - PAD_R + 6" :y="yP(t) + 3">{{ num(t, t > 100 ? 0 : 2) }}</text>
          </g>
          <!-- profile levels -->
          <path :d="valPath" class="lvl va" />
          <path :d="vahPath" class="lvl va" />
          <path :d="pocPath" class="lvl poc" />
          <!-- flips -->
          <line
            v-for="(b, i) in bars"
            v-show="b.flip"
            :key="`f${i}`"
            :x1="x.at(i)"
            :x2="x.at(i)"
            :y1="6"
            :y2="H_PRICE"
            class="flip"
            :class="b.dir > 0 ? 'call-stroke' : 'put-stroke'"
          />
          <!-- candles -->
          <g v-for="(b, i) in bars" :key="`c${i}`">
            <template v-if="b.o != null && b.c != null && b.h != null && b.l != null">
              <line :x1="x.at(i)" :x2="x.at(i)" :y1="yP(b.h)" :y2="yP(b.l)" class="wick" :class="b.c >= b.o ? 'call-stroke' : 'put-stroke'" />
              <rect
                :x="x.at(i) - candleW / 2"
                :width="candleW"
                :y="Math.min(yP(b.o), yP(b.c))"
                :height="Math.max(1, Math.abs(yP(b.o) - yP(b.c)))"
                :class="b.c >= b.o ? 'call-fill' : 'put-fill'"
              />
            </template>
          </g>
          <path :d="vwapUp" class="vwap call-stroke" />
          <path :d="vwapDn" class="vwap put-stroke" />
          <!-- markers -->
          <g v-for="(b, i) in bars" :key="`m${i}`">
            <circle v-if="b.reclaim && b.c != null" :cx="x.at(i)" :cy="yP(b.c)" r="4" class="mk call-fill" />
            <circle v-if="b.reject && b.c != null" :cx="x.at(i)" :cy="yP(b.c)" r="4" class="mk put-fill" />
            <path
              v-if="b.bull_div && !bars[i - 1]?.bull_div && b.l != null"
              :d="`M${x.at(i)},${yP(b.l) + 8} l4,5 l-4,5 l-4,-5 z`"
              class="mk call-fill"
            />
            <path
              v-if="b.bear_div && !bars[i - 1]?.bear_div && b.h != null"
              :d="`M${x.at(i)},${yP(b.h) - 18} l4,5 l-4,5 l-4,-5 z`"
              class="mk put-fill"
            />
          </g>

          <!-- volume -->
          <g>
            <rect
              v-for="(b, i) in bars"
              :key="`v${i}`"
              :x="x.at(i) - candleW / 2"
              :width="candleW"
              :y="yV(b.v ?? 0)"
              :height="Math.max(0, volTop + H_VOL - yV(b.v ?? 0))"
              :class="(b.rvol ?? 0) >= 2 ? 'vol-hot' : 'vol'"
            />
            <text :x="W - PAD_R + 6" :y="volTop + 10" class="axis">vol</text>
            <text :x="W - PAD_R + 6" :y="volTop + 22" class="axis">≥2x hot</text>
          </g>

          <!-- MACD-HA pane -->
          <g>
            <rect :x="PAD_L" :width="W - PAD_L - PAD_R" :y="yM(150)" :height="Math.max(0, yM(100) - yM(150))" class="zone put-zone" />
            <rect :x="PAD_L" :width="W - PAD_L - PAD_R" :y="yM(-100)" :height="Math.max(0, yM(-150) - yM(-100))" class="zone call-zone" />
            <line :x1="PAD_L" :x2="W - PAD_R" :y1="yM(0)" :y2="yM(0)" class="zero" />
            <text v-for="t in [150, 100, 0, -100, -150]" :key="`mt${t}`" :x="W - PAD_R + 6" :y="yM(t) + 3" class="axis">{{ t }}</text>
            <g v-for="(b, i) in bars" :key="`h${i}`">
              <template v-if="b.m_o != null && b.m_c != null && b.m_h != null && b.m_l != null">
                <line :x1="x.at(i)" :x2="x.at(i)" :y1="yM(b.m_h)" :y2="yM(b.m_l)" class="wick" :class="b.m_c >= b.m_o ? 'call-stroke' : 'put-stroke'" />
                <rect
                  :x="x.at(i) - candleW / 2"
                  :width="candleW"
                  :y="Math.min(yM(b.m_o), yM(b.m_c))"
                  :height="Math.max(1, Math.abs(yM(b.m_o) - yM(b.m_c)))"
                  :class="b.m_c >= b.m_o ? 'hollow call-stroke' : 'put-fill'"
                />
              </template>
              <path v-if="b.os && b.m_l != null" :d="`M${x.at(i)},${yM(b.m_l) + 6} l5,8 l-10,0 z`" class="mk call-fill" />
              <path v-if="b.ob && b.m_h != null" :d="`M${x.at(i)},${yM(b.m_h) - 6} l5,-8 l-10,0 z`" class="mk put-fill" />
            </g>
            <path :d="macdSignalPath" class="sig" />
          </g>

          <!-- dates -->
          <text v-for="t in dateTicks" :key="`d${t.i}`" :x="x.at(t.i)" :y="TOTAL_H - 4" class="axis" text-anchor="middle">{{ t.label }}</text>

          <line v-if="hover != null" :x1="x.at(hover)" :x2="x.at(hover)" y1="0" :y2="TOTAL_H - 14" class="cross" />
        </svg>
        <div v-if="hoverBar" class="tip label">
          <span class="fig">{{ hoverBar.t.slice(0, 16).replace('T', ' ') }}</span>
          <span>C {{ optNum(hoverBar.c) }}</span>
          <span>VWAP {{ optNum(hoverBar.svwap) }}</span>
          <span>POC {{ optNum(hoverBar.poc) }}</span>
          <span>rvol {{ optNum(hoverBar.rvol) }}x</span>
          <span>MACD {{ optNum(hoverBar.m_c, 0) }}</span>
        </div>
      </div>
    </Panel>

    <div v-if="d && ok && read" class="grid2">
      <Panel label="Triggers — traded, vs no-signal baseline" index="R3" :meta="d.study?.available ? `full sample ${d.study.fit_period?.[0]} → ${d.study.test_period?.[1]} · late = 2nd half` : 'unmeasured'">
        <p class="note">
          Each trigger is traded the way you'd trade it: enter on the close, stop just past the leg's extreme, target 2R.
          <strong>Edge</strong> is its average R minus the average R of entering on ordinary leg bars under the same rule,
          so market drift cancels out.
          <HelpTip text="95% interval resamples whole dates. 'edge' only when the whole interval is above zero. Late = second half of the sample only, a stability check. R is the underlying's move in stop-distance units, before option premium and costs." />
        </p>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead>
              <tr>
                <th>Trigger</th>
                <th>Now</th>
                <th class="num">Trades</th>
                <th class="num">Win</th>
                <th class="num">Avg</th>
                <th class="num">Edge vs base</th>
                <th class="num">Late</th>
                <th class="num">Stop</th>
                <th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in read.triggers" :key="t.trigger" :class="{ lit: t.fired }">
                <td>{{ t.label }}</td>
                <td class="fig">{{ t.fired ? `${t.bars_ago} ago` : DASH }}</td>
                <td class="num fig">{{ t.n ?? DASH }}</td>
                <td class="num fig">{{ pp(t.win_rate, 0) }}</td>
                <td class="num fig">{{ r(t.avg_r) }}</td>
                <td class="num fig">
                  {{ r(t.edge_r) }}
                  <span class="ci">[{{ r(t.edge_r_lo) }}, {{ r(t.edge_r_hi) }}]</span>
                </td>
                <td class="num fig">{{ r(t.edge_r_late) }}</td>
                <td class="num fig">{{ t.risk_atr_median == null ? DASH : `${num(t.risk_atr_median, 1)} ATR` }}</td>
                <td><span class="chip" :class="t.measured_edge">{{ edgeLabel(t.measured_edge) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel label="How late is each cue" index="R4" :meta="lag ? `${lag.flips} swing legs` : ''">
        <template v-if="lag">
          <p class="note">Median distance from the true extreme, over every leg that flipped. Earlier is closer to 0 bars and 0 ATR.</p>
          <div class="tbl-wrap">
            <table class="tbl">
              <thead>
                <tr>
                  <th>Cue</th>
                  <th class="num">Present</th>
                  <th class="num">Bars after extreme</th>
                  <th class="num">Move already gone</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Swing VWAP flip (Zeiierman)</td>
                  <td class="num fig">100%</td>
                  <td class="num fig">{{ num(lag.flip_lag_bars_median, 0) }}</td>
                  <td class="num fig">{{ num(lag.flip_move_atr_median, 1) }} ATR</td>
                </tr>
                <tr>
                  <td>VWAP reclaim / reject</td>
                  <td class="num fig">{{ pp(lag.cue_share, 0) }}</td>
                  <td class="num fig">{{ optNum(lag.cue_lag_bars_median, 0) }}</td>
                  <td class="num fig">{{ optNum(lag.cue_move_atr_median, 1) }} ATR</td>
                </tr>
                <tr>
                  <td>MACD-HA OS / OB</td>
                  <td class="num fig">{{ pp(lag.macd_share, 0) }}</td>
                  <td class="num fig">{{ optNum(lag.macd_lag_bars_median, 0) }}</td>
                  <td class="num fig">{{ optNum(lag.macd_move_atr_median, 1) }} ATR</td>
                </tr>
                <tr>
                  <td>MACD-HA divergence</td>
                  <td class="num fig">{{ pp(lag.div_share, 0) }}</td>
                  <td class="num fig">{{ optNum(lag.div_lag_bars_median, 0) }}</td>
                  <td class="num fig">{{ optNum(lag.div_move_atr_median, 1) }} ATR</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="note">
            "Present" counts legs where the cue fired at all. Early cues also fire in legs that never turn — the trigger table
            above is what says whether acting on them paid.
          </p>
        </template>
        <p v-else class="note">No lag measurement for this timeframe.</p>
      </Panel>
    </div>

    <Panel v-if="d && ok && read" label="Signal checklist — 2:1 hit rate when on" index="R5" :meta="`base ${pp(read.base_rate_test)} · ${read.signals_on} on`">
      <p class="note">
        Every bar in a qualifying leg, +{{ d.barrier?.win_atr }} ATR before −{{ d.barrier?.loss_atr }} ATR within {{ d.barrier?.horizon_bars }} {{ barUnit }}.
        Lift is the hit rate when the signal is on minus the base rate, test period only.
      </p>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead>
            <tr>
              <th>Signal</th>
              <th>Now</th>
              <th class="num">Hit rate</th>
              <th class="num">Lift [95%]</th>
              <th class="num">n</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in read.signals" :key="s.key" :class="{ lit: s.on }">
              <td>{{ s.label }}</td>
              <td class="fig">{{ s.on ? 'ON' : DASH }}</td>
              <td class="num fig">{{ pp(s.test_rate) }}</td>
              <td class="num fig">
                {{ spp(s.test_lift) }} <span class="ci">[{{ spp(s.test_lift_lo) }}, {{ spp(s.test_lift_hi) }}]</span>
              </td>
              <td class="num fig">{{ s.test_n ?? DASH }}</td>
              <td><span class="chip" :class="s.measured_edge">{{ edgeLabel(s.measured_edge) }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="read.model_auc" class="note">
        Combined model ({{ read.model_chosen }}, picked on validation): test AUC {{ num(read.model_auc.auc, 3) }}
        [{{ num(read.model_auc.lo, 3) }}, {{ num(read.model_auc.hi, 3) }}]. 0.50 is a coin flip.
        <template v-if="read.drivers?.length">
          Biggest drivers: {{ read.drivers.slice(0, 4).map((x) => x.feature).join(', ') }}.
        </template>
      </p>
      <div v-if="rankTiers.length" class="tbl-wrap">
        <table class="tbl">
          <thead>
            <tr>
              <th>Model rank tier (test period)</th>
              <th class="num">2:1 hit rate</th>
              <th class="num">Lift vs base [95%]</th>
              <th class="num">n</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="[name, t] in rankTiers" :key="name" :class="{ lit: read.rank?.tier === name }">
              <td>{{ tierLabel(name) }} of leg bars</td>
              <td class="num fig">{{ pp(t.rate) }}</td>
              <td class="num fig">{{ spp(t.lift) }} <span class="ci">[{{ spp(t.lift_lo) }}, {{ spp(t.lift_hi) }}]</span></td>
              <td class="num fig">{{ t.n ?? DASH }}</td>
              <td><span class="chip" :class="t.edge">{{ edgeLabel(t.edge) }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </Panel>

    <Panel label="Scanner — symbols in a qualifying leg" index="R6" :meta="scan.data.value?.status === 'running' ? `scanning ${scan.data.value.done ?? 0}/${scan.data.value.total ?? '…'}` : `${scanRows.length} ${focusSide === 'bottom' ? 'down' : 'up'}-legs`">
      <p class="note">
        {{ scan.data.value?.universe ?? 'Core universe' }}. Sorted by model rank — the one read with a measured out-of-sample edge.
        <template v-if="tf === '1h'"> Local 1h bars can lag — check each row's as-of.</template>
      </p>
      <LoadingState v-if="!scan.data.value" compact label="Starting scan" />
      <p v-else-if="scan.data.value.status === 'error'" class="fail">{{ scan.data.value.error }}</p>
      <div v-else class="tbl-wrap">
        <table class="tbl">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>As of</th>
              <th class="num">Leg</th>
              <th class="num">VWAP</th>
              <th class="num">POC</th>
              <th class="num">MACD</th>
              <th>Model rank</th>
              <th>Triggers (last 5 bars)</th>
              <th class="num">Signals on</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in scanRows" :key="row.symbol" :class="{ lit: row.symbol === symbol }">
              <td>
                <button type="button" class="sym-btn fig" :aria-label="`Load ${row.symbol}`" @click="loadSymbol(row.symbol)">{{ row.symbol }}</button>
              </td>
              <td class="fig">{{ row.asof.slice(0, tf === '1h' ? 16 : 10).replace('T', ' ') }}</td>
              <td class="num fig">{{ optNum(row.leg_atr, 1) }}</td>
              <td class="num fig">{{ optSigned(row.svwap_dist_atr, 1) }}</td>
              <td class="num fig">{{ optSigned(row.poc_dist_atr, 1) }}</td>
              <td class="num fig">{{ optNum(row.macd, 0) }}</td>
              <td>
                <span v-if="row.rank_tier" class="chip" :class="row.rank_tier_edge === 'helps' ? 'helps' : ''">
                  {{ tierLabel(row.rank_tier) }} · {{ pp(row.rank_tier_rate, 0) }}
                </span>
                <span v-else class="dim">{{ DASH }}</span>
              </td>
              <td>
                <span v-for="t in row.triggers_fired" :key="t.trigger" class="chip" :class="t.measured_edge">{{ t.trigger }} · {{ t.bars_ago }}</span>
                <span v-if="!row.triggers_fired.length" class="dim">{{ DASH }}</span>
              </td>
              <td class="num fig">{{ row.signals_on.length }}</td>
            </tr>
            <tr v-if="scan.data.value.status === 'ready' && !scanRows.length">
              <td colspan="9" class="dim">No symbol is in a qualifying {{ focusSide === 'bottom' ? 'down' : 'up' }}-leg.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Panel>

    <p v-if="studyMeta?.available" class="foot label">
      Study: {{ studyMeta.symbols }} symbols · fit {{ studyMeta.fit_period?.join(' → ') }} · validation {{ studyMeta.validation_period?.join(' → ') }} ·
      test {{ studyMeta.test_period?.join(' → ') }} · generated {{ studyMeta.generated_at?.slice(0, 10) }}
      <span v-if="d?.source"> · bars: {{ d.source }}</span>
    </p>
    <p v-else-if="studyMeta" class="foot label warn">{{ studyMeta.reason }}</p>
  </div>
</template>

<style scoped>
.view {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  padding: var(--s4);
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

.ctl > .label {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.sym-row {
  display: flex;
  gap: var(--s1);
}

.input {
  width: 110px;
  height: var(--density-control-h);
  padding: 0 var(--s2);
  color: var(--ink);
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  font-size: var(--t-small);
}

.btn {
  height: var(--density-control-h);
  min-height: 28px;
  padding: 0 var(--s3);
  color: var(--ink);
  background: var(--panel-raise);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.refresh {
  margin-left: auto;
}

.seg {
  display: inline-flex;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
  overflow: hidden;
}

.seg button {
  min-height: 28px;
  padding: 0 var(--s3);
  color: var(--ink-dim);
  background: var(--panel-hi);
  border: 0;
  cursor: pointer;
}

.seg button + button {
  border-left: var(--hair) solid var(--rule);
}

.seg button.on {
  color: var(--ink);
  background: var(--panel-raise);
}

.seg button.call-on.on {
  color: var(--call-hi);
  background: var(--call-wash);
}

.seg button.put-on.on {
  color: var(--put-hi);
  background: var(--put-wash);
}

.headline {
  display: grid;
  grid-template-columns: minmax(180px, auto) 1fr;
  gap: var(--s4);
  align-items: center;
  margin: var(--s3) 0;
  padding: var(--s3);
  border: var(--hair) solid var(--rule);
  border-left-width: 3px;
  border-radius: var(--r-sm);
  background: var(--panel-hi);
}

.headline.call {
  border-left-color: var(--call);
}

.headline.put {
  border-left-color: var(--put);
}

.headline.flat {
  border-left-color: var(--rule-hi);
}

.setup {
  font-size: var(--t-fig);
  letter-spacing: 0.02em;
}

.headline.call .setup {
  color: var(--call-hi);
}

.headline.put .setup {
  color: var(--put-hi);
}

.setup-sub {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.verdict {
  margin: 0;
  color: var(--ink-soft);
  font-size: var(--t-body);
  line-height: 1.45;
}

.readouts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--s3);
}

.note {
  margin: var(--s2) 0;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.5;
}

.note.warn,
.foot.warn {
  color: var(--warn);
}

.fail {
  margin: var(--s3) 0;
  color: var(--put-hi);
  font-size: var(--t-small);
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  color: var(--ink-dim);
  font-size: var(--t-micro);
  border-bottom: var(--hair) solid var(--rule);
}

.legend .sw {
  display: inline-block;
  width: 14px;
  height: 3px;
  margin-right: 4px;
  vertical-align: middle;
}

.call-bg {
  background: var(--call);
}

.put-bg {
  background: var(--put);
}

.poc-bg {
  background: var(--warn);
}

.va-bg {
  background: var(--ink-ghost);
}

.chart-host {
  position: relative;
  width: 100%;
  height: auto;
  overflow-x: auto;
}

.chart-host svg {
  display: block;
  width: 100%;
  height: auto;
}

.grid line {
  stroke: var(--rule-faint);
  stroke-width: 1;
}

.grid text,
.axis {
  fill: var(--ink-faint);
  font-family: var(--font-data);
  font-size: 10px;
}

.lvl {
  fill: none;
  stroke-width: 1.2;
}

.lvl.poc {
  stroke: var(--warn);
}

.lvl.va {
  stroke: var(--ink-ghost);
  stroke-dasharray: 4 3;
}

.flip {
  stroke-width: 1;
  stroke-dasharray: 2 3;
  opacity: 0.7;
}

.wick {
  stroke-width: 1;
}

.call-stroke {
  stroke: var(--call);
}

.put-stroke {
  stroke: var(--put);
}

.call-fill {
  fill: var(--call);
}

.put-fill {
  fill: var(--put);
}

.hollow {
  fill: var(--panel);
  stroke-width: 1;
}

.vwap {
  fill: none;
  stroke-width: 2;
}

.mk {
  stroke: var(--panel);
  stroke-width: 1;
}

.vol {
  fill: var(--ink-ghost);
  opacity: 0.55;
}

.vol-hot {
  fill: var(--warn);
  opacity: 0.85;
}

.zone {
  opacity: 0.14;
}

.call-zone {
  fill: var(--call);
}

.put-zone {
  fill: var(--put);
}

.zero {
  stroke: var(--rule-hi);
  stroke-width: 1;
}

.sig {
  fill: none;
  stroke: var(--ink-soft);
  stroke-width: 1.2;
}

.cross {
  stroke: var(--ink-ghost);
  stroke-width: 1;
}

.tip {
  position: absolute;
  top: var(--s2);
  left: var(--s3);
  display: flex;
  flex-wrap: wrap;
  gap: var(--s3);
  padding: var(--s1) var(--s2);
  color: var(--ink-soft);
  font-size: var(--t-micro);
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  pointer-events: none;
}

.grid2 {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr);
  gap: var(--s4);
}

@media (max-width: 1100px) {
  .grid2 {
    grid-template-columns: minmax(0, 1fr);
  }

  .headline {
    grid-template-columns: 1fr;
  }
}

.tbl-wrap {
  overflow-x: auto;
}

.tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-tiny);
}

.tbl th {
  padding: var(--s1) var(--s2);
  color: var(--ink-faint);
  font-size: var(--t-nano);
  font-weight: 500;
  text-align: left;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: var(--hair) solid var(--rule);
  white-space: nowrap;
}

.tbl td {
  padding: var(--s1) var(--s2);
  color: var(--ink-soft);
  border-bottom: var(--hair) solid var(--rule-faint);
  vertical-align: top;
}

.tbl .num {
  text-align: right;
  white-space: nowrap;
}

.tbl tr.lit td {
  color: var(--ink);
  background: var(--panel-hi);
}

.sym-btn {
  min-height: 28px;
  padding: 0 var(--s2);
  color: var(--ink);
  background: var(--panel-raise);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  cursor: pointer;
}

.sym-btn:focus-visible {
  outline: var(--hair) solid var(--action-focus);
  outline-offset: 1px;
}

.ci {
  display: block;
  color: var(--ink-faint);
  font-size: var(--t-nano);
}

.chip {
  display: inline-block;
  margin: 0 4px 2px 0;
  padding: 1px 6px;
  font-size: var(--t-nano);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  color: var(--ink-dim);
  white-space: nowrap;
}

.chip.helps {
  color: var(--call-hi);
  border-color: var(--call-dim);
  background: var(--call-wash);
}

.chip.hurts {
  color: var(--put-hi);
  border-color: var(--put-dim);
  background: var(--put-wash);
}

.dim {
  color: var(--ink-faint);
}

.foot {
  margin: 0;
  color: var(--ink-faint);
  font-size: var(--t-micro);
}
</style>
