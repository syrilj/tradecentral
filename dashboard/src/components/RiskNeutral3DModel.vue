<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as THREE from 'three'
import type { OptionsProbability } from '@/api'
import { pctFrac, usd } from '@/format'

const props = withDefaults(
  defineProps<{
    probability: OptionsProbability | null | undefined
    spot: number
    callWall?: number | null
    putWall?: number | null
    focusPrice?: number | null
    height?: number
  }>(),
  { height: 320, callWall: null, putWall: null, focusPrice: null },
)

const containerRef = ref<HTMLDivElement | null>(null)
const probeInfo = ref<{ price: number; density: number; probAbove: number; probBelow: number } | null>(null)

let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let renderer: THREE.WebGLRenderer | null = null
let animFrameId: number | null = null

// Interaction state
let isDragging = false
let previousMousePosition = { x: 0, y: 0 }
let rotationX = 0.5
let rotationY = -0.6
let distance = 8

function cdfNormal(x: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const d = 0.3989423 * Math.exp(-x * x / 2)
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
  return x >= 0 ? 1 - p : p
}

function density(x: number, mu: number, sigma: number): number {
  if (x <= 0 || sigma <= 0) return 0
  const z = (Math.log(x) - mu) / sigma
  return (1 / (x * sigma * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * z * z)
}

function initThree() {
  if (!containerRef.value) return

  const width = containerRef.value.clientWidth || 600
  const height = props.height || 320

  scene = new THREE.Scene()
  scene.background = new THREE.Color(0x0a0b0f)

  camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000)
  updateCameraPosition()

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
  renderer.setSize(width, height)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))

  // Clean container
  containerRef.value.innerHTML = ''
  containerRef.value.appendChild(renderer.domElement)

  // Add lights
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.7)
  scene.add(ambientLight)

  /* Match flow tokens: --call #5b95b5, --put #c1955e (no green/red neon) */
  const dirLight1 = new THREE.DirectionalLight(0x5b95b5, 1.2)
  dirLight1.position.set(5, 10, 7)
  scene.add(dirLight1)

  const dirLight2 = new THREE.DirectionalLight(0xc1955e, 1.0)
  dirLight2.position.set(-5, -5, -5)
  scene.add(dirLight2)

  buildSurfaceModel()

  // Event listeners for orbit control
  const canvas = renderer.domElement
  canvas.addEventListener('mousedown', onMouseDown)
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', onMouseUp)
  canvas.addEventListener('wheel', onWheel, { passive: false })

  animate()
}

function updateCameraPosition() {
  if (!camera) return
  camera.position.x = distance * Math.sin(rotationY) * Math.cos(rotationX)
  camera.position.y = distance * Math.sin(rotationX)
  camera.position.z = distance * Math.cos(rotationY) * Math.cos(rotationX)
  camera.lookAt(0, 0, 0)
}

