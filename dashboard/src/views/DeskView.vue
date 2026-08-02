<script setup lang="ts">
import { computed, inject, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, type StatusPayload, type Readiness, type Trajectory } from '@/api'
import type { Resource } from '@/composables/useResource'
import { num, pctFrac, signedPct, tone, usd, DASH } from '@/format'
import Panel from '@/components/Panel.vue'
import VerdictChip from '@/components/VerdictChip.vue'

/**
 * The Desk View.
 *
 * Provides a high-density, command-center dashboard for live-capital interlocks,
 * PEAD pre-market setups, directional trading signals, and custom ticker probing.
 */
const status = inject<Resource<StatusPayload>>('status')!
const readiness = inject<Resource<Readiness>>('readiness')!
const router = useRouter()

const scanningPead = ref(false)
const scanningSig = ref(false)
const scanMsg = ref<string | null>(null)

// Filtering state for dropdowns
const peadFilter = ref<'all' | 'entered' | 'long' | 'short'>('all')
const signalFilter = ref<'all' | 'entered' | 'long' | 'short'>('all')

// Custom Watchlist & Ad-hoc probe
const customTickerInput = ref('')
const probing = ref(false)
const probeErr = ref<string | null>(null)
const customWatchlist = ref<string[]>(['NVDA', 'TSLA', 'AMD'])
const probeResults = ref<Record<string, Trajectory | null>>({})

onMounted(() => {
  try {
    const saved = localStorage.getItem('edge_custom_watchlist')
    if (saved) {
      const parsed = JSON.parse(saved)
      if (Array.isArray(parsed) && parsed.length > 0) {
        customWatchlist.value = parsed.map((s) => String(s).toUpperCase())
      }
    }
  } catch {
    /* fallback to default */
  }
  // Probe initial watchlist symbols
  void probeWatchlist()
})

function saveWatchlist(): void {
  try {
    localStorage.setItem('edge_custom_watchlist', JSON.stringify(customWatchlist.value))
  } catch {
    /* ignore storage errors */
  }
}

async function probeSymbol(sym: string): Promise<void> {
  const clean = sym.trim().toUpperCase()
  if (!clean) return
  probing.value = true
  probeErr.value = null
  try {
    const t = await api.trajectory(clean, '1m')
    probeResults.value[clean] = t
    if (!customWatchlist.value.includes(clean)) {
      customWatchlist.value.push(clean)
      saveWatchlist()
    }
    customTickerInput.value = ''
  } catch (e) {
    probeErr.value = e instanceof Error ? e.message : String(e)
  } finally {
    probing.value = false
  }
}

async function probeWatchlist(): Promise<void> {
  for (const sym of customWatchlist.value) {
    try {
      if (!probeResults.value[sym]) {
        probeResults.value[sym] = await api.trajectory(sym, '1m')
      }
    } catch {
      /* ignore individual ticker probe error */
    }
  }
}

function removeWatchlistSymbol(sym: string): void {
  const idx = customWatchlist.value.indexOf(sym)
  if (idx >= 0) {
    customWatchlist.value.splice(idx, 1)
    delete probeResults.value[sym]
    saveWatchlist()
  }
}

async function rescanPead(): Promise<void> {
  scanningPead.value = true
  scanMsg.value = null
  try {
    scanMsg.value = (await api.triggerScan()).message
    await status.refresh()
  } catch (e) {
    scanMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    scanningPead.value = false
  }
}

async function rescanSignals(): Promise<void> {
  scanningSig.value = true
  scanMsg.value = null
  try {
    scanMsg.value = (await api.triggerScan()).message
    await status.refresh()
  } catch (e) {
    scanMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    scanningSig.value = false
  }
}

const r = computed(() => readiness.data.value)
const d = computed(() => status.data.value)

/* ---- typed narrowings --------------------------------------------------- */

interface PeadRow {
  symbol: string
  side: string
  setup_ok: boolean
  model: {
    probability: number
    state: string
    horizon_days: number
    entry_threshold: number
    id: string
    promotion_authorized: boolean
  }
}
interface SignalRow {
  symbol: string
  side: string
  model: string
  horizon: string
  probability: number
  state: string
  momentum: number
}
interface BoardRow {
  gate_file: string
  strategy: string
  features: string
  rank_ic: string
  net_return: string
  sharpe: string
  verdict: string
  validation_status: string
}

