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

  it('keeps the last good value while a replacement is still calculating', async () => {
    vi.useFakeTimers()
    try {
      const collect = createDecisionSources(100)
      expect(await collect('SPY:vpa', async () => 1)).toBe(1)

      let resolveRefresh!: (value: number) => void
      const refresh = collect(
        'SPY:vpa',
        () =>
          new Promise<number>((done) => {
            resolveRefresh = done
          }),
      )
      await vi.advanceTimersByTimeAsync(100)
      await expect(refresh).resolves.toBe(1)

      resolveRefresh(2)
      await Promise.resolve()
      await Promise.resolve()

      const nextRefresh = collect('SPY:vpa', () => new Promise<number>(() => undefined))
      await vi.advanceTimersByTimeAsync(100)
      await expect(nextRefresh).resolves.toBe(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not hide a hard provider failure behind the last good value', async () => {
    const collect = createDecisionSources(100)
    expect(await collect('SPY:options', async () => 1)).toBe(1)
    await expect(
      collect('SPY:options', async () => {
        throw new Error('provider offline')
      }),
    ).rejects.toThrow('provider offline')
  })
})
