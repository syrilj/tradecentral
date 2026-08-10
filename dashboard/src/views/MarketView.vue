<script setup lang="ts">
import { computed, inject, ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, WINDOWS, type SearchHit, type Trajectory, type ComparePayload, type TrajWindow, type StatusPayload } from '@/api'
import type { Resource } from '@/composables/useResource'
import { debounce } from '@/composables/useResource'
import { num, pct, pctFrac, signedPct, compact, usd, tone, shortDate, DASH } from '@/format'
import { sparkline } from '@/charts'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import TrajectoryChart from '@/components/TrajectoryChart.vue'

const status = inject<Resource<StatusPayload>>('status')
const route = useRoute()
const router = useRouter()

const q = ref('')
const hits = ref<SearchHit[]>([])
const searching = ref(false)

const symbol = ref<string>(((route.query.symbol as string) || 'AAPL').toUpperCase())
const win = ref<TrajWindow>('1y')
const mode = ref<'price' | 'growth'>('price')
const chartStyle = ref<'candles' | 'line'>('candles')

const traj = ref<Trajectory | null>(null)
const trajErr = ref<string | null>(null)
const trajBusy = ref(false)

const basket = ref<string[]>([])
const cmp = ref<ComparePayload | null>(null)
const cmpErr = ref<string | null>(null)

// Ensure route query changes update active symbol
watch(
  () => route.query.symbol,
  (newSym) => {
    if (newSym && typeof newSym === 'string' && newSym !== symbol.value) {
      symbol.value = newSym
    }
  },
  { immediate: true }
)

function cleanTicker(term: string): string {
  return term.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, '').slice(0, 10)
}

const runSearch = debounce(async (term: string) => {
  searching.value = true
  try {
    const cleaned = cleanTicker(term)
    const raw = await api.search(cleaned, 18)
    let list = raw.filter((h) => (h.kind ?? 'symbol') === 'symbol')
    // Always surface the exact typed ticker so missing-cache names are visible.
    if (cleaned && !list.some((h) => h.symbol === cleaned)) {
      list = [
        {
          symbol: cleaned,
          kind: 'symbol',
          tier: 'wide',
          n_bars: 0,
          first_date: '',
          last_date: '',
        } as SearchHit,
        ...list,
      ]
    }
    hits.value = list
  } catch {
    hits.value = []
  } finally {
    searching.value = false
  }
}, 140)

watch(q, (v) => runSearch(v))

async function loadTrajectory(): Promise<void> {
  trajBusy.value = true
  trajErr.value = null
  try {
    traj.value = await api.trajectory(symbol.value, win.value)
  } catch (e) {
    trajErr.value = e instanceof Error ? e.message : String(e)
    traj.value = null
  } finally {
    trajBusy.value = false
  }
}

async function loadCompare(): Promise<void> {
  if (basket.value.length < 2) {
    cmp.value = null
    cmpErr.value = null
    return
  }
  try {
    cmp.value = await api.compare(basket.value, win.value)
    cmpErr.value = null
  } catch (e) {
    cmpErr.value = e instanceof Error ? e.message : String(e)
    cmp.value = null
  }
}

function select(sym: string): void {
  const s = cleanTicker(sym)
  if (!s) return
  symbol.value = s
  q.value = s
  void router.replace({ query: { ...route.query, symbol: s } })
}

function onSearchKey(e: KeyboardEvent): void {
  if (e.key === 'Enter') {
    e.preventDefault()
    const typed = cleanTicker(q.value)
    if (typed) select(typed)
  }
}

function toggleBasket(sym: string): void {
  const i = basket.value.indexOf(sym)
  if (i >= 0) basket.value.splice(i, 1)
  else if (basket.value.length < 8) basket.value.push(sym)
  void loadCompare()
}

watch([symbol, win], () => void loadTrajectory())
watch(win, () => void loadCompare())
onMounted(() => {
  void loadTrajectory()
  runSearch('')
})

const s = computed(() => traj.value?.stats)

