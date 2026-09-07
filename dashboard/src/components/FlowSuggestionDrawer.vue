<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, type FlowSuggestion, type LiveOpportunityRow, type MarketClock } from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import { DASH, num, shortDate, usd } from '@/format'
import {
  freshnessLabel,
  formatSetupLevel,
  formatSupportLevels,
  formatTakeProfitZones,
  levelSourceLabel,
  missingSourcesCopy,
  qlibAlignmentLabel,
  setupCalculatorQuery,
  setupHeadlineInvalidation,
  suggestionStabilityCopy,
  suggestedRightLabel,
  suggestedRightTokenClass,
} from '@/suggestDisplay'
import LoadingState from '@/components/LoadingState.vue'
import SetupRiskPanel from '@/components/SetupRiskPanel.vue'

const props = defineProps<{ symbol: string }>()
const emit = defineEmits<{ close: [] }>()
const sharedMarketClock = inject<Resource<MarketClock> | null>('marketClock', null)

const POLL_MS = 15_000
const forceNext = ref(true)
const feed = useResource(
  async () => {
    const force = forceNext.value
    forceNext.value = false
    return api.flowSuggestions({ symbol: props.symbol, force })
  },
  { intervalMs: POLL_MS, enabled: () => Boolean(props.symbol) },
)

watch(
  () => props.symbol,
  (newSym, oldSym) => {
    if (props.symbol && newSym !== oldSym) {
      forceNext.value = true
      void feed.refresh({ clear: true })
    }
  },
)

const row = computed<LiveOpportunityRow | null>(
  () =>
    feed.data.value?.rows?.find((item) => item.symbol === props.symbol) ??
    feed.data.value?.rows?.[0] ??
    null,
)
const suggestion = computed<FlowSuggestion | null>(() => row.value?.suggestion ?? null)
const planningMode = computed(() =>
  Boolean(
    sharedMarketClock?.data.value?.market_session &&
    sharedMarketClock.data.value.market_session !== 'regular',
  ),
)
const live = computed(() =>
  Boolean(row.value?.freshness?.pass && !feed.error.value && !planningMode.value),
)
const invalidationMark = computed(() =>
  setupHeadlineInvalidation({
    invalidation: suggestion.value?.invalidation,
    invalidationSource: suggestion.value?.invalidation_source,
    planInvalidation: suggestion.value?.plan_invalidation,
    planInvalidationSource: suggestion.value?.plan_invalidation_source,
  }),
)
const takeProfitCopy = computed(() => {
  const zones = formatTakeProfitZones(suggestion.value?.take_profit_zones)
  if (zones !== DASH) return zones
  return formatSetupLevel(suggestion.value?.plan_target, suggestion.value?.plan_target_source)
})
const dataState = computed(() => {
  if (live.value) return 'LIVE INPUTS'
  if (planningMode.value) return 'CLOSED · PLANNING'
  return 'VERIFY INPUTS'
})

async function refreshLive(): Promise<void> {
  forceNext.value = true
  try {
    await feed.refresh()
  } finally {
    forceNext.value = false
  }
}

