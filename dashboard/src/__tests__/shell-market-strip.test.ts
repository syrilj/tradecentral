import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const app = readFileSync(join(root, 'App.vue'), 'utf8')
const api = readFileSync(join(root, 'api.ts'), 'utf8')
const icons = readFileSync(join(root, 'components', 'AppIcon.vue'), 'utf8')

describe('application market strip contract', () => {
  it('shows observed freshness and trend instead of anonymous number blocks', () => {
    expect(app).toContain('compactBarDate')
    expect(app).toContain('sparklinePath')
    expect(app).toContain("`quality-${m.quality}`")
    expect(app).toContain("`${m.asofLabel} · STALE`")
    expect(app).toContain('changeBasis: chg1d != null ? \'1D\' : \'1M\'')
    expect(api).toContain('change_basis?: \'last_two_observed_closes\'')
  })

  it('labels the energy proxy honestly and dates the rotation source', () => {
    expect(app).toContain("{ sym: 'XLE', label: 'Energy' }")
    expect(app).not.toContain("{ sym: 'XLE', label: 'Oil' }")
    expect(app).toContain('rotationAsOf')
    expect(app).toContain('rotationFreshness')
    expect(app).toContain('BAR ${compactBarDate(rotationAsOf.value)}')
  })

  it('keeps rotation dated from the independently refreshed sector panel', () => {
    expect(app).toContain('board.sector_flow === flow')
    expect(app).toContain('sector_flow: flow')
  })

  it('moves search into the top strip and removes the detached rail block', () => {
    expect(app).toContain('class="strip-search"')
    expect(app).not.toContain('class="find"')
    expect(app).not.toContain('.profile-block')
    expect(app).not.toContain('.profile-label')
  })

  it('uses the TradeCentral identity throughout the operator shell', () => {
    expect(app).toContain("import TradeCentralMark from '@/components/TradeCentralMark.vue'")
    expect(app).toContain('aria-label="TradeCentral workspaces"')
    expect(app).toContain('<TradeCentralMark :size="28" />')
    expect(app).toContain('<strong>Trade</strong>')
    expect(app).toContain('<strong>Central</strong>')
    expect(app).not.toContain('class="mark-e"')
  })

  it('gives secondary workspaces distinct icons and a keyboard-operable menu', () => {
    for (const icon of ['sectors', 'pulse', 'momentum', 'fintel', 'evolution', 'adaptive', 'graph', 'changepoints', 'cloud']) {
      expect(app).toContain(`icon: '${icon}'`)
      expect(icons).toContain(`name === '${icon}'`)
    }
    expect(app).toContain('aria-haspopup="menu"')
    expect(app).toContain('@keydown="onMoreMenuKey"')
    expect(app).toContain("document.addEventListener('pointerdown', onOutsidePointer)")
  })

  it('keeps desktop Account visible and teleports Tools so the flyout is not clipped', () => {
    expect(app).toContain('class="clerk-user"')
    expect(app).toContain('class="rail-foot"')
    expect(app).toContain("<Teleport to=\"body\">")
    expect(app).toContain('id="workspace-tools-menu"')
    expect(app).toContain('placeToolsMenu')
    expect(app).toContain("from '@/toolsMenu'")
    expect(app).toContain('placeToolsMenuStyle')
    expect(app).not.toMatch(/top: `\$\{Math\.round\(rect\.top\)\}px`/)
    expect(app).not.toMatch(/@media \(max-width: 1080px\)[\s\S]{0,400}\.clerk-user[\s\S]{0,80}display:\s*none/)
  })

  it('maps a present market_session instead of staying on CAL SYNC', () => {
    expect(app).toContain("from '@/marketSession'")
    expect(app).toContain('sessionLabelOf')
    expect(app).toContain('formatMarketCountdown')
    expect(app).toContain('marketClock.data.value?.market_session')
    expect(app).not.toContain("regular: 'RTH OPEN'")
  })
})
