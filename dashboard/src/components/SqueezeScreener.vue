<script setup lang="ts">
/**
 * Gamma squeeze read — one verdict, and the arithmetic that produced it.
 *
 * The score is FUEL × DIRECTION: how much short dealer gamma sits near spot
 * relative to what the name trades, times how hard flow and momentum push one
 * way. The board shows the verdict, then walks those three steps with the real
 * numbers so the conclusion can be checked, not trusted. Unmeasured inputs are
 * named as missing and never drawn as a zero.
 */
import { computed } from 'vue'
import type { OptionsSqueeze } from '@/api'
import { optUsd, DASH } from '@/format'
import HelpTip from '@/components/HelpTip.vue'
import { buildSqueezeExplanation, freshnessTier, formatAge } from '@/squeezeCalc'

const props = defineProps<{
  squeeze: OptionsSqueeze | null | undefined
  spot?: number | null
  /** Provenance of the chain snapshot this board was scored from. */
  asof?: string | null
  ageSeconds?: number | null
  mode?: string | null
  chainProvider?: string | null
  oiProvider?: string | null
  contracts?: number | null
  expiryLabel?: string | null
  /**
   * Tape state, already present on the options payload — no second fetch.
   * prints = flow prints included in the scoring; signed = whether the tape
   * carries an aggressor side; warnings = the payload's warning strings.
   */
  tapePrints?: number | null
  tapeSigned?: boolean | null
  tapeWarnings?: string[] | null
}>()

const ex = computed(() => buildSqueezeExplanation(props.squeeze, props.spot))

/** Scale ticks on the −100…+100 bar, as 0–100% positions. */
const ticks = computed(() => {
  const { leanAt, squeezeAt } = ex.value
  return [-squeezeAt, -leanAt, 0, leanAt, squeezeAt].map((v) => ({
    v,
    left: 50 + v / 2,
    major: v === 0,
  }))
})

/** Coloured run from centre to the marker, so the eye reads sign + size at once. */
const runStyle = computed(() => {
  const m = ex.value.markerPct
  if (m == null) return { display: 'none' }
  const left = Math.min(50, m)
  return { left: `${left}%`, width: `${Math.abs(m - 50)}%` }
})

function distLabel(pct: number | null): string {
  if (pct == null || !Number.isFinite(pct)) return DASH
  if (Math.abs(pct) < 0.00005) return 'at spot'
  const r = pct * 100
  return `${r > 0 ? '+' : '−'}${Math.abs(r).toFixed(2)}%`
}

/** Feed provenance. Reported, never assumed: an unknown age stays unknown. */
const fresh = computed(() => {
  const tier = freshnessTier(props.ageSeconds, props.mode)
  const labels: Record<string, string> = {
    live: 'LIVE',
    delayed: 'DELAYED',
    stale: 'STALE',
    history: 'HISTORY',
    unknown: 'AGE UNKNOWN',
  }
  return { tier, label: labels[tier] ?? 'AGE UNKNOWN', age: formatAge(props.ageSeconds) }
})

const asofLabel = computed(() => {
  const raw = props.asof
  if (!raw) return DASH
  const ms = Date.parse(raw)
  if (!Number.isFinite(ms)) return String(raw)
  return new Date(ms).toISOString().replace('T', ' ').slice(0, 19) + 'Z'
})

const contractsLabel = computed(() =>
  props.contracts == null || !Number.isFinite(props.contracts)
    ? DASH
    : Number(props.contracts).toLocaleString('en-US'),
)

/**
 * One-line tape status, derived from data already on the options payload —
 * never a second request. Cooldown/rate-limit warnings outrank the print
 * count; anything unknown falls back to the count; nothing renders when the
 * payload carried nothing at all.
 */
