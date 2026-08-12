/**
 * Options UI token / anti-neon gate.
 *
 * Reads the shipped Vue SFCs that power the Options desk and asserts the
 * instrument palette (call/put tokens, solid live lamp, no green-red chart
 * fills, no expanding neon pulse). This is a source-structure gate on the
 * real files Vite serves — not a reimplementation of the UI.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

function readSrc(rel: string): string {
  return readFileSync(join(root, rel), 'utf8')
}

/** Classic emerald/red chart palette + glow filters that violate the instrument brief. */
const FORBIDDEN = [
  '#10b981',
  '#ef4444',
  '#34d399',
  '#f87171',
  '#059669',
  '#dc2626',
  '0x10b981',
  '0xef4444',
  'drop-shadow',
  '@keyframes live-pulse',
  'live-pulse 1.6s',
  'GREEN=CALL',
  'RED=PUT',
]

const OPTIONS_SURFACES = [
  'views/OptionsView.vue',
  'components/SqueezeScreener.vue',
  'components/GammaExposureMap.vue',
  'components/OptionsFlowContext.vue',
  'components/ProbabilityDensityChart.vue',
  'components/RiskNeutral3DModel.vue',
  'components/OptionsDriftChart.vue',
] as const

describe('Options UI token gate (shipped SFCs)', () => {
  for (const rel of OPTIONS_SURFACES) {
    it(`${rel} has no green/red neon chart fills, drop-shadow glow, or expanding live-pulse`, () => {
      const src = readSrc(rel)
      for (const bad of FORBIDDEN) {
        expect(src, `${rel} still contains forbidden pattern: ${bad}`).not.toContain(bad)
      }
    })
  }

  it('SqueezeScreener ships circular ring + KEY sections + call/put side-dots', () => {
    const src = readSrc('components/SqueezeScreener.vue')
    expect(src).toMatch(/class="ring-fill"/)
    expect(src).toMatch(/RING_C/)
    expect(src).toMatch(/KEY LEVELS/)
    expect(src).toMatch(/KEY FACTORS/)
    expect(src).toMatch(/KEY TAKEAWAYS/)
    expect(src).toMatch(/side-dot/)
    expect(src).toMatch(/var\(--call/)
    expect(src).toMatch(/var\(--put/)
    expect(src).toMatch(/\.ring-fill\.bullish\s*\{\s*stroke:\s*var\(--call/)
    expect(src).toMatch(/\.ring-fill\.bearish\s*\{\s*stroke:\s*var\(--put/)
  })

  it('GammaExposureMap bars/legend use call/put tokens and flat net dots', () => {
    const src = readSrc('components/GammaExposureMap.vue')
    expect(src).toMatch(/leg-dot call/)
    expect(src).toMatch(/leg-dot put/)
    expect(src).toMatch(/leg-dot net/)
    expect(src).toMatch(/\.strike-bar \.call-bar\s*\{\s*fill:\s*var\(--call\)/)
    expect(src).toMatch(/\.strike-bar \.put-bar\s*\{\s*fill:\s*var\(--put\)/)
    expect(src).toMatch(/\.strike-bar \.net-dot\s*\{[^}]*fill:\s*var\(--ink\)/s)
    // No glow on net markers
    const netBlock = src.match(/\.strike-bar \.net-dot\s*\{[^}]+\}/s)?.[0] ?? ''
    expect(netBlock).not.toMatch(/drop-shadow|filter:/)
  })

  it('Options workbench + flow context use token colors and a solid live lamp', () => {
    const view = readSrc('views/OptionsView.vue')
    const flow = readSrc('components/OptionsFlowContext.vue')
    expect(view).toMatch(/OptionsFlowContext/)
    expect(flow).toMatch(/class="premium-track"/)
    expect(flow).toMatch(/\.call-fill\s*\{\s*background:\s*var\(--call\)/)
    expect(flow).toMatch(/\.put-fill\s*\{\s*background:\s*var\(--put\)/)
    expect(flow).toMatch(/\.flow-context\.call\s*\{[^}]*--flow-tone:\s*var\(--call\)/s)
    expect(flow).toMatch(/\.flow-context\.put\s*\{[^}]*--flow-tone:\s*var\(--put\)/s)
    expect(view).toMatch(/grid-template-columns:\s*minmax\(260px,\s*300px\)[^;]+minmax\(250px,\s*290px\)/)
    expect(view).toMatch(/grid-auto-rows:\s*clamp\(430px,\s*46vh,\s*500px\)/)
    expect(view).toMatch(/\.workbench\s*\{[^}]*gap:\s*8px/s)
    // Solid phosphor lamp — no animation keyframes
    expect(view).toMatch(/\.live-pulse\.live\s*\{[^}]*background:\s*var\(--phosphor\)/s)
    expect(view).not.toMatch(/@keyframes live-pulse/)
  })

  it('ProbabilityDensityChart has no curve glow filter', () => {
    const src = readSrc('components/ProbabilityDensityChart.vue')
    expect(src).not.toMatch(/filter:\s*drop-shadow/)
    expect(src).toMatch(/\.curve\s*\{[^}]*stroke:\s*var\(--phosphor\)/s)
  })

  it('only enables the 3D probability surface when measured inputs exist', () => {
    const density = readSrc('components/ProbabilityDensityChart.vue')
    const surface = readSrc('components/RiskNeutral3DModel.vue')
    expect(density).toContain('const canRender3d = computed(() => model.value !== null)')
    expect(density).toContain(':disabled="!canRender3d"')
    expect(density).toContain("v-if=\"viewMode === '3d' && canRender3d\"")
    expect(surface).not.toContain('props.spot || 100')
    expect(surface).not.toContain('atm_iv || 0.25')
    expect(surface).not.toContain('horizon_days || 30')
  })

  it('Options inherits the global instrument palette and labels setup status truthfully', () => {
    const view = readSrc('views/OptionsView.vue')
    expect(view).toMatch(/\.options-view\s*\{[^}]*background:\s*var\(--void\)/s)
    expect(view).not.toMatch(/--(?:void|panel|phosphor|call|put|long|short|warn):\s*#/)
    expect(view).toContain('SETUP WATCH')
    expect(view).not.toContain('LONG IT')
  })

  it('OptionsDriftChart call/put traces use token family', () => {
    const src = readSrc('components/OptionsDriftChart.vue')
    expect(src).toMatch(/\.flow-trace\.call\s*\{\s*stroke:\s*var\(--call/)
    expect(src).toMatch(/\.flow-trace\.put\s*\{\s*stroke:\s*var\(--put/)
    expect(src).toMatch(/\.activity-bars \.bar\.call\s*\{\s*fill:\s*var\(--call\)/)
    expect(src).toMatch(/\.activity-bars \.bar\.put\s*\{\s*fill:\s*var\(--put\)/)
  })
})

/**
 * Aura-farming / instrument shell gate.
 * Bans glass scrims, decorative gradients, and rainbow chart defaults that
 * fight the measurement-instrument brief in tokens.css.
 */
const AURA_FORBIDDEN = [
  'backdrop-filter',
  '#ffb703',
  '#4cc9f0',
  '#b5179e',
  '#d77bcf',
  '#8fd4b8',
  '#6ee7b7',
  'linear-gradient(90deg, color-mix',
  'linear-gradient(110deg',
  'linear-gradient(180deg, color-mix(in srgb, var(--phosphor)',
]

const AURA_SURFACES = [
  'views/FlowView.vue',
  'components/SearchPalette.vue',
  'components/TrajectoryChart.vue',
  'views/DeskView.vue',
  'views/AdaptiveView.vue',
  'views/FintelView.vue',
] as const

describe('Aura-farming instrument shell gate', () => {
  for (const rel of AURA_SURFACES) {
    it(`${rel} has no glass blur, rainbow hex, or decorative phosphor gradients`, () => {
      const src = readSrc(rel)
      for (const bad of AURA_FORBIDDEN) {
        expect(src, `${rel} still contains forbidden pattern: ${bad}`).not.toContain(bad)
      }
    })
  }

  it('TrajectoryChart overlays stay on-token (warn / call / put)', () => {
    const src = readSrc('components/TrajectoryChart.vue')
    expect(src).toMatch(/\.overlay\.vwap\s*\{\s*stroke:\s*var\(--warn\)/)
    expect(src).toMatch(/\.overlay\.ema9\s*\{\s*stroke:\s*var\(--call-hi\)/)
    expect(src).toMatch(/\.overlay\.ema21\s*\{\s*stroke:\s*var\(--put\)/)
  })

  it('SearchPalette uses a solid scrim, not frosted glass', () => {
    const src = readSrc('components/SearchPalette.vue')
    expect(src).not.toContain('backdrop-filter')
    expect(src).toMatch(/\.scrim\s*\{[^}]*background:\s*color-mix\(in srgb,\s*var\(--void\)/s)
  })

  it('FlowView standalone market-tape shell stays flat and instrument-like', () => {
    const src = readSrc('views/FlowView.vue')
    expect(src).toMatch(/\.flow-head\s*\{[^}]*border:\s*var\(--hair\) solid var\(--border-strong\)/s)
    expect(src).not.toContain('opportunity-row')
    expect(src).not.toMatch(/feed-beacon::before/)
  })
})
