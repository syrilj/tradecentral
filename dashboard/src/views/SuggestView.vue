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
import SetupBacktestCard from '@/components/SetupBacktestCard.vue'
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
const searchQuery = ref('')

function resetFilters(): void {
  filter.value = 'ALL'
  searchQuery.value = ''
}
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
  let list = rows.value
  if (want === 'ALL') {
    list = rows.value
  } else if (want === 'SETUPS') {
    list = rows.value.filter(hasDirectionalPlan)
  } else if (want === 'NEEDS DATA') {
    list = rows.value.filter((row) =>
      ['WATCH', 'BLOCKED'].includes(String(row.suggestion?.right || '').toUpperCase()),
    )
  } else {
    list = rows.value.filter((row) => String(row.suggestion?.right || '').toUpperCase() === want)
  }

  const query = searchQuery.value.trim().toUpperCase()
  if (query) {
    list = list.filter(
      (row) =>
        row.symbol.toUpperCase().includes(query) ||
        String(row.signal_basis || '')
          .toUpperCase()
          .includes(query) ||
        String(row.suggestion?.reason || '')
          .toUpperCase()
          .includes(query),
    )
  }
  return list
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

function handleTableKeydown(e: KeyboardEvent): void {
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
  e.preventDefault()
  const list = filtered.value
  if (!list.length) return
  const currentIndex = list.findIndex((r) => r.symbol === selected.value)
  if (e.key === 'ArrowDown') {
    const next = (currentIndex + 1) % list.length
    selectRow(list[next].symbol)
  } else if (e.key === 'ArrowUp') {
    const prev = (currentIndex - 1 + list.length) % list.length
    selectRow(list[prev].symbol)
  }
}

function suggestionOf(row: LiveOpportunityRow): FlowSuggestion | null {
  return row.suggestion ?? null
}

