<script setup lang="ts">
/**
 * Gamma Squeeze Screener — primary-side probability board with circular score,
 * factor breakdown, key levels, and takeaways. Dual-side data still available;
 * the active (higher) side is featured. Structure is never hard-zeroed.
 */
import { computed } from 'vue'
import type { OptionsSqueeze, SqueezeSetup, SqueezeFactor } from '@/api'
import { usd } from '@/format'

const props = defineProps<{
  squeeze: OptionsSqueeze | null | undefined
  spot?: number | null
}>()

const primary = computed(() => props.squeeze?.primary ?? 'quiet')
const bull = computed(() => props.squeeze?.bullish_setup)
const bear = computed(() => props.squeeze?.bearish_setup)
const signedScore = computed(() => props.squeeze?.score ?? null)
const levels = computed(() => props.squeeze?.key_levels)
const dampened = computed(() => Boolean(props.squeeze?.long_gamma_dampened))
const fuel = computed(() => {
  const v = props.squeeze?.negative_fuel
  return typeof v === 'number' ? v : null
})

/** Featured setup: highest structure score, with primary bias as tie-break. */
const featured = computed((): { side: 'bullish' | 'bearish'; setup: SqueezeSetup | undefined } => {
  const b = bull.value
  const r = bear.value
  const bs = b?.score ?? 0
  const rs = r?.score ?? 0
  if (primary.value === 'bearish' || (rs > bs && primary.value !== 'bullish')) {
    return { side: 'bearish', setup: r }
  }
  if (primary.value === 'bullish' || bs >= rs) {
    return { side: 'bullish', setup: b }
  }
  return { side: 'bearish', setup: r }
})

const boardScore = computed(() => featured.value.setup?.score ?? 0)
const likelihood = computed(() => featured.value.setup?.likelihood ?? 'unlikely')
const factors = computed(() => featured.value.setup?.factors ?? [])
const analysis = computed(() => featured.value.setup?.setup_analysis ?? [])
const spectrumPct = computed(() => Math.max(0, Math.min(100, boardScore.value)))

/** Full ring: circumference of r=42 → 2πr ≈ 263.9 */
const RING_C = 263.89
const ringOffset = computed(() => RING_C * (1 - boardScore.value / 100))

function scoreCls(score: number): string {
  if (score >= 75) return 'hot'
  if (score >= 55) return 'elev'
  if (score >= 35) return 'mid'
  return 'low'
}

const featuredWall = computed(() => {
  const setup = featured.value.setup
  if (setup?.wall != null) {
    return {
      level: setup.wall,
      pct: setup.wall_pct,
      label: featured.value.side === 'bullish' ? 'Call Wall' : 'Put Wall',
    }
  }
  if (featured.value.side === 'bullish') {
    return {
      level: levels.value?.call_wall ?? null,
      pct: levels.value?.call_wall_pct ?? null,
      label: 'Call Wall',
    }
  }
  return {
    level: levels.value?.put_wall ?? null,
    pct: levels.value?.put_wall_pct ?? null,
    label: 'Put Wall',
  }
})

const displayFactors = computed(() => factors.value ?? [])

function factorTheme(f: SqueezeFactor): string {
  const id = (f.id || '').toLowerCase()
  const lbl = (f.label || '').toLowerCase()
  if (id.includes('call') || lbl.includes('call') || id.includes('bull')) return 'bullish'
  if (id.includes('put') || lbl.includes('put') || id.includes('bear')) return 'bearish'
  if (id.includes('fuel') || id.includes('gamma') || id.includes('skew')) return 'warn'
  return 'accent'
}

