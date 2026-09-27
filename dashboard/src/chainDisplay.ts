import type { RelationshipType, SupplyChainEdge, SupplyChainNode, SupplyTier } from './api'

export function tierBadgeLabel(tier: SupplyTier | string | undefined): string {
  switch (tier) {
    case 'mega_driver':
      return 'Core Driver'
    case 'tier1_supplier':
      return 'Tier 1 Supplier'
    case 'tier2_supplier':
      return 'Tier 2 Supplier'
    case 'horizontal_enabler':
      return 'Enabler / Infra'
    case 'downstream_customer':
      return 'Downstream Cloud'
    default:
      return 'Beneficiary'
  }
}

export function tierColorClass(tier: SupplyTier | string | undefined): string {
  switch (tier) {
    case 'mega_driver':
      return 'badge-driver'
    case 'tier1_supplier':
      return 'badge-tier1'
    case 'tier2_supplier':
      return 'badge-tier2'
    case 'horizontal_enabler':
      return 'badge-enabler'
    case 'downstream_customer':
      return 'badge-customer'
    default:
      return 'badge-neutral'
  }
}

export function elasticityTone(score: number | null | undefined): 'up' | 'warm' | 'cool' | 'down' {
  if (score == null) return 'cool'
  if (score >= 90) return 'up'
  if (score >= 80) return 'warm'
  if (score >= 60) return 'cool'
  return 'down'
}

export function formatCapExSensitivity(sens: number | null | undefined): string {
  if (sens == null || !Number.isFinite(sens)) return '—'
  return `+${sens.toFixed(1)}x`
}

export function formatRevConcentration(pct: number | null | undefined): string {
  if (pct == null || !Number.isFinite(pct)) return '—'
  return `${pct.toFixed(1)}%`
}

export function formatMarketCap(billions: number | null | undefined): string {
  if (billions == null || !Number.isFinite(billions)) return '—'
  if (billions >= 1000) return `$${(billions / 1000).toFixed(2)}T`
  return `$${billions.toFixed(1)}B`
}

export function relationshipLabel(rel: RelationshipType | string | undefined): string {
  switch (rel) {
    case 'supplies_to':
      return 'Supplies to'
    case 'purchases_from':
      return 'Purchases from'
    case 'co_dependent':
      return 'Co-engineered with'
    case 'technology_partner':
      return 'Tech Partner of'
    case 'infrastructure_enabler':
      return 'Powers / Cools'
    case 'peer':
      return 'Sector Peer'
    default:
      return 'Linked with'
  }
}

/**
 * Skew chip label, or null when no skew data exists. A missing skew must not
 * render as "Neutral" — that is indistinguishable from a measured neutral skew.
 */
export function optionsSkewLabel(
  skew: string | null | undefined,
): { label: string; tone: string } | null {
  if (!skew) return null
  switch (skew) {
    case 'heavy_call_sweep':
      return { label: 'Call Sweep', tone: 'up' }
    case 'bullish_call_drift':
      return { label: 'Bull Drift', tone: 'up' }
    case 'balanced_bullish':
      return { label: 'Lean Bull', tone: 'warm' }
    case 'hedged':
      return { label: 'Hedged', tone: 'cool' }
    case 'bearish_put_skew':
      return { label: 'Put Skew', tone: 'down' }
    default:
      return { label: skew, tone: 'cool' }
  }
}

export function flowTypeClass(
  rel: RelationshipType | string | undefined,
  srcCol: number,
  tgtCol: number,
): 'flow-supply' | 'flow-demand' | 'flow-partner' | 'flow-peer' {
  if (rel === 'peer') return 'flow-peer'
  if (rel === 'technology_partner' || rel === 'co_dependent') return 'flow-partner'
  if (rel === 'purchases_from' || srcCol > tgtCol) return 'flow-demand'
  return 'flow-supply'
}

export function flowMarkerId(
  flowType: 'flow-supply' | 'flow-demand' | 'flow-partner' | 'flow-peer',
  active: boolean,
): string {
  if (!active) return 'url(#arrow-default)'
  switch (flowType) {
    case 'flow-supply':
      return 'url(#arrow-supply)'
    case 'flow-demand':
      return 'url(#arrow-demand)'
    case 'flow-partner':
      return 'url(#arrow-partner)'
    case 'flow-peer':
      return 'url(#arrow-peer)'
  }
}

export function edgeRelationshipSummary(
  rel: RelationshipType | string | undefined,
  category?: string,
  strength?: number,
): string {
  const relStr = relationshipLabel(rel)
  const catStr = category ? ` · ${category}` : ''
  const sensStr = strength ? ` (${(strength * 100).toFixed(0)}% link)` : ''
  return `${relStr}${catStr}${sensStr}`
}

