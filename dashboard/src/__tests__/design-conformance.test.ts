/**
 * Design-conformance guard test — the enforcement backbone of the
 * TradeCentral instrument design system.
 *
 * Source of truth: dashboard/src/styles/tokens.css + dashboard/src/styles/base.css
 * + docs/DESIGN.md + dashboard/ui-registry.md
 *
 * This suite statically scans desk component source and enforces three rules:
 *   1. no hardcoded hex/rgb/rgba/hsl palette colors,
 *   2. no undefined CSS custom properties (every var(--x) resolves to a token
 *      defined in tokens.css or a local --x: definition in the same file,
 *      or carries its own fallback value),
 *   3. no forbidden effects (box-shadow: 0 0 glow, text-shadow,
 *      filter: brightness(), radial-gradient, decorative linear-gradient).
 *
 * Progressive enforcement (critical): the mission fixes components
 * incrementally. To keep the suite green at every milestone, an EXEMPT list
 * holds files that are not yet conformant. Each subsequent feature removes the
 * files it fixes from EXEMPT; the final audit empties it entirely. The list
 * only ever shrinks — never add a file to EXEMPT to make a test pass without
 * fixing it.
 *
 * Paper surfaces (LandingView, AuthView, the marketing *Visual components) are
 * a separate design system and are NOT scanned here.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join, relative, sep } from 'node:path'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const root = join(srcRoot, '..')

// ---------------------------------------------------------------------------
// File discovery — desk .vue/.ts source, excluding the paper system and tests.
// ---------------------------------------------------------------------------

/** Paper surfaces keep their own offset-print system; never scanned here. */
const PAPER_FILES = new Set<string>([
  'src/views/LandingView.vue',
  'src/views/AuthView.vue',
  'src/components/LiveStateVisual.vue',
  'src/components/GexFlowVisual.vue',
  'src/components/ResearchLoopVisual.vue',
  'src/components/OperatorAccessVisual.vue',
  'src/components/EvidenceLayerVisual.vue',
  'src/components/FlowWorkspaceMockup.vue',
  'src/components/ProductMockup.vue',
])

/** tokens.css IS allowed to define hex/rgb/rgba/hsl literals — it is the palette. */
const TOKENS_FILE = 'src/styles/tokens.css'
/** base.css is the shared-class source of truth and is also enforced. */
const BASE_FILE = 'src/styles/base.css'

/** Files not yet conformant at this milestone. Each later feature removes its
 *  files from this set once they are fixed. The list only ever shrinks. */
const EXEMPT = new Set<string>([
  // tokens.css / base.css are owned by THIS feature and are enforced below.
  // Each entry below is genuinely non-conformant at the baseline — verified
  // with DESIGN_CONFORMANCE_DIAGNOSE=1. Conformant desk files are enforced.
  // A later feature removes its files from here once they are fixed.
  'src/views/MarketView.vue',
  'src/views/DeskView.vue',
  'src/views/ChainView.vue',
  'src/views/SectorsView.vue',
  'src/views/ChangepointsView.vue',
  'src/components/ValueChainGraph.vue',
  'src/components/OptionsConvictionBoard.vue',
  'src/components/SqueezeScreener.vue',
  'src/components/RiskNeutral3DModel.vue',
  'src/components/Panel.vue',
  'src/components/SearchPalette.vue',
  'src/components/FlowSuggestionDrawer.vue',
  'src/App.vue',
  'src/main.ts',
])

function listSourceFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      if (entry === '__tests__' || entry === 'tests') continue
      listSourceFiles(full, acc)
    } else if (/\.(vue|ts)$/.test(entry)) {
      acc.push(full)
    }
  }
  return acc
}

function toRel(abs: string): string {
  return relative(root, abs).split(sep).join('/')
}

