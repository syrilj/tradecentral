<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type FlowSuggestion, type LiveOpportunityRow, type MarketClock } from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import LoadingState from '@/components/LoadingState.vue'
import HelpTip from '@/components/HelpTip.vue'
import SetupRiskPanel from '@/components/SetupRiskPanel.vue'
import { DASH, num, shortDate, signed } from '@/format'
import {
  compactPriceList,
  freshnessLabel,
  formatPriceList,
  formatSetupPrice,
  formatTakeProfitZones,
  gexMagnetCopy,
  levelSourceImplication,
  levelSourceLabel,
  missingSourcesCopy,
  presentSetupRows,
  qlibAlignmentLabel,
  setupCalculatorQuery,
  setupHeadlineInvalidation,
  setupsFeedRequest,
  suggestionStabilityCopy,
  suggestedRightLabel,
  suggestedRightTokenClass,
  unmeasured,
} from '@/suggestDisplay'

type RightFilter = 'SETUPS' | 'CALL' | 'PUT' | 'NEEDS DATA' | 'ALL'
const FILTERS: RightFilter[] = ['SETUPS', 'CALL', 'PUT', 'NEEDS DATA', 'ALL']

const POLL_MS = 90_000
const route = useRoute()
const router = useRouter()
const sharedMarketClock = inject<Resource<MarketClock> | null>('marketClock', null)
const forceNext = ref(false)
const filter = ref<RightFilter>('SETUPS')
const selected = ref<string>('')

const feed = useResource(() => api.flowSuggestions(setupsFeedRequest(forceNext.value)), {
  intervalMs: POLL_MS,
})

async function scanLive(): Promise<void> {
  forceNext.value = true
  try {
    await feed.refresh()
  } finally {
    forceNext.value = false
  }
}

const presented = computed(() => presentSetupRows(feed.data.value))
const rows = computed<LiveOpportunityRow[]>(() => presented.value.rows as LiveOpportunityRow[])
const available = computed(() => feed.data.value?.available !== false)
const emptyReason = computed(
  () =>
    feed.data.value?.reason || feed.data.value?.suggestion?.reason || 'No Flow or board rows yet.',
)

const coverage = computed(() => presented.value.coverage)
const flowTapeUnmeasured = computed(() => {
  const cov = feed.data.value?.coverage
  return Boolean(cov && cov.flow_symbols === 0 && (cov.union_symbols ?? 0) > 0)
})
const qlibPublished = computed(() => feed.data.value?.sources?.qlib?.published === true)
const marketSession = computed(() => sharedMarketClock?.data.value?.market_session ?? null)
const planningMode = computed(() =>
  Boolean(marketSession.value && marketSession.value !== 'regular'),
)
const setupCount = computed(
  () => (coverage.value?.suggested_call ?? 0) + (coverage.value?.suggested_put ?? 0),
)
const needsDataCount = computed(
  () => (coverage.value?.suggested_watch ?? 0) + (coverage.value?.suggested_blocked ?? 0),
)
const readyCount = computed(
  () =>
    rows.value.filter((row) => {
      const plan = row.suggestion?.contract_plan
      return Boolean(plan?.sizing_eligible && plan?.stable && plan?.action === 'BUY_TO_OPEN')
    }).length,
)
const paperActionCount = computed(
  () => rows.value.filter((row) => row.suggestion?.paper_actionable).length,
)
const paperCount = computed(() =>
  Math.max(0, setupCount.value - readyCount.value - paperActionCount.value),
)

function hasDirectionalPlan(row: LiveOpportunityRow): boolean {
  return ['CALL', 'PUT'].includes(String(row.suggestion?.right || '').toUpperCase())
}

const filtered = computed(() => {
  const want = filter.value
  if (want === 'ALL') return rows.value
  if (want === 'SETUPS') {
    return rows.value.filter(hasDirectionalPlan)
  }
  if (want === 'NEEDS DATA') {
    return rows.value.filter((row) =>
      ['WATCH', 'BLOCKED'].includes(String(row.suggestion?.right || '').toUpperCase()),
    )
  }
  return rows.value.filter((row) => String(row.suggestion?.right || '').toUpperCase() === want)
})

watch(
  [rows, filtered, () => route.query.symbol],
  () => {
    const fromQuery = String(route.query.symbol || '')
      .trim()
      .toUpperCase()
    if (fromQuery && rows.value.some((row) => row.symbol === fromQuery)) {
      selected.value = fromQuery
      return
    }
    if (selected.value && filtered.value.some((row) => row.symbol === selected.value)) return
    selected.value = filtered.value[0]?.symbol || rows.value[0]?.symbol || ''
  },
  { immediate: true },
)

const active = computed(() => rows.value.find((row) => row.symbol === selected.value) ?? null)
const suggestion = computed<FlowSuggestion | null>(() => active.value?.suggestion ?? null)

function selectRow(symbol: string): void {
  selected.value = symbol
  void router.replace({ name: 'suggest', query: symbol ? { symbol } : {} })
}

