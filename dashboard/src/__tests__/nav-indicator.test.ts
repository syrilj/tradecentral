import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const appSrc = readFileSync(join(root, 'App.vue'), 'utf8')

function rule(src: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const re = new RegExp(`^[ \\t]*${escaped}\\s*\\{([\\s\\S]*?)\\n[ \\t]*\\}`, 'm')
  const m = src.match(re)
  return m?.[1] ?? ''
}

describe('Rail active-tab indicator is an icon well', () => {
  const navItem = rule(appSrc, '.nav-item')
  const navOn = rule(appSrc, '.nav-item.on')
  const icon = rule(appSrc, '.nav-icon')
  const onIcon = rule(appSrc, '.nav-item.on .nav-icon')
  const collapsedItem = rule(appSrc, '.rail.is-collapsed .nav-item')
  const compact = appSrc.match(/@media \(max-width: 780px\)\s*\{([\s\S]*)$/)?.[1] ?? ''
  const compactItem = rule(compact, '.nav-item')

  it('sizes the hit target to at least 44px in every rail mode', () => {
    expect(navItem).toMatch(/min-height:\s*44px/)
    expect(collapsedItem).toMatch(/min-height:\s*44px/)
    expect(compactItem).toMatch(/min-height:\s*64px/)
  })

  it('draws the well on .nav-icon around the 16px glyph, not a full-row capsule', () => {
    expect(appSrc).toMatch(/<span class="nav-icon">/)
    expect(appSrc).toMatch(/<AppIcon :name="n\.icon" :size="16" \/>/)
    expect(navItem).toMatch(/--nav-icon-size:\s*16px/)
    expect(navItem).toMatch(/--nav-icon-well:\s*28px/)
    expect(navItem).not.toMatch(/border-radius:\s*var\(--r-capsule\)/)
    expect(navOn).not.toMatch(/--r-capsule/)

    expect(icon).toMatch(/width:\s*var\(--nav-icon-well\)/)
    expect(icon).toMatch(/height:\s*var\(--nav-icon-well\)/)
    expect(icon).toMatch(/place-items:\s*center/)
    expect(icon).toMatch(/border-radius:\s*var\(--r-sm\)/)
    expect(onIcon).toMatch(/background:\s*var\(--panel-hi\)/)
    expect(onIcon).toMatch(/border-color:\s*var\(--phosphor\)/)

    expect(appSrc).not.toMatch(/\.nav-item\.on::after/)
    expect(appSrc).not.toMatch(/top:\s*22%/)
    expect(appSrc).not.toMatch(/bottom:\s*22%/)
    expect(appSrc).not.toMatch(/calc\(\s*6px\s*\+\s*var\(--nav-icon-size\)/)
    expect(appSrc).not.toMatch(/calc\(\s*4px\s*\+\s*var\(--nav-icon-size\)/)
  })

  it('keeps that well on the icon when collapsed and in the compact bar', () => {
    expect(collapsedItem).toMatch(/align-items:\s*center/)
    expect(compactItem).toMatch(/align-items:\s*center/)
    expect(compactItem).toMatch(/flex-direction:\s*column/)
    expect(compact).not.toMatch(/\.nav-item\.on::after/)
    expect(compact).not.toMatch(/left:\s*18%/)
    expect(compact).not.toMatch(/right:\s*18%/)
    expect(compact).not.toMatch(/top:\s*22%/)
    expect(appSrc).not.toMatch(/\.rail\.is-collapsed \.nav-item\.on::after/)
  })
})
