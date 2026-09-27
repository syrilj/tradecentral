/**
 * Notable options-flow alerts (Cheddar-style Power Alerts, without dark pool).
 *
 * Attention rank only: size, sweep/block class, vol/OI, heat, and unusual flags.
 * Call/put is contract identity. Signed long/short requires a provider aggressor.
 * Missing prices stay missing — never a fake zero or invented option P/L.
 */
import type { MarketFlowPrint, UnusualFlowRow } from '@/api'
import { classifyFlowOrder, computeVolOiRatio } from '@/flowDisplay'
import { flowPrintKey } from '@/flowPulse'
import { normalizeWatchSymbol } from '@/watchlist'

export const POWER_ALERT_HISTORY_KEY = 'edge.flow.power-alerts.v1'
export const FLOW_EXCLUSIONS_KEY = 'edge.flow.exclusions.v1'
export const FLOW_LAYOUTS_KEY = 'edge.flow.saved-layouts.v1'

export const CHEAP_CONTRACT_MIN = 0.2
export const CHEAP_CONTRACT_MAX = 0.7
export const POWER_ALERT_LIMIT = 40
export const POWER_ALERT_HISTORY_MAX = 400
export const POWER_ALERT_HISTORY_DAYS = 14
export const TRACKER_DAYS = 5
export const MAX_SAVED_LAYOUTS = 6
export const MAX_EXCLUSIONS = 40

export type PowerAlertLean = 'signed-bullish' | 'signed-bearish' | 'call' | 'put' | 'unsigned'

export interface PowerAlert {
  key: string
  symbol: string
  right: 'call' | 'put'
  strike: number | null
  expiry: string | null
  dte: number | null
  premium: number
  price: number | null
  contracts: number | null
  openInterest: number | null
  volOi: number | null
  firstSpot: number | null
  currentSpot: number | null
  spotMovePct: number | null
  firstPrice: number | null
  currentPrice: number | null
  premiumMovePct: number | null
  timestamp: string
  sessionDate: string
  strength: number
  lean: PowerAlertLean
  leanLabel: string
  orderLabel: string
  orderClass: string
  cheap: boolean
  why: string[]
  heat: number | null
}

export interface PersistedPowerAlert {
  key: string
  symbol: string
  sessionDate: string
  timestamp: string
  firstSpot: number | null
  firstPrice: number | null
  right: 'call' | 'put' | string
  strike: number | null
  expiry: string | null
  premium: number
  strength: number
  lean: PowerAlertLean
}

export interface PowerAlertDayBucket {
  date: string
  count: number
  firstSpot: number | null
  lastSpot: number | null
  spotMovePct: number | null
}

export interface FiveDayTracker {
  symbol: string
  days: PowerAlertDayBucket[]
  totalAlerts: number
  firstAppearanceSpot: number | null
  currentSpot: number | null
  spotMovePct: number | null
}

export interface SignedStreak {
  lean: 'signed-bullish' | 'signed-bearish'
  count: number
}

export interface FlowSymbolQuery {
  includes: string[]
  excludes: string[]
}

export interface FlowFilterLayout {
  id: string
  name: string
  savedAt: string
  tapePreset: string
  activityFilter: string
  rightFilter: string
  dteFilter: string
  moneynessFilter: string
  selectedSector: string
  minPremium: number
  symbolQuery: string
}

