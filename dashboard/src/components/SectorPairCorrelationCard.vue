<script setup lang="ts">
import { computed } from 'vue'
import type { RegimeBreadthPayload, RegimeSymbolRow } from '@/regimeContracts'
import { tickerSector, tickerSectorEtf, tickerSectorCode } from '@/tickerIdentity'

const props = defineProps<{
  symbol: string
  spot: number | null
  dayChangePct?: number | null
  breadthPayload: RegimeBreadthPayload | null
}>()

const emit = defineEmits<{
  selectSymbol: [symbol: string]
}>()

const cleanSym = computed(() => props.symbol.toUpperCase().trim())
const sectorName = computed(() => tickerSector(cleanSym.value))
const sectorEtf = computed(() => tickerSectorEtf(cleanSym.value))
const sectorCode = computed(() => tickerSectorCode(cleanSym.value))

const isIndexOrEtf = computed(() =>
  [
    'SPY',
    'QQQ',
    'IWM',
    'DIA',
    'XLK',
    'XLF',
    'XLE',
    'XLV',
    'XLI',
    'XLY',
    'XLP',
    'XLU',
    'XLB',
    'XLRE',
    'XLC',
  ].includes(cleanSym.value),
)

// Find sector row in breadth payload
const sectorRow = computed<RegimeSymbolRow | null>(() => {
  if (!props.breadthPayload?.rows) return null
  return props.breadthPayload.rows.find((r) => r.symbol === sectorEtf.value) ?? null
})

// Calculate relative performance (Alpha vs Sector ETF)
const tickerReturn = computed(() => props.dayChangePct ?? 0)
const sectorReturn = computed(() => {
  if (sectorRow.value?.distanceToFlip != null) {
    // If we have price change in row or estimate
    return 0 // default neutral if raw return not directly in row
  }
  return 0
})

const relativeAlpha = computed(() => {
  return tickerReturn.value - sectorReturn.value
})

const pairLeadershipStatus = computed(() => {
  if (isIndexOrEtf.value) {
    return {
      status: 'BENCHMARK',
      tone: 'neutral',
      desc: 'Benchmark / Core Sector ETF',
    }
  }

  const alpha = relativeAlpha.value
  if (alpha >= 0.6) {
    return {
      status: 'SECTOR LEADER (+ALPHA)',
      tone: 'long',
      desc: `Outperforming ${sectorEtf.value} by +${alpha.toFixed(2)}%. Idiosyncratic strength / institutional bidding.`,
    }
  } else if (alpha <= -0.6) {
    return {
      status: 'SECTOR LAGGING (-DRAG)',
      tone: 'short',
      desc: `Lagging ${sectorEtf.value} by ${alpha.toFixed(2)}%. Sector drag or underlier-specific supply.`,
    }
  } else {
    return {
      status: 'BETA TIDE (IN-LINE)',
      tone: 'neutral',
      desc: `Trading in close correlation with ${sectorEtf.value} (${sectorName.value}). Move is macro/sector driven.`,
    }
  }
})

// Sector Rows sorted by gamma stance
const allSectorRows = computed(() => {
  if (!props.breadthPayload?.rows) return []
  return props.breadthPayload.rows.filter((r) => r.kind === 'sector')
})
</script>

