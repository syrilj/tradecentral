<script setup lang="ts">
import { computed } from 'vue'
import type { OptionsIntelligence, OptionsTapeRow } from '@/api'
import { compact, num, pctFrac, usd, DASH } from '@/format'

const props = defineProps<{
  summary: OptionsIntelligence['summary'] | null | undefined
  tape: OptionsTapeRow[]
  anomalyCount: number
  signedFlowAvailable: boolean
  tapeStatus: string
  tapeTitle: string
}>()

const premium = computed(() => {
  let call = props.summary?.call_premium ?? 0
  let put = props.summary?.put_premium ?? 0

  // The summary covers the complete filtered window; only fall back to the
  // visible tape when the provider did not publish aggregate premiums.
  if (call + put <= 0 && props.tape.length) {
    for (const row of props.tape) {
      if (row.right === 'call') call += row.premium
      if (row.right === 'put') put += row.premium
    }
  }

  const total = call + put
  const callPct = total > 0 ? Math.round((call / total) * 100) : 50
  const putPct = 100 - callPct
  const dominantPct = Math.max(callPct, putPct)
  const tone = callPct >= 58 ? 'call' : putPct >= 58 ? 'put' : 'neutral'
  const conviction = dominantPct >= 72 ? 'HIGH' : dominantPct >= 62 ? 'MED' : 'LOW'

  return {
    call,
    put,
    total,
    callPct,
    putPct,
    tone,
    conviction,
    label: tone === 'call' ? 'CALL FLOW DOMINANT' : tone === 'put' ? 'PUT FLOW DOMINANT' : 'BALANCED FLOW',
  }
})

const tapeStats = computed(() => {
  let signed = 0

  for (const row of props.tape) {
    if (row.signed_premium != null || row.aggressor === 'buy' || row.aggressor === 'sell') signed += 1
  }

  return { signed }
})

const signedCoverage = computed(() => {
  if (!props.tape.length) return null
  return tapeStats.value.signed / props.tape.length
})

const flipDistance = computed(() => {
  const spot = props.summary?.spot
  const flip = props.summary?.gamma_flip
  if (spot == null || flip == null || spot === 0) return null
  return (spot - flip) / spot
})

const callWallDistance = computed(() => {
  const spot = props.summary?.spot
  const wall = props.summary?.call_wall
  if (spot == null || wall == null || spot === 0) return null
  return (wall - spot) / spot
})

const putWallDistance = computed(() => {
  const spot = props.summary?.spot
  const wall = props.summary?.put_wall
  if (spot == null || wall == null || spot === 0) return null
  return (wall - spot) / spot
})
</script>

<template>
  <div class="flow-context" :class="premium.tone">
    <section class="flow-hero">
      <div class="flow-hero-copy">
        <span class="label eyebrow">FLOW SENTIMENT</span>
        <strong class="fig dominant">{{ premium.label }}</strong>
        <span class="label feed-state" :class="tapeStatus">
          <i aria-hidden="true" />{{ tapeTitle }}
        </span>
      </div>
      <span class="label conviction" :class="premium.tone">{{ premium.conviction }}</span>
    </section>

    <section class="premium-section">
      <div class="section-head label">
        <span>PREMIUM SPLIT</span>
        <span>TOTAL <b class="fig">${{ compact(premium.total) }}</b></span>
      </div>
      <div class="premium-track" aria-label="Call versus put premium split">
        <i class="call-fill" :style="{ width: `${premium.callPct}%` }" />
        <i class="put-fill" :style="{ width: `${premium.putPct}%` }" />
      </div>
      <div class="premium-values">
        <div class="premium-side call">
          <span class="label">CALL</span>
          <strong class="fig">{{ premium.callPct }}%</strong>
          <small class="fig">${{ compact(premium.call) }}</small>
        </div>
        <div class="premium-side put">
          <span class="label">PUT</span>
          <strong class="fig">{{ premium.putPct }}%</strong>
          <small class="fig">${{ compact(premium.put) }}</small>
        </div>
      </div>
    </section>

    <section class="metric-grid">
      <div class="metric">
        <span class="label">C / P RATIO</span>
        <strong class="fig">{{ summary?.call_put_ratio == null ? DASH : num(summary.call_put_ratio, 2) }}</strong>
      </div>
      <div class="metric">
        <span class="label">QUALIFIED</span>
        <strong class="fig">{{ tape.length }}</strong>
        <small class="label">PRINTS</small>
      </div>
      <div class="metric">
        <span class="label">SIGNED COVER</span>
        <strong class="fig">{{ signedCoverage == null ? DASH : pctFrac(signedCoverage, 0) }}</strong>
        <small class="label">{{ signedFlowAvailable ? 'FEED SIDE' : 'LIMITED' }}</small>
      </div>
      <div class="metric">
        <span class="label">ANOMALIES</span>
        <strong class="fig" :class="{ warn: anomalyCount > 0 }">{{ anomalyCount }}</strong>
        <small class="label">FLAGGED</small>
      </div>
    </section>

    <section class="structure-section">
      <div class="section-head label">
        <span>MARKET STRUCTURE</span>
        <span class="regime" :class="summary?.regime">{{ (summary?.regime ?? 'unknown').toUpperCase() }} Γ</span>
      </div>
      <div class="structure-primary">
        <span class="label">NET GEX</span>
        <strong class="fig" :class="summary?.total_gex_m != null && summary.total_gex_m >= 0 ? 'positive' : 'negative'">
          {{ summary?.total_gex_m == null ? DASH : `${summary.total_gex_m >= 0 ? '+' : ''}$${num(summary.total_gex_m, 1)}M` }}
        </strong>
      </div>
      <div class="level-list">
        <div class="level-row">
          <span class="level-dot put" /><span class="label">PUT WALL</span>
          <strong class="fig">{{ usd(summary?.put_wall) }}</strong>
          <small class="fig">{{ putWallDistance == null ? DASH : pctFrac(putWallDistance, 1) }}</small>
        </div>
        <div class="level-row">
          <span class="level-dot flip" /><span class="label">GAMMA FLIP</span>
          <strong class="fig">{{ usd(summary?.gamma_flip) }}</strong>
          <small class="fig">{{ flipDistance == null ? DASH : `${flipDistance >= 0 ? '+' : ''}${pctFrac(flipDistance, 1)}` }}</small>
        </div>
        <div class="level-row">
          <span class="level-dot spot" /><span class="label">SPOT</span>
          <strong class="fig">{{ usd(summary?.spot) }}</strong>
          <small class="fig">NOW</small>
        </div>
        <div class="level-row">
          <span class="level-dot call" /><span class="label">CALL WALL</span>
          <strong class="fig">{{ usd(summary?.call_wall) }}</strong>
          <small class="fig">{{ callWallDistance == null ? DASH : `${callWallDistance >= 0 ? '+' : ''}${pctFrac(callWallDistance, 1)}` }}</small>
        </div>
      </div>
    </section>

  </div>
