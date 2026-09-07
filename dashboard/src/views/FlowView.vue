<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type StatusPayload } from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import { num } from '@/format'
import { printPremium, classifyFlowOrder, classifyPremiumTier } from '@/flowDisplay'
import FlowDashboard from '@/components/FlowDashboard.vue'

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
  <div class="flow-view">
    <header class="flow-head ticked rise">
      <div class="flow-title">
        <span class="label eyebrow"
          ><i aria-hidden="true" class="live-dot" /> OPTIONS FLOW · 15s POLL</span
        >
        <h1>Market-Wide Order Flow</h1>
        <p>
          LSE options prints from one market-wide provider window. 15s HTTP poll (not a websocket
          firehose). Sweeps, unusual, and heat are descriptive flags, not ENTER. Unsigned prints stay
          unsigned.
        </p>
      </div>
      <div class="scope-stack">
        <span class="scope-chip label live"><i aria-hidden="true" /> PROVIDER TAPE</span>
        <span class="scope-chip label">SWEEPS &amp; BLOCKS</span>
        <span class="scope-chip label">HEURISTIC FLAGS</span>
        <span class="scope-chip label">POWER ALERTS</span>
        <span class="scope-chip label">WATCHLIST ALERTS</span>
        <span class="scope-chip label">15s POLL</span>
      </div>
    </header>

    <!-- InsiderFinance Flow Terminal Market HUD -->
    <div
      v-if="flowTapeStats"
      class="flow-market-hud rise"
      aria-label="Market flow summary HUD"
    >
      <span class="hud-label label">FLOW HUD</span>
      <div class="flow-hud-chip chip-call" title="Total Call Flow Premium">
        <span class="hud-name label">CALL FLOW</span>
        <span class="hud-val fig">${{ num(flowTapeStats.totalCallM, 1) }}M</span>
        <span v-if="flowTapeStats.callPct != null" class="hud-sub fig">({{ num(flowTapeStats.callPct, 0) }}%)</span>
      </div>
      <div class="flow-hud-chip chip-put" title="Total Put Flow Premium">
        <span class="hud-name label">PUT FLOW</span>
        <span class="hud-val fig">${{ num(flowTapeStats.totalPutM, 1) }}M</span>
        <span v-if="flowTapeStats.putPct != null" class="hud-sub fig">({{ num(flowTapeStats.putPct, 0) }}%)</span>
      </div>
      <div class="flow-hud-chip chip-ratio" title="Put/Call Premium Ratio">
        <span class="hud-name label">P/C RATIO</span>
        <span class="hud-val fig">{{ flowTapeStats.pcRatio != null ? num(flowTapeStats.pcRatio, 2) : '—' }}</span>
      </div>
      <div class="flow-hud-chip chip-golden" title="Vendor Golden Sweep Flags">
        <span class="hud-name label">GOLDEN FLAGS</span>
        <span class="hud-val fig">{{ flowTapeStats.goldenCount }}</span>
      </div>
      <div class="flow-hud-chip chip-sweeps" title="Aggressive Sweeps">
        <span class="hud-name label">SWEEPS</span>
        <span class="hud-val fig">{{ flowTapeStats.sweepCount }}</span>
      </div>
      <div class="flow-hud-chip chip-whales" title="Whale Orders ($500k+)">
        <span class="hud-name label">WHALES</span>
        <span class="hud-val fig">{{ flowTapeStats.whaleCount }}</span>
      </div>
      <div class="flow-hud-chip chip-neutral" title="Tape Sample Prints Count">
        <span class="hud-name label">SAMPLED</span>
        <span class="hud-val fig">{{ flowTapeStats.totalPrints }}</span>
      </div>
    </div>

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

/* Content-layer hero: opaque standard material, concentric corners,
   phosphor leading edge marks the live feed. No backdrop blur here. */
.flow-head {
  position: relative;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s6);
  padding: var(--s4) var(--s5);
  border: var(--hair) solid var(--rule);
  border-left: 1px solid var(--phosphor-dim);
  border-radius: var(--r-xl);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 48px),
    var(--surface-base);
  box-shadow: var(--shadow-1);
}

