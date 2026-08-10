import { ref, shallowRef, onScopeDispose, type Ref, type ShallowRef } from 'vue'
import { ApiError } from '@/api'

export interface Resource<T> {
  data: ShallowRef<T | null>
  error: Ref<string | null>
  loading: Ref<boolean>
  /** Wall-clock of the last successful load — drives the staleness readout. */
  fetchedAt: Ref<string | null>
  refresh: (opts?: { clear?: boolean }) => Promise<void>
  /** Drop cached data immediately (e.g. when the underlier changes). */
  clear: () => void
}

/**
 * Fetch-with-polling primitive.
 *
 * Deliberate choices:
 *  · A failed refresh keeps the previous `data` and sets `error`. Panels show
 *    the last good numbers *plus* a stale badge — blanking the screen on one
 *    dropped request is worse than showing aged data that is labelled aged.
 *  · Polling pauses while the tab is hidden, and fires once immediately on
 *    return, so a backgrounded desk does not accumulate a queue of requests.
 *  · In-flight requests are tracked so a slow response cannot overwrite a
 *    newer one (last-write-wins by request sequence, not by arrival order).
 *  · `refresh({ clear: true })` blanks data first so keyed UIs (symbol pages)
 *    cannot paint the previous key's payload as if it belonged to the new one.
 */
export function useResource<T>(
  loader: () => Promise<T>,
  opts: {
    intervalMs?: number
    immediate?: boolean
    /**
     * Optional activity gate for expensive resources. The caller remains in
     * charge of calling `refresh()` when the gate first becomes true; polling
     * and visibility refreshes stay dormant while it is false.
     */
    enabled?: () => boolean
  } = {},
): Resource<T> {
  const { intervalMs = 0, immediate = true, enabled = () => true } = opts

  const data = shallowRef<T | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(false)
  const fetchedAt = ref<string | null>(null)

  let seq = 0
  let timer: number | undefined
  let disposed = false

  let inFlight = false

  function clear(): void {
    data.value = null
    error.value = null
    fetchedAt.value = null
  }

  async function refresh(opts?: { clear?: boolean }): Promise<void> {
    const mine = ++seq
    inFlight = true
    loading.value = true
    if (opts?.clear) {
      // Invalidate immediately so consumers keyed on data identity cannot show
      // the previous response under a new selection.
      data.value = null
      error.value = null
    }
    try {
      const result = await loader()
      if (mine !== seq || disposed) return // a newer request already landed
      data.value = result
      error.value = null
      fetchedAt.value = new Date().toISOString()
    } catch (e) {
      if (mine !== seq || disposed) return
      error.value =
        e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e)
    } finally {
      if (mine === seq) {
        loading.value = false
        inFlight = false
      } else if (!disposed) {
        // A newer request owns the flag; if we were the last writer and got
        // superseded, the newer one will clear it.
      }
    }
  }

  function schedule(): void {
    if (!intervalMs || disposed) return
    stop()
    // Skip ticks while a request is still in flight so a slow backend cannot
    // stack fetches until the tab freezes.
    timer = window.setInterval(() => {
      if (enabled() && document.visibilityState === 'visible' && !inFlight) void refresh()
    }, intervalMs)
  }

  function stop(): void {
    if (timer !== undefined) {
      clearInterval(timer)
      timer = undefined
    }
  }

  function onVisible(): void {
    if (enabled() && document.visibilityState === 'visible') void refresh()
  }

  if (immediate && enabled()) void refresh()
  schedule()
  document.addEventListener('visibilitychange', onVisible)

  onScopeDispose(() => {
    disposed = true
    stop()
    document.removeEventListener('visibilitychange', onVisible)
  })

  return { data, error, loading, fetchedAt, refresh, clear }
}

/** Trailing-edge debounce for search-as-you-type. */
export function debounce<A extends unknown[]>(
  fn: (...args: A) => void,
  ms: number,
): (...args: A) => void {
  let t: number | undefined
  return (...args: A) => {
    if (t !== undefined) clearTimeout(t)
    t = window.setTimeout(() => fn(...args), ms)
  }
}
