<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as THREE from 'three'
import AppIcon from '@/components/AppIcon.vue'

const props = withDefaults(
  defineProps<{
    height?: number
  }>(),
  {
    height: 420,
  },
)

const containerRef = ref<HTMLDivElement | null>(null)
const dragging = ref(false)
const activePreset = ref<'orbit' | 'elevation' | 'matrix'>('orbit')

// Telemetry readout state
const telemetryAzimuth = ref('-37°')
const telemetryElevation = ref('24°')
const telemetryGex = ref('+1.42B')
const telemetryRegime = ref('LONG GAMMA')

let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let renderer: THREE.WebGLRenderer | null = null
let rootGroup: THREE.Group | null = null
let ringsGroup: THREE.Group | null = null
let particlesGroup: THREE.Group | null = null

let resizeObserver: ResizeObserver | null = null
let visibilityObserver: IntersectionObserver | null = null
let animFrameId = 0
let disposed = false

// Orbit angles (spherical coordinates around center)
let rotY = -0.65
let rotX = 0.42
const rotXMin = 0.05
const rotXMax = 1.35
const idleSpin = 0.0014
let pointerTiltX = 0
let pointerTiltY = 0
let dragPrev = { x: 0, y: 0 }
let reducedMotion = false
let pageHidden = false
let frameVisible = true

// Target angles for smooth camera transitions
let targetRotY = rotY
let targetRotX = rotX

// Particle system data for signed options flow streams
interface FlowParticle {
  spline: THREE.CatmullRomCurve3
  t: number
  speed: number
  mesh: THREE.Mesh
}
const flowParticles: FlowParticle[] = []

function disposeObject3D(obj: THREE.Object3D): void {
  obj.traverse((child) => {
    if (
      child instanceof THREE.Line ||
      child instanceof THREE.Mesh ||
      child instanceof THREE.Points
    ) {
      child.geometry?.dispose()
      const mat = child.material as THREE.Material | THREE.Material[] | undefined
      if (Array.isArray(mat)) {
        mat.forEach((m) => m.dispose())
      } else {
        mat?.dispose()
      }
    }
  })
}

/**
 * Builds the 3D parametric Dealer Gamma & Volatility Topology manifold.
 * Strikes (K/Spot: 0.85 -> 1.15) x Tenors (1W -> 1Y).
 */
