<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { SupplyChainNode } from '@/api'
import {
  elasticityTone,
  formatCapExSensitivity,
  formatRevConcentration,
  optionsSkewLabel,
  rankBeneficiaries,
  tierBadgeLabel,
  tierColorClass,
} from '@/chainDisplay'

const props = defineProps<{
  nodes: SupplyChainNode[]
  selectedSymbol?: string | null
}>()

const emit = defineEmits<{
  (e: 'select-ticker', symbol: string): void
  (e: 'inspect-evidence', symbol: string): void
  (e: 'focus-ticker', symbol: string): void
}>()

const router = useRouter()
const activeFilter = ref<string>('all')
const searchFilter = ref<string>('')
const sortBy = ref<'elasticity' | 'sensitivity' | 'concentration' | 'pe'>('elasticity')
const sortAsc = ref<boolean>(false)

const filters = [
  { id: 'all', label: 'All Beneficiaries' },
  { id: 'space', label: 'Space & Direct-to-Cell' },
  { id: 'optic', label: 'Optics & Lasers' },
  { id: 'memory', label: 'Memory & Storage' },
  { id: 'cooling', label: 'Liquid Cooling' },
  { id: 'power', label: 'Power & Nuclear SMRs' },
  { id: 'glp1', label: 'GLP-1 & CDMO' },
  { id: 'foundry', label: 'Foundry & Metrology' },
  { id: 'robotics', label: 'Robotics & Vision' },
  { id: 'quantum', label: 'Quantum Systems' },
  { id: 'software', label: 'Enterprise AI' },
]

function setFilter(id: string) {
  activeFilter.value = id
}

function toggleSort(field: 'elasticity' | 'sensitivity' | 'concentration' | 'pe') {
  if (sortBy.value === field) {
    sortAsc.value = !sortAsc.value
  } else {
    sortBy.value = field
    sortAsc.value = false
  }
}

const displayRows = computed(() => {
  let list = rankBeneficiaries(props.nodes, activeFilter.value)

  if (searchFilter.value.trim()) {
    const q = searchFilter.value.trim().toLowerCase()
    list = list.filter(
      (n) =>
        n.symbol.toLowerCase().includes(q) ||
        n.name.toLowerCase().includes(q) ||
        n.sub_industry.toLowerCase().includes(q),
    )
  }

  return list.sort((a, b) => {
    let valA = 0
    let valB = 0
    if (sortBy.value === 'elasticity') {
      valA = a.metrics?.elasticity_score ?? 0
      valB = b.metrics?.elasticity_score ?? 0
    } else if (sortBy.value === 'sensitivity') {
      valA = a.metrics?.capex_sensitivity ?? 0
      valB = b.metrics?.capex_sensitivity ?? 0
    } else if (sortBy.value === 'concentration') {
      valA = a.metrics?.revenue_concentration_pct ?? 0
      valB = b.metrics?.revenue_concentration_pct ?? 0
    } else if (sortBy.value === 'pe') {
      valA = a.metrics?.forward_pe ?? 999
      valB = b.metrics?.forward_pe ?? 999
    }
    return sortAsc.value ? valA - valB : valB - valA
  })
})

function navOptions(symbol: string) {
  void router.push({ name: 'options', query: { symbol } })
}

function navMarket(symbol: string) {
  void router.push({ name: 'market', query: { symbol } })
}
</script>

