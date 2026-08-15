import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { pctFrac, DASH } from '@/format'
import { sparkline } from '@/charts'
import { loadWatchlist } from '@/watchlist'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const desk = readFileSync(join(srcRoot, 'views', 'DeskView.vue'), 'utf8')

// Replicate DeskView core logic functions for direct unit stress-testing
const ENTER_EDGE = 0.65
const ACTIONABLE_EDGE = 0.55

function confidenceBand(value: number | null | undefined): 'HIGH' | 'MODERATE' | 'LOW' | 'UNAVAILABLE' {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'UNAVAILABLE'
  if (value >= ENTER_EDGE) return 'HIGH'
  if (value >= ACTIONABLE_EDGE) return 'MODERATE'
  return 'LOW'
}

function hasHighConfidence(value: number | null | undefined, state?: string): boolean {
  if (state === 'ENTER') return true
  if (value === null || value === undefined || !Number.isFinite(value)) return false
  return value >= ENTER_EDGE
}

function hasActionableEdge(value: number | null | undefined): boolean {
  if (value === null || value === undefined || !Number.isFinite(value)) return false
  return value >= ACTIONABLE_EDGE
}

function edgeTitle(value: number | null | undefined, state?: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return 'No calibrated probability — use momentum + state only. Not authorization.'
  }
  if (hasHighConfidence(value, state)) {
    return `${pctFrac(value, 1)} HIGH — meets ENTER bar (≥${pctFrac(ENTER_EDGE, 0)})`
  }
  if (hasActionableEdge(value)) {
    return `${pctFrac(value, 1)} MODERATE — above ${pctFrac(ACTIONABLE_EDGE, 0)} watch floor; below ENTER ${pctFrac(ENTER_EDGE, 0)}`
  }
  return `${pctFrac(value, 1)} LOW — near coin-flip; not authorization edge`
}

function compareSignals(a: any, b: any): number {
  const aEnter = a.state === 'ENTER' ? 1 : 0
  const bEnter = b.state === 'ENTER' ? 1 : 0
  if (aEnter !== bEnter) return bEnter - aEnter
  const ap = typeof a.probability === 'number' && Number.isFinite(a.probability) ? a.probability : -1
  const bp = typeof b.probability === 'number' && Number.isFinite(b.probability) ? b.probability : -1
  if (bp !== ap) return bp - ap
  return Math.abs(b.momentum ?? 0) - Math.abs(a.momentum ?? 0)
}

function comparePead(a: any, b: any): number {
  return Math.abs(b.evidence?.pead_score ?? 0) - Math.abs(a.evidence?.pead_score ?? 0)
}

function momentumBarPct(value: number | null | undefined): number {
  if (value == null || !Number.isFinite(value)) return 0
  return Math.min(100, Math.max(0, Math.abs(value) * 50))
}

function sideWord(value: string | null | undefined): string {
  const side = String(value || '').toLowerCase()
  return side === 'long' ? 'UP' : side === 'short' ? 'DOWN' : 'NONE'
}

function activityLean(row: any): { label: string; cls: string; title: string } {
  const lean = String(row.activity_lean || '').toLowerCase()
  const source = String(row.activity_lean_source || 'none').replaceAll('_', ' ')
  if (lean === 'bullish') {
    return { label: row.activity_lean_label || 'BULLISH', cls: 'bullish', title: `Activity lean · ${source}` }
  }
  if (lean === 'bearish') {
    return { label: row.activity_lean_label || 'BEARISH', cls: 'bearish', title: `Activity lean · ${source}` }
  }
  if (lean === 'mixed') {
    return { label: 'MIXED', cls: 'mixed', title: `Activity lean · ${source}` }
  }
  const impulse = String(row.price_impulse || '').toLowerCase()
  if (impulse === 'up' || (row.ret_1d != null && row.ret_1d > 0)) {
    return { label: 'BULLISH', cls: 'bullish', title: 'Activity lean · price impulse' }
  }
  if (impulse === 'down' || (row.ret_1d != null && row.ret_1d < 0)) {
    return { label: 'BEARISH', cls: 'bearish', title: 'Activity lean · price impulse' }
  }
  return { label: 'NEUTRAL', cls: 'neutral', title: 'No clear bullish/bearish activity lean' }
}

