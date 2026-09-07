<script setup lang="ts">
import { computed, ref } from 'vue'
import type { OptionsTapeRow } from '@/api'
import { num, compact, DASH } from '@/format'
import { printSide, printPremium, classifyFlowOrder } from '@/flowDisplay'
import { formatTapeTime } from '@/optionsTape'

/** The workspace is single-ticker, so the expiry only needs MM-DD to be read. */
const fmtExp = (exp: string) => (exp.length === 10 ? exp.slice(5) : exp)

export interface FlowTapePrint {
  time: string
  ticker: string
  exp: string
  type: 'CALL' | 'PUT'
  strike: number | null
  premium: number
  side: 'Bullish' | 'Bearish' | 'Neutral'
  isSweep?: boolean
  isWhale?: boolean
  classLabel: string
  classCls: string
}

const props = withDefaults(
  defineProps<{
    symbol?: string
    prints?: OptionsTapeRow[]
  }>(),
  {
    symbol: 'SPY',
    prints: () => [],
  },
)

const emit = defineEmits<{
  'view-all': []
}>()

const filterMode = ref<'All' | 'Sweeps' | 'Golden' | 'Blocks'>('All')
const isPaused = ref(false)
const frozenPrints = ref<OptionsTapeRow[] | null>(null)

function togglePause() {
  if (!isPaused.value) {
    frozenPrints.value = [...props.prints]
    isPaused.value = true
  } else {
    frozenPrints.value = null
    isPaused.value = false
  }
}

const sourcePrints = computed<OptionsTapeRow[]>(() =>
  isPaused.value && frozenPrints.value ? frozenPrints.value : props.prints,
)

const filteredPrints = computed<FlowTapePrint[]>(() => {
  const filtered = sourcePrints.value.filter((p: OptionsTapeRow) => {
    const isSweep = Boolean(p.is_sweep || p.trade_class === 'sweep')
    const calculatedPrem = printPremium(p) ?? 0
    if (filterMode.value === 'Sweeps') {
      return isSweep
    }
    if (filterMode.value === 'Golden') {
      const badge = classifyFlowOrder(p)
      return badge.type === 'golden_sweep'
    }
    if (filterMode.value === 'Blocks') {
      return calculatedPrem >= 750_000 || p.is_block === true || p.trade_class === 'block'
    }
    return true
  })

  return filtered.slice(0, 6).map((p: OptionsTapeRow) => {
    const rawTime = formatTapeTime(p.timestamp)
    const right = (p.right || 'call').toUpperCase() as 'CALL' | 'PUT'
    const side = printSide(p)
    const calculatedPremium = printPremium(p) ?? 0
    const badge = classifyFlowOrder(p)
    return {
      time: rawTime,
      ticker: props.symbol || 'SPY',
      exp: p.expiry || '',
      type: right,
      strike: p.strike,
      premium: calculatedPremium,
      side,
      isSweep: p.is_sweep || p.trade_class === 'sweep',
      isWhale: calculatedPremium >= 500_000,
      classLabel: badge.type === 'golden_sweep' ? 'GOLDEN' : badge.label,
      classCls: badge.className,
    }
  })
})
</script>

