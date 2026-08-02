/**
 * Typed client for edge/tools/api_server.py.
 *
 * Every call funnels through `req()` so a dead backend surfaces as a typed
 * error rather than an unhandled rejection. In a trading surface a silently
 * stale panel is worse than a visibly broken one, so callers are expected to
 * render the error, not swallow it.
 */

const BASE = import.meta.env.DEV ? '' : ''

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly endpoint: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { Accept: 'application/json' },
      ...init,
    })
  } catch (e) {
    throw new ApiError(
      `backend unreachable — is api_server.py running on :8787?`,
      0,
      path,
    )
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { error?: string }
      if (body?.error) detail = body.error
    } catch {
      /* non-JSON error body; keep statusText */
    }
    throw new ApiError(detail, res.status, path)
  }
  return (await res.json()) as T
}

/* ------------------------------------------------------------------ types */

export type Verdict = 'GO' | 'NO-GO' | 'UNKNOWN' | string

export interface VolReadout {
  VIX: number
  term_slope: number
  tail_risk: number
  date: string
}

export interface DirectionalSignal {
  symbol: string
  [k: string]: unknown
}

export interface PeadCandidate {
  symbol: string
  [k: string]: unknown
}

export interface LeaderboardRow {
  [k: string]: unknown
}

export interface StatusPayload {
  asof: string
  broad_universe_count: number
  pead_candidates: PeadCandidate[]
  directional_signals: DirectionalSignal[]
  sector_flow: Record<string, unknown>
  latest_vol: VolReadout
  pead_metrics: Record<string, number | string | Record<string, boolean>>
  gcp_resources: Record<string, unknown>
  leaderboard: LeaderboardRow[]
}

export interface SearchHit {
  symbol: string
  kind?: 'symbol' | 'track'
  name?: string
  category?: string
  description?: string
  tier: 'wide' | 'core'
  n_bars: number
  first_date: string
  last_date: string
}

export interface TrajectoryBar {
  d: string
  o: number
  h: number
  l: number
  c: number
  v: number
  ret: number
  cum: number
  dd: number
}

export interface TrajectoryStats {
  last_price: number
  chg_1d_pct: number
  chg_5d_pct: number
  chg_1m_pct: number
  chg_3m_pct: number
  chg_ytd_pct: number
  chg_window_pct: number
  ann_return_pct: number
  ann_vol_pct: number
  sharpe: number | null
  max_drawdown_pct: number
  calmar: number | null
  atr_20: number
  atr_pct: number
  adv_20_usd: number
  best_day_pct: number
  worst_day_pct: number
  pct_days_up: number
}

export interface Trajectory {
  symbol: string
  window: string
  n_bars: number
  first_date: string
  last_date: string
  source: string
  series: TrajectoryBar[]
  stats: TrajectoryStats
  factors: Record<string, number | null>
}

export interface ComparePayload {
  window: string
  series: Record<string, { d: string; cum: number }[]>
  stats: Record<string, Partial<TrajectoryStats>>
  correlation: Record<string, Record<string, number>>
}

export interface Gate {
  id: string
  name: string
  verdict: Verdict
  source_file: string
  metrics: Record<string, number | string | null>
  checks: Record<string, boolean>
  updated: string | null
}

export interface Readiness {
  asof: string
  cleared_for_live: boolean
  blocking_reasons: string[]
  shadow: {
    n_sessions: number
    required: number
    latest_decision: unknown
    reliability: Record<string, unknown> | null
  }
  gates_summary: { go: number; no_go: number; unknown: number }
}

export interface Health {
  ok: boolean
  ts: string
  symbols_indexed: number
  uptime_s: number
}

export type TrajWindow = '1m' | '3m' | '6m' | '1y' | '3y' | '5y' | 'max'

export const WINDOWS: TrajWindow[] = ['1m', '3m', '6m', '1y', '3y', '5y', 'max']

/* ---------------------------------------------------------------- endpoints */

export const api = {
  health: () => req<Health>('/api/health'),
  status: () => req<StatusPayload>('/api/status'),
  leaderboard: () => req<{ asof: string; leaderboard: LeaderboardRow[] }>('/api/leaderboard'),
  gcp: () => req<Record<string, unknown>>('/api/gcp'),
  gates: () => req<{ gates: Gate[] }>('/api/gates'),
  readiness: () => req<Readiness>('/api/readiness'),

  search: (q: string, limit = 25) =>
    req<{ results: SearchHit[] } | SearchHit[]>(
      `/api/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ).then(normalizeSearch),

  trajectory: (symbol: string, window: TrajWindow = '1y') =>
    req<Trajectory>(
      `/api/trajectory?symbol=${encodeURIComponent(symbol)}&window=${window}`,
    ),

  compare: (symbols: string[], window: TrajWindow = '1y') =>
    req<ComparePayload>(
      `/api/compare?symbols=${encodeURIComponent(symbols.join(','))}&window=${window}`,
    ),

  analyze: (symbol: string) =>
    req<Record<string, unknown>>(`/api/analyze?symbol=${encodeURIComponent(symbol)}`),

  triggerScan: () =>
    req<{ status: string; message: string; asof?: string }>('/api/trigger_scan', {
      method: 'POST',
    }),
}

/** The server may return a bare array or a wrapped object; accept both. */
function normalizeSearch(r: { results: SearchHit[] } | SearchHit[]): SearchHit[] {
  return Array.isArray(r) ? r : (r.results ?? [])
}
