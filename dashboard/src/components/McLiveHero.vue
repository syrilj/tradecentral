<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * Live Monte Carlo hero — the landing page's opening instrument.
 *
 * Geometric-Brownian-Motion paths are drawn one batch per animation frame
 * while the empirical terminal histogram accumulates beside its closed-form
 * lognormal density, so model-vs-simulation convergence is something you
 * watch rather than are told about. Deterministic seeds keep renders stable.
 *
 * Structural anatomy only: S0=100, σ and T labelled on the figure. No market
 * data, no invented quotes — live prints appear after operator sign-in.
 */

interface Props {
  /** Initial spot — structural constant, not a market quote. */
  s0?: number
  sigma?: number
  /** Time to expiry in years. */
  maturity?: number
  mu?: number
  r?: number
  q?: number
  steps?: number
  totalPaths?: number
  seed?: number
}

const props = withDefaults(defineProps<Props>(), {
  s0: 100,
  sigma: 0.3,
  maturity: 0.25,
  mu: 0.08,
  r: 0.05,
  q: 0,
  steps: 64,
  totalPaths: 140,
  seed: 7,
})

const containerRef = ref<HTMLDivElement | null>(null)
const pathCount = ref(0)

/* Palette is read at runtime from the inherited design tokens (canvas needs
   resolved colour strings, not var()). The landing page remaps --phosphor,
   --ink, --grid, and friends inside .landing-page, and custom properties
   inherit — so reading them off the container keeps this figure on-palette
   without hardcoding literals. Translucency is applied through the context's
   globalAlpha rather than by synthesising colour strings. */
interface Palette {
  mint: string
  ink: string
  inkDim: string
  grid: string
  rule: string
}
let pal: Palette = { mint: '', ink: '', inkDim: '', grid: '', rule: '' }

function readPalette(): boolean {
  const el = containerRef.value
  if (!el) return false
  const cs = getComputedStyle(el)
  const pick = (name: string): string => cs.getPropertyValue(name).trim()
  pal = {
    mint: pick('--phosphor'),
    ink: pick('--ink'),
    inkDim: pick('--ink-dim'),
    grid: pick('--grid'),
    rule: pick('--rule-hi'),
  }
  return Boolean(pal.mint && pal.ink && pal.inkDim)
}

/** Set the active stroke colour at a given opacity. */
function strokeAt(color: string, alpha: number): void {
  if (!ctx) return
  ctx.globalAlpha = alpha
  ctx.strokeStyle = color
}

/** Set the active fill colour at a given opacity. */
function fillAt(color: string, alpha: number): void {
  if (!ctx) return
  ctx.globalAlpha = alpha
  ctx.fillStyle = color
}

/** Reset opacity to fully opaque after translucent drawing. */
function opaque(): void {
  if (ctx) ctx.globalAlpha = 1
}

let ctx: CanvasRenderingContext2D | null = null
let resizeObserver: ResizeObserver | null = null
let animFrameId = 0
let disposed = false
let hidden = false

/* Precomputed simulation state */
let rawLog: number[][] = []
let terminals: number[] = []
let lo = -1
let hi = 1
let counts: number[] = []
const N_BINS = 26

function simulate(seed: number): void {
  // Local mulberry32 + Box-Muller (deterministic anatomy)
  let a = seed | 0
  const rand = (): number => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
  const gauss = (): number => {
    let u = 0
    let v = 0
    while (u === 0) u = rand()
    while (v === 0) v = rand()
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
  }

  const dt = props.maturity / props.steps
  const drift = (props.mu - 0.5 * props.sigma * props.sigma) * dt
  const diffusion = props.sigma * Math.sqrt(dt)

  rawLog = []
  lo = Infinity
  hi = -Infinity
  for (let p = 0; p < props.totalPaths; p++) {
    const row: number[] = [0]
    for (let i = 1; i <= props.steps; i++) row.push(row[i - 1] + drift + diffusion * gauss())
    for (const v of row) {
      if (v < lo) lo = v
      if (v > hi) hi = v
    }
    rawLog.push(row)
  }
  terminals = rawLog.map((row) => props.s0 * Math.exp(row[row.length - 1]))
  counts = new Array<number>(N_BINS).fill(0)
}

