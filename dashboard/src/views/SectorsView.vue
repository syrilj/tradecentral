<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { type SectorFlowPayload, type StatusPayload } from '@/api'
import type { Resource } from '@/composables/useResource'
import { age, shortDate, signedPct, tone } from '@/format'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import HelpTip from '@/components/HelpTip.vue'
import LoadingState from '@/components/LoadingState.vue'

/**
 * Sector Rotation & Flow Analysis View.
 *
 * Dedicated tab for monitoring cross-sector ETF flow scores, relative strength
 * against benchmark, market regime indicators, and surfaced flow watch names.
 */
const status = inject<Resource<StatusPayload>>('status')!
type SectorFlowResource = Resource<SectorFlowPayload> & {
  refresh: (opts?: { force?: boolean; clear?: boolean }) => Promise<void>
}
const sectorFlowRes = inject<SectorFlowResource>('sectorFlow')
const router = useRouter()

const watchSearch = ref('')
const selectedCategory = ref<'all' | 'in' | 'out'>('all')
/** ETF code expanded under the rotation map (click a sector row). */
const expandedEtf = ref<string | null>(null)

const d = computed(() => status.data.value)
const flow = computed(
  () =>
    (sectorFlowRes?.data.value ?? d.value?.sector_flow) as
      | {
          money_in?: string[]
          money_out?: string[]
          sectors_ranked?: SectorRow[]
          watch_names?: WatchRow[]
          market_context?: Record<string, number | boolean | string>
          asof?: string | null
          asof_bar?: string | null
          source?: string | null
        }
      | undefined,
)

const sectorLoading = computed(() =>
  Boolean(
    sectorFlowRes?.loading.value || (status.loading.value && !flow.value?.sectors_ranked?.length),
  ),
)
const sectorAsOf = computed(() => flow.value?.asof_bar ?? null)
const sectorAgeDays = computed(() => {
  if (!sectorAsOf.value) return null
  const stamp = Date.parse(`${sectorAsOf.value}T00:00:00Z`)
  if (!Number.isFinite(stamp)) return null
  return Math.max(0, Math.floor((Date.now() - stamp) / 86_400_000))
})
const sectorStale = computed(() => sectorAgeDays.value == null || sectorAgeDays.value > 3)
const rotationMeta = computed(() => {
  if (!sectorAsOf.value) return sectorLoading.value ? 're-running' : 'date unknown'
  const bar = shortDate(sectorAsOf.value)
  const src = String(flow.value?.source || 'scan').replace(/_/g, ' ')
  const stale = sectorStale.value ? ' · STALE' : ''
  const ago = sectorFlowRes?.fetchedAt.value ? ` · ${age(sectorFlowRes.fetchedAt.value)}` : ''
  return `BAR ${bar} · ${src}${ago}${stale}`
})

onMounted(() => {
  void sectorFlowRes?.refresh({ force: true })
})

interface SectorRow {
  etf: string
  name: string
  bucket: string
  ret_1d: number
  ret_5d: number
  ret_21d: number
  rs_5d: number
  rs_21d: number
  flow_score: number
}

interface WatchRow {
  symbol: string
  sector_hint: string
  etf: string
  score: number
  rs_5d: number
}

const sectors = computed(() => flow.value?.sectors_ranked ?? [])
const watch = computed(() => flow.value?.watch_names ?? [])
const mkt = computed(() => {
  const raw = flow.value?.market_context
  return raw && typeof raw === 'object' ? raw : undefined
})

const flowMax = computed(() => Math.max(1e-6, ...sectors.value.map((s) => Math.abs(s.flow_score))))

const accumulationSectors = computed(() => sectors.value.filter((s) => s.flow_score > 0))
const distributionSectors = computed(() => sectors.value.filter((s) => s.flow_score < 0))

const topIn = computed(() => {
  if (!sectors.value.length) return null
  return [...sectors.value].sort((a, b) => b.flow_score - a.flow_score)[0]
})

const topOut = computed(() => {
  if (!sectors.value.length) return null
  return [...sectors.value].sort((a, b) => a.flow_score - b.flow_score)[0]
})

const filteredWatch = computed(() => {
  const query = watchSearch.value.trim().toUpperCase()
  return watch.value.filter((w) => {
    if (
      query &&
      !w.symbol.includes(query) &&
      !w.sector_hint.toUpperCase().includes(query) &&
      !w.etf.includes(query)
    ) {
      return false
    }
    if (selectedCategory.value === 'in') return w.score >= 0
    if (selectedCategory.value === 'out') return w.score < 0
    return true
  })
})

