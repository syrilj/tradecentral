<script setup lang="ts">
/**
 * Index + sector gamma-regime breadth strip.
 *
 * This is the expensive read on /regime — the backend prices 15 option
 * chains to answer it, a 30-45s cold call against a rate-limited paid
 * provider — so this component never fetches on its own. It stays in an
 * explicit idle state until the operator asks for it, then tells its parent
 * via `activate`; the parent owns the resource.
 *
 * Activation is deliberately a CLICK, not visibility. An IntersectionObserver
 * was tried first and was wrong: this section sits above the fold at the
 * default window size, so "scrolled into view" fired on page load and spent
 * the most expensive call in the app before the operator had asked for
 * anything. Viewport-deferred loading is for cheap content; a metered call
 * needs intent, and intent means a click.
 *
 * The one number that matters here is not any single row — it is the
 * divergence note: an index pinned long-gamma while its heavy sectors run
 * short-gamma means the index print is held up while the money underneath
 * it is already free to move. That note is surfaced above the table, not
 * buried in it.
 */
import { computed, ref } from 'vue'
import type { GammaRegime, RegimeBreadthPayload, RegimeSymbolRow } from '@/regimeContracts'
import { age, signedPct } from '@/format'
import LoadingState from '@/components/LoadingState.vue'

const props = withDefaults(
  defineProps<{
    payload: RegimeBreadthPayload | null
    activated: boolean
    loading?: boolean
    error?: string | null
    fetchedAt?: string | null
  }>(),
  { loading: false, error: null, fetchedAt: null },
)

const emit = defineEmits<{ activate: [] }>()

const hostRef = ref<HTMLElement | null>(null)

/** Only ever called from the operator's own click on the idle gate. */
function fireActivate(): void {
  if (props.activated) return
  emit('activate')
}

const indices = computed(() => (props.payload?.rows ?? []).filter((r) => r.kind === 'index'))
const sectors = computed(() => (props.payload?.rows ?? []).filter((r) => r.kind === 'sector'))

const regimeLabel: Record<GammaRegime, string> = {
  short: 'SHORT',
  long: 'LONG',
  flip: 'FLIP',
  unmeasurable: 'N/M',
}

function regimeClass(r: GammaRegime): string {
  if (r === 'short') return 'is-short'
  if (r === 'long') return 'is-long'
  if (r === 'flip') return 'is-flip'
  return 'is-unmeasurable'
}

function trendArrow(t: RegimeSymbolRow['trend']): string {
  if (t === 'up') return '↑'
  if (t === 'down') return '↓'
  if (t === 'flat') return '→'
  return '—'
}

function trendClass(t: RegimeSymbolRow['trend']): string {
  if (t === 'up') return 'is-long'
  if (t === 'down') return 'is-short'
  return 'is-flat'
}

function distanceLabel(row: RegimeSymbolRow): string {
  if (row.distanceToFlip == null || !Number.isFinite(row.distanceToFlip)) return '—'
  return signedPct(row.distanceToFlip * 100, 2)
}

const stalenessLabel = computed(() => (props.fetchedAt ? `AS OF ${age(props.fetchedAt)} AGO` : ''))

/**
 * The table answers "which name is in which regime" one row at a time; the
 * question breadth actually exists to answer is the aggregate — how much of
 * the tape is pinned vs free. One chip line, counted across all rows.
 */
const regimeCounts = computed(() => {
  const rows = props.payload?.rows ?? []
  const counts = { long: 0, short: 0, flip: 0, unmeasurable: 0 }
  for (const r of rows) counts[r.regime] += 1
  return counts
})

/** Rows whose chain fell back to a dated snapshot — one aggregate mention
 *  replaces nine identical warnings. */
const fallbackRowCount = computed(() => (props.payload?.rows ?? []).filter((r) => r.note).length)

/** Same message repeated once per symbol is spam, not caution — dedupe. */
const uniqueWarnings = computed(() => [...new Set(props.payload?.warnings ?? [])])
</script>

