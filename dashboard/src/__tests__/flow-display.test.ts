import { describe, expect, it } from 'vitest'
import {
  FIRST_WINDOW_BASELINE,
  NO_MIX_IN_SAMPLE,
  NO_SIGNED_SIDE,
  NO_SIGNAL,
  NO_STRIKE_IN_TAPE,
  PREVIOUS_PROVIDER_WINDOW,
  concentrationLabel,
  flowLeanTokenClass,
  flowPriorityTokenClass,
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
})
