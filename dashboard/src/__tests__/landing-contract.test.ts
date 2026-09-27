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
const appSource = readFileSync(join(root, 'App.vue'), 'utf8')
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
  })

  it('reads measured state through shell resources without polling the API from a public route', () => {
    expect(src).not.toContain('api.marketClock')
    expect(src).toMatch(/inject<Resource<StatusPayload>>\('status'\)/)
    expect(src).toMatch(/inject<Resource<Readiness>>\('readiness'\)/)
    expect(src).toMatch(/inject<Resource<MarketClock>>\('marketClock'\)/)
    expect(appSource).toContain('api.marketClock()')
    expect(appSource).toContain("provide('marketClock', marketClock)")
  })

  it('routes entry calls to the operator access flow', () => {
    expect(src).toContain("name: 'auth'")
    expect(src).toContain("redirect: '/flow'")
    expect(src).toContain('Sign in')
    expect(src).toContain('Request operator access')
    expect(src).not.toContain('>Create access<')
    expect(src).toContain('GexFlowVisual')
  })

  it('keeps the public page focused instead of exposing an internal section index', () => {
    expect(src).not.toContain('ticker-tape')
    expect(src).not.toContain('href="#workstation"')
    expect(src).not.toContain('href="#regimes"')
  })

  it('uses the product mark and shared icon vocabulary', () => {
    expect(src).toContain('TradeCentralMark')
    expect(src).toContain('AppIcon')
    expect(preview).toContain('TradeCentralMark')
    expect(preview).not.toContain('<span class="mock-mark">E</span>')
    expect(src).not.toMatch(/[🚀📈💡🔒]/u)
  })

  it('keeps the research-only and no-execution boundary visible', () => {
    expect(src).toContain('Source-visible.')
    expect(src).toContain('No order routing')
    expect(src).toContain('No investment advice')
  })

  it('keeps the launch path direct and avoids a free demo promise', () => {
    expect(src).toContain('Join now')
    expect(src).toContain('Join the access list')
    expect(src).toContain('Pro workspaces')
    expect(src).not.toContain('runs without an account')
    expect(src).not.toContain('Try the model lab')
  })

  it('keeps the public page focused on one access decision', () => {
    expect(src).toContain('id="access"')
    expect(src).toContain('Operator access')
    expect(src).toContain('No payment details collected')
    expect(src).not.toContain('See the work behind every readout')
    expect(src).not.toContain('Read the options surface')
    expect(src).not.toContain('Built on hard boundaries')
  })

  it('uses the requested brand palette and respects reduced motion', () => {
    for (const token of ['var(--void)', 'var(--phosphor)', 'var(--call)', 'var(--warn)']) {
      expect(src).toContain(token)
    }
    expect(src).toContain('@media (prefers-reduced-motion: reduce)')
  })

  it('foregrounds market flow instead of local-first marketing language', () => {
    // Asserted by structure, not by one CTA string: the flow surface must be
    // a named section with its own anatomy visual, and the page's calls to
    // action must route a visitor into /flow. Pinning the exact button label
    // made ordinary copy edits look like contract breaks.
    expect(src).toContain('GexFlowVisual')
    expect(src).toMatch(/id="flow"/)
    expect(src).toMatch(/redirect:\s*'\/flow'/)
    expect(src).toMatch(/>\s*Flow\s*</)
    expect(src.toLowerCase()).not.toContain('local-first')
  })

  it('uses custom evidence diagrams and the shared professional symbol system', () => {
    expect(src).not.toContain('EvidenceLayerVisual')
  })

  it('uses authored product compositions instead of dashboard boxes', () => {
    expect(src).not.toContain('workspace-board')
    expect(src).not.toContain('instrument-card')
  })
})
