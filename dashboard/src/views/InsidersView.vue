<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type FintelIntelPayload,
  type FintelStatusPayload,
  type SentimentPayload,
} from '@/api'
import { useResource } from '@/composables/useResource'
import { DASH } from '@/format'
import Panel from '@/components/Panel.vue'
import HelpTip from '@/components/HelpTip.vue'
import LoadingState from '@/components/LoadingState.vue'
import {
  FORM_BRIEFS,
  formBrief,
  insiderLean,
  presentFintelInsiders,
  presentSecFilings,
} from '@/insiderDisplay'

const route = useRoute()
const router = useRouter()
const symbol = ref(((route.query.symbol as string) || 'AAPL').toUpperCase())
const draft = ref(symbol.value)

const filings = useResource<SentimentPayload>(
  () => api.sentiment(symbol.value),
  { intervalMs: 0 },
)
const status = useResource<FintelStatusPayload>(
  () => api.fintelStatus(),
  { intervalMs: 300_000 },
)
const intel = useResource<FintelIntelPayload>(
  () => api.fintelIntel(symbol.value, { country: 'US', depth: 'full' }),
  { intervalMs: 0, immediate: false },
)

watch(
  () => route.query.symbol,
  (value) => {
    const next = typeof value === 'string' ? value.toUpperCase() : symbol.value
    if (!next || next === symbol.value) return
    symbol.value = next
    draft.value = next
    void filings.refresh({ clear: true })
    intel.clear()
  },
)

function applySymbol(): void {
  const next = draft.value.trim().toUpperCase().replace(/[^A-Z0-9.-]/g, '').slice(0, 12)
  symbol.value = next || 'AAPL'
  draft.value = symbol.value
  void router.replace({ name: 'insiders', query: { symbol: symbol.value } })
  void filings.refresh({ clear: true })
  intel.clear()
}

const configured = computed(() => status.data.value?.configured === true)
const secRows = computed(() => presentSecFilings(filings.data.value?.symbol_filings))
const form4 = computed(() => secRows.value.filter((row) => row.kind === 'insider'))
const events = computed(() => secRows.value.filter((row) => row.kind === 'event'))
const holders = computed(() => secRows.value.filter((row) => row.kind === 'holder'))
const insiders = computed(() => presentFintelInsiders(intel.data.value?.blocks?.insiders))
const mix = computed(() => insiderLean(insiders.value))
const counts = computed(() => filings.data.value?.symbol_filings?.counts_90d ?? {})
</script>

