<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ZeroDteTapePayload, ZeroDteLevel } from '@/api'
import { linearScale, niceTicks } from '@/charts'
import { useChartSize } from '@/composables/useChartSize'
import { compact, num, DASH } from '@/format'

/**
 * 0DTE tape — the session's real bars with the same-day expiry pulling on them.
 *
 * Three things share one price axis, which is the whole point of the panel:
 *
 *   · the candles          — actual OHLC prints, not a smoothed line
 *   · the magnet lines     — gamma flip / pin / walls / max pain, drawn at
 *                            their price, weighted by pull so a level that
 *                            cannot reach price is visibly faint
 *   · the strike ladder    — same-day gamma by strike, on the right, at the
 *                            same vertical scale, so "the pull to the bars"
 *                            is a thing you look at rather than infer
 *
 * Nothing here is drawn unless the engine measured it. When a level is absent
 * the row says so; it is never replaced with a plausible-looking number.
 */
const props = withDefaults(
  defineProps<{
    payload: ZeroDteTapePayload | null
    loading?: boolean
    height?: number
  }>(),
  { loading: false, height: 460 },
)

const emit = defineEmits<{ (e: 'timeframe', tf: '1m' | '5m' | '15m'): void }>()

const frameEl = ref<HTMLDivElement | null>(null)
const { W } = useChartSize(frameEl, { minW: 320, minH: 260, fallbackW: 1080, fallbackH: 460 })

const H = computed(() => Math.max(320, Math.round(props.height)))
const LADDER_W = computed(() => (W.value < 640 ? 0 : 132))
const pad = computed(() => ({
  t: 16,
  r: 76 + LADDER_W.value,
  b: 74,
  l: W.value < 480 ? 44 : 56,
}))

const bars = computed(() => props.payload?.bars ?? [])
const levels = computed<ZeroDteLevel[]>(() => props.payload?.levels ?? [])
const profile = computed(() => props.payload?.strike_profile ?? [])
const intent = computed(() => props.payload?.intent ?? null)
const gamma = computed(() => props.payload?.gamma ?? null)
const session = computed(() => props.payload?.session ?? null)

const plotW = computed(() => Math.max(60, W.value - pad.value.l - pad.value.r))
const plotH = computed(() => Math.max(80, H.value - pad.value.t - pad.value.b - 52))
const volTop = computed(() => pad.value.t + plotH.value + 14)
const volH = 38

/** Price domain covers the bars *and* every level, so no magnet falls off. */
const domain = computed<[number, number]>(() => {
  const px: number[] = []
  for (const b of bars.value) px.push(b.high, b.low)
  for (const lv of levels.value) px.push(lv.price)
  if (!px.length) return [0, 1]
  const lo = Math.min(...px)
  const hi = Math.max(...px)
  const padY = (hi - lo) * 0.06 || 1
  return [lo - padY, hi + padY]
})

const y = computed(() => linearScale(domain.value, [pad.value.t + plotH.value, pad.value.t]))
const x = computed(() =>
  linearScale([0, Math.max(1, bars.value.length - 1)], [pad.value.l, pad.value.l + plotW.value]),
)
const candleW = computed(() =>
  Math.max(1, Math.min(9, (plotW.value / Math.max(1, bars.value.length)) * 0.72)),
)
const yTicks = computed(() => niceTicks(domain.value[0], domain.value[1], 6))

const maxVol = computed(() => Math.max(1, ...bars.value.map((b) => b.volume)))

/** Hour boundaries, labelled in exchange time — the session's own clock. */
const timeMarks = computed(() => {
  const out: { cx: number; label: string }[] = []
  let last = ''
  bars.value.forEach((b, i) => {
    const d = new Date(b.ts)
    const hh = d.toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
    if (hh.endsWith(':00') && hh !== last) {
      last = hh
      out.push({ cx: x.value(i), label: hh })
    }
  })
  return out
})

const spotY = computed(() => {
  const s = props.payload?.spot
  return s != null ? y.value(s) : null
})

const LEVEL_TONE: Record<string, string> = {
  gamma_flip: 'var(--warn)',
  pin: 'var(--phosphor)',
  call_wall: 'var(--call)',
  put_wall: 'var(--put)',
  max_pain: 'var(--ink-dim)',
  vwap: 'var(--ink-faint)',
}

