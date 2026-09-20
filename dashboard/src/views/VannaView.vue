<script setup lang="ts">
/**
 * Vanna — delta–vol coupling mechanics, one underlier.
 *
 * Reads top-to-bottom as mechanics → levels → event:
 *   · EVENT STRIP   FOMC clock: phase badge, next meeting, desk note
 *   · SUMMARY ROW   net vanna flow ($Δ per vol pt), call/put split, direction
 *   · BY STRIKE     diverging call-up / put-down bars, spot + vanna pivot
 *   · BY EXPIRY     which expiry carries the load (front week on FOMC week)
 *
 * Data honesty: when the backend has no chain (404 / empty by_strike) the
 * board renders an explicit "chain unavailable" state. No placeholder bars,
 * no invented numbers — every figure below is a payload field or derived
 * from one (dominance share = |net| / Σ|net| across strikes).
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  vannaDirectionCopy,
  vannaDirectionLabel,
  vannaDominantExpiry,
  vannaPhaseLabel,
  vannaPhaseTone,
  type VannaExpiryFlowRow,
  type VannaPayload,
  type VannaStrikeFlowRow,
} from '@/api'
import { useResource } from '@/composables/useResource'
import { compact, DASH, optSignedGex, shortDate, usd } from '@/format'
import { linearScale, niceTicks } from '@/charts'
import Panel from '@/components/Panel.vue'
import LoadingState from '@/components/LoadingState.vue'

const route = useRoute()
const router = useRouter()

/* ---- symbol selection (route-query convention, same as Options/Drift) ---- */
function readSymbol(): string {
  const raw = route.query.symbol
  return typeof raw === 'string' && raw.trim()
    ? raw
        .trim()
        .toUpperCase()
        .replace(/[^A-Z0-9.-]/g, '')
        .slice(0, 10)
    : 'SPY'
}
const symbol = ref(readSymbol())
const symbolInput = ref(readSymbol())

function loadSymbol(raw: string): void {
  const clean = raw
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
    .slice(0, 10)
  if (!clean || clean === symbol.value) return
  symbol.value = clean
  symbolInput.value = clean
  void router.replace({ name: 'vanna', query: { symbol: clean } })
}

watch(
  () => route.query.symbol,
  (next) => {
    if (typeof next === 'string' && next && next.toUpperCase() !== symbol.value) {
      symbol.value = next.toUpperCase()
      symbolInput.value = next.toUpperCase()
    }
  },
)
watch(symbol, () => void res.refresh({ clear: true }))

/* ---- payload ---- */
const res = useResource<VannaPayload>(() => api.vanna(symbol.value), {
  intervalMs: 60_000,
  immediate: true,
})
const payload = computed(() => res.data.value)
const initialLoading = computed(() => res.loading.value && !payload.value)

const summary = computed(() => payload.value?.vanna_summary ?? null)
const event = computed(() => payload.value?.event_context ?? null)
const spot = computed(() => payload.value?.spot ?? null)
const asof = computed(() => payload.value?.asof ?? null)
const pivot = computed(() => payload.value?.vanna_pivot ?? null)

/**
 * Explicit empty state, never a fabricated one: a failed fetch with no prior
 * payload, or a payload with no measured strikes, both mean "no chain".
 */
const unavailableReason = computed(() => {
  if (payload.value) {
    return (payload.value.by_strike ?? []).length === 0
      ? 'no measured option chain for this underlier'
      : null
  }
  if (res.error.value) return res.error.value
  return null
})

const panelMeta = computed(() =>
  asof.value ? `snapshot ${shortDate(asof.value.slice(0, 10))}` : '',
)

const source = computed(() => summary.value?.source ?? '')
const skipped = computed(() => summary.value?.contracts_skipped ?? 0)

const direction = computed(() => summary.value?.direction ?? null)
const directionLabel = computed(() => vannaDirectionLabel(direction.value))
const directionCopy = computed(() => vannaDirectionCopy(direction.value))
const phaseLabel = computed(() => vannaPhaseLabel(event.value))
const phaseTone = computed(() => vannaPhaseTone(event.value))

/* ---- money readouts: +$12.3M / — for unmeasured ----
 * Backend vanna_flow is RAW DOLLARS ($ of delta per 1 vol pt);
 * optSignedGex expects its input pre-scaled to millions. */
