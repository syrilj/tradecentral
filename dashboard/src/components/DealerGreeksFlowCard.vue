<script setup lang="ts">
import { computed } from 'vue'
import type { MicrostructureRegimeSnapshot } from '@/microstructureContracts'
import { num, optSigned, DASH } from '@/format'

const props = withDefaults(
  defineProps<{
    snapshot: MicrostructureRegimeSnapshot | null
    /**
     * Canonical levels from the page's single regime read (`regimeRead`).
     * The snapshot carries its own flip/walls/peak, solved by a different
     * endpoint on a slower clock; rendering those next to the ladder and the
     * gamma map printed two different gamma flips for one surface. The
     * canonical values win when supplied, the snapshot is the fallback, and
     * any material disagreement is named in `divergences` rather than hidden.
     */
    spot?: number | null
    gammaFlip?: number | null
    callWall?: number | null
    putWall?: number | null
    pinStrike?: number | null
    /** Net dealer gamma interpolated at live spot off the map's curve. */
    netGammaAtSpotM?: number | null
  }>(),
  {
    spot: null,
    gammaFlip: null,
    callWall: null,
    putWall: null,
    pinStrike: null,
    netGammaAtSpotM: null,
  },
)

/**
 * An unmeasurable snapshot carries zeros in every Greek, because there was
 * nothing to measure. Rendered through this card those zeros become
 * "NET GEX +0.00M · Net Market Inflow (Dealers absorb supply)" — a confident
 * balanced read of a chain that does not exist. So the card keys off
 * `quality.measurable`, not merely off the snapshot being non-null.
 */
const snap = computed(() => {
  const s = props.snapshot
  return s && s.quality?.measurable !== false ? s : null
})

const isNetGexPositive = computed(() => (snap.value?.net_gex_m ?? 0) >= 0)
const isNetVexPositive = computed(() => (snap.value?.net_vex_m ?? 0) >= 0)
const isNetChexPositive = computed(() => (snap.value?.net_chex_m ?? 0) >= 0)
/** Net DEX is null, not 0, when the chain could not be measured -- so the
 *  presence test comes first and the sign test is only meaningful under it. */
const hasNetDex = computed(() => snap.value?.net_dex_m != null)
const isNetDexPositive = computed(() => (snap.value?.net_dex_m ?? 0) >= 0)

/** Null-aware: a withheld hedging flow gets neither tone nor a direction
 *  sentence. `?? 0` would have painted "positive" onto an absent number. */
const hedgingFlowSign = computed<1 | -1 | null>(() => {
  const v = snap.value?.hedging_flow_m
  if (v == null || !Number.isFinite(v)) return null
  return v >= 0 ? 1 : -1
})

/**
 * One level per concept. `props.*` is the page's canonical read; the snapshot
 * only fills a gap it alone measured. Distances are quoted against the same
 * spot the rest of the page uses, so "+0.3%" here and "+0.13%" on the map can
 * no longer describe the same level.
 */
const lv = computed(() => {
  const s = snap.value
  return {
    spot: props.spot ?? s?.spot ?? null,
    gammaFlip: props.gammaFlip ?? s?.gamma_flip ?? null,
    callWall: props.callWall ?? s?.call_wall ?? null,
    putWall: props.putWall ?? s?.put_wall ?? null,
    pin: props.pinStrike ?? s?.absolute_gamma_peak ?? null,
  }
})

/** Named `refSpot`, not `spot`: a computed sharing a prop's name shadows it
 *  in the template and is a duplicate key to the compiler. */
const refSpot = computed(() => lv.value.spot)

/**
 * Two solves for one level disagree, for this card's purposes, exactly when
 * they would have *printed* as different prices. That is the complaint being
 * answered: the page showed 770.33 in one panel and 770.47 in another, and a
 * basis-point threshold would have called that gap immaterial and stayed
 * silent about the one discrepancy the operator could actually see. Sub-cent
 * float noise rounds to the same string and is silently ignored.
 */
