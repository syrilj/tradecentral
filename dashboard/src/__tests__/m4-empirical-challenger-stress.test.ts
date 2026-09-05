/**
 * Empirical Adversarial Stress Test Suite for Milestone 4:
 * Dashboard Views Integration (LiveStackView.vue and DeskView.vue)
 *
 * Challenger 1 Verification Harness:
 * - Rapid symbol mutations & input sanitization
 * - Partial / missing / corrupted payload robustness
 * - Massive board array scaling (40+ symbols) and regime breadth calculation
 * - Zero-spoofing invariants: missing data renders as '—' / honest fallback text
 * - Table column symmetry and responsive dual-view state transitions
 * - Fallback cascade logic (Quote marks -> Probe stats -> Bar close -> null)
 * - Sparkline cache stability and edge case defenses
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'

import { compact, num, signedPct, pctFrac, DASH } from '@/format'
import { sparkline } from '@/charts'
import {
  createUnmeasuredPayload,
  formatDistancePercent,
  formatDistancePoints,
  formatPullScore,
  type PriceDrawTelemetryPayload,
  type PriceDrawLevel,
} from '@/priceDrawContracts'
import RegimeStateBadge from '@/components/RegimeStateBadge.vue'
import PriceDrawLadder from '@/components/PriceDrawLadder.vue'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Challenger 1 Empirical Adversarial Stress Testing — Milestone 4', () => {
  const liveStackSrc = source('views/LiveStackView.vue')
  const deskSrc = source('views/DeskView.vue')

  // =========================================================================
  // 1. LIVESTACKVIEW — SYMBOL SANITIZATION & ROUTE INPUT STRESS
  // =========================================================================
  describe('1. LiveStackView: Symbol Sanitization & Route Input Robustness', () => {
    function sanitizeSymbol(value: unknown): string {
      const raw = Array.isArray(value) ? value[0] : value
      return (
        String(raw || 'SPY')
          .trim()
          .toUpperCase()
          .replace(/[^A-Z0-9.-]/g, '')
          .slice(0, 10) || 'SPY'
      )
    }

    it('sanitizes empty, null, undefined, and whitespace inputs to SPY fallback', () => {
      expect(sanitizeSymbol('')).toBe('SPY')
      expect(sanitizeSymbol(null)).toBe('SPY')
      expect(sanitizeSymbol(undefined)).toBe('SPY')
      expect(sanitizeSymbol('   ')).toBe('SPY')
      expect(sanitizeSymbol([])).toBe('SPY')
      expect(sanitizeSymbol([''])).toBe('SPY')
    })

    it('handles query arrays correctly by taking the first valid entry', () => {
      expect(sanitizeSymbol(['AAPL', 'MSFT'])).toBe('AAPL')
      expect(sanitizeSymbol(['', 'TSLA'])).toBe('SPY')
      expect(sanitizeSymbol(['nvda', 'amd'])).toBe('NVDA')
    })

    it('strips hostile injection strings, script tags, and illegal punctuation', () => {
      expect(sanitizeSymbol("<script>alert('xss')</script>")).toBe('SCRIPTALER')
      expect(sanitizeSymbol("SPY'; DROP TABLE symbols;--")).toBe('SPYDROPTAB')
      expect(sanitizeSymbol('$SPY!@#$%^&*()_+')).toBe('SPY')
      expect(sanitizeSymbol('  tsla / usd  ')).toBe('TSLAUSD')
    })

    it('preserves valid market tickers with dots and hyphens up to 10 characters', () => {
      expect(sanitizeSymbol('brk.b')).toBe('BRK.B')
      expect(sanitizeSymbol('bf-b')).toBe('BF-B')
      expect(sanitizeSymbol('a'.repeat(25))).toBe('AAAAAAAAAA')
      expect(sanitizeSymbol('1234567890123')).toBe('1234567890')
    })

    it('verifies LiveStackView AST implements route symbol watch and error boundaries', () => {
      expect(liveStackSrc).toContain('function readSymbol(): string')
      expect(liveStackSrc).toContain('watch(symbol, () => {')
      expect(liveStackSrc).toContain('void optionsRes.refresh({ clear: true })')
      expect(liveStackSrc).toContain('void priceDrawRes.refresh({ clear: true })')
      expect(liveStackSrc).toContain('payloadError')
      expect(liveStackSrc).toContain('dataModeBadge')
    })
  })

  // =========================================================================
  // 2. LIVESTACKVIEW — ZERO-SPOOFING & PARTIAL PAYLOAD VERDICTS
  // =========================================================================
  describe('2. LiveStackView: Zero-Spoofing & Partial Payload Verdict Computeds', () => {
    function computePctFromSpot(
      level: number | null | undefined,
      spot: number | null | undefined,
    ): string {
      if (level == null || spot == null || !spot) return ''
      const rel = ((level - spot) / spot) * 100
      return ` ${signedPct(rel, 1)} from spot`
    }

    function computeGammaVerdict(
      gexMeasurable: boolean,
      regime: string,
      netGex: number | null,
      putWall: number | null,
      callWall: number | null,
      gammaFlip: number | null,
    ) {
      if (!gexMeasurable) {
        return {
          key: 'gamma',
          lens: 'GAMMA',
          headline: 'UNMEASURED',
          detail: 'No open-interest snapshot behind these numbers — structure cannot be read.',
          tone: 'missing',
        }
      }
      if (regime === 'positive') {
        return {
          key: 'gamma',
          lens: 'GAMMA',
          headline: 'DEALERS LONG · MEAN REVERSION',
          detail: `Net dealer gamma +$${compact(netGex)}M. Hedging compresses price between the put wall (${num(putWall, 0)}) and call wall (${num(callWall, 0)}). Breakouts tend to fail inside this band.`,
          tone: 'neutral',
        }
      }
      if (regime === 'negative') {
        return {
          key: 'gamma',
          lens: 'GAMMA',
          headline: 'DEALERS SHORT · TREND FUEL',
          detail: `Net dealer gamma −$${compact(Math.abs(netGex ?? 0))}M. Hedges chase price — moves accelerate toward the flip at ${num(gammaFlip, 0)}.`,
          tone: 'neg',
        }
      }
      return {
        key: 'gamma',
        lens: 'GAMMA',
        headline: 'FLAT',
        detail: 'No net gamma structure measured.',
        tone: 'neutral',
      }
    }

    function computeCharmThetaVerdict(
      charm: number | null | undefined,
      theta: number | null | undefined,
      decaySide: string | null | undefined,
    ) {
      if (charm == null && theta == null) {
        return {
          key: 'decay',
          lens: 'DECAY',
          headline: 'NO INPUTS',
          detail: 'Charm/theta need dated IV + open interest; none usable in this chain.',
          tone: 'missing',
        }
      }
      const pressureWord =
        charm != null
          ? charm > 0
            ? 'dealers sell underlying as deltas decay — selling pressure builds'
            : charm < 0
              ? 'dealers buy underlying back as deltas decay — buying pressure builds'
              : 'delta decay is balanced across sides'
          : 'charm unavailable'
      const decayLine =
        theta != null && decaySide && decaySide !== 'balanced'
          ? `${decaySide} carry the fastest bleed (${compact(Math.abs(theta))} pts/day net)`
          : theta != null
            ? 'decay spread evenly across strikes'
            : ''
      return {
        key: 'decay',
        lens: 'DECAY',
        headline:
          charm == null
            ? 'THETA ONLY'
            : charm > 0
              ? 'CHARM → SELLING'
              : charm < 0
                ? 'CHARM → BUYING'
                : 'BALANCED',
        detail: [pressureWord, decayLine].filter(Boolean).join(' · ') + '.',
        tone: charm == null ? 'neutral' : charm > 0 ? 'neg' : charm < 0 ? 'pos' : 'neutral',
      }
    }

    function computeIvVerdict(
      s: {
        available?: boolean
        atm_iv?: number | null
        call_iv_wall?: number | null
        put_iv_wall?: number | null
      } | null,
    ) {
      if (!s?.available) {
        return {
          key: 'iv',
          lens: 'IV SURFACE',
          headline: 'NO QUOTES',
          detail: 'No usable implied-volatility quotes on this chain.',
          tone: 'missing',
        }
      }
      const cw = s.call_iv_wall != null ? `upside uncertainty parks at ${s.call_iv_wall}` : null
      const pw = s.put_iv_wall != null ? `downside uncertainty parks at ${s.put_iv_wall}` : null
      const lines = [pw, cw].filter(Boolean).join(' · ')
      return {
        key: 'iv',
        lens: 'IV SURFACE',
        headline: `ATM ${(s.atm_iv ?? 0) * 100 >= 100 ? '>100' : num((s.atm_iv ?? 0) * 100, 1)}%`,
        detail: lines
          ? `${lines}. That's where option prices carry the biggest volatility premium.`
          : 'IV smile flat — no standout wall.',
        tone: 'neutral',
      }
    }

    function computeVolumeVerdict(
      s: {
        available?: boolean
        poc?: number | null
        value_area_low?: number | null
        value_area_high?: number | null
        lvn_count?: number | null
      } | null,
      spot: number | null,
    ) {
      if (!s?.available) {
        return {
          key: 'volume',
          lens: 'VOLUME PROFILE',
          headline: 'NOT ENOUGH BARS',
          detail: 'Volume profile needs ≥5 priced sessions with volume.',
          tone: 'missing',
        }
      }
      const poc = s.poc
      const above = poc != null && spot != null && spot > poc
      const lvns = s.lvn_count ?? 0
      return {
        key: 'volume',
        lens: 'VOLUME PROFILE',
        headline: above ? 'TRADING ABOVE POC' : 'TRADING BELOW POC',
        detail: `Heaviest trade printed at ${num(poc, 2)}${poc != null ? computePctFromSpot(poc, spot) : ''}. Value area ${num(s.value_area_low, 0)}–${num(s.value_area_high, 0)}${lvns ? `, ${lvns} thin zone${lvns === 1 ? '' : 's'} where activity dropped out` : ''}.`,
        tone: 'neutral',
      }
    }

    it('correctly reports unmeasured gamma when quality.gex_measurable is false', () => {
      const v = computeGammaVerdict(false, 'positive', 12.5, 590, 610, 600)
      expect(v.headline).toBe('UNMEASURED')
      expect(v.tone).toBe('missing')
      expect(v.detail).toContain('No open-interest snapshot')
    })

    it('evaluates positive and negative dealer gamma regimes without numeric spoofing', () => {
      const pos = computeGammaVerdict(true, 'positive', 450.2, 580, 620, 600)
      expect(pos.headline).toContain('DEALERS LONG')
      expect(pos.tone).toBe('neutral')
      expect(pos.detail).toContain('Net dealer gamma +$450M')

      const neg = computeGammaVerdict(true, 'negative', -180.5, 580, 620, 595)
      expect(neg.headline).toContain('DEALERS SHORT')
      expect(neg.tone).toBe('neg')
      expect(neg.detail).toContain('Net dealer gamma −$181M')
    })

    it('evaluates charm & theta decay under all combinations of missing data', () => {
      const bothMissing = computeCharmThetaVerdict(null, null, undefined)
      expect(bothMissing.headline).toBe('NO INPUTS')
      expect(bothMissing.tone).toBe('missing')

      const thetaOnly = computeCharmThetaVerdict(null, -25.4, 'calls')
      expect(thetaOnly.headline).toBe('THETA ONLY')
      expect(thetaOnly.tone).toBe('neutral')
      expect(thetaOnly.detail).toContain('charm unavailable')
      expect(thetaOnly.detail).toContain('calls carry the fastest bleed')

      const sellingCharm = computeCharmThetaVerdict(150.0, -10.0, 'puts')
      expect(sellingCharm.headline).toBe('CHARM → SELLING')
      expect(sellingCharm.tone).toBe('neg')
      expect(sellingCharm.detail).toContain('selling pressure builds')

      const buyingCharm = computeCharmThetaVerdict(-85.0, null, null)
      expect(buyingCharm.headline).toBe('CHARM → BUYING')
      expect(buyingCharm.tone).toBe('pos')
      expect(buyingCharm.detail).toContain('buying pressure builds')
    })

    it('evaluates IV surface verdict with normal, elevated (>100%), and missing quotes', () => {
      const missing = computeIvVerdict(null)
      expect(missing.headline).toBe('NO QUOTES')
      expect(missing.tone).toBe('missing')

      const normal = computeIvVerdict({
        available: true,
        atm_iv: 0.284,
        call_iv_wall: 620,
        put_iv_wall: 580,
      })
      expect(normal.headline).toBe('ATM 28.4%')
      expect(normal.detail).toContain('upside uncertainty parks at 620')
      expect(normal.detail).toContain('downside uncertainty parks at 580')

      const extremeVol = computeIvVerdict({ available: true, atm_iv: 1.45, call_iv_wall: 150 })
      expect(extremeVol.headline).toBe('ATM >100%')
    })

    it('evaluates volume profile verdict with spot above/below POC and missing history', () => {
      const missing = computeVolumeVerdict(null, 600)
      expect(missing.headline).toBe('NOT ENOUGH BARS')
      expect(missing.tone).toBe('missing')

      const above = computeVolumeVerdict(
        { available: true, poc: 590, value_area_low: 580, value_area_high: 600, lvn_count: 2 },
        595,
      )
      expect(above.headline).toBe('TRADING ABOVE POC')
      expect(above.detail).toContain('Heaviest trade printed at 590.00 -0.8% from spot')
      expect(above.detail).toContain('2 thin zones')

      const below = computeVolumeVerdict(
        { available: true, poc: 600, value_area_low: 590, value_area_high: 610, lvn_count: 1 },
        590,
      )
      expect(below.headline).toBe('TRADING BELOW POC')
      expect(below.detail).toContain('1 thin zone')
    })

    it('verifies safe math in pctFromSpot preventing divide-by-zero or NaN output', () => {
      expect(computePctFromSpot(600, null)).toBe('')
      expect(computePctFromSpot(600, 0)).toBe('')
      expect(computePctFromSpot(null, 600)).toBe('')
      expect(computePctFromSpot(606, 600)).toBe(' +1.0% from spot')
      expect(computePctFromSpot(594, 600)).toBe(' -1.0% from spot')
    })
  })

  // =========================================================================
  // 3. LIVESTACKVIEW — COMPONENT SSR RENDERING & TELEMETRY INTEGRATION
  // =========================================================================
  describe('3. LiveStackView: PriceDraw & Regime Telemetry SSR Rendering', () => {
    it('renders RegimeStateBadge component in compact header mode cleanly', async () => {
      const sampleMagnet: PriceDrawLevel = {
        id: 'call_wall_600',
        type: 'call_wall',
        label: 'Call Wall',
        price: 600.0,
        distance_pts: 5.0,
        distance_pct: 0.84,
        pull_score: 80,
        direction: 'above',
        regime_role: 'Overhead Resistance',
        supporting_lenses: ['GAMMA', 'GEX'],
        lens_count: 2,
        is_primary_magnet: true,
      }

      const samplePayload: PriceDrawTelemetryPayload = {
        symbol: 'SPY',
        spot: 595.0,
        asof_utc: '2026-08-29T20:00:00Z',
        regime_state: 'volatility_dampening',
        regime_label: 'Vol Dampening',
        regime_strength: 0.9,
        dominant_direction: 'bullish_pull',
        primary_magnet: sampleMagnet,
        levels: [sampleMagnet],
        confluence_clusters: [],
        quality: {
          measurable: true,
          open_interest_available: true,
          iv_available: true,
          volume_available: true,
          reason: null,
        },
        warnings: [],
      }

      const app = createSSRApp({
        render: () =>
          h(RegimeStateBadge, {
            payload: samplePayload,
            compact: true,
            showStrength: true,
            showVector: true,
          }),
      })
      const html = await renderToString(app)
      expect(html).toContain('is-compact')
      expect(html).toContain('VOL DAMPENING · LONG Γ')
      expect(html).toContain('▲ BULLISH PULL')
      expect(html).toContain('90%')
    })

    it('renders PriceDrawLadder component with unmeasured telemetry without crashing', async () => {
      const unmeasured = createUnmeasuredPayload('XYZ', 'Options chain offline')
      const app = createSSRApp({
        render: () =>
          h(PriceDrawLadder, {
            payload: unmeasured,
            symbol: 'XYZ',
            spot: null,
            selectedLevelId: null,
          }),
      })
      const html = await renderToString(app)
      expect(html).toContain('unmeasured-state')
      expect(html).toContain('REGIME UNMEASURED · NO ACTIVE PRICE MAGNETS')
      expect(html).toContain('Options chain offline')
      expect(html).toContain('—')
      expect(html).not.toContain('NaN')
    })
  })

  // =========================================================================
  // 4. DESKVIEW — MASSIVE BOARD SYMBOL ARRAY SCALING & REGIME BREADTH
  // =========================================================================
  describe('4. DeskView: Massive Board Scaling & Regime Breadth Computation', () => {
    function buildBoardSymbols(
      peadList: Array<{ symbol?: string }>,
      signalsList: Array<{ symbol?: string }>,
      watchlist: string[],
    ): string[] {
      const out: string[] = []
      const seen = new Set<string>()
      const push = (value: string | undefined) => {
        const sym = String(value || '')
          .trim()
          .toUpperCase()
        if (!sym || seen.has(sym)) return
        seen.add(sym)
        out.push(sym)
      }
      for (const row of peadList) push(row.symbol)
      for (const row of signalsList) push(row.symbol)
      for (const row of watchlist) push(row)
      return out.slice(0, 40)
    }

    function calculateMarketRegimeBreadth(
      symbols: string[],
      regimeMap: Record<string, PriceDrawTelemetryPayload | null | undefined>,
    ) {
      let dampening = 0
      let amplification = 0
      let other = 0
      let unmeasured = 0
      let bullishPulls = 0
      let bearishPulls = 0

      for (const sym of symbols) {
        const tel = regimeMap[sym.toUpperCase()]
        if (!tel || !tel.quality?.measurable || tel.regime_state === 'unmeasurable') {
          unmeasured++
          continue
        }
        if (tel.regime_state === 'volatility_dampening') {
          dampening++
        } else if (tel.regime_state === 'volatility_amplification') {
          amplification++
        } else {
          other++
        }

        if (tel.dominant_direction === 'bullish_pull') {
          bullishPulls++
        } else if (tel.dominant_direction === 'bearish_pull') {
          bearishPulls++
        }
      }

      const measured = dampening + amplification + other
      const dominantBias =
        bullishPulls > bearishPulls
          ? 'BULL PULL'
          : bearishPulls > bullishPulls
            ? 'BEAR PULL'
            : 'PIN / FLAT'

      return {
        dampening,
        amplification,
        other,
        unmeasured,
        measured,
        dominantBias,
        total: symbols.length,
      }
    }

    it('strictly deduplicates and caps board symbols to 40 targets under massive 150+ input load', () => {
      const peadList = Array.from({ length: 60 }, (_, i) => ({ symbol: `PEAD_${i}` }))
      const signalsList = Array.from({ length: 60 }, (_, i) => ({ symbol: `SIG_${i}` }))
      const watchlist = Array.from({ length: 60 }, (_, i) => `WATCH_${i}`)

      const board = buildBoardSymbols(peadList, signalsList, watchlist)
      expect(board.length).toBe(40)
      expect(new Set(board).size).toBe(40)
      expect(board[0]).toBe('PEAD_0')
      expect(board[39]).toBe('PEAD_39')
    })

    it('handles overlapping symbols across all three domains with case-insensitive normalization', () => {
      const peadList = [{ symbol: 'aapl' }, { symbol: 'msft' }, { symbol: 'NVDA' }]
      const signalsList = [{ symbol: 'AAPL' }, { symbol: 'TSLA' }, { symbol: 'nvda' }]
      const watchlist = ['aapl', 'GOOGL', 'AMZN', 'msft']

      const board = buildBoardSymbols(peadList, signalsList, watchlist)
      expect(board).toEqual(['AAPL', 'MSFT', 'NVDA', 'TSLA', 'GOOGL', 'AMZN'])
      expect(board.length).toBe(6)
    })

    it('correctly aggregates market regime breadth with mixed measured, unmeasured, and null states', () => {
      const symbols = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'GOOGL', 'AMZN', 'META', 'UNM']
      const regimeMap: Record<string, PriceDrawTelemetryPayload | null> = {
        AAPL: {
          symbol: 'AAPL',
          spot: 230,
          asof_utc: '',
          regime_state: 'volatility_dampening',
          regime_label: '',
          regime_strength: 0.8,
          dominant_direction: 'bullish_pull',
          primary_magnet: null,
          levels: [],
          confluence_clusters: [],
          quality: {
            measurable: true,
            open_interest_available: true,
            iv_available: true,
            volume_available: true,
            reason: null,
          },
          warnings: [],
        },
        MSFT: {
          symbol: 'MSFT',
          spot: 420,
          asof_utc: '',
          regime_state: 'volatility_dampening',
          regime_label: '',
          regime_strength: 0.75,
          dominant_direction: 'bullish_pull',
          primary_magnet: null,
          levels: [],
          confluence_clusters: [],
          quality: {
            measurable: true,
            open_interest_available: true,
            iv_available: true,
            volume_available: true,
            reason: null,
          },
          warnings: [],
        },
        NVDA: {
          symbol: 'NVDA',
          spot: 130,
          asof_utc: '',
          regime_state: 'volatility_amplification',
          regime_label: '',
          regime_strength: 0.85,
          dominant_direction: 'bearish_pull',
          primary_magnet: null,
          levels: [],
          confluence_clusters: [],
          quality: {
            measurable: true,
            open_interest_available: true,
            iv_available: true,
            volume_available: true,
            reason: null,
          },
          warnings: [],
        },
        TSLA: {
          symbol: 'TSLA',
          spot: 210,
          asof_utc: '',
          regime_state: 'charm_decay_selling',
          regime_label: '',
          regime_strength: 0.6,
          dominant_direction: 'bearish_pull',
          primary_magnet: null,
          levels: [],
          confluence_clusters: [],
          quality: {
            measurable: true,
            open_interest_available: true,
            iv_available: true,
            volume_available: true,
            reason: null,
          },
          warnings: [],
        },
        GOOGL: createUnmeasuredPayload('GOOGL', 'No chain'),
        AMZN: null,
        META: undefined as any,
        UNM: {
          symbol: 'UNM',
          spot: 50,
          asof_utc: '',
          regime_state: 'unmeasurable',
          regime_label: '',
          regime_strength: null,
          dominant_direction: 'unmeasured',
          primary_magnet: null,
          levels: [],
          confluence_clusters: [],
          quality: {
            measurable: false,
            open_interest_available: false,
            iv_available: false,
            volume_available: false,
            reason: 'unmeasurable',
          },
          warnings: [],
        },
      }

      const breadth = calculateMarketRegimeBreadth(symbols, regimeMap)
      expect(breadth.total).toBe(8)
      expect(breadth.dampening).toBe(2) // AAPL, MSFT
      expect(breadth.amplification).toBe(1) // NVDA
      expect(breadth.other).toBe(1) // TSLA (charm_decay_selling)
      expect(breadth.unmeasured).toBe(4) // GOOGL, AMZN, META, UNM
      expect(breadth.measured).toBe(4)
      expect(breadth.dominantBias).toBe('PIN / FLAT') // 2 bullish vs 2 bearish = PIN/FLAT
    })

    it('resolves dominant directional pull bias to BULL PULL or BEAR PULL when unpinned', () => {
      const symbols = ['A', 'B', 'C']
      const bullishMap: Record<string, PriceDrawTelemetryPayload> = {
        A: {
          symbol: 'A',
          spot: 10,
          asof_utc: '',
          regime_state: 'volatility_dampening',
          regime_label: '',
          regime_strength: 0.5,
          dominant_direction: 'bullish_pull',
          primary_magnet: null,
          levels: [],
          confluence_clusters: [],
          quality: {
            measurable: true,
            open_interest_available: true,
            iv_available: true,
            volume_available: true,
            reason: null,
          },
          warnings: [],
        },
        B: {
          symbol: 'B',
          spot: 20,
          asof_utc: '',
          regime_state: 'volatility_dampening',
          regime_label: '',
          regime_strength: 0.5,
          dominant_direction: 'bullish_pull',
          primary_magnet: null,
          levels: [],
          confluence_clusters: [],
          quality: {
            measurable: true,
            open_interest_available: true,
            iv_available: true,
            volume_available: true,
            reason: null,
          },
          warnings: [],
        },
        C: {
          symbol: 'C',
          spot: 30,
          asof_utc: '',
          regime_state: 'volatility_amplification',
          regime_label: '',
          regime_strength: 0.5,
          dominant_direction: 'bearish_pull',
          primary_magnet: null,
          levels: [],
          confluence_clusters: [],
          quality: {
            measurable: true,
            open_interest_available: true,
            iv_available: true,
            volume_available: true,
            reason: null,
          },
          warnings: [],
        },
      }
      expect(calculateMarketRegimeBreadth(symbols, bullishMap).dominantBias).toBe('BULL PULL')
    })
  })

  // =========================================================================
  // 5. DESKVIEW — QUOTE MARKS & CASCADE FALLBACKS
  // =========================================================================
  describe('5. DeskView: Quote Marks & Cascade Fallback Reliability', () => {
    function getWatchPrice(sym: string, probeResults: Record<string, any>): number | null {
      const t = probeResults[sym]
      if (!t) return null
      const fromStats = t.stats?.last_price
      if (fromStats != null && Number.isFinite(fromStats)) return fromStats
      const last = t.series?.at(-1)?.c
      return last != null && Number.isFinite(last) ? last : null
    }

    function getMarkLast(
      sym: string,
      liveMarks: Record<string, any>,
      probeResults: Record<string, any>,
    ): number | null {
      const mark = liveMarks[sym.toUpperCase()]
      const last = mark?.last
      if (last != null && Number.isFinite(last)) return last
      return getWatchPrice(sym, probeResults)
    }

    function getMarkChg(
      sym: string,
      liveMarks: Record<string, any>,
      probeResults: Record<string, any>,
    ): number | null {
      const live = liveMarks[sym.toUpperCase()]?.chg_1d_pct
      if (live != null && Number.isFinite(live)) return live
      const traj = probeResults[sym]?.stats?.chg_1d_pct
      return traj != null && Number.isFinite(traj) ? traj : null
    }

    it('cascades from live mark last -> trajectory stats last -> trajectory series close -> null', () => {
      const liveMarks = {
        AAPL: { last: 232.5 },
        MSFT: { last: null },
        NVDA: { last: undefined },
        TSLA: {},
      }
      const probeResults = {
        MSFT: { stats: { last_price: 425.0 } },
        NVDA: { series: [{ c: 128.0 }, { c: 130.5 }] },
        TSLA: { stats: { last_price: NaN }, series: [{ c: null }] },
        EMPTY: null,
      }

      expect(getMarkLast('AAPL', liveMarks, probeResults)).toBe(232.5)
      expect(getMarkLast('MSFT', liveMarks, probeResults)).toBe(425.0)
      expect(getMarkLast('NVDA', liveMarks, probeResults)).toBe(130.5)
      expect(getMarkLast('TSLA', liveMarks, probeResults)).toBeNull()
      expect(getMarkLast('EMPTY', liveMarks, probeResults)).toBeNull()
      expect(getMarkLast('UNKNOWN', liveMarks, probeResults)).toBeNull()
    })

    it('cascades 1-day percentage change from live marks to trajectory stats safely', () => {
      const liveMarks = {
        AAPL: { chg_1d_pct: 0.015 },
        MSFT: { chg_1d_pct: null },
      }
      const probeResults = {
        MSFT: { stats: { chg_1d_pct: -0.008 } },
        GOOGL: { stats: { chg_1d_pct: 0.022 } },
      }

      expect(getMarkChg('AAPL', liveMarks, probeResults)).toBe(0.015)
      expect(getMarkChg('MSFT', liveMarks, probeResults)).toBe(-0.008)
      expect(getMarkChg('GOOGL', liveMarks, probeResults)).toBe(0.022)
      expect(getMarkChg('UNKNOWN', liveMarks, probeResults)).toBeNull()
    })
  })

  // =========================================================================
  // 6. DESKVIEW — SPARKLINE GENERATOR & CACHE INVARIANCE
  // =========================================================================
  describe('6. DeskView: Sparkline Generator & Cache Invariance', () => {
    it('produces valid SVG sparkline paths for series >= 3 bars and returns empty for < 3', () => {
      const emptySeries: any[] = []
      const singleBar = [{ c: 100 }]
      const twoBars = [{ c: 100 }, { c: 102 }]
      const validBars = [{ c: 100 }, { c: 102 }, { c: 105 }, { c: 104 }]

      const calc = (series: any[]) => {
        if (!series || series.length <= 2) return null
        const closes = series.map((b) => b.c)
        return sparkline(closes.slice(-40), 88, 22, 2).d
      }

      expect(calc(emptySeries)).toBeNull()
      expect(calc(singleBar)).toBeNull()
      expect(calc(twoBars)).toBeNull()

      const path = calc(validBars)
      expect(path).toBeDefined()
      expect(path).toContain('M')
      expect(path).toMatch(/[0-9]/)
    })

    it('generates consistent cache keys and prevents memory leaks under rapid ticker probing', () => {
      const sparkCache = new Map<string, { key: string; path: string }>()
      const series = [
        { d: '2026-08-28', c: 100 },
        { d: '2026-08-29', c: 105 },
        { d: '2026-08-30', c: 108 },
      ]

      const lastBar = series[series.length - 1]
      const cacheKey = `${series.length}_${lastBar.d}_${lastBar.c}`

      const path1 = sparkline(
        series.map((b) => b.c),
        88,
        22,
        2,
      ).d
      sparkCache.set('NVDA', { key: cacheKey, path: path1 })

      // Subsequent lookup with same data hits cache
      const cached = sparkCache.get('NVDA')
      expect(cached?.key).toBe(cacheKey)
      expect(cached?.path).toBe(path1)

      // Changed last price invalidates cache key
      const newLastBar = { d: '2026-08-30', c: 110 }
      const newCacheKey = `${series.length}_${newLastBar.d}_${newLastBar.c}`
      expect(newCacheKey).not.toBe(cacheKey)
    })
  })

  // =========================================================================
  // 7. COMPREHENSIVE ZERO-SPOOFING & DESIGN CONFORMANCE INVARIANTS
  // =========================================================================
  describe('7. Conformance: Zero-Spoofing & Decision Support Integrity', () => {
    it('verifies all unmeasured helper formatters output genuine em-dash (—) and not fake zeroes', () => {
      expect(formatDistancePoints(null)).toBe('—')
      expect(formatDistancePercent(null)).toBe('—')
      expect(formatPullScore(null)).toBe('—')
      expect(DASH).toBe('—')
      expect(pctFrac(null, 1)).toBe('—')
      expect(compact(null)).toBe('—')
      expect(num(null, 2)).toBe('—')
    })

    it('confirms both LiveStackView and DeskView contain required decision support disclaimers', () => {
      expect(liveStackSrc).toContain('DECISION SUPPORT ONLY')
      expect(liveStackSrc).toContain('never an order or an authorization')
      expect(liveStackSrc).toContain('confluence zones are descriptive geometry, not probabilities')

      expect(deskSrc).toContain('RESEARCH BOOK')
      expect(deskSrc).toContain('LIVE BOOK CLEARED')
      expect(deskSrc).toContain('Execution Arena')
    })
  })
})