function finite(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function defaultStorage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

export function sessionDate(timestamp: string, now: Date = new Date()): string {
  const parsed = Date.parse(timestamp)
  const date = Number.isFinite(parsed) ? new Date(parsed) : now
  return date.toISOString().slice(0, 10)
}

export function isCheapContract(price: unknown): boolean {
  const value = finite(price)
  if (value == null) return false
  return value >= CHEAP_CONTRACT_MIN && value <= CHEAP_CONTRACT_MAX
}

export function powerAlertLean(print: MarketFlowPrint): PowerAlertLean {
  const bias = String(print.bias ?? '')
    .trim()
    .toLowerCase()
  if (bias === 'bullish') return 'signed-bullish'
  if (bias === 'bearish') return 'signed-bearish'
  const aggressor = String(print.aggressor ?? print.aggressor_label ?? '')
    .trim()
    .toLowerCase()
  if (
    aggressor === 'buy' ||
    aggressor === 'long' ||
    aggressor === 'ask' ||
    aggressor === 'above_ask'
  ) {
    return 'signed-bullish'
  }
  if (
    aggressor === 'sell' ||
    aggressor === 'short' ||
    aggressor === 'bid' ||
    aggressor === 'below_bid'
  ) {
    return 'signed-bearish'
  }
  if (print.right === 'call') return 'call'
  if (print.right === 'put') return 'put'
  return 'unsigned'
}

export function powerAlertLeanLabel(lean: PowerAlertLean): string {
  if (lean === 'signed-bullish') return 'SIGNED LONG'
  if (lean === 'signed-bearish') return 'SIGNED SHORT'
  if (lean === 'call') return 'CALL IDENTITY'
  if (lean === 'put') return 'PUT IDENTITY'
  return 'NO SIGNED SIDE'
}

export function isPowerAlertCandidate(print: MarketFlowPrint): boolean {
  if (!normalizeWatchSymbol(print.symbol)) return false
  const classified = classifyFlowOrder(print)
  const volOi = computeVolOiRatio(print.contracts ?? print.volume, print.open_interest)
  const premium = finite(print.premium) ?? 0
  const heat = finite(print.heat)
  const hot = heat != null && (heat >= 0.7 || heat >= 70)
  const presets = print.presets ?? []
  const flags = print.anomaly_flags ?? []
  return (
    print.is_unusual === true ||
    print.is_sweep === true ||
    print.is_block === true ||
    print.is_momentum === true ||
    print.is_moonshot === true ||
    classified.type === 'sweep' ||
    classified.type === 'golden_sweep' ||
    classified.type === 'block' ||
    volOi.isHigh ||
    premium >= 100_000 ||
    hot ||
    presets.includes('unusual') ||
    presets.includes('sweeps') ||
    presets.includes('momentum') ||
    presets.includes('moonshot') ||
    flags.some((flag) =>
      ['premium_outlier', 'volume_outlier', 'repeat_cluster', 'sweep_burst'].includes(String(flag)),
    )
  )
}

export function scorePowerAlert(print: MarketFlowPrint): number {
  const premium = Math.max(0, finite(print.premium) ?? 0)
  const premiumPts = Math.min(Math.log1p(premium) / Math.log1p(1_000_000), 1) * 40
  const unusual = print.is_unusual === true || (print.presets ?? []).includes('unusual') ? 15 : 0
  const classified = classifyFlowOrder(print)
  const sweepPts = classified.type === 'sweep' || classified.type === 'golden_sweep' ? 12 : 0
  const goldenPts = classified.type === 'golden_sweep' ? 10 : 0
  const blockPts = classified.type === 'block' ? 8 : 0
  const volOi = computeVolOiRatio(print.contracts ?? print.volume, print.open_interest)
  const volOiPts = volOi.isExtreme ? 16 : volOi.isHigh ? 10 : 0
  const heat = finite(print.heat)
  let heatPts = 0
  if (heat != null) {
    const normalized = heat > 1 ? heat / 100 : heat
    heatPts = Math.max(0, Math.min(1, normalized)) * 8
  }
  const cheapPts = isCheapContract(print.price) ? 5 : 0
  const clusterPts = (print.anomaly_flags ?? []).some(
    (flag) =>
      String(flag).toLowerCase().includes('repeat') ||
      String(flag).toLowerCase().includes('cluster'),
  )
    ? 6
    : 0
  const percentile = finite(print.premium_percentile)
  const pctPts = percentile != null ? Math.max(0, Math.min(1, percentile)) * 8 : 0
  return Math.round(
    Math.min(
      100,
      premiumPts +
        unusual +
        sweepPts +
        goldenPts +
        blockPts +
        volOiPts +
        heatPts +
        cheapPts +
        clusterPts +
        pctPts,
    ),
  )
}

export function powerAlertWhy(print: MarketFlowPrint): string[] {
  const why = [...(print.why ?? [])]
  const classified = classifyFlowOrder(print)
  if (classified.type === 'golden_sweep') why.push('Vendor golden flag')
  else if (classified.type === 'sweep') why.push('Sweep')
  if (classified.type === 'block') why.push('Block')
  if (print.is_unusual) why.push('Unusual')
  const volOi = computeVolOiRatio(print.contracts ?? print.volume, print.open_interest)
  if (volOi.isHigh) why.push(`Vol/OI ${volOi.formatted}`)
  if (isCheapContract(print.price)) why.push('Cheap contract')
  const premium = finite(print.premium)
  if (premium != null && premium >= 1_000_000) why.push('$1M+ premium')
  else if (premium != null && premium >= 500_000) why.push('$500k+ premium')
  else if (premium != null && premium >= 100_000) why.push('$100k+ premium')
  return [...new Set(why)].slice(0, 6)
}

function relativeMove(first: number | null, current: number | null): number | null {
  if (first == null || current == null || first === 0) return null
  return (current - first) / first
}

export function parseFlowSymbolQuery(raw: string): FlowSymbolQuery {
  const tokens = String(raw || '')
    .toUpperCase()
    .split(/[\s,]+/)
    .map((token) => token.trim())
    .filter(Boolean)
  const includes: string[] = []
  const excludes: string[] = []
  for (const token of tokens) {
    if (token.startsWith('-') && token.length > 1) {
      const symbol = normalizeWatchSymbol(token.slice(1))
      if (symbol) excludes.push(symbol)
      continue
    }
    const stripped = token.startsWith('+') ? token.slice(1) : token
    const symbol = normalizeWatchSymbol(stripped)
    if (symbol) includes.push(symbol)
  }
  return { includes, excludes }
}

export function symbolPassesQuery(
  symbol: string,
  query: FlowSymbolQuery,
  persistedExcludes: Iterable<string> = [],
): boolean {
  const normalized = normalizeWatchSymbol(symbol)
  if (!normalized) return false
  const blocked = new Set(
    [...persistedExcludes, ...query.excludes].map(normalizeWatchSymbol).filter(Boolean),
  )
  if (blocked.has(normalized)) return false
  if (!query.includes.length) return true
  return query.includes.some((needle) => normalized.includes(needle) || needle.includes(normalized))
}

function uniqueSymbols(values: unknown): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const value of Array.isArray(values) ? values : []) {
    const symbol = normalizeWatchSymbol(value)
    if (!symbol || seen.has(symbol)) continue
    seen.add(symbol)
    out.push(symbol)
    if (out.length >= MAX_EXCLUSIONS) break
  }
  return out
}