function open(sym: string | undefined): void {
  if (sym) void router.push({ name: 'market', query: { symbol: sym } })
}

function toggleSector(etf: string): void {
  expandedEtf.value = expandedEtf.value === etf ? null : etf
}

const expandedNames = computed(() => {
  const etf = expandedEtf.value
  if (!etf) return [] as WatchRow[]
  return watch.value
    .filter((w) => w.etf === etf)
    .sort((a, b) => Math.abs(b.score) - Math.abs(a.score))
})
</script>

<template>
  <div class="sectors-view">
    <!-- ── 00 Summary KPI Header ───────────────────────────────────────── -->
    <div class="summary-deck">
      <div class="kpi-card">
        <span class="label kpi-label">Benchmark Market Context</span>
        <div class="kpi-val-row">
          <span class="kpi-val">{{ mkt?.benchmark ?? 'SPY' }}</span>
          <span class="kpi-badge" :class="mkt?.spy_above_ma20 ? 'pos' : 'neg'">
            {{ mkt?.spy_above_ma20 ? 'ABOVE MA20' : 'BELOW MA20' }}
          </span>
        </div>
        <span class="kpi-sub">
          SPY 1D: {{ signedPct(Number(mkt?.spy_ret_1d ?? 0) * 100, 2) }} · 5D:
          {{ signedPct(Number(mkt?.spy_ret_5d ?? 0) * 100, 2) }}
        </span>
      </div>

      <div class="kpi-card armed">
        <span class="label kpi-label">Top Accumulation Sector</span>
        <div class="kpi-val-row">
          <span class="kpi-val sym">{{ topIn ? topIn.etf : '—' }}</span>
          <span class="kpi-badge pos">
            {{ topIn ? signedPct(topIn.flow_score * 100, 1) : '—' }}
          </span>
        </div>
        <span class="kpi-sub fl-truncate">
          {{ topIn ? topIn.name : 'No sector data' }}
        </span>
      </div>

      <div class="kpi-card held">
        <span class="label kpi-label">Top Distribution Sector</span>
        <div class="kpi-val-row">
          <span class="kpi-val sym">{{ topOut ? topOut.etf : '—' }}</span>
          <span class="kpi-badge neg">
            {{ topOut ? signedPct(topOut.flow_score * 100, 1) : '—' }}
          </span>
        </div>
        <span class="kpi-sub fl-truncate">
          {{ topOut ? topOut.name : 'No sector data' }}
        </span>
      </div>

      <div class="kpi-card">
        <span class="label kpi-label">Sector Flow Breadth</span>
        <div class="kpi-val-row">
          <span class="kpi-val fig"
            >{{ accumulationSectors.length }} In / {{ distributionSectors.length }} Out</span
          >
          <span class="kpi-badge flat">BREADTH</span>
        </div>
        <span class="kpi-sub"> {{ sectors.length }} sector ETFs tracked </span>
      </div>
    </div>

    <!-- ── 01 Market Context Strip & Cards ────────────────────────────── -->
    <Panel
      label="Sector rotation map"
      index="01"
      :meta="rotationMeta"
      :live="sectorLoading"
      class="w-full"
    >
      <template #action>
        <HelpTip
          label="Sector rotation"
          text="Flow score ranks sector ETFs by multi-horizon relative strength vs the benchmark. Right/green = accumulation (money in), left/red = distribution. Use this for which sleeve is leading, then open Market on the ETF or a watch name. This panel re-runs the daily sector scan on its own; it does not wait for a full Desk scan."
        />
        <button
          class="filter-btn label"
          type="button"
          :class="{ active: sectorLoading }"
          :disabled="sectorLoading"
          title="Re-run the sector money-flow scan now"
          @click="void sectorFlowRes?.refresh({ force: true })"
        >
          {{ sectorLoading ? 'RUNNING' : 'RE-RUN' }}
        </button>
      </template>
      <LoadingState v-if="sectorLoading && !sectors.length" label="Loading sector flow" compact />
      <div v-if="mkt" class="mkt-readouts">
        <Readout
          label="SPY 1D Return"
          :value="signedPct(Number(mkt.spy_ret_1d) * 100)"
          :tone="tone(mkt.spy_ret_1d)"
          size="sm"
        />
        <Readout
          label="SPY 5D Return"
          :value="signedPct(Number(mkt.spy_ret_5d) * 100)"
          :tone="tone(mkt.spy_ret_5d)"
          size="sm"
        />
        <Readout
          label="SPY 21D Return"
          :value="signedPct(Number(mkt.spy_ret_21d) * 100)"
          :tone="tone(mkt.spy_ret_21d)"
          size="sm"
        />
        <Readout
          label="SPY Trend"
          :value="mkt.spy_above_ma20 ? 'ABOVE MA20' : 'BELOW MA20'"
          :tone="mkt.spy_above_ma20 ? 'pos' : 'neg'"
          size="sm"
        />
        <Readout
          label="QQQ 5D RS vs SPY"
          :value="signedPct(Number(mkt.qqq_spy_rs_5d) * 100)"
          :tone="tone(mkt.qqq_spy_rs_5d)"
          size="sm"
        />
      </div>

      <!-- Single rotation visual: click a row to expand names under it -->
      <div v-if="sectors.length" class="rotation-strip">
        <template
          v-for="s in [...sectors].sort((a, b) => b.flow_score - a.flow_score)"
          :key="'rot-' + s.etf"
        >
          <div
            class="rot-row"
            :class="[s.flow_score >= 0 ? 'in' : 'out', { open: expandedEtf === s.etf }]"
            @click="toggleSector(s.etf)"
          >
            <span class="fig rot-etf">{{ s.etf }}</span>
            <span class="label rot-name" :title="s.name">{{ s.name }}</span>
            <span class="rot-bar" aria-hidden="true">
              <i
                :class="s.flow_score >= 0 ? 'in' : 'out'"
                :style="{ width: `${Math.min(100, (Math.abs(s.flow_score) / flowMax) * 100)}%` }"
              />
            </span>
            <span class="fig rot-score" :class="tone(s.flow_score)">{{
              signedPct(s.flow_score * 100, 1)
            }}</span>
            <span class="fig rot-rs" :class="tone(s.ret_5d)"
              >{{ signedPct(s.ret_5d * 100, 1) }} 5D</span
            >
            <span class="fig rot-rs" :class="tone(s.rs_5d)"
              >{{ signedPct(s.rs_5d * 100, 1) }} RS</span
            >
            <span class="rot-chev label">{{ expandedEtf === s.etf ? '▴' : '▾' }}</span>
          </div>
          <div v-if="expandedEtf === s.etf" class="rot-expand">
            <div class="rot-expand-head">
              <span class="label">{{ s.etf }} · surfaced names</span>
              <button class="filter-btn label" type="button" @click.stop="open(s.etf)">
                OPEN ETF ↗
              </button>
            </div>
            <div v-if="expandedNames.length" class="name-chips">
              <button
                v-for="w in expandedNames"
                :key="w.symbol"
                type="button"
                class="name-chip"
                :class="(w.score ?? 0) >= 0 ? 'in' : 'out'"
                @click.stop="open(w.symbol)"
              >
                <span class="fig">{{ w.symbol }}</span>
                <span class="fig" :class="tone(w.score)">{{ signedPct(w.score * 100, 1) }}</span>
              </button>
            </div>
            <p v-else class="note tiny">No watch names mapped to this sleeve this session.</p>
          </div>
        </template>
      </div>
      <p v-else-if="!status.loading.value" class="note pad">No sector flow data available.</p>
      <p v-if="sectors.length" class="note tiny pad-x">
        Green = accumulation · red = distribution. Click a sector to expand stock names; click a
        name for Market.
      </p>
    </Panel>

    <!-- Full catalog (filterable) stays below for search across all sleeves -->
    <Panel
      label="All surfaced names"
      index="02"
      :meta="`${filteredWatch.length} shown`"
      class="w-full"
      flush
    >
      <template #action>
        <div class="action-bar">
          <div class="filter-group">
            <button
              class="filter-btn label"
              :class="{ active: selectedCategory === 'all' }"
              @click="selectedCategory = 'all'"
            >
              ALL ({{ watch.length }})
            </button>
            <button
              class="filter-btn label"
              :class="{ active: selectedCategory === 'in' }"
              @click="selectedCategory = 'in'"
            >
              MONEY IN
            </button>
            <button
              class="filter-btn label"
              :class="{ active: selectedCategory === 'out' }"
              @click="selectedCategory = 'out'"
            >
              MONEY OUT
            </button>
          </div>
          <input
            v-model="watchSearch"
            type="text"
            placeholder="Filter symbols…"
            class="search-input label"
          />
        </div>
      </template>

      <div class="table-container watch-expanded">
        <table v-if="filteredWatch.length" class="grid">
          <thead>
            <tr>
              <th class="label">Symbol</th>
              <th class="label">Sector</th>
              <th class="label">ETF</th>
              <th class="label">Flow bar</th>
              <th class="label num">Flow score</th>
              <th class="label num">5D RS</th>
              <th class="label">Lean</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(w, i) in filteredWatch" :key="i" @click="open(w.symbol)">
              <td class="row-select-cell fig sym">
  <button type="button" class="row-select-btn" @click.stop="open(w.symbol)"><span class="sr-only">Select row</span></button>{{ w.symbol }}</td>
              <td class="label">{{ w.sector_hint }}</td>
              <td class="fig etf-sym">{{ w.etf }}</td>
              <td>
                <span class="fl-track" aria-hidden="true">
                  <b class="fl-mid" />
                  <i
                    class="fl-fill"
                    :class="(w.score ?? 0) >= 0 ? 'in' : 'out'"
                    :style="
                      (w.score ?? 0) >= 0
                        ? {
                            left: '50%',
                            width: `${Math.min(50, (Math.abs(Number(w.score ?? 0)) / flowMax) * 50)}%`,
                          }
                        : {
                            right: '50%',
                            width: `${Math.min(50, (Math.abs(Number(w.score ?? 0)) / flowMax) * 50)}%`,
                          }
                    "
                  />
                </span>
              </td>
              <td class="fig num" :class="tone(w.score)">{{ signedPct(w.score * 100, 2) }}</td>
              <td class="fig num" :class="tone(w.rs_5d)">{{ signedPct(w.rs_5d * 100, 2) }}</td>
              <td class="label" :class="(w.score ?? 0) >= 0 ? 'pos' : 'neg'">
                {{ (w.score ?? 0) >= 0 ? 'money in' : 'money out' }}
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">
          {{
            watch.length === 0
              ? 'No watch names surfaced by the flow engine.'
              : 'No watch names match the filter.'
          }}
        </p>
      </div>
    </Panel>
  </div>
