<script setup lang="ts">
/**
 * /live — one options decision. The four gamma reads, the levels to watch,
 * and whether the chart agrees, runs opposite, or is stretched. The other
 * screens stay where they are. This view does not route an order.
 */
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import GammaExposureMap from '@/components/GammaExposureMap.vue'
import GammaReadCard from '@/components/GammaReadCard.vue'
import LoadingState from '@/components/LoadingState.vue'
import Panel from '@/components/Panel.vue'
import { useResource } from '@/composables/useResource'
import { shortDate, usd } from '@/format'
import {
  HORIZONS,
  cleanSymbol,
  normalizeMaxDte,
  readCards,
  reasonCopy,
  screenPhase,
  statusNotes,
  type HorizonDte,
} from '@/gammaResistance'
import {
  positiveLevel,
  priceGeometry,
  profileRows,
  stanceWord,
  type ChartStance,
} from '@/liveOptions'

const route = useRoute()
const router = useRouter()

const symbol = ref(cleanSymbol(route.query.symbol))
const symbolInput = ref(symbol.value)
const maxDte = ref<HorizonDte>(normalizeMaxDte(route.query.max_dte))
const focusStrike = ref<number | null>(null)

function pushQuery(nextSymbol: string, nextDte: HorizonDte): void {
  void router.replace({
    name: 'live-options',
    query: { symbol: nextSymbol, max_dte: String(nextDte) },
  })
}

function loadSymbol(raw: string): void {
  const clean = cleanSymbol(raw, '')
  if (!clean || clean === symbol.value) {
    symbolInput.value = symbol.value
    return
  }
  symbol.value = clean
  symbolInput.value = clean
  focusStrike.value = null
  pushQuery(clean, maxDte.value)
}

function setHorizon(dte: HorizonDte): void {
  if (dte === maxDte.value) return
  maxDte.value = dte
  focusStrike.value = null
  pushQuery(symbol.value, dte)
}

watch(
  () => route.query.symbol,
  (next) => {
    const clean = cleanSymbol(next, '')
    if (clean && clean !== symbol.value) {
      symbol.value = clean
      symbolInput.value = clean
      focusStrike.value = null
    }
  },
)
watch(
  () => route.query.max_dte,
  (next) => {
    const dte = normalizeMaxDte(next)
    if (dte !== maxDte.value) maxDte.value = dte
  },
)

const res = useResource(() => api.liveOptions(symbol.value, maxDte.value), {
  intervalMs: 60_000,
  immediate: true,
})
watch([symbol, maxDte], () => void res.refresh({ clear: true }))

const payload = computed(() => res.data.value)
const gamma = computed(() => payload.value?.gamma ?? null)
const phase = computed(() =>
  screenPhase({
    loading: res.loading.value,
    error: res.error.value,
    payload: gamma.value,
  }),
)
const notes = computed(() => statusNotes({ error: res.error.value, payload: gamma.value }))
const cards = computed(() => (gamma.value ? readCards(gamma.value) : []))
const levels = computed(() => payload.value?.levels ?? [])
const chart = computed(() => payload.value?.chart ?? null)
const stance = computed<ChartStance | null>(() => chart.value?.stance ?? null)
const profile = computed(() => (gamma.value ? profileRows(gamma.value.by_strike) : []))
const spot = computed(() => positiveLevel(gamma.value?.spot))
const callLevel = computed(() => positiveLevel(gamma.value?.call_resistance?.level))
const supportLevel = computed(() => positiveLevel(gamma.value?.nearby_support?.level))
const putWallLevel = computed(
  () => positiveLevel(gamma.value?.put_wall?.level) ?? supportLevel.value,
)
const zeroLevel = computed(() => positiveLevel(gamma.value?.zero_gamma))
const geometry = computed(() => {
  const closes = chart.value?.closes ?? []
  return priceGeometry(
    closes.map((row) => row.close),
    levels.value.map((level) => level.level),
    640,
    88,
  )
})
const panelMeta = computed(() => {
  const current = gamma.value
  if (!current) return ''
  const bits: string[] = []
  if (spot.value != null) bits.push(`spot ${usd(spot.value)}`)
  if (current.asof) bits.push(shortDate(current.asof.slice(0, 10)))
  return bits.join(' · ')
})
const emptyReason = computed(() => reasonCopy(gamma.value?.reason))

const screens = [
  { name: 'options', label: 'Options' },
  { name: 'vanna', label: 'Vanna' },
  { name: 'chain', label: 'Chain' },
  { name: 'calculator', label: 'Calculator' },
  { name: 'drift', label: 'Drift' },
  { name: 'gamma', label: 'Gamma' },
] as const

