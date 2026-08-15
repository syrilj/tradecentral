export interface DefinedRiskSizingInput {
  accountEquity: number
  riskPct: number
  maxRiskPct: number
  portfolioHeatPct: number
  openRiskDollars: number
  netDebit: number | null
  spreadWidth?: number | null
  eligible: boolean
}

export interface DefinedRiskSizing {
  accountRiskBudget: number
  portfolioRiskBudget: number
  remainingPortfolioHeat: number
  effectiveBudget: number
  perContractRisk: number | null
  contracts: number
  maxLoss: number
  maxProfit: number | null
  rewardRisk: number | null
  state: 'ready' | 'blocked' | 'quote_required' | 'no_capacity'
}

function finiteNonNegative(value: number | null | undefined): number {
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, number) : 0
}

/**
 * Fail-closed sizing for a long debit or debit spread. The server owns the
 * maximum risk policies; the operator may choose a smaller per-trade risk.
 * No live debit means no contracts, and open portfolio risk consumes heat
 * before the per-trade budget is considered.
 */
export function sizeDefinedRisk(input: DefinedRiskSizingInput): DefinedRiskSizing {
  const equity = finiteNonNegative(input.accountEquity)
  const maxRiskPct = finiteNonNegative(input.maxRiskPct)
  const selectedRiskPct = Math.min(finiteNonNegative(input.riskPct), maxRiskPct)
  const portfolioHeatPct = finiteNonNegative(input.portfolioHeatPct)
  const openRisk = finiteNonNegative(input.openRiskDollars)
  const debit = input.netDebit == null ? null : finiteNonNegative(input.netDebit)
  const width = input.spreadWidth == null ? null : finiteNonNegative(input.spreadWidth)

  const accountRiskBudget = equity * selectedRiskPct
  const portfolioRiskBudget = equity * portfolioHeatPct
  const remainingPortfolioHeat = Math.max(0, portfolioRiskBudget - openRisk)
  const effectiveBudget = Math.min(accountRiskBudget, remainingPortfolioHeat)
  const perContractRisk = debit != null && debit > 0 ? debit * 100 : null

  let state: DefinedRiskSizing['state'] = 'ready'
  if (!input.eligible) state = 'blocked'
  else if (perContractRisk == null) state = 'quote_required'
  else if (effectiveBudget < perContractRisk) state = 'no_capacity'

  const contracts = state === 'ready' && perContractRisk != null
    ? Math.max(0, Math.floor(effectiveBudget / perContractRisk))
    : 0
  const maxLoss = contracts * (perContractRisk ?? 0)
  const maxProfit = contracts > 0 && width != null && debit != null && width > debit
    ? contracts * (width - debit) * 100
    : null
  const rewardRisk = maxProfit != null && maxLoss > 0 ? maxProfit / maxLoss : null

  return {
    accountRiskBudget,
    portfolioRiskBudget,
    remainingPortfolioHeat,
    effectiveBudget,
    perContractRisk,
    contracts,
    maxLoss,
    maxProfit,
    rewardRisk,
    state,
  }
}
