<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type AnomaliesPayload } from '@/api'
import { useResource } from '@/composables/useResource'
import { num, signedPct, tone, shortDate, DASH } from '@/format'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'

/**
 * Anomalies desk — thresholded outliers only.
 * Empty panels mean the source is missing, not that markets are calm.
 */
const route = useRoute()
const router = useRouter()

const symbol = ref(((route.query.symbol as string) || '').toUpperCase())
const draft = ref(symbol.value)

const feed = useResource<AnomaliesPayload>(
  () => api.anomalies({ limit: 40, symbol: symbol.value || undefined }),
  { intervalMs: 300_000 },
)

watch(
  () => route.query.symbol,
  (s) => {
    const next = typeof s === 'string' ? s.toUpperCase() : ''
    if (next !== symbol.value) {
      symbol.value = next
      draft.value = next
      void feed.refresh()
    }
  },
)

function applySymbol(): void {
  const s = draft.value.trim().toUpperCase()
  symbol.value = s
  void router.replace({ query: s ? { symbol: s } : {} })
  void feed.refresh()
}

const d = computed(() => feed.data.value)
const unified = computed(() => d.value?.unified ?? [])
const pxRows = computed(() => (d.value?.price_volume?.rows ?? []) as any[])
const shortRows = computed(() => ((d.value?.finra_short_extremes as any)?.rows ?? []) as any[])
const optRows = computed(() => ((d.value?.options_extremes as any)?.rows ?? []) as any[])
const secRows = computed(() => ((d.value?.sec_activity as any)?.rows ?? []) as any[])
const focus = computed(() => d.value?.symbol_focus as any)

function openMarket(sym: string): void {
  void router.push({ name: 'market', query: { symbol: sym } })
}

function kindClass(kind: string): string {
  if (kind.includes('SHORT')) return 'neg'
  if (kind.includes('SEC')) return 'flat'
  if (kind.includes('OPTIONS')) return 'neg'
  return 'pos'
}
</script>