<template>
  <div class="real-time-flow-card">
    <div class="card-header">
      <div class="title-group">
        <span class="card-title font-mono font-bold">REAL-TIME FLOW</span>
      </div>
      <div class="controls-group">
        <!-- The "Filter" caption was adjacent but unassociated, so the control
             announced as an unnamed combobox. A real <label for> ties them. -->
        <div class="filter-select-wrap font-mono">
          <label for="tape-filter-mode" class="filter-label font-mono text-ink-dim">Filter</label>
          <select id="tape-filter-mode" v-model="filterMode" class="filter-select font-mono">
            <option value="All">All</option>
            <option value="Sweeps">Sweeps</option>
            <option value="Golden">Golden</option>
            <option value="Blocks">Blocks</option>
          </select>
        </div>
        <button
          type="button"
          class="pause-btn font-mono"
          :class="{ paused: isPaused }"
          @click="togglePause"
        >
          {{ isPaused ? 'Resume' : 'Pause' }}
        </button>
      </div>
    </div>

    <!-- Table Frame -->
    <div class="flow-table-frame">
      <table class="tape-table font-mono">
        <thead>
          <tr>
            <th class="time-col">TIME</th>
            <th class="exp-col">EXP</th>
            <th class="type-col">TYPE</th>
            <th class="strike-col num-col">STRIKE</th>
            <th class="class-col">CLASS</th>
            <th class="premium-col num-col">PREMIUM</th>
            <th class="side-col">SIDE</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="filteredPrints.length === 0">
            <td colspan="7" class="empty-tape-cell font-mono">NO PRINTS · TAPE IDLE</td>
          </tr>
          <tr v-for="(row, idx) in filteredPrints" :key="idx">
            <td class="time-col font-mono text-ink-dim">{{ row.time || DASH }}</td>
            <td class="exp-col font-mono text-ink-soft">{{ fmtExp(row.exp) }}</td>
            <td class="type-col">
              <span
                class="type-pill font-mono font-bold"
                :class="row.type === 'CALL' ? 'is-call' : 'is-put'"
              >
                {{ row.type }}
              </span>
            </td>
            <td class="strike-col font-mono">
              {{ row.strike != null ? `$${num(row.strike, 0)}` : DASH }}
            </td>
            <td class="class-col">
              <span class="tape-flow-badge label" :class="row.classCls">
                {{ row.classLabel }}
              </span>
            </td>
            <td
              class="premium-col font-mono font-bold"
              :class="{
                'text-call-hi': row.side === 'Bullish',
                'text-put-hi': row.side === 'Bearish',
                'text-ink-dim': row.side === 'Neutral',
              }"
            >
              {{ row.premium > 0 ? `$${compact(row.premium)}` : DASH }}
              <span v-if="row.isWhale" class="tape-whale-tag font-mono">WHALE</span>
            </td>
            <td class="side-col">
              <span
                class="side-pill font-mono font-semibold"
                :class="{
                  'is-bullish': row.side === 'Bullish',
                  'is-bearish': row.side === 'Bearish',
                  'is-neutral': row.side === 'Neutral',
                }"
              >
                {{ row.side }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Footer link -->
    <div class="card-footer">
      <button type="button" class="view-all-btn font-mono" @click="emit('view-all')">
        View All Flow
      </button>
    </div>
  </div>
</template>

<style scoped>
.real-time-flow-card {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: 0.875rem 1rem;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 0.5rem;
  box-sizing: border-box;
  overflow: hidden;
  min-width: 0;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.card-title {
  font-size: 0.8125rem;
  letter-spacing: 0.05em;
  color: var(--ink);
}

.controls-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.filter-select-wrap {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: var(--t-micro);
}

.filter-select {
  background: var(--panel-hi);
  border: 1px solid var(--rule-hi);
  color: var(--ink);
  font-size: var(--t-micro);
  padding: 0.125rem 0.375rem;
  border-radius: var(--r-xs);
  outline: none;
  cursor: pointer;
}

.pause-btn {
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  color: var(--ink-dim);
  font-size: var(--t-nano);
  padding: 0.125rem 0.5rem;
  border-radius: var(--r-xs);
  cursor: pointer;
}

.pause-btn:hover {
  color: var(--ink);
  border-color: var(--rule-hi);
}

.pause-btn.paused {
  background: var(--warn-wash);
  color: var(--warn);
  border-color: var(--warn);
}

.flow-table-frame {
  width: 100%;
  overflow-x: auto;
  min-height: 195px;
}

.tape-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  font-size: var(--t-micro);
  font-variant-numeric: tabular-nums;
  text-align: left;
}

.tape-table th.time-col {
  width: 15%;
}

.tape-table th.exp-col {
  width: 12%;
}

.tape-table th.type-col {
  width: 11%;
}

.tape-table th.strike-col {
  width: 13%;
}

.tape-table th.class-col {
  width: 17%;
}

.tape-table th.premium-col {
  width: 17%;
}

.tape-table th.side-col {
  width: 15%;
}

/* Numerics right-align on the decimal like every other column on the desk. */
.num-col {
  text-align: right;
}

.strike-col,
.premium-col {
  text-align: right;
}

.tape-table th {
  color: var(--ink-dim);
  font-weight: 600;
  font-size: var(--t-nano);
  letter-spacing: 0.02em;
  padding: 0.25rem 0.5rem;
  border-bottom: 1px solid var(--rule-faint);
  white-space: nowrap;
}

/* Right-aligned headers need extra leading room so adjacent labels never read
   as one run-on word (STRIKE vs PREMIUM). */
.tape-table th.num-col {
  text-align: right;
  letter-spacing: 0.02em;
  padding-right: 0.625rem;
}

.empty-tape-cell {
  padding: 1.5rem 0.5rem;
  text-align: center;
  color: var(--ink-dim);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  border-bottom: none;
}

.tape-table td {
  padding: 0.375rem 0.375rem;
  border-bottom: 1px solid var(--rule-faint);
  white-space: nowrap;
}

.type-pill {
  font-size: var(--t-nano);
  padding: 0.1rem 0.3rem;
  border-radius: 2px;
}

.type-pill.is-call {
  background: var(--call-wash);
  color: var(--call-hi);
}

.type-pill.is-put {
  background: var(--put-wash);
  color: var(--put-hi);
}

.side-pill {
  font-size: var(--t-nano);
  padding: 0.1rem 0.35rem;
  border-radius: 2px;
}

.side-pill.is-bullish {
  background: var(--call-wash);
  color: var(--call-hi);
  border: 1px solid var(--call-dim);
}

.side-pill.is-bearish {
  background: var(--put-wash);
  color: var(--put-hi);
  border: 1px solid var(--put-dim);
}

.side-pill.is-neutral {
  background: var(--panel-raise);
  color: var(--ink-dim);
  border: 1px solid var(--rule-hi);
}

.card-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 0.25rem;
  border-top: 1px solid var(--rule-faint);
}

