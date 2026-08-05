<script setup lang="ts">
/**
 * InsiderFinance-style Gamma Squeeze Screener.
 * Primary-side probability board with factor breakdown, key levels,
 * setup analysis, and trading implication. Dual-side data still available;
 * the active (higher) side is featured — structure is never hard-zeroed.
 */
import { computed } from 'vue'
import type { OptionsSqueeze, SqueezeSetup } from '@/api'
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

/** Spectrum fill: map 0–100 score onto the likelihood track. */
const spectrumPct = computed(() => Math.max(0, Math.min(100, boardScore.value)))

function scoreCls(score: number): string {
  if (score >= 75) return 'hot'
  if (score >= 55) return 'elev'
  if (score >= 35) return 'mid'
  return 'low'
}

const featuredWall = computed(() => {
  const setup = featured.value.setup
  if (setup?.wall != null) return { level: setup.wall, pct: setup.wall_pct, label: featured.value.side === 'bullish' ? 'Call Wall' : 'Put Wall' }
  if (featured.value.side === 'bullish') {
    return { level: levels.value?.call_wall ?? null, pct: levels.value?.call_wall_pct ?? null, label: 'Call Wall' }
  }
  return { level: levels.value?.put_wall ?? null, pct: levels.value?.put_wall_pct ?? null, label: 'Put Wall' }
})

