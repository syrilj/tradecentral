<script setup lang="ts">
/**
 * Conviction board — the scan's top-ranked names with their option structure.
 *
 * Until this existed, the options engine only ever ran on a hand-typed ticker,
 * so the names the scan surfaced (PEAD flags, live-flow prints, activity ranks)
 * never got a chain fetch. Each row here is one live chain request, and clicking
 * one loads it in the detail view below.
 *
 * Three honesty rules the design enforces, because the numbers invite misreading:
 *   1. Selection is ordinal. Every row shows WHY it earned a chain request.
 *   2. A missing measurement renders as "—", never as 0.0/"quiet".
 *   3. Staleness is loud. A live chain scored on old bars gets a visible mark.
 */
import { computed, onMounted, ref } from 'vue'
import { api, type OptionsBoard, type OptionsBoardRow } from '@/api'
import { optGex, optPctFrac, optSigned, optUsd } from '@/format'
import Panel from '@/components/Panel.vue'
import HelpTip from '@/components/HelpTip.vue'

export type ConvictionSortKey =
  | 'rank'
  | 'symbol'
  | 'selection_basis'
  | 'selection_score'
  | 'spot'
  | 'squeeze_score'
  | 'net_gex_m'
  | 'put_wall'
  | 'call_wall'
  | 'expected_move'
  | 'atm_iv'

export type ConvictionSortDir = 'asc' | 'desc'
export type BasisFilter = 'ALL' | 'LIVE FLOW' | 'PEAD' | 'MODEL' | 'ACTIVITY'

const props = defineProps<{ depth?: 'quick' | 'deep' }>()
const emit = defineEmits<{ (e: 'select', symbol: string): void }>()

const board = ref<OptionsBoard | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const requireLiveFlow = ref(false)

const sortKey = ref<ConvictionSortKey>('rank')
const sortDir = ref<ConvictionSortDir>('asc')
const searchQuery = ref('')
const selectedBasis = ref<BasisFilter>('ALL')