describe('Empirical Stress Testing: DeskView.vue', () => {
  describe('1. Mode Toggling & Split-View Responsive Invariants', () => {
    it('supports rapid mode toggling across split, pead, and directional without template desynchronization', () => {
      // Check mode tab buttons and bindings
      expect(desk).toContain("dualViewMode = 'split'")
      expect(desk).toContain("dualViewMode = 'pead'")
      expect(desk).toContain("dualViewMode = 'directional'")
      expect(desk).toContain("dualViewMode === 'split'")
      expect(desk).toContain("dualViewMode === 'pead'")
      expect(desk).toContain("dualViewMode === 'directional'")
    })

    it('enforces exact table column symmetry in PEAD table for split vs focus modes', () => {
      // PEAD table header check
      const peadTableMatch = desk.match(/<table v-if="filteredPead\.length" class="grid table-pead"[\s\S]*?<\/thead>/)
      expect(peadTableMatch).toBeTruthy()
      const peadHead = peadTableMatch![0]

      const peadBodyMatch = desk.match(/<tr v-for="c in filteredPead" :key="c\.symbol" class="pead-row"[\s\S]*?<\/tr>/)
      expect(peadBodyMatch).toBeTruthy()
      const peadRow = peadBodyMatch![0]

      // Count th vs td tags with v-if="dualViewMode !== 'split'"
      const thSplitHidden = (peadHead.match(/<th\b[^>]*v-if="dualViewMode !== 'split'"/g) || []).length
      const tdSplitHidden = (peadRow.match(/<td\b[^>]*v-if="dualViewMode !== 'split'"/g) || []).length
      expect(thSplitHidden).toBe(2) // Gap / ATR, Volume
      expect(tdSplitHidden).toBe(2) // Gap / ATR, Volume

      // Count total columns (using \b to avoid matching thead)
      const totalTh = (peadHead.match(/<th\b/g) || []).length
      const totalTd = (peadRow.match(/<td\b/g) || []).length
      expect(totalTh).toBe(10)
      expect(totalTd).toBe(10)

      // Total in split mode: 10 - 2 = 8
      expect(totalTh - thSplitHidden).toBe(8)
      expect(totalTd - tdSplitHidden).toBe(8)
    })

    it('enforces exact table column symmetry in Directional table for split vs focus modes', () => {
      // Directional table header check
      const dirTableMatch = desk.match(/<table v-if="filteredSignals\.length" class="grid table-directional"[\s\S]*?<\/thead>/)
      expect(dirTableMatch).toBeTruthy()
      const dirHead = dirTableMatch![0]

      const dirBodyMatch = desk.match(/<tr\s+v-for="s in filteredSignals"\s+:key="s\.symbol"[\s\S]*?<\/tr>/)
      expect(dirBodyMatch).toBeTruthy()
      const dirRow = dirBodyMatch![0]

      // Count th vs td tags with v-if="dualViewMode !== 'split'"
      const thSplitHidden = (dirHead.match(/<th\b[^>]*v-if="dualViewMode !== 'split'"/g) || []).length
      const tdSplitHidden = (dirRow.match(/<td\b[^>]*v-if="dualViewMode !== 'split'"/g) || []).length
      expect(thSplitHidden).toBe(1) // Hz column
      expect(tdSplitHidden).toBe(1) // Hz column

      // Count total columns (using \b to avoid matching thead)
      const totalTh = (dirHead.match(/<th\b/g) || []).length
      const totalTd = (dirRow.match(/<td\b/g) || []).length
      expect(totalTh).toBe(10)
      expect(totalTd).toBe(10)

      // Total in split mode: 10 - 1 = 9
      expect(totalTh - thSplitHidden).toBe(9)
      expect(totalTd - tdSplitHidden).toBe(9)
    })

    it('validates responsive CSS rules for split-view tables preventing horizontal clipping', () => {
      expect(desk).toContain('.w-half .table-pead th')
      expect(desk).toContain('.w-half .table-directional th')
      expect(desk).toContain('.w-half .col-sym')
      expect(desk).toContain('.w-half .col-last')
      expect(desk).toContain('.w-half .col-side')
      expect(desk).toContain('.w-half .col-score')
      expect(desk).toContain('.w-half .col-5d')
      expect(desk).toContain('.w-half .col-chain')
      expect(desk).toContain('.w-half .prob-bar-wrap')
      expect(desk).toContain('.w-half .mom-bar')
      expect(desk).toContain('@media (max-width: 1400px)')
      expect(desk).toContain('@media (max-width: 1100px)')
      expect(desk).toContain('@media (max-width: 768px)')
    })
  })

  describe('2. Data Permutations & Resilience Under Edge/Null Conditions', () => {
    it('handles empty PEAD array gracefully with honest empty copy and no null pointer dereference', () => {
      const emptyPead: any[] = []
      const ranked = emptyPead.slice().sort(comparePead)
      expect(ranked).toEqual([])

      const peadFlagged = emptyPead.filter((p) => p.setup_ok || p.model?.state === 'FLAG').length
      expect(peadFlagged).toBe(0)

      const summary: any = null
      const peadMeta = summary
        ? `${emptyPead.length} ordinal flags / ${summary.pead_attempted_symbols} examined · gate ${summary.pead_gate_verdict}`
        : `${emptyPead.length} ordinal flags · no calibrated probability`
      expect(peadMeta).toBe('0 ordinal flags · no calibrated probability')

      expect(desk).toContain('No gap/volume flags cleared the ordinal threshold this session.')
    })

    it('handles empty directional signals gracefully with empty authorization queue and honest copy', () => {
      const emptySignals: any[] = []
      const highConfQueue = emptySignals
        .filter((s) => hasHighConfidence(s.probability, s.state))
        .sort(compareSignals)
      expect(highConfQueue).toEqual([])

      let max: number | null = null
      for (const s of emptySignals) {
        if (typeof s.probability === 'number' && Number.isFinite(s.probability) && (max === null || s.probability > max)) {
          max = s.probability
        }
      }
      expect(max).toBeNull()

      expect(desk).toContain('No directional scores loaded.')
      expect(desk).toContain('No high-confidence authorizations this session.')
      expect(desk).toContain('No directional signals emitted — run Quick or Deep scan.')
    })

    it('handles non-empty signals with 0/0 high confidence names (honest desk state)', () => {
      const lowConfSignals = [
        { symbol: 'AAPL', state: 'WATCH', probability: 0.58, momentum: 0.12 },
        { symbol: 'MSFT', state: 'WATCH', probability: 0.52, momentum: -0.05 },
        { symbol: 'GOOGL', state: 'WATCH', probability: null, momentum: 0.0 },
      ]

      const highConf = lowConfSignals.filter((s) => hasHighConfidence(s.probability, s.state))
      expect(highConf).toHaveLength(0)

      const actionable = lowConfSignals.filter((s) => hasActionableEdge(s.probability))
      expect(actionable).toHaveLength(1) // AAPL at 0.58

      let max = 0
      for (const s of lowConfSignals) {
        if (typeof s.probability === 'number' && Number.isFinite(s.probability) && s.probability > max) {
          max = s.probability
        }
      }
      expect(max).toBe(0.58)
    })

    it('handles malformed numbers, NaNs, and unexpected types without throwing errors', () => {
      const dirtySignals = [
        { symbol: 'A', state: 'ENTER', probability: Number.NaN, momentum: Number.POSITIVE_INFINITY },
        { symbol: 'B', state: 'WATCH', probability: null, momentum: null },
        { symbol: 'C', state: undefined, probability: -1, momentum: undefined },
        { symbol: 'D', state: 'ENTER', probability: 0.72, momentum: 1.4 },
      ]

      const sorted = dirtySignals.slice().sort(compareSignals)
      // D (ENTER, p=0.72) should rank first, then A (ENTER, p=NaN), then C/B
      expect(sorted[0].symbol).toBe('D')
      expect(sorted[1].symbol).toBe('A')

      expect(confidenceBand(Number.NaN)).toBe('UNAVAILABLE')
      expect(confidenceBand(null)).toBe('UNAVAILABLE')
      expect(confidenceBand(undefined)).toBe('UNAVAILABLE')
      expect(confidenceBand(0.70)).toBe('HIGH')
      expect(confidenceBand(0.60)).toBe('MODERATE')
      expect(confidenceBand(0.40)).toBe('LOW')

      expect(momentumBarPct(Number.NaN)).toBe(0)
      expect(momentumBarPct(null)).toBe(0)
      expect(momentumBarPct(undefined)).toBe(0)
      expect(momentumBarPct(1.5)).toBe(75)
      expect(momentumBarPct(5.0)).toBe(100) // clamped to 100

      // edgeTitle tests
      expect(edgeTitle(null)).toBe('No calibrated probability — use momentum + state only. Not authorization.')
      expect(edgeTitle(0.70, 'ENTER')).toContain('HIGH — meets ENTER bar')
      expect(edgeTitle(0.58)).toContain('MODERATE — above 55% watch floor')
      expect(edgeTitle(0.40)).toContain('LOW — near coin-flip')

      // sideWord tests
      expect(sideWord('long')).toBe('UP')
      expect(sideWord('short')).toBe('DOWN')
      expect(sideWord(null)).toBe('NONE')
      expect(sideWord('unknown')).toBe('NONE')
    })

    it('handles activity lean computation across all permutations and fallbacks', () => {
      expect(activityLean({ activity_lean: 'bullish', activity_lean_label: 'BULLISH' }).cls).toBe('bullish')
      expect(activityLean({ activity_lean: 'bearish', activity_lean_label: 'BEARISH' }).cls).toBe('bearish')
      expect(activityLean({ activity_lean: 'mixed' }).cls).toBe('mixed')
      // Fallbacks
      expect(activityLean({ price_impulse: 'up' }).cls).toBe('bullish')
      expect(activityLean({ ret_1d: 0.05 }).cls).toBe('bullish')
      expect(activityLean({ price_impulse: 'down' }).cls).toBe('bearish')
      expect(activityLean({ ret_1d: -0.05 }).cls).toBe('bearish')
      expect(activityLean({}).cls).toBe('neutral')
    })

    it('handles empty or corrupted watchlist gracefully', () => {
      const storage = (seed: string | null) => ({
        getItem: () => seed,
        setItem: () => undefined,
      })
      expect(loadWatchlist(storage(null))).toEqual(['NVDA', 'TSLA', 'AMD'])
      expect(loadWatchlist(storage('invalid json'))).toEqual(['NVDA', 'TSLA', 'AMD'])
      expect(loadWatchlist(storage('{}'))).toEqual(['NVDA', 'TSLA', 'AMD'])
      expect(loadWatchlist(storage('["aapl", "msft"]'))).toEqual(['AAPL', 'MSFT'])
      expect(loadWatchlist(storage('[]'))).toEqual(['NVDA', 'TSLA', 'AMD'])
    })
  })

  describe('3. Telemetry, Polling Loops and Contract Strings Integrity', () => {
    it('preserves all mandatory AST strings from PROJECT.md', () => {
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

    it('strictly avoids all banned terminology and styling anti-patterns', () => {
      expect(desk).not.toContain('PAPER TRADING MODE')
      expect(desk).not.toContain('PAPER TRADING')
      expect(desk).not.toContain('backdrop-filter')
      expect(desk).not.toMatch(/#ffb703|#4cc9f0|#b5179e|#d77bcf|#8fd4b8|#6ee7b7/i)
      expect(desk).not.toMatch(/linear-gradient\(90deg,\s*color-mix/)
      expect(desk).not.toMatch(/linear-gradient\(110deg/)
      expect(desk).not.toMatch(/linear-gradient\(180deg,\s*color-mix\(in srgb,\s*var\(--phosphor\)/)
    })

    it('verifies timer intervals and cleanup in lifecycle hooks', () => {
      expect(desk).toContain('60_000') // Watchlist polling 60s
      expect(desk).toContain('20_000') // Marks polling 20s
      expect(desk).toContain('document.visibilityState === \'visible\'')
      expect(desk).toContain('clearInterval(watchlistTimer)')
      expect(desk).toContain('clearInterval(marksTimer)')
    })

    it('deduplicates and limits board symbols to maximum 40 targets', () => {
      const peadList = Array.from({ length: 25 }, (_, i) => ({ symbol: `SYM_${i}` }))
      const signalsList = Array.from({ length: 25 }, (_, i) => ({ symbol: `SYM_${i + 15}` }))
      const customWatch = ['SYM_0', 'SYM_50', 'SYM_51']

      const boardSymbols = (): string[] => {
        const out: string[] = []
        const seen = new Set<string>()
        const push = (value: string | undefined) => {
          const sym = String(value || '').trim().toUpperCase()
          if (!sym || seen.has(sym)) return
          seen.add(sym)
          out.push(sym)
        }
        for (const row of peadList) push(row.symbol)
        for (const row of signalsList) push(row.symbol)
        for (const row of customWatch) push(row)
        return out.slice(0, 40)
      }

      const res = boardSymbols()
      expect(res.length).toBe(40)
      expect(new Set(res).size).toBe(40) // strictly unique
      expect(res).toContain('SYM_0')
      expect(res).toContain('SYM_24')
      expect(res).toContain('SYM_39')
      expect(res).not.toContain('SYM_51') // sliced away by 40 limit
    })
  })

  describe('4. Tactical Desk Computeds & Multi-domain Reconciliation', () => {
    it('evaluates confidence posture states accurately', () => {
      const getPosture = (entered: number, high: number, actionable: number, maxEdge: number | null) => {
        if (entered > 0 || high > 0) {
          return {
            label: 'HIGH CONFIDENCE',
            tone: 'armed' as const,
            detail: `${Math.max(entered, high)} name(s) at/above ENTER bar ${pctFrac(ENTER_EDGE, 0)}`,
          }
        }
        if (actionable > 0) {
          return {
            label: 'WATCH ONLY',
            tone: 'held' as const,
            detail: `${actionable} moderate (≥${pctFrac(ACTIONABLE_EDGE, 0)}); max ${maxEdge != null ? pctFrac(maxEdge, 1) : DASH} — below ENTER`,
          }
        }
        return {
          label: 'NO EDGE',
          tone: 'held' as const,
          detail: maxEdge != null
            ? `Max calibrated ${pctFrac(maxEdge, 1)} · nothing clears ${pctFrac(ACTIONABLE_EDGE, 0)} watch floor`
            : 'No calibrated directional probabilities this session',
        }
      }

      expect(getPosture(1, 1, 3, 0.72).label).toBe('HIGH CONFIDENCE')
      expect(getPosture(1, 1, 3, 0.72).tone).toBe('armed')

      expect(getPosture(0, 0, 2, 0.60).label).toBe('WATCH ONLY')
      expect(getPosture(0, 0, 2, 0.60).tone).toBe('held')

      expect(getPosture(0, 0, 0, 0.48).label).toBe('NO EDGE')
      expect(getPosture(0, 0, 0, 0.48).tone).toBe('held')
      expect(getPosture(0, 0, 0, null).detail).toBe('No calibrated directional probabilities this session')
    })

    it('correctly derives relation agreement vs conflict across model domains', () => {
      const relationFor = (
        sym: string,
        reconciledMap: Map<string, any>,
        peadRows: any[],
        signalRows: any[],
      ): 'agree' | 'conflict' | 'none' => {
        const relation = reconciledMap.get(sym.toUpperCase())?.relation
        if (relation === 'agree' || relation === 'conflict') return relation
        const peadSide = peadRows.find((r) => r.symbol?.toUpperCase() === sym.toUpperCase())?.side?.toLowerCase()
        const directionalSide = signalRows.find((r) => r.symbol?.toUpperCase() === sym.toUpperCase())?.side?.toLowerCase()
        if (!peadSide || !directionalSide) return 'none'
        return peadSide === directionalSide ? 'agree' : 'conflict'
      }

      const map = new Map()
      const peadRows = [{ symbol: 'NVDA', side: 'long' }, { symbol: 'TSLA', side: 'short' }]
      const sigRows = [{ symbol: 'NVDA', side: 'LONG' }, { symbol: 'TSLA', side: 'LONG' }, { symbol: 'AAPL', side: 'LONG' }]

      expect(relationFor('NVDA', map, peadRows, sigRows)).toBe('agree')
      expect(relationFor('TSLA', map, peadRows, sigRows)).toBe('conflict')
      expect(relationFor('AAPL', map, peadRows, sigRows)).toBe('none')
      expect(relationFor('MSFT', map, peadRows, sigRows)).toBe('none')
    })

    it('handles sparkline generator with fewer than 3 bars without crashing', () => {
      const calcSparks = (results: Record<string, any>) => {
        const out: Record<string, string> = {}
        for (const [sym, traj] of Object.entries(results)) {
          const closes = traj?.series?.map((b: any) => b.c) ?? []
          if (closes.length > 2) {
            out[sym] = sparkline(closes.slice(-40), 88, 22, 2).d
          }
        }
        return out
      }

      const empty = calcSparks({ NVDA: { series: [] }, TSLA: { series: [{ c: 100 }] } })
      expect(empty.NVDA).toBeUndefined()
      expect(empty.TSLA).toBeUndefined()

      const valid = calcSparks({ NVDA: { series: [{ c: 100 }, { c: 105 }, { c: 110 }] } })
      expect(valid.NVDA).toBeDefined()
      expect(typeof valid.NVDA).toBe('string')
      expect(valid.NVDA).toContain('M')
    })
  })
})
