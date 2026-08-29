import { describe, expect, it } from 'vitest'
import { TOOLS_MENU_PREFERRED_MAX, placeToolsMenuStyle } from '@/toolsMenu'

function buttonNearRailFoot(viewportHeight = 900): DOMRect {
  // Tools sits above the pinned Account block — near the bottom of a desktop rail.
  return {
    top: viewportHeight - 140,
    right: 80,
    bottom: viewportHeight - 92,
    left: 0,
    width: 80,
    height: 48,
    x: 0,
    y: viewportHeight - 140,
    toJSON() {
      return this
    },
  }
}

describe('tools menu placement (shipped)', () => {
  it('opens upward from a bottom-pinned desktop Tools button and clamps height to the viewport', () => {
    const viewport = { width: 1440, height: 900 }
    const style = placeToolsMenuStyle(buttonNearRailFoot(900), viewport)

    expect(style.position).toBe('fixed')
    expect(style.top).toBe('auto')
    expect(style.bottom).not.toBe('auto')
    const maxHeight = Number.parseInt(style.maxHeight, 10)
    expect(maxHeight).toBeLessThanOrEqual(TOOLS_MENU_PREFERRED_MAX)
    expect(maxHeight).toBeLessThanOrEqual(viewport.height - 8)
    const bottomPx = Number.parseInt(style.bottom, 10)
    const menuTop = viewport.height - bottomPx - maxHeight
    expect(menuTop).toBeGreaterThanOrEqual(0)
    expect(bottomPx + maxHeight).toBeLessThanOrEqual(viewport.height)
    expect(style.left).toBe('82px')
  })

  it('opens downward only when there is room below the button for the preferred height', () => {
    const viewport = { width: 1440, height: 900 }
    const highButton = {
      top: 80,
      right: 80,
      bottom: 128,
      left: 0,
      width: 80,
      height: 48,
    }
    const style = placeToolsMenuStyle(highButton, viewport)
    expect(style.top).toBe('80px')
    expect(style.bottom).toBe('auto')
    expect(Number.parseInt(style.maxHeight, 10)).toBeLessThanOrEqual(TOOLS_MENU_PREFERRED_MAX)
  })

  it('clamps a mid-rail downward menu so it cannot paint past the viewport', () => {
    const viewport = { width: 1440, height: 700 }
    const mid = {
      top: 420,
      right: 80,
      bottom: 468,
      left: 0,
      width: 80,
      height: 48,
    }
    const style = placeToolsMenuStyle(mid, viewport)
    const maxHeight = Number.parseInt(style.maxHeight, 10)
    if (style.top === 'auto') {
      const bottomPx = Number.parseInt(style.bottom, 10)
      expect(bottomPx + maxHeight).toBeLessThanOrEqual(viewport.height)
    } else {
      const topPx = Number.parseInt(style.top, 10)
      expect(topPx + maxHeight).toBeLessThanOrEqual(viewport.height)
    }
    expect(maxHeight).toBeLessThan(TOOLS_MENU_PREFERRED_MAX)
  })

  it('opens a narrow viewport menu upward with a clamped height', () => {
    const viewport = { width: 700, height: 640 }
    const style = placeToolsMenuStyle(buttonNearRailFoot(640), viewport)
    expect(style.top).toBe('auto')
    expect(Number.parseInt(style.maxHeight, 10)).toBeLessThanOrEqual(viewport.height - 8)
  })
})
