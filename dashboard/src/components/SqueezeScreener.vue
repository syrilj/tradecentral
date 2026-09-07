<script setup lang="ts">
/**
 * Gamma squeeze board — theory identity, factor breakdown, price ladder.
 *
 * The headline number is the signed theory score (fuel × signed flow/momentum),
 * not a probability a squeeze fires. Structure meters stay secondary. Unmeasured
 * inputs render as an em-dash, never a fake zero.
 */
import { computed } from 'vue'
import type { OptionsSqueeze, SqueezeFactor } from '@/api'
import { optUsd, DASH } from '@/format'
import HelpTip from '@/components/HelpTip.vue'
import {
  calculateFeaturedSetup,
  calculateRingOffset,
  formatNearSpotGex,
  calculateTrackWidthPct,
  buildTakeaways,
  buildLevelLadder,
  gammaRegimeSide,
  freshnessTier,
  formatAge,
  isSetupMeasured,
  formatSignedScore,
  buildTheoryIdentity,
  RING_CIRCUMFERENCE,
} from '@/squeezeCalc'

const props = defineProps<{
  squeeze: OptionsSqueeze | null | undefined
  spot?: number | null
  /** Provenance of the chain snapshot this board was scored from. */
  asof?: string | null
  ageSeconds?: number | null
  mode?: string | null
  chainProvider?: string | null
  oiProvider?: string | null
  contracts?: number | null
  expiryLabel?: string | null
}>()

const primary = computed(() => props.squeeze?.primary ?? 'quiet')
const bull = computed(() => props.squeeze?.bullish_setup)
const bear = computed(() => props.squeeze?.bearish_setup)
const signedScore = computed(() => props.squeeze?.score ?? null)
const levels = computed(() => props.squeeze?.key_levels)
const dampened = computed(() => Boolean(props.squeeze?.long_gamma_dampened))

/** Featured setup: highest structure score, with primary bias as tie-break. */
const featured = computed(() =>
  calculateFeaturedSetup(primary.value, bull.value, bear.value, signedScore.value),
)

/**
 * Whether the chain actually scored this side. A setup with no factor meters
 * carries no measurement, and printing 0/100 + UNLIKELY for it would state a
 * confident negative where the honest answer is "not measured".
 */
const measured = computed(() => isSetupMeasured(featured.value.setup))
const theory = computed(() => buildTheoryIdentity(props.squeeze))
/** Signed theory score drives the ring. Structure fill is a separate meter. */
const boardScore = computed(() => (measured.value ? theory.value.signed : null))
const structureScore = computed(() =>
  measured.value ? (featured.value.setup?.score ?? null) : null,
)
const factors = computed(() => featured.value.setup?.factors ?? [])
const analysis = computed(() => featured.value.setup?.setup_analysis ?? [])

/** Full ring: circumference of r=42 → 2πr ≈ 263.9 */
const RING_C = RING_CIRCUMFERENCE
const ringOffset = computed(() => calculateRingOffset(boardScore.value, RING_C))

function scoreCls(score: number | null): string {
  if (score == null) return 'low'
  if (score >= 75) return 'hot'
  if (score >= 55) return 'elev'
  if (score >= 35) return 'mid'
  return 'low'
}

/** Fill class for a factor meter, guarding against a zero or absent max. */
function factorCls(f: SqueezeFactor): string {
  const max = Number(f?.max ?? 0)
  if (!Number.isFinite(max) || max <= 0) return 'low'
  return scoreCls((Number(f.score ?? 0) / max) * 100)
}

const spotPrice = computed(
  () => props.spot ?? levels.value?.spot ?? featured.value.setup?.spot ?? null,
)

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

/**
 * The tradable price map: every measured level ordered high-to-low around
 * spot, each with its real dollar and percent distance. This is what turns the
 * score into something a desk can act on — where the trigger is, how far away,
 * and which level invalidates the read.
 */
const ladder = computed(() =>
  buildLevelLadder({
    side: featured.value.side,
    spot: spotPrice.value,
    callWall:
      levels.value?.call_wall ??
      (featured.value.side === 'bullish' ? featuredWall.value.level : null),
    putWall:
      levels.value?.put_wall ??
      (featured.value.side === 'bearish' ? featuredWall.value.level : null),
    gammaFlip: levels.value?.gamma_flip ?? null,
    pinStrike: levels.value?.pin_strike ?? null,
  }),
)

/** Distance to the featured trigger — the number a desk watches intraday. */
const triggerRow = computed(() => ladder.value.find((r) => r.role === 'trigger') ?? null)

const regimeSide = computed(() => gammaRegimeSide(spotPrice.value, levels.value?.gamma_flip))
const regimeCopy = computed(() => {
  switch (regimeSide.value) {
    case 'above_flip':
      return { text: 'ABOVE FLIP · LONG Γ', tone: 'warn' }
    case 'below_flip':
      return { text: 'BELOW FLIP · SHORT Γ', tone: 'live' }
    case 'at_flip':
      return { text: 'AT FLIP · BOUNDARY', tone: 'warn' }
    default:
      return { text: 'FLIP UNMEASURED', tone: 'unknown' }
  }
})

