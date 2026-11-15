/**
 * Sector-rotation readouts. A missing return or flow score stays missing.
 * `null * 100` is 0 in JavaScript, and `null >= 0` is true, so a blank SPY
 * return or a blank watch score used to render as +0.00% and "money in".
 */
import { DASH, signedPct } from './format'

export function formatReturnPct(value: unknown, dp = 2): string {
  if (value == null || value === '') return DASH
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return DASH
  return signedPct(n * 100, dp)
}

export function benchmarkTrendLabel(above: unknown): string {
  if (above === true) return 'ABOVE MA20'
  if (above === false) return 'BELOW MA20'
  return 'MA20 UNAVAILABLE'
}

export function benchmarkTrendTone(above: unknown): 'pos' | 'neg' | 'flat' {
  if (above === true) return 'pos'
  if (above === false) return 'neg'
  return 'flat'
}

export type FlowLean = 'in' | 'out' | 'flat' | 'missing'

export function flowLean(score: number | null | undefined): FlowLean {
  if (score == null || !Number.isFinite(score)) return 'missing'
  if (score > 0) return 'in'
  if (score < 0) return 'out'
  return 'flat'
}

export function flowLeanLabel(score: number | null | undefined): string {
  const lean = flowLean(score)
  if (lean === 'in') return 'money in'
  if (lean === 'out') return 'money out'
  if (lean === 'flat') return 'flat'
  return 'UNMEASURED'
}

export function watchMatchesFlow(
  score: number | null | undefined,
  category: 'all' | 'in' | 'out',
): boolean {
  if (category === 'all') return true
  const lean = flowLean(score)
  if (lean === 'missing' || lean === 'flat') return false
  return lean === category
}

/** Width of a sector rotation bar. Missing and flat scores take no ink. */
export function flowTrackWidth(score: number | null | undefined, scale: number): string {
  const lean = flowLean(score)
  if (lean !== 'in' && lean !== 'out') return '0%'
  const denom = Number.isFinite(scale) && scale > 0 ? scale : 1
  return `${Math.min(100, (Math.abs(score as number) / denom) * 100)}%`
}

export function flowBarStyle(
  score: number | null | undefined,
  scale: number,
): { side: 'in' | 'out' | 'none'; width: string } {
  const lean = flowLean(score)
  if (lean !== 'in' && lean !== 'out') return { side: 'none', width: '0%' }
  const denom = Number.isFinite(scale) && scale > 0 ? scale : 1
  const width = Math.min(50, (Math.abs(score as number) / denom) * 50)
  return { side: lean, width: `${width}%` }
}

export function topFlowRow<T extends { flow_score?: number | null }>(
  rows: T[],
  direction: 'in' | 'out',
): T | null {
  let best: T | null = null
  for (const row of rows) {
    if (flowLean(row.flow_score) !== direction) continue
    if (best == null) {
      best = row
      continue
    }
    const next = row.flow_score as number
    const current = best.flow_score as number
    if (direction === 'in' ? next > current : next < current) best = row
  }
  return best
}
