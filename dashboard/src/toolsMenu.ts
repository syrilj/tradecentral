/**
 * Tools flyout placement. The rail pins Tools near the bottom, so a
 * downward menu at `top: button.top` with a 520px cap still paints
 * research items off-screen. Clamp to the viewport and flip upward
 * when there is more room above the button.
 */

export interface ToolsMenuRect {
  top: number
  right: number
  bottom: number
  left: number
  width: number
  height: number
}

export interface ToolsMenuViewport {
  width: number
  height: number
}

export interface ToolsMenuStyle {
  position: 'fixed'
  left: string
  top: string
  bottom: string
  maxHeight: string
  zIndex: string
}

export const TOOLS_MENU_MOBILE_MAX = 780
export const TOOLS_MENU_WIDTH = 208
export const TOOLS_MENU_PREFERRED_MAX = 520
export const TOOLS_MENU_MIN_HEIGHT = 160

export function placeToolsMenuStyle(
  rect: ToolsMenuRect,
  viewport: ToolsMenuViewport,
): ToolsMenuStyle {
  const preferred = Math.min(TOOLS_MENU_PREFERRED_MAX, Math.round(viewport.height * 0.7))
  const gutter = 8

  if (viewport.width <= TOOLS_MENU_MOBILE_MAX) {
    const spaceAbove = Math.max(0, rect.top - gutter)
    const maxHeight = Math.max(TOOLS_MENU_MIN_HEIGHT, Math.min(preferred, spaceAbove))
    return {
      position: 'fixed',
      left: `${Math.round(Math.max(gutter, rect.right - TOOLS_MENU_WIDTH))}px`,
      top: 'auto',
      bottom: `${Math.round(Math.max(gutter, viewport.height - rect.top + 2))}px`,
      maxHeight: `${Math.round(maxHeight)}px`,
      zIndex: '90',
    }
  }

  const spaceBelow = Math.max(0, viewport.height - rect.top - gutter)
  const spaceAbove = Math.max(0, rect.bottom - gutter)
  const openDown = spaceBelow >= preferred || spaceBelow >= spaceAbove

  if (openDown) {
    const maxHeight = Math.max(TOOLS_MENU_MIN_HEIGHT, Math.min(preferred, spaceBelow))
    return {
      position: 'fixed',
      left: `${Math.round(rect.right + 2)}px`,
      top: `${Math.round(rect.top)}px`,
      bottom: 'auto',
      maxHeight: `${Math.round(maxHeight)}px`,
      zIndex: '90',
    }
  }

  const maxHeight = Math.max(TOOLS_MENU_MIN_HEIGHT, Math.min(preferred, spaceAbove))
  return {
    position: 'fixed',
    left: `${Math.round(rect.right + 2)}px`,
    top: 'auto',
    bottom: `${Math.round(Math.max(gutter, viewport.height - rect.bottom))}px`,
    maxHeight: `${Math.round(maxHeight)}px`,
    zIndex: '90',
  }
}
