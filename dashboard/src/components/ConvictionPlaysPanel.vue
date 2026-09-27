<script setup lang="ts">
/**
 * Today's highest-conviction flow plays.
 *
 * Sourced from the same board+flow ranking engine that already powers the
 * per-symbol setup drawer (`/api/options/suggest`), narrowed to names whose
 * signal actually includes measured options flow (`flow_only` or `both`) —
 * a pure squeeze/structure read with no flow evidence doesn't belong on a
 * "real-time flow" board. Rows arrive pre-ranked by the backend's
 * `review_score` (entry-gate + freshness + contract-stability quality), so
 * this panel filters and displays; it does not invent its own score.
 */
import { computed } from 'vue'
import { api, type LiveOpportunityRow } from '@/api'
import { useResource } from '@/composables/useResource'
import { DASH, num, usd, age } from '@/format'
import { suggestedRightLabel, suggestedRightTokenClass } from '@/suggestDisplay'
import Panel from '@/components/Panel.vue'
import LoadingState from '@/components/LoadingState.vue'

const LIMIT = 8
const POLL_MS = 20_000

const emit = defineEmits<{ select: [symbol: string] }>()

const feed = useResource(() => api.flowSuggestions({ limit: 30 }), { intervalMs: POLL_MS })

const flowConfirmedRows = computed<LiveOpportunityRow[]>(() => {
  const rows = feed.data.value?.rows ?? []
  return rows.filter(
    (row) =>
      row.suggestion != null && (row.signal_basis === 'flow_only' || row.signal_basis === 'both'),
  )
})

const topRows = computed(() => flowConfirmedRows.value.slice(0, LIMIT))

const available = computed(() => feed.data.value?.available !== false)
const emptyReason = computed(
  () => feed.data.value?.reason || 'No name has cleared the flow-confirmed bar yet today.',
)

function reviewLabelClass(label: string | null | undefined): string {
  const value = String(label ?? '').toUpperCase()
  if (value === 'READY') return 'rl-ready'
  if (value === 'STRONG PAPER') return 'rl-strong'
  if (value === 'PAPER' || value === 'PAPER ACTION') return 'rl-paper'
  if (value === 'NEW / CHURNING') return 'rl-new'
  return 'rl-watch'
}

function topReason(row: LiveOpportunityRow): string {
  const reasons = row.suggestion?.review_reasons
  if (reasons && reasons.length) return reasons[0]
  return row.suggestion?.reason || DASH
}

/**
 * `review_score` (0-100, entry-gate + freshness + contract-stability quality)
 * is the field the backend actually sorts rows by, and the one that varies
 * meaningfully across names. `flow_unusual_z`/`flow_unusual_score` exist on
 * the row too, but in a thin-feed session they collapse to one repeated
 * value across nearly every symbol — showing that as a per-row "strength"
 * figure would draw false precision from a currently degenerate signal, so
 * this panel doesn't surface it.
 */
function reviewScoreLabel(row: LiveOpportunityRow): string {
  const score = row.suggestion?.review_score
  return score == null ? DASH : num(score, 0)
}

function gateLabel(row: LiveOpportunityRow): string {
  if (row.gate_pass) return 'LIVE READY'
  return row.gate_reasons?.[0] || 'GATE UNMET'
}

const asofCopy = computed(() =>
  feed.data.value?.asof_utc ? `AS OF ${age(feed.data.value.asof_utc)} AGO` : DASH,
)
</script>

<template>
  <Panel
    label="Today's highest-conviction flow plays"
    :meta="`${topRows.length}/${flowConfirmedRows.length} shown · ${asofCopy}`"
    live
  >
    <LoadingState
      v-if="feed.loading.value && !feed.data.value"
      label="Ranking today's flow-confirmed names…"
    />
    <p v-else-if="!available" class="cp-empty label">
      {{ feed.data.value?.reason || 'Conviction ranking unavailable.' }}
    </p>
    <p v-else-if="!topRows.length" class="cp-empty label">
      {{ emptyReason }}
    </p>
    <div v-if="topRows.length" class="cp-head label" aria-hidden="true">
      <span class="cp-head-cell cp-cell-rank">#</span>
      <span class="cp-head-cell cp-cell-symbol">TICKER</span>
      <span class="cp-head-cell cp-cell-review">SETUP</span>
      <span class="cp-head-cell cp-cell-score">SCORE</span>
      <span class="cp-head-cell cp-cell-premium">PREMIUM</span>
      <span class="cp-head-cell cp-cell-reason">CONVICTION DRIVER / THESIS</span>
      <span class="cp-head-cell cp-cell-gate">EXECUTION GATE</span>
    </div>
    <ol v-else class="cp-list">
      <li v-for="(row, index) in topRows" :key="row.symbol">
        <button
          type="button"
          class="cp-row"
          :aria-label="`Open ${row.symbol} flow-confirmed setup`"
          @click="emit('select', row.symbol)"
        >
          <span class="cp-rank fig">{{ index + 1 }}</span>

          <span class="cp-symbol-col">
            <strong class="cp-symbol fig">{{ row.symbol }}</strong>
            <span class="cp-right label" :class="suggestedRightTokenClass(row.suggestion?.right)">{{
              suggestedRightLabel(row.suggestion?.right)
            }}</span>
          </span>

          <span class="cp-review label" :class="reviewLabelClass(row.suggestion?.review_label)">
            {{ row.suggestion?.review_label || 'WATCH' }}
          </span>

          <span class="cp-stat">
            <span class="cp-stat-label label">SCORE</span>
            <span class="cp-stat-val fig">{{ reviewScoreLabel(row) }}</span>
          </span>

          <span class="cp-stat">
            <span class="cp-stat-label label">PREMIUM</span>
            <span class="cp-stat-val fig">{{
              row.premium == null ? DASH : usd(row.premium, 0)
            }}</span>
          </span>

          <span class="cp-reason" :title="topReason(row)">{{ topReason(row) }}</span>

          <span
            class="cp-gate label"
            :class="{ pass: row.gate_pass, blocked: !row.gate_pass }"
            :title="gateLabel(row)"
          >
            <i class="cp-gate-lamp" aria-hidden="true" />
            <span class="cp-gate-text">{{ gateLabel(row) }}</span>
          </span>
        </button>
      </li>
    </ol>
    <p class="cp-caveat label">
      Ordinal ranking of board-observed flow evidence — decision support only, never an entry signal
      or order routing.
    </p>
  </Panel>
