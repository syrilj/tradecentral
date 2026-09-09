<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import {
  api,
  CRYPTO_COT_ID,
  CRYPTO_FOCUS_DEFAULT,
  CRYPTO_TAPE_SLEEVES,
  CRYPTO_TAPE_SYMBOLS,
  type CotMarket,
  type CryptoVehicle,
  type KalmanTrendPayload,
  type QuoteMark,
} from '@/api'
import { useResource } from '@/composables/useResource'
import {
  cryptoSpotRead,
  kalmanTrendLabel,
  type EvidenceKind,
  type KalmanTrendRead,
} from '@/cryptoRead'
import { cotLeanTone } from '@/cotLean'
import { age, DASH, num, shortDate, signedPct, tone } from '@/format'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import HelpTip from '@/components/HelpTip.vue'
import LoadingState from '@/components/LoadingState.vue'

/**
 * CRYPTO — 24/7 coin workspace.
 *
 * Three measured lenses, one page:
 *   01 Coin tape — Yahoo hyphenated marks (BTC-USD and peers) plus labeled
 *      equity vehicles. Missing last is missing, never a fake zero.
 *   02 Focus-coin Kalman — slope / noise (scale-tested on ~$50k BTC).
 *   03 Bitcoin futures spec lean — CFTC COT id BTC.
 *
 * Combined LONG/SHORT/BALANCED/UNKNOWN is inferred from those two z-scores.
 * Session language is 24/7. Decision support only.
 */

const route = useRoute()
const router = useRouter()

const TAPE_POLL_MS = 60_000
const COT_POLL_MS = 900_000
const KALMAN_POLL_MS = 300_000

function cleanCoin(raw: string): string {
  const t = raw
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
    .slice(0, 10)
  return CRYPTO_TAPE_SYMBOLS.includes(t) ? t : CRYPTO_FOCUS_DEFAULT
}

const focusCoin = ref(cleanCoin(String(route.query.symbol ?? CRYPTO_FOCUS_DEFAULT)))

function selectCoin(sym: string): void {
  const clean = cleanCoin(sym)
  focusCoin.value = clean
  void router.replace({ query: { ...route.query, symbol: clean } })
}

watch(
  () => route.query.symbol,
  (s) => {
    if (typeof s === 'string' && s) {
      const clean = cleanCoin(s)
      if (clean !== focusCoin.value) focusCoin.value = clean
    }
  },
)

