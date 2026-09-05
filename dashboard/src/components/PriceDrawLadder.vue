<script setup lang="ts">
/**
 * PriceDrawLadder.vue
 *
 * Instrument-grade visual price attraction ladder & level gauge.
 * Displays real-time spot price relative to key structural magnet targets
 * (Call Wall, Put Wall, Gamma Flip, Max Pain Pin, Kinematic Drift, Volume POC,
 * and Confluence Zones) alongside a ranked tabular attraction target matrix.
 *
 * Adheres strictly to tokens.css design variables, monospace data figures,
 * and zero-spoofing / missing-data protocols.
 */
import { computed } from 'vue'
import type {
  PriceDrawTelemetryPayload,
  PriceDrawLevel,
  PriceDrawLevelType,
  QualityBreakdown,
} from '@/priceDrawContracts'
import { DASH, usd, optSigned, optSignedPct } from '@/format'
import RegimeStateBadge from '@/components/RegimeStateBadge.vue'

const props = withDefaults(
  defineProps<{
    payload?: PriceDrawTelemetryPayload | null
    levels?: PriceDrawLevel[]
    spot?: number | null
    quality?: QualityBreakdown | null
    symbol?: string
    title?: string
    showGauge?: boolean
    showTable?: boolean
    showRegimeBadge?: boolean
    compact?: boolean
    selectedLevelId?: string | null
  }>(),
  {
    payload: null,
    levels: undefined,
    spot: undefined,
    quality: undefined,
    symbol: '',
    title: 'PRICE DRAW LADDER & MAGNET GAUGE',
    showGauge: true,
    showTable: true,
    showRegimeBadge: true,
    compact: false,
    selectedLevelId: null,
  },
)

const emit = defineEmits<{
  'select-level': [level: PriceDrawLevel]
}>()

const activeSymbol = computed<string>(() => {
  if (props.symbol) return props.symbol.toUpperCase()
  if (props.payload?.symbol) return props.payload.symbol.toUpperCase()
  return ''
})

const activeSpot = computed<number | null>(() => {
  if (props.spot !== undefined) return props.spot
  return props.payload?.spot ?? null
})

const activeQuality = computed<QualityBreakdown | null>(() => {
  if (props.quality !== undefined) return props.quality
  return props.payload?.quality ?? null
})

const isMeasurable = computed<boolean>(() => {
  if (activeQuality.value) return activeQuality.value.measurable
  if (props.payload) return props.payload.quality.measurable
  return activeSpot.value !== null && Number.isFinite(activeSpot.value) && activeSpot.value > 0
})

const rawLevels = computed<PriceDrawLevel[]>(() => {
  if (props.levels !== undefined) return props.levels
  return props.payload?.levels ?? []
})

const validLevels = computed<PriceDrawLevel[]>(() => {
  return rawLevels.value.filter((l) => Number.isFinite(l.price) && l.price > 0)
})

// Ranked targets: primary magnet first, then by pull score descending, then by price
const rankedLevels = computed<PriceDrawLevel[]>(() => {
  return [...validLevels.value].sort((a, b) => {
    if (a.is_primary_magnet !== b.is_primary_magnet) {
      return a.is_primary_magnet ? -1 : 1
    }
    const scoreA = a.pull_score ?? -1
    const scoreB = b.pull_score ?? -1
    if (scoreB !== scoreA) {
      return scoreB - scoreA
    }
    return b.price - a.price
  })
})

// Levels sorted by price descending for the vertical ladder gauge
const ladderLevels = computed<PriceDrawLevel[]>(() => {
  return [...validLevels.value].sort((a, b) => b.price - a.price)
})

/* ---- Gauge Price Domain & Normalization ----------------------------------- */
const priceDomain = computed<[number, number]>(() => {
  const spot = activeSpot.value
  const prices: number[] = []
  if (spot !== null && Number.isFinite(spot) && spot > 0) {
    prices.push(spot)
  }
  for (const lvl of validLevels.value) {
    prices.push(lvl.price)
  }
  if (prices.length === 0) {
    return [0, 100]
  }
  let min = Math.min(...prices)
  let max = Math.max(...prices)
  if (min === max) {
    min = min * 0.98
    max = max * 1.02
  }
  const span = max - min
  const pad = Math.max(span * 0.08, 0.5)
  return [min - pad, max + pad]
})