function toneFor(kind: string): string {
  return LEVEL_TONE[kind] ?? 'var(--ink-dim)'
}

/** Pull drives opacity and stroke width — a weak magnet must look weak. */
function levelStyle(lv: ZeroDteLevel) {
  const p = Math.max(0, Math.min(100, lv.pull)) / 100
  return {
    stroke: toneFor(lv.kind),
    strokeWidth: 1 + p * 2.2,
    opacity: 0.28 + p * 0.62,
  }
}

const drawnLevels = computed(() =>
  levels.value
    .filter((lv) => lv.price >= domain.value[0] && lv.price <= domain.value[1])
    .map((lv) => ({ lv, cy: y.value(lv.price), ...levelStyle(lv) })),
)

/** Right-hand ladder: same-day gamma per strike, on the shared price axis. */
const ladder = computed(() => {
  if (!LADDER_W.value || !profile.value.length) return []
  const peak = Math.max(...profile.value.map((r) => Math.abs(r.call_gex_m) + Math.abs(r.put_gex_m)), 1e-9)
  const x0 = pad.value.l + plotW.value + 64
  const rows = profile.value.filter(
    (r) => r.strike >= domain.value[0] && r.strike <= domain.value[1],
  )
  const step = rows.length > 1 ? Math.abs(y.value(rows[1].strike) - y.value(rows[0].strike)) : 6
  const barH = Math.max(1.5, Math.min(10, step * 0.78))
  return rows.map((r) => {
    const cw = (Math.abs(r.call_gex_m) / peak) * (LADDER_W.value - 8)
    const pw = (Math.abs(r.put_gex_m) / peak) * (LADDER_W.value - 8)
    return { row: r, cy: y.value(r.strike) - barH / 2, h: barH, x0, cw, pw }
  })
})

const tfOptions: Array<'1m' | '5m' | '15m'> = ['1m', '5m', '15m']

/** Only worth saying when it is a big enough slice to change the picture. */
const ivFallbackNote = computed(() => {
  const q = props.payload?.quality
  if (!q || !q.strikes || !q.iv_fallback_rows) return null
  const share = q.iv_fallback_rows / Math.max(1, q.strikes * 2)
  if (share < 0.1) return null
  return `${Math.round(share * 100)}% of contracts quoted no usable implied vol; those borrowed the expiry's at-the-money vol to price gamma.`
})

const INTENT_TONE: Record<string, string> = {
  pinning: 'var(--phosphor)',
  magnetized: 'var(--phosphor)',
  rejected: 'var(--put)',
  escaping: 'var(--warn)',
  drifting_off: 'var(--ink-dim)',
  ranging: 'var(--ink-dim)',
  unresolved: 'var(--ink-faint)',
}

function verdictLabel(v: string | undefined): string {
  if (!v) return DASH
  return { accepted: 'held', rejected: 'rejected', converging: 'closing', diverging: 'leaving', idle: 'quiet' }[v] ?? v
}
</script>

