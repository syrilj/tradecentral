/**
 * One level ladder, built from every lens that has an opinion on price.
 *
 * WHAT WAS MISSING
 * /regime derived its levels from dealer gamma alone — call wall, put wall,
 * flip, pin — and drew them as a row of pills. Three things followed from that:
 *
 *   1. No level carried a probability, so a wall 0.3% away and a wall 4% away
 *      read identically.
 *   2. Nothing in the page looked at where volume actually traded. Dealer
 *      gamma says where hedging flow will fire; it says nothing about the
 *      prices real size has already changed hands at, which is what makes a
 *      level hold when it is tested.
 *   3. Order flow was absent entirely. The backend has measured signed volume,
 *      wick absorption, touch and rejection counts per price bin on every
 *      /api/absorption call for months (daily_plays/absorption.py); the regime
 *      page never read a byte of it.
 *
 * This module merges the three families onto one price axis:
 *   · gamma      — call/put wall, flip, pin (dealer positioning)
 *   · volume     — POC, value-area edges (where business got done)
 *   · orderflow  — scored absorption zones (where it got DEFENDED)
 *   · kernel     — causal NW mean, anchored VWAP (statistical equilibrium)
 *   · vol        — expected-move bands (what the options market pays for)
 *
 * A price named by several lenses is not a stronger version of the same claim
 * — it is independent confirmation, and that is what `conviction` scores.
 */
import type { AbsorptionMatrix, AbsorptionMatrixBin } from '@/api'
import { levelProbability, type LevelProbability } from '@/levelProbability'

export type Lens = 'gamma' | 'volume' | 'orderflow' | 'kernel' | 'vol'

export interface LevelSource {
  lens: Lens
  label: string
  price: number
}

/**
 * What the tape did at this price, from the order-flow matrix bin containing
 * it. Every field is measured over the matrix's trailing window — none of it
 * is a forecast.
 */
export interface FlowEvidence {
  /** Net signed volume in the bin, as a signed fraction of the window's
   *  largest |delta| bin. Positive = net buying was absorbed here. */
  deltaFrac: number
  /** buy / (buy + sell) volume in the bin. 0.5 = balanced. */
  buyShare: number
  /** Bin volume as a fraction of the heaviest bin. 1 = this IS the POC. */
  volumeShare: number
  /** Wick-defended volume: size that pushed into this price and was refused. */
  absorption: number
  touches: number
  rejections: number
  inValueArea: boolean
  /** The matrix's own 0-10 zone strength for this bin. */
  strength: number
  /** Non-null only when a scored zone covers the price. */
  zoneTier: string | null
  zoneSide: 'support' | 'resistance' | null
}

export interface MergedLevel {
  /**
   * Cluster centroid, and therefore NOT necessarily any one lens's own price.
   * `label` names the highest-priority member, so a two-member cluster used to
   * print "Call wall $770.17" when the call wall was at $770.00 and the flip
   * at $770.33. Consumers rendering a merged level must show `members` too,
   * or the operator hangs an order on a price no lens actually named.
   */
  price: number
  /** Primary label — the highest-priority lens naming this price. */
  label: string
  /** Every lens in the cluster with the price it actually named. */
  members: Array<{ label: string; price: number; lens: Lens }>
  /** Width of the cluster in dollars (0 for a single-member level). */
  spread: number
  lenses: Lens[]
  sources: LevelSource[]
  role: 'support' | 'resistance'
  /** Signed % from spot: positive above, negative below. */
  distancePct: number
  /** |distance| in 1-day expected moves, when an EM is measurable. */
  emMultiple: number | null
  prob: LevelProbability | null
  flow: FlowEvidence | null
  /** 0-100 heuristic composite. See `scoreConviction` for the exact mix —
   *  it is a ranking aid, never a probability, and the UI must not print it
   *  with a % sign. */
  conviction: number
  /** Plain-language reasons behind the score, in descending contribution. */
  evidence: string[]
}