function buildTopology(): void {
  if (!scene) return

  rootGroup = new THREE.Group()

  const strikesCount = 17
  const tenorsCount = 13
  const halfWidth = 3.4
  const halfDepth = 2.4
  const elevationScale = 1.8

  // Gamma elevation formula:
  // Concentrated call support hill at ATM/front-month transitioning to negative gamma trough on downside skew
  function calcGexHeight(strikeIdx: number, tenorIdx: number): { y: number; gexVal: number } {
    const kNorm = strikeIdx / (strikesCount - 1) // 0..1 (0.85 to 1.15)
    const tNorm = tenorIdx / (tenorsCount - 1) // 0..1 (1W to 1Y)

    // Center around ATM (kNorm = 0.5)
    const kDev = kNorm - 0.5
    const decay = 1 / Math.sqrt(0.2 + tNorm * 1.8)

    // Positive gamma hill ATM
    const hill = Math.exp(-(kDev * kDev) / 0.035) * decay

    // Downside volatility skew / dealer hedging drag
    const putDrag = (1 - kNorm) * 0.42 * (1 - tNorm * 0.5)

    const rawGex = hill * 0.9 - putDrag
    const y = (rawGex - 0.15) * elevationScale
    return { y, gexVal: rawGex }
  }

  const gridPoints: THREE.Vector3[][] = []
  const gexValues: number[][] = []

  for (let ti = 0; ti < tenorsCount; ti++) {
    const row: THREE.Vector3[] = []
    const gRow: number[] = []
    const z = (ti / (tenorsCount - 1)) * 2 * halfDepth - halfDepth

    for (let ki = 0; ki < strikesCount; ki++) {
      const x = (ki / (strikesCount - 1)) * 2 * halfWidth - halfWidth
      const { y, gexVal } = calcGexHeight(ki, ti)
      row.push(new THREE.Vector3(x, y, z))
      gRow.push(gexVal)
    }
    gridPoints.push(row)
    gexValues.push(gRow)
  }

  // Institutional color mapper:
  // Jade Mint (0x0f8a5f) for positive gamma -> Slate (0x5e5b53) -> Electric Orange (0xff5229) for negative gamma
  function getGexColor(val: number): THREE.Color {
    const green = new THREE.Color(0x0f8a5f)
    const neutral = new THREE.Color(0x5e5b53)
    const orange = new THREE.Color(0xff5229)

    if (val >= 0.1) {
      const t = Math.min(1, (val - 0.1) / 0.6)
      return neutral.clone().lerp(green, t)
    } else {
      const t = Math.min(1, (0.1 - val) / 0.4)
      return neutral.clone().lerp(orange, t)
    }
  }

  // 1. Strike line curves (X axis)
  for (let ti = 0; ti < tenorsCount; ti++) {
    const pts = gridPoints[ti]
    const geom = new THREE.BufferGeometry().setFromPoints(pts)
    const midVal = gexValues[ti][Math.floor(strikesCount / 2)]
    const lineMat = new THREE.LineBasicMaterial({
      color: getGexColor(midVal),
      transparent: true,
      opacity: ti % 2 === 0 ? 0.85 : 0.45,
    })
    rootGroup.add(new THREE.Line(geom, lineMat))
  }

  // 2. Tenor line curves (Z axis)
  for (let ki = 0; ki < strikesCount; ki++) {
    const pts: THREE.Vector3[] = []
    for (let ti = 0; ti < tenorsCount; ti++) {
      pts.push(gridPoints[ti][ki])
    }
    const geom = new THREE.BufferGeometry().setFromPoints(pts)
    const midVal = gexValues[Math.floor(tenorsCount / 2)][ki]
    const lineMat = new THREE.LineBasicMaterial({
      color: getGexColor(midVal),
      transparent: true,
      opacity: ki % 2 === 0 ? 0.85 : 0.45,
    })
    rootGroup.add(new THREE.Line(geom, lineMat))
  }

  // 3. Translucent GEX topology membrane
  const positions: number[] = []
  const indices: number[] = []

  for (let ti = 0; ti < tenorsCount; ti++) {
    for (let ki = 0; ki < strikesCount; ki++) {
      const p = gridPoints[ti][ki]
      positions.push(p.x, p.y, p.z)
    }
  }

  for (let ti = 0; ti < tenorsCount - 1; ti++) {
    for (let ki = 0; ki < strikesCount - 1; ki++) {
      const a = ti * strikesCount + ki
      const b = a + 1
      const c = a + strikesCount
      const d = c + 1
      indices.push(a, c, b, b, c, d)
    }
  }

  const membraneGeom = new THREE.BufferGeometry()
  membraneGeom.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  membraneGeom.setIndex(indices)
  membraneGeom.computeVertexNormals()

  const membraneMat = new THREE.MeshBasicMaterial({
    color: 0x0082e6,
    transparent: true,
    opacity: 0.06,
    side: THREE.DoubleSide,
    depthWrite: false,
  })
  rootGroup.add(new THREE.Mesh(membraneGeom, membraneMat))

  // 4. Sparkle nodes at key strike intersections
  for (let ti = 0; ti < tenorsCount; ti += 3) {
    for (let ki = 0; ki < strikesCount; ki += 3) {
      const p = gridPoints[ti][ki]
      const g = new THREE.BufferGeometry().setFromPoints([p])
      const val = gexValues[ti][ki]
      const pointMat = new THREE.PointsMaterial({
        color: val >= 0.1 ? 0x0f8a5f : 0xff5229,
        size: 0.09,
        sizeAttenuation: true,
        transparent: true,
        opacity: 0.9,
      })
      rootGroup.add(new THREE.Points(g, pointMat))
    }
  }

  // 5. Zero-Gamma Flip Horizon plane
  const flipGrid = new THREE.GridHelper(7.2, 16, 0xc9c9c4, 0xe4e3de)
  flipGrid.position.y = -0.15 * elevationScale
  rootGroup.add(flipGrid)

  // 6. Horizon caliper boundary ring
  const boundaryRadius = 3.9
  const boundaryCurve = new THREE.EllipseCurve(0, 0, boundaryRadius, boundaryRadius, 0, 2 * Math.PI, false, 0)
  const boundaryPoints = boundaryCurve.getPoints(64)
  const boundaryGeom = new THREE.BufferGeometry().setFromPoints(
    boundaryPoints.map((p) => new THREE.Vector3(p.x, -0.15 * elevationScale, p.y)),
  )
  const boundaryMat = new THREE.LineDashedMaterial({
    color: 0xa8a8a2,
    dashSize: 0.2,
    gapSize: 0.15,
    transparent: true,
    opacity: 0.75,
  })
  const boundaryLine = new THREE.Line(boundaryGeom, boundaryMat)
  boundaryLine.computeLineDistances()
  rootGroup.add(boundaryLine)

  scene.add(rootGroup)
}