export function loadExclusions(
  storage: Pick<Storage, 'getItem'> | null | undefined = defaultStorage(),
): string[] {
  if (!storage) return []
  try {
    return uniqueSymbols(JSON.parse(storage.getItem(FLOW_EXCLUSIONS_KEY) ?? '[]'))
  } catch {
    return []
  }
}

export function saveExclusions(
  symbols: unknown,
  storage: Pick<Storage, 'setItem'> | null | undefined = defaultStorage(),
): string[] {
  const next = uniqueSymbols(symbols)
  if (storage) {
    try {
      storage.setItem(FLOW_EXCLUSIONS_KEY, JSON.stringify(next))
    } catch {
      // Quota / private mode must not break Flow.
    }
  }
  return next
}

export function loadAlertHistory(
  storage: Pick<Storage, 'getItem'> | null | undefined = defaultStorage(),
): PersistedPowerAlert[] {
  if (!storage) return []
  try {
    const raw = JSON.parse(storage.getItem(POWER_ALERT_HISTORY_KEY) ?? '[]')
    if (!Array.isArray(raw)) return []
    return raw
      .map((row) => normalizePersisted(row))
      .filter((row): row is PersistedPowerAlert => row != null)
  } catch {
    return []
  }
}

function normalizePersisted(row: unknown): PersistedPowerAlert | null {
  if (!row || typeof row !== 'object') return null
  const record = row as Record<string, unknown>
  const symbol = normalizeWatchSymbol(record.symbol)
  const key = String(record.key || '')
  if (!symbol || !key) return null
  const lean = String(record.lean || 'unsigned') as PowerAlertLean
  return {
    key,
    symbol,
    sessionDate: String(record.sessionDate || '').slice(0, 10),
    timestamp: String(record.timestamp || ''),
    firstSpot: finite(record.firstSpot),
    firstPrice: finite(record.firstPrice),
    right: String(record.right || ''),
    strike: finite(record.strike),
    expiry: record.expiry == null ? null : String(record.expiry),
    premium: finite(record.premium) ?? 0,
    strength: finite(record.strength) ?? 0,
    lean:
      lean === 'signed-bullish' || lean === 'signed-bearish' || lean === 'call' || lean === 'put'
        ? lean
        : 'unsigned',
  }
}

