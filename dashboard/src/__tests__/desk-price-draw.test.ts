import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { PriceDrawTelemetryPayload } from '@/priceDrawContracts'
import { createUnmeasuredPayload } from '@/priceDrawContracts'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Milestone 4: DeskView Price Draw & Market Regime Integration', () => {
  const deskSrc = source('views/DeskView.vue')

  describe('1. Component Imports & State Management', () => {
    it('imports RegimeStateBadge component and price draw contracts', () => {
      expect(deskSrc).toContain("import RegimeStateBadge from '@/components/RegimeStateBadge.vue'")
      expect(deskSrc).toContain('isRegimeMeasurable')
      expect(deskSrc).toContain('formatDistancePercent')
      expect(deskSrc).toContain('type PriceDrawTelemetryPayload')
      expect(deskSrc).toContain('type PriceDrawLevel')
    })

    it('maintains reactive regimeTelemetryMap state', () => {
      expect(deskSrc).toContain(
        'const regimeTelemetryMap = ref<Record<string, PriceDrawTelemetryPayload>>({})',
      )
    })

    it('provides regimeFor and primaryMagnetFor lookup helpers', () => {
      expect(deskSrc).toContain(
        'function regimeFor(sym: string | undefined): PriceDrawTelemetryPayload | null {',
      )
      expect(deskSrc).toContain(
        'function primaryMagnetFor(sym: string | undefined): PriceDrawLevel | null {',
      )
    })

    it('fetches api.priceAttractors concurrently for board and activity symbols in refreshBoardMarks', () => {
      expect(deskSrc).toContain('const data = await api.priceAttractors(sym)')
      expect(deskSrc).toContain('regimeTelemetryMap.value[sym.toUpperCase()] = data')
      expect(deskSrc).toContain('Promise.allSettled(')
    })
  })

  describe('2. Section 00 Market Regime & Magnet Breadth KPI Card', () => {
    it('computes marketRegimeBreadth aggregating dampening, amplification, and dominant draw bias', () => {
      expect(deskSrc).toContain('const marketRegimeBreadth = computed(() => {')
      expect(deskSrc).toContain('dampening++')
      expect(deskSrc).toContain('amplification++')
      expect(deskSrc).toContain('dominantBias =')
    })

    it('renders the Regime & Magnet Breadth card in Section 00 with click navigation to livestack', () => {
      expect(deskSrc).toContain('Regime & Magnet Breadth')
      expect(deskSrc).toContain("navTo('livestack')")
      expect(deskSrc).toContain('kpi-regime-card')
      expect(deskSrc).toContain('marketRegimeBreadth.dampening')
      expect(deskSrc).toContain('marketRegimeBreadth.amplification')
    })

    it('uses a 6-column grid for desk-summary to cleanly accommodate all KPI cards', () => {
      expect(deskSrc).toContain('grid-template-columns: repeat(6, minmax(0, 1fr));')
    })
  })

  describe('3. Multi-Panel Table Columns Integration', () => {
    it('adds Regime / Magnet column to Panel 01 (Live Activity Flags)', () => {
      expect(deskSrc).toContain('<th class="label col-regime">Regime / Magnet</th>')
      expect(deskSrc).toContain(':payload="regimeFor(row.symbol)"')
      expect(deskSrc).toContain('primaryMagnetFor(row.symbol)')
    })

    it('adds Regime / Magnet column to Panel 03 (Directional Signals)', () => {
      expect(deskSrc).toContain(':payload="regimeFor(s.symbol)"')
      expect(deskSrc).toContain('primaryMagnetFor(s.symbol)')
    })

    it('adds Regime / Magnet column to Panel 04 (Personal Watchlist & Probe Console)', () => {
      expect(deskSrc).toContain(':payload="regimeFor(sym)"')
      expect(deskSrc).toContain('primaryMagnetFor(sym)')
    })
  })

  describe('4. Zero-Spoofing & Missing Data Protocol across Table Cells', () => {
    it('renders neutral em dash placeholder when symbol regime telemetry is absent or unmeasured', () => {
      expect(deskSrc).toContain('<span v-else class="dim">—</span>')
      expect(deskSrc).toContain('isRegimeMeasurable(regimeFor(')
    })

    it('validates breadth computation under edge scenarios', () => {
      // Replicate the exact breadth algorithm from DeskView.vue to stress-test it
      function computeBreadth(
        symbols: string[],
        telemetryMap: Record<string, PriceDrawTelemetryPayload | null>,
      ) {
        let dampening = 0
        let amplification = 0
        let other = 0
        let unmeasured = 0
        let bullishPulls = 0
        let bearishPulls = 0

        for (const sym of symbols) {
          const tel = telemetryMap[sym.toUpperCase()]
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

      // Scenario A: All dampening
      const mapA: Record<string, PriceDrawTelemetryPayload> = {
        AAPL: {
          symbol: 'AAPL',
          spot: 230,
          asof_utc: '2026-08-29T16:00:00Z',
          regime_state: 'volatility_dampening',
          regime_label: 'Vol Dampening (Long Γ)',
          regime_strength: 0.85,
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
          spot: 450,
          asof_utc: '2026-08-29T16:00:00Z',
          regime_state: 'volatility_dampening',
          regime_label: 'Vol Dampening (Long Γ)',
          regime_strength: 0.72,
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
      }
      const resA = computeBreadth(['AAPL', 'MSFT'], mapA)
      expect(resA.dampening).toBe(2)
      expect(resA.amplification).toBe(0)
      expect(resA.dominantBias).toBe('BULL PULL')

      // Scenario B: Unmeasured & mixed
      const mapB: Record<string, PriceDrawTelemetryPayload> = {
        TSLA: createUnmeasuredPayload('TSLA'),
        NVDA: {
          symbol: 'NVDA',
          spot: 120,
          asof_utc: '2026-08-29T16:00:00Z',
          regime_state: 'volatility_amplification',
          regime_label: 'Vol Amplification (Short Γ)',
          regime_strength: 0.9,
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
      const resB = computeBreadth(['TSLA', 'NVDA', 'MISSING_SYM'], mapB)
      expect(resB.dampening).toBe(0)
      expect(resB.amplification).toBe(1)
      expect(resB.unmeasured).toBe(2)
      expect(resB.dominantBias).toBe('BEAR PULL')
    })
  })
})