/**
 * Builds the 3-axis institutional research gyroscope & enclave rings.
 */
function buildEnclaveRings(): void {
  if (!scene) return

  ringsGroup = new THREE.Group()

  // Ring 1: Outer Allowlist Ring (cyan / 0x0082e6)
  const r1Geom = new THREE.BufferGeometry().setFromPoints(
    new THREE.EllipseCurve(0, 0, 4.3, 4.3, 0, Math.PI * 2, false, 0)
      .getPoints(72)
      .map((p) => new THREE.Vector3(p.x, 0, p.y)),
  )
  const r1Mat = new THREE.LineBasicMaterial({ color: 0x0082e6, transparent: true, opacity: 0.4 })
  const ring1 = new THREE.LineLoop(r1Geom, r1Mat)
  ring1.rotation.x = Math.PI * 0.15
  ringsGroup.add(ring1)

  // Ring 2: Middle Local Boundary 127.0.0.1 Ring (orange / 0xff5229)
  const r2Geom = new THREE.BufferGeometry().setFromPoints(
    new THREE.EllipseCurve(0, 0, 4.0, 4.0, 0, Math.PI * 2, false, 0)
      .getPoints(64)
      .map((p) => new THREE.Vector3(p.x, p.y, 0)),
  )
  const r2Mat = new THREE.LineBasicMaterial({ color: 0xff5229, transparent: true, opacity: 0.35 })
  const ring2 = new THREE.LineLoop(r2Geom, r2Mat)
  ring2.rotation.y = Math.PI * 0.25
  ringsGroup.add(ring2)

  // Ring 3: Inner Evidence Ledger Ring (dark slate / 0x3f3f46)
  const r3Geom = new THREE.BufferGeometry().setFromPoints(
    new THREE.EllipseCurve(0, 0, 3.7, 3.7, 0, Math.PI * 2, false, 0)
      .getPoints(54)
      .map((p) => new THREE.Vector3(0, p.x, p.y)),
  )
  const r3Mat = new THREE.LineBasicMaterial({ color: 0x3f3f46, transparent: true, opacity: 0.45 })
  const ring3 = new THREE.LineLoop(r3Geom, r3Mat)
  ring3.rotation.z = Math.PI * 0.12
  ringsGroup.add(ring3)

  scene.add(ringsGroup)
}

/**
 * Builds continuous signed options flow particle streams traveling across the manifold.
 */
function buildFlowStreams(): void {
  if (!scene) return

  particlesGroup = new THREE.Group()

  // Spline 1: Green aggressor buyer call flow
  const callPath = new THREE.CatmullRomCurve3([
    new THREE.Vector3(-2.8, -0.2, 1.8),
    new THREE.Vector3(-1.0, 0.4, 0.8),
    new THREE.Vector3(0.0, 0.9, 0.0),
    new THREE.Vector3(1.2, 0.7, -0.8),
    new THREE.Vector3(2.5, 0.2, -1.8),
  ])

  // Spline 2: Orange aggressor seller put flow
  const putPath = new THREE.CatmullRomCurve3([
    new THREE.Vector3(-2.6, 0.1, -1.6),
    new THREE.Vector3(-1.5, -0.4, -0.6),
    new THREE.Vector3(0.0, -0.2, 0.2),
    new THREE.Vector3(1.5, -0.6, 1.0),
    new THREE.Vector3(2.8, -0.8, 1.9),
  ])

  const sphereGeom = new THREE.SphereGeometry(0.065, 8, 8)
  const greenMat = new THREE.MeshBasicMaterial({ color: 0x0f8a5f })
  const orangeMat = new THREE.MeshBasicMaterial({ color: 0xff5229 })

  // Instantiate 14 call particles
  for (let i = 0; i < 14; i++) {
    const mesh = new THREE.Mesh(sphereGeom, greenMat)
    particlesGroup.add(mesh)
    flowParticles.push({
      spline: callPath,
      t: i / 14,
      speed: 0.0035 + (i % 3) * 0.0008,
      mesh,
    })
  }

  // Instantiate 12 put particles
  for (let i = 0; i < 12; i++) {
    const mesh = new THREE.Mesh(sphereGeom, orangeMat)
    particlesGroup.add(mesh)
    flowParticles.push({
      spline: putPath,
      t: i / 12,
      speed: 0.004 + (i % 2) * 0.001,
      mesh,
    })
  }

  scene.add(particlesGroup)
}

