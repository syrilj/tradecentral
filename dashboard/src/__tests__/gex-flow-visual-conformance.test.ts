/**
 * GexFlowVisual — paper-surface conformance for assertion VAL-DS-004.
 *
 * GexFlowVisual.vue is a marketing/paper surface, so it is intentionally
 * excluded from the desk design-conformance guard (`PAPER_FILES`). The desk
 * guard's three rules (no hardcoded colors, no undefined tokens, no forbidden
 * effects) do not apply to the paper system.
 *
 * VAL-DS-004 carves out three rules that DO apply to this file specifically,
 * because they are universal design-system defects, not desk-only styling:
 *   1. No self-referential CSS custom property (e.g. `--ink: var(--ink)`).
 *   2. No continuous ambient animation (no `animation: ... infinite`).
 *   3. The "live" accent (`--phosphor`) is not used as decorative chrome —
 *      the trace line, flow-tag markers, card accent, and net-positioning
 *      legend must not borrow the live/selected accent for decoration.
 *
 * The paper-system palette itself is preserved (no conversion to desk tokens).
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = readFileSync(join(root, 'components', 'GexFlowVisual.vue'), 'utf8')

/**
 * Matches a self-referential custom-property declaration: `--x: var(--x)`,
 * optionally with inner whitespace. Captures the property name so each hit can
 * be reported precisely. A `--x: var(--x, fallback)` carries a fallback and is
 * valid CSS, so it is excluded by requiring the var() to close immediately.
 */
const SELF_REFERENTIAL = /(--[\w-]+)\s*:\s*var\(\s*(--[\w-]+)\s*\)\s*[;}\n]/g

function findSelfReferentialVars(css: string): string[] {
  const hits: string[] = []
  for (const m of css.matchAll(SELF_REFERENTIAL)) {
    if (m[1] === m[2]) hits.push(`${m[1]}: var(${m[2]})`)
  }
  return hits
}

/**
 * Matches a continuous ambient animation: any `animation:` shorthand that
 * includes the `infinite` iteration count. This is the "gex-trace" ambient
 * trace animation the design system forbids. Short, finite transitions are
 * allowed; only the unbounded ambient loop is rejected.
 */
const INFINITE_ANIMATION = /animation\s*:[^;}]*\binfinite\b/g

describe('GexFlowVisual — VAL-DS-004 paper-surface conformance', () => {
  it('has no self-referential CSS custom property', () => {
    const hits = findSelfReferentialVars(src)
    expect(
      hits,
      `GexFlowVisual.vue has self-referential custom properties:\n${hits.join('\n')}`,
    ).toEqual([])
  })

  it('has no continuous ambient (infinite) animation', () => {
    const hits = [...src.matchAll(INFINITE_ANIMATION)].map((m) => m[0].trim())
    expect(
      hits,
      `GexFlowVisual.vue has continuous ambient animations:\n${hits.join('\n')}`,
    ).toEqual([])
  })

  it('does not use the --phosphor "live" accent as decorative chrome', () => {
    // The "live" accent is reserved for live/selected state only. On this
    // illustrative anatomy figure nothing is live, so --phosphor must not
    // appear at all — neither directly nor via an alias that forwards to it.
    const direct = [...src.matchAll(/var\(\s*--phosphor\b/g)]
    const aliasToPhosphor = [...src.matchAll(/--[\w-]+\s*:\s*var\(\s*--phosphor\b/g)]
    const all = [...direct, ...aliasToPhosphor]
    expect(
      all.length,
      `GexFlowVisual.vue uses --phosphor as decorative chrome (${all.length} occurrence(s))`,
    ).toBe(0)
  })

  it('preserves the paper-system palette (no conversion to desk structural tokens)', () => {
    // The paper visual keeps its existing desk-palette ink/rule/call/put
    // vocabulary. VAL-DS-004 fixes defects, not a token migration — so the
    // palette anchors must still be present.
    expect(src).toContain('--paper: var(--ink)')
    expect(src).toContain('--blue: var(--call)')
    expect(src).toContain('--orange: var(--put)')
  })

  it('no longer defines the removed --green phosphor alias or gex-trace keyframes', () => {
    // Regression guards: the removed decorative alias and the removed ambient
    // keyframes must not be reintroduced.
    expect(src).not.toContain('--green:')
    expect(src).not.toContain('@keyframes gex-trace')
    expect(src).not.toContain('gex-trace')
  })
})