function watchLevel(level: number): void {
  focusStrike.value = level
}
</script>

<template>
  <div class="live-view">
    <form class="controls" @submit.prevent="loadSymbol(symbolInput)">
      <label class="symbol-ctl">
        <span class="label">Symbol</span>
        <span class="sym-row">
          <input
            v-model="symbolInput"
            class="input fig"
            data-testid="live-symbol"
            name="symbol"
            autocomplete="off"
            spellcheck="false"
            aria-label="Symbol"
          />
          <button class="btn" type="submit">Load</button>
        </span>
      </label>
      <div class="horizons" role="group" aria-label="Expiry window">
        <button
          v-for="horizon in HORIZONS"
          :key="horizon.dte"
          type="button"
          class="btn"
          :class="{ on: maxDte === horizon.dte }"
          :data-testid="`live-horizon-${horizon.dte}`"
          @click="setHorizon(horizon.dte)"
        >
          {{ horizon.label }}
        </button>
      </div>
      <p class="mechanic-caption">
        Read call resistance, absolute gamma, zero gamma, and nearby support in one pass. The chart
        agrees, runs opposite, or is stretched. Missing inputs stay blank.
      </p>
    </form>

    <Panel label="The decision" index="01" :meta="panelMeta">
      <LoadingState v-if="phase === 'loading'" label="Reading the book" />

      <div v-else-if="phase === 'error'" class="unavailable" role="alert" data-testid="live-error">
        <p class="unavailable-title">Chain unavailable</p>
        <p>{{ res.error }}</p>
        <p>Missing inputs stay blank. This is not a flat gamma book.</p>
      </div>

      <div v-else-if="phase === 'empty'" class="unavailable" data-testid="live-empty">
        <p class="unavailable-title">Nothing measured</p>
        <p>{{ emptyReason }}</p>
        <p>Missing inputs stay blank. This is not a flat gamma book.</p>
      </div>

      <template v-else>
        <p
          v-for="note in notes"
          :key="note.text"
          class="banner"
          :class="note.kind"
          :data-testid="note.kind === 'stale' ? 'live-stale' : 'live-refresh-error'"
        >
          {{ note.text }}
        </p>

        <section
          class="stance"
          :data-stance="stance ?? 'missing'"
          data-testid="live-stance"
          aria-live="polite"
        >
          <p class="stance-word">{{ stanceWord(stance) }}</p>
          <p class="stance-sentence">{{ chart?.sentence }}</p>
        </section>

        <div class="reads">
          <GammaReadCard
            v-for="card in cards"
            :key="card.id"
            :label="card.label"
            :kicker="card.kicker"
            :value="card.value"
            :sub="card.sub"
            :note="card.note"
            :missing="card.missing"
            :missing-reason="card.missingReason"
            :tone="card.tone"
            :test-id="`live-${card.id}`"
          />
        </div>

        <section class="levels" data-testid="live-levels" aria-label="Levels to watch">
          <h2 class="section-label">Levels to watch</h2>
          <p v-if="!levels.length" class="quiet">No level to watch.</p>
          <div v-else class="level-row">
            <button
              v-for="level in levels"
              :key="level.role"
              type="button"
              class="level"
              :data-testid="`live-level-${level.role}`"
              :class="{ on: focusStrike === level.level }"
              @click="watchLevel(level.level)"
            >
              <span class="kicker">{{ level.label }}</span>
              <span class="fig level-px">{{ usd(level.level) }}</span>
            </button>
            <p v-if="spot != null" class="spot fig">Spot {{ usd(spot) }}</p>
          </div>
        </section>

        <section class="chart-block" aria-label="Price chart">
          <h2 class="section-label">Chart</h2>
          <svg
            v-if="geometry"
            class="chart"
            data-testid="live-chart"
            viewBox="0 0 640 88"
            role="img"
            :aria-label="chart?.sentence"
          >
            <line
              v-for="guide in geometry.guides"
              :key="guide.level"
              x1="8"
              x2="632"
              :y1="guide.y"
              :y2="guide.y"
              class="guide"
            />
            <path :d="geometry.line" class="path" />
          </svg>
          <p v-else class="quiet" data-testid="live-chart-missing">No local price chart.</p>
        </section>

        <section class="profile" data-testid="live-profile" aria-label="Gamma profile">
          <h2 class="section-label">Profile</h2>
          <p class="quiet drag-hint">Drag across the profile. The read follows the pointer.</p>
          <div v-if="profile.length && spot != null" class="profile-frame">
            <GammaExposureMap
              :rows="profile"
              :spot="spot"
              :call-wall="callLevel"
              :put-wall="putWallLevel"
              :gamma-flip="zeroLevel"
              :focus-strike="focusStrike"
              @update:focus-strike="focusStrike = $event"
            />
          </div>
          <p v-else class="quiet" data-testid="live-profile-missing">No strike gamma to draw.</p>
        </section>

        <nav class="screens" aria-label="Full screens">
          <RouterLink
            v-for="screen in screens"
            :key="screen.name"
            class="screen-link"
            :to="{ name: screen.name, query: { symbol } }"
          >
            {{ screen.label }}
          </RouterLink>
        </nav>
        <p class="quiet limit">This read does not route an order.</p>
      </template>
    </Panel>
  </div>