const tapeChip = computed(() => {
  const warns = (props.tapeWarnings ?? []).join(' ').toLowerCase()
  if (/cooldown|rate.?limit|http_?\s?429|retry after|temporarily unavailable/.test(warns)) {
    return { text: 'TAPE: PROVIDER COOLDOWN', tone: 'warn' as const }
  }
  const n = props.tapePrints
  if (n != null && Number.isFinite(n) && n > 0) {
    const unsigned = props.tapeSigned === false
    return {
      text: `TAPE: ${Math.round(n).toLocaleString('en-US')} PRINTS${unsigned ? ' · UNSIGNED' : ''}`,
      tone: unsigned ? ('warn' as const) : ('ok' as const),
    }
  }
  if (n === 0 || /no trade-tape prints|no_prints/.test(warns)) {
    return { text: 'TAPE: NO PRINTS', tone: 'muted' as const }
  }
  return null
})

/**
 * The full audit line. Every clause names a real payload field; a field the
 * payload did not carry is reported as unknown rather than omitted, because a
 * silently missing source reads as "no problem" when it is the opposite.
 */
const provDetail = computed(() => {
  const parts = [
    `As of ${asofLabel.value} (age ${fresh.value.age}).`,
    `Chain feed: ${props.chainProvider || 'unknown'}.`,
    `Open interest: ${props.oiProvider || 'unknown'}.`,
    `${contractsLabel.value} contracts passed quality filters.`,
  ]
  if (props.expiryLabel) parts.push(`Expiry: ${props.expiryLabel}.`)
  if (props.mode) parts.push(`Mode: ${props.mode}.`)
  const scale = ex.value.fuelScale
  parts.push(
    `Score = fuel × direction. Fuel = tanh(${scale} × squeeze risk), ` +
      'where squeeze risk is |short dealer gamma| ÷ daily $ volume × ATM share × front-book expiry urgency. ' +
      'Direction blends signed flow and 5-day momentum; an input that is not measured does not vote. ' +
      'A gamma-structure diagnostic, not a calibrated probability.',
  )
  return parts.join(' ')
})
</script>

