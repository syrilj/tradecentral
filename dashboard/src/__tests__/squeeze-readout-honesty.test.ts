import { describe, expect, it } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import type { OptionsSqueeze } from '@/api'
import { buildSqueezeExplanation } from '@/squeezeCalc'
import SqueezeScreener from '@/components/SqueezeScreener.vue'

/**
 * Three-state honesty for the squeeze readout: the direction half of
 * fuel × direction is a two-leg vote (signed tape + fresh 5-day momentum).
 *
 *   MEASURED — both legs vote → full score presentation
 *   PARTIAL  — one leg votes → the voting leg is shown, the missing leg is
 *              labelled UNMEASURED, the score still renders
 *   DEGRADED — neither leg votes → the score is suppressed to '—' and the
 *              headline explains that only structure stands. A missing input
 *              must never render as a numeric 0/100 or as "quiet".
 *
 * The fixtures below pin *states*, not specific fuel percentages — the backend
 * fuel calibration may move, but the honest-state contract may not.
 */

const keyLevels = {
  spot: 177.4,
  call_wall: 185,
  call_wall_pct: 0.043,
  put_wall: 170,
  put_wall_pct: -0.042,
  gamma_flip: 180.2,
  gamma_flip_pct: 0.016,
  pin_strike: 175,
} as const

function measuredSqueeze(over: Partial<OptionsSqueeze> = {}): OptionsSqueeze {
  return {
    bullish: 0.32,
    bearish: 0.05,
    score: 27.2,
    label: 'bullish_lean',
    primary: 'bullish',
    drivers: ['short_premium_dealer_gamma', 'signed_bullish_flow'],
    long_gamma_dampened: false,
    negative_fuel: 0.62,
    theory: {
      squeeze_risk: 0.019,
      fuel_ui: 0.62,
      bullish_ui: 27,
      bearish_ui: 4,
      adv_m: 840,
      adv_available: true,
      measurable: true,
      directional_flow_imbalance: 0.35,
      flow_measured: true,
      flow_weight: 0.5,
      momentum: 0.02,
      momentum_fresh: true,
      conviction_bull: 0.44,
      conviction_bear: 0.06,
      short_premium_gex_m: { total_gex_m: -11.8, atm_share: 0.29, weighted_dte: 6.5 },
    },
    key_levels: { ...keyLevels },
    ...over,
  }
}

/** One leg votes: momentum is fresh, the tape carries no buy/sell side. */
function partialSqueeze(over: Partial<OptionsSqueeze> = {}): OptionsSqueeze {
  return measuredSqueeze({
    theory: {
      squeeze_risk: 0.019,
      fuel_ui: 0.62,
      bullish_ui: 27,
      bearish_ui: 4,
      adv_m: 840,
      adv_available: true,
      measurable: true,
      directional_flow_imbalance: null,
      flow_measured: false,
      flow_weight: 0,
      momentum: 0.02,
      momentum_fresh: true,
      conviction_bull: 0.44,
      conviction_bear: 0.06,
      short_premium_gex_m: { total_gex_m: -11.8, atm_share: 0.29, weighted_dte: 6.5 },
    },
    ...over,
  })
}

/** No leg votes: unsigned tape AND momentum 5 calendar days stale. */
function degradedSqueeze(over: Partial<OptionsSqueeze> = {}): OptionsSqueeze {
  return measuredSqueeze({
    bullish: 0,
    bearish: 0,
    score: 0,
    label: 'quiet',
    primary: 'quiet',
    drivers: ['short_premium_dealer_gamma'],
    theory: {
      squeeze_risk: 0.0013,
      fuel_ui: 0.05,
      bullish_ui: 0,
      bearish_ui: 0,
      adv_m: 840,
      adv_available: true,
      measurable: true,
      directional_flow_imbalance: null,
      flow_measured: false,
      flow_weight: 0,
      momentum: 0.012,
      momentum_fresh: false,
      momentum_price_age_days: 5,
      conviction_bull: 0,
      conviction_bear: 0,
      short_premium_gex_m: { total_gex_m: -1.1, atm_share: 0.3, weighted_dte: 3 },
    },
    ...over,
  })
}

interface ScreenerProps {
  squeeze: OptionsSqueeze | null | undefined
  spot?: number | null
  tapePrints?: number | null
  tapeSigned?: boolean | null
  tapeWarnings?: string[] | null
}

async function renderScreener(props: ScreenerProps): Promise<string> {
  const app = createSSRApp({ render: () => h(SqueezeScreener, props) })
  return renderToString(app)
}