function onKey(event: KeyboardEvent): void {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => document.addEventListener('keydown', onKey))
onUnmounted(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div class="drawer-layer" role="presentation" @mousedown.self="emit('close')">
      <aside
        class="setup-drawer ticked"
        role="dialog"
        aria-modal="true"
        :aria-label="`${symbol} live setup`"
      >
        <header class="drawer-head">
          <div>
            <span class="label eyebrow">Flow → live options setup</span>
            <div class="symbol-line">
              <h2 class="fig">{{ symbol }}</h2>
              <span class="live-state label" :class="{ live, planning: planningMode }"
                ><i />{{ dataState }}</span
              >
            </div>
          </div>
          <div class="head-actions">
            <button
              class="refresh label"
              type="button"
              :disabled="feed.loading.value"
              @click="void refreshLive()"
            >
              {{ feed.loading.value ? 'UPDATING…' : 'REFRESH' }}
            </button>
            <button class="close" type="button" aria-label="Close setup" @click="emit('close')">
              ×
            </button>
          </div>
        </header>

        <div class="drawer-scroll">
          <LoadingState
            v-if="feed.loading.value && !row"
            label="Fetching the selected chain and recombining Flow…"
          />
          <div v-else-if="feed.error.value && !row" class="state error">
            <strong>Setup unavailable</strong>
            <p>{{ feed.error.value }}</p>
            <button type="button" class="refresh label" @click="void refreshLive()">
              TRY AGAIN
            </button>
          </div>
          <div v-else-if="!row || !suggestion" class="state">
            <strong>No setup returned for {{ symbol }}</strong>
            <p>
              {{
                feed.data.value?.reason || 'The selected symbol has no usable options evidence yet.'
              }}
            </p>
          </div>

          <template v-else>
            <section class="verdict" :class="suggestedRightTokenClass(suggestion.right)">
              <div>
                <span class="label">Suggested right</span>
                <strong>{{ suggestedRightLabel(suggestion.right) }}</strong>
                <p>
                  {{
                    suggestion.reason ||
                    `${row.playbook?.structure_label || 'Defined-risk structure'} from ${row.playbook?.direction_source || 'measured context'}.`
                  }}
                </p>
                <small
                  v-if="suggestion.bias_right && !suggestion.bias_confirmed"
                  class="bias-note label"
                >
                  UNSIGNED {{ suggestion.bias_right.toUpperCase() }} BIAS · PAPER CANDIDATE · SIZING
                  LOCKED
                </small>
              </div>
              <div class="verdict-meta">
                <span class="label" :class="{ paper: suggestion.setup_tier === 'paper' }">
                  {{
                    suggestion.paper_actionable
                      ? 'PAPER ACTION · UNSIZED'
                      : suggestion.setup_tier === 'paper'
                        ? 'PAPER · WAITING'
                        : String(suggestion.status).replaceAll('_', ' ')
                  }}
                </span>
                <span class="label">{{
                  planningMode && !row.freshness?.pass
                    ? 'CLOSED SNAPSHOT'
                    : freshnessLabel(row.freshness?.status, row.freshness?.pass)
                }}</span>
                <span class="label">{{ suggestionStabilityCopy(suggestion) }}</span>
              </div>
            </section>

            <section v-if="suggestion.paper_actionable" class="paper-action">
              <span class="label">Paper action</span>
              <strong>{{ suggestion.paper_action?.replaceAll('_', ' ') }} {{ symbol }}</strong>
              <p>
                Use the displayed contract and GEX levels for forward paper tracking only. Live
                sizing and execution remain locked.
              </p>
            </section>

            <section
              v-if="suggestion.contract_plan"
              class="exact-contract"
              :class="suggestedRightTokenClass(suggestion.right)"
            >
              <div class="contract-command">
                <span class="label">Specific contract plan</span>
                <strong>
                  {{ suggestion.contract_plan.action.replaceAll('_', ' ') }} ·
                  {{ symbol }}
                  {{ suggestion.contract_plan.expiry || 'EXPIRY NOT SUPPLIED' }}
                  {{
                    suggestion.contract_plan.strike == null
                      ? 'STRIKE NOT SUPPLIED'
                      : `${usd(suggestion.contract_plan.strike, 0)} ${suggestion.contract_plan.right.toUpperCase()}`
                  }}
                </strong>
                <p>{{ suggestion.contract_plan.selection_method }}</p>
              </div>
              <div class="contract-price">
                <span class="label">{{
                  suggestion.contract_plan.quote_reference_only
                    ? 'Delayed midpoint'
                    : 'Planning limit'
                }}</span>
                <strong class="fig">{{
                  suggestion.contract_plan.quote_reference_only &&
                  suggestion.contract_plan.midpoint != null
                    ? usd(suggestion.contract_plan.midpoint, 2)
                    : suggestion.contract_plan.sizing_debit == null
                      ? 'QUOTE REQUIRED'
                      : usd(suggestion.contract_plan.sizing_debit, 2)
                }}</strong>
                <small>{{ suggestion.contract_plan.contract_stage.replaceAll('_', ' ') }}</small>
              </div>
            </section>

            <section
              class="completeness"
              :class="{ complete: suggestion.risk_levels_complete, ready: row.live_ready }"
              aria-label="Setup completeness"
            >
              <span class="label">{{
                suggestion.risk_levels_complete
                  ? row.live_ready
                    ? 'READY'
                    : 'LEVELS COMPLETE · NOT LIVE READY'
                  : 'LEVELS INCOMPLETE'
              }}</span>
              <strong>{{ row.confidence?.band || 'UNCALIBRATED' }}</strong>
              <p>
                {{
                  suggestion.risk_levels_complete
                    ? 'Strike, supports, invalidation, and take profit are measured.'
                    : `Missing: ${suggestion.risk_missing_fields?.length ? suggestion.risk_missing_fields.join(', ') : 'not supplied'}.`
                }}
              </p>
              <p v-if="suggestion.missing_sources?.length">
                Sources unmeasured: {{ missingSourcesCopy(suggestion.missing_sources) }}
              </p>
            </section>

            <section class="levels" aria-label="Setup levels">
              <article>
                <span class="label">Strike</span>
                <strong class="fig">{{
                  formatSetupLevel(
                    suggestion.strike ?? suggestion.contract_plan?.strike,
                    suggestion.strike_source,
                  )
                }}</strong>
                <small>{{
                  suggestion.strike_source
                    ? levelSourceLabel(suggestion.strike_source)
                    : 'not supplied'
                }}</small>
              </article>
              <article>
                <span class="label">Supports</span>
                <strong class="fig">{{ formatSupportLevels(suggestion.supports) }}</strong>
                <small>{{
                  suggestion.supports?.length ? 'Watch these supports' : 'not supplied'
                }}</small>
              </article>
              <article>
                <span class="label">Invalidation</span>
                <strong class="fig">{{
                  invalidationMark.price == null ? DASH : usd(invalidationMark.price, 2)
                }}</strong>
                <small>{{
                  invalidationMark.source
                    ? levelSourceLabel(invalidationMark.source)
                    : 'not supplied'
                }}</small>
              </article>
              <article class="target">
                <span class="label">Take profit zones</span>
                <strong class="fig">{{ takeProfitCopy }}</strong>
                <small>{{
                  suggestion.take_profit_zones?.length
                    ? 'Labeled zones, not a blend'
                    : 'not supplied'
                }}</small>
              </article>
            </section>

            <section class="evidence-grid">
              <article>
                <span class="label">Direction source</span>
                <strong>{{
                  suggestion.direction_source === 'activity_lean'
                    ? 'Activity planning bias'
                    : row.playbook?.direction_source || DASH
                }}</strong>
                <small>{{
                  suggestion.evidence_kind === 'activity_lean'
                    ? 'Unsigned activity · planning only'
                    : 'Call/put identity never sets direction'
                }}</small>
              </article>
              <article>
                <span class="label">Qlib alignment</span>
                <strong>{{ qlibAlignmentLabel(suggestion.qlib.alignment) }}</strong>
                <small>{{
                  suggestion.qlib.measured
                    ? `Rank ${suggestion.qlib.rank ?? DASH} / ${suggestion.qlib.n_symbols ?? DASH}`
                    : 'No published score for this symbol'
                }}</small>
              </article>
              <article>
                <span class="label">Spread gate</span>
                <strong>{{
                  row.spread_pct == null ? DASH : `${num(row.spread_pct * 100, 1)}%`
                }}</strong>
                <small>{{
                  row.costs?.spread_gate_pass
                    ? 'Within configured maximum'
                    : 'Fails or is unmeasured'
                }}</small>
              </article>
              <article>
                <span class="label">Expiry / OI</span>
                <strong>{{ row.playbook?.expiry || DASH }}</strong>
                <small>{{
                  row.open_interest == null
                    ? 'OI unmeasured'
                    : `${num(row.open_interest, 0)} open interest`
                }}</small>
              </article>
            </section>

            <section v-if="suggestion.contract_plan" class="contract-plan">
              <header>
                <div>
                  <span class="label">Contract quote & risk map</span>
                  <strong class="fig">
                    {{ suggestion.contract_plan.expiry || DASH }} ·
                    {{ suggestion.contract_plan.right.toUpperCase() }}
                    {{
                      suggestion.contract_plan.strike == null
                        ? DASH
                        : usd(suggestion.contract_plan.strike, 0)
                    }}
                  </strong>
                </div>
                <span class="reference-chip label">{{
                  suggestion.contract_plan.quote_status.replaceAll('_', ' ')
                }}</span>
              </header>
              <dl class="quote-grid">
                <div>
                  <dt class="label">
                    {{ suggestion.contract_plan.quote_reference_only ? 'Delayed bid' : 'Bid' }}
                  </dt>
                  <dd class="fig">
                    {{
                      suggestion.contract_plan.bid == null
                        ? 'Not supplied'
                        : usd(suggestion.contract_plan.bid, 2)
                    }}
                  </dd>
                </div>
                <div>
                  <dt class="label">
                    {{
                      suggestion.contract_plan.quote_reference_only
                        ? 'Delayed midpoint'
                        : 'Midpoint'
                    }}
                  </dt>
                  <dd class="fig">
                    {{
                      suggestion.contract_plan.midpoint == null
                        ? 'Not supplied'
                        : usd(suggestion.contract_plan.midpoint, 2)
                    }}
                  </dd>
                </div>
                <div>
                  <dt class="label">
                    {{ suggestion.contract_plan.quote_reference_only ? 'Delayed ask' : 'Ask' }}
                  </dt>
                  <dd class="fig">
                    {{
                      suggestion.contract_plan.ask == null
                        ? 'Not supplied'
                        : usd(suggestion.contract_plan.ask, 2)
                    }}
                  </dd>
                </div>
                <div>
                  <dt class="label">Spread</dt>
                  <dd class="fig">
                    {{
                      suggestion.contract_plan.spread_pct == null
                        ? 'Not supplied'
                        : `${num(suggestion.contract_plan.spread_pct * 100, 1)}%`
                    }}
                  </dd>
                </div>
                <div>
                  <dt class="label">Volume</dt>
                  <dd class="fig">
                    {{
                      suggestion.contract_plan.volume == null
                        ? 'Not supplied'
                        : num(suggestion.contract_plan.volume, 0)
                    }}
                  </dd>
                </div>
                <div>
                  <dt class="label">Open interest</dt>
                  <dd class="fig">
                    {{
                      suggestion.contract_plan.open_interest == null
                        ? 'Not supplied'
                        : num(suggestion.contract_plan.open_interest, 0)
                    }}
                  </dd>
                </div>
                <div>
                  <dt class="label">IV / Delta</dt>
                  <dd class="fig">
                    {{
                      suggestion.contract_plan.implied_volatility == null
                        ? 'IV not supplied'
                        : `${num(suggestion.contract_plan.implied_volatility * 100, 1)}% IV`
                    }}
                    ·
                    {{
                      suggestion.contract_plan.delta == null
                        ? 'Δ not supplied'
                        : `Δ ${num(suggestion.contract_plan.delta, 2)}`
                    }}
                  </dd>
                </div>
                <div>
                  <dt class="label">Quote observed</dt>
                  <dd class="fig">
                    {{
                      suggestion.contract_plan.observed_at
                        ? shortDate(suggestion.contract_plan.observed_at)
                        : 'Timestamp not supplied'
                    }}
                  </dd>
                </div>
              </dl>
              <dl class="risk-map">
                <div>
                  <dt class="label">Max loss / 1 contract</dt>
                  <dd class="fig">
                    {{
                      suggestion.contract_plan.reference_max_loss == null
                        ? 'Debit required'
                        : usd(suggestion.contract_plan.reference_max_loss, 0)
                    }}
                  </dd>
                </div>
                <div>
                  <dt class="label">Take-profit reference</dt>
                  <dd class="fig">
                    {{
                      suggestion.contract_plan.take_profit_debit == null
                        ? 'Debit required'
                        : usd(suggestion.contract_plan.take_profit_debit, 2)
                    }}
                  </dd>
                  <small>Rule: +50% premium; not a forecast</small>
                </div>
                <div>
                  <dt class="label">Review / cut reference</dt>
                  <dd class="fig">
                    {{
                      suggestion.contract_plan.review_exit_debit == null
                        ? 'Debit required'
                        : usd(suggestion.contract_plan.review_exit_debit, 2)
                    }}
                  </dd>
                  <small>Rule: −50% premium or underlying invalidation</small>
                </div>
              </dl>
              <p v-if="suggestion.contract_plan.missing_fields.length" class="missing-data">
                Provider did not supply: {{ suggestion.contract_plan.missing_fields.join(', ') }}.
              </p>
              <p v-if="suggestion.contract_plan.quote_reference_only" class="missing-data">
                {{ suggestion.contract_plan.quote_source?.replaceAll('_', ' ') }} · paper reference
                only · never sizing-eligible.
              </p>
              <ul
                v-if="suggestion.contract_plan.rejection_reasons.length"
                class="contract-rejections"
              >
                <li v-for="item in suggestion.contract_plan.rejection_reasons" :key="item">
                  {{ item }}
                </li>
              </ul>
              <p>{{ suggestion.contract_plan.note }}</p>
            </section>

            <details v-if="suggestion.blockers.length || suggestion.warnings.length" class="checks">
              <summary class="label">
                Why live entry is not ready ·
                {{ suggestion.blockers.length + suggestion.warnings.length }} checks
              </summary>
              <ul>
                <li v-for="item in suggestion.blockers" :key="`b-${item}`">{{ item }}</li>
                <li v-for="item in suggestion.warnings" :key="`w-${item}`">{{ item }}</li>
              </ul>
            </details>

            <SetupRiskPanel
              :key="row.symbol"
              :risk="row.playbook?.risk"
              :setup-status="suggestion.status"
              :reference-debit="suggestion.contract_plan?.sizing_debit"
              :reference-label="
                suggestion.contract_plan?.sizing_eligible
                  ? 'Stable two-sided chain midpoint'
                  : 'Sizing locked until quote, liquidity, stability, and setup gates pass'
              "
            />

            <footer class="drawer-foot">
              <div class="links">
                <RouterLink :to="{ name: 'options', query: { symbol } }" class="primary-link label"
                  >OPEN LIVE CHAIN →</RouterLink
                >
                <RouterLink
                  :to="{ name: 'suggest', query: { symbol } }"
                  class="secondary-link label"
                  >FULL SETUPS BOARD</RouterLink
                >
                <RouterLink
                  :to="{
                    name: 'calculator',
                    query: setupCalculatorQuery({
                      symbol,
                      right: suggestion.right,
                      spot: suggestion.spot,
                      strike: suggestion.contract_plan?.strike,
                      dte: suggestion.contract_plan?.dte,
                      vol:
                        suggestion.contract_plan?.implied_volatility ??
                        suggestion.contract_plan?.play?.vol,
                      premium:
                        suggestion.contract_plan?.reference_debit ??
                        suggestion.contract_plan?.play?.premium,
                    }),
                  }"
                  class="secondary-link label"
                  >PLAY CALCULATOR</RouterLink
                >
              </div>
              <span class="label"
                >POLL 15S ·
                {{
                  feed.data.value?.asof_utc
                    ? `AS OF ${shortDate(feed.data.value.asof_utc)}`
                    : 'AWAITING ASOF'
                }}</span
              >
            </footer>
          </template>
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.drawer-layer {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  display: flex;
  justify-content: flex-end;
  background: color-mix(in srgb, var(--void) 82%, transparent);
}

