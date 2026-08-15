import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DASH, signedPct } from '@/format'
import {
  UNMEASURED,
  freshnessLabel,
  presentSetupRows,
  qlibAlignmentLabel,
  sellSourceLabel,
  setupCalculatorQuery,
  setupsFeedRequest,
  spotRelativeSellCopy,
  suggestionStabilityCopy,
  suggestedRightLabel,
  suggestedRightTokenClass,
  unmeasured,
} from '@/suggestDisplay'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')

describe('suggest display helpers (shipped)', () => {
  it('labels a suggested right or leaves it unmeasured', () => {
    expect(suggestedRightLabel('call')).toBe('CALL')
    expect(suggestedRightLabel('PUT')).toBe('PUT')
    expect(suggestedRightLabel('watch')).toBe('WATCH')
    expect(suggestedRightLabel('blocked')).toBe('BLOCKED')
    expect(suggestedRightLabel(null)).toBe(UNMEASURED)
    expect(suggestedRightLabel('')).toBe(UNMEASURED)
    expect(suggestedRightLabel('maybe')).toBe(UNMEASURED)
  })

  it('maps call/put onto option-right tokens, not long/short chrome', () => {
    expect(suggestedRightTokenClass('call')).toBe('token-call')
    expect(suggestedRightTokenClass('put')).toBe('token-put')
    expect(suggestedRightTokenClass('watch')).toBe('token-warn')
    expect(suggestedRightTokenClass('blocked')).toBe('token-unsigned')
    expect(suggestedRightTokenClass(null)).toBe('token-unsigned')
    expect(suggestedRightTokenClass('call')).not.toBe('token-long')
    expect(suggestedRightTokenClass('put')).not.toBe('token-short')
  })

  it('renders a spot-relative sell from the shipped GEX fields, or —', () => {
    expect(spotRelativeSellCopy({
      sell: 108,
      spot: 100,
      sellRelPct: 0.08,
      sellSource: 'call_wall',
    })).toBe('$108.00  +8.0%  call wall')
    expect(spotRelativeSellCopy({
      sell: 94,
      sellRelPct: -0.06,
      sellSource: 'put_wall',
    })).toBe(`$94.00  ${signedPct(-6, 1)}  put wall`)
    expect(spotRelativeSellCopy({ sell: null, sellRelPct: 0.08, sellSource: 'call_wall' })).toBe(DASH)
    expect(spotRelativeSellCopy({ sell: Number.NaN })).toBe(UNMEASURED)
    expect(sellSourceLabel(null)).toBe(UNMEASURED)
  })

  it('names freshness and qlib alignment without fabricating scores', () => {
    expect(freshnessLabel('FRESH', true)).toBe('FRESH')
    expect(freshnessLabel('STALE_OR_PROXY', false)).toBe('STALE')
    expect(freshnessLabel(null, null)).toBe(UNMEASURED)
    expect(qlibAlignmentLabel('confirms')).toBe('CONFIRMS')
    expect(qlibAlignmentLabel('conflicts')).toBe('CONFLICTS')
    expect(qlibAlignmentLabel('unmeasured')).toBe(UNMEASURED)
    expect(qlibAlignmentLabel(null)).toBe(UNMEASURED)
    expect(unmeasured(null)).toBe(UNMEASURED)
    expect(unmeasured(undefined)).toBe(UNMEASURED)
    expect(unmeasured(Number.NaN)).toBe(UNMEASURED)
    expect(unmeasured(12)).toBe('12')
  })

  it('does not cap the Setups feed — coverage must match the unsliced union', () => {
    expect(setupsFeedRequest(false)).toEqual({})
    expect(setupsFeedRequest(true)).toEqual({ force: true })
    expect(setupsFeedRequest(false)).not.toHaveProperty('limit')
    expect(setupsFeedRequest(true)).not.toHaveProperty('limit')
  })

  it('shows direction and contract stability without implying probability', () => {
    expect(suggestionStabilityCopy({
      right: 'call',
      review_label: 'PAPER',
      direction_observations: 3,
      direction_required: 3,
      direction_stable: true,
      contract_plan: { stability_observations: 2, stability_required: 3, stable: false },
    })).toBe('PAPER · DIR 3/3 · CTR 2/3')
    expect(suggestionStabilityCopy({
      right: 'put',
      direction_observations: 1,
      direction_required: 3,
      direction_churned: true,
    })).toBe('FLIPPED · DIR 1/3')
    expect(suggestionStabilityCopy({ right: 'blocked' })).toBe(DASH)
  })

  it('uses review quality rank before call/put grouping', () => {
    const view = presentSetupRows({ rows: [
      { symbol: 'LOWCALL', suggestion: { right: 'call', review_rank: 2, review_score: 30 } },
      { symbol: 'HIGHPUT', suggestion: { right: 'put', review_rank: 1, review_score: 75 } },
    ] })
    expect(view.rows.map((row) => row.symbol)).toEqual(['HIGHPUT', 'LOWCALL'])
  })

  it('keeps call/put rows that sit after forty blocked names and recounts coverage from those rows', () => {
    const blocked = Array.from({ length: 42 }, (_, i) => ({
      symbol: `BLK${i}`,
      suggestion: { right: 'blocked' as const },
    }))
    const late = [
      { symbol: 'CVS', suggestion: { right: 'put' as const } },
      { symbol: 'UBER', suggestion: { right: 'put' as const } },
      { symbol: 'ANET', suggestion: { right: 'call' as const } },
      { symbol: 'BKNG', suggestion: { right: 'call' as const } },
    ]
    const payload = {
      available: true,
      coverage: { union_symbols: 46, suggested_call: 2, suggested_put: 2 },
      rows: [...blocked, ...late],
    }
    const slicedAway = payload.rows.slice(0, 40)
    expect(slicedAway.some((row) => row.symbol === 'CVS')).toBe(false)
    expect(slicedAway.some((row) => row.symbol === 'UBER')).toBe(false)

    const view = presentSetupRows(payload)
    const symbols = view.rows.map((row) => row.symbol)
    expect(symbols).toContain('CVS')
    expect(symbols).toContain('UBER')
    expect(symbols).toContain('ANET')
    expect(symbols).toContain('BKNG')
    expect(symbols.indexOf('CVS')).toBeLessThan(symbols.indexOf('BLK0'))
    expect(view.coverage.union_symbols).toBe(payload.rows.length)
    expect(view.coverage.suggested_put).toBe(2)
    expect(view.coverage.suggested_call).toBe(2)
    expect(view.coverage.suggested_blocked).toBe(42)
  })
})

