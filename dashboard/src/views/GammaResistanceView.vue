<script setup lang="ts">
/**
 * /gamma — call resistance, absolute gamma, zero gamma, and nearby support
 * before a trade. Figures come from GET /api/gamma/resistance. A missing
 * input stays missing.
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import {
  HORIZONS,
  cleanSymbol,
  ladderRows,
  normalizeMaxDte,
  readCards,
  reasonCopy,
  screenPhase,
  statusNotes,
  type HorizonDte,
} from '@/gammaResistance'
import { shortDate, usd } from '@/format'
import Panel from '@/components/Panel.vue'
import LoadingState from '@/components/LoadingState.vue'
import GammaReadCard from '@/components/GammaReadCard.vue'
import GammaStrikeLadder from '@/components/GammaStrikeLadder.vue'
import { useResource } from '@/composables/useResource'

const route = useRoute()
const router = useRouter()

const symbol = ref(cleanSymbol(route.query.symbol))
const symbolInput = ref(symbol.value)
const maxDte = ref<HorizonDte>(normalizeMaxDte(route.query.max_dte))

function pushQuery(nextSymbol: string, nextDte: HorizonDte): void {
  void router.replace({
    name: 'gamma',
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
  pushQuery(clean, maxDte.value)
}

function setHorizon(dte: HorizonDte): void {
  if (dte === maxDte.value) return
  maxDte.value = dte
  pushQuery(symbol.value, dte)
}

watch(
  () => route.query.symbol,
  (next) => {
    const clean = cleanSymbol(next, '')
    if (clean && clean !== symbol.value) {
      symbol.value = clean
      symbolInput.value = clean
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

const res = useResource(() => api.gammaResistance(symbol.value, maxDte.value), {
  intervalMs: 60_000,
  immediate: true,
})
watch([symbol, maxDte], () => void res.refresh({ clear: true }))

const payload = computed(() => res.data.value)
const phase = computed(() =>
  screenPhase({
    loading: res.loading.value,
    error: res.error.value,
    payload: payload.value,
  }),
)
const notes = computed(() => statusNotes({ error: res.error.value, payload: payload.value }))
const cards = computed(() => (payload.value ? readCards(payload.value) : []))
const ladder = computed(() => {
  const current = payload.value
  if (!current) return []
  return ladderRows(current.by_strike, current.spot, {
    call: current.call_resistance?.level ?? null,
    zero: current.zero_gamma,
    support: current.nearby_support?.level ?? null,
  })
})
const panelMeta = computed(() => {
  const current = payload.value
  if (!current) return ''
  const bits: string[] = []
  if (current.spot != null) bits.push(`spot ${usd(current.spot)}`)
  if (current.asof) bits.push(shortDate(current.asof.slice(0, 10)))
  const measured = current.quality?.contracts_measured
  if (measured != null) bits.push(`${measured} contracts`)
  return bits.join(' · ')
})
const emptyReason = computed(() => reasonCopy(payload.value?.reason))
</script>

<template>
  <div class="gamma-view">
    <form class="controls" @submit.prevent="loadSymbol(symbolInput)">
      <label class="symbol-ctl">
        <span class="label">Symbol</span>
        <span class="sym-row">
          <input
            v-model="symbolInput"
            class="input fig"
            data-testid="gamma-symbol"
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
          :data-testid="`gamma-horizon-${horizon.dte}`"
          @click="setHorizon(horizon.dte)"
        >
          {{ horizon.label }}
        </button>
      </div>
      <p class="mechanic-caption">
        Call dollar-gamma is positive and put dollar-gamma is negative. Absolute gamma is the
        unsigned sum for a 1% move. Zero gamma is where that net, repriced off implied vol, crosses
        zero. Nearby support is the closest material put shelf inside 8% of spot — a heavier wall
        further away is named, not relabeled as support.
      </p>
    </form>

    <Panel label="Before the trade" index="01" :meta="panelMeta">
      <LoadingState v-if="phase === 'loading'" label="Pricing gamma" />

      <div v-else-if="phase === 'error'" class="unavailable" role="alert" data-testid="gamma-error">
        <p class="unavailable-title">Chain unavailable</p>
        <p>{{ res.error }}</p>
      </div>

      <div v-else-if="phase === 'empty'" class="unavailable" data-testid="gamma-empty">
        <p class="unavailable-title">Nothing measured</p>
        <p>{{ emptyReason }}</p>
        <p>Missing inputs stay blank. This is not a flat gamma book.</p>
        <p v-for="note in notes" :key="note.text" class="note" :class="note.kind">
          {{ note.text }}
        </p>
      </div>

      <template v-else>
        <p
          v-for="note in notes"
          :key="note.text"
          class="banner"
          :class="note.kind"
          :data-testid="note.kind === 'stale' ? 'gamma-stale' : 'gamma-refresh-error'"
        >
          {{ note.text }}
        </p>
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
            :test-id="`gamma-${card.id}`"
          />
        </div>
        <GammaStrikeLadder
          :rows="ladder"
          :spot="payload?.spot ?? null"
          :call-level="payload?.call_resistance?.level ?? null"
          :support-level="payload?.nearby_support?.level ?? null"
        />
      </template>
    </Panel>
  </div>
</template>

<style scoped>
.gamma-view {
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
.horizons {
  display: flex;
  gap: var(--s2);
}
.input,
.btn {
  min-height: var(--density-control-h);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--panel-hi);
  color: var(--ink);
  padding: 0 var(--s3);
}
.btn {
  cursor: pointer;
  color: var(--ink-soft);
}
.btn.on {
  color: var(--ink);
  border-color: var(--rule-hi);
}
.btn:focus-visible,
.input:focus-visible {
  outline: var(--focus-ring);
  outline-offset: var(--focus-ring-offset);
}
.mechanic-caption {
  flex: 1 1 280px;
  margin: 0;
  font-size: var(--t-tiny);
  color: var(--ink-dim);
  line-height: 1.5;
}
.unavailable,
.banner {
  padding: var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  color: var(--ink-dim);
  background: var(--panel-hi);
}
.unavailable-title {
  margin: 0 0 var(--s2);
  color: var(--ink);
}
.unavailable p,
.banner {
  margin: 0 0 var(--s2);
  line-height: 1.45;
}
.banner.stale {
  border-color: color-mix(in srgb, var(--warn) 35%, var(--rule));
}
.banner.error {
  border-color: color-mix(in srgb, var(--put) 35%, var(--rule));
}
.reads {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s3);
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
}
</style>