/* Floating overlay chrome — this sheet genuinely floats over content, so it
   takes true Liquid Glass: heavy optics, specular edge, deep shadow. */
.setup-drawer {
  width: min(760px, calc(100vw - 72px));
  height: 100%;
  border-left: var(--hair) solid var(--glass-border-hi);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.035), rgba(255, 255, 255, 0) 140px),
    var(--glass-overlay);
  backdrop-filter: var(--chrome-optics-xl);
  -webkit-backdrop-filter: var(--chrome-optics-xl);
  box-shadow:
    var(--glass-shadow-drawer),
    inset 1px 0 0 rgba(255, 255, 255, 0.06);
  animation: drawer-in var(--dur) var(--ease-out) both;
}

@media (prefers-reduced-transparency: reduce) {
  .setup-drawer {
    background: var(--void-lift);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

@keyframes drawer-in {
  from {
    transform: translateX(28px);
    opacity: 0;
  }
  to {
    transform: none;
    opacity: 1;
  }
}

.drawer-head {
  height: 84px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s4);
  padding: var(--s4) var(--s5);
  border-bottom: var(--hair) solid var(--rule-hi);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0));
}
.eyebrow {
  color: var(--phosphor);
}
.symbol-line {
  display: flex;
  align-items: center;
  gap: var(--s3);
  margin-top: 4px;
}
.symbol-line h2 {
  color: var(--ink);
  font-size: var(--t-fig);
}
.live-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--warn);
}
.live-state i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}
.live-state.live {
  color: var(--phosphor);
}
.live-state.planning {
  color: var(--call-hi);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: var(--s2);
}
.refresh {
  min-height: 30px;
  padding: 6px 14px;
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  border-radius: var(--r-capsule);
}
.refresh:disabled {
  opacity: 0.55;
  cursor: wait;
}
.close {
  width: 32px;
  height: 32px;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule-hi);
  border-radius: 50%;
  font-size: 22px;
  line-height: 1;
}
.close:hover {
  color: var(--ink);
  border-color: var(--ink-faint);
}

