<script setup lang="ts">
import { computed } from 'vue'
import { api } from '@/api'
import { useResource } from '@/composables/useResource'
import { num, age, pick, DASH } from '@/format'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import VerdictChip from '@/components/VerdictChip.vue'

/**
 * Vertex AI training surface. Jobs poll on a short interval because a Spot VM
 * can be preempted at any moment and a stale RUNNING badge is how you end up
 * waiting on a job that died twenty minutes ago.
 */
const gcp = useResource<Record<string, unknown>>(() => api.gcp(), { intervalMs: 45_000 })

/** The resource payload is loosely shaped; find the job list wherever it sits. */
const jobs = computed(() => {
  const g = gcp.data.value
  if (!g) return []
  const candidates = [
    pick(g, 'vertex_jobs', 'jobs', 'custom_jobs', 'training_jobs'),
    (g as Record<string, unknown>).vertex,
  ]
  for (const c of candidates) {
    if (Array.isArray(c)) return c as Record<string, unknown>[]
    if (c && typeof c === 'object') {
      const inner = pick(c, 'jobs', 'items')
      if (Array.isArray(inner)) return inner as Record<string, unknown>[]
    }
  }
  return []
})

function stateOf(j: Record<string, unknown>): string {
  const s = String(pick(j, 'state', 'status') ?? 'UNKNOWN')
  return s.replace(/^JOB_STATE_/, '')
}

function stateKind(s: string): string {
  const u = s.toUpperCase()
  if (u.includes('SUCCEED')) return 'GO'
  if (u.includes('FAIL') || u.includes('CANCEL') || u.includes('EXPIRE')) return 'NO-GO'
  if (u.includes('RUN') || u.includes('PEND') || u.includes('QUEUE')) return 'RUNNING'
  return 'UNKNOWN'
}

const counts = computed(() => {
  const c: Record<string, number> = { RUNNING: 0, GO: 0, 'NO-GO': 0, UNKNOWN: 0 }
  for (const j of jobs.value) c[stateKind(stateOf(j))]++
  return c
})

const storage = computed(() => pick(gcp.data.value, 'storage', 'gcs', 'buckets'))
const credits = computed(() => pick(gcp.data.value, 'credits', 'billing', 'cost'))

/** Anything the shaped panels did not consume, shown verbatim rather than dropped. */
const extras = computed(() => {
  const g = gcp.data.value
  if (!g) return []
  const consumed = new Set([
    'vertex_jobs',
    'jobs',
    'custom_jobs',
    'training_jobs',
    'vertex',
    'storage',
    'gcs',
    'buckets',
    'credits',
    'billing',
    'cost',
  ])
  return Object.entries(g)
    .filter(
      ([k, v]) =>
        !consumed.has(k) &&
        (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'),
    )
    .slice(0, 12)
})
</script>

<template>
  <div class="cloud">
    <Panel
      label="Vertex AI training"
      index="04"
      :meta="gcp.fetchedAt.value ? `polled ${age(gcp.fetchedAt.value)} ago` : ''"
      class="w-full"
      live
    >
      <p v-if="gcp.error.value" class="err">{{ gcp.error.value }}</p>
      <template v-else>
        <div class="counts">
          <Readout label="Running" :value="String(counts.RUNNING)" tone="accent" />
          <Readout label="Succeeded" :value="String(counts.GO)" tone="pos" />
          <Readout label="Failed" :value="String(counts['NO-GO'])" tone="neg" />
          <Readout label="Total tracked" :value="String(jobs.length)" tone="flat" />
        </div>
      </template>
    </Panel>

    <Panel
      label="Job queue"
      index="—"
      :meta="`${jobs.length} job${jobs.length === 1 ? '' : 's'}`"
      :delay="60"
      flush
      class="w-full"
    >
      <table v-if="jobs.length" class="grid">
        <thead>
          <tr>
            <th class="label">Display name</th>
            <th class="label">State</th>
            <th class="label">Created</th>
            <th class="label num">Elapsed</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(j, i) in jobs" :key="i">
            <td class="fig name">{{ pick(j, 'display_name', 'displayName', 'name') ?? DASH }}</td>
            <td><VerdictChip :verdict="stateOf(j)" size="sm" /></td>
            <td class="fig dim">{{ pick(j, 'create_time', 'createTime', 'created') ?? DASH }}</td>
            <td class="fig num dim">
              {{ age(String(pick(j, 'create_time', 'createTime', 'created') ?? '')) }}
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="note pad">
        No Vertex AI jobs reported. Submit with
        <code>bash edge/tools/run_gcp_training_suite.sh</code>.
      </p>
    </Panel>

    <Panel v-if="storage" label="Artifact storage" index="—" :delay="120">
      <pre class="raw">{{ JSON.stringify(storage, null, 2) }}</pre>
    </Panel>

    <Panel v-if="credits" label="Credits & cost" index="—" :delay="160">
      <pre class="raw">{{ JSON.stringify(credits, null, 2) }}</pre>
    </Panel>

    <Panel v-if="extras.length" label="Environment" index="—" :delay="200">
      <dl class="kv">
        <template v-for="[k, v] in extras" :key="k">
          <dt class="label">{{ k.replace(/_/g, ' ') }}</dt>
          <dd class="fig">{{ typeof v === 'number' ? num(v, 2) : String(v) }}</dd>
        </template>
      </dl>
    </Panel>
  </div>
</template>

<style scoped>
.cloud {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--s4);
  align-items: start;
}
.w-full {
  grid-column: 1 / -1;
}

.counts {
  display: flex;
  gap: var(--s7);
  flex-wrap: wrap;
}

.grid {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-small);
}
.grid th {
  text-align: left;
  padding: var(--s2) var(--s4);
  color: var(--ink-faint);
  border-bottom: var(--hair) solid var(--rule);
  font-weight: 600;
}
.grid td {
  padding: 5px var(--s4);
  border-bottom: var(--hair) solid var(--rule-faint);
  color: var(--ink-soft);
}
.num {
  text-align: right;
}
.name {
  color: var(--ink);
  font-weight: 500;
}
.dim {
  color: var(--ink-faint);
  font-size: var(--t-tiny);
}

.raw {
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  color: var(--ink-dim);
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 260px;
  overflow: auto;
}

.kv {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 3px var(--s3);
  align-items: baseline;
}
.kv dt {
  color: var(--ink-faint);
}
.kv dd {
  font-size: var(--t-small);
  color: var(--ink-soft);
  text-align: right;
}

.note {
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.5;
}
.note.pad {
  padding: var(--s5) var(--s4);
}
.note code {
  font-family: var(--font-data);
  color: var(--phosphor-dim);
}
.err {
  color: var(--short);
  font-size: var(--t-small);
}
</style>
