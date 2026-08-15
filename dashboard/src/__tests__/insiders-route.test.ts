import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')

describe('Insiders desk is reachable from options without authorizing trades', () => {
  const router = readFileSync(join(srcRoot, 'router.ts'), 'utf8')
  const app = readFileSync(join(srcRoot, 'App.vue'), 'utf8')
  const view = readFileSync(join(srcRoot, 'views', 'InsidersView.vue'), 'utf8')
  const options = readFileSync(join(srcRoot, 'views', 'OptionsView.vue'), 'utf8')

  it('registers the route and a market-tools entry', () => {
    expect(router).toMatch(/path:\s*'\/insiders'/)
    expect(router).toMatch(/name:\s*'insiders'/)
    expect(app).toContain("name: 'insiders'")
    expect(app).toContain("title: 'Insiders'")
    expect(app).toMatch(/const marketTools = \[[^\]]*name: 'insiders'/s)
  })

  it('loads SEC filings and optional Fintel without an order path', () => {
    expect(view).toContain('api.sentiment')
    expect(view).toContain('api.fintelIntel')
    expect(view).toContain('Authorized =')
    expect(view).toContain("name: 'options'")
    expect(view).not.toMatch(/place order|broker|dark pool/i)
    expect(options).toContain("name: 'insiders'")
    expect(options).toContain('ACTIVITY SIGN')
    expect(options).toContain('AUTHORIZED')
  })
})