/** Feed provenance. Reported, never assumed: an unknown age stays unknown. */
const fresh = computed(() => {
  const tier = freshnessTier(props.ageSeconds, props.mode)
  const labels: Record<string, string> = {
    live: 'LIVE',
    delayed: 'DELAYED',
    stale: 'STALE',
    history: 'HISTORY',
    unknown: 'AGE UNKNOWN',
  }
  return { tier, label: labels[tier] ?? 'AGE UNKNOWN', age: formatAge(props.ageSeconds) }
})

const asofLabel = computed(() => {
  const raw = props.asof
  if (!raw) return DASH
  const ms = Date.parse(raw)
  if (!Number.isFinite(ms)) return String(raw)
  return new Date(ms).toISOString().replace('T', ' ').slice(0, 19) + 'Z'
})

const contractsLabel = computed(() =>
  props.contracts == null || !Number.isFinite(props.contracts)
    ? DASH
    : Number(props.contracts).toLocaleString('en-US'),
)

/**
 * The full audit line. Every clause names a real payload field; a field the
 * payload did not carry is reported as unknown rather than omitted, because a
 * silently missing source reads as "no problem" when it is the opposite.
 */
const provDetail = computed(() => {
  const parts = [
    `As of ${asofLabel.value} (age ${fresh.value.age}).`,
    `Chain feed: ${props.chainProvider || 'unknown'}.`,
    `Open interest: ${props.oiProvider || 'unknown'}.`,
    `${contractsLabel.value} contracts passed quality filters.`,
  ]
  if (props.expiryLabel) parts.push(`Expiry: ${props.expiryLabel}.`)
  if (props.mode) parts.push(`Mode: ${props.mode}.`)
  parts.push('Every figure on this board is computed from this snapshot.')
  return parts.join(' ')
})

const displayFactors = computed(() => factors.value ?? [])

function factorTheme(f: SqueezeFactor): string {
  const id = (f.id || '').toLowerCase()
  const lbl = (f.label || '').toLowerCase()
  if (id.includes('call') || lbl.includes('call') || id.includes('bull')) return 'bullish'
  if (id.includes('put') || lbl.includes('put') || id.includes('bear')) return 'bearish'
  if (id.includes('fuel') || id.includes('gamma') || id.includes('regime')) return 'warn'
  return 'accent'
}

const driverLabels = computed(() =>
  (props.squeeze?.drivers ?? []).map((d) => d.replace(/_/g, ' ').toUpperCase()),
)

/** Signed percent from a fraction. Placeholder when the distance is unmeasured. */
function distPct(pct: number | null | undefined): string {
  if (pct == null || !Number.isFinite(pct)) return DASH
  return `${pct > 0 ? '+' : ''}${(pct * 100).toFixed(2)}%`
}