describe('setup calculator query', () => {
  it('prefills a long call from the contract plan without inventing numbers', () => {
    expect(setupCalculatorQuery({
      symbol: 'spy',
      right: 'call',
      spot: 500,
      strike: 510,
      dte: 21,
      vol: 0.18,
      premium: 6.2,
    })).toEqual({
      strategy: 'long_call',
      symbol: 'SPY',
      spot: '500',
      strike: '510',
      dte: '21',
      vol: '0.18',
      premium: '6.2',
    })
  })

  it('omits missing fields and maps puts', () => {
    expect(setupCalculatorQuery({ right: 'put', symbol: 'QQQ' })).toEqual({
      strategy: 'long_put',
      symbol: 'QQQ',
    })
  })
})

describe('Setups tab is reachable without a private palette or order ticket', () => {
  const router = readFileSync(join(srcRoot, 'router.ts'), 'utf8')
  const app = readFileSync(join(srcRoot, 'App.vue'), 'utf8')
  const view = readFileSync(join(srcRoot, 'views', 'SuggestView.vue'), 'utf8')
  const risk = readFileSync(join(srcRoot, 'components', 'SetupRiskPanel.vue'), 'utf8')
  const api = readFileSync(join(srcRoot, 'api.ts'), 'utf8')

  it('registers a dedicated route and a specialist nav entry', () => {
    expect(router).toMatch(/path:\s*'\/suggest'/)
    expect(router).toMatch(/name:\s*'suggest'/)
    expect(router).toContain("import('@/views/SuggestView.vue')")
    expect(app).toContain("name: 'suggest'")
    expect(app).toContain("title: 'Setups'")
    expect(app).toMatch(/const primaryNav = \[[^\]]*name: 'suggest'/s)
    expect(app).not.toMatch(/const marketTools = \[[^\]]*name: 'suggest'/s)
  })

  it('consumes Flow-derived suggestion data and shared tokens', () => {
    expect(view).toContain('api.flowSuggestions')
    expect(view).toContain('setupsFeedRequest')
    expect(view).toContain('presentSetupRows')
    expect(view).not.toMatch(/limit:\s*40/)
    expect(view).toContain('spotRelativeSellCopy')
    expect(view).toContain('suggestedRightLabel')
    expect(view).toContain('token-call')
    expect(view).toContain('token-put')
    expect(view).toContain('var(--call)')
    expect(view).toContain('var(--put)')
    expect(view).toContain('Panel')
    expect(view).toContain('SetupRiskPanel')
    expect(view).toContain("filter = ref<RightFilter>('SETUPS')")
    expect(view).toContain("'NEEDS DATA'")
    expect(view).toContain('MARKET CLOSED · PLANNING')
    expect(view).toContain('Why live entry is not ready')
    expect(view).toContain('PAPER ACTION · UNSIZED')
    expect(view).toContain('PAPER BUY')
    expect(risk).toContain('Debit / premium')
    expect(risk).toContain('referenceDebit')
    expect(view).toContain('Specific contract plan')
    expect(view).toContain('setupCalculatorQuery')
    expect(view).toContain("name: 'calculator'")
    expect(view).toContain('Play card')
    expect(view).toContain('Max loss / 1')
    expect(view).toContain('Provider did not supply')
    expect(risk).toContain('Open portfolio risk')
    expect(risk).toContain('Max contracts')
    expect(risk).toContain('Planning size only')
    expect(api).toContain('/api/options/suggest')
  })

  it('does not ship a broker ticket or a private neon palette', () => {
    expect(view.toLowerCase()).not.toContain('submit order')
    expect(view.toLowerCase()).not.toContain('place order')
    expect(view.toLowerCase()).not.toContain('broker')
    expect(view).not.toMatch(/linear-gradient\(/)
    expect(view).not.toMatch(/#00ff|#39ff|#7f00ff|#ff00ff/i)
    expect(view).toContain('Research template')
    expect(view).toContain('No order ticket')
  })
})