</template>

<style scoped>
.flow-context {
  --flow-tone: var(--ink-dim);
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  flex-direction: column;
  background: var(--panel);
  color: var(--ink);
}
.flow-context.call { --flow-tone: var(--call); }
.flow-context.put { --flow-tone: var(--put); }

.flow-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s2);
  padding: 12px;
  border-left: 3px solid var(--flow-tone);
  border-bottom: var(--hair) solid var(--rule-hi);
  background: color-mix(in srgb, var(--flow-tone) 7%, var(--void-lift));
}
.flow-hero-copy { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.eyebrow { color: var(--ink-faint); font-size: 8px; }
.dominant { color: var(--flow-tone); font-size: 0.95rem; line-height: 1.2; letter-spacing: -0.02em; }
.feed-state { display: inline-flex; align-items: center; gap: 5px; color: var(--ink-ghost); font-size: 8px; }
.feed-state i { width: 6px; height: 6px; border-radius: 50%; background: var(--ink-ghost); }
.feed-state.live i { background: var(--phosphor); }
.feed-state.stale i, .feed-state.warm i { background: var(--warn); }
.conviction { padding: 2px 6px; border: var(--hair) solid var(--rule-hi); color: var(--ink-dim); background: var(--void-lift); font-size: 8px; }
.conviction.call { color: var(--call-hi); border-color: color-mix(in srgb, var(--call) 50%, var(--rule)); }
.conviction.put { color: var(--put-hi); border-color: color-mix(in srgb, var(--put) 50%, var(--rule)); }

.premium-section, .structure-section { padding: 10px 12px; border-bottom: var(--hair) solid var(--rule); }
.section-head { display: flex; justify-content: space-between; gap: 8px; color: var(--ink-faint); font-size: 8px; }
.section-head b { color: var(--ink-soft); }
.premium-track { display: flex; height: 8px; margin: 8px 0 7px; overflow: hidden; background: var(--rule); border: var(--hair) solid var(--rule-hi); }
.premium-track i { height: 100%; }
.call-fill { background: var(--call); }
.put-fill { background: var(--put); }
.premium-values { display: flex; justify-content: space-between; gap: 12px; }
.premium-side { display: grid; grid-template-columns: auto auto; align-items: baseline; gap: 1px 5px; }
.premium-side:last-child { justify-items: end; }
.premium-side strong { font-size: 0.95rem; }
.premium-side small { grid-column: 1 / -1; color: var(--ink-dim); font-size: 9px; }
.premium-side.call strong { color: var(--call-hi); }
.premium-side.put strong { color: var(--put-hi); }

.metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; background: var(--rule); border-bottom: var(--hair) solid var(--rule); }
.metric { display: grid; grid-template-columns: 1fr auto; align-items: baseline; gap: 2px 6px; min-width: 0; padding: 8px 10px; background: var(--void-lift); }
.metric .label { color: var(--ink-faint); font-size: 8px; }
.metric strong { color: var(--ink-soft); font-size: 0.85rem; }
.metric small { grid-column: 1 / -1; }
.metric .warn { color: var(--warn); }

.regime.positive { color: var(--call-hi); }
.regime.negative { color: var(--put-hi); }
.structure-primary { display: flex; align-items: baseline; justify-content: space-between; margin: 7px 0; padding: 7px 0; border-block: var(--hair) solid var(--rule-faint); }
.structure-primary .label { color: var(--ink-dim); }
.structure-primary strong { font-size: 1rem; }
.structure-primary strong.positive { color: var(--call-hi); }
.structure-primary strong.negative { color: var(--put-hi); }
.level-list { display: flex; flex-direction: column; }
.level-row { display: grid; grid-template-columns: 6px minmax(0, 1fr) auto 46px; align-items: center; gap: 6px; min-height: 24px; border-bottom: var(--hair) solid var(--rule-faint); }
.level-row:last-child { border-bottom: 0; }
.level-row .label { color: var(--ink-dim); font-size: 8px; }
.level-row strong { color: var(--ink-soft); font-size: 10px; }
.level-row small { color: var(--ink-ghost); font-size: 9px; text-align: right; }
.level-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ink); }
.level-dot.call { background: var(--call); }
.level-dot.put { background: var(--put); }
.level-dot.flip { background: var(--warn); }
.level-dot.spot { background: var(--ink); }

</style>
