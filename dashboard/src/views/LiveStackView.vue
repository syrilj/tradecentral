<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type ConfluenceCluster, type OptionsIntelligence, type OptionsMode } from '@/api'
import { useResource } from '@/composables/useResource'
import { compact, num, signedPct } from '@/format'
import Panel from '@/components/Panel.vue'
import LoadingState from '@/components/LoadingState.vue'
import GammaExposureMap from '@/components/GammaExposureMap.vue'
import ThetaVannaChart from '@/components/ThetaVannaChart.vue'
import IvSurfaceChart from '@/components/IvSurfaceChart.vue'
import VolumeProfileChart from '@/components/VolumeProfileChart.vue'

/**
 * LIVE STACK — one underlier, every lens at once.
 *
 * GEX walls name the structure. Charm and theta show how delta decays into
 * expiration. Vanna shows how that delta shifts with volatility. The volume
 * profile shows where real trading activity thinned out. IV walls show where
 * the options market prices the most uncertainty. Each lens alone tells a
 * piece; stacked on one tape they become decision support:
 *
 *   · VERDICT strip — plain-language reads ("who's leading", "what's pinned")
 *   · CONFLUENCE map — levels named by ≥2 independent lenses
 *   · One row per lens, same strike axis where it applies
 *
 * Decision support only: this surface reports what the data says. It never
 * places or routes an order, and no panel is an authorization.
 */

const router = useRouter()
const route = useRoute()

const REFRESH_MS = 30_000

function readSymbol(): string {
  const raw = route.query.symbol
  const value = Array.isArray(raw) ? raw[0] : raw
  return (
    String(value || 'SPY')
      .trim()
      .toUpperCase()
      .replace(/[^A-Z0-9.-]/g, '')
      .slice(0, 10) || 'SPY'
  )
}

const symbolInput = ref(readSymbol())
const symbol = ref(readSymbol())
const mode = ref<OptionsMode>('live')

const optionsRes = useResource<OptionsIntelligence>(
  () => api.options({ symbol: symbol.value, mode: mode.value, range: '5d', expiry: 'all' }),
  { intervalMs: REFRESH_MS },
)

watch(symbol, () => {
  void optionsRes.refresh({ clear: true })
})

watch(
  () => route.query.symbol,
  (val) => {
    const next = Array.isArray(val) ? val[0] : val
    if (typeof next === 'string' && next && next.toUpperCase() !== symbol.value) {
      symbol.value = next.toUpperCase()
      symbolInput.value = next.toUpperCase()
    }
  },
)

function applySymbol(): void {
  const clean = symbolInput.value
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
    .slice(0, 10)
  if (!clean || clean === symbol.value) return
  symbol.value = clean
  void router.replace({ name: 'livestack', query: { ...route.query, symbol: clean } })
}

function onSymbolKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter') {
    e.preventDefault()
    applySymbol()
  }
}

/* ---- payload slices ---------------------------------------------------- */
const payload = computed(() => optionsRes.data.value)
/** Backend returns `{ error }` payloads with 200/404 for unavailable chains. */
const payloadError = computed(() => {
  const raw: unknown = payload.value
  if (raw && typeof raw === 'object' && 'error' in raw) {
    return typeof (raw as { error: unknown }).error === 'string'
      ? (raw as { error: string }).error
      : 'Options payload unavailable.'
  }
  return null
})
const summary = computed(() => payload.value?.summary)
const stack = computed(() => payload.value?.stacked_signals)
const spot = computed(() => summary.value?.spot ?? null)
const callWall = computed(() => summary.value?.call_wall ?? null)
const putWall = computed(() => summary.value?.put_wall ?? null)
const gammaFlip = computed(() => summary.value?.gamma_flip ?? null)
const netGex = computed(() => summary.value?.total_gex_m ?? null)
const gexRegime = computed(() => summary.value?.regime ?? 'neutral')
const charmSummary = computed(() => payload.value?.charm_summary)
const pressure = computed(() => payload.value?.pressure)
const thetaRows = computed(() => stack.value?.theta_by_strike ?? [])
const thetaSummary = computed(() => stack.value?.theta_summary)
const vannaSummary = computed(() => stack.value?.vanna_summary)
const ivSurface = computed(() => stack.value?.iv_surface ?? [])
const ivSummary = computed(() => stack.value?.iv_summary ?? null)
const vpBins = computed(() => stack.value?.volume_profile ?? [])
const vpSummary = computed(() => stack.value?.volume_profile_summary ?? null)
const confluence = computed(() => stack.value?.confluence ?? [])
const gexMeasurable = computed(() => payload.value?.quality?.gex_measurable === true)
const priceSeries = computed(() => payload.value?.price_series ?? [])

