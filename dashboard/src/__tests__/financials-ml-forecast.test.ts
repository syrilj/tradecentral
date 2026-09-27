import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DASH } from '@/format'
import {
  formatGearingUp,
  formatModelForecastScore,
  formatModelPredictedPrice,
  presentCaseRange,
  presentModelForecast,
  presentPriceScale,
  scaleLeftPct,
} from '@/financialsDisplay'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
// The Market surface is MarketView plus the cards it delegates to, so the
// markup contract is asserted against both.
const marketViewSource = [
  readFileSync(join(srcRoot, 'views', 'MarketView.vue'), 'utf8'),
  readFileSync(join(srcRoot, 'components', 'ModelForecastCard.vue'), 'utf8'),
].join('\n')
const routerSource = readFileSync(join(srcRoot, 'router.ts'), 'utf8')

describe('presentModelForecast vs Street consensus', () => {
  it('formats a ready model view without using Street targets', () => {
    const view = presentModelForecast({
      predicted_price: 48.25,
      forecast_score: 72.4,
      gearing_up_towards: 'product and capacity expansion',
      status: 'ok',
      label: 'what it should be',
    })
    expect(view.ready).toBe(true)
    expect(view.spotUsed).toBeNull()
    expect(view.timeframe).toBeNull()
    expect(view.cases.bear.price).toBeNull()
    expect(view.predictedPrice).toBe(48.25)
    expect(view.forecastScore).toBe(72.4)
    expect(view.gearingUpTowards).toBe('product and capacity expansion')
    expect(formatModelPredictedPrice(view.predictedPrice)).toBe('$48.25')
    expect(formatModelForecastScore(view.forecastScore)).toBe('72.4')
    expect(formatGearingUp(view.gearingUpTowards)).toBe('product and capacity expansion')
  })

  it('renders missing inputs as dash — never a fabricated zero score', () => {
    const view = presentModelForecast({
      predicted_price: 0,
      forecast_score: 0,
      gearing_up_towards: '',
      status: 'missing',
    })
    expect(view.ready).toBe(false)
    expect(view.predictedPrice).toBeNull()
    expect(view.forecastScore).toBeNull()
    expect(view.gearingUpTowards).toBeNull()
    expect(formatModelPredictedPrice(view.predictedPrice)).toBe(DASH)
    expect(formatModelForecastScore(view.forecastScore)).toBe(DASH)
    expect(formatGearingUp(view.gearingUpTowards)).toBe(DASH)
    expect(formatModelForecastScore(undefined)).toBe(DASH)
    expect(formatModelPredictedPrice(null)).toBe(DASH)
    expect(formatGearingUp('0')).toBe(DASH)
  })

  it('treats an absent payload as missing, not zero', () => {
    const view = presentModelForecast(undefined)
    expect(view.status).toBe('missing')
    expect(view.predictedPrice).toBeNull()
    expect(view.forecastScore).toBeNull()
    expect(formatModelForecastScore(view.forecastScore)).not.toBe('0.0')
    expect(formatModelForecastScore(view.forecastScore)).not.toBe('0')
  })
})