export function saveAlertHistory(
  rows: Iterable<PersistedPowerAlert>,
  storage: Pick<Storage, 'setItem'> | null | undefined = defaultStorage(),
  now: Date = new Date(),
): PersistedPowerAlert[] {
  const cutoff = new Date(now.getTime() - POWER_ALERT_HISTORY_DAYS * 86_400_000)
    .toISOString()
    .slice(0, 10)
  const seen = new Set<string>()
  const next: PersistedPowerAlert[] = []
  for (const row of [...rows].reverse()) {
    if (!row.key || seen.has(row.key)) continue
    if (row.sessionDate && row.sessionDate < cutoff) continue
    seen.add(row.key)
    next.push(row)
    if (next.length >= POWER_ALERT_HISTORY_MAX) break
  }
  next.reverse()
  if (storage) {
    try {
      storage.setItem(POWER_ALERT_HISTORY_KEY, JSON.stringify(next))
    } catch {
      // Ignore persistence failures.
    }
  }
  return next
}

function contractKey(print: MarketFlowPrint): string {
  return [
    normalizeWatchSymbol(print.symbol),
    print.right,
    finite(print.strike) ?? '',
    print.expiry ?? '',
  ].join('|')
}

export function buildPowerAlerts(input: {
  prints: MarketFlowPrint[]
  rows?: UnusualFlowRow[]
  history?: PersistedPowerAlert[]
  now?: Date
  limit?: number
}): { alerts: PowerAlert[]; history: PersistedPowerAlert[] } {
  const now = input.now ?? new Date()
  const spotBySymbol = new Map<string, number>()
  const priceByContract = new Map<string, number>()
  for (const row of input.rows ?? []) {
    const spot = finite(row.spot)
    if (spot != null) spotBySymbol.set(normalizeWatchSymbol(row.symbol), spot)
  }
  for (const print of input.prints) {
    const symbol = normalizeWatchSymbol(print.symbol)
    const spot = finite(print.underlying_price)
    if (symbol && spot != null) spotBySymbol.set(symbol, spot)
    const price = finite(print.price)
    if (price != null) priceByContract.set(contractKey(print), price)
  }

  const prior = new Map((input.history ?? []).map((row) => [row.key, row]))
  const live: PowerAlert[] = []
  const nextHistory = [...(input.history ?? [])]

  for (const print of input.prints) {
    if (!isPowerAlertCandidate(print)) continue
    const symbol = normalizeWatchSymbol(print.symbol)
    if (!symbol) continue
    const key = flowPrintKey(print)
    const classified = classifyFlowOrder(print)
    const lean = powerAlertLean(print)
    const firstFromHistory = prior.get(key)
    const currentSpot = spotBySymbol.get(symbol) ?? finite(print.underlying_price)
    const currentPrice = priceByContract.get(contractKey(print)) ?? finite(print.price)
    const firstSpot = firstFromHistory?.firstSpot ?? finite(print.underlying_price)
    const firstPrice = firstFromHistory?.firstPrice ?? finite(print.price)
    const timestamp = String(print.timestamp || '')
    const alert: PowerAlert = {
      key,
      symbol,
      right: print.right,
      strike: finite(print.strike),
      expiry: print.expiry ?? null,
      dte: finite(print.dte),
      premium: finite(print.premium) ?? 0,
      price: finite(print.price),
      contracts: finite(print.contracts ?? print.volume),
      openInterest: finite(print.open_interest),
      volOi: computeVolOiRatio(print.contracts ?? print.volume, print.open_interest).ratio,
      firstSpot,
      currentSpot: currentSpot ?? null,
      spotMovePct: relativeMove(firstSpot, currentSpot ?? null),
      firstPrice,
      currentPrice: currentPrice ?? null,
      premiumMovePct: relativeMove(firstPrice, currentPrice ?? null),
      timestamp,
      sessionDate: sessionDate(timestamp, now),
      strength: scorePowerAlert(print),
      lean,
      leanLabel: powerAlertLeanLabel(lean),
      orderLabel: classified.label,
      orderClass: classified.className,
      cheap: isCheapContract(print.price),
      why: powerAlertWhy(print),
      heat: finite(print.heat),
    }
    live.push(alert)
    if (!prior.has(key)) {
      nextHistory.push({
        key,
        symbol,
        sessionDate: alert.sessionDate,
        timestamp,
        firstSpot,
        firstPrice,
        right: print.right,
        strike: alert.strike,
        expiry: alert.expiry,
        premium: alert.premium,
        strength: alert.strength,
        lean,
      })
      prior.set(key, nextHistory[nextHistory.length - 1])
    }
  }

  live.sort(
    (a, b) => b.strength - a.strength || b.premium - a.premium || a.symbol.localeCompare(b.symbol),
  )
  const limit = Math.max(1, input.limit ?? POWER_ALERT_LIMIT)
  return {
    alerts: live.slice(0, limit),
    history: saveAlertHistory(nextHistory, undefined, now),
  }
}

