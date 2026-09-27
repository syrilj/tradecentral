import { describe, expect, it } from 'vitest'
import { COT_LEAN_Z_CUTOFF, cotLeanFromSpecNetZ } from '@/cotLean'
import {
  CRYPTO_COT_SOURCE,
  CRYPTO_KALMAN_SOURCE,
  KALMAN_TREND_Z_CUTOFF,
  cryptoSpotRead,
  finiteOrNull,
  kalmanTrendFromSlopeOverNoise,
  kalmanTrendLabel,
} from '@/cryptoRead'

describe('finiteOrNull', () => {
  it('keeps a real zero and drops null / NaN / Infinity', () => {
    expect(finiteOrNull(0)).toBe(0)
    expect(finiteOrNull(-0)).toBe(-0)
    expect(finiteOrNull(1.25)).toBe(1.25)
    expect(finiteOrNull(null)).toBeNull()
    expect(finiteOrNull(undefined)).toBeNull()
    expect(finiteOrNull(Number.NaN)).toBeNull()
    expect(finiteOrNull(Number.POSITIVE_INFINITY)).toBeNull()
    expect(finiteOrNull(Number.NEGATIVE_INFINITY)).toBeNull()
  })
})

describe('kalmanTrendFromSlopeOverNoise', () => {
  it('maps slope-over-noise onto trend vs chop at the shipped cutoff', () => {
    expect(KALMAN_TREND_Z_CUTOFF).toBe(1)
    expect(kalmanTrendFromSlopeOverNoise(1)).toBe('TREND_UP')
    expect(kalmanTrendFromSlopeOverNoise(2.4)).toBe('TREND_UP')
    expect(kalmanTrendFromSlopeOverNoise(-1)).toBe('TREND_DOWN')
    expect(kalmanTrendFromSlopeOverNoise(-3)).toBe('TREND_DOWN')
    expect(kalmanTrendFromSlopeOverNoise(0.99)).toBe('CHOP')
    expect(kalmanTrendFromSlopeOverNoise(0)).toBe('CHOP')
    expect(kalmanTrendFromSlopeOverNoise(-0.4)).toBe('CHOP')
  })

  it('returns UNMEASURED for missing inputs, never a numeric stand-in', () => {
    expect(kalmanTrendFromSlopeOverNoise(null)).toBe('UNMEASURED')
    expect(kalmanTrendFromSlopeOverNoise(undefined)).toBe('UNMEASURED')
    expect(kalmanTrendFromSlopeOverNoise(Number.NaN)).toBe('UNMEASURED')
    expect(kalmanTrendLabel('UNMEASURED')).toBe('Unmeasured')
  })
})

describe('cryptoSpotRead', () => {
  it('uses cotLeanFromSpecNetZ cutoffs for the COT lean', () => {
    expect(COT_LEAN_Z_CUTOFF).toBe(0.5)
    const samples: Array<number | null | undefined> = [
      0.5,
      0.6,
      2,
      -0.5,
      -0.6,
      0,
      0.49,
      -0.49,
      null,
      undefined,
      Number.NaN,
    ]
    for (const z of samples) {
      const read = cryptoSpotRead({ cotSpecNetZ: z })
      expect(read.cot.read).toBe(cotLeanFromSpecNetZ(z))
      expect(read.cot.source).toBe(CRYPTO_COT_SOURCE)
    }
    expect(cryptoSpotRead({ cotSpecNetZ: 0.5 }).cot.read).toBe('LONG')
    expect(cryptoSpotRead({ cotSpecNetZ: -0.5 }).cot.read).toBe('SHORT')
    expect(cryptoSpotRead({ cotSpecNetZ: 0 }).cot.read).toBe('BALANCED')
    expect(cryptoSpotRead({ cotSpecNetZ: null }).cot.read).toBe('UNKNOWN')
  })

  it('maps Kalman z onto a trend vs chop read and tags the source', () => {
    const up = cryptoSpotRead({ kalmanSlopeOverNoise: 1.8 })
    expect(up.kalman.read).toBe('TREND_UP')
    expect(up.kalman.value).toBe(1.8)
    expect(up.kalman.kind).toBe('measured')
    expect(up.kalman.source).toBe(CRYPTO_KALMAN_SOURCE)
    expect(up.combined.lean).toBe('LONG')
    expect(up.combined.kind).toBe('inferred')

    const down = cryptoSpotRead({ kalmanSlopeOverNoise: -1.2, cotSpecNetZ: -0.9 })
    expect(down.kalman.read).toBe('TREND_DOWN')
    expect(down.cot.read).toBe('SHORT')
    expect(down.combined.lean).toBe('SHORT')

    const chop = cryptoSpotRead({ kalmanSlopeOverNoise: 0.2, cotSpecNetZ: 0.1 })
    expect(chop.kalman.read).toBe('CHOP')
    expect(chop.cot.read).toBe('BALANCED')
    expect(chop.combined.lean).toBe('BALANCED')
  })

  it('never turns null or NaN into 0 — missing stays unmeasured', () => {
    const missing = cryptoSpotRead({
      kalmanSlopeOverNoise: Number.NaN,
      cotSpecNetZ: Number.NaN,
    })
    expect(missing.kalman.value).toBeNull()
    expect(missing.cot.value).toBeNull()
    expect(missing.kalman.value).not.toBe(0)
    expect(missing.cot.value).not.toBe(0)
    expect(missing.kalman.read).toBe('UNMEASURED')
    expect(missing.cot.read).toBe('UNKNOWN')
    expect(missing.combined.lean).toBe('UNKNOWN')
    expect(missing.combined.kind).toBe('missing')
    expect(missing.kalman.kind).toBe('missing')
    expect(missing.cot.kind).toBe('missing')

    const half = cryptoSpotRead({ kalmanSlopeOverNoise: null, cotSpecNetZ: 1.1 })
    expect(half.kalman.value).toBeNull()
    expect(half.kalman.read).toBe('UNMEASURED')
    expect(half.cot.value).toBe(1.1)
    expect(half.cot.read).toBe('LONG')
    expect(half.combined.lean).toBe('LONG')
    expect(half.combined.kind).toBe('inferred')
  })

  it('keeps a measured zero as chop / balanced rather than missing', () => {
    const zero = cryptoSpotRead({ kalmanSlopeOverNoise: 0, cotSpecNetZ: 0 })
    expect(zero.kalman.value).toBe(0)
    expect(zero.kalman.read).toBe('CHOP')
    expect(zero.kalman.kind).toBe('measured')
    expect(zero.cot.value).toBe(0)
    expect(zero.cot.read).toBe('BALANCED')
    expect(zero.cot.kind).toBe('measured')
  })
})