describe('Market Financials highlight + /quantitative-research', () => {
  it('registers /quantitative-research onto the Financials model highlight, not /', () => {
    expect(routerSource).toMatch(/path:\s*'\/quantitative-research'/)
    expect(routerSource).toMatch(/name:\s*'quantitative-research'/)
    expect(routerSource).toMatch(/tab:\s*'financials'/)
    expect(routerSource).toMatch(/highlight:\s*'model-forecast'/)
    expect(routerSource).not.toMatch(
      /path:\s*'\/quantitative-research'[\s\S]{0,200}redirect:\s*'\/'/,
    )
  })

  it('Financials markup highlights the internal what-it-should-be model view', () => {
    expect(marketViewSource).toContain('model-forecast-highlight')
    expect(marketViewSource).toContain('What it should be')
    expect(marketViewSource).toContain('Predicted price')
    expect(marketViewSource).toContain('Forecast score')
    expect(marketViewSource).toContain('Gearing up towards')
    expect(marketViewSource).toContain('Bear case')
    expect(marketViewSource).toContain('Bull case')
    expect(marketViewSource).toContain('Factors')
    expect(marketViewSource).toContain('mf-timeframe')
    expect(marketViewSource).toContain('formatModelPredictedPrice')
    expect(marketViewSource).toContain('formatModelForecastScore')
    expect(marketViewSource).toContain('formatGearingUp')
  })

  it('formats bull/bear cases and dashes missing case prices', () => {
    const ready = presentModelForecast({
      predicted_price: 144.47,
      forecast_score: 90,
      status: 'ok',
      timeframe: '18 months',
      cases: {
        bear: { price: 88.2, label: 'Bear', thesis: 'Growth slips.' },
        base: { price: 144.47, label: 'Base', thesis: 'Look-through.' },
        bull: { price: 210.1, label: 'Bull', thesis: 'Scale converts.' },
      },
      factors: [{ label: 'Revenue growth', display: '+45%', tone: 'pos' }],
    })
    expect(ready.timeframe).toBe('18 months')
    expect(ready.cases.bear.price).toBe(88.2)
    expect(ready.cases.bull.price).toBe(210.1)
    expect(ready.factors[0].display).toBe('+45%')
    const missing = presentModelForecast({
      status: 'missing',
      cases: { bear: { price: 0 }, bull: { price: 0 } },
    })
    expect(formatModelPredictedPrice(missing.cases.bear.price)).toBe(DASH)
    expect(formatModelPredictedPrice(missing.cases.bull.price)).toBe(DASH)
    expect(missing.factors).toEqual([])
  })
})

describe('mark vs predicted / Street target hit', () => {
  it('marks a prediction hit only when the live mark has reached the target', async () => {
    const { presentPredictionHit } = await import('../financialsDisplay')
    const hit = presentPredictionHit(70.98, 50.8)
    const open = presentPredictionHit(70.98, 78)
    const missing = presentPredictionHit(null, 78)
    expect(hit.hit).toBe(true)
    expect(hit.remainingPct).toBeNull()
    expect(open.hit).toBe(false)
    expect(open.remainingPct).toBeCloseTo(((78 - 70.98) / 70.98) * 100, 4)
    expect(missing.hit).toBeNull()
    expect(missing.remainingPct).toBeNull()
  })

  it('scales a case rail that includes prices below the live mark', () => {
    const scale = presentPriceScale([40, 70.98, 110, 160])
    expect(scale).not.toBeNull()
    expect(scale!.min).toBeLessThan(40)
    expect(scale!.max).toBeGreaterThan(160)
    const range = presentCaseRange({
      spot: 70.98,
      bear: 40,
      base: 110,
      bull: 160,
    })
    expect(range).not.toBeNull()
    expect(range!.marks.map((m) => m.key)).toEqual(['bear', 'spot', 'base', 'bull'])
    const bearPct = Number.parseFloat(range!.marks[0].pct)
    const spotPct = Number.parseFloat(range!.marks[1].pct)
    expect(bearPct).toBeLessThan(spotPct)
    expect(scaleLeftPct(0, scale)).toBeNull()
    expect(presentPriceScale([0, null])).toBeNull()
    expect(presentCaseRange({ spot: null, bear: null, base: null, bull: null })).toBeNull()
  })

  it('Financials markup draws the case rail and the overview chart includes case levels', () => {
    expect(marketViewSource).toContain('presentCaseRange')
    // Suffixed per surface (`-forecast` on the Forecast tab) so both cards can
    // mount without colliding; the stem is the stable hook.
    expect(marketViewSource).toContain('model-forecast-range')
    expect(marketViewSource).toContain('forecastLevels')
    expect(marketViewSource).toContain(':levels="mode === \'price\' ? forecastLevels : []"')
  })

  it('Forecast tab renders firm-level estimates and rating buckets from observed data', () => {
    expect(marketViewSource).toContain('analyst-estimates-table')
    expect(marketViewSource).toMatch(/forecast(?:\.|\?\.)estimates/)
    expect(marketViewSource).toContain('strong_sell')
    expect(marketViewSource).toContain('presentPredictionHit')
    expect(marketViewSource).toContain('signedPct')
    expect(marketViewSource).not.toMatch(/\+\$\{profile\.forecast\.upside_pct\}%/)
    expect(marketViewSource).not.toMatch(
      /recommendations\.(strong_buy|buy|hold|underperform|sell)\s*\?\?\s*0/,
    )
  })
})

