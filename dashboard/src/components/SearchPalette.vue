<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import { api, type SearchHit } from '@/api'
import { debounce } from '@/composables/useResource'
import { shortDate } from '@/format'

/**
 * ⌘K symbol search over the 558-name daily universe.
 * Keyboard-first: type, arrow, enter. The mouse is optional.
 */
const emit = defineEmits<{ close: []; select: [symbol: string] }>()

const q = ref('')
const hits = ref<SearchHit[]>([])
const cursor = ref(0)
const busy = ref(false)
const err = ref<string | null>(null)
const input = ref<HTMLInputElement | null>(null)

const run = debounce(async (term: string) => {
  busy.value = true
  try {
    hits.value = await api.search(term, 40)
    cursor.value = 0
    err.value = null
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e)
    hits.value = []
  } finally {
    busy.value = false
  }
}, 130)

watch(q, (v) => run(v.trim()))

onMounted(async () => {
  await nextTick()
  input.value?.focus()
  run('')
})

function move(delta: number): void {
  if (!hits.value.length) return
  cursor.value = (cursor.value + delta + hits.value.length) % hits.value.length
  document
    .getElementById(`hit-${cursor.value}`)
    ?.scrollIntoView({ block: 'nearest' })
}

function commit(): void {
  const hit = hits.value[cursor.value]
  if (hit) emit('select', hit.symbol)
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
          placeholder="Search 558 symbols — ticker or fragment"
          autocomplete="off"
          spellcheck="false"
          @keydown.down.prevent="move(1)"
          @keydown.up.prevent="move(-1)"
          @keydown.enter.prevent="commit"
          @keydown.esc.prevent="emit('close')"
        />
        <span class="label state">{{ busy ? 'SCANNING' : `${hits.length} HIT${hits.length === 1 ? '' : 'S'}` }}</span>
      </div>

      <p v-if="err" class="err label">{{ err }}</p>

      <ul v-else class="hits">
        <li
          v-for="(h, i) in hits"
          :id="`hit-${i}`"
          :key="h.symbol"
          class="hit"
          :class="{ on: i === cursor, isTrack: h.kind === 'track' }"
          @mouseenter="cursor = i"
          @click="emit('select', h.symbol)"
        >
          <span class="sym fig">{{ h.symbol }}</span>
          <span v-if="h.kind === 'track'" class="tier label track-badge">{{ h.category || 'TRACK' }}</span>
          <span v-else class="tier label" :class="h.tier">{{ h.tier }}</span>
          <span class="span label">
            <template v-if="h.kind === 'track'">{{ h.description || h.name }}</template>
            <template v-else>{{ shortDate(h.first_date) }} → {{ shortDate(h.last_date) }}</template>
          </span>
          <span class="bars fig">{{ h.kind === 'track' ? 'TRACK' : h.n_bars }}</span>
        </li>
        <li v-if="!hits.length && !busy" class="empty label">No symbol or track matches “{{ q }}”</li>
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

.sym { font-size: var(--t-body); font-weight: 600; color: var(--ink); }
.hit.on .sym { color: var(--phosphor); }

.tier {
  justify-self: start;
  padding: 1px 5px;
  border: var(--hair) solid var(--rule-hi);
  color: var(--ink-faint);
}
.tier.core { color: var(--phosphor-dim); border-color: var(--phosphor-dim); }
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
