import { describe, it, expect } from 'vitest'
import {
  tierBadgeLabel,
  tierColorClass,
  elasticityTone,
  formatCapExSensitivity,
  formatRevConcentration,
  formatMarketCap,
  relationshipLabel,
  optionsSkewLabel,
  rankBeneficiaries,
  formatContractValue,
  strengthTone,
  generateRelationshipNarrative,
} from '@/chainDisplay'
import type { SupplyChainEdge, SupplyChainNode } from '@/api'

describe('chainDisplay helpers', () => {
  it('formats tier labels and badge classes properly', () => {
    expect(tierBadgeLabel('mega_driver')).toBe('Core Driver')
    expect(tierBadgeLabel('tier1_supplier')).toBe('Tier 1 Supplier')
    expect(tierBadgeLabel('tier2_supplier')).toBe('Tier 2 Supplier')
    expect(tierBadgeLabel('horizontal_enabler')).toBe('Enabler / Infra')
    expect(tierBadgeLabel('downstream_customer')).toBe('Downstream Cloud')
    expect(tierBadgeLabel('unknown' as any)).toBe('Beneficiary')

    expect(tierColorClass('mega_driver')).toBe('badge-driver')
    expect(tierColorClass('tier1_supplier')).toBe('badge-tier1')
    expect(tierColorClass('tier2_supplier')).toBe('badge-tier2')
  })

  it('computes elasticity tone', () => {
    expect(elasticityTone(95)).toBe('up')
    expect(elasticityTone(85)).toBe('warm')
    expect(elasticityTone(70)).toBe('cool')
    expect(elasticityTone(40)).toBe('down')
    expect(elasticityTone(null)).toBe('cool')
  })

  it('formats numerical metrics and market caps', () => {
    expect(formatCapExSensitivity(3.4)).toBe('+3.4x')
    expect(formatCapExSensitivity(null)).toBe('—')

    expect(formatRevConcentration(45.2)).toBe('45.2%')
    expect(formatRevConcentration(null)).toBe('—')

    expect(formatMarketCap(3120.0)).toBe('$3.12T')
    expect(formatMarketCap(45.5)).toBe('$45.5B')
    expect(formatMarketCap(null)).toBe('—')
  })

  it('maps relationship and options skew labels', () => {
    expect(relationshipLabel('supplies_to')).toBe('Supplies to')
    expect(relationshipLabel('infrastructure_enabler')).toBe('Powers / Cools')

    expect(optionsSkewLabel('heavy_call_sweep')).toEqual({ label: 'Call Sweep', tone: 'up' })
    expect(optionsSkewLabel('bullish_call_drift')).toEqual({ label: 'Bull Drift', tone: 'up' })
    expect(optionsSkewLabel('hedged')).toEqual({ label: 'Hedged', tone: 'cool' })

    // A missing skew is null — never a fake "Neutral" chip.
    expect(optionsSkewLabel(null)).toBeNull()
    expect(optionsSkewLabel(undefined)).toBeNull()
    expect(optionsSkewLabel('')).toBeNull()
  })

  it('computes flow types and marker URLs correctly', async () => {
    const { flowTypeClass, flowMarkerId, edgeRelationshipSummary } = await import('@/chainDisplay')
    expect(flowTypeClass('supplies_to', 0, 1)).toBe('flow-supply')
    expect(flowTypeClass('purchases_from', 2, 1)).toBe('flow-demand')
    expect(flowTypeClass('technology_partner', 1, 1)).toBe('flow-partner')
    expect(flowTypeClass('peer', 1, 1)).toBe('flow-peer')

    expect(flowMarkerId('flow-supply', false)).toBe('url(#arrow-default)')
    expect(flowMarkerId('flow-supply', true)).toBe('url(#arrow-supply)')
    expect(flowMarkerId('flow-demand', true)).toBe('url(#arrow-demand)')
    expect(flowMarkerId('flow-partner', true)).toBe('url(#arrow-partner)')
    expect(flowMarkerId('flow-peer', true)).toBe('url(#arrow-peer)')

    const summary = edgeRelationshipSummary('supplies_to', '800G Optics', 0.85)
    expect(summary).toContain('Supplies to')
    expect(summary).toContain('800G Optics')
    expect(summary).toContain('85% link')
  })

  it('ranks and filters beneficiaries by elasticity and sub-industry', () => {
    const mockNodes: SupplyChainNode[] = [
      {
        symbol: 'NVDA',
        name: 'NVIDIA',
        sector: 'Semis',
        sub_industry: 'Compute',
        tier: 'mega_driver',
        market_cap_billions: 3000,
        is_focus: true,
        metrics: { elasticity_score: 99 } as any,
        evidence: [],
      },
      {
        symbol: 'AAOI',
        name: 'Applied Opto',
        sector: 'Tech',
        sub_industry: 'Optical Transceivers',
        tier: 'tier1_supplier',
        market_cap_billions: 1.8,
        is_focus: false,
        metrics: { elasticity_score: 96 } as any,
        evidence: [],
      },
      {
        symbol: 'LITE',
        name: 'Lumentum',
        sector: 'Tech',
        sub_industry: 'Photonics & Optics',
        tier: 'tier1_supplier',
        market_cap_billions: 6.4,
        is_focus: false,
        metrics: { elasticity_score: 92 } as any,
        evidence: [],
      },
      {
        symbol: 'MU',
        name: 'Micron',
        sector: 'Semis',
        sub_industry: 'HBM Memory',
        tier: 'tier1_supplier',
        market_cap_billions: 140,
        is_focus: false,
        metrics: { elasticity_score: 88 } as any,
        evidence: [],
      },
    ]

    const ranked = rankBeneficiaries(mockNodes)
    expect(ranked.map((n) => n.symbol)).toEqual(['AAOI', 'LITE', 'MU'])

    const opticsOnly = rankBeneficiaries(mockNodes, 'optic')
    expect(opticsOnly.map((n) => n.symbol)).toEqual(['AAOI', 'LITE'])

    const highElasticity = rankBeneficiaries(mockNodes, undefined, 90)
    expect(highElasticity.map((n) => n.symbol)).toEqual(['AAOI', 'LITE'])
  })

  it('formats contract value and computes strength tone', () => {
    expect(formatContractValue(null)).toBe('—')
    expect(formatContractValue(undefined)).toBe('—')
    expect(formatContractValue(Number.NaN)).toBe('—')
    expect(formatContractValue(180)).toBe('$180M / yr')
    expect(formatContractValue(1250)).toBe('$1.3B / yr')

    expect(strengthTone(null)).toBe('mid')
    expect(strengthTone(0.95)).toBe('high')
    expect(strengthTone(0.8)).toBe('high')
    expect(strengthTone(0.65)).toBe('mid')
    expect(strengthTone(0.5)).toBe('mid')
    expect(strengthTone(0.35)).toBe('low')
  })

  it('generates institutional relationship narrative', () => {
    const edge: SupplyChainEdge = {
      id: 'e1',
      source: 'AAOI',
      target: 'NVDA',
      relationship: 'supplies_to',
      strength: 0.9,
      supply_category: '800G Transceivers',
      annual_contract_value_est_m: 240,
      evidence_count: 3,
    }
    const node: SupplyChainNode = {
      symbol: 'AAOI',
      name: 'Applied Optoelectronics',
      sector: 'Technology',
      sub_industry: 'Optical Transceivers',
      tier: 'tier1_supplier',
      market_cap_billions: 1.8,
      metrics: {
        elasticity_score: null,
        capex_sensitivity: null,
        revenue_concentration_pct: 35.5,
        operating_leverage: null,
        forward_pe: null,
        peg_ratio: null,
        gross_margin_trend: null,
        yoy_revenue_growth: null,
        next_earnings_date: null,
        flow_sentiment_score: null,
        options_skew: null,
      },
      evidence: [],
    }

    const narrative = generateRelationshipNarrative(edge, node)
    expect(narrative).toContain('AAOI')
    expect(narrative).toContain('NVDA')
    expect(narrative).toContain('supplies to')
    expect(narrative).toContain('800G Transceivers')
    expect(narrative).toContain('90% dependency link')
    expect(narrative).toContain('$240M')
    expect(narrative).toContain('35.5%')
  })
})