function updateCameraPosition(): void {
  if (!rootGroup || !ringsGroup) return

  // Smooth lerp to target angles
  rotY += (targetRotY - rotY) * 0.1
  rotX += (targetRotX - rotX) * 0.1

  const currentY = rotY + pointerTiltY
  const currentX = Math.max(rotXMin, Math.min(rotXMax, rotX)) + pointerTiltX

  rootGroup.rotation.y = currentY
  rootGroup.rotation.x = currentX

  if (ringsGroup) {
    ringsGroup.rotation.y = currentY * 0.75
    ringsGroup.rotation.x = currentX * 0.75
  }

  if (particlesGroup) {
    particlesGroup.rotation.y = currentY
    particlesGroup.rotation.x = currentX
  }

  // Update telemetry readouts
  const degY = Math.round((currentY * (180 / Math.PI)) % 360)
  const degX = Math.round((currentX * (180 / Math.PI)) % 360)
  telemetryAzimuth.value = `${degY}°`
  telemetryElevation.value = `${degX}°`
  telemetryGex.value = currentX > 0.4 ? '+1.42B' : '-320M'
  telemetryRegime.value = currentX > 0.4 ? 'LONG GAMMA' : 'FLIP REGIME'
}

function updateParticles(): void {
  for (const p of flowParticles) {
    p.t = (p.t + p.speed) % 1.0
    const pos = p.spline.getPointAt(p.t)
    p.mesh.position.copy(pos)
  }
}

function render(): void {
  if (!renderer || !camera || !scene) return
  updateCameraPosition()
  updateParticles()
  renderer.render(scene, camera)
}

function loop(): void {
  if (disposed) return
  animFrameId = requestAnimationFrame(loop)

  if (pageHidden || !frameVisible) return

  if (!reducedMotion && !dragging.value) {
    targetRotY += idleSpin
  }

  // Soft damping on pointer tilt
  pointerTiltX *= 0.92
  pointerTiltY *= 0.92

  render()
}

function onVisibility(): void {
  pageHidden = document.visibilityState !== 'visible'
}

function onPointerDown(e: PointerEvent): void {
  dragging.value = true
  dragPrev = { x: e.clientX, y: e.clientY }
  const target = e.currentTarget as HTMLElement
  if (target?.setPointerCapture) {
    target.setPointerCapture(e.pointerId)
  }
}

function onPointerMove(e: PointerEvent): void {
  if (dragging.value) {
    const deltaX = e.clientX - dragPrev.x
    const deltaY = e.clientY - dragPrev.y
    targetRotY += deltaX * 0.007
    targetRotX += deltaY * 0.005
    dragPrev = { x: e.clientX, y: e.clientY }
  }
}

function onPointerUp(): void {
  dragging.value = false
}

function onPointerHover(e: PointerEvent): void {
  if (dragging.value) return
  const el = containerRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  pointerTiltY = ((e.clientX - rect.left) / rect.width - 0.5) * 0.16
  pointerTiltX = ((e.clientY - rect.top) / rect.height - 0.5) * 0.1
}

function onPointerLeave(): void {
  pointerTiltX = 0
  pointerTiltY = 0
}

function setPreset(preset: 'orbit' | 'elevation' | 'matrix'): void {
  activePreset.value = preset
  if (preset === 'orbit') {
    targetRotY = -0.65
    targetRotX = 0.42
  } else if (preset === 'elevation') {
    targetRotY = -Math.PI / 2
    targetRotX = 0.08
  } else if (preset === 'matrix') {
    targetRotY = 0
    targetRotX = 1.3
  }
}

function resetView(): void {
  setPreset('orbit')
}