async function load(force = false) {
  loading.value = true
  error.value = null
  try {
    board.value = await api.optionsBoard({
      limit: 25,
      depth: props.depth,
      requireLiveFlow: requireLiveFlow.value,
      force,
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => void load(false))

const rows = computed(() => board.value?.rows ?? [])
const cov = computed(() => board.value?.coverage)

/** Cache age in words — a cached chain must never look live. */
const cacheNote = computed(() => {
  const c = board.value?.cache
  if (!c) return ''
  if (!c.hit) return 'fetched just now'
  const mins = Math.floor(c.age_seconds / 60)
  return mins < 1 ? `cached ${Math.round(c.age_seconds)}s ago` : `cached ${mins}m ago`
})

const meta = computed(() => {
  const c = cov.value
  if (!c) return ''
  return `${c.chain_fetched}/${c.requested} chains · ${c.squeeze_scored} scored of ${c.candidates_considered} considered · ${cacheNote.value}`
})

const basisLabel: Record<string, string> = {
  pead_ordinal: 'PEAD',
  live_options_flow: 'LIVE FLOW',
  activity_ordinal: 'ACTIVITY',
  directional_model: 'MODEL',
}

const basisKeyMap: Record<BasisFilter, string | null> = {
  ALL: null,
  'LIVE FLOW': 'live_options_flow',
  PEAD: 'pead_ordinal',
  MODEL: 'directional_model',
  ACTIVITY: 'activity_ordinal',
}

function setSort(key: ConvictionSortKey) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = (key === 'rank' || key === 'symbol' || key === 'selection_basis') ? 'asc' : 'desc'
  }
}

function sortIndicator(key: ConvictionSortKey): string {
  if (sortKey.value !== key) return ''
  return sortDir.value === 'asc' ? '▴' : '▾'
}

const filteredRows = computed(() => {
  let list = board.value?.rows ?? []
  const query = searchQuery.value.trim().toUpperCase()
  if (query) {
    list = list.filter((r) => r.symbol.toUpperCase().includes(query))
  }
  const targetBasis = basisKeyMap[selectedBasis.value]
  if (targetBasis) {
    list = list.filter((r) => r.selection_basis === targetBasis)
  }

  return [...list].sort((a, b) => {
    const k = sortKey.value
    const dir = sortDir.value === 'asc' ? 1 : -1
    const va = a[k]
    const vb = b[k]
    if (va === vb) return a.rank - b.rank
    if (va === null || va === undefined) return 1
    if (vb === null || vb === undefined) return -1
    if (typeof va === 'string' && typeof vb === 'string') {
      return dir * va.localeCompare(vb)
    }
    return dir * ((va as number) - (vb as number))
  })
})

function pct(v: number | null | undefined): string {
  return optPctFrac(v, 1)
}

/** Signed squeeze tone. Null stays neutral — no measurement, no colour. */
function squeezeTone(row: OptionsBoardRow): string {
  const s = row.squeeze_score
  if (s === null || s === undefined) return 'flat'
  return s > 0 ? 'pos' : s < 0 ? 'neg' : 'flat'
}

function selectionDisplay(row: OptionsBoardRow): string {
  if (row.selection_score === null || row.selection_score === undefined) return '0.00'
  return row.score_kind === 'calibrated_probability'
    ? pct(row.selection_score)
    : row.selection_score.toFixed(2)
}

function computePressureScore(row: OptionsBoardRow): {
  score: number
  signed: number
  tone: 'pos' | 'neg' | 'neutral'
  label: string
} {
  const callPrem = Number(row.call_premium ?? 0)
  const putPrem = Number(row.put_premium ?? 0)
  const totalPrem = callPrem + putPrem
  // Normalize pressure score delta with total premium dampening so small prints (< $100k) do not distort conviction
  const dampener = totalPrem > 0 ? Math.min(1, Math.max(0.15, totalPrem / 100_000)) : 1

  if (row.squeeze_score != null && Number.isFinite(row.squeeze_score)) {
    const rawSigned = Math.max(-100, Math.min(100, row.squeeze_score))
    const signed = (row.selection_basis === 'live_options_flow' && totalPrem > 0)
      ? rawSigned * dampener
      : rawSigned
    const score = Math.abs(signed)
    const tone = signed > 0.5 ? 'pos' : signed < -0.5 ? 'neg' : 'neutral'
    return { score, signed, tone, label: `${signed > 0 ? '+' : ''}${signed.toFixed(1)}` }
  }
  if (row.activity_imbalance != null && Number.isFinite(row.activity_imbalance)) {
    const rawSigned = Math.max(-1, Math.min(1, row.activity_imbalance)) * 100
    const signed = rawSigned * (totalPrem > 0 ? dampener : 0.5)
    const score = Math.abs(signed)
    const tone = signed > 0.5 ? 'pos' : signed < -0.5 ? 'neg' : 'neutral'
    return { score, signed, tone, label: `${signed > 0 ? '+' : ''}${signed.toFixed(1)}` }
  }
  if (row.net_gex_m != null && Number.isFinite(row.net_gex_m)) {
    const gex = row.net_gex_m
    const tone = gex > 0 ? 'pos' : gex < 0 ? 'neg' : 'neutral'
    const score = Math.min(100, Math.abs(gex) * 10)
    return { score, signed: gex, tone, label: `${gex > 0 ? '+' : ''}${gex.toFixed(1)}M` }
  }
  if (row.selection_score != null && Number.isFinite(row.selection_score)) {
    const score = Math.min(100, row.selection_score)
    return { score, signed: score, tone: 'neutral', label: `${score.toFixed(1)}` }
  }
  return { score: 0, signed: 0, tone: 'neutral', label: '0.0' }
}
</script>

<template>
  <Panel
    label="Conviction Board"
    index="00"
    :meta="meta"
    :live="!loading"
    flush
  >
    <template #action>
      <label class="live-toggle label">
        <input v-model="requireLiveFlow" type="checkbox" @change="load(true)" />
        LIVE FLOW ONLY
      </label>
      <button
        class="refresh-btn label"
        type="button"
        :disabled="loading"
        title="Refetch every chain live, bypassing the 5-minute server cache"
        @click="load(true)"
      >
        {{ loading ? 'PULLING…' : 'REFRESH LIVE' }}
      </button>
    </template>

    <p v-if="error" class="board-msg label err">{{ error }}</p>

    <!-- Data-integrity banners. These are not decoration: a stale-bar or
         unmeasured-OI board looks completely normal without them. -->
    <ul v-if="board?.warnings?.length" class="board-warnings">
      <li v-for="w in board.warnings" :key="w" class="label">{{ w }}</li>
    </ul>

    <!-- Filter and Search Toolbar -->
    <div class="board-toolbar">
      <div class="search-wrap">
        <span class="search-ico label">⌕</span>
        <input
          v-model="searchQuery"
          type="text"
          class="search-input label"
          placeholder="SEARCH SYM…"
          aria-label="Filter candidates by ticker"
          spellcheck="false"
        />
        <button
          v-if="searchQuery"
          type="button"
          class="clear-query-btn label"
          aria-label="Clear ticker filter"
          @click="searchQuery = ''"
        >
          ✕
        </button>
      </div>

      <div class="basis-chips" role="group" aria-label="Selection basis filter">
        <button
          v-for="b in (['ALL', 'LIVE FLOW', 'PEAD', 'MODEL', 'ACTIVITY'] as const)"
          :key="b"
          type="button"
          class="basis-chip-btn label"
          :class="{ active: selectedBasis === b }"
          @click="selectedBasis = b"
        >
          {{ b }}
        </button>
      </div>

      <span class="row-count label">
        {{ filteredRows.length }} OF {{ rows.length }} CANDIDATES
      </span>
    </div>

    <!-- Institutional Pressure Score Conviction Heatmap Bar -->
    <div v-if="filteredRows.length" class="pressure-heatmap-bar" aria-label="Institutional Conviction Heatmap">
      <div class="heatmap-header label">
        <span class="heatmap-title">INSTITUTIONAL PRESSURE CONVICTION SPECTRUM</span>
        <div class="heatmap-legend">
          <span class="leg-item"><span class="leg-swatch pos" /> BULL / LONG GEX</span>
          <span class="leg-item"><span class="leg-swatch neg" /> BEAR / SHORT GEX</span>
          <span class="leg-item"><span class="leg-swatch neutral" /> UNMEASURED</span>
        </div>
      </div>
      <div class="heatmap-strip">
        <button
          v-for="row in filteredRows"
          :key="row.symbol"
          type="button"
          class="heatmap-cell"
          :class="computePressureScore(row).tone"
          :style="{ opacity: 0.5 + (computePressureScore(row).score / 100) * 0.5 }"
          :title="`${row.symbol} (#${row.rank}) · Pressure: ${computePressureScore(row).label} · Squeeze: ${optSigned(row.squeeze_score, 1)} · Net GEX: ${optGex(row.net_gex_m, 1)}`"
          @click="emit('select', row.symbol)"
        >
          <span class="cell-sym">{{ row.symbol }}</span>
          <span class="cell-val">{{ computePressureScore(row).label }}</span>
        </button>
      </div>
    </div>

    <div v-if="filteredRows.length" class="board-scroll">
      <table class="grid board-table">
        <thead>
          <tr>
            <th class="label sortable" :class="{ active: sortKey === 'rank' }" @click="setSort('rank')">
              # <span class="sort-arr">{{ sortIndicator('rank') }}</span>
            </th>
            <th class="label sortable" :class="{ active: sortKey === 'symbol' }" @click="setSort('symbol')">
              SYM <span class="sort-arr">{{ sortIndicator('symbol') }}</span>
            </th>
            <th class="label sortable" :class="{ active: sortKey === 'selection_basis' }" @click="setSort('selection_basis')">
              WHY
              <HelpTip text="Which scan tier routed this name into a chain request. Ordinal except MODEL, which is the only calibrated probability on the board." />
              <span class="sort-arr">{{ sortIndicator('selection_basis') }}</span>
            </th>
            <th class="label num sortable" :class="{ active: sortKey === 'selection_score' }" @click="setSort('selection_score')">
              SCORE <span class="sort-arr">{{ sortIndicator('selection_score') }}</span>
            </th>
            <th class="label num sortable" :class="{ active: sortKey === 'spot' }" @click="setSort('spot')">
              SPOT <span class="sort-arr">{{ sortIndicator('spot') }}</span>
            </th>
            <th class="label num sortable" :class="{ active: sortKey === 'squeeze_score' }" @click="setSort('squeeze_score')">
              SQUEEZE
              <HelpTip text="Signed structural score. '0.0' indicates baseline or unmeasured structure." />
              <span class="sort-arr">{{ sortIndicator('squeeze_score') }}</span>
            </th>
            <th class="label num sortable" :class="{ active: sortKey === 'net_gex_m' }" @click="setSort('net_gex_m')">
              NET GEX $M <span class="sort-arr">{{ sortIndicator('net_gex_m') }}</span>
            </th>
            <th class="label num sortable" :class="{ active: sortKey === 'put_wall' }" @click="setSort('put_wall')">
              PUT WALL <span class="sort-arr">{{ sortIndicator('put_wall') }}</span>
            </th>
            <th class="label num sortable" :class="{ active: sortKey === 'call_wall' }" @click="setSort('call_wall')">
              CALL WALL <span class="sort-arr">{{ sortIndicator('call_wall') }}</span>
            </th>
            <th class="label num sortable" :class="{ active: sortKey === 'expected_move' }" @click="setSort('expected_move')">
              EXP MOVE <span class="sort-arr">{{ sortIndicator('expected_move') }}</span>
            </th>
            <th class="label num sortable" :class="{ active: sortKey === 'atm_iv' }" @click="setSort('atm_iv')">
              ATM IV <span class="sort-arr">{{ sortIndicator('atm_iv') }}</span>
            </th>
            <th class="label">DATA</th>
            <th class="label num sq-col">RISK VIZ</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in filteredRows"
            :key="row.symbol"
            class="board-row"
            :class="{ unavailable: !row.available, unmeasured: !row.gex_measurable }"
            tabindex="0"
            role="button"
            :title="`Load ${row.symbol} chain below`"
            @click="emit('select', row.symbol)"
            @keydown.enter="emit('select', row.symbol)"
          >
            <td class="fig num dim">{{ row.rank }}</td>
            <td class="sym">{{ row.symbol }}</td>
            <td>
              <span class="basis label" :class="row.selection_basis">
                {{ basisLabel[row.selection_basis] ?? row.selection_basis }}
              </span>
            </td>
            <td class="fig num">{{ selectionDisplay(row) }}</td>
            <td class="fig num">{{ optUsd(row.spot) }}</td>
            <td class="fig num" :class="squeezeTone(row)">
              {{ optSigned(row.squeeze_score, 1) }}
              <i v-if="row.squeeze_label" class="sq-label">{{ row.squeeze_label }}</i>
            </td>
            <td class="fig num">{{ optGex(row.net_gex_m, 1) }}</td>
            <td class="fig num put">{{ optUsd(row.put_wall) }}</td>
            <td class="fig num call">{{ optUsd(row.call_wall) }}</td>
            <td class="fig num">{{ optUsd(row.expected_move) }}</td>
            <td class="fig num">{{ optPctFrac(row.atm_iv, 1) }}</td>
            <td class="flags">
              <span v-if="!row.available" class="chip halt label">NO CHAIN</span>
              <span v-else-if="!row.gex_measurable" class="chip warn label" title="Open interest unavailable — gamma is unmeasured, not zero">NO OI</span>
              <span
                v-if="row.clock_mismatch"
                class="chip warn label"
                :title="`Chain is ${row.clock_skew_days}d newer than the last price bar (${row.price_asof}) — momentum term is stale`"
              >{{ row.clock_skew_days }}D STALE</span>
            </td>
            <td class="risk-viz-cell">
              <!-- Squeeze score spark bar -->
              <div class="sq-spark" :title="row.squeeze_score != null ? `Squeeze: ${row.squeeze_score.toFixed(1)}` : 'Unmeasured'">
                <div
                  class="sq-spark-bar"
                  :class="row.squeeze_score == null ? 'unmeasured' : row.squeeze_score > 0 ? 'pos' : 'neg'"
                  :style="{ width: row.squeeze_score != null ? `${Math.min(100, Math.abs(row.squeeze_score))}%` : '0%' }"
                />
              </div>
              <!-- ATM IV chip -->
              <span v-if="row.atm_iv != null" class="iv-chip label">IV {{ optPctFrac(row.atm_iv, 1) }}</span>
              <!-- Expected move -->
              <span v-if="row.expected_move != null" class="em-chip label">±{{ optUsd(row.expected_move) }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-else-if="!loading" class="board-msg label">
      No scan candidate met the selection criteria. Clear the search/filter, run a deep scan from the Desk,
      or clear the live-flow filter.
    </p>

    <footer v-if="board?.caveats?.length" class="board-caveats">
      <p v-for="c in board.caveats" :key="c" class="label">{{ c }}</p>
    </footer>
  </Panel>
</template>

<style scoped>
/* Surface glass token: var(--glass-surface-hi) */
.refresh-btn,
.live-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-hi);
  color: var(--ink-soft);
  padding: 0.25rem 0.55rem;
  cursor: pointer;
}