const pead = computed(() => (d.value?.pead_candidates ?? []) as unknown as PeadRow[])
const signals = computed(() => (d.value?.directional_signals ?? []) as unknown as SignalRow[])
const board = computed(() => (d.value?.leaderboard ?? []) as unknown as BoardRow[])
const sectors = computed(() => (d.value?.sector_flow as any)?.sectors_ranked ?? [])

/* Filtering computed properties */
const peadEntered = computed(() => pead.value.filter((p) => p.model?.state === 'ENTER').length)
const sigEntered = computed(() => signals.value.filter((s) => s.state === 'ENTER').length)

const filteredPead = computed(() => {
  return pead.value.filter((p) => {
    if (peadFilter.value === 'entered') return p.model?.state === 'ENTER'
    if (peadFilter.value === 'long') return p.side?.toLowerCase() === 'long'
    if (peadFilter.value === 'short') return p.side?.toLowerCase() === 'short'
    return true
  })
})

const filteredSignals = computed(() => {
  return signals.value.filter((s) => {
    if (signalFilter.value === 'entered') return s.state === 'ENTER'
    if (signalFilter.value === 'long') return s.side?.toLowerCase() === 'long'
    if (signalFilter.value === 'short') return s.side?.toLowerCase() === 'short'
    return true
  })
})

/* Top summary stats */
const topSector = computed(() => {
  if (!sectors.value.length) return null
  return [...sectors.value].sort((a: any, b: any) => b.flow_score - a.flow_score)[0]
})

const topStrategy = computed(() => {
  if (!board.value.length) return null
  return board.value.find((b) => b.verdict === 'GO') ?? board.value[0]
})

function open(sym: string | undefined): void {
  if (sym) void router.push({ name: 'market', query: { symbol: sym } })
}

function navTo(name: string): void {
  void router.push({ name })
}
</script>

