/**
 * Market-clock session labels for the shell strip.
 * CAL SYNC is only the absent-payload fallback — a present session maps.
 */

export const MARKET_SESSION_LABELS: Record<string, string> = {
  regular: 'RTH OPEN',
  premarket: 'PREMARKET',
  after_hours: 'AFTER HOURS',
  closed: 'MARKET CLOSED',
  replay: 'REPLAY',
}

export const MARKET_TRANSITION_VERBS: Record<string, string> = {
  premarket_opens: 'PRE IN',
  regular_opens: 'OPEN IN',
  regular_closes: 'CLOSE IN',
  after_hours_closes: 'EXT CLOSE',
}

export function marketSessionLabel(
  session: string | null | undefined,
  options: { error?: boolean } = {},
): string {
  if (options.error) return 'CAL FAULT'
  if (!session) return 'CAL SYNC'
  return MARKET_SESSION_LABELS[session] ?? 'CAL SYNC'
}

export function marketSessionClass(session: string | null | undefined): string {
  return session || 'unknown'
}

export function formatMarketCountdown(
  nextTransitionUtc: string | null | undefined,
  nextTransition: string | null | undefined,
  nowMs: number,
): string {
  if (!nextTransitionUtc || !nextTransition) return 'NEXT n/a'
  const seconds = Math.max(0, Math.floor((Date.parse(nextTransitionUtc) - nowMs) / 1000))
  if (!Number.isFinite(seconds)) return 'NEXT n/a'
  const days = Math.floor(seconds / 86_400)
  const hours = Math.floor((seconds % 86_400) / 3_600)
  const minutes = Math.floor((seconds % 3_600) / 60)
  const secs = seconds % 60
  const countdown =
    days > 0
      ? `${days}D ${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
      : `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
  return `${MARKET_TRANSITION_VERBS[nextTransition] ?? 'NEXT'} ${countdown}`
}
