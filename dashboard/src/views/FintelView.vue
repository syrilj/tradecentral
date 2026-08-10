<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type FintelIntelPayload,
  type FintelStatusPayload,
  type FintelStreamPayload,
} from '@/api'
import { useResource } from '@/composables/useResource'
import { num, compact, DASH } from '@/format'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import HelpTip from '@/components/HelpTip.vue'
import LoadingState from '@/components/LoadingState.vue'

/**
 * Fintel analysis desk — short interest, borrow, ownership, unusual options.
 * Server proxies api.fintel.io with X-API-KEY from FINTEL_API_KEY (never in browser).
 * Research attention only — not trade-authorized.
 */
const route = useRoute()
const router = useRouter()

const tab = ref<'stream' | 'symbol'>(route.query.tab === 'symbol' ? 'symbol' : 'stream')
const symbol = ref(((route.query.symbol as string) || 'AAPL').toUpperCase())
const draft = ref(symbol.value)

const status = useResource<FintelStatusPayload>(() => api.fintelStatus(), { intervalMs: 300_000 })
/* Manual / slow poll only — Fintel bills monthly API weight; auto-refresh burns quota. */
const stream = useResource<FintelStreamPayload>(
  () => api.fintelStream({ squeezeLimit: 25, shortInterestLimit: 25 }),
  { intervalMs: 0, immediate: true },
)
const intel = useResource<FintelIntelPayload>(
  () => api.fintelIntel(symbol.value || 'AAPL', { country: 'US', depth: 'core' }),
  { intervalMs: 0, immediate: false },
)

watch(
  () => route.query.symbol,
  (s) => {
    const next = typeof s === 'string' ? s.toUpperCase() : symbol.value
    if (next && next !== symbol.value) {
      symbol.value = next
      draft.value = next
      if (tab.value === 'symbol') void intel.refresh({ clear: true })
    }
  },
)

watch(
  () => route.query.tab,
  (t) => {
    if (t === 'symbol' || t === 'stream') tab.value = t
  },
)

function setTab(next: 'stream' | 'symbol'): void {
  tab.value = next
  void router.replace({
    name: 'fintel',
    query: {
      ...(symbol.value ? { symbol: symbol.value } : {}),
      ...(next === 'symbol' ? { tab: 'symbol' } : {}),
    },
  })
  if (next === 'symbol') void intel.refresh({ clear: true })
  if (next === 'stream') void stream.refresh()
}

function applySymbol(): void {
  const s = draft.value.trim().toUpperCase().replace(/[^A-Z0-9.-]/g, '').slice(0, 12)
  draft.value = s
  symbol.value = s || 'AAPL'
  void router.replace({
    name: 'fintel',
    query: {
      symbol: symbol.value,
      tab: 'symbol',
    },
  })
  tab.value = 'symbol'
  void intel.refresh({ clear: true })
}

const configured = computed(() => status.data.value?.configured === true)
const streamBoards = computed(() => stream.data.value?.boards ?? {})
const squeezeRows = computed(() => asRows(streamBoards.value.short_squeeze))
const shortRows = computed(() => asRows(streamBoards.value.short_interest))
const gainerRows = computed(() => asRows(streamBoards.value.gainers))
const loserRows = computed(() => asRows(streamBoards.value.losers))
const volumeRows = computed(() => asRows(streamBoards.value.volume))
const earnings = computed(() => asRows(streamBoards.value.earnings_calendar).slice(0, 20))

const analysis = computed(() => intel.data.value?.analysis)
const metrics = computed(() => analysis.value?.metrics ?? {})
const notes = computed(() => analysis.value?.notes ?? [])
const attention = computed(() => analysis.value?.attention_score ?? null)
const insiders = computed(() => asRows(intel.data.value?.blocks?.insiders).slice(0, 12))
const owners = computed(() => asRows(intel.data.value?.blocks?.owners).slice(0, 12))
const unusual = computed(() => asRows(intel.data.value?.blocks?.options_flow_unusual).slice(0, 12))
const blockErrors = computed(() => intel.data.value?.errors ?? {})
const streamErrors = computed(() => stream.data.value?.errors ?? {})