/** Data availability & integrity status computation */
const dataAudit = computed(() => {
  if (!traj.value) return null
  const lastDate = traj.value.last_date
  const firstDate = traj.value.first_date
  const nBars = traj.value.n_bars
  const source = traj.value.source
  const advUsd = s.value?.adv_20_usd
  const isFresh = Boolean(lastDate && (lastDate.startsWith('2026-07') || lastDate.startsWith('2026-08')))
  return {
    lastDate,
    firstDate,
    nBars,
    source,
    advUsd,
    isFresh,
  }
})

/** Real desk signal only — never invent a ~54% "confidence". */
const signalBranch = computed(() => {
  const sym = symbol.value?.toUpperCase()
  if (!sym) return null

  const dSignals = (status?.data?.value?.directional_signals ?? []) as any[]
  const peadCandidates = (status?.data?.value?.pead_candidates ?? []) as any[]

  const sig = dSignals.find((s) => s.symbol?.toUpperCase() === sym)
  const pead = peadCandidates.find((p) => p.symbol?.toUpperCase() === sym)

  if (sig) {
    const prob = sig.probability
    return {
      type: 'Directional Signal',
      side: (sig.side || 'LONG').toUpperCase(),
      prob: typeof prob === 'number' && Number.isFinite(prob) ? prob : null,
      state: sig.state || 'WATCH',
      horizon: sig.horizon || '5d',
      momentum: sig.momentum ?? 0,
      model: sig.model || 'XS3 LightGBM',
    }
  }

  if (pead) {
    const prob = pead.model?.probability
    return {
      type: 'PEAD Gap Setup',
      side: (pead.side || 'LONG').toUpperCase(),
      prob: typeof prob === 'number' && Number.isFinite(prob) ? prob : null,
      state: pead.model?.state || 'FLAG',
      horizon: `${pead.model?.horizon_days ?? 20}d`,
      model: pead.model?.id || 'PEAD Catalyst',
    }
  }

  return null
})

/** Every compare curve as a sparkline path, sized to the legend row. */
const cmpSparks = computed(() => {
  const out: Record<string, string> = {}
  if (!cmp.value) return out
  for (const [sym, rows] of Object.entries(cmp.value.series)) {
    if (rows && rows.length > 0) {
      out[sym] = sparkline(rows.map((r) => r.cum), 120, 22, 2).d
    }
  }
  return out
})

const cmpSyms = computed(() => (cmp.value ? Object.keys(cmp.value.series) : []))

/** Correlation cell tint: 1.0 hot, 0 neutral, negative cool. */
function corrStyle(r: number): Record<string, string> {
  if (!Number.isFinite(r)) return {}
  const pct = Math.min(1, Math.abs(r)) * 55
  const hue = r >= 0 ? 'short' : 'long'
  return { background: `color-mix(in srgb, var(--${hue}) ${pct.toFixed(1)}%, transparent)` }
}

const factorRows = computed(() => {
  const f = traj.value?.factors ?? {}
  return [
    {
      k: 'rev1',
      label: '1D Reversal',
      desc: 'Short-term 1-day return reversal (-1 × ret1)',
      v: f.rev1,
      formatted: f.rev1 == null ? DASH : signedPct(f.rev1 * 100, 2),
      barPct: Math.min(100, Math.abs(Number(f.rev1 ?? 0)) * 500),
      toneClass: tone(f.rev1),
    },
    {
      k: 'rev5',
      label: '5D Reversal',
      desc: 'Weekly 5-day return reversal (-1 × ret5)',
      v: f.rev5,
      formatted: f.rev5 == null ? DASH : signedPct(f.rev5 * 100, 2),
      barPct: Math.min(100, Math.abs(Number(f.rev5 ?? 0)) * 200),
      toneClass: tone(f.rev5),
    },
    {
      k: 'mom12_1',
      label: '12-1M Momentum',
      desc: '12-month momentum (excl. recent month)',
      v: f.mom12_1,
      formatted: f.mom12_1 == null ? DASH : signedPct(f.mom12_1 * 100, 2),
      barPct: Math.min(100, Math.abs(Number(f.mom12_1 ?? 0)) * 100),
      toneClass: tone(f.mom12_1),
    },
    {
      k: 'lowvol',
      label: 'Low Volatility',
      desc: '20-day return volatility suppression',
      v: f.lowvol,
      formatted: f.lowvol == null ? DASH : num(f.lowvol, 4),
      barPct: Math.min(100, Math.abs(Number(f.lowvol ?? 0)) * 2000),
      toneClass: tone(f.lowvol),
    },
    {
      k: 'liq',
      label: 'Liquidity Index',
      desc: '20-day log dollar volume scale',
      v: f.liq,
      formatted: f.liq == null ? DASH : `${num(f.liq, 2)} log$`,
      sub: f.adv20_usd ? compact(f.adv20_usd) : undefined,
      barPct: Math.min(100, Math.max(0, (Number(f.liq ?? 0) / 12) * 100)),
      toneClass: 'pos',
    },
  ]
})
</script>

