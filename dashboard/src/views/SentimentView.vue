<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type AnomaliesPayload,
  type CotMarket,
  type SentimentPayload,
  type SecFilingsPayload,
} from '@/api'
import { useResource } from '@/composables/useResource'
import { num, signed, signedPct, compact, tone, shortDate, DASH } from '@/format'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import HelpTip from '@/components/HelpTip.vue'
import LoadingState from '@/components/LoadingState.vue'

/**
 * Pulse desk — market structure sentiment + statistical anomalies.
 * Empty = source failed or no threshold clear, never "neutral market".
 */
const route = useRoute()
const router = useRouter()

const tab = ref<'structure' | 'outliers'>(
  route.query.tab === 'outliers' || route.name === 'anomalies' ? 'outliers' : 'structure',
)
const symbol = ref(((route.query.symbol as string) || '').toUpperCase())
const draft = ref(symbol.value)

const sentiment = useResource<SentimentPayload>(
  () => api.sentiment(symbol.value || undefined),
  { intervalMs: 300_000 },
)
const anomalies = useResource<AnomaliesPayload>(
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
      void sentiment.refresh()
      void anomalies.refresh()
    }
  },
)

watch(
  () => route.query.tab,
  (t) => {
    if (t === 'outliers' || t === 'structure') tab.value = t
  },
)

function setTab(next: 'structure' | 'outliers'): void {
  tab.value = next
  void router.replace({
    name: 'sentiment',
    query: {
      ...(symbol.value ? { symbol: symbol.value } : {}),
      ...(next === 'outliers' ? { tab: 'outliers' } : {}),
    },
  })
}

function applySymbol(): void {
  const s = draft.value.trim().toUpperCase().replace(/[^A-Z0-9.-]/g, '').slice(0, 10)
  draft.value = s
  symbol.value = s
  void router.replace({
    query: {
      ...(s ? { symbol: s } : {}),
      ...(tab.value === 'outliers' ? { tab: 'outliers' } : {}),
    },
  })
  void sentiment.refresh()
  void anomalies.refresh()
}

const d = computed(() => sentiment.data.value)
const composite = computed(() => d.value?.composite)
const vol = computed(() => d.value?.vol as Record<string, any> | undefined)
const cotMarkets = computed(() => (d.value?.cot?.markets ?? []) as CotMarket[])
const finraTop = computed(() => (d.value?.finra_short?.top_short_pressure as any[]) ?? [])
const finraLow = computed(() => (d.value?.finra_short?.low_short_pressure as any[]) ?? [])
const filings = computed(() => d.value?.symbol_filings as SecFilingsPayload | undefined)

const a = computed(() => anomalies.data.value)
const unified = computed(() => a.value?.unified ?? [])
const pxRows = computed(() => (a.value?.price_volume?.rows ?? []) as any[])
const shortRows = computed(() => ((a.value?.finra_short_extremes as any)?.rows ?? []) as any[])
const secRows = computed(() => ((a.value?.sec_activity as any)?.rows ?? []) as any[])
const focus = computed(() => a.value?.symbol_focus as any)

function qTone(q: string | undefined): 'pos' | 'neg' | 'flat' {
  if (!q) return 'flat'
  if (q === 'ok') return 'pos'
  if (q === 'stale' || q === 'degraded') return 'flat'
  return 'neg'
}

function biasTone(b: string | undefined): 'pos' | 'neg' | 'flat' {
  if (!b) return 'flat'
  if (b.includes('LONG')) return 'pos'
  if (b.includes('SHORT')) return 'neg'
  return 'flat'
}

function openMarket(sym: string): void {
  void router.push({ name: 'market', query: { symbol: sym } })
}

function kindClass(kind: string): string {
  if (kind.includes('SHORT')) return 'neg'
  if (kind.includes('SEC')) return 'flat'
  if (kind.includes('OPTIONS')) return 'neg'
  return 'pos'
}

const structureLoading = computed(() => sentiment.loading.value && !sentiment.data.value)
const outliersLoading = computed(() => anomalies.loading.value && !anomalies.data.value)
const isRefreshing = computed(() => sentiment.loading.value || anomalies.loading.value)

