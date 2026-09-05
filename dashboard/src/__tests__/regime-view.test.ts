/**
 * /regime — route, lazy-activation and cleanup contract.
 *
 * This repo's test harness runs under `environment: 'node'` (see
 * vitest.config.ts) with no DOM shim and no @vue/test-utils installed —
 * every other view/component test in `__tests__/` (router.test.ts,
 * kalman-view.test.ts, livestack-view.test.ts, chain-view.test.ts, ...)
 * verifies component behaviour by reading the compiled .vue source and
 * asserting on the exact code paths that implement a contract, rather than
 * mounting. This file follows that same, only-available methodology.
 *
 * Where the brief asks to "test it directly" (no fetch on mount / one fetch
 * after activation), the assertions below target the precise lines that
 * make that true — `immediate: false` + `enabled: () => activated.value`
 * (so nothing can fire before the gate flips) paired with `goLive()`
 * calling `.refresh()` explicitly (so activation is exactly what triggers
 * the first fetch) — rather than a loose keyword match.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

const routerSrc = source('router.ts')
const view = source('views/RegimeView.vue')
const chart = source('components/RegimeSurfaceChart.vue')
const breadth = source('components/RegimeBreadthStrip.vue')

describe('/regime route', () => {
  it('resolves at /regime and is lazy-loaded like every other route', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/regime['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]regime['"]/)
    // Dynamic import — not a static top-of-file import — is what makes the
    // route lazy; router.ts imports every view this way.
    expect(routerSrc).toMatch(
      /component:\s*\(\)\s*=>\s*import\(['"]@\/views\/RegimeView\.vue['"]\)/,
    )
    expect(routerSrc).toMatch(/meta:\s*\{\s*title:\s*['"]Regime['"]/)
  })

  it('does not statically import RegimeView.vue anywhere in router.ts', () => {
    expect(routerSrc).not.toMatch(/^import .*RegimeView/m)
  })
})

describe('/regime is reachable from the primary nav, exactly once', () => {
  const app = source('App.vue')

  it('sits in primaryNav with an icon', () => {
    const primary = app.match(/const primaryNav = \[\s*([\s\S]*?)\] as const/)![1]
    expect(primary).toContain("name: 'regime'")
    expect(primary).toContain("icon: 'regime'")
  })

  it('appears in exactly one nav group', () => {
    /*
     * It was originally added to macroTools, feeding the Tools overflow. Being
     * listed in both groups is not cosmetic: overflowActiveItem matches purely
     * on route name, so on /regime the primary nav item and the Tools button
     * would both render active at once.
     */
    const occurrences = app.match(/name: 'regime'/g) ?? []
    expect(occurrences).toHaveLength(1)
  })

  it('has a glyph defined in AppIcon so the nav item is not blank', () => {
    expect(source('components/AppIcon.vue')).toContain("name === 'regime'")
  })
})

describe('lazy activation — nothing fetches on mount, activation triggers exactly one fetch', () => {
  it('starts the activation gate closed', () => {
    expect(view).toContain('const activated = ref(false)')
  })

  it('gates both clocks behind the SAME activation flag with no immediate fetch', () => {
    // Both useResource() calls for the slow (options) and fast (spot)
    // clocks must be immediate: false and enabled only once `activated` is
    // true — this is what makes "nothing fetches on mount" true rather than
    // merely asserted in prose.
    const optionsResourceBlock = view.slice(
      view.indexOf('const optionsRes = useResource'),
      view.indexOf('const optionsRes = useResource') + 400,
    )
    expect(optionsResourceBlock).toContain('immediate: false')
    expect(optionsResourceBlock).toContain('enabled: () => activated.value')

    const spotResourceBlock = view.slice(
      view.indexOf('const spotRes = useResource'),
      view.indexOf('const spotRes = useResource') + 300,
    )
    expect(spotResourceBlock).toContain('immediate: false')
    expect(spotResourceBlock).toContain('enabled: () => activated.value')
  })

  it('fires the first fetch only from goLive(), not from a watcher or onMounted', () => {
    const goLiveBlock = view.slice(
      view.indexOf('function goLive'),
      view.indexOf('function goLive') + 300,
    )
    expect(goLiveBlock).toContain('activated.value = true')
    expect(goLiveBlock).toContain('void optionsRes.refresh()')
    expect(goLiveBlock).toContain('void spotRes.refresh()')
    // No onMounted hook anywhere kicks off a fetch — the view has no
    // onMounted at all, which is the strongest version of "nothing fetches
    // on mount" this static check can assert.
    expect(view).not.toContain('onMounted')
  })

  it('renders an explicit idle state gated on the SAME flag, with a GO LIVE control wired to goLive', () => {
    expect(view).toContain('v-if="!activated"')
    expect(view).toMatch(/class="idle-gate"[\s\S]{0,400}@click="goLive"/)
    expect(view).toContain('GO LIVE')
  })

  it('re-clears and re-fetches both clocks on a symbol change, only while already activated', () => {
    const applySymbolBlock = view.slice(
      view.indexOf('function applySymbol'),
      view.indexOf('function applySymbol') + 500,
    )
    expect(applySymbolBlock).toContain('if (activated.value)')
    expect(applySymbolBlock).toContain('optionsRes.refresh({ clear: true })')
    expect(applySymbolBlock).toContain('spotRes.refresh({ clear: true })')
  })
})

