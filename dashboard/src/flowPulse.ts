import type { MarketFlowPrint, UnusualFlowPayload, UnusualFlowRow } from '@/api'

export type FlowPulsePayload = Pick<UnusualFlowPayload, 'asof' | 'generated_at' | 'rows' | 'tape'>

export interface SymbolPulse {
  newPrints: number
  newPremium: number
  windowPremiumDelta: number
  rankMove: number | null
}

export interface FlowPulse {
  baseline: boolean
  asofAdvanced: boolean
  newPrintCount: number
  newPremium: number
  expiredPrintCount: number
  netWindowPremiumChange: number
  changedSymbolCount: number
  newPrintKeys: Set<string>
  bySymbol: Map<string, SymbolPulse>
}

function finite(value: unknown): number | null {
  const number = Number(value)
  return value !== null && value !== undefined && value !== '' && Number.isFinite(number)
    ? number
    : null
}

function rowPremium(row: UnusualFlowRow | undefined): number {
  return finite(row?.premium) ?? 0
}

export function flowReviewScore(row: UnusualFlowRow, maxPremium: number): number {
  const premium = rowPremium(row)
  const contracts = finite(row.contract_count) ?? 0
  const sweepPremium = finite(row.sweep_premium) ?? 0
  const unusualContracts = finite(row.unusual_contracts) ?? 0
  const size = maxPremium > 0 ? premium / maxPremium : 0
  const sweepShare = premium > 0 ? Math.max(0, Math.min(1, sweepPremium / premium)) : 0
  const flaggedShare = contracts > 0 ? Math.max(0, Math.min(1, unusualContracts / contracts)) : 0
  return size * 0.5 + sweepShare * 0.3 + flaggedShare * 0.2
}

export function compareFlowReviewRows(
  a: UnusualFlowRow,
  b: UnusualFlowRow,
  maxPremium: number,
): number {
  return (
    flowReviewScore(b, maxPremium) - flowReviewScore(a, maxPremium) ||
    rowPremium(b) - rowPremium(a) ||
    a.symbol.localeCompare(b.symbol)
  )
}

function reviewRanks(rows: UnusualFlowRow[]): Map<string, number> {
  const maxPremium = Math.max(1, ...rows.map((row) => rowPremium(row)))
  return new Map(
    [...rows]
      .sort((a, b) => compareFlowReviewRows(a, b, maxPremium))
      .map((row, index) => [row.symbol, index + 1]),
  )
}

/** Stable enough to compare overlapping bounded provider windows. */
export function flowPrintKey(row: MarketFlowPrint): string {
  return [
    row.timestamp,
    row.symbol ?? '',
    row.right,
    row.expiry ?? '',
    finite(row.strike) ?? '',
    finite(row.price) ?? '',
    finite(row.contracts ?? row.volume) ?? '',
    finite(row.premium) ?? '',
  ].join('|')
}

function printCounts(rows: MarketFlowPrint[]): Map<string, number> {
  const counts = new Map<string, number>()
  for (const row of rows) {
    const key = flowPrintKey(row)
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return counts
}

function blankSymbolPulse(): SymbolPulse {
  return { newPrints: 0, newPremium: 0, windowPremiumDelta: 0, rankMove: null }
}

/**
 * Apply a provider window without blanking the desk.
 * A null/empty refresh keeps the last good tape; a new window updates pulse copy.
 */
export function applyFlowWindow(
  previous: FlowPulsePayload | null,
  next: FlowPulsePayload | null,
): { window: FlowPulsePayload | null; pulse: FlowPulse | null } {
  if (!next) return { window: previous, pulse: null }
  return { window: next, pulse: buildFlowPulse(previous, next) }
}

export function buildFlowPulse(
  previous: FlowPulsePayload | null,
  current: FlowPulsePayload,
): FlowPulse {
  if (!previous) {
    return {
      baseline: true,
      asofAdvanced: false,
      newPrintCount: 0,
      newPremium: 0,
      expiredPrintCount: 0,
      netWindowPremiumChange: 0,
      changedSymbolCount: 0,
      newPrintKeys: new Set(),
      bySymbol: new Map(),
    }
  }

  const previousRows = new Map(previous.rows.map((row) => [row.symbol, row]))
  const currentRows = new Map(current.rows.map((row) => [row.symbol, row]))
  const previousRanks = reviewRanks(previous.rows)
  const currentRanks = reviewRanks(current.rows)
  const bySymbol = new Map<string, SymbolPulse>()

  for (const symbol of new Set([...previousRows.keys(), ...currentRows.keys()])) {
    const before = previousRows.get(symbol)
    const after = currentRows.get(symbol)
    const beforeRank = previousRanks.get(symbol)
    const afterRank = currentRanks.get(symbol)
    const pulse = blankSymbolPulse()
    pulse.windowPremiumDelta = rowPremium(after) - rowPremium(before)
    pulse.rankMove = beforeRank != null && afterRank != null ? beforeRank - afterRank : null
    bySymbol.set(symbol, pulse)
  }

  const remainingPrevious = printCounts(previous.tape ?? [])
  const newPrintKeys = new Set<string>()
  let newPrintCount = 0
  let newPremium = 0

  for (const row of current.tape ?? []) {
    const key = flowPrintKey(row)
    const remaining = remainingPrevious.get(key) ?? 0
    if (remaining > 0) {
      remainingPrevious.set(key, remaining - 1)
      continue
    }
    newPrintKeys.add(key)
    newPrintCount += 1
    const premium = finite(row.premium) ?? 0
    newPremium += premium
    const symbol = row.symbol ?? ''
    if (symbol) {
      const pulse = bySymbol.get(symbol) ?? blankSymbolPulse()
      pulse.newPrints += 1
      pulse.newPremium += premium
      bySymbol.set(symbol, pulse)
    }
  }

  const expiredPrintCount = [...remainingPrevious.values()].reduce((sum, count) => sum + count, 0)
  const netWindowPremiumChange =
    current.rows.reduce((sum, row) => sum + rowPremium(row), 0) -
    previous.rows.reduce((sum, row) => sum + rowPremium(row), 0)
  const changedSymbolCount = [...bySymbol.values()].filter(
    (pulse) =>
      pulse.newPrints > 0 ||
      Math.abs(pulse.windowPremiumDelta) >= 1 ||
      (pulse.rankMove != null && pulse.rankMove !== 0),
  ).length

  return {
    baseline: false,
    asofAdvanced: current.asof !== previous.asof,
    newPrintCount,
    newPremium,
    expiredPrintCount,
    netWindowPremiumChange,
    changedSymbolCount,
    newPrintKeys,
    bySymbol,
  }
}
