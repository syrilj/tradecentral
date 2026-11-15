<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import TradeCentralMark from '@/components/TradeCentralMark.vue'

const route = useRoute()

onMounted(() => document.body.classList.add('edge-public-mode'))
onUnmounted(() => document.body.classList.remove('edge-public-mode'))
</script>

<template>
  <main class="missing">
    <TradeCentralMark :size="28" />
    <p class="missing-kicker">No workspace</p>
    <h1>This address is not a TradeCentral screen.</h1>
    <p class="missing-copy">
      <code>{{ route.fullPath }}</code>
      does not match a research workspace. TradeCentral reads dealer positioning, options flow, and
      the evidence behind them. It does not route orders.
    </p>
    <nav class="missing-links" aria-label="Continue">
      <RouterLink to="/">Overview</RouterLink>
      <RouterLink :to="{ name: 'auth', query: { mode: 'signin', redirect: '/flow' } }"
        >Sign in</RouterLink
      >
      <RouterLink :to="{ name: 'waitlist', query: { redirect: '/flow' } }"
        >Request operator access</RouterLink
      >
    </nav>
  </main>
</template>

<style scoped>
.missing {
  --ink: #18181b;
  --ink-dim: #565660;
  --rule: #e4e3de;
  min-height: 100vh;
  display: grid;
  align-content: center;
  justify-items: start;
  gap: 14px;
  max-width: 640px;
  margin: 0 auto;
  padding: 48px 24px 80px;
  color: var(--ink);
  background: #fbfbf8;
}
.missing-kicker {
  margin: 0;
  font-family: var(--font-data);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-dim);
}
h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: clamp(32px, 5vw, 48px);
  line-height: 1.05;
  letter-spacing: -0.03em;
}
.missing-copy {
  margin: 0;
  max-width: 52ch;
  color: var(--ink-dim);
  line-height: 1.5;
}
code {
  font-family: var(--font-data);
  color: var(--ink);
}
.missing-links {
  display: flex;
  flex-wrap: wrap;
  gap: 16px 22px;
  margin-top: 8px;
}
.missing-links a {
  color: var(--ink);
  font-weight: 650;
}
</style>
