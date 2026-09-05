/**
 * Comprehensive verification test for Landing Page visual banners and showcase imagery.
 * Ensures all visual banners (both JPEG and modern WebP formats) are present on disk,
 * properly integrated with picture tags, fully accessible with meaningful alt text,
 * protected against Cumulative Layout Shift (CLS), responsive across viewports,
 * and strictly compliant with legal and product boundaries (decision-support only).
 */
import { describe, it, expect } from 'vitest'
import { existsSync, statSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const testDir = dirname(fileURLToPath(import.meta.url))
const dashboardRoot = join(testDir, '..', '..')
const publicImagesDir = join(dashboardRoot, 'public', 'images')
const landingViewPath = join(dashboardRoot, 'src', 'views', 'LandingView.vue')

const EXPECTED_IMAGES = [
  'hero-workstation.jpg',
  'flow-gex-showcase.jpg',
  'regime-magnets.jpg',
  'research-governance.jpg',
  'options-workbench.jpg',
] as const

const EXPECTED_WEBP = [
  'hero-workstation.webp',
  'flow-gex-showcase.webp',
  'regime-magnets.webp',
  'research-governance.webp',
  'options-workbench.webp',
] as const

describe('Landing Page Visual Banner Suite', () => {
  it('has all generated JPEG banner assets present in public/images', () => {
    for (const imgName of EXPECTED_IMAGES) {
      const fullPath = join(publicImagesDir, imgName)
      expect(existsSync(fullPath), `Missing JPEG asset: ${imgName}`).toBe(true)
      const stats = statSync(fullPath)
      expect(stats.size, `Image asset ${imgName} is unexpectedly small`).toBeGreaterThan(50_000)
    }
  })

  it('has high-performance WebP versions present with modern compression savings', () => {
    for (const webpName of EXPECTED_WEBP) {
      const fullPath = join(publicImagesDir, webpName)
      expect(existsSync(fullPath), `Missing WebP asset: ${webpName}`).toBe(true)
      const stats = statSync(fullPath)
      expect(stats.size, `WebP asset ${webpName} is unexpectedly small`).toBeGreaterThan(30_000)
      // WebP files should be lightweight (< 200 KB) for instantaneous landing paint
      expect(stats.size, `WebP asset ${webpName} exceeds payload budget`).toBeLessThan(200_000)
    }
  })

  it('references all visual banners with modern picture and webp source tags in LandingView.vue', () => {
    const src = readFileSync(landingViewPath, 'utf8')
    for (const imgName of EXPECTED_IMAGES) {
      expect(src).toContain(`/images/${imgName}`)
    }
    for (const webpName of EXPECTED_WEBP) {
      expect(src).toContain(`/images/${webpName}`)
      expect(src).toContain(`srcset="/images/${webpName}" type="image/webp"`)
    }
  })

  it('ensures all images have descriptive alt attributes for accessibility', () => {
    const src = readFileSync(landingViewPath, 'utf8')
    const imgTags = src.match(/<img[^>]+>/g) ?? []
    expect(imgTags.length).toBeGreaterThanOrEqual(5)

    for (const tag of imgTags) {
      expect(tag).toMatch(/alt="[^"]{10,}"/)
    }
  })

  it('protects against Cumulative Layout Shift (CLS) with width, height, and decoding attributes', () => {
    const src = readFileSync(landingViewPath, 'utf8')
    const imgTags = src.match(/<img[^>]+>/g) ?? []
    for (const tag of imgTags) {
      expect(tag).toContain('width="1376"')
      expect(tag).toContain('height="768"')
      expect(tag).toContain('decoding="async"')
    }
  })

  it('supports interactive view toggles for hero and flow sections', () => {
    const src = readFileSync(landingViewPath, 'utf8')
    expect(src).toContain('heroViewMode')
    expect(src).toContain('flowViewMode')
    expect(src).toContain("heroViewMode === 'mc'")
    expect(src).toContain("heroViewMode === 'workstation'")
    expect(src).toContain("flowViewMode === 'interactive'")
    expect(src).toContain("flowViewMode === 'tape'")
  })

  it('links the new workstation and regimes sections in the topnav and footer', () => {
    const src = readFileSync(landingViewPath, 'utf8')
    expect(src).toContain('href="#workstation"')
    expect(src).toContain('href="#regimes"')
    expect(src).toContain('id="workstation"')
    expect(src).toContain('id="regimes"')
  })

  it('maintains responsive viewport layout harmony without height shift on mobile', () => {
    const src = readFileSync(landingViewPath, 'utf8')
    // Both hero stages match height in mobile media query
    expect(src).toMatch(/\.hero-mc-stage,\s*\.hero-image-stage\s*\{\s*height:\s*280px;/)
  })

  it('preserves all strict product and copyright safety boundaries', () => {
    const src = readFileSync(landingViewPath, 'utf8')
    // No forbidden claim terms
    expect(src).not.toContain('actionable insight')
    expect(src).not.toContain('INSTITUTIONAL-GRADE')
    expect(src).not.toContain('Smart Money')
    expect(src).not.toContain('guaranteed returns')
    // No prohibited third-party broker or exchange logos
    expect(src.toLowerCase()).not.toContain('robinhood')
    expect(src.toLowerCase()).not.toContain('interactive brokers')
    expect(src.toLowerCase()).not.toContain('bloomberg')
    expect(src.toLowerCase()).not.toContain('tradingview')
  })
})
