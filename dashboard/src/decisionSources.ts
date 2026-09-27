/**
 * Retain slow requests across reads without stacking provider work.
 *
 * Once a source has produced a usable value, a later refresh that merely runs
 * past the read budget falls back to that last value. Hard failures still
 * reject, so provider outages remain visible instead of being masked by an
 * indefinitely cached response.
 */
export function createDecisionSources(budgetMs = 15000) {
  const requests = new Map<string, Promise<unknown>>()
  const lastGood = new Map<string, unknown>()

  return async function collect<T>(key: string, load: () => Promise<T>): Promise<T> {
    let request = requests.get(key) as Promise<T> | undefined
    if (!request) {
      const tracked = Promise.resolve()
        .then(load)
        .then(
          (value) => {
            lastGood.set(key, value)
            if (requests.get(key) === tracked) requests.delete(key)
            return value
          },
          (error: unknown) => {
            if (requests.get(key) === tracked) requests.delete(key)
            throw error
          },
        )
      request = tracked
      requests.set(key, request)
    }
    let timer: ReturnType<typeof setTimeout> | undefined
    const pending = new Error('Source still calculating')
    try {
      const value = await Promise.race([
        request,
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(pending), budgetMs)
        }),
      ])
      return value
    } catch (error) {
      if (error === pending && lastGood.has(key)) return lastGood.get(key) as T
      throw error
    } finally {
      clearTimeout(timer)
    }
  }
}