function diverges(canonical: number | null, snapshotValue: number | null | undefined): boolean {
  if (canonical == null || snapshotValue == null) return false
  if (!Number.isFinite(canonical) || !Number.isFinite(snapshotValue)) return false
  return level(canonical) !== level(snapshotValue)
}

/** Levels where the chain snapshot disagrees with the canonical read, named
 *  so the gap is visible instead of resolving silently in one card's favour. */
const divergences = computed<string[]>(() => {
  const s = snap.value
  if (!s) return []
  const out: string[] = []
  if (diverges(props.gammaFlip, s.gamma_flip)) out.push(`flip ${level(s.gamma_flip)}`)
  if (diverges(props.callWall, s.call_wall)) out.push(`call wall ${level(s.call_wall)}`)
  if (diverges(props.putWall, s.put_wall)) out.push(`put wall ${level(s.put_wall)}`)
  if (diverges(props.pinStrike, s.absolute_gamma_peak))
    out.push(`gamma peak ${level(s.absolute_gamma_peak)}`)
  return out
})

/**
 * The chain-wide strike sum and the curve read at spot are different
 * measurements, not two attempts at one number, so both are labelled for what
 * they are. `net_gex_profile_m` exists in the contract precisely because these
 * can diverge; when they do, say so.
 */
const netGexAtSpot = computed<number | null>(() => {
  const v = props.netGammaAtSpotM ?? snap.value?.net_gex_profile_m ?? null
  return v != null && Number.isFinite(v) ? v : null
})

const netGexGapPct = computed<number | null>(() => {
  const total = snap.value?.net_gex_m
  const atSpot = netGexAtSpot.value
  if (total == null || atSpot == null || !Number.isFinite(total) || total === 0) return null
  return ((atSpot - total) / Math.abs(total)) * 100
})

function distToLevel(lvl: number | null): string {
  if (!refSpot.value || !lvl || lvl <= 0) return DASH
  const diff = ((lvl - refSpot.value) / refSpot.value) * 100
  return optSigned(diff, 1) + '%'
}

/** Level with its currency symbol, or a bare dash — never "$—". */
function level(v: number | null | undefined): string {
  return v != null && Number.isFinite(v) ? `$${num(v, 2)}` : DASH
}

// Visual meter calculations
const callGexRatio = computed(() => {
  if (!snap.value) return 50
  const call = snap.value.call_gex_m != null ? Math.max(0, snap.value.call_gex_m) : 0
  const put = snap.value.put_gex_m != null ? Math.max(0, Math.abs(snap.value.put_gex_m)) : 0
  const total = call + put
  if (total <= 0) return 50
  return Math.round((call / total) * 100)
})
</script>

