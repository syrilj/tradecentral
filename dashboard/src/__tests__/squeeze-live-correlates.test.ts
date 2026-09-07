/**
 * Live-desk correlate gate for the squeeze board.
 *
 * These cover the properties that matter when the panel is traded against:
 * an unmeasured input never renders as a number, distances are computed from
 * the same spot the score was, and freshness is reported honestly.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  distanceFromSpot,
  buildLevelLadder,
  gammaRegimeSide,
  freshnessTier,
  formatAge,
  isSetupMeasured,
  formatSignedScore,
} from '@/squeezeCalc'
import type { SqueezeSetup } from '@/api'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function setup(over: Partial<SqueezeSetup> = {}): SqueezeSetup {
  return {
    side: 'bullish',
    score: 62,
    score_01: 0.62,
    likelihood: 'likely',
    factors: [{ id: 'regime_score', label: 'Gamma Regime', score: 12, max: 25, detail: '' }],
    setup_analysis: [],
    for_stronger: [],
    trading_implication: '',
    spot: 100,
    wall: 105,
    wall_pct: 0.05,
    ...over,
  }
}

describe('distanceFromSpot', () => {
  it('returns signed dollar and fractional distance', () => {
    expect(distanceFromSpot(105, 100)).toEqual({ delta: 5, pct: 0.05 })
    const below = distanceFromSpot(96, 100)
    expect(below?.delta).toBe(-4)
    expect(below?.pct).toBeCloseTo(-0.04, 10)
  })

  it('refuses to invent a distance from a missing level or spot', () => {
    expect(distanceFromSpot(null, 100)).toBeNull()
    expect(distanceFromSpot(undefined, 100)).toBeNull()
    expect(distanceFromSpot(105, null)).toBeNull()
    expect(distanceFromSpot(105, 0)).toBeNull()
    expect(distanceFromSpot(105, -3)).toBeNull()
    expect(distanceFromSpot(Number.NaN, 100)).toBeNull()
    expect(distanceFromSpot(105, Number.NaN)).toBeNull()
  })
})

describe('buildLevelLadder', () => {
  const base = { spot: 100, callWall: 108, putWall: 94, gammaFlip: 97, pinStrike: 101 }

  it('orders measured levels high to low', () => {
    const rows = buildLevelLadder({ side: 'bullish', ...base })
    expect(rows.map((r) => r.level)).toEqual([108, 101, 100, 97, 94])
  })

  it('marks the call wall as the trigger for a bullish read and the put wall for a bearish one', () => {
    const bull = buildLevelLadder({ side: 'bullish', ...base })
    expect(bull.find((r) => r.id === 'call_wall')?.role).toBe('trigger')
    expect(bull.find((r) => r.id === 'put_wall')?.role).toBe('magnet')

    const bear = buildLevelLadder({ side: 'bearish', ...base })
    expect(bear.find((r) => r.id === 'put_wall')?.role).toBe('trigger')
    expect(bear.find((r) => r.id === 'call_wall')?.role).toBe('magnet')
  })

  it('always treats the gamma flip as the invalidation level', () => {
    for (const side of ['bullish', 'bearish'] as const) {
      const rows = buildLevelLadder({ side, ...base })
      expect(rows.find((r) => r.id === 'gamma_flip')?.role).toBe('invalidation')
    }
  })

  it('keeps unmeasured levels as rows with a null level, sunk to the bottom', () => {
    const rows = buildLevelLadder({ side: 'bullish', spot: 100, callWall: 108 })
    expect(rows).toHaveLength(5)
    const tail = rows.slice(-3)
    expect(tail.every((r) => r.level == null)).toBe(true)
    expect(tail.every((r) => r.distance == null)).toBe(true)
    expect(rows.map((r) => r.id).slice(0, 2)).toEqual(['call_wall', 'spot'])
  })

  it('computes every distance against the same spot', () => {
    const rows = buildLevelLadder({ side: 'bullish', ...base })
    expect(rows.find((r) => r.id === 'call_wall')?.distance?.pct).toBeCloseTo(0.08, 10)
    expect(rows.find((r) => r.id === 'put_wall')?.distance?.pct).toBeCloseTo(-0.06, 10)
    expect(rows.find((r) => r.id === 'spot')?.distance).toEqual({ delta: 0, pct: 0 })
  })

  it('produces no distances at all when spot itself is unmeasured', () => {
    const rows = buildLevelLadder({ side: 'bullish', spot: null, callWall: 108, putWall: 94 })
    expect(rows.every((r) => r.distance == null)).toBe(true)
  })
})

describe('gammaRegimeSide', () => {
  it('reports which side of the flip spot sits on', () => {
    expect(gammaRegimeSide(105, 100)).toBe('above_flip')
    expect(gammaRegimeSide(95, 100)).toBe('below_flip')
    expect(gammaRegimeSide(100, 100)).toBe('at_flip')
  })

  it('reports unmeasured rather than guessing a regime', () => {
    expect(gammaRegimeSide(null, 100)).toBe('unmeasured')
    expect(gammaRegimeSide(105, null)).toBe('unmeasured')
    expect(gammaRegimeSide(Number.NaN, 100)).toBe('unmeasured')
  })
})

describe('freshnessTier', () => {
  it('classifies live, delayed and stale payload ages', () => {
    expect(freshnessTier(5)).toBe('live')
    expect(freshnessTier(89)).toBe('live')
    expect(freshnessTier(90)).toBe('delayed')
    expect(freshnessTier(899)).toBe('delayed')
    expect(freshnessTier(900)).toBe('stale')
    expect(freshnessTier(86400)).toBe('stale')
  })

  it('never labels a dated payload live, however recently it was rendered', () => {
    expect(freshnessTier(2, 'history')).toBe('history')
    expect(freshnessTier(2, 'history_fallback')).toBe('history')
  })

  it('reports unknown for a missing or nonsense age', () => {
    expect(freshnessTier(null)).toBe('unknown')
    expect(freshnessTier(undefined)).toBe('unknown')
    expect(freshnessTier(Number.NaN)).toBe('unknown')
    expect(freshnessTier(-5)).toBe('unknown')
    expect(freshnessTier(3, 'unavailable')).toBe('unknown')
  })
})

describe('formatAge', () => {
  it('renders compact ages and a placeholder when unmeasured', () => {
    expect(formatAge(12)).toBe('12s')
    expect(formatAge(90)).toBe('1m')
    expect(formatAge(3700)).toBe('1h 1m')
    expect(formatAge(90000)).toBe('1d')
    expect(formatAge(null)).toBe('—')
    expect(formatAge(Number.NaN)).toBe('—')
  })
})

describe('isSetupMeasured', () => {
  it('accepts a setup that carries real factor meters', () => {
    expect(isSetupMeasured(setup())).toBe(true)
  })

  it('rejects a setup with no scored factors, so the dial shows UNSCORED not 0/100', () => {
    expect(isSetupMeasured(undefined)).toBe(false)
    expect(isSetupMeasured(null)).toBe(false)
    expect(isSetupMeasured(setup({ factors: [] }))).toBe(false)
    expect(
      isSetupMeasured(setup({ factors: [{ id: 'x', label: 'x', score: 0, max: 0, detail: '' }] })),
    ).toBe(false)
    expect(isSetupMeasured(setup({ score: Number.NaN }))).toBe(false)
  })

  it('accepts a genuine zero score, which is a measurement and not an absence', () => {
    expect(isSetupMeasured(setup({ score: 0 }))).toBe(true)
  })
})

describe('formatSignedScore', () => {
  it('signs measured scores and blanks missing ones', () => {
    expect(formatSignedScore(18)).toBe('+18')
    expect(formatSignedScore(-4)).toBe('-4')
    expect(formatSignedScore(0)).toBe('0')
    expect(formatSignedScore(null)).toBe('—')
    expect(formatSignedScore(Number.NaN)).toBe('—')
  })
})

describe('SqueezeScreener source: no fabricated figures', () => {
  const src = readFileSync(join(root, 'components/SqueezeScreener.vue'), 'utf8')

  it('never falls back to a zero price or a zero signed score', () => {
    expect(src).not.toContain("'$0.00'")
    expect(src).not.toContain('"$0.00"')
    expect(src).not.toContain("'+0'")
  })

  it('does not invent a likelihood verdict for an unscored setup', () => {
    expect(src).not.toContain("'POSSIBLE'")
    expect(src).not.toContain("|| 'UNLIKELY'")
    expect(src).toContain('UNSCORED')
  })

  it('renders a dash on the theory dial when nothing was scored, not a fake 0/100', () => {
    expect(src).toContain("boardScore == null ? DASH : formatSignedScore(boardScore)")
    expect(src).toContain("boardScore == null ? 'UNSCORED' : '/100'")
    expect(src).not.toContain('PROBABILITY SCORE')
  })

  it('ships the measured price ladder and its distance columns', () => {
    expect(src).toContain('buildLevelLadder')
    expect(src).toContain('class="ladder"')
    expect(src).toContain('class="trigger-strip"')
    expect(src).toContain('DISTANCE TO {{ triggerRow.label }}')
  })

  it('pins a freshness verdict and carries the full audit line', () => {
    expect(src).toContain('class="prov label"')
    expect(src).toContain('AGE {{ fresh.age }}')
    expect(src).toContain('{{ contractsLabel }} CONTRACTS')
    expect(src).toContain(':text="provDetail"')
  })

  it('names every source in the audit line, reporting unknowns rather than omitting them', () => {
    for (const clause of [
      'As of ',
      'Chain feed: ',
      'Open interest: ',
      'contracts passed quality filters',
    ]) {
      expect(src).toContain(clause)
    }
    expect(src.match(/\|\| 'unknown'/g)?.length).toBeGreaterThanOrEqual(2)
  })
})

describe('OptionsView wiring: the board is fed real provenance', () => {
  const src = readFileSync(join(root, 'views/OptionsView.vue'), 'utf8')

  it('passes the payload asof, provider and contract count to the screener', () => {
    expect(src).toContain(':chain-provider="d?.provider?.chain ?? null"')
    expect(src).toContain(':oi-provider="d?.provider?.open_interest ?? null"')
    expect(src).toContain(':contracts="d?.quality?.chain_contracts_included ?? null"')
    expect(src).toContain(':age-seconds="squeezeFeedAge"')
    expect(src).toContain(':mode="d?.mode_resolved ?? null"')
  })

  it('derives squeeze feed age from payload stamps rather than defaulting to fresh', () => {
    expect(src).toContain('const squeezeFeedAge = computed<number | null>')
    expect(src).toMatch(/squeezeFeedAge[\s\S]{0,400}if \(!payload\) return null/)
  })
})
