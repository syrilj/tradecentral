import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const routerSource = readFileSync(join(srcRoot, 'router.ts'), 'utf8')
const appSource = readFileSync(join(srcRoot, 'App.vue'), 'utf8')

describe('public entry and operator routing', () => {
  it('keeps the product overview public and gives access its own route', () => {
    expect(routerSource).toMatch(/path:\s*'\/'\s*,\s*name:\s*'landing'/s)
    expect(routerSource).toMatch(/path:\s*'\/about'\s*,\s*redirect:\s*\{\s*name:\s*'landing'\s*\}/s)
    expect(routerSource).toMatch(/path:\s*'\/auth\/:pathMatch\(\.\*\)\*'\s*,\s*name:\s*'auth'/s)
  })

  it('guards non-public workspace routes and preserves the deep link', () => {
    expect(appSource).toContain('route.meta.public !== true')
    expect(appSource).toContain("name: 'auth'")
    expect(appSource).toContain('query: { redirect: route.fullPath }')
  })

  it('sanitizes redirect targets and returns signed-in operators to Flow', () => {
    expect(routerSource).toContain("value.startsWith('//')")
    expect(routerSource).toContain("value.startsWith('/auth')")
    expect(routerSource).toContain("return fallback")
    expect(routerSource).toContain("fallback = '/flow'")
  })

  it('aliases /quantitative-research onto the Market Financials model highlight', () => {
    expect(routerSource).toContain("path: '/quantitative-research'")
    expect(routerSource).toContain("name: 'quantitative-research'")
    expect(routerSource).toContain("name: 'market'")
    expect(routerSource).toContain("highlight: 'model-forecast'")
    expect(routerSource).toContain("tab: 'financials'")
  })

  it('updates document title with active symbol from route query', () => {
    expect(routerSource).toContain('to.query.symbol || to.query.setup')
    expect(routerSource).toContain('document.title = sym ?')
  })
})
