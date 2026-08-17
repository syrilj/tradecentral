<script setup lang="ts">
/**
 * Gamma Squeeze Screener — primary-side probability board with circular score,
 * factor breakdown, key levels, and takeaways. Dual-side data still available;
 * the active (higher) side is featured. Structure is never hard-zeroed.
 */
import { computed } from 'vue'
import type { OptionsSqueeze, SqueezeFactor } from '@/api'
import { optUsd } from '@/format'
import {
  calculateFeaturedSetup,
  calculateRingOffset,
  formatNearSpotGex,
  calculateTrackWidthPct,
  buildTakeaways,
  RING_CIRCUMFERENCE,
} from '@/squeezeCalc'

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
const featured = computed(() =>
  calculateFeaturedSetup(primary.value, bull.value, bear.value, signedScore.value),
)

const boardScore = computed(() => featured.value.setup?.score ?? 0)
const likelihood = computed(() => featured.value.setup?.likelihood ?? 'unlikely')
const factors = computed(() => featured.value.setup?.factors ?? [])
const analysis = computed(() => featured.value.setup?.setup_analysis ?? [])
const spectrumPct = computed(() => Math.max(0, Math.min(100, Math.abs(boardScore.value))))

/** Full ring: circumference of r=42 → 2πr ≈ 263.9 */
const RING_C = RING_CIRCUMFERENCE
const ringOffset = computed(() => calculateRingOffset(boardScore.value, RING_C))

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

const displayTakeaways = computed(() =>
  buildTakeaways({
    analysis: analysis.value,
    side: featured.value.side,
    wallLevel: featuredWall.value.level,
    wallPct: featuredWall.value.pct,
    wallLabel: featuredWall.value.label,
    dampened: dampened.value,
    implication: featured.value.setup?.trading_implication ?? '',
  }),
)

const implication = computed(() => featured.value.setup?.trading_implication ?? '')
const stronger = computed(() => featured.value.setup?.for_stronger ?? [])
const otherSide = computed(() => {
  if (featured.value.side === 'bullish') return { side: 'bearish' as const, setup: bear.value }
  return { side: 'bullish' as const, setup: bull.value }
})
</script>

<template>
  <div v-if="squeeze" class="sq" :class="featured.side">
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
          <div class="prob-zones" :class="[likelihood, featured.side]">
            <span class="zone" data-zone="unlikely"><i />UNLIKELY</span>
            <span class="zone" data-zone="possible"><i />POSSIBLE</span>
            <span class="zone" data-zone="likely"><i />LIKELY</span>
            <span class="zone" data-zone="imminent"><i />IMMINENT</span>
            <i class="prob-thumb" :class="featured.side" :style="{ left: `${spectrumPct}%` }" />
          </div>
        </div>

        <div class="signed-block label">
          <div class="signed-line">
            <span class="signed-key">SIGNED</span>
            <strong
              class="fig"
              :class="signedScore != null && signedScore > 0 ? 'call' : signedScore != null && signedScore < 0 ? 'put' : ''"
            >
              {{ signedScore == null ? '+0' : `${signedScore > 0 ? '+' : ''}${signedScore}` }}
            </strong>
          </div>
          <span v-if="levels?.near_spot_net_gex_m != null" class="near">
            near {{ formatNearSpotGex(levels.near_spot_net_gex_m) }}
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
            {{ featuredWall.level != null ? optUsd(featuredWall.level) : '$0.00' }}
          </strong>
        </div>
        <div class="kl-cell">
          <span class="label">FLIP</span>
          <strong class="fig accent">{{ levels?.gamma_flip != null ? optUsd(levels.gamma_flip) : '$0.00' }}</strong>
        </div>
        <div class="kl-cell">
          <span class="label">SPOT</span>
          <strong class="fig">{{ optUsd(spot ?? levels?.spot ?? featured.setup?.spot) }}</strong>
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
              :style="{ width: `${calculateTrackWidthPct(f.score, f.max)}%` }"
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
      <span class="lik label">{{ (otherSide.setup.likelihood || 'UNLIKELY').toUpperCase() }}</span>
      <div class="otrack">
        <i :class="otherSide.side" :style="{ width: `${calculateTrackWidthPct(otherSide.setup.score, 100)}%` }" />
      </div>
    </div>
  </div>

  <div v-else class="sq empty label">
    <strong>Squeeze unavailable</strong>
    <span>Need a chain with OI + gamma (or IV for BS gamma) to score structure.</span>
  </div>
</template>

