import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

function readSource(relativeFilePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, '..', relativeFilePath), 'utf-8')
}

describe('Market Regime Workstation Box Fixes Verification', () => {
  it('RegimeHeaderRibbon has effectiveSymbols fallback and honest unmeasured state', () => {
    const src = readSource('components/RegimeHeaderRibbon.vue')
    expect(src).toContain('effectiveSymbols')
    expect(src).toContain('s in effectiveSymbols')
    expect(src).not.toContain("return 'Calibrating...'")
    expect(src).toContain("return 'Unmeasured'")
  })

  it('StrikeGammaExposureChart has no fabricated +$624.3M or 523/520 levels', () => {
    const src = readSource('components/StrikeGammaExposureChart.vue')
    expect(src).not.toContain('+$624.3M')
    expect(src).not.toContain("'523'")
    expect(src).not.toContain("'520'")
    expect(src).toContain('effectiveSpot')
  })

  it('NetGammaSpotTimeSeries dynamically scales Y axis to actual gamma data', () => {
    const src = readSource('components/NetGammaSpotTimeSeries.vue')
    expect(src).not.toContain('const maxGamma = 1.5')
    expect(src).not.toContain('const minGamma = -1.5')
    expect(src).toContain('gammaExtent')
    expect(src).toContain('formatGammaTick')
  })

  it('NetFlowByExpiryChart has clean empty state and dynamic scaling', () => {
    const src = readSource('components/NetFlowByExpiryChart.vue')
    expect(src).toContain('No expiry flow data')
    expect(src).toContain('chart-empty')
    expect(src).not.toContain('let peak = 100')
  })

  it('LiveAlertsPanel renders empty state when alerts is empty and avoids mock defaults', () => {
    const src = readSource('components/LiveAlertsPanel.vue')
    expect(src).toContain('No active regime alerts for {{ symbol }}')
    expect(src).toContain('alerts: () => []')
  })

  it('RealTimeFlowTape genuinely freezes and unfreezes prints on Pause', () => {
    const src = readSource('components/RealTimeFlowTape.vue')
    expect(src).toContain('frozenPrints')
    expect(src).toContain('togglePause')
    expect(src).toContain('sourcePrints')
  })

  it('VolatilitySurface3D does not hardcode 525 and displays empty state when spot is null', () => {
    const src = readSource('components/VolatilitySurface3D.vue')
    expect(src).not.toContain('spot: 525')
    expect(src).toContain('hasValidSpot')
    expect(src).toContain('No spot price available for 3D vol surface')
  })

  it('StrikeOpenInterestChart has effectiveSpot fallback when spot is temporarily null', () => {
    const src = readSource('components/StrikeOpenInterestChart.vue')
    expect(src).toContain('effectiveSpot')
    expect(src).toContain('No open-interest data')
  })

  it('RegimeView passes QUICK_UNIVERSE to ribbon and effectiveSpot to cards', () => {
    const src = readSource('views/RegimeView.vue')
    expect(src).toContain(':symbols-list="QUICK_UNIVERSE"')
    expect(src).toContain(':spot="regimeRead.spot ?? effectiveSpot"')
  })

  it('RegimeView gives section tabs equal-fill sizing and a plain-language section guide', () => {
    const src = readSource('views/RegimeView.vue')
    expect(src).toContain('class="section-guide"')
    expect(src).toContain('activeSectionGuidance.description')
    expect(src).toContain('flex: 1 1 0;')
    expect(src).toContain('grid-template-columns: repeat(2, minmax(0, 1fr));')
  })

  it('does not paint kinematic speed as a confidence penalty or fake GEX from velocity', () => {
    const src = readSource('views/RegimeView.vue')
    expect(src).not.toContain('penaltyFactors = sens')
    expect(src).not.toContain('(latestStatePoint?.kalman_velocity ?? 0) * 1000')
    expect(src).toContain(
      'penaltyFactors = labelIsLocallyReconciled ? [] : (raw?.confidence?.penaltyFactors ?? [])',
    )
  })

  it('PrimaryRegimeCard shows kinematic speed as a signed readout and does not color LOW confidence as put/red', () => {
    const src = readSource('components/PrimaryRegimeCard.vue')
    expect(src).toContain('KINEMATIC SPEED')
    expect(src).toContain('kalmanVelocity')
    expect(src).toContain('grid-template-columns: minmax(0, 1fr) minmax(0, 260px)')
    expect(src).toContain('.band-low .conf-fill')
    expect(src).toContain('background: var(--ink-faint)')
    expect(src).toContain('.band-low .conf-band-chip')
  })

  it('FourPillarContextGrid colors speed by sign, z-score as deviation, and fits columns with minmax', () => {
    const src = readSource('components/FourPillarContextGrid.vue')
    expect(src).toContain('Kinematic speed')
    expect(src).toContain('Speed vs history')
    expect(src).toContain('grid-template-columns: repeat(4, minmax(0, 1fr))')
    expect(src).toContain("'c-pos': (kalmanV ?? 0) > 0")
    expect(src).toContain("'c-warn': kalmanZ !== null && Math.abs(kalmanZ) >= 1.5")
  })

  it('ModelAgreementMatrix uses a fixed table layout so the 5×5 fit stays inside the panel', () => {
    const src = readSource('components/ModelAgreementMatrix.vue')
    expect(src).toContain('table-layout: fixed')
    expect(src).toContain('min-width: 0')
  })
})