/** Desk .vue/.ts files scanned by the guard, minus paper surfaces and tests. */
function deskFiles(): string[] {
  return listSourceFiles(srcRoot)
    .map(toRel)
    .filter((rel) => !PAPER_FILES.has(rel))
    .filter((rel) => !rel.includes('__tests__'))
    .filter((rel) => rel !== TOKENS_FILE) // tokens.css is the palette — only rule 2 applies
}

function read(rel: string): string {
  const path = join(root, rel)
  if (!existsSync(path)) throw new Error(`design-conformance: missing file ${rel}`)
  return readFileSync(path, 'utf8')
}

// ---------------------------------------------------------------------------
// Balanced-parenthesis helper (gradients / var() can nest)
// ---------------------------------------------------------------------------

/** Returns the index just past the matching ')' for the '(' at openIdx. */
function matchParen(src: string, openIdx: number): number {
  let depth = 0
  for (let i = openIdx; i < src.length; i++) {
    if (src[i] === '(') depth++
    else if (src[i] === ')') {
      depth--
      if (depth === 0) return i + 1
    }
  }
  return src.length
}

// ---------------------------------------------------------------------------
// Rule 1 — no hardcoded palette colors (hex / rgb / rgba / hsl / hsla)
// ---------------------------------------------------------------------------

/**
 * Matches color literals we forbid in desk source.
 *  - #rgb / #rgba / #rrggbb / #rrggbbaa
 *  - rgb(...) / rgba(...) / hsl(...) / hsla(...)
 */
