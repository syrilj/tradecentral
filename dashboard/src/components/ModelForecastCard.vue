<script setup lang="ts">
/**
 * "What it should be" — the internal research mark for a symbol.
 *
 * Shared by the Market tab's Financials and Forecast surfaces so the two can
 * never drift apart. Everything shown here is decision support: the card
 * publishes the hurdle, the input coverage and the mark's provenance alongside
 * the number so a reader can tell how much weight it carries.
 */
import { computed } from 'vue'
import { DASH, pctFrac, signedPct } from '@/format'
import {
  formatGearingUp,
  formatModelForecastScore,
  formatModelPredictedPrice,
  type ModelForecastView,
} from '@/financialsDisplay'
import type { CaseRangeView, PredictionHitView } from '@/financialsDisplay'

const props = defineProps<{
  forecast: ModelForecastView
  caseRange: CaseRangeView | null
  predictionVsMark: PredictionHitView
  focused?: boolean
  /**
   * Suffix that keeps `data-testid` unique when two surfaces mount the card.
   * Empty on the Financials tab so the long-standing ids stay stable.
   */
  idSuffix?: string
}>()

const sfx = computed(() => props.idSuffix ?? '')

/** Return the mark implies, in total and per-year terms, against the hurdle. */
const ret = computed(() => {
  const mf = props.forecast
  const spot = mf.spotUsed
  const target = mf.predictedPrice
  const total =
    mf.expectedReturn ?? (spot != null && target != null && spot > 0 ? target / spot - 1 : null)
  const annual = mf.annualizedReturn
  const hurdle = mf.costOfEquity
  const excess =
    mf.excessAnnualizedReturn ?? (annual != null && hurdle != null ? annual - hurdle : null)
  return {
    total,
    annual,
    hurdle,
    excess,
    // A target below the cost of equity is not a buy, however big the headline.
    verdict: excess == null ? null : excess > 0.02 ? 'pos' : excess < -0.02 ? 'neg' : 'flat',
  }
})

/** How much of the model's input set the filings actually supplied. */
const coverage = computed(() => {
  const seen = props.forecast.observedFeatureCount
  const total = props.forecast.featureCountTotal
  if (seen == null || total == null || total <= 0) return null
  const frac = seen / total
  return {
    seen,
    total,
    label: frac >= 0.75 ? 'High' : frac >= 0.5 ? 'Partial' : 'Thin',
    tone: frac >= 0.75 ? 'pos' : frac >= 0.5 ? 'flat' : 'neg',
  }
})

/** Where the price the mark is built on came from. Placeholders must be loud. */
const spotSource = computed(() => {
  switch (props.forecast.spotSource) {
    case 'live':
      return { label: 'Live mark', tone: 'pos' }
    case 'report':
      return { label: 'Filing mark', tone: 'flat' }
    case 'synthetic':
      return { label: 'Placeholder mark — not a live print', tone: 'neg' }
    default:
      return null
  }
})

/**
 * A per-year figure repeats the headline when the horizon is already a year,
 * so it is only worth the pixels on a longer or shorter look-through.
 */
const showAnnualised = computed(() => {
  const months = props.forecast.timeframeMonths
  if (ret.value.annual == null) return false
  return months == null || months < 11 || months > 13
})

/**
 * "Reached the predicted price" only reads as good news on an upside call.
 * On a markdown the same arithmetic means the downside has *not* played out,
 * which must not be painted green.
 */
const markVsTarget = computed(() => {
  const hit = props.predictionVsMark.hit
  const total = ret.value.total
  if (hit == null || total == null) return null
  const bullish = total >= 0
  if (hit) {
    return bullish
      ? { text: 'Mark has reached the predicted price', tone: 'pos' }
      : { text: 'Mark is still above the predicted price', tone: 'neg' }
  }
  return null
})

/**
 * True when the "x% to predicted" readout would just restate the implied
 * return — it only earns its place when the live mark has moved off the spot
 * the mark was built from.
 */
const restatesImpliedReturn = computed(() => {
  const remaining = props.predictionVsMark.remainingPct
  const total = ret.value.total
  if (remaining == null || total == null) return false
  return Math.abs(remaining / 100 - total) < 0.005
})

/** Percent from the live mark, so each case reads without mental arithmetic. */
function fromSpot(price: number | null): string | null {
  const spot = props.forecast.spotUsed
  if (price == null || spot == null || spot <= 0) return null
  return signedPct((price / spot - 1) * 100, 0)
}
</script>