<template>
  <section class="zdt">
    <header class="zdt-head">
      <div class="zdt-id">
        <span class="zdt-sym">{{ payload?.symbol ?? DASH }}</span>
        <span class="zdt-exp">
          {{ payload?.expiry ?? DASH }}
          <em v-if="payload?.is_true_0dte" class="tag tag-live">0DTE</em>
          <em v-else-if="payload?.days_to_expiry != null" class="tag tag-warn">
            {{ payload.days_to_expiry }}DTE — nearest expiry
          </em>
        </span>
      </div>
      <div class="zdt-meta">
        <span v-if="session">{{ session.bars_shown }} bars</span>
        <!-- A countdown only means something when these bars are the expiry
             session's. On a weekend or holiday they are the last session's,
             and "390 min to close" would read as a live clock. -->
        <span v-if="session && session.clock_is_live && payload?.is_true_0dte">
          {{ num(session.minutes_remaining, 0) }} min to close
        </span>
        <span v-else-if="session">{{ session.bars_shown ? 'last session' : DASH }}</span>
        <span v-if="gamma?.expected_move != null">
          ±{{ num(gamma.expected_move, 2) }} expected
        </span>
      </div>
      <div class="zdt-tf" role="group" aria-label="Bar size">
        <button
          v-for="tf in tfOptions"
          :key="tf"
          type="button"
          :class="['tf', { on: payload?.timeframe === tf }]"
          @click="emit('timeframe', tf)"
        >
          {{ tf }}
        </button>
      </div>
    </header>

    <p v-if="!payload" class="zdt-blocked">
      Waiting for the first chain and bar pull.
    </p>

    <p v-else-if="!payload.measurable" class="zdt-blocked">
      {{ payload.reason || 'Nothing measurable for this symbol.' }}
    </p>

    <template v-else>
      <div v-if="intent" class="zdt-intent" :style="{ '--tone': INTENT_TONE[intent.state] ?? 'var(--ink-dim)' }">
        <div class="zdt-intent-top">
          <span class="zdt-state">{{ intent.state.replace('_', ' ') }}</span>
          <p class="zdt-headline">{{ intent.headline }}</p>
        </div>
        <ul v-if="intent.evidence.length" class="zdt-ev">
          <li v-for="(e, i) in intent.evidence" :key="i">{{ e }}</li>
        </ul>
        <p class="zdt-regime">{{ intent.gamma_note }}</p>
      </div>

      <div ref="frameEl" class="zdt-frame">
        <svg :viewBox="`0 0 ${W} ${H}`" :height="H" class="zdt-svg" role="img"
             :aria-label="`${payload?.symbol} intraday bars with same-day option magnets`">
          <!-- price grid -->
          <g class="grid">
            <template v-for="t in yTicks" :key="`g${t}`">
              <line :x1="pad.l" :x2="pad.l + plotW" :y1="y(t)" :y2="y(t)" />
              <text :x="pad.l - 8" :y="y(t) + 3" text-anchor="end">{{ num(t, 2) }}</text>
            </template>
          </g>

          <!-- magnets, under the bars so the prints stay readable -->
          <g class="magnets">
            <g v-for="d in drawnLevels" :key="d.lv.kind + d.lv.price">
              <line
                :x1="pad.l" :x2="pad.l + plotW" :y1="d.cy" :y2="d.cy"
                :stroke="d.stroke" :stroke-width="d.strokeWidth" :opacity="d.opacity"
                :stroke-dasharray="d.lv.kind === 'vwap' ? '3 4' : undefined"
              />
              <text
                :x="pad.l + plotW + 6" :y="d.cy + 3"
                :fill="d.stroke" :opacity="Math.min(1, d.opacity + 0.2)" class="mag-lab"
              >{{ num(d.lv.price, 2) }}</text>
            </g>
          </g>

          <!-- the bars themselves -->
          <g class="candles">
            <g v-for="(b, i) in bars" :key="b.ts">
              <line
                :x1="x(i)" :x2="x(i)" :y1="y(b.high)" :y2="y(b.low)"
                :stroke="b.close >= b.open ? 'var(--call)' : 'var(--put)'"
                stroke-width="1" opacity="0.7"
              />
              <rect
                :x="x(i) - candleW / 2"
                :y="Math.min(y(b.open), y(b.close))"
                :width="candleW"
                :height="Math.max(1, Math.abs(y(b.close) - y(b.open)))"
                :fill="b.close >= b.open ? 'var(--call)' : 'var(--put)'"
                opacity="0.9"
              />
            </g>
          </g>

          <!-- live spot -->
          <line
            v-if="spotY != null" class="spot"
            :x1="pad.l" :x2="pad.l + plotW" :y1="spotY" :y2="spotY"
          />

          <!-- volume -->
          <g class="vol">
            <rect
              v-for="(b, i) in bars" :key="`v${b.ts}`"
              :x="x(i) - candleW / 2"
              :y="volTop + volH - (b.volume / maxVol) * volH"
              :width="candleW"
              :height="Math.max(0.5, (b.volume / maxVol) * volH)"
              :fill="b.close >= b.open ? 'var(--call-dim)' : 'var(--put-dim)'"
            />
          </g>

          <!-- session clock -->
          <g class="tmarks">
            <text v-for="m in timeMarks" :key="m.label" :x="m.cx" :y="volTop + volH + 16"
                  text-anchor="middle">{{ m.label }}</text>
          </g>

          <!-- same-day gamma by strike, same price axis -->
          <g v-if="ladder.length" class="ladder">
            <text :x="pad.l + plotW + 64" :y="pad.t - 4" class="ladder-cap">
              same-day gamma · puts ◄ ► calls
            </text>
            <g v-for="l in ladder" :key="`k${l.row.strike}`">
              <rect :x="l.x0 - l.pw" :y="l.cy" :width="l.pw" :height="l.h" fill="var(--put)" opacity="0.55" />
              <rect :x="l.x0" :y="l.cy" :width="l.cw" :height="l.h" fill="var(--call)" opacity="0.55" />
            </g>
            <line :x1="pad.l + plotW + 64" :x2="pad.l + plotW + 64" :y1="pad.t" :y2="pad.t + plotH"
                  stroke="var(--rule)" stroke-width="1" />
          </g>
        </svg>
      </div>

      <table class="zdt-tbl">
        <caption class="sr-only">Magnet levels and how the session's bars behaved at each</caption>
        <thead>
          <tr>
            <th scope="col">Magnet</th>
            <th scope="col" class="r">Price</th>
            <th scope="col" class="r">Gap</th>
            <th scope="col" class="r">Pull</th>
            <th scope="col" class="r">Touches</th>
            <th scope="col" class="r">Rejected</th>
            <th scope="col" class="r">Held</th>
            <th scope="col">Doing</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="lv in levels" :key="lv.kind + lv.price">
            <th scope="row">
              <span class="dot" :style="{ background: toneFor(lv.kind) }" />
              {{ lv.label }}
              <em v-if="lv.confluence.length > 1" class="conf">+{{ lv.confluence.length - 1 }}</em>
            </th>
            <td class="r mono">{{ num(lv.price, 2) }}</td>
            <td class="r mono" :class="lv.distance_pts >= 0 ? 'up' : 'dn'">
              {{ lv.distance_pts >= 0 ? '+' : '' }}{{ num(lv.distance_pts, 2) }}
            </td>
            <td class="r">
              <span class="pull"><i :style="{ width: `${Math.max(2, lv.pull)}%`, background: toneFor(lv.kind) }" /></span>
              <span class="mono pull-n">{{ num(lv.pull, 0) }}</span>
            </td>
            <td class="r mono">{{ lv.interaction?.touches ?? DASH }}</td>
            <td class="r mono">{{ lv.interaction?.rejections ?? DASH }}</td>
            <td class="r mono">
              {{ lv.interaction ? `${num(lv.interaction.minutes_inside_band, 0)}m` : DASH }}
            </td>
            <td class="doing">{{ verdictLabel(lv.interaction?.verdict) }}</td>
          </tr>
        </tbody>
      </table>

      <footer class="zdt-foot">
        <span v-if="gamma">
          weighted by {{ gamma.weight_basis === 'volume' ? "today's volume" : 'open interest' }}
          · flip {{ gamma.flip != null ? num(gamma.flip, 2) : 'not in range' }}
          · tilt {{ gamma.tilt >= 0 ? '+' : '' }}{{ num(gamma.tilt, 2) }}
          <template v-if="gamma.atm_iv != null"> · ATM IV {{ num(gamma.atm_iv * 100, 1) }}%</template>
          <template v-if="session && session.volume > 0">
            · {{ compact(session.volume) }} shares
          </template>
          <template v-if="payload?.chain_source === 'yahoo'"> · chain via Yahoo</template>
        </span>
        <!-- Say when a material share of the book had no usable IV of its own.
             The profile is still built, but from a borrowed expiry vol. -->
        <p v-if="ivFallbackNote" class="zdt-quality">{{ ivFallbackNote }}</p>
        <ul v-if="payload?.warnings?.length" class="zdt-warn">
          <li v-for="(w, i) in payload.warnings" :key="i">{{ w }}</li>
        </ul>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.zdt { display: flex; flex-direction: column; gap: 10px; }