<template>
  <div class="market">
    <!-- ── search column ────────────────────────────────────────────────── -->
    <Panel label="Symbol search" index="02" :meta="`${hits.length} shown`" class="col-search" flush>
      <div class="find">
        <span class="glyph" aria-hidden="true">⌕</span>
        <input
          v-model="q"
          class="q"
          type="text"
          placeholder="Ticker (case-insensitive)"
          spellcheck="false"
          autocomplete="off"
          @keydown="onSearchKey"
        />
        <span v-if="searching" class="label busy">···</span>
      </div>

      <ul class="hits">
        <li
          v-for="h in hits"
          :key="h.symbol + String(h.n_bars)"
          class="hit"
          :class="{ on: h.symbol === symbol, free: !h.n_bars }"
          @click="select(h.symbol)"
        >
          <span class="h-sym fig">{{ h.symbol }}</span>
          <span class="h-span label">
            <template v-if="h.n_bars">{{ shortDate(h.first_date) }} → {{ shortDate(h.last_date) }}</template>
            <template v-else>not in local cache</template>
          </span>
          <button
            class="h-add label"
            :class="{ in: basket.includes(h.symbol) }"
            :title="basket.includes(h.symbol) ? 'Remove from basket' : 'Add to compare basket'"
            :disabled="!h.n_bars"
            @click.stop="toggleBasket(h.symbol)"
          >
            {{ basket.includes(h.symbol) ? '−' : '+' }}
          </button>
        </li>
        <li v-if="!hits.length && !searching" class="empty label">Type a ticker and press Enter</li>
      </ul>
    </Panel>

    <!-- ── trajectory ───────────────────────────────────────────────────── -->
    <Panel
      :label="`${symbol} trajectory`"
      index="—"
      :meta="traj ? `${traj.n_bars} bars · ${traj.source}` : ''"
      :delay="60"
      class="col-traj"
    >
      <template #action>
        <div class="switches">
          <button
            type="button"
            class="mkt-refresh-btn label"
            :disabled="trajBusy"
            title="Run live scan and reload trajectory"
            @click="loadTrajectory"
          >
            <span class="refresh-icon" :class="{ spinning: trajBusy }">↻</span>
            {{ trajBusy ? 'SCANNING…' : 'RUN LIVE SCAN' }}
          </button>

          <div class="seg">
            <button
              v-for="m in (['price', 'growth'] as const)"
              :key="m"
              class="seg-b label"
              :class="{ on: mode === m }"
              @click="mode = m"
            >
              {{ m }}
            </button>
          </div>
          <div v-if="mode === 'price'" class="seg">
            <button
              class="seg-b label"
              :class="{ on: chartStyle === 'candles' }"
              @click="chartStyle = 'candles'"
            >
              candles
            </button>
            <button
              class="seg-b label"
              :class="{ on: chartStyle === 'line' }"
              @click="chartStyle = 'line'"
            >
              line
            </button>
          </div>
          <div class="seg">
            <button
              v-for="w in WINDOWS"
              :key="w"
              class="seg-b label"
              :class="{ on: win === w }"
              @click="win = w"
            >
              {{ w }}
            </button>
          </div>
        </div>
      </template>

      <!-- Data Availability Audit Bar -->
      <div v-if="dataAudit" class="data-audit-strip label">
        <span class="audit-item">
          <b class="audit-dot" :class="dataAudit.isFresh ? 'fresh' : 'stale'" />
          {{ dataAudit.isFresh ? 'DATA AS OF' : 'HISTORICAL AS OF' }} {{ shortDate(dataAudit.lastDate) }}
        </span>
        <span class="audit-item dim">{{ dataAudit.nBars }} bars ({{ shortDate(dataAudit.firstDate) }} → {{ shortDate(dataAudit.lastDate) }})</span>
        <span class="audit-item source-badge">{{ dataAudit.source.toUpperCase() }} TIER</span>
        <span v-if="dataAudit.advUsd" class="audit-item dim">ADV: {{ compact(dataAudit.advUsd) }}</span>

        <div class="desk-quick-nav label">
          <span class="nav-tag">VIEW IN:</span>
          <RouterLink :to="{ name: 'options', query: { symbol } }" class="nav-qlink">Options</RouterLink>
          <RouterLink :to="{ name: 'changepoints', query: { symbol } }" class="nav-qlink">Breaks</RouterLink>
          <RouterLink :to="{ name: 'sentiment', query: { symbol } }" class="nav-qlink">Pulse</RouterLink>
          <RouterLink :to="{ name: 'momentum', query: { symbol } }" class="nav-qlink">Momentum</RouterLink>
        </div>
      </div>

      <p v-if="trajErr" class="err">{{ trajErr }}</p>
      <p v-else-if="trajBusy && !traj" class="wait label">Loading trace…</p>

      <template v-else-if="traj">
        <div class="hero">
          <Readout
            label="Last"
            :value="usd(s?.last_price)"
            size="lg"
            :tone="tone(s?.chg_1d_pct)"
            :sub="`as of ${shortDate(traj.last_date)}`"
          />
          <div class="chgs">
            <Readout label="1D" :value="signedPct(s?.chg_1d_pct)" :tone="tone(s?.chg_1d_pct)" size="sm" />
            <Readout label="5D" :value="signedPct(s?.chg_5d_pct)" :tone="tone(s?.chg_5d_pct)" size="sm" />
            <Readout label="1M" :value="signedPct(s?.chg_1m_pct)" :tone="tone(s?.chg_1m_pct)" size="sm" />
            <Readout label="3M" :value="signedPct(s?.chg_3m_pct)" :tone="tone(s?.chg_3m_pct)" size="sm" />
            <Readout label="YTD" :value="signedPct(s?.chg_ytd_pct)" :tone="tone(s?.chg_ytd_pct)" size="sm" />
            <Readout label="Window" :value="signedPct(s?.chg_window_pct)" :tone="tone(s?.chg_window_pct)" size="sm" />
          </div>
        </div>

        <!-- Qlib cross-sectional research context (same scorer as deep scan). -->
        <div class="qlib-strip label" :class="{ missing: (traj.qlib_quality || traj.qlib?.quality) === 'missing' }">
          <span class="qlib-k">QLIB XS</span>
          <template v-if="traj.qlib_quality === 'ok' || traj.qlib?.quality === 'ok'">
            <span class="qlib-v fig">score {{ traj.qlib_score != null ? num(traj.qlib_score, 3) : DASH }}</span>
            <span class="qlib-v fig">rank {{ traj.qlib_rank != null ? traj.qlib_rank : DASH }}</span>
            <span class="qlib-v dim">asof {{ shortDate(traj.qlib_asof || traj.qlib?.asof || '') }}</span>
            <span class="qlib-v dim">{{ traj.qlib_source || traj.qlib?.source || 'qlib' }}</span>
            <span class="qlib-v dim">{{ traj.qlib_score_kind || traj.qlib?.score_kind || 'ordinal_qlib_xs' }} · research only</span>
          </template>
          <template v-else>
            <span class="qlib-v dim">unavailable — no fabricated rank</span>
            <span v-if="traj.qlib_source || traj.qlib?.source" class="qlib-v dim">{{ traj.qlib_source || traj.qlib?.source }}</span>
          </template>
        </div>

        <div v-if="signalBranch" class="signal-branch">
          <div class="sig-title-row">
            <span class="label sig-type">{{ signalBranch.type }}</span>
            <span class="sig-side-badge" :class="signalBranch.side.includes('LONG') ? 'pos' : 'neg'">
              {{ signalBranch.side }}
            </span>
            <span class="state label" :class="signalBranch.state === 'ENTER' ? 'enter' : 'watch'">
              {{ signalBranch.state }}
            </span>
          </div>
          <div class="sig-metrics">
            <Readout
              label="Edge"
              :value="signalBranch.prob != null ? pctFrac(signalBranch.prob, 1) : DASH"
              :tone="signalBranch.prob != null && signalBranch.prob >= 0.55 ? 'pos' : signalBranch.prob != null ? 'flat' : 'flat'"
              size="sm"
              :sub="signalBranch.prob != null && signalBranch.prob < 0.55 ? 'BELOW 55% ENTER BAR' : undefined"
            />
            <Readout label="Horizon" :value="signalBranch.horizon" size="sm" />
            <Readout label="Model" :value="signalBranch.model" size="sm" />
            <Readout v-if="signalBranch.momentum !== undefined" label="Momentum" :value="signedPct(signalBranch.momentum, 2)" :tone="tone(signalBranch.momentum)" size="sm" />
          </div>
        </div>

        <TrajectoryChart
          :series="traj.series"
          :symbol="traj.symbol"
          :mode="mode"
          :render-as="mode === 'price' ? chartStyle : 'line'"
          :height="360"
        />

        <div class="stats">
          <Readout label="Ann. return" :value="pct(s?.ann_return_pct)" :tone="tone(s?.ann_return_pct)" size="sm" />
          <Readout label="Ann. vol" :value="pct(s?.ann_vol_pct)" size="sm" />
          <Readout label="Sharpe" :value="s?.sharpe == null ? DASH : num(s.sharpe, 2)" :tone="tone(s?.sharpe)" size="sm" />
          <Readout label="Max DD" :value="pct(s?.max_drawdown_pct)" tone="neg" size="sm" />
          <Readout label="Calmar" :value="s?.calmar == null ? DASH : num(s.calmar, 2)" size="sm" />
          <Readout label="ATR 20" :value="num(s?.atr_20)" :sub="pct(s?.atr_pct, 1)" size="sm" />
          <Readout label="ADV 20" :value="compact(s?.adv_20_usd)" sub="usd" size="sm" />
          <Readout label="Best day" :value="signedPct(s?.best_day_pct)" tone="pos" size="sm" />
          <Readout label="Worst day" :value="signedPct(s?.worst_day_pct)" tone="neg" size="sm" />
          <Readout label="Days up" :value="pct(s?.pct_days_up, 1)" size="sm" />
        </div>
      </template>
    </Panel>

    <!-- ── factors ──────────────────────────────────────────────────────── -->
    <Panel label="Factor Loadings" index="—" meta="factor_probe.py" :delay="120" class="col-fac">
      <p class="note">
        Cross-sectional factors registered in <code>factor_probe.py</code> evaluated at the latest bar.
      </p>

      <ul class="facs">
        <li v-for="f in factorRows" :key="f.k" class="fac">
          <div class="f-top">
            <span class="label f-lab" :title="f.desc">{{ f.label }}</span>
            <div class="f-val-wrap">
              <span class="fig f-val" :class="f.toneClass">{{ f.formatted }}</span>
              <span v-if="f.sub" class="f-sub label">{{ f.sub }}</span>
            </div>
          </div>
          <span class="f-bar" aria-hidden="true">
            <i
              :style="{
                width: `${f.barPct}%`,
                background: f.k === 'liq' ? 'var(--phosphor)' : (Number(f.v ?? 0) >= 0 ? 'var(--long)' : 'var(--short)'),
              }"
            />
          </span>
        </li>
      </ul>
    </Panel>

    <!-- ── compare basket ───────────────────────────────────────────────── -->
    <Panel
      label="Compare Basket"
      index="—"
      :meta="basket.length ? `${basket.length}/8 · rebased` : 'add 2+ symbols'"
      :delay="180"
      class="col-cmp"
    >
      <p v-if="cmpErr" class="err">{{ cmpErr }}</p>
      <p v-else-if="basket.length < 2" class="note">
        Add symbols with <strong>+</strong> in search. Curves rebase to 1.00 for like-for-like correlation comparison.
      </p>

      <template v-else-if="cmp">
        <ul class="legend">
          <li v-for="sym in cmpSyms" :key="sym" class="leg">
            <button class="leg-sym fig" @click="select(sym)">{{ sym }}</button>
            <svg class="spark" viewBox="0 0 120 22" preserveAspectRatio="none" aria-hidden="true">
              <path
                v-if="cmpSparks[sym]"
                :d="cmpSparks[sym]"
                fill="none"
                stroke-width="1.25"
                vector-effect="non-scaling-stroke"
                :stroke="(cmp.stats[sym]?.chg_window_pct ?? 0) >= 0 ? 'var(--long)' : 'var(--short)'"
              />
            </svg>
            <span class="fig leg-ret" :class="tone(cmp.stats[sym]?.chg_window_pct)">
              {{ signedPct(cmp.stats[sym]?.chg_window_pct, 1) }}
            </span>
            <span class="fig leg-sh">{{ cmp.stats[sym]?.sharpe == null ? DASH : num(cmp.stats[sym]?.sharpe, 2) }}</span>
            <span class="fig leg-dd neg">{{ pct(cmp.stats[sym]?.max_drawdown_pct, 0) }}</span>
            <button class="leg-x label" title="Remove" @click="toggleBasket(sym)">×</button>
          </li>
        </ul>
        <div class="leg-head label">
          <span>symbol</span><span>trace</span><span>window</span><span>sharpe</span><span>max dd</span><span />
        </div>

        <h3 class="sub-lab label">Return Correlation</h3>
        <div class="corr" :style="{ '--n': cmpSyms.length }">
          <span />
          <span v-for="c in cmpSyms" :key="`ch${c}`" class="label corr-h">{{ c }}</span>
          <template v-for="r in cmpSyms" :key="`row${r}`">
            <span class="label corr-h">{{ r }}</span>
            <span
              v-for="c in cmpSyms"
              :key="`${r}-${c}`"
              class="fig corr-c"
              :style="corrStyle(cmp.correlation[r]?.[c] ?? NaN)"
            >
              {{ num(cmp.correlation[r]?.[c], 2) }}
            </span>
          </template>
        </div>
        <p class="note tiny">
          Red indicates co-movement, green indicates divergence/offset.
        </p>
      </template>
    </Panel>
  </div>