/** Signed dollar distance. Placeholder when unmeasured. */
function distUsd(delta: number | null | undefined): string {
  if (delta == null || !Number.isFinite(delta)) return DASH
  return `${delta > 0 ? '+' : delta < 0 ? '-' : ''}$${Math.abs(delta).toFixed(2)}`
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
  <div v-if="squeeze && featured.setup" class="sq" :class="featured.side">
    <section class="hero">
      <div class="ring-wrap">
        <svg
          role="img"
          aria-label="Gamma squeeze theory-score ring."
          class="ring-svg"
          viewBox="0 0 108 108"
        >
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
          <strong class="score-num fig" :class="scoreCls(boardScore)">{{
            boardScore == null ? DASH : formatSignedScore(boardScore)
          }}</strong>
          <span class="score-denom label">{{ boardScore == null ? 'UNSCORED' : '/100' }}</span>
        </div>
      </div>

      <div class="hero-copy">
        <div class="setup-header-row">
          <div class="setup-title-group">
            <i class="side-dot" :class="featured.side === 'bullish' ? 'call' : 'put'" />
            <strong class="setup-name">GAMMA SQUEEZE</strong>
          </div>
          <span class="likelihood-badge label" :class="theory.state">{{ theory.stateLabel }}</span>
        </div>
        <span class="score-label label">
          THEORY SCORE · NOT A FORECAST
          <HelpTip
            label="Squeeze formula"
            align="right"
            :text="theory.formula"
          />
        </span>
        <div class="leg-row">
          <span class="leg bull"
            >BULL <b class="fig">{{ theory.bullUi == null ? DASH : theory.bullUi.toFixed(1) }}</b></span
          >
          <span class="leg bear"
            >BEAR <b class="fig">{{ theory.bearUi == null ? DASH : theory.bearUi.toFixed(1) }}</b></span
          >
          <span class="leg fuel"
            >FUEL
            <b class="fig">{{
              theory.fuelUi == null ? DASH : `${Math.round(theory.fuelUi * 100)}%`
            }}</b></span
          >
        </div>
        <div class="signed-block">
          <span class="signed-cell">
            <span class="signed-key">SIGNED</span>
            <strong class="fig" :class="featured.side === 'bullish' ? 'call' : 'put'">{{
              formatSignedScore(signedScore)
            }}</strong>
          </span>
          <span v-if="levels?.near_spot_net_gex_m != null" class="signed-cell">
            <span class="signed-key">NEAR-SPOT GEX</span>
            <span class="fig">{{ formatNearSpotGex(levels.near_spot_net_gex_m) }}</span>
          </span>
          <span class="signed-cell" :class="regimeCopy.tone">
            <span class="signed-key">REGIME</span>
            <span class="fig">{{ regimeCopy.text }}</span>
          </span>
        </div>
      </div>
    </section>

    <!-- Scroll region: the panel lives in a fixed-height workbench cell, so
         the detail below the dial scrolls rather than being silently clipped. -->
    <div class="sq-scroll">
      <!-- Key levels: measured price ladder, high to low around spot -->
      <section class="block levels-block">
        <div class="block-hdr label">
          KEY LEVELS
          <HelpTip
            label="Key levels"
            align="right"
            text="Dealer gamma levels from this chain snapshot, ordered by price. Distances are measured against the same spot the score was computed from. A level the chain could not produce shows a dash; it is never defaulted to zero."
          />
        </div>

        <div v-if="triggerRow" class="trigger-strip" :class="featured.side">
          <span class="label trig-key">
            DISTANCE TO {{ triggerRow.label }}
            <span class="pocket-tag"
              >POCKET {{ optUsd(spotPrice) }}–{{ optUsd(triggerRow.level) }}</span
            >
          </span>
          <span class="trig-figs">
            <strong class="fig trig-pct" :class="featured.side === 'bullish' ? 'call' : 'put'">{{
              distPct(triggerRow.distance?.pct)
            }}</strong>
            <span class="fig trig-abs">{{ distUsd(triggerRow.distance?.delta) }}</span>
            <span class="fig trig-lvl">{{ optUsd(triggerRow.level) }}</span>
          </span>
        </div>

        <div class="ladder" role="table" aria-label="Key gamma levels">
          <div class="ladder-head label" role="row">
            <span class="ld-label" role="columnheader">LEVEL</span>
            <span class="ld-price" role="columnheader">PRICE</span>
            <span class="ld-dist" role="columnheader">Δ% · Δ$</span>
            <span class="ld-role" role="columnheader">ROLE</span>
          </div>
          <div
            v-for="row in ladder"
            :key="row.id"
            class="ladder-row"
            :class="[row.role, `tone-${row.tone}`, { unmeasured: row.level == null }]"
            role="row"
            :title="row.note"
          >
            <span class="ld-label label" role="cell">
              <i class="ld-tick" :class="`tone-${row.tone}`" aria-hidden="true" />{{ row.label }}
            </span>
            <span class="ld-price fig" role="cell">{{ optUsd(row.level) }}</span>
            <span class="ld-dist fig" role="cell">
              <b class="ld-pct">{{
                row.role === 'spot' && row.level != null ? DASH : distPct(row.distance?.pct)
              }}</b>
              <em class="ld-abs">{{
                row.role === 'spot' && row.level != null ? DASH : distUsd(row.distance?.delta)
              }}</em>
            </span>
            <span class="ld-role label" role="cell">{{ row.role.toUpperCase() }}</span>
          </div>
        </div>
        <p v-if="ladder.every((r) => r.level == null)" class="quiet label">
          No gamma levels on this chain snapshot.
        </p>
      </section>

      <!-- Factors: theory identity first, wall structure second -->
      <section class="block factors-block">
        <div class="block-hdr label">
          KEY FACTORS
          <HelpTip
            label="Squeeze identity"
            align="right"
            text="SR = |GEX⁻_1%| / ADV × e^{−0.05 T} × ATM share. Score = tanh(40·SR) × (0.5·signed flow + 0.5·5d momentum). Fuel is unsigned; direction is additive. This is a gamma-structure diagnostic — walk-forward 1d hit rate has not beaten a momentum baseline, so the number is not a probability a squeeze fires. Dealer inventory is assumed customer-long / dealer-short premium (q = −OI)."
          />
        </div>
        <p class="quiet identity-caveat">
          Dealer-gamma fuel × signed flow and 5-session momentum. Diagnostic only — not a
          calibrated directional forecast. Short interest is not on this chain.
        </p>
        <div class="factors-list theory-terms">
          <div v-for="term in theory.terms" :key="term.id" class="factor-row">
            <span class="factor-title label">{{ term.label }}</span>
            <div class="factor-track" :title="term.detail">
              <i
                class="factor-fill"
                :class="term.tone"
                :style="{ width: `${Math.round(term.fill01 * 100)}%` }"
              />
            </div>
            <span class="factor-score fig">{{ term.display }}</span>
          </div>
        </div>
        <div v-if="driverLabels.length" class="driver-row">
          <span v-for="d in driverLabels" :key="d" class="driver-chip label">{{ d }}</span>
        </div>
        <div class="block-hdr label structure-hdr">
          WALL STRUCTURE
          <span v-if="structureScore != null" class="fig structure-score"
            >{{ structureScore }}/100</span
          >
        </div>
        <div v-if="displayFactors.length" class="factors-list">
          <div v-for="f in displayFactors" :key="f.id || f.label" class="factor-row">
            <span class="factor-title label">{{ f.label }}</span>
            <div class="factor-track" :title="f.detail || ''">
              <i
                class="factor-fill"
                :class="[factorTheme(f), factorCls(f)]"
                :style="{ width: `${calculateTrackWidthPct(f.score, f.max)}%` }"
              />
            </div>
            <span class="factor-score fig">{{ f.score }}/{{ f.max }}</span>
          </div>
        </div>
        <p v-else class="quiet label">No wall-structure meters on this chain yet.</p>
      </section>

      <!-- Takeaways -->
      <section class="block takeaways-block">
        <div class="block-hdr label">KEY TAKEAWAYS</div>
        <ul class="takeaways-list">
          <li
            v-for="(item, i) in displayTakeaways"
            :key="i"
            class="takeaway-item"
            :class="item.type"
          >
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
        <span class="fig">{{
          otherSide.setup.score == null ? DASH : `${otherSide.setup.score}/100`
        }}</span>
        <span class="lik label">STRUCTURE</span>
        <div class="otrack">
          <i
            :class="otherSide.side"
            :style="{ width: `${calculateTrackWidthPct(otherSide.setup.score, 100)}%` }"
          />
        </div>
      </div>
    </div>

    <!-- Provenance: the snapshot behind every figure above -->
    <footer class="prov label">
      <span class="prov-lamp" :class="fresh.tier" aria-hidden="true" />
      <span class="prov-state" :class="fresh.tier">{{ fresh.label }}</span>
      <span class="prov-sep" aria-hidden="true">·</span>
      <span class="prov-item">AGE {{ fresh.age }}</span>
      <span class="prov-sep" aria-hidden="true">·</span>
      <span class="prov-item">{{ contractsLabel }} CONTRACTS</span>
      <HelpTip label="Data provenance" align="right" :text="provDetail" />
    </footer>
    <!-- Key levels reference fallback -->
    <span style="display: none" aria-hidden="true">
      {{ featuredWall.level != null ? optUsd(featuredWall.level) : DASH }}
      {{ levels?.gamma_flip != null ? optUsd(levels.gamma_flip) : DASH }}
    </span>
  </div>

  <div v-else-if="squeeze" class="sq empty label">
    <strong>Structure unmeasured</strong>
    <span>Chain data present, but neither bullish nor bearish structure could be scored.</span>
  </div>

  <div v-else class="sq empty label">
    <strong>Squeeze unavailable</strong>
    <span>Need a chain with OI + gamma (or IV for BS gamma) to score structure.</span>
  </div>
</template>

<style scoped>
/* Surface glass token: var(--glass-surface-hi) */
/* =========================================================================
   Squeeze Screener — instrument-grade probability board.
   The panel carries real depth: a tinted substrate keyed to the featured side,
   a substantial score dial with a background disc and tick marks, weighted
   factor readouts, and key-level cells that feel machined rather than printed.
   ========================================================================= */

.sq {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  min-width: 0;
  min-height: 0;
  height: 100%;
  padding: 0 0 0 10px;
  background: transparent;
  position: relative;
  overflow: hidden;
}
/* Left accent edge — solid rail, not a wash. */
.sq.bullish::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--call);
}
.sq.bearish::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--put);
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

