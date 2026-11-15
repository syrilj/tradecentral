/**
 * /gamma — call resistance, absolute gamma, zero gamma, nearby support.
 *
 * Pure helpers cover the empty, error, and populated screen states. The
 * shipped source is gated on the route, the four reads, and the missing-data
 * copy so a zero cannot sneak back in as a placeholder.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { DASH, optGex, usd } from '@/format'
import {
  cleanSymbol,
  gammaResistancePath,
  ladderRows,
  normalizeMaxDte,
  readCards,
  reasonCopy,
  screenPhase,
  statusNotes,
  type GammaResistancePayload,
} from '@/gammaResistance'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

function payload(overrides: Partial<GammaResistancePayload> = {}): GammaResistancePayload {
  return {
    symbol: 'SPY',
    asof: '2026-11-14T15:00:00+00:00',
    stale: false,
    stale_reason: null,
    spot: 100,
    max_dte: 365,
    min_dte: 0,
    rate: 0.045,
    measurable: true,
    reason: null,
    absolute_gamma_m: 12.5,
    absolute_gamma_strike: 100,
    absolute_gamma_strike_m: 4.2,
    net_gamma_m: 3.1,
    call_gamma_m: 7.8,
    put_gamma_m: -4.7,
    regime: 'positive',
    call_resistance: {
      level: 105,
      distance: 5,
      distance_pct: 0.05,
      dollar_gamma_m: 2.4,
      abs_dollar_gamma_m: 2.4,
      share: 0.62,
      concentrated: true,
    },
    call_resistance_reason: null,
    zero_gamma: 98.5,
    zero_gamma_distance: -1.5,
    zero_gamma_distance_pct: -0.015,
    zero_gamma_side: 'above',
    zero_gamma_reason: null,
    nearby_support: {
      level: 95,
      distance: -5,
      distance_pct: -0.05,
      dollar_gamma_m: -1.8,
      abs_dollar_gamma_m: 1.8,
      share_of_peak: 0.4,
    },
    nearby_support_reason: null,
    put_wall: {
      level: 90,
      distance: -10,
      distance_pct: -0.1,
      dollar_gamma_m: -4.4,
      abs_dollar_gamma_m: 4.4,
    },
    by_strike: [
      {
        strike: 90,
        call_gex_m: 0.1,
        put_gex_m: -4.4,
        net_gex_m: -4.3,
        abs_gex_m: 4.5,
        call_oi: 10,
        put_oi: 800,
      },
      {
        strike: 95,
        call_gex_m: 0.2,
        put_gex_m: -1.8,
        net_gex_m: -1.6,
        abs_gex_m: 2,
        call_oi: 20,
        put_oi: 400,
      },
      {
        strike: 100,
        call_gex_m: 2,
        put_gex_m: -2.2,
        net_gex_m: -0.2,
        abs_gex_m: 4.2,
        call_oi: 100,
        put_oi: 100,
      },
      {
        strike: 105,
        call_gex_m: 2.4,
        put_gex_m: -0.2,
        net_gex_m: 2.2,
        abs_gex_m: 2.6,
        call_oi: 500,
        put_oi: 20,
      },
    ],
    quality: { contracts_measured: 8, contracts_in: 9, revalue_coverage: 1 },
    unit: 'usd_millions_per_1pct',
    sign_convention: 'call_positive_put_negative',
    ...overrides,
  }
}

describe('/gamma registration', () => {
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')
  const apiSrc = source('api.ts')
  const iconSrc = source('components/AppIcon.vue')
  const viewSrc = source('views/GammaResistanceView.vue')

  it('registers /gamma on its own view', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/gamma['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]gamma['"]/)
    expect(routerSrc).toContain("import('@/views/GammaResistanceView.vue')")
    expect(routerSrc).toMatch(/title:\s*['"]Gamma['"]/)
  })

  it('adds one primary-nav destination with its own glyph', () => {
    const primary = appSrc.match(/const primaryNav = \[\s*([\s\S]*?)\] as const/)?.[1] ?? ''
    expect(primary).toContain("name: 'gamma'")
    expect(primary).toContain("title: 'Gamma'")
    expect(primary).toContain("hint: 'Resistance · flip · support'")
    const icon = primary.match(/name: 'gamma'[\s\S]*?icon: '([a-z-]+)'/)?.[1]
    expect(icon).toBe('gamma')
    expect(iconSrc).toContain(`name === '${icon}'`)
    expect([...appSrc.matchAll(/name:\s*'gamma'/g)]).toHaveLength(1)
  })

  it('fetches /api/gamma/resistance through the typed client', () => {
    expect(apiSrc).toContain('gammaResistance:')
    expect(apiSrc).toContain('gammaResistancePath(symbol, maxDte)')
    expect(gammaResistancePath('spy', 30)).toBe('/api/gamma/resistance?symbol=SPY&max_dte=30')
    expect(gammaResistancePath('bad symbol', 3)).toBe(
      '/api/gamma/resistance?symbol=BADSYMBOL&max_dte=365',
    )
  })

  it('renders empty, error, and populated states without a fake zero', () => {
    expect(viewSrc).toContain('data-testid="gamma-error"')
    expect(viewSrc).toContain('data-testid="gamma-empty"')
    expect(viewSrc).toContain('data-testid="gamma-symbol"')
    expect(viewSrc).toContain('Missing inputs stay blank')
    expect(viewSrc).not.toContain('GammaExposureMap')
    expect(viewSrc).not.toContain('StrikeGammaExposureChart')
    const mathSrc = source('gammaResistance.ts')
    expect(mathSrc).toContain("label: 'Call resistance'")
    expect(mathSrc).toContain("label: 'Absolute gamma'")
    expect(mathSrc).toContain("label: 'Zero gamma'")
    expect(mathSrc).toContain("label: 'Nearby support'")
    for (const id of ['call_resistance', 'absolute_gamma', 'zero_gamma', 'nearby_support']) {
      expect(viewSrc).toContain('card.id')
      expect(mathSrc).toContain(`id: '${id}'`)
    }
  })
})

describe('screen phase', () => {
  it('stays on loading until a payload or an error arrives', () => {
    expect(screenPhase({ loading: true, error: null, payload: null })).toBe('loading')
    expect(screenPhase({ loading: false, error: null, payload: null })).toBe('loading')
  })

  it('shows an error when the chain cannot be loaded', () => {
    expect(
      screenPhase({
        loading: false,
        error: 'No options chain is available for ZZZZ.',
        payload: null,
      }),
    ).toBe('error')
  })

  it('shows empty when the chain is present and nothing is measurable', () => {
    const empty = payload({
      measurable: false,
      reason: 'outside_dte',
      absolute_gamma_m: null,
      net_gamma_m: null,
      zero_gamma: null,
      call_resistance: null,
      nearby_support: null,
      regime: 'unmeasured',
    })
    expect(screenPhase({ loading: false, error: null, payload: empty })).toBe('empty')
    expect(reasonCopy(empty.reason)).toBe('No contracts fall inside this expiry window.')
  })

  it('keeps a populated book on screen during a refresh', () => {
    const book = payload()
    expect(screenPhase({ loading: true, error: null, payload: book })).toBe('populated')
  })
})

describe('read cards', () => {
  it('formats the four reads from a measured book', () => {
    const cards = readCards(payload())
    expect(cards.map((card) => card.id)).toEqual([
      'call_resistance',
      'absolute_gamma',
      'zero_gamma',
      'nearby_support',
    ])
    expect(cards.every((card) => card.missing === false)).toBe(true)
    expect(cards[0].value).toBe(usd(105, 2))
    expect(cards[1].value).toBe(optGex(12.5))
    expect(cards[1].value).not.toBe(DASH)
    expect(cards[2].value).toBe(usd(98.5, 2))
    expect(cards[3].value).toBe(usd(95, 2))
    expect(cards[3].note).toContain(usd(90, 2))
    expect(cards[2].note).toContain('above the flip')
  })

  it('withholds each missing read instead of printing zero', () => {
    const cards = readCards(
      payload({
        call_resistance: null,
        call_resistance_reason: 'no_calls_above_spot',
        absolute_gamma_m: null,
        absolute_gamma_strike: null,
        zero_gamma: null,
        zero_gamma_side: null,
        zero_gamma_reason: 'iv_coverage_insufficient',
        nearby_support: null,
        nearby_support_reason: 'no_put_gamma_inside_band',
        regime: 'unmeasured',
        reason: 'unmeasured',
      }),
    )
    for (const card of cards) {
      expect(card.missing).toBe(true)
      expect(card.value).toBeNull()
      expect(card.missingReason).not.toMatch(/\$0/)
      expect(card.missingReason.length).toBeGreaterThan(0)
    }
    expect(cards[0].missingReason).toBe('No call gamma above spot.')
    expect(cards[2].missingReason).toContain('implied vol')
    expect(cards[3].missingReason).toContain('8%')
    expect(cards[3].note).toContain(usd(90, 2))
  })

  it('names a stale chain without erasing the reads', () => {
    const book = payload({ stale: true, stale_reason: 'chain_older_than_20h' })
    const notes = statusNotes({ error: null, payload: book })
    expect(notes).toEqual([{ kind: 'stale', text: 'The chain is more than 20 hours old.' }])
    expect(readCards(book).every((card) => card.missing === false)).toBe(true)
  })

  it('surfaces a failed refresh beside the last book, and an error alone when there is none', () => {
    expect(statusNotes({ error: 'backend unreachable', payload: null })).toEqual([
      { kind: 'error', text: 'backend unreachable' },
    ])
    const notes = statusNotes({
      error: 'backend unreachable',
      payload: payload({ stale: true, stale_reason: 'asof_missing' }),
    })
    expect(notes.map((note) => note.kind)).toEqual(['error', 'stale'])
  })
})

describe('ladder and inputs', () => {
  it('keeps the marked strikes and drops a book with no spot', () => {
    const book = payload()
    const rows = ladderRows(book.by_strike, book.spot, { call: 105, zero: 98.5, support: 95 })
    expect(rows.map((row) => row.strike)).toEqual([90, 95, 100, 105])
    expect(ladderRows(book.by_strike, null, { call: 105, zero: null, support: null })).toEqual([])
  })

  it('accepts only the expiry windows the screen offers', () => {
    expect(normalizeMaxDte('30')).toBe(30)
    expect(normalizeMaxDte(7)).toBe(7)
    expect(normalizeMaxDte('0')).toBe(365)
    expect(normalizeMaxDte(undefined)).toBe(365)
    expect(cleanSymbol(' qqq ')).toBe('QQQ')
    expect(cleanSymbol('')).toBe('SPY')
  })
})
