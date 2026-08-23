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
const evidenceVisual = readFileSync(join(root, 'components', 'EvidenceLayerVisual.vue'), 'utf8')
const liveVisual = readFileSync(join(root, 'components', 'LiveStateVisual.vue'), 'utf8')
const researchVisual = readFileSync(join(root, 'components', 'ResearchLoopVisual.vue'), 'utf8')

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
    expect(liveVisual).toContain('No illustrative values')
  })

  it('does not introduce pricing before the product needs it', () => {
    expect(src.toLowerCase()).not.toContain('pricing')
    expect(src).not.toMatch(/\$\d+\s*\/\s*mo/)
  })

  it('reads measured state from the local API', () => {
    expect(src).toContain('api.marketClock')
    expect(src).toMatch(/inject<Resource<StatusPayload>>\('status'\)/)
    expect(src).toMatch(/inject<Resource<Readiness>>\('readiness'\)/)
    expect(liveVisual).toContain('Local API unavailable')
    expect(liveVisual).toContain('bash edge/tools/run_dashboard.sh')
  })

  it('routes entry calls to the operator access flow', () => {
    expect(src).toContain("name: 'auth'")
    expect(src).toContain("redirect: '/flow'")
    expect(src).toContain('Sign in')
    expect(src).toContain('GexFlowVisual')
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
    for (const token of ['var(--void)', 'var(--phosphor)', 'var(--call)', 'var(--warn)']) {
      expect(src).toContain(token)
    }
    expect(src).toContain('@media (prefers-reduced-motion: reduce)')
  })

  it('foregrounds market flow instead of local-first marketing language', () => {
    expect(src).toContain('GexFlowVisual')
    expect(src).toContain('Explore market flow')
    expect(src.toLowerCase()).not.toContain('local-first')
  })

  it('uses custom evidence diagrams and the shared professional symbol system', () => {
    expect(src).toContain('EvidenceLayerVisual')
    expect(evidenceVisual).toContain('<svg')
    expect(evidenceVisual).toContain('AppIcon')
    expect(evidenceVisual).toContain("'market' | 'options' | 'governance'")
    expect(evidenceVisual).not.toMatch(/[🚀📈💡🔒]/u)
  })

  it('uses authored live-state and workspace compositions instead of dashboard boxes', () => {
    expect(src).toContain('LiveStateVisual')
    expect(src).toContain('ResearchLoopVisual')
    expect(liveVisual).toContain('state-aperture')
    expect(liveVisual).toContain('aperture-orbits')
    expect(researchVisual).toContain('research-map')
    expect(researchVisual).toContain('path-main')
    expect(src).not.toContain('workspace-board')
    expect(src).not.toContain('instrument-card')
  })
})

describe('landing route keeps three.js off its critical path', () => {
  it('loads VolSurfaceCanvas asynchronously rather than importing it statically', () => {
    // VolSurfaceCanvas statically imports three. A plain
    // `import VolSurfaceCanvas from '...'` here makes the 514 kB (128 kB gzip)
    // vendor-three chunk a hard dependency of `/` -- the public landing page --
    // for a decorative figure below the fold. The operator desk already treats
    // three this way; see ProbabilityDensityChart.vue.
    expect(src).not.toMatch(/^\s*import\s+VolSurfaceCanvas\s+from/m)
    expect(src).toMatch(/defineAsyncComponent\(\s*\(\)\s*=>\s*import\('@\/components\/VolSurfaceCanvas\.vue'\)/)
  })

  it('does not import three directly', () => {
    expect(src).not.toMatch(/from\s+'three'/)
  })
})