</template>

<style scoped>
.market {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr) 300px;
  grid-template-rows: auto auto;
  grid-template-areas:
    'search traj fac'
    'search traj cmp';
  gap: var(--s4);
  align-items: start;
}

.col-search {
  grid-area: search;
  position: sticky;
  top: 0;
  max-height: calc(100vh - var(--strip-h) - var(--s7));
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.col-traj { grid-area: traj; }
.col-fac { grid-area: fac; }
.col-cmp { grid-area: cmp; }

/* ---- Data Audit Strip --------------------------------------------------- */
.data-audit-strip {
  display: flex;
  align-items: center;
  gap: var(--s4);
  flex-wrap: wrap;
  padding: var(--s2) var(--s4);
  margin-bottom: var(--s3);
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  border-radius: 3px;
  font-size: var(--t-tiny, 11px);
}
.qlib-strip {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
  margin-top: var(--s3);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--rule);
  border-radius: 2px;
  background: color-mix(in srgb, var(--phosphor-wash, transparent) 35%, transparent);
  font-size: var(--t-tiny, 11px);
}
.qlib-strip.missing {
  background: transparent;
  opacity: 0.85;
}
.qlib-k {
  font-weight: 800;
  letter-spacing: 0.08em;
  color: var(--phosphor, var(--ink));
}
.qlib-v { color: var(--ink); }
.qlib-v.dim { color: var(--ink-dim); }
.audit-item {
  display: flex;
  align-items: center;
  gap: var(--s2);
  color: var(--ink);
}
.audit-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.audit-dot.fresh {
  background: var(--phosphor);
}
.audit-dot.stale {
  background: var(--warn);
}
.source-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  background: var(--phosphor-wash);
  color: var(--phosphor);
  border-radius: 2px;
}