function suggestionOf(row: LiveOpportunityRow): FlowSuggestion | null {
  return row.suggestion ?? null
}

function freshnessCopy(row: LiveOpportunityRow): string {
  if (row.freshness?.pass) return 'LIVE'
  return planningMode.value
    ? 'CLOSED'
    : freshnessLabel(row.freshness?.status, row.freshness?.pass)
}

function actionCopy(row: LiveOpportunityRow): string {
  const suggestion = suggestionOf(row)
  if (row.live_ready) return 'READY'
  if (suggestion?.paper_actionable) return `PAPER BUY ${String(suggestion.right).toUpperCase()}`
  const action = String(suggestion?.contract_plan?.action || '')
  if (action === 'WAIT_FOR_LIVE_QUOTE') return 'WAIT QUOTE'
  if (action === 'WAIT_FOR_STABILITY') return 'WAIT STABLE'
  if (action === 'REVIEW_FLOW_PRINT') return 'REVIEW FLOW'
  return action.replaceAll('_', ' ') || 'WAIT'
}

function filterCopy(mode: RightFilter): string {
  if (mode === 'SETUPS') return `SETUPS ${setupCount.value}`
  if (mode === 'NEEDS DATA') return `NEEDS DATA ${needsDataCount.value}`
  return mode
}

function rightTone(right: string | null | undefined): 'call' | 'put' | 'flat' | 'accent' {
  const value = String(right ?? '').toLowerCase()
  if (value === 'call') return 'call'
  if (value === 'put') return 'put'
  if (value === 'watch') return 'accent'
  return 'flat'
}

function strikeHeadline(row: FlowSuggestion | null | undefined): string {
  return formatSetupPrice(row?.strike ?? row?.contract_plan?.strike)
}

function strikeSourceCopy(row: FlowSuggestion | null | undefined): string {
  const source = row?.strike_source
    ? levelSourceLabel(row.strike_source)
    : row?.contract_plan?.strike == null
      ? 'not supplied'
      : 'positions'
  const implication = levelSourceImplication(
    row?.strike_source ?? (source === 'positions' ? 'positions' : null),
    'strike',
    row?.right,
  )
  if (!implication || source === 'not supplied') return source
  return `${source} · ${implication}`
}

function supportsHeadline(row: FlowSuggestion | null | undefined): string {
  return formatPriceList(row?.supports)
}

function invalidationHeadline(row: FlowSuggestion | null | undefined): {
  value: string
  sub: string
} {
  const mark = setupHeadlineInvalidation({
    invalidation: row?.invalidation,
    invalidationSource: row?.invalidation_source,
    planInvalidation: row?.plan_invalidation,
    planInvalidationSource: row?.plan_invalidation_source,
  })
  const source = mark.source ? levelSourceLabel(mark.source) : 'not supplied'
  const implication = levelSourceImplication(mark.source, 'invalidation', row?.right)
  return {
    value: formatSetupPrice(mark.price),
    sub: implication ? `${source} · ${implication}` : source,
  }
}

function takeProfitHeadline(row: FlowSuggestion | null | undefined): string {
  const zones = formatPriceList(row?.take_profit_zones)
  if (zones !== DASH) return zones
  return formatSetupPrice(row?.plan_target)
}

function tableTakeProfit(row: FlowSuggestion | null | undefined): string {
  const compact = compactPriceList(row?.take_profit_zones)
  if (compact !== DASH) return compact
  return formatSetupPrice(row?.plan_target)
}

function tableInvalidation(row: FlowSuggestion | null | undefined): string {
  return invalidationHeadline(row).value
}

function tableScore(row: FlowSuggestion | null | undefined): string {
  return row?.review_score == null ? DASH : unmeasured(row.review_score)
}

function completenessCopy(row: LiveOpportunityRow | null | undefined): string {
  const suggestion = row?.suggestion
  if (!suggestion) return 'not supplied'
  if (suggestion.risk_levels_complete && row?.confidence?.is_high && row.live_ready) return 'READY'
  if (suggestion.risk_levels_complete && row?.confidence?.is_high)
    return 'LEVELS COMPLETE · NOT LIVE READY'
  if (suggestion.risk_levels_complete) return 'LEVELS COMPLETE · CONFIDENCE NOT HIGH'
  return 'LEVELS INCOMPLETE'
}

const meta = computed(() => {
  const cov = coverage.value
  if (!cov)
    return feed.data.value?.asof_utc
      ? `asof ${shortDate(feed.data.value.asof_utc)}`
      : 'Awaiting Flow + board'
  return `${cov.union_symbols} names · ${cov.suggested_call ?? 0} call · ${cov.suggested_put ?? 0} put`
})
</script>