const loading = computed(() => optionsRes.loading.value && !payload.value)
const error = computed(() => optionsRes.error.value)

const dataModeBadge = computed(() => {
  if (loading.value) return 'SYNC'
  if (error.value) return 'FAULT'
  const resolved = payload.value?.mode_resolved
  if (resolved === 'live') return 'LIVE'
  if (resolved === 'history_fallback') return 'DELAYED'
  if (resolved === 'history') return 'HISTORY'
  return 'NO DATA'
})

/* ---- verdict strip: what each lens says, in words ----------------------- */
interface Verdict {
  key: string
  lens: string
  headline: string
  detail: string
  tone: 'pos' | 'neg' | 'neutral' | 'missing'
}

function pctFromSpot(level: number | null | undefined): string {
  if (level == null || spot.value == null || !spot.value) return ''
  const rel = ((level - spot.value) / spot.value) * 100
  return ` ${signedPct(rel, 1)} from spot`
}

const gammaVerdict = computed<Verdict>(() => {
  if (!gexMeasurable.value) {
    return {
      key: 'gamma',
      lens: 'GAMMA',
      headline: 'UNMEASURED',
      detail: 'No open-interest snapshot behind these numbers — structure cannot be read.',
      tone: 'missing',
    }
  }
  const regime = gexRegime.value
  if (regime === 'positive') {
    return {
      key: 'gamma',
      lens: 'GAMMA',
      headline: 'DEALERS LONG · MEAN REVERSION',
      detail: `Net dealer gamma +$${compact(netGex.value)}M. Hedging compresses price between the put wall (${num(putWall.value, 0)}) and call wall (${num(callWall.value, 0)}). Breakouts tend to fail inside this band.`,
      tone: 'neutral',
    }
  }
  if (regime === 'negative') {
    return {
      key: 'gamma',
      lens: 'GAMMA',
      headline: 'DEALERS SHORT · TREND FUEL',
      detail: `Net dealer gamma −$${compact(Math.abs(netGex.value ?? 0))}M. Hedges chase price — moves accelerate toward the flip at ${num(gammaFlip.value, 0)}.`,
      tone: 'neg',
    }
  }
  return {
    key: 'gamma',
    lens: 'GAMMA',
    headline: 'FLAT',
    detail: 'No net gamma structure measured.',
    tone: 'neutral',
  }
})

const charmThetaVerdict = computed<Verdict>(() => {
  const charm = charmSummary.value?.net_charm_flow
  const theta = thetaSummary.value?.net_theta_flow
  if (charm == null && theta == null) {
    return {
      key: 'decay',
      lens: 'DECAY',
      headline: 'NO INPUTS',
      detail: 'Charm/theta need dated IV + open interest; none usable in this chain.',
      tone: 'missing',
    }
  }
  const pressureWord =
    charm != null
      ? charm > 0
        ? 'dealers sell underlying as deltas decay — selling pressure builds'
        : charm < 0
          ? 'dealers buy underlying back as deltas decay — buying pressure builds'
          : 'delta decay is balanced across sides'
      : 'charm unavailable'
  const decaySide = thetaSummary.value?.decay_side
  const decayLine =
    theta != null && decaySide && decaySide !== 'balanced'
      ? `${decaySide} carry the fastest bleed (${compact(Math.abs(theta))} pts/day net)`
      : theta != null
        ? 'decay spread evenly across strikes'
        : ''
  return {
    key: 'decay',
    lens: 'DECAY',
    headline:
      charm == null
        ? 'THETA ONLY'
        : charm > 0
          ? 'CHARM → SELLING'
          : charm < 0
            ? 'CHARM → BUYING'
            : 'BALANCED',
    detail: [pressureWord, decayLine].filter(Boolean).join(' · ') + '.',
    tone: charm == null ? 'neutral' : charm > 0 ? 'neg' : charm < 0 ? 'pos' : 'neutral',
  }
})

