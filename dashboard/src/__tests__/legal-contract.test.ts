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

describe('Legally binding licensing model and in-app legal infrastructure', () => {
  it('maintains a formal, legally enforceable commercial proprietary license agreement in repository root', () => {
    expect(existsSync(licensePath)).toBe(true)
    expect(licenseText).toContain(
      'COMMERCIAL PROPRIETARY SOFTWARE LICENSE AND EVALUATION AGREEMENT',
    )
    expect(licenseText).toContain('LEGALLY BINDING CONTRACT')
    expect(licenseText).toContain('Syril Jacob')
    expect(licenseText).toContain('LIMITED LICENSE GRANT')
    expect(licenseText).toContain('EXPLICIT RESTRICTIONS AND PROHIBITIONS')
    expect(licenseText).toContain('No Live, Automated, or Algorithmic Trading Execution')
    expect(licenseText).toContain('No Commercial Exploitation or Hosting')
    expect(licenseText).toContain('No Derivative Works or Reverse Engineering')
    expect(licenseText).toContain('No Artificial Intelligence or Machine Learning Model Ingestion')
    expect(licenseText).toContain('INTELLECTUAL PROPERTY AND TRADE SECRET PROTECTION')
    expect(licenseText).toContain('DISCLAIMER OF WARRANTIES')
    expect(licenseText).toContain('REGULATORY SAFE HARBOR AND FINANCIAL DISCLAIMERS')
    expect(licenseText).toContain('CFTC Rule 4.41')
    expect(licenseText).toContain('LIMITATION OF LIABILITY')
    expect(licenseText).toContain('INJUNCTIVE RELIEF')
    expect(licenseText).toContain('GOVERNING LAW, JURISDICTION, AND GENERAL PROVISIONS')
    expect(licenseText).toContain('Delaware')
    expect(licenseText).toContain('American Arbitration Association')
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
    expect(authSource).toContain('Software License Agreement')
    expect(authSource).toContain('to="/terms"')
    expect(authSource).toContain('to="/license"')
  })

  it('provides a dedicated LegalView component with tabs for License and Terms', () => {
    const legalViewPath = join(srcRoot, 'views', 'LegalView.vue')
    expect(existsSync(legalViewPath)).toBe(true)
    const legalViewSource = readFileSync(legalViewPath, 'utf8')
    expect(legalViewSource).toContain(
      'Commercial Proprietary Software License and Evaluation Agreement',
    )
    expect(legalViewSource).toContain(
      'Terms of Service, Regulatory Disclaimers & Publisher Safe Harbor',
    )
    expect(legalViewSource).toContain('Advisers Act § 202(a)(11)(D)')
    expect(legalViewSource).toContain('CFTC Rule 4.41')
    expect(legalViewSource).toContain('copyCurrentDocument')
    expect(legalViewSource).toContain('printDocument')
  })
})