const displayFactors = computed(() => factors.value ?? [])

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
  // Real structure only — never invent takeaways when the model is quiet.
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
  <div v-if="squeeze" class="sq">
    <!-- Top Setup Hero: Circular Gauge + Probability Track -->
    <section class="setup-hero" :class="featured.side">
      <!-- Left: Semi-circular arc score gauge -->
      <div class="gauge-card">
        <div class="gauge-svg-wrap">
          <svg class="gauge-svg" viewBox="0 0 120 75" preserveAspectRatio="xMidYMid meet">
            <path
              d="M 16 62 A 44 44 0 0 1 104 62"
              fill="none"
              stroke="var(--rule-hi)"
              stroke-width="8"
              stroke-linecap="round"
            />
            <path
              d="M 16 62 A 44 44 0 0 1 104 62"
              fill="none"
              :stroke="featured.side === 'bullish' ? 'var(--call)' : 'var(--put)'"
              stroke-width="8"
              stroke-linecap="round"
              stroke-dasharray="138.2"
              :stroke-dashoffset="138.2 * (1 - boardScore / 100)"
            />
          </svg>
          <div class="gauge-inner">
            <div class="score-display">
              <span class="score-num fig">{{ boardScore }}</span>
              <span class="score-denom">/100</span>
            </div>
            <span class="likelihood-badge label" :class="likelihood">{{ (likelihood || 'POSSIBLE').toUpperCase() }}</span>
          </div>
        </div>
        <div class="bias-lockup label" :class="featured.side">
          <span class="bias-sub">SQUEEZE BIAS</span>
          <strong class="bias-heading">{{ featured.side === 'bullish' ? 'BULLISH SETUP' : 'BEARISH SETUP' }}</strong>
        </div>
      </div>

      <!-- Right: Probability Score slider bar -->
      <div class="prob-track-block">
        <div class="prob-track-head label">
          <span>PROBABILITY SCORE</span>
        </div>
        <div class="prob-track-bar">
          <div class="prob-track-bg">
            <i class="prob-track-fill" :class="featured.side" :style="{ width: `${spectrumPct}%` }" />
            <span class="prob-track-thumb" :style="{ left: `${spectrumPct}%` }" />
          </div>
        </div>
        <div class="prob-track-labels label">
          <span :class="{ active: likelihood === 'unlikely' }">UNLIKELY</span>
          <span :class="{ active: likelihood === 'possible' }">POSSIBLE</span>
          <span :class="{ active: likelihood === 'likely' }">LIKELY</span>
          <span :class="{ active: likelihood === 'imminent' }">IMMINENT</span>
        </div>
      </div>
    </section>

    <!-- Key levels: wall / flip / spot -->
    <section class="levels-section" v-if="levels || featuredWall.level != null">
      <div class="section-hdr label">KEY LEVELS</div>
      <div class="kl-grid">
        <div class="kl-row">
          <span class="label">{{ featuredWall.label || 'WALL' }}</span>
          <strong class="fig" :class="featured.side === 'bullish' ? 'call' : 'put'">
            {{ featuredWall.level != null ? usd(featuredWall.level) : '—' }}
          </strong>
        </div>
        <div class="kl-row">
          <span class="label">FLIP</span>
          <strong class="fig accent">{{ levels?.gamma_flip != null ? usd(levels.gamma_flip) : '—' }}</strong>
        </div>
        <div class="kl-row">
          <span class="label">SPOT</span>
          <strong class="fig">{{ usd(spot ?? levels?.spot ?? featured.setup?.spot) }}</strong>
        </div>
      </div>
    </section>

    <!-- Key Factors Breakdown -->
    <section class="factors-section">
      <div class="section-hdr label">KEY FACTORS</div>
      <div v-if="displayFactors.length" class="factors-list">
        <div v-for="f in displayFactors" :key="f.id || f.label" class="factor-row">
          <div class="factor-label-wrap">
            <span class="factor-title label">{{ f.label }}</span>
          </div>
          <div class="factor-bar-wrap" :title="f.detail || ''">
            <div class="factor-track">
              <i
                class="factor-fill"
                :class="[featured.side, scoreCls(f.max ? (f.score / f.max) * 100 : 0)]"
                :style="{ width: `${f.max ? Math.min(100, (f.score / f.max) * 100) : 0}%` }"
              />
            </div>
          </div>
          <span class="factor-score fig">{{ f.score }}/{{ f.max }}</span>
        </div>
      </div>
      <p v-else class="quiet label">No factor scores on this chain yet.</p>
    </section>

    <!-- Key Takeaways -->
    <section class="takeaways-section">
      <div class="section-hdr label">KEY TAKEAWAYS</div>
      <ul class="takeaways-list">
        <li v-for="(item, i) in displayTakeaways" :key="i" class="takeaway-item" :class="item.type">
          <span class="takeaway-badge" :class="item.type">{{ item.icon }}</span>
          <span class="takeaway-text label">{{ item.line }}</span>
        </li>
      </ul>
      <p v-if="implication" class="impl-line">{{ implication }}</p>
      <div v-if="stronger.length" class="stronger">
        <div class="section-hdr label">FOR STRONGER</div>
        <ul>
          <li v-for="(s, i) in stronger" :key="i">{{ s }}</li>
        </ul>
      </div>
    </section>

    <!-- Other side + metadata -->
    <div v-if="otherSide.setup" class="other-side" :class="otherSide.side">
      <span>{{ otherSide.side === 'bullish' ? 'BULL' : 'BEAR' }} ALT</span>
      <span class="fig">{{ otherSide.setup.score ?? 0 }}/100</span>
      <span class="lik">{{ (otherSide.setup.likelihood || '—').toUpperCase() }}</span>
      <div class="otrack"><i :style="{ width: `${Math.min(100, otherSide.setup.score ?? 0)}%` }" /></div>
    </div>

    <div class="meta-strip label">
      <span>
        Signed
        <strong class="fig" :class="signedScore != null && signedScore > 0 ? 'call' : signedScore != null && signedScore < 0 ? 'put' : ''">
          {{ signedScore == null ? '—' : `${signedScore > 0 ? '+' : ''}${signedScore}` }}
        </strong>
      </span>
      <span v-if="dampened" class="tag damp">LONG Γ</span>
      <span v-else-if="fuel != null && fuel > 0" class="tag fuel">FUEL {{ Math.round(fuel * 100) }}%</span>
      <span v-if="levels?.near_spot_net_gex_m != null" class="near">
        near ${{ levels.near_spot_net_gex_m.toFixed(1) }}M
      </span>
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
  gap: 6px;
  min-width: 0;
  min-height: 0;
  height: 100%;
}
.sq.empty {
  min-height: 48px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s1);
  color: var(--ink-faint);
  text-align: center;
  padding: var(--s2);
}
.sq.empty strong {
  color: var(--ink-dim);
  letter-spacing: 0.08em;
  font-size: var(--t-micro);
}

.bolt { color: var(--phosphor); font-size: var(--t-micro); }
.bias {
  padding: 1px 6px;
  border: var(--hair) solid var(--rule-hi);
  letter-spacing: 0.08em;
  font-size: 9px;
  font-weight: 700;
  color: var(--ink-dim);
}
.bias.bullish { color: var(--call); border-color: rgba(98, 182, 203, 0.45); background: var(--call-wash); }
.bias.bearish { color: var(--put); border-color: rgba(213, 163, 95, 0.45); background: var(--put-wash); }

