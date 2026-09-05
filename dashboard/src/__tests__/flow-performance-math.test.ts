import { describe, expect, it } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import RealTimeFlowTape from '@/components/RealTimeFlowTape.vue'
import NetFlowByExpiryChart from '@/components/NetFlowByExpiryChart.vue'
import DealerGreeksFlowCard from '@/components/DealerGreeksFlowCard.vue'
import FlowSummaryDonutCard from '@/components/FlowSummaryDonutCard.vue'
import { printSide, printPremium } from '@/flowDisplay'
import type { OptionsTapeRow } from '@/api'
import type { MicrostructureRegimeSnapshot } from '@/microstructureContracts'

function makePrint(over: Partial<OptionsTapeRow> = {}): OptionsTapeRow {
  return {
    timestamp: '2026-09-04T14:30:00Z',
    right: 'call',
    premium: 100_000,
    volume: 50,
    contracts: 50,
    price: 2.0,
    strike: 150,
    underlying_price: 148,
    expiry: '2026-09-18',
    dte: 14,
    aggressor: null,
    signed_premium: null,
    premium_estimated: false,
    anomaly_flags: [],
    anomaly_score: 0,
    premium_percentile: 0.8,
    ...over,
  }
}

async function renderComponent(component: any, props: Record<string, any> = {}): Promise<string> {
  const app = createSSRApp({
    render: () => h(component, props),
  })
  return renderToString(app)
}

describe('RealTimeFlowTape math and filtering accuracy', () => {
  it('honors unsigned flow direction as Neutral and does not treat call as Bullish', async () => {
    const unsignedCall = makePrint({ right: 'call', aggressor: null, bias: null })
    const unsignedPut = makePrint({ right: 'put', aggressor: null, bias: null })
    const signedBullish = makePrint({ right: 'call', aggressor: 'buy', bias: 'bullish' })
    const signedBearish = makePrint({ right: 'put', aggressor: 'sell', bias: 'bearish' })

    expect(printSide(unsignedCall)).toBe('Neutral')
    expect(printSide(unsignedPut)).toBe('Neutral')
    expect(printSide(signedBullish)).toBe('Bullish')
    expect(printSide(signedBearish)).toBe('Bearish')

    const html = await renderComponent(RealTimeFlowTape, {
      symbol: 'NVDA',
      prints: [unsignedCall, signedBullish],
    })

    expect(html).toContain('Neutral')
    expect(html).toContain('Bullish')
    expect(html).toContain('is-neutral')
  })

  it('uses printPremium for contract multiplier and price calculation without collapsing missing to 0', () => {
    // Missing premium, but price: 2.5, volume: 10, contract_multiplier: 100 -> $2,500
    const calculated = printPremium({ price: 2.5, volume: 10, contract_multiplier: 100 })
    expect(calculated).toBe(2500)

    // Missing volume -> null (never fake zero)
    const missing = printPremium({ price: 2.5, volume: null, contract_multiplier: 100 })
    expect(missing).toBeNull()
  })

  it('renders up to 6 prints in initial default view', async () => {
    const prints = Array.from({ length: 10 }, (_, i) =>
      makePrint({ timestamp: `2026-09-04T14:30:${String(i).padStart(2, '0')}Z` }),
    )
    const html = await renderComponent(RealTimeFlowTape, {
      symbol: 'NVDA',
      prints,
    })
    // 6 flow rows rendered inside tape table
    const matches = html.match(/<tr data-v-[^>]*><td class="time-col/g)
    expect(matches?.length).toBe(6)
  })
})

describe('NetFlowByExpiryChart dynamic caption and calculation', () => {
  it('computes dynamic net flow concentration caption instead of hardcoded bullish text', async () => {
    // Near-term expiry heavy put flow (bearish)
    const rows = [
      { expiry: '2026-09-11', dte: 7, call_premium: 100_000, put_premium: 900_000 },
      { expiry: '2026-09-18', dte: 14, call_premium: 50_000, put_premium: 150_000 },
    ]

    const html = await renderComponent(NetFlowByExpiryChart, { rows })
    expect(html).not.toContain('Bullish flow concentrated in near-term expiries.')
    expect(html).toContain('Bearish flow concentrated in near-term expiries')
  })

  it('displays empty state when rows are empty without fabricating sample data', async () => {
    const html = await renderComponent(NetFlowByExpiryChart, { rows: [] })
    expect(html).toContain('chart-empty')
    expect(html).toContain('No expiry flow data')
  })
})

describe('DealerGreeksFlowCard null-safety and honesty', () => {
  it('formats null put GEX as DASH without evaluating Math.abs(null) as 0', async () => {
    const snapshot = {
      asof: '2026-09-04T14:30:00Z',
      generated_at: '2026-09-04T14:30:00Z',
      quality: { measurable: true },
      net_gex_m: 1.5,
      call_gex_m: 1.5,
      put_gex_m: null, // absent put GEX
      net_vex_m: 0.8,
      net_chex_m: 0.2,
      zero_dte_charm_drift_m: null,
      hedging_flow_m: 1.2,
    } as unknown as MicrostructureRegimeSnapshot

    const html = await renderComponent(DealerGreeksFlowCard, { snapshot })
    expect(html).toContain('Calls: +$1.5M | Puts: —')
    expect(html).not.toContain('Puts: -$0.0M')
    expect(html).not.toContain('Puts: $0.0M')
    expect(html).toContain('0DTE Charm Drift: —')
  })

  it('formats negative 0DTE charm drift with signed minus instead of forcing +$', async () => {
    const snapshot = {
      asof: '2026-09-04T14:30:00Z',
      generated_at: '2026-09-04T14:30:00Z',
      quality: { measurable: true },
      net_gex_m: 1.5,
      call_gex_m: 2.0,
      put_gex_m: -0.5,
      net_vex_m: 0.8,
      net_chex_m: 0.2,
      zero_dte_charm_drift_m: -0.45,
      hedging_flow_m: 1.2,
    } as unknown as MicrostructureRegimeSnapshot

    const html = await renderComponent(DealerGreeksFlowCard, { snapshot })
    expect(html).toContain('0DTE Charm Drift: -0.45M/day')
    expect(html).not.toContain('+$0DTE Charm Drift')
    expect(html).not.toContain('+$−0.45')
    expect(html).not.toContain('+$-0.45')
  })
})

describe('FlowSummaryDonutCard unmeasured state honesty', () => {
  it('renders DASH in center label and neutral rule stroke when flow is unmeasured', async () => {
    const html = await renderComponent(FlowSummaryDonutCard, {
      totalPremiumM: null,
      bullishPremiumM: null,
      bearishPremiumM: null,
      netFlowM: null,
    })

    expect(html).toContain('class="donut-label font-mono font-bold" data-v-')
    expect(html).toContain('>—</text>')

    // Background circle stroke is neutral rule, not put color
    expect(html).toContain('stroke="var(--rule)"')
  })
})