<template>
  <div v-if="squeeze" class="sq" :class="ex.side" :data-tone="ex.tone">
    <!-- 1 · Verdict -->
    <header class="head">
      <div class="head-main">
        <p class="kicker label">SQUEEZE READ</p>
        <h3 class="verdict">{{ ex.verdict }}</h3>
        <p class="summary">{{ ex.summary }}</p>
      </div>
      <div class="head-score">
        <span class="score-num">{{ ex.scoreDisplay }}</span>
        <span class="score-cap label">THEORY SCORE · NOT A FORECAST</span>
      </div>
    </header>

    <!-- measurement honesty + tape state: why the score looks the way it does -->
    <div v-if="ex.dirChip || tapeChip" class="chips">
      <span v-if="ex.dirChip" class="chip label" :data-tone="ex.dirChip.tone">{{ ex.dirChip.text }}</span>
      <span v-if="tapeChip" class="chip label" :data-tone="tapeChip.tone">{{ tapeChip.text }}</span>
    </div>

    <!-- 2 · Where the score sits between the bands -->
    <div
      class="scale"
      role="img"
      :aria-label="
        ex.score == null
          ? 'Squeeze score unmeasured'
          : `Squeeze score ${ex.scoreDisplay} on a scale from minus 100 to plus 100`
      "
    >
      <div class="scale-track">
        <span class="scale-run" :style="runStyle" />
        <span
          v-for="tk in ticks"
          :key="tk.v"
          class="scale-tick"
          :class="{ major: tk.major }"
          :style="{ left: `${tk.left}%` }"
        />
        <span v-if="ex.markerPct != null" class="scale-marker" :style="{ left: `${ex.markerPct}%` }" />
      </div>
      <div class="scale-legend label">
        <span>BEAR SQUEEZE</span>
        <span>LEAN</span>
        <span>QUIET</span>
        <span>LEAN</span>
        <span>BULL SQUEEZE</span>
      </div>
    </div>

    <!-- 3 · How it got here -->
    <section class="block">
      <h4 class="block-title label">HOW IT GOT HERE</h4>
      <p class="identity-formula label">{{ ex.formula }}</p>
      <ol class="steps">
        <li v-for="(st, i) in ex.steps" :key="st.id" class="step" :class="`st-${st.tone}`">
          <div class="step-top">
            <span class="step-op label" aria-hidden="true">{{ i === 0 ? '1' : i === 1 ? '×' : '=' }}</span>
            <span class="step-title label">{{ st.title }}</span>
            <span class="step-value">{{ st.value }}</span>
          </div>
          <div v-if="st.id === 'direction'" class="dir-legs" aria-label="Direction legs">
            <div
              v-for="leg in ex.dirLegs"
              :key="leg.id"
              class="dir-leg"
              :data-tone="leg.tone"
              :data-votes="leg.votes ? 'yes' : 'no'"
            >
              <span class="dir-leg-label label">{{ leg.label }}</span>
              <span class="dir-leg-val">{{ leg.display }}</span>
              <span class="dir-leg-meter" aria-hidden="true">
                <i v-if="leg.fill01 != null" :style="{ width: `${(leg.fill01 * 100).toFixed(1)}%` }" />
              </span>
            </div>
          </div>
          <div v-else class="step-meter" aria-hidden="true">
            <i v-if="st.fill01 != null" :style="{ width: `${(st.fill01 * 100).toFixed(1)}%` }" />
          </div>
          <ul class="step-lines">
            <li v-for="(ln, j) in st.lines" :key="j">{{ ln }}</li>
          </ul>
        </li>
      </ol>
    </section>

    <!-- 4 · Levels that matter -->
    <section v-if="ex.levels.length" class="block">
      <h4 class="block-title label">LEVELS</h4>
      <ul class="levels">
        <li
          v-for="lv in ex.levels"
          :key="lv.id"
          class="level"
          :class="[`lv-${lv.tone}`, { trigger: lv.trigger }]"
        >
          <span class="lv-dot" aria-hidden="true" />
          <span class="lv-label label">{{ lv.label }}</span>
          <span class="lv-price">{{ lv.price != null ? optUsd(lv.price) : DASH }}</span>
          <span class="lv-dist">{{ distLabel(lv.pct) }}</span>
          <span class="lv-note">{{ lv.note }}</span>
        </li>
      </ul>
    </section>

    <!-- 5 · What would change the read -->
    <section v-if="ex.watch.length" class="block">
      <h4 class="block-title label">WHAT WOULD CHANGE IT</h4>
      <ul class="watch">
        <li v-for="(w, i) in ex.watch" :key="i">{{ w }}</li>
      </ul>
    </section>

    <footer class="prov label" :class="`fresh-${fresh.tier}`">
      <span class="prov-lamp" aria-hidden="true" />
      <span>{{ fresh.label }}</span>
      <span>AGE {{ fresh.age }}</span>
      <span>{{ contractsLabel }} CONTRACTS</span>
      <span v-if="expiryLabel">EXP {{ expiryLabel }}</span>
      <HelpTip label="Squeeze read" :text="provDetail" />
    </footer>
  </div>

  <div v-else class="sq empty">
    <p class="empty-head label">Squeeze unavailable</p>
    <p class="empty-body">No scored chain for this symbol yet.</p>
  </div>
</template>

<style scoped>
.sq {
  --sq-tone: var(--ink-dim);
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  min-width: 0;
  min-height: 0;
  height: 100%;
  padding: var(--s4);
  overflow-y: auto;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}
.sq[data-tone='bullish'] {
  --sq-tone: var(--call-hi);
}
.sq[data-tone='bearish'] {
  --sq-tone: var(--put-hi);
}
.sq[data-tone='warn'] {
  --sq-tone: var(--warn);
}
.sq[data-tone='neutral'],
.sq[data-tone='unmeasured'] {
  --sq-tone: var(--ink-soft);
}

/* ---- verdict ---------------------------------------------------------- */
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s4);
}
.head-main {
  min-width: 0;
}
.kicker {
  margin: 0 0 var(--s1);
  color: var(--ink-faint);
  font-size: var(--t-nano);
  letter-spacing: 0.12em;
}
.verdict {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--t-lead);
  font-weight: 600;
  letter-spacing: 0.02em;
  line-height: 1.1;
  color: var(--sq-tone);
}
.summary {
  margin: var(--s2) 0 0;
  font-size: var(--t-small);
  line-height: 1.45;
  color: var(--ink-dim);
  max-width: 46ch;
}
.head-score {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  flex-shrink: 0;
  gap: var(--s1);
}
.score-num {
  font-family: var(--font-data);
  font-size: var(--t-fig-lg);
  font-weight: 600;
  line-height: 1;
  color: var(--sq-tone);
}
.score-cap {
  font-size: var(--t-nano);
  color: var(--ink-faint);
  letter-spacing: 0.08em;
  white-space: nowrap;
}