/** Which lens gets to name a merged level, most structural first. */
const LENS_PRIORITY: Lens[] = ['gamma', 'orderflow', 'volume', 'kernel', 'vol']

function lensRank(lens: Lens): number {
  const i = LENS_PRIORITY.indexOf(lens)
  return i < 0 ? LENS_PRIORITY.length : i
}

/** The matrix bin containing `price`, or null when it falls outside the
 *  window the matrix was built over (a level far from where price has
 *  recently traded genuinely has no flow evidence — say so, don't guess). */
export function binAt(matrix: AbsorptionMatrix | null, price: number): AbsorptionMatrixBin | null {
  if (!matrix?.available || !Number.isFinite(price)) return null
  for (const bin of matrix.bins) {
    if (price >= bin.low && price < bin.high) return bin
  }
  // Right-inclusive on the top bin, matching how the builder assigns the high.
  const last = matrix.bins[matrix.bins.length - 1]
  if (last && price >= last.low && price <= last.high) return last
  return null
}

export function flowAt(matrix: AbsorptionMatrix | null, price: number): FlowEvidence | null {
  const bin = binAt(matrix, price)
  if (!bin || !matrix) return null
  const peak = matrix.bins.reduce((m, b) => Math.max(m, b.total), 0)
  const traded = bin.buy + bin.sell
  const zone = matrix.zones.find((z) => price >= z.low && price <= z.high) ?? null
  return {
    // delta_frac ships unsigned magnitude; the sign lives on `delta`.
    deltaFrac: bin.delta < 0 ? -bin.delta_frac : bin.delta_frac,
    buyShare: traded > 0 ? bin.buy / traded : 0.5,
    volumeShare: peak > 0 ? bin.total / peak : 0,
    absorption: bin.absorption,
    touches: bin.touches,
    rejections: bin.rejections,
    inValueArea: bin.in_value_area,
    strength: bin.strength,
    zoneTier: zone?.tier ?? null,
    zoneSide: zone ? (zone.side === 'support' ? 'support' : 'resistance') : null,
  }
}

/**
 * 0-100 ranking composite. Four independent components, fixed weights, and a
 * missing component scores zero rather than being renormalized away — a level
 * only dealer gamma knows about SHOULD rank below one that gamma, volume and
 * the tape all name, and hiding that behind renormalization is exactly the
 * kind of flattery that gets a stop hung on nothing.
 *
 *   confluence  35 — independent lenses naming the price (2 lenses = 60% of it)
 *   flow zone   30 — the matrix's own 0-10 absorption/volume zone strength
 *   defence     20 — touches and rejections: was it tested, did it hold
 *   volume      15 — share of the window's heaviest bin
 */
function scoreConviction(
  lenses: Lens[],
  flow: FlowEvidence | null,
): { score: number; evidence: string[] } {
  const evidence: string[] = []
  const confluence = Math.min(1, (lenses.length - 1) / 2) * 35
  if (lenses.length > 1) {
    evidence.push(`${lenses.length} independent lenses name this price`)
  }
  let zone = 0
  let defence = 0
  let volume = 0
  if (flow) {
    zone = Math.min(1, flow.strength / 10) * 30
    if (flow.zoneTier)
      evidence.push(`${flow.zoneTier} order-flow zone (${flow.strength.toFixed(1)}/10)`)
    const touchTerm = Math.min(1, flow.touches / 14)
    const rejTerm = Math.min(1, flow.rejections / 4)
    defence = (touchTerm * 0.6 + rejTerm * 0.4) * 20
    if (flow.rejections > 0) {
      evidence.push(
        `${flow.rejections} wick rejection${flow.rejections === 1 ? '' : 's'} off this price`,
      )
    } else if (flow.touches > 0) {
      evidence.push(`tested ${flow.touches}x, no rejection wick`)
    }
    volume = Math.min(1, flow.volumeShare) * 15
    if (flow.volumeShare >= 0.6) {
      evidence.push(`heavy volume shelf (${Math.round(flow.volumeShare * 100)}% of POC)`)
    }
    if (Math.abs(flow.deltaFrac) >= 0.35) {
      evidence.push(
        flow.deltaFrac > 0
          ? 'net buying absorbed here, supportive'
          : 'net selling absorbed here, supply overhead',
      )
    }
  } else {
    evidence.push('no order-flow coverage at this price')
  }
  return { score: Math.round(confluence + zone + defence + volume), evidence }
}

