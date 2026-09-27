/**
 * Clerk operator access helpers.
 *
 * Clerk authenticates the dashboard operator. That is a session lock for the
 * SPA, not a claim that the loopback API is now safe to publish on a LAN.
 * Network exposure still requires a separately authenticated reverse proxy.
 */

export interface OperatorIdentity {
  displayName: string
  email: string
}

/** `EDGE_AUTH_MODE=local` runs the desk on a zero-credential workstation
 * session: the SPA never initializes Clerk (no publishable key required) and
 * the API stays isolated by its loopback bind. Anything else keeps the Clerk
 * operator session. Mirrored server-side in tools/api_server.py. */
export type OperatorAuthMode = 'clerk' | 'local'

export function operatorAuthMode(): OperatorAuthMode {
  const raw = String(import.meta.env.VITE_EDGE_AUTH_MODE ?? '')
    .trim()
    .toLowerCase()
  return raw === 'local' ? 'local' : 'clerk'
}

export function isLocalAuthMode(): boolean {
  // Local bypass is an explicit development choice. A missing Clerk key must
  // never silently turn a production deployment into an unauthenticated app.
  return operatorAuthMode() === 'local' && !import.meta.env.PROD
}

export function allowedOperatorEmails(): string[] {
  return String(import.meta.env.VITE_EDGE_ALLOWED_EMAILS ?? '')
    .split(',')
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean)
}

export function isAllowedOperatorEmail(email: string | null | undefined): boolean {
  const value = (email ?? '').trim().toLowerCase()
  return value !== '' && allowedOperatorEmails().includes(value)
}

export function safeRedirect(value: unknown, fallback = '/flow'): string {
  if (typeof value !== 'string') return fallback
  if (!value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) return fallback
  try {
    const target = new URL(value, 'https://tradecentral.invalid')
    if (target.origin !== 'https://tradecentral.invalid') return fallback
    if (
      target.pathname === '/auth' ||
      target.pathname.startsWith('/auth/') ||
      target.pathname === '/waitlist'
    ) return fallback
    return `${target.pathname}${target.search}${target.hash}`
  } catch {
    return fallback
  }
}

export function operatorLabel(identity: OperatorIdentity | null | undefined): string {
  if (!identity) return 'Operator'
  return identity.displayName || identity.email || 'Operator'
}
