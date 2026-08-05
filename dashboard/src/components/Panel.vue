<script setup lang="ts">
/**
 * The framing primitive. Every block of data sits in one of these.
 * Corner registration ticks instead of a border radius — the panel is a
 * viewfinder onto a measurement, not a card.
 */
withDefaults(
  defineProps<{
    label: string
    /** Right-aligned annotation in the header rule: counts, as-of, source. */
    meta?: string
    /** Ordinal shown before the label, e.g. "03". Purely typographic rhythm. */
    index?: string
    /** Staggered entrance delay in ms. */
    delay?: number
    /** Removes inner padding for edge-to-edge tables and charts. */
    flush?: boolean
    /** Renders a phosphor left edge — marks the panel as live-polling. */
    live?: boolean
  }>(),
  { meta: '', index: '', delay: 0, flush: false, live: false },
)
</script>

<template>
  <section
    class="panel ticked rise"
    :class="{ flush, live }"
    :style="{ animationDelay: `${delay}ms` }"
  >
    <header class="head">
      <span v-if="index" class="idx fig">{{ index }}</span>
      <h2 class="label lab">{{ label }}</h2>
      <span class="rule" aria-hidden="true" />
      <span v-if="meta" class="label meta">{{ meta }}</span>
      <slot name="action" />
    </header>
    <div class="body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.panel {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border: var(--hair) solid var(--rule);
  padding: var(--s1);
  /* Soft depth only — not a floating card */
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.18);
  transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
}

.panel:hover {
  border-color: var(--rule-hi);
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.28);
}

.panel.live::before {
  content: '';
  position: absolute;
  left: -1px;
  top: 18%;
  bottom: 18%;
  width: 2px;
  background: var(--phosphor);
}

.head {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: 4px 6px;
  min-height: 26px;
  flex: 0 0 auto;
}

.idx {
  font-size: var(--t-micro);
  color: var(--phosphor);
  letter-spacing: 0.05em;
  font-weight: 700;
}

.lab {
  color: var(--ink);
  font-weight: 700;
  letter-spacing: 0.05em;
}

/* Quiet spacer — no dashed rule chrome. */
.rule {
  flex: 1 1 auto;
  min-width: var(--s3);
  height: 0;
  opacity: 0;
}

.meta {
  color: var(--ink-dim);
  letter-spacing: 0.06em;
  font-size: var(--t-micro);
  font-variant-numeric: tabular-nums;
}

.body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 0 var(--s2) var(--s2);
}

.flush .body {
  padding: 0;
}
</style>