export interface LadderInput {
  spot: number
  /** Annualized ATM IV as a decimal, for the probabilities. */
  sigma: number | null
  /** Year fraction the probabilities are stated over. */
  tYears: number | null
  /** 1-day expected move in dollars, for the EM-multiple readout. */
  em1dDollars: number | null
  matrix: AbsorptionMatrix | null
  gamma: {
    callWall: number | null
    putWall: number | null
    zeroGamma: number | null
    pinStrike: number | null
  }
  kernel: {
    mean: number | null
    upper: number | null
    lower: number | null
    vwap: number | null
  }
  vol: { emHigh: number | null; emLow: number | null }
}

function collectSources(input: LadderInput): LevelSource[] {
  const out: LevelSource[] = []
  const push = (lens: Lens, label: string, price: number | null | undefined) => {
    if (price != null && Number.isFinite(price) && price > 0) out.push({ lens, label, price })
  }
  push('gamma', 'Call wall', input.gamma.callWall)
  push('gamma', 'Put wall', input.gamma.putWall)
  push('gamma', 'Gamma flip', input.gamma.zeroGamma)
  push('gamma', 'Pin', input.gamma.pinStrike)
  push('volume', 'POC', input.matrix?.poc ?? null)
  push('volume', 'Value-area high', input.matrix?.vah ?? null)
  push('volume', 'Value-area low', input.matrix?.val ?? null)
  for (const zone of input.matrix?.zones ?? []) {
    push('orderflow', `${zone.tier} ${zone.side}`, zone.mid)
  }
  push('kernel', 'Kernel mean m(t)', input.kernel.mean)
  push('kernel', 'Anchored VWAP', input.kernel.vwap)
  push('kernel', 'Upper envelope', input.kernel.upper)
  push('kernel', 'Lower envelope', input.kernel.lower)
  push('vol', '+1D expected move', input.vol.emHigh)
  push('vol', '-1D expected move', input.vol.emLow)
  return out
}

/**
 * Merge tolerance: 0.15% of spot, widened to half a matrix bin so two lenses
 * inside one order-flow bin are never drawn as two levels the operator has to
 * reconcile by eye.
 */
function mergeTolerance(spot: number, matrix: AbsorptionMatrix | null): number {
  const pct = spot * 0.0015
  const bins = matrix?.bins ?? []
  const binW = bins.length ? (bins[0].high - bins[0].low) / 2 : 0
  return Math.max(pct, binW)
}

