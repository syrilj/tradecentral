<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch, computed } from 'vue'
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
  { name: 'brief', title: 'Brief', idx: '00', hint: 'Every lens, one symbol' },
  { name: 'desk', title: 'Desk', idx: '01', hint: 'Signals & candidates' },
  { name: 'plays', title: 'Plays', idx: '02', hint: "Today's decision funnel" },
  { name: 'market', title: 'Market', idx: '02', hint: 'Search · VWAP · EMA' },
  { name: 'sectors', title: 'Sectors', idx: '03', hint: 'Sector rotation & flow' },
  { name: 'sentiment', title: 'Pulse', idx: '04', hint: 'Structure · COT · outliers' },
  { name: 'macro', title: 'Macro', idx: '04', hint: 'Cross-asset regime board' },
  { name: 'crypto', title: 'Crypto', idx: '07', hint: '24/7 coin tape · Kalman · BTC COT' },
  { name: 'options', title: 'Options', idx: '05', hint: 'One underlier · gamma · density' },
  { name: 'suggest', title: 'Setups', idx: '05', hint: 'Strike · levels · GEX plan' },
  { name: 'chain', title: 'Chain', idx: '05', hint: 'Value chain and growth' },
  { name: 'reversal', title: 'Reversal', idx: '08', hint: 'Bottoms · tops · when to add' },
  { name: 'drift', title: 'Drift', idx: '05', hint: 'Buying vs selling pressure' },
  { name: 'regime', title: 'Regime', idx: '05', hint: 'Dealer-gamma surface & density' },
  { name: 'gamma', title: 'Gamma', idx: '05', hint: 'Call resistance · zero gamma · support' },
  { name: 'flow', title: 'Flow', idx: '06', hint: 'Market-wide options tape' },
  { name: 'absorption', title: 'Absorption', idx: '07', hint: 'Heavy flow, held level' },
  { name: 'livestack', title: 'Live Stack', idx: '07', hint: 'All lenses, one tape' },
  { name: 'liquidity', title: 'Liquidity', idx: '08', hint: 'Stops, sweeps, and pools' },
  {
    name: 'microstructure-regime',
    title: 'Microstructure',
    idx: '05',
    hint: 'Envelope, breadth, and flow',
  },
  { name: 'gates', title: 'Gates', idx: '06', hint: 'Pre-registered verdicts' },
  { name: 'cloud', title: 'Cloud', idx: '07', hint: 'Vertex AI training' },
  { name: 'evolution', title: 'Evolution', idx: '08', hint: 'GA survivors lab' },
  { name: 'research', title: 'Research', idx: '09', hint: 'IC decay · quantile spread' },
  { name: 'graph', title: 'Graph', idx: '10', hint: 'Repo knowledge graph' },
  { name: 'adaptive', title: 'Live Blend', idx: '11', hint: 'Regime multi-stream adapt' },
  { name: 'fintel', title: 'Fintel', idx: '12', hint: 'Short · borrow · owners · flow' },
  { name: 'insiders', title: 'Insiders', idx: '15', hint: 'Form 4 · Fintel insider tape' },
  { name: 'changepoints', title: 'Breaks', idx: '13', hint: 'Bayesian regime breaks' },
  { name: 'kalman', title: 'Kalman', idx: '14', hint: 'Constant-velocity trend' },
  { name: 'momentum', title: 'Momentum', idx: '14', hint: 'Five Pillars · gap scan' },
  { name: 'calculator', title: 'Calculator', idx: '16', hint: 'Spot · strike · DTE · P/L' },
  { name: 'voltrend', title: 'Vol Trend', idx: '16', hint: 'Volatility-targeted trend strategy' },
  { name: 'vanna', title: 'Vanna', idx: '17', hint: 'Delta–vol coupling · FOMC event load' },
  { name: 'flowstate', title: 'Flow State', idx: '15', hint: 'Daily proxy research' },
  { name: 'vpa', title: 'VPA', idx: '17', hint: 'Volume Price Analysis & AI vision' },
  { name: 'amt', title: 'AMT', idx: '18', hint: 'Auction Market Theory · balance vs breakout' },
  { name: 'decision', title: 'Decision', idx: '19', hint: 'TypeSafe live read · Decision Brain' },
]

const q = ref('')
const hits = ref<SearchHit[]>([])
const cursor = ref(0)
const busy = ref(false)
const err = ref<string | null>(null)
const input = ref<HTMLInputElement | null>(null)
const paletteEl = ref<HTMLDivElement | null>(null)
let previousFocus: HTMLElement | null = null

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

type PaletteRow = { kind: 'view'; name: string } | { kind: 'symbol'; symbol: string }

/** Views sit above tickers, which is the order ↑↓ has to walk. */
const rows = computed<PaletteRow[]>(() => [
  ...matchingViews.value.map((view) => ({ kind: 'view' as const, name: view.name })),
  ...displayHits.value.map((hit) => ({ kind: 'symbol' as const, symbol: hit.symbol })),
])

const activeRowId = computed(() => (rows.value.length ? `palette-row-${cursor.value}` : undefined))

