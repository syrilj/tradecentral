<script setup lang="ts">
/**
 * Instrument skeleton for the Brief: the Today tape, and the call / range
 * cards while those reads have not landed. Flat 1px rules, no gradient,
 * no motion when the reader asks for less.
 */
withDefaults(
  defineProps<{
    kind?: 'tape' | 'call' | 'range'
  }>(),
  { kind: 'tape' },
)
</script>

<template>
  <div
    v-if="kind === 'tape'"
    class="sk sk-tape"
    role="status"
    aria-busy="true"
    aria-live="polite"
  >
    <span class="sr-only">Loading today's tape</span>
    <span v-for="n in 6" :key="n" class="sk-cell" aria-hidden="true">
      <i class="bar w-sym" />
      <i class="bar w-name" />
      <i class="bar w-px" />
    </span>
    <i class="bar w-line" aria-hidden="true" />
  </div>

  <div v-else class="sk sk-read" role="status" aria-busy="true" aria-live="polite">
    <span class="sr-only">{{
      kind === 'call' ? 'Loading the directional read' : 'Loading the range read'
    }}</span>
    <i class="bar w-kicker" aria-hidden="true" />
    <i class="bar w-wide" aria-hidden="true" />
    <i class="bar w-mid" aria-hidden="true" />
    <i class="bar w-mid" aria-hidden="true" />
    <span class="sk-figs" aria-hidden="true">
      <i class="bar w-fig" />
      <i class="bar w-fig" />
      <i class="bar w-fig" />
    </span>
  </div>
</template>

<style scoped>
.sk {
  min-width: 0;
}

.sr-only {
  position: absolute;
  inline-size: 1px;
  block-size: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.sk-tape {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--s2);
}

.sk-cell {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  padding: var(--s2) var(--s3);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--panel);
}

.sk-read {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  min-block-size: 148px;
  padding-block: var(--s2);
}

.sk-figs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s2);
  margin-block-start: var(--s2);
}

.bar {
  display: block;
  block-size: 8px;
  border-radius: 1px;
  background: var(--panel-hi);
  animation: sk-pulse 1.6s ease-in-out infinite;
}

.w-sym {
  inline-size: 42%;
  block-size: 10px;
}

.w-name {
  inline-size: 68%;
}

.w-px {
  inline-size: 54%;
  margin-block-start: 4px;
}

.w-line {
  grid-column: 1 / -1;
  inline-size: 72%;
  block-size: 10px;
  margin-block-start: var(--s1);
}

.w-kicker {
  inline-size: 28%;
  block-size: 10px;
}

.w-wide {
  inline-size: 86%;
  block-size: 14px;
}

.w-mid {
  inline-size: 64%;
}

.w-fig {
  inline-size: 100%;
  block-size: 18px;
}

@keyframes sk-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}

@media (max-width: 900px) {
  .sk-tape {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 520px) {
  .sk-tape {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (prefers-reduced-motion: reduce) {
  .bar {
    animation: none;
  }
}
</style>
