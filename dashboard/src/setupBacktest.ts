/**
 * Statistical edge classification and presentation logic for setup backtesting.
 */

import { num } from './format'

export type EdgeClassificationTone = 'confirmed' | 'marginal' | 'negative' | 'sample-low'

export interface BacktestEdgeStatus {
  label: string
  tone: EdgeClassificationTone
  detail: string
}

export function classifyBacktestEdge(input: {
  total_trades: number
  profit_factor: number
  win_rate: number
  window?: string
}): BacktestEdgeStatus {
  const { total_trades, profit_factor, win_rate, window = '1Y' } = input
  if (total_trades < 5) {
    return {
      label: 'INSUFFICIENT SAMPLE',
      tone: 'sample-low',
      detail: `${total_trades} trades simulated in ${window}. Minimum 5 trades required to assess edge.`,
    }
  }
  if (profit_factor >= 1.2 && win_rate >= 50.0) {
    return {
      label: 'HISTORICAL EDGE CONFIRMED',
      tone: 'confirmed',
      detail: `Profit factor ${num(profit_factor, 2)} with ${num(win_rate, 1)}% win rate across ${total_trades} sequential events.`,
    }
  }
  if (profit_factor >= 1.0) {
    return {
      label: 'MARGINAL HISTORICAL EDGE',
      tone: 'marginal',
      detail: `Profit factor ${num(profit_factor, 2)} near breakeven after 2 bps slippage and commissions.`,
    }
  }
  return {
    label: 'NEGATIVE HISTORICAL EXPECTANCY',
    tone: 'negative',
    detail: `Profit factor ${num(profit_factor, 2)} with negative expectancy. Statistical drag observed under execution friction.`,
  }
}
