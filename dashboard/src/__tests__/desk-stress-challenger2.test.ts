import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const desk = readFileSync(join(srcRoot, 'views', 'DeskView.vue'), 'utf8')

describe('Challenger 2: DeskView Empirical Contract & Telemetry Stress Tests', () => {
  describe('1. boardSymbols() Deduplication and 40-Symbol Cap Invariants', () => {
    // Replicate the exact boardSymbols algorithm from DeskView.vue to stress-test it
    function computeBoardSymbols(
      peadList: Array<{ symbol?: string }>,
      signalList: Array<{ symbol?: string }>,
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
      for (const row of signalList) push(row.symbol)
      for (const row of watchlist) push(row)
      return out.slice(0, 40)
    }

    it('deduplicates across pead, signals, and customWatchlist case-insensitively', () => {
      const pead = [{ symbol: 'AAPL' }, { symbol: 'msft' }, { symbol: 'GOOGL' }]
      const signals = [{ symbol: 'aapl' }, { symbol: 'TSLA' }, { symbol: 'MSFT' }]
      const watchlist = ['googl', 'TSLA', 'NVDA', 'aapl']

      const result = computeBoardSymbols(pead, signals, watchlist)
      expect(result).toEqual(['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA'])
      expect(new Set(result).size).toBe(result.length)
    })

    it('ignores empty strings, whitespace-only strings, and undefined symbols', () => {
      const pead = [{ symbol: '' }, { symbol: '   ' }, { symbol: undefined }, { symbol: 'NVDA' }]
      const signals = [{ symbol: undefined }, { symbol: 'AMD' }, { symbol: '' }]
      const watchlist = ['', '  ', 'INTC']

      const result = computeBoardSymbols(pead, signals, watchlist)
      expect(result).toEqual(['NVDA', 'AMD', 'INTC'])
    })

    it('strictly caps the output symbol array to a maximum of 40 symbols', () => {
      const pead = Array.from({ length: 30 }, (_, i) => ({ symbol: `SYM_PEAD_${i}` }))
      const signals = Array.from({ length: 30 }, (_, i) => ({ symbol: `SYM_SIG_${i}` }))
      const watchlist = Array.from({ length: 30 }, (_, i) => `SYM_WL_${i}`)

      const result = computeBoardSymbols(pead, signals, watchlist)
      expect(result.length).toBe(40)
      expect(result.slice(0, 30)).toEqual(pead.map((p) => p.symbol))
      expect(result.slice(30, 40)).toEqual(signals.slice(0, 10).map((s) => s.symbol))
    })

    it('handles empty inputs gracefully', () => {
      const result = computeBoardSymbols([], [], [])
      expect(result).toEqual([])
    })

    it('DeskView.vue contains the exact boardSymbols definition with 40-symbol slice', () => {
      expect(desk).toContain('function boardSymbols(): string[] {')
      expect(desk).toContain('return out.slice(0, 40)')
      expect(desk).toContain('seen.has(sym)')
      expect(desk).toContain('seen.add(sym)')
      expect(desk).toContain('for (const row of pead.value) push(row.symbol)')
      expect(desk).toContain('for (const row of signals.value) push(row.symbol)')
      expect(desk).toContain('for (const row of customWatchlist.value) push(row)')
    })
  })

  describe('2. Capital Clearance States and Posture Rendering', () => {
    it('contains exact clearance template conditions for LIVE BOOK CLEARED vs RESEARCH BOOK', () => {
      expect(desk).toContain("{{ r?.cleared_for_live ? 'LIVE BOOK CLEARED' : 'RESEARCH BOOK' }}")
      expect(desk).toContain(":class=\"r?.cleared_for_live ? 'live' : 'research'\"")
    })

    it('contains exact clearance template conditions for ARMED vs HELD and LIVE READY vs STANDBY', () => {
      expect(desk).toContain("{{ r?.cleared_for_live ? 'LIVE READY' : 'STANDBY' }}")
      expect(desk).toContain("{{ r?.cleared_for_live ? 'ARMED' : 'HELD' }}")
      expect(desk).toContain("{{ r?.cleared_for_live ? 'CLEARED' : 'HELD' }}")
      expect(desk).toContain(":class=\"r?.cleared_for_live ? 'armed' : 'held'\"")
      expect(desk).toContain(":class=\"r?.cleared_for_live ? 'pos' : 'warn-text'\"")
    })

    it('evaluates confidence posture correctly across all edge tiers', () => {
      function evalPosture(sigEntered: number, sigHighConf: number, sigActionable: number) {
        if (sigEntered > 0 || sigHighConf > 0) {
          return { label: 'HIGH CONFIDENCE', tone: 'armed' }
        }
        if (sigActionable > 0) {
          return { label: 'WATCH ONLY', tone: 'held' }
        }
        return { label: 'NO EDGE', tone: 'held' }
      }

      expect(evalPosture(1, 0, 0)).toEqual({ label: 'HIGH CONFIDENCE', tone: 'armed' })
      expect(evalPosture(0, 2, 0)).toEqual({ label: 'HIGH CONFIDENCE', tone: 'armed' })
      expect(evalPosture(0, 0, 3)).toEqual({ label: 'WATCH ONLY', tone: 'held' })
      expect(evalPosture(0, 0, 0)).toEqual({ label: 'NO EDGE', tone: 'held' })
    })
  })

  describe('3. Telemetry Invariants & Polling Cycles', () => {
    it('configures marks polling at 20s interval with visibilityState guard', () => {
      expect(desk).toContain('marksTimer = window.setInterval(() => {')
      expect(desk).toContain("if (document.visibilityState === 'visible') void refreshBoardMarks()")
      expect(desk).toContain('}, 20_000)')
    })

    it('configures watchlist probe timer at 60s interval', () => {
      expect(desk).toContain(
        'watchlistTimer = window.setInterval(() => void probeWatchlist(true), 60_000)',
      )
    })

    it('cleans up all intervals on component unmount', () => {
      expect(desk).toContain('onUnmounted(() => {')
      expect(desk).toContain('scanPollToken += 1')
      expect(desk).toContain('if (watchlistTimer !== undefined) clearInterval(watchlistTimer)')
      expect(desk).toContain('if (marksTimer !== undefined) clearInterval(marksTimer)')
    })

    it('triggers refreshBoardMarks and probeWatchlist in onMounted lifecycle hook', () => {
      expect(desk).toContain('onMounted(() => {')
      expect(desk).toContain('void probeWatchlist(true)')
      expect(desk).toContain('void resumeScanJob()')
      expect(desk).toContain('void refreshBoardMarks()')
    })

    it('watches status asof and model/watchlist lengths to trigger board mark refresh', () => {
      expect(desk).toContain('() => status.data.value?.asof')
      expect(desk).toContain('void probeWatchlist(true)')
      expect(desk).toContain('void refreshBoardMarks()')
      expect(desk).toContain(
        "() => [pead.value.length, signals.value.length, customWatchlist.value.join(',')]",
      )
    })

    it('integrates api.quotes in refreshBoardMarks', () => {
      expect(desk).toContain('const payload = await api.quotes(symbols)')
      expect(desk).toContain('liveMarks.value = next')
    })
  })

  describe('4. Dual-View Mode Switching & Condensed Responsive Columns', () => {
    it('supports split, pead, and directional dual view modes', () => {
      expect(desk).toContain("dualViewMode = ref<'split' | 'pead' | 'directional'>('split')")
      expect(desk).toContain("dualViewMode = 'split'")
      expect(desk).toContain("dualViewMode = 'pead'")
      expect(desk).toContain("dualViewMode = 'directional'")
    })

    it('condenses PEAD table columns in split mode by hiding Gap/ATR and Volume', () => {
      expect(desk).toContain('v-if="dualViewMode !== \'split\'" class="label num col-gap"')
      expect(desk).toContain('v-if="dualViewMode !== \'split\'" class="label num col-vol"')
      expect(desk).toContain('v-if="dualViewMode !== \'split\'" class="fig num col-gap"')
      expect(desk).toContain('v-if="dualViewMode !== \'split\'" class="fig num col-vol"')
      expect(desk).toContain(":class=\"{ 'is-split': dualViewMode === 'split' }\"")
    })

    it('condenses Directional table columns in split mode by hiding Horizon (Hz)', () => {
      expect(desk).toContain('v-if="dualViewMode !== \'split\'" class="label num col-hz"')
      expect(desk).toContain('v-if="dualViewMode !== \'split\'" class="fig num dim col-hz"')
    })

    it('dynamically adapts panel widths between w-half and w-full based on dualViewMode', () => {
      expect(desk).toContain(":class=\"dualViewMode === 'pead' ? 'w-full' : 'w-half'\"")
      expect(desk).toContain(":class=\"dualViewMode === 'directional' ? 'w-full' : 'w-half'\"")
    })
  })

  describe('5. AST and Contract String Invariants', () => {
    it('strictly complies with all desk-market-contract requirements', () => {
      expect(desk).not.toContain('PAPER TRADING MODE')
      expect(desk).not.toContain('PAPER TRADING')
      expect(desk).toContain('RESEARCH BOOK')
      expect(desk).toContain('LIVE BOOK CLEARED')
      expect(desk).toContain('STANDBY')
      expect(desk).toContain('refreshBoardMarks')
      expect(desk).toContain('api.quotes')
      expect(desk).toContain('markLast(c.symbol)')
      expect(desk).toContain('markLast(s.symbol)')
      expect(desk).toContain('v-for="c in filteredPead" :key="c.symbol"')
      expect(desk).toContain('v-for="s in filteredSignals"')
      expect(desk).toContain(':key="s.symbol"')
    })

    it('strictly complies with anti-neon/aura-farming gate tokens', () => {
      const forbiddenTokens = [
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
      for (const bad of forbiddenTokens) {
        expect(desk, `DeskView.vue must not contain forbidden aura token: ${bad}`).not.toContain(
          bad,
        )
      }
    })
  })
})
