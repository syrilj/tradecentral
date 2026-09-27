import type { OptionsIntelligence, QuoteMark, VpaAnalysisResult } from './api'

export type DecisionPriceLevelKind = 'support' | 'resistance' | 'pivot' | 'value'

export interface DecisionPriceLevel {
  id: string
  label: string
  price: number
  kind: DecisionPriceLevelKind
  source: string
  strength: number | null
}

export interface DecisionPriceContext {
  symbol: string
  spot: number | null
  spotSource: string | null
  spotQuality: string | null
  asof: string | null
  status: 'ready' | 'partial' | 'missing'
  summary: string
  nearestAbove: DecisionPriceLevel | null
  nearestBelow: DecisionPriceLevel | null
  nearbyLevels: DecisionPriceLevel[]
  valueArea: {
    low: number
    high: number
    poc: number | null
    location: 'above' | 'inside' | 'below'
  } | null
  atr: number | null
}

interface DecisionPriceContextInput {
  symbol: string
  quote?: QuoteMark | null
  options?: OptionsIntelligence | null
  vpa?: VpaAnalysisResult | null
}

function positive(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
}

function levelKind(value: string): DecisionPriceLevelKind {
  if (value.toLowerCase() === 'support') return 'support'
  if (value.toLowerCase() === 'resistance') return 'resistance'
  return 'pivot'
}

function addLevel(
  levels: DecisionPriceLevel[],
  level: Omit<DecisionPriceLevel, 'id' | 'price'> & { price: number | null },
): void {
  if (level.price == null) return
  levels.push({ ...level, id: `${level.label}-${level.price.toFixed(4)}`, price: level.price })
}

function mergeCoincidentLevels(levels: DecisionPriceLevel[]): DecisionPriceLevel[] {
  const merged = new Map<string, DecisionPriceLevel>()
  for (const level of levels) {
    const key = level.price.toFixed(4)
    const current = merged.get(key)
    if (!current) {
      merged.set(key, level)
      continue
    }
    const labels = new Set([...current.label.split(' + '), ...level.label.split(' + ')])
    const sources = new Set([...current.source.split(' + '), ...level.source.split(' + ')])
    merged.set(key, {
      ...current,
      id: `${current.id}-${level.id}`,
      label: [...labels].join(' + '),
      source: [...sources].join(' + '),
      strength: Math.max(current.strength ?? 0, level.strength ?? 0) || null,
      kind: current.kind === level.kind ? current.kind : 'pivot',
    })
  }
  return [...merged.values()]
}

function distancePct(price: number, spot: number): number {
  return ((price - spot) / spot) * 100
}

