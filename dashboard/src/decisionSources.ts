/** Retain slow requests across reads without stacking provider work. */
export function createDecisionSources(budgetMs = 2500) {
  const requests = new Map<string, Promise<unknown>>()
  return async function collect<T>(key: string, load: () => Promise<T>): Promise<T> {
    let request = requests.get(key) as Promise<T> | undefined
    if (!request) {
      request = Promise.resolve().then(load)
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
      if (requests.get(key) === request) requests.delete(key)
      return value
    } catch (error) {
      if (error !== pending && requests.get(key) === request) requests.delete(key)
      throw error
    } finally {
      clearTimeout(timer)
    }
  }
}