describe('two clocks', () => {
  it('polls the slow chain clock at ~75s and the fast spot clock at ~3s', () => {
    expect(view).toContain('const SLOW_POLL_MS = 75_000')
    expect(view).toContain('const FAST_POLL_MS = 3_000')
  })

  it('builds the smile and risk-neutral density exactly once per slow payload, cached in a shallowRef', () => {
    expect(view).toContain('const slowDerived = shallowRef')
    // The build happens inside the watcher keyed on the SLOW resource's data
    // (and the operator's expiry pick), not inside any computed that would
    // re-run on the fast tick.
    const start = view.indexOf('watch(\n  [() => optionsRes.data.value, smileExpiry]')
    expect(start).toBeGreaterThan(-1)
    const watcherBlock = view.slice(start, start + 500)
    expect(watcherBlock).toContain('buildSmile(payload, expiry)')
    expect(watcherBlock).toContain('riskNeutralDensity(smile)')
    expect(watcherBlock).toContain('slowDerived.value =')
  })

  it('builds the density from ONE expiry, selectable, not the blended surface', () => {
    // Blending every expiry's IV at each strike is what made the repriced call
    // curve non-convex, drove the density negative, and left the probability
    // panel permanently behind its own "not reliable" notice.
    expect(view).toContain('availableSmileExpiries')
    expect(view).toContain('const smileExpiry = ref<string | null>(null)')
    expect(view).toContain('const expiryChoices = computed(')
    // A stale expiry string from the previous symbol must not silently fall
    // through to "nearest" on the new one.
    expect(view).toContain('watch(symbol, () => {')
  })

  it('recomputes the regime stack from the cached smile, not from a fresh network read', () => {
    expect(view).toContain('buildRegimeState(payload, effectiveSpot.value)')
    expect(view).toContain('deriveTilt(regimeState.value, charm, sessionFractionRemaining.value)')
    expect(view).toContain('applyTilt(slowDerived.value.smile, tilt.value, regimeState.value)')
    expect(view).toContain(
      'regimeProbabilities(tiltedResult.value?.grid ?? null, regimeState.value)',
    )
  })

  it('the fast clock reads a cheap quotes call for spot, not the options chain', () => {
    const spotResourceBlock = view.slice(
      view.indexOf('const spotRes = useResource'),
      view.indexOf('const spotRes = useResource') + 150,
    )
    expect(spotResourceBlock).toContain('api.quotes([symbol.value])')
  })
})

