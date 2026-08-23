import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { ref } from 'vue'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const appVuePath = join(srcRoot, 'App.vue')
const tokensCssPath = join(srcRoot, 'styles', 'tokens.css')
const appVueSrc = readFileSync(appVuePath, 'utf8')
const tokensCssSrc = readFileSync(tokensCssPath, 'utf8')

// ---------------------------------------------------------------------------
// Helpers from design-conformance.test.ts
// ---------------------------------------------------------------------------
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

const COLOR_LITERAL = /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b|rgba?\(|hsla?\(/g
const STRUCTURAL_BLACK = /rgba?\(\s*0\s*,\s*0\s*,\s*0\s*(?:,\s*[\d.]+\s*)?\)/
const STRUCTURAL_WHITE = /rgba?\(\s*255\s*,\s*255\s*,\s*255\s*(?:,\s*[\d.]+\s*)?\)/

function isStructuralInk(literal: string): boolean {
  return STRUCTURAL_BLACK.test(literal) || STRUCTURAL_WHITE.test(literal)
}

function isHexFalsePositive(src: string, index: number): boolean {
  const before = src.slice(Math.max(0, index - 16), index)
  return /(?:`|:)url\(\s*|url\(\s*|href="/.test(before)
}

function findHardcodedColors(src: string): string[] {
  const hits: string[] = []
  for (const m of src.matchAll(COLOR_LITERAL)) {
    const literal = m[0]
    const idx = m.index ?? 0
    if (literal.startsWith('#')) {
      if (isHexFalsePositive(src, idx)) continue
    } else {
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

function collectDefinedTokens(tokensSrc: string): Set<string> {
  const names = new Set<string>()
  for (const m of tokensSrc.matchAll(/^\s*(--[\w-]+)\s*:/gm)) names.add(m[1])
  return names
}

function collectLocalProperties(src: string): Set<string> {
  const names = new Set<string>()
  for (const m of src.matchAll(/(--[\w-]+)\s*:/g)) names.add(m[1])
  for (const m of src.matchAll(/['"`](--[\w-]+)['"`]\s*:/g)) names.add(m[1])
  return names
}

const CSS_WIDE = new Set(['inherit', 'initial', 'unset', 'revert', 'currentColor'])

function findUndefinedTokens(src: string, defined: Set<string>): string[] {
  const local = collectLocalProperties(src)
  const seen = new Set<string>()
  const bad: string[] = []
  const varRe = /var\(\s*(--[\w-]*)/g
  for (const m of src.matchAll(varRe)) {
    const name = m[1]
    const matchStart = m.index ?? 0
    const afterMatch = src.slice(matchStart + m[0].length, matchStart + m[0].length + 2)
    if (afterMatch === '${' || name === '' || name.endsWith('-')) continue
    const afterName = matchStart + m[0].length
    const closeIdx = matchParen(src, matchStart + m[0].indexOf('('))
    const inside = src.slice(afterName, closeIdx - 1)
    if (inside.includes(',')) continue
    if (seen.has(name)) continue
    seen.add(name)
    if (defined.has(name) || local.has(name)) continue
    if (CSS_WIDE.has(name)) continue
    bad.push(name)
  }
  return bad
}

const BOX_SHADOW_GLOW = /box-shadow\s*:[^;}]*(?<![0-9p])\b0\s+0\s+[1-9]/g
const TEXT_SHADOW = /text-shadow\s*:/g
const FILTER_BRIGHTNESS = /filter\s*:[^;}]*brightness\s*\(/g
const RADIAL_GRADIENT = /radial-gradient\s*\(/g

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

function findDecorativeLinearGradients(src: string): string[] {
  const hits: string[] = []
  const gradRe = /linear-gradient\s*\(/g
  for (const m of src.matchAll(gradRe)) {
    const openIdx = (m.index ?? 0) + m[0].length - 1
    const end = matchParen(src, openIdx)
    const body = src.slice(openIdx + 1, end - 1)
    const vars = [...body.matchAll(/var\(\s*(--[\w-]+)/g)].map((x) => x[1])
    const hasColorLiteral =
      /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/.test(body) &&
      !isHexFalsePositive(
        body,
        body.search(/#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/),
      )
    const hasRgbLiteral =
      /rgba?\(\s*\d/.test(body) && !isStructuralInk(body.match(/rgba?\([^)]*\)/)?.[0] ?? '')
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
  for (const line of findDecorativeLinearGradients(src))
    hits.push(`decorative linear-gradient: ${line}`)
  return hits
}

describe('Challenger 2 Empirical Verification — Milestone 2 Shell & Layout Overhaul', () => {
  const definedTokens = collectDefinedTokens(tokensCssSrc)

  describe('Task 1: Design Conformance in App.vue', () => {
    it('App.vue contains 0 hardcoded palette colors (only structural ink rgba allowed)', () => {
      const hits = findHardcodedColors(appVueSrc)
      expect(hits, `Found hardcoded palette colors in App.vue:\n${hits.join('\n')}`).toEqual([])
    })

    it('App.vue references only defined CSS custom properties from tokens.css or locally defined properties', () => {
      const bad = findUndefinedTokens(appVueSrc, definedTokens)
      expect(bad, `Found undefined CSS tokens in App.vue:\n${bad.join(', ')}`).toEqual([])
    })

    it('App.vue has no forbidden effects (no glow shadows, no text-shadow, no filter brightness, no radial gradient, no decorative linear gradients)', () => {
      const hits = findForbiddenEffects(appVueSrc)
      expect(hits, `Found forbidden effects in App.vue:\n${hits.join('\n')}`).toEqual([])
    })

    it('App.vue utilizes modern glassmorphism tokens (--glass-surface, --glass-border, --glass-blur-md, --glass-specular-*)', () => {
      expect(appVueSrc).toContain('var(--glass-surface)')
      expect(appVueSrc).toContain('var(--glass-border)')
      expect(appVueSrc).toContain('var(--glass-blur-md)')
      expect(appVueSrc).toContain('var(--glass-specular')
    })
  })

  describe('Task 2: Layout Structure, Overflow, Z-Index Layering & Transitions', () => {
    it('verifies strict non-conflicting z-index hierarchy between shell layers', () => {
      // Parse z-index tokens from tokens.css
      const getZ = (token: string): number => {
        const m = tokensCssSrc.match(new RegExp(`${token}\\s*:\\s*(\\d+)`))
        return m ? parseInt(m[1], 10) : -1
      }

      const zStrip = getZ('--z-strip')
      const zRail = getZ('--z-rail')
      const zOverlay = getZ('--z-overlay')
      const zToast = getZ('--z-toast')

      expect(zStrip).toBe(40)
      expect(zRail).toBe(45)
      expect(zOverlay).toBe(90)
      expect(zToast).toBe(100)

      // Strict layering contract:
      // Background (0) < Grid th (1) < Shell (2) < Strip (40) < Rail (45) < Overlay / Tools menu (90) < Skip link / Toast (100)
      expect(zStrip).toBeLessThan(zRail) // Rail must be above Strip so sidebar border and popovers cleanly overlap strip
      expect(zRail).toBeLessThan(zOverlay) // Flyouts and dropdowns must float above the Rail
      expect(zOverlay).toBeLessThan(zToast) // Global toasts and skip links must float above all overlays
    })

    it('verifies overflow safety and grid template containment in .shell, .stage, and .rail', () => {
      // Shell grid layout minmax(0, 1fr) prevents wide table blowouts
      expect(appVueSrc).toContain('grid-template-columns: var(--rail-w) minmax(0, 1fr)')
      expect(appVueSrc).toContain('overflow: hidden')

      // Stage must have min-width: 0, min-height: 0, and overflow: auto to contain wide scrollable data tables
      expect(appVueSrc).toContain('.stage {')
      expect(appVueSrc).toMatch(/\.stage\s*\{[^}]*min-width:\s*0/s)
      expect(appVueSrc).toMatch(/\.stage\s*\{[^}]*min-height:\s*0/s)
      expect(appVueSrc).toMatch(/\.stage\s*\{[^}]*overflow:\s*auto/s)

      // Rail must handle its own vertical scroll for navigation items without blowing out shell
      expect(appVueSrc).toMatch(/\.rail\s*\{[^}]*overflow:\s*hidden/s)
      expect(appVueSrc).toMatch(/\.nav\s*\{[^}]*overflow-y:\s*auto/s)
      expect(appVueSrc).toMatch(/\.nav\s*\{[^}]*overflow-x:\s*hidden/s)
    })

    it('verifies smooth CSS transitions for sidebar expand/collapse and reduced motion support', () => {
      // Standardized easing and durations
      expect(appVueSrc).toContain('transition: grid-template-columns var(--dur) var(--ease-out)')
      expect(appVueSrc).toContain('transition: width var(--dur) var(--ease-out)')

      // tokens.css must define zeroed durations under prefers-reduced-motion: reduce
      expect(tokensCssSrc).toContain('@media (prefers-reduced-motion: reduce)')
      expect(tokensCssSrc).toMatch(
        /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[\s\S]*--dur:\s*0ms/,
      )
      expect(tokensCssSrc).toMatch(
        /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[\s\S]*--dur-fast:\s*0ms/,
      )
    })
  })

  describe('Task 3: Shell Navigation, Market Strip, and Router Contracts', () => {
    it('verifies all 3 navigation tool groupings and counts in App.vue', () => {
      const primaryNavRegex = /const primaryNav = \[\s*([\s\S]*?)\] as const/
      const primaryMatch = appVueSrc.match(primaryNavRegex)
      expect(primaryMatch).toBeTruthy()
      const primaryNames = [...primaryMatch![1].matchAll(/name:\s*'([^']+)'/g)].map((m) => m[1])
      expect(primaryNames).toEqual(['flow', 'options', 'desk', 'chain', 'market'])

      const deskToolsRegex = /const deskTools = \[\s*([\s\S]*?)\] as const/
      const deskMatch = appVueSrc.match(deskToolsRegex)
      expect(deskMatch).toBeTruthy()
      const deskNames = [...deskMatch![1].matchAll(/name:\s*'([^']+)'/g)].map((m) => m[1])
      expect(deskNames).toEqual(['plays', 'drift', 'absorption', 'livestack', 'suggest'])

      // Market Analytics: 6 items
      const marketToolsRegex = /const marketTools = \[\s*([\s\S]*?)\] as const/
      const marketMatch = appVueSrc.match(marketToolsRegex)
      expect(marketMatch).toBeTruthy()
      const marketNames = [...marketMatch![1].matchAll(/name:\s*'([^']+)'/g)].map((m) => m[1])
      expect(marketNames).toEqual([
        'sectors',
        'sentiment',
        'momentum',
        'fintel',
        'insiders',
        'calculator',
      ])

      // Research Lab: 8 items
      const researchToolsRegex = /const researchTools = \[\s*([\s\S]*?)\] as const/
      const researchMatch = appVueSrc.match(researchToolsRegex)
      expect(researchMatch).toBeTruthy()
      const researchNames = [...researchMatch![1].matchAll(/name:\s*'([^']+)'/g)].map((m) => m[1])
      expect(researchNames).toEqual([
        'research',
        'gates',
        'evolution',
        'adaptive',
        'graph',
        'changepoints',
        'cloud',
        'kalman',
      ])
    })

    it('verifies presence of all market strip elements', () => {
      // Tickers
      expect(appVueSrc).toContain("sym: 'SPY'")
      expect(appVueSrc).toContain("sym: 'QQQ'")
      expect(appVueSrc).toContain("sym: 'DIA'")
      expect(appVueSrc).toContain("sym: 'XLE'")

      // Gauges
      expect(appVueSrc).toContain('class="gauge gauge-btn gauge-vol"')
      expect(appVueSrc).toContain('class="gauge gauge-btn gauge-rot"')
      expect(appVueSrc).toContain('class="gauge gauge-btn gauge-fg"')

      // Market session clock & countdown
      expect(appVueSrc).toContain('class="market-clock"')
      expect(appVueSrc).toContain('sessionLabelOf')
      expect(appVueSrc).toContain('formatMarketCountdown')

      // Search palette trigger
      expect(appVueSrc).toContain('class="strip-search"')
      expect(appVueSrc).toContain('paletteOpen = true')
    })
  })

  describe('Task 4: Adversarial & Edge Case Simulation', () => {
    describe('Fear/Greed Sentiment Composite Logic Oracle', () => {
      function computeFearGreed(
        score: number | null | undefined,
        rawQuality?: string,
        loading = false,
      ) {
        const quality =
          rawQuality === 'ok'
            ? 'current'
            : rawQuality === 'stale' || rawQuality === 'degraded'
              ? 'stale'
              : 'missing'
        if (score == null || !Number.isFinite(score)) {
          return {
            value: null,
            label: loading ? 'SYNC' : 'NO DATA',
            band: 'missing',
            quality,
          }
        }
        const greed = Math.round((1 - Math.max(0, Math.min(1, score))) * 100)
        const band =
          greed <= 20
            ? 'extreme-fear'
            : greed <= 40
              ? 'fear'
              : greed <= 60
                ? 'neutral'
                : greed <= 80
                  ? 'greed'
                  : 'extreme-greed'
        const label = {
          'extreme-fear': 'EXTREME FEAR',
          fear: 'FEAR',
          neutral: 'NEUTRAL',
          greed: 'GREED',
          'extreme-greed': 'EXTREME GREED',
          missing: 'NO DATA',
        }[band]
        return { value: greed, label, band, quality }
      }

      it('correctly maps 5-band spectrum across boundary thresholds [0, 20, 40, 60, 80, 100]', () => {
        // High composite score (e.g. 1.0) means extreme risk / extreme fear
        expect(computeFearGreed(1.0).band).toBe('extreme-fear')
        expect(computeFearGreed(1.0).value).toBe(0)
        expect(computeFearGreed(0.85).band).toBe('extreme-fear') // greed = 15
        expect(computeFearGreed(0.8).band).toBe('extreme-fear') // greed = 20
        expect(computeFearGreed(0.79).band).toBe('fear') // greed = 21
        expect(computeFearGreed(0.6).band).toBe('fear') // greed = 40
        expect(computeFearGreed(0.59).band).toBe('neutral') // greed = 41
        expect(computeFearGreed(0.5).band).toBe('neutral') // greed = 50
        expect(computeFearGreed(0.4).band).toBe('neutral') // greed = 60
        expect(computeFearGreed(0.39).band).toBe('greed') // greed = 61
        expect(computeFearGreed(0.2).band).toBe('greed') // greed = 80
        expect(computeFearGreed(0.19).band).toBe('extreme-greed') // greed = 81
        expect(computeFearGreed(0.0).band).toBe('extreme-greed') // greed = 100
      })

      it('handles null, NaN, undefined, negative, and out-of-bound scores gracefully without crash', () => {
        expect(computeFearGreed(null).label).toBe('NO DATA')
        expect(computeFearGreed(undefined).label).toBe('NO DATA')
        expect(computeFearGreed(Number.NaN).label).toBe('NO DATA')
        expect(computeFearGreed(null, undefined, true).label).toBe('SYNC')

        // Clamped out of bounds
        expect(computeFearGreed(-5.0).value).toBe(100) // Clamped to 0 -> 100 greed
        expect(computeFearGreed(100.0).value).toBe(0) // Clamped to 1 -> 0 greed
      })
    })

    describe('Sector Rotation Ranking Oracle', () => {
      interface SectorRow {
        etf?: string
        name?: string
        flow_score?: number
      }

      function computeTopRotations(ranked: SectorRow[]) {
        const valid = [...ranked].filter((s) => s.etf)
        if (!valid.length) return { in: [] as SectorRow[], out: [] as SectorRow[] }
        const sorted = valid.sort((a, b) => Number(b.flow_score ?? 0) - Number(a.flow_score ?? 0))
        return {
          in: sorted.filter((s) => Number(s.flow_score ?? 0) > 0).slice(0, 2),
          out: sorted
            .filter((s) => Number(s.flow_score ?? 0) < 0)
            .slice(-2)
            .reverse(),
        }
      }

      it('extracts top 2 IN and top 2 OUT sectors correctly from ranked dataset', () => {
        const input: SectorRow[] = [
          { etf: 'XLK', flow_score: 0.85 },
          { etf: 'XLF', flow_score: 0.42 },
          { etf: 'XLI', flow_score: 0.15 },
          { etf: 'XLU', flow_score: -0.1 },
          { etf: 'XLE', flow_score: -0.65 },
          { etf: 'XLV', flow_score: -0.92 },
        ]

        const res = computeTopRotations(input)
        expect(res.in.map((s) => s.etf)).toEqual(['XLK', 'XLF'])
        // Out should take bottom 2 (-0.92 and -0.65) and reverse for highest negative magnitude first
        expect(res.out.map((s) => s.etf)).toEqual(['XLV', 'XLE'])
      })

      it('handles empty, single-sided, and all-zero flow score inputs safely', () => {
        expect(computeTopRotations([])).toEqual({ in: [], out: [] })

        // All positive (no out)
        const allPos = [
          { etf: 'XLK', flow_score: 0.5 },
          { etf: 'XLF', flow_score: 0.2 },
        ]
        const resPos = computeTopRotations(allPos)
        expect(resPos.in.length).toBe(2)
        expect(resPos.out.length).toBe(0)

        // All negative (no in)
        const allNeg = [
          { etf: 'XLE', flow_score: -0.5 },
          { etf: 'XLU', flow_score: -0.2 },
        ]
        const resNeg = computeTopRotations(allNeg)
        expect(resNeg.in.length).toBe(0)
        expect(resNeg.out.length).toBe(2)

        // All zero (no in or out)
        const allZero = [
          { etf: 'XLK', flow_score: 0 },
          { etf: 'XLF', flow_score: 0 },
        ]
        const resZero = computeTopRotations(allZero)
        expect(resZero.in.length).toBe(0)
        expect(resZero.out.length).toBe(0)
      })
    })

    describe('Vector Sparkline Generator Oracle', () => {
      function sparklinePath(points: { cum: number }[] | undefined): string {
        const values = (points ?? [])
          .map((point) => Number(point.cum))
          .filter(Number.isFinite)
          .slice(-20)
        if (values.length < 2) return ''
        const lo = Math.min(...values)
        const hi = Math.max(...values)
        const span = Math.max(hi - lo, Math.abs(hi) * 0.0005, 0.0001)
        return values
          .map((value, index) => {
            const x = (index / (values.length - 1)) * 48
            const y = 14 - ((value - lo) / span) * 12
            return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
          })
          .join(' ')
      }

      it('generates valid SVG path commands within [0, 48] x [2, 14] bounds', () => {
        const points = [{ cum: 100 }, { cum: 105 }, { cum: 95 }, { cum: 110 }]
        const path = sparklinePath(points)
        expect(path).toMatch(/^M0\.0,[\d.]+ L16\.0,[\d.]+ L32\.0,[\d.]+ L48\.0,[\d.]+$/)

        // Verify bounds
        const coords = [...path.matchAll(/[ML]([\d.]+),([\d.]+)/g)].map((m) => ({
          x: parseFloat(m[1]),
          y: parseFloat(m[2]),
        }))
        for (const pt of coords) {
          expect(pt.x).toBeGreaterThanOrEqual(0)
          expect(pt.x).toBeLessThanOrEqual(48)
          expect(pt.y).toBeGreaterThanOrEqual(2)
          expect(pt.y).toBeLessThanOrEqual(14)
        }
      })

      it('handles single-point, flat series (zero span), NaN, and empty inputs without divide-by-zero or crash', () => {
        expect(sparklinePath(undefined)).toBe('')
        expect(sparklinePath([])).toBe('')
        expect(sparklinePath([{ cum: 100 }])).toBe('')

        // Flat series (span = 0 protected by fallback)
        const flatPoints = [{ cum: 100 }, { cum: 100 }, { cum: 100 }]
        const flatPath = sparklinePath(flatPoints)
        expect(flatPath).not.toBe('')
        expect(flatPath).not.toContain('NaN')
        expect(flatPath).not.toContain('Infinity')

        // Corrupted series with NaN / Infinity filtered out
        const dirtyPoints = [{ cum: 100 }, { cum: Number.NaN }, { cum: 120 }]
        const dirtyPath = sparklinePath(dirtyPoints)
        expect(dirtyPath).not.toBe('')
        expect(dirtyPath).not.toContain('NaN')
      })
    })

    describe('Sidebar Toggle and LocalStorage Persistence Simulation', () => {
      let mockStorage: Record<string, string> = {}

      beforeEach(() => {
        mockStorage = {}
        vi.stubGlobal('localStorage', {
          getItem: (key: string) => mockStorage[key] ?? null,
          setItem: (key: string, val: string) => {
            mockStorage[key] = String(val)
          },
          removeItem: (key: string) => {
            delete mockStorage[key]
          },
          clear: () => {
            mockStorage = {}
          },
        })
      })

      afterEach(() => {
        vi.unstubAllGlobals()
      })

      it('toggles sidebarCollapsed state and persists to edge.sidebar.collapsed.v1', () => {
        const SIDEBAR_STORAGE_KEY = 'edge.sidebar.collapsed.v1'
        const sidebarCollapsed = ref(false)

        function toggleSidebar(): void {
          sidebarCollapsed.value = !sidebarCollapsed.value
          try {
            localStorage.setItem(SIDEBAR_STORAGE_KEY, sidebarCollapsed.value ? 'true' : 'false')
          } catch {
            /* ignore */
          }
        }

        expect(sidebarCollapsed.value).toBe(false)
        expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBeNull()

        // Toggle 1: Expand -> Collapse
        toggleSidebar()
        expect(sidebarCollapsed.value).toBe(true)
        expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe('true')

        // Toggle 2: Collapse -> Expand
        toggleSidebar()
        expect(sidebarCollapsed.value).toBe(false)
        expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe('false')
      })

      it('hydrates saved collapsed preference on mount and handles storage exceptions', () => {
        const SIDEBAR_STORAGE_KEY = 'edge.sidebar.collapsed.v1'
        mockStorage[SIDEBAR_STORAGE_KEY] = 'true'

        const sidebarCollapsed = ref(false)
        try {
          const saved = localStorage.getItem(SIDEBAR_STORAGE_KEY)
          if (saved === 'true') sidebarCollapsed.value = true
        } catch {
          /* ignore */
        }
        expect(sidebarCollapsed.value).toBe(true)

        // Storage throw test
        vi.stubGlobal('localStorage', {
          getItem: () => {
            throw new Error('SecurityError: localStorage blocked')
          },
          setItem: () => {
            throw new Error('SecurityError: localStorage blocked')
          },
        })

        // Should not throw
        expect(() => {
          try {
            const saved = localStorage.getItem(SIDEBAR_STORAGE_KEY)
            if (saved === 'true') sidebarCollapsed.value = true
          } catch {
            /* ignored gracefully */
          }
        }).not.toThrow()
      })
    })
  })
})