<template>
  <article
    class="model-forecast-highlight"
    :class="{ focused: props.focused }"
    :data-testid="`model-forecast-highlight${sfx}`"
  >
    <div class="mf-head">
      <div>
        <div class="mf-kicker label">Internal research model</div>
        <h2 class="mf-title lab">What it should be</h2>
      </div>
      <div class="mf-head-tags">
        <span
          v-if="spotSource"
          class="mf-tag label"
          :class="spotSource.tone"
          :data-testid="`model-forecast-spot-source${sfx}`"
          >{{ spotSource.label }}</span
        >
        <span
          v-if="coverage"
          class="mf-tag label"
          :class="coverage.tone"
          :data-testid="`model-forecast-coverage${sfx}`"
          :title="`${coverage.seen} of ${coverage.total} model inputs present in the filings`"
          >{{ coverage.label }} coverage · {{ coverage.seen }}/{{ coverage.total }}</span
        >
        <span class="mf-tag mf-timeframe label">{{ props.forecast.timeframe || DASH }}</span>
      </div>
    </div>

    <p class="mf-note">
      Earnings the filings imply, faded toward a long-run rate, plus the multiple that growth
      deserves by the horizon — not last year's run-rate extrapolated. Distinct from Street
      consensus. Research only — not an ENTER authorization.
    </p>

    <div class="mf-metrics">
      <div class="mf-metric">
        <span class="mf-lbl label">Predicted price</span>
        <strong class="mf-val fig">{{
          formatModelPredictedPrice(props.forecast.predictedPrice)
        }}</strong>
        <span v-if="props.forecast.spotUsed != null" class="mf-sub dim">
          from {{ formatModelPredictedPrice(props.forecast.spotUsed) }}
        </span>
        <span
          v-if="ret.total != null"
          class="mf-sub"
          :class="ret.total >= 0 ? 'pos' : 'neg'"
          :data-testid="`model-forecast-implied-return${sfx}`"
        >
          {{ signedPct(ret.total * 100, 1) }} over {{ props.forecast.timeframe || 'the horizon'
          }}<template v-if="showAnnualised"
            >, {{ signedPct(ret.annual! * 100, 1) }} a year</template
          >
        </span>
        <span v-if="markVsTarget" class="mf-sub" :class="markVsTarget.tone">{{
          markVsTarget.text
        }}</span>
        <span
          v-else-if="
            props.predictionVsMark.hit === false &&
            props.predictionVsMark.remainingPct != null &&
            !restatesImpliedReturn
          "
          class="mf-sub dim"
          >{{ signedPct(props.predictionVsMark.remainingPct, 1) }} to predicted</span
        >
      </div>

      <div class="mf-metric">
        <span class="mf-lbl label">Return vs hurdle</span>
        <strong
          class="mf-val fig"
          :class="ret.verdict || ''"
          :data-testid="`model-forecast-excess${sfx}`"
          >{{ ret.excess != null ? signedPct(ret.excess * 100, 1) : DASH }}</strong
        >
        <span v-if="ret.hurdle != null" class="mf-sub dim">
          per year over a {{ pctFrac(ret.hurdle, 1) }} cost of equity
        </span>
      </div>

      <div class="mf-metric">
        <span class="mf-lbl label">Forecast score</span>
        <strong class="mf-val fig">{{
          formatModelForecastScore(props.forecast.forecastScore)
        }}</strong>
        <span class="mf-sub dim">0–100 · quality and return over the hurdle</span>
      </div>

      <div class="mf-metric">
        <span class="mf-lbl label">Growth capitalised</span>
        <strong class="mf-val fig">{{
          props.forecast.sustainableGrowth != null
            ? `${(props.forecast.sustainableGrowth * 100).toFixed(0)}%`
            : DASH
        }}</strong>
        <span v-if="props.forecast.lookthroughGrowth != null" class="mf-sub dim">
          shrunk from {{ (props.forecast.lookthroughGrowth * 100).toFixed(0) }}% observed, then
          faded to horizon
        </span>
      </div>

      <div class="mf-metric mf-metric-wide">
        <span class="mf-lbl label">Gearing up towards</span>
        <strong class="mf-val lab">{{ formatGearingUp(props.forecast.gearingUpTowards) }}</strong>
      </div>
    </div>

    <div class="mf-cases-head">
      <span class="mf-lbl label">Scenario band</span>
      <span class="mf-band-note">
        10th–90th percentile
        <template v-if="props.forecast.scenarioSigma != null">
          · {{ (props.forecast.scenarioSigma * 100).toFixed(0) }}% horizon vol
        </template>
      </span>
    </div>

    <div class="mf-cases" :data-testid="`model-forecast-cases${sfx}`">
      <div class="mf-case bear">
        <span class="mf-lbl label">Bear case</span>
        <strong class="mf-val fig">{{
          formatModelPredictedPrice(props.forecast.cases.bear.price)
        }}</strong>
        <span v-if="fromSpot(props.forecast.cases.bear.price)" class="mf-sub dim">
          {{ fromSpot(props.forecast.cases.bear.price) }} from mark
        </span>
        <p class="mf-thesis">{{ props.forecast.cases.bear.thesis || DASH }}</p>
      </div>
      <div class="mf-case base">
        <span class="mf-lbl label">Base · {{ props.forecast.timeframe || 'horizon' }}</span>
        <strong class="mf-val fig">{{
          formatModelPredictedPrice(props.forecast.cases.base.price)
        }}</strong>
        <span v-if="fromSpot(props.forecast.cases.base.price)" class="mf-sub dim">
          {{ fromSpot(props.forecast.cases.base.price) }} from mark
        </span>
        <p class="mf-thesis">{{ props.forecast.cases.base.thesis || DASH }}</p>
      </div>
      <div class="mf-case bull">
        <span class="mf-lbl label">Bull case</span>
        <strong class="mf-val fig">{{
          formatModelPredictedPrice(props.forecast.cases.bull.price)
        }}</strong>
        <span v-if="fromSpot(props.forecast.cases.bull.price)" class="mf-sub dim">
          {{ fromSpot(props.forecast.cases.bull.price) }} from mark
        </span>
        <p class="mf-thesis">{{ props.forecast.cases.bull.thesis || DASH }}</p>
      </div>
    </div>

    <div v-if="props.caseRange" class="mf-range" :data-testid="`model-forecast-range${sfx}`">
      <div class="mf-range-track">
        <span
          class="mf-range-span"
          :style="{ left: props.caseRange.spanLeft, width: props.caseRange.spanWidth }"
        />
        <span
          v-for="m in props.caseRange.marks"
          :key="`mark-${m.key}`"
          class="mf-range-mark"
          :class="m.key"
          :style="{ left: m.pct }"
          :title="m.title"
        />
      </div>
      <div class="mf-range-caption label">
        <span
          v-for="m in props.caseRange.marks"
          :key="`cap-${m.key}`"
          class="mf-range-cap"
          :class="m.key"
        >
          {{ m.label }} {{ formatModelPredictedPrice(m.price) }}
        </span>
      </div>
    </div>

    <div class="mf-factors">
      <span class="mf-lbl label">Factors</span>
      <ul v-if="props.forecast.factors.length" class="mf-factor-list">
        <li v-for="f in props.forecast.factors" :key="f.label" class="mf-factor">
          <span class="mf-factor-name">{{ f.label }}</span>
          <span class="mf-factor-val fig" :class="f.tone">{{ f.display }}</span>
        </li>
      </ul>
      <p v-else class="mf-thesis dim">{{ DASH }}</p>
    </div>
  </article>
