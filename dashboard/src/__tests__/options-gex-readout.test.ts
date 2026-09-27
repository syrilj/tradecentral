/**
 * Options GEX readouts — the panel must not print two different net-GEX
 * numbers, and a negative amount must not render as `$-7.2M`.
 *
 * Two defects were visible on /options at once:
 *
 *   1. `NET GAMMA BY STRIKE` carried a header badge `EXPOSURE $-7.2M` (the
 *      whole-chain `summary.total_gex_m`) directly above an exposure HUD
 *      reading `NET -$7.8M`. The HUD aggregates only the DRAWN strike window
 *      (the scope control defaults to NEAR / ±12%), so on a wide chain the two
 *      disagree while claiming to be the same quantity. The HUD now names its
 *      scope. The same HUD printed `PUT GEX $16.9M` unsigned next to a signed
 *      `CALL GEX +$9.2M`, contradicting the call-positive/put-negative
 *      convention the chart itself draws by.
 *
 *   2. Negative dollar amounts were assembled as `` `$${num(v, 1)}M` ``, which
 *      puts the minus sign after the currency symbol: `$-7.2M`. `optGex` in
 *      src/format.ts already formats this correctly and was simply bypassed.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'

import GammaExposureMap from '../components/GammaExposureMap.vue'
import { DASH, optGex, optSignedGex } from '../format'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

interface Row {
  strike: number
  call_gex_m: number
  put_gex_m: number
  net_gex_m: number
  call_oi: number
  put_oi: number
}

function row(strike: number, call: number, put: number): Row {
  return {
    strike,
    call_gex_m: call,
    put_gex_m: put,
    net_gex_m: call + put,
    call_oi: Math.round(call * 100),
    put_oi: Math.round(Math.abs(put) * 100),
  }
}

const SPOT = 100

/**
 * Seven strikes inside the default NEAR window (±12% of spot → 88…112) and
 * three far outside it. The in-window count clears the component's six-row
 * "don't bother filtering" floor, so the drawn set is a strict subset and the
 * window total genuinely differs from the chain total.
 */
const NEAR_ROWS: Row[] = [
  row(94, 1, -3),
  row(96, 1, -3),
  row(98, 2, -4),
  row(100, 3, -5),
  row(102, 3, -2),
  row(104, 2, -1),
  row(106, 1, -1),
]
const FAR_ROWS: Row[] = [row(60, 0.5, -0.25), row(70, 0.5, -0.25), row(140, 6, -0.5)]
const WIDE_CHAIN: Row[] = [...FAR_ROWS.slice(0, 2), ...NEAR_ROWS, FAR_ROWS[2]].sort(
  (a, b) => a.strike - b.strike,
)

const sum = (rows: Row[], key: 'call_gex_m' | 'put_gex_m' | 'net_gex_m'): number =>
  rows.reduce((acc, r) => acc + r[key], 0)

async function render(rows: Row[]): Promise<string> {
  const app = createSSRApp({
    render: () =>
      h(GammaExposureMap, {
        rows,
        spot: SPOT,
        callWall: 104,
        putWall: 96,
        gammaFlip: 101,
      }),
  })
  return renderToString(app)
}