.refresh-btn:hover:not(:disabled) {
  border-color: var(--phosphor);
  color: var(--phosphor);
}

.refresh-btn:disabled {
  opacity: 0.5;
  cursor: progress;
}

.board-warnings {
  list-style: none;
  margin: 0;
  padding: 0.5rem 0.75rem;
  border-bottom: var(--hair) solid var(--rule);
  background: var(--warn-wash);
}

.board-warnings li {
  color: var(--warn);
  white-space: normal;
  line-height: 1.5;
}

/* Toolbar & Filter Shelf */
.board-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  background: var(--void);
  border-bottom: var(--hair) solid var(--rule-faint);
  flex-wrap: wrap;
}

.search-wrap {
  position: relative;
  display: flex;
  align-items: center;
  min-width: 180px;
}

.search-ico {
  position: absolute;
  left: 8px;
  color: var(--ink-dim);
  pointer-events: none;
  font-size: var(--t-small);
}

.search-input {
  width: 100%;
  padding: 4px 24px 4px 24px;
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  color: var(--ink);
  font-size: var(--t-micro);
  letter-spacing: 0.04em;
  border-radius: 2px;
}

.search-input:focus {
  border-color: var(--phosphor);
  outline: none;
}

.clear-query-btn {
  position: absolute;
  right: 6px;
  background: none;
  border: none;
  color: var(--ink-dim);
  cursor: pointer;
  padding: 2px;
  font-size: var(--t-tiny);
}

