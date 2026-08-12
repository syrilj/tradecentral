import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const routerSource = readFileSync(join(srcRoot, 'router.ts'), 'utf8')

describe('operator entry route', () => {
  it('opens the public overview at / and keeps the Desk one click away at /desk', () => {
    expect(routerSource).toMatch(/path:\s*'\/'\s*,\s*name:\s*'landing'/s)
    expect(routerSource).toMatch(/path:\s*'\/about'\s*,\s*redirect:\s*\{\s*name:\s*'landing'\s*\}/s)
    expect(routerSource).toMatch(/path:\s*'\/desk'\s*,\s*name:\s*'desk'/s)
  })
})
