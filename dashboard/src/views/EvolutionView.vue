<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type GaPayload, type GaRunSummary } from '@/api'
import { useResource } from '@/composables/useResource'
import { num, age, DASH } from '@/format'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import VerdictChip from '@/components/VerdictChip.vue'

/**
 * Genetic evolution lab — research-only survivors from local / Vertex GA runs.
 * Never presents GA fitness as live trading authority.
 */
const selectedId = ref<string | undefined>(undefined)
const ga = useResource<GaPayload>(() => api.ga(selectedId.value), { intervalMs: 90_000 })

watch(
  () => ga.data.value?.selected_run_id,
  (id) => {
    if (id && !selectedId.value) selectedId.value = id
  },
)

const runs = computed(() => ga.data.value?.runs ?? [])
const detail = computed(() => ga.data.value?.detail ?? null)
const history = computed(() => detail.value?.history ?? [])
const elites = computed(() => detail.value?.elites ?? [])
const confirmation = computed(() => detail.value?.confirmation ?? [])
const notes = computed(() => ga.data.value?.notes ?? detail.value?.notes ?? [])

const bestFit = computed(() => {
  const h = history.value
  if (!h.length) return null
  return h[h.length - 1]?.best_fitness ?? null
})
const confPass = computed(() => confirmation.value.filter((c) => c.passes_confirmation).length)

