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
  border-radius: var(--r-md);
  background: var(--panel);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  overflow: hidden;
  transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
}

.panel:hover {
  border-color: var(--rule-hi);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.45);
}

.panel.live::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--phosphor);
  z-index: 2;
}

.head {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: var(--s2) var(--s3);
  min-height: 32px;
  background: var(--panel-hi);
  border-bottom: var(--hair) solid var(--rule-faint);
  flex: 0 0 auto;
}

.idx {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  color: var(--phosphor);
  background: var(--phosphor-wash);
  padding: 1px 5px;
  border-radius: var(--r-xs);
  border: var(--hair) solid rgba(169, 196, 108, 0.2);
  letter-spacing: 0.04em;
  font-weight: 600;
}

.lab {
  color: var(--ink);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
}

/* Spacer */
.rule {
  flex: 1 1 auto;
  min-width: var(--s3);
  height: 0;
  opacity: 0;
}

.meta {
  color: var(--ink-dim);
  font-family: var(--font-data);
  letter-spacing: 0.04em;
  font-size: var(--t-micro);
  font-variant-numeric: tabular-nums;
  background: rgba(255, 255, 255, 0.02);
  padding: 2px 6px;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule-faint);
}

.body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: var(--s3);
}

.flush .body {
  padding: 0;
}
</style>