watch(rows, (list) => {
  if (!list.length || cursor.value > list.length - 1) cursor.value = 0
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

watch(q, (v) => {
  cursor.value = 0
  run(cleanTicker(v))
})

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End') {
    e.preventDefault()
    if (!rows.value.length) return
    const next =
      e.key === 'Home'
        ? 0
        : e.key === 'End'
          ? rows.value.length - 1
          : e.key === 'ArrowUp'
            ? (cursor.value - 1 + rows.value.length) % rows.value.length
            : (cursor.value + 1) % rows.value.length
    cursor.value = next
    const el = document.getElementById(`palette-row-${next}`)
    el?.scrollIntoView({ block: 'nearest' })
    if (document.activeElement !== input.value) el?.focus()
    return
  }
  if (e.key === 'Escape') {
    e.preventDefault()
    emit('close')
    return
  }
  if (e.key === 'Enter' && e.target === input.value) {
    e.preventDefault()
    commit()
    return
  }
  if (e.key !== 'Tab') return
  const root = paletteEl.value
  if (!root) return
  const focusable = Array.from(
    root.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((el) => !el.hasAttribute('disabled') && el.getClientRects().length > 0)
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (!root.contains(document.activeElement)) {
    e.preventDefault()
    first.focus()
    return
  }
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
    return
  }
  if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}

onMounted(async () => {
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  await nextTick()
  input.value?.focus()
  run('')
})

onUnmounted(() => {
  previousFocus?.focus({ preventScroll: true })
  previousFocus = null
})

function commit(): void {
  const row = rows.value[cursor.value]
  if (!row) {
    const term = cleanTicker(q.value)
    if (term) emit('select', term)
    return
  }
  if (row.kind === 'view') {
    openView(row.name)
    return
  }
  if (row.kind === 'symbol') {
    emit('select', row.symbol)
    return
  }
  const unreachable: never = row
  return unreachable
}
</script>

<template>
  <div class="scrim" role="presentation" @click.self="emit('close')">
    <div
      ref="paletteEl"
      class="palette ticked"
      role="dialog"
      aria-modal="true"
      aria-label="Symbol search"
      @keydown="onKeydown"
    >
      <div class="field">
        <AppIcon class="glyph" name="search" :size="18" />
        <input
          ref="input"
          v-model="q"
          class="input"
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded="true"
          aria-controls="palette-list"
          :aria-activedescendant="activeRowId"
          aria-label="Search symbols and views"
          :placeholder="`Search ${symbolCount ?? 'all'} symbols · SPY · AAPL · NVDA`"
          autocomplete="off"
          autocapitalize="none"
          autocorrect="off"
          spellcheck="false"
          enterkeyhint="search"
          aria-describedby="search-results-count"
        />
        <span id="search-results-count" class="label state" role="status" aria-live="polite">{{
          busy ? 'SCANNING' : `${displayHits.length} TICKER${displayHits.length === 1 ? '' : 'S'}`
        }}</span>
      </div>

      <div id="palette-list" class="results-scroll" role="listbox">
        <div v-if="matchingViews.length" class="section-block">
          <header class="section-head label">VIEWS &amp; COMMANDS</header>
          <ul class="cmd-list">
            <li v-for="(v, i) in matchingViews" :key="v.name">
              <button
                :id="`palette-row-${i}`"
                class="cmd-hit"
                :class="{ on: cursor === i }"
                type="button"
                role="option"
                :aria-selected="cursor === i"
                @click="openView(v.name)"
                @mouseenter="cursor = i"
                @focus="cursor = i"
              >
                <span class="cmd-idx fig">{{ v.idx }}</span>
                <span class="cmd-title label">{{ v.title }}</span>
                <span class="cmd-hint label">{{ v.hint }}</span>
              </button>
            </li>
          </ul>
        </div>

        <div class="section-block">
          <header class="section-head label">SYMBOLS &amp; TICKERS</header>
          <p v-if="err" class="err label" role="alert" aria-live="assertive">{{ err }}</p>
          <ul class="hits">
            <li v-for="(h, i) in displayHits" :key="h.symbol + String(h.n_bars)">
              <button
                :id="`palette-row-${matchingViews.length + i}`"
                type="button"
                class="hit"
                role="option"
                :aria-selected="cursor === matchingViews.length + i"
                :class="{ on: cursor === matchingViews.length + i, free: !h.n_bars }"
                @mouseenter="cursor = matchingViews.length + i"
                @focus="cursor = matchingViews.length + i"
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
        <span class="label"><kbd>⏎</kbd> open</span>
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
  max-height: min(66dvh, 640px);
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
  /* ⌘K is used constantly. An entrance animation makes the shortcut feel late. */
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
  overscroll-behavior: contain;
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
  min-height: 44px;
  padding: 6px var(--s3);
  border-radius: var(--r-sm);
  cursor: pointer;
  border-left: 2px solid transparent;
  transition:
    background 140ms var(--ease-out),
    border-color 140ms var(--ease-out),
    transform 140ms var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
  .cmd-hit:hover {
    background: var(--phosphor-wash);
  }
}
.cmd-hit.on {
  background: var(--phosphor-wash);
  border-left-color: var(--phosphor);
}
.cmd-hit:active {
  transform: scale(0.98);
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
  flex: 0 0 auto;
  min-width: 90px;
}
.cmd-hint {
  color: var(--ink-dim);
  font-size: var(--t-micro);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  min-height: 44px;
  padding: var(--s2) var(--s3);
  border-radius: var(--r-sm);
  cursor: pointer;
  border-left: 2px solid transparent;
  transition:
    background 140ms var(--ease-out),
    border-color 140ms var(--ease-out),
    color 140ms var(--ease-out),
    transform 140ms var(--ease-out);
}
.hit:active {
  transform: scale(0.98);
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
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  overflow-wrap: anywhere;
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
  outline: var(--focus-ring);
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