const displayTakeaways = computed(() => {
  if (analysis.value && analysis.value.length > 0) {
    return analysis.value.map((line) => {
      const l = line.toLowerCase()
      let icon = '↑'
      let type: 'pos' | 'warn' | 'info' = 'pos'
      if (l.includes('dampen') || l.includes('zero-gamma') || l.includes('long gamma')) {
        icon = '●'
        type = 'warn'
      } else if (l.includes('partial') || l.includes('structure') || l.includes('alone') || l.includes('lean')) {
        icon = '●'
        type = 'info'
      } else if (l.includes('near') || l.includes('magnet') || l.includes('call wall') || l.includes('upside')) {
        icon = '↑'
        type = 'pos'
      }
      return { line, icon, type }
    })
  }
  const lines: { line: string; icon: string; type: 'pos' | 'warn' | 'info' }[] = []
  if (featuredWall.value.level != null) {
    const pct = featuredWall.value.pct
    const pctTxt = pct == null ? '' : ` (${pct >= 0 ? '+' : ''}${(pct * 100).toFixed(1)}%)`
    lines.push({
      line: `${featuredWall.value.label} at ${usd(featuredWall.value.level)}${pctTxt}.`,
      icon: featured.value.side === 'bullish' ? '↑' : '↓',
      type: 'pos',
    })
  }
  if (dampened.value) {
    lines.push({ line: 'Long-gamma regime dampens squeeze follow-through below flip.', icon: '●', type: 'warn' })
  }
  if (featured.value.setup?.trading_implication) {
    lines.push({ line: featured.value.setup.trading_implication, icon: '●', type: 'info' })
  }
  if (!lines.length) {
    lines.push({ line: 'Insufficient structure factors for a squeeze read on this chain.', icon: '●', type: 'info' })
  }
  return lines
})

const implication = computed(() => featured.value.setup?.trading_implication ?? '')
const stronger = computed(() => featured.value.setup?.for_stronger ?? [])
const otherSide = computed(() => {
  if (featured.value.side === 'bullish') return { side: 'bearish' as const, setup: bear.value }
  return { side: 'bullish' as const, setup: bull.value }
})
</script>