onMounted(() => {
  const container = containerRef.value
  if (!container) return

  reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  const width = container.clientWidth || 600
  const height = props.height || 420

  scene = new THREE.Scene()

  camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 100)
  camera.position.set(0, 2.2, 8.5)
  camera.lookAt(0, 0, 0)

  renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance',
  })
  renderer.setSize(width, height)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setClearColor(0x000000, 0)

  container.appendChild(renderer.domElement)

  // Subtle ambient illumination
  const ambient = new THREE.AmbientLight(0xffffff, 0.7)
  scene.add(ambient)

  const dirLight1 = new THREE.DirectionalLight(0x0082e6, 0.9)
  dirLight1.position.set(4, 6, 4)
  scene.add(dirLight1)

  const dirLight2 = new THREE.DirectionalLight(0xff5229, 0.7)
  dirLight2.position.set(-4, -3, -4)
  scene.add(dirLight2)

  buildTopology()
  buildEnclaveRings()
  buildFlowStreams()

  // Event handlers
  container.addEventListener('pointerdown', onPointerDown)
  container.addEventListener('pointermove', onPointerMove)
  container.addEventListener('pointermove', onPointerHover)
  container.addEventListener('pointerup', onPointerUp)
  container.addEventListener('pointerleave', onPointerLeave)
  document.addEventListener('visibilitychange', onVisibility)

  resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const cr = entry.contentRect
      if (cr.width > 0 && cr.height > 0 && renderer && camera) {
        camera.aspect = cr.width / cr.height
        camera.updateProjectionMatrix()
        renderer.setSize(cr.width, cr.height)
        render()
      }
    }
  })
  resizeObserver.observe(container)

  visibilityObserver = new IntersectionObserver(
    (entries) => {
      frameVisible = entries[0]?.isIntersecting ?? true
    },
    { threshold: 0.05 },
  )
  visibilityObserver.observe(container)

  loop()
})

onBeforeUnmount(() => {
  disposed = true
  cancelAnimationFrame(animFrameId)

  document.removeEventListener('visibilitychange', onVisibility)

  const container = containerRef.value
  if (container) {
    container.removeEventListener('pointerdown', onPointerDown)
    container.removeEventListener('pointermove', onPointerMove)
    container.removeEventListener('pointermove', onPointerHover)
    container.removeEventListener('pointerup', onPointerUp)
    container.removeEventListener('pointerleave', onPointerLeave)
  }

  resizeObserver?.disconnect()
  visibilityObserver?.disconnect()

  if (rootGroup && scene) {
    disposeObject3D(rootGroup)
    scene.remove(rootGroup)
  }
  if (ringsGroup && scene) {
    disposeObject3D(ringsGroup)
    scene.remove(ringsGroup)
  }
  if (particlesGroup && scene) {
    disposeObject3D(particlesGroup)
    scene.remove(particlesGroup)
  }
  if (scene) {
    disposeObject3D(scene)
  }

  renderer?.dispose()
  renderer?.domElement?.remove()

  scene = null
  camera = null
  renderer = null
  rootGroup = null
  ringsGroup = null
  particlesGroup = null
})
</script>

<template>
  <div
    class="waitlist-3d-model"
    role="region"
    aria-label="3D Parametric Dealer Gamma and Signed Options Flow Model"
  >
    <!-- Top HUD Banner -->
    <div class="model-hud-top">
      <div class="hud-status">
        <span class="live-pip" aria-hidden="true" />
        <span class="hud-title">3D GEX TOPOLOGY · RESEARCH ENCLAVE</span>
      </div>
      <div class="hud-controls" role="toolbar" aria-label="Camera view presets">
        <button
          type="button"
          class="hud-btn"
          :class="{ active: activePreset === 'orbit' }"
          aria-label="Orbit 3/4 perspective view"
          @click="setPreset('orbit')"
        >
          Orbit
        </button>
        <button
          type="button"
          class="hud-btn"
          :class="{ active: activePreset === 'elevation' }"
          aria-label="Elevation profile view"
          @click="setPreset('elevation')"
        >
          Profile
        </button>
        <button
          type="button"
          class="hud-btn"
          :class="{ active: activePreset === 'matrix' }"
          aria-label="Top-down strike/maturity matrix view"
          @click="setPreset('matrix')"
        >
          Matrix
        </button>
        <button
          type="button"
          class="hud-btn btn-reset"
          aria-label="Reset 3D camera orientation"
          @click="resetView"
        >
          ↺ Reset
        </button>
      </div>
    </div>

    <!-- WebGL Three.js Container -->
    <div
      ref="containerRef"
      class="canvas-viewport"
      :class="{ dragging }"
      :style="{ height: `${height}px` }"
    />

    <!-- Bottom HUD Telemetry Strip -->
    <div class="model-hud-bottom" aria-hidden="true">
      <div class="hud-telemetry">
        <span class="telem-item">
          <small>AZIMUTH</small>
          <strong>{{ telemetryAzimuth }}</strong>
        </span>
        <span class="telem-item">
          <small>ELEVATION</small>
          <strong>{{ telemetryElevation }}</strong>
        </span>
        <span class="telem-item">
          <small>NET GEX</small>
          <strong class="color-gex">{{ telemetryGex }}</strong>
        </span>
        <span class="telem-item">
          <small>STATE</small>
          <strong>{{ telemetryRegime }}</strong>
        </span>
      </div>
      <div class="hud-hint">
        <AppIcon name="flow" :size="12" />
        <span>DRAG TO ORBIT · HOVER TO TILT</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.waitlist-3d-model {
  --w3d-dark: #18181b;
  --w3d-rule: #c9c9c4;
  --w3d-rule-light: #e4e3de;
  --w3d-ink-dim: #71717a;
  --w3d-orange: #ff5229;
  --w3d-green: #0f8a5f;
  --w3d-blue: #0082e6;
  position: relative;
  width: 100%;
  background: #fbfbf8;
  border: 1px solid var(--w3d-rule);
  border-top: 2px solid var(--w3d-blue);
  overflow: hidden;
  user-select: none;
}

