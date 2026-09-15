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

describe('Crypto workspace navigation', () => {
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')
  const iconSrc = source('components/AppIcon.vue')
  const paletteSrc = source('components/SearchPalette.vue')

  const primary = appSrc.match(/const primaryNav = \[\s*([\s\S]*?)\] as const/)?.[1] ?? ''
  const desk = appSrc.match(/const deskTools = \[\s*([\s\S]*?)\] as const/)?.[1] ?? ''
  const market = appSrc.match(/const marketTools = \[\s*([\s\S]*?)\] as const/)?.[1] ?? ''
  const research = appSrc.match(/const researchTools = \[\s*([\s\S]*?)\] as const/)?.[1] ?? ''
  const macro = appSrc.match(/const macroTools = \[\s*([\s\S]*?)\] as const/)?.[1] ?? ''

  it('registers a dedicated /crypto route, not a relabel of Options/Flow/Market/Macro', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/crypto['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]crypto['"]/)
    expect(routerSrc).toContain("import('@/views/CryptoView.vue')")
    expect(routerSrc).toMatch(/title:\s*['"]Crypto['"]/)
    expect(routerSrc).not.toMatch(/path:\s*['"]\/crypto['"][\s\S]{0,200}OptionsView/)
    expect(routerSrc).not.toMatch(/path:\s*['"]\/crypto['"][\s\S]{0,200}MacroView/)
  })

  it('sits in the rail primary list exactly once and is not duplicated in Tools overflow', () => {
    expect(namesIn(primary)).toContain('crypto')
    expect(primary).toContain("title: 'Crypto'")
    expect(primary).toContain("icon: 'crypto'")
    expect(primary).toContain('tab: true')
    expect(namesIn(desk)).not.toContain('crypto')
    expect(namesIn(market)).not.toContain('crypto')
    expect(namesIn(research)).not.toContain('crypto')
    expect(namesIn(macro)).not.toContain('crypto')
    expect([...appSrc.matchAll(/name:\s*'crypto'/g)]).toHaveLength(1)
  })

  it('updates the frozen primary count to the new unique total', () => {
    expect(namesIn(primary)).toEqual([
      'brief',
      'flow',
      'vpa',
      'reversal',
      'options',
      'regime',
      'suggest',
      'drift',
      'desk',
      'chain',
      'market',
      'crypto',
      'voltrend',
      'vanna',
    ])
    expect(namesIn(primary)).toHaveLength(14)
    expect(namesIn(desk)).toHaveLength(3)
    expect(namesIn(market)).toHaveLength(6)
    expect(namesIn(research)).toHaveLength(8)
  })

  it('exposes a SearchPalette jump and an icon glyph', () => {
    expect(paletteSrc).toContain("{ name: 'crypto', title: 'Crypto'")
    expect(paletteSrc).toContain("hint: '24/7 coin tape · Kalman · BTC COT'")
    expect(iconSrc).toContain("name === 'crypto'")
  })
})