function gexMoney(v: number | null | undefined): string {
  return v == null ? DASH : optSignedGex(v / 1e6)
}

/* ---- call/put split pair widths (share of the gross |call|+|put|) ---- */
const split = computed(() => {
  const s = summary.value
  if (!s) return { call: 0, put: 0, callVal: null, putVal: null }
  const gross = Math.abs(s.call_vanna_flow) + Math.abs(s.put_vanna_flow)
  if (!(gross > 0)) return { call: 0, put: 0, callVal: null, putVal: null }
  return {
    call: (Math.abs(s.call_vanna_flow) / gross) * 100,
    put: (Math.abs(s.put_vanna_flow) / gross) * 100,
    callVal: s.call_vanna_flow,
    putVal: s.put_vanna_flow,
  }
})

/* ---- by-strike diverging chart geometry ---- */
const CH = { w: 860, h: 300, top: 26, bottom: 250, left: 56, right: 14 }

/** Strike window: up to 25 strikes centred on spot (or the pivot if no spot). */
const chartRows = computed(() => {
  const rows = (payload.value?.by_strike ?? [])
    .filter((r) => Number.isFinite(r.strike))
    .sort((a, b) => a.strike - b.strike)
  if (rows.length <= 25) return rows
  const anchor = spot.value ?? pivot.value ?? rows[Math.floor(rows.length / 2)].strike
  let near = 0
  for (let i = 0; i < rows.length; i++) {
    if (Math.abs(rows[i].strike - anchor) < Math.abs(rows[near].strike - anchor)) near = i
  }
  const start = Math.max(0, Math.min(near - 12, rows.length - 25))
  return rows.slice(start, start + 25)
})

/** Symmetric $ domain around zero so the midline is true zero. */
const flowMax = computed(() => {
  let m = 0
  for (const r of chartRows.value) {
    m = Math.max(m, Math.abs(r.call_vanna_flow ?? 0), Math.abs(r.put_vanna_flow ?? 0))
  }
  return m > 0 ? m * 1.08 : 0
})
const yScale = computed(() => linearScale([-flowMax.value, flowMax.value], [CH.bottom, CH.top]))
const zeroY = computed(() => yScale.value(0))
const yTicks = computed(() =>
  flowMax.value > 0 ? niceTicks(-flowMax.value, flowMax.value, 5) : [],
)

interface StrikeGeom {
  strike: number
  cx: number
  bw: number
  callY: number
  callH: number
  putY: number
  putH: number
  isPivotNear: boolean
  isSpotNear: boolean
}
const strikeBars = computed<StrikeGeom[]>(() => {
  const rows = chartRows.value
  if (!rows.length || flowMax.value <= 0) return []
  const inner = CH.w - CH.left - CH.right
  const slot = inner / rows.length
  return rows.map((r, i) => {
    const cx = CH.left + slot * (i + 0.5)
    const bw = Math.max(3, slot * 0.36)
    const cy = yScale.value(r.call_vanna_flow)
    const py = yScale.value(r.put_vanna_flow)
    const tol = Math.max(1e-9, (rows[1]?.strike ?? r.strike) - r.strike) / 2
    return {
      strike: r.strike,
      cx,
      bw,
      callY: Math.min(cy, zeroY.value),
      callH: Math.abs(cy - zeroY.value),
      putY: Math.min(py, zeroY.value),
      putH: Math.abs(py - zeroY.value),
      isPivotNear: pivot.value != null && Math.abs(r.strike - pivot.value) <= tol,
      isSpotNear: spot.value != null && Math.abs(r.strike - spot.value) <= tol,
    }
  })
})

const xForValue = computed(() => {
  const bars = strikeBars.value
  if (!bars.length) return (_: number) => 0
  const lo = bars[0].strike
  const hi = bars[bars.length - 1].strike
  return linearScale([lo, hi], [bars[0].cx, bars[bars.length - 1].cx])
})
function guideX(v: number | null): number | null {
  if (v == null || !Number.isFinite(v) || !strikeBars.value.length) return null
  return xForValue.value(v)
}
const spotX = computed(() => guideX(spot.value))
const pivotX = computed(() => guideX(pivot.value))

