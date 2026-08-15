import { describe, expect, it } from 'vitest'
import { nextResourceData, shouldStartRefresh } from '@/composables/useResource'

describe('live resource keep-last / no-stack (shipped)', () => {
  const lastTape = { asof: '2026-08-11T17:00:00Z', rows: [{ symbol: 'SPY' }] }
  const nextTape = { asof: '2026-08-11T17:00:15Z', rows: [{ symbol: 'QQQ' }] }

  it('keeps the last good tape when a poll does not pass clear', () => {
    expect(nextResourceData(lastTape, nextTape)).toEqual(nextTape)
    expect(nextResourceData(lastTape, null)).toEqual(lastTape)
    expect(nextResourceData(lastTape, null, { failed: true })).toEqual(lastTape)
  })

  it('blanks only when the caller asked to clear', () => {
    expect(nextResourceData(lastTape, null, { clear: true })).toBeNull()
    expect(nextResourceData(lastTape, null, { clear: true, failed: true })).toBeNull()
    expect(nextResourceData(lastTape, nextTape, { clear: true })).toEqual(nextTape)
  })

  it('skips a stacked poll while a request is in flight', () => {
    expect(shouldStartRefresh(true)).toBe(false)
    expect(shouldStartRefresh(false)).toBe(true)
    expect(shouldStartRefresh(true, { clear: true })).toBe(true)
  })
})
