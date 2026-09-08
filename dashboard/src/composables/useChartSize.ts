import { computed, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

/**
 * Measure a chart host box with ResizeObserver (width + height).
 * rAF-coalesced so rapid resizes do not thrash Vue updates.
 */
export function useChartSize(
  hostRef: Ref<HTMLElement | null>,
  opts: { minW?: number; minH?: number; fallbackW?: number; fallbackH?: number } = {},
) {
  const minW = opts.minW ?? 240
  const minH = opts.minH ?? 160
  const fallbackW = opts.fallbackW ?? 640
  const fallbackH = opts.fallbackH ?? minH

  const width = ref(0)
  const height = ref(0)
  let ro: ResizeObserver | null = null
  let raf = 0

  function apply(w: number, h: number) {
    if (w > 0 && Math.round(w) !== width.value) width.value = Math.round(w)
    if (h > 0 && Math.round(h) !== height.value) height.value = Math.round(h)
  }

  function schedule(w: number, h: number) {
    if (raf) cancelAnimationFrame(raf)
    raf = requestAnimationFrame(() => {
      raf = 0
      apply(w, h)
    })
  }

  function observe(el: HTMLElement | null) {
    ro?.disconnect()
    if (!el) return
    const box = el.getBoundingClientRect()
    apply(box.width, box.height)
    if (typeof ResizeObserver === 'undefined') return
    if (!ro) {
      ro = new ResizeObserver((entries) => {
        const cr = entries[0]?.contentRect
        if (!cr) return
        schedule(cr.width, cr.height)
      })
    }
    ro.observe(el)
  }

  onMounted(() => observe(hostRef.value))

  /* A v-if can swap the host element out from under us. Without re-observing,
     the chart keeps sizing itself from the detached box — the viewBox stops
     matching the container and the drawing letterboxes inside dead gutters. */
  watch(hostRef, (el) => observe(el))

  onBeforeUnmount(() => {
    if (raf) cancelAnimationFrame(raf)
    ro?.disconnect()
    ro = null
  })

  const W = computed(() => Math.max(minW, width.value || fallbackW))
  const H = computed(() => Math.max(minH, height.value || fallbackH))

  return { width, height, W, H }
}
