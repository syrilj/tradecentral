<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  api,
  MACRO_TAPE_SYMBOLS,
  MACRO_TAPE_SLEEVES,
  type CotMarket,
  type MacroCotRow,
  type MacroVolReadout,
  type QuoteMark,
  type SectorFlowPayload,
  type StatusPayload,
} from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import { age, compact, num, shortDate, signedPct, tone } from '@/format'
import { cotLeanFromBias, cotLeanFromSpecNetZ, cotLeanTone } from '@/cotLean'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import HelpTip from '@/components/HelpTip.vue'
import LoadingState from '@/components/LoadingState.vue'

/**
 * MACRO — the cross-asset board behind the equity tape.
 *
 * Four lenses, one page:
 *   01 Cross-asset marks — index / rates / credit / real-assets / FX proxies.
 *   02 Vol complex — VIX level, term slope, skew, and the risk composite.
 *   03 CFTC COT — weekly spec positioning in the futures books.
 *   04 Equity rotation — which sleeve the money sits in this week.
 *
 * Every panel renders missing data as an explicit state — a dead feed reads
 * as "unmeasured", never as a flat zero. Decision support only: nothing here
 * places an order or authorizes one.
 */

const router = useRouter()
const status = inject<Resource<StatusPayload>>('status')!
type SectorFlowResource = Resource<SectorFlowPayload> & {
  refresh: (opts?: { force?: boolean; clear?: boolean }) => Promise<void>
}
const sectorFlowRes = inject<SectorFlowResource>('sectorFlow')

const TAPE_POLL_MS = 60_000
const COT_POLL_MS = 900_000

/* ---- resources ---------------------------------------------------------- */

const quotesRes = useResource(() => api.quotes(MACRO_TAPE_SYMBOLS), {
  intervalMs: TAPE_POLL_MS,
})

const cotForceNext = ref(false)
const cotRes = useResource(
  () => {
    const force = cotForceNext.value
    cotForceNext.value = false
    return api.cot({ force })
  },
  { intervalMs: COT_POLL_MS },
)

/** Vol complex rides the sentiment payload (same artifact server-side). */
const sentimentRes = useResource(() => api.sentiment(), { intervalMs: 300_000 })

onMounted(() => {
  // The shell keeps sector flow warm, but force one refresh so this tab opens
  // onto the current session rather than whatever the shell cached last.
  void sectorFlowRes?.refresh({ force: true })
})

async function refreshAll(): Promise<void> {
  cotForceNext.value = true
  await Promise.all([
    quotesRes.refresh(),
    cotRes.refresh(),
    sentimentRes.refresh(),
    sectorFlowRes ? sectorFlowRes.refresh({ force: true }) : Promise.resolve(),
  ])
}

const isRefreshing = computed(
  () =>
    quotesRes.loading.value ||
    cotRes.loading.value ||
    sentimentRes.loading.value ||
    Boolean(sectorFlowRes?.loading.value),
)

function openSymbol(sym: string): void {
  void router.push({ name: 'market', query: { symbol: sym } })
}

/* ---- 01 cross-asset tape -------------------------------------------------- */

interface MacroMark extends QuoteMark {
  name: string
  sleeve: string
}

const quoteBySym = computed(() => {
  const map = new Map<string, QuoteMark>()
  for (const row of quotesRes.data.value?.rows ?? []) map.set(row.symbol, row)
  return map
})

const tapeGroups = computed<{ sleeve: string; rows: MacroMark[] }[]>(() => {
  const src = quoteBySym.value
  return MACRO_TAPE_SLEEVES.map(({ sleeve, symbols }) => ({
    sleeve,
    rows: symbols.map((s) => ({
      name: s.name,
      sleeve,
      symbol: s.sym,
      last: src.get(s.sym)?.last ?? null,
      prev_close: src.get(s.sym)?.prev_close ?? null,
      chg_1d_pct: src.get(s.sym)?.chg_1d_pct ?? null,
      asof: src.get(s.sym)?.asof ?? null,
      source: src.get(s.sym)?.source ?? 'unavailable',
      quality: src.get(s.sym)?.quality ?? 'stale',
    })),
  }))
})