</template>

<style scoped>
.cp-empty {
  padding: var(--s4);
  color: var(--ink-dim);
}

.cp-head {
  display: grid;
  grid-template-columns: 24px 110px 105px 75px 105px 1fr 145px;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  background: var(--surface-base);
  border: var(--hair) solid var(--rule);
  border-bottom: none;
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--ink-dim);
  text-transform: uppercase;
}
.cp-cell-gate {
  text-align: right;
}

.cp-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--hair);
  background: var(--rule);
  border: var(--hair) solid var(--rule);
}

.cp-row {
  width: 100%;
  display: grid;
  grid-template-columns: 24px 110px 105px 75px 105px 1fr 145px;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s3);
  background: var(--panel);
  text-align: left;
  transition: background var(--dur-fast) var(--ease-out);
}
.cp-row:hover {
  background: var(--panel-hi);
}

.cp-rank {
  color: var(--ink-dim);
  font-size: var(--t-micro);
  font-weight: 600;
}

.cp-symbol-col {
  display: flex;
  align-items: center;
  gap: var(--s2);
  min-width: 0;
}
.cp-symbol {
  color: var(--ink);
  font-size: var(--t-small);
  font-weight: 750;
  letter-spacing: 0.03em;
}
.cp-right {
  font-size: var(--t-nano);
  font-weight: 700;
  padding: 2px 6px;
  border-radius: var(--r-xs);
  width: fit-content;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

/* Call / Put token styling */
.token-call {
  color: var(--call-hi);
  background: var(--call-wash);
  border: var(--hair) solid var(--call);
}
.token-put {
  color: var(--put-hi);
  background: var(--put-wash);
  border: var(--hair) solid var(--put);
}
.token-warn {
  color: var(--warn);
  background: var(--warn-wash);
  border: var(--hair) solid var(--warn);
}
.token-unsigned {
  color: var(--ink-dim);
  background: var(--surface-overlay);
  border: var(--hair) solid var(--rule-hi);
}

.cp-review {
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 2px 8px;
  border-radius: var(--r-capsule);
  text-align: center;
  white-space: nowrap;
}
.rl-ready {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
}
.rl-strong {
  color: var(--call-hi);
  background: var(--call-wash);
  border: var(--hair) solid var(--call);
}
.rl-paper {
  color: var(--warn);
  background: var(--warn-wash);
  border: var(--hair) solid var(--warn);
}
.rl-new,
.rl-watch {
  color: var(--ink-dim);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-hi);
}

.cp-stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.cp-stat-label {
  font-size: var(--t-nano);
  color: var(--ink-dim);
  font-weight: 700;
  letter-spacing: 0.05em;
}
.cp-stat-val {
  font-size: var(--t-small);
  color: var(--ink);
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.cp-reason {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-soft);
  font-size: var(--t-micro);
  line-height: 1.4;
}

.cp-gate {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  justify-content: flex-end;
  padding: 2px 8px;
  border-radius: var(--r-xs);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.04em;
  white-space: nowrap;
  max-width: 100%;
  border: var(--hair) solid var(--rule-hi);
  background: var(--surface-base);
  color: var(--ink-dim);
}
.cp-gate-text {
  overflow: hidden;
  text-overflow: ellipsis;
}
.cp-gate.pass {
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border-color: var(--phosphor-dim);
}
.cp-gate.blocked {
  color: var(--warn);
  background: var(--warn-wash);
  border-color: var(--warn);
}
.cp-gate-lamp {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}

.cp-caveat {
  margin-top: var(--s2);
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.5;
}

@media (max-width: 860px) {
  .cp-head {
    display: none;
  }
  .cp-row {
    grid-template-columns: 22px 1fr auto;
    grid-template-areas:
      'rank symbol review'
      '.    stats  stats'
      '.    reason reason'
      '.    gate   gate';
    row-gap: 6px;
  }
  .cp-rank {
    grid-area: rank;
  }
  .cp-symbol-col {
    grid-area: symbol;
  }
  .cp-review {
    grid-area: review;
  }
  .cp-stat:first-of-type {
    grid-area: stats;
  }
  .cp-stat + .cp-stat {
    display: none;
  }
  .cp-reason {
    grid-area: reason;
    white-space: normal;
  }
  .cp-gate {
    grid-area: gate;
    justify-content: flex-start;
  }
}
</style>