</template>

<style scoped>
.sectors-view {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s4);
  align-items: start;
}
.w-full {
  grid-column: 1 / -1;
}
.w-half {
  grid-column: span 2;
}

/* ---- Summary Deck -------------------------------------------------------- */
.summary-deck {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s3);
}

.kpi-card {
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: 0;
  padding: var(--s3) var(--s4);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.kpi-card.armed {
  border-color: var(--long);
}
.kpi-card.held {
  border-color: var(--short);
}

.kpi-label {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.kpi-val-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
}

.kpi-val {
  font-family: var(--font-data);
  font-size: 1.2rem;
  font-weight: 700;
  color: var(--ink);
}

.kpi-badge {
  font-size: var(--t-micro);
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 2px;
  text-transform: uppercase;
}
.kpi-badge.pos {
  color: var(--long);
  background: var(--long-wash);
}
.kpi-badge.neg {
  color: var(--short);
  background: var(--short-wash);
}
.kpi-badge.flat {
  color: var(--ink-dim);
  background: var(--rule);
}

.kpi-sub {
  font-size: var(--t-micro);
  color: var(--ink-dim);
}
.fl-truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---- Market Context Strip & Cards --------------------------------------- */
.mkt-readouts {
  display: flex;
  gap: var(--s5);
  flex-wrap: wrap;
  padding-bottom: var(--s4);
  margin-bottom: var(--s4);
  border-bottom: var(--hair) solid var(--rule);
}

.rotation-strip {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: var(--s3);
  border: var(--hair) solid var(--rule);
  max-height: 420px;
  overflow: auto;
}
.rot-row {
  display: grid;
  grid-template-columns: 4.5ch minmax(0, 1.2fr) minmax(100px, 1.6fr) 6ch 6ch 6ch 2ch;
  align-items: center;
  gap: var(--s3);
  padding: 9px 12px;
  cursor: pointer;
  border-bottom: var(--hair) solid var(--rule-faint);
  min-width: 0;
}
.rot-row:hover {
  background: var(--panel-hi);
}
.rot-row.open {
  background: var(--panel-hi);
}
.rot-row.in {
  box-shadow: inset 2px 0 0 var(--long);
}
.rot-row.out {
  box-shadow: inset 2px 0 0 var(--short);
}
.rot-chev {
  color: var(--ink-faint);
  text-align: right;
}
.rot-expand {
  padding: 8px 12px 12px 14px;
  border-bottom: var(--hair) solid var(--rule);
  background: var(--panel-wash);
}
.rot-expand-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  margin-bottom: 8px;
  color: var(--ink-dim);
}
.name-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.name-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel);
  color: var(--ink);
  cursor: pointer;
  font-size: var(--t-micro);
}
.name-chip:hover {
  border-color: var(--phosphor-dim);
  color: var(--phosphor);
}
.name-chip.in {
  border-left: 1px solid var(--long);
}
.name-chip.out {
  border-left: 1px solid var(--short);
}
.name-chip .fig:first-child {
  font-weight: 700;
  color: var(--phosphor);
}
.rot-etf {
  font-weight: 700;
  color: var(--phosphor);
}
.rot-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-dim);
}
.rot-bar {
  position: relative;
  height: 8px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.rot-bar i {
  display: block;
  height: 100%;
  max-width: 100%;
}
.rot-bar i.in {
  background: var(--long);
}
.rot-bar i.out {
  background: var(--short);
}
.rot-score,
.rot-rs {
  text-align: right;
  font-size: var(--t-small);
}

.sector-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--s3);
}