const vannaVerdict = computed<Verdict>(() => {
  const regime = vannaSummary.value?.regime
  const net = vannaSummary.value?.net_vanna_flow
  if (regime == null || net == null) {
    return {
      key: 'vanna',
      lens: 'VANNA',
      headline: 'NO INPUTS',
      detail: 'Vanna needs dated IV + OI; nothing measurable.',
      tone: 'missing',
    }
  }
  if (regime === 'iv_up_supportive') {
    return {
      key: 'vanna',
      lens: 'VANNA',
      headline: 'VOL UP = SUPPORT',
      detail: 'Rising IV adds dealer delta here — dealers buy weakness, which cushions vol spikes.',
      tone: 'pos',
    }
  }
  if (regime === 'iv_up_pressuring') {
    return {
      key: 'vanna',
      lens: 'VANNA',
      headline: 'VOL UP = PRESSURE',
      detail:
        'Rising IV strips dealer delta here — dealers sell into strength; a vol spike can feed itself.',
      tone: 'neg',
    }
  }
  return {
    key: 'vanna',
    lens: 'VANNA',
    headline: 'NEUTRAL',
    detail: 'Delta sensitivity to IV is balanced.',
    tone: 'neutral',
  }
})

const ivVerdict = computed<Verdict>(() => {
  const s = ivSummary.value
  if (!s?.available) {
    return {
      key: 'iv',
      lens: 'IV SURFACE',
      headline: 'NO QUOTES',
      detail: 'No usable implied-volatility quotes on this chain.',
      tone: 'missing',
    }
  }
  const cw = s.call_iv_wall != null ? `upside uncertainty parks at ${s.call_iv_wall}` : null
  const pw = s.put_iv_wall != null ? `downside uncertainty parks at ${s.put_iv_wall}` : null
  const lines = [pw, cw].filter(Boolean).join(' · ')
  return {
    key: 'iv',
    lens: 'IV SURFACE',
    headline: `ATM ${(s.atm_iv ?? 0) * 100 >= 100 ? '>100' : num((s.atm_iv ?? 0) * 100, 1)}%`,
    detail: lines
      ? `${lines}. That's where option prices carry the biggest volatility premium.`
      : 'IV smile flat — no standout wall.',
    tone: 'neutral',
  }
})

const volumeVerdict = computed<Verdict>(() => {
  const s = vpSummary.value
  if (!s?.available) {
    return {
      key: 'volume',
      lens: 'VOLUME PROFILE',
      headline: 'NOT ENOUGH BARS',
      detail: 'Volume profile needs ≥5 priced sessions with volume.',
      tone: 'missing',
    }
  }
  const poc = s.poc
  const above = poc != null && spot.value != null && spot.value > poc
  const lvns = s.lvn_count ?? 0
  return {
    key: 'volume',
    lens: 'VOLUME PROFILE',
    headline: above ? 'TRADING ABOVE POC' : 'TRADING BELOW POC',
    detail: `Heaviest trade printed at ${num(poc, 2)}${poc != null ? pctFromSpot(poc) : ''}. Value area ${num(s.value_area_low, 0)}–${num(s.value_area_high, 0)}${lvns ? `, ${lvns} thin zone${lvns === 1 ? '' : 's'} where activity dropped out` : ''}.`,
    tone: 'neutral',
  }
})

const verdicts = computed<Verdict[]>(() => [
  gammaVerdict.value,
  charmThetaVerdict.value,
  vannaVerdict.value,
  ivVerdict.value,
  volumeVerdict.value,
])

/** The one-paragraph stack read: only when multiple lenses agree. */
const stackReadout = computed<string | null>(() => {
  const parts: string[] = []
  const tones = new Set(verdicts.value.filter((v) => v.tone !== 'missing').map((v) => v.tone))
  if (!stack.value) return null
  if (tones.has('pos') && !tones.has('neg')) {
    parts.push('Decay-side lenses lean supportive')
  } else if (tones.has('neg') && !tones.has('pos')) {
    parts.push('Decay-side lenses lean pressuring')
  }
  const regime = gexRegime.value
  if (regime === 'positive') parts.push('dealer gamma caps range expansion')
  if (regime === 'negative') parts.push('dealer gamma amplifies trends')
  if (vpSummary.value?.available && vpSummary.value.poc != null && spot.value != null) {
    parts.push(
      `price is trading ${spot.value > vpSummary.value.poc ? 'above' : 'below'} the volume point of control`,
    )
  }
  if (!parts.length) return null
  return `${parts.join('; ')}. Levels below show where those lenses overlap.`
})

