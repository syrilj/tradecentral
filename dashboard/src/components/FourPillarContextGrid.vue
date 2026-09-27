<script setup lang="ts">
/**
 * FourPillarContextGrid.vue
 *
 * Decomposes the market regime into 4 specialized analytical pillars:
 *   1. Trend Pillar (Kinematic Kalman Velocity & Z-Score)
 *   2. Volatility Pillar (252d Realized Volatility Percentile & Dispersion)
 *   3. Structure Pillar (Lo-MacKinlay Variance Ratio & OU Half-Life)
 *   4. Flow Pillar (Signed Flow MAD Z-Score & Dealer Gamma Topography)
 *
 * Implements strict zero-spoofing honest unmeasured state styling when a lens is absent.
 */
import { computed } from 'vue'
import type { MarketRegimePayload } from '@/regimeContracts'
import { DASH, num, pct, pctFrac, signed } from '@/format'

const props = withDefaults(
  defineProps<{
    payload?: MarketRegimePayload | null
    loading?: boolean
  }>(),
  {
    payload: null,
    loading: false,
  },
)

/**
 * First-load state: no payload yet while a request is in flight. Distinct
 * from the honest "unmeasured" verdict -- this is "not yet computed".
 */
const isMeasuring = computed<boolean>(() => !props.payload && props.loading)
const MEASURING_TEXT = 'Awaiting first market-state computation.'

const trend = computed(() => props.payload?.trend)
const vol = computed(() => props.payload?.volatility)
const struct = computed(() => props.payload?.structure)
const flow = computed(() => props.payload?.flow)

// Trend calculations
const trendState = computed<string>(() => trend.value?.state ?? 'unmeasured')
const trendMeasured = computed<boolean>(() => trend.value?.measured === true)
const kalmanZ = computed<number | null>(() => trend.value?.kalmanZScore ?? null)
const kalmanV = computed<number | null>(() => trend.value?.kalmanVelocity ?? null)
const trendPersistence = computed<number | null>(() => trend.value?.trendPersistence ?? null)

// Volatility calculations
const volState = computed<string>(() => vol.value?.state ?? 'unmeasured')
const volMeasured = computed<boolean>(() => vol.value?.measured === true)
const volPctile = computed<number | null>(() => vol.value?.volPercentile ?? null)
const realizedVol = computed<number | null>(() => vol.value?.realizedVolPct ?? null)
const ivHvRatio = computed<number | null>(() => vol.value?.ivHvRatio ?? null)

// Structure calculations
const structState = computed<string>(() => struct.value?.state ?? 'unmeasured')
const structMeasured = computed<boolean>(() => struct.value?.measured === true)
const ouHalfLife = computed<number | null>(() => struct.value?.ouHalfLifeBars ?? null)
const hurstExp = computed<number | null>(() => struct.value?.hurstExponent ?? null)

// Flow calculations
const flowState = computed<string>(() => flow.value?.state ?? 'unmeasured')
const flowMeasured = computed<boolean>(() => flow.value?.measured === true)
const dealerGammaRegime = computed<string>(() => flow.value?.dealerGammaRegime ?? 'unmeasurable')
const netGexM = computed<number | null>(() => flow.value?.netGexM ?? null)
</script>