<template>
  <div class="greeks-flow-card">
    <div class="card-header">
      <div>
        <span class="eyebrow">DEALER GREEKS &amp; SECOND-ORDER FLOWS</span>
        <h3 class="card-title">Instantaneous Hedging Differential</h3>
      </div>
      <div v-if="snap" class="formula-badge">
        F<sub>hedge</sub> = GEX&middot;&Delta;S + VEX&middot;&Delta;&sigma; + CHEX
      </div>
    </div>

    <!-- 4-Metric Grid with Visual Balance Meters.
         Gated on the whole row, not on each value: dashing the numbers out
         while leaving the tone classes and state pills ("VOL DAMPEN",
         "IV Collapse -> Dealer Buying Flow") still asserts a dealer posture
         that was never measured. The pills come from `x ?? 0 >= 0`, so an
         absent reading paints as positive. -->
    <div v-if="snap" class="metrics-row">
      <!-- 1. Net GEX -->
      <div class="greek-box" :class="{ positive: isNetGexPositive, negative: !isNetGexPositive }">
        <div class="box-top">
          <span class="greek-label">NET GEX · CHAIN TOTAL (1% MOVE)</span>
          <span class="state-pill" :class="isNetGexPositive ? 'pos' : 'neg'">
            {{ isNetGexPositive ? 'VOL DAMPEN' : 'VOL ACCEL' }}
          </span>
        </div>
        <div class="greek-val font-mono">{{ snap ? optSigned(snap.net_gex_m, 2) : DASH }}M</div>
        <!-- Visual Call vs Put Ratio Bar -->
        <div class="ratio-bar-wrap">
          <div class="ratio-bar">
            <div class="ratio-fill call" :style="{ width: `${callGexRatio}%` }"></div>
            <div class="ratio-fill put" :style="{ width: `${100 - callGexRatio}%` }"></div>
          </div>
        </div>
        <div class="greek-sub">
          Calls: {{ snap && snap.call_gex_m != null ? `+$${num(snap.call_gex_m, 1)}M` : DASH }} |
          Puts:
          {{ snap && snap.put_gex_m != null ? `-$${num(Math.abs(snap.put_gex_m), 1)}M` : DASH }}
        </div>
        <!-- The map's headline is the curve read at live spot, which is a
             different measurement from the chain-wide strike sum above.
             Printed side by side and named, they stop reading as one number
             that cannot make up its mind. -->
        <div v-if="netGexAtSpot != null" class="greek-sub">
          At spot (map curve): {{ optSigned(netGexAtSpot, 2) }}M<span v-if="netGexGapPct != null">
            &middot; {{ optSigned(netGexGapPct, 0) }}% vs chain total</span
          >
        </div>
      </div>

      <!-- 2. Net VEX -->
      <div class="greek-box" :class="{ positive: isNetVexPositive, negative: !isNetVexPositive }">
        <div class="box-top">
          <span class="greek-label">NET VANNA (VEX)</span>
          <span class="state-pill" :class="isNetVexPositive ? 'pos' : 'neg'">
            {{ isNetVexPositive ? 'VOL EXPANSION BID' : 'IV SPIKE SQUEEZE' }}
          </span>
        </div>
        <div class="greek-val font-mono">{{ snap ? optSigned(snap.net_vex_m, 2) : DASH }}M</div>
        <div class="greek-sub">
          {{
            isNetVexPositive
              ? 'IV Collapse -> Dealer Buying Flow'
              : 'IV Spike -> Forced Dealer Liquidation'
          }}
        </div>
      </div>

      <!-- 3. Net DEX. Unlike the boxes either side, this one has a real
           "not measured" state: net_dex_m is null on an unmeasurable chain,
           and a balanced book is a genuine zero. So the sign classes hang off
           hasNetDex rather than a `?? 0`, which would paint an absent reading
           as dealers-are-flat-and-neutral. -->
      <div
        class="greek-box"
        :class="{
          positive: hasNetDex && isNetDexPositive,
          negative: hasNetDex && !isNetDexPositive,
        }"
      >
        <div class="box-top">
          <span class="greek-label">NET DELTA (DEX)</span>
          <span v-if="hasNetDex" class="state-pill" :class="isNetDexPositive ? 'pos' : 'neg'">
            {{ isNetDexPositive ? 'SELLS RALLIES' : 'BUYS RALLIES' }}
          </span>
        </div>
        <div class="greek-val font-mono">
          {{ hasNetDex ? `${optSigned(snap.net_dex_m, 2)}M` : DASH }}
        </div>
        <div class="greek-sub">
          <template v-if="hasNetDex">
            Calls: {{ snap.call_dex_m != null ? `${optSigned(snap.call_dex_m, 1)}M` : DASH }} |
            Puts: {{ snap.put_dex_m != null ? `${optSigned(snap.put_dex_m, 1)}M` : DASH }}
          </template>
          <template v-else>Not measured on this chain</template>
        </div>
        <div class="greek-sub">
          <template v-if="hasNetDex">
            {{
              isNetDexPositive
                ? 'Dealers long delta -> supply into strength (overhead friction)'
                : 'Dealers short delta -> buy strength (squeeze fuel)'
            }}
          </template>
        </div>
      </div>

      <!-- 4. Net CHEX / 0DTE Charm -->
      <div class="greek-box" :class="{ positive: isNetChexPositive, negative: !isNetChexPositive }">
        <div class="box-top">
          <span class="greek-label">NET CHARM (CHEX)</span>
          <span class="state-pill" :class="isNetChexPositive ? 'pos' : 'neg'">
            {{ isNetChexPositive ? 'TIME-DECAY LIFT' : 'TIME-DECAY DRAG' }}
          </span>
        </div>
        <div class="greek-val font-mono">{{ snap ? optSigned(snap.net_chex_m, 2) : DASH }}M/d</div>
        <div class="greek-sub">
          0DTE Charm Drift:
          {{
            snap && snap.zero_dte_charm_drift_m != null
              ? `${optSigned(snap.zero_dte_charm_drift_m, 2)}M/day`
              : DASH
          }}
        </div>
      </div>

      <!-- 4. Total Hedging Flow F_hedge -->
      <div
        class="greek-box total-flow"
        :class="{
          positive: hedgingFlowSign === 1,
          negative: hedgingFlowSign === -1,
        }"
      >
        <div class="box-top">
          <span class="greek-label">TOTAL HEDGING FLOW (F<sub>hedge</sub>)</span>
          <span
            v-if="hedgingFlowSign !== null"
            class="state-pill"
            :class="hedgingFlowSign === 1 ? 'pos' : 'neg'"
          >
            {{ hedgingFlowSign === 1 ? 'SUPPORTIVE' : 'EXTRACTION' }}
          </span>
        </div>
        <div class="greek-val font-mono font-bold">
          <template v-if="hedgingFlowSign !== null"
            >{{ optSigned(snap?.hedging_flow_m, 2) }}M</template
          >
          <template v-else>{{ DASH }}</template>
        </div>
        <!-- F_hedge is a flow RATE: it needs a measured spot and IV velocity,
             not an assumed one. Withheld means withheld — no direction
             sentence, no tone, no pill. -->
        <div class="greek-sub">
          {{
            hedgingFlowSign === null
              ? 'Not measured: needs a live spot and IV velocity, which this feed does not yet carry.'
              : hedgingFlowSign === 1
                ? 'Net Market Inflow (Dealers absorb supply)'
                : 'Net Liquidity Extraction (Selling into drop)'
          }}
        </div>
      </div>
    </div>

    <!-- Structural Boundaries Strip with Distance Percentages -->
    <!-- Levels print through `level()`, which emits a bare dash rather than
         "$—" when one could not be measured. -->
    <div v-if="snap" class="boundaries-strip">
      <div class="bound-item">
        <span class="b-label">PUT WALL (SUPPORT)</span>
        <div class="b-val-row">
          <span class="b-val font-mono text-put-hi">{{ level(lv.putWall) }}</span>
          <span class="b-dist font-mono">({{ distToLevel(lv.putWall) }})</span>
        </div>
      </div>
      <div class="bound-item">
        <span class="b-label">GAMMA FLIP (S*)</span>
        <div class="b-val-row">
          <span class="b-val font-mono text-warn">{{ level(lv.gammaFlip) }}</span>
          <span class="b-dist font-mono">
            ({{ lv.gammaFlip != null ? distToLevel(lv.gammaFlip) : 'none in range' }})
          </span>
        </div>
      </div>
      <div class="bound-item">
        <span class="b-label">CALL WALL (RESISTANCE)</span>
        <div class="b-val-row">
          <span class="b-val font-mono text-call-hi">{{ level(lv.callWall) }}</span>
          <span class="b-dist font-mono">({{ distToLevel(lv.callWall) }})</span>
        </div>
      </div>
      <div class="bound-item">
        <span class="b-label">PIN · ABSOLUTE GAMMA PEAK</span>
        <div class="b-val-row">
          <span class="b-val font-mono text-phosphor">{{ level(lv.pin) }}</span>
          <span class="b-dist font-mono">({{ distToLevel(lv.pin) }})</span>
        </div>
      </div>
    </div>

    <!-- Where the chain snapshot's own solve disagrees with the canonical
         read above. Naming the gap is the point: silently preferring one
         source is what let this card print a second gamma flip. -->
    <p v-if="snap && divergences.length" class="divergence-note">
      Chain snapshot solves these differently: {{ divergences.join(', ') }}. Levels above are the
      page's single regime read; treat the spread as the surface's uncertainty, not as two levels.
    </p>

    <!-- Server-side caveats on this snapshot, which the card previously
         dropped on the floor. -->
    <p v-if="snap && snap.notes?.length" class="divergence-note">{{ snap.notes.join(' · ') }}</p>

    <!-- Withheld, and why. Zeros in every Greek box would read as a balanced
         market rather than an absent one. This is a standalone `v-if`, not the
         tail of a `v-else-if` chain: the notes above sit between it and the
         metrics row, so an `else` would bind to the wrong branch and print
         "withheld" underneath a fully populated card. -->
    <p v-if="!snap && snapshot" class="withheld-note">
      Dealer Greeks withheld: {{ snapshot.quality?.reason ?? 'no measurable option chain' }}.
    </p>
  </div>
