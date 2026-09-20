import { describe, it, expect, vi } from 'vitest'
import { createDecisionSources } from '../decisionSources'

describe('bounded decision collection', () => {
  it('returns promptly and consumes the same slow request on the next read', async () => {
    vi.useFakeTimers()
    try {
      const collect = createDecisionSources(100)
      let resolve!: (value: number) => void
      const load = vi.fn(
        () =>
          new Promise<number>((done) => {
            resolve = done
          }),
      )
      const first = expect(collect('SPY:regime', load)).rejects.toThrow('still calculating')
      await vi.advanceTimersByTimeAsync(100)
      await first
      resolve(42)
      expect(await collect('SPY:regime', load)).toBe(42)
      expect(load).toHaveBeenCalledTimes(1)
      expect(await collect('QQQ:regime', async () => 9)).toBe(9)
    } finally {
      vi.useRealTimers()
    }
  })
})