function getPricePositionPct(price: number): number {
  const [min, max] = priceDomain.value
  const span = max - min
  if (span <= 0) return 50
  // In vertical rail, top is 0% (max price) and bottom is 100% (min price)
  const norm = (max - price) / span
  return Math.min(95, Math.max(5, norm * 100))
}

const spotPositionPct = computed<number>(() => {
  if (activeSpot.value === null || !Number.isFinite(activeSpot.value)) return 50
  return getPricePositionPct(activeSpot.value)
})

function getLevelTypeClass(type: PriceDrawLevelType): string {
  switch (type) {
    case 'call_wall':
      return 'type-call-wall'
    case 'put_wall':
      return 'type-put-wall'
    case 'gamma_flip':
      return 'type-gamma-flip'
    case 'kinematic_drift':
      return 'type-kinematic-drift'
    case 'max_pain_pin':
      return 'type-max-pain'
    case 'volume_poc':
      return 'type-volume-poc'
    case 'confluence_zone':
      return 'type-confluence'
    default:
      return 'type-default'
  }
}

function getLensClass(lens: string): string {
  const upper = lens.toUpperCase()
  if (upper.includes('GAMMA') || upper.includes('GEX') || upper.includes('FLIP')) {
    return 'lens-gamma'
  }
  if (upper.includes('KALMAN') || upper.includes('DRIFT') || upper.includes('PRICE')) {
    return 'lens-kalman'
  }
  if (upper.includes('VOLUME') || upper.includes('POC')) {
    return 'lens-volume'
  }
  if (
    upper.includes('CHARM') ||
    upper.includes('THETA') ||
    upper.includes('PIN') ||
    upper.includes('OI')
  ) {
    return 'lens-charm'
  }
  return 'lens-default'
}

function formatLevelDistance(level: PriceDrawLevel): string {
  if (level.distance_pts === null && level.distance_pct === null) {
    return DASH
  }
  const pts = level.distance_pts !== null ? optSigned(level.distance_pts, 2) : DASH
  const pct = level.distance_pct !== null ? optSignedPct(level.distance_pct, 2) : DASH
  return `${pts} (${pct})`
}

function formatPullScorePct(score: number | null): string {
  if (score === null || !Number.isFinite(score)) return DASH
  return `${Math.min(100, Math.max(0, Math.round(score)))}%`
}

function handleLevelClick(level: PriceDrawLevel): void {
  emit('select-level', level)
}
</script>