.primary-card {
  background: transparent;
  padding: 2px 0 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-radius: 0;
  flex: 0 0 auto;
}
.primary-card.bullish { box-shadow: inset 2px 0 0 var(--call); padding-left: 8px; }
.primary-card.bearish { box-shadow: inset 2px 0 0 var(--put); padding-left: 8px; }

.pc-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
}
.pc-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink);
  font-size: var(--t-small);
  flex-wrap: wrap;
}
.pc-title .bolt { font-size: 10px; }
.likelihood-pill {
  padding: 1px 6px;
  border: var(--hair) solid var(--rule-hi);
  letter-spacing: 0.1em;
  font-size: 10px;
  font-weight: 800;
  color: var(--ink-dim);
}
.likelihood-pill.possible,
.likelihood-pill.likely { color: var(--warn); border-color: rgba(232, 184, 74, 0.5); }
.likelihood-pill.imminent { color: var(--put-hi); border-color: var(--put); }

.prob-block { display: flex; flex-direction: column; gap: 4px; }
.prob-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  color: var(--ink-ghost);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-size: var(--t-micro);
}
.prob-head .fig {
  font-size: 1.125rem;
  font-weight: 500;
  letter-spacing: -0.03em;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
}
.prob-head .fig small {
  font-size: var(--t-tiny);
  color: var(--ink-faint);
  margin-left: 2px;
  font-weight: 400;
}
.prob-head .fig.hot { color: var(--warn); }
.prob-head .fig.elev { color: var(--ink); }
.prob-head .fig.mid { color: var(--ink-soft); }
.prob-head .fig.low { color: var(--ink-faint); }