async function refreshAll(): Promise<void> {
  await Promise.all([sentiment.refresh(), anomalies.refresh()])
}

/** Human labels + lean for vol complex keys (raw CSV names are unreadable on a desk). */
const VOL_META: Record<string, { label: string; help: string; lean: (v: number | null) => string; toneOf: (v: number | null) => 'pos' | 'neg' | 'flat' }> = {
  VIX: {
    label: 'VIX',
    help: 'Fear gauge. Higher = more expected equity volatility (risk-off lean).',
    lean: (v) => (v == null ? '' : v >= 25 ? 'elevated fear' : v <= 15 ? 'calm' : 'normal'),
    toneOf: (v) => (v == null ? 'flat' : v >= 25 ? 'neg' : v <= 15 ? 'pos' : 'flat'),
  },
  term_slope: {
    label: 'Term slope',
    help: 'Near-term vs mid-term vol (VIX/VIX3M). Above 1 = near-term stress (risk-off). Below 1 = calmer front end.',
    lean: (v) => (v == null ? '' : v > 1 ? 'near-term stress' : 'contango / calmer'),
    toneOf: (v) => (v == null ? 'flat' : v > 1 ? 'neg' : 'pos'),
  },
  SKEW_or_tail: {
    label: 'Tail / SKEW',
    help: 'Crash-protection demand. Higher = more money buying downside insurance (cautious).',
    lean: (v) => (v == null ? '' : v >= 140 ? 'heavy tail hedge' : 'moderate'),
    toneOf: (v) => (v == null ? 'flat' : v >= 140 ? 'neg' : 'flat'),
  },
  vix_vrp: {
    label: 'Vol risk premium',
    help: 'How rich options insurance is vs recent realized moves. High = expensive protection.',
    lean: (v) => (v == null ? '' : v >= 10 ? 'insurance rich' : 'cheap-ish'),
    toneOf: () => 'flat',
  },
  short_stress: {
    label: 'Short stress',
    help: 'Vol-complex short-side stress proxy. Higher = more short-side pressure in the complex.',
    lean: (v) => (v == null ? '' : v >= 1 ? 'pressured' : 'eased'),
    toneOf: (v) => (v == null ? 'flat' : v >= 1 ? 'neg' : 'pos'),
  },
  SPY_ret_5d: {
    label: 'SPY 5D',
    help: 'S&P 500 ETF 5-day return. Green up / red down.',
    lean: (v) => (v == null ? '' : v >= 0 ? 'up week' : 'down week'),
    toneOf: (v) => (v == null ? 'flat' : v >= 0 ? 'pos' : 'neg'),
  },
  QQQ_ret_5d: {
    label: 'QQQ 5D',
    help: 'Nasdaq-100 ETF 5-day return.',
    lean: (v) => (v == null ? '' : v >= 0 ? 'up week' : 'down week'),
    toneOf: (v) => (v == null ? 'flat' : v >= 0 ? 'pos' : 'neg'),
  },
}

const volRows = computed(() => {
  const rows = (vol.value?.readouts ?? []) as { key: string; value: number | null }[]
  return rows.map((r) => {
    const meta = VOL_META[r.key]
    const isRet = r.key.includes('ret')
    return {
      key: r.key,
      label: meta?.label ?? r.key.replaceAll('_', ' '),
      help: meta?.help ?? '',
      value: isRet ? signedPct(Number(r.value) * 100, 2) : num(r.value, r.key === 'term_slope' ? 3 : 2),
      lean: meta?.lean(r.value == null ? null : Number(r.value)) ?? '',
      tone: meta?.toneOf(r.value == null ? null : Number(r.value)) ?? (isRet ? tone(r.value) : 'flat'),
    }
  })
})

function finraLean(z: number | null | undefined, side: 'high' | 'low'): string {
  if (z == null || !Number.isFinite(z)) return ''
  if (side === 'high') return 'more short-side volume than usual · bearish pressure lean'
  return 'less short-side volume than usual · short covering / long lean'
}