/* ---- search -------------------------------------------------------------- */
.find {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: var(--s2) var(--s4) var(--s3);
  border-bottom: var(--hair) solid var(--rule);
}
.glyph { color: var(--phosphor); }
.q { flex: 1 1 auto; font-family: var(--font-data); font-size: var(--t-small); color: var(--ink); min-width: 0; }
.q::placeholder { color: var(--ink-dim); }
.q:focus-visible { outline: none; }
.busy { color: var(--phosphor); }

.hits {
  list-style: none;
  max-height: calc(100vh - 220px);
  overflow-y: auto;
  scrollbar-width: thin;
}
.hit {
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-areas: 'sym add' 'span add';
  gap: 2px var(--s2);
  padding: var(--s3) var(--s4);
  cursor: pointer;
  border-left: 2px solid transparent;
  transition: background var(--dur-fast) var(--ease-out);
}
.hit:hover { background: var(--panel-raise); }
.hit.on { background: var(--phosphor-wash); border-left-color: var(--phosphor); }
.hit.free .h-sym { color: var(--ink-dim); }
.hit.free .h-span { color: var(--warn); }
.h-sym { grid-area: sym; font-size: var(--t-small); font-weight: 700; color: var(--ink); }
.hit.on .h-sym { color: var(--phosphor); }
.h-span { grid-area: span; color: var(--ink-dim); font-size: var(--t-micro); }
.h-add {
  grid-area: add;
  align-self: center;
  width: 22px; height: 22px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
  font-size: var(--t-small);
  font-weight: 700;
  line-height: 1;
}
.h-add:hover { color: var(--phosphor); border-color: var(--phosphor); background: var(--phosphor-wash); }
.h-add.in { color: var(--phosphor); border-color: var(--phosphor); background: var(--phosphor-wash); }