/** Strips SSR comment anchors and collapses whitespace for substring matching. */
function text(html: string): string {
  return html
    .replace(/<!--[^>]*-->/g, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

describe('GammaExposureMap exposure HUD — scope is stated, never implied', () => {
  it('tags the readout as a window total when the chart draws a subset of the chain', async () => {
    const html = await render(WIDE_CHAIN)
    const flat = text(html)

    // Sanity: the fixture really is a strict subset, otherwise the assertion
    // below would pass for the wrong reason.
    expect(NEAR_ROWS.length).toBeLessThan(WIDE_CHAIN.length)
    expect(flat).toContain(`IN VIEW ${NEAR_ROWS.length}/${WIDE_CHAIN.length}`)
    expect(flat).not.toContain('FULL CHAIN')
  })

  it('tags the readout FULL CHAIN when every strike is drawn', async () => {
    const html = await render(NEAR_ROWS)
    const flat = text(html)

    expect(flat).toContain('FULL CHAIN')
    expect(flat).not.toContain('IN VIEW')
  })

  it('the window NET it reports is the window sum, which differs from the chain total', async () => {
    const windowNet = sum(NEAR_ROWS, 'net_gex_m')
    const chainNet = sum(WIDE_CHAIN, 'net_gex_m')

    // The defect this guards: these two numbers are not equal, and both were
    // rendered in the same panel with no label separating them.
    expect(windowNet).not.toBeCloseTo(chainNet, 3)

    const flat = text(await render(WIDE_CHAIN))
    const sign = windowNet > 0 ? '+' : windowNet < 0 ? '-' : ''
    expect(flat).toContain(`${sign}$${Math.abs(windowNet).toFixed(1)}M`)
  })

  it('reports PUT GEX with its put-negative sign, not a bare magnitude', async () => {
    const flat = text(await render(NEAR_ROWS))
    const putTotal = sum(NEAR_ROWS, 'put_gex_m')

    expect(putTotal).toBeLessThan(0)
    expect(flat).toContain(`PUT GEX -$${Math.abs(putTotal).toFixed(1)}M`)
    // The pre-fix rendering: an unsigned magnitude that reads as long gamma.
    expect(flat).not.toContain(`PUT GEX $${Math.abs(putTotal).toFixed(1)}M`)
  })

  it('reports CALL GEX signed positive, so the two sides read on one convention', async () => {
    const flat = text(await render(NEAR_ROWS))
    const callTotal = sum(NEAR_ROWS, 'call_gex_m')

    expect(callTotal).toBeGreaterThan(0)
    expect(flat).toContain(`CALL GEX +$${callTotal.toFixed(1)}M`)
  })

  it('keeps PUT OI positive — a contract count has no put-negative convention', async () => {
    const src = readFileSync(join(root, 'components', 'GammaExposureMap.vue'), 'utf8')
    // The signed branch must apply to GEX only; OI stays `r.put_oi`.
    expect(src).toMatch(/metric\.value === 'gex' \? r\.put_gex_m : r\.put_oi/)
    expect(src).not.toMatch(/metric\.value === 'gex' \? Math\.abs\(r\.put_gex_m\) : r\.put_oi/)
  })
})

describe('negative GEX renders as -$X.XM, never $-X.XM', () => {
  it('optSignedGex puts the sign ahead of the currency symbol', () => {
    expect(optSignedGex(-7.24, 1)).toBe('-$7.2M')
    expect(optSignedGex(7.24, 1)).toBe('+$7.2M')
    expect(optSignedGex(0, 1)).toBe('+$0.0M')
    expect(optSignedGex(-1800, 1)).toBe('-$1.8B')
  })

  it('reports missing GEX as DASH rather than a flat +$0.0M', () => {
    // `+$0.0M` reads as "measured, and gamma is flat". A symbol we have no
    // GEX for must not be indistinguishable from one that is genuinely flat.
    for (const missing of [null, undefined, NaN, Infinity, -Infinity, '', '   ', {}, []]) {
      expect(optSignedGex(missing, 1)).toBe(DASH)
    }
    expect(optSignedGex(null, 2)).toBe(DASH)
    expect(optSignedGex(0, 1)).toBe('+$0.0M')
  })

  it('no GEX readout hand-builds a dollar string around a signed number', () => {
    // `$${num(signedValue)}M` is the exact shape that produced `$-7.2M`.
    const MALFORMED = /\$\$\{(?:num|optNum)\([^)]*\)\}M/
    for (const rel of [
      ['views', 'OptionsView.vue'],
      ['components', 'GammaHistoryStrip.vue'],
    ] as const) {
      const src = readFileSync(join(root, ...rel), 'utf8')
      expect(MALFORMED.test(src), `${rel.join('/')} must format GEX via optGex/optSignedGex`).toBe(
        false,
      )
    }
  })

  it('optGex still owns the unsigned form the EXPOSURE badge uses', () => {
    expect(optGex(-7.24, 1)).toBe('-$7.2M')
    expect(optGex(7.24, 1)).toBe('$7.2M')
  })
})

describe('OptionsView panel numbering and header badges', () => {
  const src = readFileSync(join(root, 'views', 'OptionsView.vue'), 'utf8')

  it('numbers the rendered panels consecutively from 01', () => {
    // Panels 05 and 06 sit inside a `v-else-if="false"` branch retained for a
    // pending migration, so the reachable sequence is the `index=` props on the
    // live panels. It previously ran 01, 02, 03, 05b — implying a 04 and a 05a
    // that do not exist.
    const indices = [...src.matchAll(/index="(\d+[a-z]?)"/g)].map((m) => m[1])
    expect(indices).toEqual(['01', '02', '03', '04'])
  })

  it('does not print the gamma flip twice under two names', () => {
    // `summary.zero_gamma` is written from the same solved level as
    // `summary.gamma_flip`, so an unconditional badge rendered one number as
    // both FLIP and ZERO-GAMMA.
    expect(src).not.toMatch(/v-if="s\?\.zero_gamma != null"/)
    expect(src).toMatch(/v-if="zeroGammaDistinct"/)
  })
})
