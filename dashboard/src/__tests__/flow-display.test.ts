import { describe, expect, it } from 'vitest'
import {
  FIRST_WINDOW_BASELINE,
  NO_MIX_IN_SAMPLE,
  NO_SIGNED_SIDE,
  NO_SIGNAL,
  NO_STRIKE_IN_TAPE,
  PREVIOUS_PROVIDER_WINDOW,
  classifyFlowOrder,
  classifyPremiumTier,
  computeVolOiRatio,
  concentrationLabel,
  flowLeanTokenClass,
  flowPriorityTokenClass,
  flowWhaleTier,
  mixShareLabel,
  namedEmpty,
  pulseWindowCopy,
  signedPrintTokenClass,
} from '@/flowDisplay'

describe('flow display helpers (shipped)', () => {
  it('maps signed and model leans onto instrument token classes', () => {
    expect(flowLeanTokenClass('bullish')).toBe('token-long')
    expect(flowLeanTokenClass('model-bullish')).toBe('token-long')
    expect(flowLeanTokenClass('bearish')).toBe('token-short')
    expect(flowLeanTokenClass('model-bearish')).toBe('token-short')
    expect(flowLeanTokenClass('mixed')).toBe('token-warn')
    expect(flowLeanTokenClass('unknown')).toBe('token-unsigned')
    expect(flowLeanTokenClass(null)).toBe('token-unsigned')
    expect(flowLeanTokenClass('bullish')).not.toBe('token-call')
    expect(flowLeanTokenClass('bearish')).not.toBe('token-put')
  })

  it('maps signed buy/sell prints onto long/short tokens, not call/put or phosphor', () => {
    expect(signedPrintTokenClass('buy')).toBe('token-long')
    expect(signedPrintTokenClass('BUY')).toBe('token-long')
    expect(signedPrintTokenClass('long')).toBe('token-long')
    expect(signedPrintTokenClass('sell')).toBe('token-short')
    expect(signedPrintTokenClass('SELL')).toBe('token-short')
    expect(signedPrintTokenClass('short')).toBe('token-short')
    expect(signedPrintTokenClass('mixed')).toBe('token-unsigned')
    expect(signedPrintTokenClass('call')).toBe('token-unsigned')
    expect(signedPrintTokenClass('put')).toBe('token-unsigned')
    expect(signedPrintTokenClass(null)).toBe('token-unsigned')
    expect(signedPrintTokenClass('buy')).not.toContain('call')
    expect(signedPrintTokenClass('sell')).not.toContain('put')
    expect(signedPrintTokenClass('buy')).not.toContain('phosphor')
  })

  it('maps desk priority onto long / warn / unsigned tokens', () => {
    expect(flowPriorityTokenClass('now')).toBe('token-long')
    expect(flowPriorityTokenClass('soon')).toBe('token-warn')
    expect(flowPriorityTokenClass('watch')).toBe('token-ink')
    expect(flowPriorityTokenClass('skip')).toBe('token-unsigned')
  })

  it('names missing mix, signed side, and strike instead of leaving blanks', () => {
    expect(mixShareLabel(null, '62%')).toBe(NO_MIX_IN_SAMPLE)
    expect(mixShareLabel(0.62, '62%')).toBe('62%')
    expect(namedEmpty(null, NO_SIGNED_SIDE)).toBe(NO_SIGNED_SIDE)
    expect(namedEmpty(undefined, NO_SIGNAL)).toBe(NO_SIGNAL)
    expect(concentrationLabel('Unavailable', '')).toBe(NO_STRIKE_IN_TAPE)
    expect(concentrationLabel('C $180', 'fallback')).toBe('C $180')
  })

  it('labels the first provider window as a baseline, later windows as previous-window deltas', () => {
    expect(pulseWindowCopy({
      baseline: true,
      newPrints: 0,
      newPremiumLabel: '+$80k',
      windowDeltaLabel: '+$0',
    })).toBe(FIRST_WINDOW_BASELINE)
    expect(pulseWindowCopy({
      baseline: false,
      newPrints: 2,
      newPremiumLabel: '+$80k',
      windowDeltaLabel: '+$12k',
    })).toBe(`+$80k · 2 new vs ${PREVIOUS_PROVIDER_WINDOW}`)
    expect(pulseWindowCopy({
      baseline: false,
      newPrints: 0,
      newPremiumLabel: '+$0',
      windowDeltaLabel: '−$12k',
    })).toBe(`−$12k vs ${PREVIOUS_PROVIDER_WINDOW}`)
    expect(pulseWindowCopy({
      baseline: true,
      newPrints: 0,
      newPremiumLabel: '+$80k',
      windowDeltaLabel: '+$0',
    })).not.toContain('prior sample')
  })

  it('classifies institutional flow order taxonomy correctly', () => {
    // Golden sweep
    expect(classifyFlowOrder({
      trade_class: 'sweep',
      aggressor: 'buy',
      premium: 250_000,
    }).type).toBe('golden_sweep')

    expect(classifyFlowOrder({
      is_sweep: true,
      aggressor: 'ask',
      volume: 1500,
      open_interest: 800,
    }).type).toBe('golden_sweep')

    expect(classifyFlowOrder({
      trade_class: 'sweep',
      aggressor: 'buy',
      premium: 600_000,
    }).type).toBe('golden_sweep')

    expect(classifyFlowOrder({
      flags: ['golden_sweep'],
    }).type).toBe('golden_sweep')

    // Sweep
    expect(classifyFlowOrder({
      trade_class: 'sweep',
      aggressor: 'sell',
      premium: 50_000,
    }).type).toBe('sweep')

    // Split
    expect(classifyFlowOrder({
      trade_class: 'split',
    }).type).toBe('split')

    expect(classifyFlowOrder({
      flags: ['cross_exchange'],
    }).type).toBe('split')

    // Multi-leg
    expect(classifyFlowOrder({
      trade_class: 'multileg',
    }).type).toBe('multileg')

    expect(classifyFlowOrder({
      trade_class: 'spread',
    }).type).toBe('multileg')

    expect(classifyFlowOrder({
      flags: ['straddle'],
    }).type).toBe('multileg')

    // Block
    expect(classifyFlowOrder({
      trade_class: 'block',
      premium: 500_000,
    }).type).toBe('block')

    expect(classifyFlowOrder({
      is_block: true,
    }).type).toBe('block')

    // Standard
    expect(classifyFlowOrder({
      trade_class: 'single',
    }).type).toBe('standard')

    expect(classifyFlowOrder({})).toMatchObject({
      type: 'standard',
      label: 'STANDARD',
    })
  })

  it('computes Vol / OI ratios with proper edge case handling', () => {
    expect(computeVolOiRatio(null, null)).toEqual({
      ratio: null,
      formatted: '—',
      isHigh: false,
      isExtreme: false,
    })

    expect(computeVolOiRatio(100, null)).toEqual({
      ratio: null,
      formatted: '—',
      isHigh: false,
      isExtreme: false,
    })

    expect(computeVolOiRatio(100, 0)).toEqual({
      ratio: null,
      formatted: 'NEW (0 OI)',
      isHigh: true,
      isExtreme: true,
    })

    expect(computeVolOiRatio(0, 0)).toEqual({
      ratio: null,
      formatted: '—',
      isHigh: false,
      isExtreme: false,
    })

    const normal = computeVolOiRatio(500, 1000)
    expect(normal.ratio).toBe(0.5)
    expect(normal.formatted).toBe('0.5×')
    expect(normal.isHigh).toBe(false)
    expect(normal.isExtreme).toBe(false)

    const high = computeVolOiRatio(2000, 1000)
    expect(high.ratio).toBe(2)
    expect(high.formatted).toBe('2.0×')
    expect(high.isHigh).toBe(true)
    expect(high.isExtreme).toBe(false)

    const extreme = computeVolOiRatio(15000, 1000)
    expect(extreme.ratio).toBe(15)
    expect(extreme.formatted).toBe('15×')
    expect(extreme.isHigh).toBe(true)
    expect(extreme.isExtreme).toBe(true)
  })

  it('classifies premium tiers into institutional categories', () => {
    expect(classifyPremiumTier(1_500_000)).toMatchObject({
      tier: 'mega_whale',
      label: '$1M+ MEGA',
      className: 'tier-mega-whale',
      isWhale: true,
    })

    expect(classifyPremiumTier(750_000)).toMatchObject({
      tier: 'whale',
      label: '$500k+ WHALE',
      className: 'tier-whale',
      isWhale: true,
    })

    expect(classifyPremiumTier(200_000)).toMatchObject({
      tier: 'large',
      label: '$100k+',
      className: 'tier-large',
      isWhale: false,
    })

    expect(classifyPremiumTier(75_000)).toMatchObject({
      tier: 'medium',
      label: '$50k+',
      className: 'tier-medium',
      isWhale: false,
    })

    expect(classifyPremiumTier(25_000)).toMatchObject({
      tier: 'standard',
      label: '<$50k',
      className: 'tier-standard',
      isWhale: false,
    })

    expect(flowWhaleTier(1_200_000).tier).toBe('1m')
    expect(flowWhaleTier(600_000).tier).toBe('500k')
    expect(flowWhaleTier(150_000).tier).toBe('100k')
    expect(flowWhaleTier(30_000).tier).toBeNull()
  })
})
