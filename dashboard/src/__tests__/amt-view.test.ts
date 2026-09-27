import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Auction Market Theory (AMT) Workspace', () => {
  const view = source('views/AmtView.vue')
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')
  const apiSrc = source('api.ts')
  const contractsSrc = source('amtContracts.ts')
  const iconSrc = source('components/AppIcon.vue')
  const paletteSrc = source('components/SearchPalette.vue')

  it('registers /amt route and navigation tab in workspace shell', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/amt['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]amt['"]/)
    expect(routerSrc).toContain('Auction Market Theory')
    expect(appSrc).toContain("name: 'amt'")
    expect(appSrc).toContain("title: 'AMT'")
    expect(iconSrc).toContain("name === 'amt'")
    expect(paletteSrc).toContain("{ name: 'amt', title: 'AMT'")
  })

  it('exposes typed AMT API endpoints on the client', () => {
    expect(apiSrc).toContain('amtAnalyze:')
    expect(apiSrc).toContain('amtHealth:')
    expect(apiSrc).toContain('amtPlaybook:')
    expect(apiSrc).toContain('/api/amt/analyze')
    expect(apiSrc).toContain('/api/amt/health')
    expect(apiSrc).toContain('/api/amt/playbook')
  })

  it('declares the AMT contract types with nullable backend fields typed as such', () => {
    for (const iface of [
      'AmtAnalyzeFailure',
      'AmtCompositeProfile',
      'AmtProfileBin',
      'AmtRegime',
      'AmtLocation',
      'AmtRotationStats',
      'AmtEvidenceItem',
      'AmtTradePlan',
      'AmtBarsMeta',
      'AmtHealthPayload',
      'AmtPlaybookPayload',
    ]) {
      expect(contractsSrc).toContain(`export interface ${iface}`)
    }
    expect(contractsSrc).toContain('risk_reward: number | null')
    expect(contractsSrc).toContain('risk_reward_unavailable_reason: string | null')
    expect(contractsSrc).toContain('val_rotation_rate: number | null')
    expect(contractsSrc).toContain('vah_rotation_rate: number | null')
  })

  it('builds the timeframe dropdown from amtHealth().timeframes and renders unavailable options disabled', () => {
    expect(view).toContain('api.amtHealth(symbolInput.value)')
    expect(view).toContain('v-for="tf in timeframeOptions"')
    expect(view).toContain(':disabled="!tf.available"')
    expect(view).toContain('tf.reason')
    expect(view).toContain(':disabled="!capabilityKnown"')
  })

  it('renders section A: regime verdict banner with narrative and weighted components', () => {
    expect(view).toContain('ok.regime.label')
    expect(view).toContain('ok.regime.score')
    expect(view).toContain('ok.narrative')
    expect(view).toContain('regimeComponentRows')
    expect(view).toContain('not derivable')
    expect(view).toContain('row.weight')
  })

  it('renders section B: the profile + candle chart sharing one price axis', () => {
    expect(view).toContain('candlePath')
    expect(view).toContain('profileRows')
    expect(view).toContain('composite.poc')
    expect(view).toContain('composite.vah')
    expect(view).toContain('composite.val')
    expect(view).toContain('va-band')
  })

  it('renders section C: location & acceptance, calling out a failed auction', () => {
    expect(view).toContain('humaniseZone')
    expect(view).toContain('dist_to_poc_atr')
    expect(view).toContain('dist_to_vah_atr')
    expect(view).toContain('dist_to_val_atr')
    expect(view).toContain("failed_auction !== 'none'")
  })

  it('renders section D: the trade plan and never fabricates a risk:reward ratio', () => {
    expect(view).toContain('trade_plan.bias')
    expect(view).toContain('trade_plan.entry')
    expect(view).toContain('trade_plan.stop')
    expect(view).toContain('trade_plan.target_1')
    expect(view).toContain('trade_plan.target_2')
    expect(view).toContain('fmtRiskReward')
    expect(view).toContain('risk_reward_unavailable_reason')
    expect(view).toContain('invalidation')
    expect(view).toContain('rules_applied')
  })

  it('renders section E: the evidence ledger and directional lean', () => {
    expect(view).toContain('ok.evidence')
    expect(view).toContain('ev.signal')
    expect(view).toContain('ev.direction')
    expect(view).toContain('ev.weight')
    expect(view).toContain('ev.detail')
    expect(view).toContain('directional_lean')
  })

  it('renders section F: rotation statistics labelled as measured, not folkloric', () => {
    expect(view).toContain('rotation_stats')
    expect(view).toContain('val_rotation_rate')
    expect(view).toContain('vah_rotation_rate')
    expect(view).toContain('rotation_stats.note')
    expect(view).toMatch(/measured over \$\{ok\.rotation_stats\.sessions\} sessions/)
  })

  it('renders section G: structure flags only when the flag is true', () => {
    expect(view).toContain('humaniseShape')
    expect(view).toContain('v-if="ok.composite.poor_high"')
    expect(view).toContain('v-if="ok.composite.poor_low"')
    expect(view).toContain('v-if="ok.composite.excess_high"')
    expect(view).toContain('v-if="ok.composite.excess_low"')
    expect(view).toContain('composite.hvn.length')
    expect(view).toContain('composite.lvn.length')
  })

  it('renders section H: the playbook collapsed by default', () => {
    expect(view).toContain('<details')
    expect(view).toContain('playbook-details')
    expect(view).toContain('ok.playbook')
  })

  it('renders the failure state prominently and stops there, and guards against fabricated data', () => {
    expect(view).toContain('failure.reason')
    expect(view).toContain('risk_reward_unavailable_reason')
    expect(view).toContain('DASH')
    expect(view).toContain("import { num, signed, tone, pctFrac, DASH } from '@/format'")
  })

  it('surfaces the bars_meta downgrade warning whenever a different timeframe was served', () => {
    expect(view).toContain('ok.bars_meta.downgraded')
    expect(view).toContain('bars_meta.downgrade_reason')
    expect(view).toContain('downgrade-banner')
  })
})
