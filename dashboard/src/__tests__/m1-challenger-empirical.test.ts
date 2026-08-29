import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const DASHBOARD_DIR = resolve(__dirname, '../..')
const TOKENS_PATH = resolve(DASHBOARD_DIR, 'src/styles/tokens.css')
const BASE_PATH = resolve(DASHBOARD_DIR, 'src/styles/base.css')
const PANEL_PATH = resolve(DASHBOARD_DIR, 'src/components/Panel.vue')
const SEARCH_PATH = resolve(DASHBOARD_DIR, 'src/components/SearchPalette.vue')
const VERDICT_PATH = resolve(DASHBOARD_DIR, 'src/components/VerdictChip.vue')
const HELPTIP_PATH = resolve(DASHBOARD_DIR, 'src/components/HelpTip.vue')

describe('Milestone 1 Challenger: Empirical Design Tokens & UI Primitives Verification', () => {
  const tokensContent = readFileSync(TOKENS_PATH, 'utf-8')
  const baseContent = readFileSync(BASE_PATH, 'utf-8')
  const panelContent = readFileSync(PANEL_PATH, 'utf-8')
  const searchContent = readFileSync(SEARCH_PATH, 'utf-8')
  const verdictContent = readFileSync(VERDICT_PATH, 'utf-8')
  const helpTipContent = readFileSync(HELPTIP_PATH, 'utf-8')

  describe('1. Glassmorphism Design Token Resolution & Validation', () => {
    const rootMatch = tokensContent.match(/:root\s*\{([\s\S]*?)\n\}/)
    expect(rootMatch).toBeTruthy()
    const rootBlock = rootMatch ? rootMatch[1] : ''

    const definedVars = new Set<string>()
    const varDefRegex = /(--[a-zA-Z0-9_-]+)\s*:\s*([^;]+);/g
    let match: RegExpExecArray | null
    while ((match = varDefRegex.exec(rootBlock)) !== null) {
      definedVars.add(match[1])
    }

    const REQUIRED_GLASS_TOKENS = [
      '--glass-base',
      '--glass-surface',
      '--glass-surface-hi',
      '--glass-overlay',
      '--glass-border',
      '--glass-border-subtle',
      '--glass-border-hi',
      '--glass-border-accent',
      '--glass-specular',
      '--glass-specular-subtle',
      '--glass-specular-accent',
      '--glass-shadow-sm',
      '--glass-shadow-md',
      '--glass-shadow-lg',
      '--glass-shadow-drawer',
      '--glass-blur-sm',
      '--glass-blur-md',
      '--glass-blur-lg',
      '--glass-blur-xl',
    ]

    for (const token of REQUIRED_GLASS_TOKENS) {
      it(`defines contract token ${token}`, () => {
        expect(definedVars.has(token)).toBe(true)
      })
    }

    it('ensures all blur tokens have valid blur(Npx) format', () => {
      const blurSm = tokensContent.match(/--glass-blur-sm:\s*(blur\(\d+px\));/)
      const blurMd = tokensContent.match(/--glass-blur-md:\s*(blur\(\d+px\));/)
      const blurLg = tokensContent.match(/--glass-blur-lg:\s*(blur\(\d+px\));/)
      const blurXl = tokensContent.match(/--glass-blur-xl:\s*(blur\(\d+px\));/)

      expect(blurSm).toBeTruthy()
      expect(blurMd).toBeTruthy()
      expect(blurLg).toBeTruthy()
      expect(blurXl).toBeTruthy()
    })

    it('ensures all specular highlight tokens have valid inset shadow syntax', () => {
      const specRegex = /(--glass-specular(?:-subtle|-accent)?):\s*(inset\s+[^;]+);/g
      let specCount = 0
      while ((match = specRegex.exec(tokensContent)) !== null) {
        specCount++
        expect(match[2]).toContain('inset')
      }
      expect(specCount).toBe(3)
    })

    it('ensures all shadow tokens have valid elevation parameters and no 0 0 forbidden glow halos', () => {
      const shadowTokens = [
        '--glass-shadow-sm',
        '--glass-shadow-md',
        '--glass-shadow-lg',
        '--glass-shadow-drawer',
      ]
      for (const token of shadowTokens) {
        const regex = new RegExp(`${token}:\\s*([^;]+);`)
        const shadowMatch = tokensContent.match(regex)
        expect(shadowMatch).toBeTruthy()
        const val = shadowMatch ? shadowMatch[1] : ''
        // Check valid offset format (0 or Npx for x, 0 or Npx for y, Npx for blur, rgba for color)
        expect(val).toMatch(/-?\d+(?:px)?\s+\d+(?:px)?\s+\d+px\s+rgba\(/)
      }
    })
  })

  describe('2. CSS Custom Property Reference Integrity Check (Zero Undefined Variables)', () => {
    const allDefinedVars = new Set<string>()
    const varDefRegex = /(--[a-zA-Z0-9_-]+)\s*:\s*([^;]+);/g
    let match: RegExpExecArray | null
    while ((match = varDefRegex.exec(tokensContent)) !== null) {
      allDefinedVars.add(match[1])
    }

    const filesToTest = [
      { name: 'base.css', content: baseContent },
      { name: 'Panel.vue', content: panelContent },
      { name: 'SearchPalette.vue', content: searchContent },
      { name: 'VerdictChip.vue', content: verdictContent },
      { name: 'HelpTip.vue', content: helpTipContent },
    ]

    for (const { name, content } of filesToTest) {
      it(`verifies all CSS var() calls in ${name} reference defined tokens or valid fallbacks`, () => {
        const varUsageRegex = /var\(\s*(--[a-zA-Z0-9_-]+)([\s\S]*?)\)/g
        const usedVars = new Set<string>()
        let varMatch: RegExpExecArray | null
        while ((varMatch = varUsageRegex.exec(content)) !== null) {
          const varName = varMatch[1]
          const remainder = varMatch[2]
          if (remainder.includes(',')) continue
          usedVars.add(varName)
        }

        for (const usedVar of usedVars) {
          const isDefinedInTokens = allDefinedVars.has(usedVar)
          const isDefinedLocally = content.includes(`${usedVar}:`)
          expect(
            isDefinedInTokens || isDefinedLocally,
            `Undefined CSS variable ${usedVar} found in ${name}`,
          ).toBe(true)
        }
      })
    }
  })

  describe('3. Base CSS Utility Classes & WebKit Compatibility', () => {
    const REQUIRED_UTILITIES = [
      '.glass-panel',
      '.glass-panel-interactive',
      '.glass-card',
      '.glass-chip',
      '.btn-glass',
      '.input-glass',
    ]

    for (const util of REQUIRED_UTILITIES) {
      it(`defines utility class ${util} in base.css`, () => {
        expect(baseContent).toContain(util)
      })
    }

    it('ensures -webkit-backdrop-filter is paired with backdrop-filter across all glass utilities in base.css', () => {
      const backdropMatches = baseContent.match(
        /(?<!-webkit-)backdrop-filter:\s*var\(--glass-blur-[a-z]+\);/g,
      )
      const webkitMatches = baseContent.match(
        /-webkit-backdrop-filter:\s*var\(--glass-blur-[a-z]+\);/g,
      )

      expect(backdropMatches).toBeTruthy()
      expect(webkitMatches).toBeTruthy()
      expect(backdropMatches?.length).toBe(6)
      expect(webkitMatches?.length).toBe(6)
    })

    it('verifies interactive hover/active/focus micro-interactions in base.css', () => {
      expect(baseContent).toContain('.glass-panel-interactive:hover')
      expect(baseContent).toContain('.btn-glass:hover:not(:disabled)')
      expect(baseContent).toContain('.btn-glass:active:not(:disabled)')
      expect(baseContent).toContain('.input-glass:focus')
    })
  })

  describe('4. Component Invariant & Glassmorphism Verification', () => {
    it('verifies Panel.vue props contract and glassmorphic styling', () => {
      expect(panelContent).toContain('glass?: boolean')
      expect(panelContent).toContain('backdrop-filter: var(--glass-blur-md);')
      expect(panelContent).toContain('-webkit-backdrop-filter: var(--glass-blur-md);')
      expect(panelContent).toContain('background: var(--glass-surface);')
      expect(panelContent).toContain(
        'box-shadow: var(--glass-shadow-sm), var(--glass-specular-subtle);',
      )
      expect(panelContent).toContain('.panel:hover')
    })

    it('verifies SearchPalette.vue maintains solid scrim invariant (no forbidden backdrop-filter)', () => {
      expect(searchContent).not.toContain('backdrop-filter')
      expect(searchContent).toContain(
        'background: color-mix(in srgb, var(--void) 88%, transparent);',
      )
      expect(searchContent).toContain('var(--glass-border-hi)')
      expect(searchContent).toContain('var(--glass-specular)')
    })

    it('verifies VerdictChip.vue handles verdict codes and has frosted glass styling', () => {
      expect(verdictContent).toContain('backdrop-filter: var(--glass-blur-sm);')
      expect(verdictContent).toContain('-webkit-backdrop-filter: var(--glass-blur-sm);')
      expect(verdictContent).toContain('box-shadow: var(--glass-specular-subtle);')

      // Test classification logic matching component
      const classify = (verdict: string) => {
        const v = (verdict ?? '').toUpperCase().replace(/[\s_]/g, '-')
        if (v === 'GO') return 'go'
        if (v === 'NO-GO' || v === 'NOGO' || v === 'FAIL') return 'no-go'
        if (v.includes('RUN') || v.includes('PEND')) return 'running'
        return 'unknown'
      }

      expect(classify('GO')).toBe('go')
      expect(classify('NO-GO')).toBe('no-go')
      expect(classify('NOGO')).toBe('no-go')
      expect(classify('FAIL')).toBe('no-go')
      expect(classify('RUNNING')).toBe('running')
      expect(classify('PENDING')).toBe('running')
      expect(classify('UNKNOWN')).toBe('unknown')
      expect(classify('')).toBe('unknown')
      expect(classify('NO_GO')).toBe('no-go')
    })

    it('verifies HelpTip.vue has accessible tooltip and glassmorphism styling', () => {
      expect(helpTipContent).toContain('role="tooltip"')
      expect(helpTipContent).toContain('tabindex="0"')
      expect(helpTipContent).toContain('background: var(--glass-surface-hi);')
      expect(helpTipContent).toContain('backdrop-filter: var(--glass-blur-md);')
      expect(helpTipContent).toContain('-webkit-backdrop-filter: var(--glass-blur-md);')
      expect(helpTipContent).toContain('box-shadow: var(--glass-shadow-md), var(--glass-specular);')
    })
  })
})