const COT_HELP =
  'Weekly CFTC futures books. Spec net = non-commercial long minus short. LONG bias = specs crowded long; SHORT = crowded short. Context only — not a stock entry.'

const SEC_HELP =
  'Type a ticker and Load. Form 4 = insider trade reports. 8-K = material company events. 13D/G = large ownership stakes. Not 13F fund holdings (those lag a quarter).'

function formLabel(key: string): string {
  const k = key.toLowerCase()
  if (k.includes('form4') || k === '4') return 'Form 4 (insider)'
  if (k.includes('8k') || k.includes('eightk') || k === '8-k') return '8-K (events)'
  if (k.includes('13') || k.includes('sc13')) return '13D/G (holders)'
  return key.replaceAll('_', ' ')
}

function formMeaning(form: string | undefined): string {
  if (!form) return ''
  const f = form.toUpperCase()
  if (f.includes('4')) return 'Insider trade report'
  if (f.includes('8-K') || f === '8K') return 'Material company event'
  if (f.includes('13D') || f.includes('13G')) return 'Large ownership stake'
  if (f.includes('10-K') || f.includes('10-Q')) return 'Periodic financial report'
  return ''
}
</script>

<template>
  <div class="pulse-view">
    <div class="page-head">
      <div class="head-left">
        <div class="tabs" role="tablist">
          <button
            type="button"
            role="tab"
            class="tab label"
            :class="{ on: tab === 'structure' }"
            :aria-selected="tab === 'structure'"
            @click="setTab('structure')"
          >
            Structure
          </button>
          <button
            type="button"
            role="tab"
            class="tab label"
            :class="{ on: tab === 'outliers' }"
            :aria-selected="tab === 'outliers'"
            @click="setTab('outliers')"
          >
            Outliers
            <span v-if="unified.length" class="tab-count fig">{{ unified.length }}</span>
          </button>
        </div>

        <button
          type="button"
          class="pulse-refresh-btn label"
          :disabled="isRefreshing"
          title="Update all pulse info and anomaly scans"
          @click="refreshAll"
        >
          <span class="refresh-icon" :class="{ spinning: isRefreshing }">↻</span>
          {{ isRefreshing ? 'UPDATING...' : 'UPDATE ALL INFO' }}
        </button>
      </div>

      <form class="sym-row" @submit.prevent="applySymbol">
        <label class="label" for="pulse-sym">
          Ticker
          <HelpTip label="Ticker focus" :text="SEC_HELP" />
        </label>
        <input
          id="pulse-sym"
          v-model="draft"
          class="sym-input"
          placeholder="e.g. AAPL"
          maxlength="10"
          autocomplete="off"
          spellcheck="false"
          title="Loads SEC filings for one ticker on the Structure tab"
        />
        <button type="submit" class="btn">Load filings</button>
      </form>
    </div>

    <!-- ══════════════ STRUCTURE TAB ══════════════ -->
    <template v-if="tab === 'structure'">
      <LoadingState v-if="structureLoading" class="w-full" label="Loading structure feeds…" />

      <template v-else>
        <p v-if="sentiment.error.value" class="err w-full">{{ sentiment.error.value }}</p>

        <div class="summary-deck">
          <div class="kpi-card armed">
            <span class="label kpi-label">
              Desk composite
              <HelpTip label="Composite" text="Descriptive mix of structure sources only — not a trade call or probability." />
            </span>
            <div class="kpi-val-row">
              <span class="kpi-val">{{ composite?.label ?? DASH }}</span>
              <span class="kpi-badge" :class="qTone(composite?.quality)">
                {{ composite?.quality?.toUpperCase() ?? 'NO DATA' }}
              </span>
            </div>
            <span class="kpi-sub">Score {{ num(composite?.score, 3) }}</span>
          </div>

          <div class="kpi-card">
            <span class="label kpi-label">
              Vol regime
              <HelpTip
                label="Vol regime"
                text="RISK_OFF / CAUTIOUS = elevated fear mix. RISK_ON = calm vol complex. Descriptive only."
              />
            </span>
            <div class="kpi-val-row">
              <span class="kpi-val">{{ vol?.composite_label ?? DASH }}</span>
              <span class="kpi-badge" :class="qTone(vol?.quality)">{{ vol?.quality?.toUpperCase() ?? 'NO DATA' }}</span>
            </div>
            <span class="kpi-sub">
              Risk pctile {{ num(vol?.composite_risk_pctile, 2) }} · {{ shortDate(vol?.asof) }}
            </span>
          </div>

          <div class="kpi-card">
            <span class="label kpi-label">
              CFTC COT
              <HelpTip label="COT" :text="COT_HELP" />
            </span>
            <div class="kpi-val-row">
              <span class="kpi-val fig">{{ cotMarkets.length }} markets</span>
              <span class="kpi-badge" :class="qTone(d?.cot?.quality)">{{ d?.cot?.quality?.toUpperCase() ?? 'NO DATA' }}</span>
            </div>
            <span class="kpi-sub">Weekly futures · {{ shortDate(d?.cot?.asof) }}</span>
          </div>

          <div class="kpi-card">
            <span class="label kpi-label">
              FINRA short vol
              <HelpTip
                label="FINRA short volume"
                text="Short volume ÷ total volume on FINRA venues — not short interest (shares still short). High ratio + high z = unusually heavy short-side trading (bearish pressure lean). Low z = quieter shorting."
              />
            </span>
            <div class="kpi-val-row">
              <span class="kpi-val fig">{{ num((d?.finra_short as any)?.market_median_short_ratio, 3) }}</span>
              <span class="kpi-badge" :class="qTone((d?.finra_short as any)?.quality)">
                {{ String((d?.finra_short as any)?.quality ?? 'NO DATA').toUpperCase() }}
              </span>
            </div>
            <span class="kpi-sub">Market median ratio · {{ shortDate((d?.finra_short as any)?.asof) }}</span>
          </div>
        </div>

        <Panel
          label="Vol complex"
          index=""
          :meta="vol?.asof ? shortDate(vol.asof) : ''"
          class="w-half"
        >
          <template #action>
            <HelpTip
              label="Vol complex"
              text="Snapshot of VIX, term structure, tail demand, and index returns. Green leans risk-on, red leans risk-off. Not a trade signal."
            />
          </template>
          <div v-if="volRows.length" class="vol-grid">
            <div v-for="r in volRows" :key="r.key" class="vol-cell">
              <span class="label vol-lab">
                {{ r.label }}
                <HelpTip v-if="r.help" :label="r.label" :text="r.help" />
              </span>
              <span class="fig vol-val" :class="r.tone">{{ r.value }}</span>
              <span v-if="r.lean" class="vol-lean label">{{ r.lean }}</span>
            </div>
          </div>
          <p v-else class="note pad">Vol complex unavailable.</p>
        </Panel>

        <Panel label="CFTC commitment of traders" index="" :meta="shortDate(d?.cot?.asof) || ''" class="w-half" flush>
          <template #action>
            <HelpTip label="How to use COT" :text="COT_HELP" />
          </template>
          <div class="table-container">
            <table v-if="cotMarkets.length" class="grid">
              <thead>
                <tr>
                  <th class="label">Market</th>
                  <th class="label">
                    Bias
                    <HelpTip text="LONG = futures specs crowded long (bullish lean for that book). SHORT = crowded short (bearish lean). Not an equity entry." />
                  </th>
                  <th class="label num">
                    Spec net
                    <HelpTip text="Non-commercial long minus short. Large positive = specs net long." />
                  </th>
                  <th class="label num">
                    Z 1y
                    <HelpTip text="How extreme today's net is vs the last ~1 year." />
                  </th>
                  <th class="label num">%ile</th>
                  <th class="label num">OI</th>
                  <th class="label">As-of</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="m in cotMarkets" :key="m.id">
                  <td>
                    <span class="strat">{{ m.id }}</span>
                    <span class="label dim s-file">{{ m.label }}</span>
                  </td>
                  <td>
                    <span class="kpi-badge" :class="biasTone(m.bias)">{{ m.bias ?? 'n/a' }}</span>
                  </td>
                  <td class="fig num" :class="tone(m.noncomm_net)">{{ signed(m.noncomm_net, 0) }}</td>
                  <td class="fig num" :class="tone(m.noncomm_net_z_1y)">{{ num(m.noncomm_net_z_1y, 2) }}</td>
                  <td class="fig num">{{ num(m.noncomm_net_pctile_1y, 2) }}</td>
                  <td class="fig num">{{ compact(m.open_interest, 1) }}</td>
                  <td class="label dim">{{ shortDate(m.asof) }}</td>
                </tr>
              </tbody>
            </table>
            <p v-else class="note pad">No COT markets loaded. {{ (d?.cot?.errors || []).join('; ') }}</p>
          </div>
        </Panel>

        <Panel
          label="FINRA short-volume pressure"
          index=""
          :meta="shortDate((d?.finra_short as any)?.asof) || ''"
          class="w-full"
          flush
        >
          <template #action>
            <HelpTip
              label="Short ratio lean"
              text="Elevated = more short-side volume than that name's own history → bearish pressure lean. Quiet = less shorting than usual → short covering / less pressure. This is trading volume side, not shares still short."
            />
          </template>
          <div class="split-tables">
            <div>
              <span class="label block-lab neg-lab">
                Heavy shorting
                <small class="lean-tag">bearish pressure lean</small>
              </span>
              <table v-if="finraTop.length" class="grid">
                <thead>
                  <tr>
                    <th class="label">Sym</th>
                    <th class="label num">Short ratio</th>
                    <th class="label num">Z</th>
                    <th class="label">Lean</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="r in finraTop" :key="'h' + r.symbol" @click="openMarket(r.symbol)">
                    <td class="fig sym">{{ r.symbol }}</td>
                    <td class="fig num">{{ num(r.short_ratio, 3) }}</td>
                    <td class="fig num neg">{{ num(r.z_vs_own_hist, 2) }}</td>
                    <td class="label dim lean-cell">{{ finraLean(r.z_vs_own_hist, 'high') }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="note pad">No elevated short-pressure names.</p>
            </div>
            <div>
              <span class="label block-lab pos-lab">
                Quiet shorting
                <small class="lean-tag">less short pressure</small>
              </span>
              <table v-if="finraLow.length" class="grid">
                <thead>
                  <tr>
                    <th class="label">Sym</th>
                    <th class="label num">Short ratio</th>
                    <th class="label num">Z</th>
                    <th class="label">Lean</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="r in finraLow" :key="'l' + r.symbol" @click="openMarket(r.symbol)">
                    <td class="fig sym">{{ r.symbol }}</td>
                    <td class="fig num">{{ num(r.short_ratio, 3) }}</td>
                    <td class="fig num pos">{{ num(r.z_vs_own_hist, 2) }}</td>
                    <td class="label dim lean-cell">{{ finraLean(r.z_vs_own_hist, 'low') }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="note pad">No quiet short-pressure names.</p>
            </div>
          </div>
        </Panel>

        <Panel
          label="SEC filings"
          index=""
          :meta="filings ? `${filings.symbol}` : 'pick a ticker above'"
          class="w-full"
          flush
        >
          <template #action>
            <HelpTip label="SEC forms" :text="SEC_HELP" />
          </template>
          <template v-if="filings">
            <p v-if="filings.error" class="err">{{ filings.error }}</p>
            <div v-if="filings.counts_90d" class="mkt-readouts">
              <Readout
                v-for="(v, k) in filings.counts_90d"
                :key="k"
                :label="formLabel(String(k))"
                :value="String(v)"
                :sub="'90d count'"
                size="sm"
              />
            </div>
            <p v-if="filings.edgar_company_url" class="note pad">
              <a :href="filings.edgar_company_url" target="_blank" rel="noopener">Open EDGAR company page ↗</a>
            </p>
            <div class="table-container">
              <table v-if="filings.filings?.length" class="grid">
                <thead>
                  <tr>
                    <th class="label">Filed</th>
                    <th class="label">Form</th>
                    <th class="label">What it means</th>
                    <th class="label">Link</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(f, i) in filings.filings" :key="i">
                    <td class="label dim">{{ shortDate(f.filed) }}</td>
                    <td class="fig">{{ f.form }}</td>
                    <td class="label dim feat">{{ formMeaning(f.form) || f.description || 'n/a' }}</td>
                    <td>
                      <a v-if="f.url" :href="f.url" target="_blank" rel="noopener" class="label">doc ↗</a>
                      <span v-else class="label dim">n/a</span>
                    </td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="note pad">No watched filings in the recent window (or ticker not in SEC map).</p>
            </div>
          </template>
          <p v-else class="note pad">
            Enter a ticker (e.g. AAPL) and click <strong>Load filings</strong> to see insider trades (Form 4), material events (8-K), and large holders (13D/G).
          </p>
        </Panel>
      </template>
    </template>

    <!-- ══════════════ OUTLIERS TAB ══════════════ -->
    <template v-else>
      <LoadingState v-if="outliersLoading" class="w-full" label="Scanning outliers…" />

      <template v-else>
        <p v-if="anomalies.error.value" class="err w-full">{{ anomalies.error.value }}</p>

        <div class="summary-deck">
          <div class="kpi-card armed">
            <span class="label kpi-label">
              Unified outliers
              <HelpTip text="Names that cleared hard thresholds only. Empty means nothing cleared — not a calm market." />
            </span>
            <div class="kpi-val-row">
              <span class="kpi-val fig">{{ unified.length }}</span>
              <span class="kpi-badge flat">RANKED</span>
            </div>
            <span class="kpi-sub">Price · FINRA · SEC</span>
          </div>
          <div class="kpi-card">
            <span class="label kpi-label">Price / volume</span>
            <div class="kpi-val-row">
              <span class="kpi-val fig">{{ a?.price_volume?.n_flagged ?? DASH }}</span>
              <span class="kpi-badge">/ {{ a?.price_volume?.n_scanned ?? 'n/a' }}</span>
            </div>
            <span class="kpi-sub">{{ shortDate(a?.price_volume?.asof) }}</span>
          </div>
          <div class="kpi-card">
            <span class="label kpi-label">FINRA extremes</span>
            <div class="kpi-val-row">
              <span class="kpi-val fig">{{ shortRows.length }}</span>
              <span class="kpi-badge">|z| ≥ 2</span>
            </div>
            <span class="kpi-sub">{{ shortDate((a?.finra_short_extremes as any)?.asof) }}</span>
          </div>
          <div class="kpi-card">
            <span class="label kpi-label">SEC activity</span>
            <div class="kpi-val-row">
              <span class="kpi-val fig">{{ secRows.length }}</span>
              <span class="kpi-badge">flags</span>
            </div>
            <span class="kpi-sub">{{ shortDate((a?.sec_activity as any)?.asof) }}</span>
          </div>
        </div>

        <Panel label="Unified anomaly feed" index="" :meta="`${unified.length} events`" class="w-full" flush>
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
                  <td class="fig sym">{{ r.symbol }}</td>
                  <td><span class="kind" :class="kindClass(String(r.kind))">{{ r.kind }}</span></td>
                  <td class="fig num">{{ num(r.severity as number, 2) }}</td>
                  <td class="label dim feat">
                    <template v-if="r.kind === 'PRICE_VOLUME'">
                      1d {{ signedPct(Number(r.ret_1d) * 100, 2) }}
                      · 5d {{ signedPct(Number(r.ret_5d) * 100, 2) }}
                      · vol× {{ num(r.volume_vs_20d_med as number, 2) }}
                      <span v-if="Array.isArray(r.flags)"> · {{ (r.flags as string[]).join(', ') }}</span>
                    </template>
                    <template v-else-if="String(r.kind).includes('FINRA')">
                      ratio {{ num(r.value as number, 3) }} · z {{ num(r.z as number, 2) }}
                    </template>
                    <template v-else-if="String(r.kind).includes('SEC')">
                      F4 {{ r.form4_90d }} · 8-K {{ r.eightk_90d }} · 13D/G {{ r.sc13_90d }}
                      · latest {{ r.latest_form }}
                    </template>
                    <template v-else>{{ r.note || 'n/a' }}</template>
                  </td>
                  <td class="label dim">{{ shortDate(r.asof as string) }}</td>
                  <td class="label dim feat">{{ r.source || 'n/a' }}</td>
                </tr>
              </tbody>
            </table>
            <p v-else class="note pad">
              {{ anomalies.loading.value ? 'Scanning…' : 'No outliers cleared thresholds (or sources missing).' }}
            </p>
          </div>
        </Panel>

        <Panel label="Price & volume extremes" index="" :meta="a?.price_volume?.source || ''" class="w-half" flush>
          <p class="note pad">{{ a?.price_volume?.lag_note }}</p>
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
                  <td class="fig sym">{{ r.symbol }}</td>
                  <td class="fig num" :class="tone(r.ret_1d)">{{ signedPct(Number(r.ret_1d) * 100, 2) }}</td>
                  <td class="fig num" :class="tone(r.ret_5d)">{{ signedPct(Number(r.ret_5d) * 100, 2) }}</td>
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
          label="FINRA short-volume extremes"
          index=""
          :meta="String((a?.finra_short_extremes as any)?.source || '')"
          class="w-half"
          flush
        >
          <p class="note pad">{{ (a?.finra_short_extremes as any)?.lag_note }}</p>
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
                  <td class="fig sym">{{ r.symbol }}</td>
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
          label="SEC filing activity (sample universe)"
          index=""
          :meta="String((a?.sec_activity as any)?.source || '')"
          class="w-full"
          flush
        >
          <p class="note pad">{{ (a?.sec_activity as any)?.lag_note }}</p>
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
                  <td class="fig sym">{{ r.symbol }}</td>
                  <td class="fig num">{{ r.form4_90d }}</td>
                  <td class="fig num">{{ r.eightk_90d }}</td>
                  <td class="fig num">{{ r.sc13_90d }}</td>
                  <td class="label dim">{{ r.latest_form }} · {{ shortDate(r.latest_filing) }}</td>
                </tr>
              </tbody>
            </table>
            <p v-else class="note pad">No elevated filing activity in the scanned seed set (or SEC unreachable).</p>
          </div>
        </Panel>

        <Panel v-if="focus" label="Symbol focus" index="" :meta="focus.symbol" class="w-full">
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
              label="SEC filings quality"
              :value="focus.filings?.quality ?? DASH"
              size="sm"
            />
          </div>
        </Panel>
      </template>
    </template>
  </div>
</template>

<style scoped>
.pulse-view {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s4);
  align-content: start;
  min-width: 0;
}
.page-head {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding-bottom: var(--s2);
  border-bottom: var(--hair) solid var(--rule);
}
.head-left {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
}
.pulse-refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  height: 32px;
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-micro);
  letter-spacing: 0.05em;
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
  cursor: pointer;
  transition: all 0.12s ease;
}
.pulse-refresh-btn:hover:not(:disabled) {
  background: var(--phosphor);
  color: var(--void);
}
.pulse-refresh-btn:disabled {
  opacity: 0.65;
  cursor: wait;
}
.refresh-icon {
  display: inline-block;
  font-size: 0.95rem;
  line-height: 1;
}
.refresh-icon.spinning {
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.tabs {
  display: flex;
  gap: 2px;
  border: var(--hair) solid var(--rule-hi);
}
.tab {
  padding: 8px 14px;
  color: var(--ink-faint);
  background: transparent;
  border: 0;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.tab:hover { color: var(--ink); background: var(--panel-hi); }
.tab.on {
  color: var(--void);
  background: var(--phosphor);
  font-weight: 800;
}
.tab-count {
  font-size: 10px;
  padding: 1px 5px;
  border: var(--hair) solid currentColor;
  opacity: 0.85;
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
  min-width: 0;
  overflow: hidden;
}
.kpi-card.armed { border-color: var(--phosphor-dim); box-shadow: inset 3px 0 0 var(--phosphor); }
.kpi-label {
  color: var(--ink-dim);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: normal;
}
.kpi-val-row { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s2); min-width: 0; }
.kpi-val {
  font-family: var(--font-display);
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.kpi-val.fig { font-variant-numeric: tabular-nums; }
.kpi-sub {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kpi-badge {
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 2px 6px;
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  flex: 0 0 auto;
}
.kpi-badge.pos { color: var(--long); border-color: var(--long); background: var(--long-wash); }
.kpi-badge.neg { color: var(--short); border-color: var(--short); background: var(--short-wash); }
.kpi-badge.flat { color: var(--warn); border-color: var(--warn); background: var(--warn-wash); }

.w-full { grid-column: 1 / -1; min-width: 0; }
.w-half { grid-column: span 1; min-width: 0; }

.vol-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: var(--s3);
  padding: var(--s3) var(--s4);
}
.vol-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: var(--s3);
  border: var(--hair) solid var(--rule-faint);
  background: var(--panel-hi);
}
.vol-lab {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--ink-dim);
  white-space: normal;
}
.vol-val {
  font-size: var(--t-fig);
  font-weight: 600;
  color: var(--ink);
}
.vol-val.pos { color: var(--long); }
.vol-val.neg { color: var(--short); }
.vol-lean {
  color: var(--ink-faint);
  font-size: 9px;
  letter-spacing: 0.04em;
  white-space: normal;
  line-height: 1.3;
}
.neg-lab { color: var(--short) !important; }
.pos-lab { color: var(--long) !important; }
.lean-tag {
  display: block;
  margin-top: 2px;
  font-weight: 500;
  color: var(--ink-faint);
  letter-spacing: 0.04em;
  text-transform: none;
}
.lean-cell {
  max-width: 28ch;
  white-space: normal !important;
  font-size: 10px;
  line-height: 1.3;
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
  font-family: var(--font-mono, var(--font-display));
  padding: 6px 10px;
  width: 9ch;
  letter-spacing: 0.06em;
  text-transform: uppercase;
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
.btn:hover { background: var(--phosphor); color: var(--void); }

.mkt-readouts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
}
.note.pad, .pad { padding: var(--s3) var(--s4); }
.note { color: var(--ink-dim); font-size: var(--t-small); line-height: 1.4; }
.err { color: var(--short); padding: var(--s3) var(--s4); font-weight: 600; }
:deep(.loading.w-full),
.err.w-full { grid-column: 1 / -1; min-height: 180px; }
.table-container { overflow: auto; max-height: 420px; }
.grid { width: 100%; border-collapse: collapse; }
.grid th, .grid td {
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
.grid th .help { margin-left: 4px; }
.grid tbody tr { cursor: pointer; }
.grid tbody tr:hover { background: var(--panel-hi); }
.num { text-align: right !important; font-variant-numeric: tabular-nums; }
.fig { font-variant-numeric: tabular-nums; }
.sym { color: var(--phosphor); font-weight: 700; }
.pos { color: var(--long); }
.neg { color: var(--short); }
.flat { color: var(--ink-dim); }
.dim { color: var(--ink-faint); }
.strat { display: block; font-weight: 700; color: var(--ink); }
.s-file { display: block; font-size: var(--t-micro); max-width: 28ch; overflow: hidden; text-overflow: ellipsis; }
.feat { max-width: 42ch; overflow: hidden; text-overflow: ellipsis; }
.split-tables {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s3);
  padding: 0 var(--s3) var(--s3);
}
.block-lab {
  display: block;
  padding: var(--s2);
  color: var(--ink-dim);
  font-weight: 700;
}
.kind {
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.03em;
}
.kind.pos { color: var(--long); }
.kind.neg { color: var(--short); }
.kind.flat { color: var(--warn); }
a { color: var(--phosphor); }

@media (max-width: 1100px) {
  .pulse-view, .summary-deck, .split-tables { grid-template-columns: 1fr; }
  .w-half { grid-column: 1 / -1; }
}
</style>