const COLOR_LITERAL =
  /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b|rgba?\(|hsla?\(/g

/**
 * Structural ink exceptions. The instrument aesthetic uses pure-black
 * elevation shadows and pure-white substrate tints as structural elements
 * (see ui-registry.md: "Shadow: none, or 0 1px 0 rgba(0,0,0,0.18) shelf").
 * These do NOT encode a palette color — they are the neutral substrate of the
 * dark theme. Only semantic palette colors (phosphor, call, put, long, short,
 * warn, ink, etc.) are forbidden as hardcoded literals.
 */
const STRUCTURAL_BLACK = /rgba?\(\s*0\s*,\s*0\s*,\s*0\s*(?:,\s*[\d.]+\s*)?\)/
const STRUCTURAL_WHITE = /rgba?\(\s*255\s*,\s*255\s*,\s*255\s*(?:,\s*[\d.]+\s*)?\)/

function isStructuralInk(literal: string): boolean {
  return STRUCTURAL_BLACK.test(literal) || STRUCTURAL_WHITE.test(literal)
}

/** Legitimate non-color uses of the hex token inside TS/template logic. */
function isHexFalsePositive(src: string, index: number): boolean {
  // `index` points at the '#' of a hex literal. We inspect the text preceding
  // it to detect SVG paint-server / element-id references where '#' introduces
  // an id (e.g. `url(#abc123)`), not a color. The slice must be wide enough to
  // reach back past `xlink:href="` (12 chars); 16 is a safe window.
  const before = src.slice(Math.max(0, index - 16), index)
  // url(#id) / :url(#id) / `url(#id`  — CSS/SVG paint-server reference.
  // href="#id" / xlink:href="#id"     — SVG element-id reference (href=" also
  //                                    matches the tail of xlink:href=").
  // The patterns match the prefix that precedes '#' (the '#' itself is at
  // `index`, not in `before`), so a purely-hex id like `#fff` is correctly
  // skipped instead of being flagged as a hardcoded color.
  if (/(?:`|:)url\(\s*|url\(\s*|href="/.test(before)) return true
  return false
}

function findHardcodedColors(src: string): string[] {
  const hits: string[] = []
  for (const m of src.matchAll(COLOR_LITERAL)) {
    const literal = m[0]
    const idx = m.index ?? 0
    if (literal.startsWith('#')) {
      if (isHexFalsePositive(src, idx)) continue
    } else {
      // rgb/rgba/hsl/hsla — extract the full balanced expression (including
      // the function prefix) and check whether it's structural ink
      // (black/white) which is allowed.
      const full = literal.endsWith('(')
        ? src.slice(idx, matchParen(src, idx + literal.length - 1))
        : literal
      if (isStructuralInk(full)) continue
    }
    const start = src.lastIndexOf('\n', idx - 1) + 1
    const end = src.indexOf('\n', idx)
    hits.push(src.slice(start, end === -1 ? undefined : end).trim())
  }
  return hits
}

// ---------------------------------------------------------------------------
// Rule 2 — no undefined CSS custom properties
// ---------------------------------------------------------------------------

/** Names defined as tokens in tokens.css (:root block). */
function collectDefinedTokens(tokensSrc: string): Set<string> {
  const names = new Set<string>()
  for (const m of tokensSrc.matchAll(/^\s*(--[\w-]+)\s*:/gm)) names.add(m[1])
  return names
}

/** Names defined as local custom properties anywhere in a single file.
 *  Covers both CSS declarations (`--x:`) and Vue inline-style bindings
 *  (`:style="{ '--x': value }"` / `:style="{ \"--x\": value }"`). */
function collectLocalProperties(src: string): Set<string> {
  const names = new Set<string>()
  for (const m of src.matchAll(/(--[\w-]+)\s*:/g)) names.add(m[1])
  // Vue inline-style object keys: '--x' / "--x" / `--x` followed by :.
  for (const m of src.matchAll(/['"`](--[\w-]+)['"`]\s*:/g)) names.add(m[1])
  return names
}

/** CSS-wide keywords that may appear as fallback values, not color names. */
const CSS_WIDE = new Set(['inherit', 'initial', 'unset', 'revert', 'currentColor'])

/**
 * Finds var(--x) references that don't resolve to a defined token, a local
 * property, or carry their own fallback. A var() with a fallback
 * (var(--x, <value>)) is valid CSS even if --x is undefined, so it is skipped.
 * Dynamic template-literal references (var(--cat-${expr}) / var(--${hue}))
 * are skipped — the token name is computed at runtime and cannot be resolved
 * statically.
 */
function findUndefinedTokens(src: string, defined: Set<string>): string[] {
  const local = collectLocalProperties(src)
  const seen = new Set<string>()
  const bad: string[] = []
  const varRe = /var\(\s*(--[\w-]*)/g
  for (const m of src.matchAll(varRe)) {
    const name = m[1]
    const matchStart = m.index ?? 0
    // Skip dynamic template-literal interpolations: the match is immediately
    // followed by ${ (inside a `var(--cat-${...})` or `var(--${...})`) OR the
    // captured name is empty (var(--${...}) captures an empty --).
    const afterMatch = src.slice(matchStart + m[0].length, matchStart + m[0].length + 2)
    if (afterMatch === '${' || name === '' || name.endsWith('-')) continue
    const afterName = matchStart + m[0].length
    // Check whether this var() has a fallback: a comma before the matching ).
    const closeIdx = matchParen(src, matchStart + m[0].indexOf('('))
    const inside = src.slice(afterName, closeIdx - 1)
    const hasFallback = inside.includes(',')
    if (hasFallback) continue // var(--x, fallback) is valid CSS
    if (seen.has(name)) continue
    seen.add(name)
    if (defined.has(name) || local.has(name)) continue
    if (CSS_WIDE.has(name)) continue
    bad.push(name)
  }
  return bad
}

// ---------------------------------------------------------------------------
// Rule 3 — no forbidden effects
//   box-shadow: 0 0 (glow) | text-shadow | filter: brightness() |
//   radial-gradient | decorative linear-gradient
// ---------------------------------------------------------------------------

/**
 * box-shadow glow: a shadow whose x AND y offsets are both 0 with a NONZERO
 * blur radius (the halo), e.g. `box-shadow: 0 0 8px …`.
 *
 * This regex ALSO flags ring shadows such as `box-shadow: 0 0 0 1px …`
 * (blur=0, a crisp outline ring). The `0 0 [1-9]` pattern matches the second
 * `0`, the third `0`, and the spread/next token, so a ring with a nonzero
 * spread value is caught. Ring shadows are non-canonical desk chrome
 * (ui-registry.md allows only: none, `0 1px 0 rgba(0,0,0,…)` shelf, or an
 * inset selection bar) and ARE flagged here — they should be converted to
 * `outline: var(--hair) solid var(--rule-hi)` or a `border`, not expressed
 * as a `box-shadow: 0 0 0 Npx` ring.
 */
const BOX_SHADOW_GLOW = /box-shadow\s*:[^;}]*(?<![0-9p])\b0\s+0\s+[1-9]/g
const TEXT_SHADOW = /text-shadow\s*:/g
const FILTER_BRIGHTNESS = /filter\s*:[^;}]*brightness\s*\(/g
const RADIAL_GRADIENT = /radial-gradient\s*\(/g

/**
 * Structural/substrate tokens that may legitimately appear in a linear-gradient
 * (the measurement-grid hairline and 1px rules). Any gradient touching a
 * semantic palette token (--phosphor, --call, --put, --long, --short, --warn,
 * --ink, --badge-*, etc.) or a hardcoded color is decorative and forbidden.
 */
const STRUCTURAL_TOKENS = new Set([
  '--grid',
  '--hair',
  '--void',
  '--void-lift',
  '--panel',
  '--panel-hi',
  '--panel-raise',
  '--rule',
  '--rule-hi',
  '--rule-faint',
])

/**
 * Decorative linear-gradient detection. A linear-gradient is allowed only when
 * every color stop is a structural/substrate token or `transparent`/
 * `currentColor` — i.e. the measurement-grid hairline or a 1px rule. Any
 * gradient mixing in a semantic palette token or a hardcoded color is
 * decorative and forbidden.
 */
function findDecorativeLinearGradients(src: string): string[] {
  const hits: string[] = []
  const gradRe = /linear-gradient\s*\(/g
  for (const m of src.matchAll(gradRe)) {
    const openIdx = (m.index ?? 0) + m[0].length - 1
    const end = matchParen(src, openIdx)
    const body = src.slice(openIdx + 1, end - 1)
    // Extract all var(--x) references and color literals in the gradient body.
    const vars = [...body.matchAll(/var\(\s*(--[\w-]+)/g)].map((x) => x[1])
    const hasColorLiteral =
      /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/.test(body) &&
      !isHexFalsePositive(body, body.search(/#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/))
    const hasRgbLiteral = /rgba?\(\s*\d/.test(body) && !isStructuralInk(body.match(/rgba?\([^)]*\)/)?.[0] ?? '')
    const hasHslLiteral = /hsla?\(\s*\d/.test(body)
    const hasSemanticToken = vars.some((v) => !STRUCTURAL_TOKENS.has(v))
    if (hasColorLiteral || hasRgbLiteral || hasHslLiteral || hasSemanticToken) {
      const lineStart = src.lastIndexOf('\n', (m.index ?? 0) - 1) + 1
      const lineEnd = src.indexOf('\n', m.index ?? 0)
      hits.push(src.slice(lineStart, lineEnd === -1 ? undefined : lineEnd).trim())
    }
  }
  return hits
}

function findForbiddenEffects(src: string): string[] {
  const hits: string[] = []
  const push = (re: RegExp, label: string) => {
    for (const m of src.matchAll(re)) {
      const start = src.lastIndexOf('\n', (m.index ?? 0) - 1) + 1
      const end = src.indexOf('\n', m.index ?? 0)
      hits.push(`${label}: ${src.slice(start, end === -1 ? undefined : end).trim()}`)
    }
  }
  push(BOX_SHADOW_GLOW, 'box-shadow glow')
  push(TEXT_SHADOW, 'text-shadow')
  push(FILTER_BRIGHTNESS, 'filter brightness')
  push(RADIAL_GRADIENT, 'radial-gradient')
  for (const line of findDecorativeLinearGradients(src)) hits.push(`decorative linear-gradient: ${line}`)
  return hits
}

// ---------------------------------------------------------------------------
// Diagnostic mode — set DESIGN_CONFORMANCE_DIAGNOSE=1 to print every file that
// would fail each rule. Lets a worker rebuild the EXEMPT list after a fix
// without hand-maintaining it.
// ---------------------------------------------------------------------------

const DIAGNOSE = process.env.DESIGN_CONFORMANCE_DIAGNOSE === '1'
const tokensSource = read(TOKENS_FILE)
const definedTokens = collectDefinedTokens(tokensSource)

function enforcedFiles(): string[] {
  return deskFiles().filter((rel) => !EXEMPT.has(rel))
}

if (DIAGNOSE) {
  console.log('\n[design-conformance] DIAGNOSE mode — non-conformant enforced files:')
  const bad = new Map<string, string[]>()
  for (const rel of enforcedFiles()) {
    const src = read(rel)
    const v: string[] = []
    const colors = findHardcodedColors(src)
    if (colors.length) v.push(`colors(${colors.length}): ${colors.slice(0, 3).join(' | ')}`)
    const undef = findUndefinedTokens(src, definedTokens)
    if (undef.length) v.push(`undefined-tokens: ${undef.join(', ')}`)
    const fx = findForbiddenEffects(src)
    if (fx.length) v.push(`effects(${fx.length}): ${fx.slice(0, 3).join(' | ')}`)
    if (v.length) bad.set(rel, v)
  }
  if (bad.size === 0) console.log('  (none — every enforced file is conformant)')
  for (const [rel, v] of bad) console.log(`  ${rel}\n      ${v.join('\n      ')}`)
  console.log('')
}

// ---------------------------------------------------------------------------
// Suites
// ---------------------------------------------------------------------------

describe('design-conformance guard — design source of truth', () => {
  it('tokens.css defines the three previously-missing design tokens', () => {
    const css = read(TOKENS_FILE)
    expect(css, 'tokens.css must define --call-dim').toMatch(/--call-dim\s*:\s*#[0-9a-fA-F]{3,8}\s*;/)
    expect(css, 'tokens.css must define --put-dim').toMatch(/--put-dim\s*:\s*#[0-9a-fA-F]{3,8}\s*;/)
    expect(css, 'tokens.css must define --panel-wash').toMatch(/--panel-wash\s*:\s*rgba?\(/)
  })

  it('tokens.css --call-dim / --put-dim are dimmed variants of --call / --put', () => {
    const css = read(TOKENS_FILE)
    const get = (name: string): string => {
      const m = css.match(new RegExp(`${name}\\s*:\\s*(#[0-9a-fA-F]{3,8})\\s*;`))
      return m ? m[1].toLowerCase() : ''
    }
    const call = get('--call')
    const callHi = get('--call-hi')
    const callDim = get('--call-dim')
    const put = get('--put')
    const putHi = get('--put-hi')
    const putDim = get('--put-dim')
    expect(call).toBeTruthy()
    expect(put).toBeTruthy()
    // A dimmed variant is strictly darker than the base token (and never the
    // brighter -hi variant).
    const lum = (hex: string): number => {
      const h = hex.replace('#', '')
      const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16)
      const r = (n >> 16) & 255
      const g = (n >> 8) & 255
      const b = n & 255
      return 0.2126 * r + 0.7152 * g + 0.0722 * b
    }
    expect(lum(callDim), '--call-dim should be darker than --call').toBeLessThan(lum(call))
    expect(lum(callDim), '--call-dim should not be the brighter --call-hi').toBeLessThan(lum(callHi))
    expect(lum(putDim), '--put-dim should be darker than --put').toBeLessThan(lum(put))
    expect(lum(putDim), '--put-dim should not be the brighter --put-hi').toBeLessThan(lum(putHi))
  })

  it('tokens.css --panel-wash is a translucent panel overlay', () => {
    const css = read(TOKENS_FILE)
    const m = css.match(/--panel-wash\s*:\s*rgba?\(([^)]+)\)\s*;/)
    expect(m, '--panel-wash must be an rgba() value').toBeTruthy()
    const parts = m![1].split(',').map((s) => s.trim())
    // rgba → 4 parts, alpha < 1 (translucent, not opaque).
    expect(parts.length).toBe(4)
    const alpha = parseFloat(parts[3])
    expect(alpha).toBeGreaterThan(0)
    expect(alpha).toBeLessThan(1)
  })

  it('tokens.css references only defined tokens in its var() aliases', () => {
    const bad = findUndefinedTokens(tokensSource, definedTokens)
    expect(bad, `tokens.css references undefined tokens: ${bad.join(', ')}`).toEqual([])
  })
})

describe('design-conformance guard — base.css is conformant', () => {
  const baseSrc = read(BASE_FILE)

  it('base.css has no hardcoded palette colors (structural ink excepted)', () => {
    const hits = findHardcodedColors(baseSrc)
    expect(hits, `base.css hardcoded colors:\n${hits.join('\n')}`).toEqual([])
  })

  it('base.css references only defined tokens (or vars with fallbacks)', () => {
    const bad = findUndefinedTokens(baseSrc, definedTokens)
    expect(bad, `base.css undefined tokens: ${bad.join(', ')}`).toEqual([])
  })

  it('base.css has no forbidden effects', () => {
    const hits = findForbiddenEffects(baseSrc)
    expect(hits, `base.css forbidden effects:\n${hits.join('\n')}`).toEqual([])
  })
})

describe('design-conformance guard — enforced desk components', () => {
  const files = enforcedFiles()

  if (files.length === 0) {
    it('at least one desk file is enforced', () => {
      expect.fail('no desk files are enforced — EXEMPT list swallowed the whole desk')
    })
  }

  for (const rel of files) {
    const src = read(rel)

    it(`${rel} has no hardcoded colors`, () => {
      const hits = findHardcodedColors(src)
      expect(hits, `${rel} hardcoded colors:\n${hits.join('\n')}`).toEqual([])
    })

    it(`${rel} references only defined tokens`, () => {
      const bad = findUndefinedTokens(src, definedTokens)
      expect(bad, `${rel} undefined tokens: ${bad.join(', ')}`).toEqual([])
    })

    it(`${rel} has no forbidden effects`, () => {
      const hits = findForbiddenEffects(src)
      expect(hits, `${rel} forbidden effects:\n${hits.join('\n')}`).toEqual([])
    })
  }
})

describe('design-conformance guard — EXEMPT list integrity', () => {
  it('EXEMPT files are real desk files (no paper surfaces, no phantoms)', () => {
    const desk = new Set(deskFiles())
    const tokensAndBase = new Set([TOKENS_FILE, BASE_FILE])
    for (const rel of EXEMPT) {
      expect(
        desk.has(rel) || tokensAndBase.has(rel),
        `EXEMPT entry "${rel}" is not a desk .vue/.ts file under src/`,
      ).toBe(true)
      expect(
        !PAPER_FILES.has(rel),
        `EXEMPT entry "${rel}" is a paper surface and must never be in EXEMPT`,
      ).toBe(true)
    }
  })

  it('tokens.css and base.css are enforced (never EXEMPT)', () => {
    expect(EXEMPT.has(TOKENS_FILE), 'tokens.css must never be EXEMPT').toBe(false)
    expect(EXEMPT.has(BASE_FILE), 'base.css must never be EXEMPT').toBe(false)
  })
})