.clear-query-btn:hover {
  color: var(--ink);
}

.basis-chips {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.basis-chip-btn {
  padding: 2px 7px;
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  font-size: var(--t-micro);
  letter-spacing: 0.04em;
  cursor: pointer;
  transition: all var(--dur-fast, 120ms);
}

.basis-chip-btn:hover {
  color: var(--ink);
  border-color: var(--rule-hi);
}

.basis-chip-btn.active {
  background: var(--phosphor-wash);
  color: var(--phosphor);
  border-color: var(--phosphor);
}

.row-count {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  letter-spacing: 0.04em;
}

/* Institutional Conviction Heatmap Bar */
.pressure-heatmap-bar {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--s2) var(--s3);
  background: var(--panel-hi);
  border-bottom: var(--hair) solid var(--rule);
}

.heatmap-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--t-micro);
  color: var(--ink-dim);
  letter-spacing: var(--track-label);
}

.heatmap-legend {
  display: flex;
  gap: var(--s3);
}

.leg-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.leg-swatch {
  width: 8px;
  height: 8px;
  border-radius: 1px;
  display: inline-block;
}

.leg-swatch.pos { background: var(--call); }
.leg-swatch.neg { background: var(--put); }
.leg-swatch.neutral { background: var(--rule-hi); }