.drawer-scroll {
  height: calc(100% - 84px);
  overflow-y: auto;
  padding: var(--s4);
}
.drawer-scroll > * + * {
  margin-top: var(--s3);
}

.state {
  padding: var(--s6);
  border: var(--hair) solid var(--rule);
  background: var(--panel);
}
.state p {
  margin: var(--s2) 0 var(--s3);
  color: var(--ink-dim);
}
.state.error strong {
  color: var(--short);
}

.verdict {
  display: flex;
  justify-content: space-between;
  gap: var(--s4);
  padding: var(--s4);
  border: var(--hair) solid currentColor;
  background: var(--panel);
}
.verdict strong {
  display: block;
  margin: 5px 0;
  font-family: var(--font-display);
  font-size: var(--t-fig-lg);
  line-height: 1;
}
.verdict p {
  max-width: 58ch;
  color: var(--ink-dim);
  font-size: var(--t-small);
}
.bias-note {
  display: inline-block;
  margin-top: var(--s2);
  padding: 3px 6px;
  color: var(--warn);
  border: var(--hair) solid var(--warn);
}
.token-call {
  color: var(--call-hi);
  background: var(--call-wash);
}
.token-put {
  color: var(--put-hi);
  background: var(--put-wash);
}
.token-warn {
  color: var(--warn);
  background: var(--warn-wash);
}
.token-unsigned {
  color: var(--ink-faint);
}
.verdict-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: var(--s2);
}
.verdict-meta .paper {
  color: var(--warn);
}