.mkt-refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 9px;
  height: 24px;
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-micro);
  letter-spacing: 0.05em;
  color: var(--phosphor);
  background: var(--phosphor-wash);
  border: var(--hair) solid var(--phosphor-dim);
  border-radius: 2px;
  cursor: pointer;
  transition: all 0.12s ease;
}
.mkt-refresh-btn:hover:not(:disabled) {
  background: var(--phosphor);
  color: var(--void);
}
.mkt-refresh-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}
.refresh-icon {
  display: inline-block;
  font-size: 0.85rem;
  line-height: 1;
}
.refresh-icon.spinning {
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.desk-quick-nav {
  display: flex;
  align-items: center;
  gap: var(--s2);
  margin-left: auto;
}
.nav-tag { color: var(--ink-ghost); font-size: 9px; }
.nav-qlink {
  display: inline-block;
  padding: 1px 6px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
  font-size: 10px;
  text-decoration: none;
  transition: all 0.12s ease;
}
.nav-qlink:hover {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

/* ---- switches ------------------------------------------------------------ */
.switches { display: flex; align-items: center; gap: var(--s3); flex: 0 0 auto; }
.seg { display: flex; border: var(--hair) solid var(--rule); border-radius: 2px; overflow: hidden; }
.seg-b {
  padding: 4px 9px;
  color: var(--ink-dim);
  font-weight: 600;
  border-right: var(--hair) solid var(--rule);
  transition: color var(--dur-fast), background var(--dur-fast);
}
.seg-b:last-child { border-right: none; }
.seg-b:hover { color: var(--ink); background: var(--panel-hi); }
.seg-b.on { color: var(--void); background: var(--phosphor); font-weight: 700; }

/* ---- hero ---------------------------------------------------------------- */
.hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s5);
  flex-wrap: wrap;
  padding-bottom: var(--s4);
  margin-bottom: var(--s3);
  border-bottom: var(--hair) solid var(--rule);
}
.chgs { display: flex; gap: var(--s5); flex-wrap: wrap; }