const tapeTotal = computed(() => tapeGroups.value.reduce((n, g) => n + g.rows.length, 0))
const tapeMeasured = computed(() =>
  tapeGroups.value.reduce((n, g) => n + g.rows.filter((r) => r.last != null).length, 0),
)

type MarkQuality = 'current' | 'stale' | 'missing'

function markQuality(r: MacroMark): MarkQuality {
  if (r.last == null) return 'missing'
  if (r.quality === 'live') return 'current'
  if (!r.asof) return 'stale'
  const stamp = Date.parse(`${String(r.asof).slice(0, 10)}T00:00:00Z`)
  if (!Number.isFinite(stamp)) return 'stale'
  // Local EOD parquet is fine within a few sessions; older than that is stale.
  return Date.now() - stamp <= 4 * 86_400_000 ? 'current' : 'stale'
}

/* ---- 02 vol complex --------------------------------------------------------- */

interface VolRow {
  key: string
  label: string
  display: string
  sub: string
  toneVal: 'pos' | 'neg' | 'flat' | 'default'
}

const volBlock = computed(() => {
  const raw = sentimentRes.data.value?.vol
  if (!raw || typeof raw !== 'object') return null
  return raw as {
    quality?: string
    asof?: string | null
    lag_note?: string
    composite_risk_pctile?: number | null
    composite_label?: string
    readouts?: MacroVolReadout[]
  }
})

function volDisplay(key: string, v: number | null): string {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  if (key.endsWith('ret_5d')) return signedPct(v * 100, 2)
  if (key === 'term_slope' || key === 'short_stress') return num(v, 3)
  return num(v, 2)
}

/** Tone mirrors Pulse's VOL_META semantics so both surfaces agree. */
function volToneOf(key: string, v: number | null): 'pos' | 'neg' | 'flat' {
  if (v == null || !Number.isFinite(Number(v))) return 'flat'
  if (key === 'VIX') return v >= 25 ? 'neg' : v <= 15 ? 'pos' : 'flat'
  if (key === 'term_slope') return v > 1 ? 'neg' : 'pos'
  if (key === 'short_stress') return v >= 1 ? 'neg' : 'pos'
  if (key === 'SKEW_or_tail') return v >= 140 ? 'neg' : 'flat'
  if (key.endsWith('ret_5d')) return tone(v)
  return 'flat'
}

const VOL_LABELS: Record<string, string> = {
  VIX: 'VIX',
  term_slope: 'Term slope',
  SKEW_or_tail: 'SKEW · tail',
  vix_vrp: 'Vol risk prem',
  short_stress: 'Short stress',
  spy_ret_5d: 'SPY 5D',
  qqq_ret_5d: 'QQQ 5D',
}

const volRows = computed<VolRow[]>(() => {
  const rows = volBlock.value?.readouts ?? []
  return rows.map((r) => {
    const key = String(r.key)
    const v = r.value == null ? null : Number(r.value)
    const pctile = r.pctile_1y == null ? null : Number(r.pctile_1y)
    return {
      key,
      label: VOL_LABELS[key] ?? key.replaceAll('_', ' '),
      display: volDisplay(key, v),
      sub: pctile == null ? '' : `${Math.round(pctile * 100)}pct 1y`,
      toneVal: volToneOf(key, v),
    }
  })
})

const volCompositeLabel = computed(() =>
  String(volBlock.value?.composite_label ?? '—').toUpperCase(),
)
const volCompositePctile = computed(() => {
  const p = volBlock.value?.composite_risk_pctile
  return p == null || !Number.isFinite(Number(p)) ? '—' : `${Math.round(Number(p) * 100)}pct`
})
const volNote = computed(() => String(volBlock.value?.lag_note ?? ''))

