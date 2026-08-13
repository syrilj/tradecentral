/**
 * Landing-page product contract.
 *
 * The public page may be expressive, but it must stay faithful to the local
 * research instrument: live state comes from the API, product language names
 * real capabilities, and no invented market or performance figures appear.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = readFileSync(join(root, 'views', 'LandingView.vue'), 'utf8')
const preview = readFileSync(join(root, 'components', 'FlowWorkspaceMockup.vue'), 'utf8')

const FORBIDDEN_CLAIMS = [
  'actionable insight',
  'INSTITUTIONAL-GRADE',
  'RETAIL ACCESS',
  'Smart Money',
  'AI confidence',
  'guaranteed returns',
]

const FORBIDDEN_ILLUSTRATIVE_DATA = ['5,321.41', '456.32', '1,042.63', 'marketRows']

describe('Landing page honours the product boundary', () => {
  it('contains no invented promotional or performance claims', () => {
    for (const bad of FORBIDDEN_CLAIMS) expect(src).not.toContain(bad)
  })

  it('contains no fabricated market-board values', () => {
    for (const bad of FORBIDDEN_ILLUSTRATIVE_DATA) expect(src).not.toContain(bad)
    expect(src).toContain('No illustrative values')
  })

  it('does not introduce pricing before the product needs it', () => {
    expect(src.toLowerCase()).not.toContain('pricing')
    expect(src).not.toMatch(/\$\d+\s*\/\s*mo/)
  })

  it('reads measured state from the local API', () => {
    expect(src).toContain('api.marketClock')
    expect(src).toMatch(/inject<Resource<StatusPayload>>\('status'\)/)
    expect(src).toMatch(/inject<Resource<Readiness>>\('readiness'\)/)
    expect(src).toContain('Local API unavailable')
    expect(src).toContain('bash edge/tools/run_dashboard.sh')
  })

  it('routes entry calls to the operator access flow', () => {
    expect(src).toContain("name: 'auth'")
    expect(src).toContain("redirect: '/flow'")
    expect(src).toContain('Sign in')
    expect(src).toContain('FlowWorkspaceMockup')
  })

  it('uses the product mark and shared icon vocabulary', () => {
    expect(src).toContain('TradeCentralMark')
    expect(src).toContain('AppIcon')
    expect(preview).toContain('TradeCentralMark')
    expect(preview).not.toContain('<span class="mock-mark">E</span>')
    expect(src).not.toMatch(/[🚀📈💡🔒]/u)
  })

  it('keeps the research-only and no-execution boundary visible', () => {
    expect(src).toContain('Research only · No execution · No investment advice')
    expect(src).toContain('No order routing')
    expect(src).toContain('No broker connection')
  })

  it('uses the requested brand palette and respects reduced motion', () => {
    for (const color of ['#141413', '#faf9f5', '#d97757', '#6a9bcc', '#788c5d']) {
      expect(src.toLowerCase()).toContain(color)
    }
    expect(src).toContain('@media (prefers-reduced-motion: reduce)')
  })
})