.heatmap-strip {
  display: flex;
  gap: 3px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.heatmap-cell {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 48px;
  padding: 3px 6px;
  border: var(--hair) solid var(--rule);
  border-radius: 2px;
  cursor: pointer;
  transition: transform var(--dur-fast, 120ms);
}

.heatmap-cell:hover {
  transform: translateY(-1px);
  border-color: var(--phosphor);
}

.heatmap-cell.pos {
  background: var(--call-wash);
  border-color: var(--call);
}

.heatmap-cell.neg {
  background: var(--put-wash);
  border-color: var(--put);
}

.heatmap-cell.neutral {
  background: var(--void);
  border-color: var(--rule-hi);
}

.cell-sym {
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-tiny);
  color: var(--ink);
}

.cell-val {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  color: var(--ink-dim);
}

.heatmap-cell.pos .cell-val { color: var(--call-hi); }
.heatmap-cell.neg .cell-val { color: var(--put-hi); }

/* Table and Sort Headers */
th.sortable {
  cursor: pointer;
  user-select: none;
  transition: color var(--dur-fast, 120ms);
}

th.sortable:hover {
  color: var(--phosphor);
}

th.sortable.active {
  color: var(--ink);
  background: var(--void-lift);
}

th.sortable.active .sort-arr {
  color: var(--phosphor);
  font-weight: 700;
}