<template>
  <div class="suggest-view">
    <header class="page-head ticked rise">
      <div class="title-block">
        <span class="label eyebrow">Flow-derived research setups</span>
        <h1>Setups</h1>
        <p>
          Selecting a name shows the strike, supports, invalidation, and take profit zones from
          measured resistance/support, options GEX, positions, and technical analysis. Incomplete or
          uncalibrated rows stay unmeasured and are never a ready recommendation. Research template.
          No order ticket.
        </p>
      </div>
      <div class="scope-stack">
        <span class="scope-chip label" :class="{ planning: planningMode }">
          {{ planningMode ? 'MARKET CLOSED · PLANNING' : 'LIVE ENTRY MONITOR' }}
        </span>
        <span class="scope-chip label">STRIKE · SUPPORT · INVALIDATION · TAKE PROFIT</span>
        <span class="scope-chip label" :class="{ live: qlibPublished }">
          {{ qlibPublished ? 'QLIB PUBLISHED' : 'QLIB UNMEASURED' }}
        </span>
      </div>
    </header>

    <Panel
      label="Directional plans"
      index="M5"
      :meta="meta"
      :live="available && !feed.error.value && !planningMode"
      class="board"
    >
      <template #action>
        <button
          type="button"
          class="scan-btn label"
          :disabled="feed.loading.value"
          @click="void scanLive()"
        >
          {{ feed.loading.value ? 'UPDATING…' : planningMode ? 'REFRESH SNAPSHOT' : 'SCAN LIVE' }}
        </button>
        <HelpTip
          label="How a setup is named"
          text="A repeated CALL/PUT direction plus a stable exact contract, GEX risk levels, liquidity, and a two-sided reference quote becomes an explicit PAPER BUY action. It remains unsized. READY separately requires a live quote, calibrated confidence, and every model-state gate."
        />
      </template>

      <div v-if="feed.data.value" class="readout-grid">
        <Readout
          label="Call"
          :value="unmeasured(coverage?.suggested_call ?? 0)"
          sub="Bullish directional plans"
          tone="call"
        />
        <Readout
          label="Put"
          :value="unmeasured(coverage?.suggested_put ?? 0)"
          sub="Bearish directional plans"
          tone="put"
        />
        <Readout
          label="Ready / paper action"
          :value="`${readyCount} / ${paperActionCount}`"
          :sub="`${paperCount} still waiting · paper stays unsized`"
          :tone="readyCount || paperActionCount ? 'accent' : 'flat'"
        />
        <Readout
          label="Qlib overlay"
          :value="qlibPublished ? unmeasured(coverage?.qlib_measured ?? 0) : DASH"
          :sub="qlibPublished ? 'Published deep-scan ranks' : 'No published panel'"
          :tone="qlibPublished ? 'accent' : 'flat'"
        />
      </div>

      <div v-if="planningMode" class="planning-strip">
        <span class="label">Planning mode</span>
        <p>
          Market is outside regular hours. Directional plans remain usable; freshness and entry
          authorization stay off until a current regular-session chain clears every gate.
        </p>
      </div>
      <div v-if="flowTapeUnmeasured" class="planning-strip flow-missing">
        <span class="label">Flow tape unmeasured</span>
        <p>
          The market-wide options tape returned no rows. CALL/PUT plans that come from flow stay
          off this board until that tape is available. Board structure names remain; use All to
          see them.
        </p>
      </div>

      <div class="toolbar">
        <div class="filter-tabs">
          <button
            v-for="mode in FILTERS"
            :key="mode"
            type="button"
            class="tab-btn label"
            :class="{ active: filter === mode }"
            @click="filter = mode"
          >
            {{ filterCopy(mode) }}
          </button>
        </div>
        <span v-if="feed.data.value?.asof_utc" class="label asof"
          >AS OF {{ shortDate(feed.data.value.asof_utc) }}</span
        >
      </div>

      <LoadingState
        v-if="feed.loading.value && !feed.data.value"
        label="Recombining cached Flow, board, and qlib…"
      />
      <p v-else-if="feed.error.value" class="state err label">{{ feed.error.value }}</p>
      <p v-else-if="!available" class="state label">{{ emptyReason }}</p>

      <div v-else class="workspace">
        <div class="table-wrap">
          <table v-if="filtered.length" class="grid">
            <thead>
              <tr>
                <th class="label">Symbol</th>
                <th class="label">Right</th>
                <th class="label num">Strike</th>
                <th class="label num">Spot</th>
                <th class="label num">Inv</th>
                <th class="label num">TP</th>
                <th class="label num">Score</th>
                <th class="label">Data</th>
                <th class="label">Action</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in filtered"
                :key="row.symbol"
                :class="{
                  active: row.symbol === selected,
                  stale: !row.freshness?.pass && !hasDirectionalPlan(row),
                }"
                @click="selectRow(row.symbol)"
              >
                <td class="row-select-cell">
                  <button
                    type="button"
                    class="row-select-btn"
                    @click.stop="selectRow(row.symbol)"
                  >
                    <span class="sr-only">Select {{ row.symbol }}</span>
                  </button>
                  <span class="fig sym">{{ row.symbol }}</span>
                  <span class="basis label">{{ row.signal_basis }}</span>
                  <span
                    class="stability label"
                    :class="{
                      stable: suggestionOf(row)?.direction_stable,
                      churned: suggestionOf(row)?.direction_churned,
                    }"
                  >
                    {{ suggestionStabilityCopy(suggestionOf(row)) }}
                  </span>
                </td>
                <td>
                  <span
                    class="right-chip label"
                    :class="suggestedRightTokenClass(suggestionOf(row)?.right)"
                  >
                    {{ suggestedRightLabel(suggestionOf(row)?.right) }}
                  </span>
                </td>
                <td class="fig num">{{ strikeHeadline(suggestionOf(row)) }}</td>
                <td class="fig num">
                  {{ suggestionOf(row)?.spot == null ? DASH : num(suggestionOf(row)?.spot, 2) }}
                </td>
                <td class="fig num">{{ tableInvalidation(suggestionOf(row)) }}</td>
                <td
                  class="fig num sell"
                  :title="formatTakeProfitZones(suggestionOf(row)?.take_profit_zones)"
                >
                  {{ tableTakeProfit(suggestionOf(row)) }}
                </td>
                <td class="fig num">{{ tableScore(suggestionOf(row)) }}</td>
                <td>
                  <span class="fresh label" :class="row.freshness?.pass ? 'ok' : 'stale'">
                    {{ freshnessCopy(row) }}
                  </span>
                </td>
                <td>
                  <span
                    class="action-chip label wraps"
                    :class="{ paper: suggestionOf(row)?.paper_actionable, ready: row.live_ready }"
                    :title="suggestionOf(row)?.contract_plan?.action?.replaceAll('_', ' ') || actionCopy(row)"
                  >
                    {{ actionCopy(row) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="state label">No rows match {{ filter }}.</p>
        </div>

        <aside v-if="active && suggestion" class="detail">
          <div class="detail-head">
            <span class="fig sym-lg">{{ active.symbol }}</span>
            <span class="detail-chips">
              <span class="mode-chip label" :class="suggestion.status">{{
                unmeasured(suggestion.status)
              }}</span>
              <span class="right-chip lg label" :class="suggestedRightTokenClass(suggestion.right)">
                {{ suggestedRightLabel(suggestion.right) }}
              </span>
            </span>
          </div>
          <p v-if="suggestion.reason" class="reason">{{ suggestion.reason }}</p>
          <p v-else class="reason mute">
            Suggested from {{ active.playbook?.direction_source || 'price/model context' }}.
          </p>
          <p v-if="suggestion.bias_right && !suggestion.bias_confirmed" class="bias-watch label wraps">
            UNSIGNED {{ suggestion.bias_right.toUpperCase() }} BIAS · PAPER CANDIDATE · SIZING
            LOCKED
          </p>
          <div v-if="suggestion.paper_actionable" class="paper-action-banner">
            <span class="label">PAPER ACTION · UNSIZED</span>
            <strong>{{ suggestion.paper_action?.replaceAll('_', ' ') }} {{ active.symbol }}</strong>
            <small
              >Stable direction, exact contract, GEX risk levels, liquidity, and a two-sided
              reference quote passed. This does not authorize a live order.</small
            >
          </div>
          <p
            class="stability-banner label wraps"
            :class="{ stable: suggestion.direction_stable, churned: suggestion.direction_churned }"
          >
            {{ suggestionStabilityCopy(suggestion) }} · REVIEW SCORE
            {{ suggestion.review_score ?? 0 }}/100
          </p>

          <div
            class="completeness"
            :class="{
              complete: suggestion.risk_levels_complete,
              ready: active.live_ready,
              uncalibrated: !active.confidence?.is_high,
            }"
          >
            <span class="label wraps">{{ completenessCopy(active) }}</span>
            <strong class="fig">{{ active.confidence?.band || 'UNCALIBRATED' }}</strong>
            <small>
              {{
                suggestion.risk_levels_complete
                  ? 'Strike, supports, invalidation, and take profit are measured.'
                  : `Missing: ${suggestion.risk_missing_fields?.length ? suggestion.risk_missing_fields.join(', ') : 'not supplied'}.`
              }}
            </small>
            <small v-if="suggestion.missing_sources?.length">
              Sources unmeasured: {{ missingSourcesCopy(suggestion.missing_sources) }}
            </small>
          </div>

          <div class="levels setup-headlines">
            <Readout
              label="Strike"
              :value="strikeHeadline(suggestion)"
              :sub="strikeSourceCopy(suggestion)"
              wrap
            />
            <Readout
              label="Supports"
              :value="supportsHeadline(suggestion)"
              :sub="suggestion.supports?.length ? 'Watch these supports' : 'not supplied'"
              tone="flat"
              wrap
            />
            <Readout
              label="Invalidation"
              :value="invalidationHeadline(suggestion).value"
              :sub="invalidationHeadline(suggestion).sub"
              tone="flat"
              wrap
            />
            <Readout
              label="Take profit zones"
              :value="takeProfitHeadline(suggestion)"
              :sub="
                suggestion.take_profit_zones?.length ? 'Labeled zones, not a blend' : 'not supplied'
              "
              :tone="rightTone(suggestion.right)"
              wrap
            />
          </div>

          <ol v-if="suggestion.supports?.length" class="mark-list">
            <li v-for="(mark, index) in suggestion.supports" :key="`support-${index}`">
              <span class="fig">{{ formatSetupPrice(mark.price) }}</span>
              <span class="src label">{{ levelSourceLabel(mark.source) }}</span>
              <span class="why">{{
                levelSourceImplication(mark.source, 'support', suggestion.right)
              }}</span>
            </li>
          </ol>
          <ol v-if="suggestion.take_profit_zones?.length" class="mark-list harvest">
            <li v-for="(mark, index) in suggestion.take_profit_zones" :key="`tp-${index}`">
              <span class="fig">{{ formatSetupPrice(mark.price) }}</span>
              <span class="src label">{{ levelSourceLabel(mark.source) }}</span>
              <span class="why">{{
                levelSourceImplication(mark.source, 'take_profit', suggestion.right)
              }}</span>
            </li>
          </ol>

          <dl class="facts magnets">
            <div>
              <dt class="label">Call wall</dt>
              <dd class="fig">
                {{ active.barriers?.call_wall == null ? DASH : num(active.barriers.call_wall, 2) }}
              </dd>
              <small>{{ gexMagnetCopy('call_wall', suggestion.right) }}</small>
            </div>
            <div>
              <dt class="label">Put wall</dt>
              <dd class="fig">
                {{ active.barriers?.put_wall == null ? DASH : num(active.barriers.put_wall, 2) }}
              </dd>
              <small>{{ gexMagnetCopy('put_wall', suggestion.right) }}</small>
            </div>
            <div>
              <dt class="label">Qlib score</dt>
              <dd class="fig">
                {{ suggestion.qlib.measured ? signed(suggestion.qlib.score, 3) : DASH }}
              </dd>
            </div>
            <div>
              <dt class="label">Qlib rank</dt>
              <dd class="fig">
                {{
                  suggestion.qlib.rank == null
                    ? DASH
                    : `${suggestion.qlib.rank} / ${unmeasured(suggestion.qlib.n_symbols)}`
                }}
              </dd>
              <small>{{ qlibAlignmentLabel(suggestion.qlib.alignment) }}</small>
            </div>
          </dl>

          <div v-if="suggestion.contract_plan" class="contract-reference">
            <span class="label"
              >Specific contract plan ·
              {{ suggestion.contract_plan.quote_status.replaceAll('_', ' ') }}</span
            >
            <strong class="fig">
              {{ suggestion.contract_plan.action.replaceAll('_', ' ') }} · {{ active.symbol }} ·
              {{ suggestion.contract_plan.expiry || 'EXPIRY NOT SUPPLIED' }} ·
              {{
                suggestion.contract_plan.strike == null
                  ? 'STRIKE NOT SUPPLIED'
                  : `$${num(suggestion.contract_plan.strike, 0)} ${suggestion.contract_plan.right.toUpperCase()}`
              }}
            </strong>
            <div class="contract-numbers">
              <span
                ><i class="label">{{
                  suggestion.contract_plan.quote_reference_only ? 'Delayed bid' : 'Bid'
                }}</i
                >{{
                  suggestion.contract_plan.bid == null
                    ? 'Not supplied'
                    : `$${num(suggestion.contract_plan.bid, 2)}`
                }}</span
              >
              <span
                ><i class="label">{{
                  suggestion.contract_plan.quote_reference_only
                    ? 'Delayed midpoint'
                    : 'Sizing debit'
                }}</i
                >{{
                  suggestion.contract_plan.quote_reference_only &&
                  suggestion.contract_plan.midpoint != null
                    ? `$${num(suggestion.contract_plan.midpoint, 2)}`
                    : suggestion.contract_plan.sizing_debit == null
                      ? 'Locked'
                      : `$${num(suggestion.contract_plan.sizing_debit, 2)}`
                }}</span
              >
              <span
                ><i class="label">{{
                  suggestion.contract_plan.quote_reference_only ? 'Delayed ask' : 'Ask'
                }}</i
                >{{
                  suggestion.contract_plan.ask == null
                    ? 'Not supplied'
                    : `$${num(suggestion.contract_plan.ask, 2)}`
                }}</span
              >
              <span
                ><i class="label">Max loss / 1</i
                >{{
                  suggestion.contract_plan.reference_max_loss == null
                    ? 'Debit required'
                    : `$${num(suggestion.contract_plan.reference_max_loss, 0)}`
                }}</span
              >
            </div>
            <small v-if="suggestion.contract_plan.quote_reference_only" class="missing"
              >{{ suggestion.contract_plan.quote_source?.replaceAll('_', ' ') }} · paper reference
              only · live sizing locked.</small
            >
            <small>{{ suggestion.contract_plan.selection_method }}</small>
            <small v-if="suggestion.contract_plan.missing_fields.length" class="missing"
              >Provider did not supply:
              {{ suggestion.contract_plan.missing_fields.join(', ') }}.</small
            >
            <small v-if="suggestion.contract_plan.rejection_reasons.length" class="rejected"
              >Blocked: {{ suggestion.contract_plan.rejection_reasons.join(' · ') }}</small
            >
            <div v-if="suggestion.contract_plan.play" class="play-card">
              <span class="label"
                >Play card · {{ suggestion.contract_plan.play.method.replaceAll('_', ' ') }} · not
                authorized</span
              >
              <div class="contract-numbers">
                <span
                  ><i class="label">Breakeven</i>${{
                    num(suggestion.contract_plan.play.breakeven, 2)
                  }}</span
                >
                <span
                  ><i class="label">Max loss / 1</i>${{
                    num(suggestion.contract_plan.play.max_loss, 0)
                  }}</span
                >
                <span
                  ><i class="label">P/L at spot</i
                  >{{
                    suggestion.contract_plan.play.pnl_at_spot == null
                      ? DASH
                      : `$${num(suggestion.contract_plan.play.pnl_at_spot, 0)}`
                  }}</span
                >
                <span
                  ><i class="label">P/L at GEX sell</i
                  >{{
                    suggestion.contract_plan.play.pnl_at_sell == null
                      ? DASH
                      : `$${num(suggestion.contract_plan.play.pnl_at_sell, 0)}`
                  }}</span
                >
                <span
                  ><i class="label">P/L at invalidation</i
                  >{{
                    suggestion.contract_plan.play.pnl_at_invalidation == null
                      ? DASH
                      : `$${num(suggestion.contract_plan.play.pnl_at_invalidation, 0)}`
                  }}</span
                >
                <span
                  ><i class="label">Delta</i
                  >{{
                    suggestion.contract_plan.play.greeks?.delta == null
                      ? DASH
                      : num(suggestion.contract_plan.play.greeks.delta, 3)
                  }}</span
                >
              </div>
              <small v-if="suggestion.contract_plan.play.vol_source === 'unmeasured'"
                >IV unmeasured: expiry P/L only, no Greeks.</small
              >
            </div>
          </div>

          <p v-if="suggestion.warnings.length" class="note">{{ suggestion.warnings.join(' ') }}</p>
          <details v-if="suggestion.blockers.length" class="entry-checks">
            <summary class="label">
              Why live entry is not ready · {{ suggestion.blockers.length }} checks
            </summary>
            <ul class="blockers">
              <li v-for="item in suggestion.blockers" :key="item">{{ item }}</li>
            </ul>
          </details>

          <SetupRiskPanel
            v-if="active.playbook?.risk"
            :key="active.symbol"
            :risk="active.playbook.risk"
            :setup-status="suggestion.status"
            :reference-debit="suggestion.contract_plan?.sizing_debit"
            :reference-label="
              suggestion.contract_plan?.sizing_eligible
                ? 'Stable two-sided chain midpoint'
                : 'Sizing locked until quote, liquidity, stability, and setup gates pass'
            "
          />

          <div class="links">
            <RouterLink
              :to="{
                name: 'calculator',
                query: setupCalculatorQuery({
                  symbol: active.symbol,
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
              class="qlink label"
              >Open play in calculator</RouterLink
            >
            <RouterLink
              :to="{ name: 'options', query: { symbol: active.symbol } }"
              class="qlink label"
              >Options</RouterLink
            >
            <RouterLink :to="{ name: 'flow', query: { symbol: active.symbol } }" class="qlink label"
              >Flow</RouterLink
            >
            <RouterLink
              :to="{ name: 'market', query: { symbol: active.symbol } }"
              class="qlink label"
              >Market</RouterLink
            >
          </div>
          <p class="fine label">Research template · No order ticket · No execution authorization</p>
        </aside>
      </div>
    </Panel>
  </div>
</template>

<style scoped>
.suggest-view {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  min-width: 0;
}

.page-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--s4);
  align-items: flex-start;
  padding: var(--s3) var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  background: var(--panel);
}

.title-block {
  flex: 1 1 20rem;
  min-width: 0;
  max-width: 100%;
}

.title-block h1 {
  margin: 4px 0 8px;
  font-family: var(--font-display);
  font-size: var(--t-lead);
  font-weight: 600;
  letter-spacing: var(--track-tight);
}

.title-block p {
  max-width: 68ch;
  margin: 0;
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.45;
}

.eyebrow {
  color: var(--ink-faint);
}

.scope-stack {
  display: flex;
  flex-wrap: wrap;
  flex: 0 1 auto;
  gap: var(--s2);
  justify-content: flex-end;
}

.scope-chip {
  padding: 3px 8px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  color: var(--ink-dim);
}

.scope-chip.live {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.scope-chip.planning {
  color: var(--call-hi);
  border-color: var(--call);
  background: var(--call-wash);
}

.board {
  width: 100%;
  border-radius: var(--r-md);
  overflow: hidden;
}

.readout-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s3);
  padding: var(--s3);
  border-bottom: var(--hair) solid var(--rule);
}