.flow-title {
  min-width: 0;
}

.eyebrow {
  color: var(--phosphor);
}

h1 {
  margin: var(--s2) 0 0;
  color: var(--ink);
  font: 700 calc(var(--t-display) + 4px) / 1.12 var(--font-display);
  letter-spacing: -0.02em;
}

.flow-title p {
  max-width: 76ch;
  margin-top: var(--s3);
  color: var(--text-secondary);
  font-size: var(--t-body);
  line-height: 1.55;
}

.scope-stack {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: var(--s2);
  max-width: 28rem;
  padding-bottom: var(--s1);
}

.scope-chip {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: var(--s1) 10px;
  white-space: nowrap;
  color: var(--ink-dim);
  border: var(--hair) solid var(--glass-border);
  background: var(--glass-surface);
  box-shadow: var(--glass-specular-subtle);
  border-radius: var(--r-capsule);
}

@media (prefers-reduced-transparency: reduce) {
  .scope-chip {
    background: var(--panel-hi);
  }
}

.scope-chip.live {
  color: var(--status-live);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.scope-chip.live i {
  display: inline-block;
  width: 5px;
  height: 5px;
  margin-right: 5px;
  border-radius: 50%;
  background: currentColor;
}

.live-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--phosphor);
  margin-right: 6px;
  vertical-align: middle;
  animation: dot-pulse var(--dur-pulse) ease-in-out infinite;
}
@keyframes dot-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}

.scope-chip.warn {
  color: var(--status-stale);
}

@media (max-width: 780px) {
  .flow-head {
    flex-direction: column;
    gap: var(--s3);
    min-height: 0;
    padding: var(--s4);
  }

  h1 {
    font-size: var(--t-display);
  }

  .scope-stack {
    justify-content: flex-start;
    flex-wrap: wrap;
    max-width: none;
  }
}

/* ==========================================================================
   INSIDERFINANCE FLOW TERMINAL MARKET HUD
   ========================================================================== */

.flow-market-hud {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
  padding: 0.35rem 0.625rem;
  border-radius: var(--r-md);
  background: var(--surface-base);
  border: var(--hair) solid var(--rule);
}

.flow-market-hud .hud-label {
  color: var(--ink-faint);
  letter-spacing: 0.06em;
  margin-right: 0.25rem;
}

.flow-hud-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.2rem 0.5rem;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
  background: var(--surface-subtle, var(--wash-1));
}

.flow-hud-chip.chip-call {
  border-color: color-mix(in srgb, var(--call) 45%, var(--rule));
  color: var(--call-hi, var(--call));
  background: var(--call-wash);
}

.flow-hud-chip.chip-put {
  border-color: color-mix(in srgb, var(--put) 45%, var(--rule));
  color: var(--put-hi, var(--put));
  background: var(--put-wash);
}

.flow-hud-chip.chip-ratio {
  border-color: var(--rule-hi);
  color: var(--ink);
  background: var(--wash-1);
}

.flow-hud-chip.chip-golden {
  border-color: var(--badge-golden-border);
  color: var(--badge-golden);
  background: var(--badge-golden-wash);
}

.flow-hud-chip.chip-sweeps {
  border-color: color-mix(in srgb, var(--call) 35%, var(--rule));
  color: var(--badge-sweep);
  background: var(--badge-sweep-wash);
}

.flow-hud-chip.chip-whales {
  border-color: color-mix(in srgb, var(--warn) 40%, var(--rule));
  color: var(--warn);
  background: var(--warn-wash);
}

.flow-hud-chip.chip-neutral {
  border-color: var(--rule);
  color: var(--ink-dim);
  background: var(--wash-1);
}

.flow-hud-chip .hud-name {
  font-size: var(--t-nano);
  letter-spacing: 0.04em;
  color: var(--ink-dim);
}

.flow-hud-chip .hud-val {
  font-size: var(--t-micro);
  font-weight: 700;
}

.flow-hud-chip .hud-sub {
  font-size: var(--t-nano);
  opacity: 0.85;
}
</style>
