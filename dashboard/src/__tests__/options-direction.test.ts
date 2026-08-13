import { describe, expect, it } from 'vitest'
import { buildOptionsDirection, type OptionsDirectionSummary } from '@/optionsDirection'

function summary(overrides: Partial<OptionsDirectionSummary> = {}): OptionsDirectionSummary {
  return {
    activity_imbalance: 0,
    signed_flow_imbalance: null,
    signed_flow_confidence: 0,
    gamma_flip: 100,
    call_wall: 110,
    put_wall: 90,
    squeeze: {
      bullish: 0,
      bearish: 0,
      score: 0,
      label: 'quiet',
      primary: 'quiet',
      drivers: [],
      theory: {
        momentum: 0,
        momentum_fresh: true,
      },
    },
    ...overrides,
  }
}

describe('options direction read', () => {
  it('shows a strong bullish read when signed flow and momentum align', () => {
    const read = buildOptionsDirection(summary({
      signed_flow_imbalance: 0.62,
      signed_flow_confidence: 0.875,
      squeeze: {
        bullish: 0.74,
        bearish: 0.08,
        score: 66,
        label: 'bullish_squeeze',
        primary: 'bullish',
        drivers: ['signed_bullish_flow', 'up_momentum'],
        theory: { momentum: 0.018, momentum_fresh: true },
      },
    }), 'live')

    expect(read.state).toBe('bullish')
    expect(read.confidence).toBe('high')
    expect(read.headline).toBe('BULLISH')
    expect(read.basis).toBe('SIGNED FLOW + MOMENTUM')
    expect(read.confirmation).toContain('$110')
  })

  it('never turns unsigned call-heavy activity into bullish direction', () => {
    const read = buildOptionsDirection(summary({
      activity_imbalance: 1,
      signed_flow_imbalance: null,
      signed_flow_confidence: 0,
    }), 'live')

    expect(read.state).toBe('neutral')
    expect(read.headline).toBe('NO DIRECTION')
    expect(read.activity).toBe('call')
    expect(read.activityLabel).toBe('CALL-HEAVY ACTIVITY')
    expect(read.basis).toBe('NO SIGNED DIRECTION')
    expect(read.signedFlow).toBeNull()
    expect(read.signedConfidence).toBeNull()
  })

  it('uses fresh momentum as the underlier lean when the tape has no buy/sell side', () => {
    const read = buildOptionsDirection(summary({
      activity_imbalance: 0.6,
      signed_flow_imbalance: null,
      signed_flow_confidence: 0,
      squeeze: {
        bullish: 0.03,
        bearish: 0,
        score: 3.2,
        label: 'quiet',
        primary: 'quiet',
        drivers: ['up_momentum', 'call_wall_proximity'],
        theory: { momentum: 0.3047, momentum_fresh: true },
      },
    }), 'stale')

    expect(read.state).toBe('bullish')
    expect(read.headline).toBe('BULLISH')
    expect(read.basis).toBe('PRICE MOMENTUM')
    expect(read.confidence).toBe('low')
    expect(read.confidence).not.toBe('high')
    expect(read.signedFlow).toBeNull()
    expect(read.momentum).toBeCloseTo(0.3047)
    expect(read.momentumFresh).toBe(true)
    expect(read.tapeStale).toBe(true)
    expect(read.stale).toBe(false)
    expect(read.confirmationTitle).not.toContain('WAIT FOR DIRECTIONAL')
    expect(read.confirmation).toMatch(/momentum/i)
    expect(read.confirmation).not.toMatch(/Wait for signed side or fresh momentum/)
  })

  it('lets signed flow set the lean even when squeeze fuel is too small to fire', () => {
    const read = buildOptionsDirection(summary({
      signed_flow_imbalance: -0.4,
      signed_flow_confidence: 0.5,
      squeeze: {
        bullish: 0,
        bearish: 0.08,
        score: -6,
        label: 'quiet',
        primary: 'quiet',
        drivers: ['signed_bearish_flow'],
        theory: { momentum: 0.001, momentum_fresh: true },
      },
    }), 'live')

    expect(read.state).toBe('bearish')
    expect(read.basis).toBe('SIGNED FLOW')
    expect(read.headline).toBe('BEARISH')
  })

  it('fails to mixed when signed flow and momentum disagree', () => {
    const read = buildOptionsDirection(summary({
      signed_flow_imbalance: 0.5,
      signed_flow_confidence: 0.75,
      squeeze: {
        bullish: 0.42,
        bearish: 0.12,
        score: 30,
        label: 'bullish_lean',
        primary: 'bullish',
        drivers: ['signed_bullish_flow', 'down_momentum'],
        theory: { momentum: -0.02, momentum_fresh: true },
      },
    }), 'live')

    expect(read.state).toBe('mixed')
    expect(read.headline).toBe('MIXED / WAIT')
    expect(read.confidence).toBe('wait')
    expect(read.basis).toBe('CONFLICTING FLOW + MOMENTUM')
  })

  it('downgrades an otherwise qualified read when its inputs are stale', () => {
    const read = buildOptionsDirection(summary({
      signed_flow_imbalance: -0.4,
      signed_flow_confidence: 0.5,
      squeeze: {
        bullish: 0.06,
        bearish: 0.5,
        score: -44,
        label: 'bearish_squeeze',
        primary: 'bearish',
        drivers: ['signed_bearish_flow'],
        theory: { momentum: -0.01, momentum_fresh: true },
      },
    }), 'stale')

    expect(read.state).toBe('bearish')
    expect(read.tapeStale).toBe(true)
    expect(read.stale).toBe(false)
    // Tape lag downgrades a high aligned read; it does not erase the side.
    expect(read.confidence).toBe('medium')
  })

  it('renders an explicit unavailable state before a matching payload exists', () => {
    const read = buildOptionsDirection(null, 'loading')
    expect(read.state).toBe('unavailable')
    expect(read.headline).toBe('AWAITING DATA')
    expect(read.score).toBeNull()
  })

  it('keeps explicitly missing metrics blank instead of coercing them to zero', () => {
    const read = buildOptionsDirection(summary({
      activity_imbalance: null,
      signed_flow_imbalance: null,
      signed_flow_confidence: null,
      squeeze: {
        bullish: 0,
        bearish: 0,
        score: 0,
        label: 'quiet',
        primary: 'quiet',
        drivers: [],
        theory: { momentum: null, momentum_fresh: true },
      },
    }), 'live')

    expect(read.activity).toBe('unavailable')
    expect(read.momentum).toBeNull()
    expect(read.signedFlow).toBeNull()
  })
})