<template>
  <div class="price-draw-ladder" :class="{ 'is-compact': compact }">
    <!-- Header Bar -->
    <div class="ladder-header">
      <div class="header-left">
        <span class="ladder-title">{{ title }}</span>
        <span v-if="activeSymbol" class="symbol-tag">{{ activeSymbol }}</span>
      </div>

      <div class="header-right">
        <!-- Spot Readout -->
        <div class="spot-readout">
          <span class="spot-label">SPOT:</span>
          <span class="spot-price mono-val">
            {{ activeSpot !== null ? usd(activeSpot) : DASH }}
          </span>
          <span v-if="isMeasurable" class="live-pulse-dot" title="Live Continuous Stream" />
        </div>

        <!-- Optional Embedded Regime Badge -->
        <RegimeStateBadge
          v-if="showRegimeBadge && (payload || !isMeasurable)"
          :payload="payload"
          :measurable="isMeasurable"
          :compact="true"
        />
      </div>
    </div>

    <!-- Measurable Content -->
    <template v-if="isMeasurable && validLevels.length > 0">
      <!-- Visual Level Gauge Track -->
      <div v-if="showGauge" class="gauge-section">
        <div class="gauge-track-container">
          <!-- Rail axis line -->
          <div class="gauge-rail" />

          <!-- Spot Indicator Marker Line -->
          <div
            v-if="activeSpot !== null"
            class="gauge-marker spot-marker"
            :style="{ top: `${spotPositionPct}%` }"
          >
            <div class="marker-line spot-line" />
            <div class="marker-badge spot-badge">
              <span class="spot-icon">●</span>
              <span class="spot-badge-text">SPOT {{ usd(activeSpot) }}</span>
              <span class="spot-live-sub">ACTIVE</span>
            </div>
          </div>

          <!-- Target Level Markers -->
          <div
            v-for="level in ladderLevels"
            :key="level.id"
            class="gauge-marker level-marker"
            :class="[
              getLevelTypeClass(level.type),
              {
                'is-primary': level.is_primary_magnet,
                'is-selected': selectedLevelId === level.id,
              },
            ]"
            :style="{ top: `${getPricePositionPct(level.price)}%` }"
            @click="handleLevelClick(level)"
          >
            <div class="marker-line level-line" />
            <div class="marker-badge level-badge" :title="level.regime_role">
              <span v-if="level.is_primary_magnet" class="star-icon">★</span>
              <span class="direction-arrow">
                {{ level.direction === 'above' ? '▲' : level.direction === 'below' ? '▼' : '●' }}
              </span>
              <span class="level-label">{{ level.label }}</span>
              <span class="level-price mono-val">{{ usd(level.price) }}</span>
              <span v-if="level.distance_pct !== null" class="level-dist mono-val">
                ({{ optSignedPct(level.distance_pct) }})
              </span>
              <span v-if="level.pull_score !== null" class="level-pull-chip mono-val">
                PULL {{ formatPullScorePct(level.pull_score) }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Ranked Attraction Targets Table -->
      <div v-if="showTable" class="targets-table-section">
        <div class="table-title-row">
          <span class="section-label">RANKED ATTRACTION TARGETS</span>
          <span class="count-tag">{{ rankedLevels.length }} TARGETS IDENTIFIED</span>
        </div>

        <div class="table-wrapper">
          <table class="targets-table">
            <thead>
              <tr>
                <th class="th-level">LEVEL</th>
                <th class="th-type">TYPE</th>
                <th class="th-dist">DIST (PTS / %)</th>
                <th class="th-pull">PULL SCORE</th>
                <th class="th-role">REGIME ROLE</th>
                <th class="th-lenses">SUPPORTING LENSES</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="lvl in rankedLevels"
                :key="lvl.id"
                class="target-row"
                :class="[
                  getLevelTypeClass(lvl.type),
                  {
                    'is-primary': lvl.is_primary_magnet,
                    'is-selected': selectedLevelId === lvl.id,
                  },
                ]"
                @click="handleLevelClick(lvl)"
              >
                <!-- LEVEL (Price + Direction) -->
                <td class="td-level">
                  <!-- The row stays clickable for the mouse; the action also
                       lives on a real button so it is keyboard-reachable and
                       announced (WCAG 2.1.1). -->
                  <button
                    type="button"
                    class="row-select-btn"
                    :aria-pressed="selectedLevelId === lvl.id"
                    @click.stop="handleLevelClick(lvl)"
                  >
                    <span class="sr-only">Select level {{ usd(lvl.price) }}</span>
                  </button>
                  <div class="price-cell">
                    <span
                      class="dir-glyph"
                      :class="{
                        'is-above': lvl.direction === 'above',
                        'is-below': lvl.direction === 'below',
                      }"
                    >
                      {{ lvl.direction === 'above' ? '▲' : lvl.direction === 'below' ? '▼' : '●' }}
                    </span>
                    <span class="price-val mono-val">{{ usd(lvl.price) }}</span>
                    <span
                      v-if="lvl.is_primary_magnet"
                      class="primary-star"
                      title="Primary Magnet Target"
                      >★</span
                    >
                  </div>
                </td>

                <!-- TYPE / LABEL -->
                <td class="td-type">
                  <span class="type-pill" :class="getLevelTypeClass(lvl.type)">
                    {{ lvl.label }}
                  </span>
                </td>

                <!-- DISTANCE (PTS / %) -->
                <td class="td-dist">
                  <span
                    class="dist-val mono-val"
                    :class="{
                      'is-pos': (lvl.distance_pts ?? 0) > 0,
                      'is-neg': (lvl.distance_pts ?? 0) < 0,
                    }"
                  >
                    {{ formatLevelDistance(lvl) }}
                  </span>
                </td>

                <!-- PULL SCORE + PROGRESS BAR -->
                <td class="td-pull">
                  <div class="pull-cell">
                    <span class="pull-text mono-val">{{ formatPullScorePct(lvl.pull_score) }}</span>
                    <div class="pull-bar-track">
                      <div
                        class="pull-bar-fill"
                        :class="getLevelTypeClass(lvl.type)"
                        :style="{ width: `${Math.min(100, Math.max(0, lvl.pull_score ?? 0))}%` }"
                      />
                    </div>
                  </div>
                </td>

                <!-- REGIME ROLE -->
                <td class="td-role">
                  <span class="role-text" :title="lvl.regime_role">
                    {{ lvl.regime_role || DASH }}
                  </span>
                </td>

                <!-- SUPPORTING LENSES -->
                <td class="td-lenses">
                  <div class="lenses-wrap">
                    <span
                      v-for="lens in lvl.supporting_lenses"
                      :key="lens"
                      class="lens-chip"
                      :class="getLensClass(lens)"
                    >
                      {{ lens }}
                    </span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- Unmeasured / Empty State -->
    <div v-else class="unmeasured-state">
      <div class="unmeasured-icon-bar">—</div>
      <div class="unmeasured-title">REGIME UNMEASURED · NO ACTIVE PRICE MAGNETS</div>
      <div class="unmeasured-reason">
        {{
          activeQuality?.reason ||
          'Open interest, option chain, or spot feed is unavailable for this underlier.'
        }}
      </div>
    </div>
  </div>
