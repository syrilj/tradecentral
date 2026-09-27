<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, type DecisionTreeBacktestPayload, type DecisionTreeMetrics } from '@/api'
import { useResource } from '@/composables/useResource'
import LoadingState from '@/components/LoadingState.vue'

const forceNext = ref(false)
const result = useResource<DecisionTreeBacktestPayload>(
  () => {
    const force = forceNext.value
    forceNext.value = false
    return api.decisionTreeBacktest({ force })
  },
  { immediate: true },
)

const payload = computed(() => result.data.value)
const baseline = computed(() => payload.value?.comparison.baseline ?? null)
const improved = computed(() => payload.value?.comparison.improved ?? null)
const focusRows = computed(() => payload.value?.focus.rows ?? [])
const promotionBlocked = computed(
  () => payload.value?.verdict !== 'IMPROVEMENT_DEMONSTRATED_ON_HOLDOUT',
)
const verdictLabel = computed(() => {
  if (!payload.value) return 'AUDIT PENDING'
  if (payload.value.verdict === 'IMPROVEMENT_DEMONSTRATED_ON_HOLDOUT') return 'HOLDOUT IMPROVED'
  if (payload.value.verdict === 'RISK_CONTROL_IMPROVED_EDGE_NOT_DEMONSTRATED') {
    return 'ABSTENTION WORKED · EDGE UNPROVEN'
  }
  return 'IMPROVEMENT NOT PROVEN'
})

async function rerun(): Promise<void> {
  forceNext.value = true
  await result.refresh()
}

function pct(value: number | null | undefined, digits = 1): string {
  return value == null ? '—' : `${(value * 100).toFixed(digits)}%`
}