</template>

<style scoped>
.divergence-note {
  padding: var(--s2) var(--s3);
  border-top: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.5;
}

.withheld-note {
  padding: var(--s3);
  border-top: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  font-size: var(--t-micro);
  line-height: 1.5;
}

.greeks-flow-card {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.eyebrow {
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
  color: var(--ink-faint);
  font-family: var(--font-mono, monospace);
}

.card-title {
  margin: 0.25rem 0 0;
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--ink);
}

.formula-badge {
  font-size: var(--t-micro);
  font-family: var(--font-mono, monospace);
  color: var(--ink-dim);
  background: var(--panel-hi);
  padding: 0.25rem 0.5rem;
  border-radius: var(--r-sm);
  border: 1px solid var(--rule-faint);
}

.metrics-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0.75rem;
}

.greek-box {
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  border-radius: var(--r-sm);
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.box-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.state-pill {
  font-size: var(--t-nano);
  font-weight: 700;
  font-family: var(--font-mono, monospace);
  padding: 0.1rem 0.35rem;
  border-radius: 2px;
}

.state-pill.pos {
  background: var(--call-wash);
  color: var(--call-hi);
  border: 1px solid var(--call-dim);
}

.state-pill.neg {
  background: var(--put-wash);
  color: var(--put-hi);
  border: 1px solid var(--put-dim);
}

.greek-box.positive {
  border-left: 1px solid var(--long);
}

.greek-box.negative {
  border-left: 1px solid var(--short);
}

.greek-box.total-flow {
  background: var(--panel-raise);
}

.greek-label {
  font-size: var(--t-nano);
  color: var(--ink-faint);
  font-family: var(--font-mono, monospace);
}

.greek-val {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--ink);
}

