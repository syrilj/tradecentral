<script setup lang="ts">
import { ref, onMounted, nextTick, watch, computed } from 'vue'
import { api, type SearchHit } from '@/api'
import { debounce } from '@/composables/useResource'
import { shortDate } from '@/format'
import AppIcon from '@/components/AppIcon.vue'

/**
 * ⌘K symbol search over the server-indexed local daily universe.
 * Keyboard-first: type, arrow, enter. Case-insensitive. Exact typed tickers
 * that are not in cache still appear so the user can try to open them.
 */
import { useRouter } from 'vue-router'

defineProps<{ symbolCount?: number | null }>()
const emit = defineEmits<{ close: []; select: [symbol: string] }>()

const router = useRouter()

interface NavCommand {
  name: string
  title: string
  idx: string
  hint: string
}

const NAV_COMMANDS: NavCommand[] = [
  { name: 'desk', title: 'Desk', idx: '01', hint: 'Signals & candidates' },
  { name: 'market', title: 'Market', idx: '02', hint: 'Search · VWAP · EMA' },
  { name: 'sectors', title: 'Sectors', idx: '03', hint: 'Sector rotation & flow' },
  { name: 'sentiment', title: 'Pulse', idx: '04', hint: 'Structure · COT · outliers' },
  { name: 'macro', title: 'Macro', idx: '04', hint: 'Cross-asset regime board' },
  { name: 'crypto', title: 'Crypto', idx: '07', hint: '24/7 coin tape · Kalman · BTC COT' },
  { name: 'options', title: 'Options', idx: '05', hint: 'Flow · gamma · density' },
  { name: 'drift', title: 'Drift', idx: '05', hint: 'Buying vs selling pressure' },
  { name: 'regime', title: 'Regime', idx: '05', hint: 'Dealer-gamma surface & density' },
  { name: 'flow', title: 'Flow', idx: '06', hint: 'Market-wide options tape' },
  { name: 'absorption', title: 'Absorption', idx: '07', hint: 'Heavy flow, held level' },
  { name: 'livestack', title: 'Live Stack', idx: '07', hint: 'All lenses, one tape' },
  { name: 'gates', title: 'Gates', idx: '06', hint: 'Pre-registered verdicts' },
  { name: 'cloud', title: 'Cloud', idx: '07', hint: 'Vertex AI training' },
  { name: 'evolution', title: 'Evolution', idx: '08', hint: 'GA survivors lab' },
  { name: 'research', title: 'Research', idx: '09', hint: 'IC decay · quantile spread' },
  { name: 'graph', title: 'Graph', idx: '10', hint: 'Repo knowledge graph' },
  { name: 'adaptive', title: 'Live Blend', idx: '11', hint: 'Regime multi-stream adapt' },
  { name: 'fintel', title: 'Fintel', idx: '12', hint: 'Short · borrow · owners · flow' },
  { name: 'insiders', title: 'Insiders', idx: '15', hint: 'Form 4 · Fintel insider tape' },
  { name: 'changepoints', title: 'Breaks', idx: '13', hint: 'Bayesian regime breaks' },
  { name: 'momentum', title: 'Momentum', idx: '14', hint: 'Five Pillars · gap scan' },
  { name: 'calculator', title: 'Calculator', idx: '16', hint: 'Spot · strike · DTE · P/L' },
  { name: 'voltrend', title: 'Vol Trend', idx: '16', hint: 'Volatility-targeted trend strategy' },
  { name: 'flowstate', title: 'Flow State', idx: '15', hint: 'Daily proxy research' },
  { name: 'vpa', title: 'VPA', idx: '17', hint: 'Volume Price Analysis & AI vision' },
  { name: 'amt', title: 'AMT', idx: '18', hint: 'Auction Market Theory · balance vs breakout' },
]

const q = ref('')
const hits = ref<SearchHit[]>([])
const cursor = ref(0)
const busy = ref(false)
const err = ref<string | null>(null)
const input = ref<HTMLInputElement | null>(null)

function cleanTicker(term: string): string {
  return term
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
    .slice(0, 10)
}

const matchingViews = computed(() => {
  const term = q.value.trim().toLowerCase()
  if (!term) return NAV_COMMANDS
  return NAV_COMMANDS.filter(
    (v) =>
      v.title.toLowerCase().includes(term) ||
      v.name.toLowerCase().includes(term) ||
      v.hint.toLowerCase().includes(term) ||
      v.idx.includes(term),
  )
})

const displayHits = computed(() => {
  const term = cleanTicker(q.value)
  const list = [...hits.value]
  if (term.length >= 1 && !list.some((h) => h.symbol === term)) {
    list.unshift({
      symbol: term,
      kind: 'symbol',
      tier: 'wide',
      n_bars: 0,
      first_date: '',
      last_date: '',
    } as SearchHit)
  }
  return list
})