export function buildLevelLadder(input: LadderInput): MergedLevel[] {
  const { spot } = input
  if (!Number.isFinite(spot) || spot <= 0) return []
  const sources = collectSources(input).sort((a, b) => a.price - b.price)
  if (!sources.length) return []

  const tol = mergeTolerance(spot, input.matrix)
  const clusters: LevelSource[][] = []
  for (const src of sources) {
    const open = clusters[clusters.length - 1]
    if (open && src.price - open[0].price <= tol) open.push(src)
    else clusters.push([src])
  }

  const levels = clusters.map((group): MergedLevel => {
    // Volume-weight-free mean: every lens is one vote on the price, and a
    // cluster spans at most `tol`, so the mean cannot drift anywhere the
    // members are not.
    const price = group.reduce((s, g) => s + g.price, 0) / group.length
    const lenses = Array.from(new Set(group.map((g) => g.lens)))
    const primary = [...group].sort((a, b) => lensRank(a.lens) - lensRank(b.lens))[0]
    const flow = flowAt(input.matrix, price)
    const { score, evidence } = scoreConviction(lenses, flow)
    const prob =
      input.sigma != null && input.tYears != null
        ? levelProbability({ spot, level: price, sigma: input.sigma, tYears: input.tYears })
        : null
    const sortedMembers = [...group].sort((a, b) => a.price - b.price)
    return {
      price,
      label: group.length > 1 ? `${primary.label} +${group.length - 1}` : primary.label,
      members: sortedMembers.map((g) => ({ label: g.label, price: g.price, lens: g.lens })),
      spread: sortedMembers[sortedMembers.length - 1].price - sortedMembers[0].price,
      lenses,
      sources: group,
      role: price >= spot ? 'resistance' : 'support',
      distancePct: ((price - spot) / spot) * 100,
      emMultiple:
        input.em1dDollars != null && input.em1dDollars > 0
          ? Math.abs(price - spot) / input.em1dDollars
          : null,
      prob,
      flow,
      conviction: score,
      evidence,
    }
  })

  return levels.sort((a, b) => b.price - a.price)
}

/* -------------------------------------------------------------------------
 * Where price is trying to go
 * ---------------------------------------------------------------------- */

export interface FairValue {
  /** Composite equilibrium price — the median of the anchors below. */
  target: number
  anchors: Array<{ label: string; price: number }>
  /** Widest anchor disagreement as a % of spot. Small = the lenses concur. */
  spreadPct: number
  /** The anchors' full range. When they disagree this is the honest answer;
   *  `target` is only a point estimate inside it. */
  zone: { low: number; high: number }
  /**
   * True when the anchors are too far apart for a single price to mean
   * anything — the spread exceeds two 1-day expected moves (or 2% of spot when
   * no EM is measurable). The caller must lead with `zone`, not `target`:
   * "pull DOWN to 748.33" off anchors spanning 680 to 768 is a made-up
   * precision, and it is the reading an operator will size against.
   */
  dispersed: boolean
  /** Signed % from spot to the target. */
  distancePct: number
  /** Which way the pull points. 'at' inside a quarter of an expected move. */
  direction: 'up' | 'down' | 'at'
  /** |distance| in 1-day expected moves — the honest unit for "how far". */
  emMultiple: number | null
  /** True when spot sits between the value-area edges: price is ALREADY in
   *  balance and the pull below is weak by construction. */
  insideValueArea: boolean | null
  /** OU half-life at the latest bar, in bars of whatever series produced it. */
  halfLifeBars: number | null
  /** 'strong' once the gap exceeds a 1-day expected move. */
  pull: 'strong' | 'moderate' | 'weak'
}

export interface FairValueInput {
  spot: number
  poc: number | null
  vwap: number | null
  kernelMean: number | null
  valueAreaLow: number | null
  valueAreaHigh: number | null
  halfLifeBars: number | null
  em1dDollars: number | null
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b)
  const mid = s.length >> 1
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}

/**
 * The mean price is trying to revert to, from three independent estimates of
 * equilibrium: the volume point of control, anchored VWAP, and the causal
 * kernel mean.
 *
 * The MEDIAN rather than the average, because these disagree in exactly the
 * situation where the average is worst: a trending tape drags VWAP behind the
 * kernel mean while POC stays pinned at an old shelf, and the average of the
 * three lands at a price no lens actually named. The median is one of the
 * anchors (or the midpoint of the middle two), and `spreadPct` reports the
 * disagreement instead of burying it.
 */