const strikeTicks = computed(() => {
  const bars = strikeBars.value
  if (!bars.length) return [] as { strike: number; x: number }[]
  const step = Math.max(1, Math.ceil(bars.length / 8))
  return bars
    .filter((_, i) => i % step === 0 || i === bars.length - 1)
    .map((b) => ({ strike: b.strike, x: b.cx }))
})
function axisMoney(v: number): string {
  return `${v < 0 ? '-$' : v > 0 ? '+$' : ''}${compact(Math.abs(v), 1)}`
}

/** Net-flow dominance across the window — feeds the top-bar readouts. */
const dominantStrike = computed(() => {
  let best: VannaStrikeFlowRow | null = null
  for (const r of chartRows.value) {
    if (!best || Math.abs(r.net_vanna_flow) > Math.abs(best.net_vanna_flow)) best = r
  }
  return best
})

/* ---- by-expiry table ---- */
const expiryRows = computed(() =>
  [...(payload.value?.by_expiry ?? [])].sort((a, b) => a.dte - b.dte),
)
const expiryMax = computed(() => {
  let m = 0
  for (const r of expiryRows.value) m = Math.max(m, Math.abs(r.net_vanna_flow ?? 0))
  return m
})
const dominantExpiry = computed(() => vannaDominantExpiry(expiryRows.value))
function expiryNetWidth(row: VannaExpiryFlowRow): number {
  return expiryMax.value > 0 ? (Math.abs(row.net_vanna_flow) / expiryMax.value) * 100 : 0
}
function expiryLabel(e: string): string {
  return shortDate(e)
}
</script>