.spectrum {
  position: relative;
  height: 5px;
  background: var(--rule);
  overflow: visible;
  border-radius: 0;
}
.spectrum .fill {
  display: block;
  height: 100%;
  border-radius: 0;
  transition: width var(--dur-fast) var(--ease-out);
}
/* Flat fills — instrument aesthetic, no encoded gradient */
.spectrum .fill.bullish { background: var(--call); }
.spectrum .fill.bearish { background: var(--put); }
.spectrum .tick {
  position: absolute;
  top: -2px;
  width: 2px;
  height: 10px;
  background: var(--ink-faint);
  transform: translateX(-50%);
  opacity: 0.35;
}
.spectrum .tick.on { background: var(--ink); opacity: 1; height: 12px; top: -3px; }
.spectrum-labels {
  display: flex;
  justify-content: space-between;
  color: var(--ink-faint);
  font-size: 9px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.section-lab {
  color: var(--ink-faint);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  margin-bottom: 3px;
  font-size: 9px;
}

.factors { display: flex; flex-direction: column; gap: 3px; }
.factor { margin-bottom: 0; }
.factor-top {
  display: flex;
  justify-content: space-between;
  margin-bottom: 1px;
  gap: var(--s2);
}
.factor-top .label {
  color: var(--ink-dim);
  font-size: var(--t-micro);
}
.factor-top .fig {
  font-size: var(--t-micro);
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
}
.ftrack {
  height: 3px;
  background: var(--rule);
  overflow: hidden;
  border-radius: 0;
}
.ftrack i {
  display: block;
  height: 100%;
  background: var(--ink-dim);
  transition: width var(--dur-fast) var(--ease-out);
}
.ftrack i.bullish { background: var(--call); }
.ftrack i.bearish { background: var(--put); }
.ftrack i.hot { opacity: 1; }
.ftrack i.low { opacity: 0.45; }

/* Key levels: 3-up scannable cells */
.key-levels { display: flex; flex-direction: column; gap: 0; }
.key-levels .section-lab { margin-bottom: 4px; }
.kl-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0;
  border: var(--hair) solid var(--rule);
}
.kl-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 5px 7px;
  border-right: var(--hair) solid var(--rule);
  min-width: 0;
}
.kl-row:last-child { border-right: 0; }
.kl-row .label {
  color: var(--ink-ghost);
  font-size: 9px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.kl-row .fig {
  color: var(--ink);
  font-size: var(--t-small);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
  font-weight: 600;
  line-height: 1.2;
}
.kl-row .fig.call { color: var(--call); }
.kl-row .fig.put { color: var(--put); }
.kl-row .fig.accent { color: var(--phosphor); }
.kl-row .pct {
  margin-left: 4px;
  color: var(--ink-faint);
  font-size: 9px;
  font-weight: 400;
}

.analysis {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.analysis li {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.35;
}
.analysis .dot {
  flex: 0 0 6px;
  width: 6px;
  height: 6px;
  margin-top: 4px;
  border-radius: 50%;
  background: var(--ink-faint);
}
.analysis li.pos .dot { background: var(--call); }
.analysis li.neg .dot { background: var(--put); }
.analysis li.warn .dot { background: var(--warn); }

.stronger {
  padding: 6px var(--s2);
  border: var(--hair) solid rgba(232, 184, 74, 0.35);
  background: color-mix(in srgb, var(--warn) 8%, var(--panel));
}
.stronger ul {
  margin: 0;
  padding: 0 0 0 12px;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.35;
}
.stronger li { margin-bottom: 2px; }
.stronger li:last-child { margin-bottom: 0; }

.impl-line {
  margin: 0;
  color: var(--ink-soft);
  font-size: var(--t-tiny);
  line-height: 1.35;
  padding-top: 2px;
  border-top: var(--hair) solid var(--rule-faint);
}

.other-side {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 4px var(--s2);
  align-items: center;
  padding: 3px 6px;
  border: var(--hair) solid var(--rule);
  color: var(--ink-faint);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  font-size: 10px;
  flex: 0 0 auto;
}
.other-side .fig {
  color: var(--ink);
  font-size: var(--t-micro);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
}
.other-side .lik { color: var(--ink-faint); }
.other-side .otrack {
  grid-column: 1 / -1;
  height: 2px;
  background: var(--rule);
  overflow: hidden;
}
.other-side.bullish .otrack i { display: block; height: 100%; background: var(--call); opacity: 0.7; }
.other-side.bearish .otrack i { display: block; height: 100%; background: var(--put); opacity: 0.7; }

.meta-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 4px var(--s2);
  align-items: center;
  padding: 3px 6px;
  border: var(--hair) solid var(--rule);
  color: var(--ink-faint);
  letter-spacing: 0.06em;
  font-size: var(--t-micro);
  flex: 0 0 auto;
}
.meta-strip .fig {
  color: var(--ink);
  margin-left: 4px;
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
}
.meta-strip .fig.call { color: var(--call); }
.meta-strip .fig.put { color: var(--put); }
.tag {
  padding: 1px 5px;
  border: var(--hair) solid var(--rule-hi);
  letter-spacing: 0.06em;
  font-size: 9px;
}
.tag.damp { color: var(--warn); border-color: var(--warn); }
.tag.fuel { color: var(--phosphor); border-color: var(--phosphor-dim); }
.near { margin-left: auto; color: var(--ink-faint); }

.sq-detail {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
}
.sq-detail > summary {
  cursor: pointer;
  padding: 4px 6px;
  color: var(--ink-dim);
  list-style: none;
  letter-spacing: 0.06em;
}
.sq-detail > summary::-webkit-details-marker { display: none; }
.sq-detail[open] > summary {
  border-bottom: var(--hair) solid var(--rule);
  color: var(--ink-soft);
}
.sq-detail .analysis-block,
.sq-detail .stronger,
.sq-detail .sig-strip { padding: 6px; }

.sig-strip {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sig-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 6px;
  align-items: center;
  padding: 3px 4px;
  border-left: 2px solid var(--rule-hi);
  min-width: 0;
}
.sig-row .title {
  color: var(--ink-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sig-row .fig { color: var(--ink-faint); font-size: 10px; }
.str { font-weight: 800; font-size: 9px; }
.str.strong { color: var(--warn); }
.str.moderate { color: var(--ink-soft); }
.str.weak { color: var(--ink-faint); }
.sig-row.volatility { border-left-color: var(--warn); }
.sig-row.support { border-left-color: var(--put); }
.sig-row.resistance { border-left-color: var(--call); }
.sig-row.regime_flip { border-left-color: var(--phosphor-dim); }

.foot {
  color: var(--ink-faint);
  text-align: center;
  letter-spacing: 0.06em;
  margin: 0;
  font-size: 9px;
  flex: 0 0 auto;
}

/* ---- live layout used by the template (was missing → broken UI) -------- */
.setup-hero {
  display: grid;
  grid-template-columns: minmax(120px, 0.9fr) minmax(0, 1.4fr);
  gap: 8px;
  align-items: center;
  padding: 6px 8px 4px;
  border-bottom: var(--hair) solid var(--rule);
  flex: 0 0 auto;
}
.setup-hero.bullish { box-shadow: inset 3px 0 0 var(--call); }
.setup-hero.bearish { box-shadow: inset 3px 0 0 var(--put); }
.gauge-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.gauge-svg-wrap {
  position: relative;
  width: 100%;
  max-width: 140px;
}
.gauge-svg { display: block; width: 100%; height: auto; }
.gauge-inner {
  position: absolute;
  left: 50%;
  bottom: 4px;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  pointer-events: none;
}
.score-display {
  display: flex;
  align-items: baseline;
  gap: 2px;
  line-height: 1;
}
.score-num {
  font-size: 1.35rem;
  font-weight: 700;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
}
.score-denom { font-size: 10px; color: var(--ink-faint); }
.likelihood-badge {
  padding: 1px 6px;
  border: var(--hair) solid var(--rule-hi);
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: var(--ink-dim);
}
.likelihood-badge.possible,
.likelihood-badge.likely { color: var(--warn); border-color: rgba(232, 184, 74, 0.55); }
.likelihood-badge.imminent { color: var(--put-hi); border-color: var(--put); }
.bias-lockup {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  text-align: center;
}
.bias-sub { color: var(--ink-faint); font-size: 9px; letter-spacing: 0.1em; }
.bias-heading {
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ink);
}
.bias-lockup.bullish .bias-heading { color: var(--call); }
.bias-lockup.bearish .bias-heading { color: var(--put); }

.prob-track-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  padding: 4px 2px;
}
.prob-track-head {
  color: var(--ink-faint);
  letter-spacing: 0.08em;
  font-size: 9px;
}
.prob-track-bar { padding: 4px 0; }
.prob-track-bg {
  position: relative;
  height: 8px;
  background: var(--rule);
  border: var(--hair) solid var(--rule-hi);
}
.prob-track-fill {
  display: block;
  height: 100%;
  transition: width var(--dur-fast) var(--ease-out);
}
.prob-track-fill.bullish { background: var(--call); }
.prob-track-fill.bearish { background: var(--put); }
.prob-track-thumb {
  position: absolute;
  top: 50%;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--ink);
  border: 2px solid var(--void);
  transform: translate(-50%, -50%);
  box-shadow: 0 0 0 1px var(--rule-hi);
}
.prob-track-labels {
  display: flex;
  justify-content: space-between;
  color: var(--ink-faint);
  font-size: 9px;
  letter-spacing: 0.05em;
}
.prob-track-labels .active { color: var(--ink); font-weight: 800; }