<template>
  <div class="four-pillar-grid">
    <!-- Pillar 1: Trend -->
    <div class="pillar-card" :class="[{ 'is-unmeasured': !trendMeasured }]">
      <div class="pillar-head">
        <span class="pillar-tag">PILLAR 01</span>
        <h3 class="pillar-name">TREND & PERSISTENCE</h3>
        <span class="pillar-badge" :class="`state-${trendState}`">
          {{
            trendMeasured
              ? trendState.replace(/_/g, ' ').toUpperCase()
              : isMeasuring
                ? 'MEASURING'
                : 'UNMEASURED'
          }}
        </span>
      </div>
      <div class="pillar-body">
        <template v-if="trendMeasured">
          <div class="metric-row">
            <span class="m-label">Kinematic speed</span>
            <span
              class="m-val mono"
              :class="{ 'c-pos': (kalmanV ?? 0) > 0, 'c-neg': (kalmanV ?? 0) < 0 }"
            >
              {{ kalmanV !== null ? signed(kalmanV, 4) : DASH }}
            </span>
          </div>
          <div class="metric-row">
            <span class="m-label">Speed vs history</span>
            <span
              class="m-val mono"
              :class="{ 'c-warn': kalmanZ !== null && Math.abs(kalmanZ) >= 1.5 }"
            >
              {{ kalmanZ !== null ? `${signed(kalmanZ, 2)}σ` : DASH }}
            </span>
          </div>
          <div class="metric-row">
            <span class="m-label">Persistence Index</span>
            <span class="m-val mono">
              {{
                trendPersistence !== null
                  ? trendPersistence > 1
                    ? `${Math.round(trendPersistence)} bars`
                    : pctFrac(trendPersistence, 0)
                  : DASH
              }}
            </span>
          </div>
        </template>
        <div v-else class="unmeasured-notice">
          <span class="unm-icon">◌</span>
          <span class="unm-text">{{
            isMeasuring
              ? MEASURING_TEXT
              : 'Price bar history insufficient to compute Kinematic Kalman filter.'
          }}</span>
        </div>
      </div>
    </div>

    <!-- Pillar 2: Volatility -->
    <div class="pillar-card" :class="[{ 'is-unmeasured': !volMeasured }]">
      <div class="pillar-head">
        <span class="pillar-tag">PILLAR 02</span>
        <h3 class="pillar-name">VOLATILITY ENVIRONMENT</h3>
        <span class="pillar-badge" :class="`state-${volState}`">
          {{
            volMeasured
              ? volState.replace(/_/g, ' ').toUpperCase()
              : isMeasuring
                ? 'MEASURING'
                : 'UNMEASURED'
          }}
        </span>
      </div>
      <div class="pillar-body">
        <template v-if="volMeasured">
          <div class="metric-row">
            <span class="m-label">252d Vol Percentile</span>
            <span class="m-val mono" :class="{ 'c-warn': (volPctile ?? 0) >= 0.8 }">
              {{ volPctile !== null ? pctFrac(volPctile, 1) : DASH }}
            </span>
          </div>
          <div class="metric-row">
            <span class="m-label">Realized Vol (20D)</span>
            <span class="m-val mono">{{ realizedVol !== null ? pct(realizedVol, 1) : DASH }}</span>
          </div>
          <div class="metric-row">
            <span class="m-label">IV / HV Ratio</span>
            <span class="m-val mono">{{ ivHvRatio !== null ? num(ivHvRatio, 2) : DASH }}</span>
          </div>
        </template>
        <div v-else class="unmeasured-notice">
          <span class="unm-icon">◌</span>
          <span class="unm-text">{{
            isMeasuring ? MEASURING_TEXT : 'Historical volatility distribution unavailable.'
          }}</span>
        </div>
      </div>
    </div>

    <!-- Pillar 3: Structure -->
    <div class="pillar-card" :class="[{ 'is-unmeasured': !structMeasured }]">
      <div class="pillar-head">
        <span class="pillar-tag">PILLAR 03</span>
        <h3 class="pillar-name">MARKET STRUCTURE</h3>
        <span class="pillar-badge" :class="`state-${structState}`">
          {{
            structMeasured
              ? structState.replace(/_/g, ' ').toUpperCase()
              : isMeasuring
                ? 'MEASURING'
                : 'UNMEASURED'
          }}
        </span>
      </div>
      <div class="pillar-body">
        <template v-if="structMeasured">
          <div class="metric-row">
            <span class="m-label">OU Reversion Half-Life</span>
            <span class="m-val mono">{{
              ouHalfLife !== null ? `${num(ouHalfLife, 1)} bars` : DASH
            }}</span>
          </div>
          <div class="metric-row">
            <span class="m-label">Hurst Exponent (H)</span>
            <span class="m-val mono">{{ hurstExp !== null ? num(hurstExp, 2) : DASH }}</span>
          </div>
          <div class="metric-row">
            <span class="m-label">Diffusion Regime</span>
            <span class="m-val mono">
              {{
                (hurstExp ?? 0.5) > 0.55
                  ? 'Super-diffusive'
                  : (hurstExp ?? 0.5) < 0.45
                    ? 'Sub-diffusive'
                    : 'Random walk'
              }}
            </span>
          </div>
        </template>
        <div v-else class="unmeasured-notice">
          <span class="unm-icon">◌</span>
          <span class="unm-text">{{
            isMeasuring ? MEASURING_TEXT : 'Variance ratio and mean-reversion telemetry unmeasured.'
          }}</span>
        </div>
      </div>
    </div>

    <!-- Pillar 4: Flow -->
    <div class="pillar-card" :class="[{ 'is-unmeasured': !flowMeasured }]">
      <div class="pillar-head">
        <span class="pillar-tag">PILLAR 04</span>
        <h3 class="pillar-name">ORDER FLOW & GAMMA</h3>
        <span class="pillar-badge" :class="`state-${flowState}`">
          {{
            flowMeasured
              ? flowState.replace(/_/g, ' ').toUpperCase()
              : isMeasuring
                ? 'MEASURING'
                : 'UNMEASURED'
          }}
        </span>
      </div>
      <div class="pillar-body">
        <template v-if="flowMeasured">
          <div class="metric-row">
            <span class="m-label">Dealer Gamma Regime</span>
            <span
              class="m-val mono"
              :class="{
                'c-pos': dealerGammaRegime === 'long',
                'c-neg': dealerGammaRegime === 'short',
              }"
            >
              {{ dealerGammaRegime.toUpperCase() }} Γ
            </span>
          </div>
          <div class="metric-row">
            <span class="m-label">Net Dollar GEX</span>
            <span
              class="m-val mono"
              :class="{ 'c-pos': (netGexM ?? 0) > 0, 'c-neg': (netGexM ?? 0) < 0 }"
            >
              {{
                netGexM !== null
                  ? `${netGexM >= 0 ? '+' : '-'}$${num(Math.abs(netGexM), 1)}M`
                  : DASH
              }}
            </span>
          </div>
          <div class="metric-row">
            <span class="m-label">Hedging Bias</span>
            <span
              class="m-val mono"
              :class="{
                'c-pos': flow?.hedgingPressureDirection === 'supportive',
                'c-neg': flow?.hedgingPressureDirection === 'pressuring',
              }"
            >
              {{ flow?.hedgingPressureDirection?.toUpperCase() ?? DASH }}
            </span>
          </div>
        </template>
        <div v-else class="unmeasured-notice">
          <span class="unm-icon">◌</span>
          <span class="unm-text">{{
            isMeasuring ? MEASURING_TEXT : 'No active option chain. Flow & dealer Greeks withheld.'
          }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.four-pillar-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s3);
  min-width: 0;
}