/** Strongest confluence clusters for the ladder. */
const topConfluence = computed<ConfluenceCluster[]>(() =>
  [...confluence.value].filter((c) => c.lens_count >= 2).slice(0, 8),
)

function lensChipClass(family: string): string {
  return `chip-${family}`
}
</script>

<template>
  <div class="livestack">
    <!-- header -->
    <header class="head">
      <div class="head-left">
        <span class="idx fig">07</span>
        <h1 class="title lab">LIVE STACK</h1>
        <span class="badge" :class="dataModeBadge.toLowerCase()">{{ dataModeBadge }}</span>
      </div>
      <form class="sym-form" @submit.prevent="applySymbol">
        <input
          v-model="symbolInput"
          class="sym-input mono"
          type="text"
          spellcheck="false"
          autocomplete="off"
          maxlength="10"
          aria-label="Underlier symbol"
          @keydown="onSymbolKeydown"
        />
        <button type="submit" class="load-btn mono">STACK IT</button>
      </form>
    </header>

    <LoadingState v-if="loading" label="Stacking every lens on the tape…" />
    <div v-else-if="error" class="fault mono">STACK UNAVAILABLE · {{ error }}</div>

    <template v-else-if="payload && !payloadError">
      <!-- verdict strip -->
      <Panel
        label="WHAT THE DATA SAYS"
        index="01"
        live
        :meta="`asof ${payload.asof_utc.slice(11, 19)}Z`"
      >
        <p v-if="stackReadout" class="stack-readout">{{ stackReadout }}</p>
        <div class="verdict-grid">
          <article v-for="v in verdicts" :key="v.key" class="verdict" :class="`tone-${v.tone}`">
            <header class="v-head">
              <span class="v-lens fig">{{ v.lens }}</span>
              <span class="v-headline fig" :class="`tone-${v.tone}`">{{ v.headline }}</span>
            </header>
            <p class="v-detail">{{ v.detail }}</p>
          </article>
        </div>
      </Panel>

      <!-- pressure gauge -->
      <div class="row two">
        <Panel
          label="PRESSURE GAUGE"
          index="02"
          :meta="pressure?.label ? pressure.label.toUpperCase() : ''"
        >
          <template v-if="pressure">
            <div class="gauge-track">
              <div
                class="gauge-fill selling"
                :style="{
                  width:
                    pressure.imbalance < 0
                      ? `${Math.min(50, Math.abs(pressure.imbalance) * 50)}%`
                      : '0%',
                }"
              />
              <div class="gauge-mid" />
              <div
                class="gauge-fill buying"
                :style="{
                  width:
                    pressure.imbalance > 0 ? `${Math.min(50, pressure.imbalance * 50)}%` : '0%',
                }"
              />
            </div>
            <div class="gauge-labels mono">
              <span>SELLING</span><span>{{ num(pressure.imbalance, 2) }}</span
              ><span>BUYING</span>
            </div>
            <p class="note">{{ pressure.convention_note }}</p>
          </template>
          <p v-else class="empty">Pressure gauge needs tape + chain inputs.</p>
        </Panel>

        <Panel
          label="LEVEL CONFLUENCE"
          index="03"
          :meta="`${topConfluence.length} multi-lens zones`"
        >
          <table v-if="topConfluence.length" class="ladder fig">
            <thead>
              <tr>
                <th>LEVEL</th>
                <th>DIST</th>
                <th>LENSES</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in topConfluence" :key="`${c.level}-${c.lens_count}`">
                <td class="lvl">
                  {{ num(c.level, 2) }} <span class="side">{{ c.above_spot ? '▲' : '▼' }}</span>
                </td>
                <td class="dist">
                  {{ c.distance_pct != null ? signedPct(c.distance_pct * 100, 1) : '—' }}
                </td>
                <td class="chips">
                  <span
                    v-for="f in c.supporting_lenses"
                    :key="f"
                    class="chip"
                    :class="lensChipClass(f)"
                    >{{ f }}</span
                  >
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty">
            No level is named by more than one lens yet — the stack has no overlap to show.
          </p>
        </Panel>
      </div>

      <!-- gamma -->
      <Panel
        label="GEX · GAMMA STRUCTURE"
        index="04"
        live
        :meta="`net ${compact(netGex)}M · ${gexRegime.toUpperCase()}`"
      >
        <GammaExposureMap
          :rows="payload.gex_by_strike ?? []"
          :spot="spot ?? 0"
          :call-wall="callWall"
          :put-wall="putWall"
          :gamma-flip="gammaFlip"
        />
      </Panel>

      <!-- decay -->
      <Panel
        label="DECAY · THETA + VANNA"
        index="05"
        :meta="
          thetaSummary?.decay_side
            ? `fastest bleed: ${String(thetaSummary.decay_side).toUpperCase()}`
            : ''
        "
      >
        <ThetaVannaChart
          v-if="thetaRows.length"
          :rows="thetaRows"
          :spot="spot"
          :call-wall="callWall"
          :put-wall="putWall"
          :gamma-flip="gammaFlip"
          :call-iv-wall="ivSummary?.call_iv_wall ?? null"
          :put-iv-wall="ivSummary?.put_iv_wall ?? null"
        />
        <p v-else class="empty">
          No dated IV + open interest — theta/vanna unmeasured for this chain.
        </p>
      </Panel>

      <!-- iv surface -->
      <div class="row two">
        <Panel
          label="IV SURFACE · WHERE UNCERTAINTY PRICES"
          index="06"
          :meta="ivSummary?.available ? `ATM ${num((ivSummary.atm_iv ?? 0) * 100, 1)}%` : ''"
        >
          <IvSurfaceChart
            v-if="ivSurface.length"
            :rows="ivSurface"
            :spot="spot"
            :summary="ivSummary"
          />
          <p v-else class="empty">No usable IV quotes on this chain.</p>
        </Panel>

        <Panel
          label="VOLUME PROFILE · WHERE ACTIVITY LIVES"
          index="07"
          :meta="vpSummary?.available ? `POC ${num(vpSummary.poc, 2)}` : ''"
        >
          <VolumeProfileChart
            v-if="vpBins.length"
            :bins="vpBins"
            :spot="spot"
            :poc="vpSummary?.poc ?? null"
            :value-area-low="vpSummary?.value_area_low ?? null"
            :value-area-high="vpSummary?.value_area_high ?? null"
          />
          <p v-else class="empty">
            Needs ≥5 priced sessions with volume{{
              priceSeries.length ? ` (have ${priceSeries.length})` : ''
            }}.
          </p>
        </Panel>
      </div>

      <footer class="disclaimer">
        DECISION SUPPORT ONLY · reports what the data says, never an order or an authorization ·
        confluence zones are descriptive geometry, not probabilities.
      </footer>
    </template>

    <div v-else-if="payloadError" class="fault mono">{{ payloadError }}</div>
  </div>