describe('Squeeze readout — three-state honesty', () => {
  describe('MEASURED: both direction legs vote', () => {
    it('marks dirStatus measured and carries no suppression chip', () => {
      const ex = buildSqueezeExplanation(measuredSqueeze(), 177.4)
      expect(ex.dirStatus).toBe('measured')
      expect(ex.dirChip).toBeNull()
      expect(ex.scoreDisplay).not.toBe('—')
      expect(ex.markerPct).not.toBeNull()
    })

    it('renders the full score presentation without honesty chips', async () => {
      const html = await renderScreener({ squeeze: measuredSqueeze(), spot: 177.4 })
      expect(html).toContain('class="sq bullish"')
      expect(html).toMatch(/>BULL LEAN<\/h3>/)
      expect(html).not.toContain('DIRECTION UNMEASURED')
      expect(html).not.toContain('DIRECTION PARTIAL')
    })
  })

  describe('PARTIAL: exactly one leg votes', () => {
    it('shows the voting leg and names the missing one UNMEASURED, not 0%', () => {
      const ex = buildSqueezeExplanation(partialSqueeze(), 177.4)
      expect(ex.dirStatus).toBe('partial')
      expect(ex.dirChip?.text).toBe('DIRECTION PARTIAL · SIGNED FLOW UNMEASURED')
      const dir = ex.steps[1]
      expect(dir.lines.join(' ')).toContain("doesn't vote")
      expect(dir.lines.join(' ')).toContain('UNMEASURED')
      // The voting leg's numbers still render — partial is not suppressed.
      expect(ex.scoreDisplay).not.toBe('—')
      expect(dir.value).not.toBe('—')
      expect(dir.lines.join(' ')).toContain('5-day move +2.00%')
    })

    it('renders the partial chip between the header and the scale', async () => {
      const html = await renderScreener({ squeeze: partialSqueeze(), spot: 177.4 })
      expect(html).toContain('DIRECTION PARTIAL')
      expect(html).toContain('SIGNED FLOW UNMEASURED')
    })
  })

  describe('DEGRADED: neither leg votes', () => {
    it('suppresses the score to an em-dash — never a numeric 0, never "quiet"', () => {
      const ex = buildSqueezeExplanation(degradedSqueeze(), 177.4)
      expect(ex.dirStatus).toBe('degraded')
      expect(ex.verdict).toBe('DIRECTION UNMEASURED')
      expect(ex.tone).toBe('unmeasured')
      expect(ex.score).toBeNull()
      expect(ex.scoreDisplay).toBe('—')
      expect(ex.markerPct).toBeNull()
      expect(ex.dirChip?.text).toBe('DIRECTION UNMEASURED · SCORE SUPPRESSED')
      expect(ex.summary).toContain('Structure only')
      expect(ex.summary).toContain('suppressed, not a zero')
    })

    it('keeps fuel structural, degrades direction and score steps', () => {
      const ex = buildSqueezeExplanation(degradedSqueeze(), 177.4)
      const [fuel, dir, score] = ex.steps
      // Fuel is a structure fact — it stays measured.
      expect(fuel.value).not.toBe('—')
      expect(fuel.fill01).not.toBeNull()
      // Direction and score steps carry no fabricated numbers.
      expect(dir.value).toBe('—')
      expect(dir.fill01).toBeNull()
      expect(dir.lines.join(' ')).not.toContain('bull 0%')
      expect(score.value).toBe('—')
      expect(score.fill01).toBeNull()
      expect(score.lines.join(' ')).not.toContain('Bull − bear')
      // The stale momentum line names its age instead of just saying "stale".
      expect(dir.lines.join(' ')).toContain('5 calendar days old')
      expect(ex.watch.join(' ')).toContain('restore the momentum vote')
    })

    it('still renders the structural LEVELS ladder in the degraded state', () => {
      const ex = buildSqueezeExplanation(degradedSqueeze(), 177.4)
      expect(ex.levels.map((l) => l.id)).toContain('call_wall')
      expect(ex.levels.map((l) => l.id)).toContain('spot')
      expect(ex.levels.every((l) => !l.trigger)).toBe(true)
    })

    it('renders the degraded state visibly distinct from a measured zero', async () => {
      const html = await renderScreener({
        squeeze: degradedSqueeze(),
        spot: 177.4,
        tapePrints: 0,
        tapeSigned: false,
        tapeWarnings: [
          'No trade-tape prints returned, so there is no signed order flow to lean on.',
        ],
      })
      expect(html).toContain('data-tone="unmeasured"')
      expect(html).toMatch(/>DIRECTION UNMEASURED<\/h3>/)
      expect(html).not.toContain('NO FUEL')
      // The score cell is an em-dash, and no scale marker is placed.
      expect(html).toMatch(/score-num[^>]*>—</)
      expect(html).not.toContain('scale-marker')
      // Structure sections survive: explainer + levels + the tape reason.
      expect(html).toContain('HOW IT GOT HERE')
      expect(html).toContain('CALL WALL')
      expect(html).toContain('TAPE: NO PRINTS')
      expect(html).toContain('DIRECTION UNMEASURED · SCORE SUPPRESSED')
    })

    it('suppresses the score even when the payload ships a numeric zero', () => {
      const ex = buildSqueezeExplanation(degradedSqueeze(), 177.4)
      expect(ex.scoreDisplay).toBe('—')
      expect(ex.scoreDisplay).not.toMatch(/0/)
    })
  })

  describe('Tape status chip', () => {
    it('reports a provider cooldown from the warnings, outranking print counts', async () => {
      const html = await renderScreener({
        squeeze: measuredSqueeze(),
        spot: 177.4,
        tapePrints: 0,
        tapeWarnings: ['flow tape unavailable: flow_lse_provider_cooldown until 15:42Z'],
      })
      expect(html).toContain('TAPE: PROVIDER COOLDOWN')
      expect(html).not.toContain('TAPE: 0 PRINTS')
    })

    it('reports the print count when the tape fed the panel', async () => {
      const html = await renderScreener({
        squeeze: measuredSqueeze(),
        spot: 177.4,
        tapePrints: 500,
        tapeSigned: true,
      })
      expect(html).toContain('TAPE: 500 PRINTS')
      expect(html).not.toContain('UNSIGNED')
    })

    it('flags prints that carry no buy/sell side', async () => {
      const html = await renderScreener({
        squeeze: partialSqueeze(),
        spot: 177.4,
        tapePrints: 214,
        tapeSigned: false,
      })
      expect(html).toContain('TAPE: 214 PRINTS · UNSIGNED')
    })

    it('renders no chip when the payload says nothing about the tape', async () => {
      const html = await renderScreener({ squeeze: measuredSqueeze(), spot: 177.4 })
      expect(html).not.toContain('TAPE:')
    })
  })
})
