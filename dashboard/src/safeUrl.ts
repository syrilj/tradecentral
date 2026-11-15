/**
 * Provider and filing links are data, not trusted markup.
 * Only an http(s) URL with no embedded credentials may become an href.
 */
export function safeExternalUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (!trimmed) return null
  let url: URL
  try {
    url = new URL(trimmed)
  } catch {
    return null
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null
  if (url.username || url.password) return null
  return trimmed
}

export function externalHref(value: unknown): string | undefined {
  return safeExternalUrl(value) ?? undefined
}