<template>
  <div class="anom-view">
    <div class="summary-deck">
      <div class="kpi-card armed">
        <span class="label kpi-label">Unified Outliers</span>
        <div class="kpi-val-row">
          <span class="kpi-val fig">{{ unified.length }}</span>
          <span class="kpi-badge flat">RANKED</span>
        </div>
        <span class="kpi-sub">Across price, FINRA, options, SEC activity</span>
      </div>
      <div class="kpi-card">
        <span class="label kpi-label">Price / Volume Flags</span>
        <div class="kpi-val-row">
          <span class="kpi-val fig">{{ d?.price_volume?.n_flagged ?? DASH }}</span>
          <span class="kpi-badge">/ {{ d?.price_volume?.n_scanned ?? '—' }} scanned</span>
        </div>
        <span class="kpi-sub">asof {{ shortDate(d?.price_volume?.asof) }}</span>
      </div>
      <div class="kpi-card">
        <span class="label kpi-label">FINRA Short Extremes</span>
        <div class="kpi-val-row">
          <span class="kpi-val fig">{{ shortRows.length }}</span>
          <span class="kpi-badge">|z| ≥ 2.0</span>
        </div>
        <span class="kpi-sub">asof {{ shortDate((d?.finra_short_extremes as any)?.asof) }}</span>
      </div>
      <div class="kpi-card">
        <span class="label kpi-label">Options P/C Extremes</span>
        <div class="kpi-val-row">
          <span class="kpi-val fig">{{ optRows.length }}</span>
          <span class="kpi-badge">P/C OI ≥ 1.3</span>
        </div>
        <span class="kpi-sub">asof {{ shortDate((d?.options_extremes as any)?.asof) }}</span>
      </div>
    </div>

    <Panel
      label="Accuracy Contract"
      index="05"
      :meta="d?.generated_at ? `gen ${d.generated_at.slice(11, 19)} UTC` : ''"
      class="w-full"
    >
      <p v-if="feed.error.value" class="err">{{ feed.error.value }}</p>
      <template v-else>
        <p class="disclaimer">{{ d?.disclaimer }}</p>
        <div v-if="d?.accuracy" class="mkt-readouts">
          <Readout
            v-for="(v, k) in (d.accuracy as any).thresholds ?? {}"
            :key="String(k)"
            :label="String(k)"
            :value="String(v)"
            size="sm"
          />
        </div>
        <div class="sym-row">
          <label class="label" for="anom-sym">Focus symbol</label>
          <input
            id="anom-sym"
            v-model="draft"
            class="sym-input"
            placeholder="NVDA"
            maxlength="10"
            @keydown.enter="applySymbol"
          />
          <button type="button" class="btn" @click="applySymbol">Inspect</button>
        </div>
      </template>
    </Panel>

    <Panel
      label="Unified Anomaly Feed"
      :meta="`${unified.length} events`"
      class="w-full"
      flush
    >
      <div class="table-container">
        <table v-if="unified.length" class="grid">
          <thead>
            <tr>
              <th class="label">Symbol</th>
              <th class="label">Kind</th>
              <th class="label num">Severity</th>
              <th class="label">Detail</th>
              <th class="label">As-of</th>
              <th class="label">Source</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in unified" :key="i" @click="openMarket(String(r.symbol))">
              <td class="row-select-cell fig sym">
  <button type="button" class="row-select-btn" @click.stop="openMarket(String(r.symbol))"><span class="sr-only">Select row</span></button>{{ r.symbol }}</td>
              <td>
                <span class="kind" :class="kindClass(String(r.kind))">{{ r.kind }}</span>
              </td>
              <td class="fig num">{{ num(r.severity as number, 2) }}</td>
              <td class="label dim feat">
                <template v-if="r.kind === 'PRICE_VOLUME'">
                  1d {{ signedPct(Number(r.ret_1d) * 100, 2) }} · 5d
                  {{ signedPct(Number(r.ret_5d) * 100, 2) }} · vol×
                  {{ num(r.volume_vs_20d_med as number, 2) }}
                  <span v-if="Array.isArray(r.flags)">
                    · {{ (r.flags as string[]).join(', ') }}</span
                  >
                </template>
                <template v-else-if="String(r.kind).includes('FINRA')">
                  ratio {{ num(r.value as number, 3) }} · z {{ num(r.z as number, 2) }}
                </template>
                <template v-else-if="String(r.kind).includes('OPTIONS')">
                  P/C OI {{ num(r.value as number, 3) }}
                </template>
                <template v-else-if="String(r.kind).includes('SEC')">
                  F4 {{ r.form4_90d }} · 8-K {{ r.eightk_90d }} · 13D/G {{ r.sc13_90d }} · latest
                  {{ r.latest_form }}
                </template>
                <template v-else>{{ r.note || '—' }}</template>
              </td>
              <td class="label dim">{{ shortDate(r.asof as string) }}</td>
              <td class="label dim feat">{{ r.source || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">
          {{
            feed.loading.value
              ? 'Scanning…'
              : 'No outliers cleared thresholds (or sources missing).'
          }}
        </p>
      </div>
    </Panel>

    <Panel
      label="Price & Volume Extremes"
      :meta="d?.price_volume?.source || ''"
      class="w-half"
      flush
    >
      <p class="note pad">{{ d?.price_volume?.lag_note }}</p>
      <div class="table-container">
        <table v-if="pxRows.length" class="grid">
          <thead>
            <tr>
              <th class="label">Sym</th>
              <th class="label num">1D</th>
              <th class="label num">5D</th>
              <th class="label num">Z1</th>
              <th class="label num">Vol×</th>
              <th class="label">Flags</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in pxRows" :key="r.symbol" @click="openMarket(r.symbol)">
              <td class="row-select-cell fig sym">
  <button type="button" class="row-select-btn" @click.stop="openMarket(r.symbol)"><span class="sr-only">Select row</span></button>{{ r.symbol }}</td>
              <td class="fig num" :class="tone(r.ret_1d)">
                {{ signedPct(Number(r.ret_1d) * 100, 2) }}
              </td>
              <td class="fig num" :class="tone(r.ret_5d)">
                {{ signedPct(Number(r.ret_5d) * 100, 2) }}
              </td>
              <td class="fig num" :class="tone(r.ret_1d_z_60d)">{{ num(r.ret_1d_z_60d, 2) }}</td>
              <td class="fig num">{{ num(r.volume_vs_20d_med, 2) }}</td>
              <td class="label dim">{{ (r.flags || []).join(', ') }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">No price/volume names cleared thresholds.</p>
      </div>
    </Panel>

    <Panel
      label="FINRA Short-Volume Extremes"
      :meta="String((d?.finra_short_extremes as any)?.source || '')"
      class="w-half"
      flush
    >
      <p class="note pad">{{ (d?.finra_short_extremes as any)?.lag_note }}</p>
      <div class="table-container">
        <table v-if="shortRows.length" class="grid">
          <thead>
            <tr>
              <th class="label">Sym</th>
              <th class="label num">Short ratio</th>
              <th class="label num">Z</th>
              <th class="label">Note</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in shortRows" :key="r.symbol" @click="openMarket(r.symbol)">
              <td class="row-select-cell fig sym">
  <button type="button" class="row-select-btn" @click.stop="openMarket(r.symbol)"><span class="sr-only">Select row</span></button>{{ r.symbol }}</td>
              <td class="fig num">{{ num(r.value, 3) }}</td>
              <td class="fig num" :class="tone(r.z)">{{ num(r.z, 2) }}</td>
              <td class="label dim feat">{{ r.note }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">No FINRA short-ratio z-score ≥ 2.0.</p>
      </div>
    </Panel>

    <Panel
      label="Options P/C OI Extremes"
      :meta="String((d?.options_extremes as any)?.source || '')"
      class="w-half"
      flush
    >
      <p class="note pad">{{ (d?.options_extremes as any)?.lag_note }}</p>
      <div class="table-container">
        <table v-if="optRows.length" class="grid">
          <thead>
            <tr>
              <th class="label">Sym</th>
              <th class="label num">P/C OI</th>
              <th class="label">Note</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in optRows" :key="r.symbol" @click="openMarket(r.symbol)">
              <td class="row-select-cell fig sym">
  <button type="button" class="row-select-btn" @click.stop="openMarket(r.symbol)"><span class="sr-only">Select row</span></button>{{ r.symbol }}</td>
              <td class="fig num neg">{{ num(r.value, 3) }}</td>
              <td class="label dim feat">{{ r.note }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">No underlyings with P/C OI ≥ 1.3 in local snapshot.</p>
      </div>
    </Panel>

    <Panel
      label="SEC Filing Activity (sample universe)"
      :meta="String((d?.sec_activity as any)?.source || '')"
      class="w-half"
      flush
    >
      <p class="note pad">{{ (d?.sec_activity as any)?.lag_note }}</p>
      <div class="table-container">
        <table v-if="secRows.length" class="grid">
          <thead>
            <tr>
              <th class="label">Sym</th>
              <th class="label num">Form4</th>
              <th class="label num">8-K</th>
              <th class="label num">13D/G</th>
              <th class="label">Latest</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in secRows" :key="r.symbol" @click="openMarket(r.symbol)">
              <td class="row-select-cell fig sym">
  <button type="button" class="row-select-btn" @click.stop="openMarket(r.symbol)"><span class="sr-only">Select row</span></button>{{ r.symbol }}</td>
              <td class="fig num">{{ r.form4_90d }}</td>
              <td class="fig num">{{ r.eightk_90d }}</td>
              <td class="fig num">{{ r.sc13_90d }}</td>
              <td class="label dim">{{ r.latest_form }} · {{ shortDate(r.latest_filing) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">
          No elevated filing activity in the scanned seed set (or SEC unreachable).
        </p>
      </div>
    </Panel>

    <Panel v-if="focus" label="Symbol Focus" :meta="focus.symbol" class="w-full">
      <div class="mkt-readouts">
        <Readout
          label="Price row"
          :value="focus.price_volume ? 'FLAGGED' : 'none'"
          :tone="focus.price_volume ? 'neg' : 'flat'"
          size="sm"
        />
        <Readout
          label="FINRA short ratio"
          :value="focus.finra ? num(focus.finra.short_ratio, 3) : DASH"
          size="sm"
        />
        <Readout
          label="Options P/C OI"
          :value="focus.options ? num(focus.options.pc_oi, 3) : DASH"
          size="sm"
        />
        <Readout label="SEC filings quality" :value="focus.filings?.quality ?? DASH" size="sm" />
      </div>
      <p class="note pad">
        Deep-dive filings on the Sentiment tab with the same symbol. Last:
        {{ focus.filings?.filings?.[0]?.form || '—' }}
        {{
          focus.filings?.filings?.[0]?.filed ? '· ' + shortDate(focus.filings.filings[0].filed) : ''
        }}
      </p>
    </Panel>
  </div>
</template>

<style scoped>
.anom-view {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s4);
  align-content: start;
}
.summary-deck {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s3);
}
.kpi-card {
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  padding: var(--s4);
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 96px;
}
.kpi-card.armed {
  border-color: var(--phosphor-dim);
  box-shadow: inset 3px 0 0 var(--phosphor);
}
.kpi-label {
  color: var(--ink-dim);
}
.kpi-val-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s2);
}
.kpi-val {
  font-family: var(--font-display);
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--ink);
}
.kpi-val.fig {
  font-variant-numeric: tabular-nums;
}
.kpi-sub {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}
.kpi-badge {
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 2px 6px;
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
}
.kpi-badge.flat {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}

.w-full {
  grid-column: 1 / -1;
}
.w-half {
  grid-column: span 1;
}

.disclaimer {
  color: var(--ink-soft);
  font-size: var(--t-small);
  line-height: 1.45;
  margin: 0 0 var(--s3);
}
.sym-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s3);
}
.sym-input {
  background: var(--void);
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink);
  font-family: var(--font-data);
  padding: 6px 10px;
  width: 9ch;
  letter-spacing: 0.06em;
}
.btn {
  background: var(--phosphor-wash);
  color: var(--phosphor);
  border: var(--hair) solid var(--phosphor-dim);
  padding: 6px 12px;
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.04em;
  cursor: pointer;
}
.btn:hover {
  background: var(--phosphor);
  color: var(--void);
}
.mkt-readouts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
}
.note.pad {
  padding: var(--s3) var(--s4);
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.4;
}
.err {
  color: var(--short);
  padding: var(--s3) var(--s4);
  font-weight: 600;
}
.table-container {
  overflow: auto;
  max-height: 480px;
}
.grid {
  width: 100%;
  border-collapse: collapse;
}
.grid th,
.grid td {
  text-align: left;
  padding: 8px 12px;
  border-bottom: var(--hair) solid var(--rule-faint);
  white-space: nowrap;
}
.grid th {
  position: sticky;
  top: 0;
  background: var(--panel-hi);
  z-index: 1;
}
.grid tbody tr {
  cursor: pointer;
}
.grid tbody tr:hover {
  background: var(--panel-hi);
}
.num {
  text-align: right !important;
  font-variant-numeric: tabular-nums;
}
.fig {
  font-variant-numeric: tabular-nums;
}
.sym {
  color: var(--phosphor);
  font-weight: 700;
}
.pos {
  color: var(--long);
}
.neg {
  color: var(--short);
}
.flat {
  color: var(--ink-dim);
}
.dim {
  color: var(--ink-faint);
}
.feat {
  max-width: 48ch;
  overflow: hidden;
  text-overflow: ellipsis;
}
.kind {
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.03em;
}
.kind.pos {
  color: var(--long);
}
.kind.neg {
  color: var(--short);
}
.kind.flat {
  color: var(--warn);
}

@media (max-width: 1100px) {
  .anom-view,
  .summary-deck {
    grid-template-columns: 1fr;
  }
  .w-half {
    grid-column: 1 / -1;
  }
}
</style>