.paper-action {
  padding: var(--s4);
  color: var(--call-hi);
  border: var(--hair) solid var(--call);
  background: var(--call-wash);
  box-shadow: inset 8px 0 0 color-mix(in srgb, var(--call) 18%, transparent);
}
.paper-action strong {
  display: block;
  margin: 6px 0;
  font-family: var(--font-data);
}
.paper-action p {
  margin: 0;
  color: var(--ink-dim);
  font-size: var(--t-small);
}

.exact-contract {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 170px;
  gap: var(--hair);
  border: 1px solid currentColor;
  background: var(--panel);
}
.contract-command,
.contract-price {
  padding: var(--s4);
  background: color-mix(in srgb, currentColor 6%, var(--panel));
}
.contract-command strong {
  display: block;
  margin: 7px 0 5px;
  color: currentColor;
  font-family: var(--font-display);
  font-size: clamp(16px, 2vw, 22px);
  line-height: 1.18;
}
.contract-command p,
.contract-price small {
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.4;
}
.contract-price {
  border-left: var(--hair) solid currentColor;
}
.contract-price strong {
  display: block;
  margin: 7px 0 4px;
  color: currentColor;
  font-size: var(--t-fig);
}

.completeness {
  padding: var(--s3);
  border: var(--hair) solid var(--warn);
  background: var(--warn-wash);
}
.completeness.complete {
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.completeness.ready {
  color: var(--phosphor);
}
.completeness p {
  margin: 4px 0 0;
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.4;
}
.completeness strong {
  display: block;
  margin-top: 4px;
  font-family: var(--font-data);
}

.levels {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--hair);
  background: var(--rule);
  border: var(--hair) solid var(--rule);
}
.levels article {
  min-width: 0;
  padding: var(--s3);
  background: var(--panel);
}
.levels strong {
  display: block;
  margin: 7px 0 3px;
  color: var(--ink);
  font-size: var(--t-lead);
}
.levels .target {
  box-shadow: inset 0 2px 0 var(--phosphor-dim);
}
.levels .target strong {
  color: var(--phosphor);
}
.levels small {
  display: block;
  color: var(--ink-faint);
  font-size: var(--t-micro);
  line-height: 1.35;
}