</template>

<style scoped>
/* ---- Internal model forecast highlight ("what it should be") ------------- */
.model-forecast-highlight {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s4);
  margin-bottom: var(--s4);
  background: var(--phosphor-wash);
  border: 2px solid var(--phosphor);
  border-radius: var(--r-sm);
}

.model-forecast-highlight.focused {
  background: var(--phosphor-glow);
  outline: 1px solid var(--phosphor);
}

.mf-kicker {
  color: var(--phosphor);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-size: var(--t-tiny, 10px);
}

.mf-title {
  margin: 0;
  font-size: var(--t-fig);
  color: var(--ink);
}

/* Prose, not a chip: sentence case, wraps, no ellipsis. */
.mf-note {
  margin: 0;
  max-width: 78ch;
  font-family: var(--font-data);
  font-size: var(--t-tiny, 11px);
  line-height: 1.5;
  color: var(--ink-dim);
}

.mf-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: var(--s4);
  align-items: start;
}

.mf-metric-wide {
  grid-column: 1 / -1;
}

.mf-lbl {
  display: block;
  color: var(--ink-dim);
  margin-bottom: 4px;
}

.mf-val {
  font-size: var(--t-display);
  color: var(--phosphor);
}

/* Supporting lines are readable prose under a figure, so they wrap. */
.mf-sub {
  display: block;
  margin-top: 4px;
  font-family: var(--font-data);
  font-size: var(--t-tiny, 11px);
  line-height: 1.4;
  color: var(--ink-dim);
  white-space: normal;
  overflow: visible;
  text-overflow: clip;
}