function freshnessCopy(row: LiveOpportunityRow): string {
  if (row.freshness?.pass) return 'LIVE'
  return planningMode.value ? 'CLOSED' : freshnessLabel(row.freshness?.status, row.freshness?.pass)
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

      <!-- Interactive Top Metric Summary -->
      <div v-if="feed.data.value" class="readout-grid">
        <button
          type="button"
          class="kpi-card"
          :aria-pressed="filter === 'CALL'"
          @click="filter = 'CALL'"
        >
          <Readout
            label="Call"
            :value="unmeasured(coverage?.suggested_call ?? 0)"
            sub="Bullish directional plans"
            tone="call"
          />
        </button>
        <button
          type="button"
          class="kpi-card"
          :aria-pressed="filter === 'PUT'"
          @click="filter = 'PUT'"
        >
          <Readout
            label="Put"
            :value="unmeasured(coverage?.suggested_put ?? 0)"
            sub="Bearish directional plans"
            tone="put"
          />
        </button>
        <button
          type="button"
          class="kpi-card"
          :aria-pressed="filter === 'SETUPS'"
          @click="filter = 'SETUPS'"
        >
          <Readout
            label="Ready / paper action"
            :value="`${readyCount} / ${paperActionCount}`"
            :sub="`${paperCount} still waiting · paper stays unsized`"
            :tone="readyCount || paperActionCount ? 'accent' : 'flat'"
          />
        </button>
        <div class="kpi-card kpi-card-static">
          <Readout
            label="Qlib overlay"
            :value="qlibPublished ? unmeasured(coverage?.qlib_measured ?? 0) : DASH"
            :sub="qlibPublished ? 'Published deep-scan ranks' : 'No published panel'"
            :tone="qlibPublished ? 'accent' : 'flat'"
          />
        </div>
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
          The market-wide options tape returned no rows. CALL/PUT plans that come from flow stay off
          this board until that tape is available. Board structure names remain; use All to see
          them.
        </p>
      </div>

      <!-- Action Toolbar with Filter Tabs + Symbol Quick Search -->
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

        <div class="toolbar-tools">
          <div class="search-box">
            <span class="search-indicator label" aria-hidden="true">&gt;</span>
            <input
              v-model="searchQuery"
              type="text"
              class="search-input label"
              placeholder="Search symbol…"
              aria-label="Filter setups by symbol"
            />
            <button
              v-if="searchQuery"
              type="button"
              class="clear-btn label"
              aria-label="Clear symbol search"
              @click="searchQuery = ''"
            >
              &times;
            </button>
          </div>
          <span v-if="feed.data.value?.asof_utc" class="label asof">
            AS OF {{ shortDate(feed.data.value.asof_utc) }}
          </span>
        </div>
      </div>

      <LoadingState
        v-if="feed.loading.value && !feed.data.value"
        label="Recombining cached Flow, board, and qlib…"
      />
      <p v-else-if="feed.error.value" class="state err label">{{ feed.error.value }}</p>
      <p v-else-if="!available" class="state label">{{ emptyReason }}</p>

      <div v-else class="workspace">
        <!-- Setups Table -->
        <div class="table-wrap" tabindex="0" @keydown="handleTableKeydown">
          <table v-if="filtered.length" class="grid">
            <thead>
              <tr>
                <th class="label">Symbol</th>
                <th class="label">Right</th>
                <th class="label num">Strike</th>
                <th class="label num">Spot</th>
                <th class="label num" title="Invalidation mark (stop loss reference)">Inv</th>
                <th class="label num" title="Take profit zone (target reference)">TP</th>
                <th class="label num" title="Setup review quality score (0–100)">Score</th>
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
                  <button type="button" class="row-select-btn" @click.stop="selectRow(row.symbol)">
                    <span class="sr-only">Select {{ row.symbol }}</span>
                  </button>
                  <div class="sym-cell-body">
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
                  </div>
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
                    :title="
                      suggestionOf(row)?.contract_plan?.action?.replaceAll('_', ' ') ||
                      actionCopy(row)
                    "
                  >
                    {{ actionCopy(row) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty-filter-state">
            <p class="state label">
              No rows match {{ filter }}{{ searchQuery ? ` & "${searchQuery}"` : '' }}.
            </p>
            <button
              v-if="searchQuery || filter !== 'SETUPS'"
              type="button"
              class="tab-btn label"
              @click="resetFilters"
            >
              Reset filters
            </button>
          </div>
        </div>

        <!-- Setup Detail Inspector -->
        <aside v-if="active && suggestion" class="detail">
          <!-- Setup Header -->
          <div class="detail-head">
            <div class="symbol-meta">
              <span class="fig sym-lg">{{ active.symbol }}</span>
              <span class="active-basis label">{{
                active.signal_basis || 'Flow + structure'
              }}</span>
            </div>
            <div class="detail-chips">
              <span class="mode-chip label" :class="suggestion.status">{{
                unmeasured(suggestion.status)
              }}</span>
              <span class="right-chip lg label" :class="suggestedRightTokenClass(suggestion.right)">
                {{ suggestedRightLabel(suggestion.right) }}
              </span>
            </div>
          </div>

          <!-- Thesis Reason Card -->
          <div class="reason-card">
            <p v-if="suggestion.reason" class="reason">{{ suggestion.reason }}</p>
            <p v-else class="reason mute">
              Suggested from {{ active.playbook?.direction_source || 'price/model context' }}.
            </p>
          </div>

          <!-- Paper Action Banner -->
          <div v-if="suggestion.paper_actionable" class="paper-action-banner">
            <div class="paper-action-tag-line">
              <span class="label">PAPER ACTION · UNSIZED</span>
            </div>
            <strong>{{ suggestion.paper_action?.replaceAll('_', ' ') }} {{ active.symbol }}</strong>
            <small>
              Stable direction, exact contract, GEX risk levels, liquidity, and a two-sided
              reference quote passed. This does not authorize a live order.
            </small>
          </div>

          <p
            v-if="suggestion.bias_right && !suggestion.bias_confirmed"
            class="bias-watch label wraps"
          >
            UNSIGNED {{ suggestion.bias_right.toUpperCase() }} BIAS · PAPER CANDIDATE · SIZING
            LOCKED
          </p>

          <!-- Stability & Review Score Banner -->
          <p
            class="stability-banner label wraps"
            :class="{ stable: suggestion.direction_stable, churned: suggestion.direction_churned }"
          >
            {{ suggestionStabilityCopy(suggestion) }} · REVIEW SCORE
            {{ suggestion.review_score ?? 0 }}/100
          </p>

          <!-- Completeness & Confidence Status -->
          <div
            class="completeness"
            :class="{
              complete: suggestion.risk_levels_complete,
              ready: active.live_ready,
              uncalibrated: !active.confidence?.is_high,
            }"
          >
            <div class="completeness-row">
              <span class="label wraps">{{ completenessCopy(active) }}</span>
              <strong class="fig">{{ active.confidence?.band || 'UNCALIBRATED' }}</strong>
            </div>
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

          <!-- Key Price Structure Readouts -->
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

          <!-- Visual Support and Take-Profit Marks -->
          <div
            v-if="suggestion.supports?.length || suggestion.take_profit_zones?.length"
            class="level-marks-box"
          >
            <div v-if="suggestion.supports?.length" class="marks-group">
              <span class="label marks-header">Support levels</span>
              <ol class="mark-list">
                <li v-for="(mark, index) in suggestion.supports" :key="`support-${index}`">
                  <span class="fig">{{ formatSetupPrice(mark.price) }}</span>
                  <span class="src label">{{ levelSourceLabel(mark.source) }}</span>
                  <span class="why">{{
                    levelSourceImplication(mark.source, 'support', suggestion.right)
                  }}</span>
                </li>
              </ol>
            </div>
            <div v-if="suggestion.take_profit_zones?.length" class="marks-group">
              <span class="label marks-header">Take profit targets</span>
              <ol class="mark-list harvest">
                <li v-for="(mark, index) in suggestion.take_profit_zones" :key="`tp-${index}`">
                  <span class="fig">{{ formatSetupPrice(mark.price) }}</span>
                  <span class="src label">{{ levelSourceLabel(mark.source) }}</span>
                  <span class="why">{{
                    levelSourceImplication(mark.source, 'take_profit', suggestion.right)
                  }}</span>
                </li>
              </ol>
            </div>
          </div>

          <!-- GEX Barrier Magnets & Qlib Ranks -->
          <dl class="facts magnets">
            <div class="fact-card">
              <dt class="label">Call wall</dt>
              <dd class="fig">
                {{ active.barriers?.call_wall == null ? DASH : num(active.barriers.call_wall, 2) }}
              </dd>
              <small>{{ gexMagnetCopy('call_wall', suggestion.right) }}</small>
            </div>
            <div class="fact-card">
              <dt class="label">Put wall</dt>
              <dd class="fig">
                {{ active.barriers?.put_wall == null ? DASH : num(active.barriers.put_wall, 2) }}
              </dd>
              <small>{{ gexMagnetCopy('put_wall', suggestion.right) }}</small>
            </div>
            <div class="fact-card">
              <dt class="label">Qlib score</dt>
              <dd class="fig">
                {{ suggestion.qlib.measured ? signed(suggestion.qlib.score, 3) : DASH }}
              </dd>
              <small>{{ qlibAlignmentLabel(suggestion.qlib.alignment) }}</small>
            </div>
            <div class="fact-card">
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

          <!-- Specific Contract Plan -->
          <div v-if="suggestion.contract_plan" class="contract-reference">
            <div class="contract-plan-header">
              <span class="label">
                Specific contract plan ·
                {{ suggestion.contract_plan.quote_status.replaceAll('_', ' ') }}
              </span>
            </div>
            <strong class="fig contract-title">
              {{ suggestion.contract_plan.action.replaceAll('_', ' ') }} · {{ active.symbol }} ·
              {{ suggestion.contract_plan.expiry || 'EXPIRY NOT SUPPLIED' }} ·
              {{
                suggestion.contract_plan.strike == null
                  ? 'STRIKE NOT SUPPLIED'
                  : `$${num(suggestion.contract_plan.strike, 0)} ${suggestion.contract_plan.right.toUpperCase()}`
              }}
            </strong>

            <div class="contract-numbers">
              <span>
                <i class="label">{{
                  suggestion.contract_plan.quote_reference_only ? 'Delayed bid' : 'Bid'
                }}</i>
                {{
                  suggestion.contract_plan.bid == null
                    ? 'Not supplied'
                    : `$${num(suggestion.contract_plan.bid, 2)}`
                }}
              </span>
              <span>
                <i class="label">{{
                  suggestion.contract_plan.quote_reference_only
                    ? 'Delayed midpoint'
                    : 'Sizing debit'
                }}</i>
                {{
                  suggestion.contract_plan.quote_reference_only &&
                  suggestion.contract_plan.midpoint != null
                    ? `$${num(suggestion.contract_plan.midpoint, 2)}`
                    : suggestion.contract_plan.sizing_debit == null
                      ? 'Locked'
                      : `$${num(suggestion.contract_plan.sizing_debit, 2)}`
                }}
              </span>
              <span>
                <i class="label">{{
                  suggestion.contract_plan.quote_reference_only ? 'Delayed ask' : 'Ask'
                }}</i>
                {{
                  suggestion.contract_plan.ask == null
                    ? 'Not supplied'
                    : `$${num(suggestion.contract_plan.ask, 2)}`
                }}
              </span>
              <span>
                <i class="label">Max loss / 1</i>
                {{
                  suggestion.contract_plan.reference_max_loss == null
                    ? 'Debit required'
                    : `$${num(suggestion.contract_plan.reference_max_loss, 0)}`
                }}
              </span>
            </div>

            <small v-if="suggestion.contract_plan.quote_reference_only" class="missing">
              {{ suggestion.contract_plan.quote_source?.replaceAll('_', ' ') }} · paper reference
              only · live sizing locked.
            </small>
            <small class="selection-method">{{ suggestion.contract_plan.selection_method }}</small>
            <small v-if="suggestion.contract_plan.missing_fields.length" class="missing">
              Provider did not supply:
              {{ suggestion.contract_plan.missing_fields.join(', ') }}.
            </small>
            <small v-if="suggestion.contract_plan.rejection_reasons.length" class="rejected">
              Blocked: {{ suggestion.contract_plan.rejection_reasons.join(' · ') }}
            </small>

            <!-- Play Card Breakdown -->
            <div v-if="suggestion.contract_plan.play" class="play-card">
              <span class="label">
                Play card · {{ suggestion.contract_plan.play.method.replaceAll('_', ' ') }} · not
                authorized
              </span>
              <div class="contract-numbers">
                <span>
                  <i class="label">Breakeven</i>${{
                    num(suggestion.contract_plan.play.breakeven, 2)
                  }}
                </span>
                <span>
                  <i class="label">Max loss / 1</i>${{
                    num(suggestion.contract_plan.play.max_loss, 0)
                  }}
                </span>
                <span>
                  <i class="label">P/L at spot</i>
                  {{
                    suggestion.contract_plan.play.pnl_at_spot == null
                      ? DASH
                      : `$${num(suggestion.contract_plan.play.pnl_at_spot, 0)}`
                  }}
                </span>
                <span>
                  <i class="label">P/L at GEX sell</i>
                  {{
                    suggestion.contract_plan.play.pnl_at_sell == null
                      ? DASH
                      : `$${num(suggestion.contract_plan.play.pnl_at_sell, 0)}`
                  }}
                </span>
                <span>
                  <i class="label">P/L at invalidation</i>
                  {{
                    suggestion.contract_plan.play.pnl_at_invalidation == null
                      ? DASH
                      : `$${num(suggestion.contract_plan.play.pnl_at_invalidation, 0)}`
                  }}
                </span>
                <span>
                  <i class="label">Delta</i>
                  {{
                    suggestion.contract_plan.play.greeks?.delta == null
                      ? DASH
                      : num(suggestion.contract_plan.play.greeks.delta, 3)
                  }}
                </span>
              </div>
              <small v-if="suggestion.contract_plan.play.vol_source === 'unmeasured'">
                IV unmeasured: expiry P/L only, no Greeks.
              </small>
            </div>
          </div>

          <p v-if="suggestion.warnings.length" class="note">{{ suggestion.warnings.join(' ') }}</p>

          <!-- Live Entry Verification Checklist -->
          <details v-if="suggestion.blockers.length" class="entry-checks">
            <summary class="label">
              Why live entry is not ready · {{ suggestion.blockers.length }} checks
            </summary>
            <ul class="blockers">
              <li v-for="item in suggestion.blockers" :key="item">{{ item }}</li>
            </ul>
          </details>

          <!-- Defined-Risk Sizing Component -->
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

          <!-- Systematic Microstructure Backtest -->
          <SetupBacktestCard :key="`backtest-${active.symbol}`" :symbol="active.symbol" />

          <!-- Quick Navigation Actions -->
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
              class="qlink label primary-qlink"
            >
              Open play in calculator &rarr;
            </RouterLink>
            <RouterLink
              :to="{ name: 'options', query: { symbol: active.symbol } }"
              class="qlink label"
            >
              Options
            </RouterLink>
            <RouterLink
              :to="{ name: 'flow', query: { symbol: active.symbol } }"
              class="qlink label"
            >
              Flow
            </RouterLink>
            <RouterLink
              :to="{ name: 'market', query: { symbol: active.symbol } }"
              class="qlink label"
            >
              Market
            </RouterLink>
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
  box-shadow: var(--shadow-1);
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
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 55%, transparent);
  background: var(--warn-wash);
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

.kpi-card {
  appearance: none;
  width: 100%;
  min-width: 0;
  padding: 0;
  border: 0;
  text-align: left;
  font: inherit;
  color: inherit;
  background: transparent;
  cursor: pointer;
  border-radius: var(--r-xs);
  transition:
    background var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out);
}