export function fairValueTarget(input: FairValueInput): FairValue | null {
  const { spot } = input
  if (!Number.isFinite(spot) || spot <= 0) return null
  const anchors: Array<{ label: string; price: number }> = []
  const add = (label: string, price: number | null) => {
    if (price != null && Number.isFinite(price) && price > 0) anchors.push({ label, price })
  }
  add('Volume POC', input.poc)
  add('Anchored VWAP', input.vwap)
  add('Kernel mean m(t)', input.kernelMean)
  if (!anchors.length) return null

  const prices = anchors.map((a) => a.price)
  const target = median(prices)
  const low = Math.min(...prices)
  const high = Math.max(...prices)
  const spreadDollars = high - low
  const spreadPct = (spreadDollars / spot) * 100
  const dispersed =
    input.em1dDollars != null && input.em1dDollars > 0
      ? spreadDollars > 2 * input.em1dDollars
      : spreadPct > 2
  const distancePct = ((target - spot) / spot) * 100
  const emMultiple =
    input.em1dDollars != null && input.em1dDollars > 0
      ? Math.abs(target - spot) / input.em1dDollars
      : null

  const insideValueArea =
    input.valueAreaLow != null && input.valueAreaHigh != null
      ? spot >= input.valueAreaLow && spot <= input.valueAreaHigh
      : null

  // 'at' is defined on the expected-move scale when one exists, and falls back
  // to a fixed 10bp band when it does not — a fixed % band would call a 0.2%
  // gap "at the mean" on a 60-vol name and "a mile away" on a 6-vol one.
  const atThreshold = emMultiple != null ? 0.25 : 0.1
  const magnitude = emMultiple ?? Math.abs(distancePct)
  const direction: FairValue['direction'] =
    magnitude < atThreshold ? 'at' : distancePct > 0 ? 'up' : 'down'
  const pull: FairValue['pull'] =
    emMultiple != null
      ? emMultiple >= 1
        ? 'strong'
        : emMultiple >= 0.4
          ? 'moderate'
          : 'weak'
      : Math.abs(distancePct) >= 1
        ? 'strong'
        : Math.abs(distancePct) >= 0.4
          ? 'moderate'
          : 'weak'

  return {
    target,
    anchors,
    spreadPct,
    zone: { low, high },
    dispersed,
    distancePct,
    direction,
    emMultiple,
    insideValueArea,
    halfLifeBars: input.halfLifeBars,
    pull,
  }
}

/* -------------------------------------------------------------------------
 * Order-flow read
 * ---------------------------------------------------------------------- */

export interface FlowRead {
  regime: string
  score: number
  /** Which side of spot absorption is stacking on. */
  absorptionSide: string
  buyShare: number
  cvdBias: number
  headline: string
  detail: string
}

/**
 * The matrix's pressure block turned into a sentence.
 *
 * Kept separate from the gamma verdict on purpose: dealer gamma is positioning
 * and order flow is behaviour, and when they disagree that disagreement is the
 * signal. Merging them into one score would hide it.
 */
export function orderFlowRead(matrix: AbsorptionMatrix | null): FlowRead | null {
  const p = matrix?.pressure
  if (!matrix?.available || !p) return null
  const buyPct = Math.round(p.buy_share * 100)
  const headline =
    p.regime === 'ACCUM'
      ? 'Accumulation: buyers are lifting and being absorbed on dips'
      : p.regime === 'DISTRIB'
        ? 'Distribution: sellers are hitting and rallies are being absorbed'
        : 'Balanced: neither side is winning the tape'
  const sideTxt =
    p.absorption_side === 'SUPPORT'
      ? 'Absorption stacks BELOW spot: passive size is defending declines.'
      : p.absorption_side === 'RESISTANCE'
        ? 'Absorption stacks ABOVE spot: passive size is capping rallies.'
        : 'Absorption is even on both sides of spot.'
  return {
    regime: p.regime,
    score: p.score,
    absorptionSide: p.absorption_side,
    buyShare: p.buy_share,
    cvdBias: p.cvd_bias,
    headline,
    detail: `${buyPct}% of window volume traded on up-bars, cumulative delta bias ${p.cvd_bias >= 0 ? '+' : ''}${(p.cvd_bias * 100).toFixed(0)}%. ${sideTxt}`,
  }
}
