<script setup lang="ts">
import { computed } from 'vue'
import type { OptionsIntelligence, OptionsTapeRow } from '@/api'
import type { OptionsDirectionRead } from '@/optionsDirection'
import { optCompact, pctFrac } from '@/format'

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
  let classifiedCount = 0

  if (props.tape.length) {
    fromTape = true
    for (const row of props.tape) {
      const prem = Number(row.premium)
      if (!Number.isFinite(prem) || prem < 0) continue
      if (row.right === 'call') {
        call += prem
        classifiedCount += 1
      } else if (row.right === 'put') {
        put += prem
        classifiedCount += 1
      }
    }
  }

  if (!fromTape || call + put <= 0) {
    call = props.summary?.call_premium ?? 0
    put = props.summary?.put_premium ?? 0
    fromTape = false
  }

  const total = call + put
  const hasPrem = total > 0 && (fromTape ? classifiedCount > 0 : (call > 0 || put > 0))
  const callPct = hasPrem ? Math.round((call / total) * 100) : 0
  const putPct = hasPrem ? 100 - callPct : 0
  const dominantPct = Math.max(callPct, putPct)
  const tone = !hasPrem ? 'neutral' : callPct >= 58 ? 'call' : putPct >= 58 ? 'put' : 'neutral'
  const conviction = hasPrem ? (dominantPct >= 72 ? 'HIGH' : dominantPct >= 62 ? 'MED' : 'LOW') : 'NONE'
  const ratio = (hasPrem && put > 0) ? call / put : null

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
  <div class="flow-context flow-evidence-bar" :class="premium.tone">
    <section class="flow-hero">
      <div class="flow-hero-copy">
        <span class="label eyebrow">DISPLAYED TAPE · CONTRACT MIX</span>
        <strong class="fig dominant" :class="premium.tone">{{ premium.label }}</strong>
        <small class="label identity-note">CALL = EMERALD · PUT = CRIMSON · IDENTITY, NOT DIRECTION</small>
      </div>
      <div class="flow-hero-badges">
        <span class="label feed-state" :class="tapeStatus">
          <i aria-hidden="true" />{{ tapeTitle }}
        </span>
        <span class="label conviction" :class="premium.tone">{{ premium.conviction === 'NONE' ? 'NO SKEW' : `${premium.conviction} SKEW` }}</span>
      </div>
    </section>

    <section class="premium-section">
      <div class="section-head label">
        <span>PREMIUM SPLIT</span>
        <span>TOTAL <b class="fig">${{ optCompact(premium.total) }}</b></span>
      </div>
      <div class="premium-track" aria-label="Call versus put premium split">
        <i class="call-fill" :style="{ width: `${premium.callPct}%` }" />
        <i class="put-fill" :style="{ width: `${premium.putPct}%` }" />
      </div>
      <div class="premium-values">
        <div class="premium-side call">
          <span class="label">CALL</span>
          <strong class="fig">{{ premium.callPct }}%</strong>
        </div>
        <div class="premium-side put">
          <span class="label">PUT</span>
          <strong class="fig">{{ premium.putPct }}%</strong>
        </div>
      </div>
    </section>

    <section class="metric-grid">
      <div class="metric">
        <span class="label">C/P IMBALANCE</span>
        <strong class="fig" :class="premium.call >= premium.put ? 'call' : 'put'">
          {{ (premium.call - premium.put >= 0 ? '+' : '') + '$' + optCompact(premium.call - premium.put) }}
        </strong>
        <small class="label">IDENTITY MIX</small>
      </div>
      <div class="metric">
        <span class="label">QUALIFIED</span>
        <strong class="fig">{{ tape.length }}</strong>
        <small class="label">PRINTS</small>
      </div>
      <div class="metric">
        <span class="label">BUY / SELL SIDE</span>
        <strong class="fig">{{ signedCoverage == null ? '0.00%' : pctFrac(signedCoverage, 0) }}</strong>
        <small class="label">{{ signedFlowAvailable ? 'COVERAGE' : 'NOT SUPPLIED' }}</small>
      </div>
      <div class="metric">
        <span class="label">TAPE FLAGS</span>
        <strong class="fig" :class="{ warn: anomalyCount > 0 }">{{ anomalyCount }}</strong>
        <small class="label">ANOMALIES</small>
      </div>
    </section>

    <section class="desk-action" :class="[deskAction.direction, deskAction.priority]">
      <div class="section-head label">
        <span>DESK NEXT STEP</span>
        <span class="priority-tag">{{ deskAction.priority.toUpperCase() }}</span>
      </div>
      <strong class="fig action-title">{{ deskAction.title }}</strong>
    </section>
  </div>
</template>

<style scoped>
/* Surface glass token: var(--glass-surface-hi) */
.flow-context {
  --flow-tone: var(--ink-dim);
  display: grid;
  grid-template-columns: minmax(190px, 1.05fr) minmax(150px, 0.8fr) minmax(300px, 1.4fr) minmax(210px, 1.15fr);
  align-items: stretch;
  min-height: 74px;
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur-sm);
  -webkit-backdrop-filter: var(--glass-blur-sm);
  border-radius: var(--r-md);
  border: var(--hair) solid var(--glass-border);
  box-shadow: var(--glass-shadow-sm), var(--glass-specular-subtle);
  color: var(--ink);
}
.flow-context.call { --flow-tone: var(--call); }
.flow-context.put { --flow-tone: var(--put); }
.flow-context.bullish { --flow-tone: var(--long); }
.flow-context.bearish { --flow-tone: var(--short); }
.flow-context.mixed, .flow-context.neutral { --flow-tone: var(--ink); }
.dominant.bullish { color: var(--long); }
.dominant.bearish { color: var(--short); }
.dominant.mixed, .dominant.neutral { color: var(--ink); }
.conviction.bullish { color: var(--long); }
.conviction.bearish { color: var(--short); }
.identity-note { color: var(--ink-ghost); font-size: var(--t-micro); line-height: 1.35; white-space: normal; }

