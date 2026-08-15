import { describe, expect, it } from 'vitest'
import { activityLeanRead, printWhy } from '@/optionsTape'

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
    expect(printWhy({
      why: ['14d expiry', '18% OTM', 'burst sweep ≤3s'],
      anomaly_flags: ['sweep_burst'],
      is_unusual: true,
      is_sweep: true,
    })).toEqual(['14d expiry', '18% OTM', 'burst sweep ≤3s'])
  })

  it('falls back to flags when why is missing', () => {
    expect(printWhy({
      anomaly_flags: ['premium_outlier', 'repeat_cluster'],
      is_unusual: true,
      is_momentum: true,
    })).toEqual(['near-dated OTM', 'premium outlier', 'repeat cluster', 'high relative volume'])
  })
})