</template>

<style scoped>
/* The keyboard affordance for .target-row. Painted as a full-row overlay so it
   adds no layout of its own; the visible styling stays on the row itself. */
.row-select-btn {
  position: absolute;
  inset: 0;
  width: 100%;
  padding: 0;
  background: none;
  border: none;
}
.row-select-btn:focus-visible {
  outline: var(--focus-ring);
  outline-offset: -2px;
}
.target-row {
  position: relative;
}

.price-draw-ladder {
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  padding: var(--s3);
  gap: var(--s3);
  min-width: 0;
}

.price-draw-ladder.is-compact {
  padding: var(--s2);
  gap: var(--s2);
}

/* Header */
.ladder-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: var(--hair) solid var(--rule);
  padding-bottom: var(--s2);
  flex-wrap: wrap;
  gap: var(--s2);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.ladder-title {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 800;
  letter-spacing: 0.08em;
  color: var(--ink-soft);
  text-transform: uppercase;
}

.symbol-tag {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 850;
  color: var(--phosphor);
  background: var(--phosphor-wash);
  padding: 1px 6px;
  border-radius: var(--r-xs);
  border: var(--hair) solid color-mix(in srgb, var(--phosphor) 35%, var(--rule));
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
}

.spot-readout {
  display: inline-flex;
  align-items: center;
  gap: var(--s1);
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  color: var(--ink-dim);
}

.spot-label {
  font-weight: 700;
  letter-spacing: 0.04em;
}

.spot-price {
  font-weight: 800;
  color: var(--ink);
}

.live-pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--phosphor);
  margin-left: 2px;
}

/* Visual Gauge Section */
.gauge-section {
  display: flex;
  flex-direction: column;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-faint);
  border-radius: var(--r-sm);
  padding: var(--s3) var(--s2);
  min-height: 210px;
  position: relative;
  overflow: hidden;
}

.gauge-track-container {
  position: relative;
  width: 100%;
  height: 180px;
  margin: 0 auto;
}

.gauge-rail {
  position: absolute;
  left: 28px;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--rule);
}

.gauge-marker {
  position: absolute;
  left: 28px;
  right: 8px;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  cursor: pointer;
  transition: transform var(--dur-fast) var(--ease-out);
}

.gauge-marker:hover {
  z-index: 10;
}

.marker-line {
  height: 1px;
  width: 24px;
  background: var(--rule-hi);
  flex-shrink: 0;
}

.spot-line {
  background: var(--phosphor);
  height: 2px;
  width: 32px;
}

.marker-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--s1);
  padding: 2px 8px;
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 700;
  border: var(--hair) solid var(--rule);
  background: var(--panel-hi);
  color: var(--ink-soft);
  white-space: nowrap;
  user-select: none;
}

.spot-badge {
  border-color: color-mix(in srgb, var(--phosphor) 50%, var(--rule));
  background: var(--phosphor-wash);
  color: var(--ink);
  font-weight: 850;
}

