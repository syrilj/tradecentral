import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DASH, pctFrac } from '@/format'
import type { OptionsIntelligence, OptionsTapeRow } from '@/api'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const flowDashboardSrc = readFileSync(join(root, 'components', 'FlowDashboard.vue'), 'utf8')
const optionsFlowContextSrc = readFileSync(
  join(root, 'components', 'OptionsFlowContext.vue'),
  'utf8',
)

// Exact pure replica of OptionsFlowContext calculation logic
function computeOptionsFlowContext(
  summary: OptionsIntelligence['summary'] | null | undefined,
  tape: OptionsTapeRow[],
) {
  let call = 0
  let put = 0
  let fromSummary = false

  const hasSummary =
    summary != null && (summary.call_premium != null || summary.put_premium != null)

  if (hasSummary) {
    call = Number(summary?.call_premium) || 0
    put = Number(summary?.put_premium) || 0
    fromSummary = call + put > 0
  }

  let classifiedTapeCount = 0
  if (!fromSummary && tape.length) {
    for (const row of tape) {
      const prem = Number(row.premium)
      if (!Number.isFinite(prem) || prem < 0) continue
      if (row.right === 'call') {
        call += prem
        classifiedTapeCount += 1
      } else if (row.right === 'put') {
        put += prem
        classifiedTapeCount += 1
      }
    }
  }

  const total = call + put
  const hasPrem = total > 0 && (fromSummary || classifiedTapeCount > 0)
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

  const netCall = call - put

  let signed = 0
  for (const row of tape) {
    if (row.signed_premium != null || row.aggressor === 'buy' || row.aggressor === 'sell')
      signed += 1
  }
  const signedCoverage = tape.length ? signed / tape.length : null

  return {
    call,
    put,
    total,
    callPct,
    putPct,
    ratio,
    fromTape: !fromSummary,
    fromSummary,
    netCall,
    tone,
    conviction,
    label,
    signedCoverage,
  }
}

// Exact pure replica of FlowDashboard activeTickerStats calculation logic
function computeFlowDashboardTickerStats(input: {
  callPremium: number
  putPremium: number
  leanState: string
  leanLabel?: string
}) {
  const tot = input.callPremium + input.putPremium
  const callPct = tot > 0 ? Math.round((input.callPremium / tot) * 100) : 50
  const putPct = 100 - callPct

  const dominantState = input.leanState.includes('bullish')
    ? 'bullish'
    : input.leanState.includes('bearish')
      ? 'bearish'
      : 'neutral'
  const dominantLabel =
    input.leanLabel ||
    (dominantState === 'bullish' ? 'BULLISH' : dominantState === 'bearish' ? 'BEARISH' : 'NEUTRAL')

  return {
    callPremium: input.callPremium,
    putPremium: input.putPremium,
    totalPremium: tot,
    callPct,
    putPct,
    dominantState,
    dominantLabel,
  }
}

// Exact pure replica of FlowDashboard cumulative net flow points
function computeFlowTrendPoints(tape: { premium?: number | null; right?: string }[]) {
  if (!tape.length) {
    return []
  }
  let cum = 0
  const points: { x: number; y: number; val: number }[] = []
  const reversed = [...tape].reverse()
  const step = 240 / Math.max(1, reversed.length - 1)
  const values: number[] = []
  for (const r of reversed) {
    const prem = Number.isFinite(Number(r.premium)) ? Number(r.premium) : 0
    cum += r.right === 'call' ? prem : -prem
    values.push(cum)
  }
  const min = Math.min(0, ...values)
  const max = Math.max(1, ...values)
  const range = max - min || 1
  values.forEach((v, i) => {
    const x = Math.round(i * step)
    const y = Math.round(44 - ((v - min) / range) * 38)
    points.push({ x, y, val: v })
  })
  return points
}