const spark = computed(() => {
  const pts = history.value
  if (pts.length < 2) return ''
  const vals = pts.map((p) => Number(p.best_fitness))
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const span = hi - lo || 1
  const w = 280
  const h = 56
  return vals
    .map((v, i) => {
      const x = (i / (vals.length - 1)) * w
      const y = h - ((v - lo) / span) * (h - 6) - 3
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})

function selectRun(r: GaRunSummary) {
  selectedId.value = r.run_id
  void ga.refresh({ clear: true })
}

function fmtFit(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return DASH
  return Number(v).toFixed(3)
}

function geneLine(g: import('@/api').GaGenes | Record<string, unknown> | undefined): string {
  if (!g) return DASH
  const rec = g as Record<string, unknown>
  const family = String(rec.signal_family ?? '?')
  const lb = rec.lookback ?? '?'
  const h = rec.horizon_days ?? '?'
  const k = rec.top_k ?? '?'
  const mode = rec.long_short ?? '?'
  return `${family} · L${lb} · H${h} · k=${k} · ${mode}`
}
</script>

<template>
  <div class="evo">
    <Panel
      label="Genetic evolution lab"
      index="08"
      :meta="ga.fetchedAt.value ? `polled ${age(ga.fetchedAt.value)} ago` : 'research only'"
      class="w-full"
      live
    >
      <p v-if="ga.error.value" class="err">{{ ga.error.value }}</p>
      <template v-else>
        <div class="banner">
          <span class="pill">RESEARCH ONLY</span>
          <span class="banner-text">
            Fitness never uses the sealed terminal holdout. Survivors are not live signals: promote
            only through Gates / shadow.
          </span>
        </div>
        <div class="counts">
          <Readout label="Runs on disk" :value="String(runs.length)" tone="flat" />
          <Readout
            label="Best fitness"
            :value="fmtFit(bestFit)"
            :tone="(bestFit ?? -99) > 0 ? 'pos' : 'flat'"
          />
          <Readout
            label="Confirm pass"
            :value="`${confPass}/${confirmation.length || 0}`"
            :tone="confPass > 0 ? 'pos' : 'flat'"
          />
          <Readout label="Elites" :value="String(elites.length)" tone="accent" />
        </div>
        <p v-if="ga.data.value?.error" class="err soft">{{ ga.data.value.error }}</p>
      </template>
    </Panel>

    <div class="split">
      <Panel
        label="Run archive"
        :meta="`${runs.length} run${runs.length === 1 ? '' : 's'}`"
        :delay="40"
        flush
        class="runs-panel"
      >
        <table v-if="runs.length" class="grid">
          <thead>
            <tr>
              <th class="label">Run</th>
              <th class="label num">Best</th>
              <th class="label num">Gens</th>
              <th class="label num">Conf</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in runs"
              :key="r.run_id"
              class="row-click"
              :class="{ active: r.run_id === selectedId || r.run_id === detail?.run_id }"
              @click="selectRun(r)"
            >
              <td class="row-select-cell fig name">
  <button type="button" class="row-select-btn" @click.stop="selectRun(r)"><span class="sr-only">Select row</span></button>
                <div class="run-id">{{ r.run_id }}</div>
                <div class="dim tiny">
                  {{ r.created_at ? age(String(r.created_at)) : DASH }} ago
                </div>
              </td>
              <td class="fig num">{{ fmtFit(r.best_fitness) }}</td>
              <td class="fig num dim">{{ r.n_generations ?? DASH }}</td>
              <td class="fig num">
                {{ r.confirmation_passes ?? 0 }}/{{ r.confirmation_total ?? 0 }}
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">
          No GA runs yet. Local:
          <code>python edge/tools/run_ga_evolve.py --smoke</code>
          · GCP:
          <code>python edge/tools/gcp_ga_evolve.py submit --dry-run</code>
        </p>
      </Panel>

      <Panel
        label="Fitness trajectory"
        :meta="detail?.run_id ? detail.run_id : 'no run selected'"
        :delay="80"
        class="chart-panel"
      >
        <svg v-if="spark" role="img" aria-label="Strategy evolution over time." class="spark" viewBox="0 0 280 56" preserveAspectRatio="none">
          <path :d="spark" fill="none" stroke="currentColor" stroke-width="1.5" />
        </svg>
        <p v-else class="note">Run an evolution job to plot best-fitness by generation.</p>
        <div v-if="history.length" class="hist-meta">
          <span class="label">gen 0 → {{ history.length - 1 }}</span>
          <span class="fig dim">
            mean final {{ fmtFit(history[history.length - 1]?.mean_fitness) }}
          </span>
        </div>
      </Panel>
    </div>

    <Panel
      label="In-sample elites"
      :meta="`${elites.length} survivors`"
      :delay="100"
      flush
      class="w-full"
    >
      <table v-if="elites.length" class="grid">
        <thead>
          <tr>
            <th class="label">Genome</th>
            <th class="label">Genes</th>
            <th class="label num">Fitness</th>
            <th class="label num">Sharpe</th>
            <th class="label num">Max DD</th>
            <th class="label">Alive</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in elites" :key="e.id">
            <td class="fig name">{{ e.id }}</td>
            <td class="fig dim gene">{{ geneLine(e.genes) }}</td>
            <td class="fig num">{{ fmtFit(e.fitness) }}</td>
            <td class="fig num">{{ num(e.metrics?.sharpe as number | null, 2) }}</td>
            <td class="fig num">{{ num(e.metrics?.max_drawdown as number | null, 3) }}</td>
            <td>
              <VerdictChip :verdict="e.alive ? 'GO' : e.death_reason || 'NO-GO'" size="sm" />
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="note pad">No elites in selected run.</p>
    </Panel>

    <Panel
      label="Confirmation window"
      :meta="'out-of-sample re-score (not sealed holdout)'"
      :delay="140"
      flush
      class="w-full"
    >
      <table v-if="confirmation.length" class="grid">
        <thead>
          <tr>
            <th class="label">Genome</th>
            <th class="label num">IS fit</th>
            <th class="label num">Conf fit</th>
            <th class="label num">Conf Sharpe</th>
            <th class="label">Pass</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in confirmation" :key="c.id">
            <td class="fig name">{{ c.id }}</td>
            <td class="fig num">{{ fmtFit(c.fitness_in_sample) }}</td>
            <td class="fig num">{{ fmtFit(c.fitness_confirmation) }}</td>
            <td class="fig num">
              {{ num(c.metrics_confirmation?.sharpe as number | null, 2) }}
            </td>
            <td>
              <VerdictChip :verdict="c.passes_confirmation ? 'GO' : 'NO-GO'" size="sm" />
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="note pad">Confirmation block empty: re-run with confirmation enabled.</p>
    </Panel>

    <Panel label="How to run" :delay="180" class="w-full">
      <ul class="cmds">
        <li>
          <code>python edge/tools/run_ga_evolve.py --smoke</code>
          <span class="dim">local preflight</span>
        </li>
        <li>
          <code>python edge/tools/run_ga_evolve.py --pop 200 --gens 15</code>
          <span class="dim">full local search</span>
        </li>
        <li>
          <code>python edge/tools/gcp_ga_evolve.py submit --dry-run</code>
          <span class="dim">validate Vertex job</span>
        </li>
        <li>
          <code>python edge/tools/gcp_ga_evolve.py submit --pop 300 --gens 20</code>
          <span class="dim">SPOT CPU on GCP</span>
        </li>
        <li>
          <code>python edge/tools/gcp_ga_evolve.py fetch</code>
          <span class="dim">pull GCS artifacts → runs/ga/</span>
        </li>
      </ul>
      <p v-if="notes.length" class="notes">
        <span v-for="(n, i) in notes" :key="i" class="note-line">{{ n }}</span>
      </p>
    </Panel>
  </div>
</template>

<style scoped>
.evo {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}
.banner {
  display: flex;
  align-items: flex-start;
  gap: var(--s3);
  margin-bottom: var(--s3);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.pill {
  flex: 0 0 auto;
  font-family: var(--font-display);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  font-weight: 700;
  color: var(--phosphor);
}
.banner-text {
  font-size: var(--t-small);
  line-height: 1.4;
  color: var(--ink-soft);
}
.counts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s3);
}
.split {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: var(--s4);
}
.row-click {
  cursor: pointer;
}
.row-click:hover td {
  background: var(--panel-hi);
}
.row-click.active td {
  background: var(--phosphor-glow);
}
.run-id {
  max-width: 14rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tiny {
  font-size: 0.7rem;
}
.gene {
  font-size: 0.78rem;
  max-width: 22rem;
}
.spark {
  width: 100%;
  height: 72px;
  color: var(--phosphor);
  display: block;
}
.hist-meta {
  display: flex;
  justify-content: space-between;
  margin-top: var(--s2);
  font-size: var(--t-tiny);
}
.cmds {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.cmds li {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  align-items: baseline;
}
.cmds code {
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  padding: 2px var(--s1);
  background: var(--panel-raise);
  color: var(--ink-soft);
}
.notes {
  margin-top: var(--s3);
  display: flex;
  flex-direction: column;
  gap: var(--s1);
}
.note-line {
  font-size: var(--t-tiny);
  color: var(--ink-faint);
}
.note,
.err {
  font-size: var(--t-small);
}
.note {
  color: var(--ink-dim);
}
.err {
  color: var(--short);
}
.err.soft {
  margin-top: var(--s2);
}
.pad {
  padding: var(--s3) var(--s4);
}
.dim {
  color: var(--ink-faint);
}
.name {
  font-variant-numeric: tabular-nums;
}
@media (max-width: 960px) {
  .counts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .split {
    grid-template-columns: 1fr;
  }
}
</style>
