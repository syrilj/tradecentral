<script setup lang="ts">
withDefaults(
  defineProps<{
    label?: string
    compact?: boolean
  }>(),
  { label: 'Loading', compact: false },
)
</script>

<template>
  <div class="loading" :class="{ compact }" role="status" aria-live="polite">
    <span class="orb" aria-hidden="true">
      <i /><i /><i />
    </span>
    <span class="label text">{{ label }}</span>
  </div>
</template>

<style scoped>
.loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s3);
  min-height: 160px;
  width: 100%;
  padding: var(--s5);
  color: var(--ink-dim);
  box-sizing: border-box;
}
.loading.compact {
  min-height: 48px;
  flex-direction: row;
  padding: var(--s3);
}
.orb {
  position: relative;
  width: 28px;
  height: 28px;
}
.orb i {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 1.5px solid transparent;
  border-top-color: var(--phosphor);
  animation: spin var(--dur-orb) linear infinite;
}
.orb i:nth-child(2) {
  inset: 4px;
  border-top-color: var(--phosphor-dim);
  animation-duration: var(--dur-orb-mid);
  animation-direction: reverse;
}
.orb i:nth-child(3) {
  inset: 9px;
  border-top-color: var(--ink-faint);
  animation-duration: var(--dur-orb-fast);
}
.text {
  letter-spacing: 0.12em;
  color: var(--ink-faint);
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