.sector-card {
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  padding: var(--s3);
  display: flex;
  flex-direction: column;
  gap: 4px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.sector-card:hover {
  background: var(--panel-raise);
  border-color: var(--rule-hi);
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.5);
  transform: translateY(-1px);
}
.sector-card.card-in {
  border-left: 1px solid var(--long);
}
.sector-card.card-out {
  border-left: 1px solid var(--short);
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-etf {
  font-family: var(--font-data);
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--phosphor);
}
.card-score {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
}
.card-name {
  font-size: var(--t-micro);
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-metrics {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  color: var(--ink-dim);
}

/* ---- Action Bar & Filters ------------------------------------------------ */
.action-bar {
  display: flex;
  align-items: center;
  gap: var(--s3);
}
.filter-group {
  display: flex;
  align-items: center;
  gap: 2px;
  background: var(--panel-hi);
  padding: 2px;
  border-radius: var(--r-sm);
  border: var(--hair) solid var(--rule);
}
.filter-btn {
  background: transparent;
  border: none;
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  padding: 3px 8px;
  border-radius: var(--r-xs);
  cursor: pointer;
}
.filter-btn.active {
  background: var(--panel-raise);
  color: var(--phosphor);
}

.search-input {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  color: var(--ink);
  font-size: var(--t-micro);
  padding: 3px 8px;
  border-radius: 2px;
  width: 140px;
}

/* ---- Scrollable Table Containers ---------------------------------------- */
.table-container {
  max-height: 520px;
  overflow-y: auto;
  scrollbar-width: thin;
}
.watch-expanded {
  max-height: min(70vh, 720px);
}
.pos {
  color: var(--long);
}
.neg {
  color: var(--short);
}

.grid {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-small);
}
.grid th {
  text-align: left;
  padding: var(--s3) var(--s4);
  color: var(--ink-dim);
  border-bottom: var(--hair) solid var(--rule);
  position: sticky;
  top: 0;
  background: var(--panel-hi);
  font-weight: 700;
  z-index: 1;
}
.grid td {
  padding: var(--s2) var(--s4);
  border-bottom: var(--hair) solid var(--rule-faint);
  color: var(--ink);
  vertical-align: middle;
}
.grid tbody tr {
  cursor: pointer;
}
.grid tbody tr:hover {
  background: var(--panel-raise);
}

