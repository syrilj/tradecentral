import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { classifyBacktestEdge } from '@/setupBacktest'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')

describe('setupBacktest edge classification', () => {
  it('identifies insufficient sample when total_trades < 5', () => {
    const res = classifyBacktestEdge({
      total_trades: 3,
      profit_factor: 2.5,
      win_rate: 66.7,
      window: '1Y',
    })
    expect(res.tone).toBe('sample-low')
    expect(res.label).toBe('INSUFFICIENT SAMPLE')
    expect(res.detail).toContain('3 trades simulated in 1Y')
    expect(res.detail).toContain('Minimum 5 trades required')
  })

  it('confirms historical edge when profit factor >= 1.2 and win rate >= 50%', () => {
    const res = classifyBacktestEdge({
      total_trades: 24,
      profit_factor: 1.65,
      win_rate: 58.3,
      window: '1Y',
    })
    expect(res.tone).toBe('confirmed')
    expect(res.label).toBe('HISTORICAL EDGE CONFIRMED')
    expect(res.detail).toContain(
      'Profit factor 1.65 with 58.3% win rate across 24 sequential events',
    )
  })

  it('classifies marginal historical edge when profit factor is between 1.0 and 1.2', () => {
    const res = classifyBacktestEdge({
      total_trades: 18,
      profit_factor: 1.08,
      win_rate: 44.4,
      window: '1Y',
    })
    expect(res.tone).toBe('marginal')
    expect(res.label).toBe('MARGINAL HISTORICAL EDGE')
    expect(res.detail).toContain(
      'Profit factor 1.08 near breakeven after 2 bps slippage and commissions',
    )
  })

  it('flags negative historical expectancy when profit factor < 1.0', () => {
    const res = classifyBacktestEdge({
      total_trades: 30,
      profit_factor: 0.82,
      win_rate: 36.7,
      window: '2Y',
    })
    expect(res.tone).toBe('negative')
    expect(res.label).toBe('NEGATIVE HISTORICAL EXPECTANCY')
    expect(res.detail).toContain('Profit factor 0.82 with negative expectancy')
  })
})

describe('SetupBacktestCard and SuggestView structural contracts', () => {
  const cardPath = join(srcRoot, 'components', 'SetupBacktestCard.vue')
  const viewPath = join(srcRoot, 'views', 'SuggestView.vue')
  const cardSrc = readFileSync(cardPath, 'utf8')
  const viewSrc = readFileSync(viewPath, 'utf8')

  it('SetupBacktestCard invokes api.systematicBacktest with realistic friction parameters', () => {
    expect(cardSrc).toContain('api.systematicBacktest(')
    expect(cardSrc).toContain('slippage_bps: 2.0')
    expect(cardSrc).toContain('capital: 100_000')
    expect(cardSrc).toContain('risk_pct: 0.02')
    expect(cardSrc).toContain("bars: 'daily'")
  })

  it('SetupBacktestCard provides 3M, 6M, 1Y, 2Y, ALL backtest horizon controls', () => {
    expect(cardSrc).toContain('WINDOW_OPTIONS')
    expect(cardSrc).toContain("'3M', '6M', '1Y', '2Y', 'ALL'")
    expect(cardSrc).toContain('role="group"')
    expect(cardSrc).toContain('aria-label="Backtest window selector"')
  })

  it('SetupBacktestCard renders an interactive SVG equity curve with hover scrubber', () => {
    expect(cardSrc).toContain('equity-chart-box')
    expect(cardSrc).toContain('equity-svg')
    expect(cardSrc).toContain('baseline-line')
    expect(cardSrc).toContain('equity-area')
    expect(cardSrc).toContain('equity-stroke')
    expect(cardSrc).toContain('onChartMouseMove')
    expect(cardSrc).toContain('onChartMouseLeave')
    expect(cardSrc).toContain('scrub-readout')
    expect(cardSrc).toContain('scrub-guide-line')
  })

  it('SetupBacktestCard renders realistic execution disclosures and friction deduction', () => {
    expect(cardSrc).toContain('HONEST FRICTION MODEL')
    expect(cardSrc).toContain('2.0 bps entry/exit slippage')
    expect(cardSrc).toContain('$0.005/share commissions')
    expect(cardSrc).toContain('zero lookahead')
    expect(cardSrc).toContain('Friction deducted')
    expect(cardSrc).toContain('gamma_conditioned')
  })

  it('SetupBacktestCard renders core statistical metrics and recent trades with reason pills', () => {
    expect(cardSrc).toContain('Win Rate')
    expect(cardSrc).toContain('Profit Factor')
    expect(cardSrc).toContain('Net Return')
    expect(cardSrc).toContain('Max Drawdown')
    expect(cardSrc).toContain('Sharpe Ratio')
    expect(cardSrc).toContain('Expectancy / Trade')
    expect(cardSrc).toContain('reason-pill')
  })

  it('SuggestView imports and mounts SetupBacktestCard in the detail inspector', () => {
    expect(viewSrc).toContain("import SetupBacktestCard from '@/components/SetupBacktestCard.vue'")
    expect(viewSrc).toContain('<SetupBacktestCard')
    expect(viewSrc).toContain(':symbol="active.symbol"')
  })

  it('strictly adheres to decision-support and no broker orders', () => {
    expect(cardSrc.toLowerCase()).not.toContain('submit order')
    expect(cardSrc.toLowerCase()).not.toContain('place order')
    expect(cardSrc.toLowerCase()).not.toContain('buy now')
  })
})