.planning-strip {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  color: var(--call-hi);
  border-bottom: var(--hair) solid var(--call);
  background: var(--call-wash);
}
.planning-strip .label {
  flex: 0 0 auto;
  color: currentColor;
}
.planning-strip p {
  margin: 0;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
}
.planning-strip.flow-missing {
  color: var(--warn);
  border-bottom-color: var(--warn);
  background: var(--warn-wash);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  border-bottom: var(--hair) solid var(--rule);
}

.filter-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
}

.tab-btn {
  padding: 5px 11px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  background: var(--void-lift);
  color: var(--ink-dim);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.tab-btn.active {
  color: var(--phosphor);
  border-color: var(--phosphor);
  background: var(--phosphor-wash);
}

.scan-btn {
  padding: 5px 11px;
  height: 28px;
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-weight: 600;
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
  cursor: pointer;
}

.scan-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.asof {
  color: var(--ink-faint);
}

.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.75fr) minmax(20rem, 24rem);
  align-items: stretch;
  min-height: 28rem;
}

.table-wrap {
  overflow: auto;
  min-width: 0;
  min-height: 16rem;
  max-height: min(60vh, 40rem);
}

.grid {
  width: 100%;
  min-width: 42rem;
  border-collapse: separate;
  border-spacing: 0;
}