.zdt-head { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.zdt-sym { font: 600 15px/1 var(--font-display); color: var(--ink); letter-spacing: 0.02em; }
.zdt-exp { font: 400 var(--t-micro) var(--font-data); color: var(--ink-dim); margin-left: 8px; }
.tag { font-style: normal; font-size: var(--t-nano); padding: 1px 5px; border-radius: var(--r-xs); margin-left: 6px; }
.tag-live { background: color-mix(in srgb, var(--phosphor) 20%, transparent); color: var(--phosphor); }
.tag-warn { background: color-mix(in srgb, var(--warn) 16%, transparent); color: var(--warn); }
.zdt-meta { display: flex; gap: 12px; font: 400 var(--t-nano) var(--font-data); color: var(--ink-faint); margin-left: auto; }
.zdt-tf { display: flex; gap: 2px; }
.tf {
  font: 500 var(--t-nano) var(--font-data); color: var(--ink-dim);
  background: var(--panel); border: 1px solid var(--rule); border-radius: var(--r-xs);
  padding: 2px 7px; cursor: pointer;
}
.tf.on { color: var(--void); background: var(--phosphor); border-color: var(--phosphor); }

.zdt-blocked {
  font: 400 var(--t-micro) var(--font-data); color: var(--ink-dim);
  background: var(--panel); border: 1px solid var(--rule); border-radius: var(--r-sm);
  padding: 14px 16px; margin: 0;
}

.zdt-intent {
  border: 1px solid var(--rule); background: var(--panel);
  border-radius: var(--r-sm); padding: 10px 14px;
}
.zdt-intent-top { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.zdt-state {
  font: 600 var(--t-nano) var(--font-data); color: var(--tone);
  text-transform: uppercase; letter-spacing: 0.08em;
}
.zdt-headline { margin: 0; font: 400 var(--t-micro) var(--font-data); color: var(--ink); }
.zdt-ev { margin: 6px 0 0; padding-left: 16px; }
.zdt-ev li { font: 400 var(--t-nano) var(--font-data); color: var(--ink-dim); }
.zdt-regime { margin: 6px 0 0; font: 400 var(--t-nano) var(--font-data); color: var(--ink-faint); }

.zdt-frame { width: 100%; }
.zdt-svg { width: 100%; display: block; }
.grid line { stroke: var(--grid); stroke-width: 1; }
.grid text { font: 400 var(--t-nano) var(--font-data); fill: var(--ink-faint); }
.mag-lab { font: 500 var(--t-nano) var(--font-data); }
.spot { stroke: var(--ink); stroke-width: 1; stroke-dasharray: 2 3; opacity: 0.55; }
.tmarks text { font: 400 var(--t-nano) var(--font-data); fill: var(--ink-faint); }
.ladder-cap { font: 400 var(--t-nano) var(--font-data); fill: var(--ink-faint); text-anchor: middle; }

.zdt-tbl { width: 100%; border-collapse: collapse; }
.zdt-tbl th, .zdt-tbl td {
  font: 400 var(--t-nano) var(--font-data); padding: 4px 8px;
  border-bottom: 1px solid var(--hair); text-align: left;
}
.zdt-tbl thead th { color: var(--ink-faint); font-weight: 500; }
.zdt-tbl tbody th { color: var(--ink); font-weight: 400; white-space: nowrap; }
.r { text-align: right; }
.mono { font-family: var(--font-data); font-variant-numeric: tabular-nums; }
.up { color: var(--call); }
.dn { color: var(--put); }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; }
.conf { font-style: normal; color: var(--ink-faint); margin-left: 5px; }
.pull { display: inline-block; width: 46px; height: 5px; background: var(--rule-faint); border-radius: 3px; vertical-align: middle; overflow: hidden; }
.pull i { display: block; height: 100%; }
.pull-n { margin-left: 6px; color: var(--ink-dim); }
.doing { color: var(--ink-dim); }

.zdt-foot { font: 400 var(--t-nano) var(--font-data); color: var(--ink-faint); }
.zdt-warn { margin: 6px 0 0; padding-left: 16px; }
.zdt-warn li { color: var(--warn); }
.zdt-quality { margin: 4px 0 0; color: var(--ink-faint); }
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
</style>