export function rankBeneficiaries(
  nodes: SupplyChainNode[],
  subIndustryFilter?: string | null,
  minElasticity?: number,
): SupplyChainNode[] {
  let list = nodes.filter((n) => !n.is_focus)
  if (subIndustryFilter && subIndustryFilter !== 'all') {
    const filterKey = subIndustryFilter.toLowerCase()
    list = list.filter((n) => {
      const text = `${n.sub_industry} ${n.sector} ${n.name}`.toLowerCase()
      if (filterKey === 'space') {
        return (
          text.includes('space') ||
          text.includes('satellite') ||
          text.includes('cell') ||
          text.includes('lunar') ||
          text.includes('launch') ||
          text.includes('orbit') ||
          text.includes('aerospace') ||
          text.includes('broadband') ||
          text.includes('payload')
        )
      }
      if (filterKey === 'glp1') {
        return (
          text.includes('glp') ||
          text.includes('incretin') ||
          text.includes('injector') ||
          text.includes('fill-finish') ||
          text.includes('sterile') ||
          text.includes('cdmo') ||
          text.includes('syringe') ||
          text.includes('metabolic')
        )
      }
      if (filterKey === 'robotics') {
        return (
          text.includes('robot') ||
          text.includes('humanoid') ||
          text.includes('vision') ||
          text.includes('sensor') ||
          text.includes('warehouse') ||
          text.includes('automation') ||
          text.includes('optimus')
        )
      }
      if (filterKey === 'quantum') {
        return (
          text.includes('quantum') ||
          text.includes('qubit') ||
          text.includes('photonic') ||
          text.includes('trapped-ion') ||
          text.includes('superconducting')
        )
      }
      if (filterKey === 'optic') {
        return (
          text.includes('optic') ||
          text.includes('photon') ||
          text.includes('laser') ||
          text.includes('transceiver') ||
          text.includes('retimer')
        )
      }
      if (filterKey === 'memory') {
        return (
          text.includes('memory') ||
          text.includes('storage') ||
          text.includes('nand') ||
          text.includes('dram') ||
          text.includes('hbm') ||
          text.includes('flash') ||
          text.includes('hdd')
        )
      }
      if (filterKey === 'cooling') {
        return (
          text.includes('cooling') ||
          text.includes('thermal') ||
          text.includes('chiller') ||
          text.includes('heat')
        )
      }
      if (filterKey === 'power') {
        return (
          text.includes('power') ||
          text.includes('nuclear') ||
          text.includes('grid') ||
          text.includes('utility') ||
          text.includes('transmission') ||
          text.includes('smr') ||
          text.includes('switchgear')
        )
      }
      if (filterKey === 'foundry') {
        return (
          text.includes('foundry') ||
          text.includes('packaging') ||
          text.includes('metrology') ||
          text.includes('litho') ||
          text.includes('etch') ||
          text.includes('deposition') ||
          text.includes('equipment') ||
          text.includes('inspection') ||
          text.includes('probe')
        )
      }
      if (filterKey === 'software') {
        return (
          text.includes('software') ||
          text.includes('data') ||
          text.includes('vector') ||
          text.includes('security') ||
          text.includes('ontology') ||
          text.includes('cloud')
        )
      }
      return text.includes(filterKey)
    })
  }
  if (minElasticity != null && minElasticity > 0) {
    list = list.filter((n) => (n.metrics?.elasticity_score ?? 0) >= minElasticity)
  }
  return list.sort(
    (a, b) => (b.metrics?.elasticity_score ?? 0) - (a.metrics?.elasticity_score ?? 0),
  )
}

export function formatContractValue(millions: number | null | undefined): string {
  if (millions == null || !Number.isFinite(millions)) return '—'
  if (millions >= 1000) return `$${(millions / 1000).toFixed(1)}B / yr`
  return `$${millions.toFixed(0)}M / yr`
}

export function strengthTone(strength: number | null | undefined): 'high' | 'mid' | 'low' {
  if (strength == null) return 'mid'
  if (strength >= 0.8) return 'high'
  if (strength >= 0.5) return 'mid'
  return 'low'
}

export function generateRelationshipNarrative(
  edge: SupplyChainEdge,
  node?: SupplyChainNode | null,
): string {
  const relText = relationshipLabel(edge.relationship).toLowerCase()
  const catText = edge.supply_category ? ` supplying ${edge.supply_category}` : ''
  const strengthPct = Math.round(edge.strength * 100)
  let narrative = `${edge.source} is a critical partner that ${relText} ${edge.target}${catText}, maintaining an estimated ${strengthPct}% dependency link.`
  if (
    edge.annual_contract_value_est_m != null &&
    Number.isFinite(edge.annual_contract_value_est_m)
  ) {
    narrative += ` Estimated annual procurement / contract value is ~${formatContractValue(edge.annual_contract_value_est_m)}.`
  }
  if (
    node &&
    node.metrics?.revenue_concentration_pct != null &&
    Number.isFinite(node.metrics.revenue_concentration_pct)
  ) {
    narrative += ` Revenue concentration to key driver is ~${node.metrics.revenue_concentration_pct.toFixed(1)}%.`
  }
  return narrative
}