/* ---- 03 COT ---------------------------------------------------------------- */

const cotMarketsRaw = computed<CotMarket[]>(() => (cotRes.data.value?.markets ?? []) as CotMarket[])

const cotRows = computed<MacroCotRow[]>(() =>
  cotMarketsRaw.value.map((m) => ({
    id: m.id,
    label: m.label,
    proxy: m.proxy,
    asof: m.asof,
    noncomm_net: m.noncomm_net,
    comm_net: m.comm_net,
    open_interest: m.open_interest,
    noncomm_net_z_1y: m.noncomm_net_z_1y,
    noncomm_net_pctile_1y: m.noncomm_net_pctile_1y,
    bias: m.bias,
    lean: m.lean,
  })),
)

function cotLean(m: MacroCotRow): ReturnType<typeof cotLeanFromSpecNetZ> {
  const fromZ = cotLeanFromSpecNetZ(m.noncomm_net_z_1y)
  return fromZ === 'UNKNOWN' ? cotLeanFromBias(m.bias) : fromZ
}

const cotAsOf = computed(() => cotRes.data.value?.asof ?? null)
const cotStale = computed(() => {
  const q = String(cotRes.data.value?.quality ?? '')
  if (!q) return true
  return q === 'stale' || q === 'missing'
})
const cotErrorText = computed(() => {
  if (cotRes.error.value) return cotRes.error.value
  const errs = cotRes.data.value?.errors ?? []
  if (!cotRows.value.length && errs.length) return errs.join(' · ')
  return null
})
const cotErrList = computed(() => (cotRes.data.value?.errors ?? []).join('; '))
const cotFetchedAgo = computed(() => (cotRes.fetchedAt.value ? age(cotRes.fetchedAt.value) : null))

/* ---- 04 equity rotation ------------------------------------------------------ */

interface SectorRow {
  etf: string
  name: string
  flow_score?: number
  ret_5d?: number
  rs_5d?: number
}

const flow = computed(
  () =>
    (sectorFlowRes?.data.value ?? status.data.value?.sector_flow) as
      | {
          sectors_ranked?: SectorRow[]
          asof_bar?: string | null
          source?: string | null
        }
      | undefined,
)

const sectorRows = computed<SectorRow[]>(() =>
  [...(flow.value?.sectors_ranked ?? [])].sort(
    (a, b) => Number(b.flow_score ?? 0) - Number(a.flow_score ?? 0),
  ),
)

const sectorLoading = computed(
  () => Boolean(sectorFlowRes?.loading.value) || (status.loading.value && !sectorRows.value.length),
)

const rotationMeta = computed(() => {
  const bar = flow.value?.asof_bar ?? null
  const days =
    bar == null
      ? null
      : Math.max(0, Math.floor((Date.now() - Date.parse(`${bar}T00:00:00Z`)) / 86_400_000))
  const stale = days == null || days > 3 ? ' · STALE' : ''
  const src = String(flow.value?.source || 'scan').replace(/_/g, ' ')
  return `BAR ${shortDate(bar)} · ${src}${stale}`
})

const topIn = computed(() => sectorRows.value.find((s) => Number(s.flow_score ?? 0) > 0) ?? null)
const topOut = computed(
  () => [...sectorRows.value].reverse().find((s) => Number(s.flow_score ?? 0) < 0) ?? null,
)

/** Bar length normalised against the widest |flow score| on the board. */
const rotFlowMax = computed(() =>
  Math.max(1e-6, ...sectorRows.value.map((s) => Math.abs(Number(s.flow_score ?? 0)))),
)
function rotBarWidth(score: number | undefined): string {
  const v = Math.abs(Number(score ?? 0)) / rotFlowMax.value
  return `${Math.min(100, Math.max(2, v * 100)).toFixed(1)}%`
}
</script>

