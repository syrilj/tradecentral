<script setup lang="ts">
import { computed, inject } from 'vue'
import { api, type Gate, type StatusPayload } from '@/api'
import { useResource } from '@/composables/useResource'
import type { Resource } from '@/composables/useResource'
import { num, shortDate, tone, DASH } from '@/format'
import Panel from '@/components/Panel.vue'
import VerdictChip from '@/components/VerdictChip.vue'

/**
 * Pre-registered gates and strategy leaderboard.
 */
const status = inject<Resource<StatusPayload>>('status')
const gates = useResource<{ gates: Gate[] }>(() => api.gates(), { intervalMs: 300_000 })

const rows = computed(() => gates.data.value?.gates ?? [])
const board = computed(() => (status?.data?.value?.leaderboard ?? []) as any[])

const tally = computed(() => {
  const t = { go: 0, noGo: 0, unknown: 0 }
  for (const g of rows.value) {
    const v = (g.verdict ?? '').toUpperCase()
    if (v === 'GO') t.go++
    else if (v.startsWith('NO') || v === 'FAIL') t.noGo++
    else t.unknown++
  }
  return t
})

function checkRows(g: Gate): { k: string; ok: boolean }[] {
  return Object.entries(g.checks ?? {}).map(([k, ok]) => ({ k, ok: Boolean(ok) }))
}

function metricRows(g: Gate): { k: string; v: number | string }[] {
  return Object.entries(g.metrics ?? {})
    .filter(
      (e): e is [string, number | string] => typeof e[1] === 'number' || typeof e[1] === 'string',
    )
    .slice(0, 8)
    .map(([k, v]) => ({ k, v }))
}

function prettyKey(k: string): string {
  return k
    .replace(/_/g, ' ')
    .replace(/\bpct\b/, '%')
    .replace(/\bic\b/i, 'IC')
}

/** Counts (n_symbols, n_rows) are integers — 4dp on them is noise, not precision. */
function metricValue(v: number | string): string {
  if (typeof v !== 'number') return v ?? DASH
  return Number.isInteger(v) ? num(v, 0) : num(v, 4)
}
</script>

<template>
  <div class="gates-page">
    <!-- ── 01 Gate Summary Header ──────────────────────────────────────── -->
    <Panel
      label="Pre-registered Gate Evaluation"
      index="04"
      :meta="`${rows.length} gates evaluated`"
      class="w-full"
    >
      <p v-if="gates.error.value" class="err">{{ gates.error.value }}</p>
      <template v-else>
        <div class="tally">
          <div class="t-cell go">
            <span class="t-n fig">{{ tally.go }}</span>
            <span class="label t-lbl">GO (CLEARED)</span>
          </div>
          <div class="t-cell no">
            <span class="t-n fig">{{ tally.noGo }}</span>
            <span class="label t-lbl">HELD (RISK LIMIT)</span>
          </div>
          <div class="t-cell unk">
            <span class="t-n fig">{{ tally.unknown }}</span>
            <span class="label t-lbl">UNEVALUATED</span>
          </div>
          <p class="t-note">
            Every gate specification was pre-registered before model execution. A status here
            reflects immutable backtest artifacts recorded on disk — never re-computed or
            retroactively altered.
          </p>
        </div>
      </template>
    </Panel>

    <!-- ── 02 Gate Strategy Leaderboard ───────────────────────────────── -->
    <Panel
      label="Pre-Registered Strategy Leaderboard"
      index="—"
      :meta="`${board.length} strategies registered`"
      class="w-full"
      flush
    >
      <div class="table-container">
        <table v-if="board.length" class="grid">
          <thead>
            <tr>
              <th class="label">Strategy Name</th>
              <th class="label">Features Spec</th>
              <th class="label num">Rank IC</th>
              <th class="label num">Net Return</th>
              <th class="label num">Sharpe Ratio</th>
              <th class="label">Validation Status</th>
              <th class="label">Gate Verdict</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(m, i) in board" :key="i">
              <td class="strat">
                <span class="s-name">{{ m.strategy }}</span>
                <span class="s-file label">{{ m.gate_file }}</span>
              </td>
              <td class="label dim feat" :title="m.features">{{ m.features }}</td>
              <td class="fig num" :class="m.rank_ic?.startsWith('-') ? 'neg' : 'pos'">
                {{ m.rank_ic }}
              </td>
              <td class="fig num" :class="m.net_return?.startsWith('-') ? 'neg' : 'pos'">
                {{ m.net_return }}
              </td>
              <td class="fig num bold">{{ m.sharpe }}</td>
              <td class="label dim">{{ m.validation_status }}</td>
              <td><VerdictChip :verdict="m.verdict" size="sm" /></td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">Strategy leaderboard artifact unavailable.</p>
      </div>
      <p class="note tiny pad-x">
        Net return and Sharpe ratios reflect recorded backtest artifacts. Strategies marked HELD
        fail on turnover or max drawdown limits.
      </p>
    </Panel>

    <!-- ── 03 Detailed Gate Artifact Cards ─────────────────────────────── -->
    <div class="gate-cards-grid">
      <Panel
        v-for="(g, i) in rows"
        :key="g.id"
        :label="g.name || g.id"
        :index="String(i + 1).padStart(2, '0')"
        :meta="g.updated ? shortDate(g.updated) : ''"
        :delay="60 + i * 45"
      >
        <template #action>
          <VerdictChip :verdict="g.verdict" size="sm" />
        </template>

        <dl class="metrics">
          <template v-for="m in metricRows(g)" :key="m.k">
            <dt class="label">{{ prettyKey(m.k) }}</dt>
            <dd class="fig" :class="typeof m.v === 'number' ? tone(m.v) : ''">
              {{ metricValue(m.v) }}
            </dd>
          </template>
        </dl>

        <ul v-if="checkRows(g).length" class="checks">
          <li v-for="c in checkRows(g)" :key="c.k" class="check" :class="{ ok: c.ok }">
            <span class="c-mark" aria-hidden="true">{{ c.ok ? '✓' : '✗' }}</span>
            <span class="c-k label">{{ prettyKey(c.k) }}</span>
          </li>
        </ul>

        <p class="src label">{{ g.source_file }}</p>
      </Panel>
    </div>
  </div>
