<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { VolSurfacePoint } from '@/charts/landing-math'

/**
 * Draggable implied-volatility surface — canvas 2D, zero WebGL.
 *
 * Replaces the three.js figure on the public landing route: the same
 * parametric σ(K,T) grid, projected with a yaw/pitch isometric camera and
 * drawn as a painter-ordered wire mesh with translucent ribbons. Pointer
 * drag orbits the surface; a slow idle rotation keeps it alive while it is
 * on screen. Structural parameters only — live per-symbol surfaces appear
 * after operator sign-in.
 */

interface Props {
  points: VolSurfacePoint[]
  strikes: number[]
  maturities: number[]
}
const props = defineProps<Props>()

const containerRef = ref<HTMLDivElement | null>(null)
let ctx: CanvasRenderingContext2D | null = null
let resizeObserver: ResizeObserver | null = null
let visibilityObserver: IntersectionObserver | null = null
let rafId = 0
let disposed = false
let pageHidden = false
let frameVisible = false
let dirty = true

/* camera */
let yaw = -0.62
let pitch = 0.52
let yawVel = 0
let dragging = false
let lastPointer: { x: number; y: number } | null = null

interface Palette {
  ink: string
  inkDim: string
  inkFaint: string
  grid: string
  rule: string
  accent: string
  wash: string
  voidBg: string
  mono: string
}
let pal: Palette = {
  ink: '',
  inkDim: '',
  inkFaint: '',
  grid: '',
  rule: '',
  accent: '',
  wash: '',
  voidBg: '',
  mono: 'ui-monospace, Menlo, monospace',
}

function readPalette(): boolean {
  const el = containerRef.value
  if (!el) return false
  const cs = getComputedStyle(el)
  const pick = (name: string): string => cs.getPropertyValue(name).trim()
  pal = {
    ...pal,
    ink: pick('--ink'),
    inkDim: pick('--ink-dim'),
    inkFaint: pick('--ink-faint'),
    grid: pick('--grid'),
    rule: pick('--rule-hi'),
    accent: pick('--phosphor'),
    wash: pick('--phosphor-wash'),
    voidBg: pick('--void'),
    mono: cs.fontFamily || pal.mono,
  }
  return Boolean(pal.ink && pal.accent)
}

/* grid lookup: points arrive as maturities × strikes in row-major order */
function ivAt(K: number, T: number): number {
  const row = props.maturities.indexOf(T)
  const col = props.strikes.indexOf(K)
  const idx = row * props.strikes.length + col
  return props.points[idx]?.iv ?? 0
}

let ivMin = 0
let ivMax = 1

function normalise(): void {
  ivMin = Math.min(...props.points.map((p) => p.iv))
  ivMax = Math.max(...props.points.map((p) => p.iv))
  if (ivMax - ivMin < 1e-9) ivMax = ivMin + 1e-9
}

interface Vertex {
  x: number
  y: number
  depth: number
}

function project(
  K: number,
  T: number,
  iv: number,
  cx: number,
  cy: number,
  spanX: number,
  spanY: number,
): Vertex {
  const kx =
    (K - props.strikes[0]!) / (props.strikes[props.strikes.length - 1]! - props.strikes[0]!) - 0.5
  const tz =
    (T - props.maturities[0]!) /
      (props.maturities[props.maturities.length - 1]! - props.maturities[0]!) -
    0.5
  const yv = (iv - ivMin) / (ivMax - ivMin)
  const cosY = Math.cos(yaw)
  const sinY = Math.sin(yaw)
  const rx = kx * cosY - tz * sinY
  const rz = kx * sinY + tz * cosY
  return {
    x: cx + rx * spanX,
    y: cy + rz * spanX * Math.sin(pitch) - yv * spanY,
    depth: rz,
  }
}