.etf-sym,
.sym {
  color: var(--phosphor);
  font-weight: 700;
}
.name-cell {
  max-width: 18ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.num {
  text-align: right;
}
.dim {
  color: var(--ink-dim);
}

.fl-track {
  position: relative;
  height: 10px;
  background: var(--panel-hi);
  display: block;
  border-radius: 1px;
  width: 100%;
  min-width: 90px;
}
.fl-fill {
  position: absolute;
  top: 0;
  bottom: 0;
  border-radius: 1px;
}
.fl-fill.in {
  background: var(--long);
}
.fl-fill.out {
  background: var(--short);
}
.fl-mid {
  position: absolute;
  left: 50%;
  top: -2px;
  bottom: -2px;
  width: var(--hair);
  background: var(--rule-hi);
}

.note {
  color: var(--ink-dim);
  font-size: var(--t-small);
}
.note.pad {
  padding: var(--s5) var(--s4);
}
.note.pad-x {
  padding: var(--s3) var(--s4) var(--s4);
}
.note.tiny {
  font-size: var(--t-micro);
  margin-top: var(--s3);
}

@media (max-width: 1200px) {
  .summary-deck {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .sectors-view {
    grid-template-columns: 1fr;
  }
  .w-half {
    grid-column: span 1;
  }
}
</style>