describe('withholds probabilities when the density is not trustworthy', () => {
  /*
   * Observed live on 1DTE SPY: the OTM selection flips from puts to calls at
   * spot and the two sides disagree ~22% in IV across one strike (0.1480 at
   * 771 -> 0.1145 at 772). The median call-put spread over both-sided strikes
   * is ~-0.0005, so it is a genuine quote discontinuity, not a parity offset
   * that calibrates out. Interpolating that step drove ~28% of density mass
   * negative — and the view printed probabilities to two decimals anyway.
   */
  it('grades the density in three bands rather than blanking on any noise', () => {
    // All-or-nothing at 10% clipped mass meant the panel was blank far more
    // often than populated, which reads as broken rather than careful. A
    // distribution that lost a few percent of mass is still worth showing when
    // the loss is stated; one that lost a quarter of it is not.
    expect(view).toContain('const CLIPPED_MASS_CLEAN = 0.02')
    expect(view).toContain('const CLIPPED_MASS_UNUSABLE = 0.25')
    expect(view).toContain("const densityGrade = computed<'clean' | 'degraded' | 'unusable'>")
    expect(view).toContain(
      "const densityUnreliable = computed(() => densityGrade.value === 'unusable')",
    )
  })

  it('gates probabilities on both the clipped-mass ceiling and a blended smile', () => {
    // The gate must short-circuit the computed, not merely hide the markup:
    // a consumer reading `probabilities` must get null, not a broken number.
    const probsBlock = view.slice(view.indexOf('const probabilities = computed'))
    expect(probsBlock.slice(0, 300)).toContain(
      'if (densityUnreliable.value || smileBlended.value) return null',
    )
  })

  it('states the withheld reason instead of rendering the figures', () => {
    expect(view).toContain('v-if="smileBlended"')
    expect(view).toContain('v-else-if="densityUnreliable"')
    expect(view).toMatch(/Density not usable/)
    expect(view).toContain('v-else class="prob-grid"')
  })

  it('states the horizon every probability is conditional on', () => {
    // "62% between the walls" means something completely different at 0DTE
    // than at 30 days; the figure is unreadable without its horizon.
    expect(view).toContain('const probabilityHorizon = computed<string | null>')
    expect(view).toContain('v-if="probabilityHorizon"')
    expect(view).toMatch(/0DTE/)
  })

  it('does not double-report: the softer clipped warning yields to the hard gate', () => {
    expect(view).toContain('clippedMassMaterial && !densityUnreliable')
  })
})