export function persistPowerAlertHistory(
  history: PersistedPowerAlert[],
  storage: Pick<Storage, 'setItem'> | null | undefined = defaultStorage(),
  now: Date = new Date(),
): PersistedPowerAlert[] {
  return saveAlertHistory(history, storage, now)
}

export function fiveDayTracker(input: {
  symbol: string
  history: PersistedPowerAlert[]
  currentSpot?: number | null
  now?: Date
}): FiveDayTracker {
  const symbol = normalizeWatchSymbol(input.symbol)
  const now = input.now ?? new Date()
  const days: PowerAlertDayBucket[] = []
  for (let offset = TRACKER_DAYS - 1; offset >= 0; offset -= 1) {
    const date = new Date(
      Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - offset),
    )
      .toISOString()
      .slice(0, 10)
    const rows = input.history.filter((row) => row.symbol === symbol && row.sessionDate === date)
    const spots = rows.map((row) => row.firstSpot).filter((value): value is number => value != null)
    const firstSpot = spots[0] ?? null
    const lastSpot = spots.length ? spots[spots.length - 1] : null
    days.push({
      date,
      count: rows.length,
      firstSpot,
      lastSpot,
      spotMovePct: relativeMove(firstSpot, lastSpot),
    })
  }
  const symbolHistory = input.history.filter((row) => row.symbol === symbol)
  const firstAppearanceSpot = symbolHistory[0]?.firstSpot ?? null
  const currentSpot = input.currentSpot ?? null
  return {
    symbol,
    days,
    totalAlerts: days.reduce((sum, day) => sum + day.count, 0),
    firstAppearanceSpot,
    currentSpot,
    spotMovePct: relativeMove(firstAppearanceSpot, currentSpot),
  }
}