export function buildDecisionPriceContext({
  symbol,
  quote,
  options,
  vpa,
}: DecisionPriceContextInput): DecisionPriceContext {
  const summary = options?.summary
  const scoredBars = vpa?.bars ?? []
  const lastScoredBar = scoredBars.length ? scoredBars[scoredBars.length - 1] : null
  const liveBar = vpa?.bars_meta?.live_bar ?? null

  const quoteSpot = positive(quote?.last)
  const optionsSpot = positive(summary?.spot)
  const vpaSpot = positive(liveBar?.c) ?? positive(lastScoredBar?.c)
  const spot = quoteSpot ?? optionsSpot ?? vpaSpot
  const spotSource = quoteSpot
    ? `${quote?.source ?? 'market'} quote`
    : optionsSpot
      ? 'options snapshot'
      : vpaSpot
        ? `${vpa?.bars_meta?.timeframe_served ?? vpa?.timeframe ?? 'VPA'} close`
        : null
  const asof = quoteSpot
    ? (quote?.asof ?? null)
    : optionsSpot
      ? (options?.asof_utc ?? null)
      : (vpa?.bars_meta?.live_bar?.d ?? vpa?.bars_meta?.last_bar ?? null)

  const levels: DecisionPriceLevel[] = []
  for (const [index, level] of (vpa?.levels ?? []).entries()) {
    const price = positive(level.price)
    addLevel(levels, {
      label: `VPA ${level.kind.toUpperCase()}`,
      price,
      kind: levelKind(level.kind),
      source: level.source || 'VPA structure',
      strength: typeof level.strength === 'number' ? level.strength : null,
    })
    if (price != null && levels.length) levels[levels.length - 1].id += `-${index}`
  }

  const valueLow = positive(vpa?.vap?.value_area_low)
  const valueHigh = positive(vpa?.vap?.value_area_high)
  const poc = positive(vpa?.vap?.poc)
  addLevel(levels, {
    label: 'VALUE AREA LOW',
    price: valueLow,
    kind: 'support',
    source: 'VPA volume profile',
    strength: null,
  })
  addLevel(levels, {
    label: 'POINT OF CONTROL',
    price: poc,
    kind: 'value',
    source: 'VPA volume profile',
    strength: null,
  })
  addLevel(levels, {
    label: 'VALUE AREA HIGH',
    price: valueHigh,
    kind: 'resistance',
    source: 'VPA volume profile',
    strength: null,
  })
  addLevel(levels, {
    label: 'PUT WALL',
    price: positive(summary?.put_wall),
    kind: 'support',
    source: 'options positioning',
    strength: null,
  })
  addLevel(levels, {
    label: 'GAMMA FLIP',
    price: positive(summary?.gamma_flip),
    kind: 'pivot',
    source: 'options positioning',
    strength: null,
  })
  addLevel(levels, {
    label: 'CALL WALL',
    price: positive(summary?.call_wall),
    kind: 'resistance',
    source: 'options positioning',
    strength: null,
  })

  const measuredLevels = mergeCoincidentLevels(levels)
  const below =
    spot == null
      ? []
      : measuredLevels.filter((level) => level.price < spot).sort((a, b) => b.price - a.price)
  const above =
    spot == null
      ? []
      : measuredLevels.filter((level) => level.price > spot).sort((a, b) => a.price - b.price)
  const atSpot =
    spot == null
      ? []
      : measuredLevels.filter((level) => Math.abs(distancePct(level.price, spot)) <= 0.02)
  const nearbyLevels = [...above.slice(0, 2), ...atSpot, ...below.slice(0, 2)].sort(
    (a, b) => b.price - a.price,
  )

  const valueArea =
    spot != null && valueLow != null && valueHigh != null && valueHigh >= valueLow
      ? {
          low: valueLow,
          high: valueHigh,
          poc,
          location: (spot > valueHigh ? 'above' : spot < valueLow ? 'below' : 'inside') as
            'above' | 'inside' | 'below',
        }
      : null

  let contextSummary = 'Current price and measured structural levels are unavailable.'
  if (spot != null && !measuredLevels.length) {
    contextSummary = 'Current price is available, but no measured structural levels are ready.'
  } else if (spot != null && valueArea?.location === 'inside') {
    contextSummary = 'Price is inside the measured value area, where two-sided trade is balanced.'
  } else if (spot != null && valueArea?.location === 'above') {
    contextSummary = 'Price is above the measured value area and trading in upper price discovery.'
  } else if (spot != null && valueArea?.location === 'below') {
    contextSummary = 'Price is below the measured value area and trading in lower price discovery.'
  } else if (spot != null && below[0] && above[0]) {
    contextSummary = `Price is bracketed by ${below[0].label.toLowerCase()} below and ${above[0].label.toLowerCase()} above.`
  } else if (spot != null && above[0]) {
    contextSummary = `The nearest measured structure is ${above[0].label.toLowerCase()} above price.`
  } else if (spot != null && below[0]) {
    contextSummary = `The nearest measured structure is ${below[0].label.toLowerCase()} below price.`
  }

  return {
    symbol,
    spot,
    spotSource,
    spotQuality: quoteSpot ? (quote?.quality ?? null) : optionsSpot || vpaSpot ? 'derived' : null,
    asof,
    status: spot == null ? 'missing' : measuredLevels.length ? 'ready' : 'partial',
    summary: contextSummary,
    nearestAbove: above[0] ?? null,
    nearestBelow: below[0] ?? null,
    nearbyLevels,
    valueArea,
    atr: positive(vpa?.atr),
  }
}