function buildSurfaceModel() {
  if (!scene) return

  const probability = props.probability
  const spot = props.spot
  const iv = probability?.atm_iv
  const horizon = probability?.horizon_days
  if (!probability?.available || !spot || !iv || !horizon) return

  // Remove existing meshes/lines except lights
  const toRemove: THREE.Object3D[] = []
  scene.children.forEach((c) => {
    if (!(c instanceof THREE.Light)) toRemove.push(c)
  })
  toRemove.forEach((c) => scene?.remove(c))

  const T = Math.max(horizon, 1) / 365
  const sigma = iv * Math.sqrt(T)
  const mu = Math.log(spot) - 0.5 * iv * iv * T

  // 3D Grid Plane (Ground)
  const gridHelper = new THREE.GridHelper(6, 20, 0x39404f, 0x1b1e28)
  gridHelper.position.y = -1.2
  scene.add(gridHelper)

  // Surface Geometry (Price X vs. DTE Time Z vs. Density Y)
  const nx = 40
  const nz = 25
  const geometry = new THREE.PlaneGeometry(6, 4, nx - 1, nz - 1)
  geometry.rotateX(-Math.PI / 2)

  const posAttr = geometry.attributes.position
  const colors: number[] = []

  const lowPrice = spot * 0.8
  const highPrice = spot * 1.2

  for (let i = 0; i < posAttr.count; i++) {
    const x = posAttr.getX(i) // -3 to 3
    const z = posAttr.getZ(i) // -2 to 2

    // Map x to price
    const u = (x + 3) / 6
    const price = lowPrice + u * (highPrice - lowPrice)

    // Map z to time factor
    const tScale = 0.5 + (z + 2) / 4 * 0.8
    const currSigma = sigma * tScale
    const d = density(price, mu, currSigma)

    // Height Y
    const h = d * spot * 0.6
    posAttr.setY(i, h - 1.2)

    // Color: put-side amber below spot, call-side blue above (matches flow tokens)
    const color = new THREE.Color()
    if (price < spot) {
      const t = Math.min(1, (spot - price) / (spot * 0.2))
      color.setHSL(0.09, 0.45 + 0.15 * t, 0.40 + 0.12 * Math.min(1, h / 2)) // --put family
    } else {
      const t = Math.min(1, (price - spot) / (spot * 0.2))
      color.setHSL(0.56, 0.40 + 0.15 * t, 0.42 + 0.12 * Math.min(1, h / 2)) // --call family
    }
    colors.push(color.r, color.g, color.b)
  }

  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
  geometry.computeVertexNormals()

  const material = new THREE.MeshStandardMaterial({
    vertexColors: true,
    roughness: 0.3,
    metalness: 0.2,
    wireframe: false,
    side: THREE.DoubleSide,
  })

  const mesh = new THREE.Mesh(geometry, material)
  scene.add(mesh)

  // Overlay wireframe
  const wireMat = new THREE.MeshBasicMaterial({ color: 0xa9c46c, wireframe: true, transparent: true, opacity: 0.15 })
  const wireMesh = new THREE.Mesh(geometry, wireMat)
  scene.add(wireMesh)

  // Vertical Marker Lines (Spot, Call Wall, Put Wall)
  const addMarkerLine = (price: number, colorHex: number) => {
    const u = (price - lowPrice) / (highPrice - lowPrice)
    if (u < 0 || u > 1) return
    const xPos = -3 + u * 6

    const lineMat = new THREE.LineDashedMaterial({ color: colorHex, dashSize: 0.1, gapSize: 0.05, linewidth: 2 })
    const lineGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(xPos, -1.2, 0),
      new THREE.Vector3(xPos, 2.0, 0),
    ])
    const line = new THREE.Line(lineGeo, lineMat)
    line.computeLineDistances()
    scene?.add(line)
  }

  addMarkerLine(spot, 0xffffff)
  /* Match flow call/put tokens: --call #5b95b5, --put #c1955e */
  if (props.callWall) addMarkerLine(props.callWall, 0x5b95b5)
  if (props.putWall) addMarkerLine(props.putWall, 0xc1955e)
}

function onMouseDown(e: MouseEvent) {
  isDragging = true
  previousMousePosition = { x: e.clientX, y: e.clientY }
}

function onMouseMove(e: MouseEvent) {
  if (isDragging) {
    const deltaX = e.clientX - previousMousePosition.x
    const deltaY = e.clientY - previousMousePosition.y

    rotationY += deltaX * 0.008
    rotationX = Math.max(0.1, Math.min(Math.PI / 2 - 0.05, rotationX + deltaY * 0.008))

    updateCameraPosition()
    previousMousePosition = { x: e.clientX, y: e.clientY }
  } else if (containerRef.value && scene && camera) {
    // Mouse probe over surface
    const rect = containerRef.value.getBoundingClientRect()
    const mouseX = ((e.clientX - rect.left) / rect.width) * 2 - 1
    const mouseY = -((e.clientY - rect.top) / rect.height) * 2 + 1

    const probability = props.probability
    const spot = props.spot
    const iv = probability?.atm_iv
    const horizon = probability?.horizon_days
    if (!probability?.available || !spot || !iv || !horizon) return

    const raycaster = new THREE.Raycaster()
    raycaster.setFromCamera(new THREE.Vector2(mouseX, mouseY), camera)

    const surfaceMeshes = scene.children.filter((c) => c instanceof THREE.Mesh && !(c.material as THREE.Material & { wireframe?: boolean })?.wireframe)
    const intersects = raycaster.intersectObjects(surfaceMeshes)
    if (intersects.length > 0) {
      const hit = intersects[0]
      if (hit.point) {
        const lowPrice = spot * 0.8
        const highPrice = spot * 1.2
        const u = (hit.point.x + 3) / 6
        const probedPrice = Math.max(lowPrice, Math.min(highPrice, lowPrice + u * (highPrice - lowPrice)))

        const T = Math.max(horizon, 1) / 365
        const sigma = iv * Math.sqrt(T)
        const d2 = (Math.log(spot / probedPrice) - 0.5 * sigma * sigma) / sigma
        const probAbove = cdfNormal(d2)

        probeInfo.value = {
          price: probedPrice,
          density: Math.max(0, hit.point.y + 1.2),
          probAbove,
          probBelow: 1 - probAbove,
        }
      }
    }
  }
}

