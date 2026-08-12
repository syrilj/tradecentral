/**
 * Landing page design-contract gate.
 *
 * The /about overview was rewritten after the UI review (docs/DASHBOARD-UI-REVIEW.md)
 * flagged campaign copy, promotional type sizes, decorative filters, and an
 * illustrative market board. This gate reads the shipped SFC and fails if any
 * of that drifts back in.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = readFileSync(join(root, 'views', 'LandingView.vue'), 'utf8')

/** Sign-up framing and promo claims that contradict the research-only posture. */
const FORBIDDEN_COPY = [
  'JOIN THE EDGE',
  'Join the Edge',
  'actionable insight',
  'INSTITUTIONAL-GRADE',
  'RETAIL ACCESS',
  'Sign up',
  'Get started',
  'Smart Money',
]

/** Fabricated quotes from the old illustrative board — the landing shows
 *  measured state from the local API or an explicit unavailable state. */
const FORBIDDEN_DATA = ['5,321.41', '456.32', '1,042.63', 'ILLUSTRATIVE', 'marketRows']

/** Decorative visual mechanisms the instrument brief prohibits. */
const FORBIDDEN_VISUALS = [
  'radial-gradient',
  'linear-gradient',
  'box-shadow',
  'text-shadow',
  'drop-shadow',
  'feTurbulence',
  'feGaussianBlur',
  'feDisplacementMap',
  'border-radius: 8',
  '@keyframes',
]

describe('Landing page honours the instrument contract', () => {
  it('carries no campaign or sign-up copy', () => {
    for (const bad of FORBIDDEN_COPY) {
      expect(src, `LandingView still contains forbidden copy: ${bad}`).not.toContain(bad)
    }
  })

  it('ships no fabricated or illustrative market data', () => {
    for (const bad of FORBIDDEN_DATA) {
      expect(src, `LandingView still contains fabricated data: ${bad}`).not.toContain(bad)
    }
  })

  it('avoids decorative gradients, glow, blur filters, and keyframe motion', () => {
    for (const bad of FORBIDDEN_VISUALS) {
      expect(src, `LandingView still contains forbidden visual: ${bad}`).not.toContain(bad)
    }
  })

  it('keeps font sizes on the approved token scale', () => {
    // Fully tokenized type is the goal — any raw px size that appears must
    // stay inside the 11–36px band the design contract approves.
    const decls = src.match(/font(?:-size)?\s*:[^;}]+/g) ?? []
    const px = decls.flatMap((d) => [...d.matchAll(/(\d+(?:\.\d+)?)px/g)].map((m) => Number(m[1])))
    if (px.length) {
      expect(Math.max(...px), 'font size above the 36px large-figure ceiling').toBeLessThanOrEqual(36)
      expect(Math.min(...px), 'font size below the 11px micro floor').toBeGreaterThanOrEqual(11)
    }
    expect(src, 'expected the landing page to use the --t-* type tokens').toContain('var(--t-')
  })

  it('reads measured state from the local API instead of hardcoding it', () => {
    expect(src).toContain('api.marketClock')
    expect(src).toMatch(/inject<Resource<StatusPayload>>\('status'\)/)
    expect(src).toMatch(/inject<Resource<Readiness>>\('readiness'\)/)
  })

  it('keeps the research-only boundary visible', () => {
    expect(src).toContain('Research only · No execution · No investment advice')
    expect(src).toContain('Not an execution terminal')
  })

  it('renders an explicit unavailable state when the local API is down', () => {
    expect(src).toContain('Local API unavailable')
    expect(src).toContain('bash edge/tools/run_dashboard.sh')
  })
})