<style scoped>
/* =========================================================================
   Squeeze Screener — instrument-grade probability board.
   The panel carries real depth: a tinted substrate keyed to the featured side,
   a substantial score dial with a background disc and tick marks, weighted
   factor readouts, and key-level cells that feel machined rather than printed.
   ========================================================================= */

.sq {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  min-width: 0;
  min-height: 0;
  height: 100%;
  padding: var(--s4);
  background:
    linear-gradient(180deg, var(--void-lift) 0%, var(--void) 100%);
  border-radius: var(--r-sm);
  position: relative;
  overflow: hidden;
}
/* Side-tinted personality — a subtle vertical wash that keys the whole
   panel to the featured direction without resorting to glow. */
.sq.bullish {
  background:
    linear-gradient(180deg,
      color-mix(in srgb, var(--call-wash) 40%, var(--void-lift)) 0%,
      var(--void) 55%,
      var(--void) 100%);
}
.sq.bearish {
  background:
    linear-gradient(180deg,
      color-mix(in srgb, var(--put-wash) 40%, var(--void-lift)) 0%,
      var(--void) 55%,
      var(--void) 100%);
}
/* Left accent edge — solid, not a shadow. */
.sq.bullish::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
  background: linear-gradient(180deg, var(--call-hi), var(--call) 60%, transparent);
}
.sq.bearish::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
  background: linear-gradient(180deg, var(--put-hi), var(--put) 60%, transparent);
}

.sq.empty {
  min-height: 120px;
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
  padding: 0 0 var(--s4);
  background: transparent;
  border-bottom: var(--hair) solid var(--rule);
  flex: 0 0 auto;
}

.ring-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s2);
  min-width: 0;
}
.ring-wrap {
  position: relative;
  width: 104px;
  height: 104px;
  flex: 0 0 auto;
}
/* Background disc gives the dial visual mass even at score 0. */
.ring-wrap::before {
  content: '';
  position: absolute;
  inset: 8px;
  border-radius: 50%;
  background: var(--void);
  border: var(--hair) solid var(--rule-faint);
}
.ring-svg {
  display: block;
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
  position: relative;
  z-index: 1;
}
.ring-track {
  fill: none;
  stroke: var(--rule);
  stroke-width: 6;
}
.ring-fill {
  fill: none;
  stroke-width: 6;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.6s cubic-bezier(0.22, 1, 0.36, 1);
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
  z-index: 2;
}
.score-num {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
  letter-spacing: -0.04em;
}
.sq.bullish .score-num { color: var(--call-hi); }
.sq.bearish .score-num { color: var(--put-hi); }
.sq.bullish .score-num.hot { color: var(--call-hi); }
.sq.bearish .score-num.hot { color: var(--put-hi); }
.score-num.elev { color: inherit; }
.score-num.mid { color: inherit; opacity: 0.9; }
.score-num.low { color: var(--ink-faint); }
.score-denom {
  font-size: var(--t-micro);
  color: var(--ink-faint);
  margin-top: 1px;
  font-weight: 600;
}

.bias-lock {
  display: flex;
  align-items: center;
  gap: var(--s1);
  min-width: 0;
  padding: 4px var(--s2);
  border-radius: var(--r-xs);
  background: var(--panel);
  border: var(--hair) solid var(--rule);
}
.side-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: 0 0 auto;
}
.side-dot.call { background: var(--call-hi); box-shadow: 0 0 0 2px color-mix(in srgb, var(--call) 25%, transparent); }
.side-dot.put { background: var(--put-hi); box-shadow: 0 0 0 2px color-mix(in srgb, var(--put) 25%, transparent); }
.bias-copy {
  display: flex;
  flex-direction: column;
  gap: 0;
  min-width: 0;
}
.bias-sub {
  color: var(--ink-ghost);
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
}
.bias-heading {
  font: 800 var(--t-tiny) var(--font-display);
  letter-spacing: 0.08em;
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
  gap: 8px;
  flex-wrap: wrap;
}
.likelihood-badge {
  padding: 4px 10px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  font: 800 var(--t-micro) var(--font-display);
  letter-spacing: 0.12em;
  color: var(--ink-dim);
  background: var(--void-lift);
}
.likelihood-badge.possible {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 55%, var(--rule));
  background: var(--warn-wash);
}
.likelihood-badge.likely {
  color: var(--call-hi);
  border-color: color-mix(in srgb, var(--call) 55%, var(--rule));
  background: var(--call-wash);
}
.likelihood-badge.imminent {
  color: var(--put-hi);
  border-color: var(--put);
  background: var(--put-wash);
}
.tag {
  padding: 4px 10px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  letter-spacing: 0.1em;
  font: 700 var(--t-micro) var(--font-display);
}
.tag.damp { color: var(--warn); border-color: var(--warn); background: var(--warn-wash); }
.tag.fuel {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

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
  letter-spacing: 0.1em;
}
.prob-track-head .fig {
  color: var(--ink);
  font-size: var(--t-small);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
}