.kpi-card:hover,
.kpi-card[aria-pressed='true'] {
  background: var(--wash-2);
}

.kpi-card[aria-pressed='true'] {
  box-shadow: inset 0 -2px 0 var(--phosphor);
}

.kpi-card:focus-visible {
  outline: var(--hair) solid var(--phosphor);
  outline-offset: 2px;
}

.kpi-card-static {
  cursor: default;
}

.kpi-card-static:hover {
  background: transparent;
}

.planning-strip {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  color: var(--warn);
  border-bottom: var(--hair) solid color-mix(in srgb, var(--warn) 55%, transparent);
  background: var(--warn-wash);
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
  flex-wrap: wrap;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  border-bottom: var(--hair) solid var(--rule);
  background: var(--void-lift);
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
  background: var(--panel);
  color: var(--ink-dim);
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}

.tab-btn:hover {
  color: var(--ink);
  border-color: var(--rule-hi);
}

.tab-btn.active {
  color: var(--phosphor);
  border-color: var(--phosphor);
  background: var(--phosphor-wash);
  font-weight: 600;
}

.tab-btn:focus-visible,
.scan-btn:focus-visible,
.clear-btn:focus-visible {
  outline: var(--hair) solid var(--phosphor);
  outline-offset: 2px;
}

.toolbar-tools {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
  padding: 2px 8px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  background: var(--panel);
  transition: border-color var(--dur-fast) var(--ease-out);
}

