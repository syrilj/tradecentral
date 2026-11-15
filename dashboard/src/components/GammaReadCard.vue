<script setup lang="ts">
/**
 * One pre-trade gamma read. A missing measurement is an em dash plus the
 * reason it was withheld. The value slot is never a fabricated zero.
 */
import type { ReadTone } from '@/gammaResistance'

defineProps<{
  label: string
  kicker: string
  value: string | null
  sub: string | null
  note: string | null
  missing: boolean
  missingReason: string
  tone: ReadTone
  testId: string
}>()
</script>

<template>
  <article class="read" :class="[tone, { missing }]" :data-testid="testId" :aria-label="label">
    <header class="read-head">
      <span class="kicker">{{ kicker }}</span>
      <h3>{{ label }}</h3>
    </header>
    <p v-if="missing" class="value missing-value">—</p>
    <p v-else class="value fig">{{ value }}</p>
    <p v-if="missing" class="reason">{{ missingReason }}</p>
    <p v-else-if="sub" class="sub fig">{{ sub }}</p>
    <p v-if="note" class="note">{{ note }}</p>
  </article>
</template>

<style scoped>
.read {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  min-width: 0;
  padding: var(--s4);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-md);
  background: var(--panel-hi);
}
.read.call {
  border-top: 2px solid var(--call);
}
.read.put {
  border-top: 2px solid var(--put);
}
.read.flip {
  border-top: 2px solid var(--warn);
}
.read.abs {
  border-top: 2px solid var(--ink-soft);
}
.read-head h3 {
  margin: 0;
  font-size: var(--t-body);
  font-weight: 560;
  color: var(--ink);
}
.kicker {
  display: block;
  margin-bottom: var(--s1);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  color: var(--ink-dim);
  text-transform: uppercase;
}
.value {
  margin: 0;
  font-size: var(--t-title, 1.6rem);
  line-height: 1.1;
  color: var(--ink);
}
.missing-value,
.reason {
  color: var(--ink-dim);
}
.reason,
.sub,
.note {
  margin: 0;
  font-size: var(--t-tiny);
  line-height: 1.45;
}
.sub {
  color: var(--ink-soft);
}
.note {
  color: var(--ink-dim);
}
</style>