.waitlist-3d-model::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 50% 50%, rgba(0, 130, 230, 0.05), transparent 70%);
  pointer-events: none;
}

/* ── Top HUD ─────────────────────────────────────────────────────────────── */
.model-hud-top {
  position: absolute;
  top: 10px;
  left: 12px;
  right: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  z-index: 10;
  pointer-events: auto;
}

.hud-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid var(--w3d-rule-light);
}

.live-pip {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--w3d-green);
  box-shadow: 0 0 0 2px rgba(15, 138, 95, 0.2);
  animation: pulsePip 2.4s ease-in-out infinite;
}

@keyframes pulsePip {
  0%, 100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.6;
    transform: scale(0.85);
  }
}

.hud-title {
  font-family: var(--font-display, sans-serif);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--w3d-dark);
}

.hud-controls {
  display: flex;
  gap: 4px;
}

.hud-btn {
  min-height: 28px;
  padding: 0 8px;
  font-family: var(--font-data, monospace);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--w3d-dark);
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid var(--w3d-rule);
  cursor: pointer;
  transition: all 120ms ease;
}

.hud-btn:hover {
  background: #f0f0ea;
  border-color: #9e9d96;
}

.hud-btn:focus-visible {
  outline: 2px solid var(--w3d-blue);
  outline-offset: 1px;
}

.hud-btn.active {
  background: #09090b;
  color: #ffffff;
  border-color: #09090b;
}

.btn-reset {
  color: var(--w3d-ink-dim);
}

/* ── WebGL Canvas Viewport ───────────────────────────────────────────────── */
.canvas-viewport {
  position: relative;
  width: 100%;
  overflow: hidden;
  touch-action: none;
  cursor: grab;
}

.canvas-viewport.dragging {
  cursor: grabbing;
}

.canvas-viewport :deep(canvas) {
  display: block;
  width: 100% !important;
  height: 100% !important;
}

/* ── Bottom HUD Telemetry Strip ─────────────────────────────────────────── */
.model-hud-bottom {
  position: absolute;
  bottom: 10px;
  left: 12px;
  right: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  z-index: 10;
  pointer-events: none;
}

.hud-telemetry {
  display: flex;
  gap: 12px;
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid var(--w3d-rule-light);
}

.telem-item {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.telem-item small {
  font-family: var(--font-display, sans-serif);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--w3d-ink-dim);
  line-height: 1;
}

.telem-item strong {
  font-family: var(--font-data, monospace);
  font-size: 11px;
  font-weight: 600;
  color: var(--w3d-dark);
  line-height: 1.2;
}

.telem-item .color-gex {
  color: var(--w3d-green);
}

.hud-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid var(--w3d-rule-light);
  font-family: var(--font-display, sans-serif);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--w3d-ink-dim);
}

@media (max-width: 600px) {
  .hud-telemetry {
    display: none;
  }
  .hud-title {
    font-size: 10px;
  }
}

@media (max-width: 520px) {
  .model-hud-top {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
  .hud-controls {
    width: 100%;
    justify-content: flex-start;
    flex-wrap: wrap;
  }
}

@media (prefers-reduced-motion: reduce) {
  .live-pip {
    animation: none;
  }
}
</style>
