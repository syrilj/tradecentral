<script setup lang="ts">
import { ref, onMounted, nextTick, watch, computed } from 'vue'
import { api, type SearchHit } from '@/api'
import { debounce } from '@/composables/useResource'
import { shortDate } from '@/format'

/**
 * ⌘K symbol search over the server-indexed local daily universe.
 * Keyboard-first: type, arrow, enter. Case-insensitive. Exact typed tickers
 * that are not in cache still appear so the user can try to open them.
 */
defineProps<{ symbolCount?: number | null }>()
const emit = defineEmits<{ close: []; select: [symbol: string] }>()

const q = ref('')
const hits = ref<SearchHit[]>([])
const cursor = ref(0)
const busy = ref(false)
const err = ref<string | null>(null)
const input = ref<HTMLInputElement | null>(null)

function cleanTicker(term: string): string {
  return term.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, '').slice(0, 10)
}

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
  document
    .getElementById(`hit-${cursor.value}`)
    ?.scrollIntoView({ block: 'nearest' })
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
        <span class="glyph" aria-hidden="true">⌕</span>
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
        <span class="label state">{{ busy ? 'SCANNING' : `${displayHits.length} TICKER${displayHits.length === 1 ? '' : 'S'}` }}</span>
      </div>

      <p v-if="err" class="err label">{{ err }}</p>

      <ul v-else class="hits">
        <li
          v-for="(h, i) in displayHits"
          :id="`hit-${i}`"
          :key="h.symbol + String(h.n_bars)"
          class="hit"
          :class="{ on: i === cursor, free: !h.n_bars }"
          @mouseenter="cursor = i"
          @click="emit('select', h.symbol)"
        >
          <span class="sym fig">{{ h.symbol }}</span>
          <span class="tier label" :class="h.tier || (h.n_bars ? 'wide' : 'live')">{{ h.n_bars ? h.tier : (h.tier === 'live' ? 'LIVE' : 'OPEN') }}</span>
          <span class="span label">
            <template v-if="h.n_bars">{{ shortDate(h.first_date) }} to {{ shortDate(h.last_date) }}</template>
            <template v-else>not in local catalog — open via live bars</template>
          </span>
          <span class="bars fig">{{ h.n_bars || '—' }}</span>
        </li>
        <li v-if="!displayHits.length && !busy" class="empty label">No ticker matches “{{ q }}”</li>
      </ul>

      <footer class="keys">
        <span class="label"><kbd>↑↓</kbd> move</span>
        <span class="label"><kbd>⏎</kbd> open trajectory</span>
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
  background: rgba(4, 5, 7, 0.72);
  backdrop-filter: blur(3px);
  display: flex;
  justify-content: center;
  padding-top: 12vh;
}

.palette {
  width: min(680px, calc(100vw - var(--s6)));
  max-height: 66vh;
  display: flex;
  flex-direction: column;
  border: var(--hair) solid var(--rule-hi);
  padding: var(--s1);
  box-shadow: 0 32px 80px rgba(0, 0, 0, 0.62);
  animation: rise var(--dur) var(--ease-out) both;
}

.field {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s4);
  border-bottom: var(--hair) solid var(--rule);
}

.glyph { color: var(--phosphor); font-size: 1rem; line-height: 1; }

.input {
  flex: 1 1 auto;
  font-family: var(--font-data);
  font-size: var(--t-lead);
  color: var(--ink);
  letter-spacing: 0.01em;
  min-width: 0;
}
.input::placeholder { color: var(--ink-ghost); font-family: var(--font-ui); letter-spacing: 0; }
.input:focus-visible { outline: none; }

.state { color: var(--ink-faint); flex: 0 0 auto; }

.hits {
  list-style: none;
  overflow-y: auto;
  flex: 1 1 auto;
  padding: var(--s2) 0;
}

.hit {
  display: grid;
  grid-template-columns: 7ch 4.5rem 1fr auto;
  align-items: center;
  gap: var(--s3);
  padding: var(--s2) var(--s4);
  cursor: pointer;
  border-left: 2px solid transparent;
}

.hit.on {
  background: var(--phosphor-wash);
  border-left-color: var(--phosphor);
}
.hit.free .sym { color: var(--ink-dim); }
.hit.free .tier { color: var(--warn); border-color: var(--warn); }

.sym { font-size: var(--t-body); font-weight: 600; color: var(--ink); }
.hit.on .sym { color: var(--phosphor); }

.tier {
  justify-self: start;
  padding: 1px 5px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-faint);
}
.tier.core { color: var(--phosphor-dim); border-color: var(--phosphor-dim); }
.tier.live { color: var(--warn); border-color: var(--warn); }
.track-badge { color: #ffb703; border-color: #ffb703; font-weight: 600; font-size: 0.7rem; letter-spacing: 0.05em; }

.span { color: var(--ink-ghost); letter-spacing: 0.05em; }
.bars { font-size: var(--t-tiny); color: var(--ink-faint); }

.empty, .err { padding: var(--s5) var(--s4); color: var(--ink-faint); text-align: center; }
.err { color: var(--short); }

.keys {
  display: flex;
  gap: var(--s4);
  padding: var(--s2) var(--s4);
  border-top: var(--hair) solid var(--rule);
  color: var(--ink-ghost);
}

kbd {
  font-family: var(--font-data);
  border: var(--hair) solid var(--rule-hi);
  padding: 0 4px;
  margin-right: 3px;
  color: var(--ink-faint);
}
</style>
