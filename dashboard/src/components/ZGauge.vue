<script setup lang="ts">
import { computed } from 'vue'

/**
 * Flat z-scale for the crypto view: a horizontal track from `min` to `max`
 * with the neutral band (|z| < cutoff) shaded and a single marker at the
 * reading. No glow, no gradient — a ruler, not a meter.
 */

const props = withDefaults(
  defineProps<{
    value: number | null
    cutoff: number
    min?: number
    max?: number
    bandLabel?: string
  }>(),
  { min: -2, max: 2, bandLabel: 'chop' },
)

function clampPct(v: number): number {
  const lo = Math.min(props.min, props.max)
  const hi = Math.max(props.min, props.max)
  const t = Math.min(1, Math.max(0, (v - lo) / (hi - lo)))
  return t * 100
}

const markerPct = computed(() =>
  props.value == null ? null : Math.min(99, Math.max(1, clampPct(props.value))),
)
const bandLeft = computed(() => clampPct(-props.cutoff))
const bandRight = computed(() => 100 - clampPct(props.cutoff))
const zeroPct = computed(() => clampPct(0))

const ticks = computed(() => {
  const lo = Math.min(props.min, props.max)
  const hi = Math.max(props.min, props.max)
  const out: number[] = []
  for (let t = Math.ceil(lo); t <= Math.floor(hi); t++) out.push(t)
  return out
})
</script>

<template>
  <div class="zgauge" role="img" :aria-label="`z-scale, reading ${value ?? 'unmeasured'}`">
    <div class="zg-track">
      <span class="zg-band" :style="{ left: `${bandLeft}%`, right: `${bandRight}%` }">
        <span class="zg-band-lab">{{ bandLabel }}</span>
      </span>
      <span class="zg-zero" :style="{ left: `${zeroPct}%` }" />
      <span
        v-for="t in ticks"
        :key="t"
        class="zg-tick"
        :class="{ major: t === 0 }"
        :style="{ left: `${clampPct(t)}%` }"
      />
      <span v-if="markerPct != null" class="zg-marker" :style="{ left: `${markerPct}%` }" />
      <span v-else class="zg-absent">unmeasured</span>
    </div>
    <div class="zg-scale">
      <span>{{ min }}</span>
      <span class="zg-cutoff">−{{ cutoff }}</span>
      <span>0</span>
      <span class="zg-cutoff">+{{ cutoff }}</span>
      <span>{{ max }}</span>
    </div>
  </div>
</template>

<style scoped>
.zgauge {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.zg-track {
  position: relative;
  height: 26px;
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-xs);
  background: var(--panel);
}

.zg-band {
  position: absolute;
  top: var(--hair);
  bottom: var(--hair);
  background: var(--wash-2);
  border-left: var(--hair) solid var(--rule-faint);
  border-right: var(--hair) solid var(--rule-faint);
}

.zg-zero {
  position: absolute;
  top: 0;
  bottom: 0;
  width: var(--hair);
  background: var(--rule-hi);
}

.zg-tick {
  position: absolute;
  top: 50%;
  width: 3px;
  height: 3px;
  transform: translate(-50%, -50%);
  background: var(--ink-ghost);
}
.zg-tick.major {
  width: 5px;
  height: 5px;
  background: var(--ink-dim);
}

.zg-marker {
  position: absolute;
  top: 2px;
  bottom: 2px;
  width: 3px;
  transform: translateX(-50%);
  background: var(--phosphor);
  border-radius: 1px;
}

.zg-absent {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-micro);
}

.zg-scale {
  display: flex;
  justify-content: space-between;
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  line-height: 1;
}
.zg-scale > span:last-child {
  transform: translateX(50%);
}
.zg-scale > span:first-child {
  transform: translateX(-50%);
}

.zg-band-lab {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
</style>