.signal-branch {
  margin-bottom: var(--s4);
  padding: var(--s3) var(--s4);
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  border-radius: 2px;
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.sig-title-row {
  display: flex;
  align-items: center;
  gap: var(--s3);
}

.sig-type { color: var(--ink); font-weight: 700; font-size: var(--t-micro); letter-spacing: 0.08em; }
.sig-side-badge {
  font-family: var(--font-display);
  font-size: var(--t-small);
  font-weight: 800;
  padding: 3px 10px;
  border-radius: 2px;
  letter-spacing: 0.06em;
}
.sig-side-badge.pos { color: var(--long); background: var(--long-wash); border: var(--hair) solid var(--long); }
.sig-side-badge.neg { color: var(--short); background: var(--short-wash); border: var(--hair) solid var(--short); }

.sig-metrics {
  display: flex;
  gap: var(--s6);
  flex-wrap: wrap;
}

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(94px, 1fr));
  gap: var(--s4) var(--s3);
  margin-top: var(--s4);
  padding-top: var(--s4);
  border-top: var(--hair) solid var(--rule);
}

/* ---- factors ------------------------------------------------------------- */
.facs { list-style: none; display: flex; flex-direction: column; gap: var(--s3); margin-top: var(--s3); }
.fac { display: flex; flex-direction: column; gap: 4px; }
.f-top { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s2); }
.f-lab { color: var(--ink); font-weight: 600; }
.f-val-wrap { display: flex; align-items: baseline; gap: var(--s2); }
.f-val { font-size: var(--t-small); font-weight: 600; }
.f-sub { font-size: 10px; color: var(--ink-dim); }
.f-bar {
  height: 4px;
  background: var(--rule);
  display: block;
  border-radius: 2px;
  overflow: hidden;
}
.f-bar i { display: block; height: 100%; border-radius: 2px; transition: width var(--dur-normal) var(--ease-out); }