.grid th,
.grid td {
  padding: 6px 8px;
  border-bottom: var(--hair) solid var(--rule-faint);
  text-align: left;
  font-size: var(--t-small);
  white-space: nowrap;
  vertical-align: top;
  overflow: hidden;
}

.grid th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--panel);
  box-shadow: inset 0 -1px 0 var(--rule);
  color: var(--ink-dim);
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
}

.grid th.num,
.grid td.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.grid tbody tr {
  cursor: pointer;
}
.grid tbody tr:hover {
  background: var(--panel-hi);
}
.grid tbody tr.active {
  background: var(--phosphor-wash);
  box-shadow: inset 2px 0 0 var(--phosphor);
}
.grid tbody tr.stale {
  color: var(--ink-faint);
}

.sym {
  display: block;
  font-weight: 700;
}
.basis,
.row-select-cell .stability {
  display: block;
  color: var(--ink-faint);
  font-size: var(--t-micro);
  line-height: 1.3;
  white-space: normal;
}

.right-chip {
  display: inline-block;
  padding: 1px 7px;
  border: var(--hair) solid var(--rule-hi);
}

.token-call {
  color: var(--call);
  border-color: var(--call);
  background: var(--call-wash);
}
.token-put {
  color: var(--put);
  border-color: var(--put);
  background: var(--put-wash);
}
.token-warn {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}
.token-unsigned {
  color: var(--ink-faint);
}