.search-box:focus-within {
  border-color: var(--phosphor);
  outline: var(--focus-ring);
  outline-offset: -1px;
}

.search-indicator {
  color: var(--ink-faint);
  margin-right: 6px;
  font-size: var(--t-micro);
}

.search-input {
  width: 140px;
  border: none;
  background: transparent;
  color: var(--ink);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  outline: none;
}

.search-input::placeholder {
  color: var(--ink-faint);
}

.clear-btn {
  border: none;
  background: transparent;
  color: var(--ink-dim);
  font-size: var(--t-body);
  cursor: pointer;
  padding: 0 2px;
  line-height: 1;
}

.clear-btn:hover {
  color: var(--ink);
}

.scan-btn {
  padding: 5px 12px;
  height: 28px;
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-weight: 600;
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.scan-btn:hover:not(:disabled) {
  border-color: var(--phosphor);
  outline: var(--hair) solid var(--phosphor-dim);
}

.scan-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.asof {
  color: var(--ink-faint);
  font-size: var(--t-nano);
}

.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(22rem, 1fr);
  align-items: start;
  min-height: 28rem;
  background: var(--panel);
}

.table-wrap {
  overflow: auto;
  min-width: 0;
  min-height: 18rem;
  max-height: min(75vh, 48rem);
  outline: none;
}