.view-all-btn {
  background: transparent;
  border: none;
  color: var(--ink-dim);
  font-size: var(--t-micro);
  cursor: pointer;
  padding: 0.125rem 0.25rem;
  transition: color var(--dur-fast) ease;
}

.view-all-btn:hover {
  color: var(--phosphor);
}

.tape-flow-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.1rem 0.35rem;
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.04em;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule-hi);
  background: var(--panel-raise);
  color: var(--ink-dim);
}

.tape-flow-badge.badge-golden-sweep {
  color: var(--badge-golden);
  border-color: var(--badge-golden-border);
  background: var(--badge-golden-wash);
}

.tape-flow-badge.badge-sweep {
  color: var(--badge-sweep);
  border-color: color-mix(in srgb, var(--call) 45%, var(--rule));
  background: var(--badge-sweep-wash);
}

.tape-flow-badge.badge-block {
  color: var(--badge-block);
  border-color: color-mix(in srgb, var(--put) 45%, var(--rule));
  background: var(--badge-block-wash);
}

.tape-flow-badge.badge-split {
  color: var(--badge-split);
  border-color: color-mix(in srgb, var(--cat-4) 45%, var(--rule));
  background: var(--badge-split-wash);
}

.tape-flow-badge.badge-multileg {
  color: var(--badge-multileg);
  border-color: color-mix(in srgb, var(--cat-5) 45%, var(--rule));
  background: var(--badge-multileg-wash);
}

.tape-whale-tag {
  display: inline-block;
  margin-left: 0.25rem;
  font-size: var(--t-nano);
  font-weight: 700;
  padding: 0.05rem 0.25rem;
  border-radius: var(--r-xs);
  color: var(--warn);
  background: var(--warn-wash);
  border: var(--hair) solid color-mix(in srgb, var(--warn) 35%, var(--rule));
  vertical-align: middle;
}
</style>
