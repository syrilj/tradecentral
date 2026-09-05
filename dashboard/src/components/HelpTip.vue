<script setup lang="ts">
/**
 * Hover/focus help bubble for dense desk panels.
 * Keeps the surface clean while answering "what do I do with this?"
 */
withDefaults(
  defineProps<{
    label?: string
    /** Longer explanation shown on hover/focus. */
    text: string
    /** Horizontal alignment of the popover bubble: 'center' (default), 'left', or 'right'. */
    align?: 'center' | 'left' | 'right'
    /** Vertical placement: 'top' (default) or 'bottom'. */
    placement?: 'top' | 'bottom'
  }>(),
  {
    label: undefined,
    align: 'center',
    placement: 'top',
  },
)
</script>

<template>
  <span class="help" tabindex="0" :aria-label="label || 'Help'">
    <span class="mark" aria-hidden="true">?</span>
    <span class="bubble" :class="[`align-${align}`, `placement-${placement}`]" role="tooltip">
      <strong v-if="label" class="title">{{ label }}</strong>
      <span class="body">{{ text }}</span>
    </span>
  </span>
</template>

<style scoped>
.help {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
  cursor: help;
  vertical-align: middle;
}
.mark {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: var(--hair) solid var(--glass-border-hi);
  color: var(--ink-faint);
  font: 700 var(--t-nano)/14px var(--font-display);
  text-align: center;
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur-sm);
  -webkit-backdrop-filter: var(--glass-blur-sm);
  transition: all var(--dur-fast) var(--ease-out);
}
.help:hover .mark,
.help:focus-visible .mark {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.bubble {
  position: absolute;
  z-index: var(--z-tooltip); /* above --z-overlay so a tooltip survives an open drawer */
  left: 50%;
  bottom: calc(100% + 8px);
  transform: translateX(-50%);
  width: min(300px, calc(100vw - 32px));
  max-width: 70vw;
  padding: 10px 12px;
  background: var(--glass-surface-hi);
  backdrop-filter: var(--glass-blur-md);
  -webkit-backdrop-filter: var(--glass-blur-md);
  border: var(--hair) solid var(--glass-border-hi);
  border-radius: var(--r-md);
  box-shadow: var(--glass-shadow-md), var(--glass-specular);
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition: opacity var(--dur-fast) var(--ease-out);
}
.bubble.align-left {
  left: 0;
  transform: none;
}
.bubble.align-right {
  left: auto;
  right: 0;
  transform: none;
}
.bubble.placement-bottom {
  bottom: auto;
  top: calc(100% + 8px);
}
.help:hover .bubble,
.help:focus-visible .bubble {
  opacity: 1;
  visibility: visible;
  pointer-events: auto;
}
/* Keep bubbles on-screen when the ? sits near edges */
.help:first-child .bubble:not(.align-right),
th .help .bubble:not(.align-right) {
  left: 0;
  transform: none;
}
th:last-child .help .bubble,
th:nth-last-child(2) .help .bubble {
  left: auto;
  right: 0;
  transform: none;
}
.title {
  display: block;
  margin-bottom: 4px;
  font: 700 10px var(--font-display);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--phosphor);
}
.body {
  display: block;
  color: var(--ink-soft);
  font-size: var(--t-small);
  line-height: 1.45;
  white-space: normal;
  text-transform: none;
  letter-spacing: 0;
  font-weight: 400;
  font-family: var(--font-ui);
}
</style>