.greek-box.positive .greek-val {
  color: var(--call-hi);
}

.greek-box.negative .greek-val {
  color: var(--put-hi);
}

.ratio-bar-wrap {
  width: 100%;
  margin: 0.125rem 0;
}

.ratio-bar {
  display: flex;
  height: 4px;
  width: 100%;
  border-radius: 2px;
  overflow: hidden;
  background: var(--void);
}

.ratio-fill.call {
  background: var(--call);
}

.ratio-fill.put {
  background: var(--put);
}

.greek-sub {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  line-height: 1.3;
}

.boundaries-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.75rem;
  padding: 0.75rem;
  background: var(--void-lift);
  border: 1px solid var(--rule-faint);
  border-radius: var(--r-sm);
}

.bound-item {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.b-label {
  font-size: var(--t-nano);
  color: var(--ink-faint);
  font-family: var(--font-mono, monospace);
}

.b-val-row {
  display: flex;
  align-items: baseline;
  gap: 0.375rem;
}

.b-val {
  font-size: 0.9375rem;
  font-weight: 700;
}

.b-dist {
  font-size: var(--t-micro);
  color: var(--ink-faint);
}

.text-call-hi {
  color: var(--call-hi);
}

.text-put-hi {
  color: var(--put-hi);
}

.text-warn {
  color: var(--warn);
}

.text-phosphor {
  color: var(--phosphor);
}
</style>