<template>
  <div class="desk">
    <!-- ── 00 Summary KPI Deck ─────────────────────────────────────────── -->
    <div class="desk-summary">
      <div class="kpi-card" :class="r?.cleared_for_live ? 'armed' : 'held'">
        <span class="label kpi-label">Capital Status</span>
        <div class="kpi-val-row">
          <span class="kpi-val">{{ r?.cleared_for_live ? 'ARMED' : 'HELD' }}</span>
          <span class="kpi-badge" :class="r?.cleared_for_live ? 'armed' : 'held'">
            {{ r?.cleared_for_live ? 'LIVE READY' : 'PAPER TRADING' }}
          </span>
        </div>
        <span class="kpi-sub">
          {{ r?.blocking_reasons?.length ? `${r.blocking_reasons.length} blocker(s) active` : '0 blockers recorded' }}
        </span>
      </div>

      <div class="kpi-card">
        <span class="label kpi-label">Actionable Setups</span>
        <div class="kpi-val-row">
          <span class="kpi-val fig pos">{{ peadEntered + sigEntered }}</span>
          <span class="kpi-badge enter">ENTER SIGNAL</span>
        </div>
        <span class="kpi-sub">
          {{ peadEntered }} PEAD · {{ sigEntered }} Directional
        </span>
      </div>

      <div class="kpi-card">
        <span class="label kpi-label">Total Signals Scanned</span>
        <div class="kpi-val-row">
          <span class="kpi-val fig">{{ signals.length + pead.length }}</span>
          <span class="kpi-badge flat">ACTIVE SCAN</span>
        </div>
        <span class="kpi-sub">
          {{ signals.length }} directional · {{ pead.length }} gap setups
        </span>
      </div>

      <div class="kpi-card clickable" @click="navTo('sectors')">
        <span class="label kpi-label">Top Sector Flow ➔</span>
        <div class="kpi-val-row">
          <span class="kpi-val sym">{{ topSector ? topSector.etf : '—' }}</span>
          <span class="kpi-badge" :class="tone(topSector?.flow_score ?? 0)">
            {{ topSector ? signedPct(topSector.flow_score * 100, 1) : '—' }}
          </span>
        </div>
        <span class="kpi-sub fl-truncate">
          {{ topSector ? topSector.name : 'Sectors tab' }}
        </span>
      </div>

      <div class="kpi-card clickable" @click="navTo('gates')">
        <span class="label kpi-label">Top Alpha Strategy ➔</span>
        <div class="kpi-val-row">
          <span class="kpi-val strat-name">{{ topStrategy ? topStrategy.strategy : '—' }}</span>
          <VerdictChip v-if="topStrategy" :verdict="topStrategy.verdict" size="sm" />
        </div>
        <span class="kpi-sub">
          Net {{ topStrategy?.net_return ?? '—' }} · Sharpe {{ topStrategy?.sharpe ?? '—' }}
        </span>
      </div>
    </div>

    <!-- ── 01 PEAD Pre-Market Setups ────────────────────────────────────── -->
    <Panel
      label="PEAD Pre-Market Setups"
      index="01"
      :meta="`${peadEntered} entered · ${pead.length} scanned`"
      :delay="60"
      flush
      class="w-half"
    >
      <template #action>
        <div class="action-bar">
          <div class="select-wrap">
            <select v-model="peadFilter" class="filter-select label">
              <option value="all">ALL SETUPS ({{ pead.length }})</option>
              <option value="entered">ENTER ONLY ({{ peadEntered }})</option>
              <option value="long">LONG SETUPS</option>
              <option value="short">SHORT SETUPS</option>
            </select>
          </div>
          <button class="act label" :disabled="scanningPead" @click="rescanPead">
            {{ scanningPead ? 'SCANNING…' : 'RESCAN' }}
          </button>
        </div>
      </template>

      <p v-if="scanMsg" class="scan-msg label">{{ scanMsg }}</p>

      <div class="table-container">
        <table v-if="filteredPead.length" class="grid">
          <thead>
            <tr>
              <th class="label">Symbol</th>
              <th class="label">Side</th>
              <th class="label num">Probability</th>
              <th class="label num">Gate</th>
              <th class="label num">Hz</th>
              <th class="label">State</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(c, i) in filteredPead" :key="i" @click="open(c.symbol)">
              <td class="fig sym">{{ c.symbol }}</td>
              <td>
                <span class="side-pill" :class="c.side === 'long' ? 'pos' : 'neg'">
                  {{ (c.side ?? DASH).toUpperCase() }}
                </span>
              </td>
              <td class="fig num" :class="c.model?.probability >= (c.model?.entry_threshold ?? 1) ? 'pos' : ''">
                <div class="prob-cell">
                  <div class="prob-bar-wrap" aria-hidden="true">
                    <div
                      class="prob-bar"
                      :class="c.model?.probability >= (c.model?.entry_threshold ?? 1) ? 'pos' : 'flat'"
                      :style="{ width: `${Math.min(100, Math.max(0, (c.model?.probability ?? 0) * 100))}%` }"
                    />
                  </div>
                  <span>{{ pctFrac(c.model?.probability, 1) }}</span>
                </div>
              </td>
              <td class="fig num dim">{{ pctFrac(c.model?.entry_threshold, 0) }}</td>
              <td class="fig num dim">{{ c.model?.horizon_days ?? DASH }}d</td>
              <td>
                <span class="state label" :class="c.model?.state === 'ENTER' ? 'enter' : 'watch'">
                  {{ c.model?.state ?? DASH }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">
          {{ pead.length === 0 ? 'No gap setups cleared the pre-market filter this session.' : 'No candidates match the selected filter.' }}
        </p>
      </div>
    </Panel>

    <!-- ── 02 Directional Signals ──────────────────────────────────────── -->
    <Panel
      label="Directional Signals"
      index="02"
      :meta="`${sigEntered} entered · ${signals.length} scanned`"
      :delay="120"
      flush
      class="w-half"
    >
      <template #action>
        <div class="action-bar">
          <div class="select-wrap">
            <select v-model="signalFilter" class="filter-select label">
              <option value="all">ALL SIGNALS ({{ signals.length }})</option>
              <option value="entered">ENTER ONLY ({{ sigEntered }})</option>
              <option value="long">LONG SIGNALS</option>
              <option value="short">SHORT SIGNALS</option>
            </select>
          </div>
          <button class="act label" :disabled="scanningSig" @click="rescanSignals">
            {{ scanningSig ? 'SCANNING…' : 'RESCAN' }}
          </button>
        </div>
      </template>

      <div class="table-container">
        <table v-if="filteredSignals.length" class="grid">
          <thead>
            <tr>
              <th class="label">Symbol</th>
              <th class="label">Side</th>
              <th class="label num">Probability</th>
              <th class="label num">Momentum</th>
              <th class="label num">Hz</th>
              <th class="label">State</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(s, i) in filteredSignals" :key="i" @click="open(s.symbol)">
              <td class="fig sym">{{ s.symbol }}</td>
              <td>
                <span class="side-pill" :class="s.side === 'LONG' || s.side === 'long' ? 'pos' : 'neg'">
                  {{ (s.side ?? DASH).toUpperCase() }}
                </span>
              </td>
              <td class="fig num">
                <div class="prob-cell">
                  <div class="prob-bar-wrap" aria-hidden="true">
                    <div
                      class="prob-bar"
                      :class="s.state === 'ENTER' ? 'pos' : 'flat'"
                      :style="{ width: `${Math.min(100, Math.max(0, (s.probability ?? 0) * 100))}%` }"
                    />
                  </div>
                  <span>{{ pctFrac(s.probability, 1) }}</span>
                </div>
              </td>
              <td class="fig num" :class="tone(s.momentum)">{{ signedPct(s.momentum, 2) }}</td>
              <td class="fig num dim">{{ (s.horizon ?? '').replace(' Days', 'd') }}</td>
              <td>
                <span class="state label" :class="s.state === 'ENTER' ? 'enter' : 'watch'">{{ s.state }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">
          {{ signals.length === 0 ? 'No directional signals emitted.' : 'No directional signals match the selected filter.' }}
        </p>
      </div>
    </Panel>

    <!-- ── 03 Custom Stock Watchlist & Ad-Hoc Signal Probe ─────────────── -->
    <Panel label="Custom Watchlist & Ad-Hoc Signal Probe" index="03" meta="Personal watchlist" class="w-full" flush>
      <template #action>
        <div class="probe-input-bar">
          <input
            v-model="customTickerInput"
            type="text"
            placeholder="Add ticker e.g. TSLA, PLTR"
            class="probe-input label"
            @keyup.enter="probeSymbol(customTickerInput)"
          />
          <button class="act label" :disabled="probing || !customTickerInput.trim()" @click="probeSymbol(customTickerInput)">
            {{ probing ? 'PROBING…' : '+ ADD & PROBE' }}
          </button>
          <span class="cost-badge label" title="Local server pandas engine execution is zero cost">
            ⚡ ENGINE: $0.000 / PROBE · ~180ms
          </span>
        </div>
      </template>

      <p v-if="probeErr" class="err pad">{{ probeErr }}</p>

      <div class="table-container">
        <table v-if="customWatchlist.length" class="grid">
          <thead>
            <tr>
              <th class="label">Symbol</th>
              <th class="label num">Last Price</th>
              <th class="label num">1D Change</th>
              <th class="label num">5D Change</th>
              <th class="label num">Sharpe Ratio</th>
              <th class="label num">20D ADV</th>
              <th class="label">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="sym in customWatchlist" :key="sym" @click="open(sym)">
              <td class="fig sym">{{ sym }}</td>
              <td class="fig num">{{ usd(probeResults[sym]?.stats?.last_price) }}</td>
              <td class="fig num" :class="tone(probeResults[sym]?.stats?.chg_1d_pct)">
                {{ signedPct(probeResults[sym]?.stats?.chg_1d_pct) }}
              </td>
              <td class="fig num" :class="tone(probeResults[sym]?.stats?.chg_5d_pct)">
                {{ signedPct(probeResults[sym]?.stats?.chg_5d_pct) }}
              </td>
              <td class="fig num">{{ probeResults[sym]?.stats?.sharpe == null ? DASH : num(probeResults[sym]?.stats?.sharpe, 2) }}</td>
              <td class="fig num dim">{{ probeResults[sym]?.stats?.adv_20_usd ? `$${num(probeResults[sym]!.stats.adv_20_usd / 1e6, 1)}M` : DASH }}</td>
              <td>
                <button class="remove-btn label" title="Remove ticker from personal watchlist" @click.stop="removeWatchlistSymbol(sym)">
                  REMOVE
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="note pad">No custom tickers pinned to your watchlist yet. Type a ticker above to probe and pin.</p>
      </div>
      <p class="note tiny pad-x">
        Personal watchlists are saved locally to your browser. Click any row to view full trajectory and factor loadings in Market View.
      </p>
    </Panel>
  </div>
</template>

<style scoped>
.desk {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s4);
  align-items: start;
}
.w-full { grid-column: 1 / -1; }
.w-half { grid-column: span 2; }

/* ---- 00 Summary KPI Deck ------------------------------------------------ */
.desk-summary {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--s3);
}

