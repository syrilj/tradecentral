<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, type MomentumCandidate } from '@/api'
import { useResource } from '@/composables/useResource'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import LoadingState from '@/components/LoadingState.vue'
import HelpTip from '@/components/HelpTip.vue'
import { num, usd } from '@/format'

type FilterMode = 'QUALIFYING' | 'WATCHLIST' | 'TOP_RVOL' | 'TOP_GAP' | 'ALL'
type SortKey =
  'symbol' | 'price' | 'gap_pct' | 'day_change_pct' | 'rvol' | 'float_shares' | 'pillars_met'

const scan = useResource(() => api.momentumScan(), { intervalMs: 300_000 })

const filterMode = ref<FilterMode>('WATCHLIST')
const searchFilter = ref('')
const sortKey = ref<SortKey>('rvol')
const sortDir = ref<'asc' | 'desc'>('desc')

const allRawCandidates = computed<MomentumCandidate[]>(() => {
  const payload = scan.data.value
  if (!payload) return []
  if (payload.all_candidates && payload.all_candidates.length > 0) {
    return payload.all_candidates
  }
  return payload.candidates ?? []
})

const qualifyingCount = computed(
  () => (scan.data.value?.candidates ?? []).filter((c) => c.pillars_met === 3).length,
)
const universeSize = computed(() => scan.data.value?.universe_size ?? 0)

const topRvolSymbol = computed(() => {
  if (!allRawCandidates.value.length) return null
  const top = [...allRawCandidates.value].sort((a, b) => (b.rvol ?? 0) - (a.rvol ?? 0))[0]
  return top && (top.rvol ?? 0) > 0 ? top : null
})

function pct(v: number | null): string {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
}

function rvolTxt(v: number | null): string {
  return v == null ? '—' : `${v.toFixed(1)}×`
}

function floatTxt(shares: number | null): string {
  if (shares == null) return 'n/a'
  return `${(shares / 1_000_000).toFixed(1)}M`
}

function setSort(key: SortKey): void {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortKey.value = key
    sortDir.value = key === 'symbol' ? 'asc' : 'desc'
  }
}

function sortArrow(key: SortKey): string {
  if (sortKey.value !== key) return ''
  return sortDir.value === 'asc' ? '▴' : '▾'
}

function sortValue(c: MomentumCandidate, key: SortKey): number | string {
  switch (key) {
    case 'symbol':
      return c.symbol
    case 'price':
      return c.price
    case 'gap_pct':
      return c.gap_pct ?? -Infinity
    case 'day_change_pct':
      return c.day_change_pct ?? -Infinity
    case 'rvol':
      return c.rvol ?? -Infinity
    case 'float_shares':
      return c.float_shares ?? -Infinity
    case 'pillars_met':
      return c.pillars_met
    default:
      return 0
  }
}

const filteredCandidates = computed(() => {
  let list = [...allRawCandidates.value]
  const mode = filterMode.value
  if (mode === 'QUALIFYING') {
    list = list.filter((c) => c.pillars_met === 3)
  } else if (mode === 'WATCHLIST') {
    list = list.filter((c) => c.pillars_met >= 1)
  } else if (mode === 'TOP_RVOL') {
    list = list.filter((c) => (c.rvol ?? 0) >= 1.0)
  } else if (mode === 'TOP_GAP') {
    list = list.filter((c) => (c.gap_pct ?? 0) >= 0.01)
  }

  const query = searchFilter.value.trim().toUpperCase()
  if (query) {
    list = list.filter((c) => c.symbol.toUpperCase().includes(query))
  }

  const dir = sortDir.value === 'asc' ? 1 : -1
  const k = sortKey.value
  list.sort((a, b) => {
    const av = sortValue(a, k)
    const bv = sortValue(b, k)
    if (typeof av === 'string' || typeof bv === 'string') {
      return dir * String(av).localeCompare(String(bv))
    }
    return dir * (av - bv)
  })

  return list
})
</script>

