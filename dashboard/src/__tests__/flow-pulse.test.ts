import { describe, expect, it } from 'vitest'
import type { MarketFlowPrint, UnusualFlowRow } from '@/api'
import { applyFlowWindow, buildFlowPulse, flowPrintKey, type FlowPulsePayload } from '@/flowPulse'

function aggregate(symbol: string, rank: number, premium: number): UnusualFlowRow {
  return {
    symbol,
    activity_score: 50,
    activity_rank: rank,
    flags: [],
    context_side: 'neutral',
    calibrated_probability: null,
    live: true,
    live_asof: '2026-08-11T17:00:00Z',
    premium,
    print_count: 1,
    call_print_count: 1,
    put_print_count: 0,
    ret_1d: null,
    volume_vs_20d_median: null,
    price_impulse: 'flat',
    sources: ['provider'],
    decision_authorized: false,
    note: 'activity only',
    score_kind: 'ordinal_unusual_flow',
  }
}

function print(symbol: string, timestamp: string, premium: number): MarketFlowPrint {
  return {
    symbol,
    timestamp,
    right: 'call',
    premium,
    volume: 10,
    contracts: 10,
    price: premium / 1_000,
    strike: 100,
    underlying_price: 99,
    expiry: '2026-08-14',
    dte: 3,
    aggressor: null,
    signed_premium: null,
    premium_estimated: false,
    anomaly_flags: [],
    anomaly_score: 0,
    premium_percentile: 0.5,
  }
}

function snapshot(
  asof: string,
  rows: UnusualFlowRow[],
  tape: MarketFlowPrint[],
): FlowPulsePayload {
  return { asof, generated_at: asof, rows, tape }
}

describe('flow snapshot pulse', () => {
  it('treats the first snapshot as a baseline rather than invented new flow', () => {
    const current = snapshot('2026-08-11T17:00:00Z', [aggregate('SPY', 1, 100_000)], [
      print('SPY', '2026-08-11T16:59:59Z', 25_000),
    ])
    const pulse = buildFlowPulse(null, current)
    expect(pulse.baseline).toBe(true)
    expect(pulse.newPrintCount).toBe(0)
    expect(pulse.newPremium).toBe(0)
  })

  it('finds incoming prints, rolling-window exits, premium deltas, and rank moves', () => {
    const retained = print('SPY', '2026-08-11T16:59:59Z', 25_000)
    const expired = print('QQQ', '2026-08-11T16:59:58Z', 30_000)
    const incoming = print('SPY', '2026-08-11T17:00:14Z', 80_000)
    const before = snapshot(
      '2026-08-11T17:00:00Z',
      [aggregate('QQQ', 1, 150_000), aggregate('SPY', 2, 100_000)],
      [retained, expired],
    )
    const after = snapshot(
      '2026-08-11T17:00:14Z',
      [aggregate('SPY', 1, 180_000), aggregate('QQQ', 2, 120_000)],
      [incoming, retained],
    )

    const pulse = buildFlowPulse(before, after)
    expect(pulse.baseline).toBe(false)
    expect(pulse.asofAdvanced).toBe(true)
    expect(pulse.newPrintCount).toBe(1)
    expect(pulse.newPremium).toBe(80_000)
    expect(pulse.expiredPrintCount).toBe(1)
    expect(pulse.netWindowPremiumChange).toBe(50_000)
    expect(pulse.bySymbol.get('SPY')).toMatchObject({
      newPrints: 1,
      newPremium: 80_000,
      windowPremiumDelta: 80_000,
      rankMove: 1,
    })
    expect(pulse.newPrintKeys.has(flowPrintKey(incoming))).toBe(true)
  })

  it('handles duplicate provider prints as a multiset', () => {
    const duplicate = print('IWM', '2026-08-11T17:00:00Z', 40_000)
    const before = snapshot('2026-08-11T17:00:00Z', [aggregate('IWM', 1, 40_000)], [duplicate])
    const after = snapshot('2026-08-11T17:00:15Z', [aggregate('IWM', 1, 80_000)], [duplicate, { ...duplicate }])
    const pulse = buildFlowPulse(before, after)
    expect(pulse.newPrintCount).toBe(1)
    expect(pulse.newPremium).toBe(40_000)
  })

  it('keeps the last good window when a poll arrives without a new payload', () => {
    const current = snapshot('2026-08-11T17:00:00Z', [aggregate('SPY', 1, 100_000)], [
      print('SPY', '2026-08-11T16:59:59Z', 25_000),
    ])
    const held = applyFlowWindow(current, null)
    expect(held.window).toBe(current)
    expect(held.window?.rows).toHaveLength(1)
    expect(held.window?.tape).toHaveLength(1)
    expect(held.pulse).toBeNull()
  })

  it('updates pulse copy when a new provider window lands', () => {
    const retained = print('SPY', '2026-08-11T16:59:59Z', 25_000)
    const incoming = print('SPY', '2026-08-11T17:00:14Z', 80_000)
    const before = snapshot('2026-08-11T17:00:00Z', [aggregate('SPY', 1, 100_000)], [retained])
    const after = snapshot('2026-08-11T17:00:14Z', [aggregate('SPY', 1, 180_000)], [incoming, retained])
    const applied = applyFlowWindow(before, after)
    expect(applied.window).toBe(after)
    expect(applied.pulse?.baseline).toBe(false)
    expect(applied.pulse?.newPrintCount).toBe(1)
    expect(applied.pulse?.newPremium).toBe(80_000)
  })
})