@media (max-width: 1100px) {
  .four-pillar-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 600px) {
  .four-pillar-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.pillar-card {
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  padding: var(--s3);
  gap: var(--s2);
  min-width: 0;
}

.pillar-card.is-unmeasured {
  background: var(--void-lift);
  border-color: var(--rule-faint);
  opacity: 0.85;
}

.pillar-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-bottom: var(--hair) solid var(--rule);
  padding-bottom: var(--s2);
}

.pillar-tag {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  color: var(--ink-dim);
}

.pillar-name {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--t-small);
  font-weight: 700;
  color: var(--ink);
}

.pillar-badge {
  align-self: flex-start;
  margin-top: 4px;
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 800;
  padding: 1px 6px;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
  background: var(--void);
}

/* Pillar Badge Semantic Colors */
.state-strong_up,
.state-up,
.state-trending,
.state-accumulation {
  color: var(--call-hi);
  background: var(--call-wash);
  border-color: var(--call);
}

.state-strong_down,
.state-down,
.state-distribution,
.state-shock {
  color: var(--put-hi);
  background: var(--put-wash);
  border-color: var(--put);
}

.state-compression,
.state-range_bound,
.state-balanced {
  color: var(--badge-sweep);
  background: var(--badge-sweep-wash);
  border-color: var(--cat-1);
}

.state-mean_reverting,
.state-churn {
  color: var(--badge-split);
  background: var(--badge-split-wash);
  border-color: var(--cat-4);
}

.state-unmeasured {
  color: var(--ink-faint);
  background: var(--void);
  border-color: var(--rule-faint);
}

.pillar-body {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.metric-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--s2);
  min-width: 0;
}

.m-label {
  font-family: var(--font-ui);
  font-size: var(--t-tiny);
  color: var(--ink-dim);
  min-width: 0;
}

.m-val {
  font-size: var(--t-tiny);
  font-weight: 700;
  color: var(--ink);
  flex: 0 0 auto;
  text-align: right;
}

.unmeasured-notice {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: var(--s2) 0;
  color: var(--ink-faint);
  font-family: var(--font-ui);
  font-size: var(--t-tiny);
}

.unm-icon {
  font-size: var(--t-body);
  color: var(--ink-faint);
}

.c-pos {
  color: var(--call-hi);
}
.c-neg {
  color: var(--put-hi);
}
.c-warn {
  color: var(--warn);
}
.mono {
  font-family: var(--font-data);
}
</style>
