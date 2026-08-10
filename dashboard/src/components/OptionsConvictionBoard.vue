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
import Panel from '@/components/Panel.vue'
import HelpTip from '@/components/HelpTip.vue'

const props = defineProps<{ depth?: 'quick' | 'deep' }>()
const emit = defineEmits<{ (e: 'select', symbol: string): void }>()

const board = ref<OptionsBoard | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const requireLiveFlow = ref(false)

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

function num(v: number | null | undefined, dp = 2): string {
  return v === null || v === undefined || !Number.isFinite(v) ? '—' : v.toFixed(dp)
}

function pct(v: number | null | undefined): string {
  return v === null || v === undefined || !Number.isFinite(v)
    ? '—'
    : `${(v * 100).toFixed(1)}%`
}

/** Signed squeeze tone. Null stays neutral — no measurement, no colour. */
function squeezeTone(row: OptionsBoardRow): string {
  const s = row.squeeze_score
  if (s === null || s === undefined) return 'flat'
  return s > 0 ? 'pos' : s < 0 ? 'neg' : 'flat'
}

function selectionDisplay(row: OptionsBoardRow): string {
  if (row.selection_score === null || row.selection_score === undefined) return '—'
  return row.score_kind === 'calibrated_probability'
    ? pct(row.selection_score)
    : row.selection_score.toFixed(2)
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

    <div v-if="rows.length" class="board-scroll">
      <table class="grid board-table">
        <thead>
          <tr>
            <th class="label">#</th>
            <th class="label">SYM</th>
            <th class="label">
              WHY
              <HelpTip text="Which scan tier routed this name into a chain request. Ordinal except MODEL, which is the only calibrated probability on the board." />
            </th>
            <th class="label num">SCORE</th>
            <th class="label num">SPOT</th>
            <th class="label num">
              SQUEEZE
              <HelpTip text="Signed structural score. '—' means open interest was unavailable, so gamma is unmeasured — not quiet." />
            </th>
            <th class="label num">NET GEX $M</th>
            <th class="label num">PUT WALL</th>
            <th class="label num">CALL WALL</th>
            <th class="label num">EXP MOVE</th>
            <th class="label num">ATM IV</th>
            <th class="label">DATA</th>
            <th class="label num sq-col">RISK VIZ</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
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
            <td class="fig num">{{ num(row.spot) }}</td>
            <td class="fig num" :class="squeezeTone(row)">
              {{ num(row.squeeze_score, 1) }}
              <i v-if="row.squeeze_label" class="sq-label">{{ row.squeeze_label }}</i>
            </td>
            <td class="fig num">{{ num(row.net_gex_m, 1) }}</td>
            <td class="fig num put">{{ num(row.put_wall) }}</td>
            <td class="fig num call">{{ num(row.call_wall) }}</td>
            <td class="fig num">{{ num(row.expected_move) }}</td>
            <td class="fig num">{{ pct(row.atm_iv) }}</td>
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
              <span v-if="row.atm_iv != null" class="iv-chip label">IV {{ pct(row.atm_iv) }}</span>
              <!-- Expected move -->
              <span v-if="row.expected_move != null" class="em-chip label">±{{ num(row.expected_move, 1) }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-else-if="!loading" class="board-msg label">
      No scan candidate met the selection tiers. Run a deep scan from the Desk,
      or clear the live-flow filter.
    </p>

    <footer v-if="board?.caveats?.length" class="board-caveats">
      <p v-for="c in board.caveats" :key="c" class="label">{{ c }}</p>
    </footer>
  </Panel>
</template>

<style scoped>
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
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.05em;
  padding: 1px 4px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
  background: var(--panel-hi);
}

.em-chip {
  display: inline-block;
  font-size: 8.5px;
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