.mf-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--s4);
}

.mf-timeframe {
  flex-shrink: 0;
  padding: 4px 8px;
  border: var(--hair) solid var(--phosphor);
  color: var(--phosphor);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.mf-cases {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s3);
}

.mf-case {
  padding: var(--s3);
  background: var(--void);
  border: var(--hair) solid var(--rule);
}

.mf-case.bear {
  border-color: var(--short);
}
.mf-case.base {
  border-color: var(--phosphor);
}
.mf-case.bull {
  border-color: var(--long);
}

.mf-case.bear .mf-val {
  color: var(--short);
}
.mf-case.bull .mf-val {
  color: var(--long);
}

.mf-range {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.mf-range-track {
  position: relative;
  height: 10px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
}

.mf-range-span {
  position: absolute;
  top: 0;
  height: 100%;
  background: color-mix(in srgb, var(--phosphor) 16%, transparent);
}

.mf-range-mark {
  position: absolute;
  top: -4px;
  width: 2px;
  height: 16px;
  transform: translateX(-50%);
  background: var(--ink);
}

.mf-range-mark.bear {
  background: var(--short);
}
.mf-range-mark.bull {
  background: var(--long);
}
.mf-range-mark.base {
  background: var(--phosphor);
  width: 3px;
}
.mf-range-mark.spot {
  background: var(--ink);
  width: 3px;
}

.mf-range-caption {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2) var(--s4);
  color: var(--ink-dim);
}

.mf-range-cap.bear {
  color: var(--short);
}
.mf-range-cap.bull {
  color: var(--long);
}
.mf-range-cap.base {
  color: var(--phosphor);
}
.mf-range-cap.spot {
  color: var(--ink);
}

.mf-thesis {
  margin: 6px 0 0;
  color: var(--ink-dim);
  font-size: var(--t-tiny, 11px);
  line-height: 1.4;
}

.mf-factors {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.mf-factor-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--s2) var(--s4);
}

.mf-factor {
  display: flex;
  justify-content: space-between;
  gap: var(--s3);
  border-bottom: var(--hair) solid var(--rule-faint);
  padding-bottom: 2px;
}

.mf-factor-name {
  color: var(--ink-dim);
}
.mf-factor-val.pos {
  color: var(--long);
}
.mf-factor-val.neg {
  color: var(--short);
}

@media (max-width: 720px) {
  .mf-cases {
    grid-template-columns: 1fr;
  }
}

/* ---- Provenance / coverage chips ---------------------------------------- */
.mf-head-tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-items: center;
  gap: var(--s2);
  flex-shrink: 0;
}

.mf-tag {
  padding: 4px 8px;
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  white-space: nowrap;
}

.mf-tag.pos {
  border-color: var(--long);
  color: var(--long);
}
.mf-tag.neg {
  border-color: var(--short);
  color: var(--short);
}

/* ---- Scenario band header ------------------------------------------------ */
.mf-cases-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--s3);
  flex-wrap: wrap;
  margin-bottom: calc(-1 * var(--s2));
}

.mf-cases-head .mf-lbl {
  margin-bottom: 0;
}

.mf-band-note {
  font-family: var(--font-data);
  font-size: var(--t-tiny, 11px);
  color: var(--ink-dim);
}

/* Headline figures carry the verdict tone (return vs hurdle). */
.mf-val.pos {
  color: var(--long);
}
.mf-val.neg {
  color: var(--short);
}
.mf-val.flat {
  color: var(--ink);
}

.mf-sub.pos {
  color: var(--long);
}
.mf-sub.neg {
  color: var(--short);
}

@media (max-width: 720px) {
  .mf-head {
    flex-direction: column;
  }
  .mf-head-tags {
    justify-content: flex-start;
  }
}
</style>
