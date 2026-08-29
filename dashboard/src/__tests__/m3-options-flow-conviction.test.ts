import { describe, expect, it } from 'vitest'
import type { OptionsBoardRow, OptionsTapeRow } from '@/api'

describe('M3: Options Flow Context & C/P Zero-Division Guards', () => {
  function computePremiumSplit(
    tape: OptionsTapeRow[],
    summary?: { call_premium?: number; put_premium?: number },
  ) {
    let call = 0
    let put = 0
    let fromTape = false
    let classifiedCount = 0

    if (tape.length) {
      fromTape = true
      for (const row of tape) {
        const prem = Number(row.premium)
        if (!Number.isFinite(prem) || prem < 0) continue
        if (row.right === 'call') {
          call += prem
          classifiedCount += 1
        } else if (row.right === 'put') {
          put += prem
          classifiedCount += 1
        }
      }
    }

    if (!fromTape || call + put <= 0) {
      call = summary?.call_premium ?? 0
      put = summary?.put_premium ?? 0
      fromTape = false
    }

    const total = call + put
    const hasPrem = total > 0 && (fromTape ? classifiedCount > 0 : call > 0 || put > 0)
    const callPct = hasPrem ? Math.round((call / total) * 100) : 0
    const putPct = hasPrem ? 100 - callPct : 0
    const dominantPct = Math.max(callPct, putPct)
    const tone = !hasPrem ? 'neutral' : callPct >= 58 ? 'call' : putPct >= 58 ? 'put' : 'neutral'
    const conviction = hasPrem
      ? dominantPct >= 72
        ? 'HIGH'
        : dominantPct >= 62
          ? 'MED'
          : 'LOW'
      : 'NONE'
    const ratio = hasPrem && put > 0 ? call / put : null

    const label =
      tone === 'call'
        ? 'CALL-HEAVY ACTIVITY'
        : tone === 'put'
          ? 'PUT-HEAVY ACTIVITY'
          : total > 0
            ? 'BALANCED ACTIVITY'
            : 'NO ACTIVITY MIX'

    return {
      call,
      put,
      total,
      callPct,
      putPct,
      ratio,
      fromTape,
      tone,
      conviction,
      label,
    }
  }

  it('handles empty tape and empty summary without false 1.00 / 50-50 ratio', () => {
    const res = computePremiumSplit([], { call_premium: 0, put_premium: 0 })
    expect(res.callPct).toBe(0)
    expect(res.putPct).toBe(0)
    expect(res.total).toBe(0)
    expect(res.ratio).toBeNull()
    expect(res.tone).toBe('neutral')
    expect(res.conviction).toBe('NONE')
    expect(res.label).toBe('NO ACTIVITY MIX')
  })

  it('handles unclassified or invalid tape rows safely', () => {
    const tape = [
      { right: 'call', premium: -500 } as unknown as OptionsTapeRow,
      { right: 'put', premium: NaN } as unknown as OptionsTapeRow,
    ]
    const res = computePremiumSplit(tape)
    expect(res.callPct).toBe(0)
    expect(res.putPct).toBe(0)
    expect(res.ratio).toBeNull()
    expect(res.conviction).toBe('NONE')
  })

  it('computes call-heavy activity without zero division when put premium is 0', () => {
    const tape = [
      { right: 'call', premium: 150_000 } as OptionsTapeRow,
      { right: 'call', premium: 50_000 } as OptionsTapeRow,
    ]
    const res = computePremiumSplit(tape)
    expect(res.call).toBe(200_000)
    expect(res.put).toBe(0)
    expect(res.callPct).toBe(100)
    expect(res.putPct).toBe(0)
    expect(res.ratio).toBeNull()
    expect(res.tone).toBe('call')
    expect(res.conviction).toBe('HIGH')
    expect(res.label).toBe('CALL-HEAVY ACTIVITY')
  })

  it('computes put-heavy activity and valid ratio when both exist', () => {
    const tape = [
      { right: 'call', premium: 50_000 } as OptionsTapeRow,
      { right: 'put', premium: 150_000 } as OptionsTapeRow,
    ]
    const res = computePremiumSplit(tape)
    expect(res.call).toBe(50_000)
    expect(res.put).toBe(150_000)
    expect(res.callPct).toBe(25)
    expect(res.putPct).toBe(75)
    expect(res.ratio).toBeCloseTo(0.333, 2)
    expect(res.tone).toBe('put')
    expect(res.conviction).toBe('HIGH')
    expect(res.label).toBe('PUT-HEAVY ACTIVITY')
  })
})