<template>
  <div class="macro-view">
    <header class="macro-head ticked rise">
      <div class="head-copy">
        <span class="label eyebrow">CROSS-ASSET CONTEXT</span>
        <h1>Macro Board</h1>
        <p>
          Indexes, rates, credit, real assets and the dollar — plus where speculative futures
          positioning stands. The regime lens behind every equity decision on this desk.
        </p>
      </div>
      <div class="head-actions">
        <span class="label asof wraps">
          {{ tapeMeasured }}/{{ tapeTotal }} MARKED
          <template v-if="quotesRes.fetchedAt.value">
            · TAPE {{ age(quotesRes.fetchedAt.value) }} AGO</template
          >
          <template v-if="cotFetchedAgo"> · COT {{ cotFetchedAgo }}</template>
        </span>
        <button
          type="button"
          class="refresh-btn label"
          :disabled="isRefreshing"
          title="Refresh every macro panel"
          @click="void refreshAll()"
        >
          {{ isRefreshing ? 'REFRESHING…' : 'REFRESH ALL' }}
        </button>
      </div>
    </header>

    <!-- ── 01 cross-asset marks ─────────────────────────────────────────── -->
    <Panel
      label="Cross-asset tape"
      index="01"
      :meta="
        quotesRes.error.value
          ? 'FEED UNAVAILABLE'
          : `as-of ${shortDate(quotesRes.data.value?.asof?.slice(0, 10) ?? null)}`.trim()
      "
      :live="quotesRes.loading.value && !quotesRes.data.value"
      class="w-full"
    >
      <template #action>
        <HelpTip
          label="Cross-asset tape"
          text="One mark per macro sleeve: equity indexes, duration (TLT), credit (HYG/LQD), metals, oil, the dollar and EM. Tickers outside the local parquet universe are pulled live server-side with a short TTL, so a missing row means the provider failed — it is never painted as zero."
          align="right"
        />
      </template>
      <LoadingState
        v-if="quotesRes.loading.value && !quotesRes.data.value"
        label="Pulling cross-asset marks"
        compact
      />
      <p v-else-if="quotesRes.error.value" class="err">{{ quotesRes.error.value }}</p>
      <div v-else-if="tapeMeasured > 0" class="tape-grid">
        <div v-for="group in tapeGroups" :key="group.sleeve" class="sleeve">
          <span class="label sleeve-name">{{ group.sleeve }}</span>
          <div class="mark-list">
            <button
              v-for="r in group.rows"
              :key="r.symbol"
              type="button"
              class="mark"
              :class="`q-${markQuality(r)}`"
              :title="`${r.symbol} · ${r.name} · open Market`"
              @click="openSymbol(r.symbol)"
            >
              <span class="sym fig">{{ r.symbol }}</span>
              <span class="name label wraps">{{ r.name }}</span>
              <span class="last fig">{{ num(r.last, 2) }}</span>
              <span class="chg fig" :class="tone(r.chg_1d_pct)">
                {{ r.chg_1d_pct == null ? '—' : signedPct(r.chg_1d_pct, 2) }}
              </span>
              <span v-if="markQuality(r) !== 'current'" class="q-flag label">
                {{ markQuality(r) === 'missing' ? 'UNMEASURED' : 'STALE' }}
              </span>
            </button>
          </div>
        </div>
      </div>
      <p v-else class="note pad">
        No cross-asset marks available. The quote feed returned nothing for every sleeve.
      </p>
      <p v-if="tapeMeasured > 0" class="note tiny pad-x">
        Click a row to open the ETF on Market · UNMEASURED = provider returned no mark, STALE =
        observed bar older than four sessions.
      </p>
    </Panel>

    <!-- ── 02 vol complex ──────────────────────────────────────────────── -->
    <Panel
      label="Volatility complex"
      index="02"
      :meta="`RISK ${volCompositePctile} · ${volCompositeLabel}`"
    >
      <template #action>
        <HelpTip
          label="Vol complex"
          text="VIX level, term slope (VIX/VIX3M), skew and the vol risk premium from edge/data/vol_complex.csv. The risk read is a descriptive mix of 1-year percentile ranks — context, not a signal."
        />
      </template>
      <LoadingState
        v-if="sentimentRes.loading.value && !sentimentRes.data.value"
        label="Reading vol complex"
        compact
      />
      <p v-else-if="sentimentRes.error.value" class="err">{{ sentimentRes.error.value }}</p>
      <template v-else-if="volRows.length">
        <div class="vol-grid">
          <Readout
            v-for="r in volRows"
            :key="r.key"
            :label="r.label"
            :value="r.display"
            :sub="r.sub"
            :tone="r.toneVal"
            size="sm"
          />
        </div>
        <p v-if="volNote" class="note tiny">{{ volNote }}</p>
      </template>
      <p v-else class="note pad">
        Vol complex unavailable. Run <code>python3 edge/tools/fetch_vol_complex.py</code> to build
        edge/data/vol_complex.csv.
      </p>
    </Panel>

    <!-- ── 03 spec positioning ─────────────────────────────────────────── -->
    <Panel
      label="Spec positioning · CFTC"
      index="03"
      :meta="`WEEK OF ${shortDate(cotAsOf)}${cotStale ? ' · STALE' : ''}`"
    >
      <template #action>
        <HelpTip
          label="Commitment of traders"
          text="Weekly non-commercial (spec) net position z-scored over one year per futures book. LONG/SHORT marks crowded books — crowded trades unwind, so extremes are reversal context, not entries. Published Fridays for Tuesday positions."
          align="right"
        />
      </template>
      <LoadingState
        v-if="cotRes.loading.value && !cotRes.data.value"
        label="Loading COT books"
        compact
      />
      <p v-else-if="cotErrorText" class="err">{{ cotErrorText }}</p>
      <table v-else-if="cotRows.length" class="grid">
        <thead>
          <tr>
            <th>Book</th>
            <th class="num">Spec net</th>
            <th class="num">Z·1y</th>
            <th>Lean</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in cotRows" :key="m.id" :title="m.proxy || m.label">
            <td>
              <span class="fig sym book-sym">{{ m.id }}</span>
              <span class="name label wraps">{{ m.label }}</span>
            </td>
            <td class="fig num">{{ m.noncomm_net == null ? '—' : compact(m.noncomm_net, 1) }}</td>
            <td class="fig num">
              {{ m.noncomm_net_z_1y == null ? '—' : num(m.noncomm_net_z_1y, 2) }}
            </td>
            <td>
              <span class="kpi-badge" :class="cotLeanTone(cotLean(m))">{{ cotLean(m) }}</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="note pad">
        No COT markets loaded{{ cotErrList ? ` — ${cotErrList}` : '.' }}
      </p>
      <p v-if="cotRows.length" class="note tiny pad-x">
        Spec net = non-commercial long − short contracts. Z is against the trailing year of the same
        book.
      </p>
    </Panel>

    <!-- ── 04 equity rotation ──────────────────────────────────────────── -->
    <Panel label="Equity rotation sleeve" index="04" :meta="rotationMeta" class="w-full">
      <template #action>
        <HelpTip
          label="Rotation sleeve"
          text="Sector ETF flow score ranks sleeves by multi-horizon relative strength vs SPY. The leaders and laggards say whether the equity tape is broad risk-on, narrow leadership, or defensive."
          align="right"
        />
        <RouterLink class="filter-btn label" :to="{ name: 'sectors' }">OPEN SECTORS ↗</RouterLink>
      </template>
      <LoadingState
        v-if="sectorLoading && !sectorRows.length"
        label="Scanning sector flow"
        compact
      />
      <template v-else-if="sectorRows.length">
        <div class="rot-leaders">
          <Readout
            label="Top accumulation"
            :value="
              topIn ? `${topIn.etf} ${signedPct(Number(topIn.flow_score ?? 0) * 100, 1)}` : '—'
            "
            :sub="topIn ? topIn.name : 'no accumulation sleeve'"
            tone="pos"
            size="sm"
          />
          <Readout
            label="Top distribution"
            :value="
              topOut ? `${topOut.etf} ${signedPct(Number(topOut.flow_score ?? 0) * 100, 1)}` : '—'
            "
            :sub="topOut ? topOut.name : 'no distribution sleeve'"
            tone="neg"
            size="sm"
          />
        </div>
        <div class="rot-strip" aria-hidden="false">
          <div
            v-for="s in sectorRows"
            :key="s.etf"
            class="rot-row"
            :class="Number(s.flow_score ?? 0) >= 0 ? 'in' : 'out'"
            :title="`${s.name} · click to open ${s.etf} on Market`"
            @click="openSymbol(s.etf)"
          >
            <span class="fig rot-etf">{{ s.etf }}</span>
            <span class="rot-bar">
              <i
                :class="Number(s.flow_score ?? 0) >= 0 ? 'in' : 'out'"
                :style="{ width: rotBarWidth(s.flow_score) }"
              />
            </span>
            <span class="fig rot-score" :class="tone(s.flow_score)">
              {{ s.flow_score == null ? '—' : signedPct(Number(s.flow_score) * 100, 1) }}
            </span>
          </div>
        </div>
      </template>
      <p v-else class="note pad">No sector flow data available yet.</p>
    </Panel>

    <footer class="disclaimer label wraps">
      DECISION SUPPORT ONLY · macro context is descriptive measurement, never an order, a signal, or
      an authorization.
    </footer>
  </div>