/* ---- measurement / tape chips ----------------------------------------- */
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
}
.chip {
  display: inline-flex;
  align-items: center;
  min-height: 18px;
  padding: 0 var(--s2);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  font-size: var(--t-nano);
  letter-spacing: 0.1em;
  color: var(--ink-soft);
  background: var(--glass-base);
}
.chip[data-tone='warn'] {
  color: var(--warn);
  border-color: var(--warn);
}
.chip[data-tone='ok'] {
  color: var(--phosphor);
  border-color: var(--rule-hi);
}
.chip[data-tone='muted'] {
  color: var(--ink-faint);
  border-color: var(--rule-faint);
}

/* ---- −100…+100 scale -------------------------------------------------- */
.scale-track {
  position: relative;
  height: 8px;
  background: var(--glass-base);
  border: var(--hair) solid var(--glass-border-subtle);
  border-radius: var(--r-xs);
}
.scale-run {
  position: absolute;
  top: 0;
  bottom: 0;
  background: var(--sq-tone);
  opacity: 0.55;
}
.scale-tick {
  position: absolute;
  top: -3px;
  bottom: -3px;
  width: var(--hair);
  background: var(--rule-hi);
}
.scale-tick.major {
  background: var(--ink-faint);
}
.scale-marker {
  position: absolute;
  top: -5px;
  bottom: -5px;
  width: 3px;
  margin-left: -1.5px;
  background: var(--sq-tone);
  transition: left var(--dur) var(--ease-out);
}
.scale-legend {
  display: grid;
  grid-template-columns: 30fr 10fr 20fr 10fr 30fr;
  margin-top: var(--s2);
  font-size: var(--t-nano);
  color: var(--ink-faint);
  letter-spacing: 0.06em;
}
.scale-legend span {
  text-align: center;
  white-space: nowrap;
}
.scale-legend span:first-child {
  text-align: left;
}
.scale-legend span:last-child {
  text-align: right;
}

/* ---- sections --------------------------------------------------------- */
.block {
  border-top: var(--hair) solid var(--rule);
  padding-top: var(--s3);
}
.block-title {
  margin: 0 0 var(--s3);
  font-size: var(--t-nano);
  font-weight: 500;
  color: var(--ink-faint);
  letter-spacing: 0.12em;
}
.identity-formula {
  margin: calc(var(--s3) * -1) 0 var(--s3);
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  letter-spacing: 0.04em;
  color: var(--ink-dim);
}

