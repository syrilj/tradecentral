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
    const read = buildOptionsDirection(
      summary({
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
      }),
      'live',
    )

    expect(read.state).toBe('bullish')
    expect(read.confidence).toBe('high')
    expect(read.headline).toBe('BULLISH')
    expect(read.basis).toBe('SIGNED FLOW + MOMENTUM')
    expect(read.confirmation).toContain('$110')
  })

  it('never turns unsigned call-heavy activity into bullish direction', () => {
    const read = buildOptionsDirection(
      summary({
        activity_imbalance: 1,
        signed_flow_imbalance: null,
        signed_flow_confidence: 0,
      }),
      'live',
    )

    expect(read.state).toBe('neutral')
    expect(read.headline).toBe('NO DIRECTION')
    expect(read.activity).toBe('call')
    expect(read.activityLabel).toBe('CALL-HEAVY ACTIVITY')
    expect(read.basis).toBe('NO SIGNED DIRECTION')
    expect(read.signedFlow).toBeNull()
    expect(read.signedConfidence).toBeNull()
  })

  it('uses fresh momentum as the underlier lean when the tape has no buy/sell side', () => {
    const read = buildOptionsDirection(
      summary({
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
      }),
      'stale',
    )

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
    const read = buildOptionsDirection(
      summary({
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
      }),
      'live',
    )

    expect(read.state).toBe('bearish')
    expect(read.basis).toBe('SIGNED FLOW')
    expect(read.headline).toBe('BEARISH')
  })

  it('fails to mixed when signed flow and momentum disagree', () => {
    const read = buildOptionsDirection(
      summary({
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
      }),
      'live',
    )

    expect(read.state).toBe('mixed')
    expect(read.headline).toBe('MIXED / WAIT')
    expect(read.confidence).toBe('wait')
    expect(read.basis).toBe('CONFLICTING FLOW + MOMENTUM')
  })

  it('downgrades an otherwise qualified read when its inputs are stale', () => {
    const read = buildOptionsDirection(
      summary({
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
      }),
      'stale',
    )

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
    const read = buildOptionsDirection(
      summary({
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
      }),
      'live',
    )

    expect(read.activity).toBe('unavailable')
    expect(read.momentum).toBeNull()
    expect(read.signedFlow).toBeNull()
  })
})

import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import OptionsDirectionBrief from '../components/OptionsDirectionBrief.vue'