interface Box {
  x: number
  y: number
  w: number
  h: number
}

function render(shown: number): void {
  const canvas = ctx?.canvas
  if (!ctx || !canvas) return
  readPalette()
  const W = canvas.width
  const H = canvas.height
  const dpr = window.devicePixelRatio || 1
  ctx.clearRect(0, 0, W, H)
  ctx.save()
  ctx.scale(dpr, dpr)
  const w = W / dpr
  const h = H / dpr

  const padL = 10
  const padR = 10
  const padT = 34
  const padB = 26
  const plotW = w - padL - padR
  const plotH = h - padT - padB
  const splitX = padL + plotW * 0.6 // fan | distribution divider

  /* ── measurement grid ── */
  ctx.strokeStyle = pal.grid
  ctx.lineWidth = 1
  ctx.beginPath()
  for (let gy = 0; gy <= 4; gy++) {
    const y = padT + (plotH * gy) / 4
    ctx.moveTo(padL, y)
    ctx.lineTo(w - padR, y)
  }
  for (let gx = 0; gx <= 8; gx++) {
    const x = padL + (plotW * gx) / 8
    ctx.moveTo(x, padT)
    ctx.lineTo(x, h - padB)
  }
  ctx.stroke()

  /* ── fan box scales ── */
  const fanBox: Box = { x: padL, y: padT, w: splitX - padL - 14, h: plotH }
  const pad = (hi - lo) * 0.05 || 1e-6
  const yOf = (logV: number): number =>
    fanBox.y + (1 - (logV - (lo - pad)) / (hi + pad - (lo - pad))) * fanBox.h
  const xOf = (step: number): number => fanBox.x + (step / props.steps) * fanBox.w

  /* ── GBM paths, revealed up to `shown` ── */
  ctx.lineWidth = 1
  const pathAlphaBase = 0.16
  for (let p = 0; p < shown && p < rawLog.length; p++) {
    const isNewest = p === shown - 1
    if (isNewest) strokeAt(pal.inkDim, 0.9)
    else strokeAt(pal.inkDim, p % 5 === 0 ? 0.32 : pathAlphaBase)
    if (isNewest) ctx.lineWidth = 1.4
    const row = rawLog[p]
    ctx.beginPath()
    for (let i = 0; i < row.length; i++) {
      const px = xOf(i)
      const py = yOf(row[i])
      if (i === 0) ctx.moveTo(px, py)
      else ctx.lineTo(px, py)
    }
    ctx.stroke()
    if (isNewest) ctx.lineWidth = 1
  }

  /* spot anchor */
  const spotY = yOf(0)
  strokeAt(pal.rule, 0.9)
  ctx.setLineDash([3, 4])
  ctx.beginPath()
  ctx.moveTo(fanBox.x, spotY)
  ctx.lineTo(fanBox.x + fanBox.w, spotY)
  ctx.stroke()
  ctx.setLineDash([])
  opaque()

  /* terminal dots on the right edge of the fan */
  fillAt(pal.mint, 0.55)
  for (let p = 0; p < shown && p < rawLog.length; p++) {
    const ty = yOf(rawLog[p][rawLog[p].length - 1])
    ctx.fillRect(fanBox.x + fanBox.w + 2, ty - 1, 2.5, 2.5)
  }
  opaque()

  /* ── divider ── */
  ctx.strokeStyle = pal.rule
  ctx.beginPath()
  ctx.moveTo(splitX, padT - 8)
  ctx.lineTo(splitX, h - padB + 4)
  ctx.stroke()

  /* ── terminal distribution panel ── */
  const distX = splitX + 14
  const distW = w - padR - distX
  const baseY = h - padB
  const histTop = padT + plotH * 0.42

  const sigT = props.sigma * Math.sqrt(props.maturity)
  const muLog =
    Math.log(props.s0) + (props.r - props.q - 0.5 * props.sigma * props.sigma) * props.maturity
  const domainLo = Math.min(lo, -3 * sigT)
  const domainHi = Math.max(hi, 3 * sigT)
  const dxOf = (v: number): number => distX + ((v - domainLo) / (domainHi - domainLo)) * distW

  /* histogram from the first `shown` terminals (recomputed cheaply) */
  counts.fill(0)
  const binW = (domainHi - domainLo) / N_BINS
  const seen = Math.min(shown, terminals.length)
  for (let i = 0; i < seen; i++) {
    const idx = Math.min(
      Math.max(Math.floor((terminals[i]! / props.s0 - 1 - domainLo) / binW), 0),
      N_BINS - 1,
    )
    counts[idx] = (counts[idx] ?? 0) + 1
  }
  const maxCount = Math.max(...counts, 1)
  const bw = Math.max(distW / N_BINS - 1.5, 1)
  fillAt(pal.inkDim, 0.18)
  for (let b = 0; b < N_BINS; b++) {
    const c = counts[b] ?? 0
    if (!c) continue
    const bh = (c / maxCount) * (baseY - histTop)
    ctx.fillRect(dxOf(domainLo + binW * b) + 0.75, baseY - bh, bw, bh)
  }
  opaque()

  /* lognormal density over the same domain */
  const nPts = 110
  const pdf: number[] = []
  let maxPdf = 0
  for (let i = 0; i < nPts; i++) {
    const x = domainLo + ((domainHi - domainLo) * i) / (nPts - 1)
    const z = (Math.log(props.s0 * Math.exp(x)) - muLog) / sigT
    const p = (1 / (sigT * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * z * z)
    pdf.push(p)
    if (p > maxPdf) maxPdf = p
  }
  ctx.strokeStyle = pal.ink
  ctx.lineWidth = 1.6
  ctx.beginPath()
  for (let i = 0; i < nPts; i++) {
    const v = domainLo + ((domainHi - domainLo) * i) / (nPts - 1)
    const py = padT + (1 - pdf[i]! / maxPdf) * (baseY - padT)
    if (i === 0) ctx.moveTo(dxOf(v), py)
    else ctx.lineTo(dxOf(v), py)
  }
  ctx.stroke()

  /* median marker */
  const medX = dxOf(0)
  ctx.strokeStyle = pal.mint
  ctx.setLineDash([4, 4])
  ctx.beginPath()
  ctx.moveTo(medX, padT)
  ctx.lineTo(medX, baseY)
  ctx.stroke()
  ctx.setLineDash([])

  /* ±1σ ticks under the axis */
  strokeAt(pal.inkDim, 0.5)
  ctx.lineWidth = 1
  for (const off of [-sigT, sigT]) {
    const tx = dxOf(off)
    ctx.beginPath()
    ctx.moveTo(tx, baseY)
    ctx.lineTo(tx, baseY + 5)
    ctx.stroke()
  }
  opaque()
  fillAt(pal.inkDim, 0.8)
  ctx.font = '600 9px "Geist Mono Variable", ui-monospace, Menlo, monospace'
  ctx.textAlign = 'center'
  ctx.fillText('-1σ', dxOf(-sigT), baseY + 15)
  ctx.fillText('MED', medX, baseY + 15)
  ctx.fillText('+1σ', dxOf(sigT), baseY + 15)
  opaque()

  /* ── panel labels ── */
  fillAt(pal.inkDim, 0.9)
  ctx.font = '700 8px "Geist Mono Variable", ui-monospace, Menlo, monospace'
  ctx.textAlign = 'left'
  ctx.fillText('GBM PATH FAN · EXACT LOG-EULER', padL, padT - 10)
  ctx.textAlign = 'right'
  ctx.fillText(`TERMINAL DISTRIBUTION · ${seen}/${props.totalPaths}`, w - padR, padT - 10)

  /* spot label */
  ctx.textAlign = 'left'
  fillAt(pal.inkDim, 0.7)
  ctx.font = '600 8px "Geist Mono Variable", ui-monospace, Menlo, monospace'
  ctx.fillText(`S₀ ${props.s0.toFixed(0)}`, fanBox.x + 4, spotY - 5)

  /* live last-path print */
  if (shown > 0 && rawLog[shown - 1]) {
    const last = rawLog[shown - 1]![rawLog[shown - 1]!.length - 1]!
    const price = props.s0 * Math.exp(last)
    ctx.fillStyle = pal.mint
    ctx.font = '700 10px "Geist Mono Variable", ui-monospace, Menlo, monospace'
    ctx.textAlign = 'right'
    ctx.fillText(price.toFixed(2), fanBox.x + fanBox.w - 2, padT + 10)
  }

  ctx.restore()
}

/* Reveal pacing: batches per frame, hold, then resimulate with a new seed */
let currentCount = 0
let currentSeed = props.seed
let phase: 'draw' | 'hold' = 'draw'
let lastTick = 0

function loop(now: number): void {
  if (disposed || !ctx) return
  animFrameId = requestAnimationFrame(loop)
  if (hidden) return

  if (phase === 'draw') {
    if (now - lastTick < 33) return // ~30fps reveal
    lastTick = now
    currentCount = Math.min(currentCount + 3, props.totalPaths)
    pathCount.value = currentCount
    render(currentCount)
    if (currentCount >= props.totalPaths) {
      phase = 'hold'
      lastTick = now
    }
  } else if (now - lastTick > 2800) {
    currentSeed += 101
    simulate(currentSeed)
    currentCount = 0
    phase = 'draw'
    lastTick = now
  }
}

function staticRender(): void {
  currentCount = props.totalPaths
  pathCount.value = currentCount
  render(currentCount)
}

function fit(): boolean {
  const container = containerRef.value
  if (!container) return false
  const w = container.clientWidth
  const hgt = container.clientHeight
  if (!w || !hgt) return false
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const canvas = ctx?.canvas
  if (!canvas) return false
  canvas.width = Math.round(w * dpr)
  canvas.height = Math.round(hgt * dpr)
  canvas.style.width = `${w}px`
  canvas.style.height = `${hgt}px`
  return true
}

function onVisibility(): void {
  hidden = document.visibilityState !== 'visible'
}

onMounted(() => {
  const container = containerRef.value
  const canvas = container?.querySelector('canvas')
  if (!container || !canvas) return
  ctx = canvas.getContext('2d')
  if (!ctx || !readPalette()) return

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  simulate(currentSeed)

  if (!fit()) return
  if (reduced) {
    staticRender()
  } else {
    animFrameId = requestAnimationFrame(loop)
    document.addEventListener('visibilitychange', onVisibility)
  }

  resizeObserver = new ResizeObserver(() => {
    if (fit()) {
      if (reduced) staticRender()
      else render(currentCount)
    }
  })
  resizeObserver.observe(container)
})

onBeforeUnmount(() => {
  disposed = true
  cancelAnimationFrame(animFrameId)
  resizeObserver?.disconnect()
  document.removeEventListener('visibilitychange', onVisibility)
  ctx = null
})
</script>

<template>
  <div
    ref="containerRef"
    class="mc-live"
    role="img"
    aria-label="Live Monte Carlo simulation: geometric Brownian motion paths accumulating into a terminal distribution against its lognormal density. Structural model, not market data."
  >
    <canvas />
    <span class="mc-counter">{{ pathCount }}/{{ totalPaths }} paths</span>
  </div>
</template>

<style scoped>
.mc-live {
  position: relative;
  height: 100%;
  min-height: 300px;
  overflow: hidden;
}
.mc-live canvas {
  display: block;
}
.mc-counter {
  position: absolute;
  left: 12px;
  bottom: 10px;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 650;
  letter-spacing: 0.08em;
}
</style>
