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

export function allowedOperatorEmails(): string[] {
  return String(import.meta.env.VITE_EDGE_ALLOWED_EMAILS ?? '')
    .split(',')
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean)
}

export function isAllowedOperatorEmail(email: string | null | undefined): boolean {
  const allowed = allowedOperatorEmails()
  if (!allowed.length) return true
  const value = (email ?? '').trim().toLowerCase()
  return value.length > 0 && allowed.includes(value)
}

export function safeRedirect(value: unknown, fallback = '/flow'): string {
  if (typeof value !== 'string') return fallback
  if (!value.startsWith('/') || value.startsWith('//') || value.startsWith('/auth')) return fallback
  return value
}

export function operatorLabel(identity: OperatorIdentity | null | undefined): string {
  if (!identity) return 'Operator'
  return identity.displayName || identity.email || 'Operator'
}