function draw(): void {
  const canvas = ctx?.canvas
  if (!ctx || !canvas) return
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const w = canvas.width / dpr
  const h = canvas.height / dpr
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)

  const padT = 30
  const padB = 34
  const cx = w / 2
  const cy = padT + (h - padT - padB) / 2 + (h - padT - padB) * 0.12
  const spanX = Math.min(w * 0.62, 460)
  const spanY = (h - padT - padB) * 0.52
  const P = (K: number, T: number): Vertex => project(K, T, ivAt(K, T), cx, cy, spanX, spanY)

  /* translucent ribbons between adjacent maturities, far to near */
  const slices = [...props.maturities].sort(
    (a, b) => P(props.strikes[0]!, b).depth - P(props.strikes[0]!, a).depth,
  )
  ctx.lineWidth = 1
  for (let i = 0; i < slices.length - 1; i += 1) {
    const Tn = slices[i]!
    const Tf = slices[i + 1]!
    ctx.beginPath()
    for (let j = 0; j < props.strikes.length; j++) {
      const v = P(props.strikes[j]!, Tn)
      if (j === 0) ctx.moveTo(v.x, v.y)
      else ctx.lineTo(v.x, v.y)
    }
    for (let j = props.strikes.length - 1; j >= 0; j--) {
      const v = P(props.strikes[j]!, Tf)
      ctx.lineTo(v.x, v.y)
    }
    ctx.closePath()
    ctx.fillStyle = pal.wash
    ctx.globalAlpha = 0.5
    ctx.fill()
    ctx.globalAlpha = 1
  }

  /* mesh: constant-maturity lines across strikes, far to near */
  for (const T of slices) {
    const isShort = T === props.maturities[0]
    ctx.strokeStyle = isShort ? pal.accent : pal.inkDim
    ctx.globalAlpha = isShort ? 0.95 : 0.55
    ctx.lineWidth = isShort ? 1.6 : 1
    ctx.beginPath()
    for (let j = 0; j < props.strikes.length; j++) {
      const v = P(props.strikes[j]!, T)
      if (j === 0) ctx.moveTo(v.x, v.y)
      else ctx.lineTo(v.x, v.y)
    }
    ctx.stroke()
    /* constant-strike spine on the outer strikes closes the cage */
    if (T === slices[0] || T === slices[slices.length - 1]) {
      for (const K of [props.strikes[0]!, props.strikes[props.strikes.length - 1]!]) {
        ctx.strokeStyle = pal.inkFaint
        ctx.globalAlpha = 0.4
        ctx.lineWidth = 1
        ctx.beginPath()
        for (const T2 of slices) {
          const v = P(K, T2)
          if (T2 === slices[0]) ctx.moveTo(v.x, v.y)
          else ctx.lineTo(v.x, v.y)
        }
        ctx.stroke()
      }
    }
  }
  ctx.globalAlpha = 1

  /* vertex nodes */
  ctx.fillStyle = pal.ink
  for (const T of slices) {
    for (const K of props.strikes) {
      const v = P(K, T)
      ctx.globalAlpha = 0.35 + 0.4 * (1 - (v.depth + 0.5))
      ctx.fillRect(v.x - 1.25, v.y - 1.25, 2.5, 2.5)
    }
  }
  ctx.globalAlpha = 1

  /* labels: ATM strike on the near K edge, tenors on the near T edge */
  ctx.font = `600 8.5px ${pal.mono}`
  ctx.fillStyle = pal.inkFaint
  const Kn = props.strikes[Math.floor(props.strikes.length / 2)]!
  for (const K of [props.strikes[0]!, Kn, props.strikes[props.strikes.length - 1]!]) {
    const v = P(K, slices[0]!)
    ctx.textAlign = 'center'
    ctx.fillText(K === Kn ? `K ${K}` : String(K), v.x, v.y + 14)
  }
  const nearT = slices[0]!
  const farT = slices[slices.length - 1]!
  for (const [T, label] of [
    [nearT, `${Math.round(nearT * 12)}M`],
    [farT, `${Math.round(farT * 12)}M`],
  ] as const) {
    const v = P(props.strikes[0]!, T)
    ctx.textAlign = 'right'
    ctx.fillText(label, v.x - 6, v.y + 3)
  }
  ctx.textAlign = 'left'
  ctx.fillStyle = pal.accent
  ctx.fillText(`σ ${(((ivMin + ivMax) / 2) * 100).toFixed(0)}% MID`, 12, 16)
  ctx.fillStyle = pal.inkFaint
  ctx.fillText('σ(K,T) PARAMETRIC MESH', 12, h - 10)
}