</template>

<style scoped>
.livestack {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  max-width: 1560px;
  margin: 0 auto;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  flex-wrap: wrap;
}

.head-left {
  display: flex;
  align-items: center;
  gap: var(--s3);
}

.idx {
  font-size: var(--t-micro);
  color: var(--phosphor);
  background: var(--phosphor-wash);
  padding: 2px 7px;
  border-radius: var(--r-xs);
  border: var(--hair) solid color-mix(in srgb, var(--phosphor) 20%, transparent);
}

.title {
  font-size: var(--t-display);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ink);
}

.badge {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
  padding: 2px 8px;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-dim);
}

.badge.live {
  color: var(--phosphor);
  border-color: color-mix(in srgb, var(--phosphor) 40%, transparent);
  background: var(--phosphor-wash);
}

.badge.delayed,
.badge.history {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 35%, transparent);
}

.badge.fault,
.badge.no-data {
  color: var(--halt);
  border-color: color-mix(in srgb, var(--halt) 40%, transparent);
}

.sym-form {
  display: flex;
  gap: var(--s2);
}

.sym-input {
  width: 9ch;
  background: var(--panel);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
  color: var(--ink);
  font-size: var(--t-body);
  padding: 6px 10px;
  text-transform: uppercase;
}

.sym-input:focus {
  outline: none;
  border-color: var(--phosphor);
}

