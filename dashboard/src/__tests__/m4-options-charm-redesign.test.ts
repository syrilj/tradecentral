import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('Milestone 4: Options Chain & Charm / Greeks Positioning Overhaul (R3)', () => {
  describe('1. Design Token & Glassmorphism Conformance', () => {
    it('verifies all target view and component source files strictly use design tokens with 0 forbidden glows or text-shadows', () => {
      const targetFiles = [
        'src/views/OptionsView.vue',
        'src/views/DriftView.vue',
        'src/views/ChainView.vue',
        'src/views/CalculatorView.vue',
        'src/components/OptionsCalculator.vue',
        'src/components/GammaExposureMap.vue',
        'src/components/PressureDriftChart.vue',
        'src/components/OptionsDriftChart.vue',
        'src/components/OptionsDirectionBrief.vue',
        'src/components/OptionsFlowContext.vue',
        'src/components/SqueezeScreener.vue',
        'src/components/ProbabilityDensityChart.vue',
        'src/components/OptionsConvictionBoard.vue',
      ]

      for (const relPath of targetFiles) {
        const fullPath = resolve(__dirname, '..', '..', relPath)
        const content = readFileSync(fullPath, 'utf-8')

        // Assert no forbidden glow halos, brightness filters, or text-shadows
        expect(content).not.toMatch(/text-shadow\s*:/)
        expect(content).not.toMatch(/filter\s*:\s*brightness\(/)
        expect(content).not.toMatch(/box-shadow\s*:[^;]*\b0\s+0\s+(?:[5-9]|\d{2,})px/)

        // Verify presence of modern glass tokens in styles
        expect(content).toMatch(/--glass-/)
      }
    })
  })

  describe('2. DriftView Charm (∂Δ/∂t) and Greeks Positioning Analytics', () => {
    it('contains mathematical formulas and structure for Black-Scholes Charm and Greeks breakdown', () => {
      const driftViewPath = resolve(__dirname, '..', '..', 'src/views/DriftView.vue')
      const content = readFileSync(driftViewPath, 'utf-8')

      // Check charm formula & factor breakdowns
      expect(content).toContain('CHARM &amp; DEALER HEDGING DYNAMICS')
      expect(content).toContain('1. CHARM TIME DECAY')
      expect(content).toContain('2. GEX REGIME')
      expect(content).toContain('3. LIVE FLOW AGGRESSION')
      expect(content).toContain('NET CHARM FLOW')

      // Check dense call/put strike grid columns
      expect(content).toContain('CALL OPTIONS (DEALER LONG INVENTORY)')
      expect(content).toContain('PUT OPTIONS (DEALER SHORT INVENTORY)')
      expect(content).toContain('DEALER NET FLOW')
      expect(content).toContain('call-charm')
      expect(content).toContain('put-charm')
      expect(content).toContain('net-charm-cell')
      expect(content).toContain('gex-cell')

      // Check institutional playbook / actionable strategies
      expect(content).toContain('assessment-box')
      expect(content).toContain('strategies-grid')
      expect(content).toContain('strategy-card')
    })
  })

  describe('3. OptionsView Frosted Glassmorphic Structure & KPI Rail', () => {
    it('contains dense KPI rail, command bar, qualified flow tape, and GEX strike map integration', () => {
      const optionsViewPath = resolve(__dirname, '..', '..', 'src/views/OptionsView.vue')
      const content = readFileSync(optionsViewPath, 'utf-8')

      // Check command strip and glassmorphism classes
      expect(content).toContain('class="command')
      expect(content).toContain('class="kpi-rail')
      expect(content).toContain('class="live-filter-bar')
      expect(content).toContain('class="tape-stalker-card')
      expect(content).toContain('class="calc-handoff')

      // Check key metrics in KPI rail
      expect(content).toContain('NET GEX')
      expect(content).toContain('CALL WALL')
      expect(content).toContain('PUT WALL')
      expect(content).toContain('FLIP')
      expect(content).toContain('SQUEEZE STRUCTURE')
      expect(content).toContain('C/P PREM')
    })
  })

  describe('4. ChainView Thematic Supply Chain & Value Cascade', () => {
    it('contains thematic bridges, quick focus chips, and multi-tier controls', () => {
      const chainViewPath = resolve(__dirname, '..', '..', 'src/views/ChainView.vue')
      const content = readFileSync(chainViewPath, 'utf-8')

      expect(content).toContain('thematic-bridges-strip')
      expect(content).toContain('quick-focus-strip')
      expect(content).toContain('mode-toggle-group')
      expect(content).toContain('node-count-badge')
      expect(content).toContain('chain-ctrl-bar')
    })
  })

  describe('5. OptionsCalculator & Multi-Leg Strategy Builder', () => {
    it('contains institutional presets, multi-leg table, Greeks aggregation, and Payoff density charts', () => {
      const calcPath = resolve(__dirname, '..', '..', 'src/components/OptionsCalculator.vue')
      const content = readFileSync(calcPath, 'utf-8')

      // Presets & strategies
      expect(content).toContain('presets-shelf')
      expect(content).toContain('underlier-shelf')
      expect(content).toContain('strategy-thesis-strip')
      expect(content).toContain('alloc-card')
      expect(content).toContain('payoff-host')

      // Greeks aggregation
      expect(content).toContain('label="Delta"')
      expect(content).toContain('label="Gamma"')
      expect(content).toContain('label="Theta"')
      expect(content).toContain('label="Vega"')
      expect(content).toContain('netDebit')
    })
  })
})