</template>

<style scoped>
.macro-view {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s4);
  align-items: start;
  max-width: 1560px;
  margin: 0 auto;
}
.w-full {
  grid-column: 1 / -1;
}

/* ---- header ---------------------------------------------------------------- */
.macro-head {
  grid-column: 1 / -1;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s5);
  padding: var(--s4) var(--s5);
  border: var(--hair) solid var(--rule);
  border-left: 2px solid var(--phosphor-dim);
  border-radius: var(--r-xl);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 48px),
    var(--surface-base);
}

.eyebrow {
  color: var(--phosphor);
}
.head-copy h1 {
  margin: var(--s2) 0 0;
  color: var(--ink);
  font: 700 calc(var(--t-display) + 2px) / 1.12 var(--font-display);
  letter-spacing: -0.02em;
}
.head-copy p {
  max-width: 70ch;
  margin-top: var(--s3);
  color: var(--text-secondary);
  font-size: var(--t-body);
  line-height: 1.55;
}

.head-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: var(--s2);
  padding-bottom: var(--s1);
}
.asof {
  color: var(--ink-dim);
}
.refresh-btn {
  min-height: var(--density-control-h);
  padding: var(--s2) var(--s3);
  color: var(--ink-soft);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: rgba(255, 255, 255, 0.02);
  transition:
    border-color var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}
