<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as THREE from 'three'
import type { VolSurfacePoint } from '@/charts/landing-math'

/**
 * Interactive three.js rendering of the parametric volatility surface.
 *
 * The geometry comes from the same `volSurface` model that drives the hero's
 * SVG mesh — this component adds the third dimension: drag to orbit, idle
 * rotation, and an IV-mapped yellow→red line ramp (three needs numeric
 * colours, not CSS vars). Palette mirrors the light paper tokens: ink node
 * dots, hairline base grid, tangerine membrane wash.
 *
 * No market data: structural model only, same as the hero diagram.
 */
const props = withDefaults(
  defineProps<{
    points: VolSurfacePoint[]
    strikes: number[]
    maturities: number[]
    height?: number
  }>(),
  { height: 420 },
)

const containerRef = ref<HTMLDivElement | null>(null)
const dragging = ref(false)

let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let renderer: THREE.WebGLRenderer | null = null
let surfaceGroup: THREE.Group | null = null
let resizeObserver: ResizeObserver | null = null
let animFrameId = 0
let disposed = false

/* Orbit state — spherical angles around the surface centre */
let rotY = -0.65
let rotX = 0.42
const rotXMin = 0.08
const rotXMax = 1.15
let idleSpin = 0.0016
let pointerTiltX = 0
let pointerTiltY = 0
let dragPrev = { x: 0, y: 0 }
let reducedMotion = false

function ivColor(iv: number, ivMin: number, ivMax: number): THREE.Color {
  const t = Math.max(0, Math.min(1, (iv - ivMin) / Math.max(ivMax - ivMin, 1e-6)))
  const yellow = new THREE.Color(0xffaf01)
  const red = new THREE.Color(0xe51300)
  return yellow.lerp(red, Math.pow(t, 1.4))
}