// ============================================================================
// The Market tab must publish the numbers a reader needs to judge the mark:
// the hurdle it has to clear, how much of the model's input set the filings
// supplied, and where the price it is built on came from.
// ============================================================================
describe('model forecast is auditable on the Market tab', () => {
  const READY = {
    status: 'ok' as const,
    predicted_price: 129.36,
    forecast_score: 89.6,
    spot_used: 70.98,
    spot_source: 'live',
    timeframe: '24 months',
    timeframe_months: 24,
    expected_return: 0.8225,
    annualized_return: 0.35,
    cost_of_equity: 0.091,
    excess_annualized_return: 0.259,
    scenario_sigma: 0.66,
    lookthrough_growth: 0.8673,
    sustainable_growth: 0.5,
    observed_feature_count: 14,
    feature_count_total: 14,
  }

  it('carries the hurdle, coverage and provenance through the presenter', () => {
    const view = presentModelForecast(READY)
    expect(view.ready).toBe(true)
    expect(view.costOfEquity).toBeCloseTo(0.091, 6)
    expect(view.annualizedReturn).toBeCloseTo(0.35, 6)
    expect(view.excessAnnualizedReturn).toBeCloseTo(0.259, 6)
    expect(view.expectedReturn).toBeCloseTo(0.8225, 6)
    expect(view.scenarioSigma).toBeCloseTo(0.66, 6)
    expect(view.sustainableGrowth).toBeCloseTo(0.5, 6)
    expect(view.observedFeatureCount).toBe(14)
    expect(view.featureCountTotal).toBe(14)
    expect(view.spotSource).toBe('live')
  })

  it('never invents a hurdle or a return when the report is missing', () => {
    const view = presentModelForecast({ status: 'missing' })
    for (const val of [
      view.costOfEquity,
      view.annualizedReturn,
      view.excessAnnualizedReturn,
      view.expectedReturn,
      view.scenarioSigma,
      view.sustainableGrowth,
      view.observedFeatureCount,
      view.featureCountTotal,
    ]) {
      expect(val).toBeNull()
    }
    expect(view.ready).toBe(false)
    expect(formatModelPredictedPrice(view.predictedPrice)).toBe(DASH)
    expect(formatModelForecastScore(view.forecastScore)).toBe(DASH)
    expect(formatGearingUp(view.gearingUpTowards)).toBe(DASH)
  })

  it('renders the hurdle, coverage and mark provenance on the card', () => {
    expect(marketViewSource).toContain('Return vs hurdle')
    expect(marketViewSource).toContain('cost of equity')
    expect(marketViewSource).toContain('model-forecast-excess')
    expect(marketViewSource).toContain('model-forecast-coverage')
    expect(marketViewSource).toContain('model-forecast-implied-return')
    expect(marketViewSource).toContain('model-forecast-spot-source')
    // A placeholder price behind a published target has to be unmissable.
    expect(marketViewSource).toContain('Placeholder mark — not a live print')
    expect(marketViewSource).toContain('Growth capitalised')
    expect(marketViewSource).toContain('10th–90th percentile')
  })

  it('does not paint a bearish mark as a bullish target hit', () => {
    // "Mark has reached the predicted price" is good news only on an upside
    // call; on a markdown the same arithmetic means the downside has not run.
    expect(marketViewSource).toContain('Mark is still above the predicted price')
    expect(marketViewSource).toMatch(/bullish[\s\S]{0,120}Mark has reached the predicted price/)
  })

  it('keeps prose out of the nowrap chip utility so nothing truncates', () => {
    const card = readFileSync(join(srcRoot, 'components', 'ModelForecastCard.vue'), 'utf8')
    const template = card.slice(card.indexOf('<template>'), card.indexOf('</template>'))
    // `.label` is nowrap + ellipsis — fine for chips, wrong for sentences.
    expect(template).not.toMatch(/class="mf-note[^"]*\blabel\b/)
    expect(template).not.toMatch(/class="mf-sub[^"]*\blabel\b/)
  })

  it('shares one card between the Financials and Forecast tabs', () => {
    const view = readFileSync(join(srcRoot, 'views', 'MarketView.vue'), 'utf8')
    const mounts = view.match(/<ModelForecastCard/g) ?? []
    expect(mounts).toHaveLength(2)
    expect(view).toContain('id-suffix="-forecast"')
    // The old inline duplicate must be gone, or the two tabs drift again.
    expect(view).not.toContain('<div class="mf-metrics">')
  })
})
