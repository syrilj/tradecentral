import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const app = readFileSync(join(root, 'App.vue'), 'utf8')
const api = readFileSync(join(root, 'api.ts'), 'utf8')

describe('application market strip contract', () => {
  it('shows observed freshness and trend instead of anonymous number blocks', () => {
    expect(app).toContain('compactBarDate')
    expect(app).toContain('sparklinePath')
    expect(app).toContain("`quality-${m.quality}`")
    expect(app).toContain("`${m.asofLabel} · STALE`")
    expect(app).toContain('changeBasis: chg1d != null ? \'1D\' : \'1M\'')
    expect(api).toContain('change_basis?: \'last_two_observed_closes\'')
  })

  it('labels the energy proxy honestly and dates the rotation source', () => {
    expect(app).toContain("{ sym: 'XLE', label: 'Energy' }")
    expect(app).not.toContain("{ sym: 'XLE', label: 'Oil' }")
    expect(app).toContain('rotationAsOf')
    expect(app).toContain('rotationFreshness')
    expect(app).toContain('BAR ${compactBarDate(rotationAsOf.value)}')
  })

  it('moves search into the top strip and removes the detached rail block', () => {
    expect(app).toContain('class="strip-search"')
    expect(app).not.toContain('class="find"')
    expect(app).not.toContain('.profile-block')
    expect(app).not.toContain('.profile-label')
  })
})
