import { describe, expect, it } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = join(srcRoot, '..', '..')

const routerSource = readFileSync(join(srcRoot, 'router.ts'), 'utf8')
const landingSource = readFileSync(join(srcRoot, 'views', 'LandingView.vue'), 'utf8')
const authSource = readFileSync(join(srcRoot, 'views', 'AuthView.vue'), 'utf8')
const licensePath = join(repoRoot, 'LICENSE')
const licenseText = readFileSync(licensePath, 'utf8')

describe('Source-available license and in-app legal pages', () => {
  it('ships source-available evaluation terms in the repository root', () => {
    expect(existsSync(licensePath)).toBe(true)
    expect(licenseText).toContain('TradeCentral Source-Available Evaluation License')
    expect(licenseText).toContain('Copyright (c) 2026 Syril Jacob. All rights reserved.')
    expect(licenseText).toContain('This is not an open-source license')
    expect(licenseText).toContain('non-commercial purposes')
    expect(licenseText).toContain('THE SOFTWARE IS PROVIDED "AS IS"')
    expect(licenseText).not.toContain('MIT License')
  })

  it('exposes public /license and /terms routes in dashboard router', () => {
    expect(routerSource).toContain("path: '/license'")
    expect(routerSource).toContain("name: 'license'")
    expect(routerSource).toContain("path: '/terms'")
    expect(routerSource).toContain("name: 'terms'")
    expect(routerSource).toMatch(/path:\s*'\/license'[\s\S]*?public:\s*true/)
    expect(routerSource).toMatch(/path:\s*'\/terms'[\s\S]*?public:\s*true/)
  })

  it('links to License Agreement and Terms of Service in LandingView footer', () => {
    expect(landingSource).toContain('aria-label="Legal"')
    expect(landingSource).toContain('to="/license"')
    expect(landingSource).toContain('License agreement')
    expect(landingSource).toContain('to="/terms"')
    expect(landingSource).toContain('Terms of service')
  })

  it('incorporates legally binding consent notice in AuthView', () => {
    expect(authSource).toContain('legal-consent-notice')
    expect(authSource).toContain('Terms of Service')
    expect(authSource).toContain('Source-Available License')
    expect(authSource).toContain('to="/terms"')
    expect(authSource).toContain('to="/license"')
  })

  it('provides a dedicated LegalView component with tabs for License and Terms', () => {
    const legalViewPath = join(srcRoot, 'views', 'LegalView.vue')
    expect(existsSync(legalViewPath)).toBe(true)
    const legalViewSource = readFileSync(legalViewPath, 'utf8')
    expect(legalViewSource).toContain('TradeCentral Source-Available Evaluation License')
    expect(legalViewSource).toContain('This is not an open-source license')
    expect(legalViewSource).toContain('Terms of Service & Research Disclaimers')
    expect(legalViewSource).toContain('Hypothetical and simulated performance')
    expect(legalViewSource).not.toContain('MIT License')
    expect(legalViewSource).toContain('copyCurrentDocument')
    expect(legalViewSource).toContain('printDocument')
  })
})