const quotesRes = useResource(() => api.quotes(CRYPTO_TAPE_SYMBOLS), {
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

const kalmanRes = useResource(() => api.kalmanTrend(focusCoin.value, { window: '1y' }), {
  intervalMs: KALMAN_POLL_MS,
})

watch(focusCoin, () => {
  void kalmanRes.refresh({ clear: true })
})

async function refreshAll(): Promise<void> {
  cotForceNext.value = true
  await Promise.all([quotesRes.refresh(), cotRes.refresh(), kalmanRes.refresh({ clear: true })])
}

const isRefreshing = computed(
  () => quotesRes.loading.value || cotRes.loading.value || kalmanRes.loading.value,
)

/* ---- 01 coin tape ------------------------------------------------------- */

interface CryptoMark extends QuoteMark {
  name: string
  sleeve: string
  vehicle: CryptoVehicle
}

const quoteBySym = computed(() => {
  const map = new Map<string, QuoteMark>()
  for (const row of quotesRes.data.value?.rows ?? []) map.set(row.symbol, row)
  return map
})

const tapeGroups = computed<{ sleeve: string; rows: CryptoMark[] }[]>(() => {
  const src = quoteBySym.value
  return CRYPTO_TAPE_SLEEVES.map(({ sleeve, symbols }) => ({
    sleeve,
    rows: symbols.map((s) => ({
      name: s.name,
      sleeve,
      vehicle: s.vehicle,
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

function markQuality(r: CryptoMark): MarkQuality {
  if (r.last == null) return 'missing'
  if (r.quality === 'live') return 'current'
  if (!r.asof) return 'stale'
  const stamp = Date.parse(`${String(r.asof).slice(0, 10)}T00:00:00Z`)
  if (!Number.isFinite(stamp)) return 'stale'
  return Date.now() - stamp <= 4 * 86_400_000 ? 'current' : 'stale'
}

function markSource(r: CryptoMark): string {
  return r.source || 'unavailable'
}

const focusMeta = computed(() => {
  for (const g of tapeGroups.value) {
    const row = g.rows.find((r) => r.symbol === focusCoin.value)
    if (row) return row
  }
  return null
})

/* ---- 02 Kalman ---------------------------------------------------------- */

const kalmanPayload = computed<KalmanTrendPayload | null>(() => {
  const d = kalmanRes.data.value
  if (!d || d.symbol !== focusCoin.value) return null
  return d
})

const kalmanScore = computed(() => {
  const d = kalmanPayload.value
  if (!d || !d.available) return null
  const z = d.now?.score
  if (z == null || !Number.isFinite(Number(z))) return null
  return Number(z)
})

const kalmanSlopePct = computed(() => {
  const d = kalmanPayload.value
  if (!d || !d.available) return null
  const v = d.now?.slope_pct_per_day
  if (v == null || !Number.isFinite(Number(v))) return null
  return Number(v)
})

const kalmanAsOf = computed(() => kalmanPayload.value?.now?.date ?? kalmanPayload.value?.last_date ?? null)
const kalmanGenerated = computed(() => kalmanPayload.value?.generated_at ?? null)
const kalmanUnavailable = computed(() => {
  const d = kalmanPayload.value
  if (!d) return kalmanRes.error.value ? kalmanRes.error.value : null
  if (!d.available) return d.reason || 'unmeasured'
  return null
})

/* ---- 03 BTC COT --------------------------------------------------------- */

const btcCot = computed<CotMarket | null>(() => {
  const markets = (cotRes.data.value?.markets ?? []) as CotMarket[]
  return markets.find((m) => m.id === CRYPTO_COT_ID) ?? null
})

const cotSpecZ = computed(() => {
  const z = btcCot.value?.noncomm_net_z_1y
  if (z == null || !Number.isFinite(Number(z))) return null
  return Number(z)
})

const cotAsOf = computed(() => btcCot.value?.asof ?? cotRes.data.value?.asof ?? null)
const cotSource = computed(
  () => btcCot.value?.source || cotRes.data.value?.source || 'CFTC Commitment of Traders',
)
const cotStale = computed(() => {
  const q = String(cotRes.data.value?.quality ?? btcCot.value?.quality ?? '')
  if (!q) return true
  return q === 'stale' || q === 'missing'
})
const cotLag = computed(() => btcCot.value?.lag_note || cotRes.data.value?.lag_note || '')

/* ---- combined read ------------------------------------------------------ */

const spotRead = computed(() =>
  cryptoSpotRead({
    kalmanSlopeOverNoise: kalmanScore.value,
    cotSpecNetZ: cotSpecZ.value,
  }),
)

function kindCopy(kind: EvidenceKind): string {
  if (kind === 'measured') return 'measured'
  if (kind === 'inferred') return 'inferred'
  return 'missing'
}

function trendCopy(read: KalmanTrendRead): string {
  return kalmanTrendLabel(read)
}

const kalmanTone = computed<'pos' | 'neg' | 'flat'>(() => {
  const r = spotRead.value.kalman.read
  if (r === 'TREND_UP') return 'pos'
  if (r === 'TREND_DOWN') return 'neg'
  return 'flat'
})
</script>

<template>
  <div class="crypto-view">
    <header class="crypto-head ticked rise">
      <div class="head-copy">
        <span class="eyebrow">Cryptocurrency</span>
        <h1>Crypto</h1>
        <p>
          24/7 coin marks, Kalman slope-over-noise on the focus coin, and CFTC Bitcoin futures spec
          lean. Reads are labeled measured, inferred, or missing. Decision support only.
        </p>
      </div>
      <div class="head-actions">
        <span class="label session">Session 24/7</span>
        <span class="label asof wraps">
          {{ tapeMeasured }}/{{ tapeTotal }} marked
          <template v-if="quotesRes.fetchedAt.value">
            · tape {{ age(quotesRes.fetchedAt.value) }} ago</template
          >
        </span>
        <span class="kpi-badge" :class="cotLeanTone(spotRead.combined.lean)">
          {{ spotRead.combined.label }}
        </span>
        <span class="label kind">{{ kindCopy(spotRead.combined.kind) }} combined read</span>
        <button
          type="button"
          class="refresh-btn label"
          :disabled="isRefreshing"
          title="Refresh coin tape, Kalman, and BTC COT"
          @click="void refreshAll()"
        >
          {{ isRefreshing ? 'Refreshing…' : 'Refresh' }}
        </button>
      </div>
    </header>

    <!-- ── 01 coin tape ──────────────────────────────────────────────── -->
    <Panel
      label="Coin Tape"
      index="01"
      :meta="
        quotesRes.error.value
          ? 'Feed unavailable'
          : `as-of ${shortDate(quotesRes.data.value?.asof?.slice(0, 10) ?? null)}`.trim()
      "
      :live="quotesRes.loading.value && !quotesRes.data.value"
      class="w-full"
    >
      <template #action>
        <HelpTip
          label="Coin tape"
          text="Yahoo hyphenated coin marks (BTC-USD and peers) via the existing quotes path. Coins outside local parquet fall through to a short-TTL yfinance pull. A missing last is unmeasured — never a fake zero. IBIT and MSTR are equity vehicles, not coin spot. Session is 24/7."
          align="right"
        />
      </template>
      <LoadingState
        v-if="quotesRes.loading.value && !quotesRes.data.value"
        label="Pulling coin marks"
        compact
      />
      <p v-else-if="quotesRes.error.value" class="err">{{ quotesRes.error.value }}</p>
      <div v-else-if="tapeMeasured > 0" class="tape-grid">
        <div v-for="group in tapeGroups" :key="group.sleeve" class="sleeve">
          <span class="sleeve-name">{{ group.sleeve }}</span>
          <div class="mark-list">
            <button
              v-for="r in group.rows"
              :key="r.symbol"
              type="button"
              class="mark"
              :class="[`q-${markQuality(r)}`, { on: r.symbol === focusCoin }]"
              :title="`${r.symbol} · ${r.name} · ${markSource(r)} · set focus`"
              @click="selectCoin(r.symbol)"
            >
              <span class="sym fig">{{ r.symbol }}</span>
              <span class="name label wraps">
                {{ r.name }}
                <span v-if="r.vehicle === 'equity'" class="vehicle">Equity vehicle</span>
              </span>
              <span class="last fig">{{ num(r.last, 2) }}</span>
              <span class="chg fig" :class="tone(r.chg_1d_pct)">
                {{ r.chg_1d_pct == null ? DASH : signedPct(r.chg_1d_pct, 2) }}
              </span>
              <span class="src label">{{ markSource(r) }}</span>
              <span v-if="markQuality(r) !== 'current'" class="q-flag label">
                {{ markQuality(r) === 'missing' ? 'UNMEASURED' : 'STALE' }}
              </span>
            </button>
          </div>
        </div>
      </div>
      <p v-else class="note pad">
        No coin marks available. The quote feed returned nothing — missing, not zero.
      </p>
      <p v-if="tapeMeasured > 0" class="note tiny pad-x">
        Click a row to set the Kalman focus coin. UNMEASURED = provider returned no mark. STALE =
        observed bar older than four days. Equity vehicles are listed separately from spot coins.
      </p>
    </Panel>

    <!-- ── 02 focus-coin Kalman ──────────────────────────────────────── -->
    <Panel
      label="Focus Coin Kalman"
      index="02"
      :meta="kalmanAsOf ? `as-of ${shortDate(kalmanAsOf)}` : 'unmeasured'"
    >
      <template #action>
        <HelpTip
          label="Kalman slope over noise"
          text="Constant-velocity Kalman filter on the focus coin. The traded statistic is slope / rolling noise (z), scale-tested on ~$50k BTC so dollar level does not change the read. |z| ≥ 1.0 is trend; inside that band is chop. Non-finite scores render as unmeasured, never 0."
          align="right"
        />
        <RouterLink
          class="filter-btn label"
          :to="{ name: 'kalman', query: { symbol: focusCoin } }"
        >
          Open Kalman ↗
        </RouterLink>
      </template>
      <LoadingState
        v-if="kalmanRes.loading.value && !kalmanPayload"
        label="Running Kalman filter"
        compact
      />
      <p v-else-if="kalmanRes.error.value" class="err">{{ kalmanRes.error.value }}</p>
      <p v-else-if="kalmanUnavailable" class="note pad">
        Kalman unmeasured for {{ focusCoin }}{{ kalmanUnavailable ? ` — ${kalmanUnavailable}` : '' }}.
      </p>
      <template v-else>
        <div class="read-grid">
          <Readout
            label="Focus"
            :value="focusCoin"
            :sub="
              focusMeta
                ? `${focusMeta.name}${focusMeta.vehicle === 'equity' ? ' · equity vehicle' : ' · coin spot'}`
                : 'coin spot'
            "
            size="sm"
          />
          <Readout
            label="Slope / noise"
            :value="num(spotRead.kalman.value, 2)"
            :sub="`${kindCopy(spotRead.kalman.kind)} · ${spotRead.kalman.source}`"
            :tone="kalmanTone"
            size="sm"
          />
          <Readout
            label="Trend read"
            :value="trendCopy(spotRead.kalman.read)"
            :sub="spotRead.kalman.read === 'UNMEASURED' ? 'unmeasured' : kindCopy(spotRead.kalman.kind)"
            :tone="kalmanTone"
            size="sm"
          />
          <Readout
            label="Implied drift"
            :value="kalmanSlopePct == null ? DASH : `${signedPct(kalmanSlopePct, 3)} / day`"
            :sub="kalmanGenerated ? `generated ${age(kalmanGenerated)} ago` : 'freshness missing'"
            :tone="tone(kalmanSlopePct)"
            size="sm"
          />
        </div>
      </template>
    </Panel>

    <!-- ── 03 BTC COT ────────────────────────────────────────────────── -->
    <Panel
      label="Bitcoin Futures Spec Lean"
      index="03"
      :meta="`Week of ${shortDate(cotAsOf)}${cotStale ? ' · STALE' : ''}`"
    >
      <template #action>
        <HelpTip
          label="Bitcoin futures spec lean"
          text="Weekly CFTC non-commercial net position on Bitcoin futures (market id BTC), z-scored over one year. LONG/SHORT/BALANCED/UNKNOWN uses the same ±0.5 cutoffs as the rest of the desk. Published Fridays for Tuesday positions. This is futures spec positioning, not coin spot and not an equity-options tape."
          align="right"
        />
      </template>
      <LoadingState
        v-if="cotRes.loading.value && !cotRes.data.value"
        label="Loading BTC COT"
        compact
      />
      <p v-else-if="cotRes.error.value" class="err">{{ cotRes.error.value }}</p>
      <template v-else-if="btcCot">
        <div class="read-grid">
          <Readout
            label="Book"
            :value="CRYPTO_COT_ID"
            :sub="btcCot.label || 'Bitcoin futures'"
            size="sm"
          />
          <Readout
            label="Spec net"
            :value="btcCot.noncomm_net == null ? DASH : num(btcCot.noncomm_net, 0)"
            :sub="cotSource"
            size="sm"
          />
          <Readout
            label="Z · 1y"
            :value="num(spotRead.cot.value, 2)"
            :sub="`${kindCopy(spotRead.cot.kind)} · ${spotRead.cot.source}`"
            :tone="cotLeanTone(spotRead.cot.read)"
            size="sm"
          />
          <Readout
            label="Lean"
            :value="spotRead.cot.read"
            :sub="spotRead.cot.read === 'UNKNOWN' ? 'unmeasured' : kindCopy(spotRead.cot.kind)"
            :tone="cotLeanTone(spotRead.cot.read)"
            size="sm"
          />
        </div>
        <p v-if="cotLag" class="note tiny pad-x">{{ cotLag }}</p>
      </template>
      <p v-else class="note pad">
        No BTC COT market loaded — Bitcoin futures spec lean is missing, not zero.
      </p>
    </Panel>

    <footer class="disclaimer label wraps">
      DECISION SUPPORT ONLY · 24/7 coin session · combined {{ spotRead.combined.label }} is
      {{ kindCopy(spotRead.combined.kind) }} from Kalman and CFTC BTC spec lean · never an order or
      an authorization.
    </footer>
  </div>
</template>

<style scoped>
.crypto-view {
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

.crypto-head {
  grid-column: 1 / -1;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s5);
  padding: var(--s4) var(--s5);
  border: var(--hair) solid var(--rule);
  border-left: 1px solid var(--phosphor-dim);
  border-radius: var(--r-sm);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 48px),
    var(--surface-base);
}

.eyebrow {
  color: var(--phosphor);
  font-size: var(--t-micro);
  font-weight: 600;
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
.session {
  color: var(--phosphor);
}
.asof,
.kind {
  color: var(--ink-dim);
}
.refresh-btn {
  min-height: 44px;
  padding: var(--s2) var(--s3);
  color: var(--ink-soft);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--panel-hi);
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
.crypto-view :deep(.panel .lab) {
  text-transform: none;
  letter-spacing: 0.01em;
}
.sleeve-name {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  font-weight: 600;
  border-bottom: var(--hair) solid var(--rule-faint);
  padding-bottom: var(--s1);
}
.mark-list {
  display: flex;
  flex-direction: column;
}
.mark {
  display: grid;
  grid-template-columns: 8ch minmax(0, 1fr) auto minmax(8ch, auto);
  align-items: center;
  gap: var(--s3);
  min-height: 44px;
  padding: var(--s2);
  border-bottom: var(--hair) solid var(--rule-faint);
  text-align: left;
  transition: background var(--dur-fast) var(--ease-out);
}
.mark:last-child {
  border-bottom: none;
}
.mark:hover,
.mark.on {
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
.src {
  grid-column: 1 / 3;
  font-size: var(--t-micro);
  color: var(--ink-faint);
}
.vehicle {
  margin-left: var(--s2);
  color: var(--warn);
}
.pos {
  color: var(--long);
}
.neg {
  color: var(--short);
}
.q-flag {
  grid-column: 3 / 5;
  justify-self: end;
  color: var(--warn);
  font-size: var(--t-tiny);
}

.read-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--s3);
}

.kpi-badge {
  display: inline-block;
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  font-weight: 700;
  padding: 2px 7px;
  border-radius: var(--r-xs);
  letter-spacing: 0.04em;
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

.filter-btn {
  min-height: 44px;
  display: inline-flex;
  align-items: center;
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
  padding: 0 var(--s4) var(--s3);
}
.err {
  color: var(--warn);
  padding: var(--s4);
}
.disclaimer {
  grid-column: 1 / -1;
  color: var(--ink-faint);
  padding: var(--s3) 0;
}

@media (max-width: 780px) {
  .crypto-view {
    grid-template-columns: minmax(0, 1fr);
  }
  .crypto-head {
    flex-direction: column;
    align-items: stretch;
  }
  .head-actions {
    align-items: flex-start;
  }
}
</style>
