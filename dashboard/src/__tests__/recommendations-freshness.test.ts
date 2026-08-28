import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { api, clearApiCache } from '@/api'
import { DASH } from '@/format'
import {
  UNMEASURED,
  formatSetupLevel,
  formatSupportLevels,
  formatTakeProfitZones,
  levelSourceLabel,
  sellSourceLabel,
  setupHeadlineInvalidation,
  suggestedRightLabel,
  suggestedRightTokenClass,
} from '@/suggestDisplay'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const drawerSrc = readFileSync(join(root, 'components', 'FlowSuggestionDrawer.vue'), 'utf8')
const apiSrc = readFileSync(join(root, 'api.ts'), 'utf8')
const suggestDisplaySrc = readFileSync(join(root, 'suggestDisplay.ts'), 'utf8')

describe('Recommendations Freshness & Level Source Attribution', () => {
  describe('Group 1: FlowSuggestionDrawer Cache Invalidation & Force Refresh', () => {
    let originalFetch: typeof globalThis.fetch

    beforeEach(() => {
      originalFetch = globalThis.fetch
    })

    afterEach(() => {
      globalThis.fetch = originalFetch
      clearApiCache()
    })

    it('constructs query parameters correctly for api.flowSuggestions with force and symbol', async () => {
      const capturedUrls: string[] = []
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        capturedUrls.push(url)
        return {
          ok: true,
          status: 200,
          json: async () => ({ available: true, rows: [] }),
        } as Response
      })

      await api.flowSuggestions({ symbol: 'NVDA', force: true })
      expect(capturedUrls[0]).toContain('/api/options/suggest')
      expect(capturedUrls[0]).toContain('force=1')
      expect(capturedUrls[0]).toContain('symbol=NVDA')

      await api.flowSuggestions({ symbol: 'AAPL', force: false })
      expect(capturedUrls[1]).toContain('/api/options/suggest')
      expect(capturedUrls[1]).not.toContain('force=1')
      expect(capturedUrls[1]).toContain('symbol=AAPL')

      await api.flowSuggestions({ limit: 20, force: true })
      expect(capturedUrls[2]).toContain('limit=20')
      expect(capturedUrls[2]).toContain('force=1')
    })

    it('constructs query parameters correctly for api.liveOpportunities with force', async () => {
      const capturedUrls: string[] = []
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        capturedUrls.push(url)
        return {
          ok: true,
          status: 200,
          json: async () => ({ available: true, rows: [] }),
        } as Response
      })

      await api.liveOpportunities({ limit: 10, force: true })
      expect(capturedUrls[0]).toContain('/api/options/opportunities')
      expect(capturedUrls[0]).toContain('limit=10')
      expect(capturedUrls[0]).toContain('force=1')
    })

    it('verifies api.ts clears memory cache on force: true', () => {
      expect(apiSrc).toMatch(
        /liveOpportunities:[\s\S]*?if \(opts\?\.force\) \{[\s\S]*?clearApiCache\('\/api\/options\/opportunities'\)/,
      )
      expect(apiSrc).toMatch(
        /flowSuggestions:[\s\S]*?if \(opts\?\.force\) \{[\s\S]*?clearApiCache\('\/api\/options\/suggest'\)/,
      )
    })

    it('verifies FlowSuggestionDrawer.vue arms forceNext and refreshes on symbol change', () => {
      expect(drawerSrc).toContain('const forceNext = ref(true)')
      expect(drawerSrc).toMatch(/const force = forceNext\.value\n\s*forceNext\.value = false/)
      expect(drawerSrc).toMatch(
        /watch\(\s*\(\) => props\.symbol,\s*\(newSym,\s*oldSym\) => \{\s*if \(props\.symbol && newSym !== oldSym\) \{\s*forceNext\.value = true\s*void feed\.refresh\(\{ clear: true \}\)/,
      )
      expect(drawerSrc).toMatch(/async function refreshLive\(\)/)
      expect(drawerSrc).toMatch(/forceNext\.value = true/)
    })
  })

  describe('Group 2: Level Source Attribution & Classification', () => {
    it('maps gamma_flip to options GEX and not technical analysis', () => {
      expect(levelSourceLabel('gamma_flip')).toBe('options GEX')
      expect(levelSourceLabel('gamma_flip')).not.toBe('technical analysis')
      expect(suggestDisplaySrc).not.toContain("value === 'gamma_flip' || value === 'ta'")
    })

    it('maps canonical level source labels correctly', () => {
      // Options GEX family
      expect(levelSourceLabel('options GEX')).toBe('options GEX')
      expect(levelSourceLabel('options gex')).toBe('options GEX')
      expect(levelSourceLabel('call_wall')).toBe('options GEX')
      expect(levelSourceLabel('put_wall')).toBe('options GEX')
      expect(levelSourceLabel('gex')).toBe('options GEX')
      expect(levelSourceLabel('gamma_flip')).toBe('options GEX')

      // Positions family
      expect(levelSourceLabel('positions')).toBe('positions')
      expect(levelSourceLabel('pin_strike')).toBe('positions')
      expect(levelSourceLabel('open_interest')).toBe('positions')

      // Resistance/Support family
      expect(levelSourceLabel('resistance/support')).toBe('resistance/support')
      expect(levelSourceLabel('support')).toBe('resistance/support')
      expect(levelSourceLabel('resistance')).toBe('resistance/support')

      // Technical Analysis family
      expect(levelSourceLabel('technical analysis')).toBe('technical analysis')
      expect(levelSourceLabel('ta')).toBe('technical analysis')

      // Unmeasured / null / unknown
      expect(levelSourceLabel(null)).toBe(UNMEASURED)
      expect(levelSourceLabel(undefined)).toBe(UNMEASURED)
      expect(levelSourceLabel('')).toBe(UNMEASURED)
      expect(levelSourceLabel('unknown_source')).toBe(UNMEASURED)
    })

    it('maps sell source labels and suggested right tokens correctly', () => {
      expect(sellSourceLabel('call_wall')).toBe('call wall')
      expect(sellSourceLabel('put_wall')).toBe('put wall')
      expect(sellSourceLabel('gamma_flip')).toBe('options GEX')
      expect(sellSourceLabel(null)).toBe(UNMEASURED)

      expect(suggestedRightLabel('call')).toBe('CALL')
      expect(suggestedRightLabel('put')).toBe('PUT')
      expect(suggestedRightLabel('watch')).toBe('WATCH')
      expect(suggestedRightLabel('blocked')).toBe('BLOCKED')
      expect(suggestedRightLabel(null)).toBe(UNMEASURED)

      expect(suggestedRightTokenClass('call')).toBe('token-call')
      expect(suggestedRightTokenClass('put')).toBe('token-put')
      expect(suggestedRightTokenClass('watch')).toBe('token-warn')
      expect(suggestedRightTokenClass('blocked')).toBe('token-unsigned')
      expect(suggestedRightTokenClass(null)).toBe('token-unsigned')
    })

    it('formats single setup levels with proper source attribution tags', () => {
      expect(formatSetupLevel(150.25, 'options GEX')).toBe('$150.25  options GEX')
      expect(formatSetupLevel(150.25, 'gamma_flip')).toBe('$150.25  options GEX')
      expect(formatSetupLevel(150.25, 'call_wall')).toBe('$150.25  options GEX')
      expect(formatSetupLevel(150.25, 'pin_strike')).toBe('$150.25  positions')
      expect(formatSetupLevel(150.25, 'support')).toBe('$150.25  resistance/support')
      expect(formatSetupLevel(150.25, 'ta')).toBe('$150.25  technical analysis')
      expect(formatSetupLevel(150.25, null)).toBe('$150.25')
      expect(formatSetupLevel(null, 'options GEX')).toBe(DASH)
      expect(formatSetupLevel(NaN, 'options GEX')).toBe(DASH)
    })

    it('formats multi-level support arrays cleanly with source tags', () => {
      const supports = [
        { price: 145.0, source: 'options GEX' },
        { price: 142.5, source: 'resistance/support' },
      ]
      expect(formatSupportLevels(supports)).toBe(
        '$145.00  options GEX · $142.50  resistance/support',
      )

      const mixed = [
        { price: 145.0, source: null },
        { price: 140.0, source: 'positions' },
      ]
      expect(formatSupportLevels(mixed)).toBe('$145.00 · $140.00  positions')

      expect(formatSupportLevels([])).toBe(UNMEASURED)
      expect(formatSupportLevels(null)).toBe(UNMEASURED)
      expect(formatSupportLevels(undefined)).toBe(UNMEASURED)
    })

    it('formats take-profit zones with proper source attribution', () => {
      const zones = [
        { price: 160.0, source: 'resistance/support' },
        { price: 165.0, source: 'technical analysis' },
      ]
      expect(formatTakeProfitZones(zones)).toBe(
        '$160.00  resistance/support · $165.00  technical analysis',
      )
      expect(formatTakeProfitZones([])).toBe(UNMEASURED)
      expect(formatTakeProfitZones(null)).toBe(UNMEASURED)
    })

    it('resolves headline invalidation with source attribution', () => {
      const suggestion = setupHeadlineInvalidation({
        invalidation: 135.0,
        invalidationSource: 'options GEX',
      })
      expect(suggestion.price).toBe(135.0)
      expect(suggestion.source).toBe('options GEX')

      const fallback = setupHeadlineInvalidation({
        planInvalidation: 132.5,
        planInvalidationSource: 'put_wall',
      })
      expect(fallback.price).toBe(132.5)
      expect(fallback.source).toBe('put_wall')

      const empty = setupHeadlineInvalidation({})
      expect(empty.price).toBeNull()
      expect(empty.source).toBeNull()
    })

    it('verifies FlowSuggestionDrawer.vue binds all level attributes cleanly', () => {
      expect(drawerSrc).toMatch(
        /formatSetupLevel\(\s*suggestion\.strike\s*\?\?\s*suggestion\.contract_plan\?\.strike,\s*suggestion\.strike_source,?\s*\)/,
      )
      expect(drawerSrc).toContain('formatSupportLevels(suggestion.supports)')
      expect(drawerSrc).toContain('levelSourceLabel(invalidationMark.source)')
      expect(drawerSrc).toContain('takeProfitCopy')
      expect(drawerSrc).toContain('missingSourcesCopy(suggestion.missing_sources)')
    })
  })
})