/* ---- scroll region ------------------------------------------------------ */
/* The dial and the provenance line are the two things that must always be on
   screen: one says what the read is, the other says whether it can be trusted.
   Everything between them scrolls. */
.sq-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  padding-right: 2px;
  scrollbar-width: thin;
  scrollbar-color: var(--rule-hi) transparent;
}
.sq-scroll::-webkit-scrollbar {
  width: 6px;
}
.sq-scroll::-webkit-scrollbar-track {
  background: transparent;
}
.sq-scroll::-webkit-scrollbar-thumb {
  background: var(--rule-hi);
  border-radius: 3px;
}

/* ---- hero --------------------------------------------------------------- */
.hero {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: var(--s3);
  align-items: start;
  padding: 0 0 var(--s3);
  background: transparent;
  border-bottom: var(--hair) solid var(--rule);
  flex: 0 0 auto;
}
@media (max-width: 420px) {
  .hero {
    grid-template-columns: 1fr;
    justify-items: start;
  }
}

.hero-copy {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.setup-header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}
.setup-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.setup-name {
  font: 800 var(--t-tiny) var(--font-display);
  letter-spacing: 0.1em;
  color: var(--ink);
}
.score-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
  text-transform: uppercase;
}
.leg-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
  color: var(--ink-faint);
}
.leg b {
  margin-left: 4px;
  font-family: var(--font-data);
  font-weight: 700;
  color: var(--ink);
}
.leg.bull b {
  color: var(--call-hi);
}
.leg.bear b {
  color: var(--put-hi);
}
.leg.fuel b {
  color: var(--phosphor);
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
  width: 88px;
  height: 88px;
  flex: 0 0 auto;
}
/* Background disc gives the dial visual mass even at score 0. */
.ring-wrap::before {
  content: '';
  position: absolute;
  inset: 8px;
  border-radius: 50%;
  background: var(--glass-base);
  border: var(--hair) solid var(--glass-border);
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
  stroke: var(--glass-border-hi);
  stroke-width: 6;
}
.ring-fill {
  fill: none;
  stroke-width: 6;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.6s cubic-bezier(0.22, 1, 0.36, 1);
}
.ring-fill.bullish {
  stroke: var(--call-hi);
}
.ring-fill.bearish {
  stroke: var(--put-hi);
}
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
.score-lockup {
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.score-num {
  font-size: 1.28rem;
  font-weight: 800;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
  letter-spacing: -0.04em;
  line-height: 1;
}
.score-num.hot {
  color: var(--ink);
}
.sq.bullish .score-num.hot {
  color: var(--call-hi);
}
.sq.bearish .score-num.hot {
  color: var(--put-hi);
}
.score-num.elev {
  color: var(--ink);
}
.score-num.mid {
  color: var(--ink-dim);
}
.score-num.low {
  color: var(--ink-faint);
}
.score-denom {
  font-size: var(--t-micro);
  color: var(--ink-faint);
  font-weight: 600;
  font-family: var(--font-data);
}

.bias-lock {
  display: flex;
  align-items: center;
  gap: var(--s2);
  min-width: 0;
  padding: 6px var(--s3);
  border-radius: var(--r-sm);
  background: var(--glass-surface-hi);
  border: var(--hair) solid var(--glass-border);
  box-shadow: var(--glass-specular-subtle);
}
.side-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: 0 0 auto;
}
.side-dot.call {
  background: var(--call-hi);
  outline: var(--hair) solid color-mix(in srgb, var(--call) 35%, transparent);
  outline-offset: 2px;
}
.side-dot.put {
  background: var(--put-hi);
  outline: var(--hair) solid color-mix(in srgb, var(--put) 35%, transparent);
  outline-offset: 2px;
}
.bias-copy {
  display: flex;
  flex-direction: column;
  gap: 0;
  min-width: 0;
}
.bias-sub {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
}
.bias-heading {
  font: 800 var(--t-tiny) var(--font-display);
  letter-spacing: 0.08em;
  color: var(--ink);
}
.bias-lock.bullish .bias-heading {
  color: var(--call-hi);
}
.bias-lock.bearish .bias-heading {
  color: var(--put-hi);
}

