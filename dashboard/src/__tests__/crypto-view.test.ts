import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Crypto workspace (24/7 coin board)', () => {
  const view = source('views/CryptoView.vue')
  const apiSrc = source('api.ts')

  it('composes existing clients rather than a new vendor', () => {
    expect(apiSrc).toContain('CRYPTO_TAPE_SLEEVES')
    expect(apiSrc).toContain('CRYPTO_TAPE_SYMBOLS')
    expect(apiSrc).toContain("sym: 'BTC-USD'")
    expect(apiSrc).toContain("CRYPTO_COT_ID = 'BTC'")
    expect(view).toContain('api.quotes(CRYPTO_TAPE_SYMBOLS)')
    expect(view).toContain('api.kalmanTrend(')
    expect(view).toContain('api.cot(')
    expect(view).toContain("from '@/cryptoRead'")
    expect(view).toContain('cryptoSpotRead(')
  })

  it('includes hyphenated coin marks and labels equity vehicles as equity', () => {
    expect(apiSrc).toMatch(/sym:\s*'BTC-USD'/)
    expect(apiSrc).toMatch(/sym:\s*'ETH-USD'/)
    expect(apiSrc).toContain("vehicle: 'spot'")
    expect(apiSrc).toContain("vehicle: 'equity'")
    expect(apiSrc).toContain("sym: 'IBIT'")
    expect(apiSrc).toContain("sym: 'MSTR'")
    expect(view).toContain('Equity vehicle')
    expect(view).toContain("r.vehicle === 'equity'")
  })

  it('renders missing/stale/unmeasured copy and uses 24/7 session language', () => {
    expect(view).toContain('UNMEASURED')
    expect(view).toContain('STALE')
    expect(view).toContain('unmeasured')
    expect(view).toContain('missing')
    expect(view).toContain('24/7')
    expect(view).toContain('Session 24/7')
    expect(view).not.toContain('RTH OPEN')
    expect(view).not.toContain('PREMARKET')
    expect(view).not.toContain('after-hours')
  })

  it('does not present GEX, flow tape, funding, or on-chain as measured evidence', () => {
    expect(view).not.toMatch(/\bGEX\b/)
    expect(view).not.toMatch(/flow-tape/i)
    expect(view).not.toMatch(/funding rate/i)
    expect(view).not.toMatch(/on-chain/i)
    expect(view).not.toMatch(/\bLSE\b/)
    expect(view).toContain('DECISION SUPPORT ONLY')
  })

  it('uses title-case section labels and inset 44px controls', () => {
    expect(view).toContain('label="Coin Tape"')
    expect(view).toContain('label="Focus Coin Kalman"')
    expect(view).toContain('label="Bitcoin Futures Spec Lean"')
    expect(view).toContain('min-height: 44px')
    expect(view).not.toContain('glass')
  })
})