.evidence-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border: var(--hair) solid var(--rule);
}
.evidence-grid article {
  padding: var(--s3);
  background: var(--panel);
  border-right: var(--hair) solid var(--rule);
  border-bottom: var(--hair) solid var(--rule);
}
.evidence-grid article:nth-child(2n) {
  border-right: 0;
}
.evidence-grid article:nth-last-child(-n + 2) {
  border-bottom: 0;
}
.evidence-grid strong {
  display: block;
  margin: 5px 0 2px;
  color: var(--ink-soft);
  font-size: var(--t-small);
}
.evidence-grid small {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.contract-plan {
  border: var(--hair) solid var(--call);
  background: var(--call-wash);
}
.contract-plan header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s3);
  border-bottom: var(--hair) solid var(--call);
}
.contract-plan header strong {
  display: block;
  margin-top: 4px;
  color: var(--call-hi);
  font-size: var(--t-small);
}
.reference-chip {
  padding: 3px 7px;
  color: var(--call-hi);
  border: var(--hair) solid var(--call);
}
.contract-plan dl {
  display: grid;
  margin: 0;
}
.contract-plan .quote-grid {
  grid-template-columns: repeat(4, 1fr);
}
.contract-plan .risk-map {
  grid-template-columns: repeat(3, 1fr);
  border-top: var(--hair) solid var(--call);
}
.contract-plan dl > div {
  min-width: 0;
  padding: var(--s3);
  border-right: var(--hair) solid var(--rule);
}
.contract-plan .quote-grid > div:nth-child(4n),
.contract-plan .risk-map > div:last-child {
  border-right: 0;
}
.contract-plan .quote-grid > div:nth-child(-n + 4) {
  border-bottom: var(--hair) solid var(--rule);
}
.contract-plan dd {
  margin: 4px 0 0;
  color: var(--ink-soft);
}
.contract-plan dd:not(.label) {
  overflow-wrap: anywhere;
}
.contract-plan .risk-map small {
  display: block;
  margin-top: 3px;
  color: var(--ink-faint);
  font-size: var(--t-micro);
  line-height: 1.3;
}
.contract-plan > p {
  margin: 0;
  padding: 0 var(--s3) var(--s3);
  color: var(--ink-dim);
  font-size: var(--t-tiny);
}
.contract-plan > .missing-data {
  padding-top: var(--s3);
  color: var(--warn);
}
.contract-rejections {
  margin: 0;
  padding: 0 var(--s3) var(--s3) 1.8rem;
  color: var(--short);
  font-size: var(--t-micro);
}
.contract-rejections li + li {
  margin-top: 3px;
}