.prob-zones {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
}
.prob-zones .zone {
  text-align: center;
  padding: 4px 6px;
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-xs, 2px);
  font-size: var(--t-nano);
  font-weight: 700;
  color: var(--ink-faint);
  background: var(--glass-base);
  letter-spacing: 0.06em;
}
.prob-zones .zone.active {
  color: var(--ink);
  background: var(--glass-surface-hi);
  border-color: var(--phosphor-dim);
}

.squeeze-metric-bar {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.metric-bar-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: var(--t-micro);
  color: var(--ink-faint);
  font-weight: 700;
  letter-spacing: 0.06em;
}
.trig-pct {
  font-size: var(--t-small);
  font-family: var(--font-data);
  font-weight: 800;
}
.trig-pct.call {
  color: var(--call-hi);
}
.trig-pct.put {
  color: var(--put-hi);
}

.trigger-track-container {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.track-bar {
  position: relative;
  height: 18px;
  background: var(--glass-base);
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-xs, 2px);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 0 4px;
}
.track-pocket-chip {
  font-size: var(--t-nano);
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 2px;
  background: var(--call-wash);
  color: var(--call-hi);
  border: var(--hair) solid var(--call);
}
.track-labels {
  display: flex;
  justify-content: space-between;
  font-size: var(--t-nano);
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-weight: 600;
}

.visually-hidden {
  position: absolute !important;
  width: 1px !important;
  height: 1px !important;
  padding: 0 !important;
  margin: -1px !important;
  overflow: hidden !important;
  clip: rect(0, 0, 0, 0) !important;
  white-space: nowrap !important;
  border: 0 !important;
}

.likelihood-badge {
  flex: 0 1 auto;
  max-width: 46%;
  padding: 3px 7px;
  border: var(--hair) solid var(--rule);
  font: 800 var(--t-nano) var(--font-display);
  letter-spacing: 0.06em;
  color: var(--ink-dim);
  background: var(--void-lift);
  white-space: normal;
  text-align: right;
  line-height: 1.25;
}
.likelihood-badge.bull_lean {
  color: var(--call-hi);
  border-color: color-mix(in srgb, var(--call) 55%, var(--rule));
  background: var(--call-wash);
}
.likelihood-badge.bear_lean {
  color: var(--put-hi);
  border-color: color-mix(in srgb, var(--put) 55%, var(--rule));
  background: var(--put-wash);
}
.likelihood-badge.two_way,
.likelihood-badge.fuel_only {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 55%, var(--rule));
  background: var(--warn-wash);
}
.likelihood-badge.dampened,
.likelihood-badge.no_fuel,
.likelihood-badge.unmeasured,
.likelihood-badge.unscored {
  color: var(--ink-faint);
  border-style: dashed;
  border-color: var(--rule-hi);
  background: transparent;
}
.regime-tag {
  padding: 4px 10px;
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-xs);
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.1em;
  color: var(--ink-dim);
  background: var(--glass-base);
  box-shadow: var(--glass-specular-subtle);
}
.regime-tag.live {
  color: var(--call-hi);
  border-color: color-mix(in srgb, var(--call) 45%, var(--rule));
  background: var(--call-wash);
}
.regime-tag.warn {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 45%, var(--rule));
  background: var(--warn-wash);
}
.regime-tag.unknown {
  color: var(--ink-faint);
  border-style: dashed;
}

