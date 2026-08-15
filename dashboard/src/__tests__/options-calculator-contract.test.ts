import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Options profit calculator contract', () => {
  const calc = source('components/OptionsCalculator.vue')
  const view = source('views/OptionsView.vue')
  const workspace = source('views/CalculatorView.vue')
  const setups = source('views/SuggestView.vue')
  const api = source('api.ts')
  const flow = source('components/FlowDashboard.vue')

  it('exposes Long Call, Long Put, and multi-leg controls plus Greeks', () => {
    expect(calc).toContain('Long Call')
    expect(calc).toContain('Long Put')
    expect(calc).toContain('Long Straddle')
    expect(calc).toContain('Spot')
    expect(calc).toContain('Strike')
    expect(calc).toContain('Expiry DTE')
    expect(calc).toContain('Vol %')
    expect(calc).toContain('Delta')
    expect(calc).toContain('Gamma')
    expect(calc).toContain('Theta')
    expect(calc).toContain('Vega')
    expect(calc).toContain('P/L at expiry')
    expect(calc).toContain('api.optionsCalculator')
    expect(api).toContain('/api/options-calculator')
    expect(workspace).toContain('OptionsCalculator')
    expect(workspace).toContain('default-spot')
    expect(view).not.toContain('OptionsCalculator')
    expect(view).toContain("name: 'calculator'")
    expect(setups).toContain('setupCalculatorQuery')
    expect(setups).toContain('Play card')
    expect(view).toContain('On-demand historical tape')
    expect(view).toContain('api.flowTape')
  })

  it('keeps dark-pool and ATS copy off Flow and options surfaces', () => {
    expect(flow).not.toContain('Dark pool')
    expect(flow).not.toContain('ATS')
    expect(flow).not.toContain('NO ATS SOURCE')
    expect(view).not.toContain('Dark pool')
    expect(view).not.toContain('NO ATS SOURCE')
  })
})
