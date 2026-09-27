import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Institutional Quant Workstation Components', () => {
  const headerRibbon = source('components/RegimeHeaderRibbon.vue')
  const marketContext = source('components/MarketContextCard.vue')
  const keyLevels = source('components/KeyLevelsCard.vue')
  const flowSummary = source('components/FlowSummaryDonutCard.vue')
  const gexChart = source('components/StrikeGammaExposureChart.vue')
  const oiChart = source('components/StrikeOpenInterestChart.vue')
  const netFlowChart = source('components/NetFlowByExpiryChart.vue')
  const realTimeFlow = source('components/RealTimeFlowTape.vue')
  const trajectoryCard = source('components/ForwardTrajectoryCard.vue')
  const volSurface = source('components/VolatilitySurface3D.vue')
  const positioning = source('components/PositioningSummaryCard.vue')
  const timeSeries = source('components/NetGammaSpotTimeSeries.vue')
  const alertsPanel = source('components/LiveAlertsPanel.vue')

  it('RegimeHeaderRibbon surfaces ticker, spot, change, sparkline and 9-metric ribbon', () => {
    expect(headerRibbon).toContain('IV Rank')
    expect(headerRibbon).toContain('IV Percentile')
    expect(headerRibbon).toContain('HV 20D')
    expect(headerRibbon).toContain('HV 30D')
    expect(headerRibbon).toContain('Put/Call Vol')
    expect(headerRibbon).toContain('Gamma Exposure')
    expect(headerRibbon).toContain('Net Flow (Today)')
    expect(headerRibbon).toContain('Next Expiry')
    expect(headerRibbon).toContain('Market Regime')
    expect(headerRibbon).toContain('sparkline-svg')
  })

  it('MarketContextCard provides synthesized narrative and dynamic condition tags', () => {
    expect(marketContext).toContain('MARKET CONTEXT')
    expect(marketContext).toContain('Price > VWAP')
    expect(marketContext).toContain('Bullish Flow')
    expect(marketContext).toContain('GEX + Above')
    expect(marketContext).toContain('Negative Below')
  })

  it('KeyLevelsCard displays Max Pain, Spot Price, VWAP, Resistance and Support', () => {
    expect(keyLevels).toContain('KEY LEVELS')
    expect(keyLevels).toContain('Max Pain')
    expect(keyLevels).toContain('Spot Price')
    expect(keyLevels).toContain('VWAP')
    expect(keyLevels).toContain('Resistance')
    expect(keyLevels).toContain('Support')
  })

  it('FlowSummaryDonutCard computes bullish vs bearish flow percentages and renders donut', () => {
    expect(flowSummary).toContain('FLOW SUMMARY (TODAY)')
    expect(flowSummary).toContain('donut-svg')
    expect(flowSummary).toContain('Bullish')
    expect(flowSummary).toContain('Bearish')
    expect(flowSummary).toContain('Net Flow')
  })

  it('StrikeGammaExposureChart draws horizontal bi-directional GEX bars with spot line', () => {
    expect(gexChart).toContain('GAMMA EXPOSURE')
    expect(gexChart).toContain('Negative Gamma')
    expect(gexChart).toContain('Positive Gamma')
    expect(gexChart).toContain('Spot Price')
    expect(gexChart).toContain('gex-svg')
  })

  it('StrikeOpenInterestChart draws horizontal paired OI bars by strike', () => {
    expect(oiChart).toContain('OPEN INTEREST BY STRIKE')
    expect(oiChart).toContain('Puts OI')
    expect(oiChart).toContain('Calls OI')
    expect(oiChart).toContain('oi-svg')
  })

  it('NetFlowByExpiryChart renders diverging flow bars and Net Flow overlay line', () => {
    expect(netFlowChart).toContain('NET FLOW BY EXPIRY')
    expect(netFlowChart).toContain('Bullish Flow')
    expect(netFlowChart).toContain('Bearish Flow')
    expect(netFlowChart).toContain('Net Flow')
    expect(netFlowChart).toContain('flow-svg')
  })

  it('RealTimeFlowTape renders institutional options prints table with filters', () => {
    expect(realTimeFlow).toContain('REAL-TIME FLOW')
    expect(realTimeFlow).toContain('Sweeps')
    expect(realTimeFlow).toContain('Blocks')
    expect(realTimeFlow).toContain('PREMIUM')
    expect(realTimeFlow).toContain('SIDE')
  })

  it('ForwardTrajectoryCard highlights where price is trying to go towards with step cascade', () => {
    expect(trajectoryCard).toContain('REGIME TRAJECTORY')
    expect(trajectoryCard).toContain('step-card')
    expect(trajectoryCard).toContain('mean-pull-badge')
    expect(trajectoryCard).toContain('Equilibrium Anchors:')
  })

  it('VolatilitySurface3D renders a hand-rolled 3D surface with axes, IV legend and spot mark', () => {
    expect(volSurface).toContain('VOLATILITY SURFACE')
    expect(volSurface).toContain('surface-svg')
    expect(volSurface).toContain('canvas-container')
    expect(volSurface).toContain('floor-line')
    expect(volSurface).toContain('spotMark')
  })

  it('PositioningSummaryCard aggregates dealer, crowd, smart money, and net delta positioning', () => {
    expect(positioning).toContain('POSITIONING SUMMARY')
    expect(positioning).toContain('Dealer Positioning')
    expect(positioning).toContain('Dealer Bias')
    expect(positioning).toContain('Crowd Positioning')
    expect(positioning).toContain('Smart Money Flow')
    expect(positioning).toContain('Net Delta (All Exp)')
  })

  it('NetGammaSpotTimeSeries displays multi-axis net gamma area and spot price trace', () => {
    expect(timeSeries).toContain('NET GAMMA &amp; SPOT PRICE')
    expect(timeSeries).toContain('posAreaPath')
    expect(timeSeries).toContain('negAreaPath')
    expect(timeSeries).toContain('priceLinePath')
    expect(timeSeries).toContain('now-tag')
  })

  it('LiveAlertsPanel displays event alerts with status indicators', () => {
    expect(alertsPanel).toContain('ALERTS')
    expect(alertsPanel).toContain('GEX Flip')
    expect(alertsPanel).toContain('Large Flow')
    expect(alertsPanel).toContain('Support Break')
  })

  it('InstantaneousHedgingCard computes dealer Greek differentials and impact', () => {
    const hedgingCard = source('components/InstantaneousHedgingCard.vue')
    expect(hedgingCard).toContain('INSTANTANEOUS HEDGING')
    expect(hedgingCard).toContain('Net Hedging Pressure')
    expect(hedgingCard).toContain('Call Hedging')
    expect(hedgingCard).toContain('Put Hedging')
    expect(hedgingCard).toContain('Hedging Impact (Price)')
    expect(hedgingCard).toContain('Hedging Impact (IV)')
  })
})