const quotaHit = computed(() => {
  if (stream.data.value?.quota_exceeded || stream.data.value?.error_kind === 'quota') return true
  if (intel.data.value?.quota_exceeded || intel.data.value?.error_kind === 'quota') return true
  const blob = [
    stream.error.value,
    intel.error.value,
    stream.data.value?.error,
    intel.data.value?.error,
    ...Object.values(blockErrors.value),
    ...Object.values(streamErrors.value),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  return blob.includes('quota') || blob.includes('monthly api') || blob.includes('429')
})

const quotaMessage = computed(() => {
  return (
    intel.data.value?.error ||
    stream.data.value?.error ||
    intel.error.value ||
    stream.error.value ||
    'Fintel monthly API key weight limit exceeded. Wait for reset or upgrade the plan at fintel.io/u/dev.'
  )
})

function friendlySliceError(err: string | undefined): string {
  if (!err) return 'No rows'
  if (/quota|429|weight limit/i.test(err)) return 'Quota exceeded — slice unavailable this month'
  return err.length > 120 ? err.slice(0, 117) + '…' : err
}

function asRows(value: unknown): Record<string, any>[] {
  if (Array.isArray(value)) return value as Record<string, any>[]
  if (value && typeof value === 'object') {
    const o = value as Record<string, any>
    for (const k of ['items', 'entries', 'results', 'rows', 'data', 'transactions', 'owners']) {
      if (Array.isArray(o[k])) return o[k]
    }
  }
  return []
}

function rowSym(row: Record<string, any>): string {
  return String(
    row.security_symbol ?? row.symbol ?? row.ticker ?? row.Symbol ?? row.securitySymbol ?? '—',
  ).toUpperCase()
}

function rowName(row: Record<string, any>): string {
  return String(row.security_name ?? row.name ?? row.company ?? row.Name ?? '')
}

function rowMetric(row: Record<string, any>, keys: string[]): string {
  for (const k of keys) {
    if (row[k] != null && row[k] !== '') {
      const v = row[k]
      if (typeof v === 'number') return Number.isInteger(v) ? compact(v) : num(v, 2)
      return String(v)
    }
  }
  return DASH
}

function openSym(sym: string): void {
  draft.value = sym
  symbol.value = sym
  setTab('symbol')
  void intel.refresh({ clear: true })
}

function refreshAll(): void {
  void status.refresh()
  if (tab.value === 'stream') void stream.refresh({ clear: false })
  else void intel.refresh({ clear: false })
}

const streamAge = computed(() => stream.fetchedAt.value)
const intelAge = computed(() => intel.fetchedAt.value)
const depthIsCore = computed(() => (intel.data.value?.depth ?? 'core') === 'core')
</script>

<template>
  <div class="fintel page">
    <header class="mast">
      <div class="mast-left">
        <span class="idx fig">12</span>
        <h1 class="title lab">FINTEL STREAM</h1>
        <HelpTip
          label="Fintel Public Data API"
          text="Short interest, borrow fees, 13F owners, insiders, and unusual options flow via Fintel. Key stays server-side (FINTEL_API_KEY → X-API-KEY). Analysis attention only — never a live order path."
        />
      </div>
      <div class="mast-right">
        <span class="pill" :class="configured ? 'ok' : 'bad'">
          {{ configured ? 'KEY CONFIGURED' : 'KEY MISSING' }}
        </span>
        <button class="btn" type="button" @click="refreshAll">Refresh</button>
      </div>
    </header>

    <Panel
      v-if="quotaHit"
      label="Fintel quota exceeded"
      index="00"
      meta="monthly weight"
      class="quota"
    >
      <p class="quota-body">{{ quotaMessage }}</p>
      <ul class="notes">
        <li>This is a Fintel plan limit, not an EDGE bug. Key is valid; weight budget is empty.</li>
        <li>Owners / insiders / options use more weight — default symbol depth is now <code>core</code> only (price, short %, borrow).</li>
        <li>Auto-poll is off. Use <strong>Refresh</strong> sparingly after the quota resets or you upgrade.</li>
        <li>
          Check usage / upgrade:
          <a href="https://fintel.io/u/dev" target="_blank" rel="noopener">fintel.io/u/dev</a>
        </li>
      </ul>
    </Panel>

    <Panel
      v-if="status.data.value && !configured"
      label="Setup — FINTEL_API_KEY"
      index="00"
      meta="required once"
      class="setup"
    >
      <ol class="setup-steps">
        <li>
          Open
          <a :href="status.data.value.key_setup_url" target="_blank" rel="noopener">
            fintel.io/u/dev
          </a>
          → <strong>Generate Key</strong>
        </li>
        <li>
          Add to <code>edge/.env</code>:
          <pre class="code">FINTEL_API_KEY=paste_your_key_here</pre>
        </li>
        <li>
          That string is the <strong>only value</strong> you put in Swagger’s Authorize box as
          <code>X-API-KEY</code>. Restart <code>api_server.py</code> after saving.
        </li>
      </ol>
      <p class="hint">{{ status.data.value.hint }}</p>
    </Panel>

    <div class="tabs">
      <button
        type="button"
        class="tab"
        :class="{ on: tab === 'stream' }"
        @click="setTab('stream')"
      >
        Market stream
      </button>
      <button
        type="button"
        class="tab"
        :class="{ on: tab === 'symbol' }"
        @click="setTab('symbol')"
      >
        Symbol intel
      </button>
      <form class="sym-form" @submit.prevent="applySymbol">
        <input
          v-model="draft"
          class="sym-input"
          maxlength="12"
          placeholder="SYMBOL"
          aria-label="Symbol"
        />
        <button class="btn" type="submit">Load</button>
      </form>
    </div>

    <!-- ── market stream ─────────────────────────────────────────────── -->
    <section v-if="tab === 'stream'" class="grid">
      <LoadingState v-if="stream.loading.value && !stream.data.value" label="Loading Fintel boards…" />
      <p v-else-if="stream.error.value" class="err">{{ stream.error.value }}</p>
      <template v-else>
        <Panel
          label="Short squeeze board"
          index="01"
          :meta="streamAge ? `asof ${streamAge.slice(11, 19)}Z` : ''"
          live
        >
          <table class="tbl">
            <thead>
              <tr>
                <th>Sym</th>
                <th>Name</th>
                <th>Metric</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in squeezeRows.slice(0, 25)" :key="'sq' + i">
                <td>
                  <button type="button" class="link" @click="openSym(rowSym(r))">
                    {{ rowSym(r) }}
                  </button>
                </td>
                <td class="muted">{{ rowName(r) || DASH }}</td>
                <td class="fig">
                  {{
                    rowMetric(r, [
                      'score',
                      'short_squeeze_score',
                      'value',
                      'metric_value',
                      'short_interest_percent_of_float',
                    ])
                  }}
                </td>
              </tr>
              <tr v-if="!squeezeRows.length">
                <td colspan="3" class="muted">
                  {{ friendlySliceError(streamErrors.short_squeeze) || 'No rows (key, plan, or empty board)' }}
                </td>
              </tr>
            </tbody>
          </table>
        </Panel>

        <Panel label="Short interest leaders" index="02">
          <table class="tbl">
            <thead>
              <tr>
                <th>Sym</th>
                <th>Name</th>
                <th>SI / value</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in shortRows.slice(0, 25)" :key="'si' + i">
                <td>
                  <button type="button" class="link" @click="openSym(rowSym(r))">
                    {{ rowSym(r) }}
                  </button>
                </td>
                <td class="muted">{{ rowName(r) || DASH }}</td>
                <td class="fig">
                  {{
                    rowMetric(r, [
                      'short_interest_percent_of_float',
                      'short_pct_float',
                      'value',
                      'metric_value',
                      'score',
                    ])
                  }}
                </td>
              </tr>
              <tr v-if="!shortRows.length">
                <td colspan="3" class="muted">
                  {{ friendlySliceError(streamErrors.short_interest) }}
                </td>
              </tr>
            </tbody>
          </table>
        </Panel>

        <Panel label="Gainers" index="03">
          <table class="tbl">
            <thead>
              <tr>
                <th>Sym</th>
                <th>Chg / val</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in gainerRows.slice(0, 15)" :key="'g' + i">
                <td>
                  <button type="button" class="link" @click="openSym(rowSym(r))">
                    {{ rowSym(r) }}
                  </button>
                </td>
                <td class="fig pos">
                  {{ rowMetric(r, ['change_percent', 'pct_change', 'value', 'metric_value']) }}
                </td>
              </tr>
              <tr v-if="!gainerRows.length">
                <td colspan="2" class="muted">{{ streamErrors.gainers || 'No rows' }}</td>
              </tr>
            </tbody>
          </table>
        </Panel>

        <Panel label="Losers" index="04">
          <table class="tbl">
            <thead>
              <tr>
                <th>Sym</th>
                <th>Chg / val</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in loserRows.slice(0, 15)" :key="'l' + i">
                <td>
                  <button type="button" class="link" @click="openSym(rowSym(r))">
                    {{ rowSym(r) }}
                  </button>
                </td>
                <td class="fig neg">
                  {{ rowMetric(r, ['change_percent', 'pct_change', 'value', 'metric_value']) }}
                </td>
              </tr>
              <tr v-if="!loserRows.length">
                <td colspan="2" class="muted">{{ streamErrors.losers || 'No rows' }}</td>
              </tr>
            </tbody>
          </table>
        </Panel>

        <Panel label="Volume leaders" index="05">
          <table class="tbl">
            <thead>
              <tr>
                <th>Sym</th>
                <th>Volume</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in volumeRows.slice(0, 15)" :key="'v' + i">
                <td>
                  <button type="button" class="link" @click="openSym(rowSym(r))">
                    {{ rowSym(r) }}
                  </button>
                </td>
                <td class="fig">
                  {{
                    rowMetric(r, [
                      'trading_volume_shares',
                      'volume',
                      'value',
                      'metric_value',
                    ])
                  }}
                </td>
              </tr>
              <tr v-if="!volumeRows.length">
                <td colspan="2" class="muted">{{ streamErrors.volume || 'No rows' }}</td>
              </tr>
            </tbody>
          </table>
        </Panel>

        <Panel label="Earnings calendar (slice)" index="06" meta="near-term">
          <table class="tbl">
            <thead>
              <tr>
                <th>Sym</th>
                <th>Date / detail</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in earnings" :key="'e' + i">
                <td>
                  <button type="button" class="link" @click="openSym(rowSym(r))">
                    {{ rowSym(r) }}
                  </button>
                </td>
                <td class="muted">
                  {{
                    rowMetric(r, [
                      'report_date',
                      'earnings_date',
                      'date',
                      'period',
                      'metric_value',
                    ])
                  }}
                </td>
              </tr>
              <tr v-if="!earnings.length">
                <td colspan="2" class="muted">
                  {{ streamErrors.earnings_calendar || 'No calendar rows' }}
                </td>
              </tr>
            </tbody>
          </table>
        </Panel>
      </template>
      <p v-if="stream.data.value?.caveat" class="caveat">{{ stream.data.value.caveat }}</p>
    </section>

    <!-- ── symbol intel ──────────────────────────────────────────────── -->
    <section v-else class="grid symbol-grid">
      <LoadingState v-if="intel.loading.value && !intel.data.value" label="Loading symbol intel…" />
      <p v-else-if="intel.error.value" class="err">{{ intel.error.value }}</p>
      <template v-else-if="intel.data.value">
        <Panel
          :label="`${symbol} · analysis`"
          index="01"
          :meta="intelAge ? `asof ${intelAge.slice(11, 19)}Z` : ''"
          live
        >
          <div class="readout-row">
            <Readout label="Attention" :value="attention != null ? num(attention, 1) : DASH" />
            <Readout
              label="SI % float"
              :value="
                metrics.short_pct_float != null ? num(Number(metrics.short_pct_float), 2) : DASH
              "
            />
            <Readout
              label="Days cover"
              :value="
                metrics.days_to_cover != null ? num(Number(metrics.days_to_cover), 2) : DASH
              "
            />
            <Readout
              label="Borrow fee %"
              :value="
                metrics.borrow_fee_pct != null ? num(Number(metrics.borrow_fee_pct), 2) : DASH
              "
            />
            <Readout
              label="Last"
              :value="metrics.last_price != null ? num(Number(metrics.last_price), 2) : DASH"
            />
            <Readout
              label="Unu. opts"
              :value="
                metrics.unusual_options_prints != null
                  ? String(metrics.unusual_options_prints)
                  : DASH
              "
            />
          </div>
          <p class="headline">{{ analysis?.headline || '—' }}</p>
          <ul class="notes">
            <li v-for="(n, i) in notes" :key="i">{{ n }}</li>
          </ul>
        </Panel>

        <Panel label="Institutional owners" index="02" :meta="`${owners.length} rows`">
          <table class="tbl">
            <thead>
              <tr>
                <th>Holder</th>
                <th>Shares / val</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in owners" :key="'o' + i">
                <td class="muted">
                  {{
                    r.owner_name ||
                    r.holder_name ||
                    r.name ||
                    r.institution ||
                    r.filer_name ||
                    DASH
                  }}
                </td>
                <td class="fig">
                  {{
                    rowMetric(r, [
                      'shares',
                      'share_count',
                      'value_usd',
                      'market_value',
                      'ownership_percent',
                    ])
                  }}
                </td>
              </tr>
              <tr v-if="!owners.length">
                <td colspan="2" class="muted">
                  {{
                    depthIsCore
                      ? 'Not loaded in core depth (saves quota). Owners need depth=full when quota allows.'
                      : friendlySliceError(blockErrors.owners)
                  }}
                </td>
              </tr>
            </tbody>
          </table>
        </Panel>

        <Panel label="Insider transactions" index="03" :meta="`${insiders.length} rows`">
          <table class="tbl">
            <thead>
              <tr>
                <th>Who</th>
                <th>Type</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in insiders" :key="'i' + i">
                <td class="muted">
                  {{ r.insider_name || r.name || r.reporting_name || DASH }}
                </td>
                <td>
                  {{ r.transaction_type || r.type || r.transactionType || DASH }}
                </td>
                <td class="fig">
                  {{
                    rowMetric(r, [
                      'shares',
                      'share_count',
                      'transaction_date',
                      'date',
                      'price',
                    ])
                  }}
                </td>
              </tr>
              <tr v-if="!insiders.length">
                <td colspan="3" class="muted">
                  {{
                    depthIsCore
                      ? 'Not loaded in core depth (saves quota). Insiders need depth=full when quota allows.'
                      : friendlySliceError(blockErrors.insiders)
                  }}
                </td>
              </tr>
            </tbody>
          </table>
        </Panel>

        <Panel label="Unusual options flow" index="04" :meta="`${unusual.length} prints`">
          <table class="tbl">
            <thead>
              <tr>
                <th>Right / strike</th>
                <th>Premium / size</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in unusual" :key="'u' + i">
                <td class="muted">
                  {{
                    [
                      r.option_right || r.right || r.call_put,
                      r.strike || r.strike_price,
                      r.expiry || r.expiration,
                    ]
                      .filter(Boolean)
                      .join(' · ') || DASH
                  }}
                </td>
                <td class="fig">
                  {{
                    rowMetric(r, [
                      'premium',
                      'premium_usd',
                      'size',
                      'volume',
                      'notional',
                    ])
                  }}
                </td>
              </tr>
              <tr v-if="!unusual.length">
                <td colspan="2" class="muted">
                  {{
                    depthIsCore
                      ? 'Not loaded in core depth (saves quota). Options flow is optional / full depth.'
                      : friendlySliceError(blockErrors.options_flow_unusual)
                  }}
                </td>
              </tr>
            </tbody>
          </table>
        </Panel>

        <Panel
          v-if="Object.keys(blockErrors).length"
          label="Partial slice errors"
          index="05"
          meta="non-fatal"
        >
          <ul class="notes">
            <li v-for="(err, key) in blockErrors" :key="key">
              <code>{{ key }}</code>: {{ err }}
            </li>
          </ul>
        </Panel>
      </template>
      <p v-if="intel.data.value?.caveat" class="caveat">{{ intel.data.value.caveat }}</p>
    </section>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s3);
  min-width: 0;
}
.mast {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  flex-wrap: wrap;
}
.mast-left {
  display: flex;
  align-items: center;
  gap: var(--s2);
}
.mast-right {
  display: flex;
  align-items: center;
  gap: var(--s2);
}
.idx {
  opacity: 0.55;
  font-size: 12px;
}
.title {
  margin: 0;
  letter-spacing: 0.08em;
  font-size: 14px;
}
.pill {
  font-size: 10px;
  letter-spacing: 0.06em;
  padding: 4px 8px;
  border: var(--hair) solid var(--rule);
}
.pill.ok {
  color: var(--long);
  border-color: color-mix(in srgb, var(--long) 40%, var(--rule));
}
.pill.bad {
  color: var(--short);
  border-color: color-mix(in srgb, var(--short) 40%, var(--rule));
}
.quota {
  border-color: color-mix(in srgb, var(--short) 45%, var(--rule));
}
.quota-body {
  margin: 0 0 var(--s2);
  font-size: 13px;
  line-height: 1.45;
  color: var(--short);
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
.btn:hover {
  border-color: var(--phosphor);
}
.tabs {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}
.tab {
  background: transparent;
  border: var(--hair) solid var(--rule);
  color: inherit;
  padding: 6px 12px;
  font: inherit;
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  cursor: pointer;
  opacity: 0.7;
}
.tab.on {
  opacity: 1;
  border-color: var(--phosphor);
  color: var(--phosphor);
}
.sym-form {
  display: flex;
  gap: var(--s1);
  margin-left: auto;
}
.sym-input {
  width: 7rem;
  background: transparent;
  border: var(--hair) solid var(--rule);
  color: inherit;
  padding: 6px 8px;
  font: inherit;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--s3);
}
.symbol-grid {
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}
.tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.tbl th {
  text-align: left;
  font-weight: 500;
  opacity: 0.55;
  padding: 4px 6px;
  border-bottom: var(--hair) solid var(--rule);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-size: 10px;
}
.tbl td {
  padding: 5px 6px;
  border-bottom: var(--hair) solid color-mix(in srgb, var(--rule) 50%, transparent);
  vertical-align: top;
}
.muted {
  opacity: 0.7;
}
.fig {
  font-variant-numeric: tabular-nums;
}
.pos {
  color: var(--long);
}
.neg {
  color: var(--short);
}
.link {
  background: none;
  border: none;
  color: var(--phosphor);
  font: inherit;
  cursor: pointer;
  padding: 0;
  letter-spacing: 0.04em;
}
.link:hover {
  text-decoration: underline;
}
.readout-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
  gap: var(--s2);
  margin-bottom: var(--s2);
}
.headline {
  margin: 0 0 var(--s2);
  font-size: 13px;
  letter-spacing: 0.02em;
}
.notes {
  margin: 0;
  padding-left: 1.1rem;
  font-size: 12px;
  opacity: 0.85;
  line-height: 1.45;
}
.caveat,
.hint {
  grid-column: 1 / -1;
  font-size: 11px;
  opacity: 0.65;
  margin: 0;
}
.err {
  color: var(--short);
  font-size: 13px;
}
.setup-steps {
  margin: 0;
  padding-left: 1.2rem;
  font-size: 13px;
  line-height: 1.55;
}
.code {
  margin: 8px 0;
  padding: 8px 10px;
  border: var(--hair) solid var(--rule);
  font-size: 12px;
  overflow-x: auto;
}
a {
  color: var(--phosphor);
}
</style>
