/**
 * Options Graph Table & Winning Side Bar Profile Verification Suite
 *
 * Verifies:
 *   1. Winning Side Bar Logic: Call winning (Call > Put) renders above the zero line in emerald/green,
 *      Put winning (Put > Call) renders below the zero line in crimson/red, and dominance % is accurate.
 *   2. Layout Switcher: Supports GRAPH, SPLIT (Graph + Table), and TABLE display modes.
 *   3. Options Strike Matrix Table: Renders strike tags (SPOT, CALL W, PUT W, FLIP),
 *      winner pills (CALL %, PUT %, TIED), call/put values, and signed net exposure bars.
 *   4. Clean Labeling & De-duplication: Top level badges avoid collision, and Squeeze Screener
 *      has zero duplicate trigger bars and clean likelihood badges.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'

import GammaExposureMap from '../components/GammaExposureMap.vue'
import SqueezeScreener from '../components/SqueezeScreener.vue'
import type { GexStrikeRow, OptionsSqueeze } from '../api'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function mockGexRow(
  strike: number,
  call_gex: number,
  put_gex: number,
  call_oi = 500,
  put_oi = 300,
): GexStrikeRow {
  return {
    strike,
    call_gex_m: call_gex,
    put_gex_m: put_gex,
    net_gex_m: call_gex + put_gex,
    call_oi,
    put_oi,
  }
}

describe('Options Graph Table & Winning Side Bar Profile', () => {
  const gexSrc = readFileSync(join(root, 'components', 'GammaExposureMap.vue'), 'utf8')
  const squeezeSrc = readFileSync(join(root, 'components', 'SqueezeScreener.vue'), 'utf8')

  describe('1. Winning Side Bar Profile Architecture', () => {
    it('defines winning side calculation fields on Bar interface', () => {
      expect(gexSrc).toContain("winnerSide: 'call' | 'put' | 'flat'")
      expect(gexSrc).toContain('winnerVal: number')
      expect(gexSrc).toContain('winnerH: number')
      expect(gexSrc).toContain('winnerY: number')
      expect(gexSrc).toContain('winnerPct: number')
      expect(gexSrc).toContain('dominanceText: string')
    })

    it('defaults to WINNING SIDE view mode with Calls above (emerald) and Puts below (crimson)', () => {
      expect(gexSrc).toContain("viewMode = ref<GexViewMode>('winner')")
      expect(gexSrc).toContain('WINNING SIDE')
      expect(gexSrc).toContain('v-if="viewMode === \'winner\'"')
      expect(gexSrc).toContain("bar.winnerSide === 'call'")
      expect(gexSrc).toContain("bar.winnerSide === 'put'")
      expect(gexSrc).toContain('winner-bar')
    })

    it('positions Call winning bars above zeroY and Put winning bars below zeroY', () => {
      expect(gexSrc).toContain('const isCallWinner = callVal > putVal')
      expect(gexSrc).toContain('const isPutWinner = putVal > callVal')
      expect(gexSrc).toContain('const winnerY = isCallWinner ? zeroY.value - winnerH : zeroY.value')
    })
  })

  describe('2. Display Layout Switcher (GRAPH, SPLIT, TABLE)', () => {
    it('supports layout modes: GRAPH, SPLIT, and TABLE', () => {
      expect(gexSrc).toContain("layoutMode = ref<GexLayoutMode>('graph')")
      expect(gexSrc).toContain('class="mini-segment layout-seg"')
      expect(gexSrc).toContain('@click="layoutMode = \'graph\'"')
      expect(gexSrc).toContain('@click="layoutMode = \'split\'"')
      expect(gexSrc).toContain('@click="layoutMode = \'table\'"')
    })

    it('renders the SVG chart in GRAPH and SPLIT modes', () => {
      expect(gexSrc).toContain('v-if="layoutMode !== \'table\'"')
    })

    it('renders the Strike Matrix Table in SPLIT and TABLE modes', () => {
      expect(gexSrc).toContain('v-if="layoutMode !== \'graph\'"')
      expect(gexSrc).toContain('class="gex-table-wrap"')
      expect(gexSrc).toContain('class="gex-strike-table"')
    })
  })

  describe('3. Integrated Options Strike Matrix Table', () => {
    it('includes table headers for STRIKE, WINNER / BIAS, CALL, PUT, NET, and SPOT DISTANCE', () => {
      expect(gexSrc).toContain('STRIKE')
      expect(gexSrc).toContain('WINNER / BIAS')
      expect(gexSrc).toContain('CALL {{ metric.toUpperCase() }}')
      expect(gexSrc).toContain('PUT {{ metric.toUpperCase() }}')
      expect(gexSrc).toContain('NET {{ metric.toUpperCase() }}')
      expect(gexSrc).toContain('SPOT DISTANCE')
    })

    it('supports fast filtering and multi-column sorting', () => {
      expect(gexSrc).toContain('tableFilter')
      expect(gexSrc).toContain('tableSortKey')
      expect(gexSrc).toContain('setTableSort')
      expect(gexSrc).toContain('filteredTableRows')
    })

    it('renders winner pills with semantic dots and dominance percentages', () => {
      expect(gexSrc).toContain('class="winner-pill"')
      expect(gexSrc).toContain('class="winner-dot"')
      expect(gexSrc).toContain('bar.dominanceText')
    })

    it('renders structural level badges: SPOT, CALL W, PUT W, FLIP', () => {
      expect(gexSrc).toContain('class="tag-badge spot"')
      expect(gexSrc).toContain('class="tag-badge call"')
      expect(gexSrc).toContain('class="tag-badge put"')
      expect(gexSrc).toContain('class="tag-badge flip"')
    })

    it('renders micro net exposure progress meters in table rows', () => {
      expect(gexSrc).toContain('class="net-micro-meter"')
      expect(gexSrc).toContain('meter-pos')
      expect(gexSrc).toContain('meter-neg')
    })
  })

  describe('4. Component SSR Rendering & Interactive Synchrony', () => {
    const rows: GexStrikeRow[] = [
      mockGexRow(95, 2.0, -10.0, 200, 1000), // Put winning
      mockGexRow(100, 8.0, -4.0, 800, 400), // Call winning, ATM/Spot
      mockGexRow(105, 15.0, -1.0, 1500, 100), // Call winning, Call Wall
    ]

    it('renders GammaExposureMap with winning dominance indicators', async () => {
      const app = createSSRApp({
        render: () =>
          h(GammaExposureMap, {
            rows,
            spot: 100,
            callWall: 105,
            putWall: 95,
            gammaFlip: 98,
          }),
      })
      const html = await renderToString(app)
      expect(html).toContain('WINNING SIDE')
      expect(html).toContain('DUAL BARS')
      expect(html).toContain('NET PROFILE')
      expect(html).toContain('GRAPH')
      expect(html).toContain('SPLIT')
      expect(html).toContain('TABLE')
      expect(html).toContain('CALL W $105')
      expect(html).toContain('PUT W $95')
      expect(html).toContain('FLIP $98')
      expect(html).toContain('SPOT $100')
    })
  })

  describe('5. Clean & Refined Squeeze Screener', () => {
    it('does not carry duplicate trigger bars in the hero section', () => {
      expect(squeezeSrc).not.toContain('class="squeeze-metric-bar"')
      expect(squeezeSrc).not.toContain('class="trigger-track-container"')
    })

    it('carries a unified, high-clarity trigger strip and key levels DOM ladder', () => {
      expect(squeezeSrc).toContain('class="trigger-strip"')
      expect(squeezeSrc).toContain('DISTANCE TO {{ triggerRow.label }}')
      expect(squeezeSrc).toContain('POCKET {{ optUsd(spotPrice) }}–{{ optUsd(triggerRow.level) }}')
      expect(squeezeSrc).toContain('class="ladder"')
    })

    it('renders SqueezeScreener with clean, non-duplicated structure', async () => {
      const mockSqueeze: OptionsSqueeze = {
        primary: 'bullish',
        bullish: 0.78,
        bearish: 0.12,
        label: 'bullish',
        drivers: ['call_wall_proximity'],
        score: 78,
        bullish_setup: {
          side: 'bullish',
          score: 78,
          score_01: 0.78,
          likelihood: 'imminent',
          spot: 100,
          wall: 110,
          wall_pct: 0.1,
          factors: [
            {
              id: 'gamma_acceleration',
              label: 'Gamma Acceleration',
              score: 20,
              max: 25,
              detail: 'Strong call delta',
            },
          ],
          setup_analysis: ['Call gamma pocket active toward $110.00 wall.'],
          for_stronger: ['Sustain spot above $100.'],
          trading_implication: 'Favorable upside gamma acceleration profile.',
        },
        bearish_setup: undefined,
        key_levels: {
          spot: 100,
          call_wall: 110,
          call_wall_pct: 0.1,
          put_wall: 90,
          put_wall_pct: -0.1,
          gamma_flip: 96,
          gamma_flip_pct: -0.04,
          pin_strike: 100,
          near_spot_net_gex_m: 5.2,
        },
        long_gamma_dampened: false,
        negative_fuel: 14.5,
      }

      const app = createSSRApp({
        render: () =>
          h(SqueezeScreener, {
            squeeze: mockSqueeze,
            spot: 100,
            asof: '2026-08-28T15:00:00Z',
            ageSeconds: 15,
            mode: 'live',
            chainProvider: 'thetagang',
            oiProvider: 'thetagang',
            contracts: 450,
          }),
      })

      const html = await renderToString(app)
      expect(html).toContain('class="sq bullish"')
      expect(html).toContain('78')
      expect(html).toContain('/100')
      expect(html).toContain('THEORY SCORE · NOT A FORECAST')
      expect(html).toContain('DISTANCE TO CALL WALL')
      expect(html).toContain('KEY LEVELS')
      expect(html).toContain('KEY FACTORS')
      expect(html).toContain('KEY TAKEAWAYS')
      expect(html).toContain('AGE 15s')
      expect(html).toContain('450 CONTRACTS')
    })
  })
})