function buildSurface() {
  if (!scene || !props.points.length) return

  const ivs = props.points.map((p) => p.iv)
  const ivMin = Math.min(...ivs)
  const ivMax = Math.max(...ivs)

  const kCount = props.strikes.length
  const tCount = props.maturities.length
  const halfW = 3.2
  const halfD = 2.0
  const heightScale = 1.9

  /* Grid vertex positions: x = strike axis, z = maturity axis, y = IV */
  const vertex = (ki: number, ti: number): THREE.Vector3 => {
    const pt = props.points[ti * kCount + ki]
    return new THREE.Vector3(
      (ki / (kCount - 1)) * 2 * halfW - halfW,
      ((pt.iv - ivMin) / Math.max(ivMax - ivMin, 1e-6)) * heightScale,
      (ti / (tCount - 1)) * 2 * halfD - halfD,
    )
  }

  surfaceGroup = new THREE.Group()

  /* Wireframe: one Line per maturity row and per strike column, IV-mapped colour */
  for (let ti = 0; ti < tCount; ti++) {
    const pts: THREE.Vector3[] = []
    for (let ki = 0; ki < kCount; ki++) pts.push(vertex(ki, ti))
    const geom = new THREE.BufferGeometry().setFromPoints(pts)
    const mid = props.points[ti * kCount + Math.floor(kCount / 2)]
    surfaceGroup.add(
      new THREE.Line(geom, new THREE.LineBasicMaterial({ color: ivColor(mid.iv, ivMin, ivMax) })),
    )
  }
  for (let ki = 0; ki < kCount; ki++) {
    const pts: THREE.Vector3[] = []
    for (let ti = 0; ti < tCount; ti++) pts.push(vertex(ki, ti))
    const geom = new THREE.BufferGeometry().setFromPoints(pts)
    const mid = props.points[Math.floor(tCount / 2) * kCount + ki]
    surfaceGroup.add(
      new THREE.Line(geom, new THREE.LineBasicMaterial({ color: ivColor(mid.iv, ivMin, ivMax) })),
    )
  }

  /* Translucent membrane under the wire — mint wash, both sides */
  const membranePos: number[] = []
  const membraneIdx: number[] = []
  for (let ti = 0; ti < tCount; ti++) {
    for (let ki = 0; ki < kCount; ki++) {
      const v = vertex(ki, ti)
      membranePos.push(v.x, v.y, v.z)
    }
  }
  for (let ti = 0; ti < tCount - 1; ti++) {
    for (let ki = 0; ki < kCount - 1; ki++) {
      const a = ti * kCount + ki
      const b = a + 1
      const c = a + kCount
      const d = c + 1
      membraneIdx.push(a, c, b, b, c, d)
    }
  }
  const membraneGeom = new THREE.BufferGeometry()
  membraneGeom.setAttribute('position', new THREE.Float32BufferAttribute(membranePos, 3))
  membraneGeom.setIndex(membraneIdx)
  membraneGeom.computeVertexNormals()
  surfaceGroup.add(
    new THREE.Mesh(
      membraneGeom,
      new THREE.MeshBasicMaterial({
        color: 0xff8204,
        transparent: true,
        opacity: 0.05,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    ),
  )

  /* Vertex sparkles at the mesh nodes */
  for (let ti = 0; ti < tCount; ti += 2) {
    for (let ki = 0; ki < kCount; ki += 2) {
      const v = vertex(ki, ti)
      const g = new THREE.BufferGeometry().setFromPoints([v])
      surfaceGroup.add(
        new THREE.Points(
          g,
          new THREE.PointsMaterial({
            color: 0x18181b,
            size: 0.055,
            sizeAttenuation: true,
            transparent: true,
            opacity: 0.85,
          }),
        ),
      )
    }
  }

  /* Base reference grid beneath the surface */
  const baseGrid = new THREE.GridHelper(7.4, 14, 0xc9c9c4, 0xe4e3de)
  baseGrid.position.y = -0.12
  surfaceGroup.add(baseGrid)

  /* Centre the vertical travel around origin */
  surfaceGroup.position.y = -heightScale / 2
  scene.add(surfaceGroup)
}

function applyOrbit() {
  if (!surfaceGroup) return
  surfaceGroup.rotation.y = rotY + pointerTiltY
  surfaceGroup.rotation.x = Math.max(rotXMin, Math.min(rotXMax, rotX)) + pointerTiltX
}

function render() {
  if (!renderer || !camera) return
  applyOrbit()
  renderer.render(scene!, camera)
}

function loop() {
  if (disposed) return
  if (!reducedMotion && !dragging.value) rotY += idleSpin
  pointerTiltX *= 0.94
  pointerTiltY *= 0.94
  render()
  animFrameId = requestAnimationFrame(loop)
}

/* Render-on-demand when motion is reduced */
function requestStaticRender() {
  if (reducedMotion) render()
}

function onPointerDown(e: PointerEvent) {
  dragging.value = true
  dragPrev = { x: e.clientX, y: e.clientY }
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}
function onPointerMove(e: PointerEvent) {
  if (dragging.value) {
    rotY += (e.clientX - dragPrev.x) * 0.006
    rotX += (e.clientY - dragPrev.y) * 0.004
    dragPrev = { x: e.clientX, y: e.clientY }
    render()
  }
}
function onPointerUp() {
  dragging.value = false
}
function onPointerHover(e: PointerEvent) {
  if (dragging.value) return
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  pointerTiltY = ((e.clientX - rect.left) / rect.width - 0.5) * 0.12
  pointerTiltX = ((e.clientY - rect.top) / rect.height - 0.5) * 0.06
  requestStaticRender()
}
function onPointerLeave() {
  pointerTiltX = 0
  pointerTiltY = 0
  requestStaticRender()
}

function disposeObject3D(obj: THREE.Object3D) {
  obj.traverse((child) => {
    if (
      child instanceof THREE.Line ||
      child instanceof THREE.Mesh ||
      child instanceof THREE.Points
    ) {
      child.geometry?.dispose()
      const mat = child.material as THREE.Material | THREE.Material[] | undefined
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose())
      else mat?.dispose()
    }
  })
}

onMounted(() => {
  const container = containerRef.value
  if (!container) return

  reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  const width = container.clientWidth || 600
  scene = new THREE.Scene()
  camera = new THREE.PerspectiveCamera(38, width / props.height, 0.1, 100)
  camera.position.set(0, 1.6, 8.6)
  camera.lookAt(0, 0, 0)

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
  renderer.setSize(width, props.height)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  container.innerHTML = ''
  container.appendChild(renderer.domElement)

  buildSurface()
  render()

  resizeObserver = new ResizeObserver(() => {
    const w = container.clientWidth
    if (!renderer || !camera || w === 0) return
    camera.aspect = w / props.height
    camera.updateProjectionMatrix()
    renderer.setSize(w, props.height)
    requestStaticRender()
  })
  resizeObserver.observe(container)

  if (reducedMotion) {
    /* Still interactive — renders happen on pointer events only */
    container.addEventListener('pointermove', onPointerHover)
  } else {
    animFrameId = requestAnimationFrame(loop)
    container.addEventListener('pointermove', onPointerHover)
  }
  container.addEventListener('pointerdown', onPointerDown)
  container.addEventListener('pointermove', onPointerMove)
  container.addEventListener('pointerup', onPointerUp)
  container.addEventListener('pointerleave', onPointerLeave)
})

onBeforeUnmount(() => {
  disposed = true
  cancelAnimationFrame(animFrameId)
  if (surfaceGroup && scene) {
    disposeObject3D(surfaceGroup)
    scene.remove(surfaceGroup)
  }
  if (scene) disposeObject3D(scene)
  renderer?.dispose()
  renderer?.domElement.remove()
  resizeObserver?.disconnect()
  const container = containerRef.value
  if (container) {
    container.removeEventListener('pointerdown', onPointerDown)
    container.removeEventListener('pointermove', onPointerMove)
    container.removeEventListener('pointermove', onPointerHover)
    container.removeEventListener('pointerup', onPointerUp)
    container.removeEventListener('pointerleave', onPointerLeave)
  }
  scene = null
  camera = null
  renderer = null
  surfaceGroup = null
})
</script>

<template>
  <div
    ref="containerRef"
    class="vol-surface-canvas"
    :class="{ dragging }"
    :style="{ height: `${height}px` }"
    role="img"
    aria-label="Interactive implied volatility surface. Drag to orbit the model."
  />
</template>

<style scoped>
.vol-surface-canvas {
  position: relative;
  width: 100%;
  overflow: hidden;
  touch-action: none;
  cursor: grab;
}
.vol-surface-canvas.dragging {
  cursor: grabbing;
}
.vol-surface-canvas :deep(canvas) {
  display: block;
}
</style>
