import type { ChangepointRegime, ChangepointRow, ChangepointThresholds } from '@/api'

export interface ChangepointInsightLine {
  label: string
  value: string
  tone: 'ok' | 'warn' | 'hot' | 'dim'
  note: string
}

export const DEFAULT_BREAK_THRESHOLD = 0.5
export const DEFAULT_SETTLING_RUNS = 10
export const BOARD_STALE_AFTER_DAYS = 3

export function parseUtcMs(value: string | null | undefined): number | null {
  if (!value) return null
  const stamp = Date.parse(value.length <= 10 ? `${value}T00:00:00Z` : value)
  return Number.isFinite(stamp) ? stamp : null
}

export function artifactAgeDays(
  asof?: string | null,
  generatedAt?: string | null,
  nowMs: number = Date.now(),
): number | null {
  const stamp = parseUtcMs(asof) ?? parseUtcMs(generatedAt)
  if (stamp == null) return null
  return Math.max(0, Math.floor((nowMs - stamp) / 86_400_000))
}

export function artifactIsStale(
  ageDays: number | null,
  thresholdDays: number = BOARD_STALE_AFTER_DAYS,
): boolean {
  return ageDays != null && ageDays > thresholdDays
}

export function regimeFromBreak(
  breakProb: number,
  mapRun: number,
  thresholds: Pick<ChangepointThresholds, 'break' | 'settling'> = {
    break: DEFAULT_BREAK_THRESHOLD,
    settling: DEFAULT_SETTLING_RUNS,
  },
): ChangepointRegime {
  if (!Number.isFinite(breakProb)) return 'STABLE'
  if (breakProb >= (thresholds.break ?? DEFAULT_BREAK_THRESHOLD)) return 'BREAK'
  if (Number.isFinite(mapRun) && mapRun <= (thresholds.settling ?? DEFAULT_SETTLING_RUNS)) {
    return 'SETTLING'
  }
  return 'STABLE'
}

function pctFrac(v: number | null | undefined, dp = 1): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${(v * 100).toFixed(dp)}%`
}

function num(v: number | null | undefined, dp = 0): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toFixed(dp)
}

export function insightFromRow(
  row: Pick<
    ChangepointRow,
    'regime' | 'break_prob' | 'map_run_length' | 'days_since_break' | 'predictive_vol' | 'trailing_vol_20d' | 'vol_ratio'
  >,
  thresholds: Pick<ChangepointThresholds, 'break' | 'settling'> = {
    break: DEFAULT_BREAK_THRESHOLD,
    settling: DEFAULT_SETTLING_RUNS,
  },
): ChangepointInsightLine[] {
  const breakCut = thresholds.break ?? DEFAULT_BREAK_THRESHOLD
  const settlingCut = thresholds.settling ?? DEFAULT_SETTLING_RUNS
  const regime = row.regime || regimeFromBreak(row.break_prob, row.map_run_length, thresholds)
  const bp = row.break_prob
  const mapRun = row.map_run_length
  const dsb = row.days_since_break
  const predVol = row.predictive_vol
  const trailVol = row.trailing_vol_20d
  const vr = row.vol_ratio

  const lines: ChangepointInsightLine[] = []
  lines.push({
    label: 'Regime',
    value: String(regime),
    tone: regime === 'BREAK' ? 'hot' : regime === 'SETTLING' ? 'warn' : 'ok',
    note:
      regime === 'BREAK'
        ? 'Variance just reset — model discarding old vol estimate. Expect unstable options pricing.'
        : regime === 'SETTLING'
          ? `MAP run ${mapRun} bars — model is rebuilding its vol estimate. Still uncertain.`
          : `MAP run ${mapRun} bars — regime stable, vol estimate reliable.`,
  })

  if (dsb != null && Number.isFinite(dsb)) {
    const fresh = dsb <= 3
    lines.push({
      label: 'Break age',
      value: `${dsb}d ago`,
      tone: fresh ? 'hot' : dsb <= 10 ? 'warn' : 'dim',
      note: fresh
        ? 'Break is very fresh (≤3 bars). Vol structure is actively changing — unreliable for options scoring.'
        : dsb <= 10
          ? 'Break within the last 10 bars. Settling but still elevated uncertainty.'
          : `Break ${dsb} bars ago — regime has had time to stabilize.`,
    })
  } else {
    lines.push({ label: 'Break age', value: '—', tone: 'dim', note: 'No break detected in this window.' })
  }

  if (predVol != null && trailVol != null && trailVol > 0) {
    const vrNum = vr ?? predVol / trailVol
    lines.push({
      label: 'Pred / Trail vol',
      value: `${pctFrac(predVol, 2)} / ${pctFrac(trailVol, 2)}`,
      tone: vrNum >= 1.3 ? 'hot' : vrNum >= 1.1 ? 'warn' : vrNum <= 0.8 ? 'warn' : 'ok',
      note:
        vrNum >= 1.3
          ? `Vol ratio ${num(vrNum, 2)} — model expects materially more vol than 20d history. Potential vol expansion; avoid short vol strategies.`
          : vrNum >= 1.1
            ? `Vol ratio ${num(vrNum, 2)} — model slightly above recent history. Watch for regime continuation.`
            : vrNum <= 0.8
              ? `Vol ratio ${num(vrNum, 2)} — model below recent history. Possible vol compression or overshoot; tail risk from mean-reversion.`
              : `Vol ratio ${num(vrNum, 2)} — model in line with recent realized vol. Regime appears stable.`,
    })
  } else {
    lines.push({ label: 'Pred / Trail vol', value: '—', tone: 'dim', note: 'Insufficient data to compute vol ratio.' })
  }

  const warnCut = breakCut * 0.5
  lines.push({
    label: 'Break prob (5d)',
    value: pctFrac(bp, 1),
    tone: bp >= breakCut ? 'hot' : bp >= warnCut ? 'warn' : 'ok',
    note:
      bp >= breakCut
        ? `Above ${pctFrac(breakCut, 0)} threshold — this name is in active break state. Do not assume the current vol reading is stable.`
        : bp >= warnCut
          ? `Elevated vs ${pctFrac(breakCut, 0)} break / ${num(settlingCut, 0)}-bar settle cuts. Monitor for confirmation.`
          : `Below ${pctFrac(breakCut, 0)} threshold — no active break detected.`,
  })

  return lines
}

export const CHANGEPOINT_FIGURE_LABELS = {
  x: 'Date',
  yTop: 'Daily return',
  yBottom: 'Run length (bars)',
  heatmap: 'log10 P(r_t | x_1:t)',
} as const
