import { describe, expect, it } from 'vitest'
import type { OptionsIntelligence } from '@/api'
import { resolveDealerRead } from '@/dealerRead'

function payload(overrides: Record<string, unknown> = {}): OptionsIntelligence {
  const base = {
    schema_version: 'test', symbol: 'XYZ', mode_requested: 'live', mode_resolved: 'live',
    asof_utc: '2026-09-26T16:00:00Z', observed_at: '2026-09-26T16:00:00Z',
    freshness: { age_seconds: 2 }, summary: {
      spot: 225.3, call_wall: 230, put_wall: 220, total_gex_m: 778,
    }, quality: { gex_measurable: true },
    charm_summary: { net_charm_flow: -952833, pressure: 'buying', contracts_measured: 10 },
    pressure: { verdict: 'BUYING PRESSURE · MEDIUM CONFIDENCE', actionable: true },
  }
  return { ...base, ...overrides } as unknown as OptionsIntelligence
}

describe('resolveDealerRead', () => {
  const now = Date.parse('2026-09-26T16:00:02Z')

  it('uses wall location as the single structural read and does not promote conflicting actionable pressure', () => {
    const read = resolveDealerRead(payload({ freshness: { age_seconds: 86668 } }), now)
    expect(read.status).toBe('stale')
    expect(read.headline).toBe('Stale dealer snapshot')
    expect(read.evidence.pressureActionable).toBe(true)
    expect(read.narrative).toContain('Do not use its wall location as a current read')
    expect(read.narrative).not.toContain('breakout')
  })

  it('classifies the representative fresh snapshot inside the walls despite actionable pressure', () => {
    const read = resolveDealerRead(payload(), now)
    expect(read.status).toBe('in_range')
    expect(read.position).toContain('220.00 ≤ spot 225.30 ≤ 230.00')
    expect(read.evidence.totalGexM).toBe(778)
    expect(read.evidence.netCharmFlow).toBe(-952833)
    expect(read.evidence.pressureActionable).toBe(true)
    expect(read.narrative).toContain('model proxy')
    expect(read.narrative).toContain('not confirmation')
  })

  it('does not let opposite pressure change an in-range location read', () => {
    const read = resolveDealerRead(payload({ pressure: { verdict: 'SELLING', actionable: false } }), now)
    expect(read.status).toBe('in_range')
    expect(read.headline).toBe('Spot inside dealer walls')
  })

  it('keeps equality at either wall in range and uses strict outside comparisons', () => {
    expect(resolveDealerRead(payload({ summary: { spot: 230, call_wall: 230, put_wall: 220 } }), now).status).toBe('in_range')
    expect(resolveDealerRead(payload({ summary: { spot: 220, call_wall: 230, put_wall: 220 } }), now).status).toBe('in_range')
    expect(resolveDealerRead(payload({ summary: { spot: 230.01, call_wall: 230, put_wall: 220 } }), now).status).toBe('above_call_wall')
    expect(resolveDealerRead(payload({ summary: { spot: 219.99, call_wall: 230, put_wall: 220 } }), now).status).toBe('below_put_wall')
  })

  it('makes absent, NaN, zero, or inverted wall data explicit', () => {
    for (const walls of [
      { spot: 225, call_wall: null, put_wall: 220 },
      { spot: 225, call_wall: Number.NaN, put_wall: 220 },
      { spot: 225, call_wall: 0, put_wall: 220 },
      { spot: 225, call_wall: 210, put_wall: 220 },
    ]) {
      const read = resolveDealerRead(payload({ summary: walls }), now)
      expect(read.status).toBe('unavailable')
      expect(read.narrative).toContain('Missing or invalid')
    }
  })

  it('does not treat zero GEX as missing, but respects an explicit unmeasurable flag', () => {
    const zero = resolveDealerRead(payload({ summary: { spot: 225, call_wall: 230, put_wall: 220, total_gex_m: 0 } }), now)
    expect(zero.evidence.totalGexM).toBe(0)
    const unavailable = resolveDealerRead(payload({ quality: { gex_measurable: false } }), now)
    expect(unavailable.evidence.totalGexM).toBeNull()
    expect(unavailable.narrative).toContain('GEX is unavailable')
  })

  it('marks missing freshness unverified and charm with no measured contracts unavailable', () => {
    const read = resolveDealerRead(payload({ freshness: {}, charm_summary: { net_charm_flow: 0, contracts_measured: 0 } }), now)
    expect(read.status).toBe('stale')
    expect(read.evidence.freshness).toBe('unknown')
    expect(read.evidence.netCharmFlow).toBeNull()
    expect(read.narrative).toContain('unverified age')
    expect(read.narrative).toContain('Charm is unavailable')
  })

  it('marks stale when asof_utc is older than five minutes even if feed age is omitted', () => {
    const tenMinutesAgo = new Date(now - 10 * 60 * 1000).toISOString()
    const read = resolveDealerRead(payload({ asof_utc: tenMinutesAgo, freshness: {} }), now)
    expect(read.status).toBe('stale')
    expect(read.evidence.freshness).toBe('stale')
    expect(read.narrative).toContain('older than five minutes')
  })

  it('marks stale when mode_resolved is non-live or underlying is explicitly stale', () => {
    const historyRead = resolveDealerRead(payload({ mode_resolved: 'history' }), now)
    expect(historyRead.status).toBe('stale')
    expect(historyRead.narrative).toContain('from history mode')

    const staleUnderlyingRead = resolveDealerRead(
      payload({ pressure: { underlying: { stale: true }, verdict: 'BALANCED', actionable: false } }),
      now,
    )
    expect(staleUnderlyingRead.status).toBe('stale')
    expect(staleUnderlyingRead.narrative).toContain('marked stale by the underlying feed')
  })

  it('handles null payload gracefully as unavailable', () => {
    const read = resolveDealerRead(null)
    expect(read.status).toBe('unavailable')
    expect(read.headline).toBe('Dealer read unavailable')
    expect(read.evidence.spot).toBeNull()
    expect(read.evidence.freshness).toBe('unknown')
  })

  it('reports spot strictly above call wall or strictly below put wall without breakout claims', () => {
    const above = resolveDealerRead(payload({ summary: { spot: 240, call_wall: 230, put_wall: 220 } }), now)
    expect(above.status).toBe('above_call_wall')
    expect(above.headline).toBe('Spot above call wall')
    expect(above.narrative).toContain('strictly above the supplied call wall')
    expect(above.narrative).not.toContain('confirmed breakout')

    const below = resolveDealerRead(payload({ summary: { spot: 210, call_wall: 230, put_wall: 220 } }), now)
    expect(below.status).toBe('below_put_wall')
    expect(below.headline).toBe('Spot below put wall')
    expect(below.narrative).toContain('strictly below the supplied put wall')
    expect(below.narrative).not.toContain('confirmed breakdown')
  })
})
