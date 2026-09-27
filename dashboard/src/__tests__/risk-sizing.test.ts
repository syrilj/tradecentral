import { describe, expect, it } from 'vitest'
import { sizeDefinedRisk } from '@/riskSizing'

const base = {
  accountEquity: 100_000,
  riskPct: 0.005,
  maxRiskPct: 0.005,
  portfolioHeatPct: 0.02,
  openRiskDollars: 0,
  netDebit: 2,
  spreadWidth: 5,
  eligible: true,
}

describe('defined-risk position sizing', () => {
  it('sizes contracts from the tighter of trade risk and remaining portfolio heat', () => {
    const result = sizeDefinedRisk(base)
    expect(result.effectiveBudget).toBe(500)
    expect(result.contracts).toBe(2)
    expect(result.maxLoss).toBe(400)
    expect(result.maxProfit).toBe(600)
    expect(result.rewardRisk).toBe(1.5)
    expect(result.state).toBe('ready')
  })

  it('subtracts existing risk from portfolio heat', () => {
    const result = sizeDefinedRisk({ ...base, openRiskDollars: 1_700 })
    expect(result.remainingPortfolioHeat).toBe(300)
    expect(result.effectiveBudget).toBe(300)
    expect(result.contracts).toBe(1)
  })

  it('never sizes without an eligible setup and live debit', () => {
    expect(sizeDefinedRisk({ ...base, eligible: false }).contracts).toBe(0)
    expect(sizeDefinedRisk({ ...base, eligible: false }).state).toBe('blocked')
    expect(sizeDefinedRisk({ ...base, netDebit: null }).contracts).toBe(0)
    expect(sizeDefinedRisk({ ...base, netDebit: null }).state).toBe('quote_required')
  })

  it('clamps operator risk to the server policy ceiling', () => {
    const result = sizeDefinedRisk({ ...base, riskPct: 0.5 })
    expect(result.accountRiskBudget).toBe(500)
  })
})
