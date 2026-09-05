/**
 * Pure phase math for the capability scroll-reveal: a strip of icons flies
 * into slots inside a headline as the section is pinned and scrubbed, then
 * the headline settles in a shuffled stagger. No DOM, no GSAP — the
 * component maps these fractions onto actual transforms.
 */

/**
 * Progress bands (0..1) within the pinned scroll range.
 *
 * The bands are front-loaded on purpose. An earlier split (0.35 / 0.70) left
 * the first two thirds of a three-viewport pin showing an empty screen before
 * a single word appeared — a long dead scroll in the middle of the page.
 * Icons now land by 18%, the flight is done by 46%, the sentence is complete
 * by `settleEnd`, and the remaining band holds the finished headline on
 * screen long enough to read before the pin releases.
 */
export const REVEAL_PHASES = {
  enterEnd: 0.18,
  flightEnd: 0.46,
  settleEnd: 0.82,
} as const

function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v))
}

/** Icon strip fades in and rises into place during the enter band. */
export function stripEntrance(progress: number): { opacity: number; offset: number } {
  const p = clamp01(progress / REVEAL_PHASES.enterEnd)
  return { opacity: p, offset: (1 - p) * 24 }
}

/**
 * Per-icon flight fraction across the flight band: each icon travels
 * vertically first, then horizontally, staggered by index so icons depart
 * in sequence rather than all at once.
 */
export function iconFlight(
  progress: number,
  index: number,
  count: number,
): { y: number; x: number } {
  if (progress <= REVEAL_PHASES.enterEnd) return { y: 0, x: 0 }
  if (progress >= REVEAL_PHASES.flightEnd) return { y: 1, x: 1 }
  const span = REVEAL_PHASES.flightEnd - REVEAL_PHASES.enterEnd
  const staggerStep = (span / (count + 1)) * 0.6
  const start = REVEAL_PHASES.enterEnd + index * staggerStep
  const local = clamp01((progress - start) / (span * 0.55))
  return { y: clamp01(local / 0.5), x: clamp01((local - 0.5) / 0.5) }
}

/** Headline segment opacity: reveals in `orderIndex` sequence across the settle band. */
export function segmentOpacity(progress: number, orderIndex: number, segmentCount: number): number {
  if (progress <= REVEAL_PHASES.flightEnd) return 0
  const span = REVEAL_PHASES.settleEnd - REVEAL_PHASES.flightEnd
  const step = span / segmentCount
  const start = REVEAL_PHASES.flightEnd + orderIndex * step
  return clamp01((progress - start) / (step * 0.7))
}

/** Fisher-Yates shuffle with an injected RNG so the reveal order is testable. */
export function shuffleOrder(count: number, rand: () => number = Math.random): number[] {
  const order = Array.from({ length: count }, (_, i) => i)
  for (let i = order.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1))
    ;[order[i], order[j]] = [order[j], order[i]]
  }
  return order
}