<template>
  <section ref="hostRef" class="breadth-strip" aria-label="Index and sector gamma-regime breadth">
    <!-- Idle until asked. This control is the ONLY way breadth ever fetches. -->
    <div v-if="!activated" class="idle-state">
      <p class="idle-copy label wraps">
        Breadth prices 15 option chains against a metered feed, roughly 30 to 45s when cold. It
        stays off until you ask for it.
      </p>
      <button type="button" class="go-live-btn" @click="fireActivate">GO LIVE</button>
    </div>

    <template v-else>
      <LoadingState v-if="loading && !payload" label="Loading breadth" compact />

      <p v-else-if="error && !payload" class="error-copy label wraps" role="alert">
        Breadth unavailable: {{ error }}
      </p>

      <template v-else-if="payload">
        <div v-if="payload.divergence" class="divergence-banner" role="note">
          <span class="divergence-tag label">DIVERGENCE</span>
          <span class="divergence-text">{{ payload.divergence.note }}</span>
        </div>

        <div class="counts-row" role="note" aria-label="Regime breadth counts">
          <span class="count-chip is-long">LONG {{ regimeCounts.long }}</span>
          <span class="count-chip is-short">SHORT {{ regimeCounts.short }}</span>
          <span class="count-chip is-flip">FLIP {{ regimeCounts.flip }}</span>
          <span v-if="regimeCounts.unmeasurable" class="count-chip is-unmeasurable">
            N/M {{ regimeCounts.unmeasurable }}
          </span>
          <span
            v-if="fallbackRowCount"
            class="count-chip is-unmeasurable"
            :title="`${fallbackRowCount} chains on dated snapshots`"
          >
            DATED CHAIN ×{{ fallbackRowCount }}
          </span>
        </div>

        <div class="strip-meta">
          <span v-if="stalenessLabel" class="label">{{ stalenessLabel }}</span>
          <span v-if="payload.cache?.hit" class="label cache-tag"
            >CACHED · {{ payload.cache.age_seconds }}s</span
          >
        </div>

        <table class="breadth-table">
          <caption class="visually-hidden">
            Index and sector dealer-gamma regime breadth
          </caption>
          <thead>
            <tr>
              <th scope="col">Symbol</th>
              <th scope="col">Regime</th>
              <th scope="col">Dist. to flip</th>
              <th scope="col">Trend</th>
            </tr>
          </thead>
          <tbody v-if="indices.length">
            <tr class="group-row">
              <th scope="colgroup" colspan="4" class="label">INDICES</th>
            </tr>
            <tr v-for="row in indices" :key="row.symbol" :class="{ unmeasurable: !row.measurable }">
              <td>
                <span class="sym fig">{{ row.symbol }}</span>
                <span v-if="row.note" class="row-note" :title="row.note">*</span>
              </td>
              <td>
                <span class="regime-chip" :class="regimeClass(row.regime)">{{
                  regimeLabel[row.regime]
                }}</span>
              </td>
              <td class="fig">{{ distanceLabel(row) }}</td>
              <td class="fig" :class="trendClass(row.trend)">{{ trendArrow(row.trend) }}</td>
            </tr>
          </tbody>
          <tbody v-if="sectors.length">
            <tr class="group-row">
              <th scope="colgroup" colspan="4" class="label">SECTORS</th>
            </tr>
            <tr v-for="row in sectors" :key="row.symbol" :class="{ unmeasurable: !row.measurable }">
              <td>
                <span class="sym fig">{{ row.symbol }}</span>
                <span v-if="row.note" class="row-note" :title="row.note">*</span>
              </td>
              <td>
                <span class="regime-chip" :class="regimeClass(row.regime)">{{
                  regimeLabel[row.regime]
                }}</span>
              </td>
              <td class="fig">{{ distanceLabel(row) }}</td>
              <td class="fig" :class="trendClass(row.trend)">{{ trendArrow(row.trend) }}</td>
            </tr>
          </tbody>
        </table>

        <p v-if="!indices.length && !sectors.length" class="label wraps">
          No breadth rows returned for this universe.
        </p>

        <ul v-if="uniqueWarnings.length" class="warnings label wraps">
          <li v-for="(w, i) in uniqueWarnings" :key="i">{{ w }}</li>
        </ul>
      </template>

      <p v-else class="label wraps">No breadth data yet.</p>
    </template>
  </section>
</template>

<style scoped>
.breadth-strip {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  min-width: 0;
}

.idle-state {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--s2);
  padding: var(--s4);
  border: var(--hair) dashed var(--rule-hi);
  border-radius: var(--r-md);
  background: var(--surface-base);
}

.idle-copy {
  color: var(--ink-dim);
}

.go-live-btn {
  padding: var(--s1) var(--s3);
  border: var(--hair) solid var(--phosphor);
  border-radius: var(--r-sm);
  background: var(--phosphor-wash);
  color: var(--phosphor);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.06em;
}

.error-copy {
  color: var(--short);
}

.divergence-banner {
  display: flex;
  align-items: baseline;
  gap: var(--s2);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--warn);
  border-radius: var(--r-sm);
  background: var(--warn-wash);
}

.divergence-tag {
  flex: 0 0 auto;
  color: var(--warn);
}

.divergence-text {
  color: var(--ink);
  font-size: var(--t-small);
  line-height: 1.4;
}

.strip-meta {
  display: flex;
  gap: var(--s3);
  color: var(--ink-faint);
}

.counts-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
}

.count-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 9px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-capsule);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.05em;
}

.count-chip.is-long {
  color: var(--long);
  background: var(--long-wash);
  border-color: var(--long);
}

.count-chip.is-short {
  color: var(--short);
  background: var(--short-wash);
  border-color: var(--short);
}

.count-chip.is-flip {
  color: var(--warn);
  background: var(--warn-wash);
  border-color: var(--warn);
}

.count-chip.is-unmeasurable {
  color: var(--ink-faint);
  background: var(--surface-base);
  border-color: var(--rule);
}

.cache-tag {
  color: var(--ink-faint);
}

.breadth-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-small);
}

.breadth-table th,
.breadth-table td {
  padding: var(--s1) var(--s2);
  text-align: left;
  border-bottom: var(--hair) solid var(--rule);
}

.breadth-table thead th {
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.group-row th {
  padding-top: var(--s2);
  color: var(--ink-faint);
  background: none;
  border-bottom: var(--hair) solid var(--rule-faint);
}

tr.unmeasurable {
  opacity: 0.6;
}

.sym {
  color: var(--ink);
  font-weight: 600;
}

.row-note {
  margin-left: 4px;
  color: var(--warn);
  cursor: help;
}

.regime-chip {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: var(--r-capsule);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.04em;
  border: var(--hair) solid transparent;
}

.regime-chip.is-short {
  color: var(--short);
  background: var(--short-wash);
  border-color: var(--short);
}

.regime-chip.is-long {
  color: var(--long);
  background: var(--long-wash);
  border-color: var(--long);
}

.regime-chip.is-flip {
  color: var(--warn);
  background: var(--warn-wash);
  border-color: var(--warn);
}

.regime-chip.is-unmeasurable {
  color: var(--ink-faint);
  background: var(--surface-base);
  border-color: var(--rule);
}

.is-long {
  color: var(--long);
}
.is-short {
  color: var(--short);
}
.is-flat {
  color: var(--ink-dim);
}

.warnings {
  margin: 0;
  padding-left: var(--s4);
  color: var(--warn);
}

/* Standard visually-hidden pattern, matches RegimeSurfaceChart's table. */
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
