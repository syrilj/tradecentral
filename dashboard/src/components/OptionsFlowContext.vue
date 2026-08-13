<script setup lang="ts">
import { computed } from 'vue'
import type { OptionsIntelligence, OptionsTapeRow } from '@/api'
import type { OptionsDirectionRead } from '@/optionsDirection'
import { compact, num, pctFrac, usd, DASH } from '@/format'

const props = defineProps<{
  summary: OptionsIntelligence['summary'] | null | undefined
  tape: OptionsTapeRow[]
  anomalyCount: number
  signedFlowAvailable: boolean
  tapeStatus: string
  tapeTitle: string
  direction: OptionsDirectionRead
}>()

const premium = computed(() => {
  // Always sum the tape this panel is paired with. Summary aggregates can
  // include prints truncated off the returned tape (tape_limit), which made
  // C/P ratio disagree with the actual flow list on screen.
  let call = 0
  let put = 0
  let fromTape = false

  if (props.tape.length) {
    fromTape = true
    for (const row of props.tape) {
      const prem = Number(row.premium)
      if (!Number.isFinite(prem) || prem < 0) continue
      if (row.right === 'call') call += prem
      else if (row.right === 'put') put += prem
    }
  }

  if (!fromTape || call + put <= 0) {
    call = props.summary?.call_premium ?? 0
    put = props.summary?.put_premium ?? 0
    fromTape = false
  }

  const total = call + put
  const callPct = total > 0 ? Math.round((call / total) * 100) : 50
  const putPct = 100 - callPct
  const dominantPct = Math.max(callPct, putPct)
  const tone = callPct >= 58 ? 'call' : putPct >= 58 ? 'put' : 'neutral'
  const conviction = dominantPct >= 72 ? 'HIGH' : dominantPct >= 62 ? 'MED' : 'LOW'
  const ratio = put > 0 ? call / put : null

  const label = tone === 'call'
    ? 'CALL-HEAVY ACTIVITY'
    : tone === 'put'
      ? 'PUT-HEAVY ACTIVITY'
      : total > 0 ? 'BALANCED ACTIVITY' : 'NO ACTIVITY MIX'

  return {
    call,
    put,
    total,
    callPct,
    putPct,
    ratio,
    fromTape,
    tone,
    conviction,
    label,
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

/**
 * Concrete research next-step for this underlier. Descriptive only —
 * never execution authorization.
 */
const deskAction = computed(() => {
  const direction = props.direction.state
  const regime = String(props.summary?.regime || 'unknown').toLowerCase()
  const callDist = callWallDistance.value
  const putDist = putWallDistance.value
  const flipDist = flipDistance.value
  const anomalies = props.anomalyCount
  const signed = props.signedFlowAvailable && (signedCoverage.value ?? 0) >= 0.25

  let priority: 'now' | 'soon' | 'watch' = 'watch'
  if (props.tapeStatus === 'stale' || props.tapeStatus === 'warm') priority = 'watch'
  else if (direction === 'bullish' || direction === 'bearish') priority = anomalies > 0 || signed ? 'now' : 'soon'
  else if (direction === 'mixed') priority = 'soon'

  const levels: string[] = []
  if (callDist != null && Math.abs(callDist) <= 0.03) levels.push(`call wall ${pctFrac(callDist, 1)} away`)
  if (putDist != null && Math.abs(putDist) <= 0.03) levels.push(`put wall ${pctFrac(putDist, 1)} away`)
  if (flipDist != null && Math.abs(flipDist) <= 0.02) levels.push(`near gamma flip`)

  let title = 'No clear lean — map walls, then wait for signed side'
  let body = 'Use put/call walls and net GEX as structure context. Do not invent direction from identity alone.'

  if (direction === 'bullish') {
    title = signed
      ? 'Bullish read — confirm call liquidity and upside wall'
      : 'Bullish momentum read — wait for signed flow confirmation'
    body = levels.length
      ? `Focus: ${levels.join(' · ')}. Confirm liquidity at the call wall before acting on the read.`
      : regime === 'positive'
        ? 'Positive GEX regime often pins toward the call wall; confirm that wall and expected move first.'
        : 'Map nearest liquid calls and the call wall; treat lean as triage, not a fill signal.'
  } else if (direction === 'bearish') {
    title = signed
      ? 'Bearish read — confirm put liquidity and downside wall'
      : 'Bearish momentum read — wait for signed flow confirmation'
    body = levels.length
      ? `Focus: ${levels.join(' · ')}. Confirm liquidity at the put wall before acting on the read.`
      : regime === 'negative'
        ? 'Negative GEX can amplify moves; confirm put wall and invalidation above flip.'
        : 'Map nearest liquid puts and the put wall; treat lean as triage, not a fill signal.'
  } else if (direction === 'mixed') {
    title = 'Mixed direction — reconcile signed flow and momentum'
    body = levels.length
      ? `Structure still matters: ${levels.join(' · ')}. Prefer watch until one side dominates.`
      : 'Directional inputs disagree. Prefer research-only until signed flow and momentum align.'
  }

  if (anomalies > 0) {
    body = `${body} ${anomalies} anomaly print${anomalies === 1 ? '' : 's'} flagged — inspect those strikes first.`
  }

  return { priority, title, body, direction }
})
</script>

<template>
  <div class="flow-context" :class="premium.tone">
    <section class="flow-hero">
      <div class="flow-hero-copy">
        <span class="label eyebrow">DISPLAYED TAPE · CONTRACT MIX</span>
        <strong class="fig dominant" :class="premium.tone">{{ premium.label }}</strong>
        <small class="label identity-note">CALL = BLUE · PUT = AMBER · IDENTITY, NOT DIRECTION</small>
        <span class="label feed-state" :class="tapeStatus">
          <i aria-hidden="true" />{{ tapeTitle }}
        </span>
      </div>
      <span class="label conviction" :class="premium.tone">{{ premium.conviction }} SKEW</span>
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
        <strong class="fig">{{ premium.ratio == null ? DASH : num(premium.ratio, 2) }}</strong>
        <small class="label">{{ premium.fromTape ? 'DISPLAYED TAPE' : 'TAPE SUMMARY' }}</small>
      </div>
      <div class="metric">
        <span class="label">QUALIFIED</span>
        <strong class="fig">{{ tape.length }}</strong>
        <small class="label">PRINTS</small>
      </div>
      <div class="metric">
        <span class="label">BUY / SELL SIDE</span>
        <strong class="fig">{{ signedCoverage == null ? DASH : pctFrac(signedCoverage, 0) }}</strong>
        <small class="label">{{ signedFlowAvailable ? 'PROVIDER COVERAGE' : 'NOT SUPPLIED' }}</small>
      </div>
      <div class="metric">
        <span class="label">TAPE FLAGS</span>
        <strong class="fig" :class="{ warn: anomalyCount > 0 }">{{ anomalyCount }}</strong>
        <small class="label">{{ anomalyCount > 0 ? 'HEURISTIC FLAGS' : 'NONE FLAGGED' }}</small>
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

    <section class="desk-action" :class="[deskAction.direction, deskAction.priority]">
      <div class="section-head label">
        <span>DESK NEXT STEP</span>
        <span class="priority-tag">{{ deskAction.priority.toUpperCase() }}</span>
      </div>
      <strong class="fig action-title">{{ deskAction.title }}</strong>
      <p>{{ deskAction.body }}</p>
      <small class="label">Research triage · not order authorization</small>
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
  overflow: auto;
  background: var(--panel);
  color: var(--ink);
}
.flow-context.call { --flow-tone: var(--call); }
.flow-context.put { --flow-tone: var(--put); }
.flow-context.bullish { --flow-tone: var(--long, var(--call)); }
.flow-context.bearish { --flow-tone: var(--short, var(--put)); }
.flow-context.mixed, .flow-context.neutral { --flow-tone: var(--ink); }
.dominant.bullish { color: var(--long, var(--call)); }
.dominant.bearish { color: var(--short, var(--put)); }
.dominant.mixed, .dominant.neutral { color: var(--ink); }
.conviction.bullish { color: var(--long, var(--call)); }
.conviction.bearish { color: var(--short, var(--put)); }
.identity-note { overflow: visible; color: var(--ink-ghost); font-size: var(--t-micro); white-space: normal; text-overflow: clip; }

.flow-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s4);
  border-left: 3px solid var(--flow-tone);
  border-bottom: var(--hair) solid var(--rule-hi);
  background: color-mix(in srgb, var(--flow-tone) 7%, var(--void-lift));
}
.flow-hero-copy { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.eyebrow { color: var(--ink-faint); font-size: var(--t-micro); }
.dominant { color: var(--flow-tone); font-size: var(--t-lead); line-height: 1.2; letter-spacing: -0.02em; }
.feed-state { display: inline-flex; align-items: center; gap: 5px; color: var(--ink-ghost); font-size: var(--t-micro); }
.feed-state i { width: 6px; height: 6px; border-radius: 50%; background: var(--ink-ghost); }
.feed-state.live i { background: var(--phosphor); }
.feed-state.stale i, .feed-state.warm i { background: var(--warn); }
.conviction { padding: var(--s1) var(--s2); border: var(--hair) solid var(--rule-hi); color: var(--ink-dim); background: var(--void-lift); font-size: var(--t-micro); }
.conviction.call { color: var(--call-hi); border-color: color-mix(in srgb, var(--call) 50%, var(--rule)); }
.conviction.put { color: var(--put-hi); border-color: color-mix(in srgb, var(--put) 50%, var(--rule)); }

.premium-section, .structure-section { padding: var(--s3) var(--s4); border-bottom: var(--hair) solid var(--rule); }
.section-head { display: flex; justify-content: space-between; gap: var(--s2); color: var(--ink-faint); font-size: var(--t-micro); }
.section-head b { color: var(--ink-soft); }
.premium-track { display: flex; height: 8px; margin: 8px 0 7px; overflow: hidden; background: var(--rule); border: var(--hair) solid var(--rule-hi); }
.premium-track i { height: 100%; }
.call-fill { background: var(--call); }
.put-fill { background: var(--put); }
.premium-values { display: flex; justify-content: space-between; gap: 12px; }
.premium-side { display: grid; grid-template-columns: auto auto; align-items: baseline; gap: 1px 5px; }
.premium-side:last-child { justify-items: end; }
.premium-side strong { font-size: 0.95rem; }
.premium-side small { grid-column: 1 / -1; color: var(--ink-dim); font-size: var(--t-micro); }
.premium-side.call strong { color: var(--call-hi); }
.premium-side.put strong { color: var(--put-hi); }

.metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; background: var(--rule); border-bottom: var(--hair) solid var(--rule); }
.metric { display: grid; grid-template-columns: 1fr auto; align-items: baseline; gap: var(--s1) var(--s2); min-width: 0; padding: var(--s3); background: var(--void-lift); }
.metric .label { color: var(--ink-faint); font-size: var(--t-micro); }
.metric strong { color: var(--ink-soft); font-size: var(--t-body); }
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
.level-row { display: grid; grid-template-columns: 6px minmax(0, 1fr) auto 46px; align-items: center; gap: var(--s2); min-height: 28px; border-bottom: var(--hair) solid var(--rule-faint); }
.level-row:last-child { border-bottom: 0; }
.level-row .label { color: var(--ink-dim); font-size: var(--t-micro); }
.level-row strong { color: var(--ink-soft); font-size: var(--t-small); }
.level-row small { color: var(--ink-ghost); font-size: var(--t-micro); text-align: right; }
.level-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ink); }
.level-dot.call { background: var(--call); }
.level-dot.put { background: var(--put); }
.level-dot.flip { background: var(--warn); }
.level-dot.spot { background: var(--ink); }

.desk-action {
  --action-tone: var(--ink-dim);
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  padding: var(--s3) var(--s4);
  border-left: 3px solid var(--action-tone);
  background: color-mix(in srgb, var(--action-tone) 6%, var(--void-lift));
}
.desk-action.bullish { --action-tone: var(--long, var(--call)); }
.desk-action.bearish { --action-tone: var(--short, var(--put)); }
.desk-action.mixed { --action-tone: var(--warn); }
.desk-action .section-head { margin-bottom: 2px; }
.priority-tag {
  padding: 1px 5px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
  font-weight: 750;
  letter-spacing: 0.05em;
}
.desk-action.now .priority-tag {
  color: var(--phosphor);
  border-color: color-mix(in srgb, var(--phosphor) 50%, var(--rule));
}
.desk-action.soon .priority-tag {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 50%, var(--rule));
}
.action-title {
  color: var(--ink);
  font-size: var(--t-body);
  line-height: 1.25;
  letter-spacing: -0.01em;
}
.desk-action p {
  margin: 0;
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.45;
}
.desk-action > small { color: var(--ink-ghost); font-size: var(--t-micro); }

</style>