describe('M3: Conviction Board Pressure Score Dampening', () => {
  function computePressureScore(row: Partial<OptionsBoardRow>): {
    score: number
    signed: number
    tone: 'pos' | 'neg' | 'neutral'
    label: string
  } {
    const callPrem = Number(row.call_premium ?? 0)
    const putPrem = Number(row.put_premium ?? 0)
    const totalPrem = callPrem + putPrem
    const dampener = totalPrem > 0 ? Math.min(1, Math.max(0.15, totalPrem / 100_000)) : 1

    if (row.squeeze_score != null && Number.isFinite(row.squeeze_score)) {
      const rawSigned = Math.max(-100, Math.min(100, row.squeeze_score))
      const signed =
        row.selection_basis === 'live_options_flow' && totalPrem > 0
          ? rawSigned * dampener
          : rawSigned
      const score = Math.abs(signed)
      const tone = signed > 0.5 ? 'pos' : signed < -0.5 ? 'neg' : 'neutral'
      return { score, signed, tone, label: `${signed > 0 ? '+' : ''}${signed.toFixed(1)}` }
    }
    if (row.activity_imbalance != null && Number.isFinite(row.activity_imbalance)) {
      const rawSigned = Math.max(-1, Math.min(1, row.activity_imbalance)) * 100
      const signed = rawSigned * (totalPrem > 0 ? dampener : 0.5)
      const score = Math.abs(signed)
      const tone = signed > 0.5 ? 'pos' : signed < -0.5 ? 'neg' : 'neutral'
      return { score, signed, tone, label: `${signed > 0 ? '+' : ''}${signed.toFixed(1)}` }
    }
    if (row.net_gex_m != null && Number.isFinite(row.net_gex_m)) {
      const gex = row.net_gex_m
      const tone = gex > 0 ? 'pos' : gex < 0 ? 'neg' : 'neutral'
      const score = Math.min(100, Math.abs(gex) * 10)
      return { score, signed: gex, tone, label: `${gex > 0 ? '+' : ''}${gex.toFixed(1)}M` }
    }
    if (row.selection_score != null && Number.isFinite(row.selection_score)) {
      const score = Math.min(100, row.selection_score)
      return { score, signed: score, tone: 'neutral', label: `${score.toFixed(1)}` }
    }
    return { score: 0, signed: 0, tone: 'neutral', label: '0.0' }
  }

  it('dampens pressure score delta for small live flow prints (<$100k)', () => {
    const smallRow: Partial<OptionsBoardRow> = {
      selection_basis: 'live_options_flow',
      squeeze_score: 80,
      call_premium: 20_000,
      put_premium: 0,
    }
    const res = computePressureScore(smallRow)
    // 80 * (20_000 / 100_000) = 16.0
    expect(res.score).toBeCloseTo(16.0, 1)
    expect(res.signed).toBeCloseTo(16.0, 1)
    expect(res.tone).toBe('pos')
    expect(res.label).toBe('+16.0')
  })

  it('gives full weighting to institutional flow prints (>= $100k)', () => {
    const largeRow: Partial<OptionsBoardRow> = {
      selection_basis: 'live_options_flow',
      squeeze_score: 80,
      call_premium: 150_000,
      put_premium: 50_000,
    }
    const res = computePressureScore(largeRow)
    expect(res.score).toBe(80)
    expect(res.signed).toBe(80)
    expect(res.tone).toBe('pos')
    expect(res.label).toBe('+80.0')
  })

  it('handles negative squeeze scores (bearish pressure)', () => {
    const bearRow: Partial<OptionsBoardRow> = {
      selection_basis: 'pead_ordinal',
      squeeze_score: -45.5,
    }
    const res = computePressureScore(bearRow)
    expect(res.score).toBe(45.5)
    expect(res.signed).toBe(-45.5)
    expect(res.tone).toBe('neg')
    expect(res.label).toBe('-45.5')
  })

  it('handles net GEX fallback when squeeze score is unmeasured', () => {
    const gexRow: Partial<OptionsBoardRow> = {
      squeeze_score: null,
      net_gex_m: 4.2,
    }
    const res = computePressureScore(gexRow)
    expect(res.score).toBe(42)
    expect(res.signed).toBe(4.2)
    expect(res.tone).toBe('pos')
    expect(res.label).toBe('+4.2M')
  })

  it('returns neutral and unmeasured mark when no metrics exist', () => {
    const emptyRow: Partial<OptionsBoardRow> = {
      squeeze_score: null,
      net_gex_m: null,
      selection_score: null,
    }
    const res = computePressureScore(emptyRow)
    expect(res.score).toBe(0)
    expect(res.signed).toBe(0)
    expect(res.tone).toBe('neutral')
    expect(res.label).toBe('0.0')
  })
})

