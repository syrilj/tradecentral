<script setup lang="ts">
/** A single labelled figure. The atom of the instrument strip and stat rows. */
withDefaults(
  defineProps<{
    label: string
    value: string
    /** Colour semantics for signed quantities. */
    tone?: 'pos' | 'neg' | 'flat' | 'accent' | 'default'
    /** Secondary line under the figure — units, as-of, denominator. */
    sub?: string
    size?: 'sm' | 'md' | 'lg'
  }>(),
  { tone: 'default', sub: '', size: 'md' },
)
</script>

<template>
  <div class="readout" :class="[`t-${tone}`, `s-${size}`]">
    <span class="label">{{ label }}</span>
    <span class="val fig">{{ value }}</span>
    <span v-if="sub" class="sub label">{{ sub }}</span>
  </div>
</template>

<style scoped>
.readout {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.val {
  font-weight: 500;
  color: var(--ink);
  line-height: 1.1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.s-sm .val { font-size: var(--t-small); }
.s-md .val { font-size: var(--t-fig); }
.s-lg .val { font-size: var(--t-fig-lg); font-weight: 400; letter-spacing: -0.03em; }

.t-pos .val { color: var(--long); }
.t-neg .val { color: var(--short); }
.t-flat .val { color: var(--ink-dim); }
.t-accent .val { color: var(--phosphor); }

.sub {
  color: var(--ink-dim);
  letter-spacing: 0.06em;
}
</style>
