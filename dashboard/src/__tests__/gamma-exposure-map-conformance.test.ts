/**
 * GammaExposureMap — desk-surface conformance for assertion VAL-DS-005.
 *
 * GammaExposureMap.vue is a desk component, so the design-conformance guard
 * (src/__tests__/design-conformance.test.ts) scans it for hardcoded colors,
 * undefined tokens, and forbidden effects once it is removed from the EXEMPT
 * list. This suite covers the two VAL-DS-005-specific defects the guard does
 * not encode:
 *
 *   1. Level badges must size to their text content — long strike labels such
 *      as `CALL W $1234.56` must not clip or overlap an adjacent badge. The
 *      prior implementation used a fixed 64px <rect> with a 56px minGap, which
 *      clipped long labels and overlapped neighbours.
 *   2. No font-size below --t-micro (11px / 0.6875rem). The prior
 *      implementation carried 7.5px–10.5px raw values, below the token scale.
 *
 * The guard test covers Rule 1 (no hardcoded colors) for this file directly;
 * this suite additionally re-asserts it so the badge/font defects cannot
 * regress even if the file were re-added to EXEMPT.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = readFileSync(join(root, 'components', 'GammaExposureMap.vue'), 'utf8')

/** Extracts the contents of the <style scoped> block so font-size scanning
 *  only inspects real CSS declarations, not prose comments in <script>. */
const styleBlock = src.match(/<style[^>]*>([\s\S]*?)<\/style>/)?.[1] ?? ''

/**
 * Matches a raw pixel font-size value in a `font:` shorthand or a standalone
 * `font-size:` declaration: `9px`, `8.5px`, `10.5px`, etc. The size must be the
 * last numeric token immediately before `px` in the declaration, so a
 * `0.12s ease` timing inside a `font:` shorthand is not mistaken for a size.
 * Rem/`var(--t-*)` values are intentionally not matched so only the forbidden
 * raw-px scale is flagged.
 */
const RAW_PX_FONT = /font(?:-size)?\s*:[^;}]*(\d+(?:\.\d+)?)px\b/g

/** Finds every raw-px font-size value and returns the numeric size in px. */
function findRawPxFontSizes(css: string): number[] {
  const sizes: number[] = []
  for (const m of css.matchAll(RAW_PX_FONT)) {
    sizes.push(parseFloat(m[1]))
  }
  return sizes
}

describe('GammaExposureMap — VAL-DS-005 level badges do not clip long strike labels', () => {
  it('does not use a fixed-width level badge background rect (width="64")', () => {
    // The prior defect was a <rect ... width="64" .../> with x = labelX - 32
    // and a 56px minGap, so any label wider than 64px clipped and adjacent
    // badges overlapped. The badge width must be derived from the label text,
    // not a fixed constant.
    expect(src, 'GammaExposureMap.vue must not hardcode the level badge width to 64px').not.toMatch(
      /width="64"/,
    )
    expect(
      src,
      'GammaExposureMap.vue must not offset the badge by a fixed -32 from labelX',
    ).not.toMatch(/labelX\s*-\s*32/)
  })

  it('sizes the level badge to the rendered label text (width is derived from content)', () => {
    // A width-aware badge computes its <rect> width from a measured text
    // width (an estimated text-width helper / char-width approximation), not a
    // constant. The source must reference a per-label width calculation such
    // as a `badgeW` / `labelW` / `badgeWidth` field on each Level, or a
    // measurement helper.
    const hasWidthField =
      /\bbadgeW(?:idth)?\b/.test(src) ||
      /\blabelW(?:idth)?\b/.test(src) ||
      /\btextW(?:idth)?\b/.test(src) ||
      /\bestimat\w*\s*\(/i.test(src)
    expect(
      hasWidthField,
      'GammaExposureMap.vue must derive the level badge width from the label ' +
        'text content (e.g. a badgeWidth/labelWidth field or text-width estimator)',
    ).toBe(true)
  })

  it('the badge minGap accommodates a long label (CALL W $1234.56)', () => {
    // The prior 56px minGap was smaller than a 64px badge, guaranteeing
    // overlap. The collision-separation gap must now be driven by the
    // (content-derived) badge width, not a raw 56 constant that ignores label
    // length.
    expect(
      src,
      'GammaExposureMap.vue must not use a fixed 56px minGap that ignores ' + 'label width',
    ).not.toMatch(/minGap\s*=\s*56\b/)
  })
})

describe('GammaExposureMap — VAL-DS-005 no font-size below --t-micro (11px)', () => {
  it('uses no raw px font-size below 11px in scoped styles', () => {
    const under = findRawPxFontSizes(styleBlock).filter((px) => px < 11)
    expect(
      under,
      `GammaExposureMap.vue has raw font sizes below 11px (--t-micro): ${under.join(', ')}px`,
    ).toEqual([])
  })

  it('raises the type scale to the --t-micro token (11px / 0.6875rem) minimum', () => {
    // The fix must replace the raw 7.5px–10.5px values with token-scale sizes.
    // At least one --t-* token reference should be present in the scoped
    // styles, anchoring the type to the design system rather than raw px.
    expect(
      styleBlock,
      'GammaExposureMap.vue must use a --t-* type-scale token for its labels',
    ).toMatch(/var\(--t-(?:micro|tiny|small|body|lead|fig|fig-lg|display)\)/)
  })
})

describe('GammaExposureMap — desk color-conformance (guard re-assertion)', () => {
  it('has no hardcoded palette color literals in scoped styles', () => {
    // Structural pure-black/pure-white rgba are allowed by the guard; only
    // semantic palette literals (call/put/etc.) are forbidden. The two prior
    // regime-zone rgba literals (#10b981 call / #f43f5e put) must be gone.
    const paletteLiterals = [
      ...styleBlock.matchAll(
        /rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*[\d.]+\s*)?\)/g,
      ),
    ]
      .map((m) => m[0])
      .filter((lit) => {
        // Allow structural pure-black (0,0,0,..) and pure-white (255,255,255,..)
        const nums = lit.match(/\d{1,3}/g)!.map(Number)
        const isBlack = nums[0] === 0 && nums[1] === 0 && nums[2] === 0
        const isWhite = nums[0] === 255 && nums[1] === 255 && nums[2] === 255
        return !isBlack && !isWhite
      })
    expect(
      paletteLiterals,
      `GammaExposureMap.vue has hardcoded palette rgba literals:\n${paletteLiterals.join('\n')}`,
    ).toEqual([])
  })
})