<template>
  <div class="momentum-view">
    <Panel
      label="Momentum Pre-Scan"
      index="14"
      :meta="scan.data.value ? `asof ${scan.data.value.asof}` : 'Five Pillars Scanner'"
      :live="!scan.error.value"
      class="w-full"
    >
      <template #action>
        <button
          type="button"
          class="refresh-btn label"
          :disabled="scan.loading.value"
          title="Force refresh momentum scan"
          @click="scan.refresh({ clear: false })"
        >
          <span class="refresh-icon" :class="{ spinning: scan.loading.value }">↻</span>
          {{ scan.loading.value ? 'SCANNING…' : 'REFRESH SCAN' }}
        </button>
      </template>

      <div class="banner label">
        <span>
          Pre-market watchlist · Ross Cameron Five Pillars (Price $2–$20, Gap ≥2%, RVOL >5×, Low
          Float) · Scanning
          {{ scan.data.value ? num(scan.data.value.universe_size, 0) : '—' }} symbols
        </span>
        <HelpTip
          label="Five Pillars Criteria"
          text="1. Price: $2.00 to $20.00 sweet spot. 2. Gap: ≥ +2.0% (10%-30% optimal). 3. Relative Volume (RVOL): > 5.0x 50-day average. 4. Float: < 20M shares (optimal < 3M). 5. Catalyst: high news volume."
        />
      </div>

      <div v-if="scan.data.value" class="readout-grid">
        <Readout
          label="Qualifying (3/3)"
          :value="String(qualifyingCount)"
          sub="Meet Price + Gap + RVOL"
          :tone="qualifyingCount > 0 ? 'pos' : 'flat'"
        />
        <Readout
          label="Scanned Universe"
          :value="num(universeSize, 0)"
          :sub="`Float coverage: ${num(scan.data.value.float_coverage_pct, 1)}%`"
          tone="accent"
        />
        <Readout
          label="Top Vol Spiker"
          :value="topRvolSymbol ? topRvolSymbol.symbol : '—'"
          :sub="topRvolSymbol ? `${rvolTxt(topRvolSymbol.rvol)} RVOL` : 'No volume spike'"
          :tone="topRvolSymbol ? 'accent' : 'flat'"
        />
      </div>

      <div class="toolbar">
        <div class="filter-tabs">
          <button
            type="button"
            class="tab-btn label"
            :class="{ active: filterMode === 'WATCHLIST' }"
            @click="filterMode = 'WATCHLIST'"
          >
            Watchlist (1+ Pillars)
          </button>
          <button
            type="button"
            class="tab-btn label"
            :class="{ active: filterMode === 'QUALIFYING' }"
            @click="filterMode = 'QUALIFYING'"
          >
            Qualifying (3/3) · {{ qualifyingCount }}
          </button>
          <button
            type="button"
            class="tab-btn label"
            :class="{ active: filterMode === 'TOP_RVOL' }"
            @click="filterMode = 'TOP_RVOL'"
          >
            High RVOL (≥1.0×)
          </button>
          <button
            type="button"
            class="tab-btn label"
            :class="{ active: filterMode === 'TOP_GAP' }"
            @click="filterMode = 'TOP_GAP'"
          >
            Gap Movers (≥1.0%)
          </button>
          <button
            type="button"
            class="tab-btn label"
            :class="{ active: filterMode === 'ALL' }"
            @click="filterMode = 'ALL'"
          >
            All Universe ({{ allRawCandidates.length }})
          </button>
        </div>

        <div class="toolbar-right">
          <button
            type="button"
            class="scan-action-btn label"
            :disabled="scan.loading.value"
            @click="scan.refresh({ clear: false })"
          >
            <span class="refresh-icon" :class="{ spinning: scan.loading.value }">↻</span>
            {{ scan.loading.value ? 'SCANNING...' : 'REFRESH SCAN' }}
          </button>
          <div class="search-box">
            <input
              v-model="searchFilter"
              type="text"
              class="search-input"
              placeholder="FILTER TICKER..."
              spellcheck="false"
            />
          </div>
        </div>
      </div>

      <LoadingState
        v-if="scan.loading.value && !scan.data.value"
        label="Scanning universe for momentum candidates..."
      />
      <p v-else-if="scan.error.value" class="state err label">{{ scan.error.value }}</p>

      <div v-else-if="!filteredCandidates.length" class="empty-state">
        <p class="state label">
          No candidates match filter "{{ filterMode }}"
          {{ searchFilter ? `for search '${searchFilter}'` : '' }}.
        </p>
        <p class="subnote label">Try switching to the Watchlist or All Universe tab above.</p>
      </div>

      <div v-else class="table-container">
        <table class="mtable">
          <thead>
            <tr>
              <th class="sortable" @click="setSort('symbol')">Symbol {{ sortArrow('symbol') }}</th>
              <th class="sortable fig" @click="setSort('price')">Price {{ sortArrow('price') }}</th>
              <th class="sortable fig" @click="setSort('gap_pct')">
                Gap % {{ sortArrow('gap_pct') }}
              </th>
              <th class="sortable fig" @click="setSort('day_change_pct')">
                Day Chg {{ sortArrow('day_change_pct') }}
              </th>
              <th class="sortable fig" @click="setSort('rvol')">RVOL {{ sortArrow('rvol') }}</th>
              <th class="sortable fig" @click="setSort('float_shares')">
                Float {{ sortArrow('float_shares') }}
              </th>
              <th class="sortable fig" @click="setSort('pillars_met')">
                Pillars {{ sortArrow('pillars_met') }}
              </th>
              <th>Quick Links</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="c in filteredCandidates"
              :key="c.symbol"
              :class="{ qualifying: c.pillars_met === 3 }"
            >
              <td class="sym">
                <span class="sym-ticker">{{ c.symbol }}</span>
              </td>
              <td class="fig">
                <span :class="['pillar-pill', c.price_qualifies ? 'pass' : 'fail']">
                  {{ usd(c.price) }}
                </span>
              </td>
              <td class="fig">
                <span
                  :class="[
                    'pillar-pill',
                    c.gap_qualifies ? 'pass' : 'fail',
                    { sweet: c.gap_sweet_spot },
                  ]"
                >
                  {{ pct(c.gap_pct) }}
                </span>
              </td>
              <td class="fig" :class="[(c.day_change_pct ?? 0) >= 0 ? 'pos' : 'neg']">
                {{ pct(c.day_change_pct) }}
              </td>
              <td class="fig">
                <span
                  :class="[
                    'pillar-pill',
                    c.rvol_qualifies ? 'pass' : (c.rvol ?? 0) >= 1.5 ? 'warn' : 'fail',
                  ]"
                >
                  {{ rvolTxt(c.rvol) }}
                </span>
              </td>
              <td class="fig">
                <span class="badge" :class="c.float_badge">{{ floatTxt(c.float_shares) }}</span>
              </td>
              <td class="fig">
                <span class="pillar-score" :class="`p-${c.pillars_met}`">
                  {{ c.pillars_met }}/3
                </span>
              </td>
              <td class="links-cell">
                <RouterLink
                  :to="{ name: 'market', query: { symbol: c.symbol } }"
                  class="qlink label"
                  >Market</RouterLink
                >
                <RouterLink
                  :to="{ name: 'options', query: { symbol: c.symbol } }"
                  class="qlink label"
                  >Options</RouterLink
                >
                <RouterLink
                  :to="{ name: 'changepoints', query: { symbol: c.symbol } }"
                  class="qlink label"
                  >Breaks</RouterLink
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Panel>
  </div>
