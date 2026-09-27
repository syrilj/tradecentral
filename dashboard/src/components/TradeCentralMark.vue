<script setup lang="ts">
withDefaults(
  defineProps<{
    size?: number
  }>(),
  {
    size: 30,
  },
)
</script>

<template>
  <svg
    class="tc-mark"
    :width="size"
    :height="size"
    viewBox="0 0 32 32"
    fill="none"
    role="img"
    aria-label="TradeCentral"
  >
    <path class="tc-mark__frame" d="M5.5 4.5v23h22" />
    <path class="tc-mark__bar" d="M9 23v-5M14 23V11M19 23V7M24 23V14" />
    <path class="tc-mark__trace" d="m8.5 16.5 5-6 5 2.5 7-8" />
    <path class="tc-mark__trace" d="m22 5h3.5v3.5" />
  </svg>
</template>

<style scoped>
.tc-mark {
  display: block;
  flex: 0 0 auto;
  overflow: visible;
}

.tc-mark__frame {
  stroke: currentColor;
  stroke-width: 1.25;
  opacity: 0.42;
}

.tc-mark__bar {
  stroke: currentColor;
  stroke-width: 3;
  stroke-linecap: square;
}

.tc-mark__trace {
  stroke: var(--call-hi);
  stroke-width: 1.5;
  stroke-linecap: square;
  stroke-linejoin: miter;
}
</style>