.table-wrap:focus-visible {
  outline: var(--hair) solid var(--phosphor);
  outline-offset: -1px;
}

.grid {
  width: 100%;
  min-width: 42rem;
  border-collapse: separate;
  border-spacing: 0;
}

.grid th,
.grid td {
  padding: 7px 10px;
  border-bottom: var(--hair) solid var(--rule-faint);
  text-align: left;
  font-size: var(--t-small);
  white-space: nowrap;
  vertical-align: middle;
  overflow: hidden;
}

.grid th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--panel-hi);
  box-shadow: inset 0 -1px 0 var(--rule);
  color: var(--ink-dim);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
}

.grid th.num,
.grid td.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.grid tbody tr {
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}

.grid tbody tr:hover {
  background: var(--panel-hi);
}

.grid tbody tr.active {
  background: var(--phosphor-wash);
  box-shadow: inset 3px 0 0 var(--phosphor);
}

.grid tbody tr.stale {
  color: var(--ink-faint);
}

.row-select-cell {
  position: relative;
}

.sym-cell-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sym {
  display: block;
  font-weight: 700;
  color: var(--ink);
}

.basis {
  display: block;
  color: var(--ink-faint);
  font-size: var(--t-nano);
  line-height: 1.2;
}

.row-select-cell .stability {
  display: block;
  color: var(--ink-dim);
  font-size: var(--t-nano);
  line-height: 1.2;
}