<template>
  <div v-if="squeeze" class="sq" :class="featured.side">
    <!-- Hero: full ring score + bias + likelihood track -->
    <section class="hero">
      <div class="ring-block">
        <div class="ring-wrap">
          <svg class="ring-svg" viewBox="0 0 108 108" aria-hidden="true">
            <circle class="ring-track" cx="54" cy="54" r="42" />
            <circle
              class="ring-fill"
              :class="featured.side"
              cx="54"
              cy="54"
              r="42"
              :stroke-dasharray="RING_C"
              :stroke-dashoffset="ringOffset"
            />
          </svg>
          <div class="ring-center">
            <span class="score-num fig" :class="scoreCls(boardScore)">{{ boardScore }}</span>
            <span class="score-denom label">/100</span>
          </div>
        </div>
        <div class="bias-lock" :class="featured.side">
          <i class="side-dot" :class="featured.side === 'bullish' ? 'call' : 'put'" />
          <div class="bias-copy">
            <span class="bias-sub label">SQUEEZE BIAS</span>
            <strong class="bias-heading">{{ featured.side === 'bullish' ? 'BULLISH' : 'BEARISH' }}</strong>
          </div>
        </div>
      </div>

      <div class="hero-meta">
        <div class="lik-row">
          <span class="likelihood-badge label" :class="likelihood">
            {{ (likelihood || 'POSSIBLE').toUpperCase() }}
          </span>
          <span v-if="dampened" class="tag damp label">LONG Γ</span>
          <span v-else-if="fuel != null && fuel > 0" class="tag fuel label">FUEL {{ Math.round(fuel * 100) }}%</span>
        </div>

        <div class="prob-track">
          <div class="prob-track-head label">
            <span>PROBABILITY</span>
            <strong class="fig">{{ boardScore }}</strong>
          </div>
          <div class="prob-bar">
            <i class="prob-fill" :class="featured.side" :style="{ width: `${spectrumPct}%` }" />
            <span class="prob-thumb" :class="featured.side" :style="{ left: `${spectrumPct}%` }" />
          </div>
          <div class="prob-labels label">
            <span :class="{ active: likelihood === 'unlikely' }">UNLIKELY</span>
            <span :class="{ active: likelihood === 'possible' }">POSSIBLE</span>
            <span :class="{ active: likelihood === 'likely' }">LIKELY</span>
            <span :class="{ active: likelihood === 'imminent' }">IMMINENT</span>
          </div>
        </div>

        <div class="signed-row label">
          <span>SIGNED</span>
          <strong
            class="fig"
            :class="signedScore != null && signedScore > 0 ? 'call' : signedScore != null && signedScore < 0 ? 'put' : ''"
          >
            {{ signedScore == null ? '—' : `${signedScore > 0 ? '+' : ''}${signedScore}` }}
          </strong>
          <span v-if="levels?.near_spot_net_gex_m != null" class="near">
            near ${{ levels.near_spot_net_gex_m.toFixed(1) }}M
          </span>
        </div>
      </div>
    </section>

    <!-- Key levels -->
    <section v-if="levels || featuredWall.level != null" class="block levels-block">
      <div class="block-hdr label">KEY LEVELS</div>
      <div class="kl-grid">
        <div class="kl-cell">
          <span class="label">{{ featuredWall.label || 'WALL' }}</span>
          <strong class="fig" :class="featured.side === 'bullish' ? 'call' : 'put'">
            {{ featuredWall.level != null ? usd(featuredWall.level) : '—' }}
          </strong>
        </div>
        <div class="kl-cell">
          <span class="label">FLIP</span>
          <strong class="fig accent">{{ levels?.gamma_flip != null ? usd(levels.gamma_flip) : '—' }}</strong>
        </div>
        <div class="kl-cell">
          <span class="label">SPOT</span>
          <strong class="fig">{{ usd(spot ?? levels?.spot ?? featured.setup?.spot) }}</strong>
        </div>
      </div>
    </section>

    <!-- Factors -->
    <section class="block factors-block">
      <div class="block-hdr label">KEY FACTORS</div>
      <div v-if="displayFactors.length" class="factors-list">
        <div v-for="f in displayFactors" :key="f.id || f.label" class="factor-row">
          <span class="factor-title label">{{ f.label }}</span>
          <div class="factor-track" :title="f.detail || ''">
            <i
              class="factor-fill"
              :class="[factorTheme(f), scoreCls(f.max ? (f.score / f.max) * 100 : 0)]"
              :style="{ width: `${f.max ? Math.min(100, (f.score / f.max) * 100) : 0}%` }"
            />
          </div>
          <span class="factor-score fig">{{ f.score }}/{{ f.max }}</span>
        </div>
      </div>
      <p v-else class="quiet label">No factor scores on this chain yet.</p>
    </section>

    <!-- Takeaways -->
    <section class="block takeaways-block">
      <div class="block-hdr label">KEY TAKEAWAYS</div>
      <ul class="takeaways-list">
        <li v-for="(item, i) in displayTakeaways" :key="i" class="takeaway-item" :class="item.type">
          <span class="takeaway-dot" :class="item.type" aria-hidden="true" />
          <span class="takeaway-text">{{ item.line }}</span>
        </li>
      </ul>
      <p v-if="implication" class="impl-line">{{ implication }}</p>
      <div v-if="stronger.length" class="stronger">
        <div class="block-hdr label">FOR STRONGER</div>
        <ul>
          <li v-for="(s, i) in stronger" :key="i">{{ s }}</li>
        </ul>
      </div>
    </section>

    <!-- Other side -->
    <div v-if="otherSide.setup" class="other-side" :class="otherSide.side">
      <i class="side-dot" :class="otherSide.side === 'bullish' ? 'call' : 'put'" />
      <span class="label">{{ otherSide.side === 'bullish' ? 'BULL' : 'BEAR' }} ALT</span>
      <span class="fig">{{ otherSide.setup.score ?? 0 }}/100</span>
      <span class="lik label">{{ (otherSide.setup.likelihood || '—').toUpperCase() }}</span>
      <div class="otrack">
        <i :class="otherSide.side" :style="{ width: `${Math.min(100, otherSide.setup.score ?? 0)}%` }" />
      </div>
    </div>
  </div>

  <div v-else class="sq empty label">
    <strong>Squeeze unavailable</strong>
    <span>Need a chain with OI + gamma (or IV for BS gamma) to score structure.</span>
  </div>
</template>

<style scoped>
.sq {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  min-width: 0;
  min-height: 0;
  height: 100%;
  padding: var(--s3);
  background: var(--panel);
}
.sq.empty {
  min-height: 96px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s2);
  color: var(--ink-faint);
  text-align: center;
  padding: var(--s4);
}
.sq.empty strong {
  color: var(--ink-dim);
  letter-spacing: 0.08em;
  font-size: var(--t-micro);
}

/* ---- hero --------------------------------------------------------------- */
.hero {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--s4);
  align-items: center;
  padding: var(--s3) var(--s3) var(--s4);
  margin: calc(-1 * var(--s3)) calc(-1 * var(--s3)) 0;
  background: var(--void-lift);
  border-bottom: var(--hair) solid var(--rule-hi);
  flex: 0 0 auto;
}
.sq.bullish .hero { box-shadow: inset 3px 0 0 var(--call); }
.sq.bearish .hero { box-shadow: inset 3px 0 0 var(--put); }