describe('M3: Moneyness and Strike Distance Null/Zero Guards', () => {
  function isItm(
    row: { right: string; strike: number | null; underlying_price?: number | null },
    spot?: number | null,
  ): boolean {
    const spotPrice = row.underlying_price ?? spot
    if (spotPrice == null || spotPrice <= 0 || row.strike == null || row.strike <= 0) return false
    return row.right === 'call' ? spotPrice > row.strike : spotPrice < row.strike
  }

  function moneynessInfo(
    row: { right: string; strike: number | null; underlying_price?: number | null },
    spot?: number | null,
  ) {
    const spotPrice = row.underlying_price ?? spot
    if (spotPrice == null || spotPrice <= 0 || row.strike == null || row.strike <= 0) return null
    const diffPct = ((spotPrice - row.strike) / row.strike) * 100
    if (!Number.isFinite(diffPct)) return null
    const isCall = row.right === 'call'
    const inTheMoney = isCall ? diffPct > 0.1 : diffPct < -0.1
    const atTheMoney = Math.abs(diffPct) <= 0.1

    if (atTheMoney) return { text: 'ATM', cls: 'atm' }
    const dist = Math.abs(diffPct).toFixed(1)
    if (inTheMoney) {
      return { text: `+${dist}% ITM`, cls: 'itm' }
    }
    return { text: `${dist}% OTM`, cls: 'otm' }
  }

  function wallPct(
    side: 'call' | 'put',
    spot: number | null | undefined,
    callWall: number | null | undefined,
    putWall: number | null | undefined,
  ) {
    const wall = side === 'call' ? callWall : putWall
    if (spot == null || spot <= 0 || wall == null || wall <= 0) return null
    const calc = (wall - spot) / spot
    return Number.isFinite(calc) ? calc : null
  }

  it('safely guards when spot is null, zero, or negative', () => {
    expect(isItm({ right: 'call', strike: 100 }, null)).toBe(false)
    expect(isItm({ right: 'call', strike: 100 }, 0)).toBe(false)
    expect(isItm({ right: 'call', strike: 100 }, -50)).toBe(false)

    expect(moneynessInfo({ right: 'call', strike: 100 }, null)).toBeNull()
    expect(moneynessInfo({ right: 'call', strike: 100 }, 0)).toBeNull()
    expect(moneynessInfo({ right: 'call', strike: 100 }, -50)).toBeNull()

    expect(wallPct('call', null, 110, 90)).toBeNull()
    expect(wallPct('call', 0, 110, 90)).toBeNull()
    expect(wallPct('call', -10, 110, 90)).toBeNull()
  })

  it('safely guards when strike or wall is null, zero, or negative', () => {
    expect(isItm({ right: 'call', strike: null }, 100)).toBe(false)
    expect(isItm({ right: 'call', strike: 0 }, 100)).toBe(false)
    expect(isItm({ right: 'call', strike: -100 }, 100)).toBe(false)

    expect(moneynessInfo({ right: 'call', strike: null }, 100)).toBeNull()
    expect(moneynessInfo({ right: 'call', strike: 0 }, 100)).toBeNull()
    expect(moneynessInfo({ right: 'call', strike: -100 }, 100)).toBeNull()

    expect(wallPct('call', 100, null, 90)).toBeNull()
    expect(wallPct('call', 100, 0, 90)).toBeNull()
    expect(wallPct('call', 100, -100, 90)).toBeNull()
  })

  it('computes valid moneyness classifications on real market values', () => {
    // 105 spot vs 100 strike Call = ITM (+5%)
    const itmCall = moneynessInfo({ right: 'call', strike: 100 }, 105)
    expect(itmCall).toEqual({ text: '+5.0% ITM', cls: 'itm' })

    // 95 spot vs 100 strike Call = OTM (5%)
    const otmCall = moneynessInfo({ right: 'call', strike: 100 }, 95)
    expect(otmCall).toEqual({ text: '5.0% OTM', cls: 'otm' })

    // 100 spot vs 100 strike Call = ATM
    const atmCall = moneynessInfo({ right: 'call', strike: 100 }, 100)
    expect(atmCall).toEqual({ text: 'ATM', cls: 'atm' })

    // 95 spot vs 100 strike Put = ITM (+5%)
    const itmPut = moneynessInfo({ right: 'put', strike: 100 }, 95)
    expect(itmPut).toEqual({ text: '+5.0% ITM', cls: 'itm' })

    // 105 spot vs 100 strike Put = OTM (5%)
    const otmPut = moneynessInfo({ right: 'put', strike: 100 }, 105)
    expect(otmPut).toEqual({ text: '5.0% OTM', cls: 'otm' })
  })

  it('computes wall percentages cleanly without infinity', () => {
    expect(wallPct('call', 100, 110, 90)).toBeCloseTo(0.1, 4)
    expect(wallPct('put', 100, 110, 90)).toBeCloseTo(-0.1, 4)
  })
})