.right-chip {
  display: inline-block;
  padding: 2px 7px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  font-size: var(--t-micro);
  font-weight: 600;
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
  padding: 3px 8px;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  font-size: var(--t-micro);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.action-chip.paper {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
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

.empty-filter-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s3);
  padding: var(--s6) var(--s4);
}

/* Setup Inspector (Detail Pane) */
.detail {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  border-left: var(--hair) solid var(--rule);
  background: var(--void-lift);
  overflow-y: auto;
  max-height: min(75vh, 48rem);
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
  padding-bottom: var(--s2);
  border-bottom: var(--hair) solid var(--rule);
}

.symbol-meta {
  display: flex;
  flex-direction: column;
}

.sym-lg {
  font-size: var(--t-fig);
  font-weight: 700;
  color: var(--ink);
}

.active-basis {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.detail-chips {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
}

.mode-chip {
  padding: 3px 8px;
  border-radius: var(--r-xs);
  font-size: var(--t-micro);
  font-weight: 600;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel);
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

.right-chip.lg {
  font-size: var(--t-small);
  padding: 3px 10px;
}

.reason-card {
  padding: var(--s2) var(--s3);
  border-radius: var(--r-xs);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
}

.reason {
  margin: 0;
  color: var(--ink-soft);
  font-size: var(--t-small);
  line-height: 1.45;
}

.reason.mute {
  color: var(--ink-dim);
}

.paper-action-banner {
  display: grid;
  gap: 4px;
  padding: var(--s3);
  border-radius: var(--r-xs);
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
  box-shadow: inset 4px 0 0 var(--phosphor);
}

.paper-action-tag-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.paper-action-banner strong {
  font-family: var(--font-data);
  font-size: var(--t-lead);
  letter-spacing: 0.02em;
}

.paper-action-banner small {
  color: var(--ink-dim);
  line-height: 1.4;
  font-size: var(--t-micro);
}

.bias-watch {
  padding: var(--s2) var(--s3);
  border-radius: var(--r-xs);
  color: var(--warn);
  border-left: 3px solid var(--warn);
  background: var(--warn-wash);
  font-size: var(--t-micro);
}

.stability-banner {
  margin: 0;
  padding: var(--s2) var(--s3);
  border-radius: var(--r-xs);
  color: var(--warn);
  border-left: 3px solid var(--warn);
  background: var(--warn-wash);
  font-size: var(--t-micro);
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

.completeness {
  display: grid;
  gap: 4px;
  padding: var(--s3);
  border-radius: var(--r-xs);
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

.completeness-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
}

.completeness strong {
  font-family: var(--font-data);
  letter-spacing: 0.04em;
  font-size: var(--t-small);
}

.completeness small {
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.4;
}

.levels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s2);
}

