<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type LiveOpportunityRow, type UnusualFlowRow } from '@/api'
import { useResource } from '@/composables/useResource'
import AppIcon from '@/components/AppIcon.vue'
import Panel from '@/components/Panel.vue'
import LoadingState from '@/components/LoadingState.vue'
import { compact, DASH, num, pctFrac, signed, signedPct, shortDate, tone, usd } from '@/format'

type FlowTab = 'live' | 'opportunities' | 'states'
type LiveSort = 'score' | 'premium' | 'return'

const FLOW_LIMIT = 40
const FlowStateView = defineAsyncComponent(() => import('@/views/FlowStateView.vue'))
const OptionsConvictionBoard = defineAsyncComponent(
  () => import('@/components/OptionsConvictionBoard.vue'),
)

const route = useRoute()
const router = useRouter()

function flowTab(value: unknown): FlowTab {
  return value === 'opportunities' || value === 'states' ? value : 'live'
}

const tab = ref<FlowTab>(flowTab(route.query.tab))
const minPremium = ref(25_000)
const liveSort = ref<LiveSort>('score')
const liveSortDir = ref<'asc' | 'desc'>('desc')
const unusualForceNext = ref(false)
const opportunitiesForceNext = ref(false)
const selectedOpportunitySymbol = ref<string | null>(null)
const showStructureBoard = ref(false)
const accountEquity = ref<number | null>(25_000)
const netDebit = ref<number | null>(null)
const nowMs = ref(Date.now())
let ageTimer: number | undefined

const unusual = useResource(
  () => api.unusualFlow({ limit: FLOW_LIMIT, minPremium: minPremium.value, force: unusualForceNext.value }),
  { intervalMs: 30_000, enabled: () => tab.value === 'live' },
)
const opportunities = useResource(
  () => api.liveOpportunities({ limit: 50, force: opportunitiesForceNext.value }),
  { intervalMs: 30_000, immediate: false, enabled: () => tab.value === 'opportunities' },
)

watch(() => route.query.tab, (value) => {
  const next = flowTab(value)
  if (tab.value !== next) tab.value = next
})

watch(tab, (next) => {
  const current = flowTab(route.query.tab)
  if (current !== next || (next === 'live' && route.query.tab != null)) {
    const query = { ...route.query }
    if (next === 'live') delete query.tab
    else query.tab = next
    void router.replace({ query })
  }

  // Inactive panes perform no polling. Refresh on entry so switching back to
  // a pane never presents an indefinitely old snapshot; server caches keep
  // this cheap when the underlying data is still fresh.
  if (next === 'live' && !unusual.loading.value) void unusual.refresh()
  if (next === 'opportunities' && !opportunities.loading.value) void opportunities.refresh()
}, { immediate: true })

onMounted(() => {
  ageTimer = window.setInterval(() => (nowMs.value = Date.now()), 5_000)
})

onUnmounted(() => {
  if (ageTimer !== undefined) window.clearInterval(ageTimer)
})

const liveRows = computed<UnusualFlowRow[]>(() => {
  const direction = liveSortDir.value === 'asc' ? 1 : -1
  return [...(unusual.data.value?.rows ?? [])].sort((a, b) => {
    const value = (row: UnusualFlowRow): number | null => {
      if (liveSort.value === 'premium') return row.premium ?? null
      if (liveSort.value === 'return') return row.ret_1d ?? null
      return row.unusual_score ?? row.activity_score
    }
    const av = value(a)
    const bv = value(b)
    if (av == null || !Number.isFinite(av)) return bv == null || !Number.isFinite(bv) ? a.symbol.localeCompare(b.symbol) : 1
    if (bv == null || !Number.isFinite(bv)) return -1
    return direction * (av - bv)
  })
})