.section-hdr {
  color: var(--ink-faint);
  letter-spacing: 0.1em;
  font-size: 9px;
  margin-bottom: 4px;
  padding: 0 8px;
}
.levels-section,
.factors-section,
.takeaways-section {
  padding: 4px 0;
  flex: 0 0 auto;
  border-bottom: var(--hair) solid var(--rule-faint);
}
.levels-section .kl-grid {
  margin: 0 8px;
  border: var(--hair) solid var(--rule);
}
.factors-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 0 8px 4px;
}
.factor-row {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1.6fr) auto;
  gap: 6px;
  align-items: center;
  min-width: 0;
}
.factor-label-wrap { min-width: 0; }
.factor-title {
  color: var(--ink-dim);
  font-size: 10px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.factor-track {
  height: 4px;
  background: var(--rule);
  overflow: hidden;
}
.factor-fill {
  display: block;
  height: 100%;
  background: var(--ink-dim);
}
.factor-fill.bullish { background: var(--call); }
.factor-fill.bearish { background: var(--put); }
.factor-fill.hot { opacity: 1; }
.factor-fill.low { opacity: 0.45; }
.factor-score {
  font-size: 10px;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
  min-width: 3.5ch;
  text-align: right;
}
.quiet { padding: 4px 8px; color: var(--ink-faint); font-size: 10px; }

.takeaways-list {
  list-style: none;
  margin: 0;
  padding: 0 8px 4px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.takeaway-item {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  color: var(--ink-dim);
  font-size: 11px;
  line-height: 1.35;
}
.takeaway-badge {
  flex: 0 0 auto;
  width: 14px;
  text-align: center;
  font-size: 10px;
  line-height: 1.4;
}
.takeaway-badge.pos { color: var(--call); }
.takeaway-badge.warn { color: var(--warn); }
.takeaway-badge.info { color: var(--phosphor-dim); }
.takeaway-text { min-width: 0; }
.takeaways-section .impl-line {
  margin: 4px 8px 0;
  padding-top: 4px;
}
.takeaways-section .stronger {
  margin: 6px 8px 0;
}

@media (max-width: 520px) {
  .setup-hero { grid-template-columns: 1fr; }
}
</style>