.ring-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s2);
  min-width: 0;
}
.ring-wrap {
  position: relative;
  width: 108px;
  height: 108px;
  flex: 0 0 auto;
}
.ring-svg {
  display: block;
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}
.ring-track {
  fill: none;
  stroke: var(--rule-hi);
  stroke-width: 8;
}
.ring-fill {
  fill: none;
  stroke-width: 8;
  stroke-linecap: round;
  transition: stroke-dashoffset var(--dur) var(--ease-out);
}
.ring-fill.bullish { stroke: var(--call-hi); }
.ring-fill.bearish { stroke: var(--put-hi); }
.ring-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0;
  pointer-events: none;
  line-height: 1;
}
.score-num {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
  letter-spacing: -0.03em;
}
.sq.bullish .score-num { color: var(--call-hi); }
.sq.bearish .score-num { color: var(--put-hi); }
.score-num.hot { color: var(--warn); }
.score-num.elev { color: inherit; }
.score-num.mid { color: inherit; opacity: 0.9; }
.score-num.low { color: var(--ink-faint); }
.score-denom {
  font-size: 10px;
  color: var(--ink-faint);
  margin-top: 2px;
}

.bias-lock {
  display: flex;
  align-items: center;
  gap: var(--s2);
  min-width: 0;
}
.side-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: 0 0 auto;
}
.side-dot.call { background: var(--call); }
.side-dot.put { background: var(--put); }
.bias-copy {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.bias-sub {
  color: var(--ink-ghost);
  font-size: 9px;
  letter-spacing: 0.1em;
}
.bias-heading {
  font: 700 12px var(--font-display);
  letter-spacing: 0.06em;
  color: var(--ink);
}
.bias-lock.bullish .bias-heading { color: var(--call-hi); }
.bias-lock.bearish .bias-heading { color: var(--put-hi); }

.hero-meta {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  min-width: 0;
}
.lik-row {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}
.likelihood-badge {
  padding: 3px 8px;
  border: var(--hair) solid var(--rule-hi);
  font: 800 10px var(--font-display);
  letter-spacing: 0.08em;
  color: var(--ink-dim);
  background: var(--panel);
}
.likelihood-badge.possible,
.likelihood-badge.likely {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 55%, var(--rule));
  background: var(--warn-wash);
}
.likelihood-badge.imminent {
  color: var(--put-hi);
  border-color: var(--put);
  background: var(--put-wash);
}
.tag {
  padding: 2px 6px;
  border: var(--hair) solid var(--rule-hi);
  letter-spacing: 0.06em;
  font-size: 9px;
}
.tag.damp { color: var(--warn); border-color: var(--warn); }
.tag.fuel { color: var(--phosphor); border-color: var(--phosphor-dim); }

.prob-track {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.prob-track-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  color: var(--ink-ghost);
  letter-spacing: 0.08em;
}
.prob-track-head .fig {
  color: var(--ink);
  font-size: var(--t-body);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
}
.prob-bar {
  position: relative;
  height: 8px;
  background: var(--void);
  border: var(--hair) solid var(--rule-hi);
}
.prob-fill {
  display: block;
  height: 100%;
  transition: width var(--dur-fast) var(--ease-out);
}
.prob-fill.bullish { background: var(--call); }
.prob-fill.bearish { background: var(--put); }
.prob-thumb {
  position: absolute;
  top: 50%;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--ink);
  border: 2px solid var(--void);
  transform: translate(-50%, -50%);
  pointer-events: none;
}
.prob-thumb.bullish { background: var(--call-hi); }
.prob-thumb.bearish { background: var(--put-hi); }
.prob-labels {
  display: flex;
  justify-content: space-between;
  color: var(--ink-faint);
  font-size: 9px;
  letter-spacing: 0.04em;
}
.prob-labels .active {
  color: var(--phosphor);
  font-weight: 800;
}

.signed-row {
  display: flex;
  align-items: center;
  gap: var(--s2);
  color: var(--ink-faint);
  letter-spacing: 0.06em;
  padding-top: 2px;
  border-top: var(--hair) solid var(--rule-faint);
}
.signed-row .fig {
  color: var(--ink);
  margin-left: 2px;
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
}
.signed-row .fig.call { color: var(--call-hi); }
.signed-row .fig.put { color: var(--put-hi); }
.near { margin-left: auto; color: var(--ink-ghost); font-size: 9px; }

