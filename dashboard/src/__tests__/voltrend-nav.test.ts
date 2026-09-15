import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

function namesIn(block: string): string[] {
  return [...block.matchAll(/name:\s*'([^']+)'/g)].map((m) => m[1])
}

describe('Volatility-Targeted Trend workspace navigation', () => {
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')
  const iconSrc = source('components/AppIcon.vue')
  const paletteSrc = source('components/SearchPalette.vue')

  const primary = appSrc.match(/const primaryNav = \[\s*([\s\S]*?)\] as const/)?.[1] ?? ''
  const desk = appSrc.match(/const deskTools = \[\s*([\s\S]*?)\] as const/)?.[1] ?? ''
  const market = appSrc.match(/const marketTools = \[\s*([\s\S]*?)\] as const/)?.[1] ?? ''
  const research = appSrc.match(/const researchTools = \[\s*([\s\S]*?)\] as const/)?.[1] ?? ''
  const macro = appSrc.match(/const macroTools = \[\s*([\s\S]*?)\] as const/)?.[1] ?? ''

  it('registers a dedicated /voltrend route pointing to VolTrendView.vue', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/voltrend['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]voltrend['"]/)
    expect(routerSrc).toContain("import('@/views/VolTrendView.vue')")
    expect(routerSrc).toMatch(/title:\s*['"]Vol Trend['"]/)
  })

  it('sits in the rail primaryNav as a main tab and is not in overflow tools', () => {
    expect(namesIn(primary)).toContain('voltrend')
    expect(primary).toContain("title: 'Vol Trend'")
    expect(primary).toContain("icon: 'voltrend'")
    expect(primary).toContain('tab: true')
    expect(namesIn(desk)).not.toContain('voltrend')
    expect(namesIn(market)).not.toContain('voltrend')
    expect(namesIn(research)).not.toContain('voltrend')
    expect(namesIn(macro)).not.toContain('voltrend')
  })

  it('has an icon glyph in AppIcon.vue and a command jump in SearchPalette.vue', () => {
    expect(iconSrc).toContain("name === 'voltrend'")
    expect(paletteSrc).toContain("name: 'voltrend'")
    expect(paletteSrc).toContain("title: 'Vol Trend'")
  })
})