.refresh-btn:hover:not(:disabled) {
  border-color: var(--phosphor-dim);
  color: var(--phosphor);
}
.refresh-btn:disabled {
  opacity: 0.55;
  cursor: default;
}

/* ---- 01 cross-asset tape ----------------------------------------------------- */
.tape-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: var(--s5);
}
.sleeve {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}
.sleeve-name {
  color: var(--ink-faint);
  letter-spacing: 0.1em;
  border-bottom: var(--hair) solid var(--rule-faint);
  padding-bottom: var(--s1);
}
.mark-list {
  display: flex;
  flex-direction: column;
}
.mark {
  display: grid;
  grid-template-columns: 5ch minmax(0, 1fr) auto minmax(8ch, auto);
  align-items: baseline;
  gap: var(--s3);
  padding: 7px var(--s2);
  border-bottom: var(--hair) solid var(--rule-faint);
  text-align: left;
  transition: background var(--dur-fast) var(--ease-out);
}
.mark:last-child {
  border-bottom: none;
}
.mark:hover {
  background: var(--panel-hi);
}
.mark.q-stale {
  box-shadow: inset 2px 0 0 var(--warn);
}
.mark.q-missing .last,
.mark.q-missing .chg {
  color: var(--ink-faint);
}
.mark .sym {
  font-weight: 700;
  color: var(--phosphor);
}
.mark .name {
  font-size: var(--t-tiny);
  color: var(--ink-dim);
}
.mark .last {
  text-align: right;
  color: var(--ink);
}
.mark .chg {
  text-align: right;
}
.pos {
  color: var(--long);
}
.neg {
  color: var(--short);
}