describe('breadth strip fetches only on an explicit click', () => {
  /*
   * Regression guard. This strip first activated on an IntersectionObserver,
   * which was verified wrong in a live browser: the section sits above the
   * fold at the default window size, so "scrolled into view" fired on page
   * load and spent the most expensive call in the app (15 option chains,
   * ~30-45s cold, metered provider) before the operator asked for anything.
   * Viewport-deferred loading suits cheap content; a metered call needs intent.
   */
  it('constructs no IntersectionObserver — visibility must never trigger the fetch', () => {
    // Matches construction/usage, not the word: the module comment explains
    // why the observer was removed and that history is worth keeping.
    expect(breadth).not.toContain('new IntersectionObserver')
    expect(breadth).not.toContain('isIntersecting')
    expect(breadth).not.toContain('.observe(')
  })

  it('emits activate only from the idle gate click handler', () => {
    // fireActivate is the sole emitter, and the only thing that calls it is
    // the button's @click. No lifecycle hook may reach it.
    expect(breadth).toContain("emit('activate')")
    expect(breadth).toMatch(/idle-state[\s\S]{0,400}@click="fireActivate"/)
    expect(breadth).not.toMatch(/onMounted\([\s\S]{0,200}fireActivate/)
  })

  it('renders an explicit idle state that names the cost', () => {
    expect(breadth).toContain('v-if="!activated"')
    expect(breadth).toContain('class="idle-state"')
    expect(breadth).toMatch(/15 option chains/)
  })

  it('the breadth resource in the view is gated behind its OWN flag, separate from the main activation gate', () => {
    expect(view).toContain('const breadthActivated = ref(false)')
    const breadthResourceBlock = view.slice(
      view.indexOf('const breadthRes = useResource'),
      view.indexOf('const breadthRes = useResource') + 250,
    )
    expect(breadthResourceBlock).toContain('immediate: false')
    expect(breadthResourceBlock).toContain('enabled: () => breadthActivated.value')
    // Separate from the surface's own `activated` gate — scrolling to
    // breadth must not depend on having clicked GO LIVE first.
    expect(breadthResourceBlock).not.toContain('activated.value')
  })

  it('the view only starts the breadth resource from its own activate handler', () => {
    const handlerBlock = view.slice(
      view.indexOf('function onBreadthActivate'),
      view.indexOf('function onBreadthActivate') + 200,
    )
    expect(handlerBlock).toContain('breadthActivated.value = true')
    expect(handlerBlock).toContain('void breadthRes.refresh()')
    expect(view).toContain('@activate="onBreadthActivate"')
  })
})

describe('unmeasurable regime — withheld, never a zero or a neutral dial', () => {
  it('branches explicitly on regime === "unmeasurable" before rendering any verdict text', () => {
    expect(view).toMatch(/v-else-if="regimeState\.regime === 'unmeasurable'"/)
    expect(view).toContain('Regime not measurable')
    expect(view).toContain('no open interest observed')
  })

  it('withholds the probabilities panel entirely when unmeasurable, rather than rendering zeroed figures', () => {
    expect(view).toMatch(
      /v-if="regimeState && regimeState\.regime !== 'unmeasurable'"[\s\S]*?label="Probabilities"/,
    )
  })

  it('verdictText returns null for the unmeasurable case instead of a fabricated sentence', () => {
    const verdictBlock = view.slice(
      view.indexOf('const verdictText = computed'),
      view.indexOf('const verdictText = computed') + 250,
    )
    expect(verdictBlock).toContain("if (!s || s.regime === 'unmeasurable') return null")
  })

  it('RegimeSurfaceChart withholds GEX bars (not zeroed bars) when state.measurable is false', () => {
    expect(chart).toContain('v-if="state.measurable && gexBars.length"')
    expect(chart).toContain('GEX NOT MEASURABLE')
    expect(chart).not.toMatch(/gexBars[\s\S]{0,20}\|\|\s*\[\]/) // no silent empty-array substitution masking the withheld state
  })
})

describe('chart stays readable: near-money window and sqrt GEX scale', () => {
  /*
   * Regression guards for the unreadable-chart failure observed live on SPY.
   *
   * (1) The density grids span +/-30-50% (full-chain smile extrapolation)
   * while flip/walls/pin/spot sit within 0.3% of the money. Domaining on ALL
   * grid strikes compressed the entire tradeable region into a ~2px band on
   * a 600-1200 axis. The grids must be clipped to the same window as the
   * GEX bars before they touch the domain or the path builders.
   *
   * (2) The call wall carried ~$3.2B of gamma against a ~$0.5M median. A
   * linear width scale keyed to that max renders 93% of bars under 2px —
   * an empty-looking frame. The width scale must be square-root.
   */
  it('windows density grids to the same near-money band as the GEX bars before domaining', () => {
    expect(chart).toContain('function clipGrid(')
    expect(chart).toContain('const visibleTiltedGrid = computed(')
    expect(chart).toContain('const visibleUntiltedGrid = computed(')
    // The domain must be fed by visibleRows + levels, not raw grid strikes.
    const domainBlock = chart.slice(
      chart.indexOf('const priceDomain = computed'),
      chart.indexOf('const priceDomain = computed') + 800,
    )
    expect(domainBlock).not.toContain('props.tiltedGrid')
    expect(domainBlock).not.toContain('props.untiltedGrid')
    // The paths must read the clipped grids, not the raw props.
    expect(chart).toContain('densityPath(visibleTiltedGrid.value)')
    expect(chart).toContain('densityPath(visibleUntiltedGrid.value)')
  })

  it('scales GEX bar widths by square root of share-of-max, not linearly', () => {
    const scaleBlock = chart.slice(
      chart.indexOf('const gexScale = computed'),
      chart.indexOf('const gexScale = computed') + 300,
    )
    expect(scaleBlock).toContain('Math.sqrt(')
    expect(scaleBlock).not.toContain('linearScale(')
  })

  it('withholds the density curves (not just the numbers) when the rail gates them', () => {
    expect(chart).toContain('densityReliable')
    expect(chart).toContain('DENSITY WITHHELD')
    expect(view).toContain(':density-reliable="!densityUnreliable"')
  })
})

describe('playbook — the read translates into a stance', () => {
  /*
   * "Regime: flip, 0.15% from the flip" is a description, not an answer.
   * The playbook panel is the answer: a stance line per regime plus trigger
   * lines carrying the exact levels whose break changes it.
   */
  it('derives stance/trigger/watch lines from live regime state', () => {
    expect(view).toContain('const playbook = computed<PlaybookLine[]>')
    expect(view).toContain("kind: 'stance'")
    expect(view).toContain("kind: 'trigger'")
    expect(view).toContain("kind: 'watch'")
  })

  it('carries the actual levels (flip, call wall, put wall) in the trigger lines', () => {
    const playbookBlock = view.slice(
      view.indexOf('const playbook = computed'),
      view.indexOf('/* ---- activation'),
    )
    expect(playbookBlock).toContain('s.zeroGamma')
    expect(playbookBlock).toContain('s.callWall')
    expect(playbookBlock).toContain('s.putWall')
    expect(playbookBlock).toContain('s.pinStrike')
  })

  it('renders as its own panel between Verdict and Probabilities, only when measurable', () => {
    expect(view).toContain('label="Playbook"')
    expect(view).toMatch(/label="Playbook"[\s\S]{0,200}playbook/)
    const playbookPanel = view.slice(view.indexOf('label="Playbook"') - 200)
    expect(playbookPanel).toContain("regimeState.regime !== 'unmeasurable'")
  })

  it('says what stands when probabilities are withheld instead of leaving a gap', () => {
    const playbookBlock = view.slice(
      view.indexOf('const playbook = computed'),
      view.indexOf('/* ---- activation'),
    )
    expect(playbookBlock).toContain('densityUnreliable.value')
    expect(view).toContain('direction and trigger levels above stand')
  })
})

describe('breadth strip reads as an aggregate, not fifteen rows', () => {
  it('counts regimes across the universe and renders the counts above the table', () => {
    expect(breadth).toContain('const regimeCounts = computed(')
    expect(breadth).toContain('count-chip')
    expect(breadth).toContain('LONG {{ regimeCounts.long }}')
    expect(breadth).toContain('SHORT {{ regimeCounts.short }}')
    expect(breadth).toContain('FLIP {{ regimeCounts.flip }}')
  })

  it('dedupes per-symbol warnings into unique conditions', () => {
    expect(breadth).toContain('const uniqueWarnings = computed(')
    expect(breadth).toContain('uniqueWarnings.length')
    expect(breadth).not.toContain('payload.warnings.length')
  })

  it('aggregates dated-chain fallbacks into one count chip', () => {
    expect(breadth).toContain('const fallbackRowCount = computed(')
    expect(breadth).toContain('DATED CHAIN ×')
  })
})

describe('tilt constants are on screen, not hidden behind the probability', () => {
  it('renders lambda, kappa, vol scale, theta and pin pull as visible readouts', () => {
    expect(view).toContain('Readout label="lambda" :value="num(tilt.constants.lambda, 3)"')
    expect(view).toContain('Readout label="kappa" :value="num(tilt.constants.kappa, 3)"')
    expect(view).toContain('Readout label="vol scale" :value="num(tilt.volScale, 3)"')
    expect(view).toContain('Readout label="theta" :value="num(tilt.theta, 3)"')
    expect(view).toContain('Readout label="pin pull" :value="num(tilt.pinPull, 3)"')
  })

  it('surfaces the symbol-relative gamma/slope scale the tilt was normalized against, when available', () => {
    expect(view).toContain('regimeState.gammaScaleM != null')
    expect(view).toContain('regimeState.slopeScaleM != null')
  })

  it('shows the clipped-mass warning only in the degraded band, not on every render', () => {
    expect(view).toContain(
      "const clippedMassMaterial = computed(() => densityGrade.value === 'degraded')",
    )
    // Three tiers, and only one may speak: this soft advisory is for a
    // usable-but-noisy density, and it defers once either hard gate (unusable
    // density, or a blended smile) has already withheld the figures outright.
    expect(view).toContain('v-if="clippedMassMaterial && !densityUnreliable && !smileBlended"')
  })
})

describe('staleness readout', () => {
  it('badges both clocks with age-since-fetch, matching how other views badge aged data', () => {
    expect(view).toContain(
      'optionsRes.fetchedAt.value ? `${age(optionsRes.fetchedAt.value)} ago` : DASH',
    )
    expect(view).toContain('spotRes.fetchedAt.value ? `${age(spotRes.fetchedAt.value)} ago` : DASH')
  })
})

describe('cleanup on unmount — no leaked intervals or observers', () => {
  it('both clocks and the breadth resource go through useResource, which owns its own interval/listener disposal', () => {
    // useResource() registers onScopeDispose internally (composables/useResource.ts)
    // to clear its interval and remove its visibilitychange listener; every
    // resource in this view is created through it rather than a hand-rolled
    // setInterval, so mounting/unmounting the view leaks nothing from the
    // two clocks or the breadth poll.
    expect(view).toContain(
      'useResource<OptionsIntelligence>(() => api.options({ symbol: symbol.value })',
    )
    expect(view).toContain('useResource(() => api.quotes([symbol.value])')
    expect(view).toContain('useResource<RegimeBreadthPayload>(fetchBreadth')
    expect(view).not.toContain('setInterval')
    expect(view).not.toContain('setTimeout')
  })

  it('RegimeBreadthStrip holds no lifecycle subscription to clean up', () => {
    // The strip is now a pure click-gated emitter: it registers no observer,
    // timer, or listener of its own, so there is nothing to leak. The parent's
    // useResource owns the only interval and disposes it on scope teardown.
    expect(breadth).not.toContain('addEventListener')
    expect(breadth).not.toContain('setInterval')
    expect(breadth).not.toContain('setTimeout')
    expect(breadth).not.toContain('onMounted')
  })

  it('RegimeSurfaceChart uses useChartSize, which owns its own ResizeObserver disposal', () => {
    expect(chart).toContain('useChartSize(hostRef')
  })
})

describe('accessibility', () => {
  it('the surface chart is an accessible img with a meaningful label and a visually-hidden data-table fallback', () => {
    expect(chart).toContain('role="img"')
    expect(chart).toContain(':aria-label="chartAriaLabel"')
    expect(chart).toContain('class="visually-hidden"')
    expect(chart).toContain('<table')
  })

  it('GEX bars are keyboard-focusable and respond to Enter/Space/Escape/ArrowUp/ArrowDown', () => {
    expect(chart).toContain('tabindex="0"')
    expect(chart).toContain('role="button"')
    expect(chart).toMatch(/ArrowUp.*ArrowDown|ArrowDown.*ArrowUp/s)
  })

  it('the symbol input has an associated label', () => {
    expect(view).toMatch(/<label for="regime-symbol"/)
    expect(view).toMatch(/id="regime-symbol"/)
  })
})

describe('symbol query sync', () => {
  it('defaults to SPY and reads the initial symbol from ?symbol=', () => {
    expect(view).toMatch(/\?\s*route\.query\.symbol\s*:\s*'SPY'\s*\)\.toUpperCase\(\)/)
  })

  it('writes the symbol back to the route on apply', () => {
    expect(view).toContain('void router.replace({ query: { ...route.query, symbol: clean } })')
  })

  it('watches route.query.symbol for external navigation (e.g. global search)', () => {
    expect(view).toContain('() => route.query.symbol')
  })
})