</template>

<style scoped>
.live-view {
  display: block;
}
.controls {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s4);
  align-items: flex-end;
  margin-bottom: var(--s4);
}
.symbol-ctl .sym-row,
.horizons,
.level-row,
.screens {
  display: flex;
  gap: var(--s2);
  flex-wrap: wrap;
  align-items: center;
}
.input,
.btn,
.level,
.screen-link {
  min-height: var(--density-control-h);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--panel-hi);
  color: var(--ink-soft);
}
.input,
.btn,
.level {
  padding: 0 var(--s3);
}
.btn,
.level,
.screen-link {
  cursor: pointer;
  transition:
    transform 140ms var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}
.btn:active,
.level:active {
  transform: scale(0.97);
}
.btn.on,
.level.on {
  color: var(--ink);
  border-color: var(--rule-hi);
}
.btn:focus-visible,
.input:focus-visible,
.level:focus-visible,
.screen-link:focus-visible {
  outline: var(--focus-ring);
  outline-offset: var(--focus-ring-offset);
}
.mechanic-caption,
.quiet {
  margin: 0;
  font-size: var(--t-tiny);
  color: var(--ink-dim);
  line-height: 1.5;
}
.mechanic-caption {
  flex: 1 1 280px;
}
.unavailable,
.banner,
.stance {
  padding: var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  background: var(--panel-hi);
}
.unavailable-title,
.stance-word,
.section-label {
  margin: 0;
  color: var(--ink);
}
.stance {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s3);
  align-items: baseline;
  margin-bottom: var(--s4);
}
.stance-word {
  font-size: var(--t-title, 1.6rem);
  line-height: 1.1;
  transition: color var(--dur-fast) var(--ease-out);
}
.stance[data-stance='agrees'] .stance-word {
  color: var(--call);
}
.stance[data-stance='opposite'] .stance-word {
  color: var(--put);
}
.stance[data-stance='stretched'] .stance-word {
  color: var(--warn);
}
.stance[data-stance='missing'] .stance-word {
  color: var(--ink-dim);
}
.stance-sentence {
  margin: 0;
  color: var(--ink-soft);
}
.reads {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s3);
  margin-bottom: var(--s4);
}
.levels,
.chart-block,
.profile {
  margin-top: var(--s4);
}
.section-label {
  margin-bottom: var(--s2);
  font-size: var(--t-body);
  font-weight: 560;
}
.level {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-width: 7.5rem;
  padding: var(--s2) var(--s3);
  text-align: left;
}
.kicker {
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  color: var(--ink-dim);
  text-transform: uppercase;
}
.level-px {
  color: var(--ink);
  font-size: var(--t-body);
}
.spot {
  margin: 0;
  color: var(--ink-soft);
}
.chart {
  display: block;
  width: 100%;
  height: 88px;
  background: var(--panel);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}
.guide {
  stroke: var(--rule-hi);
  stroke-width: 1;
}
.path {
  fill: none;
  stroke: var(--ink);
  stroke-width: 1.5;
}
.profile-frame {
  height: 440px;
}
.drag-hint {
  margin-bottom: var(--s2);
}
.screen-link {
  display: inline-flex;
  align-items: center;
  padding: 0 var(--s3);
  text-decoration: none;
}
.limit {
  margin-top: var(--s3);
}
.banner.stale {
  border-color: color-mix(in srgb, var(--warn) 35%, var(--rule));
}
.banner.error {
  border-color: color-mix(in srgb, var(--put) 35%, var(--rule));
}
@media (hover: hover) and (pointer: fine) {
  .btn:hover,
  .level:hover,
  .screen-link:hover {
    border-color: var(--rule-hi);
    color: var(--ink);
  }
}
@media (prefers-reduced-motion: reduce) {
  .btn:active,
  .level:active {
    transform: none;
  }
}
@media (max-width: 1100px) {
  .reads {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 640px) {
  .reads {
    grid-template-columns: 1fr;
  }
  .profile-frame {
    height: 520px;
  }
}
</style>
