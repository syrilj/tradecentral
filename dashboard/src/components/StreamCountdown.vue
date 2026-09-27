<script setup lang="ts">
import { onUnmounted, ref } from 'vue'

/**
 * Owns the 1-second live-stream countdown tick. Keeping the tick (and its
 * reactive text) isolated here means OptionsView's large template is not
 * re-rendered every second during live mode — previously a countdown ref read
 * in the view's template forced a full-view render per tick. Emits `fire` when
 * the interval elapses; the parent decides what to refresh.
 */
const props = defineProps<{ intervalSec: number }>()
const emit = defineEmits<{ fire: [] }>()

const remaining = ref(props.intervalSec)
let timer: number | undefined

timer = window.setInterval(() => {
  if (remaining.value > 1) {
    remaining.value -= 1
  } else {
    remaining.value = props.intervalSec
    emit('fire')
  }
}, 1000)

onUnmounted(() => {
  if (timer !== undefined) clearInterval(timer)
})
</script>

<template>
  <span>({{ remaining }}s)</span>
</template>