</template>

<style scoped>
.momentum-view {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  width: 100%;
  max-width: none;
  min-width: 0;
}

.w-full {
  width: 100%;
  min-width: 0;
}

.banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--s3);
  color: var(--ink-soft);
  font-size: var(--t-small);
  border-bottom: var(--hair) solid var(--rule);
  background: var(--void-lift);
}

.readout-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s3);
  padding: var(--s3);
  border-bottom: var(--hair) solid var(--rule);
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
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
  background: var(--void-lift);
  color: var(--ink-dim);
  cursor: pointer;
  transition: all 0.12s ease;
}
.tab-btn:hover {
  color: var(--ink);
  border-color: var(--phosphor-dim);
}
.tab-btn.active {
  color: var(--phosphor);
  border-color: var(--phosphor);
  background: var(--phosphor-wash);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.refresh-btn,
.scan-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  height: 28px;
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-micro);
  letter-spacing: 0.05em;
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
  cursor: pointer;
  transition: all 0.12s ease;
}
.refresh-btn:hover:not(:disabled),
.scan-action-btn:hover:not(:disabled) {
  background: var(--phosphor);
  color: var(--void);
}
.refresh-btn:disabled,
.scan-action-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.refresh-icon {
  display: inline-block;
  font-size: 0.9rem;
  line-height: 1;
}
.refresh-icon.spinning {
  animation: spin var(--dur-spin) linear infinite;
}
@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.search-box {
  flex: 0 0 auto;
}
.search-input {
  width: 160px;
  height: 28px;
  padding: 0 8px;
  font: 600 0.8rem var(--font-data);
  letter-spacing: 0.04em;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  color: var(--ink);
}

