/**
 * Setups tab display helpers. Drive suggested right, GEX-relative sell, and
 * freshness from the shipped payload — missing values stay "—".
 */
import { DASH, num, signedPct } from '@/format'

export const UNMEASURED = DASH

const RIGHTS = new Set(['call', 'put', 'watch', 'blocked'])

export function suggestedRightLabel(right: string | null | undefined): string {
  const value = String(right ?? '')
    .trim()
    .toLowerCase()
  if (!RIGHTS.has(value)) return UNMEASURED
  return value.toUpperCase()
}

export function suggestedRightTokenClass(right: string | null | undefined): string {
  const value = String(right ?? '')
    .trim()
    .toLowerCase()
  if (value === 'call') return 'token-call'
  if (value === 'put') return 'token-put'
  if (value === 'watch') return 'token-warn'
  return 'token-unsigned'
}

export function sellSourceLabel(source: string | null | undefined): string {
  const value = String(source ?? '')
    .trim()
    .toLowerCase()
  if (value === 'call_wall') return 'call wall'
  if (value === 'put_wall') return 'put wall'
  const family = levelSourceLabel(source)
  return family === UNMEASURED ? UNMEASURED : family
}

export function levelSourceLabel(source: string | null | undefined): string {
  const value = String(source ?? '')
    .trim()
    .toLowerCase()
  if (value === 'resistance/support' || value === 'support' || value === 'resistance') {
    return 'resistance/support'
  }
  if (
    value === 'options gex' ||
    value === 'call_wall' ||
    value === 'put_wall' ||
    value === 'gex' ||
    value === 'gamma_flip'
  ) {
    return 'options GEX'
  }
  if (value === 'positions' || value === 'pin_strike' || value === 'open_interest') {
    return 'positions'
  }
  if (value === 'technical analysis' || value === 'ta') {
    return 'technical analysis'
  }
  return UNMEASURED
}

export interface SetupLevelMark {
  price?: number | null
  source?: string | null
}

export function formatSetupLevel(price: number | null | undefined, source?: string | null): string {
  if (price == null || !Number.isFinite(Number(price))) return UNMEASURED
  const tagged = levelSourceLabel(source)
  const figure = `$${num(price, 2)}`
  return tagged === UNMEASURED ? figure : `${figure}  ${tagged}`
}

export function formatSupportLevels(supports: SetupLevelMark[] | null | undefined): string {
  if (!Array.isArray(supports) || supports.length === 0) return UNMEASURED
  const parts = supports
    .map((item) => formatSetupLevel(item?.price, item?.source))
    .filter((part) => part !== UNMEASURED)
  return parts.length ? parts.join(' · ') : UNMEASURED
}

export function formatTakeProfitZones(zones: SetupLevelMark[] | null | undefined): string {
  return formatSupportLevels(zones)
}

export function setupHeadlineInvalidation(input: {
  invalidation?: number | null
  invalidationSource?: string | null
  planInvalidation?: number | null
  planInvalidationSource?: string | null
  supports?: unknown
}): { price: number | null; source: string | null } {
  if (input.invalidation != null && Number.isFinite(Number(input.invalidation))) {
    return { price: Number(input.invalidation), source: input.invalidationSource ?? null }
  }
  if (input.planInvalidation != null && Number.isFinite(Number(input.planInvalidation))) {
    return { price: Number(input.planInvalidation), source: input.planInvalidationSource ?? null }
  }
  return { price: null, source: null }
}

export function missingSourcesCopy(sources: string[] | null | undefined): string {
  if (!Array.isArray(sources) || sources.length === 0) return UNMEASURED
  return sources.join(', ')
}

export function spotRelativeSellCopy(input: {
  sell: number | null | undefined
  spot?: number | null
  sellRelPct?: number | null
  sellSource?: string | null
}): string {
  if (input.sell == null || !Number.isFinite(Number(input.sell))) return UNMEASURED
  const price = `$${num(input.sell, 2)}`
  const rel =
    input.sellRelPct == null || !Number.isFinite(Number(input.sellRelPct))
      ? UNMEASURED
      : signedPct(Number(input.sellRelPct) * 100, 1)
  const wall = sellSourceLabel(input.sellSource)
  if (rel === UNMEASURED && wall === UNMEASURED) return price
  if (wall === UNMEASURED) return `${price}  ${rel}`
  if (rel === UNMEASURED) return `${price}  ${wall}`
  return `${price}  ${rel}  ${wall}`
}

export function freshnessLabel(status: string | null | undefined, pass?: boolean | null): string {
  if (pass === true || String(status ?? '').toUpperCase() === 'FRESH') return 'FRESH'
  if (pass === false || String(status ?? '').toUpperCase() === 'STALE_OR_PROXY') return 'STALE'
  if (!status && pass == null) return UNMEASURED
  return UNMEASURED
}

export function qlibAlignmentLabel(alignment: string | null | undefined): string {
  const value = String(alignment ?? '')
    .trim()
    .toLowerCase()
  if (value === 'confirms' || value === 'conflicts' || value === 'neutral') {
    return value.toUpperCase()
  }
  return UNMEASURED
}

export function unmeasured(value: unknown): string {
  if (value == null || value === '') return UNMEASURED
  if (typeof value === 'number' && !Number.isFinite(value)) return UNMEASURED
  return String(value)
}

