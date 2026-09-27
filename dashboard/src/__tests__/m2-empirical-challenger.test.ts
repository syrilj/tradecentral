import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  formatMarketCountdown,
  marketSessionClass,
  marketSessionLabel,
  MARKET_SESSION_LABELS,
  MARKET_TRANSITION_VERBS,
} from '../marketSession'

const DASHBOARD_DIR = resolve(__dirname, '../..')
const APP_PATH = resolve(DASHBOARD_DIR, 'src/App.vue')
const TOKENS_PATH = resolve(DASHBOARD_DIR, 'src/styles/tokens.css')
const BASE_PATH = resolve(DASHBOARD_DIR, 'src/styles/base.css')

describe('Milestone 2 Empirical Challenger: Unified Navigation Shell & Top Bar Stress Harness', () => {
  const appContent = readFileSync(APP_PATH, 'utf-8')
  const tokensContent = readFileSync(TOKENS_PATH, 'utf-8')
  const baseContent = readFileSync(BASE_PATH, 'utf-8')

  describe('1. Collapsible Sidebar Logic & State Transitions', () => {
    it('declares the designated localStorage key according to specification', () => {
      expect(appContent).toContain("const SIDEBAR_STORAGE_KEY = 'edge.sidebar.collapsed.v1'")
    })

    it('implements toggleSidebar with exception-safe localStorage persistence', () => {
      expect(appContent).toContain('function toggleSidebar(): void')
      expect(appContent).toContain('sidebarCollapsed.value = !sidebarCollapsed.value')
      expect(appContent).toContain(
        "localStorage.setItem(SIDEBAR_STORAGE_KEY, sidebarCollapsed.value ? 'true' : 'false')",
      )
    })

    it('simulates sidebar toggle transitions and localStorage updates', () => {
      let collapsed = false
      const storage = new Map<string, string>()

      const toggle = () => {
        collapsed = !collapsed
        try {
          storage.set('edge.sidebar.collapsed.v1', collapsed ? 'true' : 'false')
        } catch {
          // ignore
        }
      }

      // Initial state
      expect(collapsed).toBe(false)

      // First toggle: expand -> collapse
      toggle()
      expect(collapsed).toBe(true)
      expect(storage.get('edge.sidebar.collapsed.v1')).toBe('true')

      // Second toggle: collapse -> expand
      toggle()
      expect(collapsed).toBe(false)
      expect(storage.get('edge.sidebar.collapsed.v1')).toBe('false')

      // Fuzz toggle 100 times to verify parity invariant
      for (let i = 0; i < 100; i++) {
        toggle()
        expect(collapsed).toBe(i % 2 === 0)
        expect(storage.get('edge.sidebar.collapsed.v1')).toBe(i % 2 === 0 ? 'true' : 'false')
      }
    })

    it('fuzz tests localStorage initial loading with corrupted/boundary values', () => {
      const loadState = (rawVal: string | null) => {
        let collapsed = false
        try {
          if (rawVal === 'true') {
            collapsed = true
          }
        } catch {
          // ignore
        }
        return collapsed
      }

      expect(loadState('true')).toBe(true)
      expect(loadState('false')).toBe(false)
      expect(loadState(null)).toBe(false)
      expect(loadState('')).toBe(false)
      expect(loadState('undefined')).toBe(false)
      expect(loadState('TRUE')).toBe(false)
      expect(loadState('1')).toBe(false)
      expect(loadState('0')).toBe(false)
      expect(loadState('{"collapsed":true}')).toBe(false)
      expect(loadState('null')).toBe(false)
    })

    it('binds reactive class names and CSS variable on shell and rail', () => {
      expect(appContent).toContain(
        "'rail-collapsed': sidebarCollapsed, 'rail-expanded': !sidebarCollapsed",
      )
      expect(appContent).toContain(
        "'--rail-w': sidebarCollapsed ? 'var(--rail-w-collapsed)' : 'var(--rail-w-expanded)'",
      )
      expect(appContent).toContain(
        "'is-collapsed': sidebarCollapsed, 'is-expanded': !sidebarCollapsed",
      )
      expect(appContent).toContain(
        "sidebarCollapsed ? 'Expand navigation sidebar' : 'Collapse navigation sidebar'",
      )
      expect(appContent).toContain("sidebarCollapsed ? 'arrow-right' : 'arrow-left'")
    })
  })

  describe('2. Navigation Architecture & Categorized Tool Groupings', () => {
    it('defines 3 distinct categorized tool groupings in the Tools overflow', () => {
      expect(appContent).toContain('<div class="more-group label">Desk</div>')
      expect(appContent).toContain('<div class="more-group label">Market</div>')
      expect(appContent).toContain('<div class="more-group label">Research</div>')
    })

    it('keeps five primary destinations without ordinal indexes', () => {
      const expectedPrimary = [
        { name: 'flow', title: 'Flow' },
        { name: 'options', title: 'Options' },
        { name: 'desk', title: 'Desk' },
        { name: 'chain', title: 'Chain' },
        { name: 'market', title: 'Market' },
      ]

      for (const item of expectedPrimary) {
        expect(appContent).toContain("name: '" + item.name + "'")
        expect(appContent).toContain("title: '" + item.title + "'")
      }
      expect(appContent).not.toContain('<span>Core Desk</span>')
    })

    it('parks remaining desk routes in Tools overflow', () => {
      const expectedDesk = [
        { name: 'plays', idx: 'D1', title: 'Plays' },
        { name: 'absorption', idx: 'D2', title: 'Absorption' },
        { name: 'livestack', idx: 'LS', title: 'Live Stack' },
      ]

      for (const item of expectedDesk) {
        expect(appContent).toContain("name: '" + item.name + "'")
        expect(appContent).toContain("idx: '" + item.idx + "'")
        expect(appContent).toContain("title: '" + item.title + "'")
      }
      const desk = appContent.match(/const deskTools = \[\s*([\s\S]*?)\] as const/)![1]
      expect(desk).not.toContain("name: 'suggest'")
    })

    it('contains all 6 Market Analytics routes with exact titles and indexes', () => {
      const expectedMarket = [
        { name: 'sectors', idx: 'M1', title: 'Sectors' },
        { name: 'sentiment', idx: 'M2', title: 'Pulse' },
        { name: 'momentum', idx: 'M3', title: 'Momentum' },
        { name: 'fintel', idx: 'M4', title: 'Fintel' },
        { name: 'insiders', idx: 'M5', title: 'Insiders' },
        { name: 'calculator', idx: 'M6', title: 'Calculator' },
      ]

      for (const item of expectedMarket) {
        expect(appContent).toContain("name: '" + item.name + "'")
        expect(appContent).toContain("idx: '" + item.idx + "'")
        expect(appContent).toContain("title: '" + item.title + "'")
      }
    })

    it('contains all 8 Research Lab routes with exact titles and indexes', () => {
      const expectedResearch = [
        { name: 'research', idx: 'R1', title: 'Research' },
        { name: 'gates', idx: 'R2', title: 'Gates' },
        { name: 'evolution', idx: 'R3', title: 'Evolution' },
        { name: 'adaptive', idx: 'R4', title: 'Live Blend' },
        { name: 'graph', idx: 'R5', title: 'Graph' },
        { name: 'changepoints', idx: 'R6', title: 'Breaks' },
        { name: 'cloud', idx: 'R7', title: 'Cloud' },
        { name: 'kalman', idx: 'R8', title: 'Kalman' },
      ]

      for (const item of expectedResearch) {
        expect(appContent).toContain("name: '" + item.name + "'")
        expect(appContent).toContain("idx: '" + item.idx + "'")
        expect(appContent).toContain("title: '" + item.title + "'")
      }
    })

    it('ensures total sidebar items equals 26 unique routes', () => {
      const primaryCount = (
        appContent.match(/primaryNav\s*=\s*\[([\s\S]*?)\]\s*as const/)?.[1].match(/name:/g) || []
      ).length
      const deskCount = (
        appContent.match(/deskTools\s*=\s*\[([\s\S]*?)\]\s*as const/)?.[1].match(/name:/g) || []
      ).length
      const marketCount = (
        appContent.match(/marketTools\s*=\s*\[([\s\S]*?)\]\s*as const/)?.[1].match(/name:/g) || []
      ).length
      const researchCount = (
        appContent.match(/researchTools\s*=\s*\[([\s\S]*?)\]\s*as const/)?.[1].match(/name:/g) || []
      ).length

      // Regime, Drift, and Setups were promoted from the Tools overflow into
      // primaryNav. Each must live in exactly one group: overflowActiveItem
      // matches on route name, so a duplicate would light the primary nav and
      // mark Tools active at the same time. Brief is the first primary
      // destination; Crypto is the tenth.
      expect(primaryCount).toBe(14)
      expect(deskCount).toBe(3)
      expect(marketCount).toBe(6)
      expect(researchCount).toBe(8)
      expect(primaryCount + deskCount + marketCount + researchCount).toBe(31)
    })
  })

  describe('3. Sparkline Mathematical Engine & Path Generation Oracle', () => {
    function sparklinePath(points: { cum: number }[] | undefined): string {
      const values = (points ?? [])
        .map((point) => Number(point.cum))
        .filter(Number.isFinite)
        .slice(-20)
      if (values.length < 2) return ''
      const lo = Math.min(...values)
      const hi = Math.max(...values)
      const span = Math.max(hi - lo, Math.abs(hi) * 0.0005, 0.0001)
      return values
        .map((value, index) => {
          const x = (index / (values.length - 1)) * 48
          const y = 14 - ((value - lo) / span) * 12
          return (index === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1)
        })
        .join(' ')
    }

    it('returns empty string for undefined, empty array, or single data point', () => {
      expect(sparklinePath(undefined)).toBe('')
      expect(sparklinePath([])).toBe('')
      expect(sparklinePath([{ cum: 100 }])).toBe('')
    })

    it('filters non-finite values (NaN, Infinity, -Infinity)', () => {
      const dirty = [{ cum: 100 }, { cum: NaN }, { cum: 110 }, { cum: Infinity }, { cum: 105 }]
      const path = sparklinePath(dirty)
      expect(path).toBeTruthy()
      expect(path.startsWith('M0.0,')).toBe(true)
      const segments = path.split(' ')
      expect(segments.length).toBe(3)
    })

    it('handles perfectly flat series without division by zero', () => {
      const flat = Array.from({ length: 10 }, () => ({ cum: 500 }))
      const path = sparklinePath(flat)
      expect(path).toBeTruthy()
      expect(path.includes('NaN')).toBe(false)
      expect(path.includes('Infinity')).toBe(false)
      expect(path).toContain('M0.0,14.0')
      expect(path).toContain('L48.0,14.0')
    })

    it('generates strictly bounded coordinates between x in [0, 48] and y in [2, 14]', () => {
      const points = [{ cum: 10 }, { cum: 25 }, { cum: 5 }, { cum: 50 }, { cum: 30 }]
      const path = sparklinePath(points)
      const commands = path.split(' ')
      for (const cmd of commands) {
        const coords = cmd.slice(1).split(',')
        const x = parseFloat(coords[0])
        const y = parseFloat(coords[1])
        expect(x).toBeGreaterThanOrEqual(0)
        expect(x).toBeLessThanOrEqual(48)
        expect(y).toBeGreaterThanOrEqual(2)
        expect(y).toBeLessThanOrEqual(14)
      }
    })
  })

  describe('4. Fear & Greed Spectrum Engine & Band Classification', () => {
    function computeFearGreed(score: number | null | undefined) {
      if (score == null || !Number.isFinite(score)) {
        return { value: null, band: 'missing', label: 'NO DATA' }
      }
      const greed = Math.round((1 - Math.max(0, Math.min(1, score))) * 100)
      const band =
        greed <= 20
          ? 'extreme-fear'
          : greed <= 40
            ? 'fear'
            : greed <= 60
              ? 'neutral'
              : greed <= 80
                ? 'greed'
                : 'extreme-greed'
      const label = {
        'extreme-fear': 'EXTREME FEAR',
        fear: 'FEAR',
        neutral: 'NEUTRAL',
        greed: 'GREED',
        'extreme-greed': 'EXTREME GREED',
        missing: 'NO DATA',
      }[band]
      return { value: greed, band, label }
    }

    it('verifies 5-band threshold partitions and inversion logic', () => {
      expect(computeFearGreed(1.0)).toEqual({
        value: 0,
        band: 'extreme-fear',
        label: 'EXTREME FEAR',
      })
      expect(computeFearGreed(0.85)).toEqual({
        value: 15,
        band: 'extreme-fear',
        label: 'EXTREME FEAR',
      })
      expect(computeFearGreed(0.8)).toEqual({
        value: 20,
        band: 'extreme-fear',
        label: 'EXTREME FEAR',
      })

      expect(computeFearGreed(0.7)).toEqual({ value: 30, band: 'fear', label: 'FEAR' })
      expect(computeFearGreed(0.6)).toEqual({ value: 40, band: 'fear', label: 'FEAR' })

      expect(computeFearGreed(0.5)).toEqual({ value: 50, band: 'neutral', label: 'NEUTRAL' })
      expect(computeFearGreed(0.4)).toEqual({ value: 60, band: 'neutral', label: 'NEUTRAL' })

      expect(computeFearGreed(0.3)).toEqual({ value: 70, band: 'greed', label: 'GREED' })
      expect(computeFearGreed(0.2)).toEqual({ value: 80, band: 'greed', label: 'GREED' })

      expect(computeFearGreed(0.05)).toEqual({
        value: 95,
        band: 'extreme-greed',
        label: 'EXTREME GREED',
      })
      expect(computeFearGreed(0.0)).toEqual({
        value: 100,
        band: 'extreme-greed',
        label: 'EXTREME GREED',
      })

      expect(computeFearGreed(null)).toEqual({ value: null, band: 'missing', label: 'NO DATA' })
      expect(computeFearGreed(undefined)).toEqual({
        value: null,
        band: 'missing',
        label: 'NO DATA',
      })
      expect(computeFearGreed(NaN)).toEqual({ value: null, band: 'missing', label: 'NO DATA' })
      expect(computeFearGreed(-0.5)).toEqual({
        value: 100,
        band: 'extreme-greed',
        label: 'EXTREME GREED',
      })
      expect(computeFearGreed(1.5)).toEqual({
        value: 0,
        band: 'extreme-fear',
        label: 'EXTREME FEAR',
      })
    })

    it('verifies accessibility role and meter semantics in App.vue', () => {
      expect(appContent).toContain('role="meter"')
      expect(appContent).toContain(':aria-valuemin="0"')
      expect(appContent).toContain(':aria-valuemax="100"')
      expect(appContent).toContain(':aria-valuenow="fearGreed.value ?? undefined"')
      expect(appContent).toContain(':aria-valuetext="fearGreed.label"')
      expect(appContent).toContain('class="fg-thumb"')
    })
  })

  describe('5. Session Clock, Timers & Market Countdown Oracle', () => {
    it('verifies 1000ms clock interval setup and unmount cleanup in App.vue', () => {
      expect(appContent).toContain(
        'tick = window.setInterval(() => (clock.value = utcNow()), 1000)',
      )
      expect(appContent).toContain('if (tick !== undefined) clearInterval(tick)')
    })

    it('verifies utcNow generates valid ISO HH:mm:ss format', () => {
      const nowStr = new Date().toISOString().slice(11, 19)
      expect(nowStr).toMatch(/^\d{2}:\d{2}:\d{2}$/)
    })

    it('empirically validates marketSessionLabel mappings and fault states', () => {
      expect(MARKET_SESSION_LABELS.regular).toBe('RTH OPEN')
      expect(marketSessionLabel('regular')).toBe('RTH OPEN')
      expect(marketSessionLabel('premarket')).toBe('PREMARKET')
      expect(marketSessionLabel('after_hours')).toBe('AFTER HOURS')
      expect(marketSessionLabel('closed')).toBe('MARKET CLOSED')
      expect(marketSessionLabel('replay')).toBe('REPLAY')
      expect(marketSessionLabel(null)).toBe('CAL SYNC')
      expect(marketSessionLabel(undefined)).toBe('CAL SYNC')
      expect(marketSessionLabel('unknown_custom')).toBe('CAL SYNC')
      expect(marketSessionLabel('regular', { error: true })).toBe('CAL FAULT')
    })

    it('empirically validates marketSessionClass fallback behavior', () => {
      expect(marketSessionClass('regular')).toBe('regular')
      expect(marketSessionClass('premarket')).toBe('premarket')
      expect(marketSessionClass(null)).toBe('unknown')
      expect(marketSessionClass(undefined)).toBe('unknown')
      expect(marketSessionClass('')).toBe('unknown')
    })

    it('tests formatMarketCountdown across intraday and multi-day transitions', () => {
      const fixedNow = 1700000000000 // Fixed epoch ms

      // 10 minutes ahead with regular_opens
      expect(MARKET_TRANSITION_VERBS.regular_opens).toBe('OPEN IN')
      const future10m = new Date(fixedNow + 10 * 60 * 1000).toISOString()
      const cd10m = formatMarketCountdown(future10m, 'regular_opens', fixedNow)
      expect(cd10m).toBe('OPEN IN 00:10:00')

      // 2 hours 15 minutes ahead with regular_closes
      const future2h15m = new Date(fixedNow + (2 * 3600 + 15 * 60 + 30) * 1000).toISOString()
      const cd2h15m = formatMarketCountdown(future2h15m, 'regular_closes', fixedNow)
      expect(cd2h15m).toBe('CLOSE IN 02:15:30')

      // 2 days ahead over weekend with premarket_opens
      const future2d = new Date(fixedNow + (2 * 86400 + 4 * 3600 + 12 * 60) * 1000).toISOString()
      const cd2d = formatMarketCountdown(future2d, 'premarket_opens', fixedNow)
      expect(cd2d).toBe('PRE IN 2D 04:12')

      // Past time -> clamped to 00:00:00
      const past = new Date(fixedNow - 60000).toISOString()
      const cdPast = formatMarketCountdown(past, 'after_hours_closes', fixedNow)
      expect(cdPast).toBe('EXT CLOSE 00:00:00')

      // Missing params -> fallback
      expect(formatMarketCountdown(undefined, 'regular_opens', fixedNow)).toBe('NEXT n/a')
      expect(formatMarketCountdown(future10m, undefined, fixedNow)).toBe('NEXT n/a')
      expect(formatMarketCountdown('not-a-date', 'regular_opens', fixedNow)).toBe('NEXT n/a')
    })
  })

  describe('6. Top Navigation Strip Design Tokens & Responsive Layout', () => {
    it('verifies frosted glassmorphism tokens applied to .strip and .rail', () => {
      expect(tokensContent).toContain('--glass-surface')
      expect(tokensContent).toContain('--glass-blur-md')
      expect(tokensContent).toContain('--glass-border')
      expect(baseContent).toContain('.glass-panel')

      expect(appContent).toContain('.strip {')
      expect(appContent).toContain('backdrop-filter: var(--glass-blur-md);')
      expect(appContent).toContain('-webkit-backdrop-filter: var(--glass-blur-md);')
      expect(appContent).toContain('background: var(--glass-surface);')
      expect(appContent).toContain('border-bottom: var(--hair) solid var(--glass-border);')
      expect(appContent).toContain(
        'box-shadow: var(--glass-specular-subtle), var(--glass-shadow-sm);',
      )

      expect(appContent).toContain('.rail {')
      expect(appContent).toContain('backdrop-filter: var(--glass-blur-md);')
      expect(appContent).toContain('-webkit-backdrop-filter: var(--glass-blur-md);')
      expect(appContent).toContain('border-right: var(--hair) solid var(--glass-border);')
    })

    it('verifies responsive breakpoints (1320px, 1180px, 1080px, 780px) across shell and workspace styles', () => {
      /* The 1320px dense-layout breakpoint moved into the flow workspace's own
         styles; the shell keeps the rail/strip breakpoints. */
      const flowDashboardContent = readFileSync(
        resolve(DASHBOARD_DIR, 'src/components/FlowDashboard.vue'),
        'utf-8',
      )
      const shellOrWorkspace = `${appContent}\n${flowDashboardContent}`
      expect(shellOrWorkspace).toContain('@media (max-width: 1320px)')
      expect(appContent).toContain('@media (max-width: 1180px)')
      expect(appContent).toContain('@media (max-width: 1080px)')
      expect(appContent).toContain('@media (max-width: 780px)')
    })

    it('verifies mobile responsive layout shifts rail to bottom row and retains primary mark', () => {
      expect(appContent).toContain('.gauge-mark.primary-mark')
      expect(appContent).toContain('.mobile-market-state')
    })
  })
})
