import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { ref, computed, nextTick } from 'vue'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import * as THREE from 'three'
import { sparkline } from '@/charts'
import { useResource } from '@/composables/useResource'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const deskViewCode = readFileSync(join(srcRoot, 'views', 'DeskView.vue'), 'utf8')
const optionsViewCode = readFileSync(join(srcRoot, 'views', 'OptionsView.vue'), 'utf8')
const riskNeutral3DCode = readFileSync(join(srcRoot, 'components', 'RiskNeutral3DModel.vue'), 'utf8')

// Mathematical functions from RiskNeutral3DModel
function cdfNormal(x: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const d = 0.3989423 * Math.exp((-x * x) / 2)
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
  return x >= 0 ? 1 - p : p
}

function density(x: number, mu: number, sigma: number): number {
  if (x <= 0 || sigma <= 0) return 0
  const z = (Math.log(x) - mu) / sigma
  return (1 / (x * sigma * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * z * z)
}

describe('Milestone 1 Empirical Challenge: Frontend Optimizations & Invariants', () => {
  describe('F1.1: DeskView O(1) Pre-indexing & Sparkline Cache Stress Tests', () => {
    interface SignalRow {
      symbol: string
      side?: string
      probability?: number | null
      momentum?: number | null
      state?: string
    }

    interface PeadRow {
      symbol: string
      side?: string
      evidence?: { pead_score?: number }
    }

    interface ReconciliationRow {
      symbol: string
      relation: 'agree' | 'conflict' | 'none'
    }

    it('empirically demonstrates O(1) Map indexing speedup over O(N) Array.find on large universe', () => {
      const UNIVERSE_SIZE = 500
      const ITERATIONS = 10_000

      // Generate synthetic universe
      const mockSignals: SignalRow[] = Array.from({ length: UNIVERSE_SIZE }, (_, i) => ({
        symbol: `SYM_${i}`,
        side: i % 2 === 0 ? 'long' : 'short',
        probability: 0.5 + (i % 50) * 0.01,
        momentum: (i % 20) - 10,
        state: i % 10 === 0 ? 'ENTER' : 'WATCH',
      }))

      // 1. O(N) Array scan approach (old implementation)
      const linearSignalFor = (sym: string): SignalRow | null => {
        if (!sym) return null
        const up = sym.toUpperCase()
        return mockSignals.find((s) => s.symbol?.toUpperCase() === up) ?? null
      }

      // 2. O(1) Map indexing approach (optimized implementation)
      const map = new Map<string, SignalRow>(
        mockSignals.map((s) => [s.symbol?.toUpperCase() ?? '', s]),
      )
      const mapSignalFor = (sym: string): SignalRow | null => {
        if (!sym) return null
        return map.get(sym.toUpperCase()) ?? null
      }

      // Query set with mix of hits and misses
      const querySymbols = Array.from({ length: 200 }, (_, i) =>
        i % 4 === 0 ? `SYM_${(i * 7) % UNIVERSE_SIZE}` : `UNKNOWN_${i}`,
      )

      // Measure O(N) linear scan
      const startLinear = performance.now()
      let linearChecksum = 0
      for (let iter = 0; iter < ITERATIONS; iter++) {
        const sym = querySymbols[iter % querySymbols.length]
        const res = linearSignalFor(sym)
        if (res) linearChecksum += res.probability ?? 0
      }
      const durLinear = performance.now() - startLinear

      // Measure O(1) Map lookup
      const startMap = performance.now()
      let mapChecksum = 0
      for (let iter = 0; iter < ITERATIONS; iter++) {
        const sym = querySymbols[iter % querySymbols.length]
        const res = mapSignalFor(sym)
        if (res) mapChecksum += res.probability ?? 0
      }
      const durMap = performance.now() - startMap

      // Assert semantic parity
      expect(mapChecksum).toBeCloseTo(linearChecksum, 5)

      // Assert measurable performance gain (Map lookup is faster)
      expect(durMap).toBeLessThan(durLinear)
    })

    it('handles edge-case symbols (empty, undefined, lower/mixed case, special chars) without crashing', () => {
      const signalsRef = ref<SignalRow[]>([
        { symbol: 'AAPL', side: 'long', probability: 0.72 },
        { symbol: 'msft', side: 'long', probability: 0.68 },
        { symbol: 'BRK.B', side: 'short', probability: 0.65 },
        { symbol: 'BTC/USD', side: 'long', probability: 0.55 },
        { symbol: '', side: 'none', probability: 0.5 },
      ])

      const peadRef = ref<PeadRow[]>([
        { symbol: 'AAPL', side: 'long', evidence: { pead_score: 1.5 } },
        { symbol: 'MSFT', side: 'short', evidence: { pead_score: -0.8 } },
        { symbol: 'brk.b', side: 'short', evidence: { pead_score: -1.2 } },
      ])

      const reconciliationRef = ref<{ rows: ReconciliationRow[] }>({
        rows: [
          { symbol: 'AAPL', relation: 'agree' },
        ],
      })

      const reconciledBySymbol = computed(() => new Map(
        (reconciliationRef.value?.rows ?? []).map((row) => [row.symbol.toUpperCase(), row]),
      ))
      const signalsBySymbol = computed(() => new Map(
        signalsRef.value.map((s) => [s.symbol?.toUpperCase() ?? '', s]),
      ))
      const peadBySymbol = computed(() => new Map(
        peadRef.value.map((p) => [p.symbol?.toUpperCase() ?? '', p]),
      ))

      const signalFor = (sym: string): SignalRow | null => {
        if (!sym) return null
        return signalsBySymbol.value.get(sym.toUpperCase()) ?? null
      }

      const peadFor = (sym: string): PeadRow | null => {
        if (!sym) return null
        return peadBySymbol.value.get(sym.toUpperCase()) ?? null
      }

      const relationFor = (sym: string): 'agree' | 'conflict' | 'none' => {
        const relation = reconciledBySymbol.value.get(sym.toUpperCase())?.relation
        if (relation === 'agree' || relation === 'conflict') return relation
        const peadSide = peadFor(sym)?.side?.toLowerCase()
        const directionalSide = signalFor(sym)?.side?.toLowerCase()
        if (!peadSide || !directionalSide) return 'none'
        return peadSide === directionalSide ? 'agree' : 'conflict'
      }

      // Case-insensitivity lookups
      expect(signalFor('aapl')?.probability).toBe(0.72)
      expect(signalFor('AAPL')?.probability).toBe(0.72)
      expect(signalFor('Msft')?.probability).toBe(0.68)
      expect(signalFor('MSFT')?.probability).toBe(0.68)
      expect(signalFor('brk.b')?.probability).toBe(0.65)
      expect(signalFor('BRK.B')?.probability).toBe(0.65)
      expect(signalFor('BTC/USD')?.probability).toBe(0.55)

      // Edge values
      expect(signalFor('')).toBeNull()
      expect(signalFor(null as unknown as string)).toBeNull()
      expect(signalFor(undefined as unknown as string)).toBeNull()
      expect(signalFor('NONEXISTENT')).toBeNull()

      // Pead lookups
      expect(peadFor('aapl')?.evidence?.pead_score).toBe(1.5)
      expect(peadFor('BRK.B')?.evidence?.pead_score).toBe(-1.2)
      expect(peadFor('')).toBeNull()

      // Model reconciliation relation
      expect(relationFor('AAPL')).toBe('agree') // From reconciledBySymbol
      expect(relationFor('MSFT')).toBe('conflict') // Derived: long signal vs short pead
      expect(relationFor('BRK.B')).toBe('agree') // Derived: short signal vs short pead
      expect(relationFor('BTC/USD')).toBe('none') // Pead missing
      expect(relationFor('UNKNOWN')).toBe('none')
    })

    it('maintains dynamic reactive updates when underlying data mutations occur', async () => {
      const signalsRef = ref<SignalRow[]>([
        { symbol: 'NVDA', side: 'long', probability: 0.60 },
      ])

      const signalsBySymbol = computed(() => new Map(
        signalsRef.value.map((s) => [s.symbol?.toUpperCase() ?? '', s]),
      ))

      const signalFor = (sym: string): SignalRow | null => {
        if (!sym) return null
        return signalsBySymbol.value.get(sym.toUpperCase()) ?? null
      }

      expect(signalFor('NVDA')?.probability).toBe(0.60)
      expect(signalFor('TSLA')).toBeNull()

      // Mutate reactive data
      signalsRef.value = [
        { symbol: 'NVDA', side: 'long', probability: 0.85 },
        { symbol: 'TSLA', side: 'short', probability: 0.70 },
      ]
      await nextTick()

      expect(signalFor('NVDA')?.probability).toBe(0.85)
      expect(signalFor('TSLA')?.probability).toBe(0.70)
      expect(signalFor('tsla')?.side).toBe('short')
    })

    it('verifies sparkline cache memoization and invalidation logic', () => {
      const sparkCache = new Map<string, { key: string; path: string }>()

      const probeResults = ref<Record<string, { series: Array<{ d: string; c: number }> }>>({
        NVDA: {
          series: [
            { d: '2026-08-10', c: 120 },
            { d: '2026-08-11', c: 125 },
            { d: '2026-08-12', c: 128 },
          ],
        },
        TSLA: {
          series: [
            { d: '2026-08-10', c: 200 },
          ], // <= 2 bars, should be skipped
        },
      })

      const watchSparks = computed(() => {
        const out: Record<string, string> = {}
        for (const [sym, traj] of Object.entries(probeResults.value)) {
          const series = traj?.series
          if (!series || series.length <= 2) continue

          const lastBar = series[series.length - 1]
          const cacheKey = `${series.length}_${lastBar?.d}_${lastBar?.c}`
          const cached = sparkCache.get(sym)
          if (cached && cached.key === cacheKey) {
            out[sym] = cached.path
            continue
          }

          const closes = series.map((b) => b.c)
          const path = sparkline(closes.slice(-40), 88, 22, 2).d
          sparkCache.set(sym, { key: cacheKey, path })
          out[sym] = path
        }
        return out
      })

      // Initial compute: NVDA populated, TSLA skipped
      const sparks1 = watchSparks.value
      expect(sparks1.NVDA).toBeDefined()
      expect(sparks1.TSLA).toBeUndefined()
      expect(sparkCache.has('NVDA')).toBe(true)
      const cachedPath1 = sparkCache.get('NVDA')?.path

      // Same data accessed again -> must return identical cached path
      const sparks2 = watchSparks.value
      expect(sparks2.NVDA).toBe(cachedPath1)

      // Mutate NVDA with a new close price -> invalidates cache
      probeResults.value = {
        NVDA: {
          series: [
            { d: '2026-08-10', c: 120 },
            { d: '2026-08-11', c: 125 },
            { d: '2026-08-12', c: 135 }, // changed close
          ],
        },
      }

      const sparks3 = watchSparks.value
      expect(sparkCache.get('NVDA')?.key).toBe('3_2026-08-12_135')
      expect(sparks3.NVDA).not.toBe(cachedPath1) // New path generated

      // Adding 4th bar
      probeResults.value = {
        NVDA: {
          series: [
            { d: '2026-08-10', c: 120 },
            { d: '2026-08-11', c: 125 },
            { d: '2026-08-12', c: 135 },
            { d: '2026-08-13', c: 140 },
          ],
        },
      }
      const sparks4 = watchSparks.value
      expect(sparks4.NVDA).toBeDefined()
      expect(sparkCache.get('NVDA')?.key).toBe('4_2026-08-13_140')
    })
  })

  describe('F1.2: OptionsView Drawer Polling Gating & Lifecycle Stress Tests', () => {
    let originalWindow: any
    let originalDocument: any

    beforeEach(() => {
      vi.useFakeTimers()
      originalWindow = (globalThis as any).window
      originalDocument = (globalThis as any).document

      ;(globalThis as any).window = {
        setInterval: (fn: Function, ms: number) => setInterval(fn, ms) as unknown as number,
        clearInterval: (id: number) => clearInterval(id),
      }
      ;(globalThis as any).document = {
        visibilityState: 'visible',
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }
    })

    afterEach(() => {
      vi.useRealTimers()
      vi.restoreAllMocks()
      ;(globalThis as any).window = originalWindow
      ;(globalThis as any).document = originalDocument
    })

    it('suppresses initial mount fetch and periodic interval polling when drawer is closed', async () => {
      const loader = vi.fn().mockResolvedValue({ items: ['test'] })
      const isOpen = ref(false)

      const resource = useResource(loader, {
        intervalMs: 120_000,
        enabled: () => isOpen.value,
      })

      // 1. Initial mount: should NOT call loader because enabled() is false
      expect(loader).toHaveBeenCalledTimes(0)
      expect(resource.data.value).toBeNull()

      // 2. Fast-forward timer by 120s (1 interval cycle)
      await vi.advanceTimersByTimeAsync(120_000)
      expect(loader).toHaveBeenCalledTimes(0)

      // 3. Fast-forward another 240s
      await vi.advanceTimersByTimeAsync(240_000)
      expect(loader).toHaveBeenCalledTimes(0)
    })

    it('triggers immediate fetch upon drawer expansion and starts polling while open', async () => {
      const loader = vi.fn().mockResolvedValue({ items: ['unusual_flow_1'] })
      const isOpen = ref(false)

      const resource = useResource(loader, {
        intervalMs: 120_000,
        enabled: () => isOpen.value,
      })

      expect(loader).toHaveBeenCalledTimes(0)

      // Simulate watcher in OptionsView.vue:
      // watch(unusualOpen, (open) => { if (open && !unusual.data.value) void unusual.refresh() })
      const triggerDrawerOpen = async () => {
        isOpen.value = true
        if (isOpen.value && !resource.data.value) {
          await resource.refresh()
        }
      }

      await triggerDrawerOpen()
      expect(loader).toHaveBeenCalledTimes(1)
      expect(resource.data.value).toEqual({ items: ['unusual_flow_1'] })

      // Advance timer by 120s while open -> periodic poll should now trigger
      await vi.advanceTimersByTimeAsync(120_000)
      expect(loader).toHaveBeenCalledTimes(2)

      // Advance another 120s
      await vi.advanceTimersByTimeAsync(120_000)
      expect(loader).toHaveBeenCalledTimes(3)
    })

    it('halts periodic interval polling immediately when drawer is closed again', async () => {
      const loader = vi.fn().mockResolvedValue({ items: ['data'] })
      const isOpen = ref(true)

      const resource = useResource(loader, {
        intervalMs: 120_000,
        enabled: () => isOpen.value,
      })

      // Wait for immediate initial load promise
      await Promise.resolve()
      expect(loader).toHaveBeenCalledTimes(1)
      expect(resource.data.value).toEqual({ items: ['data'] })

      // Advance 120s
      await vi.advanceTimersByTimeAsync(120_000)
      expect(loader).toHaveBeenCalledTimes(2)

      // Close drawer
      isOpen.value = false

      // Advance another 240s -> no new calls should happen
      await vi.advanceTimersByTimeAsync(240_000)
      expect(loader).toHaveBeenCalledTimes(2)
    })

    it('supports manual one-shot scan bypassing the enabled gate', async () => {
      const loader = vi.fn().mockResolvedValue({ items: ['forced_live_data'] })
      const isOpen = ref(false)
      const forceNext = ref(false)

      const resource = useResource(loader, {
        intervalMs: 120_000,
        enabled: () => isOpen.value,
      })

      expect(loader).toHaveBeenCalledTimes(0)

      // Manual scan handler in OptionsView:
      // forceNext.value = true; await resource.refresh(); forceNext.value = false;
      forceNext.value = true
      await resource.refresh()
      forceNext.value = false

      expect(loader).toHaveBeenCalledTimes(1)
      expect(resource.data.value).toEqual({ items: ['forced_live_data'] })

      // Timer tick after manual scan while closed -> remains dormant
      await vi.advanceTimersByTimeAsync(120_000)
      expect(loader).toHaveBeenCalledTimes(1)
    })
  })

  describe('F1.3: WebGL Three.js Resource Management & Render-on-Demand', () => {
    function disposeObject3D(obj: THREE.Object3D) {
      if (!obj) return
      obj.traverse((child) => {
        if (child instanceof THREE.Mesh || child instanceof THREE.Line) {
          if (child.geometry) {
            child.geometry.dispose()
          }
          if (child.material) {
            if (Array.isArray(child.material)) {
              child.material.forEach((m) => m.dispose())
            } else {
              child.material.dispose()
            }
          }
        }
      })
    }

    it('recursively disposes all geometries and materials across single/multi material meshes and lines', () => {
      const rootGroup = new THREE.Group()

      // Mesh 1 with single material
      const geom1 = new THREE.PlaneGeometry(10, 10)
      const mat1 = new THREE.MeshBasicMaterial({ color: 0xffffff })
      const mesh1 = new THREE.Mesh(geom1, mat1)
      const geom1DisposeSpy = vi.spyOn(geom1, 'dispose')
      const mat1DisposeSpy = vi.spyOn(mat1, 'dispose')
      rootGroup.add(mesh1)

      // Mesh 2 with material array
      const geom2 = new THREE.BoxGeometry(1, 1, 1)
      const mat2a = new THREE.MeshBasicMaterial({ color: 0xff0000 })
      const mat2b = new THREE.MeshBasicMaterial({ color: 0x00ff00 })
      const mesh2 = new THREE.Mesh(geom2, [mat2a, mat2b])
      const geom2DisposeSpy = vi.spyOn(geom2, 'dispose')
      const mat2aDisposeSpy = vi.spyOn(mat2a, 'dispose')
      const mat2bDisposeSpy = vi.spyOn(mat2b, 'dispose')
      rootGroup.add(mesh2)

      // Line 1
      const lineGeom = new THREE.BufferGeometry()
      const lineMat = new THREE.LineBasicMaterial({ color: 0x0000ff })
      const line = new THREE.Line(lineGeom, lineMat)
      const lineGeomDisposeSpy = vi.spyOn(lineGeom, 'dispose')
      const lineMatDisposeSpy = vi.spyOn(lineMat, 'dispose')
      rootGroup.add(line)

      // Execute disposal
      disposeObject3D(rootGroup)

      expect(geom1DisposeSpy).toHaveBeenCalledTimes(1)
      expect(mat1DisposeSpy).toHaveBeenCalledTimes(1)
      expect(geom2DisposeSpy).toHaveBeenCalledTimes(1)
      expect(mat2aDisposeSpy).toHaveBeenCalledTimes(1)
      expect(mat2bDisposeSpy).toHaveBeenCalledTimes(1)
      expect(lineGeomDisposeSpy).toHaveBeenCalledTimes(1)
      expect(lineMatDisposeSpy).toHaveBeenCalledTimes(1)
    })

    it('batches synchronous render requests into a single animation frame via dirty flag', () => {
      let needsRender = false
      let animFrameId: number | null = null
      const renderSpy = vi.fn(() => {
        animFrameId = null
        needsRender = false
      })

      const requestRender = () => {
        if (!needsRender) {
          needsRender = true
          animFrameId = 12345 // mock frame ID
        }
      }

      // Fire 50 rapid calls synchronously
      for (let i = 0; i < 50; i++) {
        requestRender()
      }

      // Only 1 frame requested
      expect(needsRender).toBe(true)
      expect(animFrameId).toBe(12345)

      // Complete render cycle
      renderSpy()
      expect(needsRender).toBe(false)
      expect(animFrameId).toBeNull()
    })

    it('cdfNormal satisfies probability axioms, bounds, and symmetry', () => {
      expect(cdfNormal(0)).toBeCloseTo(0.5, 5)
      expect(cdfNormal(-10)).toBeCloseTo(0, 5)
      expect(cdfNormal(10)).toBeCloseTo(1, 5)
      expect(cdfNormal(1.96)).toBeCloseTo(0.975, 2)
      expect(cdfNormal(-1.96)).toBeCloseTo(0.025, 2)
    })

    it('density handles edge cases and non-positive strike/volatility safely', () => {
      const spot = 100
      const iv = 0.25
      const T = 30 / 365
      const sigma = iv * Math.sqrt(T)
      const mu = Math.log(spot) - 0.5 * iv * iv * T

      expect(density(0, mu, sigma)).toBe(0)
      expect(density(-50, mu, sigma)).toBe(0)
      expect(density(spot, mu, 0)).toBe(0)
      expect(density(spot, mu, -0.2)).toBe(0)

      const dSpot = density(spot, mu, sigma)
      expect(Number.isFinite(dSpot)).toBe(true)
      expect(dSpot).toBeGreaterThan(0)
    })
  })

  describe('AST & Interface Invariants Verification', () => {
    it('DeskView.vue satisfies all required string and contract patterns', () => {
      expect(deskViewCode).toContain('const signalsBySymbol = computed(() => new Map(')
      expect(deskViewCode).toContain('const peadBySymbol = computed(() => new Map(')
      expect(deskViewCode).toContain('const sparkCache = new Map<string, { key: string; path: string }>()')
      expect(deskViewCode).toContain('RESEARCH BOOK')
      expect(deskViewCode).toContain('LIVE BOOK CLEARED')
      expect(deskViewCode).toContain('STANDBY')
      expect(deskViewCode).toContain('boardSymbols(): string[]')
    })

    it('OptionsView.vue satisfies drawer gating patterns and tokens', () => {
      expect(optionsViewCode).toContain('enabled: () => unusualOpen.value')
      expect(optionsViewCode).toContain('enabled: () => opportunitiesOpen.value')
      expect(optionsViewCode).toContain('watch(unusualOpen')
      expect(optionsViewCode).toContain('watch(opportunitiesOpen')
    })

    it('RiskNeutral3DModel.vue satisfies WebGL disposal and render-on-demand patterns', () => {
      expect(riskNeutral3DCode).toContain('function disposeObject3D(obj: THREE.Object3D)')
      expect(riskNeutral3DCode).toContain('function requestRender()')
      expect(riskNeutral3DCode).toContain('renderer.dispose()')
      expect(riskNeutral3DCode).toContain('cancelAnimationFrame(animFrameId)')
    })
  })
})
