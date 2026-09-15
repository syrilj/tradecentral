import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Macro tab (cross-asset regime board)', () => {
  const view = source('views/MacroView.vue')
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')
  const apiSrc = source('api.ts')
  const iconSrc = source('components/AppIcon.vue')

  it('registers the /macro route with a Macro title', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/macro['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]macro['"]/)
    expect(routerSrc).toMatch(/title:\s*['"]Macro['"]/)
    expect(appSrc).toMatch(/name:\s*'macro'/)
    expect(iconSrc).toContain("name === 'globe'")
  })

  it('lives in its own Tools group without disturbing the five primary tabs', () => {
    expect(appSrc).toContain('const macroTools = [')
    expect(appSrc).toContain("title: 'Macro'")
    expect(appSrc).toContain("hint: 'Cross-asset regime board'")
    // Primary nav stays exactly the five operator destinations.
    const primaryMatch = appSrc.match(/const primaryNav = \[\s*([\s\S]*?)\] as const/)
    expect(primaryMatch).toBeTruthy()
    const primaryNames = [...primaryMatch![1].matchAll(/name:\s*'([^']+)'/g)].map((m) => m[1])
    expect(primaryNames).toEqual([
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
    ])
    expect(appSrc).not.toMatch(/const primaryNav = \[[^\]]*name: 'macro'/s)
  })

  it('composes existing endpoints instead of inventing a provider', () => {
    expect(apiSrc).toContain('MACRO_TAPE_SLEEVES')
    expect(apiSrc).toMatch(/cot:\s*\(opts\?:\s*\{\s*force\?: boolean\s*\}\)/)
    expect(view).toContain('api.quotes(MACRO_TAPE_SYMBOLS)')
    expect(view).toContain('api.cot(')
    expect(view).toContain('api.sentiment()')
    expect(view).toContain('sectorFlowRes')
  })

  it('covers every macro sleeve: tape, vol complex, COT books, rotation', () => {
    for (const sym of ['SPY', 'QQQ', 'IWM', 'TLT', 'HYG', 'GLD', 'UUP']) {
      expect(apiSrc).toMatch(new RegExp(`sym:\\s*'${sym}'`))
    }
    // COT books arrive from /api/cot (ES/NQ/RTY/VX/ZN/GC/BTC server-side);
    // the view must render them keyed by id with a z-scored lean.
    expect(view).toContain('Cross-asset tape')
    expect(view).toContain('Volatility complex')
    expect(view).toContain('Spec positioning · CFTC')
    expect(view).toContain('Equity rotation sleeve')
    expect(view).toMatch(/v-for="m in cotRows"/)
    expect(view).toContain('cotLean(')
  })

  it('renders missing data as explicit states, never fake zeros', () => {
    expect(view).toContain('UNMEASURED')
    expect(view).toContain('STALE')
    expect(view).toContain('No cross-asset marks available')
    expect(view).toContain('Vol complex unavailable')
    expect(view).toContain('No COT markets loaded')
    expect(view).toContain('No sector flow data available yet')
  })

  it('stays decision support only and reuses shared lean semantics', () => {
    expect(view).toContain('DECISION SUPPORT ONLY')
    expect(view).toContain("from '@/cotLean'")
    expect(view).toContain('cotLeanFromSpecNetZ')
  })
})