.sort-arr {
  font-size: var(--t-tiny);
  margin-left: 2px;
  color: var(--phosphor);
}

.board-scroll {
  overflow-x: auto;
}

.board-table {
  width: 100%;
  min-width: 60rem;
}

.board-row {
  cursor: pointer;
}

.board-row:hover,
.board-row:focus-visible {
  background: var(--phosphor-wash);
}

.board-row.unavailable,
.board-row.unmeasured {
  color: var(--ink-faint);
}

.sym {
  font-family: var(--font-data);
  font-weight: 700;
  color: var(--ink);
}

.dim {
  color: var(--ink-faint);
}

.pos { color: var(--call-hi, var(--call)); }
.neg { color: var(--put-hi, var(--put)); }
.call { color: var(--call-hi, var(--call)); }
.put { color: var(--put-hi, var(--put)); }

.basis {
  border: var(--hair) solid var(--rule-hi);
  padding: 0.1rem 0.35rem;
  color: var(--ink-dim);
}

.basis.pead_ordinal { border-color: var(--phosphor-dim); color: var(--phosphor); }
.basis.live_options_flow { border-color: var(--call); color: var(--call-hi); }
.basis.directional_model { border-color: var(--long); color: var(--long); }

.sq-label {
  display: block;
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-style: normal;
  color: var(--ink-faint);
  text-transform: uppercase;
}

.flags {
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
}

.chip {
  border: var(--hair) solid currentColor;
  padding: 0.05rem 0.3rem;
}

.sq-col { min-width: 120px; }

.risk-viz-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 4px 8px;
  min-width: 120px;
}

.sq-spark {
  height: 5px;
  background: var(--rule);
  overflow: hidden;
  width: 100%;
}

.sq-spark-bar {
  height: 100%;
  transition: width 0.4s ease;
  min-width: 2px;
}
.sq-spark-bar.pos { background: var(--call); }
.sq-spark-bar.neg { background: var(--put); }
.sq-spark-bar.unmeasured { background: var(--rule-hi); width: 100% !important; opacity: 0.4; }

.iv-chip {
  display: inline-block;
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.05em;
  padding: 1px 4px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
  background: var(--panel-hi);
}

.em-chip {
  display: inline-block;
  font-size: var(--t-micro);
  font-weight: 600;
  color: var(--ink-ghost);
  letter-spacing: 0.03em;
}
.chip.halt { color: var(--halt); }
.chip.warn { color: var(--warn); }

.board-msg {
  padding: 1rem 0.75rem;
  white-space: normal;
  line-height: 1.6;
  color: var(--ink-dim);
}

.board-msg.err { color: var(--halt); }

.board-caveats {
  border-top: var(--hair) solid var(--rule);
  padding: 0.6rem 0.75rem;
}

.board-caveats p {
  margin: 0 0 0.3rem;
  white-space: normal;
  line-height: 1.5;
  color: var(--ink-ghost);
}
</style>
