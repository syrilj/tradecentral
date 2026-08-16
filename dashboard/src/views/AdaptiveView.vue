<script setup lang="ts">
/**
 * Live Blend — regime-aware multi-stream adaptive ranking.
 *
 * This is the desk-facing answer to “update the signal as the market changes”
 * without continuous model retrain or broker auto-trade:
 *   technical + sector + sentiment + fundamental proxies
 *   → pre-registered regime weights
 *   → soft online reweight when stream performance is supplied
 *   → ordinal composite only (never calibrated p, never capital auth)
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type AdaptiveSignalPayload,
  type AdaptiveSignalRow,
  type StreamHitRates,
} from '@/api'
import { useResource } from '@/composables/useResource'
import { num, signed, shortDate, tone, DASH } from '@/format'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import HelpTip from '@/components/HelpTip.vue'
import LoadingState from '@/components/LoadingState.vue'

const route = useRoute()
const router = useRouter()

const symbol = ref(((route.query.symbol as string) || '').toUpperCase())
const draft = ref(symbol.value)
const limit = ref(40)

const res = useResource<AdaptiveSignalPayload>(
  () =>
    api.adaptiveSignal({
      symbol: symbol.value || undefined,
      limit: limit.value,
    }),
  { intervalMs: 60_000 },
)

watch(
  () => route.query.symbol,
  (s) => {
    const next = typeof s === 'string' ? s.toUpperCase() : ''
    if (next !== symbol.value) {
      symbol.value = next
      draft.value = next
      void res.refresh()
    }
  },
)

function applySymbol(): void {
  const s = draft.value.trim().toUpperCase().replace(/[^A-Z0-9.-]/g, '').slice(0, 10)
  draft.value = s
  symbol.value = s
  void router.replace({ name: 'adaptive', query: s ? { symbol: s } : {} })
  void res.refresh()
}

function clearSymbol(): void {
  draft.value = ''
  symbol.value = ''
  void router.replace({ name: 'adaptive' })
  void res.refresh()
}

const payload = computed(() => res.data.value)
const focus = computed<AdaptiveSignalRow | null>(() => {
  if (payload.value?.signal) return payload.value.signal
  return payload.value?.board?.rows?.[0] ?? null
})
const board = computed(() => payload.value?.board?.rows ?? [])
const coverage = computed(() => payload.value?.board?.coverage ?? null)
const regimeHist = computed(() => {
  const h = payload.value?.board?.regime_histogram ?? {}
  return Object.entries(h)
    .map(([k, v]) => ({ regime: k, n: v }))
    .sort((a, b) => b.n - a.n)
    .slice(0, 8)
})

const hitRates = computed<StreamHitRates | null>(() => payload.value?.stream_hit_rates ?? null)
const hitRows = computed(() => {
  const perf = hitRates.value?.stream_performance ?? {}
  const counts = hitRates.value?.stream_counts ?? {}
  return ['technical', 'sector', 'sentiment', 'fundamental'].map((name) => ({
    name,
    rate: perf[name] ?? null,
    n: counts[name] ?? 0,
  }))
})

function sideTone(side: string): string {
  if (side === 'long') return 'pos'
  if (side === 'short') return 'neg'
  return 'muted'
}

function bandTone(band: string): string {
  if (band === 'strong') return 'pos'
  if (band === 'moderate') return 'warm'
  if (band === 'conflicted') return 'neg'
  return 'muted'
}

function streamEntries(row: AdaptiveSignalRow | null) {
  if (!row?.streams) return []
  return ['technical', 'sector', 'sentiment', 'fundamental'].map((name) => {
    const block = row.streams[name] || { score: null, quality: 'missing' }
    const weight = row.weights?.adapted?.[name] ?? null
    return {
      name,
      score: block.score ?? null,
      quality: block.quality ?? 'missing',
      weight,
      contribution: row.weights?.contributions?.[name] ?? null,
      reasons: (block.reasons || []).slice(0, 3),
    }
  })
}

const focusStreams = computed(() => streamEntries(focus.value))

const weightBars = computed(() => {
  const w = focus.value?.weights?.adapted ?? {}
  const base = focus.value?.weights?.base ?? {}
  return ['technical', 'sector', 'sentiment', 'fundamental'].map((name) => ({
    name,
    adapted: w[name] ?? 0,
    base: base[name] ?? 0,
  }))
})
</script>

<template>
  <div class="adaptive-view">
    <header class="page-head">
      <div>
        <p class="lab kicker">11 · LIVE BLEND</p>
        <h1 class="title">
          Adaptive multi-stream
          <HelpTip
            label="Blend"
            text="Signals recompute from the latest local bars + sector/sentiment context. Weights follow the current vol×trend regime. Optional stream hit-rates can soft-reweight the blend. This is attention ranking only — not a calibrated model probability and never live-capital authorization."
          />
        </h1>
        <p class="sub lab">
          technical · sector · sentiment · fundamental → regime weights → ordinal composite
        </p>
      </div>
      <form class="sym-form" @submit.prevent="applySymbol">
        <input
          v-model="draft"
          class="sym-input fig"
          placeholder="SYMBOL"
          maxlength="10"
          autocomplete="off"
          spellcheck="false"
        />
        <button type="submit" class="btn">Score</button>
        <button v-if="symbol" type="button" class="btn ghost" @click="clearSymbol">Board</button>
      </form>
    </header>

    <LoadingState v-if="res.loading.value && !payload" label="Scoring live streams…" />
    <p v-else-if="res.error.value" class="err lab">{{ res.error.value }}</p>

    <template v-else-if="payload">
      <div class="auth-banner lab">
        decision_authorized={{ payload.decision_authorized }} ·
        live_capital_authorized={{ payload.live_capital_authorized }} ·
        mode={{ payload.mode }} ·
        asof={{ payload.asof ? shortDate(payload.asof) : DASH }}
      </div>

      <div class="grid-top">
        <Panel
          label="Focus composite"
          index="01"
          live
          :meta="focus?.symbol || '—'"
        >
          <template v-if="focus">
            <div class="focus-row">
              <div>
                <p class="sym fig">{{ focus.symbol }}</p>
                <p class="lab meta-line">
                  {{ focus.state }} ·
                  <span :class="sideTone(focus.side)">{{ focus.side }}</span>
                  · band
                  <span :class="bandTone(focus.agreement_band)">{{ focus.agreement_band }}</span>
                </p>
              </div>
              <div class="score-block">
                <p class="lab">composite</p>
                <p class="score fig" :class="tone(focus.composite_score)">
                  {{ focus.composite_score == null ? DASH : signed(focus.composite_score, 3) }}
                </p>
              </div>
            </div>
            <div class="readout-grid">
              <Readout
                label="Vol regime"
                :value="focus.regime?.volatility_regime || DASH"
              />
              <Readout
                label="Trend regime"
                :value="focus.regime?.trend_regime || DASH"
              />
              <Readout
                label="Bear"
                :value="focus.regime?.bear_market == null ? DASH : focus.regime.bear_market ? 'YES' : 'no'"
              />
              <Readout
                label="Adapt mode"
                :value="focus.weights?.adaptation_mode || DASH"
              />
              <Readout
                label="Bar freq"
                :value="focus.bar_freq || DASH"
              />
              <Readout
                label="Bars"
                :value="focus.n_bars != null ? String(focus.n_bars) : DASH"
              />
            </div>
            <p class="caveat lab">{{ focus.caveat }}</p>
          </template>
          <p v-else class="lab muted">No scored symbol yet.</p>
        </Panel>

        <Panel label="Stream stack" index="02" :meta="focus ? `${focus.present_streams?.length || 0} live` : ''">
          <div v-if="focusStreams.length" class="stream-list">
            <div v-for="s in focusStreams" :key="s.name" class="stream-row">
              <div class="stream-head">
                <span class="lab name">{{ s.name }}</span>
                <span class="fig" :class="tone(s.score)">
                  {{ s.score == null ? DASH : signed(s.score, 3) }}
                </span>
                <span class="lab w">w {{ s.weight == null ? DASH : num(s.weight, 2) }}</span>
                <span class="lab q">{{ s.quality }}</span>
              </div>
              <div class="bar-track">
                <div
                  class="bar-fill"
                  :class="tone(s.score)"
                  :style="{
                    width: `${Math.min(100, Math.abs(s.score ?? 0) * 100)}%`,
                    marginLeft: (s.score ?? 0) < 0 ? 'auto' : undefined,
                  }"
                />
              </div>
              <p v-if="s.reasons.length" class="lab reasons">{{ s.reasons.join(' · ') }}</p>
            </div>
          </div>
          <p v-else class="lab muted">Streams unavailable.</p>
        </Panel>

        <Panel label="Regime weight tilt" index="03">
          <div class="weight-list">
            <div v-for="w in weightBars" :key="w.name" class="weight-row">
              <span class="lab name">{{ w.name }}</span>
              <div class="dual">
                <span class="base" :style="{ width: `${w.base * 100}%` }" title="base" />
                <span class="adapt" :style="{ width: `${w.adapted * 100}%` }" title="adapted" />
              </div>
              <span class="fig nums">
                {{ num(w.base, 2) }}→{{ num(w.adapted, 2) }}
              </span>
            </div>
          </div>
          <p class="lab legend">thin = regime base · solid = adapted</p>
        </Panel>
      </div>

      <Panel
        v-if="!symbol"
        label="Attention board"
        index="04"
        live
        :meta="coverage ? `${coverage.scored || 0}/${coverage.requested || 0} scored` : ''"
        flush
      >
        <div class="table-wrap">
          <table class="board">
            <thead>
              <tr>
                <th>#</th>
                <th>Sym</th>
                <th>Side</th>
                <th>Composite</th>
                <th>Band</th>
                <th>Regime</th>
                <th>Tech</th>
                <th>Sector</th>
                <th>Sent</th>
                <th>Fund</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in board"
                :key="row.symbol"
                class="clickable"
                @click="draft = row.symbol; applySymbol()"
              >
                <td class="fig">{{ row.attention_rank ?? DASH }}</td>
                <td class="fig sym">{{ row.symbol }}</td>
                <td :class="sideTone(row.side)">{{ row.side }}</td>
                <td class="fig" :class="tone(row.composite_score)">
                  {{ row.composite_score == null ? DASH : signed(row.composite_score, 3) }}
                </td>
                <td :class="bandTone(row.agreement_band)">{{ row.agreement_band }}</td>
                <td class="lab">
                  {{ row.regime?.volatility_regime || '?' }}/{{ row.regime?.trend_regime || '?' }}
                </td>
                <td class="fig" :class="tone(row.stream_scores?.technical)">
                  {{ row.stream_scores?.technical == null ? DASH : signed(row.stream_scores.technical, 2) }}
                </td>
                <td class="fig" :class="tone(row.stream_scores?.sector)">
                  {{ row.stream_scores?.sector == null ? DASH : signed(row.stream_scores.sector, 2) }}
                </td>
                <td class="fig" :class="tone(row.stream_scores?.sentiment)">
                  {{ row.stream_scores?.sentiment == null ? DASH : signed(row.stream_scores.sentiment, 2) }}
                </td>
                <td class="fig" :class="tone(row.stream_scores?.fundamental)">
                  {{ row.stream_scores?.fundamental == null ? DASH : signed(row.stream_scores.fundamental, 2) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!board.length" class="lab empty pad">No board rows — check local daily bars.</p>
      </Panel>

      <div class="grid-top">
        <Panel
          label="Shadow stream hit-rates"
          index="05"
          live
          :meta="
            hitRates
              ? `${hitRates.events_scored ?? 0}/${hitRates.events_considered ?? 0} events`
              : ''
          "
        >
          <p class="lab legend">
            Closed-loop soft tilt from realized shadow outcomes (point-in-time
            stream reconstruction). Needs ≥{{ hitRates?.min_events ?? 5 }} signed
            calls per stream before a rate is used.
          </p>
          <div class="hit-list">
            <div v-for="h in hitRows" :key="h.name" class="hit-row">
              <span class="lab name">{{ h.name }}</span>
              <div class="hit-track">
                <span
                  class="hit-fill"
                  :style="{ width: h.rate == null ? '0%' : `${h.rate * 100}%` }"
                />
              </div>
              <span class="fig">
                {{ h.rate == null ? DASH : num(h.rate, 2) }}
                <span class="lab muted"> n={{ h.n }}</span>
              </span>
            </div>
          </div>
          <p v-if="hitRates?.caveat" class="caveat lab">{{ hitRates.caveat }}</p>
          <p v-if="hitRates?.error" class="err lab">{{ hitRates.error }}</p>
        </Panel>

        <Panel
          v-if="regimeHist.length"
          label="Board regime mix"
          index="06"
          :meta="`${regimeHist.length} buckets`"
        >
          <div class="hist">
            <div v-for="r in regimeHist" :key="r.regime" class="hist-row">
              <span class="lab">{{ r.regime }}</span>
              <div class="hist-bar">
                <span :style="{ width: `${Math.min(100, r.n * 8)}%` }" />
              </div>
              <span class="fig">{{ r.n }}</span>
            </div>
          </div>
        </Panel>
      </div>
    </template>
  </div>
</template>

<style scoped>
.adaptive-view {
  display: flex;
  flex-direction: column;
  gap: var(--s5);
  padding-bottom: var(--s7);
}
.page-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--s4);
  align-items: flex-end;
}
.kicker { color: var(--ink-faint); letter-spacing: 0.12em; margin: 0 0 var(--s1); }
.title {
  margin: 0;
  font-size: var(--t-display);
  font-weight: 550;
  display: flex;
  align-items: center;
  gap: var(--s2);
}
.sub { margin: var(--s1) 0 0; color: var(--ink-dim); }
.sym-form { display: flex; gap: var(--s2); align-items: center; }
.sym-input {
  width: 7.5rem;
  background: var(--panel-hi);
  border: var(--hair) solid var(--rule);
  border-radius: 2px;
  color: inherit;
  padding: var(--s2) var(--s3);
  font-size: var(--t-body);
  letter-spacing: 0.06em;
}
.btn {
  background: var(--phosphor);
  color: var(--void);
  border: 0;
  border-radius: 2px;
  padding: var(--s2) var(--s3);
  font: inherit;
  font-size: var(--t-tiny);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  cursor: pointer;
}
.btn.ghost {
  background: transparent;
  color: var(--ink);
  border: var(--hair) solid var(--rule);
}
.btn.ghost:hover { background: var(--panel-hi); }
.auth-banner {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule);
  padding: var(--s2) var(--s3);
}
.grid-top {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--s4);
}
.focus-row {
  display: flex;
  justify-content: space-between;
  gap: var(--s4);
  margin-bottom: var(--s3);
}
.sym { font-size: var(--t-fig); margin: 0; letter-spacing: 0.04em; }
.meta-line { margin: var(--s1) 0 0; color: var(--ink-dim); }
.score-block { text-align: right; }
.score { font-size: var(--t-fig); margin: 0; }
.readout-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s2);
  margin-top: var(--s2);
}
.caveat { margin: var(--s3) 0 0; color: var(--ink-faint); font-size: var(--t-micro); line-height: 1.4; }
.stream-list { display: flex; flex-direction: column; gap: var(--s3); }
.stream-head {
  display: grid;
  grid-template-columns: 1fr auto auto auto;
  gap: var(--s2);
  align-items: baseline;
}
.stream-head .name { text-transform: uppercase; letter-spacing: 0.08em; font-size: var(--t-micro); }
.stream-head .w, .stream-head .q { color: var(--ink-faint); font-size: var(--t-micro); }
.bar-track {
  height: var(--s1);
  background: color-mix(in srgb, var(--rule) 70%, transparent);
  margin-top: var(--s1);
  display: flex;
}
.bar-fill { height: 100%; background: currentColor; min-width: 2px; border-radius: 1px; }
.reasons { margin: var(--s1) 0 0; color: var(--ink-ghost); font-size: var(--t-micro); }
.weight-list { display: flex; flex-direction: column; gap: var(--s2); }
.weight-row {
  display: grid;
  grid-template-columns: 5.5rem 1fr auto;
  gap: var(--s2);
  align-items: center;
}
.dual {
  position: relative;
  height: 10px;
  background: color-mix(in srgb, var(--rule) 50%, transparent);
}
.dual .base, .dual .adapt {
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  border-radius: 1px;
}
.dual .base { background: color-mix(in srgb, var(--ink-dim) 25%, transparent); }
.dual .adapt { background: var(--phosphor); opacity: 0.85; }
.nums { font-size: var(--t-tiny); color: var(--ink-soft); }
.legend { margin: var(--s3) 0 0; color: var(--ink-ghost); font-size: var(--t-micro); }
.table-wrap { overflow-x: auto; }
.board {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-small);
}
.board th {
  text-align: left;
  padding: var(--s3) var(--s4);
  color: var(--ink-dim);
  border-bottom: var(--hair) solid var(--rule);
  position: sticky;
  top: 0;
  background: var(--panel-hi);
  font-weight: 700;
  z-index: 1;
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  white-space: nowrap;
}
.board td {
  padding: var(--s2) var(--s4);
  border-bottom: var(--hair) solid var(--rule-faint);
  color: var(--ink);
  text-align: left;
  white-space: nowrap;
  vertical-align: middle;
}
.board tr.clickable { cursor: pointer; }
.board tr.clickable:hover { background: var(--panel-hi); }
.board .sym { letter-spacing: 0.04em; }
.pad { padding: var(--s4); }
.empty { color: var(--ink-faint); }
.hist { display: flex; flex-direction: column; gap: var(--s2); }
.hist-row {
  display: grid;
  grid-template-columns: 7rem 1fr 2rem;
  gap: var(--s2);
  align-items: center;
}
.hist-bar {
  height: 6px;
  background: color-mix(in srgb, var(--rule) 60%, transparent);
}
.hist-bar span {
  display: block;
  height: 100%;
  background: var(--phosphor);
  border-radius: 1px;
}
.hit-list { display: flex; flex-direction: column; gap: var(--s2); margin-top: var(--s2); }
.hit-row {
  display: grid;
  grid-template-columns: 5.5rem 1fr auto;
  gap: var(--s2);
  align-items: center;
}
.hit-track {
  height: 6px;
  background: color-mix(in srgb, var(--rule) 60%, transparent);
}
.hit-fill {
  display: block;
  height: 100%;
  background: var(--phosphor);
  min-width: 0;
  border-radius: 1px;
}
.err { color: var(--short); }
.pos { color: var(--long); }
.neg { color: var(--short); }
.warm { color: var(--warn); }
.muted { color: var(--ink-faint); }
</style>
