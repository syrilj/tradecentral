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
    /** Renders a frosted glassmorphic surface. */
    glass?: boolean
  }>(),
  { meta: '', index: '', delay: 0, flush: false, live: false, glass: false },
)
</script>

<template>
  <section
    class="panel ticked rise"
    :class="{ flush, live, glass }"
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
/* Content-layer material: opaque, even-lit, hairline rule + one specular
   line along the top edge. No backdrop blur here — glass on cards produces
   the "blur pile"; Liquid Glass is reserved for floating chrome. */
.panel {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-lg);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.022), rgba(255, 255, 255, 0) 36px),
    var(--panel);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
  overflow: hidden;
  transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
}

.panel:hover {
  border-color: var(--rule-hi);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.45);
}

/* Opt-in: a panel that genuinely floats (popover-adjacent content) may take
   true Liquid Glass. Use sparingly — one or two per screen at most. */
.panel.glass {
  background: var(--glass-surface);
  border-color: var(--glass-border);
  box-shadow: var(--glass-shadow-sm), var(--glass-specular-subtle);
  backdrop-filter: var(--glass-blur-md);
  -webkit-backdrop-filter: var(--glass-blur-md);
}

.panel.live::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--phosphor);
  z-index: 2;
}

.head {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: var(--s2) var(--s3);
  min-height: 34px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0));
  border-bottom: var(--hair) solid var(--rule);
  flex: 0 0 auto;
}

.idx {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  color: var(--phosphor);
  background: var(--phosphor-wash);
  padding: 1px 7px;
  border-radius: var(--r-capsule);
  border: var(--hair) solid color-mix(in srgb, var(--phosphor) 30%, transparent);
  letter-spacing: 0.04em;
  font-weight: 700;
}

/* A panel title names the surface — it must never be cut short, so it wraps
   instead of inheriting the .label ellipsis. */
.lab {
  overflow: visible;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: 0.06em;
  line-height: 1.3;
  text-overflow: clip;
  text-transform: uppercase;
  white-space: normal;
}

/* Spacer */
.rule {
  flex: 1 1 auto;
  min-width: var(--s3);
  height: 0;
  opacity: 0;
}

.meta {
  overflow: visible;
  color: var(--ink-dim);
  font-family: var(--font-data);
  letter-spacing: 0.04em;
  font-size: var(--t-micro);
  font-variant-numeric: tabular-nums;
  line-height: 1.35;
  text-align: right;
  text-overflow: clip;
  white-space: normal;
  background: var(--void-lift);
  padding: 2px 8px;
  border-radius: var(--r-capsule);
  border: var(--hair) solid var(--rule);
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

@media (prefers-reduced-transparency: reduce) {
  .panel.glass {
    background: var(--panel-hi);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}
</style>