const opportunityRows = computed<LiveOpportunityRow[]>(() => opportunities.data.value?.rows ?? [])
const selectedOpportunity = computed<LiveOpportunityRow | null>(() => {
  if (!selectedOpportunitySymbol.value) return null
  return opportunityRows.value.find((row) => row.symbol === selectedOpportunitySymbol.value) ?? null
})
const liveCoverage = computed(() => unusual.data.value?.coverage)
const opportunityCoverage = computed(() => opportunities.data.value?.coverage)
const liveMeta = computed(() => {
  const c = liveCoverage.value
  if (!c) return 'LOADING MARKET COVERAGE'
  return `${c.unusual_shown} SHOWN · ${c.live_completed}/${c.live_requested} LIVE SCANS · ${c.market_universe} UNIVERSE`
})
const opportunityMeta = computed(() => {
  const c = opportunityCoverage.value
  if (!c) return 'COMBINING STRUCTURE + FLOW'
  return `${c.high_confidence} HIGH · ${c.live_ready} LIVE-READY · ${c.gate_fail} NO-TRADE · ${c.union_symbols} TESTED`
})
const feedAge = computed(() => {
  const stamp = opportunities.data.value?.asof_utc
  if (!stamp) return null
  const parsed = Date.parse(stamp)
  return Number.isFinite(parsed) ? Math.max(0, Math.floor((nowMs.value - parsed) / 1000)) : null
})
const feedAgeLabel = computed(() => {
  const seconds = feedAge.value
  if (seconds == null) return 'WAITING'
  if (seconds < 60) return `${seconds}s AGO`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m AGO`
  return `${Math.floor(seconds / 3600)}h AGO`
})
const riskCapital = computed(() => {
  const equity = Number(accountEquity.value)
  const riskFraction = selectedOpportunity.value?.playbook.risk.max_account_risk_pct ?? 0.005
  return Number.isFinite(equity) && equity > 0 ? equity * riskFraction : 0
})
const maxContracts = computed(() => {
  const debit = Number(netDebit.value)
  if (!Number.isFinite(debit) || debit <= 0 || riskCapital.value <= 0) return 0
  return Math.max(0, Math.floor(riskCapital.value / (debit * 100)))
})

watch(selectedOpportunitySymbol, () => {
  netDebit.value = null
})

function setPremium(value: number): void {
  if (minPremium.value === value) return
  minPremium.value = value
  void unusual.refresh({ clear: true })
}

async function pullLiveFlow(): Promise<void> {
  unusualForceNext.value = true
  try {
    await unusual.refresh()
  } finally {
    unusualForceNext.value = false
  }
}

async function pullLiveOpportunities(): Promise<void> {
  opportunitiesForceNext.value = true
  try {
    await opportunities.refresh()
  } finally {
    opportunitiesForceNext.value = false
  }
}

function setLiveSort(next: LiveSort): void {
  if (liveSort.value === next) {
    liveSortDir.value = liveSortDir.value === 'desc' ? 'asc' : 'desc'
  } else {
    liveSort.value = next
    liveSortDir.value = 'desc'
  }
}

function sortMark(key: LiveSort): string {
  if (liveSort.value !== key) return ''
  return liveSortDir.value === 'desc' ? ' ↓' : ' ↑'
}

function openSymbol(symbol: string): void {
  void router.push({ name: 'options', query: { symbol } })
}

function onRowKey(event: KeyboardEvent, symbol: string): void {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    openSymbol(symbol)
  }
}

function selectOpportunity(row: LiveOpportunityRow): void {
  selectedOpportunitySymbol.value = row.symbol
}

function onOpportunityKey(event: KeyboardEvent, row: LiveOpportunityRow): void {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    selectOpportunity(row)
  }
}

function confidenceLabel(row: LiveOpportunityRow): string {
  const probability = row.confidence.probability
  return probability == null
    ? row.confidence.band
    : `${row.confidence.band} ${pctFrac(probability, 0)}`
}

function readyLabel(row: LiveOpportunityRow): string {
  if (row.highlighted) return 'CANDIDATE'
  if (row.live_ready) return 'RESEARCH'
  return row.gate_pass ? 'DATA BLOCK' : 'NO-TRADE'
}

function opportunityTitle(row: LiveOpportunityRow): string {
  return [...row.gate_reasons, ...row.freshness.reasons, ...row.playbook.blockers].filter(Boolean).join(' · ')
}

function level(value: number | null | undefined): string {
  return value == null ? DASH : usd(value, 2)
}

function sideLabel(row: UnusualFlowRow): string {
  if (row.context_side === 'long') return 'UP CONTEXT'
  if (row.context_side === 'short') return 'DOWN CONTEXT'
  if (row.context_side === 'mixed') return 'MIXED'
  return 'NEUTRAL'
}

function sideTone(row: UnusualFlowRow): string {
  if (row.context_side === 'long') return 'pos'
  if (row.context_side === 'short') return 'neg'
  return 'flat'
}

function basisLabel(row: LiveOpportunityRow): string {
  if (row.signal_basis === 'both') return 'BOTH'
  if (row.signal_basis === 'flow_only') return 'FLOW'
  if (row.signal_basis === 'structure_only') return 'STRUCTURE'
  return String(row.signal_basis).toUpperCase()
}
</script>

<template>
  <div class="flow-view">
    <header class="flow-head ticked rise">
      <div class="flow-title">
        <span class="label eyebrow">Market workspace</span>
        <h1>FLOW <span>/ MARKET</span></h1>
        <p>
          Live options tape and structure board for the whole market, plus the barrier-conditioned
          continuation sleeve (abnormal flow × impact × structural barrier) as a separate research surface.
        </p>
      </div>
      <div class="scope-stack">
        <span class="scope-chip label live"><i aria-hidden="true" /> MARKET-WIDE</span>
        <span class="scope-chip label">AUTO-POLL 30S</span>
        <span class="scope-chip label warn">RESEARCH ONLY</span>
      </div>
    </header>

    <nav class="flow-tabs" aria-label="Market flow views" role="tablist">
      <button
        type="button"
        role="tab"
        aria-controls="flow-live-panel"
        :aria-selected="tab === 'live'"
        :class="{ on: tab === 'live' }"
        @click="tab = 'live'"
      ><AppIcon name="flow" :size="16" /> <span>Live Flow</span></button>
      <button
        type="button"
        role="tab"
        aria-controls="flow-opportunities-panel"
        :aria-selected="tab === 'opportunities'"
        :class="{ on: tab === 'opportunities' }"
        @click="tab = 'opportunities'"
      ><AppIcon name="options" :size="16" /> <span>Opportunities</span></button>
      <button
        type="button"
        role="tab"
        aria-controls="flow-states-panel"
        :aria-selected="tab === 'states'"
        :class="{ on: tab === 'states' }"
        @click="tab = 'states'"
      ><AppIcon name="research" :size="16" /> <span>Barrier Sleeve</span></button>
    </nav>

    <section v-if="tab === 'live'" id="flow-live-panel" role="tabpanel" class="flow-pane">
      <section class="flow-command rise" aria-label="Live flow controls">
        <div class="command-copy">
          <span class="label">Live tape threshold</span>
          <strong class="fig">${{ compact(minPremium) }} minimum premium</strong>
        </div>
        <div class="thresholds" aria-label="Minimum premium">
          <button v-for="value in [25_000, 100_000, 250_000]" :key="value" type="button" :class="{ on: minPremium === value }" @click="setPremium(value)">
            ${{ compact(value) }}+
          </button>
        </div>
        <button class="refresh label" type="button" :disabled="unusual.loading.value" @click="void pullLiveFlow()">
          {{ unusual.loading.value ? 'PULLING TAPE' : 'PULL LIVE TAPE' }}
        </button>
      </section>

      <Panel label="Live Options Flow" index="01" :meta="liveMeta" :live="!unusual.loading.value" flush class="flow-panel rise">
        <template #action>
          <span class="asof label">{{ unusual.data.value?.asof ? `AS OF ${shortDate(unusual.data.value.asof)}` : 'WAITING FOR TAPE' }}</span>
        </template>

        <LoadingState v-if="unusual.loading.value && !unusual.data.value" label="Scanning market flow" compact />
        <p v-else-if="unusual.error.value && !unusual.data.value" class="panel-note error">{{ unusual.error.value }}</p>
        <template v-else>
          <p v-if="unusual.error.value" class="panel-note error stale-error">
            Refresh failed: {{ unusual.error.value }} · showing the last successful tape.
          </p>
          <p class="panel-note">
            C/P identity is not bought/sold direction. Rows with no live tape stay visible so coverage gaps never read as zero activity.
          </p>
          <div class="table-scroll">
            <table v-if="liveRows.length" class="grid flow-table">
              <thead>
                <tr>
                  <th class="label">Rank / Symbol</th>
                  <th class="label num sort"><button type="button" @click="setLiveSort('score')">Unusual{{ sortMark('score') }}</button></th>
                  <th class="label">Evidence</th>
                  <th class="label num sort"><button type="button" @click="setLiveSort('premium')">Premium{{ sortMark('premium') }}</button></th>
                  <th class="label num">C / P</th>
                  <th class="label num sort"><button type="button" @click="setLiveSort('return')">1D{{ sortMark('return') }}</button></th>
                  <th class="label">Context</th>
                  <th class="label">Data</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in liveRows"
                  :key="row.symbol"
                  class="click-row"
                  tabindex="0"
                  role="link"
                  :aria-label="`Open ${row.symbol} options tape`"
                  @click="openSymbol(row.symbol)"
                  @keydown="onRowKey($event, row.symbol)"
                >
                  <td><span class="rank fig">{{ String(row.activity_rank).padStart(2, '0') }}</span><strong class="symbol fig">{{ row.symbol }}</strong></td>
                  <td class="num"><div class="score"><span class="fig">{{ num(row.unusual_score ?? row.activity_score, 1) }}</span><i><b :style="{ width: `${Math.min(100, row.unusual_score ?? row.activity_score)}%` }" /></i></div></td>
                  <td><span v-for="flag in row.flags.slice(0, 2)" :key="flag" class="evidence label">{{ flag }}</span><span v-if="!row.flags.length" class="muted">—</span></td>
                  <td class="fig num" :class="{ muted: !row.live }">{{ row.live ? `$${compact(row.premium)}` : 'NO LIVE TAPE' }}</td>
                  <td class="fig num"><span class="call">C{{ row.call_print_count }}</span><span class="muted"> / </span><span class="put">P{{ row.put_print_count }}</span></td>
                  <td class="fig num" :class="tone(row.ret_1d)">{{ row.ret_1d == null ? DASH : signedPct(row.ret_1d * 100, 1) }}</td>
                  <td><span class="context label" :class="sideTone(row)">{{ sideLabel(row) }}</span></td>
                  <td><span class="source-chip label" :class="row.live ? 'live' : 'proxy'">{{ row.live ? 'TRADE TAPE' : 'ACTIVITY PROXY' }}</span></td>
                </tr>
              </tbody>
            </table>
            <p v-else class="empty-state">No rows clear the current premium threshold. Lower the threshold or refresh coverage.</p>
          </div>
        </template>
      </Panel>
    </section>

    <section v-else-if="tab === 'opportunities'" id="flow-opportunities-panel" role="tabpanel" class="flow-pane">
      <section class="flow-command rise" aria-label="Opportunity board status">
        <div class="feed-beacon" :class="opportunityCoverage?.high_confidence ? 'hot' : 'quiet'" aria-hidden="true"><i /></div>
        <div class="command-copy">
          <span class="label">Opportunity radar · {{ feedAgeLabel }}</span>
          <strong class="fig">{{ opportunityMeta }}</strong>
        </div>
        <div class="feed-contract label">
          <span>PASSIVE CACHE-SAFE</span>
          <span>MANUAL PULL = LIVE VENDORS</span>
        </div>
        <button class="refresh live-pull label" type="button" :disabled="opportunities.loading.value" @click="void pullLiveOpportunities()">
          {{ opportunities.loading.value ? 'PULLING SOURCES' : 'PULL LIVE DATA' }}
        </button>
      </section>

      <Panel label="Calibrated Opportunity Radar" index="02" :meta="opportunityMeta" flush class="flow-panel rise">
        <p class="panel-note honesty-line">
          <strong>HIGH is reserved for calibrated probability ≥65%.</strong>
          Composite is an ordinal search rank only. Every stale, proxy, cost, liquidity, and confidence failure stays visible.
        </p>
        <LoadingState v-if="opportunities.loading.value && !opportunities.data.value" label="Combining market signals" compact />
        <p v-else-if="opportunities.error.value && !opportunities.data.value" class="panel-note error">{{ opportunities.error.value }}</p>
        <p v-else-if="opportunities.data.value?.available === false" class="empty-state">{{ opportunities.data.value.reason || 'No opportunities are available yet.' }}</p>
        <div v-else class="table-scroll">
          <p v-if="opportunities.error.value" class="panel-note error stale-error">
            Refresh failed: {{ opportunities.error.value }} · showing the last successful radar.
          </p>
          <table v-if="opportunityRows.length" class="grid flow-table opportunities-table">
            <thead><tr><th class="label">Rank / Symbol</th><th class="label">Confidence</th><th class="label num">Ordinal</th><th class="label">Readiness</th><th class="label">Source</th><th class="label num">Spread</th><th class="label num">OI</th><th class="label num">DTE</th></tr></thead>
            <tbody>
              <tr
                v-for="(row, index) in opportunityRows"
                :key="row.symbol"
                class="click-row opportunity-row"
                :class="{ 'gate-fail': !row.gate_pass, highlighted: row.highlighted, selected: selectedOpportunitySymbol === row.symbol }"
                tabindex="0"
                role="button"
                :aria-expanded="selectedOpportunitySymbol === row.symbol"
                :aria-label="`Inspect ${row.symbol} risk playbook`"
                :title="opportunityTitle(row)"
                @click="selectOpportunity(row)"
                @keydown="onOpportunityKey($event, row)"
              >
                <td><span class="rank fig">{{ String(index + 1).padStart(2, '0') }}</span><strong class="symbol fig">{{ row.symbol }}</strong><span v-if="row.highlighted" class="radar-mark label">FOCUS</span></td>
                <td><span class="confidence-chip label" :class="row.confidence.band.toLowerCase()">{{ confidenceLabel(row) }}</span></td>
                <td class="fig num" :class="tone(row.composite_score)">{{ signed(row.composite_score, 2) }}</td>
                <td><span class="gate label" :class="row.highlighted ? 'pass' : row.live_ready ? 'research' : 'fail'">{{ readyLabel(row) }}</span></td>
                <td><span class="source-chip label">{{ basisLabel(row) }}</span></td>
                <td class="fig num">{{ pctFrac(row.spread_pct, 1) }}</td>
                <td class="fig num">{{ num(row.open_interest, 0) }}</td>
                <td class="fig num">{{ row.selected_dte == null ? DASH : `${row.selected_dte}D` }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty-state">No opportunity rows yet. Pull live data to populate the radar.</p>
        </div>
      </Panel>

      <section v-if="selectedOpportunity" class="playbook rise" aria-live="polite" aria-label="Selected opportunity risk playbook">
        <header class="playbook-head">
          <div class="playbook-identity">
            <span class="label">Selected research playbook</span>
            <div><strong class="fig">{{ selectedOpportunity.symbol }}</strong><span class="direction label" :class="selectedOpportunity.playbook.direction">{{ selectedOpportunity.playbook.direction.toUpperCase() }}</span></div>
          </div>
          <div class="playbook-verdict">
            <span class="confidence-chip label" :class="selectedOpportunity.confidence.band.toLowerCase()">{{ confidenceLabel(selectedOpportunity) }}</span>
            <span class="gate label" :class="selectedOpportunity.playbook.status === 'candidate' ? 'pass' : selectedOpportunity.playbook.status === 'research_only' ? 'research' : 'fail'">{{ selectedOpportunity.playbook.status.replace('_', ' ').toUpperCase() }}</span>
          </div>
          <button class="close-playbook" type="button" aria-label="Close playbook" @click="selectedOpportunitySymbol = null">×</button>
        </header>

        <div class="playbook-grid">
          <article class="play-card thesis-card">
            <span class="card-index fig">A / THESIS</span>
            <h3>{{ selectedOpportunity.playbook.structure_label }}</h3>
            <p>
              {{ selectedOpportunity.playbook.direction === 'watch'
                ? 'Direction is unresolved. Keep this name on the radar; call/put identity cannot establish bought or sold direction.'
                : `Defined-risk ${selectedOpportunity.playbook.direction} template using price/model context, live liquidity gates, and measured structural barriers.` }}
            </p>
            <dl class="micro-grid">
              <div><dt class="label">Expiry</dt><dd class="fig">{{ selectedOpportunity.playbook.expiry || DASH }}</dd></div>
              <div><dt class="label">Spot</dt><dd class="fig">{{ level(selectedOpportunity.playbook.levels.spot) }}</dd></div>
              <div><dt class="label">Expected move</dt><dd class="fig">{{ level(selectedOpportunity.playbook.levels.expected_move) }}</dd></div>
              <div><dt class="label">Evidence</dt><dd class="fig">{{ basisLabel(selectedOpportunity) }}</dd></div>
            </dl>
          </article>

          <article class="play-card levels-card">
            <span class="card-index fig">B / LEVELS</span>
            <div class="level-stack">
              <div class="level-row trigger"><span class="label">Trigger</span><strong class="fig">{{ level(selectedOpportunity.playbook.trigger) }}</strong><small>Wait for confirmation; do not anticipate.</small></div>
              <div class="level-row target"><span class="label">Target / short leg</span><strong class="fig">{{ level(selectedOpportunity.playbook.target) }}</strong><small>Structural barrier or expected-move reference.</small></div>
              <div class="level-row invalid"><span class="label">Hard invalidation</span><strong class="fig">{{ level(selectedOpportunity.playbook.invalidation) }}</strong><small>Exit the thesis—never average down.</small></div>
            </div>
            <ol v-if="selectedOpportunity.playbook.legs.length" class="legs">
              <li v-for="leg in selectedOpportunity.playbook.legs" :key="leg.action"><span class="label">{{ leg.action }}</span>{{ leg.instruction }}</li>
            </ol>
            <p v-else class="muted play-note">No contract legs until direction is validated.</p>
          </article>

          <article class="play-card risk-card">
            <span class="card-index fig">C / SIZE</span>
            <h3>0.50% max-loss budget</h3>
            <div class="risk-inputs">
              <label><span class="label">Account equity</span><input v-model.number="accountEquity" type="number" min="0" step="1000" inputmode="decimal" /></label>
              <label><span class="label">Live net debit / spread</span><input v-model.number="netDebit" type="number" min="0" step="0.05" inputmode="decimal" placeholder="Enter quote" /></label>
            </div>
            <div class="size-result">
              <span class="label">Risk capital {{ usd(riskCapital, 0) }}</span>
              <strong class="fig">{{ maxContracts }} <small>MAX CONTRACT{{ maxContracts === 1 ? '' : 'S' }}</small></strong>
            </div>
            <p class="formula fig">floor(equity × 0.005 ÷ (net debit × 100))</p>
            <p class="play-note">{{ selectedOpportunity.playbook.risk.entry_order }}</p>
            <p class="play-note">{{ selectedOpportunity.playbook.risk.exit_rule }}</p>
          </article>

          <article class="play-card barrier-card">
            <span class="card-index fig">D / BARRIERS</span>
            <ul class="barrier-list">
              <li :class="selectedOpportunity.gate_pass ? 'ok' : 'stop'"><span>Liquidity gate</span><strong>{{ selectedOpportunity.gate_pass ? 'PASS' : 'BLOCK' }}</strong><small>{{ pctFrac(selectedOpportunity.spread_pct, 1) }} spread · {{ num(selectedOpportunity.open_interest, 0) }} OI · {{ selectedOpportunity.selected_dte ?? DASH }}D</small></li>
              <li :class="selectedOpportunity.freshness.pass ? 'ok' : 'stop'"><span>Feed freshness</span><strong>{{ selectedOpportunity.freshness.pass ? 'PASS' : 'BLOCK' }}</strong><small>Chain {{ selectedOpportunity.freshness.chain_age_seconds == null ? DASH : `${num(selectedOpportunity.freshness.chain_age_seconds, 0)}s` }} · flow {{ selectedOpportunity.freshness.flow_age_seconds == null ? DASH : `${num(selectedOpportunity.freshness.flow_age_seconds, 0)}s` }}</small></li>
              <li :class="selectedOpportunity.confidence.is_high ? 'ok' : 'warn'"><span>Calibration</span><strong>{{ selectedOpportunity.confidence.is_high ? 'PASS' : 'RESEARCH' }}</strong><small>{{ selectedOpportunity.confidence.reason || `${pctFrac(selectedOpportunity.confidence.probability, 1)} calibrated probability` }}</small></li>
              <li class="warn"><span>Quote cost</span><strong>PARTIAL</strong><small>{{ pctFrac(selectedOpportunity.costs.one_way_half_spread_pct, 1) }} one-way half-spread · impact unmeasured</small></li>
            </ul>
          </article>
        </div>

        <div class="blocker-strip" :class="selectedOpportunity.playbook.blockers.length ? 'has-blockers' : 'clear'">
          <div>
            <span class="label">{{ selectedOpportunity.playbook.blockers.length ? 'Do not trade until cleared' : 'Candidate checks cleared' }}</span>
            <p>{{ selectedOpportunity.playbook.blockers.length ? selectedOpportunity.playbook.blockers.join(' · ') : 'Fresh calibrated context and measured liquidity gates pass. Confirm contract quotes and portfolio exposure before any order.' }}</p>
          </div>
          <button type="button" class="open-chain label" @click="openSymbol(selectedOpportunity.symbol)">OPEN LIVE CHAIN →</button>
        </div>
      </section>

      <section class="structure-drawer rise" aria-label="Structural conviction board">
        <div>
          <span class="label">Full structural chain board</span>
          <p>Optional deep view. Opening it can fetch up to 25 option chains; the radar above stays fast and cache-safe by default.</p>
        </div>
        <button type="button" class="structure-toggle label" :aria-expanded="showStructureBoard" @click="showStructureBoard = !showStructureBoard">
          {{ showStructureBoard ? 'CLOSE STRUCTURE BOARD' : 'OPEN STRUCTURE BOARD' }}
        </button>
      </section>
      <OptionsConvictionBoard v-if="showStructureBoard" @select="openSymbol" />
    </section>

    <section v-else id="flow-states-panel" role="tabpanel" class="flow-pane">
      <section class="proxy-note ticked rise">
        <AppIcon name="research" :size="18" />
        <div>
          <span class="label">Barrier-conditioned liquidity momentum (continuation sleeve)</span>
          <p>
            Rank by continuation score: persistent abnormal pressure, elevated local impact, and proximity to a
            structural inventory barrier. This surface is for continuation research (roughly multi-session on daily
            proxies; 15–30m once true OFI lands) — not cascade fade, not bottom-picking, not live authorization.
          </p>
        </div>
      </section>
      <FlowStateView />
    </section>
  </div>
</template>

<style scoped>
.flow-view { display: flex; flex-direction: column; gap: var(--s3); min-width: 0; padding-bottom: var(--s5); }
.flow-pane { display: flex; flex-direction: column; gap: var(--s3); min-width: 0; }
.flow-head { display: flex; justify-content: space-between; gap: var(--s5); padding: var(--s5); border: var(--hair) solid var(--border-strong); }
.eyebrow { color: var(--phosphor); }
h1 { margin-top: 4px; font: 700 var(--t-fig-lg) / 1 var(--font-display); letter-spacing: -0.06em; color: var(--text-primary); }
h1 span { color: var(--text-tertiary); font-size: var(--t-display); letter-spacing: 0; }
.flow-title p { max-width: 62ch; margin-top: var(--s3); color: var(--text-secondary); font-size: var(--t-small); }
.scope-stack { display: flex; align-content: flex-start; justify-content: flex-end; flex-wrap: wrap; gap: 6px; max-width: 310px; }
.scope-chip, .source-chip, .gate, .context, .evidence { display: inline-flex; align-items: center; min-height: 20px; padding: 2px 5px; border: var(--hair) solid var(--border-strong); color: var(--text-secondary); background: var(--surface-overlay); }
.scope-chip.live { color: var(--status-live); border-color: var(--phosphor-dim); }
.scope-chip.live i { width: 5px; height: 5px; margin-right: 5px; background: currentColor; }
.scope-chip.warn { color: var(--status-stale); }
.flow-tabs { display: flex; gap: 2px; border-bottom: var(--hair) solid var(--border-strong); }
.flow-tabs button { display: inline-flex; align-items: center; gap: 8px; min-height: 38px; padding: 8px 13px; color: var(--text-secondary); border-bottom: 2px solid transparent; transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out); }
.flow-tabs button:hover { color: var(--text-primary); background: var(--surface-overlay); }
.flow-tabs button.on { color: var(--phosphor); border-bottom-color: var(--phosphor); background: var(--phosphor-wash); }
.flow-command { display: flex; align-items: center; gap: var(--s4); padding: var(--s3) var(--s4); border: var(--hair) solid var(--border-subtle); background: var(--surface-base); }
/* Status lamp — square registration mark, not a radar pulse. */
.feed-beacon { position: relative; display: grid; place-items: center; width: 22px; height: 22px; flex: 0 0 auto; border: var(--hair) solid var(--border-strong); background: var(--void); }
.feed-beacon i { width: 6px; height: 6px; background: currentColor; }
.feed-beacon.hot { color: var(--phosphor); border-color: var(--phosphor-dim); background: var(--phosphor-wash); }
.feed-beacon.quiet { color: var(--text-tertiary); }
.command-copy { display: flex; flex-direction: column; gap: 2px; min-width: 180px; }
.command-copy strong { color: var(--text-primary); font-size: var(--t-small); }
.feed-contract { display: flex; flex-direction: column; gap: 2px; margin-left: auto; color: var(--text-tertiary); text-align: right; }
.feed-contract span:last-child { color: var(--status-live); }
.thresholds { display: flex; gap: 4px; }
.thresholds button, .refresh { min-height: 30px; padding: 4px 8px; border: var(--hair) solid var(--border-strong); color: var(--text-secondary); background: var(--surface-raised); font-family: var(--font-data); font-size: var(--t-tiny); }
.thresholds button:hover, .thresholds button.on, .refresh:hover:not(:disabled) { color: var(--phosphor); border-color: var(--phosphor-dim); background: var(--phosphor-wash); }
.refresh { margin-left: auto; font-family: var(--font-display); letter-spacing: var(--track-label); }
.feed-contract + .refresh { margin-left: 0; }
.live-pull { color: var(--phosphor); border-color: var(--phosphor-dim); background: var(--phosphor-wash); }
.refresh:disabled { opacity: .55; cursor: progress; }
.asof { color: var(--text-tertiary); }
.panel-note { padding: var(--s3) var(--s4); border-bottom: var(--hair) solid var(--border-subtle); color: var(--text-secondary); font-size: var(--t-small); }
.panel-note.error { color: var(--halt); }
.panel-note.stale-error { background: color-mix(in srgb, var(--short) 7%, var(--surface-base)); }
.honesty-line { display: flex; flex-wrap: wrap; gap: 5px 10px; }
.honesty-line strong { color: var(--phosphor); font-family: var(--font-display); font-size: var(--t-tiny); letter-spacing: var(--track-label); text-transform: uppercase; }
.table-scroll { overflow: auto; }
.flow-table { min-width: 860px; }
.flow-table th button { color: inherit; font: inherit; text-transform: inherit; letter-spacing: inherit; }
.flow-table th.sort button:hover { color: var(--phosphor); }
.click-row { cursor: pointer; }
.click-row:hover, .click-row:focus-visible { background: var(--phosphor-wash); outline: none; }
.opportunity-row { position: relative; }
.opportunity-row.highlighted { background: var(--phosphor-wash); box-shadow: inset 3px 0 0 var(--phosphor); }
.opportunity-row.selected { background: var(--call-wash); box-shadow: inset 3px 0 0 var(--call-hi); }
.opportunity-row.highlighted.selected { box-shadow: inset 3px 0 0 var(--phosphor), inset 0 -1px 0 var(--call); }
.rank { display: inline-block; min-width: 3ch; margin-right: var(--s2); color: var(--text-tertiary); }
.symbol { color: var(--text-primary); }
.radar-mark { margin-left: 7px; padding: 1px 4px; color: var(--void); background: var(--phosphor); font-size: 8px; }
.score { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; min-width: 56px; }
.score i { display: block; width: 56px; height: 3px; background: var(--rule); overflow: hidden; }
.score b { display: block; height: 100%; background: var(--phosphor-dim); }
.evidence { margin: 1px 3px 1px 0; font-size: 9px; }
.muted { color: var(--text-tertiary); }
.source-chip.live { color: var(--status-live); border-color: var(--phosphor-dim); }
.source-chip.proxy { color: var(--status-proxy); border-color: var(--call); }
.context.pos { color: var(--long); }
.context.neg { color: var(--short); }
.gate.pass { color: var(--long); border-color: var(--long); }
.gate.research { color: var(--status-stale); border-color: var(--status-stale); }
.gate.fail { color: var(--short); border-color: var(--short); }
.gate-fail { opacity: .76; }
.confidence-chip { display: inline-flex; min-height: 20px; align-items: center; padding: 2px 6px; border: var(--hair) solid var(--border-strong); white-space: nowrap; }
.confidence-chip.high { color: var(--void); border-color: var(--phosphor); background: var(--phosphor); font-weight: 800; }
.confidence-chip.moderate { color: var(--status-stale); border-color: var(--status-stale); }
.confidence-chip.low { color: var(--short); border-color: var(--short); }
.confidence-chip.uncalibrated { color: var(--text-tertiary); border-color: var(--border-strong); }
.empty-state { padding: var(--s5); color: var(--text-secondary); }
.proxy-note { display: flex; align-items: flex-start; gap: var(--s3); padding: var(--s4); border: var(--hair) solid color-mix(in srgb, var(--call) 45%, var(--rule)); color: var(--call-hi); background: var(--call-wash); }
.proxy-note p { margin-top: 4px; color: var(--text-secondary); font-size: var(--t-small); }

/* ---- selected playbook -------------------------------------------------- */
.playbook { border: var(--hair) solid var(--border-strong); background: var(--void); }
.playbook-head { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: var(--s4); padding: var(--s4); border-bottom: var(--hair) solid var(--border-strong); background: var(--surface-base); border-left: 3px solid var(--call); }
.playbook-identity { display: flex; flex-direction: column; gap: 4px; }
.playbook-identity > span { color: var(--call-hi); }
.playbook-identity div { display: flex; align-items: center; gap: var(--s3); }
.playbook-identity strong { color: var(--text-primary); font-size: var(--t-fig); letter-spacing: -.05em; }
.direction { min-height: 20px; padding: 2px 6px; border: var(--hair) solid currentColor; }
.direction.long { color: var(--long); }
.direction.short { color: var(--short); }
.direction.watch { color: var(--status-stale); }
.playbook-verdict { display: flex; align-items: center; gap: 6px; }
.close-playbook { width: 32px; height: 32px; color: var(--text-secondary); border: var(--hair) solid var(--border-strong); background: var(--surface-raised); font-size: 20px; line-height: 1; }
.close-playbook:hover { color: var(--text-primary); border-color: var(--text-tertiary); }
.playbook-grid { display: grid; grid-template-columns: 1.1fr 1.15fr 1fr 1.15fr; }
.play-card { min-width: 0; min-height: 270px; padding: var(--s4); border-right: var(--hair) solid var(--border-subtle); background: var(--surface-base); }
.play-card:last-child { border-right: 0; }
.card-index { display: block; margin-bottom: var(--s4); color: var(--text-tertiary); font-size: var(--t-micro); letter-spacing: .08em; }
.play-card h3 { margin: 0 0 var(--s3); color: var(--text-primary); font: 650 var(--t-body) / 1.2 var(--font-display); }
.play-card p { color: var(--text-secondary); font-size: var(--t-small); }
.micro-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s3); margin-top: var(--s4); }
.micro-grid div { padding-top: var(--s2); border-top: var(--hair) solid var(--border-subtle); }
.micro-grid dt { color: var(--text-tertiary); }
.micro-grid dd { margin: 4px 0 0; color: var(--text-primary); font-size: var(--t-small); }
.level-stack { display: flex; flex-direction: column; }
.level-row { display: grid; grid-template-columns: 1fr auto; gap: 3px var(--s3); padding: var(--s2) 0; border-bottom: var(--hair) solid var(--border-subtle); }
.level-row strong { font-size: var(--t-body); }
.level-row small { grid-column: 1 / -1; color: var(--text-tertiary); font-size: var(--t-micro); }
.level-row.trigger strong { color: var(--call-hi); }
.level-row.target strong { color: var(--long); }
.level-row.invalid strong { color: var(--short); }
.legs { display: flex; flex-direction: column; gap: 5px; margin: var(--s3) 0 0; padding: 0; list-style: none; color: var(--text-secondary); font-size: var(--t-small); }
.legs li { display: grid; grid-template-columns: auto 1fr; gap: var(--s2); }
.legs span { color: var(--call-hi); }
.risk-card { background: var(--surface-base); }
.risk-inputs { display: grid; grid-template-columns: 1fr; gap: var(--s2); }
.risk-inputs label { display: grid; grid-template-columns: 1fr minmax(90px, .8fr); align-items: center; gap: var(--s2); }
.risk-inputs .label { overflow: visible; font-size: 9px; text-overflow: clip; white-space: normal; }
.risk-inputs input { width: 100%; min-width: 0; height: 30px; padding: 4px 7px; color: var(--text-primary); border: var(--hair) solid var(--border-strong); outline: none; background: var(--void); font: 600 var(--t-small) var(--font-data); text-align: right; }
.risk-inputs input:focus { border-color: var(--phosphor); outline: var(--hair) solid var(--phosphor-dim); outline-offset: 0; }
.size-result { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--s3); margin-top: var(--s4); padding: var(--s3) 0; border-top: var(--hair) solid var(--border-strong); border-bottom: var(--hair) solid var(--border-strong); }
.size-result > span { color: var(--text-tertiary); }
.size-result strong { color: var(--phosphor); font-size: var(--t-fig); line-height: .9; text-align: right; }
.size-result small { display: block; margin-top: 4px; color: var(--text-secondary); font: 700 var(--t-micro) var(--font-display); letter-spacing: var(--track-label); }
.formula { margin-top: var(--s2); color: var(--text-tertiary) !important; font-size: 9px !important; }
.play-note { margin-top: var(--s2); font-size: var(--t-micro) !important; }
.barrier-list { display: flex; flex-direction: column; gap: 0; margin: 0; padding: 0; list-style: none; }
.barrier-list li { display: grid; grid-template-columns: 1fr auto; gap: 3px var(--s3); padding: var(--s2) 0; border-bottom: var(--hair) solid var(--border-subtle); color: var(--text-secondary); font-size: var(--t-small); }
.barrier-list strong { font: 800 var(--t-micro) var(--font-display); letter-spacing: var(--track-label); }
.barrier-list small { grid-column: 1 / -1; color: var(--text-tertiary); font-size: var(--t-micro); line-height: 1.35; }
.barrier-list li.ok strong { color: var(--long); }
.barrier-list li.stop strong { color: var(--short); }
.barrier-list li.warn strong { color: var(--status-stale); }
.blocker-strip { display: flex; align-items: center; justify-content: space-between; gap: var(--s4); padding: var(--s3) var(--s4); border-top: var(--hair) solid var(--border-strong); }
.blocker-strip.has-blockers { background: color-mix(in srgb, var(--short) 8%, var(--surface-base)); }
.blocker-strip.clear { background: color-mix(in srgb, var(--long) 8%, var(--surface-base)); }
.blocker-strip > div { min-width: 0; }
.blocker-strip.has-blockers .label { color: var(--short); }
.blocker-strip.clear .label { color: var(--long); }
.blocker-strip p { margin-top: 3px; color: var(--text-secondary); font-size: var(--t-small); }
.open-chain { flex: 0 0 auto; min-height: 34px; padding: 6px 10px; color: var(--void); background: var(--phosphor); font-weight: 800; }
.open-chain:hover { color: var(--ink); background: var(--phosphor-dim); }
.structure-drawer { display: flex; align-items: center; justify-content: space-between; gap: var(--s4); padding: var(--s3) var(--s4); border: var(--hair) solid var(--border-subtle); background: var(--surface-base); }
.structure-drawer > div { min-width: 0; }
.structure-drawer p { margin-top: 3px; color: var(--text-tertiary); font-size: var(--t-small); }
.structure-toggle { flex: 0 0 auto; min-height: 34px; padding: 6px 10px; color: var(--phosphor); border: var(--hair) solid var(--phosphor-dim); background: var(--phosphor-wash); }
.structure-toggle:hover { color: var(--void); background: var(--phosphor); }

@media (max-width: 780px) {
  .flow-head { flex-direction: column; gap: var(--s3); padding: var(--s4); }
  h1 { font-size: var(--t-fig); }
  .scope-stack { justify-content: flex-start; max-width: none; }
  .flow-command { flex-wrap: wrap; }
  .feed-contract { order: 4; width: 100%; margin-left: 0; text-align: left; }
  .refresh { margin-left: 0; min-height: 44px; }
  .flow-tabs { overflow-x: auto; }
  .flow-tabs button { flex: 0 0 auto; min-height: 44px; }
  .thresholds button { min-height: 44px; }
  .playbook-head { grid-template-columns: 1fr auto; }
  .playbook-verdict { grid-column: 1 / -1; grid-row: 2; }
  .close-playbook { grid-column: 2; grid-row: 1; }
  .playbook-grid { grid-template-columns: 1fr; }
  .play-card { min-height: 0; border-right: 0; border-bottom: var(--hair) solid var(--border-subtle); }
  .blocker-strip { align-items: stretch; flex-direction: column; }
  .open-chain { min-height: 44px; }
  .structure-drawer { align-items: stretch; flex-direction: column; }
  .structure-toggle { min-height: 44px; }
}

@media (min-width: 781px) and (max-width: 1180px) {
  .playbook-grid { grid-template-columns: 1fr 1fr; }
  .play-card:nth-child(2) { border-right: 0; }
  .play-card:nth-child(-n + 2) { border-bottom: var(--hair) solid var(--border-subtle); }
}
</style>
