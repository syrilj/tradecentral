import { describe, expect, it } from 'vitest'
import {
  MARKET_SESSION_LABELS,
  formatMarketCountdown,
  marketSessionClass,
  marketSessionLabel,
} from '@/marketSession'

describe('market session mapping (shipped)', () => {
  it('maps every known market_session and uses CAL SYNC only when absent', () => {
    expect(MARKET_SESSION_LABELS.regular).toBe('RTH OPEN')
    expect(MARKET_SESSION_LABELS.premarket).toBe('PREMARKET')
    expect(MARKET_SESSION_LABELS.after_hours).toBe('AFTER HOURS')
    expect(MARKET_SESSION_LABELS.closed).toBe('MARKET CLOSED')
    expect(MARKET_SESSION_LABELS.replay).toBe('REPLAY')
    expect(marketSessionLabel('regular')).toBe('RTH OPEN')
    expect(marketSessionLabel('premarket')).toBe('PREMARKET')
    expect(marketSessionLabel('after_hours')).toBe('AFTER HOURS')
    expect(marketSessionLabel('closed')).toBe('MARKET CLOSED')
    expect(marketSessionLabel('replay')).toBe('REPLAY')
    expect(marketSessionLabel(null)).toBe('CAL SYNC')
    expect(marketSessionLabel(undefined)).toBe('CAL SYNC')
    expect(marketSessionLabel('regular', { error: true })).toBe('CAL FAULT')
    expect(marketSessionClass('regular')).toBe('regular')
    expect(marketSessionClass(null)).toBe('unknown')
  })

  it('formats a countdown from a present next_transition payload', () => {
    const now = Date.parse('2026-08-13T14:00:00Z')
    expect(formatMarketCountdown('2026-08-13T20:00:00Z', 'regular_closes', now)).toBe(
      'CLOSE IN 06:00:00',
    )
    expect(formatMarketCountdown(null, 'regular_closes', now)).toBe('NEXT n/a')
    expect(formatMarketCountdown('2026-08-13T20:00:00Z', null, now)).toBe('NEXT n/a')
  })
})