function fit(): boolean {
  const container = containerRef.value
  const canvas = ctx?.canvas
  if (!container || !canvas) return false
  const cw = container.clientWidth
  const ch = container.clientHeight
  if (!cw || !ch) return false
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = Math.round(cw * dpr)
  canvas.height = Math.round(ch * dpr)
  canvas.style.width = `${cw}px`
  canvas.style.height = `${ch}px`
  return true
}

const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Keyboard orbit for the drag alternative (± yaw step). */
function nudge(dir: number): void {
  yaw += dir * 0.12
  draw()
}

function loop(): void {
  if (disposed) return
  rafId = requestAnimationFrame(loop)
  if (pageHidden || !frameVisible) return
  if (!dragging) {
    yaw += yawVel + (reducedMotion() ? 0 : 0.0009)
    yawVel *= 0.94
    if (Math.abs(yawVel) < 0.0004) yawVel = 0
    if (yawVel !== 0 || !reducedMotion()) dirty = true
  }
  if (dirty) {
    draw()
    dirty = false
  }
}

/* pointer orbit */
function onDown(e: PointerEvent): void {
  dragging = true
  yawVel = 0
  lastPointer = { x: e.clientX, y: e.clientY }
  ;(e.currentTarget as Element).setPointerCapture?.(e.pointerId)
}
function onMove(e: PointerEvent): void {
  if (!dragging || !lastPointer) return
  const dx = e.clientX - lastPointer.x
  const dy = e.clientY - lastPointer.y
  lastPointer = { x: e.clientX, y: e.clientY }
  yaw += dx * 0.006
  pitch = Math.min(1.15, Math.max(0.18, pitch + dy * 0.004))
  if (reducedMotion()) draw() // no rAF loop in reduced mode: paint directly
}
function onUp(): void {
  dragging = false
  lastPointer = null
}

function onVisibility(): void {
  pageHidden = document.visibilityState !== 'visible'
}

onMounted(() => {
  const container = containerRef.value
  const canvas = container?.querySelector('canvas')
  if (!container || !canvas) return
  ctx = canvas.getContext('2d')
  if (!ctx || !readPalette()) return
  normalise()
  if (!fit()) return
  draw()
  dirty = false

  if (!reducedMotion()) {
    rafId = requestAnimationFrame(loop)
    document.addEventListener('visibilitychange', onVisibility)
    visibilityObserver = new IntersectionObserver(
      (entries) => {
        frameVisible = entries[0]?.isIntersecting ?? false
        if (frameVisible) dirty = true
      },
      { threshold: 0.05 },
    )
    visibilityObserver.observe(container)
  }

  resizeObserver = new ResizeObserver(() => {
    if (fit()) draw()
  })
  resizeObserver.observe(container)
})

onBeforeUnmount(() => {
  disposed = true
  cancelAnimationFrame(rafId)
  resizeObserver?.disconnect()
  visibilityObserver?.disconnect()
  document.removeEventListener('visibilitychange', onVisibility)
  ctx = null
})
</script>

<template>
  <div
    ref="containerRef"
    class="surface-orbit"
    role="img"
    aria-label="Draggable implied volatility surface: parametric sigma across strike and maturity, drawn as an orbitable wire mesh. Structural model, not market data."
  >
    <canvas
      tabindex="0"
      @pointerdown="onDown"
      @pointermove="onMove"
      @pointerup="onUp"
      @pointercancel="onUp"
      @keydown.left.prevent="nudge(-1)"
      @keydown.right.prevent="nudge(1)"
    />
    <span class="orbit-hint">DRAG TO ORBIT</span>
  </div>
</template>

<style scoped>
.surface-orbit {
  position: relative;
  height: 100%;
  min-height: 300px;
  touch-action: none;
}
.surface-orbit canvas {
  display: block;
  width: 100%;
  height: 100%;
  cursor: grab;
}
.surface-orbit canvas:active {
  cursor: grabbing;
}
.surface-orbit canvas:focus-visible {
  outline: 2px solid var(--phosphor);
  outline-offset: -2px;
}
.orbit-hint {
  position: absolute;
  right: 10px;
  top: 8px;
  padding: 3px 8px;
  font-family: var(--font-data);
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.09em;
  color: var(--ink-faint);
  border: var(--hair) solid var(--rule-hi);
  background: var(--void);
  pointer-events: none;
}
</style>
