<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { formatMarketCountdown } from '@/marketSession'

/**
 * Ticks locally so the shell's template only re-renders this countdown text
 * each second, instead of the whole strip (previously driven by reading the
 * shell's per-second `clock` ref inside a computed).
 */
const props = defineProps<{
  nextTransitionUtc: string | null | undefined
  nextTransition: string | null | undefined
}>()

const nowMs = ref(Date.now())
let tick: number | undefined

tick = window.setInterval(() => (nowMs.value = Date.now()), 1000)

onUnmounted(() => {
  if (tick !== undefined) clearInterval(tick)
})

const label = computed(() =>
  formatMarketCountdown(props.nextTransitionUtc, props.nextTransition, nowMs.value),
)
</script>

<template>
  <span>{{ label }}</span>
</template>