.spot-icon {
  color: var(--phosphor);
}

.spot-live-sub {
  font-size: var(--t-micro);
  color: var(--phosphor-dim);
  letter-spacing: 0.05em;
}

.star-icon {
  color: var(--phosphor);
  font-size: var(--t-tiny);
}

.level-pull-chip {
  padding: 0 4px;
  border-radius: var(--r-xs);
  background: var(--panel-wash);
  color: var(--ink);
  font-size: var(--t-micro);
}

/* Level Marker Types */
.level-marker.type-call-wall .marker-line {
  background: var(--call-hi);
}
.level-marker.type-call-wall .marker-badge {
  border-color: color-mix(in srgb, var(--call) 45%, var(--rule));
  background: var(--call-wash);
  color: var(--call-hi);
}

.level-marker.type-put-wall .marker-line {
  background: var(--put-hi);
}
.level-marker.type-put-wall .marker-badge {
  border-color: color-mix(in srgb, var(--put) 45%, var(--rule));
  background: var(--put-wash);
  color: var(--put-hi);
}

.level-marker.type-gamma-flip .marker-line {
  background: var(--warn);
}
.level-marker.type-gamma-flip .marker-badge {
  border-color: color-mix(in srgb, var(--warn) 45%, var(--rule));
  background: var(--warn-wash);
  color: var(--warn);
}

.level-marker.type-kinematic-drift .marker-line {
  background: var(--phosphor);
}
.level-marker.type-kinematic-drift .marker-badge {
  border-color: color-mix(in srgb, var(--phosphor) 45%, var(--rule));
  background: var(--phosphor-wash);
  color: var(--phosphor);
}

.level-marker.type-max-pain .marker-line {
  background: var(--badge-split);
}
.level-marker.type-max-pain .marker-badge {
  border-color: color-mix(in srgb, var(--cat-4) 45%, var(--rule));
  background: var(--badge-split-wash);
  color: var(--badge-split);
}

.level-marker.type-volume-poc .marker-line {
  background: var(--badge-sweep);
}
.level-marker.type-volume-poc .marker-badge {
  border-color: color-mix(in srgb, var(--cat-1) 45%, var(--rule));
  background: var(--badge-sweep-wash);
  color: var(--badge-sweep);
}

.level-marker.type-confluence .marker-line {
  background: var(--cat-2);
}
.level-marker.type-confluence .marker-badge {
  border-color: color-mix(in srgb, var(--cat-2) 45%, var(--rule));
  background: var(--badge-block-wash);
  color: var(--cat-2);
}

.level-marker.is-selected .marker-badge {
  outline: var(--hair) solid var(--phosphor);
}

/* Targets Table Section */
.targets-table-section {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.table-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-label {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 750;
  letter-spacing: 0.05em;
  color: var(--ink-dim);
}

.count-tag {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  color: var(--ink-faint);
}

.table-wrapper {
  overflow-x: auto;
}

.targets-table {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--font-ui);
  font-size: var(--t-small);
  text-align: left;
}

.targets-table th {
  padding: 6px 8px;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 750;
  letter-spacing: 0.05em;
  color: var(--ink-faint);
  border-bottom: var(--hair) solid var(--rule);
  text-transform: uppercase;
  white-space: nowrap;
}

.targets-table td {
  padding: 6px 8px;
  border-bottom: var(--hair) solid var(--rule-faint);
  vertical-align: middle;
  white-space: nowrap;
}

.target-row {
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}

.target-row:hover {
  background: var(--panel-hi);
}

.target-row.is-selected {
  background: var(--panel-raise);
  outline: var(--hair) solid var(--rule-hi);
}

/* Cell Contents */
.price-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--s1);
}

.dir-glyph {
  font-size: var(--t-micro);
  color: var(--ink-faint);
}

.dir-glyph.is-above {
  color: var(--call-hi);
}

.dir-glyph.is-below {
  color: var(--put-hi);
}

.price-val {
  font-weight: 750;
  color: var(--ink);
}

.primary-star {
  color: var(--phosphor);
  font-size: var(--t-tiny);
  margin-left: 2px;
}

.type-pill {
  display: inline-block;
  padding: 1px 6px;
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 750;
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
  color: var(--ink-dim);
}