function openView(name: string): void {
  emit('close')
  void router.push({ name })
}

const run = debounce(async (term: string) => {
  busy.value = true
  try {
    const raw = await api.search(term, 40)
    // Symbols only — factor tracks are not tradeable underlyings.
    hits.value = raw.filter((h) => (h.kind ?? 'symbol') === 'symbol')
    cursor.value = 0
    err.value = null
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e)
    hits.value = []
  } finally {
    busy.value = false
  }
}, 130)

watch(q, (v) => run(cleanTicker(v)))

onMounted(async () => {
  await nextTick()
  input.value?.focus()
  run('')
})

function move(delta: number): void {
  if (!displayHits.value.length) return
  cursor.value = (cursor.value + delta + displayHits.value.length) % displayHits.value.length
  document.getElementById(`hit-${cursor.value}`)?.scrollIntoView({ block: 'nearest' })
}

function commit(): void {
  const hit = displayHits.value[cursor.value]
  if (hit) emit('select', hit.symbol)
  else {
    const term = cleanTicker(q.value)
    if (term) emit('select', term)
  }
}
</script>

<template>
  <div class="scrim" @click.self="emit('close')">
    <div class="palette ticked" role="dialog" aria-modal="true" aria-label="Symbol search">
      <div class="field">
        <AppIcon class="glyph" name="search" :size="18" />
        <input
          ref="input"
          v-model="q"
          class="input"
          type="text"
          :placeholder="`Search ${symbolCount ?? 'all'} symbols · SPY · AAPL · NVDA`"
          autocomplete="off"
          spellcheck="false"
          @keydown.down.prevent="move(1)"
          @keydown.up.prevent="move(-1)"
          @keydown.enter.prevent="commit"
          @keydown.esc.prevent="emit('close')"
        />
        <span class="label state">{{
          busy ? 'SCANNING' : `${displayHits.length} TICKER${displayHits.length === 1 ? '' : 'S'}`
        }}</span>
      </div>

      <p v-if="err" class="err label">{{ err }}</p>

      <div v-else class="results-scroll">
        <div v-if="matchingViews.length" class="section-block">
          <header class="section-head label">VIEWS &amp; COMMANDS</header>
          <ul class="cmd-list">
            <li v-for="v in matchingViews" :key="v.name">
              <button class="cmd-hit" type="button" @click="openView(v.name)">
                <span class="cmd-idx fig">{{ v.idx }}</span>
                <span class="cmd-title label">{{ v.title }}</span>
                <span class="cmd-hint label">{{ v.hint }}</span>
              </button>
            </li>
          </ul>
        </div>

        <div class="section-block">
          <header class="section-head label">SYMBOLS &amp; TICKERS</header>
          <ul class="hits">
            <li v-for="(h, i) in displayHits" :key="h.symbol + String(h.n_bars)">
              <button
                :id="`hit-${i}`"
                type="button"
                class="hit"
                :class="{ on: i === cursor, free: !h.n_bars }"
                @mouseenter="cursor = i"
                @click="emit('select', h.symbol)"
              >
                <span class="sym fig">{{ h.symbol }}</span>
                <span class="tier label" :class="h.tier || (h.n_bars ? 'wide' : 'live')">{{
                  h.n_bars ? h.tier : h.tier === 'live' ? 'LIVE' : 'OPEN'
                }}</span>
                <span class="span label">
                  <template v-if="h.n_bars"
                    >{{ shortDate(h.first_date) }} to {{ shortDate(h.last_date) }}</template
                  >
                  <template v-else>not in local catalog: open via live bars</template>
                </span>
                <span class="bars fig">{{ h.n_bars || '—' }}</span>
              </button>
            </li>
            <li v-if="!displayHits.length && !busy" class="empty label">
              No ticker matches “{{ q }}”
            </li>
          </ul>
        </div>
      </div>

      <footer class="keys">
        <span class="label"><kbd>↑↓</kbd> move</span>
        <span class="label"><kbd>⏎</kbd> open ticker</span>
        <span class="label"><kbd>esc</kbd> dismiss</span>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  /* Lightened so the content layer peeks through behind the floating palette
     while staying dark enough to keep the modal readable. */
  background: color-mix(in srgb, var(--void) 55%, transparent);
  display: flex;
  justify-content: center;
  padding-top: 12vh;
}

.palette {
  width: min(680px, calc(100vw - var(--s6)));
  max-height: 66vh;
  display: flex;
  flex-direction: column;
  border: var(--hair) solid var(--glass-border-hi);
  border-radius: var(--r-xl);
  padding: 0;
  /* Floating functional chrome: the one surface allowed glass. Children
     (e.g. .field below) must stay solid — glass never nests. */
  background: var(--glass-overlay);
  backdrop-filter: var(--glass-blur-lg);
  -webkit-backdrop-filter: var(--glass-blur-lg);
  box-shadow:
    0 24px 64px rgba(0, 0, 0, 0.85),
    var(--glass-specular);
  overflow: hidden;
  animation: rise var(--dur) var(--ease-out) both;
}

