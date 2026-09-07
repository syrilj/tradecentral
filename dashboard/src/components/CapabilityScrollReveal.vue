<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import AppIcon from './AppIcon.vue'

gsap.registerPlugin(ScrollTrigger)

/**
 * Editorial capability reveal: five capability badges accompany the
 * signature statement. Clean, robust, accessible typography that never breaks
 * page flow or overlaps on screen resize.
 */
const ITEMS = [
  { icon: 'radar', label: 'Market' },
  { icon: 'options', label: 'Options' },
  { icon: 'gate', label: 'Governance' },
  { icon: 'calculator', label: 'Model lab' },
  { icon: 'desk', label: 'Workspaces' },
] as const

const SEGMENTS = [
  'Market structure,',
  'options and flow,',
  'research governance,',
  'a live model lab,',
  'and workspaces',
] as const
const CLOSING = 'all unified in TradeCentral.'
const fullSentence = `${SEGMENTS.join(' ')} ${CLOSING}`

const sectionRef = ref<HTMLElement | null>(null)
let ctx: gsap.Context | undefined

onMounted(() => {
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (prefersReducedMotion || !sectionRef.value) return

  ctx = gsap.context(() => {
    gsap.from('.capability-badge', {
      opacity: 0,
      y: 16,
      duration: 0.5,
      stagger: 0.08,
      ease: 'power2.out',
      scrollTrigger: {
        trigger: sectionRef.value,
        start: 'top 85%',
        toggleActions: 'play none none none',
        once: true,
      },
    })

    gsap.from('.capability-headline .hl-part, .capability-headline .hl-closing', {
      opacity: 0,
      y: 20,
      duration: 0.6,
      stagger: 0.06,
      ease: 'power2.out',
      scrollTrigger: {
        trigger: sectionRef.value,
        start: 'top 80%',
        toggleActions: 'play none none none',
        once: true,
      },
    })
  }, sectionRef.value)
})

onUnmounted(() => {
  ctx?.revert()
})
</script>

<template>
  <section ref="sectionRef" class="capability-reveal" aria-label="Capabilities overview">
    <div class="capability-content">
      <div class="capability-badges" aria-hidden="true">
        <span v-for="item in ITEMS" :key="item.icon" class="capability-badge">
          <AppIcon :name="item.icon" :size="15" />
          <span class="badge-label">{{ item.label }}</span>
        </span>
      </div>

      <h2 class="capability-headline" :aria-label="fullSentence">
        <span class="hl-part">Market structure, </span>
        <span class="hl-part">options and flow, </span>
        <span class="hl-part">research governance, </span>
        <span class="hl-part">a live model lab, </span>
        <span class="hl-part">and workspaces</span>
        <span class="hl-closing"> all unified in TradeCentral.</span>
      </h2>
    </div>
  </section>
</template>

<style scoped>
.capability-reveal {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: clamp(60px, 8vw, 110px) 24px;
  text-align: center;
  width: 100%;
}

.capability-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: clamp(24px, 3.5vw, 40px);
  max-width: 960px;
  margin-inline: auto;
}

.capability-badges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: clamp(8px, 1.5vw, 14px);
}

.capability-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border: var(--hair) solid var(--rule-hi);
  border-radius: var(--r-sm, 4px);
  background: var(--void);
  color: var(--phosphor);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.badge-label {
  font-family: var(--font-data);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-soft);
}

.capability-headline {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: clamp(28px, 3.8vw, 48px);
  line-height: 1.22;
  letter-spacing: -0.02em;
  color: var(--ink);
}

.hl-part {
  display: inline;
  color: var(--ink);
}

.hl-closing {
  display: inline;
  color: var(--ink-dim);
  font-style: normal;
}

@media (max-width: 640px) {
  .capability-reveal {
    padding: 48px 16px;
  }
  .capability-badges {
    gap: 6px;
  }
  .capability-badge {
    padding: 4px 10px;
    font-size: 10px;
  }
}
</style>
