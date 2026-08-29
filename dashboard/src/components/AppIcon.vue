<script setup lang="ts">
withDefaults(
  defineProps<{
    name: string
    size?: number
    stroke?: number
  }>(),
  {
    size: 18,
    stroke: 1.7,
  },
)
</script>

<template>
  <svg
    class="app-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    :stroke-width="stroke"
    stroke="currentColor"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <template v-if="name === 'desk'">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <path d="M14 17.5h7M17.5 14v7" />
    </template>
    <template v-else-if="name === 'market'">
      <path d="M3 19h18" />
      <path d="M4.5 16.5 9 12l3 2.5 7.5-8" />
      <path d="M16.5 6.5H19v2.5" />
    </template>
    <template v-else-if="name === 'options'">
      <path d="M4 7.5 12 3l8 4.5-8 4.5-8-4.5Z" />
      <path d="M4 12 12 16.5 20 12" />
      <path d="M4 16.5 12 21l8-4.5" />
    </template>
    <template v-else-if="name === 'chain'">
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </template>
    <template v-else-if="name === 'flow'">
      <path d="M3 12h3l2.2-6 4 12 2.4-7 1.7 4H21" />
    </template>
    <template v-else-if="name === 'regime'">
      <!-- A distribution sitting across a threshold: the flip line, and mass
           on either side of it. -->
      <path d="M3 13h18" stroke-dasharray="3 2.5" />
      <path d="M3 19c4 0 3.5-13 9-13s5 13 9 13" />
      <path d="M12 3v3" />
    </template>
    <template v-else-if="name === 'drift'">
      <path d="M3 12h18" />
      <path d="M6 12V6.5M9 12V8M12 12V5M15 12V8.5M18 12V7" />
      <path d="M6 12v5.5M9 12v4M12 12v7M15 12v3.5M18 12v5" />
      <path d="M3 14c4 1 5-3 9-1s5 1 9-1" />
    </template>
    <template v-else-if="name === 'research'">
      <path d="M9 3h6" />
      <path d="M10 3v6.5L4.6 18a2.2 2.2 0 0 0 1.9 3.3h11a2.2 2.2 0 0 0 1.9-3.3L14 9.5V3" />
      <path d="M8 16h8" />
    </template>
    <template v-else-if="name === 'home'">
      <path d="m3.5 10.5 8.5-7 8.5 7" />
      <path d="M5.5 9v11h13V9M9.5 20v-6h5v6" />
    </template>
    <template v-else-if="name === 'sectors'">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 3.5V12h8.5M12 12l-6 6" />
    </template>
    <template v-else-if="name === 'pulse'">
      <circle cx="12" cy="12" r="9" />
      <path d="M4.5 12H8l2-4.5 3.2 9 2.1-4.5h4.2" />
    </template>
    <template v-else-if="name === 'momentum'">
      <path d="M4 20V15M9 20V11M14 20V7" />
      <path d="m5 10 5-5 3 3 6-6M15 2h4v4" />
    </template>
    <template v-else-if="name === 'suggest'">
      <path d="M12 3v4" />
      <circle cx="12" cy="12" r="3.2" />
      <path d="M5 12H3M21 12h-2M7.1 7.1 5.7 5.7M16.9 7.1l1.4-1.4" />
      <path d="M4 19h7M13 19h7" />
      <path d="M11 17.2 12 19l1-1.8" />
    </template>
    <template v-else-if="name === 'fintel'">
      <path d="M3 20h18M5 20V9h14v11M8 20v-7M12 20v-7M16 20v-7" />
      <path d="m4 9 8-5 8 5" />
    </template>
    <template v-else-if="name === 'calculator'">
      <rect x="5" y="3" width="14" height="18" rx="1.5" />
      <path d="M8 7h8M8 11h2M12 11h2M16 11h0.01M8 15h2M12 15h2M16 15h0.01M8 18h2M12 18h2" />
    </template>
    <template v-else-if="name === 'insiders'">
      <circle cx="9" cy="8" r="2.4" />
      <path d="M4.5 18v-1.2A3.8 3.8 0 0 1 8.3 13h1.4" />
      <path d="M13 8h7M13 12h7M13 16h5" />
    </template>
    <template v-else-if="name === 'evolution'">
      <circle cx="5" cy="12" r="2" />
      <circle cx="19" cy="6" r="2" />
      <circle cx="19" cy="18" r="2" />
      <path d="M7 12h3a4 4 0 0 0 4-4 2 2 0 0 1 2-2h1M7 12h3a4 4 0 0 1 4 4 2 2 0 0 0 2 2h1" />
    </template>
    <template v-else-if="name === 'adaptive'">
      <path d="M4 6h6M14 6h6M4 12h10M18 12h2M4 18h3M11 18h9" />
      <circle cx="12" cy="6" r="2" />
      <circle cx="16" cy="12" r="2" />
      <circle cx="9" cy="18" r="2" />
    </template>
    <template v-else-if="name === 'graph'">
      <circle cx="5" cy="12" r="2" />
      <circle cx="12" cy="5" r="2" />
      <circle cx="19" cy="9" r="2" />
      <circle cx="15" cy="19" r="2" />
      <path d="m6.5 10.5 4-4M14 5.8l3.2 2.4M18.3 10.8l-2.6 6.3M6.8 13.3l6.4 4.4" />
    </template>
    <template v-else-if="name === 'changepoints'">
      <path d="M3 18h18M5 15l4-4 3 2M15 10l4-5" />
      <path d="M13.5 4v14" stroke-dasharray="2 2" />
    </template>
    <template v-else-if="name === 'kalman'">
      <path d="M3 17.5c3.5 0 4-9 7.5-9s4 9 7.5 9" />
      <path d="M3 20.5h18" />
      <path d="M3.5 13.5 8 11l4 3.5 7-8" />
    </template>
    <template v-else-if="name === 'cloud'">
      <path d="M7 18h10a4 4 0 0 0 .7-7.9A6 6 0 0 0 6.2 9 4.5 4.5 0 0 0 7 18Z" />
      <path d="m9.5 13 2.5-2.5 2.5 2.5M12 10.5V17" />
    </template>
    <template v-else-if="name === 'more'">
      <circle cx="5" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1" fill="currentColor" stroke="none" />
    </template>
    <template v-else-if="name === 'search'">
      <circle cx="10.75" cy="10.75" r="6.75" />
      <path d="m16 16 4.25 4.25" />
    </template>
    <template v-else-if="name === 'density'">
      <path d="M4 6h16M4 12h16M4 18h16" />
      <path d="M7 4v4M12 10v4M17 16v4" />
    </template>
    <template v-else-if="name === 'alert'">
      <path d="m12 3 9 17H3L12 3Z" />
      <path d="M12 9v4M12 17h.01" />
    </template>
    <template v-else-if="name === 'chevron'">
      <path d="m7 10 5 5 5-5" />
    </template>
    <template v-else-if="name === 'external'">
      <path d="M14 4h6v6" />
      <path d="m20 4-9 9" />
      <path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6" />
    </template>
    <template v-else-if="name === 'arrow-right'">
      <path d="M4 12h16" />
      <path d="m14 6 6 6-6 6" />
    </template>
    <template v-else-if="name === 'arrow-left'">
      <path d="M20 12H4" />
      <path d="m10 6-6 6 6 6" />
    </template>
    <template v-else-if="name === 'arrow-down'">
      <path d="M12 4v16" />
      <path d="m6 14 6 6 6-6" />
    </template>
    <template v-else-if="name === 'lock'">
      <rect x="4" y="10" width="16" height="11" rx="1.5" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
      <path d="M12 14v3" />
    </template>
    <template v-else-if="name === 'session'">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7v5l3.5 2" />
    </template>
    <template v-else-if="name === 'shield'">
      <path d="M12 3 20 6v5c0 5-3 8.2-8 10-5-1.8-8-5-8-10V6l8-3Z" />
      <path d="m8.5 12 2.2 2.2 4.8-5" />
    </template>
    <template v-else-if="name === 'eye'">
      <path d="M2.5 12s3.2-6 9.5-6 9.5 6 9.5 6-3.2 6-9.5 6-9.5-6-9.5-6Z" />
      <circle cx="12" cy="12" r="2.5" />
    </template>
    <template v-else-if="name === 'eye-off'">
      <path d="m4 4 16 16" />
      <path d="M9.8 6.3A9.7 9.7 0 0 1 12 6c6.3 0 9.5 6 9.5 6a13.5 13.5 0 0 1-2.4 3.1" />
      <path d="M6.2 7.2C3.7 9 2.5 12 2.5 12s3.2 6 9.5 6c1 0 1.9-.2 2.7-.4" />
    </template>
    <template v-else-if="name === 'user'">
      <circle cx="12" cy="8" r="4" />
      <path d="M5 20a7 7 0 0 1 14 0" />
    </template>
    <template v-else-if="name === 'user-check'">
      <circle cx="10" cy="8" r="4" />
      <path d="M3 20a7 7 0 0 1 11.5-5.3" />
      <path d="m15 15 2.5 2.5 4.5-4.5" />
    </template>
    <template v-else-if="name === 'terminal'">
      <path d="m4 17 6-5-6-5" />
      <path d="M12 19h8" />
    </template>
    <template v-else-if="name === 'signout'">
      <path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5" />
      <path d="M14 8l4 4-4 4" />
      <path d="M8 12h10" />
    </template>
    <template v-else-if="name === 'database'">
      <ellipse cx="12" cy="5.5" rx="8" ry="3" />
      <path d="M4 5.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
      <path d="M4 11.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
    </template>
    <template v-else-if="name === 'gate'">
      <path d="M5 21V6l7-3 7 3v15" />
      <path d="M9 21v-8h6v8M3 21h18" />
    </template>
    <template v-else-if="name === 'radar'">
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="4" />
      <path d="M12 12 18.5 5.5M12 3v2M21 12h-2M12 21v-2M3 12h2" />
    </template>
    <template v-else-if="name === 'stack'">
      <path d="M4 6.5 12 3l8 3.5-8 3.5-8-3.5Z" />
      <path d="M4 12h16M4 17.5h16" />
    </template>
    <template v-else-if="name === 'globe'">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17" />
      <path
        d="M12 3.5c2.4 2.2 3.7 5.2 3.7 8.5s-1.3 6.3-3.7 8.5c-2.4-2.2-3.7-5.2-3.7-8.5s1.3-6.3 3.7-8.5Z"
      />
    </template>
    <template v-else-if="name === 'absorption'">
      <path d="M4 19h16" />
      <path d="M4 12h16" stroke-dasharray="2 2" />
      <path d="m8 6 4 4 4-4" />
      <path d="M12 2v8" />
    </template>
    <template v-else>
      <circle cx="12" cy="12" r="8" />
    </template>
  </svg>
</template>

<style scoped>
.app-icon {
  display: block;
  flex: 0 0 auto;
}
</style>
