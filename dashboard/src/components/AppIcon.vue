<script setup lang="ts">
withDefaults(defineProps<{
  name: string
  size?: number
  stroke?: number
}>(), {
  size: 18,
  stroke: 1.7,
})
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
    <template v-else-if="name === 'flow'">
      <path d="M3 12h3l2.2-6 4 12 2.4-7 1.7 4H21" />
    </template>
    <template v-else-if="name === 'research'">
      <path d="M9 3h6" />
      <path d="M10 3v6.5L4.6 18a2.2 2.2 0 0 0 1.9 3.3h11a2.2 2.2 0 0 0 1.9-3.3L14 9.5V3" />
      <path d="M8 16h8" />
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
