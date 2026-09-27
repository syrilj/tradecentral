import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import RegimeSkeletonLoader from '../components/RegimeSkeletonLoader.vue'

function readSource(relativeFilePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, '..', relativeFilePath), 'utf-8')
}

describe('RegimeSkeletonLoader component', () => {
  it('renders accessible processing screen with aria attributes', async () => {
    const html = await renderToString(
      createSSRApp({
        render: () =>
          h(RegimeSkeletonLoader, {
            symbol: 'NVDA',
            spot: 120.5,
            optionsLoading: true,
            regimeLoading: true,
            microLoading: true,
            stateLoading: false,
          }),
      }),
    )

    expect(html).toContain('role="status"')
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain('aria-live="polite"')
    expect(html).toContain('class="regime-skeleton-screen" aria-busy="true"')
    expect(html).toContain('Processing market regime telemetry for NVDA. 1 of 4 streams calibrated.')
    expect(html).toContain('PROCESSING MULTI-MODEL REGIME TELEMETRY · NVDA')
    expect(html).toContain('CALIBRATING [1/4 STREAMS]')
    // Active progression indicators
    expect(html).toContain('role="progressbar"')
    expect(html).toContain('aria-valuenow=')
    expect(html).toContain('processing-timer')
    expect(html).toContain('T+0.0s')
    expect(html).toContain('CALIBRATING MULTI-MODEL REGIME · NVDA')
  })

  it('surfaces active progressbar with stage tracking and status pills', async () => {
    const html = await renderToString(
      createSSRApp({
        render: () =>
          h(RegimeSkeletonLoader, {
            symbol: 'AAPL',
            optionsLoading: false,
            regimeLoading: true,
            microLoading: true,
            stateLoading: false,
          }),
      }),
    )

    // With options loaded and state loaded (2/4 streams ready):
    expect(html).toContain('CALIBRATING [2/4 STREAMS]')
    expect(html).toContain('50% CALIBRATED')
    expect(html).toContain('STAGE 2/4 · MULTI-MODEL CONSENSUS')
    expect(html).toContain('Evaluating 5-model ensemble matrix')
    // Stream status pills
    expect(html).toContain('IN-FLIGHT')
    expect(html).toContain('CALIBRATED')
    expect(html).toContain('stream-micro-fill--active')
    expect(html).toContain('stream-micro-fill--ready')
  })

  it('surfaces all four analytical telemetry streams with status descriptions', async () => {
    const html = await renderToString(
      createSSRApp({
        render: () =>
          h(RegimeSkeletonLoader, {
            symbol: 'SPY',
            optionsLoading: true,
            regimeLoading: false,
            microLoading: true,
            stateLoading: false,
          }),
      }),
    )

    expect(html).toContain('OPTIONS CHAIN')
    expect(html).toContain('Pricing contracts &amp; GEX profile…')
    expect(html).toContain('MULTI-MODEL CONSENSUS')
    expect(html).toContain('Consensus reached')
    expect(html).toContain('DEALER BOOK')
    expect(html).toContain('Mapping hedging pressure &amp; walls…')
    expect(html).toContain('CAUSAL KINEMATICS')
    expect(html).toContain('Kinematics estimated')
  })

  it('renders structural skeletons for all major regime workstation panels', async () => {
    const html = await renderToString(
      createSSRApp({
        render: () =>
          h(RegimeSkeletonLoader, {
            symbol: 'SPY',
          }),
      }),
    )

    // Tactical Banner Skeleton
    expect(html).toContain('sk-tactical-banner')
    // Primary Regime Card Skeleton with ring, confidence meter and simplex
    expect(html).toContain('PRIMARY REGIME STATE · SPY')
    expect(html).toContain('sk-meter-bar')
    expect(html).toContain('sk-simplex-segments')
    expect(html).toContain('sk-levels-strip')
    // Transition Risk Gauge Skeleton
    expect(html).toContain('TRANSITION RISK &amp; STABILITY')
    expect(html).toContain('sk-gauge-svg')
    // 4 Analytical Pillars Skeleton
    expect(html).toContain('sk-four-pillar-grid')
    // Multi-Model Agreement Matrix Skeleton (5x5)
    expect(html).toContain('MULTI-MODEL AGREEMENT MATRIX')
    expect(html).toContain('sk-matrix-grid')
    // Dynamic Explanation Panel Skeleton
    expect(html).toContain('DYNAMIC EXPLAINABILITY &amp; DRIVERS')
  })
})

describe('RegimeView processing screen and wrong read prevention', () => {
  const src = readSource('views/RegimeView.vue')

  it('imports RegimeSkeletonLoader component', () => {
    expect(src).toContain(
      "import RegimeSkeletonLoader from '@/components/RegimeSkeletonLoader.vue'",
    )
  })

  it('computes isRegimeProcessing to track core in-flight telemetry', () => {
    expect(src).toContain('const isRegimeProcessing = computed<boolean>(() => {')
    expect(src).toContain('optionsRes.loading.value')
    expect(src).toContain('marketRegimeRes.loading.value')
    expect(src).toContain('microRegimeRes.loading.value')
  })

  it('withholds provisional reconciledMarketRegime while marketRegimeRes is loading', () => {
    expect(src).toContain('if (marketRegimeRes.loading.value && !raw) {\n    return null\n  }')
  })

  it('returns calibrating status in tacticalBiasRead instead of provisional fade-extremes stance', () => {
    expect(src).toContain('if (isRegimeProcessing.value) {')
    expect(src).toContain("title: 'CALIBRATING MULTI-MODEL REGIME'")
    expect(src).toContain("bias: 'CALIBRATING…'")
    expect(src).toContain(
      'Awaiting initial multi-model consensus before issuing tactical playbook guidance.',
    )
  })

  it('renders RegimeSkeletonLoader in sec-tactical when isRegimeProcessing is active', () => {
    expect(src).toContain('<RegimeSkeletonLoader')
    expect(src).toContain('v-if="isRegimeProcessing"')
    expect(src).toContain(':options-loading="optionsRes.loading.value && !optionsRes.data.value"')
    expect(src).toContain(
      ':regime-loading="marketRegimeRes.loading.value && !marketRegimeRes.data.value"',
    )
  })

  it('labels header ribbon CALIBRATING REGIME… when processing', () => {
    expect(src).toContain("'CALIBRATING REGIME…'")
    expect(src).toContain(':regime="isRegimeProcessing ? null : regimeRead.side"')
  })
})

describe('DeskView regime breadth card zero-measurement guard', () => {
  const src = readSource('views/DeskView.vue')

  it('guards against spoofing LONG Γ when zero symbols are measured', () => {
    expect(src).toContain("marketRegimeBreadth.measured === 0\n                ? 'muted'")
    expect(src).toContain("marketRegimeBreadth.measured === 0\n                ? 'UNMEASURED'")
    expect(src).toContain('Awaiting regime telemetry across watch symbols')
  })
})