/** Setups must not pass a row cap — coverage is the unsliced union. */
export function setupsFeedRequest(force: boolean): { force?: boolean } {
  return force ? { force: true } : {}
}

function finiteQuery(value: unknown): string | null {
  const n = Number(value)
  return Number.isFinite(n) ? String(n) : null
}

/** Prefill the standalone calculator from a setup contract. */
export function setupCalculatorQuery(input: {
  symbol?: string | null
  right?: string | null
  spot?: number | null
  strike?: number | null
  dte?: number | null
  vol?: number | null
  premium?: number | null
}): Record<string, string> {
  const right = String(input.right || '').toLowerCase()
  const query: Record<string, string> = {
    strategy: right === 'put' ? 'long_put' : 'long_call',
  }
  const symbol = String(input.symbol || '')
    .trim()
    .toUpperCase()
  if (symbol) query.symbol = symbol
  const spot = finiteQuery(input.spot)
  const strike = finiteQuery(input.strike)
  const dte = finiteQuery(input.dte)
  const vol = finiteQuery(input.vol)
  const premium = finiteQuery(input.premium)
  if (spot) query.spot = spot
  if (strike) query.strike = strike
  if (dte) query.dte = dte
  if (vol) query.vol = vol
  if (premium) query.premium = premium
  return query
}

export interface SetupRowLike {
  symbol?: string
  suggestion?: {
    right?: string | null
    review_score?: number | null
    review_rank?: number | null
    review_label?: string | null
    direction_observations?: number | null
    direction_required?: number | null
    direction_stable?: boolean | null
    direction_churned?: boolean | null
    contract_plan?: {
      stability_observations?: number | null
      stability_required?: number | null
      stable?: boolean | null
    } | null
    qlib?: { measured?: boolean } | null
  } | null
}

export interface SetupCoverage {
  union_symbols: number
  suggested_call: number
  suggested_put: number
  suggested_watch: number
  suggested_blocked: number
  qlib_measured: number
}

const RIGHT_ORDER: Record<string, number> = {
  call: 0,
  put: 1,
  watch: 2,
  blocked: 3,
}

export function suggestionRightOf(row: SetupRowLike | null | undefined): string {
  return String(row?.suggestion?.right ?? '')
    .trim()
    .toLowerCase()
}

export function suggestionStabilityCopy(
  suggestion: SetupRowLike['suggestion'] | null | undefined,
): string {
  const right = String(suggestion?.right ?? '').toLowerCase()
  if (!['call', 'put'].includes(right)) return UNMEASURED
  const directionObserved = Number(suggestion?.direction_observations ?? 0)
  const directionRequired = Number(suggestion?.direction_required ?? 0)
  const direction =
    directionRequired > 0 ? `DIR ${directionObserved}/${directionRequired}` : 'DIR —'
  const contract = suggestion?.contract_plan
  const contractRequired = Number(contract?.stability_required ?? 0)
  const contractCopy =
    contract && contractRequired > 0
      ? ` · CTR ${Number(contract.stability_observations ?? 0)}/${contractRequired}`
      : ''
  const prefix = suggestion?.direction_churned
    ? 'FLIPPED'
    : suggestion?.review_label || (suggestion?.direction_stable ? 'REPEATED' : 'NEW')
  return `${prefix} · ${direction}${contractCopy}`
}

/**
 * Display the full suggestion union. Call/put rise above watch/blocked so a
 * later put is not buried under forty blocked names. Coverage is counted from
 * these same rows — never from an unsliced payload while the table is sliced.
 */
export function presentSetupRows(payload: { rows?: SetupRowLike[] | null } | null | undefined): {
  rows: SetupRowLike[]
  coverage: SetupCoverage
} {
  const incoming = Array.isArray(payload?.rows) ? payload.rows : []
  const ranked = incoming.map((row, index) => ({ row, index }))
  ranked.sort((a, b) => {
    const leftRank = Number(a.row.suggestion?.review_rank)
    const rightRank = Number(b.row.suggestion?.review_rank)
    if (Number.isFinite(leftRank) && Number.isFinite(rightRank) && leftRank !== rightRank) {
      return leftRank - rightRank
    }
    const leftScore = Number(a.row.suggestion?.review_score ?? -1)
    const rightScore = Number(b.row.suggestion?.review_score ?? -1)
    if (leftScore !== rightScore) return rightScore - leftScore
    const left = RIGHT_ORDER[suggestionRightOf(a.row)] ?? 4
    const right = RIGHT_ORDER[suggestionRightOf(b.row)] ?? 4
    return left - right || a.index - b.index
  })
  const rows = ranked.map((item) => item.row)
  const coverage: SetupCoverage = {
    union_symbols: rows.length,
    suggested_call: 0,
    suggested_put: 0,
    suggested_watch: 0,
    suggested_blocked: 0,
    qlib_measured: 0,
  }
  for (const row of rows) {
    const right = suggestionRightOf(row)
    if (right === 'call') coverage.suggested_call += 1
    else if (right === 'put') coverage.suggested_put += 1
    else if (right === 'watch') coverage.suggested_watch += 1
    else if (right === 'blocked') coverage.suggested_blocked += 1
    if (row.suggestion?.qlib?.measured) coverage.qlib_measured += 1
  }
  return { rows, coverage }
}