function onMouseUp() {
  isDragging = false
}

function onWheel(e: WheelEvent) {
  e.preventDefault()
  distance = Math.max(3, Math.min(15, distance + e.deltaY * 0.005))
  updateCameraPosition()
}

function animate() {
  animFrameId = requestAnimationFrame(animate)
  if (renderer && scene && camera) {
    renderer.render(scene, camera)
  }
}

onMounted(() => {
  initThree()
})

watch([() => props.spot, () => props.probability, () => props.callWall, () => props.putWall], () => {
  buildSurfaceModel()
})

onBeforeUnmount(() => {
  if (animFrameId != null) cancelAnimationFrame(animFrameId)
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', onMouseUp)
  if (renderer) renderer.dispose()
})
</script>

<template>
  <div class="risk-3d-model">
    <div class="model-overlay-bar">
      <span class="label model-tag">3D RISK-NEUTRAL MODEL (INTERACTIVE)</span>
      <span class="label hint">DRAG TO ROTATE · SCROLL TO ZOOM · HOVER SURFACE TO PROBE</span>
      <div v-if="probeInfo" class="probe-tag">
        <span>PROBE: <strong class="fig">{{ usd(probeInfo.price) }}</strong></span>
        <span class="call">P(S&gt;) {{ pctFrac(probeInfo.probAbove, 0) }}</span>
        <span class="put">P(S&lt;) {{ pctFrac(probeInfo.probBelow, 0) }}</span>
      </div>
    </div>
    <div ref="containerRef" class="canvas-3d-container" :style="{ height: `${height}px` }" />
  </div>
</template>

<style scoped>
.risk-3d-model {
  position: relative;
  width: 100%;
  background: #0a0b0f;
  border: var(--hair) solid var(--rule);
  border-radius: 3px;
  overflow: hidden;
}
.model-overlay-bar {
  position: absolute;
  top: 8px;
  left: 8px;
  right: 8px;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  pointer-events: none;
  flex-wrap: wrap;
}
.model-tag {
  color: var(--phosphor);
  font: 700 10px var(--font-display);
  letter-spacing: 0.08em;
  background: rgba(14, 16, 21, 0.85);
  padding: 3px 8px;
  border: 1px solid var(--rule-hi);
  border-radius: 2px;
}
.hint {
  color: var(--ink-dim);
  font: 600 9px var(--font-display);
  background: rgba(14, 16, 21, 0.85);
  padding: 3px 8px;
  border: 1px solid var(--rule);
  border-radius: 2px;
}
.probe-tag {
  display: flex;
  align-items: center;
  gap: 8px;
  font: 700 10px var(--font-display);
  color: var(--ink);
  background: rgba(14, 16, 21, 0.92);
  border: 1px solid var(--phosphor-dim);
  padding: 3px 8px;
  border-radius: 2px;
}
.probe-tag .fig { color: var(--phosphor); }
.probe-tag .call { color: var(--call-hi); }
.probe-tag .put { color: var(--put-hi); }
.canvas-3d-container {
  width: 100%;
  cursor: grab;
}
.canvas-3d-container:active {
  cursor: grabbing;
}
</style>
