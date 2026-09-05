import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  feedStatusCopy,
  flowCacheCopy,
  flowTransportCopy,
  signedVsUnsignedLabel,
  tradeClassSourceLabel,
} from '@/flowDisplay'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(rel: string): string {
  return readFileSync(join(root, rel), 'utf8')
}

describe('Flow/Options written copy matches the fail-closed payload', () => {
  const flow = source('views/FlowView.vue')
  const dashboard = source('components/FlowDashboard.vue')
  const options = source('views/OptionsView.vue')
  const context = source('components/OptionsFlowContext.vue')

  it('does not claim a realtime institutional firehose or certified golden sweep', () => {
    for (const text of [flow, dashboard, options]) {
      expect(text).not.toMatch(/Real-time institutional/i)
      expect(text).not.toContain('LIVE TAPE')
      expect(text).not.toContain('GOLDEN SWEEPS')
      expect(text).not.toContain('certified golden')
      expect(text).not.toContain('Realtime Option Flow')
      expect(text).not.toContain('Realtime Flow Analytics')
      expect(text).not.toContain('LIVE STREAM')
      expect(text).not.toContain('WebSocket-style stream')
    }
    expect(dashboard).not.toContain('STREAMING')
    expect(dashboard).toContain('15s POLL')
    expect(dashboard).toContain('provider tape')
    expect(dashboard).toContain('Provider sample analytics')
    expect(options).not.toContain('SWITCH TO LIVE STREAM')
    expect(options).toContain('SWITCH TO PROVIDER POLL')
    expect(flow).toContain('PROVIDER TAPE')
    expect(flow).toContain('15s HTTP poll')
    expect(flow).toContain('not ENTER')
    expect(dashboard).toContain('NOT A WEBSOCKET')
    expect(dashboard).toContain('flowCacheCopy')
    expect(dashboard).toContain('tradeClassSourceLabel')
    expect(options).toContain('PROVIDER TAPE')
    expect(options).toContain('NO PROVIDER TAPE')
    expect(options).toContain('not ENTER')
  })

  it('keeps unusual/sweep/heat descriptive and names missing/stale/unsigned states', () => {
    expect(dashboard).toContain('UNSIGNED TAPE')
    expect(dashboard).toContain('STALE SAMPLE')
    expect(dashboard).toContain('research triage — not order authorization')
    expect(context).toContain('never execution authorization')
    expect(feedStatusCopy('live')).toBe('PROVIDER SAMPLE')
    expect(flowCacheCopy({ hit: true, age_seconds: 2, ttl_seconds: 12 })).toContain('CACHE HIT')
    expect(flowTransportCopy(15_000)).toContain('NOT A WEBSOCKET')
    expect(tradeClassSourceLabel('vendor')).toBe('VENDOR CLASS')
    expect(signedVsUnsignedLabel({})).toBe('UNSIGNED')
  })
})
