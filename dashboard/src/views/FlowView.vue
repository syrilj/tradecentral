<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type StatusPayload } from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import { num } from '@/format'
import { printPremium, classifyFlowOrder, classifyPremiumTier } from '@/flowDisplay'
import FlowDashboard from '@/components/FlowDashboard.vue'
import ConvictionPlaysPanel from '@/components/ConvictionPlaysPanel.vue'
import FlowSuggestionDrawer from '@/components/FlowSuggestionDrawer.vue'

const FLOW_LIMIT = 500
const BASE_FLOW_FLOOR = 25_000
const FLOW_POLL_MS = 15_000

const router = useRouter()
const route = useRoute()
const sharedStatus = inject<Resource<StatusPayload> | null>('status', null)
const statusPayload = computed(() => sharedStatus?.data.value ?? null)
const minPremium = ref(BASE_FLOW_FLOOR)
const forceNext = ref(false)

function queryTicker(key: 'symbol' | 'setup'): string {
  const raw = route.query[key]
  const value = Array.isArray(raw) ? raw[0] : raw
  return String(value || '')
    .trim()
    .toUpperCase()
}

function focusNameFromQuery(): string {
  return queryTicker('symbol') || queryTicker('setup')
}

const focusSymbol = ref(focusNameFromQuery())

const unusual = useResource(
  () =>
    api.unusualFlow({
      symbol: focusSymbol.value || undefined,
      limit: FLOW_LIMIT,
      minPremium: minPremium.value,
      force: forceNext.value,
    }),
  { intervalMs: FLOW_POLL_MS },
)

function setPremium(value: number): void {
  minPremium.value = value
}

watch([minPremium, focusSymbol], () => {
  void refreshFlow()
})

async function refreshFlow(): Promise<void> {
  forceNext.value = true
  try {
    await unusual.refresh()
  } finally {
    forceNext.value = false
  }
}

function openSymbol(symbol: string): void {
  focusSymbol.value = symbol
  void router.replace({
    name: 'flow',
    query: { ...route.query, symbol },
  })
}

function closeSymbol(): void {
  focusSymbol.value = ''
  const nextQuery = { ...route.query }
  delete nextQuery.symbol
  delete nextQuery.setup
  void router.replace({ name: 'flow', query: nextQuery })
}

watch(
  () => [route.query.symbol, route.query.setup],
  () => {
    focusSymbol.value = focusNameFromQuery()
  },
)

const flowTapeStats = computed(() => {
  const payload = unusual.data.value
  if (!payload) return null
  const summary = payload.summary
  const tape = payload.tape ?? []

  let callPrem = summary?.call_premium ?? 0
  let putPrem = summary?.put_premium ?? 0
  let goldenCount = 0
  let whaleCount = 0
  let sweepCount = 0

  if (!summary && tape.length) {
    for (const print of tape) {
      const p = printPremium(print) ?? 0
      const right = String(print.right || '').toLowerCase()
      if (right === 'call') callPrem += p
      else if (right === 'put') putPrem += p
    }
  }

  for (const print of tape) {
    const p = printPremium(print) ?? 0
    const classified = classifyFlowOrder(print)
    if (classified.type === 'golden_sweep') goldenCount++
    else if (classified.type === 'sweep') sweepCount++
    const tier = classifyPremiumTier(p)
    if (tier.isWhale) whaleCount++
  }

  const total = callPrem + putPrem
  if (total <= 0 && !tape.length) return null

  const pcRatio = callPrem > 0 ? putPrem / callPrem : null
  const callPct = summary?.call_flow_pct ?? (total > 0 ? (callPrem / total) * 100 : null)
  const putPct = summary?.put_flow_pct ?? (total > 0 ? (putPrem / total) * 100 : null)

  return {
    totalCallM: callPrem / 1e6,
    totalPutM: putPrem / 1e6,
    callPct,
    putPct,
    pcRatio,
    goldenCount,
    whaleCount,
    sweepCount,
    totalPrints: summary?.tape_print_count ?? tape.length,
  }
})
</script>