function signed(value: number | null | undefined, suffix = ''): string {
  if (value == null) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}${suffix}`
}

function metricValue(metrics: DecisionTreeMetrics | null, key: keyof DecisionTreeMetrics): string {
  const value = metrics?.[key]
  if (key === 'accuracy' || key === 'balanced_accuracy' || key === 'coverage') {
    return pct(typeof value === 'number' ? value : null)
  }
  if (key === 'mean_net_return_bps') return signed(typeof value === 'number' ? value : null, ' bp')
  if (key === 'cumulative_net_return_pct') {
    return signed(typeof value === 'number' ? value : null, '%')
  }
  return value == null ? '—' : String(value)
}
</script>

<template>
  <section class="audit" data-density="compact" aria-labelledby="tree-audit-heading">
    <div class="audit-toolbar">
      <div>
        <span class="kicker fig">SEALED OOS · NEXT SESSION · DAILY CART</span>
        <h2 id="tree-audit-heading">Did the decision tree earn trust last week?</h2>
      </div>
      <button type="button" :disabled="result.loading.value" @click="rerun">
        {{ result.loading.value ? 'RUNNING…' : 'RERUN SEALED AUDIT' }}
      </button>
    </div>

    <LoadingState v-if="result.loading.value && !payload" label="Training on pre-holdout bars…" />
    <p v-else-if="result.error.value" class="fault" role="alert">{{ result.error.value }}</p>

    <template v-if="payload">
      <div class="verdict" :class="{ blocked: promotionBlocked }">
        <div>
          <span class="fig">PROMOTION GATE</span>
          <strong>{{ verdictLabel }}</strong>
        </div>
        <p>
          {{ payload.protocol.warning }} The improved model was selected and calibrated before
          {{ payload.window.holdout_start }}; the test week was not reused for fitting.
        </p>
        <span class="gate fig">{{
          promotionBlocked ? 'LIVE CAPITAL · BLOCKED' : 'SHADOW ONLY'
        }}</span>
      </div>

      <div class="stat-strip">
        <article>
          <span class="fig">HOLDOUT</span>
          <strong>{{ payload.window.holdout_start }} → {{ payload.window.holdout_end }}</strong>
          <small>{{ payload.window.sessions }} actual sessions</small>
        </article>
        <article>
          <span class="fig">UNIVERSE</span>
          <strong
            >{{ payload.universe.symbols }} symbols ·
            {{ payload.universe.holdout_rows }} rows</strong
          >
          <small>{{ payload.universe.training_rows.toLocaleString() }} training rows</small>
        </article>
        <article>
          <span class="fig">FILL RULE</span>
          <strong>T+1 OPEN → CLOSE</strong>
          <small>{{ payload.protocol.round_trip_cost_bps }} bp round trip</small>
        </article>
        <article>
          <span class="fig">CONFIDENCE GATE</span>
          <strong>≥ {{ pct(payload.model.confidence_threshold, 0) }}</strong>
          <small>OOF isotonic · otherwise abstain</small>
        </article>
      </div>

      <section class="comparison" aria-label="Baseline and improved model comparison">
        <header>
          <span class="fig">HOLDOUT COMPARISON</span>
          <p>
            Headline accuracy is shown beside coverage and net return so abstention cannot
            masquerade as skill.
          </p>
        </header>
        <div class="comparison-table" role="table">
          <div class="tr th" role="row">
            <span role="columnheader">MODEL</span><span role="columnheader">TRADES</span>
            <span role="columnheader">COVERAGE</span><span role="columnheader">BAL. ACC.</span>
            <span role="columnheader">AVG NET</span><span role="columnheader">BARRIER</span>
          </div>
          <div class="tr" role="row">
            <strong role="cell">BASELINE · ALWAYS CALL</strong>
            <span role="cell">{{ baseline?.trades ?? '—' }}</span>
            <span role="cell">{{ metricValue(baseline, 'coverage') }}</span>
            <span role="cell">{{ metricValue(baseline, 'balanced_accuracy') }}</span>
            <span role="cell" :class="{ neg: (baseline?.mean_net_return_bps ?? 0) < 0 }">
              {{ metricValue(baseline, 'mean_net_return_bps') }}
            </span>
            <span role="cell">NONE</span>
          </div>
          <div class="tr improved" role="row">
            <strong role="cell">CALIBRATED · SELECTIVE</strong>
            <span role="cell">{{ improved?.trades ?? '—' }}</span>
            <span role="cell">{{ metricValue(improved, 'coverage') }}</span>
            <span role="cell">{{ metricValue(improved, 'balanced_accuracy') }}</span>
            <span role="cell">{{ metricValue(improved, 'mean_net_return_bps') }}</span>
            <span role="cell">{{ pct(payload.model.confidence_threshold, 0) }}</span>
          </div>
        </div>
      </section>

      <div class="lower-grid">
        <section class="spcx-card">
          <header>
            <div>
              <span class="fig">FOCUS TAPE · SPCX</span>
              <h3>The SELL calls were not confident enough to trade</h3>
            </div>
            <span class="focus-count fig"
              >{{ focusRows.filter((row) => row.active).length }} /
              {{ focusRows.length }} ACTIVE</span
            >
          </header>
          <div class="tape" role="table" aria-label="SPCX last-week decisions">
            <div class="tape-row tape-head" role="row">
              <span>SESSION</span><span>CALL</span><span>CONF.</span><span>ACTUAL</span
              ><span>RESULT</span>
            </div>
            <div v-for="row in focusRows" :key="row.session_date" class="tape-row" role="row">
              <time :datetime="row.session_date">{{ row.session_date.slice(5) }}</time>
              <span class="call" :class="row.action">{{
                row.active ? row.action.toUpperCase() : 'ABSTAIN'
              }}</span>
              <span>{{ pct(row.confidence, 1) }}</span>
              <span :class="row.actual_return_pct >= 0 ? 'pos' : 'neg'">
                {{ signed(row.actual_return_pct, '%') }}
              </span>
              <span :class="row.active ? (row.correct ? 'pos' : 'neg') : 'muted'">
                {{ row.active ? (row.correct ? 'HIT' : 'MISS') : 'NO TRADE' }}
              </span>
            </div>
          </div>
          <p class="spcx-note">
            The tree’s SPCX leaf estimates sat near 50/50. On 09-16, the old forced SELL would have
            faced a +{{
              focusRows
                .find((row) => row.session_date === '2026-09-16')
                ?.actual_return_pct.toFixed(2) ?? '—'
            }}% open-to-close bounce. The corrected policy says “directional lean exists, confidence
            does not.”
          </p>
        </section>

        <section class="model-card">
          <header>
            <span class="fig">MODEL CARD</span>
            <strong>CAUSAL CART · DEPTH {{ payload.model.parameters.max_depth }}</strong>
          </header>
          <dl>
            <div>
              <dt>Min leaf</dt>
              <dd>{{ payload.model.parameters.min_leaf }}</dd>
            </div>
            <div>
              <dt>Features</dt>
              <dd>{{ payload.model.feature_count }}</dd>
            </div>
            <div>
              <dt>Selection</dt>
              <dd>Expanding date folds</dd>
            </div>
            <div>
              <dt>Leakage</dt>
              <dd>{{ payload.protocol.holdout_used_for_training ? 'FAILED' : 'NONE DETECTED' }}</dd>
            </div>
          </dl>
          <div class="importance">
            <div v-for="feature in payload.model.top_importance" :key="feature.feature">
              <span>{{ feature.feature.replace(/_/g, ' ') }}</span>
              <span class="bar"><i :style="{ width: `${feature.importance * 100}%` }" /></span>
              <strong>{{ pct(feature.importance, 0) }}</strong>
            </div>
          </div>
        </section>
      </div>

      <section class="daily-card">
        <header>
          <span class="fig">SESSION LEDGER</span><span class="fig">ACTUAL HOLDOUT ONLY</span>
        </header>
        <div class="daily-grid">
          <article v-for="day in payload.daily" :key="day.date">
            <time :datetime="day.date">{{ day.date.slice(5) }}</time>
            <strong>{{ day.trades }} / {{ day.observations }}</strong>
            <small>trades / reads</small>
            <span>{{ day.accuracy == null ? 'ABSTAINED' : `${pct(day.accuracy)} HIT` }}</span>
          </article>
        </div>
      </section>

      <footer>
        Research only · no order authorization · source: local completed daily parquet · cache
        {{ payload.cache?.hit ? `${payload.cache.age_seconds}s` : 'fresh' }}
      </footer>
    </template>
  </section>
</template>

<style scoped>
.audit {
  display: grid;
  gap: var(--density-gap, var(--s3));
}
.audit-toolbar,
.verdict,
.comparison header,
.spcx-card header,
.model-card header,
.daily-card header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
}
.audit-toolbar h2 {
  margin: 4px 0 0;
  font-size: clamp(1.5rem, 2.5vw, 2.6rem);
  letter-spacing: -0.035em;
}
.kicker {
  color: var(--phosphor);
  letter-spacing: 0.12em;
  font-size: var(--t-nano);
}
.audit-toolbar button {
  min-height: 36px;
  padding: 0 14px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-hi);
  color: var(--ink);
  font: 700 var(--t-nano) var(--font-data);
  cursor: pointer;
}
.verdict {
  border: var(--hair) solid var(--long);
  background: color-mix(in srgb, var(--long) 7%, var(--panel));
  padding: var(--s3);
}
.verdict.blocked {
  border-color: var(--short);
  background: color-mix(in srgb, var(--short) 7%, var(--panel));
}
.verdict div {
  display: grid;
  gap: 4px;
  min-width: 260px;
}
.verdict strong {
  font: 800 var(--t-small) var(--font-data);
}
.verdict p {
  margin: 0;
  color: var(--ink-dim);
  max-width: 760px;
}
.gate {
  color: var(--short);
  white-space: nowrap;
}
.stat-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: var(--hair) solid var(--rule);
}
.stat-strip article {
  padding: var(--s2) var(--s3);
  display: grid;
  gap: 4px;
  border-right: var(--hair) solid var(--rule);
}
.stat-strip article:last-child {
  border-right: 0;
}
.stat-strip span,
.comparison .th,
.tape-head,
.daily-card header {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  letter-spacing: 0.09em;
}
.stat-strip strong {
  font: 750 var(--t-small) var(--font-data);
}
.stat-strip small {
  color: var(--ink-faint);
}
.comparison,
.spcx-card,
.model-card,
.daily-card {
  border: var(--hair) solid var(--rule);
  background: var(--panel);
}
.comparison header,
.spcx-card header,
.model-card header,
.daily-card header {
  padding: var(--s2) var(--s3);
  border-bottom: var(--hair) solid var(--rule);
}
.comparison header p {
  margin: 0;
  color: var(--ink-faint);
  font-size: var(--t-micro);
}
.tr {
  display: grid;
  grid-template-columns: 1.8fr repeat(5, minmax(80px, 1fr));
  min-height: var(--density-row-height, 32px);
  align-items: center;
  border-top: var(--hair) solid var(--rule-faint);
}
.tr:first-child {
  border-top: 0;
}
.tr > * {
  padding: 7px 10px;
  border-right: var(--hair) solid var(--rule-faint);
  font: var(--t-micro) var(--font-data);
}
.tr > *:last-child {
  border-right: 0;
}
.tr.improved {
  background: color-mix(in srgb, var(--phosphor) 6%, transparent);
}
.lower-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(300px, 0.75fr);
  gap: var(--s3);
}
.spcx-card h3 {
  margin: 3px 0 0;
  font-size: 1rem;
}
.focus-count {
  color: var(--phosphor);
}
.tape-row {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr 0.8fr 1fr 1fr;
  min-height: var(--density-row-height, 32px);
  align-items: center;
  border-top: var(--hair) solid var(--rule-faint);
}
.tape-row > * {
  padding: 6px 10px;
  font: var(--t-micro) var(--font-data);
}
.call.buy,
.pos {
  color: var(--long);
}
.call.sell,
.neg {
  color: var(--short);
}
.muted {
  color: var(--ink-faint);
}
.spcx-note {
  margin: 0;
  padding: var(--s3);
  border-top: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  line-height: 1.55;
}
.model-card dl {
  margin: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
}
.model-card dl div {
  padding: var(--s2);
  border-right: var(--hair) solid var(--rule-faint);
  border-bottom: var(--hair) solid var(--rule-faint);
}
.model-card dt {
  color: var(--ink-faint);
  font-size: var(--t-nano);
}
.model-card dd {
  margin: 4px 0 0;
  font: 700 var(--t-micro) var(--font-data);
}
.importance {
  padding: var(--s2);
  display: grid;
  gap: 8px;
}
.importance > div {
  display: grid;
  grid-template-columns: 1fr 90px 36px;
  gap: 8px;
  align-items: center;
  font-size: var(--t-nano);
}
.bar {
  height: 4px;
  background: var(--panel-hi);
}
.bar i {
  display: block;
  height: 100%;
  background: var(--phosphor);
}
.daily-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
}
.daily-grid article {
  padding: var(--s2);
  display: grid;
  gap: 3px;
  border-right: var(--hair) solid var(--rule-faint);
}
.daily-grid article:last-child {
  border-right: 0;
}
.daily-grid strong {
  font: 750 1.2rem var(--font-data);
}
.daily-grid small,
.daily-grid span,
footer {
  color: var(--ink-faint);
  font-size: var(--t-nano);
}
.fault {
  padding: var(--s3);
  border-left: 3px solid var(--short);
  background: var(--put-wash);
  color: var(--short);
}
footer {
  text-align: right;
  padding: var(--s1) 0;
}
@media (max-width: 900px) {
  .stat-strip {
    grid-template-columns: 1fr 1fr;
  }
  .stat-strip article:nth-child(2) {
    border-right: 0;
  }
  .lower-grid {
    grid-template-columns: 1fr;
  }
  .tr {
    grid-template-columns: 1.6fr repeat(3, 1fr);
  }
  .tr > *:nth-child(5),
  .tr > *:nth-child(6) {
    display: none;
  }
}
@media (max-width: 600px) {
  .audit-toolbar,
  .verdict {
    align-items: flex-start;
    flex-direction: column;
  }
  .stat-strip {
    grid-template-columns: 1fr;
  }
  .stat-strip article {
    border-right: 0;
  }
  .daily-grid {
    grid-template-columns: 1fr;
  }
  .daily-grid article {
    min-height: 44px;
    border-right: 0;
    border-bottom: var(--hair) solid var(--rule-faint);
    grid-template-columns: 1fr auto auto;
    align-items: center;
  }
  .tape-row {
    grid-template-columns: 1fr 0.8fr 0.8fr 1fr;
    min-height: 44px;
  }
  .tape-row > *:last-child {
    display: none;
  }
}
</style>