.q-flag {
  grid-column: 2 / 5;
  justify-self: end;
  color: var(--warn);
  font-size: var(--t-tiny);
}

/* ---- badges ------------------------------------------------------------------- */
.kpi-badge {
  display: inline-block;
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  font-weight: 700;
  padding: 2px 7px;
  border-radius: var(--r-xs);
  letter-spacing: 0.06em;
}
.kpi-badge.pos {
  color: var(--long);
  background: var(--long-wash);
}
.kpi-badge.neg {
  color: var(--short);
  background: var(--short-wash);
}
.kpi-badge.flat {
  color: var(--ink-dim);
  background: var(--panel-hi);
}

.book-sym {
  font-weight: 700;
  color: var(--phosphor);
}
.name {
  font-size: var(--t-tiny);
  color: var(--ink-dim);
}

/* ---- vol grid -------------------------------------------------------------------- */
.vol-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: var(--s3);
}

/* ---- rotation strip ------------------------------------------------------------ */
.rot-leaders {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--s3);
  padding-bottom: var(--s3);
  margin-bottom: var(--s3);
  border-bottom: var(--hair) solid var(--rule-faint);
}
.rot-strip {
  display: flex;
  flex-direction: column;
}
.rot-row {
  display: grid;
  grid-template-columns: 4.5ch minmax(120px, 1.6fr) 7ch;
  align-items: center;
  gap: var(--s3);
  padding: 6px var(--s2);
  cursor: pointer;
  border-bottom: var(--hair) solid var(--rule-faint);
}
.rot-row:hover {
  background: var(--panel-hi);
}
.rot-row.in {
  box-shadow: inset 2px 0 0 var(--long);
}
.rot-row.out {
  box-shadow: inset 2px 0 0 var(--short);
}
.rot-etf {
  font-weight: 700;
  color: var(--phosphor);
}
.rot-bar {
  position: relative;
  height: 7px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.rot-bar i {
  display: block;
  height: 100%;
  max-width: 100%;
}
.rot-bar i.in {
  background: var(--long);
}
.rot-bar i.out {
  background: var(--short);
}
.rot-score {
  text-align: right;
  font-size: var(--t-small);
}

.filter-btn {
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  padding: 3px 8px;
  transition:
    color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}
.filter-btn:hover {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

/* ---- shared bits -------------------------------------------------------------- */
.note {
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.5;
}
.note.tiny {
  font-size: var(--t-micro);
  margin-top: var(--s3);
}
.note.pad {
  padding: var(--s5) var(--s4);
}
.note.pad-x {
  padding: var(--s3) var(--s4) 0;
}
.err {
  color: var(--short);
  font-size: var(--t-small);
  padding: var(--s2) 0;
}
.note code {
  font-family: var(--font-data);
  color: var(--phosphor-dim);
}

.disclaimer {
  grid-column: 1 / -1;
  color: var(--ink-faint);
  letter-spacing: 0.08em;
  padding-top: var(--s2);
  border-top: var(--hair) solid var(--rule-faint);
}

@media (max-width: 1100px) {
  .macro-view {
    grid-template-columns: 1fr;
  }
  .macro-head {
    flex-direction: column;
    align-items: flex-start;
  }
  .head-actions {
    align-items: flex-start;
  }
}
</style>