<template>
  <div class="beneficiary-table-wrap" data-test="beneficiary-table">
    <div class="table-toolbar">
      <div class="filter-pills">
        <button
          v-for="f in filters"
          :key="f.id"
          type="button"
          class="filter-pill"
          :class="{ active: activeFilter === f.id }"
          @click="setFilter(f.id)"
        >
          {{ f.label }}
        </button>
      </div>

      <div class="search-box">
        <input
          v-model="searchFilter"
          type="text"
          placeholder="Filter ticker / sub-industry..."
          class="search-input"
        />
      </div>
    </div>

    <div class="table-scroll">
      <table class="matrix-table">
        <thead>
          <tr>
            <th class="col-ticker">TICKER / COMPANY</th>
            <th class="col-sub">SUB-INDUSTRY</th>
            <th class="col-tier">TIER</th>
            <th class="col-sortable col-num" @click="toggleSort('elasticity')">
              ELASTICITY SCORE
              <span class="sort-indicator">{{
                sortBy === 'elasticity' ? (sortAsc ? '▲' : '▼') : ''
              }}</span>
            </th>
            <th class="col-sortable col-num" @click="toggleSort('sensitivity')">
              CAPEX SENS.
              <span class="sort-indicator">{{
                sortBy === 'sensitivity' ? (sortAsc ? '▲' : '▼') : ''
              }}</span>
            </th>
            <th class="col-sortable col-num" @click="toggleSort('concentration')">
              REV CONC. %
              <span class="sort-indicator">{{
                sortBy === 'concentration' ? (sortAsc ? '▲' : '▼') : ''
              }}</span>
            </th>
            <th class="col-sortable col-num" @click="toggleSort('pe')">
              FWD P/E
              <span class="sort-indicator">{{ sortBy === 'pe' ? (sortAsc ? '▲' : '▼') : '' }}</span>
            </th>
            <th class="col-skew">OPTIONS SKEW</th>
            <th class="col-evidence">CITATIONS</th>
            <th class="col-actions">TRADE DESK</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="n in displayRows"
            :key="n.symbol"
            class="table-row"
            :class="{ selected: selectedSymbol === n.symbol }"
            @click="emit('select-ticker', n.symbol)"
          >
            <td class="col-ticker">
              <div class="ticker-identity">
                <span class="sym-badge">{{ n.symbol }}</span>
                <span class="sym-name">{{ n.name }}</span>
              </div>
            </td>

            <td class="col-sub">
              <span class="sub-pill">{{ n.sub_industry }}</span>
            </td>

            <td class="col-tier">
              <span class="tier-pill" :class="tierColorClass(n.tier)">
                {{ tierBadgeLabel(n.tier) }}
              </span>
            </td>

            <td class="col-num">
              <div class="elasticity-cell">
                <span
                  class="score-chip"
                  :class="`chip-${elasticityTone(n.metrics?.elasticity_score)}`"
                >
                  {{ n.metrics?.elasticity_score?.toFixed(1) ?? '—' }}
                </span>
                <div class="score-bar-bg">
                  <div
                    class="score-bar-fill"
                    :class="`bar-${elasticityTone(n.metrics?.elasticity_score)}`"
                    :style="{ width: `${Math.min(100, n.metrics?.elasticity_score ?? 0)}%` }"
                  />
                </div>
              </div>
            </td>

            <td class="col-num font-mono">
              <span class="sens-val">{{
                formatCapExSensitivity(n.metrics?.capex_sensitivity)
              }}</span>
            </td>

            <td class="col-num font-mono">
              <div class="conc-cell">
                <span>{{ formatRevConcentration(n.metrics?.revenue_concentration_pct) }}</span>
                <div class="conc-mini-bar">
                  <div
                    class="conc-mini-fill"
                    :style="{
                      width: `${Math.min(100, (n.metrics?.revenue_concentration_pct ?? 0) * 1.5)}%`,
                    }"
                  />
                </div>
              </div>
            </td>

            <td class="col-num font-mono">
              {{ n.metrics?.forward_pe != null ? `${n.metrics.forward_pe.toFixed(1)}x` : '—' }}
            </td>

            <td class="col-skew">
              <span
                v-if="optionsSkewLabel(n.metrics?.options_skew)"
                class="skew-tag"
                :class="`skew-${optionsSkewLabel(n.metrics?.options_skew)!.tone}`"
              >
                {{ optionsSkewLabel(n.metrics?.options_skew)!.label }}
              </span>
              <span v-else class="skew-na">—</span>
            </td>

            <td class="col-evidence">
              <button
                type="button"
                class="citation-btn"
                @click.stop="emit('inspect-evidence', n.symbol)"
              >
                {{ n.evidence?.length ?? 0 }} quotes ↗
              </button>
            </td>

            <td class="col-actions" @click.stop>
              <div class="action-buttons">
                <button
                  type="button"
                  class="action-btn focus-chain-btn"
                  title="Focus value chain on this stock"
                  @click="emit('focus-ticker', n.symbol)"
                >
                  CHAIN
                </button>
                <button
                  type="button"
                  class="action-btn"
                  title="View Options Drift"
                  @click="navOptions(n.symbol)"
                >
                  OPT
                </button>
                <button
                  type="button"
                  class="action-btn"
                  title="View Market Profile"
                  @click="navMarket(n.symbol)"
                >
                  MKT
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="!displayRows.length">
            <td colspan="10" class="empty-state">
              No supply chain beneficiaries match the selected filter.
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.beneficiary-table-wrap {
  background: var(--panel);
  border: 1px solid var(--rule);
  display: flex;
  flex-direction: column;
  font-family: var(--font-sans, system-ui, sans-serif);
}

.table-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: var(--void-lift);
  border-bottom: 1px solid var(--rule);
}