.field {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  border-bottom: var(--hair) solid var(--rule);
  /* Solid child of the glass palette — no backdrop blur. */
  background: var(--void-lift);
}

.field {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  border-bottom: var(--hair) solid var(--rule);
  background: var(--void-lift);
}

.glyph {
  color: var(--phosphor);
}

.input {
  flex: 1 1 auto;
  font-family: var(--font-data);
  font-size: var(--t-lead);
  color: var(--ink);
  letter-spacing: 0.01em;
  min-width: 0;
}
.input::placeholder {
  color: var(--ink-faint);
  font-family: var(--font-ui);
  letter-spacing: 0;
}
/* The palette autofocuses this field, so the ring is usually redundant — but
   "usually" is not "always": focus can return here from a result row, and with
   `outline: none` and no replacement there was then nothing on screen saying
   where typing would go. The ring is drawn inside the field so it does not
   collide with the palette's own border. */
.input:focus-visible {
  outline: var(--focus-ring);
  outline-offset: -3px;
  border-radius: var(--r-xs);
}

.state {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  flex: 0 0 auto;
}

.results-scroll {
  overflow-y: auto;
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s2) 0;
}

.section-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.section-head {
  padding: 4px var(--s4);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}

.cmd-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 0 4px;
}

.cmd-hit {
  width: 100%;
  display: flex;
  align-items: center;
  text-align: left;
  gap: var(--s3);
  min-height: 36px;
  padding: 6px var(--s3);
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}
.cmd-hit:hover {
  background: var(--phosphor-wash);
}
.cmd-idx {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  color: var(--phosphor);
  min-width: 2ch;
}
.cmd-title {
  font-family: var(--font-ui);
  font-weight: 600;
  font-size: var(--t-small);
  color: var(--ink);
  min-width: 90px;
}
.cmd-hint {
  color: var(--ink-dim);
  font-size: var(--t-micro);
}

.hits {
  list-style: none;
  padding: 0 4px;
}

.hit {
  display: grid;
  width: 100%;
  grid-template-columns: 7ch 4.5rem 1fr auto;
  align-items: center;
  text-align: left;
  gap: var(--s3);
  min-height: 36px;
  padding: var(--s2) var(--s3);
  border-radius: var(--r-sm);
  cursor: pointer;
  border-left: 2px solid transparent;
  transition: all var(--dur-fast) var(--ease-out);
}

.hit.on {
  background: var(--phosphor-wash);
  border-left-color: var(--phosphor);
}
.hit.free .sym {
  color: var(--ink-dim);
}
.hit.free .tier {
  color: var(--warn);
  border-color: var(--warn);
}

.sym {
  font-family: var(--font-data);
  font-size: var(--t-body);
  font-weight: 600;
  color: var(--ink);
}
.hit.on .sym {
  color: var(--phosphor);
}

.tier {
  justify-self: start;
  padding: 1px 5px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  color: var(--ink-faint);
}
.tier.core {
  color: var(--phosphor-dim);
  border-color: var(--phosphor-dim);
}
.tier.live {
  color: var(--warn);
  border-color: var(--warn);
}
.track-badge {
  color: var(--warn);
  border-color: var(--warn);
  font-weight: 600;
  font-size: 0.7rem;
  letter-spacing: 0.05em;
}

.span {
  color: var(--ink-faint);
  letter-spacing: 0.03em;
}
.bars {
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  color: var(--ink-faint);
}

.empty,
.err {
  padding: var(--s5) var(--s4);
  color: var(--ink-faint);
  text-align: center;
}
.err {
  color: var(--short);
}

.keys {
  display: flex;
  gap: var(--s4);
  padding: var(--s2) var(--s4);
  border-top: var(--hair) solid var(--rule);
  background: var(--void-lift);
  color: var(--ink-faint);
}

kbd {
  font-family: var(--font-data);
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-xs);
  padding: 0 4px;
  margin-right: 3px;
  color: var(--ink-faint);
}

.cmd-hit:focus-visible,
.hit:focus-visible {
  outline: var(--hair) solid var(--phosphor);
  outline-offset: -2px;
}

@media (max-width: 780px) {
  .scrim {
    padding-top: var(--s3);
  }
  .palette {
    width: calc(100vw - var(--s4));
    max-height: calc(100dvh - var(--s6));
  }
  .state,
  .cmd-hint,
  .span {
    display: none;
  }
  .cmd-hit,
  .hit {
    min-height: 44px;
  }
  .hit {
    grid-template-columns: 7ch 4.5rem 1fr;
  }
  .bars {
    justify-self: end;
  }
}
</style>