.load-btn {
  background: var(--phosphor-wash);
  border: var(--hair) solid color-mix(in srgb, var(--phosphor) 45%, transparent);
  color: var(--phosphor);
  border-radius: var(--r-sm);
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
  padding: 6px 14px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}

.load-btn:hover {
  background: color-mix(in srgb, var(--phosphor) 16%, transparent);
}

.fault {
  border: var(--hair) solid color-mix(in srgb, var(--halt) 45%, transparent);
  background: color-mix(in srgb, var(--halt) 8%, transparent);
  color: var(--halt);
  padding: var(--s4);
  border-radius: var(--r-md);
  font-size: var(--t-small);
  letter-spacing: 0.04em;
}

.stack-readout {
  margin: 0 0 var(--s3);
  color: var(--ink-soft);
  font-size: var(--t-small);
  line-height: 1.55;
  border-left: 2px solid var(--phosphor);
  padding-left: var(--s3);
}

.verdict-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: var(--s3);
}

.verdict {
  border: var(--hair) solid var(--rule-faint);
  border-radius: var(--r-sm);
  padding: var(--s3);
  background: rgba(255, 255, 255, 0.012);
  min-width: 0;
}

.v-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: var(--s2);
}

.v-lens {
  font-size: var(--t-micro);
  letter-spacing: 0.1em;
  color: var(--ink-faint);
}

.v-headline {
  font-size: var(--t-small);
  font-weight: 600;
  letter-spacing: 0.03em;
}

.v-headline.tone-pos {
  color: var(--long);
}
.v-headline.tone-neg {
  color: var(--short);
}
.v-headline.tone-neutral {
  color: var(--ink);
}
.v-headline.tone-missing {
  color: var(--ink-ghost);
}

.v-detail {
  margin: 0;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  line-height: 1.5;
}

.row.two {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
  gap: var(--s4);
  align-items: stretch;
}

.gauge-track {
  position: relative;
  display: flex;
  height: 18px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm);
  overflow: hidden;
  background: rgba(255, 255, 255, 0.02);
}

.gauge-fill.selling {
  background: color-mix(in srgb, var(--short) 55%, transparent);
  margin-right: auto;
}

.gauge-fill.buying {
  background: color-mix(in srgb, var(--long) 55%, transparent);
  margin-left: auto;
}

.gauge-mid {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--rule-hi);
}

.gauge-labels {
  display: flex;
  justify-content: space-between;
  margin-top: var(--s2);
  font-size: var(--t-micro);
  color: var(--ink-faint);
  letter-spacing: 0.06em;
}

.note,
.method-note-global {
  margin: var(--s3) 0 0;
  color: var(--ink-ghost);
  font-size: var(--t-micro);
  line-height: 1.5;
}

.empty {
  margin: 0;
  color: var(--ink-ghost);
  font-size: var(--t-tiny);
  letter-spacing: 0.02em;
  padding: var(--s3) 0;
}

.ladder {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-small);
}

.ladder th {
  text-align: left;
  font-weight: 500;
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: 0.08em;
  border-bottom: var(--hair) solid var(--rule);
  padding: 4px 8px 6px 0;
}

.ladder td {
  padding: 7px 8px 7px 0;
  border-bottom: var(--hair) solid var(--rule-faint);
  vertical-align: middle;
}

.ladder tr:last-child td {
  border-bottom: none;
}

.lvl {
  color: var(--ink);
  font-weight: 600;
}

.side {
  font-size: var(--t-micro);
  color: var(--ink-faint);
}

.dist {
  color: var(--ink-dim);
}

.chips {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.chip {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 1px 6px;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
  color: var(--ink-dim);
}

.chip-gamma {
  color: var(--cat-2);
  border-color: color-mix(in srgb, var(--cat-2) 35%, transparent);
}

.chip-theta {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 35%, transparent);
}

.chip-vanna {
  color: var(--cat-1);
  border-color: color-mix(in srgb, var(--cat-1) 40%, transparent);
}

.chip-iv {
  color: var(--cat-4);
  border-color: color-mix(in srgb, var(--cat-4) 40%, transparent);
}

.chip-volume {
  color: var(--phosphor);
  border-color: color-mix(in srgb, var(--phosphor) 30%, transparent);
}

.disclaimer {
  color: var(--ink-ghost);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: 0.05em;
  text-align: center;
  padding-bottom: var(--s4);
}
</style>
