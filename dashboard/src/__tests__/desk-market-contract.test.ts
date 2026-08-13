import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const desk = readFileSync(join(srcRoot, 'views', 'DeskView.vue'), 'utf8')
const market = readFileSync(join(srcRoot, 'views', 'MarketView.vue'), 'utf8')
const api = readFileSync(join(srcRoot, 'api.ts'), 'utf8')
const app = readFileSync(join(srcRoot, 'App.vue'), 'utf8')

describe('desk and market live operator contract', () => {
  it('does not present the desk as a paper-trading sandbox', () => {
    expect(desk).not.toContain('PAPER TRADING MODE')
    expect(desk).not.toContain('PAPER TRADING')
    expect(desk).toContain('RESEARCH BOOK')
    expect(desk).toContain('LIVE BOOK CLEARED')
    expect(desk).toContain('STANDBY')
  })

  it('keeps PEAD and directional last/1d marks on a live refresh path', () => {
    expect(desk).toContain('refreshBoardMarks')
    expect(desk).toContain('api.quotes')
    expect(desk).toContain('markLast(c.symbol)')
    expect(desk).toContain('markLast(s.symbol)')
    expect(desk).toContain('v-for="c in filteredPead" :key="c.symbol"')
    expect(desk).toContain('v-for="s in filteredSignals"')
    expect(desk).toContain(':key="s.symbol"')
    expect(api).toContain('/api/quotes?symbols=')
  })

  it('does not let a status poll rebuild over a completed scan depth', () => {
    expect(app).toContain('lastStatusDepth')
    expect(app).toContain('api.status(lastStatusDepth.value)')
  })

  it('refreshes the market mark from live last instead of a hardcoded month window', () => {
    expect(market).not.toContain("lastDate.startsWith('2026-07')")
    expect(market).not.toContain("lastDate.startsWith('2026-08')")
    expect(market).toContain('observedAgeDays')
    expect(market).toContain("traj.value.quality === 'live'")
    expect(market).toContain('REFRESH MARK')
    expect(market).toContain('LIVE MARK')
    expect(market).toContain('30_000')
  })
})