.sell {
  font-variant-numeric: tabular-nums;
}
.fresh.ok {
  color: var(--phosphor);
}
.fresh.stale {
  color: var(--warn);
}
.action-chip {
  display: inline-block;
  max-width: 100%;
  padding: 2px 7px;
  color: var(--ink-faint);
  border: var(--hair) solid var(--rule-hi);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.action-chip.paper {
  color: var(--call-hi);
  border-color: var(--call);
  background: var(--call-wash);
}
.action-chip.ready {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.stability {
  color: var(--ink-dim);
  white-space: nowrap;
}
.stability.stable {
  color: var(--phosphor);
}
.stability.churned {
  color: var(--short);
}

.detail {
  border-left: var(--hair) solid var(--rule);
  padding: var(--s3);
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  min-height: 0;
  overflow: auto;
  background: var(--void-lift);
}

.detail :deep(.risk-inputs),
.detail :deep(.risk-output) {
  grid-template-columns: 1fr 1fr;
}
.detail :deep(.risk-inputs label:last-child) {
  grid-column: 1 / -1;
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
}

.detail-chips {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
}
.mode-chip {
  padding: 3px 7px;
  color: var(--call-hi);
  border: var(--hair) solid var(--call);
  background: var(--call-wash);
}
.mode-chip.candidate {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.mode-chip.paper_candidate,
.mode-chip.plan,
.mode-chip.research_only {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}
.mode-chip.blocked {
  color: var(--short);
  border-color: var(--short);
  background: var(--short-wash);
}

.sym-lg {
  font-size: var(--t-fig);
  font-weight: 600;
}
.right-chip.lg {
  font-size: var(--t-small);
  padding: 3px 10px;
}

.reason {
  margin: 0;
  color: var(--ink-soft);
  font-size: var(--t-small);
}
.reason.mute {
  color: var(--ink-faint);
}

.paper-action-banner {
  display: grid;
  gap: 4px;
  padding: var(--s3);
  color: var(--call-hi);
  border: var(--hair) solid var(--call);
  background: var(--call-wash);
  box-shadow: inset 8px 0 0 color-mix(in srgb, var(--call) 18%, transparent);
}
.paper-action-banner strong {
  font-family: var(--font-data);
  letter-spacing: 0.02em;
}
.paper-action-banner small {
  color: var(--ink-dim);
  line-height: 1.4;
}

.completeness {
  display: grid;
  gap: 4px;
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
.completeness.uncalibrated:not(.complete) {
  border-color: var(--warn);
}
.completeness strong {
  font-family: var(--font-data);
  letter-spacing: 0.04em;
}
.completeness small {
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.4;
}

.levels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s3);
}
.setup-headlines {
  grid-template-columns: 1fr 1fr;
}

.mark-list {
  display: grid;
  gap: var(--s2);
  margin: 0;
  padding: var(--s2) var(--s3);
  list-style: none;
  border: var(--hair) solid var(--rule);
  background: var(--panel);
}
.mark-list.harvest {
  border-color: color-mix(in srgb, var(--call) 35%, var(--rule));
}
.mark-list li {
  display: grid;
  grid-template-columns: 5.5rem minmax(6rem, auto) minmax(0, 1fr);
  gap: var(--s2);
  align-items: baseline;
}
.mark-list .fig {
  font-variant-numeric: tabular-nums;
}
.mark-list .src {
  color: var(--ink-dim);
}
.mark-list .why {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  line-height: 1.35;
  white-space: normal;
}

.facts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s2) var(--s3);
  margin: 0;
}

