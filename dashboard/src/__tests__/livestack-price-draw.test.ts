import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  createUnmeasuredPayload,
  isRegimeMeasurable,
  formatDistancePercent,
  formatDistancePoints,
  formatPullScore,
  UNMEASURED_PLACEHOLDER,
} from '@/priceDrawContracts'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Milestone 4: LiveStackView Price Draw & Market Regime Integration', () => {
  const liveStackSrc = source('views/LiveStackView.vue')

  describe('1. Component Imports & Architecture Contracts', () => {
    it('imports PriceDrawLadder and RegimeStateBadge components', () => {
      expect(liveStackSrc).toContain(
        "import RegimeStateBadge from '@/components/RegimeStateBadge.vue'",
      )
      expect(liveStackSrc).toContain(
        "import PriceDrawLadder from '@/components/PriceDrawLadder.vue'",
      )
    })

    it('imports TypeScript telemetry contracts and types', () => {
      expect(liveStackSrc).toContain(
        "import type { PriceDrawTelemetryPayload, PriceDrawLevel } from '@/priceDrawContracts'",
      )
    })

    it('subscribes to api.priceAttractors with 30s polling cadence', () => {
      expect(liveStackSrc).toContain('const priceDrawRes = useResource<PriceDrawTelemetryPayload>(')
      expect(liveStackSrc).toContain('() => api.priceAttractors(symbol.value)')
      expect(liveStackSrc).toContain('{ intervalMs: REFRESH_MS }')
    })

    it('refreshes priceDrawRes concurrently when symbol changes', () => {
      expect(liveStackSrc).toContain('watch(symbol, () => {')
      expect(liveStackSrc).toContain('void optionsRes.refresh({ clear: true })')
      expect(liveStackSrc).toContain('void priceDrawRes.refresh({ clear: true })')
    })
  })

  describe('2. Header Bar & Level Selection State', () => {
    it('mounts RegimeStateBadge in the header bar next to dataModeBadge', () => {
      expect(liveStackSrc).toContain('<RegimeStateBadge')
      expect(liveStackSrc).toContain('v-if="priceDrawPayload"')
      expect(liveStackSrc).toContain(':payload="priceDrawPayload"')
      expect(liveStackSrc).toContain(':compact="true"')
      expect(liveStackSrc).toContain(':show-strength="true"')
      expect(liveStackSrc).toContain(':show-vector="true"')
    })

    it('maintains selectedLevelId ref and handleSelectLevel callback', () => {
      expect(liveStackSrc).toContain('const selectedLevelId = ref<string | null>(null)')
      expect(liveStackSrc).toContain('function handleSelectLevel(level: PriceDrawLevel): void {')
      expect(liveStackSrc).toContain('selectedLevelId.value = level.id')
    })
  })

  describe('3. Panel 03 Level Confluence & PriceDrawLadder Integration', () => {
    it('embeds PriceDrawLadder within Panel 03', () => {
      expect(liveStackSrc).toContain('label="LEVEL CONFLUENCE"')
      expect(liveStackSrc).toContain('index="03"')
      expect(liveStackSrc).toContain('<PriceDrawLadder')
      expect(liveStackSrc).toContain(':payload="priceDrawPayload"')
      expect(liveStackSrc).toContain(':symbol="symbol"')
      expect(liveStackSrc).toContain(':spot="spot"')
      expect(liveStackSrc).toContain(':selected-level-id="selectedLevelId"')
      expect(liveStackSrc).toContain('@select-level="handleSelectLevel"')
    })

    it('preserves all mandatory backward-compatible disclaimers and AST tokens', () => {
      expect(liveStackSrc).toContain('LEVEL CONFLUENCE')
      expect(liveStackSrc).toContain('confluence zones are descriptive geometry, not probabilities')
      expect(liveStackSrc).toContain('DECISION SUPPORT ONLY')
      expect(liveStackSrc).toMatch(/lens_count >= 2/)
    })
  })

  describe('4. Zero-Spoofing & Unmeasured Telemetry Guarantees', () => {
    it('generates genuine unmeasured payload with null distances and placeholder strings', () => {
      const unmeasured = createUnmeasuredPayload(
        'UNMEASURED_SYM',
        'No options chain data available',
      )
      expect(unmeasured.symbol).toBe('UNMEASURED_SYM')
      expect(unmeasured.spot).toBeNull()
      expect(unmeasured.regime_state).toBe('unmeasurable')
      expect(unmeasured.primary_magnet).toBeNull()
      expect(unmeasured.levels).toEqual([])
      expect(unmeasured.quality.measurable).toBe(false)
      expect(isRegimeMeasurable(unmeasured.regime_state)).toBe(false)

      expect(formatDistancePoints(null)).toBe(UNMEASURED_PLACEHOLDER)
      expect(formatDistancePercent(null)).toBe(UNMEASURED_PLACEHOLDER)
      expect(formatPullScore(null)).toBe(UNMEASURED_PLACEHOLDER)
    })

    it('correctly formats measured vs unmeasured level distances', () => {
      expect(formatDistancePoints(12.5)).toBe('+12.50')
      expect(formatDistancePoints(-4.2)).toBe('-4.20')
      expect(formatDistancePoints(null)).toBe('—')

      expect(formatDistancePercent(2.15)).toBe('+2.15%')
      expect(formatDistancePercent(-1.05)).toBe('-1.05%')
      expect(formatDistancePercent(null)).toBe('—')
    })
  })
})