.filter-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.filter-pill {
  padding: 0.3rem 0.55rem;
  background: var(--panel);
  border: 1px solid var(--rule);
  color: var(--ink-dim);
  font-size: 0.72rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.filter-pill:hover {
  background: var(--panel-raise);
  color: var(--ink);
}

.filter-pill.active {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
  color: var(--phosphor);
}

.search-input {
  background: var(--void);
  border: 1px solid var(--rule);
  color: var(--ink);
  padding: 0.3rem 0.6rem;
  font-size: 0.75rem;
  width: 200px;
}

.search-input:focus {
  outline: none;
  border-color: var(--phosphor);
}

.table-scroll {
  overflow-x: auto;
}

.matrix-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.76rem;
  text-align: left;
}

th {
  background: var(--void-lift);
  color: var(--ink-faint);
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid var(--rule);
  white-space: nowrap;
}

.col-sortable {
  cursor: pointer;
  user-select: none;
}

.col-sortable:hover {
  color: var(--ink);
}

.col-num {
  text-align: right;
}

td {
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid var(--rule-faint);
  color: var(--ink);
  vertical-align: middle;
}

.table-row {
  cursor: pointer;
  transition: background 0.1s ease;
}

.table-row:hover {
  background: var(--panel-hi);
}

.table-row.selected {
  background: var(--panel-raise);
  border-left: 1px solid var(--phosphor);
}

.ticker-identity {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.sym-badge {
  font-family: var(--font-mono, monospace);
  font-weight: 700;
  color: var(--ink);
  font-size: 0.82rem;
}

.sym-name {
  color: var(--ink-dim);
  font-size: 0.7rem;
  white-space: nowrap;
}

.sub-pill {
  font-size: 0.68rem;
  color: var(--ink-soft);
}

.tier-pill {
  font-size: var(--t-nano);
  padding: 0.15rem 0.35rem;
  background: var(--void-lift);
  border: 1px solid var(--rule);
  color: var(--ink-dim);
  text-transform: uppercase;
}

.tier-pill.badge-tier1 {
  border-color: var(--call);
  color: var(--call-hi);
}

.elasticity-cell {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem;
}

.score-chip {
  font-family: var(--font-mono, monospace);
  font-weight: 700;
  padding: 0.1rem 0.35rem;
  font-size: 0.72rem;
}

.chip-up {
  background: var(--long-wash);
  color: var(--long);
}

.chip-warm {
  background: var(--call-wash);
  color: var(--call-hi);
}

.chip-cool {
  background: var(--panel-raise);
  color: var(--ink-dim);
}

.score-bar-bg {
  width: 48px;
  height: 4px;
  background: var(--void);
  border-radius: 1px;
  overflow: hidden;
}

.score-bar-fill {
  height: 100%;
}

.bar-up {
  background: var(--long);
}

.bar-warm {
  background: var(--call);
}

.bar-cool {
  background: var(--ink-faint);
}

.font-mono {
  font-family: var(--font-mono, monospace);
}

.sens-val {
  color: var(--long);
  font-weight: 600;
}

.conc-cell {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.4rem;
}

.conc-mini-bar {
  width: 32px;
  height: 3px;
  background: var(--void);
}

.conc-mini-fill {
  height: 100%;
  background: var(--call-hi);
}

.skew-tag {
  font-size: 0.65rem;
  padding: 0.15rem 0.35rem;
}

.skew-na {
  color: var(--ink-faint);
  font-size: 0.65rem;
}

.skew-up {
  background: var(--long-wash);
  color: var(--long);
}

.skew-warm {
  background: var(--call-wash);
  color: var(--call-hi);
}

.skew-cool {
  background: var(--panel-raise);
  color: var(--ink-dim);
}

.citation-btn {
  background: transparent;
  border: 1px solid var(--rule-hi);
  color: var(--ink-dim);
  font-size: 0.65rem;
  padding: 0.2rem 0.4rem;
  cursor: pointer;
}

.citation-btn:hover {
  border-color: var(--phosphor);
  color: var(--phosphor);
}

.action-buttons {
  display: flex;
  gap: 0.25rem;
}

.action-btn {
  background: var(--void-lift);
  border: 1px solid var(--rule);
  color: var(--ink-dim);
  font-family: var(--font-mono, monospace);
  font-size: var(--t-nano);
  padding: 0.15rem 0.35rem;
  cursor: pointer;
}

.action-btn:hover {
  background: var(--panel-raise);
  color: var(--ink);
  border-color: var(--rule-hi);
}

.action-btn.focus-chain-btn {
  background: var(--phosphor-wash);
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

.action-btn.focus-chain-btn:hover {
  background: var(--phosphor);
  color: var(--void);
}

.empty-state {
  text-align: center;
  padding: 2rem;
  color: var(--ink-faint);
}
</style>
