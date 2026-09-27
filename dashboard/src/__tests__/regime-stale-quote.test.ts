import { describe, expect, it } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import RegimeHeaderRibbon from '@/components/RegimeHeaderRibbon.vue'

function render(props: Record<string, unknown>): Promise<string> {
  return renderToString(createSSRApp({ render: () => h(RegimeHeaderRibbon, props as never) }))
}

/**
 * The LSE provider 402s once the byte quota trips, and `_symbol_quote` then
 * substitutes the last stored daily close, honestly reporting
 * `quality: 'local'` with the real bar date in `asof`. The ribbon discarded
 * both, so on CRDO a six-day-old $164.75 close rendered exactly like a live
 * mark and the 09-01 -> 09-02 gap printed as "-41.88 (-20.27%)" — last week's
 * session presented as today's tape.
 */
const STALE = {
  symbol: 'CRDO',
  spot: 164.75,
  dayChangeDollar: -41.88,
  dayChangePct: -20.27,
  quoteAsof: '2026-09-02T00:00:00+00:00',
  quoteQuality: 'local',
}

const LIVE = { ...STALE, quoteAsof: new Date().toISOString(), quoteQuality: 'live' }

describe('stale quote provenance in the regime ribbon', () => {
  it('marks a fallback close as stale and dates it', async () => {
    const text = await render(STALE)
    expect(text).toMatch(/STALE/)
    expect(text).toContain('2026-09-02')
  })

  it('says the move is the last two closes, not the session', async () => {
    expect(await render(STALE)).toMatch(/last 2 closes/)
  })

  it('reports how old the mark is in days', async () => {
    expect(await render(STALE)).toMatch(/\d+d old/)
  })

  it('stays silent when the mark is genuinely live', async () => {
    const text = await render(LIVE)
    expect(text).not.toMatch(/STALE/)
    expect(text).not.toMatch(/last 2 closes/)
  })

  it('treats a missing quality as live rather than accusing a good quote', async () => {
    const text = await render({
      symbol: 'SPY',
      spot: 765.41,
      dayChangeDollar: 5.35,
      dayChangePct: 0.7,
    })
    expect(text).not.toMatch(/STALE/)
  })
})

describe('expired option board is not a 0DTE board', () => {
  it('renders a past expiry as EXPIRED, never as 0D', async () => {
    const text = await render({ symbol: 'CRDO', nextExpiryDte: -4, nextExpiryDate: '09-04' })
    expect(text).toMatch(/EXPIRED 4D/)
    expect(text).not.toMatch(/\b0D\b/)
  })

  it('still renders a genuine 0DTE as 0D', async () => {
    const text = await render({ symbol: 'SPY', nextExpiryDte: 0, nextExpiryDate: '09-08' })
    expect(text).toMatch(/0D/)
    expect(text).not.toMatch(/EXPIRED/)
  })
})