.checks {
  padding: var(--s3);
  border-left: 1px solid var(--warn);
  background: var(--warn-wash);
}
.checks summary {
  color: var(--warn);
  cursor: pointer;
}
.checks ul {
  margin: var(--s2) 0 0;
  padding-left: 1.2em;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
}
.checks li + li {
  margin-top: 3px;
}

.drawer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s3);
  border-top: var(--hair) solid var(--rule);
}
.links {
  display: flex;
  gap: var(--s2);
}
.primary-link,
.secondary-link {
  display: inline-block;
  padding: 7px 10px;
  border: var(--hair) solid var(--rule-hi);
}
.primary-link {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.secondary-link {
  color: var(--ink-dim);
}

@media (max-width: 700px) {
  .setup-drawer {
    width: 100vw;
  }
  .drawer-head {
    padding: var(--s3);
  }
  .exact-contract {
    grid-template-columns: 1fr;
  }
  .contract-price {
    border-top: var(--hair) solid currentColor;
    border-left: 0;
  }
  .levels {
    grid-template-columns: 1fr 1fr;
  }
  .contract-plan .quote-grid,
  .contract-plan .risk-map {
    grid-template-columns: 1fr 1fr;
  }
  .contract-plan .quote-grid > div,
  .contract-plan .risk-map > div {
    border-bottom: var(--hair) solid var(--rule);
  }
  .drawer-foot {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
