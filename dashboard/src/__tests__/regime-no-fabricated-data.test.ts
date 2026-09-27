/**
 * Guard: the Regime workstation must never render invented market data.
 *
 * This repo has a documented, recurring defect class in which unavailable data
 * is silently replaced with plausible-looking literals, so a trader cannot tell
 * a real reading from a placeholder. See
 * `docs/audits/2026-09-01-vwap-orderflow-evaluation.md`.
 *
 * On 2026-09-01 the Regime view and the charts it feeds carried seven such
 * instances at once:
 *
 *   1. `expiryFlowRows` returned five hardcoded expiries ('May 17', $412.5M ...)
 *      whenever the API had no `gex_by_expiry`.
 *   2. `strikeOiRows` manufactured open interest from gamma exposure with an
 *      850x magic multiplier.
 *   3. `timeSeriesPoints` fell back to a `525` spot price for any symbol.
 *   4. `timeSeriesPoints` published `total_gex_m * 25` as an order-flow
 *      "volume delta" -- a quantity this repo has no data for at all.
 *   5. `NetGammaSpotTimeSeries` synthesised an entire intraday session from
 *      sine waves when handed no points, silently overwriting an honest empty.
 *   6. `StrikeOpenInterestChart` invented an eleven-strike open-interest ladder
 *      using `Math.random()`, so the fake numbers changed on every render.
 *   7. `StrikeGammaExposureChart` did the same for the dealer-gamma profile.
 *
 * Each fix is only as durable as this test, because the failure mode is silent:
 * the charts render perfectly, and nothing in the UI says the numbers are made
 * up. A unit test asserting on rendered output would not catch a regression
 * either, since fabricated data looks exactly like real data.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const root = join(__dirname, '..')

/**
 * Trading surfaces only.
 *
 * `GexFlowVisual.vue` is deliberately excluded: it is a marketing/paper
 * surface used solely by `LandingView.vue`, and its own conformance test
 * (`gex-flow-visual-conformance.test.ts`) documents that its illustrative
 * numbers are intentional. It never renders as a data readout.
 */
const TRADING_SURFACES = [
  'views/RegimeView.vue',
  'components/NetGammaSpotTimeSeries.vue',
  'components/StrikeOpenInterestChart.vue',
  'components/StrikeGammaExposureChart.vue',
  'components/NetFlowByExpiryChart.vue',
]

const read = (rel: string) => readFileSync(join(root, rel), 'utf8')

/** Strip comments so prose *describing* a removed defect does not trip the guard. */
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
    .replace(/<!--[\s\S]*?-->/g, '')
}

describe('Regime workstation — no fabricated market data', () => {
  for (const rel of TRADING_SURFACES) {
    describe(rel, () => {
      const code = stripComments(read(rel))

      it('does not seed prices or strikes from a hardcoded 525-ish spot', () => {
        // `?? 525`, `: 525,`, `|| 525` — a plausible index level standing in
        // for an unknown spot. Wrong by an order of magnitude on most tickers.
        const hits = code.match(/(\?\?|\|\||:)\s*525(\.\d+)?\b/g) ?? []
        expect(hits, `${rel} defaults a spot/price to 525:\n${hits.join('\n')}`).toEqual([])
      })

      it('does not invent data with Math.random()', () => {
        // Randomised placeholder data is the worst case: it is not even stable
        // between renders, so two people reading the same screen disagree.
        const hits = code.match(/Math\.random\s*\(/g) ?? []
        expect(hits, `${rel} generates data with Math.random()`).toEqual([])
      })

      it('does not hardcode calendar expiry labels', () => {
        // 'May 17', 'Jun 21', '525C', '520P' — invented contract identifiers.
        const hits =
          code.match(
            /['"`](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\b[^'"`]*['"`]/g,
          ) ?? []
        const walls = code.match(/['"`]\d{3,4}[CP]['"`]/g) ?? []
        const all = [...hits, ...walls]
        expect(all, `${rel} hardcodes expiry/strike labels:\n${all.join('\n')}`).toEqual([])
      })

      it('has no fallback row/point generator standing in for absent data', () => {
        const hits = code.match(/\bfallback(Rows|Points|Series|Data)\b/g) ?? []
        expect(hits, `${rel} defines a fabricated-data fallback: ${hits.join(', ')}`).toEqual([])
      })
    })
  }

  it('RegimeView returns empty arrays, not literal rows, when the API has no data', () => {
    const code = stripComments(read('views/RegimeView.vue'))

    // The exact fabricated figures that shipped, pinned so they cannot return.
    for (const literal of ['412.5', '99.9', '312.6', '185.3', '122.1', '76.4']) {
      expect(code, `RegimeView still contains fabricated GEX figure ${literal}`).not.toContain(
        literal,
      )
    }

    // Open interest is a reported quantity; it cannot be derived from gamma.
    expect(code, 'RegimeView still synthesises open interest from gamma exposure').not.toMatch(
      /call_gex_m\s*\|\|\s*\d+\)\s*\*\s*\d+/,
    )

    // There is no volume-delta series anywhere in this repo's data.
    expect(code, 'RegimeView still publishes a fabricated volumeDelta').not.toMatch(
      /volumeDelta:\s*[a-zA-Z_.]*gex[a-zA-Z_.]*\s*\*/i,
    )
  })

  it('NetGammaSpotTimeSeries renders an empty state instead of a synthetic session', () => {
    const code = stripComments(read('components/NetGammaSpotTimeSeries.vue'))
    // The synthetic series was built from a hardcoded clock-time array.
    expect(code, 'a hardcoded intraday clock array is back').not.toMatch(/'09:30'|"09:30"/)
    // ...and shaped with trigonometry.
    expect(code, 'trigonometric price/volume synthesis is back').not.toMatch(/Math\.sin\s*\(/)
    // It must have an explicit empty branch.
    expect(code, 'no empty state guard').toMatch(/v-if="!hasData"/)
  })

  it('both strike charts guard their chart body on having real rows', () => {
    for (const rel of [
      'components/StrikeOpenInterestChart.vue',
      'components/StrikeGammaExposureChart.vue',
    ]) {
      const code = read(rel)
      expect(code, `${rel} has no hasRows guard`).toMatch(/const hasRows = computed/)
      expect(code, `${rel} does not gate its svg on hasRows`).toMatch(/v-if="!hasRows"/)
    }
  })
})