<template>
  <div class="flow-view" :aria-busy="unusual.loading.value">
    <!-- ── Slim control strip (replaces verbose header + HUD) ─────────────── -->
    <!-- Scope: PROVIDER TAPE · SWEEPS & BLOCKS · HEURISTIC FLAGS · POWER ALERTS · WATCHLIST ALERTS · 15s POLL -->
    <header class="fv-strip" aria-label="Options flow control strip">
      <div class="fv-live">
        <i aria-hidden="true" class="fv-live-dot" />
        <h1 class="fv-live-label">Options flow</h1>
        <!-- 15s HTTP poll (not a firehose). Flags are descriptive — not ENTER signals. -->
        <span class="label fv-live-sub">· 15s HTTP poll · flags not ENTER</span>
      </div>

      <!-- Stat chips — shown once data is available -->
      <div v-if="flowTapeStats" class="fv-chips" role="group" aria-label="Flow summary stats">
        <div class="fv-chip fv-chip--call" title="Total Call Flow Premium">
          <span class="fv-chip-label">CALL FLOW</span>
          <span class="fv-chip-val"
            >${{ num(flowTapeStats.totalCallM, 1) }}M
            <span v-if="flowTapeStats.callPct != null" class="fv-chip-pct"
              >({{ num(flowTapeStats.callPct, 0) }}%)</span
            ></span
          >
        </div>
        <div class="fv-chip fv-chip--put" title="Total Put Flow Premium">
          <span class="fv-chip-label">PUT FLOW</span>
          <span class="fv-chip-val"
            >${{ num(flowTapeStats.totalPutM, 1) }}M
            <span v-if="flowTapeStats.putPct != null" class="fv-chip-pct"
              >({{ num(flowTapeStats.putPct, 0) }}%)</span
            ></span
          >
        </div>
        <div class="fv-chip fv-chip--neutral" title="Put/Call Premium Ratio">
          <span class="fv-chip-label">P/C RATIO</span>
          <span class="fv-chip-val">{{
            flowTapeStats.pcRatio != null ? num(flowTapeStats.pcRatio, 2) : '—'
          }}</span>
        </div>
        <div class="fv-chip fv-chip--golden" title="Vendor Golden Sweep Flags">
          <span class="fv-chip-label">GOLDEN</span>
          <span class="fv-chip-val">{{ flowTapeStats.goldenCount }}</span>
        </div>
        <div class="fv-chip fv-chip--sweep" title="Aggressive Sweeps">
          <span class="fv-chip-label">SWEEPS</span>
          <span class="fv-chip-val">{{ flowTapeStats.sweepCount }}</span>
        </div>
        <div class="fv-chip fv-chip--whale" title="Whale Orders ($500k+)">
          <span class="fv-chip-label">WHALES</span>
          <span class="fv-chip-val">{{ flowTapeStats.whaleCount }}</span>
        </div>
        <div class="fv-chip fv-chip--neutral" title="Sampled Prints">
          <span class="fv-chip-label">SAMPLED</span>
          <span class="fv-chip-val">{{ flowTapeStats.totalPrints }}</span>
        </div>
      </div>
    </header>

    <ConvictionPlaysPanel @select="openSymbol" />

    <FlowDashboard
      :payload="unusual.data.value"
      :status="statusPayload"
      :loading="unusual.loading.value"
      :error="unusual.error.value"
      :min-premium="minPremium"
      :poll-ms="FLOW_POLL_MS"
      :focus-symbol="focusSymbol"
      @refresh="void refreshFlow()"
      @threshold="setPremium"
      @open-symbol="openSymbol"
    />

    <FlowSuggestionDrawer v-if="focusSymbol" :symbol="focusSymbol" @close="closeSymbol" />
  </div>
</template>

<style scoped>
.flow-view {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  min-width: 0;
  overflow-x: hidden;
  padding-bottom: var(--s6);
}

/* ── Slim single-row control strip ─────────────────────────────────────────
   Replaces the old verbose header + HUD chip row.
   Height is intentionally short — this is chrome, not content.           */
.fv-strip {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
  padding: var(--s2) var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-lg);
  background: var(--surface-base);
  box-shadow: var(--shadow-1);
  transition: border-color var(--dur-fast, 120ms) ease;
}

/* ── Live indicator ──────────────────────────────────────────────────────── */
.fv-live {
  display: flex;
  align-items: center;
  gap: var(--s1);
  flex-shrink: 0;
  padding-right: var(--s3);
  border-right: var(--hair) solid var(--rule);
}

.fv-live-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--phosphor);
  flex-shrink: 0;
  animation: fv-dot-pulse var(--dur-pulse, 2s) ease-in-out infinite;
}
@keyframes fv-dot-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

.fv-live-label {
  color: var(--phosphor);
  font: 700 var(--t-view-title) / 1.12 var(--font-display);
  letter-spacing: var(--track-display);
  white-space: nowrap;
}

.fv-live-sub {
  color: var(--ink-dim);
  font-size: var(--t-micro);
  letter-spacing: 0.03em;
}

/* ── Stat chip row ───────────────────────────────────────────────────────── */
.fv-chips {
  display: flex;
  align-items: stretch;
  gap: 0;
  flex: 1;
  flex-wrap: wrap;
  min-width: 0;
}

/* Each chip is a stacked label + value cell separated by a right rule */
.fv-chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 1px;
  padding: 3px var(--s3);
  border-right: var(--hair) solid var(--rule);
  transition: background-color var(--dur-fast, 120ms) ease;
}
.fv-chip:last-child {
  border-right: none;
}

.fv-chip-label {
  font-family: var(--font-display);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--ink-dim);
  white-space: nowrap;
  text-transform: uppercase;
}

.fv-chip-val {
  font-family: var(--font-data);
  font-size: var(--t-small);
  font-weight: 750;
  letter-spacing: var(--track-tight, -0.01em);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  line-height: 1.15;
}

.fv-chip-pct {
  font-size: var(--t-micro);
  font-weight: 600;
  opacity: 0.9;
  color: var(--ink-dim);
  margin-left: 3px;
}

/* ── Chip colour variants ────────────────────────────────────────────────── */
.fv-chip--call .fv-chip-val {
  color: var(--call-hi, var(--call));
}
.fv-chip--put .fv-chip-val {
  color: var(--put-hi, var(--put));
}
.fv-chip--golden .fv-chip-val {
  color: var(--warn);
}
.fv-chip--sweep .fv-chip-val {
  color: var(--call);
}
.fv-chip--whale .fv-chip-val {
  color: var(--warn);
}
.fv-chip--neutral .fv-chip-val {
  color: var(--ink);
}

/* ── Responsive ─────────────────────────────────────────────────────────── */
@media (max-width: 780px) {
  .fv-strip {
    gap: var(--s2);
    padding: var(--s2) var(--s3);
  }
  .fv-live-sub {
    display: none;
  }
  .fv-live {
    padding-right: var(--s2);
  }
  .fv-chips {
    flex: 1 1 100%;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
    border-top: var(--hair) solid var(--rule);
    padding-top: var(--s1);
  }
  .fv-chip {
    padding: var(--s1) var(--s2);
    border-right: 0;
    border-left: var(--hair) solid var(--rule);
  }
  .fv-chip:hover {
    background: var(--panel-hi);
  }
}

@media (max-width: 420px) {
  .fv-strip {
    padding-inline: var(--s2);
  }
  .fv-chip-val {
    font-size: var(--t-tiny);
  }
}
</style>