.tag {
  padding: 4px 10px;
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-xs);
  letter-spacing: 0.1em;
  font: 700 var(--t-micro) var(--font-display);
  box-shadow: var(--glass-specular-subtle);
}
.tag.damp {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-wash);
}
.tag.fuel {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}

.prob-track {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}
.prob-zones-header {
  display: flex;
  justify-content: space-between;
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--ink-faint);
}
.prob-zones-header .zone-label {
  color: var(--ink-faint);
  transition: color var(--dur-fast) var(--ease-out);
}
.prob-zones-header .zone-label.active {
  color: var(--ink);
  font-weight: 800;
}
.prob-track-bar {
  position: relative;
  height: 6px;
  background: var(--glass-base);
  border: var(--hair) solid var(--glass-border);
  border-radius: 3px;
  overflow: visible;
}
.prob-track-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--phosphor);
  transition: width 0.4s var(--ease-out);
}
.prob-track-fill.bullish {
  background: var(--call-hi);
}
.prob-track-fill.bearish {
  background: var(--put-hi);
}

/* Marker thumb that slides across the track to the score position */
.prob-thumb {
  position: absolute;
  top: 50%;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--ink);
  border: 2px solid var(--panel);
  transform: translate(-50%, -50%);
  pointer-events: none;
  transition: left var(--dur) var(--ease-out);
}
.prob-thumb.bullish {
  background: var(--call-hi);
}
.prob-thumb.bearish {
  background: var(--put-hi);
}

/* Signed block: one audit row under the identity. */
.signed-block {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
  gap: 8px;
  padding: 6px 0 0;
  border-top: var(--hair) solid var(--rule);
}
.signed-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.signed-cell .signed-key {
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
.signed-cell .fig {
  font-size: var(--t-micro);
  font-weight: 700;
  color: var(--ink);
  white-space: normal;
  line-height: 1.25;
}
.signed-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
  color: var(--ink-faint);
  letter-spacing: 0.08em;
}
.signed-line .signed-key {
  font-size: var(--t-micro);
  font-weight: 600;
}
.signed-line .fig {
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-small);
}
.signed-line .fig.call {
  color: var(--call-hi);
}
.signed-line .fig.put {
  color: var(--put-hi);
}
.signed-block .near {
  color: var(--ink-faint);
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
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-faint);
  font: 700 var(--t-micro) var(--font-display);
  letter-spacing: 0.12em;
  padding-bottom: 4px;
  border-bottom: var(--hair) solid var(--glass-border);
}

/* ---- key levels: measured price ladder ---------------------------------- */
/* Rows are ordered by real price, so the board reads like a DOM: what is above
   spot, what is below, and how far. An unmeasured level keeps its row and
   shows an em-dash rather than being dropped or zero-filled. */
.trigger-strip {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 8px 0 8px 8px;
  background: transparent;
  border-left: 2px solid var(--rule-hi);
  min-width: 0;
}
.pocket-tag {
  display: inline-block;
  margin-left: 6px;
  padding: 0;
  background: transparent;
  border: 0;
  color: var(--ink-soft);
  font: 700 var(--t-micro) var(--font-data);
}
.trigger-strip.bullish {
  border-left-color: var(--call);
}
.trigger-strip.bearish {
  border-left-color: var(--put);
}
.trig-key {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
  font-weight: 600;
  white-space: normal;
  overflow: visible;
  line-height: 1.35;
}
.trig-figs {
  display: flex;
  align-items: baseline;
  gap: var(--s2);
  flex-wrap: wrap;
  min-width: 0;
}
.trigger-strip .fig {
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.trig-pct {
  font-size: var(--t-body);
  font-weight: 700;
  color: var(--ink);
}
.trig-pct.call {
  color: var(--call-hi);
}
.trig-pct.put {
  color: var(--put-hi);
}
.trig-abs {
  font-size: var(--t-small);
  color: var(--ink-soft);
}
.trig-lvl {
  font-size: var(--t-small);
  color: var(--ink-dim);
  margin-left: auto;
}

/* The ladder is a container query, not a media query: this panel sits in a
   workbench cell whose width has nothing to do with the viewport. Narrow cells
   get a two-line row (level/price, then role/distance) so no figure is ever
   truncated; a wide cell collapses each row onto a single line. */
.ladder {
  container-type: inline-size;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: var(--hair) solid var(--rule);
}
.ladder-head {
  display: none;
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: 0.1em;
  font-weight: 600;
  background: var(--glass-surface-hi);
  border-bottom: var(--hair) solid var(--glass-border);
}
.ladder-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    'label price'
    'role  dist';
  column-gap: var(--s2);
  row-gap: 2px;
  align-items: baseline;
  padding: 6px var(--s3);
  min-width: 0;
  background: var(--glass-base);
  border-top: var(--hair) solid var(--glass-border-subtle);
  transition: background var(--dur-fast) var(--ease-out);
}
.ladder-row:first-of-type {
  border-top: 0;
}
.ladder-row:hover {
  background: var(--glass-surface-hi);
}
/* Spot is the reference row — emphasis, not colour. */
.ladder-row.spot {
  background: var(--glass-surface-hi);
  box-shadow: var(--glass-specular-subtle);
}
.ladder-row.spot .ld-price {
  color: var(--ink);
  font-weight: 700;
}
.ladder-row.unmeasured {
  opacity: 0.55;
}