describe('OptionsDirectionBrief Component & Positioning Telemetry Map (R1)', () => {
  const baseRead = buildOptionsDirection(
    summary({
      signed_flow_imbalance: 0.5,
      signed_flow_confidence: 0.8,
      squeeze: {
        bullish: 0.6,
        bearish: 0.1,
        score: 50,
        label: 'bullish_squeeze',
        primary: 'bullish',
        drivers: ['signed_bullish_flow'],
        theory: { momentum: 0.02, momentum_fresh: true },
      },
    }),
    'live',
  )

  async function renderBrief(props: {
    symbol?: string
    read?: typeof baseRead
    spot?: number | null
    callWall?: number | null
    putWall?: number | null
    gammaFlip?: number | null
    regime?: string | null
    totalGexM?: number | null
  }): Promise<string> {
    const app = createSSRApp({
      render: () =>
        h(OptionsDirectionBrief, {
          symbol: props.symbol ?? 'NVDA',
          read: props.read ?? baseRead,
          spot: props.spot !== undefined ? props.spot : 100,
          callWall: props.callWall !== undefined ? props.callWall : 110,
          putWall: props.putWall !== undefined ? props.putWall : 90,
          gammaFlip: props.gammaFlip !== undefined ? props.gammaFlip : 95,
          regime: props.regime !== undefined ? props.regime : 'long_gamma',
          totalGexM: props.totalGexM !== undefined ? props.totalGexM : 12.5,
        }),
    })
    return renderToString(app)
  }

  it('renders visual unified positioning telemetry range meter with all markers and percentage distances', async () => {
    const html = await renderBrief({
      spot: 100,
      callWall: 110,
      putWall: 90,
      gammaFlip: 95,
      regime: 'pos_gamma',
      totalGexM: 14.2,
    })

    expect(html).toContain('POSITIONING TELEMETRY MAP')
    expect(html).toContain('PUT W')
    expect(html).toContain('$90.00')
    expect(html).toContain('-10.0%')
    expect(html).toContain('FLIP')
    expect(html).toContain('$95.00')
    expect(html).toContain('SPOT')
    expect(html).toContain('$100.00')
    expect(html).toContain('CALL W')
    expect(html).toContain('$110.00')
    expect(html).toContain('+10.0%')
    expect(html).toContain('LONG GAMMA · VOLATILITY DAMPENED')
    expect(html).toContain('+$14.2M')
    // Flip 95 sits below spot 100, so reaching it is a -5.0% move — the same
    // sign convention the +10.0% call wall and -10.0% put wall use above.
    expect(html).toContain('-5.0% TO FLIP')
    expect(html).toContain('SPOT $100.00 → FLIP $95.00 = -$5.00 (-5.0%) · SPOT ABOVE FLIP')
    expect(html).toContain('DAMPEN ABOVE $95.00')
  })

  it('handles negative total GEX regime with short gamma amplified volatility tag', async () => {
    const html = await renderBrief({
      spot: 92,
      callWall: 110,
      putWall: 85,
      gammaFlip: 95,
      regime: 'neg_gamma',
      totalGexM: -8.4,
    })

    expect(html).toContain('SHORT GAMMA · VOLATILITY AMPLIFIED')
    expect(html).toContain('-$8.4M')
    expect(html).toContain('+3.3% TO FLIP')
    expect(html).toContain('SPOT $92.00 → FLIP $95.00 = +$3.00 (+3.3%) · SPOT BELOW FLIP')
    expect(html).toContain('AMPLIFY BELOW $95.00')
  })

  it('follows spot-vs-flip, not the net GEX sign, when the two disagree', async () => {
    // Net GEX is long across the chain, but spot sits below the near-spot flip.
    // Both are real states; the hedging read must come from spot vs flip, and
    // the disagreement has to be stated rather than resolved silently.
    const html = await renderBrief({
      spot: 92,
      callWall: 110,
      putWall: 85,
      gammaFlip: 95,
      regime: 'pos_gamma',
      totalGexM: 11.3,
    })

    expect(html).toContain('LONG GAMMA · VOLATILITY DAMPENED')
    expect(html).toContain('Spot is below the flip')
    expect(html).toContain('AMPLIFY BELOW $95.00')
    expect(html).toContain('NET GEX AND SPOT-SIDE DISAGREE')
    expect(html).not.toContain('Spot is above the flip')
  })

  it('does not flag a conflict when net GEX and spot-vs-flip agree', async () => {
    const html = await renderBrief({
      spot: 100,
      callWall: 110,
      putWall: 90,
      gammaFlip: 95,
      regime: 'pos_gamma',
      totalGexM: 14.2,
    })

    expect(html).toContain('Spot is above the flip')
    expect(html).not.toContain('NET GEX AND SPOT-SIDE DISAGREE')
  })

  it('never marks the book long and short at once when regime and GEX disagree', async () => {
    // Net GEX is the measurement and wins; the regime string is only a label.
    const html = await renderBrief({
      spot: 100,
      callWall: 110,
      putWall: 90,
      gammaFlip: 95,
      regime: 'neg_gamma',
      totalGexM: 14.2,
    })

    expect(html).toContain('LONG GAMMA · VOLATILITY DAMPENED')
    expect(html).not.toContain('SHORT GAMMA · VOLATILITY AMPLIFIED')
    expect(html).toContain('NET GEX +$14.2M · LONG BOOK')
  })

  it('says the flip is unmeasured instead of asserting a side', async () => {
    const html = await renderBrief({
      spot: 100,
      callWall: 110,
      putWall: 90,
      gammaFlip: null,
      regime: 'neg_gamma',
      totalGexM: -6.1,
    })

    expect(html).toContain('NO MEASURED FLIP · SPOT SIDE UNRESOLVED')
    expect(html).toContain('AMPLIFY · NO MEASURED FLIP')
    expect(html).not.toContain('Spot is below the flip')
    expect(html).not.toContain('Spot is above the flip')
  })

  it('handles spot equal to gamma flip boundary cleanly without crashing or NaN', async () => {
    const html = await renderBrief({
      spot: 100,
      callWall: 110,
      putWall: 90,
      gammaFlip: 100,
    })

    expect(html).toContain('+0.0% TO FLIP')
    expect(html).toContain('FLIP')
    expect(html).toContain('SPOT')
    expect(html).toContain('$100.00')
  })

  it('handles inverted walls where Put Wall > Call Wall due to deep ITM put open interest', async () => {
    const html = await renderBrief({
      spot: 100,
      callWall: 90,
      putWall: 110,
      gammaFlip: 95,
    })

    expect(html).toContain('PUT W')
    expect(html).toContain('$110.00')
    expect(html).toContain('+10.0%')
    expect(html).toContain('CALL W')
    expect(html).toContain('$90.00')
    expect(html).toContain('-10.0%')
  })

  it('collapses the range meter when all walls and flip are unmeasured/null', async () => {
    const html = await renderBrief({
      spot: 100,
      callWall: null,
      putWall: null,
      gammaFlip: null,
    })

    expect(html).not.toContain('POSITIONING TELEMETRY MAP')
    expect(html).not.toContain('range-track')
    // Direction header and evidence strip remain visible
    expect(html).toContain('UNDERLYING DIRECTION')
    expect(html).toContain('SIGNED FLOW')
  })

  it('renders fallback full-track regime wash when flip is unmeasured but regime is known', async () => {
    const html = await renderBrief({
      spot: 100,
      callWall: 110,
      putWall: 90,
      gammaFlip: null,
      regime: 'long_gamma',
      totalGexM: 5.0,
    })

    expect(html).toContain('POSITIONING TELEMETRY MAP')
    expect(html).toContain('long-gamma')
    expect(html).toContain('range-zone')
  })

  it('formats zero score as +0.0 on directional score block', async () => {
    const zeroScoreRead = buildOptionsDirection(
      summary({
        signed_flow_imbalance: null,
        signed_flow_confidence: 0,
        squeeze: {
          bullish: 0,
          bearish: 0,
          score: 0,
          label: 'quiet',
          primary: 'quiet',
          drivers: [],
          theory: { momentum: 0, momentum_fresh: true },
        },
      }),
      'live',
    )

    const html = await renderBrief({
      read: zeroScoreRead,
    })

    expect(html).toContain('+0.0')
  })

  it('applies is-left and is-right edge classes to prevent boundary pill clipping', async () => {
    const html = await renderBrief({
      spot: 100,
      callWall: 150,
      putWall: 50,
      gammaFlip: 100,
    })

    // Put wall is at the far left boundary (<=12%)
    expect(html).toContain('is-left')
    expect(html).toContain('put-wall')
    // Call wall is at the far right boundary (>=88%)
    expect(html).toContain('is-right')
    expect(html).toContain('call-wall')
  })

  it('staggers gamma flip marker when flip coincides with put wall or call wall', async () => {
    const htmlPutFlipCoincide = await renderBrief({
      spot: 100,
      callWall: 120,
      putWall: 80,
      gammaFlip: 80, // Flip equals Put Wall
    })

    expect(htmlPutFlipCoincide).toContain('gamma-flip')
    expect(htmlPutFlipCoincide).toContain('marker-pill flip')
    expect(htmlPutFlipCoincide).toContain('staggered')

    const htmlCallFlipCoincide = await renderBrief({
      spot: 100,
      callWall: 120,
      putWall: 80,
      gammaFlip: 120, // Flip equals Call Wall
    })

    expect(htmlCallFlipCoincide).toContain('gamma-flip')
    expect(htmlCallFlipCoincide).toContain('marker-pill flip')
    expect(htmlCallFlipCoincide).toContain('staggered')
  })

  it('formats near-zero micro-negative flip distance as +0.0% TO FLIP', async () => {
    const html = await renderBrief({
      spot: 99.999,
      gammaFlip: 100,
      callWall: 110,
      putWall: 90,
    })

    expect(html).toContain('+0.0% TO FLIP')
    expect(html).not.toContain('-0.0% TO FLIP')
  })

  it('separates colliding Put Wall and Call Wall onto vertical Tier 1 and Tier 2', async () => {
    const html = await renderBrief({
      spot: 100,
      callWall: 100,
      putWall: 100,
      gammaFlip: null,
    })

    expect(html).toContain('tier-1')
    expect(html).toContain('tier-2')
    expect(html).toContain('put-wall')
    expect(html).toContain('call-wall')
    expect(html).toMatch(/padding-top:\s*38px/)
  })

  it('resolves triple collision (Put Wall = Call Wall = Flip) into 3 distinct vertical tiers with 54px headroom', async () => {
    const html = await renderBrief({
      spot: 100,
      callWall: 100,
      putWall: 100,
      gammaFlip: 100,
    })

    expect(html).toContain('tier-1')
    expect(html).toContain('tier-2')
    expect(html).toContain('tier-3')
    expect(html).toMatch(/padding-top:\s*54px/)
  })

  it('omits range markers and suppresses range meter when wall strikes are zero or non-positive', async () => {
    const html = await renderBrief({
      spot: 100,
      callWall: 0,
      putWall: -10,
      gammaFlip: 0,
    })

    expect(html).not.toContain('POSITIONING TELEMETRY MAP')
    expect(html).not.toContain('PUT W $0')
    expect(html).not.toContain('CALL W $0')
    expect(html).not.toContain('FLIP $0')
  })
})