.flow-hero {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  min-width: 0;
  padding: 6px 12px;
  border-left: 3px solid var(--flow-tone);
  background: var(--glass-surface-hi);
}
.flow-hero-copy { display: flex; min-width: 0; flex-direction: column; gap: 1px; }
.flow-hero-badges { display: flex; flex-wrap: wrap; align-items: center; gap: 3px; }
.eyebrow { color: var(--ink-faint); font-size: var(--t-micro); line-height: 1.3; letter-spacing: 0.05em; white-space: normal; }
.dominant { color: var(--flow-tone); font-size: var(--t-small); line-height: 1.2; letter-spacing: -0.02em; white-space: normal; font-weight: 750; }
.feed-state { display: inline-flex; align-items: center; gap: 4px; color: var(--ink-ghost); font-size: var(--t-micro); white-space: nowrap; }
.feed-state i { width: 5px; height: 5px; border-radius: 50%; background: var(--ink-ghost); }
.feed-state.live i { background: var(--phosphor); }
.feed-state.stale i, .feed-state.warm i { background: var(--warn); }
.conviction { padding: 1px 6px; border: var(--hair) solid var(--glass-border); color: var(--ink-dim); background: var(--glass-base); font-size: var(--t-micro); white-space: nowrap; border-radius: 9999px; font-weight: 700; }
.conviction.call { color: var(--call-hi); border-color: color-mix(in srgb, var(--call) 50%, var(--rule)); background: var(--call-wash); }
.conviction.put { color: var(--put-hi); border-color: color-mix(in srgb, var(--put) 50%, var(--rule)); background: var(--put-wash); }

.premium-section { display: flex; min-width: 0; flex-direction: column; justify-content: center; gap: 3px; padding: 6px 12px; border-left: var(--hair) solid var(--glass-border); }
.section-head { display: flex; justify-content: space-between; gap: var(--s2); color: var(--ink-faint); font-size: var(--t-micro); letter-spacing: 0.04em; }
.section-head b { color: var(--ink-soft); font-variant-numeric: tabular-nums; }
.premium-track { display: flex; height: 7px; overflow: hidden; background: var(--glass-base); border: var(--hair) solid var(--glass-border); border-radius: 9999px; }
.premium-track i { height: 100%; }
.call-fill { background: var(--call); }
.put-fill { background: var(--put); }
.premium-values { display: flex; justify-content: space-between; gap: 8px; }
.premium-side { display: flex; align-items: baseline; gap: 4px; }
.premium-side strong { font-size: var(--t-small); font-variant-numeric: tabular-nums; }
.premium-side.call strong { color: var(--call-hi); }
.premium-side.put strong { color: var(--put-hi); }

.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; min-width: 0; background: var(--glass-border); border-left: var(--hair) solid var(--glass-border); }
.metric { display: flex; min-width: 0; flex-direction: column; justify-content: center; gap: 1px; padding: 6px 8px; background: var(--glass-surface); }
.metric .label { overflow: visible; white-space: normal; text-overflow: clip; line-height: 1.25; color: var(--ink-faint); font-size: var(--t-micro); letter-spacing: 0.04em; }
.metric strong { color: var(--ink-soft); font-size: var(--t-small); font-variant-numeric: tabular-nums; font-weight: 700; }
.metric small { color: var(--ink-ghost); font-size: var(--t-micro); }
.metric .warn { color: var(--warn); }

.desk-action {
  --action-tone: var(--ink-dim);
  display: flex;
  min-width: 0;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  padding: 6px 12px;
  border-left: 3px solid var(--action-tone);
  background: var(--glass-surface-hi);
}
.desk-action.bullish { --action-tone: var(--long); }
.desk-action.bearish { --action-tone: var(--short); }
.desk-action.mixed { --action-tone: var(--warn); }
.priority-tag {
  padding: 1px 6px;
  border: var(--hair) solid var(--glass-border);
  color: var(--ink-dim);
  font-weight: 750;
  letter-spacing: 0.05em;
  border-radius: var(--r-xs);
  background: var(--glass-base);
}
.desk-action.now .priority-tag {
  color: var(--phosphor);
  border-color: color-mix(in srgb, var(--phosphor) 50%, var(--rule));
  background: var(--phosphor-wash);
}
.desk-action.soon .priority-tag {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 45%, var(--rule));
  background: var(--warn-wash);
}
.action-title {
  color: var(--ink);
  font-size: var(--t-micro);
  line-height: 1.3;
  letter-spacing: -0.01em;
  white-space: normal;
  font-weight: 600;
}

@media (max-width: 1180px) {
  .flow-context {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 700px) {
  .flow-context { grid-template-columns: 1fr; }
}
</style>
