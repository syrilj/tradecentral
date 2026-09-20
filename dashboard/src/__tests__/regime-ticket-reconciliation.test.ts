import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { computeRuleOf16ExpectedMove } from '@/expectedMove'

const regimeSrc = readFileSync(resolve(__dirname, '../views/RegimeView.vue'), 'utf-8')

/**
 * The desk showed one regime read and, underneath it, a ticket from a second
 * engine that reports `gamma_conditioned: false`. Nothing reconciled them, so
 * a BULLISH "SHORT SQUEEZE" briefing could sit directly above an ENTER_SHORT
 * ticket and the page presented both as its own conclusion.
 */
describe('regime ticket reconciliation', () => {
  it('derives a machine-readable side from the same read the briefing uses', () => {
    expect(regimeSrc).toMatch(/const briefingSide = computed<'long' \| 'short' \| 'neutral'>/)
    // Squeeze: dealers short gamma with velocity up is a LONG bias.
    expect(regimeSrc).toMatch(/if \(r\.side === 'short'\) return vel > 0 \? 'long' : 'short'/)
  })

  it('marks the ticket unconfirmed when it contradicts the regime read', () => {
    expect(regimeSrc).toMatch(/const conflict = bias !== 'neutral' && sig\.direction !== bias/)
    expect(regimeSrc).toMatch(/actionable: !conflict && staleReason == null/)
    expect(regimeSrc).toMatch(/UNCONFIRMED TICKET/)
    expect(regimeSrc).toMatch(/CONFLICTS WITH THE REGIME READ/)
  })

  it('will not call a ticket live once spot has traded through its own levels', () => {
    expect(regimeSrc).toMatch(/spot has already traded through the stop/)
    expect(regimeSrc).toMatch(/spot has already reached the target/)
  })

  it('prints the bar the ticket was quoted on and what the stop is a multiple of', () => {
    expect(regimeSrc).toMatch(/ticketRead\.sig\.timestamp\.slice\(0, 10\)/)
    expect(regimeSrc).toMatch(/Levels sized off \{\{ ticketRead\.unitLabel \}\}/)
  })

  it('shows the R multiple and the scale-out ladder, not a bare target', () => {
    expect(regimeSrc).toMatch(/ticketRead\.sig\.risk_reward/)
    expect(regimeSrc).toMatch(/ticketRead\.sig\.target_1r/)
    expect(regimeSrc).toMatch(/ticketRead\.sig\.target_3r/)
  })
})

/**
 * The corridor was captioned "(VIX / 16)" while it was fed the symbol's own
 * ATM IV -- on CRDO, an 88% IV printing a 5.5% band under a caption claiming a
 * 15.7 VIX had produced it.
 */
describe('expected move basis labelling', () => {
  it('reports atm_iv when the symbol IV is what was used', () => {
    const em = computeRuleOf16ExpectedMove(168.2, 88.0, 15.7)!
    expect(em.ivBasis).toBe('atm_iv')
    expect(em.ivBasisLabel).toBe('ATM IV 88.0% / 16')
    expect(em.em1dDollars).toBeCloseTo((168.2 * 0.88) / 16, 4)
  })

  it('reports vix_proxy only when it actually fell back to VIX', () => {
    const em = computeRuleOf16ExpectedMove(168.2, null, 15.7)!
    expect(em.ivBasis).toBe('vix_proxy')
    expect(em.ivBasisLabel).toMatch(/^VIX 15\.7 \/ 16$/)
    expect(em.em1dDollars).toBeCloseTo((168.2 * 0.157) / 16, 4)
  })

  it('the two bases are not interchangeable at single-name IV levels', () => {
    const iv = computeRuleOf16ExpectedMove(168.2, 88.0, 15.7)!
    const vix = computeRuleOf16ExpectedMove(168.2, null, 15.7)!
    expect(iv.em1dDollars / vix.em1dDollars).toBeGreaterThan(5)
  })

  it('the panel caption is driven by the basis rather than hard-coded', () => {
    expect(regimeSrc).toMatch(
      /expectedMove\?\.ivBasis === 'vix_proxy' \? 'VIX \/ 16' : 'ATM IV \/ 16'/,
    )
    expect(regimeSrc).toMatch(/expectedMove\?\.ivBasisLabel/)
  })
})
