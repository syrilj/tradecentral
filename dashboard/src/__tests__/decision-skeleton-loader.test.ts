import { describe, it, expect } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import DecisionSkeletonLoader, {
  type DecisionStreamState,
} from '../components/DecisionSkeletonLoader.vue'

describe('DecisionSkeletonLoader component', () => {
  it('renders accessible processing screen with aria attributes and calibration progress', async () => {
    const streams: DecisionStreamState[] = [
      {
        key: 'options',
        label: 'OPTIONS FLOW & GEX',
        loading: true,
        status: 'in-flight',
        description: 'Pricing live option contracts…',
      },
      {
        key: 'regime',
        label: 'MARKET REGIME',
        loading: true,
        status: 'in-flight',
        description: 'Synthesizing 5 regime models…',
      },
      {
        key: 'microstructure',
        label: 'DEALER BOOK',
        loading: false,
        status: 'ready',
        description: 'Dealer hedging pressure & walls mapped',
      },
      {
        key: 'vpa',
        label: 'VOLUME PRICE ANALYSIS',
        loading: false,
        status: 'ready',
        description: 'VPA calibrated · markup phase',
      },
      {
        key: 'forecast',
        label: 'MODEL FORECAST',
        loading: false,
        status: 'ready',
        description: 'Horizon evidence retrieved',
      },
      {
        key: 'execution_gate',
        label: 'EXECUTION GATE',
        loading: false,
        status: 'ready',
        description: 'Session phase regular',
      },
    ]

    const html = await renderToString(
      createSSRApp({
        render: () =>
          h(DecisionSkeletonLoader, {
            symbol: 'SPY',
            streams,
            completedCount: 4,
            totalCount: 6,
          }),
      }),
    )

    expect(html).toContain('role="status"')
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain('aria-live="polite"')
    expect(html).toContain('class="decision-skeleton-screen" aria-busy="true"')
    expect(html).toContain('Calibrating multi-lens live decision for SPY. 4 of 6 lenses calibrated.')
    expect(html).toContain('CALIBRATING MULTI-LENS LIVE DECISION · SPY')
    expect(html).toContain('CALIBRATING [4/6 LENSES]')
    expect(html).toContain('role="progressbar"')
    expect(html).toContain('aria-valuenow="67"')
    expect(html).toContain('OPTIONS FLOW &amp; GEX')
    expect(html).toContain('MARKET REGIME')
    expect(html).toContain('DEALER BOOK')
    expect(html).toContain('VOLUME PRICE ANALYSIS')
    expect(html).toContain('MODEL FORECAST')
    expect(html).toContain('EXECUTION GATE')
    expect(html).toContain('IN-FLIGHT')
    expect(html).toContain('READY')
  })

  it('renders default streams and calculates progress when no streams are passed', async () => {
    const html = await renderToString(
      createSSRApp({
        render: () =>
          h(DecisionSkeletonLoader, {
            symbol: 'NVDA',
          }),
      }),
    )

    expect(html).toContain('CALIBRATING MULTI-LENS LIVE DECISION · NVDA')
    expect(html).toContain('CALIBRATING [0/6 LENSES]')
    expect(html).toContain('STAGE 1/4 · OPTIONS GEX &amp; ORDER FLOW')
  })
})