/* Zone-segmented spectrum: 4 equal zones with the active one highlighted.
   Each zone is a machined slot — bar on top, label below — with the active
   zone filled in the side accent and the marker thumb sliding across. */
.prob-zones {
  position: relative;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 3px;
  padding-top: 10px;
}
.prob-zones .zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  font-size: var(--t-micro);
  letter-spacing: 0.04em;
  color: var(--ink-faint);
  font-weight: 600;
  font-family: var(--font-display);
  text-align: center;
}
.prob-zones .zone > i {
  display: block;
  width: 100%;
  height: 6px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  order: -1;
}
/* Active zone: label lifts to ink, segment fills with the side accent. */
.prob-zones.unlikely .zone[data-zone='unlikely'],
.prob-zones.possible .zone[data-zone='possible'],
.prob-zones.likely .zone[data-zone='likely'],
.prob-zones.imminent .zone[data-zone='imminent'] {
  color: var(--ink);
  font-weight: 800;
}
.prob-zones.unlikely .zone[data-zone='unlikely'] > i { background: var(--ink-faint); border-color: var(--rule-hi); }
.prob-zones.possible .zone[data-zone='possible'] > i { background: var(--warn); border-color: var(--warn); }
.prob-zones.likely .zone[data-zone='likely'] > i { background: var(--warn); border-color: var(--warn); }
.prob-zones.imminent .zone[data-zone='imminent'] > i { background: var(--put); border-color: var(--put); }
/* Side-tinted fill for the featured direction on the active segment. */
.prob-zones.bullish .zone[data-zone='likely'] > i,
.prob-zones.bullish .zone[data-zone='imminent'] > i { background: var(--call-hi); border-color: var(--call); }
.prob-zones.bearish .zone[data-zone='likely'] > i,
.prob-zones.bearish .zone[data-zone='imminent'] > i { background: var(--put-hi); border-color: var(--put); }
/* Marker thumb that slides across the zone track to the score position. */
.prob-thumb {
  position: absolute;
  top: 7px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--ink);
  border: 2px solid var(--panel);
  transform: translate(-50%, 0);
  pointer-events: none;
  box-shadow: 0 0 0 1px var(--rule-hi), 0 1px 3px rgba(0,0,0,0.4);
  transition: left var(--dur) var(--ease-out);
}
.prob-thumb.bullish { background: var(--call-hi); }
.prob-thumb.bearish { background: var(--put-hi); }

/* Signed block: stacked so the figure and the near-spot GEX never collide. */
.signed-block {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: var(--s2) var(--s3);
  border-radius: var(--r-xs);
  background: var(--panel);
  border: var(--hair) solid var(--rule-faint);
}
.signed-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
  color: var(--ink-faint);
  letter-spacing: 0.08em;
}
.signed-line .signed-key { font-size: var(--t-micro); font-weight: 600; }
.signed-line .fig {
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-small);
}
.signed-line .fig.call { color: var(--call-hi); }
.signed-line .fig.put { color: var(--put-hi); }
.signed-block .near {
  color: var(--ink-ghost);
  font-size: var(--t-micro);
  letter-spacing: 0.04em;
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
}

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
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.12em;
  padding-bottom: 4px;
  border-bottom: var(--hair) solid var(--rule-faint);
}

/* ---- key levels: machined cells with top accent bar --------------------- */
.kl-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 3px;
  border-radius: var(--r-sm);
  overflow: hidden;
  background: var(--rule-faint);
}
.kl-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px var(--s3);
  min-width: 0;
  background: var(--panel);
  position: relative;
}
/* Top accent bar — colored by which level this cell represents. */
.kl-cell::before {
  content: '';
  position: absolute;
  left: 0; right: 0; top: 0;
  height: 2px;
  background: var(--rule-hi);
}
.kl-cell:first-child::before { background: var(--call); }
.sq.bearish .kl-cell:first-child::before { background: var(--put); }
.kl-cell:nth-child(2)::before { background: var(--phosphor-dim); }
.kl-cell:last-child::before { background: var(--ink-dim); }
.kl-cell .label {
  color: var(--ink-ghost);
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
  font-weight: 600;
}
.kl-cell .fig {
  color: var(--ink);
  font-size: var(--t-body);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
  font-weight: 700;
  line-height: 1.2;
}
.kl-cell .fig.call { color: var(--call-hi); }
.kl-cell .fig.put { color: var(--put-hi); }
.kl-cell .fig.accent { color: var(--phosphor); }