/* ---- steps ------------------------------------------------------------ */
.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}
.step {
  --st-tone: var(--ink-soft);
}
.step.st-fuel {
  --st-tone: var(--phosphor);
}
.step.st-bullish {
  --st-tone: var(--call-hi);
}
.step.st-bearish {
  --st-tone: var(--put-hi);
}
.step.st-warn {
  --st-tone: var(--warn);
}
.step-top {
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr) auto;
  align-items: baseline;
  gap: var(--s2);
}
.step-op {
  font-family: var(--font-data);
  font-size: var(--t-small);
  color: var(--ink-faint);
  text-align: center;
}
.step-title {
  font-size: var(--t-tiny);
  color: var(--ink-soft);
  letter-spacing: 0.1em;
}
.step-value {
  font-family: var(--font-data);
  font-size: var(--t-body);
  font-weight: 600;
  color: var(--st-tone);
}
.step-meter {
  height: 3px;
  margin: var(--s2) 0 var(--s2) 24px;
  background: var(--glass-base);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.step-meter i {
  display: block;
  height: 100%;
  background: var(--st-tone);
  transition: width var(--dur) var(--ease-out);
}
.dir-legs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s3);
  margin: var(--s2) 0 var(--s2) 24px;
}
.dir-leg {
  --leg-tone: var(--ink-faint);
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px var(--s2);
  align-items: baseline;
}
.dir-leg[data-tone='flow'] {
  --leg-tone: var(--phosphor);
}
.dir-leg[data-tone='mom'] {
  --leg-tone: var(--ink);
}
.dir-leg[data-tone='warn'] {
  --leg-tone: var(--warn);
}
.dir-leg-label {
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
.dir-leg-val {
  font-family: var(--font-data);
  font-size: var(--t-small);
  font-weight: 600;
  color: var(--leg-tone);
  text-align: right;
}
.dir-leg-meter {
  grid-column: 1 / -1;
  height: 3px;
  background: var(--glass-base);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.dir-leg-meter i {
  display: block;
  height: 100%;
  background: var(--leg-tone);
}
.step-lines {
  list-style: none;
  margin: 0 0 0 24px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.step-lines li {
  font-size: var(--t-tiny);
  line-height: 1.45;
  color: var(--ink-dim);
}

/* ---- levels ----------------------------------------------------------- */
.levels {
  list-style: none;
  margin: 0;
  padding: 0;
}
.level {
  --lv-tone: var(--ink-soft);
  display: grid;
  grid-template-columns: 8px 84px auto 64px minmax(0, 1fr);
  align-items: baseline;
  gap: var(--s2);
  padding: 5px 0;
  border-bottom: var(--hair) solid var(--rule-faint);
}
.level:last-child {
  border-bottom: 0;
}
.level.lv-call {
  --lv-tone: var(--call);
}
.level.lv-put {
  --lv-tone: var(--put);
}
.level.lv-accent {
  --lv-tone: var(--phosphor);
}
.level.lv-ink {
  --lv-tone: var(--ink);
}
.lv-dot {
  width: 6px;
  height: 6px;
  align-self: center;
  background: var(--lv-tone);
}
.lv-label {
  font-size: var(--t-nano);
  color: var(--ink-soft);
  letter-spacing: 0.08em;
  white-space: nowrap;
}
.lv-price {
  font-family: var(--font-data);
  font-size: var(--t-small);
  color: var(--ink);
}
.lv-dist {
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  color: var(--ink-faint);
  text-align: right;
}
.lv-note {
  font-size: var(--t-tiny);
  color: var(--ink-dim);
  min-width: 0;
}
.level.trigger .lv-label,
.level.trigger .lv-price {
  color: var(--lv-tone);
}

/* ---- watch ------------------------------------------------------------ */
.watch {
  margin: 0;
  padding: 0 0 0 var(--s4);
  display: flex;
  flex-direction: column;
  gap: var(--s1);
}
.watch li {
  font-size: var(--t-tiny);
  line-height: 1.45;
  color: var(--ink-dim);
}
.watch li::marker {
  color: var(--ink-faint);
}

/* ---- provenance ------------------------------------------------------- */
.prov {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s2) var(--s3);
  margin-top: auto;
  padding-top: var(--s3);
  border-top: var(--hair) solid var(--rule);
  font-size: var(--t-nano);
  color: var(--ink-faint);
  letter-spacing: 0.06em;
}
.prov-lamp {
  width: 6px;
  height: 6px;
  background: var(--ink-faint);
}
.prov.fresh-live .prov-lamp {
  background: var(--phosphor);
}
.prov.fresh-delayed .prov-lamp,
.prov.fresh-stale .prov-lamp {
  background: var(--warn);
}

/* ---- empty ------------------------------------------------------------ */
.sq.empty {
  justify-content: center;
  min-height: 120px;
}
.empty-head {
  margin: 0;
  color: var(--ink-soft);
  font-size: var(--t-tiny);
}
.empty-body {
  margin: var(--s1) 0 0;
  color: var(--ink-faint);
  font-size: var(--t-tiny);
}

@media (max-width: 520px) {
  .level {
    grid-template-columns: 8px minmax(0, 1fr) auto 64px;
  }
  .lv-note {
    grid-column: 2 / -1;
  }
  .head {
    flex-direction: column;
  }
  .head-score {
    align-items: flex-start;
  }
  .dir-legs {
    grid-template-columns: 1fr;
  }
}
</style>