<template>
  <div class="view vanna-view">
    <Panel label="Vanna" index="17" :meta="panelMeta">
      <!-- Symbol control -->
      <div class="controls">
        <div class="ctl symbol-ctl">
          <label class="label" for="vanna-sym">Underlier</label>
          <div class="sym-row">
            <input
              id="vanna-sym"
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
        <p class="mechanic-caption">
          Vanna is ∂Δ/∂IV: dealer delta moves when implied vol moves. Net vanna flow below is the
          dollar hedge that change forces — it is how an event-driven vol crush or spike turns into
          mechanical buying and selling.
        </p>
      </div>

      <LoadingState v-if="initialLoading" label="Loading vanna board" />

      <!-- Honest empty state: no chain, no fabricated numbers -->
      <div v-else-if="unavailableReason" class="unavailable-note label wraps">
        Vanna chain unavailable for <strong class="fig">{{ symbol }}</strong> —
        {{ unavailableReason }}. No strike, expiry, or event readout is shown for an unmeasured
        chain.
      </div>

      <template v-else-if="payload">
        <!-- EVENT STRIP -->
        <section v-if="event" class="event-strip" :class="`phase-${phaseTone}`">
          <div class="event-badge label">{{ phaseLabel }}</div>
          <div class="event-facts">
            <span class="label">NEXT FOMC</span>
            <span class="fig">{{ event.next_fomc ? shortDate(event.next_fomc) : DASH }}</span>
            <span v-if="event.days_to_fomc != null" class="label days">
              {{ event.is_fomc_day ? 'TODAY' : `${event.days_to_fomc}D OUT` }}
            </span>
            <span v-if="event.is_fomc_week" class="label week-chip">FOMC WEEK</span>
          </div>
          <p v-if="event.note" class="event-note">{{ event.note }}</p>
        </section>

        <!-- SUMMARY ROW -->
        <section class="summary-row">
          <div class="stat net-stat">
            <span class="label">NET VANNA FLOW</span>
            <span
              class="fig big"
              :class="summary && summary.net_vanna_flow < 0 ? 'tone-put' : 'tone-call'"
            >
              {{ gexMoney(summary?.net_vanna_flow) }}
            </span>
            <span class="label sub">$Δ per 1 vol pt</span>
          </div>
          <div class="stat split-stat">
            <span class="label">CALL / PUT SPLIT</span>
            <div
              class="split-pair"
              role="img"
              :aria-label="`call vanna ${gexMoney(split.callVal)}, put vanna ${gexMoney(split.putVal)}`"
            >
              <div class="split-side">
                <span class="label">CALLS</span>
                <div class="split-track">
                  <div class="split-fill call" :style="{ width: split.call + '%' }" />
                </div>
                <span class="fig sm">{{ gexMoney(split.callVal) }}</span>
              </div>
              <div class="split-side">
                <span class="label">PUTS</span>
                <div class="split-track">
                  <div class="split-fill put" :style="{ width: split.put + '%' }" />
                </div>
                <span class="fig sm">{{ gexMoney(split.putVal) }}</span>
              </div>
            </div>
          </div>
          <div class="stat dir-stat">
            <span class="label">DIRECTION</span>
            <span class="dir-chip label" :class="`dir-${direction ?? 'none'}`">{{
              directionLabel
            }}</span>
            <span class="dir-copy">{{ directionCopy }}</span>
          </div>
          <div class="stat meta-stat">
            <div class="meta-line">
              <span class="label">SPOT</span
              ><span class="fig">{{ payload.spot != null ? usd(payload.spot, 2) : DASH }}</span>
            </div>
            <div class="meta-line">
              <span class="label">ASOF</span
              ><span class="fig">{{ asof ? shortDate(asof) : DASH }}</span>
            </div>
            <div class="meta-line">
              <span class="label">SOURCE</span><span class="fig sm">{{ source || DASH }}</span>
            </div>
            <div v-if="skipped > 0" class="meta-line skipped">
              <span class="label">CONTRACTS SKIPPED</span><span class="fig">{{ skipped }}</span>
            </div>
          </div>
        </section>
        <p class="block-caption">
          Positive net vanna means a post-event vol crush lifts dealer call deltas — hedges sell
          into strength and buy dips asymmetrically. Negative flips the impulse.
        </p>

        <!-- VANNA BY STRIKE -->
        <section class="block">
          <header class="block-head">
            <h3 class="label">VANNA BY STRIKE</h3>
            <span class="label legend"
              ><i class="sw call" /> CALLS UP · <i class="sw put" /> PUTS DOWN</span
            >
            <span v-if="dominantStrike" class="label dominant">
              LARGEST LOAD <span class="fig">{{ usd(dominantStrike.strike, 0) }}</span>
            </span>
          </header>
          <svg
            class="strike-chart"
            :viewBox="`0 0 ${CH.w} ${CH.h}`"
            role="img"
            aria-label="Diverging vanna flow by strike"
          >
            <!-- gridlines + value axis -->
            <g v-for="t in yTicks" :key="`y-${t}`" class="gridline">
              <line :x1="CH.left" :x2="CH.w - CH.right" :y1="yScale(t)" :y2="yScale(t)" />
              <text class="y-label" :x="CH.left - 8" :y="yScale(t) + 3.5" text-anchor="end">
                {{ axisMoney(t) }}
              </text>
            </g>
            <line class="zero-line" :x1="CH.left" :x2="CH.w - CH.right" :y1="zeroY" :y2="zeroY" />

            <!-- bars: call column left of slot centre, put column right -->
            <g v-for="b in strikeBars" :key="`s-${b.strike}`">
              <rect
                class="bar call"
                :x="b.cx - b.bw - 0.5"
                :y="b.callY"
                :width="b.bw"
                :height="b.callH"
              />
              <rect class="bar put" :x="b.cx + 0.5" :y="b.putY" :width="b.bw" :height="b.putH" />
            </g>

            <!-- guides: spot + vanna pivot -->
            <g v-if="spotX != null" class="guide spot-guide">
              <line :x1="spotX" :x2="spotX" :y1="CH.top" :y2="CH.bottom" />
              <text :x="spotX" :y="CH.top - 8" text-anchor="middle">SPOT</text>
            </g>
            <g v-if="pivotX != null" class="guide pivot-guide" data-testid="vanna-pivot-marker">
              <line :x1="pivotX" :x2="pivotX" :y1="CH.top" :y2="CH.bottom" />
              <text :x="pivotX" :y="CH.bottom + 18" text-anchor="middle">VANNA PIVOT</text>
            </g>

            <!-- strike axis -->
            <g v-for="t in strikeTicks" :key="`x-${t.strike}`" class="x-tick">
              <text :x="t.x" :y="CH.h - 8" text-anchor="middle">{{ usd(t.strike, 0) }}</text>
            </g>
          </svg>
          <p class="block-caption">
            Call vanna above the midline, puts below (signed). The pivot is the strike where net
            vanna flips sign — the mechanical hedge impulse reverses as spot crosses it.
          </p>
        </section>

        <!-- VANNA BY EXPIRY -->
        <section class="block">
          <header class="block-head">
            <h3 class="label">VANNA BY EXPIRY</h3>
            <span v-if="dominantExpiry" class="label dominant">
              DOMINANT <span class="fig">{{ expiryLabel(dominantExpiry.expiry) }}</span> ·
              {{ dominantExpiry.dte }}D
            </span>
          </header>
          <table class="expiry-table">
            <thead>
              <tr>
                <th class="label">EXPIRY</th>
                <th class="label">DTE</th>
                <th class="label num">CALL</th>
                <th class="label num">PUT</th>
                <th class="label num">NET</th>
                <th class="label">LOAD</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in expiryRows"
                :key="row.expiry"
                :class="{ 'is-dominant': dominantExpiry && row.expiry === dominantExpiry.expiry }"
              >
                <td class="fig">{{ expiryLabel(row.expiry) }}</td>
                <td class="fig">{{ row.dte }}</td>
                <td class="fig num">{{ gexMoney(row.call_vanna_flow) }}</td>
                <td class="fig num">{{ gexMoney(row.put_vanna_flow) }}</td>
                <td class="fig num" :class="row.net_vanna_flow < 0 ? 'tone-put' : 'tone-call'">
                  {{ gexMoney(row.net_vanna_flow) }}
                </td>
                <td class="load-cell">
                  <div class="load-track">
                    <div
                      class="load-fill"
                      :class="row.net_vanna_flow < 0 ? 'put' : 'call'"
                      :style="{ width: expiryNetWidth(row) + '%' }"
                    />
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <p class="block-caption">
            DTE ascending. The shortest dated load is what the event reprices first — on FOMC week
            the front expiry dominates the board.
          </p>
        </section>
      </template>
    </Panel>
  </div>