/* ---- compare ------------------------------------------------------------- */
.legend { list-style: none; display: flex; flex-direction: column; gap: 2px; margin-top: var(--s2); }
.leg, .leg-head {
  display: grid;
  grid-template-columns: 5.5ch 1fr 5.5ch 4ch 5ch 1.2rem;
  align-items: center;
  gap: var(--s2);
}
.leg { padding: var(--s2) 0; border-bottom: var(--hair) solid var(--rule-faint); }
.leg-head { padding-top: var(--s2); padding-bottom: var(--s1); color: var(--ink-dim); font-weight: 700; border-bottom: var(--hair) solid var(--rule); order: 1; }
.leg-sym { font-size: var(--t-small); font-weight: 700; text-align: left; color: var(--phosphor); }
.leg-sym:hover { color: var(--ink); }
.spark { width: 100%; height: 22px; display: block; }
.leg-ret, .leg-sh, .leg-dd { font-size: var(--t-tiny); text-align: right; font-weight: 600; }
.leg-sh { color: var(--ink-dim); }
.leg-x { color: var(--ink-dim); font-weight: 700; }
.leg-x:hover { color: var(--short); }

.sub-lab { display: block; margin: var(--s5) 0 var(--s2); color: var(--ink); font-weight: 700; }

.corr {
  display: grid;
  grid-template-columns: 4.5ch repeat(var(--n), minmax(0, 1fr));
  gap: 2px;
}
.corr-h { color: var(--ink-dim); font-weight: 700; align-self: center; font-size: var(--t-micro); text-align: center; }
.corr-c {
  font-size: var(--t-micro);
  font-weight: 600;
  text-align: center;
  padding: 5px 3px;
  background: var(--panel-hi);
  color: var(--ink);
}

/* ---- shared -------------------------------------------------------------- */
.note { color: var(--ink-dim); font-size: var(--t-small); line-height: 1.55; }
.note.tiny { font-size: var(--t-tiny); margin-top: var(--s3); color: var(--ink-dim); }
.note code { font-family: var(--font-data); color: var(--phosphor); }
.err { color: var(--short); font-size: var(--t-small); padding: var(--s4) 0; }
.wait { color: var(--ink-dim); padding: var(--s6) 0; text-align: center; }
.empty { padding: var(--s5); text-align: center; color: var(--ink-dim); }

@media (max-width: 1280px) {
  .market {
    grid-template-columns: 230px minmax(0, 1fr);
    grid-template-areas: 'search traj' 'search fac' 'search cmp';
  }
}
@media (max-width: 860px) {
  .market { grid-template-columns: 1fr; grid-template-areas: 'search' 'traj' 'fac' 'cmp'; }
  .col-search { position: static; max-height: 320px; }
  .hits { max-height: 220px; }
}
</style>