/**
 * The level map: probabilities, order flow, and the mean.
 *
 * These lock the wiring that answers the three things the page could not:
 * how likely a level is to be REACHED, what the tape did at that price, and
 * where price is being pulled back to. Source-text assertions, per the
 * methodology note at the top of this file.
 */
describe('/regime level map — probability, order flow and the mean', () => {
  it('reads the order-flow matrix the absorption endpoint has always shipped', () => {
    // The matrix (volume-at-price split buy/sell, per-bin delta, wick
    // absorption, touch/rejection counts, scored zones) was computed on every
    // /api/absorption call and never read by this page.
    expect(view).toMatch(/api\.absorptionSymbol\(symbol\.value/)
    expect(view).toMatch(/const flowMatrix = computed\(\(\) =>[\s\S]*?\.matrix \?\? null\)/)
  })

  it('keeps the order-flow poll behind the same activation gate as every other clock', () => {
    // Lazy activation is the page's whole contract; a new resource that
    // fetches on mount would break it silently.
    const block = view.slice(view.indexOf('const absorptionRes'))
    const decl = block.slice(0, block.indexOf('\n)'))
    expect(decl).toMatch(/immediate:\s*false/)
    expect(decl).toMatch(/enabled:\s*\(\)\s*=>\s*activated\.value/)
    expect(view).toMatch(/void absorptionRes\.refresh\(\)/)
  })

  it('polls order flow slowly — it is a trailing-window statistic, not a tick', () => {
    const block = view.slice(view.indexOf('const absorptionRes'))
    expect(block.slice(0, block.indexOf('\n)'))).toMatch(/intervalMs:\s*120_000/)
  })

  it('refetches order flow when the symbol changes, like every other resource', () => {
    const clears = view.match(/void absorptionRes\.refresh\(\{ clear: true \}\)/g) ?? []
    // applySymbol() and the ?symbol= route watcher.
    expect(clears.length).toBe(2)
  })

  it('builds one ladder from gamma, volume, order flow, the kernel and the vol surface', () => {
    expect(view).toMatch(/buildLevelLadder\(\{/)
    const call = view.slice(view.indexOf('return buildLevelLadder({'))
    expect(call).toMatch(/matrix: flowMatrix\.value/)
    expect(call).toMatch(/callWall: regimeRead\.value\.callWall/)
    expect(call).toMatch(/mean: pt\?\.nw_mean/)
    expect(call).toMatch(/vwap: latestVwap\.value/)
  })

  it('withholds touch probabilities rather than assuming a volatility', () => {
    // levelHorizon returns null without an ATM IV, and LevelMap hides the
    // whole probability lane when its horizon label is null — an unlabelled
    // probability is worse than none.
    expect(view).toMatch(
      /if \(sigma == null \|\| !Number\.isFinite\(sigma\) \|\| sigma <= 0\) return null/,
    )
    expect(view).toMatch(/:horizon-label="levelHorizon\?\.label \?\? null"/)
  })

  it('states every probability over an explicit horizon', () => {
    // A 0DTE read uses the remaining session on the trading clock; anything
    // longer converts calendar DTE to trading days rather than mixing clocks.
    expect(view).toMatch(/sessionYears\(sessionFractionRemaining\.value\)/)
    expect(view).toMatch(/TRADING_DAYS_PER_CALENDAR_DAY = 252 \/ 365/)
    expect(view).toMatch(/label: 'rest of session'/)
  })

  it('derives the mean target from three independent anchors, not from spot', () => {
    const call = view.slice(view.indexOf('return fairValueTarget({'))
    expect(call).toMatch(/poc: m\?\.poc/)
    expect(call).toMatch(/vwap: latestVwap\.value/)
    expect(call).toMatch(/kernelMean: latestStatePoint\.value\?\.nw_mean/)
    expect(call).toMatch(/halfLifeBars: latestStatePoint\.value\?\.ou_half_life/)
  })

  it('anchors VWAP on the most recent anchor, not the window-wide one', () => {
    // A VWAP still carrying months of pre-event volume is not the mean
    // today's tape reverts to.
    expect(view).toMatch(
      /anchors\.reduce\(\(a, b\) => \(b\.anchor_index > a\.anchor_index \? b : a\)\)/,
    )
  })

  it('names the missing lens instead of scoring a level as if it were confirmed', () => {
    expect(view).toMatch(/ORDER FLOW UNAVAILABLE/)
    expect(view).toMatch(/No mean target/)
    expect(view).toMatch(/Touch probabilities are withheld/)
  })

  it('renders the map above the analytics grid, where the read is acted on', () => {
    const mapIdx = view.indexOf('<LevelMap')
    const heroIdx = view.indexOf('<!-- 2. Hero 2-Column Analytics Grid')
    expect(mapIdx).toBeGreaterThan(-1)
    expect(heroIdx).toBeGreaterThan(-1)
    expect(mapIdx).toBeLessThan(heroIdx)
  })

  it('never prints the conviction composite as a percentage', () => {
    // It is a ranking aid built from confluence + zone strength + touches +
    // volume share. A % sign would read as a probability, which it is not.
    const map = source('components/LevelMap.vue')
    expect(map).toMatch(/conviction \$\{l\.conviction\}/)
    expect(map).toMatch(/It ranks levels; it is not a probability\./)
  })
})

describe('LevelMap component', () => {
  const map = source('components/LevelMap.vue')

  it('renders through ECharts rather than a hand-rolled axis and collision pass', () => {
    // The hand-rolled versions of these were what read as broken: occluding
    // labels, no zoom, no tooltip, no hit-testing.
    expect(map).toMatch(/from 'echarts\/core'/)
    expect(map).toMatch(/echarts\.use\(\[/)
    expect(map).toMatch(/echarts\.init\(host/)
  })

  it('imports only the ECharts pieces it draws, not the full bundle', () => {
    expect(map).toMatch(/from 'echarts\/charts'/)
    expect(map).toMatch(/from 'echarts\/renderers'/)
    expect(map).not.toMatch(/from 'echarts'\s*$/m)
  })

  it('lets ECharts resolve label occlusion instead of nudging text by hand', () => {
    expect(map).toMatch(/labelLayout: \{ moveOverlap: 'shiftY'/)
  })

  it('puts the price on every label so a shifted one cannot be misread', () => {
    // This is what makes moveOverlap safe: the label states its own price,
    // so it stays unambiguous even when drawn off its rule.
    expect(map).toMatch(/\$\{l\.label\}\s+\$\{num\(l\.price, 2\)\}/)
  })

  it('reads colours from design tokens at runtime rather than hardcoding them', () => {
    expect(map).toMatch(/getComputedStyle\(el\)/)
    expect(map).toMatch(/cs\.getPropertyValue\(`--\$\{key\}`\)/)
  })

  it('shares one price axis across the volume and level grids', () => {
    expect(map).toMatch(/grid: \[/)
    expect(map).toMatch(/gridIndex: 0/)
    expect(map).toMatch(/gridIndex: 1/)
    expect(map).toMatch(/min: yLo/)
    expect(map).toMatch(/max: yHi/)
  })

  it('frames on the median level distance so one far zone cannot squash the cluster', () => {
    // The readability bug this default exists to prevent: a swing zone 11%
    // away pushed the call wall, both expected-move bands, the put wall and
    // spot into the top eighth of the frame.
    expect(map).toMatch(/const med = dists\.length \? median\(dists\) : 0/)
    expect(map).toMatch(/Math\.max\(med \* 1\.6, 3 \* emHalf, spot \* 0\.008\)/)
  })

  it('lets the operator widen the frame rather than deciding for them', () => {
    expect(map).toMatch(/type ZoomMode = 'near' \| 'auto' \| 'wide'/)
    expect(map).toMatch(/const zoom = ref<ZoomMode>\('auto'\)/)
    expect(map).toMatch(/class="lm-zoom-chip font-mono"/)
    expect(map).toMatch(/dataZoom: \[\{ type: 'inside'/)
  })

  it('splits the volume histogram into buy and sell rather than one bar', () => {
    expect(map).toMatch(/fill: t\.call/)
    expect(map).toMatch(/fill: t\.put/)
    expect(map).toMatch(/buy \+ sell/)
  })

  it('shows touch and terminal probability together so rejection is visible', () => {
    expect(map).toMatch(/api\.coord\(\[touch, price\]\)/)
    expect(map).toMatch(/api\.coord\(\[terminal, price\]\)/)
  })

  it('names the levels the frame dropped, not just how many', () => {
    // A bare count says a level exists somewhere and nothing about whether
    // it matters; the nearest one each way is what changes a decision.
    expect(map).toMatch(/const offFrame = computed/)
    expect(map).toMatch(/offFrame\.above\[0\]\.label/)
    expect(map).toMatch(/offFrame\.below\[0\]\.label/)
    expect(map).toMatch(/Press WIDE to include them/)
  })

  it('draws nothing at all rather than a partial map without spot or levels', () => {
    expect(map).toMatch(
      /const empty = computed\(\(\) => !props\.levels\.length \|\| !\(props\.spot && props\.spot > 0\)\)/,
    )
  })

  it('disposes the chart and its observer on unmount', () => {
    // A leaked ECharts instance keeps a canvas and a ResizeObserver alive on
    // every symbol change.
    expect(map).toMatch(/onBeforeUnmount\(\(\) => \{[\s\S]*?chart\?\.dispose\(\)/)
    expect(map).toMatch(/ro\?\.disconnect\(\)/)
  })

  it('carries no em dash in any rendered copy', () => {
    const tmpl = map.slice(map.indexOf('<template>'), map.indexOf('<style scoped>'))
    expect(tmpl).not.toContain('\u2014')
  })
})