.type-pill.type-call-wall {
  color: var(--call-hi);
  border-color: color-mix(in srgb, var(--call) 45%, var(--rule));
  background: var(--call-wash);
}

.type-pill.type-put-wall {
  color: var(--put-hi);
  border-color: color-mix(in srgb, var(--put) 45%, var(--rule));
  background: var(--put-wash);
}

.type-pill.type-gamma-flip {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 45%, var(--rule));
  background: var(--warn-wash);
}

.type-pill.type-kinematic-drift {
  color: var(--phosphor);
  border-color: color-mix(in srgb, var(--phosphor) 45%, var(--rule));
  background: var(--phosphor-wash);
}

.type-pill.type-max-pain {
  color: var(--badge-split);
  border-color: color-mix(in srgb, var(--cat-4) 45%, var(--rule));
  background: var(--badge-split-wash);
}

.type-pill.type-volume-poc {
  color: var(--badge-sweep);
  border-color: color-mix(in srgb, var(--cat-1) 45%, var(--rule));
  background: var(--badge-sweep-wash);
}

.type-pill.type-confluence {
  color: var(--cat-2);
  border-color: color-mix(in srgb, var(--cat-2) 45%, var(--rule));
  background: var(--badge-block-wash);
}

.dist-val {
  color: var(--ink-dim);
  font-weight: 600;
}

.dist-val.is-pos {
  color: var(--call-hi);
}

.dist-val.is-neg {
  color: var(--put-hi);
}

.pull-cell {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.pull-text {
  font-weight: 750;
  color: var(--ink);
  min-width: 32px;
}

.pull-bar-track {
  width: 64px;
  height: 5px;
  background: var(--void-lift);
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule-faint);
  overflow: hidden;
}

.pull-bar-fill {
  height: 100%;
  border-radius: var(--r-xs);
  background: var(--ink-dim);
}

.pull-bar-fill.type-call-wall {
  background: var(--call-hi);
}
.pull-bar-fill.type-put-wall {
  background: var(--put-hi);
}
.pull-bar-fill.type-gamma-flip {
  background: var(--warn);
}
.pull-bar-fill.type-kinematic-drift {
  background: var(--phosphor);
}
.pull-bar-fill.type-max-pain {
  background: var(--badge-split);
}
.pull-bar-fill.type-volume-poc {
  background: var(--badge-sweep);
}
.pull-bar-fill.type-confluence {
  background: var(--cat-2);
}

.role-text {
  font-size: var(--t-micro);
  color: var(--ink-soft);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.lenses-wrap {
  display: flex;
  gap: 3px;
  flex-wrap: wrap;
}

.lens-chip {
  padding: 0 4px;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 700;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
  background: var(--void-lift);
  color: var(--ink-dim);
}

.lens-chip.lens-gamma {
  color: var(--badge-golden);
  border-color: var(--badge-golden-border);
  background: var(--badge-golden-wash);
}

.lens-chip.lens-kalman {
  color: var(--phosphor);
  border-color: color-mix(in srgb, var(--phosphor) 35%, var(--rule));
  background: var(--phosphor-wash);
}

.lens-chip.lens-volume {
  color: var(--badge-sweep);
  border-color: color-mix(in srgb, var(--call) 50%, var(--rule));
  background: var(--badge-sweep-wash);
}

.lens-chip.lens-charm {
  color: var(--badge-split);
  border-color: color-mix(in srgb, var(--cat-4) 45%, var(--rule));
  background: var(--badge-split-wash);
}

/* Unmeasured State */
.unmeasured-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--s5) var(--s3);
  text-align: center;
  background: var(--void-lift);
  border: var(--hair) solid var(--rule-faint);
  border-radius: var(--r-sm);
  gap: var(--s2);
}

.unmeasured-icon-bar {
  font-family: var(--font-data);
  font-size: var(--t-fig);
  color: var(--ink-faint);
}

.unmeasured-title {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 800;
  letter-spacing: 0.06em;
  color: var(--ink-dim);
}

.unmeasured-reason {
  font-size: var(--t-micro);
  color: var(--ink-faint);
  max-width: 420px;
  line-height: 1.4;
}

.mono-val {
  font-family: var(--font-data);
}
</style>