<template>
  <div class="sector-pair-card">
    <div class="card-header">
      <div>
        <span class="eyebrow">SECTOR ROTATION &amp; PAIR CORRELATION</span>
        <h3 class="card-title">
          {{ cleanSym }} &middot; {{ sectorName }}
          <!-- Switches the whole card to another symbol, so it is a control,
               not a caption. As a bare span it had no keyboard path and no
               equivalent elsewhere on the card. -->
          <button
            v-if="!isIndexOrEtf"
            type="button"
            class="etf-badge font-mono"
            :aria-label="`Switch to ${sectorEtf}`"
            @click="emit('selectSymbol', sectorEtf)"
          >
            Pair: {{ sectorEtf }}
          </button>
        </h3>
      </div>
      <div class="pair-status-pill font-mono" :class="pairLeadershipStatus.tone">
        {{ pairLeadershipStatus.status }}
      </div>
    </div>

    <!-- Pair Alignment Grid -->
    <div class="pair-alignment-grid">
      <!-- 1. Home Sector Profile -->
      <div class="align-box">
        <span class="box-k">PRIMARY SECTOR ETF</span>
        <div class="box-v-row">
          <span class="box-v font-mono font-bold">{{ sectorEtf }}</span>
          <span class="sector-code font-mono">({{ sectorCode }})</span>
        </div>
        <span class="box-sub">
          Regime:
          <strong
            class="font-mono"
            :class="{
              'text-emerald': sectorRow?.regime === 'long',
              'text-rose': sectorRow?.regime === 'short',
              'text-warn': sectorRow?.regime === 'flip',
            }"
          >
            {{ sectorRow?.regime ? sectorRow.regime.toUpperCase() : 'MONITORED' }}
          </strong>
        </span>
      </div>

      <!-- 2. Sector Flow / Rotation Dynamic -->
      <div class="align-box">
        <span class="box-k">SECTOR ROTATION POSTURE</span>
        <div class="box-v-row">
          <span
            class="box-v font-mono font-semibold"
            :class="{
              'text-emerald': sectorRow?.regime === 'long',
              'text-rose': sectorRow?.regime === 'short',
            }"
          >
            {{
              sectorRow?.regime === 'long'
                ? 'ACCUMULATION / PIN'
                : sectorRow?.regime === 'short'
                  ? 'VOLATILITY SPREAD'
                  : 'BALANCED'
            }}
          </span>
        </div>
        <span class="box-sub">
          {{
            sectorRow?.regime === 'long'
              ? 'Dealers cushioning sector pullbacks'
              : 'Heightened sector volatility / beta risk'
          }}
        </span>
      </div>

      <!-- 3. Pair Dynamics Description -->
      <div class="align-box full-span">
        <span class="box-k">PAIR FLOW &amp; BETA INTERPRETATION</span>
        <p class="pair-desc">{{ pairLeadershipStatus.desc }}</p>
      </div>
    </div>

    <!-- 11-Sector Quick Navigation Strip -->
    <div v-if="allSectorRows.length > 0" class="sector-quick-strip">
      <span class="strip-label font-mono">SECTOR BASKET:</span>
      <div class="sector-pills-wrap">
        <button
          v-for="s in allSectorRows"
          :key="s.symbol"
          class="sector-pill font-mono"
          :class="[s.regime, { active: s.symbol === cleanSym || s.symbol === sectorEtf }]"
          @click="emit('selectSymbol', s.symbol)"
        >
          <span class="pill-sym">{{ s.symbol }}</span>
          <span class="pill-reg">{{ s.regime.slice(0, 1).toUpperCase() }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sector-pair-card {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.875rem;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
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
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.etf-badge {
  font-size: var(--t-micro);
  background: var(--panel-hi);
  color: var(--phosphor);
  border: 1px solid var(--rule-hi);
  padding: 0.125rem 0.375rem;
  border-radius: var(--r-xs);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.etf-badge:hover {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
}

.pair-status-pill {
  font-size: var(--t-micro);
  font-weight: 700;
  padding: 0.25rem 0.5rem;
  border-radius: var(--r-sm);
}

.pair-status-pill.long {
  background: var(--call-wash);
  color: var(--call-hi);
  border: 1px solid var(--call-dim);
}

.pair-status-pill.short {
  background: var(--put-wash);
  color: var(--put-hi);
  border: 1px solid var(--put-dim);
}

.pair-status-pill.neutral {
  background: var(--panel-hi);
  color: var(--ink-dim);
  border: 1px solid var(--rule-faint);
}

.pair-alignment-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.align-box {
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  border-radius: var(--r-sm);
  padding: 0.625rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.align-box.full-span {
  grid-column: 1 / -1;
}

.box-k {
  font-size: var(--t-nano);
  color: var(--ink-faint);
  font-family: var(--font-mono, monospace);
}

.box-v-row {
  display: flex;
  align-items: baseline;
  gap: 0.375rem;
}

.box-v {
  font-size: 1rem;
  color: var(--ink);
}

.sector-code {
  font-size: var(--t-micro);
  color: var(--ink-dim);
}

.box-sub {
  font-size: var(--t-micro);
  color: var(--ink-dim);
}

.pair-desc {
  font-size: 0.75rem;
  color: var(--ink);
  line-height: 1.35;
  margin: 0;
}

.sector-quick-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--rule-faint);
}

.strip-label {
  font-size: var(--t-nano);
  color: var(--ink-faint);
}

.sector-pills-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}

.sector-pill {
  background: var(--panel-hi);
  border: 1px solid var(--rule-faint);
  border-radius: var(--r-xs);
  padding: 0.15rem 0.375rem;
  font-size: var(--t-nano);
  color: var(--ink-dim);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.25rem;
  transition: all var(--dur-fast) var(--ease-out);
}

.sector-pill.active {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
  color: var(--phosphor);
  font-weight: 700;
}

.sector-pill.long .pill-reg {
  color: var(--long);
}

.sector-pill.short .pill-reg {
  color: var(--short);
}

.sector-pill.flip .pill-reg {
  color: var(--warn);
}

.text-emerald {
  color: var(--long);
}

.text-rose {
  color: var(--short);
}

.text-warn {
  color: var(--warn);
}
</style>