/* ---- factors: weighted readouts with groove tracks --------------------- */
.factors-list {
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.factor-row {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1.4fr) auto;
  gap: var(--s2);
  align-items: center;
  min-width: 0;
}
.factor-title {
  color: var(--ink-soft);
  font: 600 var(--t-micro) var(--font-display);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: 0.02em;
}
.factor-track {
  height: 8px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  overflow: hidden;
  box-shadow: inset 0 1px 2px rgba(0,0,0,0.3);
}
.factor-fill {
  display: block;
  height: 100%;
  background: var(--ink-dim);
  border-radius: var(--r-sm);
  transition: width var(--dur) var(--ease-out);
}
.factor-fill.bullish { background: linear-gradient(90deg, var(--call), var(--call-hi)); }
.factor-fill.bearish { background: linear-gradient(90deg, var(--put), var(--put-hi)); }
.factor-fill.warn { background: linear-gradient(90deg, var(--warn), var(--warn)); }
.factor-fill.accent { background: linear-gradient(90deg, var(--phosphor-dim), var(--phosphor)); }
.factor-fill.hot { opacity: 1; }
.factor-fill.elev { opacity: 0.92; }
.factor-fill.mid { opacity: 0.78; }
.factor-fill.low { opacity: 0.5; }
.factor-score {
  font: 700 var(--t-micro) var(--font-data);
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  min-width: 4ch;
  text-align: right;
  font-size: var(--t-tiny);
}
.quiet {
  color: var(--ink-dim);
  font-size: var(--t-micro);
  margin: 0;
}

/* ---- takeaways ---------------------------------------------------------- */
.takeaways-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.takeaway-item {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  color: var(--ink-soft);
  font-size: var(--t-tiny);
  line-height: 1.45;
  font-family: var(--font-ui);
}
.takeaway-dot {
  flex: 0 0 auto;
  width: 7px;
  height: 7px;
  margin-top: 5px;
  border-radius: 50%;
  background: var(--ink-faint);
}
.takeaway-dot.pos { background: var(--call-hi); }
.takeaway-dot.neg { background: var(--put); }
.takeaway-dot.warn { background: var(--warn); }
.takeaway-dot.info { background: var(--phosphor); }
.takeaway-text { min-width: 0; }

.impl-line {
  margin: 0;
  padding: var(--s2) var(--s3);
  border-radius: var(--r-xs);
  background: var(--void-lift);
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.45;
  border-left: 2px solid var(--phosphor-dim);
}
.stronger {
  margin-top: 4px;
  padding: var(--s2) var(--s3);
  border: var(--hair) solid color-mix(in srgb, var(--warn) 35%, var(--rule));
  border-radius: var(--r-sm);
  background: var(--warn-wash);
}
.stronger ul {
  margin: var(--s1) 0 0;
  padding: 0 0 0 14px;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.45;
}
.stronger li { margin-bottom: 3px; }
.stronger li:last-child { margin-bottom: 0; }

/* ---- other side: compact alt readout ------------------------------------ */
.other-side {
  display: grid;
  grid-template-columns: auto auto 1fr auto;
  gap: 4px var(--s2);
  align-items: center;
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--panel);
  color: var(--ink-faint);
  letter-spacing: 0.08em;
  flex: 0 0 auto;
  margin-top: auto;
}
.other-side .fig {
  color: var(--ink);
  font-size: var(--t-tiny);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
  font-weight: 700;
  justify-self: end;
}
.other-side .lik { color: var(--ink-faint); font-weight: 600; }
.other-side .otrack {
  grid-column: 1 / -1;
  height: 4px;
  background: var(--void);
  border: var(--hair) solid var(--rule-faint);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.other-side .otrack i {
  display: block;
  height: 100%;
  border-radius: var(--r-xs);
  opacity: 0.8;
}
.other-side .otrack i.bullish { background: var(--call); }
.other-side .otrack i.bearish { background: var(--put); }

@media (max-width: 520px) {
  .hero { grid-template-columns: 1fr; justify-items: center; text-align: center; }
  .bias-lock { justify-content: center; }
  .hero-meta { width: 100%; }
  .signed-block .near { margin-left: 0; }
}
</style>
