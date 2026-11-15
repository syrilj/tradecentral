import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(rel: string): string {
  return readFileSync(join(root, rel), 'utf8')
}

describe('interface craft on the shell', () => {
  it('opens symbol search without an entrance animation and walks views then tickers', () => {
    const palette = source('components/SearchPalette.vue')
    expect(palette).not.toContain('animation: rise')
    expect(palette).toContain("e.key === 'ArrowDown'")
    expect(palette).toContain("kind: 'view' as const")
    expect(palette).toContain("kind: 'symbol' as const")
    expect(palette).toContain('aria-activedescendant')
    expect(palette).toContain('min-height: 44px')
    expect(palette).not.toContain('transition: all')
    expect(palette).not.toContain('v-else id="palette-list"')
  })

  it('keeps the account row a real button and the tools menu a 44px target', () => {
    const app = source('App.vue')
    expect(app).toContain('class="account-open"')
    expect(app).toContain('aria-haspopup="dialog"')
    expect(app).toContain('@click="profileDrawerOpen = true"')
    expect(app).toContain('min-height: 44px')
    expect(app).toContain('min-height: 100dvh')
    expect(app).not.toContain('translateX(2px)')
    expect(app).toContain('@media (hover: hover) and (pointer: fine)')
  })

  it('slides the profile drawer on the sheet curve and arrows through radios', () => {
    const drawer = source('components/ProfileDrawer.vue')
    expect(drawer).toContain('var(--ease-drawer)')
    expect(drawer).toContain('function stepRadio')
    expect(drawer).toContain('width: 44px')
    expect(drawer).not.toContain('transition: all')
  })

  it('names the drawer curve and keeps phone inputs from zooming the page', () => {
    expect(source('styles/tokens.css')).toContain('--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1)')
    const base = source('styles/base.css')
    expect(base).toContain('-webkit-tap-highlight-color: transparent')
    expect(base).toContain('touch-action: manipulation')
    expect(base).toContain('@media (pointer: coarse)')
    expect(base).toContain('font-size: 16px')
    expect(base).not.toMatch(/\.btn-quiet[\s\S]{0,400}transition:\s*all/)
  })

  it('fits the viewport under the notch and paints the status bar per route', () => {
    const html = readFileSync(join(root, '..', 'index.html'), 'utf8')
    expect(html).toContain('viewport-fit=cover')
    expect(html).not.toContain('user-scalable=no')
    expect(html).not.toContain('maximum-scale')
    const router = source('router.ts')
    expect(router).toContain('function setThemeColor')
    expect(router).toContain("tokenColor(paper ? '--paper' : '--void')")
    expect(source('styles/tokens.css')).toContain('--paper:')
  })
})
