/**
 * Desk watchlist must not show a Sharpe (or sibling window-stat) that
 * disagrees with Market. Market trajectory defaults to 1y; Desk probes 1m
 * for the 30-day spark only. Sharpe is omitted from the watchlist.
 *
 * Hairline / last-row rules are asserted on the shipped Desk CSS.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const desk = readFileSync(join(srcRoot, 'views', 'DeskView.vue'), 'utf8')
const market = readFileSync(join(srcRoot, 'views', 'MarketView.vue'), 'utf8')
const chart = readFileSync(join(srcRoot, 'components', 'TrajectoryChart.vue'), 'utf8')

describe('Desk vs Market Sharpe alignment', () => {
  it('Market trajectory window stays 1y; Desk watchlist does not render 1m Sharpe', () => {
    expect(market).toContain("const win = ref<TrajWindow>('1y')")
    expect(market).toContain('api.trajectory(reqSym, win.value)')
    expect(desk).toContain("api.trajectory(clean, '1m'")
    expect(desk).toContain("api.trajectory(sym, '1m'")
    expect(desk).not.toContain('col-sharpe')
    expect(desk).not.toContain('probeResults[sym]?.stats?.sharpe')
    expect(desk).not.toMatch(/<th[^>]*>Sharpe<\/th>/)
  })

  it('keeps the 30-day spark / trajectory graph path and does not restyle TrajectoryChart', () => {
    expect(desk).toContain('30-Day Trend')
    expect(desk).toContain('watchSparks[sym]')
    expect(desk).toContain('class="spark"')
    expect(chart).toContain('The financial trajectory')
  })
})

describe('Desk bottom watchlist hairlines', () => {
  it('last-row rules span every watchlist cell and spark content is vertically centered', () => {
    expect(desk).toContain('table-watchlist')
    expect(desk).toMatch(/\.table-watchlist[\s\S]*border-collapse:\s*separate/)
    expect(desk).toMatch(/\.table-watchlist[\s\S]*tbody tr:last-child td[\s\S]*border-bottom/)
    expect(desk).toMatch(/\.table-watchlist[\s\S]*spark-cell[\s\S]*vertical-align:\s*middle/)
    expect(desk).toMatch(/\.table-watchlist th,\s*\n\s*\.table-watchlist td/)
  })
})