</template>

<style scoped>
.gates-page {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}
.w-full {
  width: 100%;
}

.tally {
  display: flex;
  align-items: center;
  gap: var(--s6);
  flex-wrap: wrap;
}
.t-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.t-lbl {
  font-size: 10px;
  font-weight: 700;
}
.t-n {
  font-size: 2.2rem;
  line-height: 1;
  letter-spacing: -0.04em;
  font-weight: 800;
}
.go .t-n {
  color: var(--go);
}
.no .t-n {
  color: var(--no-go);
}
.unk .t-n {
  color: var(--unknown);
}
.t-note {
  flex: 1 1 340px;
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.55;
  border-left: var(--hair) solid var(--rule);
  padding-left: var(--s5);
}

.gate-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--s4);
  align-items: start;
}

/* ---- Scrollable Leaderboard Table ---------------------------------------- */
.table-container {
  max-height: 480px;
  overflow-y: auto;
  scrollbar-width: thin;
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

.num {
  text-align: right;
}
.bold {
  font-weight: 700;
}
.dim {
  color: var(--ink-dim);
}
/* Feature lists are additive expressions — wrap so the whole set stays readable. */
.feat {
  max-width: 30ch;
  white-space: normal;
  line-height: 1.4;
}

.strat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.s-name {
  color: var(--ink);
  font-weight: 600;
}
.s-file {
  color: var(--ink-dim);
  font-size: 11px;
}

.metrics {
  display: grid;
  /* 1fr auto let a wide value ("96,986.0000") starve the term column to 0px,
     leaving a column of unlabelled numbers. Size the term to its content. */
  grid-template-columns: auto minmax(0, 1fr);
  gap: 3px var(--s3);
  align-items: baseline;
  margin-top: var(--s2);
  padding-bottom: var(--s3);
}
.metrics dt {
  color: var(--ink-dim);
  font-weight: 600;
}
.metrics dd {
  font-size: var(--t-small);
  color: var(--ink);
  text-align: right;
  font-weight: 600;
}

.checks {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-top: var(--hair) solid var(--rule-faint);
  padding-top: var(--s2);
}
.check {
  display: flex;
  align-items: center;
  gap: var(--s2);
  color: var(--no-go);
}
.check.ok {
  color: var(--go);
}
.c-mark {
  font-weight: 700;
  font-size: 12px;
}
.c-k {
  color: var(--ink-dim);
  font-size: 11px;
}

.src {
  margin-top: var(--s3);
  color: var(--ink-dim);
  font-size: 10px;
}
.err {
  color: var(--short);
  font-size: var(--t-small);
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
  font-size: 11px;
}
</style>