.ld-label {
  grid-area: label;
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-soft);
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
  font-weight: 600;
  min-width: 0;
}
.ld-tick {
  width: 3px;
  height: 11px;
  border-radius: 1px;
  flex: 0 0 auto;
  background: var(--rule-hi);
}
.ld-tick.tone-call {
  background: var(--call);
}
.ld-tick.tone-put {
  background: var(--put);
}
.ld-tick.tone-accent {
  background: var(--phosphor-dim);
}
.ld-tick.tone-ink {
  background: var(--ink-dim);
}

.ld-price {
  grid-area: price;
  text-align: right;
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
  font-size: var(--t-small);
  font-weight: 600;
  color: var(--ink-soft);
  white-space: nowrap;
}
.ladder-row.tone-call .ld-price {
  color: var(--call-hi);
}
.ladder-row.tone-put .ld-price {
  color: var(--put-hi);
}
.ladder-row.tone-accent .ld-price {
  color: var(--phosphor);
}

.ld-dist {
  grid-area: dist;
  display: flex;
  align-items: baseline;
  justify-content: flex-end;
  gap: 6px;
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
  font-size: var(--t-micro);
  white-space: nowrap;
}
.ld-dist .ld-pct {
  color: var(--ink-soft);
  font-weight: 600;
  font-style: normal;
}
.ld-dist .ld-abs {
  color: var(--ink-faint);
  font-style: normal;
}

.ld-role {
  grid-area: role;
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
  font-weight: 600;
  white-space: nowrap;
}
.ladder-row.trigger .ld-role {
  color: var(--ink);
}
.ladder-row.invalidation .ld-role {
  color: var(--warn);
}

@container (min-width: 400px) {
  .ladder-head,
  .ladder-row {
    display: grid;
    grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr) minmax(0, 1.2fr) minmax(0, 0.9fr);
    grid-template-areas: 'label price dist role';
    align-items: center;
    row-gap: 0;
  }
  .ladder-head .ld-price,
  .ladder-head .ld-dist,
  .ladder-head .ld-role {
    text-align: right;
    justify-content: flex-end;
  }
  .ld-role {
    text-align: right;
  }
}

/* ---- provenance strip --------------------------------------------------- */
/* The audit line: which feed, which snapshot, how stale. Without it none of
   the figures above can be checked against the source chain. */
.prov {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  flex: 0 0 auto;
  padding-top: var(--s2);
  border-top: var(--hair) solid var(--rule-faint);
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
  font-family: var(--font-data);
}
.prov-lamp {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: 0 0 auto;
  background: var(--ink-faint);
}
.prov-lamp.live {
  background: var(--call-hi);
}
.prov-lamp.delayed {
  background: var(--warn);
}
.prov-lamp.stale {
  background: var(--put-hi);
}
.prov-lamp.history {
  background: var(--phosphor-dim);
}
.prov-state {
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--ink-dim);
}
.prov-state.live {
  color: var(--call-hi);
}
.prov-state.delayed {
  color: var(--warn);
}
.prov-state.stale {
  color: var(--put-hi);
}
.prov-state.history {
  color: var(--phosphor);
}
.prob-zones.unscored {
  opacity: 0.4;
}
/* The separator is decoration and already aria-hidden, so it may sit at rule
   contrast. The provenance items are not decoration — age and contract count
   are how an operator knows whether to trust the row — so they take the
   provenance token rather than the quietest ink available. */
.prov-sep {
  color: var(--ink-ghost);
}
.prov-item {
  color: var(--meta-provenance);
  white-space: nowrap;
}
.prov :deep(.help) {
  margin-left: auto;
}

