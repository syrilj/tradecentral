import { describe, expect, it } from 'vitest'
import {
  activityLeanRead,
  formatTapeDate,
  formatTapeTime,
  isDateOnlyStamp,
  printWhy,
} from '@/optionsTape'

describe('activity lean readout', () => {
  it('surfaces a bullish activity sign without authorizing a trade', () => {
    const read = activityLeanRead({
      activity_lean: 'bullish',
      activity_lean_source: 'call_put_premium',
      activity_lean_label: 'BULLISH',
    })
    expect(read.lean).toBe('bullish')
    expect(read.label).toBe('BULLISH')
    expect(read.authorized).toBe(false)
    expect(read.sourceLabel).toBe('call vs put premium')
    expect(read.title).toContain('Not trade-authorized')
  })

  it('stays neutral when the tape has no lean', () => {
    const read = activityLeanRead({})
    expect(read.lean).toBe('neutral')
    expect(read.label).toBe('NEUTRAL')
    expect(read.authorized).toBe(false)
  })
})

describe('print why', () => {
  it('prefers backend why strings', () => {
    expect(
      printWhy({
        why: ['14d expiry', '18% OTM', 'burst sweep ≤3s'],
        anomaly_flags: ['sweep_burst'],
        is_unusual: true,
        is_sweep: true,
      }),
    ).toEqual(['14d expiry', '18% OTM', 'burst sweep ≤3s'])
  })

  it('falls back to flags when why is missing', () => {
    expect(
      printWhy({
        anomaly_flags: ['premium_outlier', 'repeat_cluster'],
        is_unusual: true,
        is_momentum: true,
      }),
    ).toEqual(['near-dated OTM', 'premium outlier', 'repeat cluster', 'high relative volume'])
  })
})

describe('formatTapeTime', () => {
  it('extracts HH:MM:SS from ISO timestamps', () => {
    expect(formatTapeTime('2026-08-22T14:32:05.123Z')).toBe('14:32:05')
    expect(formatTapeTime('2026-08-22T09:15:30Z')).toBe('09:15:30')
  })

  it('preserves or normalizes short time formats', () => {
    expect(formatTapeTime('14:32:05')).toBe('14:32:05')
    expect(formatTapeTime('09:15')).toBe('09:15:00')
  })

  it('returns DASH for null, undefined, or blank timestamps', () => {
    expect(formatTapeTime(null)).toBe('—')
    expect(formatTapeTime(undefined)).toBe('—')
    expect(formatTapeTime('')).toBe('—')
    expect(formatTapeTime('   ')).toBe('—')
  })
})

describe('formatTapeDate', () => {
  it('renders the UTC calendar day of an ISO print', () => {
    expect(formatTapeDate('2026-08-22T14:32:05.123Z')).toBe('22 AUG')
    expect(formatTapeDate('2026-01-05T09:15:30+00:00')).toBe('05 JAN')
  })

  it('reads the date off the stamp, not the viewer timezone', () => {
    // A late-UTC print must stay on its own UTC day even west of Greenwich.
    expect(formatTapeDate('2026-08-22T23:45:00+00:00')).toBe('22 AUG')
  })

  it('returns empty for stamps that carry no date', () => {
    expect(formatTapeDate('14:32:05')).toBe('')
    expect(formatTapeDate(null)).toBe('')
    expect(formatTapeDate('')).toBe('')
    expect(formatTapeDate('not-a-date')).toBe('')
  })
})

describe('isDateOnlyStamp', () => {
  it('flags midnight roll-ups that carry no intraday clock', () => {
    expect(isDateOnlyStamp('2026-08-24T00:00:00+00:00')).toBe(true)
    expect(isDateOnlyStamp('2026-08-24T00:00:00Z')).toBe(true)
    expect(isDateOnlyStamp('2026-08-24')).toBe(true)
  })

  it('leaves real timed prints alone', () => {
    expect(isDateOnlyStamp('2026-08-24T13:57:09.188157+00:00')).toBe(false)
    expect(isDateOnlyStamp('2026-08-24T00:00:01Z')).toBe(false)
    expect(isDateOnlyStamp(null)).toBe(false)
  })
})