describe('Flow & Options Calculation Parity & Reconciliation', () => {
  describe('Group 1: Cross-View Aggregate Parity on Matching Tickers', () => {
    it('reconciles standard institutional volume ($5.0M Total: $3.5M Call / $1.5M Put)', () => {
      const summary: OptionsIntelligence['summary'] = {
        call_premium: 3_500_000,
        put_premium: 1_500_000,
        total_premium: 5_000_000,
        spot: 150,
      } as any

      const optionsRes = computeOptionsFlowContext(summary, [])
      const flowRes = computeFlowDashboardTickerStats({
        callPremium: 3_500_000,
        putPremium: 1_500_000,
        leanState: 'bullish_flow',
      })

      expect(optionsRes.total).toBe(5_000_000)
      expect(flowRes.totalPremium).toBe(5_000_000)
      expect(optionsRes.callPct).toBe(70)
      expect(flowRes.callPct).toBe(70)
      expect(optionsRes.putPct).toBe(30)
      expect(flowRes.putPct).toBe(30)
      expect(optionsRes.netCall).toBe(2_000_000)
      expect(optionsRes.ratio).toBeCloseTo(3.5 / 1.5, 4)
      expect(optionsRes.tone).toBe('call')
      expect(optionsRes.conviction).toBe('MED')
    })

    it('reconciles put-heavy asymmetric volume ($4.0M Total: $0.8M Call / $3.2M Put)', () => {
      const summary: OptionsIntelligence['summary'] = {
        call_premium: 800_000,
        put_premium: 3_200_000,
        spot: 200,
      } as any

      const optionsRes = computeOptionsFlowContext(summary, [])
      const flowRes = computeFlowDashboardTickerStats({
        callPremium: 800_000,
        putPremium: 3_200_000,
        leanState: 'bearish_flow',
      })

      expect(optionsRes.total).toBe(4_000_000)
      expect(flowRes.totalPremium).toBe(4_000_000)
      expect(optionsRes.callPct).toBe(20)
      expect(flowRes.callPct).toBe(20)
      expect(optionsRes.putPct).toBe(80)
      expect(flowRes.putPct).toBe(80)
      expect(optionsRes.netCall).toBe(-2_400_000)
      expect(optionsRes.ratio).toBeCloseTo(0.8 / 3.2, 4)
      expect(optionsRes.tone).toBe('put')
      expect(optionsRes.conviction).toBe('HIGH')
    })

    it('reconciles 100% call flow ($2.5M Call / $0 Put) with zero-division safety', () => {
      const summary: OptionsIntelligence['summary'] = {
        call_premium: 2_500_000,
        put_premium: 0,
        spot: 100,
      } as any

      const optionsRes = computeOptionsFlowContext(summary, [])
      const flowRes = computeFlowDashboardTickerStats({
        callPremium: 2_500_000,
        putPremium: 0,
        leanState: 'bullish_flow',
      })

      expect(optionsRes.total).toBe(2_500_000)
      expect(flowRes.totalPremium).toBe(2_500_000)
      expect(optionsRes.callPct).toBe(100)
      expect(flowRes.callPct).toBe(100)
      expect(optionsRes.putPct).toBe(0)
      expect(flowRes.putPct).toBe(0)
      expect(optionsRes.ratio).toBeNull()
    })

    it('reconciles 100% put flow ($0 Call / $2.5M Put) with zero-division safety', () => {
      const summary: OptionsIntelligence['summary'] = {
        call_premium: 0,
        put_premium: 2_500_000,
        spot: 100,
      } as any

      const optionsRes = computeOptionsFlowContext(summary, [])
      const flowRes = computeFlowDashboardTickerStats({
        callPremium: 0,
        putPremium: 2_500_000,
        leanState: 'bearish_flow',
      })

      expect(optionsRes.total).toBe(2_500_000)
      expect(flowRes.totalPremium).toBe(2_500_000)
      expect(optionsRes.callPct).toBe(0)
      expect(flowRes.callPct).toBe(0)
      expect(optionsRes.putPct).toBe(100)
      expect(flowRes.putPct).toBe(100)
      expect(optionsRes.ratio).toBe(0)
    })

    it('handles zero / unmeasured flow without fabricating numbers', () => {
      const optionsRes = computeOptionsFlowContext(null, [])
      const flowRes = computeFlowDashboardTickerStats({
        callPremium: 0,
        putPremium: 0,
        leanState: 'neutral',
      })

      expect(optionsRes.total).toBe(0)
      expect(flowRes.totalPremium).toBe(0)
      expect(optionsRes.callPct).toBe(0)
      expect(optionsRes.putPct).toBe(0)
      expect(optionsRes.ratio).toBeNull()
      expect(optionsRes.conviction).toBe('NONE')
      expect(optionsRes.label).toBe('NO ACTIVITY MIX')
    })
  })

  describe('Group 2: dominantState and dominantLabel Consistency in FlowDashboard', () => {
    it('aligns bearish direction even when raw call premium share is 70%', () => {
      const stats = computeFlowDashboardTickerStats({
        callPremium: 3_500_000,
        putPremium: 1_500_000,
        leanState: 'bearish',
        leanLabel: 'BEARISH SIGNED FLOW',
      })

      expect(stats.callPct).toBe(70)
      expect(stats.dominantState).toBe('bearish')
      expect(stats.dominantLabel).toBe('BEARISH SIGNED FLOW')
      expect(stats.dominantState).not.toBe('bullish')
    })

    it('aligns bullish direction even when raw put premium share is 70%', () => {
      const stats = computeFlowDashboardTickerStats({
        callPremium: 1_500_000,
        putPremium: 3_500_000,
        leanState: 'bullish',
        leanLabel: 'BULLISH SIGNED FLOW',
      })

      expect(stats.putPct).toBe(70)
      expect(stats.dominantState).toBe('bullish')
      expect(stats.dominantLabel).toBe('BULLISH SIGNED FLOW')
      expect(stats.dominantState).not.toBe('bearish')
    })

    it('aligns neutral direction on balanced flow', () => {
      const stats = computeFlowDashboardTickerStats({
        callPremium: 2_000_000,
        putPremium: 2_000_000,
        leanState: 'neutral',
      })

      expect(stats.dominantState).toBe('neutral')
      expect(stats.dominantLabel).toBe('NEUTRAL')
    })

    it('validates FlowDashboard source does not tie dominantState to raw callPct', () => {
      expect(flowDashboardSrc).not.toMatch(/dominantState:\s*callPct\s*>=\s*55/)
      expect(flowDashboardSrc).toMatch(/dominantState\s*=\s*lean\.state\.includes\('bullish'\)/)
      expect(flowDashboardSrc).toMatch(/dominantLabel/)
    })
  })

  describe('Group 3: Session Totals vs. Tape Slice in OptionsFlowContext', () => {
    it('prioritizes full session summary aggregates over truncated tape slice', () => {
      const summary: OptionsIntelligence['summary'] = {
        call_premium: 30_000_000,
        put_premium: 20_000_000,
        spot: 500,
      } as any

      const tape: OptionsTapeRow[] = [
        { premium: 100_000, right: 'call', signed_premium: 100_000, aggressor: 'buy' } as any,
        { premium: 100_000, right: 'call', signed_premium: 100_000, aggressor: 'buy' } as any,
        { premium: 100_000, right: 'put', signed_premium: -100_000, aggressor: 'sell' } as any,
        { premium: 100_000, right: 'put', signed_premium: -100_000, aggressor: 'sell' } as any,
        { premium: 100_000, right: 'put', signed_premium: -100_000, aggressor: 'sell' } as any,
      ]

      const res = computeOptionsFlowContext(summary, tape)
      expect(res.total).toBe(50_000_000)
      expect(res.callPct).toBe(60)
      expect(res.putPct).toBe(40)
      expect(res.fromSummary).toBe(true)
      expect(res.fromTape).toBe(false)
      expect(res.netCall).toBe(10_000_000)
      expect(tape.length).toBe(5)
    })

    it('falls back to summing tape prints when session summary is missing', () => {
      const tape: OptionsTapeRow[] = [
        { premium: 100_000, right: 'call' } as any,
        { premium: 100_000, right: 'call' } as any,
        { premium: 100_000, right: 'call' } as any,
        { premium: 100_000, right: 'call' } as any,
        { premium: 100_000, right: 'put' } as any,
      ]

      const res = computeOptionsFlowContext(null, tape)
      expect(res.total).toBe(500_000)
      expect(res.callPct).toBe(80)
      expect(res.putPct).toBe(20)
      expect(res.fromSummary).toBe(false)
      expect(res.fromTape).toBe(true)
      expect(res.netCall).toBe(300_000)
    })

    it('formats null signed coverage as DASH instead of fake zero 0.00%', () => {
      const res = computeOptionsFlowContext(null, [])
      expect(res.signedCoverage).toBeNull()

      const formatted = res.signedCoverage == null ? DASH : pctFrac(res.signedCoverage, 0)
      expect(formatted).toBe(DASH)
      expect(formatted).not.toBe('0.00%')
      expect(formatted).not.toBe('0%')
    })

    it('verifies OptionsFlowContext template has SESSION TOTAL labels and DASH fallback', () => {
      expect(optionsFlowContextSrc).toContain(
        "premium.fromSummary ? 'SESSION TOTAL · CONTRACT MIX' : 'DISPLAYED TAPE · CONTRACT MIX'",
      )
      expect(optionsFlowContextSrc).toContain("premium.fromSummary ? 'SESSION TOTAL' : 'TOTAL'")
      expect(optionsFlowContextSrc).toContain(
        "premium.fromSummary ? 'SESSION MIX' : 'IDENTITY MIX'",
      )
      expect(optionsFlowContextSrc).toContain(
        'signedCoverage == null ? DASH : pctFrac(signedCoverage, 0)',
      )
      expect(optionsFlowContextSrc).not.toContain("signedCoverage == null ? '0.00%'")
    })
  })

  describe('Group 4: Net Flow Trend Calculation Parity', () => {
    it('computes cumulative net flow across all prints without hardcoded 24-row slice', () => {
      const tape: { premium: number; right: string }[] = []
      // 30 calls of $100k and 20 puts of $100k -> 50 prints total, Net +$1,000,000
      for (let i = 0; i < 30; i++) {
        tape.push({ premium: 100_000, right: 'call' })
      }
      for (let i = 0; i < 20; i++) {
        tape.push({ premium: 100_000, right: 'put' })
      }

      const pts = computeFlowTrendPoints(tape)
      expect(pts.length).toBe(50)
      expect(pts[pts.length - 1].val).toBe(1_000_000)
    })

    it('returns empty array on empty tape prints without fake mock points', () => {
      const pts = computeFlowTrendPoints([])
      expect(pts).toEqual([])
    })

    it('verifies FlowDashboard does not contain qualifiedTapeRows.value.slice(0, 24)', () => {
      expect(flowDashboardSrc).not.toContain('qualifiedTapeRows.value.slice(0, 24)')
      expect(flowDashboardSrc).toMatch(
        /const tape = qualifiedTapeRows\.value\n\s*if \(!tape\.length\) \{\n\s*return \[\]/,
      )
    })
  })
})