/* ---- factors: weighted readouts with groove tracks --------------------- */
.factors-list {
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.factor-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    'title score'
    'track track';
  gap: 3px 8px;
  align-items: baseline;
  min-width: 0;
}
.factor-title {
  grid-area: title;
  color: var(--ink-soft);
  font: 600 var(--t-micro) var(--font-display);
  white-space: normal;
  overflow: visible;
  letter-spacing: 0.02em;
  line-height: 1.3;
}
.factor-track {
  grid-area: track;
  height: 6px;
  background: var(--void);
  border: var(--hair) solid var(--rule);
  overflow: hidden;
}
.factor-fill {
  display: block;
  height: 100%;
  background: var(--ink-dim);
}
.factor-fill.bullish,
.factor-fill.bull {
  background: var(--call);
}
.factor-fill.bearish,
.factor-fill.bear {
  background: var(--put);
}
.factor-fill.warn {
  background: var(--warn);
}
.factor-fill.accent,
.factor-fill.fuel,
.factor-fill.ink {
  background: var(--phosphor);
}
.factor-fill.flow {
  background: var(--ink);
}
.factor-fill.mom {
  background: var(--phosphor-dim);
}
.identity-caveat {
  line-height: 1.4;
  white-space: normal;
  text-transform: none;
  letter-spacing: 0.01em;
}
.structure-hdr {
  margin-top: var(--s3);
}
.structure-score {
  margin-left: auto;
  color: var(--ink-dim);
  font-family: var(--font-data);
  letter-spacing: 0;
}
.driver-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.driver-chip {
  padding: 2px 6px;
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-xs);
  color: var(--ink-dim);
  background: var(--glass-base);
  letter-spacing: 0.06em;
  font-size: var(--t-nano);
}
.factor-fill.hot {
  opacity: 1;
}
.factor-fill.elev {
  opacity: 0.92;
}
.factor-fill.mid {
  opacity: 0.78;
}
.factor-fill.low {
  opacity: 0.5;
}
.factor-score {
  grid-area: score;
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
.takeaway-dot.pos {
  background: var(--call-hi);
}
.takeaway-dot.neg {
  background: var(--put);
}
.takeaway-dot.warn {
  background: var(--warn);
}
.takeaway-dot.info {
  background: var(--phosphor);
}
.takeaway-text {
  min-width: 0;
}

.impl-line {
  margin: 0;
  padding: var(--s2) var(--s3);
  border-radius: var(--r-sm);
  background: var(--glass-surface-hi);
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.45;
  border-left: 1px solid var(--phosphor-dim);
  border: var(--hair) solid var(--glass-border);
  box-shadow: var(--glass-specular-subtle);
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
.stronger li {
  margin-bottom: 3px;
}
.stronger li:last-child {
  margin-bottom: 0;
}

/* ---- Float & Cover Gauge Block ------------------------------------------ */
.float-cover-block {
  padding: var(--s2) 0;
}
.float-stat-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--s3);
}
.float-stat-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: var(--glass-surface-hi);
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-sm);
  box-shadow: var(--glass-specular-subtle);
}
.float-stat-cell .stat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--ink-faint);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.06em;
}
.float-stat-cell .stat-head .fig {
  color: var(--ink);
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-small);
}
.float-track {
  height: 4px;
  background: var(--glass-base);
  border-radius: 9999px;
  overflow: hidden;
}
.float-fill {
  display: block;
  height: 100%;
  border-radius: 9999px;
}
.float-fill.warn {
  background: var(--warn);
}
.float-fill.bullish {
  background: var(--call);
}
.float-fill.bearish {
  background: var(--put);
}
.float-stat-cell .stat-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--ink-faint);
  font-size: var(--t-nano);
  font-weight: 600;
}
.float-stat-cell .stat-footer .benchmark {
  color: var(--ink-faint);
}

/* ---- Setup Thesis Card -------------------------------------------------- */
.setup-thesis-card {
  padding: var(--s3);
  background: var(--glass-surface-hi);
  border: var(--hair) solid var(--glass-border);
  border-left: 1px solid var(--phosphor-dim);
  border-radius: var(--r-sm);
  margin: var(--s2) 0;
  box-shadow: var(--glass-specular-subtle);
}
.setup-thesis-card .thesis-text {
  margin: 0;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.5;
}
.setup-thesis-card .thesis-text strong {
  color: var(--ink);
}

/* ---- other side: compact alt readout ------------------------------------ */
.other-side {
  display: grid;
  grid-template-columns: auto auto 1fr auto;
  gap: 4px var(--s2);
  align-items: center;
  padding: var(--s2) var(--s3);
  border: var(--hair) solid var(--glass-border);
  border-radius: var(--r-sm);
  background: var(--glass-surface-hi);
  color: var(--ink-faint);
  letter-spacing: 0.08em;
  flex: 0 0 auto;
  margin-top: auto;
  box-shadow: var(--glass-specular-subtle);
}
.other-side .fig {
  color: var(--ink);
  font-size: var(--t-tiny);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-data);
  font-weight: 700;
  justify-self: end;
}
.other-side .lik {
  color: var(--ink-faint);
  font-weight: 600;
}
.other-side .otrack {
  grid-column: 1 / -1;
  height: 4px;
  background: var(--glass-base);
  border: var(--hair) solid var(--glass-border-subtle);
  border-radius: 9999px;
  overflow: hidden;
}
.other-side .otrack i {
  display: block;
  height: 100%;
  border-radius: 9999px;
  opacity: 0.8;
}
.other-side .otrack i.bullish {
  background: var(--call);
}
.other-side .otrack i.bearish {
  background: var(--put);
}

@media (max-width: 520px) {
  .hero {
    grid-template-columns: 1fr;
    justify-items: center;
    text-align: center;
  }
  .bias-lock {
    justify-content: center;
  }
  .hero-meta {
    width: 100%;
  }
  .signed-block .near {
    margin-left: 0;
  }
}
</style>
