<script setup lang="ts">
import { onUnmounted, ref } from 'vue'

/**
 * Owns the 1-second UTC tick locally so the app shell's template — which used
 * to bind a per-second `clock` ref and re-render its whole tree every tick —
 * stays static between route/data changes. Visual output is unchanged:
 * `HH:MM:SS` from `toISOString().slice(11, 19)`, refreshed at 1s cadence.
 */
const now = ref(utcNow())
let tick: number | undefined

function utcNow(): string {
  return new Date().toISOString().slice(11, 19)
}

tick = window.setInterval(() => (now.value = utcNow()), 1000)

onUnmounted(() => {
  if (tick !== undefined) clearInterval(tick)
})
</script>

<template>
  <span>{{ now }}</span>
</template>