.level-marks-box {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.marks-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.marks-header {
  color: var(--ink-faint);
  font-size: var(--t-nano);
  letter-spacing: var(--track-label);
}

.mark-list {
  display: grid;
  gap: 3px;
  margin: 0;
  padding: var(--s2) var(--s3);
  list-style: none;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
  background: var(--panel);
}

.mark-list.harvest {
  border-color: color-mix(in srgb, var(--phosphor) 30%, var(--rule));
}

.mark-list li {
  display: grid;
  grid-template-columns: 5.5rem minmax(6rem, auto) minmax(0, 1fr);
  gap: var(--s2);
  align-items: baseline;
}

.mark-list .fig {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.mark-list .src {
  color: var(--ink-dim);
  font-size: var(--t-micro);
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
  gap: var(--s2);
  margin: 0;
}

.fact-card {
  padding: var(--s2) var(--s3);
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
  background: var(--panel);
}

.facts dt {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.facts dd {
  margin: 2px 0 0;
  color: var(--ink);
  font-size: var(--t-body);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.facts small {
  display: block;
  margin-top: 4px;
  color: var(--ink-dim);
  font-size: var(--t-nano);
  line-height: 1.35;
}

.contract-reference {
  padding: var(--s3);
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
  background: var(--panel);
}

.contract-plan-header .label {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
}

.contract-title {
  display: block;
  margin: 6px 0 var(--s3);
  color: var(--ink);
  font-size: var(--t-lead);
  font-weight: 600;
  line-height: 1.25;
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

.contract-numbers {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-radius: var(--r-xs);
  overflow: hidden;
  border: var(--hair) solid var(--rule);
}

.contract-numbers span {
  padding: var(--s2) var(--s3);
  color: var(--ink-soft);
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
  background: var(--void-lift);
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

.contract-numbers i {
  display: block;
  overflow: visible;
  margin-bottom: 4px;
  font-style: normal;
  font-size: var(--t-nano);
  color: var(--ink-faint);
  line-height: 1.3;
  text-overflow: clip;
  white-space: normal;
}

.blockers {
  margin: 0;
  padding-left: 1.1em;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.4;
}

.entry-checks {
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
  background: var(--panel);
}

.entry-checks summary {
  padding: var(--s2) var(--s3);
  color: var(--warn);
  cursor: pointer;
  font-size: var(--t-micro);
  font-weight: 600;
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
  flex-wrap: wrap;
  gap: var(--s2);
}

.qlink {
  padding: 5px 10px;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel);
  color: var(--ink-dim);
  text-decoration: none;
  font-size: var(--t-micro);
  transition: all var(--dur-fast) var(--ease-out);
}

.qlink:hover {
  color: var(--ink);
  border-color: var(--rule-hi);
  background: var(--panel-hi);
}

.primary-qlink {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
  font-weight: 600;
}

.primary-qlink:hover {
  color: var(--phosphor);
  border-color: var(--phosphor);
  outline: var(--hair) solid var(--phosphor-dim);
}

.fine {
  color: var(--ink-faint);
  font-size: var(--t-nano);
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
  }
  .table-wrap {
    max-height: 24rem;
  }
  .detail {
    border-left: 0;
    border-top: var(--hair) solid var(--rule);
    max-height: none;
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

@media (max-width: 560px) {
  .page-head {
    padding: var(--s3);
  }

  .title-block h1 {
    font-size: var(--t-title, var(--t-lead));
  }

  .scope-stack,
  .toolbar,
  .toolbar-tools {
    width: 100%;
  }

  .scope-chip {
    max-width: 100%;
    white-space: normal;
  }

  .filter-tabs {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }

  .tab-btn {
    min-height: 2.5rem;
  }

  .search-box {
    flex: 1 1 12rem;
    min-width: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .kpi-card,
  .tab-btn {
    transition: none;
  }
}
</style>
