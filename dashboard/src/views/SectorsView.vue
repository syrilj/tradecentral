<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { useRouter } from 'vue-router'
import { type StatusPayload } from '@/api'
import type { Resource } from '@/composables/useResource'
import { signedPct, tone } from '@/format'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'

/**
 * Sector Rotation & Flow Analysis View.
 *
 * Dedicated tab for monitoring cross-sector ETF flow scores, relative strength
 * against benchmark, market regime indicators, and surfaced flow watch names.
 */
const status = inject<Resource<StatusPayload>>('status')!
const router = useRouter()

const watchSearch = ref('')
const selectedCategory = ref<'all' | 'in' | 'out'>('all')

const d = computed(() => status.data.value)
const flow = computed(() => d.value?.sector_flow as
  | {
      money_in?: string[]
      money_out?: string[]
      sectors_ranked?: SectorRow[]
      watch_names?: WatchRow[]
      market_context?: Record<string, number | boolean | string>
    }
  | undefined)

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
const mkt = computed(() => flow.value?.market_context)

const flowMax = computed(() =>
  Math.max(1e-6, ...sectors.value.map((s) => Math.abs(s.flow_score))),
)

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
    if (query && !w.symbol.includes(query) && !w.sector_hint.toUpperCase().includes(query) && !w.etf.includes(query)) {
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
          SPY 1D: {{ signedPct(Number(mkt?.spy_ret_1d ?? 0) * 100, 2) }} · 5D: {{ signedPct(Number(mkt?.spy_ret_5d ?? 0) * 100, 2) }}
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
          <span class="kpi-val fig">{{ accumulationSectors.length }} In / {{ distributionSectors.length }} Out</span>
          <span class="kpi-badge flat">BREADTH</span>
        </div>
        <span class="kpi-sub">
          {{ sectors.length }} sector ETFs tracked
        </span>
      </div>
    </div>

    <!-- ── 01 Market Context Strip & Cards ────────────────────────────── -->
    <Panel label="Market Context & Sector Heatmap" index="01" :meta="mkt ? `vs ${mkt.benchmark}` : ''" class="w-full">
      <div v-if="mkt" class="mkt-readouts">
        <Readout label="SPY 1D Return" :value="signedPct(Number(mkt.spy_ret_1d) * 100)" :tone="tone(mkt.spy_ret_1d)" size="sm" />
        <Readout label="SPY 5D Return" :value="signedPct(Number(mkt.spy_ret_5d) * 100)" :tone="tone(mkt.spy_ret_5d)" size="sm" />
        <Readout label="SPY 21D Return" :value="signedPct(Number(mkt.spy_ret_21d) * 100)" :tone="tone(mkt.spy_ret_21d)" size="sm" />
        <Readout
          label="SPY Trend"
          :value="mkt.spy_above_ma20 ? 'ABOVE MA20' : 'BELOW MA20'"
          :tone="mkt.spy_above_ma20 ? 'pos' : 'neg'"
          size="sm"
        />
        <Readout label="QQQ 5D RS vs SPY" :value="signedPct(Number(mkt.qqq_spy_rs_5d) * 100)" :tone="tone(mkt.qqq_spy_rs_5d)" size="sm" />
      </div>

      <div v-if="sectors.length" class="sector-cards-grid">
        <div
          v-for="s in sectors"
          :key="s.etf"
          class="sector-card"
          :class="s.flow_score >= 0 ? 'card-in' : 'card-out'"
          @click="open(s.etf)"
        >
          <div class="card-top">
            <span class="card-etf fig">{{ s.etf }}</span>
            <span class="card-score fig" :class="tone(s.flow_score)">
              {{ signedPct(s.flow_score * 100, 1) }}
            </span>
          </div>
          <span class="card-name label" :title="s.name">{{ s.name }}</span>
          <div class="card-metrics">
            <span class="label">5D: <b :class="tone(s.ret_5d)">{{ signedPct(s.ret_5d * 100, 1) }}</b></span>
            <span class="label">5D RS: <b :class="tone(s.rs_5d)">{{ signedPct(s.rs_5d * 100, 1) }}</b></span>
          </div>
        </div>
      </div>
      <p v-else class="note pad">No sector flow data available.</p>
    </Panel>

    <!-- ── 02 Detailed Sector Flow Table ──────────────────────────────── -->
    <Panel label="Bi-Directional Sector Flow Distribution" index="02" :meta="`${sectors.length} sectors`" class="w-half" flush>
      <div class="table-container">
        <table v-if="sectors.length" class="grid">
          <thead>
            <tr>
              <th class="label">ETF</th>
              <th class="label">Sector Name</th>
              <th class="label">Flow Distribution</th>
              <th class="label num">5D Return</th>
              <th class="label num">5D RS</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in sectors" :key="s.etf" @click="open(s.etf)">
              <td class="fig etf-sym">{{ s.etf }}</td>
              <td class="label name-cell" :title="s.name">{{ s.name }}</td>
              <td>
                <span class="fl-track" aria-hidden="true">
                  <b class="fl-mid" />
                  <i
                    class="fl-fill"
                    :class="s.flow_score >= 0 ? 'in' : 'out'"
                    :style="
                      s.flow_score >= 0
                        ? { left: '50%', width: `${(s.flow_score / flowMax) * 50}%` }
                        : { right: '50%', width: `${(-s.flow_score / flowMax) * 50}%` }
                    "
                  />
                </span>
              </td>
              <td class="fig num" :class="tone(s.ret_5d)">{{ signedPct(s.ret_5d * 100, 2) }}</td>
              <td class="fig num" :class="tone(s.rs_5d)">{{ signedPct(s.rs_5d * 100, 2) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">No sector data loaded.</p>
      </div>

      <p class="note tiny pad-x">
        Flow score bars are zero-centered: right indicates accumulation (money in), left indicates distribution (money out).
        <strong>5D RS</strong> is return relative to {{ mkt?.benchmark ?? 'the benchmark' }}.
      </p>
    </Panel>

    <!-- ── 03 Flow Watch Names ────────────────────────────────────────── -->
    <Panel label="Surfaced Flow Watch Names" index="03" :meta="`${watch.length} names`" class="w-half" flush>
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

      <div class="table-container">
        <table v-if="filteredWatch.length" class="grid">
          <thead>
            <tr>
              <th class="label">Symbol</th>
              <th class="label">Sector / ETF</th>
              <th class="label num">Flow Score</th>
              <th class="label num">5D RS vs SPY</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(w, i) in filteredWatch" :key="i" @click="open(w.symbol)">
              <td class="fig sym">{{ w.symbol }}</td>
              <td class="label dim">{{ w.sector_hint }} · {{ w.etf }}</td>
              <td class="fig num" :class="tone(w.score)">{{ signedPct(w.score * 100, 2) }}</td>
              <td class="fig num" :class="tone(w.rs_5d)">{{ signedPct(w.rs_5d * 100, 2) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">
          {{ watch.length === 0 ? 'No watch names surfaced by the flow engine.' : 'No watch names match the filter.' }}
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
.w-full { grid-column: 1 / -1; }
.w-half { grid-column: span 2; }

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
  border-radius: 4px;
  padding: var(--s3) var(--s4);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.kpi-card.armed { border-color: rgba(34, 197, 94, 0.3); }
.kpi-card.held { border-color: rgba(239, 68, 68, 0.3); }

.kpi-label {
  font-size: 10px;
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
  font-family: var(--font-mono);
  font-size: 1.2rem;
  font-weight: 700;
  color: var(--ink);
}

.kpi-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  text-transform: uppercase;
}
.kpi-badge.pos { color: var(--long); background: rgba(34, 197, 94, 0.12); }
.kpi-badge.neg { color: var(--short); background: rgba(239, 68, 68, 0.12); }
.kpi-badge.flat { color: var(--ink-dim); background: var(--rule); }

.kpi-sub { font-size: 11px; color: var(--ink-dim); }
.fl-truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ---- Market Context Strip & Cards --------------------------------------- */
.mkt-readouts {
  display: flex;
  gap: var(--s5);
  flex-wrap: wrap;
  padding-bottom: var(--s4);
  margin-bottom: var(--s4);
  border-bottom: var(--hair) solid var(--rule);
}

.sector-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--s3);
}

.sector-card {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  border-radius: 4px;
  padding: var(--s3);
  display: flex;
  flex-direction: column;
  gap: 4px;
  cursor: pointer;
  transition: all var(--dur-fast);
}
.sector-card:hover {
  background: var(--panel-raise);
  border-color: var(--rule-hi);
  transform: translateY(-1px);
}
.sector-card.card-in { border-left: 3px solid var(--long); }
.sector-card.card-out { border-left: 3px solid var(--short); }

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-etf { font-size: 1.1rem; font-weight: 800; color: var(--phosphor); }
.card-score { font-size: 11px; font-weight: 700; }
.card-name { font-size: 11px; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.card-metrics {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  font-size: 10px;
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
  border-radius: 3px;
  border: var(--hair) solid var(--rule);
}
.filter-btn {
  background: transparent;
  border: none;
  color: var(--ink-dim);
  font-size: 10px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 2px;
  cursor: pointer;
}
.filter-btn.active { background: var(--panel-raise); color: var(--phosphor); }

.search-input {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  color: var(--ink);
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 3px;
  width: 140px;
}

/* ---- Scrollable Table Containers ---------------------------------------- */
.table-container {
  max-height: 520px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.grid { width: 100%; border-collapse: collapse; font-size: var(--t-small); }
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
.grid td { padding: var(--s2) var(--s4); border-bottom: var(--hair) solid var(--rule-faint); color: var(--ink); vertical-align: middle; }
.grid tbody tr { cursor: pointer; }
.grid tbody tr:hover { background: var(--panel-raise); }

.etf-sym, .sym { color: var(--phosphor); font-weight: 700; }
.name-cell { max-width: 18ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.num { text-align: right; }
.dim { color: var(--ink-dim); }

.fl-track { position: relative; height: 10px; background: var(--panel-hi); display: block; border-radius: 2px; width: 100%; min-width: 90px; }
.fl-fill { position: absolute; top: 0; bottom: 0; border-radius: 2px; }
.fl-fill.in { background: var(--long); }
.fl-fill.out { background: var(--short); }
.fl-mid { position: absolute; left: 50%; top: -2px; bottom: -2px; width: var(--hair); background: var(--rule-hi); }

.note { color: var(--ink-dim); font-size: var(--t-small); }
.note.pad { padding: var(--s5) var(--s4); }
.note.pad-x { padding: var(--s3) var(--s4) var(--s4); }
.note.tiny { font-size: 11px; margin-top: var(--s3); }

@media (max-width: 1200px) {
  .summary-deck { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sectors-view { grid-template-columns: 1fr; }
  .w-half { grid-column: span 1; }
}
</style>