export function signedStreak(history: PersistedPowerAlert[], symbol: string): SignedStreak | null {
  const rows = history.filter((row) => row.symbol === normalizeWatchSymbol(symbol))
  if (!rows.length) return null
  const last = rows[rows.length - 1]
  if (last.lean !== 'signed-bullish' && last.lean !== 'signed-bearish') return null
  let count = 0
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    if (rows[index].lean !== last.lean) break
    count += 1
  }
  return count >= 2 ? { lean: last.lean, count } : null
}

export function largestOrders(
  prints: MarketFlowPrint[],
  symbol: string,
  limit = 5,
): MarketFlowPrint[] {
  const needle = normalizeWatchSymbol(symbol)
  return [...prints]
    .filter((print) => normalizeWatchSymbol(print.symbol) === needle)
    .sort((a, b) => (finite(b.premium) ?? 0) - (finite(a.premium) ?? 0))
    .slice(0, limit)
}

export function alertPathPoints(
  prints: MarketFlowPrint[],
  symbol: string,
): Array<{ key: string; t: string; y: number }> {
  const needle = normalizeWatchSymbol(symbol)
  const points: Array<{ key: string; t: string; y: number }> = []
  for (const print of [...prints].sort((a, b) =>
    String(a.timestamp).localeCompare(String(b.timestamp)),
  )) {
    if (normalizeWatchSymbol(print.symbol) !== needle) continue
    const y = finite(print.underlying_price)
    if (y == null) continue
    points.push({ key: flowPrintKey(print), t: String(print.timestamp || ''), y })
  }
  return points
}

export function loadFlowLayouts(
  storage: Pick<Storage, 'getItem'> | null | undefined = defaultStorage(),
): FlowFilterLayout[] {
  if (!storage) return []
  try {
    const raw = JSON.parse(storage.getItem(FLOW_LAYOUTS_KEY) ?? '[]')
    if (!Array.isArray(raw)) return []
    return raw
      .map((row) => normalizeLayout(row))
      .filter((row): row is FlowFilterLayout => row != null)
      .slice(0, MAX_SAVED_LAYOUTS)
  } catch {
    return []
  }
}

function normalizeLayout(row: unknown): FlowFilterLayout | null {
  if (!row || typeof row !== 'object') return null
  const record = row as Record<string, unknown>
  const name = String(record.name || '')
    .trim()
    .slice(0, 32)
  const id = String(record.id || '')
  if (!name || !id) return null
  return {
    id,
    name,
    savedAt: String(record.savedAt || ''),
    tapePreset: String(record.tapePreset || 'all'),
    activityFilter: String(record.activityFilter || 'all'),
    rightFilter: String(record.rightFilter || 'all'),
    dteFilter: String(record.dteFilter || 'all'),
    moneynessFilter: String(record.moneynessFilter || 'all'),
    selectedSector: String(record.selectedSector || 'all'),
    minPremium: finite(record.minPremium) ?? 25_000,
    symbolQuery: String(record.symbolQuery || ''),
  }
}

export function upsertFlowLayout(
  layouts: FlowFilterLayout[],
  next: FlowFilterLayout,
  storage: Pick<Storage, 'setItem'> | null | undefined = defaultStorage(),
): FlowFilterLayout[] {
  const rest = layouts.filter((row) => row.id !== next.id && row.name !== next.name)
  const saved = [next, ...rest].slice(0, MAX_SAVED_LAYOUTS)
  if (storage) {
    try {
      storage.setItem(FLOW_LAYOUTS_KEY, JSON.stringify(saved))
    } catch {
      // Ignore persistence failures.
    }
  }
  return saved
}

export function removeFlowLayout(
  layouts: FlowFilterLayout[],
  id: string,
  storage: Pick<Storage, 'setItem'> | null | undefined = defaultStorage(),
): FlowFilterLayout[] {
  const saved = layouts.filter((row) => row.id !== id)
  if (storage) {
    try {
      storage.setItem(FLOW_LAYOUTS_KEY, JSON.stringify(saved))
    } catch {
      // Ignore persistence failures.
    }
  }
  return saved
}