/* ---- shared blocks ------------------------------------------------------ */
.block {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  flex: 0 0 auto;
  min-width: 0;
}
.block-hdr {
  color: var(--ink-ghost);
  font: 700 9px var(--font-display);
  letter-spacing: 0.1em;
}

.kl-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
}
.kl-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--s2) var(--s3);
  border-right: var(--hair) solid var(--rule);
  min-width: 0;
}
.kl-cell:last-child { border-right: 0; }
.kl-cell .label {
  color: var(--ink-ghost);
  font-size: 9px;
  letter-spacing: 0.06em;
}
.kl-cell .fig {
  color: var(--ink);
  font-size: var(--t-small);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
  font-weight: 600;
  line-height: 1.2;
}
.kl-cell .fig.call { color: var(--call-hi); }
.kl-cell .fig.put { color: var(--put-hi); }
.kl-cell .fig.accent { color: var(--phosphor); }

.factors-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.factor-row {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1.5fr) auto;
  gap: var(--s2);
  align-items: center;
  min-width: 0;
}
.factor-title {
  color: var(--ink-soft);
  font: 600 10px var(--font-display);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.factor-track {
  height: 5px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  overflow: hidden;
}
.factor-fill {
  display: block;
  height: 100%;
  background: var(--ink-dim);
  transition: width var(--dur-fast) var(--ease-out);
}
.factor-fill.bullish { background: var(--call); }
.factor-fill.bearish { background: var(--put); }
.factor-fill.warn { background: var(--warn); }
.factor-fill.accent { background: var(--phosphor-dim); }
.factor-fill.hot { opacity: 1; }
.factor-fill.elev { opacity: 0.92; }
.factor-fill.mid { opacity: 0.75; }
.factor-fill.low { opacity: 0.5; }
.factor-score {
  font: 700 10px var(--font-data);
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  min-width: 3.5ch;
  text-align: right;
}
.quiet {
  color: var(--ink-dim);
  font-size: 10px;
  margin: 0;
}

.takeaways-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.takeaway-item {
  display: flex;
  gap: var(--s2);
  align-items: flex-start;
  color: var(--ink-soft);
  font-size: var(--t-tiny);
  line-height: 1.4;
  font-family: var(--font-ui);
}
.takeaway-dot {
  flex: 0 0 auto;
  width: 6px;
  height: 6px;
  margin-top: 5px;
  border-radius: 50%;
  background: var(--ink-faint);
}
.takeaway-dot.pos { background: var(--call); }
.takeaway-dot.warn { background: var(--warn); }
.takeaway-dot.info { background: var(--phosphor-dim); }
.takeaway-text { min-width: 0; }

.impl-line {
  margin: 0;
  padding-top: var(--s2);
  border-top: var(--hair) solid var(--rule-faint);
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.4;
}
.stronger {
  margin-top: 2px;
  padding: var(--s2) var(--s3);
  border: var(--hair) solid color-mix(in srgb, var(--warn) 35%, var(--rule));
  background: color-mix(in srgb, var(--warn) 8%, var(--panel));
}
.stronger ul {
  margin: var(--s1) 0 0;
  padding: 0 0 0 14px;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.4;
}
.stronger li { margin-bottom: 2px; }
.stronger li:last-child { margin-bottom: 0; }

.other-side {
  display: grid;
  grid-template-columns: auto auto 1fr auto;
  gap: 4px var(--s2);
  align-items: center;
  padding: 6px var(--s2);
  border: var(--hair) solid var(--rule);
  color: var(--ink-faint);
  letter-spacing: 0.06em;
  flex: 0 0 auto;
  margin-top: auto;
}
.other-side .fig {
  color: var(--ink);
  font-size: var(--t-micro);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
  justify-self: end;
}
.other-side .lik { color: var(--ink-faint); }
.other-side .otrack {
  grid-column: 1 / -1;
  height: 3px;
  background: var(--rule);
  overflow: hidden;
}
.other-side .otrack i {
  display: block;
  height: 100%;
  opacity: 0.75;
}
.other-side .otrack i.bullish { background: var(--call); }
.other-side .otrack i.bearish { background: var(--put); }

@media (max-width: 520px) {
  .hero { grid-template-columns: 1fr; justify-items: center; text-align: center; }
  .bias-lock { justify-content: center; }
  .hero-meta { width: 100%; }
  .signed-row .near { margin-left: 0; }
}
</style>