<template>
  <div class="page">
    <header class="mast">
      <div class="mast-left">
        <span class="idx fig">M5</span>
        <h1 class="title lab">INSIDERS</h1>
        <HelpTip
          label="Insider tape"
          text="SEC Form 4 is the official insider-trade report. Fintel insiders are a paid overlay and stay server-side. Neither source authorizes a trade."
        />
      </div>
      <form class="sym-form" @submit.prevent="applySymbol">
        <input v-model="draft" class="sym" maxlength="12" aria-label="Ticker" />
        <button class="btn" type="submit">LOAD</button>
      </form>
    </header>

    <p class="caveat">
      Filings desk for market research. Fintel is optional and quota-metered.
      Authorized = <strong>NO</strong>. Open
      <RouterLink :to="{ name: 'options', query: { symbol } }">Options</RouterLink>
      or
      <RouterLink :to="{ name: 'flow', query: { symbol } }">Flow</RouterLink>
      for the tape.
    </p>

    <section class="briefs" aria-label="What these forms pertain to">
      <article v-for="brief in FORM_BRIEFS" :key="brief.id" class="brief">
        <span class="label brief-form">{{ brief.form }}</span>
        <strong class="brief-title">{{ brief.title }}</strong>
        <p class="brief-copy">{{ brief.meaning }}</p>
      </article>
    </section>

    <section class="kpis">
      <div class="kpi">
        <span class="label">FORM 4 / 90D</span>
        <strong class="fig">{{ counts['4'] ?? counts['4/A'] ?? form4.length }}</strong>
      </div>
      <div class="kpi">
        <span class="label">8-K / 90D</span>
        <strong class="fig">{{ counts['8-K'] ?? events.length }}</strong>
      </div>
      <div class="kpi">
        <span class="label">13D/G / 90D</span>
        <strong class="fig">{{ counts['SC 13D'] ?? holders.length }}</strong>
      </div>
      <div class="kpi">
        <span class="label">FINTEL MIX</span>
        <strong class="fig">{{ intel.data.value ? mix.label : '—' }}</strong>
        <em class="label">{{ intel.data.value ? `${mix.buys} BUY / ${mix.sells} SELL` : 'NOT LOADED' }}</em>
      </div>
    </section>

    <Panel label="SEC filings" index="01" :meta="`${secRows.length} rows`">
      <LoadingState v-if="filings.loading.value && !secRows.length" label="Loading EDGAR…" />
      <p v-else-if="filings.error.value" class="note">{{ filings.error.value }}</p>
      <table v-else-if="secRows.length" class="grid">
        <thead>
          <tr>
            <th class="label">Kind</th>
            <th class="label">Form</th>
            <th class="label">Filed</th>
            <th class="label">Detail</th>
            <th class="label">Doc</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in secRows" :key="`${row.form}-${row.filed}-${i}`">
            <td><span class="kind label" :class="row.kind">{{ row.kind.toUpperCase() }}</span></td>
            <td class="fig">{{ row.form }}</td>
            <td class="dim">{{ row.filed || DASH }}</td>
            <td class="dim">{{ formBrief(row.form).title }}{{ row.description ? ` · ${row.description}` : '' }}</td>
            <td>
              <a v-if="row.url" :href="row.url" target="_blank" rel="noopener" class="label">open</a>
              <span v-else class="dim">{{ DASH }}</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="note">No watched filings in the recent window, or ticker not in the SEC map.</p>
    </Panel>

    <Panel label="Fintel insider transactions" index="02" :meta="configured ? 'KEY ON' : 'KEY OFF'">
      <p v-if="!configured" class="note">
        FINTEL_API_KEY is missing. SEC Form 4 above is the official insider record.
      </p>
      <template v-else>
        <p class="note">
          Full-depth Fintel costs monthly weight. Load only when you need the vendor overlay.
          <button class="btn" type="button" :disabled="intel.loading.value" @click="void intel.refresh({ clear: true })">
            {{ intel.loading.value ? 'LOADING…' : 'LOAD FINTEL INSIDERS' }}
          </button>
        </p>
        <p v-if="intel.error.value" class="note">{{ intel.error.value }}</p>
        <table v-else-if="insiders.length" class="grid">
          <thead>
            <tr>
              <th class="label">Side</th>
              <th class="label">Who</th>
              <th class="label">Type</th>
              <th class="label">Detail</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in insiders" :key="`${row.who}-${i}`">
              <td><span class="kind label" :class="row.side">{{ row.side.toUpperCase() }}</span></td>
              <td class="fig">{{ row.who }}</td>
              <td>{{ row.typeLabel }}</td>
              <td class="dim">{{ row.detail }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else-if="intel.data.value" class="note">Fintel returned no insider rows.</p>
      </template>
    </Panel>
  </div>
</template>

<style scoped>
.page { display: grid; gap: var(--s4); }
.mast, .sym-form, .kpis { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s3); }
.mast { justify-content: space-between; }
.mast-left { display: flex; align-items: center; gap: var(--s2); }
.idx { opacity: 0.55; font-size: 12px; }
.title { margin: 0; letter-spacing: 0.08em; font-size: 14px; }
.caveat { margin: 0; color: var(--ink-dim); font-size: var(--t-small); max-width: 80ch; }
.caveat a { color: var(--phosphor); }
.briefs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  background: var(--rule);
  border: var(--hair) solid var(--rule);
}
.brief { display: grid; gap: 4px; padding: var(--s3); background: var(--panel); }
.brief-form { color: var(--phosphor); }
.brief-title { font: 700 var(--t-small) / 1.2 var(--font-display); color: var(--ink); }
.brief-copy { margin: 0; color: var(--ink-dim); font-size: var(--t-tiny); line-height: 1.45; }
.sym {
  width: 8rem;
  padding: 6px 8px;
  border: var(--hair) solid var(--rule);
  background: var(--void);
  color: var(--ink);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.btn {
  background: transparent;
  border: var(--hair) solid var(--rule-hi);
  color: inherit;
  padding: 6px 12px;
  font: inherit;
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  cursor: pointer;
}
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; background: var(--rule); border: var(--hair) solid var(--rule); }
.kpi { display: grid; gap: 2px; padding: var(--s3); background: var(--panel); }
.kpi strong { font: 700 var(--t-display) / 1 var(--font-display); }
.grid { width: 100%; border-collapse: collapse; }
.grid th, .grid td { padding: 6px 8px; border-bottom: var(--hair) solid var(--rule); text-align: left; }
.dim { color: var(--ink-ghost); }
.note { margin: var(--s3); color: var(--ink-dim); font-size: var(--t-small); }
.kind { padding: 1px 6px; border: var(--hair) solid var(--rule); }
.kind.buy, .kind.insider { color: var(--long); }
.kind.sell { color: var(--short); }
.kind.event, .kind.holder, .kind.other { color: var(--ink-soft); }
@media (max-width: 900px) {
  .kpis, .briefs { grid-template-columns: 1fr; }
}
</style>
