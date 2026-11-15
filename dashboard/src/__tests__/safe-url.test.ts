import { describe, expect, it } from 'vitest'
import { externalHref, safeExternalUrl } from '@/safeUrl'

describe('safeExternalUrl', () => {
  it('keeps ordinary http(s) links, including the original spelling', () => {
    expect(safeExternalUrl('https://efdsearch.senate.gov')).toBe('https://efdsearch.senate.gov')
    expect(safeExternalUrl('  http://sec.gov/edgar/x  ')).toBe('http://sec.gov/edgar/x')
    expect(externalHref('https://fintel.io/u/dev')).toBe('https://fintel.io/u/dev')
  })

  it('drops scripts, credentials, and non-URLs', () => {
    expect(safeExternalUrl("javascript:alert('x')")).toBeNull()
    expect(safeExternalUrl('data:text/html,hi')).toBeNull()
    expect(safeExternalUrl('https://user:pass@sec.gov/x')).toBeNull()
    expect(safeExternalUrl('//sec.gov')).toBeNull()
    expect(safeExternalUrl('')).toBeNull()
    expect(safeExternalUrl(null)).toBeNull()
    expect(externalHref('not a url')).toBeUndefined()
  })
})