.facts dt {
  color: var(--ink-faint);
}
.facts dd {
  margin: 2px 0 0;
  font-variant-numeric: tabular-nums;
}
.facts small {
  display: block;
  margin-top: 4px;
  color: var(--ink-faint);
  font-size: var(--t-micro);
  line-height: 1.35;
}

.contract-reference {
  padding: var(--s3);
  border: var(--hair) solid var(--call);
  background: var(--call-wash);
}
.contract-reference strong {
  display: block;
  margin: 6px 0 var(--s3);
  color: var(--call-hi);
  font-size: var(--t-lead);
  line-height: 1.2;
}
.contract-reference small {
  display: block;
  margin-top: var(--s2);
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.4;
}
.contract-reference small.missing {
  color: var(--warn);
}
.contract-reference small.rejected {
  color: var(--short);
}
.play-card {
  margin-top: var(--s3);
  padding-top: var(--s3);
  border-top: var(--hair) solid var(--rule);
}
.bias-watch {
  padding: var(--s2);
  color: var(--warn);
  border-left: 1px solid var(--warn);
  background: var(--warn-wash);
}
.stability-banner {
  margin: 0;
  padding: var(--s2);
  color: var(--warn);
  border-left: 1px solid var(--warn);
  background: var(--warn-wash);
}
.stability-banner.stable {
  color: var(--phosphor);
  border-left-color: var(--phosphor);
  background: var(--phosphor-wash);
}
.stability-banner.churned {
  color: var(--short);
  border-left-color: var(--short);
  background: var(--short-wash);
}
.contract-numbers {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border: var(--hair) solid var(--rule);
}
.contract-numbers span {
  padding: var(--s2);
  color: var(--ink-soft);
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
  border-right: var(--hair) solid var(--rule);
  border-bottom: var(--hair) solid var(--rule);
}
.contract-numbers span:nth-child(2n),
.contract-numbers span:last-child {
  border-right: 0;
}
.contract-numbers span:nth-last-child(-n + 2) {
  border-bottom: 0;
}
/* Quote captions ("Delayed midpoint") are wider than a quarter cell — wrap
   rather than inherit the .label ellipsis and lose the "delayed" qualifier. */