</template>

<style scoped>
/* Content surface: de-glassed panel children, tokens only, 10px font floor. */
.vanna-view {
  display: block;
}

.controls {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s4);
  align-items: flex-end;
  margin-bottom: var(--s4);
}
.symbol-ctl .sym-row {
  display: flex;
  gap: var(--s2);
}
.input,
.btn {
  min-height: var(--density-control-h);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--panel-hi);
  color: var(--ink);
  padding: 0 var(--s3);
}
.btn {
  cursor: pointer;
  color: var(--ink-soft);
}
.btn:focus-visible,
.input:focus-visible {
  outline: var(--focus-ring);
  outline-offset: var(--focus-ring-offset);
}
.mechanic-caption {
  flex: 1 1 320px;
  margin: 0;
  font-size: var(--t-tiny);
  color: var(--ink-dim);
  line-height: 1.5;
}

.unavailable-note {
  padding: var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  color: var(--ink-dim);
  background: var(--panel-hi);
}

/* ---- event strip: accent border, no glow ---- */
.event-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s3) var(--s4);
  padding: var(--s3) var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  margin-bottom: var(--s4);
}
.event-strip.phase-hot {
  border-color: color-mix(in srgb, var(--warn) 25%, var(--rule));
  background: var(--warn-wash);
}
.event-strip.phase-cool {
  border-color: var(--rule-hi);
}
.event-badge {
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  color: var(--ink);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  padding: 2px var(--s2);
}
.phase-hot .event-badge {
  color: var(--warn);
  border-color: var(--warn);
}
.event-facts {
  display: flex;
  align-items: baseline;
  gap: var(--s3);
}
.event-facts .days {
  color: var(--ink-dim);
}
.week-chip {
  color: var(--warn);
  border: var(--hair) solid var(--warn);
  border-radius: var(--r-xs);
  padding: 1px var(--s2);
}
.event-note {
  flex: 1 1 100%;
  margin: 0;
  font-size: var(--t-tiny);
  color: var(--ink-soft);
  line-height: 1.5;
}

