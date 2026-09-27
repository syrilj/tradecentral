import type { MarketFlowPrint } from '@/api'
import { flowPrintKey } from '@/flowPulse'
import { normalizeWatchSymbol, watchlistHas } from '@/watchlist'

export const FLOW_ALERT_SEEN_KEY = 'edge.flow.alert-seen.v1'
export const FLOW_ALERT_UNREAD_KEY = 'edge.flow.alert-unread.v1'

export type FlowAlertKind = 'unusual' | 'sweep' | 'both'

export interface FlowAlert {
  key: string
  symbol: string
  kind: FlowAlertKind
  premium: number
  timestamp: string
  right: string
  strike: number | null
  expiry: string | null
  heat: number | null
}

function finite(value: unknown): number | null {
  const number = Number(value)
  return value !== null && value !== undefined && value !== '' && Number.isFinite(number)
    ? number
    : null
}

export function printAlertKind(row: MarketFlowPrint): FlowAlertKind | null {
  const unusual = row.is_unusual === true || (row.presets ?? []).includes('unusual')
  const sweep =
    row.is_sweep === true || row.trade_class === 'sweep' || (row.presets ?? []).includes('sweeps')
  if (unusual && sweep) return 'both'
  if (unusual) return 'unusual'
  if (sweep) return 'sweep'
  return null
}

export function collectWatchlistAlerts(input: {
  watchlist: unknown
  prints: MarketFlowPrint[]
  seenKeys?: Iterable<string>
  newPrintKeys?: Iterable<string> | null
}): FlowAlert[] {
  const seen = new Set(input.seenKeys ?? [])
  const onlyNew = input.newPrintKeys ? new Set(input.newPrintKeys) : null
  const alerts: FlowAlert[] = []
  for (const row of input.prints) {
    const symbol = normalizeWatchSymbol(row.symbol)
    if (!symbol || !watchlistHas(input.watchlist, symbol)) continue
    const kind = printAlertKind(row)
    if (!kind) continue
    const key = flowPrintKey(row)
    if (seen.has(key)) continue
    if (onlyNew && !onlyNew.has(key)) continue
    alerts.push({
      key,
      symbol,
      kind,
      premium: finite(row.premium) ?? 0,
      timestamp: String(row.timestamp || ''),
      right: String(row.right || ''),
      strike: finite(row.strike),
      expiry: row.expiry ?? null,
      heat: finite(row.heat),
    })
  }
  return alerts
}

export function loadSeenAlertKeys(
  storage: Pick<Storage, 'getItem'> | null | undefined = defaultStorage(),
): Set<string> {
  if (!storage) return new Set()
  try {
    const raw = JSON.parse(storage.getItem(FLOW_ALERT_SEEN_KEY) ?? '[]')
    return new Set(Array.isArray(raw) ? raw.map(String) : [])
  } catch {
    return new Set()
  }
}

export function saveSeenAlertKeys(
  keys: Iterable<string>,
  storage: Pick<Storage, 'setItem'> | null | undefined = defaultStorage(),
): string[] {
  const next = [...new Set([...keys])].slice(-400)
  if (storage) {
    try {
      storage.setItem(FLOW_ALERT_SEEN_KEY, JSON.stringify(next))
    } catch {
      // Quota / private mode must not break Flow.
    }
  }
  return next
}

export function unreadAlertCount(
  storage: Pick<Storage, 'getItem'> | null | undefined = defaultStorage(),
): number {
  if (!storage) return 0
  try {
    const value = Number(storage.getItem(FLOW_ALERT_UNREAD_KEY) ?? 0)
    return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0
  } catch {
    return 0
  }
}

export function saveUnreadAlertCount(
  count: number,
  storage: Pick<Storage, 'setItem'> | null | undefined = defaultStorage(),
): number {
  const next = Math.max(0, Math.floor(count))
  if (storage) {
    try {
      storage.setItem(FLOW_ALERT_UNREAD_KEY, String(next))
    } catch {
      // Ignore persistence failures.
    }
  }
  return next
}

function defaultStorage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}