.contract-numbers i {
  display: block;
  overflow: visible;
  margin-bottom: 4px;
  font-style: normal;
  line-height: 1.3;
  text-overflow: clip;
  white-space: normal;
}

.blockers {
  margin: 0;
  padding-left: 1.1em;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
}

.entry-checks {
  border: var(--hair) solid var(--rule);
  background: var(--panel);
}
.entry-checks summary {
  padding: var(--s2);
  color: var(--warn);
  cursor: pointer;
}
.entry-checks .blockers {
  padding: 0 var(--s3) var(--s3) 1.8rem;
}

.note {
  margin: 0;
  color: var(--warn);
  font-size: var(--t-tiny);
}

.links {
  display: flex;
  gap: var(--s2);
}

.qlink {
  padding: 3px 8px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
  text-decoration: none;
}

.qlink:hover {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

.fine {
  color: var(--ink-faint);
}

.state {
  padding: var(--s4);
  color: var(--ink-dim);
}
.state.err {
  color: var(--short);
}

@media (max-width: 980px) {
  .workspace {
    grid-template-columns: 1fr;
    height: auto;
  }
  .table-wrap {
    max-height: 28rem;
  }
  .detail {
    border-left: 0;
    border-top: var(--hair) solid var(--rule);
    max-height: 40rem;
  }
  .readout-grid {
    grid-template-columns: 1fr 1fr;
  }
  .mark-list li {
    grid-template-columns: 1fr;
    gap: 2px;
  }
  .page-head {
    flex-direction: column;
  }
  .title-block {
    flex: 0 1 auto;
  }
  .scope-stack {
    justify-content: flex-start;
  }
}
</style>