/* ---- summary row ---- */
.summary-row {
  display: grid;
  grid-template-columns: minmax(180px, 1.1fr) minmax(220px, 1.4fr) minmax(220px, 1.4fr) minmax(
      160px,
      1fr
    );
  gap: var(--s4);
  padding: var(--s3) 0 var(--s2);
}
.stat {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}
.stat .label {
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  color: var(--ink-faint);
}
.fig.big {
  font-size: var(--t-fig-lg);
  letter-spacing: var(--track-display);
  line-height: 1.1;
}
.fig.sm {
  font-size: var(--t-tiny);
}
.tone-call {
  color: var(--call);
}
.tone-put {
  color: var(--put);
}
.stat .sub {
  color: var(--ink-faint);
}
.split-pair {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}
.split-side {
  display: grid;
  grid-template-columns: 44px 1fr 76px;
  align-items: center;
  gap: var(--s2);
}
.split-track {
  height: 8px;
  background: var(--rule-faint);
  border-radius: var(--r-xs);
}
.split-fill {
  height: 100%;
  border-radius: var(--r-xs);
}
.split-fill.call {
  background: var(--call);
}
.split-fill.put {
  background: var(--put);
}
.dir-chip {
  align-self: flex-start;
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  padding: 2px var(--s2);
  color: var(--ink-dim);
}
.dir-chip.dir-iv_up_supportive {
  color: var(--call);
  border-color: var(--call-dim);
}
.dir-chip.dir-iv_up_pressuring {
  color: var(--put);
  border-color: var(--put-dim);
}
.dir-copy {
  font-size: var(--t-tiny);
  color: var(--ink-dim);
  line-height: 1.45;
}
.meta-stat .meta-line {
  display: flex;
  justify-content: space-between;
  gap: var(--s2);
}
.meta-stat .skipped .fig {
  color: var(--warn);
}

/* ---- blocks ---- */
.block {
  border-top: var(--hair) solid var(--rule);
  padding-top: var(--s3);
  margin-top: var(--s3);
}
.block-head {
  display: flex;
  align-items: baseline;
  gap: var(--s4);
  margin-bottom: var(--s2);
}
.block-head h3 {
  margin: 0;
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  color: var(--ink);
}
.label.legend {
  color: var(--ink-faint);
}
.sw {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: var(--r-xs);
  vertical-align: -1px;
}
.sw.call {
  background: var(--call);
}
.sw.put {
  background: var(--put);
}
.label.dominant {
  margin-left: auto;
  color: var(--ink-dim);
}
.block-caption {
  margin: var(--s2) 0 0;
  font-size: var(--t-tiny);
  color: var(--ink-faint);
  line-height: 1.5;
}

/* ---- strike chart ---- */
.strike-chart {
  width: 100%;
  height: auto;
  display: block;
}
.gridline line {
  stroke: var(--grid);
  stroke-width: 1;
}
.gridline .y-label {
  fill: var(--ink-faint);
  font-size: var(--t-nano);
  font-family: var(--font-data);
}
.zero-line {
  stroke: var(--rule-hi);
  stroke-width: 1;
}
.bar.call {
  fill: var(--call);
}
.bar.put {
  fill: var(--put);
}
.guide line {
  stroke-width: 1;
  stroke-dasharray: 3 3;
}
.guide text {
  font-size: var(--t-nano);
  font-family: var(--font-data);
  letter-spacing: var(--track-label);
}
.spot-guide line {
  stroke: var(--ink-dim);
}
.spot-guide text {
  fill: var(--ink-dim);
}
.pivot-guide line {
  stroke: var(--warn);
}
.pivot-guide text {
  fill: var(--warn);
}
.x-tick text {
  fill: var(--ink-faint);
  font-size: var(--t-nano);
  font-family: var(--font-data);
}

/* ---- expiry table ---- */
.expiry-table {
  width: 100%;
  border-collapse: collapse;
}
.expiry-table th {
  text-align: left;
  font-size: var(--t-micro);
  color: var(--ink-faint);
  font-weight: 400;
  padding: var(--density-cell-padding);
  border-bottom: var(--hair) solid var(--rule);
}
.expiry-table td {
  padding: var(--density-cell-padding);
  height: var(--density-row-height);
  border-bottom: var(--hair) solid var(--rule-faint);
  font-size: var(--t-small);
  color: var(--ink-soft);
}
.expiry-table .num {
  text-align: right;
}
.expiry-table .is-dominant td:first-child {
  border-left: 2px solid var(--warn);
}
.load-track {
  height: 6px;
  min-width: 80px;
  background: var(--rule-faint);
  border-radius: var(--r-xs);
}
.load-fill {
  height: 100%;
  border-radius: var(--r-xs);
}
.load-fill.call {
  background: var(--call);
}
.load-fill.put {
  background: var(--put);
}

@media (max-width: 1080px) {
  .summary-row {
    grid-template-columns: 1fr 1fr;
  }
}
@media (max-width: 640px) {
  .summary-row {
    grid-template-columns: 1fr;
  }
}
</style>