.kpi-card {
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--radius-sm, 4px);
  padding: var(--s3) var(--s4);
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  overflow: hidden;
  transition: border-color var(--dur-fast), background var(--dur-fast);
}
.kpi-card:hover {
  border-color: var(--rule-hi);
  background: var(--panel-hi);
}
.kpi-card.clickable { cursor: pointer; }
.kpi-card.armed { border-color: rgba(34, 197, 94, 0.3); }
.kpi-card.held { border-color: rgba(245, 158, 11, 0.3); }

.kpi-label {
  font-size: 10px;
  color: var(--ink-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kpi-val-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
  min-width: 0;
  overflow: hidden;
}

.kpi-val {
  font-family: var(--font-mono);
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1.1;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kpi-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  text-transform: uppercase;
  flex-shrink: 0;
  white-space: nowrap;
}
.kpi-badge.armed, .kpi-badge.pos { color: var(--long); background: rgba(34, 197, 94, 0.12); }
.kpi-badge.held, .kpi-badge.neg { color: var(--short); background: rgba(239, 68, 68, 0.12); }
.kpi-badge.enter { color: var(--phosphor); background: var(--phosphor-wash); }
.kpi-badge.flat { color: var(--ink-dim); background: var(--rule); }

.kpi-sub { font-size: 11px; color: var(--ink-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fl-truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.strat-name { font-size: 0.95rem; min-width: 0; flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ---- 01 Interlock -------------------------------------------------------- */
.interlock { display: flex; align-items: flex-start; gap: var(--s6); flex-wrap: wrap; }
.verdict-block { display: flex; flex-direction: column; gap: 4px; padding-right: var(--s5); }

.verdict-pill { display: flex; align-items: center; gap: var(--s3); }
.big-verdict {
  font-family: var(--font-display);
  font-size: 2.25rem;
  font-weight: 800;
  line-height: 0.95;
  letter-spacing: -0.04em;
}
.held .big-verdict { color: var(--warn); }
.armed .big-verdict { color: var(--phosphor); text-shadow: 0 0 24px var(--phosphor-glow); }

.lamp-dot { width: 10px; height: 10px; border-radius: 50%; }
.armed .lamp-dot { background: var(--phosphor); box-shadow: 0 0 10px var(--phosphor-glow); }
.held .lamp-dot { background: var(--warn); box-shadow: 0 0 8px rgba(245, 158, 11, 0.4); }

.vsub { color: var(--ink-dim); font-size: var(--t-small); }
.gauge-set { display: flex; gap: var(--s5); flex-wrap: wrap; }

.shadow-meter-wrap { margin: var(--s4) 0 var(--s3); }
.shadow-bar { position: relative; height: 6px; background: var(--rule); border-radius: 3px; overflow: hidden; }
.shadow-bar i {
  display: block;
  height: 100%;
  background: var(--phosphor);
  box-shadow: 0 0 10px var(--phosphor-glow);
  transition: width var(--dur-slow) var(--ease-out);
}

.shadow-meter-labels { display: flex; justify-content: space-between; font-size: 10px; color: var(--ink-dim); margin-top: 4px; }
.blocks-wrap { margin-top: var(--s3); border-top: var(--hair) solid var(--rule-faint); padding-top: var(--s3); }
.blocks-header { display: flex; justify-content: space-between; align-items: center; color: var(--ink-dim); font-size: var(--t-tiny); font-weight: 700; margin-bottom: var(--s2); }

.toggle-btn { background: transparent; border: none; color: var(--phosphor); font-size: var(--t-tiny); cursor: pointer; padding: 0; }
.toggle-btn:hover { text-decoration: underline; }

.blocks { list-style: none; display: flex; flex-direction: column; gap: var(--s1); }
.block {
  display: grid;
  grid-template-columns: 2.5ch 1fr;
  gap: var(--s3);
  align-items: baseline;
  padding: var(--s2) 0;
  border-bottom: var(--hair) solid var(--rule-faint);
}
.b-idx { font-size: var(--t-micro); color: var(--warn); font-weight: 700; }
.b-txt { font-size: var(--t-small); color: var(--ink); line-height: 1.4; }

/* ---- Filter Controls & Action Slot -------------------------------------- */
.action-bar { display: flex; align-items: center; gap: var(--s3); }

.select-wrap {
  position: relative;
}

.filter-select {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  color: var(--phosphor);
  font-size: 11px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 3px;
  cursor: pointer;
  outline: none;
}
.filter-select option {
  background: var(--panel);
  color: var(--ink);
}

/* ---- Probe Input Bar ----------------------------------------------------- */
.probe-input-bar {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
}

.probe-input {
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink);
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 3px;
  width: 200px;
}

.cost-badge {
  font-size: 10px;
  color: var(--phosphor);
  background: var(--phosphor-wash);
  padding: 2px 8px;
  border-radius: 3px;
  font-weight: 700;
}

.remove-btn {
  background: transparent;
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 2px;
  cursor: pointer;
}
.remove-btn:hover {
  color: var(--short);
  border-color: var(--short);
}

/* ---- Scrollable Signal Tables ------------------------------------------- */
.table-container {
  max-height: 480px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.grid { width: 100%; border-collapse: collapse; font-size: var(--t-small); }
.grid th {
  text-align: left;
  padding: var(--s3) var(--s4);
  color: var(--ink-dim);
  border-bottom: var(--hair) solid var(--rule);
  position: sticky;
  top: 0;
  background: var(--panel-hi);
  font-weight: 700;
  z-index: 1;
}
.grid td { padding: var(--s2) var(--s4); border-bottom: var(--hair) solid var(--rule-faint); color: var(--ink); vertical-align: middle; }
.grid tbody tr { cursor: pointer; transition: background var(--dur-fast); }
.grid tbody tr:hover { background: var(--panel-raise); }

.num { text-align: right; }
.sym { color: var(--phosphor); font-weight: 700; }
.side-pill { display: inline-block; font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 2px; }
.side-pill.pos { color: var(--long); background: rgba(34, 197, 94, 0.12); }
.side-pill.neg { color: var(--short); background: rgba(239, 68, 68, 0.12); }

.prob-cell { display: flex; align-items: center; justify-content: flex-end; gap: var(--s3); }
.prob-bar-wrap { width: 48px; height: 4px; background: var(--rule); border-radius: 2px; overflow: hidden; }
.prob-bar { height: 100%; border-radius: 2px; }
.prob-bar.pos { background: var(--phosphor); }
.prob-bar.flat { background: var(--ink-dim); opacity: 0.6; }

.dim { color: var(--ink-dim); }
.state { padding: 2px 7px; border: var(--hair) solid currentColor; border-radius: 2px; font-weight: 600; }
.state.enter { color: var(--phosphor); background: var(--phosphor-wash); }
.state.watch { color: var(--ink-dim); border-color: var(--rule-hi); }

.act {
  padding: 3px 10px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink);
  font-weight: 600;
}
.act:hover:not(:disabled) { color: var(--phosphor); border-color: var(--phosphor); background: var(--phosphor-wash); }
.act:disabled { color: var(--ink-dim); cursor: progress; }

.scan-msg { padding: var(--s2) var(--s4); color: var(--phosphor-dim); }
.note { color: var(--ink-dim); font-size: var(--t-small); }
.note.pad { padding: var(--s5) var(--s4); }
.note.pad-x { padding: var(--s3) var(--s4) var(--s4); }
.note.tiny { font-size: 11px; margin-top: var(--s3); }
.err { color: var(--short); font-size: var(--t-small); }
.err.pad { padding: var(--s3) var(--s4); }

@media (max-width: 1400px) {
  .desk-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .desk { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 768px) {
  .desk-summary { grid-template-columns: 1fr; }
  .desk { grid-template-columns: 1fr; }
  .w-half { grid-column: span 1; }
  .action-bar { flex-direction: column; align-items: flex-start; }
}
</style>