.table-container {
  max-height: 580px;
  overflow: auto;
}

.mtable {
  width: 100%;
  border-collapse: collapse;
}

.mtable th {
  text-align: right;
  padding: var(--s2) var(--s3);
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border-bottom: var(--hair) solid var(--rule);
  user-select: none;
}
.mtable th.sortable {
  cursor: pointer;
}
.mtable th.sortable:hover {
  color: var(--ink);
}
.mtable th:first-child,
.mtable td.sym {
  text-align: left;
}
.mtable th:last-child {
  text-align: center;
}

.mtable td {
  text-align: right;
  padding: var(--s2) var(--s3);
  border-bottom: var(--hair) solid var(--rule-faint);
  font-variant-numeric: tabular-nums;
}

.sym-ticker {
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-small);
  color: var(--ink);
}

.pillar-pill {
  display: inline-block;
  padding: 1px 5px;
  font-family: var(--font-data);
  border-radius: 2px;
}
.pillar-pill.pass {
  color: var(--go);
  background: var(--long-wash);
}
.pillar-pill.sweet {
  color: var(--phosphor);
  font-weight: 700;
  background: var(--phosphor-wash);
}
.pillar-pill.warn {
  color: var(--warn);
}
.pillar-pill.fail {
  color: var(--ink-faint);
}

.badge {
  padding: 1px 6px;
  border: var(--hair) solid var(--rule-hi);
  font-size: var(--t-micro);
  font-family: var(--font-data);
}
.badge.optimal {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.badge.qualifies {
  color: var(--ink);
}
.badge.no {
  color: var(--ink-faint);
}
.badge.unknown {
  color: var(--ink-ghost);
  font-style: italic;
}

.pillar-score {
  font-family: var(--font-data);
  font-weight: 700;
  padding: 2px 6px;
}
.pillar-score.p-3 {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
}
.pillar-score.p-2 {
  color: var(--warn);
}
.pillar-score.p-1 {
  color: var(--ink-dim);
}
.pillar-score.p-0 {
  color: var(--ink-ghost);
}

.links-cell {
  display: flex;
  justify-content: center;
  gap: var(--s2);
}
.qlink {
  padding: 2px 6px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
  text-decoration: none;
  font-size: var(--t-micro);
}
.qlink:hover {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

.pos {
  color: var(--long);
}
.neg {
  color: var(--short);
}

.empty-state {
  padding: var(--s6) var(--s4);
  text-align: center;
}
.subnote {
  margin-top: var(--s2);
  color: var(--ink-ghost);
  font-size: var(--t-small);
}
</style>
